from __future__ import annotations

import asyncio
import signal
import time
from pathlib import Path
from typing import Any

import pytest

from browser_automation.errors import BrowserError
from browser_automation.recording.ffmpeg import (
    build_ffmpeg_args,
    even_dimensions,
    jpeg_dimensions,
    resolve_ffmpeg,
)
from browser_automation.recording.service import WORKER_MODULE, RecordingService
from browser_automation.recording.state import RecordingFiles, read_json, write_json_atomic
from browser_automation.recording.worker import FrameSource, StopSignal, pump_frames


def jpeg_header(width: int, height: int) -> bytes:
    app0 = b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof0 = b"\xff\xc0\x00\x11\x08" + height.to_bytes(2, "big") + width.to_bytes(2, "big") + b"\x03" + b"\x00" * 9
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xd9"


def test_jpeg_dimensions_and_even_rounding() -> None:
    assert jpeg_dimensions(jpeg_header(2401, 1537)) == (2401, 1537)
    assert even_dimensions(2401, 1537) == (2400, 1536)
    with pytest.raises(ValueError):
        jpeg_dimensions(b"not a jpeg")


def test_ffmpeg_arguments_encode_constant_rate_h264_mp4(tmp_path: Path) -> None:
    args = build_ffmpeg_args(Path("/usr/bin/ffmpeg"), fps=25, width=1280, height=800, output=tmp_path / ".x.tmp")
    joined = " ".join(args)
    assert args[0] == "/usr/bin/ffmpeg"
    for fragment in (
        "-f image2pipe -framerate 25 -c:v mjpeg -i -",
        "scale=1280:800:force_original_aspect_ratio=decrease,pad=1280:800:(ow-iw)/2:(oh-ih)/2",
        "-c:v libx264 -preset veryfast -pix_fmt yuv420p -movflags +faststart -f mp4",
    ):
        assert fragment in joined
    assert args[-1] == str(tmp_path / ".x.tmp")


def test_ffmpeg_resolution(tmp_path: Path) -> None:
    fake = tmp_path / "ffmpeg"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    fake.chmod(0o755)
    assert resolve_ffmpeg({"BROWSER_AUTOMATION_FFMPEG_BIN": str(fake)}) == fake.resolve()
    assert resolve_ffmpeg({"PATH": str(tmp_path)}) == fake.resolve()
    for env in ({"BROWSER_AUTOMATION_FFMPEG_BIN": str(tmp_path / "missing")}, {"PATH": str(tmp_path / "empty")}):
        with pytest.raises(BrowserError) as raised:
            resolve_ffmpeg(env)
        assert raised.value.code == "RECORDING_DEPENDENCY_MISSING"
        assert raised.value.exit_status == 3


class FakeStdin:
    def __init__(self, stop: StopSignal, stop_after: int) -> None:
        self.frames: list[bytes] = []
        self._stop = stop
        self._stop_after = stop_after

    def write(self, data: bytes) -> None:
        self.frames.append(data)

    async def drain(self) -> None:
        if len(self.frames) >= self._stop_after:
            self._stop.trigger("stopped")


class ShiftedClock:
    """Real monotonic time plus an adjustable offset, to simulate an encoder stall."""

    def __init__(self) -> None:
        self.offset = 0.0

    def __call__(self) -> float:
        return time.monotonic() + self.offset


@pytest.mark.anyio
async def test_frame_pump_writes_the_latest_frame_at_a_constant_rate() -> None:
    frames = FrameSource()
    frames.push(b"frame-1")
    stop = StopSignal()
    stdin = FakeStdin(stop, stop_after=10)

    written, duration = await pump_frames(frames, stdin, 50, stop)

    assert written == len(stdin.frames) >= 10
    assert set(stdin.frames) == {b"frame-1"}
    assert duration == pytest.approx(written / 50)


@pytest.mark.anyio
async def test_frame_pump_catches_up_at_most_one_second_after_a_stall() -> None:
    frames = FrameSource()
    frames.push(b"f")
    stop = StopSignal()
    clock = ShiftedClock()

    class StallingStdin(FakeStdin):
        async def drain(self) -> None:
            if len(self.frames) == 1:
                clock.offset += 5.0  # the encoder stalled for five seconds
            elif len(self.frames) >= 1 + 10 + 3:
                self._stop.trigger("stopped")

    stdin = StallingStdin(stop, stop_after=0)
    written, duration = await pump_frames(frames, stdin, 10, stop, clock=clock)
    # 50 ticks were missed; only one second (10 frames) of backlog is repeated, the rest is dropped.
    assert written == len(stdin.frames) == 14
    assert duration == pytest.approx(1.4)


def test_recording_files_are_keyed_by_port_and_tab(tmp_path: Path) -> None:
    files = RecordingFiles.for_tab(tmp_path, 9333, "ABCDEF0123")
    assert files.state == tmp_path / "recordings" / "9333-ABCDEF0123.json"
    odd = RecordingFiles.for_tab(tmp_path, 9333, "weird/id")
    assert "/" not in odd.state.name and odd.state.parent == tmp_path / "recordings"
    files.ensure_directory()
    write_json_atomic(files.state, {"a": 1})
    assert read_json(files.state) == {"a": 1}
    assert (files.state.stat().st_mode & 0o777) == 0o600
    assert (files.state.parent.stat().st_mode & 0o777) == 0o700


class FakeProcess:
    def __init__(self, pid: int, on_start: Any) -> None:
        self.pid = pid
        self.killed = False
        self.returncode: int | None = None
        on_start(self)

    def poll(self) -> int | None:
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self) -> int | None:
        return self.returncode


class WorkerFixture:
    """Fake worker processes: records spawned commands and simulates their files and liveness."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        ffmpeg = tmp_path / "bin" / "ffmpeg"
        ffmpeg.parent.mkdir()
        ffmpeg.write_text("#!/bin/sh\n", encoding="utf-8")
        ffmpeg.chmod(0o755)
        self.env = {"BROWSER_AUTOMATION_FFMPEG_BIN": str(ffmpeg)}
        self.alive: dict[int, str] = {}
        self.signals: list[tuple[str, int, int]] = []
        self.commands: list[list[str]] = []
        self.ready: dict[str, Any] | None = {"ok": True, "started_at": "t"}
        self.status_on_term: dict[str, Any] | None = None
        self.next_pid = 5000

    def service(self) -> RecordingService:
        return RecordingService(
            runtime_dir=self.tmp_path / "runtime",
            env=self.env,
            process_factory=self.spawn,
            read_command=lambda pid: self.alive.get(pid),
            is_alive=lambda pid: pid in self.alive,
            signal_process=self.on_signal,
            signal_group=lambda pid, sig: self.signals.append(("group", pid, sig)),
            ready_timeout=1.0,
            status_timeout=1.0,
        )

    def spawn(self, command: list[str], **kwargs: Any) -> FakeProcess:
        assert kwargs["start_new_session"] is True
        self.commands.append(command)
        pid = self.next_pid
        self.next_pid += 1
        ready_file = Path(command[command.index("--ready-file") + 1])

        def on_start(process: FakeProcess) -> None:
            self.alive[pid] = " ".join(command)
            if self.ready is not None:
                write_json_atomic(ready_file, self.ready)
            else:
                del self.alive[pid]
                process.returncode = 1

        return FakeProcess(pid, on_start)

    def on_signal(self, pid: int, sig: int) -> None:
        self.signals.append(("process", pid, sig))
        command = self.alive.pop(pid)
        parts = command.split(" ")
        status_file = Path(parts[parts.index("--status-file") + 1])
        if self.status_on_term is not None:
            write_json_atomic(status_file, self.status_on_term)


async def start(service: RecordingService, tmp_path: Path, tab_id: str = "TAB1") -> dict[str, Any]:
    return await service.start(
        endpoint="http://127.0.0.1:9333",
        port=9333,
        tab_id=tab_id,
        output=tmp_path / "clip.mp4",
        temp=tmp_path / ".clip.mp4.tmp",
        fps=25,
        overwrite=False,
    )


@pytest.mark.anyio
async def test_start_spawns_detached_worker_with_own_interpreter_and_records_state(tmp_path: Path) -> None:
    import sys

    fixture = WorkerFixture(tmp_path)
    service = fixture.service()

    result = await start(service, tmp_path)

    assert result["tab_id"] == "TAB1" and result["output_file"] == str(tmp_path / "clip.mp4") and result["fps"] == 25
    command = fixture.commands[0]
    assert command[:3] == [sys.executable, "-m", WORKER_MODULE]
    assert command[command.index("--endpoint") + 1] == "http://127.0.0.1:9333"
    state = read_json(RecordingFiles.for_tab(tmp_path / "runtime", 9333, "TAB1").state)
    assert state["worker_pid"] == 5000 and state["endpoint_port"] == 9333 and state["tab_id"] == "TAB1"
    assert state["worker_marker"] in " ".join(command)

    with pytest.raises(BrowserError) as raised:
        await start(service, tmp_path)
    assert raised.value.code == "RECORDING_ALREADY_ACTIVE"


@pytest.mark.anyio
async def test_start_reports_worker_start_failures(tmp_path: Path) -> None:
    fixture = WorkerFixture(tmp_path)
    service = fixture.service()
    fixture.ready = {"ok": False, "error": {"code": "TAB_NOT_FOUND", "message": "gone"}}
    with pytest.raises(BrowserError) as raised:
        await start(service, tmp_path)
    assert raised.value.code == "TAB_NOT_FOUND" and raised.value.exit_status == 4

    fixture.ready = None
    with pytest.raises(BrowserError) as raised:
        await start(service, tmp_path)
    assert raised.value.code == "RECORDING_FAILED"
    assert not RecordingFiles.for_tab(tmp_path / "runtime", 9333, "TAB1").state.exists()


@pytest.mark.anyio
async def test_stop_signals_verified_worker_and_reports_the_artifact(tmp_path: Path) -> None:
    fixture = WorkerFixture(tmp_path)
    service = fixture.service()
    await start(service, tmp_path)
    fixture.status_on_term = {
        "state": "completed", "end_reason": "stopped", "output_file": str(tmp_path / "clip.mp4"),
        "duration_seconds": 4.2, "frames": 105, "bytes_written": 1234,
    }

    result = await service.stop(port=9333, tab_id="TAB1")

    assert fixture.signals == [("process", 5000, signal.SIGTERM)]
    assert result == {
        "tab_id": "TAB1",
        "artifact": {"path": str(tmp_path / "clip.mp4"), "media_type": "video/mp4", "bytes_written": 1234},
        "duration_seconds": 4.2,
        "frames": 105,
        "end_reason": "stopped",
    }
    with pytest.raises(BrowserError) as raised:
        await service.stop(port=9333, tab_id="TAB1")
    assert raised.value.code == "RECORDING_NOT_ACTIVE" and raised.value.exit_status == 4


@pytest.mark.anyio
async def test_stop_reports_a_recording_that_already_ended_without_signalling(tmp_path: Path) -> None:
    fixture = WorkerFixture(tmp_path)
    service = fixture.service()
    await start(service, tmp_path)
    files = RecordingFiles.for_tab(tmp_path / "runtime", 9333, "TAB1")
    write_json_atomic(files.status, {
        "state": "completed", "end_reason": "target_closed", "output_file": "o.mp4",
        "duration_seconds": 1.0, "frames": 25, "bytes_written": 9,
    })
    fixture.alive.clear()

    result = await service.stop(port=9333, tab_id="TAB1")

    assert result["end_reason"] == "target_closed"
    assert fixture.signals == []


@pytest.mark.anyio
async def test_stop_never_signals_a_reused_pid_and_reports_failures(tmp_path: Path) -> None:
    fixture = WorkerFixture(tmp_path)
    service = fixture.service()
    await start(service, tmp_path)
    fixture.alive[5000] = "/usr/bin/unrelated --process"

    with pytest.raises(BrowserError) as raised:
        await service.stop(port=9333, tab_id="TAB1")

    assert raised.value.code == "RECORDING_FAILED"
    assert fixture.signals == []

    await start(service, tmp_path, tab_id="TAB2")
    fixture.status_on_term = {
        "state": "failed", "end_reason": "error", "output_file": "o.mp4", "partial_file": "/w/clip.partial.mp4",
        "error": {"code": "RECORDING_FAILED", "message": "ffmpeg crashed"},
    }
    with pytest.raises(BrowserError) as raised:
        await service.stop(port=9333, tab_id="TAB2")
    assert raised.value.code == "RECORDING_FAILED" and raised.value.exit_status == 5
    assert raised.value.details["partial_file"] == "/w/clip.partial.mp4"
    assert "ffmpeg crashed" in raised.value.message


@pytest.mark.anyio
async def test_stop_forces_the_worker_group_when_no_status_arrives(tmp_path: Path) -> None:
    fixture = WorkerFixture(tmp_path)
    service = fixture.service()
    await start(service, tmp_path)

    def ignore_term(pid: int, sig: int) -> None:
        fixture.signals.append(("process", pid, sig))

    service._signal_process = ignore_term  # type: ignore[attr-defined]

    with pytest.raises(BrowserError) as raised:
        await service.stop(port=9333, tab_id="TAB1")

    assert raised.value.code == "RECORDING_FAILED"
    assert fixture.signals == [("process", 5000, signal.SIGTERM), ("group", 5000, signal.SIGKILL)]
    assert asyncio.get_running_loop()
