from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from .conftest import LocalSite
from .support import LiveChrome, run_cli
from .test_recording_real_chrome import _cdp_calls


pytestmark = [pytest.mark.integration, pytest.mark.real_chrome]


def _open(live_chrome: LiveChrome, test_site: LocalSite, tmp_path: Path, path: str = "/demo"):
    environment = live_chrome.environment(tmp_path, BROWSER_AUTOMATION_ATTACH_ONLY="1")
    opened = run_cli(tmp_path, environment, "open-tab", "--url", test_site.url(path))
    assert opened.returncode == 0, opened.payload
    return environment, opened.payload["result"]["tab_id"]


def _script(tmp_path: Path, environment: dict[str, str], tab_id: str, script: str, *extra: str):
    return run_cli(tmp_path, environment, "run-script", "--tab-id", tab_id, "--script", script, *extra)


def _value(tmp_path: Path, environment: dict[str, str], tab_id: str, expression: str):
    result = _script(tmp_path, environment, tab_id, expression)
    assert result.returncode == 0, result.payload
    assert "dialogs" not in result.payload["result"]
    return result.payload["result"]["result"]


def test_confirm_with_a_decision_is_applied_and_reported(
    live_chrome: LiveChrome, test_site: LocalSite, tmp_path: Path
) -> None:
    environment, tab_id = _open(live_chrome, test_site, tmp_path)

    accepted = _script(tmp_path, environment, tab_id, "askDelete()", "--dialog", "accept")
    assert accepted.returncode == 0, accepted.payload
    assert accepted.payload["result"]["result"] is True
    assert accepted.payload["result"]["dialogs"] == [{
        "tab_id": tab_id, "type": "confirm", "message": "Delete this item?", "default_value": "",
        "outcome": "accepted", "decided_by": "agent",
    }]

    dismissed = _script(tmp_path, environment, tab_id, "askDelete()", "--dialog", "dismiss")
    assert dismissed.payload["result"]["result"] is False
    assert dismissed.payload["result"]["dialogs"][0]["outcome"] == "dismissed"


def test_confirm_without_a_decision_is_dismissed_to_unblock_and_requires_one(
    live_chrome: LiveChrome, test_site: LocalSite, tmp_path: Path
) -> None:
    environment, tab_id = _open(live_chrome, test_site, tmp_path)

    began = time.monotonic()
    result = _script(tmp_path, environment, tab_id, "askDelete()")
    assert time.monotonic() - began < 10
    assert result.returncode == 5, result.payload
    error = result.payload["error"]
    assert error["code"] == "DIALOG_DECISION_REQUIRED"
    assert '"Delete this item?"' in error["message"]
    assert error["details"]["dialogs"][0] | {"tab_id": None} == {
        "tab_id": None, "type": "confirm", "message": "Delete this item?", "default_value": "",
        "outcome": "dismissed", "decided_by": "unblock",
    }
    # The page continued with the dismissal and is not blocked.
    assert _value(tmp_path, environment, tab_id, "window.answer") is False


def test_prompt_uses_the_given_text_or_its_default_value(
    live_chrome: LiveChrome, test_site: LocalSite, tmp_path: Path
) -> None:
    environment, tab_id = _open(live_chrome, test_site, tmp_path)

    typed = _script(tmp_path, environment, tab_id, "askName()", "--dialog", "accept", "--prompt-text", "Ada")
    assert typed.payload["result"]["result"] == "Ada"
    assert typed.payload["result"]["dialogs"][0]["default_value"] == "Default Name"

    default = _script(tmp_path, environment, tab_id, "askName()", "--dialog", "accept")
    assert default.payload["result"]["result"] == "Default Name"

    rejected = _script(tmp_path, environment, tab_id, "askName()", "--dialog", "dismiss", "--prompt-text", "x")
    assert rejected.returncode == 2 and rejected.payload["error"]["code"] == "INVALID_ARGUMENT"


def test_alert_is_closed_and_reported_without_a_decision(
    live_chrome: LiveChrome, test_site: LocalSite, tmp_path: Path
) -> None:
    environment, tab_id = _open(live_chrome, test_site, tmp_path)
    result = _script(tmp_path, environment, tab_id, "notify()")
    assert result.returncode == 0, result.payload
    assert result.payload["result"]["dialogs"][0]["outcome"] == "closed"
    assert result.payload["result"]["dialogs"][0]["decided_by"] is None


def test_leave_page_dialog_follows_the_decision(
    live_chrome: LiveChrome, test_site: LocalSite, tmp_path: Path
) -> None:
    environment, tab_id = _open(live_chrome, test_site, tmp_path)
    target = next(entry for entry in live_chrome.targets() if entry["id"] == tab_id)
    # Chrome shows "Leave site?" only after real user activation: a trusted click via CDP.
    _cdp_calls(
        target["webSocketDebuggerUrl"],
        ("Input.dispatchMouseEvent", {"type": "mousePressed", "x": 5, "y": 5, "button": "left", "clickCount": 1}),
        ("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": 5, "y": 5, "button": "left", "clickCount": 1}),
        events=[],
    )
    leave = "window.guard = true; location.href = '/next'; true"

    stayed = _script(tmp_path, environment, tab_id, leave, "--dialog", "dismiss")
    assert stayed.returncode == 0, stayed.payload
    assert stayed.payload["result"]["dialogs"][0]["type"] == "beforeunload"
    time.sleep(0.5)
    assert _value(tmp_path, environment, tab_id, "location.pathname") == "/demo"

    undecided = _script(tmp_path, environment, tab_id, leave)
    assert undecided.payload["error"]["code"] == "DIALOG_DECISION_REQUIRED"

    left = _script(tmp_path, environment, tab_id, leave, "--dialog", "accept")
    assert left.payload["result"]["dialogs"][0]["outcome"] == "accepted"
    time.sleep(1.0)
    assert _value(tmp_path, environment, tab_id, "location.pathname") == "/next"


def test_navigate_and_open_tab_handle_a_dialog_raised_while_loading(
    live_chrome: LiveChrome, test_site: LocalSite, tmp_path: Path
) -> None:
    environment, tab_id = _open(live_chrome, test_site, tmp_path)
    url = test_site.url("/confirm-on-load")

    navigated = run_cli(tmp_path, environment, "navigate", "--tab-id", tab_id, "--url", url, "--dialog", "accept")
    assert navigated.returncode == 0, navigated.payload
    assert navigated.payload["result"]["dialogs"][0]["message"] == "Continue loading?"
    assert _value(tmp_path, environment, tab_id, "window.loadAnswer") is True

    undecided = run_cli(tmp_path, environment, "navigate", "--tab-id", tab_id, "--url", url)
    assert undecided.payload["error"]["code"] == "DIALOG_DECISION_REQUIRED"
    assert "--dialog accept or --dialog dismiss" in undecided.payload["error"]["message"]

    # open-tab has no option: the new tab is its target before it loads, so the dialog is
    # dismissed to unblock it (never left open) and the hint points to navigate/run-script.
    opened = run_cli(tmp_path, environment, "open-tab", "--url", url)
    assert opened.payload["error"]["code"] == "DIALOG_DECISION_REQUIRED"
    assert "through run-script or navigate" in opened.payload["error"]["message"]
    new_tab = opened.payload["error"]["details"]["tab_id"]
    listed = run_cli(tmp_path, environment, "list-tabs")
    assert listed.returncode == 0, listed.payload
    assert _value(tmp_path, environment, new_tab, "window.loadAnswer") is False


def test_dialogs_in_other_tabs_are_left_open_and_unreported(
    live_chrome: LiveChrome, test_site: LocalSite, tmp_path: Path
) -> None:
    environment, other_tab = _open(live_chrome, test_site, tmp_path)
    _environment, own_tab = _open(live_chrome, test_site, tmp_path)
    other = next(entry for entry in live_chrome.targets() if entry["id"] == other_tab)
    fixture_results: list[dict] = []

    def fixture() -> None:
        # Attached before the dialog opens; answers it after the operation has disconnected.
        fixture_results.extend(_cdp_calls(
            other["webSocketDebuggerUrl"],
            ("Page.enable", {}),
            ("Runtime.evaluate", {"expression": "setTimeout(() => { window.otherAnswer = confirm('Mine'); }, 1500); true"}),
            ("sleep", {"seconds": 7.0}),
            ("Page.handleJavaScriptDialog", {"accept": True}),
            events=[],
        ))

    thread = threading.Thread(target=fixture)
    thread.start()
    try:
        # The operation connects first; the other tab's dialog opens while it runs.
        waited = _script(tmp_path, environment, own_tab,
                         "async () => { await new Promise((r) => setTimeout(r, 3500)); return 'done'; }",
                         "--dialog", "accept")
    finally:
        thread.join()
    assert waited.returncode == 0, waited.payload
    assert waited.payload["result"] == {
        "tab_id": own_tab, "url": waited.payload["result"]["url"], "output_mode": "inline", "result": "done",
    }
    assert fixture_results[3].get("result") == {}, fixture_results[3]  # still open after disconnect
    assert _value(tmp_path, environment, other_tab, "window.otherAnswer") is True


def test_recorder_coexists_with_answered_dialogs(
    live_chrome: LiveChrome, test_site: LocalSite, tmp_path: Path
) -> None:
    environment, tab_id = _open(live_chrome, test_site, tmp_path)
    started = run_cli(tmp_path, environment, "start-recording", "--tab-id", tab_id, "--output-file", "dialogs.mp4")
    assert started.returncode == 0, started.payload
    try:
        accepted = _script(tmp_path, environment, tab_id, "askDelete()", "--dialog", "accept")
        assert accepted.payload["result"]["dialogs"][0]["outcome"] == "accepted"
        assert accepted.payload["result"]["result"] is True
    finally:
        stopped = run_cli(tmp_path, environment, "stop-recording", "--tab-id", tab_id)
    assert stopped.returncode == 0, stopped.payload
    assert json.dumps(stopped.payload["result"]["end_reason"]) == '"stopped"'
