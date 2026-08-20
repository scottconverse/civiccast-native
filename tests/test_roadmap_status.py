# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the roadmap-status verifier (scripts/roadmap_status.py).

The verifier's whole job is to fail closed: a row may only claim a status the
repository can actually prove. These tests pin that contract — a false "built"
claim, a regression, a malformed manifest, and an unresolved evidence pointer
must all be caught, and only genuinely-present evidence may pass.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

_SPEC = importlib.util.spec_from_file_location(
    "roadmap_status",
    Path(__file__).resolve().parents[1] / "scripts" / "roadmap_status.py",
)
rs = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = rs  # let dataclasses resolve the module's annotations
_SPEC.loader.exec_module(rs)


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #


def _make_repo(tmp_path: Path) -> Path:
    """A tiny fixture repo with one fully-built feature's evidence present."""
    repo = tmp_path / "repo"
    versions = repo / "civiccast" / "foo" / "migrations" / "versions"
    versions.mkdir(parents=True)
    (versions / "0099_foo.py").write_text(
        'revision = "0099_foo"\ndown_revision = "0098_bar"\n', encoding="utf-8"
    )
    (repo / "civiccast" / "foo" / "service.py").write_text(
        "class FooService:\n    pass\n", encoding="utf-8"
    )
    testdir = repo / "tests" / "foo"
    testdir.mkdir(parents=True)
    (testdir / "test_foo.py").write_text("def test_foo():\n    assert True\n", encoding="utf-8")
    return repo


def _built_row() -> dict:
    return {
        "id": "S99",
        "kind": "section",
        "title": "Foo",
        "source": "master §11 (S99)",
        "owning_step": 12,
        "disposition": "net-new",
        "status": "built",
        "evidence": {
            "migrations": ["0099_foo"],
            "modules": ["civiccast/foo/service.py"],
            "symbols": [{"file": "civiccast/foo/service.py", "name": "FooService"}],
            "tests": ["tests/foo"],
        },
    }


# --------------------------------------------------------------------------- #
# status computation + the actual>=asserted rule
# --------------------------------------------------------------------------- #


def test_built_row_with_present_evidence_passes(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    ok, results = rs.verify(repo, [_built_row()])
    assert ok is True
    assert results[0].actual == "built"
    assert results[0].present == results[0].total > 0


def test_false_built_claim_fails_closed(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    row = _built_row()
    row["evidence"]["migrations"] = ["0100_does_not_exist"]
    row["evidence"]["modules"] = ["civiccast/foo/missing.py"]
    row["evidence"]["symbols"] = [{"file": "civiccast/foo/missing.py", "name": "Nope"}]
    row["evidence"]["tests"] = ["tests/missing"]
    ok, results = rs.verify(repo, [row])
    assert ok is False
    assert results[0].actual == "unbuilt"


def test_built_with_one_missing_evidence_is_partial_and_fails(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    row = _built_row()
    row["evidence"]["tests"] = ["tests/missing"]  # 3 present, 1 absent
    ok, results = rs.verify(repo, [row])
    assert ok is False
    assert results[0].actual == "partial"


def test_partial_row_passes_when_some_evidence_present(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    row = _built_row()
    row["status"] = "partial"
    row["evidence"]["tests"] = ["tests/missing"]  # some present, some absent
    ok, results = rs.verify(repo, [row])
    assert ok is True
    assert results[0].actual == "partial"


def test_unbuilt_row_with_absent_evidence_passes(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    row = {
        "id": "S21",
        "kind": "section",
        "title": "Scheduled recording",
        "source": "master §11 (S21)",
        "owning_step": 12,
        "disposition": "net-new",
        "status": "unbuilt",
        "evidence": {
            "migrations": ["none"],
            "modules": ["civiccast/recording/scheduled.py"],
            "symbols": [
                {"file": "civiccast/recording/scheduled.py", "name": "ScheduledRecordingService"}
            ],
            "tests": ["tests/recording/test_scheduled_recording.py"],
        },
    }
    ok, results = rs.verify(repo, [row])
    assert ok is True
    assert results[0].actual == "unbuilt"


# --------------------------------------------------------------------------- #
# evidence resolvers
# --------------------------------------------------------------------------- #


def test_migration_resolver_matches_revision_assignment(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    assert rs.migration_exists(repo, "0099_foo") is True
    assert rs.migration_exists(repo, "0099") is False  # exact id only, no prefix match
    assert rs.migration_exists(repo, "none") is False


def test_symbol_resolver_absent_file_returns_false(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    assert rs.symbol_defined(repo, "civiccast/foo/service.py", "FooService") is True
    assert rs.symbol_defined(repo, "civiccast/foo/service.py", "MissingClass") is False
    assert rs.symbol_defined(repo, "civiccast/foo/gone.py", "FooService") is False


# --------------------------------------------------------------------------- #
# malformed manifests must raise (fail closed, not silently skip)
# --------------------------------------------------------------------------- #


def test_invalid_status_raises(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    row = _built_row()
    row["status"] = "shipped"  # not a valid status
    with pytest.raises(rs.ManifestError):
        rs.verify(repo, [row])


def test_missing_required_key_raises(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    row = _built_row()
    del row["status"]
    with pytest.raises(rs.ManifestError):
        rs.verify(repo, [row])


def test_unknown_evidence_group_raises(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    row = _built_row()
    row["evidence"]["artifacts"] = ["something"]  # not a known group
    with pytest.raises(rs.ManifestError):
        rs.verify(repo, [row])


def test_symbol_entry_requires_file_and_name_raises(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    row = _built_row()
    row["evidence"]["symbols"] = [{"file": "civiccast/foo/service.py"}]  # no name
    with pytest.raises(rs.ManifestError):
        rs.verify(repo, [row])


def test_duplicate_ids_raises() -> None:
    data = {"rows": [_built_row(), _built_row()]}
    with pytest.raises(rs.ManifestError):
        rs.parse_manifest(data)


def test_parse_manifest_requires_rows_key() -> None:
    with pytest.raises(rs.ManifestError):
        rs.parse_manifest([_built_row()])  # top-level list, no 'rows' wrapper


# --------------------------------------------------------------------------- #
# CLI: exit codes are the enforcement contract
# --------------------------------------------------------------------------- #


def _write_manifest(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "ROADMAP.status.yaml"
    path.write_text(yaml.safe_dump({"rows": rows}), encoding="utf-8")
    return path


def test_main_returns_zero_when_all_pass(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    manifest = _write_manifest(tmp_path, [_built_row()])
    rc = rs.main(["--manifest", str(manifest), "--repo", str(repo), "--check"])
    assert rc == 0


def test_main_returns_one_on_false_built(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    row = _built_row()
    row["evidence"]["modules"] = ["civiccast/foo/missing.py"]
    row["evidence"]["symbols"] = [{"file": "civiccast/foo/missing.py", "name": "Nope"}]
    row["evidence"]["migrations"] = ["0100_missing"]
    row["evidence"]["tests"] = ["tests/missing"]
    manifest = _write_manifest(tmp_path, [row])
    rc = rs.main(["--manifest", str(manifest), "--repo", str(repo), "--check"])
    assert rc == 1


def test_main_returns_two_on_malformed_manifest(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    row = _built_row()
    row["status"] = "shipped"
    manifest = _write_manifest(tmp_path, [row])
    rc = rs.main(["--manifest", str(manifest), "--repo", str(repo), "--check"])
    assert rc == 2


def test_main_returns_two_on_missing_manifest(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    rc = rs.main(["--manifest", str(tmp_path / "nope.yaml"), "--repo", str(repo), "--check"])
    assert rc == 2
