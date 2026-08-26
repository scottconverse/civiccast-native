# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Gate B verdict judge -- the machine verdict for the 24h reboot soak.

Reads the evidence a ``gate-b/Run-GateB.ps1`` run leaves in an output
directory (a clean install inside a persistent Hyper-V VM, three PEG channels
broadcasting continuously, 5-minute health/beat sampling for 24 hours, a
planned REBOOT at the halfway mark, and TSDuck egress verification on both
sides of that reboot) and emits a single ``gate-b-verdict.json`` with an
unambiguous PASS/FAIL verdict and a per-check breakdown.

Why this exists, and why it is a SEPARATE gate from Gate A: Gate A runs in
Windows Sandbox, which **cannot reboot** -- the VM is disposable and dies when
the harness closes it. The 3.0 MASTER spec's release-readiness gate is
explicit that a reboot is required, not optional:

    "24h unattended soak w/ kill+restart+**reboot**; 72h candidate soak before
    broad handoff"
    -- docs/spec/3.0/civiccast-3.0-station-in-a-box-MASTER.md §12, "Global
       gates", release-readiness

    "the box calls for help when it goes off-air unattended; **survives an
    unattended reboot**"
    -- same file, §12, "Station acceptance"

    "Rung 2 | Machine-proven | Clean Windows install + unattended soak
    (24/72h) incl. reboot, midnight crossover, unclean-restart reap"
    -- same file, §5, "Unified proof / certification ladder"

Gate A's own docs (``docs/ops/gate-a.md``) name this exact scope as out of
bounds for it and assign it here. This module is the judge for that job -- it
reads files, it does not run anything, and it is FAIL-CLOSED: any missing
file, unparseable JSON, or absent/wrong field is a named FAIL, never an
assumed PASS. Same shapes and idioms as ``scripts/gate_a_verdict.py``.

Required checks, each citing the spec line it enforces:

  plan            -- the run that was actually executed meets the §12 floor:
                     a >= 24h soak, with the reboot inside it, sampled at
                     <= 5-minute beats. A shorter rehearsal run is a FAIL
                     here BY DESIGN -- see "The plan check is not a
                     formality" below.
  install         -- installs without terminal work (silent installer, exit
                     0, station-set.json present afterwards). §12 "clean
                     Windows install from artifact" / "operator
                     installs+commissions without terminal work".
  activation      -- the K1 mandatory activation hook ran and staged the
                     station. Same evidence shape Gate A uses.
  channels        -- all THREE PEG channels (public/education/government)
                     were on air in every beat. §12 station acceptance:
                     "runs the three PEG channels (public/education/
                     government) concurrently".
  uptime_beats    -- the beat log covers the whole declared soak at the
                     declared cadence, and the ONLY gap that exceeds the
                     per-beat slack is the single planned reboot gap, which
                     must fit the declared reboot budget. §12 "24h unattended
                     soak"; S9 §8.3 item 4 ("Sample /health every 5 minutes").
  reboot_recovery -- exactly one reboot happened, at the planned mark, and
                     the station came back to BROADCASTING (health ok AND all
                     three channels on air) within the declared recovery
                     budget, with no operator interaction. §12 "survives an
                     unattended reboot"; S9 §8.3 item 2 (the hour-12 restart).
  no_unplanned_restarts
                  -- within each boot epoch the supervisor service and every
                     supervised child kept the same pid for the whole soak,
                     and the supervisor log carries no restart warning. §5
                     rung 2 "unclean-restart reap"; S9 §8.3 item 5 ("pipeline
                     restarts churn faster than the latch" is a blocker).
  egress_continuity
                  -- TSDuck verified the live transport streams on all three
                     channels BEFORE the reboot and again AFTER it, both
                     clean (zero invalid syncs / transport errors /
                     discontinuities). §12 "TSDuck verify on UDP-TS
                     profiles"; S9 §8.3 item 1 (TS continuity across a
                     supervised restart).
  completion      -- the harness itself reached its own authoritative
                     completion signal (DONE.json.harness_completed, no
                     watchdog/stall marker). Same contract as Gate A.

NOT covered here -- these remain out of scope by design, not oversight:
physical SDI proof (rung 3; no DeckLink pass-through into the VM), the 72h
candidate soak (§12 names it separately -- Gate B is the 24h rung), the
commissioning-wizard UI walkthrough, OTT-app presence, and the support-bundle
export. See ``docs/ops/gate-b.md`` for the full boundary statement.

The plan check is not a formality. ``gate-b-run.json`` records the plan the
harness actually executed (soak minutes, beat interval, reboot mark, budgets),
and ``check_plan`` refuses anything below the §12 floor. The harness
deliberately supports short rehearsal runs (``-SoakMinutes 30``) so the
mechanics can be exercised without burning a day -- and a rehearsal run is
reported as a FAIL, naming the plan as the reason. That is the point: a
30-minute run is not a 24-hour soak, and the only safe way to prevent it from
ever being read as one is for the judge to say so out loud. There is no
``--allow-short-soak`` escape hatch, because an escape hatch is how "we ran
Gate B" ends up meaning "we ran something".

Two verdicts, and two non-verdicts -- exactly Gate A's contract:

  PASS / FAIL          a real reboot-soak finding; all checks computed and
                       they decide the verdict
  HYPERV_UNAVAILABLE   the run never started: Hyper-V is not enabled on the
                       host, so no VM could be created (marker:
                       HYPERV-UNAVAILABLE.txt). Empty ``checks`` -- no
                       evidence was ever produced. The peer of Gate A's
                       ``BUSY``.
  HARNESS_ERROR        the run started and then lost its evidence channel or
                       its VM (see ``HARNESS_ERROR_MARKERS``). Checks are
                       still computed and recorded as forensics, but they do
                       not decide the verdict.

Neither non-verdict is reported as a FAIL. Calling a broken harness a product
failure is the same authored-truth mistake these gates exist to eliminate,
pointed the other way.

Usage:
    python scripts/gate_b_verdict.py <output_dir> \
        [--source-sha SHA] [--run-id ID] [--out PATH]

Exit code: 0 if the verdict is PASS, 1 if FAIL, 2 for anything that is not a
reboot-soak finding at all -- the output directory not existing, a
``HYPERV_UNAVAILABLE`` verdict, or a ``HARNESS_ERROR`` verdict.
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

#: The three PEG channels §12 requires a station to run concurrently
#: ("runs the three PEG channels (public/education/government) concurrently").
#: Order is the spec's own; the checks compare as a set, so beat order is free.
REQUIRED_CHANNELS: tuple[str, ...] = ("public", "education", "government")

#: The §12 release-readiness floor this gate exists to enforce: a 24-hour
#: unattended soak. ``check_plan`` refuses to grade a shorter run as anything
#: but a FAIL. 1440 minutes = 24h.
SPEC_MIN_SOAK_MINUTES = 1440

#: S9 §8.3 item 4: "Sample /health every 5 minutes". A slower cadence would
#: leave gaps this judge cannot distinguish from an outage, so it is a floor
#: on the plan, not a preference.
SPEC_MAX_BEAT_INTERVAL_MINUTES = 5

#: The beat-record schema the in-VM agent writes, one JSON object per line.
BEAT_SCHEMA = "civiccast-gate-b-beat-v1"

#: The egress-verify document schema, produced by
#: ``sandbox-lab/soak-4h/scripts/verify-egress.ps1`` (reused verbatim -- it is
#: engine-agnostic: it listens on the UDP ports, it does not care what filled
#: them).
EGRESS_SCHEMA = "civiccast-soak-egress-verify-v1"

#: Verbatim WARNING emitted by the native supervisor when a child restart does
#: not reach ready -- ``civiccast/native/supervisor/core.py``'s
#: ``_log_restart_not_ready`` (``"restart of child %s not ready: detail=%s"``).
#: KNOWN BLIND SPOT, stated rather than hidden: that logger call is LATCHED per
#: child (the same failure detail is logged once, not once per attempt), so
#: this pattern proves "a restart was attempted and failed", never "how many".
#: It is the corroborating instrument here, not the primary one -- the primary
#: restart signal is the harness's own per-beat child-pid observation, which is
#: direct and unlatched. Two instruments of different kinds, deliberately.
SUPERVISOR_RESTART_WARNING = re.compile(r"restart of child (\S+) not ready", re.MULTILINE)

#: Markers that mean "the harness broke", not "the product failed". Each maps
#: a filename dropped into the evidence directory to the explanation that goes
#: into the verdict document. A run carrying any of these is reported as
#: ``HARNESS_ERROR`` (exit 2) and never as ``FAIL``.
HARNESS_ERROR_MARKERS: dict[str, str] = {
    "GATE-B-HOST-ERROR.txt": (
        "GATE-B-HOST-ERROR.txt is present -- Run-GateB.ps1 recorded a host-side failure "
        "(the VM died, PowerShell Direct stopped answering, or an evidence pull failed "
        "past its retry budget) rather than a finding about the candidate. No reboot-soak "
        "conclusion can be drawn from this run"
    ),
    "VM-LOST.txt": (
        "VM-LOST.txt is present -- the Gate B VM stopped existing or stopped running "
        "outside the one planned reboot, so the soak was cut short by the harness's own "
        "environment. That is a statement about the host, not about the candidate"
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


def _read_beats(output_dir: Path) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Parse ``beats.jsonl`` -- one beat object per line, in write order.

    Fail-closed on every malformed shape: a blank-line-only file, a line that
    is not JSON, a line that is not an object, or a line carrying the wrong
    ``schema`` are each a named error rather than a silently-skipped record.
    Silently skipping a bad beat would let a soak with corrupt sampling read
    as a clean one with fewer samples.
    """
    text, err = _read_text(output_dir, "beats.jsonl")
    if err is not None:
        return None, err
    assert text is not None
    beats: list[dict[str, Any]] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            return None, f"beats.jsonl line {lineno} is not valid JSON: {exc}"
        if not isinstance(record, dict):
            return None, f"beats.jsonl line {lineno} is not a JSON object"
        schema = record.get("schema")
        if schema != BEAT_SCHEMA:
            return (
                None,
                f"beats.jsonl line {lineno} has schema={schema!r} (expected {BEAT_SCHEMA!r})",
            )
        beats.append(record)
    if not beats:
        return None, "beats.jsonl contains no beat records"
    return beats, None


def _read_plan(output_dir: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Read the executed plan out of ``gate-b-run.json``.

    This is the document the harness writes describing the run it ACTUALLY
    executed -- not a copy of the defaults, and not something the judge
    supplies. Every downstream check grades against it, so a missing or
    malformed plan fails every check that needs it rather than falling back to
    an assumed 24h shape.
    """
    doc, err = _read_json(output_dir, "gate-b-run.json")
    if err is not None:
        return None, err
    if not isinstance(doc, dict):
        return None, "gate-b-run.json is not a JSON object"
    plan = doc.get("plan")
    if not isinstance(plan, dict):
        return None, "gate-b-run.json.plan missing or not an object"
    return plan, None


def _plan_number(plan: dict[str, Any], key: str) -> tuple[float | None, str | None]:
    value = plan.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, f"gate-b-run.json.plan.{key}={value!r} (expected a number)"
    return float(value), None


def _beat_float(beat: dict[str, Any], key: str) -> float | None:
    value = beat.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _beat_health_ok(beat: dict[str, Any]) -> bool:
    """True iff this beat observed the station answering /api/health with 200.

    HTTP status is the liveness signal the station's own health route
    documents ("HTTP status is liveness. Always 200 while the process answers"
    -- civiccast/app.py). Readiness (``status``: healthy/degraded) is reported
    separately in the beat and is surfaced in the detail strings, but a
    ``degraded`` readiness caused by a schema state is not what this gate is
    measuring; being off the air is.
    """
    health = beat.get("health")
    if not isinstance(health, dict):
        return False
    return health.get("http_status") == 200 and health.get("ok") is True


def _beat_on_air_channels(beat: dict[str, Any]) -> set[str] | None:
    """The set of channel ids this beat observed ON AIR, or None if malformed."""
    channels = beat.get("channels")
    if not isinstance(channels, list):
        return None
    on_air: set[str] = set()
    for entry in channels:
        if not isinstance(entry, dict):
            return None
        channel_id = entry.get("channel_id")
        if not isinstance(channel_id, str):
            return None
        if entry.get("on_air") is True:
            on_air.add(channel_id)
    return on_air


# --------------------------------------------------------------------------
# Individual checks. Every function takes the output directory and returns a
# CheckResult. None of them raise on missing/malformed input -- every failure
# mode is a named FAIL detail string, per the module's fail-closed contract.
# --------------------------------------------------------------------------


def check_plan(output_dir: Path) -> CheckResult:
    """The executed run meets the 3.0 MASTER spec §12 floor.

    A rehearsal run (short soak) is a FAIL here on purpose -- see the module
    docstring's "The plan check is not a formality".
    """
    plan, err = _read_plan(output_dir)
    if err is not None:
        return _fail(err)
    assert plan is not None
    soak, serr = _plan_number(plan, "soak_minutes")
    if serr is not None:
        return _fail(serr)
    assert soak is not None
    interval, ierr = _plan_number(plan, "beat_interval_minutes")
    if ierr is not None:
        return _fail(ierr)
    assert interval is not None
    reboot_at, rerr = _plan_number(plan, "reboot_at_minutes")
    if rerr is not None:
        return _fail(rerr)
    assert reboot_at is not None
    for budget_key in (
        "reboot_gap_budget_minutes",
        "recovery_budget_minutes",
        "beat_slack_minutes",
    ):
        _value, berr = _plan_number(plan, budget_key)
        if berr is not None:
            return _fail(berr)
    if soak < SPEC_MIN_SOAK_MINUTES:
        return _fail(
            f"plan.soak_minutes={soak:g} is below the 3.0 MASTER spec §12 floor of "
            f"{SPEC_MIN_SOAK_MINUTES} (24h unattended soak). This run was a rehearsal, not Gate B"
        )
    if interval > SPEC_MAX_BEAT_INTERVAL_MINUTES:
        return _fail(
            f"plan.beat_interval_minutes={interval:g} exceeds the {SPEC_MAX_BEAT_INTERVAL_MINUTES}-minute "
            "sampling cadence S9 §8.3 requires ('Sample /health every 5 minutes')"
        )
    if not 0 < reboot_at < soak:
        return _fail(
            f"plan.reboot_at_minutes={reboot_at:g} is not inside the soak window "
            f"(0, {soak:g}) -- §12 requires the reboot to happen DURING the 24h soak"
        )
    return _pass(
        f"soak_minutes={soak:g} (>= {SPEC_MIN_SOAK_MINUTES}), beat_interval_minutes={interval:g}, "
        f"reboot_at_minutes={reboot_at:g}"
    )


def check_install(output_dir: Path) -> CheckResult:
    """Silent install ran to exit 0 and staged the station.

    Deliberately the same field names Gate A's ``check_install`` reads
    (``installer_exit_code`` / ``station_set_json_found``): the in-VM install
    is performed by the SAME shared module
    (``sandbox-lab/common/CivicCastStationHarness.psm1``), so the two gates
    grade one evidence shape, not two that drift apart.
    """
    summary, err = _read_json(output_dir, "summary.json")
    if err is not None:
        return _fail(err)
    if not isinstance(summary, dict):
        return _fail("summary.json is not a JSON object")
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
    """The K1 mandatory activation hook ran and staged the station."""
    summary, err = _read_json(output_dir, "summary.json")
    if err is not None:
        return _fail(err)
    if not isinstance(summary, dict):
        return _fail("summary.json is not a JSON object")
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


def check_channels(output_dir: Path) -> CheckResult:
    """All three PEG channels were on air in EVERY beat.

    §12 station acceptance: "runs the three PEG channels (public/education/
    government) concurrently". Every beat, not most -- a channel that drops
    for one 5-minute window is a channel that went dark, which is precisely
    the condition §12's "the box calls for help when it goes off-air
    unattended" language is about.
    """
    beats, err = _read_beats(output_dir)
    if err is not None:
        return _fail(err)
    assert beats is not None
    required = set(REQUIRED_CHANNELS)
    for beat in beats:
        seq = beat.get("beat_seq")
        on_air = _beat_on_air_channels(beat)
        if on_air is None:
            return _fail(f"beat_seq={seq!r} has a missing/malformed channels array")
        missing = required - on_air
        if missing:
            return _fail(
                f"beat_seq={seq!r} (utc={beat.get('utc')!r}) had {sorted(missing)} not on air; "
                f"observed on air: {sorted(on_air)}"
            )
    return _pass(
        f"all {len(required)} PEG channels ({', '.join(REQUIRED_CHANNELS)}) on air in every one of "
        f"{len(beats)} beats"
    )


def check_uptime_beats(output_dir: Path) -> CheckResult:
    """The beat log covers the whole declared soak, with one allowed gap.

    Two separate things are asserted here and it is worth keeping them apart:

    * **Coverage.** The beats must span the declared soak -- a run that
      stopped sampling at hour 6 has not proven 24 hours no matter how clean
      the first 6 look.
    * **Continuity.** Consecutive beats must be no further apart than
      ``beat_interval + beat_slack``, with EXACTLY ONE exception: the planned
      reboot, whose gap must fit ``reboot_gap_budget_minutes``. A second
      oversized gap is an unexplained outage in the sampler, the station, or
      the machine, and none of those are things a 24h soak may contain.

    A beat that observed the station unhealthy is a FAIL too -- the beat
    existing is not the same as the station being up.
    """
    plan, perr = _read_plan(output_dir)
    if perr is not None:
        return _fail(perr)
    assert plan is not None
    beats, berr = _read_beats(output_dir)
    if berr is not None:
        return _fail(berr)
    assert beats is not None

    soak, e1 = _plan_number(plan, "soak_minutes")
    interval, e2 = _plan_number(plan, "beat_interval_minutes")
    slack, e3 = _plan_number(plan, "beat_slack_minutes")
    reboot_budget, e4 = _plan_number(plan, "reboot_gap_budget_minutes")
    for err in (e1, e2, e3, e4):
        if err is not None:
            return _fail(err)
    assert soak is not None and interval is not None
    assert slack is not None and reboot_budget is not None

    elapsed: list[float] = []
    for beat in beats:
        value = _beat_float(beat, "elapsed_minutes")
        if value is None:
            return _fail(
                f"beat_seq={beat.get('beat_seq')!r} has a missing/non-numeric elapsed_minutes"
            )
        elapsed.append(value)
    if elapsed != sorted(elapsed):
        return _fail(
            "beats.jsonl elapsed_minutes is not monotonically non-decreasing (out-of-order beats)"
        )

    unhealthy = [beat.get("beat_seq") for beat in beats if not _beat_health_ok(beat)]
    if unhealthy:
        return _fail(
            f"{len(unhealthy)} of {len(beats)} beats observed the station not answering "
            f"/api/health with 200; first at beat_seq={unhealthy[0]!r}"
        )

    if elapsed[0] > interval + slack:
        return _fail(
            f"first beat is at elapsed_minutes={elapsed[0]:g}, more than one interval+slack "
            f"({interval + slack:g}) into the soak -- sampling did not start with the soak"
        )
    if elapsed[-1] < soak - interval:
        return _fail(
            f"last beat is at elapsed_minutes={elapsed[-1]:g}, short of the declared "
            f"soak_minutes={soak:g} -- the beat log does not cover the whole soak"
        )

    normal_gap = interval + slack
    oversized: list[tuple[int, float]] = []
    for index in range(1, len(elapsed)):
        gap = elapsed[index] - elapsed[index - 1]
        if gap > normal_gap:
            oversized.append((index, gap))
    if len(oversized) > 1:
        rendered = ", ".join(
            f"beat_seq={beats[i].get('beat_seq')!r} gap={g:.1f}m" for i, g in oversized
        )
        return _fail(
            f"{len(oversized)} gaps exceed the normal per-beat bound of {normal_gap:g}m; only the one "
            f"planned reboot gap is allowed. Gaps: {rendered}"
        )
    if oversized:
        index, gap = oversized[0]
        boot_before = beats[index - 1].get("system_boot_utc")
        boot_after = beats[index].get("system_boot_utc")
        if boot_before == boot_after:
            return _fail(
                f"the one oversized gap ({gap:.1f}m, at beat_seq={beats[index].get('beat_seq')!r}) did NOT "
                "straddle a reboot (system_boot_utc unchanged across it) -- it is an unexplained outage, "
                "not the planned reboot"
            )
        if gap > reboot_budget:
            return _fail(
                f"the planned reboot gap is {gap:.1f}m, over the declared "
                f"reboot_gap_budget_minutes={reboot_budget:g}"
            )
        return _pass(
            f"{len(beats)} beats spanning {elapsed[-1]:g}m (declared soak {soak:g}m), all healthy; one "
            f"gap of {gap:.1f}m across the planned reboot, inside the {reboot_budget:g}m budget"
        )
    return _pass(
        f"{len(beats)} beats spanning {elapsed[-1]:g}m (declared soak {soak:g}m), all healthy, no gap "
        f"over {normal_gap:g}m"
    )


def check_reboot_recovery(output_dir: Path) -> CheckResult:
    """Exactly one reboot, at the planned mark, recovered to BROADCASTING unattended.

    "Recovered" here deliberately means more than "the box came back". §12's
    station-acceptance line is "survives an unattended reboot" in a list whose
    subject is a station running three PEG channels -- a machine that boots to
    a login prompt with a dead egress engine has not survived anything useful.
    So the recovery beat must show health 200 AND all three channels on air.

    Unattendedness is asserted from two places: every post-reboot beat must
    carry ``unattended: true`` (the in-VM agent sets it only when it was
    started by its own at-startup task rather than by an interactive logon),
    and REBOOT-RESULT.txt must record ``operator_interaction=none``.
    """
    plan, perr = _read_plan(output_dir)
    if perr is not None:
        return _fail(perr)
    assert plan is not None
    beats, berr = _read_beats(output_dir)
    if berr is not None:
        return _fail(berr)
    assert beats is not None

    reboot_at, e1 = _plan_number(plan, "reboot_at_minutes")
    recovery_budget, e2 = _plan_number(plan, "recovery_budget_minutes")
    gap_budget, e3 = _plan_number(plan, "reboot_gap_budget_minutes")
    interval, e4 = _plan_number(plan, "beat_interval_minutes")
    slack, e5 = _plan_number(plan, "beat_slack_minutes")
    for err in (e1, e2, e3, e4, e5):
        if err is not None:
            return _fail(err)
    assert reboot_at is not None and recovery_budget is not None
    assert gap_budget is not None and interval is not None and slack is not None

    boots: list[str] = []
    for beat in beats:
        boot = beat.get("system_boot_utc")
        if not isinstance(boot, str) or not boot:
            return _fail(
                f"beat_seq={beat.get('beat_seq')!r} has a missing/non-string system_boot_utc -- "
                "the reboot cannot be located without it"
            )
        boots.append(boot)

    transitions = [i for i in range(1, len(boots)) if boots[i] != boots[i - 1]]
    if not transitions:
        return _fail(
            "no reboot observed: system_boot_utc never changed across the whole beat log. §12 requires "
            "the 24h soak to include a reboot"
        )
    if len(transitions) > 1:
        marks = ", ".join(f"beat_seq={beats[i].get('beat_seq')!r}" for i in transitions)
        return _fail(
            f"{len(transitions)} reboots observed ({marks}); exactly one PLANNED reboot is allowed -- "
            "an extra boot is an unplanned restart of the whole machine"
        )

    index = transitions[0]
    last_before = beats[index - 1]
    first_after = beats[index]
    before_elapsed = _beat_float(last_before, "elapsed_minutes")
    after_elapsed = _beat_float(first_after, "elapsed_minutes")
    if before_elapsed is None or after_elapsed is None:
        return _fail(
            "the beats either side of the reboot have a missing/non-numeric elapsed_minutes"
        )

    if before_elapsed > reboot_at + interval + slack:
        return _fail(
            f"the last pre-reboot beat is at elapsed_minutes={before_elapsed:g}, past the planned "
            f"reboot_at_minutes={reboot_at:g} (+ one interval+slack) -- the reboot did not happen when planned"
        )
    if after_elapsed > reboot_at + gap_budget:
        return _fail(
            f"the first post-reboot beat is at elapsed_minutes={after_elapsed:g}, past "
            f"reboot_at_minutes + reboot_gap_budget_minutes ({reboot_at + gap_budget:g})"
        )

    for beat in beats[index:]:
        if beat.get("unattended") is not True:
            return _fail(
                f"post-reboot beat_seq={beat.get('beat_seq')!r} has unattended={beat.get('unattended')!r} "
                "(expected true) -- the agent did not resume from its own at-startup task, so this reboot "
                "was not survived UNATTENDED"
            )

    recovery: dict[str, Any] | None = None
    for beat in beats[index:]:
        on_air = _beat_on_air_channels(beat)
        if _beat_health_ok(beat) and on_air is not None and set(REQUIRED_CHANNELS) <= on_air:
            recovery = beat
            break
    if recovery is None:
        return _fail(
            "no post-reboot beat observed the station healthy with all three PEG channels on air -- "
            "the station did not come back to BROADCASTING"
        )
    recovery_elapsed = _beat_float(recovery, "elapsed_minutes")
    if recovery_elapsed is None:
        return _fail("the recovery beat has a missing/non-numeric elapsed_minutes")
    recovery_minutes = recovery_elapsed - before_elapsed
    if recovery_minutes > recovery_budget:
        return _fail(
            f"the station took {recovery_minutes:.1f}m after the last pre-reboot beat to be healthy with "
            f"all three channels on air, over the declared recovery_budget_minutes={recovery_budget:g}"
        )

    text, terr = _read_text(output_dir, "REBOOT-RESULT.txt")
    if terr is not None:
        return _fail(terr)
    assert text is not None
    if not _line_matching(text, r"^operator_interaction=none\s*$"):
        return _fail(
            "REBOOT-RESULT.txt does not carry 'operator_interaction=none' -- the harness did not record "
            "this reboot as unattended"
        )
    if not _line_matching(text, r"^reboot_issued_utc=\S+"):
        return _fail("REBOOT-RESULT.txt has no reboot_issued_utc line")

    return _pass(
        f"exactly one reboot at elapsed_minutes~{reboot_at:g} (last pre-reboot beat {before_elapsed:g}m, "
        f"first post-reboot beat {after_elapsed:g}m); back to health+3 channels on air in "
        f"{recovery_minutes:.1f}m (budget {recovery_budget:g}m), unattended"
    )


def check_no_unplanned_restarts(output_dir: Path) -> CheckResult:
    """No supervised process restarted outside the one planned reboot.

    TWO instruments of different kinds, because one is not enough here:

    1. **The harness's own per-beat process observation (primary).** Each beat
       records the supervisor service's pid and every supervised child's pid.
       Within one boot epoch those pids must not change. This is direct and
       unlatched: it counts restarts rather than inferring them.
    2. **The supervisor's own log (corroborating).** ``supervisor.log`` must be
       present and non-empty, and must not carry the
       ``restart of child <name> not ready`` WARNING. Stated blind spot: that
       logger call is latched per child, so its silence is weaker evidence
       than instrument 1's pid stability -- which is exactly why it is second
       and not alone.

    §5 rung 2 names "unclean-restart reap"; S9 §8.3 item 5 makes restart churn
    a blocker.
    """
    beats, berr = _read_beats(output_dir)
    if berr is not None:
        return _fail(berr)
    assert beats is not None

    seen_service: dict[str, Any] = {}
    seen_children: dict[str, dict[str, Any]] = {}
    for beat in beats:
        boot = beat.get("system_boot_utc")
        if not isinstance(boot, str):
            return _fail(
                f"beat_seq={beat.get('beat_seq')!r} has a missing/non-string system_boot_utc"
            )
        supervisor = beat.get("supervisor")
        if not isinstance(supervisor, dict):
            return _fail(
                f"beat_seq={beat.get('beat_seq')!r} has a missing/malformed supervisor object"
            )
        service_pid = supervisor.get("service_pid")
        if not isinstance(service_pid, int) or isinstance(service_pid, bool):
            return _fail(
                f"beat_seq={beat.get('beat_seq')!r} supervisor.service_pid={service_pid!r} "
                "(expected an int)"
            )
        if boot in seen_service and seen_service[boot] != service_pid:
            return _fail(
                f"the supervisor service pid changed within one boot epoch (boot {boot}): "
                f"{seen_service[boot]!r} -> {service_pid!r} at beat_seq={beat.get('beat_seq')!r} -- "
                "that is an unplanned service restart"
            )
        seen_service[boot] = service_pid

        children = supervisor.get("children")
        if not isinstance(children, dict) or not children:
            return _fail(
                f"beat_seq={beat.get('beat_seq')!r} supervisor.children missing, not an object, or empty"
            )
        epoch_children = seen_children.setdefault(boot, {})
        # Snapshot BEFORE the loop below adds this beat's children to it.
        # Comparing against the post-loop set would silently accept a child
        # that appeared mid-epoch, because the loop would have just added it
        # to the very set it is being compared with.
        known_before = set(epoch_children)
        for name, info in children.items():
            if not isinstance(info, dict):
                return _fail(
                    f"beat_seq={beat.get('beat_seq')!r} supervisor.children.{name} is not an object"
                )
            child_pid = info.get("pid")
            if not isinstance(child_pid, int) or isinstance(child_pid, bool):
                return _fail(
                    f"beat_seq={beat.get('beat_seq')!r} supervisor.children.{name}.pid={child_pid!r} "
                    "(expected an int)"
                )
            if name in epoch_children and epoch_children[name] != child_pid:
                return _fail(
                    f"supervised child {name!r} changed pid within one boot epoch (boot {boot}): "
                    f"{epoch_children[name]!r} -> {child_pid!r} at beat_seq={beat.get('beat_seq')!r} -- "
                    "that is an unplanned child restart"
                )
            epoch_children[name] = child_pid
        # A pid that CHANGES is a restart; a child that VANISHES is a death
        # with no restart, and a child that APPEARS mid-epoch is a start the
        # bring-up did not perform. Comparing pids alone would see neither,
        # because a key that stops being reported simply stops being compared.
        # So the child SET is asserted too, once the first beat of an epoch has
        # established what it should be.
        observed = set(children)
        if known_before and known_before != observed:
            vanished = sorted(known_before - observed)
            appeared = sorted(observed - known_before)
            return _fail(
                f"the set of supervised children changed within one boot epoch (boot {boot}) at "
                f"beat_seq={beat.get('beat_seq')!r}: vanished={vanished} appeared={appeared}"
            )

    log_text, lerr = _read_text(output_dir, "supervisor-logs/supervisor.log")
    if lerr is not None:
        return _fail(
            f"{lerr} -- the supervisor's own log is the second, independent instrument for this check "
            "and its absence is a FAIL, not a pass by silence"
        )
    assert log_text is not None
    if not log_text.strip():
        return _fail(
            "supervisor-logs/supervisor.log is empty -- no corroborating evidence that the supervisor "
            "logged anything at all across a 24h soak"
        )
    warning = SUPERVISOR_RESTART_WARNING.search(log_text)
    if warning is not None:
        return _fail(
            f"supervisor.log carries the supervisor's own restart warning for child "
            f"{warning.group(1)!r} ('restart of child ... not ready')"
        )

    child_names = sorted({name for epoch in seen_children.values() for name in epoch})
    return _pass(
        f"supervisor service pid and {len(child_names)} child pids ({', '.join(child_names)}) stable "
        f"across each of {len(seen_service)} boot epoch(s) over {len(beats)} beats; supervisor.log "
        f"({len(log_text)} bytes) carries no restart warning"
    )


def _egress_verdict(output_dir: Path, name: str, label: str) -> CheckResult:
    doc, err = _read_json(output_dir, name)
    if err is not None:
        return _fail(err)
    if not isinstance(doc, dict):
        return _fail(f"{name} is not a JSON object")
    schema = doc.get("schema")
    if schema != EGRESS_SCHEMA:
        return _fail(f"{name} schema={schema!r} (expected {EGRESS_SCHEMA!r})")
    overall = doc.get("overall_verdict")
    if overall != "pass":
        return _fail(f"{name} overall_verdict={overall!r} (expected 'pass') -- {label}")
    channels = doc.get("channels")
    if not isinstance(channels, list):
        return _fail(f"{name}.channels missing or not a list")
    seen: dict[str, Any] = {}
    for entry in channels:
        if not isinstance(entry, dict):
            return _fail(f"{name}.channels contains a non-object entry")
        channel_id = entry.get("channel")
        if not isinstance(channel_id, str):
            return _fail(f"{name}.channels contains an entry with no 'channel' string")
        verdict = entry.get("verdict")
        if verdict != "pass":
            return _fail(
                f"{name} channel {channel_id!r} verdict={verdict!r} (expected 'pass') -- {label}"
            )
        seen[channel_id] = entry.get("checks")
    missing = set(REQUIRED_CHANNELS) - set(seen)
    if missing:
        return _fail(f"{name} has no TSDuck verdict for {sorted(missing)} -- {label}")
    return _pass(f"{label}: all {len(REQUIRED_CHANNELS)} channels tsduck-verified clean")


def check_egress_continuity(output_dir: Path) -> CheckResult:
    """TSDuck verified all three transport streams before AND after the reboot.

    §12 release-readiness names "TSDuck verify on UDP-TS profiles"; S9 §8.3
    item 1 makes unbroken TS continuity across a supervised restart the
    blocking criterion. Two samples, one either side of the reboot, is the
    smallest evidence set that can distinguish "the streams were clean" from
    "the streams were clean until we rebooted".

    Both documents are produced by
    ``sandbox-lab/soak-4h/scripts/verify-egress.ps1``, reused unmodified: it
    listens on 127.0.0.1:9001/9002/9003 and analyzes what arrives, so it is
    engine-agnostic by construction -- which is what makes it valid evidence
    for the product GStreamer engine even though it was written for the
    ffmpeg-driven 4h soak.
    """
    pre = _egress_verdict(output_dir, "egress-verify-pre-reboot.json", "before the reboot")
    if pre.status != "PASS":
        return pre
    post = _egress_verdict(output_dir, "egress-verify-post-reboot.json", "after the reboot")
    if post.status != "PASS":
        return post
    return _pass(f"{pre.detail}; {post.detail}")


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

    Same contract as Gate A's ``check_completion``: gated on
    ``DONE.json.harness_completed is True`` and the ABSENCE of
    ``WATCHDOG-TIMEOUT.txt`` / ``STALL-TIMEOUT.txt``, not on a specific step
    name. A run the watchdog force-completed is a FAIL here even if a
    DONE.json exists -- the watchdog's placeholder is a bounded escape hatch
    for the host's poll loop, not a real completion.
    """
    harness_error = detect_harness_error(output_dir)
    if harness_error is not None:
        return _fail(harness_error)
    if (output_dir / "WATCHDOG-TIMEOUT.txt").is_file():
        return _fail(
            "WATCHDOG-TIMEOUT.txt is present -- the harness hit its bounded watchdog before "
            "completing; this is not a genuine run completion"
        )
    if (output_dir / "STALL-TIMEOUT.txt").is_file():
        return _fail(
            "STALL-TIMEOUT.txt is present -- the watchdog detected the run had stopped advancing "
            "before it completed; this is not a genuine run completion"
        )
    done, err = _read_json(output_dir, "DONE.json")
    if err is not None:
        return _fail(err)
    if not isinstance(done, dict):
        return _fail("DONE.json is not a JSON object")
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
    return _pass(f"DONE.json present, harness_completed=true, done_utc={done.get('done_utc')!r}")


CHECKS: dict[str, Callable[[Path], CheckResult]] = {
    "plan": check_plan,
    "install": check_install,
    "activation": check_activation,
    "channels": check_channels,
    "uptime_beats": check_uptime_beats,
    "reboot_recovery": check_reboot_recovery,
    "no_unplanned_restarts": check_no_unplanned_restarts,
    "egress_continuity": check_egress_continuity,
    "completion": check_completion,
}


def _hyperv_unavailable_verdict(
    output_dir: Path, source_sha: str | None, run_id: str | None
) -> dict[str, Any] | None:
    """Return a HYPERV_UNAVAILABLE verdict if the marker is present, else None.

    Gate B needs a persistent VM that can reboot, which on this box means
    Hyper-V. ``gate-b/Test-GateBPrereqs.ps1`` writes ``HYPERV-UNAVAILABLE.txt``
    when the feature is disabled (it REPORTS the one elevated command that
    would enable it; it never attempts elevation itself). In that case no VM
    was ever created, so none of the required checks' evidence files exist and
    running them as usual would produce a misleading wall of FAILs. This
    short-circuits to a distinct verdict instead, with an empty ``checks``
    dict -- the same reasoning, and the same shape, as Gate A's ``BUSY``.
    """
    marker = output_dir / "HYPERV-UNAVAILABLE.txt"
    if not marker.is_file():
        return None
    detail, err = _read_text(output_dir, "HYPERV-UNAVAILABLE.txt")
    if err is not None:
        detail = err
    else:
        assert detail is not None
        detail = detail.strip()
    if not detail:
        detail = "HYPERV-UNAVAILABLE.txt is present (no detail recorded)"
    return {
        "schema_version": SCHEMA_VERSION,
        "source_sha": source_sha,
        "run_id": run_id,
        "verdict": "HYPERV_UNAVAILABLE",
        "reason": "hyperv-not-enabled-on-host",
        "detail": detail,
        "checks": {},
        "plan": None,
        "beat_count": None,
        "reboot_recovery_minutes": None,
        "evidence_dir": str(output_dir),
        "judged_utc": datetime.now(UTC).isoformat(),
    }


def _informational_facts(output_dir: Path) -> dict[str, Any]:
    """Facts recorded for the human report, never gating.

    Degrades to nulls rather than affecting the verdict at all -- this block
    never raises.
    """
    facts: dict[str, Any] = {"plan": None, "beat_count": None, "reboot_recovery_minutes": None}
    plan, _perr = _read_plan(output_dir)
    if isinstance(plan, dict):
        facts["plan"] = plan
    beats, _berr = _read_beats(output_dir)
    if beats is None:
        return facts
    facts["beat_count"] = len(beats)
    boots = [beat.get("system_boot_utc") for beat in beats]
    transitions = [i for i in range(1, len(boots)) if boots[i] != boots[i - 1]]
    if len(transitions) != 1:
        return facts
    index = transitions[0]
    before = _beat_float(beats[index - 1], "elapsed_minutes")
    if before is None:
        return facts
    for beat in beats[index:]:
        on_air = _beat_on_air_channels(beat)
        if _beat_health_ok(beat) and on_air is not None and set(REQUIRED_CHANNELS) <= on_air:
            after = _beat_float(beat, "elapsed_minutes")
            if after is not None:
                facts["reboot_recovery_minutes"] = round(after - before, 2)
            return facts
    return facts


def judge(output_dir: Path, source_sha: str | None, run_id: str | None) -> dict[str, Any]:
    """Run every required check against output_dir and build the verdict document.

    HYPERV-UNAVAILABLE.txt short-circuits this before any required check runs
    -- see ``_hyperv_unavailable_verdict``.
    """
    unavailable = _hyperv_unavailable_verdict(output_dir, source_sha, run_id)
    if unavailable is not None:
        return unavailable

    checks: dict[str, dict[str, str]] = {}
    for name, fn in CHECKS.items():
        try:
            result = fn(output_dir)
        except Exception as exc:  # fail-closed even on a bug in a check itself, never propagate
            result = _fail(f"unhandled exception while evaluating this check: {exc!r}")
        checks[name] = {"status": result.status, "detail": result.detail}

    # A harness error outranks the checks entirely. The checks are still run
    # and still reported -- on a partially-shipped run they are real
    # forensics -- but a broken harness cannot be converted into a statement
    # about the candidate in either direction.
    harness_error = detect_harness_error(output_dir)
    if harness_error is not None:
        verdict = "HARNESS_ERROR"
    elif all(c["status"] == "PASS" for c in checks.values()):
        verdict = "PASS"
    else:
        verdict = "FAIL"

    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source_sha": source_sha,
        "run_id": run_id,
        "verdict": verdict,
        "harness_error": harness_error,
        "checks": checks,
        "evidence_dir": str(output_dir),
        "judged_utc": datetime.now(UTC).isoformat(),
    }
    document.update(_informational_facts(output_dir))
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "output_dir",
        type=Path,
        help="Directory containing a Gate B reboot-soak run's evidence files",
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
        help="Where to write gate-b-verdict.json (default: <output_dir>/gate-b-verdict.json)",
    )
    args = parser.parse_args(argv)

    output_dir: Path = args.output_dir
    if not output_dir.is_dir():
        print(
            f"gate_b_verdict: harness error -- output directory does not exist: {output_dir}",
            file=sys.stderr,
        )
        return 2

    result = judge(output_dir, args.source_sha, args.run_id)
    out_path: Path = args.out if args.out is not None else output_dir / "gate-b-verdict.json"
    out_path.write_text(json.dumps(result, indent=2, sort_keys=False) + "\n", encoding="utf-8")

    print(json.dumps(result, indent=2, sort_keys=False))
    print(f"\ngate_b_verdict: {result['verdict']} (written to {out_path})", file=sys.stderr)

    if result["verdict"] == "PASS":
        return 0
    if result["verdict"] == "HYPERV_UNAVAILABLE":
        # The gate could not observe the candidate at all: no hypervisor, no
        # VM, no run. Same exit-code family as the missing-output-dir usage
        # error above, never 1 (FAIL).
        return 2
    if result["verdict"] == "HARNESS_ERROR":
        # Same family again. HYPERV_UNAVAILABLE means it never started; this
        # means it started and lost its VM or its evidence channel partway.
        print(f"gate_b_verdict: harness error -- {result['harness_error']}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
