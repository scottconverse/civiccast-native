# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Runtime adapter boundary for CivicCast caption engines."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import wave
from collections.abc import Iterable
from math import exp
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Protocol

from civiccast.captions.models import AudioChunk, CaptionHypothesis, CustomVocabulary
from civiccast.native.caption_tiers import (
    CAPTION_TIER_REGISTRY,
    LARGE_V3_TIER_ID,
    CaptionTierBindingError,
    CaptionTierSpec,
)

logger = logging.getLogger(__name__)

#: Kept-alive `os.add_dll_directory` handles, keyed by the directory string
#: already registered -- makes :func:`_ensure_cuda_dll_directory` idempotent
#: per directory (a repeat call for the same directory is a no-op) and, per
#: the stdlib's own contract for `os.add_dll_directory`, keeps each returned
#: `_AddedDllDirectory` handle referenced for the life of the process:
#: letting it get garbage-collected removes the search path it added. Same
#: kept-alive-handle shape as `civiccast.native.gstreamer_runtime`'s own
#: module-level `_DLL_HANDLES`, which solved the identical problem for the
#: staged GStreamer DLLs.
_CUDA_DLL_DIRECTORY_HANDLES: dict[str, object] = {}


def _ensure_cuda_dll_directory() -> None:
    """Register the staged CUDA runtime DLL directory with the Windows
    loader before a cuda-device model load.

    TESTER4 (RTX 5070 Ti), real hardware: with both required DLLs staged
    AND on PATH, faster-whisper's CUDA backend still failed to load them.
    Consistent with a documented Windows/CPython behavior: since Python
    3.8, the loader no longer searches PATH to resolve a DLL's own
    dependent DLLs -- only directories added via `os.add_dll_directory`
    (or a handful of fixed system locations) are searched for THAT. PATH
    alone (`CIVICCAST_WHISPER_DEVICE=cuda`'s PATH prepend in
    `civiccast.native.station_runtime.load_native_station_environment`) is
    therefore necessary for non-Python consumers but not sufficient for
    this one -- the exact problem
    `civiccast.native.gstreamer_runtime.bootstrap_installed_gstreamer_runtime`
    already solved for the staged GStreamer DLLs, via the same fix mirrored
    here: `os.add_dll_directory` with a kept-alive handle.

    Reads `CIVICCAST_CUDA_BIN_DIR` (set by `load_native_station_environment`
    only when cuda was actually selected, alongside the PATH prepend) rather
    than deriving a path itself -- one producer, never a second copy of the
    resolution logic. A no-op when: the variable is unset (cpu selected, or
    an environment station_runtime never touched); the staged directory does
    not exist; this is not Windows; or `os.add_dll_directory` is unavailable
    (any non-Windows CPython). Never raises -- a missing/stale directory here
    is reported by the existing cuda-load-failure fallback in
    `FasterWhisperRuntime._model_instance`, not by this helper.

    Guard order is DELIBERATE: the two platform-independent checks (env var
    set, directory exists) run FIRST, and the two Windows-only checks
    (`os.name`, `os.add_dll_directory`) run LAST. A platform-only guard
    placed first would short-circuit every other check behind it, so a test
    for "no-op when the env var is unset" or "no-op when the directory is
    missing" could pass on a real Windows host for the WRONG reason -- it
    never got far enough to exercise the check it claims to test -- while
    silently masking the same test failing everywhere else. Checking the
    OS-independent conditions first means those tests exercise the same code
    path on every CI runner, Windows or not.
    """

    cuda_bin_dir = os.environ.get("CIVICCAST_CUDA_BIN_DIR", "").strip()
    if not cuda_bin_dir or cuda_bin_dir in _CUDA_DLL_DIRECTORY_HANDLES:
        return
    if not Path(cuda_bin_dir).is_dir():
        return
    if os.name != "nt":
        return
    add_dll_directory = getattr(os, "add_dll_directory", None)
    if add_dll_directory is None:
        return
    _CUDA_DLL_DIRECTORY_HANDLES[cuda_bin_dir] = add_dll_directory(cuda_bin_dir)


#: Environment variable through which an activated native station DECLARES
#: which caption tier it selected. Written by
#: ``civiccast.native.station_runtime.station_environment`` next to
#: ``CIVICCAST_WHISPER_MODEL_PATH``, so on a real station the tier backing a
#: packaged model path is always explicit -- never inferred, per
#: ``OWNER-DECISION-caption-adaptive-tier.md`` ("tier selection must be
#: explicit, logged, provable").
CAPTION_TIER_ENV_VAR = "CIVICCAST_CAPTION_TIER"

#: CTranslate2 ``intra_threads`` for the LIVE caption tap on CPU.
#:
#: The live tap shares its box with playout, and playout is the product. The
#: batch/VOD default of ``0`` ("every core") produced the measured field
#: failure this constant exists to prevent: on tester DESKTOP-VBMA6O5 with
#: three channels ON_AIR and no CUDA, the control plane burned ~247% of a core
#: transcribing audio the tap's own overload handling then discarded, while
#: the three GStreamer playout workers were repeatedly killed by their
#: 10-second no-output stall watchdog.
#:
#: One thread, times the tap's own bound of one concurrently-transcribing
#: channel per 8 CPUs
#: (:func:`civiccast.captions.tap_worker.default_max_channel_workers`), is a
#: whole-feature steady-state budget of about one core on the 8-core field
#: station. ``CIVICCAST_WHISPER_CPU_THREADS`` raises it on a station with
#: headroom (``0`` restores "every core").
LIVE_TAP_CPU_THREADS = 1

#: Greedy decoding for the live tap on CPU: beam search costs roughly its
#: width in decoder passes, and the live tap has a hard real-time budget that
#: a VOD pass does not. Overridable with ``CIVICCAST_WHISPER_BEAM_SIZE``.
LIVE_TAP_CPU_BEAM_SIZE = 1

#: Files a tier's pinned inventory carries for PROVENANCE rather than for
#: inference: CTranslate2/faster-whisper never opens them, and an upstream
#: snapshot may legitimately omit them (the pinned ``medium`` snapshot does).
#: Excluded from the runtime's presence gate so this gate keeps checking
#: exactly what "can this model be loaded offline" depends on -- the same
#: five large-v3 files it has always checked.
_NON_INFERENCE_MODEL_FILES = frozenset({".gitattributes", "LICENSE", "LICENSE.md", "README.md"})


def _tier_required_files(spec: CaptionTierSpec) -> tuple[str, ...]:
    """The files ``spec``'s tier must have on disk to be loadable offline.

    Derived from that tier's OWN pinned inventory in
    :data:`civiccast.native.caption_tiers.CAPTION_TIER_REGISTRY` -- the single
    source of truth the pack builder and both installer-side verifiers already
    use -- never hand-transcribed here. Hand-transcribing it is precisely the
    defect this function replaces: a flat, large-v3-shaped literal that
    demanded ``preprocessor_config.json``/``vocabulary.json`` of every tier,
    so the ``medium`` floor tier (``vocabulary.txt``, no preprocessor config)
    could never load.
    """

    return tuple(sorted(set(spec.files) - _NON_INFERENCE_MODEL_FILES))


def caption_tier_required_files(tier_id: str) -> tuple[str, ...]:
    """:func:`_tier_required_files` for a tier id, failing closed on an
    unknown or not-yet-owner-bound tier rather than guessing an inventory."""

    try:
        spec = CAPTION_TIER_REGISTRY[tier_id]
    except KeyError as exc:
        raise FasterWhisperRuntimeUnavailableError(
            f"The activated native station declared an unknown caption tier: {tier_id!r}. "
            "CivicCast will not guess a model file inventory."
        ) from exc
    try:
        return _tier_required_files(spec.require_bound())
    except CaptionTierBindingError as exc:
        raise FasterWhisperRuntimeUnavailableError(
            f"Caption tier {tier_id!r} is not bound to a pinned model identity: {exc}"
        ) from exc


#: Backwards-compatible alias: the large-v3 tier's required files, derived
#: from its pinned inventory instead of being restated. Kept because callers
#: and proofs that are large-v3-specific by construction
#: (``scripts/prove_native_caption_capacity.py``) still name it. NEW code
#: must use :func:`caption_tier_required_files` -- a module-level constant
#: cannot express a per-tier inventory, which is how the large-v3 shape came
#: to be imposed on every tier in the first place.
REQUIRED_LOCAL_MODEL_FILES = _tier_required_files(CAPTION_TIER_REGISTRY[LARGE_V3_TIER_ID])


def _tier_for_model_directory(model_path: Path) -> str | None:
    """The tier whose pinned ``model_directory`` this path's basename IS, or
    ``None`` when the basename names no known tier.

    Exact match only: ``faster-whisper-medium`` is the floor tier and
    ``faster-whisper-large-v3`` is the quality tier. Anything else is
    unidentified, never "probably large-v3".
    """

    name = model_path.name
    for tier_id, spec in CAPTION_TIER_REGISTRY.items():
        if spec.model_directory == name:
            return tier_id
    return None


def _resolve_packaged_model_tier(model_path: Path) -> tuple[str | None, tuple[str, ...]]:
    """Resolve ``(tier_id, required_files)`` for a packaged model directory.

    The station's DECLARED tier wins, and when the directory basename also
    names a known tier the two must agree: a station that says ``floor`` but
    points at ``faster-whisper-large-v3`` (or the reverse) is exactly the
    silent cross-tier swap the caption-integrity work exists to prevent, and
    fails closed and loudly here rather than being loaded.

    With no declared tier and an unrecognizable directory name the tier is
    unidentified; the caller then requires the directory to satisfy at least
    one KNOWN tier's inventory completely. That is not a weaker gate -- no
    directory passes without being a complete, recognizable caption model --
    it simply stops one tier's shape from standing in for all of them.
    """

    declared = os.environ.get(CAPTION_TIER_ENV_VAR, "").strip()
    on_disk = _tier_for_model_directory(model_path)
    if declared:
        # The DECLARATION is validated first: an unknown or unbound tier id is
        # reported as exactly that, rather than as a swap against whatever the
        # directory happens to be named.
        required = caption_tier_required_files(declared)
        if on_disk is not None and on_disk != declared:
            raise FasterWhisperRuntimeUnavailableError(
                f"The activated native station declared caption tier {declared!r} but its "
                f"packaged model path is tier {on_disk!r} ({model_path}). CivicCast will not "
                "load a caption model that was silently swapped for another tier."
            )
        return declared, required
    if on_disk is not None:
        return on_disk, caption_tier_required_files(on_disk)
    return None, ()


def _missing_packaged_model_files(model_path: Path, required: tuple[str, ...]) -> list[str]:
    return [name for name in required if not (model_path / name).is_file()]


class CaptionRuntime(Protocol):
    """Protocol implemented by concrete caption runtimes."""

    def transcribe(
        self,
        chunks: Iterable[AudioChunk],
        vocabulary: CustomVocabulary | None = None,
    ) -> Iterable[CaptionHypothesis]:
        """Yield caption hypotheses for the provided audio chunks."""


class FasterWhisperRuntimeUnavailableError(RuntimeError):
    """Raised when the optional faster-whisper runtime is requested but absent."""


class WhisperCppRuntimeUnavailableError(RuntimeError):
    """Raised when the verified native whisper.cpp caption pack is unavailable."""


class WhisperCppRuntime:
    """Offline large-v3 whisper.cpp/Vulkan adapter for native Windows stations.

    The executable and model are external caption-pack assets. Each chunk is
    passed to the pinned CLI without a shell, and the full JSON response is
    validated before it crosses the :class:`CaptionRuntime` boundary. A Vulkan
    backend is mandatory; silent CPU fallback would violate the measured
    three-channel capacity contract.
    """

    def __init__(
        self,
        *,
        executable: Path,
        model: Path,
        threads: int = 4,
        beam_size: int = 5,
        audio_context: int = 512,
        max_segment_chars: int = 42,
        language: str = "en",
        timeout_seconds: float = 60.0,
    ) -> None:
        self.executable = Path(executable).expanduser().resolve()
        self.model = Path(model).expanduser().resolve()
        missing = [str(path) for path in (self.executable, self.model) if not path.is_file()]
        if missing:
            raise WhisperCppRuntimeUnavailableError(
                "The verified native caption pack is missing required files: " + ", ".join(missing)
            )
        if "large-v3" not in self.model.name.lower():
            raise WhisperCppRuntimeUnavailableError(
                "The native caption pack model filename must identify large-v3; "
                f"got {self.model.name!r}."
            )
        if threads < 1:
            raise ValueError("whisper.cpp threads must be at least 1")
        if beam_size < 1:
            raise ValueError("whisper.cpp beam size must be at least 1")
        if audio_context < 1:
            raise ValueError("whisper.cpp audio context must be at least 1")
        if max_segment_chars < 1:
            raise ValueError("whisper.cpp maximum segment length must be at least 1")
        if timeout_seconds <= 0:
            raise ValueError("whisper.cpp timeout must be greater than zero")
        self.threads = threads
        self.beam_size = beam_size
        self.audio_context = audio_context
        self.max_segment_chars = max_segment_chars
        self.language = language
        self.timeout_seconds = timeout_seconds

    def transcribe(
        self,
        chunks: Iterable[AudioChunk],
        vocabulary: CustomVocabulary | None = None,
    ) -> Iterable[CaptionHypothesis]:
        initial_prompt = _build_initial_prompt(vocabulary)
        for chunk in chunks:
            yield from self._transcribe_chunk(chunk, initial_prompt=initial_prompt)

    def _transcribe_chunk(
        self,
        chunk: AudioChunk,
        *,
        initial_prompt: str | None,
    ) -> Iterable[CaptionHypothesis]:
        with TemporaryDirectory(prefix="civiccast-whispercpp-") as temp_dir:
            temp_root = Path(temp_dir)
            wav_path = temp_root / "chunk.wav"
            output_base = temp_root / "result"
            _write_pcm_chunk_wav(chunk, wav_path)
            command = [
                str(self.executable),
                "--model",
                str(self.model),
                "--file",
                str(wav_path),
                "--language",
                self.language,
                "--threads",
                str(self.threads),
                "--beam-size",
                str(self.beam_size),
                "--audio-ctx",
                str(self.audio_context),
                "--max-len",
                str(self.max_segment_chars),
                "--split-on-word",
                "--output-json-full",
                "--output-file",
                str(output_base),
            ]
            if initial_prompt:
                command.extend(["--prompt", initial_prompt])
            # The installer verifies both pack paths before activation; argv is
            # passed directly and never through a command shell.
            result = subprocess.run(  # noqa: S603
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip()[-1200:]
                raise WhisperCppRuntimeUnavailableError(
                    "The native whisper.cpp caption runtime failed "
                    f"(exit {result.returncode}): {detail}"
                )
            if "using Vulkan" not in result.stderr or "backend" not in result.stderr:
                raise WhisperCppRuntimeUnavailableError(
                    "The native whisper.cpp caption runtime did not confirm a Vulkan "
                    "backend; refusing silent CPU fallback."
                )
            output_path = output_base.with_suffix(".json")
            if not output_path.is_file():
                raise WhisperCppRuntimeUnavailableError(
                    "The native whisper.cpp caption runtime produced no JSON result."
                )
            try:
                payload = json.loads(output_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise WhisperCppRuntimeUnavailableError(
                    "The native whisper.cpp caption runtime produced invalid JSON."
                ) from exc
            _validate_whisper_cpp_large_v3_identity(payload)
            for index, segment in enumerate(payload.get("transcription", [])):
                hypothesis = _whisper_cpp_hypothesis(chunk, index, segment)
                if hypothesis is not None:
                    yield hypothesis


class FasterWhisperRuntime:
    """Lazy faster-whisper adapter for live and batch caption chunks.

    The optional dependency is imported only when audio is transcribed so the
    default CivicCast install remains lightweight. Install
    ``civiccast[captions-runtime]`` on hosts that should execute the model.
    """

    def __init__(
        self,
        model_size_or_path: str = "large-v3",
        *,
        device: str = "auto",
        compute_type: str = "int8",
        cpu_threads: int | None = None,
        num_workers: int = 1,
        beam_size: int | None = None,
        language: str | None = None,
        task: str = "transcribe",
        vad_filter: bool = True,
        live: bool = False,
    ) -> None:
        packaged_model = os.environ.get("CIVICCAST_WHISPER_MODEL_PATH", "").strip()
        self._local_files_only = False
        if os.environ.get("CIVICCAST_NATIVE_STATION", "").strip() == "1" and not packaged_model:
            raise FasterWhisperRuntimeUnavailableError(
                "The activated native station did not provide its verified packaged "
                "caption model path. CivicCast will not fall back to a first-use "
                "network download."
            )
        if packaged_model:
            model_path = Path(packaged_model).resolve()
            tier_id, required = _resolve_packaged_model_tier(model_path)
            if tier_id is not None:
                missing = _missing_packaged_model_files(model_path, required)
                tier_label = f" (caption tier {tier_id!r})"
            else:
                # Unidentified directory: it must still be a COMPLETE, known
                # caption model -- it just may be any tier's. Report the
                # closest candidate (fewest missing files) so the operator is
                # told what to fix, not merely that nothing matched.
                candidates = {
                    known: _missing_packaged_model_files(
                        model_path, caption_tier_required_files(known)
                    )
                    for known in CAPTION_TIER_REGISTRY
                }
                best = min(candidates, key=lambda known: len(candidates[known]))
                missing = candidates[best]
                tier_label = f" (no caption tier declared; closest tier {best!r})"
            if missing:
                raise FasterWhisperRuntimeUnavailableError(
                    "The packaged offline caption model is missing or incomplete at "
                    f"{model_path}{tier_label}; missing: {', '.join(missing)}. CivicCast "
                    "will not fall back to a first-use network download."
                )
            self.model_size_or_path = str(model_path)
            self._local_files_only = True
        else:
            self.model_size_or_path = model_size_or_path
        self.device = os.environ.get("CIVICCAST_WHISPER_DEVICE", "").strip() or device
        self.compute_type = (
            os.environ.get("CIVICCAST_WHISPER_COMPUTE_TYPE", "").strip() or compute_type
        )
        # ``live`` is the whole point of this distinction: a LIVE tap runtime
        # shares the box with playout, a batch/VOD runtime does not. It is a
        # constructor flag rather than a caller-side kwargs bundle because the
        # first version of this fix WAS a caller-side bundle -- in
        # ``build_tap_worker`` -- and the product never executed it: the app
        # pre-builds the runtime through
        # ``civiccast.ai_models.runtime.build_caption_runtime`` and injects it,
        # so ``build_tap_worker``'s own construction branch is dead in the
        # native service. The conservative values have to live where the
        # runtime is actually constructed.
        self._live = live
        # cpu_threads is CTranslate2's intra_threads and 0 means "every core".
        # That stays the batch/VOD default -- a finalization pass is allowed to
        # use the machine, and the native capacity proof
        # (``scripts/prove_native_caption_capacity.py``) is pinned to it.
        # Precedence: env > explicit argument > live/batch default.
        default_cpu_threads = LIVE_TAP_CPU_THREADS if live else 0
        self.cpu_threads = _env_int(
            "CIVICCAST_WHISPER_CPU_THREADS",
            default_cpu_threads if cpu_threads is None else cpu_threads,
            minimum=0,
        )
        self.num_workers = _env_int(
            "CIVICCAST_WHISPER_NUM_WORKERS",
            num_workers,
            minimum=1,
        )
        # Beam search costs roughly its beam width in decoder passes. Beam 5
        # stays the batch default and the GPU default; a live tap on CPU has a
        # hard real-time budget a VOD pass does not, so it decodes greedily.
        #
        # Resolved from the RESOLVED COMPUTE DEVICE, not from
        # ``CIVICCAST_WHISPER_DEVICE``: the default device is ``"auto"``, which
        # that variable never spells, so an env-only test would have silently
        # given every default-configured station the GPU beam width.
        if beam_size is None:
            beam_size = LIVE_TAP_CPU_BEAM_SIZE if (live and not self.on_cuda()) else 5
        # Scoped to the live tap deliberately: a batch/VOD pass and the native
        # capacity proof must not have their beam width changed out from under
        # them by a variable set to protect playout.
        self.beam_size = (
            _env_int("CIVICCAST_WHISPER_BEAM_SIZE", beam_size, minimum=1) if live else beam_size
        )
        self.language = language
        self.task = task
        self.vad_filter = vad_filter
        self._model: Any | None = None
        self._model_lock = threading.Lock()

    def on_cuda(self) -> bool:
        """Whether this runtime will actually decode on a GPU.

        ``self.device`` is a REQUEST, not an answer: its default is ``"auto"``,
        which is precisely the value that neither ``startswith("cuda")`` nor
        ``startswith("cpu")`` resolves, and which
        ``CIVICCAST_WHISPER_DEVICE`` never spells. Asking the environment
        instead would therefore have reported "not CUDA" for a GPU station and
        "not CUDA" for a CPU station alike -- a test that always passes and a
        distinction that never fires.

        ``auto`` is resolved by asking CTranslate2 how many CUDA devices it can
        see, which is the same question faster-whisper's own ``auto`` answers.
        Any failure (CTranslate2 absent, a driver that will not enumerate)
        resolves to CPU: the conservative answer is the safe one here, because
        the only thing this decides is whether to spend GPU-sized compute on a
        box that shares its CPU with playout.
        """

        device = str(self.device).strip().lower()
        if device.startswith("cuda"):
            return True
        if device.startswith("cpu"):
            return False
        try:
            import ctranslate2

            return int(ctranslate2.get_cuda_device_count()) > 0
        except Exception:
            return False

    def transcribe(
        self,
        chunks: Iterable[AudioChunk],
        vocabulary: CustomVocabulary | None = None,
    ) -> Iterable[CaptionHypothesis]:
        initial_prompt = _build_initial_prompt(vocabulary)
        for chunk in chunks:
            yield from self._transcribe_chunk(chunk, initial_prompt=initial_prompt)

    def _model_instance(self) -> Any:
        if self._model is None:
            with self._model_lock:
                if self._model is None:
                    model_kwargs: dict[str, Any] = {
                        "device": self.device,
                        "compute_type": self.compute_type,
                    }
                    if self.cpu_threads:
                        model_kwargs["cpu_threads"] = self.cpu_threads
                    if self.num_workers != 1:
                        model_kwargs["num_workers"] = self.num_workers
                    if self._local_files_only:
                        model_kwargs["local_files_only"] = True
                    if str(model_kwargs["device"]).startswith("cuda"):
                        # Must happen BEFORE the load attempt below, not in
                        # the except block: Windows' loader needs the
                        # directory registered before CTranslate2's CUDA
                        # backend resolves cuBLAS/cuDNN, not after it has
                        # already failed to.
                        _ensure_cuda_dll_directory()
                    try:
                        self._model = _load_whisper_model_class()(
                            self.model_size_or_path,
                            **model_kwargs,
                        )
                    except Exception as exc:
                        # A GPU device selection must DEGRADE, never kill
                        # captions: CTranslate2's CUDA backend dynamically
                        # links cuBLAS/cuDNN, so `device="cuda"` on a station
                        # without those libraries (they are not yet in the
                        # pinned payload) raises at model load. Fall back to
                        # the pack contract's validated cpu/int8 baseline and
                        # say so loudly — captions arrive slower, not never.
                        # A cpu-device failure has no safer tier below it and
                        # re-raises untouched.
                        if not str(model_kwargs["device"]).startswith("cuda"):
                            raise
                        logger.warning(
                            "faster-whisper could not initialize on device=%s "
                            "(%s); falling back to cpu/int8 — captions will "
                            "run slower until the CUDA runtime is available",
                            model_kwargs["device"],
                            exc,
                        )
                        self.device = "cpu"
                        self.compute_type = "int8"
                        model_kwargs["device"] = "cpu"
                        model_kwargs["compute_type"] = "int8"
                        if self._live and "CIVICCAST_WHISPER_BEAM_SIZE" not in os.environ:
                            # A LIVE runtime that just landed on the CPU it was
                            # not sized for must also drop to the CPU beam
                            # width, or the fallback hands playout exactly the
                            # GPU-sized decode this change exists to prevent.
                            # An explicit operator override is left alone.
                            self.beam_size = LIVE_TAP_CPU_BEAM_SIZE
                        self._model = _load_whisper_model_class()(
                            self.model_size_or_path,
                            **model_kwargs,
                        )
        return self._model

    def _transcribe_chunk(
        self,
        chunk: AudioChunk,
        *,
        initial_prompt: str | None,
    ) -> Iterable[CaptionHypothesis]:
        with TemporaryDirectory(prefix="civiccast-caption-") as temp_dir:
            wav_path = Path(temp_dir) / "chunk.wav"
            _write_pcm_chunk_wav(chunk, wav_path)

            segments, _info = self._model_instance().transcribe(
                str(wav_path),
                beam_size=self.beam_size,
                language=self.language,
                task=self.task,
                vad_filter=self.vad_filter,
                initial_prompt=initial_prompt,
            )

            for index, segment in enumerate(segments):
                text = str(getattr(segment, "text", "")).strip()
                if not text:
                    continue

                start_seconds = chunk.start_seconds + float(getattr(segment, "start", 0.0))
                end_seconds = chunk.start_seconds + float(getattr(segment, "end", 0.0))
                if end_seconds <= start_seconds:
                    continue

                yield CaptionHypothesis(
                    source_id=_segment_source_id(chunk.chunk_id, index),
                    start_seconds=start_seconds,
                    end_seconds=end_seconds,
                    text=text,
                    confidence=_segment_confidence(segment),
                )


def _load_whisper_model_class() -> Any:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise FasterWhisperRuntimeUnavailableError(
            "faster-whisper is not installed. Install CivicCast with "
            "`civiccast[captions-runtime]`, then confirm CUDA/cuDNN or CPU "
            "runtime compatibility before enabling live captions."
        ) from exc
    return WhisperModel


def _write_pcm_chunk_wav(chunk: AudioChunk, output_path: Path) -> None:
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(chunk.sample_rate_hz)
        wav_file.writeframes(chunk.pcm_s16le)


def _build_initial_prompt(vocabulary: CustomVocabulary | None) -> str | None:
    if vocabulary is None:
        return None

    parts: list[str] = []
    if vocabulary.initial_prompt:
        parts.append(vocabulary.initial_prompt.strip())
    if vocabulary.terms:
        parts.append("Prefer these civic terms and names: " + "; ".join(vocabulary.terms) + ".")
    return " ".join(parts) or None


def _segment_source_id(chunk_id: str, index: int) -> str:
    return f"{chunk_id[:110]}-{index:04d}"


def _segment_confidence(segment: Any) -> float:
    avg_logprob = getattr(segment, "avg_logprob", None)
    no_speech_prob = getattr(segment, "no_speech_prob", None)

    if isinstance(avg_logprob, int | float):
        acoustic_confidence = max(0.0, min(1.0, exp(float(avg_logprob))))
    else:
        acoustic_confidence = 1.0

    if isinstance(no_speech_prob, int | float):
        speech_confidence = 1.0 - max(0.0, min(1.0, float(no_speech_prob)))
    else:
        speech_confidence = 1.0

    return round(max(0.0, min(1.0, acoustic_confidence * speech_confidence)), 4)


def _validate_whisper_cpp_large_v3_identity(payload: object) -> None:
    if not isinstance(payload, dict):
        raise WhisperCppRuntimeUnavailableError(
            "The native caption runtime did not report the required large-v3 identity."
        )
    model = payload.get("model")
    audio = model.get("audio") if isinstance(model, dict) else None
    if not (
        isinstance(model, dict)
        and model.get("type") == "large"
        and model.get("multilingual") is True
        and isinstance(audio, dict)
        and audio.get("state") == 1280
        and audio.get("layer") == 32
    ):
        raise WhisperCppRuntimeUnavailableError(
            "The native caption runtime failed the required large-v3 identity check."
        )


def _whisper_cpp_hypothesis(
    chunk: AudioChunk,
    index: int,
    segment: object,
) -> CaptionHypothesis | None:
    if not isinstance(segment, dict):
        return None
    text = str(segment.get("text", "")).strip()
    offsets = segment.get("offsets")
    if not text or not isinstance(offsets, dict):
        return None
    start_ms = offsets.get("from")
    end_ms = offsets.get("to")
    if not isinstance(start_ms, int | float) or not isinstance(end_ms, int | float):
        return None
    start_seconds = max(chunk.start_seconds, chunk.start_seconds + float(start_ms) / 1000)
    end_seconds = min(chunk.end_seconds, chunk.start_seconds + float(end_ms) / 1000)
    if end_seconds <= start_seconds:
        return None
    probabilities: list[float] = []
    tokens = segment.get("tokens")
    if isinstance(tokens, list):
        for token in tokens:
            if not isinstance(token, dict):
                continue
            token_text = str(token.get("text", ""))
            probability = token.get("p")
            if token_text.startswith("[_") or not isinstance(probability, int | float):
                continue
            probabilities.append(max(0.0, min(1.0, float(probability))))
    confidence = round(sum(probabilities) / len(probabilities), 4) if probabilities else 0.0
    return CaptionHypothesis(
        source_id=_segment_source_id(chunk.chunk_id, index),
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        text=text,
        confidence=confidence,
    )


def _env_int(name: str, default: int, *, minimum: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        value = default
    else:
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError(f"{name} must be an integer; got {raw!r}.") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}; got {value}.")
    return value
