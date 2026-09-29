from __future__ import annotations

from pathlib import Path

import anyio
import pytest
from mcp.client.session import ClientSession
from mcp.shared.message import SessionMessage

from browser_automation.application import BrowserApplication
from browser_automation.mcp.config import McpRuntimeConfig
from browser_automation.mcp.server import create_server

from .conftest import LocalSite
from .support import LiveChrome


pytestmark = [pytest.mark.integration, pytest.mark.real_chrome]


async def _with_client(server, client_callable) -> None:
    client_to_server_send, server_read = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    server_to_client_send, client_read = anyio.create_memory_object_stream[SessionMessage](0)

    async def serve() -> None:
        await server._mcp_server.run(  # type: ignore[attr-defined]
            server_read, server_to_client_send,
            server._mcp_server.create_initialization_options(),  # type: ignore[attr-defined]
            raise_exceptions=True,
        )

    async with anyio.create_task_group() as group:
        group.start_soon(serve)
        async with ClientSession(client_read, client_to_server_send) as session:
            await session.initialize()
            await client_callable(session)
        await client_to_server_send.aclose()
        await server_to_client_send.aclose()
        group.cancel_scope.cancel()


@pytest.mark.anyio
async def test_mcp_run_script_and_navigate_take_the_same_dialog_decision(
    live_chrome: LiveChrome, test_site: LocalSite, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in live_chrome.environment(tmp_path, BROWSER_AUTOMATION_ATTACH_ONLY="1").items():
        monkeypatch.setenv(name, value)
    server = create_server(runtime_config=McpRuntimeConfig(), application=BrowserApplication())

    async def client(session: ClientSession) -> None:
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}
        assert set(tools["run_script"].inputSchema["properties"]) >= {"dialog", "prompt_text"}
        assert set(tools["navigate_to"].inputSchema["properties"]) >= {"dialog", "prompt_text"}
        assert "dialog" not in tools["close_tab"].inputSchema["properties"]

        opened = await session.call_tool("open_tab", {"url": test_site.url("/demo")})
        tab_id = opened.structuredContent["tab_id"]

        accepted = await session.call_tool("run_script", {"tab_id": tab_id, "script": "askDelete()", "dialog": "accept"})
        assert not accepted.isError, accepted.content
        # run_script returns a union (inline | artifact), which FastMCP wraps as {"result": …}.
        assert accepted.structuredContent["result"]["result"] is True
        assert accepted.structuredContent["result"]["dialogs"][0]["outcome"] == "accepted"

        plain = await session.call_tool("run_script", {"tab_id": tab_id, "script": "1 + 1"})
        assert plain.structuredContent["result"]["result"] == 2
        assert plain.structuredContent["result"].get("dialogs") is None

        undecided = await session.call_tool("run_script", {"tab_id": tab_id, "script": "askDelete()"})
        assert undecided.isError
        assert "DIALOG_DECISION_REQUIRED" in undecided.content[0].text

        navigated = await session.call_tool("navigate_to", {
            "tab_id": tab_id, "url": test_site.url("/confirm-on-load"), "dialog": "dismiss",
        })
        assert not navigated.isError, navigated.content
        assert navigated.structuredContent["dialogs"][0]["outcome"] == "dismissed"

    await _with_client(server, client)
