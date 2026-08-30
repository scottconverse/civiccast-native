# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""The contributor-upload byte accountant must be race-safe and self-healing.

Two GauntletGate rc18 re-gate findings, one accountant:

- Directory-ceiling TOCTOU (PE-2/TE-1). The aggregate directory ceiling was a plain
  unlocked read-then-act (`_upload_dir_bytes(dir) >= ceiling`), the exact race class
  QA-2 fixed for the per-IP budget but left on the directory ceiling. Concurrent
  uploads each pass the check before any of them writes, so the directory overshoots.

- Reap worker never released the per-IP budget (TE-3). The per-IP byte budget is an
  in-memory counter with no idea which file belonged to which IP, so when the reaper
  deleted a stale upload the uploader's consumed budget was never returned -- a reaped
  IP was locked out until the process restarted.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


class _SlowReadDict(dict[str, int]):
    """A dict that sleeps AFTER reading, to widen the check->write window.

    Same technique as test_router.py::_SlowReadDict and for the same reason: an
    adversarial review showed that widening only the directory SCAN does not
    reach the real race -- the in-flight counter's read-modify-write is a few
    bytecodes that complete before the GIL switch-interval elapses, so a
    scan-widening test passed even with the lock removed (false confidence). The
    directory in-flight counter lives in ``_totals`` under a sentinel key, so
    instrumenting the dict widens the window at the ACTUAL mutation point. WITH
    the lock the sleep happens while it is held and threads serialise; WITHOUT it
    every thread reads the same stale in-flight total and the ceiling is blown --
    verified by hand that removing self._lock in reserve_dir_slot makes this red.
    """

    def get(self, key: str, default: int = 0) -> int:  # type: ignore[override]
        value = super().get(key, default)
        time.sleep(0.01)
        return value


def test_dir_slot_reservation_is_atomic_under_concurrency(tmp_path: Path) -> None:
    """PE-2/TE-1: concurrent admissions cannot overshoot the directory ceiling."""
    from civiccast.contribute import router

    empty_dir = tmp_path / "uploads"
    empty_dir.mkdir()
    budget = router.ContributorUploadByteBudget()
    budget._totals = _SlowReadDict()  # widen the check->write on the in-flight counter
    ceiling = 100 * 1024
    max_bytes = 30 * 1024  # worst-case reservation per in-flight upload
    workers = 16
    barrier = threading.Barrier(workers)

    def reserve_once(_: int) -> bool:
        barrier.wait()
        return budget.reserve_dir_slot(empty_dir, ceiling, max_bytes)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(reserve_once, range(workers)))

    admitted = sum(1 for ok in results if ok)
    # Each admitted upload reserved its worst case up front, so peak on-disk
    # bytes cannot exceed the ceiling. Unlocked, all 16 pass and blow past it.
    assert admitted * max_bytes <= ceiling, (
        f"{admitted} concurrent uploads were admitted against a {ceiling}-byte "
        f"directory ceiling (worst-case {admitted * max_bytes} bytes) -- the "
        "directory-slot reservation is not atomic"
    )


def test_dir_slot_release_returns_the_reservation(tmp_path: Path) -> None:
    """A completed/aborted upload must return its reserved slot, or the ceiling
    would ratchet down permanently as uploads come and go."""
    from civiccast.contribute import router

    empty_dir = tmp_path / "uploads"
    empty_dir.mkdir()
    budget = router.ContributorUploadByteBudget()
    ceiling = 100 * 1024
    max_bytes = 60 * 1024

    assert budget.reserve_dir_slot(empty_dir, ceiling, max_bytes) is True
    # A second in-flight reservation would overshoot (60 + 60 > 100), refused.
    assert budget.reserve_dir_slot(empty_dir, ceiling, max_bytes) is False
    budget.release_dir_slot(max_bytes)
    # After release the slot is free again.
    assert budget.reserve_dir_slot(empty_dir, ceiling, max_bytes) is True


def test_release_path_returns_the_per_ip_budget() -> None:
    """TE-3: releasing a committed upload's path returns that IP's bytes.

    The reaper knows only the path it deleted, so the accountant must map
    path -> (ip, bytes) and credit the right IP on release.
    """
    from civiccast.contribute import router

    budget = router.ContributorUploadByteBudget()
    ip = "203.0.113.7"
    per_ip_ceiling = 10 * 1024
    path = str(Path("/tmp/uploads/clip.mov").resolve())

    assert budget.try_reserve(ip, 8 * 1024, per_ip_ceiling) is True
    budget.record_committed(path, ip, 8 * 1024)
    assert budget.total(ip) == 8 * 1024

    budget.release_path(path)
    assert budget.total(ip) == 0, "reaping the file did not return the IP's budget"
    # Idempotent: releasing an unknown/already-released path is a no-op.
    budget.release_path(path)
    assert budget.total(ip) == 0


def test_reaper_frees_the_uploaders_budget(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """TE-3 end to end: after the reaper deletes a stale unreferenced upload,
    the address that uploaded it can upload again within the same process."""
    from civiccast.contribute import router, store

    upload_dir = tmp_path / "contributor-uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    budget = router.ContributorUploadByteBudget()

    # Simulate an upload from one IP that consumes most of its per-IP budget,
    # committed to a real file on disk, and never attached to a submission.
    ip = "198.51.100.9"
    stale_file = upload_dir / "abandoned.mov"
    stale_file.write_bytes(b"x" * (9 * 1024))
    resolved = str(stale_file.resolve())
    assert budget.try_reserve(ip, 9 * 1024, 10 * 1024) is True
    budget.record_committed(resolved, ip, 9 * 1024)
    assert budget.total(ip) == 9 * 1024

    # Make the file old enough to reap and run one reaper sweep wired to the budget.
    old = time.time() - (72 * 3600)
    import os

    os.utime(stale_file, (old, old))
    empty_store = store.ContributorSubmissionStore(None)  # references nothing
    deleted = store.reap_unreferenced_contributor_uploads(
        empty_store, upload_dir=upload_dir, byte_budget=budget, now=time.time()
    )

    assert stale_file in deleted or str(stale_file) in {str(p) for p in deleted}
    assert not stale_file.exists()
    assert budget.total(ip) == 0, (
        "the reaper deleted the file but never returned the uploader's per-IP "
        "budget -- the address stays locked out until restart (TE-3)"
    )


def test_413_shows_a_human_readable_size_not_raw_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """UX-REGATE-2: the oversized-upload message is read by a public contributor,
    so it must say '2 GB', not a raw 10-digit byte count."""
    from fastapi.testclient import TestClient

    from civiccast.app import create_app

    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    monkeypatch.setenv("CIVICCAST_CONTRIBUTOR_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("CIVICCAST_CONTRIBUTOR_MAX_UPLOAD_BYTES", str(64 * 1024))
    client = TestClient(create_app())

    response = client.post(
        "/api/public/contribute/uploads",
        files={"file": ("huge.mov", b"x" * (64 * 1024 + 1024), "video/quicktime")},
    )

    assert response.status_code == 413, response.text
    detail = response.json()["detail"]
    assert "64 KB" in detail or "64 KiB" in detail, (
        f"the 413 detail should name a human-readable size, got: {detail!r}"
    )
    assert "65536" not in detail, "the 413 detail still exposes a raw byte count"


def test_close_failure_does_not_strand_the_reservations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An OSError from file.file.close() -- a real disk-pressure failure, exactly
    what this ceiling guards against -- must not skip the reservation releases in
    the finally. If close() ran before the releases, both the directory slot and
    the per-IP bytes leaked permanently, shrinking the ceiling toward zero."""
    import io

    from civiccast.auth.rate_limit import AuthRateLimiter
    from civiccast.contribute import router

    monkeypatch.setenv("CIVICCAST_CONTRIBUTOR_UPLOAD_DIR", str(tmp_path))
    budget = router.ContributorUploadByteBudget()

    class _FailingClose:
        def __init__(self, data: bytes) -> None:
            self._buf = io.BytesIO(data)

        def read(self, size: int = -1) -> bytes:
            return self._buf.read(size)

        def close(self) -> None:
            raise OSError(28, "No space left on device")

    class _Upload:
        filename = "clip.mov"
        content_type = "video/quicktime"

        def __init__(self, data: bytes) -> None:
            self.file = _FailingClose(data)

    state = type("S", (), {})()
    state.contributor_upload_byte_budget = budget
    state.auth_rate_limiter = AuthRateLimiter()
    app = type("A", (), {})()
    app.state = state
    request = type("R", (), {})()
    request.app = app
    request.client = type("C", (), {"host": "203.0.113.5"})()
    request.headers = {}

    data = b"real-media-bytes"
    result = router.upload_contributor_media(request, _Upload(data))  # type: ignore[arg-type]

    # close() failed but was suppressed, so the upload still succeeds...
    assert result.size_bytes == len(data)
    # ...and, crucially, the directory slot was released BEFORE the failing close.
    assert budget._totals.get(router.ContributorUploadByteBudget._DIR_SLOT_KEY, 0) == 0, (
        "directory slot leaked after file.file.close() raised"
    )
    # The per-IP bytes are legitimately retained (committed, recoverable by the
    # reaper via release_path), not leaked.
    assert budget.total("203.0.113.5") == len(data)


def test_reservation_is_released_when_path_allocation_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A transient filesystem error from _unique_upload_path happens AFTER the
    directory slot is reserved. It must be released, not stranded -- the call is
    inside the try/finally for exactly this reason."""
    from fastapi.testclient import TestClient

    from civiccast.app import create_app
    from civiccast.contribute import router

    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    monkeypatch.setenv("CIVICCAST_CONTRIBUTOR_UPLOAD_DIR", str(tmp_path))
    client = TestClient(create_app())
    budget = client.app.state.contributor_upload_byte_budget  # type: ignore[attr-defined]

    def boom(_upload_dir: Path, _filename: str) -> Path:
        raise OSError("transient filesystem error")

    monkeypatch.setattr(router, "_unique_upload_path", boom)
    response = client.post(
        "/api/public/contribute/uploads",
        files={"file": ("clip.mov", b"real-media-bytes", "video/quicktime")},
    )

    assert response.status_code == 503, response.text
    assert budget._totals.get(router.ContributorUploadByteBudget._DIR_SLOT_KEY, 0) == 0, (
        "the directory slot leaked when _unique_upload_path raised before the stream loop"
    )


def test_each_app_gets_its_own_upload_byte_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """The upload byte budget must be a fresh per-app instance -- created
    unconditionally, not only in the DATABASE_URL-gated durable-store wiring --
    or an ephemeral-mode app falls back to a process-wide module singleton and
    one caller's consumed budget wrongly refuses the next caller's upload."""
    from civiccast.app import create_app
    from civiccast.contribute.router import ContributorUploadByteBudget

    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    app1 = create_app()
    app2 = create_app()

    budget1 = getattr(app1.state, "contributor_upload_byte_budget", None)
    budget2 = getattr(app2.state, "contributor_upload_byte_budget", None)

    assert isinstance(budget1, ContributorUploadByteBudget)
    assert isinstance(budget2, ContributorUploadByteBudget)
    assert budget1 is not budget2, (
        "two apps share one budget; one app's uploads leak into another's"
    )


def test_bookkeeping_resolve_failure_does_not_fail_a_committed_upload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """record_committed is post-commit bookkeeping for the reaper. If resolving the
    just-written path raises (a stat race / AV lock), the upload has ALREADY
    committed to disk -- it must still return 201, not be misreported as 503 by the
    handler's enclosing `except OSError`."""
    from fastapi.testclient import TestClient

    from civiccast.app import create_app

    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    monkeypatch.setenv("CIVICCAST_CONTRIBUTOR_UPLOAD_DIR", str(tmp_path))

    marker = "resolvefail.mov"
    real_resolve = Path.resolve

    def failing_resolve(self: Path, *args: object, **kwargs: object) -> Path:
        # The stored file is now an opaque uuid4 token (field evidence /
        # GauntletGate finding: the on-disk name doubles as the public
        # upload_ref and must be unguessable), so this can no longer match
        # by the contributor's original filename -- match the just-written
        # file by location instead: it is the only thing this test resolves
        # directly inside the (otherwise-empty at request time) upload dir.
        if self.parent == tmp_path and self.suffix == ".mov":
            raise OSError("simulated stat/AV-lock race on the just-written file")
        return real_resolve(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "resolve", failing_resolve)
    client = TestClient(create_app())

    response = client.post(
        "/api/public/contribute/uploads",
        files={"file": (marker, b"real-media-bytes", "video/quicktime")},
    )

    assert response.status_code == 201, response.text
    committed = list(tmp_path.glob("*.mov"))
    assert len(committed) == 1, "the upload should be committed to disk"
    assert response.json()["upload_ref"] == committed[0].name


def test_reap_worker_forwards_its_byte_budget_to_the_reap(tmp_path: Path) -> None:
    """The reap WORKER must pass the byte budget it was constructed with through to
    the reap function -- otherwise the app-wired budget is created but never
    credited, silently reintroducing TE-3."""
    import os

    from civiccast.contribute import router, store

    upload_dir = tmp_path / "contributor-uploads"
    upload_dir.mkdir()
    budget = router.ContributorUploadByteBudget()

    ip = "192.0.2.1"
    stale = upload_dir / "old.mov"
    stale.write_bytes(b"x" * 4096)
    assert budget.try_reserve(ip, 4096, 10 * 1024) is True
    budget.record_committed(str(stale.resolve()), ip, 4096)
    old = time.time() - (72 * 3600)
    os.utime(stale, (old, old))

    # store_path points at a nonexistent file -> an empty store referencing nothing.
    worker = store.ContributorUploadReapWorker(
        store_path=tmp_path / "nostore.json", upload_dir=upload_dir, byte_budget=budget
    )
    deleted = worker.tick()

    assert stale in deleted
    assert budget.total(ip) == 0, "the worker did not forward its byte budget to the reap"


def test_unwritable_upload_dir_returns_503_not_a_bare_500(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A misconfigured contributor upload directory (mkdir fails) must return the
    same actionable 503 the streaming path gives, not an unhandled 500 with no
    operator-facing detail. Gate re-run QA finding (2026-07-23)."""
    from fastapi.testclient import TestClient

    from civiccast.app import create_app

    # A plain FILE sits where the upload dir's parent should be, so mkdir raises
    # NotADirectoryError (a subclass of OSError).
    blocker = tmp_path / "occupied"
    blocker.write_text("i am a file, not a directory", encoding="utf-8")
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    monkeypatch.setenv("CIVICCAST_CONTRIBUTOR_UPLOAD_DIR", str(blocker / "uploads"))
    client = TestClient(create_app())

    response = client.post(
        "/api/public/contribute/uploads",
        files={"file": ("clip.mov", b"real-media-bytes", "video/quicktime")},
    )

    assert response.status_code == 503, response.text
    assert "storage" in response.json()["detail"].lower()
