"""Validated retained-MCP runtime and exposure configuration."""

from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass
from typing import Literal, Mapping


class McpConfigError(ValueError):
    pass


DEFAULT_SERVER_NAME = "browser-automation"
DEFAULT_INSTRUCTIONS = (
    "Browser automation over the shared browser application. "
    "Use open_tab, attach_tab, or list_tabs to obtain an opaque tab_id."
)


@dataclass(slots=True)
class McpServerConfig:
    name: str = DEFAULT_SERVER_NAME
    instructions: str = DEFAULT_INSTRUCTIONS

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "McpServerConfig":
        actual = env if env is not None else os.environ
        return cls(
            name=_nonempty(actual.get("BROWSER_MCP_NAME", DEFAULT_SERVER_NAME), "BROWSER_MCP_NAME"),
            instructions=_nonempty(
                actual.get("BROWSER_MCP_INSTRUCTIONS", DEFAULT_INSTRUCTIONS),
                "BROWSER_MCP_INSTRUCTIONS",
            ),
        )


@dataclass(slots=True)
class McpRuntimeConfig:
    transport: Literal["stdio", "streamable-http"] = "stdio"
    host: str = "127.0.0.1"
    port: int = 8765

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "McpRuntimeConfig":
        actual = env if env is not None else os.environ
        transport = (actual.get("BROWSER_MCP_TRANSPORT", "stdio") or "").strip().lower()
        if transport not in {"stdio", "streamable-http"}:
            raise McpConfigError("BROWSER_MCP_TRANSPORT must be one of: stdio, streamable-http.")
        host = _host(actual.get("BROWSER_MCP_HOST", "127.0.0.1"))
        raw_port = actual.get("BROWSER_MCP_PORT", "8765")
        try:
            port = int(raw_port.strip())
        except (AttributeError, ValueError) as exc:
            raise McpConfigError("BROWSER_MCP_PORT must be an integer.") from exc
        if not 1 <= port <= 65_535:
            raise McpConfigError("BROWSER_MCP_PORT must be in range 1..65535.")
        return cls(transport=transport, host=host, port=port)  # type: ignore[arg-type]

    @property
    def is_loopback(self) -> bool:
        normalized = self.host.strip().lower().rstrip(".")
        if normalized == "localhost":
            return True
        try:
            return ipaddress.ip_address(normalized).is_loopback
        except ValueError:
            return False

    @property
    def requires_exposure_warning(self) -> bool:
        return self.transport == "streamable-http" and not self.is_loopback


def _nonempty(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise McpConfigError(f"{name} must be non-empty.")
    if any(character in normalized for character in ("\r", "\n", "\x00")):
        raise McpConfigError(f"{name} contains invalid control characters.")
    return normalized


def _host(value: str) -> str:
    normalized = _nonempty(value, "BROWSER_MCP_HOST")
    if any(character.isspace() for character in normalized):
        raise McpConfigError("BROWSER_MCP_HOST must not contain whitespace.")
    try:
        ipaddress.ip_address(normalized)
        return normalized
    except ValueError:
        pass
    hostname = normalized.rstrip(".")
    if len(hostname) > 253 or not hostname:
        raise McpConfigError("BROWSER_MCP_HOST is not a valid IP address or hostname.")
    labels = hostname.split(".")
    if any(
        len(label) > 63 or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", label)
        for label in labels
    ):
        raise McpConfigError("BROWSER_MCP_HOST is not a valid IP address or hostname.")
    return normalized
