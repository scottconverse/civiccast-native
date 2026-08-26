# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Static cross-file contract tests for the Gate B harness.

No fixtures, no ``tmp_path``: this file reads the real repository files and
fails the build when literals that MUST agree stop agreeing. It is the
counterpart to ``tests/gate_a/test_gate_a_harness_contract.py``, and it exists
because Gate B cannot be exercised in CI -- a 24-hour reboot soak on real
hardware is not something a pull request can run, so everything that CAN be
checked statically must be.

The most load-bearing group is the FIRST one. Gate B's in-VM agent performs
its install and activation through
``sandbox-lab/common/CivicCastStationHarness.psm1``, while Gate A's driver
(``sandbox-lab/scripts/In-Sandbox-Report.ps1``) still performs the same steps
with its own inline code -- migrating the live Gate A driver onto the module
is deliberately deferred (see the module header and docs/ops/gate-b.md). While
that is true, these tests are the ONLY thing keeping the two implementations
from drifting into two different definitions of "installed and activated",
which would eventually mean one gate passing a candidate the other would fail.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _find_repo_root(start: Path) -> Path:
    """Walk upward from ``start`` to the CivicCast repo root.

    A fixed ``parents[2]`` offset assumes this file always sits two
    directories below the repo root. That breaks under mutmut: the
    mutation-report job copies only the diff-scoped Python source (and a
    fixed ``also_copy`` list that does not include ``sandbox-lab`` or
    ``gate-b``) into a ``mutants/`` directory, so
    ``mutants/tests/gate_b/<this file>`` has no ``sandbox-lab`` sibling at
    the depth the fixed offset expects -- ``mutants/`` itself is nested
    inside the real checkout, though, so walking upward past it lands back
    on the real repo root, which does have ``sandbox-lab``. Recognise the
    root by a marker instead of a hardcoded depth: the presence of the
    PowerShell driver Gate B's tests read (shared with Gate A's contract
    test, see ``tests/gate_a/test_gate_a_harness_contract.py``), falling
    back to ``.git`` for any other caller that lands here without
    ``sandbox-lab`` on disk at all.
    """
    for candidate in (start, *start.parents):
        if (candidate / "sandbox-lab" / "scripts" / "In-Sandbox-Report.ps1").is_file():
            return candidate
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError(
        f"could not locate the CivicCast repo root by walking up from {start} -- "
        "expected to find sandbox-lab/scripts/In-Sandbox-Report.ps1 or a .git marker"
    )


_REPO_ROOT = _find_repo_root(Path(__file__).resolve())

_MODULE = _REPO_ROOT / "sandbox-lab" / "common" / "CivicCastStationHarness.psm1"
_GATE_A_DRIVER = _REPO_ROOT / "sandbox-lab" / "scripts" / "In-Sandbox-Report.ps1"
_AGENT = _REPO_ROOT / "gate-b" / "scripts" / "In-Vm-GateB-Agent.ps1"
_STARTUP_TASK = _REPO_ROOT / "gate-b" / "scripts" / "Register-GateBStartupTask.ps1"
_RUNNER = _REPO_ROOT / "gate-b" / "Run-GateB.ps1"
_PROVISION = _REPO_ROOT / "gate-b" / "Provision-GateBVm.ps1"
_PREREQS = _REPO_ROOT / "gate-b" / "Test-GateBPrereqs.ps1"
_ANSWER_FILE = _REPO_ROOT / "gate-b" / "answer" / "autounattend.xml"
_JUDGE_PATH = _REPO_ROOT / "scripts" / "gate_b_verdict.py"
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "gate-b-reboot-soak.yml"
_VERIFY_EGRESS = _REPO_ROOT / "sandbox-lab" / "soak-4h" / "scripts" / "verify-egress.ps1"
_SUPERVISOR_CORE = _REPO_ROOT / "civiccast" / "native" / "supervisor" / "core.py"

_WORKFLOW_NAME = "gate-b-reboot-soak.yml"
_JOB_NAME = "reboot-soak"


def _read(path: Path) -> str:
    assert path.is_file(), f"expected file is missing: {path}"
    return path.read_text(encoding="utf-8-sig")


def _load_judge() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gate_b_verdict_contract", _JUDGE_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _int_setting(text: str, pattern: str, what: str) -> int:
    match = re.search(pattern, text)
    assert match is not None, f"could not read {what} (pattern {pattern!r} did not match)"
    return int(match.group(1))


# ---------------------------------------------------------------------------
# 1. The shared module vs Gate A's inline implementation
# ---------------------------------------------------------------------------


def test_the_shared_module_exists_and_exports_the_install_and_activation_contract() -> None:
    text = _read(_MODULE)
    for function in (
        "Invoke-CivicCastSilentInstall",
        "Write-CivicCastActivationResult",
        "Test-CivicCastKnownPaths",
        "Wait-CivicCastStationHealth",
        "Get-CivicCastHarnessContract",
    ):
        assert f"function {function}" in text, f"{function} is not defined in the shared module"
        assert f"'{function}'" in text, f"{function} is defined but not exported"


def test_silent_install_flag_agrees_with_gate_a() -> None:
    """Both gates must install the candidate the same way.

    Gate A hardcodes '/S /D=<dir>' inline; the module holds '/S' and '/D=' as
    named constants and composes them. If either side changes the flag, the
    two gates stop testing the same installation and this fails.
    """
    module = _read(_MODULE)
    driver = _read(_GATE_A_DRIVER)

    silent = re.search(r"\$script:CivicCastSilentFlag\s*=\s*'([^']+)'", module)
    install_dir = re.search(r"\$script:CivicCastInstallDirFlag\s*=\s*'([^']+)'", module)
    assert silent is not None and install_dir is not None
    assert silent.group(1) == "/S"
    assert install_dir.group(1) == "/D="

    gate_a_flag = re.search(r"ArgumentList\s+'(/S\s+/D=[^']+)'", driver)
    assert gate_a_flag is not None, "could not find Gate A's installer ArgumentList literal"
    assert gate_a_flag.group(1).startswith(silent.group(1) + " " + install_dir.group(1)), (
        f"Gate A installs with {gate_a_flag.group(1)!r}, which does not start with the module's "
        f"{silent.group(1)} {install_dir.group(1)}"
    )


def test_activation_artefact_filenames_agree_with_gate_a() -> None:
    module = _read(_MODULE)
    driver = _read(_GATE_A_DRIVER)
    for constant, filename in (
        ("CivicCastStationSetFileName", "station-set.json"),
        ("CivicCastActivationSelfTestFileName", "activation-self-test.json"),
    ):
        match = re.search(rf"\$script:{constant}\s*=\s*'([^']+)'", module)
        assert match is not None, f"{constant} is not defined in the shared module"
        assert match.group(1) == filename
        assert f"'{filename}'" in driver, (
            f"Gate A's driver does not mention {filename}; the two gates would be probing for "
            "different activation artefacts"
        )


def test_known_path_lookup_probes_the_same_four_shapes_as_gate_a() -> None:
    """The four shapes, and specifically NOT a recursive scan.

    Gate A adopted a targeted lookup after a recursive Get-ChildItem over a
    ~12 GB install tree became one of the operations that could wedge its
    harness thread. The module inherits both the shapes and the prohibition.
    """
    module = _read(_MODULE)
    driver = _read(_GATE_A_DRIVER)

    known_paths = module.split("function Test-CivicCastKnownPaths", 1)[1].split("\nfunction ", 1)[0]
    # Strip the comment-based help block before asserting on the body. The
    # docstring EXPLAINS why a recursive scan is forbidden, and naming the
    # forbidden thing in prose must not read as doing it.
    known_paths_body = re.sub(r"<#.*?#>", "", known_paths, flags=re.DOTALL)
    assert "Join-Path $InstallDir $FileName" in known_paths_body
    assert "Join-Path $InstallDir 'app'" in known_paths_body
    assert "Join-Path $env:ProgramData 'CivicCast'" in known_paths_body
    assert "-Recurse" not in known_paths_body, (
        "the shared module's known-path lookup must never recurse -- that is the exact operation "
        "Gate A removed after it wedged the harness on a multi-GB install tree"
    )

    gate_a_known_paths = driver.split("function Test-KnownPaths", 1)[1].split("\n# ", 1)[0]
    assert "-Recurse" not in gate_a_known_paths
    for fragment in ("'app'", "'CivicCast'"):
        assert fragment in gate_a_known_paths


def test_activation_result_field_names_are_what_both_judges_read() -> None:
    """One file shape, two judges.

    ``ACTIVATION-RESULT.txt`` is written by the shared module and read by
    BOTH scripts/gate_a_verdict.py and scripts/gate_b_verdict.py. All three
    have to agree on the field names or Gate B reports a spurious activation
    failure on a perfectly good install.
    """
    module = _read(_MODULE)
    gate_a_judge = _read(_REPO_ROOT / "scripts" / "gate_a_verdict.py")
    gate_b_judge = _read(_JUDGE_PATH)

    for field in ("installer_exit_code", "station_set_json_found_after_install"):
        assert f'"{field}=' in module, (
            f"the module does not write {field} into ACTIVATION-RESULT.txt"
        )
        assert field in gate_a_judge, f"gate_a_verdict.py does not read {field}"
        assert field in gate_b_judge, f"gate_b_verdict.py does not read {field}"


def test_summary_field_names_agree_across_the_agent_and_both_judges() -> None:
    agent = _read(_AGENT)
    gate_a_judge = _read(_REPO_ROOT / "scripts" / "gate_a_verdict.py")
    gate_b_judge = _read(_JUDGE_PATH)
    for field in (
        "installer_exit_code",
        "station_set_json_found",
        "activation_self_test_json_found",
    ):
        assert field in agent, f"the Gate B agent does not write summary.json.{field}"
        assert field in gate_a_judge, f"gate_a_verdict.py does not read {field}"
        assert field in gate_b_judge, f"gate_b_verdict.py does not read {field}"


# ---------------------------------------------------------------------------
# 2. The reboot is what makes this Gate B
# ---------------------------------------------------------------------------


def test_the_host_issues_the_reboot_and_the_guest_does_not() -> None:
    """A station that reboots itself on a schedule it knows can prepare for it.

    §12 asks the box to survive a reboot; in the field that arrives
    unannounced. Issuing it from the host is the closest a VM can get, and it
    also means the timing record is written by something the guest could not
    have forged.
    """
    runner = _read(_RUNNER)
    agent = _read(_AGENT)
    assert "Restart-VM" in runner, "Run-GateB.ps1 must issue the reboot itself"
    for forbidden in ("Restart-Computer", "shutdown.exe", "shutdown /r"):
        assert forbidden not in agent, (
            f"the in-VM agent contains {forbidden!r} -- the guest must NOT reboot itself"
        )


def test_the_reboot_is_graceful_not_a_power_cut() -> None:
    """-Force on Restart-VM is a power-cut test, which is a DIFFERENT §12 line.

    §12 lists "kill+restart+reboot" and §5 rung 2 separately names
    "unclean-restart reap". Smuggling a hard power cut in here would make one
    run claim to have proven both, when it would actually have proven neither
    cleanly.
    """
    runner = _read(_RUNNER)
    restart_line = next(
        (line for line in runner.splitlines() if line.strip().startswith("Restart-VM")), None
    )
    assert restart_line is not None
    assert "-Force" not in restart_line, restart_line


def test_the_resume_task_is_at_startup_as_system_never_at_logon() -> None:
    """The single line that separates "rebooted" from "survived UNATTENDED".

    An at-logon task waits for a person. §12 asks for survival with nobody
    there.
    """
    text = _read(_STARTUP_TASK)
    assert "New-ScheduledTaskTrigger -AtStartup" in text
    assert "-AtLogOn" not in text and "-AtLogon" not in text
    assert "-UserId 'SYSTEM'" in text
    assert "MSFT_TaskBootTrigger" in text, (
        "the registration must read the task back and confirm it really is a BOOT trigger; "
        "'Register-ScheduledTask did not throw' is a weaker claim"
    )


def test_the_answer_file_does_not_auto_logon() -> None:
    """Auto-logon would make every post-reboot beat honestly report attended."""
    text = _read(_ANSWER_FILE)
    assert "<AutoLogon>" not in text
    assert "CHANGE-ME-BEFORE-USE" in text, (
        "the shipped answer file must carry a placeholder password, never a working credential"
    )


def test_the_agent_survives_a_reboot_by_state_not_by_assumption() -> None:
    text = _read(_AGENT)
    assert "state.json" in text
    assert "startup-task" in text
    # A resume that finds no state must refuse rather than start a fresh run
    # under a resume's identity -- otherwise the soak's clock silently
    # restarts and the run reports 24 hours that never happened.
    assert "refusing to start a NEW run under a resume's identity" in text


# ---------------------------------------------------------------------------
# 3. Reuse, not copy-paste
# ---------------------------------------------------------------------------


def test_gate_b_reuses_the_existing_tsduck_verifier_rather_than_copying_it() -> None:
    runner = _read(_RUNNER)
    assert "sandbox-lab\\soak-4h\\scripts\\verify-egress.ps1" in runner, (
        "Run-GateB.ps1 must stage the EXISTING verify-egress.ps1 into the guest"
    )
    copies = list((_REPO_ROOT / "gate-b").rglob("verify-egress.ps1"))
    assert copies == [], (
        f"a copy of verify-egress.ps1 exists under gate-b/ ({copies}); two TSDuck pass/fail "
        "definitions in one repository eventually give two answers"
    )


def test_the_egress_schema_the_judge_expects_is_the_one_the_verifier_writes() -> None:
    judge = _load_judge()
    verifier = _read(_VERIFY_EGRESS)
    assert f'schema = "{judge.EGRESS_SCHEMA}"' in verifier, (
        f"gate_b_verdict expects {judge.EGRESS_SCHEMA!r} but verify-egress.ps1 does not write it"
    )


def test_the_peg_channels_and_ports_agree_between_the_agent_and_the_verifier() -> None:
    """The agent starts channels on ports the verifier is not listening on = silent 'fail'."""
    judge = _load_judge()
    agent = _read(_AGENT)
    verifier = _read(_VERIFY_EGRESS)
    for channel, port in (("public", 9001), ("education", 9002), ("government", 9003)):
        assert channel in judge.REQUIRED_CHANNELS
        assert re.search(rf"channel_id\s*=\s*'{channel}';\s*port\s*=\s*{port}", agent), (
            f"the agent does not map {channel} to port {port}"
        )
        assert re.search(rf'channel\s*=\s*"{channel}";\s*port\s*=\s*{port}', verifier), (
            f"verify-egress.ps1 does not listen for {channel} on port {port}"
        )


def test_gate_b_drives_the_product_engine_not_synthetic_ffmpeg() -> None:
    """Gate A already treats an ffmpeg-fallback egress proof as a FAIL (S15).

    A 24-hour soak of a fallback path would prove even less than the 20-minute
    one Gate A refuses.
    """
    agent = _read(_AGENT)
    assert "/api/staff/egress/channels/$id/commands" in agent
    assert "lavfi" not in agent, "the agent must not spawn synthetic ffmpeg encoders"
    assert "start-encoders.ps1" not in agent


def test_the_supervisor_restart_pattern_matches_the_products_real_log_wording() -> None:
    """The judge's corroborating instrument must match a string the product writes.

    A pattern the supervisor never emits would make this check silently
    unfalsifiable -- it would pass on every run, including the ones it exists
    to catch.
    """
    judge = _load_judge()
    core = _read(_SUPERVISOR_CORE)
    assert '"restart of child %s not ready: detail=%s"' in core, (
        "civiccast/native/supervisor/core.py no longer emits the WARNING the Gate B judge greps "
        "for; update SUPERVISOR_RESTART_WARNING to match whatever replaced it"
    )
    rendered = "restart of child control_plane not ready: detail=probe timed out"
    assert judge.SUPERVISOR_RESTART_WARNING.search(rendered) is not None


# ---------------------------------------------------------------------------
# 4. Markers: one filename, agreed between the writer and the judge
# ---------------------------------------------------------------------------


def test_the_hyperv_marker_filename_agrees_between_powershell_and_python() -> None:
    judge = _read(_JUDGE_PATH)
    prereqs = _read(_PREREQS)
    runner = _read(_RUNNER)
    assert "HYPERV-UNAVAILABLE.txt" in judge
    assert "HYPERV-UNAVAILABLE.txt" in prereqs, (
        "Test-GateBPrereqs.ps1 must write the marker the judge keys HYPERV_UNAVAILABLE off"
    )
    assert "HYPERV-UNAVAILABLE.txt" in runner


def test_every_harness_error_marker_is_actually_written_by_the_host_script() -> None:
    judge = _load_judge()
    runner = _read(_RUNNER)
    for marker in judge.HARNESS_ERROR_MARKERS:
        assert marker in runner, (
            f"the judge treats {marker} as a harness error, but Run-GateB.ps1 never writes it -- "
            "a marker nothing produces is a branch that can never fire"
        )


def test_the_prereq_probe_reports_and_never_elevates() -> None:
    """Enabling a hypervisor reboots the runner box. A gate must not do that.

    The script must NAME the command, and must not run it.
    """
    text = _read(_PREREQS)
    assert (
        "Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All -All -NoRestart"
        in text
    )
    # It may mention the command in the strings it prints, but must never
    # invoke it or request elevation.
    assert "Start-Process" not in text
    assert "-Verb RunAs" not in text
    assert "runas" not in text.lower()


def test_the_prereq_probe_does_not_treat_hypervisorpresent_as_the_verdict() -> None:
    """The instrument with the well-known blind spot, named rather than trusted.

    Win32_ComputerSystem.HypervisorPresent is TRUE on this very box with
    Hyper-V DISABLED, because WSL2 and Windows Sandbox run on the same
    hypervisor. Measured 2026-08-25 on the sandbox-lab runner:
    Microsoft-Hyper-V-All InstallState=2 (Disabled), HypervisorPresent=True.
    """
    text = _read(_PREREQS)
    assert "hypervisor_present_note" in text
    assert "CONTEXT ONLY" in text
    verdict_block = text.split("# --- Verdict:", 1)[1].split("$report = @()", 1)[0]
    assert "hypervisor_present" not in verdict_block, (
        "HypervisorPresent must not participate in the verdict -- it is true on a box with "
        "Hyper-V disabled whenever WSL2 or Windows Sandbox is in use"
    )


# ---------------------------------------------------------------------------
# 5. Budget ordering -- one setting written in several places
# ---------------------------------------------------------------------------


def test_budgets_are_ordered_soak_then_host_deadline_then_job_timeout() -> None:
    """Each bound must outlast the one inside it, or the outer one fires first.

    Gate A learned this the expensive way: a watchdog set longer than the host
    poll deadline turns every long run into an unexplained timeout with no
    watchdog evidence. The same ordering discipline applies here across three
    files, and the CI job timeout is the one that actually governs a real run.
    """
    soak = _int_setting(
        _read(_RUNNER), r"\[int\]\$SoakMinutes\s*=\s*(\d+)", "Run-GateB -SoakMinutes"
    )
    host_deadline = _int_setting(
        _read(_RUNNER),
        r"\[int\]\$HostDeadlineMinutes\s*=\s*(\d+)",
        "Run-GateB -HostDeadlineMinutes",
    )
    job_timeout = _int_setting(
        _read(_WORKFLOW), r"timeout-minutes:\s*(\d+)", "the workflow job's timeout-minutes"
    )

    assert host_deadline > soak, (
        f"the host deadline ({host_deadline}m) must outlast the soak ({soak}m), or the harness "
        "kills the run it is supervising"
    )
    assert job_timeout > host_deadline, (
        f"the CI job timeout ({job_timeout}m) must outlast the host deadline ({host_deadline}m), "
        "or GitHub kills the job before Run-GateB.ps1 can write its verdict"
    )


def test_the_default_plan_is_the_spec_floor_not_something_below_it() -> None:
    judge = _load_judge()
    runner = _read(_RUNNER)
    soak = _int_setting(runner, r"\[int\]\$SoakMinutes\s*=\s*(\d+)", "-SoakMinutes")
    interval = _int_setting(
        runner, r"\[int\]\$BeatIntervalMinutes\s*=\s*(\d+)", "-BeatIntervalMinutes"
    )
    reboot_at = _int_setting(runner, r"\[int\]\$RebootAtMinutes\s*=\s*(\d+)", "-RebootAtMinutes")

    assert soak >= judge.SPEC_MIN_SOAK_MINUTES, (
        f"the default soak ({soak}m) is below the §12 floor the judge enforces "
        f"({judge.SPEC_MIN_SOAK_MINUTES}m), so the default run would FAIL its own plan check"
    )
    assert interval <= judge.SPEC_MAX_BEAT_INTERVAL_MINUTES
    assert 0 < reboot_at < soak, "the reboot must fall inside the soak window"


def test_the_agent_default_soak_matches_the_runner_default() -> None:
    """Two defaults for one number is one default and one trap."""
    runner_soak = _int_setting(_read(_RUNNER), r"\[int\]\$SoakMinutes\s*=\s*(\d+)", "-SoakMinutes")
    agent_soak = _int_setting(
        _read(_AGENT), r"\[int\]\$SoakMinutes\s*=\s*(\d+)", "agent -SoakMinutes"
    )
    assert runner_soak == agent_soak


def test_recovery_budget_fits_inside_the_reboot_gap_budget() -> None:
    """They measure different things, and the ordering between them is real.

    The gap budget bounds how long the beat log may be silent; the recovery
    budget bounds how long the station may take to be broadcasting again.
    Recovery is observed by a BEAT, so a recovery budget larger than the gap
    budget describes a recovery no beat could ever record.
    """
    runner = _read(_RUNNER)
    gap = _int_setting(
        runner, r"\[int\]\$RebootGapBudgetMinutes\s*=\s*(\d+)", "-RebootGapBudgetMinutes"
    )
    recovery = _int_setting(
        runner, r"\[int\]\$RecoveryBudgetMinutes\s*=\s*(\d+)", "-RecoveryBudgetMinutes"
    )
    assert recovery <= gap, f"recovery budget ({recovery}m) exceeds the reboot gap budget ({gap}m)"


def test_the_startup_delay_fits_inside_the_reboot_gap_budget() -> None:
    """The resume delay is spent inside the gap the judge is measuring."""
    task = _read(_STARTUP_TASK)
    match = re.search(r"\[string\]\$StartupDelay\s*=\s*'PT(\d+)M'", task)
    assert match is not None, "could not read the startup task's delay default"
    delay = int(match.group(1))
    gap = _int_setting(
        _read(_RUNNER), r"\[int\]\$RebootGapBudgetMinutes\s*=\s*(\d+)", "-RebootGapBudgetMinutes"
    )
    assert delay < gap, f"the {delay}m startup delay must fit inside the {gap}m reboot gap budget"


# ---------------------------------------------------------------------------
# 6. Policy ledgers -- the workflow must be registered, with dated reasons
# ---------------------------------------------------------------------------


def test_the_workflow_is_registered_in_the_self_hosted_allowlist() -> None:
    from scripts.policy.check_workflow_runners import SELF_HOSTED_ALLOWLIST

    assert _WORKFLOW_NAME in SELF_HOSTED_ALLOWLIST
    reason = SELF_HOSTED_ALLOWLIST[_WORKFLOW_NAME]
    assert len(reason.strip()) > 20, "the allowlist is an exception ledger, not a loophole"
    assert "2026-08-25" in reason, "every Gate B ledger entry carries the date it was added"


def test_the_workflow_is_registered_in_the_budget_exceptions() -> None:
    from scripts.policy.check_actions_budget import DOCUMENTED_BUDGET_EXCEPTIONS

    assert _WORKFLOW_NAME in DOCUMENTED_BUDGET_EXCEPTIONS
    reason = DOCUMENTED_BUDGET_EXCEPTIONS[_WORKFLOW_NAME]
    assert len(reason.strip()) > 20
    assert "2026-08-25" in reason


def test_the_job_is_registered_as_long_by_design() -> None:
    from scripts.policy.check_workflow_timeouts import LONG_BY_DESIGN, MAX_MINUTES

    key = (_WORKFLOW_NAME, _JOB_NAME)
    assert key in LONG_BY_DESIGN, (
        f"{key} is not in LONG_BY_DESIGN; a job over {MAX_MINUTES} minutes is refused without it"
    )
    reason = LONG_BY_DESIGN[key]
    assert len(reason.strip()) > 20
    assert "2026-08-25" in reason


def test_the_long_by_design_job_name_is_the_workflows_actual_job_name() -> None:
    """A ledger entry keyed on a job that does not exist protects nothing."""
    import yaml

    from scripts.policy.check_workflow_timeouts import LONG_BY_DESIGN

    workflow = yaml.safe_load(_read(_WORKFLOW))
    jobs = list(workflow["jobs"])
    assert jobs == [_JOB_NAME], f"the workflow's jobs are {jobs}, not [{_JOB_NAME!r}]"
    assert (_WORKFLOW_NAME, _JOB_NAME) in LONG_BY_DESIGN


def test_the_repo_policy_checks_accept_the_new_workflow() -> None:
    """Run the real checks, not a reimplementation of what they probably do."""
    from scripts.policy.check_workflow_runners import check_workflow_runners

    violations = [v for v in check_workflow_runners() if _WORKFLOW_NAME in str(v)]
    assert violations == [], violations


def test_every_artifact_transfer_step_declares_its_own_timeout() -> None:
    """check_workflow_timeouts requires it per STEP, not just per job."""
    import yaml

    workflow = yaml.safe_load(_read(_WORKFLOW))
    for job_name, job in workflow["jobs"].items():
        for step in job.get("steps", []):
            uses = str(step.get("uses", ""))
            if "upload-artifact" in uses or "download-artifact" in uses:
                assert "timeout-minutes" in step, (
                    f"{job_name} step {step.get('name')!r} transfers artifacts without its own "
                    "timeout-minutes"
                )


# ---------------------------------------------------------------------------
# 7. Honesty of the shipped status
# ---------------------------------------------------------------------------


def test_the_docs_state_gate_b_has_not_been_run() -> None:
    """Until a real run happens, every surface must say so.

    This is the check that would have caught the project's own historical
    failure mode -- a harness landing with documentation written as though it
    had already produced a result.
    """
    doc = _read(_REPO_ROOT / "docs" / "ops" / "gate-b.md")
    assert "NOT YET RUN" in doc
    workflow = _read(_WORKFLOW)
    assert "NOT YET RUN" in workflow


def test_the_fixtures_directory_explains_its_own_emptiness() -> None:
    readme = _REPO_ROOT / "tests" / "gate_b" / "fixtures" / "README.md"
    assert readme.is_file()
    text = _read(readme)
    assert "Gate B has never been run" in text
    captured = [p for p in readme.parent.iterdir() if p.is_dir()]
    assert captured == [], (
        f"{captured} looks like captured run evidence; if a real run has landed, add a test that "
        "judges it and asserts its ACTUAL verdict rather than leaving it unasserted"
    )


@pytest.mark.parametrize(
    "path",
    [
        _MODULE,
        _AGENT,
        _STARTUP_TASK,
        _RUNNER,
        _PROVISION,
        _PREREQS,
    ],
)
def test_every_harness_script_carries_the_spdx_header(path: Path) -> None:
    head = _read(path).splitlines()[:3]
    assert any("SPDX-License-Identifier: Apache-2.0" in line for line in head), path
