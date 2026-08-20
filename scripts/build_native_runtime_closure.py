#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Build the native Windows runtime packaging closure (I/O shell).

Implements the I/O half of `spec-packaging-closure`: stages the pinned
upstream wheels (D1), builds the file -> owning-distribution provenance
index, resolves the required GStreamer plugins to files in the staged tree
(never by probing GStreamer -- see `civiccast.native.runtime_closure`'s
module doc on why hardware-gated factories make a live probe
machine-dependent), walks the PE import closure with real `pefile` parsing,
copies everything into the SHARED CONTRACT tree layout, writes the
per-distribution upstream license notices (`licenses/`) plus the actual
bundled license TEXT for every license the tree ships (`licenses/texts/`,
from the committed `civiccast.native.license_texts` data -- spec D3, fix
for Codex audit finding CC-WS5-PKG-004), and writes the trust artifacts
(`runtime-manifest.json`, `SHA256SUMS`, `LICENSE-BOM.md`) via
`civiccast.native.runtime_manifest`.

All graph/policy logic is reused, not reimplemented, from
`civiccast.native.runtime_closure` (element policy, GPL refusal, the pure PE
walk) and `civiccast.native.runtime_manifest` (manifest schema, license
gate, SHA256SUMS/LICENSE-BOM rendering). This module supplies the concrete
`imports_of` / `resolve` callables those pure functions need, plus the
filesystem work neither of them does.

Refusals propagate rather than getting caught: an unauthenticated lockfile,
a GPL-tainted required factory, a missing plugin, an unresolvable PE import,
or an unknown-license file are all halt triggers per the spec, and a script
that swallowed them into a soft warning would be exactly the "quietly
degraded" failure mode the spec exists to prevent.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path, PurePosixPath
from shutil import copy2, rmtree
from tempfile import mkdtemp
from typing import Final

import pefile  # type: ignore[import-untyped]  # no inline types, no stub package upstream

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from civiccast.native.license_texts import (  # noqa: E402
    available_license_texts,
    verify_bundled_license_texts,
)
from civiccast.native.runtime_closure import (  # noqa: E402
    ABSENCE_TOLERANT_FACTORIES,
    CONDITIONAL_FACTORIES,
    FACTORY_PLUGIN,
    NON_FACTORY_PLUGINS,
    REQUIRED_FACTORIES,
    assert_authorized_distributions,
    assert_no_gpl_distributions,
    resolve_pe_closure,
    select_plugin_seeds,
)
from civiccast.native.runtime_licenses import (  # noqa: E402
    classify_shipped_file,
    license_identifiers_in,
)
from civiccast.native.runtime_manifest import (  # noqa: E402
    build_runtime_manifest,
    hash_directory_tree,
    render_license_bom,
    render_sha256sums,
)

REQUIREMENTS_FILE = ROOT / "requirements-native-runtime.txt"

#: Windows-provided system DLLs -- the MS-provided floor. Anything a shipped
#: PE file imports that is NOT in this set (or does not match the
#: api-ms-win-*/ext-ms-win-* API-set prefixes handled by `is_system_dll`)
#: must be shipped inside the closure or explicitly justified; it is never
#: assumed to "just be there" on the operator's machine.
SYSTEM_DLL_ALLOWLIST: frozenset[str] = frozenset(
    {
        "kernel32.dll",
        "user32.dll",
        "advapi32.dll",
        "ole32.dll",
        "oleaut32.dll",
        "shell32.dll",
        "ws2_32.dll",
        "msvcrt.dll",
        "ucrtbase.dll",
        "bcrypt.dll",
        "crypt32.dll",
        "secur32.dll",
        "winmm.dll",
        "gdi32.dll",
        "dxgi.dll",
        "d3d11.dll",
        "d3d12.dll",
        "mfplat.dll",
        "mfreadwrite.dll",
        "mf.dll",
        # NOT mfuuid.dll. It was allowlisted here originally and that was wrong:
        # `mfuuid` is a static import library (mfuuid.lib) of Media Foundation
        # GUID constants linked at COMPILE time -- there is no mfuuid.dll on
        # Windows at all (verified absent from System32 and SysWOW64 on 26200,
        # newer than our recorded floor). Allowlisting a name that does not
        # exist means that if a future upstream build ever does import it, the
        # closure would silently treat it as OS-provided and ship a tree that
        # dies with "DLL not found" on every operator machine, with no
        # build-time signal. Nothing imports it today; removed before it can
        # matter. Found by the fresh-agent review, which checked all 40
        # allowlist entries against a real System32 instead of assuming.
        "dwmapi.dll",
        "setupapi.dll",
        "cfgmgr32.dll",
        "iphlpapi.dll",
        "psapi.dll",
        "shlwapi.dll",
        "version.dll",
        "userenv.dll",
        "dbghelp.dll",
        "ntdll.dll",
        "rpcrt4.dll",
        "wldap32.dll",
        "normaliz.dll",
        "powrprof.dll",
        # -- OS graphics / text / crypto / networking components -------------
        # Added after the first real closure run REFUSED on these seven imports
        # (the fail-loud path working as designed). Each was then verified
        # present in %WINDIR%\System32 on Windows 11 26100 before being allowed
        # -- none is redistributable, so shipping them is not an option and
        # allowlisting is the only correct outcome. Recorded here rather than
        # waved through, per spec-packaging-closure's halt trigger: "document
        # as explicit OS dependency with version floor, owner-visible".
        # See OS_DEPENDENCY_FLOOR below for what that dependency actually means.
        "msimg32.dll",  # GDI imaging  <- cairo-2.dll
        "dnsapi.dll",  # DNS client   <- gio-2.0-0.dll
        "opengl32.dll",  # OpenGL       <- gstgl-1.0-0.dll
        "dwrite.dll",  # DirectWrite  <- pangowin32-1.0-0.dll
        "d2d1.dll",  # Direct2D     <- gstd3d11.dll, gstd3d12.dll
        "bcryptprimitives.dll",  # CNG primitives <- gstrsclosedcaption.dll
    }
)

#: The TECHNICAL floor the allowlist implies -- the oldest Windows that ships
#: every DLL in SYSTEM_DLL_ALLOWLIST.
#:
#: Direct2D/DirectWrite (d2d1, dwrite) arrived in Windows 7 SP1 with the
#: Platform Update; Media Foundation (mfplat/mfreadwrite/mf) and
#: bcryptprimitives are Windows 7+; d3d11 is Windows 7 SP1+. `d3d12.dll` is the
#: newest and therefore the binding one -- it shipped with the ORIGINAL
#: Windows 10 release (1507, build 10240), not with 1809.
TECHNICAL_OS_FLOOR = "Windows 10 1507 (build 10240) -- d3d12.dll is the newest allowlisted DLL"

#: The SUPPORTED floor, which is a product decision and a higher bar.
#:
#: These two were previously conflated into one sentence that read as though
#: 1809 were derived from the allowlist. It is not: nothing in the closure
#: requires 1809, and stating it that way overclaims what the dependency
#: analysis actually proves (Codex r1 finding CC-WS5-PKG-007, Major). Keeping
#: them as separate named constants means a future allowlist entry that really
#: does raise the TECHNICAL floor changes a different line than a policy change
#: does, and the owner can see which is which.
SUPPORTED_OS_POLICY = (
    "Windows 10 1809 (build 17763) or later -- OWNER-SELECTED product policy, "
    "not a technical requirement of this closure"
)

#: Kept as the single human-readable summary, now stating both honestly.
OS_DEPENDENCY_FLOOR = f"technical: {TECHNICAL_OS_FLOOR}; supported: {SUPPORTED_OS_POLICY}"

#: API-set DLL name prefixes. Used ONLY to decide that a name belongs to the
#: API-set families and must therefore be looked up in `API_SET_CONTRACTS` --
#: never, on its own, to decide that a name is OS-provided. See `is_system_dll`
#: for the two earlier designs that got this wrong.
_SYSTEM_DLL_PREFIXES = ("api-ms-win-", "ext-ms-win-")

#: The EXACT API-set contracts the pinned closure imports, each with the
#: Windows release that introduced it. Derived mechanically from the pinned PE
#: set (every import table, including delay-loads, of all 105 PE files in the
#: built tree), not hand-listed: see
#: `evidence/api-set-contract-inventory.md` for the derivation command and its
#: verbatim output.
#:
#: Deny-by-default. An API-set name absent from this mapping is NOT treated as
#: OS-provided, so it stays in the closure walk and the build refuses with an
#: unresolved import. That is deliberate: a NEW contract appearing in a future
#: upstream bump is a claim about what the supported floor provides, and that
#: claim deserves a human look rather than a silent pass from whatever Windows
#: the build happened to run on.
#:
#: WHY EACH IS SAFE AT THE FLOOR (SUPPORTED_OS_POLICY, Windows 10 1809):
#:   * `api-ms-win-crt-*` (14 of 17) are the Universal CRT. The UCRT became an
#:     OS component in Windows 10 RTM (1507) and has shipped in every Windows
#:     10/11 release since, so all 14 predate 1809 by three years.
#:   * `api-ms-win-core-synch-l1-2-0` and the two `api-ms-win-core-winrt-*`
#:     contracts were introduced in Windows 8, and likewise ship in every
#:     Windows 10 release.
#:
#: STATED LIMITATION, because the difference matters and the previous version
#: of this code blurred it: the above is a review against each contract's
#: DOCUMENTED introduction version. It is NOT a live probe of a clean Windows
#: 10 1809 machine, which CivicCast does not currently have. The residual risk
#: is bounded -- every contract here predates the floor by years, and none is
#: a recent or optional API set -- but "reviewed against documentation" is a
#: weaker claim than "observed on the target", and it is recorded as the
#: weaker one. A live 1809 (or floor-level VM) confirmation is an open owner
#: item, not something this table should be read as having done.
API_SET_CONTRACTS: Final[Mapping[str, str]] = {
    # --- Windows 8 era core contracts -------------------------------------
    "api-ms-win-core-synch-l1-2-0.dll": "Windows 8 (WaitOnAddress family)",
    "api-ms-win-core-winrt-l1-1-0.dll": "Windows 8 (WinRT core, RoInitialize)",
    "api-ms-win-core-winrt-string-l1-1-0.dll": "Windows 8 (HSTRING/WindowsCreateString)",
    # --- Universal CRT, an OS component since Windows 10 1507 -------------
    "api-ms-win-crt-conio-l1-1-0.dll": "Windows 10 1507 (UCRT)",
    "api-ms-win-crt-convert-l1-1-0.dll": "Windows 10 1507 (UCRT)",
    "api-ms-win-crt-environment-l1-1-0.dll": "Windows 10 1507 (UCRT)",
    "api-ms-win-crt-filesystem-l1-1-0.dll": "Windows 10 1507 (UCRT)",
    "api-ms-win-crt-heap-l1-1-0.dll": "Windows 10 1507 (UCRT)",
    "api-ms-win-crt-locale-l1-1-0.dll": "Windows 10 1507 (UCRT)",
    "api-ms-win-crt-math-l1-1-0.dll": "Windows 10 1507 (UCRT)",
    "api-ms-win-crt-multibyte-l1-1-0.dll": "Windows 10 1507 (UCRT)",
    "api-ms-win-crt-process-l1-1-0.dll": "Windows 10 1507 (UCRT)",
    "api-ms-win-crt-runtime-l1-1-0.dll": "Windows 10 1507 (UCRT)",
    "api-ms-win-crt-stdio-l1-1-0.dll": "Windows 10 1507 (UCRT)",
    "api-ms-win-crt-string-l1-1-0.dll": "Windows 10 1507 (UCRT)",
    "api-ms-win-crt-time-l1-1-0.dll": "Windows 10 1507 (UCRT)",
    "api-ms-win-crt-utility-l1-1-0.dll": "Windows 10 1507 (UCRT)",
}

#: DLLs supplied by the CivicCast Python runtime rather than by Windows or by
#: this tree. Deliberately a SEPARATE category from SYSTEM_DLL_ALLOWLIST: these
#: are not "the OS will have it", they are "our own installer must place a
#: CPython alongside this tree". Conflating the two would hide a real product
#: dependency inside a list that reads as Windows guarantees.
#:
#: The PyGObject extension modules link the interpreter directly
#: (`_gi.cp312-win_amd64.pyd` imports `python312.dll`), so the tree's ABI is
#: pinned to the interpreter minor version the wheels were built for. Listed
#: EXACTLY rather than by prefix, so a CPython bump surfaces as an unresolved
#: import that must be looked at, instead of being silently absorbed.
#: The EXACT interpreter DLL names the pinned CPython can present. Not a
#: `python3` prefix: that failed open (see `is_host_runtime_dll`). CPython
#: exposes the version-specific `python3XX.dll` and the stable-ABI forwarder
#: `python3.dll`, and nothing else.
HOST_RUNTIME_DLL_NAMES: frozenset[str] = frozenset({"python312.dll", "python3.dll"})

#: The interpreter the packaged tree's extension modules are built against.
#: The `cp312` ABI tag in the shipped `.pyd` filenames is the evidence; a tree
#: built from these wheels will not load under a different CPython minor.
HOST_PYTHON_REQUIREMENT = "CPython 3.12 (extension modules carry the cp312 ABI tag)"

_GSTREAMER_VERSION_RE = re.compile(r"^gstreamer-libs==([^\s\\]+)", re.MULTILINE)


#: The accepted API-set basename grammar (CC-WS5-PKG-011, round 5): scheme
#: prefix, hyphenated alphanumeric name parts, `-l<major>-<minor>-<build>`,
#: literal `.dll`. All 17 inventory contracts match; the loader-forwarded
#: malformed variants (missing suffix, `.exe`, extra fields) do not.
_API_SET_NAME_GRAMMAR = re.compile(r"(?i)^(?:api|ext)(?:-[a-z0-9]+)+-l\d+-\d+-\d+\.dll$")


@cache
def api_set_resolves_as_a_real_contract(name: str) -> bool:
    """True if the loader resolves ``name`` as a genuine OS API-set contract.

    CORROBORATION ONLY. This can never ADD a name to `API_SET_CONTRACTS`, and
    `is_system_dll` does not call it -- that separation is the fix for the
    round-2 finding, because a packaging decision must not depend on build-host
    state. It exists so evidence can show the inventory's entries really are
    API sets on a live Windows, and so the anti-spoof property below is
    testable.

    The spoof it defeats: the auditor copied `z-1.dll` to a file named
    `api-ms-win-civiccast-fake-l99-99-99.dll` and put its directory on the DLL
    search path. A plain `ctypes.WinDLL(name)` succeeded, because the loader
    was answering "can I find SOMETHING by this name?" -- which a file on the
    search path satisfies just as well as an OS contract does.

    What distinguishes them is where the resolved module actually lives. An API
    set is VIRTUAL: it has no file of its own, and the loader forwards it to a
    real host DLL (`api-ms-win-crt-heap-l1-1-0.dll` -> `ucrtbase.dll`), so the
    loaded module's path NEVER ends in the requested API-set name. A planted
    file does, by construction. So: load it, then ask the loaded module what
    file it came from, and reject any answer that is the API-set name itself.
    """
    if not hasattr(ctypes, "WinDLL"):  # pragma: no cover - non-Windows dev host
        return False

    # BASENAMES ONLY. Round 3 (CC-WS5-PKG-011) showed the comparison below is
    # trivially satisfiable if the caller passes a full path: it compared a
    # resolved BASENAME against the requested string, so
    # `C:\planted\api-ms-win-fake.dll` was "not equal to" its own basename and
    # the function happily called the planted file a real contract. Rejecting
    # non-basename input closes that by making the two sides comparable by
    # construction, rather than by hoping callers pass the right shape.
    if any(sep in name for sep in ("\\", "/", ":")):
        return False
    # An embedded NUL makes ctypes raise ValueError rather than return, which
    # turned malformed input into a crash instead of a "no" (round 4,
    # CC-WS5-PKG-011). A predicate asked "is this a real OS contract?" should
    # answer False for nonsense, not propagate an exception to its caller.
    if "\x00" in name or not name:
        return False
    # THE COMPLETE GRAMMAR, before the loader is ever consulted (round 5,
    # CC-WS5-PKG-011). The loader happily FORWARDS malformed variants --
    # `api-ms-win-crt-heap-l1-1-0` (no suffix) and the same name ending in
    # `.exe` both resolve to ucrtbase.dll on a live Windows -- and forwarding
    # is not grammar. Answering "is this a real OS contract?" with the
    # loader's generosity produced false corroboration. An API-set contract
    # basename is: `api-` or `ext-`, hyphenated alphanumeric name parts, an
    # `-l<n>-<n>-<n>` version triplet, and a literal `.dll`. Nothing else,
    # case-insensitive (Windows module names are).
    if len(name) > 256 or _API_SET_NAME_GRAMMAR.fullmatch(name) is None:
        return False

    try:
        handle = ctypes.WinDLL(name)._handle
    except OSError:
        return False

    buffer = ctypes.create_unicode_buffer(32768)
    if not ctypes.windll.kernel32.GetModuleFileNameW(
        ctypes.c_void_p(handle), buffer, len(buffer)
    ):  # pragma: no cover - defensive; a loaded module always has a path
        return False

    # Compare BASENAME to BASENAME. Both sides are reduced the same way so the
    # comparison cannot be won by a difference in path shape.
    resolved = PurePosixPath(buffer.value.replace("\\", "/")).name.lower()
    requested = PurePosixPath(name.replace("\\", "/")).name.lower()
    # A real API set forwarded to a host DLL; a planted file resolved to itself.
    return resolved != requested


def is_system_dll(name: str) -> bool:
    """True if ``name`` is a Windows-provided DLL never shipped in the tree.

    API-set names are decided by the checked-in `API_SET_CONTRACTS` inventory
    and by nothing else. Two earlier designs were both wrong:

      r1: bare prefix match. `api-ms-win-civiccast-fake-l99-99-99.dll` was
          waved through as "the OS has it" and its real dependency silently
          dropped from the closure. Failed open on any invented name.
      r2: prefix match confirmed against the live loader. Narrower, but still
          wrong in two ways the auditor demonstrated and stated
          (CC-WS5-PKG-003, round 2). It was SPOOFABLE -- copying `z-1.dll` to
          a file named `api-ms-win-civiccast-fake-l99-99-99.dll` and adding
          that directory via `os.add_dll_directory` flipped the answer from
          False to True, because the loader was answering "can I find
          something by this name?", not "is this an OS API-set contract?".
          And it made a PACKAGING decision depend on BUILD-HOST STATE: this
          box is Windows 11 build 26200, while the supported floor is Windows
          10 1809, so a newer host could quietly exempt a contract the target
          does not have.

    The inventory is deny-by-default and host-independent: an API-set name
    that is not in it is NOT treated as OS-provided, so a new contract halts
    the build and gets reviewed against the supported floor instead of being
    absorbed by whatever the build machine happens to be running.
    """
    lowered = name.lower()
    if lowered in SYSTEM_DLL_ALLOWLIST:
        return True
    if lowered.startswith(_SYSTEM_DLL_PREFIXES):
        return lowered in API_SET_CONTRACTS
    return False


def is_host_runtime_dll(name: str) -> bool:
    """True if ``name`` is supplied by the CivicCast Python runtime.

    Kept separate from `is_system_dll` so the two dependency stories stay
    distinguishable: one says "Windows provides this", the other says "our
    installer must provide this next to the tree". See HOST_RUNTIME_DLL_NAMES /
    HOST_PYTHON_REQUIREMENT.

    An EXACT set, not a `python3` prefix. The prefix version failed open the
    same way the API-set one did -- `python3-civiccast-fake.dll` was accepted as
    interpreter-provided (Codex r1 finding CC-WS5-PKG-003, Critical). The pinned
    interpreter can only ever present these two names, so anything else is an
    unknown dependency and must fail loud.
    """
    return name.lower() in HOST_RUNTIME_DLL_NAMES


# ---------------------------------------------------------------------------
# Step 1 -- stage the pinned upstream wheels
# ---------------------------------------------------------------------------


def stage_upstream_wheels(requirements_file: Path, stage: Path) -> None:
    """Install the pinned upstream wheels into ``stage``, isolated from this
    machine's installed packages (spec D1).

    Refuses before spawning a subprocess if the lockfile is missing or
    carries no `--hash` lines: an unauthenticated upstream input is exactly
    the gap D1 exists to close.
    """
    if not requirements_file.is_file():
        raise RuntimeError(f"refusing to stage upstream wheels: {requirements_file} does not exist")
    text = requirements_file.read_text(encoding="utf-8")
    if "--hash=" not in text:
        raise RuntimeError(
            f"refusing to stage upstream wheels: {requirements_file} has no --hash "
            "lines (spec D1 requires every upstream artifact pinned by hash before "
            "anything derives from it)"
        )
    stage.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--no-deps",
            "--require-hashes",
            "--target",
            str(stage),
            "-r",
            str(requirements_file),
        ],
        check=True,
    )


# ---------------------------------------------------------------------------
# Step 2 -- file -> owning-distribution index (RECORD parser)
# ---------------------------------------------------------------------------


def _distribution_name(dist_info_dirname: str) -> str:
    """ "gstreamer_plugins_gpl-1.28.5.dist-info" -> "gstreamer_plugins_gpl"."""
    stem = dist_info_dirname.removesuffix(".dist-info")
    name, _sep, _version = stem.rpartition("-")
    return name or stem


def build_distribution_index(stage: Path) -> dict[str, str]:
    """Map every staged file (forward-slash path relative to ``stage``) to
    its owning distribution, by parsing each `*.dist-info/RECORD`.

    A dist-info directory with no RECORD is skipped rather than fatal --
    RECORD is optional per the wheel spec. A file that ends up in the
    packaged tree without a provenance entry surfaces downstream instead,
    at `hash_directory_tree` / `build_runtime_manifest`'s AC7 gate, where an
    unknown-provenance file is a hard build refusal.
    """
    index: dict[str, str] = {}
    for dist_info in sorted(stage.glob("*.dist-info")):
        distribution = _distribution_name(dist_info.name)
        record = dist_info / "RECORD"
        if not record.is_file():
            continue
        for line in record.read_text(encoding="utf-8", errors="replace").splitlines():
            field = line.split(",", 1)[0].strip()
            if not field:
                continue
            rel = PurePosixPath(field.replace("\\", "/")).as_posix()
            index[rel] = distribution
    return index


# ---------------------------------------------------------------------------
# Step 3 -- factory -> (plugin path, distribution) origins
# ---------------------------------------------------------------------------


def locate_plugin(stage: Path, plugin_filename: str) -> Path | None:
    """Find ``plugin_filename`` by basename anywhere under ``stage``.

    Never asks GStreamer what factories exist -- hardware-gated factories
    (Media Foundation, NVENC) register only on matching hardware, which
    would make the closure machine-dependent and break AC1's determinism
    requirement. Returns ``None``, not an exception, when the plugin is
    absent: an absent CONDITIONAL/ABSENCE_TOLERANT plugin is normal, and the
    caller decides what "required but absent" means.
    """
    matches = sorted(stage.rglob(plugin_filename))
    return matches[0] if matches else None


def build_origins(stage: Path, file_index: Mapping[str, str]) -> dict[str, tuple[str, str]]:
    """factory -> (plugin path relative to ``stage``, owning distribution),
    for every `FACTORY_PLUGIN` entry actually present in the staged tree."""
    origins: dict[str, tuple[str, str]] = {}
    for factory, plugin_filename in FACTORY_PLUGIN.items():
        found = locate_plugin(stage, plugin_filename)
        if found is None:
            continue
        rel = found.relative_to(stage).as_posix()
        origins[factory] = (rel, file_index.get(rel, "<unknown>"))
    return origins


# The only GStreamer command-line consumers shipped in the Windows closure.
# They are not developer conveniences: the installed runtime uses
# gst-discoverer as a concrete, independently executable validation target.
# Their exact wheel-relative paths and owner bind the consumer requirement to
# the reviewed `gstreamer-cli==1.28.5` lock input rather than to any executable
# that happens to be present in the staging directory.
CLI_CONSUMER_EXECUTABLES: Final[tuple[str, ...]] = (
    "gstreamer_cli/bin/gst-discoverer-1.0.exe",
    "gstreamer_cli/bin/gst-inspect-1.0.exe",
)
CLI_CONSUMER_DISTRIBUTION: Final[str] = "gstreamer_cli"


def cli_consumer_seeds(stage: Path, file_index: Mapping[str, str]) -> tuple[str, ...]:
    """Return the pinned gstreamer-cli PE consumers or fail closed.

    A consumer missing from the staged wheel, or one claimed by a different
    distribution, is a dependency-contract failure before PE walking begins.
    """
    seeds: list[str] = []
    for relative in CLI_CONSUMER_EXECUTABLES:
        path = stage / relative
        if not path.is_file():
            raise RuntimeError(f"required gstreamer_cli consumer is missing: {relative}")
        owner = file_index.get(relative)
        if owner != CLI_CONSUMER_DISTRIBUTION:
            raise RuntimeError(
                f"required gstreamer_cli consumer has unexpected distribution {owner!r}: {relative}"
            )
        seeds.append(relative)
    return tuple(seeds)


def non_factory_plugin_seeds(stage: Path) -> tuple[str, ...]:
    """Return `NON_FACTORY_PLUGINS` as stage-relative seeds, or fail closed.

    These plugins export no element factory, so the factory-driven selection
    can never reach them -- `gsttypefindfunctions.dll` is the one that bit
    us: the shipped tree could not typefind ANY media file (candidate run
    31205696163), which broke the shipped gst-discoverer and every
    decodebin auto-plug path. A named non-factory plugin missing from the
    staged tree is a dependency-contract failure, never a silent drop.
    """
    seeds: list[str] = []
    for plugin_filename in sorted(NON_FACTORY_PLUGINS):
        found = locate_plugin(stage, plugin_filename)
        if found is None:
            raise RuntimeError(
                f"required non-factory plugin is missing from the staged tree: {plugin_filename}"
            )
        seeds.append(found.relative_to(stage).as_posix())
    return tuple(seeds)


# ---------------------------------------------------------------------------
# Step 5 -- pefile-backed imports_of / resolve
# ---------------------------------------------------------------------------


def _pe_imports(path: Path) -> list[str]:
    """DLL names ``path`` imports, via `pefile`.

    Reads BOTH the ordinary import table and the DELAY-LOAD import table. A
    delay-loaded dependency is resolved on first use rather than at load time,
    so it is every bit as required as a normal import -- but it lives in a
    different data directory, and reading only the ordinary one would omit it
    from the closure silently. The tree would build, hash and verify perfectly
    and then fail on the operator's machine at the moment the feature was first
    used. No file in the current pinned wheel set uses delay-loading (checked),
    so this is closing the hole before it opens rather than fixing a live bug.

    A PE with neither directory (a resource-only DLL, for example) yields an
    empty list -- that is a legitimate leaf of the closure walk, not an error.
    """
    pe = pefile.PE(str(path), fast_load=True)
    try:
        pe.parse_data_directories(
            directories=[
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"],
            ]
        )
        names: list[str] = []
        for attribute in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT"):
            for entry in getattr(pe, attribute, None) or ():
                if entry.dll:
                    names.append(entry.dll.decode("ascii", errors="replace"))
        return names
    finally:
        pe.close()


def make_imports_of(stage: Path) -> Callable[[str], list[str]]:
    """Build the `imports_of` callable `resolve_pe_closure` needs.

    System-provided imports (the allowlist, plus every api-ms-win-*/
    ext-ms-win-* API-set name) are filtered out here rather than left for
    `resolve_pe_closure`'s ``system_allowlist`` parameter, because that
    parameter only matches exact names -- the api-ms-win-*/ext-ms-win-*
    families are unbounded and must be matched by prefix (`is_system_dll`).
    """

    def imports_of(rel_path: str) -> list[str]:
        names = _pe_imports(stage / rel_path)
        return [name for name in names if not is_system_dll(name) and not is_host_runtime_dll(name)]

    return imports_of


def build_dll_index(stage: Path) -> dict[str, Path]:
    """basename.lower() -> first matching path, for every `.dll`/`.pyd` in
    ``stage``. Backs the case-insensitive resolver `resolve_pe_closure`
    needs."""
    index: dict[str, Path] = {}
    for path in sorted(stage.rglob("*")):
        if path.is_file() and path.suffix.lower() in (".dll", ".pyd"):
            index.setdefault(path.name.lower(), path)
    return index


def make_resolver(dll_index: Mapping[str, Path], stage: Path) -> Callable[[str], str | None]:
    def resolve(name: str) -> str | None:
        found = dll_index.get(name.lower())
        if found is None:
            return None
        return found.relative_to(stage).as_posix()

    return resolve


# ---------------------------------------------------------------------------
# Step 6 -- copy the closure + non-PE resources into the output tree
# ---------------------------------------------------------------------------


def _dest_for_pe_file(stage_rel: str) -> str:
    """Map a stage-relative PE file to its SHARED CONTRACT destination.

    GStreamer plugin DLLs live under a directory literally named
    "gstreamer-1.0" in the upstream wheels; everything else the PE closure
    walk reaches (glib, core GStreamer libs, ffmpeg, openh264, ...) is a
    general native DLL and lands flat in bin/.
    """
    posix = PurePosixPath(stage_rel)
    parts = {part.lower() for part in posix.parts}
    if "gstreamer-1.0" in parts:
        return f"lib/gstreamer-1.0/{posix.name}"

    # PyGObject's C extension modules are PE files, so the closure walk reaches
    # them -- but they are ALSO copied as part of the gi package. Sending them
    # to bin/ like any other DLL shipped each one TWICE, and only the
    # python/gi/ copy is importable. Mirror the gi package copy's destination
    # exactly so the two writes coincide instead of duplicating.
    if posix.suffix.lower() == ".pyd":
        lowered = [part.lower() for part in posix.parts]
        if "gi" in lowered:
            gi_index = lowered.index("gi")
            return "python/" + "/".join(posix.parts[gi_index:])

    return f"bin/{posix.name}"


def _locate_gi_package(stage: Path) -> Path | None:
    """Find the PyGObject `gi` package root in the staged tree.

    Matched by directory name plus the presence of `__init__.py`, not by
    RECORD parsing, so the mechanism does not depend on how the
    `gstreamer-python` wheel happens to lay its data files out.
    """
    candidates = sorted(
        path for path in stage.rglob("gi") if path.is_dir() and (path / "__init__.py").is_file()
    )
    return candidates[0] if candidates else None


def _python_extension_seeds(stage: Path) -> tuple[str, ...]:
    """Stage-relative paths of the PyGObject C extension modules (`.pyd`).

    These are closure SEEDS in their own right (spec D2(c)), not payload that
    rides along with the plugin graph. `_gi.cp312-win_amd64.pyd` imports
    `girepository-1.0-1.dll`, which no GStreamer plugin references -- so a
    plugin-only seed set produces a tree that builds and hashes perfectly and
    then fails at `import gi` on the operator's machine.
    """
    gi_root = _locate_gi_package(stage)
    if gi_root is None:
        return ()
    return tuple(
        sorted(
            path.relative_to(stage).as_posix() for path in gi_root.rglob("*.pyd") if path.is_file()
        )
    )


#: Typelib basenames deliberately EXCLUDED from the shipped closure.
#:
#: The typelib copy above is a blanket `rglob("*.typelib")` -- it ships every
#: generated introspection file the staged wheels carry. Pruning a file must
#: therefore be an explicit exclusion here, NOT a bare deletion: a deleted file
#: is silently resurrected on the next rebuild because the rglob finds it again.
#:
#: DBus-1.0.typelib / DBusGLib-1.0.typelib are inert introspection metadata for
#: libdbus / dbus-glib, neither of whose backing DLLs ships anywhere in bin/ --
#: nothing this closure runs can load them. Both are dual-licensed
#: "AFL-2.1 OR GPL-2.0-or-later" upstream, so they are dead, GPL-adjacent bytes.
#: Owner-approved prune 2026-07-24 (Scott, conditional on the boss blast-radius
#: analysis, result SAFE) -- see
#: `.agent-runs/native-windows/ws5-installer/OWNER-DECISION-licensing-dispositions.md`.
#:
#: The AC4 tamper control targets Gst-1.0.typelib, which is deliberately NOT
#: here: pruning it would break that control.
EXCLUDED_TYPELIB_BASENAMES: Final[frozenset[str]] = frozenset(
    {"DBus-1.0.typelib", "DBusGLib-1.0.typelib"}
)


def _collect_typelibs(stage: Path) -> list[Path]:
    return sorted(
        path for path in stage.rglob("*.typelib") if path.name not in EXCLUDED_TYPELIB_BASENAMES
    )


def _collect_gio_modules(stage: Path) -> list[Path]:
    modules = []
    for path in stage.rglob("*.dll"):
        lowered_parts = [part.lower() for part in path.parts]
        if "gio" in lowered_parts and "modules" in lowered_parts:
            modules.append(path)
    return sorted(modules)


def _copy_one(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    copy2(src, dest)


def copy_closure_into_tree(
    stage: Path,
    out: Path,
    closure: Sequence[str],
    file_index: Mapping[str, str],
) -> dict[str, str]:
    """Copy every PE-closure file plus the non-PE resources (typelibs, gio
    modules, the `gi` python package) into ``out`` per the SHARED CONTRACT
    layout.

    Returns the output-relative-path -> distribution mapping that
    `hash_directory_tree` needs to build `runtime-manifest.json`.
    """
    distribution_of: dict[str, str] = {}

    for stage_rel in closure:
        dest_rel = _dest_for_pe_file(stage_rel)
        _copy_one(stage / stage_rel, out / dest_rel)
        distribution_of[dest_rel] = file_index.get(stage_rel, "<unknown>")

    for typelib in _collect_typelibs(stage):
        stage_rel = typelib.relative_to(stage).as_posix()
        dest_rel = f"lib/girepository-1.0/{typelib.name}"
        _copy_one(typelib, out / dest_rel)
        distribution_of[dest_rel] = file_index.get(stage_rel, "<unknown>")

    for module in _collect_gio_modules(stage):
        stage_rel = module.relative_to(stage).as_posix()
        dest_rel = f"lib/gio/modules/{module.name}"
        _copy_one(module, out / dest_rel)
        distribution_of[dest_rel] = file_index.get(stage_rel, "<unknown>")

    gi_root = _locate_gi_package(stage)
    if gi_root is not None:
        for src in sorted(path for path in gi_root.rglob("*") if path.is_file()):
            stage_rel = src.relative_to(stage).as_posix()
            dest_rel = f"python/gi/{src.relative_to(gi_root).as_posix()}"
            _copy_one(src, out / dest_rel)
            distribution_of[dest_rel] = file_index.get(stage_rel, "<unknown>")

    return distribution_of


# ---------------------------------------------------------------------------
# Step 6b -- upstream license notices (<out>/licenses/)
#
# Original fix for an earlier audit finding: the SHARED CONTRACT tree layout
# specifies <out>/licenses/ and nothing created it, so LGPL-licensed binaries
# shipped with no license notice alongside them. Empirically, none of the
# staged GStreamer wheels carry a license text file in their dist-info
# (verified below by `_dist_info_bundles_license_text` -- only `setuptools`,
# a build-time-only dependency that contributes zero files to the packaged
# tree, ships one). There is nothing in the WHEELS to copy, so this records
# what IS available there -- each distribution's own verbatim METADATA
# license declaration -- rather than fabricating license text or silently
# shipping nothing.
#
# That summary is deliberately NOT the required notice itself (Codex audit
# finding CC-WS5-PKG-004, Major): spec D3 requires the license TEXT to be
# bundled, and naming "LGPL-2.1-or-later" in a table is not a substitute for
# the LGPL-2.1-or-later text. Step 6c below (`write_license_texts`) closes
# that gap by bundling the actual canonical text for every license the tree
# actually ships, from `civiccast/native/license_texts/` -- committed repo
# data, not fetched over the network at build time.
# ---------------------------------------------------------------------------

#: The "distribution" name attributed to files this script authors itself
#: (currently only `licenses/README.md`) rather than copies from an
#: upstream wheel. Kept separate from any real upstream distribution name so
#: `civiccast.native.runtime_manifest.DISTRIBUTION_LICENSE` can map it to
#: this repository's own license (Apache-2.0, per every source file's SPDX
#: header) instead of misattributing CivicCast's own prose to an upstream
#: project's LGPL/MIT/BSD declaration.
LICENSE_NOTICES_DISTRIBUTION = "civiccast_license_notices"

_METADATA_NAME_RE = re.compile(r"^Name:\s*(.+)$", re.MULTILINE)
_METADATA_VERSION_RE = re.compile(r"^Version:\s*(.+)$", re.MULTILINE)
_METADATA_HOME_PAGE_RE = re.compile(r"^Home-page:\s*(.+)$", re.MULTILINE)
_METADATA_LICENSE_RE = re.compile(r"^License:\s*(.+)$", re.MULTILINE)
_METADATA_LICENSE_EXPRESSION_RE = re.compile(r"^License-Expression:\s*(.+)$", re.MULTILINE)
_METADATA_LICENSE_CLASSIFIER_RE = re.compile(r"^Classifier:\s*(License\s*::.+)$", re.MULTILINE)

#: Filename fragments (matched against a file's stem, case-insensitively)
#: that indicate a bundled license text file, covering both the flat
#: `LICENSE`/`COPYING`/`NOTICE` convention and the PEP 639
#: `*.dist-info/licenses/` subdirectory convention (observed in the staged
#: `setuptools` wheel).
_LICENSE_FILE_STEM_FRAGMENTS = ("license", "licence", "copying", "notice")


@dataclass(frozen=True)
class DistributionMetadata:
    """What a staged distribution's own `*.dist-info/METADATA` says about
    its license -- every field read verbatim, never inferred. A field that
    is ``None``/empty simply was not present in that distribution's
    METADATA; `render_distribution_license_notice` reports that honestly
    rather than treating a missing field as license text to fabricate."""

    name: str
    version: str
    home_page: str | None
    license_field: str | None
    license_expression_field: str | None
    license_classifiers: tuple[str, ...]
    has_bundled_license_file: bool


def _dist_info_bundles_license_text(dist_info: Path) -> bool:
    """True if ``dist_info`` (a `*.dist-info` directory) contains a license
    text file, flat or under a `licenses/` subdirectory.

    Checked empirically per distribution rather than assumed: the real
    staged tree has exactly one exception (`setuptools`, which is not part
    of the packaged output), so asserting "wheels never ship license text"
    as a blanket fact would be a claim this function cannot back up for a
    distribution it has not looked at.
    """
    for path in dist_info.rglob("*"):
        if not path.is_file():
            continue
        stem = path.stem.lower()
        if any(fragment in stem for fragment in _LICENSE_FILE_STEM_FRAGMENTS):
            return True
    return False


def parse_distribution_metadata(stage: Path) -> dict[str, DistributionMetadata]:
    """Parse every staged `*.dist-info/METADATA` for the fields a license
    notice needs.

    Reads all three places a wheel can declare its license -- the legacy
    `License:` header, the PEP 639 `License-Expression:` header, and
    `Classifier: License :: ...` lines -- because the staged distributions
    use different conventions (the GStreamer wheels use `License:`;
    `setuptools` uses `License-Expression:`), and reporting only one would
    silently drop the other's declaration.
    """
    result: dict[str, DistributionMetadata] = {}
    for dist_info in sorted(stage.glob("*.dist-info")):
        distribution = _distribution_name(dist_info.name)
        metadata_path = dist_info / "METADATA"
        if not metadata_path.is_file():
            continue
        text = metadata_path.read_text(encoding="utf-8", errors="replace")
        name_match = _METADATA_NAME_RE.search(text)
        version_match = _METADATA_VERSION_RE.search(text)
        home_page_match = _METADATA_HOME_PAGE_RE.search(text)
        license_match = _METADATA_LICENSE_RE.search(text)
        expression_match = _METADATA_LICENSE_EXPRESSION_RE.search(text)
        result[distribution] = DistributionMetadata(
            name=name_match.group(1).strip() if name_match else distribution,
            version=version_match.group(1).strip() if version_match else "<unknown>",
            home_page=home_page_match.group(1).strip() if home_page_match else None,
            license_field=license_match.group(1).strip() if license_match else None,
            license_expression_field=(
                expression_match.group(1).strip() if expression_match else None
            ),
            license_classifiers=tuple(_METADATA_LICENSE_CLASSIFIER_RE.findall(text)),
            has_bundled_license_file=_dist_info_bundles_license_text(dist_info),
        )
    return result


def render_distribution_license_notice(meta: DistributionMetadata) -> str:
    """Render the `<out>/licenses/<distribution>.txt` notice for one
    distribution: name, version, upstream project, and every license field
    its own METADATA declared, verbatim -- explicitly labelled as the
    upstream project's declaration, not a CivicCast determination (audit
    finding requirement), plus a plain statement of whether a bundled
    license text file was found."""
    declared: list[str] = []
    if meta.license_expression_field:
        declared.append(f"License-Expression: {meta.license_expression_field}")
    if meta.license_field:
        declared.append(f"License: {meta.license_field}")
    declared.extend(f"Classifier: {classifier}" for classifier in meta.license_classifiers)
    declared_block = (
        "\n".join(f"  {line}" for line in declared)
        if declared
        else "  (no License / License-Expression / Classifier: License field was present)"
    )

    bundled_note = (
        "This distribution's own wheel DOES bundle a license text file "
        "(found under its `*.dist-info/`); that file is the authoritative "
        "text, this notice is only a summary of the declared expression."
        if meta.has_bundled_license_file
        else "No bundled license text file was found in this distribution's "
        "own wheel (`*.dist-info/` contains no LICENSE/COPYING/NOTICE file "
        "and no `licenses/` subdirectory). That is a statement about the "
        "WHEEL, not about this tree: the canonical text for whichever "
        "specific license(s) this distribution's shipped files actually "
        "carry (see LICENSE-BOM.md for the per-file license) IS bundled "
        "elsewhere in this same tree, at `licenses/texts/<spdx-id>.txt` -- "
        "see README.md in this directory."
    )

    lines = [
        "CivicCast native runtime packaging closure -- upstream license notice",
        "=" * 72,
        "",
        f"Distribution:      {meta.name}",
        f"Version:           {meta.version}",
        f"Upstream project:  {meta.home_page or '<not declared in METADATA>'}",
        "",
        "Declared license, read verbatim from this distribution's own",
        "*.dist-info/METADATA. This is the upstream project's declaration,",
        "not a CivicCast determination:",
        "",
        declared_block,
        "",
        bundled_note,
        "",
    ]
    return "\n".join(lines)


def render_license_notices_readme(
    distributions: Sequence[str], metadata_by_distribution: Mapping[str, DistributionMetadata]
) -> str:
    """Render `<out>/licenses/README.md`: what this directory is, and, in
    plain language, what it is not -- per the audit finding, this must
    state where the full license texts must come from and that the
    metadata expression is the upstream declaration, not our determination.
    """
    without_text = sorted(
        d for d in distributions if not metadata_by_distribution[d].has_bundled_license_file
    )
    with_text = sorted(
        d for d in distributions if metadata_by_distribution[d].has_bundled_license_file
    )

    lines = [
        "# Upstream license notices",
        "",
        "This directory records, per staged upstream distribution that "
        "contributes at least one file to the packaged runtime tree, what "
        "this build actually found about that distribution's license: its "
        "name and version, and its declared SPDX-style license expression "
        "taken **verbatim** from that distribution's own "
        "`*.dist-info/METADATA` (`License`, `License-Expression`, and "
        "`Classifier: License :: ...` fields).",
        "",
        "## What this directory is NOT",
        "",
        "The license expression recorded in each `<distribution>.txt` file "
        "is the upstream project's own self-declaration in its wheel "
        "metadata. It is **not** a CivicCast determination of the file's "
        "actual governing license, and it is **not** a substitute for the "
        "full upstream license text.",
        "",
        "## What was found, empirically, in the staged wheels for this build",
        "",
    ]
    if without_text:
        lines.append(
            "No bundled license text file (no LICENSE/COPYING/NOTICE, no "
            "`licenses/` subdirectory) was found in the staged WHEEL for: "
            f"{', '.join(without_text)}."
        )
    if with_text:
        lines.append(
            "A bundled license text file WAS found in the staged wheel for: "
            f"{', '.join(with_text)}; that file, not this summary, is "
            "authoritative for those distributions."
        )
    lines.extend(
        [
            "",
            "## Where the full license texts actually are",
            "",
            "Regardless of what the wheels above bundle (or don't), the full "
            "canonical text for every distinct license this build's BOM "
            "actually contains IS bundled in this tree, at "
            "`licenses/texts/<spdx-id>.txt` -- one file per license, sourced "
            "from `civiccast/native/license_texts/` in the CivicCast "
            "repository (committed, version-controlled data, never fetched "
            "over the network at build time) and copied in by "
            "`scripts/build_native_runtime_closure.py`'s `write_license_"
            "texts` step. See LICENSE-BOM.md for exactly which license "
            "governs which shipped file, and `licenses/texts/` for that "
            "license's full text. The one exception is `LicenseRef-"
            "Microsoft-VCRedist.txt`, which explicitly records that its "
            "text is proprietary and not reproducible here, with a pointer "
            "to Microsoft's own published terms, rather than shipping "
            "silently with nothing.",
            "",
            "## Files in this directory",
            "",
            "One `<distribution>.txt` file per staged distribution that "
            "contributes at least one file to the packaged tree, this "
            "README, and a `texts/` subdirectory holding the actual license "
            "text for every license the tree ships. All three are generated "
            "by `scripts/build_native_runtime_closure.py` on every build; "
            "hand edits here do not survive the next build.",
            "",
        ]
    )
    return "\n".join(lines)


def write_license_notices(stage: Path, out: Path, distributions: Sequence[str]) -> dict[str, str]:
    """Write `<out>/licenses/`: one `<distribution>.txt` notice per entry in
    ``distributions`` plus a README.md, and return the
    output-relative-path -> distribution mapping so the caller can fold it
    into `distribution_of`.

    These files are part of the tree, so they must be covered by
    `runtime-manifest.json`/`SHA256SUMS` like everything else -- returning
    the mapping (rather than writing the files as an untracked side effect)
    is what lets `hash_directory_tree` see them.

    Raises `RuntimeError` naming the distribution if ``distributions``
    contains a name with no staged `*.dist-info/METADATA` -- silently
    skipping it would ship an LGPL binary with no notice at all, exactly
    the gap this function exists to close.
    """
    metadata_by_distribution = parse_distribution_metadata(stage)
    licenses_dir = out / "licenses"
    licenses_dir.mkdir(parents=True, exist_ok=True)

    distribution_of: dict[str, str] = {}
    for distribution in sorted(distributions):
        meta = metadata_by_distribution.get(distribution)
        if meta is None:
            raise RuntimeError(
                f"refusing to write a license notice for {distribution!r}: no "
                "*.dist-info/METADATA was found for it in the staged tree"
            )
        dest_rel = f"licenses/{distribution}.txt"
        (out / dest_rel).write_text(render_distribution_license_notice(meta), encoding="utf-8")
        distribution_of[dest_rel] = distribution

    readme_rel = "licenses/README.md"
    (out / readme_rel).write_text(
        render_license_notices_readme(sorted(distributions), metadata_by_distribution),
        encoding="utf-8",
    )
    distribution_of[readme_rel] = LICENSE_NOTICES_DISTRIBUTION

    return distribution_of


# ---------------------------------------------------------------------------
# Step 6c -- bundled license TEXTS (<out>/licenses/texts/)
#
# Fix for Codex audit finding CC-WS5-PKG-004 (Major): spec D3 requires
# required NOTICES to be BUNDLED with the runtime -- LGPL-2.1-or-later and
# MPL-2.0 in particular REQUIRE the license text itself to accompany the
# binaries, and the per-distribution SUMMARY written above (a distribution's
# own declared SPDX expression) is not a substitute for that text.
#
# The text files themselves live in `civiccast/native/license_texts/` as
# committed repo data (see that package's module doc for sourcing/
# provenance) -- never fetched over the network at build time, so a build
# never depends on the network to be legally complete.
# ---------------------------------------------------------------------------

#: The "distribution" attributed to the bundled `licenses/texts/*.txt`
#: files. A distinct name from `LICENSE_NOTICES_DISTRIBUTION` (rather than
#: reusing it) so `LICENSE-BOM.md`'s per-distribution summary keeps "the
#: README we wrote" and "the license texts we bundled" separately
#: countable, even though both currently resolve to the same governing
#: license (Apache-2.0, via `classify_shipped_file`'s `licenses/` path-
#: prefix rule -- these are CivicCast's own committed copies, not upstream
#: wheel content, so AC7's per-file gate is satisfied independent of this
#: distribution name).
LICENSE_TEXTS_DISTRIBUTION = "civiccast_license_texts"


def resolve_shipped_licenses(distribution_of: Mapping[str, str]) -> tuple[str, ...]:
    """The distinct, sorted SPDX license identifiers actually present in
    the tree so far, derived from ``distribution_of``'s own paths via
    `classify_shipped_file` -- never a fixed list hardcoded in this script.

    Deliberately NOT sourced from a static "these are the licenses we
    support" table: a future upstream change that introduces a new license
    into the shipped BOM must show up here automatically, so
    `write_license_texts` can refuse the build instead of shipping that new
    license with no bundled text (exactly the CC-WS5-PKG-004 gap this pair
    of functions closes).

    A path `classify_shipped_file` cannot resolve is silently excluded here
    (never surfaced as a phantom `None` license) -- `hash_directory_tree`'s
    own AC7 gate is what turns an unresolved shipped file into a build
    failure; this function's only job is deriving the license SET for
    already-classifiable paths.

    Returns individual license IDENTIFIERS, not raw expressions: a file whose
    license is a cumulative expression (fontconfig 2.16.1's
    `"HPND-sell-variant AND MIT AND ..."`) obliges the tree to bundle a text
    for EVERY component. Treating the expression as one opaque key would ship
    four of fontconfig's five notices missing while the BOM string stayed
    perfectly accurate -- an omission with nothing to give it away.
    """
    licenses: set[str] = set()
    for path in distribution_of:
        license_ = classify_shipped_file(path)
        if license_ is not None:
            licenses.update(license_identifiers_in(license_))
    return tuple(sorted(licenses))


def write_license_texts(out: Path, licenses: Sequence[str]) -> dict[str, str]:
    """Copy the canonical text for every entry in ``licenses`` into
    `<out>/licenses/texts/`, from the committed, version-controlled
    `civiccast.native.license_texts` package.

    Returns the output-relative-path -> distribution mapping so the caller
    can fold it into `distribution_of`, same as `write_license_notices` --
    these files are part of the tree and must be covered by
    `runtime-manifest.json`/`SHA256SUMS` like everything else.

    Raises `RuntimeError` naming every license with no available bundled
    text. ``licenses`` is DERIVED from what the tree actually ships (see
    `resolve_shipped_licenses`), not a fixed list, so a future license
    appearing in the BOM with nothing to copy for it must halt the build --
    shipping it with a BOM entry and no text is precisely the gap
    CC-WS5-PKG-004 identified. Refuses before writing anything on a partial
    match, so a caller never ends up with a `texts/` directory holding only
    the licenses that happened to resolve before the missing one was hit.
    """
    # Integrity BEFORE selection: confirm every bundled text still matches the
    # immutable upstream it was pinned to. Without this the builder would
    # faithfully hash and manifest an altered license text -- the trust
    # artifacts would be internally consistent and legally wrong, which is the
    # worst of both (CC-WS5-PKG-004 round 2).
    verify_bundled_license_texts()

    available = available_license_texts()
    missing = sorted(license_ for license_ in licenses if license_ not in available)
    if missing:
        raise RuntimeError(
            "refusing to ship a runtime tree with no bundled license text for: "
            f"{', '.join(missing)} (spec-packaging-closure D3 requires required "
            "notices to be bundled; add "
            "civiccast/native/license_texts/<spdx-id>.txt for each, sourced "
            "from an authoritative upstream such as spdx.org/licenses or the "
            "project's own COPYING file, before this build can proceed)"
        )

    distribution_of: dict[str, str] = {}
    for license_ in licenses:
        src = available[license_]
        dest_rel = f"licenses/texts/{src.name}"
        _copy_one(src, out / dest_rel)
        distribution_of[dest_rel] = LICENSE_TEXTS_DISTRIBUTION

    return distribution_of


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _gstreamer_version() -> str:
    text = REQUIREMENTS_FILE.read_text(encoding="utf-8")
    match = _GSTREAMER_VERSION_RE.search(text)
    if match is None:
        raise RuntimeError(
            f"could not determine the pinned GStreamer version from {REQUIREMENTS_FILE}"
        )
    return match.group(1)


def build(*, stage: Path, out: Path, requirements: Path | None = None) -> dict[str, object]:
    """Run the full closure build. Returns the written `runtime-manifest.json`
    document (already the real, final numbers -- AC8).

    ``requirements`` overrides the pinned lock. It exists so the AC3 GPL
    negative control can be run end to end against a deliberately poisoned
    lockfile WITHOUT editing the repo's real one -- a negative control that
    requires mutating the artifact under test is a negative control nobody runs.
    """
    lock = requirements.resolve() if requirements is not None else REQUIREMENTS_FILE
    print(f"Staging pinned upstream wheels into {stage} ...")
    stage_upstream_wheels(lock, stage)

    print("Indexing staged distributions from *.dist-info/RECORD ...")
    file_index = build_distribution_index(stage)
    distributions = sorted(set(file_index.values()))
    print(f"  {len(file_index)} files indexed across {len(distributions)} distribution(s)")

    # Input-boundary GPL gate (AC3). Deliberately BEFORE any selection: a GPL
    # distribution that merely got staged is already a broken input contract,
    # even if nothing from it would have been chosen.
    assert_no_gpl_distributions(distributions)

    # ...and deny-by-default for everything else. The GPL gate above only
    # recognises distributions we already knew to forbid; this refuses anything
    # we did not explicitly authorise. Round 2 of the audit walked
    # `civiccast-unknown-runtime` through the old denylist-only design and had
    # it contribute a plugin, which is the case that actually matters: a
    # renamed, replaced or injected distribution is by construction absent from
    # any denylist.
    assert_authorized_distributions(distributions)

    print("Locating named plugins in the staged tree ...")
    origins = build_origins(stage, file_index)
    print(f"  {len(origins)}/{len(FACTORY_PLUGIN)} named factories resolved to a staged plugin")

    optional_present = {
        factory
        for factory in (CONDITIONAL_FACTORIES | ABSENCE_TOLERANT_FACTORIES)
        if factory in origins
    }
    required = REQUIRED_FACTORIES | optional_present
    seeds = select_plugin_seeds(origins, required=required)
    print(f"  {len(seeds)} seed plugin file(s) selected")

    # spec-packaging-closure D2(c): Python native modules are part of the
    # closure, not an afterthought. Seeding only plugins is not enough -- the
    # PyGObject extension modules pull in libraries NO plugin imports
    # (girepository-1.0-1.dll is the one that bit us: the tree built clean,
    # then `import gi` died with "DLL load failed while importing _gi" because
    # nothing in the plugin graph referenced it). Caught by the first real D6
    # run against a built tree.
    pyd_seeds = _python_extension_seeds(stage)
    if pyd_seeds:
        print(f"  {len(pyd_seeds)} Python extension module(s) added as closure seeds")
    consumer_seeds = cli_consumer_seeds(stage, file_index)
    print(
        f"  {len(consumer_seeds)} pinned gstreamer-cli consumer executable(s) added as closure seeds"
    )
    typefind_seeds = non_factory_plugin_seeds(stage)
    print(f"  {len(typefind_seeds)} non-factory plugin(s) added as closure seeds (typefinders)")
    seeds = tuple(sorted({*seeds, *pyd_seeds, *consumer_seeds, *typefind_seeds}))

    print("Walking the PE import closure ...")
    dll_index = build_dll_index(stage)
    closure = resolve_pe_closure(
        seeds,
        imports_of=make_imports_of(stage),
        resolve=make_resolver(dll_index, stage),
        system_allowlist=SYSTEM_DLL_ALLOWLIST,
    )
    print(f"  {len(closure)} PE file(s) in the closure")

    if out.exists() and any(out.iterdir()):
        raise RuntimeError(f"refusing to build into a non-empty output directory: {out}")
    out.mkdir(parents=True, exist_ok=True)

    print(f"Copying the closure and non-PE resources into {out} ...")
    distribution_of = copy_closure_into_tree(stage, out, closure, file_index)

    # Audit finding fix: <out>/licenses/ is part of the SHARED CONTRACT tree
    # layout and must exist -- one upstream license notice per distribution
    # that actually contributed a shipped file (never per every staged
    # distribution: e.g. `setuptools` is staged but contributes zero files
    # to `distribution_of`, so it has no binaries here that need a notice).
    shipped_distributions = sorted({d for d in distribution_of.values() if d != "<unknown>"})
    print(f"Writing upstream license notices for {len(shipped_distributions)} distribution(s) ...")
    distribution_of.update(write_license_notices(stage, out, shipped_distributions))

    # CC-WS5-PKG-004 fix: bundle the actual TEXT for every license the tree
    # ships (D3), derived from what is actually in the tree so far -- never a
    # fixed list -- so a future new license with no text added for it halts
    # the build instead of shipping silently.
    shipped_licenses = resolve_shipped_licenses(distribution_of)
    print(f"Bundling license text for {len(shipped_licenses)} distinct license(s) ...")
    distribution_of.update(write_license_texts(out, shipped_licenses))

    print("Hashing the packaged tree and building trust artifacts ...")
    entries = hash_directory_tree(out, distribution_of=distribution_of)
    lock_sha256 = hashlib.sha256(lock.read_bytes()).hexdigest()
    manifest = build_runtime_manifest(
        entries, gstreamer_version=_gstreamer_version(), lock_sha256=lock_sha256
    )
    (out / "runtime-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    (out / "SHA256SUMS").write_text(render_sha256sums(entries), encoding="utf-8")
    (out / "LICENSE-BOM.md").write_text(render_license_bom(entries), encoding="utf-8")

    print("Build complete.")
    print(f"  file_count  = {manifest['file_count']}")
    print(f"  total_bytes = {manifest['total_bytes']}")
    return manifest


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the native Windows runtime packaging closure."
    )
    parser.add_argument("--out", required=True, type=Path, help="output tree directory")
    parser.add_argument(
        "--requirements",
        type=Path,
        default=None,
        help=(
            "override the pinned lockfile (default: requirements-native-runtime.txt). "
            "Used by the AC3 GPL negative control so it can run against a poisoned "
            "lock without editing the real one."
        ),
    )
    parser.add_argument(
        "--stage",
        type=Path,
        default=None,
        help="scratch directory to stage upstream wheels into (default: a temp dir)",
    )
    parser.add_argument(
        "--keep-stage",
        action="store_true",
        help="do not delete the auto-created temp stage directory after the build",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    out = args.out.resolve()

    if args.stage is not None:
        stage = args.stage.resolve()
        stage.mkdir(parents=True, exist_ok=True)
        build(stage=stage, out=out, requirements=args.requirements)
        return 0

    stage = Path(mkdtemp(prefix="cc-native-stage-"))
    try:
        build(stage=stage, out=out, requirements=args.requirements)
    finally:
        if not args.keep_stage:
            rmtree(stage, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
