# Windows setup: install/upgrade engine (D3) and database creation (D4)  (nav id: installer-nsis-upgrade-database, section: Installer)
Source files (under `civiccast/apps/installer/src-tauri/`): `nsis-hooks-bootstrap.nsh:1030-1391`, `src/main.rs:6054-6155`, `src/native_service_registration.rs`; Python side `civiccast/native/provision/*.py`, `civiccast/native/upgrade` (not read in full)
Who can open it: runs inside the elevated setup.exe after pack verification. No roles.

## What it is for
Decides whether this run is a fresh install, a same-version re-run, or an upgrade, and for upgrades backs up, migrates and health-checks the database with rollback. Then it creates (or re-uses) the station's PostgreSQL database and stores its connection string in the registry.

## Step D3: install/upgrade engine (`step d3-engine`, `:1135-1285`)
Reads `HKLM\Software\CivicCast\Native\InstalledVersion` ("none" when absent) and `DatabaseUrl`, then runs `"$INSTDIR\runtime\python.exe" -m civiccast.native.upgrade --old-version <v> --new-version 1.0.0-beta.10 --install-root "$INSTDIR" --state-root "C:\ProgramData\CivicCast\upgrade" --database-url <current> --owner-run-id nsis-<window> --payload-source "$INSTDIR\runtime" --flat-installer-layout`. Details-pane line: "Running the CivicCast (Native) install/upgrade engine (D3)...".
| Engine exit | Meaning | Setup result |
|---|---|---|
| 0 | upgrade committed | "CivicCast (Native): install/upgrade committed." continue |
| 11 | fresh install, nothing to upgrade | "...no existing installation was found, so this is a fresh install — the install/upgrade engine was not applicable and did not run. Any CivicCast data already on this machine is preserved and adopted by this installation; nothing was deleted." continue |
| 12 | same version already installed | "...version 1.0.0-beta.10 is already installed — there is no database migration to run, so the install/upgrade engine did nothing. Your data was not drained, backed up, migrated, or changed." continue |
| 13 | older setup over newer install | setup exit 129: "A NEWER version of CivicCast (Native) is already installed on this computer, and this setup installs an OLDER one. CivicCast cannot move a station's database backwards, so setup stopped before changing anything at all -- no recordings, database or settings were touched. To continue: run the newer version's setup again, or uninstall CivicCast (Native) first if you genuinely mean to go back (your data in C:\ProgramData\CivicCast is preserved by uninstall, and an older version may not be able to read it). See C:\ProgramData\CivicCast\install-progress.log for the two version numbers." |
| 10 | engine rolled back its own work | setup exit 124: "CivicCast (Native) setup could not complete: the upgrade engine rolled back its own work before finishing the upgrade to 1.0.0-beta.10. Your previous version's database is intact and was not left mid-migration." plus either "The station's service has been stopped AND set to manual start, so it will not come up on the new files at the next restart either. A successful re-run of setup puts it back to automatic start." or, when containment was not confirmed, instructions to run `sc stop CivicCastSupervisor` and `sc config CivicCastSupervisor start= demand` (`:1253-1255`). Reason is in `C:\ProgramData\CivicCast\upgrade\upgrade-engine.log` and `upgrade-journal.json`. |
| 20 | engine's rollback also failed | setup exit 113: "CivicCast (Native) upgrade could not complete and automatic rollback could not restore the database. The service is stopped. Follow the recovery steps in: C:\ProgramData\CivicCast\upgrade\UPGRADE-RECOVERY.md" |
| 30 | release has a migration that cannot be rolled back | exit 114: "This CivicCast (Native) release includes a database migration that cannot be automatically rolled back. Automatic upgrade was refused. Use the manual upgrade path with operator acknowledgement." |
| 31 | an earlier failed upgrade's record is still on disk | exit 128: "CivicCast (Native) setup stopped before doing anything, because an EARLIER upgrade attempt on this machine ended in a failure whose record is still on disk... move (do not delete) the file C:\ProgramData\CivicCast\upgrade\upgrade-journal.json somewhere safe -- keep it for support -- and run setup again. Nothing on this machine was changed by this run." |
| other | unexpected fault | exit 115: "CivicCast (Native) setup hit an unexpected fault while running the install/upgrade engine (exit code N). See the installer log." |

## Step D4a: database provisioning (`step d4-provision`, `:1304-1391`)
Runs `"CivicCast Native.exe" --civiccast-provision --install-root "$INSTDIR" --owner-run-id <id> --existing-database-url <registry value>` (`main.rs:6091-6155`). The journaled Python engine creates the PostgreSQL cluster with `initdb` from the server pack under `C:\ProgramData\CivicCast\data\pgdata`, writes `postgresql.conf` and `pg_hba.conf` there, generates the database password, and writes the connection string to `HKLM\SOFTWARE\CivicCast\Native\DatabaseUrl` (readable only by SYSTEM and Administrators, SDDL `D:P(A;;GA;;;SY)(A;;GA;;;BA)`, `native_service_registration.rs:1276`). The database listens on 127.0.0.1; the first free port from 5432, 5433, 5434, 5435, 5544 is used (`provision/models.py:335-336`; `provision/port_select.py:140`). Re-running over an existing cluster is a no-op.
Details-pane line: "Provisioning the CivicCast (Native) PostgreSQL server (D4)..." then "CivicCast (Native): database/messaging provisioning complete (or already provisioned; no-op)."
| Provision exit | Setup exit | Operator text |
|---|---|---|
| 75 | 116 | "CivicCast (Native) setup could not provision the PostgreSQL server. See the installer log and C:\ProgramData\CivicCast\provision\PROVISION-RECOVERY.md for details." |
| 87 | 135 | another CivicCast product (the older WSL-based one) is registered: "...found another CivicCast product installed on this machine, so it will not claim the runtime. Setup stopped before provisioning: postgresql.conf, pg_hba.conf and your database credential were not touched. What setup observed: <line> Uninstall that product from Settings > Apps (or run its UninstallString above), or run civiccast-runtime cutover-to-native from it, then run setup again. Every read: C:\ProgramData\CivicCast\provision\OWNERSHIP-RECOVERY.md; also logged in install-progress.log." |
| 85 | 127 | "CivicCast (Native) setup could not establish which CivicCast runtime owns this machine... If this machine has no CivicCast WSL product, an administrator sets HKLM\SOFTWARE\CivicCast\ActiveRuntime to "native" and runs setup again. The exact command and every read: ...OWNERSHIP-RECOVERY.md; also logged in install-progress.log." |
| other | 117 | "CivicCast (Native) setup hit an unexpected fault while provisioning the PostgreSQL server (exit code N). See the installer log." |
The log also gets "step d4-provision: runtime ownership: <observation>" read from `provision\ownership-observation.txt` (`:1310-1332`).

## Controls and what they do
None (no operator controls). Interactive failures show an OK-only dialog; silent runs fail with the exit code.

## Typical task flows
1. Fresh install: D3 exits 11 (skipped), D4 creates the database.
2. Re-run same version: D3 exits 12, D4 no-op.
3. Upgrade: D3 backs up, migrates, health-checks; on rollback setup stops with exit 124 and keeps the old database.
4. Another CivicCast product present: follow the 135 or 127 dialog.

## Related settings / env / CLI / API
Registry `HKLM\Software\CivicCast\Native` (`InstalledVersion`, `DatabaseUrl`), `HKLM\SOFTWARE\CivicCast\ActiveRuntime`, `HKLM\Software\CivicCast` `Maintenance`. Folders `C:\ProgramData\CivicCast\upgrade`, `provision`, `data\pgdata`.

## Help-text findings
- [HELP-82] The 124 dialog gives raw `sc` commands (`:1255`), for a case where setup could not stop the service. A PEG station manager needs a copy-paste recipe plus where to find "Services"; the existing text is the only recipe and is hidden inside a rare branch.
- [HELP-83] "cutover-to-native" and "ActiveRuntime" (127, 135) are internal; no plain explanation that CivicCast has an older WSL-based edition that must be removed first.
- [HELP-84] Several dialogs say "database/messaging" (`:1334`) though messaging was removed; stale.
- [HELP-85] "D3", "D4", "journal", "owner-run-id" appear in the details pane (`:1136,1305`).
- [HELP-86] No dialog says how long the upgrade backup and migration will take or that the database is backed up (UNVERIFIED where the backup is stored).

## Screenshot plan
Details pane through D3 (fresh install and same-version re-run) and D4; the 129 downgrade dialog; the 135 dialog (needs the WSL edition installed).

## UNVERIFIED / open questions
- UNVERIFIED: the Python engine's backup location, journal contents and time; the registry ACL as applied (read only the constant).
- UNVERIFIED: the exact value format of `--owner-run-id` beyond `nsis-<window handle>` (`:1033`).
