# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Windows-only flat recovery primitives; imports remain platform-neutral."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Any

from civiccast.native.supervisor.config import SERVICE_NAME
from civiccast.native.upgrade.flat_recovery import FlatRecoveryError, _safe_path

_SERVICE_KEY = rf"SYSTEM\CurrentControlSet\Services\{SERVICE_NAME}"
_NATIVE_KEY = r"SOFTWARE\CivicCast\Native"
_CLASS = "civiccast.native.supervisor.service_host.CivicCastSupervisorService"
_HOST = Path("runtime/Lib/site-packages/civiccast/native/supervisor/service_host")
_CONFIG_LEVELS = (1, 2, 3, 4, 5, 6, 7)


def _sanitized[**P, R](function: Callable[P, R]) -> Callable[P, R]:
    @wraps(function)
    def call(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return function(*args, **kwargs)
        except Exception:
            # SCM/registry errors can carry command lines or credential values.
            raise FlatRecoveryError("Windows recovery operation failed closed") from None

    return call


def _within(root: Path, path: Path) -> Path:
    resolved = _safe_path(path)
    if not resolved.is_relative_to(root) or resolved == root:
        raise FlatRecoveryError("registration points outside the owned installation")
    return resolved


def _validate_binding(
    root: Path, config: list[Any], python_class: str, python_path: str | None
) -> None:
    root = _safe_path(root)
    if len(config) != 9 or config[7] != "LocalSystem" or config[0] != 16:
        raise FlatRecoveryError("unsupported service account or service type")
    if config[4] or config[5]:
        # User-mode CivicCast has no load-order tag; SCM cannot restore an exact tag.
        raise FlatRecoveryError("unsupported service load-order registration")
    binary = config[3]
    if binary.startswith('"'):
        if not binary.endswith('"') or binary.count('"') != 2:
            raise FlatRecoveryError("unsupported service command line")
        binary = binary[1:-1]
    elif any(character.isspace() for character in binary):
        raise FlatRecoveryError("ambiguous service command line")
    executable = _within(root, Path(binary))
    if executable.name.lower() != "pythonservice.exe":
        raise FlatRecoveryError("unsupported service executable")
    host_class = str(_safe_path(root / _HOST)) + ".CivicCastSupervisorService"
    if python_class not in (_CLASS, host_class):
        raise FlatRecoveryError("unsupported Python service class")
    if python_path is not None:
        for entry in python_path.split(";"):
            if not entry:
                raise FlatRecoveryError("empty Python service path")
            _within(root, Path(entry))


def _security_flags() -> int:
    import win32security

    return int(
        win32security.OWNER_SECURITY_INFORMATION
        | win32security.GROUP_SECURITY_INFORMATION
        | win32security.DACL_SECURITY_INFORMATION
    )


def _sddl(descriptor: Any) -> str:
    import win32security

    return str(
        win32security.ConvertSecurityDescriptorToStringSecurityDescriptor(
            descriptor, win32security.SDDL_REVISION_1, _security_flags()
        )
    )


def _descriptor(sddl: str) -> Any:
    import win32security

    return win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        sddl, win32security.SDDL_REVISION_1
    )


def _registry_snapshot(
    path: str, *, hive: Any = None, selected: set[str] | None = None, depth: int = 0
) -> dict[str, Any] | None:
    import winreg

    import win32security

    if depth > 8:
        raise FlatRecoveryError("registry snapshot exceeds recovery bounds")
    hive = winreg.HKEY_LOCAL_MACHINE if hive is None else hive
    try:
        key = winreg.OpenKey(hive, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
    except FileNotFoundError:
        return None
    with key:
        children, values, _modified = winreg.QueryInfoKey(key)
        if children > 128 or values > 128:
            raise FlatRecoveryError("registry snapshot exceeds recovery bounds")
        security = _sddl(
            win32security.GetSecurityInfo(
                int(key), win32security.SE_REGISTRY_KEY, _security_flags()
            )
        )
        recorded = []
        for index in range(values):
            name, value, kind = winreg.EnumValue(key, index)
            if selected is not None and name not in selected:
                continue
            if kind not in (
                winreg.REG_SZ,
                winreg.REG_EXPAND_SZ,
                winreg.REG_BINARY,
                winreg.REG_DWORD,
                winreg.REG_QWORD,
                winreg.REG_MULTI_SZ,
            ):
                raise FlatRecoveryError("unsupported registry value kind")
            if len(repr(value)) > 65536:
                raise FlatRecoveryError("registry value exceeds recovery bounds")
            recorded.append(
                [
                    name,
                    base64.b64encode(value).decode("ascii") if isinstance(value, bytes) else value,
                    kind,
                ]
            )
        nodes = {}
        if selected is None:
            for index in range(children):
                name = winreg.EnumKey(key, index)
                nodes[name] = _registry_snapshot(path + "\\" + name, hive=hive, depth=depth + 1)
        return {"security": security, "values": recorded, "children": nodes}


def _delete_registry_tree(hive: Any, path: str) -> None:
    import winreg

    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_ALL_ACCESS | winreg.KEY_WOW64_64KEY) as key:
            while winreg.QueryInfoKey(key)[0]:
                _delete_registry_tree(hive, path + "\\" + winreg.EnumKey(key, 0))
        winreg.DeleteKeyEx(hive, path, winreg.KEY_WOW64_64KEY, 0)
    except FileNotFoundError:
        pass


def _validate_registry_record(
    record: dict[str, Any] | None, *, selected: set[str] | None = None, depth: int = 0
) -> None:
    if record is None:
        return
    if depth > 8 or set(record) != {"security", "values", "children"}:
        raise FlatRecoveryError("invalid registry recovery record")
    if not isinstance(record["security"], str):
        raise FlatRecoveryError("invalid registry recovery security")
    _descriptor(record["security"])
    if len(record["values"]) > 128 or len(record["children"]) > 128:
        raise FlatRecoveryError("registry recovery exceeds bounds")
    seen = set()
    for name, value, kind in record["values"]:
        if (
            not isinstance(name, str)
            or name in seen
            or (selected is not None and name not in selected)
        ):
            raise FlatRecoveryError("invalid registry recovery value")
        seen.add(name)
        if kind not in (1, 2, 3, 4, 7, 11) or len(repr(value)) > 65536:
            raise FlatRecoveryError("unsupported registry recovery value")
        if kind == 3:
            base64.b64decode(value, validate=True)
    if selected is not None and record["children"]:
        raise FlatRecoveryError("selected registry recovery cannot restore subkeys")
    for name, child in record["children"].items():
        if not isinstance(name, str) or not name or any(char in name for char in "\\/"):
            raise FlatRecoveryError("invalid registry recovery child")
        _validate_registry_record(child, depth=depth + 1)


def _registry_restore(
    path: str, record: dict[str, Any] | None, *, hive: Any = None, selected: set[str] | None = None
) -> None:
    import winreg

    import win32api
    import win32security

    _validate_registry_record(record, selected=selected)
    hive = winreg.HKEY_LOCAL_MACHINE if hive is None else hive
    if record is None:
        if selected is None:
            _delete_registry_tree(hive, path)
        return
    with winreg.CreateKeyEx(hive, path, 0, winreg.KEY_ALL_ACCESS | winreg.KEY_WOW64_64KEY) as key:
        names = {value[0] for value in record["values"]}
        for index in reversed(range(winreg.QueryInfoKey(key)[1])):
            name = winreg.EnumValue(key, index)[0]
            if (selected is None or name in selected) and name not in names:
                winreg.DeleteValue(key, name)
        for name, value, kind in record["values"]:
            if selected is not None and name not in selected:
                raise FlatRecoveryError("registry restore leaves its owned surface")
            winreg.SetValueEx(
                key,
                name,
                0,
                kind,
                base64.b64decode(value, validate=True) if kind == winreg.REG_BINARY else value,
            )
        if selected is None:
            for index in reversed(range(winreg.QueryInfoKey(key)[0])):
                name = winreg.EnumKey(key, index)
                if name not in record["children"]:
                    _delete_registry_tree(hive, path + "\\" + name)
            for name, child in record["children"].items():
                if not name or any(char in name for char in "\\/"):
                    raise FlatRecoveryError("unsafe registry child")
                _registry_restore(path + "\\" + name, child, hive=hive)
        descriptor = _descriptor(record["security"])
        control, _revision = descriptor.GetSecurityDescriptorControl()
        protection = (
            win32security.PROTECTED_DACL_SECURITY_INFORMATION
            if control & win32security.SE_DACL_PROTECTED
            else win32security.UNPROTECTED_DACL_SECURITY_INFORMATION
        )
        # RegSetKeySecurity applies the captured descriptor itself. SetSecurityInfo
        # re-inherits ACEs and changes SE_DACL_AUTO_INHERITED on an existing key.
        win32api.RegSetKeySecurity(int(key), _security_flags() | protection, descriptor)


def _python_settings() -> tuple[dict[str, Any] | None, dict[str, Any], Any, Any]:
    root = _registry_snapshot(_SERVICE_KEY, selected={"PythonClass", "PythonPath"})
    children = {
        name: _registry_snapshot(_SERVICE_KEY + "\\" + name)
        for name in ("PythonClass", "PythonPath")
    }

    def value(name: str) -> Any:
        child = children[name]
        items = child["values"] if child is not None else (root or {}).get("values", [])
        return next(
            (item[1] for item in items if item[0] == ("" if child is not None else name)), None
        )

    return root, children, value("PythonClass"), value("PythonPath")


@contextmanager
def _service_handle(config: list[Any] | None = None) -> Iterator[tuple[Any, Any]]:
    import win32service  # type: ignore[import-untyped]

    access = win32service.SC_MANAGER_CONNECT
    if config is not None:
        access |= win32service.SC_MANAGER_CREATE_SERVICE
    manager = win32service.OpenSCManager(None, None, access)
    try:
        try:
            service = win32service.OpenService(
                manager, SERVICE_NAME, win32service.SERVICE_ALL_ACCESS
            )
        except Exception as error:
            if config is None or getattr(error, "winerror", None) != 1060:
                raise
            service = win32service.CreateService(
                manager,
                SERVICE_NAME,
                config[8],
                win32service.SERVICE_ALL_ACCESS,
                config[0],
                config[1],
                config[2],
                config[3],
                None,
                False,
                config[6],
                "LocalSystem",
                None,
            )
        try:
            yield win32service, service
        finally:
            win32service.CloseServiceHandle(service)
    finally:
        win32service.CloseServiceHandle(manager)


@_sanitized
def capture_registration(install_root: Path) -> dict[str, Any]:
    root = _safe_path(install_root)
    if _registry_snapshot(_SERVICE_KEY + r"\TriggerInfo") is not None:
        raise FlatRecoveryError("unsupported triggered service startup policy")
    python_values, python_children, python_class, python_path = _python_settings()
    with _service_handle() as (scm, service):
        config = list(scm.QueryServiceConfig(service))
        _validate_binding(root, config, python_class, python_path)
        return {
            "install_root": str(root),
            "config": config,
            "advanced": {
                str(level): scm.QueryServiceConfig2(service, level) for level in _CONFIG_LEVELS
            },
            "security": _sddl(scm.QueryServiceObjectSecurity(service, _security_flags())),
            "python_values": python_values,
            "python_children": python_children,
        }


@_sanitized
def verify_owned_install_root(expected: Path) -> None:
    capture_registration(expected)


def _validated_registration(record: dict[str, Any], expected_install_root: Path) -> list[Any]:
    expected = _safe_path(expected_install_root)
    if _safe_path(Path(record["install_root"])) != expected:
        raise FlatRecoveryError("service registration root is not independently bound")
    children = record["python_children"]
    values = record["python_values"]
    if set(children) != {"PythonClass", "PythonPath"} or set(record["advanced"]) != {
        str(level) for level in _CONFIG_LEVELS
    }:
        raise FlatRecoveryError("invalid service registration snapshot")
    _validate_registry_record(values, selected={"PythonClass", "PythonPath"})
    for child in children.values():
        _validate_registry_record(child)
    _descriptor(record["security"])

    def value(name: str) -> Any:
        child = children[name]
        items = child["values"] if child is not None else values["values"]
        return next(
            (item[1] for item in items if item[0] == ("" if child is not None else name)), None
        )

    config = record["config"]
    _validate_binding(expected, config, value("PythonClass"), value("PythonPath"))
    return list(config)


@_sanitized
def ensure_contained_registration(record: dict[str, Any], *, expected_install_root: Path) -> None:
    """Establish a disabled SCM root before restoring its Environment values.

    A missing service is created only from the already-bound prior snapshot.
    This does not restore automatic start or recovery actions: those policies
    remain deferred until the old database and application bytes are verified.
    """
    from civiccast.native.upgrade.service_control import _real_service_stopped_probe

    if _real_service_stopped_probe() is not True:
        raise FlatRecoveryError("registration admission requires containment")
    config = _validated_registration(record, expected_install_root)
    config[1] = 4  # SERVICE_DISABLED, including the CreateService path.
    with _service_handle(config) as (scm, service):
        scm.ChangeServiceConfig(
            service,
            scm.SERVICE_NO_CHANGE,
            scm.SERVICE_DISABLED,
            scm.SERVICE_NO_CHANGE,
            None,
            None,
            False,
            None,
            None,
            None,
            None,
        )
        scm.ChangeServiceConfig2(
            service,
            scm.SERVICE_CONFIG_FAILURE_ACTIONS,
            {"ResetPeriod": 0, "RebootMsg": "", "Command": "", "Actions": ()},
        )


@_sanitized
def restore_registration(record: dict[str, Any], *, expected_install_root: Path) -> None:
    from civiccast.native.upgrade.service_control import _real_service_stopped_probe

    if _real_service_stopped_probe() is not True:
        raise FlatRecoveryError("service registration restore requires containment")
    config = _validated_registration(record, expected_install_root)
    values = record["python_values"]
    children = record["python_children"]
    with _service_handle(config) as (scm, service):
        # Never start. Password is None only because admission requires LocalSystem.
        scm.ChangeServiceConfig(
            service,
            config[0],
            config[1],
            config[2],
            config[3],
            config[4],
            False,
            config[6],
            config[7],
            None,
            config[8],
        )
        for level in _CONFIG_LEVELS:
            setting = record["advanced"][str(level)]
            if level == 2 and setting is not None:
                setting = {
                    **setting,
                    "Actions": tuple(tuple(action) for action in setting["Actions"]),
                }
            scm.ChangeServiceConfig2(service, level, setting)
        _registry_restore(_SERVICE_KEY, values, selected={"PythonClass", "PythonPath"})
        for name, child in children.items():
            if name not in ("PythonClass", "PythonPath"):
                raise FlatRecoveryError("unsafe Python registration child")
            _registry_restore(_SERVICE_KEY + "\\" + name, child)
        scm.SetServiceObjectSecurity(service, _security_flags(), _descriptor(record["security"]))


@_sanitized
def contain_service() -> None:
    from civiccast.native.upgrade.service_control import (
        _real_scm_stop,
        _real_service_registered_probe,
        _real_service_stopped_probe,
    )

    if _real_service_registered_probe() is False:
        return
    with _service_handle() as (scm, service):
        scm.ChangeServiceConfig(
            service,
            scm.SERVICE_NO_CHANGE,
            scm.SERVICE_DISABLED,
            scm.SERVICE_NO_CHANGE,
            None,
            None,
            False,
            None,
            None,
            None,
            None,
        )
        scm.ChangeServiceConfig2(
            service,
            scm.SERVICE_CONFIG_FAILURE_ACTIONS,
            {"ResetPeriod": 0, "RebootMsg": "", "Command": "", "Actions": ()},
        )
    _real_scm_stop()
    deadline = time.monotonic() + 60
    while _real_service_stopped_probe() is not True:
        if time.monotonic() >= deadline:
            raise FlatRecoveryError("service containment could not be verified")
        time.sleep(0.1)


def _file_snapshot(path: Path) -> dict[str, str] | None:
    import win32security

    path = _safe_path(path)
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise FlatRecoveryError("unsupported PostgreSQL configuration file")
    content = path.read_bytes()
    return {
        "bytes": base64.b64encode(content).decode("ascii"),
        "sha256": hashlib.sha256(content).hexdigest(),
        "security": _sddl(win32security.GetFileSecurity(str(path), _security_flags())),
    }


def _configuration_paths(data_root: Path) -> dict[str, Path]:
    root = _safe_path(data_root)
    return {
        name: _within(root, root / "data" / "pgdata" / name)
        for name in ("postgresql.conf", "pg_hba.conf")
    }


@_sanitized
def capture_configuration(destination: Path, install_root: Path, data_root: Path) -> None:
    from civiccast.native.provision.journal import _harden_state_root_acl

    destination = _safe_path(destination)
    destination.mkdir(parents=False, exist_ok=False)
    _harden_state_root_acl(destination)
    record = {
        "install_root": str(_safe_path(install_root)),
        "data_root": str(_safe_path(data_root)),
        "native": _registry_snapshot(_NATIVE_KEY),
        "environment": _registry_snapshot(_SERVICE_KEY, selected={"Environment"}),
        "files": {
            name: _file_snapshot(path) for name, path in _configuration_paths(data_root).items()
        },
    }
    (destination / "configuration.json").write_text(json.dumps(record), encoding="utf-8")


@_sanitized
def restore_configuration(destination: Path, install_root: Path, data_root: Path) -> None:
    import win32security

    from civiccast.native.provision.journal import _harden_state_root_acl
    from civiccast.native.upgrade.service_control import _real_service_stopped_probe

    if _real_service_stopped_probe() is not True:
        raise FlatRecoveryError("configuration restore requires containment")
    destination = _safe_path(destination)
    _harden_state_root_acl(destination)
    manifest = _safe_path(destination / "configuration.json")
    if manifest.stat().st_size > 4 * 1024 * 1024:
        raise FlatRecoveryError("configuration snapshot exceeds recovery bounds")
    record = json.loads(manifest.read_text(encoding="utf-8"))
    if record["install_root"] != str(_safe_path(install_root)) or record["data_root"] != str(
        _safe_path(data_root)
    ):
        raise FlatRecoveryError("configuration snapshot root binding changed")
    paths = _configuration_paths(data_root)
    if set(record["files"]) != set(paths):
        raise FlatRecoveryError("configuration snapshot file set changed")
    decoded = {}
    _validate_registry_record(record["native"])
    _validate_registry_record(record["environment"], selected={"Environment"})
    for name, saved in record["files"].items():
        if saved is not None:
            if set(saved) != {"bytes", "sha256", "security"}:
                raise FlatRecoveryError("invalid configuration file snapshot")
            _descriptor(saved["security"])
            content = base64.b64decode(saved["bytes"], validate=True)
            if hashlib.sha256(content).hexdigest() != saved["sha256"]:
                raise FlatRecoveryError("configuration snapshot bytes changed")
            decoded[name] = content
    _registry_restore(_NATIVE_KEY, record["native"])
    _registry_restore(_SERVICE_KEY, record["environment"], selected={"Environment"})
    for name, path in paths.items():
        saved = record["files"][name]
        if saved is None:
            path.unlink(missing_ok=True)
        else:
            # Only these two exact owned files; never copy physical PGDATA or media.
            path.write_bytes(decoded[name])
            descriptor = _descriptor(saved["security"])
            control, _revision = descriptor.GetSecurityDescriptorControl()
            protection = (
                win32security.PROTECTED_DACL_SECURITY_INFORMATION
                if control & win32security.SE_DACL_PROTECTED
                else win32security.UNPROTECTED_DACL_SECURITY_INFORMATION
            )
            win32security.SetFileSecurity(str(path), _security_flags() | protection, descriptor)
