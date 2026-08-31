# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import civiccast.egress.models
import civiccast.schedule.models  # noqa: F401
from civiccast.app import create_app
from civiccast.db import Base, bind_engine, reset_engine
from civiccast.egress.models import (
    EgressCaptionProofSample,
    EgressHealthSample,
    EgressProofEvent,
    EgressStateRow,
)
from civiccast.egress.router import get_egress_store
from civiccast.egress.store import PostgresEgressStore


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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


@pytest.fixture
def client(store: PostgresEgressStore) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_egress_store] = lambda: store
    with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c:
        yield c


def _config_payload(channel_id: str = "gov") -> dict[str, object]:
    return {
        "channel_id": channel_id,
        "enabled": True,
        "slate_message": "CivicCast is preparing the channel.",
        "sinks": [
            {
                "kind": "srt",
                "label": "Headend",
                "uri": "srt://headend.example:9000",
                "secret_ref": "EGRESS_SRT_PASSPHRASE",
            }
        ],
    }


def test_staff_egress_config_round_trip(client: TestClient) -> None:
    r = client.put("/api/staff/egress/channels/gov/config", json=_config_payload())
    assert r.status_code == 200, r.text
    assert r.json()["sinks"][0]["label"] == "Headend"

    r = client.get("/api/staff/egress/channels/gov/config")
    assert r.status_code == 200
    assert r.json()["channel_id"] == "gov"


def test_staff_egress_config_accepts_hls_sink(client: TestClient) -> None:
    """DEFECT A: this exact repro (PUT an hls sink, 200 OK) used to crash the
    channel on the following ``start``. It still returns 200 — hls is now a
    genuinely supported sink kind for the default GStreamer engine — but see
    ``test_hls_relay.py``/``test_gst_bridge.py`` for proof it no longer
    crashes the channel, not just that the API accepts it."""
    payload = _config_payload() | {
        "sinks": [{"kind": "hls", "label": "Web", "uri": "C:/CivicCast/live/gov"}]
    }
    r = client.put("/api/staff/egress/channels/gov/config", json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["sinks"][0]["kind"] == "hls"


def test_staff_egress_config_rejects_unsupported_sink_kind_at_save_time(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DEFECT B: an accept-then-crash gap is the actual root defect — a
    sink kind the active engine cannot run must be refused HERE, at config
    save, with a clear reason, not accepted with 200 OK and left to explode
    deep inside a later ``start`` pass. rtmp is genuinely unsupported by the
    default (GStreamer) engine in Stage 1."""
    monkeypatch.delenv("CIVICCAST_EGRESS_ENGINE", raising=False)  # ensure GStreamer default
    payload = _config_payload() | {
        "sinks": [{"kind": "rtmp", "label": "Restream", "uri": "rtmp://example.com/live"}]
    }
    r = client.put("/api/staff/egress/channels/gov/config", json=payload)
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "rtmp" in detail
    # The message must name what IS supported, not just what wasn't.
    for kind in ("srt", "local-ts", "udp-ts", "file", "sdi", "hls"):
        assert kind in detail

    # And the config must NOT have been persisted (a 422 that still wrote the
    # row would be the same accept-then-crash gap with extra steps).
    r = client.get("/api/staff/egress/channels/gov/config")
    assert r.status_code == 404


def test_staff_egress_graphics_overlay_round_trip(client: TestClient) -> None:
    """A-3: the operator's lower-third toggle + text persist through the
    dedicated GET/PUT endpoint and flow back to the full config GET (proving
    it lands on the same durable EgressConfig row the playout-graph builder
    reads, not a side channel)."""
    assert (
        client.put("/api/staff/egress/channels/gov/config", json=_config_payload()).status_code
        == 200
    )

    # Default is off/blank before any operator ever sets it.
    r = client.get("/api/staff/egress/channels/gov/graphics-overlay")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "channel_id": "gov",
        "graphics_overlay_enabled": False,
        "graphics_overlay_lower_third_text": "",
    }

    r = client.put(
        "/api/staff/egress/channels/gov/graphics-overlay",
        json={
            "graphics_overlay_enabled": True,
            "graphics_overlay_lower_third_text": "Town Council - Live",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json() == {
        "channel_id": "gov",
        "graphics_overlay_enabled": True,
        "graphics_overlay_lower_third_text": "Town Council - Live",
    }

    # Get-after-set round trip via the dedicated endpoint...
    r = client.get("/api/staff/egress/channels/gov/graphics-overlay")
    assert r.status_code == 200
    assert r.json()["graphics_overlay_enabled"] is True
    assert r.json()["graphics_overlay_lower_third_text"] == "Town Council - Live"

    # ...and via the full channel config, proving it's the same durable row.
    r = client.get("/api/staff/egress/channels/gov/config")
    assert r.status_code == 200
    assert r.json()["graphics_overlay_enabled"] is True
    assert r.json()["graphics_overlay_lower_third_text"] == "Town Council - Live"

    # Take it back off air.
    r = client.put(
        "/api/staff/egress/channels/gov/graphics-overlay",
        json={
            "graphics_overlay_enabled": False,
            "graphics_overlay_lower_third_text": "Town Council - Live",
        },
    )
    assert r.status_code == 200
    assert r.json()["graphics_overlay_enabled"] is False


def test_staff_egress_graphics_overlay_404_before_config_exists(client: TestClient) -> None:
    r = client.get("/api/staff/egress/channels/never-configured/graphics-overlay")
    assert r.status_code == 404

    r = client.put(
        "/api/staff/egress/channels/never-configured/graphics-overlay",
        json={"graphics_overlay_enabled": True, "graphics_overlay_lower_third_text": "x"},
    )
    assert r.status_code == 404


def test_staff_egress_graphics_overlay_rejects_control_characters(client: TestClient) -> None:
    """MINOR fix (2026-08-30 audit): mirrors ``ndi_relay_name``/``sdi_relay_device``'s
    ``clean_relay_identifier`` control-char rule for the lower-third text -- rejected
    at save time so a poisoned string can never reach
    ``graphics_overlay_leg_from_config``'s rendered banner PNG.

    This exercises the PUT endpoint itself, not just the ``EgressConfig`` model: the
    endpoint applies the payload via ``EgressConfig.model_copy(update=...)``, which
    does NOT re-run ``EgressConfig``'s own field validators -- so the request body
    model (``GraphicsOverlayUpdateRequest``) needs the identical check, or a control
    character would sail straight past the model-level validator through this
    endpoint's actual write path (the real regression this test targets)."""
    assert (
        client.put("/api/staff/egress/channels/gov/config", json=_config_payload()).status_code
        == 200
    )

    r = client.put(
        "/api/staff/egress/channels/gov/graphics-overlay",
        json={
            "graphics_overlay_enabled": True,
            "graphics_overlay_lower_third_text": "Council\x07Room",
        },
    )
    assert r.status_code == 422, r.text
    assert "control characters" in r.text

    # And the config must NOT have been persisted (a 422 that still wrote the row
    # would be the same accept-then-crash gap with extra steps).
    r = client.get("/api/staff/egress/channels/gov/graphics-overlay")
    assert r.status_code == 200
    assert r.json()["graphics_overlay_lower_third_text"] == ""


def test_staff_egress_config_rtmp_allowed_on_ffmpeg_concat_engine(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The validation is engine-aware: rtmp is fully implemented by the
    ffmpeg-concat engine's RtmpSink, so it must not be rejected there."""
    monkeypatch.setenv("CIVICCAST_EGRESS_ENGINE", "ffmpeg-concat")
    payload = _config_payload() | {
        "sinks": [{"kind": "rtmp", "label": "Restream", "uri": "rtmp://example.com/live"}]
    }
    r = client.put("/api/staff/egress/channels/gov/config", json=payload)
    assert r.status_code == 200, r.text


def test_staff_egress_channel_list_and_detail(
    client: TestClient,
    store: PostgresEgressStore,
) -> None:
    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    assert (
        client.put("/api/staff/egress/channels/gov/config", json=_config_payload()).status_code
        == 200
    )
    store.write_state(
        EgressStateRow(
            channel_id="gov",
            state="ON_AIR",
            current_source_label="Council meeting",
            current_proof_event_id="proof-1",
            updated_at=now,
            pid=1234,
        )
    )
    store.append_health(
        EgressHealthSample(
            channel_id="gov",
            sampled_at=now,
            state="ON_AIR",
            sink_connected={"Headend": True},
            encoder_fps=30.0,
            seconds_on_air=12,
            caption_status="not-verified",
        )
    )

    r = client.get("/api/staff/egress/channels")

    assert r.status_code == 200
    assert r.json()[0]["channel_id"] == "gov"
    assert r.json()[0]["sink_count"] == 1
    assert r.json()[0]["state"]["state"] == "ON_AIR"
    assert r.json()[0]["latest_health"]["seconds_on_air"] == 12

    r = client.get("/api/staff/egress/channels/gov")

    assert r.status_code == 200
    assert r.json()["config"]["channel_id"] == "gov"
    assert r.json()["state"]["current_source_label"] == "Council meeting"
    assert r.json()["latest_health"]["caption_status"] == "not-verified"


def test_public_egress_now_is_viewer_safe(
    client: TestClient,
    store: PostgresEgressStore,
) -> None:
    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    store.write_state(
        EgressStateRow(
            channel_id="gov",
            state="ON_AIR",
            current_source_label="Council meeting",
            current_proof_event_id="proof-1",
            updated_at=now,
            pid=1234,
            last_error="internal detail",
        )
    )
    store.append_health(
        EgressHealthSample(
            channel_id="gov",
            sampled_at=now,
            state="ON_AIR",
            sink_connected={"Headend": True},
            encoder_fps=30.0,
            seconds_on_air=12,
            caption_status="not-verified",
        )
    )

    r = client.get("/api/public/egress/channels/gov/now", headers={})

    assert r.status_code == 200
    body = r.json()
    assert body["channel_id"] == "gov"
    assert body["state"] == "ON_AIR"
    assert body["current_source_label"] == "Council meeting"
    assert body["updated_at"].startswith("2026-06-05T12:00:00")
    assert body["caption_status"] == "not-verified"
    assert body["seconds_on_air"] == 12
    assert "pid" not in body
    assert "current_proof_event_id" not in body
    assert "sink_connected" not in body
    assert "last_error" not in body


def test_staff_egress_config_path_body_mismatch_is_422(client: TestClient) -> None:
    r = client.put("/api/staff/egress/channels/gov/config", json=_config_payload("schools"))

    assert r.status_code == 422
    assert "does not match" in r.json()["detail"]


def test_staff_egress_command_is_queued_for_daemon(
    client: TestClient,
    store: PostgresEgressStore,
) -> None:
    r = client.post(
        "/api/staff/egress/channels/gov/commands",
        json={"action": "start"},
    )

    assert r.status_code == 202
    body = r.json()
    assert body["queued"] is True
    assert body["command"]["command_id"].startswith("egress-")
    assert body["command"]["issued_by"] == "operator-token-a"
    assert [cmd.command_id for cmd in store.pop_pending_commands("gov")] == [
        body["command"]["command_id"]
    ]


def test_staff_egress_command_rejects_client_supplied_actor(client: TestClient) -> None:
    r = client.post(
        "/api/staff/egress/channels/gov/commands",
        json={"action": "start", "issued_by": "spoofed-operator"},
    )

    assert r.status_code == 422
    assert "Extra inputs are not permitted" in r.text


def test_staff_egress_state_and_health_reads(
    client: TestClient,
    store: PostgresEgressStore,
) -> None:
    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    store.write_state(
        EgressStateRow(
            channel_id="gov",
            state="ON_AIR",
            current_source_label="Council meeting",
            current_proof_event_id="proof-1",
            updated_at=now,
            pid=1234,
        )
    )
    store.append_health(
        EgressHealthSample(
            channel_id="gov",
            sampled_at=now,
            state="ON_AIR",
            sink_connected={"Headend": True},
            encoder_fps=30.0,
            seconds_on_air=5,
            caption_status="not-verified",
        )
    )

    r = client.get("/api/staff/egress/channels/gov/state")
    assert r.status_code == 200
    assert r.json()["state"] == "ON_AIR"

    r = client.get("/api/staff/egress/channels/gov/health")
    assert r.status_code == 200
    assert r.json()[0]["seconds_on_air"] == 5
    assert r.json()[0]["caption_status"] == "not-verified"


def test_staff_egress_schema_currency_reports_current_and_drift(
    client: TestClient,
    store: PostgresEgressStore,
) -> None:
    from civiccast.egress.schema_currency import current_schema_version

    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)

    # No sample yet → current (nothing to drift against).
    r = client.get("/api/staff/egress/channels/gov/schema-currency")
    assert r.status_code == 200
    body = r.json()
    assert body["is_current"] is True
    assert body["sample_schema_version"] is None

    # A sample at the running schema version → current, with the proof-churn count.
    store.append_health(
        EgressHealthSample(
            channel_id="gov",
            sampled_at=now,
            state="ON_AIR",
            schema_version=current_schema_version(),
            proof_events_appended_since_last_sample=7,
        )
    )
    body = client.get("/api/staff/egress/channels/gov/schema-currency").json()
    assert body["is_current"] is True
    assert body["sample_schema_version"] == current_schema_version()
    assert body["proof_events_appended_since_last_sample"] == 7

    # A newer sample written by a DIFFERENT schema version → drift flagged.
    store.append_health(
        EgressHealthSample(
            channel_id="gov",
            sampled_at=datetime(2026, 6, 5, 12, 1, tzinfo=UTC),
            state="ON_AIR",
            schema_version=current_schema_version() + 1,
            proof_events_appended_since_last_sample=0,
        )
    )
    body = client.get("/api/staff/egress/channels/gov/schema-currency").json()
    assert body["is_current"] is False
    assert body["sample_schema_version"] == current_schema_version() + 1

    # Negative direction: a NEWER current-version sample (e.g. after the operator
    # upgrades the code) must clear the badge to green even though an OLDER drift
    # sample still sits in the table — the surface reflects the LATEST sample only,
    # not "any sample ever drifted" (a regression that kept it red would ship green).
    store.append_health(
        EgressHealthSample(
            channel_id="gov",
            sampled_at=datetime(2026, 6, 5, 12, 2, tzinfo=UTC),
            state="ON_AIR",
            schema_version=current_schema_version(),
            proof_events_appended_since_last_sample=0,
        )
    )
    body = client.get("/api/staff/egress/channels/gov/schema-currency").json()
    assert body["is_current"] is True
    assert body["sample_schema_version"] == current_schema_version()


def test_staff_egress_proof_reads_recent_events(
    client: TestClient,
    store: PostgresEgressStore,
) -> None:
    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    store.append_proof_event(
        EgressProofEvent(
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
    )

    r = client.get("/api/staff/egress/channels/gov/proof")

    assert r.status_code == 200
    body = r.json()
    assert body[0]["event_id"] == "proof-1"
    assert body[0]["source_ref"] == "asset-council"
    assert body[0]["proof_boundary"] == "civiccast-egress-handoff-boundary"


def test_staff_egress_routes_return_503_without_store() -> None:
    app = create_app()
    with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as bare:
        r = bare.get("/api/staff/egress/channels/gov/config")

    assert r.status_code == 503
    assert "Durable storage is not ready" in r.json()["detail"]


def test_headend_profiles_listing_is_static_and_citable(client: TestClient) -> None:
    # Cable automation CA-6: the registry is generic product surface.
    r = client.get("/api/staff/egress/headend-profiles")

    assert r.status_code == 200
    profiles = {entry["profile_id"]: entry for entry in r.json()}
    assert "comcast-mtd-sd" in profiles
    assert "telvue-hypercaster-ip" in profiles
    for entry in profiles.values():
        assert entry["source_urls"], entry["profile_id"]
        assert entry["not_claimed"], entry["profile_id"]


def test_apply_headend_profile_creates_a_fresh_config(client: TestClient) -> None:
    r = client.post(
        "/api/staff/egress/channels/gov/config/headend-profile",
        json={
            "profile_id": "comcast-mtd-sd",
            "destination_uri": "udp://239.255.0.1:5000",
        },
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["canonical_profile"]["video_codec"] == "mpeg2video"
    sink = body["sinks"][0]
    assert sink["kind"] == "udp-ts"
    muxrate_idx = sink["extra_output_args"].index("-muxrate")
    assert sink["extra_output_args"][muxrate_idx + 1] == "3750k"

    persisted = client.get("/api/staff/egress/channels/gov/config").json()
    assert persisted["sinks"][0]["kind"] == "udp-ts"


def test_apply_headend_profile_keeps_existing_sinks_when_asked(client: TestClient) -> None:
    assert (
        client.put("/api/staff/egress/channels/gov/config", json=_config_payload()).status_code
        == 200
    )

    r = client.post(
        "/api/staff/egress/channels/gov/config/headend-profile",
        json={
            "profile_id": "generic-udp-spts",
            "destination_uri": "udp://10.0.0.9:5000",
            "muxrate_kbps": 9000,
            "keep_existing_sinks": True,
        },
    )

    assert r.status_code == 200, r.text
    body = r.json()
    kinds = sorted(sink["kind"] for sink in body["sinks"])
    assert kinds == ["srt", "udp-ts"]
    headend = next(sink for sink in body["sinks"] if sink["kind"] == "udp-ts")
    muxrate_idx = headend["extra_output_args"].index("-muxrate")
    assert headend["extra_output_args"][muxrate_idx + 1] == "9000k"


def test_apply_headend_profile_404_unknown_and_422_destination_mismatch(
    client: TestClient,
) -> None:
    r = client.post(
        "/api/staff/egress/channels/gov/config/headend-profile",
        json={"profile_id": "nope", "destination_uri": "udp://239.0.0.1:5000"},
    )
    assert r.status_code == 404

    r = client.post(
        "/api/staff/egress/channels/gov/config/headend-profile",
        json={"profile_id": "comcast-mtd-sd", "destination_uri": "udp://10.0.0.5:5000"},
    )
    assert r.status_code == 422
    assert "multicast" in r.json()["detail"]


def test_apply_headend_profile_503_without_store() -> None:
    app = create_app()
    with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as bare:
        r = bare.post(
            "/api/staff/egress/channels/gov/config/headend-profile",
            json={
                "profile_id": "generic-udp-spts",
                "destination_uri": "udp://10.0.0.9:5000",
            },
        )

    assert r.status_code == 503


def _udp_ts_config_payload(channel_id: str = "gov") -> dict[str, object]:
    return {
        "channel_id": channel_id,
        "enabled": True,
        "slate_message": "CivicCast is preparing the channel.",
        "sinks": [
            {
                "kind": "udp-ts",
                "label": "Cable headend",
                "uri": "udp://239.255.0.1:5000",
                "extra_output_args": ["-muxrate", "8000k"],
            }
        ],
    }


def test_compliance_probe_endpoint_runs_via_seam(client: TestClient) -> None:
    # Cable automation CA-7: the prober seam is overridable so the API
    # contract is testable without TSDuck or a live stream.
    from datetime import UTC, datetime

    from civiccast.egress.compliance import ComplianceCheck, ComplianceProbeResult
    from civiccast.egress.router import get_compliance_prober

    calls: list[tuple[str, int]] = []

    def fake_prober(config, seconds):  # type: ignore[no-untyped-def]
        calls.append((config.channel_id, seconds))
        return ComplianceProbeResult(
            channel_id=config.channel_id,
            destination="udp://239.255.0.1:5000",
            probed_at=datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
            seconds=seconds,
            expected_muxrate_kbps=8000,
            checks=[ComplianceCheck(check="ts-sync", status="pass", detail="ok")],
            verdict="pass",
        )

    client.app.dependency_overrides[get_compliance_prober] = lambda: fake_prober  # type: ignore[attr-defined]
    assert (
        client.put(
            "/api/staff/egress/channels/gov/config", json=_udp_ts_config_payload()
        ).status_code
        == 200
    )

    r = client.post("/api/staff/egress/channels/gov/compliance-probe", json={"seconds": 15})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verdict"] == "pass"
    assert calls == [("gov", 15)]


def test_compliance_probe_endpoint_rejects_channels_without_udp_ts(
    client: TestClient,
) -> None:
    assert (
        client.put("/api/staff/egress/channels/gov/config", json=_config_payload()).status_code
        == 200
    )

    r = client.post("/api/staff/egress/channels/gov/compliance-probe", json={})

    assert r.status_code == 422
    assert "udp-ts" in r.json()["detail"]


def test_compliance_probe_endpoint_404_without_config(client: TestClient) -> None:
    r = client.post("/api/staff/egress/channels/nope/compliance-probe", json={})
    assert r.status_code == 404


def test_headend_readiness_reports_tsduck_and_last_probes(client: TestClient, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from civiccast.egress.compliance import ComplianceProbeResult
    from civiccast.egress.router import get_egress_work_dir

    client.app.dependency_overrides[get_egress_work_dir] = lambda: tmp_path  # type: ignore[attr-defined]
    assert (
        client.put(
            "/api/staff/egress/channels/gov/config", json=_udp_ts_config_payload()
        ).status_code
        == 200
    )
    (tmp_path / "gov").mkdir()
    (tmp_path / "gov" / "compliance-last.json").write_text(
        ComplianceProbeResult(
            channel_id="gov", destination="udp://239.255.0.1:5000", verdict="pass"
        ).model_dump_json(),
        encoding="utf-8",
    )

    r = client.get("/api/staff/egress/headend-readiness")

    assert r.status_code == 200, r.text
    body = r.json()
    assert "installed" in body["tsduck"]
    channels = {entry["channel_id"]: entry for entry in body["channels"]}
    assert channels["gov"]["destination"] == "udp://239.255.0.1:5000"
    assert channels["gov"]["last_probe"]["verdict"] == "pass"


def test_headend_device_probe_endpoint(client: TestClient) -> None:
    from datetime import UTC, datetime

    from civiccast.egress.compliance import DevicePortProbe, DeviceProbeResult
    from civiccast.egress.router import get_device_prober

    def fake_device_prober(host, ports):  # type: ignore[no-untyped-def]
        return DeviceProbeResult(
            host=host,
            ports=[DevicePortProbe(port=p, reachable=p == 443) for p in ports],
            any_reachable=True,
            probed_at=datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
        )

    client.app.dependency_overrides[get_device_prober] = lambda: fake_device_prober  # type: ignore[attr-defined]

    r = client.post(
        "/api/staff/egress/headend-device-probe",
        json={"host": "headend.example", "ports": [80, 443]},
    )

    assert r.status_code == 200, r.text
    assert r.json()["any_reachable"] is True


def test_ndi_readiness_reports_byo_state_and_relay_statuses(
    client: TestClient, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    # Issue #116: honest BYO posture - no NDI-capable ffmpeg configured on
    # this host, plus whatever relays the automation pass is supervising.
    from civiccast.egress.ndi_relay import (
        NdiRelayStatus,
        clear_relay_statuses,
        set_relay_status,
    )

    monkeypatch.delenv("CIVICCAST_NDI_FFMPEG", raising=False)
    clear_relay_statuses()
    set_relay_status(
        NdiRelayStatus(
            channel_id="public",
            ndi_name="CivicCast Public",
            state="blocked",
            next_step="Set CIVICCAST_NDI_FFMPEG ...",
        )
    )

    r = client.get("/api/staff/egress/ndi-readiness")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["byo_ffmpeg_configured"] is False
    assert "CIVICCAST_NDI_FFMPEG" in body["next_step"]
    relays = {entry["channel_id"]: entry for entry in body["relays"]}
    assert relays["public"]["state"] == "blocked"
    clear_relay_statuses()


def test_sdi_readiness_reports_byo_state_and_relay_statuses(
    client: TestClient, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    # Issue #117: honest BYO posture - no DeckLink-capable ffmpeg configured
    # on this host, plus whatever relays the automation pass is supervising.
    from civiccast.egress.sdi_relay import (
        SdiRelayStatus,
        clear_relay_statuses,
        set_relay_status,
    )

    monkeypatch.delenv("CIVICCAST_SDI_FFMPEG", raising=False)
    clear_relay_statuses()
    set_relay_status(
        SdiRelayStatus(
            channel_id="public",
            device="DeckLink Mini Monitor 4K",
            state="blocked",
            next_step="Set CIVICCAST_SDI_FFMPEG ...",
        )
    )

    r = client.get("/api/staff/egress/sdi-readiness")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["byo_ffmpeg_configured"] is False
    assert "CIVICCAST_SDI_FFMPEG" in body["next_step"]
    relays = {entry["channel_id"]: entry for entry in body["relays"]}
    assert relays["public"]["state"] == "blocked"
    assert relays["public"]["device"] == "DeckLink Mini Monitor 4K"
    clear_relay_statuses()


# --- S11b per-sink loudness plan --------------------------------------------


def _loudness_role_app(scopes: tuple[str, ...] | None, store: PostgresEgressStore) -> Any:
    """Bare app mounting the egress staff router with a chosen operator identity
    so the real require_any_role gate runs (mirrors control_room's role tests)."""
    from fastapi import FastAPI, Request, Response

    from civiccast.auth.models import OperatorIdentity
    from civiccast.egress.router import staff_router

    app = FastAPI()

    @app.middleware("http")
    async def _ident(request: Request, call_next: Any) -> Response:
        if scopes is not None:
            request.state.operator_identity = OperatorIdentity(
                operator_id="dana", operator_display_name="Dana", scopes=scopes
            )
        return await call_next(request)

    app.include_router(staff_router)
    app.dependency_overrides[get_egress_store] = lambda: store
    return app


def _loudness_payload(channel_id: str = "gov") -> dict[str, object]:
    return {
        "channel_id": channel_id,
        "enabled": True,
        "slate_message": "CivicCast is preparing the channel.",
        "loudness_target_lufs": -16.0,
        "sinks": [
            {
                "kind": "udp-ts",
                "label": "Cable",
                "uri": "udp://239.255.0.1:5000",
                "loudness_regime": "atsc-a85",
            },
            {
                "kind": "srt",
                "label": "CDN",
                "uri": "srt://cdn.example:9000",
                "loudness_regime": "streaming",
            },
        ],
    }


def test_staff_egress_config_write_accepts_per_sink_loudness(client: TestClient) -> None:
    # S11b: the existing config write accepts the per-sink loudness fields and
    # round-trips them through GET config.
    assert (
        client.put("/api/staff/egress/channels/gov/config", json=_loudness_payload()).status_code
        == 200
    )
    body = client.get("/api/staff/egress/channels/gov/config").json()
    by_label = {s["label"]: s for s in body["sinks"]}
    assert by_label["Cable"]["loudness_regime"] == "atsc-a85"
    assert by_label["Cable"]["eas_tone_strip_enabled"] is True
    assert by_label["CDN"]["loudness_regime"] == "streaming"


def test_loudness_plan_resolves_per_sink_targets(client: TestClient) -> None:
    assert (
        client.put("/api/staff/egress/channels/gov/config", json=_loudness_payload()).status_code
        == 200
    )
    r = client.get("/api/staff/egress/channels/gov/loudness-plan")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["baseline_target_lufs"] == -16.0
    by_label = {s["label"]: s for s in body["sinks"]}
    assert by_label["Cable"]["effective_target_lufs"] == -24.0
    assert by_label["Cable"]["standard_label"] == "ATSC A/85 -24 LKFS (CALM Act)"
    assert by_label["Cable"]["requires_reencode"] is True
    assert by_label["CDN"]["effective_target_lufs"] == -16.0
    assert by_label["CDN"]["requires_reencode"] is False


def test_loudness_plan_unknown_channel_is_404(client: TestClient) -> None:
    assert client.get("/api/staff/egress/channels/ghost/loudness-plan").status_code == 404


def test_loudness_plan_forbidden_for_records_clerk(store: PostgresEgressStore) -> None:
    app = _loudness_role_app(("records_clerk",), store)
    with TestClient(app) as c:
        assert c.get("/api/staff/egress/channels/gov/loudness-plan").status_code == 403


def test_loudness_plan_allowed_for_support_admin(
    client: TestClient, store: PostgresEgressStore
) -> None:
    assert (
        client.put("/api/staff/egress/channels/gov/config", json=_loudness_payload()).status_code
        == 200
    )
    app = _loudness_role_app(("support_admin",), store)
    with TestClient(app) as c:
        assert c.get("/api/staff/egress/channels/gov/loudness-plan").status_code == 200


def test_loudness_plan_503_without_store() -> None:
    app = create_app()
    with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as bare:
        r = bare.get("/api/staff/egress/channels/gov/loudness-plan")
    assert r.status_code == 503


# --- S11a caption decode-back status + proofs ---------------------------------


def _seed_caption_proof(
    store: PostgresEgressStore, *, status: str, caption_status: str, sampled_at: datetime
) -> None:
    store.append_caption_proof_sample(
        EgressCaptionProofSample(
            channel_id="gov",
            sampled_at=sampled_at,
            status=status,  # type: ignore[arg-type]
            caption_status=caption_status,  # type: ignore[arg-type]
            mode="cea-708",
            decoder_name="ffmpeg-subcc",
            expected_cue_count=2,
            decoded_cue_count=2 if status == "PASS" else 0,
            matched_cue_count=2 if status == "PASS" else 0,
            proof_boundary="egress-caption-embed-to-emitted-stream-decode-back",
        )
    )


def test_caption_status_not_verified_without_proof(client: TestClient) -> None:
    r = client.get("/api/staff/egress/channels/gov/caption-status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["caption_status"] == "not-verified"
    assert body["latest"] is None


def test_caption_status_on_for_fresh_pass(client: TestClient, store: PostgresEgressStore) -> None:
    _seed_caption_proof(store, status="PASS", caption_status="on", sampled_at=datetime.now(UTC))
    r = client.get("/api/staff/egress/channels/gov/caption-status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["caption_status"] == "on"
    assert body["latest"]["status"] == "PASS"


def test_caption_proofs_returns_recent_samples(
    client: TestClient, store: PostgresEgressStore
) -> None:
    now = datetime.now(UTC)
    _seed_caption_proof(store, status="FAIL", caption_status="not-verified", sampled_at=now)
    _seed_caption_proof(
        store, status="PASS", caption_status="on", sampled_at=now + timedelta(seconds=30)
    )
    r = client.get("/api/staff/egress/channels/gov/caption-proofs?limit=10")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [s["status"] for s in body] == ["PASS", "FAIL"]


def test_caption_status_forbidden_for_records_clerk(store: PostgresEgressStore) -> None:
    app = _loudness_role_app(("records_clerk",), store)
    with TestClient(app) as c:
        assert c.get("/api/staff/egress/channels/gov/caption-status").status_code == 403
        assert c.get("/api/staff/egress/channels/gov/caption-proofs").status_code == 403


def test_caption_status_allowed_for_meeting_operator(store: PostgresEgressStore) -> None:
    app = _loudness_role_app(("meeting_operator",), store)
    with TestClient(app) as c:
        assert c.get("/api/staff/egress/channels/gov/caption-status").status_code == 200


def test_caption_status_503_without_store() -> None:
    app = create_app()
    with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as bare:
        r = bare.get("/api/staff/egress/channels/gov/caption-status")
    assert r.status_code == 503


def test_staff_repair_gstreamer_endpoint_returns_recovery_outcome(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tier-5 operator recovery endpoint delegates to
    ``trigger_gstreamer_repair`` and surfaces its outcome. The endpoint is
    backend-only in this change (the operator-console button is a documented
    TODO); the native repair itself is exercised in
    tests/egress/test_gstreamer_degrade_recovery.py."""
    import civiccast.native.gstreamer_repair as repair

    def _fake_trigger() -> repair.RepairTrigger:
        return repair.RepairTrigger(
            triggered=True,
            healthy=False,
            installer_binary=None,
            argv=("x",),
            pid=777,
            detail="re-stage launched",
            remedy="restage-launched",
        )

    monkeypatch.setattr(repair, "trigger_gstreamer_repair", _fake_trigger)

    r = client.post("/api/staff/egress/repair-gstreamer")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["triggered"] is True
    assert body["closure_healthy"] is False
    assert body["remedy"] == "restage-launched"
    assert body["pid"] == 777
