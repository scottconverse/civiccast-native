# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Independent-workspace reproducibility proof for the native app payload."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load() -> object:
    path = Path(__file__).resolve().parents[2] / "scripts" / "prove_native_app_reproducible.py"
    spec = importlib.util.spec_from_file_location(
        "prove_native_app_reproducible",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


proof = _load()


def test_independent_workspaces_must_be_distinct_and_not_nested(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    proof.assert_independent_workspaces(first, second)

    with pytest.raises(proof.ReproducibilityError, match="distinct"):
        proof.assert_independent_workspaces(first, first)
    nested = first / "nested"
    nested.mkdir()
    with pytest.raises(proof.ReproducibilityError, match="nested"):
        proof.assert_independent_workspaces(first, nested)


def test_tree_comparison_is_byte_exact_and_path_sensitive(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    for root in (first, second):
        (root / "Lib").mkdir()
        (root / "Lib" / "module.py").write_bytes(b"same bytes\n")
        (root / "SHA256SUMS").write_bytes(b"same trust artifact\n")

    receipt = proof.compare_payload_trees(first, second)

    assert receipt["file_count"] == 2
    assert receipt["total_bytes"] == 31
    assert len(receipt["tree_sha256"]) == 64

    (second / "Lib" / "module.py").write_bytes(b"different\n")
    with pytest.raises(proof.ReproducibilityError, match=r"Lib/module\.py"):
        proof.compare_payload_trees(first, second)

    (second / "Lib" / "module.py").write_bytes(b"same bytes\n")
    (second / "unexpected.txt").write_bytes(b"extra")
    with pytest.raises(proof.ReproducibilityError, match=r"unexpected\.txt"):
        proof.compare_payload_trees(first, second)


def test_manifests_must_bind_the_same_clean_source_and_toolchain(tmp_path: Path) -> None:
    source_state = {
        "head": "a" * 40,
        "dirty": False,
        "diff_sha256": "b" * 64,
        "status_sha256": "c" * 64,
    }
    manifest = {
        "schema_version": 6,
        "civiccast": {"source_state": source_state},
        "build_toolchain_lock_sha256": "d" * 64,
    }
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    for path in (first, second):
        path.write_text(json.dumps(manifest), encoding="utf-8")

    identity = proof.compare_manifest_provenance(first, second)
    assert identity == {
        "build_toolchain_lock_sha256": "d" * 64,
        "source_state": source_state,
    }

    changed = json.loads(second.read_text(encoding="utf-8"))
    changed["civiccast"]["source_state"]["dirty"] = True
    second.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(proof.ReproducibilityError, match="source provenance"):
        proof.compare_manifest_provenance(first, second)


def test_build_command_uses_each_workspace_venv_and_no_ambient_tools(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    output = tmp_path / "output"
    scratch = tmp_path / "scratch"
    interpreter = tmp_path / "python-embed.zip"
    reviewed_pyav = tmp_path / "av-18.0.0-cp311-abi3-win_amd64.whl"
    venv = scratch / "venv"

    command = proof.payload_build_command(
        workspace=workspace,
        output=output,
        scratch=scratch,
        interpreter_zip=interpreter,
        reviewed_pyav_wheel=reviewed_pyav,
        venv=venv,
        allow_dirty_source=False,
    )

    assert command == [
        str(venv / "Scripts" / "python.exe"),
        "-B",
        str(workspace / "scripts" / "build_native_app_payload.py"),
        "--out",
        str(output),
        "--interpreter-zip",
        str(interpreter),
        "--reviewed-pyav-wheel",
        str(reviewed_pyav),
        "--scratch",
        str(scratch / "build"),
    ]


def test_proof_receipt_is_canonical_and_records_both_workspace_roots(
    tmp_path: Path,
) -> None:
    receipt = proof.build_receipt(
        workspace_a=tmp_path / "a",
        workspace_b=tmp_path / "b",
        provenance={"source_state": {"head": "a" * 40}},
        comparison={"file_count": 1, "total_bytes": 2, "tree_sha256": "b" * 64},
    )
    rendered = proof.render_receipt(receipt)

    assert rendered == json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    assert receipt["result"] == "PASS"
    assert receipt["workspaces"]["a"] != receipt["workspaces"]["b"]
