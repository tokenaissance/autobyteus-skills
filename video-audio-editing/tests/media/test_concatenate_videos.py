import os
import sys
import math
import pytest
pytestmark = pytest.mark.requires_ffmpeg
import ffmpeg
import subprocess

# Make sure server.py is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from legacy_tools import concatenate_videos


# Paths and constants
TESTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(TESTS_DIR, "test_outputs")
SAMPLE_VIDEO_1 = os.path.join(TESTS_DIR, "sample_video_3s_1.mp4")
SAMPLE_VIDEO_2 = os.path.join(TESTS_DIR, "sample_video_3s_2.mp4")
SAMPLE_VIDEO_3 = os.path.join(TESTS_DIR, "sample_video_3s_3.mp4")
# Videos with different properties for a more robust test
SAMPLE_VIDEO_DIFF_RES_FPS = os.path.join(TESTS_DIR, "sample_video_diff_res_fps.mp4")
SAMPLE_VIDEO_NO_AUDIO = os.path.join(TESTS_DIR, "sample_video_no_audio.mp4")
SAMPLE_DURATION = 3

def _create_sample_video(path: str, duration: int, resolution: str = "320x240", rate: int = 24, has_audio: bool = True):
    """Generate a simple sample video via ffmpeg if it is missing."""
    if os.path.exists(path):
        return
    
    command = [
        "ffmpeg",
        "-f", "lavfi", "-i", f"testsrc=size={resolution}:rate={rate}:duration={duration}",
    ]

    if has_audio:
        command.extend(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-shortest"])
    else:
        # If no audio, we must specify the duration for the video stream directly
        command.extend(["-t", str(duration)])

    command.extend([
        "-c:v", "libx264",
        "-c:a", "aac",
        "-pix_fmt", "yuv420p",
        "-y",
        path,
    ])

    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        error_output = exc.stderr if hasattr(exc, "stderr") else str(exc)
        pytest.fail(f"Failed to create sample video {path}. Ensure FFmpeg is installed. Error: {error_output}")


def setup_module(module):
    """Prepare reusable directories and sample media."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _create_sample_video(SAMPLE_VIDEO_1, SAMPLE_DURATION)
    _create_sample_video(SAMPLE_VIDEO_2, SAMPLE_DURATION)
    _create_sample_video(SAMPLE_VIDEO_3, SAMPLE_DURATION)
    _create_sample_video(SAMPLE_VIDEO_DIFF_RES_FPS, SAMPLE_DURATION, resolution="640x480", rate=30)
    _create_sample_video(SAMPLE_VIDEO_NO_AUDIO, SAMPLE_DURATION, has_audio=False)


def _remove_file_if_exists(path: str):
    if os.path.exists(path):
        os.remove(path)


def _probe_media(path: str) -> dict:
    """Helper to probe media, raising a pytest failure on ffmpeg errors."""
    try:
        return ffmpeg.probe(path)
    except ffmpeg.Error as exc:
        error_output = exc.stderr.decode("utf8") if exc.stderr else str(exc)
        pytest.fail(f"ffprobe failed for {path}: {error_output}")


def _rate_to_float(rate: str) -> float:
    num, den = rate.split("/")
    return float(num) / float(den)


def _create_video_with_audio_props(
    path: str,
    *,
    rate: int,
    sample_rate: int,
    channels: int,
    duration: float = 1.0,
):
    command = [
        "ffmpeg",
        "-f", "lavfi", "-i", f"testsrc=size=160x120:rate={rate}:duration={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate={sample_rate}:duration={duration}",
        "-shortest",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-ar", str(sample_rate),
        "-ac", str(channels),
        "-y",
        path,
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        error_output = exc.stderr if hasattr(exc, "stderr") else str(exc)
        pytest.fail(f"Failed to create mixed-property sample video {path}: {error_output}")


def test_concatenate_two_videos_no_transition():
    """Tests standard concatenation of two videos."""
    output_path = os.path.join(OUTPUT_DIR, "concat_two_videos.mp4")
    _remove_file_if_exists(output_path)
    
    result = concatenate_videos([SAMPLE_VIDEO_1, SAMPLE_VIDEO_2], output_path)
    
    try:
        assert "successfully" in result
        assert os.path.exists(output_path)
        
        probe = _probe_media(output_path)
        duration = float(probe["format"]["duration"])
        expected_duration = SAMPLE_DURATION * 2
        assert math.isclose(duration, expected_duration, rel_tol=0.1)
        
        assert any(s['codec_type'] == 'video' for s in probe['streams'])
        assert any(s['codec_type'] == 'audio' for s in probe['streams'])
    finally:
        _remove_file_if_exists(output_path)


def test_concatenate_multiple_videos_no_transition():
    """Tests standard concatenation of three videos to replicate user's issue."""
    output_path = os.path.join(OUTPUT_DIR, "concat_three_videos.mp4")
    _remove_file_if_exists(output_path)
    
    video_paths = [SAMPLE_VIDEO_1, SAMPLE_VIDEO_2, SAMPLE_VIDEO_3]
    result = concatenate_videos(video_paths, output_path)
    
    try:
        assert "successfully" in result
        assert os.path.exists(output_path)
        
        probe = _probe_media(output_path)
        duration = float(probe["format"]["duration"])
        expected_duration = SAMPLE_DURATION * 3
        assert math.isclose(duration, expected_duration, rel_tol=0.1)

        assert any(s['codec_type'] == 'video' for s in probe['streams'])
        assert any(s['codec_type'] == 'audio' for s in probe['streams'])
    finally:
        _remove_file_if_exists(output_path)


def test_concatenate_videos_normalizes_mixed_audio_and_caps_high_fps():
    """Mixed TTS-like audio rates/channels and high-FPS inputs produce safe output."""
    video_24k_mono = os.path.join(OUTPUT_DIR, "concat_input_120fps_24k_mono.mp4")
    video_48k_stereo = os.path.join(OUTPUT_DIR, "concat_input_30fps_48k_stereo.mp4")
    output_path = os.path.join(OUTPUT_DIR, "concat_mixed_audio_capped_fps.mp4")

    for path in [video_24k_mono, video_48k_stereo, output_path]:
        _remove_file_if_exists(path)

    try:
        _create_video_with_audio_props(video_24k_mono, rate=120, sample_rate=24000, channels=1)
        _create_video_with_audio_props(video_48k_stereo, rate=30, sample_rate=48000, channels=2)

        result = concatenate_videos([video_24k_mono, video_48k_stereo], output_path)

        assert "successfully" in result, f"Concatenation failed with message: {result}"
        assert os.path.exists(output_path)

        probe = _probe_media(output_path)
        video_stream = next(s for s in probe['streams'] if s['codec_type'] == 'video')
        audio_stream = next(s for s in probe['streams'] if s['codec_type'] == 'audio')

        assert audio_stream['codec_name'] == 'aac'
        assert int(audio_stream['sample_rate']) == 48000
        assert int(audio_stream['channels']) == 2
        assert _rate_to_float(video_stream['r_frame_rate']) <= 60.5
    finally:
        for path in [video_24k_mono, video_48k_stereo, output_path]:
            _remove_file_if_exists(path)


def test_concatenate_videos_with_different_properties():
    """Tests concatenation of videos with different resolutions, frame rates, and one with no audio."""
    output_path = os.path.join(OUTPUT_DIR, "concat_varied_videos.mp4")
    _remove_file_if_exists(output_path)

    video_paths = [SAMPLE_VIDEO_1, SAMPLE_VIDEO_DIFF_RES_FPS, SAMPLE_VIDEO_NO_AUDIO]
    result = concatenate_videos(video_paths, output_path)

    try:
        assert "successfully" in result, f"Concatenation failed with message: {result}"
        assert os.path.exists(output_path)

        probe = _probe_media(output_path)
        duration = float(probe["format"]["duration"])
        expected_duration = SAMPLE_DURATION * 3
        assert math.isclose(duration, expected_duration, rel_tol=0.1)

        video_stream = next(s for s in probe['streams'] if s['codec_type'] == 'video')
        # The concat filter should upscale to the largest resolution
        assert video_stream['width'] == 640
        assert video_stream['height'] == 480
        
        assert any(s['codec_type'] == 'audio' for s in probe['streams'])
    finally:
        _remove_file_if_exists(output_path)


def test_concatenate_two_videos_with_xfade_transition():
    """Tests concatenation of two videos with an xfade transition."""
    output_path = os.path.join(OUTPUT_DIR, "concat_xfade.mp4")
    _remove_file_if_exists(output_path)
    
    transition_duration = 1.0
    result = concatenate_videos(
        [SAMPLE_VIDEO_1, SAMPLE_VIDEO_2],
        output_path,
        transition_effect='dissolve',
        transition_duration=transition_duration
    )
    
    try:
        assert "successfully" in result
        assert os.path.exists(output_path)
        
        probe = _probe_media(output_path)
        duration = float(probe["format"]["duration"])
        # Expected duration is sum of both minus the transition overlap
        expected_duration = (SAMPLE_DURATION * 2) - transition_duration
        assert math.isclose(duration, expected_duration, rel_tol=0.1)
    finally:
        _remove_file_if_exists(output_path)


def test_concatenate_single_video():
    """Tests the case where only one video is provided."""
    output_path = os.path.join(OUTPUT_DIR, "concat_single.mp4")
    _remove_file_if_exists(output_path)

    result = concatenate_videos([SAMPLE_VIDEO_1], output_path)
    
    try:
        assert "Single video processed" in result
        assert os.path.exists(output_path)
        probe = _probe_media(output_path)
        duration = float(probe["format"]["duration"])
        assert math.isclose(duration, SAMPLE_DURATION, rel_tol=0.1)
    finally:
        _remove_file_if_exists(output_path)


def test_concatenate_missing_input_file():
    """Tests that the function fails gracefully if an input file is missing."""
    output_path = os.path.join(OUTPUT_DIR, "concat_missing_input.mp4")
    _remove_file_if_exists(output_path)

    missing_path = "non_existent_video.mp4"
    result = concatenate_videos([SAMPLE_VIDEO_1, missing_path], output_path)
    
    assert "Error: Input video file not found" in result
    assert not os.path.exists(output_path)


def test_concatenate_xfade_with_more_than_two_videos_fails():
    """Tests that xfade is correctly rejected for more than two videos."""
    output_path = os.path.join(OUTPUT_DIR, "concat_xfade_fail.mp4")
    _remove_file_if_exists(output_path)
    
    video_paths = [SAMPLE_VIDEO_1, SAMPLE_VIDEO_2, SAMPLE_VIDEO_3]
    result = concatenate_videos(
        video_paths,
        output_path,
        transition_effect='dissolve',
        transition_duration=1.0
    )
    
    assert "xfade transition is currently only supported for exactly two videos" in result
    assert not os.path.exists(output_path)
