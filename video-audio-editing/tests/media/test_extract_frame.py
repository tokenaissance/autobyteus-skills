import os
import sys
import pytest
pytestmark = pytest.mark.requires_ffmpeg
import shutil
import subprocess

# Add the parent directory to sys.path to allow importing from 'server'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the specific function we are testing
from legacy_tools import extract_frame_from_video 
# --- Test Constants ---
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test_outputs")
TEST_FILES_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_VIDEO = os.path.join(TEST_FILES_DIR, "sample_video_5s.mp4")
VIDEO_DURATION = 5

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

# --- Test Setup & Teardown ---
def setup_module(module):
    """Setup for the test module: create output directory and sample media."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _create_sample_video(SAMPLE_VIDEO, VIDEO_DURATION)

def teardown_module(module):
    """Teardown for the test module."""
    # The sample video is intentionally left for user inspection or replacement.
    pass

# --- Test Cases ---
def test_extract_first_frame_success():
    """Test extracting the first frame of a video."""
    output_image_path = os.path.join(OUTPUT_DIR, "first_frame.png")
    try:
        result = extract_frame_from_video(SAMPLE_VIDEO, output_image_path, frame_location='first')
        assert "Frame successfully extracted" in result
        assert os.path.exists(output_image_path)
        assert os.path.getsize(output_image_path) > 0
    finally:
        if os.path.exists(output_image_path):
            os.remove(output_image_path)

def test_extract_last_frame_success():
    """Test extracting the last frame of a video."""
    output_image_path = os.path.join(OUTPUT_DIR, "last_frame.png")
    try:
        result = extract_frame_from_video(SAMPLE_VIDEO, output_image_path, frame_location='last')
        assert "Frame successfully extracted" in result
        assert os.path.exists(output_image_path)
        assert os.path.getsize(output_image_path) > 0
    finally:
        if os.path.exists(output_image_path):
            os.remove(output_image_path)

def test_extract_frame_by_seconds_success():
    """Test extracting a frame at a specific time in seconds."""
    output_image_path = os.path.join(OUTPUT_DIR, "frame_at_2_5s.png")
    try:
        result = extract_frame_from_video(SAMPLE_VIDEO, output_image_path, frame_location=2.5)
        assert "Frame successfully extracted" in result
        assert os.path.exists(output_image_path)
        assert os.path.getsize(output_image_path) > 0
    finally:
        if os.path.exists(output_image_path):
            os.remove(output_image_path)

def test_extract_frame_by_timestamp_success():
    """Test extracting a frame at a specific timestamp string."""
    output_image_path = os.path.join(OUTPUT_DIR, "frame_at_timestamp.png")
    try:
        result = extract_frame_from_video(SAMPLE_VIDEO, output_image_path, frame_location='00:00:03')
        assert "Frame successfully extracted" in result
        assert os.path.exists(output_image_path)
        assert os.path.getsize(output_image_path) > 0
    finally:
        if os.path.exists(output_image_path):
            os.remove(output_image_path)

def test_extract_frame_missing_video():
    """Test failure when the source video file is missing."""
    output_image_path = os.path.join(OUTPUT_DIR, "missing_video_frame.png")
    missing_video_path = "non_existent_video.mp4"
    
    result = extract_frame_from_video(missing_video_path, output_image_path, frame_location='first')
    
    assert "Error: Input video file not found" in result
    assert not os.path.exists(output_image_path)

def test_extract_frame_time_out_of_bounds():
    """Test failure when the specified time is beyond the video's duration."""
    output_image_path = os.path.join(OUTPUT_DIR, "out_of_bounds_frame.png")
    
    result = extract_frame_from_video(SAMPLE_VIDEO, output_image_path, frame_location=VIDEO_DURATION + 5)
    
    assert "is beyond the video duration" in result
    assert not os.path.exists(output_image_path)

def test_extract_frame_negative_time():
    """Test failure when the specified time is a negative number."""
    output_image_path = os.path.join(OUTPUT_DIR, "negative_time_frame.png")
    
    result = extract_frame_from_video(SAMPLE_VIDEO, output_image_path, frame_location=-1.0)
    
    assert "cannot be negative" in result
    assert not os.path.exists(output_image_path)

def test_extract_frame_invalid_location_string():
    """Test failure with an invalid string for frame_location that isn't a valid timestamp."""
    output_image_path = os.path.join(OUTPUT_DIR, "invalid_location_frame.png")
    
    result = extract_frame_from_video(SAMPLE_VIDEO, output_image_path, frame_location='middle')
    
    # We expect an ffmpeg error because 'middle' is not a valid time/duration specifier.
    assert "Error extracting frame" in result
    assert not os.path.exists(output_image_path)
