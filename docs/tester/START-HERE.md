# CivicCast Tester Packet - Start Here

> **Historical: retired WSL2 tester packet, not native CivicCast guidance,
> applies only to the appendix below.** `civiccast-native` ships the native
> Windows service and no WSL2 runtime. The rc-numbered release references in
> the "Historical" appendix at the bottom of this page belong to the retired
> product line and are preserved only as historical evidence.

## Current Release

`v1.0.0-beta.3` is the current release and the first **downloadable** one:
`setup.exe`, the five runtime `.ccpack` packs, a `SHA256SUMS.txt` checksum
file, and a signed `setup.exe.sidecar.json` are attached to the
[`v1.0.0-beta.3` GitHub Release](https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.3)
as a **prerelease** -- watch
<https://github.com/scottconverse/civiccast-native/releases>, not
`scottconverse/civiccast` (the retired, separate WSL2-line repository) and
not any `v1.0.0-rcNN` tag, which belongs to that other repository. See
[`docs/releases/release-truth.yaml`](../releases/release-truth.yaml) for the
authored release-state record.

`v1.0.0-beta.1` (USB-delivered, no downloadable assets) is now superseded.
`v1.0.0-beta.2` was never published -- it exists only as an internal Gate A
upgrade-baseline kit, never a release a tester receives.

`v1.0.0-beta.4` is the next candidate and, as of this page, the current
owner-held unpublished candidate (unpublished; no installer asset) -- it
does not change the install story below, which still targets
`v1.0.0-beta.3` as the current release. **If you are reading this after
Scott has told you a new beta is available, check
[`docs/releases/release-truth.yaml`](../releases/release-truth.yaml) first
-- it is the single source of truth for which tag is current, and this page
may not have been updated yet.**

A first-time install on a station with no prior CivicCast install needs the
USB model bundle even with `v1.0.0-beta.3` published -- the GitHub download
alone is the setup executable and runtime packs, not the ~21 GB model
bundle. **Upgrading from `v1.0.0-beta.1`:** copy the whole `beta.3` kit
(`setup.exe` plus the `station\` folder beside it) to the station and run
`setup.exe` over the existing install -- recordings, settings, database, and
AI models are kept and the schema migrates. Do not run `setup.exe` alone
from a `beta.1` install; see
[`docs/releases/2026-09-02-beta1-to-beta2-fresh-install-only.md`](../releases/2026-09-02-beta1-to-beta2-fresh-install-only.md)
for why. From `v1.0.0-beta.3` on, an upgrade of an already-installed station
is download-only (`setup.exe` plus the runtime packs, no `station\` folder
needed) and keeps the station's existing recordings, database, and AI
models -- this is how a `beta.3` station upgrades to `beta.4` once `beta.4`
publishes.

## Clean-Machine Test Rule

Start by reading the docs, then run the installer. For a clean Windows proof,
read these before launching anything:

1. This page.
2. [Install CivicCast On Windows](../../INSTALL-WINDOWS.md).
3. [Windows Release Trust And Verification](../install/windows-release-trust.md).

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

1. Verify the release Windows proof kit or setup executable against its
   matching manifest, sidecar, and checksum (`SHA256SUMS.txt`).
2. Run the Windows setup app. Keep at least **5 GB free** for the base
   install; recordings, media, backups, and downloaded caption models need
   additional storage. The local AI models (Ollama summary and translation
   models) add roughly 15-20 GB on top of that for a first install using the
   USB bundle -- CivicCast ensures the same three AI model versions (the
   fixed summary/translation model set) are present and downloads only the
   ones still missing, automatically in the background after the base
   install finishes, not before.
3. Let it prepare local storage, runtime dependencies, and the CivicCast
   service when your handoff names a gate-cleared package (a package your
   tester handoff confirms has passed release review). Also provisions the
   local Ollama AI runtime and its standard model set.
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

## Installer Identity -- verify before you run it

Verify the exact filename, size, SHA-256, and Authenticode signature named in
your active tester handoff and in `SHA256SUMS.txt` before running any
installer. If your download's size or hash does not match the handoff, stop
and report it -- do not run the file. Retired-line installer identity values
(rc18 and earlier) are historical and do not describe a `civiccast-native`
release; see [Windows Release Trust And Verification](../install/windows-release-trust.md)
for the current verification steps.

---

## Historical: retired WSL2 line

Everything below describes the retired public WSL2 line
(`v1.0.0-rc18` and earlier, repository `scottconverse/civiccast`) that this
repository does not carry. It is preserved as historical evidence only, not
as current tester guidance. The verification documents it used to cite --
including the withdrawn `v1.0.0-rc13`'s incident record
(`docs/releases/v1.0.0-rc18-verification.md`, `v1.0.0-rc13-verification.md`)
-- are not present in this repository -- they are omitted below rather than
linked, because they do not exist on `main`.

<details>
<summary>Expand: retired WSL2-line (rc13-rc18) tester notes</summary>

`v1.0.0-rc18` was the published controlled beta on that other line, carrying
forward rc15's clean-Windows installer repairs (its exact installer passed
clean-Windows installation from a WSL-disabled baseline, first setup, the
bounded recorded-media workflow, service restart, and cold-reboot recovery),
rc16's published UI/UX repairs, the six audited rc17 beta-blocker fixes, and
rc18's sixteen stage-gate remediations. The rc17 installer completed its own
full clean-host lifecycle walkthrough on 2026-07-20 and passed --
zero-restart install, first admin and recovery kit, backup and scoped
database restore, private rehearsal and packaging, the publish privacy gate,
resident playback, and unaided cold-reboot recovery. Captions were not
exercised in that pass.

`v1.0.0-rc13`'s earlier lab run was not a valid clean-Windows proof. A later
genuine clean-host run failed during WSL/bootstrap setup and exposed missing
user feedback; rc13 was withdrawn and superseded by rc14.

That line's setup path let WSL2 Ubuntu 24.04 (a Windows compatibility layer
that ran the Linux-based CivicCast service in the background) prepare
runtime dependencies, local storage, and the CivicCast service.

Installer identity for the last published rc18 build:

- Filename: `civiccast-1.0.0-rc18-windows-setup.exe`
- Size: 243,742,408 bytes
- SHA-256: `af4d2017c6287eaed8cb4b1553d539281fc14c3e3863869c0ea5b8d2e73c311b`
- Signature: valid Authenticode signature from Scott Converse
  (`CN=Scott Converse, O=Scott Converse, L=Longmont, S=co, C=US`),
  Microsoft-timestamped; installer sidecar and complete manifest verified.

An rc15-era display issue, where a still-open installer could briefly show a
stale restart screen after the runtime had already become healthy, was fixed
on that line.

</details>
