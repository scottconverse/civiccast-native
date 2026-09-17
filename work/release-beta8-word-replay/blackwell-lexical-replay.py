# SPDX-License-Identifier: Apache-2.0
# Isolated Blackwell replay: bootstrap the checkout and CUDA path before imports.
# ruff: noqa: E402
import hashlib
import json
import os
import sys
import time
import wave
from pathlib import Path

repo = Path(r"C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-native")
sys.path.insert(0, str(repo))
os.environ.update(
    CIVICCAST_WHISPER_MODEL_PATH=r"C:\Program Files\CivicCast (Native)\packs\captions-floor\models\faster-whisper-medium",
    CIVICCAST_WHISPER_DEVICE="cuda",
    CIVICCAST_WHISPER_COMPUTE_TYPE="float16",
    CIVICCAST_CUDA_BIN_DIR=r"C:\Program Files\CivicCast (Native)\dependencies\cuda\bin",
    HF_HUB_OFFLINE="1",
)
os.environ["PATH"] = os.environ["CIVICCAST_CUDA_BIN_DIR"] + os.pathsep + os.environ["PATH"]
from types import SimpleNamespace

from civiccast.captions.models import AudioChunk
from civiccast.captions.runtime import FasterWhisperRuntime
from civiccast.captions.stabilize import CaptionStabilizer

out = Path(r"C:\Users\scott\AppData\Local\Temp") / sys.argv[1]
source = Path(r"C:\ProgramData\CivicCast\data\caption-tap\public\processed")
runtime = FasterWhisperRuntime(live=True)
runtime.prepare()
assert runtime.device == "cuda" and runtime.compute_type == "float16"
actual_model = runtime._model
raw_words = []


def transcribe_with_words(*args, **kwargs):
    segments, info = actual_model.transcribe(*args, **kwargs)
    segments = list(segments)
    raw_words[:] = [
        {
            "start": s.start,
            "end": s.end,
            "text": s.text,
            "words": [
                {"word": w.word, "start": w.start, "end": w.end, "probability": w.probability}
                for w in (s.words or [])
            ],
        }
        for s in segments
    ]
    return segments, info


runtime._model = SimpleNamespace(transcribe=transcribe_with_words)
stabilizer = CaptionStabilizer(live=True)
record = {
    "kind": "isolated preserved PCM replay; NOT installed service validation",
    "device": runtime.device,
    "compute_type": runtime.compute_type,
    "source": str(repo),
    "module_sha256": hashlib.sha256(
        (repo / "civiccast/captions/stabilize.py").read_bytes()
    ).hexdigest(),
    "windows": [],
}
record["source_hashes"] = {
    name: hashlib.sha256((repo / "civiccast/captions" / name).read_bytes()).hexdigest()
    for name in [
        "stabilize.py",
        "runtime.py",
        "models.py",
        "pipeline.py",
        "worker.py",
        "tap_worker.py",
    ]
}
record["actual_model_device"] = actual_model.model.device
record["actual_model_compute_type"] = actual_model.model.compute_type
assert record["actual_model_device"] == "cuda" and record["actual_model_compute_type"] == "float16"
previous = b""
for offset, index in enumerate(range(int(sys.argv[2]), int(sys.argv[2]) + 24)):
    path = source / f"chunk-{index:06d}.wav"
    raw = path.read_bytes()
    with wave.open(str(path), "rb") as audio:
        assert audio.getnchannels() == 1 and audio.getsampwidth() == 2
        rate = audio.getframerate()
        pcm = audio.readframes(audio.getnframes())
    tail = previous[-5 * rate * 2 :] if previous else b""
    chunk = AudioChunk(
        chunk_id=f"replay-{index}",
        start_seconds=offset * 5 - len(tail) / (rate * 2),
        end_seconds=offset * 5 + len(pcm) / (rate * 2),
        sample_rate_hz=rate,
        pcm_s16le=tail + pcm,
    )
    began = time.monotonic()
    hypotheses = list(runtime.transcribe([chunk]))
    cues = []
    for hypothesis in hypotheses:
        cues.extend(stabilizer.observe(hypothesis))
    record["windows"].append(
        {
            "path": str(path),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "audio_start": chunk.start_seconds,
            "audio_end": chunk.end_seconds,
            "raw_model_segments": list(raw_words),
            "elapsed": time.monotonic() - began,
            "hypotheses": [h.model_dump() for h in hypotheses],
            "cues": [c.model_dump() for c in cues],
        }
    )
    previous = pcm
    out.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(index, len(hypotheses), len(cues), flush=True)
record["committed"] = [c.model_dump() for c in stabilizer.committed()]
record["expired"] = [c.model_dump() for c in stabilizer.expired_unconfirmed()]
out.write_text(json.dumps(record, indent=2), encoding="utf-8")
print("COMPLETE", len(record["committed"]), str(out), flush=True)
