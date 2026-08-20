# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Import-policy contracts for the v1.2 broker substrate boundary."""

from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "civiccast"


class TestBrokerImportPolicy:
    def test_platform_broker_exists_before_provider_import_policy_is_checked(self) -> None:
        broker_module = import_module("civiccast.platform.broker")
        violations: list[str] = []
        for path in SOURCE_ROOT.rglob("*.py"):
            relative = path.relative_to(ROOT)
            # Skip vendored third-party trees (e.g. the TSR sidecar's
            # node_modules), which may contain Python-2 tooling scripts that
            # ast.parse cannot read and that are not CivicCast source.
            if "node_modules" in relative.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    imported = [node.module or ""]
                else:
                    continue
                if any(
                    name == "nats" or name.startswith("nats.") for name in imported
                ) and not relative.as_posix().startswith("civiccast/platform/"):
                    violations.append(str(relative))

        assert broker_module.__name__ == "civiccast.platform.broker"
        assert violations == []

    def test_publish_seam_imports_platform_broker_contract(self) -> None:
        publish_files = sorted((SOURCE_ROOT / "publish").rglob("*.py"))
        importing_files = [
            path.relative_to(ROOT).as_posix()
            for path in publish_files
            if "civiccast.platform.broker" in path.read_text(encoding="utf-8")
        ]

        assert importing_files, (
            "Publish seam code must import civiccast.platform.broker instead of relying "
            "only on publish-local service/store contracts."
        )
