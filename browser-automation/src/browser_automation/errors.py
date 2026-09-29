"""Stable transport-neutral browser error taxonomy."""

from __future__ import annotations

from typing import Any


class BrowserError(Exception):
    """An expected public failure with stable recovery metadata."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        exit_status: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.exit_status = exit_status
        self.details = details

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.details:
            payload["details"] = self.details
        return payload


def invalid_argument(message: str, **details: Any) -> BrowserError:
    return BrowserError(
        "INVALID_ARGUMENT",
        message,
        retryable=False,
        exit_status=2,
        details=details or None,
    )


def configuration_error(message: str, **details: Any) -> BrowserError:
    return BrowserError(
        "CONFIGURATION_ERROR",
        message,
        retryable=False,
        exit_status=3,
        details=details or None,
    )


def browser_unavailable(message: str = "Chrome is unavailable at the configured CDP endpoint.") -> BrowserError:
    return BrowserError("BROWSER_UNAVAILABLE", message, retryable=True, exit_status=3)


def tab_not_found(tab_id: str) -> BrowserError:
    return BrowserError(
        "TAB_NOT_FOUND",
        "The requested tab is closed or unavailable.",
        retryable=True,
        exit_status=4,
        details={"tab_id": tab_id},
    )


def browser_operation_failed(message: str = "The browser operation failed.") -> BrowserError:
    return BrowserError("BROWSER_OPERATION_FAILED", message, retryable=True, exit_status=5)


def dialog_decision_required(dialogs: list[dict[str, Any]], *, can_decide: bool) -> BrowserError:
    """The operation's own page raised a dialog without a decision; it was dismissed to unblock it."""

    first = next(report for report in dialogs if report["decided_by"] == "unblock")
    remedy = (
        "Re-run the action with --dialog accept or --dialog dismiss (MCP: dialog), plus --prompt-text "
        "(MCP: prompt_text) for prompts."
        if can_decide
        else "Repeat the action that raises it through run-script or navigate with a decision "
        "(--dialog accept or --dialog dismiss)."
    )
    return BrowserError(
        "DIALOG_DECISION_REQUIRED",
        f"The page opened a {first['type']} dialog: \"{first['message']}\". It was dismissed only to "
        f"unblock the page. {remedy}",
        retryable=False,
        exit_status=5,
        details={"tab_id": first["tab_id"], "dialogs": dialogs},
    )


def page_blocked(endpoint: str, timeout_seconds: float, targets: list[dict[str, Any]]) -> BrowserError:
    return BrowserError(
        "PAGE_BLOCKED",
        f"The browser at {endpoint} is running but did not accept a connection within "
        f"{timeout_seconds:g} s. Most likely a page dialog (alert/confirm/prompt/'Leave site?') is "
        "waiting for an answer: answer it in the window (the user, or OS-level tools such as "
        "computer-use on Linux). Otherwise a page may be hung. Headless browsers have no window: "
        "close the tab or restart that browser.",
        retryable=True,
        exit_status=3,
        details={"endpoint": endpoint, "targets": targets},
    )


def recording_dependency_missing(message: str) -> BrowserError:
    return BrowserError("RECORDING_DEPENDENCY_MISSING", message, retryable=False, exit_status=3)


def recording_already_active(tab_id: str) -> BrowserError:
    return BrowserError(
        "RECORDING_ALREADY_ACTIVE",
        "A recording of this tab is already running; stop it first.",
        retryable=False,
        exit_status=5,
        details={"tab_id": tab_id},
    )


def recording_not_active(tab_id: str) -> BrowserError:
    return BrowserError(
        "RECORDING_NOT_ACTIVE",
        "No recording of this tab is active.",
        retryable=False,
        exit_status=4,
        details={"tab_id": tab_id},
    )


def recording_failed(message: str, **details: Any) -> BrowserError:
    return BrowserError("RECORDING_FAILED", message, retryable=True, exit_status=5, details=details or None)
