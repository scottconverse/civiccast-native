# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Signed deterministic native component-pack contract."""

from __future__ import annotations

import base64
import json
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import civiccast.installer.native_packs as native_packs
from civiccast.installer.native_packs import (
    NativePackVerificationError,
    build_native_pack,
    verify_native_pack,
)
from civiccast.native.app_payload import CAPTION_PACK_CONTRACT, WHISPER_MODEL_FILES


def _key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes(range(32)))


def test_reviewed_model_pack_contract_uses_the_inference_proven_runtime() -> None:
    lock = native_packs._load_reviewed_ollama_model_lock()

    assert lock["ollama_runtime_version"] == "0.30.6"


def _sources(tmp_path: Path) -> dict[str, Path]:
    runtime = tmp_path / "whisper-cli.exe"
    model = tmp_path / "ggml-large-v3-q5_0.bin"
    runtime.write_bytes(b"reproducible whisper runtime")
    model.write_bytes(b"verified large-v3 model")
    return {
        "models/ggml-large-v3-q5_0.bin": model,
        "runtime/whisper-cli.exe": runtime,
    }


def _rewrite_signed_manifest(
    source_pack: Path,
    target_pack: Path,
    *,
    key: Ed25519PrivateKey,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    with (
        zipfile.ZipFile(source_pack, "r") as source,
        zipfile.ZipFile(target_pack, "w", compression=zipfile.ZIP_STORED) as target,
    ):
        manifest = json.loads(source.read("manifest.json"))
        mutate(manifest)
        manifest_bytes = (
            json.dumps(
                manifest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
        signature = base64.b64encode(key.sign(manifest_bytes)) + b"\n"
        for info in source.infolist():
            if info.filename == "manifest.json":
                payload = manifest_bytes
            elif info.filename == "manifest.sig":
                payload = signature
            else:
                payload = source.read(info)
            target.writestr(info, payload)


def _source_bound_pack(
    tmp_path: Path, component: str, metadata: dict[str, Any]
) -> tuple[Path, Ed25519PrivateKey]:
    key = _key()
    pack = tmp_path / f"{component}.ccpack"
    build_native_pack(
        output=pack,
        component=component,
        product_version="1.0.0-rc15",
        compatible_core="1.0.0-rc15",
        sources=_sources(tmp_path),
        signing_private_key=key,
        signing_key_id="development-test-key",
        metadata={"source_sha": "a" * 40, **metadata},
    )
    return pack, key


@pytest.mark.parametrize(
    "component",
    ["native-app-payload", "native-server-binaries"],
)
@pytest.mark.parametrize("invalid_source_sha", [None, "A" * 40, "a" * 39, "g" * 40])
def test_source_bound_named_pack_rejects_missing_or_malformed_signed_source_sha(
    tmp_path: Path, component: str, invalid_source_sha: object
) -> None:
    pack, key = _source_bound_pack(
        tmp_path,
        component,
        {"civiccast_source_head": "a" * 40} if component == "native-app-payload" else {},
    )
    mutated = tmp_path / f"invalid-{component}.ccpack"
    _rewrite_signed_manifest(
        pack,
        mutated,
        key=key,
        mutate=lambda manifest: manifest["metadata"].__setitem__("source_sha", invalid_source_sha),
    )

    with pytest.raises(NativePackVerificationError, match="source SHA"):
        verify_native_pack(mutated, public_key=key.public_key())


def test_app_payload_rejects_a_signed_source_sha_substitution(tmp_path: Path) -> None:
    pack, key = _source_bound_pack(
        tmp_path,
        "native-app-payload",
        {"civiccast_source_head": "a" * 40},
    )
    substituted = tmp_path / "substituted-app-payload.ccpack"
    _rewrite_signed_manifest(
        pack,
        substituted,
        key=key,
        mutate=lambda manifest: manifest["metadata"].__setitem__("source_sha", "b" * 40),
    )

    with pytest.raises(NativePackVerificationError, match="does not match"):
        verify_native_pack(substituted, public_key=key.public_key())


def test_native_pack_is_byte_reproducible_and_verifies(tmp_path: Path) -> None:
    key = _key()
    sources = _sources(tmp_path)
    first = tmp_path / "first.ccpack"
    second = tmp_path / "second.ccpack"
    metadata = {
        "model_architecture": "large-v3",
        "model_quantization": "q5_0",
        "runtime_backend": "whispercpp-vulkan",
    }

    first_result = build_native_pack(
        output=first,
        component="test-fixture",
        product_version="1.0.0-rc15",
        compatible_core="1.0.0-rc15",
        sources=sources,
        signing_private_key=key,
        signing_key_id="development-test-key",
        metadata=metadata,
    )
    second_result = build_native_pack(
        output=second,
        component="test-fixture",
        product_version="1.0.0-rc15",
        compatible_core="1.0.0-rc15",
        sources=sources,
        signing_private_key=key,
        signing_key_id="development-test-key",
        metadata=metadata,
    )

    assert first.read_bytes() == second.read_bytes()
    assert first_result.sha256 == second_result.sha256
    verified = verify_native_pack(
        first,
        public_key=key.public_key(),
        expected_component="test-fixture",
        expected_product_version="1.0.0-rc15",
        expected_signing_key_id="development-test-key",
    )
    assert verified.file_count == 2
    assert verified.total_bytes == sum(path.stat().st_size for path in sources.values())
    assert verified.metadata == metadata


def test_payload_tree_sha256_is_stable_across_different_signing_keys(tmp_path: Path) -> None:
    """The reproducible-build claim this field exists to prove: two packs
    built from IDENTICAL payload content, signed with two DIFFERENT
    (machine-local) development keys, must agree on ``payload_tree_sha256``
    even though their ``pack_sha256``/``signing_key_id`` necessarily differ
    -- mirroring the real controller/R7/TESTER1 evidence (same commit,
    three different development keys, three different pack hashes, same
    size/count, and no prior way to prove the payload bytes actually
    matched)."""

    sources = _sources(tmp_path)
    key_a = _key()
    key_b = Ed25519PrivateKey.generate()

    result_a = build_native_pack(
        output=tmp_path / "a.ccpack",
        component="test-fixture",
        product_version="1.0.0-rc15",
        compatible_core="1.0.0-rc15",
        sources=sources,
        signing_private_key=key_a,
        signing_key_id="development-machine-a-1111",
    )
    result_b = build_native_pack(
        output=tmp_path / "b.ccpack",
        component="test-fixture",
        product_version="1.0.0-rc15",
        compatible_core="1.0.0-rc15",
        sources=sources,
        signing_private_key=key_b,
        signing_key_id="development-machine-b-2222",
    )

    # Different signing keys/ids -> different signed container bytes. This
    # is expected and is NOT the claim under test.
    assert result_a.sha256 != result_b.sha256
    assert result_a.signing_key_id != result_b.signing_key_id

    # Same payload content -> same payload_tree_sha256, on both the
    # in-memory build result AND an independent re-verification of each
    # pack on disk (so the equality is not an artifact of reusing one
    # in-process computation).
    assert result_a.payload_tree_sha256 == result_b.payload_tree_sha256

    verified_a = verify_native_pack(tmp_path / "a.ccpack", public_key=key_a.public_key())
    verified_b = verify_native_pack(tmp_path / "b.ccpack", public_key=key_b.public_key())
    assert verified_a.payload_tree_sha256 == verified_b.payload_tree_sha256
    assert verified_a.payload_tree_sha256 == result_a.payload_tree_sha256


def test_payload_tree_sha256_changes_when_one_payload_byte_changes(tmp_path: Path) -> None:
    key = _key()
    sources = _sources(tmp_path)
    baseline = build_native_pack(
        output=tmp_path / "baseline.ccpack",
        component="test-fixture",
        product_version="1.0.0-rc15",
        compatible_core="1.0.0-rc15",
        sources=sources,
        signing_private_key=key,
        signing_key_id="development-test-key",
    )

    tampered_model = tmp_path / "tampered-model.bin"
    original_bytes = sources["models/ggml-large-v3-q5_0.bin"].read_bytes()
    tampered_model.write_bytes(original_bytes[:-1] + bytes([original_bytes[-1] ^ 0x01]))
    tampered_sources = dict(sources)
    tampered_sources["models/ggml-large-v3-q5_0.bin"] = tampered_model

    tampered = build_native_pack(
        output=tmp_path / "tampered.ccpack",
        component="test-fixture",
        product_version="1.0.0-rc15",
        compatible_core="1.0.0-rc15",
        sources=tampered_sources,
        signing_private_key=key,
        signing_key_id="development-test-key",
    )

    # Same file count and total byte count (one byte flipped, not resized)
    # -- proving payload_tree_sha256 catches what size/count alone cannot.
    assert baseline.file_count == tampered.file_count
    assert baseline.total_bytes == tampered.total_bytes
    assert baseline.payload_tree_sha256 != tampered.payload_tree_sha256


def test_payload_tree_sha256_changes_when_a_payload_file_is_renamed(tmp_path: Path) -> None:
    key = _key()
    sources = _sources(tmp_path)
    baseline = build_native_pack(
        output=tmp_path / "baseline.ccpack",
        component="test-fixture",
        product_version="1.0.0-rc15",
        compatible_core="1.0.0-rc15",
        sources=sources,
        signing_private_key=key,
        signing_key_id="development-test-key",
    )

    renamed_sources = dict(sources)
    renamed_sources["models/renamed-large-v3.bin"] = renamed_sources.pop(
        "models/ggml-large-v3-q5_0.bin"
    )
    renamed = build_native_pack(
        output=tmp_path / "renamed.ccpack",
        component="test-fixture",
        product_version="1.0.0-rc15",
        compatible_core="1.0.0-rc15",
        sources=renamed_sources,
        signing_private_key=key,
        signing_key_id="development-test-key",
    )

    # Same file count and total byte count (identical bytes, only the path
    # changed) -- the exact case size/count comparison cannot distinguish.
    assert baseline.file_count == renamed.file_count
    assert baseline.total_bytes == renamed.total_bytes
    assert baseline.payload_tree_sha256 != renamed.payload_tree_sha256


def test_payload_tree_sha256_recipe_is_documented_and_order_independent() -> None:
    """Direct unit test of the documented recipe against hand-built entries
    (no pack build involved): sorts by path before hashing, so a caller
    passing entries in a different order still gets the same digest -- a
    reordered directory walk cannot change the result."""

    entries_in_one_order = [
        {"path": "share/zzz.sql", "bytes": 3, "sha256": "1" * 64},
        {"path": "bin/aaa.exe", "bytes": 1, "sha256": "2" * 64},
        {"path": "bin/mmm.dll", "bytes": 2, "sha256": "3" * 64},
    ]
    entries_in_another_order = list(reversed(entries_in_one_order))

    first = native_packs.payload_tree_sha256(entries_in_one_order)
    second = native_packs.payload_tree_sha256(entries_in_another_order)
    assert first == second

    # Sanity: it is a real SHA-256 hex digest, not a placeholder.
    assert len(first) == 64
    assert all(character in "0123456789abcdef" for character in first)


def test_native_pack_binds_compatible_core_identity(tmp_path: Path) -> None:
    key = _key()
    pack = tmp_path / "captions.ccpack"
    build_native_pack(
        output=pack,
        component="test-fixture",
        product_version="1.0.0-rc15",
        compatible_core="different-core",
        sources=_sources(tmp_path),
        signing_private_key=key,
        signing_key_id="development-test-key",
    )

    with pytest.raises(NativePackVerificationError, match="compatible core"):
        verify_native_pack(
            pack,
            public_key=key.public_key(),
            expected_component="test-fixture",
            expected_product_version="1.0.0-rc15",
            expected_compatible_core="1.0.0-rc15",
        )


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "CON",
        "models/AUX.bin",
        "models/model.bin.",
        "models/model.bin ",
        "models/model?.bin",
        "models/control\x1f.bin",
    ],
)
def test_native_pack_rejects_nonportable_windows_payload_paths(
    tmp_path: Path,
    unsafe_path: str,
) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")

    with pytest.raises(NativePackVerificationError, match="unsafe"):
        build_native_pack(
            output=tmp_path / "unsafe.ccpack",
            component="core",
            product_version="1.0.0-rc15",
            compatible_core="1.0.0-rc15",
            sources={unsafe_path: source},
            signing_private_key=_key(),
            signing_key_id="development-test-key",
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda manifest: manifest.__setitem__("file_count", True),
        lambda manifest: manifest.__setitem__("total_bytes", True),
        lambda manifest: manifest.__setitem__("unexpected", "signed-but-unsupported"),
        lambda manifest: manifest.__setitem__("component", " core "),
    ],
)
def test_native_pack_rejects_malformed_signed_manifest_shapes(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    key = _key()
    payload = tmp_path / "one-byte.bin"
    payload.write_bytes(b"x")
    source_pack = tmp_path / "source.ccpack"
    build_native_pack(
        output=source_pack,
        component="core",
        product_version="1.0.0-rc15",
        compatible_core="1.0.0-rc15",
        sources={"runtime/one-byte.bin": payload},
        signing_private_key=key,
        signing_key_id="development-test-key",
    )
    mutated_pack = tmp_path / "mutated.ccpack"
    _rewrite_signed_manifest(
        source_pack,
        mutated_pack,
        key=key,
        mutate=mutate,
    )

    with pytest.raises(NativePackVerificationError, match=r"manifest|field|count|byte"):
        verify_native_pack(mutated_pack, public_key=key.public_key())


def test_native_pack_rejects_mutated_payload_before_extraction(tmp_path: Path) -> None:
    key = _key()
    pack = tmp_path / "captions.ccpack"
    build_native_pack(
        output=pack,
        component="test-fixture",
        product_version="1.0.0-rc15",
        compatible_core="1.0.0-rc15",
        sources=_sources(tmp_path),
        signing_private_key=key,
        signing_key_id="development-test-key",
    )
    mutated = tmp_path / "mutated.ccpack"
    with zipfile.ZipFile(pack, "r") as source, zipfile.ZipFile(mutated, "w") as target:
        for info in source.infolist():
            payload = source.read(info)
            if info.filename == "payload/runtime/whisper-cli.exe":
                payload += b"mutation"
            target.writestr(info, payload)

    with pytest.raises(NativePackVerificationError, match=r"size|SHA-256"):
        verify_native_pack(
            mutated,
            public_key=key.public_key(),
            expected_component="test-fixture",
        )


def test_native_pack_rejects_extra_duplicate_and_unsafe_entries(tmp_path: Path) -> None:
    key = _key()
    pack = tmp_path / "captions.ccpack"
    build_native_pack(
        output=pack,
        component="test-fixture",
        product_version="1.0.0-rc15",
        compatible_core="1.0.0-rc15",
        sources=_sources(tmp_path),
        signing_private_key=key,
        signing_key_id="development-test-key",
    )

    for name in ("payload/extra.exe", "payload/../escape.exe"):
        candidate = tmp_path / f"{name.replace('/', '-')}.ccpack"
        with zipfile.ZipFile(pack, "r") as source, zipfile.ZipFile(candidate, "w") as target:
            for info in source.infolist():
                target.writestr(info, source.read(info))
            target.writestr(name, b"not authorized")
        with pytest.raises(NativePackVerificationError, match=r"unsafe|unexpected"):
            verify_native_pack(candidate, public_key=key.public_key())

    duplicate = tmp_path / "duplicate.ccpack"
    with zipfile.ZipFile(pack, "r") as source, zipfile.ZipFile(duplicate, "w") as target:
        for info in source.infolist():
            target.writestr(info, source.read(info))
        target.writestr("payload/runtime/WHISPER-CLI.EXE", b"case collision")
    with pytest.raises(NativePackVerificationError, match=r"duplicate|unexpected"):
        verify_native_pack(duplicate, public_key=key.public_key())


def test_native_pack_rejects_wrong_signing_key_and_component(tmp_path: Path) -> None:
    key = _key()
    pack = tmp_path / "captions.ccpack"
    build_native_pack(
        output=pack,
        component="test-fixture",
        product_version="1.0.0-rc15",
        compatible_core="1.0.0-rc15",
        sources=_sources(tmp_path),
        signing_private_key=key,
        signing_key_id="development-test-key",
    )

    with pytest.raises(NativePackVerificationError, match="signature"):
        verify_native_pack(
            pack,
            public_key=Ed25519PrivateKey.generate().public_key(),
        )
    with pytest.raises(NativePackVerificationError, match="component"):
        verify_native_pack(
            pack,
            public_key=key.public_key(),
            expected_component="core",
        )


def test_caption_pack_rejects_a_signed_smaller_model_substitution(tmp_path: Path) -> None:
    key = _key()

    with pytest.raises(
        NativePackVerificationError,
        match=r"large-v3|substituted|unapproved",
    ):
        build_native_pack(
            output=tmp_path / "smaller-caption.ccpack",
            component="captions-large-v3",
            product_version="1.0.0-rc15",
            compatible_core="1.0.0-rc15",
            sources=_sources(tmp_path),
            signing_private_key=key,
            signing_key_id="development-test-key",
            metadata={
                "model_architecture": "large-v3",
                "model_file": "ggml-large-v3-q5_0.bin",
                "model_quantization": "q5_0",
                "model_repository": "ggerganov/whisper.cpp",
                "model_revision": "5359861c739e955e79d9a303bcbc70fb988958b1",
                "model_sha256": (
                    "d75795ecff3f83b5faa89d1900604ad8c780abd5739fae406de19f23ecd98ad1"
                ),
                "required_gpu_api": "Vulkan >= 1.3",
                "runtime_backend": "whispercpp-vulkan",
                "runtime_commit": "f049fff95a089aa9969deb009cdd4892b3e74916",
                "runtime_sha256": (
                    "a86a958927e8809a9df592c99e292ae79353fac59029847ad7a949c7920761c8"
                ),
                "runtime_version": "v1.9.1",
                "vc_runtime_version": "14.50.35719.0",
            },
        )


def _valid_caption_manifest() -> dict[str, Any]:
    return {
        "component": native_packs.CAPTION_COMPONENT,
        "files": [
            {
                "path": f"models/faster-whisper-large-v3/{name}",
                "bytes": size,
                "sha256": digest,
            }
            for name, (size, digest) in WHISPER_MODEL_FILES.items()
        ]
        + [
            {
                "path": native_packs.CAPTION_SELF_TEST_PATH,
                "bytes": native_packs.CAPTION_SELF_TEST_BYTES,
                "sha256": native_packs.CAPTION_SELF_TEST_SHA256,
            }
        ],
        "metadata": {**CAPTION_PACK_CONTRACT, "caption_tiers": ["large-v3"]},
    }


def test_caption_pack_contract_rejects_a_missing_real_self_test_fixture() -> None:
    manifest = _valid_caption_manifest()
    manifest["files"] = [
        item for item in manifest["files"] if item["path"] != native_packs.CAPTION_SELF_TEST_PATH
    ]

    with pytest.raises(NativePackVerificationError, match=r"self-test/jfk\.wav"):
        native_packs._validate_component_contract(manifest)


def test_caption_pack_contract_accepts_only_the_cpu_faster_whisper_baseline() -> None:
    manifest = _valid_caption_manifest()

    native_packs._validate_component_contract(manifest)

    manifest["metadata"]["runtime_device"] = "cuda"
    with pytest.raises(
        NativePackVerificationError,
        match=r"metadata mismatch: runtime_device",
    ):
        native_packs._validate_component_contract(manifest)


def test_caption_pack_contract_rejects_missing_or_substituted_model_files() -> None:
    missing = _valid_caption_manifest()
    missing["files"] = [
        item
        for item in missing["files"]
        if item["path"] != "models/faster-whisper-large-v3/tokenizer.json"
    ]
    with pytest.raises(NativePackVerificationError, match=r"missing .*tokenizer\.json"):
        native_packs._validate_component_contract(missing)

    substituted = _valid_caption_manifest()
    model = next(
        item
        for item in substituted["files"]
        if item["path"] == "models/faster-whisper-large-v3/model.bin"
    )
    model["sha256"] = "0" * 64
    with pytest.raises(NativePackVerificationError, match=r"substituted unapproved bytes"):
        native_packs._validate_component_contract(substituted)


def test_model_pack_rejects_signed_bytes_outside_the_reviewed_lock(
    tmp_path: Path,
) -> None:
    key = _key()
    tiny = tmp_path / "tiny.bin"
    tiny.write_bytes(b"signed but substituted")
    sources = {
        "MODEL-PROVENANCE.json": tiny,
        "manifests/registry.ollama.ai/library/gemma4/e4b": tiny,
        ("blobs/sha256-f0988ff50a2458c598ff6b1b87b94d0f5c44d73061c2795391878b00b2285e11"): tiny,
        ("blobs/sha256-4c27e0f5b5adf02ac956c7322bd2ee7636fe3f45a8512c9aba5385242cb6e09a"): tiny,
        ("blobs/sha256-7339fa418c9ad3e8e12e74ad0fd26a9cc4be8703f9c110728a992b193be85cb2"): tiny,
        ("blobs/sha256-56380ca2ab89f1f68c283f4d50863c0bcab52ae3f1b9a88e4ab5617b176f71a3"): tiny,
    }

    with pytest.raises(
        NativePackVerificationError,
        match=r"reviewed model lock|substituted",
    ):
        build_native_pack(
            output=tmp_path / "substituted-model.ccpack",
            component="summary-gemma4-e4b",
            product_version="1.0.0-rc15",
            compatible_core="1.0.0-rc15",
            sources=sources,
            signing_private_key=key,
            signing_key_id="development-test-key",
            metadata={
                "manifest_sha256": (
                    "c6eb396dbd5992bbe3f5cdb947e8bbc0ee413d7c17e2beaae69f5d569cf982eb"
                ),
                "model_name": "gemma4-e4b",
                "ollama_runtime_version": "0.30.6",
            },
        )
