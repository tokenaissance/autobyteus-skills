"""Legacy-call adapters: each former MCP tool as a plain callable returning the legacy result.

Media tests exercise the real operations through the same wrapper the MCP server
registers, so string assertions verify the compatibility contract end to end.
"""

from video_audio.ffmpeg_runtime import parse_time_to_seconds as _parse_time_to_seconds  # noqa: F401
from video_audio.mcp.legacy import build_wrapper
from video_audio.operations.registry import all_operations

globals().update({spec.name: build_wrapper(spec) for spec in all_operations()})
