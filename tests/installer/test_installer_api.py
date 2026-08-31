# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from civiccast import __version__
from civiccast.app import create_app
from civiccast.installer.models import (
    DiagnosticBundleRequest,
    FirstAdminSetupRequest,
    RestoreStatus,
)
from civiccast.installer.service import (
    build_rehearsal_report,
    build_restore_status,
    build_system_health_report,
    build_update_rollback_status,
    complete_first_admin_setup,
    create_acceptance_packet,
    create_diagnostic_bundle,
)
from civiccast.installer.tsduck_install import TsduckInstallReport
from civiccast.schedule.ingest import FfprobeResult


def _external_database_reports_current(monkeypatch) -> None:
    """Make the stand-in ``DATABASE_URL`` answer like a healthy database.

    ``postgresql://configured`` is a placeholder these tests use to mean "this
    station has durable storage configured"; nothing behind it exists. That
    used to be enough, because ``durable_storage_status`` returned
    ``status="ready"``, ``migrations_applied=True`` for ANY external
    ``DATABASE_URL`` with no connection attempt and no schema check. It now
    executes a bounded connectivity + schema-currency probe, so the placeholder
    has to answer like a real, migrated database -- otherwise the
    durable-storage health check correctly reports red and buries the
    system-health behaviour these tests exist to prove. Injected at
    ``read_db_revision``, the probe's one real connect.
    """

    from civiccast import schema_check

    monkeypatch.setattr(
        schema_check,
        "read_db_revision",
        lambda database_url: schema_check.expected_migration_head(),
    )


def test_installer_first_run_plan_api() -> None:
    client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})

    response = client.get(
        "/api/staff/installer/first-run-plan",
        params={"profile": "public-meetings", "recommended_tier": "tier-1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["profile"] == "public-meetings"
    assert payload["cloud_fallback_default"] == "off"
    assert any(step["id"] == "health" for step in payload["steps"])


def test_installer_summary_exposes_operator_console_handoff_url(monkeypatch) -> None:
    monkeypatch.setenv("CIVICCAST_OPERATOR_CONSOLE_URL", "http://127.0.0.1:5173")
    client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})

    response = client.get("/api/staff/installer/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["operator_console_url"] == "http://127.0.0.1:5173"
    assert payload["ready"] is False


def test_installer_summary_ignores_a_legacy_setup_nonce_env_var(monkeypatch) -> None:
    """The installer-handoff nonce was retired 2026-08-29 (owner decision):
    the control plane binds 127.0.0.1 only, so first setup is unreachable
    from the network by construction and the nonce was a redundant,
    failure-prone gate. A station upgraded from an older build may still
    carry a leftover CIVICCAST_SETUP_NONCE in its environment; the handoff
    URL must never append it."""

    monkeypatch.setenv("CIVICCAST_OPERATOR_CONSOLE_URL", "http://127.0.0.1:5173/setup")
    monkeypatch.setenv("CIVICCAST_SETUP_NONCE", "leftover-from-an-older-build")
    client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})

    response = client.get("/api/staff/installer/summary")

    assert response.status_code == 200
    assert response.json()["operator_console_url"] == "http://127.0.0.1:5173/setup"


def test_tester_ops_state_survives_concurrent_health_panels(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("CIVICCAST_ACTIVITYPUB_MODE", "disabled")
    monkeypatch.setenv("CIVICCAST_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_TESTER_OPS_STATE_PATH", str(tmp_path / "ops-state.json"))

    def read_panel(index: int) -> str:
        if index % 3 == 0:
            return build_system_health_report().safe_to_broadcast
        if index % 3 == 1:
            return build_restore_status().status
        return build_update_rollback_status().status

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(read_panel, range(36)))

    assert len(results) == 36
    state = json.loads((tmp_path / "ops-state.json").read_text(encoding="utf-8"))
    assert state["backup"]["status"] == "ready"
    assert state["backup"]["destination"] == str((tmp_path / "backups").resolve())
    assert not list(tmp_path.glob("*.tmp"))


def test_packaged_operator_console_is_served_from_api_when_configured(
    monkeypatch,
    tmp_path: Path,
) -> None:
    operator_dist = tmp_path / "operator-dist"
    operator_dist.mkdir()
    (operator_dist / "index.html").write_text("<h1>Operator console</h1>", encoding="utf-8")
    monkeypatch.setenv("CIVICCAST_OPERATOR_CONSOLE_DIST", str(operator_dist))
    client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})

    summary = client.get("/api/staff/installer/summary")
    operator = client.get("/operator/")
    operator_deep_link = client.get("/operator/setup")

    assert summary.status_code == 200
    assert summary.json()["operator_console_url"] == "http://127.0.0.1:8000/operator/"
    assert operator.status_code == 200
    assert "Operator console" in operator.text
    assert operator_deep_link.status_code == 200
    assert "Operator console" in operator_deep_link.text


def test_installer_action_returns_operator_console_handoff_url(monkeypatch) -> None:
    monkeypatch.setenv("CIVICCAST_OPERATOR_CONSOLE_URL", "http://127.0.0.1:5173")
    client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})

    response = client.post(
        "/api/staff/installer/actions",
        json={"lane_id": "package", "action": "continue"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["operator_console_url"] == "http://127.0.0.1:5173"
    assert "Open operator console" in payload["message"]


def test_public_storage_setup_prepares_local_durable_database(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", raising=False)
    monkeypatch.setenv("CIVICCAST_MANAGED_STORAGE_DIR", str(tmp_path / "managed"))
    client = TestClient(create_app())

    before = client.get(
        "/api/setup/storage",
    )
    assert before.status_code == 200
    assert before.json()["status"] == "not_configured"

    try:
        response = client.post(
            "/api/setup/storage",
            json={},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ready"
        assert payload["migrations_applied"] is True
        assert (tmp_path / "managed" / "data" / "civiccast.sqlite3").exists()
        assert (tmp_path / "managed" / "uploads").is_dir()
        assert (tmp_path / "managed" / "uploads" / "recordings").is_dir()
        from civiccast.live.recording_paths import DEFAULT_RECORDING_TARGET_ID
        from civiccast.live.router import get_recording_target_store

        resolver = client.app.dependency_overrides[get_recording_target_store]
        targets = resolver().list()
        target = next(
            item for item in targets if item.recording_target_id == DEFAULT_RECORDING_TARGET_ID
        )
        assert target.target_uri == (tmp_path / "managed" / "uploads" / "recordings").as_uri()
        coming_up = client.get("/api/public/schedule/coming-up")
        assert coming_up.status_code == 200
        assert coming_up.json() == []
    finally:
        import gc

        from civiccast.db import reset_engine

        client.close()
        reset_engine()
        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("CIVICCAST_UPLOAD_DIR", None)
        gc.collect()


def test_public_storage_setup_enables_first_asset_upload_without_manual_upload_dir(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CIVICCAST_UPLOAD_DIR", raising=False)
    monkeypatch.delenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", raising=False)
    monkeypatch.setenv("CIVICCAST_STAFF_TOKENS_FALLBACK_WITH_DB", "1")
    monkeypatch.setenv("CIVICCAST_MANAGED_STORAGE_DIR", str(tmp_path / "managed"))
    client = TestClient(create_app())
    ffprobe_result = FfprobeResult(
        duration_seconds=60,
        codec_video="h264",
        codec_audio="aac",
        width_px=1280,
        height_px=720,
        bitrate_bps=2_000_000,
        format_name="mov,mp4,m4a,3gp,3g2,mj2",
    )

    try:
        setup = client.post(
            "/api/setup/storage",
            json={},
        )
        assert setup.status_code == 200
        assert os.environ["CIVICCAST_UPLOAD_DIR"] == str(tmp_path / "managed" / "uploads")

        with (
            patch("civiccast.schedule.router.run_ffprobe", return_value=ffprobe_result),
            patch("civiccast.schedule.router.validate_ingest"),
        ):
            response = client.post(
                "/api/staff/assets/upload",
                data={"asset_id": "first-upload", "title": "First upload"},
                files={"file": ("meeting.mp4", b"video-bytes", "video/mp4")},
                headers={"Authorization": "Bearer operator-token-a"},
            )

        assert response.status_code == 201
        payload = response.json()
        assert payload["asset_id"] == "first-upload"
        assert Path(payload["file_path"]).is_file()
        assert Path(payload["file_path"]).is_relative_to(tmp_path / "managed" / "uploads")
    finally:
        import gc

        from civiccast.db import reset_engine

        client.close()
        reset_engine()
        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("CIVICCAST_UPLOAD_DIR", None)
        gc.collect()


def test_other_worker_observes_completed_managed_storage_without_restart(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CIVICCAST_UPLOAD_DIR", raising=False)
    monkeypatch.delenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", raising=False)
    monkeypatch.setenv("CIVICCAST_STAFF_TOKENS_FALLBACK_WITH_DB", "1")
    monkeypatch.setenv("CIVICCAST_MANAGED_STORAGE_DIR", str(tmp_path / "managed"))
    other_worker = create_app()
    setup_client = TestClient(create_app())
    other_client = TestClient(
        other_worker,
        headers={"Authorization": "Bearer operator-token-a"},
    )

    try:
        setup = setup_client.post(
            "/api/setup/storage",
            json={},
        )
        assert setup.status_code == 200
        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("CIVICCAST_UPLOAD_DIR", None)

        response = other_client.get("/api/staff/assets")

        assert response.status_code == 200
        assert response.json() == []
        assert other_worker.state.durable_storage_active is True
        health = other_client.get("/api/staff/installer/system-health")
        assert health.status_code == 200
        recording_path = {item["id"]: item for item in health.json()["checks"]}["recording-path"]
        assert recording_path["state"] == "needs_attention"
        assert "1 recording target" in recording_path["message"]
        assert os.environ["CIVICCAST_UPLOAD_DIR"] == str(tmp_path / "managed" / "uploads")
    finally:
        import gc

        from civiccast.db import reset_engine

        setup_client.close()
        other_client.close()
        reset_engine()
        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("CIVICCAST_UPLOAD_DIR", None)
        gc.collect()


def test_public_storage_setup_succeeds_from_loopback_with_no_token_of_any_kind(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """OWNER DECISION 2026-08-29: the installer-handoff nonce is retired --
    the control plane binds 127.0.0.1 only, so a loopback request is already
    unreachable from the network by construction. First setup on this
    station now needs nothing but a request that actually arrives on
    loopback: no header, no query param, no cookie, no CIVICCAST_SETUP_NONCE
    env var. This is the regression test for the field loop the nonce used
    to cause (installer button -> console -> First Setup dead-ended)."""

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", raising=False)
    monkeypatch.setenv("CIVICCAST_MANAGED_STORAGE_DIR", str(tmp_path / "managed"))
    client = TestClient(create_app())

    try:
        response = client.post("/api/setup/storage", json={})

        assert response.status_code == 200
        assert response.json()["status"] == "ready"
        assert (tmp_path / "managed" / "data" / "civiccast.sqlite3").exists()
    finally:
        import gc

        from civiccast.db import reset_engine

        client.close()
        reset_engine()
        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("CIVICCAST_UPLOAD_DIR", None)
        gc.collect()


def test_public_storage_setup_rejects_client_supplied_storage_dir(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", raising=False)
    monkeypatch.setenv("CIVICCAST_MANAGED_STORAGE_DIR", str(tmp_path / "managed"))
    arbitrary = tmp_path / "attacker-chosen"
    client = TestClient(create_app())

    response = client.post(
        "/api/setup/storage",
        json={"storage_dir": str(arbitrary)},
    )

    assert response.status_code == 422
    assert not arbitrary.exists()


def test_public_first_admin_setup_rejects_malformed_body_from_non_loopback_before_validation() -> (
    None
):
    """G-24: the local-access gate must run before Pydantic body validation,
    so a malformed body from a non-loopback caller gets 403 (authz), not 422
    (which would mean the handler's body-parsing ran before the gate). A
    loopback caller with the same malformed body gets ordinary 422 body
    validation instead, since there is no other gate left to intercept it.
    """
    remote_client = TestClient(create_app(), client=("203.0.113.20", 4242))
    loopback_client = TestClient(create_app())

    remote_response = remote_client.post("/api/setup/first-admin", json={})
    loopback_response = loopback_client.post("/api/setup/first-admin", json={})

    assert remote_response.status_code == 403
    assert "station computer itself" in remote_response.json()["detail"]
    assert loopback_response.status_code == 422


def test_staff_storage_setup_requires_setup_admin_role(monkeypatch, tmp_path: Path) -> None:
    """A correctly-authenticated but wrong-role token gets 403; a correctly-
    authenticated setup_admin token succeeds.

    civiccast.auth.tokens.verify_bearer_token (a370b35) made durable-storage
    deployments fail closed on plain ``CIVICCAST_STAFF_TOKENS`` entries: once
    a DB-backed ``staff_token_store`` is active (the default whenever
    ``CIVICCAST_ALLOW_EPHEMERAL_STORES`` is not set, as here), an env token
    that is not also a DB-issued token no longer authenticates on its own --
    it needs the explicit ``CIVICCAST_STAFF_TOKENS_FALLBACK_WITH_DB=1`` opt-in
    used elsewhere in this file (see
    ``test_public_storage_setup_enables_first_asset_upload_without_manual_upload_dir``
    above). Without it, BOTH clients below get 401 before the role-check
    dependency ever runs -- correct fail-closed behavior, but it means this
    test was silently no longer proving the role check at all. Setting the
    same opt-in restores real authentication for both tokens, so the 403 the
    role dependency raises for the wrong-role token, and the 200 the
    correctly-roled token gets, are both genuinely exercised again.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CIVICCAST_UPLOAD_DIR", raising=False)
    monkeypatch.delenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", raising=False)
    monkeypatch.setenv("CIVICCAST_STAFF_TOKENS_FALLBACK_WITH_DB", "1")
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS",
        "records-token:records-1:Records Clerk:records_clerk;"
        "setup-token:setup-1:Setup Admin:setup_admin",
    )
    records_client = TestClient(create_app(), headers={"Authorization": "Bearer records-token"})
    setup_client = TestClient(create_app(), headers={"Authorization": "Bearer setup-token"})
    records_dir = tmp_path / "records-managed"
    setup_dir = tmp_path / "setup-managed"

    try:
        forbidden = records_client.post(
            "/api/staff/installer/storage",
            json={"storage_dir": str(records_dir)},
        )
        allowed = setup_client.post(
            "/api/staff/installer/storage",
            json={"storage_dir": str(setup_dir)},
        )

        assert forbidden.status_code == 403
        assert "setup_admin" in forbidden.json()["detail"]
        assert not records_dir.exists()
        assert allowed.status_code == 200
        assert allowed.json()["status"] == "ready"
    finally:
        import gc

        from civiccast.db import reset_engine

        records_client.close()
        setup_client.close()
        reset_engine()
        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("CIVICCAST_UPLOAD_DIR", None)
        gc.collect()


def test_staff_storage_setup_rejects_an_unrecognized_token_with_401(
    monkeypatch, tmp_path: Path
) -> None:
    """A bad/absent staff token gets 401 from the auth layer, before the
    role-check dependency ever runs -- not the 403 a wrong-role-but-valid
    token gets. Companion to
    ``test_staff_storage_setup_requires_setup_admin_role`` above: that test
    covers a VALID, correctly-authenticated token with the wrong role (403);
    this one covers an env token that never authenticates in the first place
    (the default, fail-closed behavior once a durable, DB-backed
    ``staff_token_store`` is active and
    ``CIVICCAST_STAFF_TOKENS_FALLBACK_WITH_DB`` is NOT set -- see
    civiccast.auth.tokens.verify_bearer_token, a370b35).
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CIVICCAST_UPLOAD_DIR", raising=False)
    monkeypatch.delenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", raising=False)
    monkeypatch.delenv("CIVICCAST_STAFF_TOKENS_FALLBACK_WITH_DB", raising=False)
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS",
        "setup-token:setup-1:Setup Admin:setup_admin",
    )
    unrecognized_client = TestClient(
        create_app(), headers={"Authorization": "Bearer not-a-registered-token"}
    )
    no_credential_client = TestClient(create_app())
    storage_dir = tmp_path / "unauthenticated-managed"

    try:
        unrecognized = unrecognized_client.post(
            "/api/staff/installer/storage",
            json={"storage_dir": str(storage_dir)},
        )
        missing = no_credential_client.post(
            "/api/staff/installer/storage",
            json={"storage_dir": str(storage_dir)},
        )

        assert unrecognized.status_code == 401, unrecognized.text
        assert missing.status_code == 401, missing.text
        assert not storage_dir.exists()
    finally:
        import gc

        from civiccast.db import reset_engine

        unrecognized_client.close()
        no_credential_client.close()
        reset_engine()
        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("CIVICCAST_UPLOAD_DIR", None)
        gc.collect()


def test_installer_health_api_reports_fail_closed_surfaces() -> None:
    client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})

    response = client.get("/api/staff/installer/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ready"] is False
    assert {check["id"] for check in payload["checks"]} >= {
        "portal",
        "internet-archive",
        "youtube",
        "local-nas",
        "podcast",
        "signed-transcript",
        "subscriber-notifications",
    }
    blocked = {check["id"]: check for check in payload["checks"]}
    assert blocked["internet-archive"]["state"] == "credential_or_secret_required"
    assert "CIVICCAST_INTERNET_ARCHIVE_ACCESS_KEY" in blocked["internet-archive"]["next_step"]


def test_system_health_includes_channel_automation_rollup(monkeypatch, tmp_path) -> None:
    """CA-4: the health report carries the 24/7 channel rollup when supplied."""

    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_TESTER_OPS_STATE_PATH", str(tmp_path / "ops-state.json"))
    from civiccast.egress.models import ChannelAutomationRollup
    from civiccast.installer.service import build_system_health_report

    dark = build_system_health_report(
        channel_automation=ChannelAutomationRollup(
            automated=3, on_air=1, on_slate=1, dark=["government"]
        )
    )
    check = next(c for c in dark.checks if c.id == "channel-automation")
    assert check.color == "red"
    assert check.required is False
    assert "government" in check.message

    healthy = build_system_health_report(
        channel_automation=ChannelAutomationRollup(automated=2, on_air=2, on_slate=0)
    )
    check = next(c for c in healthy.checks if c.id == "channel-automation")
    assert check.color == "green"
    assert "2 automated channel(s)" in check.message

    none_set = build_system_health_report(
        channel_automation=ChannelAutomationRollup(automated=0, on_air=0, on_slate=0)
    )
    check = next(c for c in none_set.checks if c.id == "channel-automation")
    assert check.color == "green"
    assert check.state == "not_set_up"

    omitted = build_system_health_report(channel_automation=None)
    assert all(c.id != "channel-automation" for c in omitted.checks)


def test_system_health_includes_contributor_upload_usage(monkeypatch, tmp_path) -> None:
    """QA-2 (Critical): before this check existed, an operator's only signal
    that the contributor upload directory was filling up was a 507 the
    first time a contributor's upload was refused. This proves the System
    Health report now carries the usage directly."""

    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_TESTER_OPS_STATE_PATH", str(tmp_path / "ops-state.json"))
    upload_dir = tmp_path / "contributor-uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CIVICCAST_CONTRIBUTOR_UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("CIVICCAST_CONTRIBUTOR_UPLOAD_DIR_MAX_BYTES", str(10 * 1024 * 1024))

    empty = build_system_health_report()
    empty_check = next(c for c in empty.checks if c.id == "contributor-upload-storage")
    assert empty_check.color == "green"

    (upload_dir / "near-ceiling.bin").write_bytes(b"\0" * (9 * 1024 * 1024))
    near_ceiling = build_system_health_report()
    near_check = next(c for c in near_ceiling.checks if c.id == "contributor-upload-storage")
    assert near_check.color == "yellow"
    assert "contributor" in near_check.message.lower()

    (upload_dir / "at-ceiling.bin").write_bytes(b"\0" * (2 * 1024 * 1024))
    full = build_system_health_report()
    full_check = next(c for c in full.checks if c.id == "contributor-upload-storage")
    assert full_check.color == "red"
    assert full_check.required is False, (
        "contributor-upload storage must never block the broadcast itself"
    )


def test_system_health_includes_caption_device_visibility(monkeypatch, tmp_path) -> None:
    """Owner review "option D": the health report must say, honestly, which
    device captions are running on -- and when a capable GPU is sitting idle
    only because the CUDA runtime component pack is not installed yet
    (owner review 2026-08-15, option B's presence gate), rather than silently
    running on CPU with no visible explanation. Never blocks readiness:
    every state below stays green/optional -- CPU is the fully-functional
    baseline, this check is purely informational.
    """

    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_TESTER_OPS_STATE_PATH", str(tmp_path / "ops-state.json"))
    monkeypatch.delenv("CIVICCAST_WHISPER_DEVICE", raising=False)
    monkeypatch.delenv("CIVICCAST_WHISPER_COMPUTE_TYPE", raising=False)
    from civiccast.installer.service import build_system_health_report
    from civiccast.native import station_runtime

    install_root = tmp_path / "install-root"
    monkeypatch.setenv("CIVICCAST_NATIVE_STATION_ROOT", str(install_root))

    # (3) No capable GPU at all -> plain CPU, no claim about missing libraries.
    monkeypatch.setattr(station_runtime, "_probe_nvidia_vram_gb", lambda: None)
    cpu_only = build_system_health_report()
    cpu_check = next(c for c in cpu_only.checks if c.id == "caption-device")
    assert cpu_check.color == "green"
    assert cpu_check.required is False
    assert cpu_check.state == "ready"
    assert "cpu" in cpu_check.message.lower()
    assert "missing" not in cpu_check.message.lower()

    # (2) Capable GPU, but the CUDA runtime DLLs are not staged -- the new
    # default reality on ~95%+ of NVIDIA machines until the component pack
    # ships. Must say the GPU path exists without claiming it is active.
    monkeypatch.setattr(station_runtime, "_probe_nvidia_vram_gb", lambda: 16.0)
    capable_no_libs = build_system_health_report()
    no_libs_check = next(c for c in capable_no_libs.checks if c.id == "caption-device")
    assert no_libs_check.color == "green"
    assert no_libs_check.required is False
    assert "cpu" in no_libs_check.message.lower()
    assert "gpu" in no_libs_check.message.lower()
    assert "component" in no_libs_check.message.lower()

    # (1) Capable GPU with both required CUDA runtime DLLs staged -> active.
    cuda_bin = station_runtime.cuda_bin_dir(install_root)
    cuda_bin.mkdir(parents=True, exist_ok=True)
    (cuda_bin / "cublas64_12.dll").write_bytes(b"")
    (cuda_bin / "cudnn64_9.dll").write_bytes(b"")
    active = build_system_health_report()
    active_check = next(c for c in active.checks if c.id == "caption-device")
    assert active_check.color == "green"
    assert active_check.required is False
    assert "gpu" in active_check.message.lower()
    assert "active" in active_check.message.lower()


def test_system_health_caption_device_finds_libs_staged_at_the_acquisition_root(
    monkeypatch, tmp_path
) -> None:
    """Chain H1: a native-cuda-runtime component the non-elevated first-run
    GUI downloaded lands under ``<PROGRAMDATA>\\CivicCast`` (the acquisition
    root), never under the elevated install root -- the GUI cannot write
    there. The caption-device check must search that root too (the SAME one
    ``resolve_whisper_device`` itself gates cuda selection on), or a
    GUI-acquired component would be invisible to this check even though
    captions are actually running on it.
    """

    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_TESTER_OPS_STATE_PATH", str(tmp_path / "ops-state.json"))
    monkeypatch.delenv("CIVICCAST_WHISPER_DEVICE", raising=False)
    monkeypatch.delenv("CIVICCAST_WHISPER_COMPUTE_TYPE", raising=False)
    from civiccast.installer.service import build_system_health_report
    from civiccast.native import station_runtime

    # A real, known install root -- but nothing is staged under it (the GUI
    # cannot write there at all); only the acquisition root carries the DLLs.
    install_root = tmp_path / "install-root"
    monkeypatch.setenv("CIVICCAST_NATIVE_STATION_ROOT", str(install_root))
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "ProgramData"))
    monkeypatch.setattr(station_runtime, "_probe_nvidia_vram_gb", lambda: 16.0)

    acquisition_cuda_bin = station_runtime.cuda_bin_dir(tmp_path / "ProgramData" / "CivicCast")
    acquisition_cuda_bin.mkdir(parents=True, exist_ok=True)
    (acquisition_cuda_bin / "cublas64_12.dll").write_bytes(b"")
    (acquisition_cuda_bin / "cudnn64_9.dll").write_bytes(b"")

    report = build_system_health_report()
    check = next(c for c in report.checks if c.id == "caption-device")

    assert check.color == "green"
    assert "gpu" in check.message.lower()
    assert "active" in check.message.lower()


def test_system_health_includes_headend_readiness(monkeypatch, tmp_path) -> None:
    """CA-7: the health report carries the headend-verification rollup."""

    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_TESTER_OPS_STATE_PATH", str(tmp_path / "ops-state.json"))
    from civiccast.egress.compliance import HeadendReadinessRollup
    from civiccast.installer.service import build_system_health_report

    failing = build_system_health_report(
        headend_readiness=HeadendReadinessRollup(
            udp_channels=2, tsduck_installed=True, passes=["public"], fails=["government"]
        )
    )
    check = next(c for c in failing.checks if c.id == "headend-readiness")
    assert check.color == "red"
    assert check.required is False
    assert "government" in check.message

    byo = build_system_health_report(
        headend_readiness=HeadendReadinessRollup(udp_channels=1, tsduck_installed=False)
    )
    check = next(c for c in byo.checks if c.id == "headend-readiness")
    assert check.color == "yellow"
    assert "TSDuck" in check.message

    healthy = build_system_health_report(
        headend_readiness=HeadendReadinessRollup(
            udp_channels=1, tsduck_installed=True, passes=["public"]
        )
    )
    check = next(c for c in healthy.checks if c.id == "headend-readiness")
    assert check.color == "green"
    assert check.state == "ready"

    none_set = build_system_health_report(
        headend_readiness=HeadendReadinessRollup(udp_channels=0, tsduck_installed=False)
    )
    check = next(c for c in none_set.checks if c.id == "headend-readiness")
    assert check.color == "green"
    assert check.state == "not_set_up"

    omitted = build_system_health_report(headend_readiness=None)
    assert all(c.id != "headend-readiness" for c in omitted.checks)


def test_provider_readiness_never_echoes_secret_values(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    sentinels = {
        "CIVICCAST_IA_ACCESS_KEY": "ia-access-sentinel",
        "CIVICCAST_IA_SECRET_KEY": "ia-secret-sentinel",
        "CIVICCAST_YOUTUBE_CLIENT_ID": "yt-client-id-sentinel",
        "CIVICCAST_YOUTUBE_CLIENT_SECRET": "yt-secret-sentinel",
        "CIVICCAST_YOUTUBE_REFRESH_TOKEN": "yt-refresh-sentinel",
        "CIVICCAST_SMTP_HOST": "relay.example",
        "CIVICCAST_SMTP_FROM": "clerk@example.gov",
        "CIVICCAST_SMTP_USERNAME": "mailer-sentinel",
        "CIVICCAST_SMTP_PASSWORD": "smtp-secret-sentinel",
    }
    for name, value in sentinels.items():
        monkeypatch.setenv(name, value)
    client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})

    response = client.get("/api/staff/installer/provider-readiness")

    assert response.status_code == 200
    for name, value in sentinels.items():
        if name in ("CIVICCAST_SMTP_HOST", "CIVICCAST_SMTP_FROM"):
            continue  # operator-visible config, not credentials
        assert value not in response.text, f"{name} value leaked into provider readiness"


def test_first_admin_contract_is_operator_safe_and_recovery_kit_first() -> None:
    client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})

    response = client.get("/api/staff/installer/first-admin-contract")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "contract_defined"
    assert payload["identity_method"] == "local_admin_password"
    assert payload["recovery_kit"]["generated_during"] == "first-admin-setup"
    assert "printable" in payload["recovery_kit"]["media"]
    assert "downloadable_pdf" not in payload["recovery_kit"]["media"]
    assert "downloadable_text_file" in payload["recovery_kit"]["media"]
    assert "one-time recovery codes" in payload["recovery_kit"]["contains"]
    field_ids = {field["id"] for field in payload["required_fields"]}
    assert {"admin-username", "admin-password", "recovery-kit-destination"} <= field_ids
    destination_field = next(
        field for field in payload["required_fields"] if field["id"] == "recovery-kit-destination"
    )
    assert destination_field["label"] == "Where will you keep the recovery kit?"
    assert "does not save" in destination_field["help_text"]

    serialized = response.text.lower()
    assert "operator-token-a" not in serialized
    assert "civiccast-v08-subscription-token-secret" not in serialized
    assert "local-proof-key" not in serialized
    assert "provider secret values" in payload["recovery_kit"]["excludes"]


def test_safe_to_broadcast_contract_defines_required_optional_and_five_minute_copy() -> None:
    client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})

    response = client.get("/api/staff/installer/safe-to-broadcast-contract")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "contract_defined"
    assert payload["default_state"] == "red"
    assert {state["color"] for state in payload["states"]} == {"green", "yellow", "red"}
    assert {check["id"] for check in payload["required_checks"]} >= {
        "source-preflight",
        "recording-path",
        "resident-portal",
        "station-policy",
    }
    assert {check["id"] for check in payload["optional_checks"]} >= {
        "youtube",
        "subscriber-notifications",
        "activitypub",
    }
    assert any(
        "do not start the public broadcast" in item.lower()
        for item in payload["five_minutes_before_meeting"]
    )
    assert "full rehearsal-mode implementation" not in payload["non_goals"]
    assert "resident-preview implementation" not in payload["non_goals"]


def test_station_state_reports_unacknowledged_recovery_kit(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    client = TestClient(create_app())

    before = client.get("/api/setup/station-state")
    assert before.status_code == 200
    assert before.json()["recovery_kit_acknowledged"] is False

    setup = client.post(
        "/api/setup/first-admin",
        json={
            "station_name": "Pinegrove School Board",
            "admin_display_name": "Avery Admin",
            "admin_username": "avery",
            "admin_password": "correct horse battery staple",
            "recovery_kit_destination": "printed and stored in the clerk safe",
        },
    )
    assert setup.status_code == 200

    state = client.get("/api/setup/station-state")
    assert state.status_code == 200
    payload = state.json()
    assert payload["setup_complete"] is True
    assert payload["recovery_kit_acknowledged"] is False
    assert "recovery kit" in payload["next_step"].lower()


def test_recovery_kit_acknowledge_records_confirmation(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    client = TestClient(create_app())
    setup = client.post(
        "/api/setup/first-admin",
        json={
            "station_name": "Pinegrove School Board",
            "admin_display_name": "Avery Admin",
            "admin_username": "avery",
            "admin_password": "correct horse battery staple",
            "recovery_kit_destination": "printed and stored in the clerk safe",
        },
    )
    assert setup.status_code == 200

    ack = client.post(
        "/api/setup/recovery-kit/acknowledge",
        json={"confirmed": True},
    )
    assert ack.status_code == 200
    assert ack.json()["recovery_kit_acknowledged"] is True
    assert "rehearsal" in ack.json()["next_step"].lower()

    state = client.get("/api/setup/station-state")
    assert state.json()["recovery_kit_acknowledged"] is True

    raw = json.loads((tmp_path / "station-state.json").read_text(encoding="utf-8"))
    assert raw["recovery"]["acknowledged"] is True
    assert raw["recovery"]["acknowledged_at"]


def test_recovery_kit_acknowledge_requires_setup_and_confirmation(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    client = TestClient(create_app())

    too_early = client.post(
        "/api/setup/recovery-kit/acknowledge",
        json={"confirmed": True},
    )
    assert too_early.status_code == 409

    setup = client.post(
        "/api/setup/first-admin",
        json={
            "station_name": "Pinegrove",
            "admin_display_name": "Avery Admin",
            "admin_username": "avery",
            "admin_password": "correct horse battery staple",
            "recovery_kit_destination": "safe",
        },
    )
    assert setup.status_code == 200

    not_confirmed = client.post(
        "/api/setup/recovery-kit/acknowledge",
        json={"confirmed": False},
    )
    assert not_confirmed.status_code == 400
    state = client.get("/api/setup/station-state")
    assert state.json()["recovery_kit_acknowledged"] is False


def test_public_first_admin_setup_rejects_spoofed_host_header() -> None:
    """The loopback gate is decided from the ASGI transport's own peer
    address (``request.client.host``), never a caller-supplied header --
    so claiming ``Host: 127.0.0.1:8000`` from a real remote peer must not
    grant access."""

    client = TestClient(create_app(), client=("203.0.113.20", 4242))

    response = client.get(
        "/api/setup/station-state",
        headers={"host": "127.0.0.1:8000"},
    )

    assert response.status_code == 403
    assert (
        response.json()["detail"]
        == "First setup can only be done from the station computer itself."
    )


def test_public_setup_station_state_allowed_from_loopback_with_no_token() -> None:
    client = TestClient(create_app())

    response = client.get("/api/setup/station-state")

    assert response.status_code == 200


def test_public_setup_session_mutations_refused_from_non_loopback(tmp_path) -> None:
    """Every pre-staff-auth /api/setup/* mutation must refuse a non-loopback
    caller with the SAME honest detail -- never nonce-shaped wording (there
    is no nonce anymore) and never advice to click a control the caller
    cannot reach from off the station."""

    client = TestClient(create_app(), client=("203.0.113.20", 4242))
    setup_payload = {
        "station_name": "Pinegrove School Board",
        "admin_display_name": "Avery Admin",
        "admin_username": "avery",
        "admin_password": "correct horse battery staple",
        "recovery_kit_destination": "printed and stored in the clerk safe",
    }

    first_admin = client.post("/api/setup/first-admin", json=setup_payload)
    login = client.post(
        "/api/setup/login",
        json={
            "admin_username": "avery",
            "admin_password": "correct horse battery staple",
        },
    )
    recovery = client.post(
        "/api/setup/recover",
        json={
            "admin_username": "avery",
            "recovery_code": "not-a-real-code",
            "new_admin_password": "fresh horse battery staple",
        },
    )
    acknowledge = client.post(
        "/api/setup/recovery-kit/acknowledge",
        json={"confirmed": True},
    )

    expected_detail = "First setup can only be done from the station computer itself."
    assert first_admin.status_code == 403
    assert login.status_code == 403
    assert recovery.status_code == 403
    assert acknowledge.status_code == 403
    assert first_admin.json()["detail"] == expected_detail
    assert login.json()["detail"] == expected_detail
    assert recovery.json()["detail"] == expected_detail
    assert acknowledge.json()["detail"] == expected_detail


def test_public_first_admin_setup_generates_recovery_kit_and_staff_token(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    client = TestClient(create_app())

    before = client.get("/api/setup/station-state")
    assert before.status_code == 200
    assert before.json()["status"] == "not_started"

    response = client.post(
        "/api/setup/first-admin",
        json={
            "station_name": "Pinegrove School Board",
            "admin_display_name": "Avery Admin",
            "admin_username": "avery",
            "admin_password": "correct horse battery staple",
            "recovery_kit_destination": "printed and stored in the clerk safe",
            "public_base_url": "https://meetings.example.gov",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "complete"
    assert payload["profile"]["station_name"] == "Pinegrove School Board"
    assert len(payload["recovery_kit"]["recovery_codes"]) == 8
    assert payload["operator_console_token"].startswith("ccst_")
    assert "staff bearer token values" in payload["recovery_kit"]["excludes"]

    raw = (tmp_path / "station-state.json").read_text(encoding="utf-8")
    assert "correct horse battery staple" not in raw
    assert payload["operator_console_token"] not in raw
    for code in payload["recovery_kit"]["recovery_codes"]:
        assert code not in raw

    authed = TestClient(
        create_app(),
        headers={"Authorization": f"Bearer {payload['operator_console_token']}"},
    )
    state = authed.get("/api/staff/installer/station-state")
    assert state.status_code == 200
    assert state.json()["setup_complete"] is True


def test_first_admin_setup_persists_first_station_commissioning_defaults(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    client = TestClient(create_app())

    response = client.post(
        "/api/setup/first-admin",
        json={
            "station_name": "Pinegrove School Board",
            "admin_display_name": "Avery Admin",
            "admin_username": "avery",
            "admin_password": "correct horse battery staple",
            "recovery_kit_destination": "printed and stored in the clerk safe",
            "station_timezone": "America/Denver",
            "channel_count": 3,
        },
    )

    assert response.status_code == 200
    profile = response.json()["profile"]
    assert profile["station_timezone"] == "America/Denver"
    assert profile["channel_count"] == 3
    assert [channel["channel_id"] for channel in profile["channel_profiles"]] == [
        "public",
        "education",
        "government",
    ]
    media_path = Path(profile["storage_locations"]["media_library"])
    recordings_path = Path(profile["storage_locations"]["recordings"])
    assert media_path.parts[-2].lower() == "civiccast"
    assert media_path.parts[-1] == "media"
    assert recordings_path.parts[-2].lower() == "civiccast"
    assert recordings_path.parts[-1] == "recordings"
    assert profile["sample_content_enabled"] is True
    assert profile["initial_schedule_enabled"] is True
    assert profile["default_roles"] == [
        "setup_admin",
        "publish_operator",
        "support_admin",
        "viewer",
    ]
    assert profile["operation_mode"] == "test"
    assert profile["dashboard_ready_state"] == "not_ready"

    state = client.get("/api/setup/station-state")
    assert state.status_code == 200
    assert state.json()["profile"] == profile

    raw = json.loads((tmp_path / "station-state.json").read_text(encoding="utf-8"))
    assert raw["station"]["station_timezone"] == "America/Denver"
    assert raw["station"]["operation_mode"] == "test"


def test_station_login_and_recovery_keep_other_sessions_signed_in(monkeypatch, tmp_path) -> None:
    """Neither password login nor recovery may sign out other live sessions.

    Field bug (OWNER-verified 2026-08-30, two-browser repro): a routine
    password sign-in in browser A rotated the single stored token, so
    browser B's console 401'd minutes later with zero user action -- while
    the sign-in card promised the opposite. Both login and recovery now
    APPEND to the bounded session list -- see the OWNER DECISION comment on
    civiccast.installer.station_state._MAX_OPERATOR_SESSIONS."""

    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    client = TestClient(create_app())
    setup = client.post(
        "/api/setup/first-admin",
        json={
            "station_name": "Pinegrove School Board",
            "admin_display_name": "Avery Admin",
            "admin_username": "avery",
            "admin_password": "correct horse battery staple",
            "recovery_kit_destination": "printed and stored in the clerk safe",
        },
    )
    assert setup.status_code == 200
    first_token = setup.json()["operator_console_token"]
    recovery_code = setup.json()["recovery_kit"]["recovery_codes"][0]

    login = client.post(
        "/api/setup/login",
        json={
            "admin_username": "avery",
            "admin_password": "correct horse battery staple",
        },
    )
    assert login.status_code == 200
    login_token = login.json()["operator_console_token"]
    assert login_token != first_token

    # The fratricide fix: browser B's token (issued at setup) must STILL be
    # valid after browser A's routine password sign-in above.
    old_token_client = TestClient(
        create_app(),
        headers={"Authorization": f"Bearer {first_token}"},
    )
    assert old_token_client.get("/api/staff/installer/station-state").status_code == 200

    recovery = client.post(
        "/api/setup/recover",
        json={
            "admin_username": "avery",
            "recovery_code": recovery_code,
            "new_admin_password": "fresh horse battery staple",
        },
    )
    assert recovery.status_code == 200
    assert recovery.json()["status"] == "recovered"

    # The field bug, fixed: recovering the account must NOT sign the admin's
    # own other still-open browser tab back out. login_token was issued
    # before this recovery ran and must still work after it.
    login_token_client = TestClient(
        create_app(),
        headers={"Authorization": f"Bearer {login_token}"},
    )
    assert login_token_client.get("/api/staff/installer/station-state").status_code == 200

    reused = client.post(
        "/api/setup/recover",
        json={
            "admin_username": "avery",
            "recovery_code": recovery_code,
            "new_admin_password": "another horse battery staple",
        },
    )
    assert reused.status_code == 401
    old_password = client.post(
        "/api/setup/login",
        json={
            "admin_username": "avery",
            "admin_password": "correct horse battery staple",
        },
    )
    new_password = client.post(
        "/api/setup/login",
        json={
            "admin_username": "avery",
            "admin_password": "fresh horse battery staple",
        },
    )
    assert old_password.status_code == 401
    assert new_password.status_code == 200


def test_legacy_single_operator_token_shape_still_verifies(monkeypatch, tmp_path) -> None:
    """A station commissioned before the multi-session fix persisted a bare
    ``token_salt``/``token_hash`` pair on ``operator_console`` (no ``tokens``
    list). An in-place upgrade must keep that already-issued token valid
    instead of silently signing the operator out on update."""

    state_path = tmp_path / "station-state.json"
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(state_path))
    client = TestClient(create_app())

    setup = client.post(
        "/api/setup/first-admin",
        json={
            "station_name": "Pinegrove School Board",
            "admin_display_name": "Avery Admin",
            "admin_username": "avery",
            "admin_password": "correct horse battery staple",
            "recovery_kit_destination": "printed and stored in the clerk safe",
        },
    )
    assert setup.status_code == 200
    token = setup.json()["operator_console_token"]

    # Rewrite the freshly-written list-shape state back into the pre-fix
    # single-token shape, simulating a station that was commissioned by an
    # older build and never logged in again since the upgrade.
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    (entry,) = raw["operator_console"]["tokens"]
    raw["operator_console"] = {"token_salt": entry["token_salt"], "token_hash": entry["token_hash"]}
    state_path.write_text(json.dumps(raw), encoding="utf-8")

    legacy_client = TestClient(create_app(), headers={"Authorization": f"Bearer {token}"})
    assert legacy_client.get("/api/staff/installer/station-state").status_code == 200


def test_repeated_recovery_caps_concurrent_sessions_instead_of_growing_forever(
    monkeypatch,
    tmp_path,
) -> None:
    """Recovery appends rather than replaces (field fix), so state must stay
    bounded: the oldest session is evicted once the cap is exceeded rather
    than growing the state file forever. The real cap (20) is bigger than
    the 8 recovery codes a station ever has, so it's monkeypatched down to
    make eviction reachable within one kit's 8 codes."""

    _assert_repeated_signin_caps_sessions(monkeypatch, tmp_path, flow="recovery")


def test_repeated_login_caps_concurrent_sessions_instead_of_growing_forever(
    monkeypatch,
    tmp_path,
) -> None:
    """Login appends too now (2026-08-30 fratricide fix), so it needs the same
    bound: repeated password sign-ins evict the oldest session at the cap
    instead of growing the state file forever."""

    _assert_repeated_signin_caps_sessions(monkeypatch, tmp_path, flow="login")


def _assert_repeated_signin_caps_sessions(monkeypatch, tmp_path, *, flow: str) -> None:

    import civiccast.installer.station_state as station_state

    monkeypatch.setattr(station_state, "_MAX_OPERATOR_SESSIONS", 3)
    state_path = tmp_path / "station-state.json"
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(state_path))
    client = TestClient(create_app())

    setup = client.post(
        "/api/setup/first-admin",
        json={
            "station_name": "Pinegrove School Board",
            "admin_display_name": "Avery Admin",
            "admin_username": "avery",
            "admin_password": "correct horse battery staple",
            "recovery_kit_destination": "printed and stored in the clerk safe",
        },
    )
    codes = list(setup.json()["recovery_kit"]["recovery_codes"])
    first_token = setup.json()["operator_console_token"]

    latest_token = first_token
    for index, code in enumerate(codes[:4]):
        if flow == "recovery":
            response = client.post(
                "/api/setup/recover",
                json={
                    "admin_username": "avery",
                    "recovery_code": code,
                    "new_admin_password": f"rotation password number {index}",
                },
            )
        else:
            response = client.post(
                "/api/setup/login",
                json={
                    "admin_username": "avery",
                    "admin_password": "correct horse battery staple",
                },
            )
        assert response.status_code == 200
        latest_token = response.json()["operator_console_token"]

    raw = json.loads(state_path.read_text(encoding="utf-8"))
    assert len(raw["operator_console"]["tokens"]) == 3

    # The very first token (issued at setup, before any of the 4 sign-ins
    # above pushed the list past the cap of 3) was evicted...
    evicted_client = TestClient(create_app(), headers={"Authorization": f"Bearer {first_token}"})
    assert evicted_client.get("/api/staff/installer/station-state").status_code == 401
    # ...but the most recent recovery's own token is still live.
    latest_client = TestClient(create_app(), headers={"Authorization": f"Bearer {latest_token}"})
    assert latest_client.get("/api/staff/installer/station-state").status_code == 200


def test_revoke_other_sessions_keeps_caller_signed_in_and_signs_out_the_rest(
    monkeypatch,
    tmp_path,
) -> None:
    """CRITICAL fix: a lost/stolen laptop's operator-console session had no
    revoke path. This proves the new "revoke others" action keeps the
    calling session valid while invalidating every other one."""

    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    client = TestClient(create_app())

    setup = client.post(
        "/api/setup/first-admin",
        json={
            "station_name": "Pinegrove School Board",
            "admin_display_name": "Avery Admin",
            "admin_username": "avery",
            "admin_password": "correct horse battery staple",
            "recovery_kit_destination": "printed and stored in the clerk safe",
        },
    )
    assert setup.status_code == 200
    setup_token = setup.json()["operator_console_token"]

    # A second, third browser sign in -- e.g. the lost laptop, plus this
    # operator's own desktop, which is the session issuing the revoke below.
    lost_laptop_token = client.post(
        "/api/setup/login",
        json={"admin_username": "avery", "admin_password": "correct horse battery staple"},
    ).json()["operator_console_token"]
    caller_token = client.post(
        "/api/setup/login",
        json={"admin_username": "avery", "admin_password": "correct horse battery staple"},
    ).json()["operator_console_token"]

    caller_client = TestClient(create_app(), headers={"Authorization": f"Bearer {caller_token}"})
    response = caller_client.post("/api/staff/installer/sessions/revoke-others")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "revoked"
    assert body["revoked_count"] == 2  # setup token + lost-laptop token

    # The calling session is still valid...
    assert caller_client.get("/api/staff/installer/station-state").status_code == 200
    # ...but every other session, including the lost laptop's, is dead.
    setup_client = TestClient(create_app(), headers={"Authorization": f"Bearer {setup_token}"})
    lost_laptop_client = TestClient(
        create_app(), headers={"Authorization": f"Bearer {lost_laptop_token}"}
    )
    assert setup_client.get("/api/staff/installer/station-state").status_code == 401
    assert lost_laptop_client.get("/api/staff/installer/station-state").status_code == 401

    raw = json.loads((tmp_path / "station-state.json").read_text(encoding="utf-8"))
    assert len(raw["operator_console"]["tokens"]) == 1


def test_revoke_other_sessions_when_already_alone_revokes_nothing(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    client = TestClient(create_app())
    setup = client.post(
        "/api/setup/first-admin",
        json={
            "station_name": "Pinegrove School Board",
            "admin_display_name": "Avery Admin",
            "admin_username": "avery",
            "admin_password": "correct horse battery staple",
            "recovery_kit_destination": "printed and stored in the clerk safe",
        },
    )
    token = setup.json()["operator_console_token"]
    authed = TestClient(create_app(), headers={"Authorization": f"Bearer {token}"})

    response = authed.post("/api/staff/installer/sessions/revoke-others")
    assert response.status_code == 200
    assert response.json()["revoked_count"] == 0
    assert authed.get("/api/staff/installer/station-state").status_code == 200


def test_revoke_other_sessions_requires_authentication(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    client = TestClient(create_app())
    client.post(
        "/api/setup/first-admin",
        json={
            "station_name": "Pinegrove School Board",
            "admin_display_name": "Avery Admin",
            "admin_username": "avery",
            "admin_password": "correct horse battery staple",
            "recovery_kit_destination": "printed and stored in the clerk safe",
        },
    )

    response = client.post("/api/staff/installer/sessions/revoke-others")
    assert response.status_code == 401


def test_regenerate_recovery_kit_mints_working_codes_and_invalidates_the_old_ones(
    monkeypatch,
    tmp_path,
) -> None:
    """CRITICAL fix: a browser that died before saving the first-run kit had
    no way to get a fresh set of codes short of the destructive full-station
    reset env var. This proves the new regenerate action mints 8 new working
    codes and immediately kills the old ones."""

    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    client = TestClient(create_app())

    setup = client.post(
        "/api/setup/first-admin",
        json={
            "station_name": "Pinegrove School Board",
            "admin_display_name": "Avery Admin",
            "admin_username": "avery",
            "admin_password": "correct horse battery staple",
            "recovery_kit_destination": "printed and stored in the clerk safe",
        },
    )
    assert setup.status_code == 200
    token = setup.json()["operator_console_token"]
    old_codes = list(setup.json()["recovery_kit"]["recovery_codes"])
    old_kit_id = setup.json()["recovery_kit"]["kit_id"]

    authed = TestClient(create_app(), headers={"Authorization": f"Bearer {token}"})
    response = authed.post("/api/staff/installer/recovery-kit/regenerate")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "regenerated"
    new_kit = body["recovery_kit"]
    assert len(new_kit["recovery_codes"]) == 8
    assert new_kit["kit_id"] != old_kit_id
    new_codes = list(new_kit["recovery_codes"])
    assert set(new_codes).isdisjoint(old_codes)

    # An old code is dead now.
    old_code_attempt = client.post(
        "/api/setup/recover",
        json={
            "admin_username": "avery",
            "recovery_code": old_codes[0],
            "new_admin_password": "should not work at all",
        },
    )
    assert old_code_attempt.status_code == 401

    # A new code works and consumes exactly once.
    new_code_attempt = client.post(
        "/api/setup/recover",
        json={
            "admin_username": "avery",
            "recovery_code": new_codes[0],
            "new_admin_password": "fresh horse battery staple",
        },
    )
    assert new_code_attempt.status_code == 200
    reused_new_code = client.post(
        "/api/setup/recover",
        json={
            "admin_username": "avery",
            "recovery_code": new_codes[0],
            "new_admin_password": "another horse battery staple",
        },
    )
    assert reused_new_code.status_code == 401

    raw = json.loads((tmp_path / "station-state.json").read_text(encoding="utf-8"))
    assert new_kit["kit_id"] not in json.dumps(old_codes)
    for code in new_codes:
        assert code not in raw["recovery"]["code_hashes"] and code not in json.dumps(raw)


def test_regenerate_recovery_kit_requires_authentication(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    client = TestClient(create_app())
    client.post(
        "/api/setup/first-admin",
        json={
            "station_name": "Pinegrove School Board",
            "admin_display_name": "Avery Admin",
            "admin_username": "avery",
            "admin_password": "correct horse battery staple",
            "recovery_kit_destination": "printed and stored in the clerk safe",
        },
    )

    response = client.post("/api/staff/installer/recovery-kit/regenerate")
    assert response.status_code == 401


def test_regenerate_recovery_kit_before_setup_is_conflict(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_ALLOW_DETERMINISTIC_STAFF_TOKEN", "1")
    client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})
    response = client.post("/api/staff/installer/recovery-kit/regenerate")
    assert response.status_code == 409


def test_first_admin_setup_is_one_time_unless_reset_is_explicit(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    client = TestClient(create_app())
    payload = {
        "station_name": "Pinegrove",
        "admin_display_name": "Avery Admin",
        "admin_username": "avery",
        "admin_password": "correct horse battery staple",
        "recovery_kit_destination": "safe",
    }

    assert (
        client.post(
            "/api/setup/first-admin",
            json=payload,
        ).status_code
        == 200
    )
    second = client.post("/api/setup/first-admin", json=payload)

    assert second.status_code == 409
    assert "already complete" in second.json()["detail"]


def test_system_health_and_rehearsal_are_real_reports(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_TESTER_OPS_STATE_PATH", str(tmp_path / "ops-state.json"))
    monkeypatch.setenv("CIVICCAST_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured")
    _external_database_reports_current(monkeypatch)
    monkeypatch.setenv("CIVICCAST_RESIDENT_PORTAL_URL", "https://meetings.example.gov")

    request = FirstAdminSetupRequest(
        station_name="Pinegrove School Board",
        admin_display_name="Avery Admin",
        admin_username="avery",
        admin_password="correct horse battery staple",
        recovery_kit_destination="safe",
    )
    complete_first_admin_setup(request)

    report = build_system_health_report(
        live_source_count=1,
        recording_target_count=1,
        live_preflight_ready=True,
        recording_write_probe_ready=True,
        resident_preview_confirmed=True,
    )
    assert report.setup.setup_complete is True
    assert report.resident_preview.status == "available"
    checked = {check.id: check for check in report.checks}
    assert checked["first-admin"].state == "ready"
    assert checked["backup-status"].state == "ready"
    assert checked["source-preflight"].state == "ready"
    assert checked["recording-path"].state == "ready"
    assert report.safe_to_broadcast in {"green", "yellow"}

    rehearsal = build_rehearsal_report(
        live_source_count=1,
        recording_target_count=1,
        live_preflight_ready=True,
        recording_write_probe_ready=True,
        resident_preview_confirmed=True,
    )
    assert rehearsal.status in {"ready", "needs_attention"}
    assert rehearsal.resident_preview.public_url == "https://meetings.example.gov"


def test_system_health_does_not_go_green_from_configuration_without_live_proof(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_TESTER_OPS_STATE_PATH", str(tmp_path / "ops-state.json"))
    monkeypatch.setenv("CIVICCAST_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured")
    _external_database_reports_current(monkeypatch)
    monkeypatch.setenv("CIVICCAST_RESIDENT_PORTAL_URL", "https://meetings.example.gov")
    complete_first_admin_setup(
        FirstAdminSetupRequest(
            station_name="Pinegrove School Board",
            admin_display_name="Avery Admin",
            admin_username="avery",
            admin_password="correct horse battery staple",
            recovery_kit_destination="safe",
        )
    )

    report = build_system_health_report(live_source_count=1, recording_target_count=1)

    checked = {check.id: check for check in report.checks}
    assert report.safe_to_broadcast == "yellow"
    assert checked["source-preflight"].state == "needs_attention"
    assert checked["recording-path"].state == "needs_attention"
    assert checked["resident-portal"].state == "needs_attention"

    rehearsal = build_rehearsal_report(live_source_count=1, recording_target_count=1)

    assert rehearsal.status == "needs_attention"
    assert "required item still needs live proof" in rehearsal.message


def test_system_health_api_reports_setup_and_broadcast_readiness(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})

    response = client.get("/api/staff/installer/system-health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["safe_to_broadcast"] == "red"
    assert payload["setup"]["setup_complete"] is False
    assert payload["resident_preview"]["public_url"].startswith("http://127.0.0.1")
    assert {check["id"] for check in payload["checks"]} >= {
        "first-admin",
        "recovery-kit",
        "durable-storage",
        "source-preflight",
        "recording-path",
        "resident-portal",
        "station-policy",
    }


def test_backup_provider_source_update_and_support_contracts_are_operator_safe(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("CIVICCAST_TESTER_OPS_STATE_PATH", str(tmp_path / "ops-state.json"))
    monkeypatch.setenv(
        "CIVICCAST_PROVIDER_CREDENTIALS_FILE",
        str(tmp_path / "provider-credentials.json"),
    )
    monkeypatch.setenv(
        "CIVICCAST_PROVIDER_PROOFS_FILE",
        str(tmp_path / "provider-proof-evidence.json"),
    )
    monkeypatch.setenv("CIVICCAST_SUPPORT_BUNDLE_DIR", str(tmp_path / "support"))
    for env_name in (
        "CIVICCAST_YOUTUBE_CLIENT_ID",
        "CIVICCAST_YOUTUBE_CLIENT_SECRET",
        "CIVICCAST_INTERNET_ARCHIVE_ACCESS_KEY",
        "CIVICCAST_SUBSCRIBER_WEBHOOK_SECRET",
    ):
        monkeypatch.delenv(env_name, raising=False)
    client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})

    before_backup = client.get("/api/staff/installer/backup")
    assert before_backup.status_code == 200
    assert before_backup.json()["status"] == "not_set_up"

    backup = client.post(
        "/api/staff/installer/backup",
        json={"destination": str(tmp_path / "backups")},
    )
    assert backup.status_code == 200
    backup_payload = backup.json()
    assert backup_payload["status"] == "ready"
    assert backup_payload["destination"] == str((tmp_path / "backups").resolve())
    assert not list((tmp_path / "backups").glob(".civiccast-backup-probe-*"))

    provider = client.get("/api/staff/installer/provider-readiness")
    assert provider.status_code == 200
    provider_items = {item["id"]: item for item in provider.json()["items"]}
    assert provider_items["backup"]["status"] == "ready"
    assert "Run Verify backup" in " ".join(provider_items["backup"]["setup_steps"])
    assert provider_items["youtube"]["status"] == "not_set_up"
    assert "optional" in provider_items["youtube"]["message"].lower()
    assert provider_items["youtube"]["what_you_need"]
    assert provider_items["youtube"]["setup_url"].startswith("https://")
    assert "proof" in provider_items["youtube"]["proof_requirement"].lower()
    assert {field["id"] for field in provider_items["youtube"]["credential_fields"]} == {
        "client_id",
        "client_secret",
    }

    provider_credentials = client.post(
        "/api/staff/installer/provider-credentials",
        json={
            "provider_id": "youtube",
            "values": {
                "client_id": "youtube-client-id-for-test",
                "client_secret": "super-secret-youtube-client-secret",
            },
        },
    )
    assert provider_credentials.status_code == 200
    credentials_payload = provider_credentials.json()
    serialized_credentials = json.dumps(credentials_payload, sort_keys=True)
    assert credentials_payload["status"] == "stored"
    assert credentials_payload["credential_handle"] == "civiccast-provider://youtube"
    assert "super-secret-youtube-client-secret" not in serialized_credentials

    # rc17 D4 round 2 (CC-RC17-001): Setup-stored field names alone no longer
    # grant readiness -- they never reach the real adapter's own env-backed
    # loader. Set the exact variables `YouTubeSettings.from_env()` reads so
    # this test continues to exercise the proof/redaction contract below
    # against a genuinely satisfied real adapter, not the fixed false positive.
    monkeypatch.setenv("CIVICCAST_YOUTUBE_CLIENT_ID", "youtube-client-id-for-test")
    monkeypatch.setenv("CIVICCAST_YOUTUBE_CLIENT_SECRET", "super-secret-youtube-client-secret")
    monkeypatch.setenv("CIVICCAST_YOUTUBE_REFRESH_TOKEN", "youtube-refresh-token-for-test")

    provider_after = client.get("/api/staff/installer/provider-readiness")
    assert provider_after.status_code == 200
    youtube_after = {item["id"]: item for item in provider_after.json()["items"]}["youtube"]
    assert youtube_after["status"] == "needs_live_proof"
    assert (
        youtube_after["message"]
        == "YouTube credentials are present, but live proof has not passed."
    )
    assert "Start and stop a controlled live stream" in youtube_after["next_step"]
    assert "Upload a controlled VOD asset" in youtube_after["next_step"]
    assert youtube_after["credential_handle"] == "civiccast-provider://youtube"
    assert "super-secret-youtube-client-secret" not in json.dumps(youtube_after, sort_keys=True)

    proof_with_secret_reference = client.post(
        "/api/staff/installer/provider-proof",
        json={
            "provider_id": "youtube",
            "evidence_reference": "docs/releases/evidence/youtube.txt?token=leaked",
            "redaction_reviewed": True,
        },
    )
    assert proof_with_secret_reference.status_code == 422

    provider_proof = client.post(
        "/api/staff/installer/provider-proof",
        json={
            "provider_id": "youtube",
            "evidence_reference": "docs/releases/evidence/v1.4-youtube-proof.md",
            "redaction_reviewed": True,
        },
    )
    assert provider_proof.status_code == 200
    proof_payload = provider_proof.json()
    assert proof_payload["status"] == "stored"
    assert proof_payload["proof_status"] == "proof_passed"
    assert proof_payload["evidence_reference"] == "docs/releases/evidence/v1.4-youtube-proof.md"

    provider_proven = client.get("/api/staff/installer/provider-readiness")
    assert provider_proven.status_code == 200
    youtube_proven = {item["id"]: item for item in provider_proven.json()["items"]}["youtube"]
    assert youtube_proven["status"] == "ready"
    assert youtube_proven["proof_status"] == "proof_passed"
    assert youtube_proven["evidence_reference"] == "docs/releases/evidence/v1.4-youtube-proof.md"
    assert "super-secret-youtube-client-secret" not in json.dumps(youtube_proven, sort_keys=True)

    source = client.get("/api/staff/installer/source-setup")
    assert source.status_code == 200
    source_payload = source.json()
    assert source_payload["status"] == "not_set_up"
    assert {option["id"] for option in source_payload["options"]} >= {
        "usb-hdmi",
        "phone-app",
        "sample-upload",
    }
    assert all("operator_steps" in option for option in source_payload["options"])

    current = client.get("/api/staff/installer/update-rollback")
    assert current.status_code == 200
    assert current.json()["status"] == "current"
    assert current.json()["safe_to_apply"] is False

    no_update_preflight = client.post("/api/staff/installer/update-rollback/preflight")
    assert no_update_preflight.status_code == 200
    assert no_update_preflight.json()["status"] == "needs_attention"
    assert no_update_preflight.json()["safe_to_apply"] is False

    monkeypatch.setenv("CIVICCAST_TESTER_AVAILABLE_VERSION", __version__)
    current_available_marker = client.get("/api/staff/installer/update-rollback")
    assert current_available_marker.status_code == 200
    assert current_available_marker.json()["status"] == "current"
    assert current_available_marker.json()["safe_to_apply"] is False
    monkeypatch.delenv("CIVICCAST_TESTER_AVAILABLE_VERSION", raising=False)

    monkeypatch.setenv("CIVICCAST_TESTER_AVAILABLE_VERSION", "9.9.9")
    blocked_update = client.get("/api/staff/installer/update-rollback")
    assert blocked_update.status_code == 200
    assert blocked_update.json()["status"] == "needs_attention"
    assert blocked_update.json()["safe_to_apply"] is False
    assert "restore proof" in blocked_update.json()["message"]
    monkeypatch.delenv("CIVICCAST_TESTER_AVAILABLE_VERSION", raising=False)

    restore_before = client.get("/api/staff/installer/restore")
    assert restore_before.status_code == 200
    assert restore_before.json()["status"] == "not_tested"
    assert restore_before.json()["target_profile"] == "isolated-station-profile"
    assert any("Restore database, media" in step for step in restore_before.json()["plan_steps"])
    before_items = {item["id"]: item for item in restore_before.json()["proof_items"]}
    assert before_items["database"]["state"] == "pending"
    assert before_items["media"]["state"] == "pending"
    assert before_items["credential-metadata"]["state"] == "pending"
    assert "provider secret values" in restore_before.json()["excluded_items"]
    restore = client.post("/api/staff/installer/restore/rehearsal")
    assert restore.status_code == 200
    restore_payload = restore.json()
    assert restore_payload["status"] == "needs_attention"
    assert "checksum" in restore_payload["proof_summary"]
    assert "did not restore" in restore_payload["proof_summary"].lower()
    assert "database" in " ".join(restore_payload["plan_steps"])
    restore_items = {item["id"]: item for item in restore_payload["proof_items"]}
    assert {
        "database",
        "media",
        "config",
        "station-profile",
        "schedules",
        "captions",
        "records",
        "publish-state",
        "provider-readiness",
        "credential-metadata",
    } <= set(restore_items)
    assert all(item["state"] == "pending" for item in restore_items.values())
    serialized_restore = json.dumps(restore_payload, sort_keys=True)
    assert "super-secret-youtube-client-secret" not in serialized_restore
    assert not list((tmp_path / "backups").glob(".civiccast-restore-*"))
    restore_after = client.get("/api/staff/installer/restore")
    assert restore_after.status_code == 200
    assert restore_after.json()["status"] == "not_tested"
    assert {item["state"] for item in restore_after.json()["proof_items"]} == {"pending"}

    # The remainder of this test exercises the update/rollback state machine
    # with its restore prerequisite supplied. The production manifest
    # round-trip above intentionally no longer manufactures that prerequisite.
    update_prerequisite = RestoreStatus.model_validate(
        {
            **restore_payload,
            "status": "passed",
            "proof_items": [{**item, "state": "passed"} for item in restore_payload["proof_items"]],
            "message": "Full isolated restore prerequisite supplied by the update test.",
        }
    )
    monkeypatch.setattr(
        "civiccast.installer.service.build_restore_status",
        lambda: update_prerequisite,
    )

    monkeypatch.setenv("CIVICCAST_TESTER_AVAILABLE_VERSION", "9.9.9")
    available = client.get("/api/staff/installer/update-rollback")
    assert available.status_code == 200
    assert available.json()["status"] == "update_available"
    assert available.json()["available_version"] == "9.9.9"
    assert available.json()["safe_to_apply"] is False
    assert available.json()["last_preflight_at"] is None
    assert available.json()["checkpoint_summary"] is None
    assert any("maintenance window" in step for step in available.json()["plan_steps"])
    assert available.json()["rollback_artifact"] is None
    assert "Run update preflight" in available.json()["next_step"]

    preflight = client.post("/api/staff/installer/update-rollback/preflight")
    assert preflight.status_code == 200
    preflight_payload = preflight.json()
    assert preflight_payload["status"] == "update_available"
    assert preflight_payload["safe_to_apply"] is False
    assert preflight_payload["last_preflight_at"] is not None
    assert "9.9.9" in preflight_payload["checkpoint_summary"]
    assert preflight_payload["maintenance_window_state"] == "closed"
    assert "Open the maintenance window" in preflight_payload["next_step"]
    assert not list((tmp_path / "backups").glob(".civiccast-update-checkpoint-*"))

    blocked_window = client.post(
        "/api/staff/installer/update-rollback/maintenance-window",
        json={"duration_minutes": 30},
    )
    assert blocked_window.status_code == 200
    assert blocked_window.json()["status"] == "needs_attention"
    assert blocked_window.json()["safe_to_apply"] is False
    assert "rollback proof has not passed" in blocked_window.json()["message"]

    monkeypatch.setenv("CIVICCAST_TESTER_AVAILABLE_VERSION", "9.9.10")
    stale_preflight = client.get("/api/staff/installer/update-rollback")
    assert stale_preflight.status_code == 200
    assert stale_preflight.json()["status"] == "update_available"
    assert stale_preflight.json()["safe_to_apply"] is False
    assert stale_preflight.json()["last_preflight_at"] is None
    assert stale_preflight.json()["checkpoint_summary"] is None

    refreshed_preflight = client.post("/api/staff/installer/update-rollback/preflight")
    assert refreshed_preflight.status_code == 200
    assert refreshed_preflight.json()["last_preflight_at"] is not None
    assert "9.9.10" in refreshed_preflight.json()["checkpoint_summary"]

    rollback_artifact = tmp_path / "CivicCast_1.4.0_x64-setup.exe"
    rollback_bytes = b"rollback artifact bytes for rehearsal"
    rollback_artifact.write_bytes(rollback_bytes)
    configured_rollback = client.post(
        "/api/staff/installer/update-rollback/rollback-artifact",
        json={"artifact_path": str(rollback_artifact)},
    )
    assert configured_rollback.status_code == 200
    configured_payload = configured_rollback.json()
    assert configured_payload["rollback_available"] is True
    assert configured_payload["rollback_artifact"] == str(rollback_artifact.resolve())
    assert configured_payload["rollback_artifact_sha256"] == sha256(rollback_bytes).hexdigest()
    assert configured_payload["rollback_proof_state"] == "not_tested"

    rollback_rehearsal = client.post("/api/staff/installer/update-rollback/rollback-rehearsal")
    assert rollback_rehearsal.status_code == 200
    rollback_payload = rollback_rehearsal.json()
    assert rollback_payload["rollback_available"] is True
    assert rollback_payload["rollback_proof_state"] == "passed"
    assert rollback_payload["last_rollback_test_at"] is not None
    assert rollback_payload["rollback_artifact_sha256"] == sha256(rollback_bytes).hexdigest()
    assert "verified rollback artifact" in rollback_payload["rollback_proof_summary"]

    maintenance_window = client.post(
        "/api/staff/installer/update-rollback/maintenance-window",
        json={"duration_minutes": 30},
    )
    assert maintenance_window.status_code == 200
    maintenance_payload = maintenance_window.json()
    assert maintenance_payload["status"] == "update_available"
    assert maintenance_payload["safe_to_apply"] is True
    assert maintenance_payload["maintenance_window_state"] == "open"
    assert maintenance_payload["maintenance_window_expires_at"] is not None
    assert "9.9.10" in maintenance_payload["maintenance_window_summary"]

    failed_update = client.post("/api/staff/installer/update-rollback/failed-update-rehearsal")
    assert failed_update.status_code == 200
    failed_payload = failed_update.json()
    assert failed_payload["failed_update_rollback_state"] == "passed"
    assert failed_payload["last_failed_update_rollback_at"] is not None
    assert "simulated failed update" in failed_payload["failed_update_rollback_summary"]
    assert not list((tmp_path / "backups").glob(".civiccast-failed-update-rollback-*"))

    rollback_artifact.write_bytes(b"modified rollback artifact bytes")
    changed_rollback = client.get("/api/staff/installer/update-rollback")
    assert changed_rollback.status_code == 200
    assert changed_rollback.json()["rollback_available"] is True
    assert changed_rollback.json()["rollback_proof_state"] == "needs_attention"
    assert changed_rollback.json()["failed_update_rollback_state"] == "needs_attention"
    assert (
        changed_rollback.json()["rollback_artifact_sha256"]
        == sha256(b"modified rollback artifact bytes").hexdigest()
    )

    post_update_proof = client.post("/api/staff/installer/update-rollback/post-update-proof")
    assert post_update_proof.status_code == 200
    assert post_update_proof.json()["status"] == "needs_attention"
    assert post_update_proof.json()["post_update_proof_state"] == "needs_attention"
    assert "Safe to broadcast is not green" in post_update_proof.json()["message"]

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:top-secret-db@localhost/civiccast")
    monkeypatch.setenv("CIVICCAST_YOUTUBE_CLIENT_SECRET", "super-youtube-secret")
    operator_note = "the pasted secret is top-secret-note"
    support = client.post(
        "/api/staff/installer/support-bundle",
        json={"operator_note": operator_note},
    )
    assert support.status_code == 200
    support_payload = support.json()
    assert support_payload["redacted"] is True
    bundle_path = Path(support_payload["path"])
    assert bundle_path.is_file()
    raw_bundle = bundle_path.read_text(encoding="utf-8")
    assert "super-youtube-secret" not in raw_bundle
    assert "top-secret-db" not in raw_bundle
    assert "top-secret-note" not in raw_bundle
    parsed = json.loads(raw_bundle)
    assert parsed["environment"]["CIVICCAST_YOUTUBE_CLIENT_SECRET"]["value"] == "[redacted]"
    assert parsed["environment"]["DATABASE_URL"]["value"] == "[redacted]"
    assert parsed["operator_note"] == {"provided": True, "length": len(operator_note)}
    # The installer-handoff nonce was retired 2026-08-29 (owner decision):
    # operator_console_url() no longer appends a ?nonce= query param at all,
    # so there is nothing left to redact from either embedded URL.
    assert "nonce=" not in parsed["station_setup"]["operator_console_url"]
    assert "nonce=" not in parsed["system_health"]["setup"]["operator_console_url"]

    download = client.get(
        f"/api/staff/installer/support-bundle/{support_payload['bundle_id']}/download"
    )
    assert download.status_code == 200
    assert download.content == bundle_path.read_bytes()
    assert download.headers["content-type"] == "application/json"
    assert (
        download.headers["content-disposition"]
        == f'attachment; filename="{support_payload["bundle_id"]}.json"'
    )
    assert download.headers["cache-control"] == "no-store"

    missing_download = client.get(
        "/api/staff/installer/support-bundle/support-20000101T000000Z-deadbeef/download"
    )
    assert missing_download.status_code == 404


def test_support_bundle_download_rejects_non_support_admin(monkeypatch) -> None:
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS",
        "limited-token:limited:Limited Operator:meeting_operator",
    )
    client = TestClient(create_app(), headers={"Authorization": "Bearer limited-token"})

    response = client.get(
        "/api/staff/installer/support-bundle/support-20000101T000000Z-deadbeef/download"
    )

    assert response.status_code == 403


def test_installer_health_api_does_not_go_ready_from_placeholder_configuration(
    monkeypatch,
) -> None:
    monkeypatch.setenv("CIVICCAST_PORTAL_TOKEN", "placeholder-token")
    monkeypatch.setenv("CIVICCAST_INTERNET_ARCHIVE_ACCESS_KEY", "placeholder-ia-key")
    monkeypatch.setenv("CIVICCAST_YOUTUBE_CLIENT_SECRET", "placeholder-youtube-secret")
    monkeypatch.setenv("CIVICCAST_NAS_ARCHIVE_PATH", "Z:/definitely-not-present-civiccast")
    monkeypatch.setenv("CIVICCAST_SUBSCRIBER_WEBHOOK_SECRET", "placeholder-webhook-secret")
    client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})

    response = client.get("/api/staff/installer/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ready"] is False
    checked = {check["id"]: check for check in payload["checks"]}
    assert checked["portal"]["state"] == "credential_or_secret_required"
    assert checked["internet-archive"]["state"] == "credential_or_secret_required"
    assert checked["youtube"]["state"] == "credential_or_secret_required"
    assert checked["local-nas"]["state"] == "failed"
    assert checked["subscriber-notifications"]["state"] == "credential_or_secret_required"


def test_v12_first_run_api_does_not_report_ok_from_placeholder_configuration(
    monkeypatch,
) -> None:
    monkeypatch.setenv("CIVICCAST_PORTAL_TOKEN", "placeholder-token")
    monkeypatch.setenv("CIVICCAST_INTERNET_ARCHIVE_ACCESS_KEY", "placeholder-ia-key")
    monkeypatch.setenv("CIVICCAST_YOUTUBE_CLIENT_SECRET", "placeholder-youtube-secret")
    monkeypatch.setenv("CIVICCAST_NAS_ARCHIVE_PATH", "Z:/definitely-not-present-civiccast")
    monkeypatch.setenv("CIVICCAST_SUBSCRIBER_WEBHOOK_SECRET", "placeholder-webhook-secret")
    client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})

    response = client.get("/api/staff/first-run/wizard-v1.2")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    gates = {gate["name"]: gate for gate in payload["gates"]}
    assert gates["Resident portal"]["status"] == "credential_or_secret_required"
    assert gates["Internet Archive"]["status"] == "credential_or_secret_required"
    assert gates["YouTube"]["status"] == "credential_or_secret_required"
    assert gates["Local NAS"]["status"] == "failed"
    assert gates["Subscriber notifications"]["status"] == "credential_or_secret_required"


def test_cg_public_api_exposes_idle_and_emergency_states() -> None:
    client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})

    idle = client.get("/api/public/cg/idle", params={"channel_id": "gov-ch12"})
    overlay = client.get(
        "/api/public/cg/emergency-overlay",
        params={"overlay_id": "storm-warning", "severity": "emergency"},
    )

    assert idle.status_code == 200
    assert idle.json()["channel_id"] == "gov-ch12"
    assert overlay.status_code == 200
    assert overlay.json()["severity"] == "emergency"
    assert overlay.json()["cellular_fallback_enabled"] is True


def test_tsduck_status_endpoint_reports_install_state() -> None:
    client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})
    response = client.get("/api/staff/installer/tsduck")
    assert response.status_code == 200
    body = response.json()
    assert "installed" in body
    assert isinstance(body["installed"], bool)


def test_tsduck_install_endpoint_runs_helper_and_returns_report() -> None:
    fake = TsduckInstallReport(
        status="installed",
        version="3.44-4676",
        tsp_path="C:/managed/TSDuck/bin/tsp.exe",
        asset="TSDuck-Win64-3.44-4676-Portable.zip",
        message="TSDuck installed. Cable verification is now available.",
    )
    with patch("civiccast.installer.router.install_tsduck", return_value=fake) as install:
        client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})
        response = client.post("/api/staff/installer/tsduck/install")
    assert response.status_code == 200
    assert install.called
    body = response.json()
    assert body["status"] == "installed"
    assert body["version"] == "3.44-4676"


def test_tsduck_install_endpoint_rejects_non_admin(monkeypatch) -> None:
    # A meeting_operator token lacks setup_admin/support_admin -> the gate must 403
    # before any download/disk effect (the server gate is the real control).
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS", "limited-token:limited:Limited Operator:meeting_operator"
    )
    client = TestClient(create_app(), headers={"Authorization": "Bearer limited-token"})
    response = client.post("/api/staff/installer/tsduck/install")
    assert response.status_code == 403


def test_package_verification_endpoint_rejects_non_admin(monkeypatch) -> None:
    # SEC-2: package-verification takes arbitrary artifact/sidecar paths and
    # returns their SHA-256/attestation state -- a file oracle. A low-privilege
    # (meeting_operator) token must be refused before it can probe any path.
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS", "limited-token:limited:Limited Operator:meeting_operator"
    )
    client = TestClient(create_app(), headers={"Authorization": "Bearer limited-token"})
    response = client.post(
        "/api/staff/installer/package-verification",
        json={"artifact": "some/artifact", "sidecar": "some/sidecar"},
    )
    assert response.status_code == 403


def test_airgap_import_endpoint_rejects_non_admin(monkeypatch) -> None:
    # SEC-2: airgap-import reads/parses an arbitrary bundle_dir + proof_manifest
    # and echoes their content -- also a file oracle. Same gate.
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS", "limited-token:limited:Limited Operator:meeting_operator"
    )
    client = TestClient(create_app(), headers={"Authorization": "Bearer limited-token"})
    response = client.post(
        "/api/staff/installer/airgap-import",
        json={"bundle_dir": "some/bundle"},
    )
    assert response.status_code == 403


def test_support_bundle_includes_logs_with_secrets_redacted(monkeypatch, tmp_path) -> None:
    # Item #26: the support bundle must include runtime/service logs (installer
    # bootstrap log + per-channel egress FFmpeg logs), but every known-secret
    # pattern in those logs must come out redacted -- this is the "bundle must
    # never leak secrets/nonces/tokens even with logs included" acceptance test.
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_SUPPORT_BUNDLE_DIR", str(tmp_path / "support"))
    monkeypatch.setenv("CIVICCAST_EGRESS_WORK_DIR", str(tmp_path / "egress-work"))

    bootstrap_log = tmp_path / "runtime-host.log"
    bootstrap_log.write_text(
        "Runtime host started.\n"
        "CIVICCAST_SETUP_NONCE=super-secret-nonce-value\n"
        "Authorization: Bearer super-secret-bearer-token\n"
        "CivicCast service health recovered.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CIVICCAST_INSTALLER_BOOTSTRAP_LOG", str(bootstrap_log))

    channel_log_dir = tmp_path / "egress-work" / "channel-a" / "logs"
    channel_log_dir.mkdir(parents=True)
    (channel_log_dir / "ffmpeg.stderr.log").write_text(
        "frame=  120 fps=30 q=28.0 size=1024kB time=00:00:04.00 bitrate=2048kbits/s\n"
        "rtmp://ingest.example.com/live/super-secret-stream-key-abcdef\n"
        "error: could not connect, retrying\n",
        encoding="utf-8",
    )
    (channel_log_dir / "ffmpeg.stdout.log").write_text("encoder ready\n", encoding="utf-8")

    response = create_diagnostic_bundle(
        DiagnosticBundleRequest(operator_note=None),
        channel_ids=("channel-a",),
    )

    raw_bundle = Path(response.path).read_text(encoding="utf-8")
    # Real content made it in -- this isn't a bundle that silently dropped logs.
    assert "CivicCast service health recovered." in raw_bundle
    assert "frame=" in raw_bundle
    assert "encoder ready" in raw_bundle
    # But every secret-shaped value is gone, never just present-but-relabeled.
    assert "super-secret-nonce-value" not in raw_bundle
    assert "super-secret-bearer-token" not in raw_bundle
    assert "super-secret-stream-key-abcdef" not in raw_bundle

    parsed = json.loads(raw_bundle)
    assert "recent installer and per-channel egress logs" in " ".join(response.contains)
    assert parsed["logs"]["installer_bootstrap"]["path"] == str(bootstrap_log)
    assert "[redacted" in parsed["logs"]["installer_bootstrap"]["tail"]
    assert "channel-a" in parsed["logs"]["egress_channels"]
    assert "[redacted" in parsed["logs"]["egress_channels"]["channel-a"]["stderr"]


def test_support_bundle_omits_logs_section_when_no_log_files_exist(monkeypatch, tmp_path) -> None:
    # No installer bootstrap log, no egress channels -> logs section is simply
    # absent rather than a lie about what was collected.
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_SUPPORT_BUNDLE_DIR", str(tmp_path / "support"))
    monkeypatch.setenv("CIVICCAST_EGRESS_WORK_DIR", str(tmp_path / "egress-work"))
    monkeypatch.setenv("CIVICCAST_INSTALLER_BOOTSTRAP_LOG", str(tmp_path / "does-not-exist.log"))

    response = create_diagnostic_bundle(DiagnosticBundleRequest(operator_note=None))

    parsed = json.loads(Path(response.path).read_text(encoding="utf-8"))
    assert parsed["logs"] == {}
    assert not any("logs" in item for item in response.contains)


def test_acceptance_packet_endpoint_generates_redacted_packet(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_ACCEPTANCE_PACKET_DIR", str(tmp_path / "acceptance"))
    monkeypatch.setenv("CIVICCAST_YOUTUBE_CLIENT_SECRET", "super-youtube-secret")
    client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})

    response = client.post("/api/staff/installer/acceptance-packet")

    assert response.status_code == 200
    payload = response.json()
    assert payload["redacted"] is True
    assert payload["safe_to_broadcast"] in {"red", "yellow", "green"}
    packet_path = Path(payload["path"])
    assert packet_path.is_file()
    raw_packet = packet_path.read_text(encoding="utf-8")
    assert "super-youtube-secret" not in raw_packet
    parsed = json.loads(raw_packet)
    assert parsed["packet_id"] == payload["packet_id"]
    assert sha256(packet_path.read_bytes()).hexdigest() == payload["sha256"]


def test_acceptance_packet_endpoint_rejects_non_admin(monkeypatch) -> None:
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS", "limited-token:limited:Limited Operator:meeting_operator"
    )
    client = TestClient(create_app(), headers={"Authorization": "Bearer limited-token"})
    response = client.post("/api/staff/installer/acceptance-packet")
    assert response.status_code == 403


def test_create_acceptance_packet_service_matches_response_hash(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_ACCEPTANCE_PACKET_DIR", str(tmp_path / "acceptance"))

    response = create_acceptance_packet()

    packet_path = Path(response.path)
    assert packet_path.is_file()
    assert sha256(packet_path.read_bytes()).hexdigest() == response.sha256
