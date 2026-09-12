# beta.7 local repair verification - 2026-09-12

## Release identity

- Branch: `fix/f1-stall-recovery-20260912`.
- Green base: `5e8551a0b8983b8a3b2f54f7cb1641f55bec54cc`.
- GStreamer repair commit: `24e81a7abd8313538c4df0baf03a6fdba2e72d14`.
- beta.7 identity and generated-doc proof anchor:
  `ead9adda6f0573bc60333ce8f48a9863c248e6bb`.
- beta.5 and beta.6 are rejected. No beta.7 installer or kit has been built,
  gate-tested, soaked, or published.

## Failure and correction

The physical beta.6 tester reproduced a programme change where the replacement
leg completed preroll but the outgoing leg stopped producing output without
EOS. The ordinary output-stall watchdog ended the worker before the deferred
switch watchdog could commit the ready replacement. The tester diagnostic is
commit `b500789a` on branch `tester/soak8-e1acfe6-DESKTOP-VBMA6O5`.

The beta.7 engine correction forces a boundary only for the current deferred
transaction after all replacement holds are complete and the new leg is ready.
It then uses the existing selector-first commit and old-leg retirement path.
Stale, incomplete, immediate, natural-EOS, and already-committing transactions
retain their existing handling. Current `engine.py` Git blob:
`3c1d1ef21b22d8f5840c9353551a43d8e370ddd4`.

Local GStreamer ordering and watchdog verification passed 79 tests. The combined
focused release set passed 143 tests. A native Windows regression then executed
the worktree worker against the existing bundled GStreamer runtime dependencies
from candidate `39e7ec3cbb4ccbeb3009ff3257dfc314010151f3`. It passed in 63.48
seconds: the outgoing live UDP source froze without EOS after replacement
preroll; the 3-second stall budget forced one guarded commit, the worker resumed
TS output, the selector/retire/hold ordering held, and teardown was clean. The
552,720-byte capture passed the test's TS continuity checks. The worker log is
retained beside this note as `native-worker.stdout.txt`; `native-results.txt`
records the exact command, environment, source paths, raw pytest result and exit
code, while `SOURCE-BLOBS.txt` binds the engine and native regression bytes.

These source checks use a rejected candidate only for its bundled runtime
dependencies. They do not test or rehabilitate its product bytes, and they do
not replace the required installed beta.7 Sandbox, Gate A, or dedicated tester
soak.

## CI correction

PR head `4274e3eac5eae45bad73e5b359fe893e2df10bd6` passed the tracked manual
render gate. deterministic-detectors run `34680753672` then found two concrete
branch issues:

- `run_ffmpeg()` checked an already-set cancellation event after executable
  discovery. The correction checks before discovery and again before launch;
  all 60 FFmpeg wrapper tests and Ruff pass locally.
- The two historical GStreamer claim entries still bound the pre-repair
  `engine.py` blob. Both bindings now use the current blob above and native-test
  blob `70cabce5ea6825b10fca5f2498dc03d6298fd602`. This restores the registry's
  current-source drift tripwire. It does not reclassify the historical Windows
  observations or claim installed beta.7 acceptance.

Fresh PR CI remains required. After merge, beta.7 still requires an exact-source
signed build, Sandbox, Gate A, dedicated-tester soak, and publication only after
those gates pass.
