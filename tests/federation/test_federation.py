# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Configured-station federation and actual two-ASGI-station boundaries."""

import asyncio
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from civiccast.app import create_app
from civiccast.egress.models import EgressConfig, EgressHealthSample, EgressSinkSpec, EgressStateRow
from civiccast.egress.router import get_egress_store
from civiccast.egress.store import InMemoryEgressStore
from civiccast.federation.models import FederationConfig, RemoteCommandRequest, StationPeer
from civiccast.federation.service import FederationError, FederationService
from civiccast.schedule.router import get_asset_store
from civiccast.vod.models import AssetMetadata
from civiccast.vod.store import InMemoryAssetStore

ADMIN = {"Authorization": "Bearer central-admin"}


@pytest.fixture
def federated(monkeypatch):
    monkeypatch.setenv("CIVICCAST_ALLOW_DETERMINISTIC_STAFF_TOKEN", "1")
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS",
        "central-admin:central:Central:admin;peer-token:remote:Remote:meeting_operator;publisher:pub:Publisher:publish_operator;records:rec:Records:records_clerk",
    )
    monkeypatch.setenv("TEST_FEDERATION_TOKEN", "peer-token")
    remote = create_app()
    assets = InMemoryAssetStore()
    for asset_id, published in (("published-program", True), ("private-program", False)):
        assets.create(
            AssetMetadata(
                asset_id=asset_id,
                title=asset_id,
                manifest_url=f"/media/vod/{asset_id}/playlist.m3u8",
                published_at=datetime.now(UTC) if published else None,
                duration_seconds=15,
            )
        )
    store = InMemoryEgressStore()
    for channel_id in ("public", "hidden"):
        store.upsert_config(
            EgressConfig(
                channel_id=channel_id,
                enabled=True,
                slate_message="Test station",
                sinks=[EgressSinkSpec(kind="file", label="Test", uri="test.ts")],
            )
        )
    store.write_state(
        EgressStateRow(channel_id="public", state="STOPPED", updated_at=datetime.now(UTC))
    )
    store.append_health(
        EgressHealthSample(channel_id="public", sampled_at=datetime.now(UTC), state="STOPPED")
    )
    remote.dependency_overrides[get_asset_store] = lambda: assets
    remote.dependency_overrides[get_egress_store] = lambda: store
    seen = []

    @remote.middleware("http")
    async def capture(request, call_next):
        seen.append((request.url.path, request.headers.get("Authorization")))
        return await call_next(request)

    config = FederationConfig(
        stations=[
            StationPeer(
                station_id="neighbor",
                label="Neighbor",
                public_origin="https://watch.station.test",
                staff_origin="https://staff.station.test",
                token_env="TEST_FEDERATION_TOKEN",
                channel_ids=["public"],
            )
        ]
    )
    central = create_app()
    central.state.federation_service = FederationService(
        config, transport=httpx.ASGITransport(app=remote)
    )
    return TestClient(central), store, seen


def test_two_stations_share_only_published_catalog_and_queue_real_remote_control(federated):
    client, store, seen = federated
    stations = client.get("/api/staff/federation/stations", headers=ADMIN)
    assert stations.status_code == 200
    assert stations.json()[0]["control_configured"] is True
    assert "peer-token" not in stations.text and "token_env" not in stations.text
    catalog = client.get("/api/staff/federation/stations/neighbor/catalog", headers=ADMIN)
    assert catalog.status_code == 200
    assert [item["asset_id"] for item in catalog.json()["items"]] == ["published-program"]
    assert (
        catalog.json()["items"][0]["portal_url"]
        == "https://watch.station.test/#/watch/published-program"
    )
    assert seen[-1] == ("/api/public/assets", None)
    channels = client.get("/api/staff/federation/stations/neighbor/channels", headers=ADMIN)
    assert channels.status_code == 200
    assert [row["channel_id"] for row in channels.json()["channels"]] == ["public"]
    assert channels.json()["channels"][0]["last_health_at"]
    assert seen[-1] == ("/api/staff/egress/channels", "Bearer peer-token")
    started = client.post(
        "/api/staff/federation/stations/neighbor/channels/public/commands",
        headers=ADMIN,
        json={"action": "start"},
    )
    assert started.status_code == 202
    assert started.json()["queued"] is True
    assert "confirm execution" in started.json()["message"]
    assert store.read_state("public").state == "STOPPED"  # acknowledgment is not execution
    queued = store.pop_pending_commands("public")
    assert len(queued) == 1 and queued[0].action == "start" and queued[0].issued_by == "remote"


def test_remote_stop_requires_confirmation_and_commands_are_allowlisted(federated):
    client, store, _ = federated
    path = "/api/staff/federation/stations/neighbor/channels/public/commands"
    assert client.post(path, headers=ADMIN, json={"action": "stop"}).status_code == 422
    assert client.post(path, headers=ADMIN, json={"action": "reload"}).status_code == 422
    assert store.pop_pending_commands("public") == []
    assert (
        client.post(path, headers=ADMIN, json={"action": "stop", "confirm_stop": True}).status_code
        == 202
    )
    assert store.pop_pending_commands("public")[0].action == "stop"
    assert (
        client.post(
            path.replace("/public/", "/hidden/"), headers=ADMIN, json={"action": "start"}
        ).status_code
        == 404
    )


def test_local_roles_and_remote_authorization_both_remain_enforced(federated, monkeypatch):
    client, store, _ = federated
    base = "/api/staff/federation/stations"
    assert client.get(base).status_code == 401
    assert client.get(base, headers={"Authorization": "Bearer records"}).status_code == 403
    assert client.get(base, headers={"Authorization": "Bearer publisher"}).status_code == 200
    command = base + "/neighbor/channels/public/commands"
    assert (
        client.post(
            command, headers={"Authorization": "Bearer publisher"}, json={"action": "start"}
        ).status_code
        == 403
    )
    monkeypatch.setenv("TEST_FEDERATION_TOKEN", "publisher")
    response = client.post(command, headers=ADMIN, json={"action": "start"})
    assert response.status_code == 502
    assert "refused authorization" in response.text
    assert store.pop_pending_commands("public") == []


@pytest.mark.parametrize(
    "origin",
    [
        "http://station.test",
        "https://token@station.test",
        "https://station.test/path",
        "https://station.test?key=secret",
        "https://station.test/#x",
        "https://station.test\\@evil.test",
        "https://169.254.169.254",
        "https://station.test\n",
    ],
)
def test_peer_addresses_cannot_smuggle_paths_credentials_or_insecure_transport(origin):
    with pytest.raises(ValidationError):
        StationPeer(station_id="bad", label="Bad", public_origin=origin)


@pytest.mark.parametrize("kind", ["redirect", "oversize", "malformed", "refusal", "timeout"])
def test_peer_failures_are_bounded_and_never_echo_remote_secrets(kind):
    seen = []

    def handle(request):
        seen.append(request)
        if kind == "timeout":
            raise httpx.ReadTimeout("secret-value", request=request)
        if kind == "redirect":
            return httpx.Response(302, headers={"Location": "https://untrusted.test/secret-value"})
        if kind == "oversize":
            return httpx.Response(200, content=b"x" * 1_048_577)
        if kind == "refusal":
            return httpx.Response(403, text="secret-value")
        return httpx.Response(200, text="secret-value")

    peer = StationPeer(
        station_id="neighbor", label="Neighbor", public_origin="https://station.test"
    )
    service = FederationService(
        FederationConfig(stations=[peer]), transport=httpx.MockTransport(handle)
    )
    with pytest.raises(FederationError) as error:
        asyncio.run(service.catalog("neighbor"))
    assert error.value.status == 502
    assert "secret-value" not in str(error.value)
    assert len(seen) == 1
    assert "authorization" not in seen[0].headers


def test_unknown_station_and_missing_credential_never_make_network_requests(monkeypatch):
    monkeypatch.delenv("MISSING_PEER_TOKEN", raising=False)

    def never(request):
        pytest.fail("unconfigured access must not contact the network")

    peer = StationPeer(
        station_id="neighbor",
        label="Neighbor",
        public_origin="https://watch.test",
        staff_origin="https://staff.test",
        token_env="MISSING_PEER_TOKEN",
        channel_ids=["public"],
    )
    service = FederationService(
        FederationConfig(stations=[peer]), transport=httpx.MockTransport(never)
    )
    with pytest.raises(FederationError, match="not found"):
        asyncio.run(service.catalog("unknown"))
    with pytest.raises(FederationError, match="not configured"):
        asyncio.run(service.command("neighbor", "public", RemoteCommandRequest(action="start")))


def test_federation_without_config_has_truthful_empty_station_list(monkeypatch):
    monkeypatch.delenv("CIVICCAST_STAFF_TOKENS", raising=False)
    monkeypatch.setenv("CIVICCAST_ALLOW_DETERMINISTIC_STAFF_TOKEN", "1")
    response = TestClient(create_app()).get(
        "/api/staff/federation/stations", headers={"Authorization": "Bearer operator-token-a"}
    )
    assert response.status_code == 200
    assert response.json() == []
