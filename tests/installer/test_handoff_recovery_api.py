# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""HTTP-level tests for the W-2 setup-handoff recovery routes
(``POST /api/setup/handoff-recovery/start`` and ``.../complete``).

Every test monkeypatches ``handoff_recovery._harden_recovery_dir_acl`` to a
recording no-op so no real ``win32security`` call happens here -- the SDDL
literal and the decision logic around it are covered directly in
``test_handoff_recovery.py``, matching the rest of this codebase's own
convention for Windows-only ACL seams
(``tests/native/test_pgdata_acl.py``).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.installer import handoff_recovery

_NONCE = "nonce-from-installer"


@pytest.fixture(autouse=True)
def _no_real_acl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(handoff_recovery, "_harden_recovery_dir_acl", lambda directory: None)


@pytest.fixture(autouse=True)
def _recovery_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVICCAST_SETUP_RECOVERY_DIR", str(tmp_path / "setup-recovery"))


def _start(client: TestClient) -> dict[str, object]:
    response = client.post("/api/setup/handoff-recovery/start")
    assert response.status_code == 200, response.text
    return response.json()


def _read_code(code_file: str) -> str:
    return Path(code_file).read_text().strip()


# --- happy path + "never returns the code" -----------------------------------


def test_start_never_returns_the_code(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(create_app())

    payload = _start(client)

    assert set(payload.keys()) == {"code_file", "expires_in"}
    assert payload["expires_in"] == handoff_recovery.CODE_TTL_SECONDS
    real_code = _read_code(str(payload["code_file"]))
    assert real_code not in payload["code_file"], "the code itself must never appear on the wire"


def test_start_then_complete_grants_the_configured_setup_nonce(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVICCAST_SETUP_NONCE", _NONCE)
    client = TestClient(create_app())
    payload = _start(client)
    code = _read_code(str(payload["code_file"]))

    response = client.post("/api/setup/handoff-recovery/complete", json={"code": code})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {
        "status": "recovered",
        "setup_nonce": _NONCE,
        "next_step": "Setup will resume automatically.",
    }
    # Redeemed once: the challenge file is gone, and the SAME code the
    # operator console now holds is exactly what admits every other
    # /api/setup/* mutation through the ordinary nonce-header path.
    assert not Path(str(payload["code_file"])).exists()
    other_route = client.get(
        "/api/setup/station-state",
        headers={"X-CivicCast-Setup-Nonce": body["setup_nonce"]},
    )
    assert other_route.status_code == 200


def test_complete_without_a_configured_nonce_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CIVICCAST_SETUP_NONCE", raising=False)
    client = TestClient(create_app())
    payload = _start(client)
    code = _read_code(str(payload["code_file"]))

    response = client.post("/api/setup/handoff-recovery/complete", json={"code": code})

    assert response.status_code == 503


# --- no oracle: every failure is the same generic 403 ------------------------


def test_complete_wrong_code_is_a_generic_403(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVICCAST_SETUP_NONCE", _NONCE)
    client = TestClient(create_app())
    _start(client)

    response = client.post("/api/setup/handoff-recovery/complete", json={"code": "ZZZZZZZZ"})

    assert response.status_code == 403
    assert response.json() == {"detail": "Invalid or expired setup recovery code."}


def test_complete_replayed_code_is_the_same_generic_403(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVICCAST_SETUP_NONCE", _NONCE)
    client = TestClient(create_app())
    payload = _start(client)
    code = _read_code(str(payload["code_file"]))
    first = client.post("/api/setup/handoff-recovery/complete", json={"code": code})
    assert first.status_code == 200

    replay = client.post("/api/setup/handoff-recovery/complete", json={"code": code})

    assert replay.status_code == 403
    assert replay.json() == {"detail": "Invalid or expired setup recovery code."}


def test_complete_expired_code_is_the_same_generic_403(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVICCAST_SETUP_NONCE", _NONCE)
    client = TestClient(create_app())
    payload = _start(client)
    code = _read_code(str(payload["code_file"]))
    # Backdate the challenge's own TTL on disk rather than shrinking
    # CODE_TTL_SECONDS -- that constant also feeds the /start response's
    # expires_in, which would otherwise smuggle a negative TTL onto the wire
    # instead of exercising the expiry branch this test targets.
    state_path = handoff_recovery.recovery_dir() / handoff_recovery._STATE_FILENAME
    state = json.loads(state_path.read_text())
    state["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    state_path.write_text(json.dumps(state))

    response = client.post("/api/setup/handoff-recovery/complete", json={"code": code})

    assert response.status_code == 403
    assert response.json() == {"detail": "Invalid or expired setup recovery code."}


def test_complete_burns_after_five_wrong_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVICCAST_SETUP_NONCE", _NONCE)
    client = TestClient(create_app())
    payload = _start(client)
    code = _read_code(str(payload["code_file"]))

    for _ in range(handoff_recovery.MAX_ATTEMPTS):
        wrong = client.post("/api/setup/handoff-recovery/complete", json={"code": "NNNNNNNN"})
        assert wrong.status_code == 403

    burned = client.post("/api/setup/handoff-recovery/complete", json={"code": code})

    assert burned.status_code == 403
    assert burned.json() == {"detail": "Invalid or expired setup recovery code."}


# --- loopback-only, both routes -----------------------------------------------


def test_start_is_loopback_only() -> None:
    client = TestClient(create_app(), client=("203.0.113.20", 4242))

    response = client.post("/api/setup/handoff-recovery/start")

    assert response.status_code == 403


def test_complete_is_loopback_only() -> None:
    client = TestClient(create_app(), client=("203.0.113.20", 4242))

    response = client.post("/api/setup/handoff-recovery/complete", json={"code": "AAAAAAAA"})

    assert response.status_code == 403


# --- rate limiting -------------------------------------------------------------


def test_start_is_rate_limited_to_three_per_hour() -> None:
    client = TestClient(create_app())

    for _ in range(3):
        response = client.post("/api/setup/handoff-recovery/start")
        assert response.status_code == 200

    fourth = client.post("/api/setup/handoff-recovery/start")

    assert fourth.status_code == 429
    assert "Retry-After" in fourth.headers


def test_start_rate_limit_is_keyed_per_client_ip() -> None:
    app = create_app()
    first_client = TestClient(app, client=("127.0.0.1", 1))
    second_client = TestClient(app, client=("127.0.0.2", 1))
    for _ in range(3):
        assert first_client.post("/api/setup/handoff-recovery/start").status_code == 200
    assert first_client.post("/api/setup/handoff-recovery/start").status_code == 429

    # Same shared app/limiter, but a different peer IP is a different
    # (ip, path) budget key -- the first peer exhausting its three does not
    # touch the second peer's own three.
    response = second_client.post("/api/setup/handoff-recovery/start")

    assert response.status_code == 200


# --- ACL seam is actually invoked ---------------------------------------------


def test_start_invokes_the_acl_hardening_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Path] = []
    monkeypatch.setattr(handoff_recovery, "_harden_recovery_dir_acl", calls.append)
    client = TestClient(create_app())

    _start(client)

    assert calls == [handoff_recovery.recovery_dir()]


def test_start_returns_503_when_the_acl_cannot_be_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(directory: Path) -> None:
        raise PermissionError("access denied writing the DACL")

    monkeypatch.setattr(handoff_recovery, "_harden_recovery_dir_acl", _refuse)
    client = TestClient(create_app())

    response = client.post("/api/setup/handoff-recovery/start")

    assert response.status_code == 503
