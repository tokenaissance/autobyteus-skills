from __future__ import annotations

from contextlib import asynccontextmanager
import os
from pathlib import Path
import subprocess
import uuid

import anyio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client
import pytest

from .conftest import LocalSite
from .support import MCP_LAUNCHER, LiveChrome, free_port, terminate_process_group, wait_for_tcp


pytestmark = pytest.mark.integration

EXPECTED_TOOLS = {
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


def structured_result(call_result) -> dict:
    """Return the tool result described by its MCP output schema.

    FastMCP represents union/root result schemas as an object with a required
    ``result`` property, while single TypedDict results are emitted directly.
    Both shapes are advertised in list_tools output and are protocol-valid.
    """

    structured = call_result.structuredContent
    assert isinstance(structured, dict), structured
    value = structured.get("result", structured)
    assert isinstance(value, dict), value
    return value


@pytest.mark.anyio
@pytest.mark.real_chrome
async def test_production_stdio_mcp_launcher_inventory_real_operation_and_error(
    live_chrome: LiveChrome,
    test_site: LocalSite,
    tmp_path: Path,
) -> None:
    log_dir = tmp_path / "mcp-logs"
    environment = live_chrome.environment(tmp_path, BROWSER_MCP_LOG_DIR=str(log_dir))
    errlog_path = tmp_path / "stdio-client.err"
    errlog = errlog_path.open("w", encoding="utf-8")
    try:
        parameters = StdioServerParameters(
            command="bash",
            args=[str(MCP_LAUNCHER)],
            env=environment,
            cwd=str(tmp_path),
        )
        async with stdio_client(parameters, errlog=errlog) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {tool.name for tool in tools.tools} == EXPECTED_TOOLS

                token = uuid.uuid4().hex
                opened = await session.call_tool("open_tab", {"url": test_site.url(f"/page?token={token}")})
                assert not opened.isError, opened.content
                tab_id = structured_result(opened)["tab_id"]
                read = await session.call_tool("read_page", {"tab_id": tab_id, "cleaning_mode": "text"})
                assert not read.isError, read.content
                assert f"Integration Page {token}" in structured_result(read)["content"]
                scripted = await session.call_tool(
                    "run_script",
                    {"tab_id": tab_id, "script": "({title:document.title,target:arg.target})", "arg": {"target": tab_id}},
                )
                assert not scripted.isError, scripted.content
                assert structured_result(scripted)["result"]["target"] == tab_id

                stale = await session.call_tool("read_page", {"tab_id": "not-a-live-target"})
                assert stale.isError
                assert "TAB_NOT_FOUND" in " ".join(getattr(item, "text", "") for item in stale.content)

                closed = await session.call_tool("close_tab", {"tab_id": tab_id})
                assert not closed.isError, closed.content
                assert structured_result(closed)["closed"] is True
    finally:
        errlog.close()
    assert live_chrome.process.poll() is None
    assert (log_dir / "browser-mcp.log").is_file()


@asynccontextmanager
async def running_http_mcp(
    live_chrome: LiveChrome,
    workspace: Path,
    *,
    host: str | None,
):
    port = free_port()
    log_dir = workspace / f"http-mcp-{port}"
    environment = live_chrome.environment(
        workspace,
        BROWSER_MCP_LOG_DIR=str(log_dir),
        BROWSER_MCP_TRANSPORT="streamable-http",
        BROWSER_MCP_PORT=str(port),
    )
    if host is not None:
        environment["BROWSER_MCP_HOST"] = host
    process = subprocess.Popen(
        ["bash", str(MCP_LAUNCHER)],
        cwd=workspace,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        await anyio.to_thread.run_sync(wait_for_tcp, "127.0.0.1", port)
        yield process, port, log_dir
    finally:
        terminate_process_group(process)


async def exercise_http_session(port: int, test_site: LocalSite) -> None:
    async with streamable_http_client(f"http://127.0.0.1:{port}/mcp") as (
        read_stream,
        write_stream,
        _get_session_id,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {tool.name for tool in tools.tools} == EXPECTED_TOOLS
            token = uuid.uuid4().hex
            opened = await session.call_tool("open_tab", {"url": test_site.url(f"/page?token=http-{token}")})
            assert not opened.isError, opened.content
            tab_id = structured_result(opened)["tab_id"]
            read = await session.call_tool("read_page", {"tab_id": tab_id, "cleaning_mode": "text"})
            assert not read.isError, read.content
            assert f"Integration Page http-{token}" in structured_result(read)["content"]
            closed = await session.call_tool("close_tab", {"tab_id": tab_id})
            assert not closed.isError, closed.content


@pytest.mark.anyio
@pytest.mark.real_chrome
async def test_streamable_http_default_loopback_and_explicit_remote_warning(
    live_chrome: LiveChrome,
    test_site: LocalSite,
    tmp_path: Path,
) -> None:
    async with running_http_mcp(live_chrome, tmp_path, host=None) as (process, port, log_dir):
        await exercise_http_session(port, test_site)
        assert process.poll() is None
    default_log = (log_dir / "browser-mcp.log").read_text(errors="replace")
    assert f"127.0.0.1:{port}" in default_log
    assert "without built-in authentication" not in default_log

    async with running_http_mcp(live_chrome, tmp_path, host="0.0.0.0") as (process, port, log_dir):
        await exercise_http_session(port, test_site)
        assert process.poll() is None
    remote_log = (log_dir / "browser-mcp.log").read_text(errors="replace")
    assert remote_log.count("without built-in authentication") == 1
    assert "0.0.0.0" in remote_log


def test_mcp_invalid_host_and_port_fail_before_server_start(tmp_path: Path) -> None:
    for key, value, expected in (
        ("BROWSER_MCP_HOST", "bad host", "must not contain whitespace"),
        ("BROWSER_MCP_PORT", "70000", "range 1..65535"),
    ):
        log_dir = tmp_path / f"invalid-{key.lower()}"
        environment = os.environ.copy()
        environment.update(
            {
                "BROWSER_AUTOMATION_WORKSPACE": str(tmp_path),
                "BROWSER_MCP_LOG_DIR": str(log_dir),
                "BROWSER_MCP_TRANSPORT": "streamable-http",
                "BROWSER_MCP_PORT": str(free_port()),
            }
        )
        environment[key] = value
        completed = subprocess.run(
            ["bash", str(MCP_LAUNCHER)],
            cwd=tmp_path,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=60,
        )
        assert completed.returncode != 0
        assert completed.stdout == b""
        log = (log_dir / "browser-mcp.log").read_text(errors="replace")
        assert expected in log
