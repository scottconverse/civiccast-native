# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S11c EAS data layer — models + EasStore (dedup/supersede/expire) + migration 0051.

SQLite-backed; the live-Postgres full-chain head check lives in
tests/live/test_real_postgres.py. The 0051 migration's up/down reversibility is
asserted by TestPublicSafetyEasMigration via the real Alembic chain on SQLite.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.eas.models import (
    EasCapAlert,
    EasCapSource,
    EasDisplayDecision,
    severity_at_or_above,
)
from civiccast.eas.store import (
    DecisionNotFoundError,
    EasStore,
    SourceNotFoundError,
    parse_cap_references,
)

_T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


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


def _source(source_id: str = "src_nws", **kw: object) -> EasCapSource:
    base: dict[str, object] = {
        "source_id": source_id,
        "label": "NWS api.weather.gov",
        "kind": "nws-cap",
        "endpoint_url": "https://api.weather.gov/alerts/active",
        "geocode_filter": ["MNZ001"],
        "severity_floor": "severe",
        "poll_seconds": 60,
    }
    base.update(kw)
    return EasCapSource(**base)  # type: ignore[arg-type]


def _alert(identifier: str = "NWS.1", *, sent: datetime = _T0, **kw: object) -> EasCapAlert:
    base: dict[str, object] = {
        "alert_id": f"src_nws:{identifier}",
        "source_id": "src_nws",
        "sender": "w-nws.webmaster@noaa.gov",
        "identifier": identifier,
        "sent": sent,
        "msg_type": "alert",
        "event": "Tornado Warning",
        "severity": "extreme",
        "areas": ["MNZ001"],
        "expires": sent + timedelta(hours=1),
    }
    base.update(kw)
    return EasCapAlert(**base)  # type: ignore[arg-type]


# --- models -------------------------------------------------------------------


def test_severity_ranking() -> None:
    assert severity_at_or_above("extreme", "severe") is True
    assert severity_at_or_above("severe", "severe") is True
    assert severity_at_or_above("moderate", "severe") is False
    assert severity_at_or_above("unknown", "minor") is False


def test_display_decision_eas_claim_is_locked_to_not_eas() -> None:
    decision = EasDisplayDecision(
        decision_id="d1", alert_id="a1", channel_id="gov", mode="crawl", decided_by="auto"
    )
    assert decision.eas_claim == "not_eas"
    with pytest.raises(Exception):  # noqa: B017 — pydantic rejects any other claim
        EasDisplayDecision(
            decision_id="d2",
            alert_id="a1",
            channel_id="gov",
            mode="crawl",
            decided_by="auto",
            eas_claim="eas",  # type: ignore[arg-type]
        )


def test_parse_cap_references() -> None:
    refs = "w-nws@noaa.gov,NWS.1,2026-01-01T12:00:00-00:00 w-nws@noaa.gov,NWS.0,2026-01-01T11:00:00-00:00"
    assert parse_cap_references(refs) == [
        ("w-nws@noaa.gov", "NWS.1"),
        ("w-nws@noaa.gov", "NWS.0"),
    ]
    assert parse_cap_references(None) == []
    assert parse_cap_references("") == []


# --- source CRUD --------------------------------------------------------------


def test_source_upsert_get_list_delete(store: EasStore) -> None:
    store.upsert_source(_source())
    store.upsert_source(_source("src_amber", label="State AMBER", kind="amber-cap"))
    assert store.get_source("src_nws").label == "NWS api.weather.gov"
    assert {s.source_id for s in store.list_sources()} == {"src_nws", "src_amber"}
    store.upsert_source(_source(enabled=False))
    assert {s.source_id for s in store.list_sources(enabled_only=True)} == {"src_amber"}
    store.delete_source("src_amber")
    assert store.get_source("src_amber") is None
    with pytest.raises(SourceNotFoundError):
        store.delete_source("nope")


# --- alert ingest / dedup / supersede / expire --------------------------------


def test_ingest_alert_inserts_then_dedups(store: EasStore) -> None:
    _, is_new = store.ingest_alert(_alert())
    assert is_new is True
    # re-ingest the SAME (sender, identifier) with a NEWER sent → update, not a 2nd row
    _, is_new2 = store.ingest_alert(_alert(sent=_T0 + timedelta(minutes=5), headline="Updated"))
    assert is_new2 is False
    rows = store.list_alerts()
    assert len(rows) == 1
    assert rows[0].headline == "Updated"


def test_ingest_alert_ignores_older_sent(store: EasStore) -> None:
    store.ingest_alert(_alert(sent=_T0 + timedelta(minutes=5), headline="Newer"))
    # an out-of-order older delivery must not clobber the newer state
    persisted, is_new = store.ingest_alert(_alert(sent=_T0, headline="Older"))
    assert is_new is False
    assert persisted.headline == "Newer"


def test_update_supersedes_referenced_alert(store: EasStore) -> None:
    store.ingest_alert(_alert("NWS.1"))
    refs = "w-nws.webmaster@noaa.gov,NWS.1,2026-01-01T12:00:00+00:00"
    store.ingest_alert(
        _alert("NWS.2", sent=_T0 + timedelta(minutes=10), msg_type="update", references=refs)
    )
    superseded = store.get_alert("src_nws:NWS.1")
    assert superseded.status == "superseded"
    assert store.get_alert("src_nws:NWS.2").status == "active"


def test_cancel_cancels_referenced_alert(store: EasStore) -> None:
    store.ingest_alert(_alert("NWS.1"))
    refs = "w-nws.webmaster@noaa.gov,NWS.1,2026-01-01T12:00:00+00:00"
    store.ingest_alert(
        _alert("NWS.9", sent=_T0 + timedelta(minutes=10), msg_type="cancel", references=refs)
    )
    assert store.get_alert("src_nws:NWS.1").status == "cancelled"


def test_expire_alerts_flips_only_past_expiry(store: EasStore) -> None:
    store.ingest_alert(_alert("PAST", sent=_T0, expires=_T0 + timedelta(minutes=30)))
    store.ingest_alert(_alert("FUTURE", sent=_T0, expires=_T0 + timedelta(hours=6)))
    count = store.expire_alerts(now=_T0 + timedelta(hours=1))
    assert count == 1
    assert store.get_alert("src_nws:PAST").status == "expired"
    assert store.get_alert("src_nws:FUTURE").status == "active"


def test_reingest_does_not_resurrect_expired_alert(store: EasStore) -> None:
    # Blocker regression: an equal-sent re-poll (parser default status='active') must
    # NEVER flip a non-active lifecycle back to active (a recalled alert returning to air).
    store.ingest_alert(_alert("PAST", sent=_T0, expires=_T0 + timedelta(minutes=30)))
    store.expire_alerts(now=_T0 + timedelta(hours=1))
    assert store.get_alert("src_nws:PAST").status == "expired"
    _, is_new = store.ingest_alert(_alert("PAST", sent=_T0, expires=_T0 + timedelta(minutes=30)))
    assert is_new is False
    assert store.get_alert("src_nws:PAST").status == "expired"  # NOT resurrected


def test_reingest_does_not_resurrect_cancelled_alert(store: EasStore) -> None:
    store.ingest_alert(_alert("A"))
    refs = "w-nws.webmaster@noaa.gov,A,2026-01-01T12:00:00+00:00"
    store.ingest_alert(
        _alert("C", sent=_T0 + timedelta(minutes=5), msg_type="cancel", references=refs)
    )
    assert store.get_alert("src_nws:A").status == "cancelled"
    # the steady-state re-poll of A (still in the live feed at equal sent) keeps it cancelled
    store.ingest_alert(_alert("A"))
    assert store.get_alert("src_nws:A").status == "cancelled"


def test_list_active_alerts_only(store: EasStore) -> None:
    store.ingest_alert(_alert("A"))
    store.ingest_alert(_alert("B", expires=_T0 - timedelta(minutes=1)))
    store.expire_alerts(now=_T0)
    active = store.list_alerts(active_only=True)
    assert {a.identifier for a in active} == {"A"}


# --- display decisions --------------------------------------------------------


def test_decision_crud_and_state_transition(store: EasStore) -> None:
    store.upsert_decision(
        EasDisplayDecision(
            decision_id="d1",
            alert_id="src_nws:NWS.1",
            channel_id="gov",
            mode="crawl",
            decided_by="auto",
            auto_surfaced=True,
        )
    )
    assert store.get_decision("d1").state == "pending"
    store.set_decision_state("d1", "displayed", displayed_at=_T0)
    displayed = store.get_decision("d1")
    assert displayed.state == "displayed"
    assert displayed.eas_claim == "not_eas"
    assert [d.decision_id for d in store.list_decisions(channel_id="gov", state="displayed")] == [
        "d1"
    ]
    with pytest.raises(DecisionNotFoundError):
        store.set_decision_state("missing", "cleared")


# --- migration 0051 up/down reversibility -------------------------------------


def _make_cfg(database_url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


class TestPublicSafetyEasMigration:
    """0051_public_safety_eas creates the three EAS tables on upgrade and drops
    exactly those on a single-step downgrade to 0050 — the rest survives."""

    _TABLES = ("eas_cap_sources", "eas_cap_alerts", "eas_display_decisions")

    def test_upgrade_head_creates_the_three_tables(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "head")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            insp = inspect(eng)
            for table in self._TABLES:
                assert insp.has_table(table), table
            idx = {ix["name"] for ix in insp.get_indexes("eas_cap_alerts")}
            assert "ix_eas_cap_alerts_status_expires" in idx
        finally:
            eng.dispose()

    def test_single_step_downgrade_drops_only_the_three_tables(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "0050_caption_proof_samples")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            insp = inspect(eng)
            for table in self._TABLES:
                assert not insp.has_table(table), table
            assert insp.has_table("egress_caption_proof_samples")  # 0050 table survives
        finally:
            eng.dispose()
