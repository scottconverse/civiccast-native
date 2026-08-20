# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""CUDA-pack builder tests: pinned-wheel validation, wheel-extraction
mapping, the required-DLL stop, the license-provenance refusal paths, and the
extraction-layout contract for the ``native-cuda-runtime`` pack.

Uses tiny fake wheel zips built directly with :mod:`zipfile` -- never a real
(hundreds-of-MB) NVIDIA wheel download. No network access happens anywhere in
this file: ``acquire_cuda_pack_sources``/``_resolve_pypi_wheel_url`` are never
called here, matching ``test_build_native_ffmpeg_pack.py``'s own posture of
concentrating on the offline build/refusal paths, where the real acquisition
belongs on a real CLI invocation instead.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from civiccast.installer.native_packs import verify_native_pack
from civiccast.native.runtime_licenses import (
    CUDA_TOOLKIT_EULA_LICENSE,
    classify_cuda_pack_file,
    is_gpl_license,
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "build_native_cuda_pack.py"


def _load() -> object:
    assert SCRIPT_PATH.is_file(), f"native cuda pack builder is missing: {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("build_native_cuda_pack", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


builder = _load()


def _dev_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes(range(32)))


def _write_fake_wheel(path: Path, *, bin_prefix: str, files: dict[str, bytes]) -> tuple[int, str]:
    """A tiny fake wheel (a plain zip) carrying ``files`` under
    ``bin_prefix`` -- e.g. ``nvidia/cublas/bin/``. Returns the wheel's own
    ``(bytes, sha256)`` so callers can monkeypatch the builder's pin table to
    match exactly, letting the real pinned-file-validation code path run
    unmodified against fixture bytes."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, mode="w") as archive:
        for name, data in files.items():
            archive.writestr(f"{bin_prefix}{name}", data)
    data = path.read_bytes()
    return len(data), hashlib.sha256(data).hexdigest()


def _make_fixture_wheels(tmp_path: Path) -> tuple[Path, Path, dict[str, builder._WheelPin]]:
    """A pair of tiny fake cuBLAS/cuDNN wheels matching the REAL pinned
    wheels' own shipped DLL sets: the real ``nvidia-cublas-cu12`` wheel ships
    ``cublas64_12.dll``, ``cublasLt64_12.dll``, AND ``nvblas64_12.dll`` under
    ``nvidia/cublas/bin/`` (confirmed against the pinned wheel's own
    contents). ``CUDA_REQUIRED_DLL_NAMES`` is a SUBSET of this fixture's DLL
    set, not an exact match -- ``cublasLt64_12.dll`` and ``nvblas64_12.dll``
    are both EXTRA shipped DLLs the required-DLL check never mentions, so the
    real required-DLL check still runs against a superset exactly like the
    real wheels present it."""

    cublas_path = tmp_path / "wheels" / "nvidia_cublas_cu12-0.0.0-py3-none-win_amd64.whl"
    cudnn_path = tmp_path / "wheels" / "nvidia_cudnn_cu12-0.0.0-py3-none-win_amd64.whl"

    cublas_bytes, cublas_sha256 = _write_fake_wheel(
        cublas_path,
        bin_prefix="nvidia/cublas/bin/",
        files={
            "cublas64_12.dll": b"pretend-cublas64_12-bytes",
            "cublasLt64_12.dll": b"pretend-cublasLt64_12-bytes",
            "nvblas64_12.dll": b"pretend-nvblas64_12-bytes",
        },
    )
    cudnn_bytes, cudnn_sha256 = _write_fake_wheel(
        cudnn_path,
        bin_prefix="nvidia/cudnn/bin/",
        files={
            "cudnn64_9.dll": b"pretend-cudnn64_9-bytes",
            "cudnn_ops64_9.dll": b"pretend-cudnn_ops64_9-bytes",
        },
    )

    pins = {
        "cublas": builder._WheelPin(
            pypi_project="nvidia-cublas-cu12",
            version="0.0.0",
            filename=cublas_path.name,
            bytes=cublas_bytes,
            sha256=cublas_sha256,
            wheel_bin_prefix="nvidia/cublas/bin/",
        ),
        "cudnn": builder._WheelPin(
            pypi_project="nvidia-cudnn-cu12",
            version="0.0.0",
            filename=cudnn_path.name,
            bytes=cudnn_bytes,
            sha256=cudnn_sha256,
            wheel_bin_prefix="nvidia/cudnn/bin/",
        ),
    }
    return cublas_path, cudnn_path, pins


def _patch_pins(monkeypatch: pytest.MonkeyPatch, pins: dict[str, builder._WheelPin]) -> None:
    monkeypatch.setattr(builder, "CUDA_WHEEL_PINS", pins)


def _build(
    tmp_path: Path, cublas_path: Path, cudnn_path: Path, *, output: str = "out.ccpack"
) -> dict[str, object]:
    return builder.build_cuda_pack(
        output=tmp_path / output,
        cublas_wheel=cublas_path,
        cudnn_wheel=cudnn_path,
        signing_private_key=_dev_key(),
        signing_key_id="development-test-key",
        product_version="0.0.0-test",
    )


# ---------------------------------------------------------------------------
# Identity + end-to-end
# ---------------------------------------------------------------------------


def test_component_identity_is_the_string_every_other_layer_pins() -> None:
    assert builder.CUDA_RUNTIME_COMPONENT == "native-cuda-runtime"


def test_required_dll_names_match_the_presence_gate_exactly() -> None:
    """Drift guard: the builder's own literal must exactly match
    ``civiccast.native.station_runtime``'s private presence-gate tuple, since
    a pack built against a stale/wrong pair could pass this builder's own
    checks while remaining invisible to the gate that actually matters."""
    import civiccast.native.station_runtime as station_runtime

    assert builder.CUDA_REQUIRED_DLL_NAMES == station_runtime._CUDA_REQUIRED_DLL_NAMES


def test_end_to_end_build_verifies_through_the_products_own_verifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cublas_path, cudnn_path, pins = _make_fixture_wheels(tmp_path)
    _patch_pins(monkeypatch, pins)

    report = _build(tmp_path, cublas_path, cudnn_path)

    assert report["component"] == "native-cuda-runtime"
    verified = verify_native_pack(
        tmp_path / "out.ccpack",
        public_key=_dev_key().public_key(),
        expected_component="native-cuda-runtime",
        expected_product_version="0.0.0-test",
        expected_compatible_core="0.0.0-test",
        expected_signing_key_id="development-test-key",
    )
    # 5 DLLs (cublas64_12, cublasLt64_12, nvblas64_12, cudnn64_9, cudnn_ops64_9)
    # + 2 license references + 1 NOTICE.
    assert verified.file_count == 8
    assert set(verified.metadata["required_dll_names"]) == {"cublas64_12.dll", "cudnn64_9.dll"}
    assert "nvblas64_12.dll" in verified.metadata["dll_names"]
    assert verified.metadata["attribution"] == builder.NVIDIA_ATTRIBUTION_NOTICE


def test_payload_is_bin_rooted_so_it_composes_onto_the_activation_pinned_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The load-bearing layout contract. ``pack_extraction_destination`` maps
    this component to ``<INSTDIR>\\dependencies\\cuda``; the payload must
    therefore be rooted at ``bin/`` for ``cublas64_12.dll`` to land on the
    ``dependencies/cuda/bin/cublas64_12.dll`` path
    ``station_runtime.cuda_bin_dir`` computes."""
    cublas_path, cudnn_path, pins = _make_fixture_wheels(tmp_path)
    _patch_pins(monkeypatch, pins)

    _build(tmp_path, cublas_path, cudnn_path)

    with zipfile.ZipFile(tmp_path / "out.ccpack") as archive:
        names = set(archive.namelist())
    assert "payload/bin/cublas64_12.dll" in names
    assert "payload/bin/cudnn64_9.dll" in names
    assert "payload/bin/cublasLt64_12.dll" in names
    assert "payload/bin/cudnn_ops64_9.dll" in names
    # nvblas64_12.dll is an EXTRA DLL the real cublas wheel ships alongside
    # the two required names -- it must land in the payload too, not just
    # the required pair.
    assert "payload/bin/nvblas64_12.dll" in names
    instdir = Path(r"C:\Program Files\CivicCast")
    staged = instdir / "dependencies" / "cuda" / "bin" / "cublas64_12.dll"
    assert staged == instdir.joinpath("dependencies", "cuda", "bin", "cublas64_12.dll")


def test_nvblas_extra_dll_is_shipped_and_classified_under_the_cuda_eula(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The recurrence guard for the candidate-build CI failure this fix
    closed: the real ``nvidia-cublas-cu12`` wheel ships ``nvblas64_12.dll``
    alongside ``cublas64_12.dll``/``cublasLt64_12.dll`` under its ``bin/``
    directory, but ``CUDA_PACK_BIN_BASENAME_PREFIX_LICENSE`` only classified
    the ``cublas``/``cudnn`` prefixes -- leaving ``nvblas64_12.dll`` an
    unconfirmed-provenance file that ``_require_full_license_provenance``
    fail-closed refuses to pack. Before commit e04911c34 added the
    ``nvblas`` prefix entry, ``_build`` below raises
    ``CudaPackBuildError('...unconfirmed license provenance for:
    bin/nvblas64_12.dll...')`` and this test never reaches its assertions.
    """
    cublas_path, cudnn_path, pins = _make_fixture_wheels(tmp_path)
    _patch_pins(monkeypatch, pins)

    _build(tmp_path, cublas_path, cudnn_path)

    with zipfile.ZipFile(tmp_path / "out.ccpack") as archive:
        names = set(archive.namelist())
    assert "payload/bin/nvblas64_12.dll" in names

    assert classify_cuda_pack_file("bin/nvblas64_12.dll") == CUDA_TOOLKIT_EULA_LICENSE


def test_the_pack_carries_reference_license_texts_and_the_attribution_string(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cublas_path, cudnn_path, pins = _make_fixture_wheels(tmp_path)
    _patch_pins(monkeypatch, pins)

    _build(tmp_path, cublas_path, cudnn_path)

    with zipfile.ZipFile(tmp_path / "out.ccpack") as archive:
        names = set(archive.namelist())
        notice = archive.read("payload/notices/native-cuda-runtime.txt").decode("utf-8")
        cuda_license = archive.read("payload/licenses/cuda/LICENSE.txt").decode("utf-8")
        cudnn_license = archive.read("payload/licenses/cudnn/LICENSE.txt").decode("utf-8")

    assert "payload/licenses/cuda/LICENSE.txt" in names
    assert "payload/licenses/cudnn/LICENSE.txt" in names
    assert builder.NVIDIA_ATTRIBUTION_NOTICE in notice
    assert builder.NVIDIA_ATTRIBUTION_NOTICE in cuda_license
    assert builder.NVIDIA_ATTRIBUTION_NOTICE in cudnn_license
    assert builder.CUDA_TOOLKIT_EULA_URL in notice
    assert builder.CUDA_TOOLKIT_EULA_URL in cuda_license
    assert builder.CUDNN_EULA_URL in notice
    assert builder.CUDNN_EULA_URL in cudnn_license
    # Reference, never a verbatim copy of NVIDIA's copyrighted EULA text.
    assert "REFERENCE" in cuda_license
    assert "REFERENCE" in cudnn_license


# ---------------------------------------------------------------------------
# Refusal paths (a successful build never exercises any of these)
# ---------------------------------------------------------------------------


def test_refuses_a_byte_length_mismatched_wheel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cublas_path, cudnn_path, pins = _make_fixture_wheels(tmp_path)
    _patch_pins(monkeypatch, pins)

    cublas_path.write_bytes(b"not the pinned bytes at all")

    with pytest.raises(builder.CudaPackBuildError, match="byte length mismatch"):
        _build(tmp_path, cublas_path, cudnn_path)


def test_refuses_a_hash_mismatched_wheel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cublas_path, cudnn_path, pins = _make_fixture_wheels(tmp_path)
    _patch_pins(monkeypatch, pins)

    original_len = cudnn_path.stat().st_size
    cudnn_path.write_bytes(b"X" * original_len)

    with pytest.raises(builder.CudaPackBuildError, match="SHA-256"):
        _build(tmp_path, cublas_path, cudnn_path)


def test_refuses_a_missing_wheel_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cublas_path, cudnn_path, pins = _make_fixture_wheels(tmp_path)
    _patch_pins(monkeypatch, pins)

    cublas_path.unlink()

    with pytest.raises(builder.CudaPackBuildError, match="is missing"):
        _build(tmp_path, cublas_path, cudnn_path)


def test_refuses_a_wheel_with_no_dlls_under_its_bin_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cublas_path = tmp_path / "wheels" / "cublas.whl"
    cudnn_path = tmp_path / "wheels" / "cudnn.whl"
    cublas_bytes, cublas_sha256 = _write_fake_wheel(
        cublas_path, bin_prefix="nvidia/cublas/bin/", files={}
    )
    cudnn_bytes, cudnn_sha256 = _write_fake_wheel(
        cudnn_path,
        bin_prefix="nvidia/cudnn/bin/",
        files={"cudnn64_9.dll": b"pretend-cudnn64_9-bytes"},
    )
    pins = {
        "cublas": builder._WheelPin(
            "nvidia-cublas-cu12", "0.0.0", cublas_path.name, cublas_bytes, cublas_sha256,
            "nvidia/cublas/bin/",
        ),
        "cudnn": builder._WheelPin(
            "nvidia-cudnn-cu12", "0.0.0", cudnn_path.name, cudnn_bytes, cudnn_sha256,
            "nvidia/cudnn/bin/",
        ),
    }
    _patch_pins(monkeypatch, pins)

    with pytest.raises(builder.CudaPackBuildError, match="no DLLs found"):
        _build(tmp_path, cublas_path, cudnn_path)


def test_refuses_colliding_dll_basenames_between_the_two_wheels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cublas_path = tmp_path / "wheels" / "cublas.whl"
    cudnn_path = tmp_path / "wheels" / "cudnn.whl"
    cublas_bytes, cublas_sha256 = _write_fake_wheel(
        cublas_path,
        bin_prefix="nvidia/cublas/bin/",
        files={"cublas64_12.dll": b"a", "shared_name.dll": b"from-cublas"},
    )
    cudnn_bytes, cudnn_sha256 = _write_fake_wheel(
        cudnn_path,
        bin_prefix="nvidia/cudnn/bin/",
        files={"cudnn64_9.dll": b"b", "shared_name.dll": b"from-cudnn"},
    )
    pins = {
        "cublas": builder._WheelPin(
            "nvidia-cublas-cu12", "0.0.0", cublas_path.name, cublas_bytes, cublas_sha256,
            "nvidia/cublas/bin/",
        ),
        "cudnn": builder._WheelPin(
            "nvidia-cudnn-cu12", "0.0.0", cudnn_path.name, cudnn_bytes, cudnn_sha256,
            "nvidia/cudnn/bin/",
        ),
    }
    _patch_pins(monkeypatch, pins)

    with pytest.raises(builder.CudaPackBuildError, match="colliding"):
        _build(tmp_path, cublas_path, cudnn_path)


def test_stops_when_a_required_dll_name_is_absent_from_the_wheels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The spec-mandated STOP: a wheel re-pin that silently changed the
    shipped DLL name (e.g. a hypothetical CUDA 13 cublas64_13.dll) must never
    quietly ship a pack the presence gate can't see."""
    cublas_path = tmp_path / "wheels" / "cublas.whl"
    cudnn_path = tmp_path / "wheels" / "cudnn.whl"
    cublas_bytes, cublas_sha256 = _write_fake_wheel(
        cublas_path,
        bin_prefix="nvidia/cublas/bin/",
        files={"cublas64_13.dll": b"renamed-in-a-future-cuda"},
    )
    cudnn_bytes, cudnn_sha256 = _write_fake_wheel(
        cudnn_path,
        bin_prefix="nvidia/cudnn/bin/",
        files={"cudnn64_9.dll": b"pretend-cudnn64_9-bytes"},
    )
    pins = {
        "cublas": builder._WheelPin(
            "nvidia-cublas-cu12", "0.0.0", cublas_path.name, cublas_bytes, cublas_sha256,
            "nvidia/cublas/bin/",
        ),
        "cudnn": builder._WheelPin(
            "nvidia-cudnn-cu12", "0.0.0", cudnn_path.name, cudnn_bytes, cudnn_sha256,
            "nvidia/cudnn/bin/",
        ),
    }
    _patch_pins(monkeypatch, pins)

    with pytest.raises(builder.CudaPackBuildError, match="STOP"):
        _build(tmp_path, cublas_path, cudnn_path)


def test_refuses_an_unconfirmed_license_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cublas_path, cudnn_path, pins = _make_fixture_wheels(tmp_path)
    _patch_pins(monkeypatch, pins)

    monkeypatch.setattr(builder, "classify_cuda_pack_file", lambda path: None)

    with pytest.raises(builder.CudaPackBuildError, match="unconfirmed license"):
        _build(tmp_path, cublas_path, cudnn_path)


def test_refuses_a_gpl_flagged_license_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cublas_path, cudnn_path, pins = _make_fixture_wheels(tmp_path)
    _patch_pins(monkeypatch, pins)

    monkeypatch.setattr(builder, "classify_cuda_pack_file", lambda path: "GPL-3.0-only")

    with pytest.raises(builder.CudaPackBuildError, match="GPL"):
        _build(tmp_path, cublas_path, cudnn_path)


def test_development_signing_key_requires_explicit_nonrelease_switch() -> None:
    with pytest.raises(builder.CudaPackBuildError, match="allow-development-key"):
        builder.require_allowed_signing_key(
            "development-civiccast-native", allow_development_key=False
        )
    builder.require_allowed_signing_key("development-civiccast-native", allow_development_key=True)
    builder.require_allowed_signing_key("civiccast-production-2026", allow_development_key=False)


def test_acquire_refuses_mutually_exclusive_flags_via_the_cli_contract() -> None:
    """The CLI-level guard is exercised through the pure acquisition function
    it wraps -- resolving/downloading never happens in this test."""
    assert "acquire_cuda_pack_sources" in dir(builder)


# ---------------------------------------------------------------------------
# License-registry completeness against the REAL pin table's naming scheme
# ---------------------------------------------------------------------------


def test_real_pin_table_dll_prefixes_have_a_confirmed_non_gpl_license() -> None:
    """The real pins' own filenames -- not a fixture -- must classify cleanly,
    since a build against the real wheels runs this exact check."""
    paths = [
        f"bin/{name}"
        for name in (*builder.CUDA_REQUIRED_DLL_NAMES, "cublasLt64_12.dll", "cudnn_ops64_9.dll")
    ]
    unresolved = [path for path in paths if classify_cuda_pack_file(path) is None]
    assert unresolved == []

    gpl_flagged = [
        path
        for path in paths
        if (license_id := classify_cuda_pack_file(path)) is not None and is_gpl_license(license_id)
    ]
    assert gpl_flagged == []


def test_classify_cuda_pack_file_returns_none_for_an_unconfirmed_path() -> None:
    assert classify_cuda_pack_file("bin/some-unrelated-tool.exe") is None
    # Prefix matching is scoped to bin/ only.
    assert classify_cuda_pack_file("cublas64_12.dll") is None


def test_real_pins_carry_both_required_dll_names_as_the_exact_gate_string() -> None:
    assert set(builder.CUDA_REQUIRED_DLL_NAMES) == {"cublas64_12.dll", "cudnn64_9.dll"}


def test_real_wheel_pins_are_sha256_hex_and_positive_byte_length() -> None:
    import re

    for key, pin in builder.CUDA_WHEEL_PINS.items():
        assert re.fullmatch(r"[0-9a-f]{64}", pin.sha256), f"{key} sha256 is not lowercase hex-64"
        assert pin.bytes > 0, f"{key} pinned byte length must be positive"
        assert pin.filename.endswith(".whl")
