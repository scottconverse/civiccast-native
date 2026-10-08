# SPDX-License-Identifier: Apache-2.0
"""Current caption startup reset error contract."""

from types import SimpleNamespace

import pytest

from civiccast.captions import tap_worker as tap
from civiccast.captions.review import InMemoryCaptionReviewStore


def test_session_reset_preserves_original_error(tmp_path, monkeypatch):
    monkeypatch.setenv("CIVICCAST_CAPTION_TAP", "inline")
    monkeypatch.setenv("CIVICCAST_CAPTION_TAP_DIR", str(tmp_path / "tap"))
    worker = tap.build_tap_worker(
        settings=tap.CaptionTapWorkerSettings.from_env(),
        runtime=SimpleNamespace(),
        review_store=InMemoryCaptionReviewStore(),
        caption_work_dir=tmp_path / "egress",
    )
    original = OSError("test reset failure")

    def fail(_channel):
        raise original

    monkeypatch.setattr(worker, "_begin_channel_session_locked", fail)
    with pytest.raises(OSError) as caught:
        worker.begin_channel_session("public")
    assert caught.value is original
