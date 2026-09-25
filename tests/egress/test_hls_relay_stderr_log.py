# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""BETA.10 U24 (.1) — each HLS relay child's stderr is captured, per channel, bounded.

Two live incidents had no evidence because the relay child's stderr went to
``subprocess.DEVNULL`` (``start_ffmpeg`` was called with no ``stderr_path``):

* 2026-09-25 00:51:26 (education) — on slate entry the channel's output jumped
  +19.75 s A/V inside the relay; U21 could not decide where the jump is born
  because the child's own ``timestamp discontinuity``/``Non-monotonous DTS``
  lines were discarded.
* 2026-09-25 01:04 — a freshly restarted relay child wrote nothing for ~2
  minutes while the engine was producing; U21 recorded INFERRED ("its input was
  not delivering") with no child-side evidence.

U24.1 corrects the shape U24 first shipped. That cut had the *child* write the
log file (``start_ffmpeg(stderr_path=…)``) and the *parent* trim it in place by
rewriting ``header + newest tail``. That cannot bound anything on Windows, and
its docstring's claim — "measured on Windows: append-mode ffmpeg writes after a
rewrite continue from the new size" — was false. An inherited OS handle keeps
its own position, and the CRT's ``O_APPEND`` emulation lives in the writing
process, which is the *child*, not the process doing the rewrite. The
coordinator's repro against the real starter measured it::

    before 5663 after_trim 2007 1s later 5809 final 5882 NULs 3656 first_nul_at 2007

so the child's next write landed at its old offset, the gap between the rewrite
and that offset was zero-filled, and the file grew back past the cap it had just
been trimmed to. The cap bounded nothing, the trim fired every tick (a WARNING
storm of its own), and the retained tail was mostly padding.

**The test that supported that claim, and why it passed.**
``test_the_log_is_trimmed_to_the_cap_keeping_the_header_and_the_newest_lines``
(and the "fake writer" shape before it) appended to the log from *this* process
and then called ``maybe_trim_logs``, also in this process: one open Python
handle doing both writes, where the CRT's append emulation does continue from
the new size. It measured a Python file object, never the inherited OS handle a
real child writes through, so it passed on machinery no relay child has. Sizing
its write from the imported ``HLS_RELAY_LOG_CAP_BYTES`` made it worse still — a
mutant of that constant would have resized the test alongside the code, so the
test could not have detected the mutation it appeared to guard. Its replacement
never imports the cap: every cap, tail and volume below is a local literal, and
the cap test drives a **real ffmpeg child through the real starter**.

The contract now, in the two layers this module tests it at.

*Unit layer* — the fake starter hands the supervisor an in-memory stream as the
child's stderr pipe, so these tests exercise the real drain path
(``_RelayLogWriter``) rather than simulating its output:

* one file per (channel, sink): ``<log_root>/<channel>/logs/hls-relay.<sink>.stderr.log``;
* one header line per spawn (UTC, channel, sink, pid, spawn ordinal, reason,
  full argv) — the argument/session evidence survives every rotation;
* the child's stderr is a ``subprocess.PIPE`` and a drain thread owns the file —
  the only handle on it anywhere in the system, which is exactly what makes a
  rewrite (or a rename) safe in the parent's hands and unsafe in a child's
  (``WinError 32``);
* the writer enforces the cap in-thread (spawn header + newest tail) and never
  lets the log stall or kill the relay: a log it cannot open or write is warned
  once per episode and the bytes are discarded, while the read continues;
* current + one previous, rotated at spawn only, once the predecessor's handle
  is provably closed;
* no log root configured -> no file, and the starter keeps its one-argument call
  shape (the pre-U24 contract every other relay test double relies on).

*Real-child layer* — ``_RealArgvStarter`` substitutes only the argv (the
production argv reads a live ``udp://`` input that never reaches EOF) and runs
the production ``_default_starter`` -> ``start_ffmpeg``, the production
supervisor and the production drain thread:

* a real child's stderr lands in the log, header first, its own pid stamped in;
* a storm — a corrupt MPEG-TS replayed at ``-loglevel debug``, which is what a
  real DTS/discontinuity storm looks like — is capped with **no NUL padding**,
  leaves exactly one header, and never restarts the child;
* the drain does not stall the child: the same storm finishes within +10 % of
  the same run with stderr to ``DEVNULL`` (min of three on each side, because
  per-run spread on a shared Windows box was measured at ±20 %);
* the drain thread ends by itself at EOF (the child exiting) and does not slow
  ``terminate``.
"""

from __future__ import annotations

import io
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import IO, TYPE_CHECKING, NamedTuple, cast

import pytest

from civiccast.egress import hls_relay as hls_relay_module
from civiccast.egress.hls_relay import HlsRelaySupervisor, _default_starter
from civiccast.egress.models import EgressConfig, EgressSinkSpec
from civiccast.stream._ffmpeg import FfmpegProcessHandle

if TYPE_CHECKING:  # pragma: no cover - typing only, and absent before U24.1
    from civiccast.egress.hls_relay import _RelayLogWriter

_CHILD_PID = 4242
_KEY = "gov|Web"

#: ffmpeg's own presence, not GStreamer's: this capture is ffmpeg-side only.
_FFMPEG = shutil.which("ffmpeg")
requires_ffmpeg = pytest.mark.skipif(
    _FFMPEG is None,
    reason="ffmpeg is not on PATH -- the real-child stderr capture is UNPROVEN here; "
    "the fake-starter capture contract is not a substitute for it",
)

# --- test-local literals, never the module constants -------------------------------
#
# U24.1: a test whose write size comes from the constant under test is not a
# test of that constant -- a mutant moves both sides together. So the caps and
# tails asserted below are stated here as literals and the module constants are
# never imported. They are shrunk (48 KiB instead of the production cap) so the
# fixture's storm crosses them in a second or two rather than a minute, and so
# the retained tail is small enough to inspect by eye.

_CAP_BYTES = 48 * 1024
_TAIL_BYTES = 16 * 1024

#: The storm used by the real-child tests: one "quiet" 4 s testsrc2 clip that
#: mpeg2video encodes to a valid MPEG-TS, then every other 2 KiB block zeroed.
#: ffmpeg's demuxer then reports a discontinuity per damaged block at
#: ``-loglevel debug`` — measured ~16.7 KB of stderr per 4 s loop, ~1.7 MB for
#: the 100 loops below and ~3.3 MB for the 200. (A *clean* lavfi input at the
#: same loglevel yields only ~18 KB in total, which is why the brief's "60 s of
#: a verbose lavfi input" could not reach 1 MiB; a real station's storm comes
#: from damaged input, so the fixture reproduces that instead of faking volume.)
_STORM_LOOPS_CAP = 100
_STORM_LOOPS_TIMING = 200

#: 2 MiB cap for the timing runs, so the storm crosses it once and the writer
#: demonstrably spends the run trimming (the cap test's 48 KiB would trim ~700
#: times and make the timing about the trim, not about the drain).
_STORM_CAP_BYTES = 2 * 1024 * 1024
_STORM_TAIL_BYTES = 512 * 1024
#: After the single trim the file is the retained tail plus the child's
#: remaining ~1.3 MB; requiring more than a megabyte here is what makes this
#: run a backpressure proof rather than a test of a quiet child.
_STORM_MIN_LOG_BYTES = 1024 * 1024
#: A file can sit one read chunk over the cap between the append and the trim
#: check in the same call (see ``_RelayLogWriter._append``).
_MID_APPEND_ALLOWANCE = 128 * 1024

_TIMING_SAMPLES = 3
_TIMING_BOUND = 1.10

#: A quiet real child for the lifecycle tests: it exits on its own in ~3 s.
_QUIET_ARGV = [
    "-hide_banner",
    "-nostdin",
    "-loglevel",
    "debug",
    "-f",
    "lavfi",
    "-i",
    "testsrc2=size=320x240:rate=50",
    "-t",
    "3",
    "-f",
    "null",
    "-",
]


def _config(*sinks: EgressSinkSpec, channel_id: str = "gov") -> EgressConfig:
    return EgressConfig(
        channel_id=channel_id, enabled=True, slate_message="slate", sinks=list(sinks)
    )


def _hls_sink(uri: str = "C:/CivicCast/live/gov", label: str = "Web") -> EgressSinkSpec:
    return EgressSinkSpec(kind="hls", label=label, uri=uri)


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


def _writer(sup: HlsRelaySupervisor, key: str = _KEY) -> _RelayLogWriter | None:
    """This relay's drain writer, or ``None`` when nothing owns its log.

    Read through ``getattr`` on purpose. This is also the assertion that the
    *parent* owns the file: on the pre-U24.1 shape there is no writer at all,
    because the child held the file, which is precisely what made the cap
    unenforceable no matter what the parent did to it afterwards.
    """
    return cast("_RelayLogWriter | None", getattr(sup._relays[key], "log_writer", None))


def _settle(sup: HlsRelaySupervisor, key: str = _KEY) -> None:
    """Wait for a relay's drain thread to reach EOF of a finite fake stream."""
    writer = _writer(sup, key)
    assert writer is not None, "no drain thread was started for this relay"
    assert writer.join(10.0), "the drain thread did not reach EOF"


def _alive_drain_threads() -> list[str]:
    return [t.name for t in threading.enumerate() if t.name.startswith("hls-relay-log:")]


def _wait_for_drain_threads_to_end(timeout: float) -> list[str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        alive = _alive_drain_threads()
        if not alive:
            return []
        time.sleep(0.01)
    return _alive_drain_threads()


def _wait_for_exit(handle: FfmpegProcessHandle, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if handle.poll() is not None:
            return True
        time.sleep(0.005)
    return handle.poll() is not None


def _wait_for_log_growth(path: Path, timeout: float) -> bool:
    """Wait until the drain thread has put the child's first stderr bytes on disk."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if path.stat().st_size > 0:
                return True
        except OSError:
            pass
        time.sleep(0.01)
    return False


def _wait_until_the_cap_is_crossed(
    sup: HlsRelaySupervisor, path: Path, cap_bytes: int, timeout: float
) -> str:
    """Wait until the log is over its cap on whichever shape is under test.

    The regression test below has to run the daemon's ``maybe_trim_logs`` tick
    *after* the cap has been crossed, or it proves nothing about the trim -- it
    only proves the tick ran early. Crossing has two shapes and this waits for
    either:

    * parent-owns-the-file: the drain thread trims in-thread, so the file never
      sits over the cap for long; the writer's own trim count is the signal;
    * the pre-U24.1 shape: no thread owns the file and nothing trims it between
      ticks, so the file's raw size is the signal.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        writer = _writer(sup)
        if writer is not None and writer.trims >= 1:
            return "writer"
        try:
            if path.stat().st_size > cap_bytes:
                return "file"
        except OSError:
            pass
        time.sleep(0.01)
    return ""


def _time_call(call: Callable[..., object], *args: object) -> float:
    started = time.perf_counter()
    call(*args)
    return time.perf_counter() - started


class _FakeProcess:
    """A relay child double: it carries the read end of its own stderr pipe."""

    def __init__(self, pid: int = _CHILD_PID, stderr_pipe: IO[str] | None = None) -> None:
        self.pid = pid
        self.stderr_pipe = stderr_pipe
        self.terminated = False
        self._returncode: int | None = None

    def poll(self) -> int | None:
        return self._returncode

    def terminate(self, *, grace_seconds: float = 5.0) -> int | None:
        self.terminated = True
        self._returncode = 0
        return 0


class _LoggingStarter:
    """A starter double whose child really produces stderr bytes.

    U24.1: the child does not write the log — it hands the supervisor the read
    end of a pipe and the supervisor's drain thread owns the file. This double
    does the same with a finite in-memory stream, so the tests below run the
    real drain path rather than a simulation of its output. The double it
    replaces wrote the file itself from the test process, which is exactly what
    let the first cut's cap test pass while a real child NUL-padded its log.
    """

    def __init__(self, *, lines: list[str] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.paths: list[Path | None] = []
        self.procs: list[_FakeProcess] = []
        self.streams: list[io.StringIO] = []
        self._lines = lines if lines is not None else []

    def __call__(self, args: list[str], *, stderr_path: Path | None = None) -> _FakeProcess:
        self.calls.append(args)
        self.paths.append(stderr_path)
        stream = io.StringIO("".join(f"{line}\n" for line in self._lines))
        self.streams.append(stream)
        proc = _FakeProcess(pid=_CHILD_PID + len(self.procs), stderr_pipe=stream)
        self.procs.append(proc)
        return proc


class _CountingStream(io.StringIO):
    """A stderr pipe double that remembers how many reads it served."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.lines_read = 0

    # typeshed types ``_IOBase.readline`` as bytes-returning, so any str-returning
    # override of it reads as a Liskov violation even though ``StringIO`` is the
    # text-mode base every caller here uses.
    def readline(self, size: int | None = -1, /) -> str:  # type: ignore[override]
        line = super().readline()
        if line:
            self.lines_read += 1
        return line


class _RealArgvStarter:
    """The production starter with a substituted argv — nothing else.

    The relay's own argv reads a live ``udp://`` input that never reaches EOF,
    so a storm cannot be driven through it. Everything else here is production
    code: ``_default_starter`` -> ``start_ffmpeg`` -> a real ``Popen`` with a
    real stderr ``PIPE``, the real supervisor, the real drain thread, the real
    log file.
    """

    def __init__(self, argv: list[str]) -> None:
        self.argv = list(argv)
        self.handles: list[FfmpegProcessHandle] = []

    def __call__(self, args: list[str], *, stderr_path: Path | None = None) -> FfmpegProcessHandle:
        handle = _default_starter(self.argv, stderr_path=stderr_path)
        self.handles.append(handle)
        return handle


def _build_storm_media(directory: Path) -> Path:
    """Encode a 4 s clip to MPEG-TS, then zero every other 2 KiB block."""
    assert _FFMPEG is not None
    seed = directory / "storm-seed.ts"
    subprocess.run(
        [
            _FFMPEG,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x240:rate=25:d=4",
            "-c:v",
            "mpeg2video",
            "-f",
            "mpegts",
            str(seed),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    raw = bytearray(seed.read_bytes())
    for offset in range(0, len(raw), 4096):
        if (offset // 4096) % 2 == 0:
            raw[offset : offset + 2048] = b"\x00" * 2048
    storm = directory / "storm.ts"
    storm.write_bytes(bytes(raw))
    return storm


def _storm_argv(media: Path, loops: int) -> list[str]:
    return [
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "debug",
        "-stream_loop",
        str(loops),
        "-i",
        str(media),
        "-f",
        "null",
        "-",
    ]


@pytest.fixture(scope="module")
def storm_media(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The damaged-transport-stream fixture, built once for the real-child tests."""
    if _FFMPEG is None:
        pytest.skip("ffmpeg is not on PATH")
    return _build_storm_media(tmp_path_factory.mktemp("u24-storm"))


class _SupervisedRun(NamedTuple):
    seconds: float
    raw: bytes
    trims: int
    returncode: int | None


def _supervised_storm(directory: Path, argv: list[str]) -> _SupervisedRun:
    """Run one storm through the real supervisor; return its wall time and log."""
    starter = _RealArgvStarter(argv)
    sup = HlsRelaySupervisor(starter=starter, log_root=directory)
    started = time.perf_counter()
    try:
        sup.apply(_config(_hls_sink()))
        handle = starter.handles[0]
        assert _wait_for_exit(handle, 300.0), "the storm child never exited"
        seconds = time.perf_counter() - started
        writer = _writer(sup)
        assert writer is not None, "no drain thread owns the log"
        assert writer.join(60.0), "the drain thread did not reach EOF"
        run = _SupervisedRun(
            seconds=seconds,
            raw=_log_path(directory).read_bytes(),
            trims=writer.trims,
            returncode=handle.poll(),
        )
    finally:
        sup.stop_all()
    return run


def _baseline_storm(argv: list[str]) -> float:
    """The same storm with stderr to ``DEVNULL``: the child's own wall time."""
    started = time.perf_counter()
    handle = _default_starter(argv)
    try:
        assert _wait_for_exit(handle, 300.0), "the baseline child never exited"
        assert handle.poll() == 0, "the baseline child did not finish cleanly"
        return time.perf_counter() - started
    finally:
        handle.terminate()


# --- unit layer: the supervisor's bookkeeping and the drain thread -----------------


def test_spawn_writes_a_header_then_the_childs_stderr_through_the_drain_thread(
    tmp_path: Path,
) -> None:
    starter = _LoggingStarter(lines=["Non-monotonous DTS in output stream 0:1"])
    sup = HlsRelaySupervisor(starter=starter, log_root=tmp_path)

    sup.apply(_config(_hls_sink()))

    path = _log_path(tmp_path)
    assert path.exists(), "the spawn left no header on disk"
    assert starter.paths == [path], "the child was not handed a log path"
    _settle(sup)
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
    _settle(sup)

    second = _LoggingStarter(lines=["second child line"])
    sup._starter = second
    sup.apply(_config(_hls_sink()), new_session=True)
    _settle(sup)

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


def test_the_writer_trims_its_own_file_to_the_cap_keeping_the_header_and_newest_lines(
    tmp_path: Path,
) -> None:
    """The cap, at the layer that now enforces it: the drain thread's own writer.

    Imported here rather than at module scope so this file also *runs* against
    the pre-U24.1 commit (where the class does not exist), which is what makes
    the real-child cap test below a usable RED for that shape.
    """
    from civiccast.egress.hls_relay import _RelayLogWriter

    cap = _CAP_BYTES
    tail = _TAIL_BYTES
    path = tmp_path / "gov" / "logs" / "hls-relay.Web.stderr.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        b"[hls-relay] pid=0000004242 utc=2026-09-25T00:00:00.000000Z channel=gov "
        b"sink=Web spawn=1 reason=start argv=[]\n"
    )
    path.write_bytes(header)
    # Sized from the LOCAL literals above, never from the module's own cap: a
    # mutant of that constant must not be able to resize this write with it.
    lines = [f"{index:06d} " + "x" * 190 for index in range((3 * cap) // 200 + 1)]

    writer = _RelayLogWriter(path, cap_bytes=cap, tail_bytes=tail)
    try:
        writer.start(io.StringIO("\n".join(lines) + "\n"))
        assert writer.join(30.0), "the writer did not drain an in-memory stream"
    finally:
        writer.close()

    raw = path.read_bytes()
    assert writer.trims >= 1, "the write never crossed the cap"
    assert b"\x00" not in raw
    assert len(raw) <= cap
    body = raw.decode("utf-8").splitlines()
    assert body[0] == header.decode().rstrip("\n"), "the header must survive every trim"
    assert body[-1] == lines[-1], "the newest line must survive every trim"
    assert len(body) > 1


def test_the_writer_discards_and_keeps_draining_when_its_log_cannot_be_opened(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A log must never stall the relay: read on, discard, warn once."""
    from civiccast.egress.hls_relay import _RelayLogWriter

    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    path = blocker / "logs" / "hls-relay.Web.stderr.log"
    stream = _CountingStream("first\nsecond\nthird\n")

    writer = _RelayLogWriter(path, cap_bytes=_CAP_BYTES, tail_bytes=_TAIL_BYTES)
    with caplog.at_level(logging.WARNING, logger="civiccast.egress.hls_relay"):
        try:
            writer.start(stream)
            assert writer.join(30.0), "the writer stopped draining when its log failed"
        finally:
            writer.close()

    assert stream.lines_read == 3, "the writer stopped reading the child's stderr"
    assert not path.exists()
    warnings = [r for r in caplog.records if "could not be opened" in r.getMessage()]
    assert len(warnings) == 1, "one warning per episode, not one per line"


def test_trim_is_a_no_op_below_the_cap(tmp_path: Path) -> None:
    sup = HlsRelaySupervisor(starter=_LoggingStarter(lines=["quiet"]), log_root=tmp_path)
    sup.apply(_config(_hls_sink()))
    _settle(sup)
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
    assert _writer(sup) is None
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
    """The spawn path's ordering is load-bearing, not stylistic.

    On Windows a file another handle holds open cannot be renamed (WinError 32),
    so a rotation only works once the holder has let go. U24.1 moved the holder
    from the child to the drain thread, and the spawn path still terminates
    first and rotates second — so the rename below is the one the supervisor
    performs, and it succeeds because the predecessor's writer was released by
    ``_terminate_relay`` before ``_rotate_relay_log`` ran.
    """
    path = tmp_path / "held.log"
    held = path.open("a", encoding="utf-8")
    with pytest.raises(PermissionError):
        path.rename(tmp_path / "held.log.1")
    held.close()
    path.rename(tmp_path / "held.log.1")
    assert (tmp_path / "held.log.1").exists()

    starter = _LoggingStarter(lines=["first child line"])
    sup = HlsRelaySupervisor(starter=starter, log_root=tmp_path)
    sup.apply(_config(_hls_sink()))
    _settle(sup)
    first = sup._relays[_KEY]

    sup.apply(_config(_hls_sink()), new_session=True)

    assert first.log_writer is None, "the predecessor's file was still held at rotation time"
    live = _log_path(tmp_path)
    assert live.with_name(live.name + ".1").exists()
    assert "first child line" in live.with_name(live.name + ".1").read_text(encoding="utf-8")


# --- real-child layer: the same contract against ffmpeg itself ---------------------


@requires_ffmpeg
def test_a_real_childs_stderr_reaches_the_log_through_the_drain_thread(tmp_path: Path) -> None:
    """Real ffmpeg, the real starter, the real drain thread, the real file.

    The doubles above prove the supervisor's bookkeeping; only a real child can
    prove that ``_default_starter`` -> ``start_ffmpeg(stderr_pipe=True)`` routes
    ffmpeg's own stderr through the pipe into the per-channel file, that the
    header stays line 1, and that the pid stamped into that header is this
    child's.
    """
    starter = _RealArgvStarter(_QUIET_ARGV)
    sup = HlsRelaySupervisor(starter=starter, log_root=tmp_path)
    try:
        sup.apply(_config(_hls_sink()))
        handle = starter.handles[0]
        assert _wait_for_exit(handle, 60.0), "the real child did not finish on its own"
        assert handle.poll() == 0
        writer = _writer(sup)
        assert writer is not None, "the real starter returned no stderr pipe"
        assert writer.join(30.0), "the drain thread did not reach EOF after the child exited"
        raw = _log_path(tmp_path).read_bytes()
    finally:
        sup.stop_all()

    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    assert lines[0].startswith("[hls-relay] pid="), "the header must be the first line"
    assert _fields(lines[0])["pid"] == f"{handle.pid:010d}", "the header is not this child's"
    assert sum(1 for line in lines if line.startswith("[hls-relay] ")) == 1
    # ffmpeg's OWN output follows the header: these are the lines U21's two
    # incidents would have had if the child's stderr had gone to DEVNULL.
    assert len(raw) > 4096, "only the header was captured -- ffmpeg's stderr did not land"
    assert "ffmpeg version" not in text  # -hide_banner: no version banner
    assert "testsrc2" in text, "no ffmpeg chatter about the input was captured"
    assert b"\x00" not in raw


@requires_ffmpeg
def test_a_real_childs_storm_is_capped_with_no_nul_padding_and_no_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, storm_media: Path
) -> None:
    """The cap, against a real child writing past it — the U24.1 regression test.

    On the pre-U24.1 shape this is the test that fails: the parent's in-place
    trim while the child kept appending left a zero-filled hole and a file
    larger than the cap it had just been trimmed to. It runs the daemon's
    ``maybe_trim_logs`` tick mid-storm *and* waits for the child to finish, so
    both the belt and the writer's braces are exercised.

    The tick is run only once the cap has actually been crossed
    (:func:`_wait_until_the_cap_is_crossed`), so the failure it reports on the
    old shape is the trim's doing and not a tick that happened to run before
    the file was over the cap.
    """
    monkeypatch.setattr(hls_relay_module, "HLS_RELAY_LOG_CAP_BYTES", _CAP_BYTES)
    monkeypatch.setattr(hls_relay_module, "HLS_RELAY_LOG_TAIL_BYTES", _TAIL_BYTES)
    starter = _RealArgvStarter(_storm_argv(storm_media, _STORM_LOOPS_CAP))
    sup = HlsRelaySupervisor(starter=starter, log_root=tmp_path)
    try:
        sup.apply(_config(_hls_sink()))
        handle = starter.handles[0]
        path = _log_path(tmp_path)
        assert _wait_for_log_growth(path, 30.0), "the storm child wrote no stderr"
        crossed = _wait_until_the_cap_is_crossed(sup, path, _CAP_BYTES, 30.0)
        assert crossed, "the storm never crossed the cap: this test's premise was not met"

        sup.maybe_trim_logs("gov")
        time.sleep(1.0)
        mid_flight = path.read_bytes()
        nul = mid_flight.count(b"\x00")
        assert nul == 0, (
            f"the log grew a NUL hole while the child was still writing: {nul} NUL bytes "
            f"in {len(mid_flight)}; something rewrote the file under a child that kept "
            "appending at its own offset"
        )
        assert len(mid_flight) <= _CAP_BYTES + _MID_APPEND_ALLOWANCE, (
            f"the log is {len(mid_flight)} bytes against a {_CAP_BYTES}-byte cap while the "
            "child is still writing: the cap bounds nothing"
        )

        assert _wait_for_exit(handle, 300.0), "the storm child never exited"
        assert handle.poll() == 0
        writer = _writer(sup)
        assert writer is not None, "no drain thread owns the log"
        assert writer.join(60.0), "the drain thread did not reach EOF"
        raw = path.read_bytes()
    finally:
        sup.stop_all()

    assert len(starter.handles) == 1, "something restarted the relay child"
    assert writer.trims >= 1, "the storm never crossed the cap: this test's premise was not met"
    assert b"\x00" not in raw, "the log is NUL-padded: something wrote past a rewrite"
    assert len(raw) <= _CAP_BYTES + _MID_APPEND_ALLOWANCE
    lines = raw.decode("utf-8", errors="replace").splitlines()
    assert lines[0].startswith("[hls-relay] pid=")
    assert sum(1 for line in lines if line.startswith("[hls-relay] ")) == 1
    assert _fields(lines[0])["pid"] == f"{handle.pid:010d}"


@requires_ffmpeg
def test_a_logging_storm_does_not_stall_the_child_and_stays_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, storm_media: Path
) -> None:
    """The pipe must never become backpressure for the relay child.

    The same storm, once with stderr to ``DEVNULL`` and once drained into the
    log, three times each, compared on the minimum of each side. The minimum is
    the right statistic because a shared Windows box only ever *adds* time; the
    measured per-run spread of these two shapes was ±20 %, hence the min-of-three
    and the +10 % bound (measured min/min: 1.024 and 0.870). One retry is
    allowed for a host-load spike; the deterministic companions below fail on
    their own if the pipe really is stalling the child.
    """
    monkeypatch.setattr(hls_relay_module, "HLS_RELAY_LOG_CAP_BYTES", _STORM_CAP_BYTES)
    monkeypatch.setattr(hls_relay_module, "HLS_RELAY_LOG_TAIL_BYTES", _STORM_TAIL_BYTES)
    argv = _storm_argv(storm_media, _STORM_LOOPS_TIMING)
    baseline: list[float] = []
    runs: list[_SupervisedRun] = []

    for attempt in (1, 2):
        baseline = [_baseline_storm(argv) for _ in range(_TIMING_SAMPLES)]
        runs = [
            _supervised_storm(tmp_path / f"attempt{attempt}-run{index}", argv)
            for index in range(_TIMING_SAMPLES)
        ]
        for run in runs:
            assert run.returncode == 0, "the supervised storm child did not finish cleanly"
            assert run.trims >= 1, "the storm never crossed the cap: not a backpressure proof"
            assert b"\x00" not in run.raw, "the log is NUL-padded"
            assert len(run.raw) <= _STORM_CAP_BYTES + _MID_APPEND_ALLOWANCE
            assert len(run.raw) > _STORM_MIN_LOG_BYTES, (
                f"the child logged only {len(run.raw)} bytes: this run is not a backpressure proof"
            )
        best_baseline = min(baseline)
        best_supervised = min(run.seconds for run in runs)
        if best_supervised <= best_baseline * _TIMING_BOUND:
            return

    pytest.fail(
        f"the drain stalled the child: best supervised {best_supervised:.2f}s vs best DEVNULL "
        f"{best_baseline:.2f}s (bound {_TIMING_BOUND:.2f}x); DEVNULL samples {[round(s, 2) for s in baseline]}, "
        f"supervised samples {[round(run.seconds, 2) for run in runs]}"
    )


@requires_ffmpeg
def test_the_drain_thread_ends_by_itself_when_the_child_exits(tmp_path: Path) -> None:
    """No ``close`` needed: EOF of the pipe is the thread's own exit condition.

    It must also keep nothing alive — a thread that outlived its child would
    pin the channel's state for the life of the daemon.
    """
    starter = _RealArgvStarter(_QUIET_ARGV)
    sup = HlsRelaySupervisor(starter=starter, log_root=tmp_path)
    try:
        sup.apply(_config(_hls_sink()))
        handle = starter.handles[0]
        assert _wait_for_exit(handle, 60.0), "the real child did not finish on its own"
        alive = _wait_for_drain_threads_to_end(5.0)
        assert alive == [], f"the drain thread outlived its child: {alive}"
    finally:
        sup.stop_all()


@requires_ffmpeg
def test_terminating_a_relay_is_not_slowed_by_its_drain_thread(
    tmp_path: Path, storm_media: Path
) -> None:
    """Teardown of a *storming* relay costs what teardown of a plain child costs.

    Timed against a second child running the identical storm with stderr to
    ``DEVNULL`` and no writer at all, so the comparison is against the same work
    in the same state. Measured on this host: 0.0032-0.0048 s for
    ``stop_all`` vs 0.0031-0.0048 s for a bare ``terminate``.
    """
    argv = _storm_argv(storm_media, 100_000)
    starter = _RealArgvStarter(argv)
    sup = HlsRelaySupervisor(starter=starter, log_root=tmp_path)
    plain: FfmpegProcessHandle | None = None
    try:
        sup.apply(_config(_hls_sink()))
        handle = starter.handles[0]
        assert _wait_for_log_growth(_log_path(tmp_path), 15.0), "the storm child wrote no stderr"

        plain = _default_starter(argv)
        assert plain.poll() is None, "the plain child exited before it could be timed"
        t_plain = _time_call(plain.terminate)
        t_threaded = _time_call(sup.stop_all)
    finally:
        if plain is not None:
            plain.terminate()
        sup.stop_all()

    assert handle.poll() is not None, "the supervised child is still running"
    assert t_threaded < 2.0, f"stop_all waited on the drain thread ({t_threaded:.4f}s)"
    assert t_threaded <= t_plain + 0.5, (
        f"the drain thread slowed terminate: {t_threaded:.4f}s vs {t_plain:.4f}s"
    )
    assert _wait_for_drain_threads_to_end(5.0) == [], "a drain thread outlived its relay"
