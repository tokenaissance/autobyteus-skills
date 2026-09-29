from __future__ import annotations

import os
from pathlib import Path
import signal
import time
import uuid

import pytest

from .conftest import LocalSite
from .support import chrome_executable, fetch_json, free_port, run_cli


pytestmark = [pytest.mark.integration, pytest.mark.real_chrome]


def _write_recording_chrome_wrapper(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
: "${BROWSER_AUTOMATION_TEST_REAL_CHROME:?}"
: "${BROWSER_AUTOMATION_TEST_OWNED_PID_FILE:?}"
printf '%s\n' "$$" >"$BROWSER_AUTOMATION_TEST_OWNED_PID_FILE"
exec "$BROWSER_AUTOMATION_TEST_REAL_CHROME" \
  --headless=new \
  --no-default-browser-check \
  --disable-background-networking \
  --disable-component-update \
  --disable-default-apps \
  --disable-sync \
  --disable-features=Translate \
  --remote-debugging-address=127.0.0.1 \
  "$@" \
  about:blank
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _group_is_alive(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    return True


def _terminate_recorded_group(process_group_id: int, *, timeout: float = 10.0) -> None:
    if not _group_is_alive(process_group_id):
        return
    os.killpg(process_group_id, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _group_is_alive(process_group_id):
            return
        time.sleep(0.05)
    os.killpg(process_group_id, signal.SIGKILL)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _group_is_alive(process_group_id):
            return
        time.sleep(0.05)
    raise AssertionError(f"owned Chrome process group {process_group_id} did not terminate")


def _success(result, command: str) -> dict:
    assert result.returncode == 0, (result.command, result.stderr.decode(errors="replace"), result.payload)
    assert result.payload["ok"] is True
    assert result.payload["command"] == command
    return result.payload["result"]


def test_production_owned_chrome_persists_for_later_cli_processes(
    test_site: LocalSite,
    tmp_path: Path,
) -> None:
    """AC-015: an unavailable endpoint is launched once, promoted, and remains durable."""

    workspace = tmp_path / "unrelated-task-workspace"
    workspace.mkdir()
    wrapper = tmp_path / "recording-chrome"
    _write_recording_chrome_wrapper(wrapper)
    pid_file = tmp_path / "owned-chrome.pid"
    profile = tmp_path / "owned-profile"
    port = free_port()
    environment = os.environ.copy()
    environment.update(
        {
            "CHROME_REMOTE_DEBUGGING_PORT": str(port),
            "CHROME_USER_DATA_DIR": str(profile),
            "CHROME_PROFILE_DIRECTORY": "Default",
            "CHROME_LOG_PATH": str(tmp_path / "owned-chrome.log"),
            "BROWSER_AUTOMATION_CHROME_BIN": str(wrapper),
            "BROWSER_AUTOMATION_WORKSPACE": str(workspace),
            "BROWSER_AUTOMATION_TEST_REAL_CHROME": str(chrome_executable()),
            "BROWSER_AUTOMATION_TEST_OWNED_PID_FILE": str(pid_file),
        }
    )
    process_group_id: int | None = None
    tab_id: str | None = None

    with pytest.raises(OSError):
        fetch_json(f"http://127.0.0.1:{port}/json/version", timeout=0.2)

    try:
        first = _success(run_cli(workspace, environment, "health-check", timeout=180), "health-check")
        assert first["connected"] is True
        assert pid_file.is_file()
        process_group_id = int(pid_file.read_text(encoding="utf-8").strip())
        assert os.getpgid(process_group_id) == process_group_id
        assert _group_is_alive(process_group_id)
        assert fetch_json(f"http://127.0.0.1:{port}/json/version")["Browser"]

        token = uuid.uuid4().hex
        opened = _success(
            run_cli(
                workspace,
                environment,
                "open-tab",
                "--url",
                test_site.url(f"/page?token={token}&title=Owned-{token}"),
            ),
            "open-tab",
        )
        tab_id = opened["tab_id"]

        listed = _success(run_cli(workspace, environment, "list-tabs"), "list-tabs")
        assert tab_id in {tab["tab_id"] for tab in listed["tabs"]}
        read = _success(
            run_cli(workspace, environment, "read-page", "--tab-id", tab_id, "--cleaning-mode", "text"),
            "read-page",
        )
        assert f"Integration Page {token}" in read["content"]
        assert _group_is_alive(process_group_id)

        _success(run_cli(workspace, environment, "close-tab", "--tab-id", tab_id), "close-tab")
        tab_id = None
        later = _success(run_cli(workspace, environment, "health-check"), "health-check")
        assert later["connected"] is True
        assert _group_is_alive(process_group_id)
    finally:
        if tab_id is not None and process_group_id is not None and _group_is_alive(process_group_id):
            run_cli(workspace, environment, "close-tab", "--tab-id", tab_id)
        if process_group_id is not None:
            _terminate_recorded_group(process_group_id)
            assert not _group_is_alive(process_group_id)
