# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""WP2 Core-pack builder tests: pinned-input validation, license refusal
paths, and the end-to-end provisioning-layout contract for the
``native-server-binaries`` pack (PostgreSQL 17 + TSDuck subset).

Uses tiny fixture bytes for every binary -- never a real (hundreds-of-MB)
PostgreSQL/TSDuck download -- mirroring ``tests/native/
test_caption_pack_builder.py``'s ``monkeypatch.setattr(builder, ...)``
style. No real ``postgres``/``tsp`` process is ever spawned.

NATS JetStream was removed from the product (owner decision 2026-08-20; see
ADR 0023, which supersedes ADR 0001); ``nats-server.exe`` is no longer part
of this pack.
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
from civiccast.native.provision.__main__ import resolve_provision_paths
from civiccast.native.provision.pack import (
    SERVER_BINARIES_COMPONENT,
    verify_server_binaries_pack,
)
from civiccast.native.runtime_licenses import classify_server_pack_file, is_gpl_license

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "build_native_server_pack.py"


def _load() -> object:
    assert SCRIPT_PATH.is_file(), f"native server pack builder is missing: {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("build_native_server_pack", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


builder = _load()


def _write(path: Path, body: bytes) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return len(body), hashlib.sha256(body).hexdigest()


def _make_fixture_roots(tmp_path: Path) -> tuple[Path, Path, dict[str, tuple[int, str]]]:
    """Build tiny postgres/tsduck source trees whose pinned files EXACTLY
    match a monkeypatched, minimal set of the builder's real pin tables, so
    every source-selection code path (bin, bin-dll, lib, share top files,
    share/extension, share data trees, licenses) still runs for real."""

    postgres_root = tmp_path / "postgres"
    tsduck_root = tmp_path / "tsduck"

    pins: dict[str, tuple[int, str]] = {}

    bin_pins = {}
    for name in (
        "initdb.exe",
        "postgres.exe",
        "pg_ctl.exe",
        "pg_dump.exe",
        "pg_restore.exe",
        "psql.exe",
    ):
        bin_pins[name] = _write(postgres_root / "bin" / name, f"pg-bin:{name}".encode())
    dll_pins = {}
    for name in ("libpq.dll", "libssl-3-x64.dll"):
        dll_pins[name] = _write(postgres_root / "bin" / name, f"pg-dll:{name}".encode())
    lib_pins = {
        "btree_gist.dll": _write(postgres_root / "lib" / "btree_gist.dll", b"pg-ext:btree_gist")
    }

    for name in builder.POSTGRES_SHARE_TOP_FILES:
        _write(postgres_root / "share" / name, f"share-top:{name}".encode())
    for name in builder.POSTGRES_SHARE_EXTENSION_FILES:
        _write(postgres_root / "share" / "extension" / name, f"share-ext:{name}".encode())
    for subdir in builder.POSTGRES_SHARE_DATA_DIRS:
        _write(postgres_root / "share" / subdir / "UTC", b"tzdata")
    for name in builder.POSTGRES_LICENSE_FILES:
        _write(postgres_root / name, f"license:{name}".encode())

    tsduck_pins = {}
    for name in (
        "tsp.exe",
        "tscore.dll",
        "tsduck.dll",
        "tsplugin_analyze.dll",
        "tsplugin_continuity.dll",
        "tsplugin_pcradjust.dll",
        "tsplugin_until.dll",
    ):
        tsduck_pins[name] = _write(tsduck_root / "bin" / name, f"tsduck:{name}".encode())
    # The .names/.xml data files TSDuck resolves relative to tsp.exe's own
    # directory at runtime (TSDUCK_DATA_PINS) -- a real fixture file per
    # pinned name, same fabrication style as the DLL/exe fixtures above, so
    # the source-selection path that stages them is genuinely exercised.
    tsduck_data_pins = {}
    for name in builder.TSDUCK_DATA_PINS:
        tsduck_data_pins[name] = _write(tsduck_root / "bin" / name, f"tsduck-data:{name}".encode())
    for name in builder.TSDUCK_LICENSE_FILES:
        _write(tsduck_root / name, f"license:{name}".encode())

    pins.update({f"bin/{k}": v for k, v in {**bin_pins, **dll_pins}.items()})
    pins.update({f"lib/{k}": v for k, v in lib_pins.items()})
    pins.update({f"tsduck/{k}": v for k, v in {**tsduck_pins, **tsduck_data_pins}.items()})

    return (
        postgres_root,
        tsduck_root,
        {
            "bin": bin_pins,
            "bin_dll": dll_pins,
            "lib": lib_pins,
            "tsduck": tsduck_pins,
            "tsduck_data": tsduck_data_pins,
        },
    )


def _patch_minimal_pins(monkeypatch: pytest.MonkeyPatch, pins: dict) -> None:
    monkeypatch.setattr(builder, "POSTGRES_BIN_PINS", pins["bin"])
    monkeypatch.setattr(builder, "POSTGRES_BIN_DLL_PINS", pins["bin_dll"])
    monkeypatch.setattr(builder, "POSTGRES_LIB_PINS", pins["lib"])
    monkeypatch.setattr(builder, "TSDUCK_BIN_PINS", pins["tsduck"])
    monkeypatch.setattr(builder, "TSDUCK_DATA_PINS", pins["tsduck_data"])


def _dev_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes(range(32)))


def test_component_identity_matches_the_provisioning_trust_wire() -> None:
    """The builder must target the EXACT component identity
    ``civiccast.native.provision.pack`` verifies against -- a drift here
    would silently produce a pack the provisioning engine refuses."""

    assert builder.SERVER_BINARIES_COMPONENT == SERVER_BINARIES_COMPONENT
    assert SERVER_BINARIES_COMPONENT == "native-server-binaries"


def test_end_to_end_build_verifies_through_the_real_provisioning_trust_wire(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    postgres_root, tsduck_root, pins = _make_fixture_roots(tmp_path)
    _patch_minimal_pins(monkeypatch, pins)

    key = _dev_key()
    output = tmp_path / "native-server-binaries.ccpack"
    report = builder.build_server_pack(
        output=output,
        postgres_root=postgres_root,
        tsduck_root=tsduck_root,
        signing_private_key=key,
        signing_key_id="development-test-key",
        product_version="0.0.0-test",
        source_sha="a" * 40,
    )
    assert report["component"] == "native-server-binaries"
    assert report["source_sha"] == "a" * 40

    # Verified through native_packs directly...
    verify_native_pack(output, public_key=key.public_key())
    # ...AND through the SAME trust wire civiccast.native.provision.seams
    # actually calls at install time (verify_server_binaries_pack), proving
    # the two agree.
    verified = verify_server_binaries_pack(
        output,
        public_key=key.public_key(),
        expected_product_version="0.0.0-test",
        expected_compatible_core="0.0.0-test",
        expected_signing_key_id="development-test-key",
    )
    assert verified.component == "native-server-binaries"
    assert verified.metadata["postgres_version"] == builder.POSTGRES_VERSION
    assert verified.metadata["tsduck_version"] == builder.TSDUCK_VERSION
    assert verified.metadata["source_sha"] == "a" * 40


def test_tsduck_data_files_are_staged_beside_the_pinned_binaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Root cause of the Gate A TS-capture failure (2026-09-03 22:55Z,
    "configuration file 'dtv' not found" / "file not found:
    tsduck.hfbands.xml"): the pack shipped tsp.exe and its 4 plugin DLLs but
    none of the .names/.xml data files those plugins need at runtime.
    ``_tsduck_sources`` must stage every ``TSDUCK_DATA_PINS`` entry at
    ``tsduck/bin/<name>`` -- the SAME directory as tsp.exe itself, since
    TSDuck resolves these files relative to its own executable path on
    Windows, not a separate ``share``/``etc`` tree."""

    assert builder.TSDUCK_DATA_PINS, "TSDUCK_DATA_PINS must not be empty"
    # These are TSDuck's OWN bundled data, not extra plugin binaries: no new
    # plugin DLL should ever land in this table (guards against future
    # accidental scope creep past what the Gate A fix required).
    for name in builder.TSDUCK_DATA_PINS:
        assert not name.lower().endswith((".dll", ".exe")), (
            f"TSDUCK_DATA_PINS carries a binary ({name!r}) -- binaries belong in "
            "TSDUCK_BIN_PINS, not the data-file table"
        )

    _postgres_root, tsduck_root, pins = _make_fixture_roots(tmp_path)
    _patch_minimal_pins(monkeypatch, pins)

    sources = builder._tsduck_sources(tsduck_root)

    for name in pins["tsduck_data"]:
        key = f"tsduck/bin/{name}"
        assert key in sources, f"{key} missing from _tsduck_sources() output"
        expected_bytes, expected_sha256 = pins["tsduck_data"][name]
        observed = sources[key].read_bytes()
        assert len(observed) == expected_bytes
        assert hashlib.sha256(observed).hexdigest() == expected_sha256

    # Every real (non-fixture) TSDUCK_DATA_PINS name this task's audit found
    # in the actual upstream archive is present -- pins the exact file list,
    # not just "some data files exist".
    expected_real_names = {
        "tscore.ip.names",
        "tscore.keytable.model.xml",
        "tscore.monitor.model.xml",
        "tscore.monitor.xml",
        "tscore.time.model.xml",
        "tscore.time.xml",
        "tsduck.channels.model.xml",
        "tsduck.dektec.names",
        "tsduck.dtv.names",
        "tsduck.etuner.model.xml",
        "tsduck.hfbands.model.xml",
        "tsduck.hfbands.xml",
        "tsduck.hides.names",
        "tsduck.lnbs.model.xml",
        "tsduck.lnbs.xml",
        "tsduck.oui.names",
        "tsduck.tables.model.xml",
    }
    assert set(builder.TSDUCK_DATA_PINS) == expected_real_names


def test_provisioning_layout_contract_initdb_path_exists_once_extracted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact contract ``civiccast.native.provision.__main__.
    resolve_provision_paths`` pins: once the pack is laid out at
    ``<install_root>\\packs\\native-server-binaries\\`` (the ``payload/``
    prefix from the ZIP preserved verbatim), ``initdb.exe`` must exist at
    ``payload\\bin\\initdb.exe`` -- the exact default ``initdb_path``."""

    postgres_root, tsduck_root, pins = _make_fixture_roots(tmp_path)
    _patch_minimal_pins(monkeypatch, pins)

    key = _dev_key()
    output = tmp_path / "native-server-binaries.ccpack"
    builder.build_server_pack(
        output=output,
        postgres_root=postgres_root,
        tsduck_root=tsduck_root,
        signing_private_key=key,
        signing_key_id="development-test-key",
        product_version="0.0.0-test",
        source_sha="a" * 40,
    )

    extract_root = tmp_path / "install" / "packs" / "native-server-binaries"
    with zipfile.ZipFile(output) as archive:
        archive.extractall(extract_root)

    paths = resolve_provision_paths(install_root=str(tmp_path / "install"))
    # payload/ prefix is the ZIP's own internal convention
    # (native_packs.PACK_PAYLOAD_PREFIX); resolve_provision_paths' default
    # initdb_path is <install_root>\packs\native-server-binaries\payload\bin\initdb.exe.
    initdb_on_disk = extract_root / "payload" / "bin" / "initdb.exe"
    assert initdb_on_disk.is_file()
    assert str(initdb_on_disk) == paths.initdb_path or paths.initdb_path.endswith(
        r"packs\native-server-binaries\payload\bin\initdb.exe"
    )
    expected_bytes, expected_sha256 = pins["bin"]["initdb.exe"]
    observed = initdb_on_disk.read_bytes()
    assert len(observed) == expected_bytes
    assert hashlib.sha256(observed).hexdigest() == expected_sha256


def test_refuses_a_missing_pinned_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    postgres_root, tsduck_root, pins = _make_fixture_roots(tmp_path)
    _patch_minimal_pins(monkeypatch, pins)

    (postgres_root / "bin" / "initdb.exe").unlink()

    with pytest.raises(builder.ServerPackBuildError, match=r"initdb\.exe"):
        builder.build_server_pack(
            output=tmp_path / "out.ccpack",
            postgres_root=postgres_root,
            tsduck_root=tsduck_root,
            signing_private_key=_dev_key(),
            signing_key_id="development-test-key",
            product_version="0.0.0-test",
            source_sha="a" * 40,
        )


def test_refuses_a_hash_mismatched_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    postgres_root, tsduck_root, pins = _make_fixture_roots(tmp_path)
    _patch_minimal_pins(monkeypatch, pins)

    original_bytes, _ = pins["bin"]["postgres.exe"]
    tampered = (b"X" * original_bytes)[:original_bytes]
    (postgres_root / "bin" / "postgres.exe").write_bytes(tampered)

    with pytest.raises(builder.ServerPackBuildError, match="SHA-256"):
        builder.build_server_pack(
            output=tmp_path / "out.ccpack",
            postgres_root=postgres_root,
            tsduck_root=tsduck_root,
            signing_private_key=_dev_key(),
            signing_key_id="development-test-key",
            product_version="0.0.0-test",
            source_sha="a" * 40,
        )


def test_refuses_a_gpl_flagged_license_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    postgres_root, tsduck_root, pins = _make_fixture_roots(tmp_path)
    _patch_minimal_pins(monkeypatch, pins)

    # Patch the classifier's own lookup table (imported by reference into the
    # builder module) so ONE fixture file resolves to a GPL license -- proves
    # the zero-GPL/AGPL-tolerance gate actually inspects every packed path,
    # not just a hard-coded few.
    import civiccast.native.runtime_licenses as runtime_licenses

    patched_table = dict(runtime_licenses.SERVER_PACK_BASENAME_LICENSE)
    patched_table["postgres.exe"] = "GPL-3.0-only"
    monkeypatch.setattr(runtime_licenses, "SERVER_PACK_BASENAME_LICENSE", patched_table)
    monkeypatch.setattr(
        builder, "classify_server_pack_file", runtime_licenses.classify_server_pack_file
    )

    with pytest.raises(builder.ServerPackBuildError, match="GPL"):
        builder.build_server_pack(
            output=tmp_path / "out.ccpack",
            postgres_root=postgres_root,
            tsduck_root=tsduck_root,
            signing_private_key=_dev_key(),
            signing_key_id="development-test-key",
            product_version="0.0.0-test",
            source_sha="a" * 40,
        )


def test_refuses_an_unconfirmed_license_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    postgres_root, tsduck_root, pins = _make_fixture_roots(tmp_path)
    _patch_minimal_pins(monkeypatch, pins)

    monkeypatch.setattr(builder, "classify_server_pack_file", lambda path: None)

    with pytest.raises(builder.ServerPackBuildError, match="unconfirmed license"):
        builder.build_server_pack(
            output=tmp_path / "out.ccpack",
            postgres_root=postgres_root,
            tsduck_root=tsduck_root,
            signing_private_key=_dev_key(),
            signing_key_id="development-test-key",
            product_version="0.0.0-test",
            source_sha="a" * 40,
        )


def test_acquire_refuses_a_lock_version_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the reviewed lock's pinned ``postgres``/``tsduck`` version
    ever drifts from what this builder's hand-verified pins were computed
    against, acquisition must refuse rather than silently fetch and pack an
    unreviewed version."""

    def _fake_load_lock(_path: Path) -> dict:
        return {
            "artifacts": {
                "postgres": {"version": "99.0-drifted"},
                "tsduck": {"version": builder.TSDUCK_VERSION},
            }
        }

    monkeypatch.setattr(builder, "load_lock", _fake_load_lock)
    with pytest.raises(builder.ServerPackBuildError, match="drifted"):
        builder.acquire_server_pack_sources(tmp_path / "cache")


# ---------------------------------------------------------------------------
# Idempotent self-hosted cache: a persistent --cache must never trust a
# stale/incomplete extraction just because the directory exists.
# ---------------------------------------------------------------------------
#
# Candidate run 32845198987 (self-hosted) failed identically in BOTH
# attempts with "pinned PostgreSQL initdb.exe is missing" from
# civiccast-server-pack-cache\extracted\postgres\bin\initdb.exe. A
# self-hosted runner's --cache persists across runs (a hosted runner is
# always fresh); a previous run's extraction there had been interrupted,
# leaving a directory that EXISTED but was missing files --
# acquire_server_pack_sources()'s bare `destination.exists()` check trusted
# it anyway and never re-extracted.


def _fake_lock(_path: Path) -> dict:
    return {
        "artifacts": {
            "postgres": {"version": builder.POSTGRES_VERSION, "strip_prefix": "pgsql"},
            "tsduck": {"version": builder.TSDUCK_VERSION, "strip_prefix": "tsduck"},
        }
    }


def test_acquire_reuses_a_complete_pre_existing_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pre-existing extraction that genuinely has every pinned file must
    be reused as-is -- no wasted re-extraction on a valid self-hosted
    cache hit."""
    _postgres_root, _tsduck_root, pins = _make_fixture_roots(tmp_path / "fixture")
    _patch_minimal_pins(monkeypatch, pins)
    monkeypatch.setattr(builder, "load_lock", _fake_lock)
    monkeypatch.setattr(
        builder, "fetch_locked_artifact", lambda *a, **kw: tmp_path / "unused-archive.zip"
    )
    extract_calls: list[str] = []
    monkeypatch.setattr(
        builder,
        "safe_extract_zip",
        lambda *a, **kw: extract_calls.append("called"),
    )

    cache = tmp_path / "cache"
    # Pre-populate a COMPLETE extraction directly at the destination
    # acquire_server_pack_sources() would use -- the fixture roots already
    # built above ARE a complete, pin-matching tree. Copied (not
    # symlinked): Windows symlinks need elevated privileges the test
    # sandbox may not have.
    complete_postgres, complete_tsduck, _complete_pins = _make_fixture_roots(tmp_path / "cache2")
    (cache / "extracted").mkdir(parents=True)
    shutil.copytree(complete_postgres, cache / "extracted" / "postgres")
    shutil.copytree(complete_tsduck, cache / "extracted" / "tsduck")

    result = builder.acquire_server_pack_sources(cache)

    assert extract_calls == [], "a complete pre-existing extraction must not be re-extracted"
    assert result["postgres"] == cache / "extracted" / "postgres"
    assert result["tsduck"] == cache / "extracted" / "tsduck"


def test_acquire_re_extracts_an_incomplete_pre_existing_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact candidate-run-32845198987 shape: a previous run's
    interrupted extraction left `cache/extracted/postgres` EXISTING but
    missing initdb.exe. acquire_server_pack_sources() must detect the
    incompleteness, clear it, and re-extract -- not silently hand back a
    broken tree that only fails much later, deep inside the live bootstrap
    proof."""
    # A REAL valid tree (same helper the round-trip tests use) stands in
    # for "what a genuine, successful extraction would produce" -- no
    # hand-duplicated byte-pattern guessing that could silently drift from
    # `_make_fixture_roots`'s own convention.
    good_postgres, good_tsduck, pins = _make_fixture_roots(tmp_path / "fixture")
    _patch_minimal_pins(monkeypatch, pins)
    monkeypatch.setattr(builder, "load_lock", _fake_lock)
    monkeypatch.setattr(
        builder, "fetch_locked_artifact", lambda *a, **kw: tmp_path / "unused-archive.zip"
    )

    good_source_by_name = {"postgres": good_postgres, "tsduck": good_tsduck}
    extract_calls: list[Path] = []

    def _tracking_extract(_archive: Path, destination: Path, **_kw: object) -> None:
        extract_calls.append(destination)
        name = destination.name
        shutil.copytree(good_source_by_name[name], destination, dirs_exist_ok=True)

    monkeypatch.setattr(builder, "safe_extract_zip", _tracking_extract)

    cache = tmp_path / "cache"
    stale_postgres = cache / "extracted" / "postgres"
    stale_postgres.mkdir(parents=True)
    # Every pinned bin file EXCEPT initdb.exe -- exactly the observed
    # shape: a directory that exists and looks populated, but is missing
    # the one file the live bootstrap proof needed.
    for filename in pins["bin"]:
        if filename == "initdb.exe":
            continue
        (stale_postgres / "bin" / filename).parent.mkdir(parents=True, exist_ok=True)
        (stale_postgres / "bin" / filename).write_bytes(b"stale")
    assert not (stale_postgres / "bin" / "initdb.exe").exists()

    result = builder.acquire_server_pack_sources(cache)

    assert stale_postgres in extract_calls, "the incomplete tree must be re-extracted"
    assert (stale_postgres / "bin" / "initdb.exe").is_file(), (
        "re-extraction must actually land the previously-missing file"
    )
    # The re-extracted tree now genuinely validates.
    builder._postgres_sources(result["postgres"])


def test_acquire_extracts_fresh_when_nothing_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No pre-existing destination at all: the ordinary, unaffected
    fresh-extraction path, unchanged by this fix."""
    _postgres_root, _tsduck_root, pins = _make_fixture_roots(tmp_path / "fixture")
    _patch_minimal_pins(monkeypatch, pins)
    monkeypatch.setattr(builder, "load_lock", _fake_lock)
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
    result = builder.acquire_server_pack_sources(cache)

    assert extract_calls == [
        cache / "extracted" / "postgres",
        cache / "extracted" / "tsduck",
    ]
    assert result["postgres"] == cache / "extracted" / "postgres"


def test_extracted_tree_is_complete_dispatches_per_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Direct unit coverage of the completeness check itself: a real valid
    tree passes, a missing-file tree fails, for both artifact kinds."""
    postgres_root, tsduck_root, pins = _make_fixture_roots(tmp_path)
    _patch_minimal_pins(monkeypatch, pins)

    assert builder._extracted_tree_is_complete("postgres", postgres_root) is True
    assert builder._extracted_tree_is_complete("tsduck", tsduck_root) is True

    (postgres_root / "bin" / "initdb.exe").unlink()
    assert builder._extracted_tree_is_complete("postgres", postgres_root) is False

    (tsduck_root / "bin" / "tsp.exe").unlink()
    assert builder._extracted_tree_is_complete("tsduck", tsduck_root) is False


def test_development_signing_key_requires_explicit_nonrelease_switch() -> None:
    with pytest.raises(builder.ServerPackBuildError, match="allow-development-key"):
        builder.require_allowed_signing_key(
            "development-civiccast-native", allow_development_key=False
        )
    builder.require_allowed_signing_key("development-civiccast-native", allow_development_key=True)
    builder.require_allowed_signing_key("civiccast-production-2026", allow_development_key=False)


@pytest.mark.parametrize("source_sha", [None, "A" * 40, "a" * 39, "g" * 40])
def test_refuses_missing_or_malformed_source_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source_sha: object
) -> None:
    postgres_root, tsduck_root, pins = _make_fixture_roots(tmp_path)
    _patch_minimal_pins(monkeypatch, pins)

    with pytest.raises(builder.ServerPackBuildError, match="source SHA"):
        builder.build_server_pack(
            output=tmp_path / "out.ccpack",
            postgres_root=postgres_root,
            tsduck_root=tsduck_root,
            signing_private_key=_dev_key(),
            signing_key_id="development-test-key",
            product_version="0.0.0-test",
            source_sha=source_sha,
        )


# ---------------------------------------------------------------------------
# License-registry completeness: every REAL (non-fixture) path this builder
# selects from the actual reviewed pin tables must resolve to a confirmed,
# non-GPL SPDX license via civiccast.native.runtime_licenses.
# ---------------------------------------------------------------------------


def test_every_real_pinned_path_has_a_confirmed_non_gpl_license() -> None:
    paths: list[str] = []
    paths += [f"bin/{name}" for name in builder.POSTGRES_BIN_PINS]
    paths += [f"bin/{name}" for name in builder.POSTGRES_BIN_DLL_PINS]
    paths += [f"lib/{name}" for name in builder.POSTGRES_LIB_PINS]
    paths += [f"share/{name}" for name in builder.POSTGRES_SHARE_TOP_FILES]
    paths += [f"share/extension/{name}" for name in builder.POSTGRES_SHARE_EXTENSION_FILES]
    paths += [f"licenses/postgresql/{name}" for name in builder.POSTGRES_LICENSE_FILES]
    paths += [f"tsduck/bin/{name}" for name in builder.TSDUCK_BIN_PINS]
    paths += [f"tsduck/bin/{name}" for name in builder.TSDUCK_DATA_PINS]
    paths += [f"licenses/tsduck/{name}" for name in builder.TSDUCK_LICENSE_FILES]
    for subdir in builder.POSTGRES_SHARE_DATA_DIRS:
        paths.append(f"share/{subdir}/UTC")  # representative path under the data tree

    unresolved = [path for path in paths if classify_server_pack_file(path) is None]
    assert unresolved == []

    gpl_flagged = [
        path
        for path in paths
        if (license_id := classify_server_pack_file(path)) is not None
        and is_gpl_license(license_id)
    ]
    assert gpl_flagged == []


def test_classify_server_pack_file_returns_none_for_an_unconfirmed_path() -> None:
    assert classify_server_pack_file("bin/some-unreviewed-tool.exe") is None


class TestCoreRuntimeModulePins:
    """Sandbox matrix row 1, run 2 (2026-07-30): the live fresh install died
    at initdb -- FATAL: could not access file "$libdir/utf8_and_win" --
    because the lib/ selection carried ONLY the opted-in btree_gist
    extension. PostgreSQL's lib/ also holds CORE runtime modules the
    bootstrap itself loads: the encoding-conversion family, plpgsql
    (installed by initdb's bootstrap), and dict_snowball (loaded by the
    snowball_create.sql the pack already ships). These pins are a
    regression guard so no future trim reintroduces the fault."""

    REQUIRED_CONVERSIONS = (
        "cyrillic_and_mic.dll",
        "euc2004_sjis2004.dll",
        "euc_cn_and_mic.dll",
        "euc_jp_and_sjis.dll",
        "euc_kr_and_mic.dll",
        "euc_tw_and_big5.dll",
        "latin2_and_win1250.dll",
        "latin_and_mic.dll",
        "utf8_and_big5.dll",
        "utf8_and_cyrillic.dll",
        "utf8_and_euc2004.dll",
        "utf8_and_euc_cn.dll",
        "utf8_and_euc_jp.dll",
        "utf8_and_euc_kr.dll",
        "utf8_and_euc_tw.dll",
        "utf8_and_gb18030.dll",
        "utf8_and_gbk.dll",
        "utf8_and_iso8859.dll",
        "utf8_and_iso8859_1.dll",
        "utf8_and_johab.dll",
        "utf8_and_sjis.dll",
        "utf8_and_sjis2004.dll",
        "utf8_and_uhc.dll",
        "utf8_and_win.dll",
    )

    def test_every_encoding_conversion_module_is_pinned(self) -> None:
        missing = [n for n in self.REQUIRED_CONVERSIONS if n not in builder.POSTGRES_LIB_PINS]
        assert not missing, (
            f"encoding-conversion modules missing from POSTGRES_LIB_PINS: {missing} "
            "(initdb bootstrap loads these; proven live in Sandbox run 2)"
        )

    def test_plpgsql_and_snowball_core_modules_are_pinned(self) -> None:
        for name in ("plpgsql.dll", "dict_snowball.dll"):
            assert name in builder.POSTGRES_LIB_PINS, (
                f"{name} missing from POSTGRES_LIB_PINS -- initdb bootstrap "
                "(plpgsql) / snowball_create.sql (dict_snowball) load it"
            )


class TestBootstrapProof:
    """Unit coverage for ``prove_postgres_bootstrap`` with an injected
    runner (hard rule: no real postgres execution in the unit suite -- the
    live execution happens on every real CLI pack build)."""

    @staticmethod
    def _ok(argv, **kwargs):
        import subprocess as sp

        return sp.CompletedProcess(argv, 0, stdout="", stderr="")

    def test_runs_initdb_start_probe_stop_in_order_with_the_provisioning_argv_shape(
        self, tmp_path, monkeypatch
    ) -> None:
        postgres_root, _tsduck, pins = _make_fixture_roots(tmp_path)
        _patch_minimal_pins(monkeypatch, pins)
        calls = []

        def recorder(argv, **kwargs):
            calls.append(list(argv))
            return self._ok(argv)

        builder.prove_postgres_bootstrap(postgres_root, run=recorder)

        assert len(calls) == 4
        initdb, start, probe, stop = calls
        assert initdb[0].endswith("initdb.exe")
        # The argv shape is the provisioning engine's own (seams.initdb_argv),
        # not a lookalike -- the proof must exercise the exact live call.
        assert "--auth-host=scram-sha-256" in initdb
        assert "--no-instructions" in initdb
        assert "--pwfile" in initdb
        assert start[0].endswith("pg_ctl.exe") and "start" in start
        assert any("listen_addresses=127.0.0.1" in part for part in start)
        assert probe[0].endswith("psql.exe")
        assert any("btree_gist" in part for part in probe)
        assert any("to_tsvector" in part for part in probe)
        assert stop[0].endswith("pg_ctl.exe") and "stop" in stop

    def test_scratch_access_grant_runs_after_staging_and_before_initdb(
        self, tmp_path, monkeypatch
    ) -> None:
        # Candidate runs 31143881561/31154873108: initdb's restricted-token
        # re-exec could not read the scratch tree on the hosted runner and
        # died 0xC0000135 with no output. The proof must therefore grant the
        # current user's SID on the fully staged tree before the first spawn.
        postgres_root, _tsduck, pins = _make_fixture_roots(tmp_path)
        _patch_minimal_pins(monkeypatch, pins)
        events = []

        def recording_grant(root):
            staged_bin = root / "pg" / "bin"
            events.append(("grant", staged_bin.exists()))

        def recorder(argv, **kwargs):
            events.append(("run", next(iter(argv))))
            return self._ok(argv)

        monkeypatch.setattr(builder, "_grant_scratch_tree_to_current_user", recording_grant)
        builder.prove_postgres_bootstrap(postgres_root, run=recorder)

        assert events[0] == ("grant", True), (
            f"the access grant must run first, on an already-staged tree (events: {events[:2]})"
        )
        assert events[1][0] == "run" and events[1][1].endswith("initdb.exe")

    def test_probe_failure_raises_and_still_stops_the_server(self, tmp_path, monkeypatch) -> None:
        postgres_root, _tsduck, pins = _make_fixture_roots(tmp_path)
        _patch_minimal_pins(monkeypatch, pins)
        calls = []

        def failing_probe(argv, **kwargs):
            import subprocess as sp

            calls.append(list(argv))
            if argv[0].endswith("psql.exe"):
                return sp.CompletedProcess(argv, 1, stdout="", stderr="FATAL: boom")
            return self._ok(argv)

        with pytest.raises(builder.ServerPackBuildError, match="bootstrap proof failed at psql"):
            builder.prove_postgres_bootstrap(postgres_root, run=failing_probe)
        assert calls[-1][0].endswith("pg_ctl.exe") and "stop" in calls[-1], (
            "a failed probe must still stop the started server"
        )

    def test_initdb_failure_names_the_selection_as_the_suspect(self, tmp_path, monkeypatch) -> None:
        postgres_root, _tsduck, pins = _make_fixture_roots(tmp_path)
        _patch_minimal_pins(monkeypatch, pins)

        def failing_initdb(argv, **kwargs):
            import subprocess as sp

            code = 1 if argv[0].endswith("initdb.exe") else 0
            return sp.CompletedProcess(argv, code, stdout="", stderr="could not access file")

        with pytest.raises(builder.ServerPackBuildError, match="POSTGRES_LIB_PINS"):
            builder.prove_postgres_bootstrap(postgres_root, run=failing_initdb)
