# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""U51 item 1: a relay (re)start must not inherit the previous session's window.

Live finding (2026-09-26): every relay start left its final window behind in
the channel's HLS directory, so a station that had restarted a dozen times
since 09-19 carried 35-43 stale ``seg*.ts`` per channel. The writer is
``HlsSink.container_args()`` with ``append_list``: the muxer continues the
sequence and playlist it finds on disk, so the fossils are not merely wasted
disk -- they are what a fresh child appends behind.

The fix under test is deliberately blunt: at relay (re)start, BEFORE the child
is launched, clear the channel's HLS directory (``seg*.ts``, the advertised
``playlist.m3u8``, the muxer's private staging playlist, and any ``*.tmp``).
The one hard requirement is that a locked file can NEVER fail the start: on
Windows a reader holding a file blocks its unlink (``WinError 32``), exactly
as it blocks the muxer's playlist rename, and a relay that refuses to start
because a viewer held a file would trade a leaked segment for a dead channel.

Scope note: this file is about the DIRECTORY STATE AT SPAWN. The sibling
``test_hls_relay_manifest_publish.py`` owns what the relay publishes while it
runs.
"""

from __future__ import annotations

import contextlib
import logging

import pytest

from civiccast.egress.hls_relay import HlsRelaySupervisor
from civiccast.egress.models import EgressConfig, EgressSinkSpec

_RELAY_LOGGER = "civiccast.egress.hls_relay"

#: Every supervisor built here starts a REAL U51 publisher thread (the fake
#: starter only fakes the child, not the thread). Left running, they would leak
#: for the rest of the session and show up in a later test's thread assertion.
_STARTED: list[HlsRelaySupervisor] = []


@pytest.fixture(autouse=True)
def _stop_every_supervisor_this_test_started():
    yield
    while _STARTED:
        with contextlib.suppress(Exception):
            _STARTED.pop().stop_all()


class _FakeProcess:
    def __init__(self) -> None:
        self.terminated = False
        self._returncode: int | None = None

    def poll(self) -> int | None:
        return self._returncode

    def terminate(self, *, grace_seconds: float = 5.0) -> int | None:
        self.terminated = True
        self._returncode = 0
        return 0


def _config(*sinks: EgressSinkSpec, channel_id: str = "gov") -> EgressConfig:
    return EgressConfig(
        channel_id=channel_id, enabled=True, slate_message="slate", sinks=list(sinks)
    )


def _hls_sink(uri: str, label: str = "Web") -> EgressSinkSpec:
    return EgressSinkSpec(kind="hls", label=label, uri=uri)


def _supervisor(*, on_spawn=None):
    """A supervisor whose starter can snapshot the directory AT SPAWN TIME.

    The snapshot has to be taken inside the starter, not after ``apply``
    returns: the assertion this file exists for is the ORDER (the window is
    cleared before the child exists), and only the starter can witness it.
    """
    calls: list[list[str]] = []
    procs: list[_FakeProcess] = []
    at_spawn: list[list[str]] = []

    def starter(args: list[str]) -> _FakeProcess:
        calls.append(args)
        if on_spawn is not None:
            at_spawn.append(on_spawn())
        proc = _FakeProcess()
        procs.append(proc)
        return proc

    sup = HlsRelaySupervisor(starter=starter)
    _STARTED.append(sup)
    return sup, calls, procs, at_spawn


def _seed_window(live_dir, *, newest: int = 42, segments: int = 3) -> None:
    """Leave behind what a stopped relay leaves: segments, a playlist, debris."""
    live_dir.mkdir(parents=True, exist_ok=True)
    first = newest - segments + 1
    for index in range(first, newest + 1):
        (live_dir / f"seg{index:09d}.ts").write_bytes(b"stale-segment")
    entries = "".join(f"#EXTINF:2.000,\nseg{index:09d}.ts\n" for index in range(first, newest + 1))
    (live_dir / "playlist.m3u8").write_text(f"#EXTM3U\n{entries}")
    (live_dir / "playlist.mux.m3u8").write_text(f"#EXTM3U\n{entries}")
    (live_dir / "playlist.mux.m3u8.tmp").write_text("#EXTM3U\n")


def test_a_restart_clears_the_previous_sessions_window_before_the_child_starts(
    tmp_path,
) -> None:
    """The whole item-1 requirement in one assertion: at spawn, the directory is
    empty. Not "the child overwrites it" -- the stale files are gone before the
    child that would have appended to them exists."""
    live_dir = tmp_path / "gov"
    _seed_window(live_dir)
    sup, calls, procs, at_spawn = _supervisor(
        on_spawn=lambda: sorted(entry.name for entry in live_dir.iterdir())
    )

    sup.apply(_config(_hls_sink(str(live_dir))))

    assert len(calls) == 1
    assert not procs[0].terminated
    assert at_spawn == [[]]
    assert sorted(entry.name for entry in live_dir.iterdir()) == []


def test_a_fresh_start_with_nothing_on_disk_still_starts(tmp_path) -> None:
    """The wipe must not be the thing that creates a failure mode: a first-ever
    start has no directory at all, and the relay has to come up anyway."""
    live_dir = tmp_path / "gov"  # deliberately NOT created

    sup, calls, procs, _at_spawn = _supervisor()
    sup.apply(_config(_hls_sink(str(live_dir))))

    assert len(calls) == 1
    assert not procs[0].terminated
    assert live_dir.is_dir()


def test_a_locked_fossil_is_skipped_and_never_fails_the_start(tmp_path, caplog) -> None:
    """Tolerate-and-continue. A held file is skipped, the rest is still cleared,
    the relay still starts -- and the skip is logged, not silent."""
    live_dir = tmp_path / "gov"
    _seed_window(live_dir)
    locked = live_dir / "seg000000042.ts"
    handle = locked.open("rb")  # the reader shape that blocks unlink on Windows
    try:
        sup, calls, procs, _at_spawn = _supervisor()
        with caplog.at_level(logging.WARNING, logger=_RELAY_LOGGER):
            sup.apply(_config(_hls_sink(str(live_dir))))

        assert len(calls) == 1  # the child was still launched
        assert not procs[0].terminated
        assert locked.exists()  # the held file survives...
        assert sorted(entry.name for entry in live_dir.iterdir()) == [locked.name]
        assert locked.name in caplog.text  # ...and the skip is visible to an operator
    finally:
        handle.close()


def test_a_rebind_also_clears_the_window_it_replaces(tmp_path) -> None:
    """The wipe belongs to the SPAWN, not to the process's first start. A U21
    rebind (``new_session=True``) tears the child down and spawns a replacement
    for a genuinely new worker session, so the replacement must start from an
    empty directory rather than appending behind the session it replaced."""
    live_dir = tmp_path / "gov"
    live_dir.mkdir(parents=True)
    sup, calls, procs, at_spawn = _supervisor(
        on_spawn=lambda: sorted(entry.name for entry in live_dir.iterdir())
    )

    sup.apply(_config(_hls_sink(str(live_dir))))
    _seed_window(live_dir, newest=77)  # what the first child left behind
    sup.apply(_config(_hls_sink(str(live_dir))), new_session=True)

    assert len(calls) == 2
    assert procs[0].terminated
    assert not procs[1].terminated
    assert at_spawn[1] == []


def test_a_uri_change_clears_the_new_directory_not_the_old_one(tmp_path) -> None:
    """A sink whose directory moved gets the NEW directory cleared; the old one
    is not touched by that spawn (its own relay -- if any -- owns it, and a
    sibling sink may still be configured against it)."""
    old_dir = tmp_path / "gov"
    new_dir = tmp_path / "gov-v2"
    live_old = tmp_path / "live-old"  # stands in for the first child's own window
    sup, calls, _procs, _at_spawn = _supervisor()
    sup.apply(_config(_hls_sink(str(old_dir))))
    # The first child's window, written after its own spawn: this is state the
    # SECOND spawn must leave alone -- as is the old directory itself, which a
    # sibling sink may still be configured against.
    _seed_window(live_old, newest=9)
    _seed_window(old_dir, newest=9)
    _seed_window(new_dir, newest=5)  # a previous session in the new directory too

    sup.apply(_config(_hls_sink(str(new_dir))))

    assert len(calls) == 2
    assert sorted(entry.name for entry in new_dir.iterdir()) == []
    assert (old_dir / "playlist.mux.m3u8").exists()  # never a target of this spawn
    assert (live_old / "playlist.mux.m3u8").exists()
