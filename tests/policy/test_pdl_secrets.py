# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Credential handling checks for the parallel artifact downloader."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
PDL_PATH = ROOT / "ops" / "beta10-oversight" / "bin" / "release" / "pdl.py"


def _load_pdl() -> ModuleType:
    spec = importlib.util.spec_from_file_location("pdl_under_test", PDL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_github_token_stays_out_of_argv_and_signed_download_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdl = _load_pdl()
    secret = 'ghp_secret"\\value'
    captured: dict[str, object] = {}

    monkeypatch.setattr(pdl, "executable", lambda name: f"mock-{name}")
    monkeypatch.setattr(
        pdl.subprocess,
        "check_output",
        lambda *args, **kwargs: f"{secret}\n",
    )

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["args"] = args
        captured.update(kwargs)
        return subprocess.CompletedProcess(args, 0, "https://objects.example.test/signed", "")

    monkeypatch.setattr(pdl.subprocess, "run", fake_run)

    url = pdl.fresh_url("123456")

    args = captured["args"]
    assert isinstance(args, list)
    assert secret not in " ".join(args)
    assert (
        args[-1]
        == "https://api.github.com/repos/scottconverse/civiccast-native/actions/artifacts/123456/zip"
    )
    assert args[args.index("--config") + 1] == "-"
    assert captured["shell"] is False
    assert "--fail" in args
    assert "--proto" in args and "=https" in args
    assert "--proto-redir" in args
    curl_config = captured["input"]
    assert isinstance(curl_config, str)
    assert "Authorization: Bearer" in curl_config
    assert "Accept: application/vnd.github+json" in curl_config
    assert 'secret\\"\\\\value' in curl_config

    request = pdl.artifact_range_request(url, 0, 127)
    assert request.get_header("Range") == "bytes=0-127"
    assert request.get_header("Authorization") is None
    with pytest.raises(ValueError, match="HTTPS"):
        pdl.artifact_range_request("http://objects.example.test/signed", 0, 127)


def test_curl_config_refuses_token_control_characters_before_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdl = _load_pdl()
    called = False

    monkeypatch.setattr(pdl, "executable", lambda name: f"mock-{name}")
    monkeypatch.setattr(
        pdl.subprocess, "check_output", lambda *args, **kwargs: "token\r\nInjected: yes"
    )

    def unexpected_run(*args: object, **kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(pdl.subprocess, "run", unexpected_run)

    with pytest.raises(ValueError, match="control character"):
        pdl.fresh_url("123456")
    assert called is False


def test_invalid_artifact_redirect_does_not_truncate_existing_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pdl = _load_pdl()
    output = tmp_path / "artifact.zip"
    output.write_bytes(b"preserve until redirect validation")
    monkeypatch.setattr(pdl, "fresh_url", lambda artifact_id: "http://example.test/not-https")

    with pytest.raises(ValueError, match="HTTPS"):
        pdl.main(["unused", str(output), "1024", "123456"])

    assert output.read_bytes() == b"preserve until redirect validation"
