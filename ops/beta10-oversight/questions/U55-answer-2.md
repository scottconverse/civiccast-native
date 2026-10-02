# U59 (this session) - CAPTION_QUIET let a real caption outage through

Rung `8h-post-c4` verify #9 (01:36:01) printed
`OK public:CAPTION_QUIET(FAIL over 60s, 0 cue(s); the worker reported received=8 in 60s, 6.462s ago)`.
It was a REAL outage: the coordinator decoded every public keeper segment 01:34:45..01:36:40 - 0 cues in each -
while government (same method) had cues in 5/10, and public's ASR `captions\active.vtt` kept emitting cues. The
worker's receipt ("injected=8") was true of the injector and false of the output. (Unit U58 is diagnosing the
station fault; fixtures in `fixtures\U58-public\`.)

The softening rule (mine, U48) trusts a fresh receipt. The ASR is the better witness, and you already built the
VTT-to-wall-clock mapping in U55.

## Work
1. In `caption_outage()` / the CAPTION_QUIET path: when the window is >= 50 s of span and decoded 0 cues, use your
   U55 mapping to count ASR cues emitted inside the window. If >= 2 ASR cues fall inside it, the line is
   `BAD <ch>:caption_decode_back=FAIL(CAPTIONS_LOST: asr emitted N cues in the window, 0 reached the video)`,
   regardless of the receipt. If the ASR emitted 0-1 cues there, keep CAPTION_QUIET / NO_SPEECH_SOURCE as today.
   If the mapping is unavailable, keep today's behaviour and say so in the line (fail-safe for the checker's own
   gaps, not a pass-through).
2. RED-first: re-run on `evidence\rung-8h-post-c4-20260927-000847\verify-09.json` - today's code prints OK
   CAPTION_QUIET (RED), new code prints BAD CAPTIONS_LOST (GREEN). Re-run every earlier CAPTION_QUIET verify in
   `evidence\rung-*\verify-*.json` and list which flip, with the ASR cue counts, so the coordinator can re-judge
   them.
3. Atomic replace (the rung is live). Report `reports\U59.md`, receipt last. No station action.
