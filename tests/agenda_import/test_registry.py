# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""build_source() -- all three vendors resolve (plan §8 task 5).

``civicclerk`` moved from "raises AgendaSourceNotAvailableError" (Phases 1-2)
to "resolves to a working adapter" in Phase 3 -- the placeholder assertion is
replaced, not weakened: a genuinely-unknown source name still raises
:class:`AgendaSourceNotAvailableError`, proven by the parametrized test
below."""

from __future__ import annotations

import pytest

from civiccast.agenda_import.base import AgendaSourceNotAvailableError
from civiccast.agenda_import.civicclerk import CivicClerkSource
from civiccast.agenda_import.legistar import LegistarSource
from civiccast.agenda_import.primegov import PrimeGovSource
from civiccast.agenda_import.registry import build_source


def test_legistar_resolves_to_a_working_adapter() -> None:
    source = build_source("legistar", timeout_seconds=10.0, token=None)
    assert isinstance(source, LegistarSource)


def test_primegov_resolves_to_a_working_adapter_and_ignores_token() -> None:
    source = build_source("primegov", timeout_seconds=10.0, token="ignored-not-used")
    assert isinstance(source, PrimeGovSource)


def test_civicclerk_resolves_to_a_working_adapter_and_ignores_token() -> None:
    source = build_source("civicclerk", timeout_seconds=10.0, token="ignored-not-used")
    assert isinstance(source, CivicClerkSource)


@pytest.mark.parametrize("name", ["bogus-vendor", "legistar2", ""])
def test_unimplemented_sources_raise_not_available(name: str) -> None:
    with pytest.raises(AgendaSourceNotAvailableError):
        build_source(name, timeout_seconds=10.0, token=None)
