# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""FFmpeg-pack builder tests: pinned-input validation, the license/GPL refusal
paths, the closure-drift guard, and the extraction-layout contract for the
``native-ffmpeg-runtime`` pack.

Uses tiny fixture bytes for every binary -- never a real (hundreds-of-MB)
FFmpeg download -- mirroring ``tests/native/test_build_native_server_pack.py``'s
``monkeypatch.setattr(builder, ...)`` style. No real ``ffmpeg``/``ffprobe``
process is ever spawned here: the live ``-version``/``-L``/encode/probe proof
runs on every real CLI pack build instead (``prove_ffmpeg_runtime``), which is
where a real execution belongs.

These tests deliberately concentrate on the REFUSAL paths, because those are
exactly what a successful build never exercises: a happy-path pack build can
never demonstrate that the GPL gate, the unconfirmed-provenance gate, the lock
drift assertions, or the closure-drift guard actually fire.
"""

from __future__ import annotations

import hashlib
import importlib.util
import shutil
import sys
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from civiccast.installer.native_packs import verify_native_pack
from civiccast.native.runtime_licenses import classify_ffmpeg_pack_file, is_gpl_license

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "build_native_ffmpeg_pack.py"


def _load() -> object:
    assert SCRIPT_PATH.is_file(), f"native ffmpeg pack builder is missing: {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("build_native_ffmpeg_pack", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


builder = _load()


def _dev_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes(range(32)))


def _make_fixture_root(tmp_path: Path) -> tuple[Path, dict[str, tuple[int, str]]]:
    """A tiny FFmpeg source tree whose files EXACTLY match a monkeypatched,
    minimal version of the builder's real pin table, so the real
    source-selection code path (bin pins + the license file) still runs."""

    root = tmp_path / "ffmpeg-src"
    (root / "bin").mkdir(parents=True)
    pins: dict[str, tuple[int, str]] = {}
    for name in ("ffmpeg.exe", "ffprobe.exe", "avcodec-62.dll", "avutil-60.dll"):
        body = f"pretend-{name}-bytes".encode("ascii")
        (root / "bin" / name).write_bytes(body)
        pins[name] = (len(body), hashlib.sha256(body).hexdigest())
    (root / "LICENSE.txt").write_bytes(b"GNU LESSER GENERAL PUBLIC LICENSE Version 3\n")
    return root, pins


def _patch_minimal_pins(monkeypatch: pytest.MonkeyPatch, pins: dict[str, tuple[int, str]]) -> None:
    monkeypatch.setattr(builder, "FFMPEG_BIN_PINS", pins)


def _build(tmp_path: Path, root: Path, *, output: str = "out.ccpack") -> dict[str, object]:
    return builder.build_ffmpeg_pack(
        output=tmp_path / output,
        ffmpeg_root=root,
        signing_private_key=_dev_key(),
        signing_key_id="development-test-key",
        product_version="0.0.0-test",
    )


# ---------------------------------------------------------------------------
# Identity + end-to-end
# ---------------------------------------------------------------------------


def test_component_identity_is_the_string_every_other_layer_pins() -> None:
    assert builder.FFMPEG_RUNTIME_COMPONENT == "native-ffmpeg-runtime"


def test_end_to_end_build_verifies_through_the_products_own_verifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, pins = _make_fixture_root(tmp_path)
    _patch_minimal_pins(monkeypatch, pins)

    report = _build(tmp_path, root)

    assert report["component"] == "native-ffmpeg-runtime"
    verified = verify_native_pack(
        tmp_path / "out.ccpack",
        public_key=_dev_key().public_key(),
        expected_component="native-ffmpeg-runtime",
        expected_product_version="0.0.0-test",
        expected_compatible_core="0.0.0-test",
        expected_signing_key_id="development-test-key",
    )
    assert verified.file_count == len(pins) + 2  # + LICENSE.txt + the generated NOTICE


def test_payload_is_bin_rooted_so_it_composes_onto_the_activation_pinned_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The load-bearing layout contract. ``pack_extraction_destination`` maps
    this component to ``<INSTDIR>\\dependencies\\ffmpeg``; the payload must
    therefore be rooted at ``bin/`` for ``ffmpeg.exe`` to land on the
    ``dependencies/ffmpeg/bin/ffmpeg.exe`` path ``native_activation.rs``
    pins. A payload rooted anywhere else extracts cleanly and then fails
    activation."""
    root, pins = _make_fixture_root(tmp_path)
    _patch_minimal_pins(monkeypatch, pins)

    _build(tmp_path, root)

    with zipfile.ZipFile(tmp_path / "out.ccpack") as archive:
        names = set(archive.namelist())
    assert "payload/bin/ffmpeg.exe" in names
    assert "payload/bin/ffprobe.exe" in names
    # Simulating the extraction bridge: payload/ is stripped, the remainder is
    # joined onto <INSTDIR>\dependencies\ffmpeg.
    instdir = Path(r"C:\Program Files\CivicCast")
    staged = instdir / "dependencies" / "ffmpeg" / "bin" / "ffmpeg.exe"
    assert staged == instdir.joinpath("dependencies", "ffmpeg", "bin", "ffmpeg.exe")


def test_the_pack_carries_its_license_text_and_a_source_offer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LGPL obligation, checked on the artifact rather than asserted in a
    comment: the verbatim upstream license text must ship, and the generated
    NOTICE must carry a corresponding-source offer naming a real source
    location -- not merely name the license."""
    root, pins = _make_fixture_root(tmp_path)
    _patch_minimal_pins(monkeypatch, pins)

    _build(tmp_path, root)

    with zipfile.ZipFile(tmp_path / "out.ccpack") as archive:
        names = set(archive.namelist())
        notice = archive.read("payload/notices/ffmpeg-runtime.txt").decode("utf-8")
        license_text = archive.read("payload/licenses/ffmpeg/LICENSE.txt").decode("utf-8")

    assert "payload/licenses/ffmpeg/LICENSE.txt" in names
    assert "LESSER GENERAL PUBLIC LICENSE" in license_text.upper()
    assert "WRITTEN OFFER OF CORRESPONDING SOURCE" in notice
    assert builder.FFMPEG_SOURCE_URL in notice
    assert builder.FFMPEG_BUILD_RECIPE_URL in notice
    assert builder.FFMPEG_SPDX_LICENSE in notice
    # The honest scope disclosure -- statically linked third-party libraries
    # are NOT claimed as per-dependency provenance this pack does not have.
    assert "SCOPE OF THIS NOTICE" in notice


# ---------------------------------------------------------------------------
# Refusal paths (a successful build never exercises any of these)
# ---------------------------------------------------------------------------


def test_refuses_a_missing_pinned_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, pins = _make_fixture_root(tmp_path)
    _patch_minimal_pins(monkeypatch, pins)

    (root / "bin" / "ffmpeg.exe").unlink()

    with pytest.raises(builder.FfmpegPackBuildError, match=r"ffmpeg\.exe"):
        _build(tmp_path, root)


def test_refuses_a_hash_mismatched_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, pins = _make_fixture_root(tmp_path)
    _patch_minimal_pins(monkeypatch, pins)

    original_bytes, _ = pins["avcodec-62.dll"]
    (root / "bin" / "avcodec-62.dll").write_bytes(b"X" * original_bytes)

    with pytest.raises(builder.FfmpegPackBuildError, match="SHA-256"):
        _build(tmp_path, root)


def test_refuses_a_missing_upstream_license_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing license text must refuse the build exactly as hard as a
    missing binary -- shipping LGPL binaries with no license text is a
    compliance failure, not a cosmetic one."""
    root, pins = _make_fixture_root(tmp_path)
    _patch_minimal_pins(monkeypatch, pins)

    (root / "LICENSE.txt").unlink()

    with pytest.raises(builder.FfmpegPackBuildError, match="license file"):
        _build(tmp_path, root)


def test_refuses_a_gpl_flagged_license_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The owner-settled constraint is the LGPL FFmpeg build. FFmpeg ships in
    BOTH a GPL and an LGPL flavour under near-identical archive names, so this
    gate is the thing standing between a mis-retargeted lock and a GPL binary
    in the product."""
    root, pins = _make_fixture_root(tmp_path)
    _patch_minimal_pins(monkeypatch, pins)

    import civiccast.native.runtime_licenses as runtime_licenses

    patched = dict(runtime_licenses.FFMPEG_PACK_BASENAME_LICENSE)
    patched["ffmpeg.exe"] = "GPL-3.0-only"
    monkeypatch.setattr(runtime_licenses, "FFMPEG_PACK_BASENAME_LICENSE", patched)
    monkeypatch.setattr(
        builder, "classify_ffmpeg_pack_file", runtime_licenses.classify_ffmpeg_pack_file
    )

    with pytest.raises(builder.FfmpegPackBuildError, match="GPL"):
        _build(tmp_path, root)


def test_refuses_an_unconfirmed_license_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, pins = _make_fixture_root(tmp_path)
    _patch_minimal_pins(monkeypatch, pins)

    monkeypatch.setattr(builder, "classify_ffmpeg_pack_file", lambda path: None)

    with pytest.raises(builder.FfmpegPackBuildError, match="unconfirmed license"):
        _build(tmp_path, root)


def test_acquire_refuses_a_lock_version_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        builder,
        "load_lock",
        lambda _path: {"artifacts": {"ffmpeg": {"version": "99.0-drifted"}}},
    )
    with pytest.raises(builder.FfmpegPackBuildError, match="drifted"):
        builder.acquire_ffmpeg_pack_sources(tmp_path / "cache")


def test_acquire_refuses_a_lock_license_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retargeting the lock at the GPL FFmpeg archive must refuse at acquire
    time, before a single byte is fetched -- not later, at review time."""
    monkeypatch.setattr(
        builder,
        "load_lock",
        lambda _path: {
            "artifacts": {
                "ffmpeg": {
                    "version": builder.FFMPEG_VERSION,
                    "spdx_license": "GPL-3.0-or-later",
                }
            }
        },
    )
    with pytest.raises(builder.FfmpegPackBuildError, match="license drifted"):
        builder.acquire_ffmpeg_pack_sources(tmp_path / "cache")


def test_acquire_refuses_an_expected_executables_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        builder,
        "load_lock",
        lambda _path: {
            "artifacts": {
                "ffmpeg": {
                    "version": builder.FFMPEG_VERSION,
                    "spdx_license": builder.FFMPEG_SPDX_LICENSE,
                    "expected_executables": ["bin/ffmpeg.exe"],
                }
            }
        },
    )
    with pytest.raises(builder.FfmpegPackBuildError, match="expected_executables"):
        builder.acquire_ffmpeg_pack_sources(tmp_path / "cache")


# ---------------------------------------------------------------------------
# Idempotent self-hosted cache: a persistent --cache must never trust a
# stale/incomplete extraction just because the directory exists.
# ---------------------------------------------------------------------------
#
# Candidate run 32858543561 (self-hosted) failed with "FFmpeg closure seed
# bin/ffmpeg.exe is missing" from civiccast-ffmpeg-pack-cache\extracted\
# ffmpeg\bin\ffmpeg.exe -- the same idempotent-scratch bug class already
# fixed for civiccast-server-pack-cache (#41), one script over. A
# self-hosted runner's --cache persists across runs (a hosted runner is
# always fresh); a previous run's extraction there had been interrupted,
# leaving a directory that EXISTED but was missing files --
# acquire_ffmpeg_pack_sources()'s bare `destination.exists()` check trusted
# it anyway and never re-extracted.


def _fake_ffmpeg_lock(_path: Path) -> dict:
    return {
        "artifacts": {
            "ffmpeg": {
                "version": builder.FFMPEG_VERSION,
                "spdx_license": builder.FFMPEG_SPDX_LICENSE,
                "expected_executables": sorted(
                    f"bin/{name}" for name in builder.FFMPEG_EXECUTABLES
                ),
                "strip_prefix": "ffmpeg",
            }
        }
    }


def test_acquire_reuses_a_complete_pre_existing_ffmpeg_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pre-existing extraction that genuinely has every pinned file must
    be reused as-is -- no wasted re-extraction on a valid self-hosted
    cache hit."""
    good_root, pins = _make_fixture_root(tmp_path / "fixture")
    _patch_minimal_pins(monkeypatch, pins)
    monkeypatch.setattr(builder, "load_lock", _fake_ffmpeg_lock)
    monkeypatch.setattr(
        builder, "fetch_locked_artifact", lambda *a, **kw: tmp_path / "unused-archive.zip"
    )
    extract_calls: list[Path] = []
    monkeypatch.setattr(
        builder,
        "safe_extract_zip",
        lambda *a, **kw: extract_calls.append("called"),
    )

    cache = tmp_path / "cache"
    destination = cache / "extracted" / "ffmpeg"
    destination.parent.mkdir(parents=True)
    shutil.copytree(good_root, destination)

    result = builder.acquire_ffmpeg_pack_sources(cache)

    assert extract_calls == [], "a complete pre-existing extraction must not be re-extracted"
    assert result == destination


def test_acquire_re_extracts_an_incomplete_pre_existing_ffmpeg_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact candidate-run-32858543561 shape: a previous run's
    interrupted extraction left `cache/extracted/ffmpeg` EXISTING but
    missing bin/ffmpeg.exe. acquire_ffmpeg_pack_sources() must detect the
    incompleteness, clear it, and re-extract."""
    good_root, pins = _make_fixture_root(tmp_path / "fixture")
    _patch_minimal_pins(monkeypatch, pins)
    monkeypatch.setattr(builder, "load_lock", _fake_ffmpeg_lock)
    monkeypatch.setattr(
        builder, "fetch_locked_artifact", lambda *a, **kw: tmp_path / "unused-archive.zip"
    )

    extract_calls: list[Path] = []

    def _tracking_extract(_archive: Path, destination: Path, **_kw: object) -> None:
        extract_calls.append(destination)
        shutil.copytree(good_root, destination, dirs_exist_ok=True)

    monkeypatch.setattr(builder, "safe_extract_zip", _tracking_extract)

    cache = tmp_path / "cache"
    stale = cache / "extracted" / "ffmpeg"
    (stale / "bin").mkdir(parents=True)
    for filename in pins:
        if filename == "ffmpeg.exe":
            continue
        (stale / "bin" / filename).write_bytes(b"stale")
    assert not (stale / "bin" / "ffmpeg.exe").exists()

    result = builder.acquire_ffmpeg_pack_sources(cache)

    assert stale in extract_calls, "the incomplete tree must be re-extracted"
    assert (stale / "bin" / "ffmpeg.exe").is_file(), (
        "re-extraction must actually land the previously-missing file"
    )
    # The re-extracted tree now genuinely validates.
    builder._ffmpeg_sources(result)


def test_acquire_extracts_ffmpeg_fresh_when_nothing_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No pre-existing destination at all: the ordinary, unaffected
    fresh-extraction path, unchanged by this fix."""
    _good_root, pins = _make_fixture_root(tmp_path / "fixture")
    _patch_minimal_pins(monkeypatch, pins)
    monkeypatch.setattr(builder, "load_lock", _fake_ffmpeg_lock)
    monkeypatch.setattr(
        builder, "fetch_locked_artifact", lambda *a, **kw: tmp_path / "unused-archive.zip"
    )
    extract_calls: list[Path] = []
    monkeypatch.setattr(
        builder,
        "safe_extract_zip",
        lambda archive, destination, **kw: extract_calls.append(destination),
    )

    cache = tmp_path / "cache"
    result = builder.acquire_ffmpeg_pack_sources(cache)

    assert extract_calls == [cache / "extracted" / "ffmpeg"]
    assert result == cache / "extracted" / "ffmpeg"


def test_extracted_ffmpeg_is_complete_detects_a_missing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Direct unit coverage of the completeness check itself."""
    root, pins = _make_fixture_root(tmp_path)
    _patch_minimal_pins(monkeypatch, pins)

    assert builder._extracted_ffmpeg_is_complete(root) is True

    (root / "bin" / "ffmpeg.exe").unlink()
    assert builder._extracted_ffmpeg_is_complete(root) is False


def test_closure_drift_guard_reports_both_directions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pin table is DERIVED from an import walk, so it can go stale when
    upstream rebuilds. The guard must name what the walk reached but the pins
    do not carry (the dangerous direction -- a DLL that would be missing at
    run time) as well as the reverse."""
    root, pins = _make_fixture_root(tmp_path)
    _patch_minimal_pins(monkeypatch, pins)
    monkeypatch.setattr(
        builder,
        "resolve_ffmpeg_pe_closure",
        lambda _root: ("bin/ffmpeg.exe", "bin/a-newly-required.dll"),
    )

    with pytest.raises(builder.FfmpegPackBuildError) as excinfo:
        builder.verify_pinned_closure_matches_a_real_import_walk(root)

    message = str(excinfo.value)
    assert "a-newly-required.dll" in message
    assert "Re-derive FFMPEG_BIN_PINS" in message


def test_development_signing_key_requires_explicit_nonrelease_switch() -> None:
    with pytest.raises(builder.FfmpegPackBuildError, match="allow-development-key"):
        builder.require_allowed_signing_key(
            "development-civiccast-native", allow_development_key=False
        )
    builder.require_allowed_signing_key("development-civiccast-native", allow_development_key=True)
    builder.require_allowed_signing_key("civiccast-production-2026", allow_development_key=False)


# ---------------------------------------------------------------------------
# License-registry completeness against the REAL pin table
# ---------------------------------------------------------------------------


def test_every_real_pinned_path_has_a_confirmed_non_gpl_license() -> None:
    paths = [f"bin/{name}" for name in builder.FFMPEG_BIN_PINS]
    paths += [f"licenses/ffmpeg/{name}" for name in builder.FFMPEG_LICENSE_FILES]

    unresolved = [path for path in paths if classify_ffmpeg_pack_file(path) is None]
    assert unresolved == []

    gpl_flagged = [
        path
        for path in paths
        if (license_id := classify_ffmpeg_pack_file(path)) is not None
        and is_gpl_license(license_id)
    ]
    assert gpl_flagged == []


def test_classify_ffmpeg_pack_file_returns_none_for_an_unconfirmed_path() -> None:
    assert classify_ffmpeg_pack_file("bin/some-unreviewed-tool.exe") is None


def test_the_real_pin_table_carries_both_executables_and_no_ffplay() -> None:
    """``ffplay.exe`` is the single largest file the minimization drops
    (~17.9 MB): an interactive SDL player no code in this repository invokes,
    and not a dependency of either shipped tool. A future re-derivation that
    quietly pulls it back in should be a deliberate, visible change."""
    assert set(builder.FFMPEG_EXECUTABLES) == {"ffmpeg.exe", "ffprobe.exe"}
    for name in builder.FFMPEG_EXECUTABLES:
        assert name in builder.FFMPEG_BIN_PINS
    assert "ffplay.exe" not in builder.FFMPEG_BIN_PINS


def test_the_proof_encoder_is_not_the_gpl_only_one() -> None:
    """libx264 is GPL and therefore cannot exist in this artifact. The live
    proof must not be written against it, or every real build would fail for
    the wrong reason and the real gap (product call sites that DO request
    libx264) would be masked."""
    assert builder.PROOF_VIDEO_ENCODER == "libopenh264"
    assert builder.PROOF_VIDEO_ENCODER != "libx264"
