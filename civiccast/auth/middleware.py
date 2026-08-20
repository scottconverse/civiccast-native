# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""FastAPI middleware for first-party staff bearer authentication."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, Response, status
from starlette.responses import JSONResponse

from civiccast.auth.rate_limit import (
    AuthRateLimiter,
    auth_rate_limit_config,
    client_ip,
)
from civiccast.auth.tokens import (
    StaffAuthError,
    token_matches_exactly,
    verify_bearer_token,
)


async def staff_auth_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Authenticate every /api/staff/* request and attach operator identity.

    Failed verifications are rate-limited per client IP (audit item #27):
    without this, /api/staff/* is an unthrottled bearer-token oracle. Only
    FAILURES count -- valid requests are never recorded against the limit, so
    a noisy client sharing the operator's proxy/NAT cannot deny access. The
    key is the client IP alone, NOT ip+token-prefix: per-prefix buckets hand a
    token-rotating brute-forcer a fresh budget per guess. Once saturated,
    exact full-token matches bypass the unknown-token budget. Exact misses
    receive 429 plus Retry-After without expensive verification or a queue in
    front of a valid operator.
    State is process-local, so ingress controls remain required for distributed
    or multi-worker lookup and request load.
    """

    syncer = getattr(request.app.state, "sync_durable_storage", None)
    if callable(syncer):
        syncer()
    if not request.url.path.startswith("/api/staff/"):
        return await call_next(request)

    limiter = getattr(request.app.state, "auth_rate_limiter", None)
    limit, window_seconds = auth_rate_limit_config()
    key = f"staff-auth-fail:{client_ip(request)}"
    token_store = getattr(request.app.state, "staff_token_store", None)
    if (
        isinstance(limiter, AuthRateLimiter)
        and limiter.saturated(key, limit=limit, window_seconds=window_seconds)
        and not token_matches_exactly(
            request.headers.get("Authorization"),
            token_store=token_store,
        )
    ):
        return _staff_rate_limited_response(
            limiter,
            key=key,
            window_seconds=window_seconds,
        )
    try:
        request.state.operator_identity = verify_bearer_token(
            request.headers.get("Authorization"),
            token_store=token_store,
        )
    except StaffAuthError as exc:
        if isinstance(limiter, AuthRateLimiter) and not limiter.allow(
            key, limit=limit, window_seconds=window_seconds
        ):
            return _staff_rate_limited_response(
                limiter,
                key=key,
                window_seconds=window_seconds,
            )
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": str(exc)},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await call_next(request)


def _staff_rate_limited_response(
    limiter: AuthRateLimiter,
    *,
    key: str,
    window_seconds: int,
) -> JSONResponse:
    retry_after = limiter.retry_after_seconds(key, window_seconds=window_seconds)
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": "Too many failed staff authentication attempts. Wait and retry."},
        headers={"Retry-After": str(retry_after)},
    )
