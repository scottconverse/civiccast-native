# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Pinned, offline-reproducible Ollama model-pack acquisition."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
import urllib.parse
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = ROOT / "native-windows-ollama-models.lock.json"
SCRIPT_PATH = ROOT / "scripts" / "provision_native_ollama_models.py"

EXPECTED = {
    "gemma4-12b": (
        "summary-gemma4-12b",
        "4eb23ef187e2c5462566d6a1d3bbbc2f1346d0b4327cbb66d58fffbcc9b2b05c",
        "1278394b693672ac2799eadc9a83fd98259a6a88a40acfb1dcaa6c6fc895a606",
    ),
    "gemma4-e4b": (
        "summary-gemma4-e4b",
        "c6eb396dbd5992bbe3f5cdb947e8bbc0ee413d7c17e2beaae69f5d569cf982eb",
        "4c27e0f5b5adf02ac956c7322bd2ee7636fe3f45a8512c9aba5385242cb6e09a",
    ),
    "translategemma-4b": (
        "translation-translategemma-4b",
        "c49d986b0764f5881c476eb21435bb62b7abc62347aab3d4a6071e811be510a1",
        "bdbf939b402e2f88fbe3e918beb777813009335756b4c17be7fe008dfe4815d4",
    ),
}


def _load() -> object:
    spec = importlib.util.spec_from_file_location("provision_native_ollama_models", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def provisioner() -> object:
    return _load()


def _fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, bytes]]:
    blobs = {
        "config": b'{"architecture":"fixture"}',
        "model": b"fixture-model-bytes",
        "license": b"fixture model license",
    }
    manifest = json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
            "config": {
                "mediaType": "application/vnd.docker.container.image.v1+json",
                "digest": "sha256:" + hashlib.sha256(blobs["config"]).hexdigest(),
                "size": len(blobs["config"]),
            },
            "layers": [
                {
                    "mediaType": "application/vnd.ollama.image.model",
                    "digest": "sha256:" + hashlib.sha256(blobs["model"]).hexdigest(),
                    "size": len(blobs["model"]),
                },
                {
                    "mediaType": "application/vnd.ollama.image.license",
                    "digest": "sha256:" + hashlib.sha256(blobs["license"]).hexdigest(),
                    "size": len(blobs["license"]),
                },
            ],
        },
        separators=(",", ":"),
    ).encode()
    lock = {
        "schema_version": 1,
        "registry": "registry.ollama.ai",
        "ollama_runtime_version": "0.30.6",
        "models": {
            "fixture": {
                "component": "summary-fixture",
                "repository": "fixture",
                "tag": "one",
                "manifest_bytes": len(manifest),
                "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
                "config": {
                    "bytes": len(blobs["config"]),
                    "sha256": hashlib.sha256(blobs["config"]).hexdigest(),
                },
                "layers": [
                    {
                        "bytes": len(blobs["model"]),
                        "sha256": hashlib.sha256(blobs["model"]).hexdigest(),
                        "media_type": "application/vnd.ollama.image.model",
                    },
                    {
                        "bytes": len(blobs["license"]),
                        "sha256": hashlib.sha256(blobs["license"]).hexdigest(),
                        "media_type": "application/vnd.ollama.image.license",
                    },
                ],
            }
        },
    }
    lock_path = tmp_path / "models.lock.json"
    lock_path.write_text(json.dumps(lock, sort_keys=True), encoding="utf-8")
    cache = tmp_path / "cache"
    (cache / "manifests").mkdir(parents=True)
    (cache / "blobs").mkdir()
    (cache / "manifests" / f"{lock['models']['fixture']['manifest_sha256']}.json").write_bytes(
        manifest
    )
    for body in blobs.values():
        (cache / "blobs" / f"sha256-{hashlib.sha256(body).hexdigest()}").write_bytes(body)
    return lock_path, cache, {"manifest": manifest, **blobs}


def test_committed_lock_pins_all_required_models_and_licenses(provisioner: object) -> None:
    lock = provisioner.load_lock()

    assert lock["ollama_runtime_version"] == "0.30.6"
    assert set(lock["models"]) == set(EXPECTED)
    for name, (component, manifest_sha, model_sha) in EXPECTED.items():
        model = lock["models"][name]
        assert model["component"] == component
        assert model["manifest_sha256"] == manifest_sha
        assert model["manifest_bytes"] > 0
        assert model["config"]["bytes"] > 0
        assert any(
            layer["media_type"] == "application/vnd.ollama.image.model"
            and layer["sha256"] == model_sha
            and layer["bytes"] > 1_000_000_000
            for layer in model["layers"]
        )
        assert any(
            layer["media_type"] == "application/vnd.ollama.image.license" and layer["bytes"] > 0
            for layer in model["layers"]
        )
    provisioner.validate_lock(lock)


def test_offline_stage_reconstructs_exact_ollama_store(provisioner: object, tmp_path: Path) -> None:
    lock_path, cache, fixture = _fixture(tmp_path)
    output = tmp_path / "model"

    result = provisioner.stage_model(
        "fixture",
        lock_path=lock_path,
        cache=cache,
        output=output,
        offline=True,
    )

    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    model = lock["models"]["fixture"]
    assert result == output / "MODEL-PROVENANCE.json"
    assert (
        output / "manifests" / "registry.ollama.ai" / "library" / "fixture" / "one"
    ).read_bytes() == fixture["manifest"]
    for identity in [model["config"], *model["layers"]]:
        assert (output / "blobs" / f"sha256-{identity['sha256']}").stat().st_size == identity[
            "bytes"
        ]
    provenance = json.loads(result.read_text(encoding="utf-8"))
    assert provenance["component"] == "summary-fixture"
    assert provenance["manifest_sha256"] == model["manifest_sha256"]
    provisioner.verify_staged_model("fixture", output, lock_path=lock_path)


def test_manifest_semantics_must_match_the_signed_lock(provisioner: object, tmp_path: Path) -> None:
    lock_path, cache, _fixture_files = _fixture(tmp_path)
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    manifest_path = cache / "manifests" / (lock["models"]["fixture"]["manifest_sha256"] + ".json")
    parsed = json.loads(manifest_path.read_bytes())
    parsed["layers"][0]["mediaType"] = "application/vnd.ollama.image.template"
    malicious = json.dumps(parsed, separators=(",", ":")).encode()
    lock["models"]["fixture"]["manifest_bytes"] = len(malicious)
    lock["models"]["fixture"]["manifest_sha256"] = hashlib.sha256(malicious).hexdigest()
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    manifest_path.unlink()
    (cache / "manifests" / f"{lock['models']['fixture']['manifest_sha256']}.json").write_bytes(
        malicious
    )

    with pytest.raises(provisioner.ModelProvisionError, match=r"media type|manifest"):
        provisioner.stage_model(
            "fixture",
            lock_path=lock_path,
            cache=cache,
            output=tmp_path / "bad",
            offline=True,
        )


def test_corrupt_cached_blob_is_rejected_offline(provisioner: object, tmp_path: Path) -> None:
    lock_path, cache, fixture = _fixture(tmp_path)
    model_sha = hashlib.sha256(fixture["model"]).hexdigest()
    (cache / "blobs" / f"sha256-{model_sha}").write_bytes(b"corrupt")

    with pytest.raises(provisioner.ModelProvisionError, match=r"size|SHA-256"):
        provisioner.stage_model(
            "fixture",
            lock_path=lock_path,
            cache=cache,
            output=tmp_path / "bad",
            offline=True,
        )


def test_offline_mode_never_opens_network(provisioner: object, tmp_path: Path) -> None:
    lock_path, cache, _fixture_files = _fixture(tmp_path)

    provisioner.stage_model(
        "fixture",
        lock_path=lock_path,
        cache=cache,
        output=tmp_path / "model",
        offline=True,
        opener=lambda *_args, **_kwargs: pytest.fail("offline mode touched networking"),
    )


class _Response(io.BytesIO):
    def __init__(self, body: bytes, final_url: str) -> None:
        super().__init__(body)
        self._final_url = final_url
        self.status = 200
        self.headers = {"Content-Length": str(len(body))}

    def geturl(self) -> str:
        return self._final_url

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def test_manifest_fetch_verifies_raw_registry_bytes_before_cache(
    provisioner: object,
    tmp_path: Path,
) -> None:
    lock_path, existing_cache, fixture = _fixture(tmp_path)
    lock = provisioner.load_lock(lock_path)
    cache = tmp_path / "empty-cache"
    calls: list[str] = []

    def opener(request: object, *, timeout: float) -> _Response:
        calls.append(request.full_url)  # type: ignore[attr-defined]
        assert timeout == 60
        return _Response(
            fixture["manifest"],
            "https://registry.ollama.ai/v2/library/fixture/manifests/one",
        )

    path = provisioner.fetch_manifest(
        "fixture",
        lock["models"]["fixture"],
        cache,
        opener=opener,
    )

    assert path.read_bytes() == fixture["manifest"]
    assert calls == ["https://registry.ollama.ai/v2/library/fixture/manifests/one"]
    assert existing_cache.is_dir()


def _official_r2_url(digest: str, **query_overrides: str) -> str:
    query = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": "66040c77ac1b787c3af820529859349a/20260726/auto/s3/aws4_request",
        "X-Amz-Date": "20260726T113924Z",
        "X-Amz-Expires": "86400",
        "X-Amz-SignedHeaders": "host",
        "X-Amz-Signature": "a" * 64,
    }
    query.update(query_overrides)
    return (
        "https://dd20bb891979d25aebc8bec07b2b3bbc.r2.cloudflarestorage.com"
        f"/ollama/docker/registry/v2/blobs/sha256/{digest[:2]}/{digest}/data?"
        + urllib.parse.urlencode(query)
    )


def test_blob_redirect_accepts_only_exact_digest_bound_official_r2_url(
    provisioner: object,
) -> None:
    digest = "1a" + ("b" * 62)
    expected_path = f"/v2/library/fixture/blobs/sha256:{digest}"

    provisioner._validate_final_registry_url(
        _official_r2_url(digest),
        expected_path=expected_path,
        expected_blob_digest=digest,
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda url, _digest: url.replace("https://", "http://", 1),
        lambda url, _digest: url.replace(
            ".r2.cloudflarestorage.com", ".r2.cloudflarestorage.com.evil.example", 1
        ),
        lambda url, _digest: url.replace(
            "dd20bb891979d25aebc8bec07b2b3bbc",
            "not-an-account",
            1,
        ),
        lambda url, digest: url.replace(f"/{digest[:2]}/{digest}/", f"/ff/{digest}/", 1),
        lambda url, digest: url.replace(digest, "2c" + ("d" * 62), 1),
        lambda url, _digest: url + "&unexpected=true",
        lambda url, _digest: url + "&X-Amz-Signature=" + ("b" * 64),
        lambda url, _digest: url.replace("X-Amz-Expires=86400", "X-Amz-Expires=86401"),
        lambda url, _digest: url.replace("X-Amz-SignedHeaders=host", "X-Amz-SignedHeaders=x"),
        lambda url, _digest: url.replace("X-Amz-Signature=" + ("a" * 64), "X-Amz-Signature=A"),
        lambda url, _digest: url + "#fragment",
    ],
)
def test_blob_redirect_rejects_untrusted_r2_variants(
    provisioner: object,
    mutate: object,
) -> None:
    digest = "1a" + ("b" * 62)
    expected_path = f"/v2/library/fixture/blobs/sha256:{digest}"
    value = mutate(_official_r2_url(digest), digest)

    with pytest.raises(provisioner.ModelProvisionError, match="redirect refused"):
        provisioner._validate_final_registry_url(
            value,
            expected_path=expected_path,
            expected_blob_digest=digest,
        )


def test_manifest_redirect_cannot_use_blob_r2_exception(provisioner: object) -> None:
    digest = "1a" + ("b" * 62)

    with pytest.raises(provisioner.ModelProvisionError, match="redirect refused"):
        provisioner._validate_final_registry_url(
            _official_r2_url(digest),
            expected_path="/v2/library/fixture/manifests/one",
        )
