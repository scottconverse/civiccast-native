# Bundled GStreamer Runtime Proof - 2026-06-24

This note records the corrective proof for the cleanroom installer failure where
stock Ubuntu 24.04 packages did not provide the native caption-SEI elements
`h264ccinserter` and `tttocea608`.

## Runtime Artifact

- Artifact: `gstreamer-runtime-linux-x86_64.tar.gz`
- SHA-256: `1b89a2712d29bfd27cb1c5679d0ab4e423d7f5d86c3f08661aa650d359c579e3`
- Runtime path after installer extraction: `/opt/civiccast/gstreamer`
- GStreamer version: `1.28.4`
- Build recipe: `scripts/build_gstreamer_runtime_container.sh`
- Clean extraction proof: `scripts/prove_gstreamer_runtime_container.sh`
- Clean extraction proof log:
  `docs/releases/evidence/v3.0.0-beta1-reroll-8bef23b9-cleanroom/bundled-gstreamer-runtime-proof-20260624.log`
- Runtime provenance:
  `docs/releases/evidence/v3.0.0-beta1-reroll-8bef23b9-cleanroom/bundled-gstreamer-runtime-provenance-20260624.json`

## Clean Dependency Substrate Proof

The runtime was extracted and verified in a fresh Ubuntu 24.04 container with
only the required native runtime libraries, Python GI bindings, FFmpeg, and tar
installed from Ubuntu 24.04 repositories. No Plucky repository and no
non-release Ubuntu package source were used.

Verified private-runtime elements:

- `cccombiner`
- `ccconverter`
- `h264ccinserter`
- `tttocea608`
- `openh264enc`
- `mpegtsmux`

Verified Python GI visibility:

- `python-gst GStreamer 1.28.4`
- `python-elements-ok`

The captured Docker proof exited with `DOCKER_EXIT:0`.

## Pinned Build Inputs

The tracked builder script pins the runtime inputs used for rebuilds:

- GStreamer monorepo tag `1.28.4`, commit
  `ac267fb521cb9bc8a8450c1f99ee5dc7a914a118`
- `gst-plugin-closedcaption` crate `0.15.2`, SHA-256
  `95af8d6878c6bfc07c01876b19a1b29295e1fca12841080f939c8c0721a6e2d3`
- Meson `1.9.1`
- Rust toolchain `1.96.0`
- `cargo-c` `0.10.23+cargo-0.97.1`

## Release Impact

The Windows helper installer no longer relies on stock Ubuntu GStreamer
packages for the native caption-SEI lane. It now ships the CivicCast-bundled
runtime, verifies the archive SHA-256 before root extraction, extracts it under
`/opt/civiccast/gstreamer`, sets the runtime
environment for CivicCast services, and fails setup if the required caption
elements cannot be inspected through the private runtime.
