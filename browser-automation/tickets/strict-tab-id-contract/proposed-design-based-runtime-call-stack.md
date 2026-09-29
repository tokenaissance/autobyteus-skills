# Proposed-Design-Based Runtime Call Stack

## Version
v1

## UC-1 Open and Navigate (explicit tab)
1. `tools/open_tab.py:open_tab(url?)`
2. `tabs.py:TabManager.open_tab()`
3. `tabs.py:prepare_integrator()`
4. `brui_core` initializes page
5. optional `page.goto(url)`
6. return `{ tab_id, url }`
7. `tools/navigate_to.py:navigate_to(tab_id, url)`
8. `tabs.py:get_tab_or_raise(tab_id)`
9. `page.goto(url)`
10. return `{ url, ok, status, tab_id }`

## UC-2 Read/Snapshot/Script (explicit tab)
1. `tools/read_page.py:read_page(tab_id, cleaning_mode)`
2. `tabs.py:get_tab_or_raise(tab_id)`
3. guard `tab.last_url` exists
4. `page.content()`
5. `cleaning.clean_html(...)`
6. return `{ url, content, tab_id }`

1. `tools/dom_snapshot.py:dom_snapshot(tab_id, ...)`
2. `tabs.py:get_tab_or_raise(tab_id)`
3. guard `tab.last_url` exists
4. `page.evaluate(_DOM_SNAPSHOT_SCRIPT, ...)`
5. return structured snapshot + `tab_id`

1. `tools/run_script.py:run_script(tab_id, script, arg)`
2. `tabs.py:get_tab_or_raise(tab_id)`
3. guard `tab.last_url` exists
4. normalize script
5. `page.evaluate(...)`
6. return `{ url, result, tab_id }`

## UC-3 Close Tab
1. `tools/close_tab.py:close_tab(tab_id, close_browser)`
2. `tabs.py:TabManager.close_tab(tab_id, close_browser)`
3. close integrator if found
4. return `{ tab_id, closed }`
