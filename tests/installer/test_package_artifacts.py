# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for installer package artifacts, sidecars, and release builders."""

from __future__ import annotations

import base64
import hashlib
import importlib
import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest


def _write_minimal_gstreamer_runtime(runtime_dir: Path) -> None:
    archive = runtime_dir / "gstreamer-runtime-linux-x86_64.tar.gz"
    required_files = {
        "gstreamer/bin/gst-inspect-1.0": b"#!/bin/sh\n",
        "gstreamer/lib/x86_64-linux-gnu/gstreamer-1.0/libgstrsclosedcaption.so": b"plugin",
        "gstreamer/libexec/gstreamer-1.0/gst-plugin-scanner": b"scanner",
    }
    with tarfile.open(archive, "w:gz") as tar:
        for name, data in required_files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (runtime_dir / "gstreamer-runtime-linux-x86_64.tar.gz.sha256").write_text(
        f"{digest}  gstreamer-runtime-linux-x86_64.tar.gz\n",
        encoding="utf-8",
    )


def _write_attestation_bundle(
    artifact: Path, *, subject_sha256: str | None = None, base64_mod=None
) -> Path:
    """Write a cosign-shaped Sigstore bundle whose DSSE in-toto payload names
    the artifact's bytes (or an arbitrary digest, for mismatch fixtures)."""
    import base64 as _base64

    b64 = base64_mod or _base64
    digest = subject_sha256 or hashlib.sha256(artifact.read_bytes()).hexdigest()
    statement = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": artifact.name, "digest": {"sha256": digest}}],
        "predicateType": "https://civiccast.example/release-proof",
        "predicate": {"release": "test"},
    }
    bundle = {
        "mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json",
        "verificationMaterial": {"certificate": {"rawBytes": "dGVzdA=="}},
        "dsseEnvelope": {
            "payload": b64.b64encode(json.dumps(statement).encode()).decode(),
            "payloadType": "application/vnd.in-toto+json",
            "signatures": [{"sig": "dGVzdC1zaWduYXR1cmU="}],
        },
    }
    bundle_path = artifact.with_name(artifact.name + ".sigstore.json")
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    return bundle_path


def test_runtime_resource_build_id_tracks_exact_staged_bytes(tmp_path: Path) -> None:
    builder = importlib.import_module("scripts.build_release_artifacts")
    resources = tmp_path / "resources"
    (resources / "wheelhouse").mkdir(parents=True)
    wheel = resources / "wheelhouse" / "civiccast.whl"
    wheel.write_bytes(b"first runtime")

    first = builder._runtime_resource_build_id(resources)
    (resources / "bootstrap-manifest.json").write_text("ignored", encoding="utf-8")
    assert builder._runtime_resource_build_id(resources) == first

    wheel.write_bytes(b"different runtime")
    second = builder._runtime_resource_build_id(resources)
    assert len(first) == 64
    assert second != first


class TestPackageArtifactValidation:
    def test_package_accepts_real_hash_and_service_metadata_when_attested(
        self, tmp_path: Path
    ) -> None:
        packages = importlib.import_module("civiccast.installer.packages")
        artifact = tmp_path / "civiccast_1.0.0_all.deb"
        artifact.write_bytes(b"real package bytes")
        _write_attestation_bundle(artifact)
        sidecar = tmp_path / "civiccast_1.0.0_all.deb.sidecar.json"
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        sidecar.write_text(
            json.dumps(
                {
                    "sha256": digest,
                    "attestation": "https://github.com/scottconverse/CivicCast/attestations/1",
                    "install_manifest": {
                        "signed": True,
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

    def test_package_preserves_egress_supervision_metadata(self, tmp_path: Path) -> None:
        packages = importlib.import_module("civiccast.installer.packages")
        artifact = tmp_path / "civiccast_1.0.0_all.deb"
        artifact.write_bytes(b"real package bytes")
        _write_attestation_bundle(artifact)
        sidecar = tmp_path / "civiccast_1.0.0_all.deb.sidecar.json"
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        sidecar.write_text(
            json.dumps(
                {
                    "sha256": digest,
                    "attestation": "sigstore://example",
                    "install_manifest": {
                        "signed": True,
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
            json.dumps({"sha256": "0" * 64, "attestation": "sigstore://example"}),
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
                    "attestation": "sigstore://example",
                    "install_manifest": {
                        "signed": True,
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

    def test_package_rejects_missing_attestation_reference(self, tmp_path: Path) -> None:
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
        assert result.reason == "missing_attestation"

    def test_signed_false_sidecar_with_real_bundle_verifies_ok(self, tmp_path: Path) -> None:
        """NF-2: the release pipeline writes sidecars BEFORE cosign runs, so a
        genuinely-attested artifact ships with signed:false in its sidecar.
        Verification must trust the real bundle on disk, not that stale flag."""
        packages = importlib.import_module("civiccast.installer.packages")
        artifact = tmp_path / "civiccast.rpm"
        artifact.write_bytes(b"rpm bytes")
        _write_attestation_bundle(artifact)
        sidecar = tmp_path / "civiccast.rpm.sidecar.json"
        sidecar.write_text(
            json.dumps(
                {
                    "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                    "attestation": None,
                    "install_manifest": {
                        "signed": False,
                        "service": {"manager": "systemd", "name": "civiccast"},
                        "bootstrap": {"package_kind": "rpm"},
                    },
                }
            ),
            encoding="utf-8",
        )

        result = packages.verify_package_artifact(artifact, sidecar)

        assert result.status == "ok"
        assert result.reason == "verified"
        assert result.attestation == "civiccast.rpm.sigstore.json"

    def test_package_rejects_bundle_attesting_different_bytes(self, tmp_path: Path) -> None:
        packages = importlib.import_module("civiccast.installer.packages")
        artifact = tmp_path / "civiccast.rpm"
        artifact.write_bytes(b"rpm bytes")
        _write_attestation_bundle(artifact, subject_sha256="a" * 64)
        sidecar = tmp_path / "civiccast.rpm.sidecar.json"
        sidecar.write_text(
            json.dumps(
                {
                    "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                    "install_manifest": {
                        "signed": False,
                        "service": {"manager": "systemd", "name": "civiccast"},
                        "bootstrap": {"package_kind": "rpm"},
                    },
                }
            ),
            encoding="utf-8",
        )

        result = packages.verify_package_artifact(artifact, sidecar)

        assert result.status == "blocked"
        assert result.reason == "attestation_mismatch"

    def test_package_rejects_malformed_attestation_bundle(self, tmp_path: Path) -> None:
        packages = importlib.import_module("civiccast.installer.packages")
        artifact = tmp_path / "civiccast.rpm"
        artifact.write_bytes(b"rpm bytes")
        (tmp_path / "civiccast.rpm.sigstore.json").write_text(
            json.dumps({"mediaType": "x", "no_envelope": True}), encoding="utf-8"
        )
        sidecar = tmp_path / "civiccast.rpm.sidecar.json"
        sidecar.write_text(
            json.dumps(
                {
                    "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                    "install_manifest": {
                        "signed": False,
                        "service": {"manager": "systemd", "name": "civiccast"},
                        "bootstrap": {"package_kind": "rpm"},
                    },
                }
            ),
            encoding="utf-8",
        )

        result = packages.verify_package_artifact(artifact, sidecar)

        assert result.status == "blocked"
        assert result.reason == "invalid_attestation"

    def test_package_rejects_invalid_additional_service_metadata(self, tmp_path: Path) -> None:
        packages = importlib.import_module("civiccast.installer.packages")
        artifact = tmp_path / "civiccast.deb"
        artifact.write_bytes(b"package bytes")
        _write_attestation_bundle(artifact)
        sidecar = tmp_path / "civiccast.deb.sidecar.json"
        sidecar.write_text(
            json.dumps(
                {
                    "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                    "attestation": "sigstore://example",
                    "install_manifest": {
                        "signed": True,
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


class TestReleaseArtifactBuilderContracts:
    def test_rpm_version_fields_keep_beta_version_rpm_safe(self) -> None:
        builder = importlib.import_module("scripts.build_release_artifacts")

        assert builder._rpm_version_fields("3.0.0-beta1") == (
            "3.0.0",
            "1.beta1",
            "3.0.0-1.beta1",
        )
        assert builder._rpm_version_fields("3.0.0") == ("3.0.0", "1", "3.0.0")

    def test_source_archive_skips_transient_agent_run_state(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        builder = importlib.import_module("scripts.build_release_artifacts")
        root = tmp_path / "repo"
        root.mkdir()
        readme = root / "README.md"
        readme.write_text("source\n", encoding="utf-8")
        removed_receipt = root / ".agent-runs" / "run" / "scope-lock-receipt.txt"

        monkeypatch.setattr(builder, "ROOT", root)
        monkeypatch.setattr(builder, "_git_files", lambda: [readme, removed_receipt])

        artifact = builder.build_source_archive(tmp_path / "out", "3.0.0-beta1")

        with tarfile.open(artifact.path, "r:gz") as tar:
            names = {member.name for member in tar.getmembers()}

        assert "civiccast-3.0.0-beta1/README.md" in names
        assert not any(".agent-runs" in name for name in names)

    def test_source_archive_rejects_missing_real_source_file(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        builder = importlib.import_module("scripts.build_release_artifacts")
        root = tmp_path / "repo"
        root.mkdir()
        missing_source = root / "civiccast" / "missing.py"

        monkeypatch.setattr(builder, "ROOT", root)
        monkeypatch.setattr(builder, "_git_files", lambda: [missing_source])

        try:
            builder.build_source_archive(tmp_path / "out", "3.0.0-beta1")
        except FileNotFoundError as exc:
            assert "civiccast/missing.py" in str(exc)
        else:
            raise AssertionError("missing source file should block release archive")

    def test_builder_represents_native_portable_and_blocked_tooling_entries(
        self, tmp_path: Path
    ) -> None:
        builder = importlib.import_module("scripts.build_release_artifacts")

        manifest = builder.build_cross_platform_installer_artifacts(
            tmp_path,
            version="1.0.0",
            available_tools={
                "dpkg-deb": False,
                "rpmbuild": False,
                "pkgbuild": False,
                "tauri": False,
            },
        )

        kinds = {entry["kind"] for entry in manifest["artifacts"]}
        assert {
            "macos-pkg",
            "windows-tauri-installer",
            "portable-archive",
        } <= kinds
        # Guard the removals, not just the survivors: deb-package, rpm-package,
        # windows-wsl2-bootstrap-manifest and container-manifest went with the
        # Linux/WSL2/Docker lanes. A manifest that advertises an artifact this
        # product cannot build is worse than one that omits it.
        assert not ({
            "deb-package",
            "rpm-package",
            "windows-wsl2-bootstrap-manifest",
            "container-manifest",
        } & kinds)
        assert all(entry["sha256"] for entry in manifest["artifacts"] if entry["status"] == "ok")
        assert all(entry["sidecar"] for entry in manifest["artifacts"] if entry["status"] == "ok")
        assert any(entry["status"] == "blocked" for entry in manifest["artifacts"])
        assert any(
            "tooling unavailable" in entry["proof"].lower() for entry in manifest["artifacts"]
        )
        # Was: read the WSL2 bootstrap manifest's sidecar and assert it
        # registered a civiccast-egress@.service systemd unit. Both the entry
        # and that unit are gone. The portable archive is the one entry here
        # that is always built regardless of available tooling, so it is what
        # this assertion can rely on.
        portable_entry = next(
            entry for entry in manifest["artifacts"] if entry["kind"] == "portable-archive"
        )
        sidecar = tmp_path / str(portable_entry["sidecar"])
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        install_manifest = payload["install_manifest"]
        # A native station supervises egress as a child of the Windows service,
        # so there is no second registered service to declare.
        assert install_manifest["additional_services"] == []
        assert install_manifest["service"]["manager"] == "none"

    def test_builder_wheelhouse_manifest_hashes_application_and_dependency_wheels(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        builder = importlib.import_module("scripts.build_release_artifacts")
        app_wheel = tmp_path / "civiccast-1.1.1-py3-none-any.whl"
        app_wheel.write_bytes(b"stale app wheel")

        def fake_build_python_artifacts(out_dir: Path) -> list[object]:
            fresh_wheel = out_dir / "civiccast-1.1.1-py3-none-any.whl"
            fresh_wheel.write_bytes(b"fresh app wheel")
            return [builder.Artifact(fresh_wheel, "python-package")]

        def fake_run(cmd: list[str], *, cwd=builder.ROOT) -> None:
            if "export" in cmd:
                output = Path(cmd[cmd.index("--output-file") + 1])
                output.write_text("fastapi==0.1\n", encoding="utf-8")
                return
            if "download" in cmd:
                dest = Path(cmd[cmd.index("--dest") + 1])
                (dest / "fastapi-0.1-py3-none-any.whl").write_bytes(b"dependency wheel")
                return
            raise AssertionError(f"unexpected command: {cmd}")

        monkeypatch.setattr(builder, "build_python_artifacts", fake_build_python_artifacts)
        monkeypatch.setattr(builder, "_run", fake_run)
        monkeypatch.setattr(builder, "_python_with_pip_command", lambda: ["python"])

        artifact = builder.build_python_wheelhouse(tmp_path, "1.1.1")

        payload = json.loads(artifact.path.read_text(encoding="utf-8"))
        filenames = {entry["filename"] for entry in payload["wheels"]}
        assert filenames == {
            "civiccast-1.1.1-py3-none-any.whl",
            "fastapi-0.1-py3-none-any.whl",
        }
        assert all(entry["sha256"] for entry in payload["wheels"])
        assert (tmp_path / "wheelhouse" / "requirements.txt").exists()
        assert (
            tmp_path / "wheelhouse" / "civiccast-1.1.1-py3-none-any.whl"
        ).read_bytes() == b"fresh app wheel"

    def test_builder_wheelhouse_accepts_pep440_normalized_prerelease_wheel(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        builder = importlib.import_module("scripts.build_release_artifacts")

        def fake_build_python_artifacts(out_dir: Path) -> list[object]:
            wheel = out_dir / "civiccast-3.0.0b1-py3-none-any.whl"
            wheel.write_bytes(b"beta app wheel")
            return [builder.Artifact(wheel, "python-package")]

        def fake_run(cmd: list[str], *, cwd=builder.ROOT) -> None:
            if "export" in cmd:
                output = Path(cmd[cmd.index("--output-file") + 1])
                output.write_text("fastapi==0.1\n", encoding="utf-8")
                return
            if "download" in cmd:
                dest = Path(cmd[cmd.index("--dest") + 1])
                (dest / "fastapi-0.1-py3-none-any.whl").write_bytes(b"dependency wheel")
                return
            raise AssertionError(f"unexpected command: {cmd}")

        monkeypatch.setattr(builder, "build_python_artifacts", fake_build_python_artifacts)
        monkeypatch.setattr(builder, "_run", fake_run)
        monkeypatch.setattr(builder, "_python_with_pip_command", lambda: ["python"])

        artifact = builder.build_python_wheelhouse(tmp_path, "3.0.0-beta1")

        payload = json.loads(artifact.path.read_text(encoding="utf-8"))
        filenames = {entry["filename"] for entry in payload["wheels"]}
        assert "civiccast-3.0.0b1-py3-none-any.whl" in filenames
        assert "wheelhouse/civiccast-3.0.0b1-py3-none-any.whl" in payload["install_command"]

    def test_builder_wheelhouse_rejects_mismatched_application_wheel_version(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        builder = importlib.import_module("scripts.build_release_artifacts")

        def fake_build_python_artifacts(out_dir: Path) -> list[object]:
            wheel = out_dir / "civiccast-3.3.0-py3-none-any.whl"
            wheel.write_bytes(b"old app wheel")
            return [builder.Artifact(wheel, "python-package")]

        monkeypatch.setattr(builder, "build_python_artifacts", fake_build_python_artifacts)

        try:
            builder.build_python_wheelhouse(tmp_path, "4.0.0-rc.2")
        except RuntimeError as exc:
            assert "application wheel for CivicCast 4.0.0-rc.2 was not produced" in str(exc)
            assert "civiccast-3.3.0-py3-none-any.whl" in str(exc)
        else:
            raise AssertionError("mismatched application wheel should block release packaging")

    def test_builder_windows_installer_refreshes_wheelhouse_before_packaging(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        builder = importlib.import_module("scripts.build_release_artifacts")
        calls: list[str] = []

        def artifact(path: Path, kind: str) -> object:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(kind.encode("ascii"))
            return builder.Artifact(path, kind)

        monkeypatch.setattr(
            builder,
            "build_source_archive",
            lambda out_dir, version: artifact(
                out_dir / f"civiccast-{version}-source.tar.gz", "source-tarball"
            ),
        )
        monkeypatch.setattr(
            builder,
            "build_model_manifest",
            lambda out_dir, version: artifact(
                out_dir / f"civiccast-{version}-model-bundle-manifest.json", "model-bundle-manifest"
            ),
        )
        monkeypatch.setattr(
            builder,
            "build_container_manifest",
            lambda out_dir, version: artifact(
                out_dir / f"civiccast-{version}-container-manifest.json", "container-manifest"
            ),
        )

        def fake_wheelhouse(out_dir: Path, version: str) -> object:
            calls.append("wheelhouse")
            return artifact(
                out_dir / "wheelhouse" / "WHEELHOUSE-MANIFEST.json", "python-wheelhouse-manifest"
            )

        def fake_installer(out_dir: Path, version: str, *, reuse_existing: bool = False) -> object:
            calls.append("installer")
            return artifact(
                out_dir / f"civiccast-{version}-windows-setup.exe", "windows-tauri-installer"
            )

        def fake_tester_package(out_dir: Path, version: str, windows_installer: object) -> object:
            calls.append("tester-package")
            return artifact(
                out_dir / f"civiccast-{version}-windows-tester-package.zip",
                "windows-tester-package",
            )

        def fake_proof_kit(out_dir: Path, version: str, windows_installer: object) -> object:
            calls.append("proof-kit")
            return artifact(
                out_dir / f"civiccast-{version}-clean-windows-proof-kit.zip",
                "clean-windows-proof-kit",
            )

        monkeypatch.setattr(builder, "build_python_wheelhouse", fake_wheelhouse)
        monkeypatch.setattr(builder, "build_windows_tauri_installer", fake_installer)
        monkeypatch.setattr(builder, "build_windows_tester_package", fake_tester_package)
        monkeypatch.setattr(builder, "build_clean_windows_proof_kit", fake_proof_kit)
        monkeypatch.setattr(
            builder.sys,
            "argv",
            [
                "build_release_artifacts.py",
                "--version",
                "1.3.0",
                "--out-dir",
                str(tmp_path),
                "--windows-installer",
            ],
        )

        assert builder.main() == 0
        assert calls[:2] == ["wheelhouse", "installer"]

    def test_builder_windows_tauri_installer_copies_real_build_output(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        builder = importlib.import_module("scripts.build_release_artifacts")
        fake_root = tmp_path / "repo"
        built = (
            fake_root
            / "civiccast"
            / "apps"
            / "installer"
            / "src-tauri"
            / "target"
            / "release"
            / "bundle"
            / "nsis"
            / "CivicCast Installer_1.2.0_x64-setup.exe"
        )
        built.parent.mkdir(parents=True, exist_ok=True)
        built.write_bytes(b"real tauri setup bytes")
        wheelhouse = tmp_path / "wheelhouse"
        wheelhouse.mkdir()
        (wheelhouse / "WHEELHOUSE-MANIFEST.json").write_text(
            json.dumps({"wheels": []}),
            encoding="utf-8",
        )
        (wheelhouse / "civiccast-1.2.0-py3-none-any.whl").write_bytes(b"wheel")
        gstreamer_runtime = tmp_path / "gstreamer-runtime"
        gstreamer_runtime.mkdir()
        _write_minimal_gstreamer_runtime(gstreamer_runtime)

        calls: list[tuple[list[str], Path]] = []

        def fake_run(cmd: list[str], *, cwd=builder.ROOT) -> None:
            calls.append((cmd, Path(cwd)))

        monkeypatch.setattr(builder, "_run", fake_run)
        monkeypatch.setattr(builder, "_npm_command", lambda: ["npm"])
        monkeypatch.setattr(builder.sys, "platform", "win32")
        monkeypatch.setattr(builder, "ROOT", fake_root)

        artifact = builder.build_windows_tauri_installer(tmp_path, "1.2.0")

        assert artifact.kind == "windows-tauri-installer"
        assert artifact.path.name == "civiccast-1.2.0-windows-setup.exe"
        assert artifact.path.read_bytes() == b"real tauri setup bytes"
        assert calls == [
            (
                ["npm", "run", "tauri:build"],
                fake_root / "civiccast" / "apps" / "installer",
            )
        ]

    def test_reuse_installer_exe_regenerates_sidecar_from_existing_binary(
        self, tmp_path: Path
    ) -> None:
        # Issue #253: with reuse_existing the Tauri build is skipped and the
        # sidecar is regenerated from the .exe already on disk -- so after the
        # workflow signs the .exe, the sidecar hashes the SIGNED bytes.
        builder = importlib.import_module("scripts.build_release_artifacts")
        version = "9.9.9-rc9"
        exe = tmp_path / f"civiccast-{version}-windows-setup.exe"
        exe.write_bytes(b"pretend signed installer bytes")
        expected = builder._sha256(exe)

        artifact = builder.build_windows_tauri_installer(tmp_path, version, reuse_existing=True)

        assert artifact.path == exe
        assert exe.read_bytes() == b"pretend signed installer bytes"  # never rewritten
        sidecar = json.loads((tmp_path / f"{exe.name}.sidecar.json").read_text())
        assert sidecar["sha256"] == expected

    def test_reuse_installer_exe_requires_an_existing_binary(self, tmp_path: Path) -> None:
        builder = importlib.import_module("scripts.build_release_artifacts")
        with pytest.raises(RuntimeError, match="reuse-installer-exe"):
            builder.build_windows_tauri_installer(tmp_path, "9.9.9-rc9", reuse_existing=True)

    def test_builder_windows_tauri_installer_writes_honest_unsigned_sidecar(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        builder = importlib.import_module("scripts.build_release_artifacts")
        packages = importlib.import_module("civiccast.installer.packages")
        fake_root = tmp_path / "repo"
        built = (
            fake_root
            / "civiccast"
            / "apps"
            / "installer"
            / "src-tauri"
            / "target"
            / "release"
            / "bundle"
            / "nsis"
            / "CivicCast Installer_4.0.0-rc.2_x64-setup.exe"
        )
        built.parent.mkdir(parents=True, exist_ok=True)
        built.write_bytes(b"real tauri setup bytes")
        wheelhouse = tmp_path / "wheelhouse"
        wheelhouse.mkdir()
        (wheelhouse / "WHEELHOUSE-MANIFEST.json").write_text(
            json.dumps({"wheels": []}),
            encoding="utf-8",
        )
        (wheelhouse / "civiccast-4.0.0rc2-py3-none-any.whl").write_bytes(b"wheel")
        gstreamer_runtime = tmp_path / "gstreamer-runtime"
        gstreamer_runtime.mkdir()
        _write_minimal_gstreamer_runtime(gstreamer_runtime)

        monkeypatch.setattr(builder, "_run", lambda cmd, *, cwd=builder.ROOT: None)
        monkeypatch.setattr(builder, "_npm_command", lambda: ["npm"])
        monkeypatch.setattr(builder.sys, "platform", "win32")
        monkeypatch.setattr(builder, "ROOT", fake_root)

        artifact = builder.build_windows_tauri_installer(tmp_path, "4.0.0-rc.2")
        sidecar = artifact.path.with_name(artifact.path.name + ".sidecar.json")
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        result = packages.verify_package_artifact(artifact.path, sidecar)

        # No real cosign attestation bundle exists next to the artifact (it is
        # only created by a separate `cosign attest-blob` CI step, and the
        # Windows job runs no such step at all) -- the sidecar must say so
        # honestly rather than fabricate signed:true / a sigstore:// claim.
        assert payload["sha256"] == hashlib.sha256(b"real tauri setup bytes").hexdigest()
        assert payload["install_manifest"]["bootstrap"]["package_kind"] == "windows-tauri-exe"
        assert payload["install_manifest"]["signed"] is False
        assert payload["attestation"] is None
        assert result.status == "blocked"
        assert result.ready is False
        assert result.reason == "missing_attestation"

    def test_builder_windows_tauri_installer_references_real_sigstore_bundle_when_present(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        builder = importlib.import_module("scripts.build_release_artifacts")
        packages = importlib.import_module("civiccast.installer.packages")
        fake_root = tmp_path / "repo"
        built = (
            fake_root
            / "civiccast"
            / "apps"
            / "installer"
            / "src-tauri"
            / "target"
            / "release"
            / "bundle"
            / "nsis"
            / "CivicCast Installer_4.0.0-rc.2_x64-setup.exe"
        )
        built.parent.mkdir(parents=True, exist_ok=True)
        built.write_bytes(b"real tauri setup bytes")
        wheelhouse = tmp_path / "wheelhouse"
        wheelhouse.mkdir()
        (wheelhouse / "WHEELHOUSE-MANIFEST.json").write_text(
            json.dumps({"wheels": []}),
            encoding="utf-8",
        )
        (wheelhouse / "civiccast-4.0.0rc2-py3-none-any.whl").write_bytes(b"wheel")
        gstreamer_runtime = tmp_path / "gstreamer-runtime"
        gstreamer_runtime.mkdir()
        _write_minimal_gstreamer_runtime(gstreamer_runtime)

        monkeypatch.setattr(builder, "_run", lambda cmd, *, cwd=builder.ROOT: None)
        monkeypatch.setattr(builder, "_npm_command", lambda: ["npm"])
        monkeypatch.setattr(builder.sys, "platform", "win32")
        monkeypatch.setattr(builder, "ROOT", fake_root)

        # Simulate a real cosign attest-blob bundle already sitting on disk
        # next to where the artifact will be copied, e.g. a rerun after CI
        # signing already happened. The bundle's DSSE in-toto subject digest
        # must name the built artifact's bytes (the builder copies `built`),
        # so verify_package_artifact's real-bundle check accepts it.
        target = tmp_path / "civiccast-4.0.0-rc.2-windows-setup.exe"
        built_digest = hashlib.sha256(built.read_bytes()).hexdigest()
        statement = {
            "_type": "https://in-toto.io/Statement/v1",
            "subject": [{"name": target.name, "digest": {"sha256": built_digest}}],
            "predicateType": "https://civiccast.example/release-proof",
            "predicate": {"release": "test"},
        }
        (tmp_path / (target.name + ".sigstore.json")).write_text(
            json.dumps(
                {
                    "mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json",
                    "dsseEnvelope": {
                        "payload": base64.b64encode(json.dumps(statement).encode()).decode(),
                        "payloadType": "application/vnd.in-toto+json",
                        "signatures": [{"sig": "dGVzdC1zaWduYXR1cmU="}],
                    },
                }
            ),
            encoding="utf-8",
        )

        artifact = builder.build_windows_tauri_installer(tmp_path, "4.0.0-rc.2")
        sidecar = artifact.path.with_name(artifact.path.name + ".sidecar.json")
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        result = packages.verify_package_artifact(artifact.path, sidecar)

        assert payload["install_manifest"]["signed"] is True
        assert payload["attestation"] == artifact.path.name + ".sigstore.json"
        assert result.status == "ok"
        assert result.ready is True

    def test_builder_windows_tauri_installer_aligns_tauri_metadata_for_release_version(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        builder = importlib.import_module("scripts.build_release_artifacts")
        fake_root = tmp_path / "repo"
        installer_dir = fake_root / "civiccast" / "apps" / "installer"
        tauri_dir = installer_dir / "src-tauri"
        tauri_dir.mkdir(parents=True)
        (tauri_dir / "tauri.conf.json").write_text(
            json.dumps({"productName": "CivicCast Installer", "version": "3.3.0"}),
            encoding="utf-8",
        )
        (installer_dir / "package.json").write_text(
            json.dumps({"name": "@civiccast/installer", "version": "3.3.0"}),
            encoding="utf-8",
        )
        (installer_dir / "package-lock.json").write_text(
            json.dumps(
                {
                    "name": "@civiccast/installer",
                    "version": "3.3.0",
                    "packages": {"": {"name": "@civiccast/installer", "version": "3.3.0"}},
                }
            ),
            encoding="utf-8",
        )
        (tauri_dir / "Cargo.toml").write_text(
            '[package]\nname = "civiccast-installer"\nversion = "3.3.0"\n',
            encoding="utf-8",
        )
        wheelhouse = tmp_path / "wheelhouse"
        wheelhouse.mkdir()
        (wheelhouse / "WHEELHOUSE-MANIFEST.json").write_text(
            json.dumps({"wheels": []}),
            encoding="utf-8",
        )
        (wheelhouse / "civiccast-4.0.0-rc1-py3-none-any.whl").write_bytes(b"wheel")
        gstreamer_runtime = tmp_path / "gstreamer-runtime"
        gstreamer_runtime.mkdir()
        _write_minimal_gstreamer_runtime(gstreamer_runtime)

        def fake_run(cmd: list[str], *, cwd=builder.ROOT) -> None:
            assert json.loads((tauri_dir / "tauri.conf.json").read_text())["version"] == "4.0.0-rc1"
            assert (
                json.loads((installer_dir / "package.json").read_text())["version"] == "4.0.0-rc1"
            )
            package_lock = json.loads((installer_dir / "package-lock.json").read_text())
            assert package_lock["version"] == "4.0.0-rc1"
            assert package_lock["packages"][""]["version"] == "4.0.0-rc1"
            assert 'version = "4.0.0-rc1"' in (tauri_dir / "Cargo.toml").read_text()
            built = (
                tauri_dir
                / "target"
                / "release"
                / "bundle"
                / "nsis"
                / "CivicCast Installer_4.0.0-rc1_x64-setup.exe"
            )
            built.parent.mkdir(parents=True, exist_ok=True)
            built.write_bytes(b"release-version tauri setup bytes")

        monkeypatch.setattr(builder, "_run", fake_run)
        monkeypatch.setattr(builder, "_npm_command", lambda: ["npm"])
        monkeypatch.setattr(builder.sys, "platform", "win32")
        monkeypatch.setattr(builder, "ROOT", fake_root)

        artifact = builder.build_windows_tauri_installer(tmp_path, "4.0.0-rc1")

        assert artifact.path.name == "civiccast-4.0.0-rc1-windows-setup.exe"
        assert json.loads((tauri_dir / "tauri.conf.json").read_text())["version"] == "3.3.0"
        assert json.loads((installer_dir / "package.json").read_text())["version"] == "3.3.0"
        package_lock = json.loads((installer_dir / "package-lock.json").read_text())
        assert package_lock["version"] == "3.3.0"
        assert package_lock["packages"][""]["version"] == "3.3.0"
        assert 'version = "3.3.0"' in (tauri_dir / "Cargo.toml").read_text()

    def test_builder_windows_tauri_installer_respects_cargo_target_dir(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        builder = importlib.import_module("scripts.build_release_artifacts")
        fake_root = tmp_path / "repo"
        (fake_root / "civiccast" / "apps" / "installer" / "src-tauri").mkdir(parents=True)
        alternate_target = tmp_path / "target-v2"
        built = (
            alternate_target
            / "release"
            / "bundle"
            / "nsis"
            / "CivicCast Installer_2.0.0_x64-setup.exe"
        )
        built.parent.mkdir(parents=True, exist_ok=True)
        built.write_bytes(b"alternate tauri setup bytes")
        wheelhouse = tmp_path / "wheelhouse"
        wheelhouse.mkdir()
        (wheelhouse / "WHEELHOUSE-MANIFEST.json").write_text(
            json.dumps({"wheels": []}),
            encoding="utf-8",
        )
        (wheelhouse / "civiccast-2.0.0-py3-none-any.whl").write_bytes(b"wheel")
        gstreamer_runtime = tmp_path / "gstreamer-runtime"
        gstreamer_runtime.mkdir()
        _write_minimal_gstreamer_runtime(gstreamer_runtime)

        monkeypatch.setattr(builder, "_run", lambda cmd, *, cwd=builder.ROOT: None)
        monkeypatch.setattr(builder, "_npm_command", lambda: ["npm"])
        monkeypatch.setattr(builder.sys, "platform", "win32")
        monkeypatch.setattr(builder, "ROOT", fake_root)
        monkeypatch.setenv("CARGO_TARGET_DIR", str(alternate_target))

        artifact = builder.build_windows_tauri_installer(tmp_path, "2.0.0")

        assert artifact.kind == "windows-tauri-installer"
        assert artifact.path.name == "civiccast-2.0.0-windows-setup.exe"
        assert artifact.path.read_bytes() == b"alternate tauri setup bytes"

    def test_builder_windows_tauri_installer_requires_wheelhouse(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        builder = importlib.import_module("scripts.build_release_artifacts")
        fake_root = tmp_path / "repo"
        (fake_root / "civiccast" / "apps" / "installer" / "src-tauri").mkdir(parents=True)
        monkeypatch.setattr(builder.sys, "platform", "win32")
        monkeypatch.setattr(builder, "ROOT", fake_root)

        try:
            builder.build_windows_tauri_installer(tmp_path, "1.2.0")
        except RuntimeError as exc:
            assert "requires a built wheelhouse" in str(exc)
        else:
            raise AssertionError("Windows installer build should fail without wheelhouse")

    def test_builder_windows_tauri_installer_requires_gstreamer_runtime(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        builder = importlib.import_module("scripts.build_release_artifacts")
        fake_root = tmp_path / "repo"
        (fake_root / "civiccast" / "apps" / "installer" / "src-tauri").mkdir(parents=True)
        wheelhouse = tmp_path / "wheelhouse"
        wheelhouse.mkdir()
        (wheelhouse / "WHEELHOUSE-MANIFEST.json").write_text(
            json.dumps({"wheels": []}),
            encoding="utf-8",
        )
        monkeypatch.setattr(builder.sys, "platform", "win32")
        monkeypatch.setattr(builder, "ROOT", fake_root)

        try:
            builder.build_windows_tauri_installer(tmp_path, "1.2.0")
        except RuntimeError as exc:
            assert "requires the bundled CivicCast GStreamer runtime" in str(exc)
        else:
            raise AssertionError("Windows installer build should fail without GStreamer runtime")

    def test_builder_windows_tauri_installer_requires_gstreamer_runtime_checksum(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        builder = importlib.import_module("scripts.build_release_artifacts")
        fake_root = tmp_path / "repo"
        (fake_root / "civiccast" / "apps" / "installer" / "src-tauri").mkdir(parents=True)
        wheelhouse = tmp_path / "wheelhouse"
        wheelhouse.mkdir()
        (wheelhouse / "WHEELHOUSE-MANIFEST.json").write_text(
            json.dumps({"wheels": []}),
            encoding="utf-8",
        )
        gstreamer_runtime = tmp_path / "gstreamer-runtime"
        gstreamer_runtime.mkdir()
        (gstreamer_runtime / "gstreamer-runtime-linux-x86_64.tar.gz").write_bytes(b"gst-runtime")
        monkeypatch.setattr(builder.sys, "platform", "win32")
        monkeypatch.setattr(builder, "ROOT", fake_root)

        try:
            builder.build_windows_tauri_installer(tmp_path, "1.2.0")
        except RuntimeError as exc:
            assert ".sha256 sidecar" in str(exc)
        else:
            raise AssertionError("Windows installer build should fail without runtime checksum")

    def test_builder_windows_tester_package_includes_installer_and_wheelhouse(
        self, tmp_path: Path
    ) -> None:
        builder = importlib.import_module("scripts.build_release_artifacts")
        installer = tmp_path / "civiccast-1.3.0-windows-setup.exe"
        installer.write_bytes(b"real installer")
        wheelhouse = tmp_path / "wheelhouse"
        wheelhouse.mkdir()
        (wheelhouse / "WHEELHOUSE-MANIFEST.json").write_text(
            json.dumps({"wheels": []}),
            encoding="utf-8",
        )
        (wheelhouse / "civiccast-1.3.0-py3-none-any.whl").write_bytes(b"wheel")

        artifact = builder.build_windows_tester_package(
            tmp_path,
            "1.3.0",
            builder.Artifact(installer, "windows-tauri-installer"),
        )

        assert artifact.kind == "windows-tester-package"
        with zipfile.ZipFile(artifact.path) as package:
            names = set(package.namelist())
            manifest = json.loads(package.read("civiccast-1.3.0-windows-tester-package.json"))
        assert "civiccast-1.3.0-windows-setup.exe" in names
        assert "wheelhouse/WHEELHOUSE-MANIFEST.json" in names
        assert "wheelhouse/civiccast-1.3.0-py3-none-any.whl" in names
        assert manifest["unsigned_installer"] is True
        assert manifest["installer_sha256"] == hashlib.sha256(b"real installer").hexdigest()
        assert "Set up Windows helper" in manifest["operator_path"]
        assert "run its local meeting tools" not in manifest["operator_path"]
        assert "Install WSL2 Ubuntu 24.04" not in manifest["operator_path"]
        assert "official CivicCast GitHub release asset" in manifest["trust_guidance"]
        assert (
            "release owner explicitly authorizes this exact SHA-256" in manifest["trust_guidance"]
        )
        assert "clean-machine acceptance" in manifest["trust_guidance"]
        assert "not for public distribution" in manifest["trust_guidance"]
        assert "private GitHub release" not in manifest["trust_guidance"]

    @staticmethod
    def _pe_bytes(*, signed: bool, plus: bool = False, magic: int | None = None) -> bytes:
        """Minimal PE whose Certificate Table (data directory index 4) is non-empty
        when signed. Lets the Authenticode-presence check read real bytes instead of
        trusting a flag. ``plus`` builds a PE32+ (64-bit) header (data directory at
        opt+112 vs opt+96); ``magic`` overrides the optional-header magic to exercise
        the unrecognized-magic branch."""
        buf = bytearray(0x400)
        e_lfanew = 0x80
        buf[0:2] = b"MZ"
        buf[0x3C:0x40] = e_lfanew.to_bytes(4, "little")
        buf[e_lfanew : e_lfanew + 4] = b"PE\x00\x00"
        opt = e_lfanew + 24
        if magic is None:
            magic = 0x20B if plus else 0x10B
        buf[opt : opt + 2] = magic.to_bytes(2, "little")
        dd_start = opt + 112 if plus else opt + 96
        cert = dd_start + 4 * 8  # data directory index 4 = Certificate Table
        buf[cert : cert + 4] = (0x300).to_bytes(4, "little")  # (file) address
        buf[cert + 4 : cert + 8] = (0x100 if signed else 0).to_bytes(4, "little")
        return bytes(buf)

    def test_pe_check_rejects_non_pe_truncated_and_bad_magic(self, tmp_path: Path) -> None:
        # TE-5: the defensive early-returns must all yield False, never a crash or a
        # false "signed" (these branches were previously untested).
        builder = importlib.import_module("scripts.build_release_artifacts")
        garbage = tmp_path / "a.exe"
        garbage.write_bytes(b"this is not a PE file at all")
        assert builder._pe_has_authenticode_evidence(garbage) is False
        truncated = tmp_path / "b.exe"
        truncated.write_bytes(b"MZ" + b"\x00" * 8)  # len < 0x40
        assert builder._pe_has_authenticode_evidence(truncated) is False
        bad_magic = tmp_path / "c.exe"
        bad_magic.write_bytes(self._pe_bytes(signed=True, magic=0x999))
        assert builder._pe_has_authenticode_evidence(bad_magic) is False

    def test_pe_check_handles_pe32plus(self, tmp_path: Path) -> None:
        # TE-5: the PE32+ (magic 0x20B, data directory at opt+112) path was
        # branched-on but never exercised.
        builder = importlib.import_module("scripts.build_release_artifacts")
        signed = tmp_path / "s.exe"
        signed.write_bytes(self._pe_bytes(signed=True, plus=True))
        assert builder._pe_has_authenticode_evidence(signed) is True
        unsigned = tmp_path / "u.exe"
        unsigned.write_bytes(self._pe_bytes(signed=False, plus=True))
        assert builder._pe_has_authenticode_evidence(unsigned) is False

    def test_tester_package_marks_signed_installer_as_signed(self, tmp_path: Path) -> None:
        builder = importlib.import_module("scripts.build_release_artifacts")
        installer = tmp_path / "civiccast-1.0.0-windows-setup.exe"
        installer.write_bytes(self._pe_bytes(signed=True))
        artifact = builder.build_windows_tester_package(
            tmp_path, "1.0.0", builder.Artifact(installer, "windows-tauri-installer")
        )
        with zipfile.ZipFile(artifact.path) as package:
            manifest = json.loads(package.read("civiccast-1.0.0-windows-tester-package.json"))
        assert manifest["unsigned_installer"] is False
        assert "Authenticode" in manifest["trust_guidance"]

    def test_tester_package_marks_unsigned_installer_as_unsigned(self, tmp_path: Path) -> None:
        builder = importlib.import_module("scripts.build_release_artifacts")
        installer = tmp_path / "civiccast-1.0.0-windows-setup.exe"
        installer.write_bytes(self._pe_bytes(signed=False))
        artifact = builder.build_windows_tester_package(
            tmp_path, "1.0.0", builder.Artifact(installer, "windows-tauri-installer")
        )
        with zipfile.ZipFile(artifact.path) as package:
            manifest = json.loads(package.read("civiccast-1.0.0-windows-tester-package.json"))
        assert manifest["unsigned_installer"] is True
        assert "does not contain Authenticode signing evidence" in manifest["trust_guidance"]
        assert (
            "release owner explicitly authorizes this exact SHA-256" in manifest["trust_guidance"]
        )
        assert "clean-machine acceptance" in manifest["trust_guidance"]
        assert "not for public distribution" in manifest["trust_guidance"]
        assert "verified publisher Scott Converse" not in manifest["trust_guidance"]

    def test_installer_sidecar_reflects_authenticode_without_sigstore(self, tmp_path: Path) -> None:
        builder = importlib.import_module("scripts.build_release_artifacts")
        installer = tmp_path / "civiccast-1.0.0-windows-setup.exe"
        installer.write_bytes(self._pe_bytes(signed=True))
        # No .sigstore.json present: pre-fix this forced signed=false for Windows.
        builder._installer_artifact_entry(
            tmp_path,
            installer,
            kind="windows-tauri-installer",
            package_kind="windows-tauri-exe",
            service_manager="wsl2-systemd",
        )
        sidecar = json.loads(
            installer.with_name(installer.name + ".sidecar.json").read_text(encoding="utf-8")
        )
        assert sidecar["install_manifest"]["signed"] is True
        assert sidecar["attestation"] is None

    @staticmethod
    def _write_partial_manifest(job_dir: Path, version: str, files: dict[str, bytes]) -> None:
        import hashlib as _h

        job_dir.mkdir(parents=True, exist_ok=True)
        entries = []
        for name, data in files.items():
            (job_dir / name).write_bytes(data)
            entries.append(
                {
                    "kind": "release-artifact",
                    "filename": name,
                    "sha256": _h.sha256(data).hexdigest(),
                    "size_bytes": len(data),
                }
            )
        manifest = {
            "version": version,
            "generated_at_unix": 1700000000,
            "artifacts": entries,
            "source_state": {"commit": "abc123"},
            "beta_handoff_acquisition": None,
        }
        (job_dir / f"civiccast-{version}-release-artifacts-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def test_merge_manifests_unions_both_jobs(self, tmp_path: Path) -> None:
        builder = importlib.import_module("scripts.build_release_artifacts")
        linux = tmp_path / "linux"
        windows = tmp_path / "windows"
        out = tmp_path / "combined"
        self._write_partial_manifest(linux, "1.0.0", {"civiccast-1.0.0-source.tar.gz": b"src"})
        self._write_partial_manifest(
            windows,
            "1.0.0",
            {"civiccast-1.0.0-windows-setup.exe": b"signed-installer-bytes"},
        )

        builder.merge_release_manifests([linux, windows], out, "1.0.0")

        merged = json.loads(
            (out / "civiccast-1.0.0-release-artifacts-manifest.json").read_text(encoding="utf-8")
        )
        names = {a["filename"] for a in merged["artifacts"]}
        assert names == {
            "civiccast-1.0.0-source.tar.gz",
            "civiccast-1.0.0-windows-setup.exe",
        }
        win = next(
            a for a in merged["artifacts"] if a["filename"] == "civiccast-1.0.0-windows-setup.exe"
        )
        assert win["sha256"] == hashlib.sha256(b"signed-installer-bytes").hexdigest()
        assert win["size_bytes"] == len(b"signed-installer-bytes")

    def test_merge_unions_absent_file_on_recorded_sha(self, tmp_path: Path) -> None:
        # A per-job CI bundle need not carry every artifact its manifest lists (the
        # Windows bundle omits the .sidecar.json / .sigstore.json). The merge trusts
        # the sha the building job recorded rather than failing closed. Regression for
        # the rc9 (wheelhouse) / rc10 (sidecar) layered publish-manifest failures.
        import hashlib as _h

        builder = importlib.import_module("scripts.build_release_artifacts")
        job = tmp_path / "job"
        sidecar = "civiccast-1.0.0-windows-setup.exe.sidecar.json"
        self._write_partial_manifest(job, "1.0.0", {sidecar: b"x"})
        recorded = _h.sha256(b"x").hexdigest()
        (job / sidecar).unlink()  # present in the manifest, absent from the bundle
        art = builder.merge_release_manifests([job], tmp_path / "out", "1.0.0")
        merged = json.loads(art.path.read_text(encoding="utf-8"))
        entry = next(a for a in merged["artifacts"] if a["filename"] == sidecar)
        assert entry["sha256"] == recorded

    def test_merge_fails_closed_when_absent_file_has_no_recorded_sha(self, tmp_path: Path) -> None:
        builder = importlib.import_module("scripts.build_release_artifacts")
        job = tmp_path / "job"
        self._write_partial_manifest(job, "1.0.0", {"present.bin": b"x"})
        manifest = next(job.glob("civiccast-*-release-artifacts-manifest.json"))
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["artifacts"][0].pop("sha256")  # unverifiable: absent AND no recorded sha
        manifest.write_text(json.dumps(data), encoding="utf-8")
        (job / "present.bin").unlink()
        with pytest.raises(RuntimeError):
            builder.merge_release_manifests([job], tmp_path / "out", "1.0.0")

    def test_merge_dedupes_nonreproducible_artifact_built_by_both_jobs(
        self, tmp_path: Path
    ) -> None:
        # The Python sdist + app wheel are rebuilt non-reproducibly by BOTH the linux and
        # windows jobs, so the same filename carries a different sha per job. The merge
        # must dedupe to the first (published) copy, not raise. Regression for the rc10
        # `merge: conflicting sha256 for civiccast-*-py3-none-any.whl` failure.
        import hashlib as _h

        builder = importlib.import_module("scripts.build_release_artifacts")
        linux = tmp_path / "linux"
        windows = tmp_path / "windows"
        wheel = "civiccast-1.0.0-py3-none-any.whl"
        self._write_partial_manifest(linux, "1.0.0", {wheel: b"linux-built-bytes"})
        self._write_partial_manifest(windows, "1.0.0", {wheel: b"windows-rebuilt-bytes"})
        art = builder.merge_release_manifests([linux, windows], tmp_path / "out", "1.0.0")
        merged = json.loads(art.path.read_text(encoding="utf-8"))
        entries = [a for a in merged["artifacts"] if a["filename"] == wheel]
        assert len(entries) == 1  # deduped, not duplicated
        assert entries[0]["sha256"] == _h.sha256(b"linux-built-bytes").hexdigest()

    def test_merge_manifests_via_cli_entrypoint(self, tmp_path: Path, monkeypatch) -> None:
        # TE-4: the workflow drives this through main()'s --merge-manifests branch
        # (out-dir resolve/mkdir + the try/except-to-exit-1 wrapper + the default
        # version), NOT the function directly -- exercise that exact wiring, mirroring
        # the existing --windows-installer CLI test.
        builder = importlib.import_module("scripts.build_release_artifacts")
        linux = tmp_path / "linux"
        windows = tmp_path / "windows"
        out = tmp_path / "combined"
        self._write_partial_manifest(linux, "9.9.9", {"civiccast-9.9.9-source.tar.gz": b"src"})
        self._write_partial_manifest(
            windows, "9.9.9", {"civiccast-9.9.9-windows-setup.exe": b"exe"}
        )
        monkeypatch.setattr(
            builder.sys,
            "argv",
            [
                "build_release_artifacts.py",
                "--merge-manifests",
                str(linux),
                str(windows),
                "--out-dir",
                str(out),
            ],
        )
        assert builder.main() == 0
        merged = list(out.glob("civiccast-*-release-artifacts-manifest.json"))
        assert len(merged) == 1
        names = {
            a["filename"] for a in json.loads(merged[0].read_text(encoding="utf-8"))["artifacts"]
        }
        assert names == {"civiccast-9.9.9-source.tar.gz", "civiccast-9.9.9-windows-setup.exe"}

    def test_manifest_excludes_subdir_build_intermediates(self, tmp_path: Path) -> None:
        # gate-civiccast: the wheelhouse (a subdir build intermediate the installer
        # bundles internally, NOT a published release asset) must not be listed in the
        # release manifest, or the publish-manifest merge fails closed re-hashing a
        # file a given per-job bundle does not carry (the real rc9 tag-build failure).
        builder = importlib.import_module("scripts.build_release_artifacts")
        (tmp_path / "civiccast-1.0.0-windows-setup.exe").write_bytes(b"installer")
        (tmp_path / "wheelhouse").mkdir()
        (tmp_path / "wheelhouse" / "WHEELHOUSE-MANIFEST.json").write_text("{}", encoding="utf-8")
        (tmp_path / "wheelhouse" / "dep-1.0-py3-none-any.whl").write_bytes(b"wheel")
        manifest = builder.write_artifact_manifest(tmp_path, "1.0.0", [])
        entries = {
            a["filename"]
            for a in json.loads(manifest.path.read_text(encoding="utf-8"))["artifacts"]
        }
        assert "civiccast-1.0.0-windows-setup.exe" in entries
        assert not any("wheelhouse" in e for e in entries), entries

    def test_builder_clean_windows_proof_kit_is_self_contained(self, tmp_path: Path) -> None:
        builder = importlib.import_module("scripts.build_release_artifacts")
        installer = tmp_path / "civiccast-2.0.0-windows-setup.exe"
        installer.write_bytes(b"real installer")

        artifact = builder.build_clean_windows_proof_kit(
            tmp_path,
            "2.0.0",
            builder.Artifact(installer, "windows-tauri-installer"),
        )

        assert artifact.kind == "clean-windows-proof-kit"
        with zipfile.ZipFile(artifact.path) as package:
            names = set(package.namelist())
            sums = package.read("SHA256SUMS.txt").decode()
            readme = package.read("README.md").decode()
            verifier = package.read("VERIFY-AND-LAUNCH.ps1").decode()
            packaged_directive = package.read("proof-directive.md").decode()
        acquisition = builder._beta_handoff_acquisition(tmp_path, [artifact])
        assert "incoming/civiccast-2.0.0-windows-setup.exe" in names
        assert hashlib.sha256(b"real installer").hexdigest() in sums
        assert "Windows 11 reports an NT version beginning with `10.0`" in readme
        assert "$isWindows11 = $build -ge 22000" in verifier
        assert '$signature.Status -ne "Valid"' in verifier
        assert '"Microsoft-Windows-Subsystem-Linux"' in verifier
        assert '"VirtualMachinePlatform"' in verifier
        assert '"CivicCast-Ubuntu-24.04"' in verifier
        assert "required_features_absent" in verifier
        assert "prior_civiccast_absent" in verifier
        assert "CivicCast v2.0.0 Clean Windows Proof Directive" in packaged_directive
        assert "civiccast-2.0.0-windows-setup.exe" in packaged_directive
        assert "v2.0.0-clean-windows-proof.md" in packaged_directive
        assert "The Windows helper starts successfully." in packaged_directive
        assert "Windows helper/restart/resume" in packaged_directive
        assert "private packaging" in packaged_directive
        assert "Portal-only approval" in packaged_directive
        assert "resident metadata and HLS playback" in packaged_directive
        assert "repair/relaunch" in packaged_directive
        assert "uninstall cleanup" in packaged_directive
        assert "private rehearsal" not in packaged_directive
        assert "safe-to-broadcast" not in packaged_directive
        assert "WSL2 Ubuntu starts successfully." not in packaged_directive
        assert "v1.3" not in packaged_directive
        assert acquisition["clean_windows_proof_kit"] == {
            "filename": "civiccast-2.0.0-clean-windows-proof-kit.zip",
            "kind": "clean-windows-proof-kit",
        }
        assert acquisition["hashes"]["clean_windows_proof_kit"]

    def test_clean_windows_proof_directive_collects_recoverable_findings(self) -> None:
        directive = (
            Path("docs") / "releases" / "evidence" / "v1.3-clean-windows-codex-proof-directive.md"
        ).read_text(encoding="utf-8")

        assert "collect-and-continue proof" in directive
        assert "expected filename/path mismatch" in directive
        assert "Record each mismatch as a finding" in directive
        assert "Stop immediately only for a blocker" in directive
        assert "In the pullable tester branch flow, do not copy files by hand" in directive
        assert "If `C:\\CivicCastProof\\VERIFY-AND-LAUNCH.ps1` already exists" in directive
        assert "Run-WindowsTesterDirective.ps1" in directive
        assert "versioned tester runner handles WSL2/Ubuntu 24.04" in directive
        assert "Do not click the installer app's WSL button as the main" in directive
        assert "installs Node.js and Playwright Chromium" in directive
        assert "Do not manually click installer screens" in directive
        assert "C:\\CivicCastTester\\Use-CivicCastPlaywright.ps1" in directive
        assert "Install WSL2 Ubuntu 24.04`. Approve the Windows UAC prompt" not in directive
        assert "-Mode RecordResult" in directive
        assert "test-results/windows" in directive
        assert "not as a replacement for the\npushed tester result" in directive

    def test_beta_handoff_acquisition_exposes_gstreamer_runtime_hash(self, tmp_path: Path) -> None:
        builder = importlib.import_module("scripts.build_release_artifacts")
        runtime_dir = tmp_path / "gstreamer-runtime"
        runtime_dir.mkdir()
        _write_minimal_gstreamer_runtime(runtime_dir)
        runtime = runtime_dir / "gstreamer-runtime-linux-x86_64.tar.gz"
        artifact = builder.Artifact(runtime, "release-artifact")

        acquisition = builder._beta_handoff_acquisition(tmp_path, [artifact])

        assert acquisition["gstreamer_runtime"] == {
            "filename": "gstreamer-runtime/gstreamer-runtime-linux-x86_64.tar.gz",
            "kind": "release-artifact",
        }
        assert (
            acquisition["hashes"]["gstreamer_runtime"]
            == hashlib.sha256(runtime.read_bytes()).hexdigest()
        )


def test_direct_tauri_bundle_script_fails_closed_when_runtime_payload_is_absent() -> None:
    package = json.loads(
        (Path("civiccast") / "apps" / "installer" / "package.json").read_text(encoding="utf-8")
    )

    command = package["scripts"]["tauri:build"]

    assert "verify-bundle-resources" in command


def test_bundle_resource_guard_checks_the_gstreamer_archive_and_checksum() -> None:
    guard = (
        Path("civiccast") / "apps" / "installer" / "scripts" / "verify-bundle-resources.mjs"
    ).read_text(encoding="utf-8")

    assert "gstreamer-runtime-linux-x86_64.tar.gz" in guard
    assert "gstreamer-runtime-linux-x86_64.tar.gz.sha256" in guard
    assert "createHash" in guard


def test_python_sdist_excludes_local_build_and_release_artifact_caches() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    sdist = pyproject.split("[tool.hatch.build.targets.sdist]", 1)[1].split(
        "[tool.hatch.build.targets.wheel]", 1
    )[0]

    assert '"/target"' in sdist
    assert '"/artifacts"' in sdist
    assert '"/civiccast/apps/installer/src-tauri/target"' in sdist


def test_clean_windows_verifier_survives_a_machine_with_no_wsl() -> None:
    """FALSIFICATION (found by the rc17 clean-VM gauntlet): the generated
    VERIFY-AND-LAUNCH.ps1 must not crash on a genuinely clean machine.

    `wsl.exe --list` on a box without WSL writes to stderr and exits 1;
    under the script's own `$ErrorActionPreference = "Stop"` that native
    stderr becomes a terminating NativeCommandError, and a bare `2>$null`
    does NOT suppress it. The old template shelled `& wsl.exe --list
    --quiet 2>$null` directly, so the proof tool died before writing
    preflight.json or launching the installer -- on exactly the clean
    machines it exists to verify. The fix redirects stderr at the cmd.exe
    level so PowerShell never sees it.
    """
    from scripts.build_release_artifacts import _clean_windows_proof_verifier

    verifier = _clean_windows_proof_verifier(
        "1.0.0-rc-test", "civiccast-1.0.0-rc-test-windows-setup.exe", "0" * 64
    )
    # The fragile pattern must be gone...
    assert "& wsl.exe --list --quiet 2>$null" not in verifier
    # ...and the WSL enumeration must redirect stderr at the cmd level and
    # tolerate the clean-machine failure.
    assert 'cmd.exe /c "wsl.exe --list --quiet 2>nul"' in verifier
    assert "$wslDistributions = @()" in verifier
