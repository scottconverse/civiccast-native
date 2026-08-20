# Flaky Auth Lifecycle Test Close-Out (issue #120) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans.

**Goal:** Close #120 honestly. Investigation finding (code+git verified 2026-06-11): the root cause WAS already fixed in commit `d60a0e6` (2026-06-09, after the issue was filed, tagged `refs #98` so #120 never closed): audit-event order flipped when `issued/used/revoked` collided on `created_at` (Windows clock quantizes ~15.6ms; Postgres has no stable scan order, SQLite masked it). The fix: time-ordered `event_id` (`new_audit_event_id()` — zero-padded microsecond timestamp + per-process monotonic sequence) and `ORDER BY created_at, event_id`. What is MISSING: nothing in the suite pins this (no `event_id` monotonicity test, and no Postgres-gated lifecycle-ordering test — the flake surface only exists on Postgres).

**This plan adds the missing pins + soak evidence; no production change expected.**

**Branch:** `work/flaky-auth-close-out` from `main`.

### Task 1: Regression pins in `tests/auth/test_staff_token_lifecycle.py`

- [ ] `test_audit_event_ids_are_strictly_increasing_under_timestamp_collisions` — generate 10_000 ids from `new_audit_event_id()` in a tight loop (guaranteed `created_at`-equivalent collisions on Windows); assert strictly increasing lexicographic order (`all(a < b for a, b in pairwise)`).
- [ ] `test_postgres_audit_order_is_deterministic_under_collisions` — Postgres-gated via `tests._postgres_harness.fresh_database_from_env` (skip when unset and no Docker, mirroring tests/live/test_real_postgres.py); `alembic upgrade head`; run issue→verify→revoke→rotate lifecycles 20 times in a tight loop; after each, assert the exact expected `event_type` sequence from `audit_events()` (the original flake's assertion, now under deliberate collision pressure).
- [ ] Reference #120 + d60a0e6 in the test docstrings (the issue's "flake-tracking notes" task).

### Task 2: Soak + gates + close

- [ ] Soak: run the lifecycle test file 25 consecutive times against the portable Postgres; record pass count.
- [ ] Full `pytest -q` gate with Postgres + ffmpeg.
- [ ] PR `closes #120` including the honest correction: the hardening already existed (d60a0e6); this PR adds the missing regression pins + soak evidence.
