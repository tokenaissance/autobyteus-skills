# Implementation Plan

## Scope Classification
- Classification: Medium
- Reasoning:
  - New tool surface + tab-state metadata model changes + close policy updates + tests/docs updates.
- Workflow Depth: Medium

## Upstream Artifacts (Required)
- Investigation notes: `tickets/in-progress/attach-existing-tab/investigation-notes.md`
- Requirements: `tickets/in-progress/attach-existing-tab/requirements.md`
  - Current Status: Refined
- Runtime call stacks: `tickets/in-progress/attach-existing-tab/future-state-runtime-call-stack.md`
- Runtime review: `tickets/in-progress/attach-existing-tab/future-state-runtime-call-stack-review.md`
- Proposed design: `tickets/in-progress/attach-existing-tab/proposed-design.md`

## Plan Maturity
- Current Status: Ready For Implementation
- Notes: Runtime review gate is Go Confirmed on v2 artifacts.

## Preconditions (Must Be True Before Finalizing This Plan)
- `requirements.md` is at least `Design-ready`: Yes (`Refined`)
- Runtime call stack review artifact exists and is current: Yes
- All in-scope use cases reviewed: Yes
- No unresolved blocking findings: Yes
- Runtime review has `Go Confirmed` with two consecutive clean deep-review rounds: Yes

## Runtime Call Stack Review Gate Summary (Required)
| Round | Review Result | Findings Requiring Write-Back | Write-Back Completed | Round State (`Reset`/`Candidate Go`/`Go Confirmed`) | Clean Streak After Round |
| --- | --- | --- | --- | --- | --- |
| 3 | Pass | No | N/A | Candidate Go | 1 |
| 4 | Pass | No | N/A | Go Confirmed | 2 |

## Go / No-Go Decision
- Decision: Go
- Evidence:
  - Final review round: 4
  - Clean streak at final round: 2
  - Final review gate line (`Implementation can start`): Yes

## Principles
- Bottom-up: update shared type/state model before tool adapters.
- Test-driven: update unit tests with each behavior addition.
- Mandatory modernization rule: no hidden/implicit attach behavior.

## Dependency And Sequencing Map
| Order | File/Module | Depends On | Why This Order |
| --- | --- | --- | --- |
| 1 | `src/browser_mcp/types.py` | N/A | define output contracts first |
| 2 | `src/browser_mcp/tabs.py` | `types.py` | core lifecycle + metadata behavior |
| 3 | `src/browser_mcp/tools/attach_tab.py` | `tabs.py`, `types.py` | new API entrypoint |
| 4 | `src/browser_mcp/tools/list_tabs.py` | `tabs.py`, `types.py` | expose metadata payload |
| 5 | `src/browser_mcp/tools/close_tab.py` | `tabs.py`, `types.py` | retain legacy `close_browser` while aligning attach close semantics |
| 6 | `src/browser_mcp/tools/__init__.py` | attach tool | register API |
| 7 | `tests/test_server.py` | all above | behavior validation |
| 8 | `tests/test_integration_real.py` | all above | real CDP flow verification |
| 9 | `README.md` | final behavior | operator docs |

## Requirement And Design Traceability
| Requirement | Design Section | Use Case / Call Stack | Planned Task ID(s) | Stage 5 Verification (Unit/Integration) | Stage 6 Scenario ID(s) |
| --- | --- | --- | --- | --- | --- |
| R-001 | Target State + C-001 | UC-001 | T-003 | Unit + Integration | SV-001 |
| R-002 | Error Handling + C-001/C-002 | UC-001/UC-002 | T-002,T-003,T-007 | Unit + Integration | SV-002 |
| R-003 | Target State + C-005 | UC-005 | T-002,T-005,T-007 | Unit + Integration | SV-003 |
| R-004 | Naming Decisions + C-003/C-004 | UC-003 | T-001,T-004,T-007 | Unit + Integration | SV-004 |
| R-005 | Target State + C-002 | UC-004 | T-002,T-007,T-008 | Unit + Integration | SV-005 |
| R-006 | Anti-Hack + C-001/C-004 | UC-001/UC-003 | T-003,T-004,T-009 | Unit + review | SV-006 |
| R-007 | Target State + C-005 | UC-005 | T-005,T-007 | Unit + Integration | SV-007 |

## Step-By-Step Plan
1. T-001: Extend `types.py` for `AttachTabResult`, `TabListEntry`, and richer `CloseTabResult` metadata.
2. T-002: Refactor `tabs.py` to support `attach_state` + `attached_by`, and attach flow.
3. T-003: Implement `tools/attach_tab.py` with explicit matcher validation and deterministic match handling.
4. T-004: Update `tools/list_tabs.py` to return `tabs` metadata list.
5. T-005: Update `tools/close_tab.py` to keep legacy `close_browser` and remove attach-specific close flags.
6. T-006: Register new tool in `tools/__init__.py`.
7. T-007: Update/extend `tests/test_server.py` for attach/list/close behavior and matcher errors.
8. T-008: Add/adjust real integration tests for attach-on-existing-page flow.
9. T-009: Update README tool docs and list-tabs payload examples.

## Test Strategy
- Unit tests: `tests/test_server.py` focused tool behavior and deterministic failure modes.
- Integration tests: `tests/test_integration_real.py` for live CDP attach flow.
- Stage 5 boundary: module-level tests only.
- Stage 6 handoff notes:
  - critical flows: attach -> list -> dom_snapshot -> close(tab) -> close(tab+browser)
  - expected scenario count: 6
  - constraints: requires reachable CDP browser endpoint with at least one existing tab.

## Aggregated System Validation Scenario Catalog (Stage 6 Input)
| Scenario ID | Source Type (`Requirement`/`Design-Risk`) | Requirement ID(s) | Use Case ID(s) | Validation Level (`API`/`E2E`/`System`) | Expected Outcome |
| --- | --- | --- | --- | --- | --- |
| SV-001 | Requirement | R-001 | UC-001 | E2E | attach returns MCP tab id for existing page |
| SV-002 | Requirement | R-002 | UC-001,UC-002 | E2E | zero/multi matches return clear errors |
| SV-003 | Requirement | R-003 | UC-005 | E2E | close attached tab closes underlying page and removes tracked entry |
| SV-004 | Requirement | R-004 | UC-003 | API | list includes attach_state/attached_by/url/title metadata |
| SV-005 | Requirement | R-005 | UC-004 | E2E | dom/read/script/screenshot all work on attached tab |
| SV-006 | Requirement | R-006 | UC-001,UC-003 | API | no implicit attach path exists |
| SV-007 | Requirement | R-007 | UC-005 | API | close_tab retains `close_browser` parameter |
