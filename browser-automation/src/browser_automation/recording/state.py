"""Per-recording file layout under the private runtime directory, and atomic JSON files.

One recording exists per (CDP port, tab_id). The service writes the state file; the worker
writes the ready marker and the final status file; the worker's log sits beside them.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RECORDING_SCHEMA_VERSION = 1
_SAFE_TAB_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


@dataclass(frozen=True, slots=True)
class RecordingFiles:
    state: Path
    ready: Path
    status: Path
    log: Path

    @classmethod
    def for_tab(cls, runtime_dir: Path, port: int, tab_id: str) -> "RecordingFiles":
        key = tab_id if _SAFE_TAB_ID.match(tab_id) else hashlib.sha256(tab_id.encode()).hexdigest()[:32]
        directory = runtime_dir / "recordings"
        stem = f"{port}-{key}"
        return cls(
            state=directory / f"{stem}.json",
            ready=directory / f"{stem}.ready.json",
            status=directory / f"{stem}.status.json",
            log=directory / f"{stem}.log",
        )

    def ensure_directory(self) -> None:
        directory = self.state.parent
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.is_symlink() or not directory.is_dir():
            raise OSError(f"recording directory is not a directory: {directory}")
        directory.chmod(0o700)

    def clear(self, *, keep_log: bool = False) -> None:
        for path in (self.state, self.ready, self.status) + (() if keep_log else (self.log,)):
            path.unlink(missing_ok=True)


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle)
    os.replace(temporary, path)


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None
