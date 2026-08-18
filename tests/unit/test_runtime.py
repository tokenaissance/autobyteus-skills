from __future__ import annotations

import asyncio
import json
import os
import signal
import stat
import subprocess
import threading
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from browser_automation.errors import BrowserError
from browser_automation.runtime import (
    BrowserRuntime,
    BrowserRuntimeConfig,
    BrowserSession,
    ChromeAvailability,
    ChromeAvailabilityState,
    ChromeLauncher,
    EstablishmentGate,
)
from browser_automation.runtime import chrome_launcher as launcher_module


class FakeCdpSession:
    def __init__(self, target_id: str) -> None:
        self.target_id = target_id
        self.detached = False

    async def send(self, method: str) -> dict[str, dict[str, str]]:
        assert method == "Target.getTargetInfo"
        return {"targetInfo": {"targetId": self.target_id}}

    async def detach(self) -> None:
        self.detached = True


class FakePage:
    url = "https://example.com"

    def is_closed(self) -> bool:
        return False

    async def title(self) -> str:
        return "Example"


class FakeContext:
    def __init__(self) -> None:
        self.pages = [FakePage()]
        self.cdp_session: FakeCdpSession | None = None

    async def new_cdp_session(self, _page: FakePage) -> FakeCdpSession:
        self.cdp_session = FakeCdpSession("opaque-target-id")
        return self.cdp_session


class FakeBrowser:
    def __init__(self, contexts: list[FakeContext] | None = None) -> None:
        self.contexts = contexts if contexts is not None else [FakeContext()]

    async def close(self) -> None:
        raise AssertionError("Runtime must not close the remote browser")


class FakePlaywright:
    def __init__(self, connect: Callable[[str], Awaitable[FakeBrowser]]) -> None:
        self._connect = connect
        self.chromium = self
        self.stopped = False
        self.connect_calls: list[str] = []

    async def connect_over_cdp(self, endpoint: str) -> FakeBrowser:
        self.connect_calls.append(endpoint)
        return await self._connect(endpoint)

    async def stop(self) -> None:
        self.stopped = True


class FakePlaywrightStarter:
    def __init__(self, playwright: FakePlaywright) -> None:
        self.playwright = playwright
        self.started = False

    async def start(self) -> FakePlaywright:
        self.started = True
        return self.playwright


class FakeProcess:
    def __init__(self, pid: int = 41_001, return_code: int | None = None) -> None:
        self.pid = pid
        self.return_code = return_code
        self.wait_calls: list[float | None] = []

    def poll(self) -> int | None:
        return self.return_code

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls.append(timeout)
        return self.return_code or 0


def runtime_config(tmp_path: Path, *, port: int = 49_151) -> BrowserRuntimeConfig:
    return BrowserRuntimeConfig(
        host="127.0.0.1",
        port=port,
        profile_directory="Profile 1",
        user_data_dir=None,
        log_path=tmp_path / "chrome.log",
        chrome_executable=None,
        establishment_timeout_seconds=1.0,
        poll_interval_seconds=0.005,
        probe_timeout_seconds=0.1,
        termination_timeout_seconds=0.1,
    )


@pytest.mark.anyio
async def test_browser_session_uses_public_cdp_target_info_and_detaches() -> None:
    context = FakeContext()
    session = BrowserSession(browser=object(), context=context)
    summary = await session.summarize_page(context.pages[0])
    assert summary == {
        "tab_id": "opaque-target-id",
        "url": "https://example.com",
        "title": "Example",
    }
    assert context.cdp_session is not None and context.cdp_session.detached


def test_runtime_config_has_owned_defaults_and_ignores_removed_download_setting() -> None:
    config = BrowserRuntimeConfig.from_environment({"CHROME_DOWNLOAD_DIRECTORY": "/not/owned"})
    assert config.host == "127.0.0.1"
    assert config.port == 9222
    assert config.profile_directory == "Profile 1"
    assert config.user_data_dir is None
    assert config.chrome_executable is None
    assert config.log_path.name == "browser-automation-chrome.log"
    assert config.endpoint == "http://127.0.0.1:9222"
    assert config.version_endpoint == "http://127.0.0.1:9222/json/version"


def test_runtime_config_validates_explicit_launch_settings(tmp_path: Path) -> None:
    executable = tmp_path / "chrome"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o700)
    config = BrowserRuntimeConfig.from_environment(
        {
            "CHROME_REMOTE_DEBUGGING_PORT": "9333",
            "CHROME_USER_DATA_DIR": "~/chrome-profile",
            "CHROME_PROFILE_DIRECTORY": "Work",
            "CHROME_LOG_PATH": str(tmp_path / "logs" / "chrome.log"),
            "BROWSER_AUTOMATION_CHROME_BIN": str(executable),
        }
    )
    assert config.port == 9333
    assert config.user_data_dir == Path("~/chrome-profile").expanduser()
    assert config.profile_directory == "Work"
    assert config.log_path == tmp_path / "logs" / "chrome.log"
    assert config.chrome_executable == executable.resolve()


@pytest.mark.parametrize(
    "environment",
    [
        {"CHROME_REMOTE_DEBUGGING_PORT": "not-a-port"},
        {"CHROME_REMOTE_DEBUGGING_PORT": "0"},
        {"CHROME_REMOTE_DEBUGGING_PORT": "65536"},
        {"CHROME_PROFILE_DIRECTORY": "  "},
        {"CHROME_PROFILE_DIRECTORY": "bad\nprofile"},
        {"BROWSER_AUTOMATION_CHROME_BIN": "/definitely/not/an/executable"},
    ],
)
def test_runtime_config_rejects_invalid_values(environment: dict[str, str]) -> None:
    with pytest.raises(BrowserError) as raised:
        BrowserRuntimeConfig.from_environment(environment)
    assert raised.value.code == "CONFIGURATION_ERROR"


def test_executable_resolution_uses_deterministic_path_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "chromium"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o700)
    config = runtime_config(tmp_path)
    monkeypatch.setattr(launcher_module, "MACOS_CHROME_CANDIDATES", ())
    monkeypatch.setattr(launcher_module, "LINUX_CHROME_CANDIDATES", ())
    monkeypatch.setattr(
        launcher_module.shutil,
        "which",
        lambda command: str(executable) if command == "chromium" else None,
    )
    assert launcher_module.resolve_chrome_executable(config) == executable.resolve()


def test_executable_resolution_fails_without_supported_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = runtime_config(tmp_path)
    monkeypatch.setattr(launcher_module, "MACOS_CHROME_CANDIDATES", ())
    monkeypatch.setattr(launcher_module, "LINUX_CHROME_CANDIDATES", ())
    monkeypatch.setattr(launcher_module.shutil, "which", lambda _command: None)
    with pytest.raises(BrowserError) as raised:
        launcher_module.resolve_chrome_executable(config)
    assert raised.value.code == "BROWSER_UNAVAILABLE"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("websocket_url", "expected"),
    [
        ("ws://127.0.0.1/devtools/browser/test", True),
        ("wss://127.0.0.1/devtools/browser/test", True),
        ("ws-not-a-url", False),
        (None, False),
    ],
)
async def test_cdp_probe_requires_a_real_websocket_debugger_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    websocket_url: str | None,
    expected: bool,
) -> None:
    class Response:
        status = 200

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def read(self, _limit: int) -> bytes:
            return json.dumps({"webSocketDebuggerUrl": websocket_url}).encode("utf-8")

    monkeypatch.setattr(launcher_module, "urlopen", lambda *_args, **_kwargs: Response())
    assert await launcher_module.probe_cdp_endpoint(runtime_config(tmp_path)) is expected


@pytest.mark.anyio
async def test_establishment_gate_is_private_noninheritable_and_cancel_safe(tmp_path: Path) -> None:
    root = tmp_path / "gates"
    loop = asyncio.get_running_loop()
    first = await EstablishmentGate.acquire(
        port=49_152,
        deadline=loop.time() + 1,
        poll_interval=0.005,
        directory=root,
    )
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE(first.path.stat().st_mode) == 0o600
    assert not os.get_inheritable(first.descriptor)

    waiter = asyncio.create_task(
        EstablishmentGate.acquire(
            port=49_152,
            deadline=loop.time() + 1,
            poll_interval=0.005,
            directory=root,
        )
    )
    await asyncio.sleep(0.02)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    first.release()
    replacement = await EstablishmentGate.acquire(
        port=49_152,
        deadline=loop.time() + 1,
        poll_interval=0.005,
        directory=root,
    )
    replacement.release()


@pytest.mark.anyio
async def test_establishment_gate_rejects_a_symlink_lock_file(tmp_path: Path) -> None:
    root = tmp_path / "gates"
    root.mkdir(mode=0o700)
    target = tmp_path / "target"
    target.write_text("not a gate", encoding="utf-8")
    (root / "chrome-49159.lock").symlink_to(target)
    with pytest.raises(BrowserError) as raised:
        await EstablishmentGate.acquire(
            port=49_159,
            deadline=asyncio.get_running_loop().time() + 1,
            poll_interval=0.005,
            directory=root,
        )
    assert raised.value.code == "BROWSER_UNAVAILABLE"


@pytest.mark.anyio
async def test_launcher_acquires_gate_before_authoritative_ready_probe(tmp_path: Path) -> None:
    config = runtime_config(tmp_path, port=49_153)
    root = tmp_path / "gates"
    loop = asyncio.get_running_loop()
    held = await EstablishmentGate.acquire(
        port=config.port,
        deadline=loop.time() + 1,
        poll_interval=0.005,
        directory=root,
    )
    probe_called = asyncio.Event()

    async def ready_probe(_config: BrowserRuntimeConfig) -> bool:
        probe_called.set()
        return True

    launcher = ChromeLauncher(config, probe=ready_probe, gate_directory=root)
    result_task = asyncio.create_task(launcher.ensure_available())
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(asyncio.shield(probe_called.wait()), timeout=0.03)
    held.release()
    availability = await result_task
    assert probe_called.is_set()
    assert availability.state is ChromeAvailabilityState.DURABLE_EXISTING
    assert not availability.has_abort_authority


@pytest.mark.anyio
async def test_launcher_gate_timeout_does_not_probe_or_acquire_abort_authority(tmp_path: Path) -> None:
    config = replace(
        runtime_config(tmp_path, port=49_161),
        establishment_timeout_seconds=0.03,
    )
    root = tmp_path / "gates"
    loop = asyncio.get_running_loop()
    held = await EstablishmentGate.acquire(
        port=config.port,
        deadline=loop.time() + 1,
        poll_interval=0.005,
        directory=root,
    )
    probe_calls = 0

    async def forbidden_probe(_config: BrowserRuntimeConfig) -> bool:
        nonlocal probe_calls
        probe_calls += 1
        return True

    try:
        with pytest.raises(BrowserError) as raised:
            await ChromeLauncher(config, probe=forbidden_probe, gate_directory=root).ensure_available()
    finally:
        held.release()
    assert raised.value.code == "BROWSER_UNAVAILABLE"
    assert probe_calls == 0


@pytest.mark.anyio
async def test_probe_cancellation_keeps_gate_until_authoritative_probe_finishes(tmp_path: Path) -> None:
    config = runtime_config(tmp_path, port=49_162)
    root = tmp_path / "gates"
    first_probe_started = asyncio.Event()
    finish_first_probe = asyncio.Event()
    second_probe_started = asyncio.Event()

    async def first_probe(_config: BrowserRuntimeConfig) -> bool:
        first_probe_started.set()
        await finish_first_probe.wait()
        return True

    async def second_probe(_config: BrowserRuntimeConfig) -> bool:
        second_probe_started.set()
        return True

    first_task = asyncio.create_task(
        ChromeLauncher(config, probe=first_probe, gate_directory=root).ensure_available()
    )
    await first_probe_started.wait()
    first_task.cancel()
    second_task = asyncio.create_task(
        ChromeLauncher(config, probe=second_probe, gate_directory=root).ensure_available()
    )
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(asyncio.shield(second_probe_started.wait()), timeout=0.03)

    finish_first_probe.set()
    with pytest.raises(asyncio.CancelledError):
        await first_task
    second = await second_task
    assert second.state is ChromeAvailabilityState.DURABLE_EXISTING


@pytest.mark.anyio
async def test_launcher_spawns_one_noninheriting_group_and_retains_gate_until_promote(
    tmp_path: Path,
) -> None:
    config = runtime_config(tmp_path, port=49_154)
    config = replace(config, user_data_dir=tmp_path / "profile")
    process = FakeProcess()
    spawn: dict[str, Any] = {}
    probe_calls = 0

    async def probe(_config: BrowserRuntimeConfig) -> bool:
        nonlocal probe_calls
        probe_calls += 1
        return probe_calls > 1

    def process_factory(arguments: list[str], **kwargs: Any) -> FakeProcess:
        spawn["arguments"] = arguments
        spawn["kwargs"] = kwargs
        return process

    availability = await ChromeLauncher(
        config,
        probe=probe,
        process_factory=process_factory,
        executable_resolver=lambda _config: Path("/fake/chrome"),
        termination_runner=lambda *_args: None,
        gate_directory=tmp_path / "gates",
    ).ensure_available()
    assert availability.state is ChromeAvailabilityState.PENDING_OWNED
    assert availability.has_abort_authority
    assert spawn["arguments"] == [
        "/fake/chrome",
        "--no-first-run",
        "--flag-switches-begin",
        "--flag-switches-end",
        "--remote-debugging-port=49154",
        "--profile-directory=Profile 1",
        f"--user-data-dir={tmp_path / 'profile'}",
    ]
    assert spawn["kwargs"]["start_new_session"] is True
    assert spawn["kwargs"]["close_fds"] is True
    assert spawn["kwargs"]["stderr"] is subprocess.STDOUT

    availability.promote()
    assert availability.state is ChromeAvailabilityState.PROMOTED
    assert not availability.has_abort_authority
    loop = asyncio.get_running_loop()
    next_gate = await EstablishmentGate.acquire(
        port=config.port,
        deadline=loop.time() + 1,
        poll_interval=0.005,
        directory=tmp_path / "gates",
    )
    next_gate.release()


@pytest.mark.anyio
async def test_launcher_aborts_owned_group_before_unlock_on_early_exit(tmp_path: Path) -> None:
    config = runtime_config(tmp_path, port=49_155)
    process = FakeProcess(return_code=7)
    terminated: list[tuple[FakeProcess, int, float]] = []

    async def unavailable(_config: BrowserRuntimeConfig) -> bool:
        return False

    with pytest.raises(BrowserError) as raised:
        await ChromeLauncher(
            config,
            probe=unavailable,
            process_factory=lambda *_args, **_kwargs: process,
            executable_resolver=lambda _config: Path("/fake/chrome"),
            termination_runner=lambda owned, group, timeout: terminated.append(
                (owned, group, timeout)
            ),
            gate_directory=tmp_path / "gates",
        ).ensure_available()
    assert raised.value.code == "BROWSER_UNAVAILABLE"
    assert terminated == [(process, process.pid, config.termination_timeout_seconds)]

    loop = asyncio.get_running_loop()
    next_gate = await EstablishmentGate.acquire(
        port=config.port,
        deadline=loop.time() + 1,
        poll_interval=0.005,
        directory=tmp_path / "gates",
    )
    next_gate.release()


@pytest.mark.anyio
async def test_launcher_cancellation_aborts_owned_group_before_unlock(tmp_path: Path) -> None:
    config = runtime_config(tmp_path, port=49_156)
    process = FakeProcess()
    spawned = asyncio.Event()
    cleaned = threading.Event()

    async def unavailable(_config: BrowserRuntimeConfig) -> bool:
        return False

    def process_factory(*_args: Any, **_kwargs: Any) -> FakeProcess:
        spawned.set()
        return process

    launcher = ChromeLauncher(
        config,
        probe=unavailable,
        process_factory=process_factory,
        executable_resolver=lambda _config: Path("/fake/chrome"),
        termination_runner=lambda _owned, _group, _timeout: cleaned.set(),
        gate_directory=tmp_path / "gates",
    )
    task = asyncio.create_task(launcher.ensure_available())
    await spawned.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleaned.is_set()

    loop = asyncio.get_running_loop()
    next_gate = await EstablishmentGate.acquire(
        port=config.port,
        deadline=loop.time() + 1,
        poll_interval=0.005,
        directory=tmp_path / "gates",
    )
    next_gate.release()


def test_exact_process_group_cleanup_uses_only_owned_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = FakeProcess(pid=41_777)
    wait_count = 0

    def wait(timeout: float | None = None) -> int:
        nonlocal wait_count
        process.wait_calls.append(timeout)
        wait_count += 1
        if wait_count == 1:
            raise subprocess.TimeoutExpired("chrome", timeout)
        process.return_code = -signal.SIGKILL
        return process.return_code

    process.wait = wait  # type: ignore[method-assign]
    signals: list[tuple[int, int]] = []

    def killpg(group: int, sent_signal: int) -> None:
        signals.append((group, sent_signal))
        if sent_signal == 0:
            raise ProcessLookupError

    monkeypatch.setattr(launcher_module.os, "killpg", killpg)
    launcher_module._terminate_process_group(process, process.pid, 0.1)
    assert signals == [
        (process.pid, signal.SIGTERM),
        (process.pid, signal.SIGKILL),
        (process.pid, 0),
    ]
    assert process.wait_calls == [0.1, 0.1]


@pytest.mark.anyio
async def test_runtime_disconnects_client_without_browser_close(tmp_path: Path) -> None:
    config = runtime_config(tmp_path)
    context = FakeContext()
    browser = FakeBrowser([context])

    async def connect(_endpoint: str) -> FakeBrowser:
        return browser

    playwright = FakePlaywright(connect)
    starter = FakePlaywrightStarter(playwright)

    class DurableLauncher:
        async def ensure_available(self) -> ChromeAvailability:
            return ChromeAvailability.durable_existing(config)

    runtime = BrowserRuntime(
        config_factory=lambda: config,
        launcher_factory=lambda _config: DurableLauncher(),
        playwright_factory=lambda: starter,
    )
    async with runtime.session() as session:
        assert session.context is context

    assert playwright.stopped
    assert playwright.connect_calls == [config.endpoint]


@pytest.mark.anyio
@pytest.mark.parametrize("missing_context", [False, True])
async def test_runtime_aborts_pending_launch_on_connection_or_context_failure(
    tmp_path: Path,
    missing_context: bool,
) -> None:
    config = runtime_config(tmp_path)
    process = FakeProcess()
    gate = await EstablishmentGate.acquire(
        port=config.port,
        deadline=asyncio.get_running_loop().time() + 1,
        poll_interval=0.005,
        directory=tmp_path / "gates",
    )
    terminated = threading.Event()
    availability = ChromeAvailability.pending_owned(
        config=config,
        gate=gate,
        process=process,
        termination_runner=lambda *_args: terminated.set(),
    )

    async def connect(_endpoint: str) -> FakeBrowser:
        if not missing_context:
            raise RuntimeError("connect failed")
        return FakeBrowser([])

    playwright = FakePlaywright(connect)
    starter = FakePlaywrightStarter(playwright)

    class PendingLauncher:
        async def ensure_available(self) -> ChromeAvailability:
            return availability

    runtime = BrowserRuntime(
        config_factory=lambda: config,
        launcher_factory=lambda _config: PendingLauncher(),
        playwright_factory=lambda: starter,
    )
    with pytest.raises(BrowserError) as raised:
        async with runtime.session():
            raise AssertionError("failed establishment must not yield")
    assert raised.value.code == "BROWSER_UNAVAILABLE"
    assert availability.state is ChromeAvailabilityState.ABORTED
    assert terminated.is_set()
    assert playwright.stopped


@pytest.mark.anyio
async def test_runtime_promotes_before_yield_and_never_aborts_promoted_chrome(tmp_path: Path) -> None:
    config = runtime_config(tmp_path)
    process = FakeProcess()
    gate = await EstablishmentGate.acquire(
        port=config.port,
        deadline=asyncio.get_running_loop().time() + 1,
        poll_interval=0.005,
        directory=tmp_path / "gates",
    )
    aborted = False

    def terminate(*_args: Any) -> None:
        nonlocal aborted
        aborted = True

    availability = ChromeAvailability.pending_owned(
        config=config,
        gate=gate,
        process=process,
        termination_runner=terminate,
    )

    async def connect(_endpoint: str) -> FakeBrowser:
        return FakeBrowser()

    playwright = FakePlaywright(connect)

    class PendingLauncher:
        async def ensure_available(self) -> ChromeAvailability:
            return availability

    runtime = BrowserRuntime(
        config_factory=lambda: config,
        launcher_factory=lambda _config: PendingLauncher(),
        playwright_factory=lambda: FakePlaywrightStarter(playwright),
    )
    async with runtime.session():
        assert availability.state is ChromeAvailabilityState.PROMOTED
        assert not availability.has_abort_authority
    assert not aborted
    assert playwright.stopped


@pytest.mark.anyio
async def test_runtime_cancellation_during_pending_connection_aborts_before_return(
    tmp_path: Path,
) -> None:
    config = runtime_config(tmp_path, port=49_160)
    gate = await EstablishmentGate.acquire(
        port=config.port,
        deadline=asyncio.get_running_loop().time() + 1,
        poll_interval=0.005,
        directory=tmp_path / "gates",
    )
    cleaned = threading.Event()
    availability = ChromeAvailability.pending_owned(
        config=config,
        gate=gate,
        process=FakeProcess(),
        termination_runner=lambda *_args: cleaned.set(),
    )
    connect_started = asyncio.Event()
    never_connect = asyncio.Event()

    async def connect(_endpoint: str) -> FakeBrowser:
        connect_started.set()
        await never_connect.wait()
        raise AssertionError("cancelled connection must not complete")

    playwright = FakePlaywright(connect)

    class PendingLauncher:
        async def ensure_available(self) -> ChromeAvailability:
            return availability

    runtime = BrowserRuntime(
        config_factory=lambda: config,
        launcher_factory=lambda _config: PendingLauncher(),
        playwright_factory=lambda: FakePlaywrightStarter(playwright),
    )

    async def connect_session() -> None:
        async with runtime.session():
            raise AssertionError("cancelled establishment must not yield")

    task = asyncio.create_task(connect_session())
    await connect_started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert availability.state is ChromeAvailabilityState.ABORTED
    assert cleaned.is_set()
    assert playwright.stopped


@pytest.mark.anyio
@pytest.mark.parametrize("owner_outcome", ["abort", "promote"])
async def test_second_caller_stays_before_probe_connect_until_pending_owner_is_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    owner_outcome: str,
) -> None:
    """PREM-004: no caller can attach while another caller retains abort authority."""

    port = 49_157 if owner_outcome == "abort" else 49_158
    config = runtime_config(tmp_path, port=port)
    gate_root = tmp_path / "gates"
    owner_probe_calls = 0
    waiter_probe_calls = 0
    owner_process = FakeProcess(pid=41_900 + port)
    cleanup_complete = threading.Event()
    pending_pause_reached = asyncio.Event()
    allow_owner_terminal = asyncio.Event()
    owner_yielded = asyncio.Event()
    finish_owner_session = asyncio.Event()
    second_gate_opened = asyncio.Event()
    waiter_connected = asyncio.Event()

    original_open_gate = launcher_module._open_gate_file
    open_count = 0

    def observed_open_gate(root: Path, selected_port: int) -> int:
        nonlocal open_count
        descriptor = original_open_gate(root, selected_port)
        open_count += 1
        if open_count == 2:
            second_gate_opened.set()
        return descriptor

    monkeypatch.setattr(launcher_module, "_open_gate_file", observed_open_gate)

    async def owner_probe(_config: BrowserRuntimeConfig) -> bool:
        nonlocal owner_probe_calls
        owner_probe_calls += 1
        return owner_probe_calls > 1

    async def waiter_probe(_config: BrowserRuntimeConfig) -> bool:
        nonlocal waiter_probe_calls
        waiter_probe_calls += 1
        if owner_outcome == "abort":
            assert cleanup_complete.is_set()
        return True

    owner_launcher = ChromeLauncher(
        config,
        probe=owner_probe,
        process_factory=lambda *_args, **_kwargs: owner_process,
        executable_resolver=lambda _config: Path("/fake/chrome"),
        termination_runner=lambda *_args: cleanup_complete.set(),
        gate_directory=gate_root,
    )
    waiter_launcher = ChromeLauncher(
        config,
        probe=waiter_probe,
        gate_directory=gate_root,
    )

    async def pause_pending(_availability: ChromeAvailability) -> None:
        pending_pause_reached.set()
        await allow_owner_terminal.wait()

    async def owner_connect(_endpoint: str) -> FakeBrowser:
        if owner_outcome == "abort":
            raise RuntimeError("deterministic owner connect failure")
        return FakeBrowser()

    async def waiter_connect(_endpoint: str) -> FakeBrowser:
        waiter_connected.set()
        return FakeBrowser()

    owner_playwright = FakePlaywright(owner_connect)
    waiter_playwright = FakePlaywright(waiter_connect)
    owner_runtime = BrowserRuntime(
        config_factory=lambda: config,
        launcher_factory=lambda _config: owner_launcher,
        playwright_factory=lambda: FakePlaywrightStarter(owner_playwright),
        pending_ready_hook=pause_pending,
    )
    waiter_runtime = BrowserRuntime(
        config_factory=lambda: config,
        launcher_factory=lambda _config: waiter_launcher,
        playwright_factory=lambda: FakePlaywrightStarter(waiter_playwright),
    )

    async def run_owner() -> None:
        async with owner_runtime.session():
            owner_yielded.set()
            await finish_owner_session.wait()

    async def run_waiter() -> None:
        async with waiter_runtime.session():
            return

    owner_task = asyncio.create_task(run_owner())
    await pending_pause_reached.wait()
    waiter_task = asyncio.create_task(run_waiter())
    await second_gate_opened.wait()
    await asyncio.sleep(0.02)

    assert waiter_probe_calls == 0
    assert waiter_playwright.connect_calls == []
    assert not waiter_connected.is_set()
    assert not waiter_task.done()

    allow_owner_terminal.set()
    if owner_outcome == "abort":
        with pytest.raises(BrowserError):
            await owner_task
        assert cleanup_complete.is_set()
    else:
        await owner_yielded.wait()

    await waiter_task
    assert waiter_probe_calls == 1
    assert waiter_connected.is_set()
    assert waiter_playwright.connect_calls == [config.endpoint]

    if owner_outcome == "promote":
        finish_owner_session.set()
        await owner_task
