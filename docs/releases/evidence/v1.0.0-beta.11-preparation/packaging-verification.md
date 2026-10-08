# Beta 11 packaging verification receipt

**Scope:** pinned Whistle asset provisioning, station/app payload contracts, activation paths, and Beta 11 source identity. This is source preparation evidence; no candidate installer or station bundle was built or signed on this host.

## Packaging gap and resulting contract

The source already contained the Whistle runtime, but the native package path did not provision its local model and engine, require a signed Whistle component pack, or stage the pair at the runtime's canonical paths. The package now requires these exact assets:

| Asset | Authoritative source | Size | SHA-256 | Runtime/package path |
|---|---|---:|---|---|
| Whistle model | <https://huggingface.co/Cactus-Compute/whistle/resolve/main/whistle.cact> | 16,919,407 bytes | `b6e02f048568ac5d01a2042556c658061e699acbc0aa2a1439f52f3d461dffeb` | `packs/captions-whistle/whistle.cact` |
| `cactus-needle` Windows wheel, version 3.1.0 | <https://huggingface.co/Cactus-Compute/needle3/resolve/main/python/cactus_needle-3.1.0-py3-none-win_amd64.whl> | 683,889 bytes | `4f5fc86abfc50d551cdb237a34b501f36d82d4b6f5911ee7bec4e9532d44dd95` | Build input; Apache-2.0 |
| DLL member `needle/libneedle3.dll` | Extracted only from that hash-pinned wheel | 1,502,720 bytes | `de2e2c39cd311fbd9971fad4736abc329ed970653674c203e149c4ef27fd1c62` | Station pack: `packs/captions-whistle/libneedle.dll`; app payload: `Lib/site-packages/needle/libneedle3.dll` |

The model and engine are Apache-2.0. Provisioning verifies wheel/model size and hash, extracts only the exact DLL member, and caps streamed downloads at one byte over the pinned size before failing. The signed pack contract requires exactly `whistle.cact` and `libneedle.dll`, binds both pins and source/license metadata, and rejects substitutions. The Whistle component is mandatory in station distribution and activation; its extracted root is `packs/captions-whistle`. Ollama composition remains limited to its three explicit model components.

The signed pack path is `artifacts/native-station-bundle/station/captions-whistle.ccpack`. Its raw payload totals 18,422,127 bytes; final `.ccpack` size is not known because the station bundle was not produced on this host.

## Focused verification commands and raw summaries

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/native/test_build_native_station_bundle.py tests/installer/test_native_packs.py tests/native/test_whistle_asset_provisioning.py tests/native/test_app_payload_builder.py tests/native/test_station_runtime.py -q
```

Raw summary:

```text
........................................................................ [ 33%]
........................................................................ [ 66%]
........................................................................ [100%]
216 passed in 6.25s
```

Release identity tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/policy/test_release_identity.py -q
```

```text
..........                                                               [100%]
10 passed in 1.48s
```

Identity checker:

```powershell
.\.venv\Scripts\python.exe scripts/policy/check_release_identity.py
```

```text
check_release_identity: PASS - release identity is aligned for v1.0.0-beta.11.
```

Whitespace check:

```powershell
git diff --check
```

Exit code was 0. Git printed CRLF-to-LF advisory notices for working-copy files; it reported no whitespace errors.

The initial same-size DLL digest test used a shorter tampered fixture and correctly stopped at the earlier size check. The fixture was changed to equal length so the regression assertion reaches the SHA-256 branch; the focused suite above is the final result.

## Rust check limitation

The formatter command was:

```powershell
cargo fmt --check --manifest-path civiccast/apps/installer/src-tauri/Cargo.toml
```

It exited 1 with extensive formatting diffs across the installer crate, including unchanged files such as `acquisition_catalog.rs` and `native_uninstall.rs`, plus pre-existing formatting in nearby installer modules. The output was truncated by the tool (2,929 reported lines). No broad reformat was applied. Rust tests and builds were not run because the coordinator kept compilation off the active soak host to preserve the owner-requested station run; this receipt therefore does not claim Rust compile/test proof. Rust tests were added for the pinned Whistle contract, the required Whistle component, and activation path, but remain unexecuted here.

## Five-lens self-audit

1. **Correctness and supply-chain integrity  -  pass after one fix.** Exact official URLs, sizes, SHA-256 pins, two-file pack inventory, wheel-member identity, and installed package DLL identity are checked at provisioning/verification boundaries. The first review found unbounded response streaming; reads are now capped at `expected_bytes + 1`, with a focused test proving early refusal and partial-file cleanup.
2. **Runtime and activation  -  pass by source/test evidence.** Whistle is appended to required distribution/activation lists; its root and two required files match the Python runtime contract. Ollama-store composition uses an explicit three-model list, so Whistle does not enter that path. Rust execution remains unverified as stated above.
3. **Build and operational handling  -  pass by source inspection.** The workflow provisions into a build-owned temporary root, passes it to the station bundle builder, then removes only that root/cache after pack creation. The output stays in the flat `station/` directory used by the side-load package path. The workflow job itself was not executed here.
4. **Docs and release truth  -  pass.** Source, native, Tauri, Cargo, package, app version, operator smoke expectation, API reference, and health example now identify `1.0.0-beta.11`. README and docs index identify it as an **owner-held unpublished candidate**; beta.10 remains identified as the latest published release. The release identity checker passes.
5. **Tests and scope  -  pass with stated runtime limit.** Python packaging/activation tests and release identity tests pass. No telemetry schema/event contract was changed; runtime changes add only the required Whistle asset root to the existing runtime contract. No installed `C:\Program Files\CivicCast` or ProgramData runtime, live station, service, or monitor was touched; no candidate build, publication, tag, push, or stop action occurred.
