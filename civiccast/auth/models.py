# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Auth data contracts for staff-route identity binding."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

OperatorRole = Literal[
    "setup_admin",
    "meeting_operator",
    "records_clerk",
    "publish_operator",
    "support_admin",
]


class OperatorIdentity(BaseModel):
    """Server-verified operator identity attached to staff requests."""

    model_config = ConfigDict(extra="forbid")

    operator_id: Annotated[str, Field(min_length=1, max_length=160)]
    operator_display_name: Annotated[str, Field(min_length=1, max_length=200)]
    token_id: str | None = None
    scopes: tuple[str, ...] = Field(default_factory=tuple)


class StaffIdentityResponse(BaseModel):
    """Staff identity and v1.4 product roles returned to the operator console."""

    model_config = ConfigDict(extra="forbid")

    operator_id: Annotated[str, Field(min_length=1, max_length=160)]
    operator_display_name: Annotated[str, Field(min_length=1, max_length=200)]
    token_id: str | None = None
    scopes: tuple[str, ...] = Field(default_factory=tuple)
    roles: tuple[OperatorRole, ...] = Field(default_factory=tuple)
