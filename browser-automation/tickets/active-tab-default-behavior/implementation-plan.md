# Implementation Plan - Active Tab Default Behavior

## Scope
Implement active-tab-first tool behavior and remove `keep_tab` from browser MCP tools and resolver logic.

## Requirement Traceability
| Requirement | Design Section | Use Case | Implementation Tasks | Verification |
|---|---|---|---|---|
| AC-1 open_tab sets active tab | Target-State + API table | UC-1 | Update `TabManager.open_tab`; extend `open_tab` tool to support optional URL | `tests/test_server.py`, `tests/test_integration_real.py` |
| AC-2 remove keep_tab | Change inventory (`Remove`) | UC-2/UC-3/UC-4 | Remove param from resolver + all page tools + docs/tests | static checks + unit/integration tests |
| AC-3 omitted tab uses active | Target-State | UC-3 | Add active pointer getters/setters and resolver branch | unit/integration tests |
| AC-4 no active + url ephemeral | Target-State | UC-4 | Preserve ephemeral path in resolver without `keep_tab` | unit/integration tests |
| AC-5 close_tab defaults active | Target-State | UC-5 | Make `close_tab` tab_id optional and update active pointer policy | unit/integration tests |
| AC-6 list_tabs unchanged | Current/Target summary | UC-1/UC-5 | Keep list semantics; add active indicator field | unit/integration tests |
| AC-7 full tool coverage | Requirements | UC-1..UC-5 | Update/add tests for all tools | run pytest suites |
| AC-8 no backward compatibility | Core modernization | all | delete keep_tab branches and old tests | code review + test pass |

## Task Breakdown (Bottom-Up)
1. Update `src/browser_mcp/tabs.py`:
   - add active tab state and deterministic close behavior,
   - replace resolver signature with active-tab-first semantics.
2. Update tool contracts:
   - `open_tab(url?, wait_until, timeout_ms)`,
   - `close_tab(tab_id?, close_browser)`,
   - remove `keep_tab` from `navigate_to`, `read_page`, `screenshot`, `dom_snapshot`, `run_script`.
3. Update result types in `src/browser_mcp/types.py`.
4. Update server tests (`tests/test_server.py`) for active-tab default paths.
5. Update real integration tests (`tests/test_integration_real.py`) to validate default same-tab behavior.
6. Update `README.md` contract and examples.
7. Run verification suites and record outcomes.

## Verification Strategy
- Unit/server-level tests:
  - tool registration and behavior through fake page/integrator.
- Integration tests:
  - real browser flow through MCP client/session for every tool.
  - explicit multi-step flow showing same active tab across multiple tool calls.
- E2E feasibility:
  - feasible when a Chrome debug endpoint is reachable on localhost (or Linux Chrome binary exists at `/usr/bin/google-chrome`).
  - current host constraint: no debug endpoint and no `/usr/bin/google-chrome`, so real integration/E2E is blocked here.
  - representative E2E-style scenario once environment is ready: open tab -> navigate -> dom_snapshot -> run_script -> screenshot -> read_page -> close tab.

## Decommission / Cleanup
- Remove all `keep_tab` arguments and branches.
- Remove tests asserting old ephemeral-by-default expectation when active tab exists.

## Risks / Mitigations
- Risk: concurrent requests race active pointer.
  - Mitigation: keep state transitions under `TabManager` lock for open/close.
- Risk: behavior mismatch in docs/tests.
  - Mitigation: update README and enforce integration coverage for all tools.
