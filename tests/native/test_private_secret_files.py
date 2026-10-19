# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Regression coverage for local plaintext secret-file ACLs."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from civiccast.alerting.credentials import FileCredentialStore
from civiccast.native.private_files import PrivateFileProtectionError
from civiccast.subscribe.secrets import AesGcmSecretBox, load_subscription_secrets

_USERS_SID = "S-1-5-32-545"
_WINDOWS_ONLY = pytest.mark.skipif(os.name != "nt", reason="Windows file ACL behavior.")


def _grant_inherited_users_read(path: Path) -> None:
    result = subprocess.run(
        ["icacls", str(path), "/grant", f"*{_USERS_SID}:(OI)(CI)(R)"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _file_acl_sids(path: Path) -> tuple[set[str], bool]:
    import win32security

    descriptor = win32security.GetFileSecurity(str(path), win32security.DACL_SECURITY_INFORMATION)
    acl = descriptor.GetSecurityDescriptorDacl()
    principals = {
        win32security.ConvertSidToStringSid(acl.GetAce(index)[2])
        for index in range(acl.GetAceCount())
    }
    control, _revision = descriptor.GetSecurityDescriptorControl()
    return principals, bool(control & win32security.SE_DACL_PROTECTED)


def _service_acl_mask(path: Path) -> int:
    import win32security

    from civiccast.native.service_identity import SERVICE_SID

    descriptor = win32security.GetFileSecurity(str(path), win32security.DACL_SECURITY_INFORMATION)
    acl = descriptor.GetSecurityDescriptorDacl()
    mask = 0
    for index in range(acl.GetAceCount()):
        ace = acl.GetAce(index)
        if ace[0][0] == 0 and win32security.ConvertSidToStringSid(ace[2]) == SERVICE_SID:
            mask |= ace[1]
    return mask


@_WINDOWS_ONLY
def test_new_alert_credentials_strip_inherited_users_read(tmp_path: Path) -> None:
    _grant_inherited_users_read(tmp_path)
    path = tmp_path / "alert-credentials.json"

    FileCredentialStore(path).put("test-handle", {"url": "http://127.0.0.1", "secret": "synthetic"})

    principals, protected = _file_acl_sids(path)
    assert protected
    assert _USERS_SID not in principals
    assert _service_acl_mask(path) & 0x00010003 == 0x00010003
    assert FileCredentialStore(path).get("test-handle") == {
        "url": "http://127.0.0.1",
        "secret": "synthetic",
    }


@_WINDOWS_ONLY
def test_subscription_secret_read_migrates_acl_without_rotating_keys(
    tmp_path: Path,
) -> None:
    _grant_inherited_users_read(tmp_path)
    path = tmp_path / "subscribe-secrets.json"
    token_secret = "synthetic-token-secret-" + "t" * 32
    encryption_key = "synthetic-encryption-key-" + "e" * 32
    payload = {
        "format_version": 1,
        "token_secret": token_secret,
        "encryption_key": encryption_key,
        "legacy_token_secrets": [],
        "legacy_encryption_keys": [],
    }
    original = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(original)
    original_principals, _original_protected = _file_acl_sids(path)
    assert _USERS_SID in original_principals
    encrypted = AesGcmSecretBox(encryption_key).seal(
        "synthetic webhook secret", aad="sub-existing:secret"
    )

    loaded = load_subscription_secrets({"CIVICCAST_SUBSCRIBE_SECRETS_FILE": str(path)})

    assert loaded.token_secret == token_secret
    assert (
        loaded.secret_box.open(encrypted, aad="sub-existing:secret") == "synthetic webhook secret"
    )
    assert path.read_bytes() == original
    principals, protected = _file_acl_sids(path)
    assert protected
    assert _USERS_SID not in principals
    assert _service_acl_mask(path) & 0x00010003 == 0x00010003


def test_failed_alert_credential_replace_keeps_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "alert-credentials.json"
    original = b'{"existing":{"secret":"synthetic"}}\n'
    path.write_bytes(original)

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="synthetic replace failure"):
        FileCredentialStore(path)._save({"new-handle": {"secret": "synthetic-new"}})

    assert path.read_bytes() == original


def test_unreadable_alert_credentials_are_not_treated_as_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "alert-credentials.json"
    original = b'{"existing":{"secret":"synthetic"}}\n'
    path.write_bytes(original)
    original_read_bytes = Path.read_bytes

    def fail_existing_read(candidate: Path) -> bytes:
        if candidate == path:
            raise PermissionError("synthetic access denied")
        return original_read_bytes(candidate)

    monkeypatch.setattr(Path, "read_bytes", fail_existing_read)
    with pytest.raises(PrivateFileProtectionError, match="Cannot read existing"):
        FileCredentialStore(path).put("new-handle", {"secret": "synthetic-new"})

    monkeypatch.setattr(Path, "read_bytes", original_read_bytes)
    assert path.read_bytes() == original


def test_failed_alert_credential_protection_keeps_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import civiccast.native.private_files as private_files

    path = tmp_path / "alert-credentials.json"
    original = b'{"existing":{"secret":"synthetic"}}\n'
    path.write_bytes(original)

    def fail_protection(temporary: Path, _descriptor: int) -> None:
        assert temporary.stat().st_size == 0
        raise PrivateFileProtectionError("synthetic ACL failure")

    monkeypatch.setattr(private_files, "_protect_empty_file", fail_protection)
    with pytest.raises(PrivateFileProtectionError, match="synthetic ACL failure"):
        FileCredentialStore(path)._save({"new-handle": {"secret": "synthetic-new"}})

    assert path.read_bytes() == original
    assert list(tmp_path.glob("*.tmp")) == []
