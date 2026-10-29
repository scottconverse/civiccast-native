# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Shipped runtime coverage and fail-closed native finding triage."""

import datetime as dt

import pytest

from scripts.check_native_audit import check
from scripts.native_gstreamer_ffmpeg_overlay import policy as gstreamer_ffmpeg_policy
from scripts.native_security_inventory import inventory


def test_inventory_includes_ocr_pdfium_native_server_and_excludes_build_node() -> None:
    components = {component["name"]: component for component in inventory()["components"]}
    names = set(components)
    assert {
        "tesseract",
        "leptonica",
        "tessdata-fast-eng",
        "pypdfium2",
        "cpython",
        "postgres",
        "ffmpeg",
        "gstreamer",
        "ollama",
    } <= names
    assert "node" not in names
    for name in ("gstreamer-libexpat", "cpython-libexpat"):
        assert components[name]["cpe"].startswith("cpe:2.3:a:libexpat_project:libexpat:")
    reviewed = gstreamer_ffmpeg_policy()
    ffmpeg = components["gstreamer-ffmpeg"]
    assert ffmpeg["version"] == reviewed["version"]
    assert ":ffmpeg:ffmpeg:7.1.5:" in ffmpeg["cpe"]
    assert ffmpeg["hashes"] == [
        {"alg": "SHA-256", "content": reviewed["provenance"]["source_sha256"]}
    ]


def test_native_triage_requires_exact_version_and_current_review() -> None:
    match = {
        "artifact": {"name": "library", "version": "2"},
        "vulnerability": {"id": "CVE-example"},
    }
    entry = {
        "package": "library",
        "version": "2",
        "id": "CVE-example",
        "reason": "Absent vulnerable codec",
        "evidence": ["shipped manifest"],
        "review_by": "2026-11-29",
    }
    assert not check({"matches": [match]}, {"not_affected": [entry]}, today=dt.date(2026, 10, 29))
    assert check({"matches": [match]}, {"not_affected": [entry]}, today=dt.date(2026, 12, 1))
    entry["version"] = "1"
    assert check({"matches": [match]}, {"not_affected": [entry]}, today=dt.date(2026, 10, 29))
    with pytest.raises(KeyError):
        check({"error": "scanner failed"}, {"not_affected": []})
