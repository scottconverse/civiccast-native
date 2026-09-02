# Windows Release Trust And Verification

> **Historical: retired WSL2 release-trust guide, applies only to the
> appendix below.** `civiccast-native` has no public installer asset yet.
> The rc-numbered instructions in the "Historical" appendix at the bottom of
> this page are preserved as historical evidence only; a native release must
> bind its own exact installer, SHA-256, signature, and proof, using the
> steps in this page's current sections.

## Current Release State

`v1.0.0-beta.1` is the current release. It was delivered by USB, not by a
GitHub Release download -- there is no GitHub-hosted installer asset to
verify for it.

`v1.0.0-beta.2` is the current owner-held unpublished candidate (unpublished;
no installer asset). It is intended to be the first downloadable beta
candidate: `setup.exe`, per-pack runtime `.ccpack` assets, and a
`SHA256SUMS.txt` checksum file, published as a **prerelease** at
<https://github.com/scottconverse/civiccast-native/releases> -- watch that
page, not `scottconverse/civiccast` (the retired, separate WSL2-line
repository) and not any `v1.0.0-rcNN` tag, which belongs to that other
repository. See
[`docs/releases/release-truth.yaml`](../releases/release-truth.yaml) for the
authored release-state record.

This page explains how an operator should verify a CivicCast Windows setup
download before running it, once one is published.

## Read The Release Docs First

For a clean-machine proof, read these documents before downloading or running
anything:

1. [Beta Tester Start Here](../tester/START-HERE.md)
2. [Install CivicCast On Windows](../../INSTALL-WINDOWS.md)
3. This trust and verification page

Download only the asset attached to the exact tagged GitHub Release you were
told to use, and verify it against `SHA256SUMS.txt` and its sidecar before
installation.

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
| Signature | The artifact was Authenticode-signed by the stated release process (Azure Trusted Signing). See [CODE_SIGNING_POLICY.md](../../CODE_SIGNING_POLICY.md) -- this release chain carries no Sigstore/cosign step; Authenticode is the only code signature a Windows release asset carries. | It is not the same as Microsoft SmartScreen reputation unless Authenticode signing is explicitly present. |

Do not assume a candidate is Authenticode-signed. The active handoff and exact
artifact sidecar must state its actual signature status. A public beta should
report `Valid` and the approved publisher; a local `NotSigned` engineering build
is suitable only for an explicitly authorized local acceptance run and must not
be distributed as a public beta.

## Verify The Download With PowerShell

1. From the exact tagged GitHub Release, obtain these matching files and
   keep them together in one folder:
   - `civiccast-<version>-windows-setup.exe`
   - `civiccast-<version>-windows-setup.exe.sidecar.json`
   - `SHA256SUMS.txt`
   Use the exact release page, not a draft, an older prerelease, or a
   generic "latest" link.
2. Open PowerShell in the download folder.
3. Compute the local hash:

```powershell
$Version = "REPLACE-WITH-RELEASE-VERSION"
Get-FileHash ".\civiccast-$Version-windows-setup.exe" -Algorithm SHA256
```

4. Compare the `Hash` value with the SHA-256 value recorded for that filename
   in `SHA256SUMS.txt`, and cross-check it against the matching
   `civiccast-<version>-windows-setup.exe.sidecar.json` file. All three
   values must match exactly.

If they do not match, quarantine the package and request a replacement proof
bundle from the owner. Do not run an installer with a mismatched hash.

Do not trust stale local artifact paths or hashes copied from earlier proof
runs. The `SHA256SUMS.txt` and setup sidecar published with the exact
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
install manifest, and service/bootstrap metadata line up, and -- when the
sidecar claims `signed: true` -- the `.exe` genuinely carries an embedded
Authenticode certificate table. It should report blocked or failed when any
one is missing or inconsistent.

## Authenticode And SmartScreen Status

Each release must say whether the Windows setup executable is Authenticode
signed. If it is signed, verify the signature in PowerShell:

```powershell
$Version = "REPLACE-WITH-RELEASE-VERSION"
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

Install only the exact tagged release you were told to use, verified against
its own `SHA256SUMS.txt` and sidecar. Approved sources include:

- the official CivicCast GitHub Release,
- a release artifact set built by your organization from source, or
- an internal package repository your organization controls.

Do not install a CivicCast setup executable received through email, chat, a
shared drive, or an issue comment unless your organization independently checks
the hash and release provenance.

---

## Historical: retired rc line

Everything below describes the retired public WSL2 line
(`v1.0.0-rc18` and earlier, repository `scottconverse/civiccast`) that this
repository does not carry. It is preserved as historical evidence only. The
verification document it used to cite
(`docs/releases/v1.0.0-rc18-verification.md`) is not present in this
repository -- it is omitted below rather than linked, because it does not
exist on `main`.

<details>
<summary>Expand: retired WSL2-line (rc17-rc18) release state</summary>

`v1.0.0-rc18` was the most recently published release on that other line and
superseded `v1.0.0-rc17`. Its signed GitHub release assets and complete
manifest were public. `v1.0.0-rc13` was withdrawn on that line; only rc18
and its matching proof assets were the recommended install.

</details>
