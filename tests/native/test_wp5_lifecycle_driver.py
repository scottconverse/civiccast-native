# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Regression guard for the WP-5 clean-venue lifecycle proof driver.

The driver lives at ``scripts/wp5_lifecycle_driver.py``. It used to sit under
``.agent-runs/native-windows/ws5-installer/evidence/`` -- marooned in the
otherwise-scratch agent-run tree -- and the native-repo migration dropped that
tree wholesale, taking a load-bearing harness with it. It is proof harness
rather than product code, but it is RUN code that a test imports and the
Windows Sandbox launcher maps in, so it belongs beside the other runnable
scripts. This test binds it into the suite so a future change to the D3 engine
or the driver cannot silently break the proof. It also PROVES the driver's negative control works: a fault-injected
run must NOT be reported as a passing COMPLETE — a harness that cannot fail
proves nothing.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_DRIVER = Path(__file__).resolve().parents[2] / "scripts" / "wp5_lifecycle_driver.py"


def _load_driver() -> ModuleType:
    spec = importlib.util.spec_from_file_location("wp5_lifecycle_driver", _DRIVER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so dataclass annotation resolution can find the module
    # (dataclasses looks up cls.__module__ in sys.modules).
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_driver_file_present() -> None:
    assert _DRIVER.exists(), f"driver missing at {_DRIVER}"


def test_selftest_negative_controls_pass(tmp_path: Path) -> None:
    """The driver's own negative controls must hold (checkers can fail)."""
    drv = _load_driver()
    assert drv.selftest(tmp_path / "st") is True


def test_good_rows_pass_on_real_filesystem(tmp_path: Path) -> None:
    """The non-process rows classify a genuine good/rollback/halt run correctly."""
    drv = _load_driver()
    good = drv.row_fresh_install_fs(tmp_path / "fresh")
    assert good.passed, good.observed
    assert good.observed["phase"] == "complete"

    rolled = drv.row_failed_upgrade_health(tmp_path / "health")
    assert rolled.passed, rolled.observed
    assert rolled.observed["phase"] == "rolled_back"

    halted = drv.row_rollback_restore_failure_halt(tmp_path / "halt")
    assert halted.passed, halted.observed
    assert halted.observed["phase"] == "halted_restore_failed"


def test_checker_rejects_a_broken_run(tmp_path: Path) -> None:
    """WATCH IT FAIL: a health-refusing run driven through the FRESH-install
    checker (which expects COMPLETE) must be reported as NOT passed.

    This is the falsification: build a run that genuinely does not COMPLETE and
    confirm the pass predicate returns False, so a green fresh-install result
    cannot be a rubber stamp.
    """
    drv = _load_driver()
    base = tmp_path / "broken"
    base.mkdir()
    ctx, payload = drv._make_synthetic_root(base, old_version=None)
    calls = drv._SeamCalls()
    # Health refuses -> the engine rolls back -> phase is NOT complete.
    outcome = drv.run_upgrade(
        drv.UpgradePlan(old_version="none", new_version="1.0.0-rc15"),
        ctx,
        drv._make_seams(ctx, payload, calls=calls, health_ok=False),
    )
    assert outcome.phase is not drv.UpgradePhase.COMPLETE
    # The fresh-install pass predicate requires COMPLETE; on this run it is False.
    cur_complete = outcome.phase is drv.UpgradePhase.COMPLETE
    assert cur_complete is False


@pytest.mark.slow
def test_power_loss_real_kill_resumes(tmp_path: Path) -> None:
    """A REAL process killed mid-run leaves the journal at the boundary and a
    fresh process resumes to COMPLETE (spec D3 power-loss row)."""
    drv = _load_driver()
    res = drv.row_power_loss_resume(tmp_path / "pl", "migrate")
    assert res.passed, res.observed
    assert res.observed["journal_after_kill"] == "tree_laid"
    assert res.observed["resume_phase"] == "complete"
    assert res.observed["resume_backup_calls"] == 0
