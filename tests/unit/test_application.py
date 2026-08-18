from __future__ import annotations

from contextlib import asynccontextmanager
import math
from pathlib import Path
from typing import Any

import pytest

from browser_automation.application import BrowserApplication
from browser_automation.errors import BrowserError
from browser_automation.json_codec import dumps_strict, loads_strict
from browser_automation.policy import ArtifactPolicy


class FakeResponse:
    ok = True
    status = 200


class FakePage:
    def __init__(self, target_id: str, url: str = "about:blank", title: str = "New Tab") -> None:
        self.target_id = target_id
        self.url = url
        self._title = title
        self._closed = False
        self.script_result: Any | None = None
        self.has_script_result = False

    def is_closed(self) -> bool:
        return self._closed

    async def title(self) -> str:
        return self._title

    async def goto(self, url: str, **_kwargs: Any) -> FakeResponse:
        self.url = url
        self._title = "Example Domain" if "example.com" in url else "Page"
        return FakeResponse()

    async def close(self) -> None:
        self._closed = True

    async def content(self) -> str:
        return "<html><body><h1>Example</h1><script>bad()</script></body></html>"

    async def screenshot(self, path: str, **_kwargs: Any) -> None:
        Path(path).write_bytes(b"png")

    async def evaluate(self, script: str, arg: Any = None) -> Any:
        if isinstance(arg, dict) and "maxElements" in arg:
            return {
                "total_candidates": 1,
                "returned_elements": 1,
                "truncated": False,
                "elements": [{
                    "element_id": "e1",
                    "tag_name": "button",
                    "dom_id": "go",
                    "css_selector": "#go",
                    "role": "button",
                    "name": "Go",
                    "text": "Go",
                    "href": None,
                    "value": None,
                    "bounding_box": None,
                }],
            }
        if self.has_script_result:
            return self.script_result
        return {"script_uses_arg": "arg" in script, "arg": arg}


class FakeContext:
    def __init__(self) -> None:
        self.pages = [FakePage("target-user", "https://user.example/account", "Account")]
        self._next = 1

    async def new_page(self) -> FakePage:
        page = FakePage(f"target-{self._next}")
        self._next += 1
        self.pages.append(page)
        return page


class FakeSession:
    def __init__(self, context: FakeContext) -> None:
        self.context = context
        self.browser = type("Browser", (), {"contexts": [context]})()

    async def target_id_for_page(self, page: FakePage) -> str:
        return page.target_id

    async def summarize_page(self, page: FakePage) -> dict[str, Any]:
        return {"tab_id": page.target_id, "url": page.url, "title": await page.title()}

    async def list_tabs(self) -> list[dict[str, Any]]:
        return [await self.summarize_page(page) for page in self.context.pages if not page.is_closed()]

    async def resolve_page(self, tab_id: str) -> FakePage:
        for page in self.context.pages:
            if page.target_id == tab_id and not page.is_closed():
                return page
        from browser_automation.errors import tab_not_found

        raise tab_not_found(tab_id)


class FakeRuntime:
    endpoint = "http://localhost:9222"

    def __init__(self) -> None:
        self.context = FakeContext()

    @asynccontextmanager
    async def session(self):
        yield FakeSession(self.context)


@pytest.mark.anyio
async def test_shared_application_supports_explicit_cross_call_tab_workflow(tmp_path: Path) -> None:
    app = BrowserApplication(runtime=FakeRuntime(), artifact_policy=ArtifactPolicy(tmp_path))

    health = await app.health_check()
    assert health["page_count"] == 1

    attached = await app.attach_tab(url_contains="user.example")
    assert attached["tab_id"] == "target-user"

    opened = await app.open_tab(url="https://example.com")
    tab_id = opened["tab_id"]
    assert tab_id == "target-1"
    assert not tab_id.isdigit()

    listed = await app.list_tabs()
    assert {tab["tab_id"] for tab in listed["tabs"]} == {"target-user", "target-1"}

    read = await app.read_page(tab_id=tab_id, cleaning_mode="text")
    assert read["output_mode"] == "inline"
    assert read["content"] == "Example"

    snapshot = await app.dom_snapshot(tab_id=tab_id)
    assert snapshot["output_mode"] == "inline"
    assert snapshot["elements"][0]["css_selector"] == "#go"

    script = await app.run_script(tab_id=tab_id, script="return arg.value;", arg={"value": 2})
    assert script["result"] == {"script_uses_arg": True, "arg": {"value": 2}}

    shot = await app.screenshot(tab_id=tab_id, output_file="artifacts/page.png")
    assert Path(shot["artifact"]["path"]).read_bytes() == b"png"

    closed = await app.close_tab(tab_id=tab_id)
    assert closed == {"tab_id": tab_id, "closed": True}
    assert "target-user" in {tab["tab_id"] for tab in (await app.list_tabs())["tabs"]}


@pytest.mark.anyio
async def test_attach_ambiguity_and_stale_target_are_stable(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    runtime.context.pages.append(FakePage("target-user-2", "https://user.example/other", "Account 2"))
    app = BrowserApplication(runtime=runtime, artifact_policy=ArtifactPolicy(tmp_path))

    with pytest.raises(BrowserError) as ambiguous:
        await app.attach_tab(url_contains="user.example")
    assert ambiguous.value.code == "AMBIGUOUS_TAB_MATCH"

    with pytest.raises(BrowserError) as stale:
        await app.read_page(tab_id="missing-target")
    assert stale.value.code == "TAB_NOT_FOUND"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("result", "output_file"),
    [
        (math.nan, None),
        (math.inf, "artifacts/result.json"),
        ({"nested": [-math.inf]}, None),
        ({"nested": [math.nan]}, "artifacts/result.json"),
    ],
)
async def test_script_results_must_be_strict_finite_json(
    tmp_path: Path,
    result: Any,
    output_file: str | None,
) -> None:
    runtime = FakeRuntime()
    page = runtime.context.pages[0]
    page.has_script_result = True
    page.script_result = result
    app = BrowserApplication(runtime=runtime, artifact_policy=ArtifactPolicy(tmp_path))

    with pytest.raises(BrowserError) as failure:
        await app.run_script(
            tab_id=page.target_id,
            script="1",
            output_file=output_file,
        )
    assert failure.value.code == "SCRIPT_FAILED"
    assert failure.value.exit_status == 5
    assert not (tmp_path / "artifacts/result.json").exists()
    assert list(tmp_path.rglob("*.tmp")) == []


@pytest.mark.anyio
async def test_script_argument_must_be_strict_finite_json(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    app = BrowserApplication(runtime=runtime, artifact_policy=ArtifactPolicy(tmp_path))
    with pytest.raises(BrowserError) as failure:
        await app.run_script(tab_id="target-user", script="arg.value", arg={"value": math.inf})
    assert failure.value.code == "INVALID_ARGUMENT"
    assert failure.value.exit_status == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("script_result", "output_file"),
    [
        ("\ud800", None),
        ("\udfff", None),
        ({"nested": ["\ud800"]}, "artifacts/high-surrogate.json"),
        ({"nested": ["\udfff"]}, "artifacts/low-surrogate.json"),
    ],
)
async def test_script_lone_surrogate_results_remain_sink_safe(
    tmp_path: Path,
    script_result: Any,
    output_file: str | None,
) -> None:
    runtime = FakeRuntime()
    page = runtime.context.pages[0]
    page.has_script_result = True
    page.script_result = script_result
    app = BrowserApplication(runtime=runtime, artifact_policy=ArtifactPolicy(tmp_path))

    response = await app.run_script(
        tab_id=page.target_id,
        script="1",
        output_file=output_file,
    )

    if output_file is None:
        assert response["result"] == script_result
        dumps_strict(response).encode("utf-8", errors="strict")
    else:
        artifact_bytes = (tmp_path / output_file).read_bytes()
        artifact_payload = loads_strict(artifact_bytes.decode("utf-8", errors="strict"))
        assert artifact_payload["result"] == script_result


@pytest.mark.anyio
async def test_screenshot_no_overwrite_preserves_interleaving_winner_and_cleans_temporary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = FakeRuntime()
    policy = ArtifactPolicy(tmp_path)
    app = BrowserApplication(runtime=runtime, artifact_policy=policy)
    output = tmp_path / "artifacts/race.png"
    original_commit = policy.commit_temporary

    def interleaving_commit(temporary: Path, destination: Path, *, overwrite: bool) -> None:
        destination.write_bytes(b"other-process")
        original_commit(temporary, destination, overwrite=overwrite)

    monkeypatch.setattr(policy, "commit_temporary", interleaving_commit)
    with pytest.raises(BrowserError) as collision:
        await app.screenshot(tab_id="target-user", output_file="artifacts/race.png")
    assert collision.value.code == "ARTIFACT_EXISTS"
    assert collision.value.exit_status == 2
    assert output.read_bytes() == b"other-process"
    assert list(output.parent.glob(".race.png.*.tmp")) == []


@pytest.mark.anyio
async def test_screenshot_explicit_overwrite_replaces_existing_file(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    app = BrowserApplication(runtime=runtime, artifact_policy=ArtifactPolicy(tmp_path))
    output = tmp_path / "artifacts/replace.png"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"old")

    result = await app.screenshot(
        tab_id="target-user",
        output_file="artifacts/replace.png",
        overwrite=True,
    )
    assert output.read_bytes() == b"png"
    assert result["artifact"]["bytes_written"] == 3
    assert list(output.parent.glob(".replace.png.*.tmp")) == []
