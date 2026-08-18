from mcp.server.fastmcp import FastMCP

from browser_automation.application import BrowserApplication
from browser_automation.contracts import ScreenshotResult


def register(server: FastMCP, application: BrowserApplication) -> None:
    from browser_automation.mcp.tools import invoke

    @server.tool(name="screenshot", title="Screenshot", description="Save one tab screenshot inside the agent workspace.", structured_output=True)
    async def screenshot(
        tab_id: str,
        file_path: str,
        full_page: bool = True,
        image_format: str = "png",
        overwrite: bool = False,
    ) -> ScreenshotResult:
        return await invoke(
            application.screenshot(
                tab_id=tab_id,
                output_file=file_path,
                full_page=full_page,
                image_format=image_format,
                overwrite=overwrite,
            )
        )
