#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Build the native app payload in two independent Windows workspaces.

This release gate bootstraps an isolated project environment in each checkout
from the same provisioned toolchain, runs each checkout's own builder, and then
requires byte-for-byte equality of every payload and trust-artifact path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


class ReproducibilityError(RuntimeError):
    """The two independently built payloads are not reproducible."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assert_independent_workspaces(first: Path, second: Path) -> None:
    """Require two existing, distinct, non-nested source workspaces."""

    first_resolved = first.resolve()
    second_resolved = second.resolve()
    if not first_resolved.is_dir() or not second_resolved.is_dir():
        raise ReproducibilityError("both independent workspaces must exist")
    if first_resolved == second_resolved:
        raise ReproducibilityError("independent workspaces must be distinct")
    if first_resolved in second_resolved.parents or second_resolved in first_resolved.parents:
        raise ReproducibilityError("independent workspaces must not be nested")


def _tree_index(root: Path) -> dict[str, tuple[int, str]]:
    if not root.is_dir():
        raise ReproducibilityError(f"payload tree does not exist: {root}")
    return {
        path.relative_to(root).as_posix(): (path.stat().st_size, _sha256_file(path))
        for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file())
    }


def _index_digest(index: Mapping[str, tuple[int, str]]) -> str:
    digest = hashlib.sha256()
    for relative, (size, sha256) in sorted(index.items()):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
        digest.update(sha256.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def compare_payload_trees(first: Path, second: Path) -> dict[str, int | str]:
    """Require identical file sets, sizes, and bytes across both payloads."""

    first_index = _tree_index(first)
    second_index = _tree_index(second)
    problems: list[str] = []
    for relative in sorted(first_index.keys() | second_index.keys()):
        if relative not in first_index:
            problems.append(f"{relative}: only in workspace B")
        elif relative not in second_index:
            problems.append(f"{relative}: only in workspace A")
        elif first_index[relative] != second_index[relative]:
            problems.append(f"{relative}: A={first_index[relative]} B={second_index[relative]}")
    if problems:
        preview = "\n".join(f"  - {problem}" for problem in problems[:50])
        raise ReproducibilityError(
            f"native app payloads differ in {len(problems)} path(s):\n{preview}"
        )
    return {
        "file_count": len(first_index),
        "total_bytes": sum(size for size, _sha256 in first_index.values()),
        "tree_sha256": _index_digest(first_index),
    }


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReproducibilityError(f"cannot read payload manifest {path}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ReproducibilityError(f"payload manifest is not an object: {path}")
    return parsed


def compare_manifest_provenance(
    first: Path,
    second: Path,
    *,
    require_clean: bool = True,
) -> dict[str, object]:
    """Require the same source identity and acquisition lock in both builds."""

    first_manifest = _read_manifest(first)
    second_manifest = _read_manifest(second)
    try:
        first_source = first_manifest["civiccast"]["source_state"]
        second_source = second_manifest["civiccast"]["source_state"]
        first_lock = first_manifest["build_toolchain_lock_sha256"]
        second_lock = second_manifest["build_toolchain_lock_sha256"]
    except (KeyError, TypeError) as exc:
        raise ReproducibilityError("payload manifest lacks required provenance") from exc
    if first_source != second_source:
        raise ReproducibilityError("workspace source provenance does not match")
    if first_lock != second_lock:
        raise ReproducibilityError("workspace build-toolchain locks do not match")
    if not isinstance(first_source, dict) or not isinstance(first_lock, str):
        raise ReproducibilityError("payload provenance has invalid types")
    if require_clean and first_source.get("dirty") is not False:
        raise ReproducibilityError("release reproducibility proof requires clean source")
    return {
        "build_toolchain_lock_sha256": first_lock,
        "source_state": first_source,
    }


def payload_build_command(
    *,
    workspace: Path,
    output: Path,
    scratch: Path,
    interpreter_zip: Path,
    reviewed_pyav_wheel: Path | None,
    venv: Path,
    allow_dirty_source: bool,
) -> list[str]:
    """Return the exact builder command for one independent workspace."""

    command = [
        str(venv / "Scripts" / "python.exe"),
        "-B",
        str(workspace / "scripts" / "build_native_app_payload.py"),
        "--out",
        str(output),
        "--interpreter-zip",
        str(interpreter_zip),
    ]
    if reviewed_pyav_wheel is not None:
        command.extend(["--reviewed-pyav-wheel", str(reviewed_pyav_wheel)])
    command.extend(["--scratch", str(scratch / "build")])
    if allow_dirty_source:
        command.append("--allow-dirty-source")
    return command


def _build_environment(
    toolchain: Path,
    *,
    venv: Path,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    environment = dict(os.environ if base is None else base)
    prefixes = [toolchain / "node", toolchain / "uv", toolchain / "python"]
    existing = environment.get("PATH", "")
    environment["PATH"] = ";".join([*(str(path) for path in prefixes), existing])
    environment["UV_PYTHON"] = str(toolchain / "python" / "python.exe")
    environment["UV_PYTHON_DOWNLOADS"] = "never"
    environment["CIVICCAST_UV_EXE"] = str(toolchain / "uv" / "uv.exe")
    environment["UV_PROJECT_ENVIRONMENT"] = str(venv)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def _bootstrap_workspace(
    workspace: Path,
    *,
    scratch: Path,
    toolchain: Path,
) -> Path:
    venv = scratch / "venv"
    environment = _build_environment(toolchain, venv=venv)
    subprocess.run(
        [
            str(toolchain / "uv" / "uv.exe"),
            "sync",
            "--frozen",
            "--all-groups",
            "--python",
            str(toolchain / "python" / "python.exe"),
            "--project",
            str(workspace),
        ],
        cwd=workspace,
        env=environment,
        check=True,
        timeout=30 * 60,
    )
    python = venv / "Scripts" / "python.exe"
    if not python.is_file():
        raise ReproducibilityError(f"workspace bootstrap produced no Python: {python}")
    return venv


def _build_workspace(
    workspace: Path,
    *,
    output: Path,
    scratch: Path,
    toolchain: Path,
    interpreter_zip: Path,
    reviewed_pyav_wheel: Path | None,
    allow_dirty_source: bool,
) -> None:
    venv = _bootstrap_workspace(workspace, scratch=scratch, toolchain=toolchain)
    environment = _build_environment(toolchain, venv=venv)
    subprocess.run(
        payload_build_command(
            workspace=workspace,
            output=output,
            scratch=scratch,
            interpreter_zip=interpreter_zip,
            reviewed_pyav_wheel=reviewed_pyav_wheel,
            venv=venv,
            allow_dirty_source=allow_dirty_source,
        ),
        cwd=workspace,
        env=environment,
        check=True,
        timeout=4 * 60 * 60,
    )


def build_receipt(
    *,
    workspace_a: Path,
    workspace_b: Path,
    provenance: Mapping[str, object],
    comparison: Mapping[str, int | str],
) -> dict[str, object]:
    """Build the durable, path-explicit PASS receipt."""

    return {
        "comparison": dict(comparison),
        "provenance": dict(provenance),
        "result": "PASS",
        "schema_version": 1,
        "workspaces": {
            "a": str(workspace_a.resolve()),
            "b": str(workspace_b.resolve()),
        },
    }


def render_receipt(receipt: Mapping[str, object]) -> str:
    return json.dumps(receipt, indent=2, sort_keys=True) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-a", required=True, type=Path)
    parser.add_argument("--workspace-b", required=True, type=Path)
    parser.add_argument("--output-a", required=True, type=Path)
    parser.add_argument("--output-b", required=True, type=Path)
    parser.add_argument("--scratch-a", required=True, type=Path)
    parser.add_argument("--scratch-b", required=True, type=Path)
    parser.add_argument("--toolchain", required=True, type=Path)
    parser.add_argument("--interpreter-zip", required=True, type=Path)
    parser.add_argument("--reviewed-pyav-wheel", type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--allow-dirty-source", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    workspace_a = args.workspace_a.resolve()
    workspace_b = args.workspace_b.resolve()
    assert_independent_workspaces(workspace_a, workspace_b)
    toolchain = args.toolchain.resolve()
    if not (toolchain / "toolchain-receipt.json").is_file():
        raise ReproducibilityError("provisioned toolchain receipt is missing")
    if not args.interpreter_zip.resolve().is_file():
        raise ReproducibilityError("pinned embeddable interpreter archive is missing")
    reviewed_pyav_wheel = (
        args.reviewed_pyav_wheel.resolve() if args.reviewed_pyav_wheel is not None else None
    )
    if reviewed_pyav_wheel is not None and not reviewed_pyav_wheel.is_file():
        raise ReproducibilityError("reviewed PyAV wheel is missing")

    _build_workspace(
        workspace_a,
        output=args.output_a.resolve(),
        scratch=args.scratch_a.resolve(),
        toolchain=toolchain,
        interpreter_zip=args.interpreter_zip.resolve(),
        reviewed_pyav_wheel=reviewed_pyav_wheel,
        allow_dirty_source=args.allow_dirty_source,
    )
    _build_workspace(
        workspace_b,
        output=args.output_b.resolve(),
        scratch=args.scratch_b.resolve(),
        toolchain=toolchain,
        interpreter_zip=args.interpreter_zip.resolve(),
        reviewed_pyav_wheel=reviewed_pyav_wheel,
        allow_dirty_source=args.allow_dirty_source,
    )
    provenance = compare_manifest_provenance(
        args.output_a.resolve() / "app-payload-manifest.json",
        args.output_b.resolve() / "app-payload-manifest.json",
        require_clean=not args.allow_dirty_source,
    )
    comparison = compare_payload_trees(
        args.output_a.resolve(),
        args.output_b.resolve(),
    )
    receipt = build_receipt(
        workspace_a=workspace_a,
        workspace_b=workspace_b,
        provenance=provenance,
        comparison=comparison,
    )
    receipt_path = args.receipt.resolve()
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(render_receipt(receipt), encoding="utf-8")
    print(render_receipt(receipt), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
