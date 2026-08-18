# Requirements - Active Tab Default Behavior

## Version History
- `v0`: Initial capture from user discussion.
- `v1`: Design-ready refinement after codebase understanding pass.

## Goal / Problem Statement
The current browser MCP requires explicit `tab_id` handoff or `keep_tab=true` to preserve tab state. This is not natural for agents: by default they should continue operating on the same active tab unless they intentionally open or target another tab.

## In-Scope Use Cases
1. Open and continue on same tab by default.
2. Navigate/read/screenshot/dom-snapshot/run-script without passing `tab_id`, and have operations resolve to the active tab when one exists.
3. Open a new tab and make it the new active tab.
4. Explicit `tab_id` still overrides active-tab default.
5. Close active tab without specifying `tab_id`.
6. If no active tab exists, tools requiring a page can still create a short-lived tab when given `url`.

## Acceptance Criteria
1. `open_tab(url?)` creates a persistent tab and sets it as active.
2. `navigate_to`, `read_page`, `screenshot`, `dom_snapshot`, and `run_script` remove `keep_tab` parameter.
3. When `tab_id` is omitted and active tab exists, tools operate on active tab.
4. When `tab_id` is omitted and no active tab exists:
   - tools requiring URL input succeed only when `url` is provided and can use ephemeral behavior,
   - tools without URL context return a clear error.
5. `close_tab(tab_id?)` closes the specified tab or active tab when omitted; active tab pointer updates deterministically.
6. `list_tabs` behavior remains unchanged (persistent tabs only).
7. Integration tests and server tests cover all tools with active-tab default semantics.
8. No backward compatibility path for `keep_tab`; parameter is removed cleanly.

## Constraints / Dependencies
- Depends on `brui_core.UIIntegrator` and Playwright page lifecycle.
- Must keep MCP tool names stable for currently kept tools.
- Must avoid legacy compatibility branches per project policy.

## Assumptions
- Single agent flow commonly targets one primary tab.
- Persistent tab state should be explicit in manager state, not inferred from last operation.
- Ephemeral mode remains useful when a user provides one-off `url` without opening a tab.

## Open Questions / Risks
- Closing active tab selection policy (choose most recently opened remaining tab vs oldest). Proposed: choose most recently opened remaining tab.
- Concurrent tool calls may race active-tab updates. Risk mitigated by lock-protected manager operations.

## Scope Triage
- **Chosen depth: Medium**
- Rationale:
  - public tool API changes (`keep_tab` removal, `open_tab`/`close_tab` signatures),
  - cross-cutting behavior updates across tab manager + all page tools + tests + README,
  - no storage/schema changes and architecture remains local to browser-mcp.
