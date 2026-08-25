# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Clean-host provisioning policy for the native Windows build toolchain."""

from __future__ import annotations

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

from civiccast.native.app_payload import APP_BUILD_TOOLCHAIN


def _load() -> object:
    path = Path(__file__).resolve().parents[2] / "scripts" / "provision_native_build_toolchain.py"
    spec = importlib.util.spec_from_file_location(
        "provision_native_build_toolchain",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


provisioner = _load()


def test_committed_lock_is_complete_and_matches_runtime_attestation() -> None:
    lock = provisioner.load_lock()

    assert lock["schema_version"] == 1
    assert lock["target"] == "windows-x86_64"
    assert set(lock["artifacts"]) == {"node", "npm", "python", "uv", "msvc"}
    assert lock["installed_identities"] == APP_BUILD_TOOLCHAIN

    artifacts = lock["artifacts"]
    assert artifacts["node"] == {
        "version": "24.15.0",
        "url": "https://nodejs.org/dist/v24.15.0/node-v24.15.0-win-x64.zip",
        "filename": "node-v24.15.0-win-x64.zip",
        "bytes": 36_465_163,
        "sha256": "cc5149eabd53779ce1e7bdc5401643622d0c7e6800ade18928a767e940bb0e62",
        "archive": "zip",
        "strip_prefix": "node-v24.15.0-win-x64",
    }
    assert artifacts["npm"]["version"] == "11.12.1"
    assert artifacts["npm"]["sha256"] == (
        "e679850e663b16f5f146ee425d0eb0e3442c1d2bda3d513bbfd7c81f5ee5db38"
    )
    assert artifacts["python"]["version"] == "3.12.13+20260510"
    assert artifacts["python"]["sha256"] == (
        "24168aff2e7d93784c6a436124c4ebb79b076a4e289bde4902c08333507b71d0"
    )
    assert artifacts["uv"]["version"] == "0.11.15"
    assert artifacts["uv"]["sha256"] == (
        "04b98d414a9000e25e5e0e7c9f53749e66b790cdaffc582829e6f58c544ee11c"
    )

    msvc = artifacts["msvc"]
    assert msvc["version"] == "18.5.2+11723.231"
    assert msvc["url"].startswith("https://download.visualstudio.microsoft.com/download/pr/")
    assert msvc["sha256"] == ("97b2740209702f310a53d1e92ce971e86aafbde916a4d6cd087464e98ff61e2b")
    assert msvc["compiler_version"] == "19.50.35730"
    assert msvc["linker_version"] == "14.50.35730.0"
    assert msvc["components"] == [
        "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
        "Microsoft.VisualStudio.Component.VC.Redist.14.Latest",
        "Microsoft.VisualStudio.Component.Windows11SDK.26100",
    ]
    provisioner.validate_lock(lock)


class _Response(io.BytesIO):
    def __init__(self, body: bytes, final_url: str) -> None:
        super().__init__(body)
        self._final_url = final_url

    def geturl(self) -> str:
        return self._final_url

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _artifact(body: bytes) -> dict[str, object]:
    return {
        "version": "1",
        "url": "https://nodejs.org/tool.zip",
        "filename": "tool.zip",
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "archive": "zip",
        "strip_prefix": "tool",
    }


def test_fetch_verifies_redirect_host_size_and_digest_before_cache_use(
    tmp_path: Path,
) -> None:
    body = b"reviewed artifact"
    calls: list[str] = []

    def opener(request: object, *, timeout: float) -> _Response:
        calls.append(request.full_url)  # type: ignore[attr-defined]
        assert timeout == 60
        return _Response(body, "https://nodejs.org/tool.zip")

    result = provisioner.fetch_locked_artifact(
        "node",
        _artifact(body),
        tmp_path,
        opener=opener,
    )
    assert result.read_bytes() == body
    assert calls == ["https://nodejs.org/tool.zip"]
    assert not (tmp_path / "tool.zip.partial").exists()

    result = provisioner.fetch_locked_artifact(
        "node",
        _artifact(body),
        tmp_path,
        offline=True,
        opener=lambda *_args, **_kwargs: pytest.fail("cache should be reused"),
    )
    assert result.read_bytes() == body

    result.write_bytes(b"tampered")
    with pytest.raises(provisioner.ToolchainProvisionError, match=r"SHA-256|size"):
        provisioner.fetch_locked_artifact(
            "node",
            _artifact(body),
            tmp_path,
            offline=True,
        )


def test_fetch_rejects_unapproved_source_and_redirect_hosts(tmp_path: Path) -> None:
    body = b"reviewed artifact"
    invalid = _artifact(body)
    invalid["url"] = "http://nodejs.org/tool.zip"
    with pytest.raises(provisioner.ToolchainProvisionError, match="HTTPS"):
        provisioner.fetch_locked_artifact("node", invalid, tmp_path)

    def opener(_request: object, *, timeout: float) -> _Response:
        assert timeout == 60
        return _Response(body, "https://attacker.example/tool.zip")

    with pytest.raises(provisioner.ToolchainProvisionError, match="redirect"):
        provisioner.fetch_locked_artifact(
            "node",
            _artifact(body),
            tmp_path,
            opener=opener,
        )


@pytest.mark.parametrize("archive_kind", ["zip", "tar.gz"])
def test_safe_extract_rejects_parent_traversal(
    tmp_path: Path,
    archive_kind: str,
) -> None:
    archive = tmp_path / f"unsafe.{archive_kind.replace('.', '')}"
    if archive_kind == "zip":
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("tool/../../escape.txt", b"escape")
    else:
        with tarfile.open(archive, "w:gz") as handle:
            info = tarfile.TarInfo("tool/../../escape.txt")
            info.size = len(b"escape")
            handle.addfile(info, io.BytesIO(b"escape"))

    with pytest.raises(provisioner.ToolchainProvisionError, match="unsafe"):
        provisioner.safe_extract(
            archive,
            tmp_path / "out",
            archive_kind=archive_kind,
            strip_prefix="tool",
        )
    assert not (tmp_path / "escape.txt").exists()


def test_safe_extract_strips_only_the_reviewed_prefix(tmp_path: Path) -> None:
    archive = tmp_path / "tool.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("tool/bin/tool.exe", b"binary")
        handle.writestr("tool/LICENSE", b"license")

    provisioner.safe_extract(
        archive,
        tmp_path / "out",
        archive_kind="zip",
        strip_prefix="tool",
    )

    assert (tmp_path / "out" / "bin" / "tool.exe").read_bytes() == b"binary"
    assert (tmp_path / "out" / "LICENSE").read_bytes() == b"license"


def test_msvc_layout_command_is_exact_and_noninteractive(tmp_path: Path) -> None:
    bootstrapper = tmp_path / "vs_BuildTools-18.5.2.exe"
    bootstrapper.write_bytes(b"stub")
    msvc = provisioner.load_lock()["artifacts"]["msvc"]

    command = provisioner.msvc_layout_command(
        bootstrapper,
        tmp_path / "layout",
        msvc,
    )

    assert command == [
        str(bootstrapper),
        "--layout",
        str(tmp_path / "layout"),
        "--lang",
        "en-US",
        "--add",
        "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
        "--add",
        "Microsoft.VisualStudio.Component.VC.Redist.14.Latest",
        "--add",
        "Microsoft.VisualStudio.Component.Windows11SDK.26100",
        "--quiet",
        "--wait",
        "--norestart",
    ]


def test_msvc_install_command_is_exact_and_noninteractive(tmp_path: Path) -> None:
    bootstrapper = tmp_path / "vs_BuildTools-18.5.2.exe"
    bootstrapper.write_bytes(b"stub")
    install_root = tmp_path / "BuildTools"
    msvc = provisioner.load_lock()["artifacts"]["msvc"]

    command = provisioner.msvc_install_command(
        bootstrapper,
        install_root,
        msvc,
    )

    assert command == [
        str(bootstrapper),
        "--installPath",
        str(install_root),
        "--add",
        "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
        "--add",
        "Microsoft.VisualStudio.Component.VC.Redist.14.Latest",
        "--add",
        "Microsoft.VisualStudio.Component.Windows11SDK.26100",
        "--quiet",
        "--wait",
        "--norestart",
    ]


def test_msvc_paths_longer_than_microsofts_documented_limit_are_refused() -> None:
    # Microsoft: "Make sure that your full installation path is less than 80
    # characters." https://learn.microsoft.com/en-us/visualstudio/install/
    # create-an-offline-installation-of-visual-studio
    # Observed 2026-07-30 on R7-TESTER: a 106-character --msvc-install path
    # made vs_BuildTools-18.5.2.exe exit 1 after its download, logging
    # "Warning: The root installation path is too long for this product."
    provisioner.assert_msvc_path_length(Path("C:/ccbt"), "--msvc-install")

    too_long = Path("C:/") / ("d" * 80)
    with pytest.raises(provisioner.ToolchainProvisionError) as refusal:
        provisioner.assert_msvc_path_length(too_long, "--msvc-install")

    message = str(refusal.value)
    assert str(too_long) in message
    assert "--msvc-install" in message
    assert "80" in message


def test_msvc_install_refuses_a_long_path_before_downloading_anything(
    tmp_path: Path,
) -> None:
    lock = provisioner.load_lock()
    cache = tmp_path / "cache"

    def _fail_on_fetch(*args: object, **kwargs: object) -> Path:
        raise AssertionError("the length refusal must fire before any download")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(provisioner, "fetch_locked_artifact", _fail_on_fetch)
        with pytest.raises(provisioner.ToolchainProvisionError):
            provisioner.install_msvc(lock, cache, Path("C:/") / ("d" * 80))

    assert not cache.exists()


def test_install_msvc_reuses_an_already_verified_install_without_reinstalling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Self-hosted `_work\\_temp` persists across runs (candidate run
    32810709045's own follow-up): a previous run's install can still be good.
    Reinstalling MSVC Build Tools takes real minutes -- verify-and-skip must
    not pay that cost when the existing tree is already trustworthy."""
    lock = provisioner.load_lock()
    install_root = tmp_path / "civiccast-msvc-build-tools"
    install_root.mkdir()
    (install_root / "marker").write_text("looks complete", encoding="utf-8")

    monkeypatch.setattr(provisioner, "verify_msvc_installation", lambda *a, **kw: None)
    monkeypatch.setattr(
        provisioner,
        "fetch_locked_artifact",
        lambda *a, **kw: pytest.fail("a verified-valid install must not be reinstalled"),
    )

    result = provisioner.install_msvc(lock, tmp_path / "cache", install_root)

    assert result == install_root
    assert (install_root / "marker").read_text(encoding="utf-8") == "looks complete"


def test_install_msvc_replaces_an_invalid_existing_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale/incomplete tree from an interrupted previous self-hosted run
    fails verification -- it must be cleared and reinstalled at the SAME
    canonical path, since every later workflow step reads
    $env:CIVICCAST_MSVC_INSTALLATION_PATH as a fixed literal."""
    # A real pytest tmp_path (deep under AppData\Local\Temp\pytest-of-...)
    # already exceeds Microsoft's real 80-character installation-path limit
    # on its own -- unrelated to what this test is about (already covered by
    # test_msvc_paths_longer_than_microsofts_documented_limit_are_refused).
    monkeypatch.setattr(provisioner, "_MSVC_PATH_LIMIT", 4096)
    lock = provisioner.load_lock()
    install_root = tmp_path / "civiccast-msvc-build-tools"
    install_root.mkdir()
    (install_root / "half-built").write_text("stale", encoding="utf-8")

    verify_calls: list[Path] = []

    def fake_verify(path: Path, *_a: object, **_kw: object) -> None:
        verify_calls.append(path)
        if len(verify_calls) == 1:
            raise provisioner.ToolchainProvisionError("stale install, missing vcvarsall.bat")
        # second call: the "freshly installed" tree passes.

    monkeypatch.setattr(provisioner, "verify_msvc_installation", fake_verify)
    monkeypatch.setattr(
        provisioner, "fetch_locked_artifact", lambda *a, **kw: tmp_path / "bootstrapper.exe"
    )
    monkeypatch.setattr(
        provisioner.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(a[0] if a else [], 0),
    )

    result = provisioner.install_msvc(lock, tmp_path / "cache", install_root)

    assert result == install_root
    assert not (install_root / "half-built").exists(), "the stale tree must have been cleared"
    assert len(verify_calls) == 2


def test_install_msvc_relocates_when_the_invalid_install_cannot_be_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Candidate run 32810709045's follow-up: the MSVC scratch was left
    undeletable (Access denied) after a prior run's cleanup died partway
    through with vctip.exe/mspdbsrv.exe still holding files open. Reuse must
    fall back to a sibling directory rather than failing the whole job."""
    # See the identical note in test_install_msvc_replaces_an_invalid_
    # existing_install: a real pytest tmp_path already exceeds the real
    # 80-character limit on its own, unrelated to what this test covers.
    monkeypatch.setattr(provisioner, "_MSVC_PATH_LIMIT", 4096)
    lock = provisioner.load_lock()
    install_root = tmp_path / "civiccast-msvc-build-tools"
    install_root.mkdir()
    (install_root / "cl.exe").write_bytes(b"unknown-completeness leftover")

    def fake_verify(path: Path, *_a: object, **_kw: object) -> None:
        if path == install_root:
            raise provisioner.ToolchainProvisionError("stale install, missing vcvarsall.bat")
        # any other (relocated) path passes -- simulates a good fresh install.

    def locked_rmtree(path: object, *a: object, **kw: object) -> None:
        raise OSError("Access is denied (simulated: vctip.exe/mspdbsrv.exe still open)")

    monkeypatch.setattr(provisioner, "verify_msvc_installation", fake_verify)
    monkeypatch.setattr(provisioner.shutil, "rmtree", locked_rmtree)
    monkeypatch.setattr(
        provisioner, "fetch_locked_artifact", lambda *a, **kw: tmp_path / "bootstrapper.exe"
    )
    monkeypatch.setattr(
        provisioner.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(a[0] if a else [], 0),
    )

    result = provisioner.install_msvc(lock, tmp_path / "cache", install_root)

    assert result != install_root
    assert result.parent == install_root.parent
    assert result.name.startswith(install_root.name + "-")
    # The old, undeletable tree is left behind untouched -- best-effort
    # cleanup is a later run's job, not this one's, per install_msvc's
    # docstring.
    assert (install_root / "cl.exe").exists()


def test_main_reexports_a_relocated_msvc_path_to_github_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every later workflow step (the Tauri vcvars64.bat import, the pack
    build's env block) reads $env:CIVICCAST_MSVC_INSTALLATION_PATH as a
    fixed literal -- when install_msvc() relocates, main() must re-export
    the ACTUAL path to GITHUB_ENV so those steps pick it up automatically."""
    requested = tmp_path / "civiccast-msvc-build-tools"
    relocated = tmp_path / "civiccast-msvc-build-tools-deadbeef"
    github_env = tmp_path / "github_env.txt"
    github_env.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_ENV", str(github_env))
    monkeypatch.setattr(
        provisioner, "provision_portable_toolchain", lambda *a, **kw: {"node": {"path": "x"}}
    )
    monkeypatch.setattr(
        provisioner,
        "install_msvc",
        lambda *a, **kw: relocated,
    )

    exit_code = provisioner.main(
        [
            "--cache",
            str(tmp_path / "cache"),
            "--output",
            str(tmp_path / "output"),
            "--msvc-install",
            str(requested),
        ]
    )

    assert exit_code == 0
    assert f"CIVICCAST_MSVC_INSTALLATION_PATH={relocated}\n" in github_env.read_text(
        encoding="utf-8"
    )


def test_main_does_not_touch_github_env_when_msvc_install_is_not_relocated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The common case (hosted lane always; self-hosted whenever nothing is
    locked) must not perturb GITHUB_ENV at all -- only an actual relocation
    is worth a re-export."""
    requested = tmp_path / "civiccast-msvc-build-tools"
    github_env = tmp_path / "github_env.txt"
    github_env.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_ENV", str(github_env))
    monkeypatch.setattr(
        provisioner, "provision_portable_toolchain", lambda *a, **kw: {"node": {"path": "x"}}
    )
    monkeypatch.setattr(provisioner, "install_msvc", lambda *a, **kw: requested)

    exit_code = provisioner.main(
        [
            "--cache",
            str(tmp_path / "cache"),
            "--output",
            str(tmp_path / "output"),
            "--msvc-install",
            str(requested),
        ]
    )

    assert exit_code == 0
    assert github_env.read_text(encoding="utf-8") == ""


def test_msvc_version_probe_rejects_compiler_or_linker_drift() -> None:
    msvc = provisioner.load_lock()["artifacts"]["msvc"]
    provisioner.assert_msvc_version_output(
        "Microsoft C/C++ Optimizing Compiler Version 19.50.35730",
        "Microsoft Incremental Linker Version 14.50.35730.0",
        msvc,
    )
    with pytest.raises(provisioner.ToolchainProvisionError, match="compiler"):
        provisioner.assert_msvc_version_output(
            "Compiler Version 19.50.35737",
            "Linker Version 14.50.35730.0",
            msvc,
        )
    with pytest.raises(provisioner.ToolchainProvisionError, match="linker"):
        provisioner.assert_msvc_version_output(
            "Compiler Version 19.50.35730",
            "Linker Version 14.50.35737.0",
            msvc,
        )


def test_portable_environment_points_only_at_provisioned_tools(tmp_path: Path) -> None:
    root = tmp_path / "toolchain"
    environment = provisioner.portable_environment(root, {"PATH": "host-tools"})

    assert environment["PATH"] == (f"{root / 'node'};{root / 'uv'};{root / 'python'};host-tools")
    assert environment["UV_PYTHON"] == str(root / "python" / "python.exe")
    assert environment["CIVICCAST_UV_EXE"] == str(root / "uv" / "uv.exe")
    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"


def test_lock_file_is_canonical_json() -> None:
    path = provisioner.LOCK_PATH
    parsed = json.loads(path.read_text(encoding="utf-8"))
    expected = json.dumps(parsed, indent=2, sort_keys=True) + "\n"
    assert path.read_text(encoding="utf-8") == expected


def test_cli_is_standalone_before_civiccast_is_installed() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(provisioner.ROOT / "scripts" / "provision_native_build_toolchain.py"),
            "--help",
        ],
        cwd=provisioner.ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "reviewed native-Windows build toolchain" in result.stdout
