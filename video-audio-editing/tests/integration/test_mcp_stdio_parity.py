"""Real MCP stdio session: legacy tool contract, and parity with the CLI on real media."""

import asyncio
import shutil

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .support import HAS_FFMPEG, MCP_LAUNCHER, SAMPLE_VIDEO, probe_duration, run_launcher

pytestmark = [pytest.mark.integration, pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")]


async def _mcp(workspace, calls):
    params = StdioServerParameters(command=str(MCP_LAUNCHER), env={"AUTOBYTEUS_AGENT_WORKSPACE": str(workspace),
                                                                  "PATH": __import__("os").environ["PATH"],
                                                                  "HOME": __import__("os").environ.get("HOME", "/tmp")})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            results = [await session.call_tool(name, args) for name, args in calls]
            return len(tools.tools), results


def test_mcp_and_cli_produce_equivalent_media(tmp_path):
    shutil.copy(SAMPLE_VIDEO, tmp_path / "in.mp4")
    count, results = asyncio.run(_mcp(tmp_path, [
        ("health_check", {}),
        ("trim_video", {"video_path": "in.mp4", "output_video_path": "mcp.mp4", "start_time": "1", "end_time": "3"}),
        ("get_media_duration", {"media_path": "in.mp4"}),
        ("trim_video", {"video_path": "missing.mp4", "output_video_path": "x.mp4", "start_time": "0", "end_time": "1"}),
    ]))
    assert count == 32
    assert results[0].content[0].text == "Server is healthy!"
    assert "Video trimmed successfully" in results[1].content[0].text
    assert abs(float(results[2].content[0].text) - probe_duration(tmp_path / "in.mp4")) < 0.01
    assert results[3].content[0].text.startswith("An unexpected error") or "rror" in results[3].content[0].text

    status, env, _ = run_launcher(tmp_path, "trim-video", "--video-path", "in.mp4", "--output-video-path", "cli.mp4",
                                  "--start-time", "1", "--end-time", "3")
    assert status == 0
    assert abs(probe_duration(tmp_path / "mcp.mp4") - probe_duration(tmp_path / "cli.mp4")) < 0.1
