# F5 installed signing and lifecycle acceptance — October 26, 2026

**Result: passed.** The existing signed candidate installed, activated, ran, and
uninstalled in an isolated headless Windows Sandbox with **12,288 MB** allocated.
No installer rebuild, LFS transfer, host-station change, or public release occurred.

- Candidate run: `40317362877`.
- Source: `423393349f87148e7253f93691a9a70478cc120c`.
- Setup SHA-256: `9b01304429a07220dd5f35b061a779fdc07744fb6d0ae45defec232eccb0375a`.
- Guest installation: `C:\CivicCastF5`, on the sandbox's native filesystem.
- Networking and virtual GPU were disabled. The existing local kit was read-only.
- Install began 18:44:36 MDT and completed 19:01:17 MDT, exit code **0**.
- Built-in offline inference passed for Gemma 4 12B, Gemma 4 E4B,
  TranslateGemma 4B, and the caption self-test. No activation assertion was skipped.
- The isolated service registered, ran, and answered `/health` with schema
  `0097_agenda_minutes`. This is startup evidence, not proof of broadcast quality.
- Installed launcher and uninstaller both had **Valid** Scott Converse
  Authenticode signatures and Microsoft timestamps. Exported files were matched
  against hashes computed from the actual installed guest files before verification.
- The real uninstaller ran 19:01:52–19:02:28 MDT, exit code **0**. The service,
  launcher, runtime, and packs were removed. The operator-upload sentinel and the
  PostgreSQL cluster's `PG_VERSION` remained unchanged. This checks the existing
  uninstall preservation contract, not every database row.

The earlier 16 GB allocation was a configuration, not a demonstrated minimum.
The first 12 GB attempt passed activation but failed service ACL migration when
installed onto a host-mapped folder. The corrected attempt used the native guest
filesystem, measured at approximately 82 GB free, and passed with the same signed
installer. This supports an isolation-path diagnosis; the first truncated traceback
does not establish the precise failing Windows ACL operation.

Both owned sandboxes were stopped. Disposable installation files and exported
executable copies were removed. The signed kit and small evidence files remain.
Scott's host station was not started, restarted, stopped, or upgraded by this check.

Machine-readable receipt: [f5-installed-acceptance-2026-10-26.json](evidence/f5-installed-acceptance-2026-10-26.json).
Raw attempt logs and scripts are retained locally under
`C:\CivicCastTester\f5-installed-42339334\`.

F5 is closed. F4's separate historical transition diagnosis remains unresolved;
this installer result does not close it or authorize tagging/publication.
