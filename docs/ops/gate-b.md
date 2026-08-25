# Gate B — the 24-hour unattended reboot soak

> **STATUS: NOT YET RUN.** As of this document's commit, Gate B has never
> executed against any candidate. The harness, the judge, its tests and its
> workflow exist and are statically verified; no 24-hour soak has been
> performed, and nothing in this repository may cite Gate B as evidence about
> any candidate. See "Honest status" at the bottom for exactly what has and
> has not been done.

## Why this exists, and why Gate A cannot do it

Gate A proves a lot: a clean Windows Sandbox install, K1 activation, both UIs
rendering, the clerk loop, real captions, the product egress engine passing
TSDuck, and a bounded soak. It cannot prove one thing, and the reason is
structural rather than a matter of effort:

**Windows Sandbox cannot reboot.** It is a disposable VM that is destroyed
rather than restarted. There is no configuration, no flag, and no amount of
harness work that makes a Sandbox VM survive a restart, because surviving is
not a thing it does.

The 3.0 MASTER spec asks for exactly that, in three separate places:

| Spec location | The requirement |
|---|---|
| `docs/spec/3.0/civiccast-3.0-station-in-a-box-MASTER.md` §12, "Global gates", release-readiness | *"24h unattended soak w/ kill+restart+**reboot**; 72h candidate soak before broad handoff"* |
| Same file, §12, "Station acceptance" | *"the box calls for help when it goes off-air unattended; **survives an unattended reboot**"* |
| Same file, §5, "Unified proof / certification ladder", rung 2 | *"Machine-proven — Clean Windows install + unattended soak (24/72h) **incl. reboot**, midnight crossover, unclean-restart reap"* |

`docs/ops/gate-a.md` names this scope as out of bounds for Gate A and assigns
it here by name. This document is the other half of that sentence.

Gate B therefore needs a **persistent** Windows environment. On the
`sandbox-lab` runner box that means a Hyper-V VM; a spare physical box is the
documented alternative.

## What Gate B proves, and what it does not

**Proves** — the checks in `scripts/gate_b_verdict.py`, each fail-closed:

| Check | What it proves | Spec citation | Evidence file(s) |
|---|---|---|---|
| `plan` | The run that was actually executed meets the §12 floor: ≥24h soak, reboot inside it, ≤5-minute beats | §12 release-readiness; S9 §8.3 item 4 | `gate-b-run.json` |
| `install` | The signed installer ran silently to exit 0 and `station-set.json` exists afterwards | §12 *"clean Windows install from artifact"*, *"operator installs+commissions without terminal work"* | `summary.json` |
| `activation` | The K1 mandatory activation hook ran and staged the station | §12 station acceptance | `ACTIVATION-RESULT.txt`, `summary.json` |
| `channels` | All three PEG channels were on air in **every** beat | §12 *"runs the three PEG channels (public/education/government) concurrently"* | `beats.jsonl` |
| `uptime_beats` | The beat log covers the whole declared soak at the declared cadence, with exactly one oversized gap — the planned reboot, inside its budget | §12 *"24h unattended soak"*; S9 §8.3 item 4 | `beats.jsonl`, `gate-b-run.json` |
| `reboot_recovery` | Exactly one reboot, at the planned mark, recovered to **broadcasting** (health 200 **and** all three channels on air) inside the recovery budget, with no operator interaction | §12 *"survives an unattended reboot"*; S9 §8.3 item 2 | `beats.jsonl`, `REBOOT-RESULT.txt` |
| `no_unplanned_restarts` | Within each boot epoch the supervisor service and every supervised child kept the same pid, the child set never changed, and `supervisor.log` carries no restart warning | §5 rung 2 *"unclean-restart reap"*; S9 §8.3 item 5 (restart churn is a blocker) | `beats.jsonl`, `supervisor-logs/supervisor.log` |
| `egress_continuity` | TSDuck verified all three transport streams **before** the reboot and again **after** it, both clean (zero invalid syncs / transport errors / discontinuities) | §12 *"TSDuck verify on UDP-TS profiles"*; S9 §8.3 item 1 (TS continuity across a supervised restart) | `egress-verify-pre-reboot.json`, `egress-verify-post-reboot.json` |
| `completion` | The harness reached its own authoritative completion signal | (harness contract, same as Gate A) | `DONE.json` |

**Does NOT prove** — out of scope by design, not by oversight:

- **Physical SDI proof** (rung 3). No DeckLink pass-through into the VM. Same
  boundary Gate A has, for the same reason.
- **The 72h candidate soak.** §12 names it separately from the 24h one. Gate B
  is the 24h rung; a 72h run is a future, longer job.
- **Unclean restart / power cut.** §12 lists *"kill+restart+reboot"* and §5
  separately names *"unclean-restart reap"*. Gate B performs a **graceful**
  reboot (`Restart-VM` without `-Force`) because that is what a patch cycle
  does. Smuggling a hard power cut into the same run would let one run claim
  to have proven both when it would have proven neither cleanly. A power-cut
  variant deserves its own named run.
- **Midnight crossover** (§5 rung 2). A 24h soak crosses midnight
  incidentally, but nothing here asserts anything about date-boundary
  behaviour, so do not cite Gate B for it.
- **The commissioning-wizard UI walkthrough, OTT-app presence, the force
  matrix, schedule commit, and the support-bundle export.** The existing
  Playwright/manual acceptance work covers these.
- **Networking-dependent tiers.** The soak VM has **no network adapter**, so
  YouTube Live, Internet Archive and real syndication targets are never
  exercised — the same boundary Gate A has.

## Four verdicts: two findings, two non-verdicts

Exactly Gate A's contract, with `HYPERV_UNAVAILABLE` playing the role Gate A's
`BUSY` plays.

| Value | Meaning | Marker | Checks in the document | Exit |
|---|---|---|---|---|
| `PASS` / `FAIL` | A real reboot-soak finding | — | All computed, and they decide the verdict | 0 / 1 |
| `HYPERV_UNAVAILABLE` | The run never started: Hyper-V is not enabled (or this session may not drive it), so no rebootable VM could be created | `HYPERV-UNAVAILABLE.txt` | Empty: no evidence was ever produced | 2 |
| `HARNESS_ERROR` | The run started, then lost its VM or its evidence channel | `GATE-B-HOST-ERROR.txt`, `VM-LOST.txt` | All computed and recorded as forensics, but they do not decide the verdict | 2 |

Neither non-verdict is ever reported as a `FAIL`. A gate that never observed
the candidate has said nothing about it, and saying otherwise is the
authored-truth failure these gates exist to eliminate, pointed the other way.

### The `plan` check is not a formality

`Run-GateB.ps1` exposes `-SoakMinutes` so an operator can rehearse the
mechanics in half an hour instead of a day. The judge's `plan` check reports
any run below 1440 minutes as a **FAIL**, naming the plan as the reason.

That is deliberate and there is no `--allow-short-soak` flag. A rehearsal is
not a 24-hour soak, and the only reliable way to stop *"we ran Gate B"* from
quietly coming to mean *"we ran something"* is for the judge to say so out
loud in the verdict document. The workflow's failure step recognises this case
and says which it was, so nobody hunts for a regression that is not there.

## Hyper-V on this box: the one command

**Measured 2026-08-25 on the `sandbox-lab` runner (this box):**

```
os=Microsoft Windows 11 Pro 10.0.26200
instrument_1_optional_feature=Microsoft-Hyper-V-All:Disabled (raw InstallState=2)
instrument_2_vmms=service_present:False binary_present:False
instrument_3_hyperv_module=False
context_hypervisor_present=True  # CONTEXT ONLY
instruments_agreeing=0/3
verdict=unavailable
```

**Hyper-V is disabled.** Three unelevated instruments of different kinds agree
(`gate-b/Test-GateBPrereqs.ps1` runs all three; `Get-WindowsOptionalFeature`
itself requires elevation and cannot be used from a normal runner session).

Note `context_hypervisor_present=True`. That is **not** evidence Hyper-V is
available. `Win32_ComputerSystem.HypervisorPresent` is true on this box
*because* WSL2 and Windows Sandbox run on the same hypervisor, with Hyper-V
itself off. The probe records it as context and refuses to let it vote —
reading it as "Hyper-V is here" is exactly the misread this gate's front door
is built to avoid.

### The one elevated command

Run this in an **Administrator** PowerShell, then **reboot the box**:

```powershell
Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All -All -NoRestart
```

Equivalent with DISM, if you prefer:

```
DISM /Online /Enable-Feature /FeatureName:Microsoft-Hyper-V-All /All /NoRestart
```

`Microsoft-Hyper-V-All` pulls in the hypervisor, the management service, the
management clients and the Hyper-V PowerShell module in one feature, which is
why it is one command and not four.

**No agent runs this.** Enabling a hypervisor is a machine-scope change with a
mandatory reboot on a box that hosts a CI runner; a release gate does not take
its own runner down on its own authority. `Test-GateBPrereqs.ps1` detects,
reports and exits 3 — it never elevates and never prompts.

After enabling, also confirm the account the Gate B runner logs on as can
actually drive Hyper-V (creating a VM, mounting and partitioning a VHD all
require it):

```powershell
Add-LocalGroupMember -SID S-1-5-32-578 -Member <DOMAIN\User-or-.\User>   # Hyper-V Administrators
```

then log that account off and on so the group lands in its token. The probe
reports this separately as `verdict=not-authorized`, because "the feature is
off" and "you may not use it" need different remedies.

### Alternative target: a spare physical box

If this box must not run Hyper-V, Gate B's design does not actually require a
VM — it requires a **persistent Windows machine that can be rebooted and
resumed**. On a spare physical box:

1. Skip `Provision-GateBVm.ps1` entirely. Put the extracted kit somewhere
   local on that box (the harness only needs a directory with `setup.exe`,
   `packs\` and `station\`; the kit VHDX exists purely to move the kit into a
   VM efficiently).
2. Run `gate-b/scripts/In-Vm-GateB-Agent.ps1 -LaunchedBy bootstrap` on that
   box directly, with `-KitVolumeLabel` replaced by pointing the agent at the
   kit — this is the one place the physical-box path needs a small parameter
   change rather than none, and it has not been exercised.
3. The reboot must then be issued from outside the agent, the way
   `Run-GateB.ps1` issues `Restart-VM` — e.g. a scheduled `shutdown /r /t 0`
   from a second account, or a remote `Restart-Computer`. Whatever issues it
   must write `REBOOT-RESULT.txt` with `operator_interaction=none` and a
   `reboot_issued_utc=` line, or the judge fails `reboot_recovery`.
4. Pull the evidence directory to wherever the judge runs and judge it
   unchanged.

**Honest boundary:** the physical-box path is designed for and documented, not
built or tested. Steps 2 and 3 need small pieces of work that do not exist in
this repository today. The Hyper-V path is the one the harness implements
end to end.

## What the operator must supply

Gate B cannot be fully automated from a cold box, because a Windows image and
a credential are things a human provides. Four inputs:

### 1. A prepared base VHDX (primary path) — `-BaseVhdx`

A Windows 11 Pro (or Windows Server) VHDX that has **already completed OOBE**
and carries a known local account in `Administrators`. Prepare it once and
keep it; every run clones it.

It is never modified: the VM gets a **differencing disk** whose parent is your
base file, so a failed run costs a differencing disk and the next run starts
from a known-clean image.

**Or** — `-WindowsIso`

A Windows installation ISO carrying `sources\install.wim` (not `install.esd`).
`Provision-GateBVm.ps1` applies the image to a fresh VHDX, injects
`gate-b/answer/autounattend.xml` at `Windows\Panther\unattend.xml` so the
first boot completes setup with nobody present, and runs `bcdboot`. This takes
tens of minutes and only has to happen once — **keep the resulting VHDX and
pass it with `-BaseVhdx` from then on.**

Before using the ISO path you **must** edit `gate-b/answer/autounattend.xml`
and replace the literal `CHANGE-ME-BEFORE-USE` password. It ships as a
placeholder on purpose: an answer file with a working credential in it is a
credential committed to a public repository, and this repository does not have
those. Provisioning with the placeholder produces a VM you cannot log into,
which is the intended failure.

### 2. A guest credential file — `-GuestCredentialPath`

Created by **you**, once, as the account the runner uses:

```powershell
Get-Credential | Export-CliXml C:\CivicCastGateB\guest-cred.xml
```

The username and password must match the account inside the base VHDX (the
ISO path creates `gatebadmin`). `Export-CliXml` protects the secret with DPAPI
scoped to the creating account, so the file is inert if copied elsewhere —
which is also why it must be created by the account the runner logs on as, not
by you at your own desk and then copied over.

The harness **never** prompts for a password, never accepts one on the command
line, and never writes one anywhere.

### 3. The candidate kit — `-KitDir`

The extracted kit in the same flat layout Gate A validates: `setup.exe`,
`packs\` and `station\` at the root. The workflow can resolve this from a
`run_id` (reusing `C:\CivicCastTester\kit-staging\<sha>\` when this box already
has it, exactly as Gate A does) or take a `kit_dir` directly.

### 4. Roughly a day of the box

Gate B holds the `sandbox-lab` concurrency group for over 24 hours. Gate A
runs and self-hosted candidate builds queue behind it. Schedule accordingly.

## How the harness is put together

```text
gate-b/
├── Test-GateBPrereqs.ps1        # Detect Hyper-V + authorization. REPORTS, never elevates.
├── Provision-GateBVm.ps1        # Create/reuse the VM, build+attach the kit disk, start it
├── Run-GateB.ps1                # Orchestrate: provision -> launch agent -> reboot -> pull -> judge
├── answer/
│   └── autounattend.xml         # ISO path only; ships with a PLACEHOLDER password
├── scripts/
│   ├── In-Vm-GateB-Agent.ps1        # Runs INSIDE the VM; resumable across the reboot
│   └── Register-GateBStartupTask.ps1 # The AtStartup SYSTEM task that resumes it
├── evidence/   (gitignored)     # <source_sha>/<utc-stamp>/ per run, same shape as Gate A's
└── kit-staging/ (gitignored)    # Downloaded candidate kits, keyed by sha

sandbox-lab/common/
└── CivicCastStationHarness.psm1 # The install/activation contract BOTH gates grade against

scripts/gate_b_verdict.py        # The judge
tests/gate_b/                    # Judge tests + the static cross-file contract tests
```

### Three design decisions worth the words

**1. Evidence moves by pull, never by push.** Gate A ships evidence through a
Windows Sandbox mapped folder, and that channel cost it three silent late-run
hangs and a measured ~2× slowdown of every install step that crossed it
(`docs/ops/gate-a.md`, "Mapped-folder stalls" and "Run 7"). Gate B does not
reproduce it. The host pulls evidence out over **PowerShell Direct** — an
in-band VMBus channel needing no networking, no share and no credentials on
the wire — on its own 30-minute schedule. A wedged pull costs one pull; the
next gets fresh handles. A 24-hour run cannot absorb Gate A's failure mode:
the same wedge that cost Gate A 47 minutes would cost Gate B the entire run.

**2. The kit arrives as a read-only VHDX, not a share.** A ~21 GB copy over
VMBus would be slower than the artifact download it replaces. Instead the host
builds a one-shot VHDX from the kit directory and attaches it read-only. That
is a block device: the installer reads `packs\` and `station\` off it at
local-disk speed, and nothing inside the VM can modify the candidate it is
being judged on. Gate A's own install code already proves the read-only-payload
assumption holds.

**3. The host issues the reboot; the guest never reboots itself.** A station
that reboots on a schedule it knows about can prepare for it. §12 asks the box
to survive a reboot, which in the field arrives as a power event or a patch
cycle, unannounced. Issuing it from outside is the closest a VM gets — and it
means `REBOOT-RESULT.txt`'s timing record is written by something the guest
could not have forged. `tests/gate_b/test_gate_b_harness_contract.py` asserts
the agent contains no `Restart-Computer`/`shutdown` at all.

### The reboot survival mechanism, precisely

The agent is a **resumable state machine**, not a script with a loop:

- All continuity lives in `C:\CivicCastGateB\state.json` — run id, the soak's
  true start, the next beat sequence number, the phase, and the station
  credential the post-reboot login needs. Every beat commits it, write-then-
  rename, so a reboot landing mid-write cannot truncate the one file that
  makes resumption possible.
- Resumption is a scheduled task registered **AtStartup as SYSTEM**, not at
  logon. An at-logon task waits for a person; §12 asks for survival with
  nobody there. `Register-GateBStartupTask.ps1` reads the task back after
  registering and fails if the trigger is not `MSFT_TaskBootTrigger` —
  "Register-ScheduledTask did not throw" is a weaker claim than "the row says
  so".
- The answer file deliberately contains **no** `<AutoLogon>`. Auto-logon would
  create an interactive desktop on every boot, and the agent's own
  unattendedness measurement (which looks for `explorer.exe`) would then
  honestly report `unattended: false` on every post-reboot beat.
- A resume that finds no readable `state.json` **refuses to run** rather than
  starting a fresh run under a resume's identity. Silently restarting the
  soak clock would report 24 hours that never happened.

### The soak clock starts when the station is broadcasting

Not when the installer launched. §12's 24 hours are 24 hours of a *running
station*; counting the install into them would shorten the thing being proven
by however long the install took. The host learns the true start by reading
the guest's own `state.json`, which is also why it cannot compute the reboot
mark from its own wall clock.

### Two instruments for unplanned restarts, and one stated blind spot

`no_unplanned_restarts` uses two instruments of different kinds, because
neither alone is sufficient:

1. **Per-beat process observation (primary).** Each beat records the
   supervisor service's pid and every supervised child's pid, keyed by image
   name and creation order — deliberately **not** by pid, because a key
   containing the pid would make a restart look like one key disappearing and
   an unrelated one appearing, i.e. invisible. Within one boot epoch those
   pids must not change and the child set must not change. Direct and
   unlatched: it counts restarts rather than inferring them.
2. **`supervisor.log` (corroborating).** Must be present and non-empty, and
   must not carry the `restart of child <name> not ready` WARNING.

**Stated blind spot:** that logger call in
`civiccast/native/supervisor/core.py` is **latched per child** — the same
failure detail is logged once, not once per attempt — so its silence proves
"no new failure mode was seen", never "no restarts happened". That is exactly
why it is the second instrument and not the only one. A contract test asserts
the judge's pattern still matches a string the supervisor actually emits, so
the check cannot quietly become unfalsifiable.

### Reuse rather than copy-paste

- **`sandbox-lab/soak-4h/scripts/verify-egress.ps1` is reused byte-for-byte.**
  It listens on `127.0.0.1:9001/9002/9003` and analyses what arrives, so it is
  engine-agnostic by construction — which is what lets it serve as evidence
  about the product GStreamer engine even though it was written for the
  ffmpeg-driven 4h soak. A contract test fails the build if a copy of it ever
  appears under `gate-b/`.
- **`sandbox-lab/common/CivicCastStationHarness.psm1`** holds the install,
  activation, known-path-lookup, station-health-wait and station-API pieces
  both gates need, parameterized so nothing closes over a caller's scope.

**Named, deferred decision — read this rather than assuming.** Gate B consumes
that module. `sandbox-lab/scripts/In-Sandbox-Report.ps1` **does not yet**:
migrating the live Gate A driver onto it means editing the one harness whose
mapped-folder/shipper/watchdog architecture was earned over seven failed runs,
with no way to exercise a Windows Sandbox run from a pull request. That
migration is deliberately left for its own change.

What prevents the two implementations drifting in the meantime is not hope.
`tests/gate_b/test_gate_b_harness_contract.py` reads the literals out of
**both** files and fails the build when they stop agreeing: the silent-install
flag, the four `station-set.json` lookup shapes, the prohibition on recursive
scans, the `ACTIVATION-RESULT.txt` field names, and the `summary.json` field
names both judges read.

## Budget ordering

| Bound | Where | Value |
|---|---|---|
| Soak | `Run-GateB.ps1 -SoakMinutes` (and the agent's matching default) | 1440 |
| Reboot mark | `Run-GateB.ps1 -RebootAtMinutes` | 720 |
| Reboot gap budget | `Run-GateB.ps1 -RebootGapBudgetMinutes` | 20 |
| Recovery budget | `Run-GateB.ps1 -RecoveryBudgetMinutes` | 15 |
| Resume task delay | `Register-GateBStartupTask.ps1 -StartupDelay` | PT2M |
| Host deadline | `Run-GateB.ps1 -HostDeadlineMinutes` | 1500 |
| CI job timeout | `.github/workflows/gate-b-reboot-soak.yml` | 1560 |

Each bound must **strictly** outlast the one inside it. Gate A learned this
expensively: a watchdog set longer than the host poll deadline turns every
long run into an unexplained timeout with no watchdog evidence. The host
deadline sits *below* the job timeout so `Run-GateB.ps1` is always the first
bound to fire and always gets to write its verdict document — a job GitHub
kills produces no verdict at all, only a red X. Equal values would be a coin
toss between the two.

`test_gate_b_harness_contract.py` asserts the whole chain — soak < host
deadline < job timeout, recovery budget ≤ gap budget, startup delay < gap
budget, agent soak default == runner soak default — so a fix applied in one
place cannot look correct while changing nothing. It caught exactly that
during this change: the host deadline and the job timeout were both 1560.

The recovery budget sitting **inside** the gap budget is not arbitrary:
recovery is observed by a *beat*, so a recovery budget larger than the gap
budget would describe a recovery no beat could ever record.

## Running it

```powershell
# Once, as the runner account: create the guest credential file.
Get-Credential | Export-CliXml C:\CivicCastGateB\guest-cred.xml

# The real thing (24h). Holds the box for over a day.
pwsh -File gate-b/Run-GateB.ps1 `
  -KitDir C:\CivicCastTester\kit-staging\<sha> `
  -BaseVhdx C:\CivicCastGateB\base\windows11-oobe-complete.vhdx `
  -GuestCredentialPath C:\CivicCastGateB\guest-cred.xml `
  -SourceSha <sha>

# A 40-minute rehearsal of the mechanics. The judge will report FAIL on its
# `plan` check -- that is correct and expected, not a regression.
pwsh -File gate-b/Run-GateB.ps1 ... -SoakMinutes 40 -RebootAtMinutes 20 -HostDeadlineMinutes 70

# Judge an existing evidence directory without running anything:
uv run python scripts/gate_b_verdict.py gate-b/evidence/<sha>/<stamp> --source-sha <sha>
```

Exit codes: `0` PASS, `1` FAIL, `2` anything that is not a reboot-soak finding
at all (`HYPERV_UNAVAILABLE`, `HARNESS_ERROR`, bad inputs, missing judge).

In CI it is `workflow_dispatch` only — never triggered by a candidate build,
because it occupies the one physical box for over a day and needs the operator
inputs above to exist beforehand.

## Promotion rule

Gate B's workflow is **informational only**. Per this repo's `CLAUDE.md`
"Owner gates", only Scott promotes a check to required, and only Scott flips
branch protection — no agent does it. Gate A's agreed bar is three consecutive
green runs; Gate B should not adopt a number until at least one real run has
happened and its true failure rate is known rather than guessed.

## Honest status

**What has been done** (2026-08-25):

- The harness, judge, tests, workflow and this document are written.
- All six PowerShell files parse cleanly under **both** PowerShell 7 and
  Windows PowerShell 5.1 (the agent runs under 5.1 inside a stock image).
- `gate-b/Test-GateBPrereqs.ps1` was **executed** on the `sandbox-lab` box
  under PowerShell 5.1; it correctly reported `verdict=unavailable`, wrote
  `HYPERV-UNAVAILABLE.txt`, and exited 3. The measured output is quoted above.
- `gate-b/answer/autounattend.xml` parses as XML and carries a placeholder
  password, asserted by a test.
- The judge's tests pass against synthetic evidence.

**What has NOT been done:**

- **No 24-hour soak has been run.** No VM has been provisioned, no candidate
  has been installed by this harness, no reboot has been performed, and no
  `gate-b-verdict.json` has ever been produced from real evidence.
- **Hyper-V is not enabled on this box**, so the harness's provisioning,
  install, beat, reboot and evidence-pull paths have never executed at all.
  They are statically verified only.
- **`tests/gate_b/fixtures/` is deliberately empty** of captured run evidence.
  Gate B's tests build every evidence directory synthetically, and
  `tests/gate_b/fixtures/README.md` records why: a fabricated
  "`pass-2026-XX-XX/`" directory that read as a captured run would be exactly
  the authored-truth failure this gate exists to eliminate. A synthetic PASS
  in the test suite means "the judge would pass evidence shaped like this",
  never "a candidate passed".
- **The spare-physical-box path is designed and documented, not built.** Two
  of its four steps need work that does not exist here.

When the first real run happens, follow `tests/gate_b/fixtures/README.md`:
copy the evidence in verbatim — including whatever it got wrong — and assert
its **actual** verdict.
