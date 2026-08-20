# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S11c EAS poll worker — fetch→parse→filter→ingest→expire, fail-closed."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.eas.cap import stable_alert_id
from civiccast.eas.models import EasCapSource
from civiccast.eas.store import EasStore
from civiccast.eas.workers import EasPollWorker

_T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

_CAP_XML_TEMPLATE = """<?xml version="1.0"?>
<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
  <identifier>{identifier}</identifier>
  <sender>snd@example.gov</sender>
  <sent>{sent}</sent>
  <msgType>{msg_type}</msgType>
  {references}
  <info>
    <event>{event}</event>
    <severity>{severity}</severity>
    <expires>{expires}</expires>
    <area><geocode><valueName>UGC</valueName><value>MNZ001</value></geocode></area>
  </info>
</alert>"""


def _cap_xml(
    identifier: str = "A1",
    *,
    msg_type: str = "Alert",
    severity: str = "Extreme",
    event: str = "Tornado Warning",
    sent: datetime = _T0,
    expires: datetime | None = None,
    references: str = "",
) -> str:
    ref = f"<references>{references}</references>" if references else ""
    return _CAP_XML_TEMPLATE.format(
        identifier=identifier,
        sent=sent.isoformat(),
        msg_type=msg_type,
        event=event,
        severity=severity,
        expires=(expires or (sent + timedelta(hours=1))).isoformat(),
        references=ref,
    )


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


def _source(source_id: str = "src_ipaws", *, kind: str = "ipaws-cap", **kw: object) -> EasCapSource:
    base: dict[str, object] = {
        "source_id": source_id,
        "label": "IPAWS",
        "kind": kind,
        "endpoint_url": "https://ipaws.example/feed",
        "severity_floor": "severe",
    }
    base.update(kw)
    return EasCapSource(**base)  # type: ignore[arg-type]


def test_poll_ingests_filtered_alert_and_reports_healthy(store: EasStore) -> None:
    store.upsert_source(_source())
    health: list[tuple[str, bool, str]] = []
    worker = EasPollWorker(
        store=store,
        fetcher=lambda _s: _cap_xml("A1", severity="Extreme"),
        health_hook=lambda s, ok, detail: health.append((s.source_id, ok, detail)),
        clock=lambda: _T0,
    )
    result = worker.run_once()
    assert result.alerts_ingested == 1
    assert result.sources_unhealthy == 0
    assert health[0][1] is True
    assert len(store.list_alerts(active_only=True)) == 1


def test_poll_drops_below_floor_alert(store: EasStore) -> None:
    store.upsert_source(_source(severity_floor="severe"))
    worker = EasPollWorker(
        store=store, fetcher=lambda _s: _cap_xml("A1", severity="Minor"), clock=lambda: _T0
    )
    result = worker.run_once()
    assert result.alerts_ingested == 0
    assert store.list_alerts() == []


def test_poll_fetch_failure_is_fail_closed(store: EasStore) -> None:
    store.upsert_source(_source())
    health: list[tuple[str, bool, str]] = []
    worker = EasPollWorker(
        store=store,
        fetcher=lambda _s: None,  # fetch failed
        health_hook=lambda s, ok, detail: health.append((s.source_id, ok, detail)),
        clock=lambda: _T0,
    )
    result = worker.run_once()
    assert result.sources_unhealthy == 1
    assert result.unhealthy_source_ids == ("src_ipaws",)
    assert health[0][1] is False
    assert store.list_alerts() == []  # nothing fabricated


def test_poll_fetch_exception_is_fail_closed(store: EasStore) -> None:
    store.upsert_source(_source())

    def _boom(_s: EasCapSource) -> str | None:
        raise RuntimeError("connection reset")

    worker = EasPollWorker(store=store, fetcher=_boom, clock=lambda: _T0)
    result = worker.run_once()
    assert result.sources_unhealthy == 1
    assert store.list_alerts() == []


def test_poll_skips_manual_sources(store: EasStore) -> None:
    store.upsert_source(_source("src_manual", kind="manual", endpoint_url=None))
    calls: list[str] = []
    worker = EasPollWorker(
        store=store, fetcher=lambda s: calls.append(s.source_id) or "", clock=lambda: _T0
    )
    result = worker.run_once()
    assert result.sources_polled == 0
    assert calls == []


def test_poll_expires_stale_alerts(store: EasStore) -> None:
    store.upsert_source(_source())
    # ingest an alert that expires before the next scan's clock
    EasPollWorker(
        store=store,
        fetcher=lambda _s: _cap_xml("OLD", severity="Extreme", expires=_T0 + timedelta(minutes=30)),
        clock=lambda: _T0,
    ).run_once()
    assert len(store.list_alerts(active_only=True)) == 1
    # a later scan (fetch returns nothing new) expires it
    result = EasPollWorker(
        store=store, fetcher=lambda _s: "<alert/>", clock=lambda: _T0 + timedelta(hours=1)
    ).run_once()
    assert result.expired == 1
    assert store.list_alerts(active_only=True) == []


def test_poll_runs_post_scan_hook(store: EasStore) -> None:
    # the auto-surface hook runs after each ingest scan
    store.upsert_source(_source())
    called: list[bool] = []
    worker = EasPollWorker(
        store=store,
        fetcher=lambda _s: _cap_xml("A1", severity="Extreme"),
        post_scan=lambda: called.append(True),
        clock=lambda: _T0,
    )
    worker.run_once()
    assert called == [True]


def test_poll_post_scan_error_does_not_kill_loop(store: EasStore) -> None:
    store.upsert_source(_source())

    def _boom() -> None:
        raise RuntimeError("auto-surface failed")

    worker = EasPollWorker(
        store=store,
        fetcher=lambda _s: _cap_xml("A1", severity="Extreme"),
        post_scan=_boom,
        clock=lambda: _T0,
    )
    result = worker.run_once()  # must not raise
    assert result.alerts_ingested == 1


def test_poll_cancel_supersedes_below_floor(store: EasStore) -> None:
    store.upsert_source(_source())
    EasPollWorker(
        store=store, fetcher=lambda _s: _cap_xml("A1", severity="Extreme"), clock=lambda: _T0
    ).run_once()
    assert store.list_alerts(active_only=True)[0].identifier == "A1"
    # a Cancel (no severity → unknown, below floor) must still supersede via references
    refs = "snd@example.gov,A1," + _T0.isoformat()
    EasPollWorker(
        store=store,
        fetcher=lambda _s: _cap_xml(
            "C1",
            msg_type="Cancel",
            severity="Unknown",
            sent=_T0 + timedelta(minutes=5),
            references=refs,
        ),
        clock=lambda: _T0 + timedelta(minutes=5),
    ).run_once()
    assert store.get_alert(stable_alert_id("snd@example.gov", "A1")).status == "cancelled"
