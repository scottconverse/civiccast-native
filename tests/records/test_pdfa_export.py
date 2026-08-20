# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Artifact contract tests for v0.6 PDF/A-3 signed record export."""

from __future__ import annotations

import base64
import json
import re
from io import BytesIO

import pikepdf
import pytest

from civiccast.auth.models import OperatorIdentity
from civiccast.records.exporter import RecordExportError, SignedRecordExporter
from civiccast.records.pdfa import (
    EMBEDDED_FILE_SUBTYPES,
    EXPECTED_EMBEDDED_METADATA_NAMES,
    STANDARD_14_FONT_NAMES,
    VALID_AF_RELATIONSHIPS,
    validate_pdfa3_shape,
)
from civiccast.records.timestamp import DeterministicTimestampAuthority
from civiccast.summary.store import InMemorySummaryStore
from tests.summary.test_summary_persistence import _summary

TEST_OPERATOR = OperatorIdentity(
    operator_id="staff-1",
    operator_display_name="Staff One",
    token_id="token-staff-1",
)


class TestPdfaExport:
    def test_rejects_unapproved_summary_before_rendering(self) -> None:
        summary_store = InMemorySummaryStore()
        summary_store.create_summary(_summary())
        exporter = SignedRecordExporter(
            summary_store=summary_store,
            timestamp_authority=DeterministicTimestampAuthority(),
        )

        with pytest.raises(RecordExportError, match="approved"):
            exporter.export(summary_id="summary-1", operator_identity=TEST_OPERATOR)

    def test_pdfa_record_contains_transcript_summary_metadata_and_timestamp_proof(self) -> None:
        summary = _summary().model_copy(update={"status": "approved"})
        summary_store = InMemorySummaryStore()
        summary_store.create_summary(summary)
        exporter = SignedRecordExporter(
            summary_store=summary_store,
            timestamp_authority=DeterministicTimestampAuthority(),
        )

        record = exporter.export(summary_id="summary-1", operator_identity=TEST_OPERATOR)

        assert record.pdfa.conformance == "PDF/A-3B"
        assert record.pdf_bytes.startswith(b"%PDF-")
        assert "sourced-claims.json" in record.pdfa.embedded_metadata_names
        # timestamp_proof.artifact_digest is the digest of what the timestamp
        # authority actually signed (the pre-token render); artifact_digest is
        # the digest of the final served PDF once the real token is embedded
        # into it, so the two are no longer the same value (see
        # test_embedded_timestamp_token_matches_the_real_stored_proof below).
        assert record.timestamp_proof.artifact_digest != record.artifact_digest
        assert summary.audit_fingerprint in record.audit_fingerprint

        with pikepdf.open(BytesIO(record.pdf_bytes)) as document:
            assert document.Root.Metadata is not None
            assert set(EXPECTED_EMBEDDED_METADATA_NAMES).issubset(document.attachments.keys())
            assert len(document.Root.AF) == len(EXPECTED_EMBEDDED_METADATA_NAMES)
            embedded_file_refs = {
                document.Root.Names.EmbeddedFiles.Names[index].objgen
                for index in range(1, len(document.Root.Names.EmbeddedFiles.Names), 2)
            }
            for file_spec in document.Root.AF:
                assert file_spec.objgen in embedded_file_refs
                assert file_spec.Type == pikepdf.Name.Filespec
                assert file_spec.AFRelationship in VALID_AF_RELATIONSHIPS
            assert document.Root.OutputIntents[0].S == pikepdf.Name.GTS_PDFA1
            assert document.Root.OutputIntents[0].DestOutputProfile is not None
            assert document.pages[0].obj.Resources.ColorSpace.DefaultRGB[0] == pikepdf.Name.ICCBased
            for name in EXPECTED_EMBEDDED_METADATA_NAMES:
                assert document.attachments[name].obj.AFRelationship in VALID_AF_RELATIONSHIPS
            with document.open_metadata() as metadata:
                assert metadata["pdfaid:part"] == "3"
                assert metadata["pdfaid:conformance"] == "B"
                assert metadata["dc:creator"] == ["CivicCast"]
                # PDF/A-3 §6.6.2.3.1 forbids custom XMP properties that are not
                # defined in an extension schema. veraPDF rejected the prior
                # civiccast:* namespace (no extension schema declared) so the
                # renderer now keeps audit data in the structured attachments
                # only — this test guards against the namespace returning.
                with pytest.raises(KeyError):
                    metadata["civiccast:summary_id"]
                uuid_pattern = (
                    r"^uuid:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
                )
                assert re.match(uuid_pattern, metadata["xmpMM:DocumentID"])
                assert re.match(uuid_pattern, metadata["xmpMM:InstanceID"])
            assert b"civiccast:" not in document.Root.Metadata.read_bytes()
            content = document.pages[0].Contents.read_bytes()
            assert b" rg" not in content
            assert b" RG" not in content
            for page in document.pages:
                font_resources = page.obj.Resources.Font
                base_fonts = {str(font.BaseFont).lstrip("/") for font in font_resources.values()}
                assert not (base_fonts & STANDARD_14_FONT_NAMES)

    def test_embedded_timestamp_token_matches_the_real_stored_proof(self) -> None:
        """The archived PDF's own timestamp-token.der attachment must be the
        real token recorded in timestamp_proof, not a hardcoded placeholder
        string that looks like one but isn't."""
        summary = _summary().model_copy(
            update={"summary_id": "summary-token-check", "status": "approved"}
        )
        summary_store = InMemorySummaryStore()
        summary_store.create_summary(summary)
        exporter = SignedRecordExporter(
            summary_store=summary_store,
            timestamp_authority=DeterministicTimestampAuthority(),
        )

        record = exporter.export(summary_id="summary-token-check", operator_identity=TEST_OPERATOR)

        with pikepdf.open(BytesIO(record.pdf_bytes)) as document:
            embedded_token = document.attachments["timestamp-token.der"].get_file().read_bytes()
        assert embedded_token != b"CivicCast timestamp token placeholder"
        assert embedded_token == base64.b64decode(record.timestamp_proof.token_der_b64)


class TestPdfaConformanceStructure:
    """Local checks for the PDF fields that veraPDF rejected in Phase 1.

    These tests are a regression net for the exact saved-byte defects reported
    by veraPDF run 25971878411. They do not replace veraPDF as the conformance
    authority.
    """

    @staticmethod
    def _approved_pdf_bytes() -> bytes:
        summary = _summary().model_copy(
            update={"summary_id": "summary-conformance", "status": "approved"}
        )
        store = InMemorySummaryStore()
        store.create_summary(summary)
        exporter = SignedRecordExporter(
            summary_store=store,
            timestamp_authority=DeterministicTimestampAuthority(),
        )
        return exporter.export(
            summary_id="summary-conformance",
            operator_identity=TEST_OPERATOR,
        ).pdf_bytes

    def test_validate_pdfa3_shape_returns_all_pass_messages(self) -> None:
        results = validate_pdfa3_shape(self._approved_pdf_bytes())
        failures = [line for line in results if line.startswith("FAIL")]
        assert not failures, "validate_pdfa3_shape reported failures: " + "; ".join(failures)
        assert all(line.startswith("PASS") for line in results)

    def test_every_embedded_file_stream_has_conformant_subtype(self) -> None:
        with pikepdf.open(BytesIO(self._approved_pdf_bytes())) as document:
            names_tree = document.Root.Names.EmbeddedFiles.Names
            seen_pairs: list[tuple[str, str, str]] = []
            for index in range(0, len(names_tree), 2):
                spec_name = str(names_tree[index])
                spec = names_tree[index + 1]
                ef = spec.get("/EF")
                assert ef is not None, f"{spec_name}: file spec missing /EF"
                ef_keys = list(ef.keys())
                assert ef_keys, f"{spec_name}: /EF dictionary is empty"
                for ef_key in ef_keys:
                    subtype = ef[ef_key].get("/Subtype")
                    assert subtype is not None, (
                        f"{spec_name}/EF{ef_key}: missing /Subtype (ISO 19005-3:2012 §6.8 test 1)"
                    )
                    subtype_str = str(subtype)
                    assert re.match(r"^/[-\w+.]+/[-\w+.]+$", subtype_str), (
                        f"{spec_name}/EF{ef_key}: /Subtype not MIME-shaped: {subtype_str}"
                    )
                    seen_pairs.append((spec_name, str(ef_key), subtype_str))
            for spec_name, expected in EMBEDDED_FILE_SUBTYPES.items():
                expected_str = str(expected)
                matching = [s for (name, _, s) in seen_pairs if name == spec_name]
                assert matching, f"{spec_name}: no EF stream observed"
                assert all(s == expected_str for s in matching), (
                    f"{spec_name}: expected Subtype {expected_str}, got {matching}"
                )

    def test_destoutputprofile_is_mntr_or_prtr_rgb_under_v5(self) -> None:
        with pikepdf.open(BytesIO(self._approved_pdf_bytes())) as document:
            icc_bytes = document.Root.OutputIntents[0]["/DestOutputProfile"].read_bytes()
        assert len(icc_bytes) >= 128, "ICC profile shorter than 128-byte header"
        device_class = icc_bytes[12:16]
        color_space = icc_bytes[16:20]
        version_major = icc_bytes[8]
        assert device_class in (b"mntr", b"prtr"), (
            f"ISO 19005-3:2012 §6.2.3 test 1: Device Class must be mntr or prtr, got "
            f"{device_class!r}"
        )
        assert color_space in (b"RGB ", b"CMYK", b"GRAY"), (
            f"ISO 19005-3:2012 §6.2.3 test 1: color space must be RGB/CMYK/GRAY, got "
            f"{color_space!r}"
        )
        assert version_major < 5, (
            f"ISO 19005-3:2012 §6.2.3 test 1: ICC version must be <5, got {version_major}"
        )

    def test_xmp_packet_has_no_undeclared_custom_namespace(self) -> None:
        with pikepdf.open(BytesIO(self._approved_pdf_bytes())) as document:
            xmp_bytes = document.Root.Metadata.read_bytes()
        xmp_text = xmp_bytes.decode("utf-8", errors="replace")
        assert "civiccast:" not in xmp_text, (
            "ISO 19005-3:2012 §6.6.2.3.1 tests 1 and 2: civiccast: namespace is not "
            "defined in any PDF/A extension schema; veraPDF rejects every property "
            "in this namespace. The audit data must live in attachments only."
        )

    def test_xmp_document_id_and_instance_id_are_uuid_uris(self) -> None:
        pattern = re.compile(r"^uuid:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
        with (
            pikepdf.open(BytesIO(self._approved_pdf_bytes())) as document,
            document.open_metadata() as xmp,
        ):
            assert pattern.match(str(xmp["xmpMM:DocumentID"])), (
                f"xmpMM:DocumentID not a uuid: URI: {xmp['xmpMM:DocumentID']}"
            )
            assert pattern.match(str(xmp["xmpMM:InstanceID"])), (
                f"xmpMM:InstanceID not a uuid: URI: {xmp['xmpMM:InstanceID']}"
            )

    def test_page_content_streams_emit_no_device_rgb_operators(self) -> None:
        with pikepdf.open(BytesIO(self._approved_pdf_bytes())) as document:
            for page_index, page in enumerate(document.pages):
                contents = page.obj.get("/Contents")
                if isinstance(contents, pikepdf.Array):
                    payload = b"".join(stream.read_bytes() for stream in contents)
                else:
                    payload = contents.read_bytes()
                assert b" rg" not in payload and not payload.startswith(b"rg "), (
                    f"page {page_index}: content stream emits device-RGB fill 'rg' "
                    "(ISO 19005-3:2012 §6.2.3 — would require an active default "
                    "color space resolution)"
                )
                assert b" RG" not in payload and not payload.startswith(b"RG "), (
                    f"page {page_index}: content stream emits device-RGB stroke 'RG'"
                )

    def test_audit_data_remains_recoverable_from_attachments(self) -> None:
        """Removing civiccast:* XMP must not regress audit-data availability."""
        with pikepdf.open(BytesIO(self._approved_pdf_bytes())) as document:
            attachments = document.attachments
            sourced = json.loads(attachments["sourced-claims.json"].get_file().read_bytes())
            provenance = json.loads(attachments["provenance.json"].get_file().read_bytes())
            approval_blob = attachments["approval.json"].get_file().read_bytes()
            assert isinstance(sourced, list)
            assert sourced, "sourced-claims.json attachment is empty"
            assert "extraction_version" in provenance
            # approval.json carries JSON 'null' when no operator approval was
            # attached and a JSON object otherwise; either form satisfies the
            # contract that the attachment is present and parseable.
            approval = json.loads(approval_blob)
            assert approval is None or isinstance(approval, dict)
