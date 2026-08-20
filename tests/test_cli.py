# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""CLI smoke tests via Typer's CliRunner."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

import civiccast.cli as cli_module
from civiccast._version import __version__
from civiccast.auth.store import InMemoryStaffTokenStore
from civiccast.cli import app


def test_version_flag() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_help_runs() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "CivicCast" in result.stdout


def test_doctor_human_output() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "hardware probe" in result.stdout
    assert "Recommended deployment tier:" in result.stdout
    # Must always render one of the four tier values.
    assert any(tier in result.stdout for tier in ("tier-0", "tier-1", "tier-1-plus", "tier-2"))


def test_doctor_json_output_is_valid_json() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert "cpu" in payload
    assert "ram" in payload
    assert "disk" in payload
    assert "os" in payload
    assert "recommended_tier" in payload
    assert payload["civiccast_version"] == __version__


def test_doctor_with_explicit_disk_path(tmp_path: object) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["doctor", "--json", "--disk", str(tmp_path)])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["disk"]["path"] == str(tmp_path)


def test_installer_plan_json() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["installer", "plan", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["profile"] == "public-meetings"
    assert payload["cloud_fallback_default"] == "off"
    assert any(step["id"] == "publish-targets" for step in payload["steps"])


def test_installer_health_check_reports_not_ready_with_next_steps() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["installer", "health-check"])

    assert result.exit_code == 0
    assert "CivicCast first-run health: NOT READY" in result.stdout
    assert "CIVICCAST_INTERNET_ARCHIVE_ACCESS_KEY" in result.stdout


def test_installer_health_check_stays_not_ready_with_placeholder_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CIVICCAST_PORTAL_TOKEN", "placeholder-token")
    monkeypatch.setenv("CIVICCAST_INTERNET_ARCHIVE_ACCESS_KEY", "placeholder-ia-key")
    monkeypatch.setenv("CIVICCAST_YOUTUBE_CLIENT_SECRET", "placeholder-youtube-secret")
    monkeypatch.setenv("CIVICCAST_NAS_ARCHIVE_PATH", "Z:/definitely-not-present-civiccast")
    monkeypatch.setenv("CIVICCAST_SUBSCRIBER_WEBHOOK_SECRET", "placeholder-webhook-secret")
    runner = CliRunner()

    result = runner.invoke(app, ["installer", "health-check"])

    assert result.exit_code == 0
    assert "CivicCast first-run health: NOT READY" in result.stdout
    assert "You are streaming." not in result.stdout
    assert "Local NAS: failed" in result.stdout
    assert "Resident portal: credential_or_secret_required" in result.stdout


def test_model_download_offline_bundle_requires_real_bundle_dir() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["model", "download", "--offline-bundle", "--json"])

    assert result.exit_code != 0
    assert "required with" in result.output
    assert "offline model artifacts" in result.output


def test_model_download_offline_bundle_json(tmp_path: Path) -> None:
    model_payloads = {
        "whisper-large-v3.tar.zst": b"whisper model bytes",
        "gemma4-12b.tar.zst": b"summary 12b model bytes",
        "gemma4-e4b.tar.zst": b"summary model bytes",
        "translategemma-4b.tar.zst": b"translation model bytes",
    }
    for filename, payload in model_payloads.items():
        (tmp_path / filename).write_bytes(payload)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "model",
            "download",
            "--offline-bundle",
            "--bundle-dir",
            str(tmp_path),
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["bundle_name"] == f"civiccast-models-public-meetings-v{__version__}.tar"
    assert payload["bundle_dir"] == str(tmp_path)
    # Bundle ships BOTH summary tags so the adaptive 12B/e4b default is present
    # offline regardless of detected RAM (S13 E2/T2/Q1).
    assert {item["id"] for item in payload["items"]} == {
        "whisper-large-v3",
        "gemma4:12b",
        "gemma4:e4b",
        "translategemma:4b",
    }
    assert {item["filename"] for item in payload["items"]} == set(model_payloads)
    assert all(item["sha256"] not in {"1" * 64, "2" * 64, "3" * 64} for item in payload["items"])


def test_model_download_online_dry_run_json() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["model", "download", "--dry-run", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "planned"
    # The online pull provisions BOTH summary tags so the adaptive 12B/e4b default is
    # present on first run regardless of detected RAM (S13 E2/T2/Q1). It also
    # provisions BOTH caption tiers unconditionally: large-v3 (quality, optional) and
    # the mandatory CPU-only floor tier (medium, OWNER-DECISION-caption-adaptive-tier.md,
    # 2026-07-30) so a station is never missing its caption baseline.
    assert {item["id"] for item in payload["items"]} == {
        "faster-whisper-large-v3",
        "faster-whisper-medium",
        "gemma4-12b",
        "gemma4-e4b",
        "translategemma-4b",
    }


def test_egress_run_once_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class _Report:
        channel_ids = ("council",)
        iterations = 1
        commands_processed = 0
        stopped_by = "max_iterations"
        last_iteration_at = None

    captured: dict[str, object] = {}

    def _fake_run_egress_service(**kwargs: object) -> _Report:
        captured.update(kwargs)
        return _Report()

    monkeypatch.setattr(cli_module, "_run_egress_service", _fake_run_egress_service)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "egress",
            "run",
            "--channel-id",
            "council",
            "--work-dir",
            str(tmp_path),
            "--once",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["channel_ids"] == ["council"]
    assert payload["iterations"] == 1
    assert payload["commands_processed"] == 0
    assert payload["stopped_by"] == "max_iterations"
    assert payload["work_dir"] == str(tmp_path.resolve())
    assert captured == {
        "channel_ids": ("council",),
        "work_dir": tmp_path.resolve(),
        "poll_seconds": 2.0,
        "once": True,
    }


def test_egress_trim_health_json(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, datetime] = {}

    def _fake_trim_egress_health(*, cutoff: datetime) -> int:
        captured["cutoff"] = cutoff
        return 7

    monkeypatch.setattr(cli_module, "_trim_egress_health", _fake_trim_egress_health)
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["egress", "trim-health", "--older-than-days", "14", "--json"],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["older_than_days"] == 14
    assert payload["deleted_count"] == 7
    assert payload["dry_run"] is False
    assert captured["cutoff"].tzinfo is not None


def test_egress_trim_health_dry_run_does_not_touch_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_module,
        "_trim_egress_health",
        lambda **_kwargs: pytest.fail("dry-run must not delete telemetry"),
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["egress", "trim-health", "--older-than-days", "14", "--dry-run", "--json"],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["older_than_days"] == 14
    assert payload["deleted_count"] is None
    assert payload["dry_run"] is True


def test_egress_runner_wires_schedule_source_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import civiccast.egress as egress_module

    class _Report:
        channel_ids = ("council",)
        iterations = 1
        commands_processed = 0
        stopped_by = "max_iterations"
        last_iteration_at = None

    class _FakeDaemon:
        def __init__(self, store: object, **kwargs: object) -> None:
            captured["store"] = store
            captured.update(kwargs)

    class _FakeService:
        def __init__(self, daemon: object, **kwargs: object) -> None:
            captured["daemon"] = daemon
            captured.update(kwargs)

        def run(self, **kwargs: object) -> _Report:
            captured["run"] = kwargs
            return _Report()

    import civiccast.egress.bulletin_filler as bulletin_filler_module

    captured: dict[str, object] = {}
    source_provider = object()
    store = object()
    monkeypatch.setattr(cli_module, "_resolve_egress_database_url", lambda: "sqlite:///test.db")
    monkeypatch.setattr(cli_module, "_bind_egress_database", lambda _database_url: None)
    monkeypatch.setattr(cli_module, "_build_egress_store", lambda: store)
    monkeypatch.setattr(cli_module, "_build_egress_source_plan_provider", lambda: source_provider)
    monkeypatch.setattr(cli_module, "_build_cli_session_factory", lambda: "session-factory")
    monkeypatch.setattr(egress_module, "EgressDaemon", _FakeDaemon)
    monkeypatch.setattr(egress_module, "EgressService", _FakeService)
    # CA-3: the CLI fallback is the per-channel fill-policy provider
    # (bulletins or slate), built from the same session factory.
    monkeypatch.setattr(
        bulletin_filler_module,
        "build_filler_source_provider",
        lambda session_factory, *, work_dir: f"filler:{session_factory}",
    )
    monkeypatch.setattr(
        egress_module,
        "SourcePreparer",
        lambda work_dir: type("_FakePreparer", (), {"prepare": "prepare"})(),
    )

    report = cli_module._run_egress_service(
        channel_ids=("council",),
        work_dir=tmp_path,
        poll_seconds=0.1,
        once=True,
    )

    assert report.channel_ids == ("council",)
    assert captured["store"] is store
    assert captured["source_plan_provider"] is source_provider
    assert captured["fallback_source_provider"] == "filler:session-factory"
    assert captured["source_preparer"] == "prepare"
    assert captured["channel_ids"] == ("council",)
    assert captured["poll_seconds"] == 0.1
    assert captured["should_stop"] is None
    assert captured["run"] == {"max_iterations": 1}


def test_egress_runner_wires_stop_predicate_for_continuous_runs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import civiccast.egress as egress_module

    class _Report:
        channel_ids = ("council",)
        iterations = 0
        commands_processed = 0
        stopped_by = "stop_predicate"
        last_iteration_at = None

    class _FakeDaemon:
        def __init__(self, _store: object, **_kwargs: object) -> None:
            pass

    class _FakeService:
        def __init__(self, _daemon: object, **kwargs: object) -> None:
            captured.update(kwargs)

        def run(self, **kwargs: object) -> _Report:
            captured["run"] = kwargs
            return _Report()

    captured: dict[str, object] = {}
    monkeypatch.setattr(cli_module, "_resolve_egress_database_url", lambda: "sqlite:///test.db")
    monkeypatch.setattr(cli_module, "_bind_egress_database", lambda _database_url: None)
    monkeypatch.setattr(cli_module, "_build_egress_store", lambda: object())
    monkeypatch.setattr(cli_module, "_build_egress_source_plan_provider", lambda: object())
    monkeypatch.setattr(egress_module, "EgressDaemon", _FakeDaemon)
    monkeypatch.setattr(egress_module, "EgressService", _FakeService)
    monkeypatch.setattr(egress_module, "SlateSourceGenerator", lambda work_dir: object())
    monkeypatch.setattr(
        egress_module,
        "SourcePreparer",
        lambda work_dir: type("_FakePreparer", (), {"prepare": object()})(),
    )

    report = cli_module._run_egress_service(
        channel_ids=("council",),
        work_dir=tmp_path,
        poll_seconds=0.1,
        once=False,
    )

    assert report.stopped_by == "stop_predicate"
    assert captured["channel_ids"] == ("council",)
    assert captured["poll_seconds"] == 0.1
    assert callable(captured["should_stop"])
    assert captured["should_stop"]() is False
    assert captured["run"] == {"max_iterations": None}


def test_egress_continuity_proof_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import civiccast.egress as egress_module

    config_path = tmp_path / "config.json"
    source_plan_path = tmp_path / "source-plan.json"
    output_path = tmp_path / "proof.ts"
    config_path.write_text(
        json.dumps(
            {
                "channel_id": "gov",
                "enabled": True,
                "sinks": [{"kind": "srt", "label": "Headend", "uri": "srt://127.0.0.1:19001"}],
                "loudness_target_lufs": -16.0,
                "loudness_tolerance_lufs": 2.0,
                "slate_message": "Local government programming will resume shortly.",
            }
        ),
        encoding="utf-8",
    )
    source_plan_path.write_text(
        json.dumps(
            {
                "channel_id": "gov",
                "segments": [
                    {
                        "label": "Program 1",
                        "path": str(tmp_path / "program-1.ts"),
                        "duration_seconds": 2.0,
                    },
                    {
                        "label": "Program 2",
                        "path": str(tmp_path / "program-2.ts"),
                        "duration_seconds": 2.0,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    def fake_proof(**kwargs: object) -> egress_module.EgressContinuityProof:
        captured.update(kwargs)
        return egress_module.EgressContinuityProof(
            status="PASS",
            channel_id="gov",
            proof_boundary=egress_module.CONTINUITY_PROOF_BOUNDARY,
            boundary_count=1,
            expected_duration_seconds=4.0,
            measured_duration_seconds=4.0,
            duration_within_tolerance=True,
            loudness_status="ok",
            loudness_target_lufs=-16.0,
            loudness_tolerance_lufs=2.0,
            measured_lufs=-16.1,
            ffmpeg_returncode=0,
            output_path=str(output_path),
            concat_plan_path=str(tmp_path / "work" / "gov" / "continuity-proof.ffconcat"),
            boundary_events=(),
            canonical_profile={},
            blocker=None,
            next_step="Continue.",
        )

    monkeypatch.setattr(egress_module, "run_filesink_continuity_proof", fake_proof)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "egress",
            "continuity-proof",
            "--source-plan-json",
            str(source_plan_path),
            "--config-json",
            str(config_path),
            "--output-path",
            str(output_path),
            "--work-dir",
            str(tmp_path / "work"),
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "PASS"
    assert payload["proof_boundary"] == egress_module.CONTINUITY_PROOF_BOUNDARY
    assert captured["output_path"] == output_path.resolve()


def test_egress_srt_continuity_proof_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import civiccast.egress as egress_module

    config_path = tmp_path / "config.json"
    source_plan_path = tmp_path / "source-plan.json"
    receiver_output_path = tmp_path / "receiver.ts"
    config_path.write_text(
        json.dumps(
            {
                "channel_id": "gov",
                "enabled": True,
                "sinks": [{"kind": "srt", "label": "Headend", "uri": "srt://127.0.0.1:19001"}],
                "loudness_target_lufs": -16.0,
                "loudness_tolerance_lufs": 2.0,
                "slate_message": "Local government programming will resume shortly.",
            }
        ),
        encoding="utf-8",
    )
    source_plan_path.write_text(
        json.dumps(
            {
                "channel_id": "gov",
                "segments": [
                    {
                        "label": "Program 1",
                        "path": str(tmp_path / "program-1.ts"),
                        "duration_seconds": 2.0,
                    },
                    {
                        "label": "Program 2",
                        "path": str(tmp_path / "program-2.ts"),
                        "duration_seconds": 2.0,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    def fake_proof(**kwargs: object) -> egress_module.EgressContinuityProof:
        captured.update(kwargs)
        return egress_module.EgressContinuityProof(
            status="PASS",
            sink_kind="srt",
            channel_id="gov",
            proof_boundary=egress_module.CONTINUITY_PROOF_BOUNDARY,
            boundary_count=1,
            expected_duration_seconds=4.0,
            measured_duration_seconds=4.0,
            duration_within_tolerance=True,
            loudness_status="ok",
            loudness_target_lufs=-16.0,
            loudness_tolerance_lufs=2.0,
            measured_lufs=-16.1,
            ffmpeg_returncode=0,
            output_path="srt://127.0.0.1:19001",
            receiver_returncode=0,
            receiver_output_path=str(receiver_output_path),
            concat_plan_path=str(tmp_path / "work" / "gov" / "srt-continuity-proof.ffconcat"),
            boundary_events=(),
            canonical_profile={},
            blocker=None,
            next_step="Continue.",
        )

    monkeypatch.setattr(egress_module, "run_srt_receiver_continuity_proof", fake_proof)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "egress",
            "srt-continuity-proof",
            "--source-plan-json",
            str(source_plan_path),
            "--config-json",
            str(config_path),
            "--sender-url",
            "srt://127.0.0.1:19001",
            "--receiver-url",
            "srt://127.0.0.1:19001?mode=listener",
            "--receiver-output-path",
            str(receiver_output_path),
            "--work-dir",
            str(tmp_path / "work"),
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "PASS"
    assert payload["sink_kind"] == "srt"
    assert captured["sender_url"] == "srt://127.0.0.1:19001"
    assert captured["receiver_output_path"] == receiver_output_path.resolve()


def test_egress_caption_decode_proof_json_writes_evidence(tmp_path: Path) -> None:
    emitted_stream_path = tmp_path / "egress.ts"
    expected_path = tmp_path / "expected.vtt"
    decoded_path = tmp_path / "decoded.vtt"
    evidence_path = tmp_path / "evidence" / "caption-proof.json"
    emitted_stream_path.write_bytes(b"fake-ts")
    expected_path.write_text(
        """WEBVTT

cue-1
00:00:01.000 --> 00:00:02.000
Motion carries.
""",
        encoding="utf-8",
    )
    decoded_path.write_text(
        """WEBVTT

decoded-1
00:00:01.100 --> 00:00:02.100
 motion   carries.
""",
        encoding="utf-8",
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "egress",
            "caption-decode-proof",
            "--channel-id",
            "gov",
            "--emitted-stream",
            str(emitted_stream_path),
            "--expected-captions",
            str(expected_path),
            "--decoded-captions",
            str(decoded_path),
            "--decoder-name",
            "ffmpeg-cc-decode",
            "--output-path",
            str(evidence_path),
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"
    assert payload["caption_status"] == "on"
    assert payload["matched_cue_count"] == 1
    assert payload == evidence


def test_egress_caption_decode_proof_fails_on_mismatch(tmp_path: Path) -> None:
    emitted_stream_path = tmp_path / "egress.ts"
    expected_path = tmp_path / "expected.vtt"
    decoded_path = tmp_path / "decoded.vtt"
    emitted_stream_path.write_bytes(b"fake-ts")
    expected_path.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nMotion carries.\n",
        encoding="utf-8",
    )
    decoded_path.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nDifferent caption.\n",
        encoding="utf-8",
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "egress",
            "caption-decode-proof",
            "--channel-id",
            "gov",
            "--emitted-stream",
            str(emitted_stream_path),
            "--expected-captions",
            str(expected_path),
            "--decoded-captions",
            str(decoded_path),
        ],
    )

    assert result.exit_code == 1
    assert "Egress caption decode-back proof: FAIL" in result.stdout
    assert "Blocker: EGRESS_CAPTION_DECODE_BACK_MISMATCH" in result.stdout


def test_egress_caption_decode_proof_requires_real_emitted_stream(tmp_path: Path) -> None:
    expected_path = tmp_path / "expected.vtt"
    decoded_path = tmp_path / "decoded.vtt"
    expected_path.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nMotion carries.\n",
        encoding="utf-8",
    )
    decoded_path.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nMotion carries.\n",
        encoding="utf-8",
    )
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "egress",
            "caption-decode-proof",
            "--channel-id",
            "gov",
            "--emitted-stream",
            str(tmp_path / "missing.ts"),
            "--expected-captions",
            str(expected_path),
            "--decoded-captions",
            str(decoded_path),
        ],
    )

    assert result.exit_code != 0
    assert "Emitted stream file does not exist" in result.output


def test_egress_run_requires_channel_id() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["egress", "run", "--once"])

    assert result.exit_code != 0
    assert "At least one --channel-id value is required" in _plain_text(result.output)


def test_staff_token_cli_generate_env_emits_versioned_random_secret() -> None:
    runner = CliRunner()

    first = runner.invoke(app, ["token", "generate-env"])
    second = runner.invoke(app, ["token", "generate-env"])

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert re.fullmatch(r"ccenv1_[A-Za-z0-9_-]{43}\n", first.stdout)
    assert first.stdout != second.stdout


def test_staff_token_cli_issue_list_and_revoke_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryStaffTokenStore()
    monkeypatch.setattr(cli_module, "_get_staff_token_store", lambda: store)
    runner = CliRunner()

    issued_result = runner.invoke(
        app,
        [
            "token",
            "issue",
            "--operator-id",
            "clerk-a",
            "--display-name",
            "Clerk A",
            "--json",
        ],
    )
    assert issued_result.exit_code == 0
    issued = json.loads(issued_result.stdout)
    assert issued["secret"].startswith(f"ccst_{issued['token_id']}_")
    assert issued["secret_shown_once"] is True

    list_result = runner.invoke(app, ["token", "list", "--json"])
    assert list_result.exit_code == 0
    listed = json.loads(list_result.stdout)
    assert listed["tokens"][0]["token_id"] == issued["token_id"]
    assert "secret" not in listed["tokens"][0]

    revoke_result = runner.invoke(
        app,
        ["token", "revoke", issued["token_id"], "--reason", "test", "--json"],
    )
    assert revoke_result.exit_code == 0
    revoked = json.loads(revoke_result.stdout)
    assert revoked["revocation_reason"] == "test"
    assert revoked["revoked_at"] is not None


def _plain_text(value: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", value)


def test_egress_verify_runs_probe_and_exits_on_fail(monkeypatch, tmp_path) -> None:
    """CA-7: civiccast egress verify wires the compliance probe and exit code."""

    from civiccast.egress.compliance import ComplianceCheck, ComplianceProbeResult
    from civiccast.egress.models import EgressConfig, EgressSinkSpec

    config = EgressConfig(
        channel_id="gov",
        enabled=True,
        slate_message="x",
        sinks=[
            EgressSinkSpec(
                kind="udp-ts",
                label="Cable headend",
                uri="udp://239.255.0.1:5000",
                extra_output_args=["-muxrate", "8000k"],
            )
        ],
    )

    class _FakeStore:
        def __init__(self, _factory) -> None:  # type: ignore[no-untyped-def]
            pass

        def get_config(self, channel_id: str):  # type: ignore[no-untyped-def]
            return config if channel_id == "gov" else None

    calls: list[tuple[str, int]] = []

    def fake_probe(cfg, *, seconds, work_dir):  # type: ignore[no-untyped-def]
        calls.append((cfg.channel_id, seconds))
        return ComplianceProbeResult(
            channel_id=cfg.channel_id,
            destination="udp://239.255.0.1:5000",
            verdict="fail",
            checks=[ComplianceCheck(check="continuity", status="fail", detail="9 errors")],
            detail="",
        )

    monkeypatch.setattr("civiccast.egress.store.PostgresEgressStore", _FakeStore)
    monkeypatch.setattr("civiccast.egress.compliance.run_compliance_probe", fake_probe)
    monkeypatch.setattr(cli_module, "_build_cli_session_factory", lambda: None)
    monkeypatch.setattr(cli_module, "_default_egress_work_dir", lambda: tmp_path)

    runner = CliRunner()
    result = runner.invoke(app, ["egress", "verify", "--channel-id", "gov", "--seconds", "5"])

    assert calls == [("gov", 5)]
    assert result.exit_code == 1
    assert "Verdict: fail" in result.stdout
    assert "continuity: fail" in result.stdout
