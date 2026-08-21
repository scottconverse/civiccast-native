# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Import-policy contracts for the broker substrate boundary.

NATS JetStream was removed from the product (owner decision 2026-08-20; see
ADR 0023, which supersedes ADR 0001). This module used to also assert the
v12 "no module outside civiccast/platform/ imports the nats provider"
boundary -- with the NATS provider gone (not a dependency, no import of it
anywhere in the tree), that assertion is permanently vacuous, so it was
removed rather than kept as dead weight.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "civiccast"


class TestBrokerImportPolicy:
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
