# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Verify the version string is exposed and shaped like a PEP 440 release."""

from __future__ import annotations

from packaging.version import Version

from civiccast import __version__ as umbrella_version
from civiccast._version import __version__ as canonical_version


def test_canonical_version_is_pep440() -> None:
    parsed = Version(canonical_version)
    assert str(parsed), f"Not PEP 440: {canonical_version!r}"


def test_umbrella_version_matches_canonical() -> None:
    """Re-export must be identical so importers don't drift."""
    assert umbrella_version == canonical_version
