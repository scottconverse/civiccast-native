# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the Cloudflare R2 concierge (installer.r2_concierge)."""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from typing import Any

import httpx

from civiccast.installer.r2_concierge import provision_r2

_TOKEN = "tok-value-abc"
_TOKEN_ID = "verify-id-1"
_ACCOUNT_ID = "acct-1"
_BUCKET = "civiccast-media"
_DOMAIN = "pub-0113a9e4549cf9b1ff1bf56e04da0cef.r2.dev"


def _json(payload: dict[str, Any], status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=payload)


def _handler(
    *,
    verify: dict[str, Any] | None = None,
    accounts: dict[str, Any] | None = None,
    bucket: dict[str, Any] | None = None,
    domain: dict[str, Any] | None = None,
    calls: list[str] | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    verify = verify or {"success": True, "result": {"id": _TOKEN_ID, "status": "active"}}
    accounts = accounts or {
        "success": True,
        "result": [{"id": _ACCOUNT_ID, "name": "Test Station"}],
    }
    bucket = bucket or {"success": True, "result": {"name": _BUCKET}}
    domain = domain or {
        "success": True,
        "result": {"domain": _DOMAIN, "enabled": True, "bucketId": "x"},
    }

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if calls is not None:
            calls.append(f"{request.method} {path}")
        if path.endswith("/user/tokens/verify"):
            return _json(verify)
        if path.endswith("/accounts"):
            return _json(accounts)
        if path.endswith("/domains/managed"):
            return _json(domain)
        if path.endswith("/r2/buckets"):
            return _json(bucket)
        raise AssertionError(f"unexpected request: {request.method} {path}")

    return handle


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_happy_path_provisions_bucket_and_derives_credentials() -> None:
    with _client(_handler()) as http:
        result = provision_r2(_TOKEN, bucket_name=_BUCKET, http=http)

    assert result.status == "success"
    assert result.account_id == _ACCOUNT_ID
    assert result.bucket == _BUCKET
    assert result.public_base_url == f"https://{_DOMAIN}"
    assert result.credential_fields == {
        "account_id": _ACCOUNT_ID,
        "access_key_id": _TOKEN_ID,
        "secret_access_key": sha256(_TOKEN.encode("utf-8")).hexdigest(),
        "bucket": _BUCKET,
        "public_base_url": f"https://{_DOMAIN}",
    }


def test_keypair_derivation_vector() -> None:
    # access_key_id = the token's own id; secret_access_key = sha256(token).hexdigest().
    with _client(
        _handler(verify={"success": True, "result": {"id": "the-id", "status": "active"}})
    ) as http:
        result = provision_r2("abc", bucket_name=_BUCKET, http=http)

    assert result.credential_fields["access_key_id"] == "the-id"
    assert result.credential_fields["secret_access_key"] == sha256(b"abc").hexdigest()


def test_invalid_token_is_reported_distinctly() -> None:
    with _client(
        _handler(verify={"success": False, "errors": [{"code": 1000, "message": "Invalid token"}]})
    ) as http:
        result = provision_r2("bad-token", bucket_name=_BUCKET, http=http)

    assert result.status == "error"
    assert result.error_code == "invalid_token"


def test_r2_not_enabled_carries_the_dashboard_deep_link() -> None:
    bucket_error = {
        "success": False,
        "errors": [
            {"code": 10042, "message": "Please enable R2 through the Cloudflare Dashboard."}
        ],
    }
    with _client(_handler(bucket=bucket_error)) as http:
        result = provision_r2(_TOKEN, bucket_name=_BUCKET, http=http)

    assert result.status == "error"
    assert result.error_code == "r2_not_enabled"
    assert result.deep_link == "https://dash.cloudflare.com/?to=/:account/r2"


def test_multiple_accounts_without_explicit_account_id_is_an_error() -> None:
    two_accounts = {
        "success": True,
        "result": [{"id": "a1", "name": "One"}, {"id": "a2", "name": "Two"}],
    }
    with _client(_handler(accounts=two_accounts)) as http:
        result = provision_r2(_TOKEN, bucket_name=_BUCKET, http=http)

    assert result.status == "error"
    assert result.error_code == "no_account"


def test_zero_accounts_is_an_error() -> None:
    with _client(_handler(accounts={"success": True, "result": []})) as http:
        result = provision_r2(_TOKEN, bucket_name=_BUCKET, http=http)

    assert result.status == "error"
    assert result.error_code == "no_account"


def test_explicit_account_id_skips_account_listing() -> None:
    calls: list[str] = []
    with _client(_handler(calls=calls)) as http:
        result = provision_r2(_TOKEN, bucket_name=_BUCKET, http=http, account_id="explicit-acct")

    assert result.status == "success"
    assert result.account_id == "explicit-acct"
    assert not any(call.endswith("/accounts") for call in calls)


def test_bucket_already_exists_is_treated_as_idempotent_success() -> None:
    already_exists = {
        "success": False,
        "errors": [{"code": 10004, "message": "A bucket with that name already exists"}],
    }
    with _client(_handler(bucket=already_exists)) as http:
        result = provision_r2(_TOKEN, bucket_name=_BUCKET, http=http)

    assert result.status == "success"
    assert result.bucket == _BUCKET


def test_other_bucket_errors_are_reported() -> None:
    other_error = {
        "success": False,
        "errors": [{"code": 9999, "message": "Something else went wrong"}],
    }
    with _client(_handler(bucket=other_error)) as http:
        result = provision_r2(_TOKEN, bucket_name=_BUCKET, http=http)

    assert result.status == "error"
    assert result.error_code == "bucket_error"


def test_domain_enable_failure_is_reported() -> None:
    with _client(
        _handler(domain={"success": False, "errors": [{"code": 1, "message": "nope"}]})
    ) as http:
        result = provision_r2(_TOKEN, bucket_name=_BUCKET, http=http)

    assert result.status == "error"
    assert result.error_code == "domain_error"


def test_blank_token_is_rejected_without_a_network_call() -> None:
    def handle(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("no network call should happen for a blank token")

    with _client(handle) as http:
        result = provision_r2("   ", bucket_name=_BUCKET, http=http)

    assert result.status == "error"
    assert result.error_code == "invalid_token"


def test_single_account_with_null_id_is_reported_as_no_account() -> None:
    # Cloudflare can return exactly one account whose "id" is explicitly null
    # (e.g. a pending/incomplete account). `.get("id", "")` would let a literal
    # None through as the truthy string "None", bypassing the no_account guard.
    null_id_account = {"success": True, "result": [{"id": None, "name": "Pending"}]}
    with _client(_handler(accounts=null_id_account)) as http:
        result = provision_r2(_TOKEN, bucket_name=_BUCKET, http=http)

    assert result.status == "error"
    assert result.error_code == "no_account"


def test_single_account_entry_that_is_not_a_dict_does_not_crash() -> None:
    # A malformed/non-dict single account entry must be handled like the
    # multi-account branch already handles it, not raise AttributeError.
    malformed = {"success": True, "result": ["not-a-dict"]}
    with _client(_handler(accounts=malformed)) as http:
        result = provision_r2(_TOKEN, bucket_name=_BUCKET, http=http)

    assert result.status == "error"
    assert result.error_code == "no_account"


def test_transient_token_verify_failure_is_not_reported_as_invalid_token() -> None:
    # A 429/5xx from Cloudflare during verify is a retryable condition, not a
    # rejected token -- the operator should not be told to create a new token.
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/user/tokens/verify"):
            return httpx.Response(429, json={"success": False})
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    with _client(handle) as http:
        result = provision_r2(_TOKEN, bucket_name=_BUCKET, http=http)

    assert result.status == "error"
    assert result.error_code == "invalid_token"
    assert "create a new token" not in result.message.lower()
    assert "temporarily" in result.message.lower()


def test_transient_accounts_failure_is_not_reported_as_no_account_scope_message() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/user/tokens/verify"):
            return httpx.Response(
                200, json={"success": True, "result": {"id": _TOKEN_ID, "status": "active"}}
            )
        if path.endswith("/accounts"):
            return httpx.Response(503, json={"success": False})
        raise AssertionError(f"unexpected request: {request.method} {path}")

    with _client(handle) as http:
        result = provision_r2(_TOKEN, bucket_name=_BUCKET, http=http)

    assert result.status == "error"
    assert result.error_code == "no_account"
    assert "temporarily" in result.message.lower()


def test_expired_token_status_is_reported_as_invalid_before_accounts_call() -> None:
    calls: list[str] = []
    expired_verify = {"success": True, "result": {"id": _TOKEN_ID, "status": "expired"}}
    with _client(_handler(verify=expired_verify, calls=calls)) as http:
        result = provision_r2(_TOKEN, bucket_name=_BUCKET, http=http)

    assert result.status == "error"
    assert result.error_code == "invalid_token"
    assert "expired" in result.message.lower()
    assert not any(call.endswith("/accounts") for call in calls)
