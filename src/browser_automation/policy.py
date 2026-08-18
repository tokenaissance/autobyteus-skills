"""Validation and workspace-safe file policy for browser effects."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from browser_automation.errors import BrowserError, configuration_error, invalid_argument
from browser_automation.json_codec import StrictJsonError, dumps_strict

MIN_TIMEOUT_MS = 1
MAX_TIMEOUT_MS = 300_000
MAX_TAB_ID_LENGTH = 512
MAX_MATCHER_LENGTH = 2_048
MAX_SCRIPT_LENGTH = 1_000_000


def validate_url(url: str) -> str:
    value = url.strip()
    try:
        parsed = urlparse(value)
    except ValueError as exc:
        raise BrowserError("INVALID_URL", "The URL is invalid.", retryable=False, exit_status=2) from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise BrowserError(
            "INVALID_URL",
            "Only absolute http:// and https:// URLs are supported.",
            retryable=False,
            exit_status=2,
            details={"url": value},
        )
    return value


def validate_timeout(timeout_ms: int) -> int:
    if isinstance(timeout_ms, bool) or not MIN_TIMEOUT_MS <= timeout_ms <= MAX_TIMEOUT_MS:
        raise invalid_argument(
            f"timeout_ms must be in range {MIN_TIMEOUT_MS}..{MAX_TIMEOUT_MS}.",
            timeout_ms=timeout_ms,
        )
    return timeout_ms


def validate_choice(value: str, *, name: str, allowed: Iterable[str]) -> str:
    normalized = value.strip().lower()
    choices = tuple(allowed)
    if normalized not in choices:
        raise invalid_argument(f"{name} must be one of: {', '.join(choices)}.", **{name: value})
    return normalized


def validate_tab_id(tab_id: str) -> str:
    value = tab_id.strip()
    if not value or len(value) > MAX_TAB_ID_LENGTH or any(char.isspace() for char in value):
        raise invalid_argument("tab_id must be a non-empty opaque identifier without whitespace.")
    return value


def validate_matcher(value: str | None, *, name: str) -> str:
    normalized = (value or "").strip()
    if len(normalized) > MAX_MATCHER_LENGTH:
        raise invalid_argument(f"{name} is too long.", **{name: normalized})
    return normalized


def validate_script(script: str) -> str:
    normalized = script.strip()
    if not normalized:
        raise invalid_argument("script must not be empty.")
    if len(normalized) > MAX_SCRIPT_LENGTH:
        raise invalid_argument(f"script must not exceed {MAX_SCRIPT_LENGTH} characters.")
    return normalized


class ArtifactPolicy:
    """Confine all agent-selected file access to one explicit workspace."""

    def __init__(self, workspace_root: Path) -> None:
        root = workspace_root.expanduser().resolve()
        if not root.is_dir():
            raise configuration_error("The agent workspace must be an existing directory.", workspace=str(root))
        self.workspace_root = root

    @classmethod
    def from_environment(cls) -> "ArtifactPolicy":
        configured = os.environ.get("BROWSER_AUTOMATION_WORKSPACE")
        if configured is not None:
            if not configured.strip():
                raise configuration_error("BROWSER_AUTOMATION_WORKSPACE must be non-empty when set.")
            path = Path(configured).expanduser()
            if not path.is_absolute():
                raise configuration_error("BROWSER_AUTOMATION_WORKSPACE must be an absolute path.")
            return cls(path)
        return cls(Path.cwd())

    def resolve_input(self, candidate: str) -> Path:
        path = self._resolve_relative(candidate)
        if not path.is_file():
            raise invalid_argument("The requested input file does not exist.", path=candidate)
        return path

    def resolve_output(self, candidate: str, *, overwrite: bool) -> Path:
        path = self._resolve_relative(candidate)
        if path.exists() and not path.is_file():
            raise BrowserError(
                "ARTIFACT_PATH_REJECTED",
                "The output path is not a regular file.",
                retryable=False,
                exit_status=2,
                details={"path": candidate},
            )
        if path.exists() and not overwrite:
            raise BrowserError(
                "ARTIFACT_EXISTS",
                "The output file already exists; use overwrite explicitly to replace it.",
                retryable=False,
                exit_status=2,
                details={"path": candidate},
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def read_text(self, candidate: str) -> str:
        try:
            return self.resolve_input(candidate).read_text(encoding="utf-8")
        except BrowserError:
            raise
        except (OSError, UnicodeError) as exc:
            raise invalid_argument("The input file could not be read as UTF-8 text.", path=candidate) from exc

    def write_text(self, candidate: str, content: str, *, overwrite: bool, media_type: str) -> dict[str, Any]:
        return self.write_bytes(candidate, content.encode("utf-8"), overwrite=overwrite, media_type=media_type)

    def write_json(self, candidate: str, value: Any, *, overwrite: bool) -> dict[str, Any]:
        try:
            content = dumps_strict(value) + "\n"
        except StrictJsonError as exc:
            raise BrowserError(
                "BROWSER_OPERATION_FAILED",
                "The artifact value is not strict finite JSON.",
                retryable=True,
                exit_status=5,
            ) from exc
        return self.write_text(candidate, content, overwrite=overwrite, media_type="application/json")

    def write_bytes(self, candidate: str, content: bytes, *, overwrite: bool, media_type: str) -> dict[str, Any]:
        output = self.resolve_output(candidate, overwrite=overwrite)
        temporary = self.temporary_sibling(output)
        try:
            temporary.write_bytes(content)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise BrowserError(
                "BROWSER_OPERATION_FAILED",
                "The artifact could not be written.",
                retryable=True,
                exit_status=5,
                details={"path": str(output)},
            ) from exc
        self.commit_temporary(temporary, output, overwrite=overwrite)
        return {"path": str(output), "media_type": media_type, "bytes_written": len(content)}

    def temporary_sibling(self, output: Path) -> Path:
        descriptor, name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
        os.close(descriptor)
        return Path(name)

    def commit_temporary(self, temporary: Path, output: Path, *, overwrite: bool) -> None:
        """Atomically publish a complete sibling, preserving no-overwrite semantics."""

        try:
            if overwrite:
                os.replace(temporary, output)
            else:
                # The sibling is on the same filesystem. A hard-link publish is
                # atomic and fails with EEXIST rather than replacing a winner.
                os.link(temporary, output)
                temporary.unlink()
        except FileExistsError as exc:
            raise BrowserError(
                "ARTIFACT_EXISTS",
                "The output file already exists; use overwrite explicitly to replace it.",
                retryable=False,
                exit_status=2,
                details={"path": str(output)},
            ) from exc
        except OSError as exc:
            raise BrowserError(
                "BROWSER_OPERATION_FAILED",
                "The artifact could not be committed.",
                retryable=True,
                exit_status=5,
                details={"path": str(output)},
            ) from exc
        finally:
            temporary.unlink(missing_ok=True)

    def artifact_metadata(self, output: Path, *, media_type: str) -> dict[str, Any]:
        return {
            "path": str(output),
            "media_type": media_type,
            "bytes_written": output.stat().st_size,
        }

    def _resolve_relative(self, candidate: str) -> Path:
        value = candidate.strip()
        raw = Path(value).expanduser()
        if not value or raw.is_absolute():
            raise BrowserError(
                "ARTIFACT_PATH_REJECTED",
                "Artifact and input paths must be relative to the agent workspace.",
                retryable=False,
                exit_status=2,
                details={"path": candidate},
            )
        resolved = (self.workspace_root / raw).resolve()
        if resolved != self.workspace_root and self.workspace_root not in resolved.parents:
            raise BrowserError(
                "ARTIFACT_PATH_REJECTED",
                "The path must remain inside the agent workspace.",
                retryable=False,
                exit_status=2,
                details={"path": candidate},
            )
        return resolved
