# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Emit a producer job's ``<job>-meta.json`` for the claims-evidence verifier (D3).

Every junit-producing job in ``ci-test.yml`` runs this after its checkout and
before uploading artifacts. The meta file records the job's OWN checked-out
commit, alongside the run identifiers, so the claims verifier
(``scripts/policy/check_claims_evidence.py``) can assert, per producer job:

* the checkout SHA the job actually tested equals the source identity the
  verifier itself resolved (the PR head SHA, never the synthetic merge
  commit `GITHUB_SHA` on `pull_request` events); and
* the artifact came from the SAME workflow run/attempt the verifier is
  evaluating, not a stale artifact from an earlier attempt.

Usage:
    python scripts/policy/emit_producer_meta.py --job-id test --out test-meta.json

Fields written: ``job_id``, ``sha`` (``git rev-parse HEAD`` in the current
checkout), ``run_id``, ``run_attempt`` (from ``GITHUB_RUN_ID`` /
``GITHUB_RUN_ATTEMPT``; empty string outside of Actions).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def current_head_sha(cwd: Path) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(f"git rev-parse HEAD failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def build_meta(job_id: str, cwd: Path) -> dict[str, str]:
    return {
        "job_id": job_id,
        "sha": current_head_sha(cwd),
        "run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", required=True, help="the producer job's static ID")
    parser.add_argument("--out", required=True, type=Path, help="output meta.json path")
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    try:
        meta = build_meta(args.job_id, args.cwd)
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    args.out.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.out}: {meta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
