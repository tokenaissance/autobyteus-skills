"""JavaScript normalization for the explicit advanced operation."""

from __future__ import annotations

from browser_automation.policy import validate_script


def normalize_script(script: str) -> str:
    normalized = validate_script(script)
    lowered = normalized.lstrip()
    if lowered.startswith(("function", "async function", "()", "(function", "(async", "(()", "arg =>", "(arg) =>")):
        return normalized
    if any(token in normalized for token in ("return", ";", "\n")):
        return f"(arg) => {{ {normalized} }}"
    return f"(arg) => ({normalized})"
