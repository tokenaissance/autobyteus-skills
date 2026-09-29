from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from browser_automation.application import BrowserApplication
from browser_automation.contracts import RunScriptResult


def register(server: FastMCP, application: BrowserApplication) -> None:
    from browser_automation.mcp.tools import invoke

    @server.tool(name="run_script", title="Run script", description="Advanced: evaluate JavaScript in one explicit tab. If the page opens a confirm/prompt/leave-page dialog, pass dialog=accept|dismiss (prompt_text for prompts); without it the dialog is dismissed and the call fails with DIALOG_DECISION_REQUIRED.", structured_output=True)
    async def run_script(
        tab_id: str,
        script: str,
        arg: Any | None = None,
        output_file: str | None = None,
        overwrite: bool = False,
        dialog: Literal["accept", "dismiss"] | None = None,
        prompt_text: str | None = None,
    ) -> RunScriptResult:
        return await invoke(
            application.run_script(
                tab_id=tab_id,
                script=script,
                arg=arg,
                output_file=output_file,
                overwrite=overwrite,
                dialog=dialog,
                prompt_text=prompt_text,
            )
        )
