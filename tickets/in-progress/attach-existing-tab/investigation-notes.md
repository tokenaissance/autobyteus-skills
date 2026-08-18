# Investigation Notes - Attach Existing Tab

## Date
- 2026-02-25

## Problem Context
- Current browser MCP tools can only act on tabs explicitly created by `open_tab` in the current MCP server process.
- In the ChatGPT debugging flow, the user often already has a live/authenticated tab open in Chrome. That tab is not represented in MCP `list_tabs`, so DOM inspection cannot be performed on the real page state.

## Sources Consulted
- `/home/ryan-ai/.codex/config.toml`
- `/home/ryan-ai/SSD/autobyteus_org_workspace/autobyteus_mcps/browser-mcp/src/browser_mcp/server.py`
- `/home/ryan-ai/SSD/autobyteus_org_workspace/autobyteus_mcps/browser-mcp/src/browser_mcp/tabs.py`
- `/home/ryan-ai/SSD/autobyteus_org_workspace/autobyteus_mcps/browser-mcp/src/browser_mcp/tools/list_tabs.py`
- `/home/ryan-ai/SSD/autobyteus_org_workspace/autobyteus_mcps/browser-mcp/src/browser_mcp/tools/open_tab.py`
- `/home/ryan-ai/SSD/autobyteus_org_workspace/autobyteus_mcps/browser-mcp/src/browser_mcp/tools/navigate_to.py`
- `/home/ryan-ai/SSD/autobyteus_org_workspace/autobyteus_mcps/browser-mcp/src/browser_mcp/tools/read_page.py`
- `/home/ryan-ai/SSD/autobyteus_org_workspace/autobyteus_rpa_llm/.venv/lib/python3.11/site-packages/brui_core/ui_integrator.py`
- `/home/ryan-ai/SSD/autobyteus_org_workspace/autobyteus_rpa_llm/.venv/lib/python3.11/site-packages/brui_core/browser/browser_manager.py`

## Key Findings
1. Browser MCP config currently points to `browser-mcp` with `CHROME_REMOTE_DEBUGGING_PORT=9223`, so tools connect over CDP to an existing Chrome debug endpoint.
2. `TabManager` stores tabs only in an in-memory map (`_tabs`) populated by `open_tab`.
3. `list_tabs` returns only `tab_manager.list_tabs()`, which is just sorted keys of `_tabs`.
4. `UIIntegrator.initialize()` always creates a new page (`context.new_page()`), even when browser context already has existing pages.
5. Therefore, existing user-opened pages in the CDP-connected browser context are not discoverable/attachable through MCP tools.
6. All stateful tools (`navigate_to`, `read_page`, `dom_snapshot`, `run_script`, `screenshot`) require MCP tab IDs from `_tabs`; no lookup path exists for existing context pages.

## Constraints
- Must preserve deterministic multi-step automation semantics for existing users of `open_tab` + `tab_id`.
- Must avoid destructive behavior on user-owned tabs (no implicit close on server shutdown unless explicitly attached as managed-with-close policy).
- Must keep API explicit enough to avoid accidental attachment to wrong tab.

## Unknowns
- Whether multiple browser contexts should be supported or only `browser.contexts[0]` (current brui_core behavior assumes index 0).
- Final attach match strategy preference: page URL exact match vs substring vs title regex vs explicit page index.
- Whether attached tabs should appear differently in `list_tabs` metadata to prevent accidental closure.

## Implications For Requirements/Design
- Add explicit `attach_tab` tool to map an existing Playwright page into `TabManager` without opening a new browser tab.
- Extend `list_tabs` output to include attachment metadata and enough context (url/title/source) for safe operator use.
- Keep close semantics consistent for all tracked tabs and preserve legacy `close_browser` option for compatibility.
- Keep `open_tab` behavior unchanged for backward stability in current workflows.
