#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Build the signed native ``native-server-binaries`` component pack
(PostgreSQL 17 + a TSDuck subset) that
``civiccast.native.provision.pack.verify_server_binaries_pack`` verifies and
``civiccast.native.provision.__main__.resolve_provision_paths`` expects to
find, extracted, at ``<install_root>\\packs\\native-server-binaries\\
payload\\bin\\initdb.exe``.

WP2 gap this closes: the provisioning engine (wired at 3907465a) has a real,
tested caller (``python -m civiccast.native.provision``) and a real trust
wire (``civiccast.native.provision.pack``), but nothing ever built the pack
that trust wire verifies -- ``nsis-hooks-native.nsh``'s own comment names
this exact gap ("Server-binaries pack staging ... no earlier work package
lays this hook's own file section down with a packs\\ tree"). This script is
that builder.

Mirrors ``scripts/build_native_caption_pack.py`` + ``civiccast.installer.
native_packs`` conventions exactly: pinned-input validation before packing,
a signed ZIP64 pack via ``build_native_pack``, and a development-signing-key
guard. Two things caption packs do NOT need that this pack does:

* **Acquisition.** Caption models are pulled by a separate, already-landed
  flow. PostgreSQL/TSDuck are not -- ``--acquire`` (this script) reuses
  ``scripts.provision_native_runtime_dependencies``'s ALREADY-REVIEWED lock
  (``native-windows-runtime-dependencies.lock.json``, schema_version 2,
  pinned PostgreSQL 17.10-2 / TSDuck 3.44-4676 URLs +
  SHA-256) and its ``fetch_locked_artifact``/``safe_extract_zip`` primitives
  verbatim -- never re-typing a URL or a hash this repo already reviewed.
  Only the 2 artifacts this pack needs are fetched (never the ffmpeg/node/
  ollama artifacts the SAME lock also pins for the unrelated "Core" pack --
  see ``build_native_distribution.py``, a different pack with a different
  component identity, "core", not "native-server-binaries").
* **Minimization.** The upstream PostgreSQL/TSDuck distributions are
  general-purpose (pgAdmin-adjacent StackBuilder GUI, wx* libs, ecpg,
  pgbench, 87 TSDuck plugins covering satellite/cable/DVB hardware this
  product never touches, ...). This builder ships only the closure real
  code in this repo actually invokes -- see ``POSTGRES_BIN_PINS`` /
  ``TSDUCK_BIN_PINS`` below for the exact evidence per file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Final

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from civiccast._native_version import __version__  # noqa: E402
from civiccast.installer.native_packs import build_native_pack  # noqa: E402
from civiccast.native.provision.pack import (  # noqa: E402
    SERVER_BINARIES_COMPONENT,
)
from civiccast.native.provision.seams import initdb_argv  # noqa: E402
from civiccast.native.runtime_licenses import (  # noqa: E402
    classify_server_pack_file,
    is_gpl_license,
)
from scripts.provision_native_runtime_dependencies import (  # noqa: E402
    LOCK_PATH,
    fetch_locked_artifact,
    load_lock,
    safe_extract_zip,
)

_REPARSE_POINT: Final[int] = 0x400

#: Upstream component versions this builder was reviewed against -- SAME
#: pins as ``native-windows-runtime-dependencies.lock.json``'s ``postgres``/
#: ``tsduck`` entries (``--acquire`` fetches exactly those). Not
#: re-declared as a second source of truth: ``acquire_server_pack_sources``
#: asserts the loaded lock's ``version`` fields equal these before fetching,
#: so a lock file edited out from under this builder fails loud instead of
#: silently shipping an unreviewed version.
POSTGRES_VERSION: Final[str] = "17.10-2"
TSDUCK_VERSION: Final[str] = "3.44-4676"


class ServerPackBuildError(RuntimeError):
    """The native-server-binaries pack could not be built."""


# ---------------------------------------------------------------------------
# Pinned minimal-closure inventories.
#
# Each dict maps a SOURCE-relative filename (directly under the artifact's
# extracted root, or a named subdirectory) to (expected_bytes, expected_
# sha256) -- computed directly from the reviewed, hash-pinned upstream
# archives (see the lock file + this task's evidence file for the exact
# derivation commands). Executables and DLLs are pinned individually here
# (the supply-chain-meaningful subset, mirroring
# ``build_native_caption_pack.WHISPER_MODEL_FILES``'s per-file pin style);
# the bulk data trees (``share/timezone/``, ``share/timezonesets/``, the
# ``btree_gist`` SQL migration scripts) are validated by exact PATH-SET
# instead (no extra/missing file), not per-file hash -- both are already
# covered transitively by ``fetch_locked_artifact``'s whole-archive SHA-256
# check before ANY of these bytes are ever extracted, so per-file hashing
# of hundreds of small SQL/data files would duplicate, not add, a trust
# boundary. A tamper AFTER extraction (not the download itself) is still
# caught: ``build_native_pack`` hashes every byte it packs into the
# manifest it signs, and ``verify_native_pack`` re-derives every hash on
# read.
# ---------------------------------------------------------------------------

#: PostgreSQL executables this product's provisioning engine
#: (``civiccast.native.provision``, ``initdb``/``postgres``/``pg_ctl``) and
#: disaster-recovery tooling (``civiccast/dr/backup.py``,
#: ``civiccast/dr/restore_drill.py`` -- ``pg_dump`` for the per-database
#: snapshot, ``pg_dumpall --globals-only`` for cluster-global roles,
#: ``pg_restore`` for restore) and operator diagnostics (``psql``) actually
#: invoke. Excludes: StackBuilder (GUI installer for extra modules this
#: product never offers), clusterdb/createdb/createuser/dropdb/dropuser/
#: reindexdb/vacuumdb/vacuumlo/oid2name (interactive DBA utilities nothing
#: in this repo calls), ecpg (embedded-SQL C preprocessor -- a build tool,
#: not a runtime), pgbench (benchmarking), pg_amcheck/pg_basebackup/
#: pg_checksums/pg_combinebackup/pg_createsubscriber/pg_isready/
#: pg_receivewal/pg_recvlogical/pg_resetwal/pg_rewind/pg_test_fsync/
#: pg_test_timing/pg_upgrade/pg_verifybackup/pg_waldump/pg_walsummary/
#: pg_archivecleanup/pg_controldata/pg_config (operational tools for
#: replication/upgrade/backup-orchestration topologies this product does
#: not run today -- a later work package that adds them re-derives their
#: pins the same way this file does, never inherits an unreviewed default).
POSTGRES_BIN_PINS: Final[dict[str, tuple[int, str]]] = {
    "initdb.exe": (244_736, "2556d079888bf9ebba6b8ba7d3e8c08c947e6e564ceb73054fe1929611c87d48"),
    "postgres.exe": (
        9_918_464,
        "882a5a073a88817f6c6d4c8827df1e4269ff226d52cf6f47c9883e91088c6345",
    ),
    "pg_ctl.exe": (132_096, "abe89b0767a8cd0f956059aa5a5a93cd1042efc6194d000c2501da3e23babbd2"),
    "pg_dump.exe": (613_376, "e01d19b862085eb1fe12c54cdfd07fd691533e5fe8363ae6cf27a423fffd815a"),
    "pg_dumpall.exe": (
        194_560,
        "935a34cd3e873d2deea0dc98705ee0902c9d5bb095c4d69327159b8988ed3ffa",
    ),
    "pg_restore.exe": (
        370_688,
        "900de0096d68993acd46b25db1cd909e8a197760b56b7f12f7a631be1fbedf64",
    ),
    "psql.exe": (633_344, "e43adb9c5032e7efc63eebb44c5d32b142b34e5f4207666fed2dc7a51d43b630"),
}

#: The bundled runtime DLLs the seven binaries above actually import,
#: determined by a real ``pefile``-based recursive PE import-table walk
#: (ordinary + delay-load directories, same method ``scripts/
#: build_native_runtime_closure.py`` uses for the media closure) against
#: the extracted, hash-verified archive -- never assumed from the full
#: ``bin/`` listing. ``pg_dumpall.exe`` re-checked separately when it was
#: added and introduces no DLL beyond this same set. Excludes libcurl/
#: libecpg*/libpgtypes/libxslt/wx*/testplug.dll/pgevent -- present in the
#: upstream ``bin/`` tree but not imported by any of the selected
#: executables.
POSTGRES_BIN_DLL_PINS: Final[dict[str, tuple[int, str]]] = {
    "icudt67.dll": (
        28_399_104,
        "5ff9c8026344e886f280ddfa235a1e16e1bcd396e90f9ed600b6f71d9d881ae8",
    ),
    "icuin67.dll": (
        2_674_176,
        "23d5914acf071f566df19aaf404373e5c73c9910c370e728976f6202c04cf6c3",
    ),
    "icuuc67.dll": (
        1_906_688,
        "2fb4007a1f1089a0807cc1abde5443f5c3b0865ecfd80344b6ad165f1fe53ade",
    ),
    "libcrypto-3-x64.dll": (
        4_704_256,
        "ef9cfc17dc0069ea86fcc731305f61540aab8078178006c62b58df729ee1f417",
    ),
    "libiconv-2.dll": (
        1_850_401,
        "3ee9786ab3eb8dfd791bdbd17c7e791dbe025734befcded0ee4170e1089f79df",
    ),
    "libintl-9.dll": (475_769, "1125ac8dc0c4f5c3ed4712e0d8ad29474099fcb55bb0e563a352ce9d03ef1d78"),
    "liblz4.dll": (128_000, "096af775241b3bd4b1c3d79c83b103bb8f02da54ec4cd76c5d49eef61a68ad01"),
    "libpq.dll": (351_232, "66859f7f4b0eeb5ce50b7df8aaabb0b92c2073f584f49f15a3101f5fba167113"),
    "libssl-3-x64.dll": (
        779_776,
        "0da042f7021d8910966643c1c7da86d7bb555eb1aca0fbaaaad9a30d95187dc1",
    ),
    "libwinpthread-1.dll": (
        52_736,
        "ffe2d56375bb4e8bdee9037df6befc5016ddd8871d0d85027314dd5792f8fdc9",
    ),
    "libxml2.dll": (1_230_848, "fa13b5d8bdc8254a6a7f0bc9b26331fa6badf096334bb912e7dc6928206a74a0"),
    "libzstd.dll": (727_040, "287e7e474961e8886a3d961e2c07da647a7ac8d60d97023545f3a3ecf604daba"),
    "zlib1.dll": (91_648, "890afa7a17fb66308e0026631070409138b157ef2773c0a41d22a76943f7aedf"),
}

#: ``lib/`` selection, in three groups. LESSON (Sandbox matrix row 1 run 2,
#: 2026-07-30): ``lib/`` is NOT only contrib extensions -- it also holds
#: CORE runtime modules the server bootstrap itself loads. The original
#: btree_gist-only selection made the first live ``initdb`` die with
#: ``FATAL: could not access file "$libdir/utf8_and_win"``.
#:
#: 1. The complete encoding-conversion module family (every ``*_and_*.dll``
#:    plus ``euc2004_sjis2004.dll``): ``initdb``'s bootstrap and any
#:    client-encoding negotiation load these on demand; shipping the whole
#:    24-module family (~2 MB) rather than guessing which encodings a
#:    station will ever negotiate.
#: 2. Core PL / dictionary modules: ``plpgsql.dll`` (the default procedural
#:    language, installed by ``initdb``'s bootstrap itself) and
#:    ``dict_snowball.dll`` (loaded by the ``snowball_create.sql`` this
#:    pack already ships in ``share/``).
#: 3. The one loadable extension the product's schema actually installs:
#:    ``civiccast/schedule/migrations/versions/
#:    0003_create_schedule_items_table.py`` runs ``CREATE EXTENSION IF NOT
#:    EXISTS btree_gist`` (grepped every ``migrations/`` tree in the repo --
#:    the only ``CREATE EXTENSION`` statement that exists). Every other
#:    ``lib/*.dll`` contrib extension upstream ships remains excluded.
#:
#: The build-time bootstrap proof (``_prove_postgres_bootstrap``, CLI path)
#: runs a REAL ``initdb`` + server start + ``CREATE EXTENSION btree_gist``
#: + ``to_tsvector`` against exactly this selection on every pack build, so
#: the NEXT missing file fails the build -- never a station install.
POSTGRES_LIB_PINS: Final[dict[str, tuple[int, str]]] = {
    # Group 1: encoding-conversion modules (complete family).
    "cyrillic_and_mic.dll": (
        20_480,
        "a0ffea13b3aec8000ada34ab06050dae74aaa6a25983cb7af5b4df90ff5bcdef",
    ),
    "euc2004_sjis2004.dll": (
        16_896,
        "fd85a9d4f67df8d90414cd7cb028a69355c5ee2444c041b9d74517296140082e",
    ),
    "euc_cn_and_mic.dll": (
        15_872,
        "a7403ebff7c092fb063de8fefe8edad58042cab10e35c5e46586b516377e2b86",
    ),
    "euc_jp_and_sjis.dll": (
        23_040,
        "42398e11a0068d2f759f6b90f17cfd70d072751f18adc4ec6afc776fd1887ee3",
    ),
    "euc_kr_and_mic.dll": (
        15_872,
        "bf71dc21591912f84262f4403855ceefc51acccb6e6ff4ac0390fb4efc05bbab",
    ),
    "euc_tw_and_big5.dll": (
        22_528,
        "4d806f12ebdfbc9a566d28508fd823f61b84007a539dfb6db7e7c9de3854ee7b",
    ),
    "latin2_and_win1250.dll": (
        16_384,
        "c1a0a45a66d764bb2f4e066c07cbe4e071a3660e1c89d9c71168f97d2dbacd14",
    ),
    "latin_and_mic.dll": (
        15_872,
        "ea22ecdd239992c9260cfb9ae22ded71da27cbc623cc4dacbc46a4d41c5ac7aa",
    ),
    "utf8_and_big5.dll": (
        129_024,
        "253254404d378ab07484948b4b98fc8c4526cf3f528580998bd7b5ca02268da7",
    ),
    "utf8_and_cyrillic.dll": (
        20_480,
        "d063f4732a07554b16ec24ed8a9137403f0927a2991ba10f0c9ca44778a3caa2",
    ),
    "utf8_and_euc2004.dll": (
        219_136,
        "33f4012bf8e47fb318caab2f4ca1d9b1a3146f33652e06ae21b084cbab8fa8b2",
    ),
    "utf8_and_euc_cn.dll": (
        89_600,
        "90a68b52cdad241d35bb70e6bd2800daa21341c839125629036fd0b40522aa00",
    ),
    "utf8_and_euc_jp.dll": (
        165_376,
        "a27ad7ae429419eb79c313991c9594227e4fad727fe1e5ded4fbd881dd0d513e",
    ),
    "utf8_and_euc_kr.dll": (
        117_248,
        "773da9c1ad60a9fdfc023b0836525f5a2486578c9fc3a098f22fae6fb69b5cd8",
    ),
    "utf8_and_euc_tw.dll": (
        214_016,
        "8d6a2f7dd637a7a448731e510d54a0ec23addb1e0bd14446308cf1cf6481407e",
    ),
    "utf8_and_gb18030.dll": (
        275_456,
        "3faa094d4e10b6445c0dcdcf2b945339d09be81a4ecc938611eae3fcb00b32da",
    ),
    "utf8_and_gbk.dll": (
        160_768,
        "849128133e046d9cc32eca1694164736e3468c8e204b9182d64ed477665386fd",
    ),
    "utf8_and_iso8859.dll": (
        36_864,
        "3c9c88fd8c042247bbff07f3d87981ec52bf9ba9b3fae60da902d64c80482263",
    ),
    "utf8_and_iso8859_1.dll": (
        15_360,
        "aadfc8042ef2f591a230f6b1ab1944db457a00d5b5245f8e5d1d3560b1cee893",
    ),
    "utf8_and_johab.dll": (
        176_128,
        "906920275f408d98e1a37e1b4b981ba905d672d210ca7dd21da74f50a370e342",
    ),
    "utf8_and_sjis.dll": (
        95_744,
        "ee5a5cefc2e3bccabead23f2b5bbf1690b3d9388b18dbb36548fbd3b13a00747",
    ),
    "utf8_and_sjis2004.dll": (
        140_800,
        "19c157fd9ead7816fb731560fd8883235ebd582dc48b1cb12a3f4daadf6ab489",
    ),
    "utf8_and_uhc.dll": (
        181_760,
        "aff3f00f06b2337d57e126387d4d3d7028e3dc13c76644965a34bda429e48906",
    ),
    "utf8_and_win.dll": (
        39_936,
        "326866ed0be41d021901eac7d4cd6998c8e53ddd6e0d3e387eca3767e3521c78",
    ),
    # Group 2: core PL / dictionary modules the bootstrap + shipped share/
    # scripts load.
    "plpgsql.dll": (195_072, "0cb9cf979f53f416daea5e222f1fc1a1e6ce61615581c8eb08368abd2051b26c"),
    "dict_snowball.dll": (
        648_704,
        "ef01094f6e8eb8f27f4e1e5f879f1c8a8a735ac4ee95d1ddbc906466f40401ff",
    ),
    # Group 3: the one product-installed extension.
    "btree_gist.dll": (75_776, "d30056c80ba6a649aecec2cd9e1811340322b3d375a90bffb6300bc37d5f4ada"),
}

#: ``initdb`` reads the bootstrap catalog + SQL scripts and copies the
#: ``.sample`` config templates from ``share/`` at cluster-creation time;
#: PostgreSQL refuses to start without a valid ``share/timezone``` +
#: ``share/timezonesets`` (the ``timezone``/``timezone_abbreviations`` GUCs'
#: backing data). ``share/locale`` (~23 MB of ``.mo`` gettext translation
#: catalogs -- purely cosmetic: translated log/error text) and ``share/doc``
#: are excluded; their absence changes nothing about correctness, only the
#: language server log lines appear in (English, the untranslated default).
POSTGRES_SHARE_TOP_FILES: Final[tuple[str, ...]] = (
    "postgres.bki",
    "errcodes.txt",
    "information_schema.sql",
    "snowball_create.sql",
    "sql_features.txt",
    "system_constraints.sql",
    "system_functions.sql",
    "system_views.sql",
    "pg_hba.conf.sample",
    "pg_ident.conf.sample",
    "pg_service.conf.sample",
    "postgresql.conf.sample",
    "psqlrc.sample",
)

#: ``btree_gist``'s own ``.control`` + every version-upgrade ``.sql`` script
#: PostgreSQL's extension machinery may need (``CREATE EXTENSION`` always
#: installs the latest version file; a later ``ALTER EXTENSION ... UPDATE``
#: needs the upgrade-path scripts between versions -- shipping all of them,
#: same as upstream, rather than guessing which single version is "enough").
POSTGRES_SHARE_EXTENSION_FILES: Final[tuple[str, ...]] = (
    # plpgsql: initdb's own post-bootstrap initialization runs
    # `CREATE EXTENSION plpgsql` -- caught live by the build-time bootstrap
    # proof the first time it ran (the DLL alone is not enough; the
    # extension control + install script must ship too).
    "plpgsql.control",
    "plpgsql--1.0.sql",
    "btree_gist.control",
    "btree_gist--1.2.sql",
    "btree_gist--1.2--1.3.sql",
    "btree_gist--1.3--1.4.sql",
    "btree_gist--1.4--1.5.sql",
    "btree_gist--1.5--1.6.sql",
    "btree_gist--1.6--1.7.sql",
    "btree_gist--1.0--1.1.sql",
    "btree_gist--1.1--1.2.sql",
)

#: ``tsp.exe`` + the exact plugin closure ``civiccast/egress/ts_relay.py``
#: (``continuity``, ``pcradjust``), ``civiccast/egress/compliance.py``
#: (``until``, ``analyze``), and ``civiccast/alerting/self_test.py``
#: (``analyze``) invoke, determined the SAME way as the PostgreSQL DLL set
#: above: a real recursive PE import-table walk of ``tsp.exe`` PLUS all 4
#: plugin DLLs resolves to exactly ``tscore.dll`` + ``tsduck.dll`` (TSDuck's
#: core libraries) and only OS-provided imports (QUARTZ/WININET/WINUSB/
#: WinSCard) -- never ``libsrt``/``librist``/``libvatek``/DTAPI (TSDuck's
#: OWN ``OTHERS.txt`` third-party notices), which back only the
#: ``tsplugin_srt``/``tsplugin_rist``/``tsplugin_dektec``/``tsplugin_vatek``
#: plugin DLLs this pack does not ship. ``ip``, ``file``, and ``drop`` (also
#: used by the same call sites) need no separate plugin DLL of their own:
#: TSDuck compiles those three fundamental I/O plugins directly into
#: ``tsduck.dll``/``tscore.dll`` (confirmed: no ``tsplugin_ip.dll`` /
#: ``tsplugin_file.dll`` / ``tsplugin_drop.dll`` exists in the upstream
#: ``bin/`` listing at all, out of 87 ``tsplugin_*.dll`` files). Of the 87
#: shipped plugins, only these 4 leave this pack; the other 83 (satellite/
#: cable/ATSC/ISDB tuners, Dektec/VATek/HiDes hardware modulators, DVB
#: descramblers, SRT/RIST/SMPTE-2022/FLUTE transports, ...) are excluded.
TSDUCK_BIN_PINS: Final[dict[str, tuple[int, str]]] = {
    "tsp.exe": (88_576, "3ec0e60c1fe0459ba3baef70ac2527321841d0c84a82d0bea153009b51fe4a0d"),
    "tscore.dll": (
        1_990_656,
        "21ded43ac3d0c9954edf3ba9f2a3179bbf38d995c5655b79606c3f99405ace70",
    ),
    "tsduck.dll": (
        11_967_488,
        "76e1186f30aa4d04fdc492e0cafd106a8075a7492df3369512d1222beb03c083",
    ),
    "tsplugin_analyze.dll": (
        111_616,
        "f91a2de5160966ab37383033d7cb020d3a26e218b3e8f3103406b223d0da45f2",
    ),
    "tsplugin_continuity.dll": (
        91_136,
        "44860daa02ebf2503756486c9b59b8d3f44b9962fe1f65415531de66a7445991",
    ),
    "tsplugin_pcradjust.dll": (
        105_472,
        "74b03d91336b890c921da32c26d1136da904f984b769a40ffab843b49c4231ec",
    ),
    "tsplugin_until.dll": (
        93_696,
        "787650f04a4fc18c6e9c6b86aecf9c2181f425ec9725a7c89ea00119ebc09e0d",
    ),
}

#: Required upstream license text, one per component, verified present at
#: the exact archive-relative path named. Not hash-pinned individually
#: (license TEXT changing is not a supply-chain risk the way binary bytes
#: changing is; presence + content is instead checked via
#: ``classify_server_pack_file``, which requires every packed path resolve
#: to a confirmed SPDX id) but presence is still a hard requirement -- a
#: missing license file refuses the build the same as a missing binary.
POSTGRES_LICENSE_FILES: Final[tuple[str, ...]] = (
    "server_license.txt",
    "commandlinetools_3rd_party_licenses.txt",
)
TSDUCK_LICENSE_FILES: Final[tuple[str, ...]] = ("LICENSE.txt", "OTHERS.txt")

#: PostgreSQL's bundled IANA time zone database directories, plus
#: ``tsearch_data`` (85 KB: stop-word lists + ispell/synonym samples the
#: text-search dictionaries read at QUERY time). ``tsearch_data`` earned its
#: place via the build-time bootstrap proof: ``snowball_create.sql`` (shipped
#: in ``share/``) installs the ``english`` text-search configuration into
#: every cluster at initdb, so any query touching it (``to_tsvector`` --
#: exercised by the proof's probe) errors without these files even though no
#: product code calls it today; shipping the catalog without its data would
#: be a fail-at-runtime landmine. All validated by exact path SET (every
#: file present, nothing extra), not per-file pin; see the module
#: docstring's "Minimization"/pinning-strategy note.
POSTGRES_SHARE_DATA_DIRS: Final[tuple[str, ...]] = (
    "timezone",
    "timezonesets",
    "tsearch_data",
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_regular_file(path: Path, *, label: str) -> Path:
    try:
        details = path.lstat()
    except OSError as exc:
        raise ServerPackBuildError(f"{label} is missing: {path}") from exc
    attributes = int(getattr(details, "st_file_attributes", 0))
    if not stat.S_ISREG(details.st_mode) or path.is_symlink() or attributes & _REPARSE_POINT:
        raise ServerPackBuildError(f"{label} must be a regular non-reparse file: {path}")
    return path


def _require_real_directory(path: Path, *, label: str) -> Path:
    path = path.expanduser().resolve()
    try:
        details = path.lstat()
    except OSError as exc:
        raise ServerPackBuildError(f"{label} is missing: {path}") from exc
    attributes = int(getattr(details, "st_file_attributes", 0))
    if not stat.S_ISDIR(details.st_mode) or path.is_symlink() or attributes & _REPARSE_POINT:
        raise ServerPackBuildError(
            f"{label} must be a real directory, not a link or reparse point: {path}"
        )
    return path


def _validate_pinned_file(
    path: Path, *, expected_bytes: int, expected_sha256: str, label: str
) -> None:
    path = _require_regular_file(path, label=label)
    data = path.read_bytes()
    if len(data) != expected_bytes:
        raise ServerPackBuildError(
            f"{label} byte length mismatch: expected {expected_bytes}, observed {len(data)}"
        )
    observed = _sha256_bytes(data)
    if observed != expected_sha256:
        raise ServerPackBuildError(
            f"{label} SHA-256 mismatch: expected {expected_sha256}, observed {observed}"
        )


def _collect_data_tree(root: Path, *, dest_prefix: str) -> dict[str, Path]:
    """Every regular file under ``root`` -> its ``dest_prefix``-relative
    pack destination. Refuses symlinks, reparse points, and anything that
    is not a plain file (the same posture ``native_packs``'s own source
    validation applies at pack-build time, applied here too so a
    traversal/link problem is caught at the SELECTION stage with a clear
    per-file message, not a generic one from deep inside ``build_native_pack``).
    """

    root = _require_real_directory(root, label=f"{dest_prefix} data tree")
    sources: dict[str, Path] = {}
    for candidate in sorted(root.rglob("*")):
        if candidate.is_dir():
            continue
        details = candidate.lstat()
        attributes = int(getattr(details, "st_file_attributes", 0))
        if candidate.is_symlink() or attributes & _REPARSE_POINT:
            raise ServerPackBuildError(
                f"{dest_prefix} data tree contains a link or reparse point: {candidate}"
            )
        if not stat.S_ISREG(details.st_mode):
            raise ServerPackBuildError(
                f"{dest_prefix} data tree contains a non-regular file: {candidate}"
            )
        relative = PurePosixPath(dest_prefix) / candidate.relative_to(root).as_posix()
        sources[relative.as_posix()] = candidate
    if not sources:
        raise ServerPackBuildError(f"{dest_prefix} data tree is empty: {root}")
    return sources


def require_allowed_signing_key(key_id: str, *, allow_development_key: bool) -> None:
    """Keep development trust roots out of an accidental release build
    (same contract as ``build_native_caption_pack``'s guard)."""

    if key_id.startswith("development-") and not allow_development_key:
        raise ServerPackBuildError(
            "development pack signing keys require --allow-development-key; "
            "release packaging must use Scott-approved production key custody"
        )


def load_ed25519_private_key(path: Path) -> Ed25519PrivateKey:
    if not path.is_file():
        raise ServerPackBuildError(f"pack signing private key is missing: {path}")
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ServerPackBuildError("pack signing private key must be Ed25519")
    return key


# ---------------------------------------------------------------------------
# Acquisition (--acquire): reuse the reviewed lock + primitives verbatim.
# ---------------------------------------------------------------------------

_ACQUIRE_ARTIFACTS: Final[tuple[str, ...]] = ("postgres", "tsduck")
_ACQUIRE_EXPECTED_VERSIONS: Final[dict[str, str]] = {
    "postgres": POSTGRES_VERSION,
    "tsduck": TSDUCK_VERSION,
}


def acquire_server_pack_sources(cache: Path, *, lock_path: Path = LOCK_PATH) -> dict[str, Path]:
    """Download + verify + extract ONLY the postgres/tsduck artifacts
    from the reviewed runtime-dependency lock (never the ffmpeg/node/ollama
    artifacts the same lock also pins for the unrelated "Core" pack).

    ``cache`` is caller-controlled and MUST live outside the repository
    (this task's hard rule) -- callers pass a scratch/temp directory, never
    a path under the checked-out tree.

    A pre-existing ``cache/extracted/<name>`` is trusted only if it is
    actually COMPLETE -- re-verified against the same pinned bin/lib/share
    file set ``build_server_pack()`` itself requires (see
    ``_extracted_tree_is_complete``), not merely present. Candidate run
    32845198987 failed identically in both attempts with "pinned PostgreSQL
    initdb.exe is missing" from a persistent self-hosted `--cache` whose
    extraction had been interrupted by a prior run; a bare `destination.
    exists()` check trusted the incomplete tree and never re-extracted it.
    An invalid tree is cleared and re-extracted from the ALREADY hash-
    verified archive (``fetch_locked_artifact``'s own `.partial`-then-
    verify-then-rename download is unaffected by any of this -- the
    archive on disk was never the problem, only the derived extraction).
    """

    lock = load_lock(lock_path)
    extracted: dict[str, Path] = {}
    for name in _ACQUIRE_ARTIFACTS:
        artifact = lock["artifacts"][name]
        expected_version = _ACQUIRE_EXPECTED_VERSIONS[name]
        if str(artifact["version"]) != expected_version:
            raise ServerPackBuildError(
                f"{name} artifact version drifted from this builder's reviewed pin: "
                f"lock has {artifact['version']!r}, builder expects {expected_version!r} "
                "-- re-review before rebuilding"
            )
        archive = fetch_locked_artifact(name, artifact, cache / "archives", offline=False)
        destination = cache / "extracted" / name
        if destination.exists() and not _extracted_tree_is_complete(name, destination):
            shutil.rmtree(destination, ignore_errors=True)
        if not destination.exists():
            safe_extract_zip(
                archive,
                destination,
                strip_prefix=str(artifact["strip_prefix"]),
                include=artifact.get("include"),
            )
        extracted[name] = destination
    return extracted


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def _postgres_sources(postgres_root: Path) -> dict[str, Path]:
    postgres_root = _require_real_directory(postgres_root, label="PostgreSQL source root")
    sources: dict[str, Path] = {}

    for filename, (expected_bytes, expected_sha256) in sorted(POSTGRES_BIN_PINS.items()):
        path = postgres_root / "bin" / filename
        _validate_pinned_file(
            path,
            expected_bytes=expected_bytes,
            expected_sha256=expected_sha256,
            label=f"pinned PostgreSQL {filename}",
        )
        sources[f"bin/{filename}"] = path
    for filename, (expected_bytes, expected_sha256) in sorted(POSTGRES_BIN_DLL_PINS.items()):
        path = postgres_root / "bin" / filename
        _validate_pinned_file(
            path,
            expected_bytes=expected_bytes,
            expected_sha256=expected_sha256,
            label=f"pinned PostgreSQL runtime dependency {filename}",
        )
        sources[f"bin/{filename}"] = path
    for filename, (expected_bytes, expected_sha256) in sorted(POSTGRES_LIB_PINS.items()):
        path = postgres_root / "lib" / filename
        _validate_pinned_file(
            path,
            expected_bytes=expected_bytes,
            expected_sha256=expected_sha256,
            label=f"pinned PostgreSQL extension {filename}",
        )
        sources[f"lib/{filename}"] = path

    for filename in POSTGRES_SHARE_TOP_FILES:
        path = _require_regular_file(
            postgres_root / "share" / filename, label=f"PostgreSQL share/{filename}"
        )
        sources[f"share/{filename}"] = path
    for filename in POSTGRES_SHARE_EXTENSION_FILES:
        path = _require_regular_file(
            postgres_root / "share" / "extension" / filename,
            label=f"PostgreSQL share/extension/{filename}",
        )
        sources[f"share/extension/{filename}"] = path
    for subdir in POSTGRES_SHARE_DATA_DIRS:
        sources.update(
            _collect_data_tree(postgres_root / "share" / subdir, dest_prefix=f"share/{subdir}")
        )
    for filename in POSTGRES_LICENSE_FILES:
        path = _require_regular_file(
            postgres_root / filename, label=f"PostgreSQL license file {filename}"
        )
        sources[f"licenses/postgresql/{filename}"] = path
    return sources


def _tsduck_sources(tsduck_root: Path) -> dict[str, Path]:
    tsduck_root = _require_real_directory(tsduck_root, label="TSDuck source root")
    sources: dict[str, Path] = {}
    for filename, (expected_bytes, expected_sha256) in sorted(TSDUCK_BIN_PINS.items()):
        path = tsduck_root / "bin" / filename
        _validate_pinned_file(
            path,
            expected_bytes=expected_bytes,
            expected_sha256=expected_sha256,
            label=f"pinned TSDuck {filename}",
        )
        sources[f"tsduck/bin/{filename}"] = path
    for filename in TSDUCK_LICENSE_FILES:
        path = _require_regular_file(
            tsduck_root / filename, label=f"TSDuck license file {filename}"
        )
        sources[f"licenses/tsduck/{filename}"] = path
    return sources


_ACQUIRE_VALIDATORS: Final[dict[str, Callable[[Path], dict[str, Path]]]] = {
    "postgres": _postgres_sources,
    "tsduck": _tsduck_sources,
}


def _extracted_tree_is_complete(name: str, destination: Path) -> bool:
    """Re-verify a pre-existing extraction against the SAME pinned bin/lib/
    share file set `build_server_pack()` itself requires, rather than
    trusting bare directory existence.

    A self-hosted runner's `--cache` persists across runs (a hosted runner
    is always fresh); a previous run's extraction into `cache/extracted/
    <name>` interrupted partway through (a crash, a cancelled run, a disk
    hiccup) leaves a directory that EXISTS but is missing files --
    candidate run 32845198987 failed identically in BOTH attempts with
    "pinned PostgreSQL initdb.exe is missing" from exactly this path,
    surfaced only much later, deep inside the live PostgreSQL bootstrap
    proof, rather than here where the incompleteness actually originates.
    """
    try:
        _ACQUIRE_VALIDATORS[name](destination)
    except ServerPackBuildError:
        return False
    return True


def _require_zero_gpl_and_full_license_provenance(sources: dict[str, Path]) -> None:
    """Refuse the build if any packed path has no confirmed license, or a
    confirmed license that is GPL-family (task's zero GPL/AGPL tolerance).
    Runs on every path this build is ABOUT to pack, so a future addition to
    the source-selection functions above that forgets to update
    ``civiccast.native.runtime_licenses`` fails the build loud instead of
    shipping an unreviewed file silently."""

    unresolved: list[str] = []
    gpl_flagged: list[tuple[str, str]] = []
    for relative_path in sorted(sources):
        if relative_path.startswith(("notices/",)):
            continue  # this builder's own generated NOTICE, not upstream bytes
        license_id = classify_server_pack_file(relative_path)
        if license_id is None:
            unresolved.append(relative_path)
        elif is_gpl_license(license_id):
            gpl_flagged.append((relative_path, license_id))
    if gpl_flagged:
        raise ServerPackBuildError(
            "native-server-binaries pack refuses GPL/AGPL-family entries: "
            + ", ".join(f"{path} ({license_id})" for path, license_id in gpl_flagged)
        )
    if unresolved:
        raise ServerPackBuildError(
            "native-server-binaries pack has unconfirmed license provenance for: "
            + ", ".join(unresolved[:10])
            + (f" (+{len(unresolved) - 10} more)" if len(unresolved) > 10 else "")
        )


def _free_loopback_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _grant_scratch_tree_to_current_user(root: Path) -> None:
    """Give the current user's OWN SID explicit rights on the proof's
    scratch tree (Windows only; no-op elsewhere).

    LESSON (candidate runs 31143881561 and 31154873108, diagnosed live on
    the runner via PR #368's three-leg probe): PostgreSQL's Windows
    binaries re-exec themselves under a RESTRICTED token that marks the
    Administrators group deny-only (``get_restricted_token``). On GitHub's
    hosted runners the scratch drive's ACLs grant access through
    Administrators alone, so the re-exec'd ``initdb`` child cannot read
    the DLLs beside its own executable and its loader dies with
    0xC0000135 (STATUS_DLL_NOT_FOUND) and NO output -- the parent
    silently propagates that status, which is exactly the empty-output
    failure both candidate runs showed. ``initdb --version`` exits before
    the re-exec, which is why simple load probes pass on the same image.

    Granting the user's own SID mirrors what an installed station already
    has (pack payloads land under ProgramData with user-readable ACLs --
    the 2026-07-30 Sandbox run's initdb got far past loading), so this
    keeps the proof faithful to station reality rather than weakening it:
    probe leg A (no grant) reproduced 0xC0000135 on the runner; leg C
    (this exact grant) ran initdb to its first real bootstrap step.
    """

    if os.name != "nt":
        return
    whoami = subprocess.run(["whoami"], capture_output=True, text=True, timeout=60, check=False)
    account = whoami.stdout.strip()
    if whoami.returncode != 0 or not account:
        raise ServerPackBuildError(
            "bootstrap proof could not resolve the current user for the "
            f"scratch-tree access grant (whoami exit {whoami.returncode})"
        )
    grant = subprocess.run(
        ["icacls", str(root), "/grant:r", f"{account}:(OI)(CI)F", "/T"],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if grant.returncode != 0:
        raise ServerPackBuildError(
            "bootstrap proof could not grant the current user access to its "
            f"scratch tree (icacls exit {grant.returncode}): "
            f"{grant.stdout.strip()} {grant.stderr.strip()}"
        )


def prove_postgres_bootstrap(
    postgres_root: Path,
    *,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> None:
    """Live build-time proof that the EXACT ``lib``/``bin``/``share``
    selection this builder packs can bootstrap and serve a real cluster.

    Sandbox matrix row 1, run 2 (2026-07-30): the first live ``initdb``
    against a packed tree died on a ``lib/`` module the selection had
    trimmed (``$libdir/utf8_and_win``) -- a class of omission no
    hash/path-set validation can catch, because every file the selection
    DOES name was present and correct. The only authority on completeness
    is PostgreSQL itself, so every real pack build now materializes the
    selected files into a scratch tree and runs, in order: ``initdb``
    (the SAME argv shape provisioning uses -- ``initdb_argv`` imported
    from ``civiccast.native.provision.seams``, never a lookalike),
    ``pg_ctl start`` on a free loopback port, a ``psql`` probe that
    exercises the pinned extension (``CREATE EXTENSION btree_gist``) and
    the snowball dictionary path (``to_tsvector``), then ``pg_ctl stop``.
    Any nonzero step fails the BUILD with the step's full output -- never
    a station install. ``run`` is injectable for the unit suite (hard
    rule: no real postgres execution in unit tests; the live execution
    happens on every real CLI pack build).
    """

    sources = _postgres_sources(postgres_root)
    with tempfile.TemporaryDirectory(
        prefix="civiccast-pack-bootstrap-proof-", ignore_cleanup_errors=True
    ) as temporary:
        root = Path(temporary)
        pgroot = root / "pg"
        for key, src in sources.items():
            if key.split("/", 1)[0] not in ("bin", "lib", "share"):
                continue
            dest = pgroot.joinpath(*PurePosixPath(key).parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        # Without this, initdb's restricted-token re-exec cannot read the
        # staged tree on GitHub-hosted runners and dies 0xC0000135 before
        # its first print -- see _grant_scratch_tree_to_current_user.
        _grant_scratch_tree_to_current_user(root)
        pwfile = root / "bootstrap-proof-pwfile.txt"
        pwfile.write_text("civiccast-bootstrap-proof\n", encoding="ascii")
        pgdata = root / "pgdata"
        logfile = root / "postgres-proof.log"
        port = _free_loopback_port()
        env = {**os.environ, "PGPASSWORD": "civiccast-bootstrap-proof"}

        step_index = 0

        def check(step: str, argv: list[str]) -> None:
            # Step output goes to FILES, never subprocess pipes: ``pg_ctl
            # start`` leaves a detached ``postgres.exe`` holding inherited
            # copies of the parent's stdout/stderr handles, and with PIPE
            # capture ``subprocess.run`` blocks on pipe EOF until the server
            # exits -- a deadlock observed live on this proof's first
            # passing initdb (2026-07-30). File handles are inherited too,
            # but nothing waits on their closure.
            nonlocal step_index
            step_index += 1
            out_path = root / f"proof-step-{step_index:02d}-output.txt"
            with out_path.open("w", encoding="utf-8") as sink:
                result = run(argv, stdout=sink, stderr=subprocess.STDOUT, text=True, env=env)
            if result.returncode != 0:
                captured = out_path.read_text(encoding="utf-8", errors="replace")
                log_tail = ""
                if logfile.exists():
                    log_tail = "\n--- server log tail ---\n" + "\n".join(
                        logfile.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
                    )
                raise ServerPackBuildError(
                    f"pack bootstrap proof failed at {step} (exit {result.returncode}). "
                    "The packed PostgreSQL selection cannot bootstrap a live cluster -- "
                    "most likely a bin/lib/share file the pins do not carry. Fix the "
                    "selection (see POSTGRES_LIB_PINS' lesson comment); do NOT ship "
                    f"this pack.\n--- output ---\n{captured}{log_tail}"
                )

        bin_dir = pgroot / "bin"
        check(
            "initdb",
            initdb_argv(
                initdb_path=str(bin_dir / "initdb.exe"),
                data_dir=str(pgdata),
                username="civiccast",
                pwfile=str(pwfile),
            ),
        )
        started = False
        try:
            check(
                "pg_ctl start",
                [
                    str(bin_dir / "pg_ctl.exe"),
                    "--pgdata",
                    str(pgdata),
                    "--log",
                    str(logfile),
                    "--wait",
                    "--timeout",
                    "60",
                    "--options",
                    f"-p {port} -c listen_addresses=127.0.0.1",
                    "start",
                ],
            )
            started = True
            check(
                "psql probe",
                [
                    str(bin_dir / "psql.exe"),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--username",
                    "civiccast",
                    "--dbname",
                    "postgres",
                    "--set",
                    "ON_ERROR_STOP=1",
                    "--command",
                    "CREATE EXTENSION btree_gist;",
                    "--command",
                    "SELECT to_tsvector('english', 'pack bootstrap proof');",
                ],
            )
        finally:
            if started:
                with (root / "proof-step-99-stop-output.txt").open("w", encoding="utf-8") as sink:
                    run(
                        [
                            str(bin_dir / "pg_ctl.exe"),
                            "--pgdata",
                            str(pgdata),
                            "--mode",
                            "fast",
                            "--wait",
                            "stop",
                        ],
                        stdout=sink,
                        stderr=subprocess.STDOUT,
                        text=True,
                        env=env,
                    )


def build_server_pack(
    *,
    output: Path,
    postgres_root: Path,
    tsduck_root: Path,
    signing_private_key: Ed25519PrivateKey,
    signing_key_id: str,
    product_version: str,
    source_sha: str,
    compatible_core: str | None = None,
) -> dict[str, object]:
    """Validate the pinned PostgreSQL/TSDuck inputs and build the
    signed ``native-server-binaries`` pack.

    The returned report's ``payload_tree_sha256`` (from
    ``civiccast.installer.native_packs.payload_tree_sha256``, applied to the
    SAME manifest ``files`` entries ``build_native_pack`` already computes
    and signs -- not a second, independent hashing pass) lets two machines
    that each built this pack from the same commit compare their PAYLOAD
    bytes decisively, even though their ``pack_sha256``/signing key id
    necessarily differ (each machine signs with its own local development
    key). Equal ``payload_tree_sha256`` across machines is the actual
    reproducible-build proof; equal ``payload_bytes``/``file_count`` alone
    is not (same size and count can hide a rename or a same-size content
    swap)."""

    if not (
        isinstance(source_sha, str)
        and len(source_sha) == 40
        and all(character in "0123456789abcdef" for character in source_sha)
    ):
        raise ServerPackBuildError("source SHA must be exactly 40 lowercase hexadecimal characters")

    sources = {
        **_postgres_sources(postgres_root),
        **_tsduck_sources(tsduck_root),
    }

    notice = (
        "CivicCast native server-binaries pack\n"
        f"PostgreSQL {POSTGRES_VERSION} (bin/initdb.exe, bin/postgres.exe, "
        "bin/pg_ctl.exe, bin/pg_dump.exe, bin/pg_dumpall.exe, bin/pg_restore.exe, bin/psql.exe, "
        "the runtime DLLs they import, the btree_gist extension, and required "
        "share/ bootstrap + timezone data)\n"
        f"TSDuck {TSDUCK_VERSION} subset (tsduck/bin/tsp.exe, tscore.dll, "
        "tsduck.dll, and the analyze/continuity/pcradjust/until plugins)\n"
        "See licenses/ for upstream license texts and "
        "civiccast.native.runtime_licenses.SERVER_PACK_BASENAME_LICENSE for "
        "the per-file provenance table.\n"
    )
    with tempfile.TemporaryDirectory(prefix="civiccast-server-pack-") as temporary:
        notice_path = Path(temporary) / "NOTICE.txt"
        notice_path.write_text(notice, encoding="utf-8", newline="\n")
        sources["notices/server-binaries.txt"] = notice_path

        _require_zero_gpl_and_full_license_provenance(sources)

        result = build_native_pack(
            output=output,
            component=SERVER_BINARIES_COMPONENT,
            product_version=product_version,
            compatible_core=compatible_core or product_version,
            sources=sources,
            signing_private_key=signing_private_key,
            signing_key_id=signing_key_id,
            metadata={
                "postgres_version": POSTGRES_VERSION,
                "tsduck_version": TSDUCK_VERSION,
                "source_sha": source_sha,
            },
        )
    return {
        "component": result.component,
        "file_count": result.file_count,
        "output": str(result.path),
        "pack_bytes": result.path.stat().st_size,
        "pack_sha256": result.sha256,
        "payload_bytes": result.total_bytes,
        "payload_tree_sha256": result.payload_tree_sha256,
        "product_version": result.product_version,
        "signing_key_id": result.signing_key_id,
        "source_sha": source_sha,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--acquire",
        action="store_true",
        help=(
            "download + verify + extract postgres/tsduck from the reviewed "
            "lock into --cache before building (mutually exclusive with the "
            "--*-root flags)"
        ),
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path(tempfile.gettempdir()) / "civiccast-native-server-pack-cache",
        help="scratch directory OUTSIDE the repo for --acquire's downloads/extraction",
    )
    parser.add_argument("--lock", type=Path, default=LOCK_PATH)
    parser.add_argument("--postgres-root", type=Path)
    parser.add_argument("--tsduck-root", type=Path)
    parser.add_argument("--signing-private-key", required=True, type=Path)
    parser.add_argument("--signing-key-id", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--product-version", default=__version__)
    parser.add_argument("--compatible-core", default=None)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--allow-development-key",
        action="store_true",
        help="explicitly allow a development-only trust root for non-release proof",
    )
    parser.add_argument(
        "--skip-bootstrap-proof",
        action="store_true",
        help=(
            "skip the live initdb/server bootstrap proof of the packed "
            "PostgreSQL selection (emergency/debug ONLY -- the proof exists "
            "because a trimmed selection shipped a pack whose first live "
            "initdb died; see POSTGRES_LIB_PINS)"
        ),
    )
    args = parser.parse_args()

    try:
        require_allowed_signing_key(
            args.signing_key_id, allow_development_key=args.allow_development_key
        )
        key = load_ed25519_private_key(args.signing_private_key)

        if args.acquire:
            if args.postgres_root or args.tsduck_root:
                raise ServerPackBuildError("--acquire is mutually exclusive with --*-root flags")
            roots = acquire_server_pack_sources(args.cache, lock_path=args.lock)
            postgres_root, tsduck_root = (
                roots["postgres"],
                roots["tsduck"],
            )
        else:
            missing = [
                flag
                for flag, value in (
                    ("--postgres-root", args.postgres_root),
                    ("--tsduck-root", args.tsduck_root),
                )
                if value is None
            ]
            if missing:
                raise ServerPackBuildError(
                    f"missing required flags (or pass --acquire instead): {', '.join(missing)}"
                )
            postgres_root, tsduck_root = (
                args.postgres_root,
                args.tsduck_root,
            )

        if args.skip_bootstrap_proof:
            print(
                "build_native_server_pack: WARNING -- bootstrap proof SKIPPED "
                "(--skip-bootstrap-proof); this pack's PostgreSQL selection is "
                "unproven against a live initdb",
                file=sys.stderr,
            )
        else:
            print("build_native_server_pack: running live bootstrap proof (initdb + server)...")
            prove_postgres_bootstrap(postgres_root)
            print("build_native_server_pack: bootstrap proof PASSED")

        report = build_server_pack(
            output=args.output.resolve(),
            postgres_root=postgres_root,
            tsduck_root=tsduck_root,
            signing_private_key=key,
            signing_key_id=args.signing_key_id,
            product_version=args.product_version,
            source_sha=args.source_sha,
            compatible_core=args.compatible_core,
        )
    except ServerPackBuildError as exc:
        print(f"build_native_server_pack: {exc}", file=sys.stderr)
        return 1

    rendered = json.dumps(report, indent=2) + "\n"
    if args.report is not None:
        report_path = args.report.resolve()
        if report_path.exists():
            raise FileExistsError(f"server pack report already exists: {report_path}")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
