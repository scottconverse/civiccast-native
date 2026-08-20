# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S8-5 self-test runner tests (spec §6.6)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from civiccast.alerting.models import AlertChannel
from civiccast.alerting.self_test import (
    _SRT_LOOPBACK_SELF_TEST_LATENCY_MS,
    SelfTestCheck,
    SelfTestDeps,
    assemble_available_self_test_checks,
    assemble_self_test_checks,
    channel_delivery_ready,
    default_self_test_availability,
    default_self_test_deps,
    run_self_test,
    srt_continuity_probe,
    tsduck_smoke_probe,
)
from civiccast.alerting.store import get_alert_events, get_self_tests, record_alert_condition
from civiccast.egress.compliance import TsduckStatus


@contextmanager
def _null_session():
    yield None  # get_alert_channels is monkeypatched in these tests


def _channel(handle: str | None, *, enabled: bool = True, cid: str = "ch-1") -> AlertChannel:
    return AlertChannel(
        channel_id=cid,
        kind="email",
        label="x",
        enabled=enabled,
        target_redacted="ops@***",
        credential_handle=handle,
        created_at=_NOW,
    )


_NOW = datetime(2026, 6, 15, 2, 0, 0, tzinfo=UTC)


def _check(name: str, ok: bool, *, required: bool = True) -> SelfTestCheck:
    return SelfTestCheck(name=name, run=lambda: ok, required=required)


def _boom(name: str) -> SelfTestCheck:
    def _raise() -> bool:
        raise RuntimeError("probe blew up")

    return SelfTestCheck(name=name, run=_raise)


class TestRunSelfTest:
    def test_all_pass_records_pass_no_alert(self, db_session: Session) -> None:
        test = run_self_test(
            db_session,
            "daily",
            [_check("readiness", True), _check("filesink_continuity", True)],
            now=_NOW,
        )
        assert test.status == "pass"
        assert test.checks == {"readiness": True, "filesink_continuity": True}
        assert test.finished_at == _NOW
        assert get_alert_events(db_session, state="firing") == []
        # Persisted to history.
        assert len(get_self_tests(db_session, kind="daily")) == 1

    def test_required_failure_is_fail_and_raises_alert(self, db_session: Session) -> None:
        test = run_self_test(
            db_session,
            "daily",
            [_check("readiness", True), _check("backup_probe", False)],
            now=_NOW,
        )
        assert test.status == "fail"
        assert "backup_probe" in test.summary
        firing = get_alert_events(db_session, state="firing")
        assert any(e.condition == "self-test-fail" for e in firing)
        assert firing[0].resource_ref == "self-test:daily"

    def test_advisory_failure_is_warn_and_raises_alert(self, db_session: Session) -> None:
        test = run_self_test(
            db_session,
            "weekly",
            [_check("readiness", True), _check("model_ping", False, required=False)],
            now=_NOW,
        )
        assert test.status == "warn"
        assert any(
            e.condition == "self-test-fail" for e in get_alert_events(db_session, state="firing")
        )

    def test_crashing_check_is_treated_as_failure(self, db_session: Session) -> None:
        test = run_self_test(db_session, "daily", [_boom("srt_continuity")], now=_NOW)
        assert test.status == "fail"
        assert test.checks["srt_continuity"] is False

    def test_clean_run_resolves_prior_failure(self, db_session: Session) -> None:
        run_self_test(db_session, "daily", [_check("backup_probe", False)], now=_NOW)
        assert any(
            e.condition == "self-test-fail" for e in get_alert_events(db_session, state="firing")
        )
        run_self_test(db_session, "daily", [_check("backup_probe", True)], now=_NOW)
        assert not any(
            e.condition == "self-test-fail" for e in get_alert_events(db_session, state="firing")
        )
        assert any(
            e.condition == "self-test-fail" for e in get_alert_events(db_session, state="resolved")
        )

    def test_daily_and_weekly_dedupe_independently(self, db_session: Session) -> None:
        run_self_test(db_session, "daily", [_check("x", False)], now=_NOW)
        run_self_test(db_session, "weekly", [_check("y", False)], now=_NOW)
        refs = {
            e.resource_ref
            for e in get_alert_events(db_session, state="firing")
            if e.condition == "self-test-fail"
        }
        assert refs == {"self-test:daily", "self-test:weekly"}


def _deps(**overrides) -> SelfTestDeps:
    base = {
        name: (lambda: True)
        for name in (
            "readiness",
            "filesink_continuity",
            "backup_probe",
            "model_ping",
            "restore_rehearsal",
            "srt_continuity",
            "tsduck_probe",
            "channel_test_send",
        )
    }
    base.update(overrides)
    return SelfTestDeps(**base)


class TestAssembleSelfTestChecks:
    def test_daily_check_set(self) -> None:
        names = [c.name for c in assemble_self_test_checks("daily", _deps())]
        assert names == ["readiness", "filesink_continuity", "backup_probe", "model_ping"]

    def test_weekly_extends_daily(self) -> None:
        checks = assemble_self_test_checks("weekly", _deps())
        names = [c.name for c in checks]
        assert names[:4] == ["readiness", "filesink_continuity", "backup_probe", "model_ping"]
        assert names[4:] == [
            "restore_rehearsal",
            "srt_continuity",
            "tsduck_probe",
            "channel_test_send",
        ]

    def test_model_ping_and_tsduck_and_test_send_are_advisory(self) -> None:
        by_name = {c.name: c for c in assemble_self_test_checks("weekly", _deps())}
        assert by_name["model_ping"].required is False
        assert by_name["tsduck_probe"].required is False
        assert by_name["channel_test_send"].required is False
        assert by_name["readiness"].required is True
        assert by_name["restore_rehearsal"].required is True

    def test_assembled_checks_run_to_pass_when_all_green(self, db_session: Session) -> None:
        test = run_self_test(
            db_session, "daily", assemble_self_test_checks("daily", _deps()), now=_NOW
        )
        assert test.status == "pass"

    def test_advisory_only_failure_warns_required_failure_fails(self, db_session: Session) -> None:
        warn = run_self_test(
            db_session,
            "weekly",
            assemble_self_test_checks("weekly", _deps(model_ping=lambda: False)),
            now=_NOW,
        )
        assert warn.status == "warn"
        fail = run_self_test(
            db_session,
            "weekly",
            assemble_self_test_checks("weekly", _deps(filesink_continuity=lambda: False)),
            now=_NOW,
        )
        assert fail.status == "fail"


class TestAvailabilityAwareAssembly:
    def test_excludes_unavailable_checks(self) -> None:
        availability = {
            "readiness": True,
            "backup_probe": True,
            "model_ping": True,
            "filesink_continuity": False,
        }
        names = [
            c.name for c in assemble_available_self_test_checks("daily", _deps(), availability)
        ]
        assert "filesink_continuity" not in names  # tooling absent -> honest not-run
        assert "readiness" in names and "backup_probe" in names

    def test_absent_from_map_defaults_included(self) -> None:
        # An empty availability map includes everything (the light probes).
        names = [c.name for c in assemble_available_self_test_checks("daily", _deps(), {})]
        assert names == ["readiness", "filesink_continuity", "backup_probe", "model_ping"]


class TestDefaultSelfTestDeps:
    def test_default_availability_light_on_no_heavy_tooling(self, monkeypatch) -> None:
        import civiccast.alerting.self_test as st

        # Force a box with no heavy tooling: no ffmpeg, no backup, no TSDuck.
        monkeypatch.setattr(st, "_ffmpeg_present", lambda: False)
        monkeypatch.setattr(st, "_backup_ok", lambda: False)
        monkeypatch.setattr(
            "civiccast.egress.compliance.locate_tsduck",
            lambda **_k: TsduckStatus(installed=False),
        )
        avail = default_self_test_availability()
        assert avail["readiness"] and avail["backup_probe"] and avail["model_ping"]
        for heavy in (
            "filesink_continuity",
            "restore_rehearsal",
            "srt_continuity",
            "tsduck_probe",
            "channel_test_send",
        ):
            assert avail[heavy] is False

    def test_tsduck_availability_present_when_tsp_and_ffmpeg(self, monkeypatch) -> None:
        import civiccast.alerting.self_test as st

        monkeypatch.setattr(st, "_ffmpeg_present", lambda: True)
        monkeypatch.setattr(
            "civiccast.egress.compliance.locate_tsduck",
            lambda **_k: TsduckStatus(installed=True, path="X/tsp.exe", version="3.44-4676"),
        )
        assert default_self_test_availability()["tsduck_probe"] is True

    def test_default_run_excludes_heavy_and_runs_light(
        self, db_session: Session, monkeypatch
    ) -> None:
        import civiccast.alerting.self_test as st

        monkeypatch.setattr(st, "_readiness_ok", lambda: True)
        monkeypatch.setattr(st, "_backup_ok", lambda: True)
        monkeypatch.setattr(st, "_model_ping", lambda: True)
        # Force a no-heavy-tooling environment so the run is deterministic and never
        # spawns a real ffmpeg encode or restore rehearsal in the unit test.
        monkeypatch.setattr(st, "_ffmpeg_present", lambda: False)
        monkeypatch.setattr(
            st,
            "default_self_test_availability",
            lambda: {
                "readiness": True,
                "backup_probe": True,
                "model_ping": True,
                "filesink_continuity": False,
                "restore_rehearsal": False,
                "srt_continuity": False,
                "tsduck_probe": False,
                "channel_test_send": False,
            },
        )
        deps = default_self_test_deps()  # captures the patched light probes via module globals
        checks = assemble_available_self_test_checks(
            "weekly", deps, st.default_self_test_availability()
        )
        # Only the three light probes survive — the heavy proofs are excluded (so they
        # are never invoked and can never raise or spawn ffmpeg).
        assert [c.name for c in checks] == ["readiness", "backup_probe", "model_ping"]
        result = run_self_test(db_session, "weekly", checks, now=_NOW)
        assert result.status == "pass"

    def test_not_wired_probe_raises_if_invoked(self) -> None:
        import pytest as _pytest

        from civiccast.alerting.self_test import _not_wired

        with _pytest.raises(NotImplementedError):
            _not_wired("filesink_continuity")()


class TestTsduckSmokeProbe:
    """The weekly TSDuck smoke — injected fakes, no real ffmpeg/tsp."""

    def test_returns_false_when_tsduck_not_installed(self) -> None:
        calls = {"clip": 0, "tsp": 0}

        def gen(wd, _r):
            calls["clip"] += 1
            return wd / "c.ts"

        def tsp(_args):
            calls["tsp"] += 1
            return 0

        assert (
            tsduck_smoke_probe(
                locator=lambda: TsduckStatus(installed=False),
                clip_generator=gen,
                tsp_runner=tsp,
            )
            is False
        )
        assert calls == {"clip": 0, "tsp": 0}  # never touched ffmpeg/tsp

    def test_passes_when_tsp_analyze_exits_zero(self, tmp_path) -> None:
        seen: list[list[str]] = []
        ok = tsduck_smoke_probe(
            work_dir=tmp_path,
            locator=lambda: TsduckStatus(installed=True, path="tsp", version="3.44"),
            ffmpeg_runner=lambda _args: None,
            clip_generator=lambda wd, _r: wd / "clip.ts",
            tsp_runner=lambda args: seen.append(args) or 0,
        )
        assert ok is True
        # We smoke the real analyze plugin (what cable compliance relies on).
        assert seen and seen[0][0] == "tsp" and "analyze" in seen[0]

    def test_fails_when_tsp_exits_nonzero(self, tmp_path) -> None:
        assert (
            tsduck_smoke_probe(
                work_dir=tmp_path,
                locator=lambda: TsduckStatus(installed=True, path="tsp", version="3.44"),
                ffmpeg_runner=lambda _args: None,
                clip_generator=lambda wd, _r: wd / "clip.ts",
                tsp_runner=lambda _args: 1,
            )
            is False
        )

    def test_clip_failure_is_false_not_raise(self, tmp_path) -> None:
        def gen_boom(_wd, _r):
            raise OSError("ffmpeg gone")

        assert (
            tsduck_smoke_probe(
                work_dir=tmp_path,
                locator=lambda: TsduckStatus(installed=True, path="tsp", version="3.44"),
                clip_generator=gen_boom,
                tsp_runner=lambda _args: 0,
            )
            is False
        )


class TestSrtContinuityProbe:
    """The weekly SRT receiver continuity proof — injected proof_runner so the
    orchestration unit-tests without ffmpeg/SRT."""

    def test_passes_when_proof_passes(self, tmp_path) -> None:
        from types import SimpleNamespace

        seen: dict = {}

        def fake_proof(**kwargs):
            seen.update(kwargs)
            return SimpleNamespace(status="PASS")

        ok = srt_continuity_probe(
            work_dir=tmp_path,
            port=19999,
            clip_generator=lambda wd, _r: wd / "c.ts",
            ffmpeg_runner=lambda _a: None,
            proof_runner=fake_proof,
        )
        assert ok is True
        assert seen["sender_url"] == "srt://127.0.0.1:19999"
        assert "mode=listener" in seen["receiver_url"]
        assert seen["config"].sinks[0].latency_ms == _SRT_LOOPBACK_SELF_TEST_LATENCY_MS
        # Two segments of the same clip exercise a real concat boundary.
        assert len(seen["source_plan"].segments) == 2

    def test_fails_when_proof_not_pass(self, tmp_path) -> None:
        from types import SimpleNamespace

        assert (
            srt_continuity_probe(
                work_dir=tmp_path,
                port=19999,
                clip_generator=lambda wd, _r: wd / "c.ts",
                ffmpeg_runner=lambda _a: None,
                proof_runner=lambda **_k: SimpleNamespace(status="NEEDS_ATTENTION"),
            )
            is False
        )

    def test_clip_failure_is_false_not_raise(self, tmp_path) -> None:
        from types import SimpleNamespace

        def gen_boom(_wd, _r):
            raise OSError("no ffmpeg")

        assert (
            srt_continuity_probe(
                work_dir=tmp_path,
                port=19999,
                clip_generator=gen_boom,
                proof_runner=lambda **_k: SimpleNamespace(status="PASS"),
            )
            is False
        )

    def test_availability_gated_on_ffmpeg_srt(self, monkeypatch) -> None:
        import civiccast.alerting.self_test as st

        monkeypatch.setattr(st, "_ffmpeg_present", lambda: True)
        monkeypatch.setattr(st, "_ffmpeg_has_srt", lambda: True)
        monkeypatch.setattr(
            "civiccast.egress.compliance.locate_tsduck",
            lambda **_k: TsduckStatus(installed=False),
        )
        assert default_self_test_availability()["srt_continuity"] is True
        monkeypatch.setattr(st, "_ffmpeg_has_srt", lambda: False)
        assert default_self_test_availability()["srt_continuity"] is False


class TestChannelDeliveryReady:
    """The weekly delivery-readiness check — a config/credential check, never a
    live send (no weekly spam/cost). get_alert_channels is monkeypatched so the
    logic tests without a DB."""

    def test_ready_when_an_enabled_channel_resolves(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "civiccast.alerting.store.get_alert_channels", lambda _s: [_channel("h1")]
        )
        assert (
            channel_delivery_ready(_null_session, lambda h: {"pw": "x"} if h == "h1" else None)
            is True
        )

    def test_not_ready_when_secret_missing(self, monkeypatch) -> None:
        # Enabled channel declares a handle that does NOT resolve -> alerts can't deliver.
        monkeypatch.setattr(
            "civiccast.alerting.store.get_alert_channels", lambda _s: [_channel("gone")]
        )
        assert channel_delivery_ready(_null_session, lambda _h: None) is False

    def test_ready_when_channel_needs_no_secret(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "civiccast.alerting.store.get_alert_channels", lambda _s: [_channel(None)]
        )
        assert channel_delivery_ready(_null_session, lambda _h: None) is True

    def test_not_ready_when_no_enabled_channels(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "civiccast.alerting.store.get_alert_channels",
            lambda _s: [_channel("h1", enabled=False)],
        )
        assert channel_delivery_ready(_null_session, lambda _h: {"pw": "x"}) is False

    def test_ready_when_any_enabled_channel_resolves(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "civiccast.alerting.store.get_alert_channels",
            lambda _s: [_channel("gone", cid="a"), _channel("h2", cid="b")],
        )
        assert (
            channel_delivery_ready(_null_session, lambda h: {"pw": "x"} if h == "h2" else None)
            is True
        )

    def test_availability_and_dep_wired_with_session(self, monkeypatch) -> None:
        import civiccast.alerting.self_test as st

        # Keep the rest of availability fast/deterministic.
        monkeypatch.setattr(st, "_ffmpeg_present", lambda: False)
        monkeypatch.setattr(st, "_backup_ok", lambda: False)
        monkeypatch.setattr(
            "civiccast.egress.compliance.locate_tsduck", lambda **_k: TsduckStatus(installed=False)
        )
        monkeypatch.setattr(
            "civiccast.alerting.store.get_alert_channels", lambda _s: [_channel("h1")]
        )
        avail = default_self_test_availability(session_factory=_null_session)
        assert avail["channel_test_send"] is True
        # No session factory -> not-run; and the zero-arg dep stays not-wired.
        assert default_self_test_availability()["channel_test_send"] is False

        deps = default_self_test_deps(
            session_factory=_null_session, credential_reader=lambda _h: {"pw": "x"}
        )
        assert deps.channel_test_send() is True  # real readiness check, not a raise

    def test_zero_arg_dep_is_not_wired(self) -> None:
        import pytest as _pytest

        with _pytest.raises(NotImplementedError):
            default_self_test_deps().channel_test_send()


class TestFilesinkContinuityProbe:
    """The daily FileSink continuity proof — tested with injected fakes (no real
    ffmpeg/media), mirroring tests/egress/test_continuity.py's fake runner."""

    def _fakes(self, monkeypatch, *, loudness_ok: bool = True):
        from civiccast.stream._ffmpeg import FfmpegResult
        from civiccast.stream.loudness import LoudnessGateResult

        monkeypatch.setattr("civiccast.egress.continuity.probe_duration", lambda _p: 4.0)
        monkeypatch.setattr(
            "civiccast.egress.continuity.check_streaming_loudness",
            lambda **_k: LoudnessGateResult(
                status="ok" if loudness_ok else "out_of_tolerance",
                standard="ITU-R BS.1770 / EBU R128",
                target_lufs=-16.0,
                used_ffmpeg_wrapper=True,
                measured_lufs=-16.2 if loudness_ok else -6.0,
                operator_action="x",
            ),
        )

        def fake_runner(args):
            # The proof's encode writes the file the args name as output.
            out = args[-1]
            from pathlib import Path as _P

            _P(out).parent.mkdir(parents=True, exist_ok=True)
            _P(out).write_bytes(b"transport stream")
            return FfmpegResult(returncode=0, stdout="", stderr="")

        def fake_clip(work_dir, _runner):
            from pathlib import Path as _P

            work_dir.mkdir(parents=True, exist_ok=True)
            clip = _P(work_dir) / "clip.ts"
            clip.write_bytes(b"clip")
            return clip

        return fake_runner, fake_clip

    def test_passes_with_clean_encode(self, tmp_path, monkeypatch) -> None:
        from civiccast.alerting.self_test import filesink_continuity_probe

        runner, clip = self._fakes(monkeypatch, loudness_ok=True)
        assert (
            filesink_continuity_probe(work_dir=tmp_path, ffmpeg_runner=runner, clip_generator=clip)
            is True
        )

    def test_fails_on_bad_loudness(self, tmp_path, monkeypatch) -> None:
        from civiccast.alerting.self_test import filesink_continuity_probe

        runner, clip = self._fakes(monkeypatch, loudness_ok=False)
        assert (
            filesink_continuity_probe(work_dir=tmp_path, ffmpeg_runner=runner, clip_generator=clip)
            is False
        )

    def test_ffmpeg_crash_is_false_not_raise(self, tmp_path) -> None:
        from civiccast.alerting.self_test import filesink_continuity_probe

        def boom(_args):
            raise RuntimeError("ffmpeg blew up")

        assert (
            filesink_continuity_probe(
                work_dir=tmp_path,
                ffmpeg_runner=boom,
                clip_generator=lambda wd, r: tmp_path / "x.ts",
            )
            is False
        )

    def test_availability_tracks_ffmpeg_presence(self, monkeypatch) -> None:
        import civiccast.alerting.self_test as st

        monkeypatch.setattr(st, "_ffmpeg_present", lambda: True)
        assert default_self_test_availability()["filesink_continuity"] is True
        monkeypatch.setattr(st, "_ffmpeg_present", lambda: False)
        assert default_self_test_availability()["filesink_continuity"] is False


class TestRestoreRehearsalProbe:
    def test_passed_status_is_true(self, monkeypatch) -> None:
        import civiccast.alerting.self_test as st
        from civiccast.installer.models import RestoreStatus

        def fake() -> RestoreStatus:
            from datetime import UTC as _UTC
            from datetime import datetime as _dt

            return RestoreStatus(
                generated_at=_dt(2026, 6, 15, tzinfo=_UTC),
                status="passed",
                proof_items=[],
                excluded_items=[],
                plan_steps=[],
                message="ok",
                next_step="x",
            )

        monkeypatch.setattr("civiccast.installer.service.run_restore_rehearsal", fake)
        assert st._restore_rehearsal_ok() is True

    def test_needs_attention_status_is_false(self, monkeypatch) -> None:
        import civiccast.alerting.self_test as st
        from civiccast.installer.models import RestoreStatus

        def fake() -> RestoreStatus:
            from datetime import UTC as _UTC
            from datetime import datetime as _dt

            return RestoreStatus(
                generated_at=_dt(2026, 6, 15, tzinfo=_UTC),
                status="needs_attention",
                proof_items=[],
                excluded_items=[],
                plan_steps=[],
                message="blocked",
                next_step="x",
            )

        monkeypatch.setattr("civiccast.installer.service.run_restore_rehearsal", fake)
        assert st._restore_rehearsal_ok() is False

    def test_crash_is_false(self, monkeypatch) -> None:
        import civiccast.alerting.self_test as st

        def boom() -> object:
            raise RuntimeError("backup volume gone")

        monkeypatch.setattr("civiccast.installer.service.run_restore_rehearsal", boom)
        assert st._restore_rehearsal_ok() is False

    def test_availability_gated_on_backup_ready(self, monkeypatch) -> None:
        import civiccast.alerting.self_test as st

        monkeypatch.setattr(st, "_backup_ok", lambda: True)
        monkeypatch.setattr(st, "_ffmpeg_present", lambda: False)
        assert default_self_test_availability()["restore_rehearsal"] is True
        monkeypatch.setattr(st, "_backup_ok", lambda: False)
        assert default_self_test_availability()["restore_rehearsal"] is False


class TestResolveBeyondRecencyWindow:
    """M2: a clean run resolves a firing self-test-fail via the indexed exact
    lookup, even when it is older than the 200-row get_alert_events window."""

    def test_clean_run_resolves_stale_self_test_fail_past_200_window(
        self, db_session: Session
    ) -> None:
        base = _NOW
        # 1) Fire a self-test-fail (oldest firing event).
        run_self_test(db_session, "daily", [_check("readiness", False)], now=base)
        # 2) 205 newer, unrelated firing events push it out of the 200-row window.
        for i in range(205):
            record_alert_condition(
                db_session,
                kind="off-air",
                resource_ref=f"ch-{i}",
                source_section="S8",
                summary="off air",
                observed_at=base + timedelta(seconds=i + 1),
            )
        # 3) A clean run must still resolve the (now-stale) self-test-fail.
        run_self_test(
            db_session, "daily", [_check("readiness", True)], now=base + timedelta(seconds=1000)
        )
        firing = get_alert_events(db_session, state="firing", limit=1000)
        assert not any(e.condition == "self-test-fail" for e in firing)

    def test_clean_run_with_no_prior_failure_writes_no_resolved_row(
        self, db_session: Session
    ) -> None:
        # Guard: a clean run when nothing was firing must NOT create a spurious
        # pre-resolved self-test-fail audit row.
        run_self_test(db_session, "daily", [_check("readiness", True)], now=_NOW)
        events = get_alert_events(db_session, limit=1000)
        assert not any(e.condition == "self-test-fail" for e in events)


class TestDefaultDepsAndAvailabilityResolution:
    def test_default_deps_tsduck_lambda_resolves_when_absent(self, monkeypatch) -> None:
        # The zero-arg lambda default_self_test_deps wires must resolve its default
        # imports (locate_tsduck etc.) and return False when TSDuck is absent —
        # proving the production wiring path, not just the injected-seam tests.
        monkeypatch.setattr(
            "civiccast.egress.compliance.locate_tsduck", lambda **_k: TsduckStatus(installed=False)
        )
        assert default_self_test_deps().tsduck_probe() is False

    def test_tsduck_smoke_timeout_is_false(self, tmp_path) -> None:
        import subprocess

        def boom(_args):
            raise subprocess.TimeoutExpired(cmd="tsp", timeout=30)

        assert (
            tsduck_smoke_probe(
                work_dir=tmp_path,
                locator=lambda: TsduckStatus(installed=True, path="tsp", version="3.44"),
                ffmpeg_runner=lambda _a: None,
                clip_generator=lambda wd, _r: wd / "c.ts",
                tsp_runner=boom,
            )
            is False
        )

    def test_channel_availability_db_error_is_false(self, monkeypatch) -> None:
        def boom(_session):
            raise RuntimeError("db down")

        monkeypatch.setattr("civiccast.alerting.store.get_alert_channels", boom)
        assert (
            default_self_test_availability(session_factory=_null_session)["channel_test_send"]
            is False
        )
