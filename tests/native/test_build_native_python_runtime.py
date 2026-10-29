# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Fail-closed source inputs and bounded upstream CPython build overrides."""

from __future__ import annotations

import hashlib
import importlib.util
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_native_python_runtime.py"
spec = importlib.util.spec_from_file_location("build_native_python_runtime", SCRIPT)
assert spec is not None and spec.loader is not None
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_runtime_inputs_pin_security_source_and_modern_external_dependencies():
    assert builder.VERSION == "3.12.16"
    assert builder.SOURCE["url"].endswith("/Python-3.12.16.tgz")
    assert builder.SOURCE["sha256"] == (
        "710c3e75dac8b2f258d9cd0f76e5c4c2e9175fac9e249c98901552f7cf33b7dd"
    )
    assert {item["name"]: item["version"] for item in builder.DEPENDENCIES} == {
        "bzip2": "1.0.8",
        "libffi": "3.4.4",
        "openssl": "3.5.9",
        "sqlite": "3.54.1",
        "zlib": "1.3.2",
        "xz": "5.8.3",
    }
    for item in [builder.SOURCE, *builder.DEPENDENCIES]:
        assert len(item["sha256"]) == 64 and item["license"]


def test_cached_source_hash_mismatch_never_reaches_extraction(tmp_path):
    path = tmp_path / "source-1.zip"
    path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="cached input SHA256 mismatch"):
        builder.fetch_input(
            {
                "name": "source",
                "version": "1",
                "url": "https://example.org/a.zip",
                "sha256": hashlib.sha256(b"reviewed").hexdigest(),
            },
            tmp_path,
        )


def test_archive_reuse_checks_original_source_contents(tmp_path):
    archive = tmp_path / "input.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("source/PCbuild/build.bat", "reviewed upstream")
    output = tmp_path / "source"
    builder.unpack_input(archive, output)
    builder.unpack_input(archive, output)
    assert (output / "PCbuild" / "build.bat").read_text() == "reviewed upstream"
    (output / "PCbuild" / "build.bat").write_text("unreviewed local patch")
    with pytest.raises(ValueError, match="modified runtime source cache"):
        builder.unpack_input(archive, output)


def test_upstream_generated_crlf_text_can_resume_without_accepting_modified_code(tmp_path):
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("source/Python/generated.c", b"/* upstream */\nint x;\n")
    target = tmp_path / "source"
    builder.unpack_input(archive, target)
    generated = target / "Python" / "generated.c"
    generated.write_bytes(b"/* upstream */\r\nint x;\r\n")
    builder.unpack_input(archive, target)
    generated.write_bytes(b"/* upstream */\r\nint changed;\r\n")
    with pytest.raises(ValueError, match="modified runtime source cache"):
        builder.unpack_input(archive, target)


@pytest.mark.parametrize("name", ["source/../../escape", "C:/escape", "source/..\\escape"])
def test_source_extraction_refuses_escaping_paths(tmp_path, name):
    archive = tmp_path / "input.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(name, "unsafe")
    with pytest.raises(ValueError, match="unsafe runtime source archive path"):
        builder.unpack_input(archive, tmp_path / "output")
    assert not (tmp_path / "escape").exists()


def test_compile_override_caps_workers_and_uses_upstream_liblzma(tmp_path):
    path = tmp_path / "compile.props"
    builder.write_compile_overrides(path)
    root = ElementTree.parse(path).getroot()
    namespace = {"m": "http://schemas.microsoft.com/developer/msbuild/2003"}
    assert root.find(".//m:MultiProcessorCompilation", namespace).text == "false"
    removal = root.find(".//m:ProjectReference", namespace)
    assert removal.attrib == {"Remove": "liblzma.vcxproj"}
    group = root.find("m:ItemGroup", namespace)
    assert group.attrib["Condition"] == "'$(MSBuildProjectName)' == '_lzma'"


def test_dependency_overrides_escape_paths_and_avoid_upstream_stale_defaults(tmp_path):
    path = tmp_path / "deps.props"
    deps = tmp_path / "deps & dependencies"
    builder.write_overrides(path, deps)
    root = ElementTree.parse(path).getroot()
    namespace = {"m": "http://schemas.microsoft.com/developer/msbuild/2003"}
    assert root.find(".//m:opensslOutDir", namespace).text == str(deps / "openssl" / "amd64") + "\\"
    assert root.find(".//m:sqlite3Dir", namespace).text == str(deps / "sqlite-3.54.1.0") + "\\"
