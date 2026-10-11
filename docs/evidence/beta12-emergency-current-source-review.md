# Beta12 emergency presentation: reviewed-source bindings

Date: 2026-10-09. This note renews the current-source review tripwires in
`native-decision-gate` and `session0-service-broadcast`. It does not renew the
July hardware observations or qualify current installed-service, Session 0,
boot/prelogin, hot-swap, crash-recovery, or multichannel operation.

The existing claim descriptions already distinguish their historical observations
from current-source review bindings. D2 remains enforced for every input. The
historical evidence documents, test node IDs, and controls remain unchanged.
`session0-service-before-logon` remains `stale` with `rebind: hardware_proof` in
the capability ledger. No historical result is transferred to Beta12.

## Reviewed delta and source identity

The four files last changed in `f44ca32808c51495eb88f50c471a7b895d12de5c`.
Review compared that change with the previously bound blobs. The delta adds the
emergency command parser and worker dispatch; an emergency-only compositor layer;
software/D3D11 memory conversion; output-canvas bounds; late-image running-time
alignment; crawl movement; and preservation of other layers during emergency
updates and graphics reload. The added existing-framework test sends commands
through the production worker pipe and inspects decoded MPEG-TS pixels.

Git blob IDs below identify portable source contents, including checkout newline
normalization. These are reviewed-source bindings, not the July spike inputs.

| File | Previous Git blob | Reviewed Git blob |
| --- | --- | --- |
| `civiccast/egress/gst/worker.py` | `f0ecae34d1bc1c1a6b9cb58610192c949e72fe15` | `e420d099f7126f9946713de26696737d0ce43048` |
| `civiccast/egress/gst/engine.py` | `6f42c4cee1b4a5d32e4cc13c3f123076fbcf1517` | `1c339902ad46909e9ca489442fecc885946facac` |
| `civiccast/egress/gst/control.py` | `af3e7ca70bb32952c37fee1391730483a5469b43` | `2cde47b2bf03fe14301ce86269424b1e3eeafcea` |
| `tests/egress/test_gst_engine_wsl.py` | `c02f25c5e31c21cae9767bdd8a6120e15eb8df0b` | `eeb9bb935f9adaf96fe5436b429aa1f1c1f384f0` |

## Existing actual runtime evidence

The retained local receipt is
`C:\Users\scott\Documents\Codex\2026-10-04\rea\outputs\beta12-emergency-presentation.txt`.
These are owner-workspace artifacts, **not committed repository files, CI
artifacts, or downloadable links**. Their absence from another checkout must not
be interpreted as a new successful execution. The existing receipt records:

```powershell
$env:CIVICCAST_GSTREAMER_RUNTIME_ROOT='C:\Program Files\CivicCast (Native)\runtime'
$env:PATH='C:\Program Files\CivicCast (Native)\packs\native-server-binaries\payload\bin;'+$env:PATH
.venv\Scripts\python -m pytest tests/egress/test_gst_engine_wsl.py -k emergency_late_image -q
```

Result: **2 passed, 31 deselected in 11.86s**, one software compositor case and
one D3D11 compositor case. Synthetic sources and isolated filesinks exercised the
production engine and Windows worker pipe using the installed GStreamer/FFmpeg
runtime. Decoded frames showed the emergency panel, then its removal with the
station logo retained. The receipt also retains CPU crawl and forced-slate clips.
No live feed, host service, station setting, or prelogin session was exercised.

Artifacts are under the same workspace's `outputs\eas-pixels\` directory.
SHA-256 values identify the retained bytes checked for this renewal:

| Artifact | SHA-256 |
| --- | --- |
| `cpu-worker-displayed.png` | `485bb6b36c04c649c904be3bbafb1e1ca00bd60306f333a1b5d02e3db5d10125` |
| `cpu-worker-cleared.png` | `f60c60f6fdbe0c7fbf9b52e81faa638d47ead6b3716d4482e25f17606946ab62` |
| `d3d11-worker-displayed.png` | `3a9767db47e5c82a31a5e908c8e9c49777c193a6045199614b6fa4f5441f63a8` |
| `d3d11-worker-cleared.png` | `c78c25b8e69f1651a91c1974b932cf6c85bebd482eb413cc3dcf33af0e542a36` |
| `cpu-worker-full.ts` | `0137b3b62a8219c9205321f7e1f427ba3d4c2a84eb01242b5706d1523165c56b` |
| `d3d11-worker-full.ts` | `491179e1650deb7cf82078f4ed95bfe057be8bcfaa5cd035f508769510adf46b` |
| `crawl.ts` | `665a09d8aa1118a1d91e3f3e3dc73d36c9950a2255bc8bdb0c6be024e40243f6` |
| `forced_slate.ts` | `0c45516b991d0df027891ccc54d4c37593b7ac717d633edb47a10abc60087953` |

The four current local source SHA-256 values match the original runtime receipt:
worker `ee1310e246e4fcc6b74707f3cb88177f0d94f9969daae5c87b912126fa6c7803`,
engine `120bc1bd79f90dc7f5be800a9237cc31730bcdce2fd4daefc03b1c43531fbebe`,
control `3f033e732886b4b430652710502c8d37753192f4d08bb2bd9df21a5f84bb2013`,
test `cf3629dcc1aadc8147f377d4c8868fcd0e76e1b4ca5b2ec3e3d4d36b6fba2c4d`.
Later retention/order changes were confined to presentation/strategy tests and
helpers, outside these four bindings. They have separate receipts; this renewal
does not turn their isolated failure tests into new hardware proof.

The pixel test was not independently sensitive specifically to removal of the
late-image offset: a recorded temporary offset-zero run passed. Its demonstrated
claim is the resulting pixels, clearing, and logo preservation, not sensitivity
to every individual implementation detail. No test or verifier assertion is
weakened by this renewal; future changes to any bound input still trigger D2.

## Subsequent workflow binding renewal

The independent CI-fixture review also found that raising the native-suite
floors changes the bound `.github/workflows/ci-test.yml` input for all six
registered claims. The previous Git blob was
`ed5cd2f49ad8890e113f7bdc4901dd8b094e907e`; the reviewed workflow blob is
`9997e7bef02d51459acc9fa3e485f91c03792042` (local SHA-256
`9f6af131dc271ff355f9c52b992f80c5d2723548e11ea850ac53e0963b285016`).

A parsed YAML comparison against HEAD found exactly two runtime changes:
`--floor 1888` becomes `--floor 1909`, and `--floor 2096` becomes `--floor 2115`.
Other textual changes are explanatory collection-date/count comments. Test
selection, jobs, producer commands, permissions, artifact routing, and controls
are unchanged. The existing 50-test margin is unchanged; floors increase.

The independent existing-framework check was:

```powershell
.venv\Scripts\python.exe -m pytest tests/cg/test_cg_router.py tests/installer/test_installer_api.py::test_cg_public_api_exposes_idle_and_requires_a_real_emergency_overlay tests/egress/test_takeover_readiness_gate.py tests/live/test_app_takeover_live_source_wiring.py tests/test_release_notes_body_bound.py tests/policy/test_native_caption_workflow_policy.py::test_native_marker_collections_match_the_workflow_floors tests/policy/test_native_caption_workflow_policy.py::test_native_junit_workflow_floors_match_current_exact_collections tests/egress/test_takeover_service.py -q
```

Result: **50 passed in 37.48s**, with inherited `CIVICCAST_STAFF_TOKENS` removed
only in the child shell. The two existing collection-policy checks actually
collect the native tests: the exact pure/total assertion is 1959/2168; the other
check freshly collects the workflow's Windows `not integration` selection and
enforces the existing maximum margin. The worker's fresh Windows nonintegration
collection was 2165. This review also confirmed the unchanged selectors and
unknown/disabled-channel no-audit/no-enqueue tests; no hardware tests were run by
collecting them. Local receipt:
`C:\Users\scott\Documents\Codex\2026-10-04\rea\outputs\beta12-ci-fixture-review.txt`.

Renewing the six workflow role hashes records only this reviewed workflow delta.
It does not supply new backup/restore, release-producer, or hardware acceptance
evidence. Existing claim definitions, historical proof references, controls,
node IDs, tests, and verifier remain intact.

## Follow-up floor renewal for the added native cases

Randomized CI run `38017271224` on `f93beca07afc5605fb6c70a27fa16ac15d936210`
collected 1,968 platform-independent native tests and 2,179 total native tests.
A fresh local collection reproduced 1,968 with `-m "not windows_only"`, 2,179
without a marker, and 2,176 with `-m "not integration"` (the Windows CI
selection). The two existing policy checks failed against the stale 1,957/2,168
exact assertion and the old 1,909 pure floor; the old Windows floor 2,115 was
61 below its executed collection.

The current-source correction pins the exact pure/total counts to 1,968/2,179
and sets floors to 1,918/2,126, preserving the existing 50-test margin for
both actual CI selections. The workflow comparison against the preceding
reviewed version contains only those two floor increases and explanatory
comments; jobs, selectors, permissions, commands, artifact paths, and claim
controls are unchanged. The updated workflow blob is
`60d1bc177bdb96b55649c282e2fb250061b68920`; all six existing workflow-role
bindings in `docs/claims/claims.yaml` point to that exact blob. No historical
evidence, controls, or acceptance claims were changed.

The two existing policy tests were rerun after the correction and passed
(`2 passed in 21.67s`). Raw RED and GREEN output is retained at
`C:\Users\scott\Documents\Codex\2026-10-04\rea\outputs\beta12-native-count-policy-red.txt`
and `C:\Users\scott\Documents\Codex\2026-10-04\rea\outputs\beta12-native-count-policy-green.txt`.
