from mcp.server.fastmcp import FastMCP

from browser_automation.application import BrowserApplication
from browser_automation.contracts import StopRecordingResult


def register(server: FastMCP, application: BrowserApplication) -> None:
    from browser_automation.mcp.tools import invoke

    @server.tool(
        name="stop_recording",
        title="Stop recording",
        description="Finish the tab's recording and return the MP4 artifact, or report one that already ended.",
        structured_output=True,
    )
    async def stop_recording(tab_id: str) -> StopRecordingResult:
        return await invoke(application.stop_recording(tab_id=tab_id))
