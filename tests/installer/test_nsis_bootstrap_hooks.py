"""Contract for the operator-facing behaviour of the NSIS bootstrap hooks.

`nsis-hooks-bootstrap.nsh` is the ONE live native installer hook file (see its
own header, and `tests/policy/test_native_installer_identity.py` for the pin on
that fact). It is NSIS script, not Python or Rust, so -- following the
source-shape convention `test_native_service_start.py` and
`test_tauri_windows_manifest.py` already use in this directory -- the contract
pinned here is the SHAPE of the script text: which exit codes each step
branches on, which branches route to the fail-loud `CIVICCAST_FAIL` macro, and
what the operator-visible remedy text actually says.

Both defects covered here were found on real hardware on 2026-08-01, not in the
pristine Windows Sandbox that every prior proof run used:

  * chain E -- the vc-redist step hard-failed the whole install on MSI exit
    1638 (ERROR_PRODUCT_VERSION, "another version of this product is already
    installed"), which for the VC++ redistributable bootstrapper is the NORMAL
    state of a machine that already carries a same-or-newer runtime. The
    prerequisite is satisfied; the install aborted anyway.

  * chain F -- the stage-packs failure dialog offered a remedy the product does
    not implement ("connect this machine to the network so setup can download
    them"). The hook's own comment says the online path is a typed
    NOT_AVAILABLE outcome today because no channel index URL is pinned anywhere
    in this codebase.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP_HOOKS_NSH = (
    ROOT / "civiccast" / "apps" / "installer" / "src-tauri" / "nsis-hooks-bootstrap.nsh"
)

VC_REDIST_BEGIN = '!insertmacro CIVICCAST_STEP "step vc-redist: begin"'
STAGE_PACKS_BEGIN = '!insertmacro CIVICCAST_STEP "step stage-packs: begin"'


def _hooks_source() -> str:
    return BOOTSTRAP_HOOKS_NSH.read_text(encoding="utf-8")


def _slice(source: str, start_marker: str, end_marker: str) -> str:
    start = source.find(start_marker)
    assert start != -1, f"{start_marker!r} not found in {BOOTSTRAP_HOOKS_NSH}"
    end = source.find(end_marker, start)
    assert end != -1, f"{end_marker!r} not found after {start_marker!r}"
    return source[start:end]


def _vc_redist_block(source: str) -> str:
    """The whole vc-redist step, from its breadcrumb to the next step's."""
    return _slice(source, VC_REDIST_BEGIN, STAGE_PACKS_BEGIN)


def _vc_redist_1638_branch(block: str) -> str:
    """The 1638 arm only, up to the chain's outer catch-all `${Else}`.

    The outer `${If}/${ElseIf}/${Else}` chain sits at two-space indentation, so
    a newline followed by exactly two spaces and `${Else}` closes the 1638 arm;
    any `${Else}` nested INSIDE the arm is indented deeper than that.
    """
    marker = "$0 == 1638"
    start = block.find(marker)
    assert start != -1, (
        "the vc-redist step has no branch for MSI exit 1638 (ERROR_PRODUCT_VERSION). "
        "1638 from the VC++ redistributable bootstrapper means a same-or-newer runtime "
        "is already installed -- the prerequisite is SATISFIED -- yet it currently "
        "falls into the catch-all that aborts the install. Real machine R7 failed "
        "install on exactly this on 2026-08-01."
    )
    end = block.find("\n  ${Else}", start)
    assert end != -1, "the vc-redist branch chain has no outer catch-all ${Else}"
    return block[start:end]


def test_e_the_1638_branch_verifies_the_runtime_is_really_present_in_the_registry() -> None:
    branch = _vc_redist_1638_branch(_vc_redist_block(_hooks_source()))

    assert "SetRegView 64" in branch, (
        "the 1638 branch must read the 64-bit registry view explicitly; the VC++ x64 "
        "runtime key lives in the 64-bit view and a 32-bit NSIS installer does not see "
        "it by default"
    )
    assert "ReadRegDWORD" in branch, (
        "the 1638 branch must READ the runtime's presence, not assume it; 'Installed' is a DWORD"
    )
    assert r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" in branch, (
        "the 1638 branch does not read Microsoft's documented VC++ x64 runtime presence key"
    )
    assert '"Installed"' in branch, (
        "the 1638 branch does not read the 'Installed' DWORD value that proves the "
        "runtime is genuinely present"
    )


def test_e_a_confirmed_present_runtime_is_a_success_and_an_unconfirmed_one_still_fails() -> None:
    branch = _vc_redist_1638_branch(_vc_redist_block(_hooks_source()))

    split = branch.find("\n    ${Else}")
    assert split != -1, (
        "the 1638 branch does not split on the registry answer; it must have a "
        "confirmed-present arm AND an unconfirmed arm"
    )
    confirmed_present, unconfirmed = branch[:split], branch[split:]

    assert "CIVICCAST_FAIL" not in confirmed_present, (
        "a 1638 whose runtime presence IS confirmed in the registry still routes to "
        "CIVICCAST_FAIL and aborts the install; the prerequisite is satisfied and the "
        "install must continue"
    )
    assert "DetailPrint" in confirmed_present, (
        "the confirmed-present case must say so honestly in the installer log"
    )
    assert "CIVICCAST_FAIL $0" in unconfirmed, (
        "a 1638 that the registry does NOT confirm is genuinely abnormal and must keep "
        "failing loud with the real MSI exit code"
    )


def test_e_every_other_nonzero_vc_redist_exit_code_still_fails_loud() -> None:
    block = _vc_redist_block(_hooks_source())

    handled = set(re.findall(r"\$0 == (\d+)", block))
    assert handled == {"0", "3010", "1638"}, (
        "the vc-redist step must special-case exactly success (0), success-with-reboot "
        "(3010) and already-present (1638); anything else is a real prerequisite "
        f"failure. Found: {sorted(handled)}"
    )

    catch_all = block[block.find("\n  ${Else}") :]
    assert "CIVICCAST_FAIL $0" in catch_all, (
        "the catch-all arm must keep routing every other nonzero exit code through the "
        "fail-loud macro with the redist's own exit code"
    )


# --------------------------------------------------------------------------
# chain F-min: the stage-packs failure dialog must only name remedies that exist
# --------------------------------------------------------------------------

PACK_DELIVERY_COMMENT_BEGIN = "NATIVE COMPONENT PACK DELIVERY"
D2_VERIFY_BEGIN = "D2 INSTALL-TIME RE-VERIFICATION"

# Remedies the product does not implement. There is no channel index URL pinned
# anywhere in this codebase, so `acquire_online_distribution` can only return a
# typed NOT_AVAILABLE -- telling an operator to plug in a network cable sends
# them to fix something that would not help.
FALSE_REMEDY_PATTERNS = (
    r"connect\b[^\"]{0,60}\bnetwork",
    r"\bdownload\b",
    r"\bonline[- ]fallback\b",
    r"\binternet\b",
)


def _stage_packs_step(source: str) -> str:
    """The stage-packs step itself: breadcrumb, DetailPrints and the abort."""
    return _slice(source, STAGE_PACKS_BEGIN, D2_VERIFY_BEGIN)


def _stage_packs_comment(source: str) -> str:
    """The pack-delivery design comment that sits above the step."""
    return _slice(source, PACK_DELIVERY_COMMENT_BEGIN, STAGE_PACKS_BEGIN)


def _stage_packs_fail_message(source: str) -> str:
    step = _stage_packs_step(source)
    marker = "!insertmacro CIVICCAST_FAIL ${CIVICCAST_EXIT_PACK_DELIVERY}"
    start = step.find(marker)
    assert start != -1, (
        "the stage-packs step no longer aborts through CIVICCAST_FAIL with "
        "CIVICCAST_EXIT_PACK_DELIVERY; the exit code and the fail-loud routing must not "
        "change"
    )
    return step[start + len(marker) : step.find("\n", start)]


def test_f_the_stage_packs_failure_never_offers_a_remedy_the_product_cannot_perform() -> None:
    step = _stage_packs_step(_hooks_source())

    operator_text = "\n".join(
        line for line in step.splitlines() if "DetailPrint" in line or "CIVICCAST_FAIL" in line
    )
    for pattern in FALSE_REMEDY_PATTERNS:
        found = re.search(pattern, operator_text, re.IGNORECASE)
        assert found is None, (
            f"the stage-packs step tells the operator {found.group(0)!r}, but no online "
            "pack acquisition exists: no channel index URL is pinned anywhere in this "
            "codebase, so acquire_online_distribution can only return a typed "
            "NOT_AVAILABLE. A real tester hit this on 2026-08-01 (child exit 74, hook "
            "exit 110) and was given instructions for a capability the product does not "
            "have."
        )


def test_f_the_stage_packs_failure_names_the_remedy_that_does_exist() -> None:
    message = _stage_packs_fail_message(_hooks_source())

    assert "'packs' folder" in message, (
        "the dialog must name the side-load folder by its exact name; that is the only "
        "path that actually delivers a pack"
    )
    assert "next to the installer" in message, (
        "the dialog must say WHERE the 'packs' folder goes -- $EXEDIR, beside the installer .exe"
    )
    assert re.search(r"release page|distribution medium", message, re.IGNORECASE), (
        "the dialog must tell the operator where to obtain the pack file(s); 'put the "
        "file somewhere' is not a remedy if they do not know where the file comes from"
    )
    # Intent: name the retry step; the dialog's numbered step correctly capitalizes it.
    assert "run setup again" in message.lower(), "the dialog must name the retry step"
    assert "installer log" in message, (
        "the dialog must keep pointing at the installer log for the exact missing component list"
    )


def test_f_the_design_comment_stops_describing_the_missing_path_as_a_working_fallback() -> None:
    comment = _stage_packs_comment(_hooks_source())

    assert "online-fallback" not in comment, (
        "the comment labels the nonexistent path 'online-fallback', which reads as "
        "working behaviour; the label is what the false operator remedy was written from"
    )
    assert "NOT_AVAILABLE" in comment, (
        "the accurate description -- a typed NOT_AVAILABLE outcome, because no channel "
        "index URL is pinned anywhere in this codebase -- must stay"
    )


# --------------------------------------------------------------------------
# chain F-min2: the dialog promises the installer log names the missing
# component(s). TESTER2 (request-0050) verified on real hardware that
# C:\ProgramData\CivicCast\install-progress.log carries only the CIVICCAST_STEP
# breadcrumbs and never the component names, because the staging child's output
# went to the wizard detail pane (nsExec::ExecToLog) and nowhere else.
# --------------------------------------------------------------------------

PACK_STAGING_RS = (
    ROOT / "civiccast" / "apps" / "installer" / "src-tauri" / "src" / "native_pack_staging.rs"
)


def _stage_packs_failure_arm(step: str) -> str:
    start = step.find("${If} $0 != 0")
    assert start != -1, "the stage-packs step no longer branches on a nonzero child exit"
    return step[start:]


def test_f2_the_staging_child_output_is_captured_rather_than_only_streamed_to_the_pane() -> None:
    step = _stage_packs_step(_hooks_source())

    assert "nsExec::ExecToStack" in step, (
        "the staging child runs under nsExec::ExecToLog, which pipes its output into the "
        "wizard detail pane and NOWHERE else -- so the missing-component names the child "
        "prints can never reach install-progress.log, which is exactly what the failure "
        "dialog promises the operator will find there (TESTER2, request-0050)"
    )
    assert re.search(r"Pop \$0\s*;?[^\n]*\n\s*Pop \$1", step), (
        "ExecToStack pushes the exit code and then the captured output; both must be "
        "popped, or the output is discarded and the stack is left unbalanced"
    )
    # Chain F-min2 originally pinned an unconditional `DetailPrint "$1"` here,
    # because ExecToLog had put the child's output in the wizard pane and the
    # move to ExecToStack must not silently take it away. Chain O (finding
    # F-11, from the 2026-08-01 newcomer walkthrough) showed that on the
    # SUCCESS path that output is the child's raw JSON manifest report, and
    # dumping it into the pane both bewildered the operator and flushed the
    # real step log out of view. The requirement F-min2 was actually
    # protecting is that the child's words REACH THE OPERATOR'S LOG -- which
    # is what the failure dialog promises -- not that they are pasted into
    # the pane. Both paths must therefore carry $1 into install-progress.log
    # via the breadcrumb macro (the only writer of that file), and the
    # failure path is the one the dialog's promise depends on.
    assert re.search(r'CIVICCAST_STEP "step stage-packs: child reported: \$1"', step), (
        "the failure path must put the child's own words -- the missing component "
        "names -- into install-progress.log, or the dialog's 'see the installer log "
        "for the exact missing component(s)' is a promise the log cannot keep "
        "(TESTER2, request-0050)"
    )
    assert re.search(r'CIVICCAST_STEP "step stage-packs: manifest report: \$1"', step), (
        "the success path must still preserve the child's report in the installer "
        "log; it is the record of what was staged and verified"
    )
    assert 'DetailPrint "$1"' not in step, (
        "the raw child output must not be dumped into the wizard detail pane: on "
        "success it is a JSON manifest that means nothing to an operator and "
        "flushes the human step log out of view (walkthrough finding F-11)"
    )


def test_f2_the_captured_output_reaches_the_installer_log_on_failure() -> None:
    failure_arm = _stage_packs_failure_arm(_stage_packs_step(_hooks_source()))

    breadcrumbs_with_output = [
        line for line in failure_arm.splitlines() if "CIVICCAST_STEP" in line and "$1" in line
    ]
    assert breadcrumbs_with_output, (
        "nothing writes the child's captured output into install-progress.log on the "
        "failure path. CIVICCAST_STEP is the only thing in this file that writes to that "
        "file, so without it the dialog's 'see the installer log for the exact missing "
        "component(s)' is a promise the log cannot keep"
    )


def test_f2_the_rust_abort_message_names_the_components_without_a_download_remedy() -> None:
    source = PACK_STAGING_RS.read_text(encoding="utf-8")
    marker = "pub fn build_pack_delivery_abort_message"
    start = source.find(marker)
    assert start != -1, f"{marker} not found in {PACK_STAGING_RS}"
    body = source[start : source.find("\n}", start)]

    assert "missing_components.join" in body, (
        "the abort message must keep naming every missing component; that list is the "
        "whole reason the hook now persists this string into install-progress.log"
    )
    for pattern in FALSE_REMEDY_PATTERNS:
        found = re.search(pattern, body, re.IGNORECASE)
        assert found is None, (
            f"the staging child's own abort message tells the operator {found.group(0)!r}. "
            "The hook now persists this string verbatim into install-progress.log and the "
            "detail pane, so the false remedy chain F-min removed from the NSIS dialog "
            "would simply reappear in the operator's log through the child"
        )


# --------------------------------------------------------------------------
# chain M2: F-01, uninstaller half. The sandbox newcomer re-walk (dd7f835f,
# 2026-08-01) uninstalled through the product's own uninstaller -- which
# reported "Uninstall was completed successfully" -- and the post-uninstall
# sweep found HKLM\SOFTWARE\CivicCast\Native\InstalledVersion=1.0.0-rc15 still
# there. The next install read it, misclassified a clean install as an upgrade,
# ran the D3 engine and rolled back.
#
# Chain K owns the ROUTING side (what the D3 gate does with a version marker it
# should not trust). This pins the UNINSTALLER side: after a completed
# uninstall, nothing may be left claiming a product is installed. Two things
# make that claim -- InstalledVersion (cleared by the teardown CLI, pinned in
# native_service_registration.rs / native_uninstall.rs) and Tauri's
# InstallDirRegKey, whose DEFAULT VALUE is the install path and which is what
# Tauri's own reinstall page reads to decide a machine is "Already Installed".
# --------------------------------------------------------------------------

POSTUNINSTALL_MACRO_BEGIN = "!macro NSIS_HOOK_POSTUNINSTALL"
PREUNINSTALL_TEARDOWN_STEP = (
    '!insertmacro CIVICCAST_STEP "preuninstall: teardown native state '
    '(service/firewall/registry): begin"'
)

# Tauri derives NSIS's ${MANUFACTURER} from the bundle identifier's second
# segment when no explicit publisher is configured: tauri.native.conf.json's
# "org.civiccast.native" -> "civiccast" (which is also why the product's
# Publisher renders lowercase). ${PRODUCTNAME} is "CivicCast (Native)". So
# ${MANUPRODUCTKEY} is Software\civiccast\CivicCast (Native).
TAURI_INSTALL_DIR_REG_KEY = r"Software\civiccast\CivicCast (Native)"


def _postuninstall_macro(source: str) -> str:
    return _slice(source, POSTUNINSTALL_MACRO_BEGIN, "\n!macroend")


def _preuninstall_teardown_call(source: str) -> str:
    return _slice(source, PREUNINSTALL_TEARDOWN_STEP, "!macroend")


def test_m2_a_completed_uninstall_removes_the_tauri_install_dir_registry_key() -> None:
    macro = _postuninstall_macro(_hooks_source())

    assert f'DeleteRegKey HKLM "{TAURI_INSTALL_DIR_REG_KEY}"' in macro, (
        "NSIS_HOOK_POSTUNINSTALL never removes Tauri's InstallDirRegKey "
        f"(HKLM\\{TAURI_INSTALL_DIR_REG_KEY}), whose default value is the install path. "
        "Left behind, it is what makes a fresh install of this product show Tauri's "
        '"Already Installed" reinstall page on an otherwise clean host -- the same '
        "lifecycle defect the retired WSL product's nsis-hooks.nsh already carried an "
        "explicit repair for (its rc13 'orphaned uninstall registration' block), proving "
        "Tauri's own generated uninstall Section cannot be relied on to have done it"
    )


def test_m2_the_install_dir_key_is_only_removed_when_the_uninstall_really_completed() -> None:
    macro = _postuninstall_macro(_hooks_source())

    delete_at = macro.find(f'DeleteRegKey HKLM "{TAURI_INSTALL_DIR_REG_KEY}"')
    assert delete_at != -1, "no InstallDirRegKey removal to place"

    # $R2 == "1" is this macro's own latch for "the supervisor service could
    # not be confirmed stopped, so the program trees were NOT removed". A
    # machine whose trees are still there IS still installed; erasing the key
    # that says so would let the next install run straight over it.
    retention_gate = macro.find('${If} $R2 == "1"')
    assert retention_gate != -1, "the tree-retention gate ($R2) is gone"
    assert delete_at > retention_gate, (
        "the InstallDirRegKey removal must sit inside/after the tree-retention gate, not "
        "before it: on the retained-tree path the product is still installed and the key "
        "must keep saying so"
    )
    tail = macro[retention_gate:]
    skip_arm, _, remove_arm = tail.partition("${Else}")
    assert f'DeleteRegKey HKLM "{TAURI_INSTALL_DIR_REG_KEY}"' not in skip_arm, (
        "the InstallDirRegKey is removed on the SKIPPED arm, where the runtime/packs "
        "trees were deliberately left in place because the service could not be confirmed "
        "stopped"
    )
    assert f'DeleteRegKey HKLM "{TAURI_INSTALL_DIR_REG_KEY}"' in remove_arm, (
        "the InstallDirRegKey removal must be on the arm that actually removed the trees"
    )


def test_m2_the_teardown_result_is_still_what_gates_everything_downstream() -> None:
    """Guard against 'fix the leftover by ignoring the refusal'."""
    macro = _postuninstall_macro(_hooks_source())

    assert "$CIVICCAST_TEARDOWN_EXIT" in macro, (
        "the teardown exit code carried from PREUNINSTALL must still gate this macro"
    )
    assert 'StrCpy $CIVICCAST_TEARDOWN_EXIT "82"' in macro, (
        "the fail-closed default for an unset teardown result must stay"
    )


# --------------------------------------------------------------------------
# chain M3: F-03. The sandbox newcomer re-walk (dd7f835f, 2026-08-01) ended in
# a dialog that was false three ways and a log line that contradicted itself:
#
#   [2026-08-01 18:17:40] postinstall: SUCCESS (D3 clean rollback;
#                         InstalledVersion left at 1.0.0-rc15, NOT 1.0.0-rc15)
#
# and, on screen, "could not complete the upgrade to 1.0.0-rc15 and
# automatically rolled back. The previously installed version is healthy and
# still running -- no data was lost." while the machine actually held a
# complete 1.19 GB install, a RUNNING CivicCastSupervisor, and a live API
# answering /health 200 "healthy" on :8000 -- and had had NO prior install at
# all (the "previous version" was a leftover registry value, F-01).
#
# The rule these pin: every operator-facing claim on this path is either a
# fact the installer just verified, or an attributed report from the component
# that produced it. Never an assumption, never SUCCESS for a run that did not
# succeed, and never a sentence that asserts a thing and its negation.
# --------------------------------------------------------------------------

POSTINSTALL_MACRO_BEGIN = "!macro NSIS_HOOK_POSTINSTALL"


def _postinstall_macro(source: str) -> str:
    return _slice(source, POSTINSTALL_MACRO_BEGIN, "\n!macroend")


def _code(block: str) -> str:
    """NSIS code only. A `;` comment discussing a macro is not a call to it, and
    these assertions are about what the installer DOES, not what it explains."""
    return "\n".join(line for line in block.splitlines() if not line.lstrip().startswith(";"))


def _breadcrumbs(block: str) -> list[str]:
    return re.findall(r'!insertmacro CIVICCAST_STEP "([^"]*)"', _code(block))


def _operator_claims(block: str) -> list[str]:
    """Everything the operator can actually read: dialogs and the detail pane."""
    return re.findall(
        r'!insertmacro CIVICCAST_(?:NOTICE|ALERT) "([^"]*)"|DetailPrint "([^"]*)"', _code(block)
    )


def test_m3_a_rolled_back_install_is_never_logged_as_success() -> None:
    for crumb in _breadcrumbs(_postinstall_macro(_hooks_source())):
        if "rollback" in crumb.lower() or "rolled back" in crumb.lower():
            assert "SUCCESS" not in crumb, (
                "an install whose upgrade engine rolled back is logged as SUCCESS: "
                f"{crumb!r}. SUCCESS is the word an operator, a support engineer and a "
                "fleet log scraper all key on; a run that did not succeed must not carry it"
            )


def test_m3_no_claim_asserts_a_thing_and_its_negation() -> None:
    """`InstalledVersion left at $R0, NOT ${VERSION}` renders as
    "left at 1.0.0-rc15, NOT 1.0.0-rc15" whenever the leftover marker happens
    to equal the version being installed -- which is exactly the case the
    re-walk hit, because the leftover came from installing this same build."""
    macro = _postinstall_macro(_hooks_source())
    claims = _breadcrumbs(macro) + [
        text for pair in _operator_claims(macro) for text in pair if text
    ]
    for claim in claims:
        if "$R0" in claim and "${VERSION}" in claim:
            assert not re.search(r",\s*NOT\s*\$\{VERSION\}", claim), (
                f"{claim!r} contrasts $R0 against ${{VERSION}}, but the two are equal "
                "whenever a leftover marker records the same build being installed -- the "
                'string then reads "left at X, NOT X". A claim must be true for every '
                "value its own variables can take"
            )


def test_m3_the_rollback_path_verifies_the_service_state_instead_of_asserting_it() -> None:
    """SUPERSEDED (Gate A run 33681670855, 2026-09-02): the M3-era rollback
    path used to CONTINUE past exit 10 and describe machine state at the end
    of the macro, so it had to read the service control manager rather than
    assert. That path is gone -- exit 10 under the flat installer layout
    (the only layout this bootstrap ever invokes) now fails the install
    outright via CIVICCAST_FAIL before D4 provisioning/service registration
    ever runs, so there is no live service to query and nothing here needs to
    verify a running-service claim it no longer makes."""
    macro = _postinstall_macro(_hooks_source())

    assert "healthy and still running" not in macro, (
        'the rollback path must not tell the operator an installation "is healthy and '
        'still running" -- exit 10 now fails the install before any service is registered '
        "or started, so no such claim can ever be true here"
    )
    d3_arm = _slice(macro, "${ElseIf} $0 == 10", "${ElseIf} $0 == 20")
    assert "!insertmacro CIVICCAST_FAIL" in _code(d3_arm), (
        "exit 10 (D3 clean rollback) under the flat installer layout must fail the "
        "install via CIVICCAST_FAIL -- see the Gate A run 33681670855 fix comment above "
        "the branch for why a bare continue-with-notice is unsafe under this layout"
    )
    assert "${CIVICCAST_EXIT_D3_ROLLED_BACK_FLAT}" in d3_arm


def test_m3_the_rollback_path_never_claims_the_install_itself_was_undone() -> None:
    """D3 exit 10 means the UPGRADE ENGINE reverted its OWN work. It does not
    mean setup was undone: D4 provisioning, service registration and the
    firewall rule all still run after it, and Tauri laid the program files down
    before this macro was ever entered."""
    macro = _postinstall_macro(_hooks_source())
    claims = [text for pair in _operator_claims(macro) for text in pair if text]

    for claim in claims:
        if not re.search(r"roll(ed|ing|s)? ?back|rollback|reverted", claim, re.IGNORECASE):
            continue
        assert re.search(r"engine|its own work", claim, re.IGNORECASE), (
            f"{claim!r} tells the operator something was rolled back without naming WHAT. "
            "The re-walk operator read it as the install being undone and found a "
            "complete 1.19 GB install, a running service and a live API instead. The "
            "rollback is the D3 upgrade engine reverting its own work; say that"
        )
        assert "no data was lost" not in claim.lower(), (
            f"{claim!r} claims no data was lost. Nothing here verified that, and on a "
            "machine with no prior install there was no data to speak about"
        )


def test_m3_the_rollback_arm_is_retired_in_favor_of_an_unconditional_write() -> None:
    """SUPERSEDED (Gate A run 33681670855, 2026-09-02): the `$R4 == "1"`
    rollback-report arm this test used to pin (three-way $R0-vs-${VERSION}
    wording) existed to describe a D3 clean-rollback state that CONTINUED
    past exit 10. That state is no longer reachable -- exit 10 now aborts via
    CIVICCAST_FAIL before this point in the macro, so $R4 is never set to
    "1" and the InstalledVersion write at the end of POSTINSTALL is
    unconditional (reachable only by a fully successful chain, since every
    failure branch above it aborts outright)."""
    macro = _postinstall_macro(_hooks_source())
    executable = _code(macro)

    assert '$R4 == "1"' not in executable, (
        "the retired rollback-report arm must not reappear -- exit 10 fails closed now, "
        "so there is nothing left for a $R4 latch to gate"
    )
    assert 'WriteRegStr HKLM "Software\\CivicCast\\Native" "InstalledVersion" "${VERSION}"' in (
        executable
    ), "the InstalledVersion write must still happen, unconditionally, at the end of POSTINSTALL"


# --------------------------------------------------------------------------
# chain F-17: the D2 install-time re-verification steps write a `begin`
# breadcrumb and then, on success, NOTHING else -- the newcomer walkthrough of
# build dd7f835f (evidence/install-progress.log, evidence/FINDINGS-rewalk-
# dd7f835f.md) shows exactly this:
#
#   step d2-verify-server-binaries: begin
#   step d2-verify-app-payload: begin
#   step d3-engine: begin (old=1.0.0-rc15)
#
# -- with 107 seconds between the app-payload begin and the next breadcrumb,
# and no result line for either D2 step anywhere in between. An operator
# reading the log cannot tell whether either verification ran, passed, or
# hung. Every other instrumented step in this file (vc-redist, stage-packs,
# d4-provision, d4-service-registration, d4-firewall-rule) pops its child's
# exit code and immediately writes a "step X: returned $0" breadcrumb BEFORE
# branching on it, so the log carries a result unconditionally, on both the
# success and the failure path (the timestamp on that line, against the
# timestamp on "begin", is how every other step in this log already conveys
# elapsed duration -- there is no separate duration field anywhere in this
# file). The two D2 steps must follow the same contract.
# --------------------------------------------------------------------------

D2_SERVER_BINARIES_BEGIN = '!insertmacro CIVICCAST_STEP "step d2-verify-server-binaries: begin"'
D2_APP_PAYLOAD_BEGIN = '!insertmacro CIVICCAST_STEP "step d2-verify-app-payload: begin"'
D2_APP_PAYLOAD_DEST_COMMENT = "The native-app-payload pack's extraction destination is BRIDGED by"
D2_FFMPEG_DEST_COMMENT = (
    "The native-ffmpeg-runtime pack's extraction destination is BRIDGED the same"
)


def _d2_server_binaries_step(source: str) -> str:
    """The whole d2-verify-server-binaries step, begin through its own branch."""
    return _slice(source, D2_SERVER_BINARIES_BEGIN, D2_APP_PAYLOAD_DEST_COMMENT)


def _d2_app_payload_step(source: str) -> str:
    """The whole d2-verify-app-payload step, begin through its own branch."""
    return _slice(source, D2_APP_PAYLOAD_BEGIN, D2_FFMPEG_DEST_COMMENT)


def test_f17_d2_server_binaries_verification_logs_a_result_before_branching_on_it() -> None:
    step = _d2_server_binaries_step(_hooks_source())

    pop_at = step.find("Pop $0")
    assert pop_at != -1, "the d2-verify-server-binaries step no longer pops the child's exit code"
    branch_at = step.find("${If} $0 != 0")
    assert branch_at != -1, "the d2-verify-server-binaries step no longer branches on the exit code"

    result_marker = '!insertmacro CIVICCAST_STEP "step d2-verify-server-binaries: returned $0"'
    result_at = step.find(result_marker)
    assert result_at != -1, (
        "the d2-verify-server-binaries step writes a 'begin' breadcrumb and then, on "
        "success, nothing else to install-progress.log. The newcomer walkthrough of "
        "dd7f835f (evidence/install-progress.log, finding F-17) shows exactly this -- "
        "'step d2-verify-server-binaries: begin' with no matching result line -- so an "
        "operator reading the log cannot tell whether verification ran, passed, or hung"
    )
    assert pop_at < result_at < branch_at, (
        "the result breadcrumb must be written immediately after popping the exit code "
        "and BEFORE the success/failure branch, exactly like vc-redist / stage-packs / "
        "d4-provision -- so the log carries a result unconditionally on both the success "
        "and the failure path, not only when CIVICCAST_FAIL happens to fire"
    )


def test_f17_d2_app_payload_verification_logs_a_result_before_branching_on_it() -> None:
    step = _d2_app_payload_step(_hooks_source())

    pop_at = step.find("Pop $0")
    assert pop_at != -1, "the d2-verify-app-payload step no longer pops the child's exit code"
    branch_at = step.find("${If} $0 != 0")
    assert branch_at != -1, "the d2-verify-app-payload step no longer branches on the exit code"

    result_marker = '!insertmacro CIVICCAST_STEP "step d2-verify-app-payload: returned $0"'
    result_at = step.find(result_marker)
    assert result_at != -1, (
        "the d2-verify-app-payload step writes a 'begin' breadcrumb and then, on success, "
        "nothing else to install-progress.log. The newcomer walkthrough of dd7f835f "
        "(evidence/install-progress.log, finding F-17) shows 107 seconds between this "
        "step's begin and the next breadcrumb with no result line in between -- an "
        "operator reading the log cannot tell whether verification ran, passed, or hung"
    )
    assert pop_at < result_at < branch_at, (
        "the result breadcrumb must be written immediately after popping the exit code "
        "and BEFORE the success/failure branch, exactly like vc-redist / stage-packs / "
        "d4-provision -- so the log carries a result unconditionally on both the success "
        "and the failure path"
    )


def test_m3_no_claim_about_machine_state_is_made_before_the_state_exists() -> None:
    """D3 runs BEFORE D4 provisioning, service registration and the firewall
    rule. Anything the D3 branch says about what is running on this machine is
    a claim about a state that has not happened yet."""
    macro = _postinstall_macro(_hooks_source())
    d3_arm = _slice(macro, "${ElseIf} $0 == 10", "${ElseIf} $0 == 20")
    claims = [text for pair in _operator_claims(d3_arm) for text in pair if text]

    for claim in claims:
        assert not re.search(r"still running|is healthy|no data was lost", claim, re.IGNORECASE), (
            f"{claim!r} describes machine state from inside the D3 branch, which runs "
            "before D4 provisioning, service registration and the firewall rule have "
            "happened. That claim belongs at the end of the macro, where the state exists "
            "and can be read"
        )
    assert not any("CIVICCAST_NOTICE" in line for line in _code(d3_arm).splitlines()), (
        "the D3 rollback branch raises the operator dialog before setup has finished. "
        "The dialog must be raised at the end, from verified final state"
    )


# --------------------------------------------------------------------------
# DELTA-M-02 (rewalk-de3aaf6f, 2026-08-02): a fresh install must not print a
# raw "ERROR:" line while stopping a bootstrap process that was never there
# --------------------------------------------------------------------------

BOOTSTRAP_STOP_BEGIN = '!insertmacro CIVICCAST_STEP "preinstall: stopping existing bootstrap"'
PREINSTALL_DONE = '!insertmacro CIVICCAST_STEP "preinstall: done"'


def _bootstrap_stop_step(source: str) -> str:
    """The whole 'stopping existing bootstrap' preinstall step."""
    return _slice(source, BOOTSTRAP_STOP_BEGIN, PREINSTALL_DONE)


def test_delta_m02_the_bootstrap_taskkill_never_runs_on_a_fresh_install() -> None:
    """Evidence 016b-error-line-crop.png (rewalk-de3aaf6f): a genuinely fresh
    install -- no "$INSTDIR\\CivicCast Native.exe" left behind by a prior
    install -- ran `taskkill.exe /IM "CivicCast Native.exe" /T /F`
    unconditionally anyway. Under this installer's execution context that
    surfaced as a raw "ERROR: The user name or password is incorrect." line
    in the operator-visible details pane (nsExec::ExecToLog echoes the
    child's stdout/stderr verbatim), immediately after "Stopping the existing
    CivicCast Native bootstrap before installation...", right before the
    install went on to complete successfully -- alarming and confusing.

    The taskkill call must be gated behind the exact same existence check the
    sc.exe-based service-stop step immediately above it already uses -- there
    is nothing to stop on a fresh install, so nothing should be attempted."""
    step = _bootstrap_stop_step(_hooks_source())

    gate_at = step.find('${If} ${FileExists} "$INSTDIR\\CivicCast Native.exe"')
    taskkill_at = step.find("taskkill.exe")
    assert gate_at != -1, (
        "the 'stopping existing bootstrap' step no longer opens with a "
        '${If} ${FileExists} "$INSTDIR\\CivicCast Native.exe" gate -- taskkill must never '
        "run against a target that provably does not exist yet"
    )
    assert taskkill_at != -1, "the step no longer stops the bootstrap process at all"
    assert gate_at < taskkill_at, (
        "the FileExists gate must come BEFORE the taskkill call, not after -- taskkill "
        "must be inside the gated arm, never reached unconditionally"
    )

    else_at = step.find("${Else}")
    endif_at = step.find("${EndIf}")
    assert else_at != -1 and endif_at != -1, (
        "the step must have both a gated arm (exe present: stop it) and an ${Else} arm "
        "(exe absent: nothing to stop) closed by ${EndIf}"
    )
    assert gate_at < taskkill_at < else_at < endif_at, (
        "taskkill must sit strictly inside the ${If}...${Else} arm -- if it runs after "
        "${Else} or after ${EndIf} it is unconditional again"
    )


def test_delta_m02_the_fresh_install_arm_is_silent_not_a_raw_child_invocation() -> None:
    """The safety property: the ${Else} arm (fresh install, nothing to stop)
    must say so in plain English and must never itself invoke nsExec/taskkill
    -- otherwise the same raw-ERROR hazard just moves to the other branch."""
    step = _bootstrap_stop_step(_hooks_source())

    else_at = step.find("${Else}")
    endif_at = step.find("${EndIf}")
    assert else_at != -1 and endif_at != -1
    fresh_install_arm = step[else_at:endif_at]

    assert "nsExec" not in fresh_install_arm, (
        "the fresh-install arm must not run any child process at all -- there is nothing "
        "to stop, so nothing should be executed"
    )
    assert "taskkill" not in fresh_install_arm, (
        "the fresh-install arm must not invoke taskkill -- that is exactly the "
        "unconditional call this fix removes from the fresh-install path"
    )
    assert "DetailPrint" in fresh_install_arm, (
        "the fresh-install arm must say something informational in the details pane -- "
        "silence there would be as confusing as the raw ERROR line it replaces"
    )


def test_delta_m02_a_genuine_taskkill_failure_still_reaches_the_details_pane() -> None:
    """Not fixed by hiding real errors: when a prior install DID leave the exe
    behind, the taskkill call and its output must still be logged exactly as
    before -- only the fresh-install case (nothing to stop) is now silent
    about the raw child output."""
    step = _bootstrap_stop_step(_hooks_source())

    gate_at = step.find('${If} ${FileExists} "$INSTDIR\\CivicCast Native.exe"')
    else_at = step.find("${Else}")
    assert gate_at != -1 and else_at != -1
    prior_install_arm = step[gate_at:else_at]

    assert "nsExec::ExecToLog" in prior_install_arm, (
        "when a prior install left the exe behind, taskkill's output must still be "
        "captured through nsExec::ExecToLog exactly as before -- this fix must not "
        "suppress a genuine stop attempt or its real output"
    )
    assert 'taskkill.exe /IM "CivicCast Native.exe" /T /F' in prior_install_arm, (
        "the real stop command itself must be unchanged"
    )


# --------------------------------------------------------------------------
# 2026-09-02 (owner decision): the installer now EMBEDS the signed station
# index and the tiny `core` pack as Tauri bundle.resources, so a
# download-only install/upgrade of setup.exe ALONE can activate. Before this,
# d4-activate-station imported only "$EXEDIR\station\station-index.json" and
# failed the install outright when it was absent -- and its dialog offered a
# remedy ("publish one alongside the installer") that is release-engineering
# work, not something the operator standing at the machine can perform.
#
# Same class of defect as chain F above: a fail-loud dialog naming a remedy
# outside the operator's reach. Pinned here, next to chain F, for that reason.
# --------------------------------------------------------------------------

ACTIVATE_STATION_BEGIN = '!insertmacro CIVICCAST_STEP "step d4-activate-station: begin"'
SERVICE_REGISTRATION_BEGIN = '!insertmacro CIVICCAST_STEP "step d4-service-registration: begin"'


def _activate_station_step(source: str) -> str:
    return _slice(source, ACTIVATE_STATION_BEGIN, SERVICE_REGISTRATION_BEGIN)


def _activate_station_fail_messages(step: str) -> tuple[str, ...]:
    messages = re.findall(
        r"!insertmacro CIVICCAST_FAIL \$\{CIVICCAST_EXIT_D4_ACTIVATION\} \"(.*?)\"\n",
        step,
        re.DOTALL,
    )
    assert messages, "the activation step no longer fails loud through CIVICCAST_FAIL"
    return tuple(messages)


def test_station_activation_tries_the_kit_bundle_before_the_embedded_index() -> None:
    """Order is the whole contract. An air-gapped station that carried a full
    signed bundle to the machine on a stick must keep using THAT bundle --
    its component packs live in the same media directory the index sits in
    (native_distribution.rs::acquire_station_distribution derives media_root
    from the index's parent). Preferring the embedded copy would silently
    send that station down the pack-cache path instead, on a machine whose
    cache is empty."""
    step = _activate_station_step(_hooks_source())

    exedir = r'IfFileExists "$EXEDIR\station\station-index.json"'
    instdir = r'IfFileExists "$INSTDIR\station\station-index.json"'
    assert exedir in step, "the USB-kit index must still be probed"
    assert instdir in step, "the embedded index must be probed as a fallback"
    assert step.index(exedir) < step.index(instdir), (
        "the kit's own bundle must be preferred over the embedded index"
    )


def test_station_activation_only_fails_closed_when_neither_index_exists() -> None:
    """The K1 invariant survives: a missing index still aborts the install
    (never a silent success that leaves a station which can never activate).
    What changed is only WHEN -- both sources must be exhausted first."""
    step = _activate_station_step(_hooks_source())

    no_index_arm = step.split("civiccast_activate_station_no_index:", 1)
    assert len(no_index_arm) == 2, (
        "there must be a distinct branch for 'no index at either location' -- "
        "otherwise the two sources are not really both tried"
    )
    arm = no_index_arm[1].split("civiccast_activate_station_ran:", 1)[0]
    assert "!insertmacro CIVICCAST_FAIL ${CIVICCAST_EXIT_D4_ACTIVATION}" in arm, (
        "no index anywhere must still abort the install through CIVICCAST_FAIL"
    )
    assert "!insertmacro CIVICCAST_ALERT" not in arm


def test_station_activation_failure_names_a_remedy_the_operator_can_perform() -> None:
    """chain-F rule, applied to this dialog: 'publish one alongside the
    installer' is release-engineering work, not an action available to the
    volunteer standing at the station. The replacement must name things the
    operator can actually do."""
    messages = _activate_station_fail_messages(_activate_station_step(_hooks_source()))
    combined = "\n".join(messages)

    assert "publish one alongside the installer" not in combined, (
        "the old dialog told the operator to publish a station bundle -- that is a "
        "build-pipeline action, not an operator action"
    )
    assert re.search(r"release page", combined, re.IGNORECASE), (
        "the operator must be told where a good setup.exe comes from"
    )
    assert re.search(r"\bkit\b", combined, re.IGNORECASE), (
        "the operator must be told the other real remedy: copy the full CivicCast kit "
        "folder (setup.exe together with its station folder) onto this machine"
    )
    for message in messages:
        assert "installer log" in message, (
            "every activation failure dialog must keep pointing at the installer log"
        )


def test_station_activation_logs_which_index_source_it_used() -> None:
    r"""An install nobody watched is diagnosed from
    $COMMONPROGRAMDATA\CivicCast\install-progress.log alone. With two possible
    sources, 'activation failed' is not diagnosable unless the log says which
    index was imported."""
    step = _activate_station_step(_hooks_source())

    assert "step d4-activate-station: source EXEDIR" in step
    assert "step d4-activate-station: source INSTDIR" in step
    assert "step d4-activate-station: no station index at" in step, (
        "the neither-present case must also name itself in the breadcrumb log"
    )
