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
  t6_engine_soak  -- <gate-a-engine-soak> when SOAK_MINUTES.txt > 20: the
                      real product-engine soak (real assets, scheduled onto
                      all three PEG channels' real GStreamer egress engines,
                      TSDuck-verified every beat) passed. A no-op PASS when
                      SOAK_MINUTES.txt <= 20 (Gate A's own CI lanes, 10/20).
  completion      -- the harness itself reached its own authoritative
                      completion signal (DONE.json, last_completed_step)

NOT covered here (see docs/ops/gate-a.md for the full boundary statement):
the 24h/72h real-hardware soaks, physical SDI proof, unattended reboot
survival, commissioning wizard UI walkthrough, and OTT-app checks that the
rest of §12 requires for actual release readiness. Those remain Gate B and
the existing Playwright/manual acceptance work; Gate A is a fast, cheap,
fail-closed floor that runs on every candidate build, not a replacement for
them.

Shared-sandbox guard: Windows Sandbox is a single-instance-per-machine
resource shared with an independent, unrelated build system on the Gate A
runner box (see ``docs/ops/gate-a.md``, "Shared Windows Sandbox"). When
``sandbox-lab/Host-Launch-Sandbox-Test.ps1`` finds Windows Sandbox already
occupied and it stays busy for the whole ``-SandboxWaitMinutes`` wait
window, it writes ``SANDBOX-BUSY.txt`` into the output directory instead of
ever launching. This module checks for that file FIRST, before any of the
required checks run: its presence short-circuits the verdict to ``BUSY``
with an empty ``checks`` dict, never a per-check ``FAIL``. The distinction
matters because every required check would otherwise fail closed on files
that were never going to exist (no sandbox ever launched, so no
summary.json/DONE.json/etc.) -- that would read as a wall of station-
acceptance FAILs when the true condition is "the harness never got to run
because the resource was occupied by someone else." ``BUSY`` is a distinct,
third verdict value alongside ``PASS``/``FAIL`` for exactly this reason.

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

Mapped-folder stall guard: ``HARNESS_ERROR`` is the second non-verdict,
alongside ``BUSY`` above. ``BUSY`` means the run never started; this one
means it started and then lost its evidence channel.
``HOST-QUIET-SHARE.txt``, written by
``sandbox-lab/Host-Launch-Sandbox-Test.ps1`` when the Windows Sandbox mapped
output folder stops changing while the VM is still alive, produces
``verdict: "HARNESS_ERROR"`` and exit code 2. Unlike ``BUSY`` this does NOT
short-circuit the checks: a partially shipped run's real check results are
useful forensics and are still computed and recorded. They just do not
decide the verdict -- a run whose evidence never reached the host supports
no conclusion about the candidate, and calling that a station-acceptance
FAIL would be the same authored-truth failure this module exists to
prevent, pointed the other way.

Dirty lane <gate-a-dirty-lane>: ``--lane dirty`` adds three checks on top of
the unchanged clean set -- ``dirty_prep`` (the remnant prologue's
install/uninstall/preservation contract), ``dirty_survival`` (operator data
survived the uninstall -> reinstall cycle), and ``dirty_orphaned_tier``
(PR #80's orphaned-caption-tier fallback provably fired; a loud ``SKIP`` when
the runner staged no model seed). See docs/ops/gate-a.md, "Dirty lane". The
default ``--lane clean`` is byte-identical to the pre-dirty-lane judge.

Download-only lane <gate-a-download-only-lane>: ``--lane download-only`` adds
``dirty_prep`` and ``dirty_survival`` (the same cross-version upgrade
evidence the dirty lane's ``UPGRADE_MODE=1`` shape produces -- phase 1
installs a pinned previous candidate from its full kit) plus a new
``download_only_no_station_dir`` check, and deliberately does NOT add
``dirty_orphaned_tier`` (that remnant sub-shape is specific to the dirty
lane's uninstall-only path and is never authored here). The new check reads
``DOWNLOAD-ONLY-RESULT.txt`` and FAILS unless it proves the phase-2 payload
(the CURRENT candidate's setup.exe, run from a filtered payload directory
containing only ``setup.exe`` and ``packs`` -- no ``station`` directory) had
no station directory beside it, the phase-2 install and its D4 activation step
both exited 0, and the resulting ``station-set.json`` names the CURRENT
candidate's product version (proving the parallel "reuse an already-activated
station's cached model packs" change, not a stale receipt, is what let
activation succeed with no station directory present). See
docs/ops/gate-a.md, "Download-only lane".

Usage:
    python scripts/gate_a_verdict.py <output_dir> \
        [--source-sha SHA] [--run-id ID] [--lane clean|dirty|download-only] [--out PATH]

Exit code: 0 if the verdict is PASS, 1 if FAIL, 2 for anything that is not a
station-acceptance finding at all -- the output directory not existing, a
``BUSY`` verdict (SANDBOX-BUSY.txt: the run never executed because Windows
Sandbox was occupied by another process), or a ``HARNESS_ERROR`` verdict
(see ``HARNESS_ERROR_MARKERS``).
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

#: <gate-a-audit-BL-09> A floor on ``DONE.json.step_seq`` -- the harness's
#: MONOTONIC progress counter, incremented on every ``Save-Summary``. This
#: replaces the old self-comparison (summary.json.last_completed_step vs
#: DONE.json.last_completed_step, both written by one `finally` block from
#: one variable microseconds apart, so always equal). A genuine acceptance
#: run advances well past this; a run that crashed in its install phase
#: cannot reach it. Deliberately conservative: it is a floor on "the flow
#: actually ran", not a pin on the current step list, so adding or removing
#: a diagnostic step does not break the gate.
MINIMUM_STEP_SEQ = 25

#: Markers that mean "the harness broke", not "the product failed". Each maps
#: a filename dropped into the evidence directory to the explanation that
#: goes into the verdict document. A run carrying any of these is reported as
#: ``HARNESS_ERROR`` (exit 2) and never as ``FAIL`` -- the checks below may be
#: missing evidence purely because the evidence never arrived, so their
#: results describe the channel, not the candidate.
HARNESS_ERROR_MARKERS: dict[str, str] = {
    "HOST-QUIET-SHARE.txt": (
        "HOST-QUIET-SHARE.txt is present -- Host-Launch-Sandbox-Test.ps1 observed the Windows "
        "Sandbox mapped output folder stop changing while the VM was still alive, so the "
        "guest-to-host evidence channel (or the guest itself) was wedged. No station-acceptance "
        "conclusion can be drawn from this run"
    ),
}


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
    """The product egress engine ran AND its transport stream was analysed.

    <gate-a-audit-MA-27> The ``T4_RESULT=`` string alone is not enough. In
    Gate A run 33681670855 the harness's own ``Test-TsProof`` reported
    ``verdict: "pass"`` over a **0-byte** ``tsduck-engine-government-report.json``
    (``Get-Content -Raw`` on an empty file returns ``$null``, PowerShell's
    pipeline drops ``$null``, so ``ConvertFrom-Json`` never ran and never
    threw, and the three counters stayed at their initialised zeroes) --
    alongside ``"timed_out": true, "exit_code": null``. That produced
    ``T4_RESULT=PASS_PRODUCT_ENGINE`` and a judge PASS with **zero transport
    stream analysed**. The harness side is fixed; this reads the artifact so
    a future regression there cannot pass here either.
    """
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

    proof, perr = _read_json(output_dir, "egress-verify-engine.json")
    if perr is not None:
        return _fail(
            f"T4_RESULT=PASS_PRODUCT_ENGINE but the TSDuck proof artifact is unusable: {perr}"
        )
    assert isinstance(proof, dict)
    if proof.get("verdict") != "pass":
        return _fail(
            f"egress-verify-engine.json verdict={proof.get('verdict')!r} (expected 'pass')"
        )
    if proof.get("timed_out") is True:
        return _fail(
            "egress-verify-engine.json timed_out=true -- tsp was killed at its deadline, so "
            "nothing it left behind describes a completed analysis"
        )
    exit_code = proof.get("exit_code")
    if exit_code != 0:
        return _fail(f"egress-verify-engine.json exit_code={exit_code!r} (expected 0)")
    packets = proof.get("packets_total")
    if not isinstance(packets, int) or isinstance(packets, bool) or packets <= 0:
        return _fail(
            f"egress-verify-engine.json packets_total={packets!r} (expected an int > 0) -- a "
            "TSDuck report over zero packets is a report about nothing"
        )
    for field in ("invalid_syncs", "transport_errors", "discontinuities"):
        got = proof.get(field)
        if got != 0:
            return _fail(f"egress-verify-engine.json {field}={got!r} (expected 0)")
    return _pass(
        f"T4_RESULT=PASS_PRODUCT_ENGINE; tsp exited 0 over {packets} analysed packets with "
        "0 invalid syncs / transport errors / discontinuities"
    )


#: <gate-a-audit-MN-20> The floor on a soak that is allowed to say PASS. The
#: harness beats every 300s, so any nonzero soak window produces at least one
#: beat; the previous contract asserted only ``status=='PASS'`` and
#: ``unhealthy==0``, both of which a ``beats=0`` soak (``-SoakMinutes 0``,
#: whose loop body never executed) satisfied trivially.
T5_MINIMUM_BEATS = 1


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
    if beats < T5_MINIMUM_BEATS:
        return _fail(
            f"T5 beats={beats} (expected at least {T5_MINIMUM_BEATS}) -- a soak that never "
            "sampled the station proves nothing, and 'PASS with unhealthy=0' over zero beats is "
            "vacuously true"
        )
    if unhealthy != 0:
        return _fail(f"T5 unhealthy={unhealthy} (expected 0) over beats={beats}")
    return _pass(f"T5_RESULT=PASS beats={beats} unhealthy=0")


def check_t6_engine_soak(output_dir: Path) -> CheckResult:
    """The T6 real product-engine soak, gated by SOAK_MINUTES.txt.

    <gate-a-engine-soak> T5's health-only loop only proves ``/api/health``
    answered every 300s; it says nothing about the station's own GStreamer
    egress engine. ``In-Sandbox-Report.ps1`` runs T6 instead of T5's
    health-only loop whenever ``SOAK_MINUTES.txt`` is present and its value
    is > 20 minutes: real assets scheduled onto all three PEG channels' real
    egress engines, verified with TSDuck every beat, for the whole window.

    ``SOAK_MINUTES.txt <= 20`` (Gate A's own CI lanes, 10/20) never runs T6
    at all -- this check is a PASS no-op for them, exactly preserving the
    pre-T6 verdict for every existing lane. ``> 20`` (the manual/soak-runner
    lane, e.g. ``-SoakMinutes 480``) requires a real ``T6_RESULT=PASS`` line;
    anything else -- ``FAIL``, ``FAIL_EARLY``, ``SKIPPED``, or the line being
    entirely absent -- is a FAIL here, and therefore of the whole verdict.
    """
    soak_text, _soak_err = _read_text(output_dir, "SOAK_MINUTES.txt")
    soak_minutes = 0
    if soak_text is not None:
        try:
            soak_minutes = int(soak_text.strip().splitlines()[0])
        except (ValueError, IndexError):
            soak_minutes = 0
    if soak_minutes <= 20:
        return _pass(
            f"SOAK_MINUTES.txt={soak_minutes} (<=20) -- T6 real-engine soak is not required for "
            "this lane; T5's health-only soak (t5_soak check) covers it"
        )

    t35_text, err = _read_text(output_dir, "T3T5-RESULT.txt")
    if err is not None:
        return _fail(err)
    assert t35_text is not None
    match = _line_matching(t35_text, r"^T6_RESULT=(\S+)")
    if match is None:
        return _fail(
            f"SOAK_MINUTES.txt={soak_minutes} (>20) requires a T6_RESULT= line in "
            "T3T5-RESULT.txt, but none was found"
        )
    value = match.group(1)
    if value != "PASS":
        return _fail(f"T6_RESULT={value} (expected PASS) -- see T6-SOAK.txt / T6-ENGINE-NOTES.txt")
    return _pass(f"SOAK_MINUTES.txt={soak_minutes}, T6_RESULT=PASS")


def check_install_progress(output_dir: Path) -> CheckResult:
    """The installer's own breadcrumb log says the postinstall chain SUCCEEDED.

    <gate-a-audit-MA-25> ``check_install`` asserts only
    ``installer_exit_code == 0`` plus a truthy ``station_set_json_found``
    *path string* it never opens, and the ``D3_ENGINE_EXIT`` gate existed
    only in the dirty and download-only lanes. The pre-#143 installer exited
    0 on a rolled-back upgrade and today's evidence carries the proof:

        [16:37:51] postinstall: COMPLETED WITH A D3 ROLLBACK (... unchanged at
        1.0.0-beta.2 ...)     installer_exit_code=0

    Phase 1 of that same run logged ``route=FRESH_INSTALL engine_exit=11``
    and no check in any lane looked at it. install-progress.log is already
    copied into every evidence directory; this grades it, in every lane.
    """
    text, err = _read_text(output_dir, "INSTALL-PROGRESS-RESULT.txt")
    if err is not None:
        return _fail(err)
    assert text is not None

    outcome = _dirty_line(text, "POSTINSTALL_OUTCOME")
    if outcome != "SUCCESS":
        return _fail(
            f"INSTALL-PROGRESS-RESULT.txt POSTINSTALL_OUTCOME={outcome or '<missing>'} "
            "(expected SUCCESS) -- 'FAILED' and 'COMPLETED WITH A D3 ROLLBACK' are both "
            "compatible with installer_exit_code=0 and neither is a completed install"
        )
    alerts = _dirty_line(text, "POSTINSTALL_ALERTS")
    if alerts != "0":
        return _fail(
            f"INSTALL-PROGRESS-RESULT.txt POSTINSTALL_ALERTS={alerts or '<missing>'} (expected 0) "
            "-- the installer raised at least one operator ALERT during this install"
        )
    nonzero = _dirty_line(text, "POSTINSTALL_NONZERO_STEPS")
    if nonzero != "none":
        return _fail(
            f"INSTALL-PROGRESS-RESULT.txt POSTINSTALL_NONZERO_STEPS={nonzero or '<missing>'} "
            "(expected none) -- a d2/d3/d4 step returned a nonzero exit during this install"
        )
    d4 = _dirty_line(text, "D4_ACTIVATE_EXIT")
    if d4 not in ("0", "MISSING"):
        # MISSING is legitimate on a route that skips activation entirely;
        # a recorded nonzero never is.
        return _fail(f"INSTALL-PROGRESS-RESULT.txt D4_ACTIVATE_EXIT={d4} (expected 0)")
    return _pass(
        f"postinstall reached SUCCESS with 0 ALERTs, no nonzero d2/d3/d4 step, "
        f"D4_ACTIVATE_EXIT={d4}"
    )


def detect_harness_error(output_dir: Path) -> str | None:
    """Return the harness-error detail if the evidence carries a marker, else None.

    Checked before the verdict is decided (and inside ``check_completion``, so
    the per-check breakdown names the real cause rather than a misleading
    "DONE.json not found"). Markers are ordered by ``HARNESS_ERROR_MARKERS``
    insertion order; the first present wins.
    """
    for name, detail in HARNESS_ERROR_MARKERS.items():
        if (output_dir / name).is_file():
            return detail
    return None


def check_completion(output_dir: Path) -> CheckResult:
    """The harness reached its own authoritative completion signal.

    Contract as of the gate-a-station-up-wait-and-log-capture change: gated
    on ``DONE.json.harness_completed is True`` and the ABSENCE of
    ``WATCHDOG-TIMEOUT.txt`` / ``STALL-TIMEOUT.txt`` -- not on a specific
    ``last_completed_step`` string. The previous contract required
    ``last_completed_step == "t5-soak-complete"``, but
    ``In-Sandbox-Report.ps1`` always runs two more numbered steps after T5
    (install-progress-log-copied, event-log-checked) and then its own
    ``finally`` block, every one of which legitimately advances
    ``last_completed_step`` past T5 -- so that contract could never actually
    pass on a real, fully-completed run (it only ever "passed" in this
    module's own synthetic test fixture, which fabricated the stale value
    directly). ``harness_completed`` is a dedicated, stable field the
    `finally` block sets unconditionally right before writing DONE.json, so
    the completion contract no longer depends on how many diagnostic steps
    happen to run after T5.

    A run the watchdog force-completed (``WATCHDOG-TIMEOUT.txt`` present, or
    ``DONE.json.watchdog_timeout is True``) is a FAIL here even if a
    DONE.json exists -- the watchdog's placeholder DONE.json is a bounded
    escape hatch for the HOST's poll loop, not a real completion.

    ``STALL-TIMEOUT.txt`` is a second, narrower watchdog trigger (added
    after 8579e66-run4, which stalled 6+ minutes past
    'station-diag-captured-after-t3t5' with no forward progress and no
    DONE.json): the same background watchdog process polls
    ``summary.json.last_completed_step`` every 30s once the run reaches the
    runtime verdict, and fires if that step stops changing for 8 minutes --
    a much tighter bound than the overall ``-MaxScriptMinutes`` deadline.
    Its presence is a FAIL here for the same reason as
    ``WATCHDOG-TIMEOUT.txt``: a stall-forced placeholder DONE.json is not a
    genuine completion.

    A harness-error marker (see ``HARNESS_ERROR_MARKERS``) is reported here
    first, so the per-check breakdown names the real cause -- "the evidence
    channel broke" -- instead of the misleading downstream symptom "DONE.json
    not found". The overall verdict for such a run is ``HARNESS_ERROR``, not
    ``FAIL``; see ``judge``.
    """
    harness_error = detect_harness_error(output_dir)
    if harness_error is not None:
        return _fail(harness_error)
    if (output_dir / "WATCHDOG-TIMEOUT.txt").is_file():
        return _fail(
            "WATCHDOG-TIMEOUT.txt is present -- the harness hit its bounded script-level "
            "watchdog before completing; this is not a genuine run completion"
        )
    if (output_dir / "STALL-TIMEOUT.txt").is_file():
        return _fail(
            "STALL-TIMEOUT.txt is present -- the watchdog detected last_completed_step had "
            "stopped advancing (stalled) before the run completed; this is not a genuine run "
            "completion"
        )
    done, err = _read_json(output_dir, "DONE.json")
    if err is not None:
        return _fail(err)
    assert isinstance(done, dict)
    if done.get("watchdog_timeout") is True:
        return _fail(
            "DONE.json.watchdog_timeout=true -- the watchdog fired, not a genuine completion"
        )
    if done.get("stall_timeout") is True:
        return _fail(
            "DONE.json.stall_timeout=true -- the watchdog detected a stall, not a genuine completion"
        )
    if done.get("harness_completed") is not True:
        return _fail(
            f"DONE.json.harness_completed={done.get('harness_completed')!r} (expected true)"
        )
    top_level_error = done.get("top_level_error")
    if top_level_error:
        return _fail(
            f"DONE.json.top_level_error={top_level_error!r} -- the harness's main try block threw "
            "and its catch recorded the failure; this run did not complete its acceptance flow"
        )
    summary, serr = _read_json(output_dir, "summary.json")
    if serr is not None:
        return _fail(serr)
    assert isinstance(summary, dict)

    # <gate-a-audit-BL-09> The OLD cross-check here compared
    # summary.json.last_completed_step to DONE.json.last_completed_step --
    # two fields the harness's own `finally` block writes microseconds apart
    # from the SAME $summary variable, so they were always equal and always
    # 'finally-block'. That is the textbook self-comparison, sitting in the
    # check whose entire job is to prove the run happened. It is replaced by
    # assertions on values a crashed run genuinely cannot produce.
    summary_error = summary.get("top_level_error")
    if summary_error:
        return _fail(
            f"summary.json.top_level_error={summary_error!r} -- the harness recorded a top-level "
            "failure; this run did not complete its acceptance flow"
        )
    if summary.get("harness_completed") is not True:
        return _fail(
            f"summary.json.harness_completed={summary.get('harness_completed')!r} (expected true)"
        )
    errors = summary.get("errors")
    if isinstance(errors, list):
        fatal = [e for e in errors if isinstance(e, str) and e.startswith("top-level failure:")]
        if fatal:
            return _fail(
                f"summary.json.errors carries {len(fatal)} top-level failure entr"
                f"{'y' if len(fatal) == 1 else 'ies'}: {fatal[0]!r}"
            )
    write_errors, _werr = _read_text(output_dir, "summary-write-errors.log")
    if write_errors is not None and write_errors.strip():
        return _fail(
            "summary-write-errors.log is non-empty -- the harness could not write part of its own "
            f"evidence: {write_errors.strip().splitlines()[0]!r}"
        )
    if not done.get("run_end_utc"):
        return _fail("DONE.json.run_end_utc is missing -- the harness never reached its own end")
    step_seq = done.get("step_seq")
    if not isinstance(step_seq, int) or isinstance(step_seq, bool) or step_seq < MINIMUM_STEP_SEQ:
        return _fail(
            f"DONE.json.step_seq={step_seq!r} (expected an int >= {MINIMUM_STEP_SEQ}) -- a run "
            "that advanced fewer steps than the acceptance flow contains did not run it"
        )
    done_step = done.get("last_completed_step")
    return _pass(
        f"DONE.json present, harness_completed=true, step_seq={step_seq}, "
        f"run_end_utc recorded, last_completed_step={done_step!r}"
    )


# --------------------------------------------------------------------------
# Dirty-lane checks <gate-a-dirty-lane>. Run IN ADDITION to every clean-lane
# check when the judge is invoked with --lane dirty (Run-GateA.ps1
# -DirtyLane). The dirty lane's evidence contract is written by
# In-Sandbox-Report.ps1's remnant prologue (DIRTY-PREP-RESULT.txt) and its
# post-station-up survival verify (DIRTY-RESULT.txt); see
# docs/ops/gate-a.md, "Dirty lane" for the remnant shapes covered and the
# field failures (weeks of clean-sandbox-green / real-machine-dead installs,
# most recently DESKTOP-2BR3SJR's #18 receipt crash, PR #80) this lane
# exists to catch before customers do.
#
# One status beyond PASS/FAIL exists here and ONLY here: ``SKIP``, used
# exclusively by ``check_dirty_orphaned_tier`` when the run's own evidence
# says the orphaned large-v3 remnant was not seeded (the real model was not
# staged on the runner). A SKIP never silently passes -- it is surfaced in
# the verdict document and the workflow's run summary as an uncovered shape.
# --------------------------------------------------------------------------


def _dirty_line(text: str, key: str) -> str | None:
    match = _line_matching(text, rf"^{re.escape(key)}=(\S+)")
    return match.group(1) if match else None


def _post_upgrade_revision_failure(text: str, source: str) -> str | None:
    """Return a FAIL detail when the post-upgrade schema proof does not hold.

    <gate-a-audit-BL-10> THE central finding of the installer-path audit.
    PR #143 added ``POST_UPGRADE_DB_REVISION_MATCHES_HEAD`` to both upgrade
    lanes on the stated ground that "a healthy station-up body and
    ``D3_ENGINE_EXIT=0`` are no longer treated as proof by themselves." The
    flag was computed as::

        $healthRes.ok -and $rev -ne '<unavailable>' -and ($rev -eq $expectedHead)

    Follow the operands back: ``$healthRes.ok`` requires
    ``body_schema -eq 'current'``; ``civiccast/app.py`` sources BOTH
    ``schema_db_revision`` and ``schema_expected_head`` from one
    ``SchemaStatus``; and ``civiccast/schema_check.py``'s
    ``evaluate_schema_currency`` returns ``state="current"`` **if and only
    if** ``db_revision == expected_head``. So ``MATCHES_HEAD`` was 1 whenever
    ``ok`` was 1 -- always. The guard written to stop trusting a label was
    itself the label, and this judge only read the two revisions to build an
    error message, never re-deriving the match from them.

    The contract now, in the order it is checked:

    1. ``POST_UPGRADE_DB_REVISION_PSQL`` -- the LIVE database's own
       ``alembic_version`` row, read in the sandbox with ``psql`` straight out
       of the station's Postgres. It does not travel through ``/health``, the
       running control plane, or any code path that also computes a head.
    2. ``KIT_EXPECTED_HEAD`` -- the head the CI job derived at BUILD time from
       the candidate's own migration files
       (``scripts/gate_a_expected_head.py``), handed to the run as an input.
    3. The judge re-derives ``matches`` from those two and FAILs on
       inequality -- so this check can fail on its own, with the station-up
       check green.
    4. Cross-checks: the harness's own ``MATCHES_HEAD`` flag must agree with
       the re-derived answer, and ``/health``'s reported revision must agree
       with the database's. Disagreement is a FAIL naming the inconsistency,
       because inconsistent evidence supports no verdict in either direction.
    """
    psql_revision = _dirty_line(text, "POST_UPGRADE_DB_REVISION_PSQL")
    kit_head = _dirty_line(text, "KIT_EXPECTED_HEAD")
    health_revision = _dirty_line(text, "POST_UPGRADE_DB_REVISION")
    reported_matches = _dirty_line(text, "POST_UPGRADE_DB_REVISION_MATCHES_HEAD")

    if psql_revision is None or psql_revision.startswith("<"):
        return (
            f"{source} POST_UPGRADE_DB_REVISION_PSQL={psql_revision or '<missing>'} -- the "
            "database's own alembic_version row could not be read. This is the ONLY operand of "
            "the post-upgrade schema proof that does not come from the station's own /health "
            "self-report, so its absence is a FAIL, never an assumed pass"
        )
    if kit_head is None or kit_head.startswith("<"):
        return (
            f"{source} KIT_EXPECTED_HEAD={kit_head or '<missing>'} -- no build-time migration "
            "head was recorded for this candidate (Run-GateA.ps1 -ExpectedMigrationHead / the "
            "workflow's 'Record the candidate's migration head' step). Without it the only "
            "available expected head is the one the station under test computed about itself, "
            "which is exactly the self-comparison this check exists to end"
        )
    derived_matches = psql_revision == kit_head
    if not derived_matches:
        return (
            f"{source}: the live database is at revision {psql_revision!r} (read directly with "
            f"psql) but the candidate's build-time migration head is {kit_head!r}. The upgrade "
            "did not land the schema the shipped code expects"
        )
    if reported_matches != "1":
        return (
            f"{source} POST_UPGRADE_DB_REVISION_MATCHES_HEAD={reported_matches or '<missing>'} "
            f"while the independent evidence agrees (psql revision {psql_revision!r} == "
            f"build-time head {kit_head!r}). Inconsistent evidence supports no verdict"
        )
    if health_revision and not health_revision.startswith("<") and health_revision != psql_revision:
        return (
            f"{source}: /health reported schema_db_revision={health_revision!r} but the database "
            f"itself is at {psql_revision!r}. The station's self-report disagrees with its own "
            "database -- most likely /health's boot-time snapshot is stale"
        )
    return None


def check_dirty_prep(output_dir: Path) -> CheckResult:
    """Grade either dirty-lane preparation shape.

    Upgrade mode installs a hash-distinct previous candidate and leaves it
    live for the current setup to replace. Legacy remnant mode retains the
    same-candidate install/uninstall/preservation contract.
    """
    text, err = _read_text(output_dir, "DIRTY-PREP-RESULT.txt")
    if err is not None:
        return _fail(err)
    assert text is not None
    if _dirty_line(text, "UPGRADE_MODE") == "1":
        upgrade_expectations = {
            "PHASE1_INSTALL_EXIT": "0",
            "UPGRADE_OVER_LIVE_REQUESTED": "1",
        }
        for key, want in upgrade_expectations.items():
            got = _dirty_line(text, key)
            if got != want:
                return _fail(f"DIRTY-PREP-RESULT.txt {key}={got or '<missing>'} (expected {want})")
        previous_hash = _dirty_line(text, "PREVIOUS_INSTALLER_SHA256")
        current_hash = _dirty_line(text, "CURRENT_INSTALLER_SHA256")
        for label, value in (
            ("PREVIOUS_INSTALLER_SHA256", previous_hash),
            ("CURRENT_INSTALLER_SHA256", current_hash),
        ):
            if value is None or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                return _fail(
                    f"DIRTY-PREP-RESULT.txt {label}={value or '<missing>'} "
                    "(expected lowercase SHA-256)"
                )
        if previous_hash == current_hash:
            return _fail(
                "previous and current installer SHA-256 identities are identical -- this is "
                "a same-candidate reinstall, not a cross-version upgrade"
            )
        previous_version = _dirty_line(text, "PREVIOUS_PRODUCT_VERSION")
        current_version = _dirty_line(text, "CURRENT_PRODUCT_VERSION")
        for label, value in (
            ("PREVIOUS_PRODUCT_VERSION", previous_version),
            ("CURRENT_PRODUCT_VERSION", current_version),
        ):
            if value is None or value.startswith("<"):
                return _fail(
                    f"DIRTY-PREP-RESULT.txt {label}={value or '<missing>'} "
                    "(expected the installer product version)"
                )
        if previous_version == current_version:
            return _fail(
                "previous and current product versions are identical -- D3 would route "
                "SAME_VERSION_NO_OP instead of exercising the upgrade lifecycle"
            )
        return _pass(
            "cross-version upgrade prepared: previous candidate installed live; installer "
            "SHA-256 and product-version identities are distinct"
        )

    expectations = {
        "PHASE1_INSTALL_EXIT": "0",
        "UNINSTALL_EXIT": "0",
        "PGDATA_PRESERVED_AFTER_UNINSTALL": "1",
        "UPLOADS_PRESERVED_AFTER_UNINSTALL": "1",
        "INSTALL_TREE_REMOVED_AFTER_UNINSTALL": "1",
    }
    for key, want in expectations.items():
        got = _dirty_line(text, key)
        if got != want:
            return _fail(f"DIRTY-PREP-RESULT.txt {key}={got or '<missing>'} (expected {want})")
    return _pass(
        "phase-1 install + real uninstall completed; uninstall preserved pgdata and uploads "
        "and removed the install tree"
    )


def check_dirty_survival(output_dir: Path) -> CheckResult:
    """Operator data survived the full uninstall -> reinstall -> station-up
    cycle: the SAME pgdata cluster (creation time + PG_VERSION identity) and
    byte-identical planted uploads."""
    text, err = _read_text(output_dir, "DIRTY-RESULT.txt")
    if err is not None:
        return _fail(err)
    assert text is not None
    if _dirty_line(text, "UPGRADE_MODE") == "1":
        current_exit = _dirty_line(text, "UPGRADE_CURRENT_INSTALL_EXIT")
        if current_exit != "0":
            return _fail(
                "DIRTY-RESULT.txt "
                f"UPGRADE_CURRENT_INSTALL_EXIT={current_exit or '<missing>'} (expected 0)"
            )
        d3_route = _dirty_line(text, "D3_ROUTE")
        if d3_route != "UPGRADE":
            return _fail(
                f"DIRTY-RESULT.txt D3_ROUTE={d3_route or '<missing>'} (expected UPGRADE); "
                "FRESH_INSTALL and SAME_VERSION_NO_OP are successful installer routes but "
                "do not prove a cross-version upgrade"
            )
        d3_engine_exit = _dirty_line(text, "D3_ENGINE_EXIT")
        if d3_engine_exit != "0":
            return _fail(
                f"DIRTY-RESULT.txt D3_ENGINE_EXIT={d3_engine_exit or '<missing>'} (expected 0)"
            )
        # Gate A run 33681670855 fix: D3_ENGINE_EXIT=0 and a healthy/current
        # station-up body are NOT the same claim as "the live database is at
        # the code's migration head" -- that run shipped exactly this gap
        # (a pre-upgrade restore-drill false-negative rolled the engine back,
        # but the flat-layout installer still finished, provisioned, and
        # started a service that happened to answer /health 200 over the
        # unmigrated database's OLD schema, which is a legitimately different
        # state from "the upgrade committed"). Judge the two revisions
        # explicitly instead of inferring them from exit codes alone.
        # <gate-a-audit-BL-10> Judged from the database's own alembic_version
        # row and the candidate's build-time head, not from two fields of one
        # /health body. See _post_upgrade_revision_failure.
        revision_failure = _post_upgrade_revision_failure(text, "DIRTY-RESULT.txt")
        if revision_failure is not None:
            return _fail(revision_failure)

        # <gate-a-audit-MA-24> D3's exit code says nothing about D4. Today's
        # evidence has them diverging in one run:
        # `route=UPGRADE engine_exit=0` then `step d4-activate-station:
        # returned 66` then `postinstall: FAILED`.
        d4_exit = _dirty_line(text, "D4_ACTIVATE_EXIT")
        if d4_exit != "0":
            return _fail(
                f"DIRTY-RESULT.txt D4_ACTIVATE_EXIT={d4_exit or '<missing>'} (expected 0) -- the "
                "D4 station-activation step is a separate outcome from D3's engine exit"
            )
        postinstall = _dirty_line(text, "POSTINSTALL_OUTCOME")
        if postinstall != "SUCCESS":
            return _fail(
                f"DIRTY-RESULT.txt POSTINSTALL_OUTCOME={postinstall or '<missing>'} "
                "(expected SUCCESS)"
            )

        # Post-upgrade app-payload identity, prompted by the 2026-09-05
        # real-tester install-over regression: exit 0 and a healthy station
        # proved setup finished, never that the installed APPLICATION
        # PAYLOAD is the one THIS kit shipped. Fail the run when the staged
        # pack's digest and the kit's own pack digest diverge.
        #
        # HONEST SCOPE NOTE: this lane's baseline (sandbox-lab/
        # upgrade-baseline.json) is always a genuinely OLDER product_version
        # than the candidate under test, so the incoming pack is always
        # copied here and these two digests always match by construction --
        # this check alone does NOT reproduce or catch the regression's
        # actual trigger (two kits declaring the SAME product_version with
        # different content). That exact scenario is covered by
        # native_pack_staging.rs's own Rust unit/e2e tests
        # (decide_offline_staging_action_with_identity and the
        # install_over_a_different_content_kit_* tests), not by this Gate A
        # lane. What this check DOES buy: a real, independent post-upgrade
        # assertion that the kit's OWN payload is what ended up installed --
        # worth keeping regardless -- plus the scaffolding (evidence keys,
        # verdict wiring) a future same-product_version install-over lane
        # can reuse.
        post_upgrade_digest = _dirty_line(text, "POST_UPGRADE_APP_PAYLOAD_DIGEST")
        kit_digest = _dirty_line(text, "KIT_APP_PAYLOAD_DIGEST")
        if (
            not post_upgrade_digest
            or post_upgrade_digest in ("unavailable", "")
            or (post_upgrade_digest.startswith("error:"))
        ):
            return _fail(
                "DIRTY-RESULT.txt POST_UPGRADE_APP_PAYLOAD_DIGEST="
                f"{post_upgrade_digest or '<missing>'} -- could not hash the staged "
                "native-app-payload.ccpack after install-over"
            )
        if not kit_digest or kit_digest in ("unavailable", "") or kit_digest.startswith("error:"):
            return _fail(
                f"DIRTY-RESULT.txt KIT_APP_PAYLOAD_DIGEST={kit_digest or '<missing>'} -- could "
                "not hash this kit's own native-app-payload.ccpack"
            )
        if post_upgrade_digest != kit_digest:
            return _fail(
                "DIRTY-RESULT.txt POST_UPGRADE_APP_PAYLOAD_DIGEST="
                f"{post_upgrade_digest} != KIT_APP_PAYLOAD_DIGEST={kit_digest} -- the installed "
                "application payload is NOT this kit's payload (install-over left a previous "
                "kit's app payload staged; see native_pack_staging.rs's identity-aware staging "
                "decision)"
            )
    pg = _dirty_line(text, "DIRTY_PGDATA_PRESERVED")
    if pg != "1":
        return _fail(f"DIRTY-RESULT.txt DIRTY_PGDATA_PRESERVED={pg or '<missing>'} (expected 1)")
    uploads = _dirty_line(text, "DIRTY_UPLOADS_PRESERVED")
    if uploads != "1":
        return _fail(
            f"DIRTY-RESULT.txt DIRTY_UPLOADS_PRESERVED={uploads or '<missing>'} (expected 1)"
        )
    if _dirty_line(text, "UPGRADE_MODE") == "1":
        return _pass(
            "current installer completed over the live previous candidate via D3 UPGRADE "
            "with engine exit 0; pgdata cluster identity and planted uploads survived"
        )
    return _pass("pgdata cluster identity and planted uploads survived the reinstall")


def check_dirty_orphaned_tier(output_dir: Path) -> CheckResult:
    """When the orphaned large-v3 remnant WAS seeded, PR #80's fallback must
    have provably fired: the supervisor log carries its orphaned-tier
    WARNING (DIRTY_ORPHAN_WARNING=1). When the remnant was not seeded (no
    hash-valid model staged on the runner), this is a loud SKIP -- the shape
    was not covered this run -- never a silent pass."""
    text, err = _read_text(output_dir, "DIRTY-RESULT.txt")
    if err is not None:
        return _fail(err)
    assert text is not None
    if _dirty_line(text, "UPGRADE_MODE") == "1":
        return CheckResult(
            status="SKIP",
            detail=(
                "cross-version upgrade mode does not author the uninstall-only orphaned-tier "
                "shape -- that legacy remnant sub-shape was NOT covered this run"
            ),
        )
    seeded = _dirty_line(text, "DIRTY_ORPHAN_SEEDED")
    if seeded == "0":
        return CheckResult(
            status="SKIP",
            detail=(
                "orphaned large-v3 remnant NOT seeded this run (no hash-valid model staged at "
                "the runner's dirty-seed path) -- the PR #80 orphaned-tier shape was NOT covered; "
                "see docs/ops/gate-a.md, 'Dirty lane' for how to enable it"
            ),
        )
    if seeded != "1":
        return _fail(
            f"DIRTY-RESULT.txt DIRTY_ORPHAN_SEEDED={seeded or '<missing>'} (expected 0 or 1)"
        )
    warning = _dirty_line(text, "DIRTY_ORPHAN_WARNING")
    if warning != "1":
        return _fail(
            f"DIRTY-RESULT.txt DIRTY_ORPHAN_WARNING={warning or '<missing>'} (expected 1): the "
            "orphaned tier was seeded but the supervisor log carries no orphaned-tier fallback "
            "WARNING -- either the remnant was never detected or the fallback did not fire"
        )
    return _pass(
        "orphaned large-v3 remnant seeded and PR #80's fallback WARNING found in the supervisor log"
    )


DIRTY_CHECKS: dict[str, Callable[[Path], CheckResult]] = {
    "dirty_prep": check_dirty_prep,
    "dirty_survival": check_dirty_survival,
    "dirty_orphaned_tier": check_dirty_orphaned_tier,
}


# --------------------------------------------------------------------------
# Download-only lane <gate-a-download-only-lane>. Run in addition to the
# clean-lane checks plus ``dirty_prep``/``dirty_survival`` (the same
# cross-version upgrade shape the dirty lane's UPGRADE_MODE=1 evidence
# proves) when the judge is invoked with --lane download-only
# (Run-GateA.ps1 -DownloadOnlyLane, which implies -DirtyLane -UpgradeMode).
# Never combined with dirty_orphaned_tier -- that remnant sub-shape belongs
# only to the dirty lane's legacy uninstall-only path. See
# docs/ops/gate-a.md, "Download-only lane" for the field bug this lane exists
# to catch: since the K1 fix, the installer's d4-activate-station step
# required a station\ folder beside setup.exe and aborted otherwise, so a
# download-only install/upgrade (setup.exe + packs\, no station\, reusing an
# already-activated station's cached model packs) silently stopped working
# and no existing Gate A lane caught it because every other lane installs
# from the full kit.
# --------------------------------------------------------------------------


def check_download_only_no_station_dir(output_dir: Path) -> CheckResult:
    """FAILS unless the evidence proves ALL of:

    - the phase-2 (current candidate) install ran from a payload directory
      with no ``station\\`` beside ``setup.exe`` (``STATION_DIR_PRESENT=0``);
    - that install's D4 activation step exited 0 (``PHASE2_INSTALL_EXIT=0``
      and ``D3_ENGINE_EXIT=0``); and
    - the resulting ``station-set.json`` names the CURRENT candidate's
      product version, not the pinned previous candidate's -- proving the
      two parallel changes (not a leftover/mismatched receipt) are what let
      activation succeed with no ``station\\`` present: the installer's
      EMBEDDED signed index, which gives ``d4-activate-station`` something to
      import when no ``station\\`` sits beside ``setup.exe``, and the
      station-reuse change, which serves the model packs that index names
      from the per-SHA cache.

    Fails closed on any missing or malformed field -- an absent
    DOWNLOAD-ONLY-RESULT.txt is a FAIL, never an assumed PASS.
    """
    text, err = _read_text(output_dir, "DOWNLOAD-ONLY-RESULT.txt")
    if err is not None:
        return _fail(err)
    assert text is not None

    station_dir_present = _dirty_line(text, "STATION_DIR_PRESENT")
    if station_dir_present != "0":
        return _fail(
            "DOWNLOAD-ONLY-RESULT.txt "
            f"STATION_DIR_PRESENT={station_dir_present or '<missing>'} (expected 0 -- the "
            "phase-2 payload must carry no station\\ directory beside setup.exe)"
        )

    phase2_exit = _dirty_line(text, "PHASE2_INSTALL_EXIT")
    if phase2_exit != "0":
        return _fail(
            f"DOWNLOAD-ONLY-RESULT.txt PHASE2_INSTALL_EXIT={phase2_exit or '<missing>'} (expected 0)"
        )

    # <gate-a-audit-MA-23> D3_ROUTE must be this phase's own, and it must be
    # UPGRADE. install-progress.log is append-only across both install
    # phases; before the harness fix the capture kept the LAST match in the
    # whole file, so a phase-2 installer that died before its d3-engine line
    # left phase 1's `route=FRESH_INSTALL engine_exit=11` in place -- and
    # this check, gating only on D3_ENGINE_EXIT=0, passed on stale data.
    d3_route = _dirty_line(text, "D3_ROUTE")
    if d3_route != "UPGRADE":
        return _fail(
            f"DOWNLOAD-ONLY-RESULT.txt D3_ROUTE={d3_route or '<missing>'} (expected UPGRADE); "
            "FRESH_INSTALL/SAME_VERSION_NO_OP/MISSING do not prove the phase-2 install drove the "
            "cross-version upgrade this lane exists to exercise"
        )

    d3_engine_exit = _dirty_line(text, "D3_ENGINE_EXIT")
    if d3_engine_exit != "0":
        return _fail(
            f"DOWNLOAD-ONLY-RESULT.txt D3_ENGINE_EXIT={d3_engine_exit or '<missing>'} (expected 0)"
        )

    # <gate-a-audit-MA-24> The check that CLAIMED to prove "the D4 activation
    # step exited 0" was reading D3's number. The two diverge:
    # gate-a-download-only-33623737236/install-progress.log:346-353 records
    # `route=UPGRADE engine_exit=0`, then `step d4-activate-station:
    # returned 66`, then `postinstall: FAILED`. Judge D4's own breadcrumb.
    d4_exit = _dirty_line(text, "D4_ACTIVATE_EXIT")
    if d4_exit != "0":
        return _fail(
            f"DOWNLOAD-ONLY-RESULT.txt D4_ACTIVATE_EXIT={d4_exit or '<missing>'} (expected 0 -- "
            "the D4 activation step must have exited 0 with no station\\ directory present)"
        )
    postinstall = _dirty_line(text, "POSTINSTALL_OUTCOME")
    if postinstall != "SUCCESS":
        return _fail(
            f"DOWNLOAD-ONLY-RESULT.txt POSTINSTALL_OUTCOME={postinstall or '<missing>'} "
            "(expected SUCCESS)"
        )

    # <gate-a-audit-BL-10> Independent post-upgrade schema proof; see
    # _post_upgrade_revision_failure for why the previous flag could not fail.
    revision_failure = _post_upgrade_revision_failure(text, "DOWNLOAD-ONLY-RESULT.txt")
    if revision_failure is not None:
        return _fail(revision_failure)

    station_set_version = _dirty_line(text, "STATION_SET_PRODUCT_VERSION")
    current_version = _dirty_line(text, "CURRENT_PRODUCT_VERSION")
    for label, value in (
        ("STATION_SET_PRODUCT_VERSION", station_set_version),
        ("CURRENT_PRODUCT_VERSION", current_version),
    ):
        if not value or value.startswith("<"):
            return _fail(
                f"DOWNLOAD-ONLY-RESULT.txt {label}={value or '<missing>'} "
                "(expected the installer product version)"
            )
    if station_set_version != current_version:
        return _fail(
            f"DOWNLOAD-ONLY-RESULT.txt STATION_SET_PRODUCT_VERSION={station_set_version} does not "
            f"match CURRENT_PRODUCT_VERSION={current_version} -- station-set.json must name the "
            "CURRENT candidate, not a stale or mismatched receipt"
        )

    return _pass(
        "phase-2 payload carried no station\\ directory, install + D4 activation exited 0, and "
        f"station-set.json names the current candidate's product version ({station_set_version})"
    )


DOWNLOAD_ONLY_CHECKS: dict[str, Callable[[Path], CheckResult]] = {
    "dirty_prep": check_dirty_prep,
    "dirty_survival": check_dirty_survival,
    "download_only_no_station_dir": check_download_only_no_station_dir,
}


CHECKS: dict[str, Callable[[Path], CheckResult]] = {
    "install": check_install,
    "activation": check_activation,
    "runtime": check_runtime,
    "t2_render": check_t2_render,
    "t3_loop": check_t3_loop,
    "captions": check_captions,
    "t4_engine": check_t4_engine,
    "t5_soak": check_t5_soak,
    # <gate-a-engine-soak> Runs in EVERY lane; a no-op PASS when
    # SOAK_MINUTES.txt <= 20 (see check_t6_engine_soak's docstring).
    "t6_engine_soak": check_t6_engine_soak,
    # <gate-a-audit-MA-25> Runs in EVERY lane, including clean.
    "install_progress": check_install_progress,
    "completion": check_completion,
}


def _sandbox_busy_verdict(
    output_dir: Path, source_sha: str | None, run_id: str | None
) -> dict[str, Any] | None:
    """Return a BUSY verdict document if SANDBOX-BUSY.txt is present, else None.

    Windows Sandbox is a shared, single-instance-per-machine resource (see
    the module docstring's "Shared-sandbox guard" section). SANDBOX-BUSY.txt
    is written by ``Host-Launch-Sandbox-Test.ps1`` only when it gave up
    waiting for the sandbox to become free WITHOUT ever launching it -- in
    that case none of the required checks' evidence files exist, and running
    them as usual would produce a misleading wall of FAILs. This short-
    circuits to a distinct ``BUSY`` verdict instead, with an empty
    ``checks`` dict, never a PASS or FAIL.
    """
    busy_path = output_dir / "SANDBOX-BUSY.txt"
    if not busy_path.is_file():
        return None
    detail, err = _read_text(output_dir, "SANDBOX-BUSY.txt")
    if err is not None:
        detail = err
    else:
        assert detail is not None
        detail = detail.strip()
    if not detail:
        detail = "SANDBOX-BUSY.txt is present (no detail recorded)"
    return {
        "schema_version": SCHEMA_VERSION,
        "source_sha": source_sha,
        "run_id": run_id,
        "verdict": "BUSY",
        "reason": "sandbox-busy-other-user",
        "detail": detail,
        "checks": {},
        "station_up": None,
        "station_boot_seconds": None,
        "station_first_healthy_utc": None,
        "evidence_dir": str(output_dir),
        "judged_utc": datetime.now(UTC).isoformat(),
    }


def judge(
    output_dir: Path, source_sha: str | None, run_id: str | None, lane: str = "clean"
) -> dict[str, Any]:
    """Run every required check against output_dir and build the verdict document.

    SANDBOX-BUSY.txt short-circuits this before any required check runs --
    see ``_sandbox_busy_verdict``.

    ``lane="dirty"`` <gate-a-dirty-lane> adds the dirty-lane checks
    (``DIRTY_CHECKS``) on top of the unchanged clean-lane set, and stamps a
    ``lane`` field into the verdict document. ``SKIP`` (only ever produced by
    ``check_dirty_orphaned_tier``) does not fail the verdict but is preserved
    in the checks breakdown so an uncovered remnant shape stays visible.
    ``lane="download-only"`` <gate-a-download-only-lane> adds
    ``DOWNLOAD_ONLY_CHECKS`` instead (``dirty_prep``, ``dirty_survival``, and
    ``download_only_no_station_dir`` -- never ``dirty_orphaned_tier``, which
    is specific to the dirty lane's own legacy uninstall-only path).
    The default ``lane="clean"`` produces the exact pre-dirty-lane document
    -- no new fields, no new checks.
    """
    busy_verdict = _sandbox_busy_verdict(output_dir, source_sha, run_id)
    if busy_verdict is not None:
        if lane != "clean":
            busy_verdict["lane"] = lane
        return busy_verdict

    all_checks: dict[str, Callable[[Path], CheckResult]] = dict(CHECKS)
    if lane == "dirty":
        all_checks.update(DIRTY_CHECKS)
    elif lane == "download-only":
        all_checks.update(DOWNLOAD_ONLY_CHECKS)

    checks: dict[str, dict[str, str]] = {}
    for name, fn in all_checks.items():
        try:
            result = fn(output_dir)
        except Exception as exc:  # fail-closed even on a bug in a check itself, never propagate
            result = _fail(f"unhandled exception while evaluating this check: {exc!r}")
        checks[name] = {"status": result.status, "detail": result.detail}

    # A harness error outranks the checks entirely. The checks are still run
    # and still reported -- on a partially-shipped run they are real
    # forensics -- but a broken evidence channel cannot be converted into a
    # statement about the candidate in either direction.
    harness_error = detect_harness_error(output_dir)
    if harness_error is not None:
        verdict = "HARNESS_ERROR"
    elif all(c["status"] in ("PASS", "SKIP") for c in checks.values()):
        verdict = "PASS"
    else:
        verdict = "FAIL"

    # station_up / station_boot_seconds / station_first_healthy_utc are
    # INFORMATIONAL ONLY -- recorded for the human report, never gating.
    # Gate A's judge intentionally does not fail on boot duration (Gate B
    # owns timing); these are surfaced here purely so a run's boot time is
    # visible without having to open summary.json separately. Absent/
    # unparseable summary.json degrades to nulls rather than affecting the
    # verdict at all -- this block never raises.
    station_up: bool | None = None
    station_boot_seconds: float | None = None
    station_first_healthy_utc: str | None = None
    summary, _summary_err = _read_json(output_dir, "summary.json")
    if isinstance(summary, dict):
        station_up = summary.get("station_up")
        station_boot_seconds = summary.get("station_boot_seconds")
        station_first_healthy_utc = summary.get("station_first_healthy_utc")

    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source_sha": source_sha,
        "run_id": run_id,
        "verdict": verdict,
        "harness_error": harness_error,
        "checks": checks,
        "station_up": station_up,
        "station_boot_seconds": station_boot_seconds,
        "station_first_healthy_utc": station_first_healthy_utc,
        "evidence_dir": str(output_dir),
        "judged_utc": datetime.now(UTC).isoformat(),
    }
    if lane != "clean":
        # Additive, dirty-lane-only field: a clean-lane verdict document is
        # byte-shape-identical to the pre-dirty-lane schema.
        document["lane"] = lane
    return document


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
        "--lane",
        choices=("clean", "dirty", "download-only"),
        default="clean",
        help=(
            "Which Gate A lane produced this evidence. 'dirty' adds the remnant-lane checks "
            "(dirty_prep, dirty_survival, dirty_orphaned_tier) on top of the clean set; "
            "'download-only' adds dirty_prep, dirty_survival, and "
            "download_only_no_station_dir (never dirty_orphaned_tier) on top of the clean set; "
            "'clean' (default) is byte-identical to the pre-dirty-lane judge"
        ),
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

    result = judge(output_dir, args.source_sha, args.run_id, lane=args.lane)
    out_path: Path = args.out if args.out is not None else output_dir / "gate-a-verdict.json"
    out_path.write_text(json.dumps(result, indent=2, sort_keys=False) + "\n", encoding="utf-8")

    print(json.dumps(result, indent=2, sort_keys=False))
    print(f"\ngate_a_verdict: {result['verdict']} (written to {out_path})", file=sys.stderr)

    if result["verdict"] == "PASS":
        return 0
    if result["verdict"] == "BUSY":
        # Harness-busy, not a station-acceptance finding -- same exit-code
        # family as the missing-output-dir usage error above, never 1 (FAIL).
        return 2
    if result["verdict"] == "HARNESS_ERROR":
        # Same family again: the gate could not observe the candidate. BUSY
        # means it never started; this means it started and lost its
        # evidence channel partway through.
        print(f"gate_a_verdict: harness error -- {result['harness_error']}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
