# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Staff authentication and identity routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from civiccast.auth.models import OperatorIdentity, StaffIdentityResponse, StaffSignOutResponse
from civiccast.auth.roles import roles_for_identity
from civiccast.auth.store import StaffTokenLifecycleError
from civiccast.installer.station_state import StationAuthError, revoke_operator_session

staff_router = APIRouter(prefix="/api/staff/auth", tags=["staff-auth"])

_SIGN_OUT_NEXT_STEP = "Sign in again from First Setup when you need the console."


def _current_identity(request: Request) -> OperatorIdentity:
    identity = request.state.operator_identity
    if not isinstance(identity, OperatorIdentity):
        raise TypeError("Staff auth middleware did not attach an OperatorIdentity.")
    return identity


def _caller_bearer_token(request: Request) -> str:
    """Return the raw bearer token this already-authenticated request carried.

    ``staff_auth_middleware`` has already verified this header for every
    ``/api/staff/*`` request before any route handler runs; this re-parses
    the same header the same way and never performs its own verification.
    Mirrors ``civiccast.installer.router._caller_bearer_token``.
    """

    authorization = request.headers.get("Authorization")
    if not authorization:  # pragma: no cover - staff_auth_middleware already rejects this
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header. Use Bearer <staff-token>.",
        )
    scheme, sep, token = authorization.partition(" ")
    if not sep or scheme.lower() != "bearer" or not token.strip():
        # pragma: no cover - staff_auth_middleware already rejects this
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header. Use Bearer <staff-token>.",
        )
    return token.strip()


@staff_router.get(
    "/me",
    response_model=StaffIdentityResponse,
    summary="Return the verified staff identity and product roles",
)
def get_staff_identity(request: Request) -> StaffIdentityResponse:
    identity = _current_identity(request)
    return StaffIdentityResponse(
        operator_id=identity.operator_id,
        operator_display_name=identity.operator_display_name,
        token_id=identity.token_id,
        scopes=identity.scopes,
        roles=tuple(sorted(roles_for_identity(identity))),
    )


@staff_router.post(
    "/sign-out",
    response_model=StaffSignOutResponse,
    summary="Sign out this browser's own staff session, leaving every other session signed in",
)
def sign_out_staff_session(request: Request) -> StaffSignOutResponse:
    """End exactly the session that is calling.

    2026-09-09 beta.5 clean-machine walkthrough: the operator console had no
    sign-out control at all. The complement of the Station Profile "Sign out
    other sessions" action (``POST /api/staff/installer/sessions/revoke-
    others``): that one keeps the caller and revokes the rest; this one
    revokes the caller and keeps the rest. Any role may call it -- ending
    your own session is never privileged.

    Three kinds of staff token can reach here, and each ends differently:

    * a station operator-console token (first-admin login/recovery) -- its
      entry is removed from ``operator_console.tokens``;
    * a lifecycle-store token (``app.state.staff_token_store``) -- revoked
      through the store, which also writes the audit event;
    * an env-configured ``CIVICCAST_STAFF_TOKENS`` token -- has no
      server-side revocation record, so the response says
      ``session_revoked=false`` and the browser simply forgets it.
    """

    identity = _current_identity(request)
    token = _caller_bearer_token(request)
    try:
        revoke_operator_session(token)
    except StationAuthError:
        pass
    else:
        return StaffSignOutResponse(
            status="signed_out",
            session_revoked=True,
            message="Signed out. Every other signed-in browser or device stays signed in.",
            next_step=_SIGN_OUT_NEXT_STEP,
        )

    token_store = getattr(request.app.state, "staff_token_store", None)
    token_id = identity.token_id
    # StaffTokenStore is a non-runtime-checkable Protocol; duck-type it the
    # way the middleware does.
    if (
        token_store is not None
        and hasattr(token_store, "revoke_token")
        and token_id
        and not token_id.startswith("env-")
    ):
        try:
            token_store.revoke_token(token_id, reason="operator sign-out")
        except StaffTokenLifecycleError:
            pass
        else:
            return StaffSignOutResponse(
                status="signed_out",
                session_revoked=True,
                message="Signed out. This staff token has been revoked.",
                next_step=_SIGN_OUT_NEXT_STEP,
            )

    return StaffSignOutResponse(
        status="signed_out",
        session_revoked=False,
        message=(
            "Signed out of this browser. This staff token is configured by the station "
            "environment and cannot be revoked here; rotate CIVICCAST_STAFF_TOKENS to retire it."
        ),
        next_step=_SIGN_OUT_NEXT_STEP,
    )
