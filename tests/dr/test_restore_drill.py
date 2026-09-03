# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""The 0.5.0 gate: restore into a fresh database and prove it, including falsification.

TDD note: :func:`test_restore_drill_catches_a_dropped_row` is the
falsification pass the dev-rigor loop requires — it proves the comparison
logic actually fails when the data is wrong, not just that it reports
"passed" unconditionally.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from civiccast import schema_check
from civiccast.dr.backup import build_sqlite_engine, run_full_backup
from civiccast.dr.restore_drill import run_sqlite_restore_drill


def test_restore_drill_passes_against_an_untouched_backup(
    seeded_station_db: Path, tmp_path: Path
) -> None:
    manifest = run_full_backup(
        database_url=f"sqlite:///{seeded_station_db}", dest_dir=tmp_path / "backup"
    )
    report = run_sqlite_restore_drill(
        backup_dir=tmp_path / "backup", manifest=manifest, work_dir=tmp_path / "restore"
    )

    assert report.ok, report.errors
    assert report.schema_ok
    assert report.db_revision == schema_check.expected_migration_head()
    assert report.app_store_reads["assets"] == 2
    assert report.app_store_reads["egress_configs"] == 1
    matched_names = {t.name for t in report.tables if t.matched}
    assert {"assets", "schedule_items", "egress_configs"} <= matched_names


def test_restore_drill_catches_a_dropped_row(seeded_station_db: Path, tmp_path: Path) -> None:
    """FALSIFICATION: corrupt the backup artifact, and the drill MUST fail."""

    manifest = run_full_backup(
        database_url=f"sqlite:///{seeded_station_db}", dest_dir=tmp_path / "backup"
    )
    # Watch it fail first: tamper with the *backed-up* artifact (simulating a
    # backup that silently lost a row) and confirm the comparison notices.
    engine = build_sqlite_engine(tmp_path / "backup" / manifest.db_artifact)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM assets WHERE asset_id = 'council-meeting-0'"))
    engine.dispose()

    report = run_sqlite_restore_drill(
        backup_dir=tmp_path / "backup", manifest=manifest, work_dir=tmp_path / "restore"
    )

    assert not report.ok
    assets_result = next(t for t in report.tables if t.name == "assets")
    assert not assets_result.matched
    assert assets_result.actual_row_count == 1
    assert assets_result.expected_row_count == 2


def test_restore_drill_catches_a_stale_schema(seeded_station_db: Path, tmp_path: Path) -> None:
    """FALSIFICATION: a backup artifact stamped at an older migration must fail schema_ok."""

    manifest = run_full_backup(
        database_url=f"sqlite:///{seeded_station_db}", dest_dir=tmp_path / "backup"
    )
    artifact = tmp_path / "backup" / manifest.db_artifact
    engine = build_sqlite_engine(artifact)
    with engine.begin() as conn:
        conn.execute(text("UPDATE alembic_version SET version_num = 'not-a-real-revision'"))
    engine.dispose()

    report = run_sqlite_restore_drill(
        backup_dir=tmp_path / "backup", manifest=manifest, work_dir=tmp_path / "restore"
    )

    assert not report.ok
    assert not report.schema_ok
    assert report.db_revision == "not-a-real-revision"


def test_restore_drill_uses_a_fresh_file_never_the_original(
    seeded_station_db: Path, tmp_path: Path
) -> None:
    """The restore target must be a brand-new path, never the source db."""

    manifest = run_full_backup(
        database_url=f"sqlite:///{seeded_station_db}", dest_dir=tmp_path / "backup"
    )
    original_bytes = seeded_station_db.read_bytes()
    run_sqlite_restore_drill(
        backup_dir=tmp_path / "backup", manifest=manifest, work_dir=tmp_path / "restore"
    )
    # The original station db must be byte-identical after the drill — the
    # drill only ever reads it (via the backup step), never writes it.
    assert seeded_station_db.read_bytes() == original_bytes
    restored_files = list((tmp_path / "restore").glob("restored-*.sqlite3"))
    assert len(restored_files) == 1
    assert restored_files[0] != seeded_station_db


# ---------------------------------------------------------------------------
# <installer-path-audit MA-11 / MA-10> The verdict must not be vacuous.
# ---------------------------------------------------------------------------


def test_a_drill_that_compared_zero_tables_is_never_ok() -> None:
    """``all(t.matched for t in [])`` is True.

    ``_table_results`` returns ``[]`` whenever both sides are empty, and every
    Postgres cross-check hardcodes ``schema="civiccast"`` -- so a
    schema-resolution regression empties both, ``[] == []`` "passes",
    ``report.py`` prints "confirmed every row came back exactly as it was",
    and ``installer/service.py`` summarises "0 tables verified,
    schema_ok=True".
    """
    from datetime import UTC, datetime

    from civiccast.dr.models import RestoreDrillReport

    empty = RestoreDrillReport(
        backup_id="b",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        schema_ok=True,
        db_revision="0087_head",
        expected_head="0087_head",
        tables=[],
        errors=[],
    )
    assert empty.ok is False, "a comparison over zero tables proves nothing"


def test_the_sqlite_manifest_snapshot_is_taken_from_the_source_database(
    seeded_station_db, tmp_path
) -> None:
    """<installer-path-audit MA-10> The manifest used to be snapshotted from
    the ARTIFACT, and the drill then copies that same artifact and
    re-snapshots it -- so the whole comparison was
    artifact-vs-copy-of-artifact and could never see a backup that diverged
    from the live database.

    Proven by making the two differ: the manifest must describe the SOURCE.
    """
    import civiccast.dr.backup as backup_module

    real_backup = backup_module.run_sqlite_backup

    def _lossy_backup(*, db_path, dest_dir):  # type: ignore[no-untyped-def]
        artifact = real_backup(db_path=db_path, dest_dir=dest_dir)
        # A "copy" that silently lost every row -- the exact class of failure
        # (partial page copy / wrong source / schema_translate_map regression)
        # the drill exists to catch.
        import sqlite3

        connection = sqlite3.connect(str(artifact))
        try:
            names = [
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name != 'alembic_version'"
                )
            ]
            for name in names:
                connection.execute(f'DELETE FROM "{name}"')  # nosec B608
            connection.commit()
        finally:
            connection.close()
        return artifact

    backup_module.run_sqlite_backup = _lossy_backup  # type: ignore[assignment]
    try:
        manifest = run_full_backup(
            database_url=f"sqlite:///{seeded_station_db}",
            dest_dir=tmp_path / "backup",
            media_root=None,
        )
    finally:
        backup_module.run_sqlite_backup = real_backup  # type: ignore[assignment]

    assert any(table.row_count > 0 for table in manifest.tables), (
        "the manifest must describe the SOURCE's real rows; snapshotting the emptied "
        "artifact would record zeroes and the drill would then 'confirm' them"
    )
