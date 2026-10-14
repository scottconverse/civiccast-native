# Sprint 3 HLS relay and EOS handoff evidence

Branch: `codex/sprint3-output-completion`  
Worktree: `C:\Dev\Claude\civiccast-beta15-completion`

## Item 10: HLS publisher-controlled segment lifetime

The relay no longer gives FFmpeg `delete_segments`. It enables `temp_file`, validates that a staging playlist contains only safe local segment names and that each referenced file exists, and publishes only complete windows. The publisher retains public and staging references, tracks removed public entries until the previous playlist's measured EXTINF sum plus that retired segment's measured EXTINF duration has elapsed, and prunes only exact `seg#########.ts` names older than the staging window. Restart orphans get one grace period derived from the observed public/staging playlist durations. Segments at or beyond the staging minimum remain protected, covering the segment-rename-before-playlist-update interval even when a same-named orphan was found at startup.

Checks:

- Baseline relay suite, before implementation: `.venv\Scripts\python.exe -m pytest tests/egress/test_hls_relay.py -q` -> `20 passed in 1.87s`.
- Initial test-only RED attempt: asserted that FFmpeg deletion was removed and that a playlist with a missing segment was not published; both product assertions failed as expected. The grace test also hit a test-fixture constructor mismatch (`_ManifestPublisher` did not yet accept an injectable clock); the fixture was corrected and the clock injection is now a small internal test seam.
- Focused relay suite after implementation: `.venv\Scripts\python.exe -m pytest tests/egress/test_hls_relay.py -q` -> `24 passed in 2.02s`.
- Real FFmpeg/HTTP/ffprobe check: `.venv\Scripts\python.exe -m pytest tests/egress/test_hls_sink_live_playability.py::test_hls_sink_produces_rolling_playable_live_manifest -q` -> `1 passed in 16.47s`. FFmpeg 8.1.1 generated rolling H.264/AAC segments; ffprobe read both streams over HTTP, and the check confirmed both current segments and an initial segment removed from the later playlist remained HTTP-served during grace. One earlier run stopped after the first append and failed only the newly added retirement assertion; the wait condition was corrected to wait for an actual retirement, then the focused check passed.
- `git diff --check` -> exit 0. Git emitted existing CRLF-to-LF working-copy warnings for `docs/manual/src/22-configuration.md` and `docs/manual/src/30-architecture.md`; no whitespace errors.

Limits and docs needed:

- The public playlist still uses the pre-existing in-place `r+b` rewrite. `civiccast.stream.media_router` returns a direct FastAPI `FileResponse`; it does not lock or snapshot the playlist. Therefore this change protects segment file lifetimes across publication, but does not prove that a concurrent HTTP reader can never observe a mixed/partial playlist during the in-place rewrite. Do not document the public playlist update as atomic.
- With a valid staging playlist, pruning continues on unchanged ticks and after public write failures, and can remove old segments strictly behind the staging window while publication is stalled. If staging is absent, malformed, or references a missing segment, pruning pauses safely; a prolonged invalid staging state while the muxer continues producing files could grow disk use.
- Fresh/dead relay startup still uses the existing output-window cleanup path. This change's grace covers publisher retirement/rebind orphans; it does not promise that clients holding a playlist across an intentional fresh-session wipe can still fetch its segments.
- Architecture wording belongs to the parent task: describe publisher-owned segment deletion and measured playlist-plus-segment grace, and retain the in-place serving caveat above.

## Item 9: GStreamer unequal A/V ending handoff

Per parent direction, no `gst/engine.py` edits or additional EOS probes were made; the difficult EOS work is handed to Sol. Findings for that implementation:

- `_on_old_leg_eos` commits on the first outgoing audio/video EOS. `_begin_reload_commit` then snapshots observed pad ends, so a shorter video stream can trigger the boundary before the longer audio tail is known.
- Simply choosing the maximum duration is unsafe: existing comments record a measured 0.631-second video hole when max was used, while the minimum strategy can trim longer audio. Waiting for both EOS also needs care because outgoing EOS is intercepted around selector handoff to avoid pipeline EOS and may leave a mux pad live but starved.
- Use the existing engine runtime seam in `tests/egress/test_gst_engine_wsl.py` for asymmetric audio-longer and video-longer endings; verify emitted output duration/content and that the shorter video holds/bridges its final picture while longer audio completes. The native bundled-GStreamer availability helper returned `False` in this environment, so this session did not prove native Windows engine behavior.
- The sibling output work adds `audioloudnorm` to divergent output branches; the parent reports its live latency is 3 seconds. EOS integration should account for downstream audio buffers draining after selector EOS.

