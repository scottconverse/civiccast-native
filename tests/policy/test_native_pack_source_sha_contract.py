# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Static cross-language contract for source-bound native runtime packs.

Rust compilation is intentionally excluded from this host-safe slice. This
policy test instead asserts the installer verifier retains the same strict
component list, source SHA shape, and app-payload substitution guard as the
Python verifier tests exercise through signed manifests.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

RUST_NATIVE_PACKS = Path("civiccast/apps/installer/src-tauri/src/native_packs.rs")
PACK_BUILDERS = (
    "scripts/build_native_app_payload_pack.py",
    "scripts/build_native_server_pack.py",
)


def _checked_in_builder_invocations() -> list[tuple[Path, str]]:
    tracked = subprocess.run(
        ["git", "ls-files"], check=True, capture_output=True, text=True
    ).stdout.splitlines()
    invocations: list[tuple[Path, str]] = []
    for name in tracked:
        path = Path(name)
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for index, line in enumerate(lines):
            if "python" not in line or not any(builder in line for builder in PACK_BUILDERS):
                continue
            command = [line]
            next_index = index + 1
            while command[-1].rstrip().endswith(("\\", "`")) and next_index < len(lines):
                command.append(lines[next_index])
                next_index += 1
            invocations.append((path, "\n".join(command)))
    return invocations


def test_checked_in_pack_builder_invocations_bind_a_valid_source_sha() -> None:
    invocations = _checked_in_builder_invocations()
    assert invocations
    assert {builder for _, command in invocations for builder in PACK_BUILDERS if builder in command} == set(
        PACK_BUILDERS
    )
    for path, command in invocations:
        text = path.read_text(encoding="utf-8")
        assert re.search(
            r"--source-sha\s+(?:[\"']?\$[A-Za-z_][A-Za-z0-9_]*|\$env:[A-Za-z_][A-Za-z0-9_]*)",
            command,
        )
        assert "git rev-parse HEAD" in text
        assert "^[0-9a-f]{40}$" in text


def _assert_rust_source_contract(source: str) -> None:
    assert '"native-app-payload"' in source
    assert '"native-server-binaries"' in source
    assert '"native-gstreamer-runtime"' not in source
    assert "SOURCE_BOUND_COMPONENTS.contains(&manifest.component.as_str())" in source
    assert '.get("source_sha")' in source
    assert "source_sha.len() != 40" in source
    assert "character.is_ascii_digit()" in source
    assert "(b'a'..=b'f').contains(&character)" in source
    assert '.get("civiccast_source_head")' in source
    assert "native-app-payload source SHA does not match civiccast_source_head" in source


def test_rust_native_pack_verifier_matches_the_source_sha_contract() -> None:
    _assert_rust_source_contract(RUST_NATIVE_PACKS.read_text(encoding="utf-8"))


def test_rust_native_pack_source_contract_rejects_component_list_drift() -> None:
    source = RUST_NATIVE_PACKS.read_text(encoding="utf-8")
    mutated = source.replace('"native-server-binaries"', '"removed-server-pack"', 1)
    assert mutated != source

    with pytest.raises(AssertionError):
        _assert_rust_source_contract(mutated)
