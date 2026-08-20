# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for the online model-download provisioning surface (S13/native).

Gap #2 (caption floor packaging slice): ``download_release_models`` used to provision
ONLY the large-v3 caption tier, so the mandatory CPU-only floor tier (medium, bound by
``OWNER-DECISION-caption-adaptive-tier.md``, 2026-07-30) could never actually be
downloaded through this surface. These tests pin the new floor-tier download item
against :data:`civiccast.native.caption_tiers.CAPTION_TIER_REGISTRY` -- the external
authority also used by the caption pack builder and the pack verifier -- rather than
against a value hand-copied into this test, so a drift between the two would show up
here as a real failure, not a tautology.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import civiccast.installer.model_download as model_download
from civiccast.installer.model_download import (
    OLLAMA_REGISTRY_HOST,
    WHISPER_MODEL_REPO,
    StagedOllamaModelCheck,
    check_staged_ollama_model,
    download_release_models,
)
from civiccast.native.caption_tiers import CAPTION_TIER_REGISTRY, FLOOR_TIER_ID


def _floor_spec():
    return CAPTION_TIER_REGISTRY[FLOOR_TIER_ID].require_bound()


def test_floor_caption_tier_is_planned_alongside_large_v3() -> None:
    report = download_release_models(dry_run=True)
    by_id = {item.id: item for item in report.items}

    floor_spec = _floor_spec()
    assert floor_spec.model_directory in by_id
    floor_item = by_id[floor_spec.model_directory]
    assert floor_item.runtime == "faster-whisper"
    # Grounded against caption_tiers.py's pinned repo -- the single source of truth --
    # never a literal re-typed here.
    assert floor_item.source == floor_spec.model_repository
    assert floor_item.status == "planned"

    # large-v3 (the quality tier) is still planned too -- the floor addition must not
    # crowd it out.
    assert "faster-whisper-large-v3" in by_id
    assert by_id["faster-whisper-large-v3"].source == WHISPER_MODEL_REPO


def test_floor_caption_tier_download_uses_the_pinned_repo_and_revision(
    tmp_path: Path,
) -> None:
    """The real (non-dry-run) download path must call the floor downloader with the
    exact pinned repo/revision from caption_tiers.py -- not a hand-typed literal that
    could silently diverge from the registry the pack builder and verifier trust."""

    floor_spec = _floor_spec()
    captured: dict[str, object] = {}

    def fake_floor_downloader(cache_dir: Path | None) -> str:
        captured["cache_dir"] = cache_dir
        return str((cache_dir or tmp_path) / floor_spec.model_directory)

    report = download_release_models(
        dry_run=False,
        cache_dir=tmp_path,
        whisper_downloader=lambda _cache: "/fake/whisper",
        floor_caption_downloader=fake_floor_downloader,
        ollama_pull=lambda _model: None,
    )

    assert captured["cache_dir"] == tmp_path
    by_id = {item.id: item for item in report.items}
    floor_item = by_id[floor_spec.model_directory]
    assert floor_item.status == "ok"
    assert floor_item.source == floor_spec.model_repository
    assert floor_item.local_path == str(tmp_path / floor_spec.model_directory)
    assert report.status == "ok"


def test_default_floor_downloader_sources_repo_and_revision_from_the_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real (huggingface_hub-backed) default downloader -- not just the plan
    string -- must resolve to caption_tiers.py's pinned repo_id/revision."""

    import civiccast.installer.model_download as model_download

    floor_spec = _floor_spec()
    captured_kwargs: dict[str, object] = {}

    def fake_snapshot_download(**kwargs: object) -> str:
        captured_kwargs.update(kwargs)
        return "/fake/snapshot-dir"

    fake_hub = type("FakeHub", (), {"snapshot_download": staticmethod(fake_snapshot_download)})
    monkeypatch.setitem(__import__("sys").modules, "huggingface_hub", fake_hub)

    result = model_download._download_floor_caption_model(None)

    assert result == "/fake/snapshot-dir"
    assert captured_kwargs["repo_id"] == floor_spec.model_repository
    assert captured_kwargs["revision"] == floor_spec.model_revision


# ---------------------------------------------------------------------------
# Task #57 D1 (audit 2026-07-31): the download/verify verb manages its OWN
# ephemeral `ollama serve` with OLLAMA_MODELS in the SERVER's environment
# (the previous fix env-wrapped the pull CLIENT -- the wrong process). No
# real ollama binary, server, or network anywhere in this suite: every
# staged-path test injects ALL of `staged_ollama_server` / `ollama_pull_via`
# / `ollama_tags` (fakes), plus `ollama_models_root`; the dev path injects
# the legacy 1-arg `ollama_pull` fake.
# ---------------------------------------------------------------------------


def _write_ollama_manifest(
    models_root: Path,
    *,
    repository: str = "gemma4",
    tag: str = "12b",
    registry: str = OLLAMA_REGISTRY_HOST,
    config_digest: str = "sha256:" + "a" * 64,
    layer_digests: tuple[str, ...] = ("sha256:" + "b" * 64, "sha256:" + "c" * 64),
) -> Path:
    manifest_dir = models_root / "manifests" / registry / "library" / repository
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schemaVersion": 2,
        "config": {"digest": config_digest, "size": 1},
        "layers": [{"digest": digest, "size": 1} for digest in layer_digests],
    }
    manifest_path = manifest_dir / tag
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def _write_ollama_blob(models_root: Path, digest: str) -> Path:
    hex_digest = digest.split(":", 1)[1]
    blob_dir = models_root / "blobs"
    blob_dir.mkdir(parents=True, exist_ok=True)
    blob_path = blob_dir / f"sha256-{hex_digest}"
    blob_path.write_bytes(b"fake-blob-bytes")
    return blob_path


def test_check_staged_ollama_model_not_staged_when_no_manifest(tmp_path: Path) -> None:
    check = check_staged_ollama_model(tmp_path, repository="gemma4", tag="12b")
    assert check.status == "not_staged"


def test_check_staged_ollama_model_staged_when_manifest_and_all_blobs_present(
    tmp_path: Path,
) -> None:
    _write_ollama_manifest(tmp_path)
    for digest in ("sha256:" + "a" * 64, "sha256:" + "b" * 64, "sha256:" + "c" * 64):
        _write_ollama_blob(tmp_path, digest)

    check = check_staged_ollama_model(tmp_path, repository="gemma4", tag="12b")

    assert check.status == "staged"
    assert check.models_root == tmp_path


def test_check_staged_ollama_model_half_staged_when_a_blob_is_missing(tmp_path: Path) -> None:
    _write_ollama_manifest(tmp_path)
    # Only the config blob is present -- both layer blobs are missing.
    _write_ollama_blob(tmp_path, "sha256:" + "a" * 64)

    check = check_staged_ollama_model(tmp_path, repository="gemma4", tag="12b")

    assert check.status == "half_staged"
    assert set(check.missing_blob_digests) == {"sha256:" + "b" * 64, "sha256:" + "c" * 64}


def test_check_staged_ollama_model_not_staged_for_a_malformed_manifest(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "manifests" / OLLAMA_REGISTRY_HOST / "library" / "gemma4"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "12b").write_text("{not valid json", encoding="utf-8")

    check = check_staged_ollama_model(tmp_path, repository="gemma4", tag="12b")

    assert check.status == "not_staged"


def test_staged_ollama_model_check_is_frozen_dataclass() -> None:
    check = StagedOllamaModelCheck(status="not_staged")
    assert check.models_root is None
    assert check.missing_blob_digests == ()


ALL_OLLAMA_TAGS = ("gemma4:12b", "gemma4:e4b", "translategemma:4b")


def _pull_recording_env(calls: list[dict[str, object]]):
    def _fake_pull(model: str) -> None:
        calls.append({"model": model, "OLLAMA_MODELS": os.environ.get("OLLAMA_MODELS")})

    return _fake_pull


class FakeStagedServer:
    """A fake `staged_ollama_server` seam: records the store it was opened
    for, yields a loopback base URL on a NON-default port, and records
    orderly teardown -- no process, no socket."""

    BASE_URL = "http://127.0.0.1:59999"

    def __init__(self) -> None:
        self.opened_for: list[Path] = []
        self.closed = 0

    @contextlib.contextmanager
    def factory(self, models_root: Path):
        self.opened_for.append(models_root)
        try:
            yield self.BASE_URL
        finally:
            self.closed += 1


def _stage_full_model(staged_root: Path, *, repository: str = "gemma4", tag: str = "12b") -> None:
    _write_ollama_manifest(staged_root, repository=repository, tag=tag)
    for digest in ("sha256:" + "a" * 64, "sha256:" + "b" * 64, "sha256:" + "c" * 64):
        _write_ollama_blob(staged_root, digest)


def test_staged_model_is_a_verifying_noop_with_server_side_store_and_no_client_env(
    tmp_path: Path,
) -> None:
    """Task #57 D1: a verified fully-staged model must be verified against
    this verb's OWN ephemeral server (OLLAMA_MODELS is the SERVER's, tags
    prove serveability) -- never pulled, never via a client-side env var,
    and never through the legacy 1-arg pull."""

    staged_root = tmp_path / "models" / "ollama"
    staged_root.mkdir(parents=True)
    _stage_full_model(staged_root)

    assert "OLLAMA_MODELS" not in os.environ
    server = FakeStagedServer()
    pulled_via: list[tuple[str, str]] = []
    legacy_calls: list[dict[str, object]] = []

    report = download_release_models(
        dry_run=False,
        cache_dir=tmp_path,
        whisper_downloader=lambda _cache: "/fake/whisper",
        floor_caption_downloader=lambda _cache: "/fake/floor",
        ollama_pull=_pull_recording_env(legacy_calls),
        ollama_models_root=lambda: staged_root,
        staged_ollama_server=server.factory,
        ollama_pull_via=lambda model, base_url: pulled_via.append((model, base_url)),
        ollama_tags=lambda _base_url: frozenset(ALL_OLLAMA_TAGS),
    )

    assert "OLLAMA_MODELS" not in os.environ, "must never mutate this process's environment"
    assert server.opened_for == [staged_root]
    assert server.closed == 1, "the ephemeral server must be shut down"
    # gemma4:12b is fully staged -> NO pull of any kind for it.
    assert all(model != "gemma4:12b" for model, _ in pulled_via)
    assert not legacy_calls, "the legacy client pull must not run on the staged path"

    by_id = {item.id: item for item in report.items}
    gemma_item = by_id["gemma4-12b"]
    assert gemma_item.status == "ok"
    assert "imported=true" in gemma_item.operator_action
    assert str(staged_root) in gemma_item.operator_action
    assert "no network access" in gemma_item.operator_action


def test_all_models_staged_completes_with_zero_pulls(tmp_path: Path) -> None:
    """The whole point of #57: with every tag staged (the activation flow's
    composed models/ollama store), the verb completes as a verifying no-op
    with NO network pull at all -- air-gap safe."""

    staged_root = tmp_path / "models" / "ollama"
    staged_root.mkdir(parents=True)
    for model in ALL_OLLAMA_TAGS:
        repository, tag = model.split(":")
        _stage_full_model(staged_root, repository=repository, tag=tag)

    server = FakeStagedServer()

    def _no_pull(model: str, base_url: str) -> None:
        raise AssertionError(f"network pull attempted for {model} via {base_url}")

    report = download_release_models(
        dry_run=False,
        cache_dir=tmp_path,
        whisper_downloader=lambda _cache: "/fake/whisper",
        floor_caption_downloader=lambda _cache: "/fake/floor",
        ollama_pull=lambda model: pytest.fail(f"legacy pull ran for {model}"),
        ollama_models_root=lambda: staged_root,
        staged_ollama_server=server.factory,
        ollama_pull_via=_no_pull,
        ollama_tags=lambda _base_url: frozenset(ALL_OLLAMA_TAGS),
    )

    assert report.status == "ok"
    for model in ALL_OLLAMA_TAGS:
        item = next(i for i in report.items if i.id == model.replace(":", "-"))
        assert "imported=true" in item.operator_action
    assert server.closed == 1


def test_unstaged_models_are_pulled_through_the_ephemeral_server(tmp_path: Path) -> None:
    """An unstaged tag is network-pulled as a CLIENT of the ephemeral
    staged-store server (OLLAMA_HOST -> its non-default port), so the bytes
    land in the staged store the runtime child (D2) serves."""

    staged_root = tmp_path / "models" / "ollama"
    staged_root.mkdir(parents=True)
    _stage_full_model(staged_root)  # only gemma4:12b staged

    server = FakeStagedServer()
    pulled_via: list[tuple[str, str]] = []

    download_release_models(
        dry_run=False,
        cache_dir=tmp_path,
        whisper_downloader=lambda _cache: "/fake/whisper",
        floor_caption_downloader=lambda _cache: "/fake/floor",
        ollama_pull=lambda model: pytest.fail(f"legacy pull ran for {model}"),
        ollama_models_root=lambda: staged_root,
        staged_ollama_server=server.factory,
        ollama_pull_via=lambda model, base_url: pulled_via.append((model, base_url)),
        ollama_tags=lambda _base_url: frozenset(ALL_OLLAMA_TAGS),
    )

    assert pulled_via == [
        ("gemma4:e4b", FakeStagedServer.BASE_URL),
        ("translategemma:4b", FakeStagedServer.BASE_URL),
    ]


def test_staged_model_the_server_does_not_list_fails_loud(tmp_path: Path) -> None:
    """A fully-staged tree the ephemeral server cannot actually serve (tag
    absent from /api/tags) is a store ollama cannot read -- refuse to report
    it as provisioned."""

    staged_root = tmp_path / "models" / "ollama"
    staged_root.mkdir(parents=True)
    _stage_full_model(staged_root)

    server = FakeStagedServer()

    with pytest.raises(RuntimeError, match="gemma4:12b"):
        download_release_models(
            dry_run=False,
            cache_dir=tmp_path,
            whisper_downloader=lambda _cache: "/fake/whisper",
            floor_caption_downloader=lambda _cache: "/fake/floor",
            ollama_pull=lambda model: pytest.fail(f"legacy pull ran for {model}"),
            ollama_models_root=lambda: staged_root,
            staged_ollama_server=server.factory,
            ollama_pull_via=lambda model, base_url: None,
            ollama_tags=lambda _base_url: frozenset(),
        )

    assert server.closed == 1, "the ephemeral server must be shut down even on failure"


def test_download_release_models_dev_invocation_keeps_the_legacy_client_pull(
    tmp_path: Path,
) -> None:
    """No staged store resolvable (dev/CLI invocation): the legacy 1-arg
    pull runs for every tag, no ephemeral server is started, and the
    environment is never touched."""

    calls: list[dict[str, object]] = []
    server = FakeStagedServer()

    report = download_release_models(
        dry_run=False,
        cache_dir=tmp_path,
        whisper_downloader=lambda _cache: "/fake/whisper",
        floor_caption_downloader=lambda _cache: "/fake/floor",
        ollama_pull=_pull_recording_env(calls),
        ollama_models_root=lambda: None,
        staged_ollama_server=server.factory,
        ollama_pull_via=lambda model, base_url: pytest.fail("server-path pull ran"),
        ollama_tags=lambda _base_url: pytest.fail("server-path tags ran"),
    )

    assert [call["model"] for call in calls] == list(ALL_OLLAMA_TAGS)
    assert all(call["OLLAMA_MODELS"] is None for call in calls)
    assert not server.opened_for, "no ephemeral server on the dev path"

    by_id = {item.id: item for item in report.items}
    assert by_id["gemma4-12b"].operator_action == "runtime=ollama model=gemma4:12b pulled=true"


def test_download_release_models_reports_and_repairs_a_half_staged_tree(
    tmp_path: Path,
) -> None:
    """Task #57: a manifest with a missing blob (an interrupted/corrupt
    installer download) must be reported, not silently trusted -- and is
    repaired by a network pull routed through the ephemeral server, so the
    re-download lands in the staged store."""

    staged_root = tmp_path / "packs" / "local-ai-model" / "models"
    staged_root.mkdir(parents=True)
    _write_ollama_manifest(staged_root)
    _write_ollama_blob(staged_root, "sha256:" + "a" * 64)  # only the config blob

    server = FakeStagedServer()
    pulled_via: list[tuple[str, str]] = []

    report = download_release_models(
        dry_run=False,
        cache_dir=tmp_path,
        whisper_downloader=lambda _cache: "/fake/whisper",
        floor_caption_downloader=lambda _cache: "/fake/floor",
        ollama_pull=lambda model: pytest.fail(f"legacy pull ran for {model}"),
        ollama_models_root=lambda: staged_root,
        staged_ollama_server=server.factory,
        ollama_pull_via=lambda model, base_url: pulled_via.append((model, base_url)),
        ollama_tags=lambda _base_url: frozenset(ALL_OLLAMA_TAGS),
    )

    assert ("gemma4:12b", FakeStagedServer.BASE_URL) in pulled_via

    by_id = {item.id: item for item in report.items}
    gemma_item = by_id["gemma4-12b"]
    assert gemma_item.status == "ok"
    assert "staged_root_incomplete=true" in gemma_item.operator_action
    assert ("b" * 64) in gemma_item.operator_action
    assert ("c" * 64) in gemma_item.operator_action


# ---------------------------------------------------------------------------
# The staged-store locator (install_layout ground truth, preference order)
# ---------------------------------------------------------------------------


def _runtime_python(tmp_path: Path) -> Path:
    install_root = tmp_path / "install"
    runtime = install_root / "runtime"
    runtime.mkdir(parents=True)
    python = runtime / "python.exe"
    python.write_bytes(b"")
    return python


def test_locator_prefers_the_composed_activation_store(tmp_path: Path) -> None:
    """models\\ollama (native_activation.rs's composed store) wins over the
    acquisition pack store when both exist."""

    python = _runtime_python(tmp_path)
    install_root = python.parent.parent
    composed = install_root / "models" / "ollama"
    (composed / "manifests").mkdir(parents=True)
    pack = install_root / "packs" / "local-ai-model" / "models"
    (pack / "manifests").mkdir(parents=True)

    assert model_download._installed_ollama_models_root(python) == composed


def test_locator_falls_back_to_the_acquisition_pack_store(tmp_path: Path) -> None:
    python = _runtime_python(tmp_path)
    install_root = python.parent.parent
    pack = install_root / "packs" / "local-ai-model" / "models"
    (pack / "manifests").mkdir(parents=True)

    assert model_download._installed_ollama_models_root(python) == pack


def test_locator_returns_none_without_a_manifests_tree_or_runtime_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "program-data"))
    python = _runtime_python(tmp_path)
    # Runtime-shaped interpreter but no staged store at all.
    assert model_download._installed_ollama_models_root(python) is None
    # A store dir WITHOUT a manifests/ subtree does not count.
    (python.parent.parent / "models" / "ollama").mkdir(parents=True)
    assert model_download._installed_ollama_models_root(python) is None
    # Not the installed embedded interpreter (dev venv shape).
    dev_python = tmp_path / "venv" / "Scripts" / "python.exe"
    dev_python.parent.mkdir(parents=True)
    dev_python.write_bytes(b"")
    assert model_download._installed_ollama_models_root(dev_python) is None


# ---------------------------------------------------------------------------
# Ephemeral-serve lifecycle units (fake popen/HTTP/clock -- no real process)
# ---------------------------------------------------------------------------


class FakeServeProc:
    def __init__(self, exit_code: int | None = None) -> None:
        self._exit_code = exit_code
        self.pid = 4242
        self.terminated = 0
        self.killed = 0

    def poll(self) -> int | None:
        return self._exit_code

    def wait(self, timeout: float | None = None) -> int:
        if self._exit_code is None:
            raise subprocess.TimeoutExpired(cmd="ollama serve", timeout=timeout or 0)
        return self._exit_code

    def terminate(self) -> None:
        self.terminated += 1
        self._exit_code = 1

    def kill(self) -> None:
        self.killed += 1
        self._exit_code = 1


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, dt: float) -> None:
        self.t += dt


def test_wait_for_ollama_serve_ready_succeeds_when_version_endpoint_answers(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    answers = iter([False, False, True])

    model_download._wait_for_ollama_serve_ready(
        FakeServeProc(exit_code=None),
        "http://127.0.0.1:59999",
        stderr_path=tmp_path / "stderr.log",
        http_ok=lambda _url: next(answers),
        clock=clock.now,
        sleep=clock.sleep,
    )


def test_wait_for_ollama_serve_ready_times_out_with_stderr_tail(tmp_path: Path) -> None:
    clock = FakeClock()
    stderr = tmp_path / "stderr.log"
    stderr.write_text("bind: address already in use", encoding="utf-8")

    with pytest.raises(RuntimeError, match="did not become ready"):
        model_download._wait_for_ollama_serve_ready(
            FakeServeProc(exit_code=None),
            "http://127.0.0.1:59999",
            stderr_path=stderr,
            budget_seconds=2.0,
            http_ok=lambda _url: False,
            clock=clock.now,
            sleep=clock.sleep,
        )


def test_wait_for_ollama_serve_ready_reports_an_early_exit(tmp_path: Path) -> None:
    stderr = tmp_path / "stderr.log"
    stderr.write_text("fatal: models directory unreadable", encoding="utf-8")

    with pytest.raises(RuntimeError, match="exited before readiness"):
        model_download._wait_for_ollama_serve_ready(
            FakeServeProc(exit_code=3),
            "http://127.0.0.1:59999",
            stderr_path=stderr,
            http_ok=lambda _url: pytest.fail("must not poll after exit"),
        )


def test_stop_ollama_serve_tree_is_bounded_and_kills_a_wedged_process() -> None:
    proc = FakeServeProc(exit_code=None)

    class Wedged(FakeServeProc):
        def terminate(self) -> None:
            self.terminated += 1  # stays alive: poll() still None

        def wait(self, timeout: float | None = None) -> int:
            if self.killed:
                return 1
            raise subprocess.TimeoutExpired(cmd="ollama serve", timeout=timeout or 0)

    wedged = Wedged(exit_code=None)
    model_download._stop_ollama_serve_tree(wedged)
    if sys.platform != "win32":
        assert wedged.terminated == 1
    assert wedged.killed == 1

    # An already-exited process is a no-op.
    model_download._stop_ollama_serve_tree(FakeServeProc(exit_code=0))
    assert proc.killed == 0
