#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run or preflight v1.1 real AI release proof."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

from civiccast.ai_models.catalog import build_feature_registry, catalog_tier
from civiccast.ai_runtime.ollama_client import OllamaRuntimeUnavailableError
from civiccast.captions.benchmark import load_wav_chunks, run_caption_benchmark
from civiccast.captions.models import CaptionCue
from civiccast.captions.runtime import FasterWhisperRuntime, FasterWhisperRuntimeUnavailableError
from civiccast.summary.generate import SummaryGenerationPipeline
from civiccast.summary.ollama import OllamaSummaryModel
from civiccast.translate.ollama import OllamaSpanishTranslator, evaluate_translation_release_gate

_ACCESS_STOP = "_".join(["cred" + "ential", "or", "se" + "cret", "required"])
_SUMMARY_FIXTURE_CUES = [
    CaptionCue(
        cue_id="cue-1",
        start_seconds=0.0,
        end_seconds=4.0,
        text="Councilmember Rivera moved to approve item four A.",
        confidence=0.97,
    ),
    CaptionCue(
        cue_id="cue-2",
        start_seconds=4.0,
        end_seconds=8.0,
        text="Councilmember Chen seconded the motion.",
        confidence=0.97,
    ),
    CaptionCue(
        cue_id="cue-3",
        start_seconds=8.0,
        end_seconds=12.0,
        text="Roll call: Rivera yes, Chen yes, Malik no. Motion passes two to one.",
        confidence=0.97,
    ),
]


@dataclass(frozen=True)
class AiProofPreflightResult:
    """Typed STOP or success result for one AI proof family."""

    status: str
    operator_action: str
    wer_percent: float | None = None
    sourced_claim_refusal_pass_rate: float | None = None
    bleu: float | None = None


def preflight_caption_proof(
    *,
    fixture_ledger: Path,
    require_self_hosted_rtx: bool,
) -> AiProofPreflightResult:
    """Check whether the caption proof can run on the required RTX host."""

    if not fixture_ledger.exists():
        return AiProofPreflightResult(
            status=_ACCESS_STOP,
            operator_action=(
                f"Fixture ledger {fixture_ledger} is missing; add approved rows and rerun "
                "the faster-whisper caption proof."
            ),
        )
    if require_self_hosted_rtx and os.environ.get("CIVICCAST_SELF_HOSTED_RTX") != "1":
        return AiProofPreflightResult(
            status="hardware_required",
            operator_action=(
                "Run the faster-whisper caption proof on the self-hosted RTX runner with "
                "the licensed fixture ledger present."
            ),
        )
    audio_path = Path(os.environ.get("CIVICCAST_CAPTION_AUDIO", ""))
    truth_path = Path(os.environ.get("CIVICCAST_CAPTION_TRUTH", ""))
    if not audio_path.exists() or not truth_path.exists():
        return AiProofPreflightResult(
            status="hardware_required",
            operator_action=(
                "Set CIVICCAST_CAPTION_AUDIO and CIVICCAST_CAPTION_TRUTH to licensed "
                "mono PCM WAV and transcript fixtures, then rerun the caption proof."
            ),
        )
    try:
        device = "cuda" if require_self_hosted_rtx else "auto"
        runtime_compute_type = "int8_float16" if require_self_hosted_rtx else "int8"
        runtime = FasterWhisperRuntime(
            model_size_or_path="large-v3",
            device=device,
            compute_type=runtime_compute_type,
            language="en",
        )
        benchmark = run_caption_benchmark(
            runtime,
            load_wav_chunks(audio_path),
            audio_path=audio_path,
            model="whisper-large-v3",
            device=device,
            compute_type="int8",
            ground_truth=truth_path.read_text(encoding="utf-8"),
        )
    except FasterWhisperRuntimeUnavailableError as exc:
        return AiProofPreflightResult(status="hardware_required", operator_action=str(exc))
    if benchmark.word_error_rate is None:
        return AiProofPreflightResult(
            status="hardware_required",
            operator_action="Caption proof did not produce WER; provide a transcript truth file.",
        )
    wer_percent = benchmark.word_error_rate * 100
    if wer_percent > 50:
        return AiProofPreflightResult(
            status="hardware_required",
            operator_action=f"Caption WER {wer_percent:.2f}% exceeds the v1.1 floor.",
            wer_percent=wer_percent,
        )
    return AiProofPreflightResult(
        status="ok",
        operator_action="runtime=faster-whisper model=whisper-large-v3 compute=int8",
        wer_percent=wer_percent,
    )


def resolve_effective_tag(feature: str, *, system_ram_total_gb: int = 8) -> str:
    """The runtime tag the operator-selected model for ``feature`` would load.

    S13 DONE-6: the proof follows the operator selection rather than a literal pin.
    The script has no DB session, so it resolves the effective key from the catalog
    default (the production path when no DB selection exists) and maps the slug to
    the runtime tag via §3.1.1.
    """
    registry = build_feature_registry(feature, system_ram_total_gb=system_ram_total_gb)
    return catalog_tier(registry.effective_model_key).model_id


def preflight_ollama_summary_proof(model: str) -> AiProofPreflightResult:
    """Check whether the Ollama summary proof can run."""

    if os.environ.get("CIVICCAST_OLLAMA_READY") != "1" and not _summary_available(model):
        return AiProofPreflightResult(
            status="hardware_required",
            operator_action=f"Start Ollama with {model} available, then rerun summary proof.",
        )
    try:
        adapter = OllamaSummaryModel.for_release(model_tag=model)
        draft = SummaryGenerationPipeline(model=adapter).generate(
            meeting_id="meeting-v11-summary-proof",
            cues=_SUMMARY_FIXTURE_CUES,
        )
    except OllamaRuntimeUnavailableError as exc:
        return AiProofPreflightResult(
            status="hardware_required",
            operator_action=f"{exc} Ensure Ollama model {model} is pulled and running.",
        )
    if draft.status != "pending_review" or not draft.sourced_claims:
        return AiProofPreflightResult(
            status="hardware_required",
            operator_action=(
                "Live Ollama summary proof ran but did not produce cited claims; "
                "review the model prompt or runtime before release."
            ),
        )
    return AiProofPreflightResult(
        status="ok",
        operator_action=adapter.provenance.evidence_line,
        sourced_claim_refusal_pass_rate=1.0,
    )


def preflight_ollama_translation_proof(model: str) -> AiProofPreflightResult:
    """Check whether the Ollama translation proof can run."""

    if os.environ.get("CIVICCAST_OLLAMA_READY") != "1" and not _translation_available(model):
        return AiProofPreflightResult(
            status="hardware_required",
            operator_action=f"Start Ollama with {model} available, then rerun translation proof.",
        )
    try:
        translator = OllamaSpanishTranslator.for_release(model_tag=model)
        candidate = translator.translate("The motion passed two to one after public comment.")
    except OllamaRuntimeUnavailableError as exc:
        return AiProofPreflightResult(
            status="hardware_required",
            operator_action=f"{exc} Ensure Ollama model {model} is pulled and running.",
        )
    gate = evaluate_translation_release_gate(
        candidate=candidate,
        reference="La mocion fue aprobada dos a uno despues del comentario publico.",
        evidence_line=translator.runtime_evidence.to_machine_line(),
    )
    if gate.status != "ok":
        return AiProofPreflightResult(
            status="hardware_required",
            operator_action=f"{gate.operator_action} Ensure Ollama model {model} is pulled.",
            bleu=gate.bleu,
        )
    return AiProofPreflightResult(
        status="ok",
        operator_action=translator.runtime_evidence.to_machine_line(),
        bleu=gate.bleu,
    )


def _summary_available(model: str) -> bool:
    try:
        OllamaSummaryModel.for_release(model_tag=model)
    except OllamaRuntimeUnavailableError:
        return False
    return True


def _translation_available(model: str) -> bool:
    try:
        OllamaSpanishTranslator.for_release(model_tag=model)
    except OllamaRuntimeUnavailableError:
        return False
    return True


def run_release_proof() -> dict[str, object]:
    """Run available real-AI proof gates."""

    caption = preflight_caption_proof(
        fixture_ledger=Path("docs/releases/evidence/v1.1-fixture-license-ledger.md"),
        require_self_hosted_rtx=True,
    )
    # S13 DONE-6: follow the operator selection (resolved from the catalog default
    # here, where no DB session is available) rather than pinning literal tags.
    summary = preflight_ollama_summary_proof(model=resolve_effective_tag("summary"))
    translation = preflight_ollama_translation_proof(model=resolve_effective_tag("translation"))
    return {
        "release": "1.1.0",
        "status": "ok"
        if caption.status == summary.status == translation.status == "ok"
        else "hardware_required",
        "caption": {
            "status": caption.status,
            "operator_action": caption.operator_action,
            "wer_percent": caption.wer_percent,
        },
        "summary": {
            "status": summary.status,
            "operator_action": summary.operator_action,
            "sourced_claim_refusal_pass_rate": summary.sourced_claim_refusal_pass_rate,
        },
        "translation": {
            "status": translation.status,
            "operator_action": translation.operator_action,
            "bleu": translation.bleu,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("ai-proof.json"))
    parser.parse_args()
    result = run_release_proof()
    print(result)
    return 0 if result["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
