# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the native application-payload policy core (`app_payload`).

Exercises the deny-by-default authorized-distribution gate, the GPL/AGPL
refusal (LGPL is acceptable), the evidence-backed per-distribution license
resolution, and the invariant that the committed authorized set stays in sync
with the pinned lock `requirements-native-app.txt`.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from civiccast.native.app_payload import (
    APP_BUILD_TOOLCHAIN_LOCK_SHA256,
    APP_DISTRIBUTION_LICENSE,
    APP_REQUIREMENTS_SHA256,
    AUTHORIZED_APP_DISTRIBUTIONS,
    CAPTION_PACK_CONTRACT,
    CIVICCAST_DISTRIBUTION,
    INTERPRETER_LICENSE,
    INTERPRETER_VERSION,
    WHISPER_MODEL_FILES,
    WHISPER_MODEL_REPO,
    WHISPER_MODEL_REVISION,
    ProhibitedLicenseError,
    UnauthorizedAppDistributionError,
    UnknownAppLicenseError,
    assert_authorized_app_distributions,
    assert_no_prohibited_declared_licenses,
    canonical_distribution_name,
    is_prohibited_license,
    resolve_app_license,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# canonical_distribution_name
# ---------------------------------------------------------------------------


def test_canonical_name_collapses_pep503_separators() -> None:
    assert canonical_distribution_name("jaraco.classes") == "jaraco-classes"
    assert canonical_distribution_name("nvidia_ml_py") == "nvidia-ml-py"
    assert canonical_distribution_name("PyYAML") == "pyyaml"
    assert canonical_distribution_name("typing_extensions") == "typing-extensions"
    # A run of mixed separators collapses to a single hyphen.
    assert canonical_distribution_name("a__.-_b") == "a-b"


# ---------------------------------------------------------------------------
# is_prohibited_license -- GPL/AGPL refused, LGPL accepted
# ---------------------------------------------------------------------------


def test_is_prohibited_license_flags_gpl_and_agpl() -> None:
    assert is_prohibited_license("GPL-3.0-only")
    assert is_prohibited_license("GPL-2.0-or-later")
    assert is_prohibited_license("GPL")
    assert is_prohibited_license("AGPL-3.0-or-later")
    assert is_prohibited_license("AGPL")
    # A prohibited branch inside an OR expression is still prohibited.
    assert is_prohibited_license("MIT OR GPL-3.0-only")
    assert is_prohibited_license("MIT OR AGPL-3.0-only")
    # Wheel metadata is free text in the wild; case and PyPI classifier wording
    # must not bypass the legal gate.
    assert is_prohibited_license("gpl-3.0-only")
    assert is_prohibited_license("GNU General Public License v3 (GPLv3)")
    assert is_prohibited_license("GNU Affero General Public License v3")


def test_is_prohibited_license_accepts_lgpl_and_permissive() -> None:
    # LGPL is explicitly acceptable (psycopg 3 is LGPL-3.0-only) -- it must NOT
    # be flagged by the GPL predicate.
    assert not is_prohibited_license("LGPL-3.0-only")
    assert not is_prohibited_license("LGPL-2.1-or-later")
    for permissive in ("MIT", "BSD-3-Clause", "Apache-2.0", "PSF-2.0", "MPL-2.0", "ISC"):
        assert not is_prohibited_license(permissive)


# ---------------------------------------------------------------------------
# resolve_app_license
# ---------------------------------------------------------------------------


def test_resolve_app_license_returns_the_confirmed_license() -> None:
    assert resolve_app_license("psycopg") == "LGPL-3.0-only"
    assert resolve_app_license("fastapi") == "MIT"
    assert resolve_app_license("av") == "BSD-3-Clause"
    assert resolve_app_license(CIVICCAST_DISTRIBUTION) == "Apache-2.0"


def test_resolve_app_license_refuses_an_unknown_distribution() -> None:
    with pytest.raises(UnknownAppLicenseError, match="totally-unknown-dist"):
        resolve_app_license("totally-unknown-dist")


# ---------------------------------------------------------------------------
# assert_authorized_app_distributions (deny-by-default)
# ---------------------------------------------------------------------------


def test_authorized_subset_passes() -> None:
    assert_authorized_app_distributions(frozenset({"fastapi", "psycopg", CIVICCAST_DISTRIBUTION}))


def test_unauthorized_distribution_fails_even_with_a_fine_looking_name() -> None:
    with pytest.raises(UnauthorizedAppDistributionError, match="civiccast-unknown-runtime"):
        assert_authorized_app_distributions(frozenset({"fastapi", "civiccast-unknown-runtime"}))


def test_a_gpl_license_in_the_confirmed_map_fails_the_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Belt-and-braces: the committed map should never contain a GPL license, but
    # a bad edit must fail the build, not ship. Simulated by injecting one.
    monkeypatch.setitem(APP_DISTRIBUTION_LICENSE, "fastapi", "GPL-3.0-only")
    with pytest.raises(ProhibitedLicenseError, match="fastapi"):
        assert_authorized_app_distributions(frozenset({"fastapi"}))


# ---------------------------------------------------------------------------
# assert_no_prohibited_declared_licenses (live-METADATA cross-check)
# ---------------------------------------------------------------------------


def test_clean_declared_licenses_pass() -> None:
    assert_no_prohibited_declared_licenses(
        {"fastapi": "MIT", "psycopg": "LGPL-3.0-only", "certifi": "MPL-2.0"}
    )


def test_a_wheel_self_reporting_gpl_fails_even_if_the_map_says_otherwise() -> None:
    # The drift case: a pinned distribution whose upstream switched to GPL in a
    # version bump would still install under the same name; reading its own
    # METADATA and refusing on a GPL self-report closes that hole.
    with pytest.raises(ProhibitedLicenseError, match="somepkg"):
        assert_no_prohibited_declared_licenses({"fastapi": "MIT", "somepkg": "GPL-2.0-or-later"})


# ---------------------------------------------------------------------------
# Invariants of the committed policy
# ---------------------------------------------------------------------------


def test_authorized_set_is_exactly_the_license_map_keys() -> None:
    assert frozenset(APP_DISTRIBUTION_LICENSE) == AUTHORIZED_APP_DISTRIBUTIONS


def test_no_confirmed_license_in_the_map_is_gpl_or_agpl() -> None:
    """The whole point of the payload: nothing GPL/AGPL ships. Every confirmed
    license must pass the prohibition predicate."""
    offenders = sorted(
        d for d, lic in APP_DISTRIBUTION_LICENSE.items() if is_prohibited_license(lic)
    )
    assert offenders == [], f"GPL/AGPL license in the confirmed map for: {offenders}"


def test_interpreter_identity_is_pinned() -> None:
    assert INTERPRETER_VERSION.startswith("3.12."), "must be a CPython 3.12 (cp312 ABI) interpreter"
    assert INTERPRETER_LICENSE == "PSF-2.0"


def test_external_caption_contract_pins_real_activation_audio() -> None:
    assert CAPTION_PACK_CONTRACT["runtime_backend"] == "faster-whisper"
    assert CAPTION_PACK_CONTRACT["runtime_version"] == "1.2.1"
    assert CAPTION_PACK_CONTRACT["model_repository"] == WHISPER_MODEL_REPO
    assert CAPTION_PACK_CONTRACT["model_revision"] == WHISPER_MODEL_REVISION
    assert CAPTION_PACK_CONTRACT["model_files"] == {
        name: {"bytes": size, "sha256": digest}
        for name, (size, digest) in WHISPER_MODEL_FILES.items()
    }
    assert CAPTION_PACK_CONTRACT["self_test_audio_file"] == "jfk.wav"
    assert CAPTION_PACK_CONTRACT["self_test_audio_bytes"] == 352_078
    assert (
        CAPTION_PACK_CONTRACT["self_test_audio_sha256"]
        == "59dfb9a4acb36fe2a2affc14bacbee2920ff435cb13cc314a08c13f66ba7860e"
    )


def test_external_caption_contract_requires_a_portable_cpu_baseline() -> None:
    """Mandatory captions cannot depend on NVIDIA CUDA being installed."""

    assert CAPTION_PACK_CONTRACT["runtime_device"] == "cpu"
    assert CAPTION_PACK_CONTRACT["runtime_compute_type"] == "int8"
    assert CAPTION_PACK_CONTRACT["hardware_acceleration_required"] is False


def test_authorized_set_matches_the_pinned_lock() -> None:
    """Drift guard: the committed authorized set (minus civiccast, which is
    built from this repo, not pinned in the lock) must equal exactly the set of
    distributions named in `requirements-native-app.txt`. A resolver change that
    adds/drops a dependency must be consciously reflected in
    APP_DISTRIBUTION_LICENSE, not silently absorbed.
    """
    lock = _REPO_ROOT / "requirements-native-app.txt"
    text = lock.read_text(encoding="utf-8")
    # Distribution lines look like `name==version \` at column 0.
    names = {
        canonical_distribution_name(m.group(1))
        for m in re.finditer(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==", text, re.MULTILINE)
    }
    assert names, "no pinned distributions parsed from the lock"
    assert AUTHORIZED_APP_DISTRIBUTIONS - {CIVICCAST_DISTRIBUTION} == names


def test_native_lock_includes_every_mandatory_feature_profile() -> None:
    """The native station payload includes captions and both CDN adapters.

    These are optional extras for a generic Python installation, but mandatory
    features of the offline-capable native beta. The generated lock records the
    selected profiles in its command header and contains each profile's direct
    runtime dependency.
    """
    lock = _REPO_ROOT / "requirements-native-app.txt"
    text = lock.read_text(encoding="utf-8")

    for extra in ("captions-runtime", "cloudflare-r2", "s3-cdn"):
        assert f"--extra {extra}" in text, f"native lock was generated without {extra}"

    names = {
        canonical_distribution_name(m.group(1))
        for m in re.finditer(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==", text, re.MULTILINE)
    }
    assert {"faster-whisper", "boto3", "botocore"} <= names


def test_native_lock_authorizes_only_the_reviewed_lgpl_pyav_wheel() -> None:
    text = (_REPO_ROOT / "requirements-native-app.txt").read_text(encoding="utf-8")
    av_block = re.search(
        r"^av==18\.0\.0 \\\n(?P<body>.*?)(?=^[A-Za-z0-9][A-Za-z0-9._-]*==)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert av_block is not None
    hashes = re.findall(r"--hash=sha256:([0-9a-f]{64})", av_block.group("body"))
    assert hashes == ["445e6a94724b6e83639c3ff4f35135cf3ae7e13a4954957d54cedf91f2e98622"]


def test_native_app_lock_matches_its_reviewed_identity() -> None:
    lock = _REPO_ROOT / "requirements-native-app.txt"
    assert hashlib.sha256(lock.read_bytes()).hexdigest() == APP_REQUIREMENTS_SHA256


def test_native_build_toolchain_lock_matches_its_reviewed_identity() -> None:
    lock = _REPO_ROOT / "native-windows-build-toolchain.lock.json"
    assert hashlib.sha256(lock.read_bytes()).hexdigest() == APP_BUILD_TOOLCHAIN_LOCK_SHA256
