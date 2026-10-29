import hashlib
import json

import pytest

from civiccast.native import python_runtime as runtime


@pytest.fixture
def fixture_runtime(monkeypatch):
    files = {"python.exe": b"MZ-reviewed", "python312._pth": b"original-pth"}
    provenance = {
        "schema_version": 1,
        "distribution": runtime.INTERPRETER_DISTRIBUTION,
        "version": runtime.INTERPRETER_VERSION,
        "architecture": "amd64",
        "builder_sha256": runtime.BUILDER_SHA256,
        "files": {
            name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in files.items()
        },
    }

    def pin():
        raw = json.dumps(provenance).encode()
        files[runtime.PROVENANCE_PATH] = raw
        monkeypatch.setattr(runtime, "PROVENANCE_SHA256", hashlib.sha256(raw).hexdigest())

    pin()
    return files, provenance, pin


def test_original_and_installed_runtime(fixture_runtime):
    files, _, _ = fixture_runtime
    assert runtime.verify_runtime_files(files.__getitem__) == []
    files["python312._pth"] = runtime.INSTALLED_PTH
    assert runtime.verify_runtime_files(files.__getitem__, installed=True) == []
    files["python312._pth"] += b"untrusted-path\n"
    assert "python312._pth" in runtime.verify_runtime_files(files.__getitem__, installed=True)[0]


@pytest.mark.parametrize("field,value", [("version", "3.12.10"), ("builder_sha256", "0" * 64)])
def test_wrong_runtime_identity_rejected(fixture_runtime, field, value):
    files, provenance, pin = fixture_runtime
    provenance[field] = value
    pin()
    assert "identity/version/builder" in runtime.verify_runtime_files(files.__getitem__)[0]


def test_self_reported_provenance_cannot_authorize_new_binary(fixture_runtime):
    files, provenance, _ = fixture_runtime
    files["python.exe"] = b"MZ-altered"
    assert "python.exe" in runtime.verify_runtime_files(files.__getitem__)[0]
    provenance["files"]["python.exe"]["sha256"] = hashlib.sha256(files["python.exe"]).hexdigest()
    files[runtime.PROVENANCE_PATH] = json.dumps(provenance).encode()
    assert "SHA-256" in runtime.verify_runtime_files(files.__getitem__)[0]


def test_missing_runtime_file_rejected(fixture_runtime):
    files, _, _ = fixture_runtime
    del files["python.exe"]
    assert "missing" in runtime.verify_runtime_files(files.__getitem__)[0]
