# Release Candidates: Build -> Consumer Evidence -> Publish

Runbook for cutting and publishing a native-Windows beta-candidate release.
Owner decision 2026-09-02: the coordinating agent cuts these releases going
forward, because the beta tester (Sergio, "LPM") checks
`scottconverse/civiccast-native`'s GitHub Releases page daily for new
versions. This document is the checklist that agent follows -- and the
checklist Scott follows to withdraw a bad one.

Nothing in this runbook authorizes an agent to merge to `main` or to publish
without the checks below all passing. `scripts/release/publish_beta_candidate.py`
is fail-closed at every step (see its module docstring) -- it refuses rather
than proceeds past any failed check.

## 1. Build

Dispatch or let `push` trigger `.github/workflows/native-beta-candidate-artifacts.yml`
on the release branch. It produces, per candidate commit (`<sha>`):

- `setup.exe` -- the Authenticode-signed native installer.
- `packs\*.ccpack` -- signed runtime component packs (app payload, server
  binaries, FFmpeg, Ollama runtime, optional CUDA runtime). Each is well
  under GitHub's 2 GB/file release-asset cap.
- `station\` -- the ~21 GB AI-model bundle. **This never goes on a GitHub
  release.** It is either already on the target machine (an upgrade,
  reusing cached model packs per PR #127/#126) or delivered via the USB
  bundle (a first-time install).
- `manual\` in the assembled kit -- `USER-MANUAL.pdf`, `USER-MANUAL.docx`,
  the render manifest, and an exact-source/run receipt. Beta 11 publication
  includes these four small files as release assets and in `SHA256SUMS.txt`.

Confirm the build run's conclusion is `success` and note its run id
(`--build-run-id` below).

### Beta 11 hosted preparation run (not an installable kit)

While the accepted 24-hour station soak and monitor are still running, use
the manual workflow with `build_target: hosted` and `prepare_only: true`.
This keeps packaging and signing work off the station desktop. The workflow
still builds, signs, and verifies the complete candidate and station bundle
on `windows-latest`, then retains only these short-lived artifacts:

- `native-beta-candidate-<sha>`: candidate reports, signing receipt, and
  installer-pack checksums.
- `native-beta-candidate-binaries-<sha>`: signed installer and runtime packs
  (about 3.4 GB before the Whistle runtime addition). The setup embeds the
  signed station index, `core.ccpack`, and `captions-whistle.ccpack` under
  `station\` for setup-only upgrade activation.
- `native-station-embed-<sha>`: the same signed station index and the embedded
  `core.ccpack` plus `captions-whistle.ccpack` used to build those installer
  resources.
- `native-station-prepare-<sha>`: signed `captions-whistle.ccpack`, the exact
  station index, the station bundle `SHA256SUMS.txt`, and its build report.
- `native-beta-manual-<sha>`: the exact-SHA PDF, DOCX, render manifest, and
  receipt bound to the candidate version and workflow run. It is rendered
  with the same Pandoc/TeX and currentness checks as `ci-docs.yml`, has
  one-day retention, and is copied into a full kit by the normal assembly job.
  `prepare_only` produces this small manual artifact too, but still skips kit
  assembly; it does not make a preparation run Gate A eligible.

The Whistle pack payload is 18,422,127 bytes (about 17.6 MiB). It is included
in the installer and repeated in both small station artifacts, so budget for
about 3.5 GB total, plus small indexes and reports; the run will confirm actual
upload sizes. Each artifact has one-day retention, keeping this below the
shared 10 GB Actions artifact budget. The run does not upload the full model
bundle or assemble `native-beta-kit-<sha>`. These artifacts are not a complete
first-install kit and cannot be used for Gate A or sent to a station. An
existing setup-only upgrade can use the embedded Whistle pack and retain its
local cached large models; the signed station index has no download URLs.
The automatic `workflow_run` preflight sees the marker immediately; do not
manually dispatch Gate A against this run after the marker expires, because a
missing expired artifact cannot distinguish preparation-only from a full
self-hosted build. If the candidate binaries expire before later kit assembly,
rerun the candidate workflow at the same source SHA and use the fresh run id.

The station build report and checksum list record the full signed bundle's
identity, but the large model packs are not retained by this run. A later
full-kit build must reconstruct those packs from the pinned, verified local
model cache for the same source SHA, compare the rebuilt station index and
pack hashes with the preparation artifacts, assemble the kit, and run Gate A.
If those identities differ, the preparation run does not establish the full
kit's identity.

Gate A automatically receives a `workflow_run` event when this preparation
workflow completes. After the preflight change is on the default branch, its
hosted preflight sees `native-station-prepare-<sha>` on that exact run and
skips all Windows Sandbox lanes. A pre-merge run still uses the default-
branch Gate A definition, so that guard is not active yet; keep the local
`blackwell-builder` runner offline and cancel any auto-queued Gate A run for
the preparation candidate. Gate A has no separate registered Windows runner
today. Do not bring the desktop runner online or start Windows Sandbox while
the owner continues the station and monitor. Clean-machine Gate A remains
outstanding until that work has ended and the owner schedules it.

## 2. Gate A: three required lanes (workflow-backed route)

`.github/workflows/gate-a-station-acceptance.yml` runs automatically after a
successful build (`workflow_run`), or can be dispatched manually against a
specific build run id. It produces three jobs, each with its own
`gate-a-verdict.json`:

| job | lane name in the verdict JSON | artifact name |
| --- | --- | --- |
| `station-acceptance` | (no `lane` field -- implicitly `clean`) | `gate-a-verdict-<run_id>` |
| `station-acceptance-dirty` | `dirty` | `gate-a-dirty-verdict-<run_id>` |
| `station-acceptance-download-only` | `download-only` | `gate-a-download-only-verdict-<run_id>` |

All three are **required** when using the workflow-backed route (owner decision
2026-09-02 made the download-only lane required alongside clean and dirty).
Each verdict JSON must report `"verdict": "PASS"` and the same producer
`source_sha` as the candidate artifacts. Note the Gate A run id
(`--gate-a-run-id` below) -- this is the
`gate-a-station-acceptance` workflow run id that produced all three jobs,
not any one job's own id.

If any lane is missing, not `PASS`, or reports a different `source_sha`, do
not publish. Re-run Gate A (or the specific failing lane via
`workflow_dispatch` with `lane: cross-version-only` /
`lane: download-only-only`) and fix the underlying defect first.

### Direct Sandbox consumer evidence route

The publisher also accepts direct consumer receipts instead of the Gate A
workflow. Select exactly one route: pass `--gate-a-run-id` for the
workflow-backed route, or `--consumer-evidence-receipt <file>` for direct
evidence. Direct mode also requires an explicit `--artifact-source-sha`; it
never downloads Gate A artifacts or manufactures lane verdicts.

The default direct receipt is Sandbox evidence, with all install, repair,
preservation and scoped runtime groups below. An explicit
`consumer_mode: "physical-host"` is a separate, bounded in-place update route.
It binds the exact signed setup to a healthy pre-install host, successful
candidate install, verified installed app manifest and retained service-loop/schema
state. Its runtime group contains at least two time-ordered snapshots covering
public, government and education, spanning at least 30 seconds, with HLS no
older than 30 seconds, advancing playlists/segments, H.264/AAC and changing
nonempty caption output. It proves those sampled outputs on that
host; it does not claim a clean Sandbox install, failed-install repair,
cross-version Sandbox upgrade or simultaneous capacity.

The Sandbox version-1 JSON receipt has `kind: "civiccast-native-beta-direct-consumer-evidence"`, an `artifact` object with
the exact `source_sha`, `build_run_id`, and a hash-bound `assembly_receipt`,
and an `evidence` object containing all of these named proof groups:

- `fresh_install`: installer run, final install state, and activation
  self-test.
- `failed_install_repair`: the missing-Whistle-field/removed-version-marker
  fixture, installer run/state/self-test, repair and verification command
  logs, and post-repair result/preservation marker.
- `beta10_baseline_install`: the Beta 10 installer run and healthy state.
- `beta10_to_beta11_upgrade`: the current candidate's installer run/state/self-test
  and upgrade-engine log. This legacy field name is retained for receipt
  compatibility; the validated installed version must match the candidate,
  including Beta 12, rather than being accepted because the field says Beta 11.
- `verify_after_upgrade`: the actual sign-in, existing asset and saved
  schedule verification result plus its preservation marker.
- A runtime proof group selected by the explicit scope below: its five-minute
  result, preservation marker, and all five minute snapshots.

Legacy receipts omit `runtime_proof_scope` and use `three_channel_runtime`
for public, government, and education. A functional installation smoke
instead sets the top-level `runtime_proof_scope` to
`"one-channel-install-smoke"` and uses `one_channel_install_smoke` for exactly
`["public"]`. Unknown scopes, mixed runtime groups and missing or different
channels are rejected; missing channels never silently reduce the scope.
Account, asset and three saved schedule preservation checks remain required
regardless of the runtime scope.

For those runtime snapshots, the publisher requires a time-ordered sample
span of at least three minutes, HLS playlist age no greater than 30 seconds,
and advancing playlist timestamps and newest segment names for each channel.
It also requires audio/video HLS, at least three distinct VTT snapshots, and
at least two accumulated JFK reference words per channel across the run. The
bounded VTT text sample remains in the hash-bound evidence for human review;
the publisher does not compare it to a transcript.

The one-channel scope proves installed caption functionality, not
three-channel capacity. It is used while the owner's existing three-station
host soak continues; adding three guest stations would test six simultaneous
stations on the development machine. Release notes keep the accepted host
soak, the failed three-channel guest run and its workload context separate.
The new package's simultaneous three-channel capacity remains unproven;
the single-channel result must never be described as a three-channel pass.

Every referenced file is a `{ "path": ..., "sha256": ... }` object. The
publisher verifies each file hash and the semantics above, then checks all 19
kit files against the build's `kit-assembly-receipt.json` hashes and sizes.
The receipt binds `artifact.source_sha` and the assembly workflow run to
`--artifact-source-sha` and `--build-run-id`. The tested installer is named
`CivicCast (Native)_1.0.0-beta.N_x64-setup.exe`; direct mode stages a
byte-identical `setup.exe` release asset without changing the assembled kit.

`--source-sha` always names the commit targeted by the release tag.
`--artifact-source-sha` names the commit that produced the signed package and
consumer evidence; the values may differ, for example when publishing the
already-built package from a later documentation-only commit. Release notes
show both identities. Direct evidence does not establish Gate A's
download-only network route; the notes state that the route was not tested.
File hashes bind the receipt to its evidence files but do not turn the local
receipt into a signed attestation.

## 3. Publish: `publish_beta_candidate.py`

```powershell
uv run python scripts/release/publish_beta_candidate.py `
  --kit-dir C:\CivicCastTester\kit-staging\<sha> `
  --source-sha <sha> `
  --build-run-id <native-beta-candidate-artifacts run id> `
  --gate-a-run-id <gate-a-station-acceptance run id> `
  --tag v1.0.0-beta.N `
  --truth-status staging `
  --dry-run
```

Always run with `--dry-run` first and read what it prints and what it wrote
to `artifacts\release\<tag>\` (`RELEASE-NOTES.md`, the sidecar JSON,
`SHA256SUMS.txt`) before dropping `--dry-run`. The dry run touches no GitHub
or git-remote state at all.

For a direct-evidence run, use the same command but replace
`--gate-a-run-id` with the exact receipt and producer source SHA:

```powershell
uv run python scripts/release/publish_beta_candidate.py `
  --kit-dir C:\CivicCastTester\kit-staging\<artifact-source-sha> `
  --source-sha <tag-target-sha> `
  --artifact-source-sha <artifact-source-sha> `
  --build-run-id <native-beta-candidate-artifacts run id> `
  --consumer-evidence-receipt C:\CivicCastTester\evidence\direct-consumer-evidence.json `
  --tag v1.0.0-beta.N `
  --truth-status staging `
  --dry-run
```

What it checks, in order, refusing (exit nonzero, no further action) on the
first failure:

1. **Layout** -- workflow mode requires `setup.exe`, `packs\*.ccpack`
   (>=1), and `station\`; direct mode resolves the signed installer path
   from the hash-bound assembly receipt. Both modes require the Beta 11
   `manual\` PDF, DOCX, render manifest, and candidate-manual receipt.
2. **Version identity** -- the signed installer's `VersionInfo.ProductVersion`
   (via PowerShell), `civiccast._native_version.__version__` (source tree),
   and `--tag` with its leading `v` stripped must all agree.
3. **Candidate manual** -- Beta 11 and later must carry the four files from
   `native-beta-manual-<sha>`. The publisher checks the receipt's source SHA,
   candidate version, and artifact producer build-run id, then verifies the
   current Markdown source, render-manifest hash, and PDF/DOCX hashes and
   sizes before checking the selected consumer-evidence route.
4. **Authenticode signature** -- `Get-AuthenticodeSignature` on `setup.exe`
   must report `Status: Valid` (see `CODE_SIGNING_POLICY.md`).
5. **Consumer evidence** -- workflow mode downloads all three Gate A lane
   verdicts and requires them to PASS for `--artifact-source-sha` (which
   defaults to `--source-sha`). Direct mode verifies every bound Sandbox
   receipt and all 19 assembled-kit member hashes/sizes. Direct mode does not
   claim Gate A lanes or the network download-only route.
6. **Hashing + manifest** -- SHA-256 of `setup.exe`, every
   `packs\*.ccpack`, and all four manual files, written to `SHA256SUMS.txt` and a
   `<setup.exe>.sidecar.json` shaped to match
   `scripts/policy/check_sidecar_attestation_integrity.py`'s contract
   (`sha256`, `attestation: null`, `install_manifest.signed`) and what
   `scripts/download_windows_release_artifacts.ps1` already reads.
7. **Release notes** -- rendered via
   `scripts/render_release_notes.render_native_beta_candidate_notes`. They
   identify the artifact producer and tag target, link the build run, and
   show either the three Gate A PASS lanes or the direct Sandbox scenarios
   actually checked, plus the `[Unreleased]` CHANGELOG section, an asset table
   with size + SHA-256, plain-English install/upgrade instructions, the
   SmartScreen note, and the beta-candidate boundary statement.
8. **Pre-flight the asset set** -- every asset (setup.exe, each pack, each
   manual file,
   SHA256SUMS.txt, the sidecar) must be under GitHub's documented 2 GiB
   per-file release-asset cap. The complete set is printed with sizes.
   Anything at or over the cap refuses BEFORE any remote mutation. (Also a
   pre-flight, first of all: `gh auth status` must succeed.)
9. **Publish or dry-run** -- without `--dry-run`, in an order that can never
   leave an orphan tag (no `git tag`/`git push` is ever run by hand):
   1. `gh release create <tag> --draft --target <source-sha> --prerelease
      --title ... --notes-file ... <every asset>` -- a **draft** creates no
      tag. If this fails, the (possibly partial) draft is deleted
      best-effort and the run refuses.
   2. `gh release view <tag> --json assets,isDraft` -- every expected asset
      must be present with a size matching the local file, and the release
      must still be a draft. On ANY mismatch the draft is deleted
      (`gh release delete <tag> --yes`) and the run refuses: nothing is left
      behind, because a draft has no tag.
   3. `gh release edit <tag> --draft=false` -- the single step that creates
      the public tag, atomically with its verified release. If this fails
      the draft is deliberately NOT deleted (un-draft may have partially
      applied server-side); the run refuses loudly and you inspect the
      release on GitHub and publish or delete it by hand.
   4. Only then: update `docs/releases/release-truth.yaml` (adding the new
      entry at the given `--truth-status`, flipping the previous `current`
      entry to `superseded` when the new one becomes `current`) and print a
      summary of the edit.

   GitHub's un-draft creates a lightweight tag at `--source-sha`. No policy
   check in this repository requires an annotated tag, so none is made.

### Failure and rollback map

| failed step | what exists afterwards | what the script does | what you do |
| --- | --- | --- | --- |
| gh auth / layout / version / signature / Gate A / pre-flight | nothing remote | refuses | fix the cause, re-run |
| `gh release create --draft` | maybe a partial draft, no tag | best-effort `gh release delete`, refuses | confirm no draft remains on GitHub, re-run |
| draft verification (missing asset / size mismatch / not a draft) | draft, no tag | `gh release delete`, refuses | confirm no draft remains, investigate the asset, re-run |
| `gh release edit --draft=false` | verified draft, tag state uncertain | refuses, does NOT delete | first run `gh release view <tag> -R scottconverse/civiccast-native --json isDraft,url` to learn whether the release actually went public (a failed un-draft may have partially applied), then publish it by hand if it is intact and still a draft, or delete it |
| `release-truth.yaml` update | public prerelease + tag, manifest not updated | refuses | edit `release-truth.yaml` by hand to match what is live |

`--truth-status staging` for a first publish under review; flip a later
publish to `--truth-status current` once you're ready for it to be the
recommended install target.

## 4. What Sergio (LPM) sees on GitHub

`https://github.com/scottconverse/civiccast-native/releases` shows the new
tag as a **prerelease** (never a full "Latest release" until the owner
decides otherwise) with:

- `setup.exe` and every `*.ccpack` runtime pack as downloadable assets
  (each under 2 GB).
- `SHA256SUMS.txt` and the installer's `*.sidecar.json`.
- Release notes stating: this is a beta candidate, not a production release;
  the exact source SHA; a link to the build and the selected consumer-evidence
  route (the Gate A run with per-lane PASS verdicts for workflow mode, or the
  direct Sandbox scenarios with Gate A and download-only route gaps stated);
  an asset table with size and SHA-256; plain install/upgrade instructions
  ("download setup.exe; if you already have CivicCast installed just run it --
  your recordings, database and AI models are kept; first-time installs need
  the USB model bundle"); and the SmartScreen note.

No release ever carries the ~21 GB `station\` bundle as an asset. A
download-only fresh install (no prior CivicCast install, no USB bundle
run first) is not yet a supported path -- the release notes and
`INSTALL-WINDOWS.md` say so explicitly; do not imply otherwise.

## 5. Withdrawing a bad candidate

If a published beta candidate turns out to be broken:

1. Unpublish it on GitHub:
   ```powershell
   gh release edit <tag> --draft -R scottconverse/civiccast-native
   ```
   This pulls it off the public Releases page immediately (a draft release
   is not visible to Sergio or anyone else without direct owner access).
2. Mark it in `docs/releases/release-truth.yaml`: change its `status` to
   `withdrawn` and add `superseded_by: <the tag that replaces it>` (required
   by `scripts/policy/check_release_truth.py`'s `REQUIRES_SUCCESSOR` rule --
   a `withdrawn` entry with no `superseded_by` fails that check). If nothing
   replaces it yet, do not mark it `withdrawn` until a replacement tag
   exists to name; in the meantime describe the problem in its `notes` field
   and leave `status` as `staging` (never silently leave a known-bad
   `current`).
3. If the withdrawn tag was `current`, promote the last known-good tag back
   to `current` in the same edit (exactly one entry may carry
   `status: current`).
4. Tell Sergio directly (do not rely on him re-checking GitHub on his own
   schedule) that the tag is withdrawn and what to do instead -- reinstall
   the previous good candidate, or wait for the replacement.
5. Never delete the git tag itself (`git tag -d` / `git push origin
   :refs/tags/<tag>`) as part of a withdrawal -- the tag stays as history;
   only its GitHub Release visibility and its `release-truth.yaml` status
   change.

## Related

- `scripts/release/publish_beta_candidate.py` -- the publisher this runbook
  describes.
- `tests/release/test_publish_beta_candidate.py` -- its test suite.
- `docs/releases/release-truth.yaml` -- the sole authored source for release
  state; `scripts/policy/check_release_truth.py` checks docs against it.
- `docs/ops/gate-a.md` -- the full Gate A verdict-criteria table, including
  the "Download-only lane" and "Promotion rule" sections.
- `CODE_SIGNING_POLICY.md` -- what a `Valid` Authenticode signature means
  here and how to verify one yourself.
- `docs/install/windows-release-trust.md` -- the operator-facing trust and
  verification page this runbook's published assets must stay compatible
  with.
