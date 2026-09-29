# Argument-Isomorphic MCP-to-CLI Mapping

Use **argument-isomorphic MCP-to-CLI mapping**—plainly, **direct MCP-argument-to-CLI-option mapping**—when converting an MCP capability into a task-oriented command-line interface.

The rule is:

1. Map the MCP tool/function name to a CLI subcommand, normally from `snake_case` to `kebab-case`.
2. Map each MCP argument name to a named CLI option, normally from `snake_case` to `--kebab-case`.
3. Pass the MCP argument value as that option's value, using strict JSON for structured values.

This preserves the operation's public meaning without inserting a generic MCP, JSON-RPC, request-envelope, or `call-tool` layer. The repository's [Browser Automation](../browser-automation/README.md) implementation is the concrete reference, but the practice is intended for future MCP-to-CLI conversions.

## Terminology

Use these terms precisely when designing and reviewing a CLI:

| Term | Meaning | Browser example |
| --- | --- | --- |
| Executable / launcher | The program or script the shell starts. | `bash "<resolved-launcher>"` |
| Command / invocation | The complete executable-plus-arguments operation. “Command” is sometimes also used informally for the executable; prefer “invocation” when ambiguity matters. | `bash "<resolved-launcher>" list-tabs` |
| Subcommand | The operation selector immediately under the CLI. | `run-script`, mapped from MCP `run_script` |
| Option | A named command-line argument that takes an option value. | `--tab-id "ABC123"` |
| Option value | The value associated with an option. | `"ABC123"` for `--tab-id` |
| Flag | A value-less switch whose presence selects a boolean behavior. | `--overwrite` |
| `argv` / command-line arguments | The tokenized arguments supplied to the process. All tokens after the executable are command-line arguments/`argv` entries; process APIs commonly also expose the executable as `argv[0]`. | `run-script`, `--tab-id`, `ABC123`, `--script`, and the script value are distinct tokens. |

Do not call every named token a flag. `--overwrite` is a flag because it has no following value. `--tab-id` is an option and `ABC123` is its option value.

## Mapping Rules

### 1. Preserve the MCP contract

Preserve each input's:

- required or optional status;
- scalar, structured, enum, or boolean type;
- default value;
- mutual-exclusion and dependency rules;
- validation bounds; and
- stable semantic meaning.

A CLI adapter may improve shell ergonomics, but it must not silently change the operation. If the MCP requires explicit tab identity, for example, the CLI must not invent an implicit active-tab default.

### 2. Map names directly

Use predictable spelling unless a reviewed product vocabulary requires otherwise:

| MCP surface | CLI surface |
| --- | --- |
| `run_script` | `run-script` |
| `attach_tab` | `attach-tab` |
| `start_recording` | `start-recording` |
| `tab_id` | `--tab-id` |
| `url_contains` | `--url-contains` |
| `title_contains` | `--title-contains` |
| `output_file` | `--output-file` |

Keep one operation-specific option per supported argument. Do not collapse ordinary inputs into an opaque generic request object.

### 3. Pass scalar values directly

Strings, integers, finite numbers, and enum values normally become one option value:

```text
MCP: navigate_to(tab_id="ABC123", url="https://example.com", timeout_ms=60000)
CLI: navigate --tab-id "ABC123" --url "https://example.com" --timeout-ms 60000
```

The CLI parser and application boundary must still validate the value and preserve the MCP default when the optional option is omitted.

### 4. Pass structured values as strict JSON

Use a clearly named option such as `--arg-json`, `--config-json`, or another domain-specific `--*-json` name. The option value must be strict JSON, not a Python literal or shell-specific pseudo-object.

```text
MCP argument: arg={"x": 4}
CLI option:   --arg-json '{"x":4}'
```

Reject non-JSON values such as `NaN` and infinities when the public contract promises strict JSON.

### 5. Use direct `argv` by default

Direct option values are the normal agent path, including nontrivial, long, or multiline JavaScript. Complexity alone is not a reason to introduce a temporary file, stdin pipeline, environment variable, or generic payload.

File or stdin alternatives may exist as **optional input sources** when:

- the content already exists in that source; or
- a concrete operating-system, shell, or process-length limit prevents faithful direct `argv` transport.

When alternatives exist, make them explicitly mutually exclusive with the direct option and keep their decoded semantics identical. For example, `--script`, `--script-file`, and `--script-stdin` are alternate sources for one `script` argument; they are not different operations.

### 6. Map booleans deliberately

A boolean that defaults to `false` may map naturally to a value-less flag such as `--overwrite`. If both `true` and `false` must be selected explicitly, or omission differs from `false`, use a reviewed pair such as `--feature` / `--no-feature` or a typed option value. Preserve the original default and avoid ambiguous presence semantics.

### 7. Keep the output contract separate

Input mapping does not define output transport. For automation-oriented CLIs, every non-help invocation should independently return one strict, machine-readable JSON envelope on stdout, with diagnostics on stderr and stable exit categories.

Browser Automation uses:

```json
{"schema_version":"1","ok":true,"command":"run-script","result":{}}
```

or:

```json
{"schema_version":"1","ok":false,"command":"run-script","error":{"code":"SCRIPT_FAILED","message":"...","retryable":false}}
```

Human-readable help is a separate exception.

## Canonical Browser Examples

### `run_script`

Canonical mapping:

```text
MCP: run_script(tab_id="ABC123", script="(arg) => arg.x + 1", arg={"x":4})
CLI: bash "<resolved-launcher>" run-script --tab-id "ABC123" --script '(arg) => arg.x + 1' --arg-json '{"x":4}'
```

Mapping table:

| MCP element | CLI element |
| --- | --- |
| Tool `run_script` | Subcommand `run-script` |
| Argument `tab_id` | Option `--tab-id` |
| Value `"ABC123"` | Option value `"ABC123"` |
| Argument `script` | Option `--script` |
| JavaScript string | One directly quoted option value |
| Structured argument `arg` | Option `--arg-json` |
| Object `{"x":4}` | One strict-JSON option value |

The reviewed Browser Automation agent procedure uses this direct form even for nontrivial or multiline JavaScript. Its `--script-file`, `--script-stdin`, and `--arg-file` forms remain optional sources, not the normal complexity path.

### `attach_tab`

```text
MCP: attach_tab(url_contains="example.com", title_contains="Dashboard")
CLI: bash "<resolved-launcher>" attach-tab --url-contains "example.com" --title-contains "Dashboard"
```

Both optional match arguments remain optional named options. The operation's stable semantics still require the supplied criteria to identify exactly one tab; the CLI must not choose arbitrarily when multiple tabs match.

### Boolean flag

```text
MCP: screenshot(tab_id="ABC123", output_file="artifacts/page.png", overwrite=true)
CLI: bash "<resolved-launcher>" screenshot --tab-id "ABC123" --output-file "artifacts/page.png" --overwrite
```

Here `--overwrite` is a value-less boolean flag. `--tab-id` and `--output-file` are options with option values.

## Shell-Quoting Guidance

Shell quoting is a transport concern: it must preserve one intended value as one `argv` token.

- In Bash and other POSIX-like shells, single quotes are usually the safest wrapper for literal JavaScript or JSON because the shell performs no variable, command, wildcard, or backslash expansion inside them.
- Use double quotes for ordinary values when intentional shell-variable expansion is needed, such as `--tab-id "$TAB_ID"`.
- JSON uses double quotes internally, so a single-quoted outer shell value is normally clear: `--arg-json '{"x":4}'`.
- Never leave JSON, JavaScript, URLs containing shell metacharacters, or user-derived strings unquoted.
- A literal single quote cannot appear inside one POSIX single-quoted segment. Close and reopen the quoted string with an escaped quote (for example, `'before'"'"'after'`) or use another shell-safe construction that still produces exactly one option value.
- For multiline text, a quoted string may contain literal newlines. Verify the resulting token rather than switching to a file merely because the content spans lines.
- When invoking a process through an API that accepts an argument array, pass the token list directly instead of first rebuilding a shell command string.

Quoting must not alter the semantic mapping. The option value received by the CLI must equal the intended MCP argument value after decoding.

## Rejected Normal Forms

Do not make any of these the standard CLI:

```text
browser call-tool run_script --payload '{"tab_id":"ABC123","script":"...","arg":{"x":4}}'
browser invoke --request-json '{"method":"run_script","params":{...}}'
browser json-rpc --message '{"jsonrpc":"2.0",...}'
```

These approaches:

- reproduce the transport protocol instead of exposing a task-oriented CLI;
- hide required/optional inputs and defaults from normal CLI help;
- force callers to construct a second generic envelope;
- weaken shell completion, validation, and error locality; and
- encourage duplicated MCP-specific logic rather than a shared application boundary.

A retained MCP adapter and a CLI should call the same transport-neutral application/service owner. The CLI should not call MCP or JSON-RPC internally.

## Review And Test Checklist

For each conversion, verify:

- [ ] Every approved MCP tool has an explicit disposition: direct subcommand, intentionally retained only in MCP, combined for a documented reason, or not converted.
- [ ] Tool and argument names map predictably to the task subcommand and named options.
- [ ] Required/optional status, types, defaults, enums, bounds, dependencies, and mutual exclusivity are preserved.
- [ ] Scalars travel directly as option values.
- [ ] Structured values use strict JSON through a clearly named option.
- [ ] Nontrivial and multiline direct values are tested through actual process `argv`.
- [ ] Optional file/stdin modes are source alternatives, not the default complexity path.
- [ ] Boolean flags preserve default and presence semantics.
- [ ] Help exposes the real task surface without a generic `call-tool`/payload normal form.
- [ ] CLI and MCP delegate to one transport-neutral application/service boundary.
- [ ] Non-help output is exactly one strict machine-readable envelope; stderr and exit categories are stable.
- [ ] Process-level tests cover quoting, invalid strict JSON, missing required options, defaults, mutual exclusion, and representative success/failure results.
- [ ] Fresh-agent validation confirms that an agent can discover help, build the direct invocation, parse output, recover, and clean up without undocumented setup or indirection.

## When Direct Mapping Is Not Enough

Argument-isomorphic mapping is the preferred input design when the MCP operation has a coherent one-shot CLI meaning. Do not force it mechanically when the MCP capability fundamentally depends on server-held sessions, streaming, sampling, elicitation, progress channels, or other transport-only behavior. In that case, design an explicit task-oriented CLI lifecycle or retain the MCP surface; do not disguise the mismatch behind a generic request payload.
