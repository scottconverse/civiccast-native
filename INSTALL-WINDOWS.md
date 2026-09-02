# Install CivicCast On Windows

> **This repository (`civiccast-native`) ships ONE product: the native
> Windows station.** No WSL, no Docker, no Linux install target -- see
> [BRANCHES.md](BRANCHES.md). It is a signed installer that registers a
> Windows service through the SCM and supervises the control plane,
> Postgres, and the media workers from a bundled runtime, at
> `C:\Program Files\CivicCast (Native)\`.

## Current Release

`v1.0.0-beta.1` is the current release. It was delivered by USB, not by a
GitHub Release download -- the GitHub Release page carries no installer
asset for it (the ~21 GB AI-model bundle it needs exceeds GitHub's 2 GB
per-file asset cap, and the publish tooling that splits runtime packs from
the model bundle did not exist yet when it shipped). If you already have a
USB-delivered `v1.0.0-beta.1` station, it is the real, current, testable
native install -- there is nothing further to download for it.

**Next release:** `v1.0.0-beta.2` is the current owner-held unpublished
candidate. It has no installer asset and is not a public or production release.
It is intended to be the first **downloadable** beta candidate:
a `setup.exe`, per-pack runtime `.ccpack` assets, and a `SHA256SUMS.txt`
checksum file (each asset under GitHub's 2 GB/file cap), published as a
prerelease at <https://github.com/scottconverse/civiccast-native/releases>.
Watch that page, not `scottconverse/civiccast` (the retired, separate
WSL2-line repository) and not any `v1.0.0-rcNN` tag, which belongs to that
other repository. See
[`docs/releases/release-truth.yaml`](docs/releases/release-truth.yaml) for
the authored release-state record -- it is the single source of truth for
which tag is current.

**First install vs. upgrade, once `v1.0.0-beta.2` publishes:**

- **First-time install on a station with no prior CivicCast install** still
  needs the USB model bundle (~21 GB of AI models). The GitHub download
  alone is not enough for a first install -- it ships the setup executable
  and runtime packs, not the model bundle, because that bundle is too large
  for a GitHub Release asset.
- **Upgrade of an already-installed station** can be download-only starting
  with `v1.0.0-beta.2`: it reuses the AI models already on the machine. An
  upgrade keeps the station's existing recordings, database, and AI models --
  nothing already on the station is discarded by an upgrade install.

**Upgrading from `v1.0.0-beta.1`:** `beta.1` to `beta.2` is a **fresh
install from the beta.2 kit, not an in-place upgrade** -- wipe the existing
`beta.1` install and install `beta.2` fresh (USB kit or a LAN copy of it).
A `v1.0.0-beta.2` release changed the signed identity of every AI model pack
so that later download-only upgrades can reuse them; a `beta.1` station's
already-downloaded models were signed under the old identity and cannot
satisfy a `beta.2` station's signed index. Recordings, settings, and
downloaded AI models are not carried over by this one step -- export or back
up anything you need before wiping. **From `beta.2` onward, upgrades are
download-only**: `beta.2` to `beta.3` and every later step downloads
`setup.exe` and the runtime packs and upgrades in place, keeping recordings,
settings, and AI models. See
[`docs/releases/2026-09-02-beta1-to-beta2-fresh-install-only.md`](docs/releases/2026-09-02-beta1-to-beta2-fresh-install-only.md)
for why.

Setup remains visibly active during long steps: it reports its current
phase, step count, elapsed time, and a heartbeat that updates every few
seconds instead of appearing frozen.

## Read This First

A clean-machine test starts with the documentation, not with a copied `.exe`.
Before running the installer, read these in order:

1. [Beta Tester Start Here](docs/tester/START-HERE.md)
2. This Windows install page
3. [Windows Release Trust And Verification](docs/install/windows-release-trust.md)

Record in the clean-machine proof report that each document was opened and read.
If the docs and the installer/proof package disagree about version, filename,
checksum, or expected next step, stop and report the mismatch before installing.

## What To Download

- **If you are receiving `v1.0.0-beta.1`:** it is USB-delivered. There is no
  GitHub Release download for it -- do not go looking for one.
- **If you are receiving `v1.0.0-beta.2` or later** (once it is published as
  a downloadable prerelease): download `setup.exe`, the matching
  `.ccpack` runtime pack(s), and `SHA256SUMS.txt` from the exact tagged
  GitHub Release at
  <https://github.com/scottconverse/civiccast-native/releases> -- never a
  draft, an older prerelease, or a generic "latest" link. A first-time
  install on that station also needs the USB model bundle. An upgrade of an
  already-installed `beta.2`-or-later station does not need the USB bundle --
  but a `beta.1` station upgrading to `beta.2` is the one exception: see
  "Upgrading from `v1.0.0-beta.1`" above, it needs a fresh install from the
  beta.2 kit, not a download-only upgrade.

Do not install from the repository source ZIP unless you are intentionally
working as a developer.

## Before Running It

Read [Windows Release Trust And Verification](docs/install/windows-release-trust.md)
before running any downloaded installer. Verify `setup.exe` against
`SHA256SUMS.txt` and its sidecar `.sidecar.json` file first -- the trust
page has the exact PowerShell steps.

Leave at least **5 GB of free disk space** for the base installation. This
does not include station recordings, media, backups, or the AI model
bundle; plan those separately. The local AI models (Ollama summary and
translation models) are large on top of that -- roughly 15-20 GB combined
for a first install using the USB bundle.

Windows may show a blue **Windows protected your PC** screen. Do not infer a
signature from that screen. The approved handoff must state the exact file's
actual Authenticode status. If signed, verify the named publisher; if the result
is `NotSigned` or differs from the handoff, stop. Read
[docs/tester/SMARTSCREEN-WALKTHROUGH.md](docs/tester/SMARTSCREEN-WALKTHROUGH.md) before
you run the installer so you know exactly what to click and why, plus how
to independently verify the file yourself first if you want extra confidence.

## If The Operator Console Says "Could Not Read Setup State"

**This is the current, applicable content in this repository.** It covers
the native Windows line's own install -- the paths and executables below
(`CivicCast Native.exe`, `CivicCast (Native)`, `civiccast.native.runtime_cli`)
only exist on a native-line install.

The operator console's first setup page needs the one-time handoff URL the
Windows installer creates -- a plain console URL with no `?nonce=` on the end
cannot read setup state, cannot create the first administrator, and cannot
sign in. If the console shows:

> Could not read setup state. Open the operator console from the CivicCast
> installer handoff, then continue setup.

...and reopening CivicCast Setup and pressing **Open operator console** produces
the same result, the setup app could not read the handoff the installer stored.
That handoff lives in a registry key restricted to SYSTEM and Administrators, so
a setup app running without administrator rights cannot read it and opens the
console without it.

**Recover it on a native Windows station (no reinstall needed).** Either
option below reads the same registry-stored handoff and requires
administrator rights on the station -- use whichever is more convenient.

**Option A -- restore it in CivicCast Setup (recommended):**

1. Run, adjusting the path if you installed somewhere other than the default:

   ```
   "C:\Program Files\CivicCast (Native)\CivicCast Native.exe" --civiccast-restore-setup-handoff
   ```

2. Approve the Windows administrator prompt. CivicCast re-reads the stored
   handoff and updates Setup's own cache -- no URL to copy.
3. In CivicCast Setup, use **Open operator console** as normal.

**Option B -- print the handoff URL directly (from an elevated terminal, or
when the Setup app itself is not available):**

1. Open **Command Prompt** or **PowerShell** with **Run as administrator**.
2. Run, adjusting the path if you installed somewhere other than the default:

   ```
   "C:\Program Files\CivicCast (Native)\runtime\python.exe" -m civiccast.native.runtime_cli setup-handoff
   ```

   (From a checkout or a pip install, `civiccast runtime setup-handoff` is the
   same command.)

3. Copy the printed `http://127.0.0.1:8000/operator/?nonce=...` URL and open it
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

## If Something Fails

Open **System Health**, create a support bundle, and use
`docs/tester/bug-report-template.md`.

Do not paste passwords, recovery codes, provider secrets, private keys,
resident data, or private meeting content into reports.

---

## Historical: retired rc line

Everything in this section describes the retired public WSL2 line
(`v1.0.0-rc18` and earlier, repository `scottconverse/civiccast`) that this
repository does not carry. That product's full history, release artifacts,
and verification docs live in the separate, private `scottconverse/civiccast`
repository (see BRANCHES.md's "Where the old line went"). It is kept as
historical reference only, not as current install instructions for this
repository. None of the GitHub release links below resolve from this
repository, and the verification documents they used to cite -- including
the withdrawn `v1.0.0-rc13`'s incident record
(`docs/releases/v1.0.0-rc18-verification.md`, `v1.0.0-rc17-verification.md`,
`v1.0.0-rc13-verification.md`) -- are not present here -- they are omitted
below rather than linked, because they do not exist on `main`.

<details>
<summary>Expand: retired WSL2-line (rc13-rc18) install notes</summary>

`v1.0.0-rc18` was the published controlled beta on the retired WSL2 line.
Its installer was built from the gate-cleared `main`, Authenticode-signed,
and proven on a genuinely clean Windows host. `v1.0.0-rc17` remained the
rollback target but carried the sixteen findings rc18 fixed.

The exact rc18 installer passed a clean-host install, launch, reinstall,
uninstall, and rc17-to-rc18 upgrade on a pristine Windows 11 guest, plus an
interactive installer walkthrough. The full product path was last proven on
a clean host against rc17's exact bytes and was not repeated on rc18. That
rc17 run completed a full clean-host lifecycle walkthrough on 2026-07-20 --
install with no restarts, first admin and recovery kit, backup and scoped
database restore drill, private rehearsal and packaging, the
pre-publication privacy check, Portal-only approval and resident playback,
real local summary/translation inference, service relaunch, cold-reboot
recovery, and reinstall. Verdict: passed (1 Minor, 1 Nit; no
blocker/critical/Major -- an initial Major uninstall data-retention finding
was reviewed and downgraded to non-blocking). Captions were not exercised in
rc17's full-lifecycle walkthrough, and rc18 did not inherit that result
either.

`v1.0.0-rc13` was withdrawn from beta use: a real bare-metal test with WSL
and its Windows features absent exposed a release-blocking helper-bootstrap
failure. Only rc18 and its matching proof assets were the recommended
install on that line.

Uninstalling on that line removed station data through an uninstaller
checkbox labeled "Delete the application data." Checking it removed
everything, including the ~19 GB Windows helper (the `CivicCast-Ubuntu-24.04`
WSL distribution that held the database and recordings). Leaving it
unchecked kept recordings and settings for a later reinstall; a command-line
silent uninstall (`/S`) kept the data by default. To remove kept data by
hand, `wsl --unregister CivicCast-Ubuntu-24.04` and delete
`%USERPROFILE%\.civiccast`.

The setup path on that line guided: Windows helper setup (WSL2 Ubuntu
24.04), local durable storage preparation, CivicCast service startup,
operator-console handoff, first-admin setup and recovery-kit creation, and
the local Ollama AI runtime with the standard summary/translation models
(rc17 and later), continuing in the background after the console was
already open. A normal operator test did not need Git, GitHub CLI, Git LFS,
Python commands, or Ubuntu commands. Windows administrator prompts could
appear more than once across a restart (rc17 and later) because a restart
cleared the earlier approval.

After a successful install, CivicCast registered a per-user runtime host at
Windows sign-in through an HKCU `Run` entry that kept the WSL helper
available, polled CivicCast health, and restarted the helper or Linux
service if health was lost.

For IT: that line's Windows helper was WSL2 Ubuntu 24.04, and its install
path depended on WSL2 because the local meeting tools ran inside that helper
with Linux-compatible service behavior. WSL1 was never a supported release
path for it. The native Windows line documented above this appendix does
not use WSL at all; it runs as a native Windows service through the SCM.
None of the WSL2 requirement above applies to a native-line install.

</details>
