#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Assemble the online first-install delivery from an exact signed candidate kit.

This is packaging, not publication. Existing component verification and offline
station activation contracts remain authoritative. No model is repacked.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from civiccast.installer.native_distribution import canonical_json  # noqa: E402
from civiccast.installer.native_packs import build_native_pack, verify_native_pack  # noqa: E402
from scripts.build_native_station_bundle import (  # noqa: E402
    REQUIRED_COMPONENTS as STATION_COMPONENTS,
)
from scripts.build_native_station_bundle import (  # noqa: E402
    STATION_MODEL_PACK_PRODUCT_VERSION,
    _build_station_index,
    _station_component_sort_key,
    require_allowed_signing_key,
)

RUNTIME_COMPONENTS = (
    "native-server-binaries",
    "native-app-payload",
    "native-ffmpeg-runtime",
    "native-ollama-runtime",
)
REQUIRED_COMPONENTS = (*STATION_COMPONENTS, *RUNTIME_COMPONENTS, "installer-bootstrap")
OPTIONAL_COMPONENTS = ("captions-large-v3", "native-cuda-runtime")


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _regular(path: Path) -> Path:
    if path.is_symlink() or path.is_junction() or not path.is_file():
        raise ValueError(f"Expected a regular candidate file: {path.name}")
    return path


def write_channel_index(
    *,
    output: Path,
    packs: dict[str, Path],
    private_key: Ed25519PrivateKey,
    key_id: str,
    version: str,
    channel: str,
    base_url: str,
    created_epoch: int,
) -> None:
    """Sign only the complete current first-install plan; extras fail closed."""
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,126}", version)
        or not re.fullmatch(r"[a-z0-9-]+", channel)
        or not key_id
        or key_id.strip() != key_id
        or type(created_epoch) is not int
        or created_epoch < 0
    ):
        raise ValueError("Invalid first-install release identity")
    if not set(REQUIRED_COMPONENTS) <= set(packs) or set(packs) - {
        *REQUIRED_COMPONENTS,
        *OPTIONAL_COMPONENTS,
    }:
        raise ValueError("First-install component set is incomplete or unsupported")
    try:
        url = urlsplit(base_url)
        port = url.port
    except ValueError as exc:
        raise ValueError("First-install assets require an unambiguous HTTPS base URL") from exc
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or (port is not None and not 1 <= port <= 65535)
        or url.query
        or url.fragment
    ):
        raise ValueError("First-install assets require an unambiguous HTTPS base URL")
    if output.exists():
        raise FileExistsError(output)
    entries = []
    filenames = set()
    for component in sorted(packs, key=_station_component_sort_key):
        path = _regular(packs[component])
        if path.name.casefold() in filenames or path.stat().st_size == 0:
            raise ValueError("First-install assets must be nonempty with unique filenames")
        if url.hostname.lower() == "github.com" and path.stat().st_size >= 2 * 1024**3:
            raise ValueError(
                "GitHub release assets cannot deliver this pack: use a large-object HTTPS host"
            )
        filenames.add(path.name.casefold())
        entries.append(
            {
                "component": component,
                "filename": path.name,
                "bytes": path.stat().st_size,
                "sha256": _digest(path),
                "required": component in REQUIRED_COMPONENTS,
                "urls": [base_url.rstrip("/") + "/" + quote(path.name, safe="-._~")],
            }
        )
    manifest = {
        "schema_version": 1,
        "product": "civiccast-native",
        "kind": "channel-index",
        "channel": channel,
        "product_version": version,
        "compatible_core": version,
        "signing_key_id": key_id,
        "created_epoch": created_epoch,
        "packs": entries,
    }
    output.write_bytes(
        canonical_json(
            {
                "manifest": manifest,
                "signature": base64.b64encode(private_key.sign(canonical_json(manifest))).decode(
                    "ascii"
                ),
            }
        )
    )


def assemble(
    *,
    candidate: Path,
    station: Path,
    output: Path,
    private_key: Ed25519PrivateKey,
    key_id: str,
    version: str,
    source_sha: str,
    channel: str,
    base_url: str,
    created_epoch: int,
) -> Path:
    """Verify existing signed bytes, then stage one complete online delivery."""
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("An exact source SHA is required")
    if output.exists():
        raise FileExistsError("First-install output must be a new directory")
    receipt = json.loads(_regular(candidate / "candidate-receipt.json").read_text("utf-8-sig"))
    if (
        receipt.get("source_sha") != source_sha
        or receipt.get("authenticode_status") != "Valid"
        or receipt.get("pack_signing_key_id") != key_id
    ):
        raise ValueError("Signed candidate receipt does not match this source and trust root")
    setups = list(candidate.glob("CivicCast (Native)_*_x64-setup.exe"))
    if len(setups) != 1:
        raise ValueError("Expected exactly one freshly built candidate setup")
    setup = _regular(setups[0])
    launcher = _regular(candidate / "CivicCast First Install.exe")
    checksums = {}
    for line in (candidate / "SHA256SUMS.txt").read_text("utf-8-sig").splitlines():
        digest, name = line.split("  ", 1)
        checksums[name] = digest
    for executable in (setup, launcher):
        if executable.name not in receipt.get("assets", []) or checksums.get(
            executable.name
        ) != _digest(executable):
            raise ValueError(
                "Candidate executable is absent from or differs from the signed build receipt"
            )

    packs = {component: station / f"{component}.ccpack" for component in STATION_COMPONENTS}
    packs.update(
        {component: candidate / "packs" / f"{component}.ccpack" for component in RUNTIME_COMPONENTS}
    )
    for component, root in (
        ("captions-large-v3", station),
        ("native-cuda-runtime", candidate / "packs"),
    ):
        if (root / f"{component}.ccpack").exists():
            packs[component] = root / f"{component}.ccpack"
    for component, path in packs.items():
        model = component in (*STATION_COMPONENTS[1:], "captions-large-v3")
        identity = STATION_MODEL_PACK_PRODUCT_VERSION if model else version
        verified = verify_native_pack(
            _regular(path),
            public_key=private_key.public_key(),
            expected_component=component,
            expected_product_version=identity,
            expected_compatible_core=identity,
            expected_signing_key_id=key_id,
        )
        if (
            component in ("native-app-payload", "native-server-binaries")
            and verified.metadata.get("source_sha") != source_sha
        ):
            raise ValueError(f"{component} is not from the exact candidate source")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="first-install-", dir=output.parent) as scratch:
        stage = Path(scratch) / "delivery"
        stage.mkdir()
        variants = Path(scratch) / "station-indexes"
        variants.mkdir()
        bootstrap_sources = {"setup.exe": setup}
        for variant, selected in (
            ("baseline", STATION_COMPONENTS),
            ("large", (*STATION_COMPONENTS, "captions-large-v3")),
        ):
            if not set(selected) <= set(packs):
                continue
            index = variants / f"{variant}.json"
            _build_station_index(
                output=index,
                channel=channel,
                product_version=version,
                compatible_core=version,
                signing_key_id=key_id,
                created_epoch=created_epoch,
                packs={name: packs[name] for name in selected},
                signing_private_key=private_key,
            )
            bootstrap_sources[f"station-indexes/{variant}.json"] = index
        bootstrap = stage / "installer-bootstrap.ccpack"
        build_native_pack(
            output=bootstrap,
            component="installer-bootstrap",
            product_version=version,
            compatible_core=version,
            sources=bootstrap_sources,
            signing_private_key=private_key,
            signing_key_id=key_id,
            metadata={"source_sha": source_sha, "setup_sha256": _digest(setup)},
        )
        for component, path in list(packs.items()):
            destination = stage / path.name
            shutil.copyfile(path, destination)
            packs[component] = destination
        packs["installer-bootstrap"] = bootstrap
        write_channel_index(
            output=stage / "first-install.channel.json",
            packs=packs,
            private_key=private_key,
            key_id=key_id,
            version=version,
            channel=channel,
            base_url=base_url,
            created_epoch=created_epoch,
        )
        shutil.copyfile(launcher, stage / launcher.name)
        (stage / "first-install.json").write_bytes(
            canonical_json(
                {
                    "schema_version": 1,
                    "product_version": version,
                    "compatible_core": version,
                    "channel": channel,
                    "channel_url": base_url.rstrip("/") + "/first-install.channel.json",
                }
            )
        )
        stage.replace(output)
    return output / "first-install.channel.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("candidate", "station", "output", "signing-private-key"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("signing-key-id", "product-version", "source-sha", "base-url"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--channel", default="beta")
    parser.add_argument("--created-epoch", type=int, required=True)
    parser.add_argument("--allow-development-key", action="store_true")
    args = parser.parse_args()
    require_allowed_signing_key(
        args.signing_key_id, allow_development_key=args.allow_development_key
    )
    key = serialization.load_pem_private_key(args.signing_private_key.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Pack signing key must be Ed25519")
    result = assemble(
        candidate=args.candidate,
        station=args.station,
        output=args.output,
        private_key=key,
        key_id=args.signing_key_id,
        version=args.product_version,
        source_sha=args.source_sha,
        channel=args.channel,
        base_url=args.base_url,
        created_epoch=args.created_epoch,
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
