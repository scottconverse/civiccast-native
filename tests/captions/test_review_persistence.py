# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Durable caption review store tests (Stage E).

The audit capability row: "InMemoryCaptionReviewStore is a real but ephemeral
component; default even on the durable path; no DB model/migration." Caption
review decisions are operator work product on the public-record path — they
must survive a restart. These tests pin the Postgres/SQLite-backed store to
the exact contract of the in-memory store, prove durability across store
instances and across app restarts, and run the same contract against real
PostgreSQL when available.
"""

from __future__ import annotations

import hashlib
import wave
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from civiccast.captions.models import CaptionCue
from civiccast.captions.persistence import PostgresCaptionReviewStore
from civiccast.captions.review import (
    CaptionReviewAudioEvidence,
    CaptionReviewAudioEvidenceRequiredError,
    CaptionReviewDecision,
    CaptionReviewEdit,
    CaptionReviewItemAlreadyExistsError,
    CaptionReviewItemCreate,
    CaptionReviewItemNotFoundError,
    CaptionReviewLowConfidenceAcknowledgementRequiredError,
)
from civiccast.db import Base


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine("sqlite:///:memory:", future=True)
    eng = eng.execution_options(schema_translate_map={"civiccast": None})
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def store(engine: Engine) -> PostgresCaptionReviewStore:
    return PostgresCaptionReviewStore(_factory_for(engine))


def _factory_for(engine: Engine):  # type: ignore[no-untyped-def]
    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    return factory


def _cue(cue_id: str = "cue-1", *, low_confidence: bool = False) -> CaptionCue:
    return CaptionCue(
        cue_id=cue_id,
        start_seconds=12.0,
        end_seconds=14.5,
        text="the budget motion carries",
        confidence=0.42,
        low_confidence=low_confidence,
    )


def _create(
    store: PostgresCaptionReviewStore,
    review_item_id: str = "review-1",
    *,
    asset_id: str = "council-2026-06-09",
    low_confidence: bool = False,
    audio_evidence: CaptionReviewAudioEvidence | None = None,
) -> None:
    store.create(
        CaptionReviewItemCreate(
            review_item_id=review_item_id,
            asset_id=asset_id,
            cue=_cue(f"cue-{review_item_id}", low_confidence=low_confidence),
            reviewer_note=None,
            audio_evidence=audio_evidence,
        )
    )


def _covering_evidence(path: Path) -> CaptionReviewAudioEvidence:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(b"\0\0" * 16_000 * 5)
    return CaptionReviewAudioEvidence(
        source_path=str(path.resolve()),
        source_start_seconds=10.0,
        source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        source_bytes=path.stat().st_size,
    )


class TestContract:
    def test_create_and_get_round_trip(self, store: PostgresCaptionReviewStore) -> None:
        _create(store, low_confidence=True)
        item = store.get("review-1")
        assert item is not None
        assert item.status == "pending"
        assert item.original_text == "the budget motion carries"
        assert item.reviewed_text is None
        assert item.low_confidence is True
        assert item.cue.cue_id == "cue-review-1"
        assert item.cue.end_seconds == 14.5

    def test_private_audio_evidence_round_trips_without_exposing_its_path(
        self,
        store: PostgresCaptionReviewStore,
        tmp_path: Path,
    ) -> None:
        source = tmp_path / "evidence.wav"
        source.write_bytes(b"RIFF-evidence")
        evidence = CaptionReviewAudioEvidence(
            source_path=str(source.resolve()),
            source_start_seconds=10.0,
            source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            source_bytes=source.stat().st_size,
        )
        created = store.create(
            CaptionReviewItemCreate(
                review_item_id="review-evidence",
                asset_id="gov",
                cue=_cue("cue-evidence"),
                audio_evidence=evidence,
            )
        )

        assert created.audio_evidence_available is True
        assert "source_path" not in created.model_dump()
        assert store.get_audio_evidence("review-evidence") == evidence

    def test_get_missing_returns_none(self, store: PostgresCaptionReviewStore) -> None:
        assert store.get("missing") is None

    def test_duplicate_id_raises(self, store: PostgresCaptionReviewStore) -> None:
        _create(store)
        with pytest.raises(CaptionReviewItemAlreadyExistsError):
            _create(store)

    def test_list_filters_and_ordering(self, store: PostgresCaptionReviewStore) -> None:
        _create(store, "review-b", asset_id="asset-1")
        _create(store, "review-a", asset_id="asset-1")
        _create(store, "review-c", asset_id="asset-2")
        store.approve(
            "review-c",
            CaptionReviewDecision(
                reviewer_note=None,
                low_confidence_acknowledged=True,
            ),
        )

        all_rows = store.list()
        assert {row.review_item_id for row in all_rows} == {"review-a", "review-b", "review-c"}
        # Contract: ordered by (created_at, review_item_id). The wall clock can
        # quantize on Windows, so assert the invariant rather than a fixed
        # insertion order.
        assert [row.review_item_id for row in all_rows] == [
            row.review_item_id
            for row in sorted(all_rows, key=lambda r: (r.created_at, r.review_item_id))
        ]
        asset_rows = store.list(asset_id="asset-1")
        assert {row.review_item_id for row in asset_rows} == {"review-a", "review-b"}
        approved = store.list(status="approved")
        assert [row.review_item_id for row in approved] == ["review-c"]

    def test_language_defaults_to_en_and_scopes_the_list(
        self, store: PostgresCaptionReviewStore
    ) -> None:
        """Recorded-Spanish: en/es rows share an asset_id but list separately.

        Existing callers create rows with no ``language``, which must persist
        (and round-trip) as ``en`` -- the durable default the 0083 migration
        backfills. A Spanish row created with ``language='es'`` on the same
        asset must be reachable ONLY through the ``es`` filter, so the two
        review passes never mix on a shared asset.
        """

        _create(store, "en-row", asset_id="council-x")
        store.create(
            CaptionReviewItemCreate(
                review_item_id="es-row",
                asset_id="council-x",
                cue=_cue("cue-es"),
                language="es",
            )
        )

        # Default persists and round-trips as en.
        assert store.get("en-row").language == "en"  # type: ignore[union-attr]
        assert store.get("es-row").language == "es"  # type: ignore[union-attr]

        english = store.list(asset_id="council-x", language="en")
        spanish = store.list(asset_id="council-x", language="es")
        assert [row.review_item_id for row in english] == ["en-row"]
        assert [row.review_item_id for row in spanish] == ["es-row"]
        # Unfiltered by language still returns both.
        assert {row.review_item_id for row in store.list(asset_id="council-x")} == {
            "en-row",
            "es-row",
        }

    def test_approve_keeps_prior_edit_text(self, store: PostgresCaptionReviewStore) -> None:
        _create(store)
        store.edit(
            "review-1",
            CaptionReviewEdit(text="the budget motion carries 5-2", reviewer_note="fixed tally"),
        )
        item = store.approve(
            "review-1",
            CaptionReviewDecision(
                reviewer_note="ok",
                low_confidence_acknowledged=True,
            ),
        )
        assert item.status == "approved"
        assert item.reviewed_text == "the budget motion carries 5-2"
        assert item.reviewer_note == "ok"

    def test_approve_without_edit_uses_original_text(
        self, store: PostgresCaptionReviewStore
    ) -> None:
        _create(store)
        item = store.approve(
            "review-1",
            CaptionReviewDecision(
                reviewer_note=None,
                low_confidence_acknowledged=True,
            ),
        )
        assert item.reviewed_text == "the budget motion carries"

    def test_low_confidence_approval_requires_acknowledgement(
        self,
        store: PostgresCaptionReviewStore,
    ) -> None:
        _create(store, low_confidence=True)

        with pytest.raises(
            CaptionReviewLowConfidenceAcknowledgementRequiredError,
            match="low-confidence",
        ):
            store.approve("review-1", CaptionReviewDecision(reviewer_note=None))

        assert store.get("review-1").status == "pending"  # type: ignore[union-attr]

    def test_low_confidence_approval_requires_valid_covering_audio_evidence(
        self,
        store: PostgresCaptionReviewStore,
        tmp_path: Path,
    ) -> None:
        _create(store, "missing-evidence", low_confidence=True)
        with pytest.raises(
            CaptionReviewAudioEvidenceRequiredError,
            match="audio evidence",
        ):
            store.approve(
                "missing-evidence",
                CaptionReviewDecision(low_confidence_acknowledged=True),
            )

        evidence = _covering_evidence(tmp_path / "covering.wav")
        _create(
            store,
            "valid-evidence",
            low_confidence=True,
            audio_evidence=evidence,
        )
        approved = store.approve(
            "valid-evidence",
            CaptionReviewDecision(low_confidence_acknowledged=True),
        )
        assert approved.status == "approved"

        corrupt = _covering_evidence(tmp_path / "corrupt.wav")
        _create(
            store,
            "corrupt-evidence",
            low_confidence=True,
            audio_evidence=corrupt,
        )
        Path(corrupt.source_path).write_bytes(b"tampered")
        with pytest.raises(
            CaptionReviewAudioEvidenceRequiredError,
            match="audio evidence",
        ):
            store.approve(
                "corrupt-evidence",
                CaptionReviewDecision(low_confidence_acknowledged=True),
            )

        uncovered = _covering_evidence(tmp_path / "uncovered.wav").model_copy(
            update={"source_start_seconds": 14.0}
        )
        _create(
            store,
            "uncovered-evidence",
            low_confidence=True,
            audio_evidence=uncovered,
        )
        with pytest.raises(
            CaptionReviewAudioEvidenceRequiredError,
            match="cover",
        ):
            store.approve(
                "uncovered-evidence",
                CaptionReviewDecision(low_confidence_acknowledged=True),
            )

    def test_reject_clears_reviewed_text(self, store: PostgresCaptionReviewStore) -> None:
        _create(store)
        store.edit("review-1", CaptionReviewEdit(text="edited", reviewer_note=None))
        item = store.reject("review-1", CaptionReviewDecision(reviewer_note="bad cue"))
        assert item.status == "rejected"
        assert item.reviewed_text is None
        assert item.reviewer_note == "bad cue"

    @pytest.mark.parametrize("action", ["approve", "edit", "reject"])
    def test_missing_item_raises_not_found(
        self, store: PostgresCaptionReviewStore, action: str
    ) -> None:
        with pytest.raises(CaptionReviewItemNotFoundError):
            if action == "edit":
                store.edit("missing", CaptionReviewEdit(text="x", reviewer_note=None))
            else:
                getattr(store, action)("missing", CaptionReviewDecision(reviewer_note=None))


class TestDurability:
    def test_second_store_instance_sees_rows(self, engine: Engine) -> None:
        first = PostgresCaptionReviewStore(_factory_for(engine))
        _create(first)
        second = PostgresCaptionReviewStore(_factory_for(engine))
        item = second.get("review-1")
        assert item is not None
        assert item.original_text == "the budget motion carries"


class TestAppRestartSurvival:
    def test_review_items_survive_an_app_restart(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The exact failure the audit row describes: with durable storage
        active, a caption review decision must not vanish when the app
        restarts. Drives the running app over HTTP, then boots a NEW app
        instance on the same database."""

        from alembic import command
        from alembic.config import Config
        from fastapi.testclient import TestClient

        from civiccast.app import create_app

        db_path = tmp_path / "captions.db"
        repo_root = Path(__file__).resolve().parents[2]
        cfg = Config(str(repo_root / "alembic.ini"))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
        command.upgrade(cfg, "head")

        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        monkeypatch.setenv(
            "CIVICCAST_STAFF_TOKENS",
            "captions-token:cap-op:Caption Operator:records_clerk,setup_admin",
        )
        monkeypatch.setenv("CIVICCAST_STAFF_TOKENS_FALLBACK_WITH_DB", "1")
        monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")
        monkeypatch.setenv("CIVICCAST_FINALIZATION_WORKER", "off")
        # This test owns caption persistence across app lifespans, not the
        # scheduled alerting lane.  The real daily self-test can outlive the
        # TestClient shutdown budget while it runs media probes, leaking its
        # SQLite session into later tests.
        monkeypatch.setenv("CIVICCAST_ALERTING", "off")
        headers = {"Authorization": "Bearer captions-token"}
        payload = {
            "review_item_id": "review-restart-1",
            "asset_id": "council-2026-06-09",
            "cue": {
                "cue_id": "cue-77",
                "start_seconds": 31.0,
                "end_seconds": 34.0,
                "text": "public comment opens",
                "confidence": 0.4,
                "low_confidence": True,
            },
        }

        with TestClient(create_app()) as client:
            created = client.post("/api/staff/captions/review-items", json=payload, headers=headers)
            assert created.status_code in (200, 201), created.text

        with TestClient(create_app()) as fresh_client:
            fetched = fresh_client.get(
                "/api/staff/captions/review-items/review-restart-1", headers=headers
            )
            assert fetched.status_code == 200, (
                f"review item vanished across app restart: {fetched.status_code} "
                f"{fetched.text} — the durable path must not use the in-memory store"
            )
            assert fetched.json()["original_text"] == "public comment opens"


@pytest.mark.skipif(
    "CIVICCAST_POSTGRES_TEST_URL" not in __import__("os").environ,
    reason="external Postgres server not configured",
)
class TestRealPostgres:
    def test_contract_round_trip_on_real_postgres(self) -> None:
        from alembic import command
        from alembic.config import Config

        from tests._postgres_harness import fresh_database_from_env

        repo_root = Path(__file__).resolve().parents[2]
        with fresh_database_from_env() as url:
            assert url is not None
            cfg = Config(str(repo_root / "alembic.ini"))
            cfg.set_main_option("sqlalchemy.url", url)
            command.upgrade(cfg, "head")
            eng = create_engine(url, future=True)
            try:
                store = PostgresCaptionReviewStore(_factory_for(eng))
                _create(store)
                store.edit("review-1", CaptionReviewEdit(text="edited on pg", reviewer_note=None))
                item = store.approve(
                    "review-1",
                    CaptionReviewDecision(
                        reviewer_note="ok",
                        low_confidence_acknowledged=True,
                    ),
                )
                assert item.status == "approved"
                assert item.reviewed_text == "edited on pg"
            finally:
                eng.dispose()
