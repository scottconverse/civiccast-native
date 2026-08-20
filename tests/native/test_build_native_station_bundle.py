# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""K1 follow-up: ``scripts/build_native_station_bundle.py`` (the station-
bundle publisher) tests.

Proves the pieces that ARE honestly fixture-testable, and is explicit about
the one that is not: ``core`` and ``captions-floor`` have no reviewed-model-
lock coupling and fully round-trip through the real, unmodified
``verify_native_pack`` with tiny fixture bytes. ``summary-gemma4-12b`` /
``summary-gemma4-e4b`` / ``translation-translategemma-4b`` are checked by
``civiccast.installer.native_packs._validate_ollama_model_contract`` against
the EMBEDDED reviewed Ollama model lock (real, pinned SHA-256 digests of
real multi-GB blobs) -- no fixture can satisfy that, by design (the exact
supply-chain gate it exists to be), and ``build_native_pack`` itself
self-verifies every pack it builds, so this script cannot even locally
build a fake pack claiming one of those three identities. This file proves
that gate correctly REJECTS fixture attempts rather than trying to work
around it -- see
``tests/native/test_build_native_station_bundle.py::
test_ollama_model_components_reject_fixture_bytes_without_a_matching_reviewed_lock_entry``.

The Rust-side proof that a bundle of this exact shape is accepted by
``native_distribution::acquire_station_distribution`` lives in
``native_distribution.rs``'s own test module
(``publisher_shaped_station_index_passes_schema_and_signature_verification``,
``acquire_station_distribution_accepts_the_unlocked_components_and_fails_closed_at_the_reviewed_model_lock_gate``)
-- invoking this Python script from a ``cargo test`` run has no precedent
anywhere in this test suite (checked), so the schema is proven in Rust
directly against a Rust-built fixture of the identical shape instead of by
shelling out to Python.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import civiccast.installer.native_packs as native_packs
from civiccast.installer.native_distribution import canonical_json
from civiccast.installer.native_packs import NativePackVerificationError, verify_native_pack

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "build_native_station_bundle.py"
NSIS_HOOKS = ROOT / "civiccast" / "apps" / "installer" / "src-tauri" / "nsis-hooks-bootstrap.nsh"


def _load() -> object:
    assert SCRIPT_PATH.is_file(), f"native station bundle publisher is missing: {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("build_native_station_bundle", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


builder = _load()


def _dev_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes(range(32)))


def _write_tree(root: Path, files: dict[str, bytes]) -> Path:
    for relative, data in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root


# ---------------------------------------------------------------------------
# The station-index filename this publisher emits must match the literal
# nsis-hooks-bootstrap.nsh's K1 wiring invokes --civiccast-import-station
# with -- otherwise a real bundle this script builds would sit right next to
# the installer and still never be found.
# ---------------------------------------------------------------------------


def test_station_index_filename_matches_the_nsis_wiring() -> None:
    hooks_text = NSIS_HOOKS.read_text(encoding="utf-8")
    assert f"station\\{builder.STATION_INDEX_FILENAME}" in hooks_text, (
        f"nsis-hooks-bootstrap.nsh must invoke --civiccast-import-station against "
        f"$EXEDIR\\station\\{builder.STATION_INDEX_FILENAME} -- the exact filename "
        "this publisher writes"
    )


# ---------------------------------------------------------------------------
# Required-root validation: fail loud, name exactly what is missing, before
# writing anything.
# ---------------------------------------------------------------------------


def test_require_pack_root_fails_loud_when_missing() -> None:
    with pytest.raises(builder.StationBundleBuildError, match="missing required pack artifact root"):
        builder._require_pack_root(None, component="captions-floor", required=True)


def test_require_pack_root_fails_loud_when_empty(tmp_path: Path) -> None:
    empty = tmp_path / "empty-root"
    empty.mkdir()
    with pytest.raises(builder.StationBundleBuildError, match="is empty"):
        builder._require_pack_root(empty, component="captions-floor", required=True)


def test_require_pack_root_allows_an_absent_optional_root() -> None:
    assert builder._require_pack_root(None, component="captions-large-v3", required=False) is None


def test_build_station_bundle_fails_loud_and_writes_nothing_when_a_required_root_is_missing(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "station"
    with pytest.raises(builder.StationBundleBuildError, match="captions-floor"):
        builder.build_station_bundle(
            output_dir=output_dir,
            captions_floor_root=tmp_path / "does-not-exist",
            gemma4_12b_root=_write_tree(tmp_path / "gemma-12b", {"blobs/sha256-x": b"x"}),
            gemma4_e4b_root=_write_tree(tmp_path / "gemma-e4b", {"blobs/sha256-y": b"y"}),
            translategemma_4b_root=_write_tree(tmp_path / "translate", {"blobs/sha256-z": b"z"}),
            captions_large_v3_root=None,
            signing_private_key=_dev_key(),
            signing_key_id="development-test-key",
            product_version="1.0.0-rc15",
            compatible_core=None,
            channel="beta",
            created_epoch=1_700_000_000,
        )
    assert not output_dir.exists(), "a failed build must never leave a partial bundle on disk"


def test_build_station_bundle_refuses_a_non_empty_output_directory(tmp_path: Path) -> None:
    output_dir = tmp_path / "station"
    output_dir.mkdir()
    (output_dir / "leftover.txt").write_text("stale", encoding="utf-8")

    with pytest.raises(builder.StationBundleBuildError, match="non-empty"):
        builder.build_station_bundle(
            output_dir=output_dir,
            captions_floor_root=_write_tree(
                tmp_path / "captions-floor", {"models/faster-whisper-medium/model.bin": b"m"}
            ),
            gemma4_12b_root=_write_tree(tmp_path / "gemma-12b", {"blobs/sha256-x": b"x"}),
            gemma4_e4b_root=_write_tree(tmp_path / "gemma-e4b", {"blobs/sha256-y": b"y"}),
            translategemma_4b_root=_write_tree(tmp_path / "translate", {"blobs/sha256-z": b"z"}),
            captions_large_v3_root=None,
            signing_private_key=_dev_key(),
            signing_key_id="development-test-key",
            product_version="1.0.0-rc15",
            compatible_core=None,
            channel="beta",
            created_epoch=1_700_000_000,
        )


def test_require_allowed_signing_key_blocks_a_bare_development_key() -> None:
    with pytest.raises(builder.StationBundleBuildError, match="allow-development-key"):
        builder.require_allowed_signing_key("development-test-key", allow_development_key=False)
    # Must not raise with the explicit override.
    builder.require_allowed_signing_key("development-test-key", allow_development_key=True)


# ---------------------------------------------------------------------------
# core + captions-floor: NO reviewed-model-lock coupling -- these fully
# round-trip through the real, unmodified verify_native_pack.
# ---------------------------------------------------------------------------


def test_core_placeholder_pack_round_trips_through_verify_native_pack(tmp_path: Path) -> None:
    key = _dev_key()
    sources = builder._core_placeholder_sources(tmp_path, product_version="1.0.0-rc15")
    output = tmp_path / "core.ccpack"
    builder.build_native_pack(
        output=output,
        component="core",
        product_version="1.0.0-rc15",
        compatible_core="1.0.0-rc15",
        sources=sources,
        signing_private_key=key,
        signing_key_id="development-test-key",
        metadata={"payload": "placeholder-only; see NOTICE.txt"},
    )
    result = verify_native_pack(
        output,
        public_key=key.public_key(),
        expected_component="core",
        expected_product_version="1.0.0-rc15",
        expected_compatible_core="1.0.0-rc15",
        expected_signing_key_id="development-test-key",
    )
    assert result.component == "core"
    assert result.file_count == 1


def test_captions_floor_pack_round_trips_through_verify_native_pack(tmp_path: Path) -> None:
    key = _dev_key()
    floor_root = _write_tree(
        tmp_path / "captions-floor",
        {
            "models/faster-whisper-medium/config.json": b"floor-config",
            "models/faster-whisper-medium/model.bin": b"floor-model-bytes",
            "models/faster-whisper-medium/tokenizer.json": b"floor-tokenizer",
            "models/faster-whisper-medium/vocabulary.txt": b"floor-vocab",
            "self-test/jfk.wav": b"floor-self-test-audio",
        },
    )
    sources = builder._collect_tree_sources(floor_root)
    output = tmp_path / "captions-floor.ccpack"
    builder.build_native_pack(
        output=output,
        component="captions-floor",
        product_version="1.0.0-rc15",
        compatible_core="1.0.0-rc15",
        sources=sources,
        signing_private_key=key,
        signing_key_id="development-test-key",
        metadata={"source_root": str(floor_root)},
    )
    result = verify_native_pack(
        output,
        public_key=key.public_key(),
        expected_component="captions-floor",
        expected_product_version="1.0.0-rc15",
        expected_compatible_core="1.0.0-rc15",
        expected_signing_key_id="development-test-key",
    )
    assert result.component == "captions-floor"
    assert result.file_count == 5


# ---------------------------------------------------------------------------
# The reviewed-model-lock gate: proven to actually fire for fixture bytes,
# never silently bypassed.
# ---------------------------------------------------------------------------


def test_ollama_model_components_reject_fixture_bytes_without_a_matching_reviewed_lock_entry(
    tmp_path: Path,
) -> None:
    """`build_native_pack` self-verifies every pack it builds
    (`native_packs.build_native_pack` calls `verify_native_pack` internally
    before returning) -- so this publisher cannot even locally construct a
    fake `summary-gemma4-12b` pack, let alone ship one. This is the gate
    working as designed, not a builder bug: a station bundle for these three
    components requires REAL, reviewed-lock-matching Ollama model exports as
    input, which is real production data this test suite correctly never
    fabricates."""

    key = _dev_key()
    root = _write_tree(
        tmp_path / "gemma-12b",
        {
            "blobs/sha256-" + "0" * 64: b"pretend-config",
            "manifests/registry.ollama.ai/library/gemma4/12b": b"pretend-manifest",
        },
    )
    sources = builder._collect_tree_sources(root)
    output = tmp_path / "summary-gemma4-12b.ccpack"

    with pytest.raises(NativePackVerificationError, match=r"model_name|reviewed model lock"):
        builder.build_native_pack(
            output=output,
            component="summary-gemma4-12b",
            product_version="1.0.0-rc15",
            compatible_core="1.0.0-rc15",
            sources=sources,
            signing_private_key=key,
            signing_key_id="development-test-key",
            metadata={},
        )
    assert not output.exists(), "a pack that fails its own self-verification must not be left on disk"


# ---------------------------------------------------------------------------
# Ollama-model metadata: the reviewed-lock gate PASSING for a correctly-
# provenanced, lock-matching pack -- not just failing closed on a bare/
# mismatched one. Regression coverage for the K1 CI round-trip (run
# 31979342933): provisioning succeeded end to end, but the first real Ollama
# pack failed self-verification with "missing model_name metadata" --
# ``build_native_pack``'s own self-verify call means the fixture-rejection
# test above proves the gate fails closed, but it cannot prove the gate also
# PASSES a genuinely correct pack, since real production model bytes can't
# be fixtured. A monkeypatched reviewed lock (the same technique
# ``tests/native/test_caption_pack_builder.py`` uses for
# ``CAPTION_SELF_TEST_BYTES``/``SHA256``) closes that gap: tiny fixture
# bytes, a real lock file shape, a real signed pack, a real
# ``verify_native_pack`` pass.
# ---------------------------------------------------------------------------


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_test_ollama_lock(tmp_path: Path) -> dict[str, dict[str, object]]:
    """A structurally-valid reviewed Ollama model lock -- satisfies
    ``native_packs._load_reviewed_ollama_model_lock``'s own schema checks --
    with tiny fixture bytes for ALL THREE required components (that loader
    requires the full component set present, even when a given test only
    exercises one of them). Returns the in-memory model dicts (including a
    private ``_fixture_bytes`` scratch key stripped before the lock is
    written to disk) so callers can build a matching on-disk model root
    without re-deriving hashes."""

    fixtures = {
        "gemma4-12b": ("summary-gemma4-12b", "gemma4", "12b"),
        "gemma4-e4b": ("summary-gemma4-e4b", "gemma4", "e4b"),
        "translategemma-4b": ("translation-translategemma-4b", "translategemma", "4b"),
    }
    models: dict[str, dict[str, object]] = {}
    for name, (component, repository, tag) in fixtures.items():
        config_bytes = f"config-for-{name}".encode()
        layer_bytes = f"model-layer-for-{name}".encode()
        manifest_bytes = f"manifest-for-{name}".encode()
        models[name] = {
            "component": component,
            "repository": repository,
            "tag": tag,
            "manifest_bytes": len(manifest_bytes),
            "manifest_sha256": _sha256_hex(manifest_bytes),
            "config": {"bytes": len(config_bytes), "sha256": _sha256_hex(config_bytes)},
            "layers": [
                {
                    "bytes": len(layer_bytes),
                    "sha256": _sha256_hex(layer_bytes),
                    "media_type": "application/vnd.ollama.image.model",
                }
            ],
            "_fixture_bytes": {
                "config": config_bytes,
                "layer": layer_bytes,
                "manifest": manifest_bytes,
            },
        }

    lock_path = tmp_path / "test-native-windows-ollama-models.lock.json"
    on_disk = {
        "schema_version": 1,
        "registry": "registry.ollama.ai",
        "ollama_runtime_version": "0.30.6",
        "models": {
            name: {key: value for key, value in model.items() if key != "_fixture_bytes"}
            for name, model in models.items()
        },
    }
    lock_path.write_text(json.dumps(on_disk), encoding="utf-8")
    models["_lock_path"] = lock_path  # type: ignore[assignment]
    return models


def _write_ollama_model_root(tmp_path: Path, *, model_name: str, model: dict[str, object]) -> Path:
    """The exact directory shape
    ``scripts/provision_native_ollama_models.py::stage_model`` produces:
    ``blobs/sha256-<digest>`` + ``manifests/<registry>/library/<repo>/<tag>``
    + ``MODEL-PROVENANCE.json`` -- the file
    ``_ollama_model_pack_metadata`` reads."""

    fixture_bytes: dict[str, bytes] = model["_fixture_bytes"]  # type: ignore[assignment]
    config: dict[str, object] = model["config"]  # type: ignore[assignment]
    layers: list[dict[str, object]] = model["layers"]  # type: ignore[assignment]
    layer = layers[0]

    root = tmp_path / f"ollama-root-{model_name}"
    (root / "blobs").mkdir(parents=True)
    (root / "blobs" / f"sha256-{config['sha256']}").write_bytes(fixture_bytes["config"])
    (root / "blobs" / f"sha256-{layer['sha256']}").write_bytes(fixture_bytes["layer"])
    manifest_path = (
        root / "manifests" / "registry.ollama.ai" / "library" / str(model["repository"]) / str(model["tag"])
    )
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_bytes(fixture_bytes["manifest"])

    provenance = {
        "schema_version": 1,
        "component": model["component"],
        "model_name": model_name,
        "repository": model["repository"],
        "tag": model["tag"],
        "manifest_bytes": model["manifest_bytes"],
        "manifest_sha256": model["manifest_sha256"],
        "ollama_runtime_version": "0.30.6",
        "lock_sha256": "0" * 64,
        "blobs": [
            {"bytes": config["bytes"], "sha256": config["sha256"]},
            {"bytes": layer["bytes"], "sha256": layer["sha256"]},
        ],
    }
    (root / "MODEL-PROVENANCE.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return root


def test_ollama_model_pack_metadata_extracts_the_fields_the_contract_requires(
    tmp_path: Path,
) -> None:
    models = _write_test_ollama_lock(tmp_path)
    model = models["gemma4-12b"]
    root = _write_ollama_model_root(tmp_path, model_name="gemma4-12b", model=model)

    metadata = builder._ollama_model_pack_metadata("summary-gemma4-12b", root)

    assert metadata["model_name"] == "gemma4-12b"
    assert metadata["manifest_sha256"] == model["manifest_sha256"]
    assert metadata["ollama_runtime_version"] == "0.30.6"
    assert metadata["source_root"] == str(root)


def test_ollama_model_pack_metadata_fails_loud_when_provenance_is_missing(tmp_path: Path) -> None:
    root = tmp_path / "no-provenance-root"
    (root / "blobs").mkdir(parents=True)

    with pytest.raises(builder.StationBundleBuildError, match=r"MODEL-PROVENANCE\.json"):
        builder._ollama_model_pack_metadata("summary-gemma4-12b", root)


def test_ollama_model_pack_metadata_fails_loud_on_component_mismatch(tmp_path: Path) -> None:
    models = _write_test_ollama_lock(tmp_path)
    model = models["gemma4-12b"]
    root = _write_ollama_model_root(tmp_path, model_name="gemma4-12b", model=model)

    with pytest.raises(builder.StationBundleBuildError, match="does not match the pack being built"):
        builder._ollama_model_pack_metadata("summary-gemma4-e4b", root)


def test_ollama_model_component_pack_passes_verification_against_a_matching_reviewed_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The positive path the fail-closed test above cannot prove: a
    publisher-built pack whose metadata AND bytes genuinely match a
    reviewed lock entry passes ``verify_native_pack`` cleanly -- the exact
    path that broke on the real CI round-trip (run 31979342933)."""

    models = _write_test_ollama_lock(tmp_path)
    monkeypatch.setattr(native_packs, "OLLAMA_MODEL_LOCK_PATH", models["_lock_path"])

    model = models["gemma4-12b"]
    root = _write_ollama_model_root(tmp_path, model_name="gemma4-12b", model=model)

    sources = builder._collect_tree_sources(root)
    metadata = builder._ollama_model_pack_metadata("summary-gemma4-12b", root)
    key = _dev_key()
    output = tmp_path / "summary-gemma4-12b.ccpack"

    builder.build_native_pack(
        output=output,
        component="summary-gemma4-12b",
        product_version="1.0.0-rc15",
        compatible_core="1.0.0-rc15",
        sources=sources,
        signing_private_key=key,
        signing_key_id="development-test-key",
        metadata=metadata,
    )

    result = verify_native_pack(
        output,
        public_key=key.public_key(),
        expected_component="summary-gemma4-12b",
        expected_product_version="1.0.0-rc15",
        expected_compatible_core="1.0.0-rc15",
        expected_signing_key_id="development-test-key",
    )
    assert result.component == "summary-gemma4-12b"
    assert result.metadata["model_name"] == "gemma4-12b"
    assert result.metadata["ollama_runtime_version"] == "0.30.6"


def test_build_station_bundle_succeeds_with_matching_provenance_for_every_ollama_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The full ``build_station_bundle`` entry point -- not just one
    component pack -- succeeds when all three Ollama roots carry
    provenance matching a (monkeypatched) reviewed lock. This is the exact
    call the native-beta-candidate-artifacts.yml CI job makes; run
    31979342933 failed here."""

    models = _write_test_ollama_lock(tmp_path)
    monkeypatch.setattr(native_packs, "OLLAMA_MODEL_LOCK_PATH", models["_lock_path"])

    gemma_12b_root = _write_ollama_model_root(
        tmp_path, model_name="gemma4-12b", model=models["gemma4-12b"]
    )
    gemma_e4b_root = _write_ollama_model_root(
        tmp_path, model_name="gemma4-e4b", model=models["gemma4-e4b"]
    )
    translate_root = _write_ollama_model_root(
        tmp_path, model_name="translategemma-4b", model=models["translategemma-4b"]
    )
    floor_root = _write_tree(
        tmp_path / "captions-floor",
        {
            "models/faster-whisper-medium/config.json": b"floor-config",
            "models/faster-whisper-medium/model.bin": b"floor-model-bytes",
            "models/faster-whisper-medium/tokenizer.json": b"floor-tokenizer",
            "models/faster-whisper-medium/vocabulary.txt": b"floor-vocab",
            "self-test/jfk.wav": b"floor-self-test-audio",
        },
    )

    output_dir = tmp_path / "station"
    result = builder.build_station_bundle(
        output_dir=output_dir,
        captions_floor_root=floor_root,
        gemma4_12b_root=gemma_12b_root,
        gemma4_e4b_root=gemma_e4b_root,
        translategemma_4b_root=translate_root,
        captions_large_v3_root=None,
        signing_private_key=_dev_key(),
        signing_key_id="development-test-key",
        product_version="1.0.0-rc15",
        compatible_core=None,
        channel="beta",
        created_epoch=1_700_000_000,
    )

    assert set(result["packs"]) == {
        "core",
        "captions-floor",
        "summary-gemma4-12b",
        "summary-gemma4-e4b",
        "translation-translategemma-4b",
    }
    assert (output_dir / builder.STATION_INDEX_FILENAME).is_file()
    for component in (
        "core",
        "captions-floor",
        "summary-gemma4-12b",
        "summary-gemma4-e4b",
        "translation-translategemma-4b",
    ):
        assert (output_dir / f"{component}.ccpack").is_file()


# ---------------------------------------------------------------------------
# station-index.json schema: proven directly, without needing real Ollama
# model bytes (this function never opens or verifies a single .ccpack -- see
# its own doc).
# ---------------------------------------------------------------------------


def test_build_station_index_schema_matches_the_rust_contract(tmp_path: Path) -> None:
    key = _dev_key()
    packs: dict[str, Path] = {}
    # Deliberately built in a SCRAMBLED order -- _build_station_index must
    # sort into canonical order itself, not merely preserve caller order.
    for component in [
        "translation-translategemma-4b",
        "core",
        "summary-gemma4-e4b",
        "captions-floor",
        "summary-gemma4-12b",
    ]:
        path = tmp_path / f"{component}.ccpack"
        path.write_bytes(f"pretend-{component}-pack-bytes".encode())
        packs[component] = path

    index_path = tmp_path / builder.STATION_INDEX_FILENAME
    manifest = builder._build_station_index(
        output=index_path,
        channel="beta",
        product_version="1.0.0-rc15",
        compatible_core="1.0.0-rc15",
        signing_key_id="development-test-key",
        created_epoch=1_700_000_000,
        packs=packs,
        signing_private_key=key,
    )

    assert manifest["schema_version"] == 1
    assert manifest["product"] == "civiccast-native"
    assert manifest["kind"] == "station-index"
    entries = manifest["packs"]
    assert [entry["component"] for entry in entries] == [
        "core",
        "captions-floor",
        "summary-gemma4-12b",
        "summary-gemma4-e4b",
        "translation-translategemma-4b",
    ]
    assert all(entry["required"] is True for entry in entries)
    assert all(entry["urls"] == [] for entry in entries)

    # The file on disk is exactly canonical_json(envelope) -- the same byte
    # contract native_distribution.rs::verify_distribution_bytes enforces
    # (`canonical_json(&envelope_value)?.as_bytes() != raw` fails closed on
    # anything else).
    raw = index_path.read_bytes()
    envelope = json.loads(raw)
    assert canonical_json(envelope) == raw
    assert set(envelope) == {"manifest", "signature"}


def test_build_station_index_with_captions_large_v3_present_sorts_it_after_the_required_set(
    tmp_path: Path,
) -> None:
    key = _dev_key()
    packs: dict[str, Path] = {}
    for component in [
        "core",
        "captions-floor",
        "summary-gemma4-12b",
        "summary-gemma4-e4b",
        "translation-translategemma-4b",
        "captions-large-v3",
    ]:
        path = tmp_path / f"{component}.ccpack"
        path.write_bytes(f"pretend-{component}-pack-bytes".encode())
        packs[component] = path

    index_path = tmp_path / builder.STATION_INDEX_FILENAME
    manifest = builder._build_station_index(
        output=index_path,
        channel="beta",
        product_version="1.0.0-rc15",
        compatible_core="1.0.0-rc15",
        signing_key_id="development-test-key",
        created_epoch=1_700_000_000,
        packs=packs,
        signing_private_key=key,
    )

    entries = manifest["packs"]
    assert entries[-1]["component"] == "captions-large-v3"
    assert entries[-1]["required"] is False
