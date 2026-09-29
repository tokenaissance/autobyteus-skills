from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from browser_automation.application import BrowserApplication
from browser_automation.errors import BrowserError
from browser_automation.policy import ArtifactPolicy, validate_dialog_option
from browser_automation.runtime.dialogs import DialogDecision, DialogHandling


class FakeDialog:
    def __init__(self, page: Any, type: str, message: str = "Sure?", default_value: str = "") -> None:
        self.page = page
        self.type = type
        self.message = message
        self.default_value = default_value
        self.calls: list[tuple[str, Any]] = []

    async def accept(self, prompt_text: str | None = None) -> None:
        self.calls.append(("accept", prompt_text))

    async def dismiss(self) -> None:
        self.calls.append(("dismiss", None))


class FakeContext:
    def __init__(self) -> None:
        self.handlers: list[Any] = []

    def on(self, event: str, handler: Any) -> None:
        assert event == "dialog"
        self.handlers.append(handler)

    def raise_dialog(self, dialog: FakeDialog) -> None:
        for handler in self.handlers:
            handler(dialog)


async def handled(decision: DialogDecision | None, dialog_type: str, **kwargs: Any) -> tuple[FakeDialog, DialogHandling]:
    context, page = FakeContext(), object()
    handling = DialogHandling(decision)
    handling.attach(context)
    handling.set_target(page, "T1")
    dialog = FakeDialog(page, dialog_type, **kwargs)
    context.raise_dialog(dialog)
    await handling.settle()
    return dialog, handling


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("decision", "dialog_type", "kwargs", "call", "outcome", "decided_by"),
    [
        (None, "alert", {}, ("accept", None), "closed", None),
        (DialogDecision("dismiss"), "alert", {}, ("accept", None), "closed", None),
        (None, "confirm", {}, ("dismiss", None), "dismissed", "unblock"),
        (DialogDecision("accept"), "confirm", {}, ("accept", None), "accepted", "agent"),
        (DialogDecision("dismiss"), "confirm", {}, ("dismiss", None), "dismissed", "agent"),
        (None, "prompt", {"default_value": "d"}, ("dismiss", None), "dismissed", "unblock"),
        (DialogDecision("accept"), "prompt", {"default_value": "d"}, ("accept", "d"), "accepted", "agent"),
        (DialogDecision("accept", "typed"), "prompt", {"default_value": "d"}, ("accept", "typed"), "accepted", "agent"),
        (DialogDecision("dismiss"), "prompt", {}, ("dismiss", None), "dismissed", "agent"),
        (None, "beforeunload", {}, ("dismiss", None), "dismissed", "unblock"),
        (DialogDecision("accept"), "beforeunload", {}, ("accept", None), "accepted", "agent"),
    ],
)
async def test_target_page_dialog_rules(decision, dialog_type, kwargs, call, outcome, decided_by) -> None:
    dialog, handling = await handled(decision, dialog_type, **kwargs)

    assert dialog.calls == [call]  # answered exactly once
    [report] = handling.reports
    assert report.to_payload() == {
        "tab_id": "T1",
        "type": dialog_type,
        "message": "Sure?",
        "default_value": kwargs.get("default_value", ""),
        "outcome": outcome,
        "decided_by": decided_by,
    }
    assert handling.decision_required is (decided_by == "unblock")


@pytest.mark.anyio
async def test_other_pages_dialogs_are_never_touched_or_reported() -> None:
    context, target, other = FakeContext(), object(), object()
    handling = DialogHandling(DialogDecision("accept"))
    handling.attach(context)
    handling.set_target(target, "T1")
    foreign = FakeDialog(other, "confirm")
    context.raise_dialog(foreign)
    await handling.settle()

    assert foreign.calls == []
    assert handling.reports == []


@pytest.mark.anyio
async def test_dialogs_before_the_target_is_known_are_answered_only_once_it_is() -> None:
    context, target, other = FakeContext(), object(), object()
    handling = DialogHandling(None)
    handling.attach(context)
    early_own = FakeDialog(target, "confirm")
    early_other = FakeDialog(other, "confirm")
    context.raise_dialog(early_own)
    context.raise_dialog(early_other)
    assert early_own.calls == [] and early_other.calls == []

    handling.set_target(target, "T1")
    await handling.settle()
    assert early_own.calls == [("dismiss", None)]
    assert early_other.calls == []
    assert [report.tab_id for report in handling.reports] == ["T1"]


@pytest.mark.anyio
async def test_without_target_nothing_is_ever_answered() -> None:
    context = FakeContext()
    handling = DialogHandling(DialogDecision("accept"))
    handling.attach(context)
    dialog = FakeDialog(object(), "confirm")
    context.raise_dialog(dialog)
    await handling.settle()
    assert dialog.calls == [] and handling.reports == []


def test_dialog_option_validation() -> None:
    assert validate_dialog_option(None, None) is None
    assert validate_dialog_option("accept", None) == DialogDecision("accept")
    assert validate_dialog_option(" Dismiss ", None) == DialogDecision("dismiss")
    assert validate_dialog_option("accept", "") == DialogDecision("accept", "")
    assert validate_dialog_option("accept", "x" * 10_000) == DialogDecision("accept", "x" * 10_000)
    for dialog, text in [("maybe", None), (None, "text"), ("dismiss", "text"), ("accept", "x" * 10_001)]:
        with pytest.raises(BrowserError) as raised:
            validate_dialog_option(dialog, text)
        assert raised.value.code == "INVALID_ARGUMENT"


class DialogPage:
    """A page whose evaluation raises a dialog on its own page through the session's handling."""

    url = "https://app.example/items"

    def __init__(self, context: FakeContext, dialog_type: str | None, fail_after_dialog: bool = False) -> None:
        self._context = context
        self._dialog_type = dialog_type
        self._fail_after_dialog = fail_after_dialog
        self.dialog: FakeDialog | None = None

    def is_closed(self) -> bool:
        return False

    async def evaluate(self, _script: str, _arg: Any = None) -> Any:
        if self._dialog_type is not None:
            self.dialog = FakeDialog(self, self._dialog_type, "Delete this item?")
            self._context.raise_dialog(self.dialog)
            # A real page stays blocked until the dialog is answered.
            while not self.dialog.calls:
                await asyncio.sleep(0)
        if self._fail_after_dialog:
            raise RuntimeError("navigation interrupted by the dialog")
        return {"deleted": bool(self.dialog and self.dialog.calls == [("accept", None)])}

    async def content(self) -> str:
        return "<html></html>"


class DialogRuntime:
    endpoint = "http://127.0.0.1:9333"

    def __init__(self, page_factory: Any) -> None:
        self._page_factory = page_factory
        self.decisions: list[DialogDecision | None] = []

    @asynccontextmanager
    async def session(self, dialog_decision: DialogDecision | None = None):
        self.decisions.append(dialog_decision)
        context = FakeContext()
        handling = DialogHandling(dialog_decision)
        handling.attach(context)
        page = self._page_factory(context)

        class Session:
            dialogs = handling

            async def resolve_target(self, tab_id: str) -> Any:
                handling.set_target(page, tab_id)
                return page

        try:
            yield Session()
        finally:
            await handling.settle()


def application(tmp_path: Path, dialog_type: str | None, **kwargs: Any) -> tuple[BrowserApplication, DialogRuntime]:
    runtime = DialogRuntime(lambda context: DialogPage(context, dialog_type, **kwargs))
    return BrowserApplication(runtime=runtime, artifact_policy=ArtifactPolicy(tmp_path)), runtime


@pytest.mark.anyio
async def test_results_are_unchanged_without_dialogs(tmp_path: Path) -> None:
    app, _runtime = application(tmp_path, None)
    result = await app.run_script(tab_id="T1", script="1")
    assert "dialogs" not in result


@pytest.mark.anyio
async def test_decided_dialog_is_applied_and_reported(tmp_path: Path) -> None:
    app, runtime = application(tmp_path, "confirm")
    result = await app.run_script(tab_id="T1", script="deleteItem()", dialog="accept")

    assert runtime.decisions == [DialogDecision("accept")]
    assert result["result"] == {"deleted": True}
    assert result["dialogs"] == [{
        "tab_id": "T1", "type": "confirm", "message": "Delete this item?", "default_value": "",
        "outcome": "accepted", "decided_by": "agent",
    }]


@pytest.mark.anyio
async def test_alert_is_closed_and_reported_without_failing(tmp_path: Path) -> None:
    app, _runtime = application(tmp_path, "alert")
    result = await app.run_script(tab_id="T1", script="notify()")
    assert result["dialogs"][0]["outcome"] == "closed"


@pytest.mark.anyio
async def test_undecided_dialog_is_dismissed_to_unblock_and_requires_a_decision(tmp_path: Path) -> None:
    app, _runtime = application(tmp_path, "confirm")
    with pytest.raises(BrowserError) as raised:
        await app.run_script(tab_id="T1", script="deleteItem()")

    error = raised.value
    assert error.code == "DIALOG_DECISION_REQUIRED"
    assert error.exit_status == 5 and error.retryable is False
    assert '"Delete this item?"' in error.message
    assert "--dialog accept or --dialog dismiss" in error.message
    assert error.details["tab_id"] == "T1"
    assert error.details["dialogs"][0]["decided_by"] == "unblock"


@pytest.mark.anyio
async def test_decision_required_explains_a_failure_the_dismissal_caused(tmp_path: Path) -> None:
    app, _runtime = application(tmp_path, "confirm", fail_after_dialog=True)
    with pytest.raises(BrowserError) as raised:
        await app.run_script(tab_id="T1", script="leave()")
    assert raised.value.code == "DIALOG_DECISION_REQUIRED"


@pytest.mark.anyio
async def test_operations_without_the_option_point_to_run_script_or_navigate(tmp_path: Path) -> None:
    class ReadDialogPage(DialogPage):
        async def content(self) -> str:
            await self.evaluate("")
            return "<html></html>"

    runtime = DialogRuntime(lambda context: ReadDialogPage(context, "confirm"))
    app = BrowserApplication(runtime=runtime, artifact_policy=ArtifactPolicy(tmp_path))
    with pytest.raises(BrowserError) as raised:
        await app.read_page(tab_id="T1")

    assert raised.value.code == "DIALOG_DECISION_REQUIRED"
    assert "through run-script or navigate" in raised.value.message
    assert runtime.decisions == [None]
