# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""WP-08: value/unit/forever retention-term authoring.

Covers the store-level authoring/conversion contract
(``PostgresAssetStore._apply_retention_term`` via
``PostgresAssetStore.update_metadata``):

  TestAssetMetadataUpdateTermValidation  -- Pydantic-level term validation
                                             and the legacy/new mutual-
                                             exclusion rule
  TestStoreAuthorTerm                    -- finite terms, forever, invalid
                                             values, anchor capture/reuse/
                                             immutability, legacy-row
                                             conversion + audit fallback
  TestPublishUnpublishRepublishAnchor    -- retention_anchor_at is set on
                                             first publish only and never
                                             moves across unpublish/
                                             republish
  TestRetentionWorkerIntegration         -- an authored finite term that
                                             crosses its deadline flows
                                             through the UNCHANGED
                                             enforcement worker: a
                                             disposition review is created
                                             and no media is deleted
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from civiccast.schedule.media_lifecycle_models import MediaLifecycleAuditEntry
from civiccast.schedule.models import (
    RETENTION_DEFAULT,
    RETENTION_PERMANENT,
    Asset,
    AssetMetadataUpdate,
)
from civiccast.schedule.retention_worker import (
    RetentionEnforcementWorker,
    RetentionWorkerSettings,
)
from civiccast.schedule.store import PostgresAssetStore

_NOW = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)


def _seed_asset(
    session_factory,
    asset_id: str,
    *,
    manifest_url: str | None = "https://cdn.example/x/playlist.m3u8",
    published_at: datetime | None = None,
    retention_anchor_at: datetime | None = None,
    retention_policy: str = "default",
) -> None:
    with session_factory() as sess:
        sess.add(
            Asset(
                asset_id=asset_id,
                title=f"Asset {asset_id}",
                state="validated",
                manifest_url=manifest_url,
                published_at=published_at,
                retention_anchor_at=retention_anchor_at,
                retention_policy=retention_policy,
            )
        )
        sess.commit()


# ---------------------------------------------------------------------------
# TestAssetMetadataUpdateTermValidation
# ---------------------------------------------------------------------------


class TestAssetMetadataUpdateTermValidation:
    def test_forever_alone_is_valid(self) -> None:
        update = AssetMetadataUpdate(expected_version=1, retention_term_unit="forever")
        assert update.retention_term_unit == "forever"
        assert update.retention_term_value is None

    def test_finite_unit_requires_value(self) -> None:
        with pytest.raises(ValidationError, match="positive integer"):
            AssetMetadataUpdate(expected_version=1, retention_term_unit="days")

    def test_forever_rejects_a_value(self) -> None:
        with pytest.raises(ValidationError, match="must be omitted"):
            AssetMetadataUpdate(
                expected_version=1, retention_term_unit="forever", retention_term_value=5
            )

    def test_value_alone_without_unit_rejected(self) -> None:
        with pytest.raises(ValidationError, match="requires retention_term_unit"):
            AssetMetadataUpdate(expected_version=1, retention_term_value=10)

    def test_unit_cannot_be_explicitly_nulled(self) -> None:
        with pytest.raises(ValidationError, match="cannot be cleared"):
            AssetMetadataUpdate(expected_version=1, retention_term_unit=None)

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"retention_term_unit": "forever", "retention_policy": "permanent"},
            {"retention_term_unit": "forever", "retention_until": _NOW},
        ],
    )
    def test_new_contract_cannot_mix_with_legacy_fields(self, kwargs: dict) -> None:
        with pytest.raises(ValidationError, match="cannot be combined"):
            AssetMetadataUpdate(expected_version=1, **kwargs)

    def test_negative_or_zero_value_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AssetMetadataUpdate(expected_version=1, retention_term_unit="days", retention_term_value=0)
        with pytest.raises(ValidationError):
            AssetMetadataUpdate(
                expected_version=1, retention_term_unit="days", retention_term_value=-3
            )

    def test_unknown_unit_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AssetMetadataUpdate(expected_version=1, retention_term_unit="fortnights", retention_term_value=1)


# ---------------------------------------------------------------------------
# TestStoreAuthorTerm
# ---------------------------------------------------------------------------


class TestStoreAuthorTerm:
    def test_finite_term_computes_deadline_from_anchor(self, session_factory) -> None:
        anchor = datetime(2026, 1, 1, tzinfo=UTC)
        _seed_asset(session_factory, "a1", retention_anchor_at=anchor)
        store = PostgresAssetStore(session_factory)

        result = store.update_metadata(
            "a1",
            AssetMetadataUpdate(
                expected_version=1, retention_term_unit="days", retention_term_value=30
            ),
        )

        assert result.retention_term_unit == "days"
        assert result.retention_term_value == 30
        assert result.retention_until == anchor + timedelta(days=30)
        assert result.retention_policy == RETENTION_DEFAULT
        assert result.retention_anchor_at == anchor

    def test_forever_clears_deadline_and_mirrors_permanent(self, session_factory) -> None:
        anchor = datetime(2026, 1, 1, tzinfo=UTC)
        _seed_asset(session_factory, "a2", retention_anchor_at=anchor)
        store = PostgresAssetStore(session_factory)

        result = store.update_metadata(
            "a2", AssetMetadataUpdate(expected_version=1, retention_term_unit="forever")
        )

        assert result.retention_term_unit == "forever"
        assert result.retention_term_value is None
        assert result.retention_until is None
        # Mirrors the legacy enum so the UNCHANGED enforcement worker's own
        # `retention_policy != 'permanent'` skip keeps working.
        assert result.retention_policy == RETENTION_PERMANENT

    def test_anchor_is_reused_not_moved_across_edits(self, session_factory) -> None:
        anchor = datetime(2025, 3, 1, tzinfo=UTC)
        _seed_asset(session_factory, "a3", retention_anchor_at=anchor)
        store = PostgresAssetStore(session_factory)

        first = store.update_metadata(
            "a3",
            AssetMetadataUpdate(
                expected_version=1, retention_term_unit="months", retention_term_value=6
            ),
        )
        second = store.update_metadata(
            "a3",
            AssetMetadataUpdate(
                expected_version=first.version,
                retention_term_unit="years",
                retention_term_value=2,
            ),
        )

        assert first.retention_anchor_at == anchor
        assert second.retention_anchor_at == anchor, "anchor must never move on a term edit"
        # Second edit recomputes the deadline from the SAME anchor, not
        # from "now" or from the first edit's own deadline.
        assert second.retention_until == datetime(2027, 3, 1, tzinfo=UTC)

    def test_conversion_with_no_publication_history_falls_back_and_audits(
        self, session_factory
    ) -> None:
        # A never-published legacy `short` row: no retention_anchor_at
        # exists anywhere to reuse (finalization plan section 6, item 6).
        _seed_asset(
            session_factory,
            "a4",
            manifest_url=None,
            published_at=None,
            retention_anchor_at=None,
            retention_policy="short",
        )
        store = PostgresAssetStore(session_factory)

        before = datetime.now(UTC)
        result = store.update_metadata(
            "a4",
            AssetMetadataUpdate(
                expected_version=1, retention_term_unit="days", retention_term_value=30
            ),
        )
        after = datetime.now(UTC)

        assert result.retention_anchor_at is not None
        assert before <= result.retention_anchor_at <= after
        assert result.retention_until == result.retention_anchor_at + timedelta(days=30)

        with session_factory() as sess:
            entries = list(
                sess.execute(
                    select(MediaLifecycleAuditEntry).where(
                        MediaLifecycleAuditEntry.asset_id == "a4"
                    )
                ).scalars()
            )
        assert len(entries) == 1
        assert entries[0].action == "retention_term_anchor_fallback"
        assert "no publication" in entries[0].detail.lower() or "conversion time" in entries[0].detail.lower()

    def test_legacy_row_never_converted_has_no_term_fields(self, session_factory) -> None:
        # A legacy `meeting` row that is never touched under the new
        # contract must show no authored term -- WP-08 does not backfill
        # ambiguous legacy policies.
        _seed_asset(session_factory, "a5", retention_policy="meeting")
        store = PostgresAssetStore(session_factory)
        row = store.get_staff_row("a5")
        assert row is not None
        assert row.retention_term_unit is None
        assert row.retention_term_value is None

    def test_mixing_new_and_legacy_contract_rejected_before_store(self, session_factory) -> None:
        # Pydantic rejects this before the store ever sees it (see
        # TestAssetMetadataUpdateTermValidation) -- this asserts the store
        # is never reached with a mixed payload by construction.
        with pytest.raises(ValidationError):
            AssetMetadataUpdate(
                expected_version=1,
                retention_term_unit="forever",
                retention_policy="permanent",
            )


# ---------------------------------------------------------------------------
# TestPublishUnpublishRepublishAnchor
# ---------------------------------------------------------------------------


class TestPublishUnpublishRepublishAnchor:
    def test_anchor_captured_on_first_publish(self, session_factory) -> None:
        _seed_asset(session_factory, "p1", manifest_url="https://cdn.example/p1/playlist.m3u8")
        store = PostgresAssetStore(session_factory)

        published_at = datetime(2026, 4, 1, tzinfo=UTC)
        result = store.mark_published("p1", published_at=published_at)

        assert result.retention_anchor_at == published_at

    def test_anchor_survives_unpublish_and_does_not_move_on_republish(
        self, session_factory
    ) -> None:
        _seed_asset(session_factory, "p2", manifest_url="https://cdn.example/p2/playlist.m3u8")
        store = PostgresAssetStore(session_factory)

        first_publish = datetime(2026, 4, 1, tzinfo=UTC)
        store.mark_published("p2", published_at=first_publish)

        unpublished = store.mark_unpublished("p2")
        assert unpublished.published_at is None
        assert unpublished.retention_anchor_at == first_publish, (
            "unpublish clears published_at but must NEVER clear retention_anchor_at"
        )

        second_publish = datetime(2026, 9, 1, tzinfo=UTC)
        republished = store.mark_published("p2", published_at=second_publish)
        assert republished.published_at == second_publish
        assert republished.retention_anchor_at == first_publish, (
            "republish overwrites published_at but must NEVER move retention_anchor_at"
        )


# ---------------------------------------------------------------------------
# TestRetentionWorkerIntegration
# ---------------------------------------------------------------------------


class TestRetentionWorkerIntegration:
    def test_authored_finite_term_crossing_deadline_creates_review_deletes_no_media(
        self, session_factory
    ) -> None:
        """Explicit WP-08 done-criterion: an asset whose NEW value/unit/forever
        term has crossed retention_until is flagged into the disposition
        review queue by the UNCHANGED retention worker, and no media file
        reference is touched."""
        anchor = _NOW - timedelta(days=31)
        _seed_asset(session_factory, "r1", retention_anchor_at=anchor)
        store = PostgresAssetStore(session_factory)
        store.update_metadata(
            "r1",
            AssetMetadataUpdate(
                expected_version=1, retention_term_unit="days", retention_term_value=30
            ),
        )

        worker = RetentionEnforcementWorker(
            session_factory, settings=RetentionWorkerSettings(mode="inline", poll_seconds=3600.0)
        )
        flagged = worker.run_once(now=_NOW)

        assert [row.asset_id for row in flagged] == ["r1"]
        assert flagged[0].status == "pending_review"

        with session_factory() as sess:
            row = sess.get(Asset, "r1")
            assert row is not None
            # No bytes/paths touched -- file_path stays exactly as seeded
            # (None, since this test asset was never given one), and the
            # asset row itself is not deleted or state-transitioned.
            assert row.file_path is None
            assert row.state == "validated"

    def test_forever_term_never_flagged_even_far_past_any_deadline(
        self, session_factory
    ) -> None:
        anchor = _NOW - timedelta(days=10_000)
        _seed_asset(session_factory, "r2", retention_anchor_at=anchor)
        store = PostgresAssetStore(session_factory)
        store.update_metadata(
            "r2", AssetMetadataUpdate(expected_version=1, retention_term_unit="forever")
        )

        worker = RetentionEnforcementWorker(
            session_factory, settings=RetentionWorkerSettings(mode="inline", poll_seconds=3600.0)
        )
        assert worker.run_once(now=_NOW) == []
