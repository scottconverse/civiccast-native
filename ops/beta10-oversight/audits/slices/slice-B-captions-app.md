# Slice B audit lite: captions, app/API layer, native supervisor

Repo: C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-release (release/beta10, HEAD 657d8438). Read-only. One small repro script was run against a temp dir (scratchpad\audit\repro_retention.py) and 21 existing caption tests were run at BelowNormal (all passed). Nothing under ProgramData / Program Files was touched.

### B-001 Critical: Anonymous contributor upload buffers the whole body to disk before any size, rate or budget check runs
**Dimension:** Runtime
**Evidence:** civiccast/contribute/router.py:450-454 `def upload_contributor_media(request, file: UploadFile = File(...))` calls `_enforce_upload_rate_limit(request)` as its first statement. FastAPI has already parsed the multipart body by then. Starlette's multipart parser (starlette/formparsers.py:181-188, 282-284) writes file parts into a SpooledTemporaryFile with no ceiling; `max_part_size` (1 MB) applies only to non-file fields. The only body-size middleware in the app is for the analytics path (civiccast/app.py:2323-2330).
**Why it matters:** The 2 GB per-file cap, 5 GB per-IP budget, 50 GB directory ceiling and hourly rate limit all fire after an anonymous caller has already streamed an arbitrary number of bytes into the system temp directory (usually C:\). An anonymous caller on `/api/public/contribute/uploads` can fill the system drive the station records to, and the limits that were written to prevent exactly this never get a chance to run.
**Fix path:** Enforce a Content-Length cap (reject over `_max_upload_bytes()` + overhead with 413) and the per-IP rate limit in an ASGI middleware or a route dependency that runs before body parsing; reject chunked bodies without Content-Length on this path or count bytes in a receive wrapper like the analytics shim. Alternatively stream the body yourself (raw `request.stream()` with a hard byte counter) instead of `UploadFile`. Confirm with a reverse-proxy `client_max_body_size` equivalent as defence in depth.
**Blast radius:** tests/contribute (upload ceiling and budget tests assume the in-handler path); `ContributorUploadByteBudget` accounting (router.py:150-300); the app.py analytics body-limit middleware is the existing pattern to copy; any portal client that sends chunked uploads.

### B-002 Critical: Webhook subscribe is unauthenticated: SSRF to any URL, forgeable HMAC secret, and self-confirm (only when the real webhook provider is enabled)
**Dimension:** Correctness
**Evidence:** civiccast/subscribe/models.py:43 `webhook_url: HttpUrl` accepts any URL incl. loopback and link-local. civiccast/subscribe/service.py:149 `webhook_secret = hashlib.sha256(f"{subscription_id}:webhook".encode()).hexdigest()`, where `subscription_id` is an unkeyed hash of channel, URL and target (service.py:41-43) and is returned in the public response (service.py:46-97). The confirmation token is echoed in the public response for webhooks (service.py:84-97, acknowledged in the comment at 67-87). civiccast/subscribe/webhook.py:69-80 `httpx.Client(...).post(url, ...)` has no destination check.
**Why it matters:** Any caller can register `http://127.0.0.1:<port>/...` or a metadata address, confirm it themselves, and make the station POST signed JSON there on every published recording. The "HMAC signature" is computable by anyone who knows the URL and target, so a webhook receiver cannot authenticate notices. Exposure is conditional: the shipped default is the in-memory mock (app.py:1245-1250, `CIVICCAST_PROVIDER_WEBHOOK=real` opt-in), so this is Critical for any station that enables real webhooks and harmless otherwise.
**Fix path:** Derive the per-subscription secret from a server-side key (HMAC with `token_secret`) or random bytes, never from public values. Resolve and block private, loopback, link-local and metadata ranges at registration and at every delivery (re-resolve at connect time, `follow_redirects=False`). Deliver the confirmation token to the webhook URL (challenge/response) instead of echoing it.
**Blast radius:** subscribe/store.py (sealed secret column keeps working but existing rows hold the weak secret and need rotation), subscribe/retry_worker.py:191-217, tests/subscribe (any test asserting the echoed token or the deterministic secret), docs for webhook receivers.

### B-003 Major: Live caption review rows and evidence WAVs never expire unless an operator resolves every cue; the whole table is reloaded every 60 s and listed unpaginated
**Dimension:** Runtime
**Evidence:** civiccast/captions/persistence.py:159 `status="pending"` for every created row, and nothing in persistence.py or review.py deletes rows. civiccast/captions/retention.py:958-962 only prunes `review-evidence` when `candidate.review_status != "pending"`. persistence.py:237-254 `list_with_audio_evidence()` selects every row, run by each retention sweep (RETENTION_SWEEP_SECONDS = 60.0, retention.py:66). civiccast/captions/router.py:153-170 `list_review_items` returns `store.list(...)` with no limit. The module docstring in test_caption_retention.py cites 1,487 evidence WAVs in 3 days.
**Why it matters:** The live tap creates a review row (and a ~320 KB evidence WAV) per committed cue on every channel, and a volunteer-run station will not review them all. Rows, evidence files and memory used by the sweep grow without bound, and the 2026-09-20 owner decision removed the volume caps (retention.py:309-316), so the only brake is a human clicking approve. The review queue API and the sweep both degrade as the table grows.
**Fix path:** Add an age-based expiry for unresolved live-tap rows and their evidence (distinct from the low-confidence protected set), keyed off `reviewer_note`/source or a new `origin` column; paginate `GET /review-items` (limit/cursor); make the sweep stream rows or query only evidence-bearing rows with a created_at cutoff.
**Blast radius:** retention.py `_discover_candidates`/`_is_eligible`, a new Alembic migration for any new column, tests/captions/test_caption_retention.py and test_review_router.py, operator console review screen paging.

### B-004 Major: Raw tap chunks that no evidence window covers are retained forever once the channel has any evidence-bearing review row (reproduced)
**Dimension:** Runtime
**Evidence:** civiccast/captions/retention.py:548 `"evidence_pending": bool(windows)` is channel-level, and retention.py:955-956 `if candidate.evidence_pending and not candidate.derived_evidence_verified: return False`. Repro (scratchpad\audit\repro_retention.py): 10 aged chunks, one evidence window covering chunks 0-1, `enforce(now=+2 days)` printed `deleted raw: ['chunk-000000.wav','chunk-000001.wav']` and left chunks 2-9 in processed/.
**Why it matters:** Evidence is only written when a cue commits, so silence, music and applause chunks are never covered. The 2026-09-17 fix (comment at retention.py:540-547) only handles a channel with zero windows, so in production every non-speech chunk of every channel is kept indefinitely (about 160 KB per 5 s, roughly 3 GB per channel per day if mostly uncovered). The existing tests inject `evidence_pending=False` directly (test_caption_retention.py:455-490) and never run discovery against a mixed channel.
**Fix path:** Make `evidence_pending` per chunk: a chunk is pending only if a cue/evidence row could still cover its window (for example a pending hypothesis or an in-flight batch for that index), otherwise eligible on the age cap. Add a discovery-level test with one covered and several uncovered chunks.
**Blast radius:** retention.py:511-550, `_Candidate`/`_normalize_candidate` (retention.py:920-935), tests/captions/test_caption_retention.py, the tap's own sweep and CaptionRetentionVerdictSource (both call enforce_discovered).

### B-005 Major: A live station's active.vtt grows for the whole session and is rewritten, fsynced and publicly served in full every segment
**Dimension:** Runtime
**Evidence:** civiccast/captions/stabilize.py:65 `_committed` and :66 `_expired_unconfirmed` are append-only lists (appends at :531, :134, :149, :266, :345, :507); `committed()` re-sorts the whole list (:385-391). tap_worker.py:1685 publishes `worker.committed_cues()` after every consumed segment, and live_sidecar.py:104-163 `_atomic_write_text` rewrites and fsyncs the whole document. civiccast/cable/router.py:105-135 serves the entire `active.vtt` publicly with `Cache-Control: no-store`. Per-channel workers live until `begin_channel_session` (tap_worker.py:1155-1165).
**Why it matters:** A 24/7 channel keeps one session for days or weeks. The sidecar is O(cues) to render, write and fsync every 5 s per channel, and every viewer poll downloads all of it, so cost grows quadratically over uptime. `expired_unconfirmed()` also copies the full list per batch (stabilize.py:440-449).
**Fix path:** Publish only a trailing window of cues (for example the last 2-5 minutes; viewers only need current captions) and keep the full history in the review store. Trim `_committed` for cues older than the overlap window (keep a small tail for `_overlaps_committed`), and prune `_expired_unconfirmed` after they are handed to review.
**Blast radius:** captions/stabilize.py, live_sidecar.py, egress/caption_feed.py and caption_proof_worker.py (both read active.vtt), tests/captions/test_captions_core.py and test_live_sidecar.py, HLS caption republish paths that expect a complete cue set.

### B-006 Major: Any local authenticated user can wedge the supervisor control pipe by connecting and not sending
**Dimension:** Runtime
**Evidence:** civiccast/native/supervisor/pipe_server.py:73 SDDL grants Authenticated Users read/write (`(A;;0x120083;;;AU)`). `PipeServer.accept_and_serve_one` (pipe_server.py:656-690) serves one connection to completion on the single accept thread (service.py:807-817), and `serve_connection` blocks in `win32file.ReadFile(handle, 4096)` (pipe_server.py:797) with no timeout or idle limit. No test covers an idle or slow client (grep of tests/native/test_supervisor_pipe_server*.py).
**Why it matters:** One unprivileged local process that opens the pipe and sleeps (or pipelines requests without reading replies until the 16 KB buffer fills) blocks status, start, stop and restart for the admin tooling until it disconnects. Playout keeps running (children are unaffected), so this is control-plane availability only, but the repo's own threat model treats other local users as real (auth/rate_limit.py docstring).
**Fix path:** Serve each connection on its own thread (or use overlapped I/O) with an idle read deadline (for example 10-30 s), a per-connection frame count limit, and a bounded WriteFile; keep `CommandQueue` serialization for the commands themselves.
**Blast radius:** pipe_server.py `serve_connection`/`accept_and_serve_one`/`close` (the run-17 shutdown logic depends on the single `_serving` lock), service.py `_ControlPipe`, tests/native/test_supervisor_pipe_server_win.py.

### B-007 Minor: An ASR exception leaves the segment in place, reports "overloaded", engages no backoff and logs a full traceback every scan
**Dimension:** Runtime
**Evidence:** tap_worker.py:1660 `worker.process_batch(...)` is not guarded inside `_process_channel`; `_isolated_process_channel` (tap_worker.py:1574-1595) logs `_LOG.exception(...)`, calls `_publish_status(state="overloaded")` and returns, leaving the file in the tap directory. Logs are a 10 MiB x 10 rotating handler with fsync per record (supervisor/service.py:222-300).
**Why it matters:** A persistent ASR fault (CUDA error, bad model) re-runs and re-logs a traceback every 2 s per channel until backlog shedding deletes the audio. At roughly 3 channels x 30 per minute that can rotate the 100 MB log window in a few hours and bury the original cause. The status says "overloaded" for what is a failure, and the pause ladder is never used.
**Fix path:** Treat a process_batch exception as a failed segment: quarantine or delete it after N attempts, rate-limit the traceback per channel (first occurrence plus periodic summary), and publish a distinct status (for example `error`) or feed the backoff ladder.
**Blast radius:** tap_worker.py:1525-1595, CaptionRuntimeState literal (live_sidecar.py:21-27) and its consumers, tests/captions/test_caption_tap_worker.py.

### B-008 Minor: Atomic sidecar write closes the file descriptor a second time on its failure path
**Dimension:** Correctness
**Evidence:** civiccast/captions/live_sidecar.py:141-166 opens with `os.fdopen(descriptor, ...)` (the `with` closes it), then the outer `except Exception:` runs `with suppress(OSError): os.close(descriptor)`.
**Why it matters:** The failure that triggers it is the documented field case (PermissionError WinError 5 on replace, docstring at :103-119). By then the descriptor number may belong to another thread's file (channel workers and the evidence writer open and close files constantly), so the stray close can break an unrelated write.
**Fix path:** Track whether fdopen took ownership (set `descriptor = None` after the `with`, close only if still open) or use `NamedTemporaryFile(delete=False)`.
**Blast radius:** live_sidecar.py only; tests/captions/test_live_sidecar.py.

### B-009 Minor: Raw audio parked in quarantine/ and collision/, and the retention audit log, are never pruned
**Dimension:** Runtime
**Evidence:** tap_worker.py:1626-1635 and :1647 move segments to `<channel>/collision` and `<channel>/quarantine`; retention.py only scans `processed/` (retention.py:511) and `*/captions/evidence/*.wav` (:495). `_append_audit_records` (retention.py:607-620) appends one JSON line per pruned file with fsync to caption-retention-audit.jsonl, which has no rotation.
**Why it matters:** A writer that emits wrong-format segments (not mono s16, empty frames) turns every 5 s segment into retained, unswept broadcast audio. The audit file gains a few thousand lines per channel per day indefinitely.
**Fix path:** Include quarantine/collision in the age sweep (or delete after logging a hash), and rotate or cap the audit JSONL.
**Blast radius:** retention.py discovery, any support tooling that reads the audit file, tests/captions/test_caption_retention.py.

### B-010 Minor: Auth rate limiter never frees keys and has an unreachable cleanup branch
**Dimension:** Runtime
**Evidence:** civiccast/auth/rate_limit.py:27-38 `allow()` only deletes a key inside `if len(hits) >= limit: if not hits: del ...`, which cannot be true; `_hits` is a `defaultdict`, so every distinct key ever seen (client IP, ip:path, `contribute-upload:<ip>`, `staff-auth-fail:<ip>`) stays as an empty deque forever.
**Why it matters:** The limiter is shared by public routes (contribute upload, status, submissions) and setup/staff auth. A caller with many source addresses (an IPv6 /64) grows process memory without bound.
**Fix path:** Delete a key when its deque is empty after pruning (in `allow` and `saturated`), or sweep stale keys periodically.
**Blast radius:** auth/rate_limit.py; tests/auth/test_rate_limit*.

### B-011 Minor: Unauthenticated live-HLS route feeds attacker-chosen channel ids into the surge monitor (state grows without bound when surge is enabled)
**Dimension:** Runtime
**Evidence:** civiccast/stream/media_router.py:318-323 calls `surge.observe(channel_id, resolve_client_ip(request))` for any `.m3u8` path before the channel is validated (`_live_dir_for_channel` runs after, :324-327). civiccast/live/surge_service.py:79-102 and live/load_monitor.py:44-48 create `_seen`, `_channel_locks` and `_last_tick` entries per channel id; pruning only happens in `concurrent()` for channels that are ticked again.
**Why it matters:** Opt-in (`CIVICCAST_LIVE_SURGE_THRESHOLD`), but when on, random `/media/live/<random>/x.m3u8` requests leak a lock, a timestamp and a viewer map per id.
**Fix path:** Call `observe` only after `_live_dir_for_channel` succeeds, or whitelist configured channel ids.
**Blast radius:** media_router.py, surge_service.py, tests/stream/test_media_router*.

### B-012 Minor: Unauthenticated /api/hardware is uncached, runs NVML init twice per call, and still returns the hostname
**Dimension:** Runtime
**Evidence:** civiccast/app.py:2454-2467 serves `public_hardware_probe()`; platform/hardware.py:130-148 calls `_probe_gpu()` twice (lines 144 and 146), each doing `nvmlInit`/`nvmlShutdown` (:230-263); `_probe_os()` (:266-275) includes `hostname`, and `public_hardware_probe` (:151-171) only strips the disk path.
**Why it matters:** Anyone who can reach the port can hammer driver calls on a station that is also running GPU captioning, and learns the machine name (same class as the W-3 account-name leak that was already fixed for the disk path).
**Fix path:** Cache the probe for a few seconds, compute GPU once, and blank `os.hostname` in the public view.
**Blast radius:** hardware.py, tests/test_hardware_probe*.py and tests/test_hardware_disclosure.py.

### B-013 Minor: ThreadSupervisor neither restarts a dead worker nor safely handles a stop timeout
**Dimension:** Runtime
**Evidence:** civiccast/platform/worker_runtime.py:50-83: one thread is created in `start()` with no watchdog; `stop()` sets `self._thread = None` even when `thread.is_alive()` after the timeout, and a later `start()` calls `self._stop_event.clear()` (line 62) on the same event the still-running old thread is waiting on.
**Why it matters:** A worker whose `run_forever` lets an exception escape dies silently until the process restarts; after a stop timeout a restart can leave two threads running the same worker. (I did not audit each worker's own exception handling.)
**Fix path:** Log and restart on thread death with backoff (or surface `running` in /health), and use a fresh Event per start.
**Blast radius:** worker_runtime.py and every `ThreadSupervisor` user in app.py:830-900.

### B-014 Minor: Plaintext initdb password file is written before its ACL is restricted and outside the cleanup try
**Dimension:** Runtime
**Evidence:** civiccast/native/provision/seams.py:287 `pwfile.write_text(f"{password}\n")`, then the ACL call and `try/finally` start at :288-295.
**Why it matters:** The superuser password sits in a file with inherited ACLs for a short window, and a failure in `write_text` (disk full) leaves a partial secret behind because `unlink` is only in the `finally` after.
**Fix path:** Create the file with `os.open(..., 0o600)` / restrict the ACL on an empty file first, and open the `try` before the write.
**Blast radius:** seams.py `_initdb_pwfile` and its tests (tests/native/test_provision_seams.py).

### B-015 Minor: verify_and_kill_process can raise although its contract says it never does
**Dimension:** Correctness
**Evidence:** civiccast/egress/process_identity.py:44-46 `except psutil.TimeoutExpired: process.kill()` can itself raise `NoSuchProcess` or `AccessDenied`; sibling except clauses do not cover an exception raised in another handler, and the function does not wait after `kill()`.
**Why it matters:** Callers (egress daemon orphan reaper, relay_reclaim, contribution coprocess) rely on "Never raises"; an exception here can abort an orphan-cleanup pass.
**Fix path:** Wrap the forced kill in its own try/except (NoSuchProcess means success) and wait briefly.
**Blast radius:** egress/process_identity.py, tests/egress/test_process_identity*.

### B-016 Minor: Test health: real-Postgres contract tests skip silently by default and the retention tests do not exercise discovery for the leak above
**Dimension:** Tests
**Evidence:** tests/auth/test_staff_token_lifecycle.py:49-52 skips when no external Postgres or Docker (fails only if `CIVICCAST_RUN_POSTGRES_TESTS` is set); tests/captions/test_review_persistence.py:477-480 skips `TestRealPostgres` unless `CIVICCAST_POSTGRES_TEST_URL` is set; tests/captions/test_live_caption_proof.py:30,45 skip without ffmpeg. test_caption_retention.py:455-490 sets `evidence_pending` by hand (see B-004). No xfail marks in captions, native or auth tests; the remaining skips are Windows-only or tool-missing guards.
**Why it matters:** A green local run does not exercise token revocation or the Postgres review store; the retention leak passed because the test built the candidate dict itself.
**Fix path:** Have the release gate set the two env vars so skips become failures, and add a discovery-level retention test (mixed covered/uncovered chunks).
**Blast radius:** tests only.

### B-017 Nit: Restart-storm alert reports lifetime restarts and the epoch list is never trimmed
**Dimension:** Correctness
**Evidence:** civiccast/native/supervisor/core.py:502,1188,1201: `_restart_epochs` is append-only and the alert text says `{len(self._restart_epochs)} child restarts within the ...s window`.
**Why it matters:** The number in the alert is all-time, not in-window; the list grows slowly under a crash loop.
**Fix path:** Prune to the window on append and report the in-window count.
**Blast radius:** core.py, tests/native/test_supervisor_core*.

### B-018 Nit: Failed containment cleanup can kill the control plane it just contained
**Dimension:** Correctness
**Evidence:** civiccast/platform/child_containment.py:275-283: if `assign_current_process` succeeded and then `current_process_in_job` raises (or returns False), the code calls `api.close_handle(job)`; the job is KILL_ON_JOB_CLOSE and the process is already a member.
**Why it matters:** Very unlikely, but the failure posture is documented as "never fatal".
**Fix path:** Keep the handle open (append to `_RETAINED_HANDLES`) if assignment succeeded, even when confirmation failed.
**Blast radius:** child_containment.py, tests/native/test_child_containment*.

### B-019 Nit: Pipe error replies and the provider-key CLI expose detail they need not
**Dimension:** Correctness
**Evidence:** pipe_server.py:386-391 returns `detail=str(exc)` from command failures to any Authenticated User on the pipe; civiccast/cli.py:985-1012 accepts the cloud provider secret via `--key` (visible in the process list) although an env-var path exists.
**Why it matters:** Minor local information disclosure and secret-on-argv exposure.
**Fix path:** Return a generic error plus a correlation id and log the detail; prefer stdin/env for the key and warn when `--key` is used.
**Blast radius:** pipe_server.py Dispatcher tests, tests/test_cli_provider_key.py.

## What's working

- Staff authentication is middleware-enforced for every `/api/staff/*` path (civiccast/auth/middleware.py:36-60) and I found no router mounted outside that prefix that mutates state without its own check. An AST scan of all routers showed every non-GET staff route carries a role dependency (producer_ops via router-level `dependencies`, auth sign-out intentionally any role). Staff GETs without a role are authenticated reads only.
- The earlier "DB password served unauthenticated" class is closed: `ManagedStorageStatusReport` strips the URL and credential (installer/storage.py:124-179), `/api/setup/storage` requires staff auth once setup is complete (installer/router.py:1296-1330), `signed_out_view` withholds the profile (installer/models.py:447-464), `/openapi.json` on LAN-only stations needs a staff token (app.py:3683-3705). Setup access uses the socket peer, never a forwarded header.
- Public contributor and media routes show deliberate hardening: opaque upload refs rather than server paths (contribute/router.py:575-590), generic 503 text for storage errors, per-IP reservations under one lock, path containment on `/media/vod` and `/media/live` (`stream/media_router.py:_serve_from_directory` plus `resolve_local_hls_directory`), no `audio_evidence` accepted from clients (captions/review.py:44-63).
- Caption tap concurrency design is careful: consistent session-then-retention lock order (tap_worker.py:1612-1697, 2360-2375), generation tokens to drop stale ASR results, fail-closed retention gating, honest docstring on what the thread-priority nudge does not do (tap_worker.py:277-316), bounded phase-timing collector (phase_timing.py:75-130).
- Process hygiene: argv-only subprocess calls (no `shell=True` anywhere in the product package), PID-reuse guard by create-time in `verify_and_kill_process`, anonymous kill-on-close job for control-plane descendants (platform/child_containment.py), pipe SDDL with explicit NETWORK deny and squat detection (pipe_server.py:73, create_control_pipe), logs rotate at 10 MiB x 10.
- tests: `tests/captions/test_caption_retention.py` and `test_live_sidecar.py` pass (21 passed in 3 s at BelowNormal). No xfail in the three test trees I checked; skips are environmental.

## Not checked

- Most of the 2,377-line supervisor/service.py and 1,896-line core.py (read the pipe, containment, restart-recovery and storm paths only); native/upgrade, provision orchestration beyond the password file, installed-runtime/closure/license code, win_probes, gstreamer repair.
- cli.py (2,755 lines) beyond the token and provider-key commands; app.py beyond the middleware chain, lifespan head, health/hardware and portal mounts; the durable-store wiring and every background worker's own error handling.
- Most staff routers' input validation and role mapping per route (only the missing-role scan); schedule upload and watch-folder code; ActivityPub inbox signature verification; paywall webhook; auth/store.py token lifecycle internals; Postgres-backed behaviour (no DB available, real-Postgres tests skip).
- captions/vod.py, vod_job.py, runtime.py (ASR runtime), benchmark.py, hls.py, cdn_republish.py, external.py, tap_backoff.py, tap_batch_diagnostic.py.
- No live or soak runs, no network probing, nothing executed against the live station; B-004 is the only finding proven by running code, the rest are from reading.
