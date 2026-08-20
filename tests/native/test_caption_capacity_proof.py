# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Acceptance logic for the real three-channel native caption capacity proof."""

from __future__ import annotations

import importlib.util
import os
import sys
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from civiccast.captions.runtime import REQUIRED_LOCAL_MODEL_FILES


def _load() -> object:
    path = Path(__file__).resolve().parents[2] / "scripts" / "prove_native_caption_capacity.py"
    spec = importlib.util.spec_from_file_location("prove_native_caption_capacity", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


proof = _load()


def test_capacity_proof_reads_the_exact_windows_cpu_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[tuple[object, str]] = []
    local_machine = object()

    def open_key(root: object, path: str) -> tuple[object, str]:
        opened.append((root, path))
        return root, path

    fake_winreg = SimpleNamespace(
        HKEY_LOCAL_MACHINE=local_machine,
        OpenKey=open_key,
        CloseKey=lambda _key: None,
        QueryValueEx=lambda _key, name: (
            (
                "AMD Ryzen 7 7800X3D 8-Core Processor",
                1,
            )
            if name == "ProcessorNameString"
            else ("", 1)
        ),
    )
    monkeypatch.setattr(proof.os, "name", "nt")
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)

    assert proof.cpu_model_name() == "AMD Ryzen 7 7800X3D 8-Core Processor"
    assert opened == [
        (
            local_machine,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
        )
    ]


def test_capacity_proof_cpu_model_falls_back_to_platform_processor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(proof.os, "name", "posix")
    monkeypatch.setattr(proof.platform, "processor", lambda: "fallback processor")

    assert proof.cpu_model_name() == "fallback processor"


def test_capacity_proof_cpu_model_falls_back_when_windows_registry_read_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_winreg = SimpleNamespace(
        HKEY_LOCAL_MACHINE=object(),
        OpenKey=lambda _root, _path: (_ for _ in ()).throw(OSError("registry unavailable")),
    )
    monkeypatch.setattr(proof.os, "name", "nt")
    monkeypatch.setattr(proof.platform, "processor", lambda: "fallback processor")
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)

    assert proof.cpu_model_name() == "fallback processor"


def _passing_report() -> dict[str, object]:
    return {
        "channels": {
            channel: {
                "active_vtt": True,
                "review_items": 2,
                # Derived from proof.REQUIRED_TRANSCRIPT_PHRASES rather than
                # hard-coded, so a future re-pin of the canonical fixture
                # phrases (as happened when the owner re-derived the gate at
                # 10s segments and the fixtures moved to real council audio)
                # updates this passing report automatically instead of
                # silently turning it into a failing one.
                "review_texts": [
                    f"Transcript containing {phrase}."
                    for phrase in proof.REQUIRED_TRANSCRIPT_PHRASES
                ],
            }
            for channel in proof.REQUIRED_CHANNELS
        },
        "network_attempts": [],
        "model": {
            "backend": "faster-whisper",
            "runtime_version": "1.2.1",
            "ctranslate2_version": "4.8.1",
            "device": "cpu",
            "compute_type": "int8",
            "model_repository": proof.WHISPER_MODEL_REPO,
            "model_revision": proof.WHISPER_MODEL_REVISION,
            "model_files": {
                name: {"bytes": size, "sha256": digest}
                for name, (size, digest) in proof.WHISPER_MODEL_FILES.items()
            },
        },
        "performance": {
            "elapsed_seconds": 9.5,
            "realtime_deadline_seconds": 10.0,
            "peak_process_tree_rss_bytes": 4_000_000_000,
            "max_process_tree_rss_bytes": proof.MAX_CAPTION_PROCESS_TREE_RSS_BYTES,
            "peak_child_rss_bytes": 1_000_000_000,
            "peak_process_count": 2,
            "gpu_measurement_status": "measured",
            "peak_caption_gpu_delta_bytes": 5_000_000_000,
        },
        "scan": {
            "committed_review_items": 6,
            "consumed_segments": 6,
            "dropped_overload_segments": 0,
            "overloaded_channels": [],
        },
        "overload_negative_control": {
            "active_vtt_cleared": True,
            "dropped_overload_segments": 3,
            "runtime_state": "overloaded",
        },
    }


def test_capacity_acceptance_requires_real_time_three_channel_success() -> None:
    report = _passing_report()

    assert proof.evaluate_capacity_report(report) == []

    report["performance"]["elapsed_seconds"] = 10.001  # type: ignore[index]
    assert "missed real-time deadline" in " ".join(proof.evaluate_capacity_report(report))


def test_capacity_acceptance_fails_closed_on_missing_channel_or_overload_control() -> None:
    report = _passing_report()
    del report["channels"]["public"]  # type: ignore[index]
    report["overload_negative_control"]["active_vtt_cleared"] = False  # type: ignore[index]

    problems = proof.evaluate_capacity_report(report)

    assert any("required channels" in problem for problem in problems)
    assert any("overload negative control" in problem for problem in problems)


def test_capacity_acceptance_rejects_wrong_transcript_content() -> None:
    report = _passing_report()
    report["channels"]["public"]["review_texts"] = ["unrelated words"]  # type: ignore[index]

    assert any(
        "required transcript" in problem for problem in proof.evaluate_capacity_report(report)
    )


def test_capacity_acceptance_enforces_16gb_station_process_budget() -> None:
    report = _passing_report()
    report["performance"]["peak_process_tree_rss_bytes"] = (  # type: ignore[index]
        proof.MAX_CAPTION_PROCESS_TREE_RSS_BYTES + 1
    )

    assert any("RSS budget" in problem for problem in proof.evaluate_capacity_report(report))


def test_capacity_acceptance_rejects_alternate_runtime_or_model_hash() -> None:
    alternate = _passing_report()
    alternate["model"]["backend"] = "whispercpp-vulkan"  # type: ignore[index]
    assert any(
        "accepted faster-whisper" in problem
        for problem in proof.evaluate_capacity_report(alternate)
    )

    mutated = _passing_report()
    mutated["model"]["model_files"]["model.bin"]["sha256"] = "0" * 64  # type: ignore[index]
    assert any("model identity" in problem for problem in proof.evaluate_capacity_report(mutated))


def test_capacity_acceptance_does_not_require_a_gpu() -> None:
    cpu_only = _passing_report()
    cpu_only["performance"]["gpu_measurement_status"] = "unavailable"  # type: ignore[index]
    cpu_only["performance"]["peak_caption_gpu_delta_bytes"] = None  # type: ignore[index]

    assert proof.evaluate_capacity_report(cpu_only) == []


def test_process_tree_memory_includes_child_processes() -> None:
    class _Memory:
        def __init__(self, rss: int) -> None:
            self.rss = rss

    class _Process:
        def __init__(self, pid: int, rss: int, children: list[_Process] | None = None) -> None:
            self.pid = pid
            self._rss = rss
            self._children = children or []

        def children(self, *, recursive: bool) -> list[_Process]:
            assert recursive is True
            return self._children

        def memory_info(self) -> _Memory:
            return _Memory(self._rss)

    child = _Process(2, 300)
    parent = _Process(1, 700, [child])

    measured = proof.measure_process_tree_memory(parent)

    assert measured == {
        "child_rss_bytes": 300,
        "pids": (1, 2),
        "process_count": 2,
        "process_tree_rss_bytes": 1000,
    }


def test_capacity_proof_requires_three_compatible_sequential_segments(
    tmp_path: Path,
) -> None:
    segments: list[Path] = []
    for index in range(3):
        path = tmp_path / f"chunk-{index:06d}.wav"
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(16_000)
            handle.writeframes(b"\x00\x00" * 16_000)
        segments.append(path)

    assert proof.validate_audio_segments(segments) == (16_000, 1.0)

    with pytest.raises(ValueError, match="exactly three"):
        proof.validate_audio_segments(segments[:2])

    incompatible = tmp_path / "incompatible.wav"
    with wave.open(str(incompatible), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8_000)
        handle.writeframes(b"\x00\x00" * 8_000)
    with pytest.raises(ValueError, match="same sample rate and duration"):
        proof.validate_audio_segments([segments[0], segments[1], incompatible])


def test_capacity_runtime_tuning_is_explicit_and_fail_closed() -> None:
    assert proof.validate_runtime_configuration(
        beam_size=1,
        overlap_seconds=1.0,
        cpu_threads=0,
        vad_filter=True,
    ) == {
        "beam_size": 1,
        "cpu_threads": 0,
        "overlap_seconds": 1.0,
        "vad_filter": True,
    }

    with pytest.raises(ValueError, match="beam size"):
        proof.validate_runtime_configuration(
            beam_size=0,
            overlap_seconds=1.0,
            cpu_threads=0,
            vad_filter=True,
        )
    with pytest.raises(ValueError, match="overlap"):
        proof.validate_runtime_configuration(
            beam_size=1,
            overlap_seconds=0.0,
            cpu_threads=0,
            vad_filter=True,
        )


def test_capacity_proof_builds_exact_faster_whisper_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    captured_environment: dict[str, str | None] = {}
    expected_runtime = SimpleNamespace(num_workers=1)

    def runtime_factory(**kwargs: object) -> object:
        captured.update(kwargs)
        captured_environment.update(
            {
                name: os.environ.get(name)
                for name in (
                    "CIVICCAST_WHISPER_MODEL_PATH",
                    "CIVICCAST_WHISPER_DEVICE",
                    "CIVICCAST_WHISPER_COMPUTE_TYPE",
                )
            }
        )
        return expected_runtime

    monkeypatch.setattr(
        proof,
        "FasterWhisperRuntime",
        runtime_factory,
    )
    monkeypatch.setattr(
        proof,
        "verify_packaged_model",
        lambda _path: {
            "model_repository": proof.WHISPER_MODEL_REPO,
            "model_revision": proof.WHISPER_MODEL_REVISION,
            "model_files": {
                name: {"bytes": size, "sha256": digest}
                for name, (size, digest) in proof.WHISPER_MODEL_FILES.items()
            },
        },
    )
    monkeypatch.setattr(
        proof,
        "runtime_distribution_versions",
        lambda: {
            "runtime_version": "1.2.1",
            "ctranslate2_version": "4.8.1",
        },
    )
    model_dir = tmp_path / "faster-whisper-large-v3"

    runtime, identity = proof.build_caption_runtime(
        backend="faster-whisper",
        model_dir=model_dir,
        beam_size=5,
        cpu_threads=0,
        vad_filter=True,
    )

    assert runtime is expected_runtime
    # num_workers is deliberately absent: build_caption_runtime must not pass
    # it, so the constructor's own default (and any operator
    # CIVICCAST_WHISPER_NUM_WORKERS override) governs -- identically to how
    # civiccast/captions/tap_worker.py constructs the production runtime
    # bare. A capacity proof that hardcoded a different num_workers than
    # production would measure a runtime nobody ships (Codex review, PR
    # #427).
    assert "num_workers" not in captured
    assert captured == {
        "beam_size": 5,
        "compute_type": "int8",
        "cpu_threads": 0,
        "device": "cpu",
        "language": "en",
        "model_size_or_path": str(model_dir),
        "vad_filter": True,
    }
    assert captured_environment == {
        "CIVICCAST_WHISPER_MODEL_PATH": str(model_dir),
        "CIVICCAST_WHISPER_DEVICE": "cpu",
        "CIVICCAST_WHISPER_COMPUTE_TYPE": "int8",
    }
    # The identity dict records the *actual* num_workers the constructed
    # runtime ended up with (post env-override resolution), taken from
    # expected_runtime.num_workers, so every capacity report states which
    # executor configuration was measured rather than assuming one.
    assert identity == {
        "backend": "faster-whisper",
        "beam_size": 5,
        "compute_type": "int8",
        "cpu_threads": 0,
        "ctranslate2_version": "4.8.1",
        "device": "cpu",
        "local_files_only": True,
        "model": str(model_dir),
        "model_files": {
            name: {"bytes": size, "sha256": digest}
            for name, (size, digest) in proof.WHISPER_MODEL_FILES.items()
        },
        "model_repository": proof.WHISPER_MODEL_REPO,
        "model_revision": proof.WHISPER_MODEL_REVISION,
        "num_workers": 1,
        "runtime_version": "1.2.1",
        "vad_filter": True,
    }


def test_capacity_runtime_constructs_production_adapter_in_local_only_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_dir = tmp_path / "faster-whisper-large-v3"
    model_dir.mkdir()
    for name in REQUIRED_LOCAL_MODEL_FILES:
        (model_dir / name).write_bytes(b"test model file")
    monkeypatch.setattr(proof, "verify_packaged_model", lambda _path: {})
    monkeypatch.setattr(proof, "runtime_distribution_versions", lambda: {})
    for name in (
        "CIVICCAST_WHISPER_MODEL_PATH",
        "CIVICCAST_WHISPER_DEVICE",
        "CIVICCAST_WHISPER_COMPUTE_TYPE",
    ):
        monkeypatch.delenv(name, raising=False)

    runtime, _identity = proof.build_caption_runtime(
        backend="faster-whisper",
        model_dir=model_dir,
        beam_size=5,
        cpu_threads=0,
        vad_filter=True,
    )

    assert runtime.model_size_or_path == str(model_dir.resolve())
    assert runtime.device == "cpu"
    assert runtime.compute_type == "int8"
    assert runtime._local_files_only is True
    for name in (
        "CIVICCAST_WHISPER_MODEL_PATH",
        "CIVICCAST_WHISPER_DEVICE",
        "CIVICCAST_WHISPER_COMPUTE_TYPE",
    ):
        assert name not in os.environ


def test_capacity_runtime_restores_process_environment_after_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(proof, "verify_packaged_model", lambda _path: {})
    monkeypatch.setattr(proof, "runtime_distribution_versions", lambda: {})
    monkeypatch.setattr(
        proof, "FasterWhisperRuntime", lambda **_kwargs: SimpleNamespace(num_workers=1)
    )
    monkeypatch.setenv("CIVICCAST_WHISPER_MODEL_PATH", "before-model")
    monkeypatch.setenv("CIVICCAST_WHISPER_DEVICE", "before-device")
    monkeypatch.setenv("CIVICCAST_WHISPER_COMPUTE_TYPE", "before-compute")

    proof.build_caption_runtime(
        backend="faster-whisper",
        model_dir=tmp_path / "faster-whisper-large-v3",
        beam_size=5,
        cpu_threads=0,
        vad_filter=True,
    )

    assert os.environ["CIVICCAST_WHISPER_MODEL_PATH"] == "before-model"
    assert os.environ["CIVICCAST_WHISPER_DEVICE"] == "before-device"
    assert os.environ["CIVICCAST_WHISPER_COMPUTE_TYPE"] == "before-compute"


def test_capacity_runtime_removes_initially_absent_environment_after_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(proof, "verify_packaged_model", lambda _path: {})
    monkeypatch.setattr(proof, "runtime_distribution_versions", lambda: {})
    monkeypatch.setattr(
        proof, "FasterWhisperRuntime", lambda **_kwargs: SimpleNamespace(num_workers=1)
    )
    for name in (
        "CIVICCAST_WHISPER_MODEL_PATH",
        "CIVICCAST_WHISPER_DEVICE",
        "CIVICCAST_WHISPER_COMPUTE_TYPE",
    ):
        monkeypatch.delenv(name, raising=False)

    proof.build_caption_runtime(
        backend="faster-whisper",
        model_dir=tmp_path / "faster-whisper-large-v3",
        beam_size=5,
        cpu_threads=0,
        vad_filter=True,
    )

    for name in (
        "CIVICCAST_WHISPER_MODEL_PATH",
        "CIVICCAST_WHISPER_DEVICE",
        "CIVICCAST_WHISPER_COMPUTE_TYPE",
    ):
        assert name not in os.environ


def test_capacity_runtime_restores_absent_environment_when_construction_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(proof, "verify_packaged_model", lambda _path: {})
    monkeypatch.setattr(proof, "runtime_distribution_versions", lambda: {})

    def raise_during_construction(**_kwargs: object) -> object:
        raise RuntimeError("runtime construction failed")

    monkeypatch.setattr(proof, "FasterWhisperRuntime", raise_during_construction)
    for name in (
        "CIVICCAST_WHISPER_MODEL_PATH",
        "CIVICCAST_WHISPER_DEVICE",
        "CIVICCAST_WHISPER_COMPUTE_TYPE",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(RuntimeError, match="runtime construction failed"):
        proof.build_caption_runtime(
            backend="faster-whisper",
            model_dir=tmp_path / "faster-whisper-large-v3",
            beam_size=5,
            cpu_threads=0,
            vad_filter=True,
        )

    for name in (
        "CIVICCAST_WHISPER_MODEL_PATH",
        "CIVICCAST_WHISPER_DEVICE",
        "CIVICCAST_WHISPER_COMPUTE_TYPE",
    ):
        assert name not in os.environ


def test_capacity_runtime_restores_preexisting_environment_when_construction_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(proof, "verify_packaged_model", lambda _path: {})
    monkeypatch.setattr(proof, "runtime_distribution_versions", lambda: {})

    def raise_during_construction(**_kwargs: object) -> object:
        raise RuntimeError("runtime construction failed")

    monkeypatch.setattr(proof, "FasterWhisperRuntime", raise_during_construction)
    previous = {
        "CIVICCAST_WHISPER_MODEL_PATH": "before-model",
        "CIVICCAST_WHISPER_DEVICE": "before-device",
        "CIVICCAST_WHISPER_COMPUTE_TYPE": "before-compute",
    }
    for name, value in previous.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError, match="runtime construction failed"):
        proof.build_caption_runtime(
            backend="faster-whisper",
            model_dir=tmp_path / "faster-whisper-large-v3",
            beam_size=5,
            cpu_threads=0,
            vad_filter=True,
        )

    assert {name: os.environ.get(name) for name in previous} == previous


def test_capacity_runtime_rejects_every_alternate_backend(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="accepted faster-whisper"):
        proof.build_caption_runtime(
            backend="whispercpp-vulkan",
            model_dir=tmp_path,
            beam_size=5,
            cpu_threads=0,
            vad_filter=True,
        )
