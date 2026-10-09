# Install CivicCast On Windows

> **This repository (`civiccast-native`) ships ONE product: the native
> Windows station.** No WSL, no Docker, no Linux install target -- see
> [BRANCHES.md](BRANCHES.md). It is a signed installer that registers a
> Windows service through the SCM and supervises the control plane,
> Postgres, and the media workers from a bundled runtime, at
> `C:\Program Files\CivicCast (Native)\`.

## Current Release

`v1.0.0-beta.11` is the current release (published 2026-10-08), a GitHub
pre-release, not a production release. The release includes the signed
`setup.exe`, five runtime `.ccpack` assets, `SHA256SUMS.txt`, installer
sidecar metadata, and manuals:
<https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.11>.
The October 8 package (producer source `b7cc3e7c`, build `37827938199`) was
installed as an in-place refresh over an existing Beta 11 host; it returned
healthy on the current schema, and a brief three-channel observation showed
advancing HLS and changing captions. A clean-machine
install, failed-install repair, Beta 10 upgrade, and longer capacity run were
not performed for this exact package. See
[`docs/releases/v1.0.0-beta.11-verification.md`](docs/releases/v1.0.0-beta.11-verification.md)
for its tested scope and limits.

`v1.0.0-beta.10` (published 2026-10-02) is superseded. Its historical Gate A
clean-install lane passed 10 of 10 criteria; the upgrade and download-only
lanes were not run. `v1.0.0-beta.8` and `v1.0.0-beta.9` were never published;
their work was included in beta.10. See
[`docs/releases/v1.0.0-beta.10-verification.md`](docs/releases/v1.0.0-beta.10-verification.md)
for that release's record. Watch the Beta 11 release page, not
`scottconverse/civiccast` (the retired, separate WSL2-line repository) and not
any `v1.0.0-rcNN` tag, which belongs to that other repository. See
[`docs/releases/release-truth.yaml`](docs/releases/release-truth.yaml) for
the authored release-state record.

`v1.0.0-beta.7` (published 2026-09-15; its record is
[`docs/releases/v1.0.0-beta.7-verification.md`](docs/releases/v1.0.0-beta.7-verification.md)),
`v1.0.0-beta.5`, `v1.0.0-beta.4`, and `v1.0.0-beta.3` (the first downloadable release) are
now superseded.
`v1.0.0-beta.1` (USB-delivered, no downloadable assets) is also superseded.
If you already have a USB-delivered `v1.0.0-beta.1` station, or a
`v1.0.0-beta.3` station, it still runs. The upgrade instructions below
describe the path that was proven for earlier releases; the upgrade lane was
not run for `v1.0.0-beta.10`, so back up your station data before upgrading.

`v1.0.0-beta.2` was **never published**: it exists only as an internal Gate A
upgrade-baseline kit used to prove the download-only install/upgrade lanes,
never a release a station receives.

**First install vs. upgrade:**

- **First-time install on a station with no prior CivicCast install.** The
  installer itself is small; the large AI components (the caption engine,
  the local summary and translation AI model, and, on capable hardware, an
  optional higher-quality caption engine and GPU acceleration) are not inside
  it. During install the CivicCast Installer window lists each large
  component with a plain-English explanation and its size, uses a copy that is
  already on the computer (shown as **Found locally - verified**, for example
  from the `station\` folder of a USB/LAN kit or from an earlier install), and
  downloads the rest with a progress display and a **Stop downloading**
  button. File download and station activation are separate steps; a visible
  download completing does not establish that a first install will activate.
  The complete signed USB/LAN kit (installer, runtime packs, and the
  `station\` model bundle, about 21 GB) is the offline alternative for a
  station without a reliable internet connection. **Not proven for this Beta
  11 package:** a first install on a clean machine that has neither a kit nor an
  earlier install. The exact Beta 11 package has not passed a clean first-install
  check using downloads alone. If a required runtime pack is missing, staging
  stops with exit 110; station activation and self-test failures occur later
  and are reported at the activation step (overall setup exit 123, with the
  inner cause in the installer log). See "Download-only lane" in
  [`docs/ops/gate-a.md`](docs/ops/gate-a.md); use the complete kit your tester
  handoff names. After setup there is no further
  background model download; a technical admin can fetch or import models later
  with `civiccast model download` or `civiccast model import-offline`.
- **Upgrade of an already-installed station** can be download-only starting
  with `v1.0.0-beta.3`: it reuses the AI models already on the machine. An
  upgrade keeps the station's existing recordings, database, and AI models --
  nothing already on the station is discarded by an upgrade install. This is
  the path that was proven for `v1.0.0-beta.5` -> `v1.0.0-beta.7`: run `setup.exe` (with the
  runtime packs) over the existing install, no `station\` folder needed. The
  upgrade lane was not run for beta.10 (waived by the owner for this
  publication).

**Upgrading from `v1.0.0-beta.1`:** copy the whole `beta.3` kit --
`setup.exe`, the runtime packs, and the `station\` folder beside them (USB
kit or a LAN copy of it) -- to the station, then run `setup.exe` **over**
the existing `beta.1` install. Your recordings, settings, database, and AI
models are kept and the schema migrates. The one unsupported path is
running `setup.exe` **alone**, without the `station\` folder, from a
`beta.1` install: the `beta.2` internal baseline kit changed the signed
identity of every AI model pack so later download-only upgrades can reuse
them, and a `beta.1` station's already-downloaded models were signed under
the old identity, so `setup.exe` alone can't resolve `beta.3`'s signed
index against that stale pack cache. Always bring the full kit for this one
upgrade. **From `beta.3` onward, upgrades are download-only**: `beta.3` to
`beta.4` and every later step downloads `setup.exe` and the runtime packs
and upgrades in place, keeping recordings, settings, and AI models. See
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
- **If you are receiving `v1.0.0-beta.3` or later**: download `setup.exe`,
  the matching `.ccpack` runtime pack(s), and `SHA256SUMS.txt` from the
  exact tagged GitHub Release at
  <https://github.com/scottconverse/civiccast-native/releases> -- never a
  draft, an older prerelease, or a generic "latest" link. A first-time
  install on that station also needs either the complete signed USB/LAN kit
  (with its `station\` model bundle) or, once proven, installer-side
  downloads of the large AI components (see "First install vs. upgrade"
  above). An upgrade of an
  already-installed `beta.3`-or-later station does not need the station bundle --
  but a `beta.1` station upgrading to `beta.3` is the one exception: see
  "Upgrading from `v1.0.0-beta.1`" above, it needs the full `beta.3` kit
  (`setup.exe` plus the `station\` folder) run over the existing install,
  not a download-only upgrade. `v1.0.0-beta.2` is never distributed to a
  tester; skip it entirely.

Do not install from the repository source ZIP unless you are intentionally
working as a developer.

## Before Running It

Read [Windows Release Trust And Verification](docs/install/windows-release-trust.md)
before running any downloaded installer. Verify `setup.exe` against
`SHA256SUMS.txt` and its sidecar `.sidecar.json` file first -- the trust
page has the exact PowerShell steps.

Plan disk space for the large AI components (whether they arrive in a USB/LAN
kit or are downloaded by the installer) and the installed runtime/model copy
they produce, plus the recordings, media, and backups the station will retain.
The installer composes the signed model components into the station's local
Ollama store; it does not run a further background model download after
setup.

Starting with `v1.0.0-beta.10`, the cache of prepared copies of
long programs (the "conform cache") defaults to a 60 GB budget instead of
20 GB. Leave room for it on the data drive, or set
`CIVICCAST_CONFORM_CACHE_GB` to a smaller value.

Windows may show a blue **Windows protected your PC** screen. Do not infer a
signature from that screen. The approved handoff must state the exact file's
actual Authenticode status. If signed, verify the named publisher; if the result
is `NotSigned` or differs from the handoff, stop. Read
[docs/tester/SMARTSCREEN-WALKTHROUGH.md](docs/tester/SMARTSCREEN-WALKTHROUGH.md) before
you run the installer so you know exactly what to click and why, plus how
to independently verify the file yourself first if you want extra confidence.

## If First Setup Will Not Open Or Says "Could Not Read Setup State"

**This is the current, applicable content in this repository.** It covers
the native Windows line's own install.

First Setup (naming the station and creating the first administrator) is only
available from the station computer itself. The operator console listens on
the station's own loopback address (`127.0.0.1`, port 8000), and the setup
screen accepts a request only from that same computer. There is no setup
link, code, or password to copy, and there is nothing to restore: an older
build used a one-time setup link (`?nonce=...`) and an administrator
command to recover it, and both were retired. If a note you were given
still mentions either one, ignore it.

- **To open First Setup,** on the station computer use **Open operator
  console** in CivicCast Setup, or the **CivicCast Operator Console**
  shortcut (desktop and Start menu), or open
  `http://127.0.0.1:8000/operator/` in a browser running on that same
  computer.
- **"First setup can only be done from the station computer itself."** The
  browser you used is not running on the station -- for example the
  window of a remote-desktop viewer's own computer, or another computer on
  the network. Open the console in a browser on the station.
- **"The station is cooling down after too many requests."** Wait a moment
  and select **Try again**.
- **"Could not read setup state."** followed by a reason means the console
  reached the station but the station could not answer. Wait a moment and
  reload the page. If it persists, check that the CivicCast service is
  running, open **System Health** if you can reach it, and collect
  `C:\ProgramData\CivicCast\install-progress.log`. Ask for IT help and do
  not run the installer again until someone has read that log.

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
