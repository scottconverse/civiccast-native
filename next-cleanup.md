<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Next Cleanup

Deferred, non-blocking follow-up work queued out of `civiccast/` source per
`scripts/policy/check_no_todos.py` (no TODO/FIXME/HACK markers allowed in
shipped source; unfinished work is tracked here instead).

- **WP-5 install-time payload staging + verification wiring.**
  `civiccast/native/upgrade/seams.py`'s `default_lay_tree` currently trusts
  an already-verified staging tree. WP-4 Part B closed the build-time half of
  D2 (audited closure embedded in the signed bundle, byte-verified against
  `runtime-manifest.json`, see `scripts/build_native_installer.py`). WP-5 is
  wiring the actual install-time staging path plus verification call (D2's
  SHA256SUMS-chained-to-Authenticode check that the NSIS installer asserts
  before this code runs).
