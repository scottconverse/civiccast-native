# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S8-4 AlertDeliveryDispatch + AlertRetryWorker tests.

Transport senders are tested via injectable stubs to avoid SMTP/HTTP I/O.
Store helpers (fail_delivery, succeed_delivery, dead_letter_delivery,
due_retry_deliveries) are covered as part of the integration tests that
exercise the full dispatch + retry lifecycle.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.alerting.delivery import (
    AlertDeliveryDispatch,
    AlertRetrySettings,
    AlertRetryWorker,
    AlertSmsSender,
    AlertSmtpSender,
    AlertWebhookSender,
)
from civiccast.alerting.evaluator import AlertEvaluator
from civiccast.alerting.models import AlertChannel, AlertEvent, AlertEventDeliveryDb, AlertRule
from civiccast.alerting.store import (
    get_alert_events,
    get_event_deliveries,
    upsert_alert_channel,
    upsert_alert_rule,
)

_NOW = datetime(2026, 6, 15, 10, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Shared stubs
# ---------------------------------------------------------------------------


class _OkSender:
    """Transport stub that always succeeds."""

    calls: list[tuple]

    def __init__(self):
        self.calls = []

    def send(self, event, channel, get_credential):
        self.calls.append((event.event_id, channel.channel_id))
        return True


class _FailSender:
    """Transport stub that always fails."""

    calls: list[tuple]

    def __init__(self):
        self.calls = []

    def send(self, event, channel, get_credential):
        self.calls.append((event.event_id, channel.channel_id))
        return False


def _null_cred(handle: str) -> dict[str, str] | None:
    return None


def _smtp_cred(handle: str) -> dict[str, str] | None:
    return {
        "smtp_host": "smtp.example.com",
        "smtp_port": "587",
        "from_addr": "alerts@example.com",
        "to_addr": "ops@example.com",
    }


def _webhook_cred(handle: str) -> dict[str, str] | None:
    return {"url": "https://hooks.example.com/civiccast", "secret": "test-secret"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def session_factory(db_session: Session):
    @contextmanager
    def factory() -> Iterator[Session]:
        yield db_session

    return factory


def _make_event_and_channel(
    db_session: Session,
    kind: str = "email",
    condition: str = "off-air",
) -> tuple[str, str]:
    """Seed an AlertRule + AlertChannel and return (event_id, channel_id)."""
    ch = AlertChannel(
        channel_id="ch-del-1",
        kind=kind,  # type: ignore[arg-type]
        label="Test",
        target_redacted="ops@***",
        credential_handle="handle-1",
        created_at=_NOW,
    )
    upsert_alert_channel(db_session, ch)

    rule = AlertRule(
        rule_id=f"default:{condition}",
        condition=condition,  # type: ignore[arg-type]
        severity="critical",
        channel_ids=["ch-del-1"],
        updated_at=_NOW,
        updated_by="test",
    )
    upsert_alert_rule(db_session, rule)

    # Use the evaluator to create a real event + delivery row via the null hook
    def _null_hook(*args):
        pass

    evaluator = AlertEvaluator(session_factory=_make_sf(db_session), dispatch=_null_hook)
    evaluator.evaluate_channel("ch1", "STOPPED", now=_NOW)

    events = get_alert_events(db_session)
    assert len(events) == 1
    event_id = events[0].event_id

    deliveries = get_event_deliveries(db_session, event_id)
    # With null hook: one "sent" delivery (evaluator writes it optimistically)
    assert len(deliveries) == 1
    return event_id, deliveries[0].delivery_id


def _make_sf(session: Session):
    @contextmanager
    def factory() -> Iterator[Session]:
        yield session

    return factory


@pytest.fixture()
def durable_webhook(tmp_path: Path):
    """Real transport and independent transactions, all local and disposable."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'alerts.sqlite'}",
        execution_options={"schema_translate_map": {"civiccast": None}},
    )
    from civiccast.alerting.models import AlertChannelDb, AlertEventDb, AlertRuleDb

    for model in (AlertRuleDb, AlertChannelDb, AlertEventDb, AlertEventDeliveryDb):
        model.__table__.create(engine)

    posts = []
    responses = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            posts.append(json.loads(body))
            self.send_response(responses.pop(0) if responses else 200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    @contextmanager
    def factory():
        with Session(engine) as session:
            yield session

    credentials = {"url": f"http://127.0.0.1:{server.server_port}/alerts", "secret": "local"}
    with factory() as session:
        upsert_alert_channel(
            session,
            AlertChannel(
                channel_id="local",
                kind="webhook",
                label="Local",
                target_redacted="loopback",
                credential_handle="local",
                created_at=_NOW,
            ),
        )
        upsert_alert_rule(
            session,
            AlertRule(
                rule_id="default:off-air",
                condition="off-air",
                severity="critical",
                channel_ids=["local"],
                updated_at=_NOW,
                updated_by="test",
            ),
        )
        session.commit()
    try:
        yield factory, credentials, posts, responses
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        engine.dispose()


def test_durable_webhook_fire_and_resolve(durable_webhook):
    factory, credentials, posts, _ = durable_webhook
    evaluator = AlertEvaluator(factory, AlertDeliveryDispatch(factory, lambda _: credentials))
    evaluator.evaluate_channel("CH-LOCAL", "STOPPED", now=_NOW)
    assert [post["state"] for post in posts] == ["firing"]
    evaluator.evaluate_channel(
        "CH-LOCAL",
        "ON_AIR",
        encoder_fps=29.97,
        encoder_bitrate_kbps=8000,
        now=_NOW + timedelta(minutes=5),
    )
    assert [post["state"] for post in posts] == ["firing", "resolved"]
    with factory() as session:
        event = get_alert_events(session)[0]
        assert event.state == "resolved"
        assert [d.status for d in get_event_deliveries(session, event.event_id)] == ["sent", "sent"]


@pytest.mark.parametrize("raises", [False, True])
def test_durable_webhook_failure_and_retry(durable_webhook, raises):
    factory, credentials, posts, responses = durable_webhook
    broken = True

    def get_credential(_):
        if raises and broken:
            raise RuntimeError("credential provider unavailable")
        return credentials

    if not raises:
        responses.extend([503, 503])
    dispatch = AlertDeliveryDispatch(factory, get_credential)
    AlertEvaluator(factory, dispatch).evaluate_channel("CH-LOCAL", "STOPPED", now=_NOW)
    with factory() as session:
        event = get_alert_events(session)[0]
        delivery = get_event_deliveries(session, event.event_id)[0]
        assert delivery.status == "failed"
        assert delivery.next_attempt_at is not None
    worker = AlertRetryWorker(factory, get_credential)
    retry_at = datetime.now(UTC) + timedelta(hours=1)
    assert worker.tick(now=retry_at) == 1
    with factory() as session:
        failed = get_event_deliveries(session, event.event_id)[0]
        assert failed.status == "failed"
        assert failed.attempts > delivery.attempts
        assert failed.next_attempt_at is not None
    broken = False
    assert worker.tick(now=retry_at + timedelta(hours=1)) == 1
    with factory() as session:
        recovered = get_event_deliveries(session, event.event_id)[0]
        assert recovered.status == "sent"
        assert recovered.next_attempt_at is None
    assert posts[-1]["state"] == "firing"


@pytest.mark.parametrize("missing", ["event", "channel"])
def test_durable_dispatch_missing_resource_dead_letters(durable_webhook, missing):
    from sqlalchemy import delete

    from civiccast.alerting.models import AlertChannelDb, AlertEventDb

    factory, credentials, posts, _ = durable_webhook
    # Seed a committed delivery without sending, then remove its dependency
    # in a different transaction before the actual dispatch reads it.
    AlertEvaluator(factory).evaluate_channel("CH-LOCAL", "STOPPED", now=_NOW)
    with factory() as session:
        event = get_alert_events(session)[0]
        delivery = get_event_deliveries(session, event.event_id)[0]
        session.execute(delete(AlertEventDb if missing == "event" else AlertChannelDb))
        session.commit()
    AlertDeliveryDispatch(factory, lambda _: credentials)(
        event.event_id, delivery.delivery_id, "local", "off-air", "Local"
    )
    with factory() as session:
        row = session.get(AlertEventDeliveryDb, delivery.delivery_id)
        assert row is not None
        assert row.status == "dead_letter"
        assert row.next_attempt_at is None
    assert posts == []


def test_durable_evaluator_does_not_send_before_successful_commit(durable_webhook, monkeypatch):
    factory, credentials, posts, _ = durable_webhook

    def fail_commit(self):
        raise RuntimeError("commit unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="commit unavailable"):
            AlertEvaluator(
                factory, AlertDeliveryDispatch(factory, lambda _: credentials)
            ).evaluate_channel("CH-LOCAL", "STOPPED", now=_NOW)
    assert posts == []
    with factory() as session:
        assert get_alert_events(session) == []


# ---------------------------------------------------------------------------
# AlertSmtpSender unit tests
# ---------------------------------------------------------------------------


class TestAlertSmtpSender:
    def test_no_credential_handle_returns_false(self) -> None:
        sender = AlertSmtpSender()
        event = _dummy_event()
        channel = AlertChannel(
            channel_id="ch-x",
            kind="email",
            label="Test",
            target_redacted="ops@***",
            credential_handle=None,
            created_at=_NOW,
        )
        assert sender.send(event, channel, _null_cred) is False

    def test_credential_not_found_returns_false(self) -> None:
        sender = AlertSmtpSender()
        event = _dummy_event()
        channel = AlertChannel(
            channel_id="ch-x",
            kind="email",
            label="Test",
            target_redacted="ops@***",
            credential_handle="missing",
            created_at=_NOW,
        )
        assert sender.send(event, channel, _null_cred) is False

    def test_smtp_exception_returns_false(self) -> None:
        import smtplib
        from unittest.mock import patch

        sender = AlertSmtpSender()
        event = _dummy_event()
        channel = AlertChannel(
            channel_id="ch-x",
            kind="email",
            label="Test",
            target_redacted="ops@***",
            credential_handle="h1",
            created_at=_NOW,
        )
        with patch("smtplib.SMTP", side_effect=smtplib.SMTPConnectError(111, "refused")):
            assert sender.send(event, channel, _smtp_cred) is False

    def test_smtp_success_returns_true(self) -> None:
        from unittest.mock import MagicMock, patch

        sender = AlertSmtpSender()
        event = _dummy_event()
        channel = AlertChannel(
            channel_id="ch-x",
            kind="email",
            label="Test",
            target_redacted="ops@***",
            credential_handle="h1",
            created_at=_NOW,
        )
        mock_smtp = MagicMock()
        mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp.__exit__ = MagicMock(return_value=False)
        with patch("smtplib.SMTP", return_value=mock_smtp):
            result = sender.send(event, channel, _smtp_cred)
        assert result is True
        mock_smtp.starttls.assert_called_once()
        mock_smtp.send_message.assert_called_once()


# ---------------------------------------------------------------------------
# AlertWebhookSender unit tests
# ---------------------------------------------------------------------------


class TestAlertWebhookSender:
    def test_no_credential_handle_returns_false(self) -> None:
        sender = AlertWebhookSender()
        event = _dummy_event()
        channel = AlertChannel(
            channel_id="ch-x",
            kind="webhook",
            label="Webhook",
            target_redacted="https://hooks.***",
            credential_handle=None,
            created_at=_NOW,
        )
        assert sender.send(event, channel, _null_cred) is False

    def test_credential_not_found_returns_false(self) -> None:
        sender = AlertWebhookSender()
        event = _dummy_event()
        channel = AlertChannel(
            channel_id="ch-x",
            kind="webhook",
            label="Webhook",
            target_redacted="https://hooks.***",
            credential_handle="missing",
            created_at=_NOW,
        )
        assert sender.send(event, channel, _null_cred) is False

    def test_webhook_http_error_returns_false(self) -> None:
        from unittest.mock import MagicMock, patch

        sender = AlertWebhookSender()
        event = _dummy_event()
        channel = AlertChannel(
            channel_id="ch-x",
            kind="webhook",
            label="Webhook",
            target_redacted="https://hooks.***",
            credential_handle="h1",
            created_at=_NOW,
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=mock_resp
        )
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp
        with patch("civiccast.alerting.delivery.httpx.Client", return_value=mock_client):
            assert sender.send(event, channel, _webhook_cred) is False

    def test_webhook_success_posts_with_signature(self) -> None:
        from unittest.mock import MagicMock, patch

        sender = AlertWebhookSender()
        event = _dummy_event()
        channel = AlertChannel(
            channel_id="ch-x",
            kind="webhook",
            label="Webhook",
            target_redacted="https://hooks.***",
            credential_handle="h1",
            created_at=_NOW,
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status.return_value = None
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp
        with patch("civiccast.alerting.delivery.httpx.Client", return_value=mock_client):
            result = sender.send(event, channel, _webhook_cred)
        assert result is True
        call_kwargs = mock_client.post.call_args
        assert "X-CivicCast-Signature" in call_kwargs.kwargs["headers"]


# ---------------------------------------------------------------------------
# AlertSmsSender unit test
# ---------------------------------------------------------------------------


_TWILIO_CRED = {
    "account_sid": "ACtestsid000000000000000000000001",
    "auth_token": "secrettoken",
    "from_number": "+15551234567",
    "to_number": "+15557654321",
}


def _twilio_cred(handle: str) -> dict[str, str] | None:
    return dict(_TWILIO_CRED) if handle == "h1" else None


def _twilio_cred_partial(handle: str) -> dict[str, str] | None:
    """Cred missing ``to_number`` — should fail validation in the sender."""
    if handle != "h1":
        return None
    cred = dict(_TWILIO_CRED)
    cred.pop("to_number", None)
    return cred


def _twilio_cred_no_sender(handle: str) -> dict[str, str] | None:
    """Cred missing both ``from_number`` and ``messaging_service_sid``."""
    if handle != "h1":
        return None
    cred = dict(_TWILIO_CRED)
    cred.pop("from_number", None)
    return cred


def _twilio_cred_messaging_service(handle: str) -> dict[str, str] | None:
    """Cred using a Messaging Service SID instead of a from_number — a real
    Twilio deployment pattern for SMS sender-pool failover."""
    if handle != "h1":
        return None
    cred = dict(_TWILIO_CRED)
    cred.pop("from_number", None)
    cred["messaging_service_sid"] = "MGtestservice00000000000000000001"
    return cred


def _sms_channel() -> AlertChannel:
    return AlertChannel(
        channel_id="ch-x",
        kind="sms",
        label="SMS",
        target_redacted="+1 *** *** 4321",
        credential_handle="h1",
        created_at=_NOW,
    )


class TestAlertSmsSender:
    """Twilio-backed SMS sender (replaced the b1 finish-line placeholder).

    These tests verify the wire shape against a mocked httpx.Client; we
    never contact Twilio. The auth tuple, form-encoded body, target URL,
    and the ``MessagingServiceSid``-vs-``From`` choice are all asserted.
    """

    def test_no_credential_handle_returns_false(self) -> None:
        sender = AlertSmsSender()
        event = _dummy_event()
        channel = AlertChannel(
            channel_id="ch-x",
            kind="sms",
            label="SMS",
            target_redacted="+1***",
            credential_handle=None,
            created_at=_NOW,
        )
        assert sender.send(event, channel, _null_cred) is False

    def test_credential_not_found_returns_false(self) -> None:
        sender = AlertSmsSender()
        event = _dummy_event()
        channel = _sms_channel()
        assert sender.send(event, channel, lambda _h: None) is False

    def test_missing_to_number_returns_false(self) -> None:
        sender = AlertSmsSender()
        event = _dummy_event()
        channel = _sms_channel()
        assert sender.send(event, channel, _twilio_cred_partial) is False

    def test_missing_from_or_messaging_service_returns_false(self) -> None:
        sender = AlertSmsSender()
        event = _dummy_event()
        channel = _sms_channel()
        assert sender.send(event, channel, _twilio_cred_no_sender) is False

    def test_twilio_5xx_returns_false(self) -> None:
        from unittest.mock import MagicMock, patch

        sender = AlertSmsSender()
        event = _dummy_event()
        channel = _sms_channel()
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "503", request=MagicMock(), response=mock_resp
        )
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp
        with patch("civiccast.alerting.delivery.httpx.Client", return_value=mock_client):
            assert sender.send(event, channel, _twilio_cred) is False

    def test_happy_path_posts_with_basic_auth_and_form_body(self) -> None:
        from unittest.mock import MagicMock, patch

        sender = AlertSmsSender()
        event = _dummy_event()
        channel = _sms_channel()
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "sid": "SMtestmessage000000000000000000aa",
            "status": "queued",
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp

        with patch("civiccast.alerting.delivery.httpx.Client", return_value=mock_client):
            assert sender.send(event, channel, _twilio_cred) is True

        call_args = mock_client.post.call_args
        # POSTed to the right URL on the Twilio API.
        url = call_args.args[0]
        assert url.startswith("https://api.twilio.com/2010-04-01/Accounts/")
        assert "Messages.json" in url
        # Basic-auth tuple is (account_sid, auth_token).
        assert call_args.kwargs["auth"] == (
            "ACtestsid000000000000000000000001",
            "secrettoken",
        )
        # Form body carries To / From / Body and NOT MessagingServiceSid
        # (since the cred has from_number set).
        form = call_args.kwargs["data"]
        assert form["To"] == "+15557654321"
        assert form["From"] == "+15551234567"
        assert "MessagingServiceSid" not in form
        assert "Body" in form
        assert "CivicCast" in form["Body"]
        assert "WARNING" in form["Body"] or "CRITICAL" in form["Body"] or "INFO" in form["Body"]

    def test_messaging_service_overrides_from(self) -> None:
        from unittest.mock import MagicMock, patch

        sender = AlertSmsSender()
        event = _dummy_event()
        channel = _sms_channel()
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"sid": "SMtest"}
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp

        with patch("civiccast.alerting.delivery.httpx.Client", return_value=mock_client):
            assert sender.send(event, channel, _twilio_cred_messaging_service) is True

        form = mock_client.post.call_args.kwargs["data"]
        assert form["MessagingServiceSid"] == "MGtestservice00000000000000000001"
        assert "From" not in form

    def test_body_truncates_long_payload(self) -> None:
        from unittest.mock import MagicMock, patch

        sender = AlertSmsSender()
        # Event with a near-max summary — sender concatenates head + ref +
        # summary so total ends up > 320; the sender should clip.
        long_summary = "x" * 300
        event = AlertEvent(
            event_id="ev-long",
            rule_id="default:off-air",
            condition="off-air",
            severity="warning",
            state="firing",
            resource_ref="channel-1",
            summary=long_summary,
            source_section="S8",
            first_observed_at=_NOW,
            last_observed_at=_NOW,
        )
        channel = _sms_channel()
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"sid": "SM"}
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp
        with patch("civiccast.alerting.delivery.httpx.Client", return_value=mock_client):
            assert sender.send(event, channel, _twilio_cred) is True
        body = mock_client.post.call_args.kwargs["data"]["Body"]
        assert len(body) <= AlertSmsSender._BODY_MAX_CHARS
        assert body.endswith("…")


# ---------------------------------------------------------------------------
# AlertDeliveryDispatch integration tests
# ---------------------------------------------------------------------------


class TestAlertDeliveryDispatch:
    def test_success_leaves_delivery_sent(self, db_session: Session, session_factory) -> None:
        event_id, delivery_id = _make_event_and_channel(db_session)
        ok_sender = _OkSender()
        dispatch = AlertDeliveryDispatch(
            session_factory,
            _smtp_cred,
            smtp_sender=ok_sender,  # type: ignore[arg-type]
        )
        dispatch(event_id, delivery_id, "ch-del-1", "off-air", "Test")

        row = db_session.get(AlertEventDeliveryDb, delivery_id)
        assert row is not None
        assert row.status == "sent"
        assert row.next_attempt_at is None
        assert len(ok_sender.calls) == 1

    def test_failure_marks_delivery_failed_with_backoff(
        self, db_session: Session, session_factory
    ) -> None:
        event_id, delivery_id = _make_event_and_channel(db_session)
        fail_sender = _FailSender()
        settings = AlertRetrySettings(max_attempts=5, base_backoff_seconds=120)
        dispatch = AlertDeliveryDispatch(
            session_factory,
            _null_cred,
            retry_settings=settings,
            smtp_sender=fail_sender,  # type: ignore[arg-type]
        )
        dispatch(event_id, delivery_id, "ch-del-1", "off-air", "Test")

        row = db_session.get(AlertEventDeliveryDb, delivery_id)
        assert row is not None
        assert row.status == "failed"
        assert row.next_attempt_at is not None

    def test_missing_event_skips_gracefully(self, db_session: Session, session_factory) -> None:
        ok_sender = _OkSender()
        dispatch = AlertDeliveryDispatch(session_factory, _null_cred, smtp_sender=ok_sender)  # type: ignore[arg-type]
        # event_id and delivery_id that don't exist
        dispatch("no-such-event", "no-such-del", "ch-del-1", "off-air", "Test")
        assert len(ok_sender.calls) == 0


# ---------------------------------------------------------------------------
# AlertRetryWorker integration tests
# ---------------------------------------------------------------------------


class TestAlertRetryWorker:
    def _seed_failed_delivery(
        self,
        db_session: Session,
        *,
        attempts: int = 1,
        condition: str = "off-air",
    ) -> tuple[str, str]:
        """Seed an event + delivery, then mark it failed with a past next_attempt_at."""
        event_id, delivery_id = _make_event_and_channel(db_session, condition=condition)
        # Mark it failed so the retry worker picks it up
        row = db_session.get(AlertEventDeliveryDb, delivery_id)
        assert row is not None
        row.status = "failed"
        row.attempts = attempts
        row.next_attempt_at = _NOW - timedelta(seconds=1)
        row.last_error = "initial error"
        db_session.flush()
        return event_id, delivery_id

    def test_no_due_returns_zero(self, db_session: Session, session_factory) -> None:
        worker = AlertRetryWorker(session_factory, _null_cred)
        count = worker.tick(now=_NOW)
        assert count == 0

    def test_successful_retry_marks_sent(self, db_session: Session, session_factory) -> None:
        _, delivery_id = self._seed_failed_delivery(db_session)
        ok_sender = _OkSender()
        worker = AlertRetryWorker(
            session_factory,
            _smtp_cred,
            smtp_sender=ok_sender,  # type: ignore[arg-type]
        )
        count = worker.tick(now=_NOW)
        assert count == 1

        row = db_session.get(AlertEventDeliveryDb, delivery_id)
        assert row is not None
        assert row.status == "sent"
        assert row.next_attempt_at is None
        assert len(ok_sender.calls) == 1

    def test_failed_retry_doubles_backoff(self, db_session: Session, session_factory) -> None:
        _, delivery_id = self._seed_failed_delivery(db_session, attempts=1)
        fail_sender = _FailSender()
        settings = AlertRetrySettings(max_attempts=5, base_backoff_seconds=120)
        worker = AlertRetryWorker(
            session_factory,
            _null_cred,
            settings=settings,
            smtp_sender=fail_sender,  # type: ignore[arg-type]
        )
        worker.tick(now=_NOW)

        row = db_session.get(AlertEventDeliveryDb, delivery_id)
        assert row is not None
        assert row.status == "failed"
        assert row.attempts == 2
        # base=120, new_attempts=2 -> backoff = 120 * 2^(2-1) = 240s
        # SQLite returns tz-naive datetimes; strip tzinfo for comparison.
        expected_next = (_NOW + timedelta(seconds=240)).replace(tzinfo=None)
        assert row.next_attempt_at == expected_next

    def test_dead_letter_after_max_attempts(self, db_session: Session, session_factory) -> None:
        _, delivery_id = self._seed_failed_delivery(db_session, attempts=4)
        fail_sender = _FailSender()
        settings = AlertRetrySettings(max_attempts=5, base_backoff_seconds=120)
        worker = AlertRetryWorker(
            session_factory,
            _null_cred,
            settings=settings,
            smtp_sender=fail_sender,  # type: ignore[arg-type]
        )
        worker.tick(now=_NOW)

        row = db_session.get(AlertEventDeliveryDb, delivery_id)
        assert row is not None
        assert row.status == "dead_letter"
        assert row.next_attempt_at is None

        # A "service-down" alert should have been raised
        events = get_alert_events(db_session, state="firing")
        service_down = [e for e in events if e.condition == "service-down"]
        assert len(service_down) >= 1

    def test_not_yet_due_skipped(self, db_session: Session, session_factory) -> None:
        _, delivery_id = _make_event_and_channel(db_session)
        row = db_session.get(AlertEventDeliveryDb, delivery_id)
        assert row is not None
        row.status = "failed"
        row.attempts = 1
        # next_attempt_at is AFTER now -> should not be picked up
        row.next_attempt_at = _NOW + timedelta(seconds=300)
        db_session.flush()

        ok_sender = _OkSender()
        worker = AlertRetryWorker(session_factory, _smtp_cred, smtp_sender=ok_sender)  # type: ignore[arg-type]
        count = worker.tick(now=_NOW)
        assert count == 0
        assert len(ok_sender.calls) == 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dummy_event() -> AlertEvent:
    return AlertEvent(
        event_id="evt-test-1",
        rule_id="default:off-air",
        condition="off-air",
        severity="critical",
        state="firing",
        resource_ref="ch1",
        summary="Channel ch1 is off air",
        source_section="S8",
        first_observed_at=_NOW,
        last_observed_at=_NOW,
    )
