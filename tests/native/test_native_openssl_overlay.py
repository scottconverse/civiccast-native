# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts import native_openssl_overlay as overlay


def test_verified_runtime_refuses_missing_or_modified_bytes(tmp_path, monkeypatch):
    body = b"verified upstream runtime"
    monkeypatch.setattr(
        overlay,
        "policy",
        lambda: {
            "files": {
                "libssl-3-x64.dll": {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
            }
        },
    )
    with pytest.raises(ValueError, match="unverified"):
        overlay.verify_runtime(tmp_path)
    path = tmp_path / "libssl-3-x64.dll"
    path.write_bytes(body)
    overlay.verify_runtime(tmp_path)
    path.write_bytes(b"x" * len(body))
    with pytest.raises(ValueError, match="unverified"):
        overlay.verify_runtime(tmp_path)


def test_overlay_keeps_binary_names_and_full_license_provenance(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    files = ["libcrypto-3-x64.dll", "libssl-3-x64.dll", "LICENSE.txt", "provenance.json"]
    for name in files:
        (runtime / name).write_text(name)
    monkeypatch.setattr(overlay, "policy", lambda: {"files": dict.fromkeys(files)})
    monkeypatch.setattr(overlay, "acquire_runtime", lambda cache: runtime)
    checked = []
    monkeypatch.setattr(
        overlay, "assert_compatible_imports", lambda consumers, root: checked.extend(consumers)
    )
    out = tmp_path / "closure"
    (out / "bin").mkdir(parents=True)
    consumer = out / "bin/consumer.dll"
    consumer.write_bytes(b"consumer")
    owners = overlay.overlay_directory(out, tmp_path / "cache")
    assert checked == [consumer]
    assert set(owners) == {
        "bin/libcrypto-3-x64.dll",
        "bin/libssl-3-x64.dll",
        "licenses/openssl-3.5.9/LICENSE.txt",
        "licenses/openssl-3.5.9/provenance.json",
    }
    assert owners["bin/libcrypto-3-x64.dll"] == (
        "openssl",
        "3.5.9",
        "Apache-2.0 AND LicenseRef-Microsoft-VCRedist",
    )
    assert not (out / "bin/libcrypto-3.dll").exists()


def test_postgres_overlay_preserves_original_selection(tmp_path, monkeypatch):
    monkeypatch.setattr(overlay, "acquire_runtime", lambda cache: tmp_path)
    monkeypatch.setattr(
        overlay, "policy", lambda: {"files": {"libssl-3-x64.dll": {}, "LICENSE.txt": {}}}
    )
    monkeypatch.setattr(overlay, "assert_compatible_imports", lambda consumers, root: None)
    original = {"bin/postgres.exe": Path("original.exe"), "bin/libssl-3-x64.dll": Path("old.dll")}
    result = overlay.secured_postgres_sources(original, tmp_path)
    assert result["bin/postgres.exe"] == original["bin/postgres.exe"]
    assert result["bin/libssl-3-x64.dll"] == tmp_path / "libssl-3-x64.dll"
    assert "licenses/openssl-3.5.9/LICENSE.txt" in result
    assert original["bin/libssl-3-x64.dll"] == Path("old.dll")
