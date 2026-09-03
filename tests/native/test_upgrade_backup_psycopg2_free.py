# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Regression: D3 step 3's DB layer must not need ``psycopg2`` (chain K, K1).

Live-proven defect, real hardware R7, 2026-08-01 (request 0053b,
``upgrade-journal.json``)::

    interlock_acquired -- D7a maintenance interlock acquired
    writers_drained    -- writers drained; quiescence verified
    rolled_back        -- rolled back after failure (No module named 'psycopg2');
                          junction/tree reverted (no DB mutation)

The step that was ATTEMPTED when that fired is the one right after
``writers_drained``: D3 step 3, ``BACKUP_VERIFIED``
(:func:`civiccast.native.upgrade.orchestrator._drive_forward`). Its production
seam is :func:`civiccast.native.upgrade.seams.default_backup`, which runs the
WS2 full backup (already normalized -- ``civiccast/dr/backup.py`` line ~617)
and THEN the restore-drill spot check
:func:`civiccast.dr.restore_drill.run_postgres_restore_drill`, whose FIRST
statement is ``create_engine(verify_source_url)`` on the raw, driver-less
``postgresql://`` URL the installer persists to
``HKLM\\SOFTWARE\\CivicCast\\Native\\DatabaseUrl``. SQLAlchemy resolves a
driver-less ``postgresql`` scheme to the **psycopg2** dialect and imports it at
ENGINE CONSTRUCTION -- and this product ships psycopg **v3** only (ADR 0008,
``psycopg[binary]>=3.2``; the built app-payload pack contains psycopg 3.3.4 +
psycopg_binary and no psycopg2 whatsoever).

``civiccast/db/url.py``'s docstring listed ``civiccast/dr/restore_drill.py`` as
"still out of scope ... operator/DR-drill only, not on the native
service/control-plane/installer path". That was wrong: D3 step 3 calls it on
every upgrade, before the mutation frontier. This module pins that it is on the
path AND that its DB layer resolves a shipped driver.

Import isolation: ``psycopg2`` is not installed in this venv either (see
``requirements-native-app.txt``), so the defect reproduces natively -- but these
tests install an explicit import block anyway so the proof does not silently
become a no-op on a developer machine that happens to have psycopg2 present.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from importlib.abc import MetaPathFinder
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from civiccast.dr import restore_drill
from civiccast.dr.models import BackupManifest
from civiccast.native.upgrade import seams as upgrade_seams
from civiccast.native.upgrade.models import UpgradeContext

#: The exact URL SHAPE the installer persists and hands the D3 engine: a
#: driver-less `postgresql://`. Port 1 is closed on every Windows host, so a
#: connect attempt is refused immediately -- these tests must fail on
#: DRIVER RESOLUTION or not at all, never on a network timeout.
_BARE_POSTGRES_URL = "postgresql://civiccast:secret@127.0.0.1:1/civiccast"

_PSYCOPG2_MISSING = "No module named 'psycopg2'"


class _BlockedModuleFinder(MetaPathFinder):
    """Raise ``ModuleNotFoundError`` for a module name and its submodules.

    Raising from ``find_spec`` (rather than returning ``None``) reproduces the
    EXACT exception type and message text R7 recorded, independently of
    whether the blocked distribution is installed in the running venv.
    """

    def __init__(self, blocked: str) -> None:
        self._blocked = blocked

    def find_spec(self, fullname: str, path: object = None, target: object = None) -> None:
        if fullname == self._blocked or fullname.startswith(f"{self._blocked}."):
            raise ModuleNotFoundError(f"No module named {fullname!r}", name=fullname)


@contextmanager
def _import_blocked(module_name: str) -> Iterator[None]:
    """Make ``module_name`` unimportable for the duration of the block."""

    finder = _BlockedModuleFinder(module_name)
    saved = {
        name: module
        for name, module in sys.modules.items()
        if name == module_name or name.startswith(f"{module_name}.")
    }
    for name in saved:
        del sys.modules[name]
    sys.meta_path.insert(0, finder)
    importlib.invalidate_caches()
    try:
        yield
    finally:
        sys.meta_path.remove(finder)
        sys.modules.update(saved)
        importlib.invalidate_caches()


def _postgres_manifest() -> BackupManifest:
    """The minimum manifest shape D3 step 3 hands the drill on the Postgres
    lane. Nothing in it is read before the drill's first ``create_engine``."""

    return BackupManifest(
        backup_id="pre-1.0.0-rc15",
        created_at=datetime.now(UTC),
        engine="postgres",
        db_artifact="civiccast.dump",
    )


def test_psycopg2_block_is_effective() -> None:
    """The block itself must work, or every assertion below is vacuous."""

    with _import_blocked("psycopg2"), pytest.raises(ModuleNotFoundError) as excinfo:
        importlib.import_module("psycopg2")
    assert _PSYCOPG2_MISSING in str(excinfo.value)


def test_shipped_psycopg_v3_is_importable() -> None:
    """The driver the product actually ships is present -- so a failure below
    is a wiring defect, not a missing dependency in this environment."""

    assert importlib.import_module("psycopg") is not None


def test_restore_drill_db_layer_runs_without_psycopg2(tmp_path: Path) -> None:
    """RED against the pre-fix tree: D3 step 3's restore drill must reach a
    real CONNECT failure, never a driver-import failure, when psycopg2 is
    absent.

    Pre-fix this raises ``ModuleNotFoundError: No module named 'psycopg2'``
    from ``create_engine`` -- exactly R7's journal entry. Post-fix the engine
    constructs against psycopg v3 and the first real DB touch fails with a
    refused connection, which is the honest outcome for an unreachable host.
    """

    with _import_blocked("psycopg2"), pytest.raises(Exception) as excinfo:
        restore_drill.run_postgres_restore_drill(
            backup_dir=tmp_path,
            manifest=_postgres_manifest(),
            source_database_url=_BARE_POSTGRES_URL,
        )

    raised = excinfo.value
    assert not isinstance(raised, ModuleNotFoundError), (
        f"D3 step 3's restore drill resolved the uninstalled psycopg2 dialect: {raised!r}"
    )
    assert _PSYCOPG2_MISSING not in str(raised)


def test_restore_drill_engines_name_the_shipped_driver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asserted at the engine boundary the ModuleNotFoundError comes from:
    every URL the drill hands ``create_engine`` must name a driver, and that
    driver must be the shipped psycopg v3. Independent of whether psycopg2
    happens to be installed, so this pin cannot go quiet."""

    captured: list[str] = []
    real_create_engine = restore_drill.create_engine

    def _spy(url: str, *args: object, **kwargs: object) -> object:
        captured.append(str(url))
        return real_create_engine(url, *args, **kwargs)

    monkeypatch.setattr(restore_drill, "create_engine", _spy)

    # The drill cannot COMPLETE against an unreachable host; what is under
    # test is only the URL each engine is built on, so any raise is expected
    # and is swallowed deliberately rather than asserted on here.
    with suppress(Exception):
        restore_drill.run_postgres_restore_drill(
            backup_dir=tmp_path,
            manifest=_postgres_manifest(),
            source_database_url=_BARE_POSTGRES_URL,
        )

    assert captured, "the drill built no engine at all -- the pin would be vacuous"
    for url in captured:
        assert make_url(url).get_driver_name() == "psycopg", (
            f"restore drill built an engine on {url!r}, which SQLAlchemy resolves "
            "to a driver this product does not ship"
        )


def test_restore_drill_normalization_preserves_the_credential(tmp_path: Path) -> None:
    """Normalization must not corrupt the connection credential -- a drill
    that names the right driver but cannot authenticate is a worse outcome
    than the bug it replaces (``civiccast/db/url.py`` makes the same point)."""

    normalized = make_url(restore_drill._verification_engine_url(_BARE_POSTGRES_URL))
    assert normalized.get_driver_name() == "psycopg"
    assert normalized.username == "civiccast"
    assert normalized.password == "secret"
    assert normalized.host == "127.0.0.1"
    assert normalized.port == 1
    assert normalized.database == "civiccast"


def test_d3_step_three_backup_seam_actually_reaches_the_restore_drill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole reason the drill matters: D3 step 3's production backup seam
    calls it. Without this pin, a future refactor could drop the spot check
    and leave the tests above passing while proving nothing about the upgrade
    path."""

    calls: list[str] = []

    def _fake_full_backup(**kwargs: object) -> BackupManifest:
        return _postgres_manifest()

    def _fake_drill(**kwargs: object) -> object:
        calls.append(str(kwargs["source_database_url"]))
        raise AssertionError("stop: the seam reached the drill")

    monkeypatch.setattr(upgrade_seams, "run_full_backup", _fake_full_backup)
    monkeypatch.setattr(upgrade_seams, "run_postgres_restore_drill", _fake_drill)
    # Gate A run 33681670855 fix (Fix A): _backup now reads the SOURCE
    # database's own current revision (to pass as run_postgres_restore_drill's
    # expected_revision -- the pre-upgrade drill's honest question, "does the
    # restore match what was dumped", not the DR-drill's "does it match
    # today's code") BEFORE calling the drill. That read goes through
    # civiccast.schema_check.read_db_revision, which this test's fake
    # unreachable _BARE_POSTGRES_URL would otherwise hang on for a real
    # bounded-connect timeout (see the module docstring on why port 1 does
    # not refuse immediately in every environment) -- fake it out too so this
    # stays a fast, network-free proof of "the seam reaches the drill".
    monkeypatch.setattr(
        "civiccast.schema_check.read_db_revision", lambda database_url: "fake-source-revision"
    )

    context = UpgradeContext(
        install_root=str(tmp_path / "install"),
        state_root=str(tmp_path / "state"),
        database_url=_BARE_POSTGRES_URL,
        owner_run_id="test-run",
    )
    backup = upgrade_seams.default_backup(context)

    with pytest.raises(AssertionError, match="the seam reached the drill"):
        backup(str(tmp_path / "backups" / "pre-1.0.0-rc15"))

    assert calls == [_BARE_POSTGRES_URL]
