# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Static proof for native OTT empty-channel states."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_android_tv_and_fire_tv_render_empty_channel_guidance() -> None:
    for relative in [
        "civiccast/apps/ott-native/android-tv/app/src/main/java/com/civiccast/tv/MainBrowseFragment.kt",
        "civiccast/apps/ott-native/fire-tv/app/src/main/java/com/civiccast/firetv/MainBrowseFragment.kt",
    ]:
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "channels.isEmpty()" in source
        assert "renderNotice(getString(R.string.empty_channels))" in source

    for relative in [
        "civiccast/apps/ott-native/android-tv/app/src/main/res/values/strings.xml",
        "civiccast/apps/ott-native/fire-tv/app/src/main/res/values/strings.xml",
    ]:
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "No channels are configured yet" in source
        assert "operator console" in source


def test_roku_empty_state_does_not_publish_fake_placeholder_channels() -> None:
    source = (ROOT / "civiccast/apps/ott-native/roku/components/CivicCastScene.brs").read_text(
        encoding="utf-8"
    )

    assert "showEmptyState" in source
    assert "No channels configured" in source
    assert "Public" not in source
    assert "Education" not in source
    assert "Government" not in source
