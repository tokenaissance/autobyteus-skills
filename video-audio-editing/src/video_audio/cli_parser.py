"""Operation signature -> argparse mapping (the single place for CLI mapping rules)."""

from __future__ import annotations

import argparse
import inspect
import math
import types
from dataclasses import dataclass
from typing import Annotated, Any, Union, get_args, get_origin

from pydantic.fields import FieldInfo

from video_audio.operations.registry import OperationSpec


@dataclass
class ParamMapping:
    name: str
    option: str
    dest: str
    annotation: Any  # the bare type (Annotated stripped)
    is_json: bool


def cli_name(operation_name: str) -> str:
    return operation_name.replace("_", "-")


def _strip_annotated(annotation: Any) -> tuple[Any, str | None]:
    description = None
    if get_origin(annotation) is Annotated:
        base, *meta = get_args(annotation)
        for item in meta:
            if isinstance(item, FieldInfo) and item.description:
                description = item.description
        return base, description
    return annotation, description


def _union_members(annotation: Any) -> list[Any]:
    if get_origin(annotation) in (Union, types.UnionType):
        return [a for a in get_args(annotation) if a is not type(None)]
    return [annotation]


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise argparse.ArgumentTypeError("must be a finite number")
    return number


def _scalar_type(members: list[Any]) -> Any | None:
    """Return the argparse type for scalar members, or None when the value is structured."""
    if len(members) == 1 and members[0] is bool:
        return bool
    if any(get_origin(m) in (list, dict) or m in (list, dict) for m in members):
        return None
    if members == [int]:
        return int
    if members == [float]:
        return _finite_float
    # str, Union[str, float] (frame_location) and similar are transported as text
    return str


def map_parameters(spec: OperationSpec) -> list[ParamMapping]:
    mappings = []
    for name, param in spec.signature.parameters.items():
        base, _ = _strip_annotated(param.annotation)
        is_json = _scalar_type(_union_members(base)) is None
        option = "--" + name.replace("_", "-") + ("-json" if is_json else "")
        mappings.append(ParamMapping(name, option, name + ("_json" if is_json else ""), base, is_json))
    return mappings


def _esc(text: str) -> str:
    return text.replace("%", "%%")


def add_operation_parser(commands: Any, spec: OperationSpec) -> dict[str, ParamMapping]:
    first_line = (spec.description.strip().splitlines() or [""])[0]
    sub = commands.add_parser(cli_name(spec.name), help=_esc(first_line), description=_esc(spec.description))
    mappings = {}
    for mapping, (name, param) in zip(map_parameters(spec), spec.signature.parameters.items()):
        _, description = _strip_annotated(param.annotation)
        required = param.default is inspect.Parameter.empty
        members = _union_members(mapping.annotation)
        help_text = _esc(description or "")
        if mapping.is_json:
            sub.add_argument(mapping.option, dest=mapping.dest, required=required, metavar="JSON",
                             help=f"{help_text} (strict JSON)")
        elif members == [bool]:
            if param.default is True:
                sub.add_argument(mapping.option, dest=mapping.dest,
                                 action=argparse.BooleanOptionalAction, default=None, help=help_text)
            else:
                sub.add_argument(mapping.option, dest=mapping.dest, action="store_true", default=None, help=help_text)
        else:
            sub.add_argument(mapping.option, dest=mapping.dest, required=required,
                             type=_scalar_type(members), default=None, help=help_text)
        mappings[mapping.dest] = mapping
    if spec.writes_output:
        sub.add_argument("--overwrite", action="store_true", help="Replace an existing output file.")
    return mappings
