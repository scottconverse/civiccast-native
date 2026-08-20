# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Live GStreamer playout-engine tests — they import gi via a real worker subprocess,
so they only run where a real GStreamer + gi is actually available. That is Linux/WSL
(gi from the system package manager), OR native Windows with the bundled native
GStreamer runtime bootstrapped via ``CIVICCAST_GSTREAMER_RUNTIME_ROOT`` (TEST-1: the
bundled native-Windows runtime is proven working — an
``openh264enc -> mpegtsmux`` pipeline runs natively through
``civiccast.native.gstreamer_runtime.bootstrap_installed_gstreamer_runtime``). The
capability check (``_wsl_gi_available``) is what actually gates the suite; skipped
(naming ``CIVICCAST_GSTREAMER_RUNTIME_ROOT`` in the reason) only where NEITHER path is
available, so the cross-platform suite still stays green on a bare checkout.

These drive the *production* path: a ``worker.py`` subprocess fed a serialized graph and
a control channel, exactly as the daemon launches it. On WSL/Linux the control channel is
the POSIX FIFO; on native Windows it is the product's own D2 named-pipe seam
(``civiccast.egress.gst.strategy.WindowsWorkerPipeServer`` / ``WorkerPipeSession`` /
``_WindowsPipeChannel``) — this harness plays the STRATEGY's role (pipe server, versioned
envelope, bounded ack wait), the same protocol the daemon speaks in production, not a bare
pipe write (see ``_launch_worker``/``_send``). The captured MPEG-TS is checked for both
continuity-counter errors AND PCR monotonicity (a PCR jump that preserves CC is the
discontinuity a bare CC check would miss — QA-005). Synchronization is by worker log
markers rather than fixed sleeps (QA-003), and the UDP ingest test uses an ephemeral port
(QA-002). The live UDP-TS feed for the ingest/stall tests is synthesized in-process via
the same bundled gi/Gst runtime (``_LiveUdpSender``), not an external ``gst-launch-1.0``
subprocess — one code path on both platforms (task_6dc784a6).

Coverage: build → PLAYING → clean teardown; role-swap continuity; program content-reload
(D-S1-6) continuity incl. the **audio** path (QA-001); reload element-leak guard (TEST-003);
the never-buffers watchdog recovery (ENG-001); a real UDP-TS ingest round-trip; no-hang teardown.

Run under WSL:     wsl -d Ubuntu-24.04 -- bash tests/egress/run_wsl_engine_tests.sh
Run natively on Windows against a bundled runtime install: the interpreter running
pytest must be ABI-compatible with the bundled runtime's ``gi`` extension (its
``_gi.cp312-win_amd64.pyd`` is CPython-3.12-specific — a 3.13 interpreter imports the
pure-Python ``gi`` package fine but fails to load the compiled extension, which
``_windows_bundled_gstreamer_available`` treats as "bootstrap did not succeed" and
skips cleanly, exactly like any other missing capability):
    $env:CIVICCAST_GSTREAMER_RUNTIME_ROOT = "<install_root>\runtime"
    uv run --python 3.12 pytest tests/egress/test_gst_engine_wsl.py
"""

from __future__ import annotations

import base64
import contextlib
import errno
import faulthandler
import os
import re
import socket
import subprocess
import sys
import threading
import time
import uuid
import wave
from dataclasses import replace
from pathlib import Path

import pytest

_GST_DIR = Path(__file__).resolve().parents[2] / "civiccast" / "egress" / "gst"
_WORKER = str(_GST_DIR / "worker.py")


def _linux_gi_available() -> bool:
    """True on Linux (WSL/CI) with gi+Gst importable."""
    if sys.platform != "linux":
        return False
    try:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst  # noqa: F401

        return True
    except Exception:
        return False


def _windows_bundled_gstreamer_available() -> bool:
    """True on native Windows when the bundled native GStreamer runtime is
    present and bootstraps successfully -- the counterpart of
    ``_linux_gi_available`` for the platform this product actually SHIPS
    pipelines on.

    TEST-1 (verified working this session, 2026-08-18): a real
    openh264enc -> mpegtsmux pipeline runs natively via
    ``civiccast.native.gstreamer_runtime.bootstrap_installed_gstreamer_runtime``
    plus ``gi``, TSDuck-clean. Requires ``CIVICCAST_GSTREAMER_RUNTIME_ROOT``
    to name the installed runtime root (the directory whose
    ``dependencies/gstreamer`` subtree ``gstreamer_runtime.py`` expects --
    typically ``<install_root>\\runtime``).

    ``bootstrap_installed_gstreamer_runtime`` only arms THIS process (sys.path
    for ``import gi``, ``PYGI_DLL_DIRS``, and the DLL search path) -- it does
    not persist ``PATH``/``GST_PLUGIN_PATH``/``GI_TYPELIB_PATH`` into
    ``os.environ``. But every worker subprocess this suite launches inherits
    ``env=dict(os.environ)`` (see ``_launch_worker``) and needs exactly those
    three to find its own plugins, typelibs, and the GStreamer DLLs -- so this
    function computes the full environment via
    ``installed_gstreamer_environment`` and applies it to ``os.environ``
    itself (the "PATH prepend... before process start" the runtime needs),
    rather than leaving that to the caller.
    """
    if sys.platform != "win32":
        return False
    root = os.environ.get("CIVICCAST_GSTREAMER_RUNTIME_ROOT")
    if not root:
        return False
    try:
        from civiccast.native.gstreamer_runtime import (
            bootstrap_installed_gstreamer_runtime,
            installed_gstreamer_environment,
        )

        if not bootstrap_installed_gstreamer_runtime():
            return False
        env = installed_gstreamer_environment(root, base_environment=os.environ)
        os.environ.update(env)

        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst  # noqa: F401

        return True
    except Exception:
        return False


_LINUX_GI_AVAILABLE = _linux_gi_available()
# Short-circuited exactly like the original ``_linux_gi_available() or
# _windows_bundled_gstreamer_available()`` expression: the Windows probe (which
# has real side effects -- os.environ mutation, a live gi import) only runs
# when the Linux path did not already satisfy availability, and on Linux it is
# never even called.
_WINDOWS_BUNDLED_GSTREAMER_AVAILABLE = (
    False if _LINUX_GI_AVAILABLE else _windows_bundled_gstreamer_available()
)


def _wsl_gi_available() -> bool:
    """True only where the live engine can actually run for real: Linux
    (WSL/CI) with gi+Gst, or native Windows with the bundled GStreamer
    runtime bootstrapped (see ``_windows_bundled_gstreamer_available``).
    Name kept as-is (rather than renamed at every call site) -- it is still
    exactly "is a live GStreamer engine available here." Reads the two
    module-level flags above rather than recomputing them (recomputing would
    re-run the Windows bootstrap's side effects a second time).
    """
    return _LINUX_GI_AVAILABLE or _WINDOWS_BUNDLED_GSTREAMER_AVAILABLE


pytestmark = pytest.mark.skipif(
    not _wsl_gi_available(),
    reason=(
        "live GStreamer engine tests require Linux/WSL with gi + GStreamer, or native "
        "Windows with CIVICCAST_GSTREAMER_RUNTIME_ROOT set to a bundled native GStreamer "
        "runtime that bootstraps successfully"
    ),
)

# --- resolved Windows-only gap classes ------------------------------------------------
#
# 2026-08-18 verification run: the control channel (FIFO-only harness, unwired Windows
# named-pipe alternative - task_846126ae) and the gst-launch-1.0 sender (deliberately
# excluded from the Windows closure - task_6dc784a6) both blocked the suite from running
# for real on Windows at all. Both are now fixed (see ``_launch_worker``/``_send`` for the
# D2 named-pipe seam port, and ``_LiveUdpSender`` for the in-process sender).
#
# The first real native run (2026-08-19) then surfaced what looked like a caption-embed
# gap (``_WINDOWS_CC_EMBED_DECODE_XFAIL``, since removed): ffmpeg's subcc decode of the
# emitted TS came back empty on Windows. Root-caused the same day: the embed chain
# (tttocea608/ccconverter/cccombiner/h264ccinserter and openh264enc's SEI path) works
# natively — the emitted TS carries the A/53 ``GA94`` caption SEI — but the decode-back
# helper single-escaped the drive colon in the lavfi ``movie=`` filename, so ffmpeg
# split ``C:/...`` at the colon and opened nothing (see ``_decode_back_caption_text``
# and ``caption_proof._escape_movie_path``, fixed together). No Windows caption gap
# remains; the caption tests below run un-marked on both platforms.

# --- hard per-test hang backstop -------------------------------------------------
#
# PR #424: a CI run of this file's "GStreamer live engine" and "Unit tests" jobs ran
# 68+ minutes before a human had to cancel them (forensics: both jobs' logs showed
# the actual hang was in an `apt-get update`/`install` step, before pytest ever
# started -- an infra/mirror stall, not a test hang; see this file's git history for
# the full analysis). That a human had to notice and manually cancel a run at all,
# for ANY reason, is still the real gap: no test in this file had a bound on its OWN
# worst case, so a genuine future hang -- in this harness, in the product it drives,
# or anywhere else in the process -- would silently run the CI job clock out (historically
# up to ~60min) instead of failing fast with a diagnosis. This is a pure safety net,
# stdlib-only (``faulthandler``, no new dependency): every test in this module gets a
# generous, bounded wall-clock allowance; if it's ever exceeded, the interpreter dumps
# every thread's live stack (visible in the CI log -- exactly what was stuck and
# where) and hard-exits, rather than continuing to burn CI minutes silently. This does
# NOT paper over a hang: a test that trips it still reports as failed (the process
# exits non-zero), just fast and with a diagnosis instead of slow and silent.
_TEST_HANG_TIMEOUT_S = 120.0  # ~4-5x this suite's slowest observed single-test wall time


@pytest.fixture(autouse=True)
def _hard_hang_timeout():
    faulthandler.dump_traceback_later(_TEST_HANG_TIMEOUT_S, exit=True)
    try:
        yield
    finally:
        faulthandler.cancel_dump_traceback_later()


# The graph builders are gi-free; import them standalone (no pydantic) the way the
# worker does, so this harness runs under a bare python without the full package.
sys.path.insert(0, str(_GST_DIR))
import graph as graphmod  # noqa: E402

_E = graphmod.ElementSpec
_CAPS = "video/x-raw,width=640,height=360,framerate=30/1"
_ACAPS = "audio/x-raw,rate=48000,channels=2"
_H264_ENCODER = os.environ.get("CIVICCAST_GST_TEST_H264_ENCODER", "openh264enc")


def _h264_sender_encoder_args(*, bitrate_kbps: int = 1500, gop: int = 30) -> list[str]:
    if _H264_ENCODER == "x264enc":
        return [
            "x264enc",
            "tune=zerolatency",
            f"bitrate={bitrate_kbps}",
            f"key-int-max={gop}",
            "!",
            "h264parse",
            "!",
        ]
    return [_H264_ENCODER, f"bitrate={bitrate_kbps}", "!", "h264parse", "!"]


def _live_udp_sender_pipeline_str(port: int, *, bitrate_kbps: int = 1500, gop: int = 30) -> str:
    """The ``gst-launch``-syntax pipeline description for the live UDP-TS sender: a
    scheduled videotestsrc encoded to H.264, muxed to MPEG-TS, and sent over UDP to
    ``127.0.0.1:<port>`` -- identical shape to the sender this replaces, just built for
    ``Gst.parse_launch`` instead of a ``gst-launch-1.0`` argv."""
    encoder_str = " ".join(_h264_sender_encoder_args(bitrate_kbps=bitrate_kbps, gop=gop))
    return (
        f"videotestsrc is-live=true pattern=18 ! {_CAPS} ! {encoder_str} "
        f"mpegtsmux ! udpsink host=127.0.0.1 port={port}"
    )


# Bound on every blocking Gst.Element.get_state() this sender performs, and on the
# background-thread join that guards Gst.State.NULL teardown (see _LiveUdpSender.stop).
# GStreamer's own get_state(timeout) is documented to return (not block past the
# timeout) once the timeout elapses, but a state-change FUNCTION on some element
# (encoder/network sink) blocking internally before ever returning control is a real,
# separate risk class -- exactly what a killed/canceled CI run of this file could not
# distinguish from an apt-get hang without a log (see the commit message for the actual
# forensic finding on this branch: the CI hang that prompted this hardening pass turned
# out to be an apt-get mirror stall before pytest ever started, not this class -- but
# the hardening below is real and warranted independent of that specific run).
_SENDER_STATE_TIMEOUT_S = 5.0


class _LiveUdpSender:
    """In-process UDP-TS sender for the live-ingest tests, replacing the external
    ``gst-launch-1.0`` subprocess (task_6dc784a6: deliberately excluded from the
    native-Windows runtime closure) with a small ``videotestsrc -> encoder ->
    mpegtsmux -> udpsink`` pipeline built via ``Gst.parse_launch`` on the SAME bundled
    gi/Gst runtime this suite already bootstraps -- one code path for both Linux/WSL
    and native Windows rather than an external binary only one platform ships.

    ``freeze()`` (Gst PAUSED) rather than killing a subprocess is the more faithful
    model of S9-5's real failure mode -- "a live source that WAS delivering output
    then silently freezes... no EOS, no bus error": pausing this pipeline stops it
    producing further buffers (so the worker's ``udpsrc`` simply stops receiving
    packets) without tearing down the process or the UDP association, exactly the
    "still there, gone quiet" shape a killed subprocess can only approximate.

    Every state-change wait here is BOUNDED and fails LOUDLY (raises, or prints a
    clear warning to stderr) rather than hanging the caller -- this class has no
    "kill the process" backstop available the way engine.py's own production
    stop() path does (worker.py runs as its own subprocess the daemon can just
    kill; this sender lives IN the pytest process, so a hang here hangs the whole
    test run)."""

    def __init__(self, port: int, *, bitrate_kbps: int = 1500, gop: int = 30) -> None:
        from gi.repository import Gst  # local: only ever constructed once gi is available

        if not Gst.is_initialized():
            Gst.init(None)
        self._Gst = Gst
        pipeline_str = _live_udp_sender_pipeline_str(port, bitrate_kbps=bitrate_kbps, gop=gop)
        self._pipeline = Gst.parse_launch(pipeline_str)
        if self._pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            self._pipeline.set_state(Gst.State.NULL)
            raise RuntimeError(f"live UDP sender pipeline failed to reach PLAYING: {pipeline_str!r}")
        # Block for the (possibly async) PLAYING transition, BOUNDED, so callers can
        # rely on the feed already flowing once the constructor returns -- mirrors the
        # subprocess sender being observably "started" before the caller moves on.
        # The result is CHECKED (not discarded): a pipeline that never actually
        # settles into PLAYING/NO_PREROLL within the bound fails loudly here, at
        # construction, rather than leaving a half-started sender for the caller to
        # discover only via a much-later, harder-to-diagnose timeout elsewhere.
        result, state, _pending = self._pipeline.get_state(_SENDER_STATE_TIMEOUT_S * Gst.SECOND)
        if result == Gst.StateChangeReturn.FAILURE or state != Gst.State.PLAYING:
            with contextlib.suppress(Exception):
                self._pipeline.set_state(Gst.State.NULL)
            raise RuntimeError(
                f"live UDP sender pipeline did not settle into PLAYING within "
                f"{_SENDER_STATE_TIMEOUT_S}s (get_state result={result!r}, state={state!r}): "
                f"{pipeline_str!r}"
            )

    def freeze(self) -> None:
        """Pause the pipeline: no further buffers are produced or sent -- the live
        source silently freezes with no EOS and no bus error (S9-5's real failure
        mode), without tearing down this process or the pipeline. ``set_state()``
        itself is a non-blocking state-change REQUEST (GStreamer defers full
        completion to ``get_state()``), so this cannot hang the caller; the
        pipeline is left in PAUSED until ``stop()`` tears it down."""
        self._pipeline.set_state(self._Gst.State.PAUSED)

    def stop(self) -> None:
        """Tear the sender pipeline down with a BOUNDED teardown. Idempotent; never
        raises (mirrors ``_reap`` never raising on an already-dead subprocess) --
        but a teardown that does not complete within the bound is NOT silently
        swallowed: it prints a loud warning to stderr (visible in the test log)
        instead of blocking the caller forever.

        Runs the actual ``set_state(NULL)`` + confirming ``get_state()`` on a
        background thread and joins it with a timeout: a state-change function
        that itself blocks internally (the classic GStreamer teardown-hang class
        -- exactly what engine.py's own production ``stop()`` guards against with
        a force-exit backstop this in-process sender has no equivalent for) would
        otherwise hang this call, and therefore the whole pytest process,
        indefinitely. On timeout the thread is abandoned (daemon=True, so it
        cannot block interpreter/process exit) rather than joined forever."""
        Gst = self._Gst
        done = threading.Event()

        def _teardown() -> None:
            try:
                self._pipeline.set_state(Gst.State.NULL)
                self._pipeline.get_state(_SENDER_STATE_TIMEOUT_S * Gst.SECOND)
            except Exception:
                pass
            finally:
                done.set()

        thread = threading.Thread(
            target=_teardown, name="civiccast-test-sender-teardown", daemon=True
        )
        thread.start()
        if not done.wait(timeout=_SENDER_STATE_TIMEOUT_S + 2.0):
            print(
                "WARNING: _LiveUdpSender.stop() teardown did not complete within "
                f"{_SENDER_STATE_TIMEOUT_S + 2.0}s -- abandoning the teardown thread "
                "(daemon; will not block process exit) rather than hanging the caller. "
                "This is the exact class of hang engine.py's own force-exit backstop "
                "guards production teardown against; the in-process test sender has no "
                "process to kill, so it gives up loudly here instead.",
                file=sys.stderr,
                flush=True,
            )


# --- MPEG-TS analysis: per-PID continuity counters + PCR monotonicity ----------------


def _analyze_ts(path: Path) -> dict:
    """Return {cc_errors, packets, pids, pcr_backward, pcr_samples} for a captured .ts.

    CC: TR 101 290 P1-style per-PID continuity. PCR: extracted from the adaptation
    field; a backward step (ignoring the 27MHz wrap) is a clock discontinuity a CC
    check can't see (QA-005)."""
    data = path.read_bytes()
    errors, total, last = 0, 0, {}
    pids: dict[int, int] = {}
    pcr_backward, pcr_samples = 0, 0
    last_pcr: float | None = None
    for i in range(0, len(data) - 187, 188):
        if data[i] != 0x47:
            continue
        total += 1
        pid = ((data[i + 1] & 0x1F) << 8) | data[i + 2]
        afc = (data[i + 3] >> 4) & 0x3
        cc = data[i + 3] & 0x0F
        pids[pid] = pids.get(pid, 0) + 1
        if pid == 0x1FFF:
            continue
        # PCR lives in the adaptation field when present and flagged.
        if afc in (2, 3) and i + 5 < len(data):
            af_len = data[i + 4]
            if af_len >= 7 and (data[i + 5] & 0x10):  # PCR_flag
                b = data[i + 6 : i + 12]
                base = (b[0] << 25) | (b[1] << 17) | (b[2] << 9) | (b[3] << 1) | (b[4] >> 7)
                ext = ((b[4] & 0x01) << 8) | b[5]
                pcr = (base * 300 + ext) / 27_000_000.0
                pcr_samples += 1
                if last_pcr is not None and pcr < last_pcr - 1.0:  # >1s backward = jump
                    pcr_backward += 1
                last_pcr = pcr
        if afc in (1, 3):  # has payload → CC must increment
            if pid in last:
                exp = (last[pid] + 1) & 0x0F
                if cc == last[pid]:
                    pass  # one duplicate is permitted by the spec; PCR check backstops it
                elif cc != exp:
                    errors += 1
            last[pid] = cc
    return {
        "cc_errors": errors,
        "packets": total,
        "pids": pids,
        "pcr_backward": pcr_backward,
        "pcr_samples": pcr_samples,
    }


def _assert_continuous(ts: Path, log: str, *, require_audio_pid: bool = False) -> dict:
    a = _analyze_ts(ts)
    assert a["packets"] > 0, f"no TS produced; log:\n{log}"
    assert a["cc_errors"] == 0, f"{a['cc_errors']} continuity errors; log:\n{log}"
    assert a["pcr_backward"] == 0, f"{a['pcr_backward']} PCR discontinuities; log:\n{log}"
    if require_audio_pid:
        # elementary PIDs are >= 0x40 here (PAT=0, PMT=0x20); expect >= 2 (video+audio)
        elementary = [p for p in a["pids"] if p >= 0x40]
        assert len(elementary) >= 2, f"expected video+audio PIDs, got {a['pids']}; log:\n{log}"
    return a


def _ffprobe_codec_types(path: Path) -> set[str]:
    """The set of stream codec_types ffprobe reports for the captured TS (e.g.
    ``{'video', 'audio'}``) — a decode-level confirmation beyond PID counting."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


# --- worker subprocess driver --------------------------------------------------------

# On native Windows, ack wait must cover the time from write until the worker's GLib
# main loop actually starts running (idle_add callbacks only fire once loop.run() is
# reached, i.e. AFTER the pipeline hits PLAYING -- engine.py's run_forever) -- not just
# network/IPC latency. The pipe CONNECT itself happens near-instantly (the worker's
# pipe-reader thread connects as client at process start, independent of PLAYING), but
# the first command's ack can't land until the pipeline has prerolled. 20s gives ample
# headroom over the engine's own 5s default teardown_timeout_s (used as the PLAYING
# deadline too) for a slower software encoder start, while still failing fast and
# legibly if something is actually wedged.
_WINDOWS_PIPE_ACK_TIMEOUT_S = 20.0


def _free_udp_port() -> int:
    """Pick a currently-free UDP port (bind :0, read it, release) — no fixed-port
    collisions across overlapping runs (QA-002)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def _send(control, line: str, *, attempts: int = 80) -> None:
    """Send one control line to the worker over its control channel.

    POSIX (``control`` is the FIFO ``Path``): a non-blocking FIFO write, retrying
    until a reader is present (the worker opens the read end only once it reaches
    PLAYING — so this also gates on readiness, no warmup sleep needed). Unchanged
    from before the D2 port.

    Native Windows (``control`` is a ``_WindowsPipeChannel``): routes through the
    product's own D2 worker-pipe seam — the versioned envelope
    (``encode_envelope_command``/``decode_envelope_ack``) plus a bounded wait for the
    worker's ack (``_WindowsPipeChannel.send_and_wait``), exactly the protocol
    ``GstPlayoutStrategy.send_command`` speaks in production. A bare pipe write would
    skip the structured envelope/dedup/ack contract the worker's pipe-reader thread
    actually requires (worker.py's ``_windows_pipe_reader_loop`` expects a JSON
    envelope, not a raw control line)."""
    if os.name == "nt":
        verb_token = line.strip().split(None, 1)
        if not verb_token:
            raise AssertionError(f"empty control line: {line!r}")
        verb = verb_token[0].lower()
        if not control.send_and_wait(verb, line):
            raise AssertionError(
                f"worker never acked control line {line!r} over the D2 named-pipe seam "
                f"(no ack within {control._ack_timeout_s}s)"
            )
        return
    payload = (line.rstrip("\n") + "\n").encode("utf-8")
    for _ in range(attempts):
        try:
            fd = os.open(os.fspath(control), os.O_WRONLY | os.O_NONBLOCK)
        except OSError as exc:
            if exc.errno in (errno.ENXIO, errno.ENOENT):
                time.sleep(0.1)
                continue
            raise
        try:
            os.write(fd, payload)
            return
        finally:
            os.close(fd)
    raise AssertionError(f"worker never opened the control FIFO for {line!r}")


def _wait_for_log(log: Path, marker: str, *, count: int = 1, timeout: float = 15.0) -> None:
    """Poll the worker log until ``marker`` has appeared ``count`` times (a readiness
    signal instead of a fixed sleep — QA-003)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if (
            log.exists()
            and log.read_text(encoding="utf-8", errors="replace").count(marker) >= count
        ):
            return
        time.sleep(0.1)
    got = log.read_text(encoding="utf-8", errors="replace") if log.exists() else "<no log>"
    raise AssertionError(f"marker {marker!r} x{count} not seen within {timeout}s; log:\n{got}")


def _launch_worker(tmp_path: Path, graph, out_ts: Path, env_extra: dict | None = None):
    """Start a worker on ``graph`` writing TS to ``out_ts``; return (proc, control, log).

    ``control`` is the FIFO ``Path`` on POSIX, or a ``_WindowsPipeChannel`` on native
    Windows -- on Windows this harness plays the STRATEGY's role from design.md sec4:
    it creates+serves the per-worker named pipe (``WindowsWorkerPipeServer`` via
    ``_WindowsPipeChannel``) BEFORE launching the worker, then passes the worker the
    pipe NAME (not a filesystem path) as argv[2], matching
    ``GstPlayoutStrategy.start()`` exactly (strategy.py ~703-729)."""
    gpath = tmp_path / "graph.json"
    gpath.write_text(graphmod.graph_to_json(graph), encoding="utf-8")
    log = tmp_path / "worker.log"
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    log_fh = log.open("w", encoding="utf-8")
    if os.name == "nt":
        from civiccast.egress.gst.strategy import (
            WindowsWorkerPipeServer,
            _WindowsPipeChannel,
            worker_pipe_name,
        )

        channel_id = f"wsltest-{uuid.uuid4().hex}"
        # WindowsWorkerPipeServer's default SDDL is "D:P(A;;GA;;;SY)" -- SYSTEM only,
        # correct for production where the daemon (server) AND the worker it spawns
        # (client) both run as the LocalSystem service identity (strategy.py's own
        # comment on this). This dev/CI harness runs as a normal, non-SYSTEM Windows
        # user for BOTH sides, so a SYSTEM-only ACL makes the worker's CreateFile
        # connect fail with ERROR_ACCESS_DENIED (verified directly: a bare-Win32 probe
        # against the default SDDL reproduces winerror 5 "Access is denied" on
        # connect). That failure is silent to the test process — the worker's own
        # reader thread just retries with backoff forever, never delivers the "stop"
        # ack, and the strategy side's accept() thread blocks in ConnectNamedPipe
        # forever too -- an indefinite hang, not a fast, legible failure. The fix is
        # the SDDL constructor param `WindowsWorkerPipeServer` already exposes for
        # exactly this: supply one that admits the identity this harness actually
        # runs as (Authenticated Users), instead of touching the production default.
        server = WindowsWorkerPipeServer(channel_id, security_descriptor_sddl="D:P(A;;GA;;;AU)")
        control = _WindowsPipeChannel(
            channel_id, server=server, ack_timeout_s=_WINDOWS_PIPE_ACK_TIMEOUT_S
        )
        control.start()  # creates the pipe + accepts the worker's connection on a bg thread
        control_arg = worker_pipe_name(channel_id)
    else:
        control = tmp_path / "control.fifo"
        control_arg = str(control)
    proc = subprocess.Popen(
        [sys.executable, _WORKER, str(gpath), control_arg],
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    proc._cc_log_fh = log_fh  # keep a ref so _reap can close it (no ResourceWarning)
    proc._cc_control = control  # so _reap can close the Windows pipe channel too
    return proc, control, log


def _reap(proc) -> int | None:
    if proc.poll() is None:
        proc.kill()
    try:
        rc = proc.wait(timeout=5)
    except Exception:
        rc = None
    fh = getattr(proc, "_cc_log_fh", None)
    if fh is not None:
        with contextlib.suppress(Exception):
            fh.close()
    control = getattr(proc, "_cc_control", None)
    if control is not None and hasattr(control, "close"):
        with contextlib.suppress(Exception):
            control.close()
    return rc


def _filesink_graph(graph, out_ts: Path):
    """Return ``graph`` with its sink rewritten to a single filesink at ``out_ts``."""
    sinks = ((_E("queue"), _E("filesink", props={"location": str(out_ts)})),)
    return graphmod.PlayoutGraph(
        sources=graph.sources,
        encoder=graph.encoder,
        audio_encoder=graph.audio_encoder,
        mux=graph.mux,
        sinks=sinks,
        captions=graph.captions,
        secondary_audio=graph.secondary_audio,
    )


# worker.py's D2 Windows pipe-seam dispatch (`_dispatch_control_with_ack`) calls the
# SAME engine effects the POSIX FIFO dispatch (`GstPlayoutEngine._dispatch_control`)
# does, but does NOT print that path's operator-facing "CTRL swap N applied" /
# "CTRL reload armed" / "CTRL stop" lines (confirmed by reading worker.py:73-111
# against engine.py's `_dispatch_control`, engine.py:870-906 -- the ack-dispatch
# function returns a (result, detail) tuple for the pipe ack instead of printing).
# "CTRL reload committed" / "CTRL reload aborted" / "CTRL reload superseding..." are
# unaffected -- those are printed from INSIDE ``reload_program()`` itself
# (engine.py:1010, 690, 932), which both dispatch paths call identically, so they
# still appear on both platforms. This is a disclosed, real worker.py log-parity gap
# (production operators tailing a Windows worker's stdout would not see these
# confirmations either) -- out of scope to fix here (test harness only; see the
# task's own "no product-code changes expected" scope) -- so the harness routes
# around it rather than either masking it or blocking forever on markers that can
# never appear on Windows.
_WINDOWS_CTRL_APPLIED_LOG_LINES_MISSING = os.name == "nt"


def _await_markers_if_needed(log: Path, markers) -> None:
    """Wait for each log marker in turn -- meaningful only on the POSIX FIFO path.

    There, ``_send`` is a fire-and-forget non-blocking write with no ack, so
    log-marker polling is the ONLY way to know a command was actually applied. On
    the Windows D2 pipe path ``_send`` already performs a synchronous
    send-and-wait-for-ack (``_WindowsPipeChannel.send_and_wait``) -- by the time
    each ``_send()`` call in the caller's loop returns, that command has ALREADY
    been applied, a stronger, synchronous guarantee than polling a log line that
    (per ``_WINDOWS_CTRL_APPLIED_LOG_LINES_MISSING`` above) does not even get
    printed on that path."""
    if _WINDOWS_CTRL_APPLIED_LOG_LINES_MISSING:
        return
    for marker in markers:
        _wait_for_log(log, marker)


def _assert_reload_committed(logtext: str) -> None:
    """Assert a content-reload committed -- and, on POSIX only, that it was also
    logged as armed (see ``_WINDOWS_CTRL_APPLIED_LOG_LINES_MISSING``: "CTRL reload
    armed" is never printed on the Windows D2 dispatch path). "CTRL reload
    committed" is printed from inside ``reload_program()`` itself, unaffected by
    which dispatch path called it, so it is asserted unconditionally on both
    platforms."""
    assert "CTRL reload committed" in logtext, logtext
    if not _WINDOWS_CTRL_APPLIED_LOG_LINES_MISSING:
        assert "CTRL reload armed" in logtext, logtext


def _run_worker(
    tmp_path: Path,
    graph,
    commands=(),
    *,
    await_markers=(),
    produce_window: float = 0.8,
    wait_timeout: float = 25.0,
    auto_stop: bool = True,
    env_extra: dict | None = None,
) -> tuple[int, Path, str]:
    """Launch a worker, send ``commands``, wait for ``await_markers`` (not fixed
    sleeps), let a little more TS flush, then ``stop``. ``auto_stop=False`` waits for a
    self-terminating (finite, non-live) source. Returns (rc, out_ts, log_text)."""
    out_ts = tmp_path / "out.ts"
    proc, control, log = _launch_worker(tmp_path, _filesink_graph(graph, out_ts), out_ts, env_extra)
    returncode: int | None = None
    try:
        if auto_stop:
            for command in commands:
                _send(control, command)
                time.sleep(0.3)  # small spacing so each command lands distinctly
            _await_markers_if_needed(log, await_markers)
            time.sleep(produce_window)
            _send(control, "stop")
        returncode = proc.wait(timeout=wait_timeout)
    finally:
        _reap(proc)  # closes the log fh; kills if still running
    return returncode, out_ts, log.read_text(encoding="utf-8", errors="replace")


# --- S11a CEA-708 caption embed (live engine) ----------------------------------------


def _cc_embed_elements_available() -> bool:
    """True only when the gst-native CC embed lane is installed (gst-plugins-bad
    closedcaption + gst-plugins-rs rsclosedcaption). Lets the caption embed test skip
    cleanly where the plugins are not provisioned, instead of false-failing."""
    from gi.repository import Gst

    Gst.init([])
    return all(
        Gst.ElementFactory.find(name)
        for name in ("tttocea608", "ccconverter", "cccombiner", "h264ccinserter")
    )


def _decode_back_caption_text(ts: Path) -> str:
    """Decode embedded CEA-608/708 captions from a TS via ffmpeg ``movie=...subcc`` → SRT.

    Mirrors ``caption_proof.decode_embedded_captions`` but inline (the WSL harness runs
    under a bare python without the full package). The filename crosses two
    escape-consuming ffmpeg parsers (filtergraph, then the movie filter's option
    parser), so a literal ``:`` needs ``\\\\:`` — single-level ``\\:`` splits a Windows
    ``C:/...`` path at the drive colon (see ``caption_proof._escape_movie_path``)."""
    movie = ts.as_posix().replace("\\", "\\\\\\\\").replace(":", "\\\\:")
    proc = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-f",
            "lavfi",
            "-i",
            f"movie={movie}[out0+subcc]",
            "-map",
            "0:1",
            "-f",
            "srt",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    return proc.stdout if proc.returncode == 0 else ""


def _assert_caption_decoded(decoded: str, expected: str, *, context: str) -> None:
    """The exact, narrow decode-check both CC-embed tests end on.

    This used to raise a distinct ``_CaptionDecodeGap`` so the (now removed)
    ``_WINDOWS_CC_EMBED_DECODE_XFAIL`` marker could absorb THIS check and only
    this one. That xfail existed because the decode came back empty on native
    Windows; root-caused to the single-escaped drive colon in the lavfi
    ``movie=`` path, not a caption-embed gap, and fixed. With no xfail left to
    scope, the distinct exception type has nothing to distinguish itself from
    and a plain ``assert`` is the honest form -- every check in these tests now
    fails the same loud way."""
    assert expected.upper() in decoded.upper(), (
        f"embedded caption did not decode back out of the emitted stream; "
        f"decoded={decoded!r}; {context}"
    )


@pytest.mark.skipif(
    not (_wsl_gi_available() and _cc_embed_elements_available()),
    reason="CC embed elements (tttocea608/ccconverter/cccombiner/h264ccinserter) not installed",
)
def test_caption_embed_survives_to_emitted_stream(tmp_path: Path) -> None:
    """S11a rung-1: a sidecar caption embedded by the native CC leg decodes back out of
    the emitted stream — the proof that flips caption_status to on. The full embed path
    (graph.caption leg → engine pad-link → cccombiner/h264ccinserter SEI) end-to-end."""
    sidecar = tmp_path / "cap.srt"
    sidecar.write_text("1\n00:00:00,200 --> 00:00:03,500\nHELLO CIVICCAST\n", encoding="utf-8")
    out_ts = tmp_path / "out.ts"
    graph = graphmod.PlayoutGraph(
        sources=(
            graphmod.SourceLeg(
                label="program",
                elements=(
                    _E("videotestsrc", props={"is-live": True, "pattern": 0}),
                    _E("capsfilter", props={"caps": _CAPS}),
                ),
            ),
        ),
        encoder=graphmod.encode_chain_specs(
            width=640,
            height=360,
            fps=30,
            bitrate_kbps=2000,
            gop=30,
            encoder=_H264_ENCODER,
        ),
        mux=_E("mpegtsmux", name="mux"),
        sinks=((_E("queue"), _E("filesink", props={"location": str(out_ts)})),),
        captions=graphmod.caption_embed_leg_from_sidecar(str(sidecar)),
    )
    proc, control, log = _launch_worker(tmp_path, graph, out_ts)
    try:
        time.sleep(4.0)  # produce past the 0.2-3.5s cue window
        _send(control, "stop")
        proc.wait(timeout=25)
    finally:
        _reap(proc)
    assert out_ts.exists() and out_ts.stat().st_size > 0, f"no TS produced; log:\n{log.read_text()}"
    decoded = _decode_back_caption_text(out_ts)
    _assert_caption_decoded(
        decoded, "HELLO CIVICCAST", context=f"worker log:\n{log.read_text(errors='replace')}"
    )


@pytest.mark.skipif(
    not (_wsl_gi_available() and _cc_embed_elements_available()),
    reason="CC embed elements (tttocea608/ccconverter/cccombiner/h264ccinserter) not installed",
)
def test_live_caption_appsrc_starts_without_a_cue_and_decodes_a_later_cue(
    tmp_path: Path,
) -> None:
    """Sparse live captions must neither deadlock startup nor stall video output."""

    out_ts = tmp_path / "out.ts"
    graph = graphmod.PlayoutGraph(
        sources=(
            graphmod.SourceLeg(
                label="program",
                elements=(
                    _E("videotestsrc", props={"is-live": True, "pattern": 0}),
                    _E("capsfilter", props={"caps": _CAPS}),
                ),
            ),
        ),
        encoder=graphmod.encode_chain_specs(
            width=640,
            height=360,
            fps=30,
            bitrate_kbps=2000,
            gop=30,
            encoder=_H264_ENCODER,
        ),
        mux=_E("mpegtsmux", name="mux"),
        sinks=((_E("queue"), _E("filesink", props={"location": str(out_ts)})),),
        captions=graphmod.caption_embed_leg_live(),
    )
    payload = base64.b64encode(b"HELLO LIVE CIVICCAST").decode("ascii")
    returncode, emitted, log = _run_worker(
        tmp_path,
        graph,
        commands=(f"caption 1000 2000 {payload}",),
        produce_window=4.0,
    )

    assert returncode == 0, log
    assert emitted.stat().st_size > 0, log
    _assert_caption_decoded(_decode_back_caption_text(emitted), "HELLO LIVE CIVICCAST", context=log)


# --- S11 gap 9: secondary audio PID (SAP / descriptive) -----------------------------


def _count_audio_streams(ts: Path) -> int:
    """Count audio elementary streams in a captured TS via ffprobe."""
    import shutil

    if shutil.which("ffprobe") is None:
        return -1  # ffprobe absent — caller skips
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(ts),
        ],
        capture_output=True,
        text=True,
    )
    return len([line for line in proc.stdout.splitlines() if line.strip()])


def _audio_language_tags(ts: Path) -> set[str]:
    """The ISO-639 language tags on the TS's audio PIDs (from the language descriptor)."""
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream_tags=language",
            "-of",
            "csv=p=0",
            str(ts),
        ],
        capture_output=True,
        text=True,
    )
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


def test_secondary_audio_muxes_an_extra_pid(tmp_path: Path) -> None:
    """S11 gap 9 / DC-SAP1: a secondary audio program is muxed as a 2nd audio PID
    (the TV SAP button). End-to-end: graph.secondary_audio -> engine PID muxing."""
    import shutil

    if shutil.which("ffprobe") is None:
        import pytest

        pytest.skip("ffprobe not installed; cannot count audio streams")
    out_ts = tmp_path / "out.ts"
    graph = graphmod.PlayoutGraph(
        sources=(
            graphmod.SourceLeg(
                label="program",
                elements=(
                    _E("videotestsrc", props={"is-live": True, "pattern": 0}),
                    _E("capsfilter", props={"caps": _CAPS}),
                ),
                audio=(
                    _E("audiotestsrc", props={"is-live": True, "wave": 0}),
                    _E("audioconvert"),
                    _E("audioresample"),
                    _E("capsfilter", props={"caps": _ACAPS}),
                ),
            ),
        ),
        encoder=graphmod.encode_chain_specs(
            width=640, height=360, fps=30, bitrate_kbps=2000, gop=30
        ),
        audio_encoder=graphmod.audio_encode_specs(),
        mux=_E("mpegtsmux", name="mux"),
        sinks=((_E("queue"), _E("filesink", props={"location": str(out_ts)})),),
        secondary_audio=(
            graphmod.SecondaryAudioLeg(
                label="Spanish SAP",
                language="es",
                kind="sap",
                source=(
                    _E("audiotestsrc", props={"is-live": True, "wave": 4}),  # 4 = silence
                    _E("capsfilter", props={"caps": _ACAPS}),
                ),
                encoder=graphmod.audio_encode_specs(),
            ),
        ),
    )
    proc, control, log = _launch_worker(tmp_path, graph, out_ts)
    try:
        time.sleep(3.0)
        _send(control, "stop")
        proc.wait(timeout=25)
    finally:
        _reap(proc)
    assert out_ts.exists() and out_ts.stat().st_size > 0, f"no TS; log:\n{log.read_text()}"
    audio_streams = _count_audio_streams(out_ts)
    assert audio_streams >= 2, (
        f"expected >=2 audio PIDs (primary + SAP), got {audio_streams}; "
        f"log:\n{log.read_text(errors='replace')}"
    )
    # DC-SAP / parity: the SAP PID must carry its ISO-639 language descriptor (the TV
    # SAP button's label), not just exist — _tag_audio_language is best-effort, so this
    # converts it from unverified-by-design into a checked behavior. mpegtsmux may map
    # 'es' -> the ISO-639-2 'spa'.
    langs = _audio_language_tags(out_ts)
    assert langs & {"es", "spa"}, (
        f"secondary audio PID is missing its language descriptor; tags={langs}; "
        f"log:\n{log.read_text(errors='replace')}"
    )


# --- graph builders ------------------------------------------------------------------


def _av_demo_graph(nsrc: int = 2):
    """Production-shape A/V graph: dual-selector video+audio (what graph_from_config
    always emits) — the shape the video-only demo graph never exercises (QA-001)."""
    patterns = [0, 18, 1, 2]
    sources = tuple(
        graphmod.SourceLeg(
            label=f"src{i}",
            elements=(
                _E("videotestsrc", props={"is-live": True, "pattern": patterns[i % len(patterns)]}),
                _E("capsfilter", props={"caps": _CAPS}),
            ),
            audio=(
                _E("audiotestsrc", props={"is-live": True, "wave": (i % 2) * 4}),
                _E("audioconvert"),
                _E("audioresample"),
                _E("capsfilter", props={"caps": _ACAPS}),
            ),
        )
        for i in range(nsrc)
    )
    return graphmod.PlayoutGraph(
        sources=sources,
        encoder=graphmod.encode_chain_specs(
            width=640, height=360, fps=30, bitrate_kbps=2000, gop=30
        ),
        audio_encoder=graphmod.audio_encode_specs(sample_rate=48000),
        mux=_E("mpegtsmux", name="mux"),
        sinks=((_E("queue"), _E("filesink", props={"location": "/tmp/x.ts"})),),
    )


def test_live_worker_forks_selected_program_audio_into_atomic_caption_wavs(
    tmp_path: Path,
) -> None:
    out_ts = tmp_path / "caption-tap.ts"
    tap_dir = tmp_path / "caption-tap" / "channel-1"
    base = replace(
        _av_demo_graph(),
        audio_encoder=graphmod.audio_encode_specs(codec="voaacenc"),
    )
    graph = replace(
        _filesink_graph(base, out_ts),
        audio_tap=graphmod.AudioTapLeg(
            tap_dir=str(tap_dir),
            segment_seconds=0.5,
        ),
    )
    proc, control, log = _launch_worker(tmp_path, graph, out_ts)
    try:
        time.sleep(4.0)
        _send(control, "stop")
        proc.wait(timeout=25)
    finally:
        _reap(proc)

    segments = sorted(tap_dir.glob("chunk-*.wav"))
    assert len(segments) >= 2, f"no rolling caption audio; log:\n{log.read_text()}"
    assert not list(tap_dir.glob("*.partial"))
    total_frames = 0
    for segment in segments:
        with wave.open(str(segment), "rb") as source:
            assert source.getnchannels() == 1
            assert source.getsampwidth() == 2
            assert source.getframerate() == 16_000
            total_frames += source.getnframes()
    assert total_frames > 16_000, f"caption tap captured too little audio; log:\n{log.read_text()}"


def _reload_graph(pattern: int, *, audio: bool = False):
    """A graph whose program leg (source 0) is a distinct videotestsrc pattern (used as
    a reload payload — only ``sources[0]`` is read by the worker)."""
    program = graphmod.SourceLeg(
        label="program",
        elements=(
            _E("videotestsrc", props={"is-live": True, "pattern": pattern}),
            _E("capsfilter", props={"caps": _CAPS}),
        ),
        audio=(
            _E("audiotestsrc", props={"is-live": True, "wave": 8}),
            _E("audioconvert"),
            _E("audioresample"),
            _E("capsfilter", props={"caps": _ACAPS}),
        )
        if audio
        else (),
    )
    base = _av_demo_graph(nsrc=2) if audio else graphmod.demo_test_graph(nsrc=2)
    return graphmod.PlayoutGraph(
        sources=(program, base.sources[1]),
        encoder=base.encoder,
        audio_encoder=base.audio_encoder,
        mux=base.mux,
        sinks=base.sinks,
    )


def _udpsrc_program_graph(port: int):
    """A program leg fed by a live udpsrc (used by the dead-port watchdog test and the
    live-ingest test)."""
    live = graphmod.SourceLeg(
        label="program",
        elements=(
            _E("udpsrc", props={"uri": f"udp://127.0.0.1:{port}"}),
            _E("decodebin"),
            _E("videoconvert"),
            _E("videoscale"),
            _E("videorate"),
            _E("capsfilter", props={"caps": _CAPS}),
        ),
    )
    base = graphmod.demo_test_graph(nsrc=2)
    return graphmod.PlayoutGraph(
        sources=(live, base.sources[1]), encoder=base.encoder, mux=base.mux, sinks=base.sinks
    )


# --- tests ---------------------------------------------------------------------------


def test_build_play_teardown_clean(tmp_path: Path) -> None:
    """A finite non-live source reaches EOS and tears down to NULL cleanly (exit 0)."""
    caps = "video/x-raw,width=320,height=240,framerate=30/1"
    src = graphmod.SourceLeg(
        label="program",
        elements=(
            _E("videotestsrc", props={"is-live": False, "num-buffers": 300, "pattern": 0}),
            _E("capsfilter", props={"caps": caps}),
        ),
    )
    graph = graphmod.PlayoutGraph(
        sources=(src,),
        encoder=graphmod.encode_chain_specs(
            width=320, height=240, fps=30, bitrate_kbps=1500, gop=30
        ),
        mux=_E("mpegtsmux", name="mux"),
        sinks=((_E("filesink", props={"location": "/tmp/x.ts"}),),),
    )
    rc, out_ts, log = _run_worker(tmp_path, graph, auto_stop=False, wait_timeout=20.0)
    assert rc == 0, f"expected clean NULL teardown (exit 0); log:\n{log}"
    _assert_continuous(out_ts, log)


def test_swap_role_continuity(tmp_path: Path) -> None:
    """A role swap keeps MPEG-TS continuity (CC + PCR) intact, and the channel tears
    down cleanly (rc==0 — a forced-kill 70 would signal a teardown regression)."""
    rc, out_ts, log = _run_worker(
        tmp_path,
        graphmod.demo_test_graph(nsrc=2),
        commands=["swap 1", "swap 0"],
        await_markers=["CTRL swap 1 applied", "CTRL swap 0 applied"],
    )
    assert rc == 0, f"unclean teardown after swap (rc={rc}); log:\n{log}"
    _assert_continuous(out_ts, log)


def test_content_reload_continuity(tmp_path: Path) -> None:
    """D-S1-6 (Gap 2): a program content-reload rebuilds the program leg live, commits
    on the new leg's first buffer, and keeps continuity (CC + PCR) intact."""
    reload_path = tmp_path / "reload.json"
    reload_path.write_text(graphmod.graph_to_json(_reload_graph(18)), encoding="utf-8")
    rc, out_ts, log = _run_worker(
        tmp_path,
        graphmod.demo_test_graph(nsrc=2),
        commands=[f"reload {reload_path}"],
        await_markers=["CTRL reload committed"],
    )
    assert rc == 0, f"unclean teardown after reload (rc={rc}); log:\n{log}"
    _assert_reload_committed(log)
    _assert_continuous(out_ts, log)


def test_swap_role_continuity_av(tmp_path: Path) -> None:
    """QA-001/TEST-002 — A/V twin of test_swap_role_continuity. The production
    dual-selector graph (video + audio) is what graph_from_config always emits; the
    video-only demo graph never exercises the audio input-selector swap (engine.py
    77-79) or the A/V index-alignment guard (engine.py 317-331, the issue-#56 desync
    class). Swap roles and assert BOTH the video and audio PIDs stay continuous."""
    rc, out_ts, log = _run_worker(
        tmp_path,
        _av_demo_graph(nsrc=2),
        commands=["swap 1", "swap 0"],
        await_markers=["CTRL swap 1 applied", "CTRL swap 0 applied"],
    )
    assert rc == 0, f"unclean teardown after A/V swap (rc={rc}); log:\n{log}"
    a = _assert_continuous(out_ts, log, require_audio_pid=True)  # >=2 elementary PIDs, 0 CC on all
    assert a["cc_errors"] == 0, f"audio/video desync across swap; pids={a['pids']}; log:\n{log}"
    assert {"video", "audio"} <= _ffprobe_codec_types(out_ts), (
        f"ffprobe did not report both a video and an audio stream; log:\n{log}"
    )


def test_content_reload_continuity_av(tmp_path: Path) -> None:
    """QA-001/TEST-002 — A/V twin of test_content_reload_continuity. A content-reload on
    the production dual-selector graph rebuilds the program leg's video AND audio,
    commits on the new leg's first buffer, and disposes the old A/V leg (engine.py
    527-560, the audio branches of _commit_reload / _dispose_source_leg). Assert both
    PIDs stay continuous across the reload — the issue-#56 desync class on the reload
    path, which is otherwise untested."""
    reload_path = tmp_path / "reload_av.json"
    reload_path.write_text(graphmod.graph_to_json(_reload_graph(18, audio=True)), encoding="utf-8")
    rc, out_ts, log = _run_worker(
        tmp_path,
        _av_demo_graph(nsrc=2),
        commands=[f"reload {reload_path}"],
        await_markers=["CTRL reload committed"],
    )
    assert rc == 0, f"unclean teardown after A/V reload (rc={rc}); log:\n{log}"
    _assert_reload_committed(log)
    a = _assert_continuous(out_ts, log, require_audio_pid=True)
    assert a["cc_errors"] == 0, f"audio/video desync across reload; pids={a['pids']}; log:\n{log}"
    assert {"video", "audio"} <= _ffprobe_codec_types(out_ts), (
        f"ffprobe did not report both a video and an audio stream; log:\n{log}"
    )


def test_repeated_reloads_no_leak(tmp_path: Path) -> None:
    """TEST-003: reload many times; the disposer must reclaim the old leg every cycle
    so the pipeline element count stays flat (a dispose leak would grow it)."""
    out_ts = tmp_path / "out.ts"
    graph = _filesink_graph(graphmod.demo_test_graph(nsrc=2), out_ts)
    proc, control, log = _launch_worker(tmp_path, graph, out_ts)
    cycles = 5
    try:
        for n in range(cycles):
            rg = tmp_path / f"reload_{n}.json"
            rg.write_text(
                graphmod.graph_to_json(_reload_graph(18 if n % 2 else 1)), encoding="utf-8"
            )
            _send(control, f"reload {rg}")
            _wait_for_log(log, "CTRL reload committed", count=n + 1)
        _send(control, "stop")
        proc.wait(timeout=25)
    finally:
        _reap(proc)
    counts = [
        int(m) for m in re.findall(r"CTRL reload committed \(elements=(\d+)\)", log.read_text())
    ]
    assert len(counts) == cycles, f"expected {cycles} commits, got {counts}"
    assert len(set(counts)) == 1, f"element count not flat across reloads: {counts} (leak)"


def test_reload_never_buffers_recovers(tmp_path: Path) -> None:
    """ENG-001 + TEST-003: a reload whose new leg never delivers a first buffer (a
    udpsrc on a dead port) must NOT wedge the channel. Also exercises supersede: a
    second dead reload arriving while the first is still settling replaces it; then the
    watchdog aborts, and a SUBSEQUENT good reload still commits (the channel recovers)."""
    dead_a, dead_b = _free_udp_port(), _free_udp_port()  # nothing is sending to either
    good = tmp_path / "good.json"
    good.write_text(graphmod.graph_to_json(_reload_graph(2)), encoding="utf-8")
    bad_a = tmp_path / "bad_a.json"
    bad_a.write_text(graphmod.graph_to_json(_udpsrc_program_graph(dead_a)), encoding="utf-8")
    bad_b = tmp_path / "bad_b.json"
    bad_b.write_text(graphmod.graph_to_json(_udpsrc_program_graph(dead_b)), encoding="utf-8")

    out_ts = tmp_path / "out.ts"
    graph = _filesink_graph(graphmod.demo_test_graph(nsrc=2), out_ts)
    # 2s reload watchdog so the abort happens fast in the test
    proc, control, log = _launch_worker(tmp_path, graph, out_ts, {"CIVICCAST_RELOAD_TIMEOUT_S": "2"})
    try:
        _send(control, f"reload {bad_a}")  # never buffers (dead port)
        time.sleep(0.2)
        _send(control, f"reload {bad_b}")  # supersedes bad_a while it's still settling
        _wait_for_log(log, "CTRL reload aborted", timeout=12.0)  # watchdog fired on bad_b
        _send(control, f"reload {good}")  # channel must NOT be wedged
        _wait_for_log(log, "CTRL reload committed", timeout=12.0)
        _send(control, "stop")
        proc.wait(timeout=25)
    finally:
        _reap(proc)
    text = log.read_text()
    assert "superseding a still-settling reload" in text, "supersede path not exercised"
    assert "CTRL reload aborted" in text, "watchdog never aborted the dead reload"
    assert "CTRL reload committed" in text, "channel wedged — good reload never landed"
    _assert_continuous(out_ts, text)


def test_control_stop_does_not_hang(tmp_path: Path) -> None:
    """An is-live channel must exit on stop rather than hang at →NULL (the Stage-0
    6-hour-hang lesson). 0 = clean NULL, 70 = forced-kill backstop — both = exited."""
    rc, _out, log = _run_worker(tmp_path, graphmod.demo_test_graph(nsrc=2))
    assert rc in (0, 70), f"worker did not exit (rc={rc}); log:\n{log}"
    # "CTRL stop" is never printed on the Windows D2 dispatch path (see
    # _WINDOWS_CTRL_APPLIED_LOG_LINES_MISSING) -- there, ``_send``'s synchronous
    # ack (which `_run_worker` already required to succeed, or it would have
    # raised) is the proof stop was processed, together with the clean/forced exit
    # asserted above.
    if not _WINDOWS_CTRL_APPLIED_LOG_LINES_MISSING:
        assert "CTRL stop" in log, log


def test_live_udp_ingest_continuity(tmp_path: Path) -> None:
    """Gap 3: the engine ingests a real live UDP-TS feed as its program source and
    re-muxes it with continuity intact. Ephemeral port — no fixed-port collision (QA-002)."""
    port = _free_udp_port()
    out_ts = tmp_path / "out.ts"
    graph = _filesink_graph(_udpsrc_program_graph(port), out_ts)
    sender = _LiveUdpSender(port, bitrate_kbps=1500, gop=30)
    proc, control, log = _launch_worker(tmp_path, graph, out_ts)
    try:
        time.sleep(4.0)  # receive several seconds of the live feed, re-mux to disk
        _send(control, "stop")
        rc = proc.wait(timeout=20)
    finally:
        _reap(proc)
        sender.stop()
    logtext = log.read_text(encoding="utf-8", errors="replace")
    assert rc in (0, 70), f"worker did not exit (rc={rc}); log:\n{logtext}"
    _assert_continuous(out_ts, logtext)


def test_stall_watchdog_fires_when_live_source_freezes(tmp_path: Path) -> None:
    """S9-5: the watchdog's real job — a live source that WAS delivering output then
    silently freezes (the sender goes away with no EOS, no bus error). Output flows past
    the mux for several seconds (watchdog stays quiet — it sees progress), the sender is
    frozen (paused, not killed — see ``_LiveUdpSender.freeze``), output stalls, and the
    watchdog quits the worker so the daemon restarts it.

    (A source that is dead from boot is a *different* failure — the pipeline never reaches
    PLAYING, so ``_await_playing`` exits the worker before the watchdog ever arms; that
    restart path is covered by the daemon, not this output-stall watchdog.)"""
    port = _free_udp_port()
    out_ts = tmp_path / "out.ts"
    graph = _filesink_graph(_udpsrc_program_graph(port), out_ts)
    sender = _LiveUdpSender(port, bitrate_kbps=1500, gop=30)
    proc, _, log = _launch_worker(
        tmp_path, graph, out_ts, env_extra={"CIVICCAST_STALL_TIMEOUT_S": "3"}
    )
    try:
        time.sleep(4.0)  # reach PLAYING + flow output past the mux (watchdog sees progress)
        flowing = log.read_text(encoding="utf-8", errors="replace")
        assert "CTRL stall" not in flowing, f"watchdog fired while output was flowing:\n{flowing}"
        sender.freeze()  # live source freezes: no more buffers, no EOS/error
        _wait_for_log(log, "CTRL stall", timeout=15.0)  # watchdog fires ~stall_timeout later
        rc = proc.wait(timeout=20)
    finally:
        _reap(proc)
        sender.stop()
    logtext = log.read_text(encoding="utf-8", errors="replace")
    assert "CTRL stall" in logtext, f"stall watchdog did not fire on a frozen source:\n{logtext}"
    # The exit MUST be non-zero: the daemon's _poll_process only crash-relaunches on a
    # non-zero exit (a clean 0 reads as a deliberate stop). 1 = stall error; 70 = forced
    # teardown backstop — both non-zero. Pins the half of the contract the engine owns.
    assert rc not in (0, None), f"stall exit must be non-zero for daemon relaunch (rc={rc})"


def test_stall_watchdog_does_not_fire_on_healthy_output(tmp_path: Path) -> None:
    """S9-5 fail-closed check: with a SHORT stall_timeout, healthy flowing output must
    NOT trip the watchdog — every output buffer resets it. Runs well past the timeout."""
    rc, out_ts, log = _run_worker(
        tmp_path,
        graphmod.demo_test_graph(nsrc=2),
        commands=["swap 1", "swap 0", "swap 1"],
        await_markers=["CTRL swap 1 applied"],
        produce_window=5.0,  # keep flowing well past the 3s stall_timeout
        env_extra={"CIVICCAST_STALL_TIMEOUT_S": "3"},
    )
    assert "CTRL stall" not in log, f"watchdog FALSE-FIRED on healthy output; log:\n{log}"
    assert rc == 0, f"unclean teardown (rc={rc}); log:\n{log}"
    _assert_continuous(out_ts, log)


def test_content_reload_to_live_udp_ingest_continuity(tmp_path: Path) -> None:
    """Step 9 / S5 live takeover: a content-reload swaps the program leg from a
    scheduled (testsrc) source to a LIVE udpsrc ingest IN PLACE — the exact shape a
    PlayoutSupervisor live takeover drives (request_live_takeover -> _request_reload,
    NOT a phantom 'live' selector pad). The cut to live must commit seamlessly with
    the re-muxed TS continuous (0 CC, no PCR discontinuity) and no encoder restart.
    Ephemeral port (QA-002)."""
    port = _free_udp_port()
    out_ts = tmp_path / "out.ts"
    # Start on a normal scheduled program (testsrc) leg.
    start_graph = _filesink_graph(graphmod.demo_test_graph(nsrc=2), out_ts)
    # The takeover reload payload's program leg (sources[0]) is the live udpsrc ingest.
    reload_path = tmp_path / "takeover.json"
    reload_path.write_text(graphmod.graph_to_json(_udpsrc_program_graph(port)), encoding="utf-8")
    sender = _LiveUdpSender(port, bitrate_kbps=1500, gop=30)
    proc, control, log = _launch_worker(tmp_path, start_graph, out_ts)
    try:
        time.sleep(1.0)  # establish the scheduled program leg on air
        _send(control, f"reload {reload_path}")  # the live takeover
        _wait_for_log(log, "CTRL reload committed", timeout=15.0)
        time.sleep(1.5)  # re-mux a few seconds of the live feed after the cut
        _send(control, "stop")
        rc = proc.wait(timeout=20)
    finally:
        _reap(proc)
        sender.stop()
    logtext = log.read_text(encoding="utf-8", errors="replace")
    assert rc in (0, 70), f"worker did not exit after live takeover (rc={rc}); log:\n{logtext}"
    _assert_reload_committed(logtext)
    _assert_continuous(out_ts, logtext)
