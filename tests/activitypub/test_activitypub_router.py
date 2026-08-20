# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""ActivityPub public router contracts for enabled federation."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from civiccast.activitypub.keys import (
    generate_activitypub_private_key,
    load_activitypub_private_key,
    public_key_pem_from_private_key_path,
)
from civiccast.activitypub.remote import DeliveryResult, RemoteActor
from civiccast.activitypub.signatures import signed_request_headers, verify_http_signature
from civiccast.app import create_app


class FakeActorFetcher:
    def __init__(self, actors: dict[str, RemoteActor]) -> None:
        self.actors = actors

    def fetch(self, actor_url: str) -> RemoteActor:
        key = actor_url.split("#", 1)[0].rstrip("/")
        return self.actors[key]


class RecordingDeliveryClient:
    def __init__(self) -> None:
        self.deliveries: list[tuple[str, dict[str, Any]]] = []

    def deliver(self, *, inbox_url: str, activity: dict[str, Any]) -> DeliveryResult:
        self.deliveries.append((inbox_url, activity))
        return DeliveryResult(
            inbox_url=inbox_url,
            status_code=202,
            response_body="accepted",
            delivered_at=datetime.now(UTC),
        )


@pytest.fixture
def station_key_path(tmp_path: Path) -> Path:
    key_path = tmp_path / "station-activitypub.pem"
    generate_activitypub_private_key(key_path)
    return key_path


@pytest.fixture
def remote_key_path(tmp_path: Path) -> Path:
    key_path = tmp_path / "remote-activitypub.pem"
    generate_activitypub_private_key(key_path)
    return key_path


@pytest.fixture(autouse=True)
def activitypub_env(monkeypatch: pytest.MonkeyPatch, station_key_path: Path) -> None:
    monkeypatch.setenv("CIVICCAST_ACTIVITYPUB_HANDLE", "station")
    monkeypatch.setenv("CIVICCAST_ACTIVITYPUB_DISPLAY_NAME", "CivicCast Station")
    monkeypatch.setenv("CIVICCAST_ACTIVITYPUB_MODE", "open")
    monkeypatch.setenv("CIVICCAST_ACTIVITYPUB_BASE_URL", "http://testserver")
    monkeypatch.setenv("CIVICCAST_ACTIVITYPUB_PRIVATE_KEY_PATH", str(station_key_path))
    monkeypatch.setenv("CIVICCAST_ACTIVITYPUB_BLOCKLIST", "blocked.example")
    monkeypatch.setenv("CIVICCAST_ACTIVITYPUB_ALLOWLIST", "neighbor.example")
    monkeypatch.setenv("CIVICCAST_ACTIVITYPUB_INBOX_RATE_LIMIT", "10")


@pytest.fixture
def remote_actor(remote_key_path: Path) -> RemoteActor:
    return RemoteActor(
        actor_id="https://neighbor.example/users/alex",
        inbox="https://neighbor.example/users/alex/inbox",
        shared_inbox="https://neighbor.example/inbox",
        public_key_id="https://neighbor.example/users/alex#main-key",
        public_key_pem=public_key_pem_from_private_key_path(remote_key_path),
    )


@pytest.fixture
def blocked_actor(remote_key_path: Path) -> RemoteActor:
    return RemoteActor(
        actor_id="https://blocked.example/users/spam",
        inbox="https://blocked.example/users/spam/inbox",
        shared_inbox=None,
        public_key_id="https://blocked.example/users/spam#main-key",
        public_key_pem=public_key_pem_from_private_key_path(remote_key_path),
    )


@pytest.fixture
def delivery_client() -> RecordingDeliveryClient:
    return RecordingDeliveryClient()


@pytest.fixture
def client(
    remote_actor: RemoteActor,
    blocked_actor: RemoteActor,
    delivery_client: RecordingDeliveryClient,
) -> Iterator[TestClient]:
    app = create_app()
    app.state.activitypub_actor_fetcher = FakeActorFetcher(
        {
            remote_actor.actor_id: remote_actor,
            blocked_actor.actor_id: blocked_actor,
        }
    )
    app.state.activitypub_delivery_client = delivery_client
    with TestClient(app) as test_client:
        yield test_client


def _follow(actor: str = "https://neighbor.example/users/alex") -> dict[str, object]:
    return {
        "@context": "https://www.w3.org/ns/activitystreams",
        "id": f"{actor}/follows/civiccast",
        "type": "Follow",
        "actor": actor,
        "object": "http://testserver/ap/actor",
    }


def _undo_follow(actor: str = "https://neighbor.example/users/alex") -> dict[str, object]:
    return {
        "@context": "https://www.w3.org/ns/activitystreams",
        "id": f"{actor}/undo/civiccast-follow",
        "type": "Undo",
        "actor": actor,
        "object": _follow(actor),
    }


def _signed_post(
    client: TestClient,
    *,
    activity: dict[str, object],
    key_path: Path,
    key_id: str = "https://neighbor.example/users/alex#main-key",
):
    raw = json.dumps(activity, separators=(",", ":"), sort_keys=True).encode("utf-8")
    headers = signed_request_headers(
        method="POST",
        url="http://testserver/ap/inbox",
        body=raw,
        private_key=load_activitypub_private_key(key_path),
        key_id=key_id,
    )
    return client.post("/ap/inbox", content=raw, headers=headers)


class TestActivityPubDiscovery:
    def test_default_configuration_does_not_advertise_federation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CIVICCAST_ACTIVITYPUB_MODE", raising=False)
        monkeypatch.delenv("CIVICCAST_ACTIVITYPUB_PRIVATE_KEY_PATH", raising=False)
        monkeypatch.delenv("CIVICCAST_ACTIVITYPUB_BASE_URL", raising=False)
        with TestClient(create_app()) as test_client:
            response = test_client.get("/ap/actor")

        assert response.status_code == 404
        assert "disabled" in response.json()["detail"].lower()

    def test_webfinger_exposes_station_actor_from_configured_base_url(
        self, client: TestClient
    ) -> None:
        response = client.get(
            "/.well-known/webfinger",
            params={"resource": "acct:station@testserver"},
            headers={"Host": "host-spoof.example"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["subject"] == "acct:station@testserver"
        assert body["links"][0]["href"] == "http://testserver/ap/actor"

    def test_actor_document_uses_real_station_public_key(self, client: TestClient) -> None:
        response = client.get("/ap/actor")

        assert response.status_code == 200
        body = response.json()
        assert body["type"] == "Application"
        assert body["preferredUsername"] == "station"
        assert body["inbox"] == "http://testserver/ap/inbox"
        assert body["outbox"] == "http://testserver/ap/outbox"
        assert body["followers"] == "http://testserver/ap/followers"
        assert body["publicKey"]["owner"] == "http://testserver/ap/actor"
        assert "BEGIN PUBLIC KEY" in body["publicKey"]["publicKeyPem"]

    def test_nodeinfo_declares_enabled_activitypub(self, client: TestClient) -> None:
        response = client.get("/nodeinfo/2.0")

        assert response.status_code == 200
        body = response.json()
        assert "activitypub" in body["protocols"]
        assert body["metadata"]["externalFediverseProof"] == "available_when_enabled"


class TestActivityPubInbox:
    def test_unsigned_follow_is_rejected(self, client: TestClient) -> None:
        response = client.post("/ap/inbox", json=_follow())

        assert response.status_code == 401
        assert "signature" in response.json()["detail"].lower()

    def test_signed_open_follow_accepts_records_and_delivers_accept(
        self,
        client: TestClient,
        remote_key_path: Path,
        delivery_client: RecordingDeliveryClient,
    ) -> None:
        response = _signed_post(client, activity=_follow(), key_path=remote_key_path)

        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "accepted"
        assert "/accepts/" in body["activity_id"]

        followers = client.get("/ap/followers").json()
        assert followers["totalItems"] == 1
        assert followers["orderedItems"] == ["https://neighbor.example/users/alex"]
        assert delivery_client.deliveries[0][0] == "https://neighbor.example/inbox"
        assert delivery_client.deliveries[0][1]["type"] == "Accept"

    def test_signed_undo_follow_removes_accepted_follower(
        self,
        client: TestClient,
        remote_key_path: Path,
    ) -> None:
        accepted = _signed_post(client, activity=_follow(), key_path=remote_key_path)
        removed = _signed_post(client, activity=_undo_follow(), key_path=remote_key_path)

        assert accepted.status_code == 202
        assert removed.status_code == 202
        assert removed.json()["status"] == "removed"
        followers = client.get("/ap/followers").json()
        assert followers["totalItems"] == 0
        removed_followers = client.get(
            "/api/staff/activitypub/followers?status=removed",
            headers={"Authorization": "Bearer operator-token-a"},
        )
        status_body = client.get(
            "/api/staff/activitypub/status",
            headers={"Authorization": "Bearer operator-token-a"},
        ).json()

        assert removed_followers.status_code == 200
        assert removed_followers.json()["followers"][0]["status"] == "removed"
        assert status_body["followers"]["removed"] == 1
        assert status_body["followers"]["accepted"] == 0

    def test_blocklisted_instance_fails_closed(
        self, client: TestClient, remote_key_path: Path
    ) -> None:
        response = _signed_post(
            client,
            activity=_follow("https://blocked.example/users/spam"),
            key_path=remote_key_path,
            key_id="https://blocked.example/users/spam#main-key",
        )

        assert response.status_code == 403
        assert "blocked" in response.json()["detail"].lower()

    def test_limited_mode_requires_allowlist(
        self,
        monkeypatch: pytest.MonkeyPatch,
        remote_actor: RemoteActor,
        remote_key_path: Path,
        delivery_client: RecordingDeliveryClient,
    ) -> None:
        monkeypatch.setenv("CIVICCAST_ACTIVITYPUB_MODE", "limited")
        monkeypatch.setenv("CIVICCAST_ACTIVITYPUB_ALLOWLIST", "approved.example")
        app = create_app()
        app.state.activitypub_actor_fetcher = FakeActorFetcher(
            {remote_actor.actor_id: remote_actor}
        )
        app.state.activitypub_delivery_client = delivery_client
        with TestClient(app) as test_client:
            response = _signed_post(test_client, activity=_follow(), key_path=remote_key_path)

        assert response.status_code == 403
        assert "allowlist" in response.json()["detail"].lower()

    def test_approval_only_queues_follow_for_staff_approval(
        self,
        monkeypatch: pytest.MonkeyPatch,
        remote_actor: RemoteActor,
        remote_key_path: Path,
        delivery_client: RecordingDeliveryClient,
    ) -> None:
        monkeypatch.setenv("CIVICCAST_ACTIVITYPUB_MODE", "approval-only")
        app = create_app()
        app.state.activitypub_actor_fetcher = FakeActorFetcher(
            {remote_actor.actor_id: remote_actor}
        )
        app.state.activitypub_delivery_client = delivery_client
        with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as test_client:
            response = _signed_post(test_client, activity=_follow(), key_path=remote_key_path)
            followers = test_client.get("/ap/followers").json()
            pending = test_client.get("/api/staff/activitypub/followers?status=pending").json()
            approved = test_client.post(
                "/api/staff/activitypub/followers/approve",
                json={"actor": remote_actor.actor_id},
            )

        assert response.status_code == 202
        assert response.json()["status"] == "pending_operator_approval"
        assert followers["totalItems"] == 0
        assert pending["followers"][0]["status"] == "pending"
        assert approved.status_code == 200
        assert approved.json()["follower"]["status"] == "accepted"
        assert delivery_client.deliveries[0][1]["type"] == "Accept"

    def test_staff_rejects_pending_follow_with_signed_reject_delivery(
        self,
        monkeypatch: pytest.MonkeyPatch,
        remote_actor: RemoteActor,
        remote_key_path: Path,
        delivery_client: RecordingDeliveryClient,
    ) -> None:
        monkeypatch.setenv("CIVICCAST_ACTIVITYPUB_MODE", "approval-only")
        app = create_app()
        app.state.activitypub_actor_fetcher = FakeActorFetcher(
            {remote_actor.actor_id: remote_actor}
        )
        app.state.activitypub_delivery_client = delivery_client
        with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as test_client:
            response = _signed_post(test_client, activity=_follow(), key_path=remote_key_path)
            rejected = test_client.post(
                "/api/staff/activitypub/followers/reject",
                json={"actor": remote_actor.actor_id},
            )
            rejected_list = test_client.get("/api/staff/activitypub/followers?status=rejected")
            outbox = test_client.get("/api/staff/activitypub/outbox").json()
            deliveries = test_client.get("/api/staff/activitypub/deliveries").json()

        assert response.status_code == 202
        assert rejected.status_code == 200
        assert rejected.json()["follower"]["status"] == "rejected"
        assert rejected_list.json()["followers"][0]["status"] == "rejected"
        assert delivery_client.deliveries[0][1]["type"] == "Reject"
        assert outbox["outbox"][0]["activity"]["type"] == "Reject"
        assert deliveries["deliveries"][0]["status_code"] == 202

    def test_staff_status_reports_all_moderation_counts_and_delivery_evidence(
        self,
        client: TestClient,
        remote_key_path: Path,
    ) -> None:
        response = _signed_post(client, activity=_follow(), key_path=remote_key_path)
        assert response.status_code == 202

        status_response = client.get(
            "/api/staff/activitypub/status",
            headers={"Authorization": "Bearer operator-token-a"},
        )
        deliveries_response = client.get(
            "/api/staff/activitypub/deliveries",
            headers={"Authorization": "Bearer operator-token-a"},
        )

        assert status_response.status_code == 200
        status_body = status_response.json()
        assert status_body["enabled"] is True
        assert status_body["mode"] == "open"
        assert status_body["handle"] == "station"
        assert status_body["actor_url"] == "http://testserver/ap/actor"
        assert status_body["followers"] == {
            "pending": 0,
            "accepted": 1,
            "blocked": 0,
            "rejected": 0,
            "removed": 0,
        }
        assert status_body["outbox_items"] == 1
        assert status_body["delivery_attempts"] == 1
        assert deliveries_response.status_code == 200
        assert deliveries_response.json()["deliveries"][0]["status_code"] == 202

    def test_inbox_rate_limit_is_enforced(
        self, monkeypatch: pytest.MonkeyPatch, remote_key_path: Path, remote_actor: RemoteActor
    ) -> None:
        monkeypatch.setenv("CIVICCAST_ACTIVITYPUB_INBOX_RATE_LIMIT", "1")
        app = create_app()
        app.state.activitypub_actor_fetcher = FakeActorFetcher(
            {remote_actor.actor_id: remote_actor}
        )
        app.state.activitypub_delivery_client = RecordingDeliveryClient()
        with TestClient(app) as test_client:
            first = _signed_post(test_client, activity=_follow(), key_path=remote_key_path)
            second = _signed_post(test_client, activity=_follow(), key_path=remote_key_path)

        assert first.status_code == 202
        assert second.status_code == 429
        assert "try again" in second.json()["detail"].lower()


class TestAuthorizedFetch:
    def test_authorized_fetch_requires_signed_get(
        self, monkeypatch: pytest.MonkeyPatch, remote_actor: RemoteActor
    ) -> None:
        monkeypatch.setenv("CIVICCAST_ACTIVITYPUB_AUTHORIZED_FETCH", "1")
        app = create_app()
        app.state.activitypub_actor_fetcher = FakeActorFetcher(
            {remote_actor.actor_id: remote_actor}
        )
        app.state.activitypub_delivery_client = RecordingDeliveryClient()
        with TestClient(app) as test_client:
            response = test_client.get("/ap/outbox")

        assert response.status_code == 401
        assert "authorized fetch" in response.json()["detail"].lower()

    def test_authorized_fetch_accepts_signed_get(
        self,
        monkeypatch: pytest.MonkeyPatch,
        remote_actor: RemoteActor,
        remote_key_path: Path,
    ) -> None:
        monkeypatch.setenv("CIVICCAST_ACTIVITYPUB_AUTHORIZED_FETCH", "1")
        app = create_app()
        app.state.activitypub_actor_fetcher = FakeActorFetcher(
            {remote_actor.actor_id: remote_actor}
        )
        app.state.activitypub_delivery_client = RecordingDeliveryClient()
        headers = signed_request_headers(
            method="GET",
            url="http://testserver/ap/outbox",
            body=b"",
            private_key=load_activitypub_private_key(remote_key_path),
            key_id=remote_actor.public_key_id,
        )
        with TestClient(app) as test_client:
            response = test_client.get("/ap/outbox", headers=headers)

        assert response.status_code == 200


class TestOutboundSigning:
    def test_real_delivery_client_signs_outbound_posts(
        self,
        monkeypatch: pytest.MonkeyPatch,
        station_key_path: Path,
    ) -> None:
        from civiccast.activitypub.config import load_activitypub_config
        from civiccast.activitypub.remote import HttpxActivityPubDeliveryClient

        captured: dict[str, Any] = {}

        class FakeResponse:
            status_code = 202
            text = "accepted"

        def fake_post(url: str, *, content: bytes, headers: dict[str, str], **kwargs: Any):
            captured["url"] = url
            captured["content"] = content
            captured["headers"] = headers
            return FakeResponse()

        def fake_getaddrinfo(host: str, *args: Any, **kwargs: Any):
            if host == "neighbor.example":
                return [(2, 1, 6, "", ("93.184.216.34", 0))]
            return [(2, 1, 6, "", (host, 0))]

        monkeypatch.setattr("civiccast.activitypub.remote.httpx.post", fake_post)
        monkeypatch.setattr("civiccast.activitypub.remote._ORIGINAL_GETADDRINFO", fake_getaddrinfo)
        config = load_activitypub_config(
            {
                "CIVICCAST_ACTIVITYPUB_MODE": "open",
                "CIVICCAST_ACTIVITYPUB_BASE_URL": "https://station.example",
                "CIVICCAST_ACTIVITYPUB_PRIVATE_KEY_PATH": str(station_key_path),
            }
        )
        client = HttpxActivityPubDeliveryClient(config=config)

        client.deliver(
            inbox_url="https://neighbor.example/inbox",
            activity={"id": "https://station.example/ap/actor/activities/1", "type": "Create"},
        )

        assert captured["url"] == "https://neighbor.example/inbox"
        params = verify_http_signature(
            method="POST",
            path_and_query="/inbox",
            headers={key.lower(): value for key, value in captured["headers"].items()},
            body=captured["content"],
            public_key_pem=public_key_pem_from_private_key_path(station_key_path),
            require_digest=True,
        )
        assert params.key_id == "https://station.example/ap/actor#main-key"

    def test_local_http_remote_actor_is_lab_only(self) -> None:
        from civiccast.activitypub.remote import ActivityPubRemoteError, remote_actor_from_document

        document = {
            "id": "http://localhost:18080/users/civiccastpeer",
            "inbox": "http://localhost:18080/users/civiccastpeer/inbox",
            "publicKey": {
                "id": "http://localhost:18080/users/civiccastpeer#main-key",
                "publicKeyPem": "-----BEGIN PUBLIC KEY-----\nabc\n-----END PUBLIC KEY-----",
            },
        }

        with pytest.raises(ActivityPubRemoteError):
            remote_actor_from_document(
                document,
                expected_actor_url="http://localhost:18080/users/civiccastpeer",
            )
        parsed = remote_actor_from_document(
            document,
            expected_actor_url="http://localhost:18080/users/civiccastpeer",
            allow_http=True,
            allow_local=True,
        )

        assert parsed.actor_id == "http://localhost:18080/users/civiccastpeer"

    def test_remote_url_rejects_if_any_resolved_address_is_private(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from civiccast.activitypub.remote import ActivityPubRemoteError, _validate_remote_url

        def fake_getaddrinfo(host: str, *args: Any, **kwargs: Any):
            assert host == "neighbor.example"
            return [
                (2, 1, 6, "", ("93.184.216.34", 0)),
                (2, 1, 6, "", ("127.0.0.1", 0)),
            ]

        monkeypatch.setattr("civiccast.activitypub.remote._ORIGINAL_GETADDRINFO", fake_getaddrinfo)

        with pytest.raises(ActivityPubRemoteError):
            _validate_remote_url("https://neighbor.example/users/alex", allow_http=False)

    def test_real_delivery_client_pins_validated_dns_address(
        self,
        monkeypatch: pytest.MonkeyPatch,
        station_key_path: Path,
    ) -> None:
        from civiccast.activitypub.config import load_activitypub_config
        from civiccast.activitypub.remote import HttpxActivityPubDeliveryClient

        resolved_hosts: list[str] = []

        class FakeResponse:
            status_code = 202
            text = "accepted"

        def fake_getaddrinfo(host: str, *args: Any, **kwargs: Any):
            resolved_hosts.append(host)
            if host == "neighbor.example":
                return [(2, 1, 6, "", ("93.184.216.34", 0))]
            if host == "93.184.216.34":
                return [(2, 1, 6, "", ("93.184.216.34", 0))]
            return [(2, 1, 6, "", (host, 0))]

        def fake_post(url: str, **kwargs: Any):
            from civiccast.activitypub import remote

            remote.socket.getaddrinfo("neighbor.example", 443)
            return FakeResponse()

        monkeypatch.setattr("civiccast.activitypub.remote._ORIGINAL_GETADDRINFO", fake_getaddrinfo)
        monkeypatch.setattr("civiccast.activitypub.remote.httpx.post", fake_post)
        config = load_activitypub_config(
            {
                "CIVICCAST_ACTIVITYPUB_MODE": "open",
                "CIVICCAST_ACTIVITYPUB_BASE_URL": "https://station.example",
                "CIVICCAST_ACTIVITYPUB_PRIVATE_KEY_PATH": str(station_key_path),
            }
        )
        client = HttpxActivityPubDeliveryClient(config=config)

        result = client.deliver(
            inbox_url="https://neighbor.example/inbox",
            activity={"id": "https://station.example/ap/actor/activities/1", "type": "Create"},
        )

        assert result.status_code == 202
        assert resolved_hosts == ["neighbor.example", "93.184.216.34"]
