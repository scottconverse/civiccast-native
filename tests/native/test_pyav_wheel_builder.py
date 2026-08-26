# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Policy tests for the reproducible LGPL-only native PyAV wheel."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_native_pyav_wheel.py"
_SPEC = importlib.util.spec_from_file_location("build_native_pyav_wheel", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
builder = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = builder
_SPEC.loader.exec_module(builder)


def _minimal_wheel(path: Path, *, timestamp: tuple[int, ...], reverse: bool = False) -> None:
    entries = [
        ("av/__init__.py", b'__version__ = "18.0.0"\n'),
        ("av.libs/avcodec-62-test.dll", b"fake-pe"),
        ("av-18.0.0.dist-info/METADATA", b"Name: av\nVersion: 18.0.0\n"),
        ("av-18.0.0.dist-info/RECORD", b""),
    ]
    if reverse:
        entries.reverse()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries:
            info = zipfile.ZipInfo(name, date_time=timestamp)
            archive.writestr(info, payload)


def test_supply_inputs_and_toolchain_are_exactly_pinned() -> None:
    assert builder.PYAV_VERSION == "18.0.0"
    assert builder.PYAV_SDIST_BYTES == 4_340_222
    assert builder.PYAV_SDIST_SHA256 == (
        "4ef7e72c3d3a872584a1215173b16e0226811037f40dcdbf75992631098df1ba"
    )
    assert builder.PYAV_SDIST_URL.startswith("https://files.pythonhosted.org/")

    assert builder.FFMPEG_COMMIT == "8c9502e9b048e21e1cae96477e338ac0635645ba"
    assert builder.FFMPEG_SOURCE_BYTES == 16_902_915
    assert builder.FFMPEG_SOURCE_SHA256 == (
        "97da8d05b040186096349179bd349168609235781776acee37015e87f8e898fc"
    )
    assert builder.FFMPEG_SOURCE_URL.endswith(f"{builder.FFMPEG_COMMIT}.tar.gz")
    assert builder.MSYS2_BASE_BYTES == 53_555_380
    assert builder.MSYS2_BASE_SHA256 == (
        "a2d047e8ee213c3c6a49a8de427eb1069df12207c0422ff1b3cbb5c905c34221"
    )
    assert len(builder.MSYS2_BUILD_PACKAGES) == 3
    assert "--disable-autodetect" in builder.FFMPEG_CONFIGURE_OPTIONS
    assert "--disable-everything" in builder.FFMPEG_CONFIGURE_OPTIONS
    assert "--extra-cflags=/Brepro @civiccast-cl.rsp" in (builder.FFMPEG_CONFIGURE_OPTIONS)

    assert builder.MSVC_COMPILER_VERSION == "19.50.35730"
    assert builder.MSVC_LINKER_VERSION == "14.50.35730.0"
    assert builder.SOURCE_DATE_EPOCH == 1_704_067_200
    assert builder.EXPECTED_WHEEL_BYTES == 4_347_090
    assert builder.EXPECTED_WHEEL_SHA256 == (
        "0f9427a4e2e46944d87a21df6c9d6daeb15363001e8bf371a2d10155ed2a4fce"
    )


def test_verify_artifact_rejects_wrong_hash(tmp_path: Path) -> None:
    artifact = tmp_path / "input.bin"
    artifact.write_bytes(b"wrong")

    with pytest.raises(builder.PyAvWheelBuildError, match="SHA-256"):
        builder.verify_artifact(
            artifact,
            expected_bytes=len(b"wrong"),
            expected_sha256="0" * 64,
        )


def test_verify_artifact_reports_hash_when_byte_length_is_wrong(tmp_path: Path) -> None:
    artifact = tmp_path / "input.bin"
    artifact.write_bytes(b"wrong")
    actual_sha256 = hashlib.sha256(b"wrong").hexdigest()

    with pytest.raises(
        builder.PyAvWheelBuildError,
        match=rf"byte length 5 != pinned 4; SHA-256 {actual_sha256}",
    ):
        builder.verify_artifact(
            artifact,
            expected_bytes=4,
            expected_sha256="0" * 64,
        )


def test_verify_artifact_advisory_mode_warns_instead_of_raising(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact = tmp_path / "input.bin"
    artifact.write_bytes(b"wrong")

    # Must not raise -- this is the whole point of advisory mode.
    builder.verify_artifact(
        artifact,
        expected_bytes=len(b"wrong"),
        expected_sha256="0" * 64,
        advisory=True,
    )
    captured = capsys.readouterr()
    assert "::warning::" in captured.out
    assert "advisory" in captured.out.lower()
    assert "SHA-256" in captured.out


def test_verify_artifact_advisory_mode_is_silent_on_a_match(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact = tmp_path / "input.bin"
    artifact.write_bytes(b"right")
    actual_sha256 = hashlib.sha256(b"right").hexdigest()

    builder.verify_artifact(
        artifact,
        expected_bytes=len(b"right"),
        expected_sha256=actual_sha256,
        advisory=True,
    )
    captured = capsys.readouterr()
    assert captured.out == ""


def test_verify_artifact_default_advisory_false_still_raises(tmp_path: Path) -> None:
    """Every pinned-download call site omits ``advisory`` -- confirm the
    default keeps them a hard failure, not just the explicit-False callers
    already covered above."""
    artifact = tmp_path / "input.bin"
    artifact.write_bytes(b"wrong")

    with pytest.raises(builder.PyAvWheelBuildError, match="SHA-256"):
        builder.verify_artifact(
            artifact,
            expected_bytes=len(b"wrong"),
            expected_sha256="0" * 64,
        )


def test_main_forwards_advisory_wheel_hash_flag_to_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real CLI parser in main() must accept --advisory-wheel-hash and
    forward it through to build() -- not a reimplemented parser."""
    received: dict[str, object] = {}

    def _fake_build(
        *, output_dir: Path, cache_dir: Path, scratch: Path, advisory_wheel_hash: bool = False
    ):
        received["advisory_wheel_hash"] = advisory_wheel_hash
        wheel = output_dir / "av-18.0.0-cp312-cp312-win_amd64.whl"
        output_dir.mkdir(parents=True, exist_ok=True)
        wheel.write_bytes(b"stub")
        return wheel, {}

    monkeypatch.setattr(builder, "build", _fake_build)
    exit_code = builder.main(
        [
            "--output-dir",
            str(tmp_path / "out"),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--scratch",
            str(tmp_path / "scratch"),
            "--advisory-wheel-hash",
        ]
    )
    assert exit_code == 0
    assert received["advisory_wheel_hash"] is True


def test_main_defaults_advisory_wheel_hash_to_false(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, object] = {}

    def _fake_build(
        *, output_dir: Path, cache_dir: Path, scratch: Path, advisory_wheel_hash: bool = False
    ):
        received["advisory_wheel_hash"] = advisory_wheel_hash
        wheel = output_dir / "av-18.0.0-cp312-cp312-win_amd64.whl"
        output_dir.mkdir(parents=True, exist_ok=True)
        wheel.write_bytes(b"stub")
        return wheel, {}

    monkeypatch.setattr(builder, "build", _fake_build)
    exit_code = builder.main(
        [
            "--output-dir",
            str(tmp_path / "out"),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--scratch",
            str(tmp_path / "scratch"),
        ]
    )
    assert exit_code == 0
    assert received["advisory_wheel_hash"] is False


def test_safe_zip_extract_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("../escape.txt", "owned")

    with pytest.raises(builder.PyAvWheelBuildError, match="unsafe archive path"):
        builder.safe_extract_zip(archive, tmp_path / "out")


@pytest.mark.parametrize("member", ["safe/file.txt:evil", "safe:evil/file.txt"])
def test_safe_zip_extract_rejects_ntfs_alternate_data_streams(
    tmp_path: Path,
    member: str,
) -> None:
    archive = tmp_path / "bad-ads.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr(member, "owned")

    with pytest.raises(builder.PyAvWheelBuildError, match="unsafe archive path"):
        builder.safe_extract_zip(archive, tmp_path / "out")


def test_safe_tar_extract_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "bad.tar.gz"
    with tarfile.open(archive, "w:gz") as tarred:
        payload = b"owned"
        member = tarfile.TarInfo("../escape.txt")
        member.size = len(payload)
        tarred.addfile(member, io.BytesIO(payload))

    with pytest.raises(builder.PyAvWheelBuildError, match="unsafe archive path"):
        builder.safe_extract_tar(archive, tmp_path / "out")


def test_safe_tar_extract_rejects_links(tmp_path: Path) -> None:
    archive = tmp_path / "bad-link.tar.gz"
    with tarfile.open(archive, "w:gz") as tarred:
        member = tarfile.TarInfo("source-link")
        member.type = tarfile.SYMTYPE
        member.linkname = "../outside"
        tarred.addfile(member)

    with pytest.raises(builder.PyAvWheelBuildError, match="unsafe tar member type"):
        builder.safe_extract_tar(archive, tmp_path / "out")


def test_reproducible_build_environment_is_explicit() -> None:
    environment = builder.reproducible_build_environment({"PATH": "toolchain"})

    assert environment["PATH"] == "toolchain"
    assert environment["CL"] == "/Brepro"
    assert environment["LINK"] == "/Brepro"
    assert environment["SOURCE_DATE_EPOCH"] == str(builder.SOURCE_DATE_EPOCH)
    assert environment["PYTHONHASHSEED"] == "0"


def test_ffmpeg_build_environment_blocks_outer_repository_identity(tmp_path: Path) -> None:
    source_dir = tmp_path / "scratch" / "ffmpeg-source" / "FFmpeg-pinned"

    environment = builder.isolate_ffmpeg_git_discovery(
        {"PATH": "toolchain"},
        source_dir=source_dir,
    )

    assert environment["PATH"] == "toolchain"
    assert environment["GIT_CEILING_DIRECTORIES"] == str(source_dir.parent)


def test_ffmpeg_build_hardens_nasm_and_transient_windows_linking(tmp_path: Path) -> None:
    wrapper = tmp_path / "civiccast-mslink"

    builder.write_msvc_link_retry_wrapper(wrapper)

    assert builder.FFMPEG_X86ASM_EXE == "nasm --reproducible"
    assert builder.MSVC_LINK_RETRY_ATTEMPTS == 5
    text = wrapper.read_text(encoding="utf-8")
    assert "./compat/windows/mslink" in text
    assert "LNK1104: cannot open file" in text
    assert '$attempt" -ge "5"' in text


def test_acquire_verified_artifact_replaces_a_poisoned_cache(tmp_path: Path) -> None:
    destination = tmp_path / "artifact.bin"
    destination.write_bytes(b"poisoned")
    expected = b"reviewed artifact"
    calls: list[str] = []

    def download(url: str, target: Path) -> None:
        calls.append(url)
        target.write_bytes(expected)

    builder.acquire_verified_artifact(
        "https://example.test/artifact.bin",
        destination,
        expected_bytes=len(expected),
        expected_sha256=hashlib.sha256(expected).hexdigest(),
        downloader=download,
    )

    assert calls == ["https://example.test/artifact.bin"]
    assert destination.read_bytes() == expected


def test_acquire_verified_artifact_does_not_keep_a_bad_download(tmp_path: Path) -> None:
    destination = tmp_path / "artifact.bin"

    def download(_url: str, target: Path) -> None:
        target.write_bytes(b"wrong")

    with pytest.raises(builder.PyAvWheelBuildError, match="byte length"):
        builder.acquire_verified_artifact(
            "https://example.test/artifact.bin",
            destination,
            expected_bytes=99,
            expected_sha256="0" * 64,
            downloader=download,
        )

    assert not destination.exists()
    assert not destination.with_suffix(".bin.part").exists()


def test_parse_environment_and_exact_toolchain_versions() -> None:
    environment = builder.parse_set_output("Path=C:\\Tools\nEMPTY=\nBROKEN\n")
    assert environment == {"Path": "C:\\Tools", "EMPTY": ""}

    builder.assert_exact_toolchain_versions(
        subprocess.CompletedProcess(
            ["cl"], 2, stdout="", stderr="Microsoft C/C++ Compiler Version 19.50.35730"
        ),
        subprocess.CompletedProcess(
            ["link"], 1104, stdout="Microsoft Incremental Linker Version 14.50.35730.0", stderr=""
        ),
    )

    with pytest.raises(builder.PyAvWheelBuildError, match="compiler version"):
        builder.assert_exact_toolchain_versions(
            subprocess.CompletedProcess(["cl"], 2, stdout="", stderr="Version 19.40.0"),
            subprocess.CompletedProcess(["link"], 1104, stdout="Version 14.50.35730.0", stderr=""),
        )

    with pytest.raises(builder.PyAvWheelBuildError, match="compiler version"):
        builder.assert_exact_toolchain_versions(
            subprocess.CompletedProcess(
                ["cl"], 2, stdout="", stderr="Microsoft C/C++ Compiler Version 19.50.35730.99"
            ),
            subprocess.CompletedProcess(
                ["link"],
                1104,
                stdout="Microsoft Incremental Linker Version 14.50.35730.0",
                stderr="",
            ),
        )

    with pytest.raises(builder.PyAvWheelBuildError, match="linker version"):
        builder.assert_exact_toolchain_versions(
            subprocess.CompletedProcess(
                ["cl"], 2, stdout="", stderr="Microsoft C/C++ Compiler Version 19.50.35730"
            ),
            subprocess.CompletedProcess(
                ["link"],
                1104,
                stdout="Microsoft Incremental Linker Version 14.50.35730.0.99",
                stderr="",
            ),
        )


def test_msvc_environment_uses_a_wrapper_for_paths_with_spaces(tmp_path: Path) -> None:
    vcvarsall = tmp_path / "Visual Studio" / "vcvarsall.bat"
    vcvarsall.parent.mkdir(parents=True)
    vcvarsall.write_text("@echo off\n", encoding="utf-8")
    calls = 0

    def run(
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            assert command[:3] == ["cmd.exe", "/d", "/c"]
            wrapper = Path(command[3])
            wrapper_text = wrapper.read_text(encoding="utf-8")
            assert f'call "{vcvarsall}" x64' in wrapper_text
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="Path=C:\\MSVC\n",
                stderr="",
            )
        if command == ["cmd.exe", "/d", "/c", "cl.exe"]:
            return subprocess.CompletedProcess(
                command,
                2,
                stdout="",
                stderr="Microsoft C/C++ Compiler Version 19.50.35730",
            )
        assert command == ["cmd.exe", "/d", "/c", "link.exe"]
        return subprocess.CompletedProcess(
            command,
            1104,
            stdout="Microsoft Incremental Linker Version 14.50.35730.0",
            stderr="",
        )

    environment = builder.load_pinned_msvc_environment(vcvarsall, runner=run)

    assert environment["Path"] == "C:\\MSVC"
    assert environment["CL"] == "/Brepro"


def test_msvc_locator_honors_reviewed_installation_override(tmp_path: Path) -> None:
    installation = tmp_path / "BuildTools"
    vcvarsall = installation / "VC" / "Auxiliary" / "Build" / "vcvarsall.bat"
    vcvarsall.parent.mkdir(parents=True)
    vcvarsall.write_text("@echo off\n", encoding="utf-8")

    result = builder.find_vcvarsall(
        environment={
            "CIVICCAST_MSVC_INSTALLATION_PATH": str(installation),
            "ProgramFiles(x86)": str(tmp_path / "unused"),
        },
        runner=lambda *_args, **_kwargs: pytest.fail("vswhere must not run"),
    )

    assert result == vcvarsall


def test_build_and_repair_uses_pinned_ffmpeg_and_isolated_python(tmp_path: Path) -> None:
    source = tmp_path / "av-18.0.0"
    source.mkdir()
    ffmpeg = tmp_path / builder.FFMPEG_BUILD
    (ffmpeg / "bin").mkdir(parents=True)
    build_python = tmp_path / "build-env" / "Scripts" / "python.exe"
    build_python.parent.mkdir(parents=True)
    build_python.write_bytes(b"fake")
    work = tmp_path / "work"
    environment = builder.reproducible_build_environment({"PATH": "msvc"})
    calls: list[tuple[list[str], Path | None, dict[str, str] | None]] = []

    def run(
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        check: bool = False,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        assert check
        calls.append((command, cwd, env))
        if "bdist_wheel" in command:
            raw_dir = Path(command[command.index("--dist-dir") + 1])
            raw_dir.mkdir(parents=True, exist_ok=True)
            _minimal_wheel(
                raw_dir / "av-18.0.0-cp311-abi3-win_amd64.whl",
                timestamp=(2024, 1, 1, 0, 0, 0),
            )
        if "delvewheel" in command:
            repaired_dir = Path(command[command.index("--wheel-dir") + 1])
            repaired_dir.mkdir(parents=True, exist_ok=True)
            source_wheel = Path(command[command.index("repair") + 1])
            (repaired_dir / source_wheel.name).write_bytes(source_wheel.read_bytes())
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    repaired = builder.build_and_repair_wheel(
        source_dir=source,
        ffmpeg_dir=ffmpeg,
        build_python=build_python,
        work_dir=work,
        environment=environment,
        runner=run,
    )

    assert repaired.name == "av-18.0.0-cp311-abi3-win_amd64.whl"
    build_command, build_cwd, build_environment = calls[0]
    assert build_command == [
        str(build_python),
        "setup.py",
        f"--ffmpeg-dir={ffmpeg}",
        "bdist_wheel",
        "--dist-dir",
        str(work / "raw"),
    ]
    assert build_cwd == source
    assert build_environment == environment
    repair_command, _, repair_environment = calls[1]
    assert repair_command == [
        str(build_python),
        "-m",
        "delvewheel",
        "repair",
        str(work / "raw" / repaired.name),
        "--add-path",
        str(ffmpeg / "bin"),
        "--wheel-dir",
        str(work / "repaired"),
    ]
    assert repair_environment == environment


def test_runtime_probe_requires_all_lgpl_libraries_and_real_decode() -> None:
    report = {
        "pyav_version": "18.0.0",
        "dlls": [f"{prefix}test.dll" for prefix in builder._ALLOWED_FFMPEG_DLL_PREFIXES],
        "licenses": {
            prefix.removesuffix("-"): "LGPL version 2.1 or later"
            for prefix in builder._ALLOWED_FFMPEG_DLL_PREFIXES
        },
        "decoded_frames": 16,
    }
    builder.assert_runtime_probe_report(report)

    report["licenses"]["avcodec"] = "GPL version 3 or later"
    with pytest.raises(builder.PyAvWheelBuildError, match="non-LGPL"):
        builder.assert_runtime_probe_report(report)

    report["licenses"]["avcodec"] = "LGPL version 2.1 or later"
    report["decoded_frames"] = 0
    with pytest.raises(builder.PyAvWheelBuildError, match="decoded no audio frames"):
        builder.assert_runtime_probe_report(report)


def test_notice_repack_is_byte_reproducible_and_record_complete(tmp_path: Path) -> None:
    wheel_a = tmp_path / "a.whl"
    wheel_b = tmp_path / "b.whl"
    _minimal_wheel(wheel_a, timestamp=(2024, 1, 1, 0, 0, 0))
    _minimal_wheel(wheel_b, timestamp=(2026, 7, 24, 12, 0, 0), reverse=True)

    lgpl = tmp_path / "LGPL-2.1.txt"
    lgpl.write_text("GNU LESSER GENERAL PUBLIC LICENSE Version 2.1\n", encoding="utf-8")
    provenance = {
        "component": "FFmpeg",
        "license": "LGPL-2.1-or-later",
        "source_archive_url": builder.FFMPEG_SOURCE_URL,
        "source_archive_sha256": builder.FFMPEG_SOURCE_SHA256,
        "relinking": "Replace the shared DLLs with interface-compatible builds.",
    }

    out_a = tmp_path / "out-a.whl"
    out_b = tmp_path / "out-b.whl"
    builder.repack_with_ffmpeg_notices(
        wheel_a,
        out_a,
        lgpl_text=lgpl.read_bytes(),
        provenance=provenance,
    )
    builder.repack_with_ffmpeg_notices(
        wheel_b,
        out_b,
        lgpl_text=lgpl.read_bytes(),
        provenance=provenance,
    )

    assert out_a.read_bytes() == out_b.read_bytes()
    with zipfile.ZipFile(out_a) as archive:
        names = set(archive.namelist())
        license_root = "av-18.0.0.dist-info/licenses"
        assert f"{license_root}/FFmpeg-LGPL-2.1-or-later.txt" in names
        assert "av-18.0.0.dist-info/FFMPEG-PROVENANCE.json" in names
        assert json.loads(archive.read("av-18.0.0.dist-info/FFMPEG-PROVENANCE.json")) == provenance

        record_path = "av-18.0.0.dist-info/RECORD"
        record = list(csv.reader(io.StringIO(archive.read(record_path).decode("utf-8"))))
        recorded_paths = {row[0] for row in record}
        assert recorded_paths == names
        record_row = next(row for row in record if row[0] == record_path)
        assert record_row == [record_path, "", ""]


def test_wheel_policy_rejects_missing_notices_and_forbidden_dlls(tmp_path: Path) -> None:
    wheel = tmp_path / "unsafe.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("av.libs/avcodec-62-test.dll", b"fake-pe")
        archive.writestr("av.libs/x264-test.dll", b"forbidden")
        archive.writestr("av-18.0.0.dist-info/RECORD", b"")

    with pytest.raises(builder.PyAvWheelBuildError, match="forbidden"):
        builder.validate_wheel_layout(wheel)


def test_wheel_policy_requires_the_complete_ffmpeg_dll_set(tmp_path: Path) -> None:
    wheel = tmp_path / "incomplete.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("av.libs/avcodec-62-test.dll", b"fake-pe")
        archive.writestr(
            "av-18.0.0.dist-info/licenses/FFmpeg-LGPL-2.1-or-later.txt",
            b"LGPL",
        )
        archive.writestr("av-18.0.0.dist-info/FFMPEG-PROVENANCE.json", b"{}")
        archive.writestr("av-18.0.0.dist-info/RECORD", b"")

    with pytest.raises(builder.PyAvWheelBuildError, match="missing FFmpeg DLL"):
        builder.validate_wheel_layout(wheel)
