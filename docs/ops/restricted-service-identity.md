# Restricted Windows service identity

The station-operations implementation replaces the beta LocalSystem account
with `NT SERVICE\CivicCastSupervisor`. This is a Windows virtual account: it has
no operator-managed password and is not added to Administrators.

The installer grants the service read/execute access to installed application
files and modify access to station data. The database connection registry key
grants it read access. Private station credentials grant it read/write access;
ordinary users are not granted access. The station control pipe recognizes this
specific service identity, while other unprivileged accounts retain read-only
status access.

Protected installer and recovery-journal directories retain their existing
administrator/SYSTEM boundary. Migration applies recursive write grants only
to runtime-owned data, logs, profile, credentials, configuration and downloaded
component directories, rather than overriding every protected directory under
ProgramData.

For an existing LocalSystem installation, setup first stops the station. It
starts the newly registered service once in migration-only mode under the old
account. That process copies and verifies the old CivicCast profile and
`.civiccast` configuration, exports only CivicCast's Windows Credential Manager
entries into the protected station vault, and exits without starting station
processes. Only after this succeeds does setup change the account and configure
its profile under `C:\ProgramData\CivicCast\profile`.

Original profile files and Credential Manager entries are retained. A conflicting
destination or failed migration stops the account change. Existing unrelated
service environment entries are preserved. Installer restoration preserves the
saved supported service account instead of substituting LocalSystem.

If migration exceeds its 90-second limit, setup requests a stop and waits up to
30 seconds for the service to stop before restoring its normal environment.
If it is still stopping, setup retains migration-only mode and leaves the
account unchanged; follow the reported stop condition before restarting.

The machine-protected credential vault is
`C:\ProgramData\CivicCast\credentials\station-vault.dpapi`. Copying this file
to another computer is insufficient: use an encrypted station backup, which
exports portable credential values inside the passphrase-encrypted archive and
protects them again on the replacement computer. Scheduled-backup passphrases
are stored separately and must be retained independently by the operator.

Custom domain or local service accounts are not automatically converted. Setup
reports that condition before changing the account. This implementation does
not change the Windows account used by other applications or their credentials.

Implementation status: development-source integration verified. An isolated
Windows SCM run migrated a LocalSystem profile and credentials, started the
service under the virtual account, served the healthy API with the current
database schema, and created and verified an encrypted PostgreSQL backup.
Protected installer journals remained restricted to SYSTEM/administrators.
This used the installed runtime with current source overlaid in a disposable
guest; it is not a signed-installer or broadcast-load result. The published
Beta 15 installer and the running host station are unchanged.
