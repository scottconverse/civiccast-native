# PR #245 CI corrections — October 13, 2026

The first pushed head, `ec68424e7316472e39938d1fd03227641d5e076d`, exposed three failures:

- Operator lint: synchronous state setters inside the network settings effect.
  Query data now supplies the form until an edit creates a local draft.
- Operator route check: the standalone login omitted the existing version label.
  It now uses the shared CivicCast logo/version component.
- Windows tests: `icacls` could not map the service SID before service registration
  (error 1332). The private-file and service-tree helpers now use native SID ACL
  APIs only for that exact failure. Other errors still fail closed. Private-file
  ACLs remain protected; tree grants preserve unrelated entries and protected
  installer children.

Focused verification before the correction push:

- Network settings unit checks: 3 passed.
- Existing `/sign-in` redirect browser checks: desktop and mobile, 2 passed.
- ESLint on the three changed UI files, TypeScript and frontend build passed.
- Four affected Windows ACL/recovery/vault modules: 55 passed.
- An actual unregistered SID reproduced error 1332. Native ACL readback proved
  the intended service permissions and preserved the protected child boundary.
  Review also caught and corrected descriptor DACL persistence on file grants.
- Full `mypy civiccast`: 701 source files passed.
- Ruff lint and formatting checks passed on the four changed Python files.

These results do not replace CI for the corrected head. No installer rebuild,
tag, release publication or host service change was performed.

The automated PR review also identified three backup issues. Corrupt/unreadable
saved state now produces a visible backup error without aborting station startup;
explicit schedule repair is required before creating backups. Scheduled failures
retry after 15 minutes and then one hour, with at most three attempts per UTC day.
Canonical destination/media overlap is rejected to prevent archives containing
earlier backups. The backup status response also correctly applies its existing
last-success path sanitization. The backup guide documents the changed behavior.

Final affected backup/runtime/wiring checks: 36 passed. Full mypy remained clean
across 701 source files after these changes; affected Ruff checks passed.

The mutation baseline also exposed a platform-specific test fixture: the saved
network-settings test wrote to the Windows location on Linux. It now isolates
both platform environment roots under its temporary directory and uses the real
path resolver. The focused test passed locally; Linux confirmation remains CI.

The first randomized suite completed with 24 failed, 11,344 passed and 100
skipped. Follow-up corrections normalize restore URLs and bound database
connection timeouts, use the defined login background token, put the unchanged
backup role dependency at router level so the policy checker recognizes it,
and document the intentional unauthenticated login exception. Focused restore
checks passed (28); CSS/role/backup checks passed (30), with overlapping backup
tests. Full mypy passed 701 files afterward.

Remaining policy bookkeeping updates refresh documentation-only DR bindings,
current native test counts/platform classification, workflow input bindings,
and tracked PDF/DOCX manual downloads. These do not require an installer rebuild.

On head 82372258581c6f91e365a76ac0d7c44945a47591, CI job 115537552943
passed 11376 tests (100 skipped, 5 deselected), but the native execution
verifier rejected six Windows-only cases incorrectly selected on Linux.
The dedicated native selection passed 2024 tests and skipped those six.
The claims verifier consequently rejected the failed producer; its named
claim tests had passed in the same log.

Those six identity/DPAPI tests now carry explicit windows_only markers.
Portable identity tests remain selected, all assertions are unchanged,
and the Windows collection remains 2256 non-integration tests. The pure
collection is 2024 with the existing 50-test-margin floor set to 1974.
All six workflow blob bindings were refreshed for that floor-only change.

Focused verification on Windows:
- Both changed modules without a marker filter: 10 passed.
- The same modules with -m "not windows_only": 4 passed, 6 deselected.
- Exact collection and workflow-floor policy checks: 2 passed.
- Registered-claims verifier check: 1 passed.
- Affected Ruff lint/format and git diff --check passed.

No production code or signed package changed. CI on the new head remains
required before merge; these local checks do not claim a new Linux run.
