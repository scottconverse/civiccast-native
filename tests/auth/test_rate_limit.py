# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Unit + endpoint coverage for the in-process auth rate limiter."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest
from fastapi.testclient import TestClient

import civiccast.auth.middleware as auth_middleware
import civiccast.installer.station_state as station_state
from civiccast.app import create_app
from civiccast.auth.rate_limit import AuthRateLimiter, client_ip
from civiccast.auth.store import InMemoryStaffTokenStore
from civiccast.auth.tokens import token_matches_exactly

_CONFIGURED_TOKEN = "ccenv1_eLgPYWMIlFTY9OV5oKIxZejCZmleu_NFVhFSjXd3fQo"


def test_limiter_allows_up_to_the_limit_then_blocks() -> None:
    limiter = AuthRateLimiter()
    for _ in range(5):
        assert limiter.allow("k", limit=5, window_seconds=60) is True
    assert limiter.allow("k", limit=5, window_seconds=60) is False


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("CIVICCAST_AUTH_RATE_LIMIT", "0"),
        ("CIVICCAST_AUTH_RATE_LIMIT", "not-an-int"),
        ("CIVICCAST_AUTH_RATE_LIMIT_WINDOW_SECONDS", "-1"),
        ("CIVICCAST_AUTH_RATE_LIMIT_WINDOW_SECONDS", "not-an-int"),
    ],
)
def test_invalid_auth_rate_limit_config_fails_at_startup(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=name):
        create_app()


def test_limiter_recovers_after_the_window_slides(monkeypatch) -> None:
    from datetime import UTC, datetime, timedelta

    import civiccast.auth.rate_limit as rate_limit_module

    limiter = AuthRateLimiter()
    now = datetime(2026, 1, 1, tzinfo=UTC)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return now

    monkeypatch.setattr(rate_limit_module, "datetime", _FrozenDatetime)
    for _ in range(3):
        assert limiter.allow("k", limit=3, window_seconds=10) is True
    assert limiter.allow("k", limit=3, window_seconds=10) is False

    now = now + timedelta(seconds=11)
    assert limiter.allow("k", limit=3, window_seconds=10) is True


def test_limiter_keys_are_independent() -> None:
    limiter = AuthRateLimiter()
    assert limiter.allow("a", limit=1, window_seconds=60) is True
    assert limiter.allow("b", limit=1, window_seconds=60) is True
    assert limiter.allow("a", limit=1, window_seconds=60) is False
    assert limiter.allow("b", limit=1, window_seconds=60) is False


def test_client_ip_falls_back_to_unknown_without_a_client() -> None:
    class _Request:
        client = None

    assert client_ip(_Request()) == "unknown"  # type: ignore[arg-type]


def test_setup_login_trips_429_with_retry_after(monkeypatch) -> None:
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT", "3")
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")
    client = TestClient(create_app())

    login_body = {"admin_username": "avery", "admin_password": "wrong password entirely"}
    responses = [client.post("/api/setup/login", json=login_body) for _ in range(4)]

    # First 3 are real auth attempts (401, no such admin yet); the 4th is
    # rate-limited before it ever reaches login logic.
    assert [r.status_code for r in responses[:3]] == [401, 401, 401]
    limited = responses[3]
    assert limited.status_code == 429
    assert "Retry-After" in limited.headers
    assert int(limited.headers["Retry-After"]) > 0


def test_setup_rate_limit_keys_are_independent_per_route(monkeypatch) -> None:
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT", "1")
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")
    client = TestClient(create_app())

    login_body = {"admin_username": "avery", "admin_password": "wrong"}
    recover_body = {
        "admin_username": "avery",
        "recovery_code": "bogus-code",
        "new_admin_password": "irrelevant password",
    }

    first_login = client.post("/api/setup/login", json=login_body)
    second_login = client.post("/api/setup/login", json=login_body)
    first_recover = client.post("/api/setup/recover", json=recover_body)

    assert first_login.status_code == 401
    assert second_login.status_code == 429
    # A different route's own budget is untouched by /login's exhaustion.
    assert first_recover.status_code == 401


def test_default_limit_survives_the_existing_full_setup_flow(monkeypatch, tmp_path) -> None:
    """Defaults must never trip the documented 10-step operator flow."""

    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    client = TestClient(create_app())

    setup = client.post(
        "/api/setup/first-admin",
        json={
            "station_name": "Pinegrove School Board",
            "admin_display_name": "Avery Admin",
            "admin_username": "avery",
            "admin_password": "correct horse battery staple",
            "recovery_kit_destination": "printed and stored in the clerk safe",
        },
    )
    assert setup.status_code == 200

    for _ in range(5):
        login = client.post(
            "/api/setup/login",
            json={"admin_username": "avery", "admin_password": "correct horse battery staple"},
        )
        assert login.status_code == 200


def test_staff_bearer_brute_force_trips_429_with_retry_after(monkeypatch) -> None:
    """Audit item #27 review: /api/staff/* was an unthrottled bearer-token
    oracle. Failed verifications from one IP must trip 429 regardless of
    whether each guess is a different token (the key is the IP, not the
    token, so a rotating brute-forcer cannot reset its own bucket)."""

    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT", "5")
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")
    client = TestClient(create_app())

    responses = [
        client.get(
            "/api/staff/installer/summary",
            headers={"Authorization": f"Bearer guessed-token-{index}"},
        )
        for index in range(7)
    ]

    assert [r.status_code for r in responses[:5]] == [401] * 5
    for limited in responses[5:]:
        assert limited.status_code == 429
        assert int(limited.headers["Retry-After"]) > 0


async def test_saturated_invalid_flood_cannot_queue_a_valid_configured_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CIVICCAST_ALLOW_DETERMINISTIC_STAFF_TOKEN", raising=False)
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT", "1")
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS",
        f"{_CONFIGURED_TOKEN}:operator-1:Operator One:operator",
    )
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        bad_headers = {"Authorization": "Bearer initial-guess"}
        first = await client.get("/api/staff/installer/summary", headers=bad_headers)
        assert first.status_code == 401

        flood = [
            asyncio.create_task(
                client.get(
                    "/api/staff/installer/summary",
                    headers={"Authorization": f"Bearer queued-guess-{index}"},
                )
            )
            for index in range(4)
        ]
        await asyncio.sleep(0.01)
        started = time.monotonic()
        valid = await client.get(
            "/api/staff/installer/summary",
            headers={"Authorization": f"Bearer {_CONFIGURED_TOKEN}"},
        )
        valid_elapsed = time.monotonic() - started
        await asyncio.gather(*flood)

    assert valid.status_code == 200
    assert valid_elapsed < 0.5


async def test_saturated_invalid_flood_cannot_queue_a_valid_lifecycle_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT", "1")
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")
    store = InMemoryStaffTokenStore()
    issued = store.issue_token(
        operator_id="operator-1",
        operator_display_name="Operator One",
        scopes=("operator",),
    )
    app = create_app()
    app.state.staff_token_store = store
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.get(
            "/api/staff/installer/summary",
            headers={"Authorization": "Bearer initial-guess"},
        )
        assert first.status_code == 401
        verified_secrets: list[str] = []
        original_verify_token = store.verify_token

        def track_verify_token(secret: str):
            verified_secrets.append(secret)
            return original_verify_token(secret)

        monkeypatch.setattr(store, "verify_token", track_verify_token)
        flood = [
            asyncio.create_task(
                client.get(
                    "/api/staff/installer/summary",
                    headers={"Authorization": f"Bearer rotating-guess-{index}"},
                )
            )
            for index in range(50)
        ]
        await asyncio.sleep(0)
        valid = await client.get(
            "/api/staff/installer/summary",
            headers={"Authorization": f"Bearer {issued.secret}"},
        )
        responses = await asyncio.gather(*flood)

    assert valid.status_code == 200
    assert verified_secrets == [issued.secret]
    assert all(response.status_code == 429 for response in responses)


def test_exact_token_matcher_rejects_malformed_unknown_revoked_and_wrong_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CIVICCAST_ALLOW_DETERMINISTIC_STAFF_TOKEN", raising=False)
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS",
        f"{_CONFIGURED_TOKEN}:operator-1:Operator One:operator",
    )
    assert token_matches_exactly(f"Bearer {_CONFIGURED_TOKEN}") is True
    assert token_matches_exactly("Bearer wrong-secret") is False
    assert token_matches_exactly("not-bearer") is False

    store = InMemoryStaffTokenStore()
    issued = store.issue_token(
        operator_id="operator-2",
        operator_display_name="Operator Two",
    )
    assert token_matches_exactly(f"Bearer {issued.secret}", token_store=store) is True
    assert token_matches_exactly(f"Bearer {issued.secret}-wrong", token_store=store) is False
    store.revoke_token(issued.metadata.token_id, reason="test")
    assert token_matches_exactly(f"Bearer {issued.secret}", token_store=store) is False


def test_saturated_unconfigured_auth_returns_429_instead_of_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT", "1")
    monkeypatch.delenv("CIVICCAST_STAFF_TOKENS", raising=False)
    client = TestClient(create_app())
    headers = {"Authorization": "Bearer guess"}

    assert client.get("/api/staff/installer/summary", headers=headers).status_code == 401
    assert client.get("/api/staff/installer/summary", headers=headers).status_code == 429
    assert client.get("/api/staff/installer/summary", headers=headers).status_code == 429


def test_saturated_exact_misses_do_not_reach_authoritative_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CIVICCAST_ALLOW_DETERMINISTIC_STAFF_TOKEN", raising=False)
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT", "1")
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS",
        f"{_CONFIGURED_TOKEN}:operator-1:Operator One:operator",
    )
    verifier_calls = 0
    real_verifier = auth_middleware.verify_bearer_token

    def counting_verifier(*args: object, **kwargs: object) -> object:
        nonlocal verifier_calls
        verifier_calls += 1
        return real_verifier(*args, **kwargs)

    monkeypatch.setattr(auth_middleware, "verify_bearer_token", counting_verifier)
    client = TestClient(create_app())
    statuses = [
        client.get(
            "/api/staff/installer/summary",
            headers={"Authorization": f"Bearer wrong-{index}"},
        ).status_code
        for index in range(3)
    ]

    assert statuses == [401, 429, 429]
    assert verifier_calls == 1


def test_staff_valid_configured_token_survives_shared_ip_failure_budget(monkeypatch) -> None:
    """A noisy client behind the operator's NAT must not deny a valid token."""

    monkeypatch.delenv("CIVICCAST_ALLOW_DETERMINISTIC_STAFF_TOKEN", raising=False)
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT", "2")
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS",
        f"{_CONFIGURED_TOKEN}:operator-1:Operator One:operator",
    )
    client = TestClient(create_app())
    bad = {"Authorization": "Bearer guessed-token"}
    valid = {"Authorization": f"Bearer {_CONFIGURED_TOKEN}"}

    assert client.get("/api/staff/installer/summary", headers=bad).status_code == 401
    assert client.get("/api/staff/installer/summary", headers=bad).status_code == 401
    assert client.get("/api/staff/installer/summary", headers=valid).status_code == 200

    limited = client.get(
        "/api/staff/installer/summary",
        headers={"Authorization": "Bearer another-guessed-token"},
    )
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) > 0


def test_staff_valid_lifecycle_token_survives_shared_ip_failure_budget(monkeypatch) -> None:
    """The native token-store path has the same shared-IP availability contract."""

    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT", "2")
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")
    store = InMemoryStaffTokenStore()
    issued = store.issue_token(
        operator_id="operator-1",
        operator_display_name="Operator One",
        scopes=("operator",),
    )
    app = create_app()
    app.state.staff_token_store = store
    client = TestClient(app)
    bad = {"Authorization": "Bearer guessed-token"}
    valid = {"Authorization": f"Bearer {issued.secret}"}

    assert client.get("/api/staff/installer/summary", headers=bad).status_code == 401
    assert client.get("/api/staff/installer/summary", headers=bad).status_code == 401
    assert client.get("/api/staff/installer/summary", headers=valid).status_code == 200

    limited = client.get(
        "/api/staff/installer/summary",
        headers={"Authorization": "Bearer another-guessed-token"},
    )
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) > 0


def test_staff_valid_station_token_survives_shared_ip_failure_budget(monkeypatch) -> None:
    """The installed station token remains usable after the peer exhausts its budget."""

    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT", "1")
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.delenv("CIVICCAST_STAFF_TOKENS", raising=False)
    token = "station-token"
    salt = "station-token-salt"
    monkeypatch.setattr(
        station_state,
        "_load_raw_state",
        lambda: {
            "admin": {"username": "first-admin", "display_name": "First Admin"},
            "operator_console": {
                "token_salt": salt,
                "token_hash": station_state._hash_token(token, salt=salt),
            },
        },
    )

    assert token_matches_exactly(f"Bearer {token}") is True
    assert token_matches_exactly("Bearer wrong-station-token") is False

    client = TestClient(create_app())
    assert (
        client.get(
            "/api/staff/installer/summary",
            headers={"Authorization": "Bearer first-guess"},
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/staff/installer/summary",
            headers={"Authorization": "Bearer second-guess"},
        ).status_code
        == 429
    )
    assert (
        client.get(
            "/api/staff/installer/summary",
            headers={"Authorization": f"Bearer {token}"},
        ).status_code
        == 200
    )


def test_staff_valid_token_traffic_is_never_throttled(monkeypatch) -> None:
    """Valid-token requests must not count against any limit — the operator
    console legitimately fires bursts far above the failure budget."""

    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT", "5")
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")
    client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})

    for _ in range(30):
        assert client.get("/api/staff/installer/summary").status_code == 200


def test_staff_throttle_recovers_after_the_window(monkeypatch) -> None:
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT", "2")
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT_WINDOW_SECONDS", "1")
    client = TestClient(create_app())

    bad = {"Authorization": "Bearer nope"}
    assert client.get("/api/staff/installer/summary", headers=bad).status_code == 401
    assert client.get("/api/staff/installer/summary", headers=bad).status_code == 401
    assert client.get("/api/staff/installer/summary", headers=bad).status_code == 429

    import time

    time.sleep(1.1)
    assert client.get("/api/staff/installer/summary", headers=bad).status_code == 401
