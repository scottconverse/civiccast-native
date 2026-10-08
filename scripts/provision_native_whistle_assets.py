#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Acquire the exact pinned Whistle model and Needle engine DLL for station packs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from civiccast.native.app_payload import WHISTLE_PACK_FILES  # noqa: E402
from civiccast.native.whistle_assets import (  # noqa: E402
    WhistleAssetError,
    provision_whistle_assets,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="pack root to populate")
    parser.add_argument(
        "--cache",
        type=Path,
        default=ROOT / "build" / "native-whistle-cache",
        help="build cache outside the pack root",
    )
    args = parser.parse_args(argv)
    try:
        assets = provision_whistle_assets(args.output.resolve(), cache=args.cache.resolve())
    except WhistleAssetError as exc:
        print(f"Whistle asset provisioning failed: {exc}", file=sys.stderr)
        return 1
    result = {
        name: {
            "path": str(path),
            "bytes": WHISTLE_PACK_FILES[name][0],
            "sha256": WHISTLE_PACK_FILES[name][1],
        }
        for name, path in sorted(assets.items())
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
