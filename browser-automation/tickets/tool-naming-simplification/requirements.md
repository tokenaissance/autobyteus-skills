# Requirements - Tool Naming Simplification

## Version History
- v0: Initial snapshot from user request and current code scan.
- v1: Design-ready requirements after understanding pass.

## Goal / Problem Statement
Remove redundant browser MCP tool naming and remove all backward-compatibility paths. Keep only concise, canonical tool names.

## In-Scope Use Cases
1. As an MCP client, I can call `read_page` to read page content.
2. As an MCP client, I can call `screenshot` to save a page image.
3. As an MCP client, I can call `dom_snapshot` to get structured DOM elements.
4. As a maintainer, I can run tests/docs without legacy alias references.

## Acceptance Criteria
1. Tool registry exposes `read_page`, `screenshot`, `dom_snapshot` and does not expose `read_webpage`, `take_webpage_screenshot`, `take_webpage_dom_snapshot`.
2. Legacy alias handlers are removed from implementation.
3. Legacy shim modules are removed.
4. Unit tests pass with new tool names only.
5. Integration tests and README examples use new names only.
6. No compatibility wrappers or fallback code remains for old names.

## Constraints / Dependencies
- Keep existing behavior and payload shapes for canonical tools.
- Keep change limited to browser-mcp package.
- Test execution is local using `uv run pytest`.

## Assumptions
- Breaking change is intentional and accepted by user.
- No external requirement to keep old tool names.

## Open Questions / Risks
- External clients using old names will break immediately after deployment.
- This task does not include client migration tooling.

## Scope Triage
- Classification: Small.
- Rationale: Limited surface area (tool registration, three tool modules, tests, README) with no data model or architecture expansion.
