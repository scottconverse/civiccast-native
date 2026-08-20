# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Policy checks for the operator console version label."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOPBAR = (
    ROOT / "civiccast" / "apps" / "portal-operator" / "src" / "components" / "shell" / "TopBar.tsx"
)


def test_operator_header_reads_runtime_version_without_stale_fallback() -> None:
    source = TOPBAR.read_text(encoding="utf-8")

    assert "getCivicCastVersion" in source
    assert "/api/version" not in source
    assert "'2.0.2'" not in source
    assert '"2.0.2"' not in source
