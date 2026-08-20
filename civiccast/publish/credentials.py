# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Credential-health abstraction for v0.7 publish targets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Protocol


@dataclass(frozen=True)
class CredentialHealth:
    """Non-secret credential readiness for one publish surface."""

    healthy: bool
    reference: str
    message: str
    next_step: str


class CredentialProvider(Protocol):
    def check_surface(self, surface_id: str) -> CredentialHealth: ...


class DeterministicCredentialProvider:
    """Mock provider shaped like an OS credential-store integration.

    No secrets are stored here. The reference is the key name an operator would
    provision in the OS credential store; tests can override individual
    surfaces by passing ``missing_surface_ids``.
    """

    _KEYS: ClassVar[dict[str, str]] = {
        "internet-archive": "os-keyring://civiccast/internet-archive",
        "local-nas-rsync": "os-keyring://civiccast/local-nas-rsync",
        "local-nas-zfs": "os-keyring://civiccast/local-nas-zfs",
        "youtube-live": "os-keyring://civiccast/youtube-live",
        "youtube-vod": "os-keyring://civiccast/youtube-vod",
    }

    def __init__(self, missing_surface_ids: set[str] | None = None) -> None:
        self._missing_surface_ids = missing_surface_ids or set()

    def check_surface(self, surface_id: str) -> CredentialHealth:
        reference = self._KEYS.get(surface_id, "not-required")
        if surface_id in self._missing_surface_ids:
            return CredentialHealth(
                healthy=False,
                reference=reference,
                message=f"{surface_id} credential is missing from the OS credential store.",
                next_step=f"Add {reference}, then rerun publish preflight.",
            )
        return CredentialHealth(
            healthy=True,
            reference=reference,
            message=f"{surface_id} credential reference is present.",
            next_step="No action required for this credential check.",
        )
