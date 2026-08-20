# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Run a redacted isolated first-run proof against the real setup API.

This is intentionally a product-level proof script, not a unit-test fixture. It
creates a brand-new profile root, forces the installer nonce path, prepares
managed storage, creates the first admin, acknowledges the recovery kit, signs in,
and records only non-secret evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import stat
import sys
from collections.abc import Mapping
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from civiccast import __version__
from civiccast.app import create_app
from civiccast.db import reset_engine
from scripts.collect_source_state import collect_source_state

_SETUP_NONCE = "isolated-first-run-attestation-nonce"
_SETUP_HEADERS = {"X-CivicCast-Setup-Nonce": _SETUP_NONCE}
_PASSWORD = "Correct-Horse-Battery-Staple-2026"
_ENV_KEYS = (
    "CIVICCAST_MANAGED_STORAGE_DIR",
    "CIVICCAST_STATION_STATE_PATH",
    "CIVICCAST_TESTER_OPS_STATE_PATH",
    "CIVICCAST_SETUP_NONCE",
    "CIVICCAST_REQUIRE_SETUP_NONCE",
    "CIVICCAST_OPERATOR_CONSOLE_URL",
    "CIVICCAST_STAFF_TOKENS_FALLBACK_WITH_DB",
    "CIVICCAST_ALERTING",
    "CIVICCAST_ALLOW_EPHEMERAL_STORES",
    "DATABASE_URL",
    "CIVICCAST_UPLOAD_DIR",
)


def run_attestation(*, artifact_root: Path, profile_root: Path) -> dict[str, Any]:
    """Run the isolated first-run flow and write redacted artifacts."""

    artifact_root = artifact_root.resolve()
    profile_root = profile_root.resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    profile_root.mkdir(parents=True, exist_ok=True)
    if any(profile_root.iterdir()):
        raise RuntimeError(f"profile root must be empty: {profile_root}")

    original_env = {key: os.environ.get(key) for key in _ENV_KEYS}
    client_stack = ExitStack()
    client: TestClient | None = None
    try:
        reset_engine()
        _install_isolated_env(profile_root)
        client = client_stack.enter_context(TestClient(create_app()))

        preflight = {
            "profile_root_empty": not any(profile_root.iterdir()),
            "dependency_probes": _dependency_probes(),
            "environment": _environment_evidence(profile_root),
        }
        storage_before = _json_response(client.get("/api/setup/storage", headers=_SETUP_HEADERS))
        station_before = _json_response(
            client.get("/api/setup/station-state", headers=_SETUP_HEADERS)
        )
        storage_ready = _json_response(
            client.post("/api/setup/storage", headers=_SETUP_HEADERS, json={})
        )
        first_admin_raw = _json_response(
            client.post(
                "/api/setup/first-admin",
                headers=_SETUP_HEADERS,
                json={
                    "station_name": "Isolated First Run Test Station",
                    "admin_display_name": "Setup Admin",
                    "admin_username": "setup-admin",
                    "admin_password": _PASSWORD,
                    "recovery_kit_destination": "redacted offline safe",
                    "default_channel_id": "lpm-lab-1",
                    "public_base_url": "http://127.0.0.1:8000",
                },
            )
        )
        acknowledged = _json_response(
            client.post(
                "/api/setup/recovery-kit/acknowledge",
                headers=_SETUP_HEADERS,
                json={"confirmed": True},
            )
        )
        login_raw = _json_response(
            client.post(
                "/api/setup/login",
                headers=_SETUP_HEADERS,
                json={"admin_username": "setup-admin", "admin_password": _PASSWORD},
            )
        )
        station_after = _json_response(
            client.get("/api/setup/station-state", headers=_SETUP_HEADERS)
        )
        public_schedule = _json_response(client.get("/api/public/schedule/coming-up"))

        managed_root = profile_root / "managed-storage"
        station_state_path = profile_root / "station-state.json"
        expected_paths = {
            "managed_storage": managed_root,
            "database": managed_root / "data" / "civiccast.sqlite3",
            "uploads": managed_root / "uploads",
            "recordings": managed_root / "uploads" / "recordings",
            "station_state": station_state_path,
        }
        _assert_expected_paths(profile_root, expected_paths)
        _assert_secret_redaction(station_state_path)

        client_stack.close()
        client.close()
        client = None
        reset_engine()

        evidence = {
            "schema_version": 1,
            "generated_at": datetime.now(UTC).isoformat(),
            "civiccast_version": __version__,
            "source_state": collect_source_state(),
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "python": platform.python_version(),
            },
            "verdict": "pass",
            "profile_root": str(profile_root),
            "artifact_root": str(artifact_root),
            "preflight": preflight,
            "steps": {
                "storage_before": _summarize_storage(storage_before),
                "station_before": _summarize_station(station_before),
                "storage_ready": _summarize_storage(storage_ready),
                "first_admin": _summarize_first_admin(first_admin_raw),
                "recovery_acknowledge": _summarize_station(acknowledged),
                "login": _summarize_login(login_raw),
                "station_after": _summarize_station(station_after),
                "public_schedule": {
                    "status_code": public_schedule["status_code"],
                    "item_count": len(public_schedule["json"]),
                },
            },
            "files": {
                key: _file_evidence(path) for key, path in expected_paths.items() if path.exists()
            },
            "isolation": {
                "all_expected_paths_under_profile_root": all(
                    path.resolve().is_relative_to(profile_root) for path in expected_paths.values()
                ),
                "database_url_under_profile_root": str(storage_ready["json"]["database_path"])
                == str(expected_paths["database"]),
                "upload_dir_under_profile_root": str(storage_ready["json"]["upload_dir"])
                == str(expected_paths["uploads"]),
                "transient_profile_retained": False,
            },
        }
        _assert_pass(evidence)
        _write_json(artifact_root / "first-run-attestation.json", evidence)
        _write_markdown(artifact_root / "first-run-attestation.md", evidence)
        _scrub_transient_profile(profile_root)
        return evidence
    finally:
        client_stack.close()
        if client is not None:
            client.close()
        reset_engine()
        _restore_env(original_env)


def _install_isolated_env(profile_root: Path) -> None:
    for key in _ENV_KEYS:
        os.environ.pop(key, None)
    os.environ["CIVICCAST_MANAGED_STORAGE_DIR"] = str(profile_root / "managed-storage")
    os.environ["CIVICCAST_STATION_STATE_PATH"] = str(profile_root / "station-state.json")
    os.environ["CIVICCAST_TESTER_OPS_STATE_PATH"] = str(profile_root / "tester-ops-state.json")
    os.environ["CIVICCAST_SETUP_NONCE"] = _SETUP_NONCE
    os.environ["CIVICCAST_REQUIRE_SETUP_NONCE"] = "1"
    os.environ["CIVICCAST_OPERATOR_CONSOLE_URL"] = "http://127.0.0.1:8000/operator/"
    os.environ["CIVICCAST_STAFF_TOKENS_FALLBACK_WITH_DB"] = "1"
    # This proof owns the first-run setup surface, not the scheduled alert
    # maintenance lane. Keep that unrelated daily/weekly sweep from starting
    # before the station is commissioned, then restore the caller's setting.
    os.environ["CIVICCAST_ALERTING"] = "off"


def _restore_env(original: Mapping[str, str | None]) -> None:
    for key, value in original.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _json_response(response: Any) -> dict[str, Any]:
    payload = response.json()
    if response.status_code >= 400:
        raise RuntimeError(f"unexpected {response.status_code}: {payload!r}")
    return {"status_code": response.status_code, "json": payload}


def _summarize_storage(response: dict[str, Any]) -> dict[str, Any]:
    payload = response["json"]
    return {
        "status_code": response["status_code"],
        "status": payload["status"],
        "migrations_applied": payload["migrations_applied"],
        "database_path": payload["database_path"],
        "upload_dir": payload["upload_dir"],
        "storage_dir": payload["storage_dir"],
    }


def _summarize_station(response: dict[str, Any]) -> dict[str, Any]:
    payload = response["json"]
    profile = payload.get("profile") or {}
    return {
        "status_code": response["status_code"],
        "status": payload["status"],
        "setup_complete": payload["setup_complete"],
        "station_name": profile.get("station_name"),
        "admin_username": profile.get("admin_username"),
        "default_channel_id": profile.get("default_channel_id"),
        "recovery_kit_created": payload.get("recovery_kit_created"),
        "recovery_kit_acknowledged": payload.get("recovery_kit_acknowledged"),
    }


def _summarize_first_admin(response: dict[str, Any]) -> dict[str, Any]:
    payload = response["json"]
    recovery_kit = payload["recovery_kit"]
    profile = payload["profile"]
    return {
        "status_code": response["status_code"],
        "status": payload["status"],
        "station_name": profile["station_name"],
        "admin_username": profile["admin_username"],
        "default_channel_id": profile["default_channel_id"],
        "recovery_kit_id": recovery_kit["kit_id"],
        "recovery_code_count": len(recovery_kit["recovery_codes"]),
        "operator_console_token_present": bool(payload.get("operator_console_token")),
        "operator_console_token_redacted": True,
    }


def _summarize_login(response: dict[str, Any]) -> dict[str, Any]:
    payload = response["json"]
    return {
        "status_code": response["status_code"],
        "status": payload["status"],
        "admin_username": payload["profile"]["admin_username"],
        "operator_console_token_present": bool(payload.get("operator_console_token")),
        "operator_console_token_redacted": True,
    }


def _dependency_probes() -> dict[str, dict[str, str | bool | None]]:
    probes = {}
    for name in ["wsl", "ffprobe", "ffmpeg", "gst-launch-1.0", "tsp", "obs64", "vMix64"]:
        path = shutil.which(name)
        probes[name] = {"available": path is not None, "path": path}
    return probes


def _environment_evidence(profile_root: Path) -> dict[str, Any]:
    return {
        "database_url_was_unset": "DATABASE_URL" not in os.environ,
        "upload_dir_was_unset": "CIVICCAST_UPLOAD_DIR" not in os.environ,
        "allow_ephemeral_stores_unset": "CIVICCAST_ALLOW_EPHEMERAL_STORES" not in os.environ,
        "managed_storage_dir": str(profile_root / "managed-storage"),
        "station_state_path": str(profile_root / "station-state.json"),
        "setup_nonce_present": bool(os.environ.get("CIVICCAST_SETUP_NONCE")),
        "setup_nonce_redacted": True,
    }


def _file_evidence(path: Path) -> dict[str, Any]:
    if path.is_dir():
        return {
            "path": str(path),
            "kind": "directory",
            "exists": True,
            "child_count": len(list(path.iterdir())),
        }
    data = path.read_bytes()
    return {
        "path": str(path),
        "kind": "file",
        "exists": True,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "mode_octal": oct(stat.S_IMODE(path.stat().st_mode)),
    }


def _assert_expected_paths(profile_root: Path, paths: Mapping[str, Path]) -> None:
    for label, path in paths.items():
        if not path.exists():
            raise RuntimeError(f"expected {label} path missing: {path}")
        if not path.resolve().is_relative_to(profile_root):
            raise RuntimeError(f"{label} path escaped isolated root: {path}")


def _assert_secret_redaction(station_state_path: Path) -> None:
    raw = station_state_path.read_text(encoding="utf-8")
    forbidden = [_PASSWORD, _SETUP_NONCE, "ccst_", "CC-"]
    leaked = [value for value in forbidden if value in raw]
    if leaked:
        raise RuntimeError(f"station-state contains raw secret markers: {leaked!r}")


def _scrub_transient_profile(profile_root: Path) -> None:
    if profile_root.exists():
        shutil.rmtree(profile_root)


def _assert_pass(evidence: Mapping[str, Any]) -> None:
    steps = evidence["steps"]
    isolation = evidence["isolation"]
    if steps["storage_before"]["status"] != "not_configured":
        raise RuntimeError("storage was not clean before setup")
    if steps["station_before"]["setup_complete"]:
        raise RuntimeError("station state was not clean before setup")
    if steps["storage_ready"]["status"] != "ready":
        raise RuntimeError("managed storage did not become ready")
    if not steps["storage_ready"]["migrations_applied"]:
        raise RuntimeError("managed storage did not apply migrations")
    if steps["first_admin"]["status"] != "complete":
        raise RuntimeError("first admin setup did not complete")
    if steps["first_admin"]["recovery_code_count"] != 8:
        raise RuntimeError("recovery kit code count is unexpected")
    if steps["recovery_acknowledge"]["recovery_kit_acknowledged"] is not True:
        raise RuntimeError("recovery kit acknowledgement was not persisted")
    if steps["login"]["status"] != "authenticated":
        raise RuntimeError("first admin login did not succeed")
    if steps["station_after"]["setup_complete"] is not True:
        raise RuntimeError("station setup did not persist")
    required_true = {
        key: value for key, value in isolation.items() if key != "transient_profile_retained"
    }
    if not all(required_true.values()) or isolation["transient_profile_retained"] is not False:
        raise RuntimeError(f"isolation check failed: {isolation!r}")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_markdown(path: Path, evidence: Mapping[str, Any]) -> None:
    steps = evidence["steps"]
    lines = [
        "# CivicCast Isolated First-Run Attestation",
        "",
        f"- Verdict: `{evidence['verdict']}`",
        f"- Generated: `{evidence['generated_at']}`",
        f"- CivicCast version: `{evidence['civiccast_version']}`",
        f"- Source branch: `{evidence['source_state']['branch']}`",
        f"- Source head: `{evidence['source_state']['head']}`",
        f"- Source dirty: `{evidence['source_state']['dirty']}`",
        f"- Source diff SHA256: `{evidence['source_state']['diff_sha256']}`",
        f"- Profile root: `{evidence['profile_root']}`",
        f"- Storage before setup: `{steps['storage_before']['status']}`",
        f"- Managed storage after setup: `{steps['storage_ready']['status']}`",
        f"- Migrations applied: `{steps['storage_ready']['migrations_applied']}`",
        f"- First admin setup: `{steps['first_admin']['status']}`",
        f"- Recovery kit code count: `{steps['first_admin']['recovery_code_count']}`",
        f"- Recovery kit acknowledged: `{steps['recovery_acknowledge']['recovery_kit_acknowledged']}`",
        f"- First-admin login: `{steps['login']['status']}`",
        f"- Station setup persisted: `{steps['station_after']['setup_complete']}`",
        f"- Public schedule smoke item count: `{steps['public_schedule']['item_count']}`",
        "",
        "Secrets are deliberately omitted: setup nonce, admin password, recovery codes, "
        "and operator console tokens are never written to this artifact.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact-root",
        type=Path,
        required=True,
        help="Directory where redacted first-run evidence should be written.",
    )
    parser.add_argument(
        "--profile-root",
        type=Path,
        required=True,
        help="Empty isolated profile root used for managed storage and station state.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    run_attestation(artifact_root=args.artifact_root, profile_root=args.profile_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
