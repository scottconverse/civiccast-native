# Technical Tester Walkthrough

> **Historical Beta 10 walkthrough.** Beta 11 is the current release. Use the
> [current User Manual](../USER-MANUAL.md), [Windows install guide](../../INSTALL-WINDOWS.md),
> and [Beta 11 verification record](../releases/v1.0.0-beta.11-verification.md)
> for current package and operating guidance; the release-specific checks below
> describe Beta 10 only.

## Release State

`v1.0.0-beta.10` was the current published release when this walkthrough was
written (published 2026-10-02); use only the exact release named
in the handoff. It is `setup.exe` + `.ccpack` runtime packs + `SHA256SUMS.txt`
+ `setup.exe.sidecar.json`, published as a GitHub pre-release (a "Beta
Candidate", not a production release) at
<https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.10>.
`v1.0.0-beta.7` was a download-only upgrade proven for stations already on
`v1.0.0-beta.5`; it is now superseded history, as are beta.5, beta.4 and
`v1.0.0-beta.3` (the first downloadable release).
`v1.0.0-beta.1` (USB-delivered, no GitHub download) is also superseded.
`v1.0.0-beta.2` was never published -- it exists only as an internal Gate A
upgrade-baseline kit.
See [`docs/releases/release-truth.yaml`](../releases/release-truth.yaml) for
the authored release-state record.

Beta 10 was a beta candidate. Gate A (automated station
acceptance): the clean-install lane passed, 10 of 10 criteria, run locally in
Windows Sandbox on 2026-10-02 against exactly this build; the cross-version
(upgrade) lane and the download-only lane were not run (waived by the owner for
this publication). The human/station acceptance pass is not done. Its lab
checks do not replace testing the exact installer you downloaded. See
[`docs/releases/v1.0.0-beta.10-verification.md`](../releases/v1.0.0-beta.10-verification.md)
and
[Known Limitations](known-limitations.md#historical-beta-10-live-caption-evidence)
for the current captions evidence boundary.

Use this path if you are validating the installer package, runtime bootstrap,
and provider setup proofs.

For a full release-owner station pass, use
[Public Station Implementation Walkthrough](station-implementation-walkthrough.md)
after the release gates and soak evidence are complete.

## Package Acquisition

1. For a first install, use the complete signed USB/LAN kit named in the
   handoff, including its `station\` model bundle. For an in-place upgrade,
   use the exact installer and runtime packs named by the handoff.
2. For a GitHub download, use the exact `setup.exe`, `SHA256SUMS.txt`, and
   `setup.exe.sidecar.json` from the published release. For USB/LAN, use its
   hash-pinned delivery manifest instead; it need not contain the GitHub sidecar.
3. Verify the SHA-256 and Authenticode publisher against the applicable handoff
   and manifest.
4. Do not use repository source ZIPs, tester handoff binaries, or Git LFS-backed
   files for normal installer acquisition.
5. Record the CivicCast version or commit SHA in your notes.

## Installer Path

1. Run the Windows setup app on Windows 11.
2. Confirm CivicCast installs and registers its Windows service through the
   SCM.
3. Confirm managed storage and upload folders are created.
4. Confirm the local API answers `/health`.
5. Confirm `/operator/` and the resident portal are served from packaged build
   assets.

## Operator Path

1. Create first admin and save the recovery kit.
2. Verify backup and run the database restore drill; record its explicit
   media/configuration/credential limits.
3. Confirm the Live Room fails closed with **Source preview unavailable** when
   no server-side media probe is configured.
4. Create or upload short sample media, run the private rehearsal, and confirm
   the evidence identifies the exact sample, finalized recording, and resident
   preview.
5. Package a validated recording, prove it remains private before approval,
   publish only to Portal, and verify public HLS playback.
6. Generate and download a support bundle, then inspect its redaction.
7. Confirm provider setup cards name required proof and do not expose secrets.

## Optional Advanced Evidence

Technical testers can collect CLI evidence when useful:

```powershell
civiccast installer beta-handoff --json
civiccast doctor --json
```

Do not share raw environment dumps. Use the support bundle unless a maintainer
asks for a specific redacted command output.
