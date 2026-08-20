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
    root: Path, version: str = "0.10.0", *, native_version: str = "0.11.0-beta.1"
) -> None:
    """A fully-aligned fixture tree, post-chain-J.

    ``version`` is the WSL/mainline product line's own identity, sourced from
    ``civiccast/_version.py`` -- the SAME string every WSL-facing surface
    below tracks (README, CHANGELOG, docs/index.html, API-REFERENCE, the
    docs/releases verification doc, Cargo.toml, tauri.conf.json,
    headless-bootstrap.ps1, the operator-console e2e mock).

    ``native_version`` is the SEPARATE native Windows product line's own
    identity, sourced from ``civiccast/_native_version.py`` -- tracked by
    ``tauri.native.conf.json`` and the installer's Rust ``CIVICCAST_VERSION``
    constant. DIFFERENT from ``version`` by default, matching the real,
    post-fix repo shape, where the two product lines must never report an
    identical version string. Pass equal values explicitly to exercise the
    divergence check itself."""
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
    # The WSL Tauri config tracks the WSL line's own `version`.
    _write(
        root / "civiccast" / "apps" / "installer" / "src-tauri" / "tauri.conf.json",
        f'{{"identifier": "org.civiccast.installer", "version": "{version}"}}\n',
    )
    # The native Tauri overlay tracks the SEPARATE native line's own version.
    _write(
        root / "civiccast" / "apps" / "installer" / "src-tauri" / "tauri.native.conf.json",
        f'{{"identifier": "org.civiccast.native", "version": "{native_version}"}}\n',
    )
    # The operator-console e2e mock is a synthetic frontend-rendering test
    # (not a real installer-identity surface), pinned to the WSL `version`.
    _write(
        root / "civiccast" / "apps" / "portal-operator" / "e2e" / "route-table-smoke.spec.ts",
        f"await expect(page.getByText('v{version}')).toBeVisible()\n",
    )
    # headless-bootstrap.ps1 is WSL-ONLY: it must track the WSL version.
    _write(
        root
        / "civiccast"
        / "apps"
        / "installer"
        / "src-tauri"
        / "resources"
        / "headless-bootstrap.ps1",
        f'$CivicCastVersion = "{version}"\n',
    )
    # main.rs's CIVICCAST_VERSION is the NATIVE line's own runtime constant.
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


def test_release_identity_rejects_wsl_tauri_config_drifting_from_the_version_file(
    tmp_path: Path,
) -> None:
    """tauri.conf.json (WSL) must track civiccast/_version.py's own version --
    headless-bootstrap.ps1 is pinned against THIS file's version, not the
    top-level `version` directly, so a drift here must surface on its own."""
    _write_aligned_release_identity_fixture(tmp_path)
    _write(
        tmp_path / "civiccast" / "apps" / "installer" / "src-tauri" / "tauri.conf.json",
        '{"identifier": "org.civiccast.installer", "version": "0.9.9"}\n',
    )

    # One violation, not two. The second was the headless-bootstrap.ps1
    # expected-version guard; that script is the WSL2 install lane, deleted
    # under "no linux", and check_release_identity no longer audits a file this
    # product does not ship. The WSL/native version-agreement check above it is
    # untouched and still fires.
    assert evaluate_release_identity(tmp_path) == [
        "civiccast/apps/installer/src-tauri/tauri.conf.json reports WSL product version "
        "0.9.9, expected 0.10.0 (from civiccast/_version.py).",
    ]


def test_release_identity_rejects_native_overlay_version_drifting_from_the_native_version_file(
    tmp_path: Path,
) -> None:
    """chain J (2026-08-02): nothing checked tauri.native.conf.json's own
    "version" before this -- it could silently drift from
    civiccast._native_version, which would break the installer's own
    post-install health verification (main.rs's CIVICCAST_VERSION constant,
    required equal to the same native_source_version, is what that check
    compares against the running service)."""
    _write_aligned_release_identity_fixture(tmp_path)
    _write(
        tmp_path / "civiccast" / "apps" / "installer" / "src-tauri" / "tauri.native.conf.json",
        '{"identifier": "org.civiccast.native", "version": "0.11.0-beta.2"}\n',
    )

    assert evaluate_release_identity(tmp_path) == [
        "civiccast/apps/installer/src-tauri/tauri.native.conf.json reports native product "
        "version 0.11.0-beta.2, expected 0.11.0-beta.1 (from civiccast/_native_version.py)."
    ]


def test_release_identity_rejects_native_and_wsl_product_lines_sharing_one_version(
    tmp_path: Path,
) -> None:
    """The regression this whole chain exists to prevent: the native and WSL
    Tauri configs must never report the same version string again (that was
    exactly the "two rc15 installers" confusion)."""
    _write_aligned_release_identity_fixture(tmp_path, version="0.10.0", native_version="0.10.0")

    assert evaluate_release_identity(tmp_path) == [
        "civiccast/apps/installer/src-tauri/tauri.native.conf.json reports the same version "
        "(0.10.0) as the WSL product's civiccast/apps/installer/src-tauri/tauri.conf.json "
        "(0.10.0) -- the native and WSL product lines must never report an identical "
        "version string."
    ]


def test_release_identity_rejects_main_rs_constant_drifting_from_the_native_version_file(
    tmp_path: Path,
) -> None:
    """main.rs's CIVICCAST_VERSION is the REAL runtime source for the
    installer's post-install health verification and the real pack-trust
    expected_product_version/expected_compatible_core -- it must track
    civiccast._native_version, not the WSL civiccast._version."""
    _write_aligned_release_identity_fixture(tmp_path)
    _write(
        tmp_path / "civiccast" / "apps" / "installer" / "src-tauri" / "src" / "main.rs",
        'const CIVICCAST_VERSION: &str = "0.10.0";\n',  # the WSL version, not the native one
    )

    assert evaluate_release_identity(tmp_path) == [
        "civiccast/apps/installer/src-tauri/src/main.rs does not carry the installer Rust "
        "runtime version constant for 0.11.0-beta.1 (from civiccast/_native_version.py). This "
        "constant drives the installer's own post-install health verification and the real "
        "pack-trust expected_product_version/expected_compatible_core -- see "
        "civiccast.native.station_runtime.native_reported_version_environment for the matching "
        "runtime override that makes the native-hosted backend's /health agree."
    ]


def test_release_identity_accepts_matching_health_example_version(tmp_path: Path) -> None:
    """TW-E: docs/technical-ops-reference.md's `/health` example must show the
    same version civiccast/_version.py reports."""
    _write_aligned_release_identity_fixture(tmp_path)
    _write(
        tmp_path / "docs" / "technical-ops-reference.md",
        "```bash\ncurl -s http://127.0.0.1:8000/health\n"
        '{"status":"degraded","version":"0.10.0","schema":"not-configured"}\n```\n',
    )

    assert evaluate_release_identity(tmp_path) == []


def test_release_identity_rejects_stale_health_example_version(tmp_path: Path) -> None:
    """TW-E regression guard: docs/technical-ops-reference.md's `/health`
    JSON example named `1.0.0-rc17` while civiccast/_version.py had already
    moved to `1.0.0-rc18`. FAILS red against that exact stale-doc shape;
    PASSES once the example is updated to name the current version."""
    _write_aligned_release_identity_fixture(tmp_path)
    _write(
        tmp_path / "docs" / "technical-ops-reference.md",
        "```bash\ncurl -s http://127.0.0.1:8000/health\n"
        '{"status":"degraded","version":"0.9.0","schema":"not-configured"}\n```\n',
    )

    assert evaluate_release_identity(tmp_path) == [
        "docs/technical-ops-reference.md's /health example shows version '0.9.0', expected '0.10.0'."
    ]
