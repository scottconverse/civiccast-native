# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Exhaustive + falsification tests for civiccast.native.runtime_guard.decide.

This is THE core: `decide` is a pure, total function over GuardInputs. The
exhaustive enumeration (4 selector-read states x 3 wsl-install-detected
[True/False/None -- F1's tri-state fix] x 3 a1.live_process x 3 a1.run_entry
x 3 a2 x 4 a3 x 3 interlock = 3888 points) checks four properties that must
hold at every point, then nine FALSIFICATION tests pin one example per D3
spec row (spec-dual-runtime-guard.md), and a final test proves the
property-check harness itself is not vacuous (AC8's negative control).
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator

import pytest

from civiccast.native.models import (
    A1Result,
    A2Result,
    A3Result,
    GuardDecision,
    GuardInputs,
    InterlockRead,
    MutexStatus,
    ProbeStatus,
    SelectorRead,
)
from civiccast.native.runtime_guard import decide

# --------------------------------------------------------------------------
# Exhaustive enumeration
# --------------------------------------------------------------------------

_SELECTOR_VARIANTS = [
    SelectorRead(ok=True, value="native", detail="HKLM ActiveRuntime=native"),
    SelectorRead(ok=True, value="wsl", detail="HKLM ActiveRuntime=wsl"),
    SelectorRead(ok=True, value="absent", detail="HKLM ActiveRuntime value missing"),
    SelectorRead(ok=False, value=None, detail="HKLM ActiveRuntime unreadable"),
]
_WSL_INSTALL_VARIANTS: list[bool | None] = [True, False, None]
_A1_SUBSIGNAL_VARIANTS: list[ProbeStatus] = ["negative", "positive", "error"]
_A2_VARIANTS: list[ProbeStatus] = ["negative", "positive", "unreadable"]
_A3_VARIANTS: list[MutexStatus] = ["acquired", "acquired_abandoned", "denied", "error"]
_INTERLOCK_VARIANTS = ["free", "held", "unreadable"]


def _all_guard_inputs() -> Iterator[GuardInputs]:
    for (
        selector,
        wsl_detected,
        a1_live,
        a1_run,
        a2_status,
        a3_status,
        interlock_status,
    ) in itertools.product(
        _SELECTOR_VARIANTS,
        _WSL_INSTALL_VARIANTS,
        _A1_SUBSIGNAL_VARIANTS,
        _A1_SUBSIGNAL_VARIANTS,
        _A2_VARIANTS,
        _A3_VARIANTS,
        _INTERLOCK_VARIANTS,
    ):
        yield GuardInputs(
            selector=selector,
            wsl_install_detected=wsl_detected,
            a1=A1Result(live_process=a1_live, run_entry=a1_run, detail="synthetic"),
            a2=A2Result(status=a2_status, detail="synthetic"),
            a3=A3Result(status=a3_status, detail="synthetic"),
            interlock=InterlockRead(status=interlock_status, record=None, detail="synthetic"),  # type: ignore[arg-type]
        )


_ALL_INPUTS: list[GuardInputs] = list(_all_guard_inputs())


def test_exhaustive_enumeration_has_3888_points() -> None:
    assert len(_ALL_INPUTS) == 4 * 3 * 3 * 3 * 3 * 4 * 3 == 3888


# --------------------------------------------------------------------------
# Independent oracles for D1/D2 -- restated from the spec, not copied from
# runtime_guard's implementation, so the properties below are real checks.
# --------------------------------------------------------------------------


def _effective_a1_positive(inputs: GuardInputs) -> bool:
    """D2: live keeper activity = (a1.live_process positive) OR (a1.run_entry
    positive AND selector was not read as "native")."""

    selector_is_native = inputs.selector.ok and inputs.selector.value == "native"
    live_positive = inputs.a1.live_process == "positive"
    run_positive_not_native = inputs.a1.run_entry == "positive" and not selector_is_native
    return live_positive or run_positive_not_native


def _is_authority_or_positive_condition(inputs: GuardInputs) -> bool:
    """Rows that are non-start for a REASON, not a probe defect: interlock
    held, an effective A1/A2 positive, an A3 conflict (denied), or selector
    authority itself (wsl / absent+wsl-CONFIRMED-detected).

    F1: absent+wsl_install_detected is a tri-state -- only a CONFIRMED
    ``True`` is an authority condition (refuse_instruct). ``None`` (install
    state unknown) is a PROBE DEFECT, not authority -- see ``_has_defect``.
    """

    if inputs.interlock.status == "held":
        return True
    if _effective_a1_positive(inputs):
        return True
    if inputs.a2.status == "positive":
        return True
    if inputs.a3.status == "denied":
        return True
    if inputs.selector.ok and inputs.selector.value == "wsl":
        return True
    return bool(
        inputs.selector.ok
        and inputs.selector.value == "absent"
        and inputs.wsl_install_detected is True
    )


def _has_defect(inputs: GuardInputs) -> bool:
    """F1: selector absent + wsl_install_detected is None (the
    install-detection probe itself could not determine an answer) is a
    probe defect -- decide() maps it to blocked_probe_unavailable, not a
    terminal refuse, which is exactly what P3 below verifies."""

    return (
        not inputs.selector.ok
        or inputs.interlock.status == "unreadable"
        or inputs.a1.live_process == "error"
        or inputs.a1.run_entry == "error"
        or inputs.a2.status == "unreadable"
        or inputs.a3.status == "error"
        or (
            inputs.selector.ok
            and inputs.selector.value == "absent"
            and inputs.wsl_install_detected is None
        )
    )


def _reaches_native_path(inputs: GuardInputs) -> bool:
    """Rows 5+ of decide(): interlock free+readable, selector resolves to
    "continue as native" (native, or absent with a CONFIRMED-False WSL
    install detection -- absent+None stops at step 4's
    blocked_probe_unavailable and never reaches here)."""

    if inputs.interlock.status != "free":
        return False
    if not inputs.selector.ok:
        return False
    if inputs.selector.value == "wsl":
        return False
    if inputs.selector.value == "absent":
        return inputs.wsl_install_detected is False
    return True


# --------------------------------------------------------------------------
# P1-P4
# --------------------------------------------------------------------------


def test_p1_totality_every_point_returns_a_valid_decision() -> None:
    for inputs in _ALL_INPUTS:
        decision = decide(inputs)
        assert isinstance(decision, GuardDecision)


def test_p2_no_positive_activity_signal_ever_starts() -> None:
    violations = [
        inputs
        for inputs in _ALL_INPUTS
        if (_effective_a1_positive(inputs) or inputs.a2.status == "positive")
        and decide(inputs).action in ("start", "start_degraded")
    ]
    assert not violations, f"{len(violations)} positive-signal inputs incorrectly started"


def test_p3_defect_only_inputs_never_produce_terminal_refuse() -> None:
    violations = [
        inputs
        for inputs in _ALL_INPUTS
        if _has_defect(inputs)
        and not _is_authority_or_positive_condition(inputs)
        and decide(inputs).action == "refuse"
    ]
    assert not violations, f"{len(violations)} defect-only inputs incorrectly refused"


def _selector_is_explicit_native(inputs: GuardInputs) -> bool:
    """D1's authority artifact: ``ActiveRuntime`` was READ successfully and
    its value is the exact string ``"native"``. Deliberately NOT satisfied by
    ``absent``-treated-as-native -- nothing was ever written there, so there
    is no artifact to stand a start on."""

    return bool(inputs.selector.ok and inputs.selector.value == "native")


def test_p4_a2_unreadable_without_an_explicit_native_selector_never_starts() -> None:
    """P4, NARROWED by chain I (owner-decided 2026-08-01) to the cases it
    still covers -- which is every native-path point EXCEPT an explicitly
    written ``ActiveRuntime=native``. The complement is P6 below; together
    they still partition the whole a2-unreadable native-path space, so no
    point lost coverage."""

    violations = [
        inputs
        for inputs in _ALL_INPUTS
        if inputs.a2.status == "unreadable"
        and _reaches_native_path(inputs)
        and not _selector_is_explicit_native(inputs)
        and decide(inputs).action in ("start", "start_degraded")
    ]
    assert not violations, f"{len(violations)} a2-unreadable native-path inputs incorrectly started"


def test_p6_explicit_native_selector_degrades_on_an_unreadable_a2_never_plain_starts() -> None:
    """P6 (chain I): the complement of P4. Under an EXPLICIT native selector
    with an unreadable A2 and nothing else blocking, the verdict must be
    ``start_degraded`` naming A2 -- never a silent plain ``start`` (which
    would hide the unreadability from the supervisor log) and never a block.

    "Nothing else blocking" is stated from the spec, not from decide(): the
    interlock is free, no positive/authority condition applies, and A3 is a
    clean ``acquired`` (``denied``/``error``/``acquired_abandoned`` each have
    their own row that chain I does not touch).
    """

    checked = 0
    for inputs in _ALL_INPUTS:
        if not (
            inputs.a2.status == "unreadable"
            and _selector_is_explicit_native(inputs)
            and inputs.interlock.status == "free"
            and not _is_authority_or_positive_condition(inputs)
            and inputs.a3.status == "acquired"
        ):
            continue
        checked += 1
        decision = decide(inputs)
        assert decision.action == "start_degraded", inputs
        assert decision.named_probe is not None and "A2" in decision.named_probe, inputs
        assert "probe-degraded" in decision.message, inputs
        assert decision.retry_seconds is None, inputs
        assert decision.state_name is None, inputs
    assert checked == 18, f"expected the 18-point chain I cell, enumerated {checked}"


# --------------------------------------------------------------------------
# One FALSIFICATION test per D3 spec row (9 total: row 2 "any POSITIVE
# (A1-A3)" is split into its three sub-signals).
# --------------------------------------------------------------------------


def _native_inputs(**overrides: object) -> GuardInputs:
    base: dict[str, object] = {
        "selector": SelectorRead(ok=True, value="native", detail="ok"),
        "wsl_install_detected": False,
        "a1": A1Result(live_process="negative", run_entry="negative", detail="clear"),
        "a2": A2Result(status="negative", detail="inactive"),
        "a3": A3Result(status="acquired", detail="owned"),
        "interlock": InterlockRead(status="free", record=None, detail="absent"),
    }
    base.update(overrides)
    return GuardInputs(**base)  # type: ignore[arg-type]


def test_falsification_row1_native_all_negative_starts() -> None:
    """D3 row: | native | all negative | start |"""

    decision = decide(_native_inputs())
    assert decision.action == "start"


def test_falsification_row2a_native_a1_positive_refuses_named_a1() -> None:
    """D3 row: | native | any POSITIVE (A1-A3) | refuse, name the probe |
    (A1 sub-signal: live keeper process)."""

    decision = decide(
        _native_inputs(
            a1=A1Result(live_process="positive", run_entry="negative", detail="wsl.exe keeper")
        )
    )
    assert decision.action == "refuse"
    assert decision.named_probe == "A1"


def test_falsification_row2b_native_a2_positive_refuses_named_a2() -> None:
    """D3 row: | native | any POSITIVE (A1-A3) | refuse, name the probe |
    (A2 sub-signal: in-distro service active)."""

    decision = decide(
        _native_inputs(a2=A2Result(status="positive", detail="civiccast.service active"))
    )
    assert decision.action == "refuse"
    assert decision.named_probe == "A2"


def test_falsification_row2c_native_a3_denied_refuses_named_a3() -> None:
    """D3 row: | native | any POSITIVE (A1-A3) | refuse, name the probe |
    (A3 sub-signal: mutex denied -- the other side owns it)."""

    decision = decide(
        _native_inputs(a3=A3Result(status="denied", detail="owned by keeper pid 4242"))
    )
    assert decision.action == "refuse"
    assert decision.named_probe == "A3"


def test_falsification_row3_native_a1_error_a2_readable_negative_starts_degraded() -> None:
    """D3 row: | native | A1 error/timeout, A2 readable-negative | start +
    log `probe-degraded`, re-probe per D5 |"""

    decision = decide(
        _native_inputs(
            a1=A1Result(live_process="error", run_entry="negative", detail="process scan failed")
        )
    )
    assert decision.action == "start_degraded"
    assert "probe-degraded" in decision.message


def test_falsification_row4_native_selector_a2_unreadable_degrades() -> None:
    """D3 row 4, AMENDED 2026-08-01 (chain I, owner-decided): an explicit,
    validly-read ``ActiveRuntime=native`` IS the authority basis for a native
    start -- it is the mechanism this spec defines for establishing one -- so
    an A2 the guard merely could not READ degrades the start and is logged,
    rather than withholding it.

    This test is the RED witness for chain I: it previously asserted
    ``blocked_probe_unavailable`` / ``retry_seconds == 10`` /
    ``state_name == "blocked_probe_unavailable"`` and PASSED against the
    pre-chain-I tree. Inverted here, it fails against that tree and passes
    only once decide() implements the amended row.

    Every OTHER selector state keeps the original row -- see
    ``test_falsification_row4b_...`` below and ``test_p4_...`` above.
    """

    decision = decide(_native_inputs(a2=A2Result(status="unreadable", detail="wsl.exe timed out")))
    assert decision.action == "start_degraded"
    assert decision.named_probe == "A2"
    assert "probe-degraded" in decision.message
    assert decision.retry_seconds is None
    assert decision.state_name is None


def test_falsification_row4b_absent_as_native_a2_unreadable_blocks() -> None:
    """The boundary chain I does NOT move. ``selector=absent`` with a
    CONFIRMED-False WSL install reaches the same native path, but the
    selector was never explicitly WRITTEN -- there is no authority artifact to
    stand the start on -- so the original D3 row 4 verdict is unchanged:
    NON-AUTHORIZING, bounded 10s retry, alert after 3."""

    decision = decide(
        _native_inputs(
            selector=SelectorRead(ok=True, value="absent", detail="value absent"),
            wsl_install_detected=False,
            a2=A2Result(status="unreadable", detail="wsl.exe timed out"),
        )
    )
    assert decision.action == "blocked_probe_unavailable"
    assert decision.retry_seconds == 10
    assert decision.state_name == "blocked_probe_unavailable"


def test_falsification_row5_selector_wsl_never_starts_natively() -> None:
    """D3 row: | wsl | -- | never start natively |"""

    decision = decide(_native_inputs(selector=SelectorRead(ok=True, value="wsl", detail="wsl")))
    assert decision.action == "never_start"


def test_falsification_row6_absent_wsl_install_detected_refuses_and_instructs() -> None:
    """D3 row: | absent | WSL install detected | refuse + instruct (set
    selector or run cutover) |"""

    decision = decide(
        _native_inputs(
            selector=SelectorRead(ok=True, value="absent", detail="absent"),
            wsl_install_detected=True,
        )
    )
    assert decision.action == "refuse_instruct"


def test_falsification_row7_absent_no_wsl_install_starts_as_native() -> None:
    """D3 row: | absent | no WSL install | start (treat as native) |"""

    decision = decide(
        _native_inputs(
            selector=SelectorRead(ok=True, value="absent", detail="absent"),
            wsl_install_detected=False,
        )
    )
    assert decision.action == "start"


def test_f1_absent_wsl_install_unknown_blocks_probe_unavailable_not_start() -> None:
    """F1 FALSIFICATION: selector absent + wsl_install_detected=None (the
    install-detection probe itself could not determine an answer) must NOT
    be silently treated as "no WSL install" (which is what the pre-fix
    fail-open bug did -- None is falsy in Python, so `if ... and
    wsl_install_detected:` fell through to "continue as native"). The
    correct outcome is blocked_probe_unavailable: cannot determine the
    authority basis for a native start."""

    decision = decide(
        _native_inputs(
            selector=SelectorRead(ok=True, value="absent", detail="absent"),
            wsl_install_detected=None,
        )
    )
    assert decision.action == "blocked_probe_unavailable"
    assert decision.retry_seconds == 10


# --------------------------------------------------------------------------
# D4 abandoned-mutex re-verify, D7a interlock precedence, D1 selector
# unreadable, run-entry-under-native ignore -- extra pinned cases beyond the
# nine D3 rows (not counted against the 9; these cover the brief's disclosed
# interpretation decisions directly).
# --------------------------------------------------------------------------


def test_interlock_held_refuses_before_anything_else() -> None:
    decision = decide(
        _native_inputs(
            interlock=InterlockRead(status="held", record=None, detail="maintenance in progress"),
            a1=A1Result(live_process="positive", run_entry="positive", detail="irrelevant"),
        )
    )
    assert decision.action == "refuse"
    assert decision.named_probe == "interlock"


def test_interlock_unreadable_blocks_fail_closed() -> None:
    decision = decide(
        _native_inputs(
            interlock=InterlockRead(status="unreadable", record=None, detail="malformed JSON")
        )
    )
    assert decision.action == "blocked_probe_unavailable"
    assert decision.retry_seconds == 10


def test_abandoned_mutex_with_a2_negative_continues_to_start() -> None:
    decision = decide(
        _native_inputs(a3=A3Result(status="acquired_abandoned", detail="prior owner crashed"))
    )
    assert decision.action == "start"


def test_abandoned_mutex_with_a2_unreadable_blocks() -> None:
    decision = decide(
        _native_inputs(
            a3=A3Result(status="acquired_abandoned", detail="prior owner crashed"),
            a2=A2Result(status="unreadable", detail="wsl.exe timed out"),
        )
    )
    assert decision.action == "blocked_probe_unavailable"


def test_run_entry_error_under_native_selector_is_ignored_not_degraded() -> None:
    """Disclosed interpretation: a1.run_entry error under selector=native is
    a presence-only signal that is IGNORED under native (not a degrade
    trigger) -- only a1.live_process error triggers start_degraded."""

    decision = decide(
        _native_inputs(
            a1=A1Result(live_process="negative", run_entry="error", detail="HKU scan failed")
        )
    )
    assert decision.action == "start"


def test_falsification_run_entry_error_under_absent_as_native_degrades() -> None:
    """FALSIFICATION (round-2 re-verify panel, Major): under selector=absent
    with a CONFIRMED-False install detection (D1 continue-as-native), the Run
    entry is a LIVE signal (D2: a positive would refuse, selector != native),
    so a failed HKU scan must degrade -- not silently vanish into a full
    non-degraded start."""

    decision = decide(
        _native_inputs(
            selector=SelectorRead(ok=True, value="absent", detail="value absent"),
            a1=A1Result(live_process="negative", run_entry="error", detail="HKU scan failed"),
        )
    )
    assert decision.action == "start_degraded"
    assert decision.named_probe == "A1"


def test_p5_relevant_probe_error_never_plain_start() -> None:
    """P5: on the native path with no positive/authority condition, an
    errored RELEVANT A1 sub-signal (live_process always; run_entry exactly
    where a run_entry positive would matter, i.e. selector != native) must
    never yield a plain non-degraded start."""

    violations = [
        inputs
        for inputs in _ALL_INPUTS
        if _reaches_native_path(inputs)
        and (
            inputs.a1.live_process == "error"
            or (inputs.a1.run_entry == "error" and inputs.selector.value != "native")
        )
        and decide(inputs).action == "start"
    ]
    assert not violations, (
        f"{len(violations)} relevant-probe-error inputs incorrectly plain-started"
    )


# --------------------------------------------------------------------------
# AC8 negative control
# --------------------------------------------------------------------------


def _assert_ac2_live_keeper_refuses(decide_fn: object) -> None:
    """AC2 shape: a live keeper process forces a refusal naming A1."""

    inputs = _native_inputs(
        a1=A1Result(live_process="positive", run_entry="negative", detail="wsl.exe keeper pid 1234")
    )
    decision = decide_fn(inputs)  # type: ignore[operator]
    assert decision.action == "refuse"
    assert decision.named_probe == "A1"


def test_ac2_live_keeper_refuses_named_a1() -> None:
    _assert_ac2_live_keeper_refuses(decide)


def test_ac8_negative_control_stubbed_always_start_fails_the_ac2_check() -> None:
    """FALSIFICATION: stub decide to always-start; the AC2-shaped assertion
    (live keeper => refuse) MUST fail -- proving the check actually bites
    rather than being vacuously true."""

    def always_start(_inputs: GuardInputs) -> GuardDecision:
        return GuardDecision(
            action="start", named_probe=None, message="stub", retry_seconds=None, state_name=None
        )

    with pytest.raises(AssertionError):
        _assert_ac2_live_keeper_refuses(always_start)


# --------------------------------------------------------------------------
# Chain I: the diff provably touches exactly ONE cell of the table.
#
# `_pre_chain_i_action` restates the PRE-chain-I D3 precedence directly from
# spec-dual-runtime-guard.md's own rows -- an independent oracle in the same
# spirit as `_effective_a1_positive` / `_has_defect` above, not a copy of
# decide()'s body. Because it is frozen at the pre-change semantics, a future
# edit to decide() cannot be silently mirrored into it: any new divergence
# shows up here as an unexplained changed point.
# --------------------------------------------------------------------------


def _pre_chain_i_action(inputs: GuardInputs) -> str:
    """The D3 table as it stood at 3cb0159a (before chain I)."""

    if inputs.interlock.status == "held":
        return "refuse"
    if inputs.interlock.status == "unreadable":
        return "blocked_probe_unavailable"
    if not inputs.selector.ok:
        return "blocked_probe_unavailable"
    if inputs.selector.value == "wsl":
        return "never_start"
    if inputs.selector.value == "absent":
        if inputs.wsl_install_detected is None:
            return "blocked_probe_unavailable"
        if inputs.wsl_install_detected:
            return "refuse_instruct"
    selector_is_native = inputs.selector.value == "native"
    if inputs.a1.live_process == "positive" or (
        inputs.a1.run_entry == "positive" and not selector_is_native
    ):
        return "refuse"
    if inputs.a2.status == "positive":
        return "refuse"
    if inputs.a3.status == "denied":
        return "refuse"
    if inputs.a3.status == "error":
        return "blocked_probe_unavailable"
    if inputs.a3.status == "acquired_abandoned" and inputs.a2.status == "unreadable":
        return "blocked_probe_unavailable"
    if inputs.a2.status == "unreadable":
        return "blocked_probe_unavailable"
    if inputs.a1.live_process == "error" or (
        inputs.a1.run_entry == "error" and not selector_is_native
    ):
        return "start_degraded"
    return "start"


def _is_chain_i_cell(inputs: GuardInputs) -> bool:
    """The ONE cell the owner decision moves: interlock free, selector read
    as an EXPLICIT "native", A2 unreadable, no positive/authority condition,
    and a clean ``acquired`` mutex (``denied``/``error``/``acquired_abandoned``
    each keep their own earlier row)."""

    return (
        inputs.interlock.status == "free"
        and _selector_is_explicit_native(inputs)
        and inputs.a2.status == "unreadable"
        and not _is_authority_or_positive_condition(inputs)
        and inputs.a3.status == "acquired"
    )


def test_chain_i_changes_exactly_the_one_decided_cell_and_nothing_else() -> None:
    """The no-other-cell-changes coverage the owner asked for: run the whole
    3888-point enumeration through both the pre-chain-I oracle and the live
    table, and assert the set of points whose ACTION changed is EXACTLY the
    decided cell -- not a superset, not a subset."""

    changed = [
        inputs for inputs in _ALL_INPUTS if _pre_chain_i_action(inputs) != decide(inputs).action
    ]
    expected = [inputs for inputs in _ALL_INPUTS if _is_chain_i_cell(inputs)]

    assert len(expected) == 18, "the decided cell is 18 of the 3888 points"
    assert len(changed) == len(expected), (
        f"{len(changed)} points changed, expected {len(expected)}; "
        f"unexpected: {[i for i in changed if not _is_chain_i_cell(i)][:3]}"
    )
    for inputs in changed:
        assert _is_chain_i_cell(inputs), f"a point outside the decided cell changed: {inputs}"
        assert _pre_chain_i_action(inputs) == "blocked_probe_unavailable"
        assert decide(inputs).action == "start_degraded"


def test_chain_i_differential_harness_is_not_vacuous() -> None:
    """AC8-style negative control for the differential above: the oracle must
    actually disagree with a table that changed something else. Feed it a stub
    that flips an UNRELATED cell (selector wsl -> start) and prove the
    outside-the-cell assertion bites."""

    wsl_point = next(
        inputs for inputs in _ALL_INPUTS if inputs.selector.ok and inputs.selector.value == "wsl"
    )
    assert _pre_chain_i_action(wsl_point) == "never_start"
    assert not _is_chain_i_cell(wsl_point)
