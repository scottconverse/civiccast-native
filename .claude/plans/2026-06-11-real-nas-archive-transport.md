# Real Local-NAS Archive Transport With Checksum Verify (issue #112, NAS half) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans.

**Goal:** Replace the mock-only local-NAS archive path with a real, config-gated transport: two genuinely distinct verified copies written to the station's mounted NAS directory (local mount or UNC — covers SMB/NFS via OS mounts, the honest Windows-first transport), each independently sha256 read-back verified. Cable (manual-vs-automated headend) stays a product decision for Scott — **no cable code here**.

**Verified current state:** `MockLocalNasArchiveClient` (civiccast/archive/models.py:54) invents `/nas/...` rsync and `zfs://...` proofs from a hash of the payload — no I/O. Publish service (civiccast/publish/service.py:408) unpacks `rsync, zfs = nas.archive(...)` for surfaces `local-nas-rsync`/`local-nas-zfs` with **no try/except** (mock never raises). A real write/hash/delete NAS probe already exists in first-run verification (`_local_nas_check`, installer/service.py:3820) keyed on `CIVICCAST_NAS_ARCHIVE_PATH` — the real adapter reuses that env var.

**Design decisions (REVISED during implementation):**
- Surface ids AND labels `local-nas-rsync` / `local-nas-zfs` are **kept untouched** — implementation reading showed rsync/ZFS is a real v1.1 product contract, not mock fiction (release-proof gates check for the `rsync`/`zfs` binaries in `publish/providers.py`, and a Scott-approved ZFS-deferral ledger mechanism exists). The surfaces' semantics are "verified copy" and "snapshot-grade protection"; the real adapter fulfills them with a verified direct copy and a write-once dated snapshot copy — the legitimate transport on Windows/UNC mounts where rsync/ZFS don't exist (the ZFS-deferral posture already covers that honestly).
- `ArchiveProof.target_type` Literal gains `"local_nas_copy"` and `"local_nas_snapshot_copy"`, used by the REAL adapter only. The mock keeps its existing deterministic shape (documented fiction) — zero churn in mock-consuming tests.
- Real adapter `LocalNasArchiveClient` (new `civiccast/archive/local_nas.py`): `LocalNasSettings.from_env()` requires `CIVICCAST_NAS_ARCHIVE_PATH` (fail-fast, exact name, directory must exist) — registered as `real` under `PROVIDER_KIND_LOCAL_NAS`.
  - `archive(*, asset_id, payload) -> tuple[ArchiveProof, ArchiveProof]` — writes `archive/{asset_id}.bin` + `snapshots/{asset_id}/{YYYYMMDDTHHMMSSZ}.bin`.
  - `archive_path(*, asset_id, path) -> tuple[ArchiveProof, ArchiveProof]` — streams the real media file (`archive/{asset_id}{suffix}` + dated snapshot), 1 MiB chunks, no full read into memory.
  - Every copy: write → flush+fsync → independent read-back sha256 → mismatch raises `LocalNasVerificationError` (no proof minted on failure). Hash format matches existing `sha256:<hex>` pattern; payload-mode digest matches the mock's `asset_id\0payload` convention? NO — real copies hash the actual stored bytes (honest); document the difference.
- Publish service: NAS branch gains try/except → `_provider_failure` (parity with IA/YouTube), and full-media support: `media_path is not None and hasattr(nas, "archive_path")` → real file archived.
- One `archive()` call per publish run, not per surface: keep the existing single-call/unpack shape (call once before the loop or memoize) so the snapshot copy isn't written twice when both surfaces are approved. Simplest: compute lazily once inside the loop via a small closure/cache.

**Branch:** `work/nas-real-transport` from `main`.

### Task 1 (TDD): `LocalNasArchiveClient` + registry
- Tests in new `tests/platform/test_local_nas_real.py` (mirror test_real_providers.py style): payload-mode writes both real files with verified hashes + proof paths point at the real files; path-mode streams a tmp media file; corrupted-write detection (monkeypatch read-back to differ → raises, no proof); `from_env` fail-fast on missing/non-directory path; registry `real` resolves / mock stays default; settings repr-redaction not needed (no secrets) but path is not a secret — skip.
- Implement `civiccast/archive/local_nas.py` + register `_real_local_nas` in platform/providers.py + extend `ArchiveProof` Literal + update `MockLocalNasArchiveClient` to the honest target_types/paths (`/nas/civiccast/archive/{asset_id}.bin` + `snapshot path`), update its docstring.
- Update mock-consuming tests that assert `local_nas_rsync`/`local_nas_zfs` target_types or mock paths (grep: tests/publish/test_router.py, test_soak.py, test_external_provider_proof.py, test_real_provider_surfaces.py, tests/platform/test_provider_registry.py, tests/installer/test_v12_first_run_verification.py — fix only what asserts the old fiction).
- Commit.

### Task 2 (TDD): publish service honest surfaces + failure handling + full media
- Tests in tests/publish/test_real_provider_surfaces.py (existing file): real NAS adapter selected via registry override → approving both NAS surfaces writes real files (tmp dir) and surface paths/hashes match the on-disk files; adapter raising → surfaces marked failed/retryable (`_provider_failure`), other surfaces unaffected; media_path set → real media file archived (not the verification payload).
- Implement: build_initial_surfaces label/message honesty; NAS branch try/except + archive_path support + single-call cache.
- Commit.

### Task 3: docs truth + gates + PR
- CAPABILITIES.md NAS row: `mock only` → `real component` -> `production-wired` (config-gated `CIVICCAST_PROVIDER_LOCAL_NAS=real` + `CIVICCAST_NAS_ARCHIVE_PATH`; copy+snapshot verified to a mounted directory; rsync/SMB/NFS daemons NOT implemented — OS mount is the transport; not field-proven on a real NAS appliance). cdn-and-providers.md registry table row. Note cable remains decision-gated (#112 stays open or closes per scope — the issue bundles YouTube/IA/NAS/cable; YouTube+IA shipped B5, NAS ships here, cable needs Scott's decision → comment on the issue, leave open ONLY for the cable decision, or close and open a cable-decision issue. DECISION: close #112 with a new `cable transfer: manual vs automated` decision issue so the tracker stays truthful.)
- Full gate `pytest -q` (Postgres + ffmpeg). PR `closes #112` + new cable decision issue. Merge.
