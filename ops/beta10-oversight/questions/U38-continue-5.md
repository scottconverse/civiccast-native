# U46 (U38 session) - LIVE: public's emitted stream carries NO embedded captions while its caption sidecar is live.

Installed now: beta10-int + U40/U41/U42/U43 (preparer, loudness_ride, automation, daemon, source_plan, engine minus
the STALL_DIAG carve, reload_policy, strategy, worker). Service pid 39572 since 07:36:46.

OBSERVED (evidence `evidence\public-no-embedded-captions-1033\`):
- Rung verifier (`evidence\rung-8h-pre-u44-20260926-101439\verify-01/02.json`): public caption_decode_back FAIL both
  runs (0 cues in 4 segments); government 1/4 then 1/4; education 1/4 then 4/4.
- My decode of the last ~56 s of emitted HLS per channel (`ffmpeg -f lavfi movie=X.ts[out0+subcc] -c:s srt`):
  public 0 cues (538 CC packets present), government 4 cues, education 7 cues. `public.srt`, `government.srt`,
  `education.srt`, and `public-last56s.ts` are in the evidence folder.
- At the same time public's `captions\active.vtt` (the ASR sidecar) was gaining cues every few seconds (copied).
So captions are produced for public but do not reach its emitted stream (or are emitted empty/null).

## Work (new worktree `civiccast-ds-u46`, branch `beta10-u46` from `beta10-u41` @ b38e5a3b; own `.venv`)
1. Trace the caption path for one channel end to end: ASR sidecar -> daemon/feed -> worker `caption` control -> engine
   cc injection -> mux. Name each hop with file:line. Measure on the LIVE station, read-only, where public's captions
   stop (counts at each hop you can observe: the feed's sends, the worker's receipts if logged, the emitted CC
   payload). Compare with education. Consider: a channel-specific feed state after a reload/restart, a
   running-time/PTS window mismatch dropping every cue (public's running time is the largest), a caption generation
   id mismatch, the U41 persistent flag or plan-EOS hold changing the caption leg.
2. Root cause with file:line and numbers; fix; tests red then green (unit + one real-worker run with the runtime root
   `C:\Program Files\CivicCast (Native)\runtime`); focused gates + full egress suite after checking no other
   `pytest tests/egress` is running; ruff; mypy. Stage `staging\U46` like U41 (bases = live sha256s; engine.py
   candidate = HEAD minus the STALL_DIAG carve). Do not install. Also add a per-channel INFO counter line in the
   worker (captions received / injected per 60 s) so this is visible in the logs next time.
3. Coordinate: U44 (engine switch-path video stall) is working in `civiccast-ds-u44` from the same base; keep your
   engine.py hunks minimal and list them so a merge is mechanical. Report `reports\U46.md`. STOP only on a product
   question.
