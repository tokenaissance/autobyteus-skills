# Implementation Plan - Tool Naming Simplification

Status: Finalized (post-review gate)

## Approved Scope
- Keep only canonical tool names:
  - `read_page`
  - `screenshot`
  - `dom_snapshot`
- Remove all backward compatibility:
  - remove legacy alias handlers from canonical tool modules
  - remove legacy shim modules/files
  - remove legacy references in tests/docs

## Tasks (Bottom-Up)
1. Update canonical tool modules to expose only canonical handlers.
2. Delete legacy shim modules.
3. Update README to canonical names only.
4. Update unit/integration tests to canonical names only.
5. Run verification suite and targeted real integration checks.

## Verification Strategy
- Unit: `uv run python -m pytest -q tests/test_server.py`
- Integration: `uv run python -m pytest -q tests/test_integration_real.py -k 'open_list_close_session_real or take_webpage_screenshot_real or navigate_and_read_local_page'`
- Real runtime smoke: invoke `read_page`, `screenshot`, `dom_snapshot` against Chrome CDP container.
- E2E feasibility: feasible in this environment; representative E2E-like tool calls will be executed.

## Traceability
- AC1/AC2/AC6 -> canonical-only tool definitions and registry verification.
- AC3 -> shim file deletions.
- AC4 -> unit tests.
- AC5 -> integration tests + README updates.
