from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from browser_automation.application import BrowserApplication
from browser_automation.errors import BrowserError
from browser_automation.policy import ArtifactPolicy
from browser_automation.presentation import HELPER_VERSION, helper_source, script_uses_helper


class RecordingPage:
    """Page that records every evaluate call in order."""

    def __init__(self, *, fail_install: bool = False) -> None:
        self.url = "https://app.example/agents"
        self.calls: list[tuple[str, Any]] = []
        self.fail_install = fail_install

    def is_closed(self) -> bool:
        return False

    async def evaluate(self, script: str, arg: Any = None) -> Any:
        self.calls.append((script, arg))
        if script == helper_source():
            if self.fail_install:
                raise RuntimeError("Trusted Types blocked the helper")
            return {"installed": True, "version": arg}
        return {"ok": True}


class OnePageRuntime:
    endpoint = "http://127.0.0.1:9333"

    def __init__(self, page: RecordingPage) -> None:
        self.page = page
        self.sessions = 0

    @asynccontextmanager
    async def session(self):
        self.sessions += 1
        page = self.page

        class Session:
            async def resolve_page(self, tab_id: str) -> RecordingPage:
                assert tab_id == "T1"
                return page

        yield Session()


def test_helper_is_used_only_by_scripts_that_mention_it() -> None:
    assert script_uses_helper("__abDemo.click({text: 'Create Agent'})")
    assert script_uses_helper("async () => { await window.__abDemo.caption('Hi'); }")
    assert not script_uses_helper("document.title")
    assert not script_uses_helper("abDemo.click()")


def test_helper_source_is_a_function_of_its_version_and_ships_as_package_data() -> None:
    source = helper_source()
    assert "(version) =>" in source
    assert "window.__abDemo" in source
    assert "__ab-demo-root" in source
    assert "innerHTML" not in source
    assert HELPER_VERSION


@pytest.mark.anyio
async def test_run_script_installs_helper_first_in_the_same_session(tmp_path: Path) -> None:
    page = RecordingPage()
    runtime = OnePageRuntime(page)
    app = BrowserApplication(runtime=runtime, artifact_policy=ArtifactPolicy(tmp_path))

    result = await app.run_script(tab_id="T1", script="__abDemo.click({text: 'Create Agent'})")

    assert result["result"] == {"ok": True}
    assert runtime.sessions == 1
    assert [call[0] for call in page.calls] == [
        helper_source(),
        "(arg) => (__abDemo.click({text: 'Create Agent'}))",
    ]
    assert page.calls[0][1] == HELPER_VERSION


@pytest.mark.anyio
async def test_run_script_without_helper_leaves_the_page_untouched(tmp_path: Path) -> None:
    page = RecordingPage()
    app = BrowserApplication(runtime=OnePageRuntime(page), artifact_policy=ArtifactPolicy(tmp_path))

    await app.run_script(tab_id="T1", script="document.title")

    assert [call[0] for call in page.calls] == ["(arg) => (document.title)"]


@pytest.mark.anyio
async def test_helper_install_failure_is_a_script_failure_with_detail(tmp_path: Path) -> None:
    page = RecordingPage(fail_install=True)
    app = BrowserApplication(runtime=OnePageRuntime(page), artifact_policy=ArtifactPolicy(tmp_path))

    with pytest.raises(BrowserError) as raised:
        await app.run_script(tab_id="T1", script="__abDemo.status()")

    assert raised.value.code == "SCRIPT_FAILED"
    assert raised.value.details == {"tab_id": "T1", "detail": "presentation_helper_install_failed"}
    assert len(page.calls) == 1
