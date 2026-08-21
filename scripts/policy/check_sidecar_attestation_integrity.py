#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Policy: release sidecar signing claims need real proof.

A ``*.sidecar.json`` sits next to every release artifact. This repo's release
chain carries no cosign/Sigstore step anywhere (Azure Trusted Signing /
Authenticode is the only signing mechanism -- see ``CODE_SIGNING_POLICY.md``),
so a sidecar's ``attestation`` field is always ``null`` now; a non-null value
is itself a policy violation (a stray or fabricated attestation claim).
``install_manifest.signed`` may be ``true`` only for a Windows PE (``.exe``)
that genuinely carries an embedded Authenticode certificate table -- a bare
flag with no such evidence is rejected.
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

        if attestation is not None:
            # No code path produces a non-null attestation any more: this repo's
            # release chain carries no cosign/Sigstore step, and nothing
            # replaced the retired attest-blob mechanism. A non-null value is a
            # stray or fabricated claim, not honest evidence.
            violations.append(
                f"{sidecar.relative_to(root)}: attestation={attestation!r} but this "
                "release chain has no attestation mechanism (Azure Trusted Signing / "
                "Authenticode only); the field must be null."
            )

        if not signed:
            continue  # honest unsigned claim -- nothing to flag

        # Artifact name is the sidecar name with the trailing ".sidecar.json" stripped.
        artifact_name = sidecar.name[: -len(".sidecar.json")]
        artifact = sidecar.with_name(artifact_name)
        has_signing_proof = artifact.suffix.lower() == ".exe" and _pe_has_authenticode_evidence(
            artifact
        )
        if not has_signing_proof:
            violations.append(
                f"{sidecar.relative_to(root)}: claims install_manifest.signed=true but "
                "has no embedded Authenticode evidence (the only signing mechanism this "
                "release chain has)."
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
