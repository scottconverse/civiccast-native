# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S8-5 B: pull-on-demand TSDuck install helper.

Network/disk effects are injected, so these run offline. The happy-path and
integration tests drive the REAL _safe_extract_zip + locate_tsduck chain (only
the tsp --version subprocess is stubbed), so the extract->swap->locate wiring is
exercised end-to-end, not just the status-string plumbing."""

from __future__ import annotations

import hashlib
import os
import zipfile
from pathlib import Path

import pytest

from civiccast.egress.compliance import TsduckStatus
from civiccast.installer.tsduck_install import (
    TSDUCK_VERSION,
    _download_file,
    _download_host_allowed,
    _PortableAsset,
    _safe_extract_zip,
    install_tsduck,
    windows_portable_asset,
)

_FAKE_VERSION = "tsp: TSDuck - The MPEG Transport Stream Toolkit - version 3.44-4676"


def _fake_runner(_path: str) -> str:
    return _FAKE_VERSION


def _make_tsp_zip(path: Path) -> None:
    """A minimal portable-zip with the real TSDuck/bin/tsp.exe layout."""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("TSDuck/bin/tsp.exe", "fake-tsp-binary")
        archive.writestr("TSDuck/bin/tsduck.dll", "fake-dll")


@pytest.fixture
def tsduck_home(tmp_path: Path, monkeypatch) -> Path:  # type: ignore[no-untyped-def]
    """Isolate the managed install dir + clear BYO/PATH so discovery is deterministic."""
    home = tmp_path / "tsduck-home"
    monkeypatch.setenv("CIVICCAST_TSDUCK_HOME", str(home))
    monkeypatch.delenv("CIVICCAST_TSDUCK_PATH", raising=False)
    monkeypatch.setenv("PATH", "")
    return home


# ---------------------------------------------------------------------------
# Asset resolution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("machine", "expect"),
    [
        ("AMD64", "Win64"),
        ("x86_64", "Win64"),
        ("x64", "Win64"),
        ("ARM64", "Arm64"),
        ("aarch64", "Arm64"),
    ],
)
def test_windows_portable_asset_resolves_arch(machine: str, expect: str) -> None:
    asset = windows_portable_asset(machine)
    assert asset is not None
    assert expect in asset.name
    assert asset.url.startswith("https://github.com/tsduck/tsduck/releases/download/")


def test_windows_portable_asset_unknown_arch_is_none() -> None:
    assert windows_portable_asset("mips") is None


# ---------------------------------------------------------------------------
# Platform gating
# ---------------------------------------------------------------------------


def test_non_windows_is_operator_assisted_and_never_downloads(tsduck_home: Path) -> None:
    def boom(url: str, dest: Path) -> None:  # pragma: no cover - must not run
        raise AssertionError("must not download on a non-Windows platform")

    linux = install_tsduck(system="Linux", machine="x86_64", force=True, downloader=boom)
    assert linux.status == "operator-assisted"
    assert "apt" in linux.message or "dnf" in linux.message

    mac = install_tsduck(system="Darwin", machine="arm64", force=True, downloader=boom)
    assert mac.status == "operator-assisted"
    assert "brew" in mac.message


def test_windows_unknown_arch_is_unsupported(tsduck_home: Path) -> None:
    report = install_tsduck(system="Windows", machine="mips", force=True)
    assert report.status == "unsupported"


# ---------------------------------------------------------------------------
# Real extract -> swap -> locate chain (only the version subprocess is stubbed)
# ---------------------------------------------------------------------------


def test_real_extract_swap_locate_installs(tsduck_home: Path, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Pin the SHA-256 to the zip we will serve, BEFORE install resolves the asset.
    zip_src = tmp_path / "portable.zip"
    _make_tsp_zip(zip_src)
    digest = hashlib.sha256(zip_src.read_bytes()).hexdigest()
    monkeypatch.setattr(
        "civiccast.installer.tsduck_install._WINDOWS_PORTABLE",
        {"amd64": _PortableAsset(name="TSDuck-test-Portable.zip", sha256=digest)},
    )

    def fake_download(url: str, dest: Path) -> None:
        dest.write_bytes(zip_src.read_bytes())

    # Real _safe_extract_zip + real locate_tsduck (only the tsp subprocess stubbed).
    report = install_tsduck(
        system="Windows",
        machine="AMD64",
        force=True,
        downloader=fake_download,
        version_runner=_fake_runner,
    )
    assert report.status == "installed", report.message
    assert report.tsp_path is not None
    assert str(tsduck_home) in report.tsp_path
    assert (tsduck_home / "TSDuck" / "bin" / "tsp.exe").is_file()
    assert "3.44-4676" in (report.version or "")


def test_reinstall_on_disk_is_idempotent(tsduck_home: Path) -> None:
    # Pre-populate a managed install on disk.
    bin_dir = tsduck_home / "TSDuck" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "tsp.exe").write_text("x")

    def boom(url: str, dest: Path) -> None:  # pragma: no cover - must not run
        raise AssertionError("already installed -> must not re-download")

    report = install_tsduck(
        system="Windows",
        machine="AMD64",
        downloader=boom,
        version_runner=_fake_runner,
    )
    assert report.status == "already-installed"
    assert "3.44-4676" in (report.version or "")


def test_force_clears_stale_files_so_only_new_version_remains(
    tsduck_home: Path, tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    # A stale OLD install is present (different layout) — a forced re-install must
    # not let it survive and shadow the freshly verified copy.
    stale = tsduck_home / "OldTSDuck" / "bin"
    stale.mkdir(parents=True)
    (stale / "tsp.exe").write_text("STALE")

    zip_src = tmp_path / "portable.zip"
    _make_tsp_zip(zip_src)
    monkeypatch.setattr(
        "civiccast.installer.tsduck_install._WINDOWS_PORTABLE",
        {
            "amd64": _PortableAsset(
                name="x.zip", sha256=hashlib.sha256(zip_src.read_bytes()).hexdigest()
            )
        },
    )

    report = install_tsduck(
        system="Windows",
        machine="AMD64",
        force=True,
        downloader=lambda url, dest: dest.write_bytes(zip_src.read_bytes()),
        version_runner=_fake_runner,
    )
    assert report.status == "installed", report.message
    # The stale tree is gone; only the freshly extracted layout remains.
    assert not (tsduck_home / "OldTSDuck").exists()
    assert (tsduck_home / "TSDuck" / "bin" / "tsp.exe").read_text() == "fake-tsp-binary"


def test_failed_install_preserves_previous_good_install(tsduck_home: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # A working install already exists.
    good = tsduck_home / "TSDuck" / "bin"
    good.mkdir(parents=True)
    (good / "tsp.exe").write_text("GOOD")
    monkeypatch.setattr(
        "civiccast.installer.tsduck_install._WINDOWS_PORTABLE",
        {"amd64": _PortableAsset(name="x.zip", sha256=hashlib.sha256(b"z").hexdigest())},
    )

    def fake_download(url: str, dest: Path) -> None:
        dest.write_bytes(b"z")

    def explode_extract(zip_path: Path, dest: Path) -> None:
        raise OSError("disk full mid-extract")

    report = install_tsduck(
        system="Windows",
        machine="AMD64",
        force=True,
        downloader=fake_download,
        extractor=explode_extract,
        version_runner=_fake_runner,
    )
    assert report.status == "failed"
    # The previously-good install is untouched (stage failure never swapped).
    assert (tsduck_home / "TSDuck" / "bin" / "tsp.exe").read_text() == "GOOD"
    # No staging litter left behind.
    assert not list(tsduck_home.parent.glob(f"{tsduck_home.name}.staging-*"))


# ---------------------------------------------------------------------------
# Fail-closed paths
# ---------------------------------------------------------------------------


def test_integrity_mismatch_fails_closed(tsduck_home: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "civiccast.installer.tsduck_install._WINDOWS_PORTABLE",
        {"amd64": _PortableAsset(name="x.zip", sha256="00" * 32)},
    )

    def must_not_extract(zip_path: Path, dest: Path) -> None:  # pragma: no cover
        raise AssertionError("must not extract an asset that failed its checksum")

    report = install_tsduck(
        system="Windows",
        machine="AMD64",
        force=True,
        downloader=lambda url, dest: dest.write_bytes(b"tampered"),
        extractor=must_not_extract,
        version_runner=_fake_runner,
    )
    assert report.status == "failed"
    assert "integrity" in report.message


def test_download_failure_is_reported(tsduck_home: Path) -> None:
    def fake_download(url: str, dest: Path) -> None:
        raise OSError("network down")

    report = install_tsduck(
        system="Windows",
        machine="AMD64",
        force=True,
        downloader=fake_download,
        version_runner=_fake_runner,
    )
    assert report.status == "failed"
    assert "network down" in report.message


def test_extract_without_tsp_fails(tsduck_home: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    payload = b"zip"
    monkeypatch.setattr(
        "civiccast.installer.tsduck_install._WINDOWS_PORTABLE",
        {"amd64": _PortableAsset(name="x.zip", sha256=hashlib.sha256(payload).hexdigest())},
    )
    report = install_tsduck(
        system="Windows",
        machine="AMD64",
        force=True,
        downloader=lambda url, dest: dest.write_bytes(payload),
        extractor=lambda zip_path, dest: dest.mkdir(parents=True),  # empty staging
        version_runner=_fake_runner,
    )
    assert report.status == "failed"
    assert "did not contain a 'tsp'" in report.message


def test_unpacked_tsp_that_cannot_run_fails(tsduck_home: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    payload = b"zip"
    monkeypatch.setattr(
        "civiccast.installer.tsduck_install._WINDOWS_PORTABLE",
        {"amd64": _PortableAsset(name="x.zip", sha256=hashlib.sha256(payload).hexdigest())},
    )

    def stage_a_broken_tsp(zip_path: Path, dest: Path) -> None:
        (dest / "TSDuck" / "bin").mkdir(parents=True)
        (dest / "TSDuck" / "bin" / "tsp.exe").write_text("broken")

    report = install_tsduck(
        system="Windows",
        machine="AMD64",
        force=True,
        downloader=lambda url, dest: dest.write_bytes(payload),
        extractor=stage_a_broken_tsp,
        version_runner=lambda _p: "",  # tsp cannot report a version -> not runnable
    )
    assert report.status == "failed"
    assert "did not report a version" in report.message
    # The broken staging never swapped into place.
    assert not (tsduck_home / "TSDuck").exists()


# ---------------------------------------------------------------------------
# zip-slip guard (Windows-specific traversal vectors)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "member",
    [
        "../escape.txt",
        "..\\escape.txt",
        "foo/../../escape.txt",
        "C:/Windows/evil.dll",
        "/abs/escape.txt",
    ],
)
def test_safe_extract_rejects_zip_slip(tmp_path: Path, member: str) -> None:
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as archive:
        archive.writestr(member, "pwned")
    with pytest.raises(ValueError, match="outside target dir"):
        _safe_extract_zip(evil, tmp_path / "dest")


def test_safe_extract_allows_normal_members(tmp_path: Path) -> None:
    good = tmp_path / "good.zip"
    with zipfile.ZipFile(good, "w") as archive:
        archive.writestr("TSDuck/bin/tsp.exe", "x")
    dest = tmp_path / "dest"
    dest.mkdir()
    _safe_extract_zip(good, dest)
    assert (dest / "TSDuck" / "bin" / "tsp.exe").is_file()


# ---------------------------------------------------------------------------
# Download host allow-list (initial URL + redirects)
# ---------------------------------------------------------------------------


def test_download_file_rejects_non_github_url(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unexpected URL"):
        _download_file("https://evil.example/tsduck.zip", tmp_path / "x.zip")


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://github.com/tsduck/tsduck/releases/download/v1/a.zip", True),
        ("https://objects.githubusercontent.com/abc", True),
        ("https://release-assets.githubusercontent.com/abc", True),
        ("http://github.com/x", False),  # not https
        ("https://evil.example/x", False),  # wrong host
        ("https://github.com.evil.example/x", False),  # lookalike
    ],
)
def test_download_host_allowlist(url: str, allowed: bool) -> None:
    assert _download_host_allowed(url) is allowed


# ---------------------------------------------------------------------------
# Already-installed short-circuit via injected locator
# ---------------------------------------------------------------------------


def test_already_installed_short_circuits_via_locator() -> None:
    def boom(url: str, dest: Path) -> None:  # pragma: no cover - must not run
        raise AssertionError("already installed -> must not re-download")

    report = install_tsduck(
        system="Windows",
        machine="AMD64",
        downloader=boom,
        locator=lambda: TsduckStatus(installed=True, path="X/tsp.exe", version="3.44-4676"),
    )
    assert report.status == "already-installed"
    assert report.version == "3.44-4676"


# ---------------------------------------------------------------------------
# Network-gated: the pinned SHA-256 still matches the live release asset.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("CIVICCAST_TSDUCK_NETWORK_TESTS") != "1",
    reason="network-gated; set CIVICCAST_TSDUCK_NETWORK_TESTS=1 to verify pins against the live release",
)
@pytest.mark.parametrize("arch", ["amd64", "arm64"])
def test_pinned_sha_matches_release(tmp_path: Path, arch: str) -> None:
    from civiccast.installer.tsduck_install import _WINDOWS_PORTABLE, _sha256_file

    asset = _WINDOWS_PORTABLE[arch]
    dest = tmp_path / asset.name
    _download_file(asset.url, dest)
    assert _sha256_file(dest).lower() == asset.sha256.lower(), (
        f"Pinned SHA-256 for {asset.name} ({TSDUCK_VERSION}) no longer matches the live asset"
    )
