# S24 — Underwriting / Sponsorship Spot Management

**Status:** Build spec for CivicCast 3.0 · Authored 2026-06-14 · Closes S18 gap 10 (migration `0057_underwriting_spots`)
**Migration note:** renumbered from planned `0055` → `0057` per RECONCILIATION D17 after S23 took the on-disk `0055`; reconciled 2026-06-18.
**Scope:** Underwriting spots as schedulable assets + trafficking/rotation + program-log break insertion + per-underwriter as-run affidavits & billing
**Functional target:** incumbent PEG platform Pre-Roll Messaging + scheduled-spot insertion + playback verification
**Owning sections:** extends S4/S5 (program-log insertion), S7 (spot asset), S23 (affidavits)
**Key claim / legal boundary:** PEG is **noncommercial** — spots are **underwriting acknowledgments** under **47 CFR 73.503**: sponsor identification only (name/logo/location/value-neutral description); **no calls-to-action, no price, no qualitative/comparative claims.** This is an **editorial** constraint enforced by operator policy + a content-review note, **not** by code.

---

## 1. Goal & PEG automation rationale

PEG/public-media is noncommercial but **runs paid underwriting spots from for-profit companies** — a real revenue stream ("PBS has commercials," just without CTAs/claims). A PEG automation system must let a station **traffic** these: define a spot, set its flight (dates/frequency), insert it into program breaks, and **prove to the underwriter it aired** (affidavit) for billing. **CivicCast today has only a CG "sponsor" logo zone** — no spot asset, no trafficking, no break insertion, no affidavits (verified: `underwrit`/`spot_`/`trafficking` ≈ logo-zone only). **VOD/OTT pre-roll already exists (~45 code refs)**, so the gap is the **linear** side. S18 gap 10 (essential — revenue).

---

## 2. Current state (code grounding)
| Component | Where | Status |
|---|---|---|
| CG `ZoneKind="sponsor"` (logo overlay) | `cg/models.py`, `app_platform/models.py` | shipped (cosmetic only) |
| VOD/OTT pre-roll | `civiccast/` (~45 `pre.?roll` refs) | shipped (internet side) |
| Generic as-run proof | `egress/` proof | shipped |
| **Spot-as-asset / flights / break insertion / underwriter affidavits** | — | **absent (net-new)** |

---

## 3. Entities & migration `0057_underwriting_spots`
```python
class UnderwritingSpot(BaseModel):
    spot_id: Slug
    station_id: Slug
    underwriter: str                   # the sponsoring entity
    asset_id: Slug                     # the :15/:30 acknowledgment video (an Asset, S7)
    fcc_compliant_ack: bool = False    # operator attests sponsor-ID-only (no CTA/price/claims) — editorial gate
    review_notes: str | None = None

class SpotFlight(BaseModel):
    flight_id: Slug
    spot_id: Slug
    start_date: date
    end_date: date
    frequency_cap_per_day: int | None = None
    daypart: DaypartSpec | None = None       # reuse S19 daypart; targeting
    channels: list[Slug]

class SpotPlacement(BaseModel):                # resolved insertion (what the compiler placed)
    placement_id: Slug
    flight_id: Slug
    channel_id: Slug
    scheduled_at: datetime                     # break/interstitial slot in the program log
    schedule_item_id: Slug                     # the materialized program-log item

class UnderwriterAffidavit(BaseModel):          # proof-of-airing for billing (view-backed by S23 as-run)
    affidavit_id: Slug
    underwriter: str
    period_start: date
    period_end: date
    aired: list[dict]                           # [{spot_id, channel, aired_at, duration_s}] from as_run (source_kind='spot')
    total_airings: int
    total_seconds: int
```
Migration `0057_underwriting_spots` adds `underwriting_spots` + `spot_flights` + `spot_placements` (+ `underwriter_affidavits` if persisted, else a report view over S23 `as_run_log`). It branches from `0055_asrun_and_epg` (S23, shipped) — `down_revision = "0055_asrun_and_epg"`. The slot `0056_scheduled_recording` is reserved as a SIBLING branch for S21 (also off `0055`); when S21 ships, an Alembic merge revision will unify the two heads. See the [RECONCILIATION chain-shape footer](../RECONCILIATION.md#per-section-fix-list-applied-in-the-finalization-pass) for the canonical explanation.

---

## 4. API surface
```
GET/POST/PATCH/DEL  /api/staff/underwriting/spots
GET/POST/PATCH/DEL  /api/staff/underwriting/flights
GET                 /api/staff/underwriting/placements?channel&from&to   # what will/did air
GET                 /api/staff/underwriting/affidavits?underwriter&from&to # proof-of-airing → billing
```
Roles: `publish_operator`/`setup_admin` manage spots/flights; `support_admin` read affidavits.

## 5. Operator UI
- **Spots** (`/portal-operator/underwriting`): create a spot (asset + underwriter + the **FCC ack checkbox** with the 73.503 reminder text), manage flights (dates/freq-cap/daypart/channels).
- **Placements** view: upcoming + aired insertions per channel.
- **Affidavits**: generate per-underwriter proof-of-airing (period) → PDF/CSV for billing.

## 6. Behavior / algorithm
- **Trafficking compiler** (runs with the S19 schedule compiler): for each active `SpotFlight`, place spots into **program-log breaks/interstitials** respecting frequency cap + daypart + flight window → `SpotPlacement` → a materialized `schedule_item` (`source_kind="spot"`). Honors the OnAirLock commit gate (S4).
- **Linear insertion**, not SCTE-35: spots are scheduled interstitial assets (validation confirmed the incumbent PEG platform lacks SCTE-35 too — scope-neutral; SCTE-35 dynamic insertion is V2/OTT only, S18 D15).
- **VOD/OTT pre-roll** reuses the existing pre-roll path (internet side already built).
- **Affidavit:** join S23 `as_run_log` where `source_kind="spot"` filtered by underwriter over a period → airings + total seconds → billing report.
- **Editorial gate:** the `fcc_compliant_ack` checkbox surfaces the 73.503 rules; unacknowledged spots can be blocked from scheduling by station policy (configurable). Code does **not** parse spot content for claims — that's human review.

## 7. Proof tier + testable DONE-criteria
| # | Done-criterion (testable) | Proof |
|---|---|---|
| DC-1 | A flight places spots into program-log breaks respecting frequency cap + daypart + window. | contract |
| DC-2 | Placed spots materialize as `schedule_item`s (`source_kind="spot"`) through the unchanged S4 commit gate. | contract→lab |
| DC-3 | After airing, the underwriter affidavit lists each airing (timestamp/channel/duration) from S23 as-run, totals correct. | contract (with S23) |
| DC-4 | Frequency cap is never exceeded; flights respect start/end dates. | contract |
| DC-5 | The `fcc_compliant_ack` gate is required (per station policy) and surfaces the 73.503 reminder; no code claims to police content. | contract |
| DC-6 | VOD/OTT pre-roll path still works (regression). | lab |

Proof tier: **contract → lab**.

## 8. Test plan
Unit: trafficking compiler (cap/daypart/window), placement→schedule_item, affidavit join + totals, ack gate. API: spots/flights/placements/affidavits + role gating. E2E: create spot+flight → see placements → (after playout) generate affidavit. Coverage >80%; audit 0/0/0/0/0.

## 9. Dependencies & cross-references
**S4/S5** (break insertion into the program log; commit gate) · **S19** (shared compiler cadence + daypart) · **S7** (spot = Asset) · **S23** (as-run → affidavits) · **S14** (optional: spot impressions). Legal: 47 CFR 73.503 (editorial only).

## 10. DONE when
DC-1…DC-6 pass; migration `0057` on the chain; spots/flights/affidavit UI complete + accessible; audit 0/0/0/0/0; MASTER §11 index + RECONCILIATION.md + `ROADMAP.status.yaml` (the S24 row AND the step-12 roll-up) all reference S24 / `0057`.

Estimated effort: **~2 engineer-weeks** (trafficking compiler + entities + migration + API + UI + affidavit join + tests).
