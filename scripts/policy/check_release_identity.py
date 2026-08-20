#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Policy: release identity must agree before a tag candidate ships."""

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
# The WSL/mainline product line's own version (unchanged by native-windows
# chain J, 2026-08-02) -- this is what README.md, CHANGELOG.md, docs/index.html,
# docs/API-REFERENCE.md, the docs/releases verification doc, and Cargo.toml all
# still track below, exactly as before chain J.
VERSION_FILE = REPO_ROOT / "civiccast" / "_version.py"
# The NATIVE Windows product line's own, separate version (chain J). See
# civiccast/_native_version.py's module docstring for why this exists.
NATIVE_VERSION_FILE = REPO_ROOT / "civiccast" / "_native_version.py"
API_REFERENCE = REPO_ROOT / "docs" / "API-REFERENCE.md"
README = REPO_ROOT / "README.md"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
DOCS_INDEX = REPO_ROOT / "docs" / "index.html"
INSTALLER_CARGO = REPO_ROOT / "civiccast" / "apps" / "installer" / "src-tauri" / "Cargo.toml"
WSL_TAURI_CONFIG = REPO_ROOT / "civiccast" / "apps" / "installer" / "src-tauri" / "tauri.conf.json"
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
    wsl_tauri_config_path = (
        root / "civiccast" / "apps" / "installer" / "src-tauri" / "tauri.conf.json"
    )
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
    wsl_tauri_config = json.loads(_read(wsl_tauri_config_path))
    wsl_version = wsl_tauri_config.get("version")
    native_tauri_config = json.loads(_read(native_tauri_config_path))
    native_version = native_tauri_config.get("version")
    held_candidate_marker = "owner-held unpublished candidate"

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
    _require(
        re.search(rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$", changelog, re.M)
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
    _require(
        version_doc.exists(),
        f"{_repo_path(version_doc, root)} is missing.",
        violations,
    )
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
        # section must show the version the running server actually reports
        # (civiccast/app.py embeds __version__ verbatim in /health), not a
        # stale prior rc left behind by the last version bump.
        health_example = re.search(
            r'"status":"degraded","version":"([^"]+)"', technical_ops_reference
        )
        _require(
            health_example is not None and health_example.group(1) == version,
            (
                f"{_repo_path(technical_ops_reference_path, root)}'s /health example shows "
                f"version {health_example.group(1) if health_example else 'MISSING'!r}, "
                f"expected {version!r}."
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
    # failure — now machine-caught. This is a synthetic-mock test of shared
    # frontend rendering (it mocks /api/version directly), not a real
    # installer-identity surface, so it stays pinned to the WSL/mainline
    # `version` exactly as before chain J.
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

    # headless-bootstrap.ps1 is WSL-ONLY (native-windows chain J investigation,
    # 2026-08-02): bundled solely via the default tauri.conf.json's
    # `bundle.resources: ["resources/**/*"]`, referenced only by the WSL hook
    # file `nsis-hooks.nsh` (zero references from the native hook file
    # `nsis-hooks-bootstrap.nsh`). It is pinned against the WSL Tauri config's
    # own "version" (its true anchor) rather than the top-level `version`
    # directly -- the two happen to always agree today (nothing in chain J
    # changed the WSL line), but this is the more precise dependency and
    # matches the pattern the native checks below use for their own anchor.
    _require(
        wsl_version == version,
        (
            f"{_repo_path(wsl_tauri_config_path, root)} reports WSL product version "
            f"{wsl_version}, expected {version} (from civiccast/_version.py)."
        ),
        violations,
    )
    headless_bootstrap = (
        root
        / "civiccast"
        / "apps"
        / "installer"
        / "src-tauri"
        / "resources"
        / "headless-bootstrap.ps1"
    )
    _require(
        headless_bootstrap.exists()
        and f'$CivicCastVersion = "{wsl_version}"' in _read(headless_bootstrap),
        (
            f"{_repo_path(headless_bootstrap, root)} does not carry the bundled bootstrap "
            f"expected-version guard for the WSL product's own version {wsl_version} "
            f"(from {_repo_path(wsl_tauri_config_path, root)})."
        ),
        violations,
    )

    # The NATIVE Windows product line's own version surfaces (chain J,
    # 2026-08-02). civiccast/_native_version.py is their single source of
    # truth -- deliberately SEPARATE from civiccast/_version.py (the WSL
    # line's own identity, checked above and unchanged by chain J). See
    # civiccast/_native_version.py's module docstring for the full rationale:
    # in short, the two product lines used to share one version string ("two
    # rc15 installers" confused the project owner personally), and giving the
    # native line its own identity without disturbing a dozen-plus
    # WSL-specific policy checks and public docs required a second, distinct
    # version source rather than repointing the shared one.
    _require(
        native_version == native_source_version,
        (
            f"{_repo_path(native_tauri_config_path, root)} reports native product version "
            f"{native_version}, expected {native_source_version} "
            f"(from civiccast/_native_version.py)."
        ),
        violations,
    )
    _require(
        native_version != wsl_version,
        (
            f"{_repo_path(native_tauri_config_path, root)} reports the same version "
            f"({native_version}) as the WSL product's {_repo_path(wsl_tauri_config_path, root)} "
            f"({wsl_version}) -- the native and WSL product lines must never report an "
            "identical version string."
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
