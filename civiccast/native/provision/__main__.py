# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""CLI entry point the native NSIS hook set invokes for live PostgreSQL/NATS
provisioning execution (WP2 provision-execution wiring;
``native_service_registration.rs``'s module doc's "DatabaseUrl" STOP section
names this as the missing caller). Mirrors
:mod:`civiccast.native.upgrade.__main__`'s CLI shape: all the logic lives in
the tested engine (:mod:`civiccast.native.provision`), never here. This
module's own job is narrow: generate the database credential, decide whether
a run is even needed (idempotency), assemble the plan/context, drive the
engine against its REAL seam bundle, and hand the resolved ``DatabaseUrl``
back to the Rust caller through a single stdout marker line -- never through
a log, a journal entry, an NSIS variable dump, or this process's own
diagnostic output.

Invocation (``nsis-hooks-native.nsh``'s ``NSIS_HOOK_POSTINSTALL``)::

    python -m civiccast.native.provision \\
        --install-root "C:\\Program Files\\CivicCast (Native)" \\
        --owner-run-id <run-id> \\
        --pack-signing-key-id <id> --pack-public-key-base64 <base64> \\
        --pack-product-version <v> --pack-compatible-core <v> \\
        [--existing-database-url <value-or-empty>]

Every other flag (``--program-data-root``, ``--server-pack-path``,
``--initdb-path``, hosts/ports, database name/username, PostgreSQL major
version) has a derived or product default (:func:`resolve_provision_paths`)
and exists mainly so tests can override it without touching a real
filesystem layout.

Password handling (credential-sensitive, read this before changing anything
here):

* The password is generated ONLY on the fresh-provisioning path
  (:data:`ProvisionCliAction.RUN`) -- never on a no-op or fail-loud path,
  and never twice for the same cluster.
* It is placed into exactly ONE output surface this process controls: the
  single ``CIVICCAST_DATABASE_URL=...`` line printed to stdout
  (:func:`format_handoff_line`). Every other write this module performs
  (``sys.stderr.write`` progress lines) is static text or a phase name --
  never the password or a URL containing it. Grepping this file for
  ``print(`` finds exactly THREE call sites: the DatabaseUrl handoff line and
  the two :func:`format_setup_nonce_line` calls, which carry the installer
  handoff NONCE (a different secret, on its own distinctly prefixed line --
  see :data:`SETUP_NONCE_MARKER_PREFIX`) and never the password.
* ``civiccast.native.provision.orchestrator`` never writes the password into
  a journal history entry, the recovery document, or a log line -- verified
  by inspection: every ``_persist``/``_halt`` call's ``detail`` string is
  static or built from ``PostgresClusterDecision``/``NatsStoreDecision``
  text, which never reference ``context.database_password``.
* CORRECTED 2026-07-30 (municipal-shared-PC hardening fix; the previous
  revision of this bullet claimed the password's on-disk persistence in
  ``ProvisionJournal.context`` was a deliberate, load-bearing design decision
  "needed so a KILLED run resumed by a NEW process can still resolve the
  final ``DatabaseUrl`` on completion" -- an independently re-verified audit
  found the journal directory was NOT actually ACL'd as that claim assumed,
  and by-inspection re-checking of the resume path shows the claim's own
  JUSTIFICATION was also wrong: no resume path ever reads
  ``journal.context.database_password`` back. ``run_provision``'s resume
  branch (``orchestrator._drive_forward(existing, seams)``) drives the
  LOADED journal's phase forward using ``seams`` built in THIS invocation of
  ``main()`` from a FRESHLY generated password (line ~414 below), not the
  journal's persisted one; and this file's own final
  ``resolve_database_url(plan=plan, context=context)`` call (line ~427)
  uses that same fresh, never-reloaded ``context`` too -- never
  ``outcome.journal.context``. The persisted value was therefore dead data
  with a false justification.
  ``civiccast.native.provision.journal.write_journal`` now redacts
  ``context.database_password`` to a fixed, non-secret marker before
  writing the journal to disk (the in-memory object this process holds is
  untouched) and additionally hardens the state root directory's own DACL
  to SYSTEM + Administrators -- see that module's docstring.
* The Rust caller (``native_service_registration::run_native_provision``)
  captures this process's stdout/stderr WITHOUT ever printing it, parses the
  one handoff line, and writes the value straight to
  ``HKLM\\SOFTWARE\\CivicCast\\Native\\DatabaseUrl`` via the existing
  ``write_database_url`` (in-process function call, not a second CLI
  subprocess -- so the password never appears on a second process's argv
  either).
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from civiccast.native.pgdata_acl import PgDataAclError
from civiccast.native.provision.journal import JournalError, journal_path
from civiccast.native.provision.models import (
    ProvisionContext,
    ProvisionJournal,
    ProvisionPhase,
    ProvisionPlan,
    resolve_database_url,
)
from civiccast.native.provision.orchestrator import (
    halt_adopt_foreign_cluster,
    halt_resume_credential_lost,
    run_provision,
)
from civiccast.native.provision.seams import (
    AdoptionForeignClusterError,
    build_default_seams_for,
    migrate_provisioned_schema,
    pg_ctl_path_for,
    psql_path_for,
    reset_cluster_credential,
)
from civiccast.native.setup_nonce import generate_setup_nonce, validate_setup_nonce

# ---------------------------------------------------------------------------
# Exit codes -- the installer branches on a number, not stderr text (same
# contract as civiccast.native.upgrade.__main__'s _EXIT_CODES).
# ---------------------------------------------------------------------------

EXIT_SUCCESS = 0  #: freshly provisioned COMPLETE, or a clean no-op reuse
EXIT_PROVISIONING_FAILED = 10  #: engine halted at FAILED; recovery doc emitted
EXIT_REPAIR_NEEDED = 20  #: existing cluster, no registry value -- D5 territory
#: C1 fix (2026-07-31): the engine provisioned cluster/role/database
#: (COMPLETE) but the post-provision schema migration to alembic head
#: failed. A DISTINCT number in the same decade-spaced band as the codes
#: above (and as ``civiccast.native.upgrade.__main__``'s ``_EXIT_CODES``,
#: which also uses 30 for its own fourth outcome) so the installer can name
#: the exact failed step; the handoff line is NOT printed on this path, so
#: the Rust caller never writes a DatabaseUrl for a schema-less database.
EXIT_SCHEMA_MIGRATION_FAILED = 30
EXIT_UNEXPECTED = 40  #: programming/environment fault (e.g. a malformed key)
#: F6 fix (pgdata-DACL audit follow-up, 2026-08-01): migrate_provisioned_schema's
#: SECOND normalize_pgdata_acl call (inside _start_provisioned_cluster, run
#: again here to start the just-provisioned cluster back up for the schema
#: migration) can itself raise PgDataAclError. Before this fix that fell into
#: the same bare ``except Exception`` as an alembic failure below and was
#: misreported as EXIT_SCHEMA_MIGRATION_FAILED with the message "'alembic
#: upgrade head' did not complete" -- wrong step name, and a decision-relevant
#: one: exit 30 (like every code above 0) still suppresses the handoff line,
#: which is CORRECT here (a machine whose data-directory ACL could not be
#: normalized must not advertise a DatabaseUrl), but the next install then
#: reads "no registry value, cluster present" and lands on
#: FAIL_LOUD_CREDENTIAL_LOST (exit 20, documented above as NOT fixed by a
#: repair install) -- a confusing dead end for a defect that is actually a
#: filesystem/ACL permission problem, not a lost credential. Next unused value
#: in the decade-spaced band above (0/10/20/30/40) so the installer can name
#: this exact step distinctly from both.
EXIT_SCHEMA_ACL_NORMALIZATION_FAILED = 50


# ---------------------------------------------------------------------------
# Password generation
# ---------------------------------------------------------------------------

#: 256 bits of entropy -- generous for a machine-generated, never-typed
#: credential. ``secrets.token_urlsafe`` draws from the URL-safe base64
#: alphabet (A-Z a-z 0-9 - _), which is already shell-safe, registry-safe,
#: and contains no character ``build_database_url``'s ``quote(..., safe="")``
#: needs to escape awkwardly -- the provision models' own percent-encoding
#: still runs on top, this charset just avoids gratuitous escaping.
_DEFAULT_PASSWORD_ENTROPY_BYTES = 32
_MIN_PASSWORD_ENTROPY_BYTES = 16  # 128 bits -- refuse anything weaker


def generate_database_password(*, entropy_bytes: int = _DEFAULT_PASSWORD_ENTROPY_BYTES) -> str:
    """A cryptographically random password for the provisioned PostgreSQL
    role. Pure w.r.t. everything except the CSPRNG itself -- no I/O."""

    if entropy_bytes < _MIN_PASSWORD_ENTROPY_BYTES:
        raise ValueError(
            f"entropy_bytes must be at least {_MIN_PASSWORD_ENTROPY_BYTES} "
            f"(128 bits) for a database credential, got {entropy_bytes!r}"
        )
    return secrets.token_urlsafe(entropy_bytes)


# ---------------------------------------------------------------------------
# Handoff marker: the ONLY surface the resolved DatabaseUrl (and therefore
# the password) is ever printed to. A unique prefix on its own line so the
# Rust caller's parser cannot confuse it with any other stdout noise.
# ---------------------------------------------------------------------------

HANDOFF_MARKER_PREFIX = "CIVICCAST_DATABASE_URL="


def format_handoff_line(database_url: str) -> str:
    if "\n" in database_url or "\r" in database_url:
        raise ValueError("database_url must not contain newline characters")
    return f"{HANDOFF_MARKER_PREFIX}{database_url}"


def parse_handoff_line(captured_stdout: str) -> str | None:
    """Find the ONE handoff line among arbitrary captured stdout, mirrored by
    the Rust side's own parser (``native_service_registration::
    parse_provision_handoff``) so both ends agree on the exact same format
    without either importing the other."""

    for line in captured_stdout.splitlines():
        if line.startswith(HANDOFF_MARKER_PREFIX):
            return line[len(HANDOFF_MARKER_PREFIX) :]
    return None


# ---------------------------------------------------------------------------
# Setup-nonce handoff: the SAME marker-line mechanism, for the installer
# handoff nonce (`civiccast.native.setup_nonce`).
#
# The nonce is generated here, at provision time, and handed to the already-
# elevated Rust installer, which persists it into the ACL-hardened
# HKLM\SOFTWARE\CivicCast\Native key beside DatabaseUrl. It travels on stdout
# rather than an argv for exactly the reason the DatabaseUrl does: an argv is
# world-readable to any process that can enumerate command lines.
#
# Unlike the DatabaseUrl line, this one is printed on EVERY successful exit --
# including NOOP_REUSE_EXISTING, where no cluster work happens at all. The
# nonce is a per-install handoff token, not a credential bound to the
# preserved cluster, so a reinstall/upgrade over an existing database must
# still end up with a usable one. A station provisioned by a build from before
# this existed otherwise has no nonce at all and can never complete setup.
# ---------------------------------------------------------------------------

SETUP_NONCE_MARKER_PREFIX = "CIVICCAST_SETUP_NONCE="


def format_setup_nonce_line(nonce: str) -> str:
    """The one stdout line carrying the setup nonce.

    Re-validates against the shared envelope rather than trusting the caller:
    this value ends up in the installer's handoff URL query string and in a
    registry write, and an out-of-envelope value would be rejected at the far
    end anyway -- failing here says why, instead of silently producing a line
    the Rust parser discards.
    """

    validated = validate_setup_nonce(nonce)
    if validated is None:
        raise ValueError(
            "setup nonce must be 16-256 URL-safe characters (A-Z a-z 0-9 - _), "
            "matching the installer's own validated_setup_nonce envelope"
        )
    return f"{SETUP_NONCE_MARKER_PREFIX}{validated}"


def parse_setup_nonce_line(captured_stdout: str) -> str | None:
    """Mirrored by the Rust side's ``parse_provision_setup_nonce``."""

    for line in captured_stdout.splitlines():
        if line.startswith(SETUP_NONCE_MARKER_PREFIX):
            return validate_setup_nonce(line[len(SETUP_NONCE_MARKER_PREFIX) :])
    return None


# ---------------------------------------------------------------------------
# Idempotency: the no-op / fail-loud decision matrix (pure, no I/O)
# ---------------------------------------------------------------------------


class ProvisionCliAction(StrEnum):
    """What the CLI does before ever touching a real seam.

    | cluster exists | registry value present | journal state                        | action                     |
    |-----------------|-------------------------|----------------------------------------|----------------------------|
    | no               | (irrelevant)            | (irrelevant)                           | RUN (fresh provisioning)   |
    | yes              | yes                     | (irrelevant)                           | NOOP_REUSE_EXISTING        |
    | yes              | no                      | resumable (non-terminal, pre-credential) | RUN (resume via journal) |
    | yes              | no                      | credential lost (non-terminal, at/past POSTGRES_CLUSTER_READY) | FAIL_LOUD_CREDENTIAL_LOST |
    | yes              | no                      | none / terminal                        | ADOPT_EXISTING (N-15)      |

    N-15: the last row USED to be ``FAIL_LOUD_MISSING_REGISTRY`` -- but a
    surviving cluster with no registry value and no in-flight journal is the
    exact, expected state uninstall leaves behind: chain M / security fix F-02
    deletes the ``DatabaseUrl`` credential while PRESERVING the product data
    directory (so the credential lives nowhere and cannot be reconstructed),
    yet the installer already promises the operator that "your recorded data
    and database are preserved by uninstall and will be adopted by the new
    installation". Refusing here broke that promise on every
    uninstall-then-reinstall. ``ADOPT_EXISTING`` keeps it: the CLI
    re-establishes a FRESH credential on the SAME cluster (no initdb, no
    database drop -- station data preserved) via
    :func:`~civiccast.native.provision.seams.reset_cluster_credential`, whose
    own LIVE ownership check fails loud
    (:class:`~civiccast.native.provision.seams.AdoptionForeignClusterError` ->
    :func:`~civiccast.native.provision.orchestrator.halt_adopt_foreign_cluster`)
    on a cluster the product did not create -- so "never touch a foreign
    cluster" is preserved, moved to where it can be verified against the live
    cluster instead of guessed offline. ``FAIL_LOUD_MISSING_REGISTRY`` remains
    as the label that foreign-cluster refusal is reported under.

    On a re-install over an existing cluster, the registry's ``DatabaseUrl``
    is the SOURCE OF TRUTH (task instruction): reusing it means the CLI never
    regenerates a password it cannot re-derive, and never re-runs ``initdb``
    over a cluster the orchestrator's own idempotency logic would refuse to
    touch anyway.

    Task #55 (audit-lite FINDING-003): a cluster with NO registry value is
    NOT automatically "an unrelated, previously-successful cluster needing a
    repair install" -- it is exactly what an INTERRUPTED provisioning run
    also leaves behind (``initdb`` at ``POSTGRES_CLUSTER_READY`` succeeded,
    but the run was killed -- process kill, power loss, AV interference,
    a Sandbox timeout -- before ever reaching the end and handing off
    ``DatabaseUrl`` to the Rust caller). :func:`probe_resumable_journal`
    distinguishes the two: a present, non-terminal
    (:class:`~civiccast.native.provision.models.ProvisionPhase`) journal at
    this ``state_root`` is proof a run is genuinely IN PROGRESS, not that
    this is a foreign cluster -- that case now resumes via
    :func:`~civiccast.native.provision.orchestrator.run_provision`'s own
    idempotent journal-replay (each forward step re-detects and reuses
    already-landed state) instead of being misdirected to
    ``FAIL_LOUD_MISSING_REGISTRY``. A cluster with NO registry value AND no
    resumable journal is still not a case this CLI may guess its way out of
    -- it surfaces as a fail-loud condition requiring operator repair (D5's
    territory), never a silent regenerate-and-hope.

    Task #57 (disclosed in commit abdba55b): resuming is only SAFE while the
    journal is still BEFORE ``POSTGRES_CLUSTER_READY`` -- at or past that
    phase, ``initdb --pwfile`` already baked a real credential into the
    cluster, and the RUN branch would drive forward with a FRESHLY generated
    (therefore different, and never reconciled) password
    (:func:`probe_credential_lost_journal` detects this, distinct from
    :func:`probe_resumable_journal`). ``FAIL_LOUD_CREDENTIAL_LOST`` halts
    that case instead of silently misdirecting it into the RUN branch --
    see :func:`~civiccast.native.provision.orchestrator.
    halt_resume_credential_lost` for the honest, situation-specific recovery
    document it writes (never the generic "needs a repair install" message,
    which does not describe or fix this state).
    """

    RUN = "run"
    NOOP_REUSE_EXISTING = "noop_reuse_existing"
    ADOPT_EXISTING = "adopt_existing"
    FAIL_LOUD_MISSING_REGISTRY = "fail_loud_missing_registry"
    FAIL_LOUD_CREDENTIAL_LOST = "fail_loud_credential_lost"


def decide_provision_cli_action(
    *,
    cluster_exists: bool,
    existing_database_url: str | None,
    journal_resumable: bool = False,
    credential_lost: bool = False,
) -> ProvisionCliAction:
    if not cluster_exists:
        return ProvisionCliAction.RUN
    has_registry_value = bool(existing_database_url and existing_database_url.strip())
    if has_registry_value:
        return ProvisionCliAction.NOOP_REUSE_EXISTING
    if journal_resumable:
        return ProvisionCliAction.RUN
    if credential_lost:
        return ProvisionCliAction.FAIL_LOUD_CREDENTIAL_LOST
    # N-15: a cluster that EXISTS with NO registry value and NO in-flight
    # (resumable / credential-lost) journal is the exact state uninstall
    # leaves behind BY DESIGN -- chain M / security fix F-02 deletes the
    # DatabaseUrl credential while deliberately PRESERVING the product data
    # directory (station data). This used to FAIL_LOUD_MISSING_REGISTRY, which
    # aborted every uninstall-then-reinstall over preserved data; it now ADOPTS
    # the surviving cluster (re-establishing a fresh credential on it WITHOUT
    # re-initializing or dropping any data -- see reset_cluster_credential).
    # The "is this genuinely the product's own cluster, or a foreign one at
    # the same path?" question is NOT guessed offline here: it is answered by a
    # LIVE ownership check inside the adoption seam, which fails loud
    # (AdoptionForeignClusterError) rather than ever taking over foreign data.
    return ProvisionCliAction.ADOPT_EXISTING


def probe_cluster_exists(postgres_data_dir: str) -> bool:
    """A CLI-level pre-check, separate from (and cheaper than) the
    orchestrator's own :func:`~civiccast.native.provision.models.
    evaluate_postgres_cluster` -- this one only answers "does *anything*
    live here yet", to decide whether the CLI should even attempt a run at
    all, before any password is generated."""

    return (Path(postgres_data_dir) / "PG_VERSION").exists()


def probe_resumable_journal(state_root: str) -> bool:
    """Task #55 (audit-lite FINDING-003), narrowed by task #57: True iff
    ``state_root`` holds a valid, NON-TERMINAL provisioning journal whose
    phase is still BEFORE ``POSTGRES_CLUSTER_READY`` -- i.e. a PRIOR
    invocation of this CLI got partway through provisioning but was
    interrupted before ``initdb`` ever ran, so a freshly generated password
    is still safe to drive forward with.

    This is the CLI-level signal that distinguishes an interrupted
    mid-provisioning retry from a genuinely foreign PostgreSQL cluster living
    at the same data directory: only the former should resume via
    :func:`~civiccast.native.provision.orchestrator.run_provision`; a
    ``COMPLETE``/``FAILED`` terminal journal, or no journal at all, still
    leaves the caller to fall back to the registry-value check
    (:func:`decide_provision_cli_action`).

    Task #57 (disclosed in commit abdba55b): a non-terminal journal AT OR
    PAST ``POSTGRES_CLUSTER_READY`` used to also count as "resumable" here,
    but resuming that one regenerates a password the already-initialized
    cluster's REAL credential (set once, by ``initdb --pwfile``, at that
    phase) will reject. That case is no longer "resumable" at all -- see
    :func:`probe_credential_lost_journal`, which recognizes it and gives the
    caller an honest, distinct halt instead.

    Propagates :class:`~civiccast.native.provision.journal.JournalError`
    UNCHANGED for a present-but-corrupt journal -- a journal this engine
    cannot trust must never be silently treated as either resumable or not
    (house rule: "fail-loud on any unexpected state, never silently
    repair" -- :mod:`civiccast.native.provision.orchestrator`'s module
    docstring); the caller decides how to surface that fault.
    """

    from civiccast.native.provision.journal import load_journal

    journal = load_journal(state_root)
    return (
        journal is not None
        and not journal.phase.is_terminal
        and journal.phase.rank < ProvisionPhase.POSTGRES_CLUSTER_READY.rank
    )


def probe_credential_lost_journal(state_root: str) -> ProvisionJournal | None:
    """Task #57 (disclosed in commit abdba55b): the companion probe to
    :func:`probe_resumable_journal` for the ONE other non-terminal case that
    function no longer treats as safely resumable -- a journal AT OR PAST
    ``POSTGRES_CLUSTER_READY``. Returns the loaded journal (so the caller can
    hand it straight to :func:`~civiccast.native.provision.orchestrator.
    halt_resume_credential_lost` without a second disk read) when that
    condition holds, else ``None`` (no journal, a terminal journal, or a
    journal still safely resumable via :func:`probe_resumable_journal`).

    Propagates :class:`~civiccast.native.provision.journal.JournalError`
    UNCHANGED for a present-but-corrupt journal, exactly like
    :func:`probe_resumable_journal`.
    """

    from civiccast.native.provision.journal import load_journal

    journal = load_journal(state_root)
    if (
        journal is not None
        and not journal.phase.is_terminal
        and journal.phase.rank >= ProvisionPhase.POSTGRES_CLUSTER_READY.rank
    ):
        return journal
    return None


# ---------------------------------------------------------------------------
# Path derivation
# ---------------------------------------------------------------------------

_PROGRAM_DATA_SUBDIR = "CivicCast"


@dataclass(frozen=True)
class ProvisionPaths:
    program_data_root: str
    state_root: str
    postgres_data_dir: str
    postgres_config_path: str
    postgres_hba_path: str
    nats_store_dir: str
    nats_config_path: str
    server_pack_path: str
    initdb_path: str


def resolve_provision_paths(
    *,
    install_root: str,
    program_data_root: str | None = None,
    server_pack_path: str | None = None,
    initdb_path: str | None = None,
) -> ProvisionPaths:
    """Derive every filesystem location a provisioning run needs from two
    roots: ``install_root`` (Program Files) and ``program_data_root``
    (ProgramData, default the ``PROGRAMDATA`` env var -- the SAME convention
    :func:`civiccast.native.supervisor.children.default_egress_work_dir` and
    :data:`civiccast.native.supervisor.service.DEFAULT_LOG_ROOT` already
    use). String-built, not ``pathlib.Path``, for the same reason
    ``default_egress_work_dir`` gives: the Windows-style backslash path must
    be identical regardless of the host OS running this pure module's tests.

    PostgreSQL data + the NATS JetStream store share ONE
    ``<program_data_root>\\CivicCast\\data`` tree (alongside the existing
    egress work dir at ``...\\data\\egress``), so a single ACL boundary
    covers all of it. ``postgresql.conf``/``pg_hba.conf`` MUST live INSIDE
    ``postgres_data_dir`` -- not a style choice: ``postgres_child_spec`` in
    :mod:`civiccast.native.supervisor.children` launches ``pg_ctl start -D
    <data_dir> -w`` with no ``-c config_file=`` override, so PostgreSQL only
    ever reads its default ``$PGDATA/postgresql.conf``/``$PGDATA/pg_hba.conf``
    locations; writing the provisioned config anywhere else would be
    silently ignored by the real server.

    ``server_pack_path``/``initdb_path`` default to a
    ``packs\\native-server-binaries\\`` convention under ``install_root`` --
    a CODER DECISION, not a spec-pinned value: no earlier work package
    established where an extracted server-binaries pack lands on disk (the
    existing component-pack acquisition flow, ``--civiccast-acquire-channel``
    / ``--civiccast-import-station``, is an operator/cache-root-driven step
    with no fixed staged-directory convention of its own yet -- see
    ``nsis-hooks-native.nsh``'s own comment on this). Documented here and in
    the WP2 evidence file so a later work package that establishes a
    different pack-staging convention has one place to change it; both
    parameters remain overridable for exactly that reason.
    """

    pd_root = (program_data_root or os.environ.get("PROGRAMDATA", r"C:\ProgramData")).rstrip("\\/")
    civiccast_root = f"{pd_root}\\{_PROGRAM_DATA_SUBDIR}"
    postgres_data_dir = f"{civiccast_root}\\data\\pgdata"
    nats_store_dir = f"{civiccast_root}\\data\\nats-store"

    install = install_root.rstrip("\\/")
    default_server_pack_path = f"{install}\\packs\\native-server-binaries.ccpack"
    default_initdb_path = f"{install}\\packs\\native-server-binaries\\payload\\bin\\initdb.exe"

    return ProvisionPaths(
        program_data_root=pd_root,
        state_root=f"{civiccast_root}\\provision",
        postgres_data_dir=postgres_data_dir,
        postgres_config_path=f"{postgres_data_dir}\\postgresql.conf",
        postgres_hba_path=f"{postgres_data_dir}\\pg_hba.conf",
        nats_store_dir=nats_store_dir,
        nats_config_path=f"{civiccast_root}\\config\\nats-server.conf",
        server_pack_path=server_pack_path or default_server_pack_path,
        initdb_path=initdb_path or default_initdb_path,
    )


# ---------------------------------------------------------------------------
# Pack public key decoding (a PUBLIC key -- not credential-sensitive; safe to
# pass on argv, unlike the password)
# ---------------------------------------------------------------------------

_ED25519_PUBLIC_KEY_BYTES = 32


def decode_pack_public_key(b64_value: str) -> Ed25519PublicKey:
    import base64

    raw = base64.b64decode(b64_value, validate=True)
    if len(raw) != _ED25519_PUBLIC_KEY_BYTES:
        raise ValueError(
            f"pack public key must be exactly {_ED25519_PUBLIC_KEY_BYTES} bytes, got {len(raw)}"
        )
    return Ed25519PublicKey.from_public_bytes(raw)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m civiccast.native.provision",
        description=(
            "Run the journaled CivicCast (Native) PostgreSQL/NATS provisioning engine (spec D4)."
        ),
    )
    parser.add_argument("--install-root", required=True)
    parser.add_argument("--owner-run-id", required=True)
    parser.add_argument("--pack-signing-key-id", required=True)
    parser.add_argument("--pack-public-key-base64", required=True)
    parser.add_argument("--pack-product-version", required=True)
    parser.add_argument("--pack-compatible-core", required=True)
    parser.add_argument(
        "--existing-database-url",
        default="",
        help="The CURRENT HKLM DatabaseUrl value (empty on a fresh install).",
    )
    parser.add_argument("--program-data-root", default=None)
    parser.add_argument("--server-pack-path", default=None)
    parser.add_argument("--initdb-path", default=None)
    parser.add_argument("--postgres-host", default="127.0.0.1")
    parser.add_argument("--postgres-port", type=int, default=5432)
    parser.add_argument("--nats-host", default="127.0.0.1")
    parser.add_argument("--nats-port", type=int, default=4222)
    parser.add_argument("--database-name", default="civiccast")
    parser.add_argument("--database-username", default="civiccast_svc")
    parser.add_argument("--postgres-major-version", default="17")
    return parser


# ---------------------------------------------------------------------------
# Plan / context assembly (pure)
# ---------------------------------------------------------------------------


def build_plan_and_context(
    *, paths: ProvisionPaths, args: argparse.Namespace, database_password: str
) -> tuple[ProvisionPlan, ProvisionContext]:
    plan = ProvisionPlan(
        postgres_major_version=args.postgres_major_version,
        database_name=args.database_name,
        database_username=args.database_username,
        server_pack_product_version=args.pack_product_version,
        server_pack_compatible_core=args.pack_compatible_core,
        server_pack_signing_key_id=args.pack_signing_key_id,
    )
    context = ProvisionContext(
        postgres_host=args.postgres_host,
        postgres_port=args.postgres_port,
        postgres_data_dir=paths.postgres_data_dir,
        postgres_config_path=paths.postgres_config_path,
        postgres_hba_path=paths.postgres_hba_path,
        database_password=database_password,
        nats_host=args.nats_host,
        nats_port=args.nats_port,
        nats_store_dir=paths.nats_store_dir,
        nats_config_path=paths.nats_config_path,
        server_pack_path=paths.server_pack_path,
        state_root=paths.state_root,
        owner_run_id=args.owner_run_id,
    )
    return plan, context


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


def _run_engine_and_finish(
    *,
    paths: ProvisionPaths,
    args: argparse.Namespace,
    plan: ProvisionPlan,
    context: ProvisionContext,
    seams: object,
) -> int:
    """Drive the journaled provisioning engine to COMPLETE, migrate the schema
    to alembic head, and print the DatabaseUrl + setup-nonce handoff lines.

    Shared verbatim by the RUN (fresh install) and ADOPT_EXISTING (N-15
    reinstall-over-preserved-data) paths: both reach this point with a fresh
    ``database_password`` already established for ``context`` -- RUN via
    ``initdb --pwfile`` (baked when the cluster is created), ADOPT via
    :func:`~civiccast.native.provision.seams.reset_cluster_credential` (set on
    the surviving cluster before this runs). Because the ADOPT path's cluster
    already exists, the engine here DETECTS and REUSES it (no initdb) and
    DETECTS and REUSES its database (no CREATE) -- station data is preserved;
    the only difference from RUN is that no data was created, only adopted.
    """

    outcome = run_provision(plan, context, seams)
    sys.stderr.write(f"provision outcome: {outcome.phase.value}\n")
    if not outcome.ok:
        return EXIT_PROVISIONING_FAILED

    database_url = resolve_database_url(plan=plan, context=context)

    # C1 fix (2026-07-31): the engine created cluster/role/database but NO
    # tables -- on a first-ever install the NSIS chain's D3 upgrade engine
    # (the product's only other alembic runner) is skipped by design
    # ("fresh-install gate"), so this is the ONE place the fresh schema can
    # be brought to alembic head. Runs the same in-process migration
    # mechanism D3 uses (see run_schema_migration_to_head), idempotently,
    # against the real freshly-provisioned DatabaseUrl. Fail-loud with its
    # own step-identifying exit code; the handoff line is NOT printed on
    # failure, so no registry value is ever written for a schema-less DB.
    # (Idempotent, so the ADOPT path's already-migrated database is a safe
    # no-op here too.)
    try:
        migrate_provisioned_schema(
            context,
            pg_ctl_path=pg_ctl_path_for(paths.initdb_path),
            database_url=database_url,
            install_root=args.install_root,
        )
    except PgDataAclError as exc:
        # F6 (audit follow-up): migrate_provisioned_schema's own
        # normalize_pgdata_acl call (inside _start_provisioned_cluster,
        # re-starting the just-provisioned cluster for the migration) failed
        # before 'pg_ctl start' -- never even reached alembic. Caught
        # DISTINCTLY, ahead of the generic handler below, so this is never
        # misreported as a schema-migration/alembic failure: same
        # credential-redaction treatment (defensive here too, since
        # PgDataAclError's own message is static/path-only and does not
        # embed the URL or password), its own step-identifying exit code,
        # and the handoff line is still correctly suppressed -- a machine
        # whose pgdata ACL could not be normalized must not advertise a
        # DatabaseUrl.
        detail = str(exc).replace(database_url, "[database-url redacted]")
        detail = detail.replace(context.database_password, "[password redacted]")
        sys.stderr.write(
            f"provision outcome: schema_acl_normalization_failed (the database was "
            f"provisioned but its data directory's ACL could not be normalized before "
            f"restarting the cluster for schema migration -- 'alembic upgrade head' was "
            f"never attempted: {detail})\n"
        )
        return EXIT_SCHEMA_ACL_NORMALIZATION_FAILED
    except Exception as exc:
        # Never let the generated credential reach stderr: SQLAlchemy/
        # alembic error text can embed the connection URL. Static prefix +
        # redacted detail only.
        detail = str(exc).replace(database_url, "[database-url redacted]")
        detail = detail.replace(context.database_password, "[password redacted]")
        sys.stderr.write(
            f"provision outcome: schema_migration_failed (the database was provisioned "
            f"but 'alembic upgrade head' did not complete: {detail})\n"
        )
        return EXIT_SCHEMA_MIGRATION_FAILED
    sys.stderr.write("provision outcome: schema migrated to alembic head\n")

    print(format_handoff_line(database_url))
    print(format_setup_nonce_line(generate_setup_nonce()))
    return EXIT_SUCCESS


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    paths = resolve_provision_paths(
        install_root=args.install_root,
        program_data_root=args.program_data_root,
        server_pack_path=args.server_pack_path,
        initdb_path=args.initdb_path,
    )

    cluster_exists = probe_cluster_exists(paths.postgres_data_dir)

    # Task #55 (audit-lite FINDING-003), narrowed by task #57: only consulted
    # in the ONE branch it can change (cluster exists, no registry value) --
    # never probed on a fresh install (cluster_exists=False, always RUN
    # regardless) or a registry-value reinstall (NOOP_REUSE_EXISTING, which
    # never touches the journal today either), so a stray/corrupt journal at
    # this state_root cannot regress either of those two already-correct
    # paths.
    journal_resumable = False
    credential_lost_journal: ProvisionJournal | None = None
    has_registry_value = bool(args.existing_database_url and args.existing_database_url.strip())
    if cluster_exists and not has_registry_value:
        try:
            journal_resumable = probe_resumable_journal(paths.state_root)
            if not journal_resumable:
                # Only the credential-lost probe needs a second read, and
                # only when the first one already found nothing safely
                # resumable -- a corrupt journal already raised above.
                credential_lost_journal = probe_credential_lost_journal(paths.state_root)
        except JournalError as exc:
            sys.stderr.write(
                "provision outcome: unexpected error reading the provisioning "
                f"journal at {paths.state_root!r}: {exc}\n"
            )
            return EXIT_UNEXPECTED

    action = decide_provision_cli_action(
        cluster_exists=cluster_exists,
        existing_database_url=args.existing_database_url,
        journal_resumable=journal_resumable,
        credential_lost=credential_lost_journal is not None,
    )

    if action is ProvisionCliAction.NOOP_REUSE_EXISTING:
        sys.stderr.write(
            "provision outcome: noop_reuse_existing (an existing PostgreSQL cluster and "
            "an existing DatabaseUrl registry value were both found; neither was touched)\n"
        )
        # A fresh handoff nonce even on the no-op path: it is a per-install
        # token, not cluster state. See SETUP_NONCE_MARKER_PREFIX's section
        # comment -- without this a reinstall/upgrade over a preserved cluster
        # (and any station provisioned before the nonce existed) could never
        # complete setup.
        print(format_setup_nonce_line(generate_setup_nonce()))
        return EXIT_SUCCESS

    if action is ProvisionCliAction.FAIL_LOUD_CREDENTIAL_LOST:
        assert credential_lost_journal is not None
        outcome = halt_resume_credential_lost(credential_lost_journal)
        sys.stderr.write(
            "provision outcome: fail_loud_credential_lost (a previous provisioning attempt "
            f"at {paths.state_root!r} reached phase {credential_lost_journal.phase.value!r} "
            "(at or past 'postgres_cluster_ready') but never completed; its PostgreSQL "
            "cluster is already initialized with a credential that was never persisted to "
            "HKLM\\SOFTWARE\\CivicCast\\Native\\DatabaseUrl and cannot be reconstructed -- "
            "resuming would only regenerate a DIFFERENT password the cluster will reject. "
            "This is NOT fixed by a repair install; see the recovery document at "
            f"{outcome.journal.recovery_document_path!r})\n"
        )
        return EXIT_REPAIR_NEEDED

    # action is RUN or ADOPT_EXISTING from here on: both need a decoded pack
    # key, a freshly generated password, and the real seam bundle.
    try:
        public_key = decode_pack_public_key(args.pack_public_key_base64)
    except Exception as exc:
        sys.stderr.write(f"provision outcome: unexpected error decoding pack public key: {exc}\n")
        return EXIT_UNEXPECTED

    database_password = generate_database_password()
    plan, context = build_plan_and_context(
        paths=paths, args=args, database_password=database_password
    )
    seams = build_default_seams_for(
        plan, context, public_key=public_key, initdb_path=paths.initdb_path
    )

    if action is ProvisionCliAction.ADOPT_EXISTING:
        # Verify the server-binaries pack BEFORE the credential reset executes
        # any of its binaries (pg_ctl/psql) -- the same "PACK_VERIFIED first,
        # before any binary runs" ordering the engine guarantees on a fresh
        # install (the pack is also D2-verified earlier in the NSIS chain, so
        # this is defense-in-depth). run_provision re-verifies idempotently
        # below; a failure here halts before the surviving cluster is touched.
        try:
            seams.verify_pack()
        except Exception as exc:
            detail = str(exc).replace(context.database_password, "[password redacted]")
            sys.stderr.write(
                "provision outcome: provisioning_failed (the server-binaries pack could not "
                f"be verified before adopting the surviving cluster: {detail})\n"
            )
            return EXIT_PROVISIONING_FAILED

        # N-15: re-establish a fresh credential ON the surviving, product-owned
        # cluster (chain M / F-02 deleted the old one; the data directory was
        # preserved). reset_cluster_credential fails loud
        # (AdoptionForeignClusterError) rather than ever adopting a cluster it
        # cannot prove the product created; a fresh scram credential is set on
        # ours, so every downstream engine/psql connection authenticates with
        # this run's password -- WITHOUT any initdb or database drop.
        try:
            adoption = reset_cluster_credential(
                context,
                plan,
                pg_ctl_path=pg_ctl_path_for(paths.initdb_path),
                psql_path=psql_path_for(paths.initdb_path),
            )
        except AdoptionForeignClusterError as exc:
            outcome = halt_adopt_foreign_cluster(plan, context, reason=str(exc))
            sys.stderr.write(
                "provision outcome: fail_loud_missing_registry (an existing PostgreSQL "
                f"cluster was found at {paths.postgres_data_dir!r} with no "
                "HKLM\\SOFTWARE\\CivicCast\\Native\\DatabaseUrl, but it could not be adopted "
                "because it is not a CivicCast-provisioned cluster this installer may take "
                f"over; see the recovery document at {outcome.journal.recovery_document_path!r})\n"
            )
            return EXIT_REPAIR_NEEDED
        except Exception as exc:
            # A real fault while re-establishing the credential (pg_ctl/psql
            # execution failure). Redact defensively even though the message is
            # static/path-only, and suppress the handoff line -- a cluster whose
            # credential could not be re-established must not advertise a
            # DatabaseUrl.
            detail = str(exc).replace(context.database_password, "[password redacted]")
            sys.stderr.write(
                "provision outcome: provisioning_failed (could not re-establish the database "
                f"credential on the surviving cluster at {paths.postgres_data_dir!r}: {detail})\n"
            )
            return EXIT_PROVISIONING_FAILED

        sys.stderr.write(f"provision outcome: adopt_existing ({adoption.detail})\n")

        # The prior provision left a terminal COMPLETE journal at this
        # state_root (or uninstall removed it). Either way, run_provision must
        # drive a FRESH forward run over the now-credential-reset cluster
        # rather than short-circuiting on the stale terminal journal, so clear
        # it first. The journal is provisioning-run bookkeeping, never station
        # data (which lives in pgdata, untouched).
        journal_path(context.state_root).unlink(missing_ok=True)

    return _run_engine_and_finish(paths=paths, args=args, plan=plan, context=context, seams=seams)


if __name__ == "__main__":  # pragma: no cover - process entry
    raise SystemExit(main())
