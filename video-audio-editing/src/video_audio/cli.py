"""Task-oriented video/audio CLI and versioned machine-output contract."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from pydantic import TypeAdapter, ValidationError

from video_audio.cli_parser import ParamMapping, add_operation_parser, cli_name
from video_audio.errors import MediaError
from video_audio.ffmpeg_runtime import require_binaries
from video_audio.json_codec import StrictJsonError, dumps_strict, loads_strict
from video_audio.operations.registry import MediaContext, OperationSpec, all_operations
from video_audio.paths import WorkspacePathPolicy

SCHEMA_VERSION = "1"
READY_ENV = "VIDEO_AUDIO_CLI_READY_FILE"
READY_TOKEN = "video-audio-cli-ready-v1"
WORKSPACE_ENV = "VIDEO_AUDIO_WORKSPACE"


class CliUsageError(Exception):
    pass


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliUsageError(message)

    def exit(self, status: int = 0, message: str | None = None) -> None:
        if message:
            self._print_message(message, sys.stderr if status else sys.stdout)
        raise SystemExit(status)


def build_parser() -> tuple[argparse.ArgumentParser, dict[str, tuple[OperationSpec, dict[str, ParamMapping]]]]:
    parser = JsonArgumentParser(prog="video-audio", description="Edit video and audio files with ffmpeg.")
    parser.add_argument("--debug", action="store_true", help="Write diagnostic tracebacks to stderr.")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=JsonArgumentParser)
    table = {}
    for spec in all_operations():
        table[cli_name(spec.name)] = (spec, add_operation_parser(commands, spec))
    return parser, table


def _decode_arguments(spec: OperationSpec, mappings: dict[str, ParamMapping], args: argparse.Namespace) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    for dest, mapping in mappings.items():
        value = getattr(args, dest)
        if value is None:
            continue
        if mapping.is_json:
            try:
                value = TypeAdapter(mapping.annotation).validate_python(loads_strict(value))
            except (StrictJsonError, ValidationError) as exc:
                raise MediaError.invalid_argument(
                    f"{mapping.option} must be strict JSON matching the documented shape: {exc}"
                ) from exc
        kwargs[mapping.name] = value
    return kwargs


def _workspace() -> str:
    configured = os.environ.get(WORKSPACE_ENV)
    workspace = configured if configured else os.getcwd()
    if not os.path.isabs(workspace) or not os.path.isdir(workspace):
        raise MediaError(
            "CONFIGURATION_ERROR",
            f"{WORKSPACE_ENV} must be an absolute path to an existing directory.",
            exit_status=3,
        )
    return workspace


def execute(spec: OperationSpec, mappings: dict[str, ParamMapping], args: argparse.Namespace) -> dict[str, Any]:
    kwargs = _decode_arguments(spec, mappings, args)
    policy = WorkspacePathPolicy(_workspace(), overwrite=bool(getattr(args, "overwrite", False)))
    result = spec.invoke(MediaContext(paths=policy), **kwargs)
    if spec.name == "health_check":
        require_binaries()  # CLI readiness policy: unhealthy without ffmpeg/ffprobe
    payload: dict[str, Any] = {"message": result.message, "outputs": result.outputs}
    if result.data is not None:
        payload["data"] = result.data
    return payload


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
    sys.stdout.write(dumps_strict(value) + "\n")
    sys.stdout.flush()


def _emit(value: dict[str, Any]) -> bool:
    try:
        _write_json(value)
        return True
    except StrictJsonError:
        _write_json({
            "schema_version": SCHEMA_VERSION, "ok": False, "command": "cli",
            "error": {"code": "INTERNAL_ERROR", "message": "A result could not be encoded as strict finite JSON.",
                      "retryable": True},
        })
        return False


def _failure(command: str, error: MediaError) -> int:
    emitted = _emit({"schema_version": SCHEMA_VERSION, "ok": False, "command": command, "error": error.to_payload()})
    return error.exit_status if emitted else 5


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
        parser, table = build_parser()
        args = parser.parse_args(actual_argv)
        command = args.command
        if args.debug:
            logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)
        spec, mappings = table[command]
        result = execute(spec, mappings, args)
    except SystemExit as exc:
        return int(exc.code or 0)
    except CliUsageError as exc:
        return _failure(command, MediaError.invalid_argument(str(exc)))
    except MediaError as exc:
        return _failure(command, exc)
    except Exception as exc:
        if "--debug" in actual_argv or os.environ.get("VIDEO_AUDIO_DEBUG") == "1":
            logging.exception("Unhandled video-audio CLI failure")
        else:
            print(f"video-audio: internal failure: {exc}", file=sys.stderr)
        return _failure(command, MediaError.internal("An unexpected video-audio CLI failure occurred."))
    emitted = _emit({"schema_version": SCHEMA_VERSION, "ok": True, "command": command, "result": result})
    return 0 if emitted else 5


if __name__ == "__main__":
    raise SystemExit(main())
