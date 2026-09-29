"""ffmpeg resolution and the MP4 encoding invocation used by the recorder worker."""

from __future__ import annotations

import os
import shutil
import struct
from collections.abc import Mapping
from pathlib import Path

from browser_automation.errors import recording_dependency_missing

FFMPEG_ENV = "BROWSER_AUTOMATION_FFMPEG_BIN"


def resolve_ffmpeg(env: Mapping[str, str] | None = None) -> Path:
    """`BROWSER_AUTOMATION_FFMPEG_BIN` when set, else `ffmpeg` on PATH."""

    actual = env if env is not None else os.environ
    configured = actual.get(FFMPEG_ENV)
    if configured is not None and configured.strip():
        candidate = Path(configured.strip()).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
        raise recording_dependency_missing(f"{FFMPEG_ENV} does not identify an executable ffmpeg: {candidate}")
    found = shutil.which("ffmpeg", path=actual.get("PATH"))
    if found is None:
        raise recording_dependency_missing(
            f"ffmpeg is required for recording; install it or set {FFMPEG_ENV} to its path."
        )
    return Path(found).resolve()


def jpeg_dimensions(data: bytes) -> tuple[int, int]:
    """(width, height) from a baseline or progressive JPEG start-of-frame segment."""

    if data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG image")
    index = 2
    while index + 4 <= len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        (length,) = struct.unpack(">H", data[index + 2 : index + 4])
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[index + 5 : index + 9])
            return width, height
        index += 2 + length
    raise ValueError("JPEG has no start-of-frame segment")


def even_dimensions(width: int, height: int) -> tuple[int, int]:
    """H.264 with yuv420p needs even dimensions."""

    return max(2, width - width % 2), max(2, height - height % 2)


def build_ffmpeg_args(ffmpeg: Path, *, fps: int, width: int, height: int, output: Path) -> list[str]:
    """Constant-rate MJPEG frames on stdin → H.264 MP4 at the first frame's (even) size."""

    scale = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
    )
    return [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-f", "image2pipe",
        "-framerate", str(fps),
        "-c:v", "mjpeg",
        "-i", "-",
        "-vf", scale,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-f", "mp4",
        str(output),
    ]
