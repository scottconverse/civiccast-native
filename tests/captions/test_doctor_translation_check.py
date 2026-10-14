# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""`civiccast doctor` must answer the question the caption job sends it.

When no translation model is available for selected Spanish captions, the
offline caption job records the issue on the row and points the operator to
"run 'civiccast doctor'". The report follows the station's completion choice:
reviewed English may already be attached in English-first mode.

These tests pin the report content, not the plumbing: the check resolves
through the same S13 ``AiModelService`` seam the worker's ``build_translator``
binds to, so doctor cannot report OK for a model the worker cannot load.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from civiccast.ai_models.models import AiModelAvailability, FeatureModelAvailability
from civiccast.captions.settings import RecordedCaptionSettings, RecordedCaptionSettingsStore
from civiccast.captions.vod_job import CAPTIONS_SPANISH_ENV_VAR
from civiccast.cli import _doctor_translation_lines


def _availability(
    *,
    runtime_reachable: bool | None,
    model_present: bool | None,
    detail: str,
) -> AiModelAvailability:
    return AiModelAvailability(
        features={
            "translation": FeatureModelAvailability(
                feature="translation",
                effective_model_key="translategemma-4b",
                band="local",
                requires_network=False,
                runtime_reachable=runtime_reachable,
                model_present=model_present,
                detail=detail,
            )
        }
    )


@pytest.fixture(autouse=True)
def stub_hardware_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the hardware-probe seam so the report test touches no real device.

    ``_doctor_translation_lines`` calls ``civiccast.platform.hardware.probe()``
    BEFORE it builds ``AiModelService``. On a restricted host that probe reads
    the filesystem's free space for ``Path.home()`` (``shutil.disk_usage`` ->
    ``nt._getdiskusage``), which can raise ``PermissionError`` and short-circuit
    the report into an UNKNOWN line before the availability stub is ever
    consulted. This fixture substitutes a realistic synthetic ``HardwareProbe``
    at the exact seam the CLI imports, so the report-content assertions exercise
    the real report logic -- not the host's disk/NVML access. Product behavior
    is unchanged; nothing is skipped or weakened.
    """

    from civiccast.platform import hardware as hardware_module

    synthetic = hardware_module.HardwareProbe(
        cpu=hardware_module.CPUInfo(cores_physical=8, cores_logical=16, brand="Synthetic test CPU"),
        ram=hardware_module.RAMInfo(total_gb=32.0, available_gb=16.0),
        disk=hardware_module.DiskInfo(path=str(Path.home()), total_gb=1000, free_gb=500),
        gpu=None,
        os=hardware_module.OSContext(
            kind="windows",
            system="Windows",
            release="test",
            machine="AMD64",
            hostname="test-host",
        ),
        recommended_tier="tier-0",
        civiccast_version="0.0.0-test",
    )
    monkeypatch.setattr(hardware_module, "probe", lambda *a, **k: synthetic, raising=True)


@pytest.fixture()
def stub_availability(monkeypatch: pytest.MonkeyPatch):
    """Patch the service the check builds, leaving the report logic real."""

    def _install(availability: AiModelAvailability | Exception) -> None:
        class _Service:
            def get_availability(self) -> AiModelAvailability:
                if isinstance(availability, Exception):
                    raise availability
                return availability

        import civiccast.ai_models.service as service_module

        monkeypatch.setattr(
            service_module, "AiModelService", lambda *a, **k: _Service(), raising=True
        )

    return _install


class TestDoctorTranslationReport:
    def test_a_missing_model_is_reported_as_not_available_with_the_consequence(
        self, monkeypatch: pytest.MonkeyPatch, stub_availability
    ) -> None:
        monkeypatch.delenv(CAPTIONS_SPANISH_ENV_VAR, raising=False)
        stub_availability(
            _availability(
                runtime_reachable=True,
                model_present=False,
                detail="Model translategemma-4b is not installed in the local runtime.",
            )
        )

        report = "\n".join(_doctor_translation_lines())

        assert "translategemma-4b" in report
        assert "NOT AVAILABLE" in report
        assert "not installed" in report
        assert "selected Spanish track is not ready" in report
        assert "does not attach the selected tracks" in report
        assert "Settings > AI Models > Translation" in report

    def test_english_reviewed_setting_explains_english_can_attach_first(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stub_availability
    ) -> None:
        monkeypatch.delenv(CAPTIONS_SPANISH_ENV_VAR, raising=False)
        monkeypatch.delenv("CIVICCAST_OFFLINE_CAPTION_JOB", raising=False)
        state_path = tmp_path / "station-state.json"
        monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(state_path))
        RecordedCaptionSettingsStore(state_path.with_name("offline-caption-settings.json")).save(
            RecordedCaptionSettings(completion_requirement="english_reviewed")
        )
        stub_availability(
            _availability(
                runtime_reachable=False,
                model_present=False,
                detail="Translation model is not available.",
            )
        )

        report = "\n".join(_doctor_translation_lines())

        assert "Reviewed English can attach after its review" in report
        assert "Spanish remains in progress" in report

    def test_an_unreachable_runtime_is_also_not_available(
        self, monkeypatch: pytest.MonkeyPatch, stub_availability
    ) -> None:
        monkeypatch.delenv(CAPTIONS_SPANISH_ENV_VAR, raising=False)
        stub_availability(
            _availability(
                runtime_reachable=False,
                model_present=None,
                detail="The local AI runtime is not reachable.",
            )
        )

        report = "\n".join(_doctor_translation_lines())

        assert "NOT AVAILABLE" in report
        assert "not reachable" in report

    def test_a_working_model_reports_ok(
        self, monkeypatch: pytest.MonkeyPatch, stub_availability
    ) -> None:
        monkeypatch.delenv(CAPTIONS_SPANISH_ENV_VAR, raising=False)
        stub_availability(
            _availability(
                runtime_reachable=True,
                model_present=True,
                detail="Local model present and the runtime is reachable.",
            )
        )

        report = "\n".join(_doctor_translation_lines())

        assert "status:            OK" in report
        assert "NOT AVAILABLE" not in report

    def test_an_unreadable_model_setting_says_unknown_not_ok(
        self, monkeypatch: pytest.MonkeyPatch, stub_availability
    ) -> None:
        """Never a false green: an unreadable source is UNKNOWN, not OK."""

        monkeypatch.delenv(CAPTIONS_SPANISH_ENV_VAR, raising=False)
        stub_availability(RuntimeError("database is locked"))

        report = "\n".join(_doctor_translation_lines())

        assert "UNKNOWN" in report
        assert "database is locked" in report
        assert "OK" not in report.replace("could not", "")

    def test_legacy_spanish_default_points_to_station_settings(
        self, monkeypatch: pytest.MonkeyPatch, stub_availability
    ) -> None:
        """Explain that the environment value is only an initial default."""

        monkeypatch.setenv(CAPTIONS_SPANISH_ENV_VAR, "off")
        stub_availability(
            _availability(
                runtime_reachable=True,
                model_present=True,
                detail="Local model present and the runtime is reachable.",
            )
        )

        report = "\n".join(_doctor_translation_lines())

        assert CAPTIONS_SPANISH_ENV_VAR in report
        assert "initial Spanish-language setting" in report
        assert "Setup > Station Profile" in report
