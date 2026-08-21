# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for installer package artifacts and sidecars."""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path


def _signed_pe_bytes() -> bytes:
    """Return minimal bytes for a PE with a non-empty Authenticode certificate
    table (data directory index 4) -- the real, on-disk evidence this repo's
    release chain checks now that Sigstore/cosign is denied (ADR 0022)."""
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


class TestPackageArtifactValidation:
    """ADR 0022: Sigstore/cosign was evaluated and denied for this release
    chain. Azure Trusted Signing (Authenticode) is the only signing
    mechanism; verify_package_artifact checks real embedded Authenticode
    evidence for a Windows .exe, never a .sigstore.json bundle. Non-Windows
    package kinds have no code-signing mechanism at all, so a signed=true
    claim for one is rejected rather than trusted blind.
    """

    def test_package_accepts_real_hash_and_service_metadata_when_unsigned(
        self, tmp_path: Path
    ) -> None:
        packages = importlib.import_module("civiccast.installer.packages")
        artifact = tmp_path / "civiccast_1.0.0_all.deb"
        artifact.write_bytes(b"real package bytes")
        sidecar = tmp_path / "civiccast_1.0.0_all.deb.sidecar.json"
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        sidecar.write_text(
            json.dumps(
                {
                    "sha256": digest,
                    "attestation": None,
                    "install_manifest": {
                        "signed": False,
                        "service": {"manager": "systemd", "name": "civiccast"},
                        "bootstrap": {"package_kind": "deb"},
                    },
                }
            ),
            encoding="utf-8",
        )

        result = packages.verify_package_artifact(artifact, sidecar)

        assert result.status == "ok"
        assert result.sha256 == digest
        assert result.service_metadata.manager == "systemd"
        assert result.additional_services == []
        assert result.attestation is None

    def test_package_preserves_egress_supervision_metadata(self, tmp_path: Path) -> None:
        packages = importlib.import_module("civiccast.installer.packages")
        artifact = tmp_path / "civiccast_1.0.0_all.deb"
        artifact.write_bytes(b"real package bytes")
        sidecar = tmp_path / "civiccast_1.0.0_all.deb.sidecar.json"
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        sidecar.write_text(
            json.dumps(
                {
                    "sha256": digest,
                    "attestation": None,
                    "install_manifest": {
                        "signed": False,
                        "service": {"manager": "systemd", "name": "civiccast"},
                        "additional_services": [
                            {
                                "manager": "systemd",
                                "name": "civiccast-egress",
                                "service_name": "civiccast-egress@.service",
                                "host_service": False,
                                "restart_policy": "always",
                                "recovery_window_seconds": 22,
                            }
                        ],
                        "bootstrap": {"package_kind": "deb"},
                    },
                }
            ),
            encoding="utf-8",
        )

        result = packages.verify_package_artifact(artifact, sidecar)

        assert result.status == "ok"
        assert len(result.additional_services) == 1
        egress = result.additional_services[0]
        assert egress.service_name == "civiccast-egress@.service"
        assert egress.restart_policy == "always"
        assert egress.recovery_window_seconds == 22

    def test_package_rejects_missing_artifact_file(self, tmp_path: Path) -> None:
        packages = importlib.import_module("civiccast.installer.packages")
        sidecar = tmp_path / "missing.deb.sidecar.json"
        sidecar.write_text(
            json.dumps({"sha256": "0" * 64, "attestation": None}),
            encoding="utf-8",
        )

        result = packages.verify_package_artifact(tmp_path / "missing.deb", sidecar)

        assert result.status == "blocked"
        assert "missing.deb" in result.next_step
        assert "rebuild the package artifact" in result.next_step.lower()

    def test_package_rejects_hash_mismatch_from_real_bytes(self, tmp_path: Path) -> None:
        packages = importlib.import_module("civiccast.installer.packages")
        artifact = tmp_path / "civiccast.pkg"
        artifact.write_bytes(b"package bytes after corruption")
        sidecar = tmp_path / "civiccast.pkg.sidecar.json"
        sidecar.write_text(
            json.dumps(
                {
                    "sha256": hashlib.sha256(b"original package bytes").hexdigest(),
                    "attestation": None,
                    "install_manifest": {
                        "signed": False,
                        "service": {"manager": "launchd", "name": "civiccast"},
                        "bootstrap": {"package_kind": "pkg"},
                    },
                }
            ),
            encoding="utf-8",
        )

        result = packages.verify_package_artifact(artifact, sidecar)

        assert result.status == "blocked"
        assert result.reason == "hash_mismatch"

    def test_package_rejects_signed_true_claim_for_non_windows_kind(self, tmp_path: Path) -> None:
        # This product line has no code-signing mechanism for non-Windows
        # package kinds (portable archives, .deb, .rpm, .pkg): a signed=true
        # claim for one of those cannot be independently verified.
        packages = importlib.import_module("civiccast.installer.packages")
        artifact = tmp_path / "civiccast.tar.gz"
        artifact.write_bytes(b"portable bytes")
        sidecar = tmp_path / "civiccast.tar.gz.sidecar.json"
        sidecar.write_text(
            json.dumps(
                {
                    "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                    "install_manifest": {
                        "signed": True,
                        "service": {"manager": "container", "name": "civiccast"},
                        "bootstrap": {"package_kind": "portable"},
                    },
                }
            ),
            encoding="utf-8",
        )

        result = packages.verify_package_artifact(artifact, sidecar)

        assert result.status == "blocked"
        assert result.reason == "unsigned_artifact"

    def test_package_accepts_real_windows_exe_with_authenticode_evidence(
        self, tmp_path: Path
    ) -> None:
        packages = importlib.import_module("civiccast.installer.packages")
        artifact = tmp_path / "civiccast-1.0.0-windows-setup.exe"
        artifact.write_bytes(_signed_pe_bytes())
        sidecar = tmp_path / "civiccast-1.0.0-windows-setup.exe.sidecar.json"
        sidecar.write_text(
            json.dumps(
                {
                    "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                    "attestation": None,
                    "install_manifest": {
                        "signed": True,
                        "service": {"manager": "windows-scm", "name": "civiccast"},
                        "bootstrap": {"package_kind": "windows-tauri-exe"},
                    },
                }
            ),
            encoding="utf-8",
        )

        result = packages.verify_package_artifact(artifact, sidecar)

        assert result.status == "ok"
        assert result.reason == "verified"
        assert result.attestation == "authenticode"

    def test_package_rejects_windows_exe_claiming_signed_without_authenticode_evidence(
        self, tmp_path: Path
    ) -> None:
        packages = importlib.import_module("civiccast.installer.packages")
        artifact = tmp_path / "civiccast-1.0.0-windows-setup.exe"
        artifact.write_bytes(b"unsigned executable bytes")
        sidecar = tmp_path / "civiccast-1.0.0-windows-setup.exe.sidecar.json"
        sidecar.write_text(
            json.dumps(
                {
                    "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                    "attestation": None,
                    "install_manifest": {
                        "signed": True,
                        "service": {"manager": "windows-scm", "name": "civiccast"},
                        "bootstrap": {"package_kind": "windows-tauri-exe"},
                    },
                }
            ),
            encoding="utf-8",
        )

        result = packages.verify_package_artifact(artifact, sidecar)

        assert result.status == "blocked"
        assert result.reason == "unsigned_artifact"

    def test_package_rejects_invalid_additional_service_metadata(self, tmp_path: Path) -> None:
        packages = importlib.import_module("civiccast.installer.packages")
        artifact = tmp_path / "civiccast.deb"
        artifact.write_bytes(b"package bytes")
        sidecar = tmp_path / "civiccast.deb.sidecar.json"
        sidecar.write_text(
            json.dumps(
                {
                    "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                    "attestation": None,
                    "install_manifest": {
                        "signed": False,
                        "service": {"manager": "systemd", "name": "civiccast"},
                        "additional_services": ["civiccast-egress@.service"],
                        "bootstrap": {"package_kind": "deb"},
                    },
                }
            ),
            encoding="utf-8",
        )

        result = packages.verify_package_artifact(artifact, sidecar)

        assert result.status == "blocked"
        assert result.reason == "invalid_sidecar"


def test_direct_tauri_bundle_script_fails_closed_when_runtime_payload_is_absent() -> None:
    package = json.loads(
        (Path("civiccast") / "apps" / "installer" / "package.json").read_text(encoding="utf-8")
    )

    command = package["scripts"]["tauri:build"]

    assert "verify-bundle-resources" in command


def test_bundle_resource_guard_checks_only_the_native_bootstrap_manifest() -> None:
    guard = (
        Path("civiccast") / "apps" / "installer" / "scripts" / "verify-bundle-resources.mjs"
    ).read_text(encoding="utf-8")

    assert '"bootstrap-manifest.json"' in guard
    # The retired WSL2 lane's Linux wheelhouse/GStreamer bundle requirement
    # must not come back -- nothing in the shipped app reads it.
    assert '"wheelhouse/WHEELHOUSE-MANIFEST.json"' not in guard
    assert "gstreamer-runtime-linux-x86_64.tar.gz" not in guard


def test_python_sdist_excludes_local_build_and_release_artifact_caches() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    sdist = pyproject.split("[tool.hatch.build.targets.sdist]", 1)[1].split(
        "[tool.hatch.build.targets.wheel]", 1
    )[0]

    assert '"/target"' in sdist
    assert '"/artifacts"' in sdist
    assert '"/civiccast/apps/installer/src-tauri/target"' in sdist
