import json
from pathlib import Path

from video_audio.cli import build_parser
from video_audio.cli_parser import cli_name, map_parameters
from video_audio.operations.registry import all_operations

BASELINE = json.loads((Path(__file__).resolve().parent.parent / "fixtures" / "mcp-tools-baseline.json").read_text())


def test_registry_has_every_baseline_tool_once():
    names = [s.name for s in all_operations()]
    assert sorted(names) == sorted(b["name"] for b in BASELINE)
    assert len(set(names)) == 32


def test_every_operation_is_a_cli_subcommand_with_isomorphic_options():
    _, table = build_parser()
    by_name = {b["name"]: b for b in BASELINE}
    for spec in all_operations():
        cli_spec, mappings = table[cli_name(spec.name)]
        schema = by_name[spec.name]["inputSchema"]
        assert set(schema.get("properties", {})) == {m.name for m in mappings.values()}, spec.name
        parser_required = {
            a.dest for a in _subparser_actions(spec)
            if a.required
        }
        expected = {m.dest for m in map_parameters(spec) if m.name in schema.get("required", [])}
        assert parser_required == expected, spec.name


def _subparser_actions(spec):
    parser, _ = build_parser()
    sub = next(a for a in parser._actions if a.dest == "command")
    return sub.choices[cli_name(spec.name)]._actions


def test_structured_arguments_use_json_options():
    _, table = build_parser()
    options = {m.option for _, mappings in table.values() for m in mappings.values() if m.is_json}
    assert options == {
        "--video-paths-json", "--audio-paths-json", "--text-elements-json",
        "--broll-clips-json", "--font-style-json",
    }


def test_writing_commands_accept_overwrite_and_readers_do_not():
    parser, table = build_parser()
    sub = next(a for a in parser._actions if a.dest == "command").choices
    for spec in all_operations():
        flags = {o for a in sub[cli_name(spec.name)]._actions for o in a.option_strings}
        assert ("--overwrite" in flags) == spec.writes_output, spec.name
    assert not table["health-check"][0].writes_output
    assert not table["get-media-duration"][0].writes_output


def test_default_true_boolean_has_negative_form():
    parser, _ = build_parser()
    trim = next(a for a in parser._actions if a.dest == "command").choices["trim-video"]
    flags = {o for a in trim._actions for o in a.option_strings}
    assert {"--reencode", "--no-reencode"} <= flags
