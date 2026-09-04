# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the Gate A verdict judge (``scripts/gate_a_verdict.py``).

Follows the same load-by-path pattern as
``tests/native/test_wp5_lifecycle_driver.py`` for importing a ``scripts/``
module that is not part of the ``civiccast`` package.

The PASS fixture (``fixtures/pass-2026-08-19/``) is a verbatim copy of the
real Aug-19 Windows Sandbox reference run's output directory (see
``scripts/gate_a_verdict.py``'s module docstring, "Known harness quirk").
That real run is missing ``DONE.json`` -- a genuine harness artifact of the
old host-side ``Watch-Run.ps1`` monitor racing ahead of the script's own
completion signal, not a fixture mistake. So the PASS fixture's own overall
verdict is FAIL (the ``completion`` check, specifically) even though every
other check on it is a real PASS. Tests below assert exactly that shape
first, then build a synthetic fully-complete evidence directory (the real
fixture plus a DONE.json) to exercise the all-PASS and per-check-FAIL paths.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "gate_a_verdict.py"
_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "pass-2026-08-19"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gate_a_verdict", _MODULE_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


gav = _load_module()

REQUIRED_CHECKS = (
    "install",
    "activation",
    "runtime",
    "t2_render",
    "t3_loop",
    "captions",
    "t4_engine",
    "t5_soak",
    # <gate-a-engine-soak> A no-op PASS when SOAK_MINUTES.txt <= 20 (or
    # absent, as in the historical fixture) -- required only when the
    # in-sandbox harness ran T6 instead of T5's health-only loop.
    "t6_engine_soak",
    # <gate-a-audit-MA-25> Added by the installer-path audit batch: the clean
    # lane previously had no check at all on install-progress.log, so an
    # installer that exited 0 after `postinstall: COMPLETED WITH A D3
    # ROLLBACK` passed every lane.
    "install_progress",
    "completion",
)

#: Checks the historical Aug-19 fixture genuinely cannot satisfy, with the
#: reason each one fails on it. The fixture is a verbatim copy of a real
#: pre-#143 harness run, so it predates the evidence these checks read -- and
#: in ``t4_engine``'s case it actually CONTAINS the defect the new check was
#: written to catch, which is why it is listed rather than papered over.
PRE_CONTRACT_CHECKS = {
    "completion": (
        "the Aug-19 run has no DONE.json -- the old host-side Watch-Run.ps1 monitor raced ahead "
        "of the script's own completion signal (see the judge's module docstring)"
    ),
    "t4_engine": (
        "<gate-a-audit-MA-27> the fixture's own egress-verify-engine.json reads "
        '"timed_out": true, "exit_code": null, "verdict": "pass" over a report with no packet '
        "count -- tsp was killed at its deadline and analysed nothing, and the old check read "
        "only the T4_RESULT= string, so it passed. The fixture IS the evidence for this finding."
    ),
    "install_progress": (
        "<gate-a-audit-MA-25> the pre-batch harness never wrote INSTALL-PROGRESS-RESULT.txt, so "
        "there is nothing for this check to grade on a historical run"
    ),
}


def _copy_fixture(dest: Path) -> Path:
    shutil.copytree(_FIXTURE_DIR, dest)
    return dest


def _write_synthetic_install_progress(run_dir: Path) -> None:
    """The INSTALL-PROGRESS-RESULT.txt shape a clean, successful install writes."""
    (run_dir / "INSTALL-PROGRESS-RESULT.txt").write_text(
        "\n".join(
            [
                "checked_utc=2026-08-19T09:29:00.000Z",
                "PHASE=post-install",
                "PHASE_LINE_COUNT=163",
                "D3_ROUTE=FRESH_INSTALL",
                "D3_ENGINE_EXIT=11",
                "D4_ACTIVATE_EXIT=0",
                "POSTINSTALL_OUTCOME=SUCCESS",
                "POSTINSTALL_ALERTS=0",
                "POSTINSTALL_NONZERO_STEPS=none",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_synthetic_engine_proof(run_dir: Path) -> None:
    """A TSDuck proof that actually analysed a transport stream.

    The real fixture's own artifact says ``timed_out: true, exit_code: null``
    -- see ``PRE_CONTRACT_CHECKS['t4_engine']``.
    """
    (run_dir / "egress-verify-engine.json").write_text(
        json.dumps(
            {
                "label": "engine-government",
                "port": 19003,
                "tsp_found": True,
                "ran": True,
                "timed_out": False,
                "exit_code": 0,
                "report_found": True,
                "report_bytes": 4096,
                "packets_total": 44_000,
                "invalid_syncs": 0,
                "transport_errors": 0,
                "discontinuities": 0,
                "verdict": "pass",
            }
        ),
        encoding="utf-8",
    )


def _synthetic_pass_dir(tmp_path: Path) -> Path:
    """A copy of the real fixture PLUS a synthetic DONE.json.

    This is the only place this test module invents evidence that was not
    actually produced by a harness run, and it does so only to exercise the
    judge's all-PASS code path in isolation -- it is never presented as real
    station-acceptance evidence.
    """
    run_dir = _copy_fixture(tmp_path / "run")
    _write_synthetic_install_progress(run_dir)
    _write_synthetic_engine_proof(run_dir)
    # <gate-a-audit-BL-09> summary.json now carries the completion verdict
    # itself, so the synthetic all-PASS directory has to author it too.
    summary_seed = json.loads((run_dir / "summary.json").read_text(encoding="utf-8-sig"))
    summary_seed["harness_completed"] = True
    summary_seed["top_level_error"] = None
    summary_seed.setdefault("step_seq", 64)
    (run_dir / "summary.json").write_text(json.dumps(summary_seed), encoding="utf-8")
    # last_completed_step mirrors what In-Sandbox-Report.ps1 actually writes
    # as its true final step (the `finally` block's own Save-Summary call),
    # not an intermediate step like "t5-soak-complete" -- steps 6/7
    # (install-progress-log-copied, event-log-checked) and the finally block
    # itself always run after T5 on a real completed harness run. Both
    # DONE.json and summary.json must agree on this value; `summary.json`
    # in the copied fixture already ends on a step name of its own, so this
    # helper does not touch it -- see test_verdict_document_shape and the
    # completion tests below for the cross-file consistency check itself.
    summary_path = run_dir / "summary.json"
    fixture_summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
    fixture_last_step = fixture_summary.get("last_completed_step")
    done = {
        "done_utc": "2026-08-19T09:29:32.000Z",
        "last_completed_step": fixture_last_step,
        "step_seq": 64,
        "run_end_utc": "2026-08-19T09:29:32.000Z",
        "installer_exit_code": 0,
        "harness_completed": True,
        "top_level_error": None,
        "watchdog_timeout": False,
        "station_up": True,
        "station_first_healthy_utc": "2026-08-19T09:05:12.000Z",
        "station_boot_seconds": 87.0,
    }
    (run_dir / "DONE.json").write_text(json.dumps(done), encoding="utf-8")
    return run_dir


# --------------------------------------------------------------------------
# Module file sanity
# --------------------------------------------------------------------------


def test_module_file_present() -> None:
    assert _MODULE_PATH.exists(), f"judge module missing at {_MODULE_PATH}"


def test_fixture_dir_present() -> None:
    assert _FIXTURE_DIR.is_dir(), f"PASS fixture missing at {_FIXTURE_DIR}"


def test_all_required_checks_are_registered() -> None:
    assert set(gav.CHECKS.keys()) == set(REQUIRED_CHECKS)


# --------------------------------------------------------------------------
# The real Aug-19 fixture, as-is
# --------------------------------------------------------------------------


def test_real_fixture_every_check_passes_except_the_pre_contract_ones() -> None:
    """Every check the historical fixture CAN satisfy still passes on it.

    The exceptions are enumerated (with reasons) in ``PRE_CONTRACT_CHECKS``
    rather than skipped silently, so a future regression that breaks one of
    the other checks on real evidence is still caught here.
    """
    result = gav.judge(_FIXTURE_DIR, source_sha="8579e66", run_id="reference-2026-08-19")
    for name in REQUIRED_CHECKS:
        if name in PRE_CONTRACT_CHECKS:
            continue
        assert result["checks"][name]["status"] == "PASS", (
            f"{name} unexpectedly FAILed on the real Aug-19 fixture: {result['checks'][name]['detail']}"
        )


def test_real_fixture_t4_engine_fails_on_its_own_timed_out_tsduck_proof() -> None:
    """<gate-a-audit-MA-27> The historical fixture IS the evidence.

    ``egress-verify-engine.json`` in the Aug-19 run reads ``timed_out: true,
    exit_code: null`` with no packet count, and ``T4_RESULT=PASS_PRODUCT_ENGINE``
    beside it. The old check read only the ``T4_RESULT=`` string and passed.
    A run whose TSDuck capture was killed at its deadline analysed nothing,
    whatever verdict string the harness wrote next to it.
    """
    result = gav.judge(_FIXTURE_DIR, source_sha="8579e66", run_id="reference-2026-08-19")
    assert result["checks"]["t4_engine"]["status"] == "FAIL"
    assert "timed_out" in result["checks"]["t4_engine"]["detail"]


def test_real_fixture_completion_check_fails_closed_on_missing_done_json() -> None:
    result = gav.judge(_FIXTURE_DIR, source_sha="8579e66", run_id="reference-2026-08-19")
    assert result["checks"]["completion"]["status"] == "FAIL"
    assert "DONE.json" in result["checks"]["completion"]["detail"]


def test_real_fixture_overall_verdict_is_fail() -> None:
    """Documents the real, current shape: FAIL overall, on completion alone.

    This is not a defect in the judge. See the module docstring's "Known
    harness quirk" section: the Aug-19 run's own DONE.json was never written
    because the sandbox VM was torn down before In-Sandbox-Report.ps1's
    `finally` block finished, so a fail-closed judge correctly refuses to
    call this run complete -- exactly the discipline Gate A exists to add.
    """
    result = gav.judge(_FIXTURE_DIR, source_sha="8579e66", run_id="reference-2026-08-19")
    assert result["verdict"] == "FAIL"
    failing = {name for name, c in result["checks"].items() if c["status"] == "FAIL"}
    assert failing == set(PRE_CONTRACT_CHECKS)


# --------------------------------------------------------------------------
# Synthetic fully-complete evidence: the all-PASS path
# --------------------------------------------------------------------------


def test_synthetic_complete_run_is_overall_pass(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    result = gav.judge(run_dir, source_sha="deadbeef", run_id="123")
    for name in REQUIRED_CHECKS:
        assert result["checks"][name]["status"] == "PASS", (
            f"{name} unexpectedly FAILed: {result['checks'][name]['detail']}"
        )
    assert result["verdict"] == "PASS"


def test_verdict_document_shape(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    result = gav.judge(run_dir, source_sha="deadbeef", run_id="123")
    assert result["source_sha"] == "deadbeef"
    assert result["run_id"] == "123"
    assert result["evidence_dir"] == str(run_dir)
    assert isinstance(result["judged_utc"], str) and result["judged_utc"]
    assert set(result["checks"].keys()) == set(REQUIRED_CHECKS)
    assert result["harness_error"] is None


# --------------------------------------------------------------------------
# Harness errors are a third verdict, never a product FAIL
#
# Added with the <gate-a-mapped-folder-stalls> fix. When
# Host-Launch-Sandbox-Test.ps1 sees the Windows Sandbox mapped output folder
# stop changing while the VM is alive, the guest-to-host evidence channel is
# broken and the run says nothing about the candidate. The judge must report
# that as HARNESS_ERROR (exit 2), never as a station-acceptance FAIL -- the
# whole point of Gate A is that a verdict means what it says.
# --------------------------------------------------------------------------


def test_harness_error_markers_registry_names_the_quiet_share_file() -> None:
    assert "HOST-QUIET-SHARE.txt" in gav.HARNESS_ERROR_MARKERS
    assert gav.HARNESS_ERROR_MARKERS["HOST-QUIET-SHARE.txt"].strip()


def test_detect_harness_error_returns_none_on_clean_evidence(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    assert gav.detect_harness_error(run_dir) is None


def test_quiet_share_marker_makes_the_verdict_harness_error_not_fail(tmp_path: Path) -> None:
    """The decisive assertion: an otherwise all-PASS run carrying the marker
    is HARNESS_ERROR, and specifically NOT "FAIL"."""
    run_dir = _synthetic_pass_dir(tmp_path)
    (run_dir / "HOST-QUIET-SHARE.txt").write_text(
        "host_quiet_share_utc=2026-08-25T00:00:00Z quiet_minutes=15.2 threshold_minutes=15 "
        "last_output_write_utc=2026-08-24T23:44:48Z vm_alive=True\n",
        encoding="utf-8",
    )
    result = gav.judge(run_dir, None, None)
    assert result["verdict"] == "HARNESS_ERROR"
    assert result["verdict"] != "FAIL"
    assert "HOST-QUIET-SHARE.txt" in result["harness_error"]


def test_quiet_share_marker_wins_over_a_genuine_product_failure(tmp_path: Path) -> None:
    """Even with a real product-check failure in the same directory, a broken
    evidence channel means no product conclusion is available -- a partially
    shipped run's T4 line may be absent or truncated for channel reasons, not
    candidate reasons."""
    run_dir = _synthetic_pass_dir(tmp_path)
    t35 = run_dir / "T3T5-RESULT.txt"
    t35.write_text(
        t35.read_text(encoding="utf-8-sig").replace(
            "T4_RESULT=PASS_PRODUCT_ENGINE", "T4_RESULT=NO_ARTIFACT"
        ),
        encoding="utf-8",
    )
    (run_dir / "HOST-QUIET-SHARE.txt").write_text("quiet\n", encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["t4_engine"]["status"] == "FAIL"
    assert result["verdict"] == "HARNESS_ERROR"


def test_quiet_share_marker_names_itself_in_the_completion_check(tmp_path: Path) -> None:
    """The completion check must blame the channel, not report the misleading
    downstream symptom (a missing DONE.json it could never have received)."""
    run_dir = _synthetic_pass_dir(tmp_path)
    (run_dir / "DONE.json").unlink()
    (run_dir / "HOST-QUIET-SHARE.txt").write_text("quiet\n", encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["completion"]["status"] == "FAIL"
    assert "HOST-QUIET-SHARE.txt" in result["checks"]["completion"]["detail"]


def test_quiet_share_cli_exit_code_is_2_not_1(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    (run_dir / "HOST-QUIET-SHARE.txt").write_text("quiet\n", encoding="utf-8")
    out_path = tmp_path / "gate-a-verdict.json"
    proc = subprocess.run(
        [sys.executable, str(_MODULE_PATH), str(run_dir), "--out", str(out_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written["verdict"] == "HARNESS_ERROR"
    assert "harness error" in proc.stderr


# --------------------------------------------------------------------------
# Fail-closed: missing / unparseable files
# --------------------------------------------------------------------------


def test_missing_summary_json_fails_install_closed(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    (run_dir / "summary.json").unlink()
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["install"]["status"] == "FAIL"
    assert "summary.json" in result["checks"]["install"]["detail"]
    assert result["verdict"] == "FAIL"


def test_malformed_summary_json_fails_closed(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    (run_dir / "summary.json").write_text("{not valid json", encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["install"]["status"] == "FAIL"
    assert "not valid JSON" in result["checks"]["install"]["detail"]


def test_missing_done_json_fails_completion_only(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    (run_dir / "DONE.json").unlink()
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["completion"]["status"] == "FAIL"
    non_completion_fails = [
        name
        for name in REQUIRED_CHECKS
        if name != "completion" and result["checks"][name]["status"] == "FAIL"
    ]
    assert non_completion_fails == []


# --------------------------------------------------------------------------
# Fail-closed: wrong values in otherwise-present, well-formed files
# --------------------------------------------------------------------------


def test_installer_exit_code_nonzero_fails_install(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    summary_path = run_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
    summary["installer_exit_code"] = 1603
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["install"]["status"] == "FAIL"
    assert "1603" in result["checks"]["install"]["detail"]


def test_runtime_non_200_fails_runtime(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    summary_path = run_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
    summary["runtime_checks"]["operator_console"]["status"] = 500
    summary["runtime_checks"]["operator_console"]["ok"] = False
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["runtime"]["status"] == "FAIL"
    assert "operator_console" in result["checks"]["runtime"]["detail"]


def test_t4_ffmpeg_fallback_is_a_named_fail(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    t35 = run_dir / "T3T5-RESULT.txt"
    text = t35.read_text(encoding="utf-8-sig")
    text = text.replace("T4_RESULT=PASS_PRODUCT_ENGINE", "T4_RESULT=PASS_FFMPEG_FALLBACK")
    t35.write_text(text, encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["t4_engine"]["status"] == "FAIL"
    assert "PASS_FFMPEG_FALLBACK" in result["checks"]["t4_engine"]["detail"]
    assert "GStreamer" in result["checks"]["t4_engine"]["detail"]
    assert result["verdict"] == "FAIL"


def test_t4_unrecognized_result_fails(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    t35 = run_dir / "T3T5-RESULT.txt"
    text = t35.read_text(encoding="utf-8-sig")
    text = text.replace("T4_RESULT=PASS_PRODUCT_ENGINE", "T4_RESULT=NO_ARTIFACT")
    t35.write_text(text, encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["t4_engine"]["status"] == "FAIL"
    assert "NO_ARTIFACT" in result["checks"]["t4_engine"]["detail"]


def test_t5_unhealthy_nonzero_fails(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    t35 = run_dir / "T3T5-RESULT.txt"
    text = t35.read_text(encoding="utf-8-sig")
    text = text.replace("T5_RESULT=PASS beats=2 unhealthy=0", "T5_RESULT=PASS beats=2 unhealthy=1")
    t35.write_text(text, encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["t5_soak"]["status"] == "FAIL"
    assert "unhealthy=1" in result["checks"]["t5_soak"]["detail"]


def test_t5_fail_result_fails(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    t35 = run_dir / "T3T5-RESULT.txt"
    text = t35.read_text(encoding="utf-8-sig")
    text = text.replace("T5_RESULT=PASS beats=2 unhealthy=0", "T5_RESULT=FAIL beats=2 unhealthy=2")
    t35.write_text(text, encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["t5_soak"]["status"] == "FAIL"


def test_captions_zero_cue_count_fails(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    artifact_path = run_dir / "T3-caption-artifact.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8-sig"))
    artifact["cue_count"] = 0
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["captions"]["status"] == "FAIL"
    assert "cue_count=0" in result["checks"]["captions"]["detail"]


def test_captions_no_pass_line_fails(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    loop_path = run_dir / "T3-LOOP.txt"
    text = loop_path.read_text(encoding="utf-8-sig").replace(
        "CAPTIONS=PASS", "CAPTIONS=FAIL_NO_ENQUEUE_ROUTE"
    )
    loop_path.write_text(text, encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["captions"]["status"] == "FAIL"


def test_t2_render_operator_fail_fails(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    t2_path = run_dir / "T2-RENDER-RESULT.txt"
    text = t2_path.read_text(encoding="utf-8-sig")
    text = text.replace(
        "T2_operator raw=698 dumped=5531 ratio=7.92 known_matched=No live meeting broadcast known_in_raw=False "
        "edge_ok=True timed_out=False error= result=PASS",
        "T2_operator raw=698 dumped=698 ratio=1.00 known_matched= known_in_raw=False "
        "edge_ok=True timed_out=False error= result=FAIL",
    )
    assert "result=FAIL" in text, "test setup did not replace the expected T2_operator line"
    t2_path.write_text(text, encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["t2_render"]["status"] == "FAIL"


# --------------------------------------------------------------------------
# <gate-a-audit-BL-09> The completion check's real assertions.
#
# The old cross-check compared summary.json.last_completed_step to
# DONE.json.last_completed_step -- two fields the harness's own `finally`
# block writes microseconds apart from the SAME $summary variable, so they
# were always equal and always 'finally-block'. That self-comparison sat in
# the one check whose job is to prove the run happened. These four tests
# assert on values a crashed or force-completed run genuinely cannot produce.
# --------------------------------------------------------------------------


def test_completion_fails_when_done_json_carries_a_top_level_error(tmp_path: Path) -> None:
    """The exact shape BL-09 describes: the 1500-line try threw, the catch
    swallowed it, and the run still shipped DONE.json. It must now say so."""
    run_dir = _synthetic_pass_dir(tmp_path)
    done_path = run_dir / "DONE.json"
    done = json.loads(done_path.read_text(encoding="utf-8"))
    done["top_level_error"] = "No *setup.exe found in mapped payload"
    done_path.write_text(json.dumps(done), encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["completion"]["status"] == "FAIL"
    assert "setup.exe" in result["checks"]["completion"]["detail"]
    assert result["verdict"] == "FAIL"


def test_completion_fails_when_summary_errors_carry_a_top_level_failure(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    summary_path = run_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
    summary["errors"] = ["top-level failure: No *setup.exe found in mapped payload"]
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["completion"]["status"] == "FAIL"
    assert "top-level failure" in result["checks"]["completion"]["detail"]


def test_completion_fails_when_summary_write_errors_log_is_non_empty(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    (run_dir / "summary-write-errors.log").write_text(
        "station diag capture (final) failed: access is denied\n", encoding="utf-8"
    )
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["completion"]["status"] == "FAIL"
    assert "summary-write-errors.log" in result["checks"]["completion"]["detail"]


def test_completion_fails_when_step_seq_is_below_the_floor(tmp_path: Path) -> None:
    """A run that barely advanced did not run the acceptance flow, whatever
    its last_completed_step string happens to say."""
    run_dir = _synthetic_pass_dir(tmp_path)
    done_path = run_dir / "DONE.json"
    done = json.loads(done_path.read_text(encoding="utf-8"))
    done["step_seq"] = 3
    done_path.write_text(json.dumps(done), encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["completion"]["status"] == "FAIL"
    assert "step_seq" in result["checks"]["completion"]["detail"]


def test_completion_fails_when_run_end_utc_is_absent(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    done_path = run_dir / "DONE.json"
    done = json.loads(done_path.read_text(encoding="utf-8"))
    done["run_end_utc"] = None
    done_path.write_text(json.dumps(done), encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["completion"]["status"] == "FAIL"
    assert "run_end_utc" in result["checks"]["completion"]["detail"]


def test_completion_no_longer_compares_two_copies_of_one_variable(tmp_path: Path) -> None:
    """The self-comparison is GONE, not merely relaxed.

    summary.json and DONE.json disagreeing about last_completed_step was the
    only thing the old contract could detect, and it could never happen: one
    `finally` block writes both from one variable. A run whose two step names
    differ (a shipper that carried DONE.json out on a later tick, say) is not
    evidence of anything, and must not decide the verdict.
    """
    run_dir = _synthetic_pass_dir(tmp_path)
    done_path = run_dir / "DONE.json"
    done = json.loads(done_path.read_text(encoding="utf-8"))
    done["last_completed_step"] = "a-different-step-name"
    done_path.write_text(json.dumps(done), encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["completion"]["status"] == "PASS"


# --------------------------------------------------------------------------
# <gate-a-audit-MA-25> The clean lane finally grades install-progress.log.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value", "needle"),
    [
        # The exact line today's evidence carries beside installer_exit_code=0.
        ("POSTINSTALL_OUTCOME", "COMPLETED WITH A D3 ROLLBACK", "POSTINSTALL_OUTCOME"),
        ("POSTINSTALL_OUTCOME", "FAILED", "POSTINSTALL_OUTCOME"),
        ("POSTINSTALL_OUTCOME", "MISSING", "POSTINSTALL_OUTCOME"),
        ("POSTINSTALL_ALERTS", "1", "POSTINSTALL_ALERTS"),
        ("POSTINSTALL_NONZERO_STEPS", "d4-activate-station=66", "POSTINSTALL_NONZERO_STEPS"),
        ("D4_ACTIVATE_EXIT", "66", "D4_ACTIVATE_EXIT"),
    ],
)
def test_install_progress_check_fails_on_each_bad_breadcrumb(
    tmp_path: Path, field: str, value: str, needle: str
) -> None:
    """A rolled-back or alerting install must FAIL even at installer exit 0.

    That combination is not hypothetical -- it is what a real Gate A run
    shipped: `postinstall: COMPLETED WITH A D3 ROLLBACK (... unchanged at
    1.0.0-beta.2 ...)` alongside `installer_exit_code=0`, with no check in
    any lane looking at it.
    """
    run_dir = _synthetic_pass_dir(tmp_path)
    path = run_dir / "INSTALL-PROGRESS-RESULT.txt"
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        key = line.split("=", 1)[0]
        lines.append(f"{field}={value}" if key == field else line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["install_progress"]["status"] == "FAIL"
    assert needle in result["checks"]["install_progress"]["detail"]
    assert result["verdict"] == "FAIL"


def test_install_progress_check_fails_closed_on_a_missing_file(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    (run_dir / "INSTALL-PROGRESS-RESULT.txt").unlink()
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["install_progress"]["status"] == "FAIL"


# --------------------------------------------------------------------------
# <gate-a-audit-MN-20> A soak that never sampled the station is not a PASS.
# --------------------------------------------------------------------------


def test_t5_soak_with_zero_beats_fails(tmp_path: Path) -> None:
    """`T5_RESULT=PASS beats=0 unhealthy=0` -- what `-SoakMinutes 0` produced,
    and what the old check accepted because it asserted only status=='PASS'
    and unhealthy==0, both vacuously true over an empty beat loop."""
    run_dir = _synthetic_pass_dir(tmp_path)
    t35 = run_dir / "T3T5-RESULT.txt"
    text = t35.read_text(encoding="utf-8-sig")
    import re as _re

    text = _re.sub(
        r"^T5_RESULT=\S+ beats=\d+ unhealthy=\d+\s*$",
        "T5_RESULT=PASS beats=0 unhealthy=0",
        text,
        flags=_re.MULTILINE,
    )
    assert "beats=0" in text, "test setup did not rewrite the T5_RESULT line"
    t35.write_text(text, encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["t5_soak"]["status"] == "FAIL"
    assert "beats=0" in result["checks"]["t5_soak"]["detail"]
    assert result["verdict"] == "FAIL"


# --------------------------------------------------------------------------
# <gate-a-engine-soak> T6, gated by SOAK_MINUTES.txt.
# --------------------------------------------------------------------------


def test_t6_engine_soak_is_a_noop_pass_when_soak_minutes_absent(tmp_path: Path) -> None:
    """The fixture's own SOAK_MINUTES.txt (or its absence) must both be a
    no-op PASS for t6_engine_soak -- exactly what a real Gate A CI run's
    clean-lane evidence looks like, since Host-Launch-Sandbox-Test.ps1 always
    writes the file but CI's own -SoakMinutes (10/20) never exceeds 20."""
    run_dir = _synthetic_pass_dir(tmp_path)
    soak_file = run_dir / "SOAK_MINUTES.txt"
    if soak_file.exists():
        assert int(soak_file.read_text(encoding="utf-8-sig").strip()) <= 20
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["t6_engine_soak"]["status"] == "PASS"
    assert result["verdict"] == "PASS"


@pytest.mark.parametrize("soak_minutes", [0, 1, 10, 20])
def test_t6_engine_soak_is_a_noop_pass_at_or_below_20_minutes(
    tmp_path: Path, soak_minutes: int
) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    (run_dir / "SOAK_MINUTES.txt").write_text(str(soak_minutes), encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["t6_engine_soak"]["status"] == "PASS"
    assert "not required" in result["checks"]["t6_engine_soak"]["detail"]
    assert result["verdict"] == "PASS"


def test_t6_engine_soak_requires_a_pass_line_above_20_minutes(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    (run_dir / "SOAK_MINUTES.txt").write_text("480", encoding="utf-8")
    t35 = run_dir / "T3T5-RESULT.txt"
    with t35.open("a", encoding="utf-8") as fh:
        fh.write("\nT6_RESULT=PASS beats=96 failed_beats=0\n")
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["t6_engine_soak"]["status"] == "PASS"
    assert result["verdict"] == "PASS"


@pytest.mark.parametrize(
    "t6_line",
    [
        "T6_RESULT=FAIL reason=1-failed-beat(s)-across-channels beats=96 failed_beats=1",
        "T6_RESULT=FAIL_EARLY reason=channel(s)-not-live beats=2",
        "T6_RESULT=SKIPPED(station-down)",
    ],
)
def test_t6_engine_soak_fails_the_verdict_above_20_minutes_unless_pass(
    tmp_path: Path, t6_line: str
) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    (run_dir / "SOAK_MINUTES.txt").write_text("480", encoding="utf-8")
    t35 = run_dir / "T3T5-RESULT.txt"
    with t35.open("a", encoding="utf-8") as fh:
        fh.write("\n" + t6_line + "\n")
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["t6_engine_soak"]["status"] == "FAIL"
    assert result["verdict"] == "FAIL"


def test_t6_engine_soak_fails_closed_when_line_is_missing_above_20_minutes(
    tmp_path: Path,
) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    (run_dir / "SOAK_MINUTES.txt").write_text("480", encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["t6_engine_soak"]["status"] == "FAIL"
    assert "T6_RESULT=" in result["checks"]["t6_engine_soak"]["detail"]
    assert result["verdict"] == "FAIL"


# --------------------------------------------------------------------------
# <gate-a-audit-MA-27> The TSDuck proof artifact, not just the verdict string.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("timed_out", True),
        ("exit_code", None),
        ("exit_code", 1),
        ("packets_total", 0),
        ("verdict", "fail-empty-report"),
        ("invalid_syncs", 3),
    ],
)
def test_t4_engine_fails_on_an_unsound_tsduck_proof(
    tmp_path: Path, field: str, value: object
) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    proof_path = run_dir / "egress-verify-engine.json"
    proof = json.loads(proof_path.read_text(encoding="utf-8-sig"))
    proof[field] = value
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["t4_engine"]["status"] == "FAIL", (
        f"{field}={value!r} should not survive the T4 check"
    )
    assert result["verdict"] == "FAIL"


def test_watchdog_timeout_file_fails_completion(tmp_path: Path) -> None:
    """A WATCHDOG-TIMEOUT.txt present must fail completion even with an
    otherwise-well-formed harness_completed=true DONE.json -- the watchdog's
    placeholder DONE.json is a bounded escape hatch for the host's poll
    loop, never a genuine completion signal."""
    run_dir = _synthetic_pass_dir(tmp_path)
    (run_dir / "WATCHDOG-TIMEOUT.txt").write_text(
        "watchdog_fired_utc=2026-08-21T00:00:00Z max_script_minutes=100 reason=test\n",
        encoding="utf-8",
    )
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["completion"]["status"] == "FAIL"
    assert "WATCHDOG-TIMEOUT.txt" in result["checks"]["completion"]["detail"]
    assert result["verdict"] == "FAIL"


def test_watchdog_timeout_field_true_fails_completion(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    done_path = run_dir / "DONE.json"
    done = json.loads(done_path.read_text(encoding="utf-8"))
    done["watchdog_timeout"] = True
    done_path.write_text(json.dumps(done), encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["completion"]["status"] == "FAIL"
    assert "watchdog_timeout" in result["checks"]["completion"]["detail"]


def test_stall_timeout_file_fails_completion(tmp_path: Path) -> None:
    """A STALL-TIMEOUT.txt present must fail completion even with an
    otherwise-well-formed harness_completed=true DONE.json -- the
    staleness watchdog's placeholder DONE.json (fired because
    last_completed_step stopped advancing for 8 minutes past the runtime
    verdict) is a bounded escape hatch, never a genuine completion."""
    run_dir = _synthetic_pass_dir(tmp_path)
    (run_dir / "STALL-TIMEOUT.txt").write_text(
        "stall_detected_utc=2026-08-21T00:00:00Z stuck_step=station-diag-captured-after-t3t5 "
        "stuck_since_utc=2026-08-20T23:52:00Z stalled_seconds=480 threshold_seconds=480\n",
        encoding="utf-8",
    )
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["completion"]["status"] == "FAIL"
    assert "STALL-TIMEOUT.txt" in result["checks"]["completion"]["detail"]
    assert result["verdict"] == "FAIL"


def test_stall_timeout_field_true_fails_completion(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    done_path = run_dir / "DONE.json"
    done = json.loads(done_path.read_text(encoding="utf-8"))
    done["stall_timeout"] = True
    done_path.write_text(json.dumps(done), encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["completion"]["status"] == "FAIL"
    assert "stall_timeout" in result["checks"]["completion"]["detail"]


def test_harness_completed_false_fails_completion(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    done_path = run_dir / "DONE.json"
    done = json.loads(done_path.read_text(encoding="utf-8"))
    done["harness_completed"] = False
    done_path.write_text(json.dumps(done), encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["completion"]["status"] == "FAIL"
    assert "harness_completed" in result["checks"]["completion"]["detail"]


def test_verdict_carries_informational_station_boot_fields(tmp_path: Path) -> None:
    """station_up / station_boot_seconds / station_first_healthy_utc are
    informational-only fields surfaced from summary.json -- present in the
    verdict document but never part of the checks dict / pass-fail gate."""
    run_dir = _synthetic_pass_dir(tmp_path)
    summary_path = run_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
    summary["station_up"] = True
    summary["station_boot_seconds"] = 123.4
    summary["station_first_healthy_utc"] = "2026-08-21T00:01:03.000Z"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["station_up"] is True
    assert result["station_boot_seconds"] == 123.4
    assert result["station_first_healthy_utc"] == "2026-08-21T00:01:03.000Z"
    assert "station_up" not in result["checks"]
    assert result["verdict"] == "PASS"


def test_verdict_station_fields_null_when_summary_missing(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    (run_dir / "summary.json").unlink()
    result = gav.judge(run_dir, None, None)
    assert result["station_up"] is None
    assert result["station_boot_seconds"] is None
    assert result["station_first_healthy_utc"] is None


def test_t3_loop_missing_result_line_fails(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    t35 = run_dir / "T3T5-RESULT.txt"
    text = t35.read_text(encoding="utf-8-sig").replace("T3_RESULT=PASS", "T3_RESULT=FAIL")
    t35.write_text(text, encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["t3_loop"]["status"] == "FAIL"


def test_activation_station_set_not_found_fails(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    act_path = run_dir / "ACTIVATION-RESULT.txt"
    text = act_path.read_text(encoding="utf-8-sig").replace(
        "station_set_json_found_after_install=1", "station_set_json_found_after_install=0"
    )
    act_path.write_text(text, encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["activation"]["status"] == "FAIL"


# --------------------------------------------------------------------------
# CLI entry point
# --------------------------------------------------------------------------


def test_cli_exit_code_2_when_output_dir_missing(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    proc = subprocess.run(
        [sys.executable, str(_MODULE_PATH), str(missing)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "does not exist" in proc.stderr


def test_cli_exit_code_1_on_the_real_fixture(tmp_path: Path) -> None:
    """The real fixture is a genuine FAIL (missing DONE.json) -- see module docstring."""
    run_dir = _copy_fixture(tmp_path / "run")
    out_path = tmp_path / "gate-a-verdict.json"
    proc = subprocess.run(
        [sys.executable, str(_MODULE_PATH), str(run_dir), "--out", str(out_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written["verdict"] == "FAIL"


def test_cli_exit_code_0_on_synthetic_complete_run(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    out_path = tmp_path / "gate-a-verdict.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(_MODULE_PATH),
            str(run_dir),
            "--source-sha",
            "deadbeef",
            "--run-id",
            "123",
            "--out",
            str(out_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written["verdict"] == "PASS"
    assert written["source_sha"] == "deadbeef"
    assert written["run_id"] == "123"


@pytest.mark.parametrize("check_name", REQUIRED_CHECKS)
def test_every_check_detail_is_a_nonempty_string(tmp_path: Path, check_name: str) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    result = gav.judge(run_dir, None, None)
    detail = result["checks"][check_name]["detail"]
    assert isinstance(detail, str) and detail.strip()


# --------------------------------------------------------------------------
# Shared-sandbox guard: SANDBOX-BUSY.txt short-circuits to a BUSY verdict,
# never a product FAIL. See Host-Launch-Sandbox-Test.ps1's busy-guard and
# scripts/gate_a_verdict.py's module docstring ("Shared-sandbox guard").
# --------------------------------------------------------------------------


def test_sandbox_busy_txt_alone_yields_busy_verdict(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "SANDBOX-BUSY.txt").write_text(
        "2026-08-24T12:00:00.0000000Z still busy after 90m wait -- giving up. "
        "processes=[WindowsSandboxClient] pids=[4242]\n",
        encoding="utf-8",
    )
    result = gav.judge(run_dir, source_sha="deadbeef", run_id="123")
    assert result["verdict"] == "BUSY"
    assert result["reason"] == "sandbox-busy-other-user"
    assert result["checks"] == {}
    assert "4242" in result["detail"]
    assert result["source_sha"] == "deadbeef"
    assert result["run_id"] == "123"


def test_sandbox_busy_overrides_even_with_other_evidence_present(tmp_path: Path) -> None:
    """A fully-complete evidence dir that ALSO carries SANDBOX-BUSY.txt (should
    never happen from a real harness run, but the judge must still fail
    closed toward BUSY rather than silently ignoring the marker and grading
    the other files) still comes out BUSY, not PASS or FAIL."""
    run_dir = _synthetic_pass_dir(tmp_path)
    (run_dir / "SANDBOX-BUSY.txt").write_text("busy\n", encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["verdict"] == "BUSY"
    assert result["checks"] == {}


def test_sandbox_busy_txt_empty_gets_a_placeholder_detail(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "SANDBOX-BUSY.txt").write_text("", encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["verdict"] == "BUSY"
    assert isinstance(result["detail"], str) and result["detail"].strip()


def test_absent_sandbox_busy_txt_does_not_affect_normal_judging(tmp_path: Path) -> None:
    """Sanity check that the new short-circuit is additive: a normal
    synthetic-complete run with no SANDBOX-BUSY.txt is unaffected."""
    run_dir = _synthetic_pass_dir(tmp_path)
    assert not (run_dir / "SANDBOX-BUSY.txt").exists()
    result = gav.judge(run_dir, None, None)
    assert result["verdict"] == "PASS"
    assert "reason" not in result


def test_cli_exit_code_2_on_sandbox_busy(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "SANDBOX-BUSY.txt").write_text("busy\n", encoding="utf-8")
    out_path = tmp_path / "gate-a-verdict.json"
    proc = subprocess.run(
        [sys.executable, str(_MODULE_PATH), str(run_dir), "--out", str(out_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written["verdict"] == "BUSY"
    assert written["reason"] == "sandbox-busy-other-user"


# --------------------------------------------------------------------------
# Dirty-box remnant lane <gate-a-dirty-lane>
# --------------------------------------------------------------------------

DIRTY_CHECKS = ("dirty_prep", "dirty_survival", "dirty_orphaned_tier")


def _write_dirty_evidence(
    run_dir: Path,
    *,
    prep_overrides: dict[str, str] | None = None,
    seeded: str = "1",
    warning: str = "1",
) -> None:
    prep = {
        "PHASE1_INSTALL_EXIT": "0",
        "UNINSTALL_EXIT": "0",
        "PGDATA_PRESERVED_AFTER_UNINSTALL": "1",
        "UPLOADS_PRESERVED_AFTER_UNINSTALL": "1",
        "INSTALL_TREE_REMOVED_AFTER_UNINSTALL": "1",
    }
    prep.update(prep_overrides or {})
    (run_dir / "DIRTY-PREP-RESULT.txt").write_text(
        "\n".join(f"{k}={v}" for k, v in prep.items()) + "\n", encoding="utf-8"
    )
    lines = [
        "DIRTY_PGDATA_PRESERVED=1 detail=same cluster",
        "DIRTY_UPLOADS_PRESERVED=1",
        f"DIRTY_ORPHAN_SEEDED={seeded}",
        f"DIRTY_ORPHAN_WARNING={warning}",
    ]
    (run_dir / "DIRTY-RESULT.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_upgrade_evidence(
    run_dir: Path,
    *,
    previous_installer_sha256: str = "a" * 64,
    current_installer_sha256: str = "b" * 64,
    previous_product_version: str = "1.0.0-rc18",
    current_product_version: str = "1.0.0-beta.2",
    current_install_exit: str = "0",
    d3_route: str = "UPGRADE",
    d3_engine_exit: str = "0",
    post_upgrade_db_revision: str = "0087_head",
    expected_head: str = "0087_head",
    post_upgrade_matches: str | None = None,
    # <gate-a-audit-BL-10> The two INDEPENDENT operands. Note they default to
    # values this helper does NOT derive from post_upgrade_db_revision /
    # expected_head: the whole finding was that the fixture computed exactly
    # what the judge was supposed to check.
    post_upgrade_db_revision_psql: str = "0087_head",
    kit_expected_head: str = "0087_head",
    d4_activate_exit: str = "0",
    postinstall_outcome: str = "SUCCESS",
) -> None:
    prep = [
        "UPGRADE_MODE=1",
        "PHASE1_INSTALL_EXIT=0",
        "UPGRADE_OVER_LIVE_REQUESTED=1",
        f"PREVIOUS_INSTALLER_SHA256={previous_installer_sha256}",
        f"CURRENT_INSTALLER_SHA256={current_installer_sha256}",
        f"PREVIOUS_PRODUCT_VERSION={previous_product_version}",
        f"CURRENT_PRODUCT_VERSION={current_product_version}",
    ]
    (run_dir / "DIRTY-PREP-RESULT.txt").write_text("\n".join(prep) + "\n", encoding="utf-8")
    if post_upgrade_matches is None:
        post_upgrade_matches = "1" if post_upgrade_db_revision == expected_head else "0"
    result = [
        "UPGRADE_MODE=1",
        f"UPGRADE_CURRENT_INSTALL_EXIT={current_install_exit}",
        f"D3_ROUTE={d3_route}",
        f"D3_ENGINE_EXIT={d3_engine_exit}",
        f"D4_ACTIVATE_EXIT={d4_activate_exit}",
        f"POSTINSTALL_OUTCOME={postinstall_outcome}",
        f"POST_UPGRADE_DB_REVISION={post_upgrade_db_revision}",
        f"EXPECTED_HEAD={expected_head}",
        f"POST_UPGRADE_DB_REVISION_MATCHES_HEAD={post_upgrade_matches}",
        f"POST_UPGRADE_DB_REVISION_PSQL={post_upgrade_db_revision_psql}",
        f"KIT_EXPECTED_HEAD={kit_expected_head}",
        "DIRTY_PGDATA_PRESERVED=1 detail=same cluster",
        "DIRTY_UPLOADS_PRESERVED=1",
        "DIRTY_ORPHAN_SEEDED=0",
        "DIRTY_ORPHAN_WARNING=NA",
    ]
    (run_dir / "DIRTY-RESULT.txt").write_text("\n".join(result) + "\n", encoding="utf-8")


def test_clean_lane_judge_is_unchanged_by_default(tmp_path: Path) -> None:
    """No --lane / lane='clean' produces the pre-dirty-lane document: no lane
    field, no dirty checks -- even when dirty evidence files are present."""
    run_dir = _synthetic_pass_dir(tmp_path)
    _write_dirty_evidence(run_dir)
    result = gav.judge(run_dir, source_sha="deadbeef", run_id="123")
    assert "lane" not in result
    assert set(result["checks"].keys()) == set(REQUIRED_CHECKS)
    assert result["verdict"] == "PASS"


def test_dirty_lane_all_pass(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    _write_dirty_evidence(run_dir)
    result = gav.judge(run_dir, source_sha="deadbeef", run_id="123", lane="dirty")
    assert result["lane"] == "dirty"
    assert set(result["checks"].keys()) == set(REQUIRED_CHECKS) | set(DIRTY_CHECKS)
    for name in DIRTY_CHECKS:
        assert result["checks"][name]["status"] == "PASS", result["checks"][name]["detail"]
    assert result["verdict"] == "PASS"


def test_cross_version_upgrade_lane_passes_only_with_distinct_installer_identities(
    tmp_path: Path,
) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    _write_upgrade_evidence(run_dir)
    result = gav.judge(run_dir, source_sha="b" * 40, run_id="123", lane="dirty")

    assert result["checks"]["dirty_prep"]["status"] == "PASS"
    assert result["checks"]["dirty_survival"]["status"] == "PASS"
    assert result["checks"]["dirty_orphaned_tier"]["status"] == "SKIP"
    assert "cross-version upgrade" in result["checks"]["dirty_prep"]["detail"]
    assert result["verdict"] == "PASS"


def test_cross_version_upgrade_lane_rejects_same_installer_as_not_cross_version(
    tmp_path: Path,
) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    same = "a" * 64
    _write_upgrade_evidence(
        run_dir,
        previous_installer_sha256=same,
        current_installer_sha256=same,
    )
    result = gav.judge(run_dir, source_sha=None, run_id=None, lane="dirty")

    assert result["checks"]["dirty_prep"]["status"] == "FAIL"
    assert "identical" in result["checks"]["dirty_prep"]["detail"]
    assert result["verdict"] == "FAIL"


def test_cross_version_upgrade_lane_rejects_same_product_version_as_no_op(
    tmp_path: Path,
) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    _write_upgrade_evidence(
        run_dir,
        previous_product_version="1.0.0-beta.1",
        current_product_version="1.0.0-beta.1",
    )
    result = gav.judge(run_dir, source_sha=None, run_id=None, lane="dirty")

    assert result["checks"]["dirty_prep"]["status"] == "FAIL"
    assert "SAME_VERSION_NO_OP" in result["checks"]["dirty_prep"]["detail"]
    assert "identical" in result["checks"]["dirty_prep"]["detail"]
    assert result["verdict"] == "FAIL"


def test_cross_version_upgrade_lane_requires_current_install_success(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    _write_upgrade_evidence(run_dir, current_install_exit="120")
    result = gav.judge(run_dir, source_sha=None, run_id=None, lane="dirty")

    assert result["checks"]["dirty_survival"]["status"] == "FAIL"
    assert "UPGRADE_CURRENT_INSTALL_EXIT=120" in result["checks"]["dirty_survival"]["detail"]
    assert result["verdict"] == "FAIL"


def test_cross_version_upgrade_lane_requires_d3_upgrade_route_and_engine_success(
    tmp_path: Path,
) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    _write_upgrade_evidence(run_dir, d3_route="FRESH_INSTALL", d3_engine_exit="11")
    result = gav.judge(run_dir, source_sha=None, run_id=None, lane="dirty")

    assert result["checks"]["dirty_survival"]["status"] == "FAIL"
    assert "D3_ROUTE=FRESH_INSTALL" in result["checks"]["dirty_survival"]["detail"]
    assert result["verdict"] == "FAIL"

    _write_upgrade_evidence(run_dir, d3_route="UPGRADE", d3_engine_exit="10")
    result = gav.judge(run_dir, source_sha=None, run_id=None, lane="dirty")

    assert result["checks"]["dirty_survival"]["status"] == "FAIL"
    assert "D3_ENGINE_EXIT=10" in result["checks"]["dirty_survival"]["detail"]
    assert result["verdict"] == "FAIL"


def test_cross_version_upgrade_lane_requires_post_upgrade_db_revision_to_match_head(
    tmp_path: Path,
) -> None:
    """Gate A run 33681670855 regression test. D3_ENGINE_EXIT=0 and healthy
    station-up evidence are NOT proof the live database is at the running
    code's migration head -- that exact combination shipped on kit 7971815
    (beta.2 -> beta.3) with the station serving 500s over an unmigrated
    database. The judge must fail closed on a revision mismatch even when
    every other upgrade signal reports success."""
    run_dir = _synthetic_pass_dir(tmp_path)
    _write_upgrade_evidence(
        run_dir,
        post_upgrade_db_revision="0082_old_head",
        expected_head="0087_new_head",
        post_upgrade_db_revision_psql="0082_old_head",
        kit_expected_head="0087_new_head",
    )
    result = gav.judge(run_dir, source_sha=None, run_id=None, lane="dirty")

    assert result["checks"]["dirty_survival"]["status"] == "FAIL"
    detail = result["checks"]["dirty_survival"]["detail"]
    assert "0082_old_head" in detail
    assert "0087_new_head" in detail
    assert result["verdict"] == "FAIL"


# --------------------------------------------------------------------------
# <gate-a-audit-BL-10> The audit's central finding, and its proof.
#
# PR #143's guard was `$healthRes.ok -and $rev -ne '<unavailable>' -and ($rev
# -eq $expectedHead)`. $healthRes.ok requires body_schema=='current';
# civiccast/app.py sources both revisions from ONE SchemaStatus; and
# schema_check.evaluate_schema_currency returns state=="current" IF AND ONLY
# IF db_revision == expected_head. So MATCHES_HEAD was 1 whenever ok was 1 --
# it could not fail. And this judge read the two revisions only to build an
# error message, never re-deriving the match from them, so a harness writing
# MATCHES_HEAD=1 beside mismatched revisions passed.
#
# Every test below writes evidence the OLD judge accepted and asserts FAIL.
# The fixture no longer computes what the judge is meant to check: the two
# independent operands are separate parameters with their own defaults.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("lane", ["dirty", "download-only"])
def test_matches_head_flag_of_1_cannot_rescue_mismatched_independent_revisions(
    tmp_path: Path, lane: str
) -> None:
    """MATCHES_HEAD=1 with an out-of-date database is a FAIL, not a PASS.

    This is the exact evidence shape the old judge accepted: the harness
    self-reports a match (as it always did, by construction), while the
    database's own alembic_version row and the candidate's build-time head
    disagree. The judge re-derives the answer instead of reading the label.
    """
    run_dir = _synthetic_pass_dir(tmp_path)
    writer = _write_upgrade_evidence if lane == "dirty" else _write_download_only_evidence
    writer(
        run_dir,
        post_upgrade_matches="1",
        post_upgrade_db_revision="0087_new_head",
        expected_head="0087_new_head",
        post_upgrade_db_revision_psql="0082_old_head",
        kit_expected_head="0087_new_head",
    )
    result = gav.judge(run_dir, source_sha=None, run_id=None, lane=lane)
    check = "dirty_survival" if lane == "dirty" else "download_only_no_station_dir"
    assert result["checks"][check]["status"] == "FAIL", result["checks"][check]["detail"]
    detail = result["checks"][check]["detail"]
    assert "0082_old_head" in detail and "0087_new_head" in detail
    assert result["verdict"] == "FAIL"


@pytest.mark.parametrize("lane", ["dirty", "download-only"])
def test_missing_kit_expected_head_fails_rather_than_falling_back_to_the_station(
    tmp_path: Path, lane: str
) -> None:
    """Without a build-time head there is no independent operand at all.

    The only other expected head available is the one the station under test
    computed about itself -- the self-comparison this check exists to end --
    so its absence is a FAIL, never an assumed pass.
    """
    run_dir = _synthetic_pass_dir(tmp_path)
    writer = _write_upgrade_evidence if lane == "dirty" else _write_download_only_evidence
    writer(run_dir, kit_expected_head="<not-provided>")
    result = gav.judge(run_dir, source_sha=None, run_id=None, lane=lane)
    check = "dirty_survival" if lane == "dirty" else "download_only_no_station_dir"
    assert result["checks"][check]["status"] == "FAIL"
    assert "KIT_EXPECTED_HEAD" in result["checks"][check]["detail"]


@pytest.mark.parametrize("lane", ["dirty", "download-only"])
def test_unreadable_psql_revision_fails_rather_than_deferring_to_health(
    tmp_path: Path, lane: str
) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    writer = _write_upgrade_evidence if lane == "dirty" else _write_download_only_evidence
    writer(run_dir, post_upgrade_db_revision_psql="<no-psql>")
    result = gav.judge(run_dir, source_sha=None, run_id=None, lane=lane)
    check = "dirty_survival" if lane == "dirty" else "download_only_no_station_dir"
    assert result["checks"][check]["status"] == "FAIL"
    assert "POST_UPGRADE_DB_REVISION_PSQL" in result["checks"][check]["detail"]


@pytest.mark.parametrize("lane", ["dirty", "download-only"])
def test_health_revision_disagreeing_with_the_database_is_a_fail(tmp_path: Path, lane: str) -> None:
    """<gate-a-audit-MA-13> /health's schema verdict is a boot-time snapshot.

    When the station's self-report and its own database disagree, neither
    supports a verdict -- most often the cached snapshot is simply stale.
    """
    run_dir = _synthetic_pass_dir(tmp_path)
    writer = _write_upgrade_evidence if lane == "dirty" else _write_download_only_evidence
    writer(
        run_dir,
        post_upgrade_db_revision="0086_stale_snapshot",
        expected_head="0086_stale_snapshot",
        post_upgrade_db_revision_psql="0087_head",
        kit_expected_head="0087_head",
    )
    result = gav.judge(run_dir, source_sha=None, run_id=None, lane=lane)
    check = "dirty_survival" if lane == "dirty" else "download_only_no_station_dir"
    assert result["checks"][check]["status"] == "FAIL"
    assert "disagrees with its own" in result["checks"][check]["detail"]


@pytest.mark.parametrize("lane", ["dirty", "download-only"])
def test_upgrade_lanes_fail_on_a_nonzero_d4_activation_with_d3_green(
    tmp_path: Path, lane: str
) -> None:
    """<gate-a-audit-MA-24> D3's exit code is not D4's.

    gate-a-download-only-33623737236/install-progress.log:346-353 recorded
    `route=UPGRADE engine_exit=0`, then `step d4-activate-station: returned
    66`, then `postinstall: FAILED` -- and the check that claimed to prove
    D4 activated was reading D3's number.
    """
    run_dir = _synthetic_pass_dir(tmp_path)
    writer = _write_upgrade_evidence if lane == "dirty" else _write_download_only_evidence
    writer(run_dir, d3_engine_exit="0", d4_activate_exit="66", postinstall_outcome="FAILED")
    result = gav.judge(run_dir, source_sha=None, run_id=None, lane=lane)
    check = "dirty_survival" if lane == "dirty" else "download_only_no_station_dir"
    assert result["checks"][check]["status"] == "FAIL"
    assert "D4_ACTIVATE_EXIT=66" in result["checks"][check]["detail"]


def test_download_only_lane_fails_on_a_stale_phase1_d3_route(tmp_path: Path) -> None:
    """<gate-a-audit-MA-23> The download-only check gated only on
    D3_ENGINE_EXIT=0, so a phase-2 install that never reached D3 -- leaving
    phase 1's `route=FRESH_INSTALL engine_exit=11`, or nothing at all --
    could pass. Both shapes must FAIL."""
    run_dir = _synthetic_pass_dir(tmp_path)
    _write_download_only_evidence(run_dir, d3_route="FRESH_INSTALL")
    result = gav.judge(run_dir, source_sha=None, run_id=None, lane="download-only")
    assert result["checks"]["download_only_no_station_dir"]["status"] == "FAIL"
    assert "D3_ROUTE=FRESH_INSTALL" in result["checks"]["download_only_no_station_dir"]["detail"]

    _write_download_only_evidence(run_dir, d3_route="MISSING")
    result = gav.judge(run_dir, source_sha=None, run_id=None, lane="download-only")
    assert result["checks"]["download_only_no_station_dir"]["status"] == "FAIL"
    assert "D3_ROUTE=MISSING" in result["checks"]["download_only_no_station_dir"]["detail"]


def test_dirty_lane_missing_evidence_fails_closed(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    result = gav.judge(run_dir, source_sha="deadbeef", run_id="123", lane="dirty")
    assert result["checks"]["dirty_prep"]["status"] == "FAIL"
    assert result["checks"]["dirty_survival"]["status"] == "FAIL"
    assert result["checks"]["dirty_orphaned_tier"]["status"] == "FAIL"
    assert result["verdict"] == "FAIL"


@pytest.mark.parametrize(
    "key",
    [
        "PHASE1_INSTALL_EXIT",
        "UNINSTALL_EXIT",
        "PGDATA_PRESERVED_AFTER_UNINSTALL",
        "UPLOADS_PRESERVED_AFTER_UNINSTALL",
        "INSTALL_TREE_REMOVED_AFTER_UNINSTALL",
    ],
)
def test_dirty_prep_fails_on_each_broken_expectation(tmp_path: Path, key: str) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    _write_dirty_evidence(run_dir, prep_overrides={key: "7"})
    result = gav.judge(run_dir, source_sha=None, run_id=None, lane="dirty")
    assert result["checks"]["dirty_prep"]["status"] == "FAIL"
    assert key in result["checks"]["dirty_prep"]["detail"]
    assert result["verdict"] == "FAIL"


def test_dirty_orphan_seeded_without_warning_fails(tmp_path: Path) -> None:
    """The seeded orphaned tier MUST produce PR #80's fallback WARNING in the
    supervisor log -- silence means the remnant was never detected."""
    run_dir = _synthetic_pass_dir(tmp_path)
    _write_dirty_evidence(run_dir, seeded="1", warning="0")
    result = gav.judge(run_dir, source_sha=None, run_id=None, lane="dirty")
    assert result["checks"]["dirty_orphaned_tier"]["status"] == "FAIL"
    assert result["verdict"] == "FAIL"


def test_dirty_orphan_not_seeded_is_a_loud_skip_not_a_fail(tmp_path: Path) -> None:
    """No hash-valid model staged on the runner -> the orphaned-tier shape was
    not covered. That is a SKIP that keeps the lane green (the OTHER remnant
    shapes still passed) but must say NOT covered, never quietly pass."""
    run_dir = _synthetic_pass_dir(tmp_path)
    _write_dirty_evidence(run_dir, seeded="0", warning="NA")
    result = gav.judge(run_dir, source_sha=None, run_id=None, lane="dirty")
    check = result["checks"]["dirty_orphaned_tier"]
    assert check["status"] == "SKIP"
    assert "NOT covered" in check["detail"]
    assert result["verdict"] == "PASS"


def test_dirty_lane_cli_lane_flag(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    _write_dirty_evidence(run_dir)
    proc = subprocess.run(
        [sys.executable, str(_MODULE_PATH), str(run_dir), "--lane", "dirty"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    written = json.loads((run_dir / "gate-a-verdict.json").read_text(encoding="utf-8"))
    assert written["lane"] == "dirty"
    assert written["verdict"] == "PASS"


def test_dirty_busy_short_circuit_still_carries_the_lane(tmp_path: Path) -> None:
    run_dir = tmp_path / "busy"
    run_dir.mkdir()
    (run_dir / "SANDBOX-BUSY.txt").write_text("busy", encoding="utf-8")
    result = gav.judge(run_dir, source_sha=None, run_id=None, lane="dirty")
    assert result["verdict"] == "BUSY"
    assert result["lane"] == "dirty"


# --------------------------------------------------------------------------
# Download-only lane <gate-a-download-only-lane>
# --------------------------------------------------------------------------

DOWNLOAD_ONLY_CHECKS = ("dirty_prep", "dirty_survival", "download_only_no_station_dir")


def _write_download_only_result(
    run_dir: Path,
    *,
    station_dir_present: str = "0",
    phase2_install_exit: str = "0",
    d3_route: str = "UPGRADE",
    d3_engine_exit: str = "0",
    station_set_product_version: str = "1.0.0-beta.2",
    current_product_version: str = "1.0.0-beta.2",
    post_upgrade_db_revision: str = "0087_head",
    expected_head: str = "0087_head",
    post_upgrade_matches: str | None = None,
    # <gate-a-audit-BL-10/MA-24> Independent operands and D4's own outcome;
    # see _write_upgrade_evidence for why these are separate parameters.
    post_upgrade_db_revision_psql: str = "0087_head",
    kit_expected_head: str = "0087_head",
    d4_activate_exit: str = "0",
    postinstall_outcome: str = "SUCCESS",
) -> None:
    if post_upgrade_matches is None:
        post_upgrade_matches = "1" if post_upgrade_db_revision == expected_head else "0"
    lines = [
        "PAYLOAD_DIR=C:\\CivicCastPayload",
        f"STATION_DIR_PRESENT={station_dir_present}",
        f"PHASE2_INSTALL_EXIT={phase2_install_exit}",
        f"D3_ROUTE={d3_route}",
        f"D3_ENGINE_EXIT={d3_engine_exit}",
        f"D4_ACTIVATE_EXIT={d4_activate_exit}",
        f"POSTINSTALL_OUTCOME={postinstall_outcome}",
        f"POST_UPGRADE_DB_REVISION={post_upgrade_db_revision}",
        f"EXPECTED_HEAD={expected_head}",
        f"POST_UPGRADE_DB_REVISION_MATCHES_HEAD={post_upgrade_matches}",
        f"POST_UPGRADE_DB_REVISION_PSQL={post_upgrade_db_revision_psql}",
        f"KIT_EXPECTED_HEAD={kit_expected_head}",
        f"STATION_SET_PRODUCT_VERSION={station_set_product_version}",
        f"CURRENT_PRODUCT_VERSION={current_product_version}",
    ]
    (run_dir / "DOWNLOAD-ONLY-RESULT.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_download_only_evidence(run_dir: Path, **overrides: str) -> None:
    """Write BOTH files the download-only lane grades, from one set of values.

    The lane runs ``dirty_prep`` and ``dirty_survival`` over the shared
    cross-version upgrade evidence PLUS ``download_only_no_station_dir`` over
    its own file, so a test that varies one field has to vary it in both
    places or it is only half testing the lane. Keys the upgrade writer does
    not take are passed to the download-only writer alone.
    """
    upgrade_keys = {
        "post_upgrade_db_revision",
        "expected_head",
        "post_upgrade_matches",
        "post_upgrade_db_revision_psql",
        "kit_expected_head",
        "d3_route",
        "d3_engine_exit",
        "d4_activate_exit",
        "postinstall_outcome",
    }
    _write_upgrade_evidence(run_dir, **{k: v for k, v in overrides.items() if k in upgrade_keys})
    _write_download_only_result(run_dir, **overrides)


def test_download_only_lane_all_pass(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    _write_upgrade_evidence(run_dir)
    _write_download_only_result(run_dir)
    result = gav.judge(run_dir, source_sha="b" * 40, run_id="123", lane="download-only")

    assert result["lane"] == "download-only"
    assert set(result["checks"].keys()) == set(REQUIRED_CHECKS) | set(DOWNLOAD_ONLY_CHECKS)
    assert "dirty_orphaned_tier" not in result["checks"], (
        "download-only lane must never run the dirty lane's own orphaned-tier remnant check"
    )
    for name in DOWNLOAD_ONLY_CHECKS:
        assert result["checks"][name]["status"] == "PASS", result["checks"][name]["detail"]
    assert result["verdict"] == "PASS"


def test_download_only_lane_requires_post_upgrade_db_revision_to_match_head(
    tmp_path: Path,
) -> None:
    """Same Gate A run 33681670855 regression, download-only lane."""
    run_dir = _synthetic_pass_dir(tmp_path)
    _write_upgrade_evidence(
        run_dir,
        post_upgrade_db_revision="0082_old_head",
        expected_head="0087_new_head",
    )
    _write_download_only_result(
        run_dir,
        post_upgrade_db_revision="0082_old_head",
        expected_head="0087_new_head",
    )
    result = gav.judge(run_dir, source_sha="b" * 40, run_id="123", lane="download-only")

    # dirty_survival is checked first and fails on the same shared evidence;
    # download_only_no_station_dir carries the same guard independently since
    # its own DOWNLOAD-ONLY-RESULT.txt is the file it actually reads.
    assert result["checks"]["dirty_survival"]["status"] == "FAIL"
    assert result["checks"]["download_only_no_station_dir"]["status"] == "FAIL"
    assert (
        "POST_UPGRADE_DB_REVISION_MATCHES_HEAD"
        in result["checks"]["download_only_no_station_dir"]["detail"]
    )
    assert result["verdict"] == "FAIL"


def test_download_only_lane_missing_evidence_fails_closed(tmp_path: Path) -> None:
    """No DOWNLOAD-ONLY-RESULT.txt (and no dirty-lane evidence either) is a
    named FAIL on every download-only check, never an assumed PASS."""
    run_dir = _synthetic_pass_dir(tmp_path)
    result = gav.judge(run_dir, source_sha="deadbeef", run_id="123", lane="download-only")
    assert result["checks"]["dirty_prep"]["status"] == "FAIL"
    assert result["checks"]["dirty_survival"]["status"] == "FAIL"
    assert result["checks"]["download_only_no_station_dir"]["status"] == "FAIL"
    assert "DOWNLOAD-ONLY-RESULT.txt" in result["checks"]["download_only_no_station_dir"]["detail"]
    assert result["verdict"] == "FAIL"


def test_download_only_lane_fails_when_station_dir_was_present(tmp_path: Path) -> None:
    """The whole point of this lane: if the phase-2 payload still carried a
    station\\ directory, it proved nothing about the download-only path."""
    run_dir = _synthetic_pass_dir(tmp_path)
    _write_upgrade_evidence(run_dir)
    _write_download_only_result(run_dir, station_dir_present="1")
    result = gav.judge(run_dir, source_sha=None, run_id=None, lane="download-only")

    check = result["checks"]["download_only_no_station_dir"]
    assert check["status"] == "FAIL"
    assert "STATION_DIR_PRESENT=1" in check["detail"]
    assert result["verdict"] == "FAIL"


def test_download_only_lane_fails_on_nonzero_phase2_install_exit(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    _write_upgrade_evidence(run_dir)
    _write_download_only_result(run_dir, phase2_install_exit="123")
    result = gav.judge(run_dir, source_sha=None, run_id=None, lane="download-only")

    check = result["checks"]["download_only_no_station_dir"]
    assert check["status"] == "FAIL"
    assert "PHASE2_INSTALL_EXIT=123" in check["detail"]
    assert result["verdict"] == "FAIL"


def test_download_only_lane_fails_on_nonzero_activation_engine_exit(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    _write_upgrade_evidence(run_dir)
    _write_download_only_result(run_dir, d3_engine_exit="7")
    result = gav.judge(run_dir, source_sha=None, run_id=None, lane="download-only")

    check = result["checks"]["download_only_no_station_dir"]
    assert check["status"] == "FAIL"
    assert "D3_ENGINE_EXIT=7" in check["detail"]
    assert result["verdict"] == "FAIL"


def test_download_only_lane_fails_when_station_set_names_a_different_version(
    tmp_path: Path,
) -> None:
    """station-set.json must name the CURRENT candidate -- a mismatch means
    activation may have reused a stale or wrong receipt instead of proving
    the parallel station-reuse change actually worked."""
    run_dir = _synthetic_pass_dir(tmp_path)
    _write_upgrade_evidence(run_dir)
    _write_download_only_result(
        run_dir,
        station_set_product_version="1.0.0-rc18",
        current_product_version="1.0.0-beta.2",
    )
    result = gav.judge(run_dir, source_sha=None, run_id=None, lane="download-only")

    check = result["checks"]["download_only_no_station_dir"]
    assert check["status"] == "FAIL"
    assert "does not match" in check["detail"]
    assert result["verdict"] == "FAIL"


def test_download_only_lane_never_runs_dirty_orphaned_tier(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    _write_upgrade_evidence(run_dir)
    _write_download_only_result(run_dir)
    result = gav.judge(run_dir, source_sha=None, run_id=None, lane="download-only")
    assert "dirty_orphaned_tier" not in result["checks"]


def test_download_only_lane_cli_lane_flag(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    _write_upgrade_evidence(run_dir)
    _write_download_only_result(run_dir)
    proc = subprocess.run(
        [sys.executable, str(_MODULE_PATH), str(run_dir), "--lane", "download-only"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    written = json.loads((run_dir / "gate-a-verdict.json").read_text(encoding="utf-8"))
    assert written["lane"] == "download-only"
    assert written["verdict"] == "PASS"


def test_download_only_busy_short_circuit_still_carries_the_lane(tmp_path: Path) -> None:
    run_dir = tmp_path / "busy"
    run_dir.mkdir()
    (run_dir / "SANDBOX-BUSY.txt").write_text("busy", encoding="utf-8")
    result = gav.judge(run_dir, source_sha=None, run_id=None, lane="download-only")
    assert result["verdict"] == "BUSY"
    assert result["lane"] == "download-only"
