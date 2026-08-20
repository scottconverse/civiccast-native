# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""SEC-1: 403 coverage for the 24 previously-unguarded staff mutation routes.

The SEC-1 audit found 24 ``/api/staff`` POST/PUT/PATCH/DELETE routes that
any authenticated staff token could reach regardless of product role. The
canonical finding was a ``records_clerk`` token driving
``/api/staff/facility/router-take-plan`` -- an AV routing action nothing
in the records workflow should be able to trigger. Fixed by adding
``Depends(require_any_role(...))`` in each router (see the accompanying
diff across ``activitypub``, ``captions``, ``facility``, ``installer``,
``playback_policy``, ``podcast``, ``programlog``, ``schedule``,
``stream``, ``subscribe``, and ``summary``).

This module proves the fix per route group: a validly-authenticated token
that does NOT carry any of the route's required roles gets a 403, not a
200/404/422/503/etc. Mirrors the fixture conventions in
``tests/auth/test_staff_auth.py`` (``CIVICCAST_STAFF_TOKENS`` env var,
``create_app()`` + ``TestClient``) rather than duplicating them there,
since this module is new and staff_auth.py is an existing file this
change does not otherwise need to touch.

Note on wrong-role selection: ``records_clerk`` is only a valid "wrong
role" probe for groups that do NOT allow it in the matrix (ActivityPub,
facility, installer, playback policy, podcast, program log, stream,
subscribe). Captions intake and AI summaries both allow
``records_clerk`` (per the matrix), so their wrong-role probe uses
``meeting_operator`` instead -- and the asset library allows both
``records_clerk`` and ``meeting_operator``, so its probe uses
``publish_operator``, the one product role in neither allowed set.

Role check dependencies are inserted at the front of each route's
dependant chain by FastAPI (decorator ``dependencies=`` resolve before the
endpoint's own parameter ``Depends(...)`` and before body validation), so
these requests reach the 403 without needing any of the underlying stores
wired up -- confirmed by direct inspection of
``route.dependant.dependencies`` order during test authoring.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from civiccast.app import create_app

_RECORDS_TOKEN = "sec1-records-token-000000000000000000"
_MEETING_TOKEN = "sec1-meeting-token-000000000000000000"
_PUBLISH_TOKEN = "sec1-publish-token-000000000000000000"

_TOKENS_BY_ROLE = {
    "records_clerk": (_RECORDS_TOKEN, "records-clerk-1"),
    "meeting_operator": (_MEETING_TOKEN, "meeting-operator-1"),
    "publish_operator": (_PUBLISH_TOKEN, "publish-operator-1"),
}


def _client_with_role(monkeypatch: pytest.MonkeyPatch, role: str) -> TestClient:
    token, operator_id = _TOKENS_BY_ROLE[role]
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS",
        f"{token}:{operator_id}:{operator_id.title()}:{role}",
    )
    return TestClient(create_app(), headers={"Authorization": f"Bearer {token}"})


@pytest.mark.parametrize(
    ("group", "method", "path", "payload", "wrong_role", "required_role_in_detail"),
    [
        (
            "ActivityPub moderation",
            "POST",
            "/api/staff/activitypub/followers/approve",
            {"actor": "https://remote.example/actor/1"},
            "records_clerk",
            "publish_operator",
        ),
        (
            "Captions intake",
            "POST",
            "/api/staff/captions/review-items",
            {},
            "meeting_operator",
            "records_clerk",
        ),
        (
            # The audit's canonical case: records_clerk driving facility
            # router-take-plan (AV routing) must be impossible.
            "Facility AV control",
            "POST",
            "/api/staff/facility/router-take-plan",
            {},
            "records_clerk",
            "meeting_operator",
        ),
        (
            "Installer actions",
            "POST",
            "/api/staff/installer/actions",
            {"action": "retry"},
            "records_clerk",
            "setup_admin",
        ),
        (
            "Playback policy",
            "POST",
            "/api/staff/playback-policy/viewer-tokens",
            {},
            "records_clerk",
            "publish_operator",
        ),
        (
            "Podcast publish",
            "POST",
            "/api/staff/podcast/episodes",
            {},
            "records_clerk",
            "publish_operator",
        ),
        (
            "Program log ops",
            "POST",
            "/api/staff/programlog/slots",
            {},
            "records_clerk",
            "meeting_operator",
        ),
        (
            "Stream overlay plan",
            "POST",
            "/api/staff/stream/overlay-compositor-plan",
            {},
            "records_clerk",
            "meeting_operator",
        ),
        (
            "Subscriber dispatch test",
            "POST",
            "/api/staff/subscribe/dispatch-test",
            {},
            "records_clerk",
            "publish_operator",
        ),
        (
            "AI summaries",
            "POST",
            "/api/staff/summaries/generate",
            {},
            "meeting_operator",
            "records_clerk",
        ),
    ],
)
def test_wrong_role_gets_403(
    monkeypatch: pytest.MonkeyPatch,
    group: str,
    method: str,
    path: str,
    payload: object,
    wrong_role: str,
    required_role_in_detail: str,
) -> None:
    """A token without any of the route's required roles must get 403."""

    client = _client_with_role(monkeypatch, wrong_role)

    response = client.request(method, path, json=payload)

    assert response.status_code == 403, (
        f"{group}: {method} {path} should reject a {wrong_role} token, got "
        f"{response.status_code}: {response.text}"
    )
    assert required_role_in_detail in response.json()["detail"]


def test_program_log_ops_reject_records_clerk_for_patch_and_disable_and_materialize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Program log ops has four routes; cover the remaining three explicitly."""

    client = _client_with_role(monkeypatch, "records_clerk")

    patch_response = client.patch("/api/staff/programlog/slots/slot-1", json={})
    disable_response = client.post("/api/staff/programlog/slots/slot-1/disable")
    materialize_response = client.post("/api/staff/programlog/materialize")

    for response in (patch_response, disable_response, materialize_response):
        assert response.status_code == 403
        assert "meeting_operator" in response.json()["detail"]


def test_facility_router_schedule_plan_rejects_records_clerk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Facility AV control's second route, alongside the canonical case above."""

    client = _client_with_role(monkeypatch, "records_clerk")

    response = client.post("/api/staff/facility/router-schedule-plan", json={})

    assert response.status_code == 403
    assert "meeting_operator" in response.json()["detail"]


def test_activitypub_moderation_rejects_records_clerk_for_reject_block_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ActivityPub moderation has four routes; cover the remaining three explicitly."""

    client = _client_with_role(monkeypatch, "records_clerk")

    reject_response = client.post(
        "/api/staff/activitypub/followers/reject",
        json={"actor": "https://remote.example/actor/1"},
    )
    block_response = client.post(
        "/api/staff/activitypub/followers/block",
        json={"actor": "https://remote.example/actor/1"},
    )
    replay_response = client.post("/api/staff/activitypub/delivery-retries/retry-1/replay")

    for response in (reject_response, block_response, replay_response):
        assert response.status_code == 403
        assert "publish_operator" in response.json()["detail"]


def test_captions_external_ingest_rejects_meeting_operator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Captions intake's second route, alongside review-items above.

    records_clerk is a VALID role for this route (per the matrix), so the
    wrong-role probe here uses meeting_operator instead.
    """

    client = _client_with_role(monkeypatch, "meeting_operator")

    response = client.post("/api/staff/captions/external-ingest", json={})

    assert response.status_code == 403
    assert "records_clerk" in response.json()["detail"]


def test_playback_policy_subject_update_rejects_records_clerk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Playback policy's second route, alongside viewer-tokens above."""

    client = _client_with_role(monkeypatch, "records_clerk")

    response = client.post("/api/staff/playback-policy/channel/gov-ch12", json={})

    assert response.status_code == 403
    assert "publish_operator" in response.json()["detail"]


def test_summaries_transcript_csv_rejects_meeting_operator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AI summaries' second route.

    records_clerk is a VALID role for this route (per the matrix), so the
    wrong-role probe here uses meeting_operator instead.
    """

    client = _client_with_role(monkeypatch, "meeting_operator")

    response = client.post("/api/staff/summaries/transcript.csv", json={"meeting_id": "m-1"})

    assert response.status_code == 403
    assert "records_clerk" in response.json()["detail"]


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("PATCH", "/api/staff/assets/asset-1", {}),
        ("POST", "/api/staff/assets", {}),
        ("POST", "/api/staff/assets/asset-1/relink", {"new_file_path": "/tmp/x.mp4"}),
    ],
)
def test_asset_library_rejects_publish_operator(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    payload: object,
) -> None:
    """Asset library allows records_clerk/meeting_operator/support_admin --
    publish_operator (in neither set) must 403 on every non-upload route.
    The multipart upload route is covered separately below."""

    client = _client_with_role(monkeypatch, "publish_operator")

    response = client.request(method, path, json=payload)

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert "records_clerk" in detail
    assert "meeting_operator" in detail


def test_asset_upload_rejects_publish_operator(monkeypatch: pytest.MonkeyPatch) -> None:
    """Asset library's multipart upload route, alongside the JSON routes above."""

    client = _client_with_role(monkeypatch, "publish_operator")

    response = client.post(
        "/api/staff/assets/upload",
        data={"asset_id": "test-asset", "title": "Test"},
        files={"file": ("clip.mp4", b"not-a-real-video", "video/mp4")},
    )

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert "records_clerk" in detail
    assert "meeting_operator" in detail
