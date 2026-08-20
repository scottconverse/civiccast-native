# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S11c EAS display service — decisions, overlay mapping, auto-surface, active overlay."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.eas.models import EasCapAlert
from civiccast.eas.service import (
    EasDisplayError,
    EasDisplayService,
    alert_to_emergency_overlay,
    overlay_severity_for,
    recommended_mode,
)
from civiccast.eas.store import AlertNotFoundError, EasStore

_T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[EasStore]:
    eng = create_engine(f"sqlite:///{tmp_path / 'eas.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    try:
        yield EasStore(factory)
    finally:
        eng.dispose()


def _alert(
    alert_id: str, *, severity: str = "extreme", status: str = "active", **kw: object
) -> EasCapAlert:
    base: dict[str, object] = {
        "alert_id": alert_id,
        "source_id": "src",
        "sender": "snd",
        "identifier": alert_id,
        "sent": _T0,
        "msg_type": "alert",
        "event": "Tornado Warning",
        "severity": severity,
        "status": status,
        "headline": "Tornado Warning issued",
        "instruction": "Take shelter now.",
        "expires": _T0 + timedelta(hours=1),
    }
    base.update(kw)
    return EasCapAlert(**base)  # type: ignore[arg-type]


def _svc(store: EasStore) -> EasDisplayService:
    return EasDisplayService(store, clock=lambda: _T0)


# --- pure mapping --------------------------------------------------------------


def test_overlay_severity_mapping() -> None:
    assert overlay_severity_for("extreme") == "emergency"
    assert overlay_severity_for("severe") == "warning"
    assert overlay_severity_for("moderate") == "watch"
    assert overlay_severity_for("unknown") == "watch"


def test_recommended_mode_never_forced_slate() -> None:
    assert recommended_mode(_alert("a", severity="extreme")) == "overlay"
    assert recommended_mode(_alert("a", severity="severe")) == "crawl"


def test_alert_to_emergency_overlay_maps_fields() -> None:
    overlay = alert_to_emergency_overlay(_alert("a", severity="extreme"), overlay_id="ov1")
    assert overlay.overlay_id == "ov1"
    assert overlay.severity == "emergency"
    assert overlay.instructions == "Take shelter now."
    assert overlay.aria_live == "assertive"


# --- surface / forced-slate guard ----------------------------------------------


def test_surface_creates_displayed_decision(store: EasStore) -> None:
    store.ingest_alert(_alert("a1"))
    decision = _svc(store).surface_alert(
        channel_id="gov", alert_id="a1", mode="crawl", decided_by="op_dana"
    )
    assert decision.state == "displayed"
    assert decision.eas_claim == "not_eas"
    assert decision.overlay_id == "eas-gov-a1"


def test_surface_unknown_alert_raises(store: EasStore) -> None:
    with pytest.raises(AlertNotFoundError):
        _svc(store).surface_alert(
            channel_id="gov", alert_id="missing", mode="crawl", decided_by="op"
        )


def test_forced_slate_requires_operator_confirmation(store: EasStore) -> None:
    store.ingest_alert(_alert("a1"))
    svc = _svc(store)
    with pytest.raises(EasDisplayError, match="confirmed by an operator"):
        svc.surface_alert(
            channel_id="gov", alert_id="a1", mode="forced_slate", decided_by="op_dana"
        )
    with pytest.raises(EasDisplayError):  # auto can never force a slate
        svc.surface_alert(
            channel_id="gov",
            alert_id="a1",
            mode="forced_slate",
            decided_by="auto",
            operator_confirmed=True,
        )
    # confirmed by a real operator → allowed
    decision = svc.surface_alert(
        channel_id="gov",
        alert_id="a1",
        mode="forced_slate",
        decided_by="op_dana",
        operator_confirmed=True,
    )
    assert decision.mode == "forced_slate"


# --- auto-surface --------------------------------------------------------------


def test_auto_surface_only_severe_plus_and_idempotent(store: EasStore) -> None:
    store.ingest_alert(_alert("ext", severity="extreme"))
    store.ingest_alert(_alert("sev", severity="severe"))
    store.ingest_alert(_alert("mod", severity="moderate"))
    svc = _svc(store)
    first = svc.auto_surface_active(channel_id="gov")
    assert {d.alert_id for d in first} == {"ext", "sev"}  # moderate skipped
    assert all(d.auto_surfaced for d in first)
    assert next(d for d in first if d.alert_id == "ext").mode == "overlay"
    # idempotent — already-shown alerts are not surfaced again
    assert svc.auto_surface_active(channel_id="gov") == []


# --- active overlay (drives the public endpoint) -------------------------------


def test_active_overlay_picks_highest_severity_active(store: EasStore) -> None:
    store.ingest_alert(_alert("sev", severity="severe"))
    store.ingest_alert(_alert("ext", severity="extreme"))
    svc = _svc(store)
    svc.surface_alert(channel_id="gov", alert_id="sev", mode="crawl", decided_by="op")
    svc.surface_alert(channel_id="gov", alert_id="ext", mode="overlay", decided_by="op")
    overlay = svc.active_emergency_overlay("gov")
    assert overlay is not None
    assert overlay.severity == "emergency"  # the extreme alert wins


def test_active_overlay_none_when_nothing_displayed(store: EasStore) -> None:
    assert _svc(store).active_emergency_overlay("gov") is None


def test_active_overlay_skips_expired_alert(store: EasStore) -> None:
    store.ingest_alert(_alert("a1", severity="extreme"))
    svc = _svc(store)
    svc.surface_alert(channel_id="gov", alert_id="a1", mode="overlay", decided_by="op")
    assert svc.active_emergency_overlay("gov") is not None
    # the alert expires out from under the (still 'displayed') decision
    store.expire_alerts(now=_T0 + timedelta(hours=2))
    assert svc.active_emergency_overlay("gov") is None


def test_expired_alert_does_not_return_to_air_on_repoll(store: EasStore) -> None:
    # Blocker regression (end to end): a steady-state re-poll of an alert that has been
    # taken off air (expired/cancelled) must NOT put it back on air.
    store.ingest_alert(_alert("a1", severity="extreme"))
    svc = _svc(store)
    svc.surface_alert(channel_id="gov", alert_id="a1", mode="overlay", decided_by="op")
    store.expire_alerts(now=_T0 + timedelta(hours=2))
    assert svc.active_emergency_overlay("gov") is None
    store.ingest_alert(_alert("a1", severity="extreme"))  # equal-sent re-poll
    assert svc.active_emergency_overlay("gov") is None  # stays off air


def test_clear_decision(store: EasStore) -> None:
    store.ingest_alert(_alert("a1"))
    svc = _svc(store)
    decision = svc.surface_alert(channel_id="gov", alert_id="a1", mode="crawl", decided_by="op")
    cleared = svc.clear_decision(decision.decision_id)
    assert cleared.state == "cleared"
    assert cleared.cleared_at is not None
    assert svc.active_emergency_overlay("gov") is None
