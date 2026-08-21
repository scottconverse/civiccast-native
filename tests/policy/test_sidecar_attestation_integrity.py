# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the sidecar attestation integrity policy check.

ADR 0022: Sigstore/cosign keyless attestation was evaluated and denied for
this release chain. Azure Trusted Signing (Authenticode) is the only signing
mechanism a Windows artifact carries; nothing produces a ``.sigstore.json``
bundle any more, so a non-null ``attestation`` field is itself a violation,
and a ``signed: true`` claim is verified against real embedded Authenticode
evidence, never a bundle file.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.policy.check_sidecar_attestation_integrity import (
    evaluate_sidecar_attestation_integrity,
)


def _write_sidecar(root: Path, name: str, payload: dict) -> Path:
    path = root / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _signed_pe_bytes() -> bytes:
    """Return a minimal PE with a non-empty Authenticode certificate table."""
    buf = bytearray(0x400)
    e_lfanew = 0x80
    buf[0:2] = b"MZ"
    buf[0x3C:0x40] = e_lfanew.to_bytes(4, "little")
    buf[e_lfanew : e_lfanew + 4] = b"PE\x00\x00"
    optional_header = e_lfanew + 24
    buf[optional_header : optional_header + 2] = (0x10B).to_bytes(2, "little")
    certificate_table = optional_header + 96 + (4 * 8)
    buf[certificate_table : certificate_table + 4] = (0x300).to_bytes(4, "little")
    buf[certificate_table + 4 : certificate_table + 8] = (0x100).to_bytes(4, "little")
    return bytes(buf)


def test_passes_when_no_sidecars_exist(tmp_path: Path) -> None:
    assert evaluate_sidecar_attestation_integrity(tmp_path) == []


def test_plain_script_entrypoint_is_not_redirected_by_ambient_pythonpath(tmp_path: Path) -> None:
    poison = tmp_path / "scripts"
    poison.mkdir()
    (poison / "build_release_artifacts.py").write_text(
        "raise ImportError('ambient checkout won')\n", encoding="utf-8"
    )
    script = Path("scripts/policy/check_sidecar_attestation_integrity.py").resolve()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(tmp_path)

    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "check_sidecar_attestation_integrity: PASS" in result.stdout


def test_passes_when_unsigned_sidecar_has_null_attestation(tmp_path: Path) -> None:
    # Honest claim: nothing signed, no attestation mechanism exists.
    _write_sidecar(
        tmp_path,
        "civiccast-1.0.0-windows-setup.exe.sidecar.json",
        {
            "sha256": "0" * 64,
            "attestation": None,
            "install_manifest": {"signed": False},
        },
    )

    assert evaluate_sidecar_attestation_integrity(tmp_path) == []


def test_passes_when_authenticode_signed_sidecar_has_null_attestation(tmp_path: Path) -> None:
    artifact = tmp_path / "civiccast-1.0.0-windows-setup.exe"
    artifact.write_bytes(_signed_pe_bytes())
    _write_sidecar(
        tmp_path,
        artifact.name + ".sidecar.json",
        {
            "sha256": "0" * 64,
            "attestation": None,
            "install_manifest": {"signed": True},
        },
    )

    assert evaluate_sidecar_attestation_integrity(tmp_path) == []


def test_fails_when_unsigned_pe_claims_signed(tmp_path: Path) -> None:
    artifact = tmp_path / "civiccast-1.0.0-windows-setup.exe"
    artifact.write_bytes(b"unsigned executable bytes")
    sidecar = _write_sidecar(
        tmp_path,
        artifact.name + ".sidecar.json",
        {
            "sha256": "0" * 64,
            "attestation": None,
            "install_manifest": {"signed": True},
        },
    )

    violations = evaluate_sidecar_attestation_integrity(tmp_path)

    assert len(violations) == 1
    assert sidecar.name in violations[0]
    assert "no embedded Authenticode evidence" in violations[0]


def test_fails_when_non_exe_artifact_claims_signed(tmp_path: Path) -> None:
    sidecar = _write_sidecar(
        tmp_path,
        "civiccast-1.0.0-portable.tar.gz.sidecar.json",
        {
            "sha256": "0" * 64,
            "attestation": None,
            "install_manifest": {"signed": True},
        },
    )

    violations = evaluate_sidecar_attestation_integrity(tmp_path)

    assert len(violations) == 1
    assert sidecar.name in violations[0]
    assert "no embedded Authenticode evidence" in violations[0]


def test_fails_on_any_non_null_attestation_reference(tmp_path: Path) -> None:
    # ADR 0022: no code path may populate a non-null attestation any more --
    # this release chain has no attestation mechanism at all.
    sidecar = _write_sidecar(
        tmp_path,
        "civiccast-1.0.0-windows-setup.exe.sidecar.json",
        {
            "sha256": "0" * 64,
            "attestation": "sigstore://civiccast/civiccast-1.0.0-windows-setup.exe",
            "install_manifest": {"signed": False},
        },
    )

    violations = evaluate_sidecar_attestation_integrity(tmp_path)

    assert len(violations) == 1
    assert sidecar.name in violations[0]
    assert "the field must be null" in violations[0]


def test_fails_on_both_stray_attestation_and_fabricated_signed_claim(tmp_path: Path) -> None:
    # PE-ENG-1 shape: the artifact was never signed, but the sidecar claims
    # otherwise AND carries a stray attestation reference -- two violations.
    sidecar = _write_sidecar(
        tmp_path,
        "civiccast-1.0.0-windows-setup.exe.sidecar.json",
        {
            "sha256": "0" * 64,
            "attestation": "sigstore://civiccast/civiccast-1.0.0-windows-setup.exe",
            "install_manifest": {"signed": True},
        },
    )

    violations = evaluate_sidecar_attestation_integrity(tmp_path)

    assert len(violations) == 2
    assert all(sidecar.name in violation for violation in violations)
    assert any("the field must be null" in violation for violation in violations)
    assert any("no embedded Authenticode evidence" in violation for violation in violations)
