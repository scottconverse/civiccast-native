# Beta 11 independent package and upgrade-path review

**Reviewer scope:** read-only review of pinned Whistle asset provisioning, station/app pack contracts, activation, the hosted preparation route, and release acquisition for existing installations. No station, installer, native build, or Rust tests were run by this review.

## Prior source-to-installed binding

The prior dev7 source-to-installed tap difference was investigated independently. The staged candidate and actual installed `tap_worker.py` had the same SHA-256, `876e33c4a9ec972f28b5563e5914e673eb69cd4830e362c46ae9316d5b24a2a8` (143,440 bytes). Compared with repository source at the tested caption commit, the additional change was U69 diagnostics instrumentation; no caption processing, queue, retention, lock, or shedding-decision changes were identified. The root recorded the hashes and diff in `runtime-binding.json` and `source-to-installed-tap.json`; package from repository source and retain the instrumentation qualification.

## Packaging and prepare-only review

Source inspection found the model and engine pinned by byte count and SHA-256; the pack builder/verifier and Rust verifier require exact metadata and the exact two-file payload. `captions-whistle` is required by the native distribution and activation contracts, stages at `packs/captions-whistle`, and both files are part of required activation layout. The app payload verifier also requires the pinned DLL at its canonical `needle` package path. I found no blocking defect in these source paths. Rust compilation/tests remain unverified on this host under the active-soak constraint.

The hosted `prepare_only` path remains hosted-only even if self-hosted is selected; it skips kit assembly and full station-bundle upload. Before uploading its Gate A skip marker, it requires the Whistle pack, signed-index file, checksum file, and build report, then compares the Whistle bytes/hash across the required index entry, checksums, and report. Gate A associates the marker with the candidate run SHA. The activation gate was not weakened.

Focused commands run independently:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/native/test_build_native_station_bundle.py tests/installer/test_native_packs.py tests/native/test_whistle_asset_provisioning.py tests/native/test_app_payload_builder.py tests/native/test_station_runtime.py -q
```

```text
........................................................................ [ 33%]
........................................................................ [ 66%]
........................................................................ [100%]
216 passed in 5.98s
```

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/policy/test_native_beta_candidate_workflow.py::test_prepare_only_preserves_signed_candidate_and_small_station_evidence tests/policy/test_native_beta_candidate_workflow.py::test_prepare_only_artifact_is_the_gate_a_skip_marker tests/policy/test_native_beta_candidate_workflow.py::test_native_beta_candidate_workflow_contract_rejects_unconditional_self_hosted_runner tests/gate_a/test_gate_a_harness_contract.py::test_gate_a_skips_prepare_only_workflow_runs_before_sandbox
```

```text
....                                                                     [100%]
4 passed in 1.45s
```

```powershell
actionlint .github/workflows/native-beta-candidate-artifacts.yml .github/workflows/gate-a-station-acceptance.yml
```

Exit code 0, no output. `git diff --check` exited 0; Git printed only working-copy CRLF normalization advisories.

## Original release blocker: setup-only beta.10 upgrade could not acquire Whistle

At initial review, the new pack was built into the station bundle, but the public beta release helper uploaded only `setup.exe` and the kit's top-level `packs/*.ccpack`; it deliberately excludes the large `station/` bundle. The initial Beta 11 setup path embedded `station-index.json` and `core.ccpack` only. The NSIS postinstall hook chooses the USB kit's `$EXEDIR\station\station-index.json` when present, otherwise the embedded `$INSTDIR\station\station-index.json`, then activates from that index.

The station-index acquisition path does not fetch missing packs online: `validate_urls` rejects nonempty URLs for `station-index`, and `copy_station_pack_to_cache` resolves missing sidecar files only from the exact per-SHA cache. A beta.10 installation can have the old floor/Ollama packs cached but cannot have the newly introduced Whistle hash cached. Therefore a beta.10-to-beta.11 setup-only upgrade fails mandatory station acquisition unless the Whistle pack is made available to that path. At that point, the prepared Whistle artifact was only a temporary Actions artifact, not a public release asset.

The original blocker is resolved at source level by the embedded-resource fix reviewed below. End-to-end installer construction and activation remain unverified pending the remote build; source inspection alone is not runtime proof.


## Re-review after embedding the Whistle pack

The setup-only upgrade path now has the required local input. `tauri.native.conf.json` maps `resources/station/captions-whistle.ccpack` to `$INSTDIR\station\captions-whistle.ccpack`. The candidate workflow copies the exact station-bundle Whistle pack into the small `native-station-embed-<sha>` artifact, downloads it to the Tauri build job, and stages it beside the index/core resources. `build_native_bootstrap.py` requires the resource, caps it below 25,000,000 bytes, and checks that the single `captions-whistle` index entry is required, URL-free, and byte/hash-identical. NSIS already falls back to the embedded `$INSTDIR\station\station-index.json` when no USB-kit `$EXEDIR\station` exists; its import then sees the embedded Whistle file. `acquire_station_distribution` obtains each named pack from the station media folder when present and otherwise from its exact per-SHA cache. Thus Whistle comes from the embedded sidecar and old floor/Ollama packs continue from the beta.10 cache. The full large model pack remains off the public release and out of setup.exe.

The focused suite now includes bootstrap resource identity/size/tamper cases and the updated resource allowlist:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/native/test_build_native_station_bundle.py tests/installer/test_native_packs.py tests/native/test_whistle_asset_provisioning.py tests/native/test_app_payload_builder.py tests/native/test_station_runtime.py tests/native/test_native_bootstrap_builder.py tests/policy/test_native_beta_candidate_workflow.py tests/policy/test_native_installer_identity.py -q
```

```text
........................................................................ [ 18%]
........................................................................ [ 37%]
........................................................................ [ 56%]
........................................................................ [ 75%]
........................................................................ [ 93%]
........................                                                 [100%]
384 passed in 10.13s
```

`actionlint .github/workflows/native-beta-candidate-artifacts.yml .github/workflows/gate-a-station-acceptance.yml` exited 0 with no output. `git diff --check` exited 0; only CRLF normalization advisories were printed. No Rust cargo check/test, installer build, installation, ASR run, or station modification was performed on this host. The source-level acquisition path is coherent; remote build and install evidence must still establish the actual setup embeds and activates these resources.

## Manual artifact and generated-help review

The three tracked release-manual files are restored to the exact PR base `8c3ab70bdc802f42ee573d83b284418c620c18ae`: PDF blob `6747fd54cb31e1aaba395f37da1f7f4c959e2e4d`, DOCX blob `01d7b4fa655134ae266f414b0858b3f680ab3175`, and render-manifest blob `0aa9f19a3106447b37a2c34dff33fbc9f7e32f3c`. Their public relative links continue to serve the historical Beta 10 baseline during preparation. The tracked-manual regression test pins the page-2 PDF header to Beta 10 and verifies manifest hashes/sizes against both tracked files, independent of the release-truth current tag. The candidate verification note records that public links switch to Beta 11 release assets at publication.

The regenerated Beta 11 PDF and DOCX were preserved at `artifacts/release-preparation/manual/` with a staged manifest tied to current manual-source SHA `b22a21ec4868d5e5cf3a332948f291ae23e00abbce5e49a97bad368a0a96cc5a`; PDF SHA-256 `d59db635a4dbf02d905e22e1c6f9cdff665422c14e7ff4bbf3880d6ed3b6ce2f` (7,150,472 bytes), DOCX SHA-256 `ffda0baacbc524d78b78b7a3014731aa112c497408ae6a07ed7439d56d33796f` (5,586,405 bytes). The staged render passed `render_user_manual.py --check-current`. CI renders to this ignored staging directory; `verify-release.sh` consumes downloaded hosted files, validates the exact-candidate receipt against source/version/workflow-run identity, then checks the PDF/DOCX manifest and page-2 header. The hosted receipt was not present in local staging during this review, so exact hosted-run validation remains pending.

The in-product manual image optimization was reviewed: raster images use WebP quality 85 with source dimensions checked after encoding; alpha is retained and animated GIF/SVG inputs keep original formats. The generated artifact retains 635 TOC entries and 29 images under the 5 MiB source-blob limit. The public-copy exception removes only the exact canonical non-affiliation notice; unrelated vendor mentions and high-risk competitive claims remain checked. The OpenAPI artifact version matches Beta 11.

Focused checks: `tests/test_user_manual_render.py` passed 11 tests in 106.67 seconds before its final baseline-version assertion adjustment; the adjusted historical-baseline test then passed independently (1 test, 1.41 seconds). `tests/docsite/test_render.py` passed 20 tests; `tests/policy/test_public_copy_legal.py` passed 13 tests; the standalone public-copy policy, docsite currentness check, OpenAPI artifact check, targeted Beta 11 missing-manual publisher case, Ruff, actionlint, shell syntax checks, and `git diff --check` passed. The full manual-render suite includes one fresh Beta 11 PDF render. No native build, station installation/restart, or ASR run was performed for this documentation review.
