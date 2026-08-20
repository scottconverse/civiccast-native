# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Staff authentication and identity routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

from civiccast.auth.models import OperatorIdentity, StaffIdentityResponse
from civiccast.auth.roles import roles_for_identity

staff_router = APIRouter(prefix="/api/staff/auth", tags=["staff-auth"])


@staff_router.get(
    "/me",
    response_model=StaffIdentityResponse,
    summary="Return the verified staff identity and product roles",
)
def get_staff_identity(request: Request) -> StaffIdentityResponse:
    identity = request.state.operator_identity
    if not isinstance(identity, OperatorIdentity):
        raise TypeError("Staff auth middleware did not attach an OperatorIdentity.")
    return StaffIdentityResponse(
        operator_id=identity.operator_id,
        operator_display_name=identity.operator_display_name,
        token_id=identity.token_id,
        scopes=identity.scopes,
        roles=tuple(sorted(roles_for_identity(identity))),
    )
