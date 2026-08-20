# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Signed online/offline distribution contracts for the native bootstrap."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from civiccast.installer.native_distribution import (
    REQUIRED_COMPONENTS,
    NativeDistributionError,
    build_distribution_index,
    verify_distribution_index,
    verify_station_media,
)

PRODUCT_VERSION = "1.0.0-rc15"
KEY_ID = "development-test-key"


def _key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes(range(32)))


def _packs(root: Path) -> dict[str, Path]:
    packs: dict[str, Path] = {}
    for index, component in enumerate(REQUIRED_COMPONENTS, start=1):
        pack = root / f"CivicCast-Native-{component}-{PRODUCT_VERSION}.ccpack"
        pack.write_bytes((f"{component}\n".encode("ascii")) * index)
        packs[component] = pack
    return packs


def _urls(packs: dict[str, Path]) -> dict[str, list[str]]:
    return {
        component: [f"https://downloads.civiccast.org/native/beta/{path.name}"]
        for component, path in packs.items()
    }


def test_channel_index_is_deterministic_and_binds_every_required_pack(
    tmp_path: Path,
) -> None:
    key = _key()
    packs = _packs(tmp_path)
    first = tmp_path / "first.ccindex"
    second = tmp_path / "second.ccindex"

    first_result = build_distribution_index(
        output=first,
        kind="channel-index",
        channel="beta",
        product_version=PRODUCT_VERSION,
        compatible_core=PRODUCT_VERSION,
        packs=packs,
        urls=_urls(packs),
        signing_private_key=key,
        signing_key_id=KEY_ID,
        created_epoch=1_700_000_000,
    )
    second_result = build_distribution_index(
        output=second,
        kind="channel-index",
        channel="beta",
        product_version=PRODUCT_VERSION,
        compatible_core=PRODUCT_VERSION,
        packs=packs,
        urls=_urls(packs),
        signing_private_key=key,
        signing_key_id=KEY_ID,
        created_epoch=1_700_000_000,
    )

    assert first.read_bytes() == second.read_bytes()
    assert first_result.sha256 == second_result.sha256
    verified = verify_distribution_index(
        first,
        public_key=key.public_key(),
        expected_kind="channel-index",
        expected_channel="beta",
        expected_product_version=PRODUCT_VERSION,
        expected_compatible_core=PRODUCT_VERSION,
        expected_signing_key_id=KEY_ID,
    )
    assert tuple(pack.component for pack in verified.packs) == REQUIRED_COMPONENTS
    assert all(pack.required for pack in verified.packs)
    assert all(pack.urls[0].startswith("https://") for pack in verified.packs)


def test_station_index_has_no_network_locations_and_verifies_local_media(
    tmp_path: Path,
) -> None:
    key = _key()
    packs = _packs(tmp_path)
    station = tmp_path / "CivicCast-Native-Station-Pack.ccstation"

    build_distribution_index(
        output=station,
        kind="station-index",
        channel="beta",
        product_version=PRODUCT_VERSION,
        compatible_core=PRODUCT_VERSION,
        packs=packs,
        urls={component: [] for component in REQUIRED_COMPONENTS},
        signing_private_key=key,
        signing_key_id=KEY_ID,
        created_epoch=1_700_000_000,
    )

    result = verify_station_media(
        station,
        public_key=key.public_key(),
        expected_channel="beta",
        expected_product_version=PRODUCT_VERSION,
        expected_compatible_core=PRODUCT_VERSION,
        expected_signing_key_id=KEY_ID,
    )
    assert tuple(pack.component for pack in result.packs) == REQUIRED_COMPONENTS
    assert all(not pack.urls for pack in result.packs)


def test_index_refuses_to_build_without_any_mandatory_component(tmp_path: Path) -> None:
    packs = _packs(tmp_path)
    packs.pop("captions-large-v3")

    with pytest.raises(NativeDistributionError, match="required component set"):
        build_distribution_index(
            output=tmp_path / "incomplete.ccindex",
            kind="channel-index",
            channel="beta",
            product_version=PRODUCT_VERSION,
            compatible_core=PRODUCT_VERSION,
            packs=packs,
            urls=_urls(packs),
            signing_private_key=_key(),
            signing_key_id=KEY_ID,
            created_epoch=1_700_000_000,
        )


@pytest.mark.parametrize(
    "component",
    [
        "captions-large-v3",
        "summary-gemma4-12b",
        "summary-gemma4-e4b",
        "translation-translategemma-4b",
    ],
)
def test_no_mandatory_model_pack_can_be_marked_optional(
    tmp_path: Path,
    component: str,
) -> None:
    key = _key()
    packs = _packs(tmp_path)
    index = tmp_path / "valid.ccindex"
    build_distribution_index(
        output=index,
        kind="channel-index",
        channel="beta",
        product_version=PRODUCT_VERSION,
        compatible_core=PRODUCT_VERSION,
        packs=packs,
        urls=_urls(packs),
        signing_private_key=key,
        signing_key_id=KEY_ID,
        created_epoch=1_700_000_000,
    )
    envelope = json.loads(index.read_bytes())
    for item in envelope["manifest"]["packs"]:
        if item["component"] == component:
            item["required"] = False
    # Re-sign the malicious-but-cryptographically-valid manifest. The semantic
    # contract still has to reject it.
    from civiccast.installer.native_distribution import canonical_json

    envelope["signature"] = (
        __import__("base64")
        .b64encode(key.sign(canonical_json(envelope["manifest"])))
        .decode("ascii")
    )
    index.write_bytes(canonical_json(envelope))

    with pytest.raises(NativeDistributionError, match="must be required"):
        verify_distribution_index(index, public_key=key.public_key())


@pytest.mark.parametrize(
    "url",
    [
        "http://downloads.civiccast.org/core.ccpack",
        "file:///C:/packs/core.ccpack",
        "https://user:password@downloads.civiccast.org/core.ccpack",
        "https://downloads.civiccast.org/core.ccpack#fragment",
    ],
)
def test_online_index_rejects_non_https_or_ambiguous_pack_locations(
    tmp_path: Path,
    url: str,
) -> None:
    packs = _packs(tmp_path)
    urls = _urls(packs)
    urls["core"] = [url]

    with pytest.raises(NativeDistributionError, match="HTTPS"):
        build_distribution_index(
            output=tmp_path / "unsafe.ccindex",
            kind="channel-index",
            channel="beta",
            product_version=PRODUCT_VERSION,
            compatible_core=PRODUCT_VERSION,
            packs=packs,
            urls=urls,
            signing_private_key=_key(),
            signing_key_id=KEY_ID,
            created_epoch=1_700_000_000,
        )


def test_station_index_rejects_any_network_location(tmp_path: Path) -> None:
    packs = _packs(tmp_path)
    urls = {component: [] for component in REQUIRED_COMPONENTS}
    urls["core"] = ["https://downloads.civiccast.org/core.ccpack"]

    with pytest.raises(NativeDistributionError, match="must not contain network"):
        build_distribution_index(
            output=tmp_path / "unsafe.ccstation",
            kind="station-index",
            channel="beta",
            product_version=PRODUCT_VERSION,
            compatible_core=PRODUCT_VERSION,
            packs=packs,
            urls=urls,
            signing_private_key=_key(),
            signing_key_id=KEY_ID,
            created_epoch=1_700_000_000,
        )


def test_index_signature_and_compatibility_are_fail_closed(tmp_path: Path) -> None:
    key = _key()
    packs = _packs(tmp_path)
    index = tmp_path / "valid.ccindex"
    build_distribution_index(
        output=index,
        kind="channel-index",
        channel="beta",
        product_version=PRODUCT_VERSION,
        compatible_core=PRODUCT_VERSION,
        packs=packs,
        urls=_urls(packs),
        signing_private_key=key,
        signing_key_id=KEY_ID,
        created_epoch=1_700_000_000,
    )

    with pytest.raises(NativeDistributionError, match="signature"):
        verify_distribution_index(
            index,
            public_key=Ed25519PrivateKey.generate().public_key(),
        )
    with pytest.raises(NativeDistributionError, match="compatible core"):
        verify_distribution_index(
            index,
            public_key=key.public_key(),
            expected_compatible_core="another-core",
        )


def test_station_media_detects_missing_truncated_and_symlinked_pack(
    tmp_path: Path,
) -> None:
    key = _key()
    packs = _packs(tmp_path)
    station = tmp_path / "station.ccstation"
    build_distribution_index(
        output=station,
        kind="station-index",
        channel="beta",
        product_version=PRODUCT_VERSION,
        compatible_core=PRODUCT_VERSION,
        packs=packs,
        urls={component: [] for component in REQUIRED_COMPONENTS},
        signing_private_key=key,
        signing_key_id=KEY_ID,
        created_epoch=1_700_000_000,
    )

    core = packs["core"]
    original = core.read_bytes()
    core.unlink()
    with pytest.raises(NativeDistributionError, match="missing"):
        verify_station_media(station, public_key=key.public_key())

    core.write_bytes(original[:-1])
    with pytest.raises(NativeDistributionError, match=r"size|SHA-256"):
        verify_station_media(station, public_key=key.public_key())

    core.unlink()
    target = tmp_path / "outside.ccpack"
    target.write_bytes(original)
    try:
        core.symlink_to(target)
    except OSError:
        pytest.skip("this Windows host does not permit creating test symlinks")
    with pytest.raises(NativeDistributionError, match=r"link|reparse|regular"):
        verify_station_media(station, public_key=key.public_key())


def test_distribution_index_rejects_unsafe_pack_filename(tmp_path: Path) -> None:
    packs = _packs(tmp_path)
    source = packs["core"]
    unsafe = tmp_path / "café.ccpack"
    source.replace(unsafe)
    packs["core"] = unsafe

    with pytest.raises(NativeDistributionError, match="filename"):
        build_distribution_index(
            output=tmp_path / "unsafe.ccindex",
            kind="channel-index",
            channel="beta",
            product_version=PRODUCT_VERSION,
            compatible_core=PRODUCT_VERSION,
            packs=packs,
            urls=_urls(packs),
            signing_private_key=_key(),
            signing_key_id=KEY_ID,
            created_epoch=1_700_000_000,
        )
