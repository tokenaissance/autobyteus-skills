from mcp.server.fastmcp import FastMCP

from browser_automation.application import BrowserApplication
from browser_automation.contracts import ListTabsResult


def register(server: FastMCP, application: BrowserApplication) -> None:
    from browser_automation.mcp.tools import invoke

    @server.tool(name="list_tabs", title="List tabs", description="List all addressable tabs in the configured Chrome context.", structured_output=True)
    async def list_tabs() -> ListTabsResult:
        return await invoke(application.list_tabs())
