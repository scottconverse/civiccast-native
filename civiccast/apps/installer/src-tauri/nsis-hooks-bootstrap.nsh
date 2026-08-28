; SPDX-License-Identifier: Apache-2.0
; Copyright (c) The CivicCast Authors
;
; Small native bootstrap hooks. The multi-gigabyte station payload is supplied
; only through signed .ccpack files and is never embedded in this NSIS binary.
;
; This is the ONE LIVE native installer hook file: `tauri.native.conf.json`
; (`bundle.windows.nsis.installerHooks`) references this file, and
; `tests/policy/test_native_installer_identity.py` pins that reference on the
; EFFECTIVE (deep-merged) native config. `scripts/build_native_bootstrap.py`'s
; `validate_native_bootstrap_config` is a hard gate requiring exactly this
; file name plus `bundle.resources == {"resources/vc_redist.x64.exe":
; "vc_redist.x64.exe"}` -- no embedded multi-gigabyte payload, ever.
;
; WP2 hook-migration (2026-07-30): POSTINSTALL below now carries the D2/D4
; install-time chain that previously sat unreachable in the retired
; `nsis-hooks-native.nsh` (that file's own header, and two independent same-
; day evidence trails -- `wp2-pack-delivery-reconciliation-2026-07-29.md` and
; `wp2-hook-build-wiring-2026-07-30.md` -- had disclosed it was fully built
; and unit-tested but wired into NO live build target). The coordinator
; decided this file, not `nsis-hooks-native.nsh`, is where that chain belongs
; (folding it in here rather than re-pointing the Tauri config, which two
; policy/builder tests pin against). Full migration map, adaptation
; rationale, and what was deliberately NOT migrated (and why):
; .agent-runs/native-windows/ws5-installer/evidence/wp2-hook-migration-2026-07-30.md
;
; Ordering summary (bootstrap-native: packs deliver runtime bytes, so
; verification, the D3 engine, and provisioning all run AFTER pack staging,
; not before, unlike the retired file's embedded-payload ordering):
;   stage required component packs -> D2 re-verify the extracted pack tree
;   -> D3 journaled install/upgrade engine -> D4 PostgreSQL provisioning
;   -> D4 service registration + firewall rule. Every step fails loud on
;   failure via CIVICCAST_FAIL: a silent-safe operator report, a
;   step-identifying process exit code, and a real NSIS Abort so the wizard
;   reports failure instead of running Tauri's unconditional success page
;   (AUDIT-001).
;
; WP2 app-payload-pack gap closure (2026-07-30): the gap named below is now
; CLOSED. `scripts/build_native_app_payload_pack.py` packages the WP-6
; application-payload TREE (CPython 3.12 embeddable + civiccast + hash-pinned
; deps) as a signed `native-app-payload` component pack;
; `native_pack_staging::DEFAULT_REQUIRED_COMPONENTS` now demands it
; (`["native-server-binaries", "native-app-payload"]`), and
; `native_pack_staging::ensure_pack_extracted` special-cases its extraction
; destination to `$INSTDIR\runtime` (NOT the generic
; `packs\native-app-payload\payload\` convention every other component pack
; uses) so `$INSTDIR\runtime\python.exe` -- the interpreter both the D4
; provisioning and D4 service-registration CLI subcommands below shell out to
; internally (`native_service_registration.rs`) -- now exists after pack
; staging completes. See `wp2-app-payload-pack-2026-07-30.md` for the full
; layout-bridge rationale and build/verification evidence.
;
; WP2 D3 rehoming (2026-07-30): the app-payload-pack gap closure above is what
; made the D3 install/upgrade engine (`civiccast.native.upgrade`) invocable at
; all -- `wp2-hook-migration-2026-07-30.md` §2 explicitly left it unwired
; because `$INSTDIR\runtime\python.exe` did not exist yet. It is now wired,
; as a THIN SHELL exactly like the retired block's own invocation (direct
; `nsExec::ExecToLog` of the embedded interpreter, no Rust CLI subcommand
; wrapper, unlike the D4 steps beside it): reads the currently-installed ARP
; version, branches on the retired block's own 5-way exit-code contract
; (commit / clean rollback / halted rollback needing operator recovery /
; refused non-restorable migration / unexpected fault), and passes
; `--payload-source "$INSTDIR\runtime"`. POSITION (coordinator decision): runs
; directly after the D2 pack-tree verification above and BEFORE D4
; provisioning/service registration below -- tree management (junction flip,
; migration, health gate, rollback) must commit on the tree before
; provisioning/service-build acts on it. See
; `wp2-d3-rehoming-2026-07-30.md` for the retired-block diff comparison, the
; exit-contract table, and the one real adaptation this position forces (the
; `--database-url` value D3 receives is now the registry's CURRENT value,
; read BEFORE D4 provisioning below can write a fresh one -- empty on a
; first-ever install, unlike the retired ordering where D4 always ran first).

; Durable install-progress breadcrumbs. DetailPrint output is invisible in
; silent installs and lost when the process dies, which made the run-3/run-4
; Sandbox hang (setup alive, no children, no observable position in the
; chain) undiagnosable from outside. Every chain step below writes a line to
; $COMMONPROGRAMDATA\CivicCast\install-progress.log BEFORE and AFTER it
; runs, so the last line always names the step in flight. This file is also
; what the fault dialogs' "see the installer log" now concretely means for
; operators. Uses $9 (saved/restored) to avoid disturbing chain registers.
; Timestamped (P3 instrumentation, 2026-07-31 run-18 forensic diagnosis): a
; breadcrumb line alone proves ORDER, not TIMING -- diagnosing a hang (this
; file's own header names the run-3/run-4 Sandbox hang this log format was
; built to make diagnosable) needs to know how long the install sat on its
; LAST logged step, which the untimestamped format could not answer without
; correlating against a process-exit timestamp from outside the file.
; ${__DATE__}/${__TIME__} are COMPILE-time constants baked into this
; installer once at build time -- every line would carry the SAME wrong
; value -- so they are explicitly not usable here. ${GetTime} (FileFunc.nsh;
; already !include'd by installer.nsi at the top of the generated script,
; strictly before this file's own !include site, and again strictly before
; any !insertmacro CIVICCAST_STEP call site, so it is always in scope) is
; the least invasive runtime option available: it is NSIS's own official
; time helper, built on the standard LOGICLIB "artificial function" calling
; convention already used elsewhere in this toolchain, and it does not
; disturb $0/$1 externally by design (that convention's own internal
; Exch-based save/restore is the entire point of it) -- unlike a raw
; `System::Call kernel32::GetLocalTime` probe, which would need hand-built
; SYSTEMTIME pointer/struct arithmetic for no accuracy benefit at this log's
; one-second granularity.
;
; Every existing CIVICCAST_STEP call site inherits this prefix automatically
; (this is the ONE place the format is produced). The prefix is a PREFIX,
; not a replacement -- every previously-logged token (`step d4-provision:
; returned 0`, `REFUSED`, `step d3-engine: begin (old=...)`, etc.) still
; appears verbatim later in the same line. Every known consumer matches with
; an unanchored substring/regex search (grep confirms:
; C:\CivicCastProof\sandbox-shared\gauntlet-run18\install_gauntlet.ps1 uses
; PowerShell `-match` with no `^`/`$` anchor at every one of its six
; breadcrumb-matching call sites -- 'REFUSED', 'step d4-provision: returned
; 0', and the regex-escaped 'step d3-engine: begin \(old=...\)' among them --
; and a repo-wide search found no OTHER consumer of install-progress.log at
; all), so a leading `[timestamp] ` prefix cannot break any of them. See
; tests/policy/test_native_installer_identity.py for the pin covering the
; prefix shape and the BEGIN line above.
;
; Registers: $2-$8 hold ${GetTime}'s seven required outputs (day, month,
; year, day-of-week [captured but unused -- this log format has never
; carried a weekday and adding one is not this fix's job], hour, minute,
; second). Chosen because those seven are used NOWHERE ELSE in this file
; (confirmed by grep) -- unlike $0, $1, $9, and $R0-$R4, which ARE live
; inside various CIVICCAST_STEP callers' own ${TEXT} argument (e.g.
; "...returned $0", "...(old=$R0)", "...$CIVICCAST_TEARDOWN_EXIT") and must
; still hold their CALLER's value, unmodified, by the time this macro's own
; FileWrite resolves that same ${TEXT} text. Still Push/Pop-saved so the
; CALLER's $2-$8 are restored after the macro -- but the Push/Pop does NOT
; make $2-$9 usable INSIDE a ${TEXT} argument: ${TEXT} expands textually at
; the FileWrite, which runs AFTER ${GetTime} has clobbered $2-$8 and after
; the file handle landed in $2 (measured 2026-07-31: a probe site logging
; "$2...$9" printed the timestamp fields and the handle, not the caller's
; values). Never reference $2-$9 in breadcrumb text.
;
; SIDE EFFECT (measured 2026-07-31): ${GetTime} routes through FileFunc's
; GetTime_, which calls ClearErrors unconditionally -- so EVERY
; CIVICCAST_STEP call clears the NSIS error flag. All current call sites
; were traced and none read the flag across a STEP, but do not place a
; STEP between a SetErrors/${GetOptions} and its ${If} ${Errors} check.
;
; ===========================================================================
; HONEST INSTALL-SIZE METADATA (F-10/F-12, 2026-08-01, FINDINGS-rewalk-
; dd7f835f.md): the wizard's "Choose Install Location" page showed "Space
; required: 237.0 MB", and Windows' Installed apps showed 37.1 MB, against a
; real ~1.19 GB on-disk install (plus up to ~12.8 GB of first-run
; downloads). Both numbers came from NSIS/Tauri machinery that can only see
; what THIS installer embeds via `File` statements (the bootstrap exe, the
; VC++ redistributable, the WebView2 offline installer) -- it has no way to
; know about the native component packs the POSTINSTALL chain below stages
; via external `nsExec` calls, which is most of the real footprint. Two
; separate, complementary fixes, because the two numbers are needed at two
; different times:
;
; 1. The pre-install "Space required" estimate (MUI_PAGE_DIRECTORY, shown
;    BEFORE anything is staged, so it cannot be measured -- it can only be
;    declared). NSIS's documented mechanism for exactly this case is
;    `AddSize` ("increases... the size used to calculate the estimated
;    space required... for actions the installer performs that increase
;    install size beyond what NSIS can auto-detect", e.g. downloads/
;    extractions done by an external process): see
;    CIVICCAST_ADDSIZE_PACKS_KB below and its use in NSIS_HOOK_PREINSTALL.
;    DERIVATION: 5,400,000 KB is the conservative current budget for all four
;    raw sidecars plus their extracted trees. The candidate workflow sums the
;    actual `pack_bytes` + `payload_bytes` from every signed builder report and
;    fails before packaging if that exact build exceeds this declaration, so
;    source or manifest growth cannot silently make the wizard understate the
;    required space. The post-install EstimatedSize remains measured from the
;    real tree below.
; 2. The ARP "Installed apps" size (EstimatedSize, read by Windows AFTER
;    install completes) does not have this before/after problem -- by the
;    time NSIS_HOOK_POSTINSTALL reaches its final steps, every pack has
;    actually been staged and D2-verified, so the true footprint can be
;    MEASURED instead of estimated. See the ${GetSize} "$INSTDIR" call near
;    the end of NSIS_HOOK_POSTINSTALL, which overwrites Tauri's own (tiny,
;    File-statement-only) EstimatedSize write with the real number --
;    self-correcting on every future build, unlike a hardcoded constant.
; ===========================================================================
!define CIVICCAST_ADDSIZE_PACKS_KB "5400000"

; MUI_DIRECTORYPAGE_TEXT_TOP is MUI2's documented mechanism for adding
; explanatory prose above the directory browse box (must be !define'd
; before `!insertmacro MUI_PAGE_DIRECTORY` runs in the generated
; installer.nsi; this whole file is !include'd near the top of that script,
; strictly before that macro, so a file-scope !define here always lands in
; time). Used here, rather than a custom nsDialogs page, to state plainly
; on this SAME screen that more will download later and where its real size
; will be shown -- so "Space required" is not read as the whole story.
!define MUI_DIRECTORYPAGE_TEXT_TOP "CivicCast (Native) needs the space shown below on this drive for the program itself. After Setup finishes, the CivicCast setup wizard downloads additional components (captions and AI models) separately -- their sizes are shown individually, before anything downloads, on that wizard's own screen."

!macro CIVICCAST_STEP TEXT
  Push $9
  Push $2
  Push $3
  Push $4
  Push $5
  Push $6
  Push $7
  Push $8
  ${GetTime} "" "L" $2 $3 $4 $5 $6 $7 $8
  ; $2=day $3=month $4=year $5=day-of-week (unused) $6=hour $7=minute $8=second
  StrCpy $9 "[$4-$3-$2 $6:$7:$8] "
  ; F-14 (carried, rewalk-de3aaf6f): this CreateDirectory used to run
  ; unconditionally on EVERY breadcrumb, including the last two calls in
  ; NSIS_HOOK_POSTUNINSTALL -- so a completed uninstall's final two visible
  ; detail-pane lines were "Create folder: C:\ProgramData\CivicCast" (NSIS
  ; logs that line for CreateDirectory whether or not the directory already
  ; existed), reading as the uninstaller re-creating the very data root it
  ; just finished tearing down. $COMMONPROGRAMDATA\CivicCast is preserved for
  ; the product's entire lifetime after first install (NSIS_HOOK_POSTUNINSTALL's
  ; own header: "deliberately NEVER touched by this removal, or by anything
  ; else in this macro"), so by the time any uninstall breadcrumb fires, this
  ; CreateDirectory is always redundant -- it exists ONLY to cover the very
  ; first breadcrumb of a fresh install, before the directory has ever been
  ; made. Guard it so it is a genuine no-op (and logs nothing) once the
  ; directory is already there, same FileExists-guard pattern this file
  ; already uses for the uninstall.exe/$INSTDIR reboot-delete guard above.
  ${IfNot} ${FileExists} "$COMMONPROGRAMDATA\CivicCast"
    CreateDirectory "$COMMONPROGRAMDATA\CivicCast"
  ${EndIf}
  FileOpen $2 "$COMMONPROGRAMDATA\CivicCast\install-progress.log" a
  ${If} $2 != ""
    FileSeek $2 0 END
    FileWrite $2 "$9${TEXT}$\r$\n"
    FileClose $2
  ${EndIf}
  Pop $8
  Pop $7
  Pop $6
  Pop $5
  Pop $4
  Pop $3
  Pop $2
  Pop $9
!macroend

; Silent-safe failure reporting. An NSIS MessageBox BLOCKS even under `/S`,
; waiting for a click no unattended install can give -- the installer stays
; alive with no children and no visible progress, which is exactly the
; "hang" that cost Sandbox matrix runs 3-6 (the D4 service-registration
; failure path). A full audit of this file found 21 MessageBox sites and
; ZERO silent guards. Every non-interactive failure report now routes
; through this macro: silent installs get the breadcrumb + DetailPrint and
; keep unwinding (the caller still SetErrors and Goto ...done), interactive
; installs still get the operator dialog. The ONE deliberate exception is
; the MB_YESNO ActiveRuntime ownership-transfer prompt in PREUNINSTALL:
; that asks a question silent mode cannot answer, so it keeps its dialog
; and remains an owner-facing policy question (a silent uninstall of the
; active runtime while the WSL product is present must fail loud rather
; than guess an answer).
!macro CIVICCAST_ALERT TEXT
  !insertmacro CIVICCAST_STEP "ALERT: ${TEXT}"
  DetailPrint "${TEXT}"
  ${IfNot} ${Silent}
    MessageBox MB_OK|MB_ICONSTOP "${TEXT}"
  ${EndIf}
!macroend

; Silent-safe OPERATOR NOTICE (CRITICAL fix, 2026-07-30 adversarial review) --
; structurally identical delivery to CIVICCAST_ALERT (breadcrumb + DetailPrint
; always; a dialog only when NOT silent) but a DISTINCT macro on purpose, for
; a DISTINCT situation: an operator-important outcome on a path that
; CONTINUES BY DESIGN and is NOT a failure (today's only caller is the D3
; clean-rollback branch in NSIS_HOOK_POSTINSTALL -- the D3 engine's own
; contract leaves the machine healthy and running on the previous version, so
; the install did not fail; what the operator needs to know is that the
; upgrade specifically did not take effect).
;
; This macro must NEVER be used to report an actual failure. It deliberately
; carries no SetErrorLevel and no Abort (see
; test_bootstrap_postinstall_every_failure_branch_actually_fails_the_install
; in tests/policy/test_native_installer_identity.py, which asserts this
; macro's body contains neither), so it is structurally incapable of
; reproducing the AUDIT-001 shape -- a report that lets a real failure keep
; going. That test also forbids POSTINSTALL from ever using a BARE
; CIVICCAST_ALERT for exactly that reason: every failure there must route
; through CIVICCAST_FAIL (which aborts); every non-failure notice routes
; through this macro instead. Use MB_ICONINFORMATION (not MB_ICONSTOP) so an
; interactive operator can tell at a glance this is not an error dialog.
!macro CIVICCAST_NOTICE TEXT
  !insertmacro CIVICCAST_STEP "NOTICE: ${TEXT}"
  DetailPrint "${TEXT}"
  ${IfNot} ${Silent}
    MessageBox MB_OK|MB_ICONINFORMATION "${TEXT}"
  ${EndIf}
!macroend

; Fail the install for real (AUDIT-001, Blocker, 2026-07-30).
;
; Before this macro, every POSTINSTALL failure branch below did SetErrors +
; alert + `Goto ...done` and nothing else. NSIS's `.onInstFailed` is documented
; to fire only on a failed extraction or an explicit `Abort` -- `SetErrors` is
; NOT a trigger -- and Tauri's generated installer.nsi defines no
; `.onInstFailed` at all while running `.onInstSuccess` unconditionally. So a
; machine whose provisioning, service registration, or pack verification had
; just failed still showed the wizard's "installation complete" page, still
; carried a healthy Add/Remove Programs entry, and still returned exit code 0
; to any deployment tool driving it silently.
;
; The shape below is not inferred from documentation; it was measured on this
; product's own makensis. Evidence:
; .agent-runs/native-windows/ws5-installer/evidence/nsis-errorlevel-probe/
;   SetErrorLevel alone   -> custom exit code, but .onInstSuccess STILL runs
;   Abort alone           -> .onInstFailed runs, but the generic exit code 2
;   SetErrorLevel + Abort -> custom exit code AND .onInstFailed  <- what we want
;
; CODE is this product's own step-identifying exit code (the table below), so
; an unattended caller can tell WHICH step failed from the process exit code
; alone -- the only signal a silent install emits.
;
; What this deliberately does NOT do: retract Tauri's Add/Remove Programs
; entry or delete the uninstaller it wrote at installer.nsi:649/670-689,
; before this hook ever runs. Both were considered and rejected on evidence:
;   * UninstallString is the ONLY way Windows' own Apps & Features UI can
;     invoke our uninstaller, and the uninstaller is now the thing that
;     actually cleans a half-installed machine (service, firewall rule,
;     recursive tree removal). Deleting the ARP entry would strand a
;     multi-gigabyte tree with no discoverable way to remove it.
;   * scripts/wait_native_uninstall_cleanup.ps1 decides an uninstall finished
;     by matching ARP DisplayName == "CivicCast (Native)" and finding none.
;     Deleting or renaming the entry on a FAILED install would make that
;     watcher report a clean machine that is not clean.
; So a failed install stays visible and removable; what changes is that it no
; longer claims to have succeeded.
!macro CIVICCAST_FAIL CODE TEXT
  SetErrors
  !insertmacro CIVICCAST_ALERT "${TEXT}"
  !insertmacro CIVICCAST_STEP "postinstall: FAILED, aborting with exit code ${CODE}"
  SetErrorLevel ${CODE}
  Abort
!macroend

; POSTINSTALL failure exit codes. Deliberately in a band of their own: the
; product's own CLI contract codes (40, 70, 73, 75, 76, 79, 81) and the D3
; engine's phase codes (0/10/20/30) travel through nsExec as $0 and must stay
; distinguishable from the installer process's own exit code.
!define CIVICCAST_EXIT_PACK_DELIVERY        110
!define CIVICCAST_EXIT_D2_SERVER_BINARIES   111
!define CIVICCAST_EXIT_D2_APP_PAYLOAD       112
!define CIVICCAST_EXIT_D3_HALTED            113
!define CIVICCAST_EXIT_D3_REFUSED           114
!define CIVICCAST_EXIT_D3_FAULT             115
!define CIVICCAST_EXIT_D4_PROVISION_FAILED  116
!define CIVICCAST_EXIT_D4_PROVISION_FAULT   117
!define CIVICCAST_EXIT_D4_SERVICE           118
!define CIVICCAST_EXIT_D4_FIREWALL          119

; INSTALL-ONLY REFUSAL (owner decision, 2026-07-30 beta): the sole code in
; this band NOT raised from POSTINSTALL -- it fires from NSIS_HOOK_PREINSTALL,
; before any destructive step, when a live existing install is detected. See
; that macro's header comment for the two honest signals this checks and why
; InstalledVersion/DatabaseUrl are deliberately never consulted.
!define CIVICCAST_EXIT_INSTALL_OVER_EXISTING 120

; D2 re-verification of the third required component pack,
; native-ffmpeg-runtime. Given its own code rather than folded into
; ${CIVICCAST_EXIT_D2_SERVER_BINARIES}/${CIVICCAST_EXIT_D2_APP_PAYLOAD} for
; the same reason those two are distinct: the exit code is the only signal a
; support log carries about WHICH pack failed to re-verify.
!define CIVICCAST_EXIT_D2_FFMPEG_RUNTIME     121
!define CIVICCAST_EXIT_D2_OLLAMA_RUNTIME     122

; K1 fix: flat-layout station activation (--civiccast-activate-station),
; run between D4 provisioning and D4 service registration. Its own code for
; the same reason every other D4 step has one: the exit code is the only
; signal a support log carries about WHICH step failed.
!define CIVICCAST_EXIT_D4_ACTIVATION         123

; Carries the --civiccast-teardown-native-state CLI's exit code from
; NSIS_HOOK_PREUNINSTALL (where the teardown call must run -- see that
; macro's header comment for why) to NSIS_HOOK_POSTUNINSTALL (where the
; recursive tree-removal gate this result controls must stay -- it can only
; run after Tauri's own file deletion). A file-scope Var, not a numbered
; register ($0/$R0/...), is the correct channel: registers are reused by
; Tauri's own generated uninstall-section code that runs BETWEEN these two
; macros (CheckIfAppIsRunning, the shortcut/registry cleanup, etc.), so they
; are not guaranteed to still hold the teardown's result by the time
; POSTUNINSTALL reads it. Left at its NSIS default (empty string) until
; PREUNINSTALL sets it; POSTUNINSTALL treats an empty value (PREUNINSTALL
; somehow did not run) the same as exit code 82 -- fail CLOSED, refusing to
; delete a tree a still-running service may depend on, rather than assuming
; it is safe.
Var CIVICCAST_TEARDOWN_EXIT

!macro NSIS_HOOK_PREINSTALL
  ; F-10 fix: declare the space the POSTINSTALL pack-staging chain below adds
  ; beyond what NSIS's own File statements already account for. AddSize is a
  ; compile-time directive (summed into this Section's total regardless of
  ; where it appears in the section body); see CIVICCAST_ADDSIZE_PACKS_KB's
  ; own definition and derivation near the top of this file.
  AddSize ${CIVICCAST_ADDSIZE_PACKS_KB}
  ; INSTALL-ONLY REFUSAL (owner decision, 2026-07-30 beta): this beta ships
  ; install-only -- running the installer over an existing LIVE install must
  ; REFUSE loudly, before any destructive PREINSTALL action (before the
  ; service-stop / tree-rebuild work below), so a refused machine is left
  ; completely untouched. The documented update path is: uninstall (which
  ; preserves the database cluster, its HKLM DatabaseUrl credential, and
  ; InstalledVersion) -> run the new installer -> the fresh install adopts
  ; the preserved data and the D3 engine below upgrades the schema from the
  ; TRUE old version.
  ;
  ; "Live" is proven by TWO signals, chosen because the uninstall teardown
  ; provably clears BOTH on a successful uninstall (see
  ; NSIS_HOOK_PREUNINSTALL / NSIS_HOOK_POSTUNINSTALL below for the code that
  ; does the clearing):
  ;   * $INSTDIR\CivicCast Native.exe existing -- the EXACT SAME FileExists
  ;     check the service-stop step immediately below already uses to detect
  ;     "a prior install exists". NSIS_HOOK_POSTUNINSTALL's recursive
  ;     `RMDir /r "$INSTDIR"` (itself gated on the teardown having confirmed
  ;     the service actually stopped -- see that macro) is the ONE thing that
  ;     removes this exe, so its presence here means either no uninstall ever
  ;     ran, or the last one was blocked/incomplete -- either way, a live
  ;     install.
  ;   * the CivicCastSupervisor service being registered in the SCM at all
  ;     (checked via `sc query`: exit 0 == registered in ANY run state, 1060
  ;     == ERROR_SERVICE_DOES_NOT_EXIST == provably not registered). This is
  ;     the identical SCM-not-winreg pattern
  ;     civiccast.native.win_probes._default_wsl_service_present already uses
  ;     for the same "is this Windows service actually registered" question,
  ;     now also reused by the Python D3 drain's writers-active probe (see
  ;     civiccast/native/upgrade/service_control.py's
  ;     _real_service_registered_probe, the update-path drain fix landed
  ;     alongside this refusal gate). NSIS_HOOK_PREUNINSTALL's
  ;     `--civiccast-teardown-native-state` call is what unregisters the
  ;     service on a real uninstall.
  ;
  ; DELIBERATELY DOES NOT key on InstalledVersion or DatabaseUrl: both HKLM
  ; values under Software\CivicCast\Native SURVIVE uninstall BY DESIGN (they
  ; are exactly the reinstall-over-preserved-data signal the D3 engine below
  ; depends on) -- refusing on either would refuse the documented update path
  ; itself, the one thing this gate must never do.
  !insertmacro CIVICCAST_STEP "preinstall: checking for a live existing install (install-only refusal)"
  ${If} ${FileExists} "$INSTDIR\CivicCast Native.exe"
    !insertmacro CIVICCAST_STEP "preinstall: REFUSED (install tree present at $INSTDIR)"
    !insertmacro CIVICCAST_FAIL ${CIVICCAST_EXIT_INSTALL_OVER_EXISTING} "An existing CivicCast (Native) installation is present on this machine. This beta is install-only and does not support installing over a live install.$\r$\n$\r$\nTo update: uninstall CivicCast (Native) first from Windows Settings > Apps. Your recorded data and database are preserved by uninstall and will be adopted by the new installation. Then run this installer again."
  ${EndIf}
  nsExec::ExecToLog '"$SYSDIR\sc.exe" query CivicCastSupervisor'
  Pop $0
  ${If} $0 == 0
    !insertmacro CIVICCAST_STEP "preinstall: REFUSED (CivicCastSupervisor service is registered in the SCM)"
    !insertmacro CIVICCAST_FAIL ${CIVICCAST_EXIT_INSTALL_OVER_EXISTING} "An existing CivicCast (Native) installation is present on this machine (the CivicCastSupervisor service is registered). This beta is install-only and does not support installing over a live install.$\r$\n$\r$\nTo update: uninstall CivicCast (Native) first from Windows Settings > Apps. Your recorded data and database are preserved by uninstall and will be adopted by the new installation. Then run this installer again."
  ${EndIf}
  !insertmacro CIVICCAST_STEP "preinstall: no live existing install found -- proceeding"
  ;
  ; CRITICAL fix (2026-07-30 Sandbox audit): nothing previously stopped the
  ; CivicCastSupervisor LocalSystem service before the D3 install/upgrade
  ; engine and D4 pack extraction delete and rebuild $INSTDIR\runtime and
  ; $INSTDIR\packs\...\payload -- the service's own pythonservice.exe (and its
  ; long-lived postgres.exe child) run FROM that tree, so a
  ; rebuild while it is still running can delete a binary out from under a
  ; live process. Stop it here, BEFORE the existing taskkill of the GUI exe.
  ; Only attempted when a prior install actually left the exe behind -- on a
  ; genuinely first-ever install there is nothing to stop yet, and running
  ; this against a not-yet-installed product is the normal, expected case
  ; (native_service_registration::stop_native_service is itself idempotent,
  ; but the exe existence check avoids even trying on a fresh machine).
  ; A nonzero result here is breadcrumbed and does NOT abort on its own.
  ;
  ; This used to claim "the taskkill below and the D3 engine's own quiescence
  ; checks are the remaining safety nets." A 2026-07-30 adversarial audit
  ; refuted that, and it is not a safety net that belongs here:
  ;   * the taskkill targets "CivicCast Native.exe" (the GUI/bootstrap exe),
  ;     never pythonservice.exe / postgres.exe;
  ;   * the D3 engine's quiescence check runs in POSTINSTALL, AFTER
  ;     --civiccast-stage-packs has already rebuilt the tree it would protect.
  ; The real enforcement lives at the destructive seam itself, in Rust:
  ; native_pack_staging::ensure_pack_extracted cannot delete an extracted tree
  ; without a TreeRebuildAuthority proving the service is stopped, so a failure
  ; here surfaces as a loud refusal at the step that would actually do damage
  ; rather than as a silent continue.
  !insertmacro CIVICCAST_STEP "preinstall: stop native service (if a prior install exists)"
  ${If} ${FileExists} "$INSTDIR\CivicCast Native.exe"
    DetailPrint "Stopping the CivicCast (Native) supervisor service before install/upgrade..."
    nsExec::ExecToLog '"$INSTDIR\CivicCast Native.exe" --civiccast-stop-native-service'
    Pop $0
    !insertmacro CIVICCAST_STEP "preinstall: stop native service returned $0"
    ${If} $0 != 0
      DetailPrint "CivicCast (Native): stopping the supervisor service before install returned exit $0 -- continuing anyway (see the installer log above)."
    ${EndIf}
  ${Else}
    !insertmacro CIVICCAST_STEP "preinstall: stop native service SKIPPED (no prior install found)"
  ${EndIf}
  ; DELTA-M-02 fix (2026-08-02, rewalk-de3aaf6f): this step used to run
  ; taskkill.exe UNCONDITIONALLY, even on a genuinely fresh install where
  ; "$INSTDIR\CivicCast Native.exe" does not exist yet -- there is no prior
  ; bootstrap process to stop. nsExec::ExecToLog echoes a child's stdout/
  ; stderr straight into the operator-visible details pane, and taskkill's
  ; /IM lookup against a not-yet-existing target, run under this installer's
  ; execution context, surfaced as a raw "ERROR: The user name or password
  ; is incorrect." line (evidence: 016b-error-line-crop.png) immediately
  ; after "Stopping the existing CivicCast Native bootstrap before
  ; installation...", right before the install went on to complete
  ; successfully. Alarming and confusing to a newcomer reading the log --
  ; the install did not fail, but the log reads as though something did.
  ;
  ; Gated the SAME way the sc.exe-based service-stop step immediately above
  ; this one already is: only attempt the stop when a prior install
  ; actually left the exe behind. This is not a suppression of a real
  ; error -- it is skipping an operation this fresh-install case never
  ; needed to attempt in the first place, exactly like the gate above it.
  !insertmacro CIVICCAST_STEP "preinstall: stopping existing bootstrap"
  ${If} ${FileExists} "$INSTDIR\CivicCast Native.exe"
    DetailPrint "Stopping the existing CivicCast Native bootstrap before installation..."
    nsExec::ExecToLog 'taskkill.exe /IM "CivicCast Native.exe" /T /F'
    Sleep 500
  ${Else}
    DetailPrint "No prior CivicCast Native bootstrap process to stop (fresh install)."
  ${EndIf}
  !insertmacro CIVICCAST_STEP "preinstall: done"
!macroend

!macro NSIS_HOOK_POSTINSTALL
  !insertmacro CIVICCAST_STEP "postinstall: begin"
  !insertmacro CIVICCAST_STEP "step vc-redist: begin"
  DetailPrint "Installing the offline Microsoft Visual C++ runtime prerequisite..."
  ExecWait '"$INSTDIR\vc_redist.x64.exe" /install /quiet /norestart' $0
  !insertmacro CIVICCAST_STEP "step vc-redist: returned $0"
  ${If} $0 == 0
    DetailPrint "Microsoft Visual C++ runtime installation completed."
  ${ElseIf} $0 == 3010
    DetailPrint "Microsoft Visual C++ runtime installation completed; a Windows restart is required."
    SetRebootFlag true
  ${ElseIf} $0 == 1638
    ; CRITICAL fix (2026-08-01, real-hardware run R7): 1638 is Microsoft's
    ; ERROR_PRODUCT_VERSION -- "Another version of this product is already
    ; installed. Installation of this version can't continue."
    ; (learn.microsoft.com/en-us/windows/win32/msi/error-codes). From the VC++
    ; redistributable bootstrapper it means a SAME-OR-NEWER runtime is already
    ; on the machine, i.e. the prerequisite this step exists to guarantee is
    ; already SATISFIED. That is the normal state of most real Windows
    ; machines; the pristine Sandbox images every prior proof run used never
    ; produced it, so the catch-all below hard-failed R7's install on a
    ; machine that was fine.
    ;
    ; NOT taken on trust: 1638 is only accepted after the runtime's presence
    ; is CONFIRMED in the registry. HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\
    ; VC\Runtimes\x64 "Installed" (DWORD) is the key the VC++ redistributable
    ; itself writes and the one Microsoft's own detection guidance reads. It
    ; lives in the 64-bit view, which this 32-bit NSIS installer does not see
    ; without SetRegView 64 (same explicit-view discipline the D3 block later
    ; in this macro and NSIS_HOOK_POSTUNINSTALL already follow); the view is
    ; restored immediately afterwards so nothing between here and that block
    ; inherits a changed view. A 1638 the registry does NOT confirm is
    ; genuinely abnormal and keeps the fail-loud path below.
    SetRegView 64
    StrCpy $1 ""
    ReadRegDWORD $1 HKLM "SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" "Installed"
    SetRegView default
    ${If} $1 = 1
      !insertmacro CIVICCAST_STEP "step vc-redist: 1638 with the runtime confirmed present in the registry -- prerequisite satisfied"
      DetailPrint "Microsoft Visual C++ runtime already present, same or newer — prerequisite satisfied; setup did not reinstall it."
    ${Else}
      !insertmacro CIVICCAST_STEP "step vc-redist: 1638 but the runtime was NOT found in the registry"
      DetailPrint "Microsoft Visual C++ runtime installation failed with exit code $0, and no installed x64 runtime could be confirmed in the registry."
      !insertmacro CIVICCAST_FAIL $0 "CivicCast (Native) setup could not install the required Microsoft Visual C++ runtime (exit code $0), and could not confirm that a runtime is already installed on this machine. See the installer log at $COMMONPROGRAMDATA\CivicCast\install-progress.log."
    ${EndIf}
  ${Else}
    DetailPrint "Microsoft Visual C++ runtime installation failed with exit code $0."
    ; Keeps the redist's own exit code (informative: 1602, 1603, ... are
    ; Microsoft's, not ours) while routing through the same fail-loud macro as
    ; every other step, so the operator gets a dialog instead of only a log
    ; line and no branch can drift back to a quiet failure. Every nonzero code
    ; other than the three branched on above still lands here, unchanged.
    !insertmacro CIVICCAST_FAIL $0 "CivicCast (Native) setup could not install the required Microsoft Visual C++ runtime (exit code $0). See the installer log at $COMMONPROGRAMDATA\CivicCast\install-progress.log."
  ${EndIf}
  ;
  ; ===================================================================
  ; NATIVE COMPONENT PACK DELIVERY (plan-sub-300mb-bootstrap.md; migrated
  ; from nsis-hooks-native.nsh's NSIS_HOOK_POSTINSTALL, WP2 hook-migration
  ; 2026-07-30 -- see the file header above and the migration evidence)
  ; ===================================================================
  ; The bootstrap executable carries NO station packs (see the file header);
  ; required packs are delivered by SIDE-LOAD ONLY: a verified `.ccpack` in a
  ; `packs\` folder next to THIS installer, at $EXEDIR -- NSIS's built-in
  ; "directory containing the currently running installer .exe".
  ;
  ; There is NO SECOND DELIVERY PATH TODAY. The
  ; native_distribution::acquire_online_distribution machinery is reached (not
  ; forked) but can only produce a typed NOT_AVAILABLE outcome, since no
  ; channel index URL is pinned anywhere in this codebase -- so it cannot
  ; fetch anything, on any machine, however well connected. This comment used
  ; to label that path an online FALLBACK; that label reads as working
  ; behaviour and is what the failure dialog below was written from. Until a
  ; channel index URL is
  ; pinned and proven, no operator-facing text here may offer a network or
  ; download remedy (chain F-min, 2026-08-01: a real tester hit this abort --
  ; child exit 74, hook exit 110 -- and was told to connect the machine to the
  ; network, which could not have helped).
  ;
  ; `--civiccast-stage-packs` verifies every candidate pack's signature + byte
  ; inventory BEFORE copying, re-verifies the landed copy, then extracts each
  ; required payload to its product-owned destination: server binaries under
  ; `$INSTDIR\packs`, the application under `$INSTDIR\runtime`, and FFmpeg /
  ; Ollama under `$INSTDIR\dependencies`. An already-verified extracted tree
  ; is left untouched. An unsatisfied required component is a loud abort
  ; naming the side-load remedy. No `--require-component` flag is passed, so
  ; the effective required set is exactly
  ; `native_pack_staging::DEFAULT_REQUIRED_COMPONENTS`: server binaries,
  ; application payload, FFmpeg runtime, and Ollama runtime.
  ;
  ; CAPTURED, not just streamed (chain F-min2, 2026-08-01; TESTER2
  ; request-0050 verified on real hardware that
  ; $COMMONPROGRAMDATA\CivicCast\install-progress.log carried only the
  ; CIVICCAST_STEP breadcrumbs -- step begin / returned 74 / postinstall
  ; FAILED -- and never named a single missing component, while the dialog
  ; below promised exactly that list would be there).
  ;
  ; The child DOES name them: main.rs's `--civiccast-stage-packs` arm
  ; `eprintln!`s native_pack_staging::build_pack_delivery_abort_message, which
  ; joins every still-missing component into the message. Under
  ; nsExec::ExecToLog that text goes to the wizard detail pane and NOWHERE
  ; else -- the pane is not install-progress.log, and under `/S` there is no
  ; pane at all -- so the promise could not be kept. ExecToStack captures it
  ; into $1 instead, and the failure arm below hands it to CIVICCAST_STEP,
  ; the one macro in this file that writes that log.
  ;
  ; ExecToStack costs nothing that ExecToLog was providing: native_pack_staging.rs
  ; contains ZERO print/println/eprintln calls (grepped), so the child emits
  ; nothing at all until it exits -- there is no progressive output for the
  ; pane to lose while the multi-gigabyte extraction runs. ExecToStack is
  ; already this file's established capture idiom (the uninstall-preflight
  ; calls in NSIS_HOOK_PREUNINSTALL use it the same way, exit code then
  ; output). $1 truncates at ${NSIS_MAX_STRLEN}; on the failure path the
  ; abort message is one short line well inside it, and on the success path
  ; $1 is the FULL pretty-printed JSON manifest report (main.rs's
  ; --civiccast-stage-packs handler: serde_json::to_string_pretty on
  ; success, a short eprintln! on failure) -- the exit code in $0, never
  ; $1's shape, is what every branch decision here is made on.
  ;
  ; F-11 fix (2026-08-01, sandbox walkthrough of dd7f835f): this used to
  ; DetailPrint "$1" UNCONDITIONALLY right after popping it, so a
  ; successful install dumped that raw JSON manifest into the wizard's
  ; "Show details" pane -- an operator asking to see what the installer was
  ; doing got a JSON blob instead of a step log, and the real human-readable
  ; step history scrolled out of view underneath it. The pane must carry the
  ; human step log; full detail (including this exact JSON) belongs in
  ; install-progress.log, which the success line below now names -- the log
  ; still gets the complete report via CIVICCAST_STEP, so nothing is lost,
  ; only moved out of the operator-facing pane.
  !insertmacro CIVICCAST_STEP "step stage-packs: begin"
  DetailPrint "Staging required native component packs from the 'packs' folder next to this installer..."
  nsExec::ExecToStack '"$INSTDIR\CivicCast Native.exe" --civiccast-stage-packs "$EXEDIR" --install-root "$INSTDIR"'
  Pop $0
  Pop $1
  !insertmacro CIVICCAST_STEP "step stage-packs: returned $0"
  ${If} $0 != 0
    ; This breadcrumb is what makes the dialog's "see the installer log for
    ; the exact missing component(s)" a true statement. It carries the CHILD's
    ; own words, so the component list an operator reads in the log is the
    ; authority's, never a copy this hook could let drift.
    !insertmacro CIVICCAST_STEP "step stage-packs: child reported: $1"
    DetailPrint "CivicCast (Native): required native component pack delivery FAILED (exit $0) — see the installer log above for the exact missing component(s)."
    ; The retry instruction MUST name the uninstall step. Measured 2026-08-08
    ; (Sandbox adversarial scenario B, evidence
    ; .civiccast-sandbox-preflight\adversarial\evidence\adv-retry-result.json):
    ; a corrupted pack aborts here with 110, but Tauri has already written its
    ; ARP entry and $INSTDIR\CivicCast Native.exe at installer.nsi:649/670-689,
    ; before this hook runs -- and CIVICCAST_FAIL deliberately does NOT retract
    ; them (see its header: the uninstaller is the only discoverable way to
    ; clean a half-installed machine, and the cleanup watcher keys on that ARP
    ; DisplayName). NSIS_HOOK_PREINSTALL then detects "a live existing install"
    ; by testing for exactly that exe. So an operator who followed the previous
    ; wording -- "then run setup again" -- got refused with exit 120 and no
    ; explanation of the contradiction. Run 1 exit 110, run 2 exit 120, service
    ; absent both times. The leftover is correct by design; only this text was
    ; wrong.
    !insertmacro CIVICCAST_FAIL ${CIVICCAST_EXIT_PACK_DELIVERY} "CivicCast (Native) setup could not obtain a required native component pack.$\r$\n$\r$\nThe component pack file(s) are published alongside this installer -- on the same release page, or on the same distribution medium you got setup from.$\r$\n$\r$\nTo retry:$\r$\n  1. Obtain the required .ccpack file(s) and put them in a 'packs' folder next to the installer (the same folder this setup .exe is in).$\r$\n  2. Uninstall CivicCast (Native) from Windows Settings > Apps. This failed attempt left a partial installation behind, and setup will refuse to install over it. Your recorded data and database in $COMMONPROGRAMDATA\CivicCast are preserved by uninstall.$\r$\n  3. Run setup again.$\r$\n$\r$\nSee the installer log at $COMMONPROGRAMDATA\CivicCast\install-progress.log for the exact missing component(s)."
  ${Else}
    ; SUCCESS: $1 is the informational JSON manifest report. Log it in full
    ; (support needs it) but show the operator a short, honest, human line
    ; in the pane instead -- naming where the rest of the detail lives.
    !insertmacro CIVICCAST_STEP "step stage-packs: manifest report: $1"
    DetailPrint "Required native component packs staged and verified. Full detail: $COMMONPROGRAMDATA\CivicCast\install-progress.log"
  ${EndIf}
  ;
  ; ===================================================================
  ; D2 INSTALL-TIME RE-VERIFICATION OF THE EXTRACTED PACK TREE
  ; (spec-installer-lifecycle.md D2; migrated + ADAPTED from the retired
  ; nsis-hooks-native.nsh's pair of manifest-tree D2 re-verification calls)
  ; ===================================================================
  ; ADAPTATION: the retired file re-verified $INSTDIR\runtime and
  ; $INSTDIR\native-runtime against an in-tree app-payload-manifest.json /
  ; runtime-manifest.json -- the WP-6 embedded-payload convention. Neither
  ; path is ever laid down by this bootstrap build (no embedded resource
  ; carries them; see the file header), so re-running that exact check here
  ; would be an unconditional false-abort on every install, not a real
  ; defense. Runs AFTER pack staging (the tree now arrives via packs, so it
  ; cannot be verified before extraction) using the pack-tree form instead:
  ; `--civiccast-verify-pack-tree` re-opens the ORIGINAL signed .ccpack fresh
  ; and re-walks the extracted directory against it (independent of the
  ; extraction step's own internal verification), the same fail-loud "verify
  ; before trusting a laid tree" posture applied to what actually exists on
  ; disk in this architecture.
  ; F-11 fix (2026-08-02, rewalk of b1c6fe4d): this used to run under
  ; nsExec::ExecToLog, which streams 100% of the child's stdout straight into
  ; the wizard's "Show details" pane live -- there is no Pop/DetailPrint choke
  ; point to gate it at all, unlike stage-packs's ExecToStack idiom just
  ; above. On success, --civiccast-verify-pack-tree (main.rs's
  ; run_native_install_verify_cli) prints the FULL VerifiedPack via
  ; serde_json::to_string_pretty -- including its complete files: Vec<{path,
  ; bytes, sha256}>, one entry per file in the pack -- so ExecToLog dumped
  ; that entire per-file manifest into the pane. Switched to ExecToStack (the
  ; same established capture idiom stage-packs uses) so the result can be
  ; gated the same way: the pane gets one honest human line, the full report
  ; still reaches install-progress.log via CIVICCAST_STEP.
  DetailPrint "Re-verifying the extracted native-server-binaries component pack against its signed pack file (D2)..."
  !insertmacro CIVICCAST_STEP "step d2-verify-server-binaries: begin"
  nsExec::ExecToStack '"$INSTDIR\CivicCast Native.exe" --civiccast-verify-pack-tree "$INSTDIR\packs\native-server-binaries.ccpack" --destination "$INSTDIR\packs\native-server-binaries\payload" --expected-component native-server-binaries'
  Pop $0
  Pop $1
  ; F-17 fix (2026-08-01, newcomer walkthrough of dd7f835f): this step used to
  ; write only its "begin" breadcrumb -- on success, nothing else ever reached
  ; install-progress.log for it, so an operator reading the log could not tell
  ; whether verification ran, passed, or hung. Written BEFORE the branch below,
  ; exactly like vc-redist / stage-packs / d4-provision, so the result lands
  ; unconditionally on both the success and the failure path; the timestamp on
  ; this line against the timestamp on "begin" is how every other step in this
  ; log already conveys elapsed duration.
  !insertmacro CIVICCAST_STEP "step d2-verify-server-binaries: returned $0"
  ${If} $0 != 0
    !insertmacro CIVICCAST_STEP "step d2-verify-server-binaries: child reported: $1"
    DetailPrint "CivicCast (Native): D2 install-time verification of the extracted native-server-binaries pack FAILED (exit $0)."
    DetailPrint "The tree at $INSTDIR\packs\native-server-binaries\payload does not match its signed pack — see the installer log above for the exact mismatched path(s)."
    !insertmacro CIVICCAST_FAIL ${CIVICCAST_EXIT_D2_SERVER_BINARIES} "CivicCast (Native) setup could not verify a required native component pack it just extracted against its signed manifest. This usually means disk corruption or an interrupted copy. Re-download the installer/pack and try again; if this persists, contact support with the installer log."
  ${Else}
    ; SUCCESS: $1 is the informational per-file VerifiedPack JSON report. Log
    ; it in full (support needs it) but show the operator a short, honest,
    ; human line in the pane instead -- naming where the rest of the detail
    ; lives.
    !insertmacro CIVICCAST_STEP "step d2-verify-server-binaries: verification report: $1"
    DetailPrint "Native-server-binaries component pack verified against its signed pack file (D2). Full detail: $COMMONPROGRAMDATA\CivicCast\install-progress.log"
  ${EndIf}
  ;
  ; The native-app-payload pack's extraction destination is BRIDGED by
  ; native_pack_staging::ensure_pack_extracted to $INSTDIR\runtime (not the
  ; generic packs\native-app-payload\payload\ convention above) -- see this
  ; file's header and wp2-app-payload-pack-2026-07-30.md. Re-verify what was
  ; actually laid down at that bridged destination.
  ; F-11 fix (2026-08-02, rewalk of b1c6fe4d): same gap as
  ; d2-verify-server-binaries above, and the one the walkthrough actually
  ; witnessed -- native-app-payload's VerifiedPack.files carries the embedded
  ; Python payload (site-packages, alembic migrations, thousands of small
  ; files), so ITS ExecToLog dump was the "Lib/site-packages/civiccast/
  ; alembic/__init__.py" manifest flood the rewalk's evidence/029-*.png
  ; screenshots show. Switched to the same guarded ExecToStack idiom.
  DetailPrint "Re-verifying the extracted native-app-payload component pack against its signed pack file (D2)..."
  !insertmacro CIVICCAST_STEP "step d2-verify-app-payload: begin"
  nsExec::ExecToStack '"$INSTDIR\CivicCast Native.exe" --civiccast-verify-pack-tree "$INSTDIR\packs\native-app-payload.ccpack" --destination "$INSTDIR\runtime" --expected-component native-app-payload'
  Pop $0
  Pop $1
  ; F-17 fix (2026-08-01, newcomer walkthrough of dd7f835f): same gap as
  ; d2-verify-server-binaries above -- see that step's comment. The
  ; walkthrough's install-progress.log showed 107 seconds between this step's
  ; "begin" and the next breadcrumb with nothing logged for it in between.
  !insertmacro CIVICCAST_STEP "step d2-verify-app-payload: returned $0"
  ${If} $0 != 0
    !insertmacro CIVICCAST_STEP "step d2-verify-app-payload: child reported: $1"
    DetailPrint "CivicCast (Native): D2 install-time verification of the extracted native-app-payload pack FAILED (exit $0)."
    DetailPrint "The tree at $INSTDIR\runtime does not match its signed pack — see the installer log above for the exact mismatched path(s)."
    !insertmacro CIVICCAST_FAIL ${CIVICCAST_EXIT_D2_APP_PAYLOAD} "CivicCast (Native) setup could not verify a required native component pack it just extracted against its signed manifest. This usually means disk corruption or an interrupted copy. Re-download the installer/pack and try again; if this persists, contact support with the installer log."
  ${Else}
    ; SUCCESS: $1 is the informational per-file VerifiedPack JSON report --
    ; this is the exact payload the rewalk observed flooding the pane. Log
    ; it in full (support needs it) but show the operator a short, honest,
    ; human line in the pane instead.
    !insertmacro CIVICCAST_STEP "step d2-verify-app-payload: verification report: $1"
    DetailPrint "Native-app-payload component pack verified against its signed pack file (D2). Full detail: $COMMONPROGRAMDATA\CivicCast\install-progress.log"
  ${EndIf}
  ;
  ; The native-ffmpeg-runtime pack's extraction destination is BRIDGED the same
  ; way, to $INSTDIR\dependencies\ffmpeg -- so that its bin\-rooted payload
  ; lands at $INSTDIR\dependencies\ffmpeg\bin\ffmpeg.exe, the exact path
  ; native_activation.rs's validate_staged_runtime_layout and the staged-runtime
  ; self-test both pin. Re-verify what was actually laid down there, never the
  ; generic packs\native-ffmpeg-runtime\payload\ path (which this component
  ; never uses).
  ;
  DetailPrint "Re-verifying the extracted native-ffmpeg-runtime component pack against its signed pack file (D2)..."
  !insertmacro CIVICCAST_STEP "step d2-verify-ffmpeg-runtime: begin"
  nsExec::ExecToStack '"$INSTDIR\CivicCast Native.exe" --civiccast-verify-pack-tree "$INSTDIR\packs\native-ffmpeg-runtime.ccpack" --destination "$INSTDIR\dependencies\ffmpeg" --expected-component native-ffmpeg-runtime'
  Pop $0
  Pop $1
  ${If} $0 != 0
    !insertmacro CIVICCAST_STEP "step d2-verify-ffmpeg-runtime: child reported: $1"
    DetailPrint "CivicCast (Native): D2 install-time verification of the extracted native-ffmpeg-runtime pack FAILED (exit $0)."
    DetailPrint "The tree at $INSTDIR\dependencies\ffmpeg does not match its signed pack — see the installer log above for the exact mismatched path(s)."
    !insertmacro CIVICCAST_FAIL ${CIVICCAST_EXIT_D2_FFMPEG_RUNTIME} "CivicCast (Native) setup could not verify a required native component pack it just extracted against its signed manifest. This usually means disk corruption or an interrupted copy. Re-download the installer/pack and try again; if this persists, contact support with the installer log."
  ${Else}
    !insertmacro CIVICCAST_STEP "step d2-verify-ffmpeg-runtime: verification report: $1"
    DetailPrint "Native-ffmpeg-runtime component pack verified against its signed pack file (D2). Full detail: $COMMONPROGRAMDATA\CivicCast\install-progress.log"
  ${EndIf}
  ;
  ; The product-owned Ollama runtime uses the same bridge pattern. Its pack is
  ; rooted at ollama.exe and lands at $INSTDIR\dependencies\ollama, the exact
  ; absolute path the LocalSystem supervisor resolves before starting AI.
  DetailPrint "Re-verifying the extracted native-ollama-runtime component pack against its signed pack file (D2)..."
  !insertmacro CIVICCAST_STEP "step d2-verify-ollama-runtime: begin"
  nsExec::ExecToStack '"$INSTDIR\CivicCast Native.exe" --civiccast-verify-pack-tree "$INSTDIR\packs\native-ollama-runtime.ccpack" --destination "$INSTDIR\dependencies\ollama" --expected-component native-ollama-runtime'
  Pop $0
  Pop $1
  ${If} $0 != 0
    !insertmacro CIVICCAST_STEP "step d2-verify-ollama-runtime: child reported: $1"
    DetailPrint "CivicCast (Native): D2 install-time verification of the extracted native-ollama-runtime pack FAILED (exit $0)."
    DetailPrint "The tree at $INSTDIR\dependencies\ollama does not match its signed pack — see the installer log above for the exact mismatched path(s)."
    !insertmacro CIVICCAST_FAIL ${CIVICCAST_EXIT_D2_OLLAMA_RUNTIME} "CivicCast (Native) setup could not verify the required local-AI runtime pack it just extracted against its signed manifest. Re-download the installer/pack and try again; if this persists, contact support with the installer log."
  ${Else}
    !insertmacro CIVICCAST_STEP "step d2-verify-ollama-runtime: verification report: $1"
    DetailPrint "Native-ollama-runtime component pack verified against its signed pack file (D2). Full detail: $COMMONPROGRAMDATA\CivicCast\install-progress.log"
  ${EndIf}
  ;
  ; A per-run id for the journal + D7a interlock owner (migrated unchanged).
  ; The installer window handle ($HWNDPARENT) is a stable, per-session unique
  ; token; the journal is keyed by state-root, so this only needs to name the
  ; interlock owner. Computed here because BOTH the D3 engine immediately
  ; below and the D4 provisioning step after it need it, for the SAME
  ; owner-id convention.
  StrCpy $R1 "nsis-$HWNDPARENT"
  ;
  ; ===================================================================
  ; D3 JOURNALED INSTALL/UPGRADE ENGINE (spec-installer-lifecycle.md D3;
  ; rehomed from the retired nsis-hooks-native.nsh's NSIS_HOOK_POSTINSTALL --
  ; left unwired by the prior hook-migration because $INSTDIR\runtime\
  ; python.exe did not exist in any bootstrap build target yet; the
  ; app-payload-pack gap closure above (bce9a3cf) bridges the native-
  ; app-payload pack's extraction to exactly that path, and the D2
  ; re-verification two blocks above re-checks that bridged tree before this
  ; call trusts it. See the file header and wp2-d3-rehoming-2026-07-30.md.
  ; ===================================================================
  ; Runs as a THIN SHELL -- all D3 logic (acquire interlock -> drain+verify
  ; quiescence -> verified pre-upgrade backup -> lay tree + flip junction ->
  ; migrate -> maintenance/read-only health gate -> commit, with the defined
  ; rollback and rollback-failure recovery paths) lives in tested Python
  ; (civiccast.native.upgrade), never in NSIS script; the engine is
  ; idempotently resumable from its own journal.
  ;
  ; POSITION (coordinator decision): runs HERE -- after D2 pack-tree
  ; verification and BEFORE D4 provisioning/service registration below --
  ; because tree management (junction flip, migration, health gate, rollback)
  ; must commit on the tree BEFORE provisioning/service-build acts on it.
  ;
  ; Contract of the call (exit code -> installer branch):
  ;   0  committed        10 clean rollback (old version healthy)
  ;   11 fresh install    — no installed product; the engine is not applicable
  ;   12 same version     — nothing to migrate; the engine did not run
  ;   20 HALTED — operator recovery doc emitted (see ProgramData\CivicCast\upgrade)
  ;   30 refused (declared non-restorable migration; needs operator ack)
  ;   40 unexpected fault
  ; 0/10/20/30/40 are preserved EXACTLY from the retired file. 11 and 12 are
  ; the ROUTING outcomes added by chain K/K2 (see below); neither is a failure
  ; and both continue the install. The numeric ladder is cross-checked against
  ; civiccast/native/upgrade/__main__.py's _EXIT_CODES and _ROUTE_EXIT_CODES
  ; in BOTH directions by tests/policy/test_native_installer_identity.py, so a
  ; code the engine can emit without a branch here fails the build.
  ;
  ; $R0 = the version installed by the PREVIOUS successful run of this chain,
  ; from the product-owned InstalledVersion marker ("none" on a fresh
  ; install). NOT the ARP DisplayVersion: Tauri's generated install section
  ; writes ARP (including DisplayVersion) BEFORE NSIS_HOOK_POSTINSTALL runs,
  ; so by the time this gate executes ARP always shows the version being
  ; installed RIGHT NOW — it can neither detect a fresh install nor supply
  ; the true old version during an upgrade. Proven live in Sandbox matrix
  ; row 1, 2026-07-30: the ARP-keyed gate never fired, the engine ran with
  ; an empty --database-url and faulted (exit 1). The marker is written only
  ; at the fully-successful end of this chain (below) and, like DatabaseUrl,
  ; deliberately survives uninstall (the database cluster is preserved), so
  ; reinstall-over-existing-data correctly runs the engine as an upgrade.
  ; $R2 = the DatabaseUrl registry value AS IT STANDS RIGHT NOW. ADAPTATION
  ; from the retired block: that block read this same key AFTER D4
  ; provisioning had already run (D3 ran after D4 there), so it always saw a
  ; freshly-provisioned value. Here D3 runs BEFORE provisioning, so $R2 is
  ; empty on a first-ever install; provisioning below re-reads the same
  ; (unchanged by D3) key into $R3 for its own decision matrix, so its
  ; fresh-vs-reuse logic is unaffected. See wp2-d3-rehoming-2026-07-30.md.
  SetRegView 64
  StrCpy $R0 ""
  ReadRegStr $R0 HKLM "Software\CivicCast\Native" "InstalledVersion"
  ${If} $R0 == ""
    StrCpy $R0 "none"
  ${EndIf}
  StrCpy $R2 ""
  ReadRegStr $R2 HKLM "Software\CivicCast\Native" "DatabaseUrl"
  ; CRITICAL fix latch (2026-07-30 adversarial review): "0" (default) means
  ; the InstalledVersion write at the end of this macro runs normally; the
  ; exit==10 (clean rollback) branch below sets this to "1" so that write is
  ; SKIPPED instead -- see the exit==10 branch and the gated write at the end
  ; of this macro for the full justification.
  StrCpy $R4 "0"
  ; UPGRADE-VS-FRESH ROUTING (chain K/K2, real-hardware R7, 2026-08-01).
  ;
  ; This block used to hold the routing gate itself:
  ;     ${If} $R0 == "none"      ; InstalledVersion absent
  ;       ${AndIf} $R2 == ""     ; DatabaseUrl absent
  ;       ... skip the D3 engine
  ; Both of those HKLM values SURVIVE uninstall BY DESIGN (they are the
  ; credential for, and version stamp of, the PostgreSQL cluster uninstall
  ; deliberately preserves -- see native_uninstall.rs's
  ; NATIVE_D4_STATE_INVENTORY). They are DATA-REMNANT signals, not
  ; product-existence signals, so the gate could never fire on a machine that
  ; had ever held a successful install. R7 was exactly that machine: 0 ARP
  ; entries, no CivicCastSupervisor service, no install directory -- and the
  ; installer ran the UPGRADE engine anyway, "upgrading" 1.0.0-rc15 to
  ; 1.0.0-rc15, failing, and ending setup in a rollback dialog that told the
  ; operator that a version which was never installed remained in good health
  ; and running. (The exact wording is not repeated here: chain M3's test
  ; greps this file for that sentence, and a comment quoting it would trip a
  ; pin whose whole job is proving the claim is gone from the product.)
  ;
  ; The decision now lives in tested Python (civiccast/native/upgrade/
  ; routing.py), which is where this file's own contract says all D3 logic
  ; belongs -- the routing gate was the one piece that violated it, and it is
  ; the piece that broke. The engine decides BEFORE it builds any seam or
  ; touches the database, keying on whether a product actually EXISTS (SCM
  ; registration of CivicCastSupervisor -- the same signal NSIS_HOOK_PREINSTALL's
  ; install-only refusal above already uses, and the only tracked D4 item that
  ; is both created by install and removed by uninstall). It reports the route
  ; through exit codes 11/12 below.
  ;
  ; The engine is therefore invoked UNCONDITIONALLY now. That is deliberate:
  ; one decision point instead of two that can disagree, and every run --
  ; including a first-ever install -- leaves the routing decision and its
  ; reason in the durable engine log under $COMMONPROGRAMDATA\CivicCast\upgrade,
  ; which is the artifact a support case actually has. $R2 may legitimately be
  ; empty here (D3 runs before D4 provisioning); the routing decision is made
  ; before the URL is used for anything.
  !insertmacro CIVICCAST_STEP "step d3-engine: begin (old=$R0)"
  DetailPrint "Running the CivicCast (Native) install/upgrade engine (D3)..."
  nsExec::ExecToLog '"$INSTDIR\runtime\python.exe" -m civiccast.native.upgrade \
      --old-version "$R0" --new-version "${VERSION}" \
      --install-root "$INSTDIR" \
      --state-root  "$COMMONPROGRAMDATA\CivicCast\upgrade" \
      --database-url "$R2" --owner-run-id "$R1" \
      --payload-source "$INSTDIR\runtime"'
  Pop $0  ; engine exit code
  ${If} $0 == 0
    DetailPrint "CivicCast (Native): install/upgrade committed."
  ${ElseIf} $0 == 11
    ; ROUTED TO FRESH INSTALL (chain K/K2). No installed product was found, so
    ; there was nothing to drain, back up, migrate, or health-gate. NOT a
    ; failure and NOT a rollback: the install continues to D4 below, which
    ; adopts any preserved PostgreSQL cluster and its credential as-is (its
    ; own decision matrix already treats an existing DatabaseUrl as reuse, not
    ; regenerate). The InstalledVersion write at the end of this macro runs
    ; normally -- this run really is installing ${VERSION}, so $R4 stays "0".
    ; The engine's own reason line (which names the preserved data root it is
    ; adopting) is already in this log via nsExec::ExecToLog and in
    ; $COMMONPROGRAMDATA\CivicCast\upgrade\upgrade-engine.log.
    DetailPrint "CivicCast (Native): no existing installation was found, so this is a fresh install — the install/upgrade engine was not applicable and did not run. Any CivicCast data already on this machine is preserved and adopted by this installation; nothing was deleted."
    !insertmacro CIVICCAST_STEP "step d3-engine: SKIPPED (routed to fresh install; existing data adopted, not deleted)"
  ${ElseIf} $0 == 12
    ; ROUTED TO SAME-VERSION NO-OP (chain K/K2). A real installed product is
    ; present and already at ${VERSION}. There is no migration between a
    ; version and itself, so the migration engine did not run. Honest text
    ; rather than a fabricated "upgrade committed": nothing about the database
    ; was touched. The rest of the chain (pack re-extraction, D2
    ; re-verification, D4 service/firewall re-registration) still runs and is
    ; what actually normalizes an installed tree.
    DetailPrint "CivicCast (Native): version ${VERSION} is already installed — there is no database migration to run, so the install/upgrade engine did nothing. Your data was not drained, backed up, migrated, or changed."
    !insertmacro CIVICCAST_STEP "step d3-engine: NO-OP (same version ${VERSION} already installed; no migration to run)"
  ${ElseIf} $0 == 10
    ; CRITICAL fix (2026-07-30 adversarial review): a clean rollback was
    ; previously recorded as a SUCCESSFUL upgrade -- this branch only
    ; DetailPrinted and fell through to the InstalledVersion write at the end
    ; of this macro, stamping ${VERSION} on a machine the D3 engine's own
    ; contract (civiccast.native.upgrade.orchestrator._rollback) had just left
    ; healthy and RUNNING on $R0 (junction flipped back, interlock released).
    ; DESIGN CHOICE (b), not (a) CIVICCAST_FAIL: that healthy, running state
    ; is why this does NOT abort the whole install -- it would misreport a
    ; fine box as a failed setup. What must not happen is the write itself:
    ; the D3 gate's NEXT run trusts InstalledVersion as the TRUE old version
    ; (see the ReadRegStr above), so a false write here feeds a wrong
    ; --old-version into the next upgrade. Latch $R4 so the write below is
    ; skipped, and notify via CIVICCAST_NOTICE (see its definition above for
    ; why not CIVICCAST_FAIL/CIVICCAST_ALERT -- this is not a failure).
    StrCpy $R4 "1"
    ;
    ; ===================================================================
    ; F-03 (2026-08-01 sandbox newcomer re-walk dd7f835f): the operator
    ; dialog used to be raised RIGHT HERE, and it was false three ways.
    ;
    ;   "could not complete the upgrade to 1.0.0-rc15 and automatically
    ;    rolled back. The previously installed version is healthy and still
    ;    running -- no data was lost."
    ;
    ; while the machine held a complete 1.19 GB install, a RUNNING
    ; CivicCastSupervisor and a live API answering /health 200 "healthy" on
    ; :8000 -- and had never had a prior install at all (the "previous
    ; version" was a leftover registry value, F-01).
    ;
    ; Two separate defects, both fixed by MOVING the dialog rather than
    ; rewording it in place:
    ;
    ;  (1) TIMING. This point is BEFORE D4 provisioning, service
    ;      registration and the firewall rule. Any claim made here about
    ;      what is or is not running on this machine is a claim about a
    ;      state that has not happened yet. The dialog now runs at the END
    ;      of this macro, where the final state exists and can be READ.
    ;  (2) SUBSTANCE. Exit 10 means the D3 UPGRADE ENGINE reverted ITS OWN
    ;      work. It has never meant setup was undone -- the chain continues
    ;      past this branch and installs everything. "Automatically rolled
    ;      back", unqualified, is what the re-walk operator read as the
    ;      install being undone.
    ;
    ; What stays here is a factual, attributed breadcrumb: the engine's own
    ; report, labelled as the engine's report. Nothing about machine state.
    ; The $R4 latch (the InstalledVersion write below is skipped) is
    ; unchanged.
    ; ===================================================================
    DetailPrint "CivicCast (Native): the D3 upgrade engine reported a clean rollback of its own work (engine exit 10); setup continues, and this machine's final state is reported at the end of this log."
    !insertmacro CIVICCAST_STEP "step d3-engine: engine reported a clean rollback of its own work (exit 10); InstalledVersion write latched off"
  ${ElseIf} $0 == 20
    ; F-03: name WHOSE rollback, for the same reason as the exit-10 branch
    ; above -- "rollback", unqualified, is what an operator reads as the
    ; install being undone. This one is the D3 upgrade engine's own rollback
    ; of its own database work, and unlike exit 10 it did NOT succeed.
    DetailPrint "CivicCast (Native): upgrade HALTED — the D3 upgrade engine's automatic rollback of its own work could not restore the database."
    DetailPrint "The service has been left STOPPED on purpose. An operator recovery document was written to"
    DetailPrint "$COMMONPROGRAMDATA\CivicCast\upgrade\UPGRADE-RECOVERY.md — follow it before restarting."
    !insertmacro CIVICCAST_FAIL ${CIVICCAST_EXIT_D3_HALTED} "CivicCast (Native) upgrade could not complete and automatic rollback could not restore the database. The service is stopped. Follow the recovery steps in:$\n$\n$COMMONPROGRAMDATA\CivicCast\upgrade\UPGRADE-RECOVERY.md"
  ${ElseIf} $0 == 30
    DetailPrint "CivicCast (Native): this release declares a non-restorable migration and needs operator acknowledgement; automatic upgrade was refused."
    !insertmacro CIVICCAST_FAIL ${CIVICCAST_EXIT_D3_REFUSED} "This CivicCast (Native) release includes a database migration that cannot be automatically rolled back. Automatic upgrade was refused. Use the manual upgrade path with operator acknowledgement."
  ${Else}
    DetailPrint "CivicCast (Native): the install/upgrade engine reported an unexpected fault (exit $0)."
    !insertmacro CIVICCAST_FAIL ${CIVICCAST_EXIT_D3_FAULT} "CivicCast (Native) setup hit an unexpected fault while running the install/upgrade engine (exit code $0). See the installer log."
  ${EndIf}
  civiccast_bootstrap_d3_done:
  ;
  ; ===================================================================
  ; D4 DATABASE/MESSAGING SERVER PROVISIONING (migrated unchanged from
  ; nsis-hooks-native.nsh's NSIS_HOOK_POSTINSTALL)
  ; ===================================================================
  ; Runs the journaled PostgreSQL provisioning engine
  ; (civiccast.native.provision). Reads the CURRENT DatabaseUrl registry
  ; value first (into $R3) so the CLI can tell a fresh install (no value, no
  ; cluster -- runs and generates a password) apart from a re-install over an
  ; existing cluster (existing value -> no-op, reused as-is; missing value
  ; with an existing cluster -> fail-loud, D5 repair territory, never a
  ; silent regenerate). See civiccast.native.provision.__main__'s
  ; ProvisionCliAction decision matrix and native_service_registration.rs's
  ; run_native_provision for the full contract. The generated password is
  ; NEVER printed to this installer log -- it travels only inside the
  ; Rust-captured (never echoed) subprocess stdout and the HKLM write below.
  StrCpy $R3 ""
  ReadRegStr $R3 HKLM "Software\CivicCast\Native" "DatabaseUrl"
  !insertmacro CIVICCAST_STEP "step d4-provision: begin"
  DetailPrint "Provisioning the CivicCast (Native) PostgreSQL server (D4)..."
  nsExec::ExecToLog '"$INSTDIR\CivicCast Native.exe" --civiccast-provision --install-root "$INSTDIR" --owner-run-id "$R1" --existing-database-url "$R3"'
  Pop $0
  !insertmacro CIVICCAST_STEP "step d4-provision: returned $0"
  ${If} $0 == 0
    DetailPrint "CivicCast (Native): database/messaging provisioning complete (or already provisioned; no-op)."
  ${ElseIf} $0 == 75
    DetailPrint "CivicCast (Native): D4 database/messaging provisioning FAILED (exit 75) — see the installer log above and $COMMONPROGRAMDATA\CivicCast\provision\PROVISION-RECOVERY.md."
    !insertmacro CIVICCAST_FAIL ${CIVICCAST_EXIT_D4_PROVISION_FAILED} "CivicCast (Native) setup could not provision the PostgreSQL server. See the installer log and $COMMONPROGRAMDATA\CivicCast\provision\PROVISION-RECOVERY.md for details."
  ${Else}
    DetailPrint "CivicCast (Native): D4 database/messaging provisioning reported an unexpected fault (exit $0) — see the installer log above."
    !insertmacro CIVICCAST_FAIL ${CIVICCAST_EXIT_D4_PROVISION_FAULT} "CivicCast (Native) setup hit an unexpected fault while provisioning the PostgreSQL server (exit code $0). See the installer log."
  ${EndIf}
  ;
  ; ===================================================================
  ; K1 FIX: FLAT-LAYOUT STATION ACTIVATION
  ; ===================================================================
  ; The ONLY writer of station-set.json / activation-self-test.json in this
  ; codebase (native_activation.rs::activate_flat_station_with, reusing the
  ; same composition/atomic-write machinery stage_distribution_with's
  ; versioned counterpart already uses) had no production caller anywhere in
  ; this hook chain (K1 audit, 2026-08-16) -- so a freshly registered,
  ; started CivicCastSupervisor service could never find station-set.json at
  ; $INSTDIR and stayed permanently in the (gracefully degraded, but never
  ; activated) NativeStationNotActivatedError state. This step closes that
  ; gap: it writes both files DIRECTLY at $INSTDIR (flat, no app/<version>
  ; subdirectory) -- the shape native/station_runtime.py::
  ; load_native_station_environment requires for a station whose service is
  ; registered against $INSTDIR\runtime\python.exe (see that macro's own
  ; header comment two steps below).
  ;
  ; Sources a signed station bundle side-loaded next to the installer, at
  ; "$EXEDIR\station\station-index.json" -- the SAME "packs next to the
  ; installer" side-load convention --civiccast-stage-packs already uses
  ; above for component packs, extended to a full station bundle (a signed
  ; index plus its own packs, verified through
  ; native_distribution::acquire_station_distribution -- reused verbatim via
  ; --civiccast-import-station, never a second, forked acquisition path).
  ;
  ; KNOWN GAP (this slice, 2026-08-16): no build step publishes a station
  ; bundle to $EXEDIR\station yet, so this step currently fails loud on
  ; every install until one is. That is the correct, honest behavior for
  ; this slice -- an unconditional silent skip here is the exact shape that
  ; produced K1 in the first place (an install that reports success while
  ; the station can never activate). See this slice's evidence/report for
  ; the full reconciliation this still needs (native_pack_staging.rs's
  ; DEFAULT_REQUIRED_COMPONENTS stages a disjoint component set from the one
  ; station activation's self-test needs) before this can pass on a real
  ; build.
  !insertmacro CIVICCAST_STEP "step d4-activate-station: begin"
  DetailPrint "Activating the CivicCast (Native) station (K1)..."
  nsExec::ExecToLog '"$INSTDIR\CivicCast Native.exe" --civiccast-activate-station --install-root "$INSTDIR" --civiccast-import-station "$EXEDIR\station\station-index.json" --cache-root "$INSTDIR\packs\.station-cache"'
  Pop $0
  !insertmacro CIVICCAST_STEP "step d4-activate-station: returned $0"
  ${If} $0 == 0
    DetailPrint "CivicCast (Native): station activation complete (or already activated; no-op)."
  ${Else}
    DetailPrint "CivicCast (Native): station activation FAILED (exit $0) — see the installer log above."
    !insertmacro CIVICCAST_FAIL ${CIVICCAST_EXIT_D4_ACTIVATION} "CivicCast (Native) setup could not activate the station. A signed station bundle (station-index.json and its packs) was not found at $EXEDIR\station -- publish one alongside the installer, place it there, and run setup again. See the installer log above for the exact underlying error."
  ${EndIf}
  ;
  ; ===================================================================
  ; D4 INSTALL-SIDE STATE ESTABLISHMENT (migrated unchanged from
  ; nsis-hooks-native.nsh's NSIS_HOOK_POSTINSTALL; spec-installer-lifecycle.md
  ; D4)
  ; ===================================================================
  ; Runs AFTER the D2 re-verification above and the provisioning step just
  ; above have both passed (every failure branch above aborts the install via
  ; CIVICCAST_FAIL, so this point is only reached with a verified pack tree
  ; AND a provisioned/reused database). Implementation:
  ; native_service_registration.rs; the state each step establishes is
  ; tracked bidirectionally against its POSTUNINSTALL removal in
  ; native_uninstall.rs's NATIVE_D4_STATE_INVENTORY (see the
  ; wp2-d4-service-registration evidence file for the full table), and this
  ; file's own NSIS_HOOK_PREUNINSTALL / NSIS_HOOK_POSTUNINSTALL macros below
  ; already implement the matching D1/D4 uninstall-side half.
  !insertmacro CIVICCAST_STEP "step d4-service-registration: begin"
  DetailPrint "Registering the CivicCast (Native) supervisor service (D4)..."
  nsExec::ExecToLog '"$INSTDIR\CivicCast Native.exe" --civiccast-register-native-service --install-root "$INSTDIR"'
  Pop $0
  !insertmacro CIVICCAST_STEP "step d4-service-registration: returned $0"
  ; pywin32's service install MOVES pythonservice.exe out of the payload's
  ; site-packages\win32 into the payload root (its own "moving host exe"
  ; step, unconditional). The payload pack ships the exe at BOTH paths, so
  ; the service's registered binary path (the root copy) is a first-class
  ; manifest member and can never dangle -- but the site-packages member is
  ; now missing, which would make the very next D5 verification report a
  ; repair. Restore it here so the installed tree stays byte-identical to
  ; the signed manifest. Proven necessary live: Sandbox matrix run 6 left
  ; the service registered but unstartable (StartService error 2) after D5
  ; repair normalized the mutated tree.
  ; NOTE the source path: pywin32 moves the exe to sys.exec_prefix, which for
  ; this payload is $INSTDIR\runtime (the service's registered binary path is
  ; $INSTDIR\runtime\pythonservice.exe -- confirmed in Sandbox run 10's
  ; sc qc snapshot). The original restore here copied from
  ; $INSTDIR\pythonservice.exe -- a path that has never existed -- and
  ; CopyFiles /SILENT swallowed the failure on every install, which is
  ; exactly why every clean install's first D5 verify reported 76/repaired
  ; (run 10: verify names the missing member
  ; runtime\Lib\site-packages\win32\pythonservice.exe). Guarded now: a
  ; missing source writes a distinct breadcrumb instead of silently doing
  ; nothing, so this can never regress invisibly again.
  ; task #50 (Sandbox runs 12+13, row 3): this restore is NOT exclusive to
  ; the install/upgrade chain anymore. D5 Repair calls
  ; native_service_registration::register_native_service directly,
  ; in-process, with no NSIS hook in that path at all -- so a copy of this
  ; same restore now lives INSIDE register_native_service itself
  ; (restore_service_host_site_packages_member, native_service_registration.rs),
  ; run immediately after every pywin32 install/update, covering repair too.
  ; This hook-side restore stays as-is (redundant but harmless on the
  ; install/upgrade path, which already gets it from the Rust seam as well).
  IfFileExists "$INSTDIR\runtime\pythonservice.exe" civiccast_svc_host_restore civiccast_svc_host_restore_missing
  civiccast_svc_host_restore:
  CopyFiles /SILENT "$INSTDIR\runtime\pythonservice.exe" "$INSTDIR\runtime\Lib\site-packages\win32\pythonservice.exe"
  !insertmacro CIVICCAST_STEP "step d4-service-registration: restored site-packages service host member"
  Goto civiccast_svc_host_restore_done
  civiccast_svc_host_restore_missing:
  !insertmacro CIVICCAST_STEP "step d4-service-registration: WARNING source $INSTDIR\runtime\pythonservice.exe missing; site-packages member NOT restored (next D5 verify will report a repair)"
  civiccast_svc_host_restore_done:
  ${If} $0 != 0
    DetailPrint "CivicCast (Native): D4 service registration FAILED (exit $0) — see the installer log above."
    !insertmacro CIVICCAST_FAIL ${CIVICCAST_EXIT_D4_SERVICE} "CivicCast (Native) setup could not register the CivicCast (Native) Windows service. See the installer log for the exact error."
  ${EndIf}
  !insertmacro CIVICCAST_STEP "step d4-firewall-rule: begin"
  DetailPrint "Registering the CivicCast (Native) portal/API firewall rule (D4)..."
  nsExec::ExecToLog '"$INSTDIR\CivicCast Native.exe" --civiccast-register-native-firewall-rule --install-root "$INSTDIR"'
  Pop $0
  !insertmacro CIVICCAST_STEP "step d4-firewall-rule: returned $0"
  ${If} $0 != 0
    DetailPrint "CivicCast (Native): D4 firewall rule registration FAILED (exit $0) — see the installer log above."
    !insertmacro CIVICCAST_FAIL ${CIVICCAST_EXIT_D4_FIREWALL} "CivicCast (Native) setup could not create the required inbound firewall rule. See the installer log for the exact error."
  ${EndIf}
  ;
  ; ===================================================================
  ; HONEST ARP "Installed apps" SIZE (F-12 fix, 2026-08-01): Tauri's own
  ; EstimatedSize write (installer.nsi, inside Section Install, strictly
  ; BEFORE this hook runs -- same ordering already relied on by the
  ; QuietUninstallString write below) sums only what NSIS's own File
  ; statements embed in this section (~237 MB measured against this exact
  ; build: the bootstrap exe, the VC++ redistributable, the WebView2
  ; offline installer) -- it cannot see the native component packs the D2/
  ; D3/D4 chain above just staged into $INSTDIR via external nsExec calls,
  ; which is most of the real footprint (a walkthrough of this exact build
  ; measured the true total at 1,187,975,659 bytes / 10,274 files -- see
  ; FINDINGS-rewalk-dd7f835f.md F-10/F-12 and VERDICT-rewalk-dd7f835f.md).
  ; Rather than hardcode that one-time snapshot (which drifts the moment a
  ; pack's size changes), measure $INSTDIR for real, right here, after
  ; every pack has been staged and D2-verified and D4 provisioning/service/
  ; firewall registration has all succeeded -- this is what Windows'
  ; "Installed apps" size should have said all along, and it self-corrects
  ; on every future build without touching this file again.
  ;
  ; ${GetSize} is a FileFunc "artificial function" (FileFunc.nsh, already
  ; !include'd by installer.nsi before this file's own !include site -- the
  ; same precedent CIVICCAST_STEP's own header comment already documents
  ; for ${GetTime}): it only touches the registers it is explicitly Popped
  ; into ($0 size-in-KB, $1 file count, $2 dir count here), so $R0-$R4
  ; (the D3 old-version/DatabaseUrl/rollback-latch state still needed
  ; below) are untouched by this call.
  ;
  ; Overwrites Tauri's own write the same way the QuietUninstallString
  ; write below already does: last write to this key in this Section wins.
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  WriteRegDWORD SHCTX "${UNINSTKEY}" "EstimatedSize" "$0"
  !insertmacro CIVICCAST_STEP "postinstall: EstimatedSize corrected to $0 KB (measured $INSTDIR: $1 files, $2 dirs)"
  ; Record the version this fully-successful chain just installed. This is
  ; the D3 gate's prior-version signal on the NEXT run (see the gate comment
  ; above). Written HERE — after every D2/D3/D4 step has succeeded — because
  ; every failure branch above aborts the install outright (CIVICCAST_FAIL)
  ; and must leave the marker at its previous value (a failed upgrade did not
  ; change the installed version).
  ;
  ; CRITICAL fix (2026-07-30 adversarial review): a clean D3 rollback (exit
  ; 10, above) reaches this point too -- it does not abort -- but must NOT be
  ; recorded as InstalledVersion=${VERSION}, because the machine never left
  ; $R0 (see the exit==10 branch's full justification). $R4 == "1" is that
  ; latch.
  ${If} $R4 == "1"
    ;
    ; ===================================================================
    ; F-03 (2026-08-01 sandbox newcomer re-walk dd7f835f). What used to be
    ; here, verbatim from the re-walk's install-progress.log:
    ;
    ;   postinstall: SUCCESS (D3 clean rollback; InstalledVersion left at
    ;                         1.0.0-rc15, NOT 1.0.0-rc15)
    ;
    ; Two defects in one line. SUCCESS is the word an operator, a support
    ; engineer and a fleet log scraper all key on, and this run did not
    ; succeed. And "left at X, NOT X" is a sentence asserting a thing and
    ; its negation -- it renders that way whenever the leftover marker
    ; happens to record the same build being installed, which is exactly the
    ; case the re-walk hit, because the leftover came from installing this
    ; same build.
    ;
    ; Everything below is either a fact this installer just VERIFIED or a
    ; report attributed to the component that produced it.
    ; ===================================================================
    ;
    ; The one claim on this path an installer can actually verify at the
    ; moment it speaks: ask the service control manager. `sc query` on an
    ; unregistered service fails and prints no STATE line, so findstr finds
    ; nothing and the NOT-running arm is taken -- which is the correct
    ; reading for "there is no service". Both arms state that the answer was
    ; read, so a reader can tell a verified fact from an assumption.
    nsExec::ExecToLog 'cmd.exe /c "sc.exe query CivicCastSupervisor | findstr /I RUNNING >nul"'
    Pop $0
    ${If} $0 == 0
      StrCpy $R5 "the CivicCast (Native) service is RUNNING on this machine right now (read from the service control manager)"
    ${Else}
      StrCpy $R5 "the CivicCast (Native) service is NOT running on this machine right now (read from the service control manager)"
    ${EndIf}
    ; The recorded-version sentence, one wording per case, so no branch can
    ; render a contradiction. $R0 is the literal string "none" on the
    ; recovery path (a CivicCast database IS registered but no
    ; InstalledVersion is), and equals ${VERSION} on the F-01 leftover path.
    ${If} $R0 == "none"
      StrCpy $R6 "no installed version was recorded before this run, and none was recorded now"
    ${ElseIf} $R0 == "${VERSION}"
      StrCpy $R6 "the recorded installed version is unchanged and still reads $R0, which is the same version this setup was installing"
    ${Else}
      StrCpy $R6 "the recorded installed version is unchanged at $R0 and was not advanced to ${VERSION}"
    ${EndIf}
    DetailPrint "CivicCast (Native): this release's upgrade did not take effect -- the D3 upgrade engine reverted its own work. $R6. $R5."
    !insertmacro CIVICCAST_STEP "postinstall: COMPLETED WITH A D3 ROLLBACK (the upgrade engine reverted its own work; $R6; $R5)"
    !insertmacro CIVICCAST_NOTICE "CivicCast (Native) setup finished, but this release's upgrade did not take effect: the D3 upgrade engine reverted its own work and reported a clean rollback.$\r$\n$\r$\nSetup itself was NOT undone. The program files, the Windows service and the firewall rule were all installed by the steps that ran after the engine, and they are on this machine now. What was reverted is the upgrade engine's own work for this release.$\r$\n$\r$\nRead from this machine just now: $R6, and $R5.$\r$\n$\r$\nSee the installer log at $COMMONPROGRAMDATA\CivicCast\install-progress.log for why the engine did not commit."
  ${Else}
    WriteRegStr HKLM "Software\CivicCast\Native" "InstalledVersion" "${VERSION}"
    DetailPrint "CivicCast (Native): recorded InstalledVersion ${VERSION} for the next install/upgrade run."
    !insertmacro CIVICCAST_STEP "postinstall: SUCCESS (InstalledVersion ${VERSION} recorded)"
  ${EndIf}
  DetailPrint "CivicCast (Native) bootstrap install complete: required component packs staged and D2-verified, D3 install/upgrade engine run, PostgreSQL provisioned, service and firewall rule registered."
  ; Reaching here means SUCCESS and nothing else. The former shared
  ; `civiccast_bootstrap_postinstall_done` unwind label is gone: it existed
  ; only so failure branches could skip the InstalledVersion write and fall
  ; out of the macro quietly, which is exactly the behavior AUDIT-001 found
  ; (a failed install continuing into Tauri's unconditional success page).
  ; See the file header and wp2-d3-rehoming-2026-07-30.md for what is
  ; deliberately NOT wired above (the WP-6 embedded-payload defensive gate,
  ; the media-runtime-closure D2 check) and why.
  ;
  ; ===================================================================
  ; QuietUninstallString registration (P1, 2026-07-31 run-18 forensic
  ; diagnosis): makes the SetErrorLevel 82 uninstall refusal in
  ; NSIS_HOOK_PREUNINSTALL (see that macro) actually REACHABLE by an
  ; unattended caller (winget, Intune, a deployment script).
  ; ===================================================================
  ; MEASURED, not assumed: Tauri's own generated installer.nsi (this file's
  ; own !include site) registers ONLY UninstallString (installer.nsi:676,
  ; `"$INSTDIR\uninstall.exe"`, no `_?=` and no QuietUninstallString) and
  ; never writes a QuietUninstallString key anywhere in that file (confirmed
  ; by reading target/release/nsis/x64/installer.nsi in full -- grep for
  ; "QuietUninstallString" there returns nothing). With no `_?=`, NSIS's own
  ; exehead behavior (confirmed live by this product's makensis probe,
  ; .agent-runs/native-windows/ws5-installer/evidence/nsis-errorlevel-probe/)
  ; is: the invoked "$INSTDIR\uninstall.exe" process respawns a copy of
  ; itself into %TEMP%, launches THAT copy to do the real work, and the
  ; ORIGINAL process -- the one any waiting caller actually holds a handle
  ; to and reads the exit code from -- returns 0 as soon as the respawn is
  ; launched. That original-process exit therefore happens BEFORE
  ; NSIS_HOOK_PREUNINSTALL, the Uninstall section body, or this file's own
  ; SetErrorLevel 82 refusal (see that macro's header) ever run in the
  ; respawned copy. A caller driving UninstallString synchronously always
  ; observes exit 0, even on a refused or failed uninstall -- the exact
  ; unreachable-refusal defect this fix closes.
  ;
  ; `_?=$INSTDIR` disables that respawn: the uninstaller runs IN-PLACE,
  ; synchronously, in the SAME process the caller is waiting on, so its real
  ; exit code (including the 82 refusal) becomes observable. This is the
  ; documented NSIS tradeoff for `_?=` (it also means the uninstaller cannot
  ; self-delete -- see the P2 fix in NSIS_HOOK_POSTUNINSTALL below, which
  ; closes that side of the same tradeoff).
  ;
  ; Registered as QuietUninstallString, NOT an overwrite of UninstallString:
  ; Windows' own Apps & Features interactive "Uninstall" button reads
  ; UninstallString and must keep the normal (self-deleting, respawning)
  ; behavior for a human-driven uninstall; QuietUninstallString is the
  ; distinct, silent-caller-specific key that modern unattended deployment
  ; tooling (winget, Intune, System Center) prefers when present, leaving
  ; the interactive path completely unchanged.
  ;
  ; Written HERE -- the LAST statement of this macro, immediately before its
  ; closing, after
  ; every D2/D3/D4 step and the InstalledVersion write above have already
  ; run, and therefore also strictly AFTER Tauri's own UNINSTKEY writes at
  ; installer.nsi:670-689 (NSIS_HOOK_POSTINSTALL is inserted at
  ; installer.nsi:703-705, itself after those writes) -- so this key is not
  ; at risk of being overwritten by anything later in the Install section,
  ; and if a future Tauri version starts writing its own
  ; QuietUninstallString, THIS write runs last and wins (see
  ; tests/policy/test_native_installer_identity.py for the pin covering
  ; this). Uses SHCTX (not a hardcoded HKLM/HKCU) and ${UNINSTKEY} to match
  ; every other UNINSTKEY write in this file and in installer.nsi, so
  ; per-machine vs per-user install mode stays consistent automatically.
  WriteRegStr SHCTX "${UNINSTKEY}" "QuietUninstallString" '"$INSTDIR\uninstall.exe" /S _?=$INSTDIR'
  !insertmacro CIVICCAST_STEP "postinstall: QuietUninstallString registered (_?=$INSTDIR)"
  ; Tauri's installer.nsi writes InstallLocation as '"$INSTDIR"' -- WITH
  ; embedded literal quotes inside the registry VALUE. Found on the first
  ; ever inspection of an installed machine (Sandbox lifecycle attempt 5,
  ; 2026-08-07): every consumer that treats the value as a path (inventory
  ; tooling, ops scripts, the lifecycle harness itself) silently resolves a
  ; nonexistent quoted path. Windows convention is the bare path. Same
  ; write-last-wins placement rationale as QuietUninstallString above.
  WriteRegStr SHCTX "${UNINSTKEY}" "InstallLocation" "$INSTDIR"
  !insertmacro CIVICCAST_STEP "postinstall: InstallLocation rewritten unquoted"
  ;
  ; ===================================================================
  ; Start Menu + Desktop shortcuts to the RUNNING STATION's own web
  ; surfaces (bug fix, field report 2026-08-28, candidate 9d4477b): once
  ; this setup wizard's own window closes, an operator had NO clickable
  ; path back to the operator console or the public portal at all. The
  ; setup app's finish screen does offer "Open operator console"
  ; (App.tsx's primaryActionLabel), but that control disappears with the
  ; window, and this installer creates no shortcut of any kind pointing at
  ; either surface -- Tauri's own generated Start Menu/Desktop entries (if
  ; any) point at "$INSTDIR\${MAINBINARYNAME}.exe", which is the SETUP
  ; WIZARD, not the running service; relaunching it re-runs first-run
  ; setup, it does not open the console.
  ;
  ; URLs are the SAME fixed literals `main.rs` hardcodes
  ; (`OPERATOR_CONSOLE_URL`, `RESIDENT_PORTAL_URL`) -- NSIS has no access to
  ; installer-state.json's (possibly nonce-bearing) operatorConsoleUrl at
  ; this point in the chain: that file is written by the GUI's OWN first
  ; run, which has not happened yet when POSTINSTALL executes. A future nonce
  ; scheme would need a first-run rewrite of these shortcuts from inside the
  ; app, not a POSTINSTALL-time value that cannot exist yet.
  ; tests/policy/test_native_installer_identity.py pins both literals against
  ; `main.rs`'s own constants so the two can never silently drift apart.
  ;
  ; Internet Shortcut (.url) files, not .lnk: a .url file is a plain
  ; INI-format text file (WriteINIStr writes it directly, creating the file
  ; and section if either is missing) that needs no icon resource and no
  ; target executable to resolve -- both matter here, because this
  ; installer embeds exactly one icon (icons/icon.ico, used only for the
  ; installer/uninstaller binaries themselves per tauri.native.conf.json)
  ; and the shortcut's target is a URL, not a file on this machine. Windows
  ; opens a .url file in the system's default browser at click time,
  ; whatever that is.
  ;
  ; SetShellVarContext all: matches this product's fixed perMachine install
  ; mode (tauri.native.conf.json's "installMode": "perMachine", not
  ; operator-selectable) so $SMPROGRAMS/$DESKTOP resolve to the ALL USERS
  ; locations -- every operator on this station sees the same two entries,
  ; not just whichever account happened to run setup. Called explicitly
  ; (never assumed already in effect) so this block's correctness does not
  ; depend on undocumented behavior of Tauri's own generated installer.nsi.
  ;
  ; Best-effort, deliberately: unlike every CIVICCAST_FAIL step above, a
  ; shortcut that could not be written does not abort or alarm the
  ; install -- the station itself is fully installed and functional either
  ; way, and the operator can still reach both surfaces via the setup
  ; wizard's own finish screen. ClearErrors/${If} ${Errors} only logs a
  ; breadcrumb so a report of "no shortcuts" is diagnosable from
  ; install-progress.log without turning a cosmetic miss into a failed
  ; install.
  ; ===================================================================
  SetShellVarContext all
  CreateDirectory "$SMPROGRAMS\${PRODUCTNAME}"
  ClearErrors
  WriteINIStr "$SMPROGRAMS\${PRODUCTNAME}\CivicCast Operator Console.url" "InternetShortcut" "URL" "http://127.0.0.1:8000/operator/"
  ${If} ${Errors}
    !insertmacro CIVICCAST_STEP "postinstall: could not write the Start Menu operator console shortcut (non-fatal)"
    ClearErrors
  ${Else}
    !insertmacro CIVICCAST_STEP "postinstall: Start Menu operator console shortcut written"
  ${EndIf}
  WriteINIStr "$SMPROGRAMS\${PRODUCTNAME}\CivicCast Public Portal.url" "InternetShortcut" "URL" "http://127.0.0.1:8000/"
  ${If} ${Errors}
    !insertmacro CIVICCAST_STEP "postinstall: could not write the Start Menu public portal shortcut (non-fatal)"
    ClearErrors
  ${Else}
    !insertmacro CIVICCAST_STEP "postinstall: Start Menu public portal shortcut written"
  ${EndIf}
  WriteINIStr "$DESKTOP\CivicCast Operator Console.url" "InternetShortcut" "URL" "http://127.0.0.1:8000/operator/"
  ${If} ${Errors}
    !insertmacro CIVICCAST_STEP "postinstall: could not write the Desktop operator console shortcut (non-fatal)"
    ClearErrors
  ${Else}
    !insertmacro CIVICCAST_STEP "postinstall: Desktop operator console shortcut written"
  ${EndIf}
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  ; P3 instrumentation (2026-07-31 run-18 forensic diagnosis): the very first
  ; breadcrumb this macro writes, before any probe, prompt, or teardown call
  ; below. $EXEPATH is the running uninstall.exe's own image path (proves
  ; WHICH copy is executing -- the in-place `_?=` copy vs. a stray respawned
  ; %TEMP% copy from an un-fixed caller, see the P1 QuietUninstallString fix
  ; in NSIS_HOOK_POSTINSTALL) and $CMDLINE is its full invocation (proves
  ; whether a caller passed /S, _?=, or neither) -- both are the two honest,
  ; already-available signals that answer "how was this uninstall actually
  ; invoked" without guessing from downstream behavior.
  !insertmacro CIVICCAST_STEP "preuninstall: BEGIN pid-image=$EXEPATH cmdline=$CMDLINE"
  ; WP2: Rust owns state observation. It reads 64-bit HKLM ActiveRuntime and
  ; current-user WSL ARP directly, never localized reg.exe output. Exit 73 is
  ; the sole-active plan and has armed the product-owned POST marker.
  ;
  ; WP2 transfer-transaction (2026-07-30): exit 74 means the ONLY thing
  ; blocking removal is an un-acknowledged ActiveRuntime ownership transfer to
  ; the still-installed WSL product (spec-installer-lifecycle.md D1: "the
  ; operator to run the cutover/rollback transfer, offered as an explicitly
  ; acknowledged transaction from the uninstall UI, before removal proceeds").
  ; This MessageBox MB_YESNO is the only interactive surface available here
  ; and is the sole place this macro is allowed to prompt the operator. On
  ; Yes, the SAME executable is re-invoked with --acknowledge-transfer, which
  ; performs the write+read-back-verified ActiveRuntime transfer to "wsl"
  ; BEFORE this macro proceeds to stop the process / let removal continue. On
  ; No (or dismiss), nothing further runs: the uninstall aborts and
  ; ActiveRuntime is left completely untouched (native_uninstall.rs never
  ; even attempted a probe-triggering write for an unacknowledged call).
  DetailPrint "Checking CivicCast Native runtime ownership before uninstall..."
  nsExec::ExecToStack '"$INSTDIR\CivicCast Native.exe" --civiccast-native-uninstall-preflight'
  Pop $0
  Pop $1
  ${If} $0 == 74
    MessageBox MB_YESNO|MB_ICONQUESTION "CivicCast (Native) is the active runtime and the WSL product (CivicCast Installer) is still installed.$\r$\n$\r$\nTo continue uninstalling CivicCast (Native), ActiveRuntime ownership must first be transferred to the WSL product, which will then become the active runtime that starts and transmits.$\r$\n$\r$\nTransfer ownership to the WSL product now and continue uninstalling CivicCast (Native)?" IDYES civiccast_native_transfer_acknowledged
    DetailPrint "CivicCast Native uninstall was declined at the ownership transfer prompt; nothing was removed and ActiveRuntime was left unchanged."
    !insertmacro CIVICCAST_ALERT "CivicCast (Native) uninstall was cancelled. ActiveRuntime ownership was NOT transferred and nothing was removed."
    SetErrors
    Abort
    civiccast_native_transfer_acknowledged:
    DetailPrint "Operator acknowledged the ActiveRuntime ownership transfer; transferring to the WSL product before removal proceeds..."
    nsExec::ExecToStack '"$INSTDIR\CivicCast Native.exe" --civiccast-native-uninstall-preflight --acknowledge-transfer'
    Pop $0
    Pop $1
    ${If} $0 != 0
      DetailPrint "CivicCast Native ownership transfer failed after acknowledgment: $1"
      !insertmacro CIVICCAST_ALERT "CivicCast (Native) could not complete the ActiveRuntime ownership transfer. Nothing was removed.$\r$\n$\r$\nDetails: $1"
      SetErrors
      Abort
    ${EndIf}
    DetailPrint "CivicCast Native ActiveRuntime ownership transferred to the WSL product; proceeding with uninstall."
  ${ElseIf} $0 != 0
  ${AndIf} $0 != 73
    DetailPrint "CivicCast Native uninstall was blocked before process termination: $1"
    !insertmacro CIVICCAST_ALERT "CivicCast (Native) cannot be uninstalled while it is the active runtime and the WSL product remains, or when lifecycle state cannot be safely read.$\r$\n$\r$\nDetails: $1"
    SetErrors
    Abort
  ${EndIf}
  ;
  ; ===================================================================
  ; BLOCKER fix (2026-07-30 Sandbox audit; moved from POSTUNINSTALL): the
  ; teardown CLI invokes "$INSTDIR\CivicCast Native.exe" itself -- but
  ; Tauri's generated uninstall Section deletes that exact file
  ; (installer.nsi:756, `Delete "$INSTDIR\${MAINBINARYNAME}.exe"`) BEFORE
  ; NSIS_HOOK_POSTUNINSTALL ever runs (installer.nsi:838, the
  ; `!insertmacro NSIS_HOOK_POSTUNINSTALL` call site). A teardown call left
  ; in POSTUNINSTALL can therefore never execute the exe it depends on --
  ; nsExec::ExecToLog just fails to launch a file that no longer exists --
  ; so the service was never stopped, the firewall rule was never removed,
  ; and the registry state was never cleared, while the uninstall still
  ; reported exit 0 (Sandbox run 7 live evidence: CivicCastSupervisor still
  ; registered, the TCP 8000 firewall rule still open, 12,145 files left
  ; behind).
  ;
  ; EVIDENCE the exe still exists at THIS point: NSIS_HOOK_PREUNINSTALL is
  ; inserted at installer.nsi:748-750, strictly BEFORE the Delete at
  ; installer.nsi:756 -- and the ownership preflight call two blocks above
  ; (in this same macro, running strictly before this point) already
  ; depends on and successfully invokes that exact exe, proving it is still
  ; present here.
  ;
  ; ORDERING (deliberate): runs AFTER the ownership preflight above --
  ; including its MB_YESNO prompt and BOTH Abort paths (decline, and a
  ; failed post-acknowledgment transfer) -- because a cancelled or failed
  ; uninstall must still be able to abort the WHOLE operation before any
  ; state is torn down; tearing the service down and THEN aborting would
  ; leave a station broken by a cancelled operation. Runs BEFORE the
  ; pre-existing taskkill below, for the same reason the ownership preflight
  ; already runs before taskkill: the running process should be asked to
  ; tear itself down cleanly (stop its own service, remove its own firewall
  ; rule) before anything forces it to exit.
  ;
  ; The recursive removal of $INSTDIR\runtime / $INSTDIR\packs / $INSTDIR
  ; itself STAYS in POSTUNINSTALL (it must run after Tauri's own file
  ; deletion there, which only happens after this Section's Uninstall body
  ; runs past this hook) -- see that macro. Its exit code is carried there
  ; via the $CIVICCAST_TEARDOWN_EXIT file-scope Var declared above.
  ; ===================================================================
  !insertmacro CIVICCAST_STEP "preuninstall: teardown native state (service/firewall/registry): begin"
  DetailPrint "Removing the CivicCast (Native) supervisor service, firewall rule, and registry state..."
  nsExec::ExecToLog '"$INSTDIR\CivicCast Native.exe" --civiccast-teardown-native-state --install-root "$INSTDIR"'
  Pop $0
  StrCpy $CIVICCAST_TEARDOWN_EXIT $0
  !insertmacro CIVICCAST_STEP "preuninstall: teardown native state returned $0"
  ;
  ; ===================================================================
  ; RECOVERABLE FAIL-CLOSED (2026-07-31, gauntlet run 17): a nonzero teardown
  ; used to be recorded here and the uninstall ALLOWED TO CONTINUE, with the
  ; refusal deferred to NSIS_HOOK_POSTUNINSTALL's tree-retention gate. That
  ; ordering is unrecoverable, and run 17 proved it on a live machine:
  ;
  ;   * PREUNINSTALL records exit 82 (service stop could not be confirmed);
  ;   * Tauri's generated uninstall Section then deletes
  ;     "$INSTDIR\CivicCast Native.exe" (installer.nsi:756) and the uninstaller
  ;     itself, plus the shortcuts and the Add/Remove Programs entry;
  ;   * only THEN does POSTUNINSTALL (installer.nsi:838) refuse to remove the
  ;     trees.
  ;
  ; The machine is left with a preserved multi-gigabyte tree, a still-running
  ; service, and NO product exe and NO uninstaller -- so neither
  ; --civiccast-repair nor a second Uninstall can be run, and the install-only
  ; refusal gate in NSIS_HOOK_PREINSTALL (exit 120, which keys on that exact
  ; exe and on the still-registered service) then refuses every future install.
  ; A retention gate whose own precondition destroys the tools needed to act on
  ; it is not fail-closed; it is a dead end.
  ;
  ; Fix: refuse HERE, before anything is deleted. Same shape as this macro's
  ; ownership-preflight refusal branches above (CIVICCAST_ALERT + SetErrors +
  ; Abort) -- not CIVICCAST_FAIL, which is the POSTINSTALL failure vocabulary
  ; and carries a SetErrorLevel from the install-side code table. Aborting from
  ; PREUNINSTALL leaves the machine FULLY INTACT: exe, uninstaller, ARP entry,
  ; service, and trees all still present, so the operator can stop the service
  ; and run Uninstall again, and every code path that ever cleans this machine
  ; still exists.
  ;
  ; ALL nonzero codes abort, not just 82. POSTUNINSTALL's narrower gate (82
  ; refuses tree removal; a generic 80 does not) was correct for the question
  ; IT answers -- "is deleting the trees dangerous?" -- because a leftover
  ; firewall rule is no reason to strand gigabytes. This gate answers a
  ; different question: "did the uninstall do what it said?" A teardown that
  ; failed to remove the service or the firewall rule did not, and continuing
  ; would delete the only exe that can retry it. Nothing is stranded by
  ; refusing here, because nothing has been removed yet.
  ;
  ; POSTUNINSTALL's gate STAYS as defense in depth: it still runs on the exit-0
  ; path, still fails closed on an unset Var, and still covers a hand-edited or
  ; foreign hook file where this Abort was not reached.
  ; ===================================================================
  ${If} $CIVICCAST_TEARDOWN_EXIT != 0
    !insertmacro CIVICCAST_STEP "preuninstall: REFUSED (teardown exit $CIVICCAST_TEARDOWN_EXIT) -- aborting before anything is removed"
    DetailPrint "CivicCast (Native) uninstall aborted: the teardown step returned exit $CIVICCAST_TEARDOWN_EXIT and nothing has been removed."
    !insertmacro CIVICCAST_ALERT "CivicCast (Native) could not be uninstalled, so the uninstall was ABORTED and NOTHING was removed -- your installation is still complete and can be uninstalled again once the problem below is cleared.$\r$\n$\r$\nThe teardown step (stopping and removing the CivicCastSupervisor service, removing the firewall rule, clearing registry state) returned exit $CIVICCAST_TEARDOWN_EXIT.$\r$\n$\r$\nMost often this means the supervisor service did not stop. To finish: stop it manually (services.msc, or 'sc stop CivicCastSupervisor'), or reboot this machine, then run Uninstall again.$\r$\n$\r$\nSee the installer log at $COMMONPROGRAMDATA\CivicCast\install-progress.log for the exact step that failed."
    SetErrors
    ; DISTINCT EXIT CODE (2026-07-31, F5a). Without this, an Abort here returns
    ; the generic NSIS script-abort code 2 -- the SAME code this macro's
    ; ownership-DECLINE aborts return, so an unattended uninstall could not tell
    ; "the operator said no" from "the teardown failed and the machine still has
    ; a live service". 82 is the teardown CLI's own "service stop could not be
    ; confirmed" code, reused here as the uninstall-refusal code: fixed, not
    ; $CIVICCAST_TEARDOWN_EXIT, because a passthrough could emit 1 or 2 (NSIS's
    ; own reserved codes) for some other teardown failure and reintroduce the
    ; ambiguity. WHICH nonzero teardown code actually fired is in the step
    ; breadcrumb + the alert text above, which is where a diagnosis belongs.
    ;
    ; SetErrorLevel-then-Abort is MEASURED, not assumed: the in-repo probe
    ; .agent-runs/native-windows/ws5-installer/evidence/nsis-errorlevel-probe/
    ; (RESULTS.md) ran this exact ordering on this product's own makensis and
    ; got exit 41 for level 41 -- the custom code survives the Abort (Abort
    ; alone returned 2). So this returns 82.
    SetErrorLevel 82
    Abort
  ${EndIf}
  ;
  DetailPrint "Stopping the CivicCast Native bootstrap after ownership preflight..."
  nsExec::ExecToLog 'taskkill.exe /IM "CivicCast Native.exe" /T /F'
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  ; BLOCKER fix (2026-07-30 Sandbox audit): this macro previously did ONLY the
  ; ActiveRuntime selector bookkeeping below, so a completed uninstall left
  ; the CivicCastSupervisor service registered, the portal/API firewall rule
  ; open, and the Native registry values in place -- while reporting exit 0 /
  ; success.
  ;
  ; RELOCATION (2026-07-30, second Blocker on the same fix): the teardown
  ; invocation itself was originally placed HERE, but Tauri's generated
  ; uninstall Section deletes "$INSTDIR\${MAINBINARYNAME}.exe" (installer.nsi:
  ; 756) BEFORE this macro is ever inserted (installer.nsi:838), so a
  ; teardown call here could never actually run the exe it depends on -- the
  ; entire teardown (service stop, service removal, firewall rule removal)
  ; silently never executed while the uninstall still reported exit 0. The
  ; invocation now lives in NSIS_HOOK_PREUNINSTALL (see that macro's header
  ; comment for the full evidence), which runs BEFORE installer.nsi:756 --
  ; while the exe still exists. Its exit code is carried here via the
  ; $CIVICCAST_TEARDOWN_EXIT file-scope Var (declared near the top of this
  ; file) rather than a fresh nsExec call, because the recursive removal gate
  ; below MUST stay in POSTUNINSTALL -- it can only run after Tauri's own
  ; file deletion above has completed.
  ;
  ; If $CIVICCAST_TEARDOWN_EXIT is still empty here, PREUNINSTALL somehow did
  ; not run (e.g. a hand-edited or foreign hook file); default it to "82" --
  ; the same code as "service stop could not be confirmed" -- so the
  ; recursive removal below fails CLOSED instead of assuming it is safe.
  ${If} $CIVICCAST_TEARDOWN_EXIT == ""
    StrCpy $CIVICCAST_TEARDOWN_EXIT "82"
    !insertmacro CIVICCAST_STEP "postuninstall: CIVICCAST_TEARDOWN_EXIT was unset (PREUNINSTALL did not run) -- defaulting to 82 (fail closed)"
  ${EndIf}
  !insertmacro CIVICCAST_STEP "postuninstall: teardown native state result carried from preuninstall: $CIVICCAST_TEARDOWN_EXIT"
  ; CRITICAL fix (2026-07-30 adversarial review): $R2 latches whether the
  ; recursive RMDir block below (the ONLY thing that deletes $INSTDIR\runtime
  ; / $INSTDIR\packs / $INSTDIR itself) is safe to run. Exit 82 is the ONE
  ; teardown outcome that makes it unsafe: native_service_registration::
  ; teardown_exit_code (main.rs's --civiccast-teardown-native-state) returns
  ; 82 SPECIFICALLY when the "stop service" step could not confirm the
  ; CivicCastSupervisor service actually stopped -- meaning its
  ; pythonservice.exe and long-lived postgres.exe child may
  ; still be running FROM those trees. Deleting the tree underneath them is
  ; the exact hazard the install/repair side already closed
  ; (native_pack_staging::ensure_pack_extracted requires a
  ; TreeRebuildAuthority proving the service is stopped before it may delete
  ; an extracted tree) -- this closes the same gap on the uninstall path,
  ; which used raw NSIS RMDir and bypassed that seam entirely.
  ;
  ; Deliberately narrow: teardown returns the generic 80 for a "remove
  ; service" or "delete firewall rule" failure too, and those do NOT set this
  ; latch -- the service is confirmed stopped in that case, so refusing tree
  ; removal over a leftover firewall rule would strand a multi-gigabyte tree
  ; for no safety reason. Only 82 refuses; every other nonzero code keeps the
  ; prior behavior (alert, continue, still remove the trees).
  StrCpy $R2 "0"
  ${If} $CIVICCAST_TEARDOWN_EXIT == 82
    StrCpy $R2 "1"
    !insertmacro CIVICCAST_ALERT "CivicCast (Native) uninstall could not confirm that the CivicCastSupervisor service was fully stopped, so the program files were NOT removed -- deleting them now could corrupt data out from under a still-running service and its database/messaging processes.$\r$\n$\r$\nTo finish removing CivicCast (Native): stop the service manually (services.msc, or 'sc stop CivicCastSupervisor'), or reboot this machine, then run Uninstall again.$\r$\n$\r$\nSee the installer log at $COMMONPROGRAMDATA\CivicCast\install-progress.log for the exact error."
    SetErrors
  ${ElseIf} $CIVICCAST_TEARDOWN_EXIT != 0
    !insertmacro CIVICCAST_ALERT "CivicCast (Native) uninstall could not fully remove the supervisor service, firewall rule, and/or registry state (exit $CIVICCAST_TEARDOWN_EXIT). See the installer log for exactly which step failed; you may need to remove it manually (services.msc / Windows Defender Firewall / HKLM\Software\CivicCast\Native)."
  ${Else}
    DetailPrint "CivicCast (Native): supervisor service, firewall rule, and registry state removed."
  ${EndIf}
  ;
  ; Never clear the selector in PREUNINSTALL. A verified, product-owned marker
  ; proves the preflight observed Native as sole active owner. Re-check the
  ; selector immediately before deletion, then remove and verify the marker.
  SetRegView 64
  ClearErrors
  ReadRegStr $R0 HKLM "Software\CivicCast" "NativeUninstallPostclearPending"
  ${If} ${Errors}
    ; No sole-active plan was armed; leave ActiveRuntime untouched.
    Goto civiccast_native_postuninstall_done
  ${EndIf}
  ${If} $R0 != "civiccast-native-sole-active-v1"
    DetailPrint "CivicCast Native post-uninstall marker is malformed; ActiveRuntime was left unchanged."
    !insertmacro CIVICCAST_ALERT "CivicCast (Native) could not verify its uninstall lifecycle marker. ActiveRuntime was left unchanged; inspect HKLM\Software\CivicCast before retrying."
    SetErrors
    Goto civiccast_native_postuninstall_done
  ${EndIf}
  ClearErrors
  ReadRegStr $R1 HKLM "Software\CivicCast" "ActiveRuntime"
  ${If} ${Errors}
    DetailPrint "CivicCast Native could not re-read ActiveRuntime; selector was left unchanged."
    !insertmacro CIVICCAST_ALERT "CivicCast (Native) could not re-read ActiveRuntime after uninstall. The selector was left unchanged; inspect HKLM\Software\CivicCast."
    SetErrors
    Goto civiccast_native_postuninstall_done
  ${EndIf}
  ${If} $R1 != "native"
    DetailPrint "ActiveRuntime changed after preflight; selector was left unchanged."
    !insertmacro CIVICCAST_ALERT "CivicCast (Native) detected that ActiveRuntime changed after uninstall preflight. The selector was left unchanged; inspect HKLM\Software\CivicCast."
    SetErrors
    Goto civiccast_native_postuninstall_done
  ${EndIf}
  ClearErrors
  DeleteRegValue HKLM "Software\CivicCast" "ActiveRuntime"
  ${If} ${Errors}
    DetailPrint "CivicCast Native could not clear ActiveRuntime; the pending marker was retained."
    !insertmacro CIVICCAST_ALERT "CivicCast (Native) could not clear ActiveRuntime. The pending marker was retained for diagnosis; inspect HKLM\Software\CivicCast."
    SetErrors
    Goto civiccast_native_postuninstall_done
  ${EndIf}
  ClearErrors
  ReadRegStr $R1 HKLM "Software\CivicCast" "ActiveRuntime"
  ${IfNot} ${Errors}
    DetailPrint "CivicCast Native could not verify ActiveRuntime removal; the pending marker was retained."
    !insertmacro CIVICCAST_ALERT "CivicCast (Native) could not verify ActiveRuntime removal. The pending marker was retained for diagnosis; inspect HKLM\Software\CivicCast."
    SetErrors
    Goto civiccast_native_postuninstall_done
  ${EndIf}
  ClearErrors
  DeleteRegValue HKLM "Software\CivicCast" "NativeUninstallPostclearPending"
  ${If} ${Errors}
    DetailPrint "CivicCast Native cleared ActiveRuntime but could not remove the pending marker."
    !insertmacro CIVICCAST_ALERT "CivicCast (Native) cleared ActiveRuntime but could not remove its pending marker; inspect HKLM\Software\CivicCast."
    SetErrors
    Goto civiccast_native_postuninstall_done
  ${EndIf}
  ClearErrors
  ReadRegStr $R0 HKLM "Software\CivicCast" "NativeUninstallPostclearPending"
  ${IfNot} ${Errors}
    DetailPrint "CivicCast Native could not verify pending-marker removal."
    !insertmacro CIVICCAST_ALERT "CivicCast (Native) could not verify pending-marker removal; inspect HKLM\Software\CivicCast."
    SetErrors
  ${EndIf}
  civiccast_native_postuninstall_done:
  ;
  ; BLOCKER fix, continued: Tauri's own generated uninstall Section only
  ; deletes the specific files it tracked from the install manifest, then
  ; calls a NON-recursive RMDir on each directory (which only succeeds if the
  ; directory is already empty) -- it has no entry for the multi-gigabyte
  ; $INSTDIR\runtime and $INSTDIR\packs trees this bootstrap extracts
  ; DYNAMICALLY from signed .ccpack files at install time (never through
  ; File/Delete instructions Tauri's uninstaller could enumerate), so those
  ; trees -- 12,145 files in the audited Sandbox run -- were silently left
  ; behind on every uninstall while it still reported exit 0/success. Runs
  ; HERE, after the selector bookkeeping above has fully completed (so a
  ; teardown/removal failure never races the selector's own re-reads of
  ; $INSTDIR-adjacent state), and recursively removes exactly the product-
  ; owned trees this bootstrap itself lays down.
  ${If} $R2 == "1"
    DetailPrint "CivicCast (Native): skipping removal of the runtime and component-pack trees -- the supervisor service could not be confirmed stopped (see the alert above)."
    !insertmacro CIVICCAST_STEP "postuninstall: recursive removal of runtime/packs/INSTDIR: SKIPPED (service stop unconfirmed, teardown exit 82)"
  ${Else}
    DetailPrint "Removing the CivicCast (Native) runtime and component-pack trees..."
    !insertmacro CIVICCAST_STEP "postuninstall: recursive removal of runtime/packs/INSTDIR: begin"
    RMDir /r "$INSTDIR\runtime"
    RMDir /r "$INSTDIR\packs"
    RMDir /r "$INSTDIR"
    ;
    ; P2 fix (2026-07-31 run-18 forensic diagnosis): the QuietUninstallString
    ; registered in NSIS_HOOK_POSTINSTALL above (`_?=$INSTDIR`) is what makes
    ; the SetErrorLevel 82 refusal above reachable by a waiting caller (see
    ; that macro's header) -- but `_?=` carries a documented NSIS tradeoff:
    ; the uninstaller then runs IN-PLACE instead of a respawned %TEMP% copy,
    ; so it can never self-delete. Tauri's own generated uninstall Section
    ; already tries (installer.nsi:769 `Delete "$INSTDIR\uninstall.exe"`,
    ; installer.nsi:771 `RMDir "$INSTDIR"` non-recursive) -- both silently
    ; no-op on the `_?=` path because the running exe cannot delete itself
    ; and a non-empty directory containing it cannot be removed by a plain
    ; RMDir -- and the RMDir /r "$INSTDIR" immediately above this comment
    ; hits the exact same wall for the same reason: `_?=` keeps
    ; uninstall.exe running from inside $INSTDIR for the whole duration of
    ; this Section, including this recursive delete, so it is always the one
    ; file RMDir /r cannot touch. MEASURED, not assumed: a live `_?=` run
    ; left exactly one file behind (filesLeft=1) -- uninstall.exe itself,
    ; with an empty-but-undeletable $INSTDIR around it.
    ;
    ; Fix: schedule BOTH for deletion on next reboot. `/REBOOTOK` is NSIS's
    ; standard mechanism for exactly this case (MoveFileEx with
    ; MOVEFILE_DELAY_UNTIL_REBOOT under the hood) -- it cannot delete the
    ; running exe or its now-should-be-empty parent directory immediately,
    ; but schedules the OS to do so at the next boot, after the process has
    ; exited. GUARDED by FileExists (2026-07-31 audit findings L3 + E7):
    ; unguarded, (a) `RMDir /REBOOTOK` on an already-removed $INSTDIR can
    ; still register a PendingFileRenameOperations entry on EVERY ordinary
    ; uninstall (NSIS EW_RMDIR calls MoveFileOnReboot whenever
    ; RemoveDirectory fails, with no existence check -- fleet tooling reads
    ; that registry value as "reboot pending"), and (b) a pending
    ; delete-on-reboot for uninstall.exe outlives an uninstall->reinstall
    ; cycle and would delete the NEW uninstaller at the next boot, leaving
    ; an unremovable product. The guard makes both calls true no-ops on the
    ; ordinary (non-`_?=`) path where Tauri's own Delete/RMDir at
    ; installer.nsi:769/771 already removed both. Order matters: the file
    ; must be scheduled before its now-empty parent directory, matching
    ; `RMDir /r`'s own child-then-parent convention immediately above.
    ${If} ${FileExists} "$INSTDIR\uninstall.exe"
      Delete /REBOOTOK "$INSTDIR\uninstall.exe"
      RMDir  /REBOOTOK "$INSTDIR"
    ${EndIf}
    !insertmacro CIVICCAST_STEP "postuninstall: recursive removal of runtime/packs/INSTDIR: done"
    ;
    ; ===================================================================
    ; F-01, UNINSTALLER HALF (2026-08-01 sandbox newcomer re-walk dd7f835f):
    ; a completed uninstall must leave NOTHING claiming a product is
    ; installed. Two things make that claim. The first is
    ; HKLM\Software\CivicCast\Native\InstalledVersion, now cleared by the
    ; teardown CLI's "clear install markers" step
    ; (native_service_registration::delete_native_install_marker_values) --
    ; that one is what the re-walk actually caught, and it is what made the
    ; next install run the D3 upgrade engine against a product that was not
    ; there. The second is this one: Tauri's InstallDirRegKey.
    ;
    ; Tauri derives NSIS's ${MANUFACTURER} from the bundle identifier's
    ; second segment when no explicit publisher is configured --
    ; tauri.native.conf.json's "org.civiccast.native" -> "civiccast", which
    ; is also why this product's Publisher renders lowercase -- so the key is
    ; Software\civiccast\CivicCast (Native) and its DEFAULT VALUE is the
    ; install path. It is what Tauri's own reinstall page reads to decide a
    ; machine is "Already Installed".
    ;
    ; Tauri's generated uninstall Section does emit its own DeleteRegKey for
    ; this key, and this removal is deliberately REDUNDANT with it rather
    ; than a replacement -- DeleteRegKey on an absent key is a silent no-op,
    ; so the redundancy costs nothing. It is here because that expectation
    ; has already failed once in this product family: the retired WSL
    ; product's hook file (nsis-hooks.nsh, removed under the owner's "no
    ; linux" decision) carried an explicit "rc13 lifecycle repair" doing
    ; exactly this deletion for its own InstallDirRegKey, with the comment
    ; "Leaving it behind after uninstall produces a false 'Already Installed'
    ; page on an otherwise clean host".
    ;
    ; PLACEMENT is load-bearing, not cosmetic: inside the ${Else} arm of the
    ; $R2 tree-retention gate, so it runs ONLY on the path that actually
    ; removed $INSTDIR\runtime / $INSTDIR\packs / $INSTDIR. On the retained-
    ; tree path (service stop unconfirmed) the product IS still installed and
    ; this key must keep saying so -- erasing it there would let the next
    ; install run straight over a live tree, which is the same class of
    ; defect as the leftover this block removes, pointed the other way.
    ;
    ; /ifempty on the parent Software\civiccast is DELIBERATELY NOT DONE:
    ; the registry is case-insensitive, so that is the SAME key as
    ; HKLM\Software\CivicCast, which holds the ActiveRuntime selector and the
    ; Maintenance interlock blob this file's own postclear protocol above
    ; owns end to end. /ifempty would be a no-op while those exist and a
    ; cross-protocol surprise the moment they do not.
    ; ===================================================================
    SetRegView 64
    DeleteRegKey HKLM "Software\civiccast\CivicCast (Native)"
    !insertmacro CIVICCAST_STEP "postuninstall: removed the Tauri InstallDirRegKey (HKLM\Software\civiccast\CivicCast (Native)) so a later install cannot see this machine as Already Installed"
  ${EndIf}
  ; $COMMONPROGRAMDATA\CivicCast is deliberately NEVER touched by this
  ; removal, or by anything else in this macro: it holds product-owned data
  ; (the PostgreSQL cluster, upgrade/provision journals, and operator
  ; recovery documents) that is preserved across uninstall by design. Purge
  ; remains a separate, typed operator action in the lifecycle implementation,
  ; not something a normal uninstall ever performs.
  ;
  ; Start Menu + Desktop shortcut removal (bug fix, field report 2026-08-28,
  ; candidate 9d4477b): the counterpart to POSTINSTALL's shortcut creation
  ; above. Deliberately OUTSIDE the $R2 tree-retention gate above (runs
  ; unconditionally, on EVERY uninstall, even one that skipped removing
  ; $INSTDIR because the supervisor service could not be confirmed stopped):
  ; unlike the runtime/packs trees, a Start Menu or Desktop shortcut is
  ; state this product owns independently of $INSTDIR and of whether the
  ; service is still running -- deleting a shortcut file carries none of
  ; the "still-running process holding the tree open" hazard that gate
  ; exists to guard against, so there is no safety reason to withhold it on
  ; that path, and every reason not to: a shortcut surviving a failed
  ; uninstall would point an operator at a station this machine may no
  ; longer be running as a service at all.
  SetShellVarContext all
  Delete "$SMPROGRAMS\${PRODUCTNAME}\CivicCast Operator Console.url"
  Delete "$SMPROGRAMS\${PRODUCTNAME}\CivicCast Public Portal.url"
  RMDir "$SMPROGRAMS\${PRODUCTNAME}"
  Delete "$DESKTOP\CivicCast Operator Console.url"
  !insertmacro CIVICCAST_STEP "postuninstall: Start Menu + Desktop shortcuts removed"
!macroend
