"""Presentation helper source, version and the "install when used" rule for run_script."""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
from typing import Any

HELPER_GLOBAL = "__abDemo"
# Bump whenever demo_helper.js changes so pages holding an older helper get the new one.
HELPER_VERSION = "1"


@lru_cache(maxsize=1)
def helper_source() -> str:
    """The helper as a JavaScript function of its version, loaded from package data."""

    return resources.files(__package__).joinpath("demo_helper.js").read_text(encoding="utf-8")


def script_uses_helper(script: str) -> bool:
    """Only scripts that mention the helper get it; other pages stay untouched."""

    return HELPER_GLOBAL in script


async def ensure_installed(page: Any) -> dict[str, Any]:
    """Install the current helper version on the page unless it is already present (idempotent)."""

    return await page.evaluate(helper_source(), HELPER_VERSION)
