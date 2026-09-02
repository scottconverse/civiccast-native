# "Windows protected your PC" — what to expect, and what to do

> **Historical: retired WSL2 installer walkthrough, not native CivicCast
> guidance.** `civiccast-native` has no public installer asset. Preserve the
> rc-numbered instructions below as historical evidence only.

> **Release state: `v1.0.0-rc18` is the published controlled beta.** Its
> installer is built from the gate-cleared `main`, Authenticode-signed, and proven
> on a genuinely clean Windows host. rc17 remains the rollback target but carries
> the sixteen findings rc18 fixes. See `docs/releases/v1.0.0-rc18-verification.md`
> for exactly what has and has not been proven.

> **Release state:** `v1.0.0-rc18` is the current controlled beta and the most recently published release; `v1.0.0-rc17` is the rollback target. Run
> only the exact installer from its signed GitHub release asset set.

When you open a CivicCast installer, Windows may show a blue SmartScreen page.
That page alone does not prove the file is safe, signed, or approved. Verify the
exact filename, SHA-256, and signature status in the active handoff first.
("Active handoff" means the tester packet you were given for this release —
see `docs/tester/START-HERE.md` if you don't have one.)

> **Do not install rc13.** `v1.0.0-rc18` is the current controlled beta and the most recently published release; `v1.0.0-rc17` is the rollback target.
> Use this SmartScreen guidance with its active tester handoff and matching
> proof assets.

---

## For the operator (no technical background needed)

### Why this happens

SmartScreen reputation and Authenticode signing are separate. In plain terms:
SmartScreen's warning is about download popularity, not about whether the file
is genuinely from us — a brand-new, genuinely signed release can still show
this screen. A signed new release can still lack reputation, while a
`NotSigned` file can show an unknown publisher. Follow the active
handoff; do not click through an identity or status that differs from it.

### What you'll see, and exactly what to click

1. You double-click the CivicCast installer (`civiccast-...-windows-setup.exe`).
2. A blue screen appears titled **"Windows protected your PC."**
3. Click the small text link that says **More info**.
4. Compare the Publisher field with the exact signature status and publisher in
   the active handoff. If they differ, stop. Click **Run anyway** only when the
   handoff explicitly authorizes that exact publisher and signature status for
   that exact SHA-256 — the hash must match too, not just the publisher name.
5. The real CivicCast Installer window opens, and setup continues normally from here. Windows will
   ask for admin approval later in setup, at **Set up Windows helper**.

That's it — two clicks past the warning screen, and you've confirmed it's really from us.

### Want to be extra sure before you click "Run anyway"?

The strongest check is a SHA-256 hash match against the sidecar file published
with the release — a hash match is mandatory before running the installer,
and signature expectations are candidate-specific. Computing that hash needs
a command (`Get-FileHash`, shown in the **For IT / technical verification**
section below). If that's not something you're set up to run yourself, ask
your IT contact to run it for you before you click "Run anyway."

---

## For IT / technical verification

Use these checks against the exact candidate handoff:

### 1. Confirm the signature (identity + integrity)

```powershell
$Version = "REPLACE-WITH-APPROVED-VERSION"
Get-AuthenticodeSignature ".\civiccast-$Version-windows-setup.exe" | Format-List Status, SignerCertificate
```

If the handoff says signed, expect `Status: Valid` and the exact named signer.
If it says `NotSigned`, that file is local-acceptance-only and must never be
treated as a public beta download.

### 2. Confirm the SHA-256 hash matches the handed-off sidecar

```powershell
$Version = "REPLACE-WITH-APPROVED-VERSION"
Get-FileHash ".\civiccast-$Version-windows-setup.exe" -Algorithm SHA256
```

Compare against the `sha256` value in the `.sidecar.json` published alongside
the installer in the exact approved replacement release. They must match. Do
not use rc13, a generic latest link, an older prerelease, or a detached sidecar.

### 3. Allowlist by publisher or hash

Once verified, IT can allowlist a signed build by its approved publisher or any
approved build by exact hash, according to local policy.

### Why SmartScreen still warns on a signed installer

SmartScreen reputation is per-file and accrues with download volume; a newly issued certificate has
none yet, and Microsoft's 2026 Trusted-Signing certificate-authority changes reset reputation for
new signers industry-wide (extended-validation certificates no longer bypass this either). The
warning shows the verified publisher and diminishes as reputation builds. See `CODE_SIGNING_POLICY.md`
for the signing posture.
