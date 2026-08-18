from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CLI_LAUNCHER = PROJECT_ROOT / "scripts" / "browser"
MCP_LAUNCHER = PROJECT_ROOT / "scripts" / "browser-mcp"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def wait_for_tcp(host: str, port: int, *, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.2)
            if probe.connect_ex((host, port)) == 0:
                return
        time.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for {host}:{port}")


def terminate_process_group(process: subprocess.Popen[Any], *, timeout: float = 10.0) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=timeout)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    process.wait(timeout=timeout)


def chrome_executable() -> Path:
    configured = os.environ.get("BROWSER_AUTOMATION_TEST_CHROME_BIN")
    candidates = [
        configured,
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return Path(candidate)
    raise FileNotFoundError(
        "No supported Chrome/Chromium executable was found; set BROWSER_AUTOMATION_TEST_CHROME_BIN."
    )


def fetch_json(url: str, *, method: str = "GET", timeout: float = 5.0) -> Any:
    request = Request(url, method=method)
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


@dataclass(slots=True)
class CliResult:
    command: list[str]
    returncode: int
    stdout: bytes
    stderr: bytes
    payload: dict[str, Any]


@dataclass(slots=True)
class LiveChrome:
    port: int
    profile: Path
    process: subprocess.Popen[bytes]
    log_path: Path

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def environment(self, workspace: Path, **extra: str) -> dict[str, str]:
        environment = os.environ.copy()
        environment.update(
            {
                "CHROME_REMOTE_DEBUGGING_PORT": str(self.port),
                "CHROME_USER_DATA_DIR": str(self.profile),
                "BROWSER_AUTOMATION_WORKSPACE": str(workspace.resolve()),
            }
        )
        environment.update(extra)
        return environment

    def targets(self) -> list[dict[str, Any]]:
        result = fetch_json(f"{self.endpoint}/json/list")
        assert isinstance(result, list)
        return [target for target in result if target.get("type") == "page"]

    def page_count(self) -> int:
        return len(self.targets())

    def open_target(self, url: str, *, title_contains: str | None = None) -> dict[str, Any]:
        encoded = quote(url, safe="")
        target = fetch_json(f"{self.endpoint}/json/new?{encoded}", method="PUT")
        target_id = target["id"]
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            match = next((item for item in self.targets() if item.get("id") == target_id), None)
            if match is not None:
                title_ok = title_contains is None or title_contains in str(match.get("title", ""))
                url_ok = url in str(match.get("url", "")) or str(match.get("url", "")).startswith(url)
                if title_ok and url_ok:
                    return match
            time.sleep(0.05)
        raise TimeoutError(f"Chrome target {target_id} did not reach {url}")

    def close_target(self, target_id: str) -> None:
        with urlopen(f"{self.endpoint}/json/close/{quote(target_id, safe='')}", timeout=5.0) as response:
            assert response.status == 200
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if all(target.get("id") != target_id for target in self.targets()):
                return
            time.sleep(0.05)
        raise TimeoutError(f"Chrome target {target_id} did not close")


def start_chrome(root: Path) -> LiveChrome:
    executable = chrome_executable()
    profile = root / "chrome-profile"
    profile.mkdir(parents=True)
    log_path = root / "chrome.log"
    port = free_port()
    log_handle = log_path.open("wb")
    process = subprocess.Popen(
        [
            str(executable),
            "--headless=new",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-default-apps",
            "--disable-sync",
            "--disable-features=Translate",
            "--window-size=1280,900",
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            "about:blank",
        ],
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log_handle.close()
    chrome = LiveChrome(port=port, profile=profile, process=process, log_path=log_path)
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Chrome exited early with {process.returncode}: {log_path.read_text(errors='replace')}")
        try:
            fetch_json(f"{chrome.endpoint}/json/version", timeout=0.5)
            return chrome
        except (OSError, URLError, TimeoutError):
            time.sleep(0.1)
    terminate_process_group(process)
    raise TimeoutError(f"Chrome did not expose CDP on port {port}: {log_path.read_text(errors='replace')}")


def run_cli(
    workspace: Path,
    environment: dict[str, str],
    *arguments: str,
    launcher: Path = CLI_LAUNCHER,
    timeout: float = 120.0,
    stdin: bytes | None = None,
) -> CliResult:
    command = ["bash", str(launcher), *arguments]
    completed = subprocess.run(
        command,
        cwd=workspace,
        env=environment,
        input=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout,
    )
    lines = completed.stdout.splitlines()
    assert len(lines) == 1, (
        f"Expected exactly one stdout JSON value for {command!r}; "
        f"status={completed.returncode} stdout={completed.stdout!r} stderr={completed.stderr!r}"
    )
    payload = json.loads(lines[0].decode("utf-8", errors="strict"))
    assert payload.get("schema_version") == "1"
    return CliResult(
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        payload=payload,
    )
