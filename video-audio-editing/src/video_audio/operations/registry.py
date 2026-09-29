"""The single operation catalog projected onto the CLI and MCP surfaces."""

from __future__ import annotations

import inspect
import os
from dataclasses import dataclass
from typing import Any, Callable

from video_audio.contracts import OperationResult
from video_audio.errors import MediaError
from video_audio.ffmpeg_runtime import require_binaries
from video_audio.paths import PathPolicy


@dataclass
class MediaContext:
    """Per-invocation dependencies injected into every operation."""

    paths: PathPolicy


@dataclass
class OperationSpec:
    name: str
    fn: Callable[..., OperationResult]
    description: str
    writes_output: bool
    needs_ffmpeg: bool

    @property
    def signature(self) -> inspect.Signature:
        """Public signature (original tool arguments; no ``ctx``)."""
        sig = inspect.signature(self.fn)
        params = list(sig.parameters.values())[1:]
        return sig.replace(parameters=params)

    def invoke(self, ctx: MediaContext, **kwargs: Any) -> OperationResult:
        """Run the operation; every failure surfaces as ``MediaError``."""
        try:
            if self.needs_ffmpeg:
                require_binaries()
            result = self.fn(ctx, **kwargs)
        except MediaError:
            raise
        except Exception as exc:  # catch-all formerly duplicated in every tool
            raise MediaError.internal(f"An unexpected error occurred: {exc}") from exc
        result.outputs = [p for p in dict.fromkeys(ctx.paths.outputs) if os.path.exists(p)]
        return result


_REGISTRY: dict[str, OperationSpec] = {}


def operation(*, description: str | None = None, writes_output: bool = True, needs_ffmpeg: bool = True):
    """Register a function ``fn(ctx, **public_args)`` as one operation."""

    def decorate(fn: Callable[..., OperationResult]) -> Callable[..., OperationResult]:
        _REGISTRY[fn.__name__] = OperationSpec(
            name=fn.__name__,
            fn=fn,
            description=description if description is not None else (fn.__doc__ or ""),
            writes_output=writes_output,
            needs_ffmpeg=needs_ffmpeg,
        )
        return fn

    return decorate


def all_operations() -> list[OperationSpec]:
    from video_audio.operations import composition, editing, properties, runtime  # noqa: F401

    return list(_REGISTRY.values())
