# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Typer commands for routine encrypted station backup and offline restore."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer

if TYPE_CHECKING:
    from civiccast.dr.station_backup import StationBackupService

backup_app = typer.Typer(
    name="backup",
    help="Create, verify, inventory, or restore encrypted station backups.",
    no_args_is_help=True,
)


def _service() -> StationBackupService:
    # The runtime adapter owns path resolution, keyring access, and PostgreSQL
    # tool discovery so CLI commands cannot guess service locations.
    from civiccast.dr.station_backup_runtime import (
        build_station_backup_service,
        preflight_station_backup_cli,
    )

    try:
        preflight_station_backup_cli()
    except PermissionError as exc:
        raise typer.BadParameter(str(exc)) from None
    return build_station_backup_service()


def _passphrase(*, confirm: bool = False) -> str:
    phrase: str = typer.prompt("Recovery passphrase", hide_input=True)
    if len(phrase) < 12:
        raise typer.BadParameter("must contain at least 12 characters")
    if confirm:
        repeated: str = typer.prompt("Confirm recovery passphrase", hide_input=True)
        if phrase != repeated:
            raise typer.BadParameter("recovery passphrases do not match")
    return phrase


def _restore_database_target(explicit: str | None) -> str:
    """Never substitute the installed database for an omitted replacement target."""
    if explicit:
        return explicit
    documented = os.environ.get("CIVICCAST_TARGET_DATABASE_URL")
    legacy = os.environ.get("CIVICAST_TARGET_DATABASE_URL")
    if documented and legacy and documented != legacy:
        raise typer.BadParameter(
            "Conflicting restore database environment settings; use --target-database-url."
        )
    target = documented or legacy
    if not target:
        raise typer.BadParameter(
            "An explicit --target-database-url or CIVICCAST_TARGET_DATABASE_URL is required; "
            "restore never defaults to the installed database."
        )
    return target


def _database_target_label(value: str) -> str:
    from sqlalchemy.engine import make_url

    from civiccast.db.url import normalize_database_url

    try:
        url = make_url(normalize_database_url(value))
        if url.get_backend_name() not in {"postgresql", "sqlite"} or not url.database:
            raise ValueError("unsupported target")
        # Neither authentication nor arbitrary query parameters belong in a preview.
        return f"{url.get_backend_name()} host={url.host or 'local'} port={url.port or 'default'} database={url.database}"
    except Exception:
        raise typer.BadParameter(
            "Restore target must identify a PostgreSQL or SQLite database."
        ) from None


@backup_app.command("create")
def create_backup() -> None:
    """Create an encrypted backup using the configured destination and media roots."""

    from civiccast.dr.station_backup import BackupCreationError

    service = _service()
    phrase = _passphrase(confirm=True)
    try:
        artifact = service.create_backup(phrase)
    except BackupCreationError as exc:
        raise typer.BadParameter(str(exc)) from None
    typer.echo(
        f"Created encrypted station backup: {artifact.path.name} ({artifact.size_bytes} bytes)"
    )


@backup_app.command("verify")
def verify_backup(archive: Path) -> None:
    """Authenticate and verify every file in an archive."""

    result = _service().verify_backup(archive, _passphrase())
    typer.echo(
        f"Verified {result.backup_id}: {result.database_engine}, "
        f"{result.files_verified} files authenticated"
    )


@backup_app.command("inventory")
def inventory_backup(archive: Path) -> None:
    """Show the source paths that must be mapped on a replacement station."""

    typer.echo(json.dumps(_service().inspect_backup(archive, _passphrase()), indent=2))


@backup_app.command("restore")
def restore_backup(
    archive: Path,
    target_paths_json: Annotated[
        Path,
        typer.Option(
            "--target-paths-json", help="JSON map of old absolute paths to new absolute paths"
        ),
    ],
    confirmation: Annotated[str, typer.Option("--confirmation", help='must be exactly "RESTORE"')],
    target_database_url: Annotated[
        str | None,
        typer.Option(
            "--target-database-url",
            help="explicit replacement database URL; alternatively set CIVICCAST_TARGET_DATABASE_URL",
        ),
    ] = None,
    restore_local_station_settings: Annotated[
        bool,
        typer.Option(
            "--restore-local-station-settings",
            help="acknowledge that portable credentials/settings replace this machine's station settings",
        ),
    ] = False,
) -> None:
    """Restore while the station service and database writers are stopped."""

    if confirmation != "RESTORE":
        raise typer.BadParameter('must be exactly "RESTORE" after checking the replacement paths')
    raw: Any = json.loads(target_paths_json.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not all(
        isinstance(source, str) and isinstance(target, str) for source, target in raw.items()
    ):
        raise typer.BadParameter("path map must be a JSON object of absolute path strings")
    mappings = {source: Path(target) for source, target in raw.items()}
    effective_database_url = _restore_database_target(target_database_url)
    typer.echo(f"Restore database: {_database_target_label(effective_database_url)}")
    for target in mappings.values():
        typer.echo(f"Restore files: {target}")

    from civiccast.dr.station_backup_runtime import offline_station_restore

    service = _service()
    if service.credential_destination:
        typer.echo(f"Restore credentials/settings: {service.credential_destination}")
        if not restore_local_station_settings:
            raise typer.BadParameter(
                "This is a full replacement-station restore, not an isolated database clone. "
                "Run it on the replacement host and explicitly acknowledge "
                "--restore-local-station-settings."
            )
    typer.confirm("Restore to the destinations shown above?", abort=True)
    phrase = _passphrase()
    with offline_station_restore(
        installed_database_url=service.database_url,
        target_database_url=effective_database_url,
    ):
        result = service.restore_backup(
            archive,
            phrase,
            target_database_url=effective_database_url,
            target_paths=mappings,
            writers_stopped=True,
            restore_local_station_settings=restore_local_station_settings,
        )
    typer.echo(
        f"Restored {result.backup_id}: {result.database_engine} database and "
        f"{result.files_restored} mapped files"
    )
