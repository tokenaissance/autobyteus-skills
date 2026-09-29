# Future-State Runtime Call Stacks (Debug-Trace Style)

## Design Basis
- Scope Classification: Medium
- Call Stack Version: v2
- Requirements: `tickets/in-progress/attach-existing-tab/requirements.md` (Refined)
- Source Artifact: `tickets/in-progress/attach-existing-tab/proposed-design.md`
- Source Design Version: v2

## Use Case Index (Stable IDs)
| use_case_id | Source Type (`Requirement`/`Design-Risk`) | Requirement ID(s) | Design-Risk Objective | Use Case Name | Coverage Target (Primary/Fallback/Error) |
| --- | --- | --- | --- | --- | --- |
| UC-001 | Requirement | R-001,R-002 | N/A | Attach existing tab by URL matcher | Yes/N/A/Yes |
| UC-002 | Requirement | R-002 | N/A | Attach existing tab by title matcher | Yes/N/A/Yes |
| UC-003 | Requirement | R-004,R-006 | N/A | List tab metadata with attachment naming | Yes/N/A/N/A |
| UC-004 | Requirement | R-005 | N/A | Use attached tab with existing page tools | Yes/N/A/Yes |
| UC-005 | Requirement | R-003,R-007 | N/A | Close attached tab with consistent tracked-tab close semantics | Yes/Yes/Yes |

## Use Case: UC-001 Attach existing tab by URL matcher
### Primary Runtime Call Stack
```text
[ENTRY] src/browser_mcp/tools/attach_tab.py:attach_tab(url_contains=..., title_contains=None)
├── src/browser_mcp/tabs.py:TabManager.attach_existing_tab(url_contains=..., title_contains=None) [ASYNC]
│   ├── src/browser_mcp/tabs.py:prepare_integrator() [ASYNC]
│   │   └── brui_core/ui_integrator.py:UIIntegrator.initialize() [ASYNC]
│   ├── src/browser_mcp/tabs.py:_find_matching_page(context.pages, matcher)
│   ├── src/browser_mcp/tabs.py:_allocate_tab_id() [STATE]
│   ├── src/browser_mcp/tabs.py:_tabs[tab_id]=BrowserTab(attach_state='attached', attached_by='attach_tab') [STATE]
│   ├── src/browser_mcp/tabs.py:_cleanup_unused_default_page() [ASYNC]
│   └── return BrowserTab
└── src/browser_mcp/tools/attach_tab.py:return AttachTabResult(tab_id, attach_state='attached', attached_by='attach_tab', url, title, attached=true)
```

### Error Path
```text
[ERROR] no matched pages
src/browser_mcp/tabs.py:_find_matching_page(...)
└── raise ValueError("No page matched attach criteria ...")
```

```text
[ERROR] multiple matched pages
src/browser_mcp/tabs.py:_find_matching_page(...)
└── raise ValueError("Multiple pages matched attach criteria ...")
```

### Coverage Status
- Primary Path: Covered
- Fallback Path: N/A
- Error Path: Covered

## Use Case: UC-002 Attach existing tab by title matcher
### Primary Runtime Call Stack
```text
[ENTRY] src/browser_mcp/tools/attach_tab.py:attach_tab(url_contains=None, title_contains=...)
├── src/browser_mcp/tabs.py:TabManager.attach_existing_tab(...) [ASYNC]
│   ├── prepare_integrator() [ASYNC]
│   ├── iterate context.pages and read page.title() [ASYNC]
│   ├── select unique match by normalized title
│   ├── register BrowserTab(attach_state='attached', attached_by='attach_tab') [STATE]
│   └── return BrowserTab
└── return AttachTabResult
```

### Error Path
```text
[ERROR] empty matcher input
src/browser_mcp/tools/attach_tab.py:attach_tab(...)
└── raise ValueError("Provide at least one matcher")
```

### Coverage Status
- Primary Path: Covered
- Fallback Path: N/A
- Error Path: Covered

## Use Case: UC-003 List tab metadata with attachment naming
### Primary Runtime Call Stack
```text
[ENTRY] src/browser_mcp/tools/list_tabs.py:list_tabs()
├── src/browser_mcp/tabs.py:TabManager.list_tabs()
│   ├── iterate _tabs values [STATE]
│   ├── collect tab_id/attach_state/attached_by/url/title/created_at
│   └── sort by numeric tab_id
└── src/browser_mcp/tools/list_tabs.py:return ListTabsResult(tabs=[...])
```

### Coverage Status
- Primary Path: Covered
- Fallback Path: N/A
- Error Path: N/A

## Use Case: UC-004 Use attached tab with existing page tools
### Primary Runtime Call Stack
```text
[ENTRY] src/browser_mcp/tools/dom_snapshot.py:dom_snapshot(tab_id=attached_id, ...)
├── src/browser_mcp/tabs.py:get_tab_or_raise(tab_id)
├── tab.integrator.page.evaluate(DOM_SCRIPT, ...) [ASYNC]
└── return DomSnapshotResult(tab_id=attached_id,...)
```

### Error Path
```text
[ERROR] attached page was closed externally
src/browser_mcp/tools/dom_snapshot.py:dom_snapshot(...)
└── playwright throws -> surface RuntimeError with actionable message
```

### Coverage Status
- Primary Path: Covered
- Fallback Path: N/A
- Error Path: Covered

## Use Case: UC-005 Close attached tab with consistent tracked-tab close semantics
### Primary Runtime Call Stack
```text
[ENTRY] src/browser_mcp/tools/close_tab.py:close_tab(tab_id, close_browser=false)
├── src/browser_mcp/tabs.py:TabManager.close_tab(tab_id, close_browser=false) [ASYNC]
│   ├── pop tab from _tabs [STATE]
│   ├── tab.integrator.close(close_browser=false) [ASYNC]
│   └── return (tab_id, closed=true)
└── return CloseTabResult(...)
```

### Fallback Path
```text
[FALLBACK] explicit browser-close passthrough
src/browser_mcp/tools/close_tab.py:close_tab(tab_id, close_browser=true)
└── TabManager.close_tab(...)
    └── tab.integrator.close(close_page=true, close_browser=...) [ASYNC]
```

### Error Path
```text
[ERROR] unknown tab_id
src/browser_mcp/tabs.py:TabManager.close_tab(...)
└── raise ValueError("Unknown tab_id ... attach_tab/open_tab first")
```

### Coverage Status
- Primary Path: Covered
- Fallback Path: Covered
- Error Path: Covered
