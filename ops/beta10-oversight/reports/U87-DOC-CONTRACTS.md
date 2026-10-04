# U87 CI documentation/policy reconciliation - v1

Scope: six existing files; no product/public-page/evidence-byte changes,
publication, commit or push. u86 confirmed no ownership collision. Claims
registry, CI workflow and native-floor work belong to other owners.
Inspected source HEAD 89fd37abb7c04b7677f726a1f34eeb1c9d5d2615; failure source
d258e46d, CI run 37225882397, unit job 111505457850 (terminal 78 failures).
Root independently reviewed six diffs; requested descriptive manual-test name
applied. Lane: Critical for secret-check preservation in the proof parser;
the copy/layout assertion reconciliation is ordinary Standard work.

## Corrections, not restored historical promises

- `check_v15_resilience_gate.py`: proof JSON reads `utf-8-sig`, supporting
  PowerShell-produced UTF-8 BOMs. Six real committed evidence files were rejected
  solely for BOM. No evidence file or hash was edited; JSON parsing, secret key
  scanning, raw-secret checks, redaction rules and API contract checks remain.
  Existing tests add BOM clean/secret and malformed controls. Real logic fix.
- `test_portal_css_tokens.py`: app shared imports and undefined-token check
  remain. The owner-approved landing page links external `assets/web/site.css`,
  not old inline `--cc-paper`/`--cc-brand`. Test now checks actual external
  stylesheet linkage and every used custom property is defined. Removing the
  used paper token is rejected by the same assertion.
- `check_v17_adoption_gate.py` and `test_audit_protocol_docs.py`: retain hardware,
  cable and field-proof limits using current plain-language copy, not discarded
  DeckLink-specific historical sentences. Three independent omission controls
  reject removed hardware/headend/field limitations. Existing negative CG/SDI
  overclaim checks and adoption overclaim detector remain.
- `test_held_rc10_docs.py`: operator manual no longer needs the old internal
  Alembic-head sentence. Existing migration reference-doc head checks remain.
  Manual now explicitly checked for actual no-field-signoff and unproven cable/
  physical-card limits, plus existing release/candidate and overclaim guards.

No user-facing wording was restored merely to satisfy tests. No assertion about
real field readiness, install trust, publication identity or quality was relaxed.
No new test module, harness, policy framework or dependency was added.

## Exact verification

All commands from `C:\Dev\Claude\civiccast-u73`; Python executable:
`C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe`.

Baseline command:
`& 'C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe' -m pytest tests/policy/test_portal_css_tokens.py tests/policy/test_v15_resilience_gate.py tests/policy/test_v17_adoption_gate.py tests/test_audit_protocol_docs.py tests/docsite/test_help_deep_links.py -q 2>&1 | Tee-Object -FilePath ops/beta10-oversight/reports/U87-DOC-CONTRACTS-baseline.txt`

`4 failed, 13 passed in 10.24s`
Full failures saved: old inline CSS assumption, six BOM files through resilience
repo check, old DeckLink phrase in adoption and public-doc tests. CI also named
old manual migration assertion; that source assertion was reconciled above.

RED command:
`& 'C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe' -m pytest tests/policy/test_v15_resilience_gate.py -q -k powershell_bom 2>&1 | Tee-Object -FilePath ops/beta10-oversight/reports/U87-DOC-CONTRACTS-red.txt`

`2 failed, 4 deselected in 1.61s`
Both valid BOM proofs failed because the old parser reported invalid JSON.
Full failures saved; synthetic secret is not a real credential.

GREEN:
`& 'C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe' -m pytest tests/policy/test_portal_css_tokens.py tests/policy/test_v15_resilience_gate.py tests/policy/test_v17_adoption_gate.py tests/policy/test_held_rc10_docs.py tests/test_audit_protocol_docs.py tests/docsite/test_help_deep_links.py -q 2>&1 | Tee-Object -FilePath ops/beta10-oversight/reports/U87-DOC-CONTRACTS-green.txt`
`33 passed in 9.97s`, saved `U87-DOC-CONTRACTS-green.txt`.

Affected command:
`& 'C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe' -m pytest tests/policy/test_portal_css_tokens.py tests/policy/test_v15_resilience_gate.py tests/policy/test_v17_adoption_gate.py tests/policy/test_held_rc10_docs.py tests/policy/test_current_release_candidate_docs.py tests/policy/test_field_installation_docs.py tests/test_audit_protocol_docs.py tests/docsite -q 2>&1 | Tee-Object -FilePath ops/beta10-oversight/reports/U87-DOC-CONTRACTS-affected.txt`

`119 passed in 22.39s`
Includes actual local pandoc-backed docsite builds and help anchors. No skips.

`& 'C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe' scripts/policy/check_v15_resilience_gate.py`
`V1.5 RESILIENCE GATE: PASS`

`& 'C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe' scripts/policy/check_v17_adoption_gate.py`
`NATIVE ADOPTION GATE: PASS`

`& 'C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe' -m ruff check scripts/policy/check_v15_resilience_gate.py scripts/policy/check_v17_adoption_gate.py tests/policy/test_portal_css_tokens.py tests/policy/test_v15_resilience_gate.py tests/policy/test_held_rc10_docs.py tests/test_audit_protocol_docs.py`

Same file list with `-m ruff format --check`:
`All checks passed!`; `6 files already formatted`.
`git diff --check`: exit0, no output.
`& 'C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe' -m pytest tests/policy/test_held_rc10_docs.py tests/policy/test_portal_css_tokens.py tests/policy/test_v15_resilience_gate.py tests/test_audit_protocol_docs.py -q -k 'cannot_be_removed or missing_used_token or powershell_bom or malformed_bom or describes_field_limitations' 2>&1 | Tee-Object -FilePath ops/beta10-oversight/reports/U87-DOC-CONTRACTS-sensitivity.txt`

`8 passed, 16 deselected in 1.37s`, after manual test-name correction.

## Boundaries and review

CI docsite/help errors were missing pandoc, not obsolete anchors. Local help
checks pass; root independently owns hosted pandoc prerequisite 61ef21d8.
No workflow changes made here. Hosted CI after integration remains unrun.
Full repository CI still has separately owned product/fixture/registry failures.

Focused review: parser preserves fail-closed malformed/secret behavior, does not
rewrite signed/registered evidence; app and site styling paths tested separately;
missing field/hardware disclaimers still reject; migration detail remains in
reference-doc checks. No runtime locks, auth, UI, services or process behavior
changes. Scoped reversal of six hunks is rollback; never reset unrelated work.

proved: sensitive BOM RED/GREEN, four actual copy/layout omission controls,
119 adjacent tests PASS, both policy entrypoints/Ruff/diff clean; lane: Critical.
