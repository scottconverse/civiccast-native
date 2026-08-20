# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S23 §6.1 — cross-module id-pattern drift must NOT silently drop as-run rows.

E-1 was a Major franchise-compliance footgun: an upstream ``channel_id`` /
``asset_id`` / station_id env value that fails the reporting-module ``Slug``
pattern would cause the recorder's outer ``try/except`` to swallow the
``ValidationError`` and silently drop the as-aired row. The exact failure mode
S23 §6.1 exists to prevent (the franchise audit gets a zero-hours report
without anyone noticing).

The fix splits schema-drift from transport errors:

* ``ValidationError`` → re-raised as :class:`AsRunCaptureSchemaError` (a typed,
  loud signal the daemon catches separately to mark degraded mode).
* Other exceptions → keep the existing swallow-and-log behavior (a transient
  DB hiccup must not break the playout path).

A startup self-check on ``resolve_station_id`` validates
``CIVICCAST_STATION_ID`` against the same ``Slug`` pattern at boot — a typo
fails closed rather than silently dropping every row.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.egress.asrun import AsRunCaptureSchemaError
from civiccast.reporting.asrun_recorder import (
    StoreAsRunRecorder,
    resolve_station_id,
)
from civiccast.reporting.store import ReportingStore


@pytest.fixture
def reporting_store(tmp_path: Path) -> Iterator[ReportingStore]:
    eng = create_engine(f"sqlite:///{tmp_path / 'reporting.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    try:
        yield ReportingStore(factory)
    finally:
        eng.dispose()


def test_invalid_channel_id_raises_asruncaptureschemaerror(
    reporting_store: ReportingStore,
) -> None:
    """A ``channel_id`` violating the lowercase-Slug pattern must raise the
    typed schema-drift exception — not silently drop the row.

    This is the exact upstream-id-drift scenario E-1 was filed for: the egress
    config allows uppercase / longer channel ids (no pattern, max 80); the
    reporting Slug enforces ``^[a-z0-9][a-z0-9_-]*$``. A typo'd
    ``channel_id="ChannelA"`` used to be silently swallowed.
    """
    recorder = StoreAsRunRecorder(reporting_store, station_id="civiccast-station")
    with pytest.raises(AsRunCaptureSchemaError, match="ChannelA"):
        recorder.record_transition(
            channel_id="ChannelA",  # uppercase — fails Slug pattern
            source_kind="program",
            asset_id="asset-ok",
            source_label="Council meeting",
            actual_start=datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
            proof_event_id="proof-1",
        )
    # And nothing is in the ledger — the drop is loud, not silent.
    assert reporting_store.list_as_run("civiccast-station") == []


def test_resolve_station_id_invalid_env_raises_at_boot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``CIVICCAST_STATION_ID`` env that fails the Slug pattern must fail
    at boot (``resolve_station_id``) rather than silently dropping every
    as-run row at runtime.

    ``My-Station`` is the operator-typed mixed-case label the deep-dive
    flagged — perfectly reasonable from a console / Helm chart, but fatal
    to the ledger contract before this fix.
    """
    monkeypatch.setenv("CIVICCAST_STATION_ID", "My-Station")  # uppercase fails
    with pytest.raises(AsRunCaptureSchemaError, match="CIVICCAST_STATION_ID"):
        resolve_station_id()


def test_valid_lowercase_channel_id_writes_a_row(
    reporting_store: ReportingStore,
) -> None:
    """Regression: the recorder still happily writes a row when the upstream
    ids match the Slug pattern. The schema-drift branch is narrow — every
    valid id round-trips into the ledger as before.
    """
    recorder = StoreAsRunRecorder(reporting_store, station_id="civiccast-station")
    recorder.record_transition(
        channel_id="gov-ch12",  # valid Slug
        source_kind="program",
        asset_id="asset-council",
        source_label="Council meeting",
        actual_start=datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
        proof_event_id="proof-ok",
    )
    rows = reporting_store.list_as_run("civiccast-station")
    assert len(rows) == 1
    assert rows[0].channel_id == "gov-ch12"
    assert rows[0].asset_id == "asset-council"
