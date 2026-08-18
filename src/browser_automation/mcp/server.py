"""FastMCP composition over the authoritative BrowserApplication."""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from browser_automation.application import BrowserApplication
from browser_automation.mcp.config import McpConfigError, McpRuntimeConfig, McpServerConfig
from browser_automation.mcp.tools import register_tools

logger = logging.getLogger(__name__)


def create_server(
    server_config: McpServerConfig | None = None,
    runtime_config: McpRuntimeConfig | None = None,
    application: BrowserApplication | None = None,
) -> FastMCP:
    server_settings = server_config or McpServerConfig.from_env()
    runtime = runtime_config or McpRuntimeConfig.from_env()
    server = FastMCP(
        name=server_settings.name,
        instructions=server_settings.instructions,
        host=runtime.host,
        port=runtime.port,
    )
    register_tools(server, application or BrowserApplication())
    return server


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")
    try:
        runtime = McpRuntimeConfig.from_env()
        server_config = McpServerConfig.from_env()
    except McpConfigError as exc:
        raise SystemExit(f"Invalid browser MCP configuration: {exc}") from exc

    if runtime.requires_exposure_warning:
        logger.warning(
            "SECURITY WARNING: browser MCP is binding to non-loopback host %s without "
            "built-in authentication. Use only behind a trusted network or external protection boundary.",
            runtime.host,
        )
    create_server(server_config=server_config, runtime_config=runtime).run(transport=runtime.transport)


if __name__ == "__main__":
    main()
