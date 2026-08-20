# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import civiccast.egress.models
import civiccast.schedule.models  # noqa: F401
from civiccast.db import Base, bind_engine, reset_engine
from civiccast.egress.models import (
    EgressCaptionProofSample,
    EgressCommand,
    EgressConfig,
    EgressHealthSample,
    EgressProofEvent,
    EgressSinkSpec,
    EgressStateRow,
)
from civiccast.egress.store import PostgresEgressStore


def _strip_tz(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo else value


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine("sqlite:///:memory:", future=True)
    bind_engine(eng)
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        reset_engine()
        eng.dispose()


@pytest.fixture
def store(engine: Engine) -> PostgresEgressStore:
    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    return PostgresEgressStore(factory)


def _config(*, channel_id: str = "gov", uri: str = "srt://headend.example:9000") -> EgressConfig:
    return EgressConfig(
        channel_id=channel_id,
        enabled=True,
        slate_message="CivicCast is preparing the channel.",
        loudness_target_lufs=-24.0,
        sinks=[
            EgressSinkSpec(
                kind="srt",
                label="Headend",
                uri=uri,
                secret_ref="EGRESS_SRT_PASSPHRASE",
                latency_ms=1500,
            )
        ],
    )


def test_postgres_egress_store_upserts_config_and_replaces_sinks(
    store: PostgresEgressStore,
) -> None:
    store.upsert_config(_config())

    first = store.get_config("gov")

    assert first is not None
    assert first.loudness_target_lufs == -24.0
    assert first.sinks[0].label == "Headend"
    assert first.sinks[0].secret_ref == "EGRESS_SRT_PASSPHRASE"

    store.upsert_config(
        EgressConfig(
            channel_id="gov",
            enabled=False,
            slate_message="CivicCast is offline.",
            sinks=[EgressSinkSpec(kind="file", label="Proof", uri="build/proof.ts")],
        )
    )

    second = store.get_config("gov")

    assert second is not None
    assert second.enabled is False
    assert [sink.label for sink in second.sinks] == ["Proof"]


def test_postgres_egress_store_round_trips_ndi_relay_name(
    store: PostgresEgressStore,
) -> None:
    # Issue #116: the NDI relay intent is durable; NULL means no NDI output.
    config = _config().model_copy(update={"ndi_relay_name": "CivicCast Gov"})
    store.upsert_config(config)
    loaded = store.get_config("gov")
    assert loaded is not None
    assert loaded.ndi_relay_name == "CivicCast Gov"

    store.upsert_config(loaded.model_copy(update={"ndi_relay_name": None}))
    cleared = store.get_config("gov")
    assert cleared is not None
    assert cleared.ndi_relay_name is None


def test_postgres_egress_store_round_trips_sdi_relay_device(
    store: PostgresEgressStore,
) -> None:
    # Issue #117: the SDI relay intent is durable; NULL means no SDI output.
    config = _config().model_copy(update={"sdi_relay_device": "DeckLink Mini Monitor 4K"})
    store.upsert_config(config)
    loaded = store.get_config("gov")
    assert loaded is not None
    assert loaded.sdi_relay_device == "DeckLink Mini Monitor 4K"

    store.upsert_config(loaded.model_copy(update={"sdi_relay_device": None}))
    cleared = store.get_config("gov")
    assert cleared is not None
    assert cleared.sdi_relay_device is None


def test_postgres_egress_store_round_trips_per_sink_loudness(
    store: PostgresEgressStore,
) -> None:
    # S11b: each sink's loudness regime / explicit target / tolerance and the
    # gap-B tone-strip flag are durable per sink; a plain ``inherit`` sink reads
    # back at the model defaults (so pre-0049 rows are unaffected).
    config = _config().model_copy(
        update={
            "sinks": [
                EgressSinkSpec(
                    kind="udp-ts",
                    label="Cable headend",
                    uri="udp://239.255.0.1:5000",
                    loudness_regime="atsc-a85",
                    eas_tone_strip_enabled=False,
                ),
                EgressSinkSpec(
                    kind="srt",
                    label="CDN",
                    uri="srt://cdn.example:9000",
                    loudness_regime="streaming",
                    loudness_target_lufs=-15.0,
                    loudness_tolerance_lufs=1.5,
                ),
                EgressSinkSpec(kind="file", label="Proof", uri="build/proof.ts"),
            ]
        }
    )
    store.upsert_config(config)

    loaded = store.get_config("gov")
    assert loaded is not None
    cable, cdn, proof = loaded.sinks
    assert cable.loudness_regime == "atsc-a85"
    assert cable.loudness_target_lufs is None
    assert cable.eas_tone_strip_enabled is False
    assert cdn.loudness_regime == "streaming"
    assert cdn.loudness_target_lufs == -15.0
    assert cdn.loudness_tolerance_lufs == 1.5
    assert cdn.eas_tone_strip_enabled is True
    # The untouched sink reads back at the model defaults.
    assert proof.loudness_regime == "inherit"
    assert proof.loudness_target_lufs is None
    assert proof.loudness_tolerance_lufs is None
    assert proof.eas_tone_strip_enabled is True


def test_postgres_egress_store_caption_proof_round_trip(
    store: PostgresEgressStore,
) -> None:
    # S11a: caption decode-back proofs persist; latest reflects the newest sample,
    # and recent() returns newest-first.
    boundary = "egress-caption-embed-to-emitted-stream-decode-back"
    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    store.append_caption_proof_sample(
        EgressCaptionProofSample(
            channel_id="gov",
            sampled_at=t0,
            status="FAIL",
            caption_status="not-verified",
            mode="cea-708",
            decoder_name="ffmpeg-readeia608",
            expected_cue_count=2,
            decoded_cue_count=0,
            matched_cue_count=0,
            proof_boundary=boundary,
            blocker="EGRESS_CAPTION_DECODE_BACK_MISMATCH",
        )
    )
    store.append_caption_proof_sample(
        EgressCaptionProofSample(
            channel_id="gov",
            sampled_at=t0 + timedelta(seconds=30),
            status="PASS",
            caption_status="on",
            mode="cea-708",
            decoder_name="ffmpeg-readeia608",
            expected_cue_count=2,
            decoded_cue_count=2,
            matched_cue_count=2,
            max_timing_delta_seconds=0.1,
            proof_boundary=boundary,
        )
    )

    latest = store.latest_caption_proof_sample("gov")
    assert latest is not None
    assert latest.status == "PASS"
    assert latest.caption_status == "on"
    assert latest.matched_cue_count == 2

    recent = store.recent_caption_proof_samples("gov", 5)
    assert [s.status for s in recent] == ["PASS", "FAIL"]
    assert store.latest_caption_proof_sample("other-channel") is None


def test_postgres_egress_store_lists_configs_in_channel_order(
    store: PostgresEgressStore,
) -> None:
    store.upsert_config(_config(channel_id="schools"))
    store.upsert_config(_config(channel_id="gov"))

    configs = store.list_configs()

    assert [config.channel_id for config in configs] == ["gov", "schools"]
    assert [config.sinks[0].label for config in configs] == ["Headend", "Headend"]


def test_postgres_egress_store_commands_are_idempotent_and_consumed(
    store: PostgresEgressStore,
) -> None:
    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    later = EgressCommand(
        channel_id="gov",
        action="stop",
        issued_at=now + timedelta(seconds=1),
        issued_by="operator",
        command_id="cmd-2",
    )
    earlier = EgressCommand(
        channel_id="gov",
        action="start",
        issued_at=now,
        issued_by="operator",
        command_id="cmd-1",
    )

    store.enqueue_command(later)
    store.enqueue_command(earlier)
    store.enqueue_command(earlier)

    popped = store.pop_pending_commands("gov")

    assert [cmd.command_id for cmd in popped] == ["cmd-1", "cmd-2"]
    assert store.pop_pending_commands("gov") == []
    store.enqueue_command(earlier)
    assert store.pop_pending_commands("gov") == []


def test_postgres_egress_store_state_and_recent_health(store: PostgresEgressStore) -> None:
    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    state = EgressStateRow(
        channel_id="gov",
        state="ON_AIR",
        current_source_label="Council meeting",
        current_proof_event_id="proof-1",
        updated_at=now,
        pid=4242,
    )

    store.write_state(state)
    store.append_health(
        EgressHealthSample(
            channel_id="gov",
            sampled_at=now,
            state="ON_AIR",
            sink_connected={"Headend": True},
            encoder_fps=30.0,
            seconds_on_air=10,
            caption_status="not-verified",
        )
    )
    store.append_health(
        EgressHealthSample(
            channel_id="gov",
            sampled_at=now + timedelta(seconds=1),
            state="ON_AIR",
            sink_connected={"Headend": True},
            encoder_fps=30.0,
            seconds_on_air=11,
            caption_status="on",
        )
    )

    got = store.read_state("gov")
    assert got is not None
    assert got.model_copy(update={"updated_at": _strip_tz(got.updated_at)}) == state.model_copy(
        update={"updated_at": _strip_tz(state.updated_at)}
    )
    assert [sample.seconds_on_air for sample in store.recent_health("gov", 2)] == [11, 10]
    assert [sample.caption_status for sample in store.recent_health("gov", 2)] == [
        "on",
        "not-verified",
    ]


def test_postgres_egress_store_trims_old_health_samples(store: PostgresEgressStore) -> None:
    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    store.append_health(
        EgressHealthSample(
            channel_id="gov",
            sampled_at=now - timedelta(days=8),
            state="ON_AIR",
            sink_connected={"Headend": True},
        )
    )
    store.append_health(
        EgressHealthSample(
            channel_id="gov",
            sampled_at=now - timedelta(days=1),
            state="ON_AIR",
            sink_connected={"Headend": True},
        )
    )

    assert store.trim_health_before(now - timedelta(days=7)) == 1

    assert [sample.sampled_at for sample in store.recent_health("gov", 10)] == [
        now.replace(tzinfo=None) - timedelta(days=1)
    ]


def test_postgres_egress_store_appends_recent_proof_events(
    store: PostgresEgressStore,
) -> None:
    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    older = EgressProofEvent(
        event_id="proof-1",
        observed_at=now,
        channel_id="gov",
        state="ON_AIR",
        source_label="Council meeting",
        source_path="prepared/council.ts",
        source_ref="asset-council",
        proof_boundary="civiccast-egress-handoff-boundary",
        machine_summary="Council meeting went to air.",
    )
    newer = older.model_copy(
        update={
            "event_id": "proof-2",
            "observed_at": now + timedelta(seconds=1),
            "source_label": "Station slate",
        }
    )

    store.append_proof_event(older)
    store.append_proof_event(newer)
    store.append_proof_event(older)

    events = store.recent_proof_events("gov", 2)

    assert [event.event_id for event in events] == ["proof-2", "proof-1"]
    assert [event.source_ref for event in events] == ["asset-council", "asset-council"]
    assert events[0].proof_boundary == "civiccast-egress-handoff-boundary"


def test_health_sample_schema_currency_round_trip(store: PostgresEgressStore) -> None:
    store.append_health(
        EgressHealthSample(
            channel_id="gov",
            sampled_at=datetime.now(UTC),
            state="ON_AIR",
            schema_version=7,
            proof_events_appended_since_last_sample=23,
        )
    )
    got = store.recent_health("gov", 1)[0]
    assert got.schema_version == 7
    assert got.proof_events_appended_since_last_sample == 23


def test_health_sample_defaults_round_trip(store: PostgresEgressStore) -> None:
    # an unset sample defaults schema_version to the current code version, churn to 0
    from civiccast.egress.schema_currency import current_schema_version

    store.append_health(
        EgressHealthSample(channel_id="gov", sampled_at=datetime.now(UTC), state="ON_AIR")
    )
    got = store.recent_health("gov", 1)[0]
    assert got.schema_version == current_schema_version()
    assert got.proof_events_appended_since_last_sample == 0
