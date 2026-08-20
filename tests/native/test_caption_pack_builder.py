# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Pinned-input and signing-policy tests for the native caption pack."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import civiccast.installer.native_packs as native_packs
from civiccast.installer.native_packs import verify_native_pack
from civiccast.native.caption_tiers import (
    CAPTION_TIER_REGISTRY,
    CaptionTierBindingError,
    CaptionTierSpec,
)


def _load() -> object:
    path = Path(__file__).resolve().parents[2] / "scripts" / "build_native_caption_pack.py"
    spec = importlib.util.spec_from_file_location("build_native_caption_pack", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


builder = _load()


def test_builder_pins_a_real_caption_self_test_fixture() -> None:
    assert "self_test_audio" in inspect.signature(builder.build_caption_pack).parameters
    assert builder.CAPTION_SELF_TEST_FILENAME == "jfk.wav"
    assert builder.CAPTION_SELF_TEST_BYTES == 352_078
    assert (
        builder.CAPTION_SELF_TEST_SHA256
        == "59dfb9a4acb36fe2a2affc14bacbee2920ff435cb13cc314a08c13f66ba7860e"
    )


def test_builder_contract_is_the_accepted_faster_whisper_large_v3_runtime() -> None:
    assert builder.FASTER_WHISPER_VERSION == "1.2.1"
    assert builder.CTRANSLATE2_VERSION == "4.8.1"
    assert builder.WHISPER_MODEL_REPO == "Systran/faster-whisper-large-v3"
    assert builder.WHISPER_MODEL_REVISION == "edaa852ec7e145841d8ffdb056a99866b5f0a478"
    assert builder.WHISPER_MODEL_FILES["model.bin"] == (
        3_087_284_237,
        "69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1",
    )
    source = inspect.getsource(builder)
    assert "whispercpp-vulkan" not in source
    assert "q5_0" not in source
    assert "Runtime backend: CPU faster-whisper, local-files-only" in source
    assert "Runtime backend: CUDA faster-whisper" not in source


def test_pinned_input_validation_accepts_only_exact_bytes(tmp_path: Path) -> None:
    payload = tmp_path / "runtime.exe"
    payload.write_bytes(b"reviewed bytes")
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()

    builder.validate_pinned_file(
        payload,
        expected_bytes=payload.stat().st_size,
        expected_sha256=digest,
        label="test runtime",
    )

    payload.write_bytes(b"mutated bytes")
    with pytest.raises(ValueError, match=r"SHA-256|byte length"):
        builder.validate_pinned_file(
            payload,
            expected_bytes=len(b"reviewed bytes"),
            expected_sha256=digest,
            label="test runtime",
        )


def test_builder_packs_a_bound_additional_tier_alongside_large_v3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: ``additional_tier_model_dirs`` produces a real signed pack
    that ``native_packs.verify_caption_pack_tiers`` accepts as a genuine
    two-tier pack -- proving the builder and the verifier agree on the SAME
    per-tier inventory, sourced from the registry rather than hand-typed
    twice in two places (the class of bug the R7 tester hit)."""

    def _write(path: Path, body: bytes) -> tuple[int, str]:
        path.write_bytes(body)
        return len(body), hashlib.sha256(body).hexdigest()

    model_dir = tmp_path / "large-v3-snapshot"
    model_dir.mkdir()
    tiny_large_v3_files = {
        "config.json": _write(model_dir / "config.json", b"large-v3-cfg"),
        "model.bin": _write(model_dir / "model.bin", b"large-v3-weights"),
    }
    monkeypatch.setattr(builder, "WHISPER_MODEL_FILES", tiny_large_v3_files)
    monkeypatch.setitem(
        CAPTION_TIER_REGISTRY,
        "large-v3",
        CaptionTierSpec(
            tier_id="large-v3",
            model_directory="faster-whisper-large-v3",
            model_repository="Systran/faster-whisper-large-v3",
            model_revision="0" * 40,
            files=tiny_large_v3_files,
            pending=False,
        ),
    )

    floor_dir = tmp_path / "floor-snapshot"
    floor_dir.mkdir()
    tiny_floor_files = {"config.json": _write(floor_dir / "config.json", b"floor-cfg")}
    monkeypatch.setitem(
        CAPTION_TIER_REGISTRY,
        "floor",
        CaptionTierSpec(
            tier_id="floor",
            model_directory="tiny-floor",
            model_repository="Systran/faster-whisper-medium",
            model_revision="1" * 40,
            files=tiny_floor_files,
            pending=False,
        ),
    )

    self_test_audio = tmp_path / "jfk.wav"
    audio_bytes, audio_sha256 = _write(self_test_audio, b"tiny-self-test-audio")
    monkeypatch.setattr(builder, "CAPTION_SELF_TEST_BYTES", audio_bytes)
    monkeypatch.setattr(builder, "CAPTION_SELF_TEST_SHA256", audio_sha256)
    monkeypatch.setattr(native_packs, "CAPTION_SELF_TEST_BYTES", audio_bytes)
    monkeypatch.setattr(native_packs, "CAPTION_SELF_TEST_SHA256", audio_sha256)

    whisper_license = tmp_path / "whisper-license.txt"
    wl_bytes, wl_sha256 = _write(whisper_license, b"MIT license text")
    monkeypatch.setattr(builder, "WHISPER_LICENSE_BYTES", wl_bytes)
    monkeypatch.setattr(builder, "WHISPER_LICENSE_SHA256", wl_sha256)

    self_test_license = tmp_path / "self-test-license.txt"
    sl_bytes, sl_sha256 = _write(self_test_license, b"self-test fixture license text")
    monkeypatch.setattr(builder, "SELF_TEST_LICENSE_BYTES", sl_bytes)
    monkeypatch.setattr(builder, "SELF_TEST_LICENSE_SHA256", sl_sha256)

    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    output = tmp_path / "captions.ccpack"

    report = builder.build_caption_pack(
        output=output,
        model_dir=model_dir,
        self_test_audio=self_test_audio,
        whisper_license=whisper_license,
        self_test_license=self_test_license,
        signing_private_key=key,
        signing_key_id="development-test-key",
        product_version="0.0.0-test",
        additional_tier_model_dirs={"floor": floor_dir},
    )

    assert report["component"] == "captions-large-v3"
    verified = verify_native_pack(output, public_key=key.public_key())
    assert verified.metadata["caption_tiers"] == ["large-v3", "floor"]


def test_builder_refuses_an_unbound_additional_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unbound (pending) tier must refuse, not silently ship without it
    or ship a broken inventory.

    The floor tier itself was this exact placeholder until the owner's
    BINDING ruling (``OWNER-DECISION-caption-adaptive-tier.md``, 2026-07-30)
    named ``medium`` and :data:`CAPTION_TIER_REGISTRY`'s real floor entry was
    bound to it. This test monkeypatches a synthetic pending placeholder
    under the ``floor`` id (the real registry's floor entry is bound now, so
    it can no longer exercise this refusal on its own) so the builder's
    unbound-tier refusal stays covered regardless of the real registry's
    current binding state.
    """

    def _write(path: Path, body: bytes) -> tuple[int, str]:
        path.write_bytes(body)
        return len(body), hashlib.sha256(body).hexdigest()

    model_dir = tmp_path / "large-v3-snapshot"
    model_dir.mkdir()
    tiny_large_v3_files = {"config.json": _write(model_dir / "config.json", b"large-v3-cfg")}
    monkeypatch.setattr(builder, "WHISPER_MODEL_FILES", tiny_large_v3_files)
    monkeypatch.setitem(
        CAPTION_TIER_REGISTRY,
        "floor",
        CaptionTierSpec(
            tier_id="floor",
            model_directory="floor-tier-pending-owner-binding",
            model_repository=None,
            model_revision=None,
            files={},
            pending=True,
        ),
    )

    with pytest.raises(CaptionTierBindingError, match="floor"):
        builder.build_caption_pack(
            output=tmp_path / "captions.ccpack",
            model_dir=model_dir,
            self_test_audio=tmp_path / "jfk.wav",
            whisper_license=tmp_path / "whisper-license.txt",
            self_test_license=tmp_path / "self-test-license.txt",
            signing_private_key=Ed25519PrivateKey.from_private_bytes(bytes(range(32))),
            signing_key_id="development-test-key",
            product_version="0.0.0-test",
            additional_tier_model_dirs={"floor": tmp_path / "floor-snapshot"},
        )


def test_cli_wires_floor_model_dir_to_the_floor_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--floor-model-dir`` is the CLI surface for gap #1: the builder CLI used to
    wire ONLY large-v3, so a floor caption pack could never actually be built from
    the command line even though ``build_caption_pack`` itself already accepted
    ``additional_tier_model_dirs``. This proves the new flag reaches that parameter
    keyed on :data:`civiccast.native.caption_tiers.FLOOR_TIER_ID`, not a hand-typed
    string."""

    from civiccast.native.caption_tiers import FLOOR_TIER_ID

    captured: dict[str, object] = {}

    def fake_build_caption_pack(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"component": "captions-large-v3"}

    monkeypatch.setattr(builder, "build_caption_pack", fake_build_caption_pack)
    monkeypatch.setattr(builder, "load_ed25519_private_key", lambda _path: object())

    floor_dir = tmp_path / "floor-snapshot"
    floor_dir.mkdir()

    monkeypatch.setattr(
        "sys.argv",
        [
            "build_native_caption_pack.py",
            "--output",
            str(tmp_path / "captions.ccpack"),
            "--model-dir",
            str(tmp_path / "large-v3-snapshot"),
            "--self-test-audio",
            str(tmp_path / "jfk.wav"),
            "--whisper-license",
            str(tmp_path / "whisper-license.txt"),
            "--self-test-license",
            str(tmp_path / "self-test-license.txt"),
            "--signing-private-key",
            str(tmp_path / "key.pem"),
            "--signing-key-id",
            "development-test-key",
            "--allow-development-key",
            "--floor-model-dir",
            str(floor_dir),
        ],
    )

    assert builder.main() == 0
    assert captured["additional_tier_model_dirs"] == {FLOOR_TIER_ID: floor_dir.resolve()}


def test_cli_omits_additional_tiers_when_no_floor_model_dir_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unchanged default: no ``--floor-model-dir`` -> the pack stays large-v3-only,
    exactly as ``build_caption_pack``'s docstring promises for today's real release
    invocation."""

    captured: dict[str, object] = {}

    def fake_build_caption_pack(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"component": "captions-large-v3"}

    monkeypatch.setattr(builder, "build_caption_pack", fake_build_caption_pack)
    monkeypatch.setattr(builder, "load_ed25519_private_key", lambda _path: object())

    monkeypatch.setattr(
        "sys.argv",
        [
            "build_native_caption_pack.py",
            "--output",
            str(tmp_path / "captions.ccpack"),
            "--model-dir",
            str(tmp_path / "large-v3-snapshot"),
            "--self-test-audio",
            str(tmp_path / "jfk.wav"),
            "--whisper-license",
            str(tmp_path / "whisper-license.txt"),
            "--self-test-license",
            str(tmp_path / "self-test-license.txt"),
            "--signing-private-key",
            str(tmp_path / "key.pem"),
            "--signing-key-id",
            "development-test-key",
            "--allow-development-key",
        ],
    )

    assert builder.main() == 0
    assert captured["additional_tier_model_dirs"] is None


def test_development_signing_key_requires_explicit_nonrelease_switch() -> None:
    with pytest.raises(ValueError, match="allow-development-key"):
        builder.require_allowed_signing_key(
            "development-civiccast-native",
            allow_development_key=False,
        )

    builder.require_allowed_signing_key(
        "development-civiccast-native",
        allow_development_key=True,
    )
    builder.require_allowed_signing_key(
        "civiccast-production-2026",
        allow_development_key=False,
    )
