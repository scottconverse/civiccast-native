# Technical Tester Walkthrough

> **Release state: `v1.0.0-rc18` is the published controlled beta.** Its
> installer is built from the gate-cleared `main`, Authenticode-signed, and proven
> on a genuinely clean Windows host. rc17 remains the rollback target but carries
> the sixteen findings rc18 fixes. See `docs/releases/v1.0.0-rc18-verification.md`
> for exactly what has and has not been proven.

> rc18's own signed installer, sidecar, and complete manifest are public; its proof boundary is recorded in the [rc18 verification record](../releases/v1.0.0-rc18-verification.md).

Use this path if you are validating the installer package, runtime bootstrap,
and provider setup proofs.

For a full release-owner station pass, use
[Public Station Implementation Walkthrough](station-implementation-walkthrough.md)
after the release gates and soak evidence are complete.

## Package Acquisition

> **Current beta:** rc13 is withdrawn. Use only the public `v1.0.0-rc18`
> release with its matching sidecar, manifest, and proof bundle.

1. For a controlled beta run, use the exact Windows setup executable,
   manifest, sidecar, and proof bundle from the current v1.0.0-rc18 release.
2. Verify the SHA-256 value against the active handoff or checksum asset.
3. Do not use repository source ZIPs, tester handoff binaries, or Git LFS-backed
   files for normal installer acquisition.
4. Record the CivicCast version or commit SHA in your notes.

## Installer Path

1. Run the Windows setup app on Windows 11.
2. Confirm WSL2 Ubuntu 24.04 detection or install/resume handling works.
3. Confirm Python, FFmpeg, and CA packages install inside WSL2.
4. Confirm CivicCast installs from the bundled wheelhouse with the
   `captions-runtime` extra.
5. Confirm managed storage and upload folders are created.
6. Confirm the local API answers `/health`.
7. Confirm `/operator/` and the resident portal are served from packaged build
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
