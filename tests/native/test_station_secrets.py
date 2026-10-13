# SPDX-License-Identifier: Apache-2.0
"""Real Windows protection and portable station credential round-trip."""

import os

import pytest

from civiccast.native.service_identity import SERVICE_SID
from civiccast.native.station_secrets import StationSecretVault

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI vault")


@pytest.mark.windows_only
def test_vault_encrypts_and_exports_portable_credentials(tmp_path):
    vault = StationSecretVault(tmp_path / "source.dpapi")
    vault.set("civiccast.live-source", "camera", "test-only-password")
    assert b"test-only-password" not in vault.path.read_bytes()
    assert vault.get("civiccast.live-source", "camera") == "test-only-password"
    restored = StationSecretVault(tmp_path / "restored.dpapi")
    restored.import_portable(vault.export_portable())
    assert restored.get("civiccast.live-source", "camera") == "test-only-password"
    restored.delete("civiccast.live-source", "camera")
    assert restored.get("civiccast.live-source", "camera") is None


@pytest.mark.windows_only
def test_vault_grants_service_access_without_public_access(tmp_path):
    import win32security

    vault = StationSecretVault(tmp_path / "vault.dpapi")
    vault.set("civiccast.staff-token", "operator", "test-only-token")
    descriptor = win32security.GetFileSecurity(
        str(vault.path), win32security.DACL_SECURITY_INFORMATION
    )
    acl = descriptor.GetSecurityDescriptorDacl()
    grants = {
        win32security.ConvertSidToStringSid(acl.GetAce(i)[2]): acl.GetAce(i)[1]
        for i in range(acl.GetAceCount())
    }
    assert SERVICE_SID in grants
    assert grants[SERVICE_SID] & 3 == 3  # Read and write file data.
    assert not {"S-1-1-0", "S-1-5-11", "S-1-5-32-545"} & grants.keys()


@pytest.mark.windows_only
def test_invalid_import_preserves_existing_vault(tmp_path):
    vault = StationSecretVault(tmp_path / "vault.dpapi")
    vault.set("civiccast.staff-token", "operator", "retained")
    before = vault.path.read_bytes()
    with pytest.raises(ValueError):
        vault.import_portable({"station-keyring.json": b'{"other.application":{"user":"secret"}}'})
    assert vault.path.read_bytes() == before


@pytest.mark.windows_only
def test_corrupt_vault_fails_closed(tmp_path):
    vault = StationSecretVault(tmp_path / "vault.dpapi")
    vault.path.write_bytes(b"not-a-dpapi-blob")
    with pytest.raises(RuntimeError, match="cannot be opened"):
        vault.set("civiccast.staff-token", "operator", "replacement")
    assert vault.path.read_bytes() == b"not-a-dpapi-blob"


@pytest.mark.windows_only
def test_old_account_retry_refreshes_changed_and_deleted_credentials(tmp_path, monkeypatch):
    import win32cred

    vault = StationSecretVault(tmp_path / "vault.dpapi")
    vault.set("civiccast.live-source", "camera", "outdated")
    vault.set("civiccast.live-source", "removed", "deleted-from-old-account")
    monkeypatch.setattr(
        win32cred,
        "CredEnumerate",
        lambda *args: [
            {
                "TargetName": "civiccast.live-source",
                "UserName": "camera",
                "Type": win32cred.CRED_TYPE_GENERIC,
                "CredentialBlob": "current".encode("utf-16"),
            },
            {
                "TargetName": "unrelated-app",
                "UserName": "unrelated-user",
                "Type": win32cred.CRED_TYPE_GENERIC,
                "CredentialBlob": "private".encode("utf-16"),
            },
        ],
    )
    assert vault.import_current_windows_keyring() == 1
    assert vault.get("civiccast.live-source", "camera") == "current"
    assert vault.get("civiccast.live-source", "removed") is None
    assert b"unrelated-app" not in vault.export_portable()["station-keyring.json"]
