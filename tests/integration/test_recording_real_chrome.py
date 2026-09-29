from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import time
from urllib.parse import urlparse

import pytest

from .conftest import LocalSite
from .support import LiveChrome, run_cli


pytestmark = [pytest.mark.integration, pytest.mark.real_chrome]


def _ok(result, command: str) -> dict:
    assert result.returncode == 0, (result.command, result.stderr.decode(errors="replace"), result.payload)
    assert result.payload["ok"] is True and result.payload["command"] == command
    return result.payload["result"]


def _error(result, command: str, code: str, status: int) -> dict:
    assert result.returncode == status, (result.command, result.stderr.decode(errors="replace"), result.payload)
    assert result.payload["ok"] is False and result.payload["command"] == command
    assert result.payload["error"]["code"] == code, result.payload
    return result.payload["error"]


def _open_demo(live_chrome: LiveChrome, test_site: LocalSite, tmp_path: Path) -> tuple[dict[str, str], str]:
    environment = live_chrome.environment(tmp_path)
    opened = _ok(run_cli(tmp_path, environment, "open-tab", "--url", test_site.url("/demo")), "open-tab")
    return environment, opened["tab_id"]


def _probe(path: Path) -> dict:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        pytest.skip("ffprobe is required to inspect recordings")
    completed = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_name,width,height,nb_frames",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(completed.stdout)


@pytest.fixture(autouse=True)
def _requires_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is required for recording coverage")


def test_recording_runs_in_background_across_other_cli_calls(
    live_chrome: LiveChrome, test_site: LocalSite, tmp_path: Path
) -> None:
    environment, tab_id = _open_demo(live_chrome, test_site, tmp_path)

    _error(run_cli(tmp_path, environment, "stop-recording", "--tab-id", tab_id), "stop-recording", "RECORDING_NOT_ACTIVE", 4)
    started = _ok(
        run_cli(tmp_path, environment, "start-recording", "--tab-id", tab_id, "--output-file", "clips/demo.mp4", "--fps", "10"),
        "start-recording",
    )
    assert started["output_file"] == str((tmp_path / "clips" / "demo.mp4").resolve())
    assert started["fps"] == 10
    began = time.monotonic()

    _error(
        run_cli(tmp_path, environment, "start-recording", "--tab-id", tab_id, "--output-file", "other.mp4"),
        "start-recording", "RECORDING_ALREADY_ACTIVE", 5,
    )
    # Ordinary operations keep their connect-operate-disconnect behaviour during the recording.
    clicked = _ok(run_cli(tmp_path, environment, "run-script", "--tab-id", tab_id, "--script",
                          "__abDemo.click({ text: 'Save' })"), "run-script")
    assert clicked["result"]["ok"] is True
    _ok(run_cli(tmp_path, environment, "screenshot", "--tab-id", tab_id, "--output-file", "during.png"), "screenshot")
    snapshot = _ok(run_cli(tmp_path, environment, "dom-snapshot", "--tab-id", tab_id), "dom-snapshot")
    assert snapshot["returned_elements"] > 0
    _ok(run_cli(tmp_path, environment, "run-script", "--tab-id", tab_id, "--script",
                "__abDemo.caption('Recording works')"), "run-script")
    time.sleep(1.0)

    stopped = _ok(run_cli(tmp_path, environment, "stop-recording", "--tab-id", tab_id), "stop-recording")
    elapsed = time.monotonic() - began
    artifact = Path(stopped["artifact"]["path"])
    assert artifact == tmp_path.resolve() / "clips" / "demo.mp4"
    assert stopped["artifact"]["media_type"] == "video/mp4"
    assert stopped["artifact"]["bytes_written"] == artifact.stat().st_size > 0
    assert stopped["end_reason"] == "stopped"
    assert stopped["frames"] >= 10
    assert 0.5 * elapsed <= stopped["duration_seconds"] <= elapsed + 1.0

    probe = _probe(artifact)
    assert probe["streams"][0]["codec_name"] == "h264"
    assert probe["streams"][0]["width"] % 2 == 0 and probe["streams"][0]["height"] % 2 == 0
    assert abs(float(probe["format"]["duration"]) - stopped["duration_seconds"]) < 0.5
    assert [path.name for path in artifact.parent.iterdir()] == ["demo.mp4"]

    _error(run_cli(tmp_path, environment, "stop-recording", "--tab-id", tab_id), "stop-recording", "RECORDING_NOT_ACTIVE", 4)
    _error(
        run_cli(tmp_path, environment, "start-recording", "--tab-id", tab_id, "--output-file", "clips/demo.mp4"),
        "start-recording", "ARTIFACT_EXISTS", 2,
    )


def test_recording_finalizes_itself_when_the_tab_closes(
    live_chrome: LiveChrome, test_site: LocalSite, tmp_path: Path
) -> None:
    environment, tab_id = _open_demo(live_chrome, test_site, tmp_path)
    _ok(run_cli(tmp_path, environment, "start-recording", "--tab-id", tab_id, "--output-file", "closed.mp4"),
        "start-recording")
    time.sleep(1.0)
    _ok(run_cli(tmp_path, environment, "close-tab", "--tab-id", tab_id), "close-tab")
    time.sleep(1.0)

    stopped = _ok(run_cli(tmp_path, environment, "stop-recording", "--tab-id", tab_id), "stop-recording")
    assert stopped["end_reason"] == "target_closed"
    assert Path(stopped["artifact"]["path"]).stat().st_size > 0


def test_recording_start_errors(live_chrome: LiveChrome, test_site: LocalSite, tmp_path: Path) -> None:
    environment, tab_id = _open_demo(live_chrome, test_site, tmp_path)
    missing = dict(environment, BROWSER_AUTOMATION_FFMPEG_BIN=str(tmp_path / "no-ffmpeg"))
    _error(run_cli(tmp_path, missing, "start-recording", "--tab-id", tab_id, "--output-file", "x.mp4"),
           "start-recording", "RECORDING_DEPENDENCY_MISSING", 3)
    _error(run_cli(tmp_path, environment, "start-recording", "--tab-id", "NOPE", "--output-file", "x.mp4"),
           "start-recording", "TAB_NOT_FOUND", 4)
    _error(run_cli(tmp_path, environment, "start-recording", "--tab-id", tab_id, "--output-file", "x.webm"),
           "start-recording", "INVALID_ARGUMENT", 2)
    _error(run_cli(tmp_path, environment, "start-recording", "--tab-id", tab_id, "--output-file", "/tmp/x.mp4"),
           "start-recording", "ARTIFACT_PATH_REJECTED", 2)
    assert not any(tmp_path.glob("*.mp4")) and not any(tmp_path.glob(".x.mp4.*"))


def _cdp_calls(websocket_url: str, *commands: tuple[str, dict], events: list[str]) -> list[dict]:
    """CDP commands over one raw websocket: Playwright cannot attach while a dialog blocks the page."""

    parsed = urlparse(websocket_url)
    with socket.create_connection((parsed.hostname, parsed.port), timeout=10) as sock:
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall(
            f"GET {parsed.path} HTTP/1.1\r\nHost: {parsed.hostname}:{parsed.port}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode()
        )
        response = b""
        while b"\r\n\r\n" not in response:
            response += sock.recv(4096)
        assert b" 101 " in response.split(b"\r\n", 1)[0], response
        buffer = response.split(b"\r\n\r\n", 1)[1]
        results: list[dict] = []
        for command_id, (method, params) in enumerate(commands, start=1):
            if method == "sleep":
                time.sleep(params["seconds"])
                results.append({})
                continue
            payload = json.dumps({"id": command_id, "method": method, "params": params}).encode()
            mask = os.urandom(4)
            header = bytes([0x81]) + (bytes([0x80 | len(payload)]) if len(payload) < 126
                                      else bytes([0x80 | 126]) + struct.pack(">H", len(payload)))
            sock.sendall(header + mask + bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload)))
            while True:
                while len(buffer) < 2:
                    buffer += sock.recv(4096)
                length = buffer[1] & 0x7F
                offset = 2
                if length == 126:
                    while len(buffer) < 4:
                        buffer += sock.recv(4096)
                    length = struct.unpack(">H", buffer[2:4])[0]
                    offset = 4
                elif length == 127:
                    while len(buffer) < 10:
                        buffer += sock.recv(4096)
                    length = struct.unpack(">Q", buffer[2:10])[0]
                    offset = 10
                while len(buffer) < offset + length:
                    buffer += sock.recv(65536)
                message = json.loads(buffer[offset:offset + length])
                buffer = buffer[offset + length:]
                if "method" in message:
                    events.append(message["method"])
                if message.get("id") == command_id:
                    results.append(message)
                    break
        return results


def test_page_dialog_raised_while_recording_stays_open_and_operable(
    live_chrome: LiveChrome, test_site: LocalSite, tmp_path: Path
) -> None:
    """MP-005: the worker's long-lived client must not auto-dismiss a confirm() raised during recording."""

    environment, tab_id = _open_demo(live_chrome, test_site, tmp_path)
    _ok(run_cli(tmp_path, environment, "start-recording", "--tab-id", tab_id, "--output-file", "dialog.mp4"),
        "start-recording")
    try:
        target = next(entry for entry in live_chrome.targets() if entry["id"] == tab_id)
        events: list[str] = []
        # One raw client observes the dialog (Page enabled first), lets the recording run for 2 s,
        # then answers it: success proves no other client (the worker) dismissed it meanwhile.
        results = _cdp_calls(
            target["webSocketDebuggerUrl"],
            ("Page.enable", {}),
            ("Runtime.evaluate", {"expression": "setTimeout(() => { window.dialogAnswer = confirm('Remove node?'); }, 200); true"}),
            ("sleep", {"seconds": 2.0}),
            ("Page.handleJavaScriptDialog", {"accept": True}),
            ("sleep", {"seconds": 0.3}),
            ("Runtime.evaluate", {"expression": "window.dialogAnswer", "returnByValue": True}),
            events=events,
        )
        assert results[3].get("result") == {}, results[3]
        assert results[5]["result"]["result"].get("value") is True, results[5]
        assert events.index("Page.javascriptDialogOpening") < events.index("Page.javascriptDialogClosed")
    finally:
        _ok(run_cli(tmp_path, environment, "stop-recording", "--tab-id", tab_id), "stop-recording")
