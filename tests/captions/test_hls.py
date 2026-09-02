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

    def test_two_subtitle_tracks_are_declared_distinctly(self, tmp_path: Path) -> None:
        """Recorded-Spanish: English + Spanish must each be a distinct,

        player-selectable subtitle rendition in the ONE manifest rewrite.
        The front end (HlsPlayer.tsx) renders one caption button per
        TYPE=SUBTITLES media line by NAME/LANGUAGE, so two lines with
        distinct LANGUAGE/NAME/URI are exactly what makes the Spanish button
        appear with no front-end change. English stays DEFAULT=YES so an
        unchanged player still lands on English.
        """

        package = _stub_vod_package(tmp_path)
        outputs = attach_caption_tracks_to_package(
            package,
            [
                CaptionHlsTrack(
                    cues=[_cue("cue-1", 0, 1, "Motion carries.")],
                    language="en",
                    name="English",
                    default=True,
                ),
                CaptionHlsTrack(
                    cues=[_cue("cue-1:es", 0, 1, "La mocion se aprueba.")],
                    language="es",
                    name="Spanish",
                    default=False,
                ),
            ],
        )

        manifest = package.manifest_path.read_text(encoding="utf-8")
        subtitle_lines = [
            line for line in manifest.splitlines() if line.startswith("#EXT-X-MEDIA:TYPE=SUBTITLES")
        ]
        assert len(subtitle_lines) == 2, manifest

        english = next(line for line in subtitle_lines if 'LANGUAGE="en"' in line)
        spanish = next(line for line in subtitle_lines if 'LANGUAGE="es"' in line)
        # Distinct language, name, and playlist URI -- the three things a
        # player uses to tell the two caption options apart.
        assert 'NAME="English"' in english and 'NAME="Spanish"' in spanish
        assert 'URI="captions/en/playlist.m3u8"' in english
        assert 'URI="captions/es/playlist.m3u8"' in spanish
        # Exactly one default track, and it is English.
        assert "DEFAULT=YES" in english
        assert "DEFAULT=NO" in spanish
        assert sum("DEFAULT=YES" in line for line in subtitle_lines) == 1
        # Both playlists were actually written to disk.
        assert {out.manifest_track.language for out in outputs} == {"en", "es"}
        assert (package.output_dir / "captions" / "en" / "playlist.m3u8").is_file()
        assert (package.output_dir / "captions" / "es" / "playlist.m3u8").is_file()
