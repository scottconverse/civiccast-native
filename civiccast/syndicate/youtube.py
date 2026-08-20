# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Real YouTube reach client (Beta sprint B5, decision #6).

Talks to the YouTube Data API v3 with an OAuth refresh token the station
obtained out-of-band. Selected with ``CIVICCAST_PROVIDER_YOUTUBE=real``; the
deterministic mock remains the default. The three credential variables are
validated fail-fast at resolution.

- ``publish_live`` creates a live broadcast + stream pair and binds them,
  returning the RTMPS ingestion address (reach evidence, not the system of
  record).
- ``upload_vod`` / ``upload_vod_path`` perform a resumable upload of the
  recording media; the asset-id-only form resolves
  ``CIVICCAST_YOUTUBE_MEDIA_ROOT/<asset_id>.mp4``.

No credentials live in code or tests; contract tests use
``httpx.MockTransport`` and never call googleapis.com. ``credential_key``
values in proofs are pointers to where the credential lives, never the
credential itself.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from civiccast.syndicate.models import YouTubePublishProof

_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - endpoint URL, not a secret
_API_BASE = "https://www.googleapis.com/youtube/v3"
_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
_CREDENTIAL_POINTER = "env://CIVICCAST_YOUTUBE_REFRESH_TOKEN"

__all__ = ["YouTubeClient", "YouTubeSettings"]


@dataclass(frozen=True)
class YouTubeSettings:
    """Station OAuth credentials and upload defaults, read from the environment."""

    client_id: str
    client_secret: str = field(repr=False)
    refresh_token: str = field(repr=False)
    media_root: Path | None = None
    privacy_status: str = "unlisted"

    @classmethod
    def from_env(cls) -> YouTubeSettings:
        client_id = os.environ.get("CIVICCAST_YOUTUBE_CLIENT_ID", "").strip()
        client_secret = os.environ.get("CIVICCAST_YOUTUBE_CLIENT_SECRET", "").strip()
        refresh_token = os.environ.get("CIVICCAST_YOUTUBE_REFRESH_TOKEN", "").strip()
        missing = [
            name
            for name, value in (
                ("CIVICCAST_YOUTUBE_CLIENT_ID", client_id),
                ("CIVICCAST_YOUTUBE_CLIENT_SECRET", client_secret),
                ("CIVICCAST_YOUTUBE_REFRESH_TOKEN", refresh_token),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                "CIVICCAST_PROVIDER_YOUTUBE=real requires "
                f"{', '.join(missing)} to be set (OAuth client + refresh "
                "token obtained out-of-band; see docs/ops/cdn-and-providers.md)."
            )
        media_root_raw = os.environ.get("CIVICCAST_YOUTUBE_MEDIA_ROOT", "").strip()
        privacy = os.environ.get("CIVICCAST_YOUTUBE_PRIVACY", "").strip().lower() or "unlisted"
        if privacy not in ("public", "unlisted", "private"):
            raise ValueError(
                f"CIVICCAST_YOUTUBE_PRIVACY must be public, unlisted, or private; got {privacy!r}."
            )
        return cls(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            media_root=Path(media_root_raw) if media_root_raw else None,
            privacy_status=privacy,
        )


class YouTubeClient:
    """Reach client satisfying the same protocol as the mock."""

    def __init__(
        self,
        settings: YouTubeSettings,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 600.0,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._timeout_seconds = timeout_seconds

    def _client(self) -> httpx.Client:
        return httpx.Client(transport=self._transport, timeout=self._timeout_seconds)

    def _access_token(self, client: httpx.Client) -> str:
        response = client.post(
            _TOKEN_URL,
            data={
                "client_id": self._settings.client_id,
                "client_secret": self._settings.client_secret,
                "refresh_token": self._settings.refresh_token,
                "grant_type": "refresh_token",
            },
        )
        response.raise_for_status()
        token = response.json().get("access_token", "")
        if not token:
            raise RuntimeError("YouTube token endpoint returned no access_token.")
        return str(token)

    def publish_live(self, *, asset_id: str) -> YouTubePublishProof:
        with self._client() as client:
            token = self._access_token(client)
            auth = {"Authorization": f"Bearer {token}"}
            broadcast = client.post(
                f"{_API_BASE}/liveBroadcasts",
                params={"part": "snippet,contentDetails,status"},
                headers=auth,
                json={
                    "snippet": {"title": asset_id, "scheduledStartTime": "1970-01-01T00:00:00Z"},
                    "contentDetails": {"enableAutoStart": True, "enableAutoStop": True},
                    "status": {
                        "privacyStatus": self._settings.privacy_status,
                        "selfDeclaredMadeForKids": False,
                    },
                },
            )
            broadcast.raise_for_status()
            broadcast_id = str(broadcast.json()["id"])
            stream = client.post(
                f"{_API_BASE}/liveStreams",
                params={"part": "snippet,cdn"},
                headers=auth,
                json={
                    "snippet": {"title": asset_id},
                    "cdn": {
                        "frameRate": "variable",
                        "ingestionType": "rtmp",
                        "resolution": "variable",
                    },
                },
            )
            stream.raise_for_status()
            stream_body = stream.json()
            stream_id = str(stream_body["id"])
            ingestion = stream_body["cdn"]["ingestionInfo"]
            bind = client.post(
                f"{_API_BASE}/liveBroadcasts/bind",
                params={"id": broadcast_id, "part": "id", "streamId": stream_id},
                headers=auth,
            )
            bind.raise_for_status()
        return YouTubePublishProof(
            target_type="youtube_live",
            url=f"{ingestion['ingestionAddress']}/{ingestion['streamName']}",
            credential_key=_CREDENTIAL_POINTER,
        )

    def upload_vod(self, *, asset_id: str) -> YouTubePublishProof:
        if self._settings.media_root is None:
            raise RuntimeError(
                "CIVICCAST_YOUTUBE_MEDIA_ROOT must point at the recordings "
                "directory for asset-id VOD uploads (or call upload_vod_path)."
            )
        return self.upload_vod_path(
            asset_id=asset_id, path=self._settings.media_root / f"{asset_id}.mp4"
        )

    def upload_vod_path(self, *, asset_id: str, path: Path) -> YouTubePublishProof:
        if not path.exists():
            raise RuntimeError(f"Recording media for {asset_id!r} not found at {path}.")
        with self._client() as client:
            token = self._access_token(client)
            auth = {"Authorization": f"Bearer {token}"}
            init = client.post(
                _UPLOAD_URL,
                params={"uploadType": "resumable", "part": "snippet,status"},
                headers={
                    **auth,
                    "X-Upload-Content-Type": "video/mp4",
                    "X-Upload-Content-Length": str(path.stat().st_size),
                },
                json={
                    "snippet": {"title": asset_id},
                    "status": {
                        "privacyStatus": self._settings.privacy_status,
                        "selfDeclaredMadeForKids": False,
                    },
                },
            )
            init.raise_for_status()
            upload_url = init.headers.get("location", "")
            if not upload_url:
                raise RuntimeError("YouTube resumable-upload init returned no Location URL.")
            with path.open("rb") as handle:
                upload = client.put(
                    upload_url,
                    content=handle,
                    headers={**auth, "Content-Type": "video/mp4"},
                )
            upload.raise_for_status()
            video_id = str(upload.json()["id"])
        return YouTubePublishProof(
            target_type="youtube_vod",
            url=f"https://www.youtube.com/watch?v={video_id}",
            credential_key=_CREDENTIAL_POINTER,
        )
