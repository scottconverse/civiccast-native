# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Decode measurement contracts, with deterministic clocks and fake models."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier
from types import SimpleNamespace

import pytest

import civiccast.captions.runtime as module
from civiccast.captions.models import AudioChunk


def chunk(rate=16000):
    return AudioChunk(
        chunk_id="measure",
        start_seconds=0,
        end_seconds=4,
        sample_rate_hz=rate,
        pcm_s16le=b"\x00\x00",
    )


def segment(**extra):
    return SimpleNamespace(text="motion carries", start=0, end=2, **extra)


def metrics(runtime):
    return getattr(runtime, "last_decode_metrics", lambda: None)()


def test_model_call_and_lazy_consumption_exclude_consumer_pause(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(perf_counter=lambda: now[0]), raising=False)
    runtime = module.FasterWhisperRuntime(device="cpu", live=False)

    @contextmanager
    def source(_):
        yield "audio"

    monkeypatch.setattr(runtime, "_chunk_audio_source", source)

    def transcribe(*args, **kwargs):
        now[0] += 2

        def segments():
            now[0] += 3
            yield segment(temperature=0.2)
            now[0] += 4
            yield segment(temperature=0.4)

        return segments(), SimpleNamespace(duration_after_vad=3.5)

    runtime._model = SimpleNamespace(transcribe=transcribe)
    stream = iter(runtime.transcribe([chunk()]))
    assert next(stream).text == "motion carries"
    now[0] += 100
    assert next(stream).text == "motion carries"
    now[0] += 100
    assert list(stream) == []
    assert metrics(runtime).get("model_call_s") == 2.0
    assert metrics(runtime).get("lazy_next_s") == 7.0
    assert metrics(runtime) == {
        "transcribe_s": 9.0,
        "model_call_s": 2.0,
        "lazy_next_s": 7.0,
        "duration_after_vad": 3.5,
        "max_segment_temperature": 0.4,
    }


def test_reset_before_predecode_failure(monkeypatch):
    runtime = module.FasterWhisperRuntime(device="cpu", live=True)
    runtime._model = SimpleNamespace(transcribe=lambda *a, **k: ([segment()], None))
    list(runtime.transcribe([chunk()]))
    assert metrics(runtime) is not None
    monkeypatch.setattr(
        module, "_write_pcm_chunk_wav", lambda *a: (_ for _ in ()).throw(RuntimeError("wav"))
    )
    with pytest.raises(RuntimeError, match="wav"):
        list(runtime.transcribe([chunk(8000)]))
    assert metrics(runtime) is None


def test_split_includes_terminal_attempt_without_extra_clock_reads(monkeypatch):
    now, ticks = [0.0], []

    def clock():
        ticks.append(now[0])
        return now[0]

    monkeypatch.setattr(module, "time", SimpleNamespace(perf_counter=clock))
    runtime = module.FasterWhisperRuntime(device="cpu", live=False)
    item, audio, prompt = object(), object(), object()
    calls = []

    def transcribe(source, **kwargs):
        calls.append((source, kwargs))
        now[0] += 2

        def segments():
            now[0] += 3
            yield item
            now[0] += 5

        return segments(), None

    runtime._model = SimpleNamespace(transcribe=transcribe)
    stream = iter(runtime._transcribe_source(audio, initial_prompt=prompt))
    assert next(stream) is item
    assert metrics(runtime)["lazy_next_s"] == 3
    now[0] += 100
    assert list(stream) == []
    assert metrics(runtime)["model_call_s"] == 2
    assert metrics(runtime)["lazy_next_s"] == 8
    assert metrics(runtime)["transcribe_s"] == 10
    assert len(ticks) == 6  # call, yield attempt, exhaustion: two reads each
    assert calls == [
        (
            audio,
            {
                "beam_size": 5,
                "language": None,
                "task": "transcribe",
                "vad_filter": True,
                "initial_prompt": prompt,
            },
        )
    ]
    copy = metrics(runtime)
    copy["lazy_next_s"] = 999
    assert metrics(runtime)["lazy_next_s"] == 8


@pytest.mark.parametrize("where", ["call", "next"])
def test_split_retains_original_failure_and_attempt_elapsed(monkeypatch, where):
    now = [0.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(perf_counter=lambda: now[0]))
    runtime = module.FasterWhisperRuntime(device="cpu", live=False)
    error = RuntimeError("original decode error")

    def transcribe(*args, **kwargs):
        now[0] += 2
        if where == "call":
            raise error

        def segments():
            now[0] += 4
            raise error
            yield  # make the failure lazy

        return segments(), None

    runtime._model = SimpleNamespace(transcribe=transcribe)
    with pytest.raises(RuntimeError) as caught:
        list(runtime._transcribe_source(object(), initial_prompt=None))
    assert caught.value is error
    assert metrics(runtime)["model_call_s"] == 2
    assert metrics(runtime)["lazy_next_s"] == (4 if where == "next" else 0)
    assert metrics(runtime)["transcribe_s"] == (6 if where == "next" else 2)


def test_partial_close_does_not_invent_terminal_work(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(perf_counter=lambda: now[0]))
    runtime = module.FasterWhisperRuntime(device="cpu", live=False)

    def segments():
        now[0] += 3
        yield object()
        now[0] += 4
        yield object()

    runtime._model = SimpleNamespace(transcribe=lambda *a, **k: (segments(), None))
    stream = runtime._transcribe_source(object(), initial_prompt=None)
    next(stream)
    now[0] += 100
    stream.close()
    assert metrics(runtime)["model_call_s"] == 0
    assert metrics(runtime)["lazy_next_s"] == 3
    assert metrics(runtime)["transcribe_s"] == 3


@pytest.mark.parametrize("call_s,next_s", [(2, 0), (0, 3), (0, 0)])
def test_call_only_next_only_and_empty_decode(monkeypatch, call_s, next_s):
    now = [0.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(perf_counter=lambda: now[0]))
    runtime = module.FasterWhisperRuntime(device="cpu", live=False)

    def transcribe(*args, **kwargs):
        now[0] += call_s

        def segments():
            now[0] += next_s
            if next_s:
                yield object()

        return segments(), None

    runtime._model = SimpleNamespace(transcribe=transcribe)
    assert len(list(runtime._transcribe_source(object(), initial_prompt=None))) == bool(next_s)
    assert metrics(runtime)["model_call_s"] == call_s
    assert metrics(runtime)["lazy_next_s"] == next_s
    assert metrics(runtime)["transcribe_s"] == call_s + next_s


def test_split_is_latest_chunk_not_previous_chunk_or_running_total(monkeypatch):
    now, calls = [0.0], [0]
    monkeypatch.setattr(module, "time", SimpleNamespace(perf_counter=lambda: now[0]))
    runtime = module.FasterWhisperRuntime(device="cpu", live=False)

    @contextmanager
    def source(_):
        yield object()

    monkeypatch.setattr(runtime, "_chunk_audio_source", source)

    def transcribe(*args, **kwargs):
        calls[0] += 1
        duration = calls[0]
        now[0] += duration

        def segments():
            now[0] += duration + 2
            yield segment()

        return segments(), None

    runtime._model = SimpleNamespace(transcribe=transcribe)
    assert len(list(runtime.transcribe([chunk(), chunk()]))) == 2
    assert metrics(runtime)["model_call_s"] == 2
    assert metrics(runtime)["lazy_next_s"] == 4
    assert metrics(runtime)["transcribe_s"] == 6
    list(runtime.transcribe([]))
    assert metrics(runtime) is None


@pytest.mark.parametrize("live", [True, False])
def test_kwargs_transcript_and_runtime_exceptions_unchanged(live, monkeypatch):
    runtime = module.FasterWhisperRuntime(device="cpu", live=live, language="en")
    calls = []

    def transcribe(source, **kwargs):
        calls.append(kwargs)
        return [segment(temperature=0.6)], None

    runtime._model = SimpleNamespace(transcribe=transcribe)
    assert [h.text for h in runtime.transcribe([chunk()])] == ["motion carries"]
    expected = {
        "beam_size": 1 if live else 5,
        "language": "en",
        "task": "transcribe",
        "vad_filter": True,
        "initial_prompt": None,
    }
    if live:
        expected["word_timestamps"] = True
    assert calls == [expected]
    error = RuntimeError("decode")

    def fail(*args, **kwargs):
        raise error

    runtime._model = SimpleNamespace(transcribe=fail)
    with pytest.raises(RuntimeError) as caught:
        list(runtime.transcribe([chunk()]))
    assert caught.value is error
    assert metrics(runtime)["transcribe_s"] >= 0


@pytest.mark.parametrize("field", ["duration_after_vad", "temperature"])
@pytest.mark.parametrize("value", [None, "bad", float("nan"), float("inf"), -1, 10**400])
def test_bad_metadata_is_null_without_changing_transcript(field, value):
    runtime = module.FasterWhisperRuntime(device="cpu", live=True)
    info = SimpleNamespace(duration_after_vad=value if field == "duration_after_vad" else 1)
    item = segment(temperature=value if field == "temperature" else 0)
    runtime._model = SimpleNamespace(transcribe=lambda *a, **k: ([item], info))
    assert [h.text for h in runtime.transcribe([chunk()])] == ["motion carries"]
    assert (
        metrics(runtime)[field if field == "duration_after_vad" else "max_segment_temperature"]
        is None
    )


@pytest.mark.parametrize("field", ["duration_after_vad", "temperature"])
def test_raising_metadata_property_cannot_fail_decode(field):
    class Broken:
        def __getattr__(self, name):
            raise RuntimeError("measurement")

    runtime = module.FasterWhisperRuntime(device="cpu", live=True)
    item = segment()
    if field == "temperature":

        class BrokenSegment:
            text, start, end = "motion carries", 0, 2

            @property
            def temperature(self):
                raise RuntimeError("measurement")

        item = BrokenSegment()
    runtime._model = SimpleNamespace(transcribe=lambda *a, **k: ([item], Broken()))
    assert [h.text for h in runtime.transcribe([chunk()])] == ["motion carries"]
    assert (
        metrics(runtime)[field if field == "duration_after_vad" else "max_segment_temperature"]
        is None
    )


def test_thread_isolation_and_same_thread_reset(monkeypatch):
    runtime = module.FasterWhisperRuntime(device="cpu", live=True)
    barrier = Barrier(2)

    def transcribe(source, **kwargs):
        from threading import current_thread

        value = 0.2 if current_thread().name.endswith("_0") else 0.8
        barrier.wait(timeout=5)
        return [segment(temperature=value)], SimpleNamespace(duration_after_vad=value)

    runtime._model = SimpleNamespace(transcribe=transcribe)

    def work():
        assert metrics(runtime) is None
        list(runtime.transcribe([chunk()]))
        result = metrics(runtime)
        barrier.wait(timeout=5)
        assert metrics(runtime) == result
        list(runtime.transcribe([]))
        assert metrics(runtime) is None
        return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(work) for _ in range(2)]
        results = [f.result(timeout=10) for f in futures]
    assert sorted(r["duration_after_vad"] for r in results) == [0.2, 0.8]
    assert metrics(runtime) is None


def test_lazy_generator_failure_retains_only_current_decode(monkeypatch):
    runtime = module.FasterWhisperRuntime(device="cpu", live=True)
    error = RuntimeError("lazy decode")

    def segments():
        yield segment(temperature=0.4)
        raise error

    runtime._model = SimpleNamespace(transcribe=lambda *a, **k: (segments(), None))
    with pytest.raises(RuntimeError) as caught:
        list(runtime.transcribe([chunk()]))
    assert caught.value is error
    assert metrics(runtime)["max_segment_temperature"] == 0.4
    assert metrics(runtime)["duration_after_vad"] is None
