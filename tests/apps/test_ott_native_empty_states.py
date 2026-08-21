# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Static proof for native OTT empty-channel states.

S12 de-duplication note: android-tv/ and fire-tv/ used to be two entire
copied source trees; they are now the single android/tv-app/ module built
as the "tv" and "firetv" product flavors (see civiccast/apps/ott-native/
android/README.md), so one assertion now covers both flavors' shared
Kotlin/resource source instead of two near-identical checks.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_android_tv_app_renders_empty_channel_guidance() -> None:
    source = (
        ROOT
        / "civiccast/apps/ott-native/android/tv-app/src/main/java/com/civiccast/tv/MainBrowseFragment.kt"
    ).read_text(encoding="utf-8")
    assert "channels.isEmpty()" in source
    assert "renderNotice(getString(R.string.empty_channels))" in source

    strings = (
        ROOT / "civiccast/apps/ott-native/android/tv-app/src/main/res/values/strings.xml"
    ).read_text(encoding="utf-8")
    assert "No channels are configured yet" in strings
    assert "operator console" in strings


def test_roku_empty_state_does_not_publish_fake_placeholder_channels() -> None:
    source = (ROOT / "civiccast/apps/ott-native/roku/components/CivicCastScene.brs").read_text(
        encoding="utf-8"
    )

    assert "showEmptyState" in source
    assert "No channels configured" in source
    assert "Public" not in source
    assert "Education" not in source
    assert "Government" not in source
