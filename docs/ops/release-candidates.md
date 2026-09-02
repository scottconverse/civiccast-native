# Release Candidates: Build -> Gate A -> Publish

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

Confirm the build run's conclusion is `success` and note its run id
(`--build-run-id` below).

## 2. Gate A: three required lanes

`.github/workflows/gate-a-station-acceptance.yml` runs automatically after a
successful build (`workflow_run`), or can be dispatched manually against a
specific build run id. It produces three jobs, each with its own
`gate-a-verdict.json`:

| job | lane name in the verdict JSON | artifact name |
| --- | --- | --- |
| `station-acceptance` | (no `lane` field -- implicitly `clean`) | `gate-a-verdict-<run_id>` |
| `station-acceptance-dirty` | `dirty` | `gate-a-dirty-verdict-<run_id>` |
| `station-acceptance-download-only` | `download-only` | `gate-a-download-only-verdict-<run_id>` |

All three are **required** for a publish (owner decision 2026-09-02 made the
download-only lane required alongside clean and dirty). Each verdict JSON
must report `"verdict": "PASS"` and the same `source_sha` as the candidate
commit. Note the Gate A run id (`--gate-a-run-id` below) -- this is the
`gate-a-station-acceptance` workflow run id that produced all three jobs,
not any one job's own id.

If any lane is missing, not `PASS`, or reports a different `source_sha`, do
not publish. Re-run Gate A (or the specific failing lane via
`workflow_dispatch` with `lane: cross-version-only` /
`lane: download-only-only`) and fix the underlying defect first.

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

What it checks, in order, refusing (exit nonzero, no further action) on the
first failure:

1. **Layout** -- `setup.exe`, `packs\*.ccpack` (>=1), `station\` all present
   in `--kit-dir`.
2. **Version identity** -- `setup.exe`'s `VersionInfo.ProductVersion`
   (via PowerShell), `civiccast._native_version.__version__` (source tree),
   and `--tag` with its leading `v` stripped must all agree.
3. **Authenticode signature** -- `Get-AuthenticodeSignature` on `setup.exe`
   must report `Status: Valid` (see `CODE_SIGNING_POLICY.md`).
4. **Gate A verdicts** -- downloads all three lane verdict artifacts for
   `--gate-a-run-id`, requires all three `PASS` and the same `source_sha`
   equal to `--source-sha`.
5. **Hashing + manifest** -- SHA-256 of `setup.exe` and every
   `packs\*.ccpack`, written to `SHA256SUMS.txt` and a
   `<setup.exe>.sidecar.json` shaped to match
   `scripts/policy/check_sidecar_attestation_integrity.py`'s contract
   (`sha256`, `attestation: null`, `install_manifest.signed`) and what
   `scripts/download_windows_release_artifacts.ps1` already reads.
6. **Release notes** -- rendered via
   `scripts/render_release_notes.render_native_beta_candidate_notes`
   (source SHA, build-run and Gate-A-run links, the per-lane PASS table, the
   `[Unreleased]` CHANGELOG section, an asset table with size + SHA-256,
   plain-English install/upgrade instructions, the SmartScreen note, and the
   beta-candidate boundary statement).
7. **Pre-flight the asset set** -- every asset (setup.exe, each pack,
   SHA256SUMS.txt, the sidecar) must be under GitHub's documented 2 GiB
   per-file release-asset cap. The complete set is printed with sizes.
   Anything at or over the cap refuses BEFORE any remote mutation. (Also a
   pre-flight, first of all: `gh auth status` must succeed.)
8. **Publish or dry-run** -- without `--dry-run`, in an order that can never
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
| `gh release edit --draft=false` | verified draft, tag state uncertain | refuses, does NOT delete | open the release on GitHub; publish it by hand if it is intact, otherwise delete it |
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
  the exact source SHA; links to the build and Gate A runs with the
  per-lane PASS verdicts; an asset table with size and SHA-256; plain
  install/upgrade instructions ("download setup.exe; if you already have
  CivicCast installed just run it -- your recordings, database and AI
  models are kept; first-time installs need the USB model bundle"); and the
  SmartScreen note.

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
