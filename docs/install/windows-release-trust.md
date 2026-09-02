# Windows Release Trust And Verification

> **Historical: retired WSL2 release-trust guide, not native CivicCast
> guidance.** `civiccast-native` has no public installer asset. Preserve the
> rc-numbered instructions below as historical evidence only; a native release
> must bind its own exact installer, SHA-256, signature, and proof.

> **Release state: `v1.0.0-rc18` is the published controlled beta.** Its
> installer is built from the gate-cleared `main`, Authenticode-signed, and proven
> on a genuinely clean Windows host. rc17 remains the rollback target but carries
> the sixteen findings rc18 fixes. See `docs/releases/v1.0.0-rc18-verification.md`
> for exactly what has and has not been proven.

> **Release state:** `v1.0.0-rc18` is the most recently published release and
> supersedes `v1.0.0-rc17`. Its signed GitHub release assets and complete manifest
> are public; its proof boundary is recorded in the
> [rc18 verification record](../releases/v1.0.0-rc18-verification.md).

This page explains how an operator should verify a CivicCast Windows setup
download before running it.

## Read The Release Docs First

For a clean-machine proof, read these documents before downloading or running
anything:

1. [Beta Tester Start Here](../tester/START-HERE.md)
2. [Install CivicCast On Windows](../../INSTALL-WINDOWS.md)
3. This trust and verification page
4. [CivicCast v1.0.0-rc18 Candidate Verification](../releases/v1.0.0-rc18-verification.md)

`v1.0.0-rc18` is the most recently published release. Download only the asset attached to
that release and verify its sidecar before installation; see the rc18
verification record for what the exact rc18 installer has and has not yet
proven on a clean host.

Record that these documents were opened and read in the proof report. If the
approved package source, manifest, sidecar, installer UI, or docs disagree about the
version, filename, checksum, or next step, stop and report the mismatch before
installing.

## What You Are Checking

A CivicCast release can provide three different kinds of trust evidence:

| Evidence | What it proves | What it does not prove |
| --- | --- | --- |
| SHA-256 checksum | The file on your machine matches the owner-approved package or published release. | It does not identify the publisher by itself. |
| Release sidecar or manifest | The package, service metadata, and expected hash belong to the same release artifact set. | It does not replace checking the downloaded file hash. |
| Signature | The artifact was Authenticode-signed by the stated release process (Azure Trusted Signing). See [CODE_SIGNING_POLICY.md](../../CODE_SIGNING_POLICY.md) — this release chain carries no Sigstore/cosign step; Authenticode is the only code signature a Windows release asset carries. | It is not the same as Microsoft SmartScreen reputation unless Authenticode signing is explicitly present. |

Do not assume a candidate is Authenticode-signed. The active handoff and exact
artifact sidecar must state its actual signature status. A public beta should
report `Valid` and the approved publisher; a local `NotSigned` engineering build
is suitable only for an explicitly authorized local acceptance run and must not
be distributed as a public beta.

## Verify The Download With PowerShell

> **Current status:** rc13 is withdrawn. The approved bounded Windows beta is
> `v1.0.0-rc18`; apply the steps below to its exact public release assets.

1. From the exact approved replacement release, obtain these matching files
   and keep them together in one folder:
   - `civiccast-<approved-version>-windows-setup.exe`
   - `civiccast-<approved-version>-windows-setup.exe.sidecar.json`
   The bundle should also include the release manifest for an
   artifact-set-wide check. Use the exact approved release page, not a draft,
   an older prerelease, or a generic "latest" link.
2. Open PowerShell in the download folder.
3. Compute the local hash:

```powershell
$Version = "REPLACE-WITH-APPROVED-VERSION"
Get-FileHash ".\civiccast-$Version-windows-setup.exe" -Algorithm SHA256
```

4. Compare the `Hash` value with the SHA-256 value recorded in the matching
   `civiccast-<approved-version>-release-artifacts-manifest.json` or
   `civiccast-<approved-version>-windows-setup.exe.sidecar.json` file. The values must
   match exactly.

If they do not match, quarantine the package and request a replacement proof
bundle from the owner. Do not run an installer with a mismatched hash.

Do not trust stale local artifact paths or hashes copied from earlier proof
runs. The manifest and setup sidecar published with the exact approved
GitHub Release are the public source of truth.

## Verify The Release Manifest

Technical operators can also use CivicCast's package verifier after placing the
setup executable and sidecar in the same folder:

```powershell
uv run civiccast installer verify-package `
  --artifact ".\civiccast-$Version-windows-setup.exe" `
  --sidecar ".\civiccast-$Version-windows-setup.exe.sidecar.json" `
  --json
```

The verifier should report `ok` only when the artifact bytes, sidecar hash,
install manifest, and service/bootstrap metadata line up, and — when the
sidecar claims `signed: true` — the `.exe` genuinely carries an embedded
Authenticode certificate table. It should report blocked or failed when any
one is missing or inconsistent.

## Authenticode And SmartScreen Status

Each release must say whether the Windows setup executable is Authenticode
signed. If it is signed, verify the signature in PowerShell:

```powershell
$Version = "REPLACE-WITH-APPROVED-VERSION"
Get-AuthenticodeSignature ".\civiccast-$Version-windows-setup.exe" | Format-List
```

For a handoff that says the installer is signed, expected good output has
`Status` equal to `Valid` and the exact signer named by that handoff. A `Valid`
result confirms both publisher identity and that the file is unmodified since
signing. Any other result is a stop condition for public beta installation.

A freshly-signed installer can still trigger a Windows SmartScreen "Windows
protected your PC" prompt until the publisher builds up enough download
reputation with Microsoft. That prompt by itself is expected and is not a
stop condition as long as `Get-AuthenticodeSignature` reports `Status: Valid`
for the correct signer. SmartScreen reputation is a separate, slower-moving
signal from Authenticode validity; do not treat the absence of a SmartScreen
warning as proof of anything, and do not treat the presence of one as proof
the file is untrustworthy if Authenticode already reports `Valid`.

## Operator Rule

Do not install rc13. Install rc18 only from its matching artifacts. Approved
sources include:

- the official CivicCast GitHub Release,
- a release artifact set built by your organization from source, or
- an internal package repository your organization controls.

Do not install a CivicCast setup executable received through email, chat, a
shared drive, or an issue comment unless your organization independently checks
the hash and release provenance.
