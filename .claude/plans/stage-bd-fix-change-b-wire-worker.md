# Change B — Wire the Finalization Worker for Real (+ settings, runbook, docs truth)

> Part of the Stage B+D fix sprint. Findings closed: ENG-002 (Blocker), QA-001
> (Blocker), DOC-001 (Blocker), W-2; ENG-006 / DOC-003 (Critical); DOC-002,
> DOC-004 (Critical); TEST-002 (Critical); DOC-010 (Major); ENG-014 (Minor);
> ENG-016 (Nit, docstring half); DOC-005/006/007/008/011/012/013 (README pass);
> DOC-014 (Minor); QA-008 (runbook note).
> Decision basis (Scott, final): **Hybrid** — in-app background thread by default,
> `CIVICCAST_FINALIZATION_WORKER=inline|external|off`, plus
> `python -m civiccast.live.finalization_worker` external entrypoint documented in
> the runbook.

**Goal:** End-broadcast in the deployed app actually finalizes: the worker loop
runs (inline thread via app lifespan by default), is configured from the
environment (manifest base URL, settle/backoff/poll), has a runbook, and every
doc claim matches runtime truth — proven by an app-factory integration test that
fails on current HEAD.

**Architecture:** A frozen `FinalizationWorkerSettings` dataclass (env-loaded) and
a `FinalizationWorkerSupervisor` (owns thread + stop_event) live in
`finalization_worker.py`. `create_app()` gains a FastAPI lifespan; both durable
wiring sites build the supervisor from settings and register it on `app.state`.
The thread starts only when the lifespan has begun AND durable storage is active
AND mode == inline — so plain `create_app()` calls in tests never spawn threads,
while installer-prepared-storage-mid-flight (durable wiring during a request)
still starts the worker.

## Tasks

### Task B1: Failing app-factory integration test (the W-2 tripwire)

**Files:**
- Create: `tests/live/test_finalization_worker_app_wiring.py`

Test sketch (ffmpeg-gated like the existing real-media proof; resolves the worker
through the app's own wiring — no hand-built worker):

```python
@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, ...)
def test_end_broadcast_reaches_completed_via_app_wired_worker(tmp_path, monkeypatch):
    db = tmp_path / "wiring.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    monkeypatch.setenv("CIVICCAST_STAFF_TOKENS", "test-token:op-1:Op One:meeting_operator,setup_admin")
    monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")
    monkeypatch.setenv("CIVICCAST_FINALIZATION_WORKER", "inline")
    monkeypatch.setenv("CIVICCAST_FINALIZATION_SETTLE_SECONDS", "0")
    monkeypatch.setenv("CIVICCAST_FINALIZATION_POLL_SECONDS", "0.05")
    _migrate(db)                      # alembic upgrade head against the file DB
    app = create_app()
    with TestClient(app) as client:   # lifespan starts the inline worker thread
        h = {"Authorization": "Bearer test-token"}
        client.post("/api/staff/live/recording-targets", json={...file URI target...}, headers=h)
        client.post("/api/staff/live/sessions", json={...}, headers=h)
        ...start-preflight / go-on-air / end-broadcast...
        _write_real_mp4(tmp_path / "wired-session.mp4")   # ffmpeg testsrc, 1s
        deadline-poll GET /api/staff/live/finalizations until state == "completed" (≤60s, 0.1s step)
        assert GET /api/staff/live/sessions/wired-session → state == "recorded"
```

Also a second, fast, ffmpeg-free test asserting the supervisor exists, is
configured from env, and does NOT run when mode=off:

```python
def test_worker_off_mode_never_starts_thread(...)  # mode=off, with TestClient(...), supervisor.running is False
```

- Run: both fail on HEAD (no supervisor attribute / session stuck `ending`).

### Task B2: Settings + supervisor + entrypoint in `finalization_worker.py`

**Files:**
- Modify: `civiccast/live/finalization_worker.py`

Additions:

```python
_LOG = logging.getLogger(__name__)

WORKER_MODE_INLINE, WORKER_MODE_EXTERNAL, WORKER_MODE_OFF = "inline", "external", "off"

@dataclass(frozen=True)
class FinalizationWorkerSettings:
    mode: str = WORKER_MODE_INLINE
    public_manifest_base_url: str | None = None
    settle_seconds: float = 30.0          # production-honest default (ENG-006)
    max_attempts: int = 3
    backoff_seconds: float = 30.0
    poll_seconds: float = 5.0

    @classmethod
    def from_env(cls) -> "FinalizationWorkerSettings":
        # CIVICCAST_FINALIZATION_WORKER, CIVICCAST_LIVE_MANIFEST_BASE_URL,
        # CIVICCAST_FINALIZATION_{SETTLE_SECONDS,MAX_ATTEMPTS,BACKOFF_SECONDS,POLL_SECONDS}
        # invalid mode → ValueError naming the three valid values (fail fast at startup)

def build_worker(session_factory, settings) -> LiveFinalizationWorker: ...

class FinalizationWorkerSupervisor:
    """Owns the inline worker thread; start() is idempotent; stop() joins."""
    def __init__(self, session_factory, settings): ...
    def start(self) -> None: ...    # no-op unless settings.mode == inline; daemon thread "civiccast-finalization-worker"
    def stop(self, timeout: float = 10.0) -> None: ...
    @property
    def running(self) -> bool: ...

def main(argv: list[str] | None = None) -> int:
    """python -m civiccast.live.finalization_worker [--once] — external worker mode."""
    # requires DATABASE_URL; binds engine, builds session factory + settings from env,
    # --once → run_once and exit 0; else run_forever until KeyboardInterrupt.

if __name__ == "__main__":
    raise SystemExit(main())
```

`run_forever` fix (ENG-014, needed for clean lifespan shutdown):

```python
while stop_event is None or not stop_event.is_set():
    self.run_once()
    if stop_event is not None:
        stop_event.wait(poll_seconds)
    else:
        time.sleep(poll_seconds)
```

Constructor default `settle_seconds: float = 30.0` (raise from test-friendly 2.0;
all existing tests pass explicit values — verify in B5).
(The survive-and-log loop hardening is Change C scope; B keeps run_forever
behavior otherwise unchanged.)

### Task B3: App lifespan + wiring

**Files:**
- Modify: `civiccast/app.py`

- Define `_finalization_worker_lifespan(app)` (asynccontextmanager) passed to
  `FastAPI(..., lifespan=...)`: on enter set `app.state.lifespan_started = True`
  and `_maybe_start_finalization_worker(app)`; on exit
  `supervisor.stop()` if present.
- New helper used by BOTH durable wiring sites (create_app durable branch and
  `_install_durable_store_wiring`):

```python
def _wire_finalization_worker(app, session_factory) -> None:
    settings = FinalizationWorkerSettings.from_env()   # raises on bad mode (fail fast)
    app.state.finalization_worker_supervisor = FinalizationWorkerSupervisor(session_factory, settings)
    _maybe_start_finalization_worker(app)

def _maybe_start_finalization_worker(app) -> None:
    sup = getattr(app.state, "finalization_worker_supervisor", None)
    if sup is not None and getattr(app.state, "lifespan_started", False):
        sup.start()   # internally no-ops unless mode == inline
```

- Both `_resolve_live_finalization_worker` resolvers construct via
  `build_worker(_session_factory, settings)` so the read endpoints and the loop
  share configuration (ENG-006: no more all-defaults construction).

### Task B4: Docs truth — same commit

**Files:**
- `CAPABILITIES.md` line 38: keep `production-wired` but the note now describes
  reality: inline worker thread by default (`CIVICCAST_FINALIZATION_WORKER`),
  external/off modes, manifest URL honesty, **no trim claims** (ENG-004 descope).
  Line 6 baseline provenance fix (DOC-014).
- `civiccast/live/README.md` full accuracy pass (DOC-002/005/006/007/008/011/012/013):
  production-path section rewritten against the now-real wiring; trim honesty
  sentence ("no production surface writes trim onto a job; follow-up story");
  endpoint table corrected (drop the spelled-out count, add relay/ingest/public
  rows); auth posture corrected (bearer enforced); migrations tree + repo-global
  chain warning; export list pointer; drop stale test counts; de-Slice-1 framing.
- `civiccast/live/router.py` end_broadcast docstring: real contract (ENG-016).
- Create `docs/ops/finalization-worker-runbook.md`: modes (inline default,
  external `python -m civiccast.live.finalization_worker`, off), all env knobs +
  defaults, serving story for `<session>-hls` output + `CIVICCAST_LIVE_MANIFEST_BASE_URL`,
  status endpoints, what terminal `failed` means today (DB-level repair note until a
  retry surface ships), `CIVICCAST_AUTH_ACK` note (QA-008).
- Link runbook from `docs/technical-ops-reference.md`.
- Erratum appended to
  `tester-handoff/v2.0.1/test-results/windows/20260609-145417-local-stage-bd-finalization-worker.md`
  (DOC-004 Option A: dated, names the overstatements, downgrades the result).
- `CHANGELOG.md` `[Unreleased]`: Added (job table+worker+endpoints with honest
  wording, worker wiring + settings + runbook), Fixed (migration renumber 0011→0023,
  BigInteger).
- Regenerate OpenAPI artifacts (docstring changes flow into openapi.json):
  `python scripts/generate-openapi-artifacts.py`.

### Task B5: Verify

- New integration tests pass; `pytest tests/live -q` clean (worker default-settle
  change verified against the whole live suite).
- Full suite → 0 failures (cite count); ruff / format / mypy scoped to touched
  files; OpenAPI artifact check; `git diff --check`.

### Task B6: Result file + commit

- Result file `<ts>-local-change-b-wire-worker.md` (cite full-suite count;
  environment gaps: no Node for portal types, no Docker).
- Commit (signed-off): `feat(live): run the finalization worker in deployments refs #98`
