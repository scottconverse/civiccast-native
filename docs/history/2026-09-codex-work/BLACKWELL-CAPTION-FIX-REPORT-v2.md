# CivicCast beta.8 Blackwell Caption-Runtime Fix - Report v2

Date: 2026-09-16 (America/Denver)
Candidate: 41ec3dda7f5c5cf678e815ac103fd7e99d85294f (1.0.0-beta.8)
Branch: fix/blackwell-caption-runtime

## Verdict

BLOCKED - bounded result. The live GPU-backed captions-ON run DID occur and produced
fresh cues with a healthy runtime, but the emitted stream carried only null caption
padding, so the required decode-back did not show text. The central acceptance
criterion is NOT met.

## What was done

1. Obtained authorized operator access to the live station API (admin scope).
2. Confirmed the live caption runtime is GPU-backed:
   - resolve_whisper_device -> cuda/float16
   - FasterWhisperRuntime device=cuda compute=float16 on_cuda=True
   - nvidia-smi: RTX 5070 Ti, 16303 MiB, CUDA runtime libs staged
3. Ran a REAL captions-ON live channel:
   - Scheduled + committed Beta7 Sample 3 Weather 360p on the public channel
   - Channel reached ON_AIR on the weather program
   - Runtime status: within-capacity (NOT paused; no overload)
   - Fresh cues appeared in active.vtt: 1 -> 2 -> 4 cues
   - Example cue: "And that's the way thunderstorms in the summer are."
4. Preserved contemporaneous TS + VTT:
   - work/paired-20260916T232254Z/ (active.vtt, segment.ts, manifest.json, decodeback.json)
   - active.vtt sha256 9168f944ea04f941060d6c082148584e0b3ce24d669f6278d27772a66f8fd300
   - segment.ts sha256 2b99c6cdf2e9984e45f8f16a050134617789d7ea41f35be657d7b868e625b041
5. Bounded decode-back on the preserved live TS:
   - expected cues: 4   decoded cues: 0
   - GA94 A/53 payloads present (60 markers) but ALL null padding
   - product proof record 126: FAIL, EGRESS_CAPTION_DECODE_BACK_MISMATCH

## Honest interpretation

The verifier works: it decodes the repo's positive CEA-708 fixture to
"CIVICCAST CEA708 TEST." and returns 0 on the negative control. So 0-decoded means
the cue TEXT did not reach the captured emitted stream in the sampled window; the
sidecar-cue -> live appsrc feed -> CEA insert hop is still not proven.

This is NOT the old failure: the runtime no longer overloads or pauses
(within-capacity, CUDA). Caption GENERATION now works; caption INSERTION into the
emitted TS is the remaining open defect / verification gap.

## Corrections applied this session

- REVERTED the station_runtime.py validator change. The installed manifest is
  cpu/int8 and equals EXPECTED_RUNTIME_CONTRACT, so the candidate validator PASSES
  it. The earlier "validator pinned CPU" claim was WRONG and is withdrawn.
- Corrected the evidence report verdict to match its proof limits.
- Kept only the session-boundary sidecar-reset fix.
- Preserved exact RED-before (2 failed on candidate) / GREEN-after (2 passed).
- Restored temporary auth changes and revoked temporary tokens.
- Restarted service; public channel stopped; service Running/healthy.

## Proof limits

- Live GPU run: REAL, with a fresh meaningful cue.
- Decode-back: performed and NEGATIVE in the sampled window (null padding only).
- Insertion vs feed-hop cause remains undetermined.
- Source tests are NOT installed validation.
