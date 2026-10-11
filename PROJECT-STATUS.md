# CivicCast project status

> **Taking over coding? Start with
> [`docs/handoff/CODER-HANDOFF-2026-10-02.md`](docs/handoff/CODER-HANDOFF-2026-10-02.md)**
> (where everything is, current state, open work, history to avoid).
>
> Built-in help work (beta.11): start with
> [`docs/handoff/CODER-HANDOFF-INAPP-HELP-2026-10-03.md`](docs/handoff/CODER-HANDOFF-INAPP-HELP-2026-10-03.md)
> (63 per-screen specs in `docs/in-app-help/`, product-defect list, in-app manual regeneration).

> **Current published release: `v1.0.0-beta.12`**, a GitHub pre-release, not a
> production release. [Release page](https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.12).
> The signed source is `a0c98cb7367dc106042ec89d35a91905470d350c`, producer
> run [38097350705](https://github.com/scottconverse/civiccast-native/actions/runs/38097350705).
> The normal Beta 11 upgrade setup exited 0 and returned a running, healthy
> service at schema 0089. The post-upgrade five-snapshot recorder failed on its
> first JSON save; no five-snapshot PASS is claimed. Repair and fresh-install
> checks have not been run. See the [Beta 12 verification record](docs/releases/v1.0.0-beta.12-verification.md).

## Historical Beta 11 package and evidence

The historical Beta 11 installer and bundled manual were built from
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

## Beta 12 release and upgrade observation

The owner authorized unattended-operation hardening and completion of existing
operator workflows: upgrade preservation and recovery; caption health and
notifications; bounded logs; summary approval/export; local administrator
recovery; Control Room session recovery; remote contribution media controls;
alert routing and emergency presentation; paywall secret preservation;
target-machine operation; and documentation/release identity consistency.
The current published release is source
`a0c98cb7367dc106042ec89d35a91905470d350c` from producer run `38097350705`.
Its asset job and 19-member local kit completed with exact-run checksums,
signature and station-index evidence. The release's separate randomized-suite
run `38097353468` failed; that recorded CI failure is distinct from the actual
installer outcome. The normal Beta 11-to-Beta 12 setup ran from 20:07:13 to
20:25:15 MDT, exited 0, and left the service running and healthy at schema
0089. The preservation assertion reached and saved its marker. Initial checks
observed HLS audio and video on all three channels and primary Whistle within
capacity. At 20:31:16 MDT, the post-upgrade recorder wrapper failed during its
first-minute JSON save with `Cannot convert value to type System.String.` No
five-snapshot PASS was recorded. The owner deferred that wrapper issue as
bookkeeping; interrupted repair, fresh install and sustained-operation checks
have not been run. Actual synthetic VDO peers previously exercised camera mute,
audio gain mute and disconnect; this does not establish guest routing into the
native broadcast compositor. The [verification record](docs/releases/v1.0.0-beta.12-verification.md)
links the published release, manual assets and exact evidence limits.

## Where the history went

The earlier dated status entries and handoff notes (beta.5 through beta.8
preparation, kit-server commands, local paths, the old task list and standing
rules from that period) are kept for the record, and are not current guidance:

- [`docs/history/PROJECT-STATUS-2026-09.md`](docs/history/PROJECT-STATUS-2026-09.md)
- [`docs/history/HANDOFF-2026-09.md`](docs/history/HANDOFF-2026-09.md)

Release state of record: [`docs/releases/release-truth.yaml`](docs/releases/release-truth.yaml).
Deferred work: [`next-cleanup.md`](next-cleanup.md).
