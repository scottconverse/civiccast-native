# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Single source of truth for "is a container engine reachable?".

Four test modules had each copy-pasted their own ``_docker_available()``, and
the copies were buggy in two different ways, so the same real-boundary suites
silently skipped on developer machines that had a perfectly good engine:

* the pipe-stat copies used ``Path(r"\\\\.\\pipe\\docker_engine").exists()`` --
  pathlib cannot stat a Windows named pipe (it returns False or raises
  WinError 231, ERROR_PIPE_BUSY, which actually means the pipe *exists*), so
  they reported "no engine" on every Windows box; and
* the CLI copies ran ``docker`` only, so they reported "no engine" on any box
  running podman, which serves the same Docker API but ships no ``docker``
  binary.

This helper detects Docker Desktop *or* podman, on Linux/macOS/Windows, without
opening a socket on the fast path (so pytest ``filterwarnings=error`` never
promotes a leaked-connection ResourceWarning into a teardown error).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def docker_engine_available() -> bool:
    """True when a Docker-API engine (Docker Desktop or podman) is reachable."""
    # An explicit endpoint always wins.
    if os.environ.get("DOCKER_HOST"):
        return True

    # Filesystem checks first -- they open no socket.
    if sys.platform == "win32":
        # List the pipe namespace; pathlib.Path.exists() cannot stat a pipe.
        try:
            if any(pipe.name == "docker_engine" for pipe in Path(r"\\.\pipe").iterdir()):
                return True
        except OSError:
            pass
    else:
        for sock in (
            Path("/var/run/docker.sock"),
            Path.home() / ".docker" / "run" / "docker.sock",  # macOS rootless
            Path(f"/run/user/{os.getuid()}/podman/podman.sock"),  # rootless podman
        ):
            try:
                if sock.exists():
                    return True
            except OSError:
                pass

    # Fall back to a one-shot CLI probe -- ``docker`` (Docker Desktop) or
    # ``podman``. ``info`` exits 0 only when the engine is actually reachable;
    # no --format, since the two expose different template fields.
    return container_cli() is not None


def container_cli() -> str | None:
    """The name of a working container CLI (``docker`` or ``podman``), or None.

    A test that has to ``<cli> exec`` into a testcontainer needs the runtime
    that actually created it, not a hardcoded ``docker`` -- podman serves the
    same API but its containers are reachable only through ``podman``.
    """
    for cli in ("docker", "podman"):
        try:
            subprocess.run(
                [cli, "info"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
            return cli
        except (OSError, subprocess.SubprocessError):
            continue
    return None
