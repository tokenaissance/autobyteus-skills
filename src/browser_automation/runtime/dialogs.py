"""Page dialogs raised during one browser operation.

Without a registered `dialog` listener, Playwright silently dismisses every page dialog it sees.
`DialogHandling` registers one listener per browser context for the whole connection and applies
explicit rules instead:

- dialogs on pages other than the operation's target page are never touched or reported;
- an `alert` on the target page is closed and reported;
- a `confirm`, `prompt` or `beforeunload` on the target page gets the operation's decision when one
  was given (a prompt accepted without text uses its default value); without a decision it is
  dismissed only to unblock the page, reported, and the operation must fail with
  DIALOG_DECISION_REQUIRED.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)

DialogAnswer = Literal["accept", "dismiss"]


@dataclass(frozen=True, slots=True)
class DialogDecision:
    """The agent's answer for dialogs its operation raises."""

    answer: DialogAnswer
    prompt_text: str | None = None


@dataclass(frozen=True, slots=True)
class DialogReport:
    tab_id: str
    type: str
    message: str
    default_value: str
    outcome: Literal["closed", "accepted", "dismissed"]
    # "agent": the operation's decision; "unblock": dismissed for lack of a decision; None: alert.
    decided_by: Literal["agent", "unblock"] | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "tab_id": self.tab_id,
            "type": self.type,
            "message": self.message,
            "default_value": self.default_value,
            "outcome": self.outcome,
            "decided_by": self.decided_by,
        }


class DialogHandling:
    """Answer the target page's dialogs by explicit rules; leave every other page's dialogs alone."""

    def __init__(self, decision: DialogDecision | None = None) -> None:
        self._decision = decision
        self._target_page: Any | None = None
        self._target_tab_id: str | None = None
        self._pending: list[Any] = []
        self._answers: list[asyncio.Future[None]] = []
        self.reports: list[DialogReport] = []

    @property
    def decision_required(self) -> bool:
        return any(report.decided_by == "unblock" for report in self.reports)

    def attach(self, context: Any) -> None:
        """Register on one browser context; the listener stays until the Playwright client stops."""

        context.on("dialog", self._on_dialog)

    def set_target(self, page: Any, tab_id: str) -> None:
        """The operation's own page. Dialogs it raised before this call are answered now."""

        self._target_page = page
        self._target_tab_id = tab_id
        pending, self._pending = self._pending, []
        for dialog in pending:
            if dialog.page is page:
                self._answer(dialog)

    def _on_dialog(self, dialog: Any) -> None:
        if self._target_page is None:
            # Page identity is compared once the operation knows its page; until then hold it.
            self._pending.append(dialog)
        elif dialog.page is self._target_page:
            self._answer(dialog)
        # Any other page: untouched. The dialog stays open for whoever owns that tab.

    def _answer(self, dialog: Any) -> None:
        dialog_type = str(dialog.type)
        default_value = str(dialog.default_value or "")
        text: str | None = None
        if dialog_type == "alert":
            outcome, decided_by, accept = "closed", None, True
        elif self._decision is not None:
            accept = self._decision.answer == "accept"
            outcome, decided_by = ("accepted" if accept else "dismissed"), "agent"
            if accept and dialog_type == "prompt":
                text = self._decision.prompt_text if self._decision.prompt_text is not None else default_value
        else:
            outcome, decided_by, accept = "dismissed", "unblock", False
        self.reports.append(DialogReport(
            tab_id=self._target_tab_id or "",
            type=dialog_type,
            message=str(dialog.message),
            default_value=default_value,
            outcome=outcome,
            decided_by=decided_by,
        ))
        self._answers.append(asyncio.ensure_future(dialog.accept(text) if accept else dialog.dismiss()))

    async def settle(self) -> None:
        """Wait until every answer given so far has reached the browser."""

        while pending := [task for task in self._answers if not task.done()]:
            await asyncio.gather(*pending, return_exceptions=True)
        for task in self._answers:
            if not task.cancelled() and task.exception() is not None:
                logger.debug("A page dialog could not be answered: %s", task.exception())
        self._answers.clear()
