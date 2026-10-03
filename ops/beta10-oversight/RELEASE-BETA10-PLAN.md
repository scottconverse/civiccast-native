# beta.10 release plan (written 2026-10-02 00:5x; Scott authorized push/merge/tag/publish, docs on all surfaces, then caption fix, then whole-repo audit-lite)

## Facts established
- GitHub releases exist for v1.0.0-beta.1,.3,.4,.5,.7 (pre-releases, "Beta Candidate"). Tag pattern: v1.0.0-beta.N. beta.10 = v1.0.0-beta.10.
- Release process = docs/ops/release-candidates.md: CI build (native-beta-candidate-artifacts.yml) -> Gate A (3 lanes, same source_sha) -> scripts/release/publish_beta_candidate.py (draft -> verify -> un-draft creates tag) -> release-truth.yaml.
- Main repo checkout (...\re\civiccast-native, main @ 35d60b75, 3 ahead of origin, heavily dirty with 35 modified files) is NEVER reset/cleaned/stashed. Do release work in a separate worktree.
- C16 in git: branch beta10-u65 (fd8c7b10, 161 commits ahead of main, linear from main's merge-base 35d60b75) matches installed civiccast/*.py on 679/681 files. The 2 differing: egress/preparer.py (installed 853a71c0 = U65 + 60 GB default; branch has 03f417aa) and egress/daemon.py (installed 903b79ad = U67; branch has 35526478). Both blobs are in staging\C16\candidate and staging\U67.
- U64's loudness_ride.py change (quiet-source exclusion) is NOT in C16 (parked, not installed) - and beta10-u65 contains it? (u65 matched installed loudness_ride 3aff1900, so u64's change is NOT on u65). Release = exactly what was proven.

## Steps
1. Worktree release/beta10 from beta10-u65; commit C16 preparer.py + daemon.py (+ U67 tests); prove tree == installed (hash compare).
2. Version bump to 1.0.0-beta.10 on every surface (_native_version, _version, pyproject, installer, docs, README, manuals, landing page docs/index.html, CHANGELOG, release-truth).
3. Docs refresh (README, USER-MANUAL md/docx/pdf, landing page, install docs, CHANGELOG).
4. Push branch, open merge to main (main is behind: do NOT disturb local dirty checkout; merge via PR/fast-forward on origin), CI build, Gate A, publish via publish_beta_candidate.py (dry-run first).
5. Caption-fix unit to DeepSeek coder (post-tag), audited by me.
6. Whole-repo audit-lite (dev-rigor-stack-lite-audit-lite).

## 2026-10-02 FINDINGS (recorded before acting)
1. Repo is PUBLIC; no Git LFS in use (0 LFS files). Hygiene rule added (docs/FILE-HYGIENE.md, .gitignore). release/beta10 pushed to origin (no media/blobs; largest 0.6 MB; secret scan clean).
2. Baseline red tests: tests/policy+docs+release+api = 28 failures ALREADY at the committed branch (14 claims-evidence engine-binding drift, lan_only x3, native_caption_workflow floors x2, css tokens, v17 adoption gate, landing-page CTA, 2 audit-protocol docs); the version bump adds 5 more (current-release doc wording). egress preparer/daemon: 10 pre-existing failures (2 preparer: missing _ORPHAN_CACHE_TMP_MAX_AGE_S; 8 daemon). U67's 5 tests pass.
3. GATE A BLOCKER: documented publish path (docs/ops/release-candidates.md) requires 3 Gate A lanes PASS on a self-hosted Windows "sandbox-lab" runner. Both registered runners (blackwell-builder, HALO-gate-a) are OFFLINE. C:\actions-runner exists on this box but is not registered/running. Dirty + download-only lanes need the pinned baseline kit candidate-beta.5 in C:\CivicCastTester\kit-staging, which is gone (wiped 2026-09-17 per sandbox-lab/upgrade-baseline.json notes; CivicCastTester deleted 2026-10-01).
   Options: (A) revive runner + rebuild baseline kit (days, ~21 GB kits); (B) publish with Gate A waived (needs publish script/policy override = owner decision 2026-09-02 says all 3 required); (C) hosted build+sign (secrets exist) -> DRAFT release, no tag; publish only after Gate A or explicit owner waiver.
   RECOMMENDATION + ACTION: C now (reversible), then ask Scott for the explicit waiver (or approve A) at the publish step.
## Parallel tracks
- Docs agent (sonnet) on worktree civiccast-docs -> narrative docs + version-bound tests.
- Caption fix U68 (DeepSeek) after docs dispatch, off release/beta10.
- Branch/worktree cleanup only after every needed ref is verified on GitHub.
- Whole-repo audit-lite last.
