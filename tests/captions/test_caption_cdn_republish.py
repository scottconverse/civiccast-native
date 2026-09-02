# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""A CDN-served recording gets its caption tracks, not just the local copy.

``attach_reviewed_captions`` writes to local disk. For a station whose VOD
package was pushed to a CDN when it finalized -- before caption review
finished -- the copy residents actually watch still has the pre-caption
manifest. These tests pin that the offline caption job re-publishes the
rewritten manifest and both language tracks to that CDN before it calls the
job complete, and that it does nothing (rather than something wrong) when
the package was never CDN-published.

The CDN is a mock adapter satisfying ``CDNAdapter`` structurally, the same
way the caption suites fake the model runtime: the real republish code,
real caption attach, real manifest rewrite, only the network boundary
replaced.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from civiccast.captions.cdn_republish import VodPackageCdnRepublisher, caption_artifact_paths
from civiccast.captions.models import CaptionCue
from civiccast.captions.vod import attach_reviewed_captions
from civiccast.stream.cdn.package_upload import CdnPackageTarget

_ASSET_ID = "council-2026-08-16"
_PREFIX = "live/ls_abc123"
_BASE_URL = "https://cdn.example.org"


class _MockCdnAdapter:
    """Records every upload, in order, and serves predictable public URLs."""

    def __init__(self) -> None:
        self.uploads: list[tuple[str, bytes]] = []

    def upload_file(self, local_path: Path, remote_key: str) -> str:
        self.uploads.append((remote_key, local_path.read_bytes()))
        return self.public_url(remote_key)

    def delete_file(self, remote_key: str) -> None:  # pragma: no cover - unused here
        raise AssertionError("caption republish must never delete CDN objects")

    def public_url(self, remote_key: str) -> str:
        return f"{_BASE_URL}/{remote_key}"

    def health_check(self) -> bool:  # pragma: no cover - unused here
        return True

    @property
    def uploaded_keys(self) -> list[str]:
        return [key for key, _ in self.uploads]


def _cue(cue_id: str, text: str) -> CaptionCue:
    return CaptionCue(cue_id=cue_id, start_seconds=0.0, end_seconds=1.8, text=text, confidence=0.95)


def _package(root: Path) -> Path:
    """Write the minimum real HLS package caption attach can rewrite."""

    package_dir = root / _ASSET_ID
    (package_dir / "720p").mkdir(parents=True, exist_ok=True)
    (package_dir / "720p" / "playlist.m3u8").write_text(
        "#EXTM3U\n#EXT-X-ENDLIST\n", encoding="utf-8"
    )
    (package_dir / "playlist.m3u8").write_text(
        "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=2500000\n720p/playlist.m3u8\n", encoding="utf-8"
    )
    return package_dir


def _attach_both(package_dir: Path):
    return attach_reviewed_captions(
        package_dir,
        [_cue("cue-000000", "motion carries")],
        spanish_cues=[_cue("cue-000000:es", "la mocion se aprueba")],
    )


@pytest.fixture()
def package(tmp_path: Path) -> Path:
    return _package(tmp_path / "packages")


class TestVodPackageCdnRepublisher:
    def test_republishes_manifest_and_both_language_tracks(self, package: Path) -> None:
        attached = _attach_both(package)
        adapter = _MockCdnAdapter()
        republisher = VodPackageCdnRepublisher(
            lambda: adapter,
            lambda asset_id: CdnPackageTarget(
                prefix=_PREFIX,
                recorded_manifest_url=f"{_BASE_URL}/{_PREFIX}/playlist.m3u8",
            ),
        )

        url = republisher.republish(asset_id=_ASSET_ID, package_dir=package, attached=attached)

        assert url == f"{_BASE_URL}/{_PREFIX}/playlist.m3u8"
        keys = adapter.uploaded_keys
        # Both languages' segmented tracks and both flat sidecars went up.
        assert f"{_PREFIX}/captions/en/playlist.m3u8" in keys
        assert f"{_PREFIX}/captions/es/playlist.m3u8" in keys
        assert f"{_PREFIX}/captions/captions.vtt" in keys
        assert f"{_PREFIX}/captions/captions.es.vtt" in keys
        # The manifest is LAST, so a resident can never fetch a manifest
        # naming a caption track the CDN does not have yet.
        assert keys[-1] == f"{_PREFIX}/playlist.m3u8"
        assert keys.count(f"{_PREFIX}/playlist.m3u8") == 1

    def test_republished_manifest_declares_both_tracks(self, package: Path) -> None:
        """What lands on the CDN is the REWRITTEN manifest, not the old one."""

        attached = _attach_both(package)
        adapter = _MockCdnAdapter()
        VodPackageCdnRepublisher(
            lambda: adapter,
            lambda asset_id: CdnPackageTarget(
                prefix=_PREFIX,
                recorded_manifest_url=f"{_BASE_URL}/{_PREFIX}/playlist.m3u8",
            ),
        ).republish(asset_id=_ASSET_ID, package_dir=package, attached=attached)

        manifest_key = f"{_PREFIX}/playlist.m3u8"
        body = next(
            payload.decode("utf-8") for key, payload in adapter.uploads if key == manifest_key
        )
        assert body.count("#EXT-X-MEDIA:TYPE=SUBTITLES") == 2
        assert 'LANGUAGE="en"' in body
        assert 'LANGUAGE="es"' in body

        spanish_vtt = next(
            payload.decode("utf-8")
            for key, payload in adapter.uploads
            if key == f"{_PREFIX}/captions/captions.es.vtt"
        )
        assert "la mocion se aprueba" in spanish_vtt

    def test_uploads_only_caption_artifacts_not_the_video_segments(self, package: Path) -> None:
        attached = _attach_both(package)
        adapter = _MockCdnAdapter()
        VodPackageCdnRepublisher(
            lambda: adapter,
            lambda asset_id: CdnPackageTarget(
                prefix=_PREFIX,
                recorded_manifest_url=f"{_BASE_URL}/{_PREFIX}/playlist.m3u8",
            ),
        ).republish(asset_id=_ASSET_ID, package_dir=package, attached=attached)

        # The 720p rendition is unchanged by captioning and must not be
        # re-uploaded -- a council meeting's segments are gigabytes.
        assert not any(key.startswith(f"{_PREFIX}/720p/") for key in adapter.uploaded_keys)

    def test_no_cdn_configured_is_a_no_op(self, package: Path) -> None:
        attached = _attach_both(package)
        called: list[str] = []

        def _lookup(asset_id: str) -> CdnPackageTarget | None:
            called.append(asset_id)
            return None

        assert (
            VodPackageCdnRepublisher(lambda: None, _lookup).republish(
                asset_id=_ASSET_ID, package_dir=package, attached=attached
            )
            is None
        )
        # Short-circuits before even asking the database.
        assert called == []

    def test_package_never_published_to_a_cdn_is_a_no_op(self, package: Path) -> None:
        attached = _attach_both(package)
        adapter = _MockCdnAdapter()

        assert (
            VodPackageCdnRepublisher(lambda: adapter, lambda asset_id: None).republish(
                asset_id=_ASSET_ID, package_dir=package, attached=attached
            )
            is None
        )
        assert adapter.uploads == []

    def test_a_locally_served_package_is_left_alone(self, package: Path) -> None:
        """A recorded manifest URL that is not this CDN's means: don't touch it.

        The finalization worker stores a LOCAL portal URL when no CDN was
        configured at the time. Uploading caption files to a prefix whose
        video segments were never uploaded would publish a broken package.
        """

        attached = _attach_both(package)
        adapter = _MockCdnAdapter()

        assert (
            VodPackageCdnRepublisher(
                lambda: adapter,
                lambda asset_id: CdnPackageTarget(
                    prefix=_PREFIX,
                    recorded_manifest_url=(
                        "http://127.0.0.1:8000/media/vod/council-2026-08-16/playlist.m3u8"
                    ),
                ),
            ).republish(asset_id=_ASSET_ID, package_dir=package, attached=attached)
            is None
        )
        assert adapter.uploads == []

    def test_caption_artifact_paths_skips_files_that_are_not_there(self, package: Path) -> None:
        attached = _attach_both(package)
        # English-only attach has no Spanish sidecar to enumerate.
        english_only = attach_reviewed_captions(package, [_cue("cue-000000", "motion carries")])
        assert english_only.spanish_sidecar_path is None
        assert all(path.is_file() for path in caption_artifact_paths(package, attached))
        assert attached.spanish_sidecar_path in caption_artifact_paths(package, attached)
