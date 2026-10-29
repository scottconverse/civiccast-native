# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Keep the existing zero-untriaged-findings policy for shipped native code."""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(report: dict, triage: dict, *, today: dt.date | None = None) -> list[str]:
    today = today or dt.date.today()
    allowed = set()
    for entry in triage["not_affected"]:
        # Findings must be tied to exact shipped component/version, evidence and
        # a bounded review period. Never carry blanket CPE/package exemptions.
        if not entry["reason"] or not entry["evidence"]:
            raise ValueError("Native triage requires a reason and evidence")
        if dt.date.fromisoformat(entry["review_by"]) < today:
            continue
        allowed.add((entry["package"], entry["version"], entry["id"]))
    matches = report["matches"]  # Missing/malformed scanner output cannot pass.
    failures = []
    for match in matches:
        key = (
            match["artifact"]["name"],
            match["artifact"]["version"],
            match["vulnerability"]["id"],
        )
        if key not in allowed:
            failures.append(" ".join(key))
    return sorted(set(failures))


if __name__ == "__main__":
    report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    triage = json.loads((ROOT / "security/native-audit-triage.json").read_text(encoding="utf-8"))
    failures = check(report, triage)
    if failures:
        print("Untriaged native findings:\n" + "\n".join(failures), file=sys.stderr)
        raise SystemExit(1)
    print("Native findings absent or individually evidenced as not affected.")
