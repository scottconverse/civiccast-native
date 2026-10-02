# Audit Lite — whole repo, beta.10 release line
**Date:** 2026-10-02
**Scope:** the whole `civiccast-native` repo at `release/beta10` (tip `264a6936`), split into five read-only slices: egress engine, captions + app/API + native supervisor, tests + CI, docs + file hygiene, security + build/install scripts. Full evidence per finding is in `slices/` next to this file.
**Reviewer:** AI agents (5 slice reviewers, sonnet) + the coordinator, who re-verified every Critical and the beta.10-critical Majors against the code.

> **Scope note (per the audit-lite rule):** a whole repo is normally the scope of the full audit team, not audit-lite. It was run as audit-lite on the owner's explicit request, as five parallel slices. It is a static read plus targeted runs, not a runtime audit. Several large modules were only partly read (listed under "Not checked").

## TL;DR
**Ship beta.10 as a labelled beta candidate (pre-release), not as production.** The playout path that the 8-hour run proved is sound and nothing found is a data-loss or core-playout blocker. But the audit found **3 Critical and 36 Major** issues, so it recommends the full audit team next. The most important truths for the owner: (1) the repo's own test suite is red in ~110 places because the code was re-based onto the lab station's installed bytes and several features the tests still pin are gone; (2) the release-signing secrets have no environment protection and `main` has no branch protection; (3) the anonymous contributor upload can fill the disk before any limit runs; (4) the new program-change watchdog has a gap on one path.

## Severity rollup (unique findings; B-002 and E-001 are the same defect)
- Blocker: 0
- Critical: 3
- Major: 36
- Minor: 35
- Nit: 8
(82 findings. 15 docs and hygiene findings (12 fixed, 3 mostly fixed) were already fixed on `release/beta10` by the two docs passes — see "Status".)

## Critical findings (all re-verified by the coordinator against the code)

### C-001 Critical: The code has silently lost features that its own tests still pin
**Dimension:** Tests / Correctness. **Evidence:** the "base the slice on the station's installed (LIVE) bytes" commits (a4ee3941, ce71c40a and similar) reset egress files to what was installed on the lab station; 24 tests (CODE-BUG class in `slices/slice-C-tests-ci.md`) fail because the features they pin are not in the tree — the loudness true-peak guard, orphan-cache reaping, the U62 round-2 mux-tail fence, caption diagnostics. A-002 shows two `test_u62b_*` tests that pass at 66ebd435 and fail at HEAD.
**Why it matters:** the tree and its tests disagree about what the product does; a reader cannot tell whether the true-peak guard "exists". The shipped behaviour is what the 8-hour run proved, so this is a repo-truth and test-gate problem, not a field failure.
**Fix path:** for each of the 24, an owner decision recorded in the repo: re-apply the feature (new unit + proof run) or delete/xfail the test with the reason. Then bring the 70 STALE-TEST failures in line with the intended behaviour.
**Blast radius:** egress/gst engine, loudness ride, preparer cache; `tests/egress` (74 failing, not the 10 previously known).

### B-001 Critical: The anonymous contributor upload accepts the whole body before any limit runs
**Dimension:** Correctness (security). **Evidence:** `civiccast/contribute/router.py:439-460` takes `file: UploadFile = File(...)` on a public, unauthenticated route; the only request-body limiter in `civiccast/app.py:2323-2350` is for the analytics path. The framework spools the multipart body to a temp file before the handler runs, so the 2 GB per-file, 5 GB per-IP, 50 GB total and rate limits apply after the data is on disk.
**Why it matters:** an anonymous caller who can reach the public portal can fill the system drive.
**Fix path:** enforce a `Content-Length` and streamed-byte cap in a middleware in front of the route (as done for analytics), or stream the upload without spooling; add a free-space guard.
**Blast radius:** every public multipart route; shared temp directory on the system drive. Exposure is reduced if the station does not expose the public contributor portal.

### E-002 Critical: Signing secrets are not environment-gated; the signing action is a mutable tag
**Dimension:** Correctness (supply chain). **Evidence:** 0 `environment:` blocks in `.github/workflows/*.yml`; `native-beta-candidate-artifacts.yml:868` uses `azure/artifact-signing-action@v2` (mutable tag) with the Azure client secret; `id-token: write` granted at `:103` but unused; `gh api …/branches/main/protection` returns 404 (main is not protected); the repo has only a `github-pages` environment.
**Why it matters:** anyone who can push a branch or a workflow change (including an automated agent holding the owner's token) can run a workflow that reads the pack-signing private key and the Azure signing secret.
**Fix path:** (owner settings, not code) create a protected `release` environment with the owner as required reviewer, move the signing secrets into it, add `environment: release` to the signing jobs, protect `main`, pin third-party actions to commit SHAs, drop the unused `id-token: write`.
**Blast radius:** all signing/publish workflows; `CIVICCAST_PACK_SIGNING_PRIVATE_KEY`, Azure secrets.

## Major findings that matter most for beta.10

- **A-001 (Major) — program-change watchdog gap.** `civiccast/egress/daemon.py` `_poll_reload_stall_watchdog`: when the watchdog's re-issued reload starts a background preparation, the "something is in flight" branch clears the step counter; if that preparation declines again, the cycle restarts at step one and the restart step is never reached. The synchronous decline that caused the 34-hour incident does escalate correctly. *Verified by the coordinator by reading the code; not reproduced by a test.* Fix: keep a per-pin re-issue count that a watchdog-initiated preparation does not reset; restart after N. Candidate for the next unit (U70).
- **E-001 / B-002 (Major, Critical if the real webhook provider is enabled) — webhook subscription SSRF.** `civiccast/subscribe/service.py:149` derives the signing secret from public inputs (`sha256(subscription_id:webhook)`), the route accepts any `http(s)` URL (`webhook_url: HttpUrl`), and the confirmation token is echoed back. Only reachable for delivery when `CIVICCAST_PROVIDER_WEBHOOK=real`; the default is a mock. Verified by the coordinator. Fix: per-install secret, private-address block, require out-of-band confirmation.
- **A-003 (Major)** — `tests/egress` has 74 failing tests; the engine reload-commit suite is effectively dark. **C-002/C-003/C-004** — the Linux CI gate would be red on any PR; 18 claims-evidence tests are red; **no CI runs on `release/beta10`** and `main` requires no checks. **C-005** — the suite is not hermetic against a machine-level `CIVICCAST_STAFF_TOKENS` (254 false reds on this box).
- **E-003 (Major)** — installer `open_operator_console` / `open_installer_log` run `cmd /C start "" <value>` after only a prefix check (`civiccast/apps/installer/src-tauri/src/main.rs` ~3777-3796, ~2943): a URL containing `&` becomes command injection. **E-004/E-005** — the pip-audit gate scans `uv.lock`, not the shipped `requirements-native-app.txt` (37 of 81 pins differ) and an allow-list entry is past its review date. **E-006/E-007** — no Host/Origin check on loopback setup routes; control plane runs as LocalSystem (owner-accepted, ADR 0021).
- **A-004 (Major)** — the loudness ride's timeout/cancel cannot fire while its decoder read blocks. **B-003/B-004/B-005 (Major)** — caption review rows/evidence WAVs and raw tap chunks are never pruned (B-004 reproduced), and `active.vtt` grows for the whole session: disk growth over weeks of uptime. **B-006** — a local authenticated user can wedge the supervisor control pipe.
- **C-007/E-015** — workflow-dispatch inputs are interpolated into `run:` scripts (injection pattern). **C-008** — Gate A auto-triggers onto an offline runner. **C-009** — the security-scan workflow has been red on `main` for two weeks.

## All findings (ID, severity, one line, status)
Status: **FIXED** = fixed on `release/beta10` already; **OPEN** = open; **OWNER** = needs an owner decision. Detail and evidence for each is in `slices/`.

**Slice A — egress** (`slices/slice-A-egress.md`): A-001 Major watchdog restart rung unreachable on async decline — OPEN. A-002 Major U62 round-2 fence absent but tested — OWNER. A-003 Major 74 failing egress tests — OPEN. A-004 Major ride timeout cannot fire while decoder blocks — OPEN. A-005 Minor probe not bound by prep timeout — OPEN. A-006 Minor async decline drops rollover horizon — OPEN. A-007 Minor stale HLS comments/tests (U51) — OPEN. A-008 Minor no free-space guard for 60 GB cache — OPEN. A-009 Minor `pop_pending_commands` not atomic — OPEN. A-010, A-011 Nit — OPEN.

**Slice B — captions/app** (`slices/slice-B-captions-app.md`): B-001 Critical upload before limits — OPEN. B-002 (= E-001) webhook SSRF — OPEN. B-003, B-004, B-005 Major unbounded caption data growth — OPEN. B-006 Major control-pipe wedge — OPEN. B-007…B-016 Minor, B-017…B-019 Nit — OPEN (B-016: real-Postgres tests skip silently by default).

**Slice C — tests/CI** (`slices/slice-C-tests-ci.md`): C-001 Critical lost features — OWNER. C-002…C-009 Major — OPEN. C-010…C-014 Minor, C-015, C-016 Nit — OPEN. Failure census: 113 failures after removing the machine-level token (70 STALE-TEST, 24 CODE-BUG, 18 CLAIM-DRIFT, 1 ENVIRONMENT); the 6 previously known counts are confirmed exactly.

**Slice D — docs/hygiene** (`slices/slice-D-docs-hygiene.md`): FIXED on `release/beta10`: D-001, D-002, D-003, D-004, D-006, D-007, D-008, D-009, D-010, D-012 (242 tracked files / 13.1 MiB removed), D-013 (my own over-broad `*.ts` ignore rule), D-014; mostly fixed: D-005, D-015, D-021. OWNER: D-011 (`CLAUDE.md`/`AGENTS.md` carry a stale standing release authorization). OPEN: D-016…D-020 (README is a 522-line changelog; jargon; WSL narrative; publish requires hand-editing ~28 files; landing page lacks doctype/charset/viewport).

**Slice E — security** (`slices/slice-E-security.md`): E-002 Critical — OWNER (repo settings). E-001 — OPEN. E-003…E-007 Major — OPEN. E-008…E-015 Minor, E-016 Nit — OPEN. **No committed secrets were found** in the tracked tree or the added lines of the last 200 commits (hits were test fixtures, public sample-cert passwords and a placeholder).

## What's working
- Playout correctness is evidenced, not asserted: 8-hour watched run, 16/16 loudness windows, 50 program changes with no holes, one service process throughout (`ops/beta10-oversight/verdicts/rung-8h-c16-…`).
- Auth: every `/api/staff/*` route is covered by staff middleware and state-changing routes have role checks; the earlier "DB password served unauthenticated" class is closed (slice B).
- Pack signing and extraction: ed25519 signatures, pinned hashes, reparse-point and path checks; hash-pinned build downloads; loopback-only bind with no `0.0.0.0`; network-disabled sandbox lab; portals and installer UI use no CDN assets or telemetry (slice E).
- Docs: 0 broken links across 30 docs; 195 of 202 documented environment variables resolve in code; every beta.10 figure matches the verification record (slice D, before the second docs pass).
- The build supply chain is pinned and the pin did its job: it refused a re-published model manifest. The fix (commit the three reviewed manifests, verified by hash) is on `release/beta10`.

## Watch items
- Six environment-variable names are spelled with one `C` (`CIVICAST_…`) in code and two elsewhere; the docs now match the code, but a rename or an alias is an owner decision.
- `tests/**` sleeps in 145 files; one real flake observed (installer timing).
- The caption-tap fix is partial by design (U68) and instrumented (U69); the tap is chronically about one segment behind its bound on three channels.

## Not checked
Most of the 8.4k-line `gst/engine.py`, `bridge.py`, `worker.py`, `strategy.py`; real GStreamer/ffmpeg/Postgres-backed tests (skipped on the audit host); ActivityPub signature checks; the OTT apps; GitHub repo settings beyond what the API showed; online advisory lookups; Windows ACLs; git history older than 200 commits; the installer was not run and the landing page was not viewed in a browser.

## Escalation recommendation
**Yes — run `audit-team-lite`** on (a) the egress engine with the A-001/A-002/C-001 findings as seeds, and (b) the public HTTP surface + signing/CI settings (B-001, E-001, E-002, E-003, E-006). Reasons: 3 Critical (the rule is 3+), findings span all five dimensions, and the C-001 root cause is architectural (the repo and the proven product diverged). None of this blocks publishing beta.10 as a clearly labelled beta candidate; B-001 and E-002 should be addressed before any broad public exposure of the station or any further release.
