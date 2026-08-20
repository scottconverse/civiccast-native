# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Cross-language pin: the native (Rust) hardware inventory's caption-tier
recommendation must AGREE with ``civiccast.platform.hardware``'s
``_tier_for`` decision tree -- it is a mirror, never a rival (see
``civiccast/apps/installer/src-tauri/src/hardware_inventory.rs``'s module
doc comment for the full rationale, including the documented NVIDIA-only
divergence).

Following the existing cross-language pin style in
``tests/policy/test_native_installer_identity.py`` (e.g.
``test_app_payload_component_identity_matches_across_python_and_rust``,
``test_d3_exit_code_contract_cross_checked_between_python_engine_and_nsis_hook``):
read BOTH source files as text, extract the real literals with a regex
(never hand-retype a "believed" value), and assert equality bidirectionally
-- so a threshold change on EITHER side that is not mirrored on the other
fails this test.

``civiccast/platform/hardware.py`` is READ-ONLY authority here: this test
must never edit it, only parse its existing ``_tier_for`` literals.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARDWARE_PY = ROOT / "civiccast" / "platform" / "hardware.py"
CAPTION_TIERS_PY = ROOT / "civiccast" / "native" / "caption_tiers.py"
INSTALLER = ROOT / "civiccast" / "apps" / "installer" / "src-tauri"
HARDWARE_INVENTORY_RS = INSTALLER / "src" / "hardware_inventory.rs"
NATIVE_PACKS_RS = INSTALLER / "src" / "native_packs.rs"
MAIN_RS = INSTALLER / "src" / "main.rs"
TYPES_TS = ROOT / "civiccast" / "apps" / "installer" / "src" / "types.ts"


def test_hardware_inventory_rs_exists() -> None:
    assert HARDWARE_INVENTORY_RS.is_file(), f"missing {HARDWARE_INVENTORY_RS}"


def _python_tier_thresholds() -> tuple[int, int, int]:
    """Parse the three VRAM-GB integer literals out of hardware.py's
    ``_tier_for`` (the ``< 8`` / ``< 16`` / ``< 24`` comparisons), in the
    order they appear -- never hand-retyped."""
    source = HARDWARE_PY.read_text(encoding="utf-8")
    assert "def _tier_for(" in source, f"expected _tier_for in {HARDWARE_PY}"
    body = source[source.index("def _tier_for(") :]
    thresholds = [int(value) for value in re.findall(r"vram_total_gb\s*<\s*(\d+)", body)]
    assert len(thresholds) == 3, (
        f"expected exactly 3 VRAM threshold comparisons in hardware.py's _tier_for, "
        f"found {thresholds} -- hardware.py's decision tree shape changed; update this "
        "parser deliberately, don't just make it pass"
    )
    return thresholds[0], thresholds[1], thresholds[2]


def _python_tier_ids_in_order() -> list[str]:
    source = HARDWARE_PY.read_text(encoding="utf-8")
    body = source[source.index("def _tier_for(") :]
    tier_ids = re.findall(r'return\s+"([\w-]+)"', body)
    assert tier_ids == ["tier-0", "tier-1", "tier-1-plus", "tier-2"], (
        f"hardware.py's _tier_for tier ids changed shape: {tier_ids}"
    )
    return tier_ids


def _rust_tier_thresholds() -> tuple[int, int, int]:
    source = HARDWARE_INVENTORY_RS.read_text(encoding="utf-8")
    tier0 = re.search(r"HARDWARE_TIER_VRAM_GB_TIER0_MAX:\s*u64\s*=\s*(\d+);", source)
    tier1 = re.search(r"HARDWARE_TIER_VRAM_GB_TIER1_MAX:\s*u64\s*=\s*(\d+);", source)
    tier1plus = re.search(r"HARDWARE_TIER_VRAM_GB_TIER1_PLUS_MAX:\s*u64\s*=\s*(\d+);", source)
    assert tier0 and tier1 and tier1plus, (
        "hardware_inventory.rs is missing one of the three pinned "
        "HARDWARE_TIER_VRAM_GB_* threshold constants"
    )
    return int(tier0.group(1)), int(tier1.group(1)), int(tier1plus.group(1))


def test_caption_tier_recommendation_vram_thresholds_match_hardware_py_bidirectionally() -> None:
    """The defect this guards against: hardware_inventory.rs's Rust
    thresholds silently drifting from hardware.py's (or vice versa) --
    either direction would make the Rust-recommended caption tier disagree
    with what `civiccast doctor` / the `/api/hardware` endpoint would
    independently compute for the same GPU."""
    python_thresholds = _python_tier_thresholds()
    rust_thresholds = _rust_tier_thresholds()
    assert rust_thresholds == python_thresholds, (
        "hardware_inventory.rs's pinned VRAM-GB thresholds "
        f"{rust_thresholds} must equal hardware.py's `_tier_for` thresholds "
        f"{python_thresholds} (civiccast/platform/hardware.py:351,353,355) -- "
        "the Rust module mirrors, never re-derives, the Python authority"
    )


def test_hardware_py_tier_id_ladder_shape_is_the_one_the_rust_mirror_assumes() -> None:
    """Pins hardware.py's own tier-id ladder shape (tier-0/1/1-plus/2, in that
    order) so a restructure there is caught even though only the tier-0
    boundary currently feeds the caption-tier recommendation."""
    assert _python_tier_ids_in_order() == ["tier-0", "tier-1", "tier-1-plus", "tier-2"]


def test_caption_tier_ids_used_by_hardware_inventory_match_python_registry() -> None:
    """hardware_inventory.rs imports FLOOR_TIER_ID/LARGE_V3_TIER_ID from
    native_packs.rs rather than re-declaring its own string literals (single
    source of truth within the Rust side); this test closes the loop by
    checking THAT Rust source against the Python registry's own tier ids."""
    hardware_inventory_source = HARDWARE_INVENTORY_RS.read_text(encoding="utf-8")
    native_packs_source = NATIVE_PACKS_RS.read_text(encoding="utf-8")
    caption_tiers_source = CAPTION_TIERS_PY.read_text(encoding="utf-8")

    assert (
        "use crate::native_packs::{FLOOR_TIER_ID, LARGE_V3_TIER_ID};" in hardware_inventory_source
    ), "hardware_inventory.rs must import the tier ids, never re-declare its own copies"

    assert 'pub(crate) const LARGE_V3_TIER_ID: &str = "large-v3";' in native_packs_source
    assert 'pub(crate) const FLOOR_TIER_ID: &str = "floor";' in native_packs_source
    assert 'LARGE_V3_TIER_ID: Final[str] = "large-v3"' in caption_tiers_source
    assert 'FLOOR_TIER_ID: Final[str] = "floor"' in caption_tiers_source


def test_native_hardware_inventory_tauri_command_is_registered() -> None:
    main_source = MAIN_RS.read_text(encoding="utf-8")
    assert "mod hardware_inventory;" in main_source
    assert "async fn native_hardware_inventory(" in main_source
    handler = main_source[main_source.index("invoke_handler(tauri::generate_handler![") :].split(
        "])", 1
    )[0]
    assert "native_hardware_inventory" in handler, (
        "native_hardware_inventory must be registered in the Tauri invoke_handler "
        "list, not just defined"
    )


def test_native_hardware_inventory_json_shape_matches_the_typescript_contract() -> None:
    """Field-name/casing agreement between the Rust struct (serde default
    snake_case -- no rename_all on this command) and the TypeScript
    interface the frontend actually consumes."""
    rust_source = HARDWARE_INVENTORY_RS.read_text(encoding="utf-8")
    types_source = TYPES_TS.read_text(encoding="utf-8")

    struct_body = rust_source[rust_source.index("pub struct HardwareInventory {") :].split("}", 1)[
        0
    ]
    ts_body = types_source[
        types_source.index("export interface NativeHardwareInventory {") :
    ].split("}", 1)[0]

    for field in (
        "cpu_model",
        "physical_cores",
        "logical_cores",
        "ram_gb",
        "gpus",
        "free_disk_bytes",
        "install_target",
        "recommended_caption_tier",
        "hardware_capable_caption_tier",
    ):
        assert field in struct_body, f"expected {field!r} on the Rust HardwareInventory struct"
        assert field in ts_body, (
            f"expected {field!r} on the TypeScript NativeHardwareInventory interface"
        )

    gpu_struct_body = rust_source[rust_source.index("pub struct GpuFacts {") :].split("}", 1)[0]
    # PIN FOLLOWED THE MERGE (5d19ee34): the UX slice's duplicate GPU shape was
    # collapsed onto ONE declaration -- NativeGpuFacts is now an alias of
    # HardwareGpu, so the field list lives on the HardwareGpu interface and the
    # alias line is asserted separately so the native name can't silently drift
    # to a third shape.
    assert "export type NativeGpuFacts = HardwareGpu;" in types_source, (
        "NativeGpuFacts must remain an alias of the single HardwareGpu shape"
    )
    gpu_ts_body = types_source[types_source.index("export interface HardwareGpu {") :].split(
        "}", 1
    )[0]
    for field in ("name", "dedicated_vram_mb", "vendor"):
        assert field in gpu_struct_body
        assert field in gpu_ts_body


# ---------------------------------------------------------------------------
# G011.1: no fabricated hardware numbers survive anywhere in this contract
# ---------------------------------------------------------------------------

COMPONENTS_CATALOG_TS = ROOT / "civiccast" / "apps" / "installer" / "src" / "components-catalog.ts"
ACQUISITION_CATALOG_RS = INSTALLER / "src" / "acquisition_catalog.rs"
API_TS = ROOT / "civiccast" / "apps" / "installer" / "src" / "api.ts"


def _without_comments(typescript_source: str) -> str:
    """``typescript_source`` with ``/* ... */`` and ``// ...`` comments removed.

    Needed because these tests assert the ABSENCE of removed identifiers, and
    the surviving doc comments deliberately name them while explaining the
    defect they replaced. Deliberately naive (it does not model strings
    containing comment markers) -- adequate for absence checks over this one
    file, and it can only ever make the assertions stricter, never weaker.
    """
    without_block = re.sub(r"/\*.*?\*/", "", typescript_source, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", without_block)


def test_every_measured_inventory_field_can_report_unavailable_on_both_sides() -> None:
    """The probe must be ABLE to say "I could not get this".

    Before G011.1 no field could: the Rust collectors each had a fabricated
    fallback (``0`` free bytes, ``0.0`` GB of RAM, an ``"unknown CPU
    (registry read failed)"`` sentinel printed verbatim as the processor, and
    an empty GPU list indistinguishable from "no dedicated GPU"), and the
    frontend's ``fetchHardwareInventory`` substituted a whole fabricated
    machine on any failure. This pins the shape that makes those
    unrepresentable, on both sides of the wire at once.
    """
    rust_source = HARDWARE_INVENTORY_RS.read_text(encoding="utf-8")
    types_source = TYPES_TS.read_text(encoding="utf-8")

    struct_body = rust_source[rust_source.index("pub struct HardwareInventory {") :].split("}", 1)[
        0
    ]
    ts_body = types_source[
        types_source.index("export interface NativeHardwareInventory {") :
    ].split("}", 1)[0]

    measured_fields = {
        "cpu_model": ("Option<String>", "string | null"),
        "physical_cores": ("Option<u32>", "number | null"),
        "logical_cores": ("Option<u32>", "number | null"),
        "ram_gb": ("Option<f64>", "number | null"),
        "gpus": ("Option<Vec<GpuFacts>>", "NativeGpuFacts[] | null"),
        "free_disk_bytes": ("Option<u64>", "number | null"),
        "install_target": ("Option<String>", "string | null"),
    }
    for field, (rust_type, ts_type) in measured_fields.items():
        assert f"pub {field}: {rust_type}," in struct_body, (
            f"{field} must be {rust_type} on the Rust side so an unobtainable "
            "value is reported as unavailable, never as a fabricated number"
        )
        assert f"{field}: {ts_type};" in ts_body, (
            f"{field} must be `{ts_type}` on the TypeScript side to match"
        )


def test_the_frontend_has_no_hardware_inventory_mock_left_to_substitute() -> None:
    """``fetchHardwareInventory``'s ``catch { return hardwareInventoryMock; }``
    is what put "Generic x86_64 CPU / 16 GB / 120 GB free" on screen under the
    heading "Here is what CivicCast found on this computer" whenever the
    native command could not be reached -- including the Tauri-ACL denial
    chain A-min found in the field."""
    api_source = API_TS.read_text(encoding="utf-8")
    # Comments legitimately NAME the removed mock (the doc comment on
    # HardwareProbeResult explains the defect it replaced), so the check is
    # against executable code only.
    code = _without_comments(api_source)
    assert "hardwareInventoryMock" not in code
    assert "Generic x86_64 CPU" not in code
    assert "free_disk_gb" not in code, (
        "free_disk_gb is the old whole-GB field; the honest contract is free_disk_bytes"
    )
    # The probe result must be a typed either/or, so a caller cannot silently
    # treat a failure as an inventory.
    assert "export type HardwareProbeResult" in api_source
    assert "{ ok: false; message: string }" in api_source


def _rust_production_catalog_ids() -> list[str]:
    source = ACQUISITION_CATALOG_RS.read_text(encoding="utf-8")
    match = re.search(
        r"pub const PRODUCTION_CATALOG_IDS:\s*\[&str;\s*\d+\]\s*=\s*\[(?P<body>[^\]]*)\];",
        source,
        re.DOTALL,
    )
    assert match is not None, f"no PRODUCTION_CATALOG_IDS array found in {ACQUISITION_CATALOG_RS}"
    return re.findall(r'"([\w_]+)"', match.group("body"))


def _typescript_deliverable_component_ids() -> list[str]:
    """Every ``COMPONENT_CATALOG`` entry whose ``deliverable`` flag is true,
    parsed out of the real source rather than hand-retyped."""
    source = COMPONENTS_CATALOG_TS.read_text(encoding="utf-8")
    body = source[source.index("export const COMPONENT_CATALOG") :]
    entries = re.findall(r'id:\s*"([\w_]+)",.*?deliverable:\s*(true|false)', body, re.DOTALL)
    assert entries, (
        f"no catalog entries with a deliverable flag parsed from {COMPONENTS_CATALOG_TS}"
    )
    return [component_id for component_id, flag in entries if flag == "true"]


def test_frontend_deliverable_components_match_the_rust_production_catalog_exactly() -> None:
    """The defect this closes (G011.1): the frontend pre-selected
    ``captions_large`` on any large-v3-capable box, but ``captions_large`` is
    not in ``production_catalog()`` -- so the downloading screen showed a row
    ``main.rs``'s ``run_production_acquisition`` would never drive. It sat on
    "Waiting" forever and ``allDone`` never became true, on exactly the
    capable hardware the recommendation was congratulating.

    Bidirectional: enrolling a component on either side without the other
    fails here.
    """
    rust_ids = sorted(_rust_production_catalog_ids())
    ts_ids = sorted(_typescript_deliverable_component_ids())
    assert ts_ids == rust_ids, (
        f"components-catalog.ts's deliverable set {ts_ids} must equal "
        f"acquisition_catalog.rs's PRODUCTION_CATALOG_IDS {rust_ids}"
    )


def test_the_recommended_caption_tier_is_derived_from_the_production_catalog() -> None:
    """``recommend_caption_tier`` must clamp to an OBTAINABLE tier, and must
    derive obtainability from ``PRODUCTION_CATALOG_IDS`` rather than from a
    second hand-maintained list that could drift from it."""
    source = HARDWARE_INVENTORY_RS.read_text(encoding="utf-8")
    assert "pub fn caption_tier_is_obtainable(" in source
    assert "crate::acquisition_catalog::PRODUCTION_CATALOG_IDS" in source, (
        "obtainability must be derived from the production catalog itself"
    )
    assert "pub fn hardware_capable_caption_tier(" in source, (
        "the hardware's real capability must still be reported separately, so the "
        "screen can explain an unobtainable tier instead of implying the GPU was "
        "not good enough"
    )
