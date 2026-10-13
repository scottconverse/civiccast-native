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
