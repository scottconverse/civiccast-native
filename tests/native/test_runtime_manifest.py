# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Red-first tests for the runtime-manifest trust artifacts (D5, AC1, AC7).

Covers `spec-packaging-closure` D5 (manifest trust at install, two-directional
verify) and D3/AC7 (per-file license provenance; unknown-license file count
must be ZERO or the build halts).

These are pure-function tests: no filesystem walking, `FileEntry` values are
constructed directly and fed to `build_runtime_manifest` /
`render_sha256sums` / `render_license_bom` / `verify_manifest`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from civiccast.native.runtime_licenses import classify_shipped_file
from civiccast.native.runtime_manifest import (
    DISTRIBUTION_LICENSE,
    DuplicatePathError,
    FileEntry,
    ManifestMismatchError,
    UnknownLicenseError,
    build_runtime_manifest,
    hash_directory_tree,
    render_license_bom,
    render_sha256sums,
    verify_manifest,
)

LOCK_SHA = "a" * 64


def _entry(
    path: str,
    *,
    sha256: str = "0" * 64,
    bytes_: int = 100,
    distribution: str = "gstreamer_libs",
    license_: str | None = None,
) -> FileEntry:
    # Default to the CONFIRMED per-file licence, falling back to the coarse
    # per-distribution map only for synthetic paths the provenance
    # investigation never examined (bin/mystery.dll and friends). Defaulting to
    # the distribution map for real paths made fixtures that were themselves
    # mis-licensed -- e.g. claiming LGPL for gstopenh264.dll, which is BSD -- so
    # the tests were asserting against a falsehood.
    resolved_license = license_
    if resolved_license is None:
        resolved_license = classify_shipped_file(path) or DISTRIBUTION_LICENSE[distribution]
    return FileEntry(
        path=path,
        sha256=sha256,
        bytes=bytes_,
        distribution=distribution,
        license=resolved_license,
    )


# --------------------------------------------------------------------------
# build_runtime_manifest
# --------------------------------------------------------------------------


def test_manifest_schema_round_trips_file_count_and_total_bytes() -> None:
    entries = [
        _entry("bin/glib-2.0-0.dll", bytes_=1234),
        _entry("bin/gstreamer-1.0-0.dll", bytes_=5678),
    ]
    manifest = build_runtime_manifest(entries, gstreamer_version="1.28.5", lock_sha256=LOCK_SHA)
    assert manifest["schema_version"] == 1
    assert manifest["gstreamer_version"] == "1.28.5"
    assert manifest["lock_sha256"] == LOCK_SHA
    assert manifest["file_count"] == 2
    assert manifest["total_bytes"] == 1234 + 5678
    assert len(manifest["files"]) == 2


def test_manifest_files_are_sorted_by_path_regardless_of_input_order() -> None:
    entries = [
        _entry("lib/gstreamer-1.0/gstopenh264.dll"),
        _entry("bin/glib-2.0-0.dll"),
        _entry("bin/gstreamer-1.0-0.dll"),
    ]
    manifest = build_runtime_manifest(entries, gstreamer_version="1.28.5", lock_sha256=LOCK_SHA)
    paths = [f["path"] for f in manifest["files"]]
    assert paths == [
        "bin/glib-2.0-0.dll",
        "bin/gstreamer-1.0-0.dll",
        "lib/gstreamer-1.0/gstopenh264.dll",
    ]


def test_manifest_file_entry_shape_matches_shared_contract() -> None:
    entries = [_entry("bin/glib-2.0-0.dll", sha256="f" * 64, bytes_=42)]
    manifest = build_runtime_manifest(entries, gstreamer_version="1.28.5", lock_sha256=LOCK_SHA)
    (record,) = manifest["files"]
    assert record == {
        "path": "bin/glib-2.0-0.dll",
        "sha256": "f" * 64,
        "bytes": 42,
        "distribution": "gstreamer_libs",
        "license": "LGPL-2.1-or-later",
    }


def test_manifest_raises_unknown_license_error_for_unmapped_distribution() -> None:
    entries = [
        _entry(
            "bin/mystery.dll",
            distribution="totally_unmapped_distribution",
            license_="LGPL-2.1-or-later",
        )
    ]
    with pytest.raises(UnknownLicenseError) as excinfo:
        build_runtime_manifest(entries, gstreamer_version="1.28.5", lock_sha256=LOCK_SHA)
    message = str(excinfo.value)
    assert "totally_unmapped_distribution" in message
    assert "bin/mystery.dll" in message


def test_manifest_raises_unknown_license_error_for_empty_license() -> None:
    entries = [_entry("bin/mystery.dll", license_="")]
    with pytest.raises(UnknownLicenseError):
        build_runtime_manifest(entries, gstreamer_version="1.28.5", lock_sha256=LOCK_SHA)


def test_manifest_raises_unknown_license_error_for_wrong_license_on_known_distribution() -> None:
    """Finding 2: a KNOWN distribution with the WRONG license must still halt.

    `gstreamer_libs` policy license is LGPL-2.1-or-later. Declaring MIT for a
    file from that distribution is a mis-license, not an unknown one -- AC7
    requires the entry's license to equal the policy license, not merely be
    non-empty with a mapped distribution.
    """
    entries = [
        _entry(
            "bin/glib-2.0-0.dll",
            distribution="gstreamer_libs",
            license_="MIT",
        )
    ]
    with pytest.raises(UnknownLicenseError) as excinfo:
        build_runtime_manifest(entries, gstreamer_version="1.28.5", lock_sha256=LOCK_SHA)
    message = str(excinfo.value)
    assert "bin/glib-2.0-0.dll" in message
    assert "MIT" in message
    assert "LGPL-2.1-or-later" in message


def test_gstreamer_ext_runtime_distribution_license_is_not_lgpl() -> None:
    """Coder self-caught finding: gstreamer_ext_runtime ships ONLY Microsoft
    VC++ Redistributable DLLs (msvcp140.dll, vcruntime140.dll,
    vcruntime140_1.dll) -- gstlibav.dll ships from gstreamer_plugins, not
    gstreamer_ext_runtime (evidence memo, "gstreamer_ext_runtime mislabel"
    section). gstreamer_ext_runtime's own dist-info/METADATA declares
    `License: LicenseRef-Proprietary`, not LGPL-2.1-or-later.
    """
    assert DISTRIBUTION_LICENSE["gstreamer_ext_runtime"] != "LGPL-2.1-or-later"
    assert DISTRIBUTION_LICENSE["gstreamer_ext_runtime"] == "LicenseRef-Proprietary"


def test_vcredist_files_from_gstreamer_ext_runtime_manifest_as_microsoft_vcredist() -> None:
    """Per-file classification outranks the coarse distribution map (see
    `_check_licenses_known`): even with the corrected LicenseRef-Proprietary
    distribution fallback, the three actual VC++ Redistributable files still
    manifest with the more specific `LicenseRef-Microsoft-VCRedist` that
    `runtime_licenses.classify_shipped_file` confirms for them -- never
    LGPL-2.1-or-later.
    """
    entries = [
        _entry("bin/msvcp140.dll", distribution="gstreamer_ext_runtime", sha256="3" * 64),
        _entry("bin/vcruntime140.dll", distribution="gstreamer_ext_runtime", sha256="4" * 64),
        _entry("bin/vcruntime140_1.dll", distribution="gstreamer_ext_runtime", sha256="5" * 64),
    ]
    manifest = build_runtime_manifest(entries, gstreamer_version="1.28.5", lock_sha256=LOCK_SHA)
    for record in manifest["files"]:
        assert record["license"] == "LicenseRef-Microsoft-VCRedist"
        assert record["license"] != "LGPL-2.1-or-later"


def test_manifest_raises_duplicate_path_error_for_repeated_path() -> None:
    """Finding 1: two FileEntry values for one path is a corrupt manifest.

    Even with different hashes, build refuses to emit a manifest that claims
    two different truths about the same shipped file.
    """
    entries = [
        _entry("bin/glib-2.0-0.dll", sha256="1" * 64),
        _entry("bin/glib-2.0-0.dll", sha256="2" * 64),
    ]
    with pytest.raises(DuplicatePathError) as excinfo:
        build_runtime_manifest(entries, gstreamer_version="1.28.5", lock_sha256=LOCK_SHA)
    assert "bin/glib-2.0-0.dll" in str(excinfo.value)


# --------------------------------------------------------------------------
# render_sha256sums
# --------------------------------------------------------------------------


def test_sha256sums_is_byte_identical_regardless_of_input_order() -> None:
    entries_a = [
        _entry("lib/gstreamer-1.0/gstopenh264.dll", sha256="1" * 64),
        _entry("bin/glib-2.0-0.dll", sha256="2" * 64),
    ]
    entries_b = list(reversed(entries_a))
    assert render_sha256sums(entries_a) == render_sha256sums(entries_b)


def test_sha256sums_format_is_hex_two_space_path_sorted_lf() -> None:
    entries = [
        _entry("lib/gstreamer-1.0/gstopenh264.dll", sha256="1" * 64),
        _entry("bin/glib-2.0-0.dll", sha256="2" * 64),
    ]
    output = render_sha256sums(entries)
    assert output == (
        "2" * 64 + "  bin/glib-2.0-0.dll\n" + "1" * 64 + "  lib/gstreamer-1.0/gstopenh264.dll\n"
    )
    assert "\r" not in output


# --------------------------------------------------------------------------
# render_license_bom
# --------------------------------------------------------------------------


def test_license_bom_contains_every_distribution_and_file_path() -> None:
    entries = [
        _entry("bin/glib-2.0-0.dll", distribution="gstreamer_libs"),
        _entry("python/gi/_gi.pyd", distribution="gstreamer_python"),
    ]
    bom = render_license_bom(entries)
    assert "gstreamer_libs" in bom
    assert "gstreamer_python" in bom
    assert "bin/glib-2.0-0.dll" in bom
    assert "python/gi/_gi.pyd" in bom


def test_license_bom_summary_lists_every_license_in_a_mixed_distribution() -> None:
    """A distribution is a wheel, not a licence -- the summary must say so.

    This is the real shape of the shipped tree: ``gstreamer_libs`` vendors ten
    different upstream projects. Reporting a single licence per distribution
    picked whichever file sorted first, which made the summary claim the whole
    wheel was `bzip2-1.0.6` (the real defect CC-WS5-PKG-010 caught). The
    alphabetically-first licence is deliberately the LEAST representative one
    here so a regression to `group[0]` cannot pass.
    """
    entries = [
        _entry("bin/bz2.dll", distribution="gstreamer_libs", license_="bzip2-1.0.6"),
        _entry("bin/glib-2.0-0.dll", distribution="gstreamer_libs", license_="LGPL-2.1-or-later"),
        _entry("bin/libxml2.dll", distribution="gstreamer_libs", license_="MIT"),
    ]
    summary = render_license_bom(entries).split("## Per-file provenance")[0]

    row = next(line for line in summary.splitlines() if line.startswith("| gstreamer_libs |"))
    assert "bzip2-1.0.6" in row
    assert "LGPL-2.1-or-later" in row
    assert "MIT" in row
    # Deterministic order (AC1): the same set of files renders byte-identically.
    assert row == "| gstreamer_libs | LGPL-2.1-or-later, MIT, bzip2-1.0.6 | 3 | 300 |"


def test_license_bom_summary_does_not_deduplicate_away_a_distributions_only_license() -> None:
    """The homogeneous case must still render one licence, not an empty cell."""
    entries = [
        _entry("python/gi/_gi.pyd", distribution="gstreamer_python", license_="LGPL-2.1-or-later"),
        _entry(
            "python/gi/__init__.py", distribution="gstreamer_python", license_="LGPL-2.1-or-later"
        ),
    ]
    summary = render_license_bom(entries).split("## Per-file provenance")[0]
    row = next(line for line in summary.splitlines() if line.startswith("| gstreamer_python |"))
    assert row == "| gstreamer_python | LGPL-2.1-or-later | 2 | 200 |"


# --------------------------------------------------------------------------
# verify_manifest
# --------------------------------------------------------------------------


def test_verify_manifest_passes_on_a_matching_pair() -> None:
    entries = [
        _entry("bin/glib-2.0-0.dll", sha256="1" * 64, bytes_=10),
        _entry("bin/gstreamer-1.0-0.dll", sha256="2" * 64, bytes_=20),
    ]
    manifest = build_runtime_manifest(entries, gstreamer_version="1.28.5", lock_sha256=LOCK_SHA)
    verify_manifest(manifest, entries)  # must not raise


def test_verify_manifest_names_a_missing_entry() -> None:
    entries = [
        _entry("bin/glib-2.0-0.dll", sha256="1" * 64),
        _entry("bin/gstreamer-1.0-0.dll", sha256="2" * 64),
    ]
    manifest = build_runtime_manifest(entries, gstreamer_version="1.28.5", lock_sha256=LOCK_SHA)
    on_disk = entries[:1]  # gstreamer-1.0-0.dll is missing from disk
    with pytest.raises(ManifestMismatchError) as excinfo:
        verify_manifest(manifest, on_disk)
    message = str(excinfo.value)
    assert "MISSING" in message
    assert "bin/gstreamer-1.0-0.dll" in message
    assert "ORPHAN" not in message
    assert "HASH MISMATCH" not in message


def test_verify_manifest_names_an_orphan_file() -> None:
    entries = [_entry("bin/glib-2.0-0.dll", sha256="1" * 64)]
    manifest = build_runtime_manifest(entries, gstreamer_version="1.28.5", lock_sha256=LOCK_SHA)
    on_disk = [
        *entries,
        _entry("bin/unexpected.dll", sha256="9" * 64),
    ]
    with pytest.raises(ManifestMismatchError) as excinfo:
        verify_manifest(manifest, on_disk)
    message = str(excinfo.value)
    assert "ORPHAN" in message
    assert "bin/unexpected.dll" in message
    assert "MISSING" not in message
    assert "HASH MISMATCH" not in message


def test_verify_manifest_names_a_hash_mismatch() -> None:
    entries = [_entry("bin/glib-2.0-0.dll", sha256="1" * 64)]
    manifest = build_runtime_manifest(entries, gstreamer_version="1.28.5", lock_sha256=LOCK_SHA)
    on_disk = [_entry("bin/glib-2.0-0.dll", sha256="f" * 64)]
    with pytest.raises(ManifestMismatchError) as excinfo:
        verify_manifest(manifest, on_disk)
    message = str(excinfo.value)
    assert "HASH MISMATCH" in message
    assert "bin/glib-2.0-0.dll" in message
    assert "MISSING" not in message
    assert "ORPHAN" not in message


def test_verify_manifest_raises_duplicate_path_error_even_when_disk_matches_one_of_them() -> None:
    """Finding 1: a manifest with two different hashes for one path must never
    verify cleanly, even when the on-disk file happens to match one of the
    two claimed hashes -- the old dict-comprehension collapse silently kept
    whichever record came last and let this pass.
    """
    manifest = {
        "schema_version": 1,
        "gstreamer_version": "1.28.5",
        "lock_sha256": LOCK_SHA,
        "file_count": 2,
        "total_bytes": 20,
        "files": [
            {
                "path": "bin/glib-2.0-0.dll",
                "sha256": "1" * 64,
                "bytes": 10,
                "distribution": "gstreamer_libs",
                "license": "LGPL-2.1-or-later",
            },
            {
                "path": "bin/glib-2.0-0.dll",
                "sha256": "2" * 64,
                "bytes": 10,
                "distribution": "gstreamer_libs",
                "license": "LGPL-2.1-or-later",
            },
        ],
    }
    on_disk = [_entry("bin/glib-2.0-0.dll", sha256="2" * 64)]
    with pytest.raises(DuplicatePathError) as excinfo:
        verify_manifest(manifest, on_disk)
    assert "bin/glib-2.0-0.dll" in str(excinfo.value)


# --------------------------------------------------------------------------
# hash_directory_tree (Finding 3: real filesystem tests, no mocks)
# --------------------------------------------------------------------------


def test_hash_directory_tree_describes_nested_files_with_correct_hash_and_size(
    tmp_path: Path,
) -> None:
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "glib-2.0-0.dll").write_bytes(b"glib payload bytes")
    (tmp_path / "lib" / "gstreamer-1.0").mkdir(parents=True)
    (tmp_path / "lib" / "gstreamer-1.0" / "gstopenh264.dll").write_bytes(b"plugin payload")

    distribution_of = {
        "bin/glib-2.0-0.dll": "gstreamer_libs",
        "lib/gstreamer-1.0/gstopenh264.dll": "gstreamer_plugins",
    }
    entries = hash_directory_tree(tmp_path, distribution_of=distribution_of)

    by_path = {entry.path: entry for entry in entries}
    assert set(by_path) == {"bin/glib-2.0-0.dll", "lib/gstreamer-1.0/gstopenh264.dll"}

    glib_entry = by_path["bin/glib-2.0-0.dll"]
    assert glib_entry.sha256 == hashlib.sha256(b"glib payload bytes").hexdigest()
    assert glib_entry.bytes == len(b"glib payload bytes")
    assert glib_entry.distribution == "gstreamer_libs"
    assert glib_entry.license == DISTRIBUTION_LICENSE["gstreamer_libs"]

    plugin_entry = by_path["lib/gstreamer-1.0/gstopenh264.dll"]
    assert plugin_entry.sha256 == hashlib.sha256(b"plugin payload").hexdigest()
    assert plugin_entry.distribution == "gstreamer_plugins"


def test_hash_directory_tree_ignores_empty_directories(tmp_path: Path) -> None:
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "glib-2.0-0.dll").write_bytes(b"payload")
    (tmp_path / "empty_subdir").mkdir()

    entries = hash_directory_tree(
        tmp_path, distribution_of={"bin/glib-2.0-0.dll": "gstreamer_libs"}
    )

    assert [entry.path for entry in entries] == ["bin/glib-2.0-0.dll"]


def test_hash_directory_tree_converts_windows_separators_to_forward_slashes(
    tmp_path: Path,
) -> None:
    nested = tmp_path / "lib" / "gstreamer-1.0" / "plugins"
    nested.mkdir(parents=True)
    (nested / "gstopenh264.dll").write_bytes(b"plugin payload")

    entries = hash_directory_tree(
        tmp_path,
        distribution_of={"lib/gstreamer-1.0/plugins/gstopenh264.dll": "gstreamer_plugins"},
    )

    (entry,) = entries
    assert entry.path == "lib/gstreamer-1.0/plugins/gstopenh264.dll"
    assert "\\" not in entry.path


def test_hash_directory_tree_raises_unknown_license_error_for_unmapped_path(
    tmp_path: Path,
) -> None:
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "mystery.dll").write_bytes(b"mystery payload")

    with pytest.raises(UnknownLicenseError) as excinfo:
        hash_directory_tree(tmp_path, distribution_of={})

    assert "bin/mystery.dll" in str(excinfo.value)
