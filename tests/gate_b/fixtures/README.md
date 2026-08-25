# `tests/gate_b/fixtures/` — deliberately empty of run evidence

Gate A's tests are anchored on `tests/gate_a/fixtures/pass-2026-08-19/`, a
verbatim copy of a real Windows Sandbox run's output directory. Gate B has no
such directory, and this file exists so that absence is a recorded fact rather
than something a reader has to infer.

**Gate B has never been run.** As of this file's commit no 24-hour reboot soak
has been executed against any candidate — Hyper-V is not yet enabled on the
`sandbox-lab` runner box (`gate-b/Test-GateBPrereqs.ps1` reports
`Microsoft-Hyper-V-All: Disabled`), and the first real run is scheduled
separately from the change that built the harness.

So `tests/gate_b/test_gate_b_verdict.py` builds every evidence directory it
judges **synthetically**, in `tmp_path`, from one documented builder
(`_pass_evidence`). That is enough to prove the judge's logic — every check,
every FAIL branch, both non-verdicts, and the CLI exit codes — and it is
explicitly **not** enough to prove anything about the product. A synthetic
PASS means "the judge would pass evidence shaped like this", never "the
candidate passed".

Fabricating a plausible-looking `pass-2026-XX-XX/` directory here and letting
it read as a captured run would be precisely the authored-truth failure these
gates exist to eliminate. The directory stays empty until a real run fills it.

## When the first real run lands

1. Copy that run's evidence directory here verbatim, named
   `<verdict>-<YYYY-MM-DD>/` (Gate A's convention), including whatever it got
   wrong.
2. Add a `FIXTURE-NOTES.md` beside it recording the candidate sha, the run id,
   the host, and any known harness quirk in that run — the way
   `tests/gate_a/fixtures/pass-2026-08-19/` documents its own missing
   `DONE.json` rather than papering over it.
3. Add a test that judges the real fixture and asserts its **actual** verdict.
   If the first real run is a FAIL, the test asserts FAIL. Do not special-case
   a fixture to force a PASS.
