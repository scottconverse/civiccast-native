# CivicCast beta.8 Blackwell Caption-Runtime - Report v3

Date: 2026-09-16 (America/Denver)
Candidate: 41ec3dda7f5c5cf678e815ac103fd7e99d85294f (1.0.0-beta.8)
Branch: fix/blackwell-caption-runtime

## Verdict: BLOCKED (bounded)

Live GPU captions-ON runs DID occur with fresh cues and a healthy runtime, but the
emitted stream carried no caption TEXT, so the required text decode-back is NOT met.

## Live runs performed (GPU-backed)

Runtime confirmed: device=cuda compute=float16 on_cuda=True, RTX 5070 Ti 16303 MiB.
Public channel ON_AIR on "Beta7 Sample 3 Weather 360p" via the real operator API.

Run A (23:17Z): fresh cue "And that's the way thunderstorms in the summer are."
  runtime within-capacity. Decode-back: expected 1, decoded 0.
Run B (23:51Z): fresh cue "For Friday, continued chance of convection."
  runtime within-capacity. Decode-back: expected 1, decoded 0.

## Payload-level finding (the decisive evidence)

18-second capture of the LIVE emitted UDP stream (work/long-20260916T235132Z):
- 244 GA94 A/53 SEI markers, only 2 DISTINCT payloads:
    x170  0354fffc 8080 fd8080 fa0000 ...     (null padding)
    x74   0354fffc 942c fd8080 fa0000 ...     (non-padding)
- Stripped to CEA-608 data bytes:
    8080 -> 00 00 (padding)
    942c -> 14 2c : 0x14 is a CEA-608 CONTROL code; 0x2c is ','
    fd80 -> 7d 00 : '}' then null
- ffmpeg sees the TS with NO caption/subtitle stream; readeia608 runs clean over
  244 frames; ffmpeg-subcc returns empty on this capture AND on the 6 s product sample.

Conclusion: the emitted SEI carries control/style bytes and stray punctuation but NO
caption text characters. The sidecar cue text is not arriving in the emitted stream.
Whether the break is feed->appsrc or within tttocea608 is not yet isolated.

## Also observed (not caption proof)

- LIVE reload committed elements=151 (vs 52 in the failed beta.8 runs). Per the
  handoff, elements is a DISPOSAL-LEAK diagnostic; 151 vs 52 indicates accumulating
  reload leakage, and by itself is NOT caption success or failure.

## Changes on the branch

KEPT (independently regression-proven):
- session-boundary sidecar reset: tap_worker.begin_channel_session + daemon
  channel_start_hook + automation/app wiring.
  RED: 2 failed on candidate. GREEN: 2 passed.

KEPT, NOT LIVE-VALIDATED (unaccepted):
- gst/control.py align_live_caption_pts_ms rebase bound (MAX_LIVE_CAPTION_FUTURE_LEAD_MS).
  RED: candidate returned 3132120 for a 3132120 ms cue at 90 s running time.
  GREEN: patched returns 90250. This is necessary-but-not-sufficient: decode-back is
  still negative, so this change is NOT accepted as the fix.

REVERTED (claim withdrawn):
- native/station_runtime.py validator change. Installed manifest is cpu/int8 and
  EQUALS EXPECTED_RUNTIME_CONTRACT, so the candidate validator PASSES it. The earlier
  "validator pinned CPU" claim was false.

## Proof limits

- All 6 installed runtime files hash-match source.
- 142+ tests pass on the affected suites; source tests are NOT installed validation.
- No successful live text decode-back exists.
- Live cue -> emitted TS text delivery is the open defect.
