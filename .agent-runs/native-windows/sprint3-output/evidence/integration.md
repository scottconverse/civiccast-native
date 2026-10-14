# Sprint 3 integration record

Scope: items 8–11 only. No installer, release, tag, production cutover, soak or
external field-validation requirement was added.

## Source and documentation

The coordinator reviewed the settings API/worker/publish wiring, operator labels,
HLS publication and startup retention, output branch wiring, and EOS padding
lifecycle. The output worker independently reviewed EOS integration with the
output queues and normalization delay. It identified missing stop cancellation
and a pacing wait that could emit early; both were corrected before the final
two-case native check. No remaining material finding was reported in that scope.

Recorded-caption review caught a same-count edited-English CDN retry defect;
the worker reproduced and corrected it with four focused passing checks.

README, changelog, caption specification, worker operations guidance and affected
manual chapters distinguish current source from the published Beta 15 package.
OpenAPI, API reference and TypeScript API types were regenerated. The existing
manual assembler rendered the updated output diagram; PDF, DOCX and built-in
Help were regenerated using the existing scripts.

Commands:

```text
.venv\Scripts\python.exe scripts/generate-openapi-artifacts.py
.venv\Scripts\python.exe ops/docs-sprint/tools/build_manual.py
.venv\Scripts\python.exe scripts/render_user_manual.py --out-dir docs
.venv\Scripts\python.exe scripts/render_docsite_manual.py
.venv\Scripts\python.exe scripts/render_user_manual.py --out-dir docs --check-current
.venv\Scripts\python.exe scripts/render_docsite_manual.py --check-current
```

All completed successfully. MiKTeX emitted its administrator-update notice;
both rendered-manual currentness checks passed.

Final changed-Python Ruff check exposed nested-if style findings and a pairwise
iteration lint finding. Those mechanical corrections and formatting were applied;
the changed-file Ruff check passed. This did not trigger another media capture.

The coordinator's existing transition-ordering-module check exposed legacy
shorter-end assertions and incomplete pending-state fixtures. The implementation
always initializes the new lifecycle events before publishing pending state;
the test fixtures require those fields for meaningful abort-path assertions.
The final affected-module result is recorded in `eos.md`.

## Five-lens pre-push review

- Engineering: implemented paths and native emitted-output results are recorded
  in `outputs.md`, `eos.md`, `tails.md` and `hls-snapshot.md`.
- UX: recorded-caption settings distinguish enablement, selected languages and
  reviewed-track attachment; disabling is separate from live captions.
- Tests: focused checks exercise the affected settings and media paths. Native
  timing/output results remain distinct from mock ordering checks and package claims.
- Docs: affected source/manual/API surfaces updated; generated editions checked.
- QA: Beta 15 package and historical Beta 11 soak attribution preserved. Runtime
  overlay and combined-normalizer-transition limitations remain explicit.

CI and merge status are not claimed by this local record.

## Initial CI correction

PR #247's initial lint job reported two mypy errors in the new EOS path:
optional dictionary lookup before `is_set`, and an `Any` result from the
GStreamer time constant. The event is a required initialized field, so the
lookup now uses that invariant; the deadline explicitly returns `float`.
`.venv\Scripts\python.exe -m mypy civiccast/egress/gst/engine.py` passed,
and the affected-file Ruff check passed. No additional media run was needed
for these typing corrections.

The informational mutation job stopped during its baseline on the manual TOC
count: the recorded-caption section increased it from 645 to 646. The existing
complete-manual assertion was updated to the actual count; its single focused
test passed in 1.96 seconds. The generated manual itself was already correct.

The completed initial unit run reported 11,425 passed and 21 failed; the
randomized run reported the same 21 failures. The remaining corrections
update two obsolete output expectations (RTMP is now accepted and persisted;
HLS relay owns deletion flags), and rebind seven current-source registry
references for the reviewed engine, graph and native-test files. Historical
acceptance remains historical. The two output checks passed (4.64 seconds);
the existing claims-evidence module passed all 125 checks (96.18 seconds).
Ruff lint/format and diff whitespace checks passed for the correction.

Correction review: engineering preserves the required EOS event invariant;
UX has no new strings; output tests retain mapping and persistence checks;
docs retain historical/package boundaries; QA found no further issue in
this correction diff. CI for the pushed correction remains authoritative.
