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

    def test_value_past_the_absolute_max_rejected_at_pydantic_layer(self) -> None:
        # Coordinator-directed fix (follow-up commit, MAJOR finding 1):
        # the Field(le=...) bound rejects an absurd/overflow-risk value at
        # request-parse time, before any custom validator or the store
        # ever runs.
        from civiccast.schedule.retention_terms import RETENTION_TERM_VALUE_ABSOLUTE_MAX

        with pytest.raises(ValidationError):
            AssetMetadataUpdate(
                expected_version=1,
                retention_term_unit="days",
                retention_term_value=RETENTION_TERM_VALUE_ABSOLUTE_MAX + 1,
            )
        with pytest.raises(ValidationError):
            AssetMetadataUpdate(
                expected_version=1, retention_term_unit="days", retention_term_value=10**9
            )

    def test_value_at_the_per_unit_boundary_accepted_one_past_rejected(self) -> None:
        from civiccast.schedule.retention_terms import max_value_for_unit

        boundary = max_value_for_unit("years")
        assert boundary is not None
        AssetMetadataUpdate(
            expected_version=1, retention_term_unit="years", retention_term_value=boundary
        )  # does not raise
        with pytest.raises(ValidationError, match="exceeds the maximum"):
            AssetMetadataUpdate(
                expected_version=1,
                retention_term_unit="years",
                retention_term_value=boundary + 1,
            )

    # Note: `bool` rejection (MINOR finding 3) is proven at the
    # civiccast.schedule.retention_terms.validate_term layer
    # (tests/schedule/test_retention_terms.py::TestValidateTermRejectsNonInteger)
    # rather than here -- Pydantic v2's lax `int` field coerces `True`/
    # `False` to `1`/`0` before this class's own `_retention_term_shape`
    # validator (or `validate_term` underneath it) ever sees the value,
    # so a bool submitted over the API becomes an ordinary valid int by
    # the time any custom validation runs. `validate_term` still rejects
    # an actual `bool` object reaching it directly (a future non-Pydantic
    # caller, or a store that bypasses the model).


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


class TestStoreRefusesLegacyOnlyPatchAgainstConvertedRow:
    """Coordinator-directed fix (follow-up commit, MAJOR finding 2): a
    legacy-only PATCH (retention_policy/retention_until, no
    retention_term_unit -- the only shape Pydantic allows once a row is
    already converted, since the two contracts can't mix in one payload)
    against an already-converted row must be refused outright, not
    silently applied (which would desync retention_policy/retention_until
    from the authored retention_term_unit/value/anchor until the next
    term edit silently clobbered it back)."""

    def test_legacy_policy_only_patch_refused_on_converted_row(self, session_factory) -> None:
        anchor = datetime(2026, 1, 1, tzinfo=UTC)
        _seed_asset(session_factory, "d1", retention_anchor_at=anchor)
        store = PostgresAssetStore(session_factory)
        authored = store.update_metadata(
            "d1",
            AssetMetadataUpdate(
                expected_version=1, retention_term_unit="days", retention_term_value=30
            ),
        )

        with pytest.raises(ValueError, match="value/unit/forever retention"):
            store.update_metadata(
                "d1",
                AssetMetadataUpdate(
                    expected_version=authored.version, retention_policy=RETENTION_PERMANENT
                ),
            )

    def test_legacy_until_only_patch_refused_on_converted_row(self, session_factory) -> None:
        anchor = datetime(2026, 1, 1, tzinfo=UTC)
        _seed_asset(session_factory, "d2", retention_anchor_at=anchor)
        store = PostgresAssetStore(session_factory)
        authored = store.update_metadata(
            "d2", AssetMetadataUpdate(expected_version=1, retention_term_unit="forever")
        )

        with pytest.raises(ValueError, match="value/unit/forever retention"):
            store.update_metadata(
                "d2",
                AssetMetadataUpdate(
                    expected_version=authored.version,
                    retention_until=datetime(2030, 1, 1, tzinfo=UTC),
                ),
            )

    def test_refused_patch_does_not_desync_the_row(self, session_factory) -> None:
        # The refused PATCH must not have partially applied -- re-reading
        # the row afterward shows the authored term/deadline untouched.
        anchor = datetime(2026, 1, 1, tzinfo=UTC)
        _seed_asset(session_factory, "d3", retention_anchor_at=anchor)
        store = PostgresAssetStore(session_factory)
        authored = store.update_metadata(
            "d3",
            AssetMetadataUpdate(
                expected_version=1, retention_term_unit="days", retention_term_value=30
            ),
        )

        with pytest.raises(ValueError):
            store.update_metadata(
                "d3",
                AssetMetadataUpdate(
                    expected_version=authored.version, retention_policy=RETENTION_PERMANENT
                ),
            )

        row = store.get_staff_row("d3")
        assert row is not None
        assert row.retention_term_unit == "days"
        assert row.retention_term_value == 30
        assert row.retention_policy == RETENTION_DEFAULT
        assert row.retention_until == anchor + timedelta(days=30)
        assert row.version == authored.version, "the refused PATCH must not bump version either"

    def test_legacy_only_patch_still_allowed_on_a_never_converted_row(
        self, session_factory
    ) -> None:
        # The guard is scoped to already-converted rows only -- an
        # ordinary legacy row keeps working exactly as before.
        _seed_asset(session_factory, "d4", retention_policy="meeting")
        store = PostgresAssetStore(session_factory)
        result = store.update_metadata(
            "d4",
            AssetMetadataUpdate(expected_version=1, retention_policy=RETENTION_PERMANENT),
        )
        assert result.retention_policy == RETENTION_PERMANENT
        assert result.retention_term_unit is None

    def test_term_edit_on_a_converted_row_still_works(self, session_factory) -> None:
        # The guard must not block the actually-supported path: a new
        # term PATCH against an already-converted row.
        anchor = datetime(2026, 1, 1, tzinfo=UTC)
        _seed_asset(session_factory, "d5", retention_anchor_at=anchor)
        store = PostgresAssetStore(session_factory)
        first = store.update_metadata(
            "d5",
            AssetMetadataUpdate(
                expected_version=1, retention_term_unit="days", retention_term_value=30
            ),
        )
        second = store.update_metadata(
            "d5",
            AssetMetadataUpdate(expected_version=first.version, retention_term_unit="forever"),
        )
        assert second.retention_term_unit == "forever"
        assert second.retention_policy == RETENTION_PERMANENT


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


# ---------------------------------------------------------------------------
# TestRouterNeverReturns500ForRetentionTermErrors
# ---------------------------------------------------------------------------


class TestRouterNeverReturns500ForRetentionTermErrors:
    """Coordinator-directed fix (follow-up commit, MAJOR finding 1):
    ``PATCH /api/staff/assets/{asset_id}`` must map every retention-term
    validation failure -- including one that would have raised
    ``OverflowError`` before this fix -- to a 422, never an uncaught 500.
    Also covers MAJOR finding 2's router-level surface (the store's
    refusal on a legacy-only PATCH against an already-converted row)."""

    def test_huge_value_is_a_422_at_the_request_body_layer_never_500(self) -> None:
        # The primary path: FastAPI's own Pydantic request-body validation
        # (the Field(le=...) bound) rejects this before the route function
        # -- and therefore the store -- is ever reached.
        from fastapi.testclient import TestClient

        from civiccast.app import create_app

        app = create_app()
        with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as client:
            response = client.patch(
                "/api/staff/assets/abc-123",
                json={
                    "expected_version": 1,
                    "retention_term_unit": "days",
                    "retention_term_value": 10**9,
                },
            )
        assert response.status_code == 422
        assert response.status_code != 500

    def test_store_raising_overflow_error_still_maps_to_422_not_500(self) -> None:
        # Defense-in-depth path: even if a value somehow reached the store
        # and its arithmetic raised OverflowError directly, the router's
        # except clause must still produce a 422, not fall through to an
        # unhandled 500.
        from unittest.mock import MagicMock

        from fastapi.testclient import TestClient

        from civiccast.app import create_app
        from civiccast.schedule.router import get_postgres_store

        app = create_app()
        mock_store = MagicMock()
        mock_store.update_metadata.side_effect = OverflowError("date value out of range")
        app.dependency_overrides[get_postgres_store] = lambda: mock_store
        with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as client:
            response = client.patch(
                "/api/staff/assets/abc-123",
                json={
                    "expected_version": 1,
                    "retention_term_unit": "days",
                    "retention_term_value": 1,
                },
            )
        assert response.status_code == 422
        assert response.status_code != 500

    def test_legacy_only_patch_on_converted_row_is_422_not_500(self) -> None:
        from unittest.mock import MagicMock

        from fastapi.testclient import TestClient

        from civiccast.app import create_app
        from civiccast.schedule.router import get_postgres_store

        app = create_app()
        mock_store = MagicMock()
        mock_store.update_metadata.side_effect = ValueError(
            "Asset abc-123 already uses the value/unit/forever retention contract "
            "(retention_term_unit='days'); the legacy retention_policy/retention_until "
            "fields can no longer be edited directly."
        )
        app.dependency_overrides[get_postgres_store] = lambda: mock_store
        with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as client:
            response = client.patch(
                "/api/staff/assets/abc-123",
                json={"expected_version": 1, "retention_policy": "permanent"},
            )
        assert response.status_code == 422
        assert response.status_code != 500
        assert "value/unit/forever" in response.json()["detail"]
