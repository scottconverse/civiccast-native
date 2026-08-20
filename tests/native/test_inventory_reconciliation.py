# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the WSL-to-native installed/runtime inventory reconciliation."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "prove_native_inventory_reconciliation.py"


def _load() -> object:
    assert SCRIPT_PATH.is_file(), (
        "create scripts/prove_native_inventory_reconciliation.py before claiming "
        "the mandatory WSL-versus-native inventory is reconciled"
    )
    spec = importlib.util.spec_from_file_location(
        "prove_native_inventory_reconciliation",
        SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_inventory_reconciliation_module_exists() -> None:
    assert SCRIPT_PATH.is_file()


def test_requirement_parser_evaluates_linux_and_windows_markers() -> None:
    proof = _load()
    requirements = """\
common-package==1.2.3
linux-only==2.0 ; sys_platform == 'linux'
windows-only==3.0 ; sys_platform == 'win32'
machine-package==4.0 ; platform_machine == 'x86_64'
"""

    linux = proof.parse_requirements(requirements, target="linux")
    windows = proof.parse_requirements(requirements, target="windows")

    assert linux == {
        "common-package": "1.2.3",
        "linux-only": "2.0",
        "machine-package": "4.0",
    }
    assert windows == {
        "common-package": "1.2.3",
        "machine-package": "4.0",
        "windows-only": "3.0",
    }


def test_bootstrap_parser_enumerates_the_literal_apt_install_set() -> None:
    proof = _load()
    bootstrap = """\
apt-get update
apt-get install -y \\
  python3 \\
  python3-venv \\
  ca-certificates \\
  tar
other-command
apt-get install -y "${downloaded_deb}"
"""

    assert proof.parse_bootstrap_apt_packages(bootstrap) == (
        "ca-certificates",
        "python3",
        "python3-venv",
        "tar",
    )


def test_reconciliation_covers_every_wsl_row_and_all_required_native_components() -> None:
    proof = _load()
    runtime_lock = {
        "artifacts": {
            name: {"version": version}
            for name, version in {
                "ffmpeg": "8.1",
                "nats": "2.14",
                "node": "24",
                "ollama": "0.30",
                "postgres": "17",
                "tsduck": "3.44",
            }.items()
        }
    }
    plan = "\n".join(
        (
            "CivicCast-Native-Core-<version>.ccpack",
            "CivicCast-Native-Captions-large-v3-<revision>.ccpack",
            "CivicCast-Native-Summary-gemma4-12b-<revision>.ccpack",
            "CivicCast-Native-Summary-gemma4-e4b-<revision>.ccpack",
            "CivicCast-Native-Translation-translategemma-4b-<revision>.ccpack",
            "required for a complete\ndefault station",
        )
    )

    report = proof.build_reconciliation(
        wsl_packages={"common-package": "1.0", "jeepney": "0.9"},
        native_packages={"common-package": "1.1", "colorama": "0.4"},
        apt_packages=("python3", "tar"),
        runtime_lock=runtime_lock,
        gstreamer_file_count=217,
        pack_plan=plan,
        source_identity={"installer_sha256": "a" * 64},
    )

    assert report["status"] == "RECONCILED"
    assert report["unreconciled"] == []
    assert report["candidate_readiness"] == "BLOCKED_ON_IMPLEMENTATION"
    assert {row["wsl_identity"] for row in report["rows"] if row["origin"] == "wsl-pip"} == {
        "common-package==1.0",
        "jeepney==0.9",
    }
    assert report["required_native_components"] == {
        "captions-large-v3": "planned-required-pack",
        "core": "partially-built",
        "ollama-runtime": "planned-core-pack",
        "postgresql-server": "built-runtime-closure",
        "nats-server": "built-runtime-closure",
        "summary-gemma4-12b": "planned-required-pack",
        "summary-gemma4-e4b": "planned-required-pack",
        "translation-translategemma-4b": "planned-required-pack",
    }
    assert report["summary"]["wsl_rows"] == 4
    assert report["summary"]["native_additions"] >= 8


def test_reconciliation_records_a_built_signed_caption_pack() -> None:
    proof = _load()
    runtime_lock = {
        "artifacts": {
            name: {"version": "1"}
            for name in ("ffmpeg", "nats", "node", "ollama", "postgres", "tsduck")
        }
    }
    plan = "\n".join(proof._REQUIRED_PACK_TOKENS)
    caption_pack = {
        "component": "captions-large-v3",
        "pack_bytes": 1_157_649_728,
        "pack_sha256": "9" * 64,
        "signing_key_id": "development-civiccast-native-test",
    }

    report = proof.build_reconciliation(
        wsl_packages={},
        native_packages={},
        apt_packages=(),
        runtime_lock=runtime_lock,
        gstreamer_file_count=217,
        pack_plan=plan,
        source_identity={},
        caption_pack=caption_pack,
    )

    assert report["required_native_components"]["captions-large-v3"] == (
        "built-signed-pack-development-trust"
    )
    assert "captions-large-v3" not in report["implementation_gaps"]
    caption_row = next(row for row in report["rows"] if row["origin"] == "wsl-model")
    assert caption_row["status"] == "built-signed-pack-development-trust"


def test_reconciliation_records_the_complete_built_distribution() -> None:
    proof = _load()
    runtime_lock = {
        "artifacts": {
            name: {"version": "1"}
            for name in ("ffmpeg", "nats", "node", "ollama", "postgres", "tsduck")
        }
    }
    plan = "\n".join(proof._REQUIRED_PACK_TOKENS)
    components = (
        "core",
        "captions-large-v3",
        "summary-gemma4-12b",
        "summary-gemma4-e4b",
        "translation-translategemma-4b",
    )
    distribution_report = {
        "schema_version": 1,
        "product": "civiccast-native",
        "product_version": "1.0.0-rc15",
        "channel": "beta",
        "signing_key_id": "development-civiccast-native-test",
        "created_epoch": 1_700_000_000,
        "packs": {
            component: {
                "filename": f"{component}.ccpack",
                "bytes": index + 1,
                "sha256": f"{index + 1:064x}",
            }
            for index, component in enumerate(components)
        },
        "total_pack_bytes": sum(range(1, len(components) + 1)),
        "channel_index": "beta.channel.json",
        "station_index": "station.ccstation",
    }

    report = proof.build_reconciliation(
        wsl_packages={},
        native_packages={},
        apt_packages=(),
        runtime_lock=runtime_lock,
        gstreamer_file_count=217,
        pack_plan=plan,
        source_identity={},
        distribution_report=distribution_report,
    )

    assert report["candidate_readiness"] == "READY_FOR_PROOF"
    assert report["implementation_gaps"] == []
    assert report["required_native_components"] == {
        "captions-large-v3": "built-signed-pack-development-trust",
        "core": "built-signed-pack-development-trust",
        "nats-server": "built-runtime-closure",
        "ollama-runtime": "built-runtime-closure",
        "postgresql-server": "built-runtime-closure",
        "summary-gemma4-12b": "built-signed-pack-development-trust",
        "summary-gemma4-e4b": "built-signed-pack-development-trust",
        "translation-translategemma-4b": "built-signed-pack-development-trust",
    }


def test_reconciliation_rejects_unmapped_wsl_packages_and_missing_required_packs() -> None:
    proof = _load()
    runtime_lock = {
        "artifacts": {
            name: {"version": "1"}
            for name in ("ffmpeg", "nats", "node", "ollama", "postgres", "tsduck")
        }
    }

    with pytest.raises(proof.InventoryReconciliationError, match="unreconciled"):
        proof.build_reconciliation(
            wsl_packages={"missing-from-native": "1.0"},
            native_packages={},
            apt_packages=("python3",),
            runtime_lock=runtime_lock,
            gstreamer_file_count=217,
            pack_plan="CivicCast-Native-Core-<version>.ccpack",
            source_identity={"installer_sha256": "a" * 64},
        )


def test_wheelhouse_only_application_requires_an_explicit_native_disposition() -> None:
    proof = _load()
    runtime_lock = {
        "artifacts": {
            name: {"version": "1"}
            for name in ("ffmpeg", "nats", "node", "ollama", "postgres", "tsduck")
        }
    }
    plan = "\n".join(proof._REQUIRED_PACK_TOKENS)
    common = {
        "wsl_packages": {"dependency": "1.0"},
        "native_packages": {"dependency": "1.0"},
        "wsl_wheelhouse_packages": {
            "civiccast": ("1.0.0rc18",),
            "dependency": ("1.0",),
        },
        "apt_packages": (),
        "runtime_lock": runtime_lock,
        "gstreamer_file_count": 217,
        "pack_plan": plan,
        "source_identity": {},
    }

    with pytest.raises(
        proof.InventoryReconciliationError,
        match=r"wheelhouse-only:civiccast==1\.0\.0rc18",
    ):
        proof.build_reconciliation(**common)

    report = proof.build_reconciliation(
        **common,
        wheel_only_dispositions={
            "civiccast": (
                "CivicCast application in the native Core pack",
                "the application wheel is installed as the immutable app payload",
            )
        },
    )

    app_row = next(
        row
        for row in report["rows"]
        if row["origin"] == "wsl-wheelhouse-only"
        and row["wsl_identity"] == "civiccast==1.0.0rc18"
    )
    assert app_row == {
        "origin": "wsl-wheelhouse-only",
        "wsl_identity": "civiccast==1.0.0rc18",
        "native_identity": "CivicCast application in the native Core pack",
        "disposition": "the application wheel is installed as the immutable app payload",
        "status": "explicitly-mapped",
    }
    assert report["summary"]["wsl_wheelhouse_distribution_versions"] == 2


def test_receipt_rendering_is_canonical_json() -> None:
    proof = _load()
    report = {"status": "RECONCILED", "rows": []}

    rendered = proof.render_report(report)

    assert rendered == json.dumps(report, indent=2, sort_keys=True) + "\n"
