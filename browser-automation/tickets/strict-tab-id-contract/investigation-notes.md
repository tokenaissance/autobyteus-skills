# Investigation Notes

## Scope
Tighten browser MCP tool API to remove implicit active-tab and ephemeral behavior that causes nondeterministic agent behavior in parallel workflows.

## Sources Consulted
- `src/browser_mcp/tabs.py`
- `src/browser_mcp/tools/*.py`
- `tests/test_server.py`
- `tests/test_integration_real.py`
- `README.md`

## Key Findings
- Existing resolver (`resolve_tab`) chooses `tab_id` -> active tab -> ephemeral tab, which permits ambiguous target selection when callers omit `tab_id`.
- Multiple tools accepted `url` without `tab_id`, mixing navigation and stateful operations into one call path.
- Real agent behavior shows parallel tab workflows where omitted `tab_id` can create cross-tab confusion.

## Constraints
- No backward compatibility.
- Keep canonical tool set (`open_tab`, `close_tab`, `list_tabs`, `navigate_to`, `read_page`, `screenshot`, `dom_snapshot`, `run_script`).
- Integration tests must pass against real Chrome debug endpoint.

## Outcome
Adopt strict explicit-tab contract for all stateful tools; remove fallback resolver paths.
