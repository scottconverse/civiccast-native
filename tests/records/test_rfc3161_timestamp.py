# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Deterministic RFC 3161 timestamp contract tests for signed records."""

from __future__ import annotations

import pytest

from civiccast.records.timestamp import (
    DeterministicTimestampAuthority,
    TimestampVerificationError,
    verify_timestamp_proof,
)


class TestRfc3161Timestamp:
    def test_fixture_timestamp_binds_payload_digest_nonce_and_time(self) -> None:
        authority = DeterministicTimestampAuthority(
            nonce="fixture-nonce",
            timestamp_iso="2026-05-14T12:00:00+00:00",
        )

        proof = authority.timestamp(b"approved summary pdf bytes")

        assert proof.algorithm == "sha256"
        assert proof.nonce == "fixture-nonce"
        assert proof.timestamped_at.isoformat() == "2026-05-14T12:00:00+00:00"
        assert verify_timestamp_proof(b"approved summary pdf bytes", proof) is True

    def test_tampered_payload_fails_verification(self) -> None:
        authority = DeterministicTimestampAuthority()
        proof = authority.timestamp(b"original pdf bytes")

        with pytest.raises(TimestampVerificationError, match="digest"):
            verify_timestamp_proof(b"tampered pdf bytes", proof)
