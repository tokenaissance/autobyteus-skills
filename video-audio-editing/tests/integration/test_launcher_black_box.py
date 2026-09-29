"""Black-box launcher checks from an unrelated working directory."""

import shutil

import pytest

from .support import HAS_FFMPEG, SAMPLE_VIDEO, probe_duration, run_launcher

pytestmark = pytest.mark.integration
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")


@pytest.fixture
def workspace(tmp_path):
    shutil.copy(SAMPLE_VIDEO, tmp_path / "in.mp4")
    return tmp_path


@needs_ffmpeg
def test_health_check_and_trim_from_unrelated_cwd(workspace):
    status, env, _ = run_launcher(workspace, "health-check")
    assert status == 0 and env["ok"] is True
    status, env, _ = run_launcher(workspace, "trim-video", "--video-path", "in.mp4",
                                  "--output-video-path", "out/clip.mp4", "--start-time", "1", "--end-time", "3")
    assert status == 0, env
    (path,) = env["result"]["outputs"]
    assert path == str(workspace / "out" / "clip.mp4")
    assert abs(probe_duration(path) - 2.0) < 0.5


@needs_ffmpeg
def test_default_reencode_and_no_reencode_flag(workspace):
    status, env, _ = run_launcher(workspace, "trim-video", "--video-path", "in.mp4", "--output-video-path", "a.mp4",
                                  "--start-time", "0", "--end-time", "1")
    assert "re-encoded" in env["result"]["message"]
    status, env, _ = run_launcher(workspace, "trim-video", "--video-path", "in.mp4", "--output-video-path", "b.mp4",
                                  "--start-time", "0", "--end-time", "1", "--no-reencode")
    assert "codec copy" in env["result"]["message"]


@needs_ffmpeg
def test_overwrite_protection_and_flag(workspace):
    args = ["trim-video", "--video-path", "in.mp4", "--output-video-path", "o.mp4", "--start-time", "0", "--end-time", "1"]
    assert run_launcher(workspace, *args)[0] == 0
    status, env, _ = run_launcher(workspace, *args)
    assert status == 2 and env["error"]["code"] == "ARTIFACT_EXISTS"
    assert run_launcher(workspace, *args, "--overwrite")[0] == 0


@needs_ffmpeg
def test_multiline_quoted_json_text_overlay(workspace):
    elements = '[\n  {"text": "It\'s a test: hello, world", "start_time": 0, "end_time": 2}\n]'
    status, env, _ = run_launcher(workspace, "add-text-overlay", "--video-path", "in.mp4",
                                  "--output-video-path", "t.mp4", "--text-elements-json", elements)
    assert status == 0, env


@needs_ffmpeg
def test_missing_input_and_ffmpeg_failure_codes(workspace):
    status, env, _ = run_launcher(workspace, "get-media-duration", "--media-path", "nope.mp4")
    assert status == 4 and env["error"]["code"] == "INPUT_NOT_FOUND"
    (workspace / "bad.mp4").write_text("not media")
    status, env, _ = run_launcher(workspace, "get-media-duration", "--media-path", "bad.mp4")
    assert status == 4 and env["error"]["code"] == "MEDIA_UNREADABLE"
    status, env, _ = run_launcher(workspace, "trim-video", "--video-path", "bad.mp4", "--output-video-path", "x.mp4",
                                  "--start-time", "0", "--end-time", "1")
    assert status == 5 and env["error"]["code"] == "FFMPEG_FAILED"


def test_invalid_json_and_missing_option_are_single_envelopes(workspace):
    status, env, _ = run_launcher(workspace, "concatenate-videos", "--video-paths-json", "[oops",
                                  "--output-video-path", "o.mp4")
    assert status == 2 and env["error"]["code"] == "INVALID_ARGUMENT"
    status, env, _ = run_launcher(workspace, "trim-video", "--video-path", "in.mp4")
    assert status == 2 and env["error"]["code"] == "INVALID_ARGUMENT"


def test_bootstrap_failure_when_uv_missing(workspace):
    status, env, _ = run_launcher(workspace, "health-check", env={"UV_BIN": "/nonexistent", "PATH": "/bin:/usr/bin", "HOME": "/nonexistent"})
    if status == 3:  # uv lives in /usr/bin on some hosts; only assert the contract when uv is truly hidden
        assert env["error"]["code"] == "BOOTSTRAP_FAILED"
