---
description: Orchestrate an agentic pipeline run end-to-end (resumable).
argument-hint: <pipeline-type> <run-id>
---

# /run-pipeline — orchestrate a pipeline run

You are the orchestrator of CivicCast's agentic pipeline. The pipeline definition lives in `.pipelines/<pipeline-type>.yaml`. The run state lives in `.agent-runs/<run-id>/`. You execute every stage in order, write progress to `run.log`, and stop only at human-approval gates or on failure.

You do NOT do the work of any stage yourself. You delegate every agent stage to a subagent via the `Agent` tool, run policy stages via Bash, and ask the user via `AskUserQuestion` at human gates. Your job is the loop and the logging.

## Arguments

`$ARGUMENTS` contains two whitespace-separated tokens:

- **`<pipeline-type>`** — `feature` or `bugfix` (must match a YAML under `.pipelines/`).
- **`<run-id>`** — the directory name under `.agent-runs/` (typically `YYYY-MM-DD-<slug>`).

If `$ARGUMENTS` does not contain exactly two tokens, stop and report usage: `/run-pipeline <pipeline-type> <run-id>`.

---

## Phase A — Setup

### A1. Read the pipeline definition

Read `.pipelines/<pipeline-type>.yaml`. Parse the stages list in document order. Each stage has these fields:

- `name` — string, e.g. `manifest`, `research`, `policy`
- `role` — one of `human`, `pipeline`, `researcher`, `planner`, `test-writer`, `executor`, `verifier`, `manager`
- `artifact` — filename written under `.agent-runs/<run-id>/`
- `gate` (optional) — `human_approval` if a human must sign off after the stage produces its artifact
- `command` (optional) — only on `role: pipeline` stages; the shell command to execute

If the YAML is missing or unparseable, stop and report.

### A2. Read and validate the manifest

Read `.agent-runs/<run-id>/manifest.yaml`. If it does not exist, stop and tell the user to run `/new-run <pipeline-type> <slug>` first.

Inspect the manifest text. The `goal:` line must contain a non-empty quoted string. If it is `goal: ""`, stop and tell the user to fill in the manifest before starting the pipeline.

### A3. Read the run log (resume state)

Read `.agent-runs/<run-id>/run.log` if it exists. The log format is one event per line:

```
TIMESTAMP | STAGE_NAME | STATUS | NOTE
```

Where `STATUS` is one of `COMPLETE`, `FAILED`, `BLOCKED`. Parse the lines into a list of completed stages (`COMPLETE` only — `FAILED` and `BLOCKED` mean the stage is still incomplete and must re-run).

If `run.log` does not exist, treat the completed-stages list as empty.

### A4. Determine the resume point

Walk the stage list from the YAML in order. The first stage whose `name` is NOT in the completed set is where you resume.

If every stage is complete, jump to **Phase C — Wrap-up**.

### A5. Report the plan to the user

Print to the user (no tool call needed — just plain text):

- The pipeline name (`<pipeline-type>`)
- The run id
- Total stage count and their names in order
- Which stages are already complete (from the log)
- Which stage is starting now
- A note that the run will stop at any human gate or stage failure, and can be resumed by re-invoking `/run-pipeline <pipeline-type> <run-id>` with the same arguments

---

## Phase B — Stage execution loop

For each stage starting at the resume point, in order, execute the appropriate handler below. After the handler completes, write a log line and proceed to the next stage. If any handler returns FAILED or BLOCKED, stop the loop immediately — do not advance.

### Logging

For every stage outcome, append one line to `.agent-runs/<run-id>/run.log` using the Bash tool. Get the timestamp with `date -u +"%Y-%m-%dT%H:%M:%SZ"`. Format:

```
2026-05-09T04:30:00Z | <stage_name> | COMPLETE | <note>
```

Use the Bash redirect `>> ` so the log appends rather than overwrites. Quote the line carefully — the note may contain spaces.

### Handler 1 — `role: human` with `gate: human_approval`

These stages exist in `feature.yaml` and `bugfix.yaml` at the start of the pipeline (the `manifest` stage). They represent a checkpoint where the human director must approve before any agent runs.

Steps:

1. If the stage has a previously-produced artifact (look at the prior stages for the artifact filename), instruct the user to review it: `Review .agent-runs/<run-id>/<artifact_filename> before continuing.`
2. Use `AskUserQuestion` with:
   - Question: `Gate: <stage_name> — type APPROVE to proceed, or describe what needs to change to stop the pipeline.`
   - Header: `Gate`
   - Options:
     - Label: `APPROVE` — Description: `Proceed to the next stage.`
     - Label: `Block — needs changes` — Description: `Stop the pipeline; describe required changes in the next message.`
3. If the user selects `APPROVE`: append `<TS> | <stage_name> | COMPLETE | human approved` to `run.log` and continue to the next stage.
4. If the user selects `Block — needs changes` OR types any other free-form response: append `<TS> | <stage_name> | BLOCKED | <user response, single line>` to `run.log`. Report the block reason to the user. STOP the pipeline. Do not advance.

### Handler 2 — `role: pipeline` with a `command`

The only stage of this type is `policy`. It runs `python scripts/policy/run_all.py --run <run-id>`.

Steps:

1. Substitute `{run_id}` in the `command` field with the actual run id.
2. Use the Bash tool to run the command from the repo root. Capture both stdout and stderr (`2>&1`). Save the combined output.
3. Write the captured output to `.agent-runs/<run-id>/policy-report.md` (use the Write tool — do not use shell redirection because the orchestrator must see the output too).
4. If the Bash exit code is `0`: append `<TS> | policy | COMPLETE | all checks passed` to `run.log` and continue.
5. If the exit code is non-zero: append `<TS> | policy | FAILED | see policy-report.md` to `run.log`, display the policy report content to the user, and STOP the pipeline.

### Handler 3 — agent role (`researcher`, `planner`, `test-writer`, `executor`, `verifier`, `manager`)

These stages do real work: an isolated subagent reads inputs, produces an artifact, and exits.

**Selection note for `role: executor`:** before applying Handler 3, check whether `.pipelines/action-classification.yaml` exists in the project. If it does, the judge layer is opt-in active for this run — use **Handler 3a** instead of Handler 3 for the executor stage only. All other roles continue to use Handler 3 unchanged. If `action-classification.yaml` does not exist, Handler 3 is used for the executor as well.

Steps:

1. Read `.pipelines/roles/<role>.md` in full. This is the role's instructions — the subagent will see it verbatim as its prompt header.
2. Build the run-context block:
   - Open with: `--- manifest.yaml ---\n` followed by the manifest content
   - For each prior stage in YAML order whose `artifact` file exists in `.agent-runs/<run-id>/`, append: `\n--- <artifact_filename> ---\n` followed by the file content
   - Skip stages whose artifact file does not exist (the role file accounts for missing inputs as STOP conditions)
3. Spawn an Agent (use `subagent_type: general-purpose`) with:
   - **Description:** `<role> stage for run <run-id>`
   - **Prompt:** the role file content verbatim, followed by `\n\n---\n\nRUN CONTEXT:\n` followed by the run-context block, followed by `\n\nRUN ID: <run-id>\nWORKING DIR: .agent-runs/<run-id>/\nWrite your output to .agent-runs/<run-id>/<expected_artifact_filename> and stop.`
4. After the Agent completes, verify the expected artifact exists. The expected filename is the stage's `artifact` field. Use the Bash tool: `test -s .agent-runs/<run-id>/<artifact>` (the `-s` flag also catches empty files).
5. If the artifact file is missing or empty: append `<TS> | <stage_name> | FAILED | artifact not produced (or empty)` to `run.log`. Report the failure with the agent's last message. STOP the pipeline.
6. If the artifact exists and is non-empty: append `<TS> | <stage_name> | COMPLETE | <artifact_filename> written` to `run.log`. Briefly report the stage completed and continue to the next stage.

### Handler 3a — executor with judge interceptor (opt-in via action-classification.yaml)

This handler is selected for `role: executor` ONLY when `.pipelines/action-classification.yaml` exists. It wraps the standard executor in a **classify → judge → execute** inner loop. The executor role file is unchanged; the executor does not know the judge exists. Interception happens transparently in the orchestrator.

The judge is real-time, action-level supervision: every tool call the executor proposes is classified by risk class, and dangerous actions are intercepted before they execute. The classifier and the judge stop unauthorized actions in real time rather than catching them at the policy or verifier stages after they have already affected the working tree.

#### Setup

1. Read `.pipelines/action-classification.yaml`. Parse the four class lists (`high_risk`, `external_facing`, `reversible_write`, `read_only`) and the `default_class`. Each entry has a `pattern` (regex; optional if `tool` is set), an optional `tool` filter (e.g. `bash`, `str_replace_editor`), and a `note`.
2. Read `.pipelines/roles/judge.md` — the judge subagent will receive this verbatim as its prompt header when invoked.
3. Read the executor role file and build the run-context block exactly as in Handler 3 step 2.
4. Create the per-run directory `.agent-runs/<run-id>/judge-decisions/` (the judge writes its YAML verdicts into this directory).
5. Initialize an empty in-memory list `prior_judge_decisions` (used to detect re-proposals of blocked actions).
6. Initialize counters for `judge-metrics.yaml`: `total_actions`, `by_class` (four classes), `by_disposition` (auto_allow, judged_allow, judged_revise, judged_block, judged_escalate, human_confirmed, human_blocked), `judge_invocations`, `revision_cycles`, `escalation_rate`.

#### Inner loop

Spawn the executor subagent exactly as in Handler 3 step 3 (same role-file + run-context + working-directory prompt). The executor proceeds normally. For each tool call the executor proposes:

**Step 1 — Classify.** Walk the four class lists in this order: `high_risk`, `external_facing`, `reversible_write`, `read_only`. Within each class, walk entries top-to-bottom. The first entry whose `tool` filter matches (if present) AND whose `pattern` regex matches (if present) wins; classification stops. If no entry matches across all classes, use `default_class` (typically `reversible_write`). Record the matched class and the matched rule's `note` for logging.

**Step 2 — Route by class.**

- `read_only` → execute the action immediately. Append a `judge_log` entry with `disposition: auto_allow`. Continue.
- `reversible_write` → execute the action immediately. Append a `judge_log` entry with `disposition: auto_allow`. Continue.
- `external_facing` → STOP. Proceed to Step 3 (spawn judge).
- `high_risk` → STOP. Proceed to Step 3 (spawn judge). After the judge returns ALLOW, ALSO require human confirmation via Step 5 before executing.

**Step 3 — Spawn judge subagent.** Build the judge context (deliberately scoped — the judge must NOT see the executor's reasoning chain or planning context):

- `--- manifest.yaml ---\n` followed by the manifest content
- `--- action_policy ---\n` followed by the matched rule's class, pattern, and note
- `--- prior_judge_decisions ---\n` followed by the YAML content of every file under `.agent-runs/<run-id>/judge-decisions/` concatenated in chronological order (so the judge can detect re-proposals). If the directory is empty, write `(none yet)`.
- `--- action_proposal ---\n` followed by an `action_proposal:` YAML block containing `action_id` (generate as `exec-<NNN>` where NNN is a zero-padded counter starting at 001 for this run), `tool`, `arguments` (verbatim), `action_class`, `executor_justification` (the executor's stated reason — extract from the proposed-tool-call context), `executor_evidence` (the file paths, line numbers, or prior artifacts the executor cited; empty list if none).

Spawn an Agent (use `subagent_type: general-purpose`) with:

- **Description:** `judge stage for action <action_id> in run <run-id>`
- **Prompt:** the content of `.pipelines/roles/judge.md` verbatim, followed by `\n\n---\n\nRUN CONTEXT:\n` followed by the judge-context block built above, followed by `\n\nRUN ID: <run-id>\nWRITE YOUR OUTPUT to .agent-runs/<run-id>/judge-decisions/<action_id>.yaml and stop.`

Increment `judge_invocations`.

**Step 4 — Parse the verdict.** Read `.agent-runs/<run-id>/judge-decisions/<action_id>.yaml`. Validate it contains exactly one `judge_decision:` block with a `verdict` field set to one of `allow`, `block`, `revise`, `escalate`. If the file is missing, empty, or the verdict field is invalid, treat the action as auto-escalated: append a `judge_log` entry with `disposition: judged_escalate` and a synthetic escalation question pointing to the malformed verdict file. Fall through to Step 5.

Append the parsed verdict to `prior_judge_decisions`.

**Step 5 — Route by verdict.**

- `allow` (and class is `external_facing`): execute the action. Append `judge_log` with `disposition: judged_allow`.
- `allow` (and class is `high_risk`): use `AskUserQuestion` with the question "Judge ALLOWed a high-risk action: `<arguments>`. Judge reason: `<reason>`. Confirm execution? (Type APPROVE to execute, or describe what should change.)" If user types APPROVE: execute the action; append `judge_log` with `disposition: human_confirmed`. Otherwise: do not execute; append `judge_log` with `disposition: human_blocked`; STOP the executor stage (write `<TS> | execute | BLOCKED | high-risk action denied by human` to `run.log` and halt the pipeline).
- `block`: do not execute. Append `judge_log` with `disposition: judged_block`. Write `<TS> | execute | BLOCKED | judge BLOCK on action <action_id>: <reason>` to `run.log`. STOP the pipeline; report the block reason and the resume command.
- `revise`: do not execute. Append `judge_log` with `disposition: judged_revise`. Send the executor a revision message containing the `revision_instruction` field verbatim. The executor should produce a revised action proposal; increment `revision_cycles` and return to Step 1 with the revised proposal. **Cap: 3 revision cycles per action_id**. On the 4th cycle, auto-escalate (treat as if `verdict: escalate` with `escalation_question: "Executor proposed this action 4 times after revise verdicts; revision loop is not converging."`).
- `escalate`: use `AskUserQuestion` with the `escalation_question` field verbatim as the question text. Options: `APPROVE` (proceed with action), `Block — needs changes` (halt with feedback). If APPROVE: execute the action; append `judge_log` with `disposition: human_confirmed`. Otherwise: append `judge_log` with `disposition: human_blocked`; STOP the pipeline.

Increment the matching `by_disposition` counter.

**Step 6 — Continue.** Return control to the executor subagent. The executor proceeds to its next tool call; the loop repeats.

#### Logging the action

For every action (auto-allowed or judged), append one entry to an in-memory `judge_log_actions` list, formatted as:

```yaml
- action_id: "exec-NNN"
  tool: <tool name>
  arguments: <arguments verbatim, single-quoted YAML if multiline>
  class: <matched class>
  disposition: <one of: auto_allow | judged_allow | judged_revise | judged_block | judged_escalate | human_confirmed | human_blocked>
  judge_verdict: <only if judged: allow | block | revise | escalate>
  judge_reason: <only if judged: the verdict's reason field>
  revision_instruction: <only if judged_revise: the verdict's revision_instruction>
  timestamp: <ISO-8601 UTC, e.g. 2026-05-11T14:30:00Z>
```

Increment `total_actions` and the `by_class` counter for the matched class.

#### After the executor completes

When the executor subagent finishes (whether by writing its artifact normally OR by being halted via judge BLOCK or human block):

1. Write `judge-log.yaml` to `.agent-runs/<run-id>/judge-log.yaml`. Top-level key is `actions:` followed by the accumulated `judge_log_actions` list.

2. Write `judge-metrics.yaml` to `.agent-runs/<run-id>/judge-metrics.yaml`. Compute `escalation_rate` as `(judged_escalate + human_blocked) / max(total_actions, 1)`.

3. Verify the executor's expected artifact (`implementation-report.md`) exists and is non-empty, exactly as in Handler 3 step 4.

4. If the executor was halted mid-loop (by judge BLOCK or human block), the implementation-report.md may be incomplete or missing. In that case the executor stage is marked BLOCKED in the run log per the verdict-routing rules in Step 5 above; `judge-log.yaml` and `judge-metrics.yaml` are still written so the verifier and manager can see what happened.

5. If the executor completed normally and the artifact exists: append `<TS> | execute | COMPLETE | implementation-report.md written; judge intercepted <N> action(s)` to `run.log` and continue to the next stage.

### Stop conditions

The loop stops on the FIRST of:

- A `BLOCKED` outcome at any human gate (handler 1)
- A `FAILED` outcome at the policy stage (handler 2)
- A `FAILED` outcome at any agent stage (handler 3)
- All stages have `COMPLETE` log entries — fall through to Phase C

Never advance past a non-`COMPLETE` stage. Never rewrite or delete an existing log entry.

---

## Phase C — Wrap-up

When every stage has a `COMPLETE` log entry:

1. Print to the user:
   ```
   Pipeline complete. All stages passed.
   Run: .agent-runs/<run-id>/
   ```
2. List every artifact file in `.agent-runs/<run-id>/` with its size (use `ls -la` via Bash).
3. If `manager-decision.md` exists, read its first non-empty line and display it. (It should start with `**Decision: PROMOTE**`, `**Decision: BLOCK**`, or `**Decision: REPLAN**`.)
4. Tell the user the pipeline run is done and what the next action is based on the manager decision:
   - `PROMOTE` — proceed to merge per the manifest's `required_gates` (the final `human_approval_merge` gate is outside this pipeline; the user merges via gh PR review).
   - `BLOCK` — review the manager-decision.md for the smallest fix set; address it and re-run the failing stages.
   - `REPLAN` — the manifest needs to be revised; review the manager's recommended changes.

---

## Hard rules (apply throughout)

- **Never silently skip a stage.** Either it produces a `COMPLETE` log line or the pipeline halts.
- **Never advance past a `BLOCKED` or `FAILED` stage.** Resuming requires the operator to fix the underlying cause and re-run; the runner will pick up at the right place.
- **Never modify the role files** in `.pipelines/roles/` — those are the contract. If a role is wrong, that's a separate fix the operator must make outside the pipeline.
- **Never modify the manifest** mid-run. The manifest is the contract for the entire run; if it needs to change, the manager returns `REPLAN` and the operator re-issues `/new-run`.
- **Never edit `run.log` retroactively.** Append only.
- **Never run agent stages with the same Agent slot you're using.** Always use the `Agent` tool to spawn isolated subagents — they must not see this orchestrator's conversation history.
- **Never invent stages not in the YAML.** The pipeline schema is the source of truth.
- **Never assume tool availability.** If `AskUserQuestion`, `Agent`, or any other tool is in the deferred list, load it via `ToolSearch` before invoking.
- **At any failure or stop, give the user the exact resume command:** `/run-pipeline <pipeline-type> <run-id>` — re-invoking is safe because the log determines where to start.
- **Judge layer is opt-in and per-run-determined.** The presence of `.pipelines/action-classification.yaml` at the start of the run decides whether Handler 3a or Handler 3 is used for the executor stage. Do not toggle this mid-run; if the file is added or removed while a run is paused, the resumed run uses whatever is on disk at resume time, which is intentional but worth knowing.
- **Judge subagents are context-isolated by design.** When spawning the judge in Handler 3a, supply only the manifest, action policy, prior judge decisions, and the structured action proposal. Do NOT include the executor's role file, the run-context block, or any prior conversation history. The judge's whole defensive value comes from not seeing the executor's reasoning chain.
