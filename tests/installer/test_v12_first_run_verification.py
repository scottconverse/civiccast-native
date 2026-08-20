# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for v1.2 first-run fail-closed verification gates."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from civiccast.installer.model_bundle import (
    BundleModel,
    V11ModelBundleManifest,
    verify_airgapped_install,
)
from civiccast.installer.service import run_first_health_check


class TestFirstRunVerificationFailsClosed:
    def test_external_lanes_do_not_report_ok_when_credentials_or_hardware_are_missing(
        self,
        monkeypatch,
    ) -> None:
        for key in (
            "CIVICCAST_PORTAL_TOKEN",
            "CIVICCAST_INTERNET_ARCHIVE_ACCESS_KEY",
            "CIVICCAST_YOUTUBE_CLIENT_SECRET",
            "CIVICCAST_NAS_ARCHIVE_PATH",
            "CIVICCAST_SUBSCRIBER_WEBHOOK_SECRET",
        ):
            monkeypatch.delenv(key, raising=False)

        report = run_first_health_check(profile="public-meetings")
        checked = {check.id: check for check in report.checks}

        for check_id in (
            "portal",
            "internet-archive",
            "youtube",
            "local-nas",
            "subscriber-notifications",
        ):
            assert checked[check_id].state in {
                "credential_or_secret_required",
                "hardware_required",
                "failed",
            }
            action = checked[check_id].next_step.lower()
            assert any(word in action for word in ("set ", "configure", "connect", "provide"))

        assert report.ready is False

    def test_placeholder_external_credentials_do_not_turn_first_run_ready(
        self,
        monkeypatch,
    ) -> None:
        monkeypatch.setenv("CIVICCAST_PORTAL_TOKEN", "placeholder-token")
        monkeypatch.setenv("CIVICCAST_INTERNET_ARCHIVE_ACCESS_KEY", "placeholder-ia-key")
        monkeypatch.setenv("CIVICCAST_YOUTUBE_CLIENT_SECRET", "placeholder-youtube-secret")
        monkeypatch.setenv("CIVICCAST_NAS_ARCHIVE_PATH", "Z:/definitely-not-present-civiccast")
        monkeypatch.setenv("CIVICCAST_SUBSCRIBER_WEBHOOK_SECRET", "placeholder-webhook-secret")

        report = run_first_health_check(profile="public-meetings")
        checked = {check.id: check for check in report.checks}

        assert report.ready is False
        for check_id in (
            "portal",
            "internet-archive",
            "youtube",
            "subscriber-notifications",
        ):
            assert checked[check_id].state == "credential_or_secret_required"
            assert "verification" in checked[check_id].next_step.lower()
            assert "ok" not in checked[check_id].message.lower()
        assert checked["local-nas"].state == "failed"
        assert "reachable directory" in checked["local-nas"].message

    def test_local_nas_reports_ok_only_after_real_write_hash_delete_probe(
        self,
        monkeypatch,
        tmp_path,
    ) -> None:
        monkeypatch.setenv("CIVICCAST_NAS_ARCHIVE_PATH", str(tmp_path))

        report = run_first_health_check(profile="public-meetings")
        checked = {check.id: check for check in report.checks}

        assert checked["local-nas"].state == "ok"
        assert "write/read/delete hash probe" in checked["local-nas"].message
        assert not list(tmp_path.glob(".civiccast-first-run-*.probe"))
        assert report.ready is False

    def test_local_nas_delete_failure_does_not_report_ok(
        self,
        monkeypatch,
        tmp_path,
    ) -> None:
        monkeypatch.setenv("CIVICCAST_NAS_ARCHIVE_PATH", str(tmp_path))
        original_unlink = Path.unlink

        def fail_probe_unlink(path: Path, *args, **kwargs) -> None:
            if path.name.startswith(".civiccast-first-run-"):
                raise OSError("simulated NAS delete lock")
            original_unlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", fail_probe_unlink)

        report = run_first_health_check(profile="public-meetings")
        checked = {check.id: check for check in report.checks}

        assert report.ready is False
        assert checked["local-nas"].state == "failed"
        assert "could not delete" in checked["local-nas"].message
        assert "permissions" in checked["local-nas"].next_step
        assert list(tmp_path.glob(".civiccast-first-run-*.probe"))

    def test_deterministic_mock_proof_is_not_reported_as_real_provider_proof(self) -> None:
        report = run_first_health_check(profile="public-meetings")

        forbidden_phrases = ("proof adapter accepted", "local adapters", "proof can")
        for check in report.checks:
            text = f"{check.message} {check.next_step}".lower()
            assert not any(phrase in text for phrase in forbidden_phrases)


class TestOfflineBundleRealHashPreserved:
    def test_real_model_file_hash_is_reported_from_file_bytes(self, tmp_path) -> None:
        model_path = tmp_path / "tiny-model.bin"
        model_bytes = b"v1.2 hardening fixture model bytes"
        model_path.write_bytes(model_bytes)
        expected_hash = sha256(model_bytes).hexdigest()
        manifest = V11ModelBundleManifest(
            output_dir=tmp_path,
            models=(
                BundleModel(
                    name="tiny-model",
                    filename=model_path.name,
                    source="local-fixture",
                    license="Apache-2.0",
                    size_bytes=len(model_bytes),
                    sha256=expected_hash,
                ),
            ),
        )

        result = verify_airgapped_install(
            bundle_dir=tmp_path,
            network_allowed=False,
            manifest=manifest,
        )

        assert result.status == "ok"
        assert expected_hash in result.operator_action

    def test_missing_model_file_failure_names_the_file_and_next_operator_action(
        self,
        tmp_path,
    ) -> None:
        manifest = V11ModelBundleManifest(
            output_dir=tmp_path,
            models=(
                BundleModel(
                    name="missing-model",
                    filename="missing-model.bin",
                    source="local-fixture",
                    license="Apache-2.0",
                    size_bytes=10,
                    sha256="0" * 64,
                ),
            ),
        )

        result = verify_airgapped_install(
            bundle_dir=tmp_path,
            network_allowed=False,
            manifest=manifest,
        )

        assert result.status == "failed"
        assert "missing-model.bin" in result.operator_action
        assert "copy" in result.operator_action.lower()
