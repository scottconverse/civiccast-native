# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Normalized model validation (plan §5)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from civiccast.agenda_import.models import (
    ExternalAgenda,
    ExternalAgendaItem,
    ExternalMeetingSummary,
)


class TestExternalAgendaItem:
    def test_requires_a_non_negative_order(self) -> None:
        with pytest.raises(ValidationError):
            ExternalAgendaItem(order=-1, title="x")

    def test_requires_a_non_empty_title(self) -> None:
        with pytest.raises(ValidationError):
            ExternalAgendaItem(order=0, title="")

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ExternalAgendaItem(order=0, title="x", unexpected="field")  # type: ignore[call-arg]

    def test_doc_url_is_not_scheme_validated_here(self) -> None:
        # Untrusted-input shape -- no allowlist at this layer (plan §10);
        # validation happens once, at the mapper's trust boundary.
        item = ExternalAgendaItem(order=0, title="x", doc_url="javascript:alert(1)")
        assert item.doc_url == "javascript:alert(1)"


class TestExternalAgenda:
    def test_defaults_to_empty_items(self) -> None:
        agenda = ExternalAgenda(external_id="1", title="x")
        assert agenda.items == []
        assert agenda.meeting_datetime is None


class TestExternalMeetingSummary:
    def test_round_trips(self) -> None:
        summary = ExternalMeetingSummary(external_id="1", title="City Council")
        assert summary.meeting_datetime is None
