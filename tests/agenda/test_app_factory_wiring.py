from __future__ import annotations

from civiccast.app import _make_agenda_chapter_provider
from civiccast.schedule.models import Chapter, StaffAssetRow


def test_production_agenda_chapter_provider_accepts_staff_asset_chapter_models() -> None:
    expected = [
        Chapter(t=0, name="Call to order"),
        Chapter(t=60, name="Public comment"),
    ]
    row = StaffAssetRow(
        asset_id="meeting-1",
        title="Council meeting",
        state="validated",
        chapters=expected,
    )

    class AssetStore:
        def get_staff_row(self, asset_id: str) -> StaffAssetRow | None:
            assert asset_id == "meeting-1"
            return row

    chapters = _make_agenda_chapter_provider(AssetStore())("meeting-1")

    assert chapters == expected


def test_production_agenda_chapters_follow_trimmed_playback_timeline() -> None:
    original = [
        Chapter(t=0, name="Discarded head"),
        Chapter(t=2, name="Opening"),
        Chapter(t=32, name="Discussion"),
        Chapter(t=65, name="Discarded tail"),
    ]
    row = StaffAssetRow(
        asset_id="meeting-1",
        title="Recorded meeting",
        state="recorded",
        trim_in_seconds=2,
        trim_out_seconds=65,
        chapters=original,
    )

    class AssetStore:
        def get_staff_row(self, asset_id: str) -> StaffAssetRow:
            return row

    chapters = _make_agenda_chapter_provider(AssetStore())("meeting-1")

    assert chapters == [Chapter(t=0, name="Opening"), Chapter(t=30, name="Discussion")]
    assert row.chapters == original
