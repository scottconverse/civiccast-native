# Technical Tester Walkthrough

## Release State

`v1.0.0-beta.5` is the current published release (2026-09-09), recorded as
`current` in `release-truth.yaml`; use only the exact release named in the
handoff. The published beta.5 release is a download-only upgrade for
stations already on `v1.0.0-beta.4` (now superseded, as is `v1.0.0-beta.3`,
the first downloadable release):
`setup.exe` + `.ccpack` runtime packs + `SHA256SUMS.txt`, published as a
prerelease at <https://github.com/scottconverse/civiccast-native/releases>.
`v1.0.0-beta.1` (USB-delivered, no GitHub download) is also superseded.
`v1.0.0-beta.2` was never published -- it exists only as an internal Gate A
upgrade-baseline kit.
See [`docs/releases/release-truth.yaml`](../releases/release-truth.yaml) for
the authored release-state record.

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
