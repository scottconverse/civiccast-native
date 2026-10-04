# SPDX-License-Identifier: Apache-2.0
"""Isolated actual health endpoint proof; no DB/native/model/service activity."""

from __future__ import annotations

import importlib
import json
import logging
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def reset_receipt(monkeypatch):
    monkeypatch.setenv("CIVICCAST_CAPTION_EXECUTABLE_PROOF", "1")
    from civiccast import health_provenance as proof

    if proof._THREAD is not None:
        proof._THREAD.join(2)
        assert not proof._THREAD.is_alive()
    importlib.reload(proof)
    yield
    if proof._THREAD is not None:
        proof._THREAD.join(2)
        assert not proof._THREAD.is_alive(), "test must release its owned proof worker"


def test_default_off_does_no_capture_clock_or_dispatch(monkeypatch):
    from civiccast import health_provenance as proof

    monkeypatch.delenv("CIVICCAST_CAPTION_EXECUTABLE_PROOF", raising=False)
    importlib.reload(proof)

    def forbidden(*args, **kwargs):
        pytest.fail("default-off entered proof work")

    monkeypatch.setattr(proof, "_capture_codes", forbidden)
    monkeypatch.setattr(proof.time, "perf_counter", forbidden)
    monkeypatch.setattr(proof.threading, "Thread", forbidden)
    proof.note_health(object(), object())
    assert proof._CLAIMED is False
    assert proof._THREAD is None


def test_entropy_failure_is_unconfirmed_not_startup_failure(monkeypatch):
    from civiccast import health_provenance as proof

    def fail(size):
        raise OSError("PLANTED_ENTROPY_DETAIL")

    monkeypatch.setattr(proof.os, "urandom", fail)
    importlib.reload(proof)
    assert proof.ENABLED and proof._NONCE == "unavailable"


def test_blocked_background_hash_never_joins_caller_or_starts_replacement(monkeypatch):
    from civiccast import health_provenance as proof

    entered, release = threading.Event(), threading.Event()
    code = test_blocked_background_hash_never_joins_caller_or_starts_replacement.__code__
    monkeypatch.setattr(proof, "_capture_codes", lambda app: (("fixture", code),))
    original = proof.fingerprint_code

    def held(value):
        entered.set()
        assert release.wait(2)
        return original(value)

    monkeypatch.setattr(proof, "fingerprint_code", held)
    try:
        start = time.monotonic()
        proof.note_health(code, object())
        assert time.monotonic() - start < 0.1
        assert entered.wait(1)
        worker = proof._THREAD
        snapshot = worker._args[0]
        assert all(type(value) is type(code) for _, value in snapshot.selected)
        assert not hasattr(snapshot, "app") and not hasattr(snapshot, "owner")
        for _ in range(100):
            proof.note_health(code, object())
        assert proof._THREAD is worker
    finally:
        release.set()


def test_late_failure_is_unavailable_without_private_exception(monkeypatch, caplog):
    from civiccast import health_provenance as proof

    code = test_late_failure_is_unavailable_without_private_exception.__code__
    monkeypatch.setattr(proof, "_capture_codes", lambda app: (("fixture", code),))

    def fail(value):
        raise ValueError("PLANTED_PRIVATE_EXCEPTION")

    monkeypatch.setattr(proof, "fingerprint_code", fail)
    with caplog.at_level(logging.INFO):
        proof.note_health(code, object())
        proof._THREAD.join(1)
    receipts = [
        r.message for r in caplog.records if "Health diagnostic executable receipt " in r.message
    ]
    assert len(receipts) == 1
    assert json.loads(receipts[0].split("receipt ", 1)[1])["status"] == "unavailable"
    assert "PLANTED_PRIVATE_EXCEPTION" not in receipts[0]


def test_reloaded_or_changed_anchor_is_not_the_original_code():
    from civiccast.captions.diagnostic_identity import fingerprint_code

    old = compile("def anchor(): return 1", "installed.py", "exec").co_consts[0]
    changed = compile("def anchor(): return 2", "installed.py", "exec").co_consts[0]
    reloaded = compile("def anchor(): return 1", "other.py", "exec").co_consts[0]
    assert fingerprint_code(old) != fingerprint_code(changed)
    # Algorithm intentionally ignores origin; origin must be bound separately.
    assert old.co_filename != reloaded.co_filename
    assert fingerprint_code(old) == fingerprint_code(reloaded)


def test_actual_health_enabled_emits_once_without_private_state(monkeypatch, tmp_path, caplog):
    from tests.support.hermetic_state import hermetic_environment

    for key, value in hermetic_environment(tmp_path).items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", raising=False)
    monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")
    monkeypatch.setenv("CIVICCAST_CAPTION_EXECUTABLE_PROOF", "1")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.delenv("CIVICCAST_STAFF_TOKENS", raising=False)
    import civiccast.app as module

    # Actual configured constructor assembles durable workers and imports the
    # lazy outbox; no fixture-only import may manufacture loaded identity.
    app = module.create_app()
    assert len(module.health_provenance._capture_codes(app)) == sum(
        len(v) for v in module.health_provenance.ANCHORS.values()
    )
    app.state.planted_private = "PLANTED_TRANSCRIPT_AUDIO_CREDENTIAL"
    try:
        with caplog.at_level(logging.INFO), TestClient(app) as client:
            client.get("/health")
            client.get("/api/health")
            deadline = time.monotonic() + 1
            while (
                not any(
                    "Health diagnostic executable receipt " in r.message for r in caplog.records
                )
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
        receipts = [
            r.message.split("Health diagnostic executable receipt ", 1)[1]
            for r in caplog.records
            if "Health diagnostic executable receipt " in r.message
        ]
        assert len(receipts) == 1, "enabled actual health frame must emit one bounded receipt"
        payload = json.loads(receipts[0])
        assert payload["status"] == "ok"
        assert payload["executing_matches_selected"] is True
        assert payload["executing"]["qualname"] == "create_app.<locals>.health"
        assert "PLANTED_TRANSCRIPT_AUDIO_CREDENTIAL" not in receipts[0]
        from civiccast.captions.diagnostic_identity import compiled_anchors, fingerprint_code

        for item in payload["selected"]:
            compiled = compile(Path(item["filename"]).read_bytes(), item["filename"], "exec")
            assert item["sha256"] == fingerprint_code(compiled_anchors(compiled)[item["qualname"]])
    finally:
        assert app.state.health_schema_owner.close(2)
        assert app.state.as_run_outbox.close()
        from civiccast.db import reset_engine

        reset_engine()


def test_ephemeral_missing_support_is_responsive_but_not_attested(monkeypatch, tmp_path, caplog):
    import sys

    from tests.support.hermetic_state import hermetic_environment

    for key, value in hermetic_environment(tmp_path).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CIVICCAST_STAFF_TOKENS", raising=False)
    import civiccast.app as module

    # Model a fresh ephemeral process even when a prior durable test loaded it.
    monkeypatch.delitem(sys.modules, "civiccast.reporting.asrun_outbox", raising=False)
    app = module.create_app()
    try:
        with caplog.at_level(logging.INFO), TestClient(app) as client:
            assert client.get("/health").status_code == 200
            module.health_provenance._THREAD.join(1)
        receipts = [
            r.message
            for r in caplog.records
            if "Health diagnostic executable receipt " in r.message
        ]
        assert len(receipts) == 1
        assert json.loads(receipts[0].split("receipt ", 1)[1])["status"] == "unavailable"
    finally:
        assert app.state.health_schema_owner.close(2)
