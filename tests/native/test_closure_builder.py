# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Red-first tests for the native runtime closure builder (I/O shell).

`scripts/build_native_runtime_closure.py` is loaded by file path (it lives
outside the `civiccast` package, matching the house pattern in
`tests/test_collect_source_state.py`). Covers `spec-packaging-closure` D1
(refuse an unauthenticated lockfile), D2 (provenance index, the PE-import
walk backed by real `pefile` parsing), and the plugin-locator contract that
`build_native_runtime_closure.build_origins` depends on (never probe
GStreamer for live factories -- locate the named plugin file in the staged
tree instead, per `civiccast.native.runtime_closure`'s module doc).

Only the pure/cheap helpers are exercised here -- not a full ~250MB staged
build. The real end-to-end run is a separate, manual proof
(`uv run python scripts/build_native_runtime_closure.py --out <dir>`).
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "build_native_runtime_closure",
    Path(__file__).resolve().parents[2] / "scripts" / "build_native_runtime_closure.py",
)
assert _SPEC is not None
assert _SPEC.loader is not None
build_native_runtime_closure = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = build_native_runtime_closure
_SPEC.loader.exec_module(build_native_runtime_closure)


# --------------------------------------------------------------------------
# build_distribution_index (RECORD parser)
# --------------------------------------------------------------------------


def test_record_parser_maps_a_file_to_its_owning_distribution(tmp_path: Path) -> None:
    dist_info = tmp_path / "gstreamer_libs-1.28.5.dist-info"
    dist_info.mkdir()
    (dist_info / "RECORD").write_text(
        "bin/glib-2.0-0.dll,sha256=abc123,45678\n"
        "gstreamer_libs-1.28.5.dist-info/METADATA,sha256=def456,10\n",
        encoding="utf-8",
    )

    index = build_native_runtime_closure.build_distribution_index(tmp_path)

    assert index["bin/glib-2.0-0.dll"] == "gstreamer_libs"
    assert index["gstreamer_libs-1.28.5.dist-info/METADATA"] == "gstreamer_libs"


def test_record_parser_handles_a_dist_info_with_no_record_without_crashing(
    tmp_path: Path,
) -> None:
    with_record = tmp_path / "gstreamer_libs-1.28.5.dist-info"
    with_record.mkdir()
    (with_record / "RECORD").write_text("bin/glib-2.0-0.dll,sha256=abc,1\n", encoding="utf-8")

    without_record = tmp_path / "gstreamer_plugins-1.28.5.dist-info"
    without_record.mkdir()
    # Deliberately no RECORD file inside without_record.

    index = build_native_runtime_closure.build_distribution_index(tmp_path)

    assert index == {"bin/glib-2.0-0.dll": "gstreamer_libs"}


def test_cli_consumers_are_required_pe_closure_seeds_from_the_pinned_distribution(
    tmp_path: Path,
) -> None:
    """The installed-runtime validator may require these only if D2 ships them."""
    for name in ("gst-discoverer-1.0.exe", "gst-inspect-1.0.exe"):
        path = tmp_path / "gstreamer_cli" / "bin" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    file_index = {
        f"gstreamer_cli/bin/{name}": "gstreamer_cli"
        for name in ("gst-discoverer-1.0.exe", "gst-inspect-1.0.exe")
    }

    assert build_native_runtime_closure.cli_consumer_seeds(tmp_path, file_index) == (
        "gstreamer_cli/bin/gst-discoverer-1.0.exe",
        "gstreamer_cli/bin/gst-inspect-1.0.exe",
    )


def test_cli_consumer_seed_refuses_an_unpinned_distribution(tmp_path: Path) -> None:
    path = tmp_path / "gstreamer_cli" / "bin" / "gst-discoverer-1.0.exe"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fixture")

    with pytest.raises(RuntimeError, match="gstreamer_cli"):
        build_native_runtime_closure.cli_consumer_seeds(
            tmp_path, {"gstreamer_cli/bin/gst-discoverer-1.0.exe": "untrusted"}
        )


# --------------------------------------------------------------------------
# System DLL allowlist
# --------------------------------------------------------------------------


def test_system_allowlist_matches_api_ms_win_prefix_case_insensitively() -> None:
    assert build_native_runtime_closure.is_system_dll("api-ms-win-crt-heap-l1-1-0.dll") is True
    assert build_native_runtime_closure.is_system_dll("API-MS-WIN-CRT-HEAP-L1-1-0.DLL") is True


def test_system_allowlist_matches_kernel32_case_insensitively() -> None:
    assert build_native_runtime_closure.is_system_dll("KERNEL32.DLL") is True
    assert build_native_runtime_closure.is_system_dll("kernel32.dll") is True


def test_api_set_prefix_does_not_wave_through_a_nonexistent_api_set() -> None:
    """CC-WS5-PKG-003 (Codex r1, Critical).

    The api-ms-win-*/ext-ms-win-* exemption was an unbounded prefix match, so
    ANY name starting with those characters was treated as OS-provided and
    silently omitted from the closure. The auditor demonstrated it with
    `api-ms-win-civiccast-fake-l99-99-99.dll`.

    That is a fail-OPEN in the one mechanism that decides what does not need to
    ship: a tampered or simply mistaken PE could name a plausible-looking
    API set and have its real dependency dropped without a word.
    """
    assert (
        build_native_runtime_closure.is_system_dll("api-ms-win-civiccast-fake-l99-99-99.dll")
        is False
    )
    assert (
        build_native_runtime_closure.is_system_dll("ext-ms-win-totally-made-up-l1-1-0.dll") is False
    )


def test_api_set_prefix_still_accepts_a_real_api_set() -> None:
    """The fix must not over-block: genuine API sets the pinned closure
    imports are in the reviewed inventory and legitimately never shipped."""
    assert build_native_runtime_closure.is_system_dll("api-ms-win-crt-heap-l1-1-0.dll") is True


@pytest.mark.windows_only
@pytest.mark.skipif(os.name != "nt", reason="requires the live Windows API-set resolver")
def test_api_set_acceptance_does_not_depend_on_the_build_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CC-WS5-PKG-003 (Codex r2, Critical) -- the host-dependence half.

    `api-ms-win-core-file-l1-1-0.dll` is a REAL API set that resolves on this
    Windows 11 box. The pinned closure does not import it, so it is not in the
    reviewed inventory, and it must therefore NOT be treated as OS-provided.

    That is the whole point: acceptance is decided by the checked-in inventory,
    not by what the build machine happens to have. The build host here is
    Windows 11 build 26200 while the supported floor is Windows 10 1809 -- a
    newer host must never be able to silently exempt a contract the target
    lacks.
    """
    assert (
        build_native_runtime_closure.api_set_resolves_as_a_real_contract(
            "api-ms-win-core-file-l1-1-0.dll"
        )
        is True
    ), "precondition: this really is a live API set on the build host"

    assert build_native_runtime_closure.is_system_dll("api-ms-win-core-file-l1-1-0.dll") is False


@pytest.mark.windows_only
@pytest.mark.skipif(os.name != "nt", reason="requires the live Windows DLL loader")
def test_a_planted_dll_cannot_masquerade_as_an_api_set(tmp_path: Path) -> None:
    """CC-WS5-PKG-003 (Codex r2, Critical) -- the spoofability half.

    The auditor's exact counterexample, kept as a test: copy a real DLL to a
    file named like an API set, put its directory on the DLL search path, and
    ask. Under the round-2 implementation this flipped `is_system_dll` from
    False to True -- the loader was answering "can I find something by this
    name?", which a planted file satisfies as well as an OS contract does.

    Two independent defences must now hold:
      1. `is_system_dll` never consults the loader at all, so planting cannot
         reach it.
      2. Even the corroboration helper rejects it, because an API set is
         virtual and forwards to a host DLL, so a genuine one never resolves to
         a file bearing its own name.
    """
    fake = "api-ms-win-civiccast-fake-l99-99-99.dll"
    real_dll = Path(os.environ["WINDIR"]) / "System32" / "ucrtbase.dll"
    if not real_dll.is_file():  # pragma: no cover - non-Windows dev host
        pytest.skip("needs a real Windows System32 DLL to plant")
    shutil.copy2(real_dll, tmp_path / fake)

    cookie = os.add_dll_directory(str(tmp_path))
    try:
        assert build_native_runtime_closure.is_system_dll(fake) is False
        assert build_native_runtime_closure.api_set_resolves_as_a_real_contract(fake) is False
    finally:
        cookie.close()


def test_api_set_inventory_matches_what_the_pinned_closure_actually_imports() -> None:
    """The inventory is derived from the pinned PE set, not hand-maintained.

    Locked as an exact set so that BOTH drift directions are caught: a new
    contract appearing without review, and an entry silently deleted (which
    would push a genuine OS dependency back into the closure walk and break the
    build with a confusing unresolved import instead of a clear message).

    See `evidence/api-set-contract-inventory.md` for the derivation.
    """
    inventory = build_native_runtime_closure.API_SET_CONTRACTS
    assert set(inventory) == {
        "api-ms-win-core-synch-l1-2-0.dll",
        "api-ms-win-core-winrt-l1-1-0.dll",
        "api-ms-win-core-winrt-string-l1-1-0.dll",
        "api-ms-win-crt-conio-l1-1-0.dll",
        "api-ms-win-crt-convert-l1-1-0.dll",
        "api-ms-win-crt-environment-l1-1-0.dll",
        "api-ms-win-crt-filesystem-l1-1-0.dll",
        "api-ms-win-crt-heap-l1-1-0.dll",
        "api-ms-win-crt-locale-l1-1-0.dll",
        "api-ms-win-crt-math-l1-1-0.dll",
        "api-ms-win-crt-multibyte-l1-1-0.dll",
        "api-ms-win-crt-process-l1-1-0.dll",
        "api-ms-win-crt-runtime-l1-1-0.dll",
        "api-ms-win-crt-stdio-l1-1-0.dll",
        "api-ms-win-crt-string-l1-1-0.dll",
        "api-ms-win-crt-time-l1-1-0.dll",
        "api-ms-win-crt-utility-l1-1-0.dll",
    }
    # Every entry must carry the release that introduced it -- the whole basis
    # for claiming it is present at the supported floor.
    for contract, introduced in inventory.items():
        assert introduced.startswith("Windows "), contract


def test_host_runtime_prefix_is_bounded_to_the_pinned_interpreter() -> None:
    """Same fail-open shape on the CPython exemption: anything starting with
    `python3` was waved through. It is now the exact set the pinned
    interpreter can actually present."""
    assert build_native_runtime_closure.is_host_runtime_dll("python312.dll") is True
    assert build_native_runtime_closure.is_host_runtime_dll("python3.dll") is True
    assert build_native_runtime_closure.is_host_runtime_dll("python3-civiccast-fake.dll") is False
    assert build_native_runtime_closure.is_host_runtime_dll("python399.dll") is False


def test_system_allowlist_does_not_match_a_shipped_gstreamer_dll() -> None:
    assert build_native_runtime_closure.is_system_dll("gstreamer-1.0-0.dll") is False


def test_system_allowlist_covers_the_imports_the_first_real_build_refused_on() -> None:
    """Regression lock for the seven imports that made the first end-to-end
    closure run refuse.

    Each was verified present in %WINDIR%\\System32 on Windows 11 26100 before
    being allowlisted; none is redistributable, so allowlisting was the only
    correct outcome. Listing them by name here means a future edit that drops
    one gets caught by a test instead of by a build failure hours later.
    """
    refused_by_the_first_real_run = (
        "MSIMG32.dll",
        "DNSAPI.dll",
        "OPENGL32.dll",
        "DWrite.dll",
        "d2d1.dll",
        "bcryptprimitives.dll",
    )
    for name in refused_by_the_first_real_run:
        assert build_native_runtime_closure.is_system_dll(name) is True, name


def test_technical_os_floor_is_separated_from_the_supported_os_policy() -> None:
    """CC-WS5-PKG-007 (Codex r1, Major).

    The two were previously one sentence reading "Windows 10 1809; d3d12.dll is
    the binding constraint", which implies 1809 was DERIVED from the allowlist.
    It was not -- d3d12 shipped with the original Windows 10 (1507), so nothing
    in this closure requires 1809. Presenting a product policy as a technical
    finding overclaims what the dependency analysis proves.

    They must stay separable so a future allowlist entry that genuinely raises
    the technical floor changes a different line than a policy change does.
    """
    technical = build_native_runtime_closure.TECHNICAL_OS_FLOOR
    policy = build_native_runtime_closure.SUPPORTED_OS_POLICY

    assert "1507" in technical, "the technical floor must state the real d3d12 baseline"
    assert "d3d12" in technical
    assert "1809" not in technical, "1809 is policy, not a technical requirement"

    assert "1809" in policy
    assert "policy" in policy.lower(), "the supported floor must say it is a choice"

    summary = build_native_runtime_closure.OS_DEPENDENCY_FLOOR
    assert technical in summary
    assert policy in summary


# --------------------------------------------------------------------------
# pefile-backed imports_of
# --------------------------------------------------------------------------


class _FakeImportlessPE:
    """Stands in for `pefile.PE` on a PE with no import directory.

    Cheapest possible fake: no real binary is needed because `_pe_imports`
    is tested against the exact code path pefile exposes -- an object with
    no `DIRECTORY_ENTRY_IMPORT` attribute after `parse_data_directories` --
    without paying for a real, committed PE fixture.
    """

    def __init__(self, name: str, fast_load: bool | None = None) -> None:
        self.name = name

    def parse_data_directories(self, directories: list[int]) -> None:
        return None

    def close(self) -> None:
        return None


def test_pe_imports_returns_empty_list_for_a_pe_with_no_import_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(build_native_runtime_closure.pefile, "PE", _FakeImportlessPE)
    fake_dll = tmp_path / "resource_only.dll"
    fake_dll.write_bytes(b"")  # content is irrelevant; pefile.PE is stubbed out

    result = build_native_runtime_closure._pe_imports(fake_dll)

    assert result == []


# --------------------------------------------------------------------------
# Plugin locator
# --------------------------------------------------------------------------


def test_plugin_locator_finds_a_plugin_by_basename_anywhere_under_the_tree(
    tmp_path: Path,
) -> None:
    plugin_dir = tmp_path / "gstreamer_plugins" / "lib" / "gstreamer-1.0"
    plugin_dir.mkdir(parents=True)
    plugin_path = plugin_dir / "gstopenh264.dll"
    plugin_path.write_bytes(b"")

    found = build_native_runtime_closure.locate_plugin(tmp_path, "gstopenh264.dll")

    assert found == plugin_path


def test_python_extension_modules_do_not_also_land_in_bin(tmp_path: Path) -> None:
    """The gi `.pyd` files are closure SEEDS (so their DLL dependencies get
    walked) but they are ALSO copied as part of the gi package resource copy.
    Mapping them to bin/ like any other PE file shipped them twice: once at
    bin/_gi.cp312-win_amd64.pyd and once at python/gi/_gi.cp312-win_amd64.pyd.

    Only the python/gi/ copy is importable. The bin/ copy is 416 KB of dead
    weight sitting in a directory that is on PATH. Found by a provenance sweep
    of a real built tree, which listed both copies as separate files.
    """
    dest = build_native_runtime_closure._dest_for_pe_file(
        "gstreamer_python/Lib/site-packages/gi/_gi.cp312-win_amd64.pyd"
    )
    assert dest == "python/gi/_gi.cp312-win_amd64.pyd"

    nested = build_native_runtime_closure._dest_for_pe_file(
        "gstreamer_python/Lib/site-packages/gi/overrides/_gi_gst.cp312-win_amd64.pyd"
    )
    assert nested == "python/gi/overrides/_gi_gst.cp312-win_amd64.pyd"


def test_ordinary_native_dlls_still_land_flat_in_bin() -> None:
    """Guard the fix above from over-reaching: a normal support library must
    keep its bin/ destination even though it also lives under a wheel path."""
    assert (
        build_native_runtime_closure._dest_for_pe_file("gstreamer_libs/bin/glib-2.0-0.dll")
        == "bin/glib-2.0-0.dll"
    )
    assert (
        build_native_runtime_closure._dest_for_pe_file(
            "gstreamer_plugins/lib/gstreamer-1.0/gstopenh264.dll"
        )
        == "lib/gstreamer-1.0/gstopenh264.dll"
    )


def test_plugin_locator_returns_none_not_an_exception_when_absent(tmp_path: Path) -> None:
    found = build_native_runtime_closure.locate_plugin(tmp_path, "gstx264.dll")

    assert found is None


# --------------------------------------------------------------------------
# Typelib prune (owner-approved 2026-07-24, WP-6 Part 0) -- the builder copies
# EVERY *.typelib by blanket rglob (`_collect_typelibs`), so pruning a file
# has to be an explicit exclusion list, not a bare deletion: a deletion is
# silently resurrected on the next rebuild. DBus-1.0.typelib /
# DBusGLib-1.0.typelib are inert introspection metadata (no libdbus/dbus-glib
# DLL ships in bin/, so nothing can load them) and are dual-licensed
# AFL-2.1 OR GPL-2.0-or-later upstream -- dead, GPL-adjacent bytes.
# See OWNER-DECISION-licensing-dispositions.md.
# --------------------------------------------------------------------------


def test_excluded_typelibs_are_the_two_dead_dbus_typelibs_only() -> None:
    """The exclusion set is exactly the two owner-approved-for-prune typelibs.

    Locked as an exact set so a future edit that widens or narrows it is caught
    here. The AC4 tamper control targets Gst-1.0.typelib, which must NOT be in
    the exclusion set -- pruning it would break that control.
    """
    excluded = build_native_runtime_closure.EXCLUDED_TYPELIB_BASENAMES
    assert set(excluded) == {"DBus-1.0.typelib", "DBusGLib-1.0.typelib"}
    assert "Gst-1.0.typelib" not in excluded


def test_collect_typelibs_drops_the_pruned_names_and_keeps_the_rest(tmp_path: Path) -> None:
    """`_collect_typelibs` never yields a pruned typelib, so the two dead D-Bus
    typelibs can never reach the copied tree (and therefore never the built
    manifest), while every other typelib is still collected."""
    girepo = tmp_path / "gstreamer_libs" / "lib" / "girepository-1.0"
    girepo.mkdir(parents=True)
    for name in (
        "Gst-1.0.typelib",
        "GLib-2.0.typelib",
        "DBus-1.0.typelib",
        "DBusGLib-1.0.typelib",
    ):
        (girepo / name).write_bytes(b"")

    collected = {p.name for p in build_native_runtime_closure._collect_typelibs(tmp_path)}

    assert "DBus-1.0.typelib" not in collected
    assert "DBusGLib-1.0.typelib" not in collected
    assert collected == {"Gst-1.0.typelib", "GLib-2.0.typelib"}


# --------------------------------------------------------------------------
# Upstream license notices (<out>/licenses/) -- audit finding fix
#
# Covers: empirically detecting whether a staged wheel bundles a license
# text file (it usually doesn't -- setuptools is the one exception in the
# real staged tree), parsing the METADATA fields that DO carry licensing
# information (License / License-Expression / Classifier), rendering a
# per-distribution notice from them verbatim, and writing the whole
# directory with the output-relative-path -> distribution mapping the build
# needs to fold into `distribution_of` so these files are covered by
# runtime-manifest.json/SHA256SUMS like everything else in the tree.
# --------------------------------------------------------------------------


def _write_metadata(dist_info: Path, text: str) -> None:
    dist_info.mkdir(parents=True, exist_ok=True)
    (dist_info / "METADATA").write_text(text, encoding="utf-8")


def test_dist_info_bundles_license_text_is_false_when_no_license_file_present(
    tmp_path: Path,
) -> None:
    dist_info = tmp_path / "gstreamer_libs-1.28.5.dist-info"
    _write_metadata(dist_info, "Name: gstreamer_libs\nVersion: 1.28.5\n")

    assert build_native_runtime_closure._dist_info_bundles_license_text(dist_info) is False


def test_dist_info_bundles_license_text_is_true_for_a_flat_license_file(tmp_path: Path) -> None:
    dist_info = tmp_path / "setuptools-83.0.0.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "LICENSE").write_text("MIT text here\n", encoding="utf-8")

    assert build_native_runtime_closure._dist_info_bundles_license_text(dist_info) is True


def test_dist_info_bundles_license_text_is_true_for_a_licenses_subdirectory(
    tmp_path: Path,
) -> None:
    dist_info = tmp_path / "setuptools-83.0.0.dist-info"
    licenses_dir = dist_info / "licenses"
    licenses_dir.mkdir(parents=True)
    (licenses_dir / "LICENSE").write_text("MIT text here\n", encoding="utf-8")

    assert build_native_runtime_closure._dist_info_bundles_license_text(dist_info) is True


def test_parse_distribution_metadata_reads_the_license_field_verbatim(tmp_path: Path) -> None:
    dist_info = tmp_path / "gstreamer_libs-1.28.5.dist-info"
    _write_metadata(
        dist_info,
        "Name: gstreamer_libs\n"
        "Version: 1.28.5\n"
        "Home-page: http://gstreamer.freedesktop.org\n"
        "License: Apache-2.0 AND LGPL-2.1-or-later AND MIT\n",
    )

    parsed = build_native_runtime_closure.parse_distribution_metadata(tmp_path)

    meta = parsed["gstreamer_libs"]
    assert meta.name == "gstreamer_libs"
    assert meta.version == "1.28.5"
    assert meta.home_page == "http://gstreamer.freedesktop.org"
    assert meta.license_field == "Apache-2.0 AND LGPL-2.1-or-later AND MIT"
    assert meta.license_expression_field is None
    assert meta.has_bundled_license_file is False


def test_parse_distribution_metadata_reads_the_license_expression_field(tmp_path: Path) -> None:
    dist_info = tmp_path / "setuptools-83.0.0.dist-info"
    _write_metadata(
        dist_info,
        "Name: setuptools\nVersion: 83.0.0\nLicense-Expression: MIT\nLicense-File: LICENSE\n",
    )
    (dist_info / "licenses").mkdir()
    (dist_info / "licenses" / "LICENSE").write_text("MIT text\n", encoding="utf-8")

    parsed = build_native_runtime_closure.parse_distribution_metadata(tmp_path)

    meta = parsed["setuptools"]
    assert meta.license_expression_field == "MIT"
    assert meta.has_bundled_license_file is True


def test_parse_distribution_metadata_captures_license_classifiers(tmp_path: Path) -> None:
    dist_info = tmp_path / "gstreamer_plugins-1.28.5.dist-info"
    _write_metadata(
        dist_info,
        "Name: gstreamer_plugins\n"
        "Version: 1.28.5\n"
        "Classifier: Development Status :: 5 - Production/Stable\n"
        "Classifier: License :: OSI Approved :: GNU Lesser General Public License v2 "
        "(LGPLv2)\n",
    )

    parsed = build_native_runtime_closure.parse_distribution_metadata(tmp_path)

    meta = parsed["gstreamer_plugins"]
    assert meta.license_classifiers == (
        "License :: OSI Approved :: GNU Lesser General Public License v2 (LGPLv2)",
    )


def test_render_distribution_license_notice_includes_name_version_and_verbatim_license(
    tmp_path: Path,
) -> None:
    dist_info = tmp_path / "gstreamer_libs-1.28.5.dist-info"
    _write_metadata(
        dist_info,
        "Name: gstreamer_libs\n"
        "Version: 1.28.5\n"
        "Home-page: http://gstreamer.freedesktop.org\n"
        "License: LGPL-2.1-or-later AND MIT\n",
    )
    meta = build_native_runtime_closure.parse_distribution_metadata(tmp_path)["gstreamer_libs"]

    notice = build_native_runtime_closure.render_distribution_license_notice(meta)

    assert "gstreamer_libs" in notice
    assert "1.28.5" in notice
    assert "LGPL-2.1-or-later AND MIT" in notice
    assert "http://gstreamer.freedesktop.org" in notice
    assert "upstream" in notice.lower()
    assert "not a civiccast determination" in notice.lower()


def test_render_distribution_license_notice_states_plainly_when_no_text_is_bundled(
    tmp_path: Path,
) -> None:
    dist_info = tmp_path / "gstreamer_libs-1.28.5.dist-info"
    _write_metadata(dist_info, "Name: gstreamer_libs\nVersion: 1.28.5\nLicense: MIT\n")
    meta = build_native_runtime_closure.parse_distribution_metadata(tmp_path)["gstreamer_libs"]

    notice = build_native_runtime_closure.render_distribution_license_notice(meta)

    assert "no bundled license text" in notice.lower()


def test_write_license_notices_writes_one_entry_per_staged_distribution_plus_a_readme(
    tmp_path: Path,
) -> None:
    stage = tmp_path / "stage"
    out = tmp_path / "out"
    out.mkdir()
    _write_metadata(
        stage / "gstreamer_libs-1.28.5.dist-info",
        "Name: gstreamer_libs\nVersion: 1.28.5\nLicense: LGPL-2.1-or-later\n",
    )
    _write_metadata(
        stage / "gstreamer_plugins-1.28.5.dist-info",
        "Name: gstreamer_plugins\nVersion: 1.28.5\nLicense: LGPL-2.1-or-later\n",
    )

    distribution_of = build_native_runtime_closure.write_license_notices(
        stage, out, ["gstreamer_libs", "gstreamer_plugins"]
    )

    licenses_dir = out / "licenses"
    notice_files = sorted(p.name for p in licenses_dir.glob("*.txt"))
    assert notice_files == ["gstreamer_libs.txt", "gstreamer_plugins.txt"]
    assert (licenses_dir / "README.md").is_file()

    assert distribution_of["licenses/gstreamer_libs.txt"] == "gstreamer_libs"
    assert distribution_of["licenses/gstreamer_plugins.txt"] == "gstreamer_plugins"
    assert (
        distribution_of["licenses/README.md"]
        == build_native_runtime_closure.LICENSE_NOTICES_DISTRIBUTION
    )


def test_write_license_notices_refuses_a_distribution_with_no_staged_metadata(
    tmp_path: Path,
) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    out = tmp_path / "out"
    out.mkdir()

    with pytest.raises(RuntimeError, match="no-such-distribution"):
        build_native_runtime_closure.write_license_notices(stage, out, ["no-such-distribution"])


def test_license_notices_readme_states_the_metadata_expression_is_upstream_not_ours(
    tmp_path: Path,
) -> None:
    stage = tmp_path / "stage"
    _write_metadata(
        stage / "gstreamer_libs-1.28.5.dist-info",
        "Name: gstreamer_libs\nVersion: 1.28.5\nLicense: LGPL-2.1-or-later\n",
    )
    metadata_by_distribution = build_native_runtime_closure.parse_distribution_metadata(stage)

    readme = build_native_runtime_closure.render_license_notices_readme(
        ["gstreamer_libs"], metadata_by_distribution
    )

    assert "upstream" in readme.lower()
    assert "civiccast determination" in readme.lower()
    assert "full" in readme.lower() and "license text" in readme.lower()


# --------------------------------------------------------------------------
# Bundled license TEXTS (<out>/licenses/texts/) -- fix for Codex audit
# finding CC-WS5-PKG-004 (Major): spec D3 requires required NOTICES to be
# BUNDLED with the runtime; a BOM naming "LGPL-2.1-or-later" is not a
# substitute for the LGPL-2.1-or-later text itself. Covers: deriving the
# distinct set of licenses actually shipped from `distribution_of` (never a
# fixed list baked into the script), copying the corresponding committed
# text file for each one, refusing to build when a shipped license has no
# available text, and the invariant that every SPDX identifier
# `civiccast.native.runtime_licenses` can ever resolve a shipped file to has
# a corresponding bundled text file.
# --------------------------------------------------------------------------


def test_resolve_shipped_licenses_derives_the_distinct_set_from_distribution_of() -> None:
    distribution_of = {
        "bin/glib-2.0-0.dll": "gstreamer_libs",
        "lib/gstreamer-1.0/gstopenh264.dll": "gstreamer_plugins_restricted",
        "bin/z-1.dll": "gstreamer_libs",
        "licenses/README.md": build_native_runtime_closure.LICENSE_NOTICES_DISTRIBUTION,
    }

    licenses = build_native_runtime_closure.resolve_shipped_licenses(distribution_of)

    assert licenses == ("Apache-2.0", "BSD-2-Clause", "LGPL-2.1-or-later", "Zlib")


def test_resolve_shipped_licenses_excludes_unresolved_paths() -> None:
    # A path classify_shipped_file cannot resolve (not a known basename/
    # prefix) must not appear as a phantom `None` entry in the derived set.
    distribution_of = {"bin/totally-unclassified-file.bin": "some_distribution"}

    licenses = build_native_runtime_closure.resolve_shipped_licenses(distribution_of)

    assert None not in licenses
    assert licenses == ()


def test_write_license_texts_copies_the_bundled_text_for_each_license(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()

    distribution_of = build_native_runtime_closure.write_license_texts(out, ("MIT", "Zlib"))

    mit_text = (out / "licenses" / "texts" / "MIT.txt").read_text(encoding="utf-8")
    assert "Permission is hereby granted" in mit_text
    zlib_text = (out / "licenses" / "texts" / "Zlib.txt").read_text(encoding="utf-8")
    assert zlib_text  # non-empty; content is the real Zlib license text

    assert (
        distribution_of["licenses/texts/MIT.txt"]
        == build_native_runtime_closure.LICENSE_TEXTS_DISTRIBUTION
    )
    assert (
        distribution_of["licenses/texts/Zlib.txt"]
        == build_native_runtime_closure.LICENSE_TEXTS_DISTRIBUTION
    )


def test_write_license_texts_refuses_when_a_shipped_license_has_no_bundled_text(
    tmp_path: Path,
) -> None:
    out = tmp_path / "out"
    out.mkdir()

    with pytest.raises(RuntimeError, match="No-Such-License-9000"):
        build_native_runtime_closure.write_license_texts(out, ("MIT", "No-Such-License-9000"))

    # Refusing must not leave a half-written texts/ directory holding only
    # the licenses that happened to resolve before the missing one was hit.
    assert not (out / "licenses" / "texts" / "MIT.txt").is_file()


def test_every_license_runtime_licenses_can_resolve_has_a_bundled_text_file() -> None:
    """The invariant CC-WS5-PKG-004 exists to guarantee: every SPDX
    identifier `civiccast.native.runtime_licenses.classify_shipped_file` can
    ever return for a shipped file has a corresponding
    `civiccast/native/license_texts/<id>.txt`. A new license appearing in
    the per-file tables with no text added alongside it must fail this
    test, not ship silently.
    """
    from civiccast.native import runtime_licenses
    from civiccast.native.license_texts import available_license_texts

    known_expressions = (
        set(runtime_licenses.PLUGIN_LICENSE.values())
        | set(runtime_licenses.SUPPORT_LIBRARY_LICENSE.values())
        | set(runtime_licenses.TYPELIB_LICENSE.values())
        | {runtime_licenses.GENERATED_ARTIFACT_LICENSE}
    )
    # Expand every expression into its component identifiers. A cumulative
    # expression like fontconfig's obliges the tree to bundle a text for EACH
    # component, not one text for the whole string -- checking the expression
    # as an opaque key is how four of fontconfig's five notices could have
    # gone missing while this test stayed green.
    known_licenses = {
        identifier
        for expression in known_expressions
        for identifier in runtime_licenses.license_identifiers_in(expression)
    }
    available = available_license_texts()

    missing = sorted(known_licenses - set(available))
    assert missing == [], f"no bundled license text for: {missing}"


def test_afl_2_1_license_text_is_removed_with_the_pruned_dbus_typelibs() -> None:
    """WP-6 Part 0: AFL-2.1 was elected ONLY by DBus-1.0.typelib /
    DBusGLib-1.0.typelib, both pruned. Its bundled text and its provenance
    ledger entry must both be gone -- and `verify_bundled_license_texts` must
    stay clean (its both-directions set-equality check would fail on either a
    leftover AFL-2.1.txt with no ledger entry, or a ledger entry with no file).
    """
    from civiccast.native.license_texts import (
        LICENSE_TEXT_SOURCES,
        available_license_texts,
        verify_bundled_license_texts,
    )

    assert "AFL-2.1" not in LICENSE_TEXT_SOURCES
    assert "AFL-2.1" not in available_license_texts()
    verify_bundled_license_texts()  # must not raise


def test_microsoft_vcredist_text_explicitly_records_that_no_text_is_reproduced() -> None:
    """The one license with genuinely no redistributable text (spec D3's own
    instruction: 'record a pointer ... and say plainly that the text is not
    reproducible here'). Must be an explicit statement, not a silently
    missing/empty file."""
    from civiccast.native.license_texts import LICENSE_TEXTS_DIR

    path = LICENSE_TEXTS_DIR / "LicenseRef-Microsoft-VCRedist.txt"
    assert path.is_file()
    text = path.read_text(encoding="utf-8").lower()
    assert "not reproduced" in text or "not reproducible" in text
    assert "microsoft" in text


# --------------------------------------------------------------------------
# License-text provenance is PINNED and ENFORCED (CC-WS5-PKG-004 round 2)
# --------------------------------------------------------------------------


def test_every_spdx_sourced_text_is_pinned_to_an_immutable_commit() -> None:
    """No entry may cite a moving ref.

    Round 1 asked for version-pinned sources; the first attempt recorded
    `.../license-list-data/main/text/...`, which names a BRANCH. It documents
    where bytes came from once and can never detect that upstream changed --
    provenance that cannot fail. This test is the guard against quietly
    reintroducing that: every SPDX-sourced entry must cite the pinned commit
    and carry a hash.
    """
    from civiccast.native.license_texts import LICENSE_TEXT_SOURCES, SPDX_LICENSE_LIST_COMMIT

    assert len(SPDX_LICENSE_LIST_COMMIT) == 40, "must be a full commit SHA, not a tag or branch"

    for spdx_id, source in LICENSE_TEXT_SOURCES.items():
        if "license-list-data" not in source.source:
            continue  # non-SPDX upstream (fontconfig's COPYING) or the MS pointer
        assert "/main/" not in source.source, f"{spdx_id} cites a moving branch ref"
        assert SPDX_LICENSE_LIST_COMMIT in source.source, f"{spdx_id} is not pinned"
        assert source.sha256, f"{spdx_id} has no expected content hash"


def test_bundled_license_texts_match_their_pinned_upstream_hashes() -> None:
    """The committed texts are, right now, byte-identical to what was pinned."""
    from civiccast.native.license_texts import verify_bundled_license_texts

    verify_bundled_license_texts()  # must not raise


def test_verify_bundled_license_texts_detects_altered_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An altered license text must halt, naming the file and its upstream.

    Simulated by pinning a hash the real file cannot match -- equivalent to
    the file's bytes having changed, without mutating a legally operative
    file on disk to prove it.
    """
    from civiccast.native import license_texts

    tampered = license_texts.LicenseTextSource(
        source=license_texts.LICENSE_TEXT_SOURCES["MIT"].source,
        fetched="2026-07-23",
        sha256="0" * 64,
    )
    monkeypatch.setitem(license_texts.LICENSE_TEXT_SOURCES, "MIT", tampered)

    with pytest.raises(license_texts.LicenseTextTamperError) as excinfo:
        license_texts.verify_bundled_license_texts()

    message = str(excinfo.value)
    assert "MIT" in message
    assert "0" * 64 in message  # the expectation
    assert "license-list-data" in message  # where to re-fetch it from


def test_verify_bundled_license_texts_detects_a_pinned_text_that_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pinned entry whose file was deleted must halt too -- not be skipped.

    The failure mode this guards: deleting the .txt makes the tree ship
    without a required notice, and a check that only compared EXISTING files
    would go green on the deletion.
    """
    from civiccast.native import license_texts

    monkeypatch.setitem(
        license_texts.LICENSE_TEXT_SOURCES,
        "TotallyAbsent-1.0",
        license_texts.LicenseTextSource(
            source="https://example.invalid/x.txt", fetched="2026-07-23", sha256="f" * 64
        ),
    )

    with pytest.raises(license_texts.LicenseTextTamperError) as excinfo:
        license_texts.verify_bundled_license_texts()
    assert "TotallyAbsent-1.0" in str(excinfo.value)


def test_every_bundled_text_is_pinned_including_the_microsoft_pointer() -> None:
    """CC-WS5-PKG-012 (Codex r4). Nothing may skip the integrity check.

    The Microsoft file was previously left unpinned because it has no upstream
    to compare against. But it is a legal-posture STATEMENT that ships to
    operators, so "no upstream" is a reason it cannot be verified against
    spdx.org -- not a reason it should be silently editable.
    """
    from civiccast.native.license_texts import LICENSE_TEXT_SOURCES

    unpinned = sorted(k for k, v in LICENSE_TEXT_SOURCES.items() if not v.sha256)
    assert unpinned == []


def test_an_unledgered_license_text_cannot_ship(tmp_path: Path) -> None:
    """CC-WS5-PKG-012 (Codex r4, Major) -- reproduced, then closed.

    The verifier only asked "does each LEDGERED entry match its hash?", so a
    .txt file nobody reviewed could sit in the directory, verify clean, and be
    staged into the shipped tree as an authoritative notice --
    `available_license_texts()` is a directory listing precisely so the builder
    trusts what is on disk. Correspondence must hold in BOTH directions.
    """
    from civiccast.native import license_texts

    extra = license_texts.LICENSE_TEXTS_DIR / "Totally-Unreviewed-1.0.txt"
    extra.write_text("whatever we like\n", encoding="utf-8")
    try:
        with pytest.raises(license_texts.LicenseTextTamperError) as excinfo:
            license_texts.verify_bundled_license_texts()
        assert "Totally-Unreviewed-1.0.txt" in str(excinfo.value)
    finally:
        extra.unlink()
    license_texts.verify_bundled_license_texts()  # clean again


def test_api_set_corroborator_answers_false_for_malformed_input() -> None:
    """CC-WS5-PKG-011 (Codex r4, Minor). An embedded NUL made ctypes raise
    ValueError, so malformed input crashed the caller instead of being
    answered. A predicate should say False to nonsense, not throw."""
    assert (
        build_native_runtime_closure.api_set_resolves_as_a_real_contract(
            "api-ms-win-\x00-l1-1-0.dll"
        )
        is False
    )
    assert build_native_runtime_closure.api_set_resolves_as_a_real_contract("") is False


def test_api_set_corroborator_enforces_the_complete_basename_grammar() -> None:
    """CC-WS5-PKG-011 (Codex r5, Minor -- the round-4 fix was incomplete).

    The loader FORWARDS malformed API-set variants: on a live Windows,
    `api-ms-win-crt-heap-l1-1-0` (no suffix) and the same name ending in
    `.exe` both resolve to ucrtbase.dll, so 'the loader forwarded it' is not
    evidence of valid grammar and produced false corroboration. The complete
    basename grammar is now enforced BEFORE the loader is consulted:
    `api-`/`ext-` scheme, hyphenated alphanumeric name parts, an
    `-l<n>-<n>-<n>` version triplet, and a literal `.dll`.
    """
    resolves = build_native_runtime_closure.api_set_resolves_as_a_real_contract
    # The auditor's exact false-positives: forwarded, but not the grammar.
    assert resolves("api-ms-win-crt-heap-l1-1-0") is False, "missing .dll suffix"
    assert resolves("api-ms-win-crt-heap-l1-1-0.exe") is False, "wrong suffix"
    # More malformed shapes the grammar must refuse.
    assert resolves("api-ms-win-crt-heap-l1-1-0.dll.dll") is False, "doubled suffix"
    assert resolves("api-ms-win-crt-heap-l1-1.dll") is False, "two-field version"
    assert resolves("api-ms-win-crt-heap-lx-1-0.dll") is False, "non-numeric level"
    assert resolves("api-.dll") is False, "no name parts, no version triplet"
    assert resolves("bpi-ms-win-crt-heap-l1-1-0.dll") is False, "wrong scheme prefix"
    assert resolves("api-ms-win-crt-heap-l1-1-0.dll" + "x" * 400) is False, "overlong"


@pytest.mark.windows_only
@pytest.mark.skipif(os.name != "nt", reason="requires the live Windows API-set resolver")
def test_api_set_corroborator_accepts_real_contracts_case_insensitively() -> None:
    resolves = build_native_runtime_closure.api_set_resolves_as_a_real_contract
    # Real contracts still corroborate, including mixed case -- Windows module
    # names are case-insensitive and the round-5 verdict confirmed mixed-case
    # real input returning True is correct behaviour to preserve.
    assert resolves("api-ms-win-crt-heap-l1-1-0.dll") is True
    assert resolves("API-MS-WIN-CRT-HEAP-L1-1-0.DLL") is True


def test_license_identifiers_in_splits_a_cumulative_expression() -> None:
    """The mechanism that makes a multi-notice component bundle every notice."""
    from civiccast.native.runtime_licenses import (
        FONTCONFIG_2_16_1_LICENSE,
        license_identifiers_in,
    )

    assert license_identifiers_in("MIT") == ("MIT",)
    assert license_identifiers_in(FONTCONFIG_2_16_1_LICENSE) == (
        "HPND-sell-variant",
        "LicenseRef-Fontconfig-2.16.1",
        "MIT",
        "MIT-Modern-Variant",
        "Unicode-TOU",
    )
    # Operators are not licenses and must never be looked up as one.
    assert "AND" not in license_identifiers_in(FONTCONFIG_2_16_1_LICENSE)
    assert license_identifiers_in("MIT OR Apache-2.0") == ("Apache-2.0", "MIT")
    assert license_identifiers_in("GPL-2.0-only WITH Classpath-exception-2.0") == (
        "Classpath-exception-2.0",
        "GPL-2.0-only",
    )


def test_write_license_notices_readme_points_at_the_bundled_texts_directory(
    tmp_path: Path,
) -> None:
    """The README's old claim ('the full text is NOT available ... must be
    sourced separately') is stale now that texts ARE bundled -- it must be
    updated to say so, or the generated doc contradicts the tree it ships
    in."""
    stage = tmp_path / "stage"
    _write_metadata(
        stage / "gstreamer_libs-1.28.5.dist-info",
        "Name: gstreamer_libs\nVersion: 1.28.5\nLicense: LGPL-2.1-or-later\n",
    )
    metadata_by_distribution = build_native_runtime_closure.parse_distribution_metadata(stage)

    readme = build_native_runtime_closure.render_license_notices_readme(
        ["gstreamer_libs"], metadata_by_distribution
    )

    assert "licenses/texts/" in readme
