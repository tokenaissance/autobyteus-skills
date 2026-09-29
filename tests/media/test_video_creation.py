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

# Import the specific function we are testing from its new location
from legacy_tools import create_video_from_image_and_audio

# --- Test Constants ---
SAMPLE_IMAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sample.png")
# The test is now dynamic and will work with any audio file here.
# We keep the name from the user's log.
SAMPLE_AUDIO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sample_audio.wav") 
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test_outputs")
# AUDIO_DURATION is no longer needed as the test will determine it dynamically.

# --- Helper Functions ---
def _create_sample_audio():
    """Creates a short, silent WAV audio file for testing if it doesn't exist."""
    if os.path.exists(SAMPLE_AUDIO):
        print(f"Sample audio file already exists: {SAMPLE_AUDIO}")
        return
    try:
        # This will only run if the user deletes the sample_audio.wav file.
        # It creates a 5-second silent file as a fallback.
        print(f"Sample audio file not found. Creating a default 5-second silent audio: {SAMPLE_AUDIO}")
        command = [
            'ffmpeg',
            '-f', 'lavfi',
            '-i', f'anullsrc=r=44100:cl=stereo', # Silent audio source
            '-t', '5',                          # Default duration
            '-y',
            SAMPLE_AUDIO
        ]
        subprocess.run(command, check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        pytest.fail(f"Failed to create sample audio file. FFmpeg might not be in PATH. Error: {e}")

# --- Test Setup & Teardown ---
def setup_module(module):
    """Setup for the test module: create output directory and sample audio."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _create_sample_audio()

def teardown_module(module):
    """Teardown for the test module."""
    # Per user request, the sample audio file is no longer removed after tests.
    pass

# --- Test Cases ---
def test_create_video_success():
    """Test the successful creation of a video from a valid image and audio file."""
    output_video_path = os.path.join(OUTPUT_DIR, "video_from_image.mp4")
    
    # Step 1: Dynamically determine the expected duration from the actual audio file.
    try:
        probe_audio = ffmpeg.probe(SAMPLE_AUDIO)
        expected_duration = float(probe_audio['format']['duration'])
    except (ffmpeg.Error, KeyError, ValueError) as e:
        pytest.fail(f"Failed to probe the sample audio file to get its duration: {e}")

    # Step 2: Execute the function
    result = create_video_from_image_and_audio(SAMPLE_IMAGE, SAMPLE_AUDIO, output_video_path)
    
    # 3. Check for success message and file existence
    assert "Video created successfully" in result, f"Expected success message, but got: {result}"
    assert os.path.exists(output_video_path), "Output video file was not created."
    
    # 4. Probe the output file to verify its properties
    try:
        probe_video = ffmpeg.probe(output_video_path)
        
        # Check duration is correct against the dynamically determined duration
        video_duration = float(probe_video['format']['duration'])
        assert math.isclose(video_duration, expected_duration, rel_tol=0.1), \
            f"Expected duration ~{expected_duration}s (from audio file), but got {video_duration}s"
        
        # Check for the presence of both video and audio streams
        video_stream = next((s for s in probe_video['streams'] if s['codec_type'] == 'video'), None)
        audio_stream = next((s for s in probe_video['streams'] if s['codec_type'] == 'audio'), None)
        assert video_stream is not None, "Output video is missing a video stream."
        assert audio_stream is not None, "Output video is missing an audio stream."

    except ffmpeg.Error as e:
        pytest.fail(f"Failed to probe the output video file: {e.stderr.decode('utf8')}")
    finally:
        # Clean up the created video file for the next test run
        if os.path.exists(output_video_path):
            # os.remove(output_video_path)
            pass

def test_create_video_missing_image():
    """Test failure case where the input image file does not exist."""
    output_video_path = os.path.join(OUTPUT_DIR, "video_from_missing_image.mp4")
    missing_image_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "non_existent_image.png")
    
    # Execute the function
    result = create_video_from_image_and_audio(missing_image_path, SAMPLE_AUDIO, output_video_path)
    
    # Assert that an error is returned and no file is created
    assert "Error: Input image file not found" in result
    assert not os.path.exists(output_video_path)

def test_create_video_missing_audio():
    """Test failure case where the input audio file does not exist."""
    output_video_path = os.path.join(OUTPUT_DIR, "video_from_missing_audio.mp4")
    missing_audio_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "non_existent_audio.mp3")
    
    # Execute the function
    result = create_video_from_image_and_audio(SAMPLE_IMAGE, missing_audio_path, output_video_path)
    
    # Assert that an error is returned and no file is created
    assert "Error: Input audio file not found" in result
    assert not os.path.exists(output_video_path)
