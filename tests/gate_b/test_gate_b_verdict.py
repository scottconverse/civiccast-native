# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for ``scripts/gate_b_verdict.py`` -- the 24h reboot-soak judge.

Every evidence directory here is built SYNTHETICALLY in ``tmp_path``. Gate B
has never been run, so there is no captured fixture to anchor on, and
inventing one that reads as real would be the authored-truth failure the gate
exists to prevent. See ``tests/gate_b/fixtures/README.md``.

What that means for what these tests prove: they prove the judge's LOGIC --
that each check fails closed on each way its evidence can be wrong, that the
two non-verdicts are not FAILs, and that the CLI's exit codes match the
contract. They prove nothing whatsoever about the product, and a synthetic
PASS here must never be cited as a Gate B pass.

The module is loaded by file path, not imported as a package, matching
``tests/gate_a/test_gate_a_verdict.py``.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "gate_b_verdict.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gate_b_verdict", _MODULE_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


gbv = _load_module()

REQUIRED_CHECKS = (
    "plan",
    "install",
    "activation",
    "channels",
    "uptime_beats",
    "reboot_recovery",
    "no_unplanned_restarts",
    "egress_continuity",
    "completion",
)

# The plan a real Gate B run executes: the 3.0 MASTER spec §12 floor.
PLAN: dict[str, Any] = {
    "soak_minutes": 1440,
    "beat_interval_minutes": 5,
    "reboot_at_minutes": 720,
    "reboot_gap_budget_minutes": 20,
    "recovery_budget_minutes": 15,
    "beat_slack_minutes": 2,
}

BOOT_ONE = "2026-09-01T00:00:00.0000000Z"
BOOT_TWO = "2026-09-01T12:12:00.0000000Z"

# The first post-reboot beat, in soak-elapsed minutes. Deliberately 12 minutes
# after the last pre-reboot beat (at 720), which is:
#   * ABOVE beat_interval + beat_slack (7), so the happy-path fixture actually
#     exercises the judge's reboot-gap branch rather than sailing through the
#     "no oversized gap at all" branch. An earlier version of this fixture used
#     727 and silently never tested the branch it was written for.
#   * inside reboot_gap_budget_minutes (20) and recovery_budget_minutes (15).
FIRST_POST_REBOOT_ELAPSED = 732.0


def _supervisor(service_pid: int, child_pids: dict[str, int]) -> dict[str, Any]:
    return {
        "service_state": "Running",
        "service_pid": service_pid,
        "children": {
            name: {"pid": pid, "name": "python.exe", "start_utc": BOOT_ONE}
            for name, pid in child_pids.items()
        },
    }


def _beat(
    seq: int,
    elapsed: float,
    boot: str,
    *,
    healthy: bool = True,
    on_air: tuple[str, ...] = ("public", "education", "government"),
    unattended: bool = True,
    service_pid: int = 4100,
    child_pids: dict[str, int] | None = None,
) -> dict[str, Any]:
    if child_pids is None:
        child_pids = {"python.exe#1": 5200, "python.exe#2": 5300}
    return {
        "schema": "civiccast-gate-b-beat-v1",
        "run_id": "synthetic",
        "beat_seq": seq,
        "utc": f"2026-09-01T00:{seq % 60:02d}:00.0000000Z",
        "elapsed_minutes": elapsed,
        "system_boot_utc": boot,
        "launched_by": "bootstrap" if boot == BOOT_ONE else "startup-task",
        "unattended": unattended,
        "health": {
            "http_status": 200 if healthy else None,
            "ok": healthy,
            "status": "healthy" if healthy else "unreachable",
            "schema": "current",
            "mode": "normal",
        },
        "channels": [
            {
                "channel_id": cid,
                "udp_port": port,
                "on_air": cid in on_air,
                "state": "running",
                "engine": "gstreamer",
            }
            for cid, port in (("public", 9001), ("education", 9002), ("government", 9003))
        ],
        "supervisor": _supervisor(service_pid, child_pids),
    }


def _default_beats() -> list[dict[str, Any]]:
    """A clean 24h run: 5-minute beats, one reboot at 720m, back at 727m.

    720 / 5 = 144 pre-reboot beats plus the beat at t=0, then the gap across
    the reboot, then beats every 5 minutes to 1440.
    """
    beats: list[dict[str, Any]] = []
    seq = 1
    elapsed = 0.0
    while elapsed <= 720.0:
        beats.append(_beat(seq, elapsed, BOOT_ONE))
        seq += 1
        elapsed += 5.0
    # The reboot: a 12-minute gap (inside the 20-minute budget), new boot
    # epoch, new pids -- a reboot legitimately changes every pid, which is why
    # the restart check groups BY boot epoch rather than comparing across one.
    elapsed = FIRST_POST_REBOOT_ELAPSED
    while elapsed <= 1440.0:
        beats.append(
            _beat(
                seq,
                elapsed,
                BOOT_TWO,
                service_pid=4900,
                child_pids={"python.exe#1": 6100, "python.exe#2": 6200},
            )
        )
        seq += 1
        elapsed += 5.0
    return beats


def _egress_doc() -> dict[str, Any]:
    return {
        "schema": "civiccast-soak-egress-verify-v1",
        "heartbeat_index": 1,
        "utc": "20260901T120000Z",
        "seconds": 15,
        "overall_verdict": "pass",
        "channels": [
            {
                "channel": cid,
                "destination": f"udp://127.0.0.1:{port}?pkt_size=1316",
                "verdict": "pass",
                "checks": {"invalid_syncs": 0, "transport_errors": 0, "discontinuities": 0},
            }
            for cid, port in (("public", 9001), ("education", 9002), ("government", 9003))
        ],
    }


def _write_beats(run_dir: Path, beats: list[dict[str, Any]]) -> None:
    (run_dir / "beats.jsonl").write_text(
        "".join(json.dumps(b) + "\n" for b in beats), encoding="utf-8"
    )


def _pass_evidence(tmp_path: Path, **overrides: Any) -> Path:
    """A complete, internally consistent evidence directory that judges PASS.

    Every negative test starts from this and breaks exactly one thing, so a
    FAIL in those tests is attributable to the thing that was broken and not
    to an incidental gap in the fixture.
    """
    run_dir = tmp_path / "evidence"
    run_dir.mkdir(exist_ok=True)

    plan = dict(PLAN)
    plan.update(overrides.get("plan", {}))
    (run_dir / "gate-b-run.json").write_text(
        json.dumps(
            {
                "schema": "civiccast-gate-b-run-v1",
                "source_sha": "deadbee",
                "run_id": "1234",
                "vm_name": "CivicCastGateB",
                "plan": plan,
            }
        ),
        encoding="utf-8",
    )

    summary = {
        "schema": "civiccast-gate-b-install-summary-v1",
        "installer_exit_code": 0,
        "station_set_json_found": ["C:\\CivicCast\\install\\station-set.json"],
        "activation_self_test_json_found": ["C:\\CivicCast\\install\\activation-self-test.json"],
        "station_up": True,
    }
    summary.update(overrides.get("summary", {}))
    (run_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    (run_dir / "ACTIVATION-RESULT.txt").write_text(
        overrides.get(
            "activation_text",
            "installer_exit_code=0\ninstall_dir=C:\\CivicCast\\install\n"
            "station_set_json_found_after_install=1\n",
        ),
        encoding="utf-8",
    )

    _write_beats(run_dir, overrides.get("beats", _default_beats()))

    (run_dir / "REBOOT-RESULT.txt").write_text(
        overrides.get(
            "reboot_text",
            "reboot_issued_utc=2026-09-01T12:00:00.0000000Z\n"
            "reboot_at_minutes_planned=720\n"
            "reboot_at_minutes_actual=720.4\n"
            "method=Restart-VM (graceful guest restart via integration services)\n"
            "operator_interaction=none\n",
        ),
        encoding="utf-8",
    )

    for name in ("egress-verify-pre-reboot.json", "egress-verify-post-reboot.json"):
        doc = overrides.get(name.replace("-", "_").replace(".json", ""), _egress_doc())
        (run_dir / name).write_text(json.dumps(doc), encoding="utf-8")

    logs = run_dir / "supervisor-logs"
    logs.mkdir(exist_ok=True)
    (logs / "supervisor.log").write_text(
        overrides.get(
            "supervisor_log",
            "2026-09-01 00:00:01 INFO supervisor logging initialized (pid 4100, sinks 2)\n"
            "2026-09-01 00:00:30 INFO children_ready\n",
        ),
        encoding="utf-8",
    )

    done = {
        "done_utc": "2026-09-02T00:00:00.0000000Z",
        "harness_completed": True,
        "watchdog_timeout": False,
        "stall_timeout": False,
        "run_id": "synthetic",
    }
    done.update(overrides.get("done", {}))
    (run_dir / "DONE.json").write_text(json.dumps(done), encoding="utf-8")

    return run_dir


# ---------------------------------------------------------------------------
# The happy path, and the shape of the verdict document
# ---------------------------------------------------------------------------


def test_synthetic_complete_run_passes_every_check(tmp_path: Path) -> None:
    result = gbv.judge(_pass_evidence(tmp_path), "deadbee", "1234")
    for name in REQUIRED_CHECKS:
        assert result["checks"][name]["status"] == "PASS", (
            f"{name} unexpectedly FAILed: {result['checks'][name]['detail']}"
        )
    assert result["verdict"] == "PASS"


def test_every_required_check_is_registered() -> None:
    # A check that exists in the module but is not in CHECKS never runs and
    # never decides anything -- a silent hole in a fail-closed judge.
    assert tuple(gbv.CHECKS) == REQUIRED_CHECKS


def test_verdict_document_carries_the_informational_facts(tmp_path: Path) -> None:
    result = gbv.judge(_pass_evidence(tmp_path), "deadbee", "1234")
    assert result["schema_version"] == gbv.SCHEMA_VERSION
    assert result["source_sha"] == "deadbee"
    assert result["run_id"] == "1234"
    assert result["plan"]["soak_minutes"] == 1440
    assert result["beat_count"] > 280
    # 732 - 720 = 12 minutes from the last pre-reboot beat to the first
    # post-reboot beat that was healthy with all three channels on air.
    assert result["reboot_recovery_minutes"] == pytest.approx(12.0)


# ---------------------------------------------------------------------------
# plan -- the check that refuses to grade a rehearsal as the real thing
# ---------------------------------------------------------------------------


def test_short_soak_fails_the_plan_check(tmp_path: Path) -> None:
    """A 30-minute rehearsal is reported as a FAIL, not quietly graded.

    This is the single most important negative test in the file: the harness
    deliberately exposes -SoakMinutes so the mechanics can be rehearsed, and
    the ONLY thing preventing "we ran Gate B" from coming to mean "we ran
    something" is that the judge says so out loud.
    """
    run_dir = _pass_evidence(tmp_path, plan={"soak_minutes": 30})
    result = gbv.judge(run_dir, None, None)
    assert result["checks"]["plan"]["status"] == "FAIL"
    assert "1440" in result["checks"]["plan"]["detail"]
    assert result["verdict"] == "FAIL"


def test_there_is_no_short_soak_escape_hatch() -> None:
    """The judge exposes no CLI flag that could waive the §12 floor.

    Asserted against the parser's ACTUAL registered options rather than
    against the source text: the module docstring says out loud that there is
    no ``--allow-short-soak``, and a naive substring scan would then fail on
    the very sentence promising the flag does not exist.
    """
    parser = None
    for action in _judge_parser()._actions:
        for option in action.option_strings:
            assert option in {"-h", "--help", "--source-sha", "--run-id", "--out"}, (
                f"{option!r} is an unexpected judge option; the plan check must not be bypassable"
            )
    assert parser is None  # nothing else registers a parser behind our back


def _judge_parser() -> Any:
    """Build the judge's argparse parser without running it."""
    import argparse
    import contextlib
    import io

    # main() builds the parser then immediately parses; invoking it with a
    # bad argv and catching SystemExit is fragile. Rebuild from the module's
    # own definition instead by calling main with --help suppressed.
    holder: dict[str, Any] = {}
    original = argparse.ArgumentParser.parse_args

    def _capture(self: Any, *args: Any, **kwargs: Any) -> Any:
        holder["parser"] = self
        raise SystemExit(0)

    argparse.ArgumentParser.parse_args = _capture  # type: ignore[method-assign]
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.suppress(SystemExit):
            gbv.main([])
    finally:
        argparse.ArgumentParser.parse_args = original  # type: ignore[method-assign]
    assert "parser" in holder, "could not capture the judge's argument parser"
    return holder["parser"]


def test_slow_beat_cadence_fails_the_plan_check(tmp_path: Path) -> None:
    run_dir = _pass_evidence(tmp_path, plan={"beat_interval_minutes": 15})
    result = gbv.judge(run_dir, None, None)
    assert result["checks"]["plan"]["status"] == "FAIL"
    assert "S9" in result["checks"]["plan"]["detail"]


def test_reboot_outside_the_soak_window_fails_the_plan_check(tmp_path: Path) -> None:
    run_dir = _pass_evidence(tmp_path, plan={"reboot_at_minutes": 2000})
    result = gbv.judge(run_dir, None, None)
    assert result["checks"]["plan"]["status"] == "FAIL"


def test_missing_run_document_fails_every_plan_dependent_check(tmp_path: Path) -> None:
    run_dir = _pass_evidence(tmp_path)
    (run_dir / "gate-b-run.json").unlink()
    result = gbv.judge(run_dir, None, None)
    for name in ("plan", "uptime_beats", "reboot_recovery"):
        assert result["checks"][name]["status"] == "FAIL", name
    assert result["verdict"] == "FAIL"


# ---------------------------------------------------------------------------
# install / activation
# ---------------------------------------------------------------------------


def test_nonzero_installer_exit_fails_install(tmp_path: Path) -> None:
    run_dir = _pass_evidence(tmp_path, summary={"installer_exit_code": 123})
    result = gbv.judge(run_dir, None, None)
    assert result["checks"]["install"]["status"] == "FAIL"
    assert "123" in result["checks"]["install"]["detail"]


def test_missing_station_set_fails_install(tmp_path: Path) -> None:
    run_dir = _pass_evidence(tmp_path, summary={"station_set_json_found": []})
    result = gbv.judge(run_dir, None, None)
    assert result["checks"]["install"]["status"] == "FAIL"


def test_missing_activation_self_test_fails_activation(tmp_path: Path) -> None:
    run_dir = _pass_evidence(tmp_path, summary={"activation_self_test_json_found": []})
    result = gbv.judge(run_dir, None, None)
    assert result["checks"]["activation"]["status"] == "FAIL"


def test_activation_result_zero_hits_fails_activation(tmp_path: Path) -> None:
    run_dir = _pass_evidence(
        tmp_path,
        activation_text=(
            "installer_exit_code=0\ninstall_dir=C:\\CivicCast\\install\n"
            "station_set_json_found_after_install=0\n"
        ),
    )
    result = gbv.judge(run_dir, None, None)
    assert result["checks"]["activation"]["status"] == "FAIL"


# ---------------------------------------------------------------------------
# channels -- §12's three concurrent PEG channels
# ---------------------------------------------------------------------------


def test_a_single_channel_dropping_for_one_beat_fails_channels(tmp_path: Path) -> None:
    """One 5-minute window off air is a channel that went dark.

    Not "mostly on air": §12 pairs "runs the three PEG channels concurrently"
    with "the box calls for help when it goes off-air unattended", and a gate
    that tolerates a dropout is a gate that would have passed the outage.
    """
    beats = _default_beats()
    beats[50] = _beat(
        beats[50]["beat_seq"],
        beats[50]["elapsed_minutes"],
        BOOT_ONE,
        on_air=("public", "education"),
    )
    run_dir = _pass_evidence(tmp_path, beats=beats)
    result = gbv.judge(run_dir, None, None)
    assert result["checks"]["channels"]["status"] == "FAIL"
    assert "government" in result["checks"]["channels"]["detail"]


def test_required_channels_are_the_spec_triad() -> None:
    assert set(gbv.REQUIRED_CHANNELS) == {"public", "education", "government"}


# ---------------------------------------------------------------------------
# uptime_beats
# ---------------------------------------------------------------------------


def test_an_unhealthy_beat_fails_uptime(tmp_path: Path) -> None:
    beats = _default_beats()
    beats[100] = _beat(
        beats[100]["beat_seq"], beats[100]["elapsed_minutes"], BOOT_ONE, healthy=False
    )
    result = gbv.judge(_pass_evidence(tmp_path, beats=beats), None, None)
    assert result["checks"]["uptime_beats"]["status"] == "FAIL"


def test_a_second_oversized_gap_fails_uptime(tmp_path: Path) -> None:
    """Only the planned reboot may open a gap. A second one is an outage."""
    beats = _default_beats()
    # Drop four consecutive beats early in the run, opening a ~25-minute hole
    # that no boot transition explains.
    del beats[20:24]
    result = gbv.judge(_pass_evidence(tmp_path, beats=beats), None, None)
    assert result["checks"]["uptime_beats"]["status"] == "FAIL"
    assert "gaps exceed" in result["checks"]["uptime_beats"]["detail"]


def test_an_oversized_gap_that_does_not_straddle_a_reboot_fails_uptime(tmp_path: Path) -> None:
    beats = [b for b in _default_beats() if b["system_boot_utc"] == BOOT_ONE]
    del beats[20:24]
    # Re-close the run so the coverage assertion is not what fires.
    beats.append(_beat(999, 1440.0, BOOT_ONE))
    result = gbv.judge(_pass_evidence(tmp_path, beats=beats), None, None)
    assert result["checks"]["uptime_beats"]["status"] == "FAIL"


def test_a_run_that_stops_sampling_early_fails_uptime(tmp_path: Path) -> None:
    beats = [b for b in _default_beats() if b["elapsed_minutes"] <= 400.0]
    result = gbv.judge(_pass_evidence(tmp_path, beats=beats), None, None)
    assert result["checks"]["uptime_beats"]["status"] == "FAIL"
    assert "does not cover the whole soak" in result["checks"]["uptime_beats"]["detail"]


def test_a_reboot_gap_over_budget_fails_uptime(tmp_path: Path) -> None:
    beats = [b for b in _default_beats() if b["system_boot_utc"] == BOOT_ONE]
    seq = beats[-1]["beat_seq"] + 1
    elapsed = 745.0  # 25 minutes after the last pre-reboot beat; budget is 20
    while elapsed <= 1440.0:
        beats.append(
            _beat(
                seq,
                elapsed,
                BOOT_TWO,
                service_pid=4900,
                child_pids={"python.exe#1": 6100, "python.exe#2": 6200},
            )
        )
        seq += 1
        elapsed += 5.0
    result = gbv.judge(_pass_evidence(tmp_path, beats=beats), None, None)
    assert result["checks"]["uptime_beats"]["status"] == "FAIL"
    assert "reboot_gap_budget_minutes" in result["checks"]["uptime_beats"]["detail"]


def test_malformed_beat_line_fails_closed_rather_than_being_skipped(tmp_path: Path) -> None:
    run_dir = _pass_evidence(tmp_path)
    text = (run_dir / "beats.jsonl").read_text(encoding="utf-8")
    lines = text.splitlines()
    lines[10] = "{this is not json"
    (run_dir / "beats.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = gbv.judge(run_dir, None, None)
    assert result["checks"]["uptime_beats"]["status"] == "FAIL"
    assert "not valid JSON" in result["checks"]["uptime_beats"]["detail"]


def test_wrong_beat_schema_fails_closed(tmp_path: Path) -> None:
    beats = _default_beats()
    beats[5]["schema"] = "civiccast-soak-heartbeat-v1"
    result = gbv.judge(_pass_evidence(tmp_path, beats=beats), None, None)
    assert result["checks"]["uptime_beats"]["status"] == "FAIL"


# ---------------------------------------------------------------------------
# reboot_recovery -- the §12 line Gate A structurally cannot test
# ---------------------------------------------------------------------------


def test_a_soak_with_no_reboot_fails(tmp_path: Path) -> None:
    """The whole point of Gate B. A clean 24h with no reboot is still a FAIL."""
    beats = []
    seq = 1
    elapsed = 0.0
    while elapsed <= 1440.0:
        beats.append(_beat(seq, elapsed, BOOT_ONE))
        seq += 1
        elapsed += 5.0
    result = gbv.judge(_pass_evidence(tmp_path, beats=beats), None, None)
    assert result["checks"]["reboot_recovery"]["status"] == "FAIL"
    assert "no reboot observed" in result["checks"]["reboot_recovery"]["detail"]
    assert result["verdict"] == "FAIL"


def test_a_second_unplanned_reboot_fails(tmp_path: Path) -> None:
    beats = _default_beats()
    for beat in beats[-10:]:
        beat["system_boot_utc"] = "2026-09-01T23:00:00.0000000Z"
    result = gbv.judge(_pass_evidence(tmp_path, beats=beats), None, None)
    assert result["checks"]["reboot_recovery"]["status"] == "FAIL"
    assert "2 reboots observed" in result["checks"]["reboot_recovery"]["detail"]


def test_recovery_without_channels_back_on_air_fails(tmp_path: Path) -> None:
    """ "Came back" is not "came back to broadcasting"."""
    beats = _default_beats()
    for beat in beats:
        if beat["system_boot_utc"] == BOOT_TWO:
            for channel in beat["channels"]:
                channel["on_air"] = False
    result = gbv.judge(_pass_evidence(tmp_path, beats=beats), None, None)
    assert result["checks"]["reboot_recovery"]["status"] == "FAIL"
    assert "BROADCASTING" in result["checks"]["reboot_recovery"]["detail"]


def test_slow_recovery_over_budget_fails(tmp_path: Path) -> None:
    beats = _default_beats()
    # The station answers after the reboot but no channel is on air until 20
    # minutes in -- inside the 20-minute gap budget, outside the 15-minute
    # recovery budget. The two budgets measure different things and this test
    # exists to keep them from collapsing into one.
    for beat in beats:
        if beat["system_boot_utc"] == BOOT_TWO and beat["elapsed_minutes"] < 740.0:
            for channel in beat["channels"]:
                channel["on_air"] = False
    result = gbv.judge(_pass_evidence(tmp_path, beats=beats), None, None)
    assert result["checks"]["reboot_recovery"]["status"] == "FAIL"
    assert "recovery_budget_minutes" in result["checks"]["reboot_recovery"]["detail"]


def test_an_attended_reboot_fails(tmp_path: Path) -> None:
    """Someone logged into the VM: the beats say so, and it is not a PASS."""
    beats = _default_beats()
    for beat in beats:
        if beat["system_boot_utc"] == BOOT_TWO:
            beat["unattended"] = False
    result = gbv.judge(_pass_evidence(tmp_path, beats=beats), None, None)
    assert result["checks"]["reboot_recovery"]["status"] == "FAIL"
    assert "UNATTENDED" in result["checks"]["reboot_recovery"]["detail"]


def test_missing_operator_interaction_line_fails(tmp_path: Path) -> None:
    run_dir = _pass_evidence(tmp_path, reboot_text="reboot_issued_utc=2026-09-01T12:00:00Z\n")
    result = gbv.judge(run_dir, None, None)
    assert result["checks"]["reboot_recovery"]["status"] == "FAIL"
    assert "operator_interaction=none" in result["checks"]["reboot_recovery"]["detail"]


def test_missing_reboot_result_file_fails(tmp_path: Path) -> None:
    run_dir = _pass_evidence(tmp_path)
    (run_dir / "REBOOT-RESULT.txt").unlink()
    result = gbv.judge(run_dir, None, None)
    assert result["checks"]["reboot_recovery"]["status"] == "FAIL"


# ---------------------------------------------------------------------------
# no_unplanned_restarts -- two instruments of different kinds
# ---------------------------------------------------------------------------


def test_a_child_pid_change_within_one_boot_epoch_fails(tmp_path: Path) -> None:
    beats = _default_beats()
    for beat in beats[60:]:
        if beat["system_boot_utc"] == BOOT_ONE:
            beat["supervisor"]["children"]["python.exe#2"]["pid"] = 5999
    result = gbv.judge(_pass_evidence(tmp_path, beats=beats), None, None)
    assert result["checks"]["no_unplanned_restarts"]["status"] == "FAIL"
    assert "unplanned child restart" in result["checks"]["no_unplanned_restarts"]["detail"]


def test_a_service_pid_change_within_one_boot_epoch_fails(tmp_path: Path) -> None:
    beats = _default_beats()
    for beat in beats[60:]:
        if beat["system_boot_utc"] == BOOT_ONE:
            beat["supervisor"]["service_pid"] = 4999
    result = gbv.judge(_pass_evidence(tmp_path, beats=beats), None, None)
    assert result["checks"]["no_unplanned_restarts"]["status"] == "FAIL"
    assert "unplanned service restart" in result["checks"]["no_unplanned_restarts"]["detail"]


def test_pids_legitimately_change_across_the_reboot(tmp_path: Path) -> None:
    """The reboot changes every pid, and that must NOT read as a restart.

    The check groups by boot epoch precisely so the one event §12 requires
    does not trip the check that exists to catch the events §12 forbids.
    """
    result = gbv.judge(_pass_evidence(tmp_path), None, None)
    assert result["checks"]["no_unplanned_restarts"]["status"] == "PASS"


def test_a_child_vanishing_mid_epoch_fails(tmp_path: Path) -> None:
    """A death with no restart is invisible to a pid-equality check alone."""
    beats = _default_beats()
    for beat in beats[60:]:
        if beat["system_boot_utc"] == BOOT_ONE:
            beat["supervisor"]["children"].pop("python.exe#2", None)
    result = gbv.judge(_pass_evidence(tmp_path, beats=beats), None, None)
    assert result["checks"]["no_unplanned_restarts"]["status"] == "FAIL"
    assert "vanished=['python.exe#2']" in result["checks"]["no_unplanned_restarts"]["detail"]


def test_a_child_appearing_mid_epoch_fails(tmp_path: Path) -> None:
    beats = _default_beats()
    for beat in beats[60:]:
        if beat["system_boot_utc"] == BOOT_ONE:
            beat["supervisor"]["children"]["python.exe#3"] = {
                "pid": 5400,
                "name": "python.exe",
                "start_utc": BOOT_ONE,
            }
    result = gbv.judge(_pass_evidence(tmp_path, beats=beats), None, None)
    assert result["checks"]["no_unplanned_restarts"]["status"] == "FAIL"
    assert "appeared=['python.exe#3']" in result["checks"]["no_unplanned_restarts"]["detail"]


def test_missing_supervisor_log_fails_rather_than_passing_by_silence(tmp_path: Path) -> None:
    run_dir = _pass_evidence(tmp_path)
    (run_dir / "supervisor-logs" / "supervisor.log").unlink()
    result = gbv.judge(run_dir, None, None)
    assert result["checks"]["no_unplanned_restarts"]["status"] == "FAIL"
    assert "pass by silence" in result["checks"]["no_unplanned_restarts"]["detail"]


def test_empty_supervisor_log_fails(tmp_path: Path) -> None:
    run_dir = _pass_evidence(tmp_path, supervisor_log="   \n")
    result = gbv.judge(run_dir, None, None)
    assert result["checks"]["no_unplanned_restarts"]["status"] == "FAIL"


def test_supervisor_restart_warning_fails(tmp_path: Path) -> None:
    """The corroborating instrument, matched against the supervisor's real wording.

    The pattern is the verbatim message
    ``civiccast/native/supervisor/core.py``'s ``_log_restart_not_ready``
    emits, so this test also guards against the judge quietly drifting to a
    pattern the product never writes.
    """
    run_dir = _pass_evidence(
        tmp_path,
        supervisor_log=(
            "2026-09-01 00:00:01 INFO supervisor logging initialized (pid 4100, sinks 2)\n"
            "2026-09-01 06:14:22 WARNING restart of child control_plane not ready: "
            "detail=readiness probe timed out\n"
        ),
    )
    result = gbv.judge(run_dir, None, None)
    assert result["checks"]["no_unplanned_restarts"]["status"] == "FAIL"
    assert "control_plane" in result["checks"]["no_unplanned_restarts"]["detail"]


# ---------------------------------------------------------------------------
# egress_continuity
# ---------------------------------------------------------------------------


def test_missing_post_reboot_egress_verify_fails(tmp_path: Path) -> None:
    run_dir = _pass_evidence(tmp_path)
    (run_dir / "egress-verify-post-reboot.json").unlink()
    result = gbv.judge(run_dir, None, None)
    assert result["checks"]["egress_continuity"]["status"] == "FAIL"


def test_a_failed_channel_after_the_reboot_fails_continuity(tmp_path: Path) -> None:
    doc = _egress_doc()
    doc["overall_verdict"] = "fail"
    doc["channels"][2]["verdict"] = "fail"
    doc["channels"][2]["checks"] = {
        "invalid_syncs": 0,
        "transport_errors": 0,
        "discontinuities": 41,
    }
    run_dir = _pass_evidence(tmp_path, egress_verify_post_reboot=doc)
    result = gbv.judge(run_dir, None, None)
    assert result["checks"]["egress_continuity"]["status"] == "FAIL"
    assert "after the reboot" in result["checks"]["egress_continuity"]["detail"]


def test_a_not_run_tsduck_verdict_is_not_a_pass(tmp_path: Path) -> None:
    """verify-egress.ps1 emits 'not-run' when tsp is missing. Not a pass."""
    doc = _egress_doc()
    doc["overall_verdict"] = "not-run"
    for channel in doc["channels"]:
        channel["verdict"] = "not-run"
        channel["detail"] = "TSDuck tsp not found; set TSP or CIVICCAST_TSDUCK_PATH"
    run_dir = _pass_evidence(tmp_path, egress_verify_pre_reboot=doc)
    result = gbv.judge(run_dir, None, None)
    assert result["checks"]["egress_continuity"]["status"] == "FAIL"


def test_egress_doc_missing_a_channel_fails(tmp_path: Path) -> None:
    doc = _egress_doc()
    doc["channels"] = doc["channels"][:2]
    run_dir = _pass_evidence(tmp_path, egress_verify_pre_reboot=doc)
    result = gbv.judge(run_dir, None, None)
    assert result["checks"]["egress_continuity"]["status"] == "FAIL"
    assert "government" in result["checks"]["egress_continuity"]["detail"]


# ---------------------------------------------------------------------------
# completion
# ---------------------------------------------------------------------------


def test_watchdog_forced_completion_is_not_a_completion(tmp_path: Path) -> None:
    run_dir = _pass_evidence(tmp_path)
    (run_dir / "WATCHDOG-TIMEOUT.txt").write_text("host deadline reached\n", encoding="utf-8")
    result = gbv.judge(run_dir, None, None)
    assert result["checks"]["completion"]["status"] == "FAIL"
    assert result["verdict"] == "FAIL"


def test_harness_completed_false_fails_completion(tmp_path: Path) -> None:
    run_dir = _pass_evidence(tmp_path, done={"harness_completed": False})
    result = gbv.judge(run_dir, None, None)
    assert result["checks"]["completion"]["status"] == "FAIL"


def test_missing_done_json_fails_completion(tmp_path: Path) -> None:
    run_dir = _pass_evidence(tmp_path)
    (run_dir / "DONE.json").unlink()
    result = gbv.judge(run_dir, None, None)
    assert result["checks"]["completion"]["status"] == "FAIL"


# ---------------------------------------------------------------------------
# The two non-verdicts -- neither may ever present as FAIL
# ---------------------------------------------------------------------------


def test_hyperv_unavailable_short_circuits_with_empty_checks(tmp_path: Path) -> None:
    run_dir = _pass_evidence(tmp_path)
    (run_dir / "HYPERV-UNAVAILABLE.txt").write_text(
        "instrument_1_optional_feature=Microsoft-Hyper-V-All:Disabled\n"
        "Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All -All -NoRestart\n",
        encoding="utf-8",
    )
    result = gbv.judge(run_dir, "deadbee", "1234")
    assert result["verdict"] == "HYPERV_UNAVAILABLE"
    assert result["verdict"] != "FAIL"
    assert result["checks"] == {}
    assert result["reason"] == "hyperv-not-enabled-on-host"
    # The remedy has to survive into the verdict document, or the operator
    # reads "unavailable" and has to go looking for what to do about it.
    assert "Enable-WindowsOptionalFeature" in result["detail"]


def test_host_error_marker_is_harness_error_not_fail(tmp_path: Path) -> None:
    """An otherwise all-PASS run carrying the marker is HARNESS_ERROR."""
    run_dir = _pass_evidence(tmp_path)
    (run_dir / "GATE-B-HOST-ERROR.txt").write_text("evidence pull failed\n", encoding="utf-8")
    result = gbv.judge(run_dir, None, None)
    assert result["verdict"] == "HARNESS_ERROR"
    assert result["verdict"] != "FAIL"
    assert "GATE-B-HOST-ERROR.txt" in result["harness_error"]


def test_vm_lost_marker_is_harness_error_not_fail(tmp_path: Path) -> None:
    run_dir = _pass_evidence(tmp_path)
    (run_dir / "VM-LOST.txt").write_text("the VM stopped at 23:14\n", encoding="utf-8")
    result = gbv.judge(run_dir, None, None)
    assert result["verdict"] == "HARNESS_ERROR"


def test_harness_error_still_computes_the_checks_as_forensics(tmp_path: Path) -> None:
    """Unlike HYPERV_UNAVAILABLE, a partially-run soak's checks are useful."""
    run_dir = _pass_evidence(tmp_path)
    (run_dir / "VM-LOST.txt").write_text("lost\n", encoding="utf-8")
    result = gbv.judge(run_dir, None, None)
    assert set(result["checks"]) == set(REQUIRED_CHECKS)
    assert result["checks"]["install"]["status"] == "PASS"


def test_every_harness_error_marker_has_a_substantive_explanation() -> None:
    for name, detail in gbv.HARNESS_ERROR_MARKERS.items():
        assert name.endswith(".txt"), name
        assert len(detail.strip()) > 40, f"{name}'s explanation is too thin to act on"
        assert name in detail, f"{detail!r} should name the marker file it is about"


# ---------------------------------------------------------------------------
# Fail-closed on a broken check, and the CLI contract
# ---------------------------------------------------------------------------


def test_a_raising_check_is_a_fail_not_a_crash(tmp_path: Path, monkeypatch: Any) -> None:
    def _boom(_output_dir: Path) -> Any:
        raise RuntimeError("instrument exploded")

    monkeypatch.setitem(gbv.CHECKS, "install", _boom)
    result = gbv.judge(_pass_evidence(tmp_path), None, None)
    assert result["checks"]["install"]["status"] == "FAIL"
    assert "instrument exploded" in result["checks"]["install"]["detail"]
    assert result["verdict"] == "FAIL"


def _run_cli(run_dir: Path, out_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(_MODULE_PATH),
            str(run_dir),
            "--source-sha",
            "deadbee",
            "--run-id",
            "1234",
            "--out",
            str(out_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_exit_0_on_a_synthetic_pass(tmp_path: Path) -> None:
    out_path = tmp_path / "gate-b-verdict.json"
    proc = _run_cli(_pass_evidence(tmp_path), out_path)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(out_path.read_text(encoding="utf-8"))["verdict"] == "PASS"


def test_cli_exit_1_on_a_real_finding(tmp_path: Path) -> None:
    run_dir = _pass_evidence(tmp_path, summary={"installer_exit_code": 123})
    out_path = tmp_path / "gate-b-verdict.json"
    proc = _run_cli(run_dir, out_path)
    assert proc.returncode == 1
    assert json.loads(out_path.read_text(encoding="utf-8"))["verdict"] == "FAIL"


def test_cli_exit_2_when_hyperv_was_unavailable(tmp_path: Path) -> None:
    """Exit 2, never 1: no VM ran, so nothing was observed about the candidate."""
    run_dir = _pass_evidence(tmp_path)
    (run_dir / "HYPERV-UNAVAILABLE.txt").write_text("disabled\n", encoding="utf-8")
    proc = _run_cli(run_dir, tmp_path / "v.json")
    assert proc.returncode == 2


def test_cli_exit_2_on_harness_error(tmp_path: Path) -> None:
    run_dir = _pass_evidence(tmp_path)
    (run_dir / "VM-LOST.txt").write_text("lost\n", encoding="utf-8")
    proc = _run_cli(run_dir, tmp_path / "v.json")
    assert proc.returncode == 2


def test_cli_exit_2_on_a_missing_output_directory(tmp_path: Path) -> None:
    proc = _run_cli(tmp_path / "nope", tmp_path / "v.json")
    assert proc.returncode == 2
    assert "does not exist" in proc.stderr


def test_cli_default_output_path_is_inside_the_evidence_dir(tmp_path: Path) -> None:
    run_dir = _pass_evidence(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(_MODULE_PATH), str(run_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert (run_dir / "gate-b-verdict.json").is_file()
