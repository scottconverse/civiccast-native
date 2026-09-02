# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""LiveSourceStore.update + record_probe_observation (WP-07).

``LiveSourceStore``'s Slice 1 docstring deferred ``update`` "until a later rung
defines the operator-cancel + edit UX". WP-07 is that rung, and the edit is
load-bearing for readiness rather than cosmetic: an edited source must not
inherit the previous address's observation.

Locked here:

* an edit that changes what would be probed clears readiness in the same
  transaction; a rename does not;
* ``probe_last_success_at`` survives both an edit and a later failure, so
  "never worked" stays distinguishable from "worked until 09:41";
* validation is applied to the MERGED row, not to the request body, so
  flipping only ``source_type`` is checked against the stored endpoint;
* optimistic concurrency: a stale ``expected_row_version`` is refused;
* a credential handle may only be stored on a source type that can execute it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import civiccast.live.models
import civiccast.schedule.models  # noqa: F401  (owns the SQLite ATTACH hook)
from civiccast.db import Base, bind_engine, reset_engine
from civiccast.live.models import LiveSourceCreate, LiveSourceUpdate
from civiccast.live.store import (
    LiveSourceConcurrencyError,
    LiveSourceNotFoundError,
    LiveSourceStore,
)

_NOW = datetime(2026, 9, 2, 18, 0, 0, tzinfo=UTC)


@pytest.fixture
def store() -> Iterator[LiveSourceStore]:
    engine: Engine = create_engine("sqlite:///:memory:", future=True)
    bind_engine(engine)
    Base.metadata.create_all(engine)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    try:
        yield LiveSourceStore(factory)
    finally:
        reset_engine()
        engine.dispose()


def _create(
    store: LiveSourceStore,
    *,
    live_source_id: str = "council-encoder",
    source_type: str = "srt",
    endpoint_url: str = "srt://0.0.0.0:9000?mode=listener",
    credentials_handle: str | None = None,
):  # type: ignore[no-untyped-def]
    return store.create(
        LiveSourceCreate(
            live_source_id=live_source_id,
            channel_id="gov-ch12",
            name="Council Room Encoder",
            source_type=source_type,  # type: ignore[arg-type]
            endpoint_url=endpoint_url,
            credentials_handle=credentials_handle,
        )
    )


def _mark_ready(store: LiveSourceStore, live_source_id: str, *, at: datetime | None = None):  # type: ignore[no-untyped-def]
    return store.record_probe_observation(
        live_source_id,
        ok=True,
        observed_at=at or datetime.now(UTC),
        detail="Council Room Encoder is delivering video; server-side media probe passed.",
        error_code=None,
    )


class TestCreateDefaults:
    def test_a_new_source_is_never_probed_not_ready(self, store: LiveSourceStore) -> None:
        created = _create(store)
        assert created.probe_state == "never_probed"
        assert created.probe_observed_at is None
        assert created.probe_last_success_at is None
        assert created.readiness == "never_probed"
        assert created.observation_age_seconds is None
        assert created.row_version == 1

    def test_response_reports_the_applied_ttl(self, store: LiveSourceStore) -> None:
        assert _create(store).readiness_ttl_seconds == 30


class TestProbeObservationPersistence:
    def test_success_sets_ready_and_last_success(self, store: LiveSourceStore) -> None:
        _create(store)
        row = _mark_ready(store, "council-encoder", at=_NOW)
        assert row.probe_state == "ready"
        assert row.probe_observed_at is not None
        assert row.probe_last_success_at is not None
        assert row.probe_error_code is None

    def test_failure_keeps_the_earlier_success_timestamp(self, store: LiveSourceStore) -> None:
        _create(store)
        _mark_ready(store, "council-encoder", at=_NOW)
        failed = store.record_probe_observation(
            "council-encoder",
            ok=False,
            observed_at=_NOW + timedelta(minutes=5),
            detail="Council Room Encoder did not respond to a server-side media probe.",
            error_code="probe_refused",
        )
        assert failed.probe_state == "failed"
        assert failed.probe_error_code == "probe_refused"
        # "Never worked" and "worked until five minutes ago" are different
        # facts, and the operator needs both.
        assert failed.probe_last_success_at is not None

    def test_detail_is_truncated_at_the_write(self, store: LiveSourceStore) -> None:
        _create(store)
        row = store.record_probe_observation(
            "council-encoder",
            ok=False,
            observed_at=_NOW,
            detail="x" * 5000,
            error_code="probe_refused",
        )
        assert row.probe_detail is not None
        assert len(row.probe_detail) == 400

    def test_missing_row_raises_not_found(self, store: LiveSourceStore) -> None:
        with pytest.raises(LiveSourceNotFoundError):
            store.record_probe_observation(
                "nope", ok=True, observed_at=_NOW, detail="", error_code=None
            )


class TestUpdateInvalidatesReadiness:
    def test_endpoint_change_clears_readiness_immediately(self, store: LiveSourceStore) -> None:
        _create(store)
        _mark_ready(store, "council-encoder")
        edited = store.update(
            "council-encoder", LiveSourceUpdate(endpoint_url="srt://0.0.0.0:9100?mode=listener")
        )
        assert edited.endpoint_url == "srt://0.0.0.0:9100?mode=listener"
        assert edited.probe_state == "never_probed"
        assert edited.probe_observed_at is None
        assert edited.readiness == "never_probed"
        # History survives; readiness does not.
        assert edited.probe_last_success_at is not None

    def test_source_type_change_clears_readiness(self, store: LiveSourceStore) -> None:
        _create(store, source_type="rtsp", endpoint_url="rtsp://camera.local/stream1")
        _mark_ready(store, "council-encoder")
        edited = store.update("council-encoder", LiveSourceUpdate(source_type="rtsp"))
        # Same value, but the request asked to set it, so the previous probe is
        # no longer evidence about the row as now defined.
        assert edited.probe_state == "never_probed"

    def test_channel_change_clears_readiness(self, store: LiveSourceStore) -> None:
        _create(store)
        _mark_ready(store, "council-encoder")
        edited = store.update("council-encoder", LiveSourceUpdate(channel_id="gov-ch13"))
        assert edited.channel_id == "gov-ch13"
        assert edited.probe_state == "never_probed"

    def test_credential_change_clears_readiness(self, store: LiveSourceStore) -> None:
        _create(store)
        _mark_ready(store, "council-encoder")
        edited = store.update(
            "council-encoder", LiveSourceUpdate(credentials_handle="council-srt-passphrase")
        )
        assert edited.credentials_handle == "council-srt-passphrase"
        assert edited.probe_state == "never_probed"

    def test_clearing_the_credential_also_clears_readiness(self, store: LiveSourceStore) -> None:
        _create(store, credentials_handle="council-srt-passphrase")
        _mark_ready(store, "council-encoder")
        edited = store.update("council-encoder", LiveSourceUpdate(clear_credentials_handle=True))
        assert edited.credentials_handle is None
        assert edited.probe_state == "never_probed"

    def test_rename_alone_does_not_clear_readiness(self, store: LiveSourceStore) -> None:
        # Renaming a camera thirty seconds before gavel must not force a
        # re-probe: the name is not part of what gets probed.
        _create(store)
        _mark_ready(store, "council-encoder")
        edited = store.update("council-encoder", LiveSourceUpdate(name="Council Chamber Encoder"))
        assert edited.name == "Council Chamber Encoder"
        assert edited.probe_state == "ready"
        assert edited.readiness == "ready"


class TestUpdateValidation:
    def test_validation_runs_against_the_merged_row(self, store: LiveSourceStore) -> None:
        # Only source_type is sent. It must be judged against the endpoint the
        # row already holds, not accepted because the body did not mention one.
        _create(store, source_type="srt", endpoint_url="srt://0.0.0.0:9000?mode=listener")
        with pytest.raises(ValueError, match="RTSP source needs"):
            store.update("council-encoder", LiveSourceUpdate(source_type="rtsp"))

    def test_bad_endpoint_for_the_existing_type_is_rejected(self, store: LiveSourceStore) -> None:
        _create(store)
        with pytest.raises(ValueError):
            store.update(
                "council-encoder", LiveSourceUpdate(endpoint_url="https://encoder.example/x.m3u8")
            )

    def test_endpoint_is_normalized_on_update(self, store: LiveSourceStore) -> None:
        _create(store, source_type="rtmp", endpoint_url="rtmp://encoder.local/live/a")
        edited = store.update(
            "council-encoder", LiveSourceUpdate(endpoint_url="RTMPS://encoder.local:1935/live/a")
        )
        assert edited.endpoint_url == "rtmps://encoder.local:1935/live/a"

    def test_credential_on_an_unsupported_type_is_rejected(self, store: LiveSourceStore) -> None:
        _create(store, source_type="rtsp", endpoint_url="rtsp://camera.local/stream1")
        with pytest.raises(ValueError, match="RTSP camera"):
            store.update("council-encoder", LiveSourceUpdate(credentials_handle="cam-password"))

    def test_switching_a_credentialed_srt_row_to_rtsp_is_rejected(
        self, store: LiveSourceStore
    ) -> None:
        # The credential would survive the type change and become unexecutable.
        _create(store, credentials_handle="council-srt-passphrase")
        with pytest.raises(ValueError):
            store.update(
                "council-encoder",
                LiveSourceUpdate(source_type="rtsp", endpoint_url="rtsp://camera.local/stream1"),
            )

    def test_empty_update_is_rejected_at_the_model(self) -> None:
        with pytest.raises(ValueError, match="at least one field"):
            LiveSourceUpdate()

    def test_setting_and_clearing_the_credential_at_once_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="not both"):
            LiveSourceUpdate(credentials_handle="x", clear_credentials_handle=True)

    def test_missing_row_raises_not_found(self, store: LiveSourceStore) -> None:
        with pytest.raises(LiveSourceNotFoundError):
            store.update("nope", LiveSourceUpdate(name="whatever"))


class TestOptimisticConcurrency:
    def test_row_version_increments_on_every_applied_edit(self, store: LiveSourceStore) -> None:
        _create(store)
        first = store.update("council-encoder", LiveSourceUpdate(name="One"))
        second = store.update("council-encoder", LiveSourceUpdate(name="Two"))
        assert (first.row_version, second.row_version) == (2, 3)

    def test_matching_expected_version_is_accepted(self, store: LiveSourceStore) -> None:
        created = _create(store)
        edited = store.update(
            "council-encoder",
            LiveSourceUpdate(name="One", expected_row_version=created.row_version),
        )
        assert edited.name == "One"

    def test_stale_expected_version_is_refused(self, store: LiveSourceStore) -> None:
        created = _create(store)
        store.update("council-encoder", LiveSourceUpdate(name="First operator wins"))
        with pytest.raises(LiveSourceConcurrencyError) as exc:
            store.update(
                "council-encoder",
                LiveSourceUpdate(name="Second operator", expected_row_version=created.row_version),
            )
        assert exc.value.expected == 1
        assert exc.value.actual == 2
        # The first operator's edit is intact.
        current = store.get("council-encoder")
        assert current is not None
        assert current.name == "First operator wins"

    def test_omitting_the_expected_version_is_last_writer_wins(
        self, store: LiveSourceStore
    ) -> None:
        _create(store)
        store.update("council-encoder", LiveSourceUpdate(name="One"))
        edited = store.update("council-encoder", LiveSourceUpdate(name="Two"))
        assert edited.name == "Two"
