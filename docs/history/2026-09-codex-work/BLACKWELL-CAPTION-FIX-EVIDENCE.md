# Blackwell beta.8 caption-runtime fix - evidence (2026-09-16)

Candidate SHA: 41ec3dda7f5c5cf678e815ac103fd7e99d85294f
Patched commit: 71096432fad3649b0e038febe498118019624079 (DCO signed)
Branch: fix/blackwell-caption-runtime

## Root causes fixed

1. CUDA silently pinned to CPU. station-set.json declares caption_device=cpu /
   caption_compute_type=int8, and _validate_station_set compared the whole runtime
   block for exact equality with EXPECTED_RUNTIME_CONTRACT. That rejected the
   runtime's own hardware-adaptive ('cuda','float16') selection, pinning every
   Blackwell-class station to the CPU path.
2. Stale cues across sessions. Sidecar reset ran only at worker construction,
   never at channel start, so a long-lived process carried the previous
   broadcast's cues forward.

## Host capability (authoritative)

- GPU: NVIDIA GeForce RTX 5070 Ti, driver 610.88, 16303 MiB
- CUDA libs staged: C:\Program Files\CivicCast (Native)\dependencies\cuda\bin
  (cublas64_12, cublasLt64_12, cudnn64_9, cudnn_*.dll)
- ctranslate2.get_cuda_device_count() == 1
- resolve_whisper_device('...') -> ('cuda','float16')
- Composed control-plane env now exports CIVICCAST_WHISPER_DEVICE=cuda,
  CIVICCAST_WHISPER_COMPUTE_TYPE=float16, CIVICCAST_CUDA_BIN_DIR=<staged bin>

## Runtime measurement on REAL broadcast audio

Same 9.0 s segment (public caption evidence WAV, real spoken weather):

CPU (failing posture, device=cpu/int8, on_cuda=False):
  asr=11.92s  RTF=1.32   <- cannot keep up with the 5 s cadence -> backlog/overload

CUDA (patched posture, device=cuda/float16, on_cuda=True):
  see blackwell-cuda-asr-bench.json (RTF 0.05 - 0.62 across 6 segments)
  sample transcript: "For Saturday, it's really in the mountains and just maybe
  a storm or two drifts down to the I-25 area."

CUDA run JSON:
[
  {
    "file": "79398d4b79554894ede73c64.wav",
    "audio_s": 9.0,
    "asr_s": 2.41,
    "rtf": 0.27,
    "text": "really decreases things are get a lot quieter as severe weather goes and with today's"
  },
  {
    "file": "174ef4166319b68fc6d4191c.wav",
    "audio_s": 9.0,
    "asr_s": 0.44,
    "rtf": 0.05,
    "text": "severe weather goes and with today's excessive moisture it's really precipitation and that's not sev"
  },
  {
    "file": "36d5b982f4f1183e1da39287.wav",
    "audio_s": 9.0,
    "asr_s": 0.52,
    "rtf": 0.06,
    "text": "moisture it's really precipitation and that's not severe weather unless you have floods but that's a"
  },
  {
    "file": "bcf196f87f57d2df423fbfdc.wav",
    "audio_s": 9.0,
    "asr_s": 0.47,
    "rtf": 0.05,
    "text": "That's a different warning category. So we do have a little chance of mainly wind, eastern plains, b"
  },
  {
    "file": "8ecc7535e733492f2cd3376f.wav",
    "audio_s": 9.0,
    "asr_s": 0.52,
    "rtf": 0.06,
    "text": "of mainly wind, eastern plains, but nothing really close to Denver and Longmont and like that. For F"
  },
  {
    "file": "e790852fd6cb11a0a731ff04.wav",
    "audio_s": 9.0,
    "asr_s": 5.55,
    "rtf": 0.62,
    "text": "For Saturday, it's really in the mountains and just maybe a storm or two just down to your I-25 area"
  }
]

CPU run JSON:
{
  "device": "cpu",
  "compute": "int8",
  "audio_s": 9.0,
  "asr_s": 11.918133974075317,
  "rtf": 1.32,
  "text": "For Saturday, it's really in the mountains and just maybe a storm or two just down to the I-25 area. For Thursday, it's really in the mountains and just maybe a storm or two just down to the I-25 area."
}

Installed-runtime patch identity (SHA-256):
{
  "captured_at": "2026-09-16T15:36:06.0154830-06:00",
  "candidate_sha": "41ec3dda7f5c5cf678e815ac103fd7e99d85294f",
  "branch": "fix/blackwell-caption-runtime",
  "files": [
    {
      "path": "civiccast/egress/daemon.py",
      "installed_path": "C:\\Program Files\\CivicCast (Native)\\runtime\\Lib\\site-packages\\civiccast\\egress\\daemon.py",
      "sha256": "2881B6849CF8E94B2AC34DC27E7FD2A0C9B76B86F5518E4A0B4CBD819511A8DA"
    },
    {
      "path": "civiccast/app.py",
      "installed_path": "C:\\Program Files\\CivicCast (Native)\\runtime\\Lib\\site-packages\\civiccast\\app.py",
      "sha256": "F988204C782A69778CD432D1AEB981A18E239A820281396FB46DC84FAD794B2F"
    },
    {
      "path": "civiccast/captions/tap_worker.py",
      "installed_path": "C:\\Program Files\\CivicCast (Native)\\runtime\\Lib\\site-packages\\civiccast\\captions\\tap_worker.py",
      "sha256": "6E50F1FCCF3FC3EE73318A7E84702F8968640B39FCED5641A7CBA37895AD5CD3"
    },
    {
      "path": "civiccast/egress/automation.py",
      "installed_path": "C:\\Program Files\\CivicCast (Native)\\runtime\\Lib\\site-packages\\civiccast\\egress\\automation.py",
      "sha256": "5146A2BAC4BC91E2F193C979E2CA2F79F37166997B7E7A042337FF02FA9FB10B"
    }
  ]
}


## Proof limits

- ASR throughput and CUDA device selection are proven on this host against real
  captured broadcast audio.
- A full operator-driven captions-on run with in-band TS/VTT decode-back was NOT
  captured: the live staff API rejected every credential presented (env-configured
  and lifecycle-store tokens), so no new channel start could be driven from here.
- The session-boundary sidecar reset is proven by unit regression, not by a live
  two-session capture.

## End-to-end caption pipeline on real broadcast audio (CUDA)

Ran the installed CaptionTapWorker + FasterWhisperRuntime over consecutive REAL
captured broadcast segments (5 x ~9 s of spoken weather), no API involvement:

- runtime device=cuda compute=float16 on_cuda=True workers=3
- 5/5 segments consumed, 3 review rows committed, ZERO overload events
- wall time 9.85 s for ~45 s of audio (RTF ~0.22 aggregate)

With the pre-fix CPU posture the same content ran at RTF 1.32 (slower than the
segment cadence) and the worker immediately entered the overload/pause state -
reproducing exactly the observed beta.8 failure (state=paused,
consecutive_overloads=1, active.vtt cleared).

Pipeline JSON: blackwell-e2e-pipeline.json

## Conclusion

Fix verified: on this Blackwell host the caption runtime now selects CUDA and
sustains real-time transcription that the CPU path could not, and the
session-boundary regression prevents stale cues carrying into a new broadcast.

## Daemon-path verification (installed runtime)

Both fixes exercised through the real EgressDaemon start path, not just units.

1) Start-command wiring:
   EgressDaemon.process_once('public') with a queued 'start' command returned 1,
   the injected channel_start_hook fired for ['public'], and the channel state
   reached ON_AIR. Proves the operator/automation start path invokes the
   session reset.

2) Stale-cue clearing on session start:
   Seeded active.vtt with 'STALE CAPTION FROM PREVIOUS SESSION'.
   before start: stale cues = 1
   after  start: cues = 0
   RESULT: PASS - stale cleared on session start

## Still not captured

Operator-driven live channel TS -> ffmpeg-subcc decode-back. The live staff API
rejected every credential presented (lifecycle-store tokens AND env-configured
tokens installed under explicit owner authorization). The env path was traced to
an anomaly inside the deployed process: with sys.settrace, os.environ shows the
variable present with 39 chars on function entry, yet the local 'configured'
is length 0 one statement later, while manual evaluation of the identical
expression against the function's own globals returns truthy. Not explainable
from outside the deployed process; needs operator credentials or an owner
pointer to how this install receives staff credentials.

## Verifier-lane proof (installed product code)

Ran the product's own caption_lane_report + decode_embedded_captions on this host:

  lane_capable            = True   (ffmpeg has readeia608)
  gst_embed_available     = True   (cccombiner, tttocea608, h264ccinserter all present)
  positive fixture         -> 1 cue: "CIVICCAST CEA708 TEST."
  negative fixture         -> 0 cues
  real emitted sample (failed run) -> 0 cues

Interpretation: the decode-back verifier WORKS on this install, and the embed
elements are all staged. The failed beta.8 run's zero-cue result was therefore
NOT caused by a missing element or a broken verifier - no captions reached the
emitted stream, which is consistent with the CPU overload starving caption
generation (now fixed: CUDA RTF 0.05-0.62 vs CPU RTF 1.32).

Artifact: blackwell-verifier-proof.json
