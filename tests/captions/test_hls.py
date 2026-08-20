from pathlib import Path

import pytest

from civiccast.captions.hls import (
    CaptionHlsTrack,
    attach_caption_tracks_to_package,
    write_hls_caption_track,
)
from civiccast.captions.models import CaptionCue
from civiccast.stream.config import ABR_LADDER, SLATE_RENDITION
from civiccast.stream.packager import RenditionOutput, SlateOnlyResult, VodPackageResult


def _cue(cue_id: str, start: float, end: float, text: str) -> CaptionCue:
    return CaptionCue(
        cue_id=cue_id,
        start_seconds=start,
        end_seconds=end,
        text=text,
        confidence=0.94,
    )


def _stub_vod_package(tmp_path: Path) -> VodPackageResult:
    output_dir = tmp_path / "hls"
    renditions: list[RenditionOutput] = []
    for config in [*ABR_LADDER, SLATE_RENDITION]:
        playlist = output_dir / config.name / "playlist.m3u8"
        playlist.parent.mkdir(parents=True, exist_ok=True)
        playlist.write_text("#EXTM3U\n#EXT-X-ENDLIST\n", encoding="utf-8")
        renditions.append(RenditionOutput(config=config, playlist_path=playlist))
    manifest = output_dir / "playlist.m3u8"
    manifest.write_text("#EXTM3U\n", encoding="utf-8")
    return VodPackageResult(manifest_path=manifest, renditions=renditions, output_dir=output_dir)


class TestWriteHlsCaptionTrack:
    def test_writes_segment_playlist_and_webvtt_files(self, tmp_path: Path) -> None:
        output = write_hls_caption_track(
            CaptionHlsTrack(
                cues=[
                    _cue("cue-1", 0.2, 1.8, "Meeting called to order."),
                    _cue("cue-2", 2.1, 3.9, "Roll call begins."),
                ]
            ),
            tmp_path,
            segment_duration=2,
        )

        assert output.playlist_path == tmp_path / "captions" / "en" / "playlist.m3u8"
        assert output.playlist_uri == "captions/en/playlist.m3u8"
        assert [p.name for p in output.segment_paths] == ["seg000.vtt", "seg001.vtt"]
        assert "seg000.vtt" in output.playlist_path.read_text(encoding="utf-8")
        assert "Meeting called to order." in output.segment_paths[0].read_text(encoding="utf-8")
        assert "Roll call begins." in output.segment_paths[1].read_text(encoding="utf-8")

    def test_starts_at_segment_zero_to_preserve_hls_timeline(self, tmp_path: Path) -> None:
        output = write_hls_caption_track(
            CaptionHlsTrack(cues=[_cue("cue-late", 65.1, 66.4, "Late cue.")]),
            tmp_path,
            segment_duration=2,
        )

        assert output.segment_paths[0].name == "seg000.vtt"
        assert output.segment_paths[-1].name == "seg033.vtt"
        assert "Late cue." in output.segment_paths[-1].read_text(encoding="utf-8")

    def test_sanitizes_language_for_directory_only(self, tmp_path: Path) -> None:
        output = write_hls_caption_track(
            CaptionHlsTrack(
                cues=[_cue("cue-1", 0, 1, "Hola.")],
                language="es-US",
                name="Spanish",
            ),
            tmp_path,
        )

        assert output.playlist_uri == "captions/es-us/playlist.m3u8"
        assert output.manifest_track.language == "es-US"
        assert output.manifest_track.name == "Spanish"

    def test_rejects_invalid_segment_duration(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="segment_duration"):
            write_hls_caption_track(
                CaptionHlsTrack(cues=[_cue("cue-1", 0, 1, "Hello.")]),
                tmp_path,
                segment_duration=0,
            )


class TestAttachCaptionTracksToPackage:
    def test_rewrites_vod_manifest_with_subtitle_track(self, tmp_path: Path) -> None:
        package = _stub_vod_package(tmp_path)
        outputs = attach_caption_tracks_to_package(
            package,
            [CaptionHlsTrack(cues=[_cue("cue-1", 0, 1, "Motion carries.")])],
        )

        manifest = package.manifest_path.read_text(encoding="utf-8")
        assert outputs[0].playlist_path.exists()
        assert "#EXT-X-MEDIA:TYPE=SUBTITLES" in manifest
        assert 'SUBTITLES="subtitles"' in manifest
        assert "captions/en/playlist.m3u8" in manifest
        assert manifest.count("#EXT-X-STREAM-INF:") == 5

    def test_rewrites_slate_only_manifest_with_subtitle_track(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "slate"
        playlist = output_dir / "slate" / "playlist.m3u8"
        playlist.parent.mkdir(parents=True, exist_ok=True)
        playlist.write_text("#EXTM3U\n#EXT-X-ENDLIST\n", encoding="utf-8")
        manifest = output_dir / "playlist.m3u8"
        manifest.write_text("#EXTM3U\n", encoding="utf-8")
        package = SlateOnlyResult(
            manifest_path=manifest,
            slate_playlist_path=playlist,
            output_dir=output_dir,
        )

        attach_caption_tracks_to_package(
            package,
            [CaptionHlsTrack(cues=[_cue("cue-1", 0, 1, "Fallback caption.")])],
        )

        manifest_text = manifest.read_text(encoding="utf-8")
        assert manifest_text.count("#EXT-X-STREAM-INF:") == 1
        assert "#EXT-X-MEDIA:TYPE=SUBTITLES" in manifest_text

    def test_rejects_empty_track_list(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="At least one"):
            attach_caption_tracks_to_package(_stub_vod_package(tmp_path), [])
