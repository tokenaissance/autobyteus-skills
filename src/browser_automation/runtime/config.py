"""Immutable configuration for the owned local Chrome runtime."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from browser_automation.errors import configuration_error


@dataclass(frozen=True, slots=True)
class BrowserRuntimeConfig:
    """Validated settings shared by Chrome establishment and Playwright sessions."""

    host: str
    port: int
    profile_directory: str
    user_data_dir: Path | None
    log_path: Path
    chrome_executable: Path | None
    establishment_timeout_seconds: float = 20.0
    poll_interval_seconds: float = 0.1
    probe_timeout_seconds: float = 1.0
    termination_timeout_seconds: float = 5.0

    @classmethod
    def from_environment(cls, env: Mapping[str, str] | None = None) -> "BrowserRuntimeConfig":
        actual = env if env is not None else os.environ
        raw_port = actual.get("CHROME_REMOTE_DEBUGGING_PORT", "9222")
        try:
            port = int(raw_port.strip())
        except (AttributeError, ValueError) as exc:
            raise configuration_error("CHROME_REMOTE_DEBUGGING_PORT must be an integer.") from exc
        if not 1 <= port <= 65_535:
            raise configuration_error("CHROME_REMOTE_DEBUGGING_PORT must be in range 1..65535.")

        profile_directory = _nonempty(
            actual.get("CHROME_PROFILE_DIRECTORY", "Profile 1"),
            "CHROME_PROFILE_DIRECTORY",
        )
        user_data_dir = _optional_path(actual, "CHROME_USER_DATA_DIR")
        log_path = _path(
            actual.get("CHROME_LOG_PATH", str(Path(tempfile.gettempdir()) / "browser-automation-chrome.log")),
            "CHROME_LOG_PATH",
        )
        chrome_executable = _optional_path(actual, "BROWSER_AUTOMATION_CHROME_BIN")
        if chrome_executable is not None:
            if not chrome_executable.is_file() or not os.access(chrome_executable, os.X_OK):
                raise configuration_error(
                    "BROWSER_AUTOMATION_CHROME_BIN must identify an executable file."
                )
            chrome_executable = chrome_executable.resolve()

        return cls(
            host="127.0.0.1",
            port=port,
            profile_directory=profile_directory,
            user_data_dir=user_data_dir,
            log_path=log_path,
            chrome_executable=chrome_executable,
        )

    @property
    def endpoint(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def version_endpoint(self) -> str:
        return f"{self.endpoint}/json/version"


def _nonempty(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise configuration_error(f"{name} must be non-empty when set.")
    if any(character in normalized for character in ("\r", "\n", "\x00")):
        raise configuration_error(f"{name} contains invalid control characters.")
    return normalized


def _path(value: str, name: str) -> Path:
    return Path(_nonempty(value, name)).expanduser()


def _optional_path(env: Mapping[str, str], name: str) -> Path | None:
    if name not in env:
        return None
    return _path(env[name], name)
