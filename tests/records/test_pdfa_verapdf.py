# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""veraPDF release-bar tests for signed-record PDF/A-3B exports."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from civiccast.auth.models import OperatorIdentity
from civiccast.records.exporter import SignedRecordExporter
from civiccast.records.timestamp import DeterministicTimestampAuthority
from civiccast.summary.models import OperatorApproval
from civiccast.summary.store import InMemorySummaryStore
from tests.summary.test_summary_persistence import _summary


def _approved_store(summary_id: str) -> InMemorySummaryStore:
    store = InMemorySummaryStore()
    summary = _summary().model_copy(
        update={
            "summary_id": summary_id,
            "meeting_id": f"{summary_id}-meeting",
            "status": "approved",
        }
    )
    store.create_summary(summary)
    store.approve_summary(
        OperatorApproval(
            summary_id=summary_id,
            operator_id="operator-token-a",
            operator_display_name="Avery Operator",
            approved_at=datetime(2026, 5, 16, 12, 0, tzinfo=UTC),
            approval_note="Checked against sourced transcript claims.",
        )
    )
    return store


def _export_pdf_bytes(summary_id: str) -> bytes:
    exporter = SignedRecordExporter(
        summary_store=_approved_store(summary_id),
        timestamp_authority=DeterministicTimestampAuthority(),
    )
    return exporter.export(
        summary_id=summary_id,
        operator_identity=OperatorIdentity(
            operator_id="operator-token-a",
            operator_display_name="Avery Operator",
            token_id="token-a",
        ),
    ).pdf_bytes


def test_verapdf_validates_three_pdfa3b_exports_including_sourced_claim_attachment() -> None:
    exports = {
        "baseline": _export_pdf_bytes("summary-verapdf-baseline"),
        "agenda": _export_pdf_bytes("summary-verapdf-agenda"),
        "with-sourced-claims": _export_pdf_bytes("summary-verapdf-sourced-claims"),
    }
    assert b"sourced-claims.json" in exports["with-sourced-claims"]

    import civiccast.records.pdfa as pdfa

    validator: Any = getattr(pdfa, "validate_pdfa3b_with_verapdf", None)
    assert callable(validator), (
        "civiccast.records.pdfa must expose validate_pdfa3b_with_verapdf(pdf_bytes) "
        "and call the pinned veraPDF 1.28.2 wrapper instead of marker-only validation."
    )

    failures = []
    for name, pdf_bytes in exports.items():
        result = validator(pdf_bytes)
        if not result.valid:
            failures.append(f"{name}: {result.message}")

    assert not failures, "veraPDF rejected generated PDF/A-3B exports: " + "; ".join(failures)
