# Beta14 independent focused source review

Date: 2026-10-12 (UTC). Branch: `codex/beta14-field-fixes`.
Reviewed the shared source worktree's actual diff against HEAD, repository instructions, the owner goal document, installer/model receipt, and task-completion record. This is a source-worktree review, not a committed-candidate or installation verdict. Candidate installation remains pending.

## Scoped verdict

PASS for the reviewed final changes, with no unresolved substantive code finding. Scope covered goals 1–7, 25 and 28, followed by goals 8–24, 26 and 27 proportionally. Generated API/manual/version consolidation, complete manual PDF bounds verification and release/installation evidence remain root work.

## Findings corrected during review

- **Live Whisper fallback selected the activation tier again.** `ai_models/runtime.py` serialized the selected model name but omitted explicit packaged path/tier; the isolated child inherited activation environment settings. A no-model-load reproduction showed selected Medium reconstructing as activated Large. The fix carries `runtime_model` into the child configuration. Independently reran both batch and live child-reconstruction regression cases: 2 passed.
- **Private playback introduced a module import cycle.** A top-level `live.router` dependency import in `schedule/router.py` made fresh `import civiccast.egress.caption_embed` fail through schedule/live/egress initialization. The dependency lookup is now deferred until the handler runs. Fresh import succeeds, and standalone commissioning plus playback regressions passed.
- **Production chapter synchronization discarded typed chapters.** The actual app provider received `StaffAssetRow.chapters` containing `Chapter` instances, then attempted `Chapter(**raw)`. Executing the production nested provider with two valid chapters returned zero and logged both as malformed. The production factory now uses `Chapter.model_validate`, preserving typed instances and legacy dictionaries. Its actual-provider regression passed independently.
- **TrimEditor could not recover after a media error with an unchanged playback URL.** Error rendering unmounted the video; grant renewal alone did not rerun attachment. The fix adds an explicit attachment attempt dependency. The corrected regression exercises a successful grant, media error, and successful same-URL renewal; the final four-test file passed independently.
- **Summary citation renewal had the same media lifecycle defect.** The final player keeps the media element mounted and explicitly reattaches on renewal. It also reports incomplete package coverage for citation start/end boundaries. Both citation regressions passed independently.

## Exact independent verification

Commands ran from `C:\Dev\Claude\civiccast-beta11-whistle` unless otherwise stated, using `.venv/Scripts/python.exe`. Shell calls explicitly set that location because the login profile can reset the working directory.

1. `python -m pytest tests/captions/test_whistle_runtime.py::test_cpu_fallback_deadline_is_configurable_and_finite tests/captions/test_caption_tap_worker.py::test_capacity_status_distinguishes_transient_and_sustained_backlog tests/captions/test_review_media.py::test_long_review_clip_includes_the_complete_cue tests/captions/test_review_media.py::test_review_clip_reports_source_audio_that_ends_before_the_cue tests/egress/test_caption_proof_worker.py::test_proof_uses_real_capture_pts_and_keeps_missing_and_wrong_cues_detectable tests/summary/test_ollama_summary.py::test_summary_defers_before_generate_when_broadcast_headroom_is_short tests/summary/test_ollama_summary.py::test_summary_runs_when_model_and_broadcast_headroom_are_available -q` — **7 passed**.
2. `python -m pytest tests/ai_models/test_runtime_wiring.py::TestCaptionsRuntimeSeam::test_native_runtime_uses_operator_selected_model_over_activation_default -q` — **2 passed**, after the child-selection correction.
3. With `CIVICCAST_STAFF_TOKENS` removed only from the check shell's environment: `python -m pytest tests/schedule/test_source_playback_router.py tests/schedule/test_asset_packaging.py tests/recording/test_dropout_detection.py::test_check_dropout_detects_crashed_process_and_reconnects tests/records/test_records_router.py::TestRecordsRouter::test_long_summary_narrative_is_paginated_and_verifies -q` — **12 passed**.
4. `python -m pytest tests/live/test_router.py::TestPublicCurrentLive::test_egress_live_status_exposes_only_actual_program_timeline_fields tests/live/test_app_preflight_source_probe_wiring.py -q` — **11 passed**.
5. From `civiccast/apps/portal-public`: `npm exec vitest run src/HlsPlayer.hlsjsCaptions.test.tsx src/screens/HomeScreen.livePoll.test.tsx` — **7 passed**.
6. After import-cycle correction: `python -c 'import civiccast.egress.caption_embed'` — **exit 0**; `python -m pytest tests/installer/test_commissioning.py::TestFirstRunCableChecks::test_default_profile_uses_backup_configuration_and_probe_result tests/schedule/test_source_playback_router.py -q` — **6 passed**.
7. From `civiccast/apps/portal-operator`: `npm exec vitest run src/screens/TrimEditorScreen.test.tsx` — **4 passed**. The final rerun also passed all four after the test was corrected to exercise an actual media error. Its attempted `-t 'media error'` npm argument was not forwarded by npm, so that invocation is a four-test file result, not a single-test result.
8. `python -m pytest tests/agenda/test_app_factory_wiring.py -q` — **1 passed**.
9. `python -m pytest tests/egress/test_source_plan.py::test_looping_provider_repeats_the_published_sequence_after_the_last_item tests/egress/test_source_plan.py::test_looping_provider_preserves_gaps_between_published_items -q` — **2 passed**.
10. From `civiccast/apps/portal-operator`: `npm exec -- vitest run src/screens/SummaryReviewScreen.test.tsx` — **2 passed**, covering source-to-package offset/coverage and fatal-media same-URL renewal.

An initial standalone commissioning invocation could not collect because of the confirmed import cycle. Its selector also named the wrong test class; the corrected exact selector and successful result are recorded above. No failed or empty invocation is counted as passing evidence.

## Review conclusions and limits

Private source grants use the existing trim roles (`records_clerk`, `meeting_operator`, `support_admin`), asset-scoped HttpOnly SameSite cookies, a 15-minute expiry, HTTPS or loopback HTTP admission, resolved configured-root containment, and native Range-capable responses. Existing public VOD routes still require publication. No bearer in media URLs or whole-file Blob playback was found in the reviewed changes.

Public playback metadata uses actual handoff proof events and the HLS playback clock. Summary citations resolve the meeting asset, subtract the packaged source offset, preserve working HLS controls, and explain unavailable citation coverage. The worker separately reported a real Chromium packaged-TS TrimEditor playback check; this reviewer did not rerun that browser check or claim it as independently executed evidence.

Goal 26's existing supported configuration was traced: contiguous published programs with `CIVICCAST_SCHEDULE_LOOP=1` repeat the sequence, while the finite default preserves intentional gaps. The two selected source-plan regressions passed independently. Root is adding the working recipe to the manual; final candidate host observation remains installation evidence.

No model was loaded or downloaded by this reviewer. No full suite, harness, build, installer, host change, soak, commit or push was performed. Complete manual PDF clipping acceptance, hardware output acceptance, initial Sandbox installation and final real installation remain separate candidate evidence. The unavailable original field TSDuck failure was not assigned an invented cause.

`proved: focused source regressions passed as listed; no unresolved scoped code finding · lane: Critical (private media access and recording concurrency reviewed)`
