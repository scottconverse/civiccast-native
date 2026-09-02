# Technical Tester Walkthrough

## Release State

`v1.0.0-beta.1` is the current release. It was delivered by USB, not a
GitHub download. `v1.0.0-beta.2` is the current owner-held unpublished
candidate and is intended to be the first downloadable one:
`setup.exe` + `.ccpack` runtime packs + `SHA256SUMS.txt`, published as a
prerelease at <https://github.com/scottconverse/civiccast-native/releases>.
See [`docs/releases/release-truth.yaml`](../releases/release-truth.yaml) for
the authored release-state record.

Use this path if you are validating the installer package, runtime bootstrap,
and provider setup proofs.

For a full release-owner station pass, use
[Public Station Implementation Walkthrough](station-implementation-walkthrough.md)
after the release gates and soak evidence are complete.

## Package Acquisition

1. **If you were given a USB-delivered `v1.0.0-beta.1` station:** there is no
   GitHub download for it; follow the handoff you were given.
2. **If you were given a downloadable `v1.0.0-beta.2` (or later) candidate:**
   use the exact `setup.exe`, `SHA256SUMS.txt`, and `setup.exe.sidecar.json`
   from that release, plus any `.ccpack` runtime packs the install needs.
3. Verify the SHA-256 value against the active handoff or checksum asset.
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
