"""Task-oriented browser CLI and versioned machine-output contract."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from browser_automation.application import BrowserApplication
from browser_automation.errors import BrowserError, invalid_argument
from browser_automation.json_codec import StrictJsonError, dumps_strict, loads_strict

SCHEMA_VERSION = "1"
READY_ENV = "BROWSER_AUTOMATION_CLI_READY_FILE"
READY_TOKEN = "browser-cli-ready-v1"


class CliUsageError(Exception):
    pass


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliUsageError(message)

    def exit(self, status: int = 0, message: str | None = None) -> None:
        if message:
            self._print_message(message, sys.stderr if status else sys.stdout)
        raise SystemExit(status)


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        prog="browser",
        description="Operate Chrome tabs through task-oriented, explicit-ID commands.",
    )
    parser.add_argument("--debug", action="store_true", help="Write diagnostic tracebacks to stderr.")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("health-check", help="Check Chrome/CDP connectivity without creating a tab.")
    commands.add_parser("list-tabs", help="List every addressable tab in the configured context.")

    attach = commands.add_parser("attach-tab", help="Find exactly one existing tab.")
    attach.add_argument("--url-contains")
    attach.add_argument("--title-contains")

    open_tab = commands.add_parser("open-tab", help="Open a tab and optionally navigate it.")
    open_tab.add_argument("--url")
    _add_navigation_options(open_tab)

    close = commands.add_parser("close-tab", help="Close exactly one tab.")
    _add_tab_id(close)

    navigate = commands.add_parser("navigate", help="Navigate one tab to an HTTP(S) URL.")
    _add_tab_id(navigate)
    navigate.add_argument("--url", required=True)
    _add_navigation_options(navigate)

    read = commands.add_parser("read-page", help="Read page content inline or into a workspace artifact.")
    _add_tab_id(read)
    read.add_argument("--cleaning-mode", choices=("raw", "text", "thorough"), default="thorough")
    _add_optional_output(read)

    shot = commands.add_parser("screenshot", help="Save a screenshot inside the agent workspace.")
    _add_tab_id(shot)
    shot.add_argument("--output-file", required=True)
    shot.add_argument("--format", dest="image_format", choices=("png", "jpeg"), default="png")
    page_mode = shot.add_mutually_exclusive_group()
    page_mode.add_argument("--full-page", dest="full_page", action="store_true", default=True)
    page_mode.add_argument("--viewport-only", dest="full_page", action="store_false")
    shot.add_argument("--overwrite", action="store_true")

    snapshot = commands.add_parser("dom-snapshot", help="Capture actionable DOM elements and CSS selectors.")
    _add_tab_id(snapshot)
    snapshot.add_argument("--include-non-interactive", action="store_true")
    boxes = snapshot.add_mutually_exclusive_group()
    boxes.add_argument("--include-bounding-boxes", dest="include_bounding_boxes", action="store_true", default=True)
    boxes.add_argument("--no-bounding-boxes", dest="include_bounding_boxes", action="store_false")
    snapshot.add_argument("--max-elements", type=int, default=200)
    _add_optional_output(snapshot)

    script = commands.add_parser("run-script", help="Advanced: evaluate JavaScript in one explicit tab.")
    _add_tab_id(script)
    script_source = script.add_mutually_exclusive_group(required=True)
    script_source.add_argument("--script")
    script_source.add_argument("--script-file")
    script_source.add_argument("--script-stdin", action="store_true")
    arg_source = script.add_mutually_exclusive_group()
    arg_source.add_argument("--arg-json")
    arg_source.add_argument("--arg-file")
    _add_optional_output(script)
    return parser


def _add_tab_id(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tab-id", required=True, help="Opaque tab ID returned by list/open/attach.")


def _add_navigation_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--wait-until", choices=("domcontentloaded", "load", "networkidle"), default="domcontentloaded")
    parser.add_argument("--timeout-ms", type=int, default=60_000)


def _add_optional_output(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output-file", help="Workspace-relative artifact path.")
    parser.add_argument("--overwrite", action="store_true")


async def execute(args: argparse.Namespace) -> Any:
    app = BrowserApplication()
    command = args.command
    if command == "health-check":
        return await app.health_check()
    if command == "list-tabs":
        return await app.list_tabs()
    if command == "attach-tab":
        return await app.attach_tab(url_contains=args.url_contains, title_contains=args.title_contains)
    if command == "open-tab":
        return await app.open_tab(url=args.url, wait_until=args.wait_until, timeout_ms=args.timeout_ms)
    if command == "close-tab":
        return await app.close_tab(tab_id=args.tab_id)
    if command == "navigate":
        return await app.navigate(
            tab_id=args.tab_id,
            url=args.url,
            wait_until=args.wait_until,
            timeout_ms=args.timeout_ms,
        )
    if command == "read-page":
        return await app.read_page(
            tab_id=args.tab_id,
            cleaning_mode=args.cleaning_mode,
            output_file=args.output_file,
            overwrite=args.overwrite,
        )
    if command == "screenshot":
        return await app.screenshot(
            tab_id=args.tab_id,
            output_file=args.output_file,
            full_page=args.full_page,
            image_format=args.image_format,
            overwrite=args.overwrite,
        )
    if command == "dom-snapshot":
        return await app.dom_snapshot(
            tab_id=args.tab_id,
            include_non_interactive=args.include_non_interactive,
            include_bounding_boxes=args.include_bounding_boxes,
            max_elements=args.max_elements,
            output_file=args.output_file,
            overwrite=args.overwrite,
        )
    if command == "run-script":
        script, arg = _decode_script_inputs(app, args)
        return await app.run_script(
            tab_id=args.tab_id,
            script=script,
            arg=arg,
            output_file=args.output_file,
            overwrite=args.overwrite,
        )
    raise invalid_argument("Unknown command.", command=command)


def _decode_script_inputs(app: BrowserApplication, args: argparse.Namespace) -> tuple[str, Any | None]:
    if args.script is not None:
        script = args.script
    elif args.script_file is not None:
        script = app.read_input_text(args.script_file)
    else:
        script = sys.stdin.read()

    raw_arg: str | None = None
    if args.arg_json is not None:
        raw_arg = args.arg_json
    elif args.arg_file is not None:
        raw_arg = app.read_input_text(args.arg_file)
    if raw_arg is None:
        return script, None
    try:
        return script, loads_strict(raw_arg)
    except StrictJsonError as exc:
        raise invalid_argument("The script argument must be valid strict finite JSON.") from exc


def _mark_ready() -> bool:
    ready_file = os.environ.get(READY_ENV)
    if not ready_file:
        return True
    try:
        Path(ready_file).write_text(f"{READY_TOKEN}\n", encoding="utf-8")
        return True
    except OSError:
        return False


def _write_json(value: dict[str, Any]) -> None:
    encoded = dumps_strict(value)
    sys.stdout.write(encoded + "\n")
    sys.stdout.flush()


def _write_json_or_internal(value: dict[str, Any]) -> bool:
    """Emit one strict envelope, falling back before any stdout is written."""

    try:
        _write_json(value)
        return True
    except StrictJsonError:
        _write_json(
            {
                "schema_version": SCHEMA_VERSION,
                "ok": False,
                "command": "cli",
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "A result could not be encoded as strict finite JSON.",
                    "retryable": True,
                },
            }
        )
        return False


def _command_hint(argv: Sequence[str]) -> str:
    for value in argv:
        if not value.startswith("-"):
            return value
    return "cli"


def main(argv: Sequence[str] | None = None) -> int:
    if not _mark_ready():
        return 3

    actual_argv = list(argv if argv is not None else sys.argv[1:])
    command = _command_hint(actual_argv)
    try:
        args = build_parser().parse_args(actual_argv)
        command = args.command
        if args.debug:
            logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)
        result = asyncio.run(execute(args))
    except SystemExit as exc:
        return int(exc.code or 0)
    except CliUsageError as exc:
        error = invalid_argument(str(exc))
        emitted = _write_json_or_internal(
            {"schema_version": SCHEMA_VERSION, "ok": False, "command": command, "error": error.to_payload()}
        )
        return error.exit_status if emitted else 5
    except BrowserError as exc:
        emitted = _write_json_or_internal(
            {"schema_version": SCHEMA_VERSION, "ok": False, "command": command, "error": exc.to_payload()}
        )
        return exc.exit_status if emitted else 5
    except Exception as exc:
        if "--debug" in actual_argv or os.environ.get("BROWSER_AUTOMATION_DEBUG") == "1":
            logging.exception("Unhandled browser CLI failure")
        else:
            print(f"browser: internal failure: {exc}", file=sys.stderr)
        error = BrowserError("INTERNAL_ERROR", "An unexpected browser CLI failure occurred.", retryable=True, exit_status=5)
        _write_json_or_internal(
            {"schema_version": SCHEMA_VERSION, "ok": False, "command": command, "error": error.to_payload()}
        )
        return error.exit_status

    emitted = _write_json_or_internal(
        {"schema_version": SCHEMA_VERSION, "ok": True, "command": command, "result": result}
    )
    return 0 if emitted else 5


if __name__ == "__main__":
    raise SystemExit(main())
