"""Focused guest composition routing across take, add and handback."""

from datetime import UTC, datetime
from types import SimpleNamespace

from civiccast.live.contribution import program
from civiccast.live.contribution.mixer import GuestFeed


def test_guest_program_takes_adds_and_returns_to_schedule(monkeypatch) -> None:
    class Sources:
        row = None

        def get(self, _source_id):
            return self.row

        def create(self, payload):
            self.row = SimpleNamespace(endpoint_url=payload.endpoint_url, row_version=1)

        def update(self, _source_id, payload):
            assert payload.expected_row_version == self.row.row_version
            self.row = SimpleNamespace(
                endpoint_url=payload.endpoint_url, row_version=self.row.row_version + 1
            )

    class Takeover:
        def __init__(self):
            self.active = None
            self.actions = []

        def state(self, _channel_id):
            return SimpleNamespace(active_session=self.active)

        def handback(self, **_kwargs):
            self.actions.append("handback")
            self.active = None

        def take(self, **kwargs):
            self.actions.append("take")
            self.active = SimpleNamespace(source_ref=kwargs["path_id"])

    class Handle:
        terminated = False
        failed = False

        def poll(self):
            return 1 if self.failed or self.terminated else None

        def terminate(self):
            self.terminated = True

    class Contributions:
        def __init__(self):
            self.sessions = []

        def list_sessions(self, **_kwargs):
            return self.sessions

        def get_invite(self, invite_id):
            return SimpleNamespace(invite_token=f"token-{invite_id}")

        def get_room(self, _room_id):
            return room

    class Readiness:
        def __init__(self, _store):
            pass

        def probe(self, _source_id):
            return None, SimpleNamespace(ok=True), None

    contributions = Contributions()
    sources = Sources()
    takeover = Takeover()
    handles = []
    feed_batches = []

    def proofs(_channel, _limit):
        if takeover.active is not None:
            # The old feed remains live while the new handoff is pending.
            if len(handles) > 1:
                assert not handles[-2].terminated
            return [SimpleNamespace(
                state="ON_AIR",
                proof_boundary="civiccast-egress-handoff-boundary",
                source_path=program.redact_source_uri(sources.row.endpoint_url),
                source_ref=takeover.active.source_ref,
                observed_at=datetime.now(UTC),
            )]
        return [SimpleNamespace(
            state="ON_AIR",
            proof_boundary="civiccast-egress-handoff-boundary",
            source_path="scheduled.ts",
            source_ref="scheduled",
            observed_at=datetime.now(UTC),
        )]

    def start(feeds, _uri):
        feed_batches.append(feeds)
        handle = Handle()
        handles.append(handle)
        return handle

    monkeypatch.setattr(program, "probe_guest_feed", lambda url, muted: GuestFeed(url, muted))
    monkeypatch.setattr(program, "start_guest_mix", start)
    monkeypatch.setattr(program, "wait_for_guest_mix", lambda _handle, _uri: None)
    monkeypatch.setattr(program, "LiveSourceReadinessService", Readiness)
    router = program.GuestProgramRouter(
        contributions,
        sources,
        lambda: takeover,
        rtsp_base="rtsp://127.0.0.1:8554",
        srt_base="srt://127.0.0.1:8890",
        proof_events=proofs,
    )
    room = SimpleNamespace(room_id="room", channel_id="public")
    first = SimpleNamespace(session_id="g1", invite_id="i1", state="on_air")
    second = SimpleNamespace(session_id="g2", invite_id="i2", state="on_air")

    contributions.sessions = [first]
    router.on_air(first, room)
    contributions.sessions = [first, second]
    router.on_air(second, room)
    assert [len(batch) for batch in feed_batches] == [1, 2]
    assert handles[0].terminated
    handles[1].failed = True
    router.check_health()
    assert [len(batch) for batch in feed_batches] == [1, 2, 2]
    assert handles[1].terminated
    router.off_air(first, room)
    assert [len(batch) for batch in feed_batches] == [1, 2, 2, 1]
    assert handles[2].terminated
    first.state = "connected"
    router.off_air(second, room)
    assert handles[3].terminated
    assert takeover.active is None
    assert takeover.actions == [
        "take", "handback", "take", "handback", "take", "handback", "take", "handback"
    ]
