# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Destination contract simulation; this does not establish real YouTube delivery."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from civiccast.syndicate.live_output import YouTubeLiveOutput


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    process = Mock()
    process.poll.return_value = None
    launch = Mock(return_value=process)
    source = Mock(return_value=tmp_path / "government" / "playlist.m3u8")
    record = Mock()
    manager = YouTubeLiveOutput(source, record, launch=launch)
    monkeypatch.setattr(manager._supervisor, "start", lambda: None)
    client = Mock()
    client.configure_live.return_value = (
        "broadcast",
        "stream",
        "rtmps://a.rtmps.youtube.com/live2/private-key",
    )
    client.live_status.return_value = ("active", "live")
    yield SimpleNamespace(
        manager=manager, process=process, launch=launch, source=source, record=record, client=client
    )
    manager.close()


def test_selected_channel_output_requires_destination_confirmation(output):
    proof = output.manager.start(
        output.client, asset_id="meeting", title="Council meeting", channel_id="government"
    )
    assert proof.delivery_state == "starting" and not proof.confirmed_live
    assert proof.url == "https://www.youtube.com/watch?v=broadcast"
    assert "private-key" not in proof.model_dump_json()
    output.source.assert_called_once_with("government")
    output.client.configure_live.assert_called_once_with(title="Council meeting")
    args = output.launch.call_args.args[0]
    assert args[args.index("-i") + 1].endswith("government\\playlist.m3u8") or args[
        args.index("-i") + 1
    ].endswith("government/playlist.m3u8")
    assert args[-1].endswith("private-key")
    output.manager.run_once()
    confirmed = output.record.call_args.args[1]
    assert confirmed.delivery_state == "live" and confirmed.confirmed_live
    output.manager.run_once()
    assert output.record.call_args.args[1] == confirmed
    duplicate = output.manager.start(
        output.client, asset_id="meeting", title="Council meeting", channel_id="government"
    )
    assert duplicate.confirmed_live
    assert output.client.configure_live.call_count == 1 and output.launch.call_count == 1
    stopped = output.manager.stop("meeting")
    assert stopped.delivery_state == "stopped"
    output.process.terminate.assert_called()
    output.client.finish_live.assert_called_with("broadcast", "stream")


@pytest.mark.parametrize("failure", ["launch", "process", "destination", "timeout", "disconnect"])
def test_failure_never_reports_delivery_and_reaps_output(output, failure):
    if failure == "launch":
        output.launch.side_effect = RuntimeError("private-key must never escape")
    proof = output.manager.start(
        output.client, asset_id="meeting", title="Meeting", channel_id="government"
    )
    if failure == "process":
        output.process.poll.return_value = 1
    elif failure == "destination":
        output.client.live_status.side_effect = RuntimeError("private-key")
    elif failure == "timeout":
        output.client.live_status.return_value = ("inactive", "ready")
        output.manager._deliveries["meeting"].started -= 121
    elif failure == "disconnect":
        output.manager.run_once()
        output.client.live_status.return_value = ("inactive", "complete")
    output.manager.run_once()
    failed = output.record.call_args.args[1]
    assert failed.delivery_state == "failed" and "private-key" not in failed.model_dump_json()
    if failure != "disconnect":
        assert not failed.confirmed_live
    if failure != "launch":
        output.process.terminate.assert_called()
    else:
        assert proof.delivery_state == "failed"


def test_missing_source_does_not_create_remote_event(output):
    output.source.side_effect = ValueError("No fresh channel output")
    with pytest.raises(ValueError, match="No fresh"):
        output.manager.start(
            output.client, asset_id="meeting", title="Meeting", channel_id="education"
        )
    output.client.configure_live.assert_not_called()


def test_unconfirmed_stop_does_not_invent_delivery(output):
    output.manager.start(
        output.client, asset_id="meeting", title="Meeting", channel_id="government"
    )
    stopped = output.manager.stop("meeting")
    assert stopped.delivery_state == "stopped" and not stopped.confirmed_live


def test_close_preserves_failed_terminal_status(output):
    output.launch.side_effect = RuntimeError("launch failed")
    output.manager.start(
        output.client, asset_id="meeting", title="Meeting", channel_id="government"
    )
    output.manager.close()
    output.manager.run_once()
    assert output.record.call_args.args[1].delivery_state == "failed"


def test_channel_wiring_persists_lifecycle_without_changing_portal(monkeypatch, tmp_path):
    from datetime import UTC, datetime

    from civiccast.egress.router import get_egress_store
    from civiccast.publish.models import PublishRunRecord, PublishSurfaceStatus
    from civiccast.publish.store import InMemoryPublishStore
    from civiccast.syndicate.live_wiring import build_youtube_output

    playlist = tmp_path / "playlist.m3u8"
    playlist.write_text("#EXTM3U\n")
    config = SimpleNamespace(enabled=True, sinks=[SimpleNamespace(kind="hls", uri=str(tmp_path))])
    egress = Mock()
    egress.get_config.return_value = config
    store = InMemoryPublishStore()
    surfaces = [
        PublishSurfaceStatus(
            id=surface_id,
            label=surface_id,
            kind=kind,
            state=state,
            approval="approved",
            required=False,
            health="ok",
            message="Initial",
            next_step="Wait",
        )
        for surface_id, kind, state in [
            ("portal", "canonical", "succeeded"),
            ("youtube-live", "reach", "running"),
        ]
    ]
    store.upsert_run(
        PublishRunRecord(
            asset_id="meeting",
            operator_id="operator",
            operator_display_name="Operator",
            approved_at=datetime.now(UTC),
            surfaces=surfaces,
        )
    )
    app = SimpleNamespace(
        dependency_overrides={get_egress_store: lambda: egress},
        state=SimpleNamespace(store_bundle=SimpleNamespace(publish_store=lambda: store)),
    )
    manager = build_youtube_output(app)
    process = Mock()
    process.poll.return_value = None
    monkeypatch.setattr(manager, "_launch", Mock(return_value=process))
    monkeypatch.setattr(manager._supervisor, "start", lambda: None)
    client = Mock()
    client.configure_live.return_value = (
        "broadcast",
        "stream",
        "rtmps://a.rtmps.youtube.com/live2/private",
    )
    client.live_status.return_value = ("active", "live")
    manager.start(client, asset_id="meeting", title="Meeting", channel_id="government")
    manager.run_once()
    row = store.get_run("meeting")
    assert row.surfaces[0] == surfaces[0]
    assert row.surfaces[1].state == "succeeded" and row.surfaces[1].delivery_state == "live"
    assert row.surfaces[1].url == "https://www.youtube.com/watch?v=broadcast"
    completed = row.surfaces[1].completed_at
    manager.run_once()
    assert store.get_run("meeting").surfaces[1].completed_at == completed
    manager.close()
    assert store.get_run("meeting").surfaces[1].delivery_state == "stopped"
    assert store.get_run("meeting").surfaces[0] == surfaces[0]


def test_legacy_ingest_proof_is_not_viewable_or_verified():
    from datetime import UTC, datetime

    from civiccast.publish.models import PublishRunRecord, PublishSurfaceStatus
    from civiccast.publish.service import build_publish_asset_status
    from civiccast.schedule.models import StaffAssetRow

    at = datetime.now(UTC)
    asset = StaffAssetRow(
        asset_id="meeting",
        title="Meeting",
        state="validated",
        manifest_url="https://station.example/video.m3u8",
        published_at=at,
        retention_policy="short",
        version=1,
    )
    surfaces = [
        PublishSurfaceStatus(
            id=surface_id,
            label=surface_id,
            kind=kind,
            state="succeeded",
            approval="approved",
            required=False,
            health="ok",
            message="Old proof",
            next_step="None",
            url=url,
        )
        for surface_id, kind, url in [
            ("portal", "canonical", "https://station.example/watch/meeting"),
            ("youtube-live", "reach", "rtmps://a.rtmps.youtube.com/live2/private-key"),
        ]
    ]
    run = PublishRunRecord(
        asset_id="meeting",
        operator_id="operator",
        operator_display_name="Operator",
        approved_at=at,
        surfaces=surfaces,
    )
    status = build_publish_asset_status(asset, run)
    assert status.surfaces[1].state == "unverified"
    assert status.surfaces[1].url is None
    assert "private-key" not in status.model_dump_json()
    assert status.surfaces[0].state == "succeeded"


def test_shutdown_reaps_all_senders_even_when_status_store_fails(output):
    for asset_id in ["first", "second"]:
        output.manager.start(
            output.client, asset_id=asset_id, title=asset_id, channel_id="government"
        )
    output.record.side_effect = RuntimeError("store unavailable")
    output.manager.close()
    assert output.process.terminate.call_count == 2
    assert output.client.finish_live.call_count == 2
