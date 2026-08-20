# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""#151 — persistent TS relay: one mux session across encoder relaunches.

Unit layer: supervisor lifecycle, URI rewriting, mode/availability gating —
all with a fake popen. Behavioral layer at the bottom: a REAL ``tsp`` relay
fed two crafted TS "sessions" (continuity counters resetting between them,
exactly what an encoder relaunch produces) must emit continuous CC on the
other side — parsed by a pure-python TS packet reader, no capture tooling.
"""

from __future__ import annotations

import itertools
import shutil
import socket
import subprocess
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from civiccast.egress.models import EgressConfig, EgressSinkSpec
from civiccast.egress.ts_relay import TsRelaySupervisor, build_tsp_relay_args, relay_mode


def _config(*sinks: EgressSinkSpec) -> EgressConfig:
    return EgressConfig(
        channel_id="gov",
        enabled=True,
        slate_message="slate",
        sinks=list(sinks),
    )


def _udp_sink(uri: str = "udp://239.1.2.3:5000?pkt_size=1316") -> EgressSinkSpec:
    return EgressSinkSpec(kind="udp-ts", label="headend", uri=uri)


class _FakeProcess:
    def __init__(self) -> None:
        self.terminated = False

    def poll(self) -> int | None:
        return None if not self.terminated else 0

    def terminate(self) -> None:
        self.terminated = True


def _supervisor(monkeypatch: pytest.MonkeyPatch, *, installed: bool = True):
    monkeypatch.setenv("CIVICCAST_TS_RELAY", "auto")
    calls: list[list[str]] = []
    procs: list[_FakeProcess] = []

    def popen(args, **_kwargs):
        calls.append(args)
        proc = _FakeProcess()
        procs.append(proc)
        return proc

    sup = TsRelaySupervisor(
        popen=popen,
        locate=lambda: SimpleNamespace(installed=installed, path="/opt/tsduck/tsp"),
    )
    return sup, calls, procs


def test_relay_mode_validates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVICCAST_TS_RELAY", "banana")
    with pytest.raises(ValueError, match=r"auto\|on\|off"):
        relay_mode()


def test_args_pin_ports_and_fix_continuity() -> None:
    args = build_tsp_relay_args(
        "/opt/tsduck/tsp",
        listen_port=17800,
        dest_host="239.1.2.3",
        dest_port=5000,
        local_out_port=18800,
    )
    joined = " ".join(args)
    assert args[0] == "/opt/tsduck/tsp"
    assert "-P continuity --fix" in joined
    assert "-P pcradjust" in joined
    assert "239.1.2.3:5000" in joined
    assert "--local-port 18800" in joined  # pinned source port — one session forever


def test_relaunches_reuse_the_same_relay(monkeypatch: pytest.MonkeyPatch) -> None:
    sup, calls, _procs = _supervisor(monkeypatch)
    first = sup.apply(_config(_udp_sink()))
    second = sup.apply(_config(_udp_sink()))  # the encoder relaunch

    assert len(calls) == 1  # ONE relay process across both starts
    assert first.sinks[0].uri == second.sinks[0].uri
    assert first.sinks[0].uri.startswith("udp://127.0.0.1:")
    assert first.sinks[0].uri.endswith("?pkt_size=1316")  # query preserved


def test_dead_relay_is_restarted_on_the_same_port(monkeypatch: pytest.MonkeyPatch) -> None:
    sup, calls, procs = _supervisor(monkeypatch)
    first = sup.apply(_config(_udp_sink()))
    procs[0].terminated = True  # relay crashed
    second = sup.apply(_config(_udp_sink()))

    assert len(calls) == 2
    assert first.sinks[0].uri == second.sinks[0].uri  # port stability survives


def test_off_mode_and_missing_tsp_pass_through(monkeypatch: pytest.MonkeyPatch) -> None:
    sup, calls, _ = _supervisor(monkeypatch)
    monkeypatch.setenv("CIVICCAST_TS_RELAY", "off")
    config = _config(_udp_sink())
    assert sup.apply(config) is config
    assert calls == []

    sup2, calls2, _ = _supervisor(monkeypatch, installed=False)
    monkeypatch.setenv("CIVICCAST_TS_RELAY", "auto")
    assert sup2.apply(config) is config
    assert calls2 == []


def test_non_udp_sinks_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    sup, calls, _ = _supervisor(monkeypatch)
    srt = EgressSinkSpec(kind="srt", label="srt", uri="srt://10.0.0.9:9000")
    config = _config(srt)
    assert sup.apply(config) is config
    assert calls == []


def test_stop_channel_terminates_only_that_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    sup, _calls, procs = _supervisor(monkeypatch)
    sup.apply(_config(_udp_sink()))
    other = EgressConfig(
        channel_id="edu",
        enabled=True,
        slate_message="slate",
        sinks=[_udp_sink("udp://239.9.9.9:6000")],
    )
    sup.apply(other)

    sup.stop_channel("gov")
    assert procs[0].terminated is True
    assert procs[1].terminated is False


def test_stop_channel_returns_listen_port_to_the_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    """Port allocation must not just monotonically climb forever: a
    long-lived station cycling through many channel/destination combinations
    would otherwise consume a fresh port every time and eventually exceed
    65535. A freed port must be handed back out to the NEXT new relay."""
    sup, _calls, _procs = _supervisor(monkeypatch)
    first = sup.apply(_config(_udp_sink()))
    freed_port = urlsplit(first.sinks[0].uri).port

    sup.stop_channel("gov")

    other = EgressConfig(
        channel_id="edu",
        enabled=True,
        slate_message="slate",
        sinks=[_udp_sink("udp://239.9.9.9:6000")],
    )
    second = sup.apply(other)

    assert urlsplit(second.sinks[0].uri).port == freed_port  # reused, not a brand-new port


# ---------------------------------------------------------------------------
# Behavioral: REAL tsp relay splices two TS sessions into continuous CC
# ---------------------------------------------------------------------------

_PID = 0x0100


def _ts_packet(pid: int, cc: int, payload_byte: int) -> bytes:
    """One 188-byte TS packet with a payload and the given continuity counter."""
    header = bytes(
        [
            0x47,
            (pid >> 8) & 0x1F,
            pid & 0xFF,
            0x10 | (cc & 0x0F),  # payload only, CC
        ]
    )
    return header + bytes([payload_byte]) * 184


def _cc_sequence(data: bytes, pid: int) -> list[int]:
    out = []
    for i in range(0, len(data) - 187, 188):
        pkt = data[i : i + 188]
        if pkt[0] != 0x47:
            continue
        p = ((pkt[1] & 0x1F) << 8) | pkt[2]
        if p == pid:
            out.append(pkt[3] & 0x0F)
    return out


@pytest.mark.skipif(shutil.which("tsp") is None, reason="TSDuck tsp not installed")
def test_real_tsp_relay_makes_cc_continuous_across_session_reset() -> None:
    """Feed two 'encoder sessions' (CC restarting from 0 — the #151 splice)
    through a real tsp continuity --fix relay and assert the OUTPUT counters
    are continuous mod 16 with no repeats/jumps.

    What the 2026-07 rework changed, and what "robust" means here:

    * Both UDP sockets are context-managed, so ANY failure below still closes
      them. A leaked socket resurfaces later as an unraisable ResourceWarning
      that the "error" filterwarnings policy escalates onto whichever
      unrelated test the garbage collector interrupts — this test was one of
      the two leak sources poisoning the randomized-order lane.
    * The receive side is DEADLINE-DRIVEN (poll until enough packets arrive
      or 5s elapses), so the assertions never depend on a magic sleep being
      long enough on a loaded machine. The remaining time.sleep() calls only
      pace the SEND side (letting tsp bind, spacing packets, simulating the
      relaunch gap); they can make the test slower, never wrongly green or
      wrongly red.
    * The assertions test the PROPERTY (output continuity mod 16, no
      repeats/jumps across the session splice), not a byte-exact capture, so
      packet timing variation cannot flake the verdict.
    """
    listen, out_port = 17997, 17998
    recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Context-managed so a failure anywhere below (a busy 17998, a tsp that
    # will not spawn) still closes both. A leaked socket is not a local
    # problem: it resurfaces later as an *unraisable* ResourceWarning, which
    # the "error" filterwarnings policy escalates onto whichever unrelated
    # test the garbage collector happens to interrupt.
    with recv, send:
        recv.bind(("127.0.0.1", out_port))
        recv.settimeout(5.0)

        args = build_tsp_relay_args(
            shutil.which("tsp") or "tsp",
            listen_port=listen,
            dest_host="127.0.0.1",
            dest_port=out_port,
            local_out_port=17999,
            rcvbuf_bytes=1 << 20,
        )
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(1.0)  # let tsp bind
            # Session A: CC 0..9. Session B (relaunch): CC restarts at 0 — the
            # exact discontinuity a headend logs.
            for cc in range(10):
                send.sendto(_ts_packet(_PID, cc, 0xAA), ("127.0.0.1", listen))
                time.sleep(0.01)
            time.sleep(0.3)  # the "relaunch gap"
            for cc in range(10):
                send.sendto(_ts_packet(_PID, cc, 0xBB), ("127.0.0.1", listen))
                time.sleep(0.01)

            received = b""
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and len(received) < 188 * 18:
                try:
                    chunk, _ = recv.recvfrom(65536)
                    received += chunk
                except TimeoutError:
                    break
            ccs = _cc_sequence(received, _PID)
            assert len(ccs) >= 16, f"too few relayed packets: {len(ccs)}"
            for a, b in itertools.pairwise(ccs):
                assert b == (a + 1) % 16, f"CC discontinuity survived the relay: {ccs}"
        finally:
            proc.terminate()
            # terminate() only signals; it does not reap. Without wait() the
            # child stays unreaped and Popen.__del__ later emits "subprocess N
            # is still running" as an unraisable ResourceWarning, felling an
            # unrelated test the same way.
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover - defensive
                proc.kill()
                proc.wait(timeout=10)


# ---------------------------------------------------------------------------
# Daemon wiring: the relay is applied at encoder start and torn down on stop
# ---------------------------------------------------------------------------


def test_daemon_routes_udp_ts_through_relay_and_stops_it_on_stop(tmp_path) -> None:
    from datetime import UTC, datetime

    from civiccast.egress.daemon import EgressDaemon
    from civiccast.egress.models import EgressCommand, EgressSourcePlan, EgressSourceSegment
    from civiccast.egress.store import InMemoryEgressStore

    class _Proc:
        pid = 4242
        returncode: int | None = None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 0

    class _RecordingSupervisor:
        def __init__(self) -> None:
            self.applied: list[str] = []
            self.stopped: list[str] = []

        def apply(self, config):
            self.applied.append(config.channel_id)
            new_sinks = [
                s.model_copy(update={"uri": "udp://127.0.0.1:17800?pkt_size=1316"})
                if s.kind == "udp-ts"
                else s
                for s in config.sinks
            ]
            return config.model_copy(update={"sinks": new_sinks})

        def stop_channel(self, channel_id: str) -> None:
            self.stopped.append(channel_id)

    store = InMemoryEgressStore()
    store.upsert_config(
        EgressConfig(
            channel_id="gov",
            enabled=True,
            slate_message="slate",
            sinks=[EgressSinkSpec(kind="udp-ts", label="headend", uri="udp://239.1.2.3:5000")],
        )
    )
    source = tmp_path / "src.ts"
    source.write_text("x", encoding="utf-8")
    plan = EgressSourcePlan(
        channel_id="gov",
        segments=[EgressSourceSegment(label="seg", path=str(source), duration_seconds=1)],
    )
    supervisor = _RecordingSupervisor()
    captured: dict[str, list[str]] = {}
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _cid: plan,
        ffmpeg_starter=lambda args: captured.setdefault("args", args) and _Proc(),
        ts_relay_supervisor=supervisor,
    )

    def cmd(action: str) -> EgressCommand:
        return EgressCommand(
            channel_id="gov",
            action=action,  # type: ignore[arg-type]
            issued_at=datetime(2026, 7, 8, 12, 0, tzinfo=UTC),
            issued_by="operator",
            command_id=f"cmd-{action}",
        )

    store.enqueue_command(cmd("start"))
    assert daemon.process_once("gov") == 1
    assert supervisor.applied == ["gov"]
    # The encoder's udp-ts output goes to the relay's local port, not the headend.
    assert any("udp://127.0.0.1:17800" in a for a in captured["args"])
    assert not any("239.1.2.3" in a for a in captured["args"])

    store.enqueue_command(cmd("stop"))
    daemon.process_once("gov")
    assert supervisor.stopped == ["gov"]  # operator stop tears the relay down
