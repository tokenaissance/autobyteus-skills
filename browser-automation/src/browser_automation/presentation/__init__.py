"""Built-in presentation helper (`window.__abDemo`) installed by run_script on use."""

from browser_automation.presentation.helper import (
    HELPER_GLOBAL,
    HELPER_VERSION,
    ensure_installed,
    helper_source,
    script_uses_helper,
)

__all__ = [
    "HELPER_GLOBAL",
    "HELPER_VERSION",
    "ensure_installed",
    "helper_source",
    "script_uses_helper",
]
