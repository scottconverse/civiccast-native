# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Native Ollama runtime pack contracts without downloading the 1.45 GB archive."""

from __future__ import annotations

import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from civiccast.installer.native_packs import verify_native_pack

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "build_native_ollama_pack.py"


def _load() -> object:
    assert SCRIPT_PATH.is_file(), f"native Ollama pack builder is missing: {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("build_native_ollama_pack", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


builder = _load()


def _dev_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes(range(32)))


def _fixture_runtime(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "ollama"
    runner = root / "lib" / "ollama" / "runners" / "cpu"
    runner.mkdir(parents=True)
    (root / "ollama.exe").write_bytes(b"fixture-ollama-exe")
    (runner / "ollama_llama_server.exe").write_bytes(b"fixture-runner")
    (runner / "runner.dll").write_bytes(b"fixture-dll")
    license_path = tmp_path / "LICENSE"
    license_path.write_text("MIT License\n", encoding="utf-8")
    return root, license_path


def _build(tmp_path: Path, root: Path, license_path: Path) -> dict[str, object]:
    return builder.build_ollama_pack(
        output=tmp_path / "out.ccpack",
        ollama_root=root,
        license_path=license_path,
        signing_private_key=_dev_key(),
        signing_key_id="development-test-key",
        product_version="0.0.0-test",
    )


def test_component_identity_is_stable() -> None:
    assert builder.OLLAMA_RUNTIME_COMPONENT == "native-ollama-runtime"


def test_end_to_end_pack_verifies_and_is_rooted_at_ollama_exe(tmp_path: Path) -> None:
    root, license_path = _fixture_runtime(tmp_path)
    report = _build(tmp_path, root, license_path)

    assert report["component"] == "native-ollama-runtime"
    verified = verify_native_pack(
        tmp_path / "out.ccpack",
        public_key=_dev_key().public_key(),
        expected_component="native-ollama-runtime",
        expected_product_version="0.0.0-test",
        expected_compatible_core="0.0.0-test",
        expected_signing_key_id="development-test-key",
    )
    assert verified.file_count == 5
    with zipfile.ZipFile(tmp_path / "out.ccpack") as archive:
        names = set(archive.namelist())
        notice = archive.read("payload/notices/ollama-runtime.txt").decode("utf-8")
    assert "payload/ollama.exe" in names
    assert "payload/lib/ollama/runners/cpu/ollama_llama_server.exe" in names
    assert "payload/licenses/ollama/LICENSE.txt" in names
    assert builder.OLLAMA_VERSION in notice


def test_pack_refuses_a_missing_runtime_executable(tmp_path: Path) -> None:
    root, license_path = _fixture_runtime(tmp_path)
    (root / "ollama.exe").unlink()

    with pytest.raises(builder.OllamaPackBuildError, match=r"ollama\.exe"):
        _build(tmp_path, root, license_path)


def test_pack_does_not_accept_model_store_bytes(tmp_path: Path) -> None:
    root, license_path = _fixture_runtime(tmp_path)
    model = root / "models" / "blobs" / "sha256-model"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"model")

    with pytest.raises(builder.OllamaPackBuildError, match="model store"):
        _build(tmp_path, root, license_path)


def test_acquire_refuses_lock_identity_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        builder,
        "load_lock",
        lambda _path: {
            "artifacts": {
                "ollama": {
                    "version": "99.0",
                    "spdx_license": "MIT",
                    "expected_executables": ["ollama.exe"],
                }
            }
        },
    )

    with pytest.raises(builder.OllamaPackBuildError, match="version drifted"):
        builder.acquire_ollama_pack_sources(tmp_path / "cache")


def test_acquire_replaces_a_stale_extracted_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "cache"
    stale = cache / "extracted" / "ollama"
    stale.mkdir(parents=True)
    (stale / "ollama.exe").write_bytes(b"stale-executable")
    (stale / "unexpected.dll").write_bytes(b"stale-extra")
    archive = tmp_path / "ollama.zip"
    archive.write_bytes(b"reviewed-archive")
    license_path = tmp_path / "LICENSE"
    license_path.write_text("MIT License\n", encoding="utf-8")
    monkeypatch.setattr(
        builder,
        "load_lock",
        lambda _path: {
            "artifacts": {
                "ollama": {
                    "version": builder.OLLAMA_VERSION,
                    "spdx_license": builder.OLLAMA_SPDX_LICENSE,
                    "expected_executables": list(builder.OLLAMA_EXECUTABLES),
                    "strip_prefix": ".",
                    "license_notice": {},
                }
            }
        },
    )
    monkeypatch.setattr(
        builder,
        "fetch_locked_artifact",
        lambda name, *_args, **_kwargs: archive if name == "ollama" else license_path,
    )

    def extract_fresh(_archive: Path, destination: Path, **_kwargs: object) -> None:
        assert not destination.exists()
        destination.mkdir(parents=True)
        (destination / "ollama.exe").write_bytes(b"fresh-executable")

    monkeypatch.setattr(builder, "safe_extract_zip", extract_fresh)

    root, acquired_license = builder.acquire_ollama_pack_sources(cache)

    assert acquired_license == license_path
    assert (root / "ollama.exe").read_bytes() == b"fresh-executable"
    assert not (root / "unexpected.dll").exists()


def test_acquire_restores_the_previous_cache_when_promotion_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "cache"
    destination = cache / "extracted" / "ollama"
    destination.mkdir(parents=True)
    (destination / "ollama.exe").write_bytes(b"previous-executable")
    archive = tmp_path / "ollama.zip"
    archive.write_bytes(b"reviewed-archive")
    license_path = tmp_path / "LICENSE"
    license_path.write_text("MIT License\n", encoding="utf-8")
    monkeypatch.setattr(
        builder,
        "load_lock",
        lambda _path: {
            "artifacts": {
                "ollama": {
                    "version": builder.OLLAMA_VERSION,
                    "spdx_license": builder.OLLAMA_SPDX_LICENSE,
                    "expected_executables": list(builder.OLLAMA_EXECUTABLES),
                    "strip_prefix": ".",
                    "license_notice": {},
                }
            }
        },
    )
    monkeypatch.setattr(
        builder,
        "fetch_locked_artifact",
        lambda name, *_args, **_kwargs: archive if name == "ollama" else license_path,
    )

    def extract_fresh(_archive: Path, root: Path, **_kwargs: object) -> None:
        root.mkdir(parents=True)
        (root / "ollama.exe").write_bytes(b"fresh-executable")

    monkeypatch.setattr(builder, "safe_extract_zip", extract_fresh)
    original_replace = Path.replace

    def fail_fresh_promotion(path: Path, target: Path) -> Path:
        if path.name == "runtime" and Path(target) == destination:
            raise OSError("simulated promotion failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_fresh_promotion)

    with pytest.raises(builder.OllamaPackBuildError, match="simulated promotion failure"):
        builder.acquire_ollama_pack_sources(cache)

    assert (destination / "ollama.exe").read_bytes() == b"previous-executable"


def test_acquire_preserves_the_backup_when_promotion_and_rollback_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "cache"
    destination = cache / "extracted" / "ollama"
    destination.mkdir(parents=True)
    (destination / "ollama.exe").write_bytes(b"previous-executable")
    archive = tmp_path / "ollama.zip"
    archive.write_bytes(b"reviewed-archive")
    license_path = tmp_path / "LICENSE"
    license_path.write_text("MIT License\n", encoding="utf-8")
    monkeypatch.setattr(
        builder,
        "load_lock",
        lambda _path: {
            "artifacts": {
                "ollama": {
                    "version": builder.OLLAMA_VERSION,
                    "spdx_license": builder.OLLAMA_SPDX_LICENSE,
                    "expected_executables": list(builder.OLLAMA_EXECUTABLES),
                    "strip_prefix": ".",
                    "license_notice": {},
                }
            }
        },
    )
    monkeypatch.setattr(
        builder,
        "fetch_locked_artifact",
        lambda name, *_args, **_kwargs: archive if name == "ollama" else license_path,
    )

    def extract_fresh(_archive: Path, root: Path, **_kwargs: object) -> None:
        root.mkdir(parents=True)
        (root / "ollama.exe").write_bytes(b"fresh-executable")

    monkeypatch.setattr(builder, "safe_extract_zip", extract_fresh)
    original_replace = Path.replace

    def fail_promotion_and_rollback(path: Path, target: Path) -> Path:
        if Path(target) == destination and path.name in {"runtime", "previous"}:
            raise OSError(f"simulated {path.name} failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_promotion_and_rollback)

    with pytest.raises(builder.OllamaPackBuildError, match="previous cache is preserved"):
        builder.acquire_ollama_pack_sources(cache)

    backups = tuple((cache / "extracted").glob(".ollama-previous-*/previous/ollama.exe"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"previous-executable"
