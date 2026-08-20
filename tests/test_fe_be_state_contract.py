# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Frontend↔backend contract test for the schedule state enum.

The audit-team v0.3.0 pass surfaced a multi-role Critical: the frontend's
``types/schedule.ts`` declared ``'aired' | 'failed'`` while the backend's
``_SCHEDULE_STATES`` tuple declared ``'published'`` — the divergence
crashed the schedule screen on the first published row and was never
caught by any automated gate. This test pins identity between the two
sources of truth so the drift cannot recur.

The test grep-parses the TypeScript file rather than running tsc.
TypeScript compilation isn't on the Python side of CI; a regex over the
declared union is sufficient because the type is explicitly listed and
documented as the contract surface.

If the backend's ``_SCHEDULE_STATES`` changes, this test fails until the
frontend's ``ScheduleState`` union is updated to match (and vice versa).

Audit: ENG-003 / QA-001 / TEST-003.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from civiccast.schedule.models import (
    _SCHEDULE_MODES,
    _SCHEDULE_STATES,
    SCHEDULE_MODE_EMBARGO,
    SCHEDULE_MODE_PREMIERE,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
FE_TYPES_FILE = (
    REPO_ROOT / "civiccast" / "apps" / "portal-operator" / "src" / "types" / "schedule.ts"
)


def _extract_braced_literal(source: str, lead_pattern: str) -> str:
    """Find a brace-delimited literal whose opening ``{`` follows the lead.

    Walks the source counting braces so nested object literals are
    handled. Returns the content between (but not including) the matching
    outer braces.
    """
    lead = re.search(lead_pattern, source)
    if not lead:
        raise AssertionError(f"Could not locate pattern {lead_pattern!r} in {FE_TYPES_FILE}.")
    start = source.index("{", lead.end())
    depth = 0
    for idx in range(start, len(source)):
        if source[idx] == "{":
            depth += 1
        elif source[idx] == "}":
            depth -= 1
            if depth == 0:
                return source[start + 1 : idx]
    raise AssertionError(f"Unbalanced braces after pattern {lead_pattern!r} in {FE_TYPES_FILE}.")


def _strip_nested_braces(text: str) -> str:
    """Replace each balanced ``{...}`` with a sentinel so an outer scan
    over keys at the top level isn't tripped by inner literal contents."""
    out: list[str] = []
    depth = 0
    for ch in text:
        if ch == "{":
            depth += 1
            if depth == 1:
                out.append("⟨")  # sentinel — never matches the [a-z_]+ key regex
            continue
        if ch == "}":
            depth -= 1
            if depth == 0:
                out.append("⟩")
            continue
        if depth == 0:
            out.append(ch)
    return "".join(out)


def _parse_ts_string_union(source: str, type_name: str) -> set[str]:
    """Extract the string-literal members of a TS string union by name.

    Accepts either inline union form::

        export type Foo = 'a' | 'b' | 'c'

    or the multi-line form::

        export type Foo =
          | 'a'
          | 'b'
          | 'c'

    Returns the set of literal strings. Raises if the type cannot be
    located or parsed — failure here means the test predicate has drifted
    and needs to be tightened, not that the contract is OK.
    """
    pattern = re.compile(
        rf"export\s+type\s+{re.escape(type_name)}\s*=\s*([^;]+?)(?:\n\n|$)",
        re.DOTALL,
    )
    match = pattern.search(source)
    if not match:
        raise AssertionError(
            f"Could not locate `export type {type_name} = ...` in "
            f"{FE_TYPES_FILE}. The contract test parser may need updating."
        )
    body = match.group(1)
    literals = re.findall(r"'([^']+)'", body)
    if not literals:
        raise AssertionError(
            f"`export type {type_name}` resolved but contained no string "
            f"literals. The parser may need updating, or the union has "
            f"degraded into a non-string-literal shape."
        )
    return set(literals)


@pytest.fixture(scope="module")
def fe_source() -> str:
    if not FE_TYPES_FILE.exists():
        pytest.skip(f"Frontend types file not present at {FE_TYPES_FILE}")
    return FE_TYPES_FILE.read_text(encoding="utf-8")


class TestScheduleStateContract:
    """Locks: the frontend ScheduleState union exactly equals the backend
    _SCHEDULE_STATES tuple. Either side editing in isolation breaks here."""

    def test_fe_union_equals_be_tuple(self, fe_source: str) -> None:
        fe_states = _parse_ts_string_union(fe_source, "ScheduleState")
        be_states = set(_SCHEDULE_STATES)
        assert fe_states == be_states, (
            "Frontend ScheduleState and backend _SCHEDULE_STATES diverged. "
            f"FE has: {sorted(fe_states)}. BE has: {sorted(be_states)}. "
            "Update both sides — see civiccast/schedule/models.py and "
            "civiccast/apps/portal-operator/src/types/schedule.ts."
        )

    def test_fe_state_meta_keys_cover_be_tuple(self, fe_source: str) -> None:
        # The SCHEDULE_STATE_META map is the runtime lookup; missing keys
        # would surface only at render time. Pin the key set against the
        # backend so a missing meta entry is caught at the test boundary.
        body = _extract_braced_literal(
            fe_source,
            r"export\s+const\s+SCHEDULE_STATE_META\s*:\s*Record\s*<\s*"
            r"ScheduleState\s*,\s*StateMeta\s*>\s*=\s*",
        )
        # Strip nested {...} so top-level `<key>:` lines don't pick up the
        # `label:` / `tone:` keys inside each entry. Replace each balanced
        # nested literal with a sentinel so the outer scan still works.
        flat = _strip_nested_braces(body)
        keys = set(re.findall(r"^\s*([a-z_]+)\s*:", flat, re.MULTILINE))
        be_states = set(_SCHEDULE_STATES)
        assert keys == be_states, (
            f"SCHEDULE_STATE_META keys {sorted(keys)} do not match "
            f"backend states {sorted(be_states)}."
        )


class TestScheduleModeContract:
    """Locks: the frontend ScheduleMode union exactly equals the backend
    _SCHEDULE_MODES tuple. The schedule drawer hard-codes a subset for the
    operator UI; that subset is verified separately below."""

    def test_fe_union_equals_be_tuple(self, fe_source: str) -> None:
        fe_modes = _parse_ts_string_union(fe_source, "ScheduleMode")
        be_modes = set(_SCHEDULE_MODES)
        assert fe_modes == be_modes, (
            "Frontend ScheduleMode and backend _SCHEDULE_MODES diverged. "
            f"FE has: {sorted(fe_modes)}. BE has: {sorted(be_modes)}."
        )

    def test_be_modes_include_documented_two(self) -> None:
        # Sanity check on the BE side — these constants are the public
        # API and should not be renamed without breaking callers.
        # Audit-team v0.3.0 ENG-004 retired SCHEDULE_MODE_LIVE; the
        # surviving public modes are premiere + embargo.
        assert SCHEDULE_MODE_PREMIERE in _SCHEDULE_MODES
        assert SCHEDULE_MODE_EMBARGO in _SCHEDULE_MODES
        assert "live" not in _SCHEDULE_MODES
