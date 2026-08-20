# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Verdict logic for the measured live-delivery soak.

The old soak's failure mode was structural: a sleep loop that always PASSed.
These tests pin the replacement's fail-closed posture — every criterion that
can fail must actually flip the verdict, and short runs can never render as
full-duration evidence.
"""

from __future__ import annotations

from civiccast.load.live_soak import Sample, analyze, render_evidence


def _sample(t: float, **overrides: int) -> Sample:
    base: dict[str, float | int] = {
        "t": t,
        "rss_bytes": 200_000_000,
        "handles": 300,
        "threads": 20,
        "viewers": 4,
        "manifest_fetches": int(t),
        "segment_fetches": int(t),
        "fetch_errors": 0,
        "server_5xx": 0,
        "stalls": 0,
        "switch_engages": 5,
        "switch_releases": 5,
    }
    base.update(overrides)
    return Sample(**base)  # type: ignore[arg-type]


def _healthy_run(duration_s: float = 12 * 3600.0) -> list[Sample]:
    return [_sample(t) for t in range(60, int(duration_s) + 60, 60)]


def test_healthy_full_run_passes() -> None:
    verdict = analyze(_healthy_run(), requested_duration_s=12 * 3600.0)
    assert verdict.passed, verdict.reasons
    assert verdict.rss_growth <= 1.01


def test_short_run_fails_even_if_otherwise_clean() -> None:
    verdict = analyze(_healthy_run(3600.0), requested_duration_s=12 * 3600.0)
    assert not verdict.passed
    assert any("requested" in r for r in verdict.reasons)


def test_no_samples_fails() -> None:
    assert not analyze([], requested_duration_s=1.0).passed


def test_5xx_fails() -> None:
    samples = _healthy_run()
    samples[-1] = _sample(samples[-1].t, server_5xx=1)
    verdict = analyze(samples, requested_duration_s=12 * 3600.0)
    assert not verdict.passed
    assert any("5xx" in r for r in verdict.reasons)


def test_stalls_within_shared_lab_budget_pass_with_report() -> None:
    # A couple of environmental freeze events on a busy lab box (each stalls
    # all viewers at once) stay within the documented 0.05% budget.
    samples = _healthy_run()
    samples[-1] = _sample(samples[-1].t, stalls=8)
    verdict = analyze(samples, requested_duration_s=12 * 3600.0)
    assert verdict.passed, verdict.reasons
    assert verdict.totals["stalls"] == 8  # still reported, never hidden


def test_stalls_beyond_budget_fail() -> None:
    samples = _healthy_run()
    samples[-1] = _sample(samples[-1].t, stalls=500)
    verdict = analyze(samples, requested_duration_s=12 * 3600.0)
    assert not verdict.passed
    assert any("shared-lab budget" in r for r in verdict.reasons)


def test_idle_viewers_fail() -> None:
    # A soak whose viewers never fetched anything proved nothing.
    samples = [
        _sample(t, manifest_fetches=0, segment_fetches=0) for t in range(60, 12 * 3600 + 60, 60)
    ]
    verdict = analyze(samples, requested_duration_s=12 * 3600.0)
    assert not verdict.passed
    assert any("never ran" in r for r in verdict.reasons)


def test_missing_switch_cycles_fail() -> None:
    samples = [_sample(t, switch_engages=0, switch_releases=0) for t in range(60, 43260, 60)]
    verdict = analyze(samples, requested_duration_s=12 * 3600.0)
    assert not verdict.passed
    assert any("switch cycles" in r for r in verdict.reasons)


def test_bounded_release_blips_pass_but_excessive_fail() -> None:
    # A handful of single-cycle 404s at release boundaries is the designed
    # race (healed by re-resolve); a flood of them is a broken CDN path.
    ok = _healthy_run()
    ok[-1] = _sample(ok[-1].t, release_blips=10, switch_releases=5)
    assert analyze(ok, requested_duration_s=12 * 3600.0).passed

    bad = _healthy_run()
    bad[-1] = _sample(bad[-1].t, release_blips=100, switch_releases=5)
    verdict = analyze(bad, requested_duration_s=12 * 3600.0)
    assert not verdict.passed
    assert any("CDN path suspect" in r for r in verdict.reasons)


def test_rss_leak_fails() -> None:
    # Steady 30%/run climb after warmup — the classic slow leak a soak exists to catch.
    total = 12 * 3600
    samples = [
        _sample(t, rss_bytes=int(200_000_000 * (1.0 + 0.5 * (t / total))))
        for t in range(60, total + 60, 60)
    ]
    verdict = analyze(samples, requested_duration_s=float(total))
    assert not verdict.passed
    assert any("RSS grew" in r for r in verdict.reasons)


def test_render_refuses_short_run_as_evidence() -> None:
    verdict = analyze(_healthy_run(3600.0), requested_duration_s=12 * 3600.0)
    text = render_evidence(
        verdict,
        requested_duration_s=12 * 3600.0,
        commit="deadbeef",
        samples_path="x.jsonl",
        baseline_viewers=4,
        surge_viewers=14,
    )
    assert "Status: **FAIL**" in text
    assert "ran 3600s of the requested" in "\n".join(verdict.reasons)


def test_render_pass_contains_measured_numbers() -> None:
    verdict = analyze(_healthy_run(), requested_duration_s=12 * 3600.0)
    text = render_evidence(
        verdict,
        requested_duration_s=12 * 3600.0,
        commit="deadbeef",
        samples_path="soak.samples.jsonl",
        baseline_viewers=4,
        surge_viewers=14,
    )
    assert "Status: **PASS**" in text
    assert "`deadbeef`" in text
    assert "soak.samples.jsonl" in text
    assert "generated from measured samples" in text
