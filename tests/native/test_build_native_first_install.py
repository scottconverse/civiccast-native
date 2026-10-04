# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""First-install packaging checks, not clean-machine installation proof."""

from __future__ import annotations

import base64
import hashlib
import importlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from civiccast.installer.native_distribution import canonical_json
from civiccast.installer.native_packs import verify_native_pack


def test_channel_builder_exists_and_preserves_optional_selection(tmp_path: Path) -> None:
    path = Path(__file__).resolve().parents[2] / "scripts/build_native_first_install.py"
    assert path.is_file(), "No build path produces the signed first-install channel authority"
    builder = importlib.import_module("scripts.build_native_first_install")
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    packs = {}
    for component in (*builder.REQUIRED_COMPONENTS, *builder.OPTIONAL_COMPONENTS):
        pack = tmp_path / f"{component}.ccpack"
        pack.write_bytes(component.encode())
        packs[component] = pack
    output = tmp_path / "channel.json"
    builder.write_channel_index(
        output=output,
        packs=packs,
        private_key=key,
        key_id="development-test",
        version="test-1",
        channel="beta",
        base_url="https://example.invalid/assets/",
        created_epoch=1,
    )
    envelope = json.loads(output.read_text())
    manifest = envelope["manifest"]
    key.public_key().verify(base64.b64decode(envelope["signature"]), canonical_json(manifest))
    assert manifest["kind"] == "channel-index"
    assert manifest["product_version"] == manifest["compatible_core"] == "test-1"
    entries = {entry["component"]: entry for entry in manifest["packs"]}
    assert {name for name, entry in entries.items() if entry["required"]} == set(
        builder.REQUIRED_COMPONENTS
    )
    assert not entries["captions-large-v3"]["required"]
    assert not entries["native-cuda-runtime"]["required"]
    assert all(
        entry["urls"] == [f"https://example.invalid/assets/{name}.ccpack"]
        for name, entry in entries.items()
    )


def test_channel_builder_rejects_incomplete_plan_before_output(tmp_path: Path) -> None:
    path = Path(__file__).resolve().parents[2] / "scripts/build_native_first_install.py"
    assert path.is_file(), "No build path produces the signed first-install channel authority"
    builder = importlib.import_module("scripts.build_native_first_install")
    with pytest.raises(ValueError, match="component set"):
        builder.write_channel_index(
            output=tmp_path / "channel.json",
            packs={},
            private_key=Ed25519PrivateKey.from_private_bytes(bytes(range(32))),
            key_id="development-test",
            version="test-1",
            channel="beta",
            base_url="https://example.invalid/assets/",
            created_epoch=1,
        )
    assert not (tmp_path / "channel.json").exists()


@pytest.mark.parametrize(
    "base_url", ["https://@example.invalid/assets", "https://example.invalid:invalid/assets"]
)
def test_channel_builder_rejects_urls_the_installer_cannot_use(
    tmp_path: Path, base_url: str
) -> None:
    builder = importlib.import_module("scripts.build_native_first_install")
    packs = {}
    for component in builder.REQUIRED_COMPONENTS:
        pack = tmp_path / f"{component}.ccpack"
        pack.write_bytes(component.encode())
        packs[component] = pack
    output = tmp_path / "channel.json"
    with pytest.raises(ValueError, match="HTTPS base URL"):
        builder.write_channel_index(
            output=output,
            packs=packs,
            private_key=Ed25519PrivateKey.from_private_bytes(bytes(range(32))),
            key_id="development-test",
            version="test-1",
            channel="beta",
            base_url=base_url,
            created_epoch=1,
        )
    assert not output.exists()


def test_assembly_binds_setup_station_variants_and_double_click_config(
    tmp_path: Path, monkeypatch
) -> None:
    builder = importlib.import_module("scripts.build_native_first_install")
    candidate, station = tmp_path / "candidate", tmp_path / "station"
    (candidate / "packs").mkdir(parents=True)
    station.mkdir()
    source_sha = "a" * 40
    names = ["CivicCast (Native)_test-1_x64-setup.exe", "CivicCast First Install.exe"]
    for name in names:
        (candidate / name).write_bytes(b"synthetic executable packaging fixture")
    (candidate / "candidate-receipt.json").write_text(
        json.dumps(
            {
                "source_sha": source_sha,
                "authenticode_status": "Valid",
                "pack_signing_key_id": "development-test",
                "assets": names,
            }
        )
    )
    (candidate / "SHA256SUMS.txt").write_text(
        "\n".join(
            f"{hashlib.sha256((candidate / name).read_bytes()).hexdigest()}  {name}"
            for name in names
        )
    )
    for component in (*builder.STATION_COMPONENTS, "captions-large-v3"):
        (station / f"{component}.ccpack").write_bytes(component.encode())
    for component in (*builder.RUNTIME_COMPONENTS, "native-cuda-runtime"):
        (candidate / "packs" / f"{component}.ccpack").write_bytes(component.encode())
    # Assembly contract only: real multi-GB model verification is not simulated
    # as installation proof. The newly emitted bootstrap is verified for real.
    observed = []

    def verified(path, **kwargs):
        observed.append(kwargs)
        return SimpleNamespace(metadata={"source_sha": source_sha})

    monkeypatch.setattr(builder, "verify_native_pack", verified)
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    output = tmp_path / "output"
    builder.assemble(
        candidate=candidate,
        station=station,
        output=output,
        private_key=key,
        key_id="development-test",
        version="test-1",
        source_sha=source_sha,
        channel="beta",
        base_url="https://example.invalid/assets/",
        created_epoch=1,
    )
    config = json.loads((output / "first-install.json").read_text())
    assert config == {
        "schema_version": 1,
        "product_version": "test-1",
        "compatible_core": "test-1",
        "channel": "beta",
        "channel_url": "https://example.invalid/assets/first-install.channel.json",
    }
    bootstrap = output / "installer-bootstrap.ccpack"
    verify_native_pack(
        bootstrap,
        public_key=key.public_key(),
        expected_component="installer-bootstrap",
        expected_product_version="test-1",
        expected_compatible_core="test-1",
        expected_signing_key_id="development-test",
    )
    with zipfile.ZipFile(bootstrap) as archive:
        assert archive.read("payload/setup.exe") == (candidate / names[0]).read_bytes()
        for variant, expected in (
            ("baseline", set(builder.STATION_COMPONENTS)),
            ("large", {*builder.STATION_COMPONENTS, "captions-large-v3"}),
        ):
            envelope = json.loads(archive.read(f"payload/station-indexes/{variant}.json"))
            key.public_key().verify(
                base64.b64decode(envelope["signature"]), canonical_json(envelope["manifest"])
            )
            assert {p["component"] for p in envelope["manifest"]["packs"]} == expected
            assert all(p["urls"] == [] for p in envelope["manifest"]["packs"])
    assert len(observed) == 11
    assert all(
        item["expected_product_version"] == "test-1"
        for item in observed
        if item["expected_component"].startswith("native-")
    )
