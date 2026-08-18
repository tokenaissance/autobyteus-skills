# Requirements - Attach Existing Browser Tabs to MCP

## Status
- Refined

## Scope Classification
- Classification: Medium
- Rationale:
  - Adds new MCP API surface (`attach_tab`) and updates output contract for tab discovery.
  - Touches core tab lifecycle behavior (`tabs.py`) plus multiple tool modules and tests.
  - Requires explicit close semantics alignment with existing `close_tab` contract.

## Goal / Problem Statement
Browser MCP must support attaching to already-open pages in the connected CDP browser context so users can inspect and automate real live tabs (for example authenticated ChatGPT sessions) without recreating state in an MCP-managed tab.

## In-Scope Use Cases
- UC-001: Attach by URL matcher to an existing context page and receive a new MCP `tab_id`.
- UC-002: Attach by title matcher when URL is dynamic but title is stable.
- UC-003: List tabs returns MCP-managed tabs with clear attachment metadata.
- UC-004: Existing tools (`read_page`, `dom_snapshot`, `run_script`, `screenshot`, `navigate_to`) work on attached tabs exactly like tabs created via `open_tab`.
- UC-005: Close semantics for attached tabs match existing tracked-tab behavior and keep legacy `close_browser` option.

## Out of Scope
- Multi-context selection policy beyond current context index behavior.
- Global Chrome tab enumeration outside the connected CDP browser session.
- Automatic implicit attachment without explicit user tool call.

## Requirements
- R-001 (`attach_tab` availability):
  - Expected outcome: MCP exposes a new `attach_tab` tool that can bind an existing page from the connected browser context into `TabManager` and return a stable MCP `tab_id`.
- R-002 (matcher support):
  - Expected outcome: `attach_tab` supports explicit matching input and fails with actionable error when zero or multiple pages match.
- R-003 (close behavior consistency):
  - Expected outcome: Closing an attached tab via MCP closes the tracked page and removes MCP state, consistent with existing tracked-tab behavior.
- R-007 (legacy option retention):
  - Expected outcome: `close_tab` keeps the existing `close_browser` option for backward compatibility.
- R-004 (tab introspection quality):
  - Expected outcome: `list_tabs` includes metadata needed for safe operator understanding: `attach_state`, `attached_by`, current `url`, optional `title`.
- R-005 (tool interoperability):
  - Expected outcome: All existing tab-id-based tools operate correctly on attached tabs without additional flags.
- R-006 (no legacy dual path retention):
  - Expected outcome: No compatibility shim that reintroduces hidden/implicit attach behavior; explicit `attach_tab` is the only attach entrypoint.

## Acceptance Criteria
- AC-001: Calling `attach_tab` with a matcher that uniquely identifies an existing page returns `attached=true`, a new MCP `tab_id`, and page URL.
- AC-002: Calling `attach_tab` with no matches fails with clear message including matcher summary.
- AC-003: Calling `attach_tab` with multiple matches fails with clear message requiring tighter matcher.
- AC-004: `list_tabs` includes metadata entries where `attach_state == "attached"` and `attached_by in {"open_tab","attach_tab"}`.
- AC-005: `read_page` on an attached tab returns content successfully when page is navigated.
- AC-006: `close_tab` on attached tab closes the underlying page and removes the MCP tab entry.
- AC-007: `close_tab` accepts `close_browser` and forwards the option through existing close lifecycle.
- AC-008: Existing `open_tab` flow and tests continue passing.

## Constraints / Dependencies
- Depends on current `brui_core` behavior: `UIIntegrator.initialize()` creates a new page but provides access to `context.pages`.
- Must keep operations compatible with CDP-connected Chrome via `CHROME_REMOTE_DEBUGGING_PORT`.
- Must remain deterministic and script-safe for agent workflows.

## Assumptions
- The target page exists in the same browser context that MCP connects to.
- Users can provide enough matcher specificity (URL/title) when duplicate tabs exist.

## Open Questions / Risks
- If target page is closed externally after attach, MCP tab entry may become stale; behavior should fail fast with clear error.
- Title-only matching can be unstable for duplicate app tabs; URL matching should be preferred where possible.

## Requirement Coverage Map
| requirement_id | mapped_use_case_ids |
| --- | --- |
| R-001 | UC-001 |
| R-002 | UC-001, UC-002 |
| R-003 | UC-005 |
| R-004 | UC-003 |
| R-005 | UC-004 |
| R-006 | UC-001, UC-003 |
| R-007 | UC-005 |
