# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""F-1: reject a commit without transaction-specific preroll evidence."""

import pytest

from scripts.ops.check_reload_preroll import check_log

_HELD = "CTRL reload: new leg stream held at its first buffer (0 stream(s) still to preroll) (reload_id=1)"
_READY = "CTRL reload: new leg preroll verified (reload_id=1) held_streams=2"
_FIRE = "CTRL reload: firing (reload_id=1)"
_COMMIT = "CTRL reload committed (elements=146)"


def test_held_and_unheld_preroll_proof() -> None:
    for lines in ([_HELD, _READY, _FIRE, _COMMIT], [_READY.replace("=2", "=0"), _FIRE, _COMMIT]):
        assert check_log("\n".join(lines), 146) == (1, [])


@pytest.mark.parametrize(
    "lines",
    [
        [_COMMIT],
        [_READY, _FIRE, _COMMIT],
        [_HELD, _READY, _FIRE.replace("=1", "=2"), _COMMIT],
        [_HELD, _READY, _FIRE, _COMMIT, _COMMIT],
        [_HELD, _READY, "WORKER_RESULT {'error': None}", _FIRE, _COMMIT],
        [_HELD, _READY, _FIRE, _COMMIT.replace("146", "56")],
        [],
    ],
)
def test_missing_stale_reused_or_undersized_proof_fails(lines: list[str]) -> None:
    assert check_log("\n".join(lines), 146)[1]
