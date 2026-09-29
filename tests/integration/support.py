import json
import os
import shutil
import subprocess
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[2]
LAUNCHER = BUNDLE / "scripts" / "video-audio"
MCP_LAUNCHER = BUNDLE / "scripts" / "video-audio-mcp"
SAMPLE_VIDEO = BUNDLE / "tests" / "sample.mp4"
HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def run_launcher(cwd, *args, env=None, input_text=None):
    full_env = {**os.environ, **(env or {})}
    proc = subprocess.run([str(LAUNCHER), *args], cwd=cwd, env=full_env, capture_output=True,
                          text=True, input=input_text, timeout=180)
    body = proc.stdout.strip()
    return proc.returncode, json.loads(body) if body.startswith("{") else body, proc.stderr


def probe_duration(path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True)
    return float(out.stdout.strip())
