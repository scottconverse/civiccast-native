# Fix: Python sdist sweeps in 640 MB of LFS proof-kit binaries

## Corrected diagnosis

The v1.3.0 binaries under `tester-handoff/v1.3.0/` are **Git LFS-tracked**
(`.gitattributes` routes `tester-handoff/v*/civiccast-*` through LFS so clean
proof machines can pull the proof kit). They are 134-byte pointers in git
history — NOT 640 MB baked into the repo. So:

- **No history rewrite** is warranted (they were never in regular git history).
- **Do NOT `git rm`** them or add them to `.gitignore` — they are intentional
  infra for the proof-machine workflow.

The real and only problem: hatchling has no `[tool.hatch.build.targets.sdist]`
config, so `python -m build --sdist` default-includes the whole working tree
and smudges the LFS files in, ballooning the release source archive to ~679 MB
(the wheel stays clean at ~1.4 MB because it only includes `civiccast/`).

## Fix

Add `[tool.hatch.build.targets.sdist]` with an `exclude` for non-source heavy
paths that have no business in a source distribution:
- `/tester-handoff` (the LFS proof binaries — the 640 MB)
- `/docs/releases/evidence` (screenshot PNGs)
- `/.agent-runs`, `/audit-*` (scratch)

## Verify

`python -m build --sdist` from a clean `git archive HEAD` extract drops from
~679 MB to a few MB; the wheel is unchanged; `pip install` of the new sdist
still builds (package source intact). No product-code change; full gate +
OpenAPI unaffected. Commit + PR; note to Scott that the task's
"remove committed binaries / rewrite history" premise was a misread (they're
LFS, intentional) and only the sdist exclude was needed.

## Option 2 (Scott chose): stop tracking proof binaries in the repo

Forward-only removal (no history purge): `git rm` the 4 LFS proof binaries
under `tester-handoff/v1.3.0/` (keep all text records); remove the
`tester-handoff/v*/civiccast-*` `filter=lfs` lines from `.gitattributes`
(proof kits ship as GitHub Release assets now — the v2.1.0 kit is already
attached); add `.gitignore` rules so the binaries can't be re-committed.
Effect: a default `git clone` at HEAD no longer downloads the ~640 MB
(git-lfs only fetches objects referenced at the checked-out commit). The LFS
objects remain in history but unreferenced at HEAD; an optional filter-repo
purge (Option 3) is a separate later follow-up.
