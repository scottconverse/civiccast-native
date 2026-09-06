# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from civiccast.cg.service import build_emergency_overlay, build_overlay_contract
from civiccast.egress.branding import build_branding_filter_plan
from civiccast.egress.caption_embed import SidecarCaptionEmbedder
from civiccast.egress.cg_bridge import (
    CG_EGRESS_PROOF_BOUNDARY,
    build_cg_overlay_egress_proof,
)
from civiccast.egress.daemon import _RESTART_ESCALATION_STREAK, EgressDaemon
from civiccast.egress.encoder_strategy import EncoderStartRequest, EncoderStartResult
from civiccast.egress.errors import SourcePrepareError
from civiccast.egress.models import (
    EgressCommand,
    EgressConfig,
    EgressSinkSpec,
    EgressSourcePlan,
    EgressSourceSegment,
    EgressStateRow,
)
from civiccast.egress.preparer import PreparedSegmentRecord, SourcePreparationReport
from civiccast.egress.store import InMemoryEgressStore
from civiccast.egress.supervisor import PlayoutSupervisor


def _write_fake_reload_status(
    work_dir: Path, channel_id: str, command_id: str | None, result: str
) -> None:
    """F1 redesign test helper: simulates ``worker.py``'s
    ``_write_reload_status`` -- writes the file ``EgressDaemon.
    _poll_reload_settlement`` polls for. ``command_id`` falls back to a fresh
    uuid (mirroring ``worker.py``'s own fallback) so a caller that doesn't
    pass one still produces a matchable id."""
    channel_dir = work_dir / channel_id
    channel_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"id": command_id or uuid.uuid4().hex, "result": result})
    (channel_dir / "reload-status.json").write_text(payload, encoding="utf-8")


class _FakeProcess:
    def __init__(self, *, pid: int = 4242, returncode: int | None = None) -> None:
        self.pid = pid
        self.returncode = returncode
        self.terminated = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0


def _start_fake_process(
    pending: list[_FakeProcess],
    started: list[_FakeProcess],
) -> _FakeProcess:
    process = pending.pop(0)
    started.append(process)
    return process


def _config(*, secret_ref: str | None = None) -> EgressConfig:
    return EgressConfig(
        channel_id="gov",
        enabled=True,
        slate_message="CivicCast is preparing the channel.",
        sinks=[
            EgressSinkSpec(
                kind="srt" if secret_ref else "file",
                label="Headend" if secret_ref else "Proof",
                uri="srt://headend.example:9000" if secret_ref else "build/out.ts",
                secret_ref=secret_ref,
            )
        ],
    )


def _source_plan(tmp_path: Path) -> EgressSourcePlan:
    source = tmp_path / "source-a.ts"
    source.write_text("fake", encoding="utf-8")
    return EgressSourcePlan(
        channel_id="gov",
        segments=[
            EgressSourceSegment(
                label="Council meeting",
                path=str(source),
                duration_seconds=1,
                source_ref="asset-council",
            )
        ],
    )


def _source_plan_with_label(tmp_path: Path, label: str) -> EgressSourcePlan:
    source = tmp_path / f"{label.replace(' ', '-').lower()}.ts"
    source.write_text(label, encoding="utf-8")
    return EgressSourcePlan(
        channel_id="gov",
        segments=[
            EgressSourceSegment(
                label=label,
                path=str(source),
                duration_seconds=1,
                source_ref=f"asset-{label.replace(' ', '-').lower()}",
            )
        ],
    )


def _live_source_plan(tmp_path: Path, label: str = "Live: Council chamber") -> EgressSourcePlan:
    source = tmp_path / "live-council-chamber.ts"
    source.write_text(label, encoding="utf-8")
    return EgressSourcePlan(
        channel_id="gov",
        segments=[
            EgressSourceSegment(
                label=label,
                path=str(source),
                duration_seconds=1,
                kind="live",
                source_ref="live-council-chamber",
            )
        ],
    )


def _slate_plan(tmp_path: Path) -> EgressSourcePlan:
    source = tmp_path / "slate.ts"
    source.write_text("slate", encoding="utf-8")
    return EgressSourcePlan(
        channel_id="gov",
        segments=[
            EgressSourceSegment(
                label="Fallback slate",
                path=str(source),
                duration_seconds=1,
                source_ref="civiccast-slate",
            )
        ],
    )


def _command(action: str = "start") -> EgressCommand:
    return EgressCommand(
        channel_id="gov",
        action=action,  # type: ignore[arg-type]
        issued_at=datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
        issued_by="operator",
        command_id=f"cmd-{action}",
    )


def test_daemon_processes_start_command_and_records_success_health(tmp_path: Path) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    captured: dict[str, list[str]] = {}
    process = _FakeProcess()

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        ffmpeg_starter=lambda args: captured.setdefault("args", args) and process,
    )

    assert daemon.process_once("gov") == 1

    state = store.read_state("gov")
    assert state is not None
    assert state.state == "ON_AIR"
    assert state.pid == 4242
    assert state.current_proof_event_id is not None
    assert captured["args"][-3:] == ["-f", "mpegts", "build/out.ts"]
    assert store.recent_health("gov", 1)[0].sink_connected == {"Proof": True}
    proof_events = store.recent_proof_events("gov", 1)
    assert proof_events[0].source_label == "Council meeting"
    assert proof_events[0].source_ref == "asset-council"
    assert proof_events[0].proof_boundary == "civiccast-egress-handoff-boundary"

    assert daemon.process_once("gov") == 0
    assert store.recent_health("gov", 1)[0].sink_connected == {"Proof": True}


def test_daemon_routes_storage_refusal_to_configured_fallback_slate_before_encoder_start(
    tmp_path: Path,
) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    started: list[list[str]] = []

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        fallback_source_provider=lambda _config: _slate_plan(tmp_path),
        caption_readiness_provider=lambda _channel_id: SimpleNamespace(
            ready=False,
            refusal_reason="free-space-reserve-unrestorable",
            requires_fallback_slate=True,
        ),
        ffmpeg_starter=lambda args: started.append(args) or _FakeProcess(),
    )

    assert daemon.process_once("gov") == 1

    state = store.read_state("gov")
    assert state is not None
    assert state.state == "FALLBACK_SLATE"
    assert state.last_error == "caption storage refused: free-space-reserve-unrestorable"
    concat_path = Path(next(arg for arg in started[0] if arg.endswith(".ffconcat")))
    assert concat_path.is_file()
    assert (tmp_path / "slate.ts").as_posix() in concat_path.read_text(encoding="utf-8")
    proof_events = store.recent_proof_events("gov", 1)
    assert proof_events[0].source_label == "Fallback slate"
    assert proof_events[0].source_ref == "civiccast-slate"
    assert proof_events[0].proof_boundary == "civiccast-egress-handoff-boundary"


def test_daemon_caption_sender_uses_its_running_encoder_strategy(tmp_path: Path) -> None:
    class _CaptionStrategy:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def send_caption_cue(
            self,
            channel_id: str,
            work_dir: Path,
            *,
            text: str,
            pts_seconds: float,
            duration_seconds: float,
            delivery_id: str,
        ) -> bool:
            self.calls.append(
                {
                    "channel_id": channel_id,
                    "work_dir": work_dir,
                    "text": text,
                    "pts_seconds": pts_seconds,
                    "duration_seconds": duration_seconds,
                    "delivery_id": delivery_id,
                }
            )
            return True

    strategy = _CaptionStrategy()
    daemon = EgressDaemon(
        InMemoryEgressStore(),
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: None,
        encoder_strategy=strategy,  # type: ignore[arg-type]
    )

    assert (
        daemon.send_caption_cue(
            "gov",
            tmp_path,
            text="Council meeting",
            pts_seconds=3.0,
            duration_seconds=1.5,
            delivery_id="caption-page-1",
        )
        is True
    )
    assert strategy.calls == [
        {
            "channel_id": "gov",
            "work_dir": tmp_path,
            "text": "Council meeting",
            "pts_seconds": 3.0,
            "duration_seconds": 1.5,
            "delivery_id": "caption-page-1",
        }
    ]


def test_daemon_prepares_source_plan_before_starting_encoder(tmp_path: Path) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    process = _FakeProcess()
    raw_plan = _source_plan(tmp_path)
    prepared_path = tmp_path / "prepared.ts"
    prepared_path.write_text("prepared", encoding="utf-8")
    prepared_plan = EgressSourcePlan(
        channel_id="gov",
        segments=[
            EgressSourceSegment(
                label="Prepared council meeting",
                path=str(prepared_path),
                duration_seconds=1,
            )
        ],
    )
    seen: dict[str, object] = {}

    def prepare(source_plan: EgressSourcePlan, config: EgressConfig) -> SourcePreparationReport:
        seen["source_plan"] = source_plan
        seen["config"] = config
        return SourcePreparationReport(
            source_plan=prepared_plan,
            records=(
                PreparedSegmentRecord(
                    label="Prepared council meeting",
                    source_path=str(raw_plan.segments[0].path),
                    prepared_path=str(prepared_path),
                    loudness_status="ok",
                    measured_lufs=-23.9,
                    normalized=False,
                ),
            ),
        )

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: raw_plan,
        source_preparer=prepare,
        ffmpeg_starter=lambda _args: process,
    )

    daemon.process_once("gov")

    state = store.read_state("gov")
    assert state is not None
    assert state.current_source_label == "Prepared council meeting"
    assert state.current_proof_event_id is not None
    assert store.recent_proof_events("gov", 1)[0].source_path == str(prepared_path)
    assert store.recent_health("gov", 1)[0].last_loudness_lufs == -23.9
    assert seen == {"source_plan": raw_plan, "config": _config()}


def test_daemon_passes_branding_plan_to_encoder_args(tmp_path: Path) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    captured: dict[str, list[str]] = {}
    process = _FakeProcess()
    branding_plan = build_branding_filter_plan(
        overlay_contract=build_overlay_contract(channel_id="gov"),
        snapshot_base_url="http://127.0.0.1:8000",
    )

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        branding_plan_provider=lambda _channel_id: branding_plan,
        ffmpeg_starter=lambda args: captured.setdefault("args", args) and process,
    )

    daemon.process_once("gov")

    assert "-filter_complex" in captured["args"]
    assert branding_plan.filter_complex in captured["args"]
    assert f"[{branding_plan.output_video_label}]" in captured["args"]


def test_daemon_passes_caption_plan_to_encoder_args(tmp_path: Path) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    captured: dict[str, list[str]] = {}
    process = _FakeProcess()
    sidecar = tmp_path / "captions.vtt"
    caption_plan = SidecarCaptionEmbedder(sidecar_path=sidecar).build_plan(
        channel_id="gov",
        cues=[],
    )

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        caption_plan_provider=lambda _channel_id: caption_plan,
        ffmpeg_starter=lambda args: captured.setdefault("args", args) and process,
    )

    daemon.process_once("gov")

    assert str(sidecar) in captured["args"]
    assert "1:s:0?" in captured["args"]
    assert captured["args"].index(str(sidecar)) < captured["args"].index("1:s:0?")


def test_daemon_surfaces_verified_caption_status_from_decode_back_provider(
    tmp_path: Path,
) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    process = _FakeProcess()

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        caption_status_provider=lambda _channel_id: "on",
        ffmpeg_starter=lambda _args: process,
    )

    daemon.process_once("gov")

    assert store.recent_health("gov", 1)[0].caption_status == "on"


def test_daemon_records_cg_overlay_raise_and_clear_lifecycle(tmp_path: Path) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    process = _FakeProcess()
    active_overlay = build_cg_overlay_egress_proof(
        overlay=build_emergency_overlay(overlay_id="notice-1", severity="warning"),
        overlay_contract=build_overlay_contract(channel_id="gov"),
    )
    overlay_enabled = True

    def overlay_provider(_channel_id: str):
        return active_overlay if overlay_enabled else None

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        cg_overlay_proof_provider=overlay_provider,
        ffmpeg_starter=lambda _args: process,
    )

    daemon.process_once("gov")

    overlay_events = [
        event
        for event in store.recent_proof_events("gov", 5)
        if event.proof_boundary == CG_EGRESS_PROOF_BOUNDARY
    ]
    assert len(overlay_events) == 1
    assert overlay_events[0].source_label == "CivicCast emergency banner"
    assert overlay_events[0].source_ref == "notice-1"
    assert "raised emergency banner" in overlay_events[0].machine_summary
    assert "not an EAS claim" in overlay_events[0].machine_summary

    daemon.process_once("gov")

    overlay_events = [
        event
        for event in store.recent_proof_events("gov", 5)
        if event.proof_boundary == CG_EGRESS_PROOF_BOUNDARY
    ]
    assert len(overlay_events) == 1

    overlay_enabled = False
    daemon.process_once("gov")

    overlay_events = [
        event
        for event in store.recent_proof_events("gov", 5)
        if event.proof_boundary == CG_EGRESS_PROOF_BOUNDARY
    ]
    assert [event.source_label for event in overlay_events] == [
        "CivicCast emergency banner cleared",
        "CivicCast emergency banner",
    ]
    assert "cleared emergency banner" in overlay_events[0].machine_summary
    assert "not an EAS claim" in overlay_events[0].machine_summary


def test_daemon_clears_active_cg_overlay_on_stop(tmp_path: Path) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    process = _FakeProcess()
    active_overlay = build_cg_overlay_egress_proof(
        overlay=build_emergency_overlay(overlay_id="notice-1", severity="warning"),
        overlay_contract=build_overlay_contract(channel_id="gov"),
    )
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        cg_overlay_proof_provider=lambda _channel_id: active_overlay,
        ffmpeg_starter=lambda _args: process,
    )

    daemon.process_once("gov")
    store.enqueue_command(_command("stop"))
    daemon.process_once("gov")

    overlay_events = [
        event
        for event in store.recent_proof_events("gov", 5)
        if event.proof_boundary == CG_EGRESS_PROOF_BOUNDARY
    ]
    assert [event.source_label for event in overlay_events] == [
        "CivicCast emergency banner cleared",
        "CivicCast emergency banner",
    ]
    assert overlay_events[0].state == "STOPPING"


def test_daemon_clears_active_cg_overlay_when_encoder_exits(tmp_path: Path) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    process = _FakeProcess()
    active_overlay = build_cg_overlay_egress_proof(
        overlay=build_emergency_overlay(overlay_id="notice-1", severity="warning"),
        overlay_contract=build_overlay_contract(channel_id="gov"),
    )
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        cg_overlay_proof_provider=lambda _channel_id: active_overlay,
        ffmpeg_starter=lambda _args: process,
    )

    daemon.process_once("gov")
    process.returncode = 0
    daemon.process_once("gov")

    overlay_events = [
        event
        for event in store.recent_proof_events("gov", 5)
        if event.proof_boundary == CG_EGRESS_PROOF_BOUNDARY
    ]
    assert [event.source_label for event in overlay_events] == [
        "CivicCast emergency banner cleared",
        "CivicCast emergency banner",
    ]
    assert overlay_events[0].state == "STOPPED"


def test_daemon_writes_fallback_slate_when_no_source_plan(tmp_path: Path) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: None,
    )

    daemon.process_once("gov")

    state = store.read_state("gov")
    assert state is not None
    assert state.state == "FALLBACK_SLATE"
    assert "Slate generation is required" in (state.last_error or "")


def test_daemon_logs_last_error_at_info_on_fallback_slate_transition(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Gate A T4 diagnosability fix (2026-09): ``_write_state`` is the ONE
    choke point every pipeline state transition passes through, including
    every ``FALLBACK_SLATE`` entry's ``last_error``. Before this fix the
    control-plane child process had no configured handler for the
    ``civiccast`` logger at any level, so this record was silently dropped
    even though the STATE it describes was durably persisted -- Gate A's T4
    probe found ``engine_state=FALLBACK_SLATE`` with no trail explaining
    why. Proves the daemon actually emits an INFO record naming both the
    new state and the fallback reason (``last_error``), which is the record
    ``configure_control_plane_logging`` now makes reach a file."""

    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: None,
    )

    with caplog.at_level("INFO", logger="civiccast.egress.daemon"):
        daemon.process_once("gov")

    state = store.read_state("gov")
    assert state is not None
    assert state.state == "FALLBACK_SLATE"
    assert state.last_error is not None

    info_records = [r for r in caplog.records if r.levelname == "INFO"]
    assert any(
        "FALLBACK_SLATE" in r.getMessage() and state.last_error in r.getMessage()
        for r in info_records
    ), [r.getMessage() for r in info_records]


def test_daemon_runs_fallback_slate_provider_when_no_source_plan(tmp_path: Path) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    captured: dict[str, list[str]] = {}
    process = _FakeProcess()
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: None,
        fallback_source_provider=lambda _config: _slate_plan(tmp_path),
        ffmpeg_starter=lambda args: captured.setdefault("args", args) and process,
    )

    daemon.process_once("gov")

    state = store.read_state("gov")
    assert state is not None
    assert state.state == "FALLBACK_SLATE"
    assert state.current_source_label == "Fallback slate"
    assert state.current_proof_event_id is not None
    assert any("egress-source-plan.ffconcat" in arg for arg in captured["args"])
    proof_event = store.recent_proof_events("gov", 1)[0]
    assert proof_event.state == "FALLBACK_SLATE"
    assert proof_event.source_label == "Fallback slate"
    assert "entered fallback slate" in proof_event.machine_summary
    assert store.recent_health("gov", 1)[0].state == "FALLBACK_SLATE"

    daemon.process_once("gov")

    state_after_poll = store.read_state("gov")
    assert state_after_poll is not None
    assert state_after_poll.state == "FALLBACK_SLATE"
    assert state_after_poll.current_proof_event_id == proof_event.event_id


def test_daemon_airs_fallback_slate_when_source_provider_fails(
    tmp_path: Path,
) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    process = _FakeProcess()

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: (_ for _ in ()).throw(
            SourcePrepareError("Scheduled asset is missing.")
        ),
        fallback_source_provider=lambda _config: _slate_plan(tmp_path),
        ffmpeg_starter=lambda _args: process,
    )

    daemon.process_once("gov")

    state = store.read_state("gov")
    assert state is not None
    assert state.state == "FALLBACK_SLATE"
    assert state.current_source_label == "Fallback slate"
    assert state.last_error == "Scheduled asset is missing."
    assert store.recent_proof_events("gov", 1)[0].state == "FALLBACK_SLATE"


def test_daemon_airs_fallback_slate_when_source_preparation_fails(
    tmp_path: Path,
) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    process = _FakeProcess()

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        fallback_source_provider=lambda _config: _slate_plan(tmp_path),
        source_preparer=lambda _source_plan, _config: (_ for _ in ()).throw(
            SourcePrepareError("Program asset could not be conformed.")
        ),
        ffmpeg_starter=lambda _args: process,
    )

    daemon.process_once("gov")

    state = store.read_state("gov")
    assert state is not None
    assert state.state == "FALLBACK_SLATE"
    assert state.current_source_label == "Fallback slate"
    assert state.last_error == "Program asset could not be conformed."
    assert store.recent_health("gov", 1)[0].state == "FALLBACK_SLATE"


def test_daemon_records_fallback_slate_exit_on_reload(tmp_path: Path) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    source_available = False
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222)]
    started: list[_FakeProcess] = []

    def source_provider(_channel_id: str) -> EgressSourcePlan | None:
        return _source_plan(tmp_path) if source_available else None

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=source_provider,
        fallback_source_provider=lambda _config: _slate_plan(tmp_path),
        ffmpeg_starter=lambda _args: _start_fake_process(processes, started),
    )

    daemon.process_once("gov")
    store.enqueue_command(_command("reload"))
    source_available = True
    daemon.process_once("gov")
    started[0].returncode = 0

    daemon.process_once("gov")

    state = store.read_state("gov")
    assert state is not None
    assert state.state == "ON_AIR"
    assert state.current_source_label == "Council meeting"
    proof_events = store.recent_proof_events("gov", 3)
    assert proof_events[0].state == "ON_AIR"
    assert "exited fallback slate" in proof_events[0].machine_summary
    assert proof_events[1].state == "TRANSITIONING"
    assert "from 'Fallback slate' to 'Council meeting'" in proof_events[1].machine_summary
    assert proof_events[2].state == "FALLBACK_SLATE"
    assert processes == []


def test_daemon_records_source_to_source_transition_on_reload(tmp_path: Path) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222)]
    started: list[_FakeProcess] = []
    current_label = "Council meeting"

    def source_provider(_channel_id: str) -> EgressSourcePlan:
        source = tmp_path / f"{current_label.replace(' ', '-').lower()}.ts"
        source.write_text(current_label, encoding="utf-8")
        return EgressSourcePlan(
            channel_id="gov",
            segments=[
                EgressSourceSegment(label=current_label, path=str(source), duration_seconds=1)
            ],
        )

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=source_provider,
        ffmpeg_starter=lambda _args: _start_fake_process(processes, started),
    )

    daemon.process_once("gov")
    current_label = "Mayor interview"
    store.enqueue_command(_command("reload"))
    daemon.process_once("gov")

    transition_state = store.read_state("gov")
    assert transition_state is not None
    assert transition_state.state == "TRANSITIONING"
    assert started[0].terminated is False

    started[0].returncode = 0
    daemon.process_once("gov")

    state = store.read_state("gov")
    assert state is not None
    assert state.state == "ON_AIR"
    assert state.current_source_label == "Mayor interview"
    proof_events = store.recent_proof_events("gov", 3)
    assert [event.state for event in proof_events] == ["ON_AIR", "TRANSITIONING", "ON_AIR"]
    assert proof_events[0].source_label == "Mayor interview"
    assert proof_events[1].source_label == "Mayor interview"
    assert "from 'Council meeting' to 'Mayor interview'" in proof_events[1].machine_summary


class _FakeContentReloadStrategy:
    """A content-reload-capable strategy (stands in for GstPlayoutStrategy) so the
    daemon's seamless-reload routing can be exercised without gi (S15 / D-S1-6)."""

    name = "fake-gst-content-reload"
    supports_live_swap = True
    supports_content_reload = True

    def __init__(
        self,
        processes: list[_FakeProcess],
        started: list[_FakeProcess],
        *,
        reload_ok: bool = True,
        reload_exc: Exception | None = None,
        # F1/F9: False lets a test control settlement timing itself (simulate
        # a deferred switch that stays pending across several poll ticks)
        # instead of the fake auto-settling "applied" the instant it arms.
        auto_settle: bool = True,
    ) -> None:
        self._processes = processes
        self._started = started
        self._reload_ok = reload_ok
        self._reload_exc = reload_exc
        self._auto_settle = auto_settle
        self.reload_calls: list[str] = []
        self.reload_ids: list[str | None] = []
        # B3 fix: records what each reload_content call was asked for, so tests
        # can pin daemon.py's should_defer_switch wiring (_try_content_reload
        # sets EncoderStartRequest.switch_at_end_of_current).
        self.switch_at_end_of_current_calls: list[bool] = []

    def start(self, request: EncoderStartRequest) -> EncoderStartResult:
        process = self._processes.pop(0)
        self._started.append(process)
        return EncoderStartResult(
            process=process,
            concat_plan_path=request.work_dir / "playout-graph.json",
            stdout_path=request.work_dir / "out.log",
            stderr_path=request.work_dir / "err.log",
            args=("worker",),
        )

    def swap_role(self, channel_id: str, work_dir: Path, role: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def reload_content(
        self,
        channel_id: str,
        work_dir: Path,
        request: EncoderStartRequest,
        *,
        command_id: str | None = None,
    ) -> bool:
        self.reload_calls.append(request.source_plan.segments[0].label)
        self.reload_ids.append(command_id)
        self.switch_at_end_of_current_calls.append(request.switch_at_end_of_current)
        if self._reload_exc is not None:
            raise self._reload_exc
        if self._reload_ok and self._auto_settle:
            # F1 redesign: True now means ARMED, and the daemon defers its
            # ON_AIR bookkeeping to _poll_reload_settlement observing
            # reload-status.json -- this fake simulates an immediate,
            # instantly-settling reload (the common case: switch_at_end_of_
            # current=False commits on the new leg's first buffer) by writing
            # that file right away. A test that needs to see the daemon's
            # POST-settlement state therefore calls process_once() ONE MORE
            # TIME after the reload -- the same shape a real deferred switch
            # takes, just compressed to zero wall-clock delay. A test that
            # constructs this fake with auto_settle=False controls the status
            # file itself (F9: proving the daemon does not terminate the
            # worker while genuinely still awaiting settlement).
            _write_fake_reload_status(work_dir, channel_id, command_id, "applied")
        return self._reload_ok


class _FakeNonReloadCapableStrategy(_FakeContentReloadStrategy):
    """Identical to ``_FakeContentReloadStrategy`` except it does NOT declare
    ``supports_content_reload`` -- ``_request_reload``'s own guard
    (``getattr(self._encoder_strategy, "supports_content_reload", False)``)
    must short-circuit to the restart path before ``_try_content_reload`` is
    ever called, so ``reload_calls`` staying empty is the proof."""

    supports_content_reload = False


def test_content_reload_swaps_program_in_place_without_restart(tmp_path: Path) -> None:
    """D-S1-6: a content-reload-capable strategy applies a newly-due program in
    place — no TRANSITIONING, no second process, the running encoder is untouched —
    and the proof chain still records the source-to-source transition."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222)]
    started: list[_FakeProcess] = []
    current_label = "Council meeting"

    def source_provider(_channel_id: str) -> EgressSourcePlan:
        return _source_plan_with_label(tmp_path, current_label)

    strategy = _FakeContentReloadStrategy(processes, started)
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=source_provider,
        encoder_strategy=strategy,
    )

    daemon.process_once("gov")
    current_label = "Mayor interview"
    store.enqueue_command(_command("reload"))
    daemon.process_once("gov")

    # seamless: the worker stayed up, no second encoder was started, no kill
    assert strategy.reload_calls == ["Mayor interview"]
    assert len(started) == 1
    assert started[0].terminated is False
    assert len(processes) == 1 and processes[0].pid == 222  # the spare was never started

    # F1 redesign: the reload is ARMED after the process_once above (the fake
    # strategy already wrote reload-status.json "applied"), but the daemon's
    # ON_AIR bookkeeping only lands once _poll_reload_settlement observes it --
    # one more tick, exactly like a real deferred switch settling later.
    daemon.process_once("gov")

    state = store.read_state("gov")
    assert state is not None
    assert state.state == "ON_AIR"
    assert state.current_source_label == "Mayor interview"
    # the live state never left ON_AIR (output never went down), but the proof chain
    # still records the source-to-source transition for parity with the restart path
    proof_events = store.recent_proof_events("gov", 3)
    assert [event.state for event in proof_events] == ["ON_AIR", "TRANSITIONING", "ON_AIR"]
    assert proof_events[0].source_label == "Mayor interview"
    assert "from 'Council meeting' to 'Mayor interview'" in proof_events[1].machine_summary


def test_content_reload_defers_switch_for_an_on_air_reload_with_no_override(
    tmp_path: Path,
) -> None:
    """B3 fix: an ON_AIR reload with no operator override active (the shape
    channel-automation's plan-rollover reload takes) asks the strategy to
    defer the selector switch to the outgoing leg's own EOS -- see
    ``reload_policy.should_defer_switch``."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222)]
    started: list[_FakeProcess] = []
    current_label = "Council meeting"

    def source_provider(_channel_id: str) -> EgressSourcePlan:
        return _source_plan_with_label(tmp_path, current_label)

    strategy = _FakeContentReloadStrategy(processes, started)
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=source_provider,
        encoder_strategy=strategy,
    )

    daemon.process_once("gov")  # initial start -> ON_AIR
    current_label = "Mayor interview"
    store.enqueue_command(_command("reload"))
    daemon.process_once("gov")

    assert strategy.switch_at_end_of_current_calls == [True]


def test_content_reload_cuts_immediately_when_the_recorded_rollover_horizon_has_already_passed(
    tmp_path: Path,
) -> None:
    """Item 78 fix 3: ``ChannelAutomationService`` records the ``plan_end_at`` it
    computed for a rollover reload (``record_rollover_plan_end``) before
    enqueuing it. If that horizon has already passed by the time the reload
    actually dispatches (e.g. the automation pass itself blocked for a long
    time before reaching this channel), deferring the switch to the outgoing
    leg's own EOS is deferring to a boundary that already happened and will
    never arrive -- the switch must cut in immediately instead, even though
    this is otherwise the exact B3 "ON_AIR, no override" shape that would
    normally defer (see the test above)."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222)]
    started: list[_FakeProcess] = []
    current_label = "Council meeting"

    def source_provider(_channel_id: str) -> EgressSourcePlan:
        return _source_plan_with_label(tmp_path, current_label)

    strategy = _FakeContentReloadStrategy(processes, started)
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=source_provider,
        encoder_strategy=strategy,
    )

    daemon.process_once("gov")  # initial start -> ON_AIR
    current_label = "Mayor interview"
    daemon.record_rollover_plan_end("gov", datetime(2020, 1, 1, tzinfo=UTC))  # already long past
    store.enqueue_command(_command("reload"))
    daemon.process_once("gov")

    assert strategy.switch_at_end_of_current_calls == [False]


def test_record_rollover_plan_end_is_consumed_once_and_never_leaks_to_a_later_reload(
    tmp_path: Path,
) -> None:
    """Item 78 fix 3: the recorded horizon is popped (not merely read) by
    ``_try_content_reload`` -- a stale value from an earlier, already-settled
    rollover must never silently apply to a LATER, unrelated reload of the
    same channel (e.g. a second automation-driven ON_AIR extension with no
    override, which should defer normally)."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222), _FakeProcess(pid=333)]
    started: list[_FakeProcess] = []
    current_label = "Council meeting"

    def source_provider(_channel_id: str) -> EgressSourcePlan:
        return _source_plan_with_label(tmp_path, current_label)

    strategy = _FakeContentReloadStrategy(processes, started)
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=source_provider,
        encoder_strategy=strategy,
    )

    daemon.process_once("gov")  # initial start -> ON_AIR
    current_label = "Mayor interview"
    daemon.record_rollover_plan_end("gov", datetime(2020, 1, 1, tzinfo=UTC))  # already long past
    store.enqueue_command(_command("reload"))
    daemon.process_once("gov")
    assert strategy.switch_at_end_of_current_calls == [False]
    # F1 redesign: the first reload is ARMED, not yet settled -- one more
    # tick lets _poll_reload_settlement observe reload-status.json and
    # finish the ON_AIR bookkeeping before a second reload is requested
    # (mirrors test_content_reload_swaps_program_in_place_without_restart
    # above).
    daemon.process_once("gov")

    current_label = "Second Program"
    # A distinct command_id -- `_command("reload")` always returns the SAME
    # id, and the store treats re-enqueuing an already-consumed id as a
    # no-op (see the identical pattern elsewhere in this file).
    store.enqueue_command(_command("reload").model_copy(update={"command_id": "cmd-reload-2"}))
    daemon.process_once("gov")

    # The stale plan_end_at from the FIRST reload must not still apply here --
    # this second reload, with nothing recorded for it, defers normally.
    assert strategy.switch_at_end_of_current_calls == [False, True]


def test_content_reload_disabled_config_pops_the_recorded_plan_end_without_using_it(
    tmp_path: Path,
) -> None:
    """Coordinator review, round 2, item 3: ``record_rollover_plan_end``'s value
    used to be popped only at the point ``EncoderStartRequest`` was actually
    built -- every early return ABOVE that point (disabled config, a
    SourcePrepareError from the provider or the preparer, a foreign/None
    plan) left it sitting in ``_rollover_plan_end_at``, where it would
    silently apply to whatever reload for this channel came next, however
    unrelated. It must now be consumed (popped) at the very top of
    ``_try_content_reload``, before any of those early returns -- this test
    covers the disabled-config path."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222)]
    started: list[_FakeProcess] = []
    current_label = "Council meeting"

    def source_provider(_channel_id: str) -> EgressSourcePlan:
        return _source_plan_with_label(tmp_path, current_label)

    strategy = _FakeContentReloadStrategy(processes, started)
    daemon = EgressDaemon(
        store, work_dir=tmp_path, source_plan_provider=source_provider, encoder_strategy=strategy
    )
    daemon.process_once("gov")  # initial start -> ON_AIR

    daemon.record_rollover_plan_end("gov", datetime(2020, 1, 1, tzinfo=UTC))
    store.upsert_config(_config().model_copy(update={"enabled": False}))
    store.enqueue_command(_command("reload"))
    daemon.process_once("gov")

    assert strategy.reload_calls == []  # never reached reload_content
    assert daemon._rollover_plan_end_at == {}  # popped, not left leaking


def test_content_reload_source_prepare_error_from_provider_pops_the_recorded_plan_end(
    tmp_path: Path,
) -> None:
    """Coordinator review, round 2, item 3 -- the provider-raises-
    SourcePrepareError early-return path."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222)]
    started: list[_FakeProcess] = []
    current_label = "Council meeting"
    fail_next = False

    def source_provider(_channel_id: str) -> EgressSourcePlan:
        if fail_next:
            raise SourcePrepareError("Scheduled asset is missing.")
        return _source_plan_with_label(tmp_path, current_label)

    strategy = _FakeContentReloadStrategy(processes, started)
    daemon = EgressDaemon(
        store, work_dir=tmp_path, source_plan_provider=source_provider, encoder_strategy=strategy
    )
    daemon.process_once("gov")  # initial start -> ON_AIR

    daemon.record_rollover_plan_end("gov", datetime(2020, 1, 1, tzinfo=UTC))
    fail_next = True
    store.enqueue_command(_command("reload"))
    daemon.process_once("gov")

    assert strategy.reload_calls == []
    assert daemon._rollover_plan_end_at == {}


def test_content_reload_source_prepare_error_from_preparer_pops_the_recorded_plan_end(
    tmp_path: Path,
) -> None:
    """Coordinator review, round 2, item 3 -- the preparer-raises-
    SourcePrepareError early-return path (a cold-conform failure, distinct
    from the provider-level failure above)."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222)]
    started: list[_FakeProcess] = []
    current_label = "Council meeting"
    fail_next = False

    def source_provider(_channel_id: str) -> EgressSourcePlan:
        return _source_plan_with_label(tmp_path, current_label)

    def source_preparer(source_plan: EgressSourcePlan, _config: EgressConfig) -> object:
        if fail_next:
            raise SourcePrepareError("Program asset could not be conformed.")
        return SimpleNamespace(source_plan=source_plan, plan_dir=None, records=[])

    strategy = _FakeContentReloadStrategy(processes, started)
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=source_provider,
        source_preparer=source_preparer,
        encoder_strategy=strategy,
    )
    daemon.process_once("gov")  # initial start -> ON_AIR

    daemon.record_rollover_plan_end("gov", datetime(2020, 1, 1, tzinfo=UTC))
    fail_next = True
    store.enqueue_command(_command("reload"))
    daemon.process_once("gov")

    assert strategy.reload_calls == []
    assert daemon._rollover_plan_end_at == {}


def test_content_reload_foreign_channel_plan_pops_the_recorded_plan_end(tmp_path: Path) -> None:
    """Coordinator review, round 2, item 3 -- the foreign/mismatched-channel
    plan early-return path (mirrors
    test_content_reload_foreign_channel_plan_falls_back_to_restart below)."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222)]
    started: list[_FakeProcess] = []
    foreign = False

    def source_provider(_channel_id: str) -> EgressSourcePlan:
        plan = _source_plan_with_label(
            tmp_path, "Mayor interview" if foreign else "Council meeting"
        )
        if foreign:
            object.__setattr__(plan, "channel_id", "someone-else")
        return plan

    strategy = _FakeContentReloadStrategy(processes, started)
    daemon = EgressDaemon(
        store, work_dir=tmp_path, source_plan_provider=source_provider, encoder_strategy=strategy
    )
    daemon.process_once("gov")  # initial start -> ON_AIR

    daemon.record_rollover_plan_end("gov", datetime(2020, 1, 1, tzinfo=UTC))
    foreign = True
    store.enqueue_command(_command("reload"))
    daemon.process_once("gov")

    assert strategy.reload_calls == []  # foreign plan rejected before reload_content
    assert daemon._rollover_plan_end_at == {}


def test_request_reload_worker_missing_or_dead_pops_the_recorded_plan_end(tmp_path: Path) -> None:
    """Coordinator review, round 3, item A: ``_request_reload`` has THREE
    early returns of its own that never reach ``_try_content_reload`` at
    all -- round 2 only closed the leak paths INSIDE that method. This one
    is "the worker is missing or has exited" (``_request_reload`` routes to
    ``_start`` instead, and never calls ``_try_content_reload``)."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222)]
    started: list[_FakeProcess] = []
    current_label = "Council meeting"

    def source_provider(_channel_id: str) -> EgressSourcePlan:
        return _source_plan_with_label(tmp_path, current_label)

    strategy = _FakeContentReloadStrategy(processes, started)
    daemon = EgressDaemon(
        store, work_dir=tmp_path, source_plan_provider=source_provider, encoder_strategy=strategy
    )
    daemon.process_once("gov")  # initial start -> ON_AIR

    daemon.record_rollover_plan_end("gov", datetime(2020, 1, 1, tzinfo=UTC))
    started[0].returncode = 0  # the worker died
    current_label = "Mayor interview"
    store.enqueue_command(_command("reload"))
    daemon.process_once("gov")

    assert strategy.reload_calls == []  # _try_content_reload was never reached
    assert len(started) == 2  # restarted instead
    assert daemon._rollover_plan_end_at == {}


def test_request_reload_no_state_row_pops_the_recorded_plan_end(tmp_path: Path) -> None:
    """Coordinator review, round 3, item A -- "no state row" (the ``state is
    not None and ...`` guard short-circuits before ``_try_content_reload``
    is ever called, falling straight to the terminate+restart path).

    Calls ``_request_reload`` directly (rather than via ``process_once``'s
    command loop): ``process_once`` runs ``_poll_process`` on every tick
    BEFORE draining commands, and ``_poll_process`` re-establishes a state
    row for any channel with a live process (deriving one from whatever the
    current health/draining/pending-reload bookkeeping says) -- which would
    mask "no state row" the instant a real "reload" command was queued
    alongside it. A genuinely missing state row against a live, tracked
    process is exactly what this guard exists to handle regardless."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    processes: list[_FakeProcess] = []
    started: list[_FakeProcess] = []
    strategy = _FakeContentReloadStrategy(processes, started)
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _cid: _source_plan_with_label(tmp_path, "Council meeting"),
        encoder_strategy=strategy,
    )
    daemon._processes["gov"] = _FakeProcess(pid=111)  # type: ignore[attr-defined]
    # Deliberately no store.write_state call -- no state row exists at all.

    daemon.record_rollover_plan_end("gov", datetime(2020, 1, 1, tzinfo=UTC))
    daemon._request_reload("gov")  # type: ignore[attr-defined]

    assert strategy.reload_calls == []  # _try_content_reload was never reached
    assert daemon._rollover_plan_end_at == {}


def test_request_reload_strategy_without_support_pops_the_recorded_plan_end(
    tmp_path: Path,
) -> None:
    """Coordinator review, round 3, item A -- the strategy doesn't declare
    ``supports_content_reload`` (``_request_reload``'s ``getattr`` guard
    short-circuits before ``_try_content_reload`` is ever called)."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222)]
    started: list[_FakeProcess] = []
    current_label = "Council meeting"

    def source_provider(_channel_id: str) -> EgressSourcePlan:
        return _source_plan_with_label(tmp_path, current_label)

    strategy = _FakeNonReloadCapableStrategy(processes, started)
    daemon = EgressDaemon(
        store, work_dir=tmp_path, source_plan_provider=source_provider, encoder_strategy=strategy
    )
    daemon.process_once("gov")  # initial start -> ON_AIR

    daemon.record_rollover_plan_end("gov", datetime(2020, 1, 1, tzinfo=UTC))
    current_label = "Mayor interview"
    store.enqueue_command(_command("reload"))
    daemon.process_once("gov")

    assert strategy.reload_calls == []  # _try_content_reload was never reached
    assert daemon._rollover_plan_end_at == {}


def test_request_reload_after_a_same_tick_crash_relaunch_still_sees_the_recorded_plan_end(
    tmp_path: Path,
) -> None:
    """Coordinator review, round 4, item 1 -- REGRESSION in b4508ef (round 3).

    Item 78's own diagnosed scenario is a worker crash whose relaunch
    (``_poll_process`` -> ``_relaunch_after_crash`` -> ``_begin_relaunch`` ->
    ``_start``) runs BEFORE that same ``process_once`` tick's queued
    "reload" command is drained (``process_once`` runs its poll tuple,
    ``_poll_process`` included, before ``pop_pending_commands``). A round-3
    revision popped ``self._rollover_plan_end_at`` inside ``_start`` too
    (defense-in-depth, or so it seemed) -- but ``_start``'s pop ran FIRST,
    during the poll phase, and ate the value ``_request_reload``'s own pop
    needed moments later during command draining: MEASURED, ff5cdfb (round
    2) cut immediately here as it should; b4508ef (round 3) silently
    deferred instead (an up-to-900s held leg on a switch that should have
    cut immediately). Only ``_request_reload`` and ``_stop`` may ever pop
    this dict now; ``_start`` must not."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222)]
    started: list[_FakeProcess] = []
    current_label = "Council meeting"

    def source_provider(_channel_id: str) -> EgressSourcePlan:
        return _source_plan_with_label(tmp_path, current_label)

    strategy = _FakeContentReloadStrategy(processes, started)
    daemon = EgressDaemon(
        store, work_dir=tmp_path, source_plan_provider=source_provider, encoder_strategy=strategy
    )
    daemon.process_once("gov")  # initial start -> ON_AIR (process 111)

    # Automation recorded a rollover plan_end that has already passed by the
    # time this reload actually dispatches -- should_defer_switch must cut
    # immediately for it, never defer.
    daemon.record_rollover_plan_end("gov", datetime(2020, 1, 1, tzinfo=UTC))
    current_label = "Mayor interview"
    started[0].returncode = 1  # the worker crashes
    store.enqueue_command(_command("reload"))
    # ONE process_once tick: _poll_process observes the crash and relaunches
    # (a fresh process 222, via _start) BEFORE the queued "reload" command
    # drains and reaches _request_reload / _try_content_reload.
    daemon.process_once("gov")

    assert len(started) == 2  # the crash-relaunch really did happen first
    assert strategy.reload_calls == ["Mayor interview"]  # the seamless path still ran
    assert strategy.switch_at_end_of_current_calls == [False]  # cut immediately, not deferred
    assert daemon._rollover_plan_end_at == {}


def test_stop_clears_the_recorded_rollover_plan_end(tmp_path: Path) -> None:
    """Coordinator review, round 4, item 2(b): ``_stop`` must clear
    ``_rollover_plan_end_at`` too (the channel going dark makes any in-
    flight rollover moot) -- a test that FAILS if that pop is reverted,
    unlike the suite as a whole (nothing else exercises this path)."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111)]
    started: list[_FakeProcess] = []
    strategy = _FakeContentReloadStrategy(processes, started)
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _cid: _source_plan_with_label(tmp_path, "Council meeting"),
        encoder_strategy=strategy,
    )
    daemon.process_once("gov")  # initial start -> ON_AIR

    daemon.record_rollover_plan_end("gov", datetime(2020, 1, 1, tzinfo=UTC))
    assert daemon._rollover_plan_end_at == {"gov": datetime(2020, 1, 1, tzinfo=UTC)}

    store.enqueue_command(_command("stop"))
    daemon.process_once("gov")

    assert daemon._rollover_plan_end_at == {}


def test_worker_clean_exit_then_restart_then_plain_reload_does_not_leak_stale_rollover_plan_end(
    tmp_path: Path,
) -> None:
    """Coordinator review, round 5, item 1 -- REGRESSION left by round 4.

    Round 4's own docstring claimed a stale ``_rollover_plan_end_at`` entry
    could never reach ``should_defer_switch`` because ``_request_reload``
    pops it first -- false: the pop PASSES the value down (as
    ``rollover_plan_end_at=``) into ``_try_content_reload`` and from there
    into ``should_defer_switch``, it does not discard it. A worker that
    exits cleanly (rc=0, no pending reload) never reaches ``_stop`` --
    that route is ``_poll_process`` observing the exit on its own, not an
    operator stop or a drain -- so the entry survived across the channel
    going fully off-air (``STOPPED``) and being freshly restarted
    (``ON_AIR``). MEASURED: record a rollover plan_end already in the past,
    let the worker exit cleanly, restart the channel, then issue a PLAIN
    operator reload with no rollover behind it at all -- the reload wrongly
    saw the stale, already-past ``plan_end_at`` and cut immediately
    (``switch_at_end_of_current=False``) instead of deferring normally
    (``True``, the ordinary ON_AIR/no-override shape an unrecorded reload
    should take). Fixed by clearing the entry in the clean-exit branch of
    ``_poll_process`` itself, alongside the terminal-``ERROR`` branch,
    ``_drain``'s process-is-None branch, and ``stop_all_channels``'
    already-gone branch (see the other new tests below and
    ``_rollover_plan_end_at``'s docstring)."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222)]
    started: list[_FakeProcess] = []
    strategy = _FakeContentReloadStrategy(processes, started)
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _cid: _source_plan_with_label(tmp_path, "Council meeting"),
        encoder_strategy=strategy,
    )
    daemon.process_once("gov")  # initial start -> ON_AIR (process 111)

    daemon.record_rollover_plan_end("gov", datetime(2020, 1, 1, tzinfo=UTC))
    started[0].returncode = 0  # a clean exit, e.g. the channel's own plan ran out
    daemon.process_once("gov")  # _poll_process's clean-exit branch -> STOPPED

    assert store.read_state("gov").state == "STOPPED"
    assert daemon._rollover_plan_end_at == {}  # must not survive the channel going dark

    # Fresh command_ids -- the initial "cmd-start"/"cmd-reload" ids from
    # ``_command()`` are already consumed and would be silently deduped.
    store.enqueue_command(
        EgressCommand(
            channel_id="gov",
            action="start",
            issued_at=datetime(2026, 6, 5, 13, 0, tzinfo=UTC),
            issued_by="operator",
            command_id="cmd-restart",
        )
    )
    daemon.process_once("gov")  # restart -> ON_AIR (process 222)
    assert store.read_state("gov").state == "ON_AIR"

    store.enqueue_command(
        EgressCommand(
            channel_id="gov",
            action="reload",
            issued_at=datetime(2026, 6, 5, 14, 0, tzinfo=UTC),
            issued_by="operator",
            command_id="cmd-plain-reload",
        )
    )  # a plain reload, no rollover behind it
    daemon.process_once("gov")

    assert strategy.switch_at_end_of_current_calls == [True]  # deferred, not cut
    assert daemon._rollover_plan_end_at == {}


def test_poll_process_terminal_error_clears_the_recorded_rollover_plan_end(
    tmp_path: Path,
) -> None:
    """Coordinator review, round 5, item 1: the terminal-``ERROR`` branch of
    ``_poll_process`` (a crash the daemon does not relaunch, because the
    state row is not in one of the relaunchable states) is another route
    that takes the channel off-air without ever reaching ``_stop`` --
    it must clear the entry itself too."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    process = _FakeProcess(pid=111)
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _cid: _source_plan(tmp_path),
        ffmpeg_starter=lambda args: process,
    )
    daemon.process_once("gov")  # start -> ON_AIR

    daemon.record_rollover_plan_end("gov", datetime(2020, 1, 1, tzinfo=UTC))
    # Force the state row out of every relaunchable state so the crash below
    # lands in the terminal ERROR branch instead of _relaunch_after_crash.
    store.write_state(
        EgressStateRow(channel_id="gov", state="STOPPED", updated_at=datetime.now(UTC))
    )
    process.returncode = 1  # a crash the daemon will not relaunch
    daemon.process_once("gov")

    assert store.read_state("gov").state == "ERROR"
    assert daemon._rollover_plan_end_at == {}


def test_drain_with_no_live_process_clears_the_recorded_rollover_plan_end(
    tmp_path: Path,
) -> None:
    """Coordinator review, round 5, item 1: ``_drain``'s process-is-None
    branch (drain issued against a channel with no live process at all) is
    another off-air route that bypasses ``_stop`` entirely -- it must
    clear the entry itself too."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    daemon = EgressDaemon(
        store, work_dir=tmp_path, source_plan_provider=lambda _cid: _source_plan(tmp_path)
    )

    daemon.record_rollover_plan_end("gov", datetime(2020, 1, 1, tzinfo=UTC))
    assert daemon._rollover_plan_end_at == {"gov": datetime(2020, 1, 1, tzinfo=UTC)}

    store.enqueue_command(_command("drain"))
    daemon.process_once("gov")  # _drain: process is None -> STOPPED

    assert store.read_state("gov").state == "STOPPED"
    assert daemon._rollover_plan_end_at == {}


def test_stop_all_channels_already_gone_clears_the_recorded_rollover_plan_end(
    tmp_path: Path,
) -> None:
    """Coordinator review, round 5, item 1: ``stop_all_channels``' "already
    gone" branch (a channel whose process already exited but hasn't been
    reaped by ``_poll_process`` yet) is another off-air route that bypasses
    ``_stop`` entirely -- it must clear the entry itself too."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    process = _FakeProcess(pid=111)
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _cid: _source_plan(tmp_path),
        ffmpeg_starter=lambda args: process,
    )
    daemon.process_once("gov")  # start -> ON_AIR, tracked in self._processes

    daemon.record_rollover_plan_end("gov", datetime(2020, 1, 1, tzinfo=UTC))
    process.returncode = 0  # exited already, but _poll_process hasn't reaped it yet

    result = daemon.stop_all_channels(deadline_seconds=0.0)

    assert [outcome.outcome for outcome in result.outcomes] == ["already_gone"]
    assert daemon._rollover_plan_end_at == {}


def test_the_recorded_plan_end_binds_to_whichever_reload_drains_first_not_automations_own(
    tmp_path: Path,
) -> None:
    """Coordinator review, round 4, item 4: the recorded value is NOT scoped
    to the reload automation dispatched it for -- it binds to whatever
    "reload" command for that channel ``_request_reload`` processes NEXT.
    ``pop_pending_commands`` drains a channel's queued commands sorted by
    ``issued_at`` (not enqueue order), so an operator reload issued EARLIER
    than automation's own rollover reload -- even if both are enqueued in
    the same tick, in either order -- drains first and consumes the value
    instead; automation's own reload, draining second, sees nothing
    recorded and defers normally. This is a real mixup this fix does not
    close (only the indefinite leak the earlier rounds fixed) -- automation's
    own 45-second retry-timeout/settlement bookkeeping is what recovers the
    never-landed reload it was actually tracking."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222)]
    started: list[_FakeProcess] = []
    current_label = "Council meeting"

    def source_provider(_channel_id: str) -> EgressSourcePlan:
        return _source_plan_with_label(tmp_path, current_label)

    strategy = _FakeContentReloadStrategy(processes, started)
    daemon = EgressDaemon(
        store, work_dir=tmp_path, source_plan_provider=source_provider, encoder_strategy=strategy
    )
    daemon.process_once("gov")  # initial start -> ON_AIR

    # Automation records a rollover plan_end (already stale, so the reload it
    # is FOR must cut immediately) for a reload it is about to enqueue.
    daemon.record_rollover_plan_end("gov", datetime(2020, 1, 1, tzinfo=UTC))
    # An operator reload command, issued_at EARLIER than automation's own,
    # is enqueued in the SAME tick -- pop_pending_commands sorts by
    # issued_at, so this one drains FIRST regardless of enqueue order.
    store.enqueue_command(
        EgressCommand(
            channel_id="gov",
            action="reload",
            issued_at=datetime(2026, 6, 5, 11, 0, tzinfo=UTC),
            issued_by="operator",
            command_id="cmd-operator-reload",
        )
    )
    store.enqueue_command(
        EgressCommand(
            channel_id="gov",
            action="reload",
            issued_at=datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
            issued_by="channel-automation",
            command_id="cmd-automation-reload",
        )
    )
    current_label = "Mayor interview"
    daemon.process_once("gov")

    # The OPERATOR reload (drained first) wrongly cuts immediately -- it
    # consumed automation's recorded value. Automation's OWN reload (drained
    # second) sees nothing recorded and defers normally, the ordinary ON_AIR/
    # no-override shape.
    assert strategy.switch_at_end_of_current_calls == [False, True]
    assert daemon._rollover_plan_end_at == {}


def test_content_reload_never_defers_switch_off_of_fallback_slate(tmp_path: Path) -> None:
    """Issue #157: filler must be interrupted the moment a due program is
    ready -- a reload issued from FALLBACK_SLATE must never defer (wait out
    the rest of a slate/filler leg's own "duration")."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    processes = [_FakeProcess(pid=111)]
    started: list[_FakeProcess] = []
    strategy = _FakeContentReloadStrategy(processes, started)
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _cid: _source_plan_with_label(tmp_path, "Due program"),
        encoder_strategy=strategy,
    )
    # Simulate a live encoder already on FALLBACK_SLATE (no process_once start
    # needed -- _try_content_reload only reads state + the tracked process).
    started.append(processes[0])
    daemon._processes["gov"] = processes[0]  # type: ignore[attr-defined]
    store.write_state(
        EgressStateRow(
            channel_id="gov",
            state="FALLBACK_SLATE",
            current_source_label="CivicCast slate",
            updated_at=datetime(2026, 6, 12, 6, 0, tzinfo=UTC),
        )
    )

    state = store.read_state("gov")
    assert state is not None
    applied = daemon._try_content_reload("gov", state, processes[0], rollover_plan_end_at=None)  # type: ignore[attr-defined]

    assert applied is True
    assert strategy.switch_at_end_of_current_calls == [False]


def test_content_reload_never_defers_switch_during_a_manual_override(tmp_path: Path) -> None:
    """B1/B3: a reload issued while has_manual_override() is True (a live
    takeover or a forced slate is active) must always cut in immediately --
    the whole point of an operator override is "now", not "wait for the
    outgoing leg to end naturally"."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    processes = [_FakeProcess(pid=111)]
    started: list[_FakeProcess] = [processes[0]]
    strategy = _FakeContentReloadStrategy(processes, started)

    class _OverriddenDaemon(EgressDaemon):
        def has_manual_override(self, channel_id: str) -> bool:
            return True

    daemon = _OverriddenDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _cid: _source_plan_with_label(tmp_path, "Live feed"),
        encoder_strategy=strategy,
    )
    daemon._processes["gov"] = processes[0]  # type: ignore[attr-defined]
    store.write_state(
        EgressStateRow(
            channel_id="gov",
            state="ON_AIR",
            current_source_label="Council meeting",
            updated_at=datetime(2026, 6, 12, 6, 0, tzinfo=UTC),
        )
    )

    state = store.read_state("gov")
    assert state is not None
    applied = daemon._try_content_reload("gov", state, processes[0], rollover_plan_end_at=None)  # type: ignore[attr-defined]

    assert applied is True
    assert strategy.switch_at_end_of_current_calls == [False]


def test_content_reload_falls_back_to_restart_when_worker_not_ready(tmp_path: Path) -> None:
    """If the seamless reload can't be applied (reload_content returns False — e.g.
    the worker control channel isn't ready), the daemon falls through to the existing
    terminate+restart reload path so the program change still lands."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222)]
    started: list[_FakeProcess] = []
    current_label = "Council meeting"

    def source_provider(_channel_id: str) -> EgressSourcePlan:
        return _source_plan_with_label(tmp_path, current_label)

    strategy = _FakeContentReloadStrategy(processes, started, reload_ok=False)
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=source_provider,
        encoder_strategy=strategy,
    )

    daemon.process_once("gov")
    current_label = "Mayor interview"
    store.enqueue_command(_command("reload"))
    daemon.process_once("gov")

    # the seamless path was attempted, then fell through to the restart drain
    assert strategy.reload_calls == ["Mayor interview"]
    assert store.read_state("gov").state == "TRANSITIONING"

    started[0].returncode = 0  # the drained encoder exits → pending reload restarts
    daemon.process_once("gov")

    assert len(started) == 2  # restart happened
    state = store.read_state("gov")
    assert state.state == "ON_AIR"
    assert state.current_source_label == "Mayor interview"


def test_content_reload_declined_logs_the_reason(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Coordinator follow-up (2026-09-06): a declined seamless reload
    (``reload_content`` returns False) used to fall back to restart with NO log
    line at all -- an operator/on-call reading the control-plane log for "why
    did this channel restart instead of reloading in place" found nothing.
    ``_try_content_reload`` now logs a WARNING naming the channel and, when the
    strategy can report one (``last_send_command_failure_reason``, an OPTIONAL
    capability probed via ``getattr`` like ``supports_content_reload``), why."""

    class _ReasonReportingStrategy(_FakeContentReloadStrategy):
        def last_send_command_failure_reason(self, channel_id: str) -> str | None:
            return "worker acked 'aborted:timeout'"

    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222)]
    started: list[_FakeProcess] = []
    current_label = "Council meeting"

    def source_provider(_channel_id: str) -> EgressSourcePlan:
        return _source_plan_with_label(tmp_path, current_label)

    strategy = _ReasonReportingStrategy(processes, started, reload_ok=False)
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=source_provider,
        encoder_strategy=strategy,
    )
    daemon.process_once("gov")
    current_label = "Mayor interview"
    store.enqueue_command(_command("reload"))

    with caplog.at_level(logging.WARNING, logger="civiccast.egress.daemon"):
        daemon.process_once("gov")

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        "gov" in message and "declined" in message and "worker acked 'aborted:timeout'" in message
        for message in warnings
    ), warnings


def test_content_reload_declined_with_no_reason_reported_still_logs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A strategy with no ``last_send_command_failure_reason`` capability at all
    (the plain ``_FakeContentReloadStrategy``, matching every existing strategy
    test double in this file) still gets a WARNING -- just without a reason."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222)]
    started: list[_FakeProcess] = []
    current_label = "Council meeting"

    def source_provider(_channel_id: str) -> EgressSourcePlan:
        return _source_plan_with_label(tmp_path, current_label)

    strategy = _FakeContentReloadStrategy(processes, started, reload_ok=False)
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=source_provider,
        encoder_strategy=strategy,
    )
    daemon.process_once("gov")
    current_label = "Mayor interview"
    store.enqueue_command(_command("reload"))

    with caplog.at_level(logging.WARNING, logger="civiccast.egress.daemon"):
        daemon.process_once("gov")

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("gov" in message and "declined" in message for message in warnings), warnings


def test_pending_reload_does_not_terminate_the_worker_while_awaiting_settlement(
    tmp_path: Path,
) -> None:
    """F1 BLOCKER fix (coordinator hostile review): a deferred/boundary-aligned
    switch (an automation-driven ON_AIR extension) can take minutes to settle.
    The pre-redesign code bounded the pipe ack itself at a fixed timeout, so a
    correctly-armed long-lead reload would time out that wait and the daemon
    would terminate a perfectly healthy worker. This redesign never blocks on
    settlement at all -- across many poll ticks with reload-status.json still
    absent, the worker must NEVER be restarted or terminated; only once the
    status file actually appears does the daemon act (and even then, only to
    finish the ON_AIR bookkeeping, not to touch the process)."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222)]
    started: list[_FakeProcess] = []
    current_label = "Council meeting"

    def source_provider(_channel_id: str) -> EgressSourcePlan:
        return _source_plan_with_label(tmp_path, current_label)

    strategy = _FakeContentReloadStrategy(processes, started, auto_settle=False)
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=source_provider,
        encoder_strategy=strategy,
    )

    daemon.process_once("gov")  # initial start -> ON_AIR
    current_label = "Mayor interview"
    store.enqueue_command(_command("reload"))
    daemon.process_once("gov")  # armed; strategy did NOT write reload-status.json

    assert strategy.reload_calls == ["Mayor interview"]
    assert len(started) == 1  # no restart happened to arm it

    # Many more ticks with settlement still pending -- this is standing in for
    # however long a real deferred switch's natural wait runs (up to
    # defer_switch_timeout_s=900s in the engine); the point is that NOTHING
    # here is time-bounded on this side, so no amount of ticks alone forces a
    # restart the way the old synchronous ack-wait design would have.
    for _ in range(20):
        daemon.process_once("gov")

    assert started[0].terminated is False  # never terminated while pending
    assert len(started) == 1  # never restarted
    state = store.read_state("gov")
    assert state is not None
    assert state.state == "ON_AIR"
    assert state.current_source_label == "Council meeting"  # still the OLD label -- honest

    # The reload NOW settles (a real worker's on_settled finally fires).
    _write_fake_reload_status(tmp_path, "gov", strategy.reload_ids[-1], "applied")
    daemon.process_once("gov")

    assert started[0].terminated is False  # still never terminated
    assert len(started) == 1  # still never restarted -- truly seamless
    state = store.read_state("gov")
    assert state is not None
    assert state.state == "ON_AIR"
    assert state.current_source_label == "Mayor interview"


def test_pending_reload_settlement_deadline_falls_back_to_restart(tmp_path: Path) -> None:
    """F1 redesign: if a status update never arrives at all (e.g. the worker
    crashed between arming and writing reload-status.json), the daemon must
    not wait forever -- past _PENDING_RELOAD_SETTLE_DEADLINE_S it gives up and
    falls back to the terminate+restart path, same as a synchronously-declined
    reload always did."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222)]
    started: list[_FakeProcess] = []
    current_label = "Council meeting"

    def source_provider(_channel_id: str) -> EgressSourcePlan:
        return _source_plan_with_label(tmp_path, current_label)

    strategy = _FakeContentReloadStrategy(processes, started, auto_settle=False)
    fake_now = [1_000_000.0]
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=source_provider,
        encoder_strategy=strategy,
        monotonic=lambda: fake_now[0],
    )

    daemon.process_once("gov")  # initial start -> ON_AIR
    current_label = "Mayor interview"
    store.enqueue_command(_command("reload"))
    daemon.process_once("gov")  # armed; no status file ever written

    assert len(started) == 1  # no restart yet -- still within the deadline

    # Advance the injected clock past the deadline with no status update ever
    # arriving.
    fake_now[0] += 961.0
    daemon.process_once("gov")

    assert store.read_state("gov").state == "TRANSITIONING"  # fell back to restart
    started[0].returncode = 0  # the drained encoder exits -> pending reload restarts
    daemon.process_once("gov")

    assert len(started) == 2  # restart landed the program change
    state = store.read_state("gov")
    assert state.state == "ON_AIR"
    assert state.current_source_label == "Mayor interview"


def test_unrecognized_settlement_result_is_treated_as_aborted_immediately(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Hostile-review follow-up: a settlement result that is neither
    "applied" nor "aborted:<reason>" (a malformed write, a future/older
    worker version) must be treated as aborted IMMEDIATELY -- not silently
    waited out for the full 960s deadline, since whatever wrote it clearly
    ran and waiting longer buys nothing."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222)]
    started: list[_FakeProcess] = []
    current_label = "Council meeting"

    def source_provider(_channel_id: str) -> EgressSourcePlan:
        return _source_plan_with_label(tmp_path, current_label)

    strategy = _FakeContentReloadStrategy(processes, started, auto_settle=False)
    fake_now = [1_000_000.0]
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=source_provider,
        encoder_strategy=strategy,
        monotonic=lambda: fake_now[0],
    )

    daemon.process_once("gov")  # initial start -> ON_AIR
    current_label = "Mayor interview"
    store.enqueue_command(_command("reload"))
    daemon.process_once("gov")  # armed; no status file ever written

    armed_reload_id = strategy.reload_ids[-1]
    _write_fake_reload_status(tmp_path, "gov", armed_reload_id, "weird-unknown-value")

    with caplog.at_level(logging.WARNING, logger="civiccast.egress.daemon"):
        # Only ONE second later -- nowhere near the 960s deadline -- proving
        # this is recognized and acted on immediately, not merely eventually.
        fake_now[0] += 1.0
        daemon.process_once("gov")

    assert store.read_state("gov").state == "TRANSITIONING"  # fell back to restart already
    messages = [r.getMessage() for r in caplog.records]
    assert any(
        "gov" in message and "unrecognized" in message and armed_reload_id in message
        for message in messages
    ), messages

    started[0].returncode = 0  # the drained encoder exits -> pending reload restarts
    daemon.process_once("gov")
    assert len(started) == 2
    state = store.read_state("gov")
    assert state.state == "ON_AIR"
    assert state.current_source_label == "Mayor interview"


def test_worker_crash_during_the_armed_window_discards_pending_settlement(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Hostile-review follow-up, item 1: a worker that crashes WHILE a reload
    it armed is still settling must not leave that tracking behind -- the
    entry is gone immediately (no spurious restart fires 960s later against a
    channel that has already been relaunched onto something else), and a
    LATE-arriving "applied" status for that dead attempt is recognized and
    ignored (logged), not silently discarded with no evidence it was even
    observed."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222), _FakeProcess(pid=333)]
    started: list[_FakeProcess] = []
    current_label = "Council meeting"

    def source_provider(_channel_id: str) -> EgressSourcePlan:
        return _source_plan_with_label(tmp_path, current_label)

    strategy = _FakeContentReloadStrategy(processes, started, auto_settle=False)
    fake_now = [1_000_000.0]
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=source_provider,
        encoder_strategy=strategy,
        monotonic=lambda: fake_now[0],
    )

    daemon.process_once("gov")  # initial start -> ON_AIR (pid 111)
    current_label = "Mayor interview"
    store.enqueue_command(_command("reload"))
    daemon.process_once("gov")  # armed; strategy did NOT write reload-status.json

    armed_reload_id = strategy.reload_ids[-1]
    assert daemon._pending_reload_settle.get("gov") is not None  # type: ignore[attr-defined]

    # The worker crashes (non-zero exit) WHILE the reload is still armed --
    # nothing ever settled it.
    started[0].returncode = 1
    daemon.process_once("gov")  # _poll_process observes the crash -> relaunches at once

    assert daemon._pending_reload_settle.get("gov") is None  # type: ignore[attr-defined]
    assert len(started) == 2  # the crash relaunch landed (pid 222)

    # Well past the 960s settlement deadline the ARMED reload itself would
    # have been allowed to take (hostile-review follow-up, third pass, P2:
    # _discarded_reload_ids is keyed by channel_id -- already bounded by the
    # number of channels this daemon tracks -- and carries no expiry of its
    # own; a real settlement for a dead attempt can legitimately land any
    # time after the crash, including well past that budget, and must still
    # be recognized), the dead attempt's worker finally writes its status
    # file. Recognized and ignored, logged; no additional restart triggered.
    fake_now[0] += 1000.0
    with caplog.at_level(logging.INFO, logger="civiccast.egress.daemon"):
        _write_fake_reload_status(tmp_path, "gov", armed_reload_id, "applied")
        daemon.process_once("gov")

    assert len(started) == 2  # the late write changes nothing
    messages = [r.getMessage() for r in caplog.records]
    assert any(
        "gov" in message and armed_reload_id in message and "ignoring" in message
        for message in messages
    ), messages
    state = store.read_state("gov")
    assert state is not None
    assert state.state == "ON_AIR"


def _prepare_with_tracked_plan_dirs(
    tmp_path: Path, counter: dict[str, int]
) -> Callable[[EgressSourcePlan, EgressConfig], SourcePreparationReport]:
    """A fake ``source_preparer`` that mints a fresh, real, uniquely-named
    directory (mirroring ``SourcePreparer.prepare``'s own per-call directory)
    on every call, so tests can assert on exactly which one gets released."""

    def prepare(source_plan: EgressSourcePlan, config: EgressConfig) -> SourcePreparationReport:
        counter["n"] += 1
        plan_dir = tmp_path / f"plan-{counter['n']}"
        plan_dir.mkdir()
        return SourcePreparationReport(source_plan=source_plan, records=(), plan_dir=plan_dir)

    return prepare


def test_superseding_a_pending_reload_releases_its_previous_plan_dir(tmp_path: Path) -> None:
    """Hostile-review follow-up, item 3: ``_try_content_reload`` used to
    silently overwrite ``_pending_reload_settle`` when a newer reload attempt
    superseded a still-pending one, leaking the replaced entry's plan_dir
    forever (never released, never GC'd until age/budget eventually caught
    it)."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222)]
    started: list[_FakeProcess] = []
    current_label = "Council meeting"
    counter = {"n": 0}
    released: list[Path] = []

    def source_provider(_channel_id: str) -> EgressSourcePlan:
        return _source_plan_with_label(tmp_path, current_label)

    strategy = _FakeContentReloadStrategy(processes, started, auto_settle=False)
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=source_provider,
        encoder_strategy=strategy,
        source_preparer=_prepare_with_tracked_plan_dirs(tmp_path, counter),
        prepared_plan_release=released.append,
    )

    daemon.process_once("gov")  # initial start -> plan-1 (becomes ACTIVE, not pending)
    assert released == []

    current_label = "Mayor interview"
    store.enqueue_command(_command("reload"))
    daemon.process_once("gov")  # arms reload #1 -> plan-2 (PENDING, never settles)
    assert released == []

    current_label = "Evening news"
    # A distinct command_id -- ``_command("reload")`` always returns the SAME
    # fixed id ("cmd-reload"), which the store's dedup would silently drop as
    # a re-enqueue of the already-consumed first reload command.
    store.enqueue_command(
        EgressCommand(
            channel_id="gov",
            action="reload",
            issued_at=datetime(2026, 6, 5, 12, 1, tzinfo=UTC),
            issued_by="operator",
            command_id="cmd-reload-2",
        )
    )
    daemon.process_once("gov")  # a second rollover supersedes reload #1

    # The FIRST reload's plan (plan-2) is released the moment it is
    # superseded -- not left dangling until GC eventually notices.
    assert released == [tmp_path / "plan-2"]


def test_stop_releases_both_the_pending_reload_and_the_active_plan_dir(tmp_path: Path) -> None:
    """Hostile-review follow-up (third pass): a direct (non-draining) operator
    stop must route through BOTH shared discard helpers -- an armed-but-
    unsettled reload's plan_dir (``_discard_pending_reload_settlement``) AND
    the channel's currently-active plan_dir (``_discard_active_prepared_plan_
    dir``) -- rather than either being left for GC. The direct stop path's
    own ``_process_terminate`` call makes the worker's exit synchronous with
    this call, so releasing the active dir here (unlike the draining path,
    see the next test) is safe."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222)]
    started: list[_FakeProcess] = []
    current_label = "Council meeting"
    counter = {"n": 0}
    released: list[Path] = []

    def source_provider(_channel_id: str) -> EgressSourcePlan:
        return _source_plan_with_label(tmp_path, current_label)

    strategy = _FakeContentReloadStrategy(processes, started, auto_settle=False)
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=source_provider,
        encoder_strategy=strategy,
        source_preparer=_prepare_with_tracked_plan_dirs(tmp_path, counter),
        prepared_plan_release=released.append,
    )

    daemon.process_once("gov")  # initial start -> plan-1, tracked ACTIVE
    assert daemon._active_prepared_plan_dir.get("gov") == tmp_path / "plan-1"  # type: ignore[attr-defined]

    current_label = "Mayor interview"
    store.enqueue_command(_command("reload"))
    daemon.process_once("gov")  # arms a reload -> plan-2, tracked PENDING (never settles)
    assert daemon._pending_reload_settle.get("gov") is not None  # type: ignore[attr-defined]
    assert released == []

    store.enqueue_command(_command("stop"))
    daemon.process_once("gov")

    assert daemon._pending_reload_settle.get("gov") is None  # type: ignore[attr-defined]
    assert daemon._active_prepared_plan_dir.get("gov") is None  # type: ignore[attr-defined]
    # _discard_pending_reload_settlement runs before _discard_active_prepared_
    # plan_dir inside _stop, so the pending reload's plan (plan-2) is
    # released first, then the active plan (plan-1).
    assert released == [tmp_path / "plan-2", tmp_path / "plan-1"]
    assert store.read_state("gov").state == "STOPPED"


def test_draining_stop_defers_the_active_plan_dir_release_to_stop_all_channels(
    tmp_path: Path,
) -> None:
    """Hostile-review follow-up (third pass), P2: a DRAINING stop
    (``stop_all_channels``'s graceful path) only sends the worker its
    TERMINAL command and returns -- the worker may still be airing from the
    active plan directory for the entire drain deadline, so ``_stop`` itself
    must NOT release it. Proves the directory survives the draining ``_stop``
    call untouched, and is only released once ``stop_all_channels`` actually
    observes the worker's exit."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    process = _FakeProcess(pid=111)
    processes = [process]
    started: list[_FakeProcess] = []
    counter = {"n": 0}
    released: list[Path] = []

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _cid: _source_plan(tmp_path),
        encoder_strategy=_FakeContentReloadStrategy(processes, started),
        source_preparer=_prepare_with_tracked_plan_dirs(tmp_path, counter),
        prepared_plan_release=released.append,
    )

    daemon.process_once("gov")  # _start -> plan-1, tracked ACTIVE
    assert daemon._active_prepared_plan_dir.get("gov") == tmp_path / "plan-1"  # type: ignore[attr-defined]

    result = daemon.stop_all_channels(deadline_seconds=0.0)  # worker never exits in time
    assert result.outcomes[0].outcome == "killed_after_deadline"

    # The worker was force-terminated by the deadline escalation -- ITS exit
    # is what unblocks the release, which this same stop_all_channels call
    # then performs once that escalation confirms it.
    assert released == [tmp_path / "plan-1"]
    assert daemon._active_prepared_plan_dir.get("gov") is None  # type: ignore[attr-defined]


def test_worker_exit_between_poll_process_and_poll_reload_settlement_falls_back(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Hostile-review follow-up (third pass): the liveness re-check inside
    ``_poll_reload_settlement`` (guarding the "applied" -> ``_commit_reload_
    settlement`` transition) must catch a worker that was still alive when
    ``_poll_process`` checked it EARLIER in this same ``process_once`` tick,
    but has exited by the time this later check runs -- proving the
    liveness check is a live re-read, not reused/stale information from
    earlier in the same pass. Falls back to restart, but (since the crash
    is only discovered mid-tick, after the healthy-poll bookkeeping already
    ran) the actual relaunch does not fire until the FOLLOWING tick, once
    ``_poll_process`` itself observes the same exit."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())

    class _ExitsOnSecondPollProcess(_FakeProcess):
        """Alive on its FIRST ``poll()`` call, exited (non-zero) on every
        call after that -- models a worker dying in the gap between two
        poll checks within the SAME process_once tick."""

        def __init__(self, *, pid: int, alive_for_calls: int) -> None:
            super().__init__(pid=pid, returncode=None)
            self._poll_calls = 0
            self._alive_for_calls = alive_for_calls

        def poll(self) -> int | None:
            self._poll_calls += 1
            if self._poll_calls <= self._alive_for_calls:
                return None
            self.returncode = 1
            return 1

    # Alive for its first 3 poll() calls (the reload-arming tick's own
    # _poll_process check, that same tick's _request_reload liveness check
    # gating whether it even attempts the seamless path, and the critical
    # tick's OWN _poll_process check) -- exited from the 4th call onward,
    # which is _poll_reload_settlement's liveness re-check later in that
    # SAME critical tick.
    worker = _ExitsOnSecondPollProcess(pid=111, alive_for_calls=3)
    restart_process = _FakeProcess(pid=222)
    processes = [worker, restart_process]
    started: list[_FakeProcess] = []
    current_label = "Council meeting"

    def source_provider(_channel_id: str) -> EgressSourcePlan:
        return _source_plan_with_label(tmp_path, current_label)

    strategy = _FakeContentReloadStrategy(processes, started, auto_settle=False)
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=source_provider,
        encoder_strategy=strategy,
    )

    daemon.process_once("gov")  # initial start -> ON_AIR (pid 111, poll call #1 pending)
    current_label = "Mayor interview"
    store.enqueue_command(_command("reload"))
    daemon.process_once("gov")  # armed; no status file ever written

    armed_reload_id = strategy.reload_ids[-1]
    _write_fake_reload_status(tmp_path, "gov", armed_reload_id, "applied")

    with caplog.at_level(logging.WARNING, logger="civiccast.egress.daemon"):
        # ONE tick: _poll_process runs first and calls worker.poll() (call #1
        # -> None, still alive) -- no crash-relaunch fires from THAT check.
        # _poll_reload_settlement runs later in this SAME tick, sees the
        # "applied" status, and does its OWN liveness re-check (call #2 ->
        # 1, exited) -- falls back to restart, but does not itself relaunch.
        daemon.process_once("gov")

    assert daemon._pending_reload_settle.get("gov") is None  # type: ignore[attr-defined]
    assert len(started) == 1  # no relaunch yet -- this tick only fell back
    state = store.read_state("gov")
    assert state is not None
    assert state.state == "TRANSITIONING"
    messages = [r.getMessage() for r in caplog.records]
    assert any(
        "gov" in message and "already exited" in message and armed_reload_id in message
        for message in messages
    ), messages

    # The FOLLOWING tick: _poll_process now observes the same exit (call #3,
    # still 1) as a fresh crash and relaunches.
    daemon.process_once("gov")
    assert len(started) == 2
    state = store.read_state("gov")
    assert state is not None
    assert state.state == "ON_AIR"
    assert state.current_source_label == "Mayor interview"


def test_start_tracks_and_releases_its_active_plan_dir_on_worker_exit(tmp_path: Path) -> None:
    """Hostile-review follow-up, item 4: with the seamless-reload flag OFF
    (``supports_content_reload=False``, the shipped default),
    ``_try_content_reload``/``_commit_reload_settlement`` never run at all --
    only ``_start`` ever prepares a plan for that channel, so without this
    the ONLY cleanup for its directory was age/budget GC. Proves ``_start``
    tracks its own plan as active and releases it once the worker exits."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111)]
    started: list[_FakeProcess] = []
    counter = {"n": 0}
    released: list[Path] = []

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _cid: _source_plan(tmp_path),
        encoder_strategy=_FakeContentReloadStrategy(processes, started),
        source_preparer=_prepare_with_tracked_plan_dirs(tmp_path, counter),
        prepared_plan_release=released.append,
    )

    daemon.process_once("gov")  # _start -> plan-1
    process = started[0]
    assert daemon.live_prepared_plan_dirs("gov") == frozenset({tmp_path / "plan-1"})
    assert released == []

    process.returncode = 0  # a clean exit (e.g. an operator-issued stop landed)
    daemon.process_once("gov")

    assert released == [tmp_path / "plan-1"]
    assert daemon.live_prepared_plan_dirs("gov") == frozenset()


def test_content_reload_strategy_exception_falls_back_to_restart(tmp_path: Path) -> None:
    """TEST-004 #5: if reload_content RAISES, the daemon logs and falls back to
    terminate+restart rather than letting a strategy bug kill the program change."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222)]
    started: list[_FakeProcess] = []
    current_label = "Council meeting"

    def source_provider(_channel_id: str) -> EgressSourcePlan:
        return _source_plan_with_label(tmp_path, current_label)

    strategy = _FakeContentReloadStrategy(
        processes, started, reload_exc=RuntimeError("worker FIFO exploded")
    )
    daemon = EgressDaemon(
        store, work_dir=tmp_path, source_plan_provider=source_provider, encoder_strategy=strategy
    )
    daemon.process_once("gov")
    current_label = "Mayor interview"
    store.enqueue_command(_command("reload"))
    daemon.process_once("gov")

    assert strategy.reload_calls == ["Mayor interview"]  # the seamless path was attempted
    assert store.read_state("gov").state == "TRANSITIONING"  # then fell through to restart
    started[0].returncode = 0
    daemon.process_once("gov")
    assert len(started) == 2  # restart landed the program change


def test_content_reload_foreign_channel_plan_falls_back_to_restart(tmp_path: Path) -> None:
    """TEST-004 #3: a plan whose channel_id doesn't match is not applied seamlessly —
    the daemon falls through to the restart path (it never calls reload_content)."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222)]
    started: list[_FakeProcess] = []
    foreign = False

    def source_provider(_channel_id: str) -> EgressSourcePlan:
        plan = _source_plan_with_label(
            tmp_path, "Mayor interview" if foreign else "Council meeting"
        )
        if foreign:
            object.__setattr__(plan, "channel_id", "someone-else")
        return plan

    strategy = _FakeContentReloadStrategy(processes, started)
    daemon = EgressDaemon(
        store, work_dir=tmp_path, source_plan_provider=source_provider, encoder_strategy=strategy
    )
    daemon.process_once("gov")
    foreign = True
    store.enqueue_command(_command("reload"))
    daemon.process_once("gov")

    assert strategy.reload_calls == []  # foreign plan rejected before reload_content
    assert store.read_state("gov").state == "TRANSITIONING"  # fell through to restart


class _CapturingEncoderStrategy:
    """Captures every EncoderStartRequest passed to start()/reload_content() so a
    test can assert what actually reached the encoder -- used here to pin the
    S15 cg_overlay_provider pass-through at BOTH EncoderStartRequest call sites
    in daemon.py (the ``_start`` start path and the ``_try_content_reload``
    seamless-swap path)."""

    name = "fake-capturing-strategy"
    supports_live_swap = False
    supports_content_reload = True

    def __init__(self, processes: list[_FakeProcess]) -> None:
        self._processes = processes
        self.start_requests: list[EncoderStartRequest] = []
        self.reload_requests: list[EncoderStartRequest] = []

    def start(self, request: EncoderStartRequest) -> EncoderStartResult:
        self.start_requests.append(request)
        process = self._processes.pop(0)
        return EncoderStartResult(
            process=process,
            concat_plan_path=request.work_dir / "playout-graph.json",
            stdout_path=request.work_dir / "out.log",
            stderr_path=request.work_dir / "err.log",
            args=("worker",),
        )

    def swap_role(self, channel_id: str, work_dir: Path, role: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def reload_content(
        self, channel_id: str, work_dir: Path, request: EncoderStartRequest, **_kwargs: Any
    ) -> bool:
        self.reload_requests.append(request)
        return True


def test_cg_overlay_provider_result_reaches_encoder_start_request_on_start(tmp_path: Path) -> None:
    """S15 CG-lite engine overlay leg: the daemon's cg_overlay_provider hook is
    supposed to hand its per-channel board raster to the encoder strategy via
    EncoderStartRequest.cg_overlay_image -- the start-path call site inside
    EgressDaemon._start. Had no direct coverage."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    overlay_path = tmp_path / "board-overlay" / "gov.png"
    overlay_calls: list[tuple[str, EgressConfig]] = []

    def cg_overlay_provider(channel_id: str, config: EgressConfig) -> Path | None:
        overlay_calls.append((channel_id, config))
        return overlay_path

    strategy = _CapturingEncoderStrategy([_FakeProcess(pid=111)])
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        encoder_strategy=strategy,
        cg_overlay_provider=cg_overlay_provider,
    )

    daemon.process_once("gov")

    assert [channel_id for channel_id, _config in overlay_calls] == ["gov"]
    assert len(strategy.start_requests) == 1
    assert strategy.start_requests[0].cg_overlay_image == overlay_path


def test_cg_overlay_provider_result_reaches_encoder_start_request_on_reload(tmp_path: Path) -> None:
    """Same pass-through pinned at the second EncoderStartRequest call site
    (EgressDaemon._try_content_reload) -- a seamless in-place program swap must
    keep the board overlay wired, not drop it because no encoder restart
    happened."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    overlay_path = tmp_path / "board-overlay" / "gov.png"
    current_label = "Council meeting"

    def source_provider(_channel_id: str) -> EgressSourcePlan:
        return _source_plan_with_label(tmp_path, current_label)

    strategy = _CapturingEncoderStrategy([_FakeProcess(pid=111), _FakeProcess(pid=222)])
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=source_provider,
        encoder_strategy=strategy,
        cg_overlay_provider=lambda _channel_id, _config: overlay_path,
    )

    daemon.process_once("gov")
    current_label = "Mayor interview"
    store.enqueue_command(_command("reload"))
    daemon.process_once("gov")

    assert len(strategy.start_requests) == 1, "the reload must stay seamless, not restart"
    assert len(strategy.reload_requests) == 1
    assert strategy.reload_requests[0].cg_overlay_image == overlay_path


def test_proof_event_redacts_live_source_credentials(tmp_path: Path) -> None:
    """ENG-003: a live segment's ingest URI (which can carry an SRT passphrase) must be
    redacted before it lands in the durable proof chain."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    process = _FakeProcess()

    def source_provider(_channel_id: str) -> EgressSourcePlan:
        return EgressSourcePlan(
            channel_id="gov",
            segments=[
                EgressSourceSegment(
                    label="Live: chamber",
                    path="srt://truck.example:7001?passphrase=hunter2",
                    duration_seconds=1,
                    kind="live",
                )
            ],
        )

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=source_provider,
        ffmpeg_starter=lambda _args: process,
    )
    daemon.process_once("gov")

    proof = store.recent_proof_events("gov", 1)[0]
    assert "hunter2" not in proof.source_path
    assert (
        "passphrase=%3Credacted%3E" in proof.source_path
        or "passphrase=<redacted>" in proof.source_path
    )


def _orphan_state_row(pid: int) -> EgressStateRow:
    return EgressStateRow(
        channel_id="gov",
        state="ON_AIR",
        current_source_label="Council meeting",
        updated_at=datetime(2026, 6, 12, 7, 0, tzinfo=UTC),
        pid=pid,
    )


def _old_ffmpeg(pid: int):  # type: ignore[no-untyped-def]
    """Probe stub: pid is an ffmpeg created long before this server booted."""
    from civiccast.egress.daemon import OrphanInfo

    return lambda probed: OrphanInfo(name="ffmpeg.exe", created_at=0.0) if probed == pid else None


class TestOrphanEncoderReap:
    """Issue #161 (CA-8 live finding): a server restart leaves the previous
    server's encoder children streaming to the sink ports; the new daemon
    must reap them before starting its own encoder, or two writers corrupt
    the stream. Audit ENG-001/TEST-004 hardening: reap only PRE-BOOT pids,
    never pids this daemon tracks, and the terminator re-verifies identity
    by create time (closes the pid-reuse TOCTOU)."""

    def test_startup_reaps_orphaned_ffmpeg_before_starting(self, tmp_path: Path) -> None:
        store = InMemoryEgressStore()
        store.upsert_config(_config())
        # The previous server process left this state row behind; pid 7777
        # is still running, is an ffmpeg image, and predates this daemon.
        store.write_state(_orphan_state_row(7777))
        store.enqueue_command(_command())
        process = _FakeProcess(pid=8888)
        terminated: list[tuple[int, float]] = []

        daemon = EgressDaemon(
            store,
            work_dir=tmp_path,
            source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
            ffmpeg_starter=lambda _args: process,
            orphan_probe=_old_ffmpeg(7777),
            orphan_terminator=lambda pid, created_at: terminated.append((pid, created_at)),
        )

        daemon.process_once("gov")

        assert terminated == [(7777, 0.0)]
        state = store.read_state("gov")
        assert state is not None
        assert state.state == "ON_AIR"
        assert state.pid == 8888
        reap_events = [
            e for e in store.recent_proof_events("gov", 5) if "orphan" in e.machine_summary
        ]
        assert len(reap_events) == 1

    def test_reused_pid_belonging_to_another_program_is_never_touched(self, tmp_path: Path) -> None:
        from civiccast.egress.daemon import OrphanInfo

        store = InMemoryEgressStore()
        store.upsert_config(_config())
        store.write_state(_orphan_state_row(7777))
        store.enqueue_command(_command())
        terminated: list[tuple[int, float]] = []

        daemon = EgressDaemon(
            store,
            work_dir=tmp_path,
            source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
            ffmpeg_starter=lambda _args: _FakeProcess(pid=8888),
            orphan_probe=lambda _pid: OrphanInfo(name="notepad.exe", created_at=0.0),
            orphan_terminator=lambda pid, created_at: terminated.append((pid, created_at)),
        )

        daemon.process_once("gov")

        assert terminated == []
        assert store.read_state("gov").pid == 8888  # type: ignore[union-attr]

    def test_ffmpeg_created_after_this_server_booted_is_never_reaped(self, tmp_path: Path) -> None:
        # Audit ENG-001: a freed pid recycled onto a FRESH ffmpeg (another
        # channel's encoder, a conform job, a relay) must never be killed -
        # only processes that predate this daemon can be its predecessor's.
        import time as _time

        from civiccast.egress.daemon import OrphanInfo

        store = InMemoryEgressStore()
        store.upsert_config(_config())
        store.write_state(_orphan_state_row(7777))
        store.enqueue_command(_command())
        terminated: list[tuple[int, float]] = []

        daemon = EgressDaemon(
            store,
            work_dir=tmp_path,
            source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
            ffmpeg_starter=lambda _args: _FakeProcess(pid=8888),
            orphan_probe=lambda _pid: OrphanInfo(name="ffmpeg.exe", created_at=_time.time() + 3600),
            orphan_terminator=lambda pid, created_at: terminated.append((pid, created_at)),
        )

        daemon.process_once("gov")

        assert terminated == []
        assert store.read_state("gov").pid == 8888  # type: ignore[union-attr]

    def test_pid_tracked_by_this_daemon_is_never_probed_or_reaped(self, tmp_path: Path) -> None:
        # Audit ENG-001: a pid this daemon already tracks belongs to it.
        store = InMemoryEgressStore()
        store.upsert_config(_config())
        store.write_state(_orphan_state_row(4242))
        store.enqueue_command(_command())
        probed: list[int] = []

        def failing_probe(pid: int):  # type: ignore[no-untyped-def]
            probed.append(pid)
            return

        daemon = EgressDaemon(
            store,
            work_dir=tmp_path,
            source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
            ffmpeg_starter=lambda _args: _FakeProcess(pid=4242),
            orphan_probe=failing_probe,
            orphan_terminator=lambda pid, created_at: pytest.fail("must not terminate"),
        )

        daemon.process_once("gov")  # starts; tracks pid 4242
        daemon.process_once("gov")  # live tracked process: no probe at all

        assert 4242 not in probed[1:]  # never probed once tracked

    def test_dead_state_pid_needs_no_reap(self, tmp_path: Path) -> None:
        store = InMemoryEgressStore()
        store.upsert_config(_config())
        store.write_state(_orphan_state_row(7777))
        store.enqueue_command(_command())
        terminated: list[tuple[int, float]] = []

        daemon = EgressDaemon(
            store,
            work_dir=tmp_path,
            source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
            ffmpeg_starter=lambda _args: _FakeProcess(pid=8888),
            orphan_probe=lambda _pid: None,
            orphan_terminator=lambda pid, created_at: terminated.append((pid, created_at)),
        )

        daemon.process_once("gov")

        assert terminated == []
        assert store.read_state("gov").pid == 8888  # type: ignore[union-attr]

    def test_live_tracked_process_is_not_treated_as_an_orphan(self, tmp_path: Path) -> None:
        # A normally-running channel (this daemon owns the encoder) must not
        # reap its own process on subsequent passes.
        store = InMemoryEgressStore()
        store.upsert_config(_config())
        store.enqueue_command(_command())
        terminated: list[tuple[int, float]] = []

        daemon = EgressDaemon(
            store,
            work_dir=tmp_path,
            source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
            ffmpeg_starter=lambda _args: _FakeProcess(pid=8888),
            orphan_probe=_old_ffmpeg(8888),
            orphan_terminator=lambda pid, created_at: terminated.append((pid, created_at)),
        )

        daemon.process_once("gov")
        daemon.process_once("gov")

        assert terminated == []

    def test_pending_reload_clears_the_state_pid_before_restarting(self, tmp_path: Path) -> None:
        # Audit ENG-001/TEST-004: the reload takeover path used to leave the
        # just-killed encoder's pid in the state row, so _reap_orphan probed
        # a FREED pid on every filler->program takeover (and unit tests
        # probed the host's real process table). The pid must be cleared
        # before the pending-reload _start, so the probe never sees it.
        store = InMemoryEgressStore()
        store.upsert_config(_config())
        store.enqueue_command(_command())
        source_available = False
        processes = [_KilledNonZeroProcess(pid=111), _FakeProcess(pid=222)]
        started: list[_FakeProcess] = []
        probed: list[int] = []

        def source_provider(_channel_id: str) -> EgressSourcePlan | None:
            return _source_plan(tmp_path) if source_available else None

        def recording_probe(pid: int):  # type: ignore[no-untyped-def]
            probed.append(pid)
            return

        daemon = EgressDaemon(
            store,
            work_dir=tmp_path,
            source_plan_provider=source_provider,
            fallback_source_provider=lambda _config: _slate_plan(tmp_path),
            ffmpeg_starter=lambda _args: _start_fake_process(processes, started),
            orphan_probe=recording_probe,
            orphan_terminator=lambda pid, created_at: pytest.fail("must not terminate"),
        )

        daemon.process_once("gov")
        source_available = True
        store.enqueue_command(_command("reload"))
        daemon.process_once("gov")  # kills filler (pid 111), pending reload
        daemon.process_once("gov")  # exit observed -> pending reload starts

        assert store.read_state("gov").state == "ON_AIR"  # type: ignore[union-attr]
        # The freed pid 111 was never offered to the orphan probe.
        assert 111 not in probed


def test_stop_discards_a_pending_reload_kill_flag(tmp_path: Path) -> None:
    """Audit ENG-005/TEST-009: a reload-on-slate kill flag that leaks past a
    stop can later misclassify a genuine crash as a clean reload handoff.
    Sequence: slate reload (flag set, encoder still dying) -> stop -> start ->
    graceful ON_AIR reload pending -> CRASH. The crash must surface the
    honest relaunch error, not silently flow into the pending reload."""

    class _SlowDyingProcess(_FakeProcess):
        def terminate(self) -> None:  # stays alive until the test says so
            self.terminated = True

    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    source_available = False
    slow = _SlowDyingProcess(pid=111)
    processes: list[_FakeProcess] = [slow, _FakeProcess(pid=222), _FakeProcess(pid=333)]
    started: list[_FakeProcess] = []
    current_label = ["Council meeting"]

    def source_provider(_channel_id: str) -> EgressSourcePlan | None:
        return _source_plan_with_label(tmp_path, current_label[0]) if source_available else None

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=source_provider,
        fallback_source_provider=lambda _config: _slate_plan(tmp_path),
        ffmpeg_starter=lambda _args: _start_fake_process(processes, started),
        orphan_probe=lambda _pid: None,
        orphan_terminator=lambda pid, created_at: None,
    )

    daemon.process_once("gov")  # slate (fallback)
    store.enqueue_command(_command("reload"))
    daemon.process_once("gov")  # kill flag set; slow process still alive
    store.enqueue_command(_command("stop").model_copy(update={"command_id": "cmd-stop-1"}))
    daemon.process_once("gov")  # stop: must ALSO discard the kill flag
    slow.returncode = 0

    source_available = True
    store.enqueue_command(_command().model_copy(update={"command_id": "cmd-start-2"}))
    daemon.process_once("gov")  # ON_AIR on pid 222
    current_label[0] = "Mayor interview"
    store.enqueue_command(_command("reload").model_copy(update={"command_id": "cmd-reload-2"}))
    daemon.process_once("gov")  # graceful drain pending (no kill)

    started[1].returncode = 1  # CRASH, not a clean drain
    daemon.process_once("gov")

    # The honest crash bookkeeping ran: a child-failure event exists (the
    # stale-flag bug routed the crash into the pending reload, skipping it).
    events = store.recent_proof_events("gov", 10)
    assert any(e.event_id.startswith("egress-encoder-child-relaunch-") for e in events)


def test_default_orphan_seams_probe_and_terminate_a_real_child() -> None:
    """Audit TEST-004: the production psutil pair was never executed by any
    test. Pin it against a real spawned child, including the create-time
    identity check that closes the pid-reuse TOCTOU."""

    import subprocess
    import sys

    from civiccast.egress.daemon import (
        _default_orphan_probe,
        _default_orphan_terminator,
    )

    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        info = _default_orphan_probe(child.pid)
        assert info is not None
        assert "python" in info.name.lower()

        # Wrong create_time = identity mismatch: must NOT kill.
        _default_orphan_terminator(child.pid, info.created_at + 9999.0)
        assert child.poll() is None

        # Matching identity: terminates.
        _default_orphan_terminator(child.pid, info.created_at)
        child.wait(timeout=15)
    finally:
        if child.poll() is None:
            child.kill()


class _KilledNonZeroProcess(_FakeProcess):
    """Real ffmpeg exits non-zero when terminated; the stock fake exits 0."""

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 1


def test_reload_interrupts_filler_instead_of_draining_the_fill_target(
    tmp_path: Path,
) -> None:
    """Issue #157 (CA-8 live finding): after #154, filler plans span an hour,
    so a drain-style reload delays a due program by up to that hour. A reload
    issued while the channel is on FALLBACK_SLATE filler must terminate the
    filler encoder and start the program when it exits - even though a real
    terminated ffmpeg exits non-zero - without the crash-relaunch error."""

    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    source_available = False
    processes: list[_FakeProcess] = [
        _KilledNonZeroProcess(pid=111),
        _FakeProcess(pid=222),
    ]
    started: list[_FakeProcess] = []

    def source_provider(_channel_id: str) -> EgressSourcePlan | None:
        return _source_plan(tmp_path) if source_available else None

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=source_provider,
        fallback_source_provider=lambda _config: _slate_plan(tmp_path),
        ffmpeg_starter=lambda _args: _start_fake_process(processes, started),
    )

    daemon.process_once("gov")
    assert store.read_state("gov").state == "FALLBACK_SLATE"  # type: ignore[union-attr]

    source_available = True
    store.enqueue_command(_command("reload"))
    daemon.process_once("gov")

    # The filler encoder is killed NOW, not drained to the end of its plan.
    assert started[0].terminated is True

    daemon.process_once("gov")

    state = store.read_state("gov")
    assert state is not None
    assert state.state == "ON_AIR"
    assert state.current_source_label == "Council meeting"
    # The deliberate kill must not masquerade as an encoder crash.
    assert state.last_error is None
    proof_events = store.recent_proof_events("gov", 2)
    assert proof_events[0].state == "ON_AIR"
    assert "exited fallback slate" in proof_events[0].machine_summary


def test_reload_still_drains_programs_gracefully(tmp_path: Path) -> None:
    """Issue #157 boundary: ON_AIR programming is never cut for a reload."""

    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222)]
    started: list[_FakeProcess] = []

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        ffmpeg_starter=lambda _args: _start_fake_process(processes, started),
    )

    daemon.process_once("gov")
    assert store.read_state("gov").state == "ON_AIR"  # type: ignore[union-attr]

    store.enqueue_command(_command("reload"))
    daemon.process_once("gov")

    assert started[0].terminated is False
    assert store.read_state("gov").state == "TRANSITIONING"  # type: ignore[union-attr]


def test_daemon_records_live_takeover_and_handback_on_reload(tmp_path: Path) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222), _FakeProcess(pid=333)]
    started: list[_FakeProcess] = []
    current_label = "Council meeting"
    current_kind = "program"

    def source_provider(_channel_id: str) -> EgressSourcePlan:
        source = tmp_path / f"{current_label.replace(' ', '-').lower()}.ts"
        source.write_text(current_label, encoding="utf-8")
        return EgressSourcePlan(
            channel_id="gov",
            segments=[
                EgressSourceSegment(
                    label=current_label,
                    path=str(source),
                    duration_seconds=1,
                    kind=current_kind,  # type: ignore[arg-type]
                )
            ],
        )

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=source_provider,
        ffmpeg_starter=lambda _args: _start_fake_process(processes, started),
    )

    daemon.process_once("gov")
    current_label = "Live: Council chamber"
    current_kind = "live"
    store.enqueue_command(_command("reload"))
    daemon.process_once("gov")
    started[0].returncode = 0
    daemon.process_once("gov")
    current_label = "Council meeting"
    current_kind = "program"
    store.enqueue_command(
        _command("reload").model_copy(update={"command_id": "cmd-reload-handback"})
    )
    daemon.process_once("gov")
    started[1].returncode = 0
    daemon.process_once("gov")

    proof_events = store.recent_proof_events("gov", 5)
    assert [event.state for event in proof_events] == [
        "ON_AIR",
        "TRANSITIONING",
        "ON_AIR",
        "TRANSITIONING",
        "ON_AIR",
    ]
    assert "released live source" in proof_events[0].machine_summary
    assert "began an egress handoff" in proof_events[1].machine_summary
    assert "put live source" in proof_events[2].machine_summary
    assert "began live takeover" in proof_events[3].machine_summary


def test_daemon_relaunches_running_encoder_when_child_exits_nonzero(tmp_path: Path) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111, returncode=None), _FakeProcess(pid=222, returncode=None)]
    started: list[_FakeProcess] = []
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        ffmpeg_starter=lambda _args: _start_fake_process(processes, started),
    )

    daemon.process_once("gov")
    started[0].returncode = 1
    daemon.process_once("gov")

    state = store.read_state("gov")
    assert state is not None
    assert state.state == "ON_AIR"
    assert state.pid == 222
    assert len(started) == 2
    assert processes == []
    assert store.recent_health("gov", 2)[1].state == "STARTING"
    proof_events = store.recent_proof_events("gov", 4)
    assert [event.state for event in proof_events] == [
        "ON_AIR",
        "TRANSITIONING",
        "STARTING",
        "ON_AIR",
    ]
    assert "non-zero FFmpeg child exit" in proof_events[2].machine_summary
    assert "started encoder relaunch" in proof_events[2].machine_summary


def test_daemon_records_error_for_unresolved_secret(tmp_path: Path) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config(secret_ref="EGRESS_SRT_PASSPHRASE"))
    store.enqueue_command(_command())
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        resolve_secret=lambda _ref: None,
        ffmpeg_starter=lambda _args: _FakeProcess(),
    )

    daemon.process_once("gov")

    state = store.read_state("gov")
    assert state is not None
    assert state.state == "ERROR"
    assert "not resolved" in (state.last_error or "")


def test_daemon_rejects_source_plan_for_wrong_channel(tmp_path: Path) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    source_plan = _source_plan(tmp_path).model_copy(update={"channel_id": "schools"})
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: source_plan,
        ffmpeg_starter=lambda _args: _FakeProcess(),
    )

    daemon.process_once("gov")

    state = store.read_state("gov")
    assert state is not None
    assert state.state == "ERROR"
    assert "does not match" in (state.last_error or "")


class _FakeReconnectStrategy:
    """A GstPlayoutStrategy stand-in exposing the optional D2 worker-pipe seam
    (send_command / reconnect_channel / close_channel) so the daemon's CC-WS5-006
    reconnect + close wiring can be proven without gi or a real named pipe."""

    name = "fake-gst-reconnect"
    supports_live_swap = True
    supports_content_reload = True

    def __init__(self, processes: list[_FakeProcess], started: list[_FakeProcess]) -> None:
        self._processes = processes
        self._started = started
        self.reconnect_calls: list[str] = []
        self.close_calls: list[str] = []
        self.stop_sends: list[str] = []

    def start(self, request: EncoderStartRequest) -> EncoderStartResult:
        process = self._processes.pop(0)
        self._started.append(process)
        return EncoderStartResult(
            process=process,
            concat_plan_path=request.work_dir / "playout-graph.json",
            stdout_path=request.work_dir / "out.log",
            stderr_path=request.work_dir / "err.log",
            args=("worker",),
        )

    def swap_role(self, channel_id: str, work_dir: Path, role: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def reload_content(
        self, channel_id: str, work_dir: Path, request: EncoderStartRequest, **_kwargs: Any
    ) -> bool:  # pragma: no cover
        return True

    def send_command(self, work_dir: Path, channel_id: str, text: str) -> bool:
        self.stop_sends.append(text)
        return True

    def reconnect_channel(self, channel_id: str) -> list[str]:
        self.reconnect_calls.append(channel_id)
        return []

    def close_channel(self, channel_id: str) -> None:
        self.close_calls.append(channel_id)


def test_crash_relaunch_replays_worker_channel_desired_state(tmp_path: Path) -> None:
    """CC-WS5-006 defect 3 (reconnect wiring): when the daemon crash-relaunches a
    channel's worker, it must call the strategy's reconnect_channel so the desired
    state (reload/swap) is replayed over the fresh worker pipe."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222)]
    started: list[_FakeProcess] = []
    strategy = _FakeReconnectStrategy(processes, started)
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        encoder_strategy=strategy,
    )

    daemon.process_once("gov")
    assert strategy.reconnect_calls == []  # a fresh start is NOT a reconnect
    started[0].returncode = 1  # worker crashes
    daemon.process_once("gov")

    assert store.read_state("gov").state == "ON_AIR"  # relaunched
    assert len(started) == 2
    assert strategy.reconnect_calls == ["gov"]  # reconnect replay was wired in


def test_operator_stop_closes_worker_pipe_channel(tmp_path: Path) -> None:
    """CC-WS5-006 defect 3 (close wiring): an operator stop must close the channel's
    worker pipe so the named-pipe server is not leaked."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111)]
    started: list[_FakeProcess] = []
    strategy = _FakeReconnectStrategy(processes, started)
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        encoder_strategy=strategy,
    )

    daemon.process_once("gov")
    store.enqueue_command(_command("stop"))
    daemon.process_once("gov")

    assert store.read_state("gov").state == "STOPPED"
    assert strategy.close_calls == ["gov"]


def test_stop_all_channels_closes_worker_pipe_channels(tmp_path: Path) -> None:
    """CC-WS5-006 defect 3 (shutdown close wiring): a graceful drain-all closes each
    channel's worker pipe once its process has exited."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111, returncode=None)]  # alive at drain time
    started: list[_FakeProcess] = []
    strategy = _FakeReconnectStrategy(processes, started)

    def fake_sleep(_seconds: float) -> None:
        started[0].returncode = 0  # the worker exits while the drain loop waits

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        encoder_strategy=strategy,
        sleep=fake_sleep,
    )

    daemon.process_once("gov")
    result = daemon.stop_all_channels(deadline_seconds=5.0)

    assert strategy.stop_sends == ["stop"]  # graceful terminal command was sent
    assert strategy.close_calls == ["gov"]  # pipe closed on shutdown
    assert [o.outcome for o in result.outcomes] == ["drained"]


def test_daemon_stop_command_terminates_running_encoder(tmp_path: Path) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    process = _FakeProcess()
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        ffmpeg_starter=lambda _args: process,
    )

    daemon.process_once("gov")
    store.enqueue_command(_command("stop"))
    daemon.process_once("gov")

    state = store.read_state("gov")
    assert state is not None
    assert state.state == "STOPPED"
    assert process.terminated is True


def test_daemon_drain_command_waits_for_encoder_to_finish(tmp_path: Path) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    process = _FakeProcess()
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        ffmpeg_starter=lambda _args: process,
    )

    daemon.process_once("gov")
    store.enqueue_command(_command("drain"))
    daemon.process_once("gov")

    draining_state = store.read_state("gov")
    assert draining_state is not None
    assert draining_state.state == "DRAINING"
    assert process.terminated is False
    assert store.recent_health("gov", 1)[0].state == "DRAINING"

    process.returncode = 0
    daemon.process_once("gov")

    stopped_state = store.read_state("gov")
    assert stopped_state is not None
    assert stopped_state.state == "STOPPED"


def test_daemon_reads_encoder_metrics_from_ffmpeg_stderr_log(tmp_path: Path) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    process = _FakeProcess()
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        ffmpeg_starter=lambda _args: process,
    )

    daemon.process_once("gov")
    log_path = tmp_path / "gov" / "logs" / "ffmpeg.stderr.log"
    log_path.parent.mkdir(parents=True)
    log_path.write_text("frame= 300 fps=29.97 bitrate=6200.5kbits/s drop=2\n", encoding="utf-8")
    daemon.process_once("gov")

    health = store.recent_health("gov", 1)[0]
    assert health.encoder_fps == 29.97
    assert health.encoder_bitrate_kbps == 6200.5
    assert health.dropped_frames == 2


def test_daemon_uses_sink_health_provider_for_running_encoder(tmp_path: Path) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    process = _FakeProcess()
    seen: dict[str, object] = {}

    def sink_health_provider(channel_id, config, metrics):  # type: ignore[no-untyped-def]
        seen["channel_id"] = channel_id
        seen["sink_labels"] = [sink.label for sink in config.sinks]
        seen["fps"] = metrics.encoder_fps
        return {"Proof": False}

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        sink_health_provider=sink_health_provider,
        ffmpeg_starter=lambda _args: process,
    )

    daemon.process_once("gov")
    log_path = tmp_path / "gov" / "logs" / "ffmpeg.stderr.log"
    log_path.parent.mkdir(parents=True)
    log_path.write_text("frame= 300 fps=29.97 bitrate=6200.5kbits/s drop=2\n", encoding="utf-8")
    daemon.process_once("gov")

    health = store.recent_health("gov", 1)[0]
    assert health.state == "ON_AIR"
    assert health.sink_connected == {"Proof": False}
    assert seen == {"channel_id": "gov", "sink_labels": ["Proof"], "fps": 29.97}


def test_daemon_default_sink_health_does_not_assume_srt_connected(tmp_path: Path) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config(secret_ref="EGRESS_SRT_PASSPHRASE"))
    store.enqueue_command(_command())
    process = _FakeProcess()

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        resolve_secret=lambda _ref: "station-passphrase",
        ffmpeg_starter=lambda _args: process,
    )

    daemon.process_once("gov")

    health = store.recent_health("gov", 1)[0]
    assert health.sink_connected == {"Headend": False}


def test_playout_supervisor_combines_lookahead_plans_for_one_encoder_start(
    tmp_path: Path,
) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    process = _FakeProcess(pid=101)
    lookahead_calls: list[tuple[str, int]] = []
    upstream_calls: list[str] = []
    started_labels: list[list[str]] = []
    plans = [
        _source_plan_with_label(tmp_path, "Council meeting"),
        _source_plan_with_label(tmp_path, "Mayor interview"),
    ]

    def lookahead_provider(channel_id: str, window: int) -> list[EgressSourcePlan]:
        lookahead_calls.append((channel_id, window))
        return plans

    def start_encoder(request: EncoderStartRequest) -> EncoderStartResult:
        started_labels.append([segment.label for segment in request.source_plan.segments])
        stderr_path = tmp_path / "gov" / "logs" / "ffmpeg.stderr.log"
        return EncoderStartResult(
            process=process,
            concat_plan_path=tmp_path / "gov" / "egress-source-plan.ffconcat",
            stdout_path=tmp_path / "gov" / "logs" / "ffmpeg.stdout.log",
            stderr_path=stderr_path,
            args=("ffmpeg",),
        )

    supervisor = PlayoutSupervisor(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda channel_id: upstream_calls.append(channel_id) or None,
        lookahead_source_plan_provider=lookahead_provider,
        lookahead_window=2,
        encoder_strategy=type(
            "Strategy",
            (),
            {"name": "test", "start": staticmethod(start_encoder)},
        )(),
    )

    supervisor.process_once("gov")

    state = store.read_state("gov")
    assert state is not None
    assert state.state == "ON_AIR"
    assert state.current_source_label == "Council meeting"
    assert state.pid == 101
    assert started_labels == [["Council meeting", "Mayor interview"]]
    assert lookahead_calls == [("gov", 2)]
    assert upstream_calls == []


def test_playout_supervisor_falls_back_to_single_source_provider(tmp_path: Path) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    process = _FakeProcess()
    source_calls: list[str] = []

    supervisor = PlayoutSupervisor(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda channel_id: (
            source_calls.append(channel_id) or _source_plan_with_label(tmp_path, "Council meeting")
        ),
        ffmpeg_starter=lambda _args: process,
    )

    supervisor.process_once("gov")

    state = store.read_state("gov")
    assert state is not None
    assert state.state == "ON_AIR"
    assert state.current_source_label == "Council meeting"
    assert source_calls == ["gov"]


def test_playout_supervisor_live_takeover_and_handback_use_explicit_live_plan(
    tmp_path: Path,
) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [
        _FakeProcess(pid=101),
        _FakeProcess(pid=202),
        _FakeProcess(pid=303),
    ]
    started: list[_FakeProcess] = []
    schedule_labels = ["Council meeting", "Mayor interview"]

    def lookahead_provider(channel_id: str, window: int) -> list[EgressSourcePlan]:
        return [
            _source_plan_with_label(tmp_path, schedule_labels.pop(0))
            for _index in range(min(window, len(schedule_labels)))
        ]

    supervisor = PlayoutSupervisor(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: None,
        lookahead_source_plan_provider=lookahead_provider,
        lookahead_window=1,
        ffmpeg_starter=lambda _args: _start_fake_process(processes, started),
    )

    supervisor.process_once("gov")
    supervisor.request_live_takeover(channel_id="gov", live_source_plan=_live_source_plan(tmp_path))
    takeover_state = store.read_state("gov")
    assert takeover_state is not None
    assert takeover_state.state == "TRANSITIONING"

    started[0].returncode = 0
    supervisor.process_once("gov")
    live_state = store.read_state("gov")
    assert live_state is not None
    assert live_state.state == "ON_AIR"
    assert live_state.current_source_label == "Live: Council chamber"

    supervisor.request_live_handback(channel_id="gov")
    handback_state = store.read_state("gov")
    assert handback_state is not None
    assert handback_state.state == "TRANSITIONING"

    started[1].returncode = 0
    supervisor.process_once("gov")
    scheduled_state = store.read_state("gov")
    assert scheduled_state is not None
    assert scheduled_state.state == "ON_AIR"
    assert scheduled_state.current_source_label == "Mayor interview"
    assert [process.pid for process in started] == [101, 202, 303]
    summaries = [event.machine_summary for event in store.recent_proof_events("gov", 5)]
    assert any("began live takeover" in summary for summary in summaries)
    assert any("released live source" in summary for summary in summaries)


def test_playout_supervisor_forces_fallback_slate_and_exits_to_schedule(
    tmp_path: Path,
) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [
        _FakeProcess(pid=101),
        _FakeProcess(pid=202),
        _FakeProcess(pid=303),
    ]
    started: list[_FakeProcess] = []
    schedule_labels = ["Council meeting", "Mayor interview"]

    def lookahead_provider(channel_id: str, window: int) -> list[EgressSourcePlan]:
        return [
            _source_plan_with_label(tmp_path, schedule_labels.pop(0))
            for _index in range(min(window, len(schedule_labels)))
        ]

    supervisor = PlayoutSupervisor(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: None,
        lookahead_source_plan_provider=lookahead_provider,
        lookahead_window=1,
        fallback_source_provider=lambda _config: _slate_plan(tmp_path),
        ffmpeg_starter=lambda _args: _start_fake_process(processes, started),
    )

    supervisor.process_once("gov")
    supervisor.request_fallback_slate(channel_id="gov", reason="scheduled asset missing")
    slate_transition = store.read_state("gov")
    assert slate_transition is not None
    assert slate_transition.state == "TRANSITIONING"

    started[0].returncode = 0
    supervisor.process_once("gov")
    slate_state = store.read_state("gov")
    assert slate_state is not None
    assert slate_state.state == "FALLBACK_SLATE"
    assert slate_state.current_source_label == "Fallback slate"
    assert slate_state.last_error == "scheduled asset missing"

    supervisor.request_slate_exit(channel_id="gov")
    exit_transition = store.read_state("gov")
    assert exit_transition is not None
    assert exit_transition.state == "TRANSITIONING"

    started[1].returncode = 0
    supervisor.process_once("gov")
    scheduled_state = store.read_state("gov")
    assert scheduled_state is not None
    assert scheduled_state.state == "ON_AIR"
    assert scheduled_state.current_source_label == "Mayor interview"
    assert [process.pid for process in started] == [101, 202, 303]


def test_playout_supervisor_raises_and_clears_cg_overlay_immediately(
    tmp_path: Path,
) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    process = _FakeProcess()
    supervisor = PlayoutSupervisor(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        ffmpeg_starter=lambda _args: process,
    )
    proof = build_cg_overlay_egress_proof(
        overlay=build_emergency_overlay(overlay_id="notice-1", severity="warning"),
        overlay_contract=build_overlay_contract(channel_id="gov"),
    )

    supervisor.process_once("gov")
    supervisor.raise_cg_emergency_overlay(proof=proof)
    supervisor.clear_cg_emergency_overlay(channel_id="gov")

    overlay_events = [
        event
        for event in store.recent_proof_events("gov", 5)
        if event.proof_boundary == CG_EGRESS_PROOF_BOUNDARY
    ]
    assert [event.source_label for event in overlay_events] == [
        "CivicCast emergency banner cleared",
        "CivicCast emergency banner",
    ]
    assert overlay_events[0].state == "ON_AIR"
    assert "not an EAS claim" in overlay_events[0].machine_summary


# --- S9-5 crash-relaunch back-off -----------------------------------------------------


class _FakeMonotonic:
    """An injectable monotonic clock for deterministic latch cooldown tests."""

    def __init__(self, start: float = 0.0) -> None:
        self.t = start

    def now(self) -> float:
        return self.t


def _backoff_daemon(
    tmp_path: Path, started: list[_FakeProcess], pids, cooldown: float, monotonic=None
):
    """A daemon whose ffmpeg_starter hands out fake processes with the given pids.
    ``monotonic`` is injected through the public constructor seam so deferral tests
    drive the back-off clock deterministically without touching private state."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=pid, returncode=None) for pid in pids]
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        ffmpeg_starter=lambda _args: _start_fake_process(processes, started),
        restart_cooldown_seconds=cooldown,
        monotonic=monotonic,
    )
    return daemon, store


def test_first_crash_relaunches_immediately_then_rapid_repeat_defers(tmp_path: Path) -> None:
    """The first crash relaunches at once (fast one-off recovery); a crash that recurs
    within the cooldown is paced, not hot-looped — no new process this tick."""
    started: list[_FakeProcess] = []
    daemon, store = _backoff_daemon(tmp_path, started, (111, 222, 333), cooldown=100.0)

    daemon.process_once("gov")  # start → pid 111 on air
    started[0].returncode = 1
    daemon.process_once("gov")  # crash 1 → immediate relaunch → pid 222
    assert len(started) == 2
    assert store.read_state("gov").state == "ON_AIR"

    started[1].returncode = 1
    daemon.process_once("gov")  # crash 2 within cooldown → DEFER, no new process
    assert len(started) == 2
    state = store.read_state("gov")
    assert state.state == "STARTING"
    assert "backing off" in (state.last_error or "")
    # the failure was still recorded as a proof event (no silent swallow)
    assert any(
        e.source_path == "ffmpeg-child:nonzero-exit" for e in store.recent_proof_events("gov", 12)
    )


def test_deferred_relaunch_fires_once_cooldown_elapses(tmp_path: Path) -> None:
    """A deferred crash-relaunch lands on the process_once tick after the cooldown."""
    started: list[_FakeProcess] = []
    clock = _FakeMonotonic(0.0)
    daemon, store = _backoff_daemon(
        tmp_path, started, (111, 222, 333), cooldown=15.0, monotonic=clock.now
    )

    daemon.process_once("gov")  # start → 111
    started[0].returncode = 1
    clock.t = 0.0
    daemon.process_once("gov")  # crash 1 at t=0 → relaunch 222 (arms next=15)
    assert len(started) == 2

    started[1].returncode = 1
    clock.t = 5.0
    daemon.process_once("gov")  # crash 2 at t=5 (<15) → defer
    assert len(started) == 2
    assert store.read_state("gov").state == "STARTING"

    clock.t = 20.0
    daemon.process_once("gov")  # t=20 ≥ 15 → deferred relaunch fires → 333
    assert len(started) == 3
    assert store.read_state("gov").state == "ON_AIR"


def test_restart_escalation_event_fires_at_threshold_and_every_multiple(tmp_path: Path) -> None:
    """A distinct restart-escalation proof event (the S8 alerting hook seam) fires at the
    escalation streak AND RE-FIRES at every multiple (n, 2n, …) so a long crash loop keeps
    alerting. The in-between streaks emit nothing — this pins the modulo boundary so a
    regression to fire-once cannot pass silently."""
    started: list[_FakeProcess] = []
    n = _RESTART_ESCALATION_STREAK
    pids = tuple(100 + i for i in range(2 * n + 1))  # start + 2n relaunches
    daemon, store = _backoff_daemon(tmp_path, started, pids, cooldown=0.0)  # never defer

    def escalation_count() -> int:
        return sum(
            1
            for e in store.recent_proof_events("gov", 100)
            if e.source_path == "ffmpeg-child:restart-escalation"
        )

    daemon.process_once("gov")  # start (streak 0)
    counts: list[int] = []
    for _ in range(2 * n):
        started[-1].returncode = 1
        daemon.process_once("gov")  # cooldown=0 → every crash relaunches; streak climbs 1..2n
        counts.append(escalation_count())

    # counts[i] = escalation count after crash i+1. Fire at streak n and 2n; quiet between.
    assert counts[n - 1] == 1, "escalation did not fire at the first threshold (streak n)"
    assert counts[2 * n - 2] == 1, "an in-between streak (2n-1) wrongly escalated"
    assert counts[2 * n - 1] == 2, "escalation did not RE-FIRE at the second multiple (streak 2n)"

    escalations = [
        e
        for e in store.recent_proof_events("gov", 100)
        if e.source_path == "ffmpeg-child:restart-escalation"
    ]
    assert "crash-relaunched" in escalations[0].machine_summary
    # recent-first: escalations[0] is the streak-2n event, escalations[1] the streak-n event.
    assert str(2 * n) in escalations[0].machine_summary
    assert str(n) in escalations[1].machine_summary


def test_healthy_uptime_resets_the_crash_streak(tmp_path: Path) -> None:
    """A worker that stays up healthily clears the crash streak, so a later failure is
    treated as a fresh one-off (immediate relaunch, no escalation carry-over)."""
    import time as _time

    started: list[_FakeProcess] = []
    daemon, store = _backoff_daemon(tmp_path, started, (100, 101, 102), cooldown=0.0)

    daemon.process_once("gov")  # start → 100
    started[0].returncode = 1
    daemon.process_once("gov")  # crash 1 → streak 1 → relaunch 101
    assert daemon._restart_streak.get("gov") == 1

    # the relaunched worker has now been up well past the reset threshold
    daemon._started_at["gov"] = _time.monotonic() - 120.0
    daemon.process_once("gov")  # healthy poll → streak cleared
    assert daemon._restart_streak.get("gov") is None
    assert store.read_state("gov").state == "ON_AIR"


class _EncoderUnavailableThenSlateStrategy:
    """First ``start()`` (the program plan) raises ``EncoderUnavailableError``;
    the retry (the slate plan) succeeds. Models degraded-mode tier 4: the egress
    encoder is unavailable for the program, so the daemon must put up the
    technical-difficulties slate rather than dropping the channel to dead air."""

    name = "fake-encoder-unavailable-then-slate"
    supports_live_swap = False
    supports_content_reload = False

    def __init__(self) -> None:
        self.start_labels: list[str] = []

    def start(self, request: EncoderStartRequest) -> EncoderStartResult:
        from civiccast.egress.errors import EncoderUnavailableError

        label = request.source_plan.segments[0].label
        self.start_labels.append(label)
        if label != "Fallback slate":
            raise EncoderUnavailableError("no usable egress encoder (ffmpeg absent)")
        return EncoderStartResult(
            process=_FakeProcess(pid=515),
            concat_plan_path=request.work_dir / "playout-graph.json",
            stdout_path=request.work_dir / "out.log",
            stderr_path=request.work_dir / "err.log",
            args=("worker",),
        )


def test_encoder_unavailable_airs_the_slate_instead_of_dead_air(tmp_path: Path) -> None:
    """Degraded-mode tier 4 (owner ruling: dead air is the cardinal sin). When
    the egress encoder cannot start for the program source -- e.g. GStreamer
    already fell back to FFmpeg and FFmpeg ALSO failed -- the daemon must air the
    fallback slate (state FALLBACK_SLATE), never drop to ERROR/black."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    strategy = _EncoderUnavailableThenSlateStrategy()

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        fallback_source_provider=lambda _config: _slate_plan(tmp_path),
        encoder_strategy=strategy,  # type: ignore[arg-type]
    )

    assert daemon.process_once("gov") == 1

    state = store.read_state("gov")
    assert state is not None
    # Slate, NOT dead air.
    assert state.state == "FALLBACK_SLATE"
    assert state.state != "ERROR"
    assert "encoder unavailable" in (state.last_error or "")
    # Tried the program first, then the slate.
    assert strategy.start_labels == ["Council meeting", "Fallback slate"]


def test_start_releases_the_prepared_plan_when_the_encoder_falls_back_to_slate(
    tmp_path: Path,
) -> None:
    """Hostile-review follow-up (second pass), item 1: prepare() succeeds
    (mints a real plan_dir for the PROGRAM plan) before the encoder-
    unavailable retry decides to air the fallback slate instead --
    using_fallback_slate flips True AFTER prepare() already ran, so the
    pre-fix guard at the tracking site silently DROPPED the reference
    without ever releasing it. Proves it is released instead."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    strategy = _EncoderUnavailableThenSlateStrategy()
    counter = {"n": 0}
    released: list[Path] = []

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        fallback_source_provider=lambda _config: _slate_plan(tmp_path),
        encoder_strategy=strategy,  # type: ignore[arg-type]
        source_preparer=_prepare_with_tracked_plan_dirs(tmp_path, counter),
        prepared_plan_release=released.append,
    )

    daemon.process_once("gov")

    state = store.read_state("gov")
    assert state is not None
    assert state.state == "FALLBACK_SLATE"
    # The program plan's prepared directory (plan-1) was minted, then
    # released once the slate aired instead -- never tracked as active
    # (the slate was never built by the preparer), never left dangling.
    assert released == [tmp_path / "plan-1"]
    assert daemon.live_prepared_plan_dirs("gov") == frozenset()


def test_start_tracks_not_releases_the_prepared_plan_for_a_force_fallback_slate(
    tmp_path: Path,
) -> None:
    """Hostile-review follow-up (third pass), P0: ``using_fallback_slate``
    also flips True on THREE paths BEFORE the preparer ever runs --
    ``force_fallback_slate`` (the crash-loop latch), a caption-readiness
    refusal, and ``source_plan is None`` (this test covers the first). On
    all three, the preparer runs against the SLATE plan itself (source_plan
    was already reassigned before the preparer block), so the resulting
    prepared_plan_dir is what the encoder is ACTIVELY airing from -- the
    pre-fix tracking code released (rmtree'd) it out from under the live
    slate the moment it started airing (reviewer-proven with a probe:
    prepared_for=['Fallback slate'], state FALLBACK_SLATE pid=111,
    released=['plan-1']). Proves the directory is tracked as active while
    the slate airs, NOT released, and is only released once that worker
    actually exits."""
    from civiccast.egress.daemon import _LIVE_SOURCE_FAILURE_FALLBACK_STREAK

    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    n = _LIVE_SOURCE_FAILURE_FALLBACK_STREAK
    pids = tuple(100 + i for i in range(n + 2))  # 1 initial start + n relaunches + 1 more
    processes = [_FakeProcess(pid=pid, returncode=None) for pid in pids]
    started: list[_FakeProcess] = []
    counter = {"n": 0}
    released: list[Path] = []

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _live_source_plan(tmp_path),
        fallback_source_provider=lambda _config: _slate_plan(tmp_path),
        ffmpeg_starter=lambda _args: _start_fake_process(processes, started),
        source_preparer=_prepare_with_tracked_plan_dirs(tmp_path, counter),
        prepared_plan_release=released.append,
        restart_cooldown_seconds=0.0,  # never defer — isolate the fallback trigger itself
    )

    daemon.process_once("gov")  # start -> the live source, ON_AIR (plan-1, tracked active)
    for _ in range(n):
        started[-1].returncode = 1  # the live source drops / never connects
        daemon.process_once("gov")  # the LAST of these force_fallback_slate=True

    state = store.read_state("gov")
    assert state is not None
    assert state.state == "FALLBACK_SLATE"
    # The slate's own prepared plan (whatever plan-N the preparer minted on
    # the force_fallback_slate relaunch) is tracked ACTIVE, not released,
    # while this worker airs it.
    active_dir = daemon._active_prepared_plan_dir.get("gov")  # type: ignore[attr-defined]
    assert active_dir is not None
    assert active_dir not in released
    assert daemon.live_prepared_plan_dirs("gov") == frozenset({active_dir})

    # Once THAT worker exits (a clean exit here, e.g. an operator stop), the
    # slate's own directory is released like any other active plan.
    started[-1].returncode = 0
    daemon.process_once("gov")
    assert active_dir in released
    assert daemon.live_prepared_plan_dirs("gov") == frozenset()


def test_start_tracks_not_releases_the_prepared_plan_for_a_caption_readiness_refusal(
    tmp_path: Path,
) -> None:
    """Hostile-review follow-up (third pass), P0 (second early-flip path):
    same defect as the force_fallback_slate test above, triggered instead by
    a caption-readiness refusal that requires the fallback slate."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222)]
    started: list[_FakeProcess] = []
    counter = {"n": 0}
    released: list[Path] = []

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        fallback_source_provider=lambda _config: _slate_plan(tmp_path),
        caption_readiness_provider=lambda _channel_id: SimpleNamespace(
            ready=False,
            refusal_reason="free-space-reserve-unrestorable",
            requires_fallback_slate=True,
        ),
        ffmpeg_starter=lambda _args: _start_fake_process(processes, started),
        source_preparer=_prepare_with_tracked_plan_dirs(tmp_path, counter),
        prepared_plan_release=released.append,
    )

    daemon.process_once("gov")

    state = store.read_state("gov")
    assert state is not None
    assert state.state == "FALLBACK_SLATE"
    assert released == []  # the slate's own directory (plan-1) is airing, not released
    assert daemon.live_prepared_plan_dirs("gov") == frozenset({tmp_path / "plan-1"})

    started[0].returncode = 0  # the slate worker exits cleanly
    daemon.process_once("gov")
    assert released == [tmp_path / "plan-1"]
    assert daemon.live_prepared_plan_dirs("gov") == frozenset()


def test_start_tracks_not_releases_the_prepared_plan_for_a_missing_source_plan(
    tmp_path: Path,
) -> None:
    """Hostile-review follow-up (third pass), P0 (third early-flip path):
    same defect as the two tests above, triggered instead by
    ``source_plan_provider`` returning ``None`` with a fallback configured."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111), _FakeProcess(pid=222)]
    started: list[_FakeProcess] = []
    counter = {"n": 0}
    released: list[Path] = []

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: None,
        fallback_source_provider=lambda _config: _slate_plan(tmp_path),
        ffmpeg_starter=lambda _args: _start_fake_process(processes, started),
        source_preparer=_prepare_with_tracked_plan_dirs(tmp_path, counter),
        prepared_plan_release=released.append,
    )

    daemon.process_once("gov")

    state = store.read_state("gov")
    assert state is not None
    assert state.state == "FALLBACK_SLATE"
    assert released == []  # the slate's own directory (plan-1) is airing, not released
    assert daemon.live_prepared_plan_dirs("gov") == frozenset({tmp_path / "plan-1"})

    started[0].returncode = 0  # the slate worker exits cleanly
    daemon.process_once("gov")
    assert released == [tmp_path / "plan-1"]
    assert daemon.live_prepared_plan_dirs("gov") == frozenset()


def test_start_releases_the_prepared_plan_on_a_failure_after_prepare_succeeds(
    tmp_path: Path,
) -> None:
    """Hostile-review follow-up (second pass), item 2: ANY raise between a
    successful prepare() and the tracking decision (a provider hook here --
    cg_overlay_provider) used to leak prepared_plan_dir; each retry (e.g. a
    subsequent auto_start pass) would mint another one. Proves the directory
    is released, and that the exception still propagates out of _start
    unchanged (existing outer behavior for an exception this generic --
    logged by process_once's command loop -- is untouched by this fix; the
    fix is scoped to the plan_dir, not to changing what state the row is
    left in)."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    processes = [_FakeProcess(pid=111)]
    started: list[_FakeProcess] = []
    counter = {"n": 0}
    released: list[Path] = []

    def _raising_cg_overlay_provider(_channel_id: str, _config: EgressConfig) -> Path | None:
        raise RuntimeError("simulated board-overlay provider failure")

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _cid: _source_plan(tmp_path),
        encoder_strategy=_FakeContentReloadStrategy(processes, started),
        source_preparer=_prepare_with_tracked_plan_dirs(tmp_path, counter),
        prepared_plan_release=released.append,
        cg_overlay_provider=_raising_cg_overlay_provider,
    )

    daemon.process_once("gov")

    assert released == [tmp_path / "plan-1"]  # released, not leaked
    assert daemon.live_prepared_plan_dirs("gov") == frozenset()
    assert len(started) == 0  # the encoder never even started
    assert daemon._active_prepared_plan_dir.get("gov") is None  # never tracked as active


def test_encoder_unavailable_with_no_fallback_provider_is_error_not_a_crash(
    tmp_path: Path,
) -> None:
    """With no fallback provider there is no slate to air, so the channel goes
    to ERROR -- but the daemon still never raises out of process_once."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())

    class _AlwaysUnavailable:
        name = "always-unavailable"
        supports_live_swap = False
        supports_content_reload = False

        def start(self, request: EncoderStartRequest) -> EncoderStartResult:
            from civiccast.egress.errors import EncoderUnavailableError

            raise EncoderUnavailableError("no usable egress encoder")

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        encoder_strategy=_AlwaysUnavailable(),  # type: ignore[arg-type]
    )

    assert daemon.process_once("gov") == 1
    state = store.read_state("gov")
    assert state is not None
    assert state.state == "ERROR"


class _AlwaysFfmpegNotFoundStrategy:
    """Every ``start()`` raises ``FfmpegNotFoundError``, regardless of which
    source plan (program or slate) is requested. This mirrors the REAL
    ``ConcatEncoderStrategy`` in production: its ``FfmpegNotFoundError`` comes
    from ``civiccast.stream._ffmpeg._ffmpeg_path()``, a pure
    ``shutil.which("ffmpeg")`` PATH lookup that is completely independent of
    the content being encoded, so it is deterministic across calls within one
    process. (P1 audit finding on an earlier version of this test file: a fake
    strategy that raised for the program plan but *succeeded* for the slate
    plan modeled a state the real ``ConcatEncoderStrategy`` can never enter --
    a passing test that proved nothing about production behavior.)"""

    name = "fake-always-ffmpeg-not-found"
    supports_live_swap = False
    supports_content_reload = False

    def __init__(self) -> None:
        self.start_labels: list[str] = []

    def start(self, request: EncoderStartRequest) -> EncoderStartResult:
        from civiccast.stream._ffmpeg import FfmpegNotFoundError

        self.start_labels.append(request.source_plan.segments[0].label)
        raise FfmpegNotFoundError(
            "ffmpeg not found on PATH. Install or repair the bundled FFmpeg "
            "runtime and verify it with 'civiccast doctor'."
        )


class _FakeIndependentSlateStrategy:
    """Models ``GstPlayoutStrategy`` standing in as the K2-1 follow-up's
    genuinely separate, ffmpeg-PATH-independent last-resort encoder: a
    DIFFERENT strategy instance from the one that raised ``FfmpegNotFoundError``,
    injected via ``independent_slate_strategy_factory`` rather than by making
    the SAME fake strategy behave inconsistently."""

    name = "fake-independent-slate-encoder"
    supports_live_swap = False
    supports_content_reload = False

    def __init__(self) -> None:
        self.start_labels: list[str] = []

    def start(self, request: EncoderStartRequest) -> EncoderStartResult:
        self.start_labels.append(request.source_plan.segments[0].label)
        return EncoderStartResult(
            process=_FakeProcess(pid=516),
            concat_plan_path=request.work_dir / "playout-graph.json",
            stdout_path=request.work_dir / "out.log",
            stderr_path=request.work_dir / "err.log",
            args=("worker",),
        )


def test_ffmpeg_not_found_airs_the_slate_instead_of_dead_air(tmp_path: Path) -> None:
    """Audit K2-1 (MAJOR, release-blocking) + P1 follow-up: a missing ffmpeg
    binary for the program source must land the channel on the fallback slate
    (state FALLBACK_SLATE), with the same operator-visible degradation event
    (last_error + a FALLBACK_SLATE proof event + health sample) as any other
    tier transition -- never ERROR/dead air while an independent slate encoder
    is available. The recovery must come from a genuinely SEPARATE encoder
    (``independent_slate_strategy_factory``, standing in for the real
    ``GstPlayoutStrategy``) -- retrying the SAME ffmpeg-concat strategy can
    never succeed, since its FfmpegNotFoundError is a content-independent PATH
    lookup (see ``_AlwaysFfmpegNotFoundStrategy``)."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())
    strategy = _AlwaysFfmpegNotFoundStrategy()
    independent_strategy = _FakeIndependentSlateStrategy()

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        fallback_source_provider=lambda _config: _slate_plan(tmp_path),
        encoder_strategy=strategy,  # type: ignore[arg-type]
        independent_slate_strategy_factory=lambda: independent_strategy,  # type: ignore[arg-type, return-value]
    )

    assert daemon.process_once("gov") == 1

    state = store.read_state("gov")
    assert state is not None
    # Slate, NOT dead air.
    assert state.state == "FALLBACK_SLATE"
    assert state.state != "ERROR"
    assert "ffmpeg not found" in (state.last_error or "").lower()
    # The program tier was tried once (and failed) against the ffmpeg-concat
    # strategy; the slate tier was tried against the SEPARATE independent
    # encoder, not a second call to the strategy already known to be unusable.
    assert strategy.start_labels == ["Council meeting"]
    assert independent_strategy.start_labels == ["Fallback slate"]

    proof_events = store.recent_proof_events("gov", 1)
    assert proof_events[0].state == "FALLBACK_SLATE"
    assert store.recent_health("gov", 1)[0].state == "FALLBACK_SLATE"


def test_ffmpeg_not_found_with_no_fallback_provider_is_error_not_a_crash(
    tmp_path: Path,
) -> None:
    """With no fallback provider there is no slate to air, so the channel goes
    to ERROR -- but the daemon still never raises out of process_once."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())

    class _AlwaysFfmpegNotFound:
        name = "always-ffmpeg-not-found"
        supports_live_swap = False
        supports_content_reload = False

        def start(self, request: EncoderStartRequest) -> EncoderStartResult:
            from civiccast.stream._ffmpeg import FfmpegNotFoundError

            raise FfmpegNotFoundError("ffmpeg not found on PATH.")

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        encoder_strategy=_AlwaysFfmpegNotFound(),  # type: ignore[arg-type]
    )

    assert daemon.process_once("gov") == 1
    state = store.read_state("gov")
    assert state is not None
    assert state.state == "ERROR"


def test_ffmpeg_not_found_on_slate_too_is_the_true_zero_ffmpeg_floor(
    tmp_path: Path,
) -> None:
    """Documents the true zero-anything floor (K2 design: a no-crash state with
    operator alerting). If ffmpeg is genuinely absent from the machine AND no
    independent encoder (GStreamer) is available in this deployment either
    (``independent_slate_strategy_factory`` returns None, exactly as the real
    ``_default_independent_slate_strategy`` does when the gst package is not
    importable), the slate retry falls back to the SAME broken ffmpeg-concat
    strategy and fails too. The ladder must still land the channel on ERROR
    (not raise out of process_once, not silently hang) with last_error naming
    the real cause, after having genuinely attempted the slate tier first."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())

    strategy = _AlwaysFfmpegNotFoundStrategy()
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        fallback_source_provider=lambda _config: _slate_plan(tmp_path),
        encoder_strategy=strategy,  # type: ignore[arg-type]
        independent_slate_strategy_factory=lambda: None,
    )

    assert daemon.process_once("gov") == 1
    # The ladder genuinely tried both tiers before giving up -- no independent
    # encoder was available, so the slate retry went through the same
    # ffmpeg-concat strategy as the program attempt.
    assert strategy.start_labels == ["Council meeting", "Fallback slate"]

    state = store.read_state("gov")
    assert state is not None
    assert state.state == "ERROR"
    assert "ffmpeg not found" in (state.last_error or "").lower()
    assert store.recent_health("gov", 1)[0].state == "ERROR"


def test_default_independent_slate_strategy_is_none_when_gst_not_importable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The production default factory must never raise -- an unavailable
    GStreamer package in this deployment is exactly the expected "no
    independent fallback" case, not an error."""
    import builtins

    from civiccast.egress.daemon import _default_independent_slate_strategy

    real_import = builtins.__import__

    def _blocked_import(
        name: str,
        globals: Any = None,  # noqa: A002 - matches builtins.__import__'s own parameter name
        locals: Any = None,  # noqa: A002 - matches builtins.__import__'s own parameter name
        fromlist: Any = (),
        level: int = 0,
    ) -> Any:
        if name == "civiccast.egress.gst.strategy" or name.startswith(
            "civiccast.egress.gst.strategy."
        ):
            raise ImportError(f"simulated: {name} not installed")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _blocked_import)
    assert _default_independent_slate_strategy() is None


# --- BLOCKER B1: a live source that keeps crashing the worker must land on slate,
# --- never crash-loop against the same dead source forever ("dead air is NEVER
# --- acceptable" — see the encoder-unavailable comment in daemon.py). --------------


def test_repeated_live_source_crash_falls_back_to_slate_instead_of_dead_air_loop(
    tmp_path: Path,
) -> None:
    """A live SRT/UDP/RTSP source that is unreachable or drops crashes the
    worker immediately after each relaunch — the encoder process itself starts
    fine (so ``_start``'s own EncoderUnavailableError/FfmpegNotFoundError
    fallback-to-slate seam never fires), then dies inside the pipeline once it
    can't connect to / keep reading the source. Before this fix,
    ``_relaunch_after_crash`` paced the RATE of relaunch but always relaunched
    against the SAME source_plan_provider, so this was an infinite crash-loop
    with no terminal slate state — dead air forever. After
    ``_LIVE_SOURCE_FAILURE_FALLBACK_STREAK`` consecutive crash-relaunches that
    never once reached a healthy uptime, the daemon must stop trusting the
    configured live source and force the fallback-slate path instead."""
    from civiccast.egress.daemon import _LIVE_SOURCE_FAILURE_FALLBACK_STREAK

    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())

    n = _LIVE_SOURCE_FAILURE_FALLBACK_STREAK
    pids = tuple(100 + i for i in range(n + 1))  # 1 initial start + n relaunches
    processes = [_FakeProcess(pid=pid, returncode=None) for pid in pids]
    started: list[_FakeProcess] = []

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _live_source_plan(tmp_path),
        fallback_source_provider=lambda _config: _slate_plan(tmp_path),
        ffmpeg_starter=lambda _args: _start_fake_process(processes, started),
        restart_cooldown_seconds=0.0,  # never defer — isolate the fallback trigger itself
    )

    daemon.process_once("gov")  # start → the live source, ON_AIR
    state = store.read_state("gov")
    assert state is not None
    assert state.state == "ON_AIR"
    assert state.current_source_label == "Live: Council chamber"

    for _ in range(n):
        started[-1].returncode = 1  # the live source drops / never connects
        daemon.process_once("gov")

    state = store.read_state("gov")
    assert state is not None
    # The terminal state that replaces dead air: slate, not a channel still
    # silently crash-looping against the same unreachable source.
    assert state.state == "FALLBACK_SLATE"
    assert state.current_source_label == "Fallback slate"
    assert state.last_error is not None
    assert str(n) in state.last_error
    assert len(started) == n + 1  # every relaunch actually tried a fresh process
    assert store.recent_health("gov", 1)[0].state == "FALLBACK_SLATE"


def test_live_source_fallback_latches_stably_even_if_the_slate_encoder_also_crashes(
    tmp_path: Path,
) -> None:
    """Once the crash streak has forced the channel onto the fallback slate,
    a further crash of THAT slate encoder must relaunch the slate again — not
    bounce back to re-resolving the still-dead live source via
    ``source_plan_provider`` for one attempt before flapping back to slate on
    the next crash. The streak only clears on a healthy uptime or an explicit
    operator/automation command (see ``_begin_relaunch``'s docstring), so the
    channel stays latched onto a stable slate state across repeat crashes of
    the slate encoder itself, instead of an ON_AIR/FALLBACK_SLATE flap."""
    from civiccast.egress.daemon import _LIVE_SOURCE_FAILURE_FALLBACK_STREAK

    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())

    n = _LIVE_SOURCE_FAILURE_FALLBACK_STREAK
    # 1 initial start + n relaunches to reach slate + n more relaunches of the
    # (also crashing) slate encoder itself.
    pids = tuple(100 + i for i in range(2 * n + 1))
    processes = [_FakeProcess(pid=pid, returncode=None) for pid in pids]
    started: list[_FakeProcess] = []

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _live_source_plan(tmp_path),
        fallback_source_provider=lambda _config: _slate_plan(tmp_path),
        ffmpeg_starter=lambda _args: _start_fake_process(processes, started),
        restart_cooldown_seconds=0.0,
    )

    daemon.process_once("gov")
    for _ in range(n):
        started[-1].returncode = 1
        daemon.process_once("gov")
    assert store.read_state("gov").state == "FALLBACK_SLATE"

    for _ in range(n):
        started[-1].returncode = 1  # the slate encoder itself keeps crashing too
        daemon.process_once("gov")
        # Every relaunch in this loop stayed on slate — none of them ever
        # bounced back to ON_AIR against the still-dead live source.
        state = store.read_state("gov")
        assert state is not None
        assert state.state == "FALLBACK_SLATE"
        assert state.current_source_label == "Fallback slate"

    assert len(started) == 2 * n + 1


# --- MAJOR M1: an HLS relay child death must surface in health, not stay invisible --


def test_dead_hls_relay_overrides_sink_health_to_false_on_the_next_daemon_tick(
    tmp_path: Path,
) -> None:
    """Before this fix, nothing polled the HLS relay subprocess after start:
    ``/api/staff/egress/channels/{id}/health`` derived the ``hls`` sink's
    ``connected`` flag purely from the MAIN encoder's own UDP send progress
    (``build_default_sink_health`` / an injected ``sink_health_provider``),
    blind to whether the SEPARATE relay child (disk full / ffmpeg missing /
    OOM) was still alive. This proves the daemon now polls
    ``HlsRelaySupervisor.is_alive`` every ``process_once`` tick and overrides
    the hls sink to unhealthy the moment the relay is confirmed dead — even
    though the injected health provider below always claims "connected", so
    the assertion can only pass if the daemon's own liveness poll is what
    flipped it."""
    from civiccast.egress.hls_relay import HlsRelaySupervisor

    store = InMemoryEgressStore()
    hls_sink = EgressSinkSpec(kind="hls", label="Web", uri=str(tmp_path / "hls-live"))
    store.upsert_config(
        EgressConfig(channel_id="gov", enabled=True, slate_message="slate", sinks=[hls_sink])
    )
    store.enqueue_command(_command())

    relay_procs: list[_FakeProcess] = []

    def relay_starter(_args: list[str]) -> _FakeProcess:
        proc = _FakeProcess(pid=999)
        relay_procs.append(proc)
        return proc

    hls_relay = HlsRelaySupervisor(starter=relay_starter)

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        ffmpeg_starter=lambda _args: _FakeProcess(pid=4242, returncode=None),
        hls_relay_supervisor=hls_relay,
        # Always claims "connected" — proves the override, not the provider,
        # is what produces the False below.
        sink_health_provider=lambda _channel_id, _config, _metrics: {"Web": True},
    )

    assert daemon.process_once("gov") == 1
    assert len(relay_procs) == 1  # the relay was actually created for the hls sink
    assert store.recent_health("gov", 1)[0].sink_connected == {"Web": True}

    relay_procs[0].returncode = 1  # the relay child dies on its own between ticks
    daemon.process_once("gov")  # a routine tick — the main encoder is unaffected

    health = store.recent_health("gov", 1)[0]
    assert health.sink_connected == {"Web": False}


def test_hls_relay_health_override_is_not_applied_when_relay_is_still_alive(
    tmp_path: Path,
) -> None:
    """Negative case for the same seam: a live relay must never be forced
    unhealthy — the override is death-specific, not a blanket downgrade."""
    from civiccast.egress.hls_relay import HlsRelaySupervisor

    store = InMemoryEgressStore()
    hls_sink = EgressSinkSpec(kind="hls", label="Web", uri=str(tmp_path / "hls-live"))
    store.upsert_config(
        EgressConfig(channel_id="gov", enabled=True, slate_message="slate", sinks=[hls_sink])
    )
    store.enqueue_command(_command())

    hls_relay = HlsRelaySupervisor(starter=lambda _args: _FakeProcess(pid=999))

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        ffmpeg_starter=lambda _args: _FakeProcess(pid=4242, returncode=None),
        hls_relay_supervisor=hls_relay,
        sink_health_provider=lambda _channel_id, _config, _metrics: {"Web": True},
    )

    daemon.process_once("gov")
    daemon.process_once("gov")  # a second, routine tick — relay never died

    assert store.recent_health("gov", 1)[0].sink_connected == {"Web": True}


def test_daemon_records_the_source_plan_it_actually_dispatched(tmp_path: Path) -> None:
    """Hostile-review (d): channel automation's rollover pass needs to know when the
    AIRING plan runs out, and the only honest source for that is the plan the daemon
    actually sent. Before this, automation re-called the source plan provider and
    summed whatever came back -- a different, re-windowed segment list that can put
    the projected end (and therefore the rollover trigger) past the real one.

    The record is keyed by the proof event written alongside it, so a consumer can
    tell "this is what is on air" from "this is stale"."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        ffmpeg_starter=lambda _args: _FakeProcess(),
    )

    assert daemon.dispatched_plan_horizon("gov") is None
    assert daemon.process_once("gov") == 1

    state = store.read_state("gov")
    assert state is not None
    recorded = daemon.dispatched_plan_horizon("gov")
    assert recorded is not None
    proof_event_id, durations, switch_deferred = recorded
    assert proof_event_id == state.current_proof_event_id
    assert durations == tuple(
        float(segment.duration_seconds) for segment in _source_plan(tmp_path).segments
    )
    # A START puts its plan on air immediately -- only a content-reload can defer.
    assert switch_deferred is False


def test_child_stderr_tail_is_ascii_folded_before_it_reaches_last_error(tmp_path: Path) -> None:
    """T6 soak 2026-09-05 (kit e502074, Desktop/CIVICCAST-EVIDENCE/
    soak-120-e502074-20260905): the worker's stall line carried one non-ASCII
    character, came back from the child log as U+FFFD (the tail reader uses
    ``errors="replace"``), was folded into ``last_error`` and then failed the
    Postgres state write with ``UnicodeEncodeError: 'charmap' codec can't encode
    character '\ufffd'``. That exception escaped ``process_once`` and aborted
    ``ChannelAutomationService._run_channel_pass`` before ``_check_plan_rollover``
    ever ran -- 23 aborted passes, zero rollovers, in a 2h soak.

    The tail must therefore be ASCII by the time it can be persisted.
    """
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        ffmpeg_starter=lambda _args: _FakeProcess(),
    )
    log_path = tmp_path / "gov-stderr.log"
    log_path.write_text(
        "CTRL stall: no output for 10s � quitting for daemon restart\n",
        encoding="utf-8",
    )
    daemon._stderr_logs["gov"] = log_path

    tail = daemon._child_stderr_tail("gov")
    assert tail is not None
    assert "�" not in tail
    tail.encode("cp1252")  # the client encoding that raised in the soak

    message = daemon._child_exit_error("gov", suffix="restarting.")
    assert "�" not in message
    message.encode("cp1252")
    assert "CTRL stall: no output for 10s" in message


def test_current_source_label_with_an_accented_title_survives_a_cp1252_write(
    tmp_path: Path,
) -> None:
    """Persistence-boundary regression: an operator-entered title with an
    accent (the common case db_safe_text is meant to PRESERVE, not just avoid
    crashing on) must round-trip through a store that encodes to cp1252 on
    write -- exactly what a WIN1252-encoded Postgres cluster does."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())

    def _cp1252_write_state(row: EgressStateRow) -> None:
        # Simulate the persistence boundary a real WIN1252 psycopg connection
        # enforces: anything not cp1252-encodable raises, exactly like the
        # T6 soak's UnicodeEncodeError.
        if row.current_source_label is not None:
            row.current_source_label.encode("cp1252")
        if row.last_error is not None:
            row.last_error.encode("cp1252")
        InMemoryEgressStore.write_state(store, row)

    store.write_state = _cp1252_write_state  # type: ignore[method-assign]

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan_with_label(
            tmp_path, "Réunion du conseil municipal"
        ),
        ffmpeg_starter=lambda _args: _FakeProcess(),
    )

    daemon.process_once("gov")  # must not raise

    state = store.read_state("gov")
    assert state is not None
    assert state.current_source_label is not None
    # cp1252 CAN represent e-acute -- db_safe_text must not degrade it.
    assert "Réunion" in state.current_source_label


def test_last_error_with_the_unicode_replacement_character_survives_a_cp1252_write(
    tmp_path: Path,
) -> None:
    """last_error=str(exc) (daemon.py's zero-ffmpeg-floor ERROR handler) must
    also survive a WIN1252 write -- U+FFFD is the exact character the T6 soak
    hit, and cp1252 genuinely cannot represent it (unlike an accent), so this
    proves the degrade-not-crash half of db_safe_text's contract."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())

    def _cp1252_write_state(row: EgressStateRow) -> None:
        if row.last_error is not None:
            row.last_error.encode("cp1252")
        InMemoryEgressStore.write_state(store, row)

    store.write_state = _cp1252_write_state  # type: ignore[method-assign]

    class _AlwaysUnavailableWithReplacementChar:
        name = "always-unavailable"
        supports_live_swap = False
        supports_content_reload = False

        def start(self, request: EncoderStartRequest) -> EncoderStartResult:
            from civiccast.egress.errors import EncoderUnavailableError

            # The exact character shape the T6 soak hit: a stray U+FFFD from
            # a child log read with errors="replace".
            raise EncoderUnavailableError("worker stall: no output for 10s � quitting")

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        encoder_strategy=_AlwaysUnavailableWithReplacementChar(),  # type: ignore[arg-type]
    )

    daemon.process_once("gov")  # must not raise

    state = store.read_state("gov")
    assert state is not None
    assert state.state == "ERROR"
    assert state.last_error is not None
    assert "�" not in state.last_error
    state.last_error.encode("cp1252")


def test_proof_event_label_and_summary_survive_a_cp1252_write(tmp_path: Path) -> None:
    """_build_proof_event's source_label/machine_summary go through
    EgressStore.append_proof_event, a SEPARATE write path from
    EgressStore.write_state -- its own persistence-boundary regression."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())

    def _cp1252_append_proof_event(event: Any) -> None:
        event.source_label.encode("cp1252")
        event.machine_summary.encode("cp1252")
        InMemoryEgressStore.append_proof_event(store, event)

    store.append_proof_event = _cp1252_append_proof_event  # type: ignore[method-assign]

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan_with_label(
            tmp_path, "Réunion du conseil municipal"
        ),
        ffmpeg_starter=lambda _args: _FakeProcess(),
    )

    daemon.process_once("gov")  # must not raise

    proof_events = store.recent_proof_events("gov", 1)
    assert proof_events[0].source_label is not None
    assert "Réunion" in proof_events[0].source_label


def test_process_once_isolates_a_poll_failure_from_the_rest_of_the_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The three per-tick polls (_poll_hls_relay, _poll_process,
    _service_backoff_relaunch) must be isolated from each other AND from
    command draining, mirroring the per-command guard immediately below them
    in process_once. Before this fix, one poll raising (e.g. the exact
    UnicodeEncodeError the encoding fix closes, or any other write failure)
    escaped process_once and aborted the WHOLE pass -- pop_pending_commands
    never even ran, so a queued takeover/stop sat unprocessed too."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command())

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        ffmpeg_starter=lambda _args: _FakeProcess(),
    )

    calls: list[str] = []
    real_poll_process = daemon._poll_process
    real_backoff = daemon._service_backoff_relaunch

    def _boom(_channel_id: str) -> None:
        calls.append("hls_relay")
        raise RuntimeError("simulated write failure")

    def _tracked_poll_process(channel_id: str) -> None:
        calls.append("poll_process")
        real_poll_process(channel_id)

    def _tracked_backoff(channel_id: str) -> None:
        calls.append("backoff")
        real_backoff(channel_id)

    monkeypatch.setattr(daemon, "_poll_hls_relay", _boom)
    monkeypatch.setattr(daemon, "_poll_process", _tracked_poll_process)
    monkeypatch.setattr(daemon, "_service_backoff_relaunch", _tracked_backoff)

    # Must not raise, and the queued start command must still be processed.
    processed = daemon.process_once("gov")

    assert calls == ["hls_relay", "poll_process", "backoff"]
    assert processed == 1
    state = store.read_state("gov")
    assert state is not None
    assert state.state == "ON_AIR"
