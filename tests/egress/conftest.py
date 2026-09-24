# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Shared egress-test fixtures (opt-in only).

Same contract as ``tests/captions/conftest.py``: ``civiccast.auth.tokens.
_configured_tokens`` resolves the documented deterministic fixture token
(``operator-token-a``) ONLY when ``CIVICCAST_STAFF_TOKENS`` is unset. A
configured deployment list -- or an ambient value in a developer shell -- takes
precedence and the fixture token is rejected with a real 401.

Nothing here is autouse; a module must request ``deterministic_staff_token``
explicitly.
"""

from __future__ import annotations

import os

import pytest

_SHADOWING_ENV = (
    "CIVICCAST_STAFF_TOKENS",
    "CIVICCAST_STAFF_TOKENS_FALLBACK_WITH_DB",
)


@pytest.fixture
def deterministic_staff_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the documented fixture token the effective staff identity."""

    for name in _SHADOWING_ENV:
        monkeypatch.delenv(name, raising=False)
    if os.environ.get("CIVICCAST_ALLOW_DETERMINISTIC_STAFF_TOKEN") != "1":
        monkeypatch.setenv("CIVICCAST_ALLOW_DETERMINISTIC_STAFF_TOKEN", "1")
