# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

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
    ) -> None:
        self._processes = processes
        self._started = started
        self._reload_ok = reload_ok
        self._reload_exc = reload_exc
        self.reload_calls: list[str] = []

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

    def reload_content(self, channel_id: str, work_dir: Path, request: EncoderStartRequest) -> bool:
        self.reload_calls.append(request.source_plan.segments[0].label)
        if self._reload_exc is not None:
            raise self._reload_exc
        return self._reload_ok


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

    def reload_content(self, channel_id: str, work_dir: Path, request: EncoderStartRequest) -> bool:
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
        self, channel_id: str, work_dir: Path, request: EncoderStartRequest
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
