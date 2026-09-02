#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Policy: release identity must agree before a tag candidate ships.

There is one product line in this repository (native-Windows CivicCast) and
one version. The WSL/mainline product line, and the separate version
identity it used to carry (``civiccast/_version.py`` tracking one number
while ``civiccast/_native_version.py`` tracked a deliberately different one,
chain J, 2026-08-02), were retired by owner decision -- the WSL/Linux lane
itself on 2026-08-19, and this last piece of its version machinery on
2026-08-31. Every surface this check touches is now required to agree on the
SAME version string. ``civiccast/_native_version.py`` still exists as a
distinct file (a dozen-plus native-line surfaces import it by name and
collapsing it is tracked as separate cleanup, not required for correctness),
but this check now asserts its value equals ``civiccast/_version.py``'s
rather than requiring the two to differ.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

try:
    from policy_utils import find_repo_root
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from scripts.policy.policy_utils import find_repo_root


REPO_ROOT = find_repo_root(__file__)
# The single source of truth for the product's version.
VERSION_FILE = REPO_ROOT / "civiccast" / "_version.py"
# Kept as a separate file (see module docstring) but required to always
# equal VERSION_FILE now that there is only one product line.
NATIVE_VERSION_FILE = REPO_ROOT / "civiccast" / "_native_version.py"
API_REFERENCE = REPO_ROOT / "docs" / "API-REFERENCE.md"
README = REPO_ROOT / "README.md"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
DOCS_INDEX = REPO_ROOT / "docs" / "index.html"
INSTALLER_CARGO = REPO_ROOT / "civiccast" / "apps" / "installer" / "src-tauri" / "Cargo.toml"
TAURI_CONFIG = REPO_ROOT / "civiccast" / "apps" / "installer" / "src-tauri" / "tauri.conf.json"
NATIVE_TAURI_CONFIG = (
    REPO_ROOT / "civiccast" / "apps" / "installer" / "src-tauri" / "tauri.native.conf.json"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_version(path: Path, root: Path = REPO_ROOT) -> str:
    match = re.search(r'__version__\s*=\s*"([^"]+)"', _read(path))
    if not match:
        raise ValueError(f"Could not read __version__ from {path.relative_to(root)}")
    return match.group(1)


def _version() -> str:
    return _extract_version(VERSION_FILE)


def _require(condition: bool, message: str, violations: list[str]) -> None:
    if not condition:
        violations.append(message)


def _repo_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def evaluate_release_identity(root: Path = REPO_ROOT) -> list[str]:
    version_file = root / "civiccast" / "_version.py"
    version = _extract_version(version_file, root)
    native_version_file = root / "civiccast" / "_native_version.py"
    native_source_version = _extract_version(native_version_file, root)
    version_doc = root / "docs" / "releases" / f"v{version}-verification.md"
    api_reference_path = root / "docs" / "API-REFERENCE.md"
    readme_path = root / "README.md"
    changelog_path = root / "CHANGELOG.md"
    docs_index_path = root / "docs" / "index.html"
    installer_cargo_path = root / "civiccast" / "apps" / "installer" / "src-tauri" / "Cargo.toml"
    tauri_config_path = root / "civiccast" / "apps" / "installer" / "src-tauri" / "tauri.conf.json"
    native_tauri_config_path = (
        root / "civiccast" / "apps" / "installer" / "src-tauri" / "tauri.native.conf.json"
    )
    violations: list[str] = []

    technical_ops_reference_path = root / "docs" / "technical-ops-reference.md"

    api_reference = _read(api_reference_path)
    readme = _read(readme_path)
    changelog = _read(changelog_path)
    docs_index = _read(docs_index_path)
    release_doc = _read(version_doc) if version_doc.exists() else ""
    technical_ops_reference = (
        _read(technical_ops_reference_path) if technical_ops_reference_path.exists() else ""
    )
    installer_cargo = tomllib.loads(_read(installer_cargo_path))
    installer_version = installer_cargo.get("package", {}).get("version")
    tauri_config = json.loads(_read(tauri_config_path))
    tauri_version = tauri_config.get("version")
    native_tauri_config = json.loads(_read(native_tauri_config_path))
    native_version = native_tauri_config.get("version")
    held_candidate_marker = "owner-held unpublished candidate"
    held_candidate = (
        f"v{version}" in readme
        and held_candidate_marker in readme.lower()
        and f"v{version}" in docs_index
        and held_candidate_marker in docs_index.lower()
    )

    # The single-source-of-truth invariant this whole check exists to
    # enforce now that the WSL line (and its separate version identity) is
    # retired: civiccast/_native_version.py must always agree with
    # civiccast/_version.py. Two product lines with two versions used to be
    # correct here; with one product line, identical versions are correct
    # and drift between the two files is the regression to catch.
    _require(
        native_source_version == version,
        (
            f"{_repo_path(native_version_file, root)} reports version "
            f"{native_source_version}, expected {version} "
            f"(from {_repo_path(version_file, root)}) -- there is one product "
            "line now and both files must agree."
        ),
        violations,
    )

    _require(
        f"OpenAPI schema, version `{version}`" in api_reference,
        f"{_repo_path(api_reference_path, root)} does not report OpenAPI version {version}.",
        violations,
    )
    _require(
        f"releases/tag/v{version}" in readme
        or (f"v{version}" in readme and held_candidate_marker in readme.lower()),
        (
            f"{_repo_path(readme_path, root)} neither links the current v{version} release "
            "nor identifies it as an owner-held unpublished candidate."
        ),
        violations,
    )
    if held_candidate:
        _require(
            "## [Unreleased]" in changelog and f"v{version}" in changelog,
            (
                f"{_repo_path(changelog_path, root)} must identify unpublished "
                f"candidate v{version} under [Unreleased]."
            ),
            violations,
        )
    else:
        _require(
            re.search(
                rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$",
                changelog,
                re.M,
            )
            is not None,
            f"{_repo_path(changelog_path, root)} is missing a dated [{version}] section.",
            violations,
        )
    _require(
        (f">v{version}<" in docs_index and f"releases/tag/v{version}" in docs_index)
        or (f"v{version}" in docs_index and held_candidate_marker in docs_index.lower()),
        (
            f"{_repo_path(docs_index_path, root)} neither shows/links latest tag v{version} "
            "nor identifies it as an owner-held unpublished candidate."
        ),
        violations,
    )
    # NOT required here. version_doc is the WSL line's release-verification
    # document and lives in docs/releases/, the archive this repository
    # deliberately did not carry across. The checks below that READ it are
    # already guarded by `if release_doc:`, so they simply do not run.
    _require(
        installer_version == version,
        (
            f"{_repo_path(installer_cargo_path, root)} reports installer version "
            f"{installer_version}, expected {version}."
        ),
        violations,
    )
    if technical_ops_reference:
        # TW-E: the /health example in the "Monitoring the running service"
        # section must show the version the running server actually reports.
        # A native station's /health reports civiccast/_native_version.py's
        # value (station_runtime sets CIVICCAST_NATIVE_REPORTED_VERSION from
        # it, and app.py's _reported_version() prefers it when set). Now
        # that native_source_version == version, checking against either
        # file is equivalent; anchored to native_source_version to keep the
        # check pointed at the value the running station actually reports.
        health_example = re.search(
            r'"status":"degraded","version":"([^"]+)"', technical_ops_reference
        )
        _require(
            health_example is not None and health_example.group(1) == native_source_version,
            (
                f"{_repo_path(technical_ops_reference_path, root)}'s /health example shows "
                f"version {health_example.group(1) if health_example else 'MISSING'!r}, "
                f"expected {native_source_version!r} (from civiccast/_native_version.py)."
            ),
            violations,
        )

    if release_doc:
        forbidden_phrases = (
            "intentionally not performed",
            "final approval before external publication",
            "Local branch state only",
        )
        for phrase in forbidden_phrases:
            _require(
                phrase not in release_doc,
                f"{_repo_path(version_doc, root)} still contains stale release-gate phrase: {phrase!r}.",
                violations,
            )
        _require(
            f"v{version}" in release_doc,
            f"{_repo_path(version_doc, root)} does not name v{version}.",
            violations,
        )

    # Runtime version literals the v0.2.0 cut missed (each one turned a
    # required CI check red): the operator console's on-screen-version e2e
    # mock. Same class as the rc1->rc4 CIVICAST_EXPECTED_VERSION cleanroom
    # failure — now machine-caught.
    _require(
        (
            root / "civiccast" / "apps" / "portal-operator" / "e2e" / "route-table-smoke.spec.ts"
        ).exists()
        and f"v{version}"
        in _read(
            root / "civiccast" / "apps" / "portal-operator" / "e2e" / "route-table-smoke.spec.ts"
        ),
        (
            f"civiccast/apps/portal-operator/e2e/route-table-smoke.spec.ts does not carry the "
            f"operator-console on-screen-version e2e expectation for {version}."
        ),
        violations,
    )

    # This repository's sole Tauri config must track civiccast/_version.py's
    # own version.
    _require(
        tauri_version == version,
        (
            f"{_repo_path(tauri_config_path, root)} reports product version "
            f"{tauri_version}, expected {version} (from civiccast/_version.py)."
        ),
        violations,
    )

    # The native Tauri overlay (tauri.native.conf.json) must also track
    # civiccast/_native_version.py's own version. Since the single-source
    # invariant above requires native_source_version == version, this is
    # equivalent to checking against `version` directly today, but stays
    # anchored to native_source_version so it still catches a drift in
    # tauri.native.conf.json specifically (as opposed to the two version
    # files disagreeing, which the check above already reports on its own).
    _require(
        native_version == native_source_version,
        (
            f"{_repo_path(native_tauri_config_path, root)} reports native product version "
            f"{native_version}, expected {native_source_version} "
            f"(from civiccast/_native_version.py)."
        ),
        violations,
    )
    main_rs_path = root / "civiccast" / "apps" / "installer" / "src-tauri" / "src" / "main.rs"
    _require(
        main_rs_path.exists()
        and f'CIVICCAST_VERSION: &str = "{native_source_version}"' in _read(main_rs_path),
        (
            f"{_repo_path(main_rs_path, root)} does not carry the installer Rust runtime "
            f"version constant for {native_source_version} (from civiccast/_native_version.py). "
            "This constant drives the installer's own post-install health verification and "
            "the real pack-trust expected_product_version/expected_compatible_core -- see "
            "civiccast.native.station_runtime.native_reported_version_environment for the "
            "matching runtime override that makes the native-hosted backend's /health agree."
        ),
        violations,
    )

    return violations


def main() -> int:
    violations = evaluate_release_identity()
    if violations:
        print("check_release_identity: FAIL")
        print("  violations:")
        for item in violations:
            print(f"    - {item}")
        return 1

    print(f"check_release_identity: PASS - release identity is aligned for v{_version()}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
