# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""End-to-end build contract for the five required native station packs."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from civiccast.installer.native_distribution import (
    REQUIRED_COMPONENTS,
    verify_distribution_index,
    verify_station_media,
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "build_native_distribution.py"


def _load() -> object:
    assert SCRIPT_PATH.is_file(), f"native distribution builder is missing: {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("build_native_distribution", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def builder() -> object:
    return _load()


def _key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes(range(32)))


def _prepare_inputs(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, Path], Path]:
    app = tmp_path / "app"
    app.mkdir()
    (app / "python.exe").write_bytes(b"app runtime")
    (app / "app-payload-manifest.json").write_text("{}\n", encoding="utf-8")

    dependencies = tmp_path / "dependencies"
    dependencies.mkdir()
    (dependencies / "postgresql").mkdir()
    (dependencies / "postgresql" / "postgres.exe").write_bytes(b"postgres")
    (dependencies / "native-runtime-dependencies-manifest.json").write_text(
        "{}\n",
        encoding="utf-8",
    )

    caption_pack = tmp_path / "captions.ccpack"
    caption_pack.write_bytes(b"signed caption pack")

    models: dict[str, Path] = {}
    model_lock = {"schema_version": 1, "models": {}}
    for model_name, component in (
        ("gemma4-12b", "summary-gemma4-12b"),
        ("gemma4-e4b", "summary-gemma4-e4b"),
        ("translategemma-4b", "translation-translategemma-4b"),
    ):
        root = tmp_path / model_name
        (root / "blobs").mkdir(parents=True)
        (root / "blobs" / "sha256-fixture").write_bytes(model_name.encode())
        provenance = {
            "schema_version": 1,
            "model_name": model_name,
            "component": component,
            "manifest_sha256": hashlib.sha256(model_name.encode()).hexdigest(),
            "ollama_runtime_version": "0.30.6",
        }
        (root / "MODEL-PROVENANCE.json").write_text(
            json.dumps(provenance, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        models[model_name] = root
        model_lock["models"][model_name] = {"component": component}
    lock_path = tmp_path / "model-lock.json"
    lock_path.write_text(json.dumps(model_lock), encoding="utf-8")
    return app, dependencies, caption_pack, models, lock_path


def _install_fakes(builder: object, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        builder,
        "check_app_payload_verification",
        lambda *_args, **_kwargs: SimpleNamespace(status="PASS", detail="verified"),
    )
    monkeypatch.setattr(
        builder,
        "verify_staged_dependencies",
        lambda *_args, **_kwargs: {"status": "PASS"},
    )
    monkeypatch.setattr(builder, "verify_staged_model", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        builder,
        "load_model_lock",
        lambda path: json.loads(Path(path).read_text(encoding="utf-8")),
    )

    def fake_pack_builder(
        *,
        output: Path,
        component: str,
        product_version: str,
        compatible_core: str,
        sources: dict[str, Path],
        signing_private_key: Ed25519PrivateKey,
        signing_key_id: str,
        metadata: dict[str, object],
    ) -> SimpleNamespace:
        del signing_private_key
        digest = hashlib.sha256()
        for relative, source in sorted(sources.items()):
            digest.update(relative.encode())
            digest.update(b"\0")
            digest.update(source.read_bytes())
        output.write_bytes(component.encode() + b"\0" + digest.digest())
        return SimpleNamespace(
            path=output,
            sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
            component=component,
            product_version=product_version,
            compatible_core=compatible_core,
            signing_key_id=signing_key_id,
            file_count=len(sources),
            total_bytes=sum(path.stat().st_size for path in sources.values()),
            metadata=metadata,
        )

    def fake_pack_verifier(
        path: Path,
        *,
        public_key: object,
        expected_component: str,
        expected_product_version: str,
        expected_compatible_core: str,
        expected_signing_key_id: str,
    ) -> SimpleNamespace:
        del public_key
        return SimpleNamespace(
            path=path,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            component=expected_component,
            product_version=expected_product_version,
            compatible_core=expected_compatible_core,
            signing_key_id=expected_signing_key_id,
            file_count=1,
            total_bytes=path.stat().st_size,
            metadata={},
        )

    monkeypatch.setattr(builder, "build_native_pack", fake_pack_builder)
    monkeypatch.setattr(builder, "verify_native_pack", fake_pack_verifier)


def test_builder_emits_exact_required_pack_set_and_both_signed_indexes(
    builder: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fakes(builder, monkeypatch)
    app, dependencies, caption_pack, models, lock_path = _prepare_inputs(tmp_path)
    output = tmp_path / "distribution"
    key = _key()

    result = builder.build_native_distribution(
        output_dir=output,
        app_payload_root=app,
        runtime_dependencies_root=dependencies,
        caption_pack=caption_pack,
        model_roots=models,
        model_lock_path=lock_path,
        signing_private_key=key,
        signing_key_id="development-test-key",
        product_version="1.0.0-rc15",
        channel="beta",
        base_url="https://downloads.civiccast.example/native/beta/",
        created_epoch=1_700_000_000,
        allow_dirty_source=True,
    )

    assert tuple(result["packs"]) == REQUIRED_COMPONENTS
    assert set(output.glob("*.ccpack")) == {
        Path(result["packs"][component]["path"]) for component in REQUIRED_COMPONENTS
    }
    channel_index = verify_distribution_index(
        Path(result["channel_index"]),
        public_key=key.public_key(),
        expected_kind="channel-index",
        expected_channel="beta",
        expected_product_version="1.0.0-rc15",
        expected_signing_key_id="development-test-key",
    )
    station_index = verify_station_media(
        Path(result["station_index"]),
        public_key=key.public_key(),
        expected_channel="beta",
        expected_product_version="1.0.0-rc15",
        expected_signing_key_id="development-test-key",
    )
    assert [pack.component for pack in channel_index.packs] == list(REQUIRED_COMPONENTS)
    assert all(pack.required and len(pack.urls) == 1 for pack in channel_index.packs)
    assert all(pack.required and not pack.urls for pack in station_index.packs)
    assert result["total_pack_bytes"] == sum(
        Path(result["packs"][component]["path"]).stat().st_size for component in REQUIRED_COMPONENTS
    )


def test_builder_refuses_the_legacy_duplicate_caption_model_in_core(
    builder: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fakes(builder, monkeypatch)
    app, dependencies, caption_pack, models, lock_path = _prepare_inputs(tmp_path)
    duplicate = app / "MODELS" / "faster-whisper-large-v3" / "model.bin"
    duplicate.parent.mkdir(parents=True)
    duplicate.write_bytes(b"three gigabytes in production")

    with pytest.raises(builder.NativeDistributionBuildError, match=r"legacy|duplicate|Core"):
        builder.build_native_distribution(
            output_dir=tmp_path / "distribution",
            app_payload_root=app,
            runtime_dependencies_root=dependencies,
            caption_pack=caption_pack,
            model_roots=models,
            model_lock_path=lock_path,
            signing_private_key=_key(),
            signing_key_id="development-test-key",
            product_version="1.0.0-rc15",
            channel="beta",
            base_url="https://downloads.civiccast.example/native/beta/",
            created_epoch=1_700_000_000,
            allow_dirty_source=True,
        )


def test_builder_requires_all_three_exact_model_roots(
    builder: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fakes(builder, monkeypatch)
    app, dependencies, caption_pack, models, lock_path = _prepare_inputs(tmp_path)
    models.pop("gemma4-12b")

    with pytest.raises(builder.NativeDistributionBuildError, match=r"model.*set|gemma4-12b"):
        builder.build_native_distribution(
            output_dir=tmp_path / "distribution",
            app_payload_root=app,
            runtime_dependencies_root=dependencies,
            caption_pack=caption_pack,
            model_roots=models,
            model_lock_path=lock_path,
            signing_private_key=_key(),
            signing_key_id="development-test-key",
            product_version="1.0.0-rc15",
            channel="beta",
            base_url="https://downloads.civiccast.example/native/beta/",
            created_epoch=1_700_000_000,
            allow_dirty_source=True,
        )


def test_builder_refuses_nonempty_output_before_writing(
    builder: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fakes(builder, monkeypatch)
    app, dependencies, caption_pack, models, lock_path = _prepare_inputs(tmp_path)
    output = tmp_path / "distribution"
    output.mkdir()
    sentinel = output / "owner-file.txt"
    sentinel.write_text("keep", encoding="utf-8")

    with pytest.raises(builder.NativeDistributionBuildError, match="non-empty"):
        builder.build_native_distribution(
            output_dir=output,
            app_payload_root=app,
            runtime_dependencies_root=dependencies,
            caption_pack=caption_pack,
            model_roots=models,
            model_lock_path=lock_path,
            signing_private_key=_key(),
            signing_key_id="development-test-key",
            product_version="1.0.0-rc15",
            channel="beta",
            base_url="https://downloads.civiccast.example/native/beta/",
            created_epoch=1_700_000_000,
            allow_dirty_source=True,
        )
    assert sentinel.read_text(encoding="utf-8") == "keep"
