# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Hard size and payload-separation gates for the small native bootstrap."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


def _load() -> object:
    path = Path(__file__).resolve().parents[2] / "scripts" / "build_native_bootstrap.py"
    spec = importlib.util.spec_from_file_location("build_native_bootstrap", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


builder = _load()


def test_bootstrap_size_gate_is_strictly_less_than_300mb() -> None:
    assert builder.BOOTSTRAP_SIZE_LIMIT_EXCLUSIVE == 300_000_000
    assert builder.SOURCE_DATE_EPOCH == 1_704_067_200
    assert builder.enforce_bootstrap_size(1) == 299_999_999
    assert builder.enforce_bootstrap_size(299_999_999) == 1

    with pytest.raises(ValueError, match="must be positive"):
        builder.enforce_bootstrap_size(0)
    with pytest.raises(ValueError, match="must be positive"):
        builder.enforce_bootstrap_size(-1)
    with pytest.raises(ValueError, match="not smaller"):
        builder.enforce_bootstrap_size(300_000_000)
    with pytest.raises(ValueError, match="not smaller"):
        builder.enforce_bootstrap_size(300_000_001)


def test_bootstrap_requires_one_raw_ed25519_public_key() -> None:
    key = bytes(range(32))
    encoded = base64.b64encode(key).decode("ascii")

    assert builder.validate_pack_public_key(encoded) == key
    with pytest.raises(ValueError, match="exactly 32"):
        builder.validate_pack_public_key(base64.b64encode(b"short").decode("ascii"))
    with pytest.raises(ValueError, match="exactly 32"):
        builder.validate_pack_public_key(base64.b64encode(bytes(range(33))).decode("ascii"))
    with pytest.raises(ValueError, match="canonical base64"):
        builder.validate_pack_public_key("not base64!")
    with pytest.raises(ValueError, match="canonical base64"):
        builder.validate_pack_public_key(encoded + "\n")


def test_native_bootstrap_config_embeds_no_station_payload() -> None:
    builder.validate_native_bootstrap_config()


def test_vc_redist_input_is_exactly_pinned(tmp_path: Path) -> None:
    source = tmp_path / "vc_redist.x64.exe"
    source.write_bytes(b"reviewed redistributable")
    expected_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()

    assert (
        builder.validate_vc_redist(
            source,
            expected_bytes=source.stat().st_size,
            expected_sha256=expected_sha256,
        )
        == source.resolve()
    )
    with pytest.raises(ValueError, match="byte length"):
        builder.validate_vc_redist(
            source,
            expected_bytes=source.stat().st_size + 1,
            expected_sha256=expected_sha256,
        )
    with pytest.raises(ValueError, match="SHA-256"):
        builder.validate_vc_redist(
            source,
            expected_bytes=source.stat().st_size,
            expected_sha256="0" * 64,
        )


def test_native_bootstrap_installs_pinned_vc_runtime_offline() -> None:
    hook = (
        Path(builder.__file__).resolve().parents[1]
        / "civiccast"
        / "apps"
        / "installer"
        / "src-tauri"
        / "nsis-hooks-bootstrap.nsh"
    ).read_text(encoding="utf-8")

    assert "vc_redist.x64.exe" in hook
    assert "/install /quiet /norestart" in hook
    assert "${ElseIf} $0 == 3010" in hook
    assert "SetRebootFlag true" in hook
    assert "restart is required" in hook


def test_native_bootstrap_config_rejects_network_dependent_webview_install(
    tmp_path: Path,
) -> None:
    config = tmp_path / "tauri.native.conf.json"
    config.write_text(
        json.dumps(
            {
                "bundle": {
                    "resources": {"resources/vc_redist.x64.exe": "vc_redist.x64.exe"},
                    "windows": {
                        "webviewInstallMode": {
                            "type": "downloadBootstrapper",
                            "silent": True,
                        },
                        "nsis": {"installerHooks": "nsis-hooks-bootstrap.nsh"},
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="offline WebView2"):
        builder.validate_native_bootstrap_config(config)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"bundle": None},
        {
            "bundle": {
                "resources": ["embedded-station-payload"],
                "windows": {"nsis": {"installerHooks": "nsis-hooks-bootstrap.nsh"}},
            }
        },
        {"bundle": {"resources": [], "windows": None}},
        {"bundle": {"resources": [], "windows": {"nsis": None}}},
        {
            "bundle": {
                "resources": [],
                "windows": {"nsis": {"installerHooks": "nsis-hooks-native.nsh"}},
            }
        },
    ],
)
def test_native_bootstrap_config_rejects_incomplete_or_payload_bearing_shapes(
    tmp_path: Path,
    payload: dict[str, Any],
) -> None:
    config = tmp_path / "tauri.native.conf.json"
    config.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=r"bootstrap|resource|hooks"):
        builder.validate_native_bootstrap_config(config)


def test_development_trust_root_requires_explicit_switch() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        builder.require_allowed_signing_key(" ", allow_development_key=True)
    with pytest.raises(ValueError, match="allow-development-key"):
        builder.require_allowed_signing_key(
            "development-civiccast-native",
            allow_development_key=False,
        )
    builder.require_allowed_signing_key(
        "development-civiccast-native",
        allow_development_key=True,
    )


def test_release_builder_has_no_prebuilt_bootstrap_bypass() -> None:
    source = Path(builder.__file__).read_text(encoding="utf-8")

    assert "--skip-build" not in source


def test_reproducible_environment_controls_rust_and_source_epoch() -> None:
    env = builder.reproducible_build_environment(
        {
            "KEEP_ME": "yes",
            "RUSTFLAGS": "-C target-cpu=native",
        }
    )

    assert env["KEEP_ME"] == "yes"
    assert "RUSTFLAGS" not in env
    assert env["SOURCE_DATE_EPOCH"] == str(builder.SOURCE_DATE_EPOCH)
    encoded_flags = env["CARGO_ENCODED_RUSTFLAGS"].split("\x1f")
    assert encoded_flags[:2] == ["-C", "link-arg=/Brepro"]
    assert all("target-cpu=native" not in flag for flag in encoded_flags)
    assert any("--remap-path-prefix=" in flag for flag in encoded_flags)


def test_tauri_bundle_marker_is_patched_exactly_once() -> None:
    binary = b"prefix-" + builder.TAURI_UNKNOWN_BUNDLE_MARKER + b"-suffix"

    patched = builder.patch_tauri_bundle_type(binary)

    assert len(patched) == len(binary)
    assert builder.TAURI_UNKNOWN_BUNDLE_MARKER not in patched
    assert builder.TAURI_NSIS_BUNDLE_MARKER in patched


@pytest.mark.parametrize(
    "binary, occurrences",
    [
        (b"no marker", 0),
        (
            builder.TAURI_UNKNOWN_BUNDLE_MARKER + builder.TAURI_UNKNOWN_BUNDLE_MARKER,
            2,
        ),
    ],
)
def test_tauri_bundle_marker_contract_rejects_ambiguous_input(
    binary: bytes,
    occurrences: int,
) -> None:
    with pytest.raises(ValueError, match=rf"found {occurrences}"):
        builder.patch_tauri_bundle_type(binary)


def test_file_hash_and_report_measure_the_actual_bootstrap(tmp_path: Path) -> None:
    setup = tmp_path / "setup.exe"
    setup.write_bytes(b"actual bootstrap bytes")

    report = builder.build_report(setup, key_id="production-key")

    assert report == {
        "artifact": str(setup.resolve()),
        "bytes": len(b"actual bootstrap bytes"),
        "limit_exclusive": builder.BOOTSTRAP_SIZE_LIMIT_EXCLUSIVE,
        "headroom_bytes": (builder.BOOTSTRAP_SIZE_LIMIT_EXCLUSIVE - len(b"actual bootstrap bytes")),
        "pack_signing_key_id": "production-key",
        "sha256": hashlib.sha256(b"actual bootstrap bytes").hexdigest(),
        "signed": False,
        "status": "PASS",
    }


def test_run_uses_the_requested_directory_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[list[str], Path, dict[str, str] | None, bool]] = []

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((command, cwd, env, check))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(builder.subprocess, "run", fake_run)
    environment = {"CONTROLLED": "1"}

    builder._run(["tool", "--flag"], cwd=tmp_path, env=environment)

    assert calls == [(["tool", "--flag"], tmp_path, environment, False)]

    for returncode in (17, -9):
        monkeypatch.setattr(
            builder.subprocess,
            "run",
            lambda *args, _returncode=returncode, **kwargs: subprocess.CompletedProcess(
                args[0], _returncode
            ),
        )
        with pytest.raises(RuntimeError, match=rf"failed \({returncode}\).*tool"):
            builder._run(["tool"], cwd=tmp_path)


def test_makensis_discovery_prefers_tauris_download(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executable = tmp_path / "tauri" / "NSIS" / "makensis.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"fixture")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(builder.shutil, "which", lambda _name: None)

    assert builder._find_makensis() == executable.resolve()

    executable.unlink()
    with pytest.raises(FileNotFoundError, match="makensis"):
        builder._find_makensis()


@pytest.mark.parametrize(
    ("key_id", "expected_development_switch"),
    [
        ("development-test", "1"),
        ("production-test", None),
    ],
)
def test_build_controls_tauri_features_and_trust_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    key_id: str,
    expected_development_switch: str | None,
) -> None:
    installer = tmp_path / "installer"
    tauri = installer / "node_modules" / ".bin" / ("tauri.cmd" if os.name == "nt" else "tauri")
    tauri.parent.mkdir(parents=True)
    tauri.write_bytes(b"fixture")
    calls: list[tuple[list[str], dict[str, str] | None]] = []
    normalized: list[bool] = []
    vc_redist = tmp_path / "vc_redist.x64.exe"
    vc_redist.write_bytes(b"reviewed")
    monkeypatch.setattr(builder, "INSTALLER_DIR", installer)
    monkeypatch.setattr(
        builder,
        "VC_REDIST_RESOURCE",
        installer / "src-tauri" / "resources" / "vc_redist.x64.exe",
    )
    monkeypatch.setattr(builder, "validate_vc_redist", lambda path: path.resolve())
    monkeypatch.setattr(
        builder,
        "_run",
        lambda command, **kwargs: calls.append((command, kwargs.get("env"))),
    )
    monkeypatch.setattr(
        builder,
        "normalize_nsis_bootstrap",
        lambda: normalized.append(True),
    )

    builder._build("public-key", key_id, vc_redist)

    assert calls[0][0] == [("npm.cmd" if os.name == "nt" else "npm"), "ci"]
    command, environment = calls[1]
    assert command == [
        str(tauri),
        "build",
        "--config",
        "src-tauri/tauri.native.conf.json",
        "--features",
        "native-packs",
        "--bundles",
        "nsis",
        "--no-sign",
        "--ci",
    ]
    assert environment is not None
    assert environment["CIVICCAST_PACK_PUBLIC_KEY_BASE64"] == "public-key"
    assert environment["CIVICCAST_PACK_SIGNING_KEY_ID"] == key_id
    assert environment.get("CIVICCAST_ALLOW_DEVELOPMENT_PACK_KEY") == expected_development_switch
    assert environment["SOURCE_DATE_EPOCH"] == str(builder.SOURCE_DATE_EPOCH)
    assert normalized == [True]
    assert not builder.VC_REDIST_RESOURCE.exists()


def test_build_removes_partial_vc_resource_when_staging_copy_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "vc_redist.x64.exe"
    source.write_bytes(b"reviewed")
    destination = tmp_path / "resources" / "vc_redist.x64.exe"
    monkeypatch.setattr(builder, "VC_REDIST_RESOURCE", destination)
    monkeypatch.setattr(builder, "validate_vc_redist", lambda path: path.resolve())

    def fail_after_partial_copy(_source: Path, target: Path) -> None:
        target.write_bytes(b"partial")
        raise OSError("simulated copy failure")

    monkeypatch.setattr(builder.shutil, "copyfile", fail_after_partial_copy)

    with pytest.raises(OSError, match="simulated copy failure"):
        builder._build("public-key", "production-test", source)

    assert not destination.exists()


def test_normalized_nsis_repack_is_reproducible_and_restores_main_binary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    main_binary = tmp_path / "release" / "CivicCast Native.exe"
    nsis_dir = tmp_path / "release" / "nsis" / "x64"
    script = nsis_dir / "installer.nsi"
    generated = nsis_dir / "nsis-output.exe"
    setup = tmp_path / "release" / "bundle" / "setup.exe"
    main_binary.parent.mkdir(parents=True)
    nsis_dir.mkdir(parents=True)
    script.write_text("fixture", encoding="utf-8")
    original = b"prefix-" + builder.TAURI_UNKNOWN_BUNDLE_MARKER + b"-suffix"
    main_binary.write_bytes(original)
    original_timestamp = 1_600_000_000
    os.utime(main_binary, (original_timestamp, original_timestamp))
    monkeypatch.setattr(builder, "MAIN_BINARY", main_binary)
    monkeypatch.setattr(builder, "GENERATED_NSIS_DIR", nsis_dir)
    monkeypatch.setattr(builder, "GENERATED_NSIS_SCRIPT", script)
    monkeypatch.setattr(builder, "GENERATED_NSIS_OUTPUT", generated)
    monkeypatch.setattr(builder, "SETUP_ARTIFACT", setup)
    monkeypatch.setattr(builder, "_find_makensis", lambda: tmp_path / "makensis.exe")

    def fake_run(command: list[str], *, cwd: Path, env: object = None) -> None:
        assert command == [str(tmp_path / "makensis.exe"), "/V2", str(script)]
        assert cwd == nsis_dir
        assert env is None
        assert builder.TAURI_NSIS_BUNDLE_MARKER in main_binary.read_bytes()
        assert main_binary.stat().st_mtime == pytest.approx(
            builder.SOURCE_DATE_EPOCH,
            abs=1,
        )
        generated.write_bytes(b"deterministic normalized setup")

    monkeypatch.setattr(builder, "_run", fake_run)

    builder.normalize_nsis_bootstrap()

    assert setup.read_bytes() == b"deterministic normalized setup"
    assert main_binary.read_bytes() == original
    assert main_binary.stat().st_mtime == pytest.approx(original_timestamp, abs=1)


def test_normalized_nsis_repack_rejects_a_missing_generated_input(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    main_binary = tmp_path / "release" / "CivicCast Native.exe"
    missing_script = tmp_path / "release" / "nsis" / "x64" / "installer.nsi"
    main_binary.parent.mkdir(parents=True)
    main_binary.write_bytes(b"prefix-" + builder.TAURI_UNKNOWN_BUNDLE_MARKER + b"-suffix")
    monkeypatch.setattr(builder, "MAIN_BINARY", main_binary)
    monkeypatch.setattr(builder, "GENERATED_NSIS_SCRIPT", missing_script)

    with pytest.raises(
        FileNotFoundError,
        match=r"generated native bootstrap input is missing.*installer\.nsi",
    ):
        builder.normalize_nsis_bootstrap()


@pytest.mark.parametrize("precreate_target_parent", [False, True])
def test_normalized_nsis_repack_creates_or_reuses_nested_target_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    precreate_target_parent: bool,
) -> None:
    main_binary = tmp_path / "release" / "CivicCast Native.exe"
    nsis_dir = tmp_path / "release" / "nsis" / "x64"
    script = nsis_dir / "installer.nsi"
    generated = nsis_dir / "nsis-output.exe"
    setup = tmp_path / "deep" / "nested" / "bundle" / "setup.exe"
    main_binary.parent.mkdir(parents=True)
    nsis_dir.mkdir(parents=True)
    if precreate_target_parent:
        setup.parent.mkdir(parents=True)
    script.write_text("fixture", encoding="utf-8")
    original = b"prefix-" + builder.TAURI_UNKNOWN_BUNDLE_MARKER + b"-suffix"
    main_binary.write_bytes(original)
    monkeypatch.setattr(builder, "MAIN_BINARY", main_binary)
    monkeypatch.setattr(builder, "GENERATED_NSIS_DIR", nsis_dir)
    monkeypatch.setattr(builder, "GENERATED_NSIS_SCRIPT", script)
    monkeypatch.setattr(builder, "GENERATED_NSIS_OUTPUT", generated)
    monkeypatch.setattr(builder, "SETUP_ARTIFACT", setup)
    monkeypatch.setattr(builder, "_find_makensis", lambda: tmp_path / "makensis.exe")

    def fake_run(command: list[str], *, cwd: Path, env: object = None) -> None:
        assert cwd == nsis_dir
        generated.write_bytes(b"normalized setup")

    monkeypatch.setattr(builder, "_run", fake_run)

    builder.normalize_nsis_bootstrap()

    assert setup.read_bytes() == b"normalized setup"
    assert main_binary.read_bytes() == original


def _stub_successful_main(
    monkeypatch: pytest.MonkeyPatch,
    *,
    report: Path,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_native_bootstrap.py",
            "--pack-public-key-base64",
            base64.b64encode(bytes(range(32))).decode("ascii"),
            "--pack-signing-key-id",
            "production-test",
            "--vc-redist-x64",
            str(report.parent / "vc_redist.x64.exe"),
            "--report",
            str(report),
        ],
    )
    monkeypatch.setattr(builder, "validate_native_bootstrap_config", lambda: None)
    monkeypatch.setattr(
        builder,
        "_build",
        lambda public_key, key_id, vc_redist: None,
    )
    monkeypatch.setattr(
        builder,
        "build_report",
        lambda setup, *, key_id: {
            "artifact": str(setup),
            "pack_signing_key_id": key_id,
            "status": "PASS",
        },
    )


@pytest.mark.parametrize("precreate_report_parent", [False, True])
def test_main_writes_a_deterministic_report_and_returns_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    precreate_report_parent: bool,
) -> None:
    report = tmp_path / "deep" / "nested" / "bootstrap-report.json"
    if precreate_report_parent:
        report.parent.mkdir(parents=True)
    _stub_successful_main(monkeypatch, report=report)

    assert builder.main() == 0
    expected = {
        "artifact": str(builder.SETUP_ARTIFACT),
        "pack_signing_key_id": "production-test",
        "status": "PASS",
    }
    assert json.loads(report.read_text(encoding="utf-8")) == expected
    assert json.loads(capsys.readouterr().out) == expected


@pytest.mark.parametrize(
    "missing",
    [
        "--pack-public-key-base64",
        "--pack-signing-key-id",
        "--vc-redist-x64",
        "--report",
    ],
)
def test_main_requires_every_identity_and_report_argument(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    missing: str,
) -> None:
    arguments = [
        "--pack-public-key-base64",
        base64.b64encode(bytes(range(32))).decode("ascii"),
        "--pack-signing-key-id",
        "production-test",
        "--vc-redist-x64",
        str(tmp_path / "vc_redist.x64.exe"),
        "--report",
        str(tmp_path / "report.json"),
    ]
    index = arguments.index(missing)
    del arguments[index : index + 2]
    monkeypatch.setattr(sys, "argv", ["build_native_bootstrap.py", *arguments])
    monkeypatch.setattr(builder, "validate_pack_public_key", lambda encoded: b"key")
    monkeypatch.setattr(
        builder,
        "require_allowed_signing_key",
        lambda key_id, *, allow_development_key: None,
    )
    monkeypatch.setattr(builder, "validate_native_bootstrap_config", lambda: None)
    monkeypatch.setattr(
        builder,
        "_build",
        lambda public_key, key_id, vc_redist: None,
    )
    monkeypatch.setattr(
        builder,
        "build_report",
        lambda setup, *, key_id: {"status": "PASS"},
    )

    with pytest.raises(SystemExit) as exc_info:
        builder.main()

    assert exc_info.value.code == 2


@pytest.mark.parametrize("failure", [OSError("disk"), ValueError("bad"), RuntimeError("tool")])
def test_main_converts_expected_build_failures_to_actionable_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure: Exception,
) -> None:
    _stub_successful_main(monkeypatch, report=tmp_path / "report.json")
    monkeypatch.setattr(
        builder,
        "_build",
        lambda public_key, key_id, vc_redist: (_ for _ in ()).throw(failure),
    )

    with pytest.raises(SystemExit, match=str(failure)):
        builder.main()


def test_script_entrypoint_rejects_missing_required_arguments() -> None:
    completed = subprocess.run(
        [sys.executable, str(Path(builder.__file__).resolve())],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "--pack-public-key-base64" in completed.stderr
