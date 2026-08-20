# Pipeline Control Loop

The CivicCast pipeline continuation rule is mechanical.

During an authorized pipeline run, the agent may not send a final response, defer work, skip push, skip CI, write a stopping handoff, compact-and-stop, or pause unless `.agent-runs/<run-id>/active-control-state.md` records a valid stop condition, `scripts/policy/check_pipeline_control_loop.py --run <run-id>` passes, `scripts/policy/final_response_gate.py --require-active-run` prints `final_response_gate: ALLOW`, and `scripts/policy/agent_decision_gate.py` allows that specific decision.

`final_response_gate.py` is the pre-final executable. It discovers `.agent-runs/*/active-control-state.md` files and fails closed when any active run records `final_response_allowed: false`.

`agent_decision_gate.py` is the pre-decision executable. It rejects unverified blocker claims, invalid stop reasons, skipped actions without evidence, and any decision that conflicts with the active control state. With `--write-ledger`, it appends the decision to `.agent-runs/<run-id>/decision-ledger.ndjson`.

`pipeline_continue.py` is the navigator executable. It prints the active run's required continuation action when stopping is not allowed.

## v0.5.9 Scope Authority

Every product run must include `.agent-runs/<run-id>/scope-lock.yaml`. The
lock names the canonical release-plan rung, the rung title, the proof statement,
required modules, allowed feature terms, forbidden later-rung terms, and any
scope or exit-criteria text copied from the release plan.

The policy stage runs these scope-authority checks:

- `check_scope_lock.py` fails if the lock is missing or contradicts
  `docs/spec/release-plan.md`.
- `check_rung_file_ownership.py` fails if an edited path or proposed commit
  subject contains a term that belongs to a later rung.
- `check_release_docs_consistency.py` fails if release docs assign the current
  rung to later-rung work.

When all three checks pass, `run_all.py` writes
`.agent-runs/<run-id>/scope-lock-receipt.txt` with:

```text
scope_lock: PASS
canonical_rung: <version title>
edited_paths_match_rung: PASS
docs_consistency: PASS
```

No product commit is valid without that receipt. Cleanup commits may delete
stale later-rung artifacts, but they must not add or relabel later-rung work as
the current rung.

Once a scope-lock receipt exists, a prior `scope_conflict` stop for
scope-authority repair is stale. `final_response_gate.py` blocks that stale
state instead of treating it as permission to stop. The active control state
must advance to the next real pipeline gate, such as the manifest approval gate,
or to `stop_condition: none` with `final_response_allowed: false` when the run
must continue.

## v0.5.9 Pipeline Shape

Feature and bugfix runs include the hardened control stages after verification:

- `drift-detect` writes `drift-report.md` and blocks unreported scope, file, or claim drift.
- `critique` writes `critic-report.md` and blocks unresolved blocker or critical implementation risks.
- `auto-promote` runs `scripts/policy/auto_promote.py --run <run-id>`. When verifier, critic, drift, policy, judge, and test evidence all pass, it writes a parseable `manager-decision.md` starting with `**Decision: PROMOTE**`.
- `manager` is `auto_promote_aware`. When auto-promote already produced a PROMOTE decision, the manager validates and appends confirmation instead of re-deciding from scratch.

`scripts/policy/run_all.py` keeps CivicCast's project-specific
`check_ffmpeg_wrapper.py` check while adding the generic manifest-schema,
scope-authority, and GitHub Actions budget checks from the agent-pipeline
payload.

## Required Control State

Every active run records:

```yaml
active_run: true
current_stage: <stage-id-or-post-push-ci>
last_completed_gate: <gate-or-none>
next_required_action: <concrete-action>
stop_condition: none | human_approval_gate | failed_gate_needs_user_direction | destructive_action | credential_or_secret_required | scope_conflict | external_system_unavailable_after_retry | user_explicitly_paused_or_stopped
final_response_allowed: true | false
continuing_to: <concrete-action>
```

## Valid Stop Conditions

- `human_approval_gate`
- `failed_gate_needs_user_direction`
- `destructive_action`
- `credential_or_secret_required`
- `scope_conflict`
- `external_system_unavailable_after_retry`
- `user_explicitly_paused_or_stopped`

## Invalid Stop Conditions

- `successful_push`
- `green_ci`
- `recommended_next_action`
- `open_caveats`
- `release_or_tag_after_gates_pass`
- `pr_draft_status`
- `unverified_blocker_or_risk`

## Caveat Rule

`Open Caveats / Release Risks` is a blocking section. Each bullet must be fixed before the slice completes.

The only permitted unfixed bullet starts with `INTENTIONAL DEFERRAL:` and cites the manifest or director decision that authorizes the deferral.

## Post-Push Rule

After every authorized push, the runner monitors CI for the exact pushed SHA. If checks fail, the runner inspects logs, fixes failures inside scope, verifies locally, commits, pushes, and repeats.

Green CI is evidence. It is not a stop condition.

## Pre-Final Gate

Before every final response in an authorized pipeline run, run:

```bash
python scripts/policy/final_response_gate.py --require-active-run
```

If the command prints `final_response_gate: BLOCK`, do not send a final response. Continue to the printed `continuing_to` action.

Before every stop, defer, skipped push, skipped CI, handoff-and-stop, compact-and-stop, or user question during an authorized run, run:

```bash
python scripts/policy/agent_decision_gate.py --intent <intent> --claimed-stop-condition <condition> --write-ledger
```

If the command prints `agent_decision_gate: BLOCK`, do not stop. Continue to the printed continuation action or verify the claimed blocker with evidence and run the gate again.

When uncertain what to do next, run:

```bash
python scripts/policy/pipeline_continue.py
```

## Merge, Release, And Tag Rule

Merge, release, and tag are not stop conditions when the action is inside the authorized slice and all required review, test, judge, CI, and release gates have passed. The runner executes the action and continues to the next authorized control-loop step.
