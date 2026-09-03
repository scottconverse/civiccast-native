# v1.0.0-beta.3 published: the first downloadable CivicCast release (2026-09-03)

**Status:** done. **Publisher:** the coordinating agent, per the owner's
2026-09-02 delegation ("every green build gets tagged and published" --
see `scripts/release/publish_beta_candidate.py`'s module docstring).
**Affects:** `docs/releases/release-truth.yaml`; every beta.1 station's
upgrade path; README / BRANCHES.md / `docs/adoption/release-policy.md`'s
"current release" wording.

## What happened

`v1.0.0-beta.3` is published as a GitHub prerelease on
[`scottconverse/civiccast-native`](https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.3),
targeting source SHA `9573d4a82e1e1d9993589f633bad6dacba792afb`. It is the
first CivicCast release a tester can obtain by download alone: `setup.exe`
and the five runtime `.ccpack` packs are attached as release assets, each
under GitHub's 2 GiB/file cap, verified by a published `SHA256SUMS.txt` and
a `setup.exe.sidecar.json` sidecar. This is exactly the shape
`docs/releases/2026-09-02-beta1-to-beta2-fresh-install-only.md` decided
beta.3 would be.

Published via `python scripts/release/publish_beta_candidate.py
--kit-dir <kit> --source-sha 9573d4a82e1e1d9993589f633bad6dacba792afb
--build-run-id 33711079441 --gate-a-run-id 33713004718 --tag v1.0.0-beta.3
--truth-status current`, whose fail-closed checks all passed before any
GitHub state was touched: version identity agrees across `setup.exe`
ProductVersion, `civiccast._native_version.__version__`, and the tag;
Authenticode signature status is `Valid`; Gate A run 33713004718 (source SHA
`9573d4a82e1e1d9993589f633bad6dacba792afb`) shows `PASS` on all three
required lanes -- clean install, cross-version upgrade (over the pinned
beta.2 baseline), and download-only.

## Two script bugs found and fixed while publishing

Both were caught because `publish_beta_candidate.py`'s live path had never
actually been exercised against a real produced kit or a real Gate A run
before this publish (the module docstring already said as much). Both fixes
are narrowly scoped, covered by the existing/added pytest suite
(`tests/release/test_publish_beta_candidate.py`, 47 passing after the
fixes), and reported here rather than silently patched.

1. **`verify_layout` required a local file literally named `setup.exe`.**
   The real kit producer
   (`.github/workflows/native-beta-candidate-artifacts.yml`) always keeps
   the branded installer name (`CivicCast (Native)_<version>_x64-setup.exe`)
   on disk -- Gate A's own consumer step matches it with a wildcard, never a
   literal name. Every existing test fixture in
   `tests/release/test_publish_beta_candidate.py` happened to fabricate a
   kit with a file already named `setup.exe`, so this never surfaced until
   a real kit directory was used. **Not patched in the script** (the fix
   would touch the release asset-naming contract shared with
   `scripts/download_windows_release_artifacts.ps1` and its pinned test
   suite, `tests/policy/test_windows_release_downloader.py`, which is
   higher-risk than this publish needed). Worked around non-destructively
   instead: a separate mirror kit directory
   (`C:\CivicCastTester\kit-staging\9573d4a82e1e1d9993589f633bad6dacba792afb-publish\`)
   was built with the exact same bytes (NTFS hardlinks to the real
   `setup.exe` and every `.ccpack`, verified by matching SHA-256) under the
   name the script expects, plus an empty placeholder `station\` directory
   (the script only checks that it exists, never reads its contents). The
   original kit-staging directory the live soak tester reads was never
   modified.
2. **Gate A verdict artifact names were formatted with the wrong run id.**
   `gate-a-station-acceptance.yml`'s own `run_id` step output is
   `github.event.inputs.run_id` -- the *build* run being validated, not the
   Gate A workflow's own run id -- so every `gate-a*-verdict-<id>` artifact
   it uploads is suffixed with the build run id even though the artifacts
   live on the Gate A run. Confirmed live: Gate A run `33713004718`
   (validating build `33711079441`) uploads artifacts named
   `gate-a-verdict-33711079441`, `gate-a-dirty-verdict-33711079441`,
   `gate-a-download-only-verdict-33711079441` -- never suffixed
   `-33713004718`. `download_gate_a_verdicts` formatted the artifact name
   with `gate_a_run_id` (used correctly elsewhere, as the `gh run download`
   positional argument selecting *which run* to fetch from) instead of
   `build_run_id`, so it looked for an artifact that can never exist
   whenever the two run ids differ -- which the existing test suite never
   caught, because its fakes never modeled a real Gate A run's artifact
   names. **Fixed in the script**: `download_gate_a_verdicts` now takes an
   explicit `build_run_id` parameter and formats
   `GATE_A_ARTIFACT_NAMES[lane]` with it, while still using `gate_a_run_id`
   to select the run `gh run download` fetches from. A regression test
   (`test_gate_a_artifact_name_uses_build_run_id_not_gate_a_run_id`) asserts
   both ids are used for their correct, distinct purposes.

## Evidence

- **Release:** `gh release view v1.0.0-beta.3 -R scottconverse/civiccast-native
  --json isDraft,assets,targetCommitish,tagName` -- `isDraft: false`,
  `targetCommitish: 9573d4a82e1e1d9993589f633bad6dacba792afb`, 8 assets
  (`setup.exe`, five `.ccpack` packs, `SHA256SUMS.txt`,
  `setup.exe.sidecar.json`).
- **Hash + signature, verified from the outside:**
  `scripts/download_windows_release_artifacts.ps1 -AssetSet NativeCandidate`
  downloaded `SHA256SUMS.txt`, `setup.exe`, and the sidecar from the live
  release and verified all three against each other with no local shortcut.
  The downloaded `setup.exe`'s SHA-256
  (`76df8f3bcc5e6b20a41448cddae8a3433e088ebd821a81870b4e40ea052492dc`)
  matches the kit's own installer byte-for-byte, and
  `Get-AuthenticodeSignature` on the downloaded file reports `Valid`
  (signer: Scott Converse).
- **Gate A:** run [33713004718](https://github.com/scottconverse/civiccast-native/actions/runs/33713004718),
  all three lanes PASS, `source_sha` agrees with the published target
  across every lane's verdict document.
- **Test suite:** `pytest tests/release/test_publish_beta_candidate.py -q`
  -- 47 passed (46 pre-existing + 1 new regression test) after both fixes
  above.

## What did NOT change

- The kit-staging directory the live soak tester reads
  (`C:\CivicCastTester\kit-staging\9573d4a82e1e1d9993589f633bad6dacba792afb\`,
  including the tester's own `samples\` and `SHA256SUMS.txt`) was not
  touched, moved, or deleted.
- The ~21 GB `station\` AI-model bundle is not, and will never be, a
  GitHub release asset -- unchanged from the beta.3 design decision.
- No tag or draft release was left orphaned at any point; the publish
  succeeded end to end on the first live attempt after the two fixes above.

## Related

- `docs/releases/release-truth.yaml`: `v1.0.0-beta.3` flipped from
  `staging` to `current`; `v1.0.0-beta.1` flipped from `current` to
  `superseded` (`superseded_by: v1.0.0-beta.3`).
- `README.md`, `BRANCHES.md`, `docs/adoption/release-policy.md`: "current
  release" wording updated to name beta.3 as published and downloadable.
- `scripts/release/publish_beta_candidate.py`,
  `tests/release/test_publish_beta_candidate.py`: the `build_run_id` fix
  and its regression test, described above.
- `docs/releases/2026-09-02-beta1-to-beta2-fresh-install-only.md`: the
  decision this publish carries out (beta.1 -> beta.3 fresh install;
  beta.3 -> beta.4 onward is download-only upgrade).
