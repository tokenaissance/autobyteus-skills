---
name: browser-automation
description: Operate a local Chrome/Chromium session through the bundled browser CLI for explicit-tab navigation, authenticated-page inspection, DOM observation, JavaScript interaction, screenshots, and multi-step browser workflows. Use when an agent must act in or inspect a live browser, especially existing signed-in tabs. Do not use for generic web research or ordinary URL lookup when a non-browser web tool is sufficient.
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

For exact flags, invoke the resolved launcher with `--help` or with a command followed by `--help`. Core commands are `list-tabs`, `attach-tab`, `open-tab`, `close-tab`, `navigate`, `read-page`, `screenshot`, `dom-snapshot`, and `run-script`.

Map script calls directly to operation flags. The normal form is `run-script --tab-id "$TAB_ID" --script '(arg) => ({title: document.title, label: arg.label})' --arg-json '{"label":"direct"}'`. This preserves `run_script(tab_id, script, arg)` without a generic payload or temporary indirection. `--script-file`, `--script-stdin`, and `--arg-file` remain optional when the content already exists in a file/stdin or a concrete shell/process limit prevents faithful argv transport. Do not choose an alternate source merely because JavaScript is nontrivial, long, multiline, or complex.

## Output and recovery

Except for help, parse stdout as exactly one JSON value:

- Success: `{"schema_version":"1","ok":true,"command":"...","result":{...}}`
- Failure: `{"schema_version":"1","ok":false,"command":"...","error":{"code":"...","message":"...","retryable":...}}`

Treat stderr as diagnostics, not machine output. Recover by code:

- `BOOTSTRAP_FAILED`, `CONFIGURATION_ERROR`, `BROWSER_UNAVAILABLE`: check the diagnostic and retry only when the environment/browser condition can change.
- `TAB_NOT_FOUND`: list tabs again; the target was closed or replaced.
- `NO_TAB_MATCH`: refine or correct discovery criteria.
- `AMBIGUOUS_TAB_MATCH`: add a more specific URL/title matcher.
- `INVALID_ARGUMENT`, `INVALID_URL`, `ARTIFACT_PATH_REJECTED`, `ARTIFACT_EXISTS`: correct the request; use a workspace-relative path and explicit `--overwrite` only when replacement is intended.
- `NAVIGATION_TIMEOUT`, `BROWSER_OPERATION_FAILED`: observe current tab state before deciding whether retry is safe.
- `SCRIPT_FAILED`: simplify/fix the script or return a JSON-serializable value.

## Safety

- Obtain normal confirmation before any consequential external side effect, including purchases, submissions, messages, account/security changes, or destructive actions.
- Treat `run-script` as advanced. Pass its script and structured argument directly with `--script` and `--arg-json` in normal use, then verify after execution.
- Keep screenshots and optional large results under the caller workspace. Absolute paths and escapes are rejected; existing files are preserved unless overwrite is explicit.
- Never attempt to terminate Chrome globally. The CLI deliberately exposes only single-tab close.
