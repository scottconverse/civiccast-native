# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Policy: a simulated archive must never look like a real one.

GauntletGate TW-1 (Critical, 2026-07-21). On a default install the Internet
Archive and local-NAS providers resolve to ``mock``. The mock returned
``https://archive.org/details/<asset_id>`` -- the *same* URL shape the real
client builds (civiccast/archive/internet_archive.py:27) -- carrying the same
``credential_posture``, so nothing in the returned object distinguished a real
archival write from one that never happened. The publish dashboard rendered
that URL verbatim, and docs/records-clerk-guide.md tells the clerk this archival
is required for every public-record meeting.

A records clerk could therefore approve an Internet Archive surface, see a
plausible archive.org link, and reasonably believe the legal archive obligation
was met when nothing was written anywhere.

These tests pin the two properties that make that impossible:
  1. a simulated proof is machine-readable as simulated (``simulated=True``)
  2. a simulated proof's URL cannot be mistaken for, or resolve as, a real one
"""

from __future__ import annotations

import pytest

from civiccast.archive.models import (
    ArchiveProof,
    MockInternetArchiveClient,
    MockLocalNasArchiveClient,
)

PAYLOAD = b"meeting-bytes"
ASSET = "council-2026-05-08"


def test_mock_internet_archive_proof_is_flagged_simulated() -> None:
    proof = MockInternetArchiveClient().upload(asset_id=ASSET, payload=PAYLOAD)
    assert proof.simulated is True, (
        "A mock archive write must be machine-readable as simulated, or no UI "
        "or API consumer can tell it apart from a real archival record."
    )


def test_mock_internet_archive_url_cannot_pass_as_a_real_permalink() -> None:
    proof = MockInternetArchiveClient().upload(asset_id=ASSET, payload=PAYLOAD)
    assert "archive.org" not in proof.target_url_or_path, (
        f"The simulated proof returned {proof.target_url_or_path!r}, which reads "
        "as a real archive.org permalink for an item that was never created. "
        "A clerk copying that link would believe the meeting is archived."
    )
    # RFC 2606 reserves .invalid precisely so it can never resolve.
    assert proof.target_url_or_path.endswith(".invalid") or ".invalid/" in (
        proof.target_url_or_path
    ), "A simulated target must use a guaranteed-non-resolving host."


@pytest.mark.parametrize("proof_index", [0, 1])
def test_mock_local_nas_proofs_are_flagged_simulated(proof_index: int) -> None:
    proofs = MockLocalNasArchiveClient().archive(asset_id=ASSET, payload=PAYLOAD)
    assert proofs[proof_index].simulated is True


def test_real_proofs_default_to_not_simulated() -> None:
    """The flag must default False so real clients are unchanged by this fix."""
    proof = ArchiveProof(
        target_type="internet_archive",
        target_url_or_path="https://archive.org/details/real-item",
        verification_hash="sha256:" + "0" * 64,
        credential_posture="informal_per_station",
    )
    assert proof.simulated is False
