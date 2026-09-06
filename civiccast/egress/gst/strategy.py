# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""GstPlayoutStrategy — the EncoderStrategy that drives the GStreamer engine.

Implements the existing egress ``EncoderStrategy`` Protocol so the daemon can run
the GStreamer engine in place of the ffmpeg ``ConcatEncoderStrategy``:

    EgressDaemon(encoder_strategy=GstPlayoutStrategy())

``start()`` builds a ``PlayoutGraph`` from the channel's config + active source plan,
serializes it to JSON, and launches a per-channel **worker subprocess** (so the
daemon's pid / poll / reap model — issue #161 — applies unchanged). The returned
process exposes ``pid`` / ``poll`` / ``terminate`` (``FfmpegProcessHandle`` is a
generic ``Popen`` wrapper). The worker is launched by file path so it needs only
``gi`` + the sibling gst modules, not the full civiccast package.
"""

from __future__ import annotations

import base64
import contextlib
import json
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, ClassVar, Protocol, cast

from civiccast.captions.tap import build_audio_tap_plan
from civiccast.egress.encoder_strategy import EncoderStartRequest, EncoderStartResult
from civiccast.egress.errors import EncoderUnavailableError
from civiccast.egress.gst.bridge import (
    CaptionEmbedRequest,
    graph_from_config,
    graphics_overlay_leg_from_config,
)
from civiccast.egress.gst.encoder_probe import (
    CG_OVERLAY_ELEMENT,
    decide_encoder,
    probe_element_registered,
    probe_hardware_encoder,
)
from civiccast.egress.gst.graph import AudioTapLeg, PlayoutGraph, graph_to_json
from civiccast.egress.gst.reload_policy import reload_sidecar_suffix
from civiccast.native.supervisor.replay import (
    ChannelReplay,
    LostAckOutcome,
    Verb,
)
from civiccast.native.supervisor.replay import (
    Command as ReplayCommand,
)
from civiccast.stream._ffmpeg import FfmpegProcessHandle

logger = logging.getLogger(__name__)

WorkerLauncher = Callable[[list[str], Path, Path], object]

_WORKER_PATH = str(Path(__file__).resolve().parent / "worker.py")
_TRUTHY = {"1", "true", "yes", "on"}
# Opt-out semantics for the seamless-reload default (see _SEAMLESS_RELOAD_ENV_VAR
# below): any of these values, set on that env var, disables the default-ON behavior.
_FALSY = {"0", "false", "no", "off"}

# -- D2 Windows worker-pipe seam (spec-supervisor D2, design.md sec4) --------------
#
# On native Windows the POSIX FIFO (worker.py:34-39, os.mkfifo -- unavailable on
# Windows) is replaced by a per-channel duplex named pipe
# ``\\.\pipe\civiccast-worker-<channel_id>``. The STRATEGY is the pipe SERVER
# (creates it with an explicit SDDL -- SYSTEM + the service identity only,
# tighter than the FIFO it replaces); the worker connects as CLIENT. The
# ``parse_control_line`` grammar is UNCHANGED; only the transport gains a
# versioned, acknowledged envelope:
#
#   strategy -> worker  {"v":1,"id":"<uuid>","cmd":"<existing control line>"}
#   worker -> strategy  {"v":1,"id":"<same>","result":"applied"|"error","detail":...}
#
# F1 redesign (2026-09-06): for the "reload" verb specifically, "applied" above
# is really "armed" (accepted; the new leg is building/prerolling) -- the
# eventual commit/abort is reported out-of-band via reload-status.json
# (worker.py's _write_reload_status / daemon._poll_reload_settlement), never
# by blocking this ack. See _reload_ack_timeout_s's docstring for why.
#
# The per-verb replay policy (reload/swap = at-least-once desired-state reissue;
# caption = at-most-once, never replayed; stop = terminal, suppresses replay) is
# NOT reimplemented here -- it is the pure, already-tested
# ``civiccast.native.supervisor.replay`` module; this file only carries the
# envelope wire format, the pending-ack bookkeeping, and (Windows only) the real
# named-pipe transport. The Linux FIFO path (``send_command`` et al. below) is
# untouched by any of this.

WORKER_PIPE_FRAME_CAP = 16 * 1024  # bytes; D7-class hardening extended to worker pipes
_WORKER_PIPE_NAME_PREFIX = r"\\.\pipe\civiccast-worker-"
_WORKER_PIPE_ACK_TIMEOUT_S = 5.0


def _reload_ack_timeout_s() -> float:
    """Bound for a ``reload`` command's ack wait.

    F1 redesign (coordinator hostile review, 2026-09-06, superseding item 4's
    original design): item 4 made the worker's ``reload`` ack wait for the
    reload to fully COMMIT or ABORT, which for a DEFERRED/boundary-aligned
    switch (an automation-driven ON_AIR extension -- see
    ``reload_policy.should_defer_switch``) can take up to
    ``defer_switch_timeout_s`` (900s default) -- so item 4 widened this bound
    to the worker's own (immediate-switch) ``reload_timeout_s`` plus a margin,
    which was STILL wrong for the deferred case: a correctly-armed reload with
    a long natural lead would blow straight through even that widened bound,
    the strategy would report a lost ack, and the daemon would terminate a
    perfectly healthy worker.

    The ack now means only "armed" (``worker.py``'s ``_dispatch_control_with_ack``
    docstring) -- the worker accepted the command and the new leg is building/
    prerolling, or the build failed synchronously -- which is fast, like every
    other verb's ack. The eventual settle outcome is reported out-of-band
    (``reload-status.json``, polled by ``EgressDaemon._poll_reload_settlement``)
    instead of riding this ack at all. This function is therefore back to the
    SAME small default every other verb uses -- kept as its own named function
    (rather than inlining ``_WORKER_PIPE_ACK_TIMEOUT_S`` at the call site) so a
    future reload-specific tuning need has a single seam to change, without
    reintroducing today's mistake of conflating "acked" with "settled"."""
    return _WORKER_PIPE_ACK_TIMEOUT_S


def worker_pipe_name(channel_id: str) -> str:
    """The per-channel D2 worker control pipe name (design.md sec4)."""
    return f"{_WORKER_PIPE_NAME_PREFIX}{channel_id}"


def encode_envelope_command(command: ReplayCommand) -> str:
    """strategy -> worker envelope: ``{"v":1,"id":<uuid>,"cmd":"<control line>"}``."""
    return json.dumps({"v": 1, "id": command.id, "cmd": command.line})


def decode_envelope_ack(raw: str) -> tuple[str, str, str | None]:
    """worker -> strategy envelope: ``{"v":1,"id":<same>,"result":..., "detail":...}``.

    Returns ``(id, result, detail)``. Raises ``ValueError`` on a missing/mismatched
    version or a missing required field -- a malformed frame, never silently
    accepted as version 1."""
    obj = json.loads(raw)
    if obj.get("v") != 1:
        raise ValueError(f"unsupported worker-pipe envelope version: {obj.get('v')!r}")
    return str(obj["id"]), str(obj["result"]), obj.get("detail")


class DuplexTransport(Protocol):
    """Structural contract a D2 worker-pipe transport must satisfy: a real Win32
    named pipe (:class:`WindowsWorkerPipeServer`) or a test's fake in-memory
    transport. Deliberately minimal -- line-oriented read/write, non-blocking
    reads (``None`` = nothing available right now)."""

    def write_line(self, text: str) -> bool: ...

    def read_line(self) -> str | None: ...


class WorkerPipeServer(DuplexTransport, Protocol):
    """A :class:`DuplexTransport` that also owns the pipe lifecycle the
    :class:`_WindowsPipeChannel` drives (create the instance, block until the
    worker connects, release the handle). The real
    :class:`WindowsWorkerPipeServer` satisfies this; so does a test's fake
    in-memory server. Kept distinct from ``DuplexTransport`` so
    :class:`WorkerPipeSession` (which only ever reads/writes) still accepts any
    plain transport, while :class:`_WindowsPipeChannel` (which also calls
    ``create``/``accept``/``close``) has a precise contract to inject against."""

    def create(self) -> None: ...

    def accept(self) -> None: ...

    def close(self) -> None: ...


class WorkerPipeSession:
    """Strategy-side D2 policy engine for one channel's worker-pipe seam
    (design.md sec4): sends the versioned envelope, tracks pending acks, and
    applies the per-verb replay policy (``civiccast.native.supervisor.replay``) on
    ack loss / reconnect. Platform-agnostic -- driven by any :class:`DuplexTransport`,
    which is what lets the falsification tests exercise this against a fake
    in-memory transport with no real pipe."""

    def __init__(self, channel_id: str, transport: DuplexTransport) -> None:
        self.channel_id = channel_id
        self._transport = transport
        self._replay = ChannelReplay(channel_id=channel_id)
        self._pending: dict[str, ReplayCommand] = {}

    @property
    def stopping(self) -> bool:
        return self._replay.stopping

    @property
    def dropped_captions(self) -> list[str]:
        return self._replay.dropped_captions

    def send(self, verb: Verb, line: str) -> str:
        """Send one NEW command over the envelope (fresh uuid); returns its id.

        Convenience for callers that do not need to register a waiter between
        allocating the id and writing it: ``dispatch(new_command(...))``. The
        acknowledged Windows path (:class:`_WindowsPipeChannel`) calls the two
        halves separately so the channel waiter is registered BEFORE the write."""
        return self.dispatch(self.new_command(verb, line))

    def new_command(
        self,
        verb: Verb,
        line: str,
        *,
        command_id: str | None = None,
    ) -> ReplayCommand:
        """Allocate a fresh command id, record its intent as desired state
        (``ChannelReplay.record_sent``), and mark it pending -- WITHOUT writing to
        the transport. Splitting this out of the write (see :meth:`dispatch`) is
        the CC-WS5-006 ack-ordering fix: the caller can register its ack waiter
        against ``command.id`` before the write happens, so an immediate ack can
        never be read+correlated before the waiter exists."""
        resolved_id = str(uuid.uuid4()) if command_id is None else command_id.strip()
        if not resolved_id:
            raise ValueError("worker-pipe command id must not be empty")
        if resolved_id in self._pending:
            raise ValueError(f"worker-pipe command id is already pending: {resolved_id}")
        command = ReplayCommand(id=resolved_id, verb=verb, line=line)
        self._replay.record_sent(command)
        self._pending[command.id] = command
        return command

    def dispatch(self, command: ReplayCommand) -> str:
        """Write an already-allocated command's envelope to the transport (the
        frame-cap check + the write half of the old ``_send``); returns its id."""
        envelope = encode_envelope_command(command)
        if len(envelope.encode("utf-8")) > WORKER_PIPE_FRAME_CAP:
            raise ValueError(
                f"worker-pipe command envelope exceeds the {WORKER_PIPE_FRAME_CAP}-byte frame cap"
            )
        self._transport.write_line(envelope)
        return command.id

    def carry_over_desired_state(self, previous: WorkerPipeSession) -> None:
        """Adopt another session's replay ledger (current reload/swap desired
        state, stopping flag, dropped captions). Used when a channel's pipe is
        rebuilt on worker relaunch so :meth:`reconnect` can replay the CURRENT
        desired state to the fresh worker rather than starting from a blank slate."""
        self._replay = previous._replay

    def _send(self, command: ReplayCommand) -> str:
        envelope = encode_envelope_command(command)
        if len(envelope.encode("utf-8")) > WORKER_PIPE_FRAME_CAP:
            raise ValueError(
                f"worker-pipe command envelope exceeds the {WORKER_PIPE_FRAME_CAP}-byte frame cap"
            )
        self._replay.record_sent(command)
        self._pending[command.id] = command
        self._transport.write_line(envelope)
        return command.id

    def handle_ack_line(self, raw: str) -> tuple[str, str, str | None] | None:
        """Parse+apply one incoming ack line. Returns ``(id, result, detail)``, or
        ``None`` for a malformed frame or an id that is not (or is no longer)
        pending -- dropped, never raises: a bad frame must not kill the strategy's
        control loop."""
        try:
            command_id, result, detail = decode_envelope_ack(raw)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None
        if command_id not in self._pending:
            return None
        del self._pending[command_id]
        return command_id, result, detail

    def expire(self, command_id: str) -> LostAckOutcome | None:
        """Explicitly mark a pending command as lost (ack timeout, or a disconnect
        observed before any response arrived). Delegates to
        ``ChannelReplay.on_lost_ack`` -- returns the per-verb outcome, or ``None``
        if the id is not (or is no longer) pending."""
        command = self._pending.pop(command_id, None)
        if command is None:
            return None
        return self._replay.on_lost_ack(command)

    def reconnect(self, transport: DuplexTransport | None = None) -> list[str]:
        """On reconnect (fresh worker / fresh pipe): resend the channel's CURRENT
        desired state (reload/swap) using the deterministic reissue ids
        ``ChannelReplay`` assigns; caption/stop are never reissued (design.md
        sec4). Returns the command ids sent."""
        if transport is not None:
            self._transport = transport
        return [self._send(cmd) for cmd in self._replay.reissue_on_reconnect()]


class WindowsWorkerPipeServer:
    """Real Win32 duplex named-pipe SERVER for one channel's D2 worker-control
    seam (design.md sec4): the strategy creates+owns this pipe; the worker
    connects as CLIENT. Explicit SDDL (SYSTEM only -- the service runs as
    LocalSystem for the beta per spec D4, so SYSTEM alone is 'the service
    identity'; when D4's tracked least-privilege virtual-account follow-up lands,
    this SDDL needs that account's SID added), ``FILE_FLAG_FIRST_PIPE_INSTANCE``
    (squat detection -- raises, does not silently proceed), 16 KiB frame cap
    (``WORKER_PIPE_FRAME_CAP``).

    Every pywin32 import here is LAZY (inside the method that needs it) so this
    class definition stays import-safe on Linux -- it is only ever
    *instantiated* on Windows, but the module must still import cleanly
    everywhere (CI runs the pure envelope/replay tests on both OSes).

    NOTE (disclosed gap): this class is written to the design's exact contract
    but is NOT exercised by any test in this unit -- proving a real named pipe
    round trip (SD readback, squat detection with a second process, frame-cap
    enforcement over the wire) is explicitly the windows-native CI job / dev-box
    tier per design.md sec5, not the pure-logic tier this unit's tests cover.
    """

    def __init__(
        self,
        channel_id: str,
        *,
        security_descriptor_sddl: str = "D:P(A;;GA;;;SY)",
    ) -> None:
        self.channel_id = channel_id
        self.pipe_name = worker_pipe_name(channel_id)
        self._security_descriptor_sddl = security_descriptor_sddl
        self._handle: Any = None
        self._write_lock = threading.Lock()

    def create(self) -> None:
        """Create the pipe instance. Raises ``RuntimeError`` if
        ``FILE_FLAG_FIRST_PIPE_INSTANCE`` detects the name already taken (a rogue
        process squatted on it) -- detection, not prevention, per D7-class
        hardening; entering a 'degraded' state on that failure is a supervisor
        (``core.py``) concern, out of this unit's scope."""
        import pywintypes
        import win32pipe
        import win32security

        sd = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
            self._security_descriptor_sddl,
            win32security.SDDL_REVISION_1,
        )
        sa = win32security.SECURITY_ATTRIBUTES()
        sa.SECURITY_DESCRIPTOR = sd
        try:
            self._handle = win32pipe.CreateNamedPipe(
                self.pipe_name,
                win32pipe.PIPE_ACCESS_DUPLEX | win32pipe.FILE_FLAG_FIRST_PIPE_INSTANCE,
                win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
                1,  # exactly one instance: one worker per channel pipe
                WORKER_PIPE_FRAME_CAP,
                WORKER_PIPE_FRAME_CAP,
                0,
                sa,
            )
        except pywintypes.error as exc:
            if exc.winerror == 5:  # ERROR_ACCESS_DENIED -- FIRST_PIPE_INSTANCE squat
                raise RuntimeError(
                    f"worker pipe {self.pipe_name!r} already exists (squat detected)"
                ) from exc
            raise

    def accept(self) -> None:
        """Block until the worker connects (``ConnectNamedPipe``). Intended to run
        on its own background thread (the strategy starts one per channel) so
        ``.start()`` itself never blocks on the worker's connect."""
        import pywintypes
        import win32pipe

        try:
            win32pipe.ConnectNamedPipe(self._handle, None)
        except pywintypes.error as exc:
            if exc.winerror != 535:  # ERROR_PIPE_CONNECTED: client beat us here, fine
                raise

    def write_line(self, text: str) -> bool:
        import pywintypes
        import win32file

        payload = (text.rstrip("\n") + "\n").encode("utf-8")
        if len(payload) > WORKER_PIPE_FRAME_CAP:
            raise ValueError(f"frame exceeds the {WORKER_PIPE_FRAME_CAP}-byte cap")
        with self._write_lock:
            try:
                win32file.WriteFile(self._handle, payload)
                return True
            except pywintypes.error:
                return False

    def read_line(self) -> str | None:
        import pywintypes
        import win32file
        import win32pipe

        try:
            _peeked, available, _remaining = win32pipe.PeekNamedPipe(self._handle, 0)
            if available == 0:
                return None
            _, data = win32file.ReadFile(self._handle, WORKER_PIPE_FRAME_CAP)
        except pywintypes.error:
            return None
        if not data:
            return None
        return data.decode("utf-8", "replace").strip() or None

    def close(self) -> None:
        import win32file

        if self._handle is not None:
            with contextlib.suppress(Exception):
                win32file.CloseHandle(self._handle)
            self._handle = None


class _PendingAck:
    """One in-flight command's correlation state."""

    __slots__ = ("detail", "result")

    def __init__(self) -> None:
        self.result: str | None = None
        self.detail: str | None = None


class _WindowsPipeChannel:
    """Bundles the real transport (:class:`WindowsWorkerPipeServer`) + the pure
    policy engine (:class:`WorkerPipeSession`) for one channel.  Each command
    performs a serialized write/poll/read round trip on the caller thread.  A
    synchronous Win32 named-pipe handle serializes simultaneous ``ReadFile`` and
    ``WriteFile`` calls, so a parked background read would deadlock the write.
    This keeps ``GstPlayoutStrategy``'s synchronous ``bool`` API unchanged while
    actually round-tripping the D2 envelope on Windows.

    NOT exercised by this unit's test suite (same disclosed tier boundary as
    ``WindowsWorkerPipeServer``: a real pipe + real threads are the
    windows-native CI job / dev-box tier, not the pure-logic tier)."""

    def __init__(
        self,
        channel_id: str,
        *,
        server: WorkerPipeServer | None = None,
        ack_timeout_s: float = _WORKER_PIPE_ACK_TIMEOUT_S,
    ) -> None:
        # ``server`` defaults to the real Win32 pipe server; a test injects a fake
        # in-memory duplex server (CC-WS5-006 sec C) so the acknowledged send path
        # is provable with no Win32 I/O and no gi.
        self.server: WorkerPipeServer = server or WindowsWorkerPipeServer(channel_id)
        self.session = WorkerPipeSession(channel_id, self.server)
        self._ack_timeout_s = ack_timeout_s
        self._pending: dict[str, _PendingAck] = {}
        self._lock = threading.Lock()
        self._round_trip_lock = threading.Lock()
        self._connected_event = threading.Event()
        # Diagnosability fix (coordinator follow-up, 2026-09-06): the daemon's
        # ``_try_content_reload`` treated a False ``reload_content`` as silent --
        # nothing said WHY the seamless path was declined, so an operator/on-call
        # reading the control-plane log for "why did this channel restart instead
        # of reloading in place" found nothing. ``send_and_wait`` keeps its
        # existing synchronous bool contract (widely relied on by callers and
        # tests); this attribute carries the reason for the MOST RECENT False
        # return on THIS channel's pipe, read by
        # ``GstPlayoutStrategy.last_send_command_failure_reason``.
        self.last_failure_reason: str | None = None

    def start(self) -> None:
        """Create the pipe, accept the worker's connection on a background
        thread so this call itself never blocks."""
        self.server.create()

        def _accept() -> None:
            try:
                self.server.accept()
            except Exception:
                logger.exception(
                    "worker pipe %s failed while accepting its worker",
                    self.session.channel_id,
                )
                return
            self._connected_event.set()

        threading.Thread(
            target=_accept,
            name=f"civiccast-pipe-accept-{self.session.channel_id}",
            daemon=True,
        ).start()

    def send_and_wait(
        self,
        verb: Verb,
        line: str,
        *,
        command_id: str | None = None,
    ) -> bool:
        """Send one command and block for its ack up to the deadline (design.md
        sec4's 'bounded retry keyed by id'). On timeout, applies the per-verb
        lost-ack policy (``WorkerPipeSession.expire``) and returns ``False`` --
        matching the existing FIFO-path contract where a dropped command is
        reported as ``False``, never an exception.

        F1 redesign: a ``reload`` command's ack means "armed" (accepted, the new
        leg is building/prerolling), written by the worker synchronously -- same
        bound as every other verb (``_reload_ack_timeout_s()`` intentionally
        equals the default now; see its own docstring for why item 4's original
        widened bound was itself a bug). ``True`` for ``reload`` on either
        ``"armed"`` or ``"applied"`` (a redelivered id re-acks whatever the
        original ack said -- see ``worker.py``'s ``_windows_pipe_reader_loop``)."""
        ack_timeout_s = _reload_ack_timeout_s() if verb == "reload" else self._ack_timeout_s
        # A synchronous Win32 pipe handle serializes ReadFile and WriteFile calls
        # issued concurrently against that handle.  Keep one request/ack exchange
        # on one caller thread instead of parking a background ReadFile that would
        # deadlock the next write.
        with self._round_trip_lock:
            deadline = time.monotonic() + ack_timeout_s
            if not self._connected_event.wait(ack_timeout_s):
                self.last_failure_reason = "worker never connected to its control pipe"
                logger.warning(
                    "worker command for %s timed out before the worker connected",
                    self.session.channel_id,
                )
                return False
            pending = _PendingAck()
            # Register the waiter before the write so even an immediate fake/pipe
            # ack is correlated to an existing command.
            command = self.session.new_command(
                verb,
                line,
                command_id=command_id,
            )
            with self._lock:
                self._pending[command.id] = pending
            self.session.dispatch(command)

            while time.monotonic() < deadline:
                raw = self.server.read_line()
                if raw is None:
                    time.sleep(0.01)
                    continue
                outcome = self.session.handle_ack_line(raw)
                if outcome is None:
                    continue
                command_id, result, detail = outcome
                with self._lock:
                    resolved = self._pending.pop(command_id, None)
                if resolved is None:
                    continue
                resolved.result = result
                resolved.detail = detail
                if command_id == command.id:
                    succeeded = result == "applied" or (verb == "reload" and result == "armed")
                    if not succeeded:
                        # e.g. a reload's synchronous "error:<repr>" ack (the
                        # build failed before anything was armed -- F1 redesign)
                        # -- surfaced so the caller (daemon._try_content_reload)
                        # can log WHY, not just that the seamless reload was
                        # declined.
                        self.last_failure_reason = f"worker acked {result!r}" + (
                            f" ({detail})" if detail else ""
                        )
                    else:
                        self.last_failure_reason = None
                    return succeeded

            with self._lock:
                self._pending.pop(command.id, None)
            # CC-WS5-006 defect 2: surface the explicit per-verb lost-ack outcome
            # (reissue_desired_state / report_dropped / keep_stopping) rather than
            # discarding it silently.
            lost_ack_outcome = self.session.expire(command.id)
            self.last_failure_reason = (
                f"ack timeout after {ack_timeout_s:.1f}s ({lost_ack_outcome})"
            )
            logger.warning(
                "worker command %s lost-ack -> %s",
                command.id,
                lost_ack_outcome,
            )
            return False

    def close(self) -> None:
        self.server.close()


PipeChannelFactory = Callable[[str], _WindowsPipeChannel]


def _embed_captions_default() -> bool:
    """Whether to embed CEA-708 captions on the gst engine, from the environment.

    Off by default (the graph is byte-identical to today's); deployments opt in with
    ``CIVICCAST_EGRESS_EMBED_CAPTIONS=1`` — mirroring how the gst engine itself is
    opt-in via ``CIVICCAST_EGRESS_ENGINE``. The live SEI insertion is WSL/LPM-validated;
    the decode-back proof loop is what flips caption_status to on."""
    return os.environ.get("CIVICCAST_EGRESS_EMBED_CAPTIONS", "").strip().lower() in _TRUTHY


#: Item 3 (beta.5 gate): the env var that controls the GStreamer engine's
#: seamless in-place program content-reload. ON by DEFAULT as of beta.5
#: (owner decision, 2026-09-06): a plan rollover must be an in-place reload
#: with no worker restart and no output gap, so the seamless path is now the
#: shipping default rather than an opt-in.
#:
#: Background on why this was OFF before today: MEASURED on real hardware
#: (2026-09-06, clean install of 609273d, three GStreamer channels), the
#: first seamless plan rollover (``daemon._try_content_reload`` ->
#: ``strategy.reload_content`` -> the D2 worker-pipe seam ->
#: ``engine.reload_program``) was followed by ``CTRL stall: no output for
#: 10s`` worker relaunches every ~30s on every channel. Root cause (H1, see
#: ``engine.py``'s ``_make``/``_build_playlist``/``_source_leg_seq``
#: comments): every ``PlaylistLeg`` build named its ``concat`` aggregators
#: with the bare leg label (``vconcat_program``/``aconcat_program``), so a
#: reload's rebuilt aggregators collided with the still-live outgoing leg's
#: same-named aggregators -- GStreamer's ``bin.add()`` silently REFUSED the
#: duplicate, the reload's new leg never actually joined the pipeline, its
#: readiness probes never fired, and the worker's ``reload_program`` call
#: ack'd "applied" before the reload had committed (worker.py's
#: premature-ack defect, also fixed in this change) -- so automation
#: believed every rollover had landed and kept re-triggering it every
#: cadence tick while the channel bounced on the stall watchdog forever.
#:
#: That same change fixed the concat-naming collision (``_source_leg_seq``),
#: the silent ``pipeline.add()`` failure (``_make`` now raises), and the
#: premature ack (``reload_program(..., on_settled=...)``). Those fixes are
#: what let the owner flip this default ON for beta.5; the sandbox soak that
#: proves the seamless path end-to-end on real hardware is what this
#: candidate is held pending (see the PR that introduced this flip).
#:
#: Set ``CIVICCAST_EGRESS_SEAMLESS_RELOAD=0`` (or any other falsy value) to
#: OPT OUT and fall back to the daemon's terminate+restart reload path at
#: every plan rollover (one encoder restart per rollover -- a rounding error
#: for 10-40 minute program items, roughly every ~30s for a rapid
#: 30-second-item test/demo schedule, and a real output gap either way).
_SEAMLESS_RELOAD_ENV_VAR = "CIVICCAST_EGRESS_SEAMLESS_RELOAD"


def _seamless_content_reload_default() -> bool:
    """Whether ``GstPlayoutStrategy.supports_content_reload`` defaults on, from the
    environment. Defaults ON as of beta.5 (owner decision, 2026-09-06) -- set
    ``CIVICCAST_EGRESS_SEAMLESS_RELOAD=0`` to opt out. See ``_SEAMLESS_RELOAD_ENV_VAR``
    above for the history and what opting out costs."""
    raw = os.environ.get(_SEAMLESS_RELOAD_ENV_VAR, "").strip().lower()
    if not raw:
        return True
    return raw not in _FALSY


def _write_graph_file(path: Path, text: str) -> None:
    """Write a serialized graph, restricting it to 0600. The graph can embed a
    resolved SRT-sink passphrase (ENG-007), so it must not be world-readable in the
    channel work dir (ENG-003). chmod is best-effort (a no-op on Windows)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    with contextlib.suppress(OSError):
        path.chmod(0o600)


def _worker_creationflags() -> int:
    """Windows process-creation flags for a GStreamer playout worker.

    ``CREATE_NO_WINDOW`` is a real requirement on native Windows, not a
    hypothetical: the supervisor spawns this worker as a LocalSystem child
    with no console, and without this flag a stray console window can appear
    (ENG-006).

    ``ABOVE_NORMAL_PRIORITY_CLASS`` is the air-protection half. MEASURED on
    tester DESKTOP-VBMA6O5 (1.0.0-beta.5 candidate kit, three channels
    ON_AIR): the control-plane python -- same NORMAL priority class as these
    workers -- was consuming ~247% of a core running live-caption ASR while
    the playout workers sat at 26-64% each and repeatedly tripped their own
    ``CTRL stall: no output for 10s`` watchdog into a daemon restart. Playout
    is the product and captions are best effort, so the scheduler is told
    which is which.

    This raise is the half that actually covers a whole process. The caption
    side's counterpart
    (``civiccast.captions.tap_worker._lower_current_thread_priority``) lowers
    only the Python thread that calls into the model, NOT CTranslate2's
    intra-op pool where the inference CPU is really spent -- so do not read
    these two as a matched pair. Neither has been measured on a station yet;
    the caption side's load-bearing protections are its concurrency bound,
    ``cpu_threads=1``, and the overload backoff.

    ``getattr`` keeps both a no-op (0) on the Linux/WSL line, where neither
    attribute exists.
    """

    return getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
        subprocess, "ABOVE_NORMAL_PRIORITY_CLASS", 0
    )


def _default_worker_launcher(
    argv: list[str], stdout_path: Path, stderr_path: Path
) -> FfmpegProcessHandle:
    """Launch the worker subprocess; return a generic poll/pid/terminate handle."""
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_file = stdout_path.open("a", encoding="utf-8")
    stderr_file = stderr_path.open("a", encoding="utf-8")
    # Production worker runs run_forever; scrub the smoke-only SWAPS/INTERVAL so a
    # stray value in the daemon's environment can't put it in fixed-swap mode (audit M4).
    env = {key: value for key, value in os.environ.items() if key not in ("SWAPS", "INTERVAL")}
    # The worker imports gi/Gst and now runs on BOTH lines: the WSL/Linux line
    # against a system GStreamer install, and the native Windows line against
    # the installed closure (`civiccast.native.gstreamer_runtime`
    # bootstraps `dependencies/gstreamer` onto PATH/GI_TYPELIB_PATH before
    # this worker imports `gi`). See `_worker_creationflags` for what the
    # flags are and why playout is raised above the control plane.
    creationflags = _worker_creationflags()
    try:
        process = subprocess.Popen(  # noqa: S603
            argv,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            creationflags=creationflags,
        )
    except Exception:  # close the log handles if the spawn failed, then re-raise
        stdout_file.close()
        stderr_file.close()
        raise
    return FfmpegProcessHandle(process=process, _stdout_file=stdout_file, _stderr_file=stderr_file)


class GstPlayoutStrategy:
    """``EncoderStrategy`` that runs the GStreamer engine in a per-channel worker."""

    name = "gstreamer-playout-worker"
    supports_live_swap = True
    # Item 3: class-level fallback ONLY, for anything that reads the attribute off
    # the class rather than an instance. Every real instance overrides this in
    # __init__ with the environment-gated, DI-overridable value -- see
    # ``_SEAMLESS_RELOAD_ENV_VAR``/``_seamless_content_reload_default`` above for
    # why this defaults True (owner decision, beta.5: seamless plan rollover ON
    # by default). Set ``CIVICCAST_EGRESS_SEAMLESS_RELOAD=0`` to opt out.
    supports_content_reload = True
    # selector index per source role — matches graph_from_config leg order
    # (program leg = pad 0, always-hot black slate = pad 1). There is deliberately
    # NO 'live' pad: CivicCast airs a single pre-switched live feed (S16 delegates
    # production switching to the external switcher), so a live takeover is a
    # seamless content-reload of the program leg, not a selector pad.
    _ROLE_INDEX: ClassVar[dict[str, int]] = {"program": 0, "slate": 1}

    def __init__(
        self,
        *,
        worker_launcher: WorkerLauncher | None = None,
        python_executable: str | None = None,
        embed_captions: bool | None = None,
        audio_tracks_provider: Callable[[str], list[Any]] | None = None,
        pipe_channel_factory: PipeChannelFactory | None = None,
        encoder_probe: Callable[[str], bool] | None = None,
        element_probe: Callable[[str], bool] | None = None,
        is_windows: bool | None = None,
        supports_content_reload: bool | None = None,
    ) -> None:
        self._launch = worker_launcher or _default_worker_launcher
        self._python = python_executable or sys.executable
        # Native-Windows encoder pre-flight: "is this hardware factory present?" —
        # injectable (like worker_launcher) so start()'s Windows branch is unit-testable
        # without a real GStreamer/gi install. ``is_windows`` is likewise injectable so
        # the pre-flight wiring is provable on any CI platform, not just a Windows runner.
        self._encoder_probe = encoder_probe or probe_hardware_encoder
        # S15 §5 CG-lite: "is this overlay element registered?" — injectable like
        # encoder_probe so the board-overlay wiring is unit-testable without gi.
        self._element_probe = element_probe or probe_element_registered
        self._is_windows = (os.name == "nt") if is_windows is None else is_windows
        # S11a: when on, every graph (start + reload) carries the live CEA-708 embed leg.
        self._embed_captions = (
            _embed_captions_default() if embed_captions is None else embed_captions
        )
        # Item 3 (beta.5 gate): instance attribute so ``getattr(strategy,
        # "supports_content_reload", False)`` (``daemon._request_reload``) reads the
        # environment-gated default unless a caller (or a test) overrides it
        # explicitly -- see ``_SEAMLESS_RELOAD_ENV_VAR`` above. Defaults True (ON)
        # as of beta.5; set ``CIVICCAST_EGRESS_SEAMLESS_RELOAD=0`` to opt out.
        self.supports_content_reload = (
            _seamless_content_reload_default()
            if supports_content_reload is None
            else supports_content_reload
        )
        # S11 gap 9: per-channel secondary audio (SAP/descriptive) tracks, if wired.
        self._audio_tracks_provider = audio_tracks_provider
        # D2 Windows worker-pipe seam: one _WindowsPipeChannel per active channel,
        # populated in .start() on Windows only (empty, unused, on POSIX). Injectable
        # (mirrors the existing worker_launcher DI seam) so a real Win32 pipe is never
        # required to unit-test the strategy's Windows wiring with a fake channel.
        self._pipe_channel_factory: PipeChannelFactory = pipe_channel_factory or _WindowsPipeChannel
        self._pipe_channels: dict[str, _WindowsPipeChannel] = {}
        # Diagnosability fix (coordinator follow-up, 2026-09-06): the reason the
        # MOST RECENT send_command() call on each channel returned False, if any --
        # read by daemon._try_content_reload so a declined seamless reload logs
        # WHY instead of silently falling back to restart. See
        # ``last_send_command_failure_reason``.
        self._last_send_command_failure: dict[str, str] = {}

    def _caption_embed(self) -> CaptionEmbedRequest | None:
        """The caption-embed request for graph assembly (None = embedding off)."""
        return CaptionEmbedRequest(mode="live") if self._embed_captions else None

    def _audio_tracks(self, channel_id: str) -> list[Any] | None:
        """The channel's secondary audio tracks for graph assembly (None = single PID)."""
        if self._audio_tracks_provider is None:
            return None
        return self._audio_tracks_provider(channel_id)

    @staticmethod
    def _with_audio_tap(graph: PlayoutGraph, channel_id: str) -> PlayoutGraph:
        plan = build_audio_tap_plan(channel_id)
        if plan is None:
            return graph
        return replace(
            graph,
            audio_tap=AudioTapLeg(
                tap_dir=str(plan.tap_dir),
                segment_seconds=plan.segment_seconds,
            ),
        )

    def _resolve_encoder_override(self, request: EncoderStartRequest, *, warn: bool) -> str | None:
        """Native-Windows encoder pre-flight shared by start() AND reload_content().

        Refuses loudly (raises EncoderUnavailableError, which the daemon surfaces to the
        operator as ERROR/last_error) or returns the GStreamer encoder factory to pin --
        None on POSIX/WSL or when the configured encoder is used unchanged. reload_content
        MUST call this too: otherwise a channel that fell back to software encoding would
        silently rebuild its live pipeline's program leg targeting the absent hardware
        encoder on the next content swap.
        """
        decision = decide_encoder(
            codec=request.config.canonical_profile.video_codec,
            is_windows=self._is_windows,
            allow_software_fallback=request.config.allow_software_fallback,
            probe=self._encoder_probe,
        )
        if warn and decision.warning:
            logger.warning("channel %s: %s", request.channel_id, decision.warning)
        # HEVC cannot embed captions: the caption inserter (h264ccinserter) is H.264-only,
        # so feeding H.265 into it would break the pipeline. decision.encoder_override is
        # only set on Windows (decide_encoder no-ops on POSIX), so this is Windows-scoped.
        if (
            decision.encoder_override
            and "265" in decision.encoder_override
            and self._caption_embed() is not None
        ):
            raise EncoderUnavailableError(
                "HEVC/H.265 cannot embed captions on native Windows -- the caption inserter "
                "is H.264-only. Use H.264 for this channel, or turn off caption embedding."
            )
        return decision.encoder_override

    def _cg_overlay_image(self, request: EncoderStartRequest, *, warn: bool) -> Path | None:
        """S15 §5 CG-lite gate: only composite the board raster when the overlay
        element is actually registered; otherwise air without it and say so."""
        if request.cg_overlay_image is None:
            return None
        if self._element_probe(CG_OVERLAY_ELEMENT):
            return request.cg_overlay_image
        if warn:
            logger.warning(
                "channel %s: board overlay requested but %s is not registered in this "
                "GStreamer runtime — airing without the board overlay.",
                request.channel_id,
                CG_OVERLAY_ELEMENT,
            )
        return None

    def start(self, request: EncoderStartRequest) -> EncoderStartResult:
        encoder_override = self._resolve_encoder_override(request, warn=True)
        channel_dir = request.work_dir / request.channel_id
        graph = graph_from_config(
            request.config,
            request.source_plan,
            request.resolve_secret,
            caption_embed=self._caption_embed(),
            audio_tracks=self._audio_tracks(request.channel_id),
            encoder_override=encoder_override,
            cg_overlay_image=self._cg_overlay_image(request, warn=True),
            graphics_overlay=graphics_overlay_leg_from_config(
                request.config, render_dir=channel_dir, sweep_stale=True
            ),
        )
        graph = self._with_audio_tap(graph, request.channel_id)
        graph_path = channel_dir / "playout-graph.json"
        _write_graph_file(graph_path, graph_to_json(graph))

        log_dir = channel_dir / "logs"
        stdout_path = log_dir / "gst-worker.stdout.log"
        stderr_path = log_dir / "gst-worker.stderr.log"
        if self._is_windows:
            # D2 Windows worker-pipe seam (design.md sec4): the STRATEGY is the pipe
            # SERVER and must exist before the worker -- create+serve it here, before
            # launch, then pass the worker the pipe NAME (not a filesystem path).
            channel = self._pipe_channel_factory(request.channel_id)
            previous = self._pipe_channels.get(request.channel_id)
            if previous is not None:
                # Same-channel replacement (e.g. a crash-relaunch): carry the
                # current desired state (reload/swap) forward so reconnect_channel
                # can replay it to the fresh worker, then CLOSE the old pipe server
                # rather than leaking it (CC-WS5-006 defect 3 -- the F-D2-3 gap).
                channel.session.carry_over_desired_state(previous.session)
                previous.close()
            channel.start()
            self._pipe_channels[request.channel_id] = channel
            control_channel = worker_pipe_name(request.channel_id)
        else:
            control_channel = str(self.control_fifo_path(request.work_dir, request.channel_id))
        argv = [self._python, _WORKER_PATH, str(graph_path), control_channel]
        # Gate A T4 diagnosability fix (2026-09): safe to log VERBATIM -- this
        # argv is only the worker interpreter path, the worker script path,
        # the serialized graph-spec path, and the control channel name/pipe.
        # Sink credentials (SRT passphrase, RTMP stream key, RTSP userinfo)
        # never touch the command line for this strategy -- they are resolved
        # into ``graph_path``'s JSON body by ``graph_from_config`` above, which
        # is never logged here or elsewhere.
        logger.info("channel %s: starting GStreamer worker: %s", request.channel_id, argv)
        process = self._launch(argv, stdout_path, stderr_path)
        return EncoderStartResult(
            process=process,
            concat_plan_path=graph_path,  # reuse: the serialized graph spec path
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            args=tuple(argv),
        )

    @staticmethod
    def control_fifo_path(work_dir: Path, channel_id: str) -> Path:
        """The per-channel worker control FIFO path (worker creates it; we write it)."""
        return work_dir / channel_id / "control.fifo"

    def send_command(
        self,
        work_dir: Path,
        channel_id: str,
        text: str,
        *,
        command_id: str | None = None,
    ) -> bool:
        """Send one control line to the channel's worker.

        On native Windows this routes through the D2 named-pipe seam (design.md
        sec4): the versioned envelope + a BOUNDED wait for the worker's ack
        (``_WindowsPipeChannel.send_and_wait``) -- returns ``True`` only when the
        worker acked ``"applied"`` (or, for ``reload``, ``"armed"`` -- F1
        redesign, see ``_reload_ack_timeout_s``'s docstring), ``False`` on a
        lost/timed-out/errored ack (never raises), matching the POSIX contract's
        shape below exactly. On
        WSL/Linux this is the ORIGINAL POSIX FIFO write, UNCHANGED: non-blocking,
        returns False (drops the command) if the FIFO is missing (worker not
        started) or has no reader yet — never raises and never blocks waiting for
        a reader (audit M2). In production the supervisor calls this on a role
        change to swap the active source instead of restarting the encoder.

        Bug fix (coordinator hostile review, 2026-09-06, CI mutation-report):
        this used to branch on the real ``os.name`` directly instead of the
        injectable ``self._is_windows`` this class already carries (and
        already uses for the encoder-override decision, ``_resolve_encoder_
        override``) -- so a test constructing this strategy with
        ``is_windows=True`` to exercise the Windows pipe path on a POSIX CI
        runner silently fell through to the FIFO branch instead (the FIFO
        never existed, so it failed with a misleading "control FIFO missing"
        reason rather than the pipe channel's own). Both branch points below
        (here and in ``start()``) now consult ``self._is_windows``, matching
        the encoder-override seam -- production behavior is unchanged
        (``self._is_windows`` still defaults to the real ``os.name`` unless a
        caller overrides it)."""
        if self._is_windows:
            channel = self._pipe_channels.get(channel_id)
            if channel is None:
                self._last_send_command_failure[channel_id] = (
                    "worker not started (no registered control-pipe channel)"
                )
                return False  # worker not started (or its channel was never registered)
            verb_token = text.strip().split(None, 1)
            if not verb_token or verb_token[0].lower() not in ("reload", "swap", "caption", "stop"):
                self._last_send_command_failure[channel_id] = f"unparseable control line: {text!r}"
                return False  # unparseable per control.parse_control_line's own grammar
            applied = channel.send_and_wait(
                cast(Verb, verb_token[0].lower()),
                text,
                command_id=command_id,
            )
            if applied:
                self._last_send_command_failure.pop(channel_id, None)
            else:
                # getattr: a test double standing in for _WindowsPipeChannel
                # (structural typing, not inheritance) need not carry this
                # attribute -- see _FakePipeChannel in test_gst_strategy.py.
                reason = getattr(channel, "last_failure_reason", None)
                if reason is not None:
                    self._last_send_command_failure[channel_id] = reason
            return applied
        path = self.control_fifo_path(work_dir, channel_id)
        flags = os.O_WRONLY | getattr(os, "O_NONBLOCK", 0)
        try:
            fd = os.open(os.fspath(path), flags)
        except OSError:
            self._last_send_command_failure[channel_id] = (
                "control FIFO missing or has no reader (worker not started)"
            )
            return False
        try:
            os.write(fd, (text.rstrip("\n") + "\n").encode("utf-8"))
        finally:
            os.close(fd)
        self._last_send_command_failure.pop(channel_id, None)
        return True

    def last_send_command_failure_reason(self, channel_id: str) -> str | None:
        """Why the most recent ``send_command``/``reload_content`` call for
        ``channel_id`` returned False, or None if the last call succeeded (or no
        call has been made yet). Read by ``daemon._try_content_reload`` so a
        declined seamless reload's log line names a reason, not just the fact of
        the decline."""
        return self._last_send_command_failure.get(channel_id)

    def reconnect_channel(self, channel_id: str) -> list[str]:
        """Replay the channel's CURRENT desired state (reload/swap) to its worker
        over the existing pipe (no-op returning ``[]`` on POSIX / for an unknown
        channel). Caption/stop are never reissued (a stopping channel replays
        nothing). The daemon calls this after a crash-relaunch has brought a fresh
        worker up so a swap/reload that was live before the crash is restored
        rather than silently lost (CC-WS5-006 defect 3). Returns the reissued
        command ids."""
        channel = self._pipe_channels.get(channel_id)
        if channel is None:
            return []
        return channel.session.reconnect()

    def close_channel(self, channel_id: str) -> None:
        """Close and forget a channel's Windows worker pipe (no-op on POSIX / for
        an unknown channel). The daemon's stop path should call this once the
        worker process has exited so the pipe handle is released promptly rather
        than only at Job Object teardown; not calling it is safe (just untidy),
        since the Job Object (D3) reclaims the handle when the process tree dies."""
        channel = self._pipe_channels.pop(channel_id, None)
        if channel is not None:
            channel.close()

    def swap_role(self, channel_id: str, work_dir: Path, role: str) -> None:
        """Toggle the active source between the two always-hot legs via the FIFO.

        ``program``=0, ``slate``=1 — both legs are built into the pipeline and kept
        hot, so this is an instant selector toggle with no encoder restart, keeping
        MPEG-TS continuity unbroken (D-S1-6). A live takeover is NOT a pad swap:
        CivicCast airs a single pre-switched live feed, so a live program reaches
        air via a seamless content-reload of the program leg (``reload_content``),
        driven by the supervisor's takeover/handback path — there is no 'live' pad."""
        index = self._ROLE_INDEX.get(role)
        if index is None:
            raise ValueError(f"unknown source role: {role!r}")
        self.send_command(work_dir, channel_id, f"swap {index}")

    def reload_content(
        self,
        channel_id: str,
        work_dir: Path,
        request: EncoderStartRequest,
        *,
        command_id: str | None = None,
    ) -> bool:
        """Rebuild the program leg from a newly-due source plan in place (D-S1-6).

        Serializes a fresh ``PlayoutGraph`` for the new plan to a sidecar file and
        tells the running worker to swap its program content to it (the worker
        rebuilds the program leg on the live pipeline and switches on the new leg's
        first buffer, or defers the switch to the outgoing leg's own EOS when
        ``request.switch_at_end_of_current`` is set — B3 fix, seamless either way,
        no encoder restart). Returns True once the worker has ACKED the command
        as armed (F1 redesign) -- not once the reload has actually committed; the
        caller (``daemon._try_content_reload``) tracks settlement separately via
        ``reload-status.json``. Returns False when the worker control channel is
        not ready or the build failed synchronously, so the daemon can fall back
        to terminate+restart. ``command_id``, when given, is threaded through as
        the D2 envelope's own id (``daemon._try_content_reload`` generates one so
        it can correlate this specific reload attempt's eventual settlement)."""
        # Apply the SAME native-Windows encoder decision as start() -- a reload that
        # skipped this would rebuild the live pipeline on the absent hardware encoder
        # after a software fallback (adversarial-review BLOCKER). warn=False: the
        # fallback was already announced at start(); don't re-log every content swap.
        encoder_override = self._resolve_encoder_override(request, warn=False)
        channel_dir = work_dir / channel_id
        graph = graph_from_config(
            request.config,
            request.source_plan,
            request.resolve_secret,
            caption_embed=self._caption_embed(),
            audio_tracks=self._audio_tracks(channel_id),
            encoder_override=encoder_override,
            cg_overlay_image=self._cg_overlay_image(request, warn=False),
            graphics_overlay=graphics_overlay_leg_from_config(
                request.config, render_dir=channel_dir
            ),
        )
        graph = self._with_audio_tap(graph, channel_id)
        # ENG-005: a unique per-reload filename — the worker consumes (deletes) it after
        # reading, so concurrent reloads can't clobber a fixed path mid-read. B3 fix:
        # the filename also carries the switch-mode flag (see reload_policy.py's
        # docstring for why the control-line grammar itself can't carry it).
        # Hostile-review follow-up (2026-09-06): the filename's unique component is
        # now the CALLER'S ``command_id`` when one is given, rather than an
        # independently generated uuid -- the POSIX FIFO control channel has no
        # separate envelope/ack id field the way the Windows D2 pipe does, so this
        # is the only way a reload dispatched over the FIFO can report its eventual
        # settlement (``reload-status.json``) under an id the daemon can correlate
        # back to this specific attempt (``reload_policy.reload_id_from_sidecar_path``,
        # read by ``engine._dispatch_control``).
        suffix = reload_sidecar_suffix(switch_at_end_of_current=request.switch_at_end_of_current)
        reload_path = channel_dir / f"playout-graph.reload.{command_id or uuid.uuid4().hex}{suffix}"
        _write_graph_file(reload_path, graph_to_json(graph))
        return self.send_command(
            work_dir, channel_id, f"reload {reload_path}", command_id=command_id
        )

    def send_caption_cue(
        self,
        channel_id: str,
        work_dir: Path,
        *,
        text: str,
        pts_seconds: float,
        duration_seconds: float,
        delivery_id: str | None = None,
    ) -> bool:
        """Push one timed-text caption cue to the running worker (S11a).

        Base64-encodes the text so it survives the newline-delimited control FIFO, then
        sends a ``caption`` command the worker turns into ``engine.push_caption_cue``.
        Returns the FIFO-write result (False if the worker control channel isn't ready).
        The daemon's caption feed (review queue / ASR tap) calls this; the live engine
        push is WSL/LPM-validated."""
        payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
        pts_ms = max(0, int(pts_seconds * 1000))
        dur_ms = max(0, int(duration_seconds * 1000))
        return self.send_command(
            work_dir,
            channel_id,
            f"caption {pts_ms} {dur_ms} {payload}",
            command_id=delivery_id,
        )
