# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Isolated Whistle live transcription with sticky Whisper fallback."""

from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import logging
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping
from pathlib import Path
from typing import IO, Any, Protocol, cast

from civiccast.captions.models import AudioChunk, CaptionHypothesis, CaptionWord, CustomVocabulary
from civiccast.captions.runtime import CaptionRuntime

_LOG = logging.getLogger(__name__)
WEIGHTS_SHA256 = "b6e02f048568ac5d01a2042556c658061e699acbc0aa2a1439f52f3d461dffeb"
LIBRARY_SHA256 = "de2e2c39cd311fbd9971fad4736abc329ed970653674c203e149c4ef27fd1c62"


class _SpeechWorker(Protocol):
    def request(self, chunk: AudioChunk, vocabulary: CustomVocabulary | None) -> object: ...

    def close(self) -> None: ...


class _PreparedCaptionRuntime(CaptionRuntime, Protocol):
    def on_cuda(self) -> bool: ...

    def prepare(self) -> None: ...


class _CloseableCaptionRuntime(_PreparedCaptionRuntime, Protocol):
    def close(self) -> None: ...


class _SpeechProcess:
    """Fixed child protocol; assign a suspended child before native loading."""

    def __init__(
        self,
        engine: str,
        weights: Path,
        library: Path,
        fallback_config: Mapping[str, object],
        timeout: float = 10.0,
    ) -> None:
        if os.name != "nt":
            raise RuntimeError("Whistle's pinned native engine requires Windows")
        import uuid

        import psutil
        import pywintypes
        import win32api
        import win32job
        import win32process
        import win32security

        self._timeout = timeout
        self._lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._responses: queue.Queue[dict[str, object]] = queue.Queue(maxsize=1)
        self._sequence = 0
        self._process: subprocess.Popen[str] | None = None
        self._job: Any | None = None
        self._stderr = tempfile.TemporaryFile()  # noqa: SIM115 -- owned across requests; close() releases it
        self._closed = False
        try:
            token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), 8)
            try:
                sid = win32security.ConvertSidToStringSid(
                    win32security.GetTokenInformation(token, win32security.TokenUser)[0]
                )
            finally:
                token.Close()
            security = pywintypes.SECURITY_ATTRIBUTES()
            security.bInheritHandle = False
            security.SECURITY_DESCRIPTOR = (
                win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
                    f"D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GA;;;{sid})", 1
                )
            )
            self._job = win32job.CreateJobObject(security, "CivicCastSpeech-" + uuid.uuid4().hex)
            limits = win32job.QueryInformationJobObject(
                self._job, win32job.JobObjectExtendedLimitInformation
            )
            flags = (
                win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                | win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY
                | win32job.JOB_OBJECT_LIMIT_JOB_MEMORY
            )
            limits["BasicLimitInformation"]["LimitFlags"] = flags
            cap = (1 if engine == "whistle" else 4) << 30
            limits["ProcessMemoryLimit"] = cap
            limits["JobMemoryLimit"] = cap
            win32job.SetInformationJobObject(
                self._job, win32job.JobObjectExtendedLimitInformation, limits
            )
            readback = win32job.QueryInformationJobObject(
                self._job, win32job.JobObjectExtendedLimitInformation
            )
            if (
                readback["ProcessMemoryLimit"] != cap
                or readback["JobMemoryLimit"] != cap
                or readback["BasicLimitInformation"]["LimitFlags"] != flags
            ):
                raise RuntimeError("speech child memory limits did not read back")
            # pywin32 311 does not expose CPU rate control. Use the two-field
            # Windows structure directly, retaining typed handles on 64-bit Windows.
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            for name in ("SetInformationJobObject", "QueryInformationJobObject"):
                fn = getattr(kernel, name)
                fn.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong] + (
                    [ctypes.c_void_p] if name.startswith("Query") else []
                )
                fn.restype = ctypes.c_int
            cpu = (ctypes.c_ulong * 2)(5, 2500)
            if not kernel.SetInformationJobObject(
                int(self._job), 15, ctypes.byref(cpu), ctypes.sizeof(cpu)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            read_cpu = (ctypes.c_ulong * 2)()
            if not kernel.QueryInformationJobObject(
                int(self._job), 15, ctypes.byref(read_cpu), ctypes.sizeof(read_cpu), None
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            if list(read_cpu) != [5, 2500]:
                raise RuntimeError("speech child CPU cap did not read back")
            env = dict(
                os.environ,
                NEEDLE_TELEMETRY="0",
                DO_NOT_TRACK="1",
                HF_HUB_OFFLINE="1",
                OMP_NUM_THREADS="1",
            )
            # Ensure a source candidate and an installed payload each use their own code.
            env["PYTHONPATH"] = (
                str(Path(__file__).resolve().parents[2]) + os.pathsep + env.get("PYTHONPATH", "")
            )
            argv = [
                sys.executable,
                "-m",
                "civiccast.captions.whistle_worker",
                engine,
                str(weights),
                str(library),
                json.dumps(fallback_config),
            ]
            process = subprocess.Popen(  # noqa: S603 -- fixed module/arguments, no shell or user command
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._stderr,
                text=True,
                encoding="utf8",
                env=env,
                creationflags=0x4 | 0x08000000 | 0x4000,
            )
            self._process = process
            process_handle = win32api.OpenProcess(0x501, False, process.pid)
            try:
                win32job.AssignProcessToJobObject(self._job, process_handle)
                if not win32job.IsProcessInJob(process_handle, self._job):
                    raise RuntimeError("speech child job membership unproven")
                threads = psutil.Process(process.pid).threads()
                if len(threads) != 1:
                    raise RuntimeError("suspended child has an unexpected thread count")
                thread_handle = win32api.OpenThread(2, False, threads[0].id)
                try:
                    win32process.ResumeThread(thread_handle)
                finally:
                    thread_handle.Close()
            finally:
                process_handle.Close()
            threading.Thread(target=self._read, daemon=True, name="caption-child-response").start()
            ready = self._receive(30)
            if ready.get("ready") != engine:
                raise RuntimeError(f"speech child failed startup: {ready}")
            _LOG.info(
                "Caption child ready: engine=%s pid=%s cap_bytes=%s device=%s",
                engine,
                process.pid,
                cap,
                ready.get("device"),
            )
        except BaseException:
            self.close()
            raise

    def _read(self) -> None:
        try:
            process = cast(subprocess.Popen[str], self._process)
            stdout = cast(IO[str], process.stdout)
            while not self._closed:
                line = stdout.readline(2 << 20)
                if not line:
                    self._responses.put({"error": "speech child exited"})
                    return
                self._responses.put(json.loads(line))
        except Exception as exc:
            if not self._closed:
                self._responses.put({"error": str(exc)})

    def _receive(self, timeout: float) -> dict[str, object]:
        try:
            result = self._responses.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError("isolated speech child missed its deadline") from exc
        if "error" in result:
            raise RuntimeError(result["error"])
        return result

    def request(self, chunk: AudioChunk, vocabulary: CustomVocabulary | None) -> object:
        with self._lock:
            if self._closed:
                raise RuntimeError("speech child is closed")
            self._sequence += 1
            request: dict[str, object] = {
                "id": self._sequence,
                "chunk": chunk.model_dump(exclude={"pcm_s16le"}),
                "pcm": base64.b64encode(chunk.pcm_s16le).decode("ascii"),
                "vocabulary": vocabulary.model_dump() if vocabulary else None,
            }
            try:
                deadline = time.monotonic() + self._timeout
                sent, errors = threading.Event(), []

                def send() -> None:
                    try:
                        process = cast(subprocess.Popen[str], self._process)
                        stdin = cast(IO[str], process.stdin)
                        stdin.write(json.dumps(request) + "\n")
                        stdin.flush()
                    except Exception as exc:
                        errors.append(exc)
                    finally:
                        sent.set()

                threading.Thread(target=send, daemon=True, name="caption-child-input").start()
                if not sent.wait(self._timeout):
                    raise TimeoutError("isolated speech child missed its input deadline")
                if errors:
                    raise errors[0]
                result = self._receive(max(0.001, deadline - time.monotonic()))
                if result.get("id") != self._sequence:
                    raise RuntimeError("speech child response identity mismatch")
                return result["result"]
            except BaseException:
                self.close()
                raise

    def close(self) -> None:
        # Independent of the request lock: shutdown must interrupt a stuck call.
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            job, self._job = self._job, None
            try:
                if job is not None:
                    import win32job

                    try:
                        win32job.TerminateJobObject(job, 1)
                    finally:
                        job.Close()
            finally:
                try:
                    if self._process is not None:
                        if self._process.poll() is None:
                            self._process.kill()
                        self._process.wait(timeout=3)
                        for pipe in (self._process.stdin, self._process.stdout):
                            if pipe:
                                pipe.close()
                finally:
                    self._stderr.close()


class WhistleRuntime:
    """Per-channel primary isolation; replay a failed window once to Whisper.

    Fallback is sticky until runtime restart. It never retries a failing native
    engine or emits partially decoded primary results before deciding fallback.
    """

    channel_workers = 3
    device = "cpu"
    compute_type = "cactus-quants"
    num_workers = 3

    def __init__(
        self,
        *,
        weights: Path,
        library: Path,
        fallback_config: Mapping[str, object],
        worker_factory: Callable[[str], _SpeechWorker] | None = None,
    ) -> None:
        self.weights, self.library = Path(weights), Path(library)
        self._factory = worker_factory or (
            lambda engine: _SpeechProcess(engine, self.weights, self.library, fallback_config)
        )
        self._primaries: dict[str, _SpeechWorker] = {}
        self._fallback: _SpeechWorker | None = None
        self._failed: set[str] = set()
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.RLock()
        self._fallback_lock = threading.Lock()
        self._primary_lock = threading.Lock()
        self._closed = False
        self._primary_error: str | None = None
        self._fallback_restarts = 0

    def on_cuda(self) -> bool:
        return False  # Whistle itself is always CPU, regardless of fallback.

    def prepare(self) -> None:
        self._fallback_worker()
        for path, digest in ((self.weights, WEIGHTS_SHA256), (self.library, LIBRARY_SHA256)):
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                self._primary_error = f"Pinned Whistle asset missing or changed: {path}"
                _LOG.warning("%s; live captions will use Whisper", self._primary_error)
                return

    def _fallback_worker(self) -> _SpeechWorker:
        with self._guard:
            if self._closed:
                raise RuntimeError("caption runtime has been closed")
            if self._fallback is None:
                self._fallback = self._factory("whisper")
            return self._fallback

    def _fallback_request(self, chunk: AudioChunk, vocabulary: CustomVocabulary | None) -> object:
        with self._fallback_lock:
            try:
                return self._fallback_worker().request(chunk, vocabulary)
            except Exception:
                with self._guard:
                    if self._closed or self._fallback_restarts >= 1:
                        _LOG.critical(
                            "Whisper fallback unavailable; caption runtime restart required"
                        )
                        raise
                    self._fallback_restarts += 1
                    if self._fallback:
                        self._fallback.close()
                    self._fallback = None
                _LOG.error(
                    "Whisper fallback failed; replaying retained audio once to its bounded replacement"
                )
                return self._fallback_worker().request(chunk, vocabulary)

    def _primary_request(
        self, channel: str, chunk: AudioChunk, vocabulary: CustomVocabulary | None
    ) -> object:
        # Serialize station-wide native recognition after the concurrent
        # three-station run exceeded the request deadline and lost queued audio.
        # This does not require transcript agreement before captions can air.
        with self._primary_lock:
            with self._guard:
                if self._is_closed():
                    raise RuntimeError("caption runtime has been closed")
                primary = self._primaries.get(channel)
            if primary is None:
                created = self._factory("whistle")
                with self._guard:
                    if self._closed:
                        created.close()
                        raise RuntimeError("caption runtime has been closed")
                    self._primaries[channel] = primary = created
                    _LOG.info(
                        "Whistle primary active: channel=%s pid=%s",
                        channel,
                        getattr(getattr(created, "_process", None), "pid", "n/a"),
                    )
            started = time.monotonic()
            try:
                result = primary.request(chunk, vocabulary)
            except Exception:
                _LOG.warning(
                    "Whistle inference failed: channel=%s seconds=%.3f",
                    channel,
                    time.monotonic() - started,
                )
                raise
            _LOG.info(
                "Whistle inference completed: channel=%s chunk=%s seconds=%.3f",
                channel,
                chunk.chunk_id,
                time.monotonic() - started,
            )
            return result

    def transcribe(
        self,
        chunks: Iterable[AudioChunk],
        vocabulary: CustomVocabulary | None = None,
    ) -> Iterator[CaptionHypothesis]:
        for chunk in chunks:
            if (
                chunk.sample_rate_hz != 16000
                or not 0 < len(chunk.pcm_s16le) <= 960000
                or len(chunk.pcm_s16le) % 2
            ):
                raise ValueError("Whistle requires <=30 seconds of mono 16 kHz s16le PCM")
            channel = chunk.chunk_id.rsplit("-tap-", 1)[0]
            with self._guard:
                if self._closed:
                    raise RuntimeError("caption runtime has been closed")
                lock = self._locks.setdefault(channel, threading.Lock())
                if len(self._locks) > self.channel_workers:
                    raise RuntimeError("Whistle live runtime supports at most three channels")
            with lock:
                try:
                    if self._primary_error:
                        raise RuntimeError(self._primary_error)
                    if channel in self._failed:
                        raise RuntimeError("primary previously failed")
                    payload = self._primary_request(channel, chunk, vocabulary)
                    results = _hypotheses(chunk, payload)
                except Exception as exc:
                    if channel not in self._failed:
                        _LOG.warning(
                            "Whistle failed for %s; switching to Whisper: %s", channel, exc
                        )
                        self._failed.add(channel)
                        worker = self._primaries.pop(channel, None)
                        if worker is not None:
                            worker.close()
                    with self._guard:
                        if self._closed:
                            raise RuntimeError("caption runtime has been closed") from exc
                    payload = self._fallback_request(chunk, vocabulary)
                    fallback_hypotheses = cast(list[dict[str, object]], payload)
                    results = [
                        CaptionHypothesis.model_validate(result) for result in fallback_hypotheses
                    ]
                with self._guard:
                    if self._closed:
                        raise RuntimeError("caption runtime has been closed")
                    yield from results

    def _is_closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        with self._guard:
            self._closed = True
            workers = list(self._primaries.values()) + ([self._fallback] if self._fallback else [])
            self._primaries.clear()
            self._fallback = None
        for worker in workers:
            try:
                worker.close()
            except Exception:
                _LOG.exception("Speech child cleanup failed; continuing remaining child cleanup")


class MixedCaptionRuntime:
    """Keep ordinary Whisper channels on their existing live runtime."""

    channel_workers = 3
    num_workers = 3
    device = "mixed"
    compute_type = "mixed"

    def __init__(
        self,
        whistle: _CloseableCaptionRuntime,
        whisper: _PreparedCaptionRuntime,
        whistle_channels: Collection[str],
    ) -> None:
        if not whistle_channels or len(whistle_channels) > 3:
            raise ValueError("Select between one and three Whistle channels")
        self._whistle = whistle
        self._whisper = whisper
        self._whistle_channels = frozenset(whistle_channels)
        self._whisper_lock = threading.Lock()
        self._closed = False

    def on_cuda(self) -> bool:
        return self._whisper.on_cuda()

    def prepare(self) -> None:
        if self._closed:
            raise RuntimeError("caption runtime has been closed")
        self._whisper.prepare()
        self._whistle.prepare()
        _LOG.info(
            "Mixed live captions: Whistle channels=%s; other channels use existing Whisper",
            sorted(self._whistle_channels),
        )

    def transcribe(
        self,
        chunks: Iterable[AudioChunk],
        vocabulary: CustomVocabulary | None = None,
    ) -> Iterator[CaptionHypothesis]:
        if self._closed:
            raise RuntimeError("caption runtime has been closed")
        for chunk in chunks:
            channel = chunk.chunk_id.rsplit("-tap-", 1)[0]
            if channel in self._whistle_channels:
                yield from self._whistle.transcribe([chunk], vocabulary)
            elif self._whisper.on_cuda():
                yield from self._whisper.transcribe([chunk], vocabulary)
            else:
                # Preserve the tap's original single-call CPU safety profile.
                with self._whisper_lock:
                    yield from self._whisper.transcribe([chunk], vocabulary)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._whistle.close()


def _hypotheses(chunk: AudioChunk, payload: object) -> list[CaptionHypothesis]:
    typed_payload = cast(Mapping[str, object], payload)
    text = cast(str, typed_payload.get("text", ""))
    if not text.strip():
        return []
    raw_words = cast(list[Mapping[str, object]], typed_payload.get("words", []))
    words: list[CaptionWord] = []
    duration = len(chunk.pcm_s16le) / 32000
    for raw in raw_words:
        start, end = float(cast(float, raw["start"])), float(cast(float, raw["end"]))
        if not 0 <= start <= end <= duration + 0.08:
            raise ValueError("Whistle word timestamp is outside its audio window")
        raw_text = cast(str, raw["word"])
        words.append(
            CaptionWord(
                text=raw_text.strip(),
                start_seconds=chunk.start_seconds + start,
                end_seconds=chunk.start_seconds + end,
                confidence=cast(float, raw.get("probability", 1)),
            )
        )
    return [
        CaptionHypothesis(
            source_id=chunk.chunk_id,
            start_seconds=words[0].start_seconds if words else chunk.start_seconds,
            end_seconds=max(words[-1].end_seconds, words[0].start_seconds + 0.001)
            if words
            else chunk.end_seconds,
            text=text,
            confidence=sum(w.confidence for w in words) / len(words) if words else 1.0,
            words=words,
            audio_window_start_seconds=chunk.start_seconds,
            audio_window_end_seconds=chunk.end_seconds,
        )
    ]
