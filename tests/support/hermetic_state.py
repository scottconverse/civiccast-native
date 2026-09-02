# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Keep ordinary tests away from the developer's real CivicCast state.

Two halves, both driven from ``tests/conftest.py``:

* :func:`hermetic_environment` returns the environment overrides that steer
  every product default-path resolver (``%LOCALAPPDATA%\\CivicCast``, the XDG
  roots, ``~/.civiccast`` via ``CIVICCAST_CONFIG_DIR`` / ``CIVICCAST_CERT_ROOT``)
  beneath one temporary root.
* :func:`snapshot` / :func:`changed_entries` detect writes to the REAL state
  roots so a test that hard-codes a path, or a resolver this module does not
  know about, fails loudly instead of quietly editing the operator's station.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from pathlib import Path

#: Environment variables whose presence selects the real user-state roots.
#: Every entry is redirected for unmarked tests.
REDIRECTED_ENV_VARS: tuple[str, ...] = (
    "LOCALAPPDATA",
    "XDG_DATA_HOME",
    "XDG_STATE_HOME",
    "XDG_CONFIG_HOME",
    "CIVICCAST_CONFIG_DIR",
    "CIVICCAST_CERT_ROOT",
    "CIVICCAST_INSTALLER_BOOTSTRAP_LOG",
    # POSIX only: ``default_storage_dir`` / ``default_egress_work_dir`` fall back
    # to ``Path.home()/.local/share/civiccast`` without consulting XDG, and
    # ``Path.home()`` reads HOME there. On Windows ``Path.home()`` reads
    # USERPROFILE, which stays untouched: every Windows default goes through
    # LOCALAPPDATA or an explicit CIVICCAST_* variable above.
    *(() if os.name == "nt" else ("HOME",)),
)

#: Marker name a test uses to opt OUT of the redirect because it deliberately
#: verifies the installed-path contract. Registered in ``pyproject.toml``.
INSTALLED_PATHS_MARKER = "installed_paths"


def hermetic_environment(root: Path) -> dict[str, str]:
    """Return env overrides that place every CivicCast state default under ``root``.

    Deliberately does NOT pre-create any of these directories. ``root`` is a
    test's ``tmp_path``, and several tests (e.g.
    ``tests/schedule/test_media_lifecycle_router.py::
    TestBrowseFoldersApi::test_lists_subdirectories_of_a_real_path``, the
    ``tests/control_room`` and ``tests/tools`` artifact-root tests) use
    ``tmp_path`` itself as a pristine sandbox and assert on its exact
    contents. Materializing ``AppData``, ``xdg``, ``civiccast-config`` or
    ``home`` beneath it here would plant extra top-level entries those tests
    never created and do not expect. Every directory below is created lazily
    by the product code that actually needs it (state, lock, upload,
    certificate, secrets writers all create their parents on first write);
    the one exception -- ``Path.home()`` needing to exist for
    ``shutil.disk_usage`` -- is fixed at the source in
    ``civiccast.platform.hardware._probe_disk`` instead of by planting a
    directory here.
    """

    local_app_data = root / "AppData" / "Local"
    xdg = root / "xdg"
    return {
        "LOCALAPPDATA": str(local_app_data),
        "XDG_DATA_HOME": str(xdg / "data"),
        "XDG_STATE_HOME": str(xdg / "state"),
        "XDG_CONFIG_HOME": str(xdg / "config"),
        "CIVICCAST_CONFIG_DIR": str(root / "civiccast-config"),
        "CIVICCAST_CERT_ROOT": str(root / "civiccast-config" / "certs"),
        "CIVICCAST_INSTALLER_BOOTSTRAP_LOG": str(root / "civiccast-config" / "runtime-host.log"),
        **({} if os.name == "nt" else {"HOME": str(root / "home")}),
    }


def real_state_roots(env: Mapping[str, str] | None = None) -> tuple[Path, ...]:
    """The directories a test must never modify: the operator's own user state.

    Resolved from the ORIGINAL process environment (captured before any test
    fixture runs), never from the redirected one. ``C:\\ProgramData\\CivicCast``
    is deliberately excluded: a running native station writes there on its own
    schedule, so a before/after comparison would blame tests for the service's
    activity. Nothing in the product resolves a default beneath ProgramData
    without ``CIVICCAST_NATIVE_STATION_ROOT`` or the service's explicit layout.
    """

    source = os.environ if env is None else env
    roots: list[Path] = []
    local_app_data = source.get("LOCALAPPDATA")
    if local_app_data:
        roots.append(Path(local_app_data) / "CivicCast")
    home = source.get("USERPROFILE") if os.name == "nt" else source.get("HOME")
    if home:
        roots.append(Path(home) / ".civiccast")
    for xdg_var, leaf in (("XDG_DATA_HOME", "civiccast"), ("XDG_STATE_HOME", "civiccast")):
        xdg_root = source.get(xdg_var)
        if xdg_root:
            roots.append(Path(xdg_root) / leaf)
    return tuple(roots)


def snapshot(roots: Iterable[Path]) -> dict[str, tuple[int, int]]:
    """Return ``{path: (size, mtime_ns)}`` for every file beneath ``roots``.

    Read-only: a root that does not exist contributes nothing (and its later
    creation shows up as a change). Permission errors on individual entries are
    skipped rather than raised so a locked file cannot break every test.
    """

    # os.path rather than pathlib on purpose: this runs at fixture teardown,
    # and a test may still have ``os.name`` monkeypatched to "posix" on
    # Windows, where instantiating a Path would raise.
    entries: dict[str, tuple[int, int]] = {}
    for root in roots:
        root_text = os.fspath(root)
        if not os.path.exists(root_text):  # noqa: PTH110 -- see comment above
            continue
        for dirpath, _dirnames, filenames in os.walk(root_text):
            for name in filenames:
                path = os.path.join(dirpath, name)  # noqa: PTH118
                try:
                    stat = os.stat(path)  # noqa: PTH116
                except OSError:
                    continue
                entries[path] = (stat.st_size, stat.st_mtime_ns)
    return entries


def changed_entries(
    before: Mapping[str, tuple[int, int]],
    after: Mapping[str, tuple[int, int]],
) -> list[str]:
    """Paths created, removed, or rewritten between two snapshots, sorted."""

    changed = set(after.keys() ^ before.keys())
    changed.update(path for path in before.keys() & after.keys() if before[path] != after[path])
    return sorted(changed)


__all__ = [
    "INSTALLED_PATHS_MARKER",
    "REDIRECTED_ENV_VARS",
    "changed_entries",
    "hermetic_environment",
    "real_state_roots",
    "snapshot",
]
