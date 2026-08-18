from __future__ import annotations

import json
from pathlib import Path
import time
import uuid

import pytest

from .conftest import LocalSite
from .support import LiveChrome, run_cli


pytestmark = [pytest.mark.integration, pytest.mark.real_chrome]


def assert_success(result, command: str) -> dict:
    assert result.returncode == 0, (result.command, result.stderr.decode(errors="replace"), result.payload)
    assert result.payload["ok"] is True
    assert result.payload["command"] == command
    return result.payload["result"]


def assert_error(result, *, command: str, code: str, status: int) -> dict:
    assert result.returncode == status, (result.command, result.stderr.decode(errors="replace"), result.payload)
    assert result.payload["ok"] is False
    assert result.payload["command"] == command
    assert result.payload["error"]["code"] == code
    return result.payload["error"]


def test_independent_cli_processes_operate_one_real_target_without_stray_or_global_close(
    live_chrome: LiveChrome,
    test_site: LocalSite,
    tmp_path: Path,
) -> None:
    environment = live_chrome.environment(tmp_path)
    user_token = uuid.uuid4().hex
    user_url = test_site.url(f"/page?token={user_token}&title=UserOwned-{user_token}")
    user_target = live_chrome.open_target(user_url, title_contains=f"UserOwned-{user_token}")
    before_health = live_chrome.page_count()

    health = assert_success(run_cli(tmp_path, environment, "health-check"), "health-check")
    assert health["connected"] is True
    assert health["endpoint"] == live_chrome.endpoint
    assert health["page_count"] == before_health
    assert live_chrome.page_count() == before_health

    task_token = uuid.uuid4().hex
    opened = assert_success(
        run_cli(tmp_path, environment, "open-tab", "--url", test_site.url(f"/page?token={task_token}")),
        "open-tab",
    )
    tab_id = opened["tab_id"]
    assert tab_id and not tab_id.isdigit()

    listed = assert_success(run_cli(tmp_path, environment, "list-tabs"), "list-tabs")
    listed_ids = {tab["tab_id"] for tab in listed["tabs"]}
    assert tab_id in listed_ids
    assert user_target["id"] in listed_ids

    navigated = assert_success(
        run_cli(
            tmp_path,
            environment,
            "navigate",
            "--tab-id",
            tab_id,
            "--url",
            test_site.url(f"/next?token={task_token}"),
        ),
        "navigate",
    )
    assert navigated["tab_id"] == tab_id
    assert navigated["ok"] is True
    assert navigated["status"] == 200

    read = assert_success(
        run_cli(tmp_path, environment, "read-page", "--tab-id", tab_id, "--cleaning-mode", "text"),
        "read-page",
    )
    assert f"Next Page {task_token}" in read["content"]

    closed = assert_success(run_cli(tmp_path, environment, "close-tab", "--tab-id", tab_id), "close-tab")
    assert closed == {"tab_id": tab_id, "closed": True}
    assert any(target["id"] == user_target["id"] for target in live_chrome.targets())
    assert live_chrome.process.poll() is None
    fetch_health = assert_success(run_cli(tmp_path, environment, "health-check"), "health-check")
    assert fetch_health["connected"] is True


def test_real_content_dom_script_screenshot_and_workspace_artifacts(
    live_chrome: LiveChrome,
    test_site: LocalSite,
    tmp_path: Path,
) -> None:
    environment = live_chrome.environment(tmp_path)
    token = uuid.uuid4().hex
    opened = assert_success(
        run_cli(tmp_path, environment, "open-tab", "--url", test_site.url(f"/page?token={token}")),
        "open-tab",
    )
    tab_id = opened["tab_id"]
    try:
        raw = assert_success(
            run_cli(tmp_path, environment, "read-page", "--tab-id", tab_id, "--cleaning-mode", "raw"),
            "read-page",
        )
        assert "fixtureLoaded" in raw["content"]
        text = assert_success(
            run_cli(tmp_path, environment, "read-page", "--tab-id", tab_id, "--cleaning-mode", "text"),
            "read-page",
        )
        assert f"Integration Page {token}" in text["content"]
        thorough = assert_success(
            run_cli(
                tmp_path,
                environment,
                "read-page",
                "--tab-id",
                tab_id,
                "--cleaning-mode",
                "thorough",
                "--output-file",
                "artifacts/page.html",
            ),
            "read-page",
        )
        html_path = Path(thorough["artifact"]["path"])
        assert html_path == tmp_path / "artifacts/page.html"
        assert html_path.is_file()
        assert "fixtureLoaded" not in html_path.read_text()
        assert thorough["artifact"]["bytes_written"] == html_path.stat().st_size

        snapshot = assert_success(
            run_cli(tmp_path, environment, "dom-snapshot", "--tab-id", tab_id, "--max-elements", "25"),
            "dom-snapshot",
        )
        selectors = {element["css_selector"] for element in snapshot["elements"]}
        assert {"#name", "#go"}.issubset(selectors)
        assert all(element["element_id"].startswith("e") for element in snapshot["elements"])

        action_script = (
            "(arg) => {"
            "document.querySelector('#name').value=arg.value;"
            "document.querySelector('#go').click();"
            "return {status:document.querySelector('#status').textContent,value:document.querySelector('#name').value};"
            "}"
        )
        action = assert_success(
            run_cli(
                tmp_path,
                environment,
                "run-script",
                "--tab-id",
                tab_id,
                "--script",
                action_script,
                "--arg-json",
                json.dumps({"value": "agent-value"}),
            ),
            "run-script",
        )
        assert action["result"] == {"status": "clicked:agent-value", "value": "agent-value"}
        verified = assert_success(
            run_cli(
                tmp_path,
                environment,
                "run-script",
                "--tab-id",
                tab_id,
                "--script",
                "document.querySelector('#status').textContent",
            ),
            "run-script",
        )
        assert verified["result"] == "clicked:agent-value"

        unicode_result = assert_success(
            run_cli(
                tmp_path,
                environment,
                "run-script",
                "--tab-id",
                tab_id,
                "--script",
                "({nested:['Grüße','😀']})",
            ),
            "run-script",
        )
        assert unicode_result["result"] == {"nested": ["Grüße", "😀"]}

        screenshot = assert_success(
            run_cli(
                tmp_path,
                environment,
                "screenshot",
                "--tab-id",
                tab_id,
                "--output-file",
                "artifacts/page.png",
            ),
            "screenshot",
        )
        shot_path = Path(screenshot["artifact"]["path"])
        assert screenshot["artifact"]["media_type"] == "image/png"
        assert shot_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        assert screenshot["artifact"]["bytes_written"] == shot_path.stat().st_size

        jpeg = assert_success(
            run_cli(
                tmp_path,
                environment,
                "screenshot",
                "--tab-id",
                tab_id,
                "--output-file",
                "artifacts/page.jpeg",
                "--format",
                "jpeg",
            ),
            "screenshot",
        )
        jpeg_path = Path(jpeg["artifact"]["path"])
        jpeg_bytes = jpeg_path.read_bytes()
        assert jpeg_path == tmp_path / "artifacts/page.jpeg"
        assert jpeg["artifact"]["media_type"] == "image/jpeg"
        assert jpeg["artifact"]["bytes_written"] == jpeg_path.stat().st_size == len(jpeg_bytes)
        assert jpeg_bytes.startswith(b"\xff\xd8\xff")
        assert jpeg_bytes.endswith(b"\xff\xd9")

        mismatched_format = run_cli(
            tmp_path,
            environment,
            "screenshot",
            "--tab-id",
            tab_id,
            "--output-file",
            "artifacts/mismatched.png",
            "--format",
            "jpeg",
        )
        assert_error(mismatched_format, command="screenshot", code="INVALID_ARGUMENT", status=2)
        assert not (tmp_path / "artifacts/mismatched.png").exists()

        collision = run_cli(
            tmp_path,
            environment,
            "screenshot",
            "--tab-id",
            tab_id,
            "--output-file",
            "artifacts/page.png",
        )
        assert_error(collision, command="screenshot", code="ARTIFACT_EXISTS", status=2)
        traversal = run_cli(
            tmp_path,
            environment,
            "read-page",
            "--tab-id",
            tab_id,
            "--output-file",
            "../escape.txt",
        )
        assert_error(traversal, command="read-page", code="ARTIFACT_PATH_REJECTED", status=2)
        invalid_url = run_cli(
            tmp_path,
            environment,
            "navigate",
            "--tab-id",
            tab_id,
            "--url",
            "file:///etc/passwd",
        )
        assert_error(invalid_url, command="navigate", code="INVALID_URL", status=2)
    finally:
        if any(target["id"] == tab_id for target in live_chrome.targets()):
            assert_success(run_cli(tmp_path, environment, "close-tab", "--tab-id", tab_id), "close-tab")


def test_attach_ambiguity_external_close_stale_error_and_user_tab_survival(
    live_chrome: LiveChrome,
    test_site: LocalSite,
    tmp_path: Path,
) -> None:
    environment = live_chrome.environment(tmp_path)
    unique = uuid.uuid4().hex
    user = live_chrome.open_target(
        test_site.url(f"/page?token={unique}&title=Attached-{unique}"),
        title_contains=f"Attached-{unique}",
    )
    attached = assert_success(
        run_cli(tmp_path, environment, "attach-tab", "--url-contains", unique),
        "attach-tab",
    )
    assert attached["tab_id"] == user["id"]
    inspected = assert_success(
        run_cli(tmp_path, environment, "read-page", "--tab-id", attached["tab_id"], "--cleaning-mode", "text"),
        "read-page",
    )
    assert f"Integration Page {unique}" in inspected["content"]
    assert any(target["id"] == user["id"] for target in live_chrome.targets())

    duplicate = uuid.uuid4().hex
    first = live_chrome.open_target(test_site.url(f"/page?token={duplicate}-one"))
    second = live_chrome.open_target(test_site.url(f"/page?token={duplicate}-two"))
    ambiguous = run_cli(tmp_path, environment, "attach-tab", "--url-contains", duplicate)
    error = assert_error(ambiguous, command="attach-tab", code="AMBIGUOUS_TAB_MATCH", status=4)
    assert error["details"]["match_count"] == 2

    stale = assert_success(
        run_cli(tmp_path, environment, "open-tab", "--url", test_site.url(f"/page?token=stale-{duplicate}")),
        "open-tab",
    )
    live_chrome.close_target(stale["tab_id"])
    stale_read = run_cli(tmp_path, environment, "read-page", "--tab-id", stale["tab_id"])
    assert_error(stale_read, command="read-page", code="TAB_NOT_FOUND", status=4)

    for target_id in (first["id"], second["id"]):
        if any(target["id"] == target_id for target in live_chrome.targets()):
            live_chrome.close_target(target_id)
    assert any(target["id"] == user["id"] for target in live_chrome.targets())


def test_navigation_timeout_rolls_back_only_new_page(
    live_chrome: LiveChrome,
    test_site: LocalSite,
    tmp_path: Path,
) -> None:
    environment = live_chrome.environment(tmp_path)
    token = uuid.uuid4().hex
    user = live_chrome.open_target(test_site.url(f"/page?token=user-{token}"))
    before = {target["id"] for target in live_chrome.targets()}
    timed_out = run_cli(
        tmp_path,
        environment,
        "open-tab",
        "--url",
        test_site.url("/slow?delay=2"),
        "--timeout-ms",
        "100",
    )
    assert_error(timed_out, command="open-tab", code="NAVIGATION_TIMEOUT", status=5)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        after = {target["id"] for target in live_chrome.targets()}
        if after == before:
            break
        time.sleep(0.05)
    assert after == before
    assert user["id"] in after
    assert live_chrome.process.poll() is None
