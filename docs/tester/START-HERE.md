# CivicCast Tester Packet - Start Here

> **Current native testers:** CivicCast `v1.0.0-beta.12` is the current
> published GitHub pre-release, not a production release. Follow the
> [current User Manual](../USER-MANUAL.md), [Windows install guide](../../INSTALL-WINDOWS.md),
> [Windows release-trust guide](../install/windows-release-trust.md), and the
> exact [Beta 12 verification record](../releases/v1.0.0-beta.12-verification.md).
> The Beta 11/Beta 10 notes below are historical and do not qualify Beta 12.
> The rc-numbered appendix at the bottom describes the retired WSL2 product.

## Current Release

`v1.0.0-beta.12` is the current published GitHub pre-release, published
October 10, 2026, with the station-model distribution repair added October 11.
The release assets include the signed installer, five runtime packs, four
manual assets, checksum list, sidecar, Windows download helper, station-models
manifest and split station ZIP parts. Use the exact release-matched helper
described in the [Windows release-trust guide](../install/windows-release-trust.md);
its `-Install` option downloads and validates the complete kit before it runs
the installer with `/S`. Availability of the repaired full download is not
installation or operational acceptance.

The October 11 R9 attempt used the earlier incomplete public asset set on
MICROMONSTERPC, a previously used machine with residual ProgramData files and
model caches but no active CivicCast service or application. With the five
verified runtime packs flat beside `setup.exe`, pack staging returned child
exit 74. Placing the same bytes in the required sibling `packs\` directory
allowed staging to advance, but activation failed with actual installer exit
123 because four required signed station packs were missing and their
embedded-index URLs were empty. No service or first-admin account was created.
This result predates the repaired download; it is not clean-machine proof or a
result for the complete kit. R9 also observed optional Large Whisper download
bytes advancing while its box was unchecked and the UI showed **Not ready**.

The recorded Beta 11-to-Beta 12 CPU-only Sandbox upgrade exited 0, the
service/API were healthy at schema 0089, and the initial-data preservation
marker was saved. Initial three-channel HLS output and Whistle within capacity
were observed. The recorder wrapper then failed during its first JSON save
with `Cannot convert value to type System.String.`; no five-snapshot PASS
was recorded. A separate fresh offline Sandbox install using the repaired
public kit exited 0, activated the station, left the service `Running`, and
passed the offline Ollama and CPU faster-whisper self-tests. Its follow-on
first-admin/three-channel check failed with only the first Python traceback
line captured, so the cause is unresolved and complete UI/channel validation
is not established. Repair, upgrade retest, and sustained-operation results
are not recorded. See the [Beta 12 verification record](../releases/v1.0.0-beta.12-verification.md) and [GitHub
release](https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.12).


## Historical Beta 11 release snapshot (October 8, 2026)

<details>
<summary>Historical Beta 11 and Beta 10 release details</summary>

`v1.0.0-beta.11` is the current published release (published 2026-10-08),
recorded as `current` in the release-truth record. It is a GitHub
**pre-release** (a "Beta Candidate"), not a production release. For a published
GitHub release, use its `setup.exe`, runtime
`.ccpack` packs, `SHA256SUMS.txt`, and `setup.exe.sidecar.json` metadata from the
exact release page. For a USB/LAN field kit, use the complete kit's own hash-pinned
delivery manifest and do not require a GitHub sidecar that is not present. The
current published release is the
[`v1.0.0-beta.11` GitHub Release](https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.11)
-- watch
<https://github.com/scottconverse/civiccast-native/releases>, not
`scottconverse/civiccast` (the retired, separate WSL2-line repository) and
not any `v1.0.0-rcNN` tag, which belongs to that other repository. See
[`docs/releases/release-truth.yaml`](../releases/release-truth.yaml) for the
authored release-state record.

`v1.0.0-beta.10`, `v1.0.0-beta.7`, `v1.0.0-beta.5`, `v1.0.0-beta.4` and `v1.0.0-beta.3` (the first
downloadable release) are now superseded. `v1.0.0-beta.8` and `v1.0.0-beta.9`
were never published; their work is inside beta.10.
`v1.0.0-beta.1` (USB-delivered, no downloadable assets) is also superseded.
`v1.0.0-beta.2` was never published -- it exists only as an internal Gate A
upgrade-baseline kit, never a release a tester receives.

The October 8 Beta 11 package (producer source `b7cc3e7c`, build
`37827938199`) was refreshed on an existing Beta 11 host and had a brief
three-channel output check. A clean install, repair, Beta 10 upgrade, and long
capacity run were not performed for that exact package. Its 10-of-10 clean
install result belongs to Beta 10 only. See the [Beta 11 verification
record](../releases/v1.0.0-beta.11-verification.md) for the package boundary.

The superseded Beta 10 release passed its historical clean-install lane (10 of
10 criteria, run in Windows Sandbox on 2026-10-02). Its upgrade and download-only
lanes were not run. These are Beta 10 results, not Beta 11 qualification. See
[`docs/releases/v1.0.0-beta.10-verification.md`](../releases/v1.0.0-beta.10-verification.md).

The October 8 `b7cc3e7c` Beta 11 package's `setup.exe` is about 249 MiB; the large AI
components and roughly 21 GB `station\` model bundle are not release assets.
During install the setup window explains each component, uses a copy already on
the computer (**Found locally - verified**), and can download missing
components with a progress display and **Stop downloading** button. The
October 8 package was verified only as an in-place refresh of an existing Beta
11 host and a brief three-channel output check. A clean first install and
download-only first-install path were not run for that package. Use the complete
signed USB/LAN kit for a first install; a completed download is not proof that
station activation succeeded. See the [Beta 11 verification
record](../releases/v1.0.0-beta.11-verification.md) for the package boundary.

The following upgrade notes are historical and do not describe the current
Beta 11 upgrade path. **Historical Beta 1 upgrade:** copy the whole `beta.3` kit
(`setup.exe` plus the `station\` folder beside it) to the station and run
`setup.exe` over the existing install -- recordings, settings, database, and
AI models are kept and the schema migrates. Do not run `setup.exe` alone
from a `beta.1` install; see
[`docs/releases/2026-09-02-beta1-to-beta2-fresh-install-only.md`](../releases/2026-09-02-beta1-to-beta2-fresh-install-only.md)
for why. From `v1.0.0-beta.3` on, an upgrade of an already-installed station
is download-only (`setup.exe` plus the runtime packs, no `station\` folder
needed) and keeps the station's existing recordings, database, and AI
models. Beta.7 had download-only upgrade proof from beta.5; consult its exact
verification record for that evidence. Upgrade paths were not run for beta.10,
so that evidence is not acceptance of a beta.10 upgrade.

</details>

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
  [Field-Test Quick Start](../QUICKSTART-OPERATOR.md) and the current manual.
  Use the active handoff for the exact package procedure.
- **Technical tester or station admin:** use
  the [Beta 12 verification record](../releases/v1.0.0-beta.12-verification.md)
  for candidate evidence and limits, plus the active handoff for assigned
  checks.
- **Meeting-night dry run:** use
  [first-broadcast-checklist.md](first-broadcast-checklist.md).
- **Longmont Public Media beta:** use
  the active owner-authorized handoff; this repository's older LPM handoff is
  historical and is not the Beta 12 procedure.
- **Before reporting a problem:** create a support bundle and use
  [bug-report-template.md](bug-report-template.md).
- **Closed or lost the recovery kit:** use
  [recovery-kit-help.md](recovery-kit-help.md). Do not paste recovery codes or
  secrets into a report.

## What You Should Be Able To Do

1. Verify the release Windows proof kit or setup executable against its
   matching delivery manifest or, for a GitHub download, its sidecar and
   checksum (`SHA256SUMS.txt`).
2. Download and install only the exact Beta 12 set named by the active handoff.
   The release helper `download_windows_release_artifacts.ps1` with `-Install`
   verifies the installer, runtime packs and multipart station bundle, extracts
   the complete kit and runs setup with `/S`. The helper is documented in
   the [Windows release-trust guide](../install/windows-release-trust.md). A
   successful download does not prove that the installation or station is
   ready. Beta 12 has setup and activation evidence for a fresh repaired-kit
   install, but its follow-on first-admin/three-channel check failed with an
   unresolved Python startup cause; complete UI/channel validation is not
   established. See the verification record for the captured result.
3. Follow the active owner-authorized handoff for the named package and checks.
   Beta 12's recorded upgrade outcome and failed R9 public-assets first-install
   attempt are summarized above and detailed in the verification record. The
   repaired-kit Sandbox setup/activation succeeded, but the follow-on check
   failed without a recoverable Python error detail. No repair, upgrade retest,
   complete UI/channel validation, or sustained run is established.
4. Open the operator console on the station itself (the **Open operator
   console** button, or the **CivicCast Operator Console** shortcut).
5. Create the first admin and save the recovery kit.
6. Verify backup and run the database restore drill; record that media,
   configuration, and credentials remain separate recovery work.
7. Configure a supported source and run the server-side source probe during
   live pre-flight. Record what the probe reports; a passing probe does not
   establish sustained ingest, every output path, or external delivery.
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
