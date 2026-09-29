import os
import sys
import pytest
pytestmark = pytest.mark.requires_ffmpeg
import shutil
import ffmpeg
import subprocess
import math

# Add the parent directory to sys.path to allow importing from 'server'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the specific function we are testing
from legacy_tools import replace_audio_track

# --- Test Constants ---
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test_outputs")
TEST_FILES_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Define paths for sample files. The test will create them if they don't exist.
# The user can replace these with their own files for testing by matching the names.
SAMPLE_VIDEO_SHORT = os.path.join(TEST_FILES_DIR, "sample_video_2s.mp4")
SAMPLE_AUDIO_LONG = os.path.join(TEST_FILES_DIR, "sample_audio_4s.wav")
SAMPLE_VIDEO_LONG = os.path.join(TEST_FILES_DIR, "sample_video_4s.mp4")
SAMPLE_AUDIO_SHORT = os.path.join(TEST_FILES_DIR, "sample_audio_2s.wav")

# Durations for generated files
SHORT_DURATION = 2
LONG_DURATION = 4

# --- Helper Functions ---

def _create_sample_video(path: str, duration: int):
    """Creates a sample video with audio if it doesn't exist."""
    if os.path.exists(path):
        print(f"Sample video file already exists: {path}")
        return
    print(f"Creating sample video: {path} with duration {duration}s")
    try:
        command = [
            'ffmpeg',
            '-f', 'lavfi', '-i', f'testsrc=duration={duration}:size=320x240:rate=24',
            '-f', 'lavfi', '-i', f'anullsrc=r=44100:cl=stereo',
            '-c:v', 'libx264',
            '-c:a', 'aac',
            '-t', str(duration),
            '-y',
            path
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        error_output = e.stderr if hasattr(e, 'stderr') else str(e)
        pytest.fail(f"Failed to create sample video {path}. FFmpeg might not be in PATH. Error: {error_output}")

def _create_sample_audio(path: str, duration: int):
    """Creates a silent sample audio file if it doesn't exist."""
    if os.path.exists(path):
        print(f"Sample audio file already exists: {path}")
        return
    print(f"Creating sample audio: {path} with duration {duration}s")
    try:
        command = [
            'ffmpeg',
            '-f', 'lavfi', '-i', f'anullsrc=r=44100:cl=stereo',
            '-t', str(duration),
            '-y',
            path
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        error_output = e.stderr if hasattr(e, 'stderr') else str(e)
        pytest.fail(f"Failed to create sample audio {path}. FFmpeg might not be in PATH. Error: {error_output}")


# --- Test Setup & Teardown ---

def setup_module(module):
    """Setup for the test module: create output directory and sample media."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _create_sample_video(SAMPLE_VIDEO_SHORT, SHORT_DURATION)
    _create_sample_audio(SAMPLE_AUDIO_LONG, LONG_DURATION)
    _create_sample_video(SAMPLE_VIDEO_LONG, LONG_DURATION)
    _create_sample_audio(SAMPLE_AUDIO_SHORT, SHORT_DURATION)

def teardown_module(module):
    """Teardown for the test module."""
    # The sample files are intentionally left for user inspection or replacement.
    pass

# --- Test Cases ---

def test_replace_audio_stretch_video():
    """Test stretching a shorter video to match a longer audio's duration."""
    output_video_path = os.path.join(OUTPUT_DIR, "stretched_video.mp4")
    
    result = replace_audio_track(SAMPLE_VIDEO_SHORT, SAMPLE_AUDIO_LONG, output_video_path, match_duration_mode='stretch_video')

    assert "Audio track replaced and video duration stretched" in result
    assert os.path.exists(output_video_path)

    try:
        probe = ffmpeg.probe(output_video_path)
        duration = float(probe['format']['duration'])
        assert math.isclose(duration, LONG_DURATION, rel_tol=0.1), \
            f"Expected stretched video duration to be ~{LONG_DURATION}s, but got {duration}s."
    except ffmpeg.Error as e:
        pytest.fail(f"Failed to probe output video: {e.stderr.decode('utf8')}")
    finally:
        if os.path.exists(output_video_path):
            os.remove(output_video_path)

def test_replace_audio_squeeze_video():
    """Test squeezing a longer video to match a shorter audio's duration."""
    output_video_path = os.path.join(OUTPUT_DIR, "squeezed_video.mp4")
    
    result = replace_audio_track(SAMPLE_VIDEO_LONG, SAMPLE_AUDIO_SHORT, output_video_path, match_duration_mode='stretch_video')

    assert "Audio track replaced and video duration stretched" in result
    assert os.path.exists(output_video_path)

    try:
        probe = ffmpeg.probe(output_video_path)
        duration = float(probe['format']['duration'])
        assert math.isclose(duration, SHORT_DURATION, rel_tol=0.1), \
            f"Expected squeezed video duration to be ~{SHORT_DURATION}s, but got {duration}s."
    except ffmpeg.Error as e:
        pytest.fail(f"Failed to probe output video: {e.stderr.decode('utf8')}")
    finally:
        if os.path.exists(output_video_path):
            os.remove(output_video_path)
            
def test_replace_audio_shortest_mode_video_shorter():
    """Test 'shortest' mode where the video is shorter than the new audio."""
    output_video_path = os.path.join(OUTPUT_DIR, "shortest_video_shorter.mp4")
    
    result = replace_audio_track(SAMPLE_VIDEO_SHORT, SAMPLE_AUDIO_LONG, output_video_path, match_duration_mode='shortest')

    assert "Audio track replaced successfully" in result and "shorter input" in result
    assert os.path.exists(output_video_path)

    try:
        probe = ffmpeg.probe(output_video_path)
        duration = float(probe['format']['duration'])
        # The output duration should match the SHORTEST input, which is the video.
        assert math.isclose(duration, SHORT_DURATION, rel_tol=0.1), \
            f"Expected 'shortest' mode duration to be ~{SHORT_DURATION}s, but got {duration}s."
    except ffmpeg.Error as e:
        pytest.fail(f"Failed to probe output video: {e.stderr.decode('utf8')}")
    finally:
        if os.path.exists(output_video_path):
            os.remove(output_video_path)

def test_replace_audio_shortest_mode_audio_shorter():
    """Test 'shortest' mode where the new audio is shorter than the video."""
    output_video_path = os.path.join(OUTPUT_DIR, "shortest_audio_shorter.mp4")
    
    result = replace_audio_track(SAMPLE_VIDEO_LONG, SAMPLE_AUDIO_SHORT, output_video_path, match_duration_mode='shortest')

    assert "Audio track replaced successfully" in result and "shorter input" in result
    assert os.path.exists(output_video_path)

    try:
        probe = ffmpeg.probe(output_video_path)
        duration = float(probe['format']['duration'])
        # The output duration should match the SHORTEST input, which is the audio.
        assert math.isclose(duration, SHORT_DURATION, rel_tol=0.1), \
            f"Expected 'shortest' mode duration to be ~{SHORT_DURATION}s, but got {duration}s."
    except ffmpeg.Error as e:
        pytest.fail(f"Failed to probe output video: {e.stderr.decode('utf8')}")
    finally:
        if os.path.exists(output_video_path):
            os.remove(output_video_path)

def test_replace_audio_missing_video_file():
    """Test failure when the source video file is missing."""
    output_video_path = os.path.join(OUTPUT_DIR, "missing_video.mp4")
    missing_video_path = "non_existent_video.mp4"
    
    result = replace_audio_track(missing_video_path, SAMPLE_AUDIO_SHORT, output_video_path, match_duration_mode='stretch_video')

    assert "Error: Input video file not found" in result
    assert not os.path.exists(output_video_path)
    
def test_replace_audio_missing_audio_file():
    """Test failure when the new audio file is missing."""
    output_video_path = os.path.join(OUTPUT_DIR, "missing_audio.mp4")
    missing_audio_path = "non_existent_audio.wav"
    
    result = replace_audio_track(SAMPLE_VIDEO_SHORT, missing_audio_path, output_video_path, match_duration_mode='stretch_video')

    assert "Error: New audio file not found" in result
    assert not os.path.exists(output_video_path)

def test_replace_audio_invalid_mode():
    """Test failure when an invalid mode is provided."""
    output_video_path = os.path.join(OUTPUT_DIR, "invalid_mode.mp4")
    
    result = replace_audio_track(SAMPLE_VIDEO_SHORT, SAMPLE_AUDIO_SHORT, output_video_path, match_duration_mode='invalid_mode')

    assert "Error: Invalid match_duration_mode" in result
    assert not os.path.exists(output_video_path)
