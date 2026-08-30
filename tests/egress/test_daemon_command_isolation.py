# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""DEFECT D regression: the command queue must keep draining after a pass fails.

Found live: after a channel's first couple of "start" commands processed,
every LATER queued command ("takeover", then a "stop") sat unprocessed for
minutes with zero log activity. Root cause, confirmed by reading the code
(not inferred): ``EgressStore.pop_pending_commands`` marks the ENTIRE
currently-pending batch consumed in one durable update BEFORE any of it
runs, and ``EgressDaemon.process_once`` used to run that batch through a
bare, unguarded ``for`` loop -- one command raising (e.g. the DEFECT A hls
crash) aborted the loop, and every command queued alongside or after it in
that same batch was already marked consumed and therefore lost forever,
with no trace of what happened to it.

These tests prove the fix at the unit level: a batch containing a command
that raises must still let every OTHER command in that same batch run.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from civiccast.egress.daemon import EgressDaemon
from civiccast.egress.models import EgressCommand, EgressConfig, EgressSinkSpec
from civiccast.egress.store import InMemoryEgressStore


def _config() -> EgressConfig:
    return EgressConfig(
        channel_id="gov",
        enabled=True,
        slate_message="CivicCast is preparing the channel.",
        sinks=[EgressSinkSpec(kind="file", label="Proof", uri="build/out.ts")],
    )


def _command(action: str, *, command_id: str, minute: int) -> EgressCommand:
    return EgressCommand(
        channel_id="gov",
        action=action,  # type: ignore[arg-type]
        issued_at=datetime(2026, 6, 5, 12, minute, tzinfo=UTC),
        issued_by="operator",
        command_id=command_id,
    )


def test_a_raising_command_does_not_starve_later_commands_in_the_same_batch(
    tmp_path: Path,
) -> None:
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    # Both commands are pending BEFORE process_once runs, so
    # pop_pending_commands returns them as ONE batch, "start" sorted first
    # (earlier issued_at) -- exactly the shape of the live repro.
    store.enqueue_command(_command("start", command_id="cmd-start", minute=0))
    store.enqueue_command(_command("stop", command_id="cmd-stop", minute=1))

    def exploding_source_plan_provider(_channel_id: str):
        # A bare, uncaught exception type -- like DEFECT A's ValueError from
        # sink_element_spec, which _start's except clauses never caught.
        raise RuntimeError("simulated DEFECT-A-shaped crash")

    failures: list[tuple[str, str, str]] = []

    def on_failure(channel_id: str, command: EgressCommand, exc: BaseException) -> None:
        failures.append((channel_id, command.command_id, str(exc)))

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=exploding_source_plan_provider,
        command_failure_hook=on_failure,
    )

    processed_count = daemon.process_once("gov")  # must not raise

    assert processed_count == 2
    # The crashing "start" was reported through the failure hook exactly once...
    assert failures == [("gov", "cmd-start", "simulated DEFECT-A-shaped crash")]
    # ...and the "stop" queued right after it in the SAME batch still ran:
    # this is the actual regression proof -- before the fix, "stop" would
    # never have been handed to _process_command at all.
    state = store.read_state("gov")
    assert state is not None
    assert state.state == "STOPPED"


def test_command_failure_hook_is_optional(tmp_path: Path) -> None:
    """A daemon built without a hook (tests, the bare CLI loop) must not raise
    just because process_once needs to report a swallowed failure to no one."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command("start", command_id="cmd-start", minute=0))
    store.enqueue_command(_command("stop", command_id="cmd-stop", minute=1))

    def exploding_source_plan_provider(_channel_id: str):
        raise RuntimeError("simulated crash")

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=exploding_source_plan_provider,
    )

    assert daemon.process_once("gov") == 2
    assert store.read_state("gov").state == "STOPPED"  # type: ignore[union-attr]


def test_a_failure_hook_that_itself_raises_does_not_break_draining(tmp_path: Path) -> None:
    """The hook is best-effort reporting, not part of the command's own
    success/failure -- a broken hook must never re-introduce the poison-batch
    bug it exists to help diagnose."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_command("start", command_id="cmd-start", minute=0))
    store.enqueue_command(_command("stop", command_id="cmd-stop", minute=1))

    def exploding_source_plan_provider(_channel_id: str):
        raise RuntimeError("simulated crash")

    def broken_hook(*_args: object) -> None:
        raise ValueError("the alert plumbing itself is broken")

    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=exploding_source_plan_provider,
        command_failure_hook=broken_hook,
    )

    assert daemon.process_once("gov") == 2
    assert store.read_state("gov").state == "STOPPED"  # type: ignore[union-attr]
