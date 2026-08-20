# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Guard: the two Alembic ``env.py`` copies must stay identical.

The repo carries two copies of the Alembic environment — ``alembic/env.py``
(the ``script_location`` the alembic.ini points at) and
``civiccast/alembic/env.py`` (the packaged copy). They are intentional
duplicates; any logic that lands in one (e.g. the ``alembic_version`` column
widen + schema bootstrap) must land in the other, or a migration that works in
one entry point silently breaks in the other. This test makes the duplication
self-policing until the copies are consolidated (audit ENG-007).
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ENV_A = _REPO_ROOT / "alembic" / "env.py"
_ENV_B = _REPO_ROOT / "civiccast" / "alembic" / "env.py"


def test_alembic_env_copies_are_identical() -> None:
    assert _ENV_A.exists(), f"missing {_ENV_A}"
    assert _ENV_B.exists(), f"missing {_ENV_B}"
    a = _ENV_A.read_text(encoding="utf-8")
    b = _ENV_B.read_text(encoding="utf-8")
    assert a == b, (
        "The two Alembic env.py copies have drifted. Any change to one "
        "(schema bootstrap, alembic_version width, version_locations) MUST be "
        "applied to both, or migrations break on one entry point. Reconcile "
        f"{_ENV_A.relative_to(_REPO_ROOT)} and {_ENV_B.relative_to(_REPO_ROOT)}."
    )
