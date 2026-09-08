# Beta.5 release recovery — 2026-09-08

Owner assignment: finish the native Windows beta for LPM field installation
and operation, including documentation, green CI, merges, release and tag.
The release manager owns execution and coordination; station production
cutover and new spending are separate decisions. No skill-stage approval is
required. The obsolete cross-agent audit protocol was deleted by request.

## Starting evidence

- Source: `c292e28b98cecec2d3eaa7d03e4ec25b203143ee`, clean main.
- Local baseline: `uv run pytest -q` — 11,739 passed, 135 skipped, 3 failed
  in 2,204.02 seconds. All three failures repeated in isolation.
- Investigation corrected the initial classification: caption and migration
  failures assumed distinct clock ticks; the sidecar failure depended on an
  ignored local beta.4 sidecar with no adjacent installer. These are test
  fixture problems, not proof of broken caption publication or unsigned
  published binaries. The signing check correctly rejected missing evidence.
- Latest public release is beta.4. Current source is beta.5, unpublished.
- Candidate `609273d` passed Gate A but failed the separate tester soak.
  Later candidate `66e02c4` built successfully; its Gate A run 34069809445
  was cancelled without a verdict. Neither proves current-source readiness.

## Baseline repair verification

Commands use the existing canonical `.venv/Scripts/python.exe` with this
release worktree as the working directory:

```text
python -m pytest -q tests/captions/test_offline_caption_job.py tests/migrate tests/policy/test_sidecar_attestation_integrity.py
141 passed in 30.61s

python -m pytest -q tests/test_audit_protocol_docs.py tests/policy/test_sidecar_attestation_integrity.py
12 passed in 1.30s
```

The second command follows review corrections: remove the obsolete protocol
existence assertion, retain public-release documentation checks, and poison
the sidecar script's actual `policy_utils` import in its fixture. The signing
test proves both successful isolation and rejection of a missing installer.
Ruff checks passed for the changed test files. Independent Sol review found
the stale protocol test/references and ineffective original import poison;
both findings were addressed before pushing.

## Remaining release work

1. Reconcile fill-plan length with the engine's subchain limit and truthful
   rollover timing. Preserve later main's asynchronous reload settlement.
2. Enable seamless rollover by default and verify opt-out and explicit
   constructor overrides. Prove continuous output in the installed runtime.
3. Run the affected suites, full regression suite, UI checks and CI.
4. Build and sign one candidate; require clean, cross-version upgrade and
   download-only Gate A PASS verdicts for that same source SHA.
5. Run local Sandbox soak, then fresh two-hour physical tester soak with
   candidate identity and counters reset for that run.
6. Align README, installation guide, user manual, landing page, release notes,
   verification record and release truth. Publish verified beta.5 assets/tag.

## Existing tester control path

The tester uses the `soak8-e1acfe6-directives` branch for scheduled polling
and returns results on `tester/soak8-e1acfe6-DESKTOP-VBMA6O5`. Autorun scripts
are consumed once by filename; an existing recurring sampler continues
after a final verdict. A new candidate requires an explicit new directive
and a fresh run identity/counter set, not merely new kit files.

As observed on 2026-09-08, that tester is still collecting failure telemetry
for `609273d`. Its old verdict must not be reused for beta.5 acceptance.
Candidate delivery uses the existing coordinator LAN kit server; public
LPM delivery uses the GitHub prerelease assets after acceptance.
