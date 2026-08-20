# Change C — Hardening + Status Contract + Stage Gate

> Part of the Stage B+D fix sprint. Findings closed: QA-002 (Critical);
> ENG-007/008/009 + QA-004/005 + W-5/6/7 (self-healing cluster, Major);
> QA-003 / ENG-013 / QA-007 (drive paths, Major); UX-002 / UX-003 / DOC-009 /
> UX-007 (status contract, Major/Minor); TEST-003 / W-9 (stage gate, Critical
> process); ENG-005 interim (Major); ENG-011 (Minor); TEST-004 annotations;
> TEST-007 (Nit); DOC-015 (Nit). Deferred with declaration: UX-006/UX-009 portal
> copy (#13 — no Node.js); watchlist items (trim writer, retry endpoint,
> rehearsal packaging, provenance model) per Scott's standing instructions.
> Decision basis (Scott, final): QA-002 → **reject at config load**; stage gate →
> **tiered** (full gate at stage completion, defined in-repo).

**Goal:** No silent permanent stalls (lease recovery, never-appeared deadline,
survive-and-log loop), no fail-open auth for role-less env tokens, Windows drive
paths resolve, the status contract tells consumers terminal-vs-retrying with a
stable failure-code taxonomy and operator copy, and the stage-completion gate is
a fixed in-repo definition.

## Tasks (each: failing test → implement → green → next)

### Task C1: Empty-scope staff token rejected at config load (QA-002)

**Files:**
- Modify: `civiccast/auth/tokens.py`, `civiccast/app.py`
- Test: `tests/auth/test_staff_auth.py` (extend)

- Tests first: (1) `_configured_tokens` with `tok:op:Name` (no roles) raises
  `StaffAuthError` naming the operator and the fix (`token:op:Name:role[,role]`);
  (2) `create_app()` with a role-less token in `CIVICCAST_STAFF_TOKENS` raises at
  startup (fail fast); (3) valid roled tokens still verify; (4)
  `verify_station_operator_token` path documented-checked: always issues
  `scopes=("admin",)` (regression assertion).
- Implement: shared `validate_staff_token_config()` called from `create_app()`;
  `_configured_tokens` enforces non-empty scopes; docstring rewritten ("roles are
  required; a token with no roles is rejected at startup").
- Check `PostgresStaffTokenStore` issue path for empty-scope tokens; if reachable,
  fail-closed there too (note choice in result file).
- Release note: CHANGELOG `[Unreleased] / Changed` — behavior change + migration
  path (add roles to existing env tokens).

### Task C2: Worker self-healing pass (TEST-006 list, test-first)

**Files:**
- Modify: `civiccast/live/finalization_worker.py`
- Test: `tests/live/test_finalization_worker.py` (extend)

Tests first (per TEST-006):
1. Stale-`running` lease recovery: seed `running` with old `started_at`; scan with
   `now` past the lease (`CIVICCAST_FINALIZATION_RUNNING_LEASE_SECONDS`, settings
   field `running_lease_seconds`, default 900); assert attempt-accounted `failed`
   + requeued with backoff (`failure_code="worker.interrupted"`), and a later scan
   retries to completion.
2. Never-appeared deadline: ending session, no file; advance `now` past
   `never_appeared_seconds` (default 1800) anchored on `LiveSession.ended_at`;
   assert terminal `failed`, `failure_code="recording.never_appeared"`,
   `failure_reason` operator copy includes the expected path.
3. `run_forever` survives a scan exception: session factory raising once inside a
   thread with `stop_event`; assert loop continues, next scan runs, and the
   exception was logged (`caplog`).
4. Terminal-failed exclusion (ENG-011): terminal job's `updated_at` unchanged by
   subsequent scans.
5. Multi-target resolution + rehearsal-target exclusion (ENG-005 interim): file
   under second target resolves; `local-rehearsal-recordings` target skipped;
   sticky-URI drop: a wrong `recording_uri` on a pending job re-resolves after the
   operator fixes targets.

Implementation: lease check + requeue in scan; deadline check in
`_ensure_or_observe_job`/scan; loop body `try/except Exception:
_LOG.exception(...)`; candidate query excludes terminal failed; module logging
(INFO attempt start/done, WARNING failures/recoveries); `_recording_path_for_session`
skips `local-rehearsal-recordings` and tries all targets until one resolves to an
existing file (falls back to first resolvable); `row.recording_uri` re-resolves
when a fresh resolution exists.

### Task C3: Windows drive paths + target_uri validation (QA-003/ENG-013/QA-007)

**Files:**
- Modify: `civiccast/live/finalization_worker.py` (`_local_recording_path`),
  `civiccast/live/models.py` (`RecordingTargetCreate.target_uri` validator)
- Test: `tests/live/test_finalization_worker.py`, `tests/live/test_router.py`

- Tests first: `_local_recording_path` parametrized over `C:\recordings`,
  `C:/recordings`, `file:///C:/recordings`, `/abs/posix`, `relative/path` (→ None),
  `http://x` (→ None). Router 422s for `http://`, relative paths, `not a uri`;
  201 for `file://` and drive paths.
- Implement: single-letter scheme → drive path (`Path(recording_uri)`); bare paths
  must be absolute; validator accepts `file://` (empty/localhost netloc), absolute
  drive/posix paths; rejects the rest with copy pointing at the `file://` form.

### Task C4: Status contract (UX-002/UX-003/DOC-009/UX-007)

**Files:**
- Create: `civiccast/live/migrations/versions/0024_finalization_failure_codes.py`
  (down_revision `0023_live_finalization_jobs`; adds `failure_code` String(64) NULL,
  `failure_detail` Text NULL)
- Modify: `civiccast/live/models.py` (columns + response fields + descriptions),
  `civiccast/live/finalization_worker.py` (classified failures), router summaries
  if needed; regenerate artifacts.
- Test: extend worker tests + `tests/live/test_router.py`.

- Failure taxonomy (stable codes + verbatim UX-003 operator copy as
  `failure_reason`; raw `str(exc)` goes to `failure_detail` only):
  `recording.never_appeared`, `recording.not_local`, `probe.failed`,
  `finalize.invalid_trim`, `package.failed`, `worker.interrupted`, `internal.error`.
  Internal `_ClassifiedFailure(code, operator_message, detail)` raised/wrapped in
  `_attempt_job` stages; `_record_failure` persists all three fields.
- Response model: add `terminal: bool` (computed: `completed`, or `failed` with
  `attempts >= max_attempts`), `failure_code`, `failure_detail`; `Field(description=...)`
  on every field incl. DOC-009's `state` retry semantics,
  `local_package_manifest_path` ("filesystem path, never servable"),
  `package_manifest_url` ("null = local-only, blocks publish readiness"),
  diagnostic markers on `recording_uri`/`local_package_manifest_path`/`failure_detail`
  (UX-007: render in a collapsed technical-details disclosure).
- Existing tests asserting raw text in `failure_reason` updated to assert the
  new contract (`failure_code` + copy; raw text in `failure_detail`) — contract
  change, not test-weakening; note in result file.
- Regenerate `docs/openapi.json` / `docs/API-REFERENCE.md` / portal generated
  types via `python scripts/generate-openapi-artifacts.py` (no Node typecheck —
  declared environment gap).

### Task C5: Stage-completion gate in-repo (TEST-003, tiered per decision)

**Files:**
- Create: `docs/ops/stage-completion-gate.md` — tiered definition: interim commits
  = targeted subsets OK; stage completion = full pytest 0-fail (named exclusions
  only) + `alembic heads`==1 + repo-wide `ruff check .` + `ruff format --check .`
  + scoped mypy (stage-touched files at minimum) + OpenAPI artifact check +
  runtime walkthrough + declared environment-gaps section; "Tests: PASS" must
  cite the full-suite count.
- Create: `scripts/run_stage_gate.ps1` — runs the mechanical parts, prints
  PASS/FAIL per check, exits non-zero on any failure.
- Reference the gate from the result-file template location (note in gate doc).

### Task C6: Annotations + nits

- Three trim tests: comment block marking synthetic seeding pending the
  repackage-on-trim-update follow-up story (TEST-004).
- `tests/live/test_finalization_worker.py` / `test_router.py`: state literals →
  `FINALIZATION_STATE_*` constants (TEST-007).
- `docs/adr/0010-live-session-state-machine.md`: drop the stale "31 tests" count
  (DOC-015).

### Task C7: Verify, result file, commit

- Full suite 0 failures (cite count); guards green; `scripts/run_stage_gate.ps1`
  passes end-to-end; ruff/mypy/format/OpenAPI/`git diff --check`.
- Result file `<ts>-local-change-c-hardening-contract.md` with declared gaps
  (Node, Docker) + clean-room Postgres acceptance criteria.
- Commit (signed-off): `fix(live): harden finalization worker, auth scopes, and status contract refs #98`
