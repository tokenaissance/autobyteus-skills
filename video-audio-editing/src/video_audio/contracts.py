"""Result types shared by every surface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class OperationResult:
    """Successful operation outcome. ``message`` is the legacy MCP text."""

    message: str
    outputs: list[str] = field(default_factory=list)
    data: dict[str, Any] | None = None
    legacy_value: Any = None  # non-text MCP result (e.g. a float duration)
