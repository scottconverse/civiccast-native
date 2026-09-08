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

## Continuous playout and operator documentation

The runtime slice enables in-place reload by default, bounds slate plans to
the engine's 12-chain limit, and concatenates larger bulletin rotations so
no approved slide is discarded. Slate media is cache-addressed and published
atomically rather than overwritten while a worker may still be reading it.

Finite program and filler horizons now refresh before EOS. A terminal program
can arm filler without restarting the worker; a newly due program still cuts
into filler immediately. Reload settlement records ON_AIR or FALLBACK_SLATE
only after the worker reports application of that specific reload. Late
schedule changes are compared by projected horizon, not asset identity: a
repeated asset can be a new occurrence, whereas a shrinking suffix is not
an extension. The provider clock is sampled before the query, with a 250 ms
rounding tolerance. Filler-render failure leaves current output running for
the existing retry path, rather than initiating an avoidable restart.

The default Sandbox run now grades the strict seamless contract without
setting the opt-in environment variable. It records explicit override and
effective expectation separately; planned restarts, reload aborts and armed
reloads that never commit cannot pass under beta.5's default behavior.

README, landing page, installation/trust instructions and the user manual
describe this behavior without claiming installed-candidate proof. The PDF
parser preserves the full beta version; CI and native Windows use the same
renderer. First-install documentation now describes the signed model bundle,
not an assumed post-install internet model download.

### Verification before the runtime slice push

- Full egress suite: 1,298 passed, 34 skipped in 108.69 seconds. Skips include
  installed-GStreamer, TSDuck and POSIX-only checks; this is not installed
  runtime proof. After the final late-schedule correction, the daemon,
  automation and reload-policy suites passed again: 211 in 6.32 seconds.
- Control-room, CG and public-documentation suites: 450 passed in 34.03 seconds.
  The first run used an output folder outside the lab's permitted artifact
  roots and hit three intentional cleanup refusals. Rerunning under repo
  artifacts resolved those without changing cleanup policy. A fourth failure
  exposed a raw-Markdown landing-page link; it was corrected to GitHub's
  rendered document page before this rerun.
- Independent Sol source review ran 117 source tests (6 platform skips) and
  109 reload/engine/pipe tests (24 skips). A real FFmpeg exercise decoded all
  13 input slides across 7 concatenated rotations. Host FFmpeg's fontconfig
  failure caused image-only fallback during its text-render exercise;
  candidate-bundled fonts/text remain an installed-runtime check.
- Sandbox verdict tests: 70/70 under both PowerShell 5.1 and PowerShell 7;
  all eight lane-unit suites passed. Review found and repaired the previous
  mismatch between default-on runtime and opt-in-only strict grading.
- Type checking: all 674 service modules passed. Release identity check
  passed for v1.0.0-beta.5. Full regression/remote CI remain separate from
  these scoped proofs and must finish before merge/publication.

## Remaining release work

### Packaged publication-status correction

Independent documentation review found that the immutable in-product handbook
would continue calling beta.5 unpublished after publication. Its introduction
now describes beta.5 operation and directs readers to the exact signed release
and current release record, without claiming unfinished acceptance. PDF, DOCX
and in-product JSON are regenerated together. A new regression first failed on
the old unpublished banner. Build34234158877 on `9bf38833` was cancelled so the
final signed candidate will carry the corrected handbook rather than shipping
a known contradiction. README and landing-page download banners remain beta.4
until beta.5 actually publishes.

The second full local run finished with 11,753 passed, 135 skipped, six failures
and four teardown errors in 1,743.56 seconds. Its temporary directory inside
the checkout contaminated Git-discovery fixtures; those modules passed all
12 tests in an external system temporary directory. The four teardown errors
detected real local application-state writes during the run. Their writer is
under investigation; they are not waived or attributed to the named tests
without process-level evidence. No all-green local-suite claim is made.
The two affected API modules subsequently passed all 21 tests in a serialized
run with an additional Python audit hook refusing real-profile file/database
writes. The real files retained their earlier timestamps throughout that run.
This rules out a reproduced write in that rerun, not every concurrent writer.

### Integrated review follow-up

Baseline PR192 passed all required CI and merged as
`e15a1011c132efbb7bc19ce00fbbe50e99fc2b7b`. Runtime PR193 was pushed at
`44a02308154d79971093e5a18586a9c0289f5aa3`. GitHub review found that its
filler settlement wrote the correct channel state but still sent ON_AIR to
immediate health, sink and alert evaluation. A strengthened regression
observed settlement directly and failed with all three values still ON_AIR.
The correction passes the actual settlement target through both health paths;
the daemon, automation and reload-policy suites then passed 211 tests in
7.04 seconds. The in-flight signed build34231404699 was cancelled because
the final candidate must include this correction.

The previous full local run completed with 11,750 passed, 135 skipped and
six failures in 1,524.14 seconds. Five cleanup tests correctly refused the
selected output root; the other was the already-corrected landing link.
All affected modules passed in the allowed artifacts directory: 85 tests
in 6.37 seconds. A fresh full regression run was started separately.

Additional native-Windows runtime proof: 58 live GStreamer engine, HLS relay
and named-pipe tests passed in 99 seconds, using current source and the
already-installed GStreamer runtime without modifying the running station.
The historical `test_gst_engine_wsl.py` filename also runs native Windows;
no WSL was used. Bundled FFmpeg 8.1.2 rendered visible bulletin and slate
text despite nonfatal Fontconfig warnings. Its verified pack hash is
`2a26749b01d460ebd7aa2716c0714ea6d4ce9bc8d89ecdae56485b145eb91afb`.
These proofs do not replace installation/soak of the final signed candidate.

1. Prove continuous program and filler output in the installed runtime,
   including text rendering with the candidate's bundled FFmpeg/fonts.
2. Review the integrated physical-tester dispatch package and verify its
   actual-media checks, candidate binding and fresh-run counters.
3. Run the affected suites, full regression suite, UI checks and CI.
4. Build and sign one candidate; require clean, cross-version upgrade and
   download-only Gate A PASS verdicts for that same source SHA.
5. Run local Sandbox soak and a fresh two-hour physical tester soak with
   candidate identity and counters reset for that run. Dedicated tester
   operation may run alongside Gate A after a successful signed build;
   publication still requires all three Gate A lanes and the soak to pass.
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
