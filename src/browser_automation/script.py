"""JavaScript normalization for the explicit advanced operation."""

from __future__ import annotations

import re

from browser_automation.policy import validate_script

# `async (arg) => …`, `async () => …` and `async arg => …` are complete functions already.
_ASYNC_ARROW = re.compile(r"async\s*\(|async\s+[A-Za-z_$][\w$]*\s*=>")


def normalize_script(script: str) -> str:
    normalized = validate_script(script)
    lowered = normalized.lstrip()
    if lowered.startswith(("function", "async function", "()", "(function", "(async", "(()", "arg =>", "(arg) =>")):
        return normalized
    if _ASYNC_ARROW.match(lowered):
        return normalized
    if any(token in normalized for token in ("return", ";", "\n")):
        return f"(arg) => {{ {normalized} }}"
    return f"(arg) => ({normalized})"
