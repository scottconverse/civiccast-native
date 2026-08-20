# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Staging contract for the built ``native-server-binaries`` pack: verify
through the real provisioning trust wire, stage both the raw file and its
extracted payload, and re-verify the staged copy -- never touching the real
``civiccast/apps/installer/src-tauri/packs/`` tree (the module's staging
constants are monkeypatched to a ``tmp_path`` for every test here)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]
BUILDER_SCRIPT = ROOT / "scripts" / "build_native_server_pack.py"
STAGER_SCRIPT = ROOT / "scripts" / "stage_native_server_pack.py"


def _load(path: Path, name: str) -> object:
    assert path.is_file(), f"missing script: {path}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pack_builder = _load(BUILDER_SCRIPT, "build_native_server_pack")
stager = _load(STAGER_SCRIPT, "stage_native_server_pack")


def _write(path: Path, body: bytes) -> tuple[int, str]:
    import hashlib

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return len(body), hashlib.sha256(body).hexdigest()


def _build_tiny_pack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: Ed25519PrivateKey
) -> Path:
    postgres_root = tmp_path / "src" / "postgres"
    nats_root = tmp_path / "src" / "nats"
    tsduck_root = tmp_path / "src" / "tsduck"

    bin_pins = {
        name: _write(postgres_root / "bin" / name, f"pg:{name}".encode())
        for name in (
            "initdb.exe",
            "postgres.exe",
            "pg_ctl.exe",
            "pg_dump.exe",
            "pg_restore.exe",
            "psql.exe",
        )
    }
    for name in pack_builder.POSTGRES_SHARE_TOP_FILES:
        _write(postgres_root / "share" / name, f"share:{name}".encode())
    for name in pack_builder.POSTGRES_SHARE_EXTENSION_FILES:
        _write(postgres_root / "share" / "extension" / name, f"ext:{name}".encode())
    for subdir in pack_builder.POSTGRES_SHARE_DATA_DIRS:
        _write(postgres_root / "share" / subdir / "UTC", b"tz")
    for name in pack_builder.POSTGRES_LICENSE_FILES:
        _write(postgres_root / name, f"license:{name}".encode())

    nats_pins = {"nats-server.exe": _write(nats_root / "nats-server.exe", b"nats")}
    for name in pack_builder.NATS_LICENSE_FILES:
        _write(nats_root / name, f"license:{name}".encode())

    tsduck_pins = {}
    for name in (
        "tsp.exe",
        "tscore.dll",
        "tsduck.dll",
        "tsplugin_analyze.dll",
        "tsplugin_continuity.dll",
        "tsplugin_pcradjust.dll",
        "tsplugin_until.dll",
    ):
        tsduck_pins[name] = _write(tsduck_root / "bin" / name, f"ts:{name}".encode())
    for name in pack_builder.TSDUCK_LICENSE_FILES:
        _write(tsduck_root / name, f"license:{name}".encode())

    monkeypatch.setattr(pack_builder, "POSTGRES_BIN_PINS", bin_pins)
    monkeypatch.setattr(pack_builder, "POSTGRES_BIN_DLL_PINS", {})
    monkeypatch.setattr(pack_builder, "POSTGRES_LIB_PINS", {})
    monkeypatch.setattr(pack_builder, "NATS_BIN_PINS", nats_pins)
    monkeypatch.setattr(pack_builder, "TSDUCK_BIN_PINS", tsduck_pins)

    output = tmp_path / "built" / "native-server-binaries.ccpack"
    pack_builder.build_server_pack(
        output=output,
        postgres_root=postgres_root,
        nats_root=nats_root,
        tsduck_root=tsduck_root,
        signing_private_key=key,
        signing_key_id="development-test-key",
        product_version="0.0.0-test",
        source_sha="a" * 40,
    )
    return output


def test_stage_server_pack_lays_the_exact_provisioning_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged_file = tmp_path / "staged" / "packs" / "native-server-binaries.ccpack"
    staged_extracted = tmp_path / "staged" / "packs" / "native-server-binaries"
    monkeypatch.setattr(stager, "STAGED_PACK_FILE", staged_file)
    monkeypatch.setattr(stager, "STAGED_PACK_EXTRACTED", staged_extracted)

    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    built_pack = _build_tiny_pack(tmp_path, monkeypatch, key)

    report = stager.stage_server_pack(
        built_pack,
        public_key=key.public_key(),
        expected_product_version="0.0.0-test",
        expected_compatible_core="0.0.0-test",
        expected_signing_key_id="development-test-key",
    )

    assert report["component"] == "native-server-binaries"
    initdb_path = Path(report["initdb_path"])
    assert initdb_path.is_file()
    assert initdb_path == staged_extracted / "payload" / "bin" / "initdb.exe"
    assert staged_file.is_file()


def test_stage_server_pack_refuses_when_the_source_pack_fails_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged_file = tmp_path / "staged" / "packs" / "native-server-binaries.ccpack"
    staged_extracted = tmp_path / "staged" / "packs" / "native-server-binaries"
    monkeypatch.setattr(stager, "STAGED_PACK_FILE", staged_file)
    monkeypatch.setattr(stager, "STAGED_PACK_EXTRACTED", staged_extracted)

    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    built_pack = _build_tiny_pack(tmp_path, monkeypatch, key)

    wrong_key = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
    from civiccast.installer.native_packs import NativePackVerificationError

    with pytest.raises(NativePackVerificationError):
        stager.stage_server_pack(
            built_pack,
            public_key=wrong_key.public_key(),
            expected_product_version="0.0.0-test",
            expected_compatible_core="0.0.0-test",
            expected_signing_key_id="development-test-key",
        )
    # Nothing must be staged on a failed verification.
    assert not staged_file.exists()
