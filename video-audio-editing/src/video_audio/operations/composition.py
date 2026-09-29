import ffmpeg
import os
import shutil
import tempfile
from typing import Union, Annotated
from pydantic import Field

from video_audio.contracts import OperationResult
from video_audio.errors import MediaError, classify, classify_media
from video_audio.ffmpeg_runtime import get_media_properties, parse_time_to_seconds
from video_audio.operations.registry import MediaContext, operation

@operation(description="Extract audio from a video file. Prefer absolute paths for inputs/outputs; relative paths are resolved against the server working directory.")
def extract_audio_from_video(
    ctx: MediaContext,
    video_path: Annotated[str, Field(description="Absolute path to the input video; relative resolves vs server cwd")],
    output_audio_path: Annotated[str, Field(description="Absolute path for extracted audio; relative resolves vs server cwd")],
    audio_codec: Annotated[str, Field(description="Audio codec (e.g., mp3, aac, wav)")] = 'mp3'
) -> OperationResult:
    """Extracts audio from a video file and saves it. Prefer absolute paths; relative paths are resolved against the server working directory."""
    video_path = ctx.paths.input(video_path)
    output_audio_path = ctx.paths.output(output_audio_path)
    try:
        ffmpeg.input(video_path).output(output_audio_path, acodec=audio_codec).run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
        return OperationResult(message=f"Audio extracted successfully to {output_audio_path}")
    except ffmpeg.Error as e:
        raise MediaError.ffmpeg_failed(f"Error extracting audio: {e.stderr.decode('utf8') if e.stderr else str(e)}")
    except FileNotFoundError:
        raise MediaError.input_not_found(f"Error: Input video file not found at {video_path}")
    except MediaError:
        raise
    except Exception as e:
        raise classify(f"An unexpected error occurred: {str(e)}", e)

@operation(description="Replace a video's audio track. Prefer absolute paths for all paths; relative paths are resolved against the server working directory.")
def replace_audio_track(
    ctx: MediaContext,
    video_path: Annotated[str, Field(description="Absolute path to the input video; relative resolves vs server cwd")],
    new_audio_path: Annotated[str, Field(description="Absolute path to the new audio file; relative resolves vs server cwd")],
    output_video_path: Annotated[str, Field(description="Absolute path for output video; relative resolves vs server cwd")],
    match_duration_mode: Annotated[str, Field(description="Duration handling: 'shortest' or 'stretch_video'")] = 'shortest'
) -> OperationResult:
    """Replaces a video's audio track with a new one, with options for handling duration mismatches. Prefer absolute paths; relative paths are resolved against the server working directory."""
    video_path = ctx.paths.input(video_path)
    new_audio_path = ctx.paths.input(new_audio_path)
    output_video_path = ctx.paths.output(output_video_path)

    if not os.path.exists(video_path):
        raise MediaError.input_not_found(f"Error: Input video file not found at {video_path}")
    if not os.path.exists(new_audio_path):
        raise MediaError.input_not_found(f"Error: New audio file not found at {new_audio_path}")
    try:
        if match_duration_mode not in ['shortest', 'stretch_video']:
            raise MediaError.invalid_argument(f"Error: Invalid match_duration_mode '{match_duration_mode}'. Must be 'shortest' or 'stretch_video'.")

        input_video = ffmpeg.input(video_path)
        input_audio = ffmpeg.input(new_audio_path)
        
        if match_duration_mode == 'shortest':
            (ffmpeg.output(input_video.video, input_audio.audio, output_video_path, vcodec='copy', acodec='aac', shortest=None)
             .run(capture_stdout=True, capture_stderr=True, overwrite_output=True))
            return OperationResult(message=f"Audio track replaced successfully. Output saved to {output_video_path} with duration matching the shorter input.")

        elif match_duration_mode == 'stretch_video':
            video_props = get_media_properties(video_path)
            audio_props = get_media_properties(new_audio_path)
            video_duration = video_props.get('duration', 0.0)
            audio_duration = audio_props.get('duration', 0.0)

            if video_duration == 0:
                raise MediaError.media_unreadable(f"Error: Could not determine duration of video file {video_path}.")
            if audio_duration == 0:
                raise MediaError.media_unreadable(f"Error: Could not determine duration of audio file {new_audio_path}.")
            speed_factor_pts = audio_duration / video_duration
            processed_video = input_video.video.filter('setpts', f"{speed_factor_pts}*PTS")
            
            (ffmpeg.output(processed_video, input_audio.audio, output_video_path, vcodec='libx264', acodec='aac')
             .run(capture_stdout=True, capture_stderr=True, overwrite_output=True))
            return OperationResult(message=(f"Audio track replaced and video duration stretched to match. "
                    f"Output saved to {output_video_path} with new duration of {audio_duration:.2f}s."))

    except (ffmpeg.Error, RuntimeError) as e:
        error_message = e.stderr.decode('utf8') if hasattr(e, 'stderr') and e.stderr else str(e)
        raise classify_media(f"Error replacing audio track: {error_message}", e)
    except MediaError:
        raise
    except Exception as e:
        raise classify(f"An unexpected error occurred: {str(e)}", e)

@operation(
    description=(
        "Burn subtitles from an SRT onto a video. "
        "Built-in layout: FontSize=20; WrapStyle=0 (smart wrap between CJK chars—2 disables wrapping and can clip); "
        "MarginV auto (~2% of video height, clamped 12–50); BorderStyle=1; Outline=1; BackColour=&H80000000 (semi-transparent). "
        "Auto line wrapping is always on (CJK lines capped ~34 chars based on video width and font size). "
        "Override visuals with font_style, e.g. "
        "{\"font_size\":\"22\",\"font_color\":\"&H00FFFFFF\",\"outline_color\":\"&H00000000\","
        "\"back_colour\":\"&H80000000\",\"margin_v\":\"36\",\"wrap_style\":\"0\"}. "
        "Honored keys: font_name, font_size, font_color/primary_color, outline_color, outline_width, "
        "shadow_color, shadow_offset_x/y, alignment, margin_v/l/r, wrap_style, border_style, back_colour."
    )
)
def add_subtitles(
    ctx: MediaContext,
    video_path: Annotated[str, Field(description="Absolute path to the input video; relative resolves vs server cwd")],
    srt_file_path: Annotated[str, Field(description="Absolute path to SRT file; relative resolves vs server cwd")],
    output_video_path: Annotated[str, Field(description="Absolute path for subtitled output; relative resolves vs server cwd")],
    font_style: Annotated[dict | None, Field(description="Optional ASS/ssa style overrides (see README)")] = None
) -> OperationResult:
    """Burns subtitles from an SRT file onto a video, with optional styling and automatic line wrapping."""
    video_path = ctx.paths.input(video_path)
    srt_file_path = ctx.paths.input(srt_file_path)
    output_video_path = ctx.paths.output(output_video_path)
    try:
        if not os.path.exists(video_path):
            raise MediaError.input_not_found(f"Error: Input video file not found at {video_path}")
        if not os.path.exists(srt_file_path):
            raise MediaError.input_not_found(f"Error: SRT subtitle file not found at {srt_file_path}")
        input_stream = ffmpeg.input(video_path)

        # Gather video properties early for layout heuristics
        try:
            props = get_media_properties(video_path)
            video_width = props.get('width', 1280) or 1280
            video_height = props.get('height', 720) or 720
        except Exception:
            video_width, video_height = 1280, 720

        # Sensible defaults so CJK text wraps and remains legible without callers
        # having to remember every libass flag.
        default_font_style = {
            'font_size': '20',
            'font_color': '&H00FFFFFF',
            'outline_color': '&H00000000',
            'back_colour': '&H80000000',   # semi-transparent black background
            'outline_width': '1',
            'border_style': '1',
            'alignment': '2',
            # margin_v computed dynamically below
            'wrap_style': '0',             # smart wrap to avoid clipping for long CJK lines
        }

        merged_font_style = {**default_font_style, **(font_style or {})}

        # Dynamic vertical margin: ~2% of height, clamped to [12, 50], if not provided.
        if 'margin_v' not in merged_font_style:
            dyn_margin = max(12, min(50, int(video_height * 0.02)))
            merged_font_style['margin_v'] = str(dyn_margin)

        # If caller did not supply a wrap_style, keep smart wrap to prevent clipping.
        if 'wrap_style' not in merged_font_style:
            merged_font_style['wrap_style'] = '0'

        style_args = []
        style_map = {
            'font_name': 'FontName',
            'font_size': 'FontSize',
            'font_color': 'PrimaryColour',
            'primary_color': 'PrimaryColour',
            'primary_colour': 'PrimaryColour',
            'outline_color': 'OutlineColour',
            'outline_colour': 'OutlineColour',
            'outline_width': 'Outline',
            'shadow_color': 'ShadowColour',
            'alignment': 'Alignment',
            'margin_v': 'MarginV',
            'margin_l': 'MarginL',
            'margin_r': 'MarginR',
            'wrap_style': 'WrapStyle',
            'border_style': 'BorderStyle',
            'back_color': 'BackColour',
            'back_colour': 'BackColour',
        }
        for key, value in merged_font_style.items():
            if key in style_map: style_args.append(f"{style_map[key]}={value}")
        if font_style and ('shadow_offset_x' in font_style or 'shadow_offset_y' in font_style):
            shadow_val = font_style.get('shadow_offset_x', font_style.get('shadow_offset_y', 1))
            style_args.append(f"Shadow={shadow_val}")

        # Auto-wrap raw SRT lines (useful for CJK with no spaces)
        temp_srt_path = None
        processed_srt_path = srt_file_path
        try:
            font_px = int(str(merged_font_style.get('font_size', '20')))
        except Exception:
            font_px = 20

        import re
        import textwrap
        cjk_pattern = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')

        def wrap_line(text: str) -> list[str]:
            if not text:
                return [text]
            cjk_count = len(cjk_pattern.findall(text))
            ratio = cjk_count / len(text)
            if ratio > 0.3:
                # CJK-heavy: tighter limit to avoid clipping even on wide videos
                max_chars = min(34, max(12, int(video_width / (font_px * 1.6))))
            else:
                # Non-CJK or mixed: allow longer words, but still constrain
                max_chars = max(28, int(video_width / (font_px * 0.9)))
            wrapped = textwrap.wrap(text, width=max_chars, break_long_words=True, break_on_hyphens=False)
            return wrapped or [text]

        import tempfile
        wrapped_lines = []
        with open(srt_file_path, 'r', encoding='utf-8') as f:
            block = []
            for line in f:
                if line.strip() == '':
                    wrapped_lines.extend(block)
                    wrapped_lines.append('')
                    block = []
                    continue
                if '-->' in line:
                    block.append(line.rstrip('\n'))
                    continue
                # Wrap subtitle text lines
                text = line.rstrip('\n')
                wrapped = wrap_line(text)
                block.extend(wrapped)
            wrapped_lines.extend(block)

        temp_srt = tempfile.NamedTemporaryFile(delete=False, suffix='.srt', mode='w', encoding='utf-8')
        temp_srt.write('\n'.join(wrapped_lines))
        temp_srt.close()
        temp_srt_path = temp_srt.name
        processed_srt_path = temp_srt_path

        vf_filter_value = f"subtitles='{processed_srt_path}'"
        if style_args:
            vf_filter_value += f":force_style='{','.join(style_args)}'"

        try:
            input_stream.output(output_video_path, vf=vf_filter_value, acodec='copy').run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
            return OperationResult(message=f"Subtitles added successfully (audio copied) to {output_video_path}")
        except ffmpeg.Error as e_acopy:
            try:
                input_stream.output(output_video_path, vf=vf_filter_value).run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
                return OperationResult(message=f"Subtitles added successfully (audio re-encoded) to {output_video_path}")
            except ffmpeg.Error as e_recode_all:
                raise MediaError.ffmpeg_failed(f"Error adding subtitles. Audio copy attempt: {e_acopy.stderr.decode('utf8')}. Full re-encode attempt: {e_recode_all.stderr.decode('utf8')}")
        finally:
            if temp_srt_path and os.path.exists(temp_srt_path):
                try:
                    os.remove(temp_srt_path)
                except OSError:
                    pass
    except MediaError:
        raise
    except Exception as e:
        raise classify(f"An unexpected error occurred: {str(e)}", e)

@operation()
def add_text_overlay(
    ctx: MediaContext,
    video_path: Annotated[str, Field(description="Absolute path to the input video; relative resolves vs server cwd")],
    output_video_path: Annotated[str, Field(description="Absolute path for output with text overlays; relative resolves vs server cwd")],
    text_elements: Annotated[list[dict], Field(description="List of overlay specs (text, start_time, end_time, positions, optional fontfile)")],
) -> OperationResult:
    """Adds one or more text overlays to a video at specified times and positions."""
    video_path = ctx.paths.input(video_path)
    output_video_path = ctx.paths.output(output_video_path)
    for element in text_elements:
        if 'font_file' in element:
            element['font_file'] = ctx.paths.input(element['font_file'])
    try:
        if not os.path.exists(video_path):
            raise MediaError.input_not_found(f"Error: Input video file not found at {video_path}")
        if not text_elements:
            raise MediaError.invalid_argument("Error: No text elements provided for overlay.")
        input_stream = ffmpeg.input(video_path)
        drawtext_filters = []

        for element in text_elements:
            if not all(k in element for k in ['text', 'start_time', 'end_time']):
                raise MediaError.invalid_argument(f"Error: Text element is missing required keys.")
            
            safe_text = element['text'].replace('\\', '\\\\').replace("'", "\\'").replace(':', '\\:').replace(',', '\\,')
            
            filter_params = [
                f"text='{safe_text}'", f"fontsize={element.get('font_size', 24)}",
                f"fontcolor={element.get('font_color', 'white')}", f"x={element.get('x_pos', '(w-text_w)/2')}",
                f"y={element.get('y_pos', 'h-text_h-10')}", f"enable=between(t\\,{element['start_time']}\\,{element['end_time']})"
            ]
            if element.get('box', False):
                filter_params.extend([
                    "box=1", f"boxcolor={element.get('box_color', 'black@0.5')}",
                    f"boxborderw={element.get('box_border_width', 0)}"
                ])
            if 'font_file' in element:
                font_path = element['font_file'].replace('\\', '\\\\').replace("'", "\\'").replace(':', '\\:')
                filter_params.append(f"fontfile='{font_path}'")
            
            drawtext_filters.append(f"drawtext={':'.join(filter_params)}")

        final_vf_filter = ','.join(drawtext_filters)

        try:
            input_stream.output(output_video_path, vf=final_vf_filter, acodec='copy').run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
            return OperationResult(message=f"Text overlays added successfully (audio copied) to {output_video_path}")
        except ffmpeg.Error:
            input_stream.output(output_video_path, vf=final_vf_filter).run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
            return OperationResult(message=f"Text overlays added successfully (audio re-encoded) to {output_video_path}")

    except ffmpeg.Error as e:
        raise MediaError.ffmpeg_failed(f"Error processing text overlays: {e.stderr.decode('utf8') if e.stderr else str(e)}")
    except MediaError:
        raise
    except Exception as e:
        raise classify(f"An unexpected error occurred: {str(e)}", e)

@operation()
def add_image_overlay(
    ctx: MediaContext,
    video_path: Annotated[str, Field(description="Absolute path to the input video; relative resolves vs server cwd")],
    output_video_path: Annotated[str, Field(description="Absolute path for output with overlay; relative resolves vs server cwd")],
    image_path: Annotated[str, Field(description="Absolute path to overlay image; relative resolves vs server cwd")],
    position: Annotated[str, Field(description="Overlay position: top_right, top_left, bottom_right, bottom_left, center")] = 'top_right',
    opacity: Annotated[float | None, Field(description="Optional opacity 0.0-1.0")] = None,
    start_time: Annotated[str | None, Field(description="Optional overlay start time (seconds)")]= None,
    end_time: Annotated[str | None, Field(description="Optional overlay end time (seconds)")]= None,
    width: Annotated[str | None, Field(description="Optional overlay width (e.g., '320' or '-1' to auto)")] = None,
    height: Annotated[str | None, Field(description="Optional overlay height (e.g., '180' or '-1' to auto)")] = None,
) -> OperationResult:
    """Adds an image overlay (watermark/logo) to a video."""
    video_path, output_video_path, image_path = ctx.paths.input(video_path), ctx.paths.output(output_video_path), ctx.paths.input(image_path)
    try:
        if not os.path.exists(video_path):
            raise MediaError.input_not_found(f"Error: Input video file not found at {video_path}")
        if not os.path.exists(image_path):
            raise MediaError.input_not_found(f"Error: Overlay image file not found at {image_path}")
        main_input = ffmpeg.input(video_path)
        overlay_input = ffmpeg.input(image_path)
        
        processed_overlay = overlay_input
        if width or height:
            w, h = (width or '-1'), (height or '-1')
            processed_overlay = processed_overlay.filter('scale', width=w, height=h)
        if opacity is not None and 0.0 <= opacity <= 1.0:
            processed_overlay = processed_overlay.filter('format', 'rgba').filter('colorchannelmixer', aa=str(opacity))

        pos_map = {
            'top_left': ('10', '10'), 'top_right': ('main_w-overlay_w-10', '10'),
            'bottom_left': ('10', 'main_h-overlay_h-10'), 'bottom_right': ('main_w-overlay_w-10', 'main_h-overlay_h-10'),
            'center': ('(main_w-overlay_w)/2', '(main_h-overlay_h)/2')
        }
        overlay_x_pos, overlay_y_pos = pos_map.get(position, ('0', '0'))

        overlay_kwargs = {'x': overlay_x_pos, 'y': overlay_y_pos}
        if start_time is not None or end_time is not None:
            enable_expr = f"between(t,{start_time or 0},{end_time or 'inf'})"
            overlay_kwargs['enable'] = enable_expr

        video_with_overlay = ffmpeg.filter([main_input, processed_overlay], 'overlay', **overlay_kwargs)
        try:
            ffmpeg.output(video_with_overlay, main_input.audio, output_video_path, acodec='copy').run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
            return OperationResult(message=f"Image overlay added successfully (audio copied) to {output_video_path}")
        except ffmpeg.Error:
            ffmpeg.output(video_with_overlay, main_input.audio, output_video_path).run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
            return OperationResult(message=f"Image overlay added successfully (audio re-encoded) to {output_video_path}")

    except MediaError:
        raise
    except Exception as e:
        raise classify(f"An unexpected error occurred in add_image_overlay: {str(e)}", e)

@operation(description="Create a video from a still image plus audio. Prefer absolute paths for all paths; relative paths are resolved against the server working directory.")
def create_video_from_image_and_audio(
    ctx: MediaContext,
    image_path: Annotated[str, Field(description="Absolute path to the still image; prefer absolute (relative resolves vs server cwd)")],
    audio_path: Annotated[str, Field(description="Absolute path to the audio file; prefer absolute (relative resolves vs server cwd)")],
    output_video_path: Annotated[str, Field(description="Absolute path for the output video; prefer absolute (relative resolves vs server cwd)")],
    fps: Annotated[int, Field(description="Frames per second (e.g., 24)")] = 24
) -> OperationResult:
    """Creates a video from a static image and an audio file. Prefer absolute paths for inputs/outputs; relative paths are resolved against the server working directory. Robust compatibility checks included."""
    image_path, audio_path, output_video_path = ctx.paths.input(image_path), ctx.paths.input(audio_path), ctx.paths.output(output_video_path)
    try:
        if not os.path.exists(image_path):
            raise MediaError.input_not_found(f"Error: Input image file not found at {image_path}")
        if not os.path.exists(audio_path):
            raise MediaError.input_not_found(f"Error: Input audio file not found at {audio_path}")
        duration = float(ffmpeg.probe(audio_path)['format']['duration'])
        image_input = ffmpeg.input(image_path, loop=1, framerate=fps)
        audio_input = ffmpeg.input(audio_path)
        video_stream = image_input.video.filter('pad', width='ceil(iw/2)*2', height='ceil(ih/2)*2').filter('format', pix_fmts='yuv420p')

        (ffmpeg.output(video_stream, audio_input.audio, output_video_path, vcodec='libx264', tune='stillimage',
                       acodec='aac', audio_bitrate='192k', ar=48000, ac=2, t=duration, movflags='+faststart')
         .run(capture_stdout=True, capture_stderr=True, overwrite_output=True))
        
        return OperationResult(message=f"Video created successfully from image and audio, saved to {output_video_path}")

    except ffmpeg.Error as e:
        raise MediaError.ffmpeg_failed(f"Error creating video: {e.stderr.decode('utf8') if e.stderr else str(e)}")
    except MediaError:
        raise
    except Exception as e:
        raise classify(f"An unexpected error occurred: {str(e)}", e)

@operation(description="Extract a single frame as an image. Prefer absolute paths; relative paths are resolved against the server working directory.")
def extract_frame_from_video(
    ctx: MediaContext,
    video_path: Annotated[str, Field(description="Absolute path to the input video; relative resolves vs server cwd")],
    output_image_path: Annotated[str, Field(description="Absolute path for extracted frame image; relative resolves vs server cwd")],
    frame_location: Annotated[Union[str, float], Field(description="Frame location: 'first', 'last', timestamp string, or seconds")],
    image_quality: Annotated[int, Field(description="Image quality (1=best, 31=worst)")] = 2
) -> OperationResult:
    """Extracts a single frame from a video and saves it as an image. Prefer absolute paths; relative paths are resolved against the server working directory."""
    video_path, output_image_path = ctx.paths.input(video_path), ctx.paths.output(output_image_path)
    try:
        if not os.path.exists(video_path):
            raise MediaError.input_not_found(f"Error: Input video file not found at {video_path}")
        seek_time = None
        if isinstance(frame_location, str):
            if frame_location.lower() == 'first': seek_time = 0
            elif frame_location.lower() == 'last':
                duration = get_media_properties(video_path).get('duration', 0)
                seek_time = max(0, duration - 0.1)
            else: seek_time = frame_location
        elif isinstance(frame_location, (int, float)):
            seek_time = frame_location
        else:
            raise MediaError.invalid_argument(f"Error: Invalid frame_location type.")

        (ffmpeg.input(video_path, ss=seek_time).output(output_image_path, vframes=1, **{'q:v': image_quality})
         .run(capture_stdout=True, capture_stderr=True, overwrite_output=True))
        
        return OperationResult(message=f"Frame successfully extracted from '{frame_location}' and saved to {output_image_path}")
    except (ffmpeg.Error, RuntimeError) as e:
        raise classify_media(f"Error extracting frame: {e.stderr.decode('utf8') if hasattr(e, 'stderr') and e.stderr else str(e)}", e)
    except MediaError:
        raise
    except Exception as e:
        raise classify(f"An unexpected error occurred: {str(e)}", e)

@operation(description="Insert B-roll clips into a main video. Prefer absolute paths for all paths; relative paths are resolved against the server working directory.")
def add_b_roll(
    ctx: MediaContext,
    main_video_path: Annotated[str, Field(description="Absolute path to the main video; relative resolves vs server cwd")],
    broll_clips: Annotated[list[dict], Field(description="List of B-roll clip dicts (clip_path, insert_at_timestamp, etc.)")],
    output_video_path: Annotated[str, Field(description="Absolute path for output with B-roll; relative resolves vs server cwd")]
) -> OperationResult:
    """Inserts B-roll clips into a main video as overlays. Prefer absolute paths; relative paths are resolved against the server working directory."""
    main_video_path, output_video_path = ctx.paths.input(main_video_path), ctx.paths.output(output_video_path)
    for clip in broll_clips:
        if 'clip_path' in clip: clip['clip_path'] = ctx.paths.input(clip['clip_path'])

    if not os.path.exists(main_video_path):
        raise MediaError.input_not_found(f"Error: Main video file not found at {main_video_path}")
    if not broll_clips:
        shutil.copy(main_video_path, output_video_path)
        return OperationResult(message=f"No B-roll clips provided. Main video copied to {output_video_path}")

    temp_dir = tempfile.mkdtemp()
    try:
        main_props = get_media_properties(main_video_path)
        if not main_props['has_video']:
            raise MediaError.media_unreadable(f"Error: Main video has no video stream.")
        main_input = ffmpeg.input(main_video_path)
        video_stream = main_input.video
        audio_stream = main_input.audio

        for i, broll_item in enumerate(broll_clips):
            clip_path = broll_item['clip_path']
            if not os.path.exists(clip_path):
                raise MediaError.input_not_found(f"Error: B-roll clip not found at {clip_path}")
            broll_input = ffmpeg.input(clip_path, ss=broll_item.get('start_trim', 0), t=broll_item.get('duration'))
            broll_video = broll_input.video
            
            # Simplified for brevity - full implementation would handle scale, position, transitions
            video_stream = video_stream.overlay(broll_video, enable=f"between(t,{parse_time_to_seconds(broll_item['insert_at_timestamp'])},inf)")

        ffmpeg.output(video_stream, audio_stream, output_video_path).run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
        return OperationResult(message=f"B-roll clips added successfully. Output at {output_video_path}")
    finally:
        shutil.rmtree(temp_dir)

@operation()
def add_basic_transitions(
    ctx: MediaContext,
    video_path: Annotated[str, Field(description="Absolute path to the input video; relative resolves vs server cwd")],
    output_video_path: Annotated[str, Field(description="Absolute path for output with transition; relative resolves vs server cwd")],
    transition_type: Annotated[str, Field(description="fade_in, fade_out, crossfade_from_black, crossfade_to_black")],
    duration_seconds: Annotated[float, Field(description="Transition duration in seconds")]
) -> OperationResult:
    """Adds basic fade transitions to the beginning or end of a video."""
    video_path, output_video_path = ctx.paths.input(video_path), ctx.paths.output(output_video_path)
    if not os.path.exists(video_path):
        raise MediaError.input_not_found(f"Error: Input video file not found at {video_path}")
    if duration_seconds <= 0:
        raise MediaError.invalid_argument("Error: Transition duration must be positive.")
    try:
        props = get_media_properties(video_path)
        if duration_seconds > props['duration']:
            raise MediaError.invalid_argument(f"Error: Transition duration exceeds video duration.")
        input_stream = ffmpeg.input(video_path)
        
        if transition_type in ['fade_in', 'crossfade_from_black']:
            processed_video = input_stream.video.filter('fade', type='in', start_time=0, duration=duration_seconds)
        elif transition_type in ['fade_out', 'crossfade_to_black']:
            fade_start_time = props['duration'] - duration_seconds
            processed_video = input_stream.video.filter('fade', type='out', start_time=fade_start_time, duration=duration_seconds)
        else:
            raise MediaError.invalid_argument(f"Error: Unsupported transition_type '{transition_type}'.")

        output_streams = [processed_video]
        if props['has_audio']: output_streams.append(input_stream.audio)

        try:
            ffmpeg.output(*output_streams, output_video_path, acodec='copy').run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
            return OperationResult(message=f"Transition '{transition_type}' applied (audio copied). Output: {output_video_path}")
        except ffmpeg.Error:
            ffmpeg.output(*output_streams, output_video_path).run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
            return OperationResult(message=f"Transition '{transition_type}' applied (audio re-encoded). Output: {output_video_path}")
    except MediaError:
        raise
    except Exception as e:
        raise classify(f"An unexpected error occurred in add_basic_transitions: {str(e)}", e)
