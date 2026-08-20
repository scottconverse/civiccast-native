# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S12 (build step 8) slice 1 — OTT build-record + submission entities + store.

Covers civiccast.app_platform.build_models (AppBuildRecord sha256 validator +
StoreSubmissionMetadata) and civiccast.app_platform.build_store.AppBuildStore
(append-only build log, per-target submission upsert, file persistence
round-trip).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from civiccast.app_platform.build_models import AppBuildRecord, StoreSubmissionMetadata
from civiccast.app_platform.build_store import AppBuildStore, AppBuildStoreError

_T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
_SHA = "a" * 64


def _record(
    record_id: str = "bld_1", *, app_target: str = "web_pwa", built_at: datetime = _T0
) -> AppBuildRecord:
    return AppBuildRecord(
        record_id=record_id,
        station_id="civiccast-station",
        app_target=app_target,  # type: ignore[arg-type]
        build_tier="unbranded",
        app_name="CivicCast",
        channels=[{"channel_id": "public"}],
        artifact_path=f"build/{record_id}.zip",
        artifact_sha256=_SHA,
        entry_point="index.html",
        manifest_json={"appTarget": app_target},
        built_at=built_at,
        built_by="op_a",
    )


def _submission(app_target: str = "roku", **kwargs: object) -> StoreSubmissionMetadata:
    base: dict[str, object] = {"app_target": app_target, "version_code": 1, "version_name": "0.1.0"}
    base.update(kwargs)
    return StoreSubmissionMetadata(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_sha256_validator_normalizes_and_rejects() -> None:
    rec = _record()
    # An uppercase 64-char hex is normalized to lowercase by the field validator.
    upper = AppBuildRecord.model_validate({**rec.model_dump(), "artifact_sha256": "A" * 64})
    assert upper.artifact_sha256 == "a" * 64
    # A too-short value trips the length constraint; a 64-char non-hex value
    # trips the validator's "64 lowercase hex" message.
    with pytest.raises(ValidationError):
        AppBuildRecord.model_validate({**rec.model_dump(), "artifact_sha256": "xyz"})
    with pytest.raises(ValidationError, match="64 lowercase hex"):
        AppBuildRecord.model_validate({**rec.model_dump(), "artifact_sha256": "g" * 64})


def test_submission_defaults() -> None:
    sub = _submission()
    assert sub.submission_status == "draft"
    assert sub.published_url is None


# ---------------------------------------------------------------------------
# Build log (append-only)
# ---------------------------------------------------------------------------


def test_add_get_list_builds_newest_first() -> None:
    store = AppBuildStore()
    store.add_build(_record("bld_old", built_at=datetime(2026, 1, 1, tzinfo=UTC)))
    store.add_build(_record("bld_new", built_at=datetime(2026, 6, 1, tzinfo=UTC)))
    assert store.get_build("bld_new") is not None
    assert store.get_build("missing") is None
    assert [r.record_id for r in store.list_builds()] == ["bld_new", "bld_old"]


def test_add_build_rejects_duplicate_record_id() -> None:
    store = AppBuildStore()
    store.add_build(_record("bld_1"))
    with pytest.raises(AppBuildStoreError, match="already exists"):
        store.add_build(_record("bld_1"))


def test_list_builds_filters_by_target() -> None:
    store = AppBuildStore()
    store.add_build(_record("bld_web", app_target="web_pwa"))
    store.add_build(_record("bld_roku", app_target="roku"))
    assert [r.record_id for r in store.list_builds(app_target="roku")] == ["bld_roku"]


# ---------------------------------------------------------------------------
# Submissions (upsert per target)
# ---------------------------------------------------------------------------


def test_submission_upsert_is_per_target() -> None:
    store = AppBuildStore()
    store.upsert_submission(_submission("roku", submission_status="draft"))
    store.upsert_submission(_submission("roku", submission_status="pending_review", version_code=2))
    store.upsert_submission(_submission("tvos"))
    roku = store.get_submission("roku")
    assert (
        roku is not None and roku.submission_status == "pending_review" and roku.version_code == 2
    )
    assert {s.app_target for s in store.list_submissions()} == {"roku", "tvos"}


# ---------------------------------------------------------------------------
# File persistence round-trip
# ---------------------------------------------------------------------------


def test_file_persistence_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "app-builds.json"
    store = AppBuildStore(path)
    store.add_build(_record("bld_1", app_target="roku"))
    store.upsert_submission(
        _submission("roku", submission_status="published", published_url="https://x")
    )
    assert path.exists()

    # A fresh store at the same path reloads both collections.
    reloaded = AppBuildStore(path)
    got = reloaded.get_build("bld_1")
    assert got is not None and got.app_target == "roku" and got.artifact_sha256 == _SHA
    sub = reloaded.get_submission("roku")
    assert (
        sub is not None
        and sub.submission_status == "published"
        and sub.published_url == "https://x"
    )


def test_ephemeral_store_without_path_does_not_persist() -> None:
    store = AppBuildStore()  # no path -> in-memory only
    store.add_build(_record("bld_1"))
    assert store.get_build("bld_1") is not None  # works in-process, just not persisted


def test_persist_failure_raises_store_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A write failure (disk full / permission) during persistence must surface as
    # AppBuildStoreError, not a bare OSError, so the router can map it to a 503.
    store = AppBuildStore(tmp_path / "app-builds.json")

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", _boom)
    with pytest.raises(AppBuildStoreError, match="Could not write"):
        store.add_build(_record("bld_x"))
