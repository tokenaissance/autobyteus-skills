# Implementation Plan

## Scope
Small

## Work Items
1. Remove active/ephemeral fallback logic from tab resolution layer.
2. Tighten tool signatures to require `tab_id` for stateful operations.
3. Update output types to use non-optional `tab_id`.
4. Update server instruction string and README examples.
5. Update unit/server tests to strict contract and error assertions for missing `tab_id`.
6. Update real integration tests to explicit `tab_id` usage in all stateful calls.
7. Run verification suites.

## Verification Strategy
1. `tests/test_server.py` should pass.
2. `tests/test_integration_real.py` should pass against `CHROME_REMOTE_DEBUGGING_PORT=9227`.
3. Combined suite should pass in a single run to catch order-dependent issues.
