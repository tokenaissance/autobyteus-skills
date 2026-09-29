import subprocess
import sys
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[2] / "src")


def test_core_and_cli_import_without_mcp_package():
    code = (
        "import sys; sys.modules['mcp'] = None\n"
        "import video_audio.cli, video_audio.operations.registry, video_audio.paths, video_audio.errors\n"
        "from video_audio.operations.registry import all_operations\n"
        "assert len(all_operations()) == 32\n"
    )
    result = subprocess.run([sys.executable, "-c", code], env={"PYTHONPATH": SRC}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
