#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Per-channel GStreamer playout worker. Runs as a subprocess.

Ships and runs on native Windows (the product's shipped platform, via the bundled
GStreamer runtime and the D2 named-pipe control-channel seam) and on Linux/macOS
(a system GStreamer install, via the POSIX FIFO control channel below) — see the
D2 Windows worker-pipe seam note further down for how the control channel differs
per platform.

Reads a serialized ``PlayoutGraph`` (JSON, ``argv[1]``), builds + runs
``GstPlayoutEngine``, then force-exits so it can never hang.

- Production: ``run_forever()`` — SIGTERM (what the daemon's ``terminate()`` sends)
  quits the loop and tears down gracefully.
- Smoke/test: set ``SWAPS`` to run a fixed program↔role swap schedule.

Launched by file path (not ``-m``) so it needs only ``gi`` + the sibling
``graph``/``engine``/``control``/``audio_tap`` modules. This module's own import
block pulls in NO civiccast package module at all (proven in
``tests/egress/test_gst_worker_module_identity.py``), which is what keeps
``civiccast/egress/__init__.py`` — 771 modules, sqlalchemy + pydantic — out of
the worker process.

Measured boundary, so nobody reads more into that than it says: the worker
process as a whole is NOT pydantic-free today. ``engine.py`` unconditionally
imports ``civiccast.native.gstreamer_runtime`` to bootstrap the bundled
GStreamer closure, and ``civiccast/native/__init__.py`` re-exports
``civiccast.native.models``, which is pydantic. A real worker on the shipped
runtime lands at 321 modules including pydantic, without sqlalchemy and without
``civiccast.egress``. That is engine.py's import, it predates this seam, and
narrowing it is a separate change.

Usage:  python3 worker.py <graph.json>
"""

import base64
import contextlib
import importlib
import json
import os
import sys
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any

_GST_DIR = Path(__file__).resolve().parent
_PACKAGE = "civiccast.egress.gst"


def _sibling_module(name: str) -> Any:
    """Import one sibling gst module BY PATH and publish it under its package name.

    Gate A T4 root cause (2026-09), and why this is not a plain ``import graph``:
    ``engine.py`` imports these siblings in the PACKAGE form
    (``from civiccast.egress.gst.graph import ...``) and only falls back to the
    by-path form when that raises. On the native Windows line the bundled
    GStreamer closure makes the engine's ``gi`` import succeed, so the engine
    takes its package branch while this worker had taken the by-path branch --
    binding two DISTINCT ``PlaylistLeg`` classes compiled from the same file.
    ``engine._instantiate_source_leg``'s ``isinstance(leg, PlaylistLeg)`` then
    missed on every program leg (``bridge.graph_from_config`` always builds a
    ``PlaylistLeg``), fell through to the ``SourceLeg`` branch, and killed the
    worker at construction with ``AttributeError: 'PlaylistLeg' object has no
    attribute 'elements'`` -- before the pipeline reached PLAYING, so the udp-ts
    sink never emitted a packet.

    Registering the by-path module object in ``sys.modules`` under
    ``civiccast.egress.gst.<name>`` makes the engine's package-form import
    resolve to THIS object. ``importlib`` returns a ``sys.modules`` hit before it
    walks parent packages, so this does NOT import ``civiccast``,
    ``civiccast.egress`` (771 modules, sqlalchemy + pydantic) or
    ``civiccast.egress.gst``. A package-first import here (``from
    civiccast.egress.gst import graph``) would fix the identity split just as
    well and break exactly that -- see this module's docstring for the isolation
    contract, and for what the worker process really does end up importing once
    ``engine.py`` runs its own bootstrap.

    A module already present under the package name wins: in an in-process
    caller that legitimately imported the package (the test suite), adopting its
    object is what keeps the two halves on ONE identity in that direction too.
    """
    package_name = f"{_PACKAGE}.{name}"
    existing = sys.modules.get(package_name)
    if existing is not None:
        return existing
    if str(_GST_DIR) not in sys.path:
        sys.path.insert(0, str(_GST_DIR))
    module = importlib.import_module(name)
    sys.modules[package_name] = module
    return module


# ORDER IS LOAD-BEARING: every sibling the engine imports in package form must be
# published BEFORE ``engine`` itself is imported, or the engine's own package
# import of the missing one falls through to the real ``civiccast.egress.gst``
# package and re-creates the split identity this fixes.
controlmod = _sibling_module("control")
graphmod = _sibling_module("graph")
_sibling_module("audio_tap")  # engine imports RollingWavSegmentWriter from it
# engine imports the gi-free CPU-decode policy from this sibling at module scope,
# BEFORE it imports gi -- publish it here or the engine's package-form import of it
# would drag in the real civiccast.egress package (771 modules, pydantic+sqlalchemy).
_sibling_module("decode_policy")
# B3 fix: engine.py also imports the gi-free reload-switch-mode decoder from this
# sibling at module scope -- same reasoning as decode_policy above.
reload_policy_mod = _sibling_module("reload_policy")
# Item 82: gi-free exit-code contract with the daemon (civiccast.egress.daemon
# reads this same module -- see exit_codes.py's own docstring for why it must
# stay side-effect-free rather than living in engine.py).
exit_codes_mod = _sibling_module("exit_codes")
enginemod = _sibling_module("engine")

# -- D2 Windows worker-pipe seam (spec-supervisor D2, design.md sec4) --------------
#
# On Linux/macOS the control channel is the POSIX FIFO below (unchanged). On native
# Windows ``os.mkfifo`` does not exist, so argv[2] is instead the NAME of a duplex
# named pipe (``\\.\pipe\civiccast-worker-<channel_id>``) the STRATEGY already
# created and is serving (civiccast.egress.gst.strategy.WindowsWorkerPipeServer) --
# this worker connects as CLIENT (CreateFile), never creates the pipe itself.
#
# ``control.py``'s ``parse_control_line`` is reused UNCHANGED. Only stdlib + the
# sibling gi-free ``control`` module are imported here (never the civiccast
# package, which pulls in pydantic) -- this module must stay importable with only
# ``gi`` + stdlib, per the module docstring above.


class _AppliedIdCache:
    """Minimal worker-side LRU of applied command ids (D2 dedup contract): a
    redelivered id is acknowledged again but NOT re-enacted. This mirrors
    ``civiccast.native.supervisor.replay.AppliedIdCache`` exactly (same
    semantics, same tests exercise the contract from the strategy side in
    ``tests/egress/test_worker_pipe_seam.py``) but is a deliberate, standalone
    copy: importing ``replay.py`` would pull pydantic into this gi-only process."""

    def __init__(self, capacity: int = 1024) -> None:
        self._capacity = capacity
        self._ids: OrderedDict[str, None] = OrderedDict()

    def should_apply(self, command_id: str) -> bool:
        return command_id not in self._ids

    def mark_applied(self, command_id: str) -> None:
        if command_id in self._ids:
            self._ids.move_to_end(command_id)
            return
        self._ids[command_id] = None
        while len(self._ids) > self._capacity:
            self._ids.popitem(last=False)


def _write_reload_status(channel_dir: Path, *, reload_id: str, result: str) -> None:
    """F1 redesign (coordinator hostile review, 2026-09-06): the OUT-OF-BAND
    settle outcome for a reload.

    The pipe ack for a ``reload`` command now means only "armed" (see
    ``_dispatch_control_with_ack``'s docstring) -- the actual commit or abort
    can take up to the engine's own ``reload_timeout_s`` (an immediate switch)
    or ``defer_switch_timeout_s`` (900s default, a deferred/boundary-aligned
    switch -- exactly the case an automation-driven ON_AIR extension uses, per
    ``reload_policy.should_defer_switch``). Blocking a synchronous pipe
    round-trip ack for up to 900s was THE F1 blocker this redesign fixes: it
    starved the automation thread and, worse, the strategy's bounded ack wait
    would time out long before a legitimately-armed deferred reload ever
    settles, causing the daemon to terminate a worker that was doing exactly
    what it was told.

    Instead, this file (``<channel_dir>/reload-status.json``) carries the
    eventual outcome; ``EgressDaemon._poll_reload_settlement`` polls it once
    per automation tick (bounded, cheap) instead of blocking on it. Atomic
    write (tmp + replace) so the daemon never observes a partial JSON body.
    Best-effort: a write hiccup here must not crash the worker -- the daemon's
    own deadline (``_PENDING_RELOAD_SETTLE_DEADLINE_S``) is the backstop if a
    status update never arrives at all."""
    status_path = channel_dir / "reload-status.json"
    tmp_path = status_path.with_name(status_path.name + ".tmp")
    payload = json.dumps({"id": reload_id, "result": result, "ts": time.time()})
    try:
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(status_path)
    except OSError as exc:
        print(f"WARN: failed to write reload-status.json: {exc!r}", flush=True)


def _dispatch_control_with_ack(
    engine_instance: Any,
    line: str,
    *,
    command_id: str | None = None,
) -> tuple[str, str | None]:
    """The D2 pipe-seam dispatch: applies ``line`` and returns an ack result
    (``"applied"``|``"armed"``|``"error"``, detail) instead of only printing, so
    the pipe seam can write back ``{"result": ...}`` (design.md sec4's 'ack-point
    reading'). Calls the SAME public engine effects ``engine._dispatch_control`` uses
    (``swap.swap_to``, ``reload_program``, ``push_caption_cue``, ``_loop.quit()``)
    -- it does not reimplement engine internals, only observes their outcome,
    since ``_dispatch_control`` itself is fire-and-forget (engine.py, out of this
    unit's file ownership) and has no return value to relay.

    F1 redesign (coordinator hostile review, 2026-09-06, superseding item 4's
    original "deferred ack" design): ``reload_program`` only ARMS a reload -- it
    builds and prerolls the new leg and returns immediately; the actual commit
    (first buffer / boundary reached) or abort (build error, async bus error,
    timeout, supersession) happens LATER, on the main loop, and for a DEFERRED
    switch (an automation-driven ON_AIR extension) that can take up to
    ``defer_switch_timeout_s`` (900s default) -- far longer than any pipe
    round-trip ack should ever block for. Item 4's fix made the ack wait for
    that full settlement, which just moved the dishonesty (and, worse,
    introduced a NEW failure: the strategy's bounded ack wait would time out
    on a correctly-armed long-lead deferred reload and the daemon would
    terminate a healthy worker). This redesign instead:

    * acks ``"armed"`` the instant ``reload_program`` returns without raising
      (the command was accepted; the new leg is now building/prerolling) --
      keeps the ack fast and bounded, like every other verb;
    * acks ``"error:<repr>"`` immediately if ``reload_program`` (or reading/
      parsing the graph file) raises synchronously -- nothing was armed, so
      there is nothing to settle later;
    * reports the EVENTUAL settle outcome out-of-band via
      ``_write_reload_status`` (``reload_id`` is the D2 envelope's own
      command id, so the daemon can correlate a specific armed attempt to its
      settlement even across a supersede).

    Every other verb (swap/caption/stop) is unchanged: dispatch and ack are
    still the same synchronous step they always were."""
    command = controlmod.parse_control_line(line)
    if command is None:
        return "error", f"unparseable control line: {line!r}"
    verb = command[0]
    try:
        if verb == "swap":
            engine_instance.swap.swap_to(command[1])
            return "applied", None
        if verb == "reload":
            reload_path = Path(command[1])
            channel_dir = reload_path.parent
            with reload_path.open(encoding="utf-8") as handle:
                new_graph = graphmod.graph_from_json(handle.read())
            switch_at_end_of_current = reload_policy_mod.reload_switch_is_deferred(command[1])
            with contextlib.suppress(OSError):
                reload_path.unlink()  # one-shot graph file: consumed after read

            reload_id = command_id or uuid.uuid4().hex

            def _on_settled(committed: bool, reason: str | None) -> None:
                result = "applied" if committed else f"aborted:{reason or 'unknown'}"
                _write_reload_status(channel_dir, reload_id=reload_id, result=result)

            engine_instance.reload_program(
                new_graph.sources[0],
                switch_at_end_of_current=switch_at_end_of_current,
                on_settled=_on_settled,
            )
            # BLOCKER fix: re-apply the graphics-overlay leg too (mirrors the FIFO
            # dispatch path, engine._dispatch_control) -- otherwise a content-reload
            # delivered over the D2 Windows pipe seam would silently drop a lower-third
            # text update just like the FIFO path used to. Its own failure must NOT
            # affect the program reload's ack above (that reload already armed
            # successfully and will settle on its own via ``_on_settled``) -- an
            # overlay re-apply failure never disturbs the already-on-air overlay
            # (see ``reload_graphics_overlay``'s own docstring) and must not be
            # conflated with the program reload's outcome.
            try:
                engine_instance.reload_graphics_overlay(new_graph.graphics_overlay)
            except Exception as exc:
                print(
                    f"CTRL reload: graphics-overlay re-apply failed "
                    f"(program reload still in flight): {exc!r}",
                    flush=True,
                )
            # F1: ack "armed" NOW -- do not wait for _on_settled.
            return "armed", None
        if verb == "caption":
            text = base64.b64decode(command[3]).decode("utf-8", "replace")
            pushed = engine_instance.push_caption_cue(
                text=text, pts_seconds=command[1] / 1000.0, duration_seconds=command[2] / 1000.0
            )
            if not pushed:
                return "error", "no live caption source"
            return "applied", None
        if verb == "stop":
            if engine_instance._loop is not None:
                engine_instance._loop.quit()
            return "applied", None
    except Exception as exc:  # a bad command must never kill the channel
        return "error", repr(exc)
    return "error", f"unknown verb: {verb!r}"


def _windows_pipe_connect(pipe_name: str, timeout_s: float = 10.0) -> Any:
    """Connect to the strategy-owned named pipe as CLIENT (``CreateFile``) --
    'the strategy exists first and holds both handles' (design.md sec4). Retries
    while the strategy's ``ConnectNamedPipe``/pipe creation catches up."""
    import pywintypes
    import win32file
    import win32pipe

    deadline = time.monotonic() + timeout_s
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            handle = win32file.CreateFile(
                pipe_name,
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0,
                None,
                win32file.OPEN_EXISTING,
                0,
                None,
            )
            win32pipe.SetNamedPipeHandleState(handle, win32pipe.PIPE_READMODE_MESSAGE, None, None)
        except pywintypes.error as exc:
            last_exc = exc
            time.sleep(0.2)
        else:
            return handle
    raise RuntimeError(f"could not connect to worker pipe {pipe_name!r}") from last_exc


def _windows_pipe_read_line(handle: Any) -> str | None:
    import pywintypes
    import win32file

    try:
        _, data = win32file.ReadFile(handle, 65536)
    except pywintypes.error:
        return None  # disconnected; caller reconnects
    if not data:
        return None
    return data.decode("utf-8", "replace").strip() or None


def _windows_pipe_write_line(handle: Any, write_lock: threading.Lock, text: str) -> bool:
    import pywintypes
    import win32file

    payload = (text.rstrip("\n") + "\n").encode("utf-8")
    with write_lock:
        try:
            win32file.WriteFile(handle, payload)
        except pywintypes.error:
            return False
        else:
            return True


def _windows_pipe_reader_loop(
    pipe_name: str,
    engine_instance: Any,
    stop_event: threading.Event,
) -> None:
    """D2 Windows worker-pipe reader THREAD (design.md sec4): blocks on pipe
    reads and marshals each NEW command onto the GLib main loop via
    ``GLib.idle_add`` so dispatch stays single-threaded exactly like the FIFO
    path (``engine._watch_control_fifo``) -- never dispatched directly from this
    thread. Acks are written back from the dispatch completion (thread-safe via
    ``write_lock``). No POSIX keepalive-fd trick (that mechanism is FIFO-specific
    -- engine.py:678, no named-pipe analogue): on disconnect, this loop
    reconnects with exponential backoff instead."""
    from gi.repository import GLib  # type: ignore[import-not-found]

    applied = _AppliedIdCache()
    write_lock = threading.Lock()
    handle: Any = None
    backoff = 0.5
    while not stop_event.is_set():
        if handle is None:
            try:
                handle = _windows_pipe_connect(pipe_name)
                backoff = 0.5
            except Exception:
                time.sleep(backoff)
                backoff = min(backoff * 2.0, 30.0)
                continue
        line = _windows_pipe_read_line(handle)
        if line is None:
            handle = None  # disconnected: loop back around and reconnect
            continue
        try:
            envelope = json.loads(line)
            command_id = str(envelope["id"])
            command_line = str(envelope["cmd"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue  # malformed frame: drop silently, never crash the worker

        current_handle = handle
        if not applied.should_apply(command_id):
            # Redelivered id: the ack was lost, not the application -- ack again
            # without re-enacting (D2 idempotent-redelivery contract). F1
            # redesign: "applied" is only ever cached for swap/caption/stop
            # now (a "reload" that ACTUALLY committed writes reload-status.json,
            # not the applied-id cache -- see _dispatch_and_ack); a cached
            # "reload" id was marked applied at ARM time, so redelivering it
            # re-acks "armed" (matching what the original ack said), never
            # "applied".
            parsed = controlmod.parse_control_line(command_line)
            reack_result = "armed" if parsed is not None and parsed[0] == "reload" else "applied"
            ack_written = threading.Event()

            def _reack(
                h: Any = current_handle,
                cid: str = command_id,
                result: str = reack_result,
                completed: threading.Event = ack_written,
            ) -> bool:
                try:
                    _windows_pipe_write_line(
                        h,
                        write_lock,
                        json.dumps({"v": 1, "id": cid, "result": result}),
                    )
                finally:
                    completed.set()
                return False  # one-shot GLib idle source

            GLib.idle_add(_reack)
            while not stop_event.is_set() and not ack_written.wait(0.05):
                pass
            continue

        ack_written = threading.Event()

        def _dispatch_and_ack(
            h: Any = current_handle,
            cid: str = command_id,
            line_text: str = command_line,
            completed: threading.Event = ack_written,
        ) -> bool:
            # F1 redesign: the ack is ALWAYS written synchronously now (a
            # "reload"'s eventual settle outcome goes out-of-band via
            # reload-status.json instead -- see _dispatch_control_with_ack's
            # docstring). "armed" counts as accepted for the dedup cache, same
            # as "applied": a redelivery of an already-armed reload id must
            # re-ack, not re-enact (re-arming would supersede the FIRST
            # attempt's own still-settling reload for no reason).
            try:
                try:
                    result, detail = _dispatch_control_with_ack(
                        engine_instance, line_text, command_id=cid
                    )
                except Exception as exc:
                    # Hostile-review follow-up (2026-09-06): _dispatch_control_
                    # with_ack already catches everything INSIDE its own body,
                    # but a raise from code that runs before its try block
                    # (e.g. a malformed line reaching parse_control_line) would
                    # otherwise escape all the way past this bare try/finally
                    # with NO ack ever written -- the strategy's send_and_wait
                    # would then sit out its full timeout and report a lost ack
                    # instead of a clean, immediate error. Write one here so a
                    # bug in dispatch itself is still an honest, fast "error"
                    # ack rather than a silent hang.
                    result, detail = "error", repr(exc)
                if result in ("applied", "armed"):
                    applied.mark_applied(cid)
                _windows_pipe_write_line(
                    h,
                    write_lock,
                    json.dumps({"v": 1, "id": cid, "result": result, "detail": detail}),
                )
            finally:
                completed.set()
            return False  # one-shot GLib idle source

        GLib.idle_add(_dispatch_and_ack)
        while not stop_event.is_set() and not ack_written.wait(0.05):
            pass


def _run_forever_windows_pipe(engine_instance: Any, pipe_name: str) -> dict[str, Any]:
    """D2 Windows worker-pipe entry point: starts the reader thread, then runs the
    engine's normal ``run_forever`` loop with ``control_fifo=None`` (no FIFO --
    the reader thread marshals commands onto the SAME GLib main loop via
    ``idle_add``, so this is still single-threaded dispatch, exactly as the FIFO
    path is)."""
    stop_event = threading.Event()
    reader_thread = threading.Thread(
        target=_windows_pipe_reader_loop,
        args=(pipe_name, engine_instance, stop_event),
        name="civiccast-worker-pipe-reader",
        daemon=True,
    )
    reader_thread.start()
    try:
        result: dict[str, Any] = engine_instance.run_forever(control_fifo=None)
        return result
    finally:
        stop_event.set()


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: worker.py <graph.json>", file=sys.stderr, flush=True)
        return 2
    with Path(sys.argv[1]).open(encoding="utf-8") as handle:
        playout = graphmod.graph_from_json(handle.read())
    control_fifo = sys.argv[2] if len(sys.argv) >= 3 else None
    if os.name == "nt":
        # D2 Windows worker-pipe seam: argv[2] is a named-pipe NAME
        # (`\\.\pipe\civiccast-worker-<channel_id>`) created+served by the
        # strategy; the worker connects as CLIENT and never creates it -- the
        # POSIX mkfifo branch below is for Linux/macOS only and is simply not
        # reached here.
        pass
    elif control_fifo and not Path(control_fifo).exists():
        Path(control_fifo).parent.mkdir(parents=True, exist_ok=True)
        if not hasattr(os, "mkfifo"):
            raise RuntimeError("control FIFO support requires a POSIX host (Linux/macOS)")
        os.mkfifo(control_fifo)
    reload_timeout = float(os.environ.get("CIVICCAST_RELOAD_TIMEOUT_S", "10"))
    stall_timeout = float(os.environ.get("CIVICCAST_STALL_TIMEOUT_S", "10"))
    # Item 85: bounds GstPlayoutEngine._commit_reload itself (see its own
    # docstring / _arm_commit_watchdog) -- separate from reload_timeout above,
    # which only bounds waiting for the NEW leg's first buffer, not the commit.
    commit_timeout = float(os.environ.get("CIVICCAST_RELOAD_COMMIT_TIMEOUT_S", "15"))
    engine_instance = enginemod.GstPlayoutEngine(
        playout,
        reload_timeout_s=reload_timeout,
        stall_timeout_s=stall_timeout,
        commit_timeout_s=commit_timeout,
    )
    swaps = int(os.environ.get("SWAPS", "0"))
    try:
        if swaps > 0:
            result = engine_instance.run(
                swaps=swaps, interval_s=int(os.environ.get("INTERVAL", "2"))
            )
        elif os.name == "nt" and control_fifo:
            result = _run_forever_windows_pipe(engine_instance, control_fifo)
        else:
            result = engine_instance.run_forever(control_fifo=control_fifo)
    except enginemod.PrerollTimeoutError as exc:
        # Item 82: a slow-but-progressing preroll under CPU load is a slow
        # start, not a crash. Exit with a DISTINCT code (never 1, the generic
        # crash code every other engine failure below still uses) so the
        # daemon's relaunch path (civiccast.egress.daemon._relaunch_after_crash
        # / _begin_relaunch) can retry with the existing backoff WITHOUT
        # counting this toward the crash-loop force-fallback-slate streak the
        # same way an ordinary crash does. A distinct stderr message too, so an
        # operator reading the worker's own log (folded into the daemon's
        # last_error) sees "slow preroll", not a generic crash.
        print(f"CTRL preroll: worker exiting -- {exc}", file=sys.stderr, flush=True)
        # Round-3 review (Opus, PR #183), item 5: ``PrerollTimeoutError`` is
        # raised INSIDE ``_await_playing`` -- before this fix it propagated
        # straight here without ``engine_instance.stop()`` ever running, so
        # the pipeline was never given a chance at a clean ``->NULL``
        # teardown; only the hard ``os._exit()`` at the bottom of this file
        # (__main__) ever tore it down, unconditionally, with no attempt at
        # a graceful release. Call ``stop()`` here too, but deliberately
        # ``force_exit_on_hang=False``: ``stop()`` is ALREADY time-bounded
        # (blocks at most ``teardown_timeout_s``, ~5s default, via its own
        # bounded ``get_state`` call) so this can never hang the worker, and
        # ``force_exit_on_hang=True`` would call ``os._exit(70)`` on a stuck
        # teardown -- silently swapping the distinct
        # ``GST_PREROLL_TIMEOUT_EXIT_CODE`` this whole except block exists to
        # preserve for a generic forced-kill code, defeating item 82 itself.
        # A teardown that itself raises (or simply doesn't complete) must
        # never block reaching the ``return`` below.
        teardown_clean = False
        try:
            teardown_clean = engine_instance.stop(force_exit_on_hang=False)
        except Exception as teardown_exc:  # never let teardown mask the real exit code
            print(
                f"CTRL preroll: teardown after preroll timeout failed: {teardown_exc}",
                file=sys.stderr,
                flush=True,
            )
        # Round-2 review, item 5: emit the WORKER_RESULT receipt here too --
        # civiccast.native.installed_gstreamer_smoke.require_clean_worker_result
        # requires ONE (its own error is an unhelpful "product worker emitted
        # no WORKER_RESULT receipt" otherwise) and, with it, its failure
        # message NAMES the actual reason (this dict's ``error`` tuple)
        # instead of just an exit code. ``teardown_clean`` now reflects the
        # ``stop()`` attempt above, not a hardcoded False -- a preroll that
        # never reached PLAYING can still tear its (partially built)
        # pipeline down to NULL cleanly within the bound.
        preroll_result = {"error": ("preroll-timeout", str(exc)), "teardown_clean": teardown_clean}
        print(f"WORKER_RESULT {preroll_result}", flush=True)
        return int(exit_codes_mod.GST_PREROLL_TIMEOUT_EXIT_CODE)
    print(f"WORKER_RESULT {result}", flush=True)
    error = result.get("error")
    if error is None:
        return 0
    # Item 84: unlike PrerollTimeoutError above (raised as an exception, so
    # its own except-clause chooses the exit code), a first-output timeout is
    # NOT raised -- ``GstPlayoutEngine._check_stall`` sets ``self._error`` and
    # quits the loop exactly like the ordinary post-first-buffer stall does
    # (see the ``("stall", ...)`` reason, which still falls through to the
    # generic exit code 1 below), so ``run_forever`` returns normally and this
    # reason has to be told apart from every OTHER engine failure here instead.
    # A distinct exit code (never 1) is what lets the daemon's relaunch path
    # (``EgressDaemon._relaunch_after_crash``) rate-limit this the same way it
    # already does ``GST_PREROLL_TIMEOUT_EXIT_CODE``, instead of counting a
    # slow-but-healthy start toward the crash-loop fallback-slate streak.
    if isinstance(error, (tuple, list)) and error and error[0] == "first-output-timeout":
        return int(exit_codes_mod.GST_FIRST_OUTPUT_TIMEOUT_EXIT_CODE)
    return 1


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)  # never hang at interpreter exit on stuck GStreamer threads
