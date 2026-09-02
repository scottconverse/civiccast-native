# CivicCast Tester Packet - Start Here

> **Historical: retired WSL2 tester packet, not native CivicCast guidance.**
> `civiccast-native` ships the native Windows service and no WSL2 runtime. The
> rc-numbered release references below belong to the retired product line and
> are preserved only as historical evidence.

> **Release state: `v1.0.0-rc18` is the published controlled beta.** Its
> installer is built from the gate-cleared `main`, Authenticode-signed, and proven
> on a genuinely clean Windows host. rc17 remains the rollback target but carries
> the sixteen findings rc18 fixes. See `docs/releases/v1.0.0-rc18-verification.md`
> for exactly what has and has not been proven.

> **Windows beta testing is open with `v1.0.0-rc18`.** rc13 is withdrawn; do not install it or
> an earlier prerelease. Download only from the
> [public rc18 release](https://github.com/scottconverse/civiccast/releases/tag/v1.0.0-rc18).

The current controlled beta is `v1.0.0-rc18`, which carries forward rc15's
clean-Windows installer repairs (its exact installer passed clean-Windows
installation from a WSL-disabled baseline, first setup, the bounded
recorded-media workflow, service restart, and cold-reboot recovery), rc16's
published UI/UX repairs, the six audited rc17 beta-blocker fixes, and rc18's
sixteen stage-gate remediations. The
rc17 installer
completed its own full clean-host lifecycle walkthrough on 2026-07-20 and
passed — zero-restart install, first admin and recovery kit, backup and scoped
database restore, private rehearsal and packaging, the publish privacy gate,
resident playback, and unaided cold-reboot recovery. Captions were not
exercised in that pass. Full results are in the
[rc18 verification record](../releases/v1.0.0-rc18-verification.md). Do
not test from source; use the release-matched installer and proof bundle.

This packet is for people testing the CivicCast package named in their active
tester handoff. rc13's earlier lab run was not a valid clean-Windows proof. A
later genuine clean-host run failed during WSL/bootstrap setup and exposed
missing user feedback. See the corrected
[rc13 incident record](../releases/v1.0.0-rc13-verification.md). Keep the later
operator steps below as the checklist for the replacement candidate, but do not
start them with rc13 or an older package.

## Clean-Machine Test Rule

Start by reading the docs, then run the installer. For a clean Windows proof,
read these before launching anything:

1. This page.
2. [Install CivicCast On Windows](../../INSTALL-WINDOWS.md).
3. [Windows Release Trust And Verification](../install/windows-release-trust.md).
4. The [rc18 verification record](../releases/v1.0.0-rc18-verification.md).

Your proof report must state that these docs were read and must list any
disagreement between the docs, GitHub Release assets, manifest, sidecar, and installer UI.

## Before You Run The Installer

Windows may show a blue **Windows protected your PC** screen. That screen is not
approval. Read [SMARTSCREEN-WALKTHROUGH.md](SMARTSCREEN-WALKTHROUGH.md), then
compare the exact hash, signature status, and publisher with the active handoff
before clicking through it.

## Pick Your Path

- **Non-technical tester:** use
  [nontechnical-walkthrough.md](nontechnical-walkthrough.md). You should not
  need a terminal.
- **Technical tester or station admin:** use
  [technical-walkthrough.md](technical-walkthrough.md) when you want to inspect
  evidence, CLI output, or live provider proof.
- **Meeting-night dry run:** use
  [first-broadcast-checklist.md](first-broadcast-checklist.md).
- **Longmont Public Media beta:** use
  [lpm-beta-test-handoff.md](lpm-beta-test-handoff.md).
- **Before reporting a problem:** create a support bundle and use
  [bug-report-template.md](bug-report-template.md).
- **Closed or lost the recovery kit:** use
  [recovery-kit-help.md](recovery-kit-help.md). Do not paste recovery codes or
  secrets into a report.

## What You Should Be Able To Do

1. Verify the public-release Windows proof kit or setup executable against its
   matching manifest, sidecar, and checksum.
2. Run the Windows setup app. Keep at least **5 GB free** for the base
   install; recordings, media, backups, and downloaded caption models need
   additional storage. **rc17 and later:** the local AI models (Ollama summary and
   translation models) add roughly 15-20 GB on top of that — CivicCast
   ensures the same three AI model versions (the fixed summary/translation
   model set) are present and downloads only the ones still missing,
   automatically in the background after the base install finishes,
   not before.
3. Let it prepare WSL2 Ubuntu 24.04 (a Windows compatibility layer that runs
   the Linux-based CivicCast service in the background), runtime dependencies,
   local storage, and the CivicCast service when your handoff names a
   gate-cleared package (a package your tester handoff confirms has passed
   release review). **(rc17 and later: also provisions the local Ollama AI runtime and
   its standard model set.)**
4. Open the operator console from the installer handoff.
5. Create the first admin and save the recovery kit.
6. Verify backup and run the database restore drill; record that media,
   configuration, and credentials remain separate recovery work.
7. Confirm the stock build fails closed with **Source preview unavailable** when no
   server-side media probe is configured.
8. Upload or create a test recording, then run the private rehearsal and
   confirm it proves that exact sample and a finalized private recording.
9. Package the recording.
10. Confirm it is private before approval, publish only to Portal, and confirm
   resident playback.
11. Create and download a redacted support bundle.
12. Optional: save provider details in Setup and confirm the provider remains
    marked "needs live proof" until controlled proof exists.

## Known Limits

Read [known-limitations.md](known-limitations.md) before testing. Do not use
repository source ZIPs, tester handoff files, or Git LFS-backed files for a
normal install. Optional external providers, ActivityPub public federation, and
provider live proofs remain gated unless your station has controlled credentials
and redacted evidence.

For the current claim boundary, read
[../releases/v1.0.0-rc18-verification.md](../releases/v1.0.0-rc18-verification.md).
The withdrawn rc13 incident record is retained at
[../releases/v1.0.0-rc13-verification.md](../releases/v1.0.0-rc13-verification.md).

## Installer Identity — verify before you run it

- Filename: `civiccast-1.0.0-rc18-windows-setup.exe`
- Size: 243,742,408 bytes
- SHA-256: `af4d2017c6287eaed8cb4b1553d539281fc14c3e3863869c0ea5b8d2e73c311b`
- Signature: valid Authenticode signature from Scott Converse
  (`CN=Scott Converse, O=Scott Converse, L=Longmont, S=co, C=US`),
  Microsoft-timestamped; installer sidecar and complete manifest verified.

If your download's size or hash does not match these values, stop and report it
— do not run the file.

An rc15-era display issue, where a still-open installer could briefly show a
stale restart screen after the runtime had already become healthy, is fixed in
this line.
