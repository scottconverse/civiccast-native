# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""WP-07 app-wiring proof: a durable LiveSource reaches the REAL takeover service.

The defect (audit ENG-003, understated there and named explicitly in the
implementation plan): ``/api/staff/live/ingest-plan`` was fixed under bug B5 to
include the channel's ``LiveSourceStore`` rows, but
``civiccast.app._resolve_takeover_service`` kept building its ingest-plan
provider from relay configuration ONLY:

    def _ingest_plan(channel_id):
        return build_ingest_plan(channel_id, relay_store.list(...))   # no sources

So the API showed the operator a plan containing their real encoder while
production takeover was built from a different, source-less plan. On a station
with no relay row -- the default, since local RTMP needs no relay -- takeover
had nothing ready to select and 422'd, or worse, silently offered only the
legacy placeholder. ``civiccast.cli._build_takeover_service`` carried the
identical omission.

Why the existing tests never caught it: every takeover unit test builds its own
ingest plan and passes ``live_sources=`` itself
(``tests/egress/test_takeover_service.py``, ``test_takeover_router.py``), so
they exercise ``build_ingest_plan``'s contract, never the app factory's
wiring. This module resolves the real dependency-override callable out of a
real ``create_app()`` over a real migrated database -- the same
durable-app-wiring pattern as
``tests/live/test_app_preflight_source_probe_wiring.py`` and
``tests/ai_models/test_app_factory_wiring.py``.

No encoder and no ffprobe subprocess is required: the probe seam is replaced,
and the ffprobe boundary itself is covered in ``tests/live/test_source_probe.py``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from civiccast.egress.router import get_takeover_service
from civiccast.egress.takeover_service import TakeoverNotReadyError
from civiccast.live.models import LiveSource
from civiccast.live.router import get_live_source_readiness_service, get_live_source_store

_CHANNEL = "gov-ch12"
_SOURCE_ID = "council-encoder"
_ENDPOINT = "srt://0.0.0.0:9000?mode=listener"


def _migrate(db_path: Path) -> None:
    from alembic import command
    from alembic.config import Config

    repo_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")


@pytest.fixture
def durable_app_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    db_path = tmp_path / "takeover-wiring.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")
    monkeypatch.setenv("CIVICCAST_FINALIZATION_WORKER", "off")
    monkeypatch.delenv("CIVICCAST_UPLOAD_DIR", raising=False)
    _migrate(db_path)
    yield tmp_path


def _engine_over_db() -> Engine:
    """A plain engine over the same sqlite file ``DATABASE_URL`` points at.

    Mirrors ``civiccast.app._create_database_engine``'s sqlite handling: alembic
    creates sqlite tables unscoped, so ORM code built against the
    schema-qualified metadata needs the same translate map to see them.
    """
    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url, future=True)
    if database_url.startswith("sqlite"):
        engine = engine.execution_options(schema_translate_map={"civiccast": None})
    return engine


def _seed_source(engine: Engine, *, probe_state: str, observed_at: datetime | None) -> None:
    with Session(bind=engine) as sess:
        sess.add(
            LiveSource(
                live_source_id=_SOURCE_ID,
                channel_id=_CHANNEL,
                name="Council Room Encoder",
                source_type="srt",
                endpoint_url=_ENDPOINT,
                probe_state=probe_state,
                probe_observed_at=observed_at,
                probe_last_success_at=observed_at if probe_state == "ready" else None,
                row_version=1,
            )
        )
        sess.commit()


def _app_with_probe(ok: bool):  # type: ignore[no-untyped-def]
    """A real ``create_app()`` with only the ffprobe subprocess seam replaced."""
    from civiccast.app import create_app
    from civiccast.live.readiness_service import LiveSourceReadinessService
    from civiccast.live.source_probe import ProbeObservation

    app = create_app()
    store = app.dependency_overrides[get_live_source_store]()
    app.dependency_overrides[get_live_source_readiness_service] = lambda: (
        LiveSourceReadinessService(
            store,
            probe=lambda source, **_: ProbeObservation(
                ok=ok,
                detail=(
                    f"{source.name} is delivering video."
                    if ok
                    else f"{source.name} did not respond: Connection refused."
                ),
                error_code=None if ok else "probe_refused",
            ),
        )
    )
    return app


def test_a_durable_live_source_reaches_the_real_takeover_service(
    durable_app_env: Path,
) -> None:
    """The regression lock for the app-factory half of ENG-003.

    Revert ``_resolve_takeover_service``'s ``live_sources=`` argument and this
    test fails: the plan the production service sees contains no path with the
    source's id, and ``take`` raises TakeoverNotReadyError even though the
    station has a working, observed-ready encoder configured.
    """
    _seed_source(_engine_over_db(), probe_state="ready", observed_at=datetime.now(UTC))
    app = _app_with_probe(True)

    service = app.dependency_overrides[get_takeover_service]()
    plan = service._ingest_plan_provider(_CHANNEL)
    assert [path.path_id for path in plan.relay_paths] == [_SOURCE_ID], (
        "the production takeover service must build its plan from the same "
        "channel-scoped LiveSourceStore rows the ingest-plan endpoint uses"
    )
    assert plan.recommended_path_id == _SOURCE_ID

    session = service.take(channel_id=_CHANNEL, operator_id="dana", operator_name="Dana")
    assert session.source_ref == _SOURCE_ID
    assert session.source_label == "Live: Council Room Encoder"
    assert service.state(_CHANNEL).active_session is not None


def test_an_unchecked_durable_source_cannot_change_air(durable_app_env: Path) -> None:
    """The same wiring, with the source never probed and the probe failing.

    Both halves have to hold at once: the source is visible to takeover (so the
    operator can see and select it) and it still cannot take air, with no audit
    row and no queued command left behind.
    """
    _seed_source(_engine_over_db(), probe_state="never_probed", observed_at=None)
    app = _app_with_probe(False)

    service = app.dependency_overrides[get_takeover_service]()
    plan = service._ingest_plan_provider(_CHANNEL)
    assert [path.path_id for path in plan.relay_paths] == [_SOURCE_ID]
    assert plan.relay_paths[0].health_state == "not_configured"

    with pytest.raises(TakeoverNotReadyError):
        service.take(channel_id=_CHANNEL, operator_id="dana")

    assert service.state(_CHANNEL).active_session is None
    assert service.audit(_CHANNEL) == []


def test_the_takeover_gate_reprobes_and_lets_a_working_source_through(
    durable_app_env: Path,
) -> None:
    """Never-probed is not a permanent refusal: the gate looks, then decides."""
    _seed_source(_engine_over_db(), probe_state="never_probed", observed_at=None)
    app = _app_with_probe(True)

    readiness = app.dependency_overrides[get_live_source_readiness_service]()
    verdict = readiness.verify_for_takeover(
        channel_id=_CHANNEL, path_id=_SOURCE_ID, endpoint_url=_ENDPOINT
    )
    assert verdict.ok is True
    assert verdict.reprobed is True

    # And the observation is durable, so the next reader sees it too.
    store = app.dependency_overrides[get_live_source_store]()
    refreshed = store.get(_SOURCE_ID)
    assert refreshed is not None
    assert refreshed.readiness == "ready"


def test_the_cli_takeover_builder_matches_the_app_factory(durable_app_env: Path) -> None:
    """``civiccast.cli._build_takeover_service`` carried the identical omission.

    A CLI takeover must not be able to put something on air that the API would
    have refused, and it must not be blind to a source the API can see.
    """
    from civiccast import cli

    _seed_source(_engine_over_db(), probe_state="ready", observed_at=datetime.now(UTC))
    service = cli._build_takeover_service()
    plan = service._ingest_plan_provider(_CHANNEL)
    assert [path.path_id for path in plan.relay_paths] == [_SOURCE_ID]
    assert service._readiness_verifier is not None
