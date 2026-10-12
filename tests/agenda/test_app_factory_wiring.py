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
