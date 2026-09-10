# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Shared fixtures for the load / switch labs."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _live_hls_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every lab builds its rolling station under ``tmp_path``; the media
    router serves only folders inside ``CIVICCAST_LIVE_HLS_ROOT`` (or the
    egress work dir), so point the root at the test's own temp dir."""
    monkeypatch.setenv("CIVICCAST_LIVE_HLS_ROOT", str(tmp_path))
