# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""The pre-broadcast checklist must tell the truth about the publish tiers.

GauntletGate PE-2 (Major, 2026-07-21). Three of the nine pre-broadcast checks
-- syndication, internet_archive, nas -- were hard-coded to ``not_configured``
with the message "the underlying integration lands in a later rung." That text
was written at Sprint 0.4 and was still shipping at 1.0.0-rc17, by which point
all three integrations existed (``civiccast/archive/internet_archive.py``,
``civiccast/archive/local_nas.py``, ``civiccast/syndicate/youtube.py``).

Two problems, both fixed here:

1. The copy was **false**. It described a codebase from three release ladders
   ago and rendered verbatim to staff on every pre-flight run.
2. The check was **dead**. An operator about to air a three-hour council
   meeting could not learn from it whether the meeting would actually reach the
   Internet Archive afterwards -- which, per the records-clerk guide, is
   required for a public-record meeting. Discovering a simulated archive after
   the meeting is discovering it too late.

The checks now read the same provider registry the publish path itself
resolves through, so the checklist and the publish run cannot disagree.
Readiness is deliberately unchanged: these surfaces complete asynchronously
after the recording and must never block go-live.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import civiccast.schedule.models  # noqa: F401  -- ATTACH hook on SQLite
from civiccast.db import Base, bind_engine, reset_engine
from civiccast.live import (
    PREFLIGHT_CHECK_INTERNET_ARCHIVE,
    PREFLIGHT_CHECK_NAS,
    PREFLIGHT_CHECK_SYNDICATION,
    PREFLIGHT_STATUS_FAIL,
    PREFLIGHT_STATUS_NOT_CONFIGURED,
    PREFLIGHT_STATUS_PASS,
    LiveSession,
    LiveSource,
    PreflightEvaluator,
    PreflightInputs,
    RecordingTarget,
)
from civiccast.live.preflight import (
    REASON_PUBLISH_SURFACE_MISCONFIGURED,
    REASON_PUBLISH_SURFACE_SIMULATED,
)

CHANNEL = "gov-ch12"
SESSION_ID = "council-2026-05-15"

# (check name, provider env var, the vars a real publish needs)
IA_CREDENTIALS = {
    "CIVICCAST_IA_ACCESS_KEY": "test-access-key",
    "CIVICCAST_IA_SECRET_KEY": "test-secret-key",
}
YOUTUBE_CREDENTIALS = {
    "CIVICCAST_YOUTUBE_CLIENT_ID": "test-client-id",
    "CIVICCAST_YOUTUBE_CLIENT_SECRET": "test-client-secret",
    "CIVICCAST_YOUTUBE_REFRESH_TOKEN": "test-refresh-token",
}


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
def evaluator(engine: Engine) -> PreflightEvaluator:
    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    with Session(bind=engine) as sess:
        sess.add(
            LiveSession(
                live_session_id=SESSION_ID,
                channel_id=CHANNEL,
                title="City Council Meeting",
                state="idle",
            )
        )
        sess.add(
            LiveSource(
                live_source_id="room-a-rtmp",
                channel_id=CHANNEL,
                name="Council Room A RTMP",
                source_type="rtmp",
                endpoint_url="rtmp://camera.example/live",
            )
        )
        sess.add(
            RecordingTarget(
                recording_target_id="nas-primary",
                name="NAS Primary",
                target_uri="/srv/civiccast/recordings",
            )
        )
        sess.commit()

    return PreflightEvaluator(
        session_factory=factory,
        source_probe=lambda source: (True, "media delivered"),
    )


def _inputs() -> PreflightInputs:
    return PreflightInputs(
        live_session_id=SESSION_ID,
        live_source_id="room-a-rtmp",
        network_reachable=True,
        storage_free_bytes=500 * (1024**3),
        ai_runtime_ready=True,
        operator_confirmed=True,
    )


def _check(evaluator: PreflightEvaluator, name: str):  # type: ignore[no-untyped-def]
    return {c.name: c for c in evaluator.evaluate(_inputs()).checks}[name]


# ---------------------------------------------------------------------------
# Simulated (the shipped default)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "check_name",
    [PREFLIGHT_CHECK_SYNDICATION, PREFLIGHT_CHECK_INTERNET_ARCHIVE, PREFLIGHT_CHECK_NAS],
)
def test_default_install_says_simulated_in_plain_words(
    evaluator: PreflightEvaluator, monkeypatch: pytest.MonkeyPatch, check_name: str
) -> None:
    for kind in ("YOUTUBE", "INTERNET_ARCHIVE", "LOCAL_NAS"):
        monkeypatch.delenv(f"CIVICCAST_PROVIDER_{kind}", raising=False)

    check = _check(evaluator, check_name)

    assert check.status == PREFLIGHT_STATUS_NOT_CONFIGURED
    assert check.reason_code == REASON_PUBLISH_SURFACE_SIMULATED
    assert check.message is not None
    assert "will NOT be published" in check.message, (
        "An operator must be able to read this line and understand that nothing "
        "reaches the outside world -- not infer it from the word 'mock'."
    )
    assert "later rung" not in check.message


# ---------------------------------------------------------------------------
# Real and usable
# ---------------------------------------------------------------------------


def test_internet_archive_with_real_credentials_passes(
    evaluator: PreflightEvaluator, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CIVICCAST_PROVIDER_INTERNET_ARCHIVE", "real")
    for name, value in IA_CREDENTIALS.items():
        monkeypatch.setenv(name, value)

    check = _check(evaluator, PREFLIGHT_CHECK_INTERNET_ARCHIVE)

    assert check.status == PREFLIGHT_STATUS_PASS
    assert check.message is not None
    assert "will be published there" in check.message


def test_syndication_with_real_credentials_passes(
    evaluator: PreflightEvaluator, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CIVICCAST_PROVIDER_YOUTUBE", "real")
    for name, value in YOUTUBE_CREDENTIALS.items():
        monkeypatch.setenv(name, value)

    assert _check(evaluator, PREFLIGHT_CHECK_SYNDICATION).status == PREFLIGHT_STATUS_PASS


def test_nas_with_a_reachable_archive_directory_passes(
    evaluator: PreflightEvaluator, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    archive_root = tmp_path / "nas-archive"
    archive_root.mkdir()
    monkeypatch.setenv("CIVICCAST_PROVIDER_LOCAL_NAS", "real")
    monkeypatch.setenv("CIVICCAST_NAS_ARCHIVE_PATH", str(archive_root))

    assert _check(evaluator, PREFLIGHT_CHECK_NAS).status == PREFLIGHT_STATUS_PASS


# ---------------------------------------------------------------------------
# Real but unusable -- the case the old placeholder could never surface
# ---------------------------------------------------------------------------


def test_real_internet_archive_without_credentials_fails_and_names_the_variables(
    evaluator: PreflightEvaluator, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CIVICCAST_PROVIDER_INTERNET_ARCHIVE", "real")
    for name in IA_CREDENTIALS:
        monkeypatch.delenv(name, raising=False)

    check = _check(evaluator, PREFLIGHT_CHECK_INTERNET_ARCHIVE)

    assert check.status == PREFLIGHT_STATUS_FAIL
    assert check.reason_code == REASON_PUBLISH_SURFACE_MISCONFIGURED
    assert check.message is not None
    assert "CIVICCAST_IA_ACCESS_KEY" in check.message
    assert "can still go ahead" in check.message, (
        "A broken archive surface must not read as 'do not broadcast'. The "
        "recording is still made and the surface is retried once fixed."
    )


def test_real_nas_pointed_at_a_missing_mount_fails(
    evaluator: PreflightEvaluator, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CIVICCAST_PROVIDER_LOCAL_NAS", "real")
    monkeypatch.setenv("CIVICCAST_NAS_ARCHIVE_PATH", str(tmp_path / "not-mounted"))

    check = _check(evaluator, PREFLIGHT_CHECK_NAS)

    assert check.status == PREFLIGHT_STATUS_FAIL
    assert check.reason_code == REASON_PUBLISH_SURFACE_MISCONFIGURED


def test_a_misconfigured_publish_surface_does_not_block_going_on_air(
    evaluator: PreflightEvaluator, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Readiness is unchanged. These tiers complete after the recording."""

    monkeypatch.setenv("CIVICCAST_PROVIDER_INTERNET_ARCHIVE", "real")
    for name in IA_CREDENTIALS:
        monkeypatch.delenv(name, raising=False)

    evaluation = evaluator.evaluate(_inputs())

    surface = {c.name: c for c in evaluation.checks}[PREFLIGHT_CHECK_INTERNET_ARCHIVE]
    assert surface.status == PREFLIGHT_STATUS_FAIL
    assert evaluation.ready is True


def test_preflight_and_the_archive_proof_agree_about_simulation(
    evaluator: PreflightEvaluator, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The seam TW-1 lived in: the checklist and the proof must not disagree.

    If pre-flight ever said "configured" while the publish run minted a
    ``simulated=True`` proof, an operator would have been told before the
    meeting that the archive was handled and shown a simulation afterwards.
    Both sides resolve through the same registry; this pins that they do.
    """

    from civiccast.platform.providers import (
        PROVIDER_KIND_INTERNET_ARCHIVE,
        default_registry,
    )

    monkeypatch.delenv("CIVICCAST_PROVIDER_INTERNET_ARCHIVE", raising=False)

    check = _check(evaluator, PREFLIGHT_CHECK_INTERNET_ARCHIVE)
    client = default_registry().resolve(PROVIDER_KIND_INTERNET_ARCHIVE)
    proof = client.upload(asset_id="council-2026-05-15", payload=b"meeting-bytes")

    assert check.status == PREFLIGHT_STATUS_NOT_CONFIGURED
    assert proof.simulated is True, (
        "Pre-flight reported a simulated Internet Archive surface, so the "
        "publish proof must be marked simulated too."
    )


def test_a_secret_value_never_reaches_the_operator_message(
    evaluator: PreflightEvaluator, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resolution errors name missing VARIABLES; they must never echo values."""

    monkeypatch.setenv("CIVICCAST_PROVIDER_INTERNET_ARCHIVE", "real")
    monkeypatch.setenv("CIVICCAST_IA_ACCESS_KEY", "super-secret-access-key")
    monkeypatch.delenv("CIVICCAST_IA_SECRET_KEY", raising=False)

    check = _check(evaluator, PREFLIGHT_CHECK_INTERNET_ARCHIVE)

    assert check.status == PREFLIGHT_STATUS_FAIL
    assert check.message is not None
    assert "super-secret-access-key" not in check.message
