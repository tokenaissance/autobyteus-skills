# Proposed Design Document

## Design Version
- Current Version: v2

## Revision History
| Version | Trigger | Summary Of Changes | Related Review Round |
| --- | --- | --- | --- |
| v1 | Initial draft | Added explicit attach flow and safe close semantics | 1 |
| v2 | Naming refinement | Replaced ambiguous source naming with `attach_state` + `attached_by` | 3 |

## Artifact Basis
- Investigation Notes: `tickets/in-progress/attach-existing-tab/investigation-notes.md`
- Requirements: `tickets/in-progress/attach-existing-tab/requirements.md`
- Requirements Status: Refined

## Summary
Add a new `attach_tab` tool that maps an already-open Playwright page (from connected CDP context) into MCP `TabManager`. Extend tab metadata and list output so each tracked tab is clearly represented with natural naming.

## Goals
- Allow direct debugging/automation against user-existing authenticated tabs.
- Keep deterministic tab-id workflow.
- Prevent accidental closing of user-owned tabs.

## Legacy Removal Policy (Mandatory)
- Policy: No backward compatibility; remove legacy code paths.
- Required action: do not add implicit auto-attach or hidden fallback attach behavior.

## Requirements And Use Cases
| Requirement | Description | Acceptance Criteria | Use Case IDs |
| --- | --- | --- | --- |
| R-001 | Expose attach tool | AC-001 | UC-001 |
| R-002 | Deterministic matcher behavior | AC-002, AC-003 | UC-001, UC-002 |
| R-003 | Detach-safe close default | AC-006, AC-007 | UC-005 |
| R-004 | Natural metadata naming | AC-004 | UC-003 |
| R-005 | Interoperate with current tools | AC-005 | UC-004 |
| R-006 | Explicit-only attach entrypoint | AC-008 + code review | UC-001, UC-003 |

## Codebase Understanding Snapshot (Pre-Design Mandatory)
| Area | Findings | Evidence (files/functions) | Open Unknowns |
| --- | --- | --- | --- |
| Entrypoints / Boundaries | All MCP tools registered from `tools/__init__.py`; state mediated via `TabManager`. | `src/browser_mcp/tools/__init__.py`, `src/browser_mcp/tabs.py` | None |
| Current Naming Conventions | Verb-object snake_case for tools, typed dict results in `types.py`. | `tools/*.py`, `types.py` | None |
| Impacted Modules / Responsibilities | `tabs.py` owns lifecycle; each tool handles one operation and requires `tab_id`. | `tabs.py`, `tools/list_tabs.py`, `tools/close_tab.py`, `tools/open_tab.py` | None |
| Data / Persistence / External IO | No persistent storage; in-memory `_tabs`. Browser state from Playwright CDP context pages. | `tabs.py`, `brui_core/ui_integrator.py` | Multi-context behavior outside context[0] |

## Current State (As-Is)
- `TabManager` can only create tabs through `open_tab` and tracks only those IDs.
- `list_tabs` returns only MCP-managed IDs.
- Existing page tools require `tab_id` and cannot reference pre-existing context pages.
- `close_tab` always closes underlying page for tracked tab.

## Target State (To-Be)
- `attach_tab` selects an existing page from current browser context by explicit matcher and registers it as tracked.
- `list_tabs` returns structured tab metadata: `tab_id`, `attach_state`, `attached_by`, `url`, `title`, `created_at`.
- `attach_state` is the attachment lifecycle state (`attached` for tracked tabs).
- `attached_by` captures how tab became tracked (`open_tab` or `attach_tab`).
- `close_tab` closes tracked tabs consistently (including attached tabs) and keeps legacy `close_browser` passthrough.

## Architecture Direction Decision (Mandatory)
- Chosen direction: Keep existing architecture, add one explicit attach tool and metadata-rich tab model.
- Rationale: keeps tool contract explicit and deterministic while minimizing disruption.
- Layering fitness assessment: Yes
- Outcome: Add + Modify

## Change Inventory (Delta)
| Change ID | Change Type (`Add`/`Modify`/`Rename/Move`/`Remove`) | Current Path | Target Path | Rationale | Impacted Areas | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| C-001 | Add | N/A | `src/browser_mcp/tools/attach_tab.py` | New explicit attach entrypoint | MCP API | URL/title matcher input |
| C-002 | Modify | `src/browser_mcp/tabs.py` | same | Track attachment metadata + attach logic | core state model | no persistence |
| C-003 | Modify | `src/browser_mcp/types.py` | same | Add typed results for attach/list/close metadata | API contracts | backward-safe extension |
| C-004 | Modify | `src/browser_mcp/tools/list_tabs.py` | same | Return structured metadata list | usability + safety | replaces id-only payload |
| C-005 | Modify | `src/browser_mcp/tools/close_tab.py` | same | Keep legacy `close_browser` option while removing attach-specific close flags | lifecycle consistency | backward compatible |
| C-006 | Modify | `src/browser_mcp/tools/__init__.py` | same | Register `attach_tab` | registry | simple wiring |
| C-007 | Modify | `tests/test_server.py` | same | Unit coverage for attach/list/close behavior | quality gate | mandatory |
| C-008 | Modify | `tests/test_integration_real.py` | same | Real browser coverage for attach flow | regression safety | env-gated |
| C-009 | Modify | `README.md` | same | Document attach semantics and naming | docs | required |

## Target Architecture Shape And Boundaries (Mandatory)
| Layer/Boundary | Purpose | Owns | Must Not Own | Notes |
| --- | --- | --- | --- | --- |
| Tool layer (`tools/*`) | Input validation + orchestration | tool params, typed return | shared state internals | delegate to `TabManager` |
| Tab state layer (`tabs.py`) | lifecycle + registry | tab creation, attach, close policy, metadata | page-specific operations | single state authority |
| Execution layer (`brui_core` + Playwright) | browser/page primitives | context/pages/actions | MCP API policies | unchanged |

## File And Module Breakdown
| File/Module | Change Type | Layer / Boundary | Concern / Responsibility | Public APIs | Inputs/Outputs | Dependencies |
| --- | --- | --- | --- | --- | --- | --- |
| `src/browser_mcp/tools/attach_tab.py` | Add | Tool | Attach existing page | `attach_tab(...)` | matcher -> `AttachTabResult` | `TabManager` |
| `src/browser_mcp/tabs.py` | Modify | State | Store metadata and close policy | `attach_existing_tab(...)`, `close_tab(...)`, `list_tabs(...)` | page + policy -> tab records | `UIIntegrator` |
| `src/browser_mcp/types.py` | Modify | Contract | New typed dicts/fields | `AttachTabResult`, `TabListEntry`, richer `ListTabsResult` | typed payloads | stdlib |
| `src/browser_mcp/tools/list_tabs.py` | Modify | Tool | expose metadata list | `list_tabs()` | none -> `ListTabsResult` | `TabManager` |
| `src/browser_mcp/tools/close_tab.py` | Modify | Tool | tracked-tab close + legacy option passthrough | `close_tab(...)` | params -> `CloseTabResult` | `TabManager` |

## Naming Decisions (Natural And Implementation-Friendly)
| Item Type (`File`/`Module`/`API`) | Current Name | Proposed Name | Reason | Notes |
| --- | --- | --- | --- | --- |
| API | N/A | `attach_tab` | clear user action | explicit attach step |
| Field | `source` (`opened`/`attached`) | `attach_state` (`attached`) | directly expresses state | avoids ambiguity |
| Field | N/A | `attached_by` (`open_tab`/`attach_tab`) | clearly expresses origin action | natural verb-based naming |
| Payload | `tab_ids` | `tabs` | extensible metadata list | operator-friendly |

## Existing-Structure Bias Check (Mandatory)
| Candidate Area | Current-File-Layout Bias Risk | Architecture-First Alternative | Decision | Why |
| --- | --- | --- | --- | --- |
| attach logic location | Medium | put logic in tool only | Change to state-layer method | keeps lifecycle authority centralized |

## Anti-Hack Check (Mandatory)
| Candidate Change | Shortcut/Hack Risk | Proper Structural Fix | Decision | Notes |
| --- | --- | --- | --- | --- |
| Infer attach implicitly from unknown `tab_id` | High | explicit `attach_tab` API | Reject shortcut | avoids hidden side effects |
| Remove legacy `close_browser` from `close_tab` | Medium | keep existing option | Reject shortcut | preserves compatibility |

## Dependency Flow And Cross-Reference Risk
| Module/File | Upstream Dependencies | Downstream Dependents | Cross-Reference Risk | Mitigation / Boundary Strategy |
| --- | --- | --- | --- | --- |
| `tabs.py` | `UIIntegrator` | all tools | Low | keep business rules in tabs, not tools |
| `tools/attach_tab.py` | `tabs.py` | MCP server | Low | one-way dependency |

## Decommission / Cleanup Plan
| Item To Remove/Rename | Cleanup Actions | Legacy Removal Notes | Verification |
| --- | --- | --- | --- |
| `ListTabsResult.tab_ids` id-only payload | replace with `tabs` metadata list | no dual payload branches | tests + README updates |

## Error Handling And Edge Cases
- zero matches -> `ValueError` with matcher context.
- multiple matches -> `ValueError` requiring tighter matcher.
- attached page closed externally -> page tools fail fast with actionable error.

## Use-Case Coverage Matrix (Design Gate)
| use_case_id | Requirement | Use Case | Primary Path Covered (`Yes`/`No`) | Fallback Path Covered (`Yes`/`No`/`N/A`) | Error Path Covered (`Yes`/`No`/`N/A`) | Runtime Call Stack Section |
| --- | --- | --- | --- | --- | --- | --- |
| UC-001 | R-001,R-002 | attach by URL | Yes | N/A | Yes | UC-001 |
| UC-002 | R-002 | attach by title | Yes | N/A | Yes | UC-002 |
| UC-003 | R-004,R-006 | list metadata | Yes | N/A | N/A | UC-003 |
| UC-004 | R-005 | operate on attached tab | Yes | N/A | Yes | UC-004 |
| UC-005 | R-003 | close attached tab safely | Yes | Yes | Yes | UC-005 |

## Open Questions
- Should `list_tabs` gain optional `include_unattached` discovery mode in a follow-up ticket?
