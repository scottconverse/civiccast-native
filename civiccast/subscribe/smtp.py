# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Real SMTP mailbox for subscriber mail (Beta sprint B5, decision #6).

Sends through the station's SMTP relay with ``smtplib``. Selected with
``CIVICCAST_PROVIDER_MAIL=real``; the in-memory ``LocalMailbox`` remains the
default. Settings are validated fail-fast at resolution: host and from-address
are required, STARTTLS is on by default, and credentials are optional but must
come as a pair.

Subjects and bodies match :class:`~civiccast.subscribe.delivery.LocalMailbox`
exactly, so proofs and real deliveries say the same thing. No credentials live
in code or tests; contract tests run an in-process SMTP server on a loopback
socket.
"""

from __future__ import annotations

import os
import smtplib
from collections.abc import Callable
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import make_msgid

from civiccast.subscribe.models import NotificationPayload

__all__ = ["SmtpMailbox", "SmtpSettings"]

SmtpFactory = Callable[[str, int], smtplib.SMTP]


@dataclass(frozen=True)
class SmtpSettings:
    """Station SMTP relay configuration, read from the environment."""

    host: str
    from_address: str
    port: int = 587
    username: str | None = None
    password: str | None = field(default=None, repr=False)
    use_starttls: bool = True

    @classmethod
    def from_env(cls) -> SmtpSettings:
        host = os.environ.get("CIVICCAST_SMTP_HOST", "").strip()
        from_address = os.environ.get("CIVICCAST_SMTP_FROM", "").strip()
        missing = [
            name
            for name, value in (
                ("CIVICCAST_SMTP_HOST", host),
                ("CIVICCAST_SMTP_FROM", from_address),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                "CIVICCAST_PROVIDER_MAIL=real requires "
                f"{', '.join(missing)} to be set (see docs/ops/cdn-and-providers.md)."
            )
        port_raw = os.environ.get("CIVICCAST_SMTP_PORT", "").strip()
        try:
            port = int(port_raw) if port_raw else 587
        except ValueError as exc:
            raise ValueError(f"CIVICCAST_SMTP_PORT must be an integer; got {port_raw!r}.") from exc
        username = os.environ.get("CIVICCAST_SMTP_USERNAME", "").strip() or None
        password = os.environ.get("CIVICCAST_SMTP_PASSWORD", "").strip() or None
        if (username is None) != (password is None):
            raise ValueError(
                "CIVICCAST_SMTP_USERNAME and CIVICCAST_SMTP_PASSWORD must be "
                "set together (or both left unset for an unauthenticated relay)."
            )
        use_starttls = os.environ.get("CIVICCAST_SMTP_STARTTLS", "1").strip() != "0"
        return cls(
            host=host,
            from_address=from_address,
            port=port,
            username=username,
            password=password,
            use_starttls=use_starttls,
        )


class SmtpMailbox:
    """Mail provider satisfying the same protocol as ``LocalMailbox``.

    ``smtp_factory`` exists for tests (and unusual relays): it must return a
    connected ``smtplib.SMTP``-compatible object for ``(host, port)``.
    """

    def __init__(
        self,
        settings: SmtpSettings,
        *,
        smtp_factory: SmtpFactory | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._settings = settings
        self._smtp_factory = smtp_factory
        self._timeout_seconds = timeout_seconds

    def _connect(self) -> smtplib.SMTP:
        if self._smtp_factory is not None:
            return self._smtp_factory(self._settings.host, self._settings.port)
        return smtplib.SMTP(self._settings.host, self._settings.port, timeout=self._timeout_seconds)

    def send_confirmation(self, *, email: str, confirmation_url: str) -> str:
        return self._send(
            to=email,
            subject="Confirm your CivicCast subscription",
            body=f"Confirm your subscription: {confirmation_url}",
        )

    def send_notification(self, *, email: str, payload: NotificationPayload) -> str:
        return self._send(
            to=email,
            subject=f"New CivicCast recording: {payload.title}",
            body=(
                f"{payload.title}\nWatch: {payload.portal_url}\n"
                f"Podcast: {payload.podcast_url or 'Not posted'}"
            ),
        )

    def _send(self, *, to: str, subject: str, body: str) -> str:
        message = EmailMessage()
        message["From"] = self._settings.from_address
        message["To"] = to
        message["Subject"] = subject
        message["Message-ID"] = make_msgid(domain=None)
        message.set_content(body)
        with self._connect() as smtp:
            smtp.ehlo()
            if self._settings.use_starttls:
                smtp.starttls()
                smtp.ehlo()
            if self._settings.username and self._settings.password:
                smtp.login(self._settings.username, self._settings.password)
            smtp.send_message(message)
        return str(message["Message-ID"])
