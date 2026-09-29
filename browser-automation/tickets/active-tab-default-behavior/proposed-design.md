# Proposed Design - Active Tab Default Behavior (`v1`)

## Current-State Summary (As-Is)
- Persistent tabs exist only when `open_tab` is called or when tools run with `keep_tab=true`.
- Most tools resolve execution through `resolve_tab(tab_id, keep_tab, url, require_url)`.
- Without `tab_id`, tools default to ephemeral tab behavior and close the page after execution.
- `close_tab` requires explicit `tab_id`.

## Target-State Summary (To-Be)
- Introduce first-class active-tab state in `TabManager`.
- Remove `keep_tab` from all tool APIs and tab resolution logic.
- Default behavior:
  - if `tab_id` provided: use that tab and mark it active,
  - else if active tab exists: use active tab,
  - else if `url` provided: use ephemeral tab for one-off operation,
  - else: raise clear missing-context error.
- `open_tab(url?)` opens persistent tab, optionally navigates immediately, sets active tab.
- `close_tab(tab_id?)` closes specified tab or current active tab.

## Change Inventory
| Type | File | Change |
|---|---|---|
| Modify | `src/browser_mcp/tabs.py` | Replace `keep_tab` path with active-tab state + resolver logic. |
| Modify | `src/browser_mcp/types.py` | Add `active_tab_id` to `ListTabsResult`; add `url` to `OpenTabResult`; allow optional `tab_id` in close result flow. |
| Modify | `src/browser_mcp/tools/open_tab.py` | Add optional `url`, wait args; navigate on open when provided; return tab metadata. |
| Modify | `src/browser_mcp/tools/close_tab.py` | Make `tab_id` optional; close active tab by default. |
| Modify | `src/browser_mcp/tools/navigate_to.py` | Remove `keep_tab`; use active-tab resolver. |
| Modify | `src/browser_mcp/tools/read_page.py` | Remove `keep_tab`; use active-tab resolver. |
| Modify | `src/browser_mcp/tools/screenshot.py` | Remove `keep_tab`; use active-tab resolver. |
| Modify | `src/browser_mcp/tools/dom_snapshot.py` | Remove `keep_tab`; use active-tab resolver. |
| Modify | `src/browser_mcp/tools/run_script.py` | Remove `keep_tab`; use active-tab resolver. |
| Modify | `tests/test_server.py` | Update tool API usage and active-tab behavior assertions. |
| Modify | `tests/test_integration_real.py` | Update integration coverage for active-tab default path. |
| Modify | `README.md` | Update tool contracts and usage examples. |
| Remove | API parameter `keep_tab` | Remove from all tools, tests, docs (no backward compatibility). |

## Module Responsibilities and APIs
### `src/browser_mcp/tabs.py`
- Responsibility: lifecycle/state for persistent tabs + active-tab pointer + ephemeral helper.
- Key APIs:
  - `open_tab() -> BrowserTab` (persistent, updates active pointer),
  - `close_tab(tab_id: str | None, close_browser: bool = False) -> tuple[str | None, bool]`,
  - `list_tabs() -> list[str]`,
  - `active_tab_id() -> str | None`,
  - `resolve_tab(tab_id, url, require_url) -> (BrowserTab, ephemeral, resolved_tab_id)`.

### `src/browser_mcp/tools/*.py`
- Responsibility: map MCP tool parameters to tab resolution + page operations.
- Key API decisions:
  - page tools no longer expose `keep_tab`,
  - `open_tab` becomes stateful opener with optional initial navigation,
  - `close_tab` defaults to active tab for human-like behavior.

## Naming Decisions
- Keep `open_tab`, `close_tab`, `list_tabs` names; they are natural and explicit.
- Keep `dom_snapshot` for structured element payload; distinct from `screenshot` bitmap output.
- Remove naming tied to old behavior: `keep_tab` removed because lifecycle is now implicit through active tab.

## Naming Drift Check
- `TabManager`: still accurate, now includes active-tab index; no rename needed.
- `resolve_tab`: remains accurate; now resolves active-first semantics; no rename needed.
- Tool names align with behavior after removing legacy parameter drift.

## Dependency Flow
- `tools/* -> tabs.py -> UIIntegrator(Page)` remains unchanged.
- No new cross-module cycles introduced.
- Locking remains centralized in `TabManager`.

## Cleanup / Decommission
- Remove `keep_tab` from all tool signatures and resolver interfaces.
- Remove any code branches exclusively supporting `keep_tab`.
- Remove test cases asserting old `keep_tab` behavior.

## Error Handling Expectations
- If no `tab_id`, no active tab, and no `url` when URL is required, return explicit `ValueError`.
- If `tab_id` is unknown, return explicit `ValueError`.
- If closing without any active/persistent tab, return `closed=false` and `tab_id=null`.

## Use-Case Coverage Matrix
| use_case_id | Description | Primary | Fallback | Error | Runtime Sections |
|---|---|---|---|---|---|
| UC-1 | Open tab and continue on same tab by default | Yes | N/A | N/A | `UC-1` |
| UC-2 | Tool call with explicit `tab_id` override | Yes | N/A | Yes | `UC-2` |
| UC-3 | Tool call without `tab_id` resolves active tab | Yes | N/A | Yes | `UC-3` |
| UC-4 | No active tab + provided `url` executes ephemeral path | Yes | N/A | Yes | `UC-4` |
| UC-5 | Close tab defaults to active tab | Yes | N/A | Yes | `UC-5` |
