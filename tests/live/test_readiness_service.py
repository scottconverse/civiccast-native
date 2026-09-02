# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""The observed-readiness service and the takeover gate (WP-07 / ENG-003).

This is the module that decides whether a live source may change air. What it
has to get right, and what these tests pin:

* a within-TTL success is REUSED (no second probe, no second subprocess in the
  request path of a takeover);
* every other state -- never probed, stale, failed -- is RE-PROBED, and the
  fresh probe decides, not the stored one;
* the ingest-plan-then-edit race fails closed: if the row's endpoint no longer
  matches the endpoint the plan offered, air does not change;
* a probe result that cannot be recorded fails closed;
* an SRT source's credential HANDLE (never its secret) flows to the engine, and
  a handle on a source type that cannot execute one is ignored rather than
  passed downstream.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import civiccast.live.models
import civiccast.schedule.models  # noqa: F401
from civiccast.db import Base, bind_engine, reset_engine
from civiccast.live.models import LiveSourceCreate, LiveSourceUpdate
from civiccast.live.readiness_service import LiveSourceReadinessService
from civiccast.live.source_probe import ProbeObservation
from civiccast.live.store import LiveSourceNotFoundError, LiveSourceStore

_ENDPOINT = "srt://0.0.0.0:9000?mode=listener"


@pytest.fixture
def store() -> Iterator[LiveSourceStore]:
    engine: Engine = create_engine("sqlite:///:memory:", future=True)
    bind_engine(engine)
    Base.metadata.create_all(engine)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    try:
        yield LiveSourceStore(factory)
    finally:
        reset_engine()
        engine.dispose()


class _CountingProbe:
    """A probe that records how often it ran and what secret it was handed."""

    def __init__(self, *results: bool) -> None:
        self._results = list(results) or [True]
        self.calls = 0
        self.resolvers_seen: list[object] = []

    def __call__(self, source, *, timeout_seconds, resolve_secret=None):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.resolvers_seen.append(resolve_secret)
        ok = self._results[min(self.calls - 1, len(self._results) - 1)]
        return ProbeObservation(
            ok=ok,
            detail=(
                f"{source.name} is delivering video; server-side media probe passed."
                if ok
                else f"{source.name} did not respond: Connection refused."
            ),
            error_code=None if ok else "probe_refused",
        )


def _create(
    store: LiveSourceStore, *, source_type: str = "srt", endpoint: str = _ENDPOINT, handle=None
):  # type: ignore[no-untyped-def]
    return store.create(
        LiveSourceCreate(
            live_source_id="council-encoder",
            channel_id="gov-ch12",
            name="Council Room Encoder",
            source_type=source_type,  # type: ignore[arg-type]
            endpoint_url=endpoint,
            credentials_handle=handle,
        )
    )


def _service(store: LiveSourceStore, probe: _CountingProbe, *, now: datetime | None = None):  # type: ignore[no-untyped-def]
    return LiveSourceReadinessService(
        store,
        probe=probe,
        resolve_secret=lambda handle: "passphrase-value",
        clock=(lambda: now) if now is not None else (lambda: datetime.now(UTC)),
    )


class TestExplicitProbe:
    def test_success_is_persisted_and_returned(self, store: LiveSourceStore) -> None:
        _create(store)
        probe = _CountingProbe(True)
        source, observation, probed_at = _service(store, probe).probe("council-encoder")
        assert observation.ok is True
        assert source.probe_state == "ready"
        assert source.readiness == "ready"
        assert probed_at is not None
        assert probe.calls == 1

    def test_failure_is_persisted_with_its_code_not_raised(self, store: LiveSourceStore) -> None:
        _create(store)
        source, observation, _ = _service(store, _CountingProbe(False)).probe("council-encoder")
        assert observation.ok is False
        assert source.probe_state == "failed"
        assert source.probe_error_code == "probe_refused"
        assert source.readiness == "failed"
        # A failed check is information for the operator's screen, and it has
        # to name the next step.
        assert "Check source" in source.next_action

    def test_missing_source_raises_not_found(self, store: LiveSourceStore) -> None:
        with pytest.raises(LiveSourceNotFoundError):
            _service(store, _CountingProbe(True)).probe("nope")


class TestTakeoverGateReuse:
    def test_a_fresh_observation_is_reused_without_reprobing(self, store: LiveSourceStore) -> None:
        _create(store)
        probe = _CountingProbe(True)
        service = _service(store, probe)
        service.probe("council-encoder")
        assert probe.calls == 1

        verdict = service.verify_for_takeover(
            channel_id="gov-ch12", path_id="council-encoder", endpoint_url=_ENDPOINT
        )
        assert verdict.ok is True
        assert verdict.reprobed is False
        assert probe.calls == 1, "a within-TTL observation must not re-probe"


class TestTakeoverGateReprobes:
    def test_never_probed_is_reprobed_and_may_pass(self, store: LiveSourceStore) -> None:
        _create(store)
        probe = _CountingProbe(True)
        verdict = _service(store, probe).verify_for_takeover(
            channel_id="gov-ch12", path_id="council-encoder", endpoint_url=_ENDPOINT
        )
        assert verdict.ok is True
        assert verdict.reprobed is True
        assert probe.calls == 1
        # The fresh observation is durable, not just returned.
        refreshed = store.get("council-encoder")
        assert refreshed is not None
        assert refreshed.probe_state == "ready"

    def test_never_probed_that_fails_the_fresh_probe_is_refused(
        self, store: LiveSourceStore
    ) -> None:
        _create(store)
        verdict = _service(store, _CountingProbe(False)).verify_for_takeover(
            channel_id="gov-ch12", path_id="council-encoder", endpoint_url=_ENDPOINT
        )
        assert verdict.ok is False
        assert verdict.reprobed is True
        assert "Check source" in verdict.reason

    def test_a_stale_observation_is_reprobed_and_the_fresh_answer_decides(
        self, store: LiveSourceStore
    ) -> None:
        _create(store)
        store.record_probe_observation(
            "council-encoder",
            ok=True,
            observed_at=datetime.now(UTC) - timedelta(minutes=30),
            detail="was fine half an hour ago",
            error_code=None,
        )
        probe = _CountingProbe(False)
        verdict = _service(store, probe).verify_for_takeover(
            channel_id="gov-ch12", path_id="council-encoder", endpoint_url=_ENDPOINT
        )
        assert probe.calls == 1
        assert verdict.ok is False, "the stale success must not carry the takeover"

    def test_a_stale_observation_that_re_probes_clean_may_take_air(
        self, store: LiveSourceStore
    ) -> None:
        _create(store)
        store.record_probe_observation(
            "council-encoder",
            ok=True,
            observed_at=datetime.now(UTC) - timedelta(minutes=30),
            detail="was fine half an hour ago",
            error_code=None,
        )
        verdict = _service(store, _CountingProbe(True)).verify_for_takeover(
            channel_id="gov-ch12", path_id="council-encoder", endpoint_url=_ENDPOINT
        )
        assert verdict.ok is True
        assert verdict.reprobed is True

    def test_a_recovered_source_reads_ready_again(self, store: LiveSourceStore) -> None:
        _create(store)
        service = _service(store, _CountingProbe(False))
        service.probe("council-encoder")
        assert store.get("council-encoder").probe_state == "failed"  # type: ignore[union-attr]
        recovered, observation, _ = _service(store, _CountingProbe(True)).probe("council-encoder")
        assert observation.ok is True
        assert recovered.probe_state == "ready"
        assert recovered.probe_error_code is None
        assert recovered.readiness == "ready"


class TestTakeoverGateRace:
    def test_an_endpoint_edited_after_the_plan_was_built_fails_closed(
        self, store: LiveSourceStore
    ) -> None:
        _create(store)
        probe = _CountingProbe(True)
        service = _service(store, probe)
        service.probe("council-encoder")
        # The operator's Live Room showed a plan built from the OLD endpoint.
        # Someone edits the source in the second before Take is pressed.
        store.update(
            "council-encoder", LiveSourceUpdate(endpoint_url="srt://0.0.0.0:9100?mode=listener")
        )
        verdict = service.verify_for_takeover(
            channel_id="gov-ch12", path_id="council-encoder", endpoint_url=_ENDPOINT
        )
        assert verdict.ok is False
        assert verdict.error_code == "source_changed_during_takeover"
        assert probe.calls == 1, "a changed source is refused, not probed and accepted"

    def test_a_path_that_is_not_a_live_source_is_left_to_the_relay_surface(
        self, store: LiveSourceStore
    ) -> None:
        verdict = _service(store, _CountingProbe(True)).verify_for_takeover(
            channel_id="gov-ch12", path_id="project-relay", endpoint_url="rtmps://relay/x"
        )
        assert verdict.ok is True
        assert verdict.reprobed is False
        assert "relay health surface" in verdict.reason

    def test_a_patch_interleaved_between_probe_and_persist_is_refused(
        self, store: LiveSourceStore
    ) -> None:
        # The race this closes: verify_for_takeover reads the row, decides it
        # needs a fresh probe, and runs one that can take up to
        # ``timeout_seconds``. If a PATCH repoints the endpoint inside that
        # window, the probe that is still in flight is about the OLD address.
        # Persisting its verdict as "ready" would durably misreport the row
        # that now exists. The store must refuse the write instead.
        _create(store)

        class _RepointingProbe:
            """Simulates an operator's PATCH landing while the probe is running."""

            def __init__(self, store: LiveSourceStore) -> None:
                self._store = store
                self.calls = 0

            def __call__(self, source, *, timeout_seconds, resolve_secret=None):  # type: ignore[no-untyped-def]
                self.calls += 1
                self._store.update(
                    source.live_source_id,
                    LiveSourceUpdate(endpoint_url="srt://0.0.0.0:9200?mode=listener"),
                )
                return ProbeObservation(
                    ok=True,
                    detail=f"{source.name} is delivering video (stale answer, old address).",
                    error_code=None,
                )

        probe = _RepointingProbe(store)
        verdict = _service(store, probe).verify_for_takeover(
            channel_id="gov-ch12", path_id="council-encoder", endpoint_url=_ENDPOINT
        )
        assert probe.calls == 1
        assert verdict.ok is False
        assert verdict.error_code == "source_changed_during_takeover"

        # The PATCH's own write already reset readiness to never_probed
        # (invalidates_readiness() -- endpoint changed). The bug this closes
        # is the probe's stale "ready" verdict silently overwriting that; the
        # row must still read never_probed, not ready, and not the new
        # endpoint's edit alone without the conflicting write ever having
        # landed.
        refreshed = store.get("council-encoder")
        assert refreshed is not None
        assert refreshed.probe_state == "never_probed"
        assert refreshed.endpoint_url == "srt://0.0.0.0:9200?mode=listener"

    def test_an_unrecordable_observation_fails_closed(self, store: LiveSourceStore) -> None:
        _create(store)
        service = _service(store, _CountingProbe(True))

        def _boom(*_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("row vanished")

        service._store.record_probe_observation = _boom  # type: ignore[attr-defined]
        verdict = service.verify_for_takeover(
            channel_id="gov-ch12", path_id="council-encoder", endpoint_url=_ENDPOINT
        )
        assert verdict.ok is False
        assert verdict.error_code == "observation_not_recorded"


class TestCredentialHandleFlow:
    def test_an_srt_handle_reaches_the_verdict_as_a_handle(self, store: LiveSourceStore) -> None:
        _create(store, handle="council-srt-passphrase")
        verdict = _service(store, _CountingProbe(True)).verify_for_takeover(
            channel_id="gov-ch12", path_id="council-encoder", endpoint_url=_ENDPOINT
        )
        assert verdict.ok is True
        assert verdict.secret_ref == "council-srt-passphrase"
        # The handle is what travels. The secret never appears in the verdict.
        assert "passphrase-value" not in verdict.reason

    def test_no_handle_means_no_secret_ref(self, store: LiveSourceStore) -> None:
        _create(store)
        verdict = _service(store, _CountingProbe(True)).verify_for_takeover(
            channel_id="gov-ch12", path_id="council-encoder", endpoint_url=_ENDPOINT
        )
        assert verdict.secret_ref is None

    def test_the_resolver_is_handed_to_the_probe_not_the_resolved_value(
        self, store: LiveSourceStore
    ) -> None:
        _create(store, handle="council-srt-passphrase")
        probe = _CountingProbe(True)
        _service(store, probe).probe("council-encoder")
        # Resolution happens inside the probe, at execution time, so rotating
        # the passphrase takes effect on the next check without a restart.
        assert probe.resolvers_seen and callable(probe.resolvers_seen[0])
