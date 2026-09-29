"""Per-family CLI happy paths and SKILL.md recipes through the real launcher (API/E2E coverage)."""

import os
import shutil
import subprocess

import pytest

from .support import BUNDLE, HAS_FFMPEG, SAMPLE_VIDEO, probe_duration, run_launcher

pytestmark = pytest.mark.integration
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
AUDIO = BUNDLE / "tests" / "sample_audio.wav"
IMAGE = BUNDLE / "tests" / "sample.png"


@pytest.fixture
def ws(tmp_path):
    shutil.copy(SAMPLE_VIDEO, tmp_path / "in.mp4")
    shutil.copy(SAMPLE_VIDEO, tmp_path / "in2.mp4")
    shutil.copy(AUDIO, tmp_path / "a.wav")
    shutil.copy(AUDIO, tmp_path / "b.wav")
    shutil.copy(IMAGE, tmp_path / "logo.png")
    return tmp_path


def ok(ws, *args):
    status, env, err = run_launcher(ws, *args)
    assert status == 0 and env["ok"] is True, (args, env, err)
    for out in env["result"]["outputs"]:
        assert os.path.isabs(out) and os.path.getsize(out) > 0
    return env


def streams(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, check=True)
    return r.stdout.split()


@needs_ffmpeg
def test_subtitles_cjk_with_font_style(ws):
    (ws / "s.srt").write_text("1\n00:00:00,000 --> 00:00:02,000\n你好，世界\n", encoding="utf-8")
    ok(ws, "add-subtitles", "--video-path", "in.mp4", "--srt-file-path", "s.srt", "--output-video-path", "sub.mp4",
       "--font-style-json", '{"font_size":"22","margin_v":"36"}')


@needs_ffmpeg
def test_text_and_image_overlay(ws):
    ok(ws, "add-text-overlay", "--video-path", "in.mp4", "--output-video-path", "t.mp4",
       "--text-elements-json", '[{"text":"Hello","start_time":0,"end_time":3}]')
    ok(ws, "add-image-overlay", "--video-path", "in.mp4", "--image-path", "logo.png", "--output-video-path", "i.mp4",
       "--position", "top_right", "--opacity", "0.6")


@needs_ffmpeg
def test_concatenate_video_audio_and_xfade(ws):
    ok(ws, "concatenate-videos", "--video-paths-json", '["in.mp4","in2.mp4"]', "--output-video-path", "j.mp4")
    ok(ws, "concatenate-videos", "--video-paths-json", '["in.mp4","in2.mp4"]', "--output-video-path", "x.mp4",
       "--transition-effect", "fade", "--transition-duration", "1")
    ok(ws, "concatenate-audios", "--audio-paths-json", '["a.wav","b.wav"]', "--output-audio-path", "j.wav")
    assert probe_duration(ws / "j.wav") > probe_duration(ws / "a.wav") * 1.9


@needs_ffmpeg
def test_extract_audio_frame_replace_audio(ws):
    ok(ws, "extract-audio-from-video", "--video-path", "in.mp4", "--output-audio-path", "o.mp3", "--audio-codec", "mp3")
    ok(ws, "extract-frame-from-video", "--video-path", "in.mp4", "--output-image-path", "f.jpg", "--frame-location", "first")
    ok(ws, "replace-audio-track", "--video-path", "in.mp4", "--new-audio-path", "a.wav", "--output-video-path", "r.mp4",
       "--match-duration-mode", "stretch_video")


@needs_ffmpeg
def test_speed_aspect_silence_fades(ws):
    ok(ws, "change-video-speed", "--video-path", "in.mp4", "--output-video-path", "sp.mp4", "--speed-factor", "2")
    assert probe_duration(ws / "sp.mp4") < probe_duration(ws / "in.mp4") * 0.7
    # pad mode fails identically on this sample in the legacy code (ffmpeg 6.1.1): pre-existing, not asserted here.
    ok(ws, "change-aspect-ratio", "--video-path", "in.mp4", "--output-video-path", "crop.mp4",
       "--target-aspect-ratio", "9:16", "--resize-mode", "crop")
    assert "video" in streams(ws / "crop.mp4")[0]
    ok(ws, "remove-silence", "--media-path", "a.wav", "--output-media-path", "ns.wav")
    ok(ws, "add-basic-transitions", "--video-path", "in.mp4", "--output-video-path", "fd.mp4",
       "--transition-type", "fade_in", "--duration-seconds", "1")


@needs_ffmpeg
def test_image_plus_audio_convert_and_set_wrappers(ws):
    ok(ws, "create-video-from-image-and-audio", "--image-path", "logo.png", "--audio-path", "a.wav", "--output-video-path", "c.mp4")
    ok(ws, "convert-video-format", "--input-video-path", "in.mp4", "--output-video-path", "o.mov", "--target-format", "mov")
    ok(ws, "convert-audio-format", "--input-audio-path", "a.wav", "--output-audio-path", "o.mp3", "--target-format", "mp3")
    ok(ws, "set-video-resolution", "--input-video-path", "in.mp4", "--output-video-path", "res.mp4", "--resolution", "640x360")
    assert "640,360" in streams(ws / "res.mp4")[0]
    ok(ws, "set-video-codec", "--input-video-path", "in.mp4", "--output-video-path", "cd.mp4", "--video-codec", "libx264")
    ok(ws, "set-audio-bitrate", "--input-audio-path", "a.wav", "--output-audio-path", "br.mp3", "--bitrate", "96k")


@needs_ffmpeg
def test_add_b_roll(ws):
    ok(ws, "add-b-roll", "--main-video-path", "in.mp4", "--output-video-path", "br.mp4",
       "--broll-clips-json", '[{"clip_path":"in2.mp4","insert_at_timestamp":1,"duration":1}]')
