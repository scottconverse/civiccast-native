# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contract + sensitivity tests for the U50 caption segment keeper.

SYNTHETIC-FIXTURE tests: they build their own channel directories under
`tmp_path` and never read the live station, so they are safe to run while a
rung is up.  Every negative assertion is paired with a positive control, so a
test that stops being able to fail is visible.

The keeper's job is to hold enough FINISHED segments that the verifier's 60 s
caption window is real rather than nominal: the live directory keeps only ~7
segments (14 s), and the fossils beside them are older runs' playlist tails,
not this run's history.
"""

from __future__ import annotations

import datetime
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

_KEEPER = Path(__file__).resolve().with_name("segment_keeper.py")
_SPEC = importlib.util.spec_from_file_location("segment_keeper", _KEEPER)
assert _SPEC is not None and _SPEC.loader is not None
keeper = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = keeper
_SPEC.loader.exec_module(keeper)

#: A frozen clock.  `keep_once` takes `now` explicitly, so no test needs the
#: real one; the fixtures below are all expressed relative to this instant.
_NOW = 1_700_000_000.0


def _segments(
    channel_dir: Path, *, count: int, seconds: float = 2.0, first: int = 1000
) -> list[str]:
    """Write `count` segments ending at _NOW, 2 s apart, newest last."""

    channel_dir.mkdir(parents=True, exist_ok=True)
    names = []
    for i in range(count):
        name = f"seg{first + i:09d}.ts"
        path = channel_dir / name
        path.write_bytes(b"\x47" * 512)
        stamp = _NOW - (count - 1 - i) * seconds
        os.utime(path, (stamp, stamp))
        names.append(name)
    return names


def _fossil(channel_dir: Path, name: str, *, age: float, size: int = 2048) -> Path:
    """Write a segment that stopped being live long ago: a fossil."""

    channel_dir.mkdir(parents=True, exist_ok=True)
    path = channel_dir / name
    path.write_bytes(b"\x47" * size)
    os.utime(path, (_NOW - age, _NOW - age))
    return path


def _out_root(tmp_path: Path) -> Path:
    root = tmp_path / "cc-caption-keep"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _run(hls_root: Path, out_root: Path, **kwargs):
    """keep_once with the test's cheap defaults: no real sleeping, frozen now."""

    kwargs.setdefault("now", _NOW)
    kwargs.setdefault("sleep", lambda _seconds: None)
    return keeper.keep_once(hls_root, out_root, **kwargs)


# --- finished_segments: what counts as keepable -----------------------------


def test_finished_segments_excludes_the_newest_two(tmp_path: Path) -> None:
    channel = tmp_path / "public"
    names = _segments(channel, count=10)

    got = [p.name for p in keeper.finished_segments(channel, now=_NOW)]

    assert got == list(reversed(names[:-2]))
    assert names[-1] not in got and names[-2] not in got


def test_finished_segments_drops_the_fossils(tmp_path: Path) -> None:
    channel = tmp_path / "public"
    names = _segments(channel, count=8)
    _fossil(channel, "seg000018677.ts", age=10_000.0)
    _fossil(channel, "seg000001284.ts", age=200.0)

    got = [p.name for p in keeper.finished_segments(channel, now=_NOW)]

    assert got == list(reversed(names[:-2]))
    assert "seg000018677.ts" not in got
    assert "seg000001284.ts" not in got


def test_finished_segments_ignores_names_that_are_not_segments(tmp_path: Path) -> None:
    channel = tmp_path / "public"
    names = _segments(channel, count=6)
    (channel / "playlist.m3u8").write_text("#EXTM3U\n", encoding="utf-8")
    (channel / "seg000000000.ts.tmp").write_text("x", encoding="utf-8")
    os.utime(channel / "playlist.m3u8", (_NOW - 5.0, _NOW - 5.0))

    got = [p.name for p in keeper.finished_segments(channel, now=_NOW)]

    assert got == list(reversed(names[:-2]))


def test_finished_segments_of_a_missing_channel_is_empty_not_an_error(tmp_path: Path) -> None:
    assert keeper.finished_segments(tmp_path / "absent", now=_NOW) == []


# --- keep_once: the copy itself --------------------------------------------


def test_keep_once_copies_the_finished_segments_it_may_use(tmp_path: Path) -> None:
    hls, out = tmp_path / "hls", _out_root(tmp_path)
    names = _segments(hls / "public", count=10)

    report = _run(hls, out)

    copied = report["channels"]["public"]["copied"]
    assert copied == list(reversed(names[:-2]))
    for name in names[:-2]:
        assert (out / "public" / name).read_bytes() == b"\x47" * 512


def test_keep_once_never_copies_the_newest_two_or_a_fossil(tmp_path: Path) -> None:
    hls, out = tmp_path / "hls", _out_root(tmp_path)
    names = _segments(hls / "public", count=10)
    _fossil(hls / "public", "seg000018677.ts", age=9_000.0)

    _run(hls, out)

    dest = out / "public"
    assert not (dest / names[-1]).exists()
    assert not (dest / names[-2]).exists()
    assert not (dest / "seg000018677.ts").exists()
    # positive control: the copy really is on disk for a segment it may use
    assert (dest / names[0]).exists()


def test_keep_once_preserves_the_source_mtime_on_the_copy(tmp_path: Path) -> None:
    hls, out = tmp_path / "hls", _out_root(tmp_path)
    names = _segments(hls / "public", count=6)

    _run(hls, out)

    # the verifier orders the window by the COPY's mtime, so this is the whole
    # point of os.utime: a copy that lands with "now" would read as newest.
    for name in names[:-2]:
        src = (hls / "public" / name).stat()
        dst = (out / "public" / name).stat()
        assert dst.st_mtime_ns == src.st_mtime_ns
    assert (out / "public" / names[0]).stat().st_mtime_ns < int(_NOW * 1_000_000_000)


def test_keep_once_does_not_recopy_a_segment_it_already_holds(tmp_path: Path) -> None:
    hls, out = tmp_path / "hls", _out_root(tmp_path)
    names = _segments(hls / "public", count=6)
    wanted = list(reversed(names[:-2]))

    first = _run(hls, out)
    second = _run(hls, out, now=_NOW + 2.0)

    assert first["channels"]["public"]["copied"] == wanted
    assert first["channels"]["public"]["already"] == []
    # second pass: everything it still may keep is already held, so it spends
    # no reads and no bytes on it
    assert second["channels"]["public"]["already"] == wanted
    assert second["channels"]["public"]["copied"] == []


def test_keep_once_prunes_copies_older_than_the_keep_window(tmp_path: Path) -> None:
    hls, out = tmp_path / "hls", _out_root(tmp_path)
    _segments(hls / "public", count=6)
    stale = out / "public" / "seg000009000.ts"
    out.joinpath("public").mkdir(parents=True, exist_ok=True)
    stale.write_bytes(b"\x47" * 512)
    os.utime(stale, (_NOW - 400.0, _NOW - 400.0))

    report = _run(hls, out)

    assert report["channels"]["public"]["pruned"] == ["seg000009000.ts"]
    assert not stale.exists()


def test_keep_once_keeps_a_copy_inside_the_keep_window(tmp_path: Path) -> None:
    hls, out = tmp_path / "hls", _out_root(tmp_path)
    names = _segments(hls / "public", count=6)

    report = _run(hls, out)

    assert report["channels"]["public"]["pruned"] == []
    assert (out / "public" / names[0]).exists()


def test_keep_once_prunes_an_abandoned_part_file(tmp_path: Path) -> None:
    hls, out = tmp_path / "hls", _out_root(tmp_path)
    _segments(hls / "public", count=6)
    (out / "public").mkdir(parents=True, exist_ok=True)
    part = out / "public" / "seg000009001.ts.part"
    part.write_bytes(b"\x47" * 16)
    os.utime(part, (_NOW - 400.0, _NOW - 400.0))

    report = _run(hls, out)

    assert not part.exists()
    assert "seg000009001.ts.part" in report["channels"]["public"]["pruned"]


def test_keep_once_leaves_no_part_file_behind(tmp_path: Path) -> None:
    hls, out = tmp_path / "hls", _out_root(tmp_path)
    _segments(hls / "public", count=6)

    _run(hls, out)

    assert [p.name for p in (out / "public").iterdir() if p.name.endswith(".part")] == []
    assert sorted(p.name for p in (out / "public").iterdir()) == [
        f"seg{1000 + i:09d}.ts" for i in range(4)
    ]


def test_keep_once_holds_no_handle_on_the_live_segment(tmp_path: Path) -> None:
    hls, out = tmp_path / "hls", _out_root(tmp_path)
    names = _segments(hls / "public", count=6)

    _run(hls, out)

    # If the keeper had left the source open, Windows would refuse this rename.
    for name in names:
        src = hls / "public" / name
        src.replace(src.with_name(name + ".rotated"))
    assert (out / "public" / names[0]).exists()


def test_keep_once_never_reads_or_writes_the_playlist(tmp_path: Path) -> None:
    hls, out = tmp_path / "hls", _out_root(tmp_path)
    _segments(hls / "public", count=6)
    playlist = hls / "public" / "playlist.m3u8"
    playlist.write_text("#EXTM3U\nseg000001000.ts\n", encoding="utf-8")
    before = (playlist.read_bytes(), playlist.stat().st_mtime_ns)

    report = _run(hls, out)

    assert (playlist.read_bytes(), playlist.stat().st_mtime_ns) == before
    assert [p.name for p in out.rglob("*.m3u8")] == []
    assert report["channels"]["public"]["copied"] == [
        f"seg{1000 + i:09d}.ts" for i in reversed(range(4))
    ]


def test_keep_once_does_every_channel(tmp_path: Path) -> None:
    hls, out = tmp_path / "hls", _out_root(tmp_path)
    for channel in keeper.CHANNELS:
        _segments(hls / channel, count=6)

    report = _run(hls, out)

    for channel in keeper.CHANNELS:
        assert len(report["channels"][channel]["copied"]) == 4
        assert (out / channel / "seg000001000.ts").exists()


def test_keep_once_reports_a_missing_channel_without_failing_the_others(tmp_path: Path) -> None:
    hls, out = tmp_path / "hls", _out_root(tmp_path)
    _segments(hls / "public", count=6)

    report = _run(hls, out)

    assert report["channels"]["government"]["copied"] == []
    assert report["channels"]["government"]["errors"] == []
    assert len(report["channels"]["public"]["copied"]) == 4


# --- keep_once: the read races ---------------------------------------------


def test_keep_once_retries_a_read_that_races_the_relay_replace(tmp_path: Path, monkeypatch) -> None:
    hls, out = tmp_path / "hls", _out_root(tmp_path)
    names = _segments(hls / "public", count=6)
    real = keeper._read_live_segment
    seen: list[int] = []

    def racy(src):
        seen.append(1)
        if len(seen) <= 2:
            raise PermissionError(13, "in use by another process")
        return real(src)

    monkeypatch.setattr(keeper, "_read_live_segment", racy)

    report = _run(hls, out)

    assert len(seen) > 2
    assert report["channels"]["public"]["copied"] == [
        f"seg{1000 + i:09d}.ts" for i in reversed(range(4))
    ]
    assert (out / "public" / names[0]).exists()


def test_keep_once_reports_a_segment_it_could_never_read(tmp_path: Path, monkeypatch) -> None:
    hls, out = tmp_path / "hls", _out_root(tmp_path)
    _segments(hls / "public", count=6)

    def always_racy(_src):
        raise PermissionError(13, "in use by another process")

    monkeypatch.setattr(keeper, "_read_live_segment", always_racy)

    report = _run(hls, out)

    errors = report["channels"]["public"]["errors"]
    assert report["channels"]["public"]["copied"] == []
    assert len(errors) == 4
    assert all("PermissionError" in e for e in errors)
    assert list((out / "public").iterdir()) == []


def test_keep_once_does_not_accept_an_unstable_read(tmp_path: Path, monkeypatch) -> None:
    hls, out = tmp_path / "hls", _out_root(tmp_path)
    _segments(hls / "public", count=6)

    monkeypatch.setattr(keeper, "_read_live_segment", lambda _src: None)

    report = _run(hls, out)

    assert report["channels"]["public"]["copied"] == []
    assert len(report["channels"]["public"]["errors"]) == 4
    assert list((out / "public").iterdir()) == []


# --- the heartbeat ----------------------------------------------------------


def test_write_heartbeat_lands_under_the_out_root_with_a_fresh_mtime(tmp_path: Path) -> None:
    out = _out_root(tmp_path)
    report = {"channels": {"public": {"copied": ["a"], "pruned": [], "errors": []}}}

    path = keeper.write_heartbeat(out, now=_NOW, loops=3, report=report)

    assert path == out / "heartbeat.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["updated_epoch"] == _NOW
    assert body["loops"] == 3
    assert body["pid"] == os.getpid()
    assert body["channels"]["public"]["copied"] == 1
    assert path.stat().st_mtime == pytest.approx(_NOW, abs=2.0)


def test_write_heartbeat_is_written_even_with_no_report(tmp_path: Path) -> None:
    out = _out_root(tmp_path)

    path = keeper.write_heartbeat(out, now=_NOW, loops=1)

    assert json.loads(path.read_text(encoding="utf-8"))["channels"] == {}


# --- the loop and the command line -----------------------------------------


def test_run_keeps_a_heartbeat_each_loop_and_exits_at_until(tmp_path: Path) -> None:
    hls, out = tmp_path / "hls", _out_root(tmp_path)
    _segments(hls / "public", count=6)
    ticks = [_NOW]
    sleeps: list[float] = []

    def clock() -> float:
        return ticks[-1]

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        ticks.append(ticks[-1] + seconds)

    loops = keeper.run(
        hls,
        out,
        until=_NOW + 12.0,
        interval=4.0,
        clock=clock,
        sleep=sleep,
        keep_seconds=180.0,
        fresh_seconds=120.0,
    )

    assert loops == 3
    assert sleeps == [4.0, 4.0, 4.0]
    body = json.loads((out / "heartbeat.json").read_text(encoding="utf-8"))
    assert body["loops"] == 3


def test_run_survives_a_channel_directory_that_vanishes_mid_loop(
    tmp_path: Path, monkeypatch
) -> None:
    hls, out = tmp_path / "hls", _out_root(tmp_path)
    _segments(hls / "public", count=6)
    calls: list[int] = []
    ticks = [_NOW]

    def boom(*_a, **_k):
        calls.append(1)
        raise OSError("the relay moved the directory")

    monkeypatch.setattr(keeper, "keep_once", boom)

    loops = keeper.run(
        hls,
        out,
        until=_NOW + 9.0,
        interval=4.0,
        clock=lambda: ticks[0],
        sleep=lambda s: ticks.__setitem__(0, ticks[0] + s),
    )

    assert len(calls) == 3
    assert loops == 3
    body = json.loads((out / "heartbeat.json").read_text(encoding="utf-8"))
    assert body["loops"] == 3
    assert body["errors"], "a failed loop must be visible in the heartbeat, not silent"


def test_parse_until_accepts_iso_and_epoch() -> None:
    # the ISO form is LOCAL time (the rung and the coordinator both think in the
    # station's clock, and rung.ps1 computes its --until from a local DateTime)
    assert keeper.parse_until("2026-09-26T21:37:00") == pytest.approx(
        datetime.datetime(2026, 9, 26, 21, 37).timestamp()
    )
    assert keeper.parse_until("1790554620") == 1790554620.0


def test_parse_until_rejects_nonsense() -> None:
    with pytest.raises(ValueError):
        keeper.parse_until("half past nine")


def test_main_exits_immediately_when_until_is_past(tmp_path: Path, capsys) -> None:
    hls, out = tmp_path / "hls", _out_root(tmp_path)
    _segments(hls / "public", count=6)

    rc = keeper.main(["--hls", str(hls), "--out", str(out), "--until", "1"])

    assert rc == 0
    assert json.loads((out / "heartbeat.json").read_text(encoding="utf-8"))["loops"] == 0
    assert "already past" in capsys.readouterr().out
