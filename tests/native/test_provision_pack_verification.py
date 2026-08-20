# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Refusal-path tests for the server-binaries pack trust wiring.

Builds REAL signed packs (the same Ed25519 signature + byte-inventory
machinery every other native component pack uses --
:mod:`civiccast.installer.native_packs`) and asserts
:func:`civiccast.native.provision.pack.verify_server_binaries_pack` accepts a
correctly signed pack and refuses a tampered one -- before any provisioning
action would touch disk. No real PostgreSQL/NATS binaries are packed or run;
the pack payload is a couple of tiny placeholder files, since only the trust
envelope is under test here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from civiccast.installer.native_packs import NativePackVerificationError, build_native_pack
from civiccast.native.provision.pack import SERVER_BINARIES_COMPONENT, verify_server_binaries_pack


def _key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes(range(32)))


def _sources(tmp_path: Path) -> dict[str, Path]:
    initdb = tmp_path / "initdb.exe"
    nats_server = tmp_path / "nats-server.exe"
    initdb.write_bytes(b"placeholder initdb binary")
    nats_server.write_bytes(b"placeholder nats-server binary")
    return {
        "postgres/initdb.exe": initdb,
        "nats/nats-server.exe": nats_server,
    }


def _build(tmp_path: Path, *, key: Ed25519PrivateKey, output_name: str = "server-binaries.ccpack"):
    return build_native_pack(
        output=tmp_path / output_name,
        component=SERVER_BINARIES_COMPONENT,
        product_version="1.0.0",
        compatible_core="1.0.0",
        sources=_sources(tmp_path / "src"),
        signing_private_key=key,
        signing_key_id="key-1",
        metadata={"source_sha": "a" * 40},
    )


def test_correctly_signed_pack_verifies(tmp_path: Path) -> None:
    key = _key()
    (tmp_path / "src").mkdir()
    result = _build(tmp_path, key=key)

    verified = verify_server_binaries_pack(
        result.path,
        public_key=key.public_key(),
        expected_product_version="1.0.0",
        expected_compatible_core="1.0.0",
        expected_signing_key_id="key-1",
    )
    assert verified.component == SERVER_BINARIES_COMPONENT
    assert verified.file_count == 2


def test_wrong_public_key_is_refused(tmp_path: Path) -> None:
    key = _key()
    other_key = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
    (tmp_path / "src").mkdir()
    result = _build(tmp_path, key=key)

    with pytest.raises(NativePackVerificationError):
        verify_server_binaries_pack(
            result.path,
            public_key=other_key.public_key(),
            expected_product_version="1.0.0",
            expected_compatible_core="1.0.0",
            expected_signing_key_id="key-1",
        )


def test_product_version_mismatch_is_refused(tmp_path: Path) -> None:
    key = _key()
    (tmp_path / "src").mkdir()
    result = _build(tmp_path, key=key)

    with pytest.raises(NativePackVerificationError):
        verify_server_binaries_pack(
            result.path,
            public_key=key.public_key(),
            expected_product_version="2.0.0",  # does not match the built pack
            expected_compatible_core="1.0.0",
            expected_signing_key_id="key-1",
        )


def test_missing_pack_file_is_refused(tmp_path: Path) -> None:
    key = _key()
    with pytest.raises(NativePackVerificationError):
        verify_server_binaries_pack(
            tmp_path / "does-not-exist.ccpack",
            public_key=key.public_key(),
            expected_product_version="1.0.0",
            expected_compatible_core="1.0.0",
            expected_signing_key_id="key-1",
        )


def test_tampered_payload_byte_is_refused(tmp_path: Path) -> None:
    import zipfile

    key = _key()
    (tmp_path / "src").mkdir()
    result = _build(tmp_path, key=key)

    tampered = tmp_path / "tampered.ccpack"
    with (
        zipfile.ZipFile(result.path, "r") as source,
        zipfile.ZipFile(tampered, "w", compression=zipfile.ZIP_STORED) as target,
    ):
        for info in source.infolist():
            payload = source.read(info)
            if info.filename == "payload/postgres/initdb.exe":
                payload = b"tampered bytes, wrong content entirely!"
            target.writestr(info, payload)

    with pytest.raises(NativePackVerificationError):
        verify_server_binaries_pack(
            tampered,
            public_key=key.public_key(),
            expected_product_version="1.0.0",
            expected_compatible_core="1.0.0",
            expected_signing_key_id="key-1",
        )
