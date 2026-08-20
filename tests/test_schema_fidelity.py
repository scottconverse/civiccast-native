# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""TEST-006 (audit-team v0.3.0) -- Pydantic schema fidelity.

The Playwright e2e specs at ``civiccast/apps/portal-operator/e2e/*.spec.ts``
declare ``MOCK_ASSET`` literals that the backend route mocks fulfill on
behalf of the live FastAPI service. The mocks are JSON literals, hand-
mirrored from the Pydantic ``StaffAssetRow`` shape. They aren't generated
from the schema, and they aren't asserted against it.

Without an explicit contract test, a future PR adding (say)
``retention_grace_period_days: int | None`` to ``StaffAssetRow`` would
leave the mocks unchanged. The Playwright tests would continue passing.
The new field would arrive in the real product unrendered. This is the
``types/schedule.ts``-style drift the audit's TEST-003 already flagged.

This module locks the keyset: every key in every ``MOCK_ASSET`` literal
must appear in ``StaffAssetRow``'s JSON schema, and every required field
in the JSON schema must appear in every ``MOCK_ASSET`` literal (modulo
defaulted fields, see below).

The full audit-team v0.3.0 fix path (TEST-006 row): "Add a pytest test
that loads the spec files as text, regex-extracts the ``MOCK_ASSET =
{ ... }`` literal, parses it, and asserts the keyset equals
``set(StaffAssetRow.model_json_schema()["properties"].keys())``. Cheap,
catches the next drift."
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from civiccast.schedule.models import StaffAssetRow

REPO_ROOT = Path(__file__).resolve().parents[1]
PLAYWRIGHT_SPECS_DIR = REPO_ROOT / "civiccast" / "apps" / "portal-operator" / "e2e"

# Known pre-existing drift the v0.3-era MOCK_ASSET literals predate but
# that Slice 1's "no frontend work" forbidden_paths posture cannot
# touch. Slice 2 (Operator Live Room) opens the frontend lane and is
# responsible for refreshing these mocks to include the missing fields.
# When Slice 2 fixes them, REMOVE the corresponding entries here -- the
# whitelist's job is to surface fields that THIS commit is letting slide
# so a future agent can find them.
#
# Two pending drift fields as of Slice 1 Commit 9:
#   * version -- added to StaffAssetRow in v0.3 (audit-team v0.3.0
#     QA-008 OCC). The MOCK_ASSET literals were authored at v0.3 task 5
#     before QA-008 closure and were never refreshed.
#   * source_live_session_id -- added in Slice 1 Commit 7 (ADR 0011
#     recording finalization). The MOCK_ASSET literals are upload-
#     derived assets, so the field should be null there; the value is
#     trivial. Missing the KEY is what the test catches.
# Audit TEST-007: the whitelist went stale (every mock now carries both
# keys), which silently weakened the guard - REMOVAL of either key from a
# mock went undetected while exempted. Empty on purpose; add entries only
# with a dated removal plan.
_KNOWN_DRIFT_TO_BE_FIXED_IN_SLICE_2: frozenset[str] = frozenset()


def _extract_mock_asset_literal(spec_path: Path) -> dict[str, object]:
    """Extract the ``MOCK_ASSET = { ... } as const`` literal from a
    Playwright spec file.

    Reads the source as text (no TypeScript parser), regex-finds the
    object literal between the equals sign and the ``as const`` suffix,
    rewrites TypeScript-isms to JSON (underscored-numeric literals,
    single quotes, trailing commas, ``null`` is fine as-is), and parses.

    Returns the parsed dict. Raises pytest.fail with a descriptive
    message if the file doesn't contain a ``MOCK_ASSET`` literal in the
    expected shape -- a future spec that uses a different mock name
    won't be silently skipped.
    """
    text = spec_path.read_text(encoding="utf-8")
    # Match `const MOCK_ASSET = { ... }` with an optional `as const`
    # suffix. Some specs use the `as const` form (asset-detail.spec.ts);
    # others omit it (trim.spec.ts). Both shapes are valid TypeScript.
    match = re.search(
        r"const\s+MOCK_ASSET\s*=\s*(\{.*?\})\s*(?:as\s+const)?\s*\n\s*\n",
        text,
        re.DOTALL,
    )
    if match is None:
        # Fall back to a greedier match that grabs the literal up to the
        # first dedented closing brace followed by a blank line. Catches
        # variant indent styles without overmatching across functions.
        match = re.search(
            r"const\s+MOCK_ASSET\s*=\s*(\{.*?\n\})",
            text,
            re.DOTALL,
        )
    if match is None:
        pytest.fail(
            f"{spec_path.name}: could not find a `const MOCK_ASSET = "
            "{ ... }` literal. If the spec was renamed or restructured, "
            "update the regex in tests/test_schema_fidelity.py."
        )

    literal = match.group(1)
    # Rewrite TypeScript-isms into JSON:
    #   1. Single-quoted strings -> double-quoted.
    literal = re.sub(r"'([^']*)'", r'"\1"', literal)
    #   2. Numeric underscores (5_000_000) -> plain (5000000).
    literal = re.sub(r"(\d)_(\d)", r"\1\2", literal)
    literal = re.sub(r"(\d)_(\d)", r"\1\2", literal)  # second pass for chained underscores
    #   3. Unquoted object keys -> quoted (asset_id: -> "asset_id":)
    #      We match identifier-like keys followed by a colon.
    literal = re.sub(
        r"([\{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:",
        r'\1"\2":',
        literal,
    )
    #   4. Trailing commas before } or ] -> remove (JSON forbids them).
    literal = re.sub(r",(\s*[}\]])", r"\1", literal)

    try:
        return json.loads(literal)
    except json.JSONDecodeError as exc:
        pytest.fail(
            f"{spec_path.name}: extracted MOCK_ASSET literal does not "
            f"parse as JSON after TypeScript-to-JSON rewriting. "
            f"Decode error: {exc}. Rewritten text:\n{literal}"
        )


def _staff_asset_row_field_set() -> set[str]:
    """Return the set of property names declared by StaffAssetRow."""
    schema = StaffAssetRow.model_json_schema()
    return set(schema["properties"].keys())


def _staff_asset_row_required_set() -> set[str]:
    """Return the set of fields StaffAssetRow declares as required.

    A field is required when it has no default AND is not Optional.
    Pydantic's JSON schema emits a ``required`` array when any such
    field exists.
    """
    schema = StaffAssetRow.model_json_schema()
    required = schema.get("required", [])
    return set(required)


# Discovery: every *.spec.ts under the e2e directory that contains a
# MOCK_ASSET literal becomes a parametrized test instance. New specs
# adding a MOCK_ASSET are picked up automatically.
def _find_mock_asset_specs() -> list[Path]:
    if not PLAYWRIGHT_SPECS_DIR.is_dir():
        return []
    return sorted(
        path
        for path in PLAYWRIGHT_SPECS_DIR.glob("*.spec.ts")
        if "MOCK_ASSET" in path.read_text(encoding="utf-8")
    )


_SPEC_FILES = _find_mock_asset_specs()


@pytest.mark.skipif(
    not _SPEC_FILES,
    reason="No e2e specs with MOCK_ASSET literal found; TEST-006 has nothing to check.",
)
class TestStaffAssetRowMockFidelity:
    """Locks: every MOCK_ASSET literal in Playwright e2e specs has the
    same keyset as StaffAssetRow.model_json_schema()'s properties.

    Drift this test catches:

    - **Field added to StaffAssetRow without updating the mocks.** Test
      fails on the "fields in StaffAssetRow not in mock" assertion. The
      operator UI's e2e tests would continue passing while the new
      field arrived in production unrendered.
    - **Field removed from StaffAssetRow without updating the mocks.**
      Test fails on the "fields in mock not in StaffAssetRow" assertion.
      The mocks would freeze a phantom contract.
    - **Field renamed.** Both above assertions fire simultaneously.

    Drift this test does NOT catch (intentionally):

    - **Field type changes** -- the schema has type info but the mocks
      are raw JSON. TypeScript's own type-checker is responsible for
      type-level drift; this test is a keyset gate, not a value-type
      gate.
    - **Validation-rule changes** (min_length, ge, max items) -- not
      keyset-relevant. The Pydantic validation tests at
      ``tests/schedule/test_metadata_edit.py::TestAssetMetadataUpdateModel``
      cover those.
    """

    @pytest.mark.parametrize(
        "spec_path",
        _SPEC_FILES,
        ids=[path.name for path in _SPEC_FILES],
    )
    def test_mock_asset_keys_match_staff_asset_row_schema(self, spec_path: Path) -> None:
        mock_keys = set(_extract_mock_asset_literal(spec_path).keys())
        schema_keys = _staff_asset_row_field_set()

        # Exempt the Slice-2-deferred drift from the missing-in-mock
        # set. The keys are documented at the module top; their absence
        # from the v0.3-era mocks is known and will be fixed by Slice 2.
        missing_in_mock = schema_keys - mock_keys - _KNOWN_DRIFT_TO_BE_FIXED_IN_SLICE_2
        extra_in_mock = mock_keys - schema_keys

        # Build a comprehensive error message before asserting so the
        # diff fixer doesn't need to bounce between two failing
        # assertions.
        if missing_in_mock or extra_in_mock:
            lines = [
                f"{spec_path.name}: MOCK_ASSET drifted from StaffAssetRow.model_json_schema().",
            ]
            if missing_in_mock:
                lines.append(
                    f"  Fields in StaffAssetRow but missing from MOCK_ASSET: "
                    f"{sorted(missing_in_mock)}"
                )
                lines.append(
                    "  -> add these keys to the MOCK_ASSET literal so the e2e "
                    "test renders the same shape the live API produces."
                )
            if extra_in_mock:
                lines.append(
                    f"  Fields in MOCK_ASSET but missing from StaffAssetRow: "
                    f"{sorted(extra_in_mock)}"
                )
                lines.append(
                    "  -> these keys are no longer on the Pydantic model. "
                    "Remove them from the MOCK_ASSET literal, or restore them "
                    "to StaffAssetRow if their removal was unintentional."
                )
            pytest.fail("\n".join(lines))

    @pytest.mark.parametrize(
        "spec_path",
        _SPEC_FILES,
        ids=[path.name for path in _SPEC_FILES],
    )
    def test_mock_asset_carries_all_required_fields(self, spec_path: Path) -> None:
        """Locks: every field StaffAssetRow declares as required is
        present in the mock. Optional fields may be omitted (the mock
        is free to default them) but required fields must be there or
        the live API would reject the response shape on parse."""
        mock_keys = set(_extract_mock_asset_literal(spec_path).keys())
        required = _staff_asset_row_required_set()

        # Same Slice-2-deferred exemption as the keyset test. The mocks
        # will gain the missing fields when Slice 2 opens the frontend
        # lane.
        missing_required = required - mock_keys - _KNOWN_DRIFT_TO_BE_FIXED_IN_SLICE_2
        if missing_required:
            pytest.fail(
                f"{spec_path.name}: MOCK_ASSET is missing required "
                f"StaffAssetRow fields: {sorted(missing_required)}. "
                f"Without these the mock cannot represent a valid "
                f"server response."
            )


class TestStaffAssetRowSchemaShape:
    """Locks: StaffAssetRow.model_json_schema() exposes a properties
    block (the contract the MOCK_ASSET fidelity tests above depend on).

    If a future Pydantic version changes the JSON schema shape, this
    test surfaces the breakage before the fidelity tests turn into
    a confusing parametrized cascade.
    """

    def test_schema_has_properties_dict(self) -> None:
        schema = StaffAssetRow.model_json_schema()
        assert "properties" in schema
        assert isinstance(schema["properties"], dict)
        assert len(schema["properties"]) > 0, (
            "StaffAssetRow.model_json_schema() emitted an empty properties "
            "dict. Either the model has no fields (shouldn't be possible) "
            "or Pydantic changed its JSON-schema format."
        )

    def test_known_fields_present(self) -> None:
        """Locks the existence of a hand-picked subset of StaffAssetRow
        fields. If any of these vanish, the audit-team v0.3.0 contract
        ledger needs an update before the test gets relaxed."""
        keys = _staff_asset_row_field_set()
        expected = {
            "asset_id",
            "title",
            "description",
            "state",
            "manifest_url",
            "published_at",
            "file_path",
            "file_size_bytes",
            "duration_seconds",
            "codec_video",
            "codec_audio",
            "width_px",
            "height_px",
            "bitrate_bps",
            "format_name",
            "trim_in_seconds",
            "trim_out_seconds",
            "chapters",
            "retention_policy",
            "retention_until",
            "version",
        }
        # source_live_session_id was added in Slice 1 Commit 7; include
        # it via subset check so this test stays forward-compatible.
        missing = expected - keys
        assert not missing, (
            f"StaffAssetRow lost fields the e2e MOCK_ASSET literals "
            f"depend on: {sorted(missing)}. Either restore the fields "
            f"or update the e2e mocks AND this test in the same commit."
        )


def test_peer_asset_metadata_models_share_a_field_set() -> None:
    """Audit ENG-011: schedule.models.AssetMetadata and vod.models.
    AssetMetadata are hand-synchronized peers (Director Decision 2); a field
    added to one and not the other silently drops data at the conversion
    boundary. Pin the field sets to each other."""

    from civiccast.schedule.models import AssetMetadata as ScheduleAssetMetadata
    from civiccast.vod.models import AssetMetadata as VodAssetMetadata

    schedule_fields = set(ScheduleAssetMetadata.model_fields)
    vod_fields = set(VodAssetMetadata.model_fields)
    assert schedule_fields == vod_fields, (
        f"Peer AssetMetadata models drifted: only-schedule={schedule_fields - vod_fields}, "
        f"only-vod={vod_fields - schedule_fields}. Add the field to both or "
        "single-source the model."
    )
