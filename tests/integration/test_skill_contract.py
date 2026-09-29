"""SKILL.md, agent metadata and launcher must agree with the real CLI."""

import re

import pytest

from video_audio.cli import build_parser
from video_audio.cli_parser import cli_name
from video_audio.operations.registry import all_operations

from .support import BUNDLE, LAUNCHER, MCP_LAUNCHER

pytestmark = pytest.mark.integration
SKILL = (BUNDLE / "SKILL.md").read_text()


def test_frontmatter_and_metadata():
    front = SKILL.split("---")[1]
    assert re.search(r"^name: video-audio-editing$", front, re.M)
    assert re.search(r"^description: .{40,}", front, re.M)
    agent = (BUNDLE / "agents" / "openai.yaml").read_text()
    assert "$video-audio-editing" in agent and "display_name" in agent


def test_launchers_are_executable_and_bundled_files_present():
    for path in (LAUNCHER, MCP_LAUNCHER):
        assert path.stat().st_mode & 0o111
    for name in ("pyproject.toml", "uv.lock", "SKILL.md"):
        assert (BUNDLE / name).is_file()


def test_documented_commands_and_flags_exist():
    parser, _ = build_parser()
    commands = next(a for a in parser._actions if a.dest == "command").choices
    for line in re.findall(r"`([a-z][a-z-]+ --[^`]+)`", SKILL):
        command = line.split()[0]
        assert command in commands, command
        flags = {o for a in commands[command]._actions for o in a.option_strings}
        for flag in re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", line):
            assert flag in flags, f"{command} {flag}"


def test_skill_has_no_direct_python_or_vendor_paths():
    assert "python " not in SKILL.lower().replace("python/uv", "")
    assert ".claude" not in SKILL and ".codex" not in SKILL


def test_every_operation_is_reachable_as_a_command():
    parser, _ = build_parser()
    commands = next(a for a in parser._actions if a.dest == "command").choices
    assert {cli_name(s.name) for s in all_operations()} == set(commands)
