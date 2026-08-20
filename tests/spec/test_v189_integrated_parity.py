from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "verify_v189_integrated_parity.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_v189_integrated_parity", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_integrated_parity_contracts_pass_against_generated_openapi() -> None:
    module = _load_script()

    result = module.verify_integrated_parity(REPO_ROOT)

    assert result["status"] == "passed"
    assert result["gap_count"] == 10
    assert result["missing"] == {}


def test_integrated_parity_contracts_cover_all_required_groups() -> None:
    module = _load_script()

    assert set(module.REQUIRED_GROUPS) == {
        "app_platform",
        "cg_bulletin_board",
        "contributor_workflow",
        "gated_preroll_playback",
        "analytics_and_epg",
        "remote_ingest_relay",
        "broadcast_facility",
        "captions_and_overlays",
    }


def test_integrated_parity_script_reports_missing_contracts(tmp_path: Path) -> None:
    module = _load_script()
    docs = tmp_path / "docs"
    docs.mkdir()
    spec_dir = docs / "spec" / "2.0"
    spec_dir.mkdir(parents=True)
    (docs / "openapi.json").write_text('{"paths": {}}', encoding="utf-8")
    (spec_dir / "parity-evidence-matrix.json").write_text(
        '{"allowed_statuses": ["complete"], "gaps": []}',
        encoding="utf-8",
    )

    result = module.verify_integrated_parity(tmp_path)

    assert result["status"] == "failed"
    assert "app_platform" in result["missing"]
