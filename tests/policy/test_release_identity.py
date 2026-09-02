# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for release identity policy checks."""

from __future__ import annotations

from pathlib import Path

from scripts.policy.check_release_identity import evaluate_release_identity


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_aligned_release_identity_fixture(
    root: Path, version: str = "0.10.0", *, native_version: str | None = None
) -> None:
    """A fully-aligned fixture tree, post-WSL-retirement (2026-08-31).

    ``version`` is this repository's single product identity, sourced from
    ``civiccast/_version.py`` -- and tracked identically by every surface
    below (README, CHANGELOG, docs/index.html, API-REFERENCE, the
    docs/releases verification doc, Cargo.toml, tauri.conf.json, the
    operator-console e2e mock, tauri.native.conf.json, and main.rs's
    CIVICCAST_VERSION constant).

    ``native_version`` defaults to the same value as ``version``, matching
    the real, post-retirement repo shape where ``civiccast/_native_version.py``
    is a distinct file but is REQUIRED to agree with ``civiccast/_version.py``
    now that there is one product line. Pass a different value explicitly to
    exercise the single-source-of-truth divergence check itself."""
    if native_version is None:
        native_version = version
    _write(root / "civiccast" / "_version.py", f'__version__ = "{version}"\n')
    _write(root / "civiccast" / "_native_version.py", f'__version__ = "{native_version}"\n')
    _write(root / "docs" / "API-REFERENCE.md", f"OpenAPI schema, version `{version}`\n")
    _write(
        root / "README.md",
        f"Latest release: https://github.com/scottconverse/civiccast/releases/tag/v{version}\n",
    )
    _write(root / "CHANGELOG.md", f"## [{version}] - 2026-05-14\n")
    _write(
        root / "docs" / "index.html",
        f'<a href="https://github.com/scottconverse/civiccast/releases/tag/v{version}">v{version}</a>',
    )
    _write(root / "docs" / "releases" / f"v{version}-verification.md", f"v{version}\n")
    _write(
        root / "civiccast" / "apps" / "installer" / "src-tauri" / "Cargo.toml",
        f'[package]\nname = "civiccast-installer"\nversion = "{version}"\n',
    )
    # This repository's sole Tauri config tracks civiccast/_version.py's own
    # version.
    _write(
        root / "civiccast" / "apps" / "installer" / "src-tauri" / "tauri.conf.json",
        f'{{"identifier": "org.civiccast.installer", "version": "{version}"}}\n',
    )
    # The native Tauri overlay tracks civiccast/_native_version.py's own
    # version -- required equal to `version` today, but checked against its
    # own source file so a drift in this file specifically still surfaces.
    _write(
        root / "civiccast" / "apps" / "installer" / "src-tauri" / "tauri.native.conf.json",
        f'{{"identifier": "org.civiccast.native", "version": "{native_version}"}}\n',
    )
    # The operator-console e2e mock is a synthetic frontend-rendering test,
    # pinned to the product's single version.
    _write(
        root / "civiccast" / "apps" / "portal-operator" / "e2e" / "route-table-smoke.spec.ts",
        f"await expect(page.getByText('v{version}')).toBeVisible()\n",
    )
    # main.rs's CIVICCAST_VERSION is the installer's own runtime constant,
    # sourced from civiccast/_native_version.py.
    _write(
        root / "civiccast" / "apps" / "installer" / "src-tauri" / "src" / "main.rs",
        f'const CIVICCAST_VERSION: &str = "{native_version}";\n',
    )


def test_release_identity_accepts_historical_release_dates(tmp_path: Path) -> None:
    _write_aligned_release_identity_fixture(tmp_path)

    assert evaluate_release_identity(tmp_path) == []


def test_release_identity_accepts_explicitly_held_unpublished_candidate(tmp_path: Path) -> None:
    _write_aligned_release_identity_fixture(tmp_path)
    _write(
        tmp_path / "README.md",
        "v0.10.0 is the current owner-held unpublished candidate.\n",
    )
    _write(
        tmp_path / "docs" / "index.html",
        "<p>v0.10.0 is the current owner-held unpublished candidate.</p>",
    )
    _write(
        tmp_path / "CHANGELOG.md",
        "## [Unreleased]\n\nCurrent owner-held unpublished candidate: v0.10.0.\n",
    )

    assert evaluate_release_identity(tmp_path) == []


def test_release_identity_rejects_undated_changelog_section(tmp_path: Path) -> None:
    _write_aligned_release_identity_fixture(tmp_path)
    _write(tmp_path / "CHANGELOG.md", "## [0.10.0]\n")

    assert evaluate_release_identity(tmp_path) == [
        "CHANGELOG.md is missing a dated [0.10.0] section."
    ]


def test_release_identity_rejects_mismatched_installer_cargo_version(
    tmp_path: Path,
) -> None:
    _write_aligned_release_identity_fixture(tmp_path)
    _write(
        tmp_path / "civiccast" / "apps" / "installer" / "src-tauri" / "Cargo.toml",
        '[package]\nname = "civiccast-installer"\nversion = "0.9.0"\n',
    )

    assert evaluate_release_identity(tmp_path) == [
        "civiccast/apps/installer/src-tauri/Cargo.toml reports installer version 0.9.0, expected 0.10.0."
    ]


def test_release_identity_rejects_tauri_config_drifting_from_the_version_file(
    tmp_path: Path,
) -> None:
    """tauri.conf.json must track civiccast/_version.py's own version."""
    _write_aligned_release_identity_fixture(tmp_path)
    _write(
        tmp_path / "civiccast" / "apps" / "installer" / "src-tauri" / "tauri.conf.json",
        '{"identifier": "org.civiccast.installer", "version": "0.9.9"}\n',
    )

    assert evaluate_release_identity(tmp_path) == [
        "civiccast/apps/installer/src-tauri/tauri.conf.json reports product version "
        "0.9.9, expected 0.10.0 (from civiccast/_version.py).",
    ]


def test_release_identity_rejects_native_overlay_version_drifting_from_the_native_version_file(
    tmp_path: Path,
) -> None:
    """tauri.native.conf.json's own "version" must track
    civiccast._native_version -- a drift here would break the installer's own
    post-install health verification (main.rs's CIVICCAST_VERSION constant,
    required equal to the same native_source_version, is what that check
    compares against the running service)."""
    _write_aligned_release_identity_fixture(tmp_path)
    _write(
        tmp_path / "civiccast" / "apps" / "installer" / "src-tauri" / "tauri.native.conf.json",
        '{"identifier": "org.civiccast.native", "version": "0.10.1"}\n',
    )

    assert evaluate_release_identity(tmp_path) == [
        "civiccast/apps/installer/src-tauri/tauri.native.conf.json reports native product "
        "version 0.10.1, expected 0.10.0 (from civiccast/_native_version.py)."
    ]


def test_release_identity_rejects_native_version_file_diverging_from_the_single_source(
    tmp_path: Path,
) -> None:
    """The regression this whole rewrite exists to catch: with the WSL line
    (and its separate version identity) retired, there is one product and
    one version. civiccast/_native_version.py drifting from
    civiccast/_version.py is the bug now -- the two used to be REQUIRED to
    differ; today they are required to agree."""
    _write_aligned_release_identity_fixture(tmp_path, version="0.10.0", native_version="0.10.0")
    _write(tmp_path / "civiccast" / "_native_version.py", '__version__ = "0.10.1"\n')

    assert evaluate_release_identity(tmp_path) == [
        "civiccast/_native_version.py reports version 0.10.1, expected 0.10.0 "
        "(from civiccast/_version.py) -- there is one product line now and both "
        "files must agree.",
        "civiccast/apps/installer/src-tauri/tauri.native.conf.json reports native product "
        "version 0.10.0, expected 0.10.1 (from civiccast/_native_version.py).",
        "civiccast/apps/installer/src-tauri/src/main.rs does not carry the installer Rust "
        "runtime version constant for 0.10.1 (from civiccast/_native_version.py). This "
        "constant drives the installer's own post-install health verification and the real "
        "pack-trust expected_product_version/expected_compatible_core -- see "
        "civiccast.native.station_runtime.native_reported_version_environment for the matching "
        "runtime override that makes the native-hosted backend's /health agree.",
    ]


def test_release_identity_rejects_main_rs_constant_drifting_from_the_native_version_file(
    tmp_path: Path,
) -> None:
    """main.rs's CIVICCAST_VERSION is the REAL runtime source for the
    installer's post-install health verification and the real pack-trust
    expected_product_version/expected_compatible_core -- it must track
    civiccast._native_version."""
    _write_aligned_release_identity_fixture(tmp_path)
    _write(
        tmp_path / "civiccast" / "apps" / "installer" / "src-tauri" / "src" / "main.rs",
        'const CIVICCAST_VERSION: &str = "0.9.0";\n',
    )

    assert evaluate_release_identity(tmp_path) == [
        "civiccast/apps/installer/src-tauri/src/main.rs does not carry the installer Rust "
        "runtime version constant for 0.10.0 (from civiccast/_native_version.py). This "
        "constant drives the installer's own post-install health verification and the real "
        "pack-trust expected_product_version/expected_compatible_core -- see "
        "civiccast.native.station_runtime.native_reported_version_environment for the matching "
        "runtime override that makes the native-hosted backend's /health agree."
    ]


def test_release_identity_accepts_matching_health_example_version(tmp_path: Path) -> None:
    """TW-E: docs/technical-ops-reference.md's `/health` example must show the
    version a native station reports -- civiccast/_native_version.py's,
    which is now required to equal civiccast/_version.py's."""
    _write_aligned_release_identity_fixture(tmp_path)
    _write(
        tmp_path / "docs" / "technical-ops-reference.md",
        "```bash\ncurl -s http://127.0.0.1:8000/health\n"
        '{"status":"degraded","version":"0.10.0","schema":"not-configured"}\n```\n',
    )

    assert evaluate_release_identity(tmp_path) == []


def test_release_identity_rejects_stale_health_example_version(tmp_path: Path) -> None:
    """TW-E regression guard: the `/health` JSON example naming a version that
    is nobody's current one. FAILS red against that stale-doc shape; PASSES
    once the example names what a native station actually reports."""
    _write_aligned_release_identity_fixture(tmp_path)
    _write(
        tmp_path / "docs" / "technical-ops-reference.md",
        "```bash\ncurl -s http://127.0.0.1:8000/health\n"
        '{"status":"degraded","version":"0.9.0","schema":"not-configured"}\n```\n',
    )

    assert evaluate_release_identity(tmp_path) == [
        "docs/technical-ops-reference.md's /health example shows version '0.9.0', "
        "expected '0.10.0' (from civiccast/_native_version.py)."
    ]
