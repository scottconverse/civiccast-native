# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Provision the exact offline Ollama model stores required by CivicCast Native."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

ROOT: Final[Path] = Path(__file__).resolve().parent.parent
LOCK_PATH: Final[Path] = ROOT / "native-windows-ollama-models.lock.json"
DEFAULT_CACHE: Final[Path] = ROOT / "build" / "native-model-cache-ollama"
DEFAULT_OUTPUT: Final[Path] = ROOT / "build" / "native-ollama-models"
PROVENANCE_NAME: Final[str] = "MODEL-PROVENANCE.json"
_CHUNK_BYTES: Final[int] = 1024 * 1024
_REGISTRY: Final[str] = "registry.ollama.ai"
_ROOT_FIELDS: Final[frozenset[str]] = frozenset(
    {"schema_version", "registry", "ollama_runtime_version", "models"}
)
_MODEL_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "component",
        "repository",
        "tag",
        "manifest_bytes",
        "manifest_sha256",
        "config",
        "layers",
    }
)
_IDENTITY_FIELDS: Final[frozenset[str]] = frozenset({"bytes", "sha256"})
_LAYER_FIELDS: Final[frozenset[str]] = frozenset({"bytes", "sha256", "media_type"})
_MEDIA_TYPES: Final[frozenset[str]] = frozenset(
    {
        "application/vnd.ollama.image.model",
        "application/vnd.ollama.image.projector",
        "application/vnd.ollama.image.license",
        "application/vnd.ollama.image.params",
        "application/vnd.ollama.image.template",
    }
)
_COMPONENT_RE: Final[re.Pattern[str]] = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?\Z")
_REGISTRY_NAME_RE: Final[re.Pattern[str]] = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?\Z")
_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{64}\Z")
_R2_HOST_RE: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{32}\.r2\.cloudflarestorage\.com\Z")
_AMZ_CREDENTIAL_RE: Final[re.Pattern[str]] = re.compile(
    r"[0-9a-f]{32}/(?P<date>[0-9]{8})/auto/s3/aws4_request\Z"
)
_AMZ_DATE_RE: Final[re.Pattern[str]] = re.compile(r"(?P<date>[0-9]{8})T[0-9]{6}Z\Z")
_AMZ_SIGNATURE_RE: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{64}\Z")
_AMZ_QUERY_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "X-Amz-Algorithm",
        "X-Amz-Credential",
        "X-Amz-Date",
        "X-Amz-Expires",
        "X-Amz-SignedHeaders",
        "X-Amz-Signature",
    }
)
_REPARSE_POINT: Final[int] = 0x400


class ModelProvisionError(RuntimeError):
    """A required model could not be reconstructed from its reviewed lock."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _lock_sha256(path: Path) -> str:
    return _sha256_file(path)


def _validate_identity(identity: object, *, label: str) -> dict[str, Any]:
    if not isinstance(identity, dict) or set(identity) != _IDENTITY_FIELDS:
        raise ModelProvisionError(f"{label} identity fields are invalid")
    byte_count = identity.get("bytes")
    digest = identity.get("sha256")
    if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count <= 0:
        raise ModelProvisionError(f"{label} byte count is invalid")
    if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
        raise ModelProvisionError(f"{label} SHA-256 is invalid")
    return identity


def validate_lock(lock: Mapping[str, Any]) -> None:
    """Validate the complete immutable model acquisition contract."""

    if set(lock) != _ROOT_FIELDS or lock.get("schema_version") != 1:
        raise ModelProvisionError("unsupported Ollama model lock schema")
    if lock.get("registry") != _REGISTRY:
        raise ModelProvisionError("Ollama model registry identity is invalid")
    runtime_version = lock.get("ollama_runtime_version")
    if (
        not isinstance(runtime_version, str)
        or not runtime_version
        or runtime_version.strip() != runtime_version
        or not runtime_version.isascii()
    ):
        raise ModelProvisionError("Ollama runtime version is invalid")
    models = lock.get("models")
    if not isinstance(models, dict) or not models:
        raise ModelProvisionError("Ollama model lock has no models")

    seen_components: set[str] = set()
    for name, model in models.items():
        if not isinstance(name, str) or _REGISTRY_NAME_RE.fullmatch(name) is None:
            raise ModelProvisionError(f"Ollama model name is invalid: {name!r}")
        if not isinstance(model, dict) or set(model) != _MODEL_FIELDS:
            raise ModelProvisionError(f"{name} model fields are invalid")
        component = model.get("component")
        if not isinstance(component, str) or _COMPONENT_RE.fullmatch(component) is None:
            raise ModelProvisionError(f"{name} component identity is invalid")
        if component in seen_components:
            raise ModelProvisionError(f"duplicate Ollama component identity: {component}")
        seen_components.add(component)
        for field in ("repository", "tag"):
            value = model.get(field)
            if not isinstance(value, str) or _REGISTRY_NAME_RE.fullmatch(value) is None:
                raise ModelProvisionError(f"{name} {field} is invalid")
        manifest_bytes = model.get("manifest_bytes")
        manifest_sha = model.get("manifest_sha256")
        if (
            not isinstance(manifest_bytes, int)
            or isinstance(manifest_bytes, bool)
            or manifest_bytes <= 0
        ):
            raise ModelProvisionError(f"{name} manifest byte count is invalid")
        if not isinstance(manifest_sha, str) or _SHA256_RE.fullmatch(manifest_sha) is None:
            raise ModelProvisionError(f"{name} manifest SHA-256 is invalid")
        _validate_identity(model.get("config"), label=f"{name} config")
        layers = model.get("layers")
        if not isinstance(layers, list) or not layers:
            raise ModelProvisionError(f"{name} layers are invalid")
        seen_digests = {model["config"]["sha256"]}
        media_types: list[str] = []
        for index, layer in enumerate(layers):
            if not isinstance(layer, dict) or set(layer) != _LAYER_FIELDS:
                raise ModelProvisionError(f"{name} layer {index} fields are invalid")
            _validate_identity(
                {"bytes": layer.get("bytes"), "sha256": layer.get("sha256")},
                label=f"{name} layer {index}",
            )
            digest = layer["sha256"]
            if digest in seen_digests:
                raise ModelProvisionError(f"{name} repeats blob identity {digest}")
            seen_digests.add(digest)
            media_type = layer.get("media_type")
            if media_type not in _MEDIA_TYPES:
                raise ModelProvisionError(f"{name} layer media type is invalid")
            media_types.append(media_type)
        if media_types.count("application/vnd.ollama.image.model") != 1:
            raise ModelProvisionError(f"{name} must contain exactly one model layer")
        if media_types.count("application/vnd.ollama.image.license") != 1:
            raise ModelProvisionError(f"{name} must contain exactly one license layer")


def load_lock(path: Path = LOCK_PATH) -> dict[str, Any]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModelProvisionError(f"cannot read Ollama model lock {path}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ModelProvisionError("Ollama model lock root must be an object")
    validate_lock(parsed)
    return parsed


def _manifest_url(model: Mapping[str, Any]) -> str:
    repository = urllib.parse.quote(str(model["repository"]), safe="")
    tag = urllib.parse.quote(str(model["tag"]), safe="")
    return f"https://{_REGISTRY}/v2/library/{repository}/manifests/{tag}"


def _blob_url(model: Mapping[str, Any], digest: str) -> str:
    repository = urllib.parse.quote(str(model["repository"]), safe="")
    return f"https://{_REGISTRY}/v2/library/{repository}/blobs/sha256:{digest}"


def _verify_file(path: Path, identity: Mapping[str, Any], *, label: str) -> None:
    _require_regular_file(path, label=label)
    actual_size = path.stat().st_size
    expected_size = int(identity["bytes"])
    if actual_size != expected_size:
        raise ModelProvisionError(f"{label} size {actual_size} != reviewed {expected_size}")
    actual_sha = _sha256_file(path)
    expected_sha = str(identity["sha256"])
    if actual_sha != expected_sha:
        raise ModelProvisionError(f"{label} SHA-256 {actual_sha} != reviewed {expected_sha}")


def _validate_final_registry_url(
    value: str,
    *,
    expected_path: str,
    expected_blob_digest: str | None = None,
) -> None:
    """Permit the registry itself or its tightly bound presigned R2 blob redirect."""

    try:
        parsed = urllib.parse.urlparse(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ModelProvisionError(f"Ollama registry redirect refused: {value}") from exc

    common_invalid = (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.params
        or port is not None
    )
    if common_invalid:
        raise ModelProvisionError(f"Ollama registry redirect refused: {value}")

    if hostname == _REGISTRY and parsed.path == expected_path and not parsed.query:
        return

    if (
        expected_blob_digest is None
        or _SHA256_RE.fullmatch(expected_blob_digest) is None
        or hostname is None
        or _R2_HOST_RE.fullmatch(hostname) is None
        or parsed.path
        != (
            "/ollama/docker/registry/v2/blobs/sha256/"
            f"{expected_blob_digest[:2]}/{expected_blob_digest}/data"
        )
    ):
        raise ModelProvisionError(f"Ollama registry redirect refused: {value}")

    try:
        pairs = urllib.parse.parse_qsl(
            parsed.query,
            keep_blank_values=True,
            strict_parsing=True,
        )
    except ValueError as exc:
        raise ModelProvisionError(f"Ollama registry redirect refused: {value}") from exc
    if len(pairs) != len(_AMZ_QUERY_FIELDS) or {key for key, _value in pairs} != _AMZ_QUERY_FIELDS:
        raise ModelProvisionError(f"Ollama registry redirect refused: {value}")
    query = dict(pairs)
    credential_match = _AMZ_CREDENTIAL_RE.fullmatch(query["X-Amz-Credential"])
    date_match = _AMZ_DATE_RE.fullmatch(query["X-Amz-Date"])
    try:
        expires = int(query["X-Amz-Expires"], 10)
    except ValueError as exc:
        raise ModelProvisionError(f"Ollama registry redirect refused: {value}") from exc
    if (
        query["X-Amz-Algorithm"] != "AWS4-HMAC-SHA256"
        or credential_match is None
        or date_match is None
        or credential_match.group("date") != date_match.group("date")
        or not 0 < expires <= 86_400
        or str(expires) != query["X-Amz-Expires"]
        or query["X-Amz-SignedHeaders"] != "host"
        or _AMZ_SIGNATURE_RE.fullmatch(query["X-Amz-Signature"]) is None
    ):
        raise ModelProvisionError(f"Ollama registry redirect refused: {value}")


def fetch_manifest(
    name: str,
    model: Mapping[str, Any],
    cache: Path,
    *,
    offline: bool = False,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> Path:
    """Fetch raw tag-manifest bytes and bind them to the reviewed digest."""

    destination = cache / "manifests" / f"{model['manifest_sha256']}.json"
    identity = {
        "bytes": model["manifest_bytes"],
        "sha256": model["manifest_sha256"],
    }
    if destination.exists():
        _verify_file(destination, identity, label=f"{name} manifest")
        return destination
    if offline:
        raise ModelProvisionError(f"offline cache is missing {name} manifest")
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(".json.partial")
    partial.unlink(missing_ok=True)
    url = _manifest_url(model)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.docker.distribution.manifest.v2+json",
            "User-Agent": "CivicCast-native-model-provisioner/1",
        },
    )
    expected_path = urllib.parse.urlparse(url).path
    try:
        with opener(request, timeout=60) as response:
            _validate_final_registry_url(response.geturl(), expected_path=expected_path)
            with partial.open("xb") as output:
                observed = 0
                while chunk := response.read(_CHUNK_BYTES):
                    observed += len(chunk)
                    if observed > int(model["manifest_bytes"]):
                        raise ModelProvisionError(f"{name} manifest exceeds reviewed size")
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
        _verify_file(partial, identity, label=f"{name} manifest")
        partial.replace(destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return destination


def fetch_blob(
    name: str,
    model: Mapping[str, Any],
    identity: Mapping[str, Any],
    cache: Path,
    *,
    offline: bool = False,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> Path:
    """Fetch one content-addressed model blob with verified resume support."""

    digest = str(identity["sha256"])
    destination = cache / "blobs" / f"sha256-{digest}"
    if destination.exists():
        _verify_file(destination, identity, label=f"{name} blob {digest}")
        return destination
    if offline:
        raise ModelProvisionError(f"offline cache is missing {name} blob {digest}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".partial")
    if partial.exists() and partial.stat().st_size > int(identity["bytes"]):
        partial.unlink()
    offset = partial.stat().st_size if partial.exists() else 0
    url = _blob_url(model, digest)
    headers = {"User-Agent": "CivicCast-native-model-provisioner/1"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = urllib.request.Request(url, headers=headers)
    expected_path = urllib.parse.urlparse(url).path
    try:
        with opener(request, timeout=60) as response:
            _validate_final_registry_url(
                response.geturl(),
                expected_path=expected_path,
                expected_blob_digest=digest,
            )
            status = int(getattr(response, "status", 200))
            append = offset > 0 and status == 206
            if offset > 0 and status not in {200, 206}:
                raise ModelProvisionError(f"{name} blob resume returned unexpected HTTP {status}")
            if status == 206:
                expected_prefix = f"bytes {offset}-"
                content_range = response.headers.get("Content-Range", "")
                if not content_range.startswith(expected_prefix):
                    raise ModelProvisionError(f"{name} blob resume Content-Range is invalid")
            if status == 200:
                offset = 0
                append = False
            mode = "ab" if append else "wb"
            observed = offset
            with partial.open(mode) as output:
                while chunk := response.read(_CHUNK_BYTES):
                    observed += len(chunk)
                    if observed > int(identity["bytes"]):
                        raise ModelProvisionError(f"{name} blob exceeds reviewed byte count")
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
        if partial.stat().st_size != int(identity["bytes"]):
            raise ModelProvisionError(f"{name} blob download is incomplete; rerun to resume")
        _verify_file(partial, identity, label=f"{name} blob {digest}")
        partial.replace(destination)
    except ModelProvisionError:
        if partial.exists() and partial.stat().st_size == int(identity["bytes"]):
            partial.unlink(missing_ok=True)
        raise
    return destination


def _validate_manifest_semantics(
    name: str,
    raw: bytes,
    model: Mapping[str, Any],
) -> None:
    try:
        manifest = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelProvisionError(f"{name} manifest is invalid JSON") from exc
    if not isinstance(manifest, dict):
        raise ModelProvisionError(f"{name} manifest root is invalid")
    if (
        manifest.get("schemaVersion") != 2
        or manifest.get("mediaType") != "application/vnd.docker.distribution.manifest.v2+json"
    ):
        raise ModelProvisionError(f"{name} manifest schema or media type is invalid")
    config = manifest.get("config")
    if not isinstance(config, dict):
        raise ModelProvisionError(f"{name} manifest config is invalid")
    if (
        config.get("mediaType") != "application/vnd.docker.container.image.v1+json"
        or config.get("digest") != f"sha256:{model['config']['sha256']}"
        or config.get("size") != model["config"]["bytes"]
    ):
        raise ModelProvisionError(f"{name} manifest config identity is invalid")
    manifest_layers = manifest.get("layers")
    if not isinstance(manifest_layers, list) or len(manifest_layers) != len(model["layers"]):
        raise ModelProvisionError(f"{name} manifest layers are invalid")
    for index, (observed, expected) in enumerate(
        zip(manifest_layers, model["layers"], strict=True)
    ):
        if not isinstance(observed, dict) or (
            observed.get("mediaType") != expected["media_type"]
            or observed.get("digest") != f"sha256:{expected['sha256']}"
            or observed.get("size") != expected["bytes"]
        ):
            raise ModelProvisionError(
                f"{name} manifest layer {index} media type or identity is invalid"
            )


def stage_model(
    name: str,
    *,
    lock_path: Path = LOCK_PATH,
    cache: Path = DEFAULT_CACHE,
    output: Path,
    offline: bool = False,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> Path:
    """Reconstruct one exact Ollama model-store tree from verified cache bytes."""

    lock = load_lock(lock_path)
    try:
        model = lock["models"][name]
    except KeyError as exc:
        raise ModelProvisionError(f"unknown reviewed Ollama model: {name}") from exc
    manifest_path = fetch_manifest(name, model, cache, offline=offline, opener=opener)
    identities = [model["config"], *model["layers"]]
    blob_paths = [
        fetch_blob(
            name,
            model,
            identity,
            cache,
            offline=offline,
            opener=opener,
        )
        for identity in identities
    ]
    manifest_raw = manifest_path.read_bytes()
    _validate_manifest_semantics(name, manifest_raw, model)

    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"Ollama model output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.", suffix=".staging", dir=output.parent)
    )
    try:
        blobs_root = temporary / "blobs"
        blobs_root.mkdir()
        for identity, source in zip(identities, blob_paths, strict=True):
            destination = blobs_root / f"sha256-{identity['sha256']}"
            try:
                os.link(source, destination)
            except OSError:
                shutil.copy2(source, destination)
        destination_manifest = (
            temporary
            / "manifests"
            / _REGISTRY
            / "library"
            / str(model["repository"])
            / str(model["tag"])
        )
        destination_manifest.parent.mkdir(parents=True)
        destination_manifest.write_bytes(manifest_raw)
        provenance = {
            "schema_version": 1,
            "component": model["component"],
            "model_name": name,
            "repository": model["repository"],
            "tag": model["tag"],
            "manifest_bytes": model["manifest_bytes"],
            "manifest_sha256": model["manifest_sha256"],
            "ollama_runtime_version": lock["ollama_runtime_version"],
            "lock_sha256": _lock_sha256(lock_path),
            "blobs": [
                {
                    "bytes": identity["bytes"],
                    "sha256": identity["sha256"],
                }
                for identity in identities
            ],
        }
        (temporary / PROVENANCE_NAME).write_text(
            json.dumps(provenance, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        temporary.replace(output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    verify_staged_model(name, output, lock_path=lock_path)
    return output / PROVENANCE_NAME


def verify_staged_model(
    name: str,
    output: Path,
    *,
    lock_path: Path = LOCK_PATH,
) -> None:
    """Re-verify a staged store bidirectionally against the model lock."""

    lock = load_lock(lock_path)
    try:
        model = lock["models"][name]
    except KeyError as exc:
        raise ModelProvisionError(f"unknown reviewed Ollama model: {name}") from exc
    expected: dict[str, Mapping[str, Any]] = {
        f"blobs/sha256-{model['config']['sha256']}": model["config"],
        **{f"blobs/sha256-{layer['sha256']}": layer for layer in model["layers"]},
        (f"manifests/{_REGISTRY}/library/{model['repository']}/{model['tag']}"): {
            "bytes": model["manifest_bytes"],
            "sha256": model["manifest_sha256"],
        },
    }
    actual = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file() and path.name != PROVENANCE_NAME
    }
    if actual != set(expected):
        missing = sorted(set(expected) - actual)
        extra = sorted(actual - set(expected))
        raise ModelProvisionError(
            f"{name} staged model inventory mismatch; missing={missing}, extra={extra}"
        )
    for relative, identity in expected.items():
        _verify_file(output / relative, identity, label=f"{name} staged {relative}")
    provenance_path = output / PROVENANCE_NAME
    _require_regular_file(provenance_path, label=f"{name} provenance")
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModelProvisionError(f"{name} provenance is invalid") from exc
    if (
        provenance.get("component") != model["component"]
        or provenance.get("manifest_sha256") != model["manifest_sha256"]
        or provenance.get("lock_sha256") != _lock_sha256(lock_path)
    ):
        raise ModelProvisionError(f"{name} provenance identity is invalid")


def _require_regular_file(path: Path, *, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ModelProvisionError(f"{label} is missing: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise ModelProvisionError(f"{label} must not be a symbolic link")
    if getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT:
        raise ModelProvisionError(f"{label} must not be a reparse point")
    if not stat.S_ISREG(metadata.st_mode):
        raise ModelProvisionError(f"{label} must be a regular file")


def provision_all(
    *,
    lock_path: Path = LOCK_PATH,
    cache: Path = DEFAULT_CACHE,
    output: Path = DEFAULT_OUTPUT,
    offline: bool = False,
) -> list[Path]:
    lock = load_lock(lock_path)
    output.mkdir(parents=True, exist_ok=True)
    results: list[Path] = []
    for name, model in sorted(lock["models"].items()):
        destination = output / str(model["component"])
        if destination.exists():
            verify_staged_model(name, destination, lock_path=lock_path)
            results.append(destination / PROVENANCE_NAME)
            continue
        results.append(
            stage_model(
                name,
                lock_path=lock_path,
                cache=cache,
                output=destination,
                offline=offline,
            )
        )
    return results


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=LOCK_PATH)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model")
    parser.add_argument("--offline", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.model:
        result = stage_model(
            args.model,
            lock_path=args.lock,
            cache=args.cache,
            output=args.output,
            offline=args.offline,
        )
        rendered = [str(result)]
    else:
        rendered = [
            str(path)
            for path in provision_all(
                lock_path=args.lock,
                cache=args.cache,
                output=args.output,
                offline=args.offline,
            )
        ]
    print(json.dumps({"status": "PASS", "provenance": rendered}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
