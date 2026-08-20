# SPDX-License-Identifier: Apache-2.0
"""Translation service tests for v0.9."""

from __future__ import annotations

import pytest

from civiccast.captions.hls import CaptionHlsTrack, attach_caption_tracks_to_package
from civiccast.captions.models import CaptionCue
from civiccast.stream.config import SLATE_RENDITION
from civiccast.stream.packager import SlateOnlyResult
from civiccast.translate import (
    DeterministicSpanishTranslator,
    PlaceholderIntegrityError,
    available_translation_models,
    translate_caption_cues,
    translated_hls_track,
)


def _cue(cue_id: str, text: str, start: float = 0.0, end: float = 2.0) -> CaptionCue:
    return CaptionCue(
        cue_id=cue_id,
        start_seconds=start,
        end_seconds=end,
        text=text,
        confidence=0.96,
    )


def test_model_registry_names_primary_and_alternate_models() -> None:
    models = {model.key: model for model in available_translation_models()}

    assert models["translate-gemma-4b-ollama"].role == "primary"
    assert models["translate-gemma-4b-ollama"].provider == "ollama"
    assert models["madlad-400"].role == "alternate"
    assert models["deterministic-es-ci"].provider == "local-deterministic"


def test_deterministic_translation_preserves_glossary_placeholders() -> None:
    result = translate_caption_cues(
        [_cue("cue-1", "Motion carries §§0001§§.")],
        provider=DeterministicSpanishTranslator(),
    )

    assert result.target_language == "es"
    assert result.within_latency_budget is True
    assert result.p95_latency_ms < 800
    assert result.cues[0].translated_text == "[es] Motion carries §§0001§§."
    assert "§§0001§§" in result.cues[0].translated_text


def test_placeholder_mutation_fails_closed() -> None:
    class BadTranslator:
        def translate_text(self, text: str, **_: object) -> str:
            return text.replace("§§0001§§", "0001")

    with pytest.raises(PlaceholderIntegrityError, match="protected glossary"):
        translate_caption_cues([_cue("cue-1", "Public comment §§0001§§")], provider=BadTranslator())


def test_translation_hls_track_writes_spanish_webvtt_and_manifest(tmp_path) -> None:
    output_dir = tmp_path / "hls"
    package = SlateOnlyResult(
        manifest_path=output_dir / "playlist.m3u8",
        slate_playlist_path=output_dir / "slate" / "playlist.m3u8",
        output_dir=output_dir,
    )
    package.slate_playlist_path.parent.mkdir(parents=True)
    package.slate_playlist_path.write_text("#EXTM3U\n#EXT-X-ENDLIST\n", encoding="utf-8")
    result = translate_caption_cues(
        [_cue("cue-1", "welcome to the council meeting")],
        provider=DeterministicSpanishTranslator(),
    )

    outputs = attach_caption_tracks_to_package(
        package,
        [
            CaptionHlsTrack(cues=[_cue("cue-1", "welcome to the council meeting")]),
            translated_hls_track(result),
        ],
        segment_duration=4,
    )

    assert [output.manifest_track.language for output in outputs] == ["en", "es"]
    manifest = package.manifest_path.read_text(encoding="utf-8")
    assert 'LANGUAGE="en",NAME="English",DEFAULT=YES' in manifest
    assert 'LANGUAGE="es",NAME="Spanish",DEFAULT=NO' in manifest
    assert "captions/es/playlist.m3u8" in manifest
    assert "bienvenidos a la reunion del consejo" in (
        output_dir / "captions" / "es" / "seg000.vtt"
    ).read_text(encoding="utf-8")
    assert SLATE_RENDITION.name == "slate"
