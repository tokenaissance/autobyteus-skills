"""Legacy MCP compatibility: original tool schemas and result text."""

from __future__ import annotations

from typing import Any

from video_audio.contracts import OperationResult
from video_audio.errors import MediaError
from video_audio.operations.registry import MediaContext, OperationSpec
from video_audio.paths import LegacyPathPolicy


def render_legacy(result: OperationResult | MediaError) -> Any:
    if isinstance(result, MediaError):
        return result.message
    return result.legacy_value if result.legacy_value is not None else result.message


def build_wrapper(spec: OperationSpec):
    """A function exposing the operation's original public signature to FastMCP."""
    original = spec.signature
    original_return = _legacy_return(spec)

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        bound = original.bind(*args, **kwargs)
        ctx = MediaContext(paths=LegacyPathPolicy())
        try:
            return render_legacy(spec.invoke(ctx, **bound.arguments))
        except MediaError as exc:
            # Failures the registry catch-all wrapped were unhandled exceptions in the
            # legacy tools (FastMCP reported them as tool errors); keep that behaviour.
            if exc.code == "INTERNAL_ERROR" and exc.__cause__ is not None:
                raise exc.__cause__
            return render_legacy(exc)

    wrapper.__name__ = spec.name
    wrapper.__qualname__ = spec.name
    wrapper.__doc__ = spec.description
    wrapper.__signature__ = original.replace(return_annotation=original_return)  # type: ignore[attr-defined]
    wrapper.__annotations__ = {
        **{n: p.annotation for n, p in original.parameters.items()},
        "return": original_return,
    }
    return wrapper


def _legacy_return(spec: OperationSpec) -> Any:
    from typing import Union

    return Union[float, str] if spec.name == "get_media_duration" else str
