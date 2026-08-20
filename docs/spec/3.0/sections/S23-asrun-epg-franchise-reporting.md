# S23 — As-Run / Proof-of-Performance, EPG Export & Franchise Reporting

**Status:** Build spec for CivicCast 3.0 · Authored 2026-06-14 · Closes S18 gap 5 (shipped as `0055_asrun_and_epg` 2026-06-18 — per RECONCILIATION.md Decisions §17–19 + the migration table)
**Scope:** As-aired logging + reports, EPG/TV-guide export (X-List/XMLTV/CSV), franchise hours-by-category, data export
**Functional target:** incumbent reporting workflow — Schedule Report, Shows Report, auto-schedule/workflow logs, **TV Guide X-List export**, hours-by-category franchise compliance
**Owning section:** extends S14 (analytics) — but distinct: **as-run = what *aired*; analytics = who *watched*.**
**Key claim boundary:** as-run reflects what the playout engine actually emitted (verified air times), not just what was scheduled.

---

## 1. Goal & PEG automation rationale

Municipal franchise agreements require PEG operators to **prove what aired** (hours by category, as-run logs) and to feed set-top-box guides. the incumbent PEG platform's Reporting suite (Schedule/Shows reports, **X-List EPG export** to TV Guide/TitanTV/XMLTV, hours-by-category) is core to keeping a franchise. **CivicCast has playback *analytics* (S14, who-watched) + generic egress proof, but no formal *as-run* report, no EPG export, no hours-by-category** (verified: `as_run`≈1 hit, `epg`/`xmltv` only as guide-display not export). S18 gap 5 (essential — franchise compliance).

---

## 2. Current state (code grounding)
| Component | Where | Status |
|---|---|---|
| Playback analytics (viewer count / time-watched) | S14 (`viewership_*`) | specced/partial |
| Program log + scheduled items (what was *planned*) | `programlog/` | shipped |
| Portal schedule guide (display) | portal (#145/#160) | shipped |
| Generic egress proof events | `egress/` proof | shipped |
| **As-run log (what *aired*) / Shows report / hours-by-category / EPG export** | — | **absent (net-new)** |

---

## 3. Entities & migration `0055_asrun_and_epg`
```python
class AsRunLogEntry(BaseModel):
    entry_id: Slug
    station_id: Slug
    channel_id: Slug
    schedule_item_id: Slug | None      # the planned slot, if any (None = live/manual/filler)
    asset_id: Slug | None
    scheduled_start: datetime | None
    actual_start: datetime             # what the engine actually emitted (S15/automation)
    actual_end: datetime
    duration_s: int
    source_kind: Literal["program","filler","live","slate","spot"]   # 'spot' links S24 underwriting
    verified: bool = True              # backed by engine proof-events (not just intent)

class EpgExportConfig(BaseModel):
    config_id: Slug
    station_id: Slug
    channel_id: Slug
    format: Literal["xlist","xmltv","csv"]
    horizon_days: int = 14
    endpoint: str | None = None        # push target (aggregator) or None = download-only
    field_map: dict = {}               # map CivicCast fields → aggregator columns
```
Migration `0055_asrun_and_epg` adds `as_run_log` + `epg_export_configs` (sequences after `0054_custom_metadata_fields`; shipped 2026-06-18). As-run entries are written by the **playout engine/automation** at actual air time (not a separate process). Reports (Shows, hours-by-category) are **queries/views** over `as_run_log` + `schedule_items` + custom fields (S22, `0054` — shipped) — no extra tables.

---

## 4. API surface
```
GET  /api/staff/reports/as-run?from&to&channel&category         # as-aired log
GET  /api/staff/reports/shows?from&to                           # per-show play counts / airtime
GET  /api/staff/reports/hours-by-category?from&to&field=<cf.key># franchise hours (groups by S22 custom field)
GET  /api/staff/reports/export?type=as-run|shows&format=csv|xml # data export
GET/POST/PATCH /api/staff/epg/configs                           # EPG export configs
POST /api/staff/epg/configs/{id}/generate                       # produce X-List/XMLTV/CSV (download or push)
GET  /api/public/reports/as-run?...                             # optional public as-run URL (PEG automation coverage)
```
Roles: `support_admin` read reports; `setup_admin`/`publish_operator` manage EPG configs.

## 5. Operator UI
- **Reports tab** (`/portal-operator/reports`): date/channel/category filters; Shows + As-Run + Hours-by-Category; print + shareable public URL; CSV/XML download.
- **EPG export config**: pick format + horizon + field map + endpoint; "Generate now"; show last export + validation.
- Accessible per S20.

## 6. Behavior / algorithm
- **As-run capture:** the engine/automation (S15/S4) emits a proof-event at every actual source transition → an `AsRunLogEntry` with `actual_start/end` + `verified` (from engine proof, so it's *what aired*, not *what was planned*). Filler/live/slate/spot all logged.
- **Reports:** Shows = group as-run by asset/series; Hours-by-category = group by a chosen S22 custom field (e.g., "Government" vs "Public-access") over a date range — the franchise number.
- **EPG export:** compile upcoming committed schedule (next `horizon_days`) into X-List/XMLTV/CSV per `field_map`; download or push to the aggregator endpoint; validate the output schema.
- **Underwriter affidavit (with S24):** filter as-run where `source_kind="spot"` by underwriter → proof-of-airing report (timestamp/channel/duration) → billing.

## 7. Proof tier + testable DONE-criteria
| # | Done-criterion (testable) | Proof |
|---|---|---|
| DC-1 | After a playout run, `as_run_log` reflects **actual** air times (engine-verified), distinct from scheduled times when they differ (e.g., a live overrun). | lab |
| DC-2 | Shows report aggregates correct play-counts/airtime over a window. | contract |
| DC-3 | Hours-by-category groups aired hours by an S22 custom field and totals correctly (the franchise number). | contract |
| DC-4 | EPG export produces valid **X-List** + **XMLTV** + CSV for the horizon, matching the committed schedule; schema-validated. | contract→lab |
| DC-5 | Data export (CSV/XML) of as-run + shows round-trips. | contract |
| DC-6 | Underwriter affidavit (join with S24 spots) lists each spot's air times for one underwriter. | contract (with S24) |

Proof tier: **contract → lab**.

## 8. Test plan
Unit: as-run aggregation, hours-by-category grouping, X-List/XMLTV serialization (schema-valid), affidavit join. API: all report + EPG endpoints + role gating + public-exposure boundary. E2E: run playout → view as-run → export EPG → download hours-by-category. Coverage >80%; audit 0/0/0/0/0.

## 9. Dependencies & cross-references
**S4/S5/S15** (engine emits actual air times + proof) · **S14** (analytics, complementary — who-watched) · **S22** (custom field = category grouping) · **S24** (underwriting affidavits) · **S8** (autopilot/workflow logs) · S20 (accessible reports UI).

## 10. DONE when
DC-1…DC-6 pass; migration `0055` on the chain; reports + EPG UI complete + accessible; audit 0/0/0/0/0; index/RECONCILIATION reference S23/`0055`.

Estimated effort: **~2 engineer-weeks** (as-run capture wiring + report queries + X-List/XMLTV exporters + UI + tests).
