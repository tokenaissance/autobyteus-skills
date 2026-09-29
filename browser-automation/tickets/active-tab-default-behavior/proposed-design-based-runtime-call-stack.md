# Proposed-Design-Based Runtime Call Stack (`v1`)

## Coverage Summary
| use_case_id | Primary | Fallback | Error |
|---|---|---|---|
| UC-1 | Yes | N/A | N/A |
| UC-2 | Yes | N/A | Yes |
| UC-3 | Yes | N/A | Yes |
| UC-4 | Yes | N/A | Yes |
| UC-5 | Yes | N/A | Yes |

## UC-1: Open tab and continue on same tab by default
1. `src/browser_mcp/tools/open_tab.py:open_tab(...)`
2. `src/browser_mcp/tabs.py:TabManager.open_tab()`
3. `src/browser_mcp/tabs.py:prepare_integrator(keep_alive=True)` `await`
4. `brui_core/ui_integrator.py:UIIntegrator.initialize()` `await`
5. `brui_core/ui_integrator.py:UIIntegrator.start_keep_alive()` `await`
6. `src/browser_mcp/tabs.py:TabManager._tabs[tab_id]=BrowserTab` (state mutation)
7. `src/browser_mcp/tabs.py:TabManager._active_tab_id=tab_id` (state mutation)
8. Return `OpenTabResult(tab_id,url)` to caller.

## UC-2: Explicit `tab_id` override
1. `src/browser_mcp/tools/read_page.py:read_page(...)` (representative page tool)
2. `src/browser_mcp/tabs.py:resolve_tab(tab_id=<provided>, url, require_url)`
3. `src/browser_mcp/tabs.py:TabManager.get_tab_or_raise(tab_id)` -> existing tab
4. `src/browser_mcp/tabs.py:TabManager.set_active_tab(tab_id)` (state mutation)
5. `read_page` performs operation on resolved page.
6. Return result with `tab_id=<provided>`.

Error branch:
1. `get_tab_or_raise` misses tab -> raise `ValueError("Unknown tab_id: ...")`.

## UC-3: Omitted `tab_id` uses active tab
1. `src/browser_mcp/tools/dom_snapshot.py:dom_snapshot(...)` (representative page tool)
2. `src/browser_mcp/tabs.py:resolve_tab(tab_id=None, url=None, require_url=False)`
3. `src/browser_mcp/tabs.py:TabManager.get_active_tab()` -> returns active persistent tab.
4. Tool executes page operation directly.
5. Return structured payload with `tab_id=<active_tab_id>`.

Error branch:
1. Active tab missing and URL missing when operation requires prior navigation context.
2. Tool raises `ValueError("No URL provided and no active tab context")` or equivalent context error.

## UC-4: No active tab + URL provided uses ephemeral path
1. `src/browser_mcp/tools/screenshot.py:screenshot(url=...)`
2. `src/browser_mcp/tabs.py:resolve_tab(tab_id=None, url=<provided>, require_url=True)`
3. `resolve_tab` sees no active tab -> `create_ephemeral_tab()` `await`
4. Tool navigates page (`page.goto`) and runs operation.
5. `finally`: `integrator.close()` for ephemeral tab (`await`)
6. Return result with `tab_id=null`.

Error branch:
1. `require_url=True` and url missing -> immediate `ValueError`.

## UC-5: Close tab defaults to active tab
1. `src/browser_mcp/tools/close_tab.py:close_tab(tab_id=None)`
2. `src/browser_mcp/tabs.py:TabManager.close_tab(tab_id=None, close_browser=...)`
3. Manager resolves target as current `_active_tab_id`.
4. Remove tab from `_tabs` (state mutation), close integrator page (`await`).
5. Manager updates `_active_tab_id` to most-recent remaining tab or `None` (state mutation).
6. Return `CloseTabResult(tab_id=<closed-or-null>, closed=<bool>)`.

Error branch:
1. No active tab and no tab_id -> return `(None, False)` without exception.
2. Unknown explicit tab_id -> return `(tab_id, False)` without exception.
