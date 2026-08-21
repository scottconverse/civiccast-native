# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S7 media lifecycle store tests: watch-folder/retention-policy CRUD,
storage budget, legal hold, replace-source DB application, audit log.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.schedule.media_lifecycle_models import (
    AssetReadiness,
    AssetRetentionPolicyInput,
    TranscodeJob,
    WatchFolderConfigInput,
)
from civiccast.schedule.media_lifecycle_store import (
    AssetNotFoundError,
    AssetRetentionPolicyNotFoundError,
    MediaLifecycleStore,
    WatchFolderConfigNotFoundError,
)
from civiccast.schedule.models import Asset


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
def session_factory(engine: Engine):  # type: ignore[no-untyped-def]
    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    return factory


@pytest.fixture
def store(session_factory) -> MediaLifecycleStore:  # type: ignore[no-untyped-def]
    return MediaLifecycleStore(session_factory)


def _seed_asset(engine: Engine, **overrides: object) -> None:
    defaults: dict[str, object] = {"asset_id": "a1", "title": "Council Meeting", "state": "validated"}
    defaults.update(overrides)
    with Session(bind=engine) as session:
        session.add(Asset(**defaults))  # type: ignore[arg-type]
        session.commit()


class TestReadiness:
    def test_get_readiness_for_unknown_asset_returns_none(self, store: MediaLifecycleStore) -> None:
        assert store.get_readiness("nope") is None

    def test_get_readiness_before_any_worker_pass_reads_not_ready(
        self, engine: Engine, store: MediaLifecycleStore
    ) -> None:
        _seed_asset(engine, asset_id="a1")
        result = store.get_readiness("a1")
        assert result is not None
        assert result.readiness_state == "not_ready"

    def test_get_readiness_reflects_legal_hold_from_asset(
        self, engine: Engine, store: MediaLifecycleStore
    ) -> None:
        _seed_asset(engine, asset_id="a1", legal_hold=True, legal_hold_reason="subpoena")
        result = store.get_readiness("a1")
        assert result is not None
        assert result.legal_hold is True

    def test_dashboard_counts_by_state(self, engine: Engine, store: MediaLifecycleStore) -> None:
        _seed_asset(engine, asset_id="a1")
        _seed_asset(engine, asset_id="a2")
        with Session(bind=engine) as session:
            session.add(AssetReadiness(asset_id="a1", readiness_state="ready"))
            session.add(AssetReadiness(asset_id="a2", readiness_state="missing_file"))
            session.commit()
        dashboard = store.dashboard()
        assert dashboard.total_assets == 2
        assert dashboard.ready_count == 1
        assert dashboard.missing_count == 1


class TestLegalHold:
    def test_set_legal_hold_unknown_asset_raises(self, store: MediaLifecycleStore) -> None:
        with pytest.raises(AssetNotFoundError):
            store.set_legal_hold("nope", hold=True, reason="x")

    def test_set_and_clear_legal_hold_round_trips(
        self, engine: Engine, store: MediaLifecycleStore
    ) -> None:
        _seed_asset(engine, asset_id="a1")
        store.set_legal_hold("a1", hold=True, reason="open records request")
        with Session(bind=engine) as session:
            asset = session.get(Asset, "a1")
            assert asset is not None
            assert asset.legal_hold is True
            assert asset.legal_hold_reason == "open records request"

        store.set_legal_hold("a1", hold=False, reason=None)
        with Session(bind=engine) as session:
            asset = session.get(Asset, "a1")
            assert asset is not None
            assert asset.legal_hold is False
            assert asset.legal_hold_reason is None


class TestWatchFolderConfigCrud:
    def test_create_list_update_delete_round_trip(self, store: MediaLifecycleStore) -> None:
        created = store.create_watch_folder_config(
            WatchFolderConfigInput(monitor_path="/mnt/nas/incoming", settle_window_seconds=15)
        )
        assert created.monitor_path == "/mnt/nas/incoming"
        assert created.settle_window_seconds == 15

        listed = store.list_watch_folder_configs()
        assert len(listed) == 1

        updated = store.update_watch_folder_config(
            created.config_id,
            WatchFolderConfigInput(monitor_path="/mnt/nas/incoming2", settle_window_seconds=20),
        )
        assert updated.monitor_path == "/mnt/nas/incoming2"
        assert updated.settle_window_seconds == 20

        store.delete_watch_folder_config(created.config_id)
        assert store.list_watch_folder_configs() == []

    def test_update_unknown_config_raises(self, store: MediaLifecycleStore) -> None:
        with pytest.raises(WatchFolderConfigNotFoundError):
            store.update_watch_folder_config(
                "nope", WatchFolderConfigInput(monitor_path="/x")
            )

    def test_delete_unknown_config_raises(self, store: MediaLifecycleStore) -> None:
        with pytest.raises(WatchFolderConfigNotFoundError):
            store.delete_watch_folder_config("nope")


class TestRetentionPolicyCrud:
    def test_create_list_update_delete_round_trip(self, store: MediaLifecycleStore) -> None:
        created = store.create_retention_policy(
            AssetRetentionPolicyInput(
                name="Council meetings", match_meeting_body="City Council", retention_policy="meeting"
            )
        )
        assert created.retention_policy == "meeting"

        listed = store.list_retention_policies()
        assert len(listed) == 1

        updated = store.update_retention_policy(
            created.policy_id,
            AssetRetentionPolicyInput(
                name="Council meetings", match_meeting_body="City Council", retention_policy="permanent"
            ),
        )
        assert updated.retention_policy == "permanent"

        store.delete_retention_policy(created.policy_id)
        assert store.list_retention_policies() == []

    def test_update_unknown_policy_raises(self, store: MediaLifecycleStore) -> None:
        with pytest.raises(AssetRetentionPolicyNotFoundError):
            store.update_retention_policy(
                "nope",
                AssetRetentionPolicyInput(name="x", retention_policy="default"),
            )

    def test_apply_retention_policies_matches_meeting_body(
        self, engine: Engine, store: MediaLifecycleStore
    ) -> None:
        _seed_asset(engine, asset_id="a1", meeting_body="City Council", retention_policy="default")
        _seed_asset(engine, asset_id="a2", meeting_body="Planning Board", retention_policy="default")
        store.create_retention_policy(
            AssetRetentionPolicyInput(
                name="Council -> meeting", match_meeting_body="City Council", retention_policy="meeting"
            )
        )
        changed = store.apply_retention_policies()
        assert changed == 1
        with Session(bind=engine) as session:
            a1 = session.get(Asset, "a1")
            a2 = session.get(Asset, "a2")
            assert a1 is not None and a1.retention_policy == "meeting"
            assert a2 is not None and a2.retention_policy == "default"

    def test_apply_retention_policies_with_no_rules_is_a_no_op(
        self, engine: Engine, store: MediaLifecycleStore
    ) -> None:
        _seed_asset(engine, asset_id="a1")
        assert store.apply_retention_policies() == 0


class TestStorageBudget:
    def test_totals_grouped_by_retention_policy(self, engine: Engine, store: MediaLifecycleStore) -> None:
        _seed_asset(engine, asset_id="a1", retention_policy="default", file_size_bytes=1000)
        _seed_asset(engine, asset_id="a2", retention_policy="default", file_size_bytes=2000)
        _seed_asset(engine, asset_id="a3", retention_policy="permanent", file_size_bytes=500)
        result = store.storage_budget(budget_bytes=None)
        assert result.total_bytes_used == 3500
        assert result.budget_bytes is None
        assert result.percent_used is None
        by_policy = {row.retention_policy: row for row in result.by_retention_policy}
        assert by_policy["default"].bytes_used == 3000
        assert by_policy["default"].asset_count == 2
        assert by_policy["permanent"].bytes_used == 500

    def test_percent_used_computed_against_budget(
        self, engine: Engine, store: MediaLifecycleStore
    ) -> None:
        _seed_asset(engine, asset_id="a1", file_size_bytes=500)
        result = store.storage_budget(budget_bytes=1000)
        assert result.percent_used == 50.0

    def test_null_file_size_bytes_treated_as_zero(
        self, engine: Engine, store: MediaLifecycleStore
    ) -> None:
        _seed_asset(engine, asset_id="a1", file_size_bytes=None)
        result = store.storage_budget(budget_bytes=None)
        assert result.total_bytes_used == 0


class TestReplaceSource:
    def test_apply_replace_source_unknown_asset_raises(self, store: MediaLifecycleStore) -> None:
        with pytest.raises(AssetNotFoundError):
            store.apply_replace_source(
                "nope",
                new_file_path="/x",
                file_size_bytes=1,
                codec_video="h264",
                codec_audio="aac",
                width_px=1920,
                height_px=1080,
                bitrate_bps=1_000_000,
                format_name="mov,mp4",
                duration_seconds=60,
                content_hash=None,
                thumbnail_path=None,
                archived_old_path=None,
            )

    def test_apply_replace_source_updates_asset_and_clears_stale_state(
        self, engine: Engine, store: MediaLifecycleStore
    ) -> None:
        _seed_asset(
            engine,
            asset_id="a1",
            state="rejected",
            file_path="/old/path.mp4",
            file_status="missing",
            version=3,
        )
        with Session(bind=engine) as session:
            session.add(AssetReadiness(asset_id="a1", readiness_state="rejected"))
            session.add(TranscodeJob(asset_id="a1", output_format="h264_720p_5mbps", status="failed"))
            session.commit()

        store.apply_replace_source(
            "a1",
            new_file_path="/new/path.mp4",
            file_size_bytes=54321,
            codec_video="h264",
            codec_audio="aac",
            width_px=1920,
            height_px=1080,
            bitrate_bps=5_000_000,
            format_name="mov,mp4",
            duration_seconds=120,
            content_hash="sha256:" + "a" * 64,
            thumbnail_path=None,
            archived_old_path="/old/path.mp4.replaced-abc",
        )

        with Session(bind=engine) as session:
            asset = session.get(Asset, "a1")
            assert asset is not None
            assert asset.file_path == "/new/path.mp4"
            assert asset.state == "validated"
            assert asset.file_status == "ok"
            assert asset.version == 4
            assert session.get(AssetReadiness, "a1") is None
            assert session.query(TranscodeJob).filter(TranscodeJob.asset_id == "a1").count() == 0


class TestAuditLog:
    def test_list_audit_log_filters_by_asset_and_respects_limit(
        self, engine: Engine, store: MediaLifecycleStore
    ) -> None:
        _seed_asset(engine, asset_id="a1")
        _seed_asset(engine, asset_id="a2")
        store.set_legal_hold("a1", hold=True, reason="hold-a1")
        store.set_legal_hold("a2", hold=True, reason="hold-a2")
        store.set_legal_hold("a1", hold=False, reason=None)

        all_entries = store.list_audit_log()
        assert len(all_entries) == 3

        a1_entries = store.list_audit_log(asset_id="a1")
        assert len(a1_entries) == 2
        assert all(e.asset_id == "a1" for e in a1_entries)

        limited = store.list_audit_log(limit=1)
        assert len(limited) == 1
