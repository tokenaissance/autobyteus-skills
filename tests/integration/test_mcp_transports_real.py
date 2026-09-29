from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import shutil
import socket
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
    "start_recording",
    "stop_recording",
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


@asynccontextmanager
async def stdio_mcp_session(environment: dict[str, str], workspace: Path, name: str):
    errlog = (workspace / f"{name}-stdio-client.err").open("w", encoding="utf-8")
    try:
        parameters = StdioServerParameters(command="bash", args=[str(MCP_LAUNCHER)], env=environment, cwd=str(workspace))
        async with stdio_client(parameters, errlog=errlog) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session
    finally:
        errlog.close()


def error_text(call_result) -> str:
    assert call_result.isError, call_result.content
    return " ".join(getattr(item, "text", "") for item in call_result.content)


@pytest.mark.anyio
@pytest.mark.real_chrome
async def test_stdio_mcp_recording_survives_concurrent_calls_and_stops_from_another_process(
    live_chrome: LiveChrome,
    test_site: LocalSite,
    tmp_path: Path,
) -> None:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is required for recording coverage")
    environment = live_chrome.environment(tmp_path, BROWSER_MCP_LOG_DIR=str(tmp_path / "mcp-logs"))

    async with stdio_mcp_session(environment, tmp_path, "recorder") as session:
        opened = await session.call_tool("open_tab", {"url": test_site.url("/demo")})
        assert not opened.isError, opened.content
        tab_id = structured_result(opened)["tab_id"]
        started = await session.call_tool(
            "start_recording", {"tab_id": tab_id, "output_file": "clips/mcp.mp4", "fps": 10}
        )
        assert not started.isError, started.content
        assert structured_result(started)["output_file"] == str((tmp_path / "clips" / "mcp.mp4").resolve())
        assert "RECORDING_ALREADY_ACTIVE" in error_text(
            await session.call_tool("start_recording", {"tab_id": tab_id, "output_file": "other.mp4"})
        )
        # Ordinary tools run concurrently while the background screencast is active.
        for round_index in range(3):
            results = await asyncio.gather(
                session.call_tool("run_script", {"tab_id": tab_id,
                                                 "script": f"__abDemo.caption('round {round_index}')"}),
                session.call_tool("screenshot", {"tab_id": tab_id, "file_path": f"during-{round_index}.png",
                                                 "full_page": False}),
                session.call_tool("dom_snapshot", {"tab_id": tab_id, "max_elements": 20}),
                session.call_tool("read_page", {"tab_id": tab_id, "cleaning_mode": "text"}),
                session.call_tool("list_tabs", {}),
            )
            assert [result.content for result in results if result.isError] == []
            assert structured_result(results[0])["result"]["ok"] is True
        await asyncio.sleep(1.0)

    # The MCP process that started the recording has exited; a different one finishes it.
    async with stdio_mcp_session(environment, tmp_path, "stopper") as session:
        stopped = await session.call_tool("stop_recording", {"tab_id": tab_id})
        assert not stopped.isError, stopped.content
        result = structured_result(stopped)
        artifact = Path(result["artifact"]["path"])
        assert artifact == (tmp_path / "clips" / "mcp.mp4").resolve()
        assert result["artifact"]["bytes_written"] == artifact.stat().st_size > 0
        assert result["end_reason"] == "stopped" and result["frames"] >= 10
        assert "RECORDING_NOT_ACTIVE" in error_text(await session.call_tool("stop_recording", {"tab_id": tab_id}))
        closed = await session.call_tool("close_tab", {"tab_id": tab_id})
        assert not closed.isError, closed.content


@pytest.mark.anyio
@pytest.mark.real_chrome
async def test_stdio_mcp_attach_only_reports_unavailable_and_never_launches_a_browser(tmp_path: Path) -> None:
    port = free_port()
    profile = tmp_path / "must-not-exist-profile"
    environment = os.environ.copy()
    environment.update(
        {
            "CHROME_REMOTE_DEBUGGING_PORT": str(port),
            "CHROME_USER_DATA_DIR": str(profile),
            "BROWSER_AUTOMATION_ATTACH_ONLY": "1",
            "BROWSER_AUTOMATION_WORKSPACE": str(tmp_path),
            "BROWSER_MCP_LOG_DIR": str(tmp_path / "mcp-logs"),
        }
    )
    async with stdio_mcp_session(environment, tmp_path, "attach-only") as session:
        assert {tool.name for tool in (await session.list_tools()).tools} == EXPECTED_TOOLS
        for tool, arguments in (("list_tabs", {}), ("open_tab", {"url": "http://127.0.0.1:9/"})):
            message = error_text(await session.call_tool(tool, arguments))
            assert "BROWSER_UNAVAILABLE" in message
            assert f"127.0.0.1:{port}" in message and "BROWSER_AUTOMATION_ATTACH_ONLY" in message
    assert not profile.exists()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.2)
        assert probe.connect_ex(("127.0.0.1", port)) != 0
