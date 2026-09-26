# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""U51 item 2: one hostile reader must not be able to stall HLS publishing.

Live incident (2026-09-26, 10:36:53-10:37:48): a reader holding a channel's
``playlist.m3u8`` froze ALL THREE channels for viewers. The relay child stayed
a live pid and its segments kept advancing; only the manifest stopped.

Measured on a replay with the station's own ffmpeg (2026-09-26, U51 findings;
commands and results in ``reports/U51.md``):

  * the muxer publishes the playlist temp-file-then-RENAME on this build, so
    its publish needs DELETE access to the existing ``playlist.m3u8`` -- and a
    reader holding that file denies it: ``WinError 5`` / ``WinError 32``;
  * a held advertised manifest therefore freezes publishing for as long as the
    handle lives, silently: 0 stderr lines mentioning error/fail/denied, the
    child alive, and the whole pending window published on the muxer's next
    cut after the holder released;
  * ``-hls_flags temp_file`` cannot help (the temp-then-rename already happens
    unconditionally here), and restarting the child cannot help either: a FRESH
    child pointed at a held directory stalled identically (M4);
  * an IN-PLACE rewrite of the held file does not need delete access and
    succeeds (47 of 47 against the reader that blocked 46 of 47 renames);
  * ``open(path, "r+b")`` + write + truncate never exposes a zero-length or
    short file to a reader (0 torn of 290,508 reads), while a plain
    ``open(path, "wb")`` truncate-then-write exposed 32 torn reads, every one
    of them empty.

So the muxer is given a PRIVATE staging name no reader knows
(``playlist.mux.m3u8``), and the relay publishes the advertised
``playlist.m3u8`` from it by in-place rewrite. A reader holding the advertised
file can no longer block a publish. The staging name is not the served one:
``media_router`` and every reader still use ``playlist.m3u8``.

This file owns the publish loop's behaviour. The sibling
``test_hls_relay_stale_window.py`` owns the directory state at spawn.
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
from pathlib import Path

import pytest

from civiccast.egress import hls_relay
from civiccast.egress.hls_relay import HlsRelaySupervisor, _playlist_path_for
from civiccast.egress.models import EgressConfig, EgressSinkSpec
from civiccast.egress.sinks import HlsSink

#: The suite cannot wait seconds per assertion for a 0.25 s production cadence;
#: the publisher captures this at construction (the same seam
#: ``HLS_RELAY_LOG_CAP_BYTES`` uses), so patching it before the supervisor is
#: built drives the real loop, faster.
_FAST_INTERVAL_S = 0.02
_WAIT_S = 5.0


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


def _supervisor():
    calls: list[list[str]] = []
    procs: list[_FakeProcess] = []

    def starter(args: list[str]) -> _FakeProcess:
        calls.append(args)
        proc = _FakeProcess()
        procs.append(proc)
        return proc

    sup = HlsRelaySupervisor(starter=starter)
    _STARTED.append(sup)
    return sup, calls, procs


def _window(sequence: int) -> str:
    """What the muxer writes: a sliding window, no ENDLIST."""
    return (
        "#EXTM3U\n"
        "#EXT-X-VERSION:3\n"
        "#EXT-X-TARGETDURATION:2\n"
        f"#EXT-X-MEDIA-SEQUENCE:{sequence}\n"
        f"#EXTINF:2.000,\nseg{sequence:09d}.ts\n"
        f"#EXTINF:2.000,\nseg{sequence + 1:09d}.ts\n"
    )


def _seed_staged(path: Path, text: str) -> None:
    """Put a window on the staging file the way the muxer does: temp + replace.

    Not a stylistic choice. These tests write the staging playlist from the
    test thread while the publisher polls it, and the publisher republishes on
    a ``(st_mtime_ns, st_size)`` change -- so a NON-atomic ``write_text`` is two
    visible states (truncated-and-empty, then complete) and a poll landing
    between them publishes the empty one and then the full one, moving the
    advertised file's mtime twice for one seeded window. Measured: that made
    ``test_a_quiet_muxer_does_not_republish`` fail inside a full-file run (the
    stamp it had just read no longer matched), and it is not a test-side
    subtlety only -- it is why the production read path is safe: ffmpeg's write
    of this file is atomic (7 file ids for 7 updates, no shrink under one id,
    no absence between updates), so the publisher only ever reads whole
    windows.
    """
    tmp = path.with_name(path.name + ".seed.tmp")
    tmp.write_text(text)
    tmp.replace(path)


def _wait_for(predicate, *, timeout: float = _WAIT_S, interval: float = 0.01) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


#: Every test here starts a REAL publisher thread, and so does every other test
#: file that starts a relay and never stops it. The thread list is
#: process-wide, so an assertion about "no publisher is left" has to be a DELTA
#: on live thread identities, never an absolute count: a supervisor another file
#: abandoned is still running under the same ``hls-manifest-publish:<channel>``
#: name, and would read as this test's leak.
_STARTED: list[HlsRelaySupervisor] = []


@pytest.fixture(autouse=True)
def _stop_every_supervisor_this_test_started():
    """Stop the supervisors this test started, so thread state is per-test."""
    yield
    while _STARTED:
        with contextlib.suppress(Exception):
            _STARTED.pop().stop_all()


def _started(tmp_path, monkeypatch, label: str = "Web"):
    """A supervisor with one live relay on ``tmp_path / <label>``."""
    monkeypatch.setattr(hls_relay, "_MANIFEST_PUBLISH_INTERVAL_S", _FAST_INTERVAL_S)
    sink = _hls_sink(str(tmp_path / label), label=label)
    sup, calls, _procs = _supervisor()
    sup.apply(_config(sink))
    assert len(calls) == 1
    return sup, sink


def _publish_threads() -> list[str]:
    return sorted(
        t.name for t in threading.enumerate() if t.name.startswith("hls-manifest-publish:")
    )


def _publish_thread_idents() -> set[int]:
    """The ids of the publisher threads alive right now.

    Ids rather than names: a neighbour test file's abandoned publisher carries
    the same name as this test's, so ``after - before`` over ids is the only
    comparison that answers "did THIS test leave a thread behind".
    """
    return {
        thread.ident
        for thread in threading.enumerate()
        if thread.name.startswith("hls-manifest-publish:") and thread.ident is not None
    }


# --- the contract: which file the muxer writes, which file the world reads --------


def test_the_muxer_writes_a_private_staging_playlist_not_the_advertised_one(tmp_path) -> None:
    """The child's argv must aim at the staging name. That single word is what
    stops a held ``playlist.m3u8`` from blocking the muxer's own rename."""
    live_dir = tmp_path / "gov"
    sup, calls, _procs = _supervisor()

    sup.apply(_config(_hls_sink(str(live_dir))))

    assert calls[0][-1] == str(live_dir / "playlist.mux.m3u8")
    hls_sink = HlsSink(_hls_sink(str(live_dir)))
    assert hls_sink.connect_target() == str(live_dir / "playlist.mux.m3u8")
    assert hls_sink.manifest_target() == str(live_dir / "playlist.m3u8")


def test_the_progress_reader_watches_the_advertised_manifest(tmp_path) -> None:
    """Progress/health must track the file VIEWERS fetch. If it watched the
    muxer's private staging file, a wedged publisher would read as a healthy
    relay while residents got nothing."""
    live_dir = tmp_path / "gov"

    assert _playlist_path_for(str(live_dir)) == live_dir / "playlist.m3u8"


# --- the loop --------------------------------------------------------------------


def test_the_advertised_manifest_follows_the_muxer_while_a_reader_holds_it(
    tmp_path, monkeypatch
) -> None:
    """The incident, reproduced as a unit test.

    A reader holds the advertised manifest for the whole middle of this test --
    the shape that froze all three channels live -- while the muxer publishes a
    new window. The advertised file must follow anyway."""
    sup, _sink = _started(tmp_path, monkeypatch)
    live_dir = tmp_path / "Web"
    staged = live_dir / "playlist.mux.m3u8"
    advertised = live_dir / "playlist.m3u8"

    _seed_staged(staged, _window(100))
    assert _wait_for(lambda: advertised.exists() and advertised.read_text() == _window(100))

    with advertised.open("rb"):  # the holder IS the test
        _seed_staged(staged, _window(101))
        assert _wait_for(lambda: advertised.read_text() == _window(101))

    sup.stop_channel("gov")


def test_the_published_manifest_is_a_byte_for_byte_copy(tmp_path, monkeypatch) -> None:
    """No re-writing, no tag surgery: the player gets exactly what the muxer
    wrote (this is what makes the two write paths agree on segments)."""
    _sup, _sink = _started(tmp_path, monkeypatch)
    staged = tmp_path / "Web" / "playlist.mux.m3u8"
    advertised = tmp_path / "Web" / "playlist.m3u8"

    _seed_staged(staged, _window(7))
    assert _wait_for(lambda: advertised.exists())
    assert advertised.read_bytes() == staged.read_bytes()


def test_a_quiet_muxer_does_not_republish(tmp_path, monkeypatch) -> None:
    """Publish on CHANGE, not on a timer: rewriting the manifest for no reason
    every tick is churn no reader asked for (and on this platform every rewrite
    is a window in which a hostile reader could have blocked a rename)."""
    _sup, _sink = _started(tmp_path, monkeypatch)
    staged = tmp_path / "Web" / "playlist.mux.m3u8"
    advertised = tmp_path / "Web" / "playlist.m3u8"

    _seed_staged(staged, _window(3))
    assert _wait_for(lambda: advertised.exists())
    stamp = advertised.stat().st_mtime_ns

    time.sleep(_FAST_INTERVAL_S * 10)

    assert advertised.stat().st_mtime_ns == stamp


def test_no_staging_window_yet_publishes_nothing(tmp_path, monkeypatch) -> None:
    """A just-started relay has no staging playlist until the muxer's first
    cut (2 s away). The publisher must idle, not invent or delete anything."""
    _sup, _sink = _started(tmp_path, monkeypatch)

    time.sleep(_FAST_INTERVAL_S * 10)

    assert not (tmp_path / "Web" / "playlist.m3u8").exists()


def test_a_vanished_staging_window_is_never_un_published(tmp_path, monkeypatch) -> None:
    """If the staging file disappears (a wipe, a sibling session), the last
    published window stays served. Blanking the manifest because the source
    vanished would turn a transient gap into a viewer-visible 404."""
    _sup, _sink = _started(tmp_path, monkeypatch)
    staged = tmp_path / "Web" / "playlist.mux.m3u8"
    advertised = tmp_path / "Web" / "playlist.m3u8"

    _seed_staged(staged, _window(11))
    assert _wait_for(lambda: advertised.exists() and advertised.read_text() == _window(11))
    staged.unlink()

    time.sleep(_FAST_INTERVAL_S * 10)

    assert advertised.read_text() == _window(11)


def test_a_staging_file_left_by_a_locked_predecessor_is_not_republished(
    tmp_path, monkeypatch
) -> None:
    """A fossil staging playlist the spawn wipe could not remove (a handle held
    across the spawn) must not be advertised as if it were the new session's
    window. Only what the CURRENT child writes gets published."""
    live_dir = tmp_path / "Web"
    live_dir.mkdir(parents=True)
    fossil = live_dir / "playlist.mux.m3u8"
    _seed_staged(fossil, _window(900))  # an old session's window, mtime in the past
    stale = time.time() - 600
    os.utime(fossil, (stale, stale))

    handle = fossil.open("rb")  # holds it across the spawn, so the wipe skips it
    try:
        sup, _sink = _started(tmp_path, monkeypatch)
        assert fossil.exists()  # the wipe really did skip it

        time.sleep(_FAST_INTERVAL_S * 10)

        assert not (live_dir / "playlist.m3u8").exists()
        sup.stop_channel("gov")
    finally:
        handle.close()


def test_stopping_the_channel_stops_publishing(tmp_path, monkeypatch) -> None:
    """The publisher is a daemon thread per relay; ``stop_channel`` must close
    it (child first, then the thread) or a stopped channel would keep touching
    disk."""
    sup, _sink = _started(tmp_path, monkeypatch)
    staged = tmp_path / "Web" / "playlist.mux.m3u8"
    advertised = tmp_path / "Web" / "playlist.m3u8"
    _seed_staged(staged, _window(200))
    assert _wait_for(lambda: advertised.exists())

    before = _publish_thread_idents()
    sup.stop_channel("gov")

    assert _publish_thread_idents() - before == set(), (
        f"stop_channel left this relay's publisher running: {_publish_threads()}"
    )
    stamp = advertised.stat().st_mtime_ns
    _seed_staged(staged, _window(201))  # the muxer is gone too, but be explicit
    time.sleep(_FAST_INTERVAL_S * 10)
    assert advertised.stat().st_mtime_ns == stamp


def test_the_publisher_survives_an_unreadable_staging_file(tmp_path, monkeypatch) -> None:
    """Never raise, never stop: a failed poll is retried on the next tick and
    the relay is untouched (the log writer's own contract, reused here)."""
    _sup, _sink = _started(tmp_path, monkeypatch)
    live_dir = tmp_path / "Web"
    staged = live_dir / "playlist.mux.m3u8"
    _seed_staged(staged, _window(50))
    advertised = live_dir / "playlist.m3u8"
    assert _wait_for(lambda: advertised.exists())

    # A directory where the publisher expects a file: reads fail, and the loop
    # must keep going rather than die.
    staged.unlink()
    staged.mkdir()
    time.sleep(_FAST_INTERVAL_S * 10)
    staged.rmdir()
    _seed_staged(staged, _window(51))

    assert _wait_for(lambda: advertised.read_text() == _window(51))


def test_a_relay_that_could_not_start_leaves_no_publisher(tmp_path, monkeypatch) -> None:
    """Degraded start (no ffmpeg) must not leave a thread behind for a channel
    that is not publishing anything."""
    monkeypatch.setattr(hls_relay, "_MANIFEST_PUBLISH_INTERVAL_S", _FAST_INTERVAL_S)

    def starter(args: list[str]):
        raise OSError("ffmpeg is not there")

    sup = HlsRelaySupervisor(starter=starter)
    before = _publish_thread_idents()
    sup.apply(_config(_hls_sink(str(tmp_path / "Web"))))

    assert _publish_thread_idents() - before == set(), (
        f"a degraded start left a publisher behind: {_publish_threads()}"
    )


def test_the_manifest_target_is_what_the_router_serves(tmp_path) -> None:
    """``media_router`` resolves the channel's configured hls sink URI to a
    directory and serves ``playlist.m3u8`` from it -- the advertised name is
    the router's, not this module's, to choose."""
    hls_sink = HlsSink(_hls_sink(str(tmp_path / "Web")))
    assert Path(hls_sink.manifest_target()).name == "playlist.m3u8"
    assert Path(hls_sink.manifest_target()).parent == tmp_path / "Web"
