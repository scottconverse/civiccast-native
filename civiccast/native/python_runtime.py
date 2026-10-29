# SPDX-License-Identifier: Apache-2.0
"""Validate the reviewed source-built interpreter independently of payload manifests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

from civiccast.native.app_payload import INTERPRETER_DISTRIBUTION, INTERPRETER_VERSION

PROVENANCE_PATH = "python-runtime-provenance.json"
# This binds source/dependency pins, compiler/builder identities, licenses and
# every original runtime file. Changing a payload manifest cannot change this pin.
PROVENANCE_SHA256 = "eacf8bf363373e1e66378977cafca2cadccbb3b5f470d74563ef72f8db5835f6"
BUILDER_SHA256 = "f3e1f646439eee6e125e9c7f672f0b0220f8ec9af99d1ff6e397612c6a79d6c6"
INSTALLED_PTH = (
    b"python312.zip\n.\n\n# Uncomment to run site.main() automatically\n"
    b"import site\nLib\\site-packages\n"
)


def verify_runtime_files(read: Callable[[str], bytes], *, installed: bool = False) -> list[str]:
    """Check original ZIP bytes, or installed bytes with the one approved ._pth edit."""
    try:
        raw = read(PROVENANCE_PATH)
        if hashlib.sha256(raw).hexdigest() != PROVENANCE_SHA256:
            return ["runtime provenance SHA-256 differs from reviewed pin"]
        provenance = json.loads(raw)
        if (
            provenance["schema_version"] != 1
            or provenance["distribution"] != INTERPRETER_DISTRIBUTION
            or provenance["version"] != INTERPRETER_VERSION
            or provenance["architecture"] != "amd64"
            or provenance["builder_sha256"] != BUILDER_SHA256
        ):
            return ["runtime provenance identity/version/builder mismatch"]
        problems = []
        for name, record in provenance["files"].items():
            # Paths are also pinned by the provenance digest; retain a local
            # boundary check so malformed test/prospective pins fail closed.
            if "\\" in name or name.startswith("/") or ".." in name.split("/"):
                return ["unsafe runtime provenance path"]
            data = read(name)
            if installed and name == "python312._pth":
                valid = data == INSTALLED_PTH
            else:
                valid = len(data) == record["bytes"] and (
                    hashlib.sha256(data).hexdigest() == record["sha256"]
                )
            if not valid:
                problems.append(f"runtime file differs from reviewed build: {name}")
        return problems
    except (OSError, KeyError, ValueError, TypeError) as exc:
        return [f"missing or invalid runtime provenance/file: {exc}"]
