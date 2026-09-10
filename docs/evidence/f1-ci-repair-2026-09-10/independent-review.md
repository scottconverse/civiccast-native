# Independent review: CivicCast local CI repairs

Reviewed 2026-09-10 against integration worktree
`work/f1-integration`, base HEAD
`5bc57d7e5500e10465c413632c2ece3cce32bfec` plus the uncommitted repair diff.

## Verdict

ACCEPTED for the authorized local CI-repair scope. No source finding remains
in the integrated mutation-harness, current-source claims binding, or Windows
launcher corrections.

This acceptance is local source and test evidence only. It is not a mutation
score, Linux PR-CI acceptance, installed-service acceptance, candidate/kit
acceptance, soak, Gate A, field acceptance, or publication approval.

## Source review

- Mutation harness: the pytester child imports only the real production
  `_hermetic_civiccast_state` fixture from `tests.conftest`. The child process
  receives its fake HOME/LOCALAPPDATA before importing that module, so the
  fixture's module-level real-root capture points at the deliberate fake
  profile. Unrelated autouse application fixtures are not registered. The
  import-tripwire variant proves that setup and teardown require no
  `civiccast` application import.
- Claims: both historical claim entries preserve claim prose and node IDs.
  Their four current-source bindings match current Git blobs:
  `engine.py` = `e6868282a4645d3a95c618c1e8ef8cc556436444` and
  `test_gst_engine_wsl.py` = `f9191cd11d871ba97bd284ea057c516c68e544a4`.
  Added comments correctly limit the correction to D2 change detection.
- Launcher: upstream uv 0.12.13 evidence establishes that interpreter lookup
  uses active RCDATA while script execution uses zipimport against the whole
  executable. The integrated repair validates both ZIPs by reading
  `__main__.py`, proves one active payload when old and new differ, rejects
  overlap/missing/ambiguous state before writing, zeros only complete old ZIP
  payload spans, preserves file size, rechecks both active PE resources, and
  verifies the whole-file ZIP-selected script. Idempotent normalization keeps
  an identical active script intact.

## Independently executed check

Executor: `/root/ci_review`, native Windows access, Python 3.12 virtual
environment from the integration worktree.

Command:

```text
.venv312\Scripts\python.exe -m pytest tests\test_hermetic_state_guard.py tests\native\test_app_payload_builder.py -q -p no:cacheprovider -p no:randomly
```

Result: exit 0, `88 passed in 9.94s`.

The first sandboxed attempt could not create the owner-Python process; it ran
no tests. The same exact command then ran with the already-authorized native
access and produced the result above.

## Reviewed reported evidence

- Integrated affected-file run: 213 passed in 99.43 seconds (lead-reported).
- Claims red/green: 18 failed and 107 passed before correction; 125 passed
  after correction, recorded in the integrated evidence directory.
- Mutation tripwire red/green: 1 failed and 1 passed before the narrow import;
  7 passed after it, recorded in the integrated evidence directory.
- Launcher matrix: `root-matrix.txt` reproduces uv 0.12.13 with active PE
  resources correct but the whole-file ZIP selecting the old CivicCast script
  and exiting 1. The fixed uv 0.12.12 and 0.12.13 launchers each execute twice
  through the relative runtime Python, report `sys.dont_write_bytecode=True`,
  and create no fixture bytecode. These matrix results were reviewed, not
  independently rerun by this reviewer.
