from mcp.server.fastmcp import FastMCP

from browser_automation.application import BrowserApplication
from browser_automation.contracts import StartRecordingResult


def register(server: FastMCP, application: BrowserApplication) -> None:
    from browser_automation.mcp.tools import invoke

    @server.tool(
        name="start_recording",
        title="Start recording",
        description=(
            "Start recording one tab to an MP4 inside the agent workspace. Recording continues in the "
            "background across other tool calls until stop_recording or until the tab closes."
        ),
        structured_output=True,
    )
    async def start_recording(
        tab_id: str,
        output_file: str,
        fps: int = 25,
        overwrite: bool = False,
    ) -> StartRecordingResult:
        return await invoke(
            application.start_recording(tab_id=tab_id, output_file=output_file, fps=fps, overwrite=overwrite)
        )
