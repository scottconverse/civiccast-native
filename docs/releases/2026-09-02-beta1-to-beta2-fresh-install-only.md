# beta.1 → beta.2 is a fresh install, not an upgrade (owner decision, 2026-09-02)

**Status:** decided. **Decider:** Scott Converse (owner). **Affects:** every
beta.1 station upgrading to beta.2; the Gate A upgrade-baseline pin
(`sandbox-lab/upgrade-baseline.json`); the download-only Gate A lane's
required status.

## What changed

`sandbox-lab/upgrade-baseline.json` is repinned from candidate-23 (the
`v1.0.0-beta.1` kit, source SHA `057ffece7157e5197e6ce9159d5a1abd84c30436`)
to the `v1.0.0-beta.2` candidate kit (source SHA
`564ee028cf712e26133ada9d7c25b498abe605ab`, build run 33621209994, Gate A run
33623737236). The pinned kit still lives at
`C:\CivicCastTester\kit-staging\564ee028cf712e26133ada9d7c25b498abe605ab\`.

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
pack digests, and a beta.2 signed station index can never match a cache
written against beta.1's digests. There is no code path that lets a beta.2
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
- **(B) — chosen.** Declare beta.1 → beta.2 fresh-install-only, and make
  beta.2 → beta.3 the first download-only-upgradeable pair. This accepts a
  one-time break in the download floor for a station crossing exactly this
  version boundary, in exchange for shipping the download-only capability now
  with the trust model unchanged.

## Consequence for beta.1 stations

- **beta.1 → beta.2 is a fresh install.** A station running `v1.0.0-beta.1`
  gets `v1.0.0-beta.2` by wiping the existing install and installing fresh
  from the beta.2 kit (USB or LAN copy) — the in-place installer-over-existing
  upgrade path is not supported across this specific boundary. Recordings,
  settings, and already-downloaded AI models are not preserved by this step;
  operators should export/back up anything they need before wiping.
- **From beta.2 onward, upgrades are download-only.** Starting with the
  beta.2 → beta.3 step, a station upgrades by downloading `setup.exe` and the
  runtime packs and running the installer in place — no USB kit required, and
  existing recordings, settings, and AI models are kept. The USB kit remains
  available as the air-gapped install option for stations that want it.
- **The required download-only Gate A lane (#125) stays required for every
  release from beta.2 forward.** This is exactly the failure this lane was
  built to catch, and it caught it before anything shipped to a real station.
  It is not weakened, skipped, or made advisory by this decision.

## Related

- CHANGELOG `[Unreleased] / Changed`: the baseline repin entry.
- `sandbox-lab/upgrade-baseline.json`: the repinned baseline itself.
- `scripts/ci/prune_local_candidate_roots.ps1`: the keep-list header already
  requires the baseline's own SHA to survive local staging prunes (#124);
  unchanged by this decision, it now simply keeps the beta.2 SHA instead of
  candidate-23's.
- `INSTALL-WINDOWS.md`, `docs/tester/lpm-beta-test-handoff.md`: carry a
  matching "Upgrading from beta.1" paragraph for testers.
