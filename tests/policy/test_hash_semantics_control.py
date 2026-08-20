# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Committed control for git hash-object filtering semantics (CC-WS1-007).

Locks the corrected premise behind the evidence runner's blob-identity
binding, in a self-contained repo so this project's own filter config is
irrelevant: for a working file asserted to contain CRLF under a ``text``
attribute, plain named-file mode and explicit same-path ``--path`` mode
both apply the clean filter and equal the committed/index blob, while
``--no-filters`` hashes raw working bytes and differs. The prior false
premise ("plain mode is unfiltered") survived several audit rounds exactly
because no committed control asserted these equalities.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

GIT_ID = ["-c", "user.name=control", "-c", "user.email=control@example.invalid"]


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "core.autocrlf=false", *GIT_ID, *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return result.stdout.strip()


def test_crlf_filtering_semantics_control(tmp_path: Path) -> None:
    repo = tmp_path / "control"
    repo.mkdir()
    _git(repo, "init", "-q")
    # The text attribute alone drives filtering; autocrlf is pinned false on
    # every command so the host's global git config cannot influence results.
    (repo / ".gitattributes").write_bytes(b"*.txt text\n")
    crlf_file = repo / "sample.txt"
    crlf_file.write_bytes(b"line one\r\nline two\r\n")
    assert b"\r\n" in crlf_file.read_bytes(), "premise: working file contains CRLF"

    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "control")
    committed = _git(repo, "rev-parse", "HEAD:sample.txt")

    named_file = _git(repo, "hash-object", "sample.txt")
    explicit_path = _git(repo, "hash-object", "--path", "sample.txt", "sample.txt")
    no_filters = _git(repo, "hash-object", "--no-filters", "sample.txt")

    # Corrected semantics: both filtered forms equal the committed blob...
    assert named_file == committed, "plain named-file mode must apply the clean filter"
    assert explicit_path == committed, "--path mode must apply the clean filter"
    # ...and raw working bytes (CRLF) hash differently. If someone reintroduces
    # the false premise by expecting raw == filtered, this line goes red.
    assert no_filters != committed, "--no-filters must hash raw CRLF bytes, not the blob"
