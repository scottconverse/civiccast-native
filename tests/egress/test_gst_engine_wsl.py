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
import reload_policy as reloadpolicy  # noqa: E402

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
            raise RuntimeError(
                f"live UDP sender pipeline failed to reach PLAYING: {pipeline_str!r}"
            )
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
    proc, control, log = _launch_worker(
        tmp_path, graph, out_ts, {"CIVICCAST_RELOAD_TIMEOUT_S": "2"}
    )
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


# --- S15 graphics-overlay leg: station bug + lower-third banner (live compositing) ---


def _graphics_overlay_available() -> bool:
    """True only when the real compositor element the leg builds on is registered.
    The bundled native-Windows runtime ships d3d11compositor and no other compositor
    (confirmed by a real gst-inspect enumeration -- see graph.GraphicsOverlayLeg's
    docstring); this skips cleanly wherever that element is absent instead of
    false-failing, the same pattern _cc_embed_elements_available() uses."""
    from gi.repository import Gst

    Gst.init([])
    from civiccast.egress.gst.graphics_overlay import GRAPHICS_OVERLAY_ELEMENT

    return Gst.ElementFactory.find(GRAPHICS_OVERLAY_ELEMENT) is not None


def _ffmpeg_frame_rgb24(ts: Path, out_raw: Path) -> bytes | None:
    """Grab the first decoded RGB24 frame from ``ts`` via ffmpeg. Returns None (caller
    skips) if ffmpeg isn't installed -- this proof step is a stronger-than-continuity
    check (did the composited pixels actually change), not a hard dependency of the
    suite. Deliberately does NOT pass ``-ss``: mpegtsmux stamps this product's TS with
    a large PTS base (observed start=3600s on a real captured file), and ffmpeg's
    ``-ss`` input-seek against that offset silently produced a zero-frame output on
    this box -- grabbing frame 0 sidesteps that rather than fighting it, and the
    graphics-overlay layers are on screen from the first frame (no fade-in), so frame 0
    is exactly as valid a proof frame as any later one."""
    import shutil

    if shutil.which("ffmpeg") is None:
        return None
    proc = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(ts),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            str(out_raw),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0 or not out_raw.exists():
        return None
    return out_raw.read_bytes()


def test_graphics_overlay_composites_station_bug_and_lower_third(tmp_path: Path) -> None:
    """S15 graphics-overlay leg, live: a station bug PNG + a rendered lower-third
    banner are actually composited onto the program video through a real
    d3d11compositor pipeline (filesrc/decodebin -> d3d11upload -> compositor pad,
    repeat-after-eos holding each still image on screen -> d3d11download -> encode).

    Proof bar: (1) MPEG-TS continuity is clean with the overlay ON -- the same bar
    every other live-engine test in this module clears; (2) DECODED OUTPUT PIXELS at
    the logo corner and the lower-third band differ from the plain program pattern's
    color there -- i.e. this is not just 'the pipeline didn't crash', it's 'the pixels
    on screen actually changed' (skipped, not failed, if ffmpeg isn't installed to
    decode the proof frame -- continuity is still asserted unconditionally)."""
    if not _graphics_overlay_available():
        pytest.skip(
            "d3d11compositor is not registered in this GStreamer runtime -- the "
            "graphics-overlay leg has nothing to build on"
        )
    from civiccast.egress.gst.graphics_overlay import station_bug_and_lower_third_leg

    canvas_w, canvas_h = 640, 360
    logo_path = tmp_path / "logo.png"
    # Fully-opaque bright green square -- easy to tell apart from videotestsrc's SMPTE
    # bars (pattern 0) at the pixel level.
    from civiccast.egress.gst.graphics_overlay import write_rgba_png

    logo_w = logo_h = 80
    write_rgba_png(logo_path, logo_w, logo_h, bytes((0, 255, 0, 255)) * (logo_w * logo_h))

    overlay = station_bug_and_lower_third_leg(
        logo_path=logo_path,
        logo_corner="top-left",
        logo_width=logo_w,
        logo_height=logo_h,
        logo_alpha=1.0,
        canvas_width=canvas_w,
        canvas_height=canvas_h,
        banner_text="CIVICCAST LIVE",
        banner_height=50,
    )

    caps = f"video/x-raw,width={canvas_w},height={canvas_h},framerate=30/1"
    src = graphmod.SourceLeg(
        label="program",
        elements=(
            _E("videotestsrc", props={"is-live": True, "pattern": 0}),  # 0 = SMPTE bars
            _E("capsfilter", props={"caps": caps}),
        ),
    )
    out_ts = tmp_path / "out.ts"
    graph = graphmod.PlayoutGraph(
        sources=(src,),
        encoder=graphmod.encode_chain_specs(
            width=canvas_w, height=canvas_h, fps=30, bitrate_kbps=2000, gop=30
        ),
        mux=_E("mpegtsmux", name="mux"),
        sinks=((_E("queue"), _E("filesink", props={"location": str(out_ts)})),),
        graphics_overlay=overlay,
    )
    proc, control, log = _launch_worker(tmp_path, graph, out_ts)
    try:
        time.sleep(3.0)
        _send(control, "stop")
        rc = proc.wait(timeout=25)
    finally:
        _reap(proc)
    logtext = log.read_text(encoding="utf-8", errors="replace")
    assert rc == 0, f"unclean teardown with graphics overlay on (rc={rc}); log:\n{logtext}"
    assert out_ts.exists() and out_ts.stat().st_size > 0, f"no TS produced; log:\n{logtext}"
    _assert_continuous(out_ts, logtext)

    raw = _ffmpeg_frame_rgb24(out_ts, tmp_path / "frame.raw")
    if raw is None:
        pytest.skip("ffmpeg not installed -- skipping the decoded-pixel compositing proof")
    stride = canvas_w * 3
    assert len(raw) >= stride * canvas_h, f"short decoded frame ({len(raw)} bytes); log:\n{logtext}"

    def pixel(x: int, y: int) -> tuple[int, int, int]:
        off = y * stride + x * 3
        return (raw[off], raw[off + 1], raw[off + 2])

    # Logo corner (well inside the 80x80 green square, away from any encoder-block
    # edge softening): must read as green-dominant, nothing like SMPTE-bar white/blue.
    r, g, b = pixel(30, 30)
    assert g > r and g > b and g > 120, (
        f"logo corner pixel {(r, g, b)} does not read as the green station bug -- "
        f"overlay did not visibly composite; log:\n{logtext}"
    )
    # Lower-third band (near the bottom): must read as the banner's dark-blue bar, not
    # SMPTE bars' bright colors at that same x/y in an un-overlaid frame.
    r2, g2, b2 = pixel(200, canvas_h - 10)
    assert b2 >= r2 and b2 >= g2 and (r2 + g2 + b2) < 400, (
        f"lower-third pixel {(r2, g2, b2)} does not read as the dark banner bar -- "
        f"overlay did not visibly composite; log:\n{logtext}"
    )


def _ffmpeg_last_frame_rgb24(ts: Path, out_raw: Path, *, width: int, height: int) -> bytes | None:
    """Decode ALL frames of ``ts`` to raw RGB24 and return the LAST one's bytes.

    Deliberately does not use ``-ss``/``-sseof`` (see ``_ffmpeg_frame_rgb24``'s own
    comment on why front-seek breaks against this product's TS PTS base) — decoding
    linearly from the start and slicing the final fixed-size frame off the raw output
    sidesteps that the same way frame-0 grabbing does, just at the other end of a
    short capture window. Returns None (caller skips) if ffmpeg isn't installed or
    produced no frames."""
    import shutil

    if shutil.which("ffmpeg") is None:
        return None
    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", str(ts), "-f", "rawvideo", "-pix_fmt", "rgb24", str(out_raw)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    frame_bytes = width * height * 3
    if proc.returncode != 0 or not out_raw.exists():
        return None
    raw = out_raw.read_bytes()
    if len(raw) < frame_bytes:
        return None
    return raw[-frame_bytes:]


def test_content_reload_reapplies_graphics_overlay(tmp_path: Path) -> None:
    """BLOCKER regression (2026-08-30 audit): a content-reload used to rebuild ONLY
    the program source leg (``reload_program``) and silently drop
    ``new_graph.graphics_overlay`` -- an operator's mid-broadcast lower-third text
    update never took effect until a full restart, even though the API + UI
    advertise a content-reload as the way to apply it
    (``civiccast.egress.router.update_graphics_overlay`` /
    ``bridge.graphics_overlay_leg_from_config``, which re-renders a fresh banner PNG
    on every call specifically so a reload can pick it up).

    Proof bar, live, mirroring ``test_graphics_overlay_composites_station_bug_and_
    lower_third``'s decoded-pixel proof: start a channel with a SOLID GREEN
    "lower_third" overlay layer, reload with a new graph whose SAME-NAMED
    "lower_third" layer points at a SOLID RED PNG instead, and assert (1) the
    engine logs the layer's swap actually committing -- not merely that
    ``reload_program`` committed the (unrelated) video source leg -- and (2) the
    decoded LAST frame of the emitted TS reads red at the overlay's screen position,
    not green. This test FAILS on the pre-fix engine: ``reload_graphics_overlay``
    does not exist yet, so mark (1) never appears in the log (a 15s timeout) --
    the reload silently keeps airing the original green layer forever."""
    if not _graphics_overlay_available():
        pytest.skip(
            "d3d11compositor is not registered in this GStreamer runtime -- the "
            "graphics-overlay leg has nothing to build on"
        )
    from civiccast.egress.gst.graphics_overlay import write_rgba_png

    canvas_w, canvas_h = 640, 360
    layer_w = layer_h = 64
    caps = f"video/x-raw,width={canvas_w},height={canvas_h},framerate=30/1"

    def _solid_overlay(color: tuple[int, int, int, int], png_path: Path):
        write_rgba_png(png_path, layer_w, layer_h, bytes(color) * (layer_w * layer_h))
        return graphmod.GraphicsOverlayLeg(
            layers=(
                graphmod.GraphicsOverlayLayer(
                    name="lower_third",  # SAME name as bridge.py's real lower-third layer
                    image_path=str(png_path),
                    xpos=0,
                    ypos=0,
                    width=layer_w,
                    height=layer_h,
                    alpha=1.0,
                ),
            ),
        )

    def _black_program() -> graphmod.SourceLeg:
        return graphmod.SourceLeg(
            label="program",
            elements=(
                _E("videotestsrc", props={"is-live": True, "pattern": 2}),  # 2 = black
                _E("capsfilter", props={"caps": caps}),
            ),
        )

    green_overlay = _solid_overlay((0, 255, 0, 255), tmp_path / "green.png")
    initial_graph = graphmod.PlayoutGraph(
        sources=(_black_program(),),
        encoder=graphmod.encode_chain_specs(
            width=canvas_w, height=canvas_h, fps=30, bitrate_kbps=2000, gop=30
        ),
        mux=_E("mpegtsmux", name="mux"),
        sinks=((_E("queue"), _E("filesink", props={"location": str(tmp_path / "out.ts")})),),
        graphics_overlay=green_overlay,
    )
    red_overlay = _solid_overlay((255, 0, 0, 255), tmp_path / "red.png")
    reload_graph = graphmod.PlayoutGraph(
        sources=(_black_program(),),
        encoder=initial_graph.encoder,
        mux=initial_graph.mux,
        sinks=initial_graph.sinks,
        graphics_overlay=red_overlay,
    )
    reload_path = tmp_path / "reload.json"
    reload_path.write_text(graphmod.graph_to_json(reload_graph), encoding="utf-8")

    out_ts = tmp_path / "out.ts"
    proc, control, log = _launch_worker(tmp_path, initial_graph, out_ts)
    try:
        time.sleep(1.5)  # let some GREEN frames flow before the reload
        _send(control, f"reload {reload_path}")
        _await_markers_if_needed(
            log,
            [
                "CTRL reload committed",
                "CTRL graphics-overlay layer 'lower_third' reload committed",
            ],
        )
        time.sleep(1.5)  # let some RED frames flow after the reload commits
        _send(control, "stop")
        rc = proc.wait(timeout=25)
    finally:
        _reap(proc)
    logtext = log.read_text(encoding="utf-8", errors="replace")
    assert rc == 0, f"unclean teardown after graphics-overlay reload (rc={rc}); log:\n{logtext}"
    assert out_ts.exists() and out_ts.stat().st_size > 0, f"no TS produced; log:\n{logtext}"
    _assert_reload_committed(logtext)
    assert "CTRL graphics-overlay layer 'lower_third' reload committed" in logtext, (
        "content-reload did not re-apply the graphics-overlay leg -- the operator's "
        f"lower-third change would never reach air without a full restart; log:\n{logtext}"
    )
    _assert_continuous(out_ts, logtext)

    raw = _ffmpeg_last_frame_rgb24(
        out_ts, tmp_path / "last_frame.raw", width=canvas_w, height=canvas_h
    )
    if raw is None:
        pytest.skip("ffmpeg not installed -- skipping the decoded-pixel reload proof")
    stride = canvas_w * 3

    def pixel(x: int, y: int) -> tuple[int, int, int]:
        off = y * stride + x * 3
        return (raw[off], raw[off + 1], raw[off + 2])

    r, g, b = pixel(30, 30)
    assert r > g and r > b and r > 120, (
        f"final frame pixel {(r, g, b)} does not read as the RELOADED red overlay -- "
        f"the reload did not actually change what's on screen; log:\n{logtext}"
    )


def test_content_reload_deletes_the_superseded_banner_png_not_the_live_one(
    tmp_path: Path,
) -> None:
    """R3 regression (2026-08-31): round-1's per-uuid banner filename fix
    (``bridge.graphics_overlay_leg_from_config``) stopped a concurrent build from
    reading a partial PNG, but nothing then deleted the OLD banner a content-reload
    superseded -- an unbounded per-start()/per-reload PNG leak on a 24/7 station,
    on the same volume as recordings/HLS/the DB.

    Live proof, real GStreamer: start a channel with a real
    ``graphics-overlay-lower-third.<uuid>.png``-named banner (the exact pattern
    ``GstPlayoutEngine._delete_stale_overlay_png`` gates deletion on), reload with a
    SECOND uniquely-named banner for the SAME layer name, and once the reload's
    engine-side commit log line lands, assert:

    1. the OLD banner file is gone (the swap point -- ``_delete_stale_overlay_png``
       -- deleted it once ``_dispose_overlay_layer_pad`` proved the old chain was
       off-air), and
    2. the NEW (now on-air) banner file still exists (the swap point must never
       delete the file the live pipeline's filesrc has open).

    This fails on the pre-fix engine: neither banner is ever deleted, so both
    remain on disk after the reload commits."""
    if not _graphics_overlay_available():
        pytest.skip(
            "d3d11compositor is not registered in this GStreamer runtime -- the "
            "graphics-overlay leg has nothing to build on"
        )
    from civiccast.egress.gst.graphics_overlay import write_rgba_png

    canvas_w, canvas_h = 640, 360
    layer_w = layer_h = 64
    caps = f"video/x-raw,width={canvas_w},height={canvas_h},framerate=30/1"

    def _banner_leg(color: tuple[int, int, int, int]) -> tuple[graphmod.GraphicsOverlayLeg, Path]:
        # Exactly bridge.py's real per-call filename shape -- the pattern
        # ``_STALE_BANNER_PNG_RE``/``_delete_stale_overlay_png`` gate deletion on.
        png_path = tmp_path / f"graphics-overlay-lower-third.{uuid.uuid4().hex}.png"
        write_rgba_png(png_path, layer_w, layer_h, bytes(color) * (layer_w * layer_h))
        leg = graphmod.GraphicsOverlayLeg(
            layers=(
                graphmod.GraphicsOverlayLayer(
                    name="lower_third",
                    image_path=str(png_path),
                    xpos=0,
                    ypos=0,
                    width=layer_w,
                    height=layer_h,
                    alpha=1.0,
                ),
            ),
        )
        return leg, png_path

    def _black_program() -> graphmod.SourceLeg:
        return graphmod.SourceLeg(
            label="program",
            elements=(
                _E("videotestsrc", props={"is-live": True, "pattern": 2}),  # 2 = black
                _E("capsfilter", props={"caps": caps}),
            ),
        )

    green_overlay, green_path = _banner_leg((0, 255, 0, 255))
    initial_graph = graphmod.PlayoutGraph(
        sources=(_black_program(),),
        encoder=graphmod.encode_chain_specs(
            width=canvas_w, height=canvas_h, fps=30, bitrate_kbps=2000, gop=30
        ),
        mux=_E("mpegtsmux", name="mux"),
        sinks=((_E("queue"), _E("filesink", props={"location": str(tmp_path / "out.ts")})),),
        graphics_overlay=green_overlay,
    )
    red_overlay, red_path = _banner_leg((255, 0, 0, 255))
    reload_graph = graphmod.PlayoutGraph(
        sources=(_black_program(),),
        encoder=initial_graph.encoder,
        mux=initial_graph.mux,
        sinks=initial_graph.sinks,
        graphics_overlay=red_overlay,
    )
    reload_path = tmp_path / "reload.json"
    reload_path.write_text(graphmod.graph_to_json(reload_graph), encoding="utf-8")

    assert green_path.exists() and red_path.exists(), "both banners must exist before the reload"

    out_ts = tmp_path / "out.ts"
    proc, control, log = _launch_worker(tmp_path, initial_graph, out_ts)
    try:
        time.sleep(1.5)  # let some GREEN frames flow before the reload
        _send(control, f"reload {reload_path}")
        _await_markers_if_needed(
            log,
            [
                "CTRL reload committed",
                "CTRL graphics-overlay layer 'lower_third' reload committed",
            ],
        )
        time.sleep(1.0)  # give the main-loop commit's file deletion time to land
        _send(control, "stop")
        rc = proc.wait(timeout=25)
    finally:
        _reap(proc)
    logtext = log.read_text(encoding="utf-8", errors="replace")
    assert rc == 0, f"unclean teardown after graphics-overlay reload (rc={rc}); log:\n{logtext}"
    assert "CTRL graphics-overlay layer 'lower_third' reload committed" in logtext, (
        f"reload never committed -- can't assert cleanup happened; log:\n{logtext}"
    )

    assert not green_path.exists(), (
        "the SUPERSEDED (green) banner PNG must be deleted once the reload's new "
        f"layer committed -- it leaked instead; log:\n{logtext}"
    )
    assert red_path.exists(), (
        "the NEW (red, now on-air) banner PNG must NEVER be deleted by its own "
        f"commit -- it was wrongly removed; log:\n{logtext}"
    )


def test_graphics_overlay_disabled_matches_existing_no_overlay_behavior(tmp_path: Path) -> None:
    """Regression bar: a graph with ``graphics_overlay=None`` (the default -- every
    pre-existing caller in this codebase) must build and run exactly as it did before
    this leg existed. ``demo_test_graph`` never sets the field, so this is the same
    call shape ``test_build_play_teardown_clean``/``test_swap_role_continuity`` already
    exercise -- pinned here explicitly, next to the overlay-ON test, so a future reader
    sees the ON/OFF pair together."""
    graph = graphmod.demo_test_graph(nsrc=2)
    assert graph.graphics_overlay is None
    rc, out_ts, log = _run_worker(tmp_path, graph, commands=["swap 1"], produce_window=1.0)
    assert rc == 0, f"unclean teardown with graphics overlay off (rc={rc}); log:\n{log}"
    _assert_continuous(out_ts, log)


# --- boundary-aligned plan rollover (deferred switch) --------------------------------


def _finite_program_av_graph(*, seconds: float = 5.0):
    """Production-shape A/V graph whose PROGRAM leg (source 0) is FINITE and
    SEGMENT-TIMED -- the two properties a real schedule-derived program leg has and
    the ``_av_demo_graph`` legs do not.

    * finite (``num-buffers``) so the leg reaches its own natural EOS: that EOS is
      the boundary the deferred rollover switches at, and the event that used to run
      straight through the still-active input-selector into the mux and take the
      whole worker down.
    * ``is-live=false`` so its buffers are stamped from ITS OWN segment starting at
      running time 0 (exactly like ``filesrc ! decodebin``), not from the pipeline
      clock -- which is what makes the running-time rebase necessary and testable. A
      live source would already be on the pipeline's timebase and, per
      ``graph.source_leg_is_clock_timed``, is deliberately neither held nor rebased.

    Pacing comes from the SINK (see ``_paced_filesink_graph``), the way ``udpsink
    sync=true`` paces a real channel -- not from the legs.
    """
    video_buffers = int(seconds * 30)
    audio_buffers = int(seconds * 48000 / 1024) + 1
    program = graphmod.SourceLeg(
        label="program",
        elements=(
            _E(
                "videotestsrc",
                props={"is-live": False, "pattern": 0, "num-buffers": video_buffers},
            ),
            _E("capsfilter", props={"caps": _CAPS}),
        ),
        audio=(
            _E("audiotestsrc", props={"is-live": False, "wave": 0, "num-buffers": audio_buffers}),
            _E("audioconvert"),
            _E("audioresample"),
            _E("capsfilter", props={"caps": _ACAPS}),
        ),
    )
    base = _av_demo_graph(nsrc=2)
    return graphmod.PlayoutGraph(
        sources=(program, base.sources[1]),
        encoder=base.encoder,
        audio_encoder=base.audio_encoder,
        mux=base.mux,
        sinks=base.sinks,
    )


def _segment_timed_reload_graph(pattern: int = 18):
    """A reload payload that is SEGMENT-TIMED and endless -- the rollover successor.
    Endless so it is still producing when the test stops the worker; segment-timed so
    ``reload_program`` takes the hold-and-rebase path under test."""
    program = graphmod.SourceLeg(
        label="program",
        elements=(
            _E("videotestsrc", props={"is-live": False, "pattern": pattern}),
            _E("capsfilter", props={"caps": _CAPS}),
        ),
        audio=(
            _E("audiotestsrc", props={"is-live": False, "wave": 8}),
            _E("audioconvert"),
            _E("audioresample"),
            _E("capsfilter", props={"caps": _ACAPS}),
        ),
    )
    base = _av_demo_graph(nsrc=2)
    return graphmod.PlayoutGraph(
        sources=(program, base.sources[1]),
        encoder=base.encoder,
        audio_encoder=base.audio_encoder,
        mux=base.mux,
        sinks=base.sinks,
    )


def _paced_filesink_graph(graph, out_ts: Path):
    """``_filesink_graph`` plus a clock sync point in front of the filesink.

    A ``filesink`` never syncs, so a graph of SEGMENT-TIMED (non-live) legs behind one
    free-runs: the program would blast through its whole duration in a fraction of the
    wall time and there would be no boundary left to aim a reload at. Real channels are
    paced at the sink (``udpsink sync=true``); ``identity sync=true`` is that same
    pacing with a file on the end, so the leg timing under test is production timing."""
    sinks = (
        (
            _E("queue"),
            _E("identity", props={"sync": True}),
            _E("filesink", props={"location": str(out_ts)}),
        ),
    )
    return graphmod.PlayoutGraph(
        sources=graph.sources,
        encoder=graph.encoder,
        audio_encoder=graph.audio_encoder,
        mux=graph.mux,
        sinks=sinks,
        captions=graph.captions,
        secondary_audio=graph.secondary_audio,
    )


def _ts_tail(path: Path, offset: int, dest: Path) -> Path:
    """Write the 188-byte-aligned TS packets of ``path`` from ``offset`` on to
    ``dest``, so the analyzer can be pointed at only what was emitted AFTER the
    boundary."""
    data = path.read_bytes()
    start = min(len(data), ((offset + 187) // 188) * 188)
    while start < len(data) and data[start] != 0x47:
        start += 1
    dest.write_bytes(data[start:])
    return dest


def _pes_pts_backward_steps(path: Path, *, tolerance_seconds: float = 0.5) -> dict[int, int]:
    """Per elementary PID, how many times the PES PTS steps BACKWARD by more than
    ``tolerance_seconds``.

    ``_analyze_ts`` above reads the PCR out of the adaptation field, which is the
    right check for the transport clock but is not the whole timestamp story: at a
    source handover the mux re-derives the video PCR, so a leg that restarted at
    running time 0 can leave the PCR looking clean while the AUDIO PID's PTS steps
    straight back to the beginning. TSDuck's own ``analyze`` plugin reports exactly
    that as ``pts-leap`` on the audio PID (verified on this branch: 1 leap without the
    running-time rebase, 0 with it); this is the same check, in-tree, so the rollover
    test does not depend on TSDuck being installed.

    Small backward steps are normal and NOT counted: B-frame reordering means
    presentation timestamps legitimately go out of order by a frame or two."""
    data = path.read_bytes()
    tolerance = int(tolerance_seconds * 90_000)  # PTS ticks are 90 kHz
    wrap = 1 << 33
    last: dict[int, int] = {}
    backward: dict[int, int] = {}
    for i in range(0, len(data) - 187, 188):
        if data[i] != 0x47:
            continue
        pid = ((data[i + 1] & 0x1F) << 8) | data[i + 2]
        if pid < 0x40 or pid == 0x1FFF:
            continue
        if not data[i + 1] & 0x40:  # payload_unit_start_indicator: a PES header starts here
            continue
        afc = (data[i + 3] >> 4) & 0x3
        offset = i + 4
        if afc in (2, 3):
            offset += 1 + data[i + 4]
        if afc == 2 or offset + 14 > i + 188:
            continue
        if data[offset : offset + 3] != b"\x00\x00\x01":  # PES start code prefix
            continue
        if not data[offset + 7] & 0x80:  # PTS_DTS_flags: no PTS present
            continue
        b = data[offset + 9 : offset + 14]
        pts = (
            ((b[0] >> 1) & 0x07) << 30
            | b[1] << 22
            | ((b[2] >> 1) & 0x7F) << 15
            | b[3] << 7
            | ((b[4] >> 1) & 0x7F)
        )
        previous = last.get(pid)
        if previous is not None:
            delta = pts - previous
            if delta < -(wrap // 2):  # 33-bit wrap, not a leap
                delta += wrap
            if delta < -tolerance:
                backward[pid] = backward.get(pid, 0) + 1
        last[pid] = pts
    return backward


def test_deferred_rollover_switches_at_the_boundary_without_eos(tmp_path: Path) -> None:
    """B3 / hostile-review (a)(b)(c): a ``switch_at_end_of_current`` reload must hand
    over AT the outgoing leg's own end without ever producing a pipeline EOS, without a
    timestamp jump, and with BOTH selectors switched.

    Before the boundary-aligned switch this scenario was a deterministic channel kill.
    The engine watched the outgoing leg's video pad and returned ``PAD_PROBE_REMOVE``
    for its EOS, which does not drop the event: ``input-selector`` forwards an ACTIVE
    pad's EOS downstream, so it reached the encoder, then ``mpegtsmux``, then the bus,
    and ``_on_bus`` quit the run loop -- strictly BEFORE the ``GLib.idle_add`` commit
    could run. The worker exited and the daemon wrote STOPPED, at every plan boundary.
    The audio selector's pad was never watched at all.

    Asserted here, against a real GStreamer:
      * the worker is STILL RUNNING a full second past the boundary (the regression
        assertion -- it used to be gone by then);
      * the reload committed AND logged the running-time rebase;
      * TS kept being written after the boundary, and the packets emitted after it
        carry BOTH elementary PIDs -- i.e. the audio selector switched too, not just
        video (an unswitched audio selector goes silent behind an EOS-latched mux pad);
      * continuity across the WHOLE capture: zero CC errors and zero backward PCR
        steps, which is the timestamp-jump check -- a leg that started again at running
        time 0 would step the PCR back by the whole uptime;
      * a clean ``stop`` teardown afterwards (rc 0).
    """
    program_seconds = 5.0
    out_ts = tmp_path / "out.ts"
    graph = _paced_filesink_graph(_finite_program_av_graph(seconds=program_seconds), out_ts)
    reload_path = tmp_path / f"rollover{reloadpolicy.DEFERRED_SWITCH_SUFFIX}"
    reload_path.write_text(
        graphmod.graph_to_json(_segment_timed_reload_graph(18)), encoding="utf-8"
    )
    assert reloadpolicy.reload_switch_is_deferred(str(reload_path)), (
        "the harness must request the DEFERRED switch mode, else this test proves nothing"
    )

    proc, control, log = _launch_worker(tmp_path, graph, out_ts)
    try:
        # Arm the rollover early -- well before the boundary, exactly as automation's
        # boundary-aligned trigger does. The new leg must WAIT, not cut in.
        time.sleep(1.0)
        _send(control, f"reload {reload_path}")
        _wait_for_log(log, "CTRL reload committed", timeout=program_seconds + 15.0)
        committed_at_size = out_ts.stat().st_size
        # A full second past the boundary the worker must still be alive: this is the
        # exact interval in which the pre-fix engine had already exited on the
        # forwarded EOS.
        time.sleep(1.0)
        assert proc.poll() is None, (
            "worker exited at the rollover boundary (a pipeline EOS escaped the switch); "
            f"log:\n{log.read_text(encoding='utf-8', errors='replace')}"
        )
        time.sleep(1.0)
        _send(control, "stop")
        returncode = proc.wait(timeout=25)
    finally:
        _reap(proc)
    text = log.read_text(encoding="utf-8", errors="replace")

    assert returncode == 0, f"unclean teardown after a boundary rollover (rc={returncode});\n{text}"
    _assert_reload_committed(text)
    assert "boundary switch rebased to running time" in text, (
        f"the deferred switch did not rebase the new leg's running time;\n{text}"
    )
    after = out_ts.stat().st_size
    assert after > committed_at_size, (
        "no TS was written after the boundary -- output stopped at the handover;\n" + text
    )

    # Everything emitted AFTER the boundary must still carry video AND audio: a
    # video-only switch leaves the audio selector on the EOS'd old pad.
    tail = _ts_tail(out_ts, committed_at_size, tmp_path / "tail.ts")
    tail_stats = _analyze_ts(tail)
    tail_elementary = [pid for pid in tail_stats["pids"] if pid >= 0x40]
    assert len(tail_elementary) >= 2, (
        f"only {tail_elementary} carried packets after the boundary -- the audio "
        f"selector did not switch with the video one;\n{text}"
    )

    stats = _assert_continuous(out_ts, text, require_audio_pid=True)
    assert stats["pcr_samples"] > 0, f"no PCR samples to check for a jump;\n{text}"
    assert {"video", "audio"} <= _ffprobe_codec_types(out_ts), (
        f"ffprobe did not report both a video and an audio stream after the rollover;\n{text}"
    )

    # The timestamp-jump check with teeth. The PCR check above passes even WITHOUT the
    # running-time rebase -- the mux re-derives the video PCR across the handover -- but
    # the audio PID's PTS steps straight back to the start. Measured on this branch
    # against the bundled GStreamer 1.28.5 and confirmed independently by the kit's own
    # TSDuck: 1 backward step (tsp analyze reports "pts-leap": 1 on the audio PID) with
    # the rebase disabled, 0 with it.
    backward = _pes_pts_backward_steps(out_ts)
    assert backward == {}, (
        f"PES PTS stepped backward on PID(s) {[hex(pid) for pid in backward]} -- the new "
        f"leg was not rebased onto the outgoing leg's end;\n{text}"
    )


# --- item 85: multi-segment concat-playlist reload commit (sandbox soaks 12/14/15) --


def _write_short_av_clip(path: Path, *, seconds: float = 0.4, pattern: int = 0) -> None:
    """Encode a short, REAL, finite A/V clip (matroska, H.264 + Opus) via a
    one-shot ``Gst.parse_launch`` EOS-driven pipeline. ``gi``/``Gst`` is already
    available in this test PROCESS (not just the worker subprocess) -- see
    ``_linux_gi_available``/``_windows_bundled_gstreamer_available`` above, both
    of which already do a live ``import gi`` to answer their capability check.

    The filesink's ``location`` is set via ``set_property`` AFTER parsing,
    never embedded in the ``Gst.parse_launch`` string -- a Windows absolute path
    contains a drive-letter colon, and this repository has already hit exactly
    that class of bug once (``caption_proof._escape_movie_path``, a single-escaped
    drive colon splitting a ``lavfi movie=`` filename); side-stepping the parser
    entirely for this property removes the whole hazard rather than re-escaping it.
    """
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    video_buffers = max(1, int(seconds * 30))
    audio_buffers = max(1, int(seconds * 48000 / 1024) + 1)
    encoder = " ".join(_h264_sender_encoder_args())
    desc = (
        f"videotestsrc is-live=false pattern={pattern} num-buffers={video_buffers} ! "
        f"{_CAPS} ! {encoder} mux. "
        f"audiotestsrc is-live=false wave=0 num-buffers={audio_buffers} ! {_ACAPS} ! "
        # avenc_aac (gst-libav), not opusenc -- matches graph.audio_encode_specs'
        # own default and is confirmed present in the bundled native runtime
        # closure (opusenc is not).
        f"audioconvert ! audioresample ! avenc_aac bitrate=128000 ! aacparse ! mux. "
        f"matroskamux name=mux ! filesink name=sink"
    )
    pipeline = Gst.parse_launch(desc)
    pipeline.get_by_name("sink").set_property("location", str(path))
    bus = pipeline.get_bus()
    if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
        pipeline.set_state(Gst.State.NULL)
        raise RuntimeError(f"failed to start the test-clip encoder pipeline for {path}")
    try:
        msg = bus.timed_pop_filtered(
            int(15 * Gst.SECOND), Gst.MessageType.EOS | Gst.MessageType.ERROR
        )
        if msg is None:
            raise RuntimeError(f"test-clip encoder for {path} produced no EOS within 15s")
        if msg.type == Gst.MessageType.ERROR:
            err, debug = msg.parse_error()
            raise RuntimeError(f"test-clip encoder for {path} errored: {err} ({debug})")
    finally:
        pipeline.set_state(Gst.State.NULL)
        pipeline.get_state(int(5 * Gst.SECOND))
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(f"test-clip encoder for {path} produced no (or an empty) file")


def _multi_segment_playlist_reload_graph(clip_paths: list[Path]):
    """A reload payload whose PROGRAM leg is a real ``concat`` ``PlaylistLeg`` of
    ``len(clip_paths)`` (>=4 in the test below) short, REAL A/V segments -- the
    exact production shape ``bridge.graph_from_config`` builds for a real
    schedule-derived program leg (``filesrc ! decodebin ! videoconvert !
    videoscale ! videorate ! capsfilter`` per segment, one shared ``audio_tail``
    concatenating each clip's decoded audio into the audio selector). Item 85's
    sandbox wedges were measured against exactly this shape -- a real multi-
    segment playlist, not a single bare ``videotestsrc`` leg -- so this is the
    scenario the commit-ordering fix has to prove itself against, with MULTIPLE
    internal concat segment-boundaries churning inside the held leg while it
    waits for the outgoing leg's own end, not just one clean first buffer."""
    program = graphmod.PlaylistLeg(
        label="program",
        subchains=tuple(
            (
                _E("filesrc", props={"location": str(clip)}),
                _E("decodebin"),
                _E("videoconvert"),
                _E("videoscale"),
                _E("videorate"),
                _E("capsfilter", props={"caps": _CAPS}),
            )
            for clip in clip_paths
        ),
        audio_tail=(
            _E("audioconvert"),
            _E("audioresample"),
            _E("capsfilter", props={"caps": _ACAPS}),
        ),
    )
    base = _av_demo_graph(nsrc=2)
    return graphmod.PlayoutGraph(
        sources=(program, base.sources[1]),
        encoder=base.encoder,
        audio_encoder=base.audio_encoder,
        mux=base.mux,
        sinks=base.sinks,
    )


def test_deferred_rollover_commits_with_a_multi_segment_concat_playlist_reload(
    tmp_path: Path,
) -> None:
    """Item 85 (sandbox runs 12/14/15): a ``switch_at_end_of_current`` reload whose
    payload is a REAL multi-segment concat ``PlaylistLeg`` (>=4 short real A/V
    clips, decoded via ``filesrc ! decodebin`` each -- the production shape,
    unlike ``test_deferred_rollover_switches_at_the_boundary_without_eos`` above,
    which uses a single bare ``videotestsrc`` leg) must still COMMIT within a
    bounded time. Before item 85's engine.py fix, the measured failure was a
    permanent wedge: the worker's last log line was "CTRL reload: boundary switch
    rebased...", the process stayed alive, and "CTRL reload committed" never
    appeared in any of seven soaks.

    The module's own ``_hard_hang_timeout`` autouse fixture (120s,
    ``faulthandler.dump_traceback_later``) already arms the every-test safety net
    this scenario asks for; a wedge here still trips that net and dumps every
    thread's live stack, it just does so at the module's shared bound rather than
    a bespoke one for this single test."""
    program_seconds = 4.0
    out_ts = tmp_path / "out.ts"
    graph = _paced_filesink_graph(_finite_program_av_graph(seconds=program_seconds), out_ts)

    clip_paths = [tmp_path / f"segment-{i}.mkv" for i in range(4)]
    for i, clip in enumerate(clip_paths):
        _write_short_av_clip(clip, seconds=0.4, pattern=i % 2)

    reload_path = tmp_path / f"multiseg-rollover{reloadpolicy.DEFERRED_SWITCH_SUFFIX}"
    reload_path.write_text(
        graphmod.graph_to_json(_multi_segment_playlist_reload_graph(clip_paths)),
        encoding="utf-8",
    )
    assert reloadpolicy.reload_switch_is_deferred(str(reload_path)), (
        "the harness must request the DEFERRED switch mode, else this test proves nothing"
    )

    proc, control, log = _launch_worker(tmp_path, graph, out_ts)
    try:
        time.sleep(1.0)
        _send(control, f"reload {reload_path}")
        _wait_for_log(log, "CTRL reload committed", timeout=program_seconds + 30.0)
        text = log.read_text(encoding="utf-8", errors="replace")
        # The item 85 staged commit prints, in order -- proves the commit ran
        # main's own ordering (switching announced, THEN the active-pad switch
        # + hold-probe release actually happen, THEN the old leg is disposed)
        # rather than just happening to still reach "committed" some other way.
        for marker in (
            "CTRL reload: switching selector",
            "CTRL reload: holds released",
            "CTRL reload: old leg disposed",
            "CTRL reload committed",
        ):
            assert marker in text, f"missing staged commit log line {marker!r};\n{text}"
        assert text.index("CTRL reload: switching selector") < text.index(
            "CTRL reload: holds released"
        )
        assert text.index("CTRL reload: holds released") < text.index(
            "CTRL reload: old leg disposed"
        )
        assert text.index("CTRL reload: old leg disposed") < text.index("CTRL reload committed")
        # Regression assertion (mirrors the single-segment test above): the
        # worker must still be alive a full second past the boundary, not
        # freshly wedged with the commit log line printed just before it hung.
        time.sleep(1.0)
        assert proc.poll() is None, (
            f"worker exited right after committing a multi-segment reload;\nlog:\n{text}"
        )
        _send(control, "stop")
        returncode = proc.wait(timeout=25)
    finally:
        _reap(proc)

    assert returncode == 0, (
        f"unclean teardown after a multi-segment concat-playlist reload (rc={returncode})"
    )
