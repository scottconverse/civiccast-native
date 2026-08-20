# S21 — Scheduled Recording (Record Schedule)

**Status:** SHIPPED 2026-06-18 · CivicCast 3.0 · Authored 2026-06-14 · Closes S18 gap 2 (migration `0056_scheduled_recording` — sibling slot off `0055`; merge revision `0060_recording_paywall_merge` unifies the heads)
**Scope:** Forward-scheduled capture from live inputs (SDI/HDMI) **and** network streams (RTSP/SRT/HLS/RTMP/MPEG-TS/NDI) into ready VOD/playout assets
**Functional target:** incumbent PEG platform **Record Schedule** — scheduled recordings from network streams + live inputs, pick encoder/target device, applied loudness at ingest
**Owning section:** extends S7 (media lifecycle / asset readiness) + S15 (engine record sink)
**Key claim boundary:** a recording produces a normal `Asset` + readiness record — downstream (VOD, program log, transcode) is unchanged.

---

## 1. Goal & PEG automation rationale

incumbent PEG platform lets an operator **schedule a recording in advance** - "record the council-chamber SDI feed Tuesdays 7-10 PM," or "capture this RTSP camera at 9 AM" - producing a file that auto-enters the library. CivicCast 3.0 now ships this as S21: the production app factory wires the scheduled recording service to an FFmpeg-backed capture runtime, asset finalizer, S8 alert sink, and supervised scheduler worker. A PEG station that captures meetings on a fixed calendar needs this; it closes S18 gap 2 (essential for SDI-fed stations, common otherwise).

---

## 2. Current state (code grounding)

| Component | Where | Status |
|---|---|---|
| Reactive recording (finalize on live-session end) | `civiccast/` live/session code (`finalize_recording`) | shipped |
| Engine record sink (open a capture pipeline) | `civiccast.recording.runtime.FfmpegScheduledCapturePipeline` + FFmpeg runtime | shipped |
| Asset + readiness pipeline | `ScheduledRecordingAssetFinalizer` + S7 ingest validation | shipped |
| Ingest-time loudness gate | S7 / S11 ingest validation path | shipped |
| **Forward-scheduled recording** | `RecordingService`, staff API, operator UI, `ScheduledRecordingWorker` | **shipped** |

---

## 3. Entities & migration `0056_scheduled_recording`

```python
class RecordingSchedule(BaseModel):
    schedule_id: Slug
    station_id: Slug
    name: str
    source: RecordingSource            # kind = sdi|hdmi|ndi|rtsp|srt|hls|rtmp|mpegts ; uri/input id
    recurrence: RecurrenceSpec | None  # None = one-shot; else RRULE-like (reuse S19/programlog)
    window: TimeWindow                 # start + (end | duration)
    encoder_profile: Slug              # references an S2/S7 encode profile (hw-encoder default)
    loudness_regime: str = "inherit"   # ingest loudness (S11)
    target_series: Slug | None = None  # auto-file the resulting asset into a series/show
    custom_field_values: dict = {}     # S22 — stamp custom metadata on the recorded asset
    enabled: bool = True

class RecordingJob(BaseModel):
    job_id: Slug
    schedule_id: Slug | None           # None = ad-hoc manual record
    state: Literal["scheduled","arming","recording","finalizing","done","failed","skipped"]
    started_at: datetime | None
    ended_at: datetime | None
    asset_id: Slug | None              # the produced Asset (S7)
    bytes_written: int = 0
    failure_reason: str | None = None
    proof_boundary: str = "local-capture-asset-sha256"
```
Migration `0056_scheduled_recording` adds `recording_schedules` + `recording_jobs`. Single global chain, as the **sibling slot off `0055_asrun_and_epg`** — its `down_revision = "0055_asrun_and_epg"` forks the chain; the data-free merge revision `0060_recording_paywall_merge` unifies the `0056` branch and the `0059_paywall_access` head back into a single new chain HEAD (`down_revision = ("0056_scheduled_recording", "0059_paywall_access")`). See RECONCILIATION's chain-shape footer for the diagram.

---

## 4. API surface

Eight endpoints total (the CRUD-per-id triple expands to GET/PATCH/DELETE):

```
GET     /api/staff/recording/schedules                            # list schedules
POST    /api/staff/recording/schedules                            # create schedule
GET     /api/staff/recording/schedules/{id}                       # read schedule
PATCH   /api/staff/recording/schedules/{id}                       # update schedule
DELETE  /api/staff/recording/schedules/{id}                       # delete schedule
POST    /api/staff/recording/schedules/{id}/record-now            # ad-hoc one-shot
GET     /api/staff/recording/jobs                                 # history + live status
POST    /api/staff/recording/jobs/{id}/stop                       # stop a running capture
```

Roles: `require_any_role("setup_admin","meeting_operator")` write; `support_admin` read. The router
mirrors role policy into the OpenAPI document via an `x-required-roles` extension on each operation
(`router.py` `_WRITE_EXTRA`) so external audit tooling can read the role policy from `openapi.json`
without parsing source — this is over-delivery vs the "Roles: ..." line below.

## 5. Operator UI
- **Recording schedules** (`/portal-operator/recording`): create/edit a schedule (source, recurrence, window, encoder, target series, custom fields), "Record now" button.
- **Job history/live** table: state, duration, bytes, link to the produced asset; stop control on running jobs.
- Phone-first; accessible per S20.

## 6. Behavior / algorithm
1. A scheduler (same cadence as S19) expands enabled schedules to upcoming `RecordingJob`s.
2. At `window.start` − arm-lead, **arm**: validate the source is reachable (S8 alert if not); reserve disk.
3. **Record:** open an S15 capture pipeline (`source → [loudness gate] → encode(profile) → file`); write the asset file; update `bytes_written`/state live.
4. At `window.end`/duration: **finalize** → create an `Asset` + `asset_readiness` (S7); apply target series + custom-field stamps; run transcode/readiness as for any ingest.
5. **Failure handling:** source unreachable → `failed` + S8 alert (never a silent miss); disk-full → `failed` + alert; overlap with another job on the same input → `skipped` with logged reason; a crash mid-record leaves a recoverable partial flagged for operator review.

## 7. Proof tier + testable DONE-criteria
| # | Done-criterion (testable) | Proof |
|---|---|---|
| DC-1 | A one-shot schedule on a network stream (RTSP/SRT/HLS) records the declared window to a playable asset; SHA-256 recorded. | lab |
| DC-2 | A recurring schedule materializes the expected `RecordingJob`s across a horizon (deterministic test). | contract |
| DC-3 | Source-unreachable at arm time → job `failed` + S8 alert; **no silent miss**. | contract→lab |
| DC-4 | Finalize produces an `Asset` + readiness identical in shape to a watch-folder ingest (S7), with target-series + custom-field stamps applied. | contract→lab |
| DC-5 | Overlap on the same input → second job `skipped` with reason; disk-full → `failed` + alert. | contract |
| DC-6 | Ingest loudness regime (S11) is applied during capture. | lab |
| DC-7 | SDI/HDMI input capture works once hardware is present (rung-3-adjacent; network-stream capture is the rung-2 bar). | lab→(SDI when hw) |

Proof tier: **contract → lab** (SDI input proof rides the S15 SDI hardware proof).

## 8. Test plan
Unit: recurrence/window expansion, arm/validate, overlap + disk-full + source-fail handling. API: all endpoints + role gating. E2E: create schedule → record-now a test stream → see asset in library. Coverage >80%; audit 0/0/0/0/0.

## 9. Dependencies & cross-references
S15 (capture pipeline / record sink) · S7 (asset + readiness + transcode) · S11 (ingest loudness) · S8 (source-fail/disk alerts) · S2 (input/source + encoder profiles) · S19 (recorded assets become schedulable; recurrence shared) · S22 (custom-field stamps).

## 10. DONE when
DC-1…DC-7 pass; migration `0056_scheduled_recording` on the chain as the sibling off `0055`, AND the merge revision `0060_recording_paywall_merge` unifies the heads; operator UI complete + accessible; audit 0/0/0/0/0; index/RECONCILIATION reference S21/`0056` + the merge `0060`.

Estimated effort: **~1.5–2 engineer-weeks** (models + migration + scheduler/capture wiring on S15 + API + UI + tests).
