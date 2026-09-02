# Browser Automation

`browser-automation/` is one relocatable browser-automation skill bundle. It contains the agent instructions, Bash launcher, locked Python runtime, task-oriented CLI, shared browser application core, and a retained thin MCP adapter.

For the reusable conversion convention behind this CLI, see [Argument-Isomorphic MCP-to-CLI Mapping](../docs/mcp-to-cli-mapping.md).

## Agent skill and CLI

At runtime, the agent receives and reads an exact locator for this bundle's `SKILL.md`. The committed skill names the launcher only as `scripts/browser`. The agent resolves that relative resource from the directory containing the exact advertised/read `SKILL.md`, then invokes the resolved launcher with Bash from its current task workspace. It passes `health-check` for preflight and `--help` or `<command> --help` for the command reference.

No framework-populated or persistent shell variable is required. The agent does not guess or scan for another bundle, change its shell working directory into this project, use a vendor-specific skill home, or register a PATH command. If the runtime does not expose an exact readable `SKILL.md` locator, this skill is unsupported in that runtime.

The launcher independently locates this bundle relative to itself, captures the caller workspace, and runs the lockfile with `uv run --frozen`. The first call prepares the environment automatically. No package installation or virtual-environment activation is part of the workflow.

Every non-help CLI result is one schema-v1 JSON value on stdout. Diagnostics use stderr. Stable exit categories are:

| Exit | Category |
| --- | --- |
| `0` | Success |
| `2` | Usage, validation, or artifact policy |
| `3` | Bootstrap, configuration, or browser connectivity |
| `4` | Tab discovery or stale target |
| `5` | Browser/application operation |

Use `list-tabs`, `attach-tab`, or `open-tab` to obtain an opaque browser-owned `tab_id`. Pass it explicitly to `navigate`, `read-page`, `screenshot`, `dom-snapshot`, `run-script`, or `close-tab`. IDs remain usable by later independent CLI processes while the Chrome target exists. There is no active-tab fallback, numeric alias registry, daemon, or global Chrome-close command.

For `run-script`, direct operation flags are the normal former-MCP-call mapping, including for nontrivial or multiline JavaScript:

```bash
bash "<resolved launcher>" run-script --tab-id "$TAB_ID" \
  --script '(arg) => ({title: document.title, label: arg.label})' \
  --arg-json '{"label":"direct"}'
```

`--script-file`, `--script-stdin`, and `--arg-file` are optional alternate sources only when input already resides there or a concrete shell/process limit prevents faithful argv transport. Complexity alone is not a reason to introduce file or stdin indirection.

Artifact and input paths are workspace-relative. The launcher captures the caller directory in `BROWSER_AUTOMATION_WORKSPACE` unless the caller already supplied an absolute existing workspace. Existing output files require `--overwrite`.

## Runtime model and support boundary

The CLI and retained MCP adapter both delegate to the same transport-neutral `BrowserApplication`. The owned `browser_automation.runtime` package acquires a per-port establishment gate before probing Chrome, attaches to a durable loopback CDP endpoint or launches one exact process group, and keeps new-launch ownership gated through Playwright connection and first-context validation. Each operation then resolves the explicit browser-owned target ID, performs one bounded operation, and disconnects its Playwright client without terminating promoted or pre-existing Chrome. Commands against the same tab should be serialized; explicit IDs prevent cross-tab ambiguity but do not impose an ordering on intentionally concurrent callers.

The supported first-release environment is a Bash-capable macOS or Linux agent host with local Chrome/Chromium over CDP. Native Windows shells, other browser engines, other agent-vendor loaders, additional Chrome/CDP version breadth, and intentionally concurrent same-tab workflows are not part of the validated baseline.

## Retained MCP adapter

MCP remains available as a thin adapter over the same `BrowserApplication`:

```json
{
  "mcpServers": {
    "browser": {
      "command": "/absolute/path/to/browser-automation/scripts/browser-mcp"
    }
  }
}
```

The wrapper self-locates and reserves stdout for JSON-RPC. The server defaults to stdio. Streamable HTTP defaults to loopback:

```bash
BROWSER_MCP_TRANSPORT=streamable-http \
BROWSER_MCP_HOST=127.0.0.1 \
BROWSER_MCP_PORT=8765 \
bash scripts/browser-mcp
```

An explicitly configured non-loopback host is accepted but emits a prominent warning: this adapter has no built-in authentication and must be protected by a trusted network or external boundary.

## Development checks

```bash
uv --directory browser-automation run --frozen --extra test python -m pytest
uv --directory browser-automation run --frozen python -m compileall -q src
```

The default pytest run includes unit/adapter coverage and Chrome-free process integrations; scenarios that require a local browser are intentionally skipped. To run the complete real-Chrome integration suite:

```bash
BROWSER_AUTOMATION_REAL_TESTS=1 \
  uv --directory browser-automation run --frozen --extra test python -m pytest tests/integration
```

Chrome/Chromium over CDP is the supported browser runtime. If the browser runtime launches Chrome 136+, configure a non-default `CHROME_USER_DATA_DIR`. For an already-running browser container, configure its `CHROME_REMOTE_DEBUGGING_PORT` and do not replace its profile.

Owned-launch configuration also supports `CHROME_PROFILE_DIRECTORY`, `CHROME_LOG_PATH`, and an explicit executable through `BROWSER_AUTOMATION_CHROME_BIN`. Otherwise, the runtime discovers common supported macOS/Linux Chrome or Chromium executables deterministically. The runtime never enumerates or globally terminates browser processes; a failed pending launch can terminate and reap only its exact owned process group.
