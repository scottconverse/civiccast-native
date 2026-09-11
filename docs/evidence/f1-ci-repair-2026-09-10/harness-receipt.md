# Mutation child-harness local regression

Date: 2026-09-10. Base: `5bc57d7e5500e10465c413632c2ece3cce32bfec`.
These are local Windows dependency-isolation checks, not a mutation score.
The actual Linux mutmut baseline and mutation verdict remain pending PR CI.

The first CI cycle copied all of `tests/conftest.py` into a pytester child.
Its unrelated cache-reset autouse fixture imported instrumented application
code, which initialized mutmut from the child's temporary directory without
the generated project configuration. The child failed during setup, before
the intended state-guard teardown proof. See the raw first-cycle mutation log
and `../f1-local-2026-09-10/CI-RESULT.md` for the original traceback.

The regression rejects any `civiccast` application import in one child variant.
With the old full-conftest copy, the new variant fails in fixture setup:
`harness-red.txt` records 1 failed, 1 passed, 5 deselected (exit 1).
The correction imports only the actual `_hermetic_civiccast_state` fixture
from `tests.conftest`; it does not copy or replace the guard implementation.
The fake profile environment is set before that module captures real roots.
Other root fixtures remain unchanged for ordinary suite execution.

Both child variants still require exactly two passing calls plus one teardown
error naming the simulated real-state SQLite file. That proves redirected
writes succeed and the actual guard rejects an unmarked write to the fake real
profile. `harness-green.txt` records the full file: 7 passed (exit 0).

Commands, from the integration worktree with its existing Python 3.12.10 venv:

```powershell
$env:UV_PROJECT_ENVIRONMENT='.venv312'
uv run --frozen --no-sync pytest -q tests/test_hermetic_state_guard.py -k guard_fails
# Above: red before the correction; 1 failed, 1 passed, 5 deselected.
uv run --frozen --no-sync pytest -q tests/test_hermetic_state_guard.py
# Above: green after the correction; 7 passed.
```

Interpreter and source provenance are in `environment.txt`. Tests were
serialized with the other repair worktrees to avoid shared state collisions.
No installed station service or real operator-state write was requested.
