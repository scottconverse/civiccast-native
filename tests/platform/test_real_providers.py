# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contract tests for the real provider adapters (Beta sprint B5, decision #6).

No live external calls anywhere here: Internet Archive and YouTube are tested
against ``httpx.MockTransport``; SMTP is tested against an in-process plain
SMTP server on a loopback socket. No real credentials appear — every key used
is an obviously fake test value.
"""

from __future__ import annotations

import smtplib
import socket
import threading
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from civiccast.archive.internet_archive import InternetArchiveClient, InternetArchiveSettings
from civiccast.platform.providers import (
    PROVIDER_KIND_INTERNET_ARCHIVE,
    PROVIDER_KIND_MAIL,
    PROVIDER_KIND_YOUTUBE,
    default_registry,
)
from civiccast.subscribe.models import NotificationPayload
from civiccast.subscribe.smtp import SmtpMailbox, SmtpSettings
from civiccast.syndicate.youtube import YouTubeClient, YouTubeSettings

_IA_SETTINGS = InternetArchiveSettings(
    access_key="test-access", secret_key="test-secret", collection="test-collection"
)
_YT_SETTINGS = YouTubeSettings(
    client_id="test-client-id",
    client_secret="test-client-secret",
    refresh_token="test-refresh-token",
)


class TestInternetArchiveClient:
    def test_upload_puts_payload_with_station_keys_and_metadata(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200)

        client = InternetArchiveClient(_IA_SETTINGS, transport=httpx.MockTransport(handler))
        proof = client.upload(asset_id="meeting-42", payload=b"payload-bytes")

        assert len(seen) == 1
        request = seen[0]
        assert request.method == "PUT"
        assert str(request.url) == "https://s3.us.archive.org/civiccast-meeting-42/meeting-42.bin"
        assert request.headers["authorization"] == "LOW test-access:test-secret"
        assert request.headers["x-amz-auto-make-bucket"] == "1"
        assert request.headers["x-archive-meta01-collection"] == "test-collection"
        assert request.headers["x-archive-meta-mediatype"] == "movies"
        assert request.content == b"payload-bytes"
        assert proof.target_type == "internet_archive"
        assert proof.target_url_or_path == "https://archive.org/details/civiccast-meeting-42"
        assert proof.verification_hash.startswith("sha256:")

    def test_upload_path_streams_the_media_file(self, tmp_path: Path) -> None:
        media = tmp_path / "meeting-42.mp4"
        media.write_bytes(b"media-bytes" * 1000)
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200)

        client = InternetArchiveClient(_IA_SETTINGS, transport=httpx.MockTransport(handler))
        proof = client.upload_path(asset_id="meeting-42", path=media)

        assert str(seen[0].url) == ("https://s3.us.archive.org/civiccast-meeting-42/meeting-42.mp4")
        assert seen[0].read() == media.read_bytes()
        assert proof.target_url_or_path == "https://archive.org/details/civiccast-meeting-42"

    def test_rejected_upload_raises_instead_of_minting_a_proof(self) -> None:
        client = InternetArchiveClient(
            _IA_SETTINGS,
            transport=httpx.MockTransport(lambda _: httpx.Response(403)),
        )
        with pytest.raises(httpx.HTTPStatusError):
            client.upload(asset_id="meeting-42", payload=b"x")

    def test_from_env_fails_fast_with_exact_variable_names(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CIVICCAST_IA_ACCESS_KEY", raising=False)
        monkeypatch.delenv("CIVICCAST_IA_SECRET_KEY", raising=False)
        with pytest.raises(ValueError, match=r"CIVICCAST_IA_ACCESS_KEY.*CIVICCAST_IA_SECRET_KEY"):
            InternetArchiveSettings.from_env()


def _youtube_handler(seen: list[httpx.Request]):  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        url = str(request.url)
        if url.startswith("https://oauth2.googleapis.com/token"):
            return httpx.Response(200, json={"access_token": "test-token"})
        if "/liveBroadcasts/bind" in url:
            return httpx.Response(200, json={"id": "bcast-1"})
        if "/liveBroadcasts" in url:
            return httpx.Response(200, json={"id": "bcast-1"})
        if "/liveStreams" in url:
            return httpx.Response(
                200,
                json={
                    "id": "stream-1",
                    "cdn": {
                        "ingestionInfo": {
                            "ingestionAddress": "rtmps://a.rtmps.youtube.com/live2",
                            "streamName": "test-stream-name",
                        }
                    },
                },
            )
        if url.startswith("https://www.googleapis.com/upload/youtube/v3/videos"):
            if request.method == "POST":
                return httpx.Response(200, headers={"location": "https://upload.example/session-1"})
            return httpx.Response(200, json={"id": "vid-123"})
        if url.startswith("https://upload.example/session-1"):
            return httpx.Response(200, json={"id": "vid-123"})
        raise AssertionError(f"unexpected request: {request.method} {url}")

    return handler


class TestYouTubeClient:
    def test_publish_live_creates_binds_and_returns_the_ingest_url(self) -> None:
        seen: list[httpx.Request] = []
        client = YouTubeClient(_YT_SETTINGS, transport=httpx.MockTransport(_youtube_handler(seen)))

        proof = client.publish_live(asset_id="meeting-42")

        assert proof.target_type == "youtube_live"
        assert proof.url == "rtmps://a.rtmps.youtube.com/live2/test-stream-name"
        # OAuth refresh happened and the API calls were bearer-authorized.
        assert "oauth2.googleapis.com" in str(seen[0].url)
        assert all(
            request.headers.get("Authorization") == "Bearer test-token" for request in seen[1:]
        )
        # The credential_key is a pointer, never the credential.
        assert "test-refresh-token" not in proof.credential_key

    def test_upload_vod_streams_media_through_the_resumable_session(self, tmp_path: Path) -> None:
        media = tmp_path / "meeting-42.mp4"
        media.write_bytes(b"vod-bytes" * 1000)
        seen: list[httpx.Request] = []
        client = YouTubeClient(
            YouTubeSettings(
                client_id="test-client-id",
                client_secret="test-client-secret",
                refresh_token="test-refresh-token",
                media_root=tmp_path,
            ),
            transport=httpx.MockTransport(_youtube_handler(seen)),
        )

        proof = client.upload_vod(asset_id="meeting-42")

        assert proof.target_type == "youtube_vod"
        assert proof.url == "https://www.youtube.com/watch?v=vid-123"
        final_put = seen[-1]
        assert final_put.method == "PUT"
        assert final_put.read() == media.read_bytes()

    def test_upload_vod_without_media_root_or_file_fails_clearly(self, tmp_path: Path) -> None:
        client = YouTubeClient(_YT_SETTINGS, transport=httpx.MockTransport(_youtube_handler([])))
        with pytest.raises(RuntimeError, match="CIVICCAST_YOUTUBE_MEDIA_ROOT"):
            client.upload_vod(asset_id="meeting-42")
        with pytest.raises(RuntimeError, match="not found"):
            client.upload_vod_path(asset_id="meeting-42", path=tmp_path / "missing.mp4")

    def test_from_env_fails_fast_with_exact_variable_names(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in (
            "CIVICCAST_YOUTUBE_CLIENT_ID",
            "CIVICCAST_YOUTUBE_CLIENT_SECRET",
            "CIVICCAST_YOUTUBE_REFRESH_TOKEN",
        ):
            monkeypatch.delenv(name, raising=False)
        with pytest.raises(ValueError, match="CIVICCAST_YOUTUBE_CLIENT_ID"):
            YouTubeSettings.from_env()


class _LoopbackSmtpServer:
    """Minimal plain-SMTP server: enough protocol for smtplib to deliver."""

    def __init__(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self.port = self._sock.getsockname()[1]
        self.mail_from: str | None = None
        self.rcpt_to: str | None = None
        self.data: str | None = None
        self._thread = threading.Thread(target=self._serve_one, daemon=True)
        self._thread.start()

    def _serve_one(self) -> None:
        conn, _ = self._sock.accept()
        with conn:
            reader = conn.makefile("rb")
            conn.sendall(b"220 loopback test SMTP\r\n")
            while True:
                line = reader.readline().decode("ascii", "replace").strip()
                upper = line.upper()
                if upper.startswith("EHLO") or upper.startswith("HELO"):
                    conn.sendall(b"250-loopback\r\n250 8BITMIME\r\n")
                elif upper.startswith("MAIL FROM:"):
                    self.mail_from = line[10:].strip()
                    conn.sendall(b"250 OK\r\n")
                elif upper.startswith("RCPT TO:"):
                    self.rcpt_to = line[8:].strip()
                    conn.sendall(b"250 OK\r\n")
                elif upper == "DATA":
                    conn.sendall(b"354 End data with <CR><LF>.<CR><LF>\r\n")
                    chunks: list[str] = []
                    while True:
                        data_line = reader.readline().decode("utf-8", "replace")
                        if data_line.rstrip("\r\n") == ".":
                            break
                        chunks.append(data_line)
                    self.data = "".join(chunks)
                    conn.sendall(b"250 OK queued\r\n")
                elif upper == "QUIT":
                    conn.sendall(b"221 Bye\r\n")
                    return
                else:
                    conn.sendall(b"250 OK\r\n")

    def join(self, timeout: float = 5.0) -> None:
        self._thread.join(timeout=timeout)
        self._sock.close()


class TestSmtpMailbox:
    def test_notification_delivers_over_a_real_smtp_conversation(self) -> None:
        server = _LoopbackSmtpServer()
        mailbox = SmtpMailbox(
            SmtpSettings(
                host="127.0.0.1",
                port=server.port,
                from_address="alerts@station.example",
                use_starttls=False,
            )
        )
        payload = NotificationPayload(
            asset_id="meeting-42",
            title="Council Meeting",
            portal_url="https://portal.example/watch/meeting-42",
            podcast_url=None,
            summary="Summary.",
            published_at=datetime(2026, 6, 10, tzinfo=UTC),
        )

        message_id = mailbox.send_notification(email="resident@example.org", payload=payload)
        server.join()

        assert message_id.startswith("<")
        assert server.mail_from is not None and "alerts@station.example" in server.mail_from
        assert server.rcpt_to is not None and "resident@example.org" in server.rcpt_to
        assert server.data is not None
        assert "Subject: New CivicCast recording: Council Meeting" in server.data
        assert "Watch: https://portal.example/watch/meeting-42" in server.data
        assert "Podcast: Not posted" in server.data

    def test_confirmation_subject_and_body_match_the_local_mailbox(self) -> None:
        server = _LoopbackSmtpServer()
        mailbox = SmtpMailbox(
            SmtpSettings(
                host="127.0.0.1",
                port=server.port,
                from_address="alerts@station.example",
                use_starttls=False,
            )
        )

        mailbox.send_confirmation(
            email="resident@example.org",
            confirmation_url="https://portal.example/confirm/abc",
        )
        server.join()

        assert server.data is not None
        assert "Subject: Confirm your CivicCast subscription" in server.data
        assert "Confirm your subscription: https://portal.example/confirm/abc" in server.data

    def test_starttls_and_login_happen_in_order_when_configured(self) -> None:
        calls: list[str] = []

        class _FakeSmtp:
            def __enter__(self) -> _FakeSmtp:
                return self

            def __exit__(self, *args: object) -> None:
                calls.append("quit")

            def ehlo(self) -> None:
                calls.append("ehlo")

            def starttls(self) -> None:
                calls.append("starttls")

            def login(self, username: str, password: str) -> None:
                calls.append(f"login:{username}")

            def send_message(self, message: object) -> None:
                calls.append("send")

        mailbox = SmtpMailbox(
            SmtpSettings(
                host="relay.example",
                port=587,
                from_address="alerts@station.example",
                username="test-user",
                password="test-pass",
                use_starttls=True,
            ),
            smtp_factory=lambda host, port: _FakeSmtp(),  # type: ignore[arg-type,return-value]
        )

        mailbox.send_confirmation(
            email="resident@example.org", confirmation_url="https://x.example/c"
        )

        assert calls == ["ehlo", "starttls", "ehlo", "login:test-user", "send", "quit"]

    def test_from_env_fails_fast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in (
            "CIVICCAST_SMTP_HOST",
            "CIVICCAST_SMTP_FROM",
            "CIVICCAST_SMTP_USERNAME",
            "CIVICCAST_SMTP_PASSWORD",
        ):
            monkeypatch.delenv(name, raising=False)
        with pytest.raises(ValueError, match=r"CIVICCAST_SMTP_HOST.*CIVICCAST_SMTP_FROM"):
            SmtpSettings.from_env()

        monkeypatch.setenv("CIVICCAST_SMTP_HOST", "relay.example")
        monkeypatch.setenv("CIVICCAST_SMTP_FROM", "alerts@station.example")
        monkeypatch.setenv("CIVICCAST_SMTP_USERNAME", "user-without-password")
        with pytest.raises(ValueError, match="set together"):
            SmtpSettings.from_env()


class TestRegistrySelection:
    def test_real_names_resolve_with_credentials(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("CIVICCAST_PROVIDER_INTERNET_ARCHIVE", "real")
        monkeypatch.setenv("CIVICCAST_IA_ACCESS_KEY", "test-access")
        monkeypatch.setenv("CIVICCAST_IA_SECRET_KEY", "test-secret")
        monkeypatch.setenv("CIVICCAST_PROVIDER_YOUTUBE", "real")
        monkeypatch.setenv("CIVICCAST_YOUTUBE_CLIENT_ID", "test-client-id")
        monkeypatch.setenv("CIVICCAST_YOUTUBE_CLIENT_SECRET", "test-client-secret")
        monkeypatch.setenv("CIVICCAST_YOUTUBE_REFRESH_TOKEN", "test-refresh-token")
        monkeypatch.setenv("CIVICCAST_PROVIDER_MAIL", "real")
        monkeypatch.setenv("CIVICCAST_SMTP_HOST", "relay.example")
        monkeypatch.setenv("CIVICCAST_SMTP_FROM", "alerts@station.example")

        registry = default_registry()
        assert isinstance(registry.resolve(PROVIDER_KIND_INTERNET_ARCHIVE), InternetArchiveClient)
        assert isinstance(registry.resolve(PROVIDER_KIND_YOUTUBE), YouTubeClient)
        assert isinstance(registry.resolve(PROVIDER_KIND_MAIL), SmtpMailbox)

    def test_real_without_credentials_fails_fast_never_falls_back_to_mock(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CIVICCAST_PROVIDER_INTERNET_ARCHIVE", "real")
        monkeypatch.delenv("CIVICCAST_IA_ACCESS_KEY", raising=False)
        monkeypatch.delenv("CIVICCAST_IA_SECRET_KEY", raising=False)
        with pytest.raises(ValueError, match="CIVICCAST_IA_ACCESS_KEY"):
            default_registry().resolve(PROVIDER_KIND_INTERNET_ARCHIVE)

    def test_mock_remains_the_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for kind in ("INTERNET_ARCHIVE", "YOUTUBE", "MAIL"):
            monkeypatch.delenv(f"CIVICCAST_PROVIDER_{kind}", raising=False)
        registry = default_registry()
        assert not isinstance(
            registry.resolve(PROVIDER_KIND_INTERNET_ARCHIVE), InternetArchiveClient
        )
        assert not isinstance(registry.resolve(PROVIDER_KIND_YOUTUBE), YouTubeClient)
        assert not isinstance(registry.resolve(PROVIDER_KIND_MAIL), SmtpMailbox)


class TestCredentialRedaction:
    """#122: no credential value may surface through reprs or error paths."""

    def test_settings_reprs_never_contain_secret_values(self) -> None:
        ia = InternetArchiveSettings(
            access_key="ia-access-sentinel", secret_key="ia-secret-sentinel"
        )
        yt = YouTubeSettings(
            client_id="yt-client-id",
            client_secret="yt-secret-sentinel",
            refresh_token="yt-refresh-sentinel",
        )
        smtp = SmtpSettings(
            host="relay.example",
            from_address="clerk@example.gov",
            username="mailer",
            password="smtp-secret-sentinel",
        )
        for rendered in (repr(ia), str(ia)):
            assert "ia-access-sentinel" not in rendered
            assert "ia-secret-sentinel" not in rendered
        for rendered in (repr(yt), str(yt)):
            assert "yt-secret-sentinel" not in rendered
            assert "yt-refresh-sentinel" not in rendered
        for rendered in (repr(smtp), str(smtp)):
            assert "smtp-secret-sentinel" not in rendered

    def test_internet_archive_error_path_never_echoes_keys(self) -> None:
        client = InternetArchiveClient(
            InternetArchiveSettings(
                access_key="ia-access-sentinel", secret_key="ia-secret-sentinel"
            ),
            transport=httpx.MockTransport(lambda _: httpx.Response(403, text="denied")),
        )
        with pytest.raises(httpx.HTTPStatusError) as excinfo:
            client.upload(asset_id="meeting-42", payload=b"x")
        rendered = f"{excinfo.value!s} {excinfo.value!r}"
        assert "ia-access-sentinel" not in rendered
        assert "ia-secret-sentinel" not in rendered

    def test_youtube_token_error_path_never_echoes_oauth_secrets(self) -> None:
        client = YouTubeClient(
            YouTubeSettings(
                client_id="yt-client-id",
                client_secret="yt-secret-sentinel",
                refresh_token="yt-refresh-sentinel",
            ),
            transport=httpx.MockTransport(lambda _: httpx.Response(401, text="invalid_grant")),
        )
        with pytest.raises(httpx.HTTPStatusError) as excinfo:
            client.publish_live(asset_id="meeting-42")
        rendered = f"{excinfo.value!s} {excinfo.value!r}"
        assert "yt-secret-sentinel" not in rendered
        assert "yt-refresh-sentinel" not in rendered

    def test_smtp_login_error_path_never_echoes_password(self) -> None:
        class _RefusingSmtp:
            def __enter__(self) -> _RefusingSmtp:
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

            def ehlo(self) -> None:
                return None

            def starttls(self) -> None:
                return None

            def login(self, username: str, password: str) -> None:
                raise smtplib.SMTPAuthenticationError(
                    535, b"authentication failed for " + username.encode()
                )

            def send_message(self, _message: object) -> None:
                raise AssertionError("send_message must not be reached after failed login")

        mailbox = SmtpMailbox(
            SmtpSettings(
                host="relay.example",
                from_address="clerk@example.gov",
                username="mailer",
                password="smtp-secret-sentinel",
            ),
            smtp_factory=lambda _host, _port: _RefusingSmtp(),  # type: ignore[arg-type,return-value]
        )
        with pytest.raises(smtplib.SMTPAuthenticationError) as excinfo:
            mailbox.send_confirmation(
                email="resident@example.gov", confirmation_url="https://x/c/1"
            )
        rendered = f"{excinfo.value!s} {excinfo.value!r}"
        assert "smtp-secret-sentinel" not in rendered
