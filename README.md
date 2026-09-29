<div align="center">
  <img src="icon.svg" alt="Video & Audio Editing MCP Server" width="128" height="128">
</div>

# 🎬 Video & Audio Editing MCP Server

A comprehensive Model Context Protocol (MCP) server that provides powerful video and audio editing capabilities through FFmpeg. This server enables AI assistants to perform professional-grade video editing operations including format conversion, trimming, overlays, transitions, and advanced audio processing.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![MCP Compatible](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)
[![smithery badge](https://smithery.ai/badge/@misbahsy/video-audio-mcp)](https://smithery.ai/server/@misbahsy/video-audio-mcp)

## ✨ Features

- **🎥 Video Processing**: Format conversion, resolution scaling, codec changes, frame rate adjustment
- **🎵 Audio Processing**: Format conversion, bitrate adjustment, sample rate changes, channel configuration
- **✂️ Editing Tools**: Video trimming, speed adjustment, aspect ratio changes
- **🎨 Overlays & Effects**: Text overlays, image watermarks, subtitle burning
- **🔗 Advanced Editing**: Video concatenation with transitions, B-roll insertion, silence removal
- **🎭 Transitions**: Fade in/out effects, crossfade transitions between clips

## 🛠️ Available Tools

### Core Video Operations
- `extract_audio_from_video` - Extract audio tracks from video files
- `trim_video` - Cut video segments with precise timing
- `convert_video_format` - Convert between video formats (MP4, MOV, AVI, etc.)
- `convert_video_properties` - Comprehensive video property conversion
- `change_aspect_ratio` - Adjust video aspect ratios with padding or cropping
- `set_video_resolution` - Change video resolution with quality preservation
- `set_video_codec` - Switch video codecs (H.264, H.265, VP9, etc.)
- `set_video_bitrate` - Adjust video quality and file size
- `set_video_frame_rate` - Change playback frame rates

### Audio Processing
- `convert_audio_format` - Convert between audio formats (MP3, WAV, AAC, etc.)
- `convert_audio_properties` - Comprehensive audio property conversion
- `set_audio_bitrate` - Adjust audio quality and compression
- `set_audio_sample_rate` - Change audio sample rates
- `set_audio_channels` - Convert between mono and stereo
- `set_video_audio_track_codec` - Change audio codec in video files
- `set_video_audio_track_bitrate` - Adjust audio bitrate in videos
- `set_video_audio_track_sample_rate` - Change audio sample rate in videos
- `set_video_audio_track_channels` - Adjust audio channels in videos

### Creative Tools
- `add_subtitles` - Burn subtitles with custom styling
- `add_text_overlay` - Add dynamic text overlays with timing
- `add_image_overlay` - Insert watermarks and logos
- `add_b_roll` - Insert B-roll footage with transitions
- `add_basic_transitions` - Apply fade in/out effects

### Advanced Editing
- `concatenate_videos` - Join multiple videos with optional transitions
- `change_video_speed` - Create slow-motion or time-lapse effects
- `remove_silence` - Automatically remove silent segments
- `health_check` - Verify server status

## 🚀 Quick Start

This bundle ships three surfaces from one operation core: an **agent skill** (`SKILL.md`), the task-oriented **`video-audio` CLI**, and the retained **MCP server**.

### Prerequisites

1. **Python 3.13+**
2. **FFmpeg and ffprobe** on `PATH` (`brew install ffmpeg` / `sudo apt install ffmpeg`)
3. **uv** - [Install uv](https://docs.astral.sh/uv/getting-started/installation/)

### CLI / agent skill

```bash
# From your working directory (the workspace). Relative paths resolve against it.
/path/to/video-audio-editing/scripts/video-audio health-check
/path/to/video-audio-editing/scripts/video-audio trim-video \
  --video-path in.mp4 --output-video-path out.mp4 --start-time 00:00:05 --end-time 00:00:12
/path/to/video-audio-editing/scripts/video-audio add-text-overlay --video-path in.mp4 \
  --output-video-path titled.mp4 --text-elements-json '[{"text":"Hi","start_time":0,"end_time":2}]'
```

Every former MCP tool is a subcommand (`trim_video` -> `trim-video`) with argument-isomorphic long options; list/dict arguments are strict JSON in `--*-json` options. Each call prints exactly one JSON envelope on stdout (`ok`, `result.message`, `result.outputs`, or `error.code`) and uses stable exit codes: `0` ok, `2` invalid argument/path/overwrite, `3` environment (`BOOTSTRAP_FAILED`, `FFMPEG_MISSING`, `CONFIGURATION_ERROR`), `4` missing/unreadable input, `5` ffmpeg/internal failure.

CLI safety rules: outputs must stay inside the workspace (`VIDEO_AUDIO_WORKSPACE`, default: the caller's working directory); existing outputs are never replaced unless `--overwrite` is passed. See [SKILL.md](SKILL.md) for agent usage and error recovery.

### MCP server (unchanged tool contract)

The 32 MCP tools keep their names, schemas and result text. Only the launch command changed:

```json
{
  "mcpServers": {
    "video-audio": {
      "command": "/path/to/video-audio-editing/scripts/video-audio-mcp"
    }
  }
}
```

> **Migration note:** this project was renamed from `video-audio-mcp/` to `video-audio-editing/`. The old `uv --directory .../video-audio-mcp run server.py` command and the `server.py` entry point no longer exist; point MCP clients at `scripts/video-audio-mcp` instead. The MCP surface keeps its legacy path rule (relative paths resolve against `AUTOBYTEUS_AGENT_WORKSPACE`) and overwrites outputs as before.

## 📖 Usage Examples

### Basic Video Editing

```
"Can you convert this MP4 file to MOV format?"
→ Uses: convert_video_format

"Trim the video from 30 seconds to 2 minutes"
→ Uses: trim_video

"Extract the audio from this video as MP3"
→ Uses: extract_audio_from_video
```

### Advanced Editing Workflows

```
"Create a highlight reel by concatenating these 3 clips with fade transitions"
→ Uses: concatenate_videos with transition effects

"Add my logo watermark to the top-right corner of this video"
→ Uses: add_image_overlay

"Remove all silent parts from this podcast recording"
→ Uses: remove_silence

"Add subtitles to this video with custom styling"
→ Uses: add_subtitles

#### Subtitle best practices
- The tool auto-wraps long lines (including CJK without spaces) by default; no parameter needed.
- Let libass handle wrapping for CJK text: set `WrapStyle` to `0` (smart wrap) so long lines don’t clip. Auto wrapping caps CJK lines to ~34 chars based on video width and font size to avoid edge clipping.
- Default vertical margin is auto (~2% of video height, clamped 12–50) so text sits closer to the bottom; override with `margin_v` if needed.
- Keep subtitles readable: a modest font size (18–24), thin outline, and semi-transparent background.
- Example `font_style` payload to reuse:
```
{
  "font_size": "20",
  "font_color": "&H00FFFFFF",
  "outline_color": "&H00000000",
  "back_colour": "&H80000000",
  "outline_width": "1",
  "border_style": "1",
  "alignment": "2",
  "margin_v": "32",
  "wrap_style": "0"
}
```
```

### Professional Workflows

```
"Convert this 4K video to 1080p, reduce bitrate to 2Mbps, and change to H.265 codec"
→ Uses: convert_video_properties

"Create a social media version: change to 9:16 aspect ratio, add text overlay, and compress"
→ Uses: change_aspect_ratio, add_text_overlay, set_video_bitrate

"Insert B-roll footage at 30 seconds with a fade transition"
→ Uses: add_b_roll
```

## 📁 Path Resolution & Output Locations

- All tool paths (inputs and `output_video_path`) run through `resolve_path`.
- Absolute paths are used as-is.
- Relative paths: if `AUTOBYTEUS_AGENT_WORKSPACE` is set, the path is joined to that directory; otherwise it stays relative to the server’s current working directory.
- Recommendation for agents: set `AUTOBYTEUS_AGENT_WORKSPACE` to a writable workspace or pass absolute output paths (e.g., `/tmp/intro_video.mp4`) to avoid surprises.

### Tool Tips for LLMs & UIs
- Prefer **absolute paths** in tool calls so outputs land where you expect; relative paths resolve against the server’s current working directory.
- Per-parameter help text is provided via `typing.Annotated` + `pydantic.Field(description=...)` (see `create_video_from_image_and_audio` for an example). Add similar annotations to other tools to surface clearer prompts in clients.

## 🎯 Real-World Use Cases

### Content Creation
- **YouTube Videos**: Automated editing, thumbnail generation, format optimization
- **Social Media**: Aspect ratio conversion, text overlays, compression for platforms
- **Podcasts**: Audio extraction, silence removal, format conversion

### Professional Video Production
- **Corporate Videos**: Logo watermarking, subtitle addition, quality standardization
- **Educational Content**: Screen recording processing, chapter markers, accessibility features
- **Marketing Materials**: B-roll integration, transition effects, brand consistency

### Workflow Automation
- **Batch Processing**: Convert entire video libraries to new formats
- **Quality Control**: Standardize video properties across projects
- **Archive Management**: Extract audio for transcription, create preview clips

## 🔍 Tool Reference

### Video Format Conversion

```python
# Convert MP4 to MOV with specific properties
convert_video_properties(
    input_video_path="input.mp4",
    output_video_path="output.mov",
    target_format="mov",
    resolution="1920x1080",
    video_codec="libx264",
    video_bitrate="5M",
    frame_rate=30
)
```

### Text Overlays with Timing

```python
# Add multiple text overlays with different timings
add_text_overlay(
    video_path="input.mp4",
    output_video_path="output.mp4",
    text_elements=[
        {
            "text": "Welcome to our presentation",
            "start_time": "0",
            "end_time": "3",
            "font_size": 48,
            "font_color": "white",
            "x_pos": "center",
            "y_pos": "center"
        },
        {
            "text": "Chapter 1: Introduction",
            "start_time": "5",
            "end_time": "8",
            "font_size": 36,
            "box": True,
            "box_color": "black@0.7"
        }
    ]
)
```

### Advanced Concatenation

```python
# Join videos with crossfade transition
concatenate_videos(
    video_paths=["clip1.mp4", "clip2.mp4"],
    output_video_path="final.mp4",
    transition_effect="dissolve",
    transition_duration=1.5
)
```

## 🛡️ Error Handling

The server includes comprehensive error handling:

- **File Validation**: Checks for file existence before processing
- **Format Support**: Validates supported formats and codecs
- **Graceful Fallbacks**: Attempts codec copying before re-encoding
- **Detailed Logging**: Provides clear error messages for troubleshooting

## 🔧 Troubleshooting

### Common Issues

**FFmpeg not found**
```bash
# Install FFmpeg
# macOS: brew install ffmpeg
# Ubuntu: sudo apt install ffmpeg
# Windows: Download from https://ffmpeg.org/
```

**Permission errors**
```bash
# Ensure file permissions
chmod +x scripts/video-audio scripts/video-audio-mcp
```

**MCP server not connecting**
1. Check file paths in configuration
2. Verify Python environment
3. Test the CLI manually: `scripts/video-audio health-check`
4. Check client logs for detailed errors

### Debug Mode

Run with debug logging:
```bash
scripts/video-audio --debug health-check
```

## 🧪 Testing

This project includes a comprehensive test suite that validates all video and audio editing functions. The tests ensure reliability and help catch regressions during development.

### Test Coverage

The test suite covers:

- **✅ Core Functions**: All 30+ video/audio editing tools
- **🎬 Video Operations**: Format conversion, trimming, resolution changes, codec switching
- **🎵 Audio Processing**: Bitrate adjustment, sample rate changes, channel configuration
- **🎨 Creative Tools**: Text overlays, image watermarks, subtitle burning
- **🔗 Advanced Features**: Video concatenation, B-roll insertion, transitions
- **⚡ Performance**: Speed changes, silence removal, aspect ratio adjustments
- **🛡️ Error Handling**: Invalid inputs, missing files, unsupported formats

### Running Tests

Layout: `tests/unit` (no ffmpeg needed: schema parity with the frozen MCP baseline, CLI mapping, policies, envelopes), `tests/media` (real ffmpeg, legacy result text), `tests/integration` (launcher black box, skill contract, MCP stdio parity). Tests marked `requires_ffmpeg` skip when ffmpeg is absent. Five `tests/media` cases (`test_extract_frame_time_out_of_bounds`, `test_extract_frame_negative_time`, `test_trim_video_fallback_reencode`, `test_add_b_roll`, `test_add_basic_transitions`) fail identically before and after this refactor with ffmpeg 6.1.1 (pre-existing).

#### Prerequisites for Testing

```bash
# Install test dependencies
uv sync --extra test

# Ensure FFmpeg is installed and accessible
ffmpeg -version
```

#### Basic Test Execution

```bash
# Run all tests
pytest tests/

# Run with verbose output
pytest tests/ -v

# Run specific test file
pytest tests/media/test_video_functions.py

# Run specific test function
pytest tests/media/test_video_functions.py::test_extract_audio
```

#### Advanced Test Options

```bash
# Run tests with detailed output and no capture
pytest tests/ -v -s

# Run tests and stop on first failure
pytest tests/ -x

# Run tests with coverage report
pytest tests/ --cov=server

# Run only failed tests from last run
pytest tests/ --lf
```

### Test Environment Setup

The test suite automatically creates:

- **Sample Files**: Test videos, audio files, and images
- **Output Directory**: `tests/test_outputs/` for generated files
- **Temporary Files**: B-roll clips and transition test materials

```bash
# Test files are created in:
tests/
├── test_outputs/          # Generated test results
├── sample_files/          # Auto-generated sample media
├── test_video_functions.py # Main test suite
└── sample.mp4            # Primary test video (if available)
```

### Sample Test Output

```bash
$ pytest tests/media/test_video_functions.py -v

tests/test_video_functions.py::test_health_check PASSED
tests/test_video_functions.py::test_extract_audio PASSED
tests/test_video_functions.py::test_trim_video PASSED
tests/test_video_functions.py::test_convert_audio_properties PASSED
tests/test_video_functions.py::test_convert_video_properties PASSED
tests/test_video_functions.py::test_add_text_overlay PASSED
tests/test_video_functions.py::test_add_subtitles PASSED
tests/test_video_functions.py::test_concatenate_videos PASSED
tests/test_video_functions.py::test_add_b_roll PASSED
tests/test_video_functions.py::test_add_basic_transitions PASSED
tests/test_video_functions.py::test_concatenate_videos_with_xfade PASSED

========================= 25 passed in 45.2s =========================
```

### Test Categories

#### 🎯 **Core Functionality Tests**
- Video format conversion and property changes
- Audio extraction and processing
- File trimming and basic operations

#### 🎨 **Creative Feature Tests**
- Text overlay positioning and timing
- Image watermark placement and opacity
- Subtitle burning with custom styling

#### 🔗 **Advanced Editing Tests**
- Multi-video concatenation with transitions
- B-roll insertion with various positions
- Speed changes and silence removal

#### 🛡️ **Error Handling Tests**
- Invalid file paths and missing files
- Unsupported formats and codecs
- Edge cases and boundary conditions

### Writing Custom Tests

To add new tests for additional functionality:

```python
def test_new_feature():
    """Test description"""
    # Setup
    input_file = "path/to/test/file.mp4"
    output_file = os.path.join(OUTPUT_DIR, "test_output.mp4")
    
    # Execute
    result = your_new_function(input_file, output_file, parameters)
    
    # Validate
    assert "success" in result.lower()
    assert os.path.exists(output_file)
    
    # Optional: Validate output properties
    duration = get_media_duration(output_file)
    assert duration > 0
```

### Continuous Integration

The test suite is designed to work in CI/CD environments:

```yaml
# Example GitHub Actions workflow
- name: Install FFmpeg
  run: sudo apt-get install ffmpeg

- name: Install dependencies
  run: pip install -r requirements.txt pytest

- name: Run tests
  run: pytest tests/ -v
```

### Performance Testing

Some tests include performance validation:

- **Duration Checks**: Verify output video lengths match expectations
- **Quality Validation**: Ensure format conversions maintain quality
- **File Size Monitoring**: Check compression and bitrate changes

### Test Data Management

- **Automatic Cleanup**: Tests clean up temporary files
- **Sample Generation**: Creates test media files as needed
- **Deterministic Results**: Tests produce consistent, reproducible results

> **💡 Tip**: Run tests after any changes to ensure functionality remains intact. The comprehensive test suite catches most issues before they reach production.

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

### Development Setup

```bash
# Clone and setup development environment
git clone https://github.com/misbahsy/video-audio-mcp.git
cd video-audio-mcp

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install development dependencies
pip install -r requirements-dev.txt

# Run tests
pytest tests/
```

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Built with [FastMCP](https://github.com/jlowin/fastmcp) framework
- Powered by [FFmpeg](https://ffmpeg.org/) for media processing
- Inspired by the [Model Context Protocol](https://modelcontextprotocol.io/) specification

## 📞 Support

- 🐛 **Bug Reports**: [GitHub Issues](https://github.com/misbahsy/video-audio-mcp/issues)


---

**Made with ❤️ for the MCP community**
