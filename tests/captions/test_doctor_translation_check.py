# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""`civiccast doctor` must answer the question the caption job sends it.

When no translation model is available, the offline caption job holds the
recording and puts a remediation on the row telling the operator to "run
'civiccast doctor'". Doctor printed nothing at all about translation, so an
operator who followed that instruction got a screen with no mention of the
broken thing -- a remediation that points at a dead end is worse than none,
because it costs the operator the trip.

These tests pin the report content, not the plumbing: the check resolves
through the same S13 ``AiModelService`` seam the worker's ``build_translator``
binds to, so doctor cannot report OK for a model the worker cannot load.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from civiccast.ai_models.models import AiModelAvailability, FeatureModelAvailability
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
        # The operator must learn what happens to recordings, not just that a
        # model is missing -- and specifically that they are HELD, because the
        # obvious wrong guess is "it publishes English only".
        assert "HELD" in report
        assert "English only" in report
        assert "Settings > AI Models > Translation" in report

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

    def test_the_retired_spanish_switch_is_called_out(
        self, monkeypatch: pytest.MonkeyPatch, stub_availability
    ) -> None:
        """A station carrying the retired switch will not start; say so here.

        An operator whose station refuses to boot runs doctor to find out
        why, so the retired variable has to be named on this screen and not
        only in the startup error.
        """

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
        assert "retired" in report
        assert "Remove it" in report
