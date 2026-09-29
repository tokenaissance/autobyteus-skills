from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from .conftest import LocalSite
from .support import LiveChrome, run_cli
from .test_recording_real_chrome import _cdp_calls


pytestmark = [pytest.mark.integration, pytest.mark.real_chrome]


def test_open_page_dialog_reports_page_blocked_quickly_and_recovers_once_answered(
    live_chrome: LiveChrome, test_site: LocalSite, tmp_path: Path
) -> None:
    environment = live_chrome.environment(tmp_path, BROWSER_AUTOMATION_ATTACH_ONLY="1")
    opened = run_cli(tmp_path, environment, "open-tab", "--url", test_site.url("/demo"))
    assert opened.returncode == 0, opened.payload
    tab_id = opened.payload["result"]["tab_id"]
    target = next(entry for entry in live_chrome.targets() if entry["id"] == tab_id)

    # A fixture client (attached before the dialog opens) raises a confirm() between operations,
    # keeps it open while the CLI runs, then answers it.
    fixture_results: list[dict] = []

    def fixture() -> None:
        fixture_results.extend(_cdp_calls(
            target["webSocketDebuggerUrl"],
            ("Page.enable", {}),
            ("Runtime.evaluate", {"expression": "setTimeout(() => { window.answer = confirm('Delete?'); }, 100); true"}),
            ("sleep", {"seconds": 14.0}),
            ("Page.handleJavaScriptDialog", {"accept": True}),
            events=[],
        ))

    thread = threading.Thread(target=fixture)
    thread.start()
    try:
        time.sleep(1.0)
        began = time.monotonic()
        blocked = run_cli(tmp_path, environment, "list-tabs")
        elapsed = time.monotonic() - began
        assert blocked.returncode == 3, blocked.payload
        error = blocked.payload["error"]
        assert error["code"] == "PAGE_BLOCKED"
        assert error["retryable"] is True
        assert "dialog" in error["message"]
        assert tab_id in {entry["tab_id"] for entry in error["details"]["targets"]}
        assert elapsed <= 10.0, elapsed
    finally:
        thread.join()

    assert fixture_results[3].get("result") == {}, fixture_results[3]
    listed = run_cli(tmp_path, environment, "list-tabs")
    assert listed.returncode == 0, listed.payload
    answered = run_cli(tmp_path, environment, "run-script", "--tab-id", tab_id, "--script", "window.answer")
    assert answered.payload["result"]["result"] is True
