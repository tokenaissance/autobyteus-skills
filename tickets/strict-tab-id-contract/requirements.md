# Requirements

## Status
Design-ready

## Goal
Make browser MCP tab behavior deterministic by requiring explicit `tab_id` for stateful operations.

## In-Scope Use Cases
1. Open a persistent tab and receive `tab_id`.
2. Navigate that tab to URL with explicit `tab_id`.
3. Read/screenshot/DOM-snapshot/run-script against explicit `tab_id` only.
4. Close a tab using explicit `tab_id` only.
5. List open tab IDs.

## Acceptance Criteria
1. `navigate_to`, `read_page`, `screenshot`, `dom_snapshot`, `run_script`, `close_tab` require `tab_id`.
2. Active-tab fallback and ephemeral resolver behavior are removed from runtime path.
3. Tool outputs use non-optional `tab_id` where applicable.
4. README reflects strict contract and examples use explicit `tab_id`.
5. Unit/server tests and real integration tests pass with updated contract.

## Constraints / Dependencies
- Depends on current `brui_core` + Playwright integration.
- Real integration test requires reachable Chrome debug endpoint (`CHROME_REMOTE_DEBUGGING_PORT`).

## Assumptions
- Client agents can store and pass returned `tab_id`.
- Breaking API changes are acceptable.

## Risks
- Existing clients using omitted `tab_id` will fail until updated.
