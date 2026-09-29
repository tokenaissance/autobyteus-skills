# Implementation Progress

- [x] Remove fallback resolver behavior (`active` + `ephemeral`).
- [x] Make stateful tools require explicit `tab_id`.
- [x] Tighten typed results (`tab_id` non-optional).
- [x] Update docs (README + server instruction string).
- [x] Update server/unit tests.
- [x] Update real integration tests.
- [x] Run verification suites.

## Verification Results
- `pytest -q tests/test_server.py` -> pass (`10 passed`).
- `CHROME_REMOTE_DEBUGGING_PORT=9227 pytest -q tests/test_integration_real.py -rs` -> pass (`9 passed`).
- `CHROME_REMOTE_DEBUGGING_PORT=9227 pytest -q tests/test_server.py tests/test_integration_real.py -rs` -> pass (`19 passed`).
