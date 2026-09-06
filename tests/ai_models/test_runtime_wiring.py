# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S13 slice 4 — wire summary/translate/captions to the operator-selected model.

The three feature adapters must consult :class:`AiModelService`'s effective model
instead of their hard-coded tags. When no operator selection exists, the resolved
runtime tag MUST equal each feature's *current* catalog default (behavior-preserving
w.r.t. whatever the catalog names as the default at any given time):

* summary (>=16GB RAM + a real GPU) -> ``gemma4:12b``  (adaptive default)
* summary (CPU-only, any RAM)       -> ``gemma4:e4b``  (adaptive default; field
  evidence 2026-08-29 retired the old RAM-only rule -- see
  ``detect_summary_model_default``)
* translation           -> ``translategemma:4b``
* captions              -> ``medium``         (faster-whisper id; ``whisper-`` stripped)

The slug->tag resolution lives at this wiring boundary (the catalog ``model_id``),
NOT inside the adapters; the captions ``whisper-`` prefix is stripped here so the
``FasterWhisperRuntime`` loads whatever the catalog's effective captions tag names.
As of OWNER-DECISION-caption-adaptive-tier.md (2026-07-30, BINDING) the catalog
default is the caption FLOOR tier (``whisper-medium-faster`` -> ``medium``), not
large-v3 -- see ``civiccast.ai_models.catalog._DEFAULT_KEY["captions"]``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.ai_models.service import AiModelService
from civiccast.ai_models.store import AiModelStore
from civiccast.db import Base


def _service(
    tmp_path: Path, *, system_ram_total_gb: int = 8, has_gpu: bool = False
) -> AiModelService:
    eng = create_engine(f"sqlite:///{tmp_path / 'wiring.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    return AiModelService(
        AiModelStore(factory), system_ram_total_gb=system_ram_total_gb, has_gpu=has_gpu
    )


# --- runtime-tag resolution (the wiring boundary) ----------------------------


class TestResolveRuntimeTag:
    def test_summary_default_8gb_is_e4b(self, tmp_path: Path) -> None:
        from civiccast.ai_models.runtime import resolve_runtime_tag

        service = _service(tmp_path, system_ram_total_gb=8)
        assert resolve_runtime_tag(service, "summary") == "gemma4:e4b"

    def test_summary_default_16gb_cpu_only_is_still_e4b(self, tmp_path: Path) -> None:
        # Field evidence 2026-08-29: no GPU signal means CPU-only, and CPU-only
        # never resolves to 12B by default, regardless of RAM.
        from civiccast.ai_models.runtime import resolve_runtime_tag

        service = _service(tmp_path, system_ram_total_gb=16)
        assert resolve_runtime_tag(service, "summary") == "gemma4:e4b"

    def test_summary_default_16gb_with_gpu_is_12b(self, tmp_path: Path) -> None:
        from civiccast.ai_models.runtime import resolve_runtime_tag

        service = _service(tmp_path, system_ram_total_gb=16, has_gpu=True)
        assert resolve_runtime_tag(service, "summary") == "gemma4:12b"

    def test_translation_default_is_translategemma_4b(self, tmp_path: Path) -> None:
        from civiccast.ai_models.runtime import resolve_runtime_tag

        service = _service(tmp_path)
        assert resolve_runtime_tag(service, "translation") == "translategemma:4b"

    def test_captions_default_strips_whisper_prefix(self, tmp_path: Path) -> None:
        from civiccast.ai_models.runtime import resolve_runtime_tag

        service = _service(tmp_path)
        # Catalog default model_id is ``whisper-medium`` (the floor tier, bound by
        # OWNER-DECISION-caption-adaptive-tier.md 2026-07-30); faster-whisper loads
        # ``medium``.
        assert resolve_runtime_tag(service, "captions") == "medium"

    def test_operator_selection_overrides_summary_tag(self, tmp_path: Path) -> None:
        from civiccast.ai_models.runtime import resolve_runtime_tag

        service = _service(tmp_path, system_ram_total_gb=8)
        service.select_model("summary", "gemma4-12b-ollama")
        assert resolve_runtime_tag(service, "summary") == "gemma4:12b"

    def test_operator_selection_overrides_translation_tag(self, tmp_path: Path) -> None:
        from civiccast.ai_models.runtime import resolve_runtime_tag

        service = _service(tmp_path)
        # gemma4-31b-cloud is a cloud tier -> consent is required to persist it.
        service.select_model("translation", "gemma4-31b-cloud", consent_accepted=True)
        assert resolve_runtime_tag(service, "translation") == "gemma4:31b-cloud"


# --- summary adapter seam ----------------------------------------------------


class TestSummaryAdapterSeam:
    def test_for_release_accepts_model_tag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from civiccast.ai_runtime.ollama_client import OllamaModelManifest
        from civiccast.summary import ollama as summary_module

        captured: dict[str, str] = {}

        def fake_manifest(model: str, *, base_url: str) -> OllamaModelManifest:
            captured["model"] = model
            return OllamaModelManifest(
                model=model,
                digest="sha256:" + ("a" * 64),
                runtime_version="ollama 0.9.0",
                manifest_source=f"http://127.0.0.1:11434/api/tags#{model}",
                details={},
            )

        monkeypatch.setattr(summary_module, "get_ollama_model_manifest", fake_manifest)

        adapter = summary_module.OllamaSummaryModel.for_release(model_tag="gemma4:12b")
        assert captured["model"] == "gemma4:12b"
        assert adapter.model_tag == "gemma4:12b"

    def test_for_release_default_preserves_e4b(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from civiccast.ai_runtime.ollama_client import OllamaModelManifest
        from civiccast.summary import ollama as summary_module

        captured: dict[str, str] = {}

        def fake_manifest(model: str, *, base_url: str) -> OllamaModelManifest:
            captured["model"] = model
            return OllamaModelManifest(
                model=model,
                digest="sha256:" + ("a" * 64),
                runtime_version="ollama 0.9.0",
                manifest_source=f"http://127.0.0.1:11434/api/tags#{model}",
                details={},
            )

        monkeypatch.setattr(summary_module, "get_ollama_model_manifest", fake_manifest)

        adapter = summary_module.OllamaSummaryModel.for_release()
        assert captured["model"] == "gemma4:e4b"
        assert adapter.model_tag == "gemma4:e4b"

    def test_build_summary_model_uses_service_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from civiccast.ai_models.runtime import build_summary_model
        from civiccast.ai_runtime.ollama_client import OllamaModelManifest
        from civiccast.summary import ollama as summary_module

        captured: dict[str, str] = {}

        def fake_manifest(model: str, *, base_url: str) -> OllamaModelManifest:
            captured["model"] = model
            return OllamaModelManifest(
                model=model,
                digest="sha256:" + ("a" * 64),
                runtime_version="ollama 0.9.0",
                manifest_source=f"http://127.0.0.1:11434/api/tags#{model}",
                details={},
            )

        monkeypatch.setattr(summary_module, "get_ollama_model_manifest", fake_manifest)

        service = _service(tmp_path, system_ram_total_gb=16, has_gpu=True)
        adapter = build_summary_model(service)
        assert adapter.model_tag == "gemma4:12b"
        assert captured["model"] == "gemma4:12b"


# --- translation adapter seam ------------------------------------------------


class TestTranslationAdapterSeam:
    def test_for_release_accepts_model_tag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from civiccast.ai_runtime.ollama_client import OllamaModelManifest
        from civiccast.translate import ollama as translate_module

        captured: dict[str, str] = {}

        def fake_manifest(model: str, *, base_url: str) -> OllamaModelManifest:
            captured["model"] = model
            return OllamaModelManifest(
                model=model,
                digest="sha256:" + ("b" * 64),
                runtime_version="ollama 0.9.0",
                manifest_source=f"http://127.0.0.1:11434/api/tags#{model}",
                details={},
            )

        monkeypatch.setattr(translate_module, "get_ollama_model_manifest", fake_manifest)

        provider = translate_module.OllamaSpanishTranslator.for_release(
            model_tag="translategemma:4b"
        )
        assert captured["model"] == "translategemma:4b"
        assert provider.model_tag == "translategemma:4b"

    def test_for_release_default_preserves_translategemma(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from civiccast.ai_runtime.ollama_client import OllamaModelManifest
        from civiccast.translate import ollama as translate_module

        captured: dict[str, str] = {}

        def fake_manifest(model: str, *, base_url: str) -> OllamaModelManifest:
            captured["model"] = model
            return OllamaModelManifest(
                model=model,
                digest="sha256:" + ("b" * 64),
                runtime_version="ollama 0.9.0",
                manifest_source=f"http://127.0.0.1:11434/api/tags#{model}",
                details={},
            )

        monkeypatch.setattr(translate_module, "get_ollama_model_manifest", fake_manifest)

        provider = translate_module.OllamaSpanishTranslator.for_release()
        assert captured["model"] == "translategemma:4b"
        assert provider.model_tag == "translategemma:4b"

    def test_build_translator_uses_service_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from civiccast.ai_models.runtime import build_translator
        from civiccast.ai_runtime.ollama_client import OllamaModelManifest
        from civiccast.translate import ollama as translate_module

        captured: dict[str, str] = {}

        def fake_manifest(model: str, *, base_url: str) -> OllamaModelManifest:
            captured["model"] = model
            return OllamaModelManifest(
                model=model,
                digest="sha256:" + ("b" * 64),
                runtime_version="ollama 0.9.0",
                manifest_source=f"http://127.0.0.1:11434/api/tags#{model}",
                details={},
            )

        monkeypatch.setattr(translate_module, "get_ollama_model_manifest", fake_manifest)

        service = _service(tmp_path)
        provider = build_translator(service)
        assert provider.model_tag == "translategemma:4b"
        assert captured["model"] == "translategemma:4b"


# --- captions runtime seam ---------------------------------------------------


class TestCaptionsRuntimeSeam:
    def test_build_caption_runtime_uses_service_default(self, tmp_path: Path) -> None:
        from civiccast.ai_models.runtime import build_caption_runtime
        from civiccast.captions.runtime import FasterWhisperRuntime

        service = _service(tmp_path)
        runtime = build_caption_runtime(service)
        assert isinstance(runtime, FasterWhisperRuntime)
        # No selection -> the catalog default, which is now the floor tier (medium)
        # per OWNER-DECISION-caption-adaptive-tier.md (2026-07-30, BINDING).
        assert runtime.model_size_or_path == "medium"

    def test_the_live_caption_runtime_is_sized_for_a_box_that_is_on_air(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`live=True` is the LIVE tap's sizing, and it must be real here.

        This is the seam the running service actually calls: `civiccast.app`
        builds the caption runtime through `build_caption_runtime` and INJECTS
        it into `build_tap_worker`, so conservative values applied inside
        `build_tap_worker`'s own construction branch never execute in the
        native product. That is exactly how the measured field failure
        happened -- the live tap ran with `cpu_threads=0` (every core) and
        beam 5 on a CPU-only station with three channels ON_AIR.

        Item 79: `cpu_threads` is no longer a flat `1` -- it is
        core-count-aware (`default_live_tap_cpu_threads`), floored at
        `LIVE_TAP_CPU_THREADS` and capped at `LIVE_TAP_CPU_THREADS_CEILING`.
        `os.cpu_count()` is monkeypatched so this assertion is exact
        regardless of what box CI runs on.
        """

        monkeypatch.setattr("civiccast.captions.runtime.os.cpu_count", lambda: 8)

        from civiccast.ai_models.runtime import build_caption_runtime
        from civiccast.captions.runtime import (
            LIVE_TAP_CPU_BEAM_SIZE,
            FasterWhisperRuntime,
        )

        service = _service(tmp_path)
        live = build_caption_runtime(service, live=True)

        assert isinstance(live, FasterWhisperRuntime)
        assert live.cpu_threads == 1  # 8 cpus // 8 == 1, at the floor
        assert live.beam_size == LIVE_TAP_CPU_BEAM_SIZE == 1

        # The batch/VOD default is deliberately untouched: a finalization pass
        # runs against a published file, not against the air signal, and the
        # native capacity proof is pinned to this sizing.
        batch = build_caption_runtime(service)
        assert isinstance(batch, FasterWhisperRuntime)
        assert batch.cpu_threads == 0
        assert batch.beam_size == 5

    def test_the_live_caption_runtime_cpu_threads_scale_with_core_count(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Item 79's exact acceptance formula: `max(1, min(2, cpus // 8))`."""

        from civiccast.ai_models.runtime import build_caption_runtime
        from civiccast.captions.runtime import FasterWhisperRuntime

        service = _service(tmp_path)

        for cpu_count, expected in ((1, 1), (4, 1), (8, 1), (16, 2), (128, 2), (None, 1)):
            monkeypatch.setattr("civiccast.captions.runtime.os.cpu_count", lambda n=cpu_count: n)
            live = build_caption_runtime(service, live=True)
            assert isinstance(live, FasterWhisperRuntime)
            assert live.cpu_threads == expected, f"cpu_count={cpu_count}"

    def test_the_live_caption_runtime_cpu_threads_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`CIVICCAST_CAPTION_TAP_CPU_THREADS` overrides the live tap only."""

        from civiccast.ai_models.runtime import build_caption_runtime
        from civiccast.captions.runtime import FasterWhisperRuntime

        monkeypatch.setattr("civiccast.captions.runtime.os.cpu_count", lambda: 8)
        monkeypatch.setenv("CIVICCAST_CAPTION_TAP_CPU_THREADS", "2")

        service = _service(tmp_path)
        live = build_caption_runtime(service, live=True)
        batch = build_caption_runtime(service)

        assert isinstance(live, FasterWhisperRuntime)
        assert live.cpu_threads == 2
        # The batch/VOD path never reads the tap-only override.
        assert isinstance(batch, FasterWhisperRuntime)
        assert batch.cpu_threads == 0

    def test_the_live_caption_runtime_cpu_threads_env_override_clamps_zero(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """`CIVICCAST_CAPTION_TAP_CPU_THREADS=0` must NEVER take a station off air.

        `FasterWhisperRuntime(live=True)` is constructed UNGUARDED during
        control-plane startup (`civiccast.app` -> `build_caption_runtime`, no
        try/except around it). `0` means "every core" to CTranslate2 -- the
        exact batch/VOD sizing that produced the original DESKTOP-VBMA6O5
        field failure -- so it must be clamped with a warning, like the
        neighbouring `CIVICCAST_CAPTION_TAP_*` backoff settings
        (`CaptionTapWorkerSettings._backoff_settings_from_env`), never allowed
        to raise and abort startup.
        """

        from civiccast.ai_models.runtime import build_caption_runtime
        from civiccast.captions.runtime import FasterWhisperRuntime

        monkeypatch.setattr("civiccast.captions.runtime.os.cpu_count", lambda: 8)
        monkeypatch.setenv("CIVICCAST_CAPTION_TAP_CPU_THREADS", "0")

        service = _service(tmp_path)
        with caplog.at_level("WARNING", logger="civiccast.captions.runtime"):
            live = build_caption_runtime(service, live=True)

        assert isinstance(live, FasterWhisperRuntime)
        assert live.cpu_threads == 1  # clamped to the shipped default, never 0
        assert "CIVICCAST_CAPTION_TAP_CPU_THREADS" in caplog.text
        assert "0" in caplog.text

    def test_the_live_caption_runtime_cpu_threads_env_override_clamps_garbage(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """An unparseable value falls back to the default rather than raising."""

        from civiccast.ai_models.runtime import build_caption_runtime
        from civiccast.captions.runtime import FasterWhisperRuntime

        monkeypatch.setattr("civiccast.captions.runtime.os.cpu_count", lambda: 8)
        monkeypatch.setenv("CIVICCAST_CAPTION_TAP_CPU_THREADS", "two")

        service = _service(tmp_path)
        with caplog.at_level("WARNING", logger="civiccast.captions.runtime"):
            live = build_caption_runtime(service, live=True)

        assert isinstance(live, FasterWhisperRuntime)
        assert live.cpu_threads == 1
        assert "CIVICCAST_CAPTION_TAP_CPU_THREADS" in caplog.text
        assert "'two'" in caplog.text

    def test_the_app_builds_its_live_tap_runtime_through_the_live_seam(self) -> None:
        """Wiring proof: `civiccast.app` must ask for the LIVE sizing.

        A unit test of `build_caption_runtime(live=True)` alone would still
        pass if `app.py` never passed the flag -- which is the shape of the
        original defect. This reads the call the app actually makes.

        DESELECTED FROM THE MUTATION LANE (see the `mutation-report` job in
        .github/workflows/deterministic-detectors.yml, alongside the
        build_native_server_pack `*_PINS` test and the other source-tree-
        binding tests). Under mutmut this test module executes from inside the
        mutants/ sandbox, so the repo-relative path below resolves to the
        sandbox's mutant-duplicated `app.py` -- one copy of every mutated
        function body per candidate mutant -- and the scan counts those
        duplicates (reported as "found 665") instead of the two real call
        sites. Normal CI runs it against pristine source, where it is exact.
        """

        import ast
        from pathlib import Path as _Path

        # The TRACKED repo file, by repo-root-relative path -- deliberately NOT
        # `inspect.getfile(civiccast.app)`. Under the mutation lane every
        # mutant is a rewritten copy of this module, so resolving it through
        # the imported object made this test read whichever mutant was loaded
        # and report every one of them as a finding ("found 665"). The claim
        # here is about what is COMMITTED at this call site, so it reads the
        # committed bytes.
        app_source = _Path(__file__).resolve().parents[2] / "civiccast" / "app.py"
        if not app_source.is_file():  # pragma: no cover - installed-wheel runs
            pytest.skip("civiccast/app.py is not present as a repo source file")
        source = app_source.read_text(encoding="utf-8")
        calls = [
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "build_caption_runtime"
        ]
        assert calls, "civiccast.app no longer calls build_caption_runtime"
        live_flags = [
            any(
                keyword.arg == "live" and getattr(keyword.value, "value", None) is True
                for keyword in call.keywords
            )
            for call in calls
        ]
        # Exactly one call site is the live tap; the other is the offline
        # caption job, which must NOT ask for the live sizing.
        assert live_flags.count(True) == 1, (
            "expected exactly one build_caption_runtime(live=True) call in civiccast.app "
            f"(the live caption tap); found {live_flags.count(True)}"
        )
        assert live_flags.count(False) >= 1
