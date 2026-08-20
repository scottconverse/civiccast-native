# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Single source of truth for the NATIVE Windows product line's own version.

Deliberately separate from ``civiccast._version`` (native-windows chain J,
2026-08-02). ``civiccast._version.__version__`` is the WSL/mainline product
line's own release identity -- read by a dozen-plus pre-existing policy
checks and public docs (README.md's public-beta paragraph, INSTALL-WINDOWS.md,
ARCHITECTURE.md, CAPABILITIES.md, FAQ.md, SUPPORT.md, the v1.7 adoption gate,
the Windows release downloader, ``package.json``, the WSL Tauri config, ...)
that all describe the already-published WSL beta and must not be disturbed by
native-line development.

The native Windows product ("CivicCast (Native)") is a separate product under
active, unreleased development. Before this module existed it inherited the
WSL line's own version string verbatim, which produced two functionally
different installers reporting the identical string ``1.0.0-rc15`` -- this
confused the project owner personally and would confuse a PEG-station
operator. This module is what the native line's own identity surfaces
(``tauri.native.conf.json``'s ``"version"``, the installer Rust crate's
``CIVICCAST_VERSION`` constant, and native component pack builders' default
``--product-version``) are kept in lockstep with instead.

This value is surfaced by the shared backend's ``/health`` and
``/api/version`` endpoints ONLY when the process is actually running as a
native station -- see ``civiccast.native.station_runtime.
load_native_station_environment`` (sets ``CIVICCAST_NATIVE_REPORTED_VERSION``)
and ``civiccast.app``'s ``health``/``get_version`` handlers (read it, falling
back to ``civiccast._version.__version__`` when unset -- i.e. every other
hosting context, including the WSL line, is completely unaffected).
"""

__version__ = "1.0.0-beta.1"
