# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""WP2 app-payload-pack gap closure: tests for
``scripts/build_native_app_payload_pack.py`` -- the missing sibling of
``scripts/build_native_server_pack.py`` that packages the already-built (or
freshly built) WP-6 application-payload TREE (``scripts/
build_native_app_payload.py``) as a signed ``native-app-payload`` component
pack.

Mirrors ``tests/native/test_build_native_server_pack.py``'s shape: tiny
fixture-scale trees, never a real ~150 MB payload build. The independent
post-build verifier this builder calls
(``scripts.verify_native_app_payload.check_app_payload_verification``) has
its own dedicated, thorough test suite in ``tests/native/
test_app_payload_builder.py`` -- these tests monkeypatch it (the same
``monkeypatch.setattr(builder, ...)`` isolation style the server-pack tests
use for ``classify_server_pack_file``) rather than re-proving its internals,
so a fixture tree here only needs to be REAL enough for the pack-building
logic (source collection, signing, trust-wire round-trip, refusal paths),
not release-grade-verifier-faithful.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from civiccast.installer.native_packs import verify_native_pack
from civiccast.native.app_payload import APP_PAYLOAD_COMPONENT
from scripts.verify_native_app_payload import PayloadVerification

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "build_native_app_payload_pack.py"


def _load() -> object:
    assert SCRIPT_PATH.is_file(), f"native app-payload pack builder is missing: {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("build_native_app_payload_pack", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


builder = _load()

_PASS = PayloadVerification("PASS", "stubbed for pack-builder isolation")


def _dev_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes(range(32)))


def _write_fixture_payload(tree: Path) -> None:
    """A tiny, FLAT payload tree: the interpreter directly at the root
    (never nested, e.g. under ``bin/``) plus one site-packages file and the
    three trust artifacts -- enough to exercise real source collection and
    packing without needing a release-grade-verifier-faithful tree (the
    independent verifier is stubbed via ``check_app_payload_verification``
    in every test below)."""

    tree.mkdir(parents=True)
    (tree / "python.exe").write_bytes(b"pretend-python-exe-bytes")
    (tree / "python312.dll").write_bytes(b"pretend-python312-dll-bytes")
    site_packages = tree / "Lib" / "site-packages" / "civiccast"
    site_packages.mkdir(parents=True)
    (site_packages / "__init__.py").write_bytes(b"print('hi')\n")
    (tree / "SHA256SUMS").write_text("deadbeef  python.exe\n", encoding="utf-8")
    (tree / "LICENSE-BOM.md").write_text("# BOM\n", encoding="utf-8")
    manifest = {
        "schema_version": 7,
        "civiccast": {
            "version": "1.0.0-rc15",
            "wheel_sha256": "a" * 64,
            "source_state": {
                "head": "b" * 40,
                "dirty": False,
                "diff_sha256": "c" * 64,
                "status_sha256": "d" * 64,
            },
        },
        "files": [],
    }
    (tree / "app-payload-manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )


def _write_fixture_closure(tree: Path) -> None:
    tree.mkdir(parents=True)
    (tree / "bin").mkdir()
    (tree / "bin" / "gst-discoverer-1.0.exe").write_bytes(b"discoverer")
    (tree / "runtime-manifest.json").write_text(
        json.dumps({"gstreamer_version": "1.28.5", "lock_sha256": "e" * 64}),
        encoding="utf-8",
    )
    (tree / "SHA256SUMS").write_text("fixture\n", encoding="utf-8")
    (tree / "LICENSE-BOM.md").write_text("fixture\n", encoding="utf-8")


def test_component_identity_is_native_app_payload() -> None:
    """The builder must target the EXACT component identity
    native_pack_staging.rs's DEFAULT_REQUIRED_COMPONENTS/bridge check
    against -- a drift here would silently produce a pack neither the
    required-set gate nor the runtime\\ extraction bridge recognizes."""

    assert builder.APP_PAYLOAD_COMPONENT == APP_PAYLOAD_COMPONENT
    assert APP_PAYLOAD_COMPONENT == "native-app-payload"


def test_end_to_end_build_verifies_through_the_real_pack_trust_wire(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload_root = tmp_path / "payload"
    _write_fixture_payload(payload_root)
    closure = tmp_path / "closure"
    _write_fixture_closure(closure)
    monkeypatch.setattr(builder, "check_app_payload_verification", lambda *a, **k: _PASS)
    monkeypatch.setattr(builder.closure_verifier, "main", lambda _args: 0)

    key = _dev_key()
    output = tmp_path / "native-app-payload.ccpack"
    report = builder.build_app_payload_pack(
        output=output,
        payload_root=payload_root,
        signing_private_key=key,
        signing_key_id="development-test-key",
        product_version="0.0.0-test",
        source_sha="b" * 40,
        gstreamer_closure=closure,
    )
    assert report["component"] == "native-app-payload"
    assert report["civiccast_version"] == "1.0.0-rc15"
    assert report["civiccast_source_head"] == "b" * 40
    assert report["source_sha"] == "b" * 40
    assert report["civiccast_source_dirty"] is False

    verified = verify_native_pack(output, public_key=key.public_key())
    assert verified.component == "native-app-payload"
    assert verified.product_version == "0.0.0-test"
    assert verified.metadata["civiccast_version"] == "1.0.0-rc15"
    assert verified.metadata["civiccast_source_head"] == "b" * 40
    assert verified.metadata["source_sha"] == "b" * 40
    assert verified.metadata["interpreter_version"] == builder.INTERPRETER_VERSION
    assert verified.metadata["gstreamer_version"] == "1.28.5"
    assert verified.metadata["runtime_lock_sha256"] == "e" * 64
    with zipfile.ZipFile(output) as archive:
        assert "payload/dependencies/gstreamer/bin/gst-discoverer-1.0.exe" in archive.namelist()


def test_provisioning_layout_contract_python_exe_lands_flat_at_the_payload_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact contract native_pack_staging::pack_extraction_destination
    bridges to: once the pack is extracted at $INSTDIR\\runtime (the
    payload/ ZIP prefix stripped, same convention every other native pack
    uses), python.exe must exist DIRECTLY there -- never nested under a
    subdirectory the way native-server-binaries nests bin/initdb.exe."""

    payload_root = tmp_path / "payload"
    _write_fixture_payload(payload_root)
    closure = tmp_path / "closure"
    _write_fixture_closure(closure)
    monkeypatch.setattr(builder, "check_app_payload_verification", lambda *a, **k: _PASS)
    monkeypatch.setattr(builder.closure_verifier, "main", lambda _args: 0)

    key = _dev_key()
    output = tmp_path / "native-app-payload.ccpack"
    builder.build_app_payload_pack(
        output=output,
        payload_root=payload_root,
        signing_private_key=key,
        signing_key_id="development-test-key",
        product_version="0.0.0-test",
        source_sha="b" * 40,
        gstreamer_closure=closure,
    )

    extract_root = tmp_path / "install" / "runtime"
    with zipfile.ZipFile(output) as archive:
        for name in archive.namelist():
            if name.startswith("payload/") and not name.endswith("/"):
                relative = name.removeprefix("payload/")
                destination = extract_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(name))

    python_exe = extract_root / "python.exe"
    assert python_exe.is_file()
    assert python_exe.read_bytes() == b"pretend-python-exe-bytes"
    assert (
        hashlib.sha256(python_exe.read_bytes()).hexdigest()
        == hashlib.sha256(b"pretend-python-exe-bytes").hexdigest()
    )
    assert (extract_root / "dependencies/gstreamer/bin/gst-discoverer-1.0.exe").is_file()


def test_refuses_omitted_gstreamer_closure_before_signing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload_root = tmp_path / "payload"
    _write_fixture_payload(payload_root)
    monkeypatch.setattr(builder, "check_app_payload_verification", lambda *a, **k: _PASS)

    with pytest.raises(builder.AppPayloadPackBuildError, match="GStreamer closure is required"):
        builder.build_app_payload_pack(
            output=tmp_path / "out.ccpack",
            payload_root=payload_root,
            signing_private_key=_dev_key(),
            signing_key_id="development-test-key",
            product_version="0.0.0-test",
            source_sha="b" * 40,
            gstreamer_closure=None,
        )
    assert not (tmp_path / "out.ccpack").exists()


def test_refuses_closure_when_its_independent_verifier_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload_root = tmp_path / "payload"
    _write_fixture_payload(payload_root)
    closure = tmp_path / "closure"
    _write_fixture_closure(closure)
    monkeypatch.setattr(builder, "check_app_payload_verification", lambda *a, **k: _PASS)
    monkeypatch.setattr(builder.closure_verifier, "main", lambda _args: 1)

    with pytest.raises(builder.AppPayloadPackBuildError, match="closure verification failed"):
        builder.build_app_payload_pack(
            output=tmp_path / "out.ccpack",
            payload_root=payload_root,
            signing_private_key=_dev_key(),
            signing_key_id="development-test-key",
            product_version="0.0.0-test",
            source_sha="b" * 40,
            gstreamer_closure=closure,
        )


def test_refuses_a_payload_tree_that_fails_independent_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload_root = tmp_path / "payload"
    _write_fixture_payload(payload_root)
    closure = tmp_path / "closure"
    _write_fixture_closure(closure)
    failing = PayloadVerification("FAIL", "GPL/AGPL LICENSE RECORDED FOR: some-distribution")
    monkeypatch.setattr(builder, "check_app_payload_verification", lambda *a, **k: failing)
    monkeypatch.setattr(builder.closure_verifier, "main", lambda _args: 0)

    with pytest.raises(builder.AppPayloadPackBuildError, match="independent"):
        builder.build_app_payload_pack(
            output=tmp_path / "out.ccpack",
            payload_root=payload_root,
            signing_private_key=_dev_key(),
            signing_key_id="development-test-key",
            product_version="0.0.0-test",
            source_sha="b" * 40,
            gstreamer_closure=closure,
        )
    assert not (tmp_path / "out.ccpack").exists()


def test_refuses_a_closure_that_overlaps_the_app_payload_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload_root = tmp_path / "payload"
    _write_fixture_payload(payload_root)
    collision = payload_root / "dependencies/gstreamer/bin/gst-discoverer-1.0.exe"
    collision.parent.mkdir(parents=True)
    collision.write_bytes(b"wrong-owner")
    closure = tmp_path / "closure"
    _write_fixture_closure(closure)
    monkeypatch.setattr(builder, "check_app_payload_verification", lambda *a, **k: _PASS)
    monkeypatch.setattr(builder.closure_verifier, "main", lambda _args: 0)

    with pytest.raises(builder.AppPayloadPackBuildError, match="overlaps"):
        builder.build_app_payload_pack(
            output=tmp_path / "out.ccpack",
            payload_root=payload_root,
            signing_private_key=_dev_key(),
            signing_key_id="development-test-key",
            product_version="0.0.0-test",
            source_sha="b" * 40,
            gstreamer_closure=closure,
        )


def test_closure_content_hash_detects_a_same_size_content_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload_root = tmp_path / "payload"
    _write_fixture_payload(payload_root)
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_fixture_closure(first)
    _write_fixture_closure(second)
    (second / "bin/gst-discoverer-1.0.exe").write_bytes(b"different!")
    monkeypatch.setattr(builder, "check_app_payload_verification", lambda *a, **k: _PASS)
    monkeypatch.setattr(builder.closure_verifier, "main", lambda _args: 0)

    common = {
        "payload_root": payload_root,
        "signing_private_key": _dev_key(),
        "signing_key_id": "development-test-key",
        "product_version": "0.0.0-test",
        "source_sha": "b" * 40,
    }
    one = builder.build_app_payload_pack(
        output=tmp_path / "one.ccpack", gstreamer_closure=first, **common
    )
    two = builder.build_app_payload_pack(
        output=tmp_path / "two.ccpack", gstreamer_closure=second, **common
    )
    assert one["closure_file_count"] == two["closure_file_count"]
    assert one["closure_payload_bytes"] == two["closure_payload_bytes"]
    assert one["closure_payload_tree_sha256"] != two["closure_payload_tree_sha256"]


def test_refuses_a_missing_payload_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(builder, "check_app_payload_verification", lambda *a, **k: _PASS)
    with pytest.raises(builder.AppPayloadPackBuildError, match="is missing"):
        builder.build_app_payload_pack(
            output=tmp_path / "out.ccpack",
            payload_root=tmp_path / "does-not-exist",
            signing_private_key=_dev_key(),
            signing_key_id="development-test-key",
            product_version="0.0.0-test",
            source_sha="b" * 40,
        )


def test_refuses_an_empty_payload_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty directory is a REAL directory but has nothing to pack --
    refuse before ``build_native_pack`` has to (its own message is more
    generic; catching it here gives an app-payload-specific diagnostic)."""

    payload_root = tmp_path / "empty-payload"
    payload_root.mkdir()
    closure = tmp_path / "closure"
    _write_fixture_closure(closure)
    monkeypatch.setattr(builder, "check_app_payload_verification", lambda *a, **k: _PASS)
    monkeypatch.setattr(builder.closure_verifier, "main", lambda _args: 0)

    with pytest.raises(Exception, match="manifest"):
        builder.build_app_payload_pack(
            output=tmp_path / "out.ccpack",
            payload_root=payload_root,
            signing_private_key=_dev_key(),
            signing_key_id="development-test-key",
            product_version="0.0.0-test",
            source_sha="b" * 40,
            gstreamer_closure=closure,
        )


def test_development_signing_key_requires_explicit_nonrelease_switch() -> None:
    with pytest.raises(builder.AppPayloadPackBuildError, match="allow-development-key"):
        builder.require_allowed_signing_key(
            "development-civiccast-native", allow_development_key=False
        )
    builder.require_allowed_signing_key("development-civiccast-native", allow_development_key=True)
    builder.require_allowed_signing_key("civiccast-production-2026", allow_development_key=False)


def test_compatible_core_defaults_to_product_version_when_omitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload_root = tmp_path / "payload"
    _write_fixture_payload(payload_root)
    closure = tmp_path / "closure"
    _write_fixture_closure(closure)
    monkeypatch.setattr(builder, "check_app_payload_verification", lambda *a, **k: _PASS)
    monkeypatch.setattr(builder.closure_verifier, "main", lambda _args: 0)

    report = builder.build_app_payload_pack(
        output=tmp_path / "out.ccpack",
        payload_root=payload_root,
        signing_private_key=_dev_key(),
        signing_key_id="development-test-key",
        product_version="0.0.0-test",
        source_sha="b" * 40,
        gstreamer_closure=closure,
    )
    verified = verify_native_pack(
        tmp_path / "out.ccpack",
        public_key=Ed25519PrivateKey.from_private_bytes(bytes(range(32))).public_key(),
    )
    assert report["product_version"] == "0.0.0-test"
    assert verified.compatible_core == "0.0.0-test"


@pytest.mark.parametrize("source_sha", [None, "B" * 40, "b" * 39, "g" * 40])
def test_refuses_missing_or_malformed_source_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source_sha: object
) -> None:
    payload_root = tmp_path / "payload"
    _write_fixture_payload(payload_root)
    monkeypatch.setattr(builder, "check_app_payload_verification", lambda *a, **k: _PASS)

    with pytest.raises(builder.AppPayloadPackBuildError, match="source SHA"):
        builder.build_app_payload_pack(
            output=tmp_path / "out.ccpack",
            payload_root=payload_root,
            signing_private_key=_dev_key(),
            signing_key_id="development-test-key",
            product_version="0.0.0-test",
            source_sha=source_sha,
        )


def test_refuses_source_sha_that_does_not_match_payload_source_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload_root = tmp_path / "payload"
    _write_fixture_payload(payload_root)
    closure = tmp_path / "closure"
    _write_fixture_closure(closure)
    monkeypatch.setattr(builder, "check_app_payload_verification", lambda *a, **k: _PASS)
    monkeypatch.setattr(builder.closure_verifier, "main", lambda _args: 0)

    with pytest.raises(builder.AppPayloadPackBuildError, match="does not match"):
        builder.build_app_payload_pack(
            output=tmp_path / "out.ccpack",
            payload_root=payload_root,
            signing_private_key=_dev_key(),
            signing_key_id="development-test-key",
            product_version="0.0.0-test",
            source_sha="a" * 40,
            gstreamer_closure=closure,
        )
