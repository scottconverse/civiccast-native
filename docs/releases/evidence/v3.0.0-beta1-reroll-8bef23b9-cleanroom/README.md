# v3.0.0-beta1 reroll 8bef23b9 clean-room evidence

Date: 2026-06-22

This evidence covers the release-artifact reroll built from `main` commit
`8bef23b9` after the public-beta GauntletGate corrections.

## Rebuilt artifacts

Command:

```powershell
uv run --python 3.12 python scripts/build_release_artifacts.py --version 3.0.0-beta1 --out-dir artifacts/release/v3.0.0-beta1-reroll-8bef23b9 --all-portable --python --wheelhouse --windows-installer
```

Result: passed.

Artifact root:

`artifacts/release/v3.0.0-beta1-reroll-8bef23b9`

Key artifact hashes:

| Artifact | SHA-256 | Size |
| --- | --- | ---: |
| `civiccast-3.0.0-beta1-windows-setup.exe` | `d5591abfc1136a5183b6e7c3d1b2366da922eb2080580c35a351756dfd944cd1` | 174378322 |
| `civiccast-3.0.0-beta1-windows-tester-package.zip` | `260f7b1f78e5ec457764a37ae58428d7da0498527d8edb82929d1dada322945a` | 346398926 |
| `civiccast-3.0.0-beta1-clean-windows-proof-kit.zip` | `1c82447e179529ba11f85c0f7e59f5534de37e1dc9b13da75baa234e0514874b` | 174415371 |
| `civiccast-3.0.0-beta1-release-artifacts-manifest.json` | `a16320f001e2233fd72614a4b4fa40d3c9b7d0122ab70205ee5dfc60ffbe0763` | 23116 |
| `civiccast-3.0.0b1-py3-none-any.whl` | `d01e717ffdfac534deaf7c1159fabd0894cb92245c0173efa7657a104faf0813` | 2491425 |
| `WHEELHOUSE-MANIFEST.json` | `7e2bfae952d9ada8b42978b16f51a5b584274c196a8bf360ebb2bcf16b23d846` | 15626 |

## WSL2 fresh-user package proof

Command:

```powershell
uv run --python 3.12 python scripts/run_clean_windows_install_proof.py --execute --evidence-dir docs/releases/evidence/v3.0.0-beta1-reroll-8bef23b9-cleanroom --release-manifest artifacts/release/v3.0.0-beta1-reroll-8bef23b9/civiccast-3.0.0-beta1-release-artifacts-manifest.json
```

Result: partial.

- `wsl2-fresh-user`: passed. A disposable Ubuntu 24.04 venv installed
  `civiccast-3.0.0b1-py3-none-any.whl[captions-runtime]` offline from the
  reroll wheelhouse and imported CivicCast as `3.0.0-beta1`.
- `wsl2-fresh-distro`: available.
- `hyper-v-vm`: blocked because `Get-VM` is unavailable on this host.
- `windows-sandbox`: blocked by elevation/feature availability.

Detailed machine-readable and Markdown evidence:

- `clean-windows-install.json`
- `clean-windows-install.md`

## Docker clean-room full gate

Commands:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\prepare_cleanroom_environment.ps1 -BuildDockerImage -KeepRepoNodeProcesses
docker run --rm -v "C:\CivicCastTester\v3-beta-release-prep:/work/civiccast:ro" -v /var/run/docker.sock:/var/run/docker.sock --add-host=host.docker.internal:host-gateway civiccast-cleanroom:latest
```

Result: passed after fixing the network-gated VDO.Ninja pin test so it runs
`git ls-remote` from a neutral temporary directory and catches
`subprocess.TimeoutExpired`.

The clean-room run passed:

- ruff check
- ruff format check
- mypy
- full pytest suite: `4298 passed, 19 skipped`
- first-run installer proof commands
- real packager end-to-end HLS encode
- public portal clean `npm ci`, production build, and accessibility tests:
  `27 passed`
- encoded asset playback in headless Chromium: `2 passed`
- synthetic RTMP live source to HLS to portal playback: `2 passed`
- real PostgreSQL schedule contract through testcontainers: `19 passed`

## Native Windows installer execution

Status: blocked at the local VirtualBox WSL2 virtualization boundary, not passed.

The host has Oracle VirtualBox and existing Windows 11 clean-room VMs. The reroll
proof kit was staged to:

`C:\Dev\Claude\vm-share\civiccast-cleanwin-v2\civiccast-3.0.0-beta1-reroll-8bef23b9-clean-windows-proof-kit.zip`

The staged proof kit hash matched
`1c82447e179529ba11f85c0f7e59f5534de37e1dc9b13da75baa234e0514874b`.

The candidate VM `civiccast-v3-r6-cleanwin` was running Windows 11 Enterprise
Evaluation with the `tester` user logged in and Guest Additions reported
installed. Screenshot evidence was captured to host-local files under
`C:\CivicCastTester\`, but the VM could not be automated:

- `VBoxManage guestcontrol ... run ... whoami` repeatedly failed with
  `Error starting guest session (current status is: starting)`.
- `VBoxManage controlvm ... keyboardputstring` failed at the scancode layer.
- SSH forwarding on host port `2223` accepted a TCP connection but timed out
  during SSH banner exchange.

No host reboot, VM reboot, VM reset, or VM power-cycle was performed.

Follow-up on 2026-06-23 used the clean snapshot
`civiccast-cleanwin-v2` / `clean-windows-base-20260602`. This VM did accept
automation:

- Restored clean Windows 11 Enterprise Evaluation snapshot.
- Verified Guest Additions guest-control access as `civiccast-clean\tester`.
- Installed `civiccast-3.0.0-beta1-windows-setup.exe`.
- Launched the installed `civiccast-installer.exe`.
- Approved the Windows helper UAC prompt.
- Rebooted/reset only the disposable VM after the guest hung on restart.
- Reopened the installer and approved the WSL updater UAC prompt.
- Confirmed WSL `2.7.8` installed.

The run then blocked when the installer tried to install `Ubuntu-24.04` for
the Windows user. The app-reported blocker was:

> Windows installed part of the helper, but this computer has a required Windows
> setting turned off.

The guest bootstrap log confirms the root cause:

```text
WSL2 is unable to start since virtualization is not enabled on this machine.
Error code: Wsl/InstallDistro/Service/RegisterDistro/CreateVm/HCS/HCS_E_HYPERV_NOT_INSTALLED
```

VirtualBox is already configured with nested hardware virtualization enabled for
this VM, but the host-side VirtualBox log shows:

```text
NestedHWVirt = 1
HM: HMR3Init: Attempting fall back to NEM: AMD-V is not available
NEM: WHvCapabilityCodeHypervisorPresent is TRUE
```

That means this local VirtualBox clean room cannot prove the full WSL2
installer path while VirtualBox is running through the Windows Hypervisor
Platform fallback. The rerolled installer proof is therefore complete through
native EXE install, app launch, UAC handoff, WSL core/update setup, and correct
blocked-state reporting, but it is not a full clean Windows beta proof because
the VM cannot run the Ubuntu 24.04 WSL2 distro.

Additional raw evidence:

- `virtualbox-clean-windows-app-logs.txt`

## Host WSL2 installer proof

Status: passed as a host WSL2-capable installer proof, not as an isolated clean
Windows machine proof.

After the local VirtualBox clean-room boundary above, the rerolled Windows
installer was exercised on the release-owner Windows host with host WSL2 Ubuntu
24.04 available. Existing per-user CivicCast app data was backed up, local
CivicCast app data was cleared, CivicCast WSL state was removed, and the
rerolled installer artifact was installed and launched without rebooting the
host.

Proof root:

`docs/releases/evidence/v3.0.0-beta1-reroll-8bef23b9-cleanroom/host-wsl2-installer-proof-20260623`

Result:

- Silent installer process exited `0`.
- Installed app registered as `CivicCast Installer` version `3.0.0-beta1`.
- Installed executable hash:
  `8153d3ddddf20289636e531a1486cc0afb38a47e3510b213e5b17d93dae36ba5`.
- Installer state reached `runtime` / `ready`.
- Installer state reported `reboot_required=false`.
- Windows host health returned
  `{"status":"healthy","version":"3.0.0-beta1","schema":"current"}`.
- WSL Ubuntu 24.04 health returned the same healthy response.
- Operator console was served from the packaged API and showed the
  `v3.0.0-beta1` first setup screen with durable storage ready.
- First-admin setup completed through the installed runtime API.
- Recovery kit generation returned 8 recovery codes; the committed evidence
  redacts those code values and the staff token.
- Recovery-kit acknowledgement recorded
  `recovery_kit_acknowledged=true`.
- Post-setup operator console showed setup complete and sign-in/recovery flow.
- Resident portal was served and showed CivicCast ready.

Evidence files:

- `setup.json`
- `install-process.json`
- `launch.json`
- `station-state-before-first-admin.json`
- `first-admin-response-redacted.json`
- `staff-station-state-after-first-admin.json`
- `recovery-kit-acknowledge.json`
- `operator-console.png`
- `operator-console-after-first-admin.png`
- `resident-portal.png`
- `final-runtime-snapshot.json`

This closes the "rebuilt installer launches and reaches a working WSL2 runtime"
proof on this host. It does not erase the remaining clean-room limitation:
VirtualBox on this machine cannot run nested WSL2 Ubuntu because AMD-V is not
available to the guest while VirtualBox is using the Windows Hypervisor Platform
fallback. A final isolated clean Windows proof still requires a clean Windows
environment that can actually start WSL2 Ubuntu 24.04.
