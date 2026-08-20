# CivicCast Beta Test Handoff For Longmont Public Media

> **Release state: `v1.0.0-rc18` is the published controlled beta.** Its
> installer is built from the gate-cleared `main`, Authenticode-signed, and proven
> on a genuinely clean Windows host. rc17 remains the rollback target but carries
> the sixteen findings rc18 fixes. See `docs/releases/v1.0.0-rc18-verification.md`
> for exactly what has and has not been proven.

> **Use `v1.0.0-rc18`; do not install `v1.0.0-rc13`.** The earlier LPM clean install
> failed, and a later genuine clean-Windows run reproduced bootstrap and user-
> feedback defects. The current line carries rc15's clean-Windows repairs
> (which passed exact-public validation), rc16's published UI/UX repairs,
> the six audited rc17 beta-blocker fixes, and rc18's sixteen stage-gate
> remediations.

> The exact rc18 installer passed a clean-host install, launch, reinstall,
> uninstall and rc17-to-rc18 upgrade on a pristine Windows 11 guest, plus an
> interactive installer walkthrough. The full product path on a clean host was
> last proven against rc17's exact bytes on 2026-07-20; the write-up is in the
> [rc17 verification record](../releases/v1.0.0-rc17-verification.md).

Last updated: 2026-07-23; published rc18 controlled beta handoff

Audience: Longmont Public Media beta testers, station operators, technical
staff, and anyone observing the first real station-side CivicCast runs.

## Plain-English Summary

CivicCast `v1.0.0-rc18` is the current controlled beta for LPM evaluation and the most recently published release; `v1.0.0-rc17` is the rollback target.
Use only its release-matched installer, sidecar, manifest, and verification
record. Its rc15 foundation passed post-publication clean-machine validation
from a WSL-disabled baseline through cold-reboot recovery, and rc18's own exact
installer passed a clean-host install, launch, reinstall, uninstall and upgrade
on a pristine guest. The full product path on a clean host was last proven
against rc17's bytes on 2026-07-20 and has NOT yet been repeated on rc18 --
that is part of what this run is for. Preserve all logs and report any failure.

## What This Beta Is Meant To Exercise

The first approved rc18 run is deliberately narrower than a full station beta.
It is meant to answer:

- Can LPM install CivicCast on a real Windows station machine?
- Can staff complete first setup without developer help?
- Can the operator console run through normal station workflows?
- Can staff run a private rehearsal that copies and validates the exact
  recorded sample they selected, finalizes a private recording, and loads its
  resident preview without publishing it?
- Can staff create or upload recorded media, package it privately, explicitly
  approve Portal publication, and play it in the resident portal?
- What copy, controls, or workflow details confuse real operators?
- What equipment-specific issues appear only at the station?

## Release Build To Use

**Use `v1.0.0-rc18`. Do not download or run rc13.**

Expected SHA-256 and byte size must match rc18's own sidecar and artifact
manifest.

LPM release candidate artifact details:

| Field | Value |
| --- | --- |
| Release tag | `v1.0.0-rc18` |
| Source candidate identity | `v1.0.0-rc18` controlled beta |
| Candidate asset source | [Public GitHub release](https://github.com/scottconverse/civiccast/releases/tag/v1.0.0-rc18) |
| Windows installer | `civiccast-1.0.0-rc18-windows-setup.exe` |
| Release manifest | `civiccast-1.0.0-rc18-release-artifacts-manifest.json` |
| Installer size | Verify against the release's own sidecar and complete manifest |
| Installer SHA-256 | Verify the exact value in this release's sidecar and complete manifest; never reuse a copied hash from another candidate |
| Signature | Valid Authenticode signature from Scott Converse; installer and manifest Sigstore verification passed |
| Status | Controlled beta; proof boundary recorded in the [rc18 verification record](../releases/v1.0.0-rc18-verification.md). |

Optional reference files (proof kit, manifest, PDF, DOCX) must come from that
same rc18 release. Do not reuse old hashes.

## Before The Test

Use a Windows 11 machine that LPM can safely use for beta work. Do not run this
on a mission-critical live playout machine unless LPM has explicitly decided
that risk is acceptable.

Before starting:

- Use a local Windows account with administrator rights.
- Keep the Windows session logged in while setup or a test is running.
- Plug the machine into reliable power.
- Disable sleep during the acceptance run.
- Make sure virtualization is enabled in BIOS/UEFI.
- Make sure outbound HTTPS is allowed to GitHub, Microsoft/WSL services, and
  Ubuntu package sources.
- Leave at least **5 GB free for installation**, plus separate capacity for the
  short sample media and recordings used in the test. **rc17 and later:** the local AI
  models (Ollama summary and translation models) add roughly 15-20 GB more —
  CivicCast ensures the same three-tag target set and downloads only the tags
  still missing, automatically in the background after the base install
  finishes.
- Have a place to save the recovery kit that is not a public folder.
- Decide who is allowed to know the beta admin password.
- Decide how LPM will send reports privately to Scott.

Do not paste passwords, recovery codes, provider credentials, private meeting
content, or resident data into bug reports.

## Verify The Installer

The approved rc18 release includes a `.sidecar.json` file next to the
installer. It lists that exact installer's SHA-256 hash.
Always verify against the sidecar from the exact package you received; do not
trust a hash copied from anywhere else.

1. Open the handed-off `civiccast-<version>-windows-setup.exe.sidecar.json`
   that matches the installer and note its `sha256` value.
2. In PowerShell, in your download folder, run:

   ```powershell
   Get-FileHash .\<installer-filename>.exe -Algorithm SHA256
   ```

3. The two hashes must match exactly. If they do not, do not run the installer.
   Quarantine the package and ask Scott for a replacement proof bundle.

Do not assume the candidate is signed. The active handoff must state the actual
Authenticode status for the exact bytes. If it says `Valid`, confirm the named
publisher. If it says `NotSigned` or the value differs from the handoff, stop;
a local engineering build with `NotSigned` status is not approved for public distribution.
See [SMARTSCREEN-WALKTHROUGH.md](SMARTSCREEN-WALKTHROUGH.md) for the conditional
signature checks.

## Install And First Setup

1. Run the exact `.exe` named in the active LPM handoff.
2. Approve expected Windows prompts.
3. Let the installer prepare CivicCast and its WSL2 Ubuntu runtime. This step can
   take several minutes, but the screen must keep showing the current phase,
   step, elapsed time, and a regularly updating heartbeat. It must explicitly
   say if a restart is required. Missing or stale feedback is itself a defect;
   capture it immediately. (Report a permanent freeze or crash if
   the window never recovers.)
4. If Windows requires a reboot, record the exact prompt and reboot reason.
   After reboot, log back into the same Windows account and continue.
5. When the installer provides the operator console URL, open that URL exactly.
6. Create the first local admin.
7. Save or print the recovery kit.
8. Store the recovery kit somewhere LPM controls.
9. Confirm the operator console opens.
10. Open System Health. Install, storage, service, and database blockers must
    not be red. In the stock build, **Source preview unavailable** and disabled live
    start are expected because no production media probe is bundled.
11. After setup says it is done, record whether the setup window closed normally.
    If a CivicCast setup window remains open or Windows still shows a CivicCast
    setup process after the operator console is healthy, capture a screenshot and
    report it with the test notes.

Record:

- install start time;
- install finish time;
- whether a reboot happened;
- CivicCast version shown in the UI or health page;
- whether first admin setup succeeded;
- whether the recovery kit was saved;
- whether the setup window closed normally;
- any warning or error text.

Expected version:

```text
1.0.0-rc18
```

Known beta diagnostic note: the older R19 release (an earlier internal release
tag, predating the current rc numbering) could show `schema=unknown`
in packaged `/health` output. The LPM controlled-test candidate includes the
packaged schema lookup fix. If LPM still sees `schema=unknown`, report it with a
support bundle, but do not treat that label alone as a failed station workflow
when setup, login, saved state, and recording workflows are working.

## First-Day Smoke Test

Run this before any long soak.

### Setup And Health

- Confirm the operator console opens after closing and reopening the browser.
- Sign out and sign back in with the admin account.
- Confirm System Health opens.
- Create a support bundle, download the JSON file to Windows, and record its
  displayed SHA-256.
- Verify backup destination if LPM has one ready.
- Run restore rehearsal if the UI offers it.

### Source Or Test Media

Use an uploaded test clip or bundled/sample media. The stock build has no production
server-side media probe, so do not treat camera, NDI, SDI, encoder, preview, or
live-start behavior as part of this acceptance run. Record the expected
**Source preview unavailable** state and confirm live start remains disabled.

### Recording

- Create or upload sample recorded media.
- Run **Private rehearsal** and confirm the result identifies the exact sample,
  a finalized private recording, and a loaded resident preview.
- Keep it short. Packaging has no durable return-later job progress, so
  production-length recordings are outside this first acceptance run.
- Validate it and choose **Package for playback** as an authorized publish
  operator or setup administrator.
- Confirm the recording remains private before approval.
- Approve only the Portal surface.
- Confirm resident playback works after approval.

### Resident View

- Open the resident/public view in another browser.
- Confirm the station name and current state look right.
- Confirm the approved recording plays; confirm unapproved media remains private.

## Recommended LPM Beta Runs

### Run 1: Clean Install And First Setup

Goal: prove LPM can install and set up CivicCast without developer intervention.

Pass if:

- installer hash matched;
- installer completed;
- operator console opened;
- first admin was created;
- recovery kit was saved;
- System Health opens;
- no blocking setup error remains.

### Run 2: Operator Workflow Rehearsal

Goal: walk through normal staff behavior.

Use a staff member who did not build the product if possible.

Cover:

- sign in;
- station setup review;
- confirm the expected source-preview-unavailable state and disabled live start;
- create or upload a short sample recording;
- run **Private rehearsal** and confirm the result names that exact sample, a
  finalized private recording, and a loaded resident preview;
- package and review the recording while it is still private;
- approve only the Portal surface and verify resident playback;
- resident preview;
- support bundle creation;
- notes on confusing wording.

Long soaks, SDI/device proof, live source work, and downstream station-output
testing are deliberately deferred. They require a later candidate with a real
server-side source probe and separate station/integrator acceptance; rc18 does
not claim those paths.

## What To Capture In Every Report

Use this shape for each report:

```text
Tester:
Date/time:
Machine:
Windows version:
CivicCast version:
Installer filename:
Installer SHA-256 checked: yes/no
Run type: install / smoke / recording / soak / real equipment
What we tried:
What worked:
What failed:
Exact error text:
Screenshots attached: yes/no
Downloaded support bundle filename:
Support bundle SHA-256:
Secrets checked/redacted: yes/no
Would this block another beta run: yes/no
```

## What Counts As A Blocking Issue

Stop and report immediately if:

- the installer hash does not match;
- the installer cannot complete;
- the operator console cannot open;
- first admin setup fails;
- login fails after first admin setup;
- the recovery kit cannot be saved;
- System Health cannot open;
- CivicCast reports the wrong version;
- a recording cannot be created or finalized;
- the app loses health during a soak;
- the UI freezes or crashes;
- a support bundle exposes secrets;
- a reboot happens during a soak without being planned and recorded.

## What Is Useful Feedback Even If It Is Not Blocking

Please report:

- unclear wording;
- buttons or screens that feel out of order;
- missing station-specific terms;
- workflows that require too many clicks;
- places where staff do not know what to do next;
- logs or support-bundle steps that feel too technical;
- places where LPM would need a checklist, label, or printed note.

Those are valuable beta findings even when the software technically works.

## Privacy And Secret Handling

Never send:

- admin passwords;
- recovery codes;
- setup nonce values;
- provider credentials;
- private keys;
- resident information;
- private meeting content;
- unredacted support bundles in public channels.

Screenshots are fine only after checking that they do not show secrets or
private content.

## If Something Goes Wrong

1. Stop the test at the safest point.
2. Write down the exact on-screen wording.
3. Take a screenshot if it does not expose secrets.
4. Create a support bundle from System Health if possible, then use **Download
   support bundle** to save its JSON file on Windows.
5. Fill out the report shape above.
6. Send it through the private beta channel Scott provided.

Do not try to repair by installing developer tools, running from source, editing
runtime files, or downloading a different release unless Scott explicitly asks
for that.

## Reference Docs

- Tester start page: `docs/tester/START-HERE.md`
- First broadcast checklist: `docs/tester/first-broadcast-checklist.md`
- Support bundle instructions: `docs/tester/support-bundle-instructions.md`
- Bug report template: `docs/tester/bug-report-template.md`
- User manual: `docs/USER-MANUAL.md`
- Release verification: `docs/releases/v1.0.0-rc18-verification.md`
- Windows release trust: `docs/install/windows-release-trust.md`

## Current Beta Boundary

rc13 is withdrawn and completed no valid clean-Windows proof. rc18 is the most
recently published release; rc17 remains available as the rollback target but
carries the sixteen findings rc18 fixes. Use an rc18
executable only after verifying its exact
filename, SHA-256, byte size, and actual signature status against the public
release. The stock build must show **Source
preview unavailable** and keep live start disabled without an integrator-
provided media probe. The bounded acceptance path is recorded media → exact-
sample private rehearsal → private package → Portal approval → resident
playback. The recovery drill covers the database only, not media,
configuration, or credentials.

Treat the beta as controlled evaluation software until the LPM station-device evidence
is complete.

Known rc15-era installer issue, fixed in this line: a still-open rc15 installer could briefly show a stale
restart screen after setup is already healthy. Close and reopen it; saved
progress is retained. That display-state defect was fixed from the rc17 line
onward and did not change the published rc15 assets, which remain immutable
history.
