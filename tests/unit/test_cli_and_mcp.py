from __future__ import annotations

import asyncio
import json
import io
import math
import subprocess
import sys
from pathlib import Path

import pytest

import browser_automation.cli as cli
import browser_automation.mcp.server as mcp_server
from browser_automation.errors import BrowserError
from browser_automation.json_codec import loads_strict
from browser_automation.mcp.config import McpConfigError, McpRuntimeConfig, McpServerConfig
from browser_automation.mcp.server import create_server


@pytest.mark.parametrize(
    ("argv", "stdin_text", "expected_script", "expected_arg"),
    [
        (
            [
                "run-script",
                "--tab-id",
                "opaque-target",
                "--script",
                "(arg) => ({label: arg.label})",
                "--arg-json",
                '{"label":"direct"}',
            ],
            "",
            "(arg) => ({label: arg.label})",
            {"label": "direct"},
        ),
        (
            [
                "run-script",
                "--tab-id",
                "opaque-target",
                "--script-file",
                "inputs/action.js",
                "--arg-file",
                "inputs/arg.json",
            ],
            "",
            "(arg) => arg.count + 1",
            {"count": 2},
        ),
        (
            ["run-script", "--tab-id", "opaque-target", "--script-stdin"],
            "(arg) => document.title",
            "(arg) => document.title",
            None,
        ),
    ],
)
def test_cli_run_script_sources_map_to_the_same_application_arguments(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    stdin_text: str,
    expected_script: str,
    expected_arg,
) -> None:
    captured: dict[str, object] = {}
    files = {
        "inputs/action.js": "(arg) => arg.count + 1",
        "inputs/arg.json": '{"count":2}',
    }

    class FakeApplication:
        def read_input_text(self, path: str) -> str:
            return files[path]

        async def run_script(self, **kwargs):
            captured.update(kwargs)
            return {"result": "ok"}

    monkeypatch.setattr(cli, "BrowserApplication", FakeApplication)
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_text))
    result = asyncio.run(cli.execute(cli.build_parser().parse_args(argv)))
    assert result == {"result": "ok"}
    assert captured == {
        "tab_id": "opaque-target",
        "script": expected_script,
        "arg": expected_arg,
        "output_file": None,
        "overwrite": False,
    }


def test_cli_success_and_stable_error_envelopes(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    async def success(_args):
        return {"tabs": []}

    monkeypatch.setattr(cli, "execute", success)
    assert cli.main(["list-tabs"]) == 0
    success_payload = json.loads(capsys.readouterr().out)
    assert success_payload == {
        "schema_version": "1",
        "ok": True,
        "command": "list-tabs",
        "result": {"tabs": []},
    }

    async def failure(_args):
        raise BrowserError("TAB_NOT_FOUND", "gone", retryable=True, exit_status=4)

    monkeypatch.setattr(cli, "execute", failure)
    assert cli.main(["list-tabs"]) == 4
    error_payload = json.loads(capsys.readouterr().out)
    assert error_payload["error"] == {"code": "TAB_NOT_FOUND", "message": "gone", "retryable": True}


def test_cli_readiness_marker_precedes_parsing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:
    marker = tmp_path / "ready"
    monkeypatch.setenv(cli.READY_ENV, str(marker))
    assert cli.main([]) == 2
    assert marker.read_text().strip() == cli.READY_TOKEN
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "INVALID_ARGUMENT"


def test_mcp_runtime_defaults_validation_and_inventory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert cli.build_parser().prog == "browser"
    default_server = McpServerConfig.from_env({})
    assert default_server.name == "browser-automation"
    assert "shared browser application" in default_server.instructions

    default = McpRuntimeConfig.from_env({})
    assert default.host == "127.0.0.1"
    assert default.is_loopback
    assert not default.requires_exposure_warning

    remote = McpRuntimeConfig.from_env({
        "BROWSER_MCP_TRANSPORT": "streamable-http",
        "BROWSER_MCP_HOST": "0.0.0.0",
        "BROWSER_MCP_PORT": "9000",
    })
    assert remote.requires_exposure_warning
    with pytest.raises(McpConfigError):
        McpRuntimeConfig.from_env({"BROWSER_MCP_PORT": "70000"})
    with pytest.raises(McpConfigError):
        McpRuntimeConfig.from_env({"BROWSER_MCP_HOST": "bad host"})

    monkeypatch.setenv("BROWSER_AUTOMATION_WORKSPACE", str(tmp_path))
    server = create_server(runtime_config=default)
    assert sorted(server._tool_manager._tools) == [  # type: ignore[attr-defined]
        "attach_tab",
        "close_tab",
        "dom_snapshot",
        "list_tabs",
        "navigate_to",
        "open_tab",
        "read_page",
        "run_script",
        "screenshot",
    ]
    close_schema = server._tool_manager._tools["close_tab"].parameters  # type: ignore[attr-defined]
    assert "close_browser" not in close_schema.get("properties", {})


def test_mcp_main_warns_once_for_non_loopback_http(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    runtime = McpRuntimeConfig(transport="streamable-http", host="0.0.0.0", port=8765)
    monkeypatch.setattr(mcp_server.McpRuntimeConfig, "from_env", classmethod(lambda cls, env=None: runtime))
    monkeypatch.setattr(
        mcp_server.McpServerConfig,
        "from_env",
        classmethod(lambda cls, env=None: McpServerConfig()),
    )

    class FakeServer:
        def run(self, *, transport: str) -> None:
            assert transport == "streamable-http"

    monkeypatch.setattr(mcp_server, "create_server", lambda **_kwargs: FakeServer())
    with caplog.at_level("WARNING"):
        mcp_server.main()
    warnings = [record.message for record in caplog.records if "without built-in authentication" in record.message]
    assert len(warnings) == 1


@pytest.mark.parametrize("raw_arg", ["NaN", "Infinity", "-Infinity", '[1,{"nested":NaN}]', "1e999"])
def test_cli_rejects_non_finite_json_arguments_with_one_strict_envelope(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
    raw_arg: str,
) -> None:
    class FakeApplication:
        async def run_script(self, **_kwargs):
            raise AssertionError("Invalid JSON must fail before browser invocation")

    monkeypatch.setattr(cli, "BrowserApplication", FakeApplication)
    status = cli.main(
        ["run-script", "--tab-id", "opaque", "--script", "1", "--arg-json", raw_arg]
    )
    lines = capsys.readouterr().out.splitlines()
    assert status == 2
    assert len(lines) == 1
    payload = loads_strict(lines[0])
    assert payload["error"]["code"] == "INVALID_ARGUMENT"


@pytest.mark.parametrize("result", [math.nan, math.inf, -math.inf, {"nested": [math.nan]}])
def test_final_cli_encoder_falls_back_to_one_strict_internal_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
    result,
) -> None:
    async def non_finite_result(_args):
        return {"value": result}

    monkeypatch.setattr(cli, "execute", non_finite_result)
    status = cli.main(["list-tabs"])
    lines = capsys.readouterr().out.splitlines()
    assert status == 5
    assert len(lines) == 1
    payload = loads_strict(lines[0])
    assert payload["ok"] is False
    assert payload["error"]["code"] == "INTERNAL_ERROR"


@pytest.mark.parametrize(
    ("shape", "codepoint"),
    [
        ("top", "d800"),
        ("top", "dfff"),
        ("nested", "d800"),
        ("nested", "dfff"),
    ],
)
def test_cli_subprocess_writes_lone_surrogates_as_one_utf8_safe_envelope(
    shape: str,
    codepoint: str,
) -> None:
    probe = """
import sys
import browser_automation.cli as cli

value = chr(int(sys.argv[2], 16))
result = value if sys.argv[1] == "top" else {"nested": [value]}

async def fake_execute(_args):
    return result

cli.execute = fake_execute
raise SystemExit(cli.main(["list-tabs"]))
"""
    completed = subprocess.run(
        [sys.executable, "-c", probe, shape, codepoint],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    assert completed.stderr == b""
    assert len(completed.stdout.splitlines()) == 1
    payload = loads_strict(completed.stdout.decode("utf-8", errors="strict"))
    expected = chr(int(codepoint, 16))
    expected_result = expected if shape == "top" else {"nested": [expected]}
    assert payload == {
        "schema_version": "1",
        "ok": True,
        "command": "list-tabs",
        "result": expected_result,
    }
