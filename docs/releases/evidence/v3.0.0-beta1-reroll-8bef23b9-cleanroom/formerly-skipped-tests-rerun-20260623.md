# Formerly Skipped Test Rerun - 2026-06-23

This file records the post-GauntletGate audit of the `22 skipped` tests from the Windows aggregate pytest run.

## Result

Release status: skipped-test closure is clear for the scoped public-beta claim.

Every formerly skipped check was exercised on its required dependency or platform. The GStreamer-native caption-SEI proof now runs and passes with the CivicCast-bundled private GStreamer runtime.

## Supplemental Passes

- External Postgres:
  - Command: `CIVICCAST_POSTGRES_TEST_URL=postgresql+psycopg://civiccast:civiccast@127.0.0.1:55432/civiccast_test pytest tests/auth/test_staff_token_lifecycle.py::test_postgres_audit_order_is_deterministic_under_collisions tests/captions/test_review_persistence.py::TestRealPostgres::test_contract_round_trip_on_real_postgres -q`
  - Result: `2 passed`.
- TSDuck live network pins:
  - Command: `CIVICCAST_TSDUCK_NETWORK_TESTS=1 pytest tests/installer/test_tsduck_install.py::test_pinned_sha_matches_release -q`
  - Result: `2 passed`.
- WSL2 hardware probe:
  - Command: `/root/cc-wsl-venv/bin/python -m pytest tests/test_hardware_probe_wsl2_positive.py -q` inside Ubuntu-24.04 WSL.
  - Result: `3 passed`.
- POSIX/XDG compliance:
  - Command: `/root/cc-wsl-venv/bin/python -m pytest tests/egress/test_compliance.py::test_managed_tsduck_dir_xdg_default -q` inside Ubuntu-24.04 WSL.
  - Result: `1 passed`.
- WSL GStreamer runtime:
  - Command: Ubuntu-24.04 dependency substrate plus the CivicCast-bundled private GStreamer runtime containing upstream GStreamer closedcaption (`h264ccinserter`) and gst-plugins-rs closedcaption (`tttocea608`), then `/root/cc-wsl-venv/bin/python -m pytest tests/egress/test_gst_engine_wsl.py -q -rs`.
  - Result: `14 passed`.
  - Follow-up fix: the public-beta default encoder now uses the bundled
    `openh264enc` path, live-ingest source conforming includes `videorate`, and
    the worker demotes GPU H.264/H.265 decoders unless
    `CIVICCAST_GST_ALLOW_HARDWARE_DECODE` is set, so decoded UDP feeds stay in
    system memory by default.

## Caption-SEI Closure

- Test: `tests/egress/test_gst_engine_wsl.py::test_caption_embed_survives_to_emitted_stream`.
- Required elements in test: `tttocea608`, `ccconverter`, `cccombiner`, `h264ccinserter`.
- Bundled runtime:
  - The CivicCast private GStreamer runtime provides `h264ccinserter`.
  - The bundled gst-plugins-rs closedcaption plugin provides `tttocea608`.
  - The installer still installs Ubuntu 24.04 native libraries and Python GI bindings needed to run the private runtime.
- Product fix:
  - `tttocea608` now runs with `mode=pop-on`.
  - The CEA-708 cc_data caps now fix framerate at `30/1`.
- Result: `1 passed` focused; `14 passed` for the full WSL GStreamer shard.

## Release Impact

The public beta gate may claim native GStreamer caption-SEI embedding only when the CivicCast-bundled private runtime is extracted and verified. Stock Ubuntu 24.04 GStreamer packages alone remain insufficient and are not the release strategy for this lane.

## 2026-06-24 Current Aggregate

- Windows aggregate: `4323 passed, 22 skipped`.
- Formerly skipped categories closed by supplemental reruns: `2` real Postgres, `2` TSDuck live network, `4` WSL2/POSIX, and `14` bundled-runtime live GStreamer tests.
- Node package lock/audit closure: all six private Node package roots now have `package-lock.json`; `npm audit --audit-level=moderate` reports `found 0 vulnerabilities` for `portal-operator`, `portal-public`, `installer`, `app-platform-shells`, `ctv-reference`, and `control_room/tsr_service`.
- TSR sidecar vulnerability closure: `timeline-state-resolver` remains pinned at `9.3.2`; `package-lock.json` records npm overrides for transitive `ws` `8.21.0` and `uuid` `11.1.1`, and `node --test builder.test.mjs` reports `6 passed`.
