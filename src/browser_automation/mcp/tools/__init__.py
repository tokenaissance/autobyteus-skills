"""Register the complete retained browser MCP tool inventory."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, TypeVar

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from browser_automation.application import BrowserApplication
from browser_automation.errors import BrowserError
from browser_automation.json_codec import StrictJsonError, dumps_strict
from browser_automation.mcp.tools.attach_tab import register as register_attach_tab
from browser_automation.mcp.tools.close_tab import register as register_close_tab
from browser_automation.mcp.tools.dom_snapshot import register as register_dom_snapshot
from browser_automation.mcp.tools.list_tabs import register as register_list_tabs
from browser_automation.mcp.tools.navigate_to import register as register_navigate_to
from browser_automation.mcp.tools.open_tab import register as register_open_tab
from browser_automation.mcp.tools.read_page import register as register_read_page
from browser_automation.mcp.tools.run_script import register as register_run_script
from browser_automation.mcp.tools.screenshot import register as register_screenshot

T = TypeVar("T")


async def invoke(operation: Awaitable[T]) -> T:
    try:
        return await operation
    except BrowserError as exc:
        try:
            suffix = f" details={dumps_strict(exc.details)}" if exc.details else ""
        except StrictJsonError:
            suffix = ""
        raise ToolError(f"{exc.code}: {exc.message}{suffix}") from exc


def register_tools(server: FastMCP, application: BrowserApplication) -> None:
    register_open_tab(server, application)
    register_attach_tab(server, application)
    register_close_tab(server, application)
    register_list_tabs(server, application)
    register_navigate_to(server, application)
    register_read_page(server, application)
    register_screenshot(server, application)
    register_dom_snapshot(server, application)
    register_run_script(server, application)
