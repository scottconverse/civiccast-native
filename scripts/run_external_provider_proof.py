#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Preflight seams for v1.1 external provider release proof."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from civiccast.publish.providers import check_provider_credentials


@dataclass(frozen=True)
class ExternalProofPreflightResult:
    """Typed STOP or success result for external provider proof."""

    status: str
    operator_action: str
    uses_real_providers: bool


def preflight_external_provider_proof(
    env: Mapping[str, str],
) -> ExternalProofPreflightResult:
    """Return a typed STOP when any required provider access value is absent."""

    checks = [
        check_provider_credentials(provider, env=env)
        for provider in ("internet_archive", "youtube", "email", "webhook", "nas")
    ]
    blocked = [check for check in checks if check.status != "ok"]
    if blocked:
        return ExternalProofPreflightResult(
            status=blocked[0].status,
            operator_action=blocked[0].operator_action,
            uses_real_providers=False,
        )
    return ExternalProofPreflightResult(
        status="ok",
        operator_action="External provider proof preflight is ready.",
        uses_real_providers=True,
    )
