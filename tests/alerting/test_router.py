# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S8-5 alerting staff API tests (runtime-safe-to-air, system-resources, self-tests)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import civiccast.alerting.models
import civiccast.egress.models
import civiccast.schedule.models  # noqa: F401
from civiccast.alerting.models import (
    AlertChannel,
    AlertEventDelivery,
    AlertRule,
    SystemResourceSample,
    SystemSelfTest,
)
from civiccast.alerting.router import (
    RuntimeStatusCache,
    get_alerting_session_factory,
    get_credential_writer,
    get_runtime_status_cache,
    get_self_test_deps,
)
from civiccast.alerting.self_test import SelfTestDeps
from civiccast.alerting.store import (
    append_resource_sample,
    record_alert_condition,
    upsert_alert_channel,
    upsert_alert_rule,
    upsert_event_delivery,
    upsert_self_test,
)
from civiccast.app import create_app
from civiccast.db import Base, bind_engine, reset_engine
from civiccast.egress.models import EgressConfig, EgressSinkSpec, EgressStateRow
from civiccast.egress.router import get_egress_store
from civiccast.egress.store import PostgresEgressStore

_NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)


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


@contextmanager
def _factory_for(engine: Engine) -> Iterator[Session]:
    with Session(bind=engine) as session:
        yield session


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    def factory() -> Iterator[Session]:
        return _factory_for(engine)

    store = PostgresEgressStore(factory)
    app = create_app()
    app.dependency_overrides[get_egress_store] = lambda: store
    app.dependency_overrides[get_alerting_session_factory] = lambda: factory
    # Fresh cache per test so the ~4s TTL never leaks across cases.
    app.dependency_overrides[get_runtime_status_cache] = lambda: RuntimeStatusCache(ttl_seconds=0.0)
    with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c:
        yield c


def _seed_channel(engine: Engine, channel_id: str = "public") -> None:
    store = PostgresEgressStore(lambda: _factory_for(engine))
    store.upsert_config(
        EgressConfig(
            channel_id=channel_id,
            enabled=True,
            auto_start=True,
            slate_message="CivicCast is preparing the channel.",
            sinks=[EgressSinkSpec(kind="udp-ts", label="Headend", uri="udp://239.0.0.1:5000")],
        )
    )
    store.write_state(EgressStateRow(channel_id=channel_id, state="ON_AIR", updated_at=_NOW))


def test_runtime_safe_to_air_returns_status(client: TestClient, engine: Engine) -> None:
    _seed_channel(engine)
    r = client.get("/api/staff/runtime-safe-to-air")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["color"] in ("green", "yellow", "red")
    assert any(c["channel_id"] == "public" for c in body["channels"])


def test_runtime_safe_to_air_no_channels_is_idle(client: TestClient) -> None:
    r = client.get("/api/staff/runtime-safe-to-air")
    assert r.status_code == 200, r.text
    assert r.json()["channels"] == []


def test_system_resources_lists_recent_samples(client: TestClient, engine: Engine) -> None:
    # The window cutoff is wall-clock-now relative, so seed "now" — a fixed
    # historical timestamp would age out of the window and the listing would be
    # empty. Seeding now also lets us actually assert the sample is returned.
    with _factory_for(engine) as session:
        append_resource_sample(
            session,
            SystemResourceSample(sampled_at=datetime.now(UTC), cpu_percent=42.0, ram_total_gb=16.0),
        )
        session.commit()
    r = client.get("/api/staff/system-resources", params={"window_minutes": 1440})
    assert r.status_code == 200, r.text
    assert len(r.json()) >= 1  # the just-recorded sample is listed


def test_self_tests_lists_history(client: TestClient, engine: Engine) -> None:
    with _factory_for(engine) as session:
        upsert_self_test(
            session,
            SystemSelfTest(
                self_test_id="st-1",
                kind="daily",
                started_at=_NOW,
                finished_at=_NOW,
                status="pass",
                checks={"readiness": True},
                summary="daily self-test passed",
            ),
        )
        session.commit()
    r = client.get("/api/staff/self-tests", params={"kind": "daily"})
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1
    assert r.json()[0]["self_test_id"] == "st-1"


# ---------------------------------------------------------------------------
# Alert rule + channel CRUD + events
# ---------------------------------------------------------------------------


def _seed_rule(engine: Engine, rule_id: str = "default:off-air") -> None:
    with _factory_for(engine) as session:
        upsert_alert_rule(
            session,
            AlertRule(
                rule_id=rule_id,
                condition="off-air",
                severity="critical",
                channel_ids=[],
                updated_at=_NOW,
                updated_by="seed",
            ),
        )
        session.commit()


def test_alert_rules_list_and_update(client: TestClient, engine: Engine) -> None:
    _seed_rule(engine)
    r = client.get("/api/staff/alert-rules")
    assert r.status_code == 200, r.text
    assert any(rule["rule_id"] == "default:off-air" for rule in r.json())

    r = client.put(
        "/api/staff/alert-rules/default:off-air",
        json={"enabled": False, "channel_ids": ["ch-1"], "re_alert_after_seconds": 600},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is False
    assert body["channel_ids"] == ["ch-1"]
    assert body["re_alert_after_seconds"] == 600
    assert body["condition"] == "off-air"  # immutable
    assert body["updated_by"] != "seed"  # stamped with the operator


def test_update_missing_rule_is_404(client: TestClient) -> None:
    assert client.put("/api/staff/alert-rules/nope", json={"enabled": False}).status_code == 404


def test_alert_channel_crud_round_trip(client: TestClient) -> None:
    payload = {
        "kind": "email",
        "label": "Ops email",
        "target_redacted": "ops@***",
        "credential_handle": "alert-smtp",
        "quiet_hours_start_utc": "22:00",
        "quiet_hours_end_utc": "07:00",
    }
    r = client.post("/api/staff/alert-channels", json=payload)
    assert r.status_code == 201, r.text
    created = r.json()
    cid = created["channel_id"]
    assert cid.startswith("ch-")
    assert "secret" not in created  # no secret ever returned

    assert any(c["channel_id"] == cid for c in client.get("/api/staff/alert-channels").json())

    r = client.put(f"/api/staff/alert-channels/{cid}", json={**payload, "label": "Renamed"})
    assert r.status_code == 200, r.text
    assert r.json()["label"] == "Renamed"

    assert client.delete(f"/api/staff/alert-channels/{cid}").status_code == 204
    assert not any(c["channel_id"] == cid for c in client.get("/api/staff/alert-channels").json())


def test_create_channel_rejects_bad_quiet_hours(client: TestClient) -> None:
    r = client.post(
        "/api/staff/alert-channels",
        json={
            "kind": "email",
            "label": "x",
            "target_redacted": "y",
            "quiet_hours_start_utc": "25:99",
        },
    )
    assert r.status_code == 422, r.text


def test_create_channel_with_secret_writes_to_store_and_never_returns_it(
    client: TestClient,
) -> None:
    written: dict[str, dict] = {}
    client.app.dependency_overrides[get_credential_writer] = lambda: (  # type: ignore[attr-defined]
        lambda handle, secret: written.__setitem__(handle, dict(secret))
    )
    r = client.post(
        "/api/staff/alert-channels",
        json={
            "kind": "webhook",
            "label": "Pager",
            "target_redacted": "https://hooks.***",
            "secret": {"url": "https://hooks.example/x", "secret": "s3cr3t"},
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    cid = body["channel_id"]
    # No secret echoed back; the channel references its own id as the handle.
    assert "secret" not in body
    assert body["credential_handle"] == cid
    assert written[cid] == {"url": "https://hooks.example/x", "secret": "s3cr3t"}


def test_create_channel_with_secret_503_when_store_unwired(client: TestClient) -> None:
    # No get_credential_writer override -> seam returns None -> a supplied secret 503s.
    r = client.post(
        "/api/staff/alert-channels",
        json={
            "kind": "email",
            "label": "x",
            "target_redacted": "y",
            "secret": {"smtp_password": "pw"},
        },
    )
    assert r.status_code == 503, r.text


def test_create_channel_without_secret_needs_no_writer(client: TestClient) -> None:
    r = client.post(
        "/api/staff/alert-channels",
        json={"kind": "email", "label": "x", "target_redacted": "y", "credential_handle": "preset"},
    )
    assert r.status_code == 201, r.text  # no secret -> writer not required


def test_delete_missing_channel_is_404(client: TestClient) -> None:
    assert client.delete("/api/staff/alert-channels/nope").status_code == 404


def test_alert_events_list_and_ack(client: TestClient, engine: Engine) -> None:
    with _factory_for(engine) as session:
        event = record_alert_condition(
            session,
            kind="off-air",
            resource_ref="public",
            source_section="S8",
            summary="public is off air",
        )
        session.commit()
        event_id = event.event_id

    r = client.get("/api/staff/alert-events", params={"state": "firing"})
    assert r.status_code == 200, r.text
    assert any(e["event_id"] == event_id for e in r.json())

    r = client.post(f"/api/staff/alert-events/{event_id}/ack")
    assert r.status_code == 200, r.text
    assert r.json()["acknowledged_by"]
    assert r.json()["acknowledged_at"] is not None


def test_ack_missing_event_is_404(client: TestClient) -> None:
    assert client.post("/api/staff/alert-events/nope/ack").status_code == 404


def test_system_health_includes_alerting_overlay(client: TestClient, engine: Engine) -> None:
    _seed_channel(engine)
    with _factory_for(engine) as session:
        record_alert_condition(
            session, kind="off-air", resource_ref="public", source_section="S8", summary="off air"
        )
        upsert_self_test(
            session,
            SystemSelfTest(
                self_test_id="st-health",
                kind="daily",
                started_at=_NOW,
                finished_at=_NOW,
                status="pass",
                checks={"readiness": True},
                summary="daily passed",
            ),
        )
        session.commit()
    r = client.get("/api/staff/installer/system-health")
    assert r.status_code == 200, r.text
    body = r.json()
    # The S8-5 overlay is populated from the alerting + egress stores.
    assert body["runtime_safe_to_air"] is not None
    assert any(c["channel_id"] == "public" for c in body["runtime_safe_to_air"]["channels"])
    assert body["last_self_test"]["self_test_id"] == "st-health"
    assert body["active_warning_alerts"] + body["active_critical_alerts"] >= 1


def test_support_bundle_includes_redacted_operations_history(
    client: TestClient, engine: Engine, tmp_path, monkeypatch
) -> None:
    # Keep all bundle/state writes inside tmp so the test never touches the box.
    monkeypatch.setenv("CIVICCAST_SUPPORT_BUNDLE_DIR", str(tmp_path / "bundles"))
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    _seed_channel(engine)
    with _factory_for(engine) as session:
        event = record_alert_condition(
            session,
            kind="off-air",
            resource_ref="public",
            source_section="S8",
            summary="public is off air",
        )
        upsert_event_delivery(
            session,
            AlertEventDelivery(
                delivery_id="d-1",
                event_id=event.event_id,
                alert_channel_id="ch-x",
                kind="webhook",
                status="failed",
                attempts=1,
                last_error="connection refused",
                signature="hmac-should-not-leak",
                dispatched_at=_NOW,
            ),
        )
        upsert_self_test(
            session,
            SystemSelfTest(
                self_test_id="st-b",
                kind="daily",
                started_at=_NOW,
                finished_at=_NOW,
                status="pass",
                checks={"readiness": True},
                summary="daily passed",
            ),
        )
        # The bundle's resource-sample window is wall-clock-now relative (24h),
        # so seed "now" — a fixed historical _NOW ages out of the window and the
        # `len(resource_samples) >= 1` assertion below then sees 0 (time flake).
        append_resource_sample(
            session,
            SystemResourceSample(sampled_at=datetime.now(UTC), cpu_percent=12.0, ram_total_gb=16.0),
        )
        upsert_alert_channel(
            session,
            AlertChannel(
                channel_id="ch-x",
                kind="webhook",
                label="Pager",
                enabled=True,
                target_redacted="https://hooks.***",
                credential_handle="secret-handle-xyz",
                created_at=_NOW,
            ),
        )
        session.commit()

    r = client.post("/api/staff/installer/support-bundle", json={"operator_note": None})
    assert r.status_code == 200, r.text
    body = r.json()
    assert any("egress activity" in entry for entry in body["contains"])

    raw = Path(body["path"]).read_text(encoding="utf-8")
    parsed = json.loads(raw)
    ops = parsed["operations"]
    assert any(e["event_id"] == event.event_id for e in ops["alert_events"])
    assert ops["self_test_history"][0]["self_test_id"] == "st-b"
    assert len(ops["resource_samples"]) >= 1
    assert "public" in ops["egress_activity"]
    deliveries = ops["alert_event_deliveries"]
    assert deliveries and all("signature" not in d for d in deliveries)
    assert all("credential_handle" not in ch for ch in ops["alert_channels"])
    # Cryptographic material and credential handles never reach the bundle file.
    assert "hmac-should-not-leak" not in raw
    assert "secret-handle-xyz" not in raw


def _all_pass_deps() -> SelfTestDeps:
    return SelfTestDeps(
        **{
            name: (lambda: True)
            for name in (
                "readiness",
                "filesink_continuity",
                "backup_probe",
                "model_ping",
                "restore_rehearsal",
                "srt_continuity",
                "tsduck_probe",
                "channel_test_send",
            )
        }
    )


def test_self_test_run_503_when_probes_unwired(client: TestClient) -> None:
    # No get_self_test_deps override -> the seam returns None -> 503.
    assert client.post("/api/staff/self-tests/run", params={"kind": "daily"}).status_code == 503


def test_self_test_run_executes_with_wired_deps(client: TestClient, engine: Engine) -> None:
    client.app.dependency_overrides[get_self_test_deps] = _all_pass_deps  # type: ignore[attr-defined]
    r = client.post("/api/staff/self-tests/run", params={"kind": "daily"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pass"
    assert r.json()["kind"] == "daily"
    # Persisted to history.
    assert client.get("/api/staff/self-tests", params={"kind": "daily"}).json()


def test_self_test_run_omits_unavailable_probe_rather_than_failing_it(
    client: TestClient, monkeypatch
) -> None:
    # T1: the on-demand endpoint must OMIT a probe whose tooling is unavailable
    # (honest not-run), never run-and-fail it — proven at the HTTP seam, with a
    # deterministic availability map (the real probes are host-dependent).
    deps = _all_pass_deps()
    deps.tsduck_probe = lambda: False  # would FAIL if it were ever run
    client.app.dependency_overrides[get_self_test_deps] = lambda: deps  # type: ignore[attr-defined]
    monkeypatch.setattr(
        "civiccast.alerting.router.default_self_test_availability",
        lambda **_k: {
            "readiness": True,
            "backup_probe": True,
            "model_ping": True,
            "filesink_continuity": False,
            "restore_rehearsal": False,
            "srt_continuity": False,
            "tsduck_probe": False,
            "channel_test_send": False,
        },
    )
    r = client.post("/api/staff/self-tests/run", params={"kind": "weekly"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "weekly"
    assert "tsduck_probe" not in body["checks"]  # omitted, not run-and-failed
    assert body["status"] == "pass"  # the failing-but-unavailable probe did not fail the run


def test_alerting_mutations_reject_non_admin(monkeypatch) -> None:
    # T2: channel CRUD + rule update require setup_admin; a meeting_operator must 403
    # (a widened gate would silently let any operator add/remove alert destinations).
    monkeypatch.setenv("CIVICCAST_STAFF_TOKENS", "limited:limited:Limited Op:meeting_operator")
    c = TestClient(create_app(), headers={"Authorization": "Bearer limited"})
    assert (
        c.put("/api/staff/alert-rules/default:off-air", json={"enabled": False}).status_code == 403
    )
    assert (
        c.post(
            "/api/staff/alert-channels",
            json={"kind": "email", "label": "x", "target_redacted": "y"},
        ).status_code
        == 403
    )
    assert c.delete("/api/staff/alert-channels/ch-x").status_code == 403
    # meeting_operator IS allowed to read events (gate passes -> not 403; 503 if storage unwired).
    assert c.get("/api/staff/alert-events").status_code != 403
