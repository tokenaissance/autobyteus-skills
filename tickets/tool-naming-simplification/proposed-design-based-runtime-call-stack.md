# Proposed-Design-Based Runtime Call Stack

Version: v1
Basis: `implementation-plan.md` draft solution sketch (Small scope)

## Use Case UC-1: Read page using canonical tool
Coverage: Primary Yes, Fallback N/A, Error Yes

1. MCP request `read_page` arrives
2. `src/browser_mcp/tools/read_page.py:read_page(...)`
3. `src/browser_mcp/tools/read_page.py:_read_page(...)`
4. `src/browser_mcp/sessions.py:resolve_session(...)`
5. `page.goto(...)` when URL provided
6. `page.content()`
7. `src/browser_mcp/cleaning.py:clean_html(...)`
8. return `ReadWebpageResult`

Error branch:
- invalid URL -> `ValueError`
- missing page/session -> `RuntimeError`/`ValueError`

## Use Case UC-2: Screenshot using canonical tool
Coverage: Primary Yes, Fallback N/A, Error Yes

1. MCP request `screenshot` arrives
2. `src/browser_mcp/tools/screenshot.py:screenshot(...)`
3. `src/browser_mcp/tools/screenshot.py:_screenshot(...)`
4. `src/browser_mcp/sessions.py:resolve_session(...)`
5. `src/browser_mcp/utils.py:resolve_output_path(...)`
6. `page.goto(...)` when URL provided
7. `page.screenshot(...)`
8. return `ScreenshotResult`

Error branch:
- invalid URL -> `ValueError`
- file/path or page errors -> propagated tool error

## Use Case UC-3: DOM snapshot using canonical tool
Coverage: Primary Yes, Fallback N/A, Error Yes

1. MCP request `dom_snapshot` arrives
2. `src/browser_mcp/tools/dom_snapshot.py:dom_snapshot(...)`
3. `src/browser_mcp/tools/dom_snapshot.py:_dom_snapshot(...)`
4. `src/browser_mcp/sessions.py:resolve_session(...)`
5. `page.goto(...)` when URL provided
6. `page.evaluate(_DOM_SNAPSHOT_SCRIPT, ...)`
7. normalize payload into `DomSnapshotResult`
8. return structured elements

Error branch:
- invalid `max_elements` -> `ValueError`
- invalid URL or missing session state -> `ValueError`
