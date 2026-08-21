<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Next Cleanup

Deferred, non-blocking follow-up work queued out of `civiccast/` source per
`scripts/policy/check_no_todos.py` (no TODO/FIXME/HACK markers allowed in
shipped source; unfinished work is tracked here instead).

- **Offline caption job retry UI.** `civiccast/captions/router.py`'s
  `list_offline_caption_jobs` route (state/attempts/last_error, and the retry
  endpoint beside it) has no operator console screen wired to it yet. A
  captions ops screen (or the publish dashboard) should list rows from here,
  optionally filtered to `state=failed`, and wire the retry endpoint to a
  per-row action.
- **GStreamer runtime repair button.** `civiccast/egress/router.py`'s
  `repair_gstreamer_runtime` endpoint (operator recovery for a station
  degraded onto the FFmpeg egress engine) has no operator console affordance.
  Add a "Repair GStreamer runtime & restore full egress" button to the
  egress health surface that POSTs here and surfaces `detail` / `remedy`.
- **WP-5 install-time payload staging + verification wiring.**
  `civiccast/native/upgrade/seams.py`'s `default_lay_tree` currently trusts
  an already-verified staging tree. WP-4 Part B closed the build-time half of
  D2 (audited closure embedded in the signed bundle, byte-verified against
  `runtime-manifest.json`, see `scripts/build_native_installer.py`). WP-5 is
  wiring the actual install-time staging path plus verification call (D2's
  SHA256SUMS-chained-to-Authenticode check that the NSIS installer asserts
  before this code runs).
