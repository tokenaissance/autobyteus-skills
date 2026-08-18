from mcp.server.fastmcp import FastMCP

from browser_automation.application import BrowserApplication
from browser_automation.contracts import DomSnapshotResult


def register(server: FastMCP, application: BrowserApplication) -> None:
    from browser_automation.mcp.tools import invoke

    @server.tool(name="dom_snapshot", title="DOM snapshot", description="Capture actionable DOM elements for one explicit tab.", structured_output=True)
    async def dom_snapshot(
        tab_id: str,
        include_non_interactive: bool = False,
        include_bounding_boxes: bool = True,
        max_elements: int = 200,
        output_file: str | None = None,
        overwrite: bool = False,
    ) -> DomSnapshotResult:
        return await invoke(
            application.dom_snapshot(
                tab_id=tab_id,
                include_non_interactive=include_non_interactive,
                include_bounding_boxes=include_bounding_boxes,
                max_elements=max_elements,
                output_file=output_file,
                overwrite=overwrite,
            )
        )
