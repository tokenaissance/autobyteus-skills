"""Transport-neutral error taxonomy. ``message`` is the legacy MCP text."""

from __future__ import annotations

from typing import Any

MAX_STDERR = 4000


class MediaError(Exception):
    """An expected public failure with stable recovery metadata."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        exit_status: int = 5,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.exit_status = exit_status
        self.details = details

    def to_payload(self) -> dict[str, Any]:
        message = self.message if len(self.message) <= MAX_STDERR else self.message[:MAX_STDERR] + "...[truncated]"
        payload: dict[str, Any] = {"code": self.code, "message": message, "retryable": self.retryable}
        if self.details:
            payload["details"] = self.details
        return payload

    # -- factories -------------------------------------------------------
    @classmethod
    def invalid_argument(cls, message: str, **details: Any) -> "MediaError":
        return cls("INVALID_ARGUMENT", message, exit_status=2, details=details or None)

    @classmethod
    def input_not_found(cls, message: str, **details: Any) -> "MediaError":
        return cls("INPUT_NOT_FOUND", message, exit_status=4, details=details or None)

    @classmethod
    def media_unreadable(cls, message: str, **details: Any) -> "MediaError":
        return cls("MEDIA_UNREADABLE", message, exit_status=4, details=details or None)

    @classmethod
    def ffmpeg_failed(cls, message: str, **details: Any) -> "MediaError":
        return cls("FFMPEG_FAILED", message, exit_status=5, details=details or None)

    @classmethod
    def ffmpeg_missing(cls, message: str, **details: Any) -> "MediaError":
        return cls("FFMPEG_MISSING", message, exit_status=3, details=details or None)

    @classmethod
    def path_rejected(cls, message: str, **details: Any) -> "MediaError":
        return cls("ARTIFACT_PATH_REJECTED", message, exit_status=2, details=details or None)

    @classmethod
    def exists(cls, message: str, **details: Any) -> "MediaError":
        return cls("ARTIFACT_EXISTS", message, exit_status=2, details=details or None)

    @classmethod
    def internal(cls, message: str, **details: Any) -> "MediaError":
        return cls("INTERNAL_ERROR", message, retryable=True, exit_status=5, details=details or None)


def classify(message: str, exc: BaseException) -> MediaError:
    """Map a caught unexpected exception to a code, keeping the legacy message."""
    from video_audio.ffmpeg_runtime import ProbeError

    if isinstance(exc, ProbeError):
        return MediaError.media_unreadable(message)
    if isinstance(exc, FileNotFoundError):
        return MediaError.input_not_found(message)
    return MediaError.internal(message)


def classify_media(message: str, exc: BaseException) -> MediaError:
    """ffmpeg failure vs unreadable media for handlers that catch both."""
    from video_audio.ffmpeg_runtime import ProbeError

    if isinstance(exc, ProbeError):
        return MediaError.media_unreadable(message)
    return MediaError.ffmpeg_failed(message)
