# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S11 SAP/descriptive audio — AudioProgramTrack model + store + migration 0052."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.egress.audio_tracks import (
    AudioProgramTrack,
    AudioTrackNotFoundError,
    AudioTrackStore,
)

_T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


@pytest.fixture
def store(tmp_path: Path) -> Iterator[AudioTrackStore]:
    eng = create_engine(f"sqlite:///{tmp_path / 'audio.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    try:
        yield AudioTrackStore(factory)
    finally:
        eng.dispose()


def _track(
    track_id: str = "t1", *, kind: str = "sap", language: str = "es", **kw: object
) -> AudioProgramTrack:
    base: dict[str, object] = {
        "track_id": track_id,
        "scope": "channel",
        "target_id": "gov",
        "kind": kind,
        "language": language,
        "label": "Spanish SAP",
    }
    base.update(kw)
    return AudioProgramTrack(**base)  # type: ignore[arg-type]


def test_track_crud_and_filtering(store: AudioTrackStore) -> None:
    store.upsert_track(_track("t1", kind="primary", language="en", label="Main"))
    store.upsert_track(_track("t2", kind="sap", language="es", label="Spanish SAP"))
    store.upsert_track(
        _track("t3", kind="descriptive", language="en", label="Audio description", enabled=False)
    )
    assert store.get_track("t2").label == "Spanish SAP"
    assert {t.track_id for t in store.list_tracks(target_id="gov")} == {"t1", "t2", "t3"}
    assert {t.track_id for t in store.list_tracks(target_id="gov", enabled_only=True)} == {
        "t1",
        "t2",
    }
    # ordered by kind then language
    kinds = [t.kind for t in store.list_tracks(target_id="gov")]
    assert kinds == sorted(kinds)


def test_track_per_track_loudness_and_source(store: AudioTrackStore) -> None:
    store.upsert_track(_track("t1", source_uri="file:///m/es.aac", loudness_target_lufs=-24.0))
    track = store.get_track("t1")
    assert track.source_uri == "file:///m/es.aac"
    assert track.loudness_target_lufs == -24.0


def test_track_delete(store: AudioTrackStore) -> None:
    store.upsert_track(_track("t1"))
    store.delete_track("t1")
    assert store.get_track("t1") is None
    with pytest.raises(AudioTrackNotFoundError):
        store.delete_track("missing")


def _make_cfg(database_url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


class TestSecondaryAudioMigration:
    """0052_secondary_audio creates audio_program_tracks on upgrade and drops it on a
    single-step downgrade to 0051 — the EAS tables survive."""

    def test_upgrade_head_creates_the_table(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "head")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            insp = inspect(eng)
            assert insp.has_table("audio_program_tracks")
            idx = {ix["name"] for ix in insp.get_indexes("audio_program_tracks")}
            assert "ix_audio_program_tracks_target" in idx
        finally:
            eng.dispose()

    def test_single_step_downgrade(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "0051_public_safety_eas")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            insp = inspect(eng)
            assert not insp.has_table("audio_program_tracks")
            assert insp.has_table("eas_cap_alerts")  # 0051 survives
        finally:
            eng.dispose()
