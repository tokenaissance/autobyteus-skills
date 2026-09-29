import ffmpeg
import os
from typing import Annotated

from pydantic import Field

from video_audio.contracts import OperationResult
from video_audio.errors import MediaError, classify
from video_audio.ffmpeg_runtime import run_with_fallback
from video_audio.operations.registry import MediaContext, operation

@operation(writes_output=False)
def get_media_duration(
    ctx: MediaContext,
    media_path: Annotated[str, Field(description="Absolute path to input media; relative resolves vs server cwd")]
) -> OperationResult:
    """Gets the duration of a video or audio file in seconds.

    Args:
        media_path: The path to the input media file.
    
    Returns:
        The duration in seconds as a float on success, or an error string on failure.
    """
    media_path = ctx.paths.input(media_path)
    try:
        if not os.path.exists(media_path):
            raise MediaError.input_not_found(f"Error: Input media file not found at {media_path}")
        
        probe = ffmpeg.probe(media_path)
        duration = float(probe['format']['duration'])
        return OperationResult(message=str(duration), data={'duration_seconds': duration}, legacy_value=duration)
    except ffmpeg.Error as e:
        error_message = e.stderr.decode('utf8') if e.stderr else str(e)
        raise MediaError.media_unreadable(f"Error probing media file: {error_message}")
    except (KeyError, ValueError) as e:
        raise MediaError.media_unreadable(f"Error parsing duration from media file metadata: {str(e)}")
    except MediaError:
        raise
    except Exception as e:
        raise classify(f"An unexpected error occurred: {str(e)}", e)

@operation()
def convert_audio_properties(
    ctx: MediaContext,
    input_audio_path: Annotated[str, Field(description="Absolute path to source audio; relative resolves vs server cwd")],
    output_audio_path: Annotated[str, Field(description="Absolute path for converted audio; relative resolves vs server cwd")],
    target_format: Annotated[str, Field(description="Target audio format, e.g., mp3, wav, aac")],
    bitrate: Annotated[str | None, Field(description="Target audio bitrate (e.g., '128k')")] = None,
    sample_rate: Annotated[int | None, Field(description="Target sample rate in Hz")] = None,
    channels: Annotated[int | None, Field(description="Number of channels (1=mono,2=stereo)")] = None
) -> OperationResult:
    """Converts audio file format and ALL specified properties like bitrate, sample rate, and channels.

    Args:
        input_audio_path: Path to the source audio file.
        output_audio_path: Path to save the converted audio file.
        target_format: Desired output audio format (e.g., 'mp3', 'wav', 'aac').
        bitrate: Target audio bitrate (e.g., '128k', '192k'). Optional.
        sample_rate: Target audio sample rate in Hz (e.g., 44100, 48000). Optional.
        channels: Number of audio channels (1 for mono, 2 for stereo). Optional.
    Returns:
        A status message indicating success or failure.
    """
    input_audio_path = ctx.paths.input(input_audio_path)
    output_audio_path = ctx.paths.output(output_audio_path)
    try:
        stream = ffmpeg.input(input_audio_path)
        kwargs = {}
        if bitrate: 
            kwargs['audio_bitrate'] = bitrate
        if sample_rate: 
            kwargs['ar'] = sample_rate
        if channels: 
            kwargs['ac'] = channels
        kwargs['format'] = target_format

        output_stream = stream.output(output_audio_path, **kwargs)
        output_stream.run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
        return OperationResult(message=f"Audio converted successfully to {output_audio_path} with format {target_format} and specified properties.")
    except ffmpeg.Error as e:
        error_message = e.stderr.decode('utf8') if e.stderr else str(e)
        raise MediaError.ffmpeg_failed(f"Error converting audio properties: {error_message}")
    except FileNotFoundError:
        raise MediaError.input_not_found(f"Error: Input audio file not found at {input_audio_path}")
    except MediaError:
        raise
    except Exception as e:
        raise classify(f"An unexpected error occurred: {str(e)}", e)

@operation()
def convert_video_properties(
    ctx: MediaContext,
    input_video_path: Annotated[str, Field(description="Absolute path to source video; relative resolves vs server cwd")],
    output_video_path: Annotated[str, Field(description="Absolute path for converted video; relative resolves vs server cwd")],
    target_format: Annotated[str, Field(description="Target container/format, e.g., mp4, mov, mkv")],
    resolution: Annotated[str | None, Field(description="Target resolution, e.g., 1920x1080 or 720; 'preserve' to keep")] = None,
    video_codec: Annotated[str | None, Field(description="Video codec, e.g., libx264, hevc, vp9")] = None,
    video_bitrate: Annotated[str | None, Field(description="Video bitrate, e.g., '4M'")] = None,
    frame_rate: Annotated[int | None, Field(description="Frame rate, e.g., 30")] = None,
    audio_codec: Annotated[str | None, Field(description="Audio codec, e.g., aac, opus")] = None,
    audio_bitrate: Annotated[str | None, Field(description="Audio bitrate, e.g., '192k'")] = None,
    audio_sample_rate: Annotated[int | None, Field(description="Audio sample rate, e.g., 48000")] = None,
    audio_channels: Annotated[int | None, Field(description="Audio channels, 1=mono, 2=stereo")] = None
) -> OperationResult:
    """Converts video file format and ALL specified properties like resolution, codecs, bitrates, and frame rate.
    Args listed in PRD.
    Returns:
        A status message indicating success or failure.
    """
    input_video_path = ctx.paths.input(input_video_path)
    output_video_path = ctx.paths.output(output_video_path)
    try:
        stream = ffmpeg.input(input_video_path)
        kwargs = {}
        vf_filters = []

        if resolution and resolution.lower() != 'preserve':
            if 'x' in resolution: 
                vf_filters.append(f"scale={resolution}")
            else: 
                vf_filters.append(f"scale=-2:{resolution}")
        
        if vf_filters:
            kwargs['vf'] = ",".join(vf_filters)

        if video_codec: kwargs['vcodec'] = video_codec
        if video_bitrate: kwargs['video_bitrate'] = video_bitrate
        if frame_rate: kwargs['r'] = frame_rate
        if audio_codec: kwargs['acodec'] = audio_codec
        if audio_bitrate: kwargs['audio_bitrate'] = audio_bitrate
        if audio_sample_rate: kwargs['ar'] = audio_sample_rate
        if audio_channels: kwargs['ac'] = audio_channels
        kwargs['format'] = target_format

        output_stream = stream.output(output_video_path, **kwargs)
        output_stream.run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
        return OperationResult(message=f"Video converted successfully to {output_video_path} with format {target_format} and specified properties.")
    except ffmpeg.Error as e:
        error_message = e.stderr.decode('utf8') if e.stderr else str(e)
        raise MediaError.ffmpeg_failed(f"Error converting video properties: {error_message}")
    except FileNotFoundError:
        raise MediaError.input_not_found(f"Error: Input video file not found at {input_video_path}")
    except MediaError:
        raise
    except Exception as e:
        raise classify(f"An unexpected error occurred: {str(e)}", e)

@operation()
def change_aspect_ratio(
    ctx: MediaContext,
    video_path: Annotated[str, Field(description="Absolute path to source video; relative resolves vs server cwd")],
    output_video_path: Annotated[str, Field(description="Absolute path for aspect-adjusted video; relative resolves vs server cwd")],
    target_aspect_ratio: Annotated[str, Field(description="Target aspect ratio like '16:9'")] ,
    resize_mode: Annotated[str, Field(description="pad (default) or crop")] = 'pad',
    padding_color: Annotated[str, Field(description="Pad color when using pad mode, e.g., black")] = 'black'
) -> OperationResult:
    """Changes the aspect ratio of a video, using padding or cropping.
    Args listed in PRD.
    Returns:
        A status message indicating success or failure.
    """
    video_path = ctx.paths.input(video_path)
    output_video_path = ctx.paths.output(output_video_path)
    try:
        probe = ffmpeg.probe(video_path)
        video_stream_info = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
        if not video_stream_info:
            raise MediaError.media_unreadable("Error: No video stream found in the input file.")

        original_width = int(video_stream_info['width'])
        original_height = int(video_stream_info['height'])

        num, den = map(int, target_aspect_ratio.split(':'))
        target_ar_val = num / den
        original_ar_val = original_width / original_height

        vf_filter = ""
        
        if resize_mode == 'pad':
            if abs(original_ar_val - target_ar_val) < 1e-4:
                try:
                    ffmpeg.input(video_path).output(output_video_path, c='copy').run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
                    return OperationResult(message=f"Video aspect ratio already matches. Copied to {output_video_path}.")
                except ffmpeg.Error:
                    ffmpeg.input(video_path).output(output_video_path).run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
                    return OperationResult(message=f"Video aspect ratio already matches. Re-encoded to {output_video_path}.")
            
            if original_ar_val > target_ar_val: 
                final_w = int(original_height * target_ar_val)
                final_h = original_height
                vf_filter = f"scale={final_w}:{final_h}:force_original_aspect_ratio=decrease,pad={final_w}:{final_h}:(ow-iw)/2:(oh-ih)/2:{padding_color}"
            else: 
                final_w = original_width
                final_h = int(original_width / target_ar_val)
                vf_filter = f"scale={final_w}:{final_h}:force_original_aspect_ratio=decrease,pad={final_w}:{final_h}:(ow-iw)/2:(oh-ih)/2:{padding_color}"

        elif resize_mode == 'crop':
            if abs(original_ar_val - target_ar_val) < 1e-4:
                try:
                    ffmpeg.input(video_path).output(output_video_path, c='copy').run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
                    return OperationResult(message=f"Video aspect ratio already matches. Copied to {output_video_path}.")
                except ffmpeg.Error:
                    ffmpeg.input(video_path).output(output_video_path).run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
                    return OperationResult(message=f"Video aspect ratio already matches. Re-encoded to {output_video_path}.")
            
            if original_ar_val > target_ar_val: 
                new_width = int(original_height * target_ar_val)
                vf_filter = f"crop={new_width}:{original_height}:(iw-{new_width})/2:0"
            else: 
                new_height = int(original_width / target_ar_val)
                vf_filter = f"crop={original_width}:{new_height}:0:(ih-{new_height})/2"
        else:
            raise MediaError.invalid_argument(f"Error: Invalid resize_mode '{resize_mode}'. Must be 'pad' or 'crop'.")
        
        try:
            ffmpeg.input(video_path).output(output_video_path, vf=vf_filter, acodec='copy').run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
            return OperationResult(message=f"Video aspect ratio changed (audio copy) to {target_aspect_ratio} using {resize_mode}. Saved to {output_video_path}")
        except ffmpeg.Error as e_acopy:
            try:
                ffmpeg.input(video_path).output(output_video_path, vf=vf_filter).run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
                return OperationResult(message=f"Video aspect ratio changed (audio re-encoded) to {target_aspect_ratio} using {resize_mode}. Saved to {output_video_path}")
            except ffmpeg.Error as e_recode_all:
                err_acopy_msg = e_acopy.stderr.decode('utf8') if e_acopy.stderr else str(e_acopy)
                err_recode_msg = e_recode_all.stderr.decode('utf8') if e_recode_all.stderr else str(e_recode_all)
                raise MediaError.ffmpeg_failed(f"Error changing aspect ratio. Audio copy attempt failed: {err_acopy_msg}. Full re-encode attempt also failed: {err_recode_msg}.")

    except ffmpeg.Error as e:
        error_message = e.stderr.decode('utf8') if e.stderr else str(e)
        raise MediaError.ffmpeg_failed(f"Error changing aspect ratio: {error_message}")
    except FileNotFoundError:
        raise MediaError.input_not_found(f"Error: Input video file not found at {video_path}")
    except ValueError:
        raise MediaError.invalid_argument(f"Error: Invalid target_aspect_ratio format. Expected 'num:den' (e.g., '16:9').")
    except MediaError:
        raise
    except Exception as e:
        raise classify(f"An unexpected error occurred: {str(e)}", e)

@operation()
def convert_audio_format(
    ctx: MediaContext,
    input_audio_path: Annotated[str, Field(description="Absolute path to source audio; relative resolves vs server cwd")],
    output_audio_path: Annotated[str, Field(description="Absolute path for converted audio; relative resolves vs server cwd")],
    target_format: Annotated[str, Field(description="Target format, e.g., mp3, wav, aac")]
) -> OperationResult:
    """Converts an audio file to the specified target format."""
    input_audio_path = ctx.paths.input(input_audio_path)
    output_audio_path = ctx.paths.output(output_audio_path)
    try:
        ffmpeg.input(input_audio_path).output(output_audio_path, format=target_format).run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
        return OperationResult(message=f"Audio format converted to {target_format} and saved to {output_audio_path}")
    except ffmpeg.Error as e:
        error_message = e.stderr.decode('utf8') if e.stderr else str(e)
        raise MediaError.ffmpeg_failed(f"Error converting audio format: {error_message}")
    except FileNotFoundError:
        raise MediaError.input_not_found(f"Error: Input audio file not found at {input_audio_path}")
    except MediaError:
        raise
    except Exception as e:
        raise classify(f"An unexpected error occurred: {str(e)}", e)

@operation()
def set_audio_bitrate(
    ctx: MediaContext,
    input_audio_path: Annotated[str, Field(description="Absolute path to source audio; relative resolves vs server cwd")],
    output_audio_path: Annotated[str, Field(description="Absolute path for output audio; relative resolves vs server cwd")],
    bitrate: Annotated[str, Field(description="Target audio bitrate, e.g., '192k'")]
) -> OperationResult:
    """Sets the bitrate for an audio file."""
    input_audio_path = ctx.paths.input(input_audio_path)
    output_audio_path = ctx.paths.output(output_audio_path)
    try:
        ffmpeg.input(input_audio_path).output(output_audio_path, audio_bitrate=bitrate).run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
        return OperationResult(message=f"Audio bitrate set to {bitrate} and saved to {output_audio_path}")
    except ffmpeg.Error as e:
        error_message = e.stderr.decode('utf8') if e.stderr else str(e)
        raise MediaError.ffmpeg_failed(f"Error setting audio bitrate: {error_message}")
    except FileNotFoundError:
        raise MediaError.input_not_found(f"Error: Input audio file not found at {input_audio_path}")
    except MediaError:
        raise
    except Exception as e:
        raise classify(f"An unexpected error occurred: {str(e)}", e)

@operation()
def set_audio_sample_rate(
    ctx: MediaContext,
    input_audio_path: Annotated[str, Field(description="Absolute path to source audio; relative resolves vs server cwd")],
    output_audio_path: Annotated[str, Field(description="Absolute path for output audio; relative resolves vs server cwd")],
    sample_rate: Annotated[int, Field(description="Target sample rate in Hz, e.g., 48000")]
) -> OperationResult:
    """Sets the sample rate for an audio file."""
    input_audio_path = ctx.paths.input(input_audio_path)
    output_audio_path = ctx.paths.output(output_audio_path)
    try:
        ffmpeg.input(input_audio_path).output(output_audio_path, ar=sample_rate).run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
        return OperationResult(message=f"Audio sample rate set to {sample_rate} Hz and saved to {output_audio_path}")
    except ffmpeg.Error as e:
        error_message = e.stderr.decode('utf8') if e.stderr else str(e)
        raise MediaError.ffmpeg_failed(f"Error setting audio sample rate: {error_message}")
    except FileNotFoundError:
        raise MediaError.input_not_found(f"Error: Input audio file not found at {input_audio_path}")
    except MediaError:
        raise
    except Exception as e:
        raise classify(f"An unexpected error occurred: {str(e)}", e)

@operation()
def set_audio_channels(
    ctx: MediaContext,
    input_audio_path: Annotated[str, Field(description="Absolute path to source audio; relative resolves vs server cwd")],
    output_audio_path: Annotated[str, Field(description="Absolute path for output audio; relative resolves vs server cwd")],
    channels: Annotated[int, Field(description="Number of channels, 1=mono, 2=stereo")]
) -> OperationResult:
    """Sets the number of channels for an audio file (1 for mono, 2 for stereo)."""
    input_audio_path = ctx.paths.input(input_audio_path)
    output_audio_path = ctx.paths.output(output_audio_path)
    try:
        ffmpeg.input(input_audio_path).output(output_audio_path, ac=channels).run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
        return OperationResult(message=f"Audio channels set to {channels} and saved to {output_audio_path}")
    except ffmpeg.Error as e:
        error_message = e.stderr.decode('utf8') if e.stderr else str(e)
        raise MediaError.ffmpeg_failed(f"Error setting audio channels: {error_message}")
    except FileNotFoundError:
        raise MediaError.input_not_found(f"Error: Input audio file not found at {input_audio_path}")
    except MediaError:
        raise
    except Exception as e:
        raise classify(f"An unexpected error occurred: {str(e)}", e)

@operation()
def convert_video_format(
    ctx: MediaContext,
    input_video_path: Annotated[str, Field(description="Absolute path to source video; relative resolves vs server cwd")],
    output_video_path: Annotated[str, Field(description="Absolute path for converted video; relative resolves vs server cwd")],
    target_format: Annotated[str, Field(description="Target format/container, e.g., mp4, mov, mkv")]
) -> OperationResult:
    """Converts a video file to the specified target format, attempting to copy codecs first."""
    primary_kwargs = {'format': target_format, 'vcodec': 'copy', 'acodec': 'copy'}
    fallback_kwargs = {'format': target_format}
    return run_with_fallback(ctx, input_video_path, output_video_path, primary_kwargs, fallback_kwargs)

@operation()
def set_video_resolution(
    ctx: MediaContext,
    input_video_path: Annotated[str, Field(description="Absolute path to source video; relative resolves vs server cwd")],
    output_video_path: Annotated[str, Field(description="Absolute path for output video; relative resolves vs server cwd")],
    resolution: Annotated[str, Field(description="Target resolution, e.g., 1920x1080 or 720")]
) -> OperationResult:
    """Sets the resolution of a video, attempting to copy the audio stream."""
    vf_filters = []
    if 'x' in resolution:
        vf_filters.append(f"scale={resolution}")
    else:
        vf_filters.append(f"scale=-2:{resolution}")
    vf_filter_str = ",".join(vf_filters)
    
    primary_kwargs = {'vf': vf_filter_str, 'acodec': 'copy'}
    fallback_kwargs = {'vf': vf_filter_str}
    return run_with_fallback(ctx, input_video_path, output_video_path, primary_kwargs, fallback_kwargs)

@operation()
def set_video_codec(
    ctx: MediaContext,
    input_video_path: Annotated[str, Field(description="Absolute path to source video; relative resolves vs server cwd")],
    output_video_path: Annotated[str, Field(description="Absolute path for output video; relative resolves vs server cwd")],
    video_codec: Annotated[str, Field(description="Video codec, e.g., libx264, hevc, vp9")]
) -> OperationResult:
    """Sets the video codec of a video, attempting to copy the audio stream."""
    primary_kwargs = {'vcodec': video_codec, 'acodec': 'copy'}
    fallback_kwargs = {'vcodec': video_codec}
    return run_with_fallback(ctx, input_video_path, output_video_path, primary_kwargs, fallback_kwargs)

@operation()
def set_video_bitrate(
    ctx: MediaContext,
    input_video_path: Annotated[str, Field(description="Absolute path to source video; relative resolves vs server cwd")],
    output_video_path: Annotated[str, Field(description="Absolute path for output video; relative resolves vs server cwd")],
    video_bitrate: Annotated[str, Field(description="Target video bitrate, e.g., '4M'")]
) -> OperationResult:
    """Sets the video bitrate of a video, attempting to copy the audio stream."""
    primary_kwargs = {'video_bitrate': video_bitrate, 'acodec': 'copy'}
    fallback_kwargs = {'video_bitrate': video_bitrate}
    return run_with_fallback(ctx, input_video_path, output_video_path, primary_kwargs, fallback_kwargs)

@operation()
def set_video_frame_rate(
    ctx: MediaContext,
    input_video_path: Annotated[str, Field(description="Absolute path to source video; relative resolves vs server cwd")],
    output_video_path: Annotated[str, Field(description="Absolute path for output video; relative resolves vs server cwd")],
    frame_rate: Annotated[int, Field(description="Target frame rate, e.g., 24, 30, 60")]
) -> OperationResult:
    """Sets the frame rate of a video, attempting to copy the audio stream."""
    primary_kwargs = {'r': frame_rate, 'acodec': 'copy'}
    fallback_kwargs = {'r': frame_rate}
    return run_with_fallback(ctx, input_video_path, output_video_path, primary_kwargs, fallback_kwargs)

@operation()
def set_video_audio_track_codec(
    ctx: MediaContext,
    input_video_path: Annotated[str, Field(description="Absolute path to source video; relative resolves vs server cwd")],
    output_video_path: Annotated[str, Field(description="Absolute path for output video; relative resolves vs server cwd")],
    audio_codec: Annotated[str, Field(description="Audio codec, e.g., aac, opus, ac3")]
) -> OperationResult:
    """Sets the audio codec of a video's audio track, attempting to copy the video stream."""
    primary_kwargs = {'acodec': audio_codec, 'vcodec': 'copy'}
    fallback_kwargs = {'acodec': audio_codec}
    return run_with_fallback(ctx, input_video_path, output_video_path, primary_kwargs, fallback_kwargs)

@operation()
def set_video_audio_track_bitrate(
    ctx: MediaContext,
    input_video_path: Annotated[str, Field(description="Absolute path to source video; relative resolves vs server cwd")],
    output_video_path: Annotated[str, Field(description="Absolute path for output video; relative resolves vs server cwd")],
    audio_bitrate: Annotated[str, Field(description="Target audio bitrate, e.g., '160k'")]
) -> OperationResult:
    """Sets the audio bitrate of a video's audio track, attempting to copy the video stream."""
    primary_kwargs = {'audio_bitrate': audio_bitrate, 'vcodec': 'copy'}
    fallback_kwargs = {'audio_bitrate': audio_bitrate}
    return run_with_fallback(ctx, input_video_path, output_video_path, primary_kwargs, fallback_kwargs)

@operation()
def set_video_audio_track_sample_rate(
    ctx: MediaContext,
    input_video_path: Annotated[str, Field(description="Absolute path to source video; relative resolves vs server cwd")],
    output_video_path: Annotated[str, Field(description="Absolute path for output video; relative resolves vs server cwd")],
    audio_sample_rate: Annotated[int, Field(description="Target audio sample rate in Hz, e.g., 48000")]
) -> OperationResult:
    """Sets the audio sample rate of a video's audio track, attempting to copy the video stream."""
    primary_kwargs = {'ar': audio_sample_rate, 'vcodec': 'copy'}
    fallback_kwargs = {'ar': audio_sample_rate}
    return run_with_fallback(ctx, input_video_path, output_video_path, primary_kwargs, fallback_kwargs)

@operation()
def set_video_audio_track_channels(
    ctx: MediaContext,
    input_video_path: Annotated[str, Field(description="Absolute path to source video; relative resolves vs server cwd")],
    output_video_path: Annotated[str, Field(description="Absolute path for output video; relative resolves vs server cwd")],
    audio_channels: Annotated[int, Field(description="Audio channels, 1=mono, 2=stereo")]
) -> OperationResult:
    """Sets the number of audio channels of a video's audio track, attempting to copy the video stream."""
    primary_kwargs = {'ac': audio_channels, 'vcodec': 'copy'}
    fallback_kwargs = {'ac': audio_channels}
    return run_with_fallback(ctx, input_video_path, output_video_path, primary_kwargs, fallback_kwargs)
