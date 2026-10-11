# CivicCast project status

> **Taking over coding? Start with
> [`docs/handoff/CODER-HANDOFF-2026-10-02.md`](docs/handoff/CODER-HANDOFF-2026-10-02.md)**
> (where everything is, current state, open work, history to avoid).
>
> Current operator Help serves the bundled manual generated from
> [`docs/manual/src/`](docs/manual/src/) and [`docs/USER-MANUAL.md`](docs/USER-MANUAL.md).
> The 62 per-screen sheets indexed in [`docs/in-app-help/README.md`](docs/in-app-help/README.md)
> are historical Beta 10 audit records; the linked Beta 11 inventory is a dated
> source audit, not the current defect list.

> **Current published release: `v1.0.0-beta.12`**, a GitHub pre-release, not a
> production release. [Release page](https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.12).
> The signed source is `a0c98cb7367dc106042ec89d35a91905470d350c`, producer
> run [38097350705](https://github.com/scottconverse/civiccast-native/actions/runs/38097350705).
> The release now has 26 assets: its original 12 plus 12 station-model ZIP parts,
> `station-models.json`, and `download_windows_release_artifacts.ps1`. All 14
> additions' published sizes and digests matched local files. The helper's
> `-Install` downloads and verifies the complete bundle and runs setup with
> `/S`, without Git, Python, or 7-Zip.
> The normal Beta 11 upgrade setup exited 0 and returned a running, healthy
> service at schema 0089. The post-upgrade five-snapshot recorder failed on its
> first JSON save; no five-snapshot PASS is claimed. The complete public
> download and all hashes verified. Fresh offline Sandbox setup and station
> activation succeeded (setup exit 0, service `Running`, offline AI and CPU
> caption self-tests passed); its follow-on first-admin/three-channel check
> failed with only the first Python traceback line captured, so the cause is
> unresolved and full UI/channel validation is not established. The R9 exit-123
> attempt predates this distribution repair and remains a failed pre-repair
> attempt. The published installer SHA-256 remains
> `2dbc982d07b66f5bc760dfc1c1a943e9a3e100d3c3c7421ace74d6a2c744ab12`; source
> installer/operator corrections are not embedded in that EXE. See the
> [Beta 12 verification record](docs/releases/v1.0.0-beta.12-verification.md).

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
bookkeeping; interrupted repair and sustained-operation checks have no result.
The pre-repair R9 attempt exited 123. The repaired public kit was subsequently
downloaded and verified in a fresh offline Sandbox run: setup exited 0, the
service was `Running`, station activation returned 0, and offline Ollama plus
CPU faster-whisper self-tests passed. The bounded first-admin/three-channel
check then failed; only `Traceback (most recent call last):` was captured from
Python stderr, so the cause is unknown and complete first-admin/channel
validation is not established. No repair, upgrade retest, or soak was run. See
the [captured result](docs/ops/evidence/beta12-public-fresh-install-2026-10-11.json).
Actual
synthetic VDO peers previously exercised camera mute, audio gain mute and
disconnect; this does not establish guest routing into the
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
