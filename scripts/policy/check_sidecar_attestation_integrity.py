#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Policy: release sidecar signing and attestation claims need real proof.

``_installer_artifact_entry`` in ``scripts/build_release_artifacts.py`` writes
a ``*.sidecar.json`` next to every release artifact. That sidecar may carry
a non-null ``attestation`` only when a real cosign bundle
(``*.sigstore.json``) sits next to the artifact. ``install_manifest.signed``
may additionally be true for a Windows PE with embedded Authenticode evidence.
This keeps the two claims distinct: signing does not fabricate an attestation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    from policy_utils import find_repo_root
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from scripts.policy.policy_utils import find_repo_root

REPO_ROOT = find_repo_root(__file__)

# Directories that legitimately contain huge trees we should never walk.
_SKIP_DIR_NAMES = {".git", ".venv", "venv", "node_modules", "target", "__pycache__"}


def _pe_has_authenticode_evidence(path: Path) -> bool:
    """Read embedded-certificate-table evidence without importing ambient packages.

    Cryptographic chain and timestamp validity remain the Windows release job's
    responsibility via ``Get-AuthenticodeSignature``.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return False
    if len(data) < 0x40 or data[:2] != b"MZ":
        return False
    e_lfanew = int.from_bytes(data[0x3C:0x40], "little")
    if len(data) < e_lfanew + 24 or data[e_lfanew : e_lfanew + 4] != b"PE\x00\x00":
        return False
    optional_header = e_lfanew + 24
    magic = int.from_bytes(data[optional_header : optional_header + 2], "little")
    if magic == 0x10B:
        data_directories = optional_header + 96
    elif magic == 0x20B:
        data_directories = optional_header + 112
    else:
        return False
    certificate_entry = data_directories + (4 * 8)
    if len(data) < certificate_entry + 8:
        return False
    certificate_offset = int.from_bytes(data[certificate_entry : certificate_entry + 4], "little")
    certificate_size = int.from_bytes(data[certificate_entry + 4 : certificate_entry + 8], "little")
    return (
        certificate_offset > 0
        and certificate_size > 0
        and certificate_offset + certificate_size <= len(data)
    )


def _iter_sidecars(root: Path):
    for path in root.rglob("*.sidecar.json"):
        if any(part in _SKIP_DIR_NAMES for part in path.parts):
            continue
        yield path


def _is_structurally_valid_sigstore_bundle(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, dict)
        and str(payload.get("mediaType", "")).startswith("application/vnd.dev.sigstore.bundle.")
        and isinstance(payload.get("verificationMaterial"), dict)
        and isinstance(payload.get("dsseEnvelope"), dict)
    )


def evaluate_sidecar_attestation_integrity(root: Path = REPO_ROOT) -> list[str]:
    """Return one violation string per unsupported signing/attestation claim."""

    violations: list[str] = []
    for sidecar in _iter_sidecars(root):
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            violations.append(f"{sidecar}: could not read/parse sidecar JSON: {exc}.")
            continue

        install_manifest = payload.get("install_manifest")
        signed = isinstance(install_manifest, dict) and install_manifest.get("signed") is True
        attestation = payload.get("attestation")

        if not signed and attestation is None:
            continue  # honest unsigned/unattested claim -- nothing to flag

        # Artifact name is the sidecar name with the trailing ".sidecar.json" stripped.
        artifact_name = sidecar.name[: -len(".sidecar.json")]
        artifact = sidecar.with_name(artifact_name)
        bundle = sidecar.with_name(artifact_name + ".sigstore.json")
        has_valid_bundle = _is_structurally_valid_sigstore_bundle(bundle)
        has_signing_proof = has_valid_bundle or (
            artifact.suffix.lower() == ".exe" and _pe_has_authenticode_evidence(artifact)
        )
        if signed and not has_signing_proof:
            violations.append(
                f"{sidecar.relative_to(root)}: claims install_manifest.signed=true but "
                "has neither a Sigstore bundle nor embedded Authenticode evidence."
            )
        if attestation is not None and not bundle.exists():
            violations.append(
                f"{sidecar.relative_to(root)}: claims attestation={attestation!r} but "
                f"{bundle.name} does not exist next to it."
            )
        elif attestation is not None and not has_valid_bundle:
            violations.append(
                f"{sidecar.relative_to(root)}: {bundle.name} is not a structurally valid "
                "Sigstore bundle."
            )
        elif attestation is not None and attestation != bundle.name:
            violations.append(
                f"{sidecar.relative_to(root)}: attestation={attestation!r} does not name "
                f"the adjacent {bundle.name}."
            )

    return violations


def main() -> int:
    violations = evaluate_sidecar_attestation_integrity()
    if violations:
        print("check_sidecar_attestation_integrity: FAIL")
        for item in violations:
            print(f"  - {item}")
        return 1

    print(
        "check_sidecar_attestation_integrity: PASS - signing/attestation claims "
        "have the required on-disk evidence structure."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
