"""Golden contract: the 32 MCP tools must match the pre-change baseline exactly."""

import asyncio
import json
from pathlib import Path

from video_audio.mcp.server import create_server

BASELINE = json.loads((Path(__file__).resolve().parent.parent / "fixtures" / "mcp-tools-baseline.json").read_text())


def _tools():
    return asyncio.run(create_server().list_tools())


def test_tool_names_match_baseline():
    assert sorted(t.name for t in _tools()) == sorted(b["name"] for b in BASELINE)
    assert len(BASELINE) == 32


def test_each_tool_contract_matches_baseline():
    by_name = {t.name: t for t in _tools()}
    for expected in BASELINE:
        tool = by_name[expected["name"]]
        assert tool.description == expected["description"], expected["name"]
        assert tool.inputSchema == expected["inputSchema"], expected["name"]
        assert tool.outputSchema == expected["outputSchema"], expected["name"]
