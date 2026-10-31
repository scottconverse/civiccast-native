# CivicCast Station Backup and Restore

Station backups protect the ordinary operating state of CivicCast. They are separate from installer rollback: installer rollback returns program files to the previous build, while this workflow restores the station database, selected configuration and credentials, and selected media after loss of the station disk or computer.

## What is included

The effective app-platform configuration (including station branding) is included independently of the station-state path. Supported configuration/storage overrides are respected. PostgreSQL routine backups use one exported snapshot for both dump and inventory; ordinary live health writes do not invalidate that snapshot. Configuration and media are copied afterward, so this is not a single atomic snapshot of every external file.

RC1 automatically includes managed agenda originals, hashes, completed-page checkpoints, previews and confirmation state, together with associated database records and saved agenda source settings. No agenda media-root selection is needed. Managed agenda data restores to the replacement installation’s configured document root; do not copy old absolute paths into the new service configuration. Resume the restored preview against the retained original to reuse completed work. An existing replacement agenda tree is preserved beside it as a `.pre-restore-*` rollback directory before the archived tree is restored, preventing stale previews from surviving against the restored database. Other configuration/media mappings still require the existing explicit restore path map; managed agenda mapping overrides are rejected.

Configuration discovery runs for every backup, so files created after the service starts are included. The portable credential adapter also captures an allowlisted set of CivicCast service settings, including SMTP and subscription credentials. Restore applies only those settings to the CivicCast service's own environment registry value; it preserves the replacement database URL and replacement-machine profile/path settings, and does not edit machine-wide environment values. Plaintext archive staging and decrypted restore staging receive a restricted ACL before any station secrets are written.

The station runtime supplies the active database URL, configuration files, credential files, selected media roots, and portable credential exporter/importer. The backup service captures a consistent SQLite snapshot or PostgreSQL custom-format dump using the existing DR backup helpers. PostgreSQL cluster globals are retained in the package's database backup set. Every selected media file is copied in full and hashed; symbolic links are rejected. The portable credential adapter must export CivicCast keyring entries as portable values and import them on the replacement station. Machine-bound DPAPI/keyring blobs are not portable and must not be copied as a replacement for that adapter.

The complete bundle is an AES-256-GCM encrypted `.ccbackup` archive. The encryption key is derived from the recovery passphrase with PBKDF2-HMAC-SHA256. Choose a unique passphrase of at least 12 characters, record it somewhere separate from the backup drive, and test it with **Verify**. The passphrase is not saved in the archive directory or backup status file. Scheduled backups obtain their passphrase through the station's OS-protected secret provider.

Backup creation reports database snapshot, media copy, encryption, and completion progress. A new encrypted file is atomically published before retention removes older CivicCast `.ccbackup` files. Retention is bounded from 1 to 100 files. Keep at least one copy on storage that is not attached to the station; a destination on the same disk does not protect against disk failure.

If creation fails, status retains the failed phase and last progress, with an operation identifier and safe next steps. Database-stage guidance covers database availability, service-account access and bundled backup tools; it does not diagnose which one failed. Copy, credential export, encryption, publication and retention failures identify their own stage. Keep the operation identifier when seeking support; do not send database URLs, passwords or passphrases. A retention-stage failure can happen after publication: verify the new archive before retrying. Earlier errors clear when another backup starts, and the screen hides obsolete operation errors while a new request runs.

On an installed Windows station, run `civiccast backup` commands from an interactive PowerShell opened with **Run as administrator**. The CLI checks elevation before loading protected service configuration or prompting for a recovery passphrase. An installation without the CivicCast service has no blanket elevation requirement; its selected files and database still need appropriate access. The operator web screen runs through the station service and does not require elevating the browser.

## Operator workflow

1. Open **Station backup and restore** and choose an absolute destination folder. A removable or network-mounted destination can be selected if it is available to the CivicCast service account.
2. Enter each selected media folder as an absolute path and choose **Save schedule** before creating the first archive. Leave daily scheduling disabled until the unattended passphrase is saved. The list persists with the schedule and every file beneath those roots is included. Review the selected roots when media storage changes.
3. Create an encrypted backup and store the recovery passphrase separately. Download or copy the `.ccbackup` file to a second device or off-site location.
4. Verify the archive with the same recovery passphrase. A successful verification authenticates the encrypted archive and checks every bundled file's SHA-256 digest.
5. Save an unattended recovery passphrase in protected station storage, then set the daily UTC schedule and retention count. The station integration protects this scheduler-only secret with its OS secret vault; the backup service never writes the passphrase into its schedule or status state. Keep the passphrase available to the operator who would rebuild the station.
6. Periodically verify an off-station copy.

The backup destination and selected media roots must be separate, non-overlapping paths. The scheduler retries a failed daily run after 15 minutes, then after one hour, with at most three attempts per UTC day. A successful run suppresses further attempts until the next UTC day; the latest failure remains visible until another backup begins or succeeds. If the persisted schedule state cannot be read or validated, status reports the error and backups remain blocked until a valid schedule is saved.

## Restore after disk replacement

Restore is an offline, full replacement-station operation. Run it on the replacement computer, not on a live/source station to test a clone. Changing the database URL or file mappings does not redirect the local credential vault or service settings. Those belong to the machine running the command and are overwritten only after explicit acknowledgement. Do not overlay a running CivicCast station or database.

1. Provision the replacement computer, CivicCast program, service identity, database server, and runtime paths. Do not run station writers during restore. Before overwriting the replacement station, preserve any data it already contains with a separate backup. The offline CLI holds the station mutex and requires the CivicCast service stopped. For a local managed PostgreSQL target, it verifies the bundled cluster is stopped, starts only that database for the restore, and stops it again on completion or failure; the station service and other workers remain stopped. An explicit external PostgreSQL target is left alone and must already be available. The restore drops archived objects and replays them in one transaction. The connection user must be able to create and drop CivicCast objects and becomes the owner of restored objects.
2. Make the encrypted archive available and resolve the new station's target paths. The runtime CLI integration supplies the station's configured service, database, and credential adapters rather than guessing local paths.
3. Authenticate and list the old source paths from the archive:

   ```powershell
   $CivicCastPython = '<install-root>\runtime\python.exe'
   & $CivicCastPython -m civiccast.cli backup inventory D:\Recovery\station-backup-YYYYMMDDTHHMMSSZ-0123abcd.ccbackup
   ```

   Inventory prompts for the recovery passphrase. For configuration files and selected media, use the listed source paths as keys in a JSON object that maps each old absolute path to its replacement absolute path. Configuration and credential files map to their new file locations; each selected media root maps to its new directory. Omit inventory entries marked `managed_root: agenda-import`: their original files, manifests, checkpoints and previews map automatically to the replacement runtime's configured agenda document root. The portable credential export is handled by the secret adapter, not a file-path mapping. Include `agenda-import-settings.json` in the configuration mapping to the replacement station-state directory.

   When a selected media root moves, restore also rewrites the matching path prefixes in `civiccast.assets.file_path` and `thumbnail_path`, `civiccast.watch_folder_configs.monitor_path`, and `civiccast.watch_folder_file_state.file_path`. If the mapped configuration includes `station-state.json`, its `station.storage_locations.media_library`, `recordings`, and `backups` values are updated when they fall beneath a selected media root. Other configuration contents and paths outside selected media roots are preserved as captured. Choose media targets that match the replacement station's configured upload and watch-folder locations; restore does not change the replacement machine's service environment or runtime path settings.

4. Set `CIVICCAST_TARGET_DATABASE_URL` to the intended replacement database URL in the administrator session (or supply `--target-database-url`). An explicit target is mandatory, including for this replacement machine's local database. Restore never falls back to the installed database. The old misspelled `CIVICAST_TARGET_DATABASE_URL` remains supported for compatibility; conflicting environment values are rejected. Then restore the database and mapped files while confirming the service is stopped:

   ```powershell
   & $CivicCastPython -m civiccast.cli backup restore D:\Recovery\station-backup-YYYYMMDDTHHMMSSZ-0123abcd.ccbackup `
     --target-paths-json D:\Recovery\target-paths.json `
     --restore-local-station-settings `
     --confirmation RESTORE
   ```

   The CLI displays the resolved database host/name, file destinations and local credential/settings destination without database authentication or query parameters. Check these destinations and answer the confirmation before entering the recovery passphrase. The literal `RESTORE` argument and `--restore-local-station-settings` acknowledge a full replacement-station restore. SQLite restores into a staged file, checks `PRAGMA integrity_check`, then replaces the configured database path; an existing SQLite target is preserved beside it with a `.pre-restore-*` name. PostgreSQL restore uses `pg_restore --clean --if-exists --single-transaction`, omits source ownership/ACLs, and applies objects as the replacement connection role. It requires the explicitly selected replacement database URL; an omitted target is refused before restore begins. Restore tooling and managed database paths are resolved by the installed station runtime, which holds the station restore mutex and verifies the local database server is stopped before taking temporary restore ownership.

5. The restore command automatically imports the archive's portable credentials through the installed station secret adapter. Review the restored service configuration and media paths, then restart CivicCast and confirm normal station operation.

The installed runtime includes the `civiccast` console script, but a replacement shell may not have its `Scripts` directory on `PATH`. The commands above invoke the installed `runtime\python.exe` directly; replace `<install-root>` with the directory where CivicCast is installed.

The offline restore service verifies the archive, path mappings, and portable credential payload before applying the database. File and credential restoration follows database restore, so a disk or permission failure during later file copies can leave the database restored while some files remain incomplete. A credential adapter failure can likewise leave the database and files restored while credentials still need attention. Keep the station stopped after any restore error, keep the encrypted backup available, and rerun after correcting the target path, storage, or credential issue. Database restore itself is transactional for PostgreSQL; SQLite replacement preserves the prior target file when one exists. Preserve the replacement station's existing data before starting because restored files and service credentials overwrite matching targets and are not committed as one cross-store transaction.

## Boundaries

The archive contains the state selected by the installed station integration. A deployment that has not wired a configuration file, media root, credential source, or portable credential adapter into `StationBackupService` will not silently discover it. Check the station's configured backup inventory before relying on it. A successful file verification proves archive integrity, not that PostgreSQL tools, target credentials, the service identity, storage capacity, or every external provider are ready on a replacement machine.
