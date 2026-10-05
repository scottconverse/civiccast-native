# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors


from civiccast.captions.models import AudioChunk
from civiccast.captions.whistle import WhistleRuntime


def chunk(channel="public", index=1):
    return AudioChunk(
        chunk_id=f"{channel}-tap-{index:06d}",
        start_seconds=100,
        end_seconds=110,
        sample_rate_hz=16000,
        pcm_s16le=b"\0" * 320000,
    )


class Worker:
    def __init__(self, engine, calls, fail=False):
        self.engine, self.calls, self.fail = engine, calls, fail
        self.closed = False

    def request(self, audio, vocabulary):
        self.calls.append((self.engine, audio.chunk_id, audio.pcm_s16le, vocabulary))
        if self.fail:
            raise TimeoutError("blocked native call")
        if self.engine == "whisper":
            return [
                {
                    "source_id": audio.chunk_id,
                    "start_seconds": 100.5,
                    "end_seconds": 102,
                    "text": "fallback words",
                    "audio_window_start_seconds": 100,
                    "audio_window_end_seconds": 110,
                }
            ]
        return {
            "text": "five to two",
            "words": [
                {"word": "five", "start": 0.5, "end": 1, "probability": 0.9},
                {"word": "to", "start": 1, "end": 1.2, "probability": 0.9},
                {"word": "two", "start": 1.2, "end": 2, "probability": 0.9},
            ],
        }

    def close(self):
        self.closed = True


def runtime(tmp_path, *, fail=False, response=None):
    calls, workers = [], []

    def factory(engine):
        worker = Worker(engine, calls, fail and engine == "whistle")
        if response is not None and engine == "whistle":
            worker.request = lambda *_: response
        workers.append(worker)
        return worker

    return (
        WhistleRuntime(
            weights=tmp_path / "whistle.cact",
            library=tmp_path / "libneedle.dll",
            fallback_config={},
            worker_factory=factory,
        ),
        calls,
        workers,
    )


def test_word_times_become_absolute_without_losing_audio_provenance(tmp_path):
    r, _calls, _ = runtime(tmp_path)
    result = list(r.transcribe([chunk()]))
    assert len(result) == 1
    assert result[0].text == "five to two"
    assert result[0].words[0].start_seconds == 100.5
    assert result[0].words[-1].end_seconds == 102
    assert result[0].audio_window_start_seconds == 100
    assert result[0].audio_window_end_seconds == 110


def test_failure_replays_exact_audio_once_then_stays_on_fallback(tmp_path):
    r, calls, workers = runtime(tmp_path, fail=True)
    first = list(r.transcribe([chunk()]))
    second = list(r.transcribe([chunk(index=2)]))
    assert first[0].text == second[0].text == "fallback words"
    assert [c[0] for c in calls] == ["whistle", "whisper", "whisper"]
    assert calls[0][2] == calls[1][2]
    assert workers[0].closed


def test_a_failed_channel_does_not_disable_another_channel(tmp_path):
    r, calls, _workers = runtime(tmp_path, fail=True)
    list(r.transcribe([chunk()]))
    list(r.transcribe([chunk("government")]))
    assert [c[0] for c in calls] == ["whistle", "whisper", "whistle", "whisper"]


def test_silence_returns_no_hypotheses_or_fallback(tmp_path):
    r, _calls, _ = runtime(tmp_path, response={"text": "", "words": []})
    assert list(r.transcribe([chunk()])) == []


def test_invalid_native_word_time_triggers_fallback(tmp_path):
    r, calls, _ = runtime(
        tmp_path,
        response={
            "text": "bad",
            "words": [{"word": "bad", "start": 0, "end": 100, "probability": 1}],
        },
    )
    assert next(iter(r.transcribe([chunk()]))).text == "fallback words"
    assert calls[-1][0] == "whisper"


def test_close_reaps_all_created_workers(tmp_path):
    r, _, workers = runtime(tmp_path)
    list(r.transcribe([chunk()]))
    list(r.transcribe([chunk("government")]))
    r.close()
    assert workers and all(w.closed for w in workers)


def test_isolated_primary_allows_three_channel_dispatch(tmp_path):
    from civiccast.captions.tap_worker import default_max_channel_workers

    r, _, _ = runtime(tmp_path)
    assert not r.on_cuda()
    assert default_max_channel_workers(r) == 3


def test_native_live_factory_selects_whistle_but_batch_stays_whisper(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from civiccast.ai_models.runtime import build_caption_runtime
    from civiccast.captions.runtime import FasterWhisperRuntime

    monkeypatch.setenv("CIVICCAST_NATIVE_STATION", "1")
    monkeypatch.setenv("CIVICCAST_WHISTLE_ROOT", str(tmp_path))
    monkeypatch.delenv("CIVICCAST_WHISPER_MODEL_PATH", raising=False)
    # The fallback constructor retains its already-tested packaged-model checks;
    # exercise the selection seam without pretending dummy files are a model.
    monkeypatch.setattr(
        FasterWhisperRuntime,
        "__init__",
        lambda self, **kw: self.__dict__.update(
            model_size_or_path="medium",
            device="cpu",
            compute_type="int8",
            cpu_threads=1,
            num_workers=1,
            beam_size=1,
            language="en",
            task="transcribe",
            vad_filter=True,
        ),
    )
    service = SimpleNamespace(effective_model_tag=lambda feature: "whisper-medium")
    assert isinstance(build_caption_runtime(service, live=True), WhistleRuntime)
    assert isinstance(build_caption_runtime(service), FasterWhisperRuntime)


def test_unavailable_primary_assets_still_prewarm_and_use_fallback(tmp_path):
    r, calls, _workers = runtime(tmp_path)
    r.prepare()
    result = list(r.transcribe([chunk()]))
    assert result[0].text == "fallback words"
    assert [c[0] for c in calls] == ["whisper"]
    r.close()


def test_close_during_primary_request_refuses_late_results(tmp_path):
    import threading

    import pytest

    r, _, workers = runtime(tmp_path)
    list(r.transcribe([chunk()]))
    entered, release = threading.Event(), threading.Event()
    original = workers[0].request

    def blocked(*args):
        entered.set()
        assert release.wait(3)
        return original(*args)

    workers[0].request = blocked
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(lambda: list(r.transcribe([chunk(index=2)])))
        assert entered.wait(3)
        r.close()
        release.set()
        with pytest.raises(RuntimeError, match="closed"):
            future.result(timeout=3)
    assert all(w.closed for w in workers)


def test_failed_fallback_replays_retained_window_to_one_replacement(tmp_path):
    calls, workers = [], []

    def factory(engine):
        fail = engine == "whistle" or not any(w.engine == "whisper" for w in workers)
        w = Worker(engine, calls, fail)
        workers.append(w)
        return w

    r = WhistleRuntime(
        weights=tmp_path / "w", library=tmp_path / "l", fallback_config={}, worker_factory=factory
    )
    assert next(iter(r.transcribe([chunk()]))).text == "fallback words"
    assert [c[0] for c in calls] == ["whistle", "whisper", "whisper"]
    assert all(c[1:3] == calls[0][1:3] for c in calls)
    r.close()
    assert all(w.closed for w in workers)


def test_shutdown_during_primary_creation_reaps_late_child(tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    import pytest

    entered, release = threading.Event(), threading.Event()
    workers = []

    def factory(engine):
        w = Worker(engine, [])
        workers.append(w)
        entered.set()
        assert release.wait(3)
        return w

    r = WhistleRuntime(
        weights=tmp_path / "w", library=tmp_path / "l", fallback_config={}, worker_factory=factory
    )
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(lambda: list(r.transcribe([chunk()])))
        assert entered.wait(3)
        r.close()
        release.set()
        with pytest.raises(RuntimeError, match="closed"):
            future.result(timeout=3)
    assert all(w.closed for w in workers)


def test_concurrent_child_close_releases_job_once(monkeypatch):
    import tempfile
    import threading
    from concurrent.futures import ThreadPoolExecutor

    import win32job

    from civiccast.captions.whistle import _SpeechProcess

    class Job:
        closed = 0

        def Close(self):
            self.closed += 1

    job = Job()
    entered, release = threading.Event(), threading.Event()

    def terminate(handle, code):
        assert handle is job
        entered.set()
        assert release.wait(3)

    monkeypatch.setattr(win32job, "TerminateJobObject", terminate)
    child = object.__new__(_SpeechProcess)
    child._job, child._process, child._closed = job, None, False
    child._close_lock = threading.Lock()
    child._stderr = tempfile.TemporaryFile()  # noqa: SIM115 -- child.close owns this handle
    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(child.close)
        assert entered.wait(3)
        b = pool.submit(child.close)
        release.set()
        a.result(timeout=3)
        b.result(timeout=3)
    assert job.closed == 1 and child._stderr.closed


def test_runtime_cleanup_continues_if_one_worker_cleanup_raises(tmp_path):
    r, _, workers = runtime(tmp_path)
    list(r.transcribe([chunk()]))
    list(r.transcribe([chunk("government")]))

    def broken():
        raise OSError("injected cleanup failure")

    workers[0].close = broken
    r.close()
    assert workers[1].closed


def test_audio_send_to_blocked_child_is_deadline_bounded():
    import threading
    from types import SimpleNamespace

    import pytest

    from civiccast.captions.whistle import _SpeechProcess

    released = threading.Event()

    class BlockedInput:
        def write(self, value):
            assert released.wait(3)

        def flush(self):
            pass

    child = object.__new__(_SpeechProcess)
    child._lock = threading.Lock()
    child._closed, child._sequence, child._timeout = False, 0, 0.05
    child._process = SimpleNamespace(stdin=BlockedInput())
    child.close = released.set
    with pytest.raises(TimeoutError, match="input deadline"):
        child.request(chunk(), None)
    assert released.is_set()


def test_station_serializes_native_whistle_inference(tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    first_entered, second_entered, release = threading.Event(), threading.Event(), threading.Event()
    r, _, _ = runtime(tmp_path)

    def factory(engine):
        worker = Worker(engine, [])
        original = worker.request

        def request(audio, vocabulary):
            if audio.chunk_id.startswith("public"):
                first_entered.set()
                assert release.wait(3)
            else:
                second_entered.set()
            return original(audio, vocabulary)

        worker.request = request
        return worker

    r._factory = factory
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(lambda: list(r.transcribe([chunk()])))
        assert first_entered.wait(3)
        second = pool.submit(lambda: list(r.transcribe([chunk("government")])))
        overlapping = second_entered.wait(0.15)
        release.set()
        first.result(timeout=3)
        second.result(timeout=3)
    r.close()
    assert not overlapping, "two native Whistle calls ran concurrently"


def test_delivery_fallback_selects_same_window_before_stabilization(tmp_path):
    r, calls, workers = runtime(tmp_path)
    for index, start in enumerate((100, 105, 110, 115), 1):
        audio = chunk(index=index).model_copy(
            update={"start_seconds": start, "end_seconds": start + 10}
        )
        native = list(r.transcribe([audio]))
        selected = r.prepare_stabilization([audio], native)
        assert selected[0].text == "five to two"
        r.note_caption_commits([audio], [])
    audio = chunk(index=5).model_copy(update={"start_seconds": 120, "end_seconds": 130})
    native = list(r.transcribe([audio]))
    selected = r.prepare_stabilization([audio], native)
    assert selected[0].text == "fallback words"
    assert calls[-1][0] == "whisper" and calls[-1][1:3] == calls[-2][1:3]
    assert workers[0].closed
    assert "public" in r._failed and "government" not in r._failed
    r.close()


def test_delivery_watch_resets_on_silence_or_committed_cue(tmp_path):
    r, _, _ = runtime(tmp_path)
    audio = chunk()
    native = list(r.transcribe([audio]))
    r.prepare_stabilization([audio], native)
    assert r._delivery_watch
    r.prepare_stabilization(
        [audio.model_copy(update={"start_seconds": 110, "end_seconds": 120})], []
    )
    assert not r._delivery_watch
    current = audio.model_copy(update={"start_seconds": 120, "end_seconds": 130})
    r.prepare_stabilization([current], native)
    r.note_caption_commits([current], [object()])
    assert not r._delivery_watch
    r.close()


def test_pipeline_replay_votes_once_and_preserves_two_window_confirmation(tmp_path):
    from civiccast.captions.models import CaptionHypothesis, CaptionWord
    from civiccast.captions.pipeline import CaptionPipeline
    from civiccast.captions.stabilize import CaptionStabilizer

    r, _, _ = runtime(tmp_path)
    original = r._factory

    def factory(engine):
        w = original(engine)
        if engine == "whisper":

            def request(audio, vocabulary):
                return [
                    CaptionHypothesis(
                        source_id=audio.chunk_id,
                        start_seconds=127,
                        end_seconds=129,
                        text="fallback words",
                        words=[
                            CaptionWord(
                                text="fallback", start_seconds=127, end_seconds=128, confidence=1
                            ),
                            CaptionWord(
                                text="words", start_seconds=128, end_seconds=129, confidence=1
                            ),
                        ],
                        audio_window_start_seconds=audio.start_seconds,
                        audio_window_end_seconds=audio.end_seconds,
                    ).model_dump()
                ]

            w.request = request
        return w

    r._factory = factory
    pipeline = CaptionPipeline(r, stabilizer=CaptionStabilizer(live=True))
    results = []
    for index, start in enumerate((100, 105, 110, 115, 120), 1):
        audio = chunk(index=index).model_copy(
            update={"start_seconds": start, "end_seconds": start + 10}
        )
        result = pipeline.process([audio], asset_id="public")
        results.append(result)
    assert results[-1].hypotheses[0].text == "fallback words"
    assert not results[-1].committed_cues
    assert not pipeline.process([audio], asset_id="public").committed_cues
    next_audio = chunk(index=6).model_copy(update={"start_seconds": 125, "end_seconds": 135})
    confirmed = pipeline.process([next_audio], asset_id="public").committed_cues
    assert len(confirmed) == 1 and confirmed[0].text == "fallback words"
    r.close()


def test_new_channel_pipeline_rearms_watch_after_timestamp_reset(tmp_path):
    from civiccast.captions.pipeline import CaptionPipeline
    r, _, _ = runtime(tmp_path)
    old = chunk().model_copy(update={"start_seconds": 1000, "end_seconds": 1010})
    r.prepare_stabilization([old], list(r.transcribe([old])))
    r._failed.add("education")
    CaptionPipeline(r, phase_timing_channel="public")
    assert "public" not in r._delivery_last_end
    assert "education" in r._failed
    for index, start in enumerate((0, 5, 10, 15, 20), 1):
        audio = chunk(index=index).model_copy(update={"start_seconds": start, "end_seconds": start+10})
        selected = r.prepare_stabilization([audio], list(r.transcribe([audio])))
    assert selected[0].text == "fallback words" and "public" in r._failed
    r.close()
