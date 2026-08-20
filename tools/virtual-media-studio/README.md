# CivicCast Virtual Media Studio

The Virtual Media Studio is the reusable local lab used to finish CivicCast
3.2. It is intentionally kept under `tools/virtual-media-studio` so the code can
later be lifted into a standalone project without untangling product modules.

The lab has three layers:

- Core runner and schemas in `vstudio/`.
- Profile packs in `vstudio/profile_packs/`.
- Device plugin manifests. In the current slice they are embedded in the LPM
  profile pack; later stages will extract concrete plugin modules.

For 3.2, the first profile pack is `lpm`, which wraps the existing
`civiccast.control_room.lpm_lab*` contract harness. It now includes
deterministic scenarios, API fixtures, state simulators, OBS/vMix/NDI software
probe commands, and the Stage 8 reusable bundle writer. Future work should add
more profile packs, concrete device plugin modules, richer sample-media
workflows, and broader product UI workflows around this same runner contract.

## Local Commands

```powershell
uv run python tools/virtual-media-studio/civiccast-vstudio.py profiles list
uv run python tools/virtual-media-studio/civiccast-vstudio.py packs list
uv run python tools/virtual-media-studio/civiccast-vstudio.py devices list --profile lpm-fixed-studio
uv run python tools/virtual-media-studio/civiccast-vstudio.py plugins list
uv run python tools/virtual-media-studio/civiccast-vstudio.py scenarios list
uv run python tools/virtual-media-studio/civiccast-vstudio.py run --profile lpm-fixed-studio --scenario smoke
uv run python tools/virtual-media-studio/civiccast-vstudio.py run --profile all --scenario soak --artifact-root artifacts/vstudio/soak-plan
uv run python tools/virtual-media-studio/civiccast-vstudio.py run --profile all --scenario release --artifact-root artifacts/vstudio/release-hardening
uv run python tools/virtual-media-studio/civiccast-vstudio.py bundle write --artifact-root artifacts/vstudio/bundle --force-clean
uv run python tools/virtual-media-studio/civiccast-vstudio.py probe obs --artifact-root artifacts/vstudio/probes/obs
uv run python tools/virtual-media-studio/civiccast-vstudio.py probe vmix --artifact-root artifacts/vstudio/probes/vmix
uv run python tools/virtual-media-studio/civiccast-vstudio.py probe ndi --artifact-root artifacts/vstudio/probes/ndi
uv run python tools/virtual-media-studio/civiccast-vstudio.py probe all --artifact-root artifacts/vstudio/probes/all --force-clean
uv run python scripts/run_lpm_contract_lab_wall_clock_soak.py --duration-seconds 14400 --interval-seconds 300 --profile all --probe-real-software --require-software-lab --artifact-root artifacts/wall-clock-soak/3.2-4h
```

The `soak` scenario currently writes a soak-plan rehearsal artifact. It does not
run a real elapsed 12-hour soak. Use
`scripts/run_lpm_contract_lab_wall_clock_soak.py` when elapsed endurance evidence
is required.

## Scenario Semantics

| Scenario | Stage | Meaning | Dependencies |
|---|---|---|---|
| `smoke` | catalog | Profile and check-catalog rehearsal for selected virtual profiles. | Project Python environment. |
| `walkthrough` | stage45 | Local API fixtures and deterministic state simulators. | Project Python environment. |
| `software` | stage45 | Local OBS/vMix hard gate plus required software probes. | OBS/vMix loopback endpoints and NDI runtime/tool artifacts. |
| `chaos` | stage67 | Deterministic local fault/recovery rehearsal. | Project Python environment; optional local software probes. |
| `soak` | stage67 | Twelve-hour plan rehearsal artifact, not elapsed wall-clock soak. | Project Python environment; optional local software probes. |
| `release` | stage8 | Local release-hardening package plus reusable lab bundle. | Project Python environment; OBS/vMix if real software proof is required. |

These scenarios do not prove a clean Windows install, approve a release, or touch
station devices.

The generic runner delegates scenario execution to the selected profile pack.
The bundled `lpm` pack delegates to the checked CivicCast harness and preserves
the existing `scripts/run_lpm_contract_lab.py` entrypoint for backwards
compatibility. Additional profile packs should implement the same pack protocol
instead of editing the generic runner.

## Reusable Bundle

`bundle write` exports the profile-pack, plugin, scenario, and extension-contract
manifest into a marked artifact root. The bundle is intentionally shaped so the
Virtual Media Studio can later be split into its own repository without changing
the public profile/plugin/scenario contracts.

The bundle is local lab software. It is not a CivicCast release artifact, does
not run an elapsed wall-clock soak, and does not claim station-device evidence.

Use `uv run python` from the CivicCast checkout so the CLI sees the pinned
project dependencies. If the command is run through a system Python that is
missing those dependencies, the CLI exits with a structured dependency error
instead of a traceback.

## Real Software Probe Prerequisites

The probe commands use local loopback endpoints and local installation paths.

For OBS, install OBS Studio with obs-websocket 5.x enabled on `127.0.0.1:4455`.
If OBS requires authentication, set `CIVICAST_OBS_WEBSOCKET_PASSWORD` for the
probe. The local CI runner starts its isolated OBS lab with authentication
required and passes the password through that environment variable without
printing it.

For vMix, enable the vMix web controller/API so `http://127.0.0.1:8088/api/`
returns status XML. The probe verifies both the parsed XML and the listener
process identity before it reports a pass. If the listener is not
network-confined, the artifact records that posture and does not claim secure
listener configuration.

For NDI, the software probe checks known local NDI runtime/tool artifacts,
including NDI files bundled with vMix. It does not discover NDI sources or touch
station devices. Missing NDI is a failed probe when a scenario names NDI as a
required local software target.

`--force-clean` only replaces marked artifact roots under the repo `artifacts`
directory or the system temp directory. Do not point it at shared evidence or
working directories.
