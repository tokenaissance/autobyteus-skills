from __future__ import annotations

from typing import Any

import anyio
import pytest
from mcp.client.session import ClientSession
from mcp.shared.message import SessionMessage

from browser_automation.mcp.config import McpRuntimeConfig
from browser_automation.mcp.server import create_server


class FakeApplication:
    calls: list[tuple[str, dict[str, Any]]]

    def __init__(self) -> None:
        self.calls = []

    async def open_tab(self, **kwargs):
        self.calls.append(("open_tab", kwargs))
        return {"tab_id": "opaque-1", "url": kwargs.get("url") or "about:blank", "title": "Example"}

    async def attach_tab(self, **kwargs):
        self.calls.append(("attach_tab", kwargs))
        return {"tab_id": "opaque-1", "url": "https://example.com", "title": "Example"}

    async def close_tab(self, **kwargs):
        self.calls.append(("close_tab", kwargs))
        return {"tab_id": kwargs["tab_id"], "closed": True}

    async def list_tabs(self):
        self.calls.append(("list_tabs", {}))
        return {"tabs": [{"tab_id": "opaque-1", "url": "https://example.com", "title": "Example"}]}

    async def navigate(self, **kwargs):
        self.calls.append(("navigate", kwargs))
        return {"tab_id": kwargs["tab_id"], "url": kwargs["url"], "ok": True, "status": 200}

    async def read_page(self, **kwargs):
        self.calls.append(("read_page", kwargs))
        return {
            "tab_id": kwargs["tab_id"],
            "url": "https://example.com",
            "output_mode": "inline",
            "content": "Example",
        }

    async def screenshot(self, **kwargs):
        self.calls.append(("screenshot", kwargs))
        return {
            "tab_id": kwargs["tab_id"],
            "url": "https://example.com",
            "artifact": {"path": "/workspace/shot.png", "media_type": "image/png", "bytes_written": 3},
        }

    async def dom_snapshot(self, **kwargs):
        self.calls.append(("dom_snapshot", kwargs))
        return {
            "tab_id": kwargs["tab_id"],
            "url": "https://example.com",
            "output_mode": "inline",
            "elements": [],
            "total_candidates": 0,
            "returned_elements": 0,
            "truncated": False,
        }

    async def run_script(self, **kwargs):
        self.calls.append(("run_script", kwargs))
        return {
            "tab_id": kwargs["tab_id"],
            "url": "https://example.com",
            "output_mode": "inline",
            "result": 2,
        }


async def _run_with_session(server, client_callable) -> None:
    client_to_server_send, server_read_stream = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    server_to_client_send, client_read_stream = anyio.create_memory_object_stream[SessionMessage](0)

    async def server_task() -> None:
        await server._mcp_server.run(  # type: ignore[attr-defined]
            server_read_stream,
            server_to_client_send,
            server._mcp_server.create_initialization_options(),  # type: ignore[attr-defined]
            raise_exceptions=True,
        )

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(server_task)
        async with ClientSession(client_read_stream, client_to_server_send) as session:
            await session.initialize()
            await client_callable(session)
        await client_to_server_send.aclose()
        await server_to_client_send.aclose()
        task_group.cancel_scope.cancel()


@pytest.mark.anyio
async def test_retained_mcp_inventory_delegates_to_one_application() -> None:
    application = FakeApplication()
    server = create_server(
        runtime_config=McpRuntimeConfig(),
        application=application,  # type: ignore[arg-type]
    )

    async def run_client(session: ClientSession) -> None:
        tools = await session.list_tools()
        assert {tool.name for tool in tools.tools} == {
            "open_tab",
            "attach_tab",
            "close_tab",
            "list_tabs",
            "navigate_to",
            "read_page",
            "screenshot",
            "dom_snapshot",
            "run_script",
        }
        calls = [
            ("open_tab", {"url": "https://example.com"}),
            ("attach_tab", {"url_contains": "example.com"}),
            ("list_tabs", {}),
            ("navigate_to", {"tab_id": "opaque-1", "url": "https://example.com/next"}),
            ("read_page", {"tab_id": "opaque-1", "cleaning_mode": "text"}),
            ("screenshot", {"tab_id": "opaque-1", "file_path": "shot.png"}),
            ("dom_snapshot", {"tab_id": "opaque-1"}),
            ("run_script", {"tab_id": "opaque-1", "script": "1 + 1"}),
            ("close_tab", {"tab_id": "opaque-1"}),
        ]
        for name, arguments in calls:
            result = await session.call_tool(name, arguments)
            assert not result.isError, (name, result.content)
            assert result.structuredContent is not None

    await _run_with_session(server, run_client)
    assert [name for name, _kwargs in application.calls] == [
        "open_tab",
        "attach_tab",
        "list_tabs",
        "navigate",
        "read_page",
        "screenshot",
        "dom_snapshot",
        "run_script",
        "close_tab",
    ]
