import logging
from typing import Literal

from mcp.server.fastmcp import Context, FastMCP

from browser_automation.application import BrowserApplication
from browser_automation.contracts import NavigateResult

logger = logging.getLogger(__name__)


def register(server: FastMCP, application: BrowserApplication) -> None:
    from browser_automation.mcp.tools import invoke

    @server.tool(name="navigate_to", title="Navigate to URL", description="Navigate one explicit tab to an HTTP(S) URL. If the page opens a leave-page or other dialog, pass dialog=accept|dismiss (prompt_text for prompts); without it the dialog is dismissed and the call fails with DIALOG_DECISION_REQUIRED.", structured_output=True)
    async def navigate_to(
        tab_id: str,
        url: str,
        wait_until: str = "domcontentloaded",
        timeout_ms: int = 60_000,
        dialog: Literal["accept", "dismiss"] | None = None,
        prompt_text: str | None = None,
        *,
        context: Context,
    ) -> NavigateResult:
        result = await invoke(
            application.navigate(
                tab_id=tab_id,
                url=url,
                wait_until=wait_until,
                timeout_ms=timeout_ms,
                dialog=dialog,
                prompt_text=prompt_text,
            )
        )
        try:
            await context.report_progress(1, 1, f"Navigated to {result['url']}")
        except Exception as exc:
            logger.debug("MCP client did not accept optional navigation progress: %s", exc)
        return result
