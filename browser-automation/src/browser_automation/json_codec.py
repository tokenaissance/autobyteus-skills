"""Strict RFC-JSON decoding, validation, and encoding."""

from __future__ import annotations

import json
from typing import Any


class StrictJsonError(ValueError):
    """Raised when a value cannot cross a strict JSON boundary."""


def dumps_strict(value: Any) -> str:
    """Encode a finite value as sink-safe JSON text."""

    try:
        return json.dumps(
            value,
            # ASCII escaping keeps every encoded envelope/artifact valid for a
            # strict UTF-8 text sink, including JavaScript lone surrogates.
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise StrictJsonError("The value is not strict finite JSON.") from exc


def loads_strict(source: str) -> Any:
    """Decode JSON while rejecting named and overflow-produced non-finite values."""

    def reject_constant(token: str) -> None:
        raise StrictJsonError(f"Non-finite JSON constant is not allowed: {token}.")

    try:
        value = json.loads(source, parse_constant=reject_constant)
    except StrictJsonError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise StrictJsonError("The input is not valid strict JSON.") from exc

    # Python accepts exponent overflow (for example 1e999) as infinity even
    # though it did not pass through parse_constant. Strict encoding catches
    # that case recursively, including inside arrays and objects.
    dumps_strict(value)
    return value
