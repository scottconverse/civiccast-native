import hashlib
import io
import json
import os
import subprocess
import types
import zipfile
from pathlib import Path

import pytest

from civiccast.native import python_runtime as runtime

BACKPORT_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "scripts/resources/cpython-3.12.16-http-client-security1.py.txt"
)


@pytest.fixture
def fixture_runtime(monkeypatch):
    stdlib = io.BytesIO()
    with zipfile.ZipFile(stdlib, "w") as archive:
        archive.writestr("http/client.pyc", b"original vulnerable bytecode")
        archive.writestr("http/__init__.pyc", b"unchanged package")
        archive.writestr("keep.pyc", b"unchanged bytecode")
    original = stdlib.getvalue()
    monkeypatch.setattr(runtime, "ORIGINAL_STDLIB_SHA256", hashlib.sha256(original).hexdigest())
    monkeypatch.setattr(runtime, "ORIGINAL_STDLIB_BYTES", len(original))
    monkeypatch.setattr(
        runtime,
        "PATCHED_STDLIB_SHA256",
        "c9a609f81dedcd0c9455845f8b463ccc7a5e910c0c6b4857ba7a5cf9538362fb",
    )
    monkeypatch.setattr(runtime, "PATCHED_STDLIB_BYTES", 60_151)
    files = {
        "python.exe": b"MZ-reviewed",
        "python312._pth": runtime.INSTALLED_PTH.replace(
            b"import site\nLib\\site-packages\n", b"#import site\n"
        ),
        runtime.STDLIB_PATH: original,
        "LICENSE.txt": b"Python Software Foundation License Version 2",
    }
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
    # The vulnerable original must not pass installed verification, even with
    # original provenance and a manifest that faithfully describes it.
    assert runtime.STDLIB_PATH in runtime.verify_runtime_files(files.__getitem__, installed=True)[0]
    files[runtime.STDLIB_PATH] = runtime.patch_stdlib_http_client(
        files[runtime.STDLIB_PATH], BACKPORT_SOURCE.read_bytes()
    )
    assert runtime.verify_runtime_files(files.__getitem__, installed=True) == []
    assert any(
        runtime.STDLIB_PATH in problem
        for problem in runtime.verify_runtime_files(files.__getitem__)
    )
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


def test_backport_changes_only_http_client_member(fixture_runtime):
    files, _, _ = fixture_runtime
    original = files[runtime.STDLIB_PATH]
    source = BACKPORT_SOURCE.read_bytes()
    patched = runtime.patch_stdlib_http_client(original, source)
    assert patched == runtime.patch_stdlib_http_client(original, source)
    with (
        zipfile.ZipFile(io.BytesIO(original)) as before,
        zipfile.ZipFile(io.BytesIO(patched)) as after,
    ):
        assert set(after.namelist()) == set(before.namelist()) - {"http/client.pyc"} | {
            "http/client.py"
        }
        assert after.read("http/client.py") == source
        for name in before.namelist():
            if name != "http/client.pyc":
                assert after.read(name) == before.read(name)
        for info in after.infolist():
            assert info.compress_type == zipfile.ZIP_STORED
            assert info.date_time == (1980, 1, 1, 0, 0, 0)
            assert info.create_system == 0
            assert info.external_attr == 0x20
            assert not info.extra and not info.comment


@pytest.mark.parametrize("tamper", ["input", "source", "output-pin"])
def test_backport_refuses_unreviewed_bytes(fixture_runtime, monkeypatch, tamper):
    files, _, _ = fixture_runtime
    original, source = files[runtime.STDLIB_PATH], BACKPORT_SOURCE.read_bytes()
    if tamper == "input":
        original += b"unreviewed"
    elif tamper == "source":
        source += b"unreviewed"
    else:
        monkeypatch.setattr(runtime, "PATCHED_STDLIB_SHA256", "0" * 64)
    with pytest.raises(
        ValueError, match={"input": "input", "source": "source", "output-pin": "output"}[tamper]
    ):
        runtime.patch_stdlib_http_client(original, source)


def test_installed_verifier_rejects_changed_or_missing_stdlib(fixture_runtime):
    files, provenance, pin = fixture_runtime
    files["python312._pth"] = runtime.INSTALLED_PTH
    files[runtime.STDLIB_PATH] = runtime.patch_stdlib_http_client(
        files[runtime.STDLIB_PATH], BACKPORT_SOURCE.read_bytes()
    )
    files[runtime.STDLIB_PATH] += b"unreviewed"
    assert runtime.STDLIB_PATH in runtime.verify_runtime_files(files.__getitem__, installed=True)[0]
    del provenance["files"][runtime.STDLIB_PATH]
    pin()
    assert (
        "omits required patched stdlib"
        in runtime.verify_runtime_files(files.__getitem__, installed=True)[0]
    )


def _write_input_archive(tmp_path, monkeypatch, files):
    from scripts import build_native_app_payload as builder

    path = tmp_path / "original-runtime.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    monkeypatch.setattr(
        builder, "INTERPRETER_SHA256", hashlib.sha256(path.read_bytes()).hexdigest()
    )
    monkeypatch.setattr(builder, "INTERPRETER_ZIP_BYTES", path.stat().st_size)
    return builder, path


def test_extraction_applies_backport_and_preserves_provenance_license(
    fixture_runtime, tmp_path, monkeypatch
):
    files, _, _ = fixture_runtime
    builder, path = _write_input_archive(tmp_path, monkeypatch, files)
    out = tmp_path / "installed"
    builder.extract_verified_interpreter(path, out)
    assert (
        runtime.verify_runtime_files(lambda name: (out / name).read_bytes(), installed=True) == []
    )
    for name in files.keys() - {runtime.STDLIB_PATH, "python312._pth"}:
        assert (out / name).read_bytes() == files[name]


def test_extraction_refuses_changed_backport_before_writing(fixture_runtime, tmp_path, monkeypatch):
    files, _, _ = fixture_runtime
    builder, path = _write_input_archive(tmp_path, monkeypatch, files)
    changed = tmp_path / "changed.py.txt"
    changed.write_bytes(BACKPORT_SOURCE.read_bytes() + b"unreviewed")
    monkeypatch.setattr(builder, "HTTP_CLIENT_BACKPORT_SOURCE", changed)
    out = tmp_path / "refused"
    with pytest.raises(SystemExit):
        builder.extract_verified_interpreter(path, out)
    assert not out.exists()


@pytest.fixture
def patched_client():
    client = types.ModuleType("patched_http_client")
    exec(compile(BACKPORT_SOURCE.read_bytes(), "http/client.py", "exec"), client.__dict__)
    return client


class _Socket:
    def __init__(self, response):
        self.response = response

    def makefile(self, _mode):
        return io.BytesIO(self.response)


@pytest.mark.parametrize("value", [b"+5", b"5_0", b"-5", b"0x5"])
def test_backported_client_does_not_frame_with_malformed_content_length(patched_client, value):
    response = patched_client.HTTPResponse(
        _Socket(b"HTTP/1.1 200 OK\r\nContent-Length: " + value + b"\r\n\r\nHello\r\n")
    )
    response.begin()
    assert response.length is None
    assert response.will_close
    assert response.read() == b"Hello\r\n"
    assert response.isclosed()


@pytest.mark.parametrize("size", [b"-5", b"+5", b"0x5", b"1_f", b" 5", b"\t5"])
def test_backported_client_rejects_malformed_chunk_size(patched_client, size):
    response = patched_client.HTTPResponse(
        _Socket(
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
            + size
            + b"\r\nHELLO\r\n0\r\n\r\n"
        )
    )
    response.begin()
    with pytest.raises(patched_client.IncompleteRead):
        response.read()
    assert response.isclosed()


@pytest.mark.parametrize("length,expected", [(b"5", b"Hello"), (b"05", b"Hello"), (b"0", b"")])
def test_backported_client_keeps_valid_content_length(patched_client, length, expected):
    response = patched_client.HTTPResponse(
        _Socket(b"HTTP/1.1 200 OK\r\nContent-Length: " + length + b"\r\n\r\nHelloNEXT")
    )
    response.begin()
    assert response.read() == expected


@pytest.mark.parametrize("size", [b"a", b"A", b"a;extension=ok", b"a \t"])
def test_backported_client_keeps_valid_chunks_and_extensions(patched_client, size):
    response = patched_client.HTTPResponse(
        _Socket(
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
            + size
            + b"\r\nHELLOWORLD\r\n0\r\n\r\n"
        )
    )
    response.begin()
    assert response.read() == b"HELLOWORLD"


@pytest.mark.windows_only
@pytest.mark.integration
@pytest.mark.skipif(
    os.name != "nt" or not os.environ.get("CIVICCAST_TEST_PYTHON_RUNTIME_ARCHIVE"),
    reason="explicit cached native CPython archive required for disposable interpreter proof",
)
def test_cached_native_interpreter_uses_pinned_http_backport(tmp_path):
    from scripts import build_native_app_payload as builder

    archive_path = Path(os.environ["CIVICCAST_TEST_PYTHON_RUNTIME_ARCHIVE"])
    out = tmp_path / "native-python"
    builder.extract_verified_interpreter(archive_path, out)
    with zipfile.ZipFile(archive_path) as archive:
        original = archive.read(runtime.STDLIB_PATH)
        for name in archive.namelist():
            if name not in {runtime.STDLIB_PATH, "python312._pth"}:
                assert (out / name).read_bytes() == archive.read(name)
    with (
        zipfile.ZipFile(io.BytesIO(original)) as before,
        zipfile.ZipFile(out / runtime.STDLIB_PATH) as after,
    ):
        assert set(after.namelist()) == set(before.namelist()) - {"http/client.pyc"} | {
            "http/client.py"
        }
        for name in before.namelist():
            if name != "http/client.pyc":
                assert after.read(name) == before.read(name)
        original_pyc = before.read("http/client.pyc")
    (tmp_path / "original-client.pyc").write_bytes(original_pyc)
    script = r"""
import hashlib, http.client as client, io, json, marshal, sys, types
from pathlib import Path
assert sys.version_info[:3] == (3, 12, 16), sys.version
assert client.__file__.replace(chr(92), "/").endswith("/http/client.py"), client.__file__
assert hashlib.sha256(client.__loader__.get_data(client.__file__)).hexdigest() == SOURCE_SHA
class Socket:
    def __init__(self, data): self.data = data
    def makefile(self, mode): return io.BytesIO(self.data)
def response(module, headers, body):
    result = module.HTTPResponse(Socket(b"HTTP/1.1 200 OK\r\n" + headers + b"\r\n\r\n" + body))
    result.begin()
    return result
original = types.ModuleType("original_http_client")
exec(marshal.loads(Path(ORIGINAL_PYC).read_bytes()[16:]), original.__dict__)
assert response(original, b"Content-Length: +5", b"Hello\r\n").read() == b"Hello"
assert response(original, b"Transfer-Encoding: chunked", b"0x5\r\nHELLO\r\n0\r\n\r\n").read() == b"HELLO"
for value in (b"+5", b"5_0", b"-5", b"0x5"):
    result = response(client, b"Content-Length: " + value, b"Hello\r\n")
    assert result.length is None and result.will_close
    assert result.read() == b"Hello\r\n"
for size in (b"-5", b"+5", b"0x5", b"1_f", b" 5", b"\t5"):
    result = response(client, b"Transfer-Encoding: chunked", size + b"\r\nHELLO\r\n0\r\n\r\n")
    try: result.read()
    except client.IncompleteRead: pass
    else: raise AssertionError(size)
    assert result.isclosed()
assert response(client, b"Content-Length: 5", b"HelloNEXT").read() == b"Hello"
assert response(client, b"Transfer-Encoding: chunked", b"A;ok=yes\r\nHELLOWORLD\r\n0\r\n\r\n").read() == b"HELLOWORLD"
print(json.dumps({"status":"PASS", "version":sys.version, "http_client":client.__file__, "source_sha256":SOURCE_SHA, "original_vulnerable":True, "malformed_content_lengths":4, "malformed_chunk_sizes":6, "positive_cases":2}))
"""
    script = (
        f"SOURCE_SHA={runtime.HTTP_CLIENT_SOURCE_SHA256!r}\n"
        f"ORIGINAL_PYC={str(tmp_path / 'original-client.pyc')!r}\n" + script
    )
    result = subprocess.run(
        [str(out / "python.exe"), "-I", "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    (tmp_path / "http-client-proof.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
