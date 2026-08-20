# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Collect a stable source-state envelope for local evidence artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


def collect_source_state(
    *, repo_root: Path | None = None, artifact_root: Path | None = None
) -> dict[str, Any]:
    """Return source-state metadata and optionally write supporting files.

    Hashes are computed over raw Git stdout bytes. That keeps PowerShell and
    Python callers from drifting on newline normalization.
    """

    root = (repo_root or Path(__file__).resolve().parents[1]).resolve()
    branch = _git_text(root, ["branch", "--show-current"]).strip()
    head = _git_text(root, ["rev-parse", "HEAD"]).strip() or _ci_head_sha()
    short_status = _git_bytes(root, ["status", "--short", "--branch"])
    porcelain_status = _git_bytes(root, ["status", "--porcelain=v1", "-uall"])
    diff_shortstat = _git_bytes(root, ["diff", "--shortstat"])
    diff_name_status = _git_bytes(root, ["diff", "HEAD", "--name-status"])
    diff_numstat = _git_bytes(root, ["diff", "HEAD", "--numstat"])
    diff_binary = _git_bytes(root, ["diff", "HEAD", "--binary"])
    untracked_files = _untracked_files(root)
    untracked_manifest, untracked_hash_blob = _untracked_hash_blob(root, untracked_files)
    source_hash_blob = b"\n".join(
        [
            b"tracked-diff",
            diff_binary,
            b"untracked-files",
            untracked_hash_blob,
        ]
    )
    status_entries = [line for line in _decode(porcelain_status).splitlines() if line.strip()]

    source_state = {
        "branch": branch,
        "head": head,
        "dirty": bool(porcelain_status.strip()),
        "status_sha256": hashlib.sha256(porcelain_status).hexdigest(),
        "diff_sha256": hashlib.sha256(source_hash_blob).hexdigest(),
        "diff_shortstat": _decode(diff_shortstat).strip(),
        "changed_files": status_entries,
        "tracked_changed_files": [
            line for line in _decode(diff_name_status).splitlines() if line.strip()
        ],
        "untracked_files": untracked_files,
        "untracked_content_sha256": hashlib.sha256(untracked_hash_blob).hexdigest(),
    }

    if artifact_root is not None:
        _write_artifacts(
            artifact_root.resolve(),
            branch=branch,
            head=head,
            short_status=short_status,
            porcelain_status=porcelain_status,
            diff_shortstat=diff_shortstat,
            diff_name_status=diff_name_status,
            diff_numstat=diff_numstat,
            diff_binary=diff_binary,
            untracked_manifest=untracked_manifest,
            source_hash_blob=source_hash_blob,
            source_state=source_state,
        )

    return source_state


def _git_bytes(repo_root: Path, args: list[str]) -> bytes:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )
    except OSError as exc:
        raise RuntimeError(f"git {' '.join(args)} failed to start: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        stderr = _decode(exc.stderr or b"").strip()
        detail = f": {stderr}" if stderr else ""
        raise RuntimeError(
            f"git {' '.join(args)} failed with exit code {exc.returncode}{detail}"
        ) from exc
    return result.stdout


def _git_text(repo_root: Path, args: list[str]) -> str:
    return _decode(_git_bytes(repo_root, args))


def _ci_head_sha() -> str:
    for name in (
        "CIVICAST_CI_SOURCE_SHA",
        "GITHUB_HEAD_SHA",
        "GITHUB_SHA",
        "CI_COMMIT_SHA",
        "BUILD_SOURCEVERSION",
    ):
        value = os.environ.get(name, "").strip()
        if re.fullmatch(r"[0-9a-fA-F]{40}", value):
            return value.lower()
    return ""


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _untracked_files(repo_root: Path) -> list[str]:
    raw = _git_bytes(repo_root, ["ls-files", "--others", "--exclude-standard"])
    return sorted(line for line in _decode(raw).splitlines() if line.strip())


def _untracked_hash_blob(repo_root: Path, paths: list[str]) -> tuple[str, bytes]:
    manifest_lines: list[str] = []
    blob_parts: list[bytes] = []
    for rel_path in paths:
        path = repo_root / rel_path
        if not path.is_file():
            continue
        data = path.read_bytes()
        content_hash = hashlib.sha256(data).hexdigest()
        manifest_lines.append(f"{content_hash}  {rel_path}")
        blob_parts.extend(
            [
                rel_path.encode("utf-8", errors="surrogateescape"),
                b"\0",
                data,
                b"\0",
            ]
        )
    manifest = "\n".join(manifest_lines)
    if manifest:
        manifest += "\n"
    return manifest, b"".join(blob_parts)


def _write_artifacts(
    artifact_root: Path,
    *,
    branch: str,
    head: str,
    short_status: bytes,
    porcelain_status: bytes,
    diff_shortstat: bytes,
    diff_name_status: bytes,
    diff_numstat: bytes,
    diff_binary: bytes,
    untracked_manifest: str,
    source_hash_blob: bytes,
    source_state: dict[str, Any],
) -> None:
    artifact_root.mkdir(parents=True, exist_ok=True)
    git_status_text = "\n".join(
        [
            f"Branch: {branch}",
            f"HEAD: {head}",
            "",
            _decode(short_status).rstrip("\n"),
            "",
        ]
    )
    (artifact_root / "git-status.txt").write_text(git_status_text, encoding="utf-8")
    (artifact_root / "git-status-porcelain.txt").write_bytes(porcelain_status)
    (artifact_root / "git-diff-shortstat.txt").write_bytes(diff_shortstat)
    (artifact_root / "git-diff-name-status.txt").write_bytes(diff_name_status)
    (artifact_root / "git-diff-numstat.txt").write_bytes(diff_numstat)
    (artifact_root / "git-diff.patch").write_bytes(diff_binary)
    (artifact_root / "git-untracked-manifest.txt").write_text(
        untracked_manifest,
        encoding="utf-8",
    )
    (artifact_root / "source-hash-input.bin").write_bytes(source_hash_blob)
    (artifact_root / "source-state.json").write_text(
        json.dumps(source_state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Git repository root. Defaults to the parent of this scripts directory.",
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=None,
        help="Optional artifact directory for git status, diff, and source-state files.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    source_state = collect_source_state(
        repo_root=args.repo_root,
        artifact_root=args.artifact_root,
    )
    print(json.dumps(source_state, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
