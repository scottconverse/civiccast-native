# U87 existing Gate A baseline attempt binding - v1

Scope: narrow metadata repair in existing Gate A only. Checkout `C:\Dev\Claude\civiccast-u73`, branch `codex/u73-caption-measurements`, HEAD `7065963351a01e422ac0fb7e351cbaff191a2c5a` plus this uncommitted diff. Root reviews before commit. No workflow dispatch, installation, artifact download, helper/VM operation, native-source edit, or new harness/module performed.

Critical trigger: release acceptance/provenance. The previous build's identity must not change when later attempts fail, and historical metadata must not masquerade as current baseline-byte acceptance. Existing committed HEAD is the rollback checkpoint; only the four scoped files below changed, plus this receipt and check logs.

## Change and unchanged checks

1. `sandbox-lab/upgrade-baseline.json`: explicitly pin original successful build `run_attempt: 1`. Preserve source `148c8d2172dd6b63cbbb856b429b68aa020dc421`, installer hash `775b9a3e63a94183f1c065bb4168d03c0aeb2d72d608c1dbed5c875a94e05842`, reconstructed station-index hash `ff7c10a698116a66b292f76493daebfed8618244631859d0d5bfc95a4d945b16`, version and previous Gate A run. Existing notes now distinguish original build attempt 1 from reconstructed station producer attempt 2, successful job `105485113314`, owner receipt commit `8d5730a596989ab320b10edcf152d10883db1550`. Preserve the lost-original-index and reconstruction limitations.
2. `.github/workflows/gate-a-station-acceptance.yml`: both existing cross-version validators require a positive integer attempt (PowerShell int/long, not bool/string/fraction/zero/negative/null), query `gh run view --attempt` with that pin, and require returned attempt, completed status, success, exact source SHA and exact workflow name. All current installer/index hash, version, same-source refusal and local-kit checks remain unchanged. Logs say verified build identity, not verified local kit.
3. `tests/gate_a/test_gate_a_harness_contract.py`: extend the existing immutable-baseline contract test to require the attempt/provenance pin and both validators' fail-closed checks. No new test module or validator framework.
4. `docs/ops/gate-a.md`: narrow baseline paragraph correction, including the stale pre-native version identity in that paragraph. Describe original and reconstructed provenance separately and state that attempt verification does not establish kit availability or baseline PASS. Added doc lines are ASCII.

The station reconstruction is not reclassified as an original successful full build. Attempt 2 overall failed even though its station job succeeded. Remote metadata corroborates that job's success and exact parent source; its logs now return HTTP 410 and artifacts are gone. The owner-signed existing receipt binds its reconstructed index. Current baseline installer/index bytes could not be checked: the expected kit path is absent on this machine. Existing tester-side byte/version checks remain an unresolved prerequisite. No baseline PASS claim.

## Exact local verification

All commands ran from the checkout above with the existing interpreter `C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe` and no environment override.

Baseline:

```powershell
& C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe -m pytest tests/gate_a/test_gate_a_harness_contract.py -q -o addopts=
```

`98 passed in 3.66s`.

RED after extending the existing contract test, before metadata/workflow edits:

```powershell
& C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe -m pytest tests/gate_a/test_gate_a_harness_contract.py -k upgrade_baseline -q --tb=short -o addopts=
```

`1 failed, 97 deselected in 2.57s`, on `assert baseline.get("run_attempt") == 1`, actual `None`. Full failure is saved in `U87-BASELINE-ATTEMPT-red.txt`.

GREEN after scoped repair:

```powershell
& C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe -m pytest tests/gate_a/test_gate_a_harness_contract.py -q -o addopts=
```

`98 passed in 3.32s`, saved in `U87-BASELINE-ATTEMPT-green.txt`.

Affected-package widening:

```powershell
& C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe -m pytest tests/gate_a -q -o addopts=
```

`227 passed in 12.48s`, saved in `U87-BASELINE-ATTEMPT-affected.txt`. These exercise existing source/contract/verdict tests, not a sandbox or installation.

```powershell
& C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe -m ruff check tests/gate_a/test_gate_a_harness_contract.py
& C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe -m ruff format --check tests/gate_a/test_gate_a_harness_contract.py
git diff --check
gh run view 34405681086 --repo scottconverse/civiccast-native --attempt 1 --json headSha,workflowName,conclusion,status,attempt
```

`All checks passed!`; `1 file already formatted`; whitespace check passed with no output. The real read-only GitHub query returned:

```json
{"attempt":1,"conclusion":"success","headSha":"148c8d2172dd6b63cbbb856b429b68aa020dc421","status":"completed","workflowName":"native-beta-candidate-artifacts"}
```

Additional bounded falsification executed the actual two source attempt-guard blocks in local PowerShell, without running their surrounding workflow, invoking gh, writing source, or creating a harness. Eight cases per block: integer 1 and long 2 accepted; zero, negative, boolean, string, floating-point 1 and null rejected. Exact command:

```powershell
$workflowText = Get-Content .github/workflows/gate-a-station-acceptance.yml -Raw; $attemptGuards = [regex]::Matches($workflowText, '(?ms)^          \$previousRunAttempt = \$baseline\.run_attempt\r?\n.*?(?=^          \$previousInstallerSha256)'); if ($attemptGuards.Count -ne 2) { throw 'Expected exactly two source guard blocks.' }; $guardChecks = 0; foreach ($guard in $attemptGuards) { foreach ($case in @(@{value=1;valid=$true}, @{value=[long]2;valid=$true}, @{value=0;valid=$false}, @{value=-1;valid=$false}, @{value=$true;valid=$false}, @{value='1';valid=$false}, @{value=[double]1;valid=$false}, @{value=$null;valid=$false})) { $baseline = [pscustomobject]@{run_attempt=$case.value}; $baselinePath='synthetic-case'; $accepted=$true; try { . ([scriptblock]::Create($guard.Value)) } catch { if ($_.Exception.Message -notlike 'Invalid immutable previous candidate run_attempt*') { throw }; $accepted=$false }; if ($accepted -ne $case.valid) { throw 'Guard acceptance mismatch.' }; $guardChecks++ } }; Write-Output "Actual source guard cases: $guardChecks passed"
```

`Actual source guard cases: 16 passed`.

The added-doc-line check returned `Added doc lines ASCII: PASS`:

```powershell
$addedDocLines = git diff --unified=0 -- docs/ops/gate-a.md | Where-Object { $_.StartsWith('+') -and -not $_.StartsWith('+++') }; if ($addedDocLines | Where-Object { $_ -match '[^\x00-\x7F]' }) { throw 'Added doc lines contain non-ASCII text.' }; Write-Output 'Added doc lines ASCII: PASS'
```

Independent coordinator review: root reported the same actual PowerShell attempt metadata check and `98 passed in 2.40s` on the entire existing contract module. Root owns that independent receipt and final commit decision.

## Focused review

Engineering: both query sites bind the exact attempt; malformed pin values fail before gh; returned status/attempt checks strengthen the existing source/workflow/success predicate. UX: error output includes expected and actual attempt/status; success output does not imply local bytes were accepted. Tests: existing assertion failed before repair, module and package passed after it, and actual guards rejected malformed input. Docs: original build and reconstructed station provenance are separate; no original-byte or baseline-PASS overclaim. QA: installer/index pins and downstream checks unchanged; kit absence remains unresolved.

Files released to root for independent review and commit. No commit/push performed by this agent.

proved: existing contract RED/GREEN; 227 affected tests passed; 16 actual source guard cases passed; Ruff/format/whitespace passed; read-only exact-attempt metadata matched - lane: Critical
