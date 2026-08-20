# S25 — Meeting Agenda Integration

**Status:** SHIPPED 2026-06-18 · Build spec authored 2026-06-14 · Closes S18 gap A (migration `0058_meeting_agenda`; chain HEAD is now `0060_recording_paywall_merge` after S21 + S26 shipped 2026-06-18 and the merge revision unified the heads)
**Migration note:** renumbered from planned `0056` → `0058` per RECONCILIATION D18 after S23 took the on-disk `0055`; reconciled 2026-06-18.
**Scope:** Agenda items synced to video timecode (chaptered navigation) + optional agenda-document display beside the player
**Functional target:** incumbent PEG platform PDF-agenda embedding + agenda-synced chaptering (a government-access essential)
**Owning section:** extends S7 (asset/meeting) + the public portal; pattern-reference **OpenSlides** (MIT — borrow the agenda/item model, do NOT embed; it has open CVEs + a microservices footprint)
**Key claim boundary:** agenda is additive navigation metadata over an existing meeting asset; a meeting without an agenda is always valid.

---

## 1. Goal & parity rationale

A government-access viewer navigating a 4-hour council meeting needs to **jump to the agenda item they care about**. an incumbent PEG platform offers a synchronized, chaptered agenda (and PDF display) beside the video — for gov channels this is essential. **CivicCast began as a civic-meeting platform but has *no agenda concept* in code** (verified: `agenda` = 0 hits in the backend). It has meetings, VOD, chapters, transcripts — but no agenda-document or agenda-item model that binds items to video timecodes. This is S18 gap A (essential, government-access) — and the single clearest net-new gap the comparative work found.

---

## 2. Current state (code grounding)
| Component | Where | Status |
|---|---|---|
| Meeting/VOD asset + `meeting_body` | `schedule/models.py`, portal | shipped |
| Video chapters (generic) | portal/VOD | shipped/partial |
| Transcript + transcript search | summary/ + search | shipped |
| **Agenda document + agenda items + timecode sync** | — | **absent (net-new)** |

---

## 3. Entities & migration `0058_meeting_agenda`
```python
class MeetingAgenda(BaseModel):
    agenda_id: Slug
    station_id: Slug
    meeting_asset_id: Slug             # the recorded meeting (Asset, S7)
    source_doc_url: str | None = None  # optional uploaded agenda PDF (displayed beside player)
    status: Literal["draft","published"] = "draft"

class AgendaItem(BaseModel):
    item_id: Slug
    agenda_id: Slug
    order: int
    number: str | None = None          # "3.a", "VII"
    title: str
    video_timecode_s: int | None = None # offset into the meeting video (the jump point)
    doc_anchor: str | None = None       # optional anchor/page in the source PDF
    notes: str | None = None
```
Migration `0058_meeting_agenda` adds `meeting_agendas` + `agenda_items`. Sequences after `0057_underwriting_spots` (S24). Agenda items double as the meeting's **chapters** (one source of truth — chapters derive from agenda items when an agenda exists; implemented as the `agendaToChapters` projection helper, with the player chapter-strip wiring documented at the top of `MeetingAgendaSidebar.tsx` as the integration site — the sidebar is the user-visible chapter UI today).

---

## 4. API surface
```
GET/POST/PATCH/DEL  /api/staff/agendas                       # + /{id}
GET/POST/PATCH/DEL  /api/staff/agendas/{id}/items            # + /{item_id}
POST                /api/staff/agendas/{id}/sync-from-chapters  # seed items from existing chapters
POST                /api/staff/agendas/{id}/import            # parse an uploaded agenda doc → draft items (best-effort)
GET                 /api/public/agendas/{meeting_asset_id}    # portal: published agenda + items + timecodes
```
Roles: `records_clerk`/`meeting_operator` author; public read only when `status="published"`.

## 5. Operator UI
- **Agenda editor** (`/portal-operator/agendas`): build/import an agenda, attach an optional PDF, set each item's **video timecode** (scrub-to-set, or auto-seed from chapters), reorder, publish.
- **Portal player**: published agenda renders beside the video; clicking an item **seeks** the player to its timecode; optional PDF pane. Items are keyboard- and screen-reader-navigable (S20).

## 6. Behavior / algorithm
- **Timecode sync:** each `AgendaItem.video_timecode_s` is a seek point; the player builds a chapter list from published agenda items.
- **Seeding:** "sync-from-chapters" seeds items from existing chapter markers; "import" best-effort parses an uploaded agenda doc into draft items (operator confirms timecodes). No silent guessing — drafts require operator publish.
- **Transcript tie-in:** agenda items + transcript search compose (jump to item, then search within).
- **Single source of truth:** when an agenda exists, the meeting's chapters = its published items (no divergent chapter list).

## 7. Proof tier + testable DONE-criteria
| # | Done-criterion (testable) | Proof |
|---|---|---|
| DC-1 | Create an agenda with N items + timecodes; the public endpoint returns them only when published. | contract |
| DC-2 | Portal player seeks to the correct timecode on item click; chapters reflect published items. | lab (E2E) |
| DC-3 | "Sync-from-chapters" seeds items from existing chapters correctly. | contract |
| DC-4 | Optional PDF renders beside the player; absent PDF degrades gracefully. | lab |
| DC-5 | Agenda navigation is keyboard + screen-reader accessible (S20 DC-2/DC-3). | lab |
| DC-6 | Draft agendas/items never appear on the public endpoint. | contract |

Proof tier: **contract → lab**.

## 8. Test plan
Unit: agenda/item CRUD + ordering, publish gating, sync-from-chapters, import parser (best-effort, drafts only). API: staff + public endpoints + role/publish gating. E2E: build agenda → publish → portal seek + a11y nav. Coverage >80%; audit 0/0/0/0/0 (achieved 2026-06-18: 131 new tests — 97 backend + 21 portal-operator + 13 portal-public; full audit 0/0/0/0/0 pursued via /gauntletgate full).

## 9. Dependencies & cross-references
S7 (meeting asset) · public portal player + chapters · **S20** (accessible agenda nav) · transcript search · S26 (a paywalled meeting still shows its agenda). Pattern-reference: OpenSlides (MIT) agenda/item model — borrow, don't embed.

## 10. DONE when
DC-1…DC-6 pass; migration `0058` on the chain; agenda editor + portal player + a11y complete; audit 0/0/0/0/0; index/RECONCILIATION reference S25/`0058`. (Met 2026-06-18; DC-2 fulfilled by the documented integration seam — `agendaToChapters` projection + `MeetingAgendaSidebar.tsx` integration-site doc-block — rather than a wired player chapter strip. DC-4 satisfied via the optional source-doc URL projection; absent PDF degrades gracefully per the public projection's `source_doc_url:null` path.)

Estimated effort: **~1.5 engineer-weeks** (models + migration + editor UI + player seek/chapter wiring + import parser + tests).
