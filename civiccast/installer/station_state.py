# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Local station setup state for first-admin handoff.

This file intentionally owns only the small bootstrap identity that lets the
installer hand a browser to the operator console. Durable civic records still
belong in the database-backed module stores.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from civiccast.ai_models.models import detect_summary_model_default
from civiccast.auth.models import OperatorIdentity
from civiccast.cable.channel import default_channel_profiles
from civiccast.installer.models import (
    FirstAdminSetupRequest,
    FirstAdminSetupResponse,
    RecoveryKit,
    StationAuthResponse,
    StationChannelProfile,
    StationDashboardReadyState,
    StationLoginRequest,
    StationOperationMode,
    StationProfile,
    StationRecoveryRequest,
    StationSetupState,
    StationStorageLocations,
)

_SCHEMA_VERSION = 1
_PASSWORD_ITERATIONS = 210_000
_RECOVERY_CODE_COUNT = 8
_DEFAULT_ROLES = ["setup_admin", "publish_operator", "support_admin", "viewer"]

# The station's seed channels MUST match the real playout/egress channel
# lineup. A manually-maintained second list here (a numbered channel set)
# once diverged from the real public/education/government channels and severed
# schedule -> commit-to-air. Derive the seed from the single source of truth
# (civiccast.cable.channel) so they can never drift again; specific channel
# numbers vary city to city and are never named in seed data, cards, or docs —
# only the PEG channel types (public, education, government).
_CHANNEL_PURPOSES: dict[str, str] = {
    "public": "Public meetings, civic boards, and community access.",
    "education": "School board, campus, student, and athletics programming.",
    "government": "Council, board, and commission meetings and official notices.",
}
_DEFAULT_CHANNEL_PROFILES = [
    StationChannelProfile(
        channel_id=profile.channel_id,
        display_name=profile.branding.display_name,
        purpose=_CHANNEL_PURPOSES.get(profile.channel_id, profile.branding.display_name),
    )
    for profile in default_channel_profiles()
]
_FALLBACK_DEFAULT_CHANNEL_ID = "government"


def _normalized_default_channel_id(persisted: object) -> str:
    """Return a real channel id, healing a station provisioned before the
    single-vocabulary fix.

    Stations commissioned by an earlier build persisted a numbered channel id
    (e.g. a ``gov-ch*`` style id) that no longer exists in the real
    playout/egress lineup. The old fallback only fired when the key was
    *absent*, so a present-but-retired value stayed stuck forever. Normalize
    any value that is not one of the station's real channels.
    """
    known = {profile.channel_id for profile in _DEFAULT_CHANNEL_PROFILES}
    candidate = str(persisted).strip() if persisted else ""
    return candidate if candidate in known else _FALLBACK_DEFAULT_CHANNEL_ID


class StationSetupAlreadyCompleteError(RuntimeError):
    """Raised when first-admin setup is attempted after completion."""


class StationAuthError(RuntimeError):
    """Raised when local station admin sign-in or recovery fails."""


class StationSetupNotCompleteError(RuntimeError):
    """Raised when a recovery-kit action needs completed first-admin setup."""


# ---------------------------------------------------------------------------
# S13 first-run adaptive-model seed (S3 §3: lives in station-state JSON, not a DB
# table). The seed records the adaptive default computed from detected RAM at
# commissioning; the operator override slot mirrors slice-1's override-else-default.
# The durable runtime *selection* still lives in the 0053 DB store; this is the
# first-run seed the console falls back to when no DB selection exists (S13 §6.1).
# ---------------------------------------------------------------------------

# The features whose first-run default is seeded into station-state. Only summary's
# default is adaptive (RAM-dependent); captions/translation have a single local
# default and do not need a seed slot today.
_SEEDED_AI_FEATURES = ("summary",)


class SummaryModelSeed(BaseModel):
    """The first-run summary-model seed: adaptive default + operator override slot."""

    model_config = ConfigDict(extra="forbid")

    adaptive_default_key: str = Field(min_length=1, max_length=120)
    operator_override_key: str | None = Field(default=None, max_length=120)
    detected_ram_gb: int = Field(ge=0)
    seeded_at: datetime

    @property
    def effective_key(self) -> str:
        """Operator override if set, else the adaptive default (slice-1 rule)."""
        return self.operator_override_key or self.adaptive_default_key


class AiModelSeed(BaseModel):
    """The per-feature first-run seed block persisted under ``ai_models``."""

    model_config = ConfigDict(extra="forbid")

    summary: SummaryModelSeed


def seed_ai_model_default(*, system_ram_total_gb: int) -> AiModelSeed:
    """Compute and persist the adaptive summary default into station-state.

    Idempotent on the override: re-seeding refreshes the adaptive default / detected
    RAM but preserves any operator override the wizard already recorded. The detected
    RAM should be the integer floor of the probed value (e.g. ``int(probe().ram.total_gb)``)
    so a 15.9 GB box rounds DOWN to 15 -> e4b, never up to a 12B it cannot run.
    """

    raw = _load_raw_state()
    existing = raw.get("ai_models")
    prior_override: str | None = None
    if isinstance(existing, dict):
        prior_summary = existing.get("summary")
        if isinstance(prior_summary, dict):
            prior_override = prior_summary.get("operator_override_key")

    summary = SummaryModelSeed(
        adaptive_default_key=detect_summary_model_default(system_ram_total_gb),
        operator_override_key=prior_override,
        detected_ram_gb=system_ram_total_gb,
        seeded_at=datetime.now(UTC),
    )
    seed = AiModelSeed(summary=summary)
    raw["ai_models"] = _ai_seed_to_state(seed)
    _save_raw_state(raw)
    return seed


def read_ai_model_seed() -> AiModelSeed | None:
    """Return the persisted first-run AI-model seed, or None before commissioning."""

    raw = _load_raw_state()
    block = raw.get("ai_models")
    if not isinstance(block, dict):
        return None
    try:
        return AiModelSeed.model_validate(block)
    except Exception:
        return None


def read_station_timezone() -> str | None:
    """Return the persisted station timezone, or None before commissioning.

    The first-admin setup wizard persists the operator's chosen IANA zone (or the
    ``"local"`` sentinel default) onto the station profile at commissioning time
    (M3). The running service is the actual consumer -- schedules, as-run logs,
    and program guides are wall-clock in this zone -- so it reads the value
    straight from station-state rather than requiring the installer to also copy
    it into the service's process environment as a second, driftable source of
    truth. Deliberately reads just this one field (not the full
    :func:`_profile_from_state` validation) so a timezone lookup never fails
    because an unrelated profile field is missing or malformed.
    """

    raw = _load_raw_state()
    station = raw.get("station")
    if not isinstance(station, dict):
        return None
    value = station.get("station_timezone")
    if not value:
        return None
    return str(value)


def set_ai_model_override(feature: str, model_key: str | None) -> AiModelSeed:
    """Record (or clear) the operator's first-run override for ``feature``.

    The wizard calls this when the operator overrides the adaptive default. Passing
    ``None`` clears the override and falls back to the adaptive default. Requires the
    seed to exist (``seed_ai_model_default`` must have run at commissioning).
    """

    if feature not in _SEEDED_AI_FEATURES:
        raise ValueError(
            f"Unknown or non-seeded AI feature {feature!r}; "
            f"seeded features: {', '.join(_SEEDED_AI_FEATURES)}."
        )
    seed = read_ai_model_seed()
    if seed is None:
        raise ValueError("AI model default is not seeded yet; run first-run commissioning first.")

    summary = seed.summary.model_copy(update={"operator_override_key": model_key})
    updated = AiModelSeed(summary=summary)
    raw = _load_raw_state()
    raw["ai_models"] = _ai_seed_to_state(updated)
    _save_raw_state(raw)
    return updated


def _ai_seed_to_state(seed: AiModelSeed) -> dict[str, Any]:
    """Serialize the seed to the plain JSON shape stored in station-state."""

    return {
        "summary": {
            "adaptive_default_key": seed.summary.adaptive_default_key,
            "operator_override_key": seed.summary.operator_override_key,
            "detected_ram_gb": seed.summary.detected_ram_gb,
            "seeded_at": seed.summary.seeded_at.isoformat(),
        }
    }


def station_state_path() -> Path:
    """Return the local bootstrap state path."""

    configured = os.getenv("CIVICCAST_STATION_STATE_PATH")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        root = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return root / "CivicCast" / "station-state.json"
    root = Path(os.getenv("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return root / "civiccast" / "station-state.json"


def read_station_setup_state(*, operator_console_url: str) -> StationSetupState:
    """Return setup state without secret-bearing fields."""

    raw = _load_raw_state()
    profile = _profile_from_state(raw)
    if profile is None:
        return StationSetupState(
            status="not_started",
            setup_complete=False,
            operator_console_url=operator_console_url,
            next_step="Create the first admin account and save the recovery kit.",
        )
    recovery = raw.get("recovery", {})
    recovery_kit_id = str(recovery.get("kit_id") or profile.recovery_kit_id)
    acknowledged = bool(recovery.get("acknowledged"))
    next_step = (
        "Open System Health and confirm the station is ready for a private rehearsal."
        if acknowledged
        else "Confirm the recovery kit is saved or printed before the first public meeting."
    )
    return StationSetupState(
        status="complete",
        setup_complete=True,
        profile=profile,
        recovery_kit_created=True,
        recovery_kit_id=recovery_kit_id,
        recovery_kit_acknowledged=acknowledged,
        operator_console_url=operator_console_url,
        next_step=next_step,
    )


def complete_first_admin_setup(
    request: FirstAdminSetupRequest,
    *,
    operator_console_url: str,
) -> FirstAdminSetupResponse:
    """Persist first-admin setup and return the one-time recovery kit."""

    existing = _load_raw_state()
    if existing.get("setup_complete") and os.getenv("CIVICCAST_ALLOW_FIRST_ADMIN_RESET") != "1":
        raise StationSetupAlreadyCompleteError(
            "First-admin setup is already complete. Use the recovery flow or set "
            "CIVICCAST_ALLOW_FIRST_ADMIN_RESET=1 for an intentional local reset."
        )

    generated_at = datetime.now(UTC)
    kit_id = "rk_" + secrets.token_urlsafe(12).replace("-", "").replace("_", "")[:18]
    recovery_codes = [_new_recovery_code() for _ in range(_RECOVERY_CODE_COUNT)]
    operator_token = "ccst_" + secrets.token_urlsafe(32)
    password_salt = secrets.token_hex(16)
    token_salt = secrets.token_hex(16)

    profile = StationProfile(
        station_name=request.station_name.strip(),
        admin_display_name=request.admin_display_name.strip(),
        admin_username=request.admin_username.strip(),
        default_channel_id=request.default_channel_id.strip(),
        public_base_url=request.public_base_url.strip() if request.public_base_url else None,
        station_timezone=request.station_timezone.strip(),
        storage_locations=request.storage_locations or _default_storage_locations(),
        channel_count=request.channel_count,
        channel_profiles=_build_channel_profiles(request.channel_count),
        sample_content_enabled=request.sample_content_enabled,
        initial_schedule_enabled=request.initial_schedule_enabled,
        default_roles=list(_DEFAULT_ROLES),
        operation_mode=request.operation_mode,
        dashboard_ready_state="not_ready",
        recovery_kit_id=kit_id,
        recovery_kit_generated_at=generated_at,
    )
    recovery_kit = RecoveryKit(
        kit_id=kit_id,
        generated_at=generated_at,
        station_name=profile.station_name,
        admin_username=profile.admin_username,
        recovery_codes=recovery_codes,
        instructions=[
            "Print or save this kit before the first public meeting.",
            "Keep it somewhere separate from the CivicCast computer.",
            "Use one recovery code at a time if the admin password is lost.",
            "If this kit is exposed, rotate the admin password and generate a new kit.",
        ],
        excludes=[
            "staff bearer token values",
            "provider secret values",
            "private keys",
            "resident email addresses",
            "database passwords",
        ],
    )

    raw_state = {
        "schema_version": _SCHEMA_VERSION,
        "setup_complete": True,
        "station": {
            "station_name": profile.station_name,
            "admin_display_name": profile.admin_display_name,
            "admin_username": profile.admin_username,
            "default_channel_id": profile.default_channel_id,
            "public_base_url": profile.public_base_url,
            "station_timezone": profile.station_timezone,
            "storage_locations": profile.storage_locations.model_dump(),
            "channel_count": profile.channel_count,
            "channel_profiles": [channel.model_dump() for channel in profile.channel_profiles],
            "sample_content_enabled": profile.sample_content_enabled,
            "initial_schedule_enabled": profile.initial_schedule_enabled,
            "default_roles": profile.default_roles,
            "operation_mode": profile.operation_mode,
            "dashboard_ready_state": profile.dashboard_ready_state,
            "recovery_kit_id": profile.recovery_kit_id,
            "recovery_kit_generated_at": profile.recovery_kit_generated_at.isoformat(),
        },
        "admin": {
            "username": profile.admin_username,
            "display_name": profile.admin_display_name,
            "password_salt": password_salt,
            "password_hash": _hash_secret(request.admin_password, salt=password_salt),
            "password_iterations": _PASSWORD_ITERATIONS,
        },
        "recovery": {
            "kit_id": kit_id,
            "generated_at": generated_at.isoformat(),
            "destination": request.recovery_kit_destination.strip(),
            "acknowledged": False,
            "acknowledged_at": None,
            "code_hashes": [_hash_secret(code, salt=kit_id) for code in recovery_codes],
        },
        "operator_console": {
            "token_salt": token_salt,
            "token_hash": _hash_token(operator_token, salt=token_salt),
        },
    }
    _save_raw_state(raw_state)

    return FirstAdminSetupResponse(
        status="complete",
        profile=profile,
        recovery_kit=recovery_kit,
        operator_console_url=operator_console_url,
        operator_console_token=operator_token,
        next_step="Open System Health, confirm readiness, then run a private rehearsal.",
    )


def acknowledge_recovery_kit(*, operator_console_url: str) -> StationSetupState:
    """Record that the operator saved or printed the one-time recovery kit."""

    raw = _load_raw_state()
    if not raw.get("setup_complete"):
        raise StationSetupNotCompleteError(
            "First-admin setup is not complete, so there is no recovery kit to confirm."
        )
    recovery = raw.setdefault("recovery", {})
    recovery["acknowledged"] = True
    recovery["acknowledged_at"] = datetime.now(UTC).isoformat()
    _save_raw_state(raw)
    return read_station_setup_state(operator_console_url=operator_console_url)


def verify_station_operator_token(token: str) -> OperatorIdentity | None:
    """Return the first-admin operator identity when token matches local state."""

    raw = _load_raw_state()
    admin = raw.get("admin")
    console = raw.get("operator_console")
    if not isinstance(admin, dict) or not isinstance(console, dict):
        return None
    salt = console.get("token_salt")
    expected = console.get("token_hash")
    if not isinstance(salt, str) or not isinstance(expected, str):
        return None
    observed = _hash_token(token, salt=salt)
    if not hmac.compare_digest(observed, expected):
        return None
    username = str(admin.get("username") or "first-admin")
    display_name = str(admin.get("display_name") or username)
    return OperatorIdentity(
        operator_id=username,
        operator_display_name=display_name,
        token_id="station-first-admin",  # noqa: S106 - audit label, not a secret.
        scopes=("admin",),
    )


def login_station_admin(
    request: StationLoginRequest,
    *,
    operator_console_url: str,
) -> StationAuthResponse:
    """Verify local first-admin credentials and return a fresh console token."""

    raw = _load_raw_state()
    profile = _profile_from_state(raw)
    if profile is None or not _verify_admin_password(
        raw,
        username=request.admin_username,
        password=request.admin_password,
    ):
        raise StationAuthError("Invalid admin username or password.")
    operator_token = _rotate_operator_token(raw)
    _save_raw_state(raw)
    return StationAuthResponse(
        status="authenticated",
        profile=profile,
        operator_console_url=operator_console_url,
        operator_console_token=operator_token,
        next_step="Open System Health and confirm the station is ready to broadcast.",
    )


def recover_station_admin(
    request: StationRecoveryRequest,
    *,
    operator_console_url: str,
) -> StationAuthResponse:
    """Consume one recovery code, reset the first-admin password, and return a token."""

    raw = _load_raw_state()
    profile = _profile_from_state(raw)
    if profile is None or request.admin_username.strip() != profile.admin_username:
        raise StationAuthError("Invalid recovery code or admin username.")
    if not _consume_recovery_code(raw, request.recovery_code):
        raise StationAuthError("Invalid recovery code or admin username.")
    _replace_admin_password(raw, request.new_admin_password)
    operator_token = _rotate_operator_token(raw)
    _save_raw_state(raw)
    return StationAuthResponse(
        status="recovered",
        profile=profile,
        operator_console_url=operator_console_url,
        operator_console_token=operator_token,
        next_step="Sign in with the new password and print a fresh recovery kit when rotation is available.",
    )


def _load_raw_state() -> dict[str, Any]:
    path = station_state_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return cast(dict[str, Any], payload)


def _save_raw_state(payload: dict[str, Any]) -> None:
    path = station_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _restrict_state_file(tmp_path)
    tmp_path.replace(path)
    _restrict_state_file(path)


def _profile_from_state(raw: dict[str, Any]) -> StationProfile | None:
    station = raw.get("station")
    if not isinstance(station, dict):
        return None
    try:
        return StationProfile(
            station_name=str(station["station_name"]),
            admin_display_name=str(station["admin_display_name"]),
            admin_username=str(station["admin_username"]),
            default_channel_id=_normalized_default_channel_id(station.get("default_channel_id")),
            public_base_url=(
                str(station["public_base_url"])
                if station.get("public_base_url") is not None
                else None
            ),
            station_timezone=str(station.get("station_timezone") or "local"),
            storage_locations=_storage_locations_from_state(station.get("storage_locations")),
            channel_count=int(station.get("channel_count") or 3),
            channel_profiles=_channel_profiles_from_state(
                station.get("channel_profiles"),
                channel_count=int(station.get("channel_count") or 3),
            ),
            sample_content_enabled=bool(station.get("sample_content_enabled", True)),
            initial_schedule_enabled=bool(station.get("initial_schedule_enabled", True)),
            default_roles=[
                str(role)
                for role in station.get("default_roles", _DEFAULT_ROLES)
                if str(role).strip()
            ],
            operation_mode=_operation_mode_from_state(station.get("operation_mode")),
            dashboard_ready_state=_dashboard_ready_state_from_state(
                station.get("dashboard_ready_state")
            ),
            recovery_kit_id=str(station["recovery_kit_id"]),
            recovery_kit_generated_at=datetime.fromisoformat(
                str(station["recovery_kit_generated_at"])
            ),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _default_storage_root() -> Path:
    configured = os.getenv("CIVICCAST_STATION_STORAGE_ROOT")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        return Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "CivicCast"
    return Path(os.getenv("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "civiccast"


def _default_storage_locations() -> StationStorageLocations:
    root = _default_storage_root()
    return StationStorageLocations(
        media_library=str(root / "media"),
        recordings=str(root / "recordings"),
        backups=str(root / "backups"),
    )


def _build_channel_profiles(channel_count: int) -> list[StationChannelProfile]:
    profiles = list(_DEFAULT_CHANNEL_PROFILES[:channel_count])
    for index in range(len(profiles) + 1, channel_count + 1):
        profiles.append(
            StationChannelProfile(
                channel_id=f"local-ch{index:02d}",
                display_name=f"Local Channel {index}",
                purpose="Additional local playout channel reserved during first-run setup.",
            )
        )
    return profiles


def _storage_locations_from_state(value: object) -> StationStorageLocations:
    if isinstance(value, dict):
        try:
            return StationStorageLocations(
                media_library=str(value["media_library"]),
                recordings=str(value["recordings"]),
                backups=str(value["backups"]),
            )
        except (KeyError, TypeError, ValueError):
            pass
    return _default_storage_locations()


def _channel_profiles_from_state(
    value: object,
    *,
    channel_count: int,
) -> list[StationChannelProfile]:
    if isinstance(value, list):
        profiles: list[StationChannelProfile] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            try:
                profiles.append(
                    StationChannelProfile(
                        channel_id=str(item["channel_id"]),
                        display_name=str(item["display_name"]),
                        purpose=str(item["purpose"]),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        if profiles:
            return profiles
    return _build_channel_profiles(channel_count)


def _operation_mode_from_state(value: object) -> StationOperationMode:
    if value == "on_air":
        return "on_air"
    return "test"


def _dashboard_ready_state_from_state(value: object) -> StationDashboardReadyState:
    if value == "ready":
        return "ready"
    return "not_ready"


def _hash_secret(secret: str, *, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        secret.encode("utf-8"),
        salt.encode("utf-8"),
        _PASSWORD_ITERATIONS,
    )
    return digest.hex()


def _hash_token(token: str, *, salt: str) -> str:
    """Hash high-entropy setup tokens without adding per-request PBKDF2 cost."""

    digest = hmac.new(salt.encode("utf-8"), token.encode("utf-8"), hashlib.sha256)
    return digest.hexdigest()


def _verify_admin_password(raw: dict[str, Any], *, username: str, password: str) -> bool:
    admin = raw.get("admin")
    if not isinstance(admin, dict):
        return False
    stored_username = admin.get("username")
    salt = admin.get("password_salt")
    expected = admin.get("password_hash")
    if not all(isinstance(value, str) for value in [stored_username, salt, expected]):
        return False
    if str(stored_username) != username.strip():
        return False
    observed = _hash_secret(password, salt=str(salt))
    return hmac.compare_digest(observed, str(expected))


def _consume_recovery_code(raw: dict[str, Any], recovery_code: str) -> bool:
    recovery = raw.get("recovery")
    if not isinstance(recovery, dict):
        return False
    kit_id = recovery.get("kit_id")
    code_hashes = recovery.get("code_hashes")
    if not isinstance(kit_id, str) or not isinstance(code_hashes, list):
        return False
    observed = _hash_secret(recovery_code.strip(), salt=kit_id)
    remaining: list[str] = []
    consumed = False
    for stored in code_hashes:
        if not isinstance(stored, str):
            continue
        if not consumed and hmac.compare_digest(observed, stored):
            consumed = True
            continue
        remaining.append(stored)
    if consumed:
        recovery["code_hashes"] = remaining
        recovery["last_recovered_at"] = datetime.now(UTC).isoformat()
    return consumed


def _replace_admin_password(raw: dict[str, Any], new_password: str) -> None:
    admin = raw.get("admin")
    if not isinstance(admin, dict):
        raise StationAuthError("Station admin state is missing.")
    password_salt = secrets.token_hex(16)
    admin["password_salt"] = password_salt
    admin["password_hash"] = _hash_secret(new_password, salt=password_salt)
    admin["password_iterations"] = _PASSWORD_ITERATIONS
    admin["password_rotated_at"] = datetime.now(UTC).isoformat()


def _rotate_operator_token(raw: dict[str, Any]) -> str:
    operator_token = "ccst_" + secrets.token_urlsafe(32)
    token_salt = secrets.token_hex(16)
    raw["operator_console"] = {
        "token_salt": token_salt,
        "token_hash": _hash_token(operator_token, salt=token_salt),
        "rotated_at": datetime.now(UTC).isoformat(),
    }
    return operator_token


def _restrict_state_file(path: Path) -> None:
    """Restrict local station bootstrap state after writing secret hashes."""

    if os.name == "nt":
        from civiccast.certs.authority import _restrict_windows_private_key_acl

        _restrict_windows_private_key_acl(path)
        return
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _new_recovery_code() -> str:
    return "CC-" + secrets.token_urlsafe(9).replace("-", "").replace("_", "")[:12].upper()
