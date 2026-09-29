import json

import pytest

from video_audio import cli
from video_audio.ffmpeg_runtime import find_binaries

ENVELOPE_KEYS = {"schema_version", "ok", "command"}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_AUDIO_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("VIDEO_AUDIO_CLI_READY_FILE", raising=False)
    return tmp_path


def run(capsys, *argv):
    status = cli.main(list(argv))
    out = capsys.readouterr().out
    return status, json.loads(out) if out.strip() else None


def test_missing_input_is_input_not_found(capsys, workspace):
    status, env = run(capsys, "get-media-duration", "--media-path", "nope.mp4")
    assert status == 4 and env["ok"] is False and env["error"]["code"] == "INPUT_NOT_FOUND"
    assert env["schema_version"] == "1" and env["command"] == "get-media-duration"


def test_usage_errors_are_invalid_argument_envelopes(capsys, workspace):
    status, env = run(capsys, "trim-video", "--video-path", "a.mp4")
    assert status == 2 and env["error"]["code"] == "INVALID_ARGUMENT"
    status, env = run(capsys, "bogus")
    assert status == 2 and env["error"]["code"] == "INVALID_ARGUMENT"


def test_invalid_json_option_is_invalid_argument(capsys, workspace):
    (workspace / "in.mp4").write_bytes(b"x")
    status, env = run(capsys, "concatenate-videos", "--video-paths-json", "not json", "--output-video-path", "o.mp4")
    assert status == 2 and env["error"]["code"] == "INVALID_ARGUMENT"
    status, env = run(capsys, "concatenate-videos", "--video-paths-json", '{"a":1}', "--output-video-path", "o.mp4")
    assert status == 2 and env["error"]["code"] == "INVALID_ARGUMENT"


def test_output_conflict_and_escape(capsys, workspace, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/bin/" + name)
    (workspace / "in.wav").write_bytes(b"x")
    (workspace / "out.wav").write_bytes(b"x")
    status, env = run(capsys, "convert-audio-format", "--input-audio-path", "in.wav",
                      "--output-audio-path", "out.wav", "--target-format", "wav")
    assert status == 2 and env["error"]["code"] == "ARTIFACT_EXISTS"
    status, env = run(capsys, "convert-audio-format", "--input-audio-path", "in.wav",
                      "--output-audio-path", "../out.wav", "--target-format", "wav")
    assert status == 2 and env["error"]["code"] == "ARTIFACT_PATH_REJECTED"


def test_missing_ffmpeg_is_ffmpeg_missing(capsys, workspace, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    (workspace / "in.mp4").write_bytes(b"x")
    status, env = run(capsys, "get-media-duration", "--media-path", "in.mp4")
    assert status == 3 and env["error"]["code"] == "FFMPEG_MISSING"
    status, env = run(capsys, "health-check")
    assert status == 3 and env["error"]["code"] == "FFMPEG_MISSING"


def test_bad_workspace_is_configuration_error(capsys, monkeypatch):
    monkeypatch.setenv("VIDEO_AUDIO_WORKSPACE", "relative/dir")
    status, env = run(capsys, "health-check")
    assert status == 3 and env["error"]["code"] == "CONFIGURATION_ERROR"


@pytest.mark.skipif(None in find_binaries().values(), reason="ffmpeg not installed")
def test_health_check_success_reports_binaries(capsys, workspace):
    status, env = run(capsys, "health-check")
    assert status == 0 and env["ok"] is True
    assert set(env["result"]["data"]) == {"ffmpeg", "ffprobe", "workspace"}


def test_ready_token_written(capsys, workspace, monkeypatch, tmp_path):
    ready = tmp_path / "ready"
    monkeypatch.setenv("VIDEO_AUDIO_CLI_READY_FILE", str(ready))
    cli.main(["bogus"])
    capsys.readouterr()
    assert ready.read_text().strip() == "video-audio-cli-ready-v1"
