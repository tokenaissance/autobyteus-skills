from mcp.server.fastmcp import FastMCP

from browser_automation.application import BrowserApplication
from browser_automation.contracts import CloseTabResult


def register(server: FastMCP, application: BrowserApplication) -> None:
    from browser_automation.mcp.tools import invoke

    @server.tool(name="close_tab", title="Close tab", description="Close exactly one tab by opaque target ID.", structured_output=True)
    async def close_tab(tab_id: str) -> CloseTabResult:
        return await invoke(application.close_tab(tab_id=tab_id))
