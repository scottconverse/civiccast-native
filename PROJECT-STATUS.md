# CivicCast project status

> **Taking over coding? Start with
> [`docs/handoff/CODER-HANDOFF-2026-10-02.md`](docs/handoff/CODER-HANDOFF-2026-10-02.md)**
> (where everything is, current state, open work, history to avoid).
>
> Built-in help work (beta.11): start with
> [`docs/handoff/CODER-HANDOFF-INAPP-HELP-2026-10-03.md`](docs/handoff/CODER-HANDOFF-INAPP-HELP-2026-10-03.md)
> (63 per-screen specs in `docs/in-app-help/`, product-defect list, in-app manual regeneration).

> **Current published release: `v1.0.0-beta.11`, published October 8, 2026**
> as a GitHub pre-release, not a production release.
> [Release page](https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.11).
> Beta 12 is in development and is not yet a published install target.

## Beta 11 package and evidence

The current installer and bundled manual were built from
`400cff08f72a4555f9de57e790a298ecefdb0cce` in signed build `37857705750`.
The original published tag remains at
`79e6431dfea248b11b079cff69408192ef22816a`; the release page discloses the
replacement package source. There are 12 public release assets. Use the
complete USB/LAN kit, including the runtime packs and signed `station\`
model bundle, for an offline installation.

That exact package passed a fresh, offline, CPU-only Windows Sandbox install,
installed Help verification, and a five-minute single-channel Whistle output
check. Public installer/manual downloads and release asset digests were
verified. Upgrade from Beta 10, repair, GPU operation, and sustained
three-channel capacity remain unverified for that package. See
[Beta 11 verification](docs/releases/v1.0.0-beta.11-verification.md).

The accepted 24-hour and 36-hour three-channel caption milestones came from
the development overlay. They are useful runtime evidence for that overlay,
not installation or capacity proof for the corrected release package. See
[soak results and limits](docs/ops/beta11-dev7-24-hour-caption-soak-2026-10-07.md).

A separate 48-hour observation of one host running Beta 11 recorded 635
discarded caption-input seconds over 518,400 nominal channel-seconds across
three channels: 99.877507716% (99.88% rounded) logged input coverage. This is
runtime evidence, not transcript-word accuracy or installer/Beta 12
qualification. See the [48-hour host report](docs/ops/beta11-host-caption-performance-48-hour-2026-10-10.md)
and its [milestone snapshot](docs/ops/evidence/beta11-host-48-hour-milestone-2026-10-10.json).

## Beta 12 work

The owner authorized unattended-operation hardening and completion of existing
operator workflows: upgrade preservation and recovery; caption health and
notifications; bounded logs; summary approval/export; local administrator
recovery; Control Room session recovery; remote contribution media controls;
alert routing and emergency presentation; paywall secret preservation;
target-machine operation; and documentation/release identity consistency.
Source changes cover caption health, bounded logs, summary approval/export,
local administrator recovery, Control Room recovery, remote guest commands,
alert routing and emergency presentation, and paywall secret preservation.
Affected tests and independent reviews are being integrated; the manual,
in-app manual and API reference have been regenerated for this candidate.
Actual synthetic VDO peers exercised camera mute, audio gain mute and
disconnect. This does not establish guest routing into the native broadcast
compositor. Exact-package installation, upgrade/recovery and target-machine
operation remain pending. This page does not claim that Beta 12 is released
or that its installation and sustained-operation outcomes have passed.
See the [Beta 12 candidate verification record](docs/releases/v1.0.0-beta.12-verification.md)
for source-check scope and the package/field checks still outstanding.

## Where the history went

The earlier dated status entries and handoff notes (beta.5 through beta.8
preparation, kit-server commands, local paths, the old task list and standing
rules from that period) are kept for the record, and are not current guidance:

- [`docs/history/PROJECT-STATUS-2026-09.md`](docs/history/PROJECT-STATUS-2026-09.md)
- [`docs/history/HANDOFF-2026-09.md`](docs/history/HANDOFF-2026-09.md)

Release state of record: [`docs/releases/release-truth.yaml`](docs/releases/release-truth.yaml).
Deferred work: [`next-cleanup.md`](next-cleanup.md).
