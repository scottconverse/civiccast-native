# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Gate A verdict judge -- the machine verdict for station-acceptance.

Reads the evidence an `sandbox-lab/Run-GateA.ps1` run leaves in an output
directory (a Windows Sandbox clean install + activation + runtime + UI-render
+ clerk-loop + captions + product-egress-engine + bounded-soak pass) and
emits a single ``gate-a-verdict.json`` with an unambiguous PASS/FAIL verdict
and a per-check breakdown.

Why this exists: the project's historical failure mode is builder-authored
"it works" claims outrunning reality (see CLAUDE.md's Mandatory CivicCast
Cross-Agent Audit Protocol). Gate A replaces prose with a machine verdict.
This module is the judge -- it reads files, it does not run anything, and it
is FAIL-CLOSED: any missing file, unparseable JSON, or absent/wrong field is
a named FAIL, never an assumed PASS.

Required checks are the subset of the 3.0 MASTER spec's station-acceptance
gate (`docs/spec/3.0/civiccast-3.0-station-in-a-box-MASTER.md` §12, "Station
acceptance": "operator installs+commissions without terminal work ... runs
the three PEG channels ... publishes VOD from a recorded meeting ...")  that
a disposable, offline, no-SDI Windows Sandbox VM can exercise in minutes
rather than the full acceptance ladder's multi-hour/physical-hardware scope:

  install        -- installs without terminal work (silent installer, exit 0)
  activation      -- the K1 mandatory activation hook ran and staged the
                      station (activation-self-test.json + station-set.json
                      found post-install)
  runtime         -- the station comes up and answers health/console/portal
  t2_render       -- both UIs (portal, operator console) actually render
                      their SPA shell, not just serve a stub document
  t3_loop         -- the clerk loop (nonce -> first-admin -> upload -> package
                      -> approve/publish -> public listing) -- this IS
                      "publishes VOD from a recorded meeting" at Sandbox scale
  captions        -- the offline caption pipeline actually produced cues
  t4_engine       -- the product egress engine (GStreamer, not a fallback)
                      started and passed TSDuck transport-stream verification
                      -- this IS "runs a PEG channel ... TSDuck verify" at
                      Sandbox scale (one channel, offline, no SDI)
  t5_soak         -- the bounded soak stayed healthy for its whole window
  completion      -- the harness itself reached its own authoritative
                      completion signal (DONE.json, last_completed_step)

NOT covered here (see docs/ops/gate-a.md for the full boundary statement):
the 24h/72h real-hardware soaks, physical SDI proof, unattended reboot
survival, commissioning wizard UI walkthrough, and OTT-app checks that the
rest of §12 requires for actual release readiness. Those remain Gate B and
the existing Playwright/manual acceptance work; Gate A is a fast, cheap,
fail-closed floor that runs on every candidate build, not a replacement for
them.

t4_engine policy note: `PASS_FFMPEG_FALLBACK` is a FAIL for Gate A. The
ffmpeg synthetic-encoder fallback path in `In-Sandbox-Report.ps1` predates
S15 (CHANGELOG "Egress default engine flipped to GStreamer"); now that
GStreamer is the shipped default engine, a candidate that only proves the
fallback path has not proven what a real station actually runs. Only
`PASS_PRODUCT_ENGINE` passes this check.

Known harness quirk -- read before trusting a "the Aug-19 fixture is a clean
PASS" claim: the historical Aug-19 reference run this module's test fixture
(`tests/gate_a/fixtures/pass-2026-08-19/`) is copied from does NOT contain a
DONE.json. Every other check in that fixture is a genuine PASS, but the
`completion` check fails closed on it, so the overall fixture verdict is
FAIL, not PASS. This is real, not a fixture bug: the old harness was
monitored by a separate host-side watcher (`sandbox-lab/scripts/Watch-Run.ps1`)
that declares "done" the moment `T3T5-RESULT.txt` contains a `T5_RESULT=`
line -- racing ahead of `In-Sandbox-Report.ps1`'s own `finally` block, which
still had to stop its transcript, query the Windows Event Log, and write
DONE.json. The operator/watcher habit of closing the sandbox VM as soon as
the watcher printed "DONE" pre-empted that tail end of the script on every
run in `sandbox-lab/evidence/` and `sandbox-lab/output/`, including the
otherwise-clean Aug-19 run -- see `sandbox-lab/evidence/run2-summary.json`'s
own `harness_note` field for an earlier, independently-documented instance of
exactly this pattern. `Run-GateA.ps1` does not use Watch-Run.ps1; it uses
`Host-Launch-Sandbox-Test.ps1`'s own poll loop, which waits for the real
DONE.json (up to `-TimeoutMinutes`) before it will touch the VM. A real Gate
A run is therefore expected to produce a genuine DONE.json when the run
truly completes. This module deliberately does NOT special-case the missing
file to force a PASS on the historical fixture -- doing that would be
exactly the "authored truth" failure mode Gate A exists to eliminate. See
`docs/ops/gate-a.md` for the full writeup.

Usage:
    python scripts/gate_a_verdict.py <output_dir> \
        [--source-sha SHA] [--run-id ID] [--out PATH]

Exit code: 0 if the verdict is PASS, 1 if FAIL, 2 if the output directory
itself does not exist (a harness/usage error, not a station-acceptance
finding).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CheckResult:
    """The outcome of one required check. status is always PASS or FAIL."""

    status: str
    detail: str


def _pass(detail: str) -> CheckResult:
    return CheckResult(status="PASS", detail=detail)


def _fail(detail: str) -> CheckResult:
    return CheckResult(status="FAIL", detail=detail)


def _read_text(output_dir: Path, name: str) -> tuple[str | None, str | None]:
    """Read a text file, tolerating a UTF-8 BOM. Returns (content, error)."""
    path = output_dir / name
    if not path.is_file():
        return None, f"{name} not found at {path}"
    try:
        return path.read_text(encoding="utf-8-sig"), None
    except OSError as exc:
        return None, f"{name} could not be read: {exc}"
    except UnicodeDecodeError as exc:
        return None, f"{name} is not valid UTF-8: {exc}"


def _read_json(output_dir: Path, name: str) -> tuple[Any | None, str | None]:
    """Read+parse a JSON file, tolerating a UTF-8 BOM. Returns (data, error)."""
    text, err = _read_text(output_dir, name)
    if err is not None:
        return None, err
    assert text is not None
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return None, f"{name} is not valid JSON: {exc}"


def _line_matching(text: str, pattern: str) -> re.Match[str] | None:
    return re.search(pattern, text, re.MULTILINE)


# --------------------------------------------------------------------------
# Individual checks. Every function takes the output directory and returns a
# CheckResult. None of them raise on missing/malformed input -- every failure
# mode is a named FAIL detail string, per the module's fail-closed contract.
# --------------------------------------------------------------------------


def check_install(output_dir: Path) -> CheckResult:
    summary, err = _read_json(output_dir, "summary.json")
    if err is not None:
        return _fail(err)
    assert isinstance(summary, dict)
    exit_code = summary.get("installer_exit_code")
    if exit_code != 0:
        return _fail(f"summary.json.installer_exit_code={exit_code!r} (expected 0)")
    station_set = summary.get("station_set_json_found")
    if not station_set:
        return _fail(
            "summary.json.station_set_json_found is empty/null -- station-set.json not found after install"
        )
    return _pass(f"installer_exit_code=0, station_set_json_found={station_set}")


def check_activation(output_dir: Path) -> CheckResult:
    summary, err = _read_json(output_dir, "summary.json")
    if err is not None:
        return _fail(err)
    assert isinstance(summary, dict)
    activation_json = summary.get("activation_self_test_json_found")
    if not activation_json:
        return _fail(
            "summary.json.activation_self_test_json_found is empty/null -- "
            "activation-self-test.json not found after install"
        )
    text, terr = _read_text(output_dir, "ACTIVATION-RESULT.txt")
    if terr is not None:
        return _fail(terr)
    assert text is not None
    exit_match = _line_matching(text, r"^installer_exit_code=(-?\d+)")
    found_match = _line_matching(text, r"^station_set_json_found_after_install=(\d+)")
    if exit_match is None or exit_match.group(1) != "0":
        got = exit_match.group(1) if exit_match else "<missing>"
        return _fail(f"ACTIVATION-RESULT.txt installer_exit_code={got} (expected 0)")
    if found_match is None or found_match.group(1) != "1":
        got = found_match.group(1) if found_match else "<missing>"
        return _fail(
            f"ACTIVATION-RESULT.txt station_set_json_found_after_install={got} (expected 1)"
        )
    return _pass(
        f"activation_self_test_json_found={activation_json}, ACTIVATION-RESULT.txt confirms station-set staged"
    )


def check_runtime(output_dir: Path) -> CheckResult:
    summary, err = _read_json(output_dir, "summary.json")
    if err is not None:
        return _fail(err)
    assert isinstance(summary, dict)
    runtime_checks = summary.get("runtime_checks")
    if not isinstance(runtime_checks, dict):
        return _fail("summary.json.runtime_checks missing or not an object")
    parts: list[str] = []
    for surface in ("health", "operator_console", "resident_portal"):
        check = runtime_checks.get(surface)
        if not isinstance(check, dict):
            return _fail(f"summary.json.runtime_checks.{surface} missing or not an object")
        status = check.get("status")
        ok = check.get("ok")
        if status != 200 or ok is not True:
            return _fail(
                f"runtime_checks.{surface} status={status!r} ok={ok!r} (expected status:200 ok:true)"
            )
        parts.append(f"{surface}=200")
    return _pass(", ".join(parts))


def check_t2_render(output_dir: Path) -> CheckResult:
    text, err = _read_text(output_dir, "T2-RENDER-RESULT.txt")
    if err is not None:
        return _fail(err)
    assert text is not None
    if not _line_matching(text, r"^T2_RENDER=PASS\s*$"):
        return _fail("T2_RENDER=PASS line not found in T2-RENDER-RESULT.txt")
    portal_match = _line_matching(text, r"^T2_portal .*\bresult=(\S+)")
    operator_match = _line_matching(text, r"^T2_operator .*\bresult=(\S+)")
    if portal_match is None or portal_match.group(1) != "PASS":
        got = portal_match.group(1) if portal_match else "<missing>"
        return _fail(f"T2_portal result={got} (expected PASS)")
    if operator_match is None or operator_match.group(1) != "PASS":
        got = operator_match.group(1) if operator_match else "<missing>"
        return _fail(f"T2_operator result={got} (expected PASS)")
    return _pass("T2_RENDER=PASS; both T2_portal and T2_operator result=PASS")


def check_t3_loop(output_dir: Path) -> CheckResult:
    t35_text, err = _read_text(output_dir, "T3T5-RESULT.txt")
    if err is not None:
        return _fail(err)
    assert t35_text is not None
    if not _line_matching(t35_text, r"^T3_RESULT=PASS\s*$"):
        return _fail("T3_RESULT=PASS line not found in T3T5-RESULT.txt")
    loop_text, err2 = _read_text(output_dir, "T3-LOOP.txt")
    if err2 is not None:
        return _fail(err2)
    assert loop_text is not None
    if not _line_matching(loop_text, r"^T3_LOOP=PASS\s*$"):
        return _fail("T3_LOOP=PASS line not found in T3-LOOP.txt")
    return _pass(
        "T3_RESULT=PASS (T3T5-RESULT.txt), T3_LOOP=PASS (T3-LOOP.txt) -- clerk loop completed"
    )


def check_captions(output_dir: Path) -> CheckResult:
    loop_text, err = _read_text(output_dir, "T3-LOOP.txt")
    if err is not None:
        return _fail(err)
    assert loop_text is not None
    if not _line_matching(loop_text, r"^CAPTIONS=PASS\s*$"):
        return _fail("CAPTIONS=PASS line not found in T3-LOOP.txt")
    artifact, aerr = _read_json(output_dir, "T3-caption-artifact.json")
    if aerr is not None:
        return _fail(aerr)
    assert isinstance(artifact, dict)
    cue_count = artifact.get("cue_count")
    if not isinstance(cue_count, int) or isinstance(cue_count, bool) or cue_count <= 0:
        return _fail(f"T3-caption-artifact.json cue_count={cue_count!r} (expected an int > 0)")
    return _pass(f"CAPTIONS=PASS, cue_count={cue_count}")


def check_t4_engine(output_dir: Path) -> CheckResult:
    t35_text, err = _read_text(output_dir, "T3T5-RESULT.txt")
    if err is not None:
        return _fail(err)
    assert t35_text is not None
    match = _line_matching(t35_text, r"^T4_RESULT=(\S+)")
    if match is None:
        return _fail("T4_RESULT= line not found in T3T5-RESULT.txt")
    value = match.group(1)
    if value == "PASS_FFMPEG_FALLBACK":
        return _fail(
            "T4_RESULT=PASS_FFMPEG_FALLBACK -- the ffmpeg synthetic-encoder fallback proved egress, "
            "but GStreamer is the shipped default engine (S15); Gate A requires PASS_PRODUCT_ENGINE"
        )
    if value != "PASS_PRODUCT_ENGINE":
        return _fail(f"T4_RESULT={value} (expected PASS_PRODUCT_ENGINE)")
    return _pass("T4_RESULT=PASS_PRODUCT_ENGINE")


def check_t5_soak(output_dir: Path) -> CheckResult:
    t35_text, err = _read_text(output_dir, "T3T5-RESULT.txt")
    if err is not None:
        return _fail(err)
    assert t35_text is not None
    match = _line_matching(t35_text, r"^T5_RESULT=(\S+) beats=(\d+) unhealthy=(\d+)\s*$")
    if match is None:
        return _fail("T5_RESULT=... beats=... unhealthy=... line not found in T3T5-RESULT.txt")
    status, beats, unhealthy = match.group(1), int(match.group(2)), int(match.group(3))
    if status != "PASS":
        return _fail(f"T5_RESULT={status} (expected PASS)")
    if unhealthy != 0:
        return _fail(f"T5 unhealthy={unhealthy} (expected 0) over beats={beats}")
    return _pass(f"T5_RESULT=PASS beats={beats} unhealthy=0")


def check_completion(output_dir: Path) -> CheckResult:
    done, err = _read_json(output_dir, "DONE.json")
    if err is not None:
        return _fail(err)
    assert isinstance(done, dict)
    step = done.get("last_completed_step")
    if step != "t5-soak-complete":
        return _fail(f"DONE.json.last_completed_step={step!r} (expected 't5-soak-complete')")
    summary, serr = _read_json(output_dir, "summary.json")
    if serr is not None:
        return _fail(serr)
    assert isinstance(summary, dict)
    summary_step = summary.get("last_completed_step")
    if summary_step != "t5-soak-complete":
        return _fail(
            f"summary.json.last_completed_step={summary_step!r} does not match "
            "DONE.json.last_completed_step='t5-soak-complete'"
        )
    return _pass(
        "DONE.json present, last_completed_step=t5-soak-complete (confirmed in summary.json)"
    )


CHECKS: dict[str, Callable[[Path], CheckResult]] = {
    "install": check_install,
    "activation": check_activation,
    "runtime": check_runtime,
    "t2_render": check_t2_render,
    "t3_loop": check_t3_loop,
    "captions": check_captions,
    "t4_engine": check_t4_engine,
    "t5_soak": check_t5_soak,
    "completion": check_completion,
}


def judge(output_dir: Path, source_sha: str | None, run_id: str | None) -> dict[str, Any]:
    """Run every required check against output_dir and build the verdict document."""
    checks: dict[str, dict[str, str]] = {}
    for name, fn in CHECKS.items():
        try:
            result = fn(output_dir)
        except Exception as exc:  # fail-closed even on a bug in a check itself, never propagate
            result = _fail(f"unhandled exception while evaluating this check: {exc!r}")
        checks[name] = {"status": result.status, "detail": result.detail}

    verdict = "PASS" if all(c["status"] == "PASS" for c in checks.values()) else "FAIL"

    return {
        "schema_version": SCHEMA_VERSION,
        "source_sha": source_sha,
        "run_id": run_id,
        "verdict": verdict,
        "checks": checks,
        "evidence_dir": str(output_dir),
        "judged_utc": datetime.now(UTC).isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "output_dir", type=Path, help="Directory containing a Gate A sandbox run's evidence files"
    )
    parser.add_argument(
        "--source-sha",
        default=None,
        help="civiccast-native commit SHA the candidate was built from",
    )
    parser.add_argument(
        "--run-id", default=None, help="GitHub Actions run id of the candidate build"
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Where to write gate-a-verdict.json (default: <output_dir>/gate-a-verdict.json)",
    )
    args = parser.parse_args(argv)

    output_dir: Path = args.output_dir
    if not output_dir.is_dir():
        print(
            f"gate_a_verdict: harness error -- output directory does not exist: {output_dir}",
            file=sys.stderr,
        )
        return 2

    result = judge(output_dir, args.source_sha, args.run_id)
    out_path: Path = args.out if args.out is not None else output_dir / "gate-a-verdict.json"
    out_path.write_text(json.dumps(result, indent=2, sort_keys=False) + "\n", encoding="utf-8")

    print(json.dumps(result, indent=2, sort_keys=False))
    print(f"\ngate_a_verdict: {result['verdict']} (written to {out_path})", file=sys.stderr)

    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
