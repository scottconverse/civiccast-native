# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Database-only recovery seams over independently admitted installer inputs."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

from civiccast.db import connect_options
from civiccast.db.url import normalize_database_url
from civiccast.dr.backup import (
    _admit_postgres_environment,
    _assert_backup_quiescent,
    _postgres_query_options,
    _postgres_tool_environment,
    read_backup_manifest,
    snapshot_tables,
    verify_backup_integrity,
    write_integrity_manifest,
)
from civiccast.dr.models import BackupManifest, PostgresRolePrerequisites
from civiccast.dr.restore_drill import (
    capture_postgres_namespace_extensions,
    capture_postgres_role_prerequisites,
    prepare_disposable_postgres_roles,
    run_postgres_restore_drill,
)
from civiccast.native.upgrade.flat_recovery import FlatRecoveryError, _safe_path
from civiccast.native.upgrade.models import BackupRef
from civiccast.native.upgrade.seams import _manifest_blob_hash

_ARTIFACT = "database.pgdump"
_ROLES = "role-prerequisites.json"
_RECEIPT = "namespace-recovery.json"
_TOOLS = ("pg_dump", "pg_restore", "psql")
_CONNECT_TIMEOUT_SECONDS = 10


def _protected[T](operation: str, action: Callable[[], T]) -> T:
    try:
        return action()
    except FlatRecoveryError:
        raise
    except Exception:
        # Driver/tool errors can contain service credentials or SQL data.
        raise FlatRecoveryError(f"database recovery {operation} failed") from None


def _sha(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _header_hash(manifest: BackupManifest) -> str:
    blob = json.dumps(manifest.model_dump(mode="json", exclude={"integrity"}), sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _loopback_server(address: str | None) -> bool:
    # PostgreSQL inet::text includes /32 or /128, unlike ip_address input.
    return address is not None and ipaddress.ip_interface(address).ip.is_loopback


def _loopback_host(host: str) -> bool:
    if host.casefold().rstrip(".") == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or (
        isinstance(address, ipaddress.IPv6Address)
        and address.ipv4_mapped is not None
        and address.ipv4_mapped.is_loopback
    )


@dataclass(frozen=True)
class FlatVerificationTarget:
    """Independent disposable-cluster admission; never a source service URL."""

    database_url: str = field(repr=False)
    expected_pgdata: Path


@dataclass(frozen=True)
class FlatDatabaseContext:
    database_url: str = field(repr=False)
    pg_bin: Path
    expected_owned_pgdata: Path | None
    backup_root: Path
    expected_schema_revision: str | None
    owned_database: str
    owned_role: str | None
    owned_schema_names: tuple[str, ...] = ("civiccast",)
    verification_target: FlatVerificationTarget | None = None


@dataclass(frozen=True)
class FlatDatabaseSeams:
    backup: Callable[[str], BackupRef]
    verify_backup: Callable[[BackupRef], None]
    restore_database: Callable[[BackupRef], None]
    schema_revision: Callable[[], str | None]


def build_flat_database_seams(context: FlatDatabaseContext) -> FlatDatabaseSeams:
    """Bind old tools and one independently admitted, namespace-only destination.

    Entry owns lifecycle/quiescence and the protected directory. Owned PGDATA
    does not imply exclusive database ownership. Roles are never replayed.
    Unlike ordinary DR callers, this flat factory never drills on the source
    cluster: an independently admitted disposable verifier is mandatory.
    """
    admitted_verifier = context.verification_target
    if admitted_verifier is None:
        raise FlatRecoveryError("database recovery requires an independent disposable verifier")
    root = _safe_path(context.backup_root)
    tools_root = _safe_path(context.pg_bin)
    tools = {name: tools_root / (name + (".exe" if os.name == "nt" else "")) for name in _TOOLS}
    for path in tools.values():
        if not _safe_path(path).is_file():
            raise FlatRecoveryError("database recovery requires admitted old PostgreSQL tools")
    tool_hashes = {name: _sha(path) for name, path in tools.items()}
    url = make_url(normalize_database_url(context.database_url))
    if (
        url.drivername != "postgresql+psycopg"
        or not url.host
        or not url.username
        or url.database != context.owned_database
        or context.owned_schema_names != ("civiccast",)
        or (context.owned_role is not None and url.username != context.owned_role)
    ):
        raise FlatRecoveryError("database recovery service target is not independently bound")
    _protected(
        "connection option admission",
        lambda: _postgres_query_options(
            context.database_url, timeout_seconds=_CONNECT_TIMEOUT_SECONDS
        ),
    )
    _protected(
        "verification connection option admission",
        lambda: _postgres_query_options(
            admitted_verifier.database_url, timeout_seconds=_CONNECT_TIMEOUT_SECONDS
        ),
    )
    verification_url = _protected(
        "verification target",
        lambda: make_url(normalize_database_url(admitted_verifier.database_url)),
    )
    verification_pgdata = _safe_path(admitted_verifier.expected_pgdata)
    owned_pgdata = (
        _safe_path(context.expected_owned_pgdata) if context.expected_owned_pgdata else None
    )
    if (
        verification_url.drivername != "postgresql+psycopg"
        or verification_url.host not in {"127.0.0.1", "::1"}
        or verification_url.database != "postgres"
        or not verification_url.username
        or verification_pgdata == owned_pgdata
        or (
            (verification_url.host == url.host or _loopback_host(url.host))
            and (verification_url.port or 5432) == (url.port or 5432)
        )
    ):
        raise FlatRecoveryError(
            "database recovery verification target is not independently disposable"
        )
    target = {
        "host": url.host,
        "port": url.port or 5432,
        "database": url.database,
        "role": url.username,
        "schemas": list(context.owned_schema_names),
        "connection_options": _postgres_query_options(
            context.database_url, timeout_seconds=_CONNECT_TIMEOUT_SECONDS
        ),
    }

    def check_tools() -> None:
        if any(_sha(_safe_path(tools[name])) != expected for name, expected in tool_hashes.items()):
            raise FlatRecoveryError("database recovery old PostgreSQL tool identity changed")

    def engine() -> Engine:
        _admit_postgres_environment(context.database_url, timeout_seconds=_CONNECT_TIMEOUT_SECONDS)
        return create_engine(
            normalize_database_url(context.database_url),
            **connect_options(context.database_url, timeout_seconds=_CONNECT_TIMEOUT_SECONDS),
        )

    def tool(
        name: str,
        args: list[str],
        *,
        data: bytes | None = None,
        connect: bool = True,
        database: str | None = None,
    ) -> bytes:
        check_tools()
        env = _postgres_tool_environment(
            context.database_url, timeout_seconds=_CONNECT_TIMEOUT_SECONDS
        )
        connection_args = (
            [
                "--host",
                str(url.host),
                "--port",
                str(url.port or 5432),
                "--username",
                str(url.username),
                "--no-password",
                "--dbname",
                database or context.owned_database,
            ]
            if connect
            else []
        )
        result = subprocess.run(  # noqa: S603 -- pinned old tool, independent context, fixed argv; no shell
            [str(tools[name]), *args, *connection_args],
            input=data,
            capture_output=True,
            env=env,
            timeout=600,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if result.returncode:
            raise FlatRecoveryError(f"database recovery {name} failed")
        return result.stdout

    def admit(db: Engine) -> None:
        with db.connect() as connection:
            identity = connection.execute(
                text("SELECT current_database(), current_user, inet_server_addr()::text")
            ).one()
            if identity[0] != context.owned_database or identity[1] != url.username:
                raise FlatRecoveryError("database recovery connected to an unexpected identity")
            if owned_pgdata is not None:
                if not _loopback_server(identity[2]):
                    raise FlatRecoveryError("owned PostgreSQL recovery requires a loopback server")
                actual = connection.execute(text("SHOW data_directory")).scalar_one()
                if _safe_path(Path(actual)) != owned_pgdata:
                    raise FlatRecoveryError(
                        "owned PostgreSQL data directory does not match admission"
                    )
            if connection.execute(
                text("SELECT EXISTS(SELECT 1 FROM pg_event_trigger WHERE evtenabled <> 'D')")
            ).scalar_one():
                raise FlatRecoveryError("database recovery refuses enabled event triggers")

    def revision() -> str | None:
        db = engine()
        try:
            admit(db)
            with db.connect() as connection:
                rows = (
                    connection.execute(text("SELECT version_num FROM civiccast.alembic_version"))
                    .scalars()
                    .all()
                )
            if len(rows) != 1:
                raise FlatRecoveryError("database recovery requires a single source revision")
            return str(rows[0])
        finally:
            db.dispose()

    def prepare_verifier(proof: PostgresRolePrerequisites) -> str:
        verifier_url = admitted_verifier.database_url
        _admit_postgres_environment(verifier_url, timeout_seconds=_CONNECT_TIMEOUT_SECONDS)
        verifier = create_engine(
            normalize_database_url(verifier_url),
            **connect_options(verifier_url, timeout_seconds=_CONNECT_TIMEOUT_SECONDS),
        )
        try:
            with verifier.connect() as connection:
                identity = connection.execute(
                    text(
                        "SELECT current_database(),current_user,inet_server_addr()::text,inet_server_port()"
                    )
                ).one()
                actual_pgdata = _safe_path(
                    Path(connection.execute(text("SHOW data_directory")).scalar_one())
                )
                if (
                    identity[0] != "postgres"
                    or identity[1] != verification_url.username
                    or not _loopback_server(identity[2])
                    or identity[3] != (verification_url.port or 5432)
                    or actual_pgdata != verification_pgdata
                    or actual_pgdata == owned_pgdata
                ):
                    raise FlatRecoveryError(
                        "database recovery verification target identity mismatch"
                    )
                if connection.execute(
                    text(
                        "SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname NOT IN ('postgres','template0','template1'))"
                    )
                ).scalar_one():
                    raise FlatRecoveryError("database recovery verification target is not fresh")
            prepare_disposable_postgres_roles(verifier, proof)
        finally:
            verifier.dispose()
        return verifier_url

    def backup(destination: str) -> BackupRef:
        if _safe_path(Path(destination)) != root:
            raise FlatRecoveryError("database recovery backup destination does not match admission")
        check_tools()
        db = engine()
        try:
            admit(db)
            with db.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
                snapshot = str(connection.execute(text("SELECT pg_export_snapshot()")).scalar_one())
                source_revision = str(
                    connection.execute(
                        text("SELECT version_num FROM civiccast.alembic_version")
                    ).scalar_one()
                )
                if (
                    context.expected_schema_revision is not None
                    and source_revision != context.expected_schema_revision
                ):
                    raise FlatRecoveryError(
                        "database recovery source revision changed before backup"
                    )
                tables = snapshot_tables(db, connection=connection)
                if not tables:
                    raise FlatRecoveryError("database recovery refuses an empty namespace proof")
                extension_tables = connection.execute(
                    text(
                        "SELECT n.nspname,c.relname FROM pg_extension e "
                        "CROSS JOIN LATERAL unnest(e.extconfig) x(oid) "
                        "JOIN pg_class c ON c.oid=x.oid JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname <> 'civiccast'"
                    )
                ).all()
                extensions = capture_postgres_namespace_extensions(db)
                args = [
                    "--format=custom",
                    "--schema=civiccast",
                    "--snapshot",
                    snapshot,
                ]
                args.extend("--extension=" + _identifier(name) for name in extensions)
                args.extend(
                    "--exclude-table-data=" + _identifier(str(n)) + "." + _identifier(str(t))
                    for n, t in extension_tables
                )
                root.mkdir(parents=False, exist_ok=False)
                dump = tool("pg_dump", args)
                if not dump:
                    raise FlatRecoveryError("database recovery dump is empty")
                (root / _ARTIFACT).write_bytes(dump)
            _assert_backup_quiescent(tables, snapshot_tables(db))
            prerequisites = capture_postgres_role_prerequisites(db)
            (root / _ROLES).write_text(prerequisites.model_dump_json(), encoding="utf-8")
            manifest = BackupManifest(
                backup_id="flat-" + uuid4().hex,
                created_at=datetime.now(UTC),
                engine="postgres",
                db_artifact=_ARTIFACT,
                tables=tables,
                role_prerequisites_artifact=_ROLES,
                namespace_extensions=extensions,
            )
            receipt = {
                "target": target,
                "source_revision": source_revision,
                "manifest_header_sha256": _header_hash(manifest),
            }
            (root / _RECEIPT).write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
            manifest = manifest.model_copy(update={"integrity": write_integrity_manifest(root)})
            (root / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
            drill_name = "civiccast_flat_drill_" + uuid4().hex
            verifier_url = prepare_verifier(prerequisites)
            with db.connect() as connection:
                if connection.execute(
                    text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": drill_name}
                ).first():
                    raise FlatRecoveryError("database recovery scratch database already exists")
            report = run_postgres_restore_drill(
                backup_dir=root,
                manifest=manifest,
                source_database_url=context.database_url,
                restore_database_name=drill_name,
                pg_restore_command=[str(tools["pg_restore"])],
                psql_command=[str(tools["psql"])],
                expected_revision=source_revision,
                restore_target_database_url=verifier_url,
                timeout_seconds=_CONNECT_TIMEOUT_SECONDS,
            )
            if not report.ok:
                raise FlatRecoveryError("database recovery fresh-database restore drill failed")
            return BackupRef(
                backup_id=manifest.backup_id,
                backup_dir=str(root),
                manifest_hash=_manifest_blob_hash(manifest),
                db_artifact=_ARTIFACT,
                verified=True,
                restore_drill_ok=True,
            )
        finally:
            db.dispose()

    def unavailable(_reference: BackupRef) -> None:
        raise FlatRecoveryError("database namespace replacement is blocked by the local tool guard")

    def verified(reference: BackupRef) -> tuple[BackupManifest, PostgresRolePrerequisites, str]:
        check_tools()
        if (
            _safe_path(Path(reference.backup_dir)) != root
            or not reference.verified
            or not reference.restore_drill_ok
        ):
            raise FlatRecoveryError("database recovery requires its admitted verified backup")
        manifest = read_backup_manifest(_safe_path(root / "manifest.json").parent)
        if (
            manifest.backup_id != reference.backup_id
            or manifest.engine != "postgres"
            or manifest.db_artifact != _ARTIFACT
            or reference.db_artifact != _ARTIFACT
            or manifest.globals_artifact is not None
            or manifest.role_prerequisites_artifact != _ROLES
            or not manifest.namespace_extensions
            or not manifest.tables
            or _manifest_blob_hash(manifest) != reference.manifest_hash
            or {entry.member for entry in manifest.integrity} != {_ARTIFACT, _ROLES, _RECEIPT}
            or len(manifest.integrity) != 3
        ):
            raise FlatRecoveryError("database recovery backup contract changed")
        for entry in manifest.integrity:
            if _safe_path(root / entry.member).parent != root:
                raise FlatRecoveryError("database recovery artifact escaped its directory")
        if verify_backup_integrity(root, manifest):
            raise FlatRecoveryError("database recovery artifact integrity failed")
        receipt = json.loads((root / _RECEIPT).read_text(encoding="utf-8"))
        if receipt.get("target") != target or receipt.get("manifest_header_sha256") != _header_hash(
            manifest
        ):
            raise FlatRecoveryError("database recovery manifest/target identity changed")
        source_revision = receipt.get("source_revision")
        if not isinstance(source_revision, str) or not source_revision:
            raise FlatRecoveryError("database recovery has no captured source revision")
        if (
            context.expected_schema_revision is not None
            and source_revision != context.expected_schema_revision
        ):
            raise FlatRecoveryError("database recovery captured revision does not match admission")
        prerequisites = PostgresRolePrerequisites.model_validate_json(
            (root / _ROLES).read_text(encoding="utf-8")
        )
        return manifest, prerequisites, source_revision

    def verify(reference: BackupRef) -> None:
        verified(reference)

    return FlatDatabaseSeams(
        backup=lambda destination: _protected("backup", lambda: backup(destination)),
        verify_backup=lambda reference: _protected("verification", lambda: verify(reference)),
        restore_database=unavailable,
        schema_revision=lambda: _protected("revision read", revision),
    )
