"""Detached recorder worker: one CDP screencast of one tab, encoded to MP4 by ffmpeg.

Run as `python -m browser_automation.recording.worker …` by RecordingService with the tool's own
interpreter. It connects directly to the configured CDP endpoint (it never launches a browser),
writes a ready marker once frames flow, and on SIGTERM or target loss finalizes the MP4 and writes
its status file.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import logging
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

from browser_automation.errors import BrowserError
from browser_automation.policy import ArtifactPolicy
from browser_automation.recording.ffmpeg import build_ffmpeg_args, even_dimensions, jpeg_dimensions
from browser_automation.recording.state import RECORDING_SCHEMA_VERSION, write_json_atomic
from browser_automation.runtime.session import BrowserSession

logger = logging.getLogger("browser_automation.recording.worker")

CONNECT_TIMEOUT_SECONDS = 20.0
FIRST_FRAME_TIMEOUT_SECONDS = 10.0
FFMPEG_EXIT_TIMEOUT_SECONDS = 60.0
MAX_CATCH_UP_SECONDS = 1.0


@dataclass(slots=True)
class FrameSource:
    """Latest screencast frame only: memory stays bounded to one JPEG."""

    latest: bytes | None = None
    received: int = 0
    first_frame: asyncio.Event = field(default_factory=asyncio.Event)

    def push(self, data: bytes) -> None:
        self.latest = data
        self.received += 1
        self.first_frame.set()


@dataclass(slots=True)
class StopSignal:
    event: asyncio.Event = field(default_factory=asyncio.Event)
    reason: str = "stopped"

    def trigger(self, reason: str) -> None:
        if not self.event.is_set():
            self.reason = reason
            self.event.set()


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="browser_automation.recording.worker")
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--tab-id", required=True)
    parser.add_argument("--fps", type=int, required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--temp-file", required=True)
    parser.add_argument("--output-file", required=True)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--ready-file", required=True)
    parser.add_argument("--status-file", required=True)
    return parser.parse_args(argv)


async def pump_frames(
    frames: FrameSource,
    stdin: Any,
    fps: int,
    stop: StopSignal,
    *,
    clock: Any = time.monotonic,
) -> tuple[int, float]:
    """Write the latest frame at a constant rate until stopped; returns (frames, seconds).

    A slow encoder is caught up by repeating the latest frame (bounded to one second of frames);
    beyond that, ticks are dropped so memory and backlog stay bounded.
    """

    interval = 1.0 / fps
    started = clock()
    scheduled = 0
    written = 0
    while not stop.event.is_set():
        due = int((clock() - started) * fps) + 1
        if due - scheduled > fps * MAX_CATCH_UP_SECONDS:
            scheduled = due - 1
        while scheduled < due and frames.latest is not None:
            stdin.write(frames.latest)
            await stdin.drain()
            scheduled += 1
            written += 1
        next_tick = started + scheduled * interval
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.event.wait(), timeout=max(0.0, next_tick - clock()))
    return written, written / fps


def _preserve_partial(temp: Path, output: Path) -> Path | None:
    if not temp.exists() or temp.stat().st_size == 0:
        temp.unlink(missing_ok=True)
        return None
    for index in range(100):
        suffix = "" if index == 0 else f"-{index}"
        candidate = output.with_name(f"{output.stem}.partial{suffix}{output.suffix}")
        if not candidate.exists():
            temp.rename(candidate)
            return candidate
    return temp


async def _find_page(browser: Any, tab_id: str) -> Any:
    if not browser.contexts:
        raise BrowserError("BROWSER_UNAVAILABLE", "The CDP endpoint exposes no browser context.", retryable=True, exit_status=3)
    return await BrowserSession(browser=browser, context=browser.contexts[0]).resolve_page(tab_id)


async def record(args: argparse.Namespace, stop: StopSignal) -> dict[str, Any]:
    temp = Path(args.temp_file)
    output = Path(args.output_file)
    ready_file = Path(args.ready_file)
    frames = FrameSource()
    status: dict[str, Any] = {
        "schema_version": RECORDING_SCHEMA_VERSION,
        "state": "failed",
        "end_reason": "error",
        "output_file": str(output),
        "duration_seconds": 0.0,
        "frames": 0,
    }
    ffmpeg: asyncio.subprocess.Process | None = None
    cdp: Any = None
    ready = False
    try:
        async with async_playwright() as playwright:
            try:
                browser = await asyncio.wait_for(
                    playwright.chromium.connect_over_cdp(args.endpoint), CONNECT_TIMEOUT_SECONDS
                )
            except Exception as exc:
                raise BrowserError(
                    "BROWSER_UNAVAILABLE",
                    f"Could not connect to {args.endpoint}: {exc}",
                    retryable=True,
                    exit_status=3,
                ) from exc
            # A no-op listener keeps page dialogs (alert/confirm) open for the app or a human:
            # without one, this long-lived client would auto-dismiss every dialog while recording.
            for context in browser.contexts:
                context.on("dialog", lambda _dialog: None)
            browser.on("disconnected", lambda _browser: stop.trigger("target_closed"))
            page = await _find_page(browser, args.tab_id)
            page.on("close", lambda _page: stop.trigger("target_closed"))

            cdp = await page.context.new_cdp_session(page)

            def on_frame(event: dict[str, Any]) -> None:
                frames.push(base64.b64decode(event["data"]))
                asyncio.create_task(_ack(cdp, event["sessionId"]))

            cdp.on("Page.screencastFrame", on_frame)
            await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 80, "everyNthFrame": 1})
            await asyncio.wait_for(frames.first_frame.wait(), FIRST_FRAME_TIMEOUT_SECONDS)

            width, height = even_dimensions(*jpeg_dimensions(frames.latest or b""))
            log_target = sys.stderr
            ffmpeg = await asyncio.create_subprocess_exec(
                *build_ffmpeg_args(Path(args.ffmpeg), fps=args.fps, width=width, height=height, output=temp),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=log_target,
            )
            write_json_atomic(ready_file, {"ok": True, "started_at": _iso_now(), "width": width, "height": height})
            ready = True
            logger.info("recording %s at %sx%s, %s fps", args.tab_id, width, height, args.fps)

            written, duration = await pump_frames(frames, ffmpeg.stdin, args.fps, stop)
            status.update(frames=written, duration_seconds=round(duration, 3), end_reason=stop.reason)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(cdp.send("Page.stopScreencast"), 2.0)
    except BrowserError as exc:
        status["error"] = {"code": exc.code, "message": exc.message}
    except (asyncio.TimeoutError, TimeoutError):
        status["error"] = {"code": "RECORDING_FAILED", "message": "No screencast frame arrived from the tab."}
    except (BrokenPipeError, ConnectionResetError) as exc:
        status["error"] = {"code": "RECORDING_FAILED", "message": f"ffmpeg stopped accepting frames: {exc}"}
    except Exception as exc:  # the status file must always be written
        logger.exception("recorder failed")
        status["error"] = {"code": "RECORDING_FAILED", "message": str(exc) or type(exc).__name__}

    ffmpeg_ok = await _finish_ffmpeg(ffmpeg)
    if not ready:
        write_json_atomic(ready_file, {"ok": False, "error": status.get("error")})
    if "error" not in status and not ffmpeg_ok:
        status["error"] = {"code": "RECORDING_FAILED", "message": "ffmpeg did not finish the MP4 successfully."}
    return _finalize(status, temp, output, overwrite=args.overwrite)


async def _ack(cdp: Any, session_id: int) -> None:
    with contextlib.suppress(Exception):
        await cdp.send("Page.screencastFrameAck", {"sessionId": session_id})


async def _finish_ffmpeg(ffmpeg: asyncio.subprocess.Process | None) -> bool:
    if ffmpeg is None:
        return False
    with contextlib.suppress(Exception):
        if ffmpeg.stdin is not None and not ffmpeg.stdin.is_closing():
            ffmpeg.stdin.close()
            await ffmpeg.stdin.wait_closed()
    try:
        return await asyncio.wait_for(ffmpeg.wait(), FFMPEG_EXIT_TIMEOUT_SECONDS) == 0
    except asyncio.TimeoutError:
        ffmpeg.kill()
        await ffmpeg.wait()
        return False


def _finalize(status: dict[str, Any], temp: Path, output: Path, *, overwrite: bool) -> dict[str, Any]:
    if "error" not in status and not overwrite and output.exists():
        status["error"] = {"code": "ARTIFACT_EXISTS", "message": "The output file appeared while recording."}
    if "error" in status:
        partial = _preserve_partial(temp, output)
        status["partial_file"] = str(partial) if partial else None
        return status
    try:
        ArtifactPolicy(output.parent).commit_temporary(temp, output, overwrite=overwrite)
    except BrowserError as exc:
        status["error"] = {"code": exc.code, "message": exc.message}
        status["partial_file"] = None
        return status
    status.update(state="completed", bytes_written=output.stat().st_size)
    return status


async def run(argv: list[str]) -> int:
    args = parse_args(argv)
    stop = StopSignal()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.trigger, "stopped")
    status = await record(args, stop)
    status["finished_at"] = _iso_now()
    write_json_atomic(Path(args.status_file), status)
    return 0 if status["state"] == "completed" else 1


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(message)s")
    raise SystemExit(asyncio.run(run(sys.argv[1:])))


if __name__ == "__main__":
    main()
