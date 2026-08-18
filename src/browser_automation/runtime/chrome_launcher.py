"""Atomic cross-process Chrome establishment for one configured CDP port."""

from __future__ import annotations

import asyncio
import errno
import fcntl
import json
import os
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from collections.abc import Awaitable, Callable
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from browser_automation.errors import browser_unavailable
from browser_automation.runtime.config import BrowserRuntimeConfig

Probe = Callable[[BrowserRuntimeConfig], Awaitable[bool]]
ProcessFactory = Callable[..., subprocess.Popen[Any]]
ExecutableResolver = Callable[[BrowserRuntimeConfig], Path]
TerminationRunner = Callable[[subprocess.Popen[Any], int, float], None]

MACOS_CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)
LINUX_CHROME_COMMANDS = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
)
LINUX_CHROME_CANDIDATES = (
    "/usr/bin/google-chrome",
    "/opt/google/chrome/google-chrome",
)


class ChromeAvailabilityState(str, Enum):
    DURABLE_EXISTING = "DURABLE_EXISTING"
    PENDING_OWNED = "PENDING_OWNED"
    PROMOTED = "PROMOTED"
    ABORTED = "ABORTED"


class EstablishmentGate:
    """One owner-only, non-inheritable advisory lock for a debug port."""

    def __init__(self, descriptor: int, path: Path) -> None:
        self._descriptor = descriptor
        self.path = path

    @property
    def descriptor(self) -> int:
        return self._descriptor

    @classmethod
    async def acquire(
        cls,
        *,
        port: int,
        deadline: float,
        poll_interval: float,
        directory: Path | None = None,
    ) -> "EstablishmentGate":
        root = directory or _default_gate_directory()
        descriptor = _open_gate_file(root, port)
        acquired = False
        loop = asyncio.get_running_loop()
        try:
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    return cls(descriptor, root / f"chrome-{port}.lock")
                except BlockingIOError:
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        raise browser_unavailable(
                            f"Timed out waiting to establish Chrome on debug port {port}."
                        )
                    await asyncio.sleep(min(poll_interval, remaining))
        finally:
            if not acquired:
                os.close(descriptor)

    def release(self) -> None:
        descriptor = self._descriptor
        if descriptor < 0:
            return
        self._descriptor = -1
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _default_gate_directory() -> Path:
    uid = os.getuid() if hasattr(os, "getuid") else os.getpid()
    return Path(tempfile.gettempdir()) / f"browser-automation-runtime-{uid}"


def _open_gate_file(root: Path, port: int) -> int:
    try:
        root.mkdir(mode=0o700, parents=False, exist_ok=True)
        root_stat = root.lstat()
        if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
            raise OSError(errno.ENOTDIR, "runtime gate root is not a directory", str(root))
        if hasattr(os, "getuid") and root_stat.st_uid != os.getuid():
            raise PermissionError(f"Runtime gate root is not owned by the current user: {root}")
        if stat.S_IMODE(root_stat.st_mode) & 0o077:
            root.chmod(0o700)

        path = root / f"chrome-{port}.lock"
        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        try:
            file_stat = os.fstat(descriptor)
            if not stat.S_ISREG(file_stat.st_mode):
                raise OSError(errno.EINVAL, "runtime gate is not a regular file", str(path))
            if hasattr(os, "getuid") and file_stat.st_uid != os.getuid():
                raise PermissionError(f"Runtime gate is not owned by the current user: {path}")
            os.fchmod(descriptor, 0o600)
            os.set_inheritable(descriptor, False)
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise
    except OSError as exc:
        raise browser_unavailable("A secure Chrome establishment gate could not be opened.") from exc


class ChromeAvailability:
    """A durable endpoint observation or an exclusively pending owned launch."""

    def __init__(
        self,
        *,
        config: BrowserRuntimeConfig,
        state: ChromeAvailabilityState,
        gate: EstablishmentGate | None = None,
        process: subprocess.Popen[Any] | None = None,
        process_group_id: int | None = None,
        termination_runner: TerminationRunner | None = None,
    ) -> None:
        self.config = config
        self.state = state
        self._gate = gate
        self._process = process
        self._process_group_id = process_group_id
        self._termination_runner = termination_runner or _terminate_process_group

    @classmethod
    def durable_existing(cls, config: BrowserRuntimeConfig) -> "ChromeAvailability":
        return cls(config=config, state=ChromeAvailabilityState.DURABLE_EXISTING)

    @classmethod
    def pending_owned(
        cls,
        *,
        config: BrowserRuntimeConfig,
        gate: EstablishmentGate,
        process: subprocess.Popen[Any],
        termination_runner: TerminationRunner,
    ) -> "ChromeAvailability":
        return cls(
            config=config,
            state=ChromeAvailabilityState.PENDING_OWNED,
            gate=gate,
            process=process,
            process_group_id=process.pid,
            termination_runner=termination_runner,
        )

    @property
    def is_pending_owned(self) -> bool:
        return self.state is ChromeAvailabilityState.PENDING_OWNED

    @property
    def has_abort_authority(self) -> bool:
        return self.is_pending_owned and self._process is not None and self._process_group_id is not None

    def promote(self) -> None:
        if not self.is_pending_owned:
            raise RuntimeError("Only a pending owned Chrome launch can be promoted.")
        gate = self._gate
        if gate is None:
            raise RuntimeError("Pending Chrome launch lost its establishment gate.")

        # Relinquish all process cleanup authority before another caller can acquire.
        self._process = None
        self._process_group_id = None
        self._gate = None
        self.state = ChromeAvailabilityState.PROMOTED
        gate.release()

    async def abort(self) -> None:
        if not self.is_pending_owned:
            return
        gate = self._gate
        process = self._process
        process_group_id = self._process_group_id
        if gate is None or process is None or process_group_id is None:
            raise RuntimeError("Pending Chrome launch has incomplete abort authority.")

        termination = asyncio.create_task(
            asyncio.to_thread(
                self._termination_runner,
                process,
                process_group_id,
                self.config.termination_timeout_seconds,
            )
        )
        cancellation: asyncio.CancelledError | None = None
        while not termination.done():
            try:
                await asyncio.shield(termination)
            except asyncio.CancelledError as exc:
                cancellation = exc
        termination.result()

        # Exact cleanup has completed before abort authority is cleared or unlocked.
        self._process = None
        self._process_group_id = None
        self._gate = None
        self.state = ChromeAvailabilityState.ABORTED
        gate.release()
        if cancellation is not None:
            raise cancellation


class ChromeLauncher:
    """Classify or establish Chrome while enforcing the per-port gate invariant."""

    def __init__(
        self,
        config: BrowserRuntimeConfig,
        *,
        probe: Probe | None = None,
        process_factory: ProcessFactory = subprocess.Popen,
        executable_resolver: ExecutableResolver | None = None,
        termination_runner: TerminationRunner | None = None,
        gate_directory: Path | None = None,
    ) -> None:
        self.config = config
        self._probe = probe or probe_cdp_endpoint
        self._process_factory = process_factory
        self._executable_resolver = executable_resolver or resolve_chrome_executable
        self._termination_runner = termination_runner or _terminate_process_group
        self._gate_directory = gate_directory

    async def ensure_available(self) -> ChromeAvailability:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.config.establishment_timeout_seconds
        gate = await EstablishmentGate.acquire(
            port=self.config.port,
            deadline=deadline,
            poll_interval=self.config.poll_interval_seconds,
            directory=self._gate_directory,
        )
        pending: ChromeAvailability | None = None
        try:
            if await self._probe_under_gate():
                gate.release()
                return ChromeAvailability.durable_existing(self.config)

            executable = self._executable_resolver(self.config)
            process = self._spawn(executable)
            pending = ChromeAvailability.pending_owned(
                config=self.config,
                gate=gate,
                process=process,
                termination_runner=self._termination_runner,
            )
            await self._wait_until_ready(process, deadline)
            return pending
        except BaseException:
            if pending is not None:
                await _finish_abort(pending)
            else:
                gate.release()
            raise

    def _spawn(self, executable: Path) -> subprocess.Popen[Any]:
        arguments = [
            str(executable),
            "--no-first-run",
            "--flag-switches-begin",
            "--flag-switches-end",
            f"--remote-debugging-port={self.config.port}",
            f"--profile-directory={self.config.profile_directory}",
        ]
        if self.config.user_data_dir is not None:
            arguments.append(f"--user-data-dir={self.config.user_data_dir}")

        try:
            self.config.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.config.log_path.open("ab") as log_file:
                return self._process_factory(
                    arguments,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    close_fds=True,
                )
        except OSError as exc:
            raise browser_unavailable("Chrome could not be started with the configured runtime settings.") from exc

    async def _wait_until_ready(self, process: subprocess.Popen[Any], deadline: float) -> None:
        loop = asyncio.get_running_loop()
        while True:
            return_code = process.poll()
            if return_code is not None:
                raise browser_unavailable(
                    f"Chrome exited before its CDP endpoint became ready (status {return_code})."
                )
            if await self._probe_under_gate():
                return
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise browser_unavailable(
                    f"Timed out waiting for Chrome on debug port {self.config.port}."
                )
            await asyncio.sleep(min(self.config.poll_interval_seconds, remaining))

    async def _probe_under_gate(self) -> bool:
        """Keep the gate held until a bounded authoritative probe actually finishes."""

        probe_task = asyncio.create_task(self._probe(self.config))
        cancellation: asyncio.CancelledError | None = None
        while not probe_task.done():
            try:
                await asyncio.shield(probe_task)
            except asyncio.CancelledError as exc:
                cancellation = exc
        result = probe_task.result()
        if cancellation is not None:
            raise cancellation
        return result


async def _finish_abort(availability: ChromeAvailability) -> None:
    abort_task = asyncio.create_task(availability.abort())
    cancellation: asyncio.CancelledError | None = None
    while not abort_task.done():
        try:
            await asyncio.shield(abort_task)
        except asyncio.CancelledError as exc:
            cancellation = exc
    abort_task.result()
    if cancellation is not None:
        raise cancellation


async def probe_cdp_endpoint(config: BrowserRuntimeConfig) -> bool:
    def probe() -> bool:
        try:
            request = Request(config.version_endpoint, headers={"Accept": "application/json"})
            with urlopen(request, timeout=config.probe_timeout_seconds) as response:
                if response.status != 200:
                    return False
                payload = json.loads(response.read(1_048_577).decode("utf-8"))
            websocket_url = payload.get("webSocketDebuggerUrl") if isinstance(payload, dict) else None
            return isinstance(websocket_url, str) and websocket_url.startswith(("ws://", "wss://"))
        except (HTTPError, URLError, OSError, UnicodeError, json.JSONDecodeError, ValueError):
            return False

    return await asyncio.to_thread(probe)


def resolve_chrome_executable(config: BrowserRuntimeConfig) -> Path:
    if config.chrome_executable is not None:
        return config.chrome_executable

    candidates: list[str | None] = list(MACOS_CHROME_CANDIDATES)
    candidates.extend(shutil.which(command) for command in LINUX_CHROME_COMMANDS)
    candidates.extend(LINUX_CHROME_CANDIDATES)
    for candidate in candidates:
        if candidate:
            path = Path(candidate)
            if path.is_file() and os.access(path, os.X_OK):
                return path.resolve()
    raise browser_unavailable(
        "No supported Chrome/Chromium executable was found. "
        "Set BROWSER_AUTOMATION_CHROME_BIN to an executable file."
    )


def _terminate_process_group(
    process: subprocess.Popen[Any],
    process_group_id: int,
    timeout_seconds: float,
) -> None:
    _signal_group(process_group_id, signal.SIGTERM)
    if process.poll() is None:
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            _signal_group(process_group_id, signal.SIGKILL)
            process.wait(timeout=timeout_seconds)
    else:
        process.wait(timeout=0)

    if _wait_for_group_exit(process_group_id, timeout_seconds):
        return
    _signal_group(process_group_id, signal.SIGKILL)
    if not _wait_for_group_exit(process_group_id, timeout_seconds):
        raise RuntimeError("Owned Chrome process group did not terminate.")


def _wait_for_group_exit(process_group_id: int, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            os.killpg(process_group_id, 0)
        except ProcessLookupError:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(min(0.05, timeout_seconds))


def _signal_group(process_group_id: int, sig: signal.Signals) -> None:
    try:
        os.killpg(process_group_id, sig)
    except ProcessLookupError:
        return
