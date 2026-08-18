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
