# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Env-driven config for agenda import (plan §7).

Follows the same ``Settings.from_env()`` shape as
:class:`civiccast.subscribe.webhook.WebhookSettings`: a frozen dataclass,
validated eagerly, no network/DB access. ``CIVICCAST_AGENDA_SOURCE=off`` is
the default (matches the repo's ``CIVICCAST_PROVIDER_<NAME>=real|mock``
convention in spirit, plan §4) — a stock install ships with agenda import
disabled and needs no credentials.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from civiccast.agenda_import.models import AGENDA_SOURCE_NAMES

# A vendor tenant identifier (PrimeGov subdomain, CivicClerk siteid). It is
# interpolated straight into the request host, e.g.
# ``f"https://{client_code}.primegov.com"`` (primegov.py / civicclerk.py), so
# anything other than a bare token can redirect the backend's outbound HTTP to
# an attacker-chosen host (SSRF) -- e.g. ``169.254.169.254/latest/meta-data/#``
# parses to host=169.254.169.254 with ``.primegov.com`` shoved into the URL
# fragment. Allow only the tenant-token shape the adapters' own docstrings
# describe: letters, digits, hyphen, underscore.
_CLIENT_CODE_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


def validate_client_code(value: str) -> str:
    """Return ``value`` if it is a safe vendor tenant token, else raise.

    Applied at the staff-facing trust boundary (the agenda-import router) so a
    malformed or hostile ``client_code`` is rejected with a 422 before it ever
    reaches an outbound URL. See :data:`_CLIENT_CODE_RE`.
    """
    if _CLIENT_CODE_RE.fullmatch(value) is None:
        raise ValueError(
            "client_code must be 1-64 characters of letters, digits, hyphen, "
            "or underscore (a bare vendor tenant siteid/subdomain)."
        )
    return value


_ENV_SOURCE = "CIVICCAST_AGENDA_SOURCE"
_ENV_CLIENT = "CIVICCAST_AGENDA_SOURCE_CLIENT"
_ENV_TOKEN = "CIVICCAST_AGENDA_SOURCE_TOKEN"  # noqa: S105 - env var name, not a secret
_ENV_TIMEOUT = "CIVICCAST_AGENDA_SOURCE_TIMEOUT_S"

_OFF = "off"
_VALID_SOURCES: tuple[str, ...] = (_OFF, *AGENDA_SOURCE_NAMES)


@dataclass(frozen=True)
class AgendaImportSettings:
    """Resolved agenda-import config. ``enabled`` is ``source != "off"``."""

    source: str = _OFF
    client_code: str | None = None
    token: str | None = None
    timeout_seconds: float = 10.0

    @property
    def enabled(self) -> bool:
        return self.source != _OFF

    @classmethod
    def from_env(cls) -> AgendaImportSettings:
        source = (os.environ.get(_ENV_SOURCE) or _OFF).strip().lower()
        if source not in _VALID_SOURCES:
            raise ValueError(
                f"{_ENV_SOURCE} must be one of {', '.join(_VALID_SOURCES)}; got {source!r}."
            )
        client_code = os.environ.get(_ENV_CLIENT, "").strip() or None
        if client_code is not None:
            # Defense in depth: even though this env value is operator-set (not
            # attacker-reachable) and currently unused, validate it to the same
            # safe-tenant-token shape as the router boundary, so a future caller
            # that wires it into a request URL cannot reintroduce the SSRF gap.
            client_code = validate_client_code(client_code)
        token = os.environ.get(_ENV_TOKEN, "").strip() or None
        raw_timeout = os.environ.get(_ENV_TIMEOUT, "").strip()
        timeout_seconds = 10.0
        if raw_timeout:
            try:
                timeout_seconds = float(raw_timeout)
            except ValueError as exc:
                raise ValueError(f"{_ENV_TIMEOUT} must be a number; got {raw_timeout!r}.") from exc
            if timeout_seconds <= 0:
                raise ValueError(f"{_ENV_TIMEOUT} must be positive; got {raw_timeout!r}.")
        return cls(
            source=source,
            client_code=client_code,
            token=token,
            timeout_seconds=timeout_seconds,
        )


__all__ = ["AgendaImportSettings"]
