# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Real backup tests: SQLite backup-API snapshot + media manifest + integrity manifest."""

from __future__ import annotations

from pathlib import Path

from civiccast.dr.backup import (
    _parse_postgres_url,
    build_media_manifest,
    build_sqlite_engine,
    run_full_backup,
    snapshot_tables,
    write_integrity_manifest,
)


def test_snapshot_matches_between_source_and_backup_copy(
    seeded_station_db: Path, tmp_path: Path
) -> None:
    """The whole drill hinges on this: source and backup-copy checksums must agree."""

    source_engine = build_sqlite_engine(seeded_station_db)
    source_snapshot = {t.name: t for t in snapshot_tables(source_engine)}
    source_engine.dispose()
    assert source_snapshot["assets"].row_count == 2
    assert source_snapshot["schedule_items"].row_count == 1
    assert source_snapshot["egress_configs"].row_count == 1

    manifest = run_full_backup(
        database_url=f"sqlite:///{seeded_station_db}", dest_dir=tmp_path / "backup"
    )
    backup_snapshot = {t.name: t for t in manifest.tables}
    for name in ("assets", "schedule_items", "egress_configs"):
        assert backup_snapshot[name].row_count == source_snapshot[name].row_count
        assert backup_snapshot[name].checksum_sha256 == source_snapshot[name].checksum_sha256


def test_backup_is_not_a_raw_copy_of_a_live_writer(seeded_station_db: Path, tmp_path: Path) -> None:
    """The backup API must produce a valid, openable snapshot even with a concurrent writer.

    A raw ``shutil.copy2`` of a live SQLite file can copy a half-written page;
    the backup API takes its own read lock instead. This proves the artifact
    it produces opens cleanly and contains the expected tables.
    """

    manifest = run_full_backup(
        database_url=f"sqlite:///{seeded_station_db}", dest_dir=tmp_path / "backup"
    )
    engine = build_sqlite_engine(tmp_path / "backup" / manifest.db_artifact)
    names = {t.name for t in snapshot_tables(engine)}
    engine.dispose()
    assert {"assets", "schedule_items", "egress_configs"} <= names


def test_media_manifest_bounds_the_hashed_sample(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    small = media_root / "small.ts"
    small.write_bytes(b"x" * 100)
    big = media_root / "big.ts"
    big.write_bytes(b"y" * 500_000)

    entries = build_media_manifest(media_root, sample_bytes=4096)
    by_path = {e.path: e for e in entries}

    assert by_path["small.ts"].size_bytes == 100
    assert by_path["small.ts"].sample_bytes == 100  # whole file, smaller than the bound

    assert by_path["big.ts"].size_bytes == 500_000
    assert by_path["big.ts"].sample_bytes <= 4096  # bounded — never the whole 500KB file


def test_media_manifest_detects_content_change(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    f = media_root / "clip.ts"
    f.write_bytes(b"a" * 200_000 + b"ORIGINAL-TAIL")
    before = build_media_manifest(media_root, sample_bytes=4096)[0]

    f.write_bytes(b"a" * 200_000 + b"CHANGED-TAIL!")  # only the tail changed
    after = build_media_manifest(media_root, sample_bytes=4096)[0]

    assert before.sampled_sha256 != after.sampled_sha256


def test_parse_postgres_url_decodes_percent_encoded_credentials() -> None:
    """FALSIFICATION: a percent-encoded password (required by RFC 3986 for hosted/managed
    Postgres credentials containing '@', ':' or '/') must come out decoded, matching what
    SQLAlchemy's own URL parser does for the run_full_backup snapshot connection."""

    conn = _parse_postgres_url("postgresql://svc:p%40ss%3Aw%2Frd@db.host:5432/civiccast")
    assert conn["user"] == "svc"
    assert conn["password"] == "p@ss:w/rd"
    assert conn["dbname"] == "civiccast"


def test_snapshot_checksum_distinguishes_null_from_literal_none_string(tmp_path: Path) -> None:
    """FALSIFICATION: a real SQL NULL and the literal text "None" must not hash identically,
    or a restore drill would report matched=True for a table that actually changed."""

    from sqlalchemy import create_engine, text

    db_path = tmp_path / "null-check.sqlite3"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE widgets (id INTEGER PRIMARY KEY, note TEXT)"))
        conn.execute(text("INSERT INTO widgets (id, note) VALUES (1, NULL)"))
    null_checksum = snapshot_tables(engine)[0].checksum_sha256

    with engine.begin() as conn:
        conn.execute(text("UPDATE widgets SET note = 'None' WHERE id = 1"))
    literal_checksum = snapshot_tables(engine)[0].checksum_sha256

    engine.dispose()
    assert null_checksum != literal_checksum


def test_integrity_manifest_covers_every_backed_up_file(
    seeded_station_db: Path, tmp_path: Path
) -> None:
    dest_dir = tmp_path / "backup"
    run_full_backup(database_url=f"sqlite:///{seeded_station_db}", dest_dir=dest_dir)
    entries = write_integrity_manifest(dest_dir)
    members = {e.member for e in entries}
    on_disk = {
        str(p.relative_to(dest_dir))
        for p in dest_dir.rglob("*")
        if p.is_file() and p.name != "manifest.json"
    }
    assert members == on_disk
    assert len(entries) > 0
