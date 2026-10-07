# Beta 11 preparation workflow verification

This receipt records local static and policy checks for the hosted
`prepare_only` route and the setup-only Whistle embedding correction. It does
not record a hosted workflow run, package build, installer, or Gate A result.

The checked worktree was branch `codex/beta11-whistle` at base commit
`4b237a05fac4eb16d1b659d84bfb49aba9797c2b`, with the candidate changes staged
for review. The builder emits the signed Whistle pack at
`artifacts/native-station-bundle/station/captions-whistle.ccpack`; the
installer embeds it with the station index and `core.ccpack` for setup-only
upgrade activation. `prepare_only` keeps the candidate binaries and small
station evidence, skips the full station bundle and installable-kit uploads,
and is explicitly ineligible for Gate A.

## Commands and results

Run from `C:\Dev\Claude\civiccast-beta11-whistle`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/policy/test_native_beta_candidate_workflow.py tests/gate_a/test_gate_a_harness_contract.py tests/policy/test_actions_budget.py tests/policy/test_workflow_runners.py
```

Raw result:

```text
........................................................................ [ 48%]
........................................................................ [ 96%]
......                                                                   [100%]
150 passed in 5.16s
```

```powershell
actionlint .github/workflows/native-beta-candidate-artifacts.yml .github/workflows/gate-a-station-acceptance.yml
```

Result: exit 0, no diagnostics.

```powershell
ruff check tests/policy/test_native_beta_candidate_workflow.py tests/gate_a/test_gate_a_harness_contract.py scripts/policy/check_workflow_runners.py
```

Raw result:

```text
All checks passed!
```

```powershell
.\.venv\Scripts\python.exe scripts/policy/check_workflow_runners.py
```

Raw result:

```text
check_workflow_runners: PASS - workflows use GitHub-hosted runners (allowlisted hardware/duration lanes excepted).
```

Both workflow YAML files parsed successfully. PowerShell parser checks passed
for the three changed staging/preparation scripts; Git Bash `bash -n` passed
for Gate A's eligibility preflight. `git diff --cached --check` and
`git diff --check` both exited 0; a trailing-whitespace scan of this new
receipt also passed.

The focused package/workflow/installer test command run by the packaging coder
was:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/native/test_build_native_station_bundle.py tests/installer/test_native_packs.py tests/native/test_whistle_asset_provisioning.py tests/native/test_app_payload_builder.py tests/native/test_station_runtime.py -q
```

Raw result: `216 passed in 6.25s` before setup embedding was added. After the
embed correction, the packaging coder ran the broader focused suite and
reported `384 passed in 11.00s`; the independent reviewer separately reported `384 passed in 10.13s`, plus actionlint, Ruff, the Beta 11 identity
checker, and `git diff --check` passing. The post-embed 150-test policy/Gate A
suite and actionlint were rerun above for this receipt.

## Five-lens review

1. **Correctness:** preparation upload checks each promised file exists and is
   nonempty, then compares the Whistle pack's size and SHA-256 with the signed
   station-index entry, checksum file, and build report. The setup-only
   installer embeds `station-index.json`, `core.ccpack`, and
   `captions-whistle.ccpack`; large cached station models remain local. The
   full model bundle and assembled first-install kit remain excluded from
   preparation runs.
2. **Security:** Gate A's hosted preflight uses the exact workflow run and
   full source SHA, with only `actions:read`, to detect the preparation marker
   before any Windows Sandbox lane. No signing private key was read, and no
   publishing or activation bypass was added.
3. **Operations:** `prepare_only` routes to `windows-latest` even if the
   invalid self-hosted choice is also selected, then fails before provisioning.
   The accepted station soak and monitor continue without local build, runner,
   or Sandbox activity. The preparation artifacts are estimated at about
   3.5 GB including the embedded and repeated Whistle pack copies; actual
   upload sizes remain unmeasured until a hosted run.
4. **Compatibility:** ordinary hosted/full and self-hosted/full branches
   retain their previous bundle and kit behavior. The preparation path retains
   signed candidate binaries and installer station resources while skipping
   only the large bundle and kit uploads. All three Gate A lanes depend on the
   candidate-eligibility result. The publisher was not changed.
5. **Evidence and limits:** local policy tests, workflow syntax/lint, and
   focused packaging checks passed. No remote build, signed artifact
   production, installer build, install, or Gate A run has occurred. The
   hosted PyAV wheel hash remains strict and unverified by this receipt. The
   Gate A skip preflight only applies after its workflow change reaches the
   default branch; before that, keep the shared runner offline and cancel any
   auto-queued Gate A run. One-day artifacts are temporary, and a preparation
   run cannot substitute for a full Gate A kit.

`proved: 150 affected policy/Gate A tests plus focused packaging suite, workflow lint/parsing, runner policy, Ruff, and diff check passed Â· lane: Critical`
