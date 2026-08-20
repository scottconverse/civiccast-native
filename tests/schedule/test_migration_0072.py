# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Migration 0072 repairs rc16 ``file://``-registered recording assets.

Drives the real migration through Alembic against a real sqlite fixture DB
(not ``create_all`` -- that would build the *current* ORM schema and never
prove ``0072`` itself does anything) seeded with the exact rc16-shaped bad
row the D3 brief describes: an ``assets.file_path`` written as a
``file://`` URI, with a real file on disk at the path it encodes.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

_PARENT_REVISION = "0071_published_blocks_overlap"
_REVISION = "0072_normalize_recording_file_uris"


def _cfg(url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _seed_asset(
    url: str,
    *,
    asset_id: str,
    file_path: str | None,
    file_status: str = "ok",
) -> None:
    engine = create_engine(url, future=True)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO assets (asset_id, title, state, file_path, file_status) "
                    "VALUES (:asset_id, :title, :state, :file_path, :file_status)"
                ),
                {
                    "asset_id": asset_id,
                    "title": "Private first-broadcast rehearsal",
                    "state": "recorded",
                    "file_path": file_path,
                    "file_status": file_status,
                },
            )
    finally:
        engine.dispose()


def _asset_row(url: str, asset_id: str) -> dict[str, object]:
    engine = create_engine(url, future=True)
    try:
        with engine.connect() as conn:
            row = (
                conn.execute(
                    text(
                        "SELECT file_path, file_status, file_status_checked_at "
                        "FROM assets WHERE asset_id = :asset_id"
                    ),
                    {"asset_id": asset_id},
                )
                .mappings()
                .one()
            )
        return dict(row)
    finally:
        engine.dispose()


def test_migration_0072_repairs_a_real_file_uri_row_and_clears_missing_status(
    tmp_path: Path,
) -> None:
    """The rc16-shaped bad row: file:// path to a file that IS on disk.

    This is the exact rc16 symptom the brief describes -- "file created,
    endpoint returned success, reload showed missing" -- captured as a
    fixture row with ``file_status='missing'``.
    """
    recording = tmp_path / "recordings" / "rehearsal-abc123.mp4"
    recording.parent.mkdir(parents=True)
    recording.write_bytes(b"rc16 recording bytes")

    url = f"sqlite:///{tmp_path / 'm0072_repair.sqlite'}"
    cfg = _cfg(url)
    command.upgrade(cfg, _PARENT_REVISION)
    _seed_asset(
        url,
        asset_id="rehearsal-abc123",
        file_path=recording.as_uri(),
        file_status="missing",
    )

    command.upgrade(cfg, _REVISION)

    row = _asset_row(url, "rehearsal-abc123")
    assert row["file_path"] == str(recording)
    assert row["file_status"] == "ok"
    assert row["file_status_checked_at"] is not None


def test_migration_0072_normalizes_windows_drive_letter_file_uris(tmp_path: Path) -> None:
    """A ``file:///C:/...`` URI (Windows) must not gain a stray leading slash.

    ``urlsplit`` reads the path component of ``file:///C:/x`` as
    ``/C:/x`` -- naively passing that straight to ``Path()`` produces an
    invalid path on Windows. This is this product's primary deployment
    target, so the migration's own URI parser must handle it, independent
    of whatever helper the reference PR shipped.
    """
    # CLEANROOM FIX (caught by the Linux full-install gate): the first
    # version of this test derived its "Windows-style" URI from tmp_path,
    # which on a POSIX runner degenerates into an ordinary POSIX file URI
    # whose correct normalization DOES start with "/" -- the assertion was
    # platform-dependent, not the migration. A true drive-letter URI is
    # hardcoded so the scenario is identical on every OS. The file does not
    # exist on any runner, so this also pins the repair-path-only behavior:
    # file_path is normalized while file_status stays untouched (the
    # media-integrity worker owns that column when the file is absent).
    windows_style_uri = "file:///C:/recordings/council-2026-07-01.mp4"
    expected_path = str(Path("C:/recordings/council-2026-07-01.mp4"))

    url = f"sqlite:///{tmp_path / 'm0072_windows.sqlite'}"
    cfg = _cfg(url)
    command.upgrade(cfg, _PARENT_REVISION)
    _seed_asset(
        url,
        asset_id="council-2026-07-01",
        file_path=windows_style_uri,
        file_status="missing",
    )

    command.upgrade(cfg, _REVISION)

    row = _asset_row(url, "council-2026-07-01")
    assert row["file_path"] == expected_path
    assert not str(row["file_path"]).startswith("/")
    assert row["file_status"] == "missing"


def test_migration_0072_repairs_path_but_leaves_status_when_file_is_absent(
    tmp_path: Path,
) -> None:
    """A file:// row whose backing file is genuinely gone: path is still
    normalized (so a relink / the next integrity scan has a real path to
    check), but the migration does not claim ``ok`` for a file it can't
    see -- ``file_status`` is left for the real integrity-scan worker to
    own, matching the module docstring's contract."""
    missing_target = tmp_path / "recordings" / "never-written.mp4"
    missing_uri = missing_target.as_uri()

    url = f"sqlite:///{tmp_path / 'm0072_absent.sqlite'}"
    cfg = _cfg(url)
    command.upgrade(cfg, _PARENT_REVISION)
    _seed_asset(
        url,
        asset_id="rehearsal-missing-file",
        file_path=missing_uri,
        file_status="missing",
    )

    command.upgrade(cfg, _REVISION)

    row = _asset_row(url, "rehearsal-missing-file")
    assert row["file_path"] == str(missing_target)
    assert row["file_status"] == "missing"
    assert row["file_status_checked_at"] is None


def test_migration_0072_ignores_rows_already_shaped_correctly(tmp_path: Path) -> None:
    """A row already storing a plain local path, and a manifest-only row
    with no ``file_path`` at all, are untouched -- the migration only
    matches ``file_path LIKE 'file://%'``."""
    already_local = str(tmp_path / "uploads" / "council-2026-06-01.mp4")
    url = f"sqlite:///{tmp_path / 'm0072_untouched.sqlite'}"
    cfg = _cfg(url)
    command.upgrade(cfg, _PARENT_REVISION)
    _seed_asset(url, asset_id="already-local", file_path=already_local, file_status="ok")
    _seed_asset(url, asset_id="manifest-only", file_path=None, file_status="ok")

    command.upgrade(cfg, _REVISION)

    local_row = _asset_row(url, "already-local")
    assert local_row["file_path"] == already_local
    assert local_row["file_status_checked_at"] is None

    manifest_row = _asset_row(url, "manifest-only")
    assert manifest_row["file_path"] is None


def test_migration_0072_downgrade_is_a_safe_no_op(tmp_path: Path) -> None:
    """Downgrade neither raises nor rewrites the just-repaired row.

    Reverting a normalized ``file_path`` back into a ``file://`` URI can't
    be done safely after the fact (see the migration's module docstring):
    a plain local path is indistinguishable from a row that was always
    stored that way. The tested contract is that downgrade is inert, not
    that it undoes the repair -- proven here by asserting the row is
    byte-identical before and after downgrade, and that the migration
    chain itself walks down and back up without error.
    """
    recording = tmp_path / "recordings" / "rehearsal-roundtrip.mp4"
    recording.parent.mkdir(parents=True)
    recording.write_bytes(b"roundtrip bytes")

    url = f"sqlite:///{tmp_path / 'm0072_downgrade.sqlite'}"
    cfg = _cfg(url)
    command.upgrade(cfg, _PARENT_REVISION)
    _seed_asset(
        url,
        asset_id="rehearsal-roundtrip",
        file_path=recording.as_uri(),
        file_status="missing",
    )
    command.upgrade(cfg, _REVISION)
    repaired = _asset_row(url, "rehearsal-roundtrip")
    assert repaired["file_path"] == str(recording)
    assert repaired["file_status"] == "ok"

    command.downgrade(cfg, _PARENT_REVISION)
    after_downgrade = _asset_row(url, "rehearsal-roundtrip")
    assert after_downgrade == repaired

    # The chain is genuinely reversible (walks down and back up cleanly),
    # which is the "both upgrade and downgrade implemented" contract this
    # repo's migrations are held to, even though the data repair itself is
    # a documented one-way street.
    command.upgrade(cfg, _REVISION)
    assert _asset_row(url, "rehearsal-roundtrip") == repaired
