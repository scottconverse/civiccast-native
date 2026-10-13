# Real SCM identity and startup check — PASS

Branch: `codex/station-operations-1-0`; base HEAD `431585942c9ced93e730b1e6b506c707a6adecb8`, dirty working tree. Run `identity-20261013-132213`, Windows Sandbox ID `5dd7b14a-ea35-40b8-aa0b-15593c767037`.

Actual `LocalSystem` service migrated through the production helper to `NT SERVICE\CivicCastSupervisor`. The running service process owner was independently queried as `NT SERVICE\CivicCastSupervisor`. Original and migrated station-state and fixture hashes matched. The portable vault retained the synthetic credential. Protected provisioning/upgrade directories remained protected and excluded the service SID.

The restricted service started actual packaged PostgreSQL 17.10 and served `/health` with `healthy`, `normal`, schema `current` at `0089_contribution_media_control_requests`, and live captions `disabled`. First-admin login through `/api/setup/login` succeeded. Its authenticated backup API created and verified an encrypted PostgreSQL archive. Inspection of that service-produced archive confirmed the migrated synthetic vault credential was present (boolean only; no plaintext credential logged).

Three genuine defects were reproduced and corrected by the parent: virtual-account `ChangeServiceConfig` required a NULL password; registry ACEs required CI inheritance to preserve readable PythonClass child registration; supervised installations needed backup binding before AI activation. Independent focused review found no additional issue in those three corrections. NULL matches the [official Windows API contract](https://learn.microsoft.com/en-us/windows/win32/api/winsvc/nf-winsvc-changeserviceconfigw); inherited service registry access remains read-only; backup authorization and maintenance lifecycle behavior remain enforced.

This used one 4096MiB guest at a time, with host runtime, PostgreSQL payload, source and scripts mapped read-only; only dedicated output was writable. Networking, GPU and clipboard were disabled. Earlier fixture failures are retained separately. The same initialized guest was reused after diagnosing the raw PowerShell pg_ctl pipe hang; corrected production registry granting was explicitly reapplied once to repair the empty PythonClass DACL left by the prior candidate. This is recovery and startup evidence, not a pristine initial installation or signed-installer proof.

Exact executed scripts are in `executed-scripts/`, configuration in `guest.wsb`. Execution used `WindowsSandbox.exe <configuration>` and `wsb.exe exec --id <above ID> --run-as ExistingLogin --command "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\CivicCastScripts\ContinueMigration.ps1" --raw`, followed by `ContinueApi.ps1`. Archive inspection used the installed Python under `--run-as System` with `InspectArchive.py` and file-backed output. The source bodies and retained diagnostic outputs document the focused correction/resume steps.

Archived Python script names have a `.txt` suffix to keep exact historical
source bytes separate from executable project code. Their contents and hashes
are unchanged; command paths above retain their actual names at execution.

Evidence:

- `guest-output/result.json`: successful migration, hashes, actual owner, health, backup verification, stopped service.
- `guest-output/archive-credential-and-source-proof.json`: credential boolean, archive SHA-256 and actual guest source hashes.
- `guest-output/migration-empty-password-failure.json`, `migration-registry-native.json`, `preactivation-backup-unavailable-failure.json`: original failures.
- `guest-output/partial-candidate-registry-repair.txt`: explicit prior-candidate repair.
- `guest-output/progress.log`, `supervisor.log`, `control_plane-app.log`: actual runtime history.
- `guest-output/stopped-guest-processes.json`: empty product/AI process list before shutdown.

Cleanup: service stopped successfully; no guest PostgreSQL/Python service/AI processes remained. `wsb.exe stop --id <above ID> --raw` closed the guest; `wsb.exe list --raw` returned `WindowsSandboxEnvironments: []`. Host `CivicCastSupervisor` remained RUNNING as LocalSystem with its existing installed binary path; no host service, registry, WSL or station-data changes were made.

Limits: installed beta.15 runtime plus current Python overlay; no rebuilt/signed installer, AI/model activation, downloads, load test, soak or station cutover. Guest source hashes were captured after successful execution; corrected app/helper hashes were also recorded immediately after staging.

proved: real SCM migration, restricted PostgreSQL/API startup, encrypted backup and migrated vault credential export verified; guest stopped and closed · lane: Critical.
