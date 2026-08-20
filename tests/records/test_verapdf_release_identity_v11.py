# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for tying veraPDF proof to v1.1 release artifact identity."""

from __future__ import annotations

import hashlib
from importlib import import_module
from pathlib import Path


class TestVeraPdfReleaseIdentity:
    def test_verapdf_proof_references_v11_artifact_hashes(self) -> None:
        records_module = import_module("civiccast.records.release_identity")
        real_digest = hashlib.sha256(b"the real v1.1 release artifact bytes").hexdigest()

        result = records_module.verify_verapdf_release_identity(
            proof_path=Path("docs/releases/evidence/v1.1-audit-hash-chain-proof.md"),
            release_version="1.1.0",
            expected_artifact_sha256=real_digest,
        )

        # The evidence doc only ever contained a placeholder hash
        # (sha256:aaaa...), never a real artifact's digest, so tying the
        # proof to a real computed digest must fail rather than pass.
        assert result.status == "failed"

    def test_stale_hash_not_matching_the_real_artifact_is_rejected(self, tmp_path: Path) -> None:
        """A hash-shaped string that merely appears in the proof text -- a
        typo, or a hash left over from a prior edit -- must not be accepted
        as proof of identity; it must match the real artifact's digest."""
        records_module = import_module("civiccast.records.release_identity")
        real_digest = hashlib.sha256(b"the real v1.1 release artifact bytes").hexdigest()
        stale_digest = "a" * 64
        proof_path = tmp_path / "proof.md"
        proof_path.write_text(f"1.1.0 sha256:{stale_digest}", encoding="utf-8")

        result = records_module.verify_verapdf_release_identity(
            proof_path=proof_path,
            release_version="1.1.0",
            expected_artifact_sha256=real_digest,
        )

        assert result.status == "failed"

    def test_hash_matching_the_real_artifact_is_accepted(self, tmp_path: Path) -> None:
        records_module = import_module("civiccast.records.release_identity")
        real_digest = hashlib.sha256(b"the real v1.1 release artifact bytes").hexdigest()
        proof_path = tmp_path / "proof.md"
        proof_path.write_text(f"1.1.0 sha256:{real_digest}", encoding="utf-8")

        result = records_module.verify_verapdf_release_identity(
            proof_path=proof_path,
            release_version="1.1.0",
            expected_artifact_sha256=real_digest,
        )

        assert result.status == "ok"
        assert result.artifact_sha256 == real_digest
