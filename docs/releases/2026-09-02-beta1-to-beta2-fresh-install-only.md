# beta.2 is an internal baseline only; beta.1 → beta.3 upgrades in place (owner decision, 2026-09-02; upgrade path corrected 2026-09-03)

**Status:** decided. **Decider:** Scott Converse (owner). **Affects:** every
beta.1 station's path to the first downloadable release; the Gate A
upgrade-baseline pin (`sandbox-lab/upgrade-baseline.json`); the product
version (`civiccast/_version.py` / `civiccast/_native_version.py`); the
download-only Gate A lane's required status; `docs/releases/release-truth.yaml`.

> **Same-day correction.** This decision was first recorded (below, "What
> changed" through "Consequence for beta.1 stations") describing `v1.0.0-beta.2`
> itself as the target of the one-time fresh install and the first
> downloadable candidate. That framing left the product version at
> `1.0.0-beta.2` -- identical to the version the Gate A baseline pin now
> names as the *previous* candidate, which made Gate A's cross-version lane
> unable to prove anything (`SAME_VERSION_NO_OP`: the installer cannot
> upgrade a station to the exact version it already reports). The corrected
> decision, folded into this document the same day: **`v1.0.0-beta.2` never
> publishes at all.** It stays what Gate A run 33623737236 already proved it
> has to be -- an internal upgrade-baseline kit, pinned in
> `sandbox-lab/upgrade-baseline.json` so Gate A has a real prior build to
> upgrade *from*. The product version moved on to `v1.0.0-beta.3`, which is
> now the one-time fresh-install target for beta.1 stations and the first
> candidate intended to publish as a downloadable release. Every mention of
> "beta.2" as an install/upgrade *target* below is superseded by "beta.3";
> mentions of beta.2 as the *pinned baseline kit* (the SHA, the hashes, the
> Gate A evidence) are unchanged and still accurate.

> **Upgrade-path correction, 2026-09-03.** The "Consequence for beta.1
> stations" section below said a beta.1 station reaches beta.3 only by
> wiping the existing install and installing fresh. That was overcautious:
> the Gate A cross-version lane in this same run already showed "installing
> beta.2 over the pinned *previous* candidate — PASS" (see "Evidence"
> below), and a dedicated Gate A cross-version run on the beta.3 kit
> (run [33713004718](https://github.com/scottconverse/civiccast-native/actions/runs/33713004718))
> confirmed it directly: running `setup.exe` from the **full** beta.3 kit
> (`setup.exe` plus the `station\` folder beside it) **over** an existing
> beta.1 install keeps recordings, settings, the database, and downloaded AI
> models, and migrates the schema in place. The one path this decision's
> own "Download-only lane" evidence (below) actually rules out is running
> `setup.exe` **alone**, without the `station\` folder, from a beta.1
> install — its per-SHA pack cache predates the pack-identity change PR #127
> made, so the new signed station index can never match it. "Fresh install"
> in the sections below should be read as "copy over the full kit and run
> `setup.exe`," not "wipe the station first." README.md and
> INSTALL-WINDOWS.md carry the corrected wording.

## What changed

`sandbox-lab/upgrade-baseline.json` is repinned from candidate-23 (the
`v1.0.0-beta.1` kit, source SHA `057ffece7157e5197e6ce9159d5a1abd84c30436`)
to the `v1.0.0-beta.2` candidate kit (source SHA
`564ee028cf712e26133ada9d7c25b498abe605ab`, build run 33621209994, Gate A run
33623737236). The pinned kit still lives at
`C:\CivicCastTester\kit-staging\564ee028cf712e26133ada9d7c25b498abe605ab\`.
`v1.0.0-beta.2` itself is never published as a release -- it exists solely as
this pinned baseline kit.

Alongside the repin, the product version (`civiccast/_version.py` and
`civiccast/_native_version.py`, and every other surface
`scripts/policy/check_release_identity.py` binds to them: the Tauri/Cargo/
package.json identities, `main.rs`'s `CIVICCAST_VERSION` constant, the
OpenAPI-derived docs, README/`docs/index.html`'s owner-held-candidate
markers) moves from `1.0.0-beta.2` to `1.0.0-beta.3`. Without that move, the
current build and the pinned "previous" baseline would report the identical
version, and Gate A's cross-version upgrade lane could never prove an
upgrade against it.

The `#23` kit and its offline copy at `D:\kit-23-FINAL-beta1\` are **not
deleted, pruned, or superseded as artifacts** — they remain the historical
record of the beta.1 release and stay on the tester's stick. Only the Gate A
*baseline pin* — which candidate kit is required to be present in local
staging for the cross-version and download-only upgrade lanes — moves
forward.

## Why

PR #127 gave every AI model pack (`captions-floor`, `captions-large-v3`, and
the three Ollama components) a stable content identity (`station-models-1`)
instead of stamping the product version into it, and stopped signing any
build-input path into a pack's metadata. That is what makes a download-only
*upgrade* able to reuse a station's already-downloaded ~21 GB of model media
instead of re-fetching it — the point of the whole download-only-install
workstream (#124–#127). But it also means the *signed bytes* of every model
pack changed once, on this release, with no migration bridge for a station
that already activated on the old bytes: a beta.1 station's per-SHA pack
cache (`<install root>\packs\.station-cache\packs\`) is keyed by the old
pack digests, and the new signed station index can never match a cache
written against beta.1's digests. There is no code path that lets the new
`setup.exe` accept a beta.1-era cached pack as a substitute for the one its
own index names.

## Evidence

Gate A run [33623737236](https://github.com/scottconverse/civiccast-native/actions/runs/33623737236)
on the beta.2 candidate kit (`564ee028…abe605ab`) ran all three required
lanes:

- **Clean install** — PASS.
- **Cross-version upgrade** (installing beta.2 over the pinned *previous*
  candidate, at the time still candidate-23/beta.1) — PASS.
- **Download-only lane** (installing/upgrading from `setup.exe` alone, no
  `station\` folder beside it) — **FAIL**. The installer exited 123; the
  station came up afterward but activation failed with engine code 66,
  `could not obtain the model packs`. Byte-level diagnosis confirmed the
  embedded station index from #126 was found and used correctly (K1's old
  failure shape did not recur) — the failure is specifically the pack-cache
  digest mismatch described above, not a regression in index discovery.

Full run diagnosis: `C:\Users\scott\Desktop\CIVICCAST-EVIDENCE\gate-a-download-only-33623737236`.
Tracking checklist and the RELEASE BLOCKED banner recording the decision:
`C:\Users\scott\Desktop\CIVICCAST-FINALIZATION-CHECKLIST.md`.

## Options considered

- **(A) Per-component cache fallback.** Accept a previously-signed,
  already-extracted, D2-valid pack for the same model component even when its
  digest doesn't match the new index, as long as it independently re-verifies
  as trust-root-signed. This is a trust-model change (the index's per-pack
  digest pin would no longer be the sole authority for what a station is
  allowed to run) and needs its own review; not taken for this release.
- **(B) — chosen.** Declare beta.2 an internal-only baseline that never
  publishes, make beta.3 the one-time full-kit upgrade target and the first
  downloadable release, and make beta.3 → beta.4 the first
  download-only-upgradeable pair. This accepts a one-time break in the
  *download-only* floor for a station crossing the beta.1 boundary (it still
  needs the full kit, not a download-only upgrade) in exchange for shipping
  the download-only capability now with the trust model unchanged. *(As
  confirmed 2026-09-03, this break is download-only, not in-place-over-
  existing-install — see the correction callout above.)*

## Consequence for beta.1 stations

- **beta.1 → beta.3 upgrades in place from the full kit.** *(Corrected
  2026-09-03 — see the callout above.)* A station running `v1.0.0-beta.1`
  gets to `v1.0.0-beta.3` by copying the whole beta.3 kit (`setup.exe` plus
  the `station\` folder beside it — USB or LAN copy) to the station and
  running `setup.exe` over the existing install. Recordings, settings, the
  database, and already-downloaded AI models are kept and the schema
  migrates. `v1.0.0-beta.2` is never distributed to a station at all. The
  one unsupported path is running `setup.exe` **alone**, without the
  `station\` folder, from a beta.1 install — its pack cache predates the
  pack-identity change and cannot satisfy beta.3's signed index (see
  "Download-only lane — FAIL" under Evidence above).
- **From beta.3 onward, upgrades are download-only.** Starting with the
  beta.3 → beta.4 step, a station upgrades by downloading `setup.exe` and the
  runtime packs and running the installer in place — no USB kit required, and
  existing recordings, settings, and AI models are kept. The USB kit remains
  available as the air-gapped install option for stations that want it.
- **The required download-only Gate A lane (#125) stays required for every
  release from beta.3 forward.** This is exactly the failure this lane was
  built to catch, and it caught it before anything shipped to a real station.
  It is not weakened, skipped, or made advisory by this decision.

## Related

- CHANGELOG `[Unreleased] / Changed`: the baseline repin and version-bump
  entries.
- `sandbox-lab/upgrade-baseline.json`: the repinned baseline itself (still
  names the beta.2 kit — that does not change; only the *product version*
  that upgrades *from* it moved to beta.3).
- `civiccast/_version.py`, `civiccast/_native_version.py`, and every other
  surface `scripts/policy/check_release_identity.py` binds to them: bumped
  to `1.0.0-beta.3` in this same change.
- `docs/releases/release-truth.yaml`: `v1.0.0-beta.2` recorded `historical`
  (internal baseline kit, never published, no live GitHub release will ever
  exist for it); `v1.0.0-beta.3` recorded `staging` (owner-held, not yet
  published) as the new first-downloadable-candidate entry.
- `scripts/ci/prune_local_candidate_roots.ps1`: the keep-list header already
  requires the baseline's own SHA to survive local staging prunes (#124);
  unchanged by this decision, it now simply keeps the beta.2 SHA instead of
  candidate-23's.
- `README.md`, `INSTALL-WINDOWS.md`, `docs/index.html`,
  `docs/tester/lpm-beta-test-handoff.md`, `docs/tester/START-HERE.md`,
  `docs/install/windows-release-trust.md`, and the tester walkthrough docs:
  updated to name beta.3, not beta.2, as the target of the one-time
  full-kit upgrade and as the first downloadable candidate; each now also
  states plainly that beta.2 was never published, and (as of 2026-09-03)
  that the beta.1 upgrade runs `setup.exe` over the existing install from
  the full kit rather than wiping it.
