from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from .conftest import LocalSite
from .support import CLI_LAUNCHER, PROJECT_ROOT, LiveChrome, run_cli


pytestmark = pytest.mark.integration


def copy_minimal_bundle(destination: Path) -> Path:
    destination.mkdir()
    for name in ("SKILL.md", "pyproject.toml", "uv.lock"):
        shutil.copy2(PROJECT_ROOT / name, destination / name)
    shutil.copytree(PROJECT_ROOT / "src", destination / "src")
    scripts = destination / "scripts"
    scripts.mkdir()
    shutil.copy2(CLI_LAUNCHER, scripts / "browser")
    return destination


def write_fake_uv(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
case "${FAKE_UV_MODE:-ready-success}" in
  ready-success)
    printf '%s\n' 'browser-cli-ready-v1' >"$BROWSER_AUTOMATION_CLI_READY_FILE"
    printf '%s\n' '{"schema_version":"1","ok":true,"command":"health-check","result":{"connected":true}}'
    ;;
  ready-error)
    printf '%s\n' 'browser-cli-ready-v1' >"$BROWSER_AUTOMATION_CLI_READY_FILE"
    printf '%s\n' '{"schema_version":"1","ok":false,"command":"navigate","error":{"code":"INVALID_URL","message":"bad","retryable":false}}'
    exit 2
    ;;
  pre-ready)
    printf '%s\n' 'dependency stdout before CLI'
    printf '%s\n' 'dependency stderr before CLI' >&2
    exit 42
    ;;
esac
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def run_raw(launcher: Path, workspace: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["bash", str(launcher), *args],
        cwd=workspace,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=60,
    )


def one_payload(completed: subprocess.CompletedProcess[bytes]) -> dict:
    lines = completed.stdout.splitlines()
    assert len(lines) == 1, (completed.returncode, completed.stdout, completed.stderr)
    return json.loads(lines[0].decode("utf-8", errors="strict"))


def test_launcher_readiness_branches_and_missing_bundle_are_exactly_once(tmp_path: Path) -> None:
    bundle = copy_minimal_bundle(tmp_path / "bundle")
    launcher = bundle / "scripts/browser"
    fake_uv = tmp_path / "fake-uv"
    write_fake_uv(fake_uv)
    workspace = tmp_path / "caller"
    workspace.mkdir()
    launcher_tmp = tmp_path / "launcher-tmp"
    launcher_tmp.mkdir()
    environment = os.environ.copy()
    environment["UV_BIN"] = str(fake_uv)
    environment["TMPDIR"] = str(launcher_tmp)

    environment["FAKE_UV_MODE"] = "ready-success"
    success = run_raw(launcher, workspace, environment, "health-check")
    assert success.returncode == 0
    assert one_payload(success)["ok"] is True
    assert success.stderr == b""
    assert list(launcher_tmp.iterdir()) == []

    environment["FAKE_UV_MODE"] = "ready-error"
    cli_error = run_raw(launcher, workspace, environment, "navigate")
    assert cli_error.returncode == 2
    payload = one_payload(cli_error)
    assert payload["error"]["code"] == "INVALID_URL"
    assert b"BOOTSTRAP_FAILED" not in cli_error.stdout
    assert list(launcher_tmp.iterdir()) == []

    environment["FAKE_UV_MODE"] = "pre-ready"
    bootstrap = run_raw(launcher, workspace, environment, "health-check")
    assert bootstrap.returncode == 3
    payload = one_payload(bootstrap)
    assert payload["command"] == "bootstrap"
    assert payload["error"]["code"] == "BOOTSTRAP_FAILED"
    assert b"dependency stdout before CLI" in bootstrap.stderr
    assert b"dependency stderr before CLI" in bootstrap.stderr
    assert list(launcher_tmp.iterdir()) == []

    (bundle / "uv.lock").unlink()
    missing = run_raw(launcher, workspace, environment, "health-check")
    assert missing.returncode == 3
    assert one_payload(missing)["error"]["code"] == "BOOTSTRAP_FAILED"
    assert b"required bundled runtime files are missing" in missing.stderr
    assert list(launcher_tmp.iterdir()) == []


@pytest.mark.real_chrome
def test_relocated_clean_bundle_first_health_and_help_from_unrelated_cwd(
    live_chrome: LiveChrome,
    tmp_path: Path,
) -> None:
    bundle = copy_minimal_bundle(tmp_path / "relocated-browser-skill")
    launcher = bundle / "scripts/browser"
    caller = tmp_path / "unrelated" / "caller"
    caller.mkdir(parents=True)
    environment = live_chrome.environment(caller)
    assert not (bundle / ".venv").exists()

    health = run_cli(caller, environment, "health-check", launcher=launcher, timeout=180)
    assert health.returncode == 0, health.stderr.decode(errors="replace")
    assert health.payload["result"]["connected"] is True
    assert (bundle / ".venv").is_dir()

    help_result = subprocess.run(
        ["bash", str(launcher), "--help"],
        cwd=caller,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=120,
    )
    assert help_result.returncode == 0
    assert b"health-check" in help_result.stdout
    assert b"open-tab" in help_result.stdout


def test_connectivity_failure_is_one_cli_owned_error(test_site: LocalSite, tmp_path: Path) -> None:
    non_cdp_port = test_site.server.server_port
    environment = os.environ.copy()
    environment.update(
        {
            "CHROME_REMOTE_DEBUGGING_PORT": str(non_cdp_port),
            "CHROME_USER_DATA_DIR": str(tmp_path / "missing-browser-profile"),
            "BROWSER_AUTOMATION_WORKSPACE": str(tmp_path),
        }
    )
    result = run_cli(tmp_path, environment, "health-check", timeout=60)
    assert result.returncode == 3
    assert result.payload["command"] == "health-check"
    assert result.payload["error"]["code"] == "BROWSER_UNAVAILABLE"
    assert result.payload["error"]["retryable"] is True
