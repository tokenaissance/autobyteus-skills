import os
import sys
import math
import pytest
pytestmark = pytest.mark.requires_ffmpeg
import ffmpeg
import subprocess

# Make sure server.py is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from legacy_tools import trim_video

# Paths and constants
TESTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(TESTS_DIR, "test_outputs")
SAMPLE_VIDEO = os.path.join(TESTS_DIR, "sample_video_5s.mp4")

# Trim window used by the main happy-path test
TRIM_START = "00:00:01"
TRIM_END = "00:00:03"
EXPECTED_DURATION_SECONDS = 2


def _create_sample_video(path: str, duration: int):
    """Generate a simple sample video via ffmpeg if it is missing."""
    if os.path.exists(path):
        return
    command = [
        "ffmpeg",
        "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=24:duration={duration}",
        "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
        "-shortest",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-pix_fmt", "yuv420p",
        "-y",
        path,
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        error_output = exc.stderr if hasattr(exc, "stderr") else str(exc)
        pytest.fail(f"Failed to create sample video {path}. Ensure FFmpeg is installed. Error: {error_output}")


def setup_module(module):
    """Prepare reusable directories and sample media."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _create_sample_video(SAMPLE_VIDEO, duration=5)


def _remove_file_if_exists(path: str):
    if os.path.exists(path):
        os.remove(path)


def _probe_duration(path: str) -> float:
    """Helper to read media duration, raising a pytest failure on ffmpeg errors."""
    try:
        probe_data = ffmpeg.probe(path)
        return float(probe_data["format"]["duration"])
    except ffmpeg.Error as exc:
        error_output = exc.stderr.decode("utf8") if exc.stderr else str(exc)
        pytest.fail(f"ffprobe failed for {path}: {error_output}")


def test_trim_video_success_copy_path():
    """End-to-end test to ensure trimming succeeds and duration matches in the codec-copy branch."""
    output_path = os.path.join(OUTPUT_DIR, "trimmed_copy.mp4")
    _remove_file_if_exists(output_path)

    result = trim_video(SAMPLE_VIDEO, output_path, TRIM_START, TRIM_END)

    try:
        assert "Video trimmed successfully" in result
        assert os.path.exists(output_path), "Output video was not created"
        duration = _probe_duration(output_path)
        assert math.isclose(duration, EXPECTED_DURATION_SECONDS, rel_tol=0.1), (
            f"Expected duration ~{EXPECTED_DURATION_SECONDS}s but got {duration}s"
        )
    finally:
        _remove_file_if_exists(output_path)


def test_trim_video_fallback_reencode(monkeypatch):
    """Ensure the fallback re-encode path is used when the codec-copy attempt fails."""
    output_path = os.path.join(OUTPUT_DIR, "trimmed_reencode.mp4")
    _remove_file_if_exists(output_path)

    class MockOutput:
        def __init__(self, should_fail: bool, target_path: str):
            self.should_fail = should_fail
            self.target_path = target_path

        def run(self, capture_stdout=True, capture_stderr=True, overwrite_output=True):
            if self.should_fail:
                raise ffmpeg.Error("mock_cmd", b"", b"copy failed")
            # Simulate creation of an output file
            with open(self.target_path, "wb") as handle:
                handle.write(b"mock video data")

    class MockStream:
        def __init__(self, should_fail: bool, target_path: str):
            self.should_fail = should_fail
            self.target_path = target_path

        def output(self, *args, **kwargs):
            return MockOutput(self.should_fail, self.target_path)

    def mock_ffmpeg_input(*args, **kwargs):
        mock_ffmpeg_input.call_count += 1
        should_fail = mock_ffmpeg_input.call_count == 1
        return MockStream(should_fail, output_path)

    mock_ffmpeg_input.call_count = 0
    monkeypatch.setattr(ffmpeg, "input", mock_ffmpeg_input)

    result = trim_video("any_source.mp4", output_path, "0", "1")

    try:
        assert mock_ffmpeg_input.call_count == 2, "Expected both copy and fallback attempts"
        assert "Video trimmed successfully (re-encoded)" in result
        assert os.path.exists(output_path), "Fallback did not create an output file"
    finally:
        _remove_file_if_exists(output_path)


def test_trim_video_missing_source():
    """If the input path is invalid, the function should surface a useful error and avoid writing output."""
    missing_path = os.path.join(TESTS_DIR, "nonexistent_input.mp4")
    output_path = os.path.join(OUTPUT_DIR, "trimmed_missing.mp4")
    _remove_file_if_exists(output_path)

    result = trim_video(missing_path, output_path, "0", "1")

    try:
        assert "Error trimming video" in result or "Error: Input video file not found" in result
        assert not os.path.exists(output_path), "Output file should not exist when trimming fails"
    finally:
        _remove_file_if_exists(output_path)
