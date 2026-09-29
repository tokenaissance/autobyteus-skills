"""Recording lifecycle across short-lived CLI/MCP calls: one detached worker per (port, tab)."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from browser_automation.errors import (
    BrowserError,
    recording_already_active,
    recording_failed,
    recording_not_active,
)
from browser_automation.recording.ffmpeg import resolve_ffmpeg
from browser_automation.recording.state import (
    RECORDING_SCHEMA_VERSION,
    RecordingFiles,
    read_json,
    write_json_atomic,
)
from browser_automation.runtime import default_runtime_directory

WORKER_MODULE = "browser_automation.recording.worker"
READY_TIMEOUT_SECONDS = 20.0
STATUS_TIMEOUT_SECONDS = 60.0
POLL_SECONDS = 0.1
LOG_TAIL_LINES = 20

ProcessFactory = Callable[..., subprocess.Popen[Any]]
CommandReader = Callable[[int], str | None]


def _read_process_command(pid: int) -> str | None:
    try:
        completed = subprocess.run(
            ["ps", "-o", "command=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() or None


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _log_tail(path: Path) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-LOG_TAIL_LINES:])
    except OSError:
        return ""


class RecordingService:
    """Own recording state, the ffmpeg check, and the worker's spawn, identity and stop."""

    def __init__(
        self,
        *,
        runtime_dir: Path | None = None,
        env: Mapping[str, str] | None = None,
        process_factory: ProcessFactory = subprocess.Popen,
        read_command: CommandReader = _read_process_command,
        is_alive: Callable[[int], bool] = _process_alive,
        signal_process: Callable[[int, int], None] = os.kill,
        signal_group: Callable[[int, int], None] = os.killpg,
        ready_timeout: float = READY_TIMEOUT_SECONDS,
        status_timeout: float = STATUS_TIMEOUT_SECONDS,
    ) -> None:
        self._runtime_dir = runtime_dir
        self._env = env
        self._process_factory = process_factory
        self._read_command = read_command
        self._is_alive = is_alive
        self._signal_process = signal_process
        self._signal_group = signal_group
        self._ready_timeout = ready_timeout
        self._status_timeout = status_timeout

    def _files(self, port: int, tab_id: str) -> RecordingFiles:
        return RecordingFiles.for_tab(self._runtime_dir or default_runtime_directory(), port, tab_id)

    def _worker_running(self, state: Mapping[str, Any]) -> bool:
        """Identity guard: the recorded pid is alive and still runs this recording's worker."""

        pid = state.get("worker_pid")
        marker = state.get("worker_marker")
        if not isinstance(pid, int) or not isinstance(marker, str) or not self._is_alive(pid):
            return False
        command = self._read_command(pid)
        return bool(command and WORKER_MODULE in command and marker in command)

    async def start(
        self,
        *,
        endpoint: str,
        port: int,
        tab_id: str,
        output: Path,
        temp: Path,
        fps: int,
        overwrite: bool,
    ) -> dict[str, Any]:
        ffmpeg = resolve_ffmpeg(self._env)
        files = self._files(port, tab_id)
        files.ensure_directory()
        previous = read_json(files.state)
        if previous is not None and self._worker_running(previous):
            raise recording_already_active(tab_id)
        # A finished recording that was never stopped is superseded by the new one.
        files.clear()

        command = [
            sys.executable, "-m", WORKER_MODULE,
            "--endpoint", endpoint,
            "--tab-id", tab_id,
            "--fps", str(fps),
            "--ffmpeg", str(ffmpeg),
            "--temp-file", str(temp),
            "--output-file", str(output),
            "--ready-file", str(files.ready),
            "--status-file", str(files.status),
        ] + (["--overwrite"] if overwrite else [])
        with files.log.open("ab") as log:
            process = self._process_factory(
                command,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
                env=dict(self._env) if self._env is not None else None,
            )
        started_at = datetime.now(timezone.utc).isoformat()
        write_json_atomic(files.state, {
            "schema_version": RECORDING_SCHEMA_VERSION,
            "endpoint_port": port,
            "tab_id": tab_id,
            "worker_pid": process.pid,
            "worker_marker": str(files.status),
            "output_file": str(output),
            "temp_file": str(temp),
            "status_file": str(files.status),
            "fps": fps,
            "started_at": started_at,
        })

        ready = await self._wait_for_ready(files, process)
        if ready is None or not ready.get("ok"):
            self._abandon(process)
            status = read_json(files.status) or {}
            error = (ready or {}).get("error") or status.get("error") or {}
            files.clear(keep_log=True)
            temp.unlink(missing_ok=True)
            raise self._start_error(tab_id, error, files.log)
        return {"tab_id": tab_id, "output_file": str(output), "fps": fps, "started_at": started_at}

    async def _wait_for_ready(self, files: RecordingFiles, process: subprocess.Popen[Any]) -> dict[str, Any] | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._ready_timeout
        while loop.time() < deadline:
            ready = read_json(files.ready)
            if ready is not None:
                return ready
            if process.poll() is not None:
                return read_json(files.ready)
            await asyncio.sleep(POLL_SECONDS)
        return None

    def _abandon(self, process: subprocess.Popen[Any]) -> None:
        if process.poll() is None:
            process.kill()
        process.wait()

    @staticmethod
    def _start_error(tab_id: str, error: Mapping[str, Any], log: Path) -> BrowserError:
        code = error.get("code")
        message = error.get("message") or "The recorder did not start."
        if code == "TAB_NOT_FOUND":
            return BrowserError("TAB_NOT_FOUND", "The requested tab is closed or unavailable.", retryable=True,
                                exit_status=4, details={"tab_id": tab_id})
        if code == "BROWSER_UNAVAILABLE":
            return BrowserError("BROWSER_UNAVAILABLE", message, retryable=True, exit_status=3)
        return recording_failed(f"The recorder did not start: {message}", tab_id=tab_id, log_file=str(log),
                                log_tail=_log_tail(log))

    async def stop(self, *, port: int, tab_id: str) -> dict[str, Any]:
        files = self._files(port, tab_id)
        state = read_json(files.state)
        if state is None:
            raise recording_not_active(tab_id)

        running = self._worker_running(state)
        if running:
            self._signal_process(state["worker_pid"], signal.SIGTERM)
        status = await self._wait_for_status(files, state, running)
        if status is None:
            if running and self._worker_running(state):
                # Identity re-checked immediately before force: end the worker and its ffmpeg.
                self._signal_group(state["worker_pid"], signal.SIGKILL)
            partial = Path(state.get("temp_file", ""))
            files.clear(keep_log=True)
            raise recording_failed(
                "The recorder ended without reporting a result.",
                tab_id=tab_id,
                partial_file=str(partial) if partial.name and partial.exists() else None,
                log_file=str(files.log),
            )

        if status.get("state") != "completed":
            files.clear(keep_log=True)
            error = status.get("error") or {}
            raise recording_failed(
                f"The recording failed: {error.get('message', 'unknown error')}",
                tab_id=tab_id,
                reason=error.get("code"),
                end_reason=status.get("end_reason"),
                partial_file=status.get("partial_file"),
                log_file=str(files.log),
            )
        files.clear()
        return {
            "tab_id": tab_id,
            "artifact": {
                "path": status["output_file"],
                "media_type": "video/mp4",
                "bytes_written": int(status.get("bytes_written", 0)),
            },
            "duration_seconds": float(status.get("duration_seconds", 0.0)),
            "frames": int(status.get("frames", 0)),
            "end_reason": status.get("end_reason", "stopped"),
        }

    async def _wait_for_status(
        self, files: RecordingFiles, state: Mapping[str, Any], running: bool
    ) -> dict[str, Any] | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + (self._status_timeout if running else 0)
        while True:
            status = read_json(files.status)
            if status is not None:
                return status
            if loop.time() >= deadline or not self._worker_running(state):
                # One last read covers a worker that wrote its status just before exiting.
                return read_json(files.status)
            await asyncio.sleep(POLL_SECONDS)
