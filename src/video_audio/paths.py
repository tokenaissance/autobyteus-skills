"""Path policies: legacy MCP behaviour vs the stricter CLI workspace policy."""

from __future__ import annotations

import os
from typing import Protocol

from video_audio.errors import MediaError


class PathPolicy(Protocol):
    outputs: list[str]

    def input(self, path: str) -> str: ...

    def output(self, path: str) -> str: ...


class LegacyPathPolicy:
    """Exactly the former ``resolve_path``: relative paths join AUTOBYTEUS_AGENT_WORKSPACE."""

    def __init__(self) -> None:
        self.outputs: list[str] = []

    def _resolve(self, path: str) -> str:
        if not isinstance(path, str) or os.path.isabs(path):
            return path
        workspace = os.getenv("AUTOBYTEUS_AGENT_WORKSPACE")
        if workspace:
            return os.path.join(workspace, path)
        return path

    def input(self, path: str) -> str:
        return self._resolve(path)

    def output(self, path: str) -> str:
        resolved = self._resolve(path)
        self.outputs.append(resolved)
        return resolved


class WorkspacePathPolicy:
    """CLI policy: inputs relative to the workspace (absolute allowed, must exist);
    outputs confined to the workspace and never silently overwritten."""

    def __init__(self, workspace: str, overwrite: bool = False) -> None:
        self.workspace = os.path.realpath(workspace)
        self.overwrite = overwrite
        self.outputs: list[str] = []

    def input(self, path: str) -> str:
        if not isinstance(path, str) or not path:
            raise MediaError.invalid_argument("Error: A non-empty input path is required.")
        resolved = path if os.path.isabs(path) else os.path.join(self.workspace, path)
        if not os.path.exists(resolved):
            raise MediaError.input_not_found(f"Error: Input file not found at {resolved}", path=resolved)
        return resolved

    def output(self, path: str) -> str:
        if not isinstance(path, str) or not path:
            raise MediaError.invalid_argument("Error: A non-empty output path is required.")
        candidate = path if os.path.isabs(path) else os.path.join(self.workspace, path)
        resolved = os.path.realpath(candidate)
        if os.path.commonpath([self.workspace, resolved]) != self.workspace:
            raise MediaError.path_rejected(
                "Error: Output path must stay inside the workspace.", path=path, workspace=self.workspace
            )
        if os.path.isdir(resolved):
            raise MediaError.path_rejected("Error: Output path is a directory.", path=resolved)
        if os.path.exists(resolved) and not self.overwrite:
            raise MediaError.exists(
                f"Error: Output file already exists at {resolved}; pass --overwrite to replace it.", path=resolved
            )
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        self.outputs.append(resolved)
        return resolved
