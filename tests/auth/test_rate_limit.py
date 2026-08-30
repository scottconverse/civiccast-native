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


def test_setup_login_lockout_message_states_wait_and_way_forward(monkeypatch) -> None:
    """Field bug (candidate #17): the old detail text ('Too many setup
    requests. Wait before trying again.') named neither how long nor what to
    do, so a locked-out single-box admin read it as a dead end. The message
    must name the wait AND a concrete next step."""

    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT", "1")
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")
    client = TestClient(create_app())

    login_body = {"admin_username": "avery", "admin_password": "wrong"}
    client.post("/api/setup/login", json=login_body)
    limited = client.post("/api/setup/login", json=login_body)

    assert limited.status_code == 429
    detail = limited.json()["detail"]
    assert "wait" in detail.lower()
    assert "60 seconds" in detail or "second" in detail.lower()
    assert "recovery code" in detail.lower() or "password" in detail.lower()


def test_setup_login_only_counts_failed_attempts_against_the_budget(monkeypatch, tmp_path) -> None:
    """Field bug (candidate #17): a few wrong-password retries used to burn
    the SAME budget as every other request to the route, so the correct
    password submitted right after could itself get 429'd. Only the wrong
    attempts should count; a correct password always gets through as long
    as the failure budget itself was not exhausted first."""

    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT", "2")
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")
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

    # One wrong guess (within the failure budget of 2), then the correct
    # password: the correct attempt must never be penalized for having read
    # setup state or having tried once before.
    wrong = client.post(
        "/api/setup/login",
        json={"admin_username": "avery", "admin_password": "not it"},
    )
    assert wrong.status_code == 401
    right = client.post(
        "/api/setup/login",
        json={"admin_username": "avery", "admin_password": "correct horse battery staple"},
    )
    assert right.status_code == 200


def test_recovery_then_stale_password_retry_never_locks_out_the_correct_one(
    monkeypatch,
    tmp_path,
) -> None:
    """Reproduces field report #3 end-to-end: after a recovery changes the
    password, a couple of retries against the now-stale OLD password must
    not burn through the budget so badly that the actual NEW password also
    gets rejected with 429."""

    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT", "3")
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")
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
    recovery_code = setup.json()["recovery_kit"]["recovery_codes"][0]

    recovery = client.post(
        "/api/setup/recover",
        json={
            "admin_username": "avery",
            "recovery_code": recovery_code,
            "new_admin_password": "fresh horse battery staple",
        },
    )
    assert recovery.status_code == 200

    # Two retries against the now-stale old password (a realistic amount of
    # confusion, still under the failure budget of 3).
    for _ in range(2):
        stale = client.post(
            "/api/setup/login",
            json={"admin_username": "avery", "admin_password": "correct horse battery staple"},
        )
        assert stale.status_code == 401

    correct = client.post(
        "/api/setup/login",
        json={"admin_username": "avery", "admin_password": "fresh horse battery staple"},
    )
    assert correct.status_code == 200


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


def test_signed_out_browsers_normal_page_loads_never_trip_the_staff_budget(
    monkeypatch,
) -> None:
    """Day-one-lockout audit finding #1, live repro: loading the console then
    #/help then #/assets -- three ordinary page loads, never signed in, no
    password ever typed -- sent a run of /api/staff/* GETs with NO
    Authorization header at all and tripped 429 within seconds. A missing
    credential is the routine state of a signed-out browser, not a failed
    guess, so it must never consume the failure budget or ever be blocked by
    it -- however many requests arrive."""

    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT", "3")
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")
    client = TestClient(create_app())

    # Far more than the (already-low) configured budget of 3.
    responses = [client.get("/api/staff/installer/summary") for _ in range(12)]

    assert all(r.status_code == 401 for r in responses), [r.status_code for r in responses]
    assert all("Retry-After" not in r.headers for r in responses)


def test_missing_header_is_never_blocked_by_a_budget_wrong_tokens_saturated(
    monkeypatch,
) -> None:
    """The saturation pre-check must not treat "no credential offered" as
    "an unmatched guess". Saturate the budget with real wrong-token guesses
    first (429), then confirm a plain signed-out request -- no Authorization
    header at all -- still gets an ordinary 401, never swept up into the
    429 the wrong-token guesses earned."""

    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT", "1")
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")
    client = TestClient(create_app())

    first_guess = client.get(
        "/api/staff/installer/summary",
        headers={"Authorization": "Bearer wrong-guess"},
    )
    assert first_guess.status_code == 401
    second_guess = client.get(
        "/api/staff/installer/summary",
        headers={"Authorization": "Bearer another-wrong-guess"},
    )
    assert second_guess.status_code == 429  # budget of 1 is now saturated

    signed_out = client.get("/api/staff/installer/summary")
    assert signed_out.status_code == 401
    assert "Retry-After" not in signed_out.headers


def test_present_but_wrong_token_still_counts_toward_the_budget(monkeypatch) -> None:
    """The other half of finding #1: relaxing the missing-credential case
    must not accidentally relax real brute-force protection. A handful of
    ordinary credential-free page loads interleaved with wrong-token guesses
    must still let the wrong guesses alone saturate the budget."""

    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT", "2")
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")
    client = TestClient(create_app())

    assert client.get("/api/staff/installer/summary").status_code == 401  # no header
    assert (
        client.get(
            "/api/staff/installer/summary",
            headers={"Authorization": "Bearer wrong-1"},
        ).status_code
        == 401
    )
    assert client.get("/api/staff/installer/summary").status_code == 401  # no header
    assert (
        client.get(
            "/api/staff/installer/summary",
            headers={"Authorization": "Bearer wrong-2"},
        ).status_code
        == 401
    )
    # Two real wrong guesses have now spent the budget of 2, regardless of
    # how many credential-free requests were interleaved between them.
    limited = client.get(
        "/api/staff/installer/summary",
        headers={"Authorization": "Bearer wrong-3"},
    )
    assert limited.status_code == 429


def test_setup_login_correct_password_survives_a_saturated_budget(monkeypatch, tmp_path) -> None:
    """Day-one-lockout audit finding #4: PR #67's setup-rate-limit accounting
    called limiter.saturated() unconditionally before the handler ever saw
    the password, so a saturated budget rejected the CORRECT password too --
    unlike the staff-auth pattern's token_matches_exactly bypass it claimed
    parity with. The correct password must always get through, exactly the
    way an exact staff bearer-token match does."""

    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT", "2")
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")
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

    # Saturate the 2-guess budget with wrong passwords.
    for _ in range(2):
        wrong = client.post(
            "/api/setup/login",
            json={"admin_username": "avery", "admin_password": "not it"},
        )
        assert wrong.status_code == 401

    # A THIRD wrong guess, while saturated, still gets 429 -- the bypass
    # must not have opened the gate for everyone, only for the right one.
    still_wrong = client.post(
        "/api/setup/login",
        json={"admin_username": "avery", "admin_password": "still not it"},
    )
    assert still_wrong.status_code == 429

    # The correct password, submitted while the budget is saturated, must
    # succeed anyway.
    right = client.post(
        "/api/setup/login",
        json={"admin_username": "avery", "admin_password": "correct horse battery staple"},
    )
    assert right.status_code == 200


def test_setup_recover_correct_code_survives_a_saturated_budget(monkeypatch, tmp_path) -> None:
    """Same audit finding #4, for /api/setup/recover: a real recovery code
    must succeed even after wrong-code guesses saturated that route's own
    budget (/login and /recover have independent budgets per
    _setup_rate_limit_key, so each is reachable with zero credentials by
    anyone on the box and each needed its own bypass)."""

    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT", "2")
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")
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
    recovery_code = setup.json()["recovery_kit"]["recovery_codes"][0]

    # Saturate the 2-guess /recover budget with bogus codes.
    for _ in range(2):
        wrong = client.post(
            "/api/setup/recover",
            json={
                "admin_username": "avery",
                "recovery_code": "not-a-real-code",
                "new_admin_password": "irrelevant password here",
            },
        )
        assert wrong.status_code == 401

    # The real, still-unused recovery code must succeed anyway.
    recovered = client.post(
        "/api/setup/recover",
        json={
            "admin_username": "avery",
            "recovery_code": recovery_code,
            "new_admin_password": "fresh horse battery staple",
        },
    )
    assert recovered.status_code == 200

    # The bypass peek must not have consumed the one-time code itself --
    # only the real, saving call should. Confirm the new password actually
    # took effect and the account is not left in a half-recovered state.
    login = client.post(
        "/api/setup/login",
        json={"admin_username": "avery", "admin_password": "fresh horse battery staple"},
    )
    assert login.status_code == 200


def test_setup_login_wrong_password_body_does_not_bypass_saturation(monkeypatch, tmp_path) -> None:
    """The bypass peek must only ever open the gate for the credential that
    is ACTUALLY correct -- an unparseable or merely well-formed-but-wrong
    body must fall through to the ordinary saturated-budget 429."""

    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT", "1")
    monkeypatch.setenv("CIVICCAST_AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")
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

    wrong = client.post(
        "/api/setup/login",
        json={"admin_username": "avery", "admin_password": "nope"},
    )
    assert wrong.status_code == 401  # budget of 1 now saturated

    still_wrong = client.post(
        "/api/setup/login",
        json={"admin_username": "avery", "admin_password": "still nope"},
    )
    assert still_wrong.status_code == 429


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
