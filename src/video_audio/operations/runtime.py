from video_audio.contracts import OperationResult
from video_audio.ffmpeg_runtime import find_binaries
from video_audio.operations.registry import MediaContext, operation


@operation(needs_ffmpeg=False, writes_output=False)
def health_check(ctx: MediaContext) -> OperationResult:
    """Returns a simple health status to confirm the server is running."""
    return OperationResult(
        message="Server is healthy!",
        data={**find_binaries(), "workspace": getattr(ctx.paths, "workspace", None)},
    )
