# Install CivicCast On Windows

> **This repository (`civiccast-native`) ships ONE product: the native
> Windows station.** No WSL, no Docker, no Linux install target -- see
> [BRANCHES.md](BRANCHES.md). It is a signed installer that registers a
> Windows service through the SCM and supervises the control plane,
> Postgres, NATS, and the media workers from a bundled runtime, at
> `C:\Program Files\CivicCast (Native)\`.
>
> **The native line is an owner-held development candidate and is not yet
> published** (per BRANCHES.md's "Release identity"). This page currently
> documents the one thing that is real and testable pre-release: recovering
> the operator-console setup handoff on an already-installed native station.
> A full install/download walkthrough will be written once a native release
> is published.
>
> **Everything below this notice, up to "If The Operator Console Says
> 'Could Not Read Setup State'," describes the retired public WSL2 line**
> (`v1.0.0-rc18` and earlier) that this repository does not carry. That
> product's full history, release artifacts, and verification docs live in
> the separate, private `scottconverse/civiccast` repository (see
> BRANCHES.md's "Where the old line went") -- the doc links and GitHub
> release URLs below point there, not here, and several no longer resolve
> from this repository. It is kept as historical reference, not as
> current install instructions for this repository.

> **Release state: `v1.0.0-rc18` is the published controlled beta.** Its
> installer is built from the gate-cleared `main`, Authenticode-signed, and proven
> on a genuinely clean Windows host. rc17 remains the rollback target but carries
> the sixteen findings rc18 fixes. See `docs/releases/v1.0.0-rc18-verification.md`
> for exactly what has and has not been proven.

> **Last published installer:**
> [`v1.0.0-rc18`](https://github.com/scottconverse/civiccast/releases/tag/v1.0.0-rc18),
> with its matching sidecar and complete manifest, plus an Authenticode signature
> (see [CODE_SIGNING_POLICY.md](CODE_SIGNING_POLICY.md); this release chain carries no Sigstore bundle).
> [`v1.0.0-rc17`](https://github.com/scottconverse/civiccast/releases/tag/v1.0.0-rc17)
> remains published as the rollback target, but it carries the sixteen findings
> rc18 fixes and is not a recommended install.

> **Proof state:** the exact rc18 installer passed a clean-host install, launch,
> reinstall, uninstall and rc17-to-rc18 upgrade on a pristine Windows 11 guest,
> plus an interactive installer walkthrough. The full product path below was
> last proven on a clean host against **rc17's** exact bytes, and has not yet
> been repeated on rc18. That rc17 run **completed** a full
> clean-host lifecycle walkthrough on 2026-07-20 — install with no restarts,
> first admin and recovery kit, backup and scoped database restore drill,
> private rehearsal and packaging, the pre-publication privacy check, Portal-only
> approval and resident playback, real local summary/translation inference,
> service relaunch, cold-reboot recovery, and reinstall. Verdict: **passed**
> (1 Minor, 1 Nit; no blocker/critical/Major — an initial Major uninstall
> data-retention finding was reviewed and downgraded to non-blocking; see the
> verification doc for detail).
>
> **Uninstalling — removing your station data.** When you uninstall, the
> uninstaller shows a **"Delete the application data"** checkbox. Check it to
> remove everything, including the ~19 GB Windows helper (the
> `CivicCast-Ubuntu-24.04` WSL distribution that holds the database and
> recordings). Leave it unchecked to keep your recordings and settings for a
> later reinstall; the uninstaller then tells you on screen exactly what was
> kept. Note two things if you keep the data: a later reinstall makes
> previously published recordings public again without a new approval, and a
> command-line **silent** uninstall (`/S`) keeps the data by default (it never
> shows the checkbox). To remove kept data by hand later, run
> `wsl --unregister CivicCast-Ubuntu-24.04` and delete `%USERPROFILE%\.civiccast`.
> Captions were not exercised in rc17's full-lifecycle walkthrough, and rc18 does not inherit that result either. Details in
> [CivicCast v1.0.0-rc17 Candidate Verification](docs/releases/v1.0.0-rc17-verification.md).

> **Do not use `v1.0.0-rc13` for a clean Windows installation.** A real
> bare-metal test with WSL and its Windows features absent exposed a release-
> blocking helper-bootstrap failure. rc13 is withdrawn from beta use.
> Use only `v1.0.0-rc18` and its matching proof assets.

`v1.0.0-rc18` is the published controlled beta. It carries rc15's
clean-machine installer repairs (validated on a WSL-disabled baseline through
cold-reboot recovery), rc16's published UI/UX repairs, the six audited
rc17 beta-blocker fixes, and the sixteen stage-gate remediations that define
this release. See the proof boundary above for what the exact rc18
installer has and has not yet proven itself.

This page explains the Windows test path for the current CivicCast line.
Preserve all logs and report any failure found during beta testing.

## Read This First

A clean-machine test starts with the documentation, not with a copied `.exe`.
Before running the installer, read these in order:

1. [Beta Tester Start Here](docs/tester/START-HERE.md)
2. This Windows install page
3. [Windows Release Trust And Verification](docs/install/windows-release-trust.md)
4. [CivicCast v1.0.0-rc18 Candidate Verification](docs/releases/v1.0.0-rc18-verification.md)
5. [CivicCast v1.0.0-rc13 Incident Record](docs/releases/v1.0.0-rc13-verification.md)

Record in the clean-machine proof report that each document was opened and read.
If the docs and the installer/proof package disagree about version, filename,
checksum, or expected next step, stop and report the mismatch before installing.

## What To Download

Download `civiccast-1.0.0-rc18-windows-setup.exe` only from the public
`v1.0.0-rc18` GitHub release. Do not use a draft, an older prerelease, a generic
"latest" link, or a copied asset whose release provenance you cannot verify.

Use the release asset meant for your test path. Do not install from the
repository source ZIP unless you are intentionally working as a developer. Do
not download files from `tester-handoff/`; those files coordinate automated
tester-machine work and are not the operator install path.

## Before Running It

Read [Windows Release Trust And Verification](docs/install/windows-release-trust.md).
Verify the release manifest, proof kit, and installer sidecar before running the
installer.

Leave at least **5 GB of free disk space** for the base installation. This
does not include station recordings, media, backups, or downloaded caption
models; plan those separately.

> **rc17 and later:** the local AI models (Ollama summary and translation
> models) are large on top of that: roughly 15-20 GB combined. CivicCast
> ensures the same three-tag target set (the fixed set of three Ollama model
> tags every install needs for summary and translation) and downloads only
> the tags still missing, automatically in the background after the base
> install finishes, not before, so budget the extra space even though
> nothing prompts for it during setup.

Windows may show a blue **Windows protected your PC** screen. Do not infer a
signature from that screen. The approved handoff must state the exact file's
actual Authenticode status. If signed, verify the named publisher; if the result
is `NotSigned` or differs from the handoff, stop. Read
[docs/tester/SMARTSCREEN-WALKTHROUGH.md](docs/tester/SMARTSCREEN-WALKTHROUGH.md) before
you run the installer so you know exactly what to click (two clicks) and why, plus how
to independently verify the file yourself first if you want extra confidence.

## What The Setup Path Does

Run the setup path and follow the screens. CivicCast guides:

- The local Windows helper setup CivicCast needs to run meeting tools on this
  computer.
- Local durable storage preparation.
- CivicCast service startup.
- Operator-console handoff.
- First-admin setup and recovery-kit creation.
- The local Ollama AI runtime (reused if a healthy install already exists,
  installed if absent) and the standard summary/translation models (the same
  three-tag target set on every install; only the tags still missing are
  downloaded), continuing in the background after the console is already
  open (rc17 and later).

You should not need Git, GitHub CLI, Git LFS, Python commands, Ubuntu commands,
or repository source files for a normal operator test.

You may still need to approve Windows administrator prompts. If Windows asks
for a restart while setting up the helper, restart and reopen the CivicCast
installer or setup instructions. The installer re-probes the helper
after reboot; it should continue when the helper is ready or show **Set up
Windows helper** again when repair is needed.

> **rc17 and later:** the installer does not expect exactly one prompt. If
> Windows asks for a restart while setting up the helper, expect to approve a
> Windows security prompt again when it resumes — a restart clears the
> earlier approval, so CivicCast re-elevates as a fresh step rather than
> carrying the first approval across the reboot.

Slow Windows setup must remain visibly active. The replacement installer shows
the current phase, step count, elapsed time, and a heartbeat that updates every
few seconds. The phase may take many minutes, but a static screen with no
heartbeat is not considered normal. Only the Windows administrator-consent
prompt should appear; helper command and PowerShell windows stay hidden. Restart
only when the installer explicitly says Windows requires it.

After a successful install, CivicCast registers a per-user runtime host at
Windows sign-in through an HKCU `Run` entry. The host keeps the WSL helper
available, polls CivicCast health, and restarts the helper or Linux service if
health is lost. No manual relaunch is expected after a normal reboot once the
one-time setup is complete. The runtime host does not perform the privileged
one-time Windows helper setup; if that step never completed, open CivicCast
Installer and choose **Set up Windows helper** for the required administrator
approval.

## If The Operator Console Says "Could Not Read Setup State"

**This is the current, applicable content in this repository.** It covers
the native Windows line's own install — the paths and executables below
(`CivicCast Native.exe`, `CivicCast (Native)`, `civiccast.native.runtime_cli`)
only exist on a native-line install; the retired public WSL2 line described
above (a different, archived repository) never had this recovery flow.

The operator console's first setup page needs the one-time handoff URL the
Windows installer creates — a plain console URL with no `?nonce=` on the end
cannot read setup state, cannot create the first administrator, and cannot
sign in. If the console shows:

> Could not read setup state. Open the operator console from the CivicCast
> installer handoff, then continue setup.

…and reopening CivicCast Setup and pressing **Open operator console** produces
the same result, the setup app could not read the handoff the installer stored.
That handoff lives in a registry key restricted to SYSTEM and Administrators, so
a setup app running without administrator rights cannot read it and opens the
console without it.

**Recover it on a native Windows station (no reinstall needed).** Either
option below reads the same registry-stored handoff and requires
administrator rights on the station — use whichever is more convenient.

**Option A — restore it in CivicCast Setup (recommended):**

1. Run, adjusting the path if you installed somewhere other than the default:

   ```
   "C:\Program Files\CivicCast (Native)\CivicCast Native.exe" --civiccast-restore-setup-handoff
   ```

2. Approve the Windows administrator prompt. CivicCast re-reads the stored
   handoff and updates Setup's own cache — no URL to copy.
3. In CivicCast Setup, use **Open operator console** as normal.

**Option B — print the handoff URL directly (from an elevated terminal, or
when the Setup app itself is not available):**

1. Open **Command Prompt** or **PowerShell** with **Run as administrator**.
2. Run, adjusting the path if you installed somewhere other than the default:

   ```
   "C:\Program Files\CivicCast (Native)\runtime\python.exe" -m civiccast.native.runtime_cli setup-handoff
   ```

   (From a checkout or a pip install, `civiccast runtime setup-handoff` is the
   same command.)

3. Copy the printed `http://127.0.0.1:8000/operator/?nonce=…` URL and open it
   in a browser **on this same computer**. Setup and sign-in work from there.

Treat that URL as a password. It authorizes creating the station's first
administrator and it stays valid for the life of the installation, so do not
put it in a screenshot, a support ticket, or a chat message. Setup is reachable
only from this computer (`127.0.0.1`); the URL is useless from another machine.

Either option refuses instead of prompting in a loop if you are not an
administrator of the station. If it reports that no setup handoff is
recorded, provisioning did not finish; check the provisioning journal under
`%ProgramData%\CivicCast\provision` and ask for IT help.

## When To Ask For IT Help

Ask for IT help if:

- Windows does not allow administrator approval.
- The machine blocks the Windows helper or says a required Windows setting is
  turned off.
- SmartScreen or an app-control policy blocks the exact verified installer.
- CivicCast says a required setup step needs IT help.
- You are testing an external provider, physical video output, or cable-headend
  path.

For IT, historical (retired public WSL2 line, not this repository): that
line's Windows helper was WSL2 Ubuntu 24.04, and its install path used to
depend on WSL2 because the local meeting tools ran inside that helper with
Linux-compatible service behavior. WSL1 was never a supported release path
for it. The native Windows line documented in this repository — see the
section below — does not use WSL at all; it runs as a native Windows
service through the SCM. None of the WSL2 requirement above applies to a
native-line install.

## If Something Fails

Open **System Health**, create a support bundle, and use
`docs/tester/bug-report-template.md`.

Do not paste passwords, recovery codes, provider secrets, private keys,
resident data, or private meeting content into reports.
