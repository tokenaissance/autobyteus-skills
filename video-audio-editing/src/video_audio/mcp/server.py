"""Thin FastMCP adapter generated from the operation registry."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from video_audio.mcp.legacy import build_wrapper
from video_audio.operations.registry import all_operations


def create_server() -> FastMCP:
    server = FastMCP("VideoAudioServer")
    for spec in all_operations():
        server.tool(name=spec.name, description=spec.description)(build_wrapper(spec))
    return server


def main() -> None:
    create_server().run()


if __name__ == "__main__":
    main()
