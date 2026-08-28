# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Unit tests for :mod:`civiccast.native.provision.port_select` -- the
port pre-check + fallback logic that survives a Windows-excluded/reserved TCP
port before ``pg_ctl start`` ever runs.

Regression context: real-world LPM deployment failure, 2026-08-27, candidate
75cc13f, two independent installer runs on the same box. Both failed
identically at ``d4-provision`` because ``pg_ctl start`` could not bind
``127.0.0.1:5432`` (``WSAEACCES`` -- "Permission denied" -- ``could not create
any TCP/IP sockets``). Evidence (read-only) at E:\\CivicCast1stfail\\ and
E:\\CivicCast2ndfail\\ (install-progress.log, provision\\PROVISION-RECOVERY.md,
provision\\provision-journal.json).

HARD RULE (matches the rest of ``civiccast.native.provision``'s test suite):
no real PostgreSQL/pg_ctl/initdb process is ever spawned here. A real TCP
socket bind (:func:`real_test_bind_port`) is NOT postgres -- it is exercised
directly, locally, against ports this test process itself opens and closes,
never against a real server.
"""

from __future__ import annotations

import socket

from civiccast.native.provision.port_select import (
    DEFAULT_PORT_CANDIDATES,
    format_excluded_ranges_for_operator,
    parse_excluded_port_ranges,
    port_in_excluded_ranges,
    real_test_bind_port,
    resolve_provision_port,
    select_provision_port,
)

# ---------------------------------------------------------------------------
# parse_excluded_port_ranges / port_in_excluded_ranges (pure, real netsh text)
# ---------------------------------------------------------------------------

#: A realistic ``netsh int ipv4 show excludedportrange protocol=tcp``
#: transcript (Windows's own documented output shape: banner, header, dashed
#: divider, data rows -- some administratively persisted (trailing "*"),
#: some not -- and a footnote).
_REAL_NETSH_OUTPUT = """
Protocol tcp Port Exclude Ranges

Start Port    End Port
----------    --------
      5357        5357
      5432        5432     *
     50000       50059     *

* - Administered port exclusions.
"""


def test_parse_excluded_port_ranges_reads_real_netsh_output() -> None:
    assert parse_excluded_port_ranges(_REAL_NETSH_OUTPUT) == (
        (5357, 5357),
        (5432, 5432),
        (50000, 50059),
    )


def test_parse_excluded_port_ranges_skips_banner_header_divider_and_footer() -> None:
    text = (
        "Protocol tcp Port Exclude Ranges\n\n"
        "Start Port    End Port\n"
        "----------    --------\n\n"
        "* - Administered port exclusions.\n"
    )
    assert parse_excluded_port_ranges(text) == ()


def test_parse_excluded_port_ranges_empty_output_returns_no_ranges() -> None:
    assert parse_excluded_port_ranges("") == ()


def test_parse_excluded_port_ranges_skips_malformed_or_out_of_bounds_rows() -> None:
    text = "\n".join(
        [
            "     70000        70001",  # out of the 1..65535 envelope
            "       100           50",  # start > end
            "       100          200",  # the one genuinely valid row
            "not a range at all",
        ]
    )
    assert parse_excluded_port_ranges(text) == ((100, 200),)


def test_port_in_excluded_ranges() -> None:
    ranges = ((5357, 5357), (50000, 50059))
    assert port_in_excluded_ranges(5357, ranges) is True
    assert port_in_excluded_ranges(50030, ranges) is True
    assert port_in_excluded_ranges(5432, ranges) is False


# ---------------------------------------------------------------------------
# select_provision_port (pure decision, injected fake test_bind)
# ---------------------------------------------------------------------------


def test_select_provision_port_returns_preferred_port_when_it_binds() -> None:
    result = select_provision_port(
        host="127.0.0.1",
        preferred_port=5432,
        candidates=DEFAULT_PORT_CANDIDATES,
        excluded_ranges=(),
        test_bind=lambda host, port: (True, f"bind succeeded on {host}:{port}"),
    )
    assert result.outcome == "selected"
    assert result.port == 5432
    assert len(result.attempts) == 1
    assert result.attempts[0].outcome == "available"


def test_select_provision_port_skips_excluded_candidates_without_binding() -> None:
    bind_calls: list[int] = []

    def fake_bind(host: str, port: int) -> tuple[bool, str]:
        bind_calls.append(port)
        return True, "ok"

    result = select_provision_port(
        host="127.0.0.1",
        preferred_port=5432,
        candidates=DEFAULT_PORT_CANDIDATES,
        excluded_ranges=((5432, 5432),),
        test_bind=fake_bind,
    )
    assert result.outcome == "selected"
    assert result.port == 5433
    assert 5432 not in bind_calls, "an excluded port must never even be test-bound"
    assert result.attempts[0].port == 5432
    assert result.attempts[0].outcome == "excluded"
    assert result.attempts[1].port == 5433
    assert result.attempts[1].outcome == "available"


def test_select_provision_port_falls_back_past_real_bind_failures() -> None:
    def fake_bind(host: str, port: int) -> tuple[bool, str]:
        if port in (5432, 5433):
            return False, f"bind failed on {host}:{port} (winerror=10013): Permission denied"
        return True, f"bind succeeded on {host}:{port}"

    result = select_provision_port(
        host="127.0.0.1",
        preferred_port=5432,
        candidates=DEFAULT_PORT_CANDIDATES,
        excluded_ranges=(),
        test_bind=fake_bind,
    )
    assert result.outcome == "selected"
    assert result.port == 5434
    assert [a.outcome for a in result.attempts] == ["bind_failed", "bind_failed", "available"]


def test_select_provision_port_no_candidate_available_names_every_attempt() -> None:
    result = select_provision_port(
        host="127.0.0.1",
        preferred_port=5432,
        candidates=DEFAULT_PORT_CANDIDATES,
        excluded_ranges=(),
        test_bind=lambda host, port: (False, f"bind failed on {host}:{port}: permission denied"),
    )
    assert result.outcome == "no_candidate_available"
    assert result.port is None
    ordered_candidates = {5432, *DEFAULT_PORT_CANDIDATES}
    assert len(result.attempts) == len(ordered_candidates)
    for candidate in ordered_candidates:
        assert str(candidate) in result.detail, (
            f"port {candidate} missing from the honest failure detail"
        )


def test_select_provision_port_tries_preferred_port_first_and_only_once() -> None:
    order: list[int] = []

    def fake_bind(host: str, port: int) -> tuple[bool, str]:
        order.append(port)
        return False, "no"

    select_provision_port(
        host="127.0.0.1",
        preferred_port=5544,  # already the LAST entry in DEFAULT_PORT_CANDIDATES
        candidates=DEFAULT_PORT_CANDIDATES,
        excluded_ranges=(),
        test_bind=fake_bind,
    )
    assert order[0] == 5544, "the preferred port must always be attempted first"
    assert order.count(5544) == 1, "the preferred port must never be retried as its own alternate"
    assert len(order) == len(DEFAULT_PORT_CANDIDATES)


# ---------------------------------------------------------------------------
# Regression: the exact LPM failure signature
# ---------------------------------------------------------------------------


def test_lpm_failure_signature_5432_excluded_falls_back_to_next_candidate() -> None:
    """Regression for the real-world LPM deployment failure (2026-08-27,
    candidate 75cc13f): both installer runs failed because port 5432 could
    not bind on this Windows box. Feeding select_provision_port the SAME
    excluded-range shape (5432 administratively excluded, matching a
    Hyper-V/WSL winnat reservation) must fall through to the next documented
    candidate and SUCCEED, rather than halting on the first rejected port."""

    netsh_transcript = "      5432        5432     *\n"
    excluded = parse_excluded_port_ranges(netsh_transcript)
    assert excluded == ((5432, 5432),)

    result = select_provision_port(
        host="127.0.0.1",
        preferred_port=5432,
        candidates=DEFAULT_PORT_CANDIDATES,
        excluded_ranges=excluded,
        test_bind=lambda host, port: (True, f"bind succeeded on {host}:{port}"),
    )
    assert result.outcome == "selected"
    assert result.port == 5433
    assert result.attempts[0].outcome == "excluded"


def test_lpm_failure_signature_honest_failure_when_every_candidate_is_reserved() -> None:
    """The other half of the same regression: if EVERY documented candidate
    -- not just 5432 -- sits inside a Windows-excluded range (a wide winnat
    reservation), the honest no-candidate-available outcome must still name
    every attempted port, never silently pick one anyway."""

    # A wide exclusion covering every DEFAULT_PORT_CANDIDATES entry.
    excluded = ((5000, 6000),)
    result = select_provision_port(
        host="127.0.0.1",
        preferred_port=5432,
        candidates=DEFAULT_PORT_CANDIDATES,
        excluded_ranges=excluded,
        test_bind=lambda host, port: (True, "unreachable -- every candidate is excluded"),
    )
    assert result.outcome == "no_candidate_available"
    assert result.port is None
    assert all(a.outcome == "excluded" for a in result.attempts)


# ---------------------------------------------------------------------------
# real_test_bind_port (mock/local -- real sockets, no external dependency)
# ---------------------------------------------------------------------------


def test_real_test_bind_port_succeeds_on_a_genuinely_free_port() -> None:
    # Ask the OS for an ephemeral free port, release it immediately, then
    # prove real_test_bind_port can bind that exact port number.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    free_port = probe.getsockname()[1]
    probe.close()

    ok, detail = real_test_bind_port("127.0.0.1", free_port)
    assert ok is True
    assert str(free_port) in detail


def test_real_test_bind_port_fails_when_the_port_is_already_held() -> None:
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    occupied_port = holder.getsockname()[1]
    try:
        ok, detail = real_test_bind_port("127.0.0.1", occupied_port)
        assert ok is False
        assert str(occupied_port) in detail
    finally:
        holder.close()


def test_real_test_bind_port_never_raises_on_bind_failure() -> None:
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    occupied_port = holder.getsockname()[1]
    try:
        # Must return a classified failure, never propagate the OSError.
        real_test_bind_port("127.0.0.1", occupied_port)
    finally:
        holder.close()


# ---------------------------------------------------------------------------
# resolve_provision_port (real-seam wrapper, fully faked at its two seams)
# ---------------------------------------------------------------------------


def test_resolve_provision_port_wires_netsh_output_into_selection() -> None:
    result = resolve_provision_port(
        host="127.0.0.1",
        preferred_port=5432,
        netsh_output_provider=lambda: "      5432        5432     *\n",
        test_bind=lambda host, port: (True, f"bind succeeded on {host}:{port}"),
    )
    assert result.outcome == "selected"
    assert result.port == 5433
    assert "5432" in result.netsh_raw_output


def test_resolve_provision_port_survives_a_failing_netsh_probe() -> None:
    """The netsh diagnostic step itself failing (subprocess error) must never
    block port selection -- the real bind test on every candidate is the
    authoritative signal."""

    def broken_netsh() -> str:
        raise OSError("netsh.exe not found")

    result = resolve_provision_port(
        host="127.0.0.1",
        preferred_port=5432,
        netsh_output_provider=broken_netsh,
        test_bind=lambda host, port: (True, "ok"),
    )
    assert result.outcome == "selected"
    assert result.port == 5432
    assert "netsh" in result.detail.lower()


def test_resolve_provision_port_honest_failure_names_every_candidate() -> None:
    result = resolve_provision_port(
        host="127.0.0.1",
        preferred_port=5432,
        netsh_output_provider=lambda: "",
        test_bind=lambda host, port: (False, f"bind failed on {host}:{port}: Permission denied"),
    )
    assert result.outcome == "no_candidate_available"
    assert result.port is None
    for candidate in {5432, *DEFAULT_PORT_CANDIDATES}:
        assert str(candidate) in result.detail


# ---------------------------------------------------------------------------
# format_excluded_ranges_for_operator (operator-facing recovery-doc text)
# ---------------------------------------------------------------------------


def test_format_excluded_ranges_for_operator_placeholder_when_empty() -> None:
    assert "could not be read" in format_excluded_ranges_for_operator("")
    assert "could not be read" in format_excluded_ranges_for_operator("   \n  ")


def test_format_excluded_ranges_for_operator_returns_raw_text_verbatim() -> None:
    text = "5432        5432     *"
    assert format_excluded_ranges_for_operator(f"  {text}  \n") == text
