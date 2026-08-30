# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S13 first-run: the adaptive summary default is computed at commissioning and
persisted to the station-state JSON (the seed), with an operator override slot.

S3 §3 locks the venue: commissioning state lives in station-state JSON (no DB table),
so the *seed* of the adaptive default rides station-state while the operator's durable
runtime *selection* lives in the 0053 DB migration. ``effective_model_key`` (slice 1)
already encodes override-else-default, so no new resolution logic is invented here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from civiccast.installer.station_state import (
    read_ai_model_seed,
    seed_ai_model_default,
    set_ai_model_override,
    station_state_path,
)


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))


def test_seed_uses_12b_on_a_16gb_box_with_a_real_gpu() -> None:
    seed = seed_ai_model_default(system_ram_total_gb=16, has_gpu=True)

    assert seed.summary.adaptive_default_key == "gemma4-12b-ollama"
    assert seed.summary.operator_override_key is None
    assert seed.summary.detected_ram_gb == 16
    assert seed.summary.effective_key == "gemma4-12b-ollama"


def test_seed_falls_back_to_e4b_below_16gb() -> None:
    seed = seed_ai_model_default(system_ram_total_gb=8)

    assert seed.summary.adaptive_default_key == "gemma4-e4b-ollama"
    assert seed.summary.effective_key == "gemma4-e4b-ollama"


def test_boundary_just_under_16gb_picks_e4b() -> None:
    # A float just under 16 (15.9 GB box) must coerce DOWN to 15 -> e4b, never 12B.
    seed = seed_ai_model_default(system_ram_total_gb=15, has_gpu=True)
    assert seed.summary.adaptive_default_key == "gemma4-e4b-ollama"


def test_seed_uses_e4b_on_a_cpu_only_32gb_box() -> None:
    """Field evidence 2026-08-29 (candidate #17): a 32GB CPU-only reference station
    must seed e4b, not 12B -- 12B took 366s to complete a summary there once and
    then failed twice more under realistic memory pressure; e4b completed every
    attempt (94-128s). ``has_gpu`` defaults False, so this is the default call shape
    for any RAM figure absent a detected GPU."""
    seed = seed_ai_model_default(system_ram_total_gb=32)

    assert seed.summary.adaptive_default_key == "gemma4-e4b-ollama"
    assert seed.summary.detected_ram_gb == 32
    assert seed.summary.effective_key == "gemma4-e4b-ollama"


def test_seed_is_persisted_to_station_state_json() -> None:
    seed_ai_model_default(system_ram_total_gb=16, has_gpu=True)

    raw = json.loads(station_state_path().read_text(encoding="utf-8"))
    assert raw["ai_models"]["summary"]["adaptive_default_key"] == "gemma4-12b-ollama"
    assert raw["ai_models"]["summary"]["operator_override_key"] is None
    assert raw["ai_models"]["summary"]["detected_ram_gb"] == 16
    assert "seeded_at" in raw["ai_models"]["summary"]


def test_read_seed_returns_none_before_commissioning() -> None:
    assert read_ai_model_seed() is None


def test_read_seed_round_trips_after_seeding() -> None:
    seed_ai_model_default(system_ram_total_gb=8)
    loaded = read_ai_model_seed()
    assert loaded is not None
    assert loaded.summary.adaptive_default_key == "gemma4-e4b-ollama"


def test_seed_preserves_existing_state_blocks() -> None:
    # commissioning writes the admin/station blocks first; seeding must not clobber them.
    path = station_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"setup_complete": True, "station": {"x": 1}}), encoding="utf-8")

    seed_ai_model_default(system_ram_total_gb=16, has_gpu=True)

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["setup_complete"] is True
    assert raw["station"] == {"x": 1}
    assert raw["ai_models"]["summary"]["adaptive_default_key"] == "gemma4-12b-ollama"


def test_override_takes_precedence_in_effective_key() -> None:
    seed_ai_model_default(system_ram_total_gb=16, has_gpu=True)
    updated = set_ai_model_override("summary", "gemma4-31b-cloud")

    assert updated.summary.operator_override_key == "gemma4-31b-cloud"
    # the adaptive default is unchanged; only the effective key follows the override
    assert updated.summary.adaptive_default_key == "gemma4-12b-ollama"
    assert updated.summary.effective_key == "gemma4-31b-cloud"

    # and it is durably persisted
    raw = json.loads(station_state_path().read_text(encoding="utf-8"))
    assert raw["ai_models"]["summary"]["operator_override_key"] == "gemma4-31b-cloud"


def test_clearing_override_returns_to_adaptive_default() -> None:
    seed_ai_model_default(system_ram_total_gb=16, has_gpu=True)
    set_ai_model_override("summary", "gemma4-31b-cloud")
    cleared = set_ai_model_override("summary", None)

    assert cleared.summary.operator_override_key is None
    assert cleared.summary.effective_key == "gemma4-12b-ollama"


def test_override_before_seed_is_an_error() -> None:
    with pytest.raises(ValueError, match="not seeded"):
        set_ai_model_override("summary", "gemma4-e4b-ollama")


def test_override_rejects_unknown_feature() -> None:
    seed_ai_model_default(system_ram_total_gb=16, has_gpu=True)
    with pytest.raises(ValueError, match="feature"):
        set_ai_model_override("captions", "whisper-large-v3-faster")


def test_commissioning_seeds_the_adaptive_default_from_the_live_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # complete_first_admin_setup must write the AI-model seed using the box's real RAM,
    # coercing the probed float DOWN to an int (15.9 -> 15 -> e4b).
    import civiccast.installer.service as service
    from civiccast.installer.models import FirstAdminSetupRequest
    from civiccast.platform import hardware

    class _Ram:
        total_gb = 15.9

    class _Probe:
        ram = _Ram()

    monkeypatch.setattr(hardware, "probe", lambda *a, **k: _Probe())
    monkeypatch.setenv("CIVICCAST_OPERATOR_CONSOLE_URL", "http://127.0.0.1:5173")

    service.complete_first_admin_setup(
        FirstAdminSetupRequest(
            station_name="Pinegrove School Board",
            admin_display_name="Avery Admin",
            admin_username="avery",
            admin_password="correct horse battery staple",
            recovery_kit_destination="safe",
        )
    )

    seed = read_ai_model_seed()
    assert seed is not None
    assert seed.summary.detected_ram_gb == 15
    assert seed.summary.adaptive_default_key == "gemma4-e4b-ollama"
