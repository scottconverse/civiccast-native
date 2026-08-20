# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Pure (any-OS) tests for the CC-WS5-007 admin-verb composition
(``civiccast.native.supervisor.admin``).

The pipe server already AUTHORIZES the admin tier (``authz`` + the
``ImpersonateNamedPipeClient`` gate in ``pipe_server``); this module tests the
ORTHOGONAL question CC-WS5-007 opened: once a mutating verb is authorized, is it
WIRED to a real, IDEMPOTENT supervisor action instead of raising? Every verb's
idempotence branch (stop-when-stopped is a noop, start-when-serving is a noop,
runtime_set-to-the-current-value is a noop) and every refuse branch (an illegal
runtime target, a restart while shutting down) is a falsifiable property proven
here with fakes -- no Win32, no registry, no pipe.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from civiccast.native.supervisor.admin import AdminCommandRouter, build_command_handler
from civiccast.native.supervisor.core import ChildStartOutcome


@dataclass
class FakeAdminSupervisor:
    """Stands in for core.Supervisor's admin surface. ``state`` is read by the
    router before and after each action; the action methods record their calls
    and move ``state`` the way the real supervisor would."""

    state: str = "ready"
    start_calls: int = 0
    graceful_stop_calls: int = 0
    restart_calls: int = 0
    restart_status: str = "started_ready"

    def start(self) -> None:
        self.start_calls += 1
        self.state = "ready"

    def graceful_stop(self) -> None:
        self.graceful_stop_calls += 1
        self.state = "stopping"

    def restart_control_plane(self) -> ChildStartOutcome:
        self.restart_calls += 1
        return ChildStartOutcome(
            name="control_plane",
            status=self.restart_status,  # type: ignore[arg-type]
            detail="fake restart",
        )

    # The read tier is served by core.command_handler in production; the combined
    # handler test drives a stand-in here.
    def command_handler(self, command: str, payload: dict[str, object]) -> dict[str, object]:
        return {"served": command}


@dataclass
class FakeSelector:
    """A fake runtime selector (the D-runtime registry value), so runtime_set's
    validate/idempotence/apply logic is proven without touching HKLM."""

    value: str | None = "native"
    writes: list[str] = field(default_factory=list)

    def read(self) -> str | None:
        return self.value

    def write(self, value: str) -> None:
        self.writes.append(value)
        self.value = value


def _router(
    supervisor: FakeAdminSupervisor, selector: FakeSelector | None = None
) -> AdminCommandRouter:
    selector = selector or FakeSelector()
    return AdminCommandRouter(
        supervisor=supervisor,  # type: ignore[arg-type]
        selector_reader=selector.read,
        selector_writer=selector.write,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# stop / drain -- graceful drain-all, idempotent when already stopping
# ---------------------------------------------------------------------------


def test_stop_from_serving_applies_the_graceful_drain() -> None:
    sup = FakeAdminSupervisor(state="ready")
    result = _router(sup).handle("stop", {"cmd": "stop", "v": 1})

    assert result["verb"] == "stop"
    assert result["outcome"] == "applied"
    assert result["state"] == "stopping"
    assert sup.graceful_stop_calls == 1


def test_drain_is_the_same_graceful_drain_all_as_stop() -> None:
    sup = FakeAdminSupervisor(state="ready")
    result = _router(sup).handle("drain", {"cmd": "drain", "v": 1})

    assert result["verb"] == "drain"
    assert result["outcome"] == "applied"
    assert sup.graceful_stop_calls == 1


def test_stop_when_already_stopping_is_an_idempotent_noop() -> None:
    """FALSIFICATION of the stop idempotence: a stop issued while the supervisor
    is already stopping must NOT re-run the drain (no torn second graceful_stop)."""

    sup = FakeAdminSupervisor(state="stopping")
    result = _router(sup).handle("stop", {"cmd": "stop", "v": 1})

    assert result["outcome"] == "noop"
    assert result["state"] == "stopping"
    assert sup.graceful_stop_calls == 0


# ---------------------------------------------------------------------------
# start -- bring up if not serving, idempotent when already serving
# ---------------------------------------------------------------------------


def test_start_when_already_ready_is_an_idempotent_noop() -> None:
    """FALSIFICATION of the start idempotence: a start issued while already
    serving (ready) must NOT re-run the full bring-up (no re-sweep/re-spawn)."""

    sup = FakeAdminSupervisor(state="ready")
    result = _router(sup).handle("start", {"cmd": "start", "v": 1})

    assert result["outcome"] == "noop"
    assert sup.start_calls == 0


def test_start_when_degraded_is_a_noop_degraded_still_serves() -> None:
    sup = FakeAdminSupervisor(state="degraded")
    result = _router(sup).handle("start", {"cmd": "start", "v": 1})

    assert result["outcome"] == "noop"
    assert sup.start_calls == 0


def test_start_from_starting_is_an_idempotent_noop() -> None:
    """CC-WS5-017 (Minor): a start issued while the machine is ALREADY mid-bring-up
    (``starting``) must be a no-op, not a fall-through to a full ``supervisor.start()``
    that re-sweeps + re-spawns children (a transient double-spawn during bring-up).
    FALSIFICATION: with the old guard (only ``workers_permitted`` -> noop),
    ``starting`` reached ``start()``; the fix treats ``starting`` as a no-op too."""

    sup = FakeAdminSupervisor(state="starting")
    result = _router(sup).handle("start", {"cmd": "start", "v": 1})

    assert result["outcome"] == "noop"
    assert result["state"] == "starting"
    assert sup.start_calls == 0
    assert "bring-up already in progress" in result["detail"]


def test_start_is_refused_while_stopping() -> None:
    sup = FakeAdminSupervisor(state="stopping")
    result = _router(sup).handle("start", {"cmd": "start", "v": 1})

    assert result["outcome"] == "refused"
    assert sup.start_calls == 0


def test_start_is_refused_while_blocked() -> None:
    sup = FakeAdminSupervisor(state="blocked_wsl_active")
    result = _router(sup).handle("start", {"cmd": "start", "v": 1})

    assert result["outcome"] == "refused"
    assert sup.start_calls == 0


# ---------------------------------------------------------------------------
# restart -- guard-gated controlled restart of the control plane
# ---------------------------------------------------------------------------


def test_restart_from_serving_applies_when_the_cp_comes_back_ready() -> None:
    sup = FakeAdminSupervisor(state="ready", restart_status="started_ready")
    result = _router(sup).handle("restart", {"cmd": "restart", "v": 1})

    assert result["outcome"] == "applied"
    assert sup.restart_calls == 1


def test_restart_is_refused_when_the_guard_withholds_the_cp() -> None:
    """A restart the D9 guard blocks (writer-capable CP withheld) is reported as
    refused, not a false 'applied'."""

    sup = FakeAdminSupervisor(state="ready", restart_status="guard_blocked")
    result = _router(sup).handle("restart", {"cmd": "restart", "v": 1})

    assert result["outcome"] == "refused"
    assert sup.restart_calls == 1


def test_restart_is_refused_while_stopping_without_touching_the_cp() -> None:
    sup = FakeAdminSupervisor(state="stopping")
    result = _router(sup).handle("restart", {"cmd": "restart", "v": 1})

    assert result["outcome"] == "refused"
    assert sup.restart_calls == 0


def test_restart_is_refused_while_blocked_without_touching_the_cp() -> None:
    sup = FakeAdminSupervisor(state="blocked_probe_unavailable")
    result = _router(sup).handle("restart", {"cmd": "restart", "v": 1})

    assert result["outcome"] == "refused"
    assert sup.restart_calls == 0


# ---------------------------------------------------------------------------
# runtime_set -- validate + apply the D-runtime selector, idempotent
# ---------------------------------------------------------------------------


def test_runtime_set_applies_a_legal_change() -> None:
    sel = FakeSelector(value="native")
    sup = FakeAdminSupervisor(state="ready")
    result = _router(sup, sel).handle("runtime_set", {"cmd": "runtime_set", "v": 1, "runtime": "wsl"})

    assert result["outcome"] == "applied"
    assert sel.writes == ["wsl"]
    assert sel.value == "wsl"


def test_runtime_set_to_the_current_value_is_an_idempotent_noop() -> None:
    """FALSIFICATION of the runtime_set idempotence: setting the selector to the
    value it already holds must NOT write the registry again."""

    sel = FakeSelector(value="native")
    sup = FakeAdminSupervisor(state="ready")
    result = _router(sup, sel).handle(
        "runtime_set", {"cmd": "runtime_set", "v": 1, "runtime": "native"}
    )

    assert result["outcome"] == "noop"
    assert sel.writes == []


def test_runtime_set_refuses_an_illegal_target() -> None:
    """'validate + apply; refuse illegal transitions': a target that is not a
    known runtime is refused and NEVER written."""

    sel = FakeSelector(value="native")
    sup = FakeAdminSupervisor(state="ready")
    result = _router(sup, sel).handle(
        "runtime_set", {"cmd": "runtime_set", "v": 1, "runtime": "haiku"}
    )

    assert result["outcome"] == "refused"
    assert sel.writes == []
    assert sel.value == "native"


def test_runtime_set_refuses_a_missing_target() -> None:
    sel = FakeSelector(value="native")
    sup = FakeAdminSupervisor(state="ready")
    result = _router(sup, sel).handle("runtime_set", {"cmd": "runtime_set", "v": 1})

    assert result["outcome"] == "refused"
    assert sel.writes == []


# ---------------------------------------------------------------------------
# The combined handler: read tier -> core.command_handler, admin tier -> router
# ---------------------------------------------------------------------------


def test_combined_handler_routes_read_verbs_to_the_core_handler() -> None:
    sup = FakeAdminSupervisor(state="ready")
    handler = build_command_handler(sup, _router(sup))  # type: ignore[arg-type]

    assert handler("status", {"cmd": "status", "v": 1}) == {"served": "status"}
    assert handler("version", {"cmd": "version", "v": 1}) == {"served": "version"}
    # The read tier never touched the mutating actions.
    assert sup.graceful_stop_calls == 0
    assert sup.start_calls == 0


def test_combined_handler_routes_admin_verbs_to_the_router() -> None:
    sup = FakeAdminSupervisor(state="ready")
    handler = build_command_handler(sup, _router(sup))  # type: ignore[arg-type]

    result = handler("stop", {"cmd": "stop", "v": 1})

    assert result["outcome"] == "applied"
    assert sup.graceful_stop_calls == 1


def test_router_raises_on_a_verb_it_does_not_serve() -> None:
    """Fail-closed backstop (mirrors core.command_handler): a command that is not
    one of this router's admin verbs raises rather than silently no-op'ing. In
    production the pipe's authz denies unknown commands upstream; this is the
    defence in depth behind it."""

    import pytest

    sup = FakeAdminSupervisor(state="ready")
    with pytest.raises(ValueError, match="does not serve"):
        _router(sup).handle("status", {"cmd": "status", "v": 1})
