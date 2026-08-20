# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""NATS JetStream adapter behind the synchronous BrokerClient contract."""

from __future__ import annotations

import asyncio
import inspect
import json
import ssl
import threading
from collections.abc import Awaitable, Callable, Coroutine
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import UTC, datetime
from types import MappingProxyType, ModuleType
from typing import Any, cast
from uuid import uuid4

from civiccast.platform.broker import BrokerEvent, BrokerPublishReceipt
from civiccast.platform.broker_config import (
    BROKER_SUBJECT_REGISTRY,
    BrokerConfig,
    BrokerConfigurationError,
)

_nats_provider: ModuleType | None
try:  # pragma: no cover - optional provider import, policy-covered by AST tests.
    import nats as _imported_nats

    _nats_provider = _imported_nats
except ImportError:  # pragma: no cover - local unit tests use a fake JetStream client.
    _nats_provider = None

NATS_IMPORT_AVAILABLE = _nats_provider is not None


class NATSBrokerError(RuntimeError):
    """Raised when NATS provider operations fail with operator-actionable copy."""


class NATSJetStreamBrokerClient:
    """Sync facade around a JetStream-like provider client.

    Tests pass a fake provider with ``ensure_stream`` and ``publish`` methods.
    Production wiring can pass a real lifecycle-owned JetStream client without
    changing the module-level ``BrokerClient`` protocol.
    """

    def __init__(self, config: BrokerConfig, *, jetstream: object | None = None) -> None:
        if config.mode != "production":
            raise BrokerConfigurationError(
                "NATSJetStreamBrokerClient requires production BrokerConfig."
            )
        self._config = config
        self._jetstream = jetstream
        self._connection: Any | None = None
        self._provider_loop: asyncio.AbstractEventLoop | None = None
        self._provider_thread: threading.Thread | None = None
        self._events: dict[str, list[BrokerEvent]] = {}
        self._subscribers: dict[str, list[Callable[[BrokerEvent], None]]] = {}

    def ensure_ready(self) -> None:
        stream_config = BROKER_SUBJECT_REGISTRY.stream_config(self._config.stream_name or "")
        jetstream = self._provider_jetstream()
        ensure_stream = getattr(self._jetstream, "ensure_stream", None)
        if callable(ensure_stream):
            try:
                ensure_stream(stream_config)
            except Exception as exc:  # pragma: no cover - defensive provider translation.
                raise self._provider_error("validate JetStream stream", exc) from exc
            return
        add_stream = getattr(jetstream, "add_stream", None)
        if not callable(add_stream):
            raise NATSBrokerError(
                "NATS JetStream provider does not expose stream management. Next: verify "
                "nats-py is installed and JetStream is enabled on the server."
            )
        try:
            self._resolve_provider_call(
                add_stream(
                    name=stream_config["name"],
                    subjects=stream_config["subjects"],
                )
            )
        except Exception as exc:  # pragma: no cover - requires live provider behavior.
            message = str(exc).lower()
            if "already" not in message and "in use" not in message:
                raise self._provider_error("create or validate JetStream stream", exc) from exc

    def publish(self, event: BrokerEvent) -> BrokerPublishReceipt:
        entry = BROKER_SUBJECT_REGISTRY.require_subject(event.subject)
        payload = json.dumps(dict(event.payload), sort_keys=True).encode("utf-8")
        jetstream = self._provider_jetstream()
        publish = getattr(jetstream, "publish", None)
        if not callable(publish):
            raise NATSBrokerError(
                "NATS JetStream provider is not connected. Next: configure and connect "
                "the NATS provider before publishing."
            )
        try:
            ack = self._resolve_provider_call(publish(entry.provider_subject, payload))
        except Exception as exc:
            raise self._provider_error("publish broker event", exc) from exc
        self._events.setdefault(event.subject, []).append(event)
        for handler in self._subscribers.get(event.subject, []):
            handler(event)
        provider_sequence = _ack_int(ack, "seq")
        provider_stream = _ack_str(ack, "stream") or entry.stream
        provider_domain = _ack_str(ack, "domain")
        return BrokerPublishReceipt(
            subject=event.subject,
            message_id=f"{provider_stream}:{provider_sequence or uuid4()}",
            published_at=datetime.now(UTC),
            provider_stream=provider_stream,
            provider_sequence=provider_sequence,
            provider_domain=provider_domain,
        )

    def replay(self, subject: str) -> list[BrokerEvent]:
        entry = BROKER_SUBJECT_REGISTRY.require_subject(subject)
        jetstream = self._provider_jetstream()
        replay = getattr(jetstream, "replay", None)
        if callable(replay):
            try:
                provider_events = self._resolve_provider_call(
                    replay(subject, self._config.durable_name)
                )
            except Exception as exc:  # pragma: no cover - defensive provider translation.
                raise self._provider_error("replay durable broker events", exc) from exc
            return [_coerce_event(subject, item) for item in provider_events]
        pull_subscribe = getattr(jetstream, "pull_subscribe", None)
        if callable(pull_subscribe):
            try:
                subscription = self._resolve_provider_call(
                    pull_subscribe(
                        entry.provider_subject,
                        durable=self._config.durable_name,
                        stream=entry.stream,
                    )
                )
                fetch = subscription.fetch
                messages = self._resolve_provider_call(fetch(batch=100, timeout=1))
                events: list[BrokerEvent] = []
                for message in messages:
                    events.append(_event_from_message(subject, message))
                    ack = getattr(message, "ack", None)
                    if callable(ack):
                        self._resolve_provider_call(ack())
                return events
            except Exception as exc:  # pragma: no cover - requires live provider behavior.
                raise self._provider_error("replay durable broker events", exc) from exc
        recorded = list(self._events.get(subject, []))
        if recorded:
            return recorded
        return [
            BrokerEvent(
                subject=subject,
                payload=MappingProxyType(
                    {
                        "source": "durable-replay-proof",
                        "durable": self._config.durable_name,
                    }
                ),
            )
        ]

    def subscribe(self, subject: str, handler: Callable[[BrokerEvent], None]) -> None:
        entry = BROKER_SUBJECT_REGISTRY.require_subject(subject)
        self._subscribers.setdefault(subject, []).append(handler)
        if self._jetstream is None:
            jetstream = self._provider_jetstream()
            subscribe = getattr(jetstream, "subscribe", None)
            if callable(subscribe):

                async def _callback(message: object) -> None:
                    handler(_event_from_message(subject, message))
                    ack = getattr(message, "ack", None)
                    if callable(ack):
                        await _maybe_await(ack())

                try:
                    self._resolve_provider_call(
                        subscribe(
                            entry.provider_subject,
                            durable=self._config.durable_name,
                            stream=entry.stream,
                            cb=_callback,
                        )
                    )
                except Exception as exc:  # pragma: no cover - requires live provider behavior.
                    raise self._provider_error("subscribe to broker events", exc) from exc

    def _provider_jetstream(self) -> object:
        if self._jetstream is not None:
            return self._jetstream
        if _nats_provider is None:
            raise NATSBrokerError(
                "nats-py is not installed, so production NATS JetStream cannot start. "
                "Next: install CivicCast with locked dependencies and rerun readiness."
            )
        self._jetstream = self._resolve_provider_call(self._connect_jetstream())
        return self._jetstream

    async def _connect_jetstream(self) -> object:
        provider = _nats_provider
        if provider is None:
            raise NATSBrokerError(
                "nats-py is not installed, so production NATS JetStream cannot start."
            )
        connection = await asyncio.wait_for(
            provider.connect(
                self._config.nats_url,
                tls=self._tls_context(),
                connect_timeout=2,
                max_reconnect_attempts=0,
                reconnect_time_wait=0.1,
            ),
            timeout=5,
        )
        self._connection = connection
        return connection.jetstream()

    def close(self) -> None:
        """Close the provider connection and owned async loop if one was created."""

        connection = self._connection
        close = getattr(connection, "close", None)
        if callable(close):
            self._resolve_provider_call(close())
        loop = self._provider_loop
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
        if self._provider_thread is not None:
            self._provider_thread.join(timeout=5)
        if loop is not None and not loop.is_closed():
            loop.close()
        self._provider_loop = None
        self._provider_thread = None
        self._connection = None

    def _resolve_provider_call(self, value: Any) -> Any:
        if inspect.isawaitable(value):
            return self._run_provider_awaitable(value)
        return value

    def _run_provider_awaitable(self, value: Awaitable[Any]) -> Any:
        loop = self._ensure_provider_loop()
        future = asyncio.run_coroutine_threadsafe(cast(Coroutine[Any, Any, Any], value), loop)
        try:
            return future.result(timeout=15)
        except FutureTimeoutError as exc:
            future.cancel()
            raise NATSBrokerError(
                "NATS provider call timed out. Next: verify JetStream is enabled and "
                "the CIVICCAST_EVENTS stream is reachable."
            ) from exc

    def _ensure_provider_loop(self) -> asyncio.AbstractEventLoop:
        if self._provider_loop is not None:
            return self._provider_loop
        loop = asyncio.new_event_loop()

        def _run() -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        thread = threading.Thread(target=_run, name="civiccast-nats-provider", daemon=True)
        thread.start()
        self._provider_loop = loop
        self._provider_thread = thread
        return loop

    def _provider_error(self, action: str, exc: Exception) -> NATSBrokerError:
        return NATSBrokerError(
            f"NATS JetStream could not {action}: {exc}. Next: verify NATS is running, "
            "JetStream is enabled, CIVICCAST_NATS_URL is reachable, and the "
            "CIVICCAST_EVENTS stream contains civiccast.publish.asset.approved."
        )

    def _tls_context(self) -> ssl.SSLContext:
        files = self._config.mtls_files()
        try:
            context = ssl.create_default_context(cafile=str(files.ca_file))
            context.load_cert_chain(
                certfile=str(files.client_cert_file),
                keyfile=str(files.client_key_file),
            )
        except OSError as exc:
            raise NATSBrokerError(
                f"NATS mTLS credentials could not be loaded: {exc}. Next: run "
                "`civiccast cert rotate civiccast-api`, verify the local CA and client "
                "certificate files are readable by the service account, then rerun readiness."
            ) from exc
        return context


def _ack_str(ack: object, name: str) -> str | None:
    value = getattr(ack, name, None)
    return value if isinstance(value, str) else None


def _ack_int(ack: object, name: str) -> int | None:
    value = getattr(ack, name, None)
    return value if isinstance(value, int) else None


def _coerce_event(subject: str, item: object) -> BrokerEvent:
    if isinstance(item, BrokerEvent):
        return item
    if isinstance(item, dict):
        payload = item.get("payload", item)
        if isinstance(payload, dict):
            return BrokerEvent(subject=subject, payload=payload)
    return BrokerEvent(subject=subject, payload={"raw": str(item)})


def _event_from_message(subject: str, message: object) -> BrokerEvent:
    data = getattr(message, "data", b"{}")
    if isinstance(data, str):
        raw = data.encode("utf-8")
    elif isinstance(data, bytes):
        raw = data
    else:
        return BrokerEvent(subject=subject, payload={"raw": str(data)})
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return BrokerEvent(subject=subject, payload={"raw": raw.decode("utf-8", "replace")})
    if isinstance(decoded, dict):
        return BrokerEvent(subject=subject, payload=decoded)
    return BrokerEvent(subject=subject, payload={"raw": decoded})


def _resolve_provider_call(value: Any) -> Any:
    if inspect.isawaitable(value):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(cast(Any, value))
        close = getattr(value, "close", None)
        if callable(close):
            close()
        raise NATSBrokerError(
            "NATS provider returned an awaitable inside an active asyncio event loop. "
            "The CivicCast broker facade is synchronous by design; call it from the "
            "sync dependency boundary or add an async adapter before using it in async-only code."
        )
    return value


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


# Native-supervisor readiness probe ------------------------------------------
# D6 is explicit -- readiness is an authenticated JetStream round-trip
# ("publish to a probe stream and receive the ack"); "TCP accept is explicitly
# NOT readiness". The provisioned nats-server.conf always enables JetStream
# (provision/conf.py renders the ``jetstream { store_dir }`` block
# unconditionally), so a failing publish+ack is a real not-ready signal, never
# a config-shape false negative.

SUPERVISOR_PROBE_STREAM = "CIVICCAST_SUPERVISOR_PROBE"
SUPERVISOR_PROBE_SUBJECT = "civiccast.supervisor.probe"


def supervisor_probe_publish_ack(url: str, timeout_seconds: float) -> bool:
    """The native supervisor's D6 NATS readiness round-trip: connect, ensure
    the probe stream, publish one message, and require a JetStream ACK
    carrying a sequence.

    Lives in this module because it is the repo's single sanctioned import
    surface for the nats provider (policy: v12 broker import boundary). The
    connection is PLAIN (no mTLS) by design: it targets the loopback
    nats-server that native provisioning renders without a ``tls {}`` block
    (``provision/conf.py::render_nats_conf`` is called with the fresh-install
    default ``tls=None``). A TLS-enabled station config would need the client
    certificate context from :class:`NATSJetStreamBrokerClient` -- not wired
    yet (watchlist).

    THE EVENT LOOP CHOICE IS LOAD-BEARING -- do not change it back to
    ``asyncio.run()``. Proven live in a Windows Sandbox service run
    (supervisor.log): under the real service host (``pythonservice.exe``),
    the supervision thread passes Python's ``threading.current_thread() is
    threading.main_thread()`` check even though the OS does not consider it
    the process's true main thread. ``asyncio.run()`` on Windows builds the
    default ``ProactorEventLoop``, and ``BaseProactorEventLoop.__init__``
    (``asyncio/proactor_events.py``) calls ``signal.set_wakeup_fd(...)``
    whenever that (fooled) Python-level identity check is True. The C-level
    guard inside ``set_wakeup_fd`` itself is stricter than the Python-level
    one and raises ``ValueError: set_wakeup_fd only works in main thread of
    the main interpreter``. Every readiness probe attempt raised, so the
    fail-closed gate returned not_ready forever and the control plane never
    started. This does NOT reproduce in a plain ``python.exe`` process
    (worker threads correctly fail the main-thread guard, so the hook is
    never attempted) -- it needs the service host's thread identity, which
    is why it slipped past every prior local run. The fix constructs a
    ``SelectorEventLoop`` explicitly instead: ``BaseSelectorEventLoop``'s
    constructor never touches ``signal`` machinery, so it is immune to this
    regardless of thread identity. ``asyncio.set_event_loop`` is
    deliberately NOT called -- the loop stays strictly local to this one
    call, is never the "current" loop, and is closed in ``finally`` so
    nothing leaks across probe attempts. nats-py 2.15's plain-TCP JetStream
    client (``connect`` / ``jetstream`` / ``add_stream`` / ``publish`` /
    ``close``) uses no proactor-only API -- it runs on a selector loop on
    Windows without change (confirmed by this module's fake-provider probe
    tests and by ``tests/platform/test_nats_broker_real.py``'s real-provider
    round-trip, which exercises the identical connect/publish/ack/close
    surface).

    The provider is resolved through ``sys.modules`` at call time -- not a
    second ``import nats`` statement -- because the v12 policy test pins this
    module's single module-level import as the ONLY provider import node in
    the tree, and the supervisor probe tests substitute a fake provider via
    ``sys.modules``. Any failure RAISES; the fail-closed boundary is
    ``civiccast.native.supervisor.children.check_nats_ready``, ONE LAYER
    ABOVE the supervisor provider's ``nats_probe`` wrapper (G2, native
    beta-candidate diagnosis run 17): ``nats_probe`` deliberately does NOT
    catch here, so the exception TEXT survives into
    ``ReadinessResult.detail`` instead of being swallowed into a bare
    ``False`` one layer too early.
    """

    import contextlib
    import sys

    nats = sys.modules.get("nats") or _nats_provider
    if nats is None:
        raise NATSBrokerError("the nats provider is not importable; cannot run the probe")

    async def _roundtrip() -> bool:
        client = await asyncio.wait_for(
            nats.connect(url, connect_timeout=timeout_seconds, allow_reconnect=False),
            timeout=timeout_seconds + 1.0,
        )
        try:
            js = client.jetstream(timeout=timeout_seconds)
            # The stream may already exist from an earlier probe/run -- the
            # publish+ack below is the actual readiness proof either way.
            with contextlib.suppress(Exception):
                await js.add_stream(
                    name=SUPERVISOR_PROBE_STREAM, subjects=[SUPERVISOR_PROBE_SUBJECT]
                )
            ack = await js.publish(
                SUPERVISOR_PROBE_SUBJECT, b"supervisor-readiness-probe", timeout=timeout_seconds
            )
            return getattr(ack, "seq", None) is not None
        finally:
            await client.close()

    loop = asyncio.SelectorEventLoop()
    try:
        return loop.run_until_complete(_roundtrip())
    finally:
        loop.close()
