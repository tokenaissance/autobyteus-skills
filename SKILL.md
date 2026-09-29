---
name: browser-automation
description: Operate a local Chrome/Chromium session through the bundled browser CLI for explicit-tab navigation, authenticated-page inspection, DOM observation, JavaScript interaction with a visible presentation cursor, screenshots, MP4 tab recordings, and multi-step browser workflows, including Electron apps such as an isolated AutoByteus instance. Use when an agent must act in or inspect a live browser, especially existing signed-in tabs. Do not use for generic web research or ordinary URL lookup when a non-browser web tool is sufficient.
---

# Browser Automation

Use only the bundled launcher referenced here as `scripts/browser`.

When browser work begins:

1. Use the exact path of this `SKILL.md` that the runtime advertised and that you read.
2. Resolve `scripts/browser` from the directory containing that exact file.
3. From the current task workspace, invoke the resolved launcher with Bash and pass `health-check` first. Keep the task workspace as the shell working directory for every call.

Resolve the launcher from the advertised file whenever needed; do not depend on a persistent shell variable or other shell state. If the runtime provides no exact readable locator for this `SKILL.md`, treat this skill as unsupported rather than guessing or scanning for another copy. Do not use a vendor-specific skill home, register a PATH command, change into the skill bundle, activate an environment, or invoke Python/uv directly.

## Workflow

Treat every command name below as arguments to the resolved launcher, not as a bare PATH command.

1. Invoke the resolved launcher with `health-check`. If it fails, interpret the JSON error before retrying.
2. Run `list-tabs`; use `attach-tab` with a precise URL/title matcher for an existing user tab, or use `open-tab` for a task-owned tab.
3. Retain the returned opaque `result.tab_id`. Supply it explicitly to every tab-scoped command. Never shorten it or infer an active tab.
4. Observe with `read-page` or `dom-snapshot` before acting.
5. Act with `navigate` or, only when needed, `run-script`.
6. Verify the result with a fresh read or DOM snapshot. Serialize commands against the same tab; independent clients can race.
7. Close only tabs opened for the task. Do not automatically close tabs discovered with `attach-tab` or other user-owned tabs.

For exact flags, invoke the resolved launcher with `--help` or with a command followed by `--help`. Core commands are `list-tabs`, `attach-tab`, `open-tab`, `close-tab`, `navigate`, `read-page`, `screenshot`, `dom-snapshot`, `run-script`, `start-recording`, and `stop-recording`.

Map script calls directly to operation flags. The normal form is `run-script --tab-id "$TAB_ID" --script '(arg) => ({title: document.title, label: arg.label})' --arg-json '{"label":"direct"}'`. This preserves `run_script(tab_id, script, arg)` without a generic payload or temporary indirection. `--script-file`, `--script-stdin`, and `--arg-file` remain optional when the content already exists in a file/stdin or a concrete shell/process limit prevents faithful argv transport. Do not choose an alternate source merely because JavaScript is nontrivial, long, multiline, or complex.

## Controlling an app or a fixed browser endpoint

The launcher controls the CDP endpoint on `127.0.0.1` at the port in `CHROME_REMOTE_DEBUGGING_PORT` (default 9222). By default it launches Chrome when nothing listens there. To control something already running, such as an isolated AutoByteus instance started with `pnpm isolated-app start` (use the `controlPort` it reports), pass the port and attach-only mode in the invocation environment, for example `env CHROME_REMOTE_DEBUGGING_PORT=<controlPort> BROWSER_AUTOMATION_ATTACH_ONLY=1 bash "<resolved launcher>" list-tabs`. Attach-only never launches a browser: if nothing listens it fails with `BROWSER_UNAVAILABLE` naming the endpoint. An Electron app window appears as one tab. Its `tab_id` changes when the app restarts, so run `list-tabs` again after a restart.

## Presentation helper (`__abDemo`)

`run-script` has a built-in helper for human-like, watchable actions. Mention `__abDemo` in a script and it is available in the page (installed automatically, also after navigation or reload). Scripts that never mention it leave the page untouched. Targets are objects: `{text: 'Create Agent'}` (visible text, `aria-label`, or button value; exact after whitespace trim) or `{selector: '#agent-name'}`, plus optional `nth` (0-based) when several elements match. Bare strings are rejected. Actions only reach elements a person could click: the topmost element at the target's center must be the target, so with an in-page popup or modal open, `click({text: 'Cancel'})` hits the modal's button, and controls behind the modal are not reachable.

- `__abDemo.click(target)`, `hover(target)`: the cursor glides to the element, then click/hover events fire (a click shows a ripple).
- `__abDemo.type(target, 'My Agent', {delayMs: 60, clear: true})`: paced typing into inputs, textareas, and contenteditable; `clear: false` appends.
- `__abDemo.press('Enter')`, `press('k', {meta: true})`: key events on the focused element.
- `__abDemo.scroll(target_or_null, {y: 600})`, `select(target, {label: 'Codex'})` (or `{value}`/`{index}`), `waitFor(target, {timeoutMs: 10000, state: 'visible'|'hidden'})`.
- `__abDemo.caption('Create your first agent', {position: 'bottom'|'top'})`, `hideCaption()`, `highlight(target, {durationMs: 1500})`, `setPresentation(false)` (instant actions, no overlays), `status()`.

Every call resolves to a JSON value: `{ok: true, action, ...}` or `{ok: false, action, error: {code, message}}` with code `NOT_FOUND`, `AMBIGUOUS` (with `candidates`), `OBSCURED` (matches exist but are covered; `covering` names the covering element, so close the popup first), `TIMEOUT`, `NOT_EDITABLE`, or `INVALID_TARGET`. Chain steps in one async script, for example `run-script --tab-id "$TAB_ID" --script 'async () => { await __abDemo.caption("Create an agent"); return await __abDemo.click({text: "Create Agent"}); }'`, then verify with `dom-snapshot` or a screenshot. Events are script-dispatched: native OS dialogs, menus, and file pickers cannot be driven this way.

## Recording a tab

`start-recording --tab-id "$TAB_ID" --output-file tutorial.mp4 [--fps 25] [--overwrite]` starts a background recording of that tab. The command returns immediately; recording continues across any number of later commands (helper actions, screenshots, navigation). `stop-recording --tab-id "$TAB_ID"` finishes it and returns `artifact.path` (the MP4 inside the workspace), `duration_seconds`, `frames`, and `end_reason`. Recording needs `ffmpeg` on PATH (or `BROWSER_AUTOMATION_FFMPEG_BIN`) and no OS screen-recording permission. It captures the page content with helper overlays, not native dialogs or other windows.

- If the tab or app closes first, the recording finalizes itself; a later `stop-recording` returns it with `end_reason` `target_closed`.
- A recording keeps running if the agent run that started it is cancelled. Any later process can finish it with `stop-recording` for the same tab and endpoint, and stopping the app or closing the tab finalizes it.
- A dialog raised during a command is handled by that command (see "Page dialogs"). One raised between commands stays open for the app or a person; until it is answered, commands against that browser fail with `PAGE_BLOCKED`.
- Recording the user's own Chrome while its window is covered or minimized may freeze frames; isolated AutoByteus instances started by `pnpm isolated-app` keep rendering while covered.

## Page dialogs

Native page dialogs (`alert`, `confirm`, `prompt`, "Leave site?") raised by the page of the tab a command works on are handled by that command:

- Give the decision with the action: `run-script` or `navigate` with `--dialog accept` or `--dialog dismiss` (MCP: `dialog`), plus `--prompt-text` (MCP: `prompt_text`) for a prompt. An accepted prompt without text gets its default value. Prompts exist in browsers only; Electron apps such as AutoByteus do not implement `window.prompt()`. Pass it whenever the action is expected to ask, for example `run-script --tab-id "$TAB_ID" --script '__abDemo.click({text: "Delete"})' --dialog accept`.
- Without a decision, a `confirm`/`prompt`/"Leave site?" is dismissed only so the page is not left blocked, and the command fails with `DIALOG_DECISION_REQUIRED` carrying the dialog's type and message. Decide, then repeat the action with `--dialog`. Side effects that happened before the dialog may repeat.
- An `alert` is closed and reported; it needs no decision.
- Successful results list the command's own dialogs in `dialogs` (`type`, `message`, `default_value`, `outcome`, `decided_by`); without dialogs results are unchanged (in MCP results `dialogs` is absent or `null`).
- Commands without the option (`open-tab`, `read-page`, `screenshot`, `dom-snapshot`) fail with `DIALOG_DECISION_REQUIRED` if their page asks; trigger that page action through `run-script` or `navigate` with a decision instead.
- Dialogs in other tabs are never answered or reported. A dialog left open (another tab, or raised between commands) must be answered on screen: by the user, or with an OS-level screen-control (computer-use) tool where one is available. Until then commands fail with `PAGE_BLOCKED`. Headful Chrome and Electron keep such dialogs open; headless Chrome may cancel another tab's dialog when a command disconnects, and it has no window to answer in.
- Chrome shows "Leave site?" only for pages the user has interacted with. `close-tab` closes without that prompt.

## Output and recovery

Except for help, parse stdout as exactly one JSON value:

- Success: `{"schema_version":"1","ok":true,"command":"...","result":{...}}`
- Failure: `{"schema_version":"1","ok":false,"command":"...","error":{"code":"...","message":"...","retryable":...}}`

Treat stderr as diagnostics, not machine output. Recover by code:

- `BOOTSTRAP_FAILED`, `CONFIGURATION_ERROR`, `BROWSER_UNAVAILABLE`: check the diagnostic and retry only when the environment/browser condition can change.
- `PAGE_BLOCKED`: the browser is running but refused the connection within 8 s, most likely because a page dialog (alert/confirm/prompt/"Leave site?") waits for an answer, otherwise a hung page. `details.targets` lists the open tabs. Have the dialog answered in the window (by the user, or with an OS-level screen-control (computer-use) tool where one is available), then retry. A headless browser has no window: close that tab or restart the browser.
- `TAB_NOT_FOUND`: list tabs again; the target was closed or replaced.
- `NO_TAB_MATCH`: refine or correct discovery criteria.
- `AMBIGUOUS_TAB_MATCH`: add a more specific URL/title matcher.
- `INVALID_ARGUMENT`, `INVALID_URL`, `ARTIFACT_PATH_REJECTED`, `ARTIFACT_EXISTS`: correct the request; use a workspace-relative path and explicit `--overwrite` only when replacement is intended.
- `NAVIGATION_TIMEOUT`, `BROWSER_OPERATION_FAILED`: observe current tab state before deciding whether retry is safe.
- `SCRIPT_FAILED`: simplify/fix the script or return a JSON-serializable value. `details.detail` `presentation_helper_install_failed` means the page refused the helper.
- `DIALOG_DECISION_REQUIRED`: the page asked a question (`details.dialogs`); it was dismissed to unblock. Repeat the action through `run-script`/`navigate` with `--dialog accept` or `--dialog dismiss`.
- `RECORDING_DEPENDENCY_MISSING`: install `ffmpeg` or set `BROWSER_AUTOMATION_FFMPEG_BIN`.
- `RECORDING_ALREADY_ACTIVE`: stop the running recording of that tab first. `RECORDING_NOT_ACTIVE`: nothing to stop for that tab.
- `RECORDING_FAILED`: read `details` (`reason`, `partial_file`, `log_file`); a partial MP4 is kept when one was written.

## Safety

- Obtain normal confirmation before any consequential external side effect, including purchases, submissions, messages, account/security changes, or destructive actions.
- Treat `run-script` as advanced. Pass its script and structured argument directly with `--script` and `--arg-json` in normal use, then verify after execution.
- Keep screenshots and optional large results under the caller workspace. Absolute paths and escapes are rejected; existing files are preserved unless overwrite is explicit.
- Never attempt to terminate Chrome globally. The CLI deliberately exposes only single-tab close.
