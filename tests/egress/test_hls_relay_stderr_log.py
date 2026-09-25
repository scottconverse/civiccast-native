# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""BETA.10 U24 — each HLS relay child's stderr is captured, per channel, bounded.

Two live incidents had no evidence because the relay child's stderr went to
``subprocess.DEVNULL`` (``start_ffmpeg`` is called with no ``stderr_path``):

* 2026-09-25 00:51:26 (education) — on slate entry the channel's output jumped
  +19.75 s A/V inside the relay; U21 could not decide where the jump is born
  because the child's own ``timestamp discontinuity``/``Non-monotonous DTS``
  lines were discarded.
* 2026-09-25 01:04 — a freshly restarted relay child wrote nothing for ~2
  minutes while the engine was producing; U21 recorded INFERRED ("its input
  was not delivering") with no child-side evidence.

This module proves the capture contract at the unit layer, with the fake
starter the relay's own tests already use:

* one file per (channel, sink): ``<log_root>/<channel>/logs/hls-relay.<sink>.stderr.log``
* one header line per spawn (UTC, channel, sink, pid, spawn ordinal, reason,
  full argv) — the argument/session evidence survives every rotation;
* the child's stderr lands in that file verbatim (``start_ffmpeg`` already
  opens ``stderr_path`` in append mode and hands ffmpeg a real file handle,
  so a full pipe can never stall the relay);
* current + one previous, rotated at spawn only, hard-capped by an in-place
  trim (Windows cannot rename a file another process holds open);
* no log root configured -> no file, and the starter keeps its one-argument
  call shape (the pre-U24 contract every other relay test double relies on).
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import IO

import pytest

from civiccast.egress.hls_relay import (
    HLS_RELAY_LOG_CAP_BYTES,
    HLS_RELAY_LOG_TAIL_BYTES,
    HlsRelaySupervisor,
    _default_starter,
)
from civiccast.egress.models import EgressConfig, EgressSinkSpec

_CHILD_PID = 4242

#: ffmpeg's own presence, not GStreamer's: this capture is ffmpeg-side only.
_FFMPEG = shutil.which("ffmpeg")
requires_ffmpeg = pytest.mark.skipif(
    _FFMPEG is None,
    reason="ffmpeg is not on PATH -- the real-child stderr capture is UNPROVEN here; "
    "the fake-starter capture contract above is not a substitute for it",
)


def _config(*sinks: EgressSinkSpec, channel_id: str = "gov") -> EgressConfig:
    return EgressConfig(
        channel_id=channel_id, enabled=True, slate_message="slate", sinks=list(sinks)
    )


def _hls_sink(uri: str = "C:/CivicCast/live/gov", label: str = "Web") -> EgressSinkSpec:
    return EgressSinkSpec(kind="hls", label=label, uri=uri)


class _FakeProcess:
    def __init__(self, pid: int = _CHILD_PID) -> None:
        self.pid = pid
        self.terminated = False
        self._returncode: int | None = None

    def poll(self) -> int | None:
        return self._returncode

    def terminate(self, *, grace_seconds: float = 5.0) -> int | None:
        self.terminated = True
        self._returncode = 0
        return 0


class _LoggingStarter:
    """A starter double that behaves like the real one: it writes the child's
    stderr into the handle the supervisor handed it, and remembers whether the
    child was asked to log at all."""

    def __init__(self, *, lines: list[str] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.paths: list[Path | None] = []
        self.procs: list[_FakeProcess] = []
        self._lines = lines if lines is not None else []

    def __call__(self, args: list[str], *, stderr_path: Path | None = None) -> _FakeProcess:
        self.calls.append(args)
        self.paths.append(stderr_path)
        if stderr_path is not None:
            with stderr_path.open("a", encoding="utf-8") as handle:
                for line in self._lines:
                    handle.write(f"{line}\n")
        proc = _FakeProcess(pid=_CHILD_PID + len(self.procs))
        self.procs.append(proc)
        return proc


def _log_path(log_root: Path, channel_id: str = "gov", label: str = "Web") -> Path:
    return log_root / channel_id / "logs" / f"hls-relay.{label}.stderr.log"


def _fields(header: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for token in header.split(" argv=")[0].split(" "):
        key, sep, value = token.partition("=")
        if sep and key in {"pid", "utc", "channel", "sink", "spawn", "reason"}:
            fields[key] = value
    return fields


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def test_spawn_writes_a_header_then_the_childs_stderr_to_the_channel_log(
    tmp_path: Path,
) -> None:
    starter = _LoggingStarter(lines=["Non-monotonous DTS in output stream 0:1"])
    sup = HlsRelaySupervisor(starter=starter, log_root=tmp_path)

    sup.apply(_config(_hls_sink()))

    path = _log_path(tmp_path)
    assert path.exists(), "the relay child's stderr was not captured"
    assert starter.paths == [path]
    body = _lines(path)
    assert body[0].startswith("[hls-relay] pid=")
    assert body[1] == "Non-monotonous DTS in output stream 0:1"


def test_the_header_carries_the_utc_time_channel_sink_pid_reason_and_full_argv(
    tmp_path: Path,
) -> None:
    starter = _LoggingStarter()
    sup = HlsRelaySupervisor(starter=starter, log_root=tmp_path)

    sup.apply(_config(_hls_sink(), channel_id="education"))

    header = _lines(_log_path(tmp_path, "education"))[0]
    fields = _fields(header)
    assert fields["pid"] == f"{_CHILD_PID:010d}"
    assert fields["channel"] == "education"
    assert fields["sink"] == "Web"
    assert fields["spawn"] == "1"
    assert fields["reason"] == "start"
    # UTC, ISO-8601, second-resolution or finer: an operator must be able to
    # line the child's life up against the station's other logs.
    assert fields["utc"].endswith("Z")
    assert "T" in fields["utc"]
    assert len(fields["utc"]) >= len("2026-09-25T00:51:26")
    # The FULL argv, so the next reader can see which input URI/port this child
    # was pointed at without guessing from the sink row.
    assert json.loads(header.split(" argv=", 1)[1]) == starter.calls[0]


def test_a_rebound_child_rotates_the_log_and_appends_a_new_header(tmp_path: Path) -> None:
    first = _LoggingStarter(lines=["first child line"])
    sup = HlsRelaySupervisor(starter=first, log_root=tmp_path)
    sup.apply(_config(_hls_sink()), new_session=True)

    second = _LoggingStarter(lines=["second child line"])
    sup._starter = second  # type: ignore[attr-defined]
    sup.apply(_config(_hls_sink()), new_session=True)

    path = _log_path(tmp_path)
    previous = path.with_name(path.name + ".1")
    assert previous.exists(), "the replaced child's log was not rotated"
    previous_body = _lines(previous)
    assert previous_body[-1] == "first child line"
    assert _fields(previous_body[0])["reason"] == "start"
    assert first.procs[0].terminated

    current = _lines(path)
    assert current[-1] == "second child line"
    assert _fields(current[0])["reason"] == "rebind"
    assert _fields(current[0])["spawn"] == "2"


def test_rotation_keeps_at_most_the_current_and_one_previous_log(tmp_path: Path) -> None:
    sup = HlsRelaySupervisor(starter=_LoggingStarter(), log_root=tmp_path)
    for _ in range(3):
        sup.apply(_config(_hls_sink()), new_session=True)

    path = _log_path(tmp_path)
    assert path.exists()
    assert path.with_name(path.name + ".1").exists()
    assert not path.with_name(path.name + ".2").exists()
    assert sorted(p.name for p in path.parent.iterdir()) == [
        "hls-relay.Web.stderr.log",
        "hls-relay.Web.stderr.log.1",
    ]


def test_a_child_that_exited_is_replaced_with_its_own_header(tmp_path: Path) -> None:
    starter = _LoggingStarter(lines=["child line"])
    sup = HlsRelaySupervisor(starter=starter, log_root=tmp_path)
    sup.apply(_config(_hls_sink()))
    starter.procs[0]._returncode = 1

    sup.apply(_config(_hls_sink()))

    current = _lines(_log_path(tmp_path))
    assert _fields(current[0])["spawn"] == "2"
    assert _fields(current[0])["reason"] == "respawn-dead"


def test_a_hostile_sink_label_cannot_escape_the_channel_log_directory(tmp_path: Path) -> None:
    """The label comes from channel config, so it is hostile until sanitized.

    ``../../Web / Main`` must collapse to a single component inside the
    channel's own ``logs`` directory: the ``..`` segments are stripped along
    with the separators that would have carried them, and the run of
    non-name characters around the inner slash collapses to one ``_``.
    """
    sup = HlsRelaySupervisor(starter=_LoggingStarter(), log_root=tmp_path)

    sup.apply(_config(_hls_sink(label="../../Web / Main")))

    logs = tmp_path / "gov" / "logs"
    assert [p.name for p in logs.iterdir()] == ["hls-relay.Web_Main.stderr.log"]
    assert not (tmp_path / "Web_Main.stderr.log").exists()


def test_the_log_is_trimmed_to_the_cap_keeping_the_header_and_the_newest_lines(
    tmp_path: Path,
) -> None:
    starter = _LoggingStarter(lines=["the first line after the header"])
    sup = HlsRelaySupervisor(starter=starter, log_root=tmp_path)
    sup.apply(_config(_hls_sink()))
    path = _log_path(tmp_path)

    # The child storms: this is the very case the cap exists for (a warning
    # storm is exactly when the child-side evidence matters most).
    noise = "x" * 200 + "\n"
    with path.open("a", encoding="utf-8") as handle:
        for _ in range((2 * HLS_RELAY_LOG_CAP_BYTES) // len(noise)):
            handle.write(noise)
        handle.write("THE NEWEST CHILD LINE\n")
    assert path.stat().st_size > HLS_RELAY_LOG_CAP_BYTES

    trimmed = sup.maybe_trim_logs("gov")

    assert trimmed == 1
    assert path.stat().st_size <= HLS_RELAY_LOG_CAP_BYTES
    body = _lines(path)
    assert body[0].startswith("[hls-relay] pid="), "the header must survive the trim"
    assert body[-1] == "THE NEWEST CHILD LINE"
    # The trim is an in-place rewrite, never a child restart: the relay that
    # was serving residents is still the relay serving them.
    assert len(starter.calls) == 1
    assert not starter.procs[0].terminated
    # And it is not a full-file wipe: the retained tail is what the cap allows.
    assert path.stat().st_size >= HLS_RELAY_LOG_TAIL_BYTES // 2


def test_trim_is_a_no_op_below_the_cap(tmp_path: Path) -> None:
    sup = HlsRelaySupervisor(starter=_LoggingStarter(lines=["quiet"]), log_root=tmp_path)
    sup.apply(_config(_hls_sink()))
    path = _log_path(tmp_path)
    before = path.read_bytes()

    assert sup.maybe_trim_logs("gov") == 0
    assert sup.maybe_trim_logs("no-such-channel") == 0

    assert path.read_bytes() == before


def test_without_a_log_root_no_file_is_written_and_the_starter_keeps_one_argument(
    tmp_path: Path,
) -> None:
    seen: list[Path | None] = []

    class _Starter:
        def __call__(self, args: list[str], *, stderr_path: Path | None = None) -> _FakeProcess:
            seen.append(stderr_path)
            return _FakeProcess()

    sup = HlsRelaySupervisor(starter=_Starter())
    sup.apply(_config(_hls_sink()))

    assert seen == [None]
    assert list(tmp_path.iterdir()) == []


def test_two_channels_get_separate_log_files(tmp_path: Path) -> None:
    sup = HlsRelaySupervisor(starter=_LoggingStarter(), log_root=tmp_path)

    sup.apply(_config(_hls_sink(), channel_id="gov"))
    sup.apply(_config(_hls_sink(uri="C:/CivicCast/live/education"), channel_id="education"))

    assert _log_path(tmp_path, "gov").exists()
    assert _log_path(tmp_path, "education").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows sharing semantics")
def test_rotation_needs_the_predecessors_handles_closed_so_it_runs_after_terminate(
    tmp_path: Path,
) -> None:
    """The ordering in the spawn path is load-bearing, not stylistic.

    On Windows a file another process holds open cannot be renamed
    (WinError 32 — the child holds its stderr handle for its whole life), so
    rotation is only possible once the predecessor has been terminated and its
    handles closed. This proves both halves: the rename genuinely fails while a
    handle is open, and the supervisor's rotation sequence (terminate, then
    rotate, then spawn) works against a child that really holds the file.
    """
    path = tmp_path / "held.log"
    held = path.open("a", encoding="utf-8")
    with pytest.raises(PermissionError):
        path.rename(tmp_path / "held.log.1")
    held.close()
    path.rename(tmp_path / "held.log.1")
    assert (tmp_path / "held.log.1").exists()

    class _HoldingStarter(_LoggingStarter):
        """A starter whose child really holds its stderr file, like ffmpeg does."""

        def __init__(self, **kwargs: object) -> None:
            super().__init__(**kwargs)  # type: ignore[arg-type]
            self.handles: list[IO[str]] = []

        def __call__(self, args: list[str], *, stderr_path: Path | None = None) -> _FakeProcess:
            proc = super().__call__(args, stderr_path=stderr_path)
            assert stderr_path is not None
            handle = stderr_path.open("a", encoding="utf-8")
            self.handles.append(handle)
            original = proc.terminate

            def terminate(*, grace_seconds: float = 5.0) -> int | None:
                if not handle.closed:
                    handle.close()
                return original(grace_seconds=grace_seconds)

            proc.terminate = terminate  # type: ignore[method-assign]
            return proc

    starter = _HoldingStarter(lines=["child line"])
    try:
        sup = HlsRelaySupervisor(starter=starter, log_root=tmp_path)
        sup.apply(_config(_hls_sink()))
        sup.apply(_config(_hls_sink()), new_session=True)

        live = _log_path(tmp_path)
        assert live.with_name(live.name + ".1").exists()
        assert "child line" in live.read_text(encoding="utf-8")
    finally:
        # The last child is still "alive" when the assertions finish: release its
        # handle here rather than leaving it to be collected mid-teardown.
        for handle in starter.handles:
            handle.close()


@requires_ffmpeg
def test_a_real_child_appends_its_own_stderr_to_the_file_the_starter_was_given(
    tmp_path: Path,
) -> None:
    """Real ffmpeg, the real starter, and a file that already has our header.

    The doubles above prove the supervisor's bookkeeping; only a real child can
    prove that the production starter (``_default_starter`` ->
    ``start_ffmpeg(stderr_path=…)``) actually routes ffmpeg's own stderr into the
    per-channel file and leaves it appendable. Three things are asserted: the
    pre-written header survives as line 1 (append mode, not truncate), ffmpeg's
    own bytes follow it, and the child exits on its own with no writer draining
    anything.

    What this deliberately does NOT claim: it is not a backpressure proof. The
    measured volume of ffmpeg's own output -- 24,233 B at ``-loglevel debug``
    for the noisiest shape tried, and ~1.4 KiB per ``timestamp discontinuity``
    event (``civiccast-ds-oversight/staging/U24/evidence/loglevel/summary.json``)
    -- sits under a
    Windows anonymous pipe's ~64 KiB buffer, so volume alone cannot distinguish
    "file" from "drained pipe" in this test. The no-pipe property is a property
    of the code path instead: ``start_ffmpeg`` opens ``stderr_path`` in append
    mode and passes that handle to ``Popen``, never ``subprocess.PIPE``.
    """
    log_path = tmp_path / "gov" / "logs" / "hls-relay.Web.stderr.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    argv = [
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "debug",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=320x240:rate=50",
        "-t",
        "5",
        "-f",
        "null",
        "-",
    ]
    # The supervisor writes the header before the spawn; mirror that here so the
    # file the child appends to is the file the field would see.
    header = (
        b"[hls-relay] pid=---------- utc=2026-09-25T00:00:00.000000Z channel=gov "
        b"sink=Web spawn=1 reason=start argv=[]\n"
    )
    log_path.write_bytes(header)

    handle = _default_starter(argv, stderr_path=log_path)
    try:
        deadline = time.monotonic() + 30.0
        while handle.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert handle.poll() == 0, "the real child did not finish on its own"
        assert handle.pid > 0
    finally:
        # Never leave an ffmpeg behind, even if an assertion above fired.
        handle.terminate()

    text = log_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    assert lines[0].startswith("[hls-relay] pid="), "the header must be the first line"
    assert sum(1 for line in lines if line.startswith("[hls-relay] ")) == 1
    # ffmpeg's OWN output follows the header: these are the lines U21's two
    # incidents would have had if the child's stderr had not gone to DEVNULL.
    assert len(text) > 4096, "only the header was captured -- ffmpeg's stderr did not land"
    assert "ffmpeg version" not in text  # -hide_banner: no version banner
    assert "testsrc2" in text, "no ffmpeg chatter about the input was captured"
