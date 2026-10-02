# Independent adversarial audit — rev3 caption diagnostic main apply

Status: **HOLD — no main-tree files changed by this audit.** The specified hold condition was met: focused isolated tests failed. No backup or patch application was performed. Existing dirty main-tree changes were preserved.

## Patch and pre-apply checks

- Patch: `C:\Users\scott\Documents\Codex\2026-09-20\you-x20\outputs\BETA10-CAPTION-TAP-PRECEDING-BATCH-DURATION-REV3.patch`
- SHA256: `5356CD4F22BA90ADAE6B2272047FCD2BC59F9996E3AF8102A536B38F6EE4F3A8` — matches request.
- `git apply --check --whitespace=error <patch>`: **exit 0**.
- Main prehashes: all three matched the requested values:
- `95F644F8BBA1F242561430BE606F5FA6BAC9DAC3A461E6C6706D9C79295330CB  civiccast/captions/tap_worker.py`
- `305089445FA93A9ABD76B3EC30636928B33AB9B81B7D45EDAE4A533D30C5D6E0  civiccast/captions/tap_batch_diagnostic.py`
- `9D27A48665FD8CC1DBBBE3D2131E4DE443E6A96AFA04C2285140D3CD6AD13E06  tests/captions/test_caption_tap_batch_diagnostic.py`
## Isolated candidate identity

The `_pb_rev3\b` isolated candidate files match all three expected posthashes:
- `B66C63C4C4B9AF7B3F8B6CF797FC52CEC77641B95487EB08EAAE51C9CFB1A35F  civiccast/captions/tap_worker.py`
- `549E90F21517708A4DB824DF3A6BF48099AB696A10A00BF13F073024E28C6F25  civiccast/captions/tap_batch_diagnostic.py`
- `DB3029733568A76A1C029D8090E799BCB4E1C1366DBC398AA809348C62E190F8  tests/captions/test_caption_tap_batch_diagnostic.py`
## Blocking test result

Command:
`\.venv\Scripts\python.exe -m pytest -q <isolated>\tests\captions\test_caption_tap_batch_diagnostic.py -k "test_overload_discard_records_prior_batch_duration_nonzero or test_prior_session_duration_does_not_leak_into_a_new_session or test_clear_channel_captions_resets_the_last_batch_duration or test_default_off_never_stamps_or_reads_the_new_batch_clocks" --basetemp <outputs>\ptmp-audit-rev3`

Result: **4 failed, 28 deselected, exit 1** (4.17 s).

Failures:
- `test_clear_channel_captions_resets_the_last_batch_duration`: `CaptionTapWorker` has no `_last_batch_seconds`.
- `test_prior_session_duration_does_not_leak_into_a_new_session`: same missing member.
- `test_overload_discard_records_prior_batch_duration_nonzero`: overload record has no `preceding_batch_seconds` field.
- `test_default_off_never_stamps_or_reads_the_new_batch_clocks`: worker has no `_channel_batch_started_at`.

The isolated candidate's `tap_worker.py` does not implement the duration-tracking behavior asserted by its paired test file, despite the supplied expected posthash matching. This mismatch blocks the independent audit. The real held-batch overload assertion did not pass, so the requested evidence is not established.

## Main apply disposition

Not applied; no three-file backup created; no normalized-content comparison, main affected suite, main Ruff, or main `git diff --check` run. This is intentional under the explicit HOLD-on-any-audit/test-failure instruction. No installed/live/service/control/restart/helper/stage/commit activity occurred.

proved: patch hash, main prehashes, apply-check passed; isolated focused contract tests failed (4); main apply held · lane: Critical
