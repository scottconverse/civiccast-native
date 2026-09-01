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
    "completion",
)


def _copy_fixture(dest: Path) -> Path:
    shutil.copytree(_FIXTURE_DIR, dest)
    return dest


def _synthetic_pass_dir(tmp_path: Path) -> Path:
    """A copy of the real fixture PLUS a synthetic DONE.json.

    This is the only place this test module invents evidence that was not
    actually produced by a harness run, and it does so only to exercise the
    judge's all-PASS code path in isolation -- it is never presented as real
    station-acceptance evidence.
    """
    run_dir = _copy_fixture(tmp_path / "run")
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
        "installer_exit_code": 0,
        "harness_completed": True,
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


def test_real_fixture_every_check_passes_except_completion() -> None:
    result = gav.judge(_FIXTURE_DIR, source_sha="8579e66", run_id="reference-2026-08-19")
    for name in REQUIRED_CHECKS:
        if name == "completion":
            continue
        assert result["checks"][name]["status"] == "PASS", (
            f"{name} unexpectedly FAILed on the real Aug-19 fixture: {result['checks'][name]['detail']}"
        )


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
    failing = [name for name, c in result["checks"].items() if c["status"] == "FAIL"]
    assert failing == ["completion"]


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


def test_completion_wrong_last_step_fails(tmp_path: Path) -> None:
    run_dir = _synthetic_pass_dir(tmp_path)
    done_path = run_dir / "DONE.json"
    done = json.loads(done_path.read_text(encoding="utf-8"))
    done["last_completed_step"] = "t4-egress-product-engine"
    done_path.write_text(json.dumps(done), encoding="utf-8")
    result = gav.judge(run_dir, None, None)
    assert result["checks"]["completion"]["status"] == "FAIL"
    assert "t4-egress-product-engine" in result["checks"]["completion"]["detail"]


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
    result = [
        "UPGRADE_MODE=1",
        f"UPGRADE_CURRENT_INSTALL_EXIT={current_install_exit}",
        f"D3_ROUTE={d3_route}",
        f"D3_ENGINE_EXIT={d3_engine_exit}",
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
