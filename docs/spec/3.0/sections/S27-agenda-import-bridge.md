# S27 — Agenda Import Bridge (vendor + JS-portal sources)

**Status:** Phases 1-3 (Legistar, PrimeGov, CivicClerk) SHIPPED prior to this
section's authorship — retroactively documented here 2026-08-25, no
numbered spec section previously existed for `civiccast/agenda_import/`
(confirmed by grep: zero hits for "agenda import"/"Agenda Bridge" anywhere
under `docs/spec/3.0/` before this file). Phase 4 (`js_portal`) SHIPPED
2026-08-25. No new migration — Phase 4 reuses migration `0078_agenda_item_
confidence`'s existing `AgendaItem.confidence` column and adds no schema.
**Scope:** Import a municipality's existing agenda system's meetings/items
into a draft `MeetingAgenda` (S25), so staff do not have to retype or
re-upload an agenda a city already publishes elsewhere.
**Functional target:** closes the manual-re-entry gap between S25's editor
(operator-typed/pasted/PDF-uploaded agendas) and municipalities that already
run PrimeGov, CivicClerk, Legistar/Granicus, or a CivicPlus AgendaCenter.
**Owning section:** extends S25 (`civiccast/agenda/`) — this module
(`civiccast/agenda_import/`) is the ONE place that writes external content
into an S25 `MeetingAgenda`/`AgendaItem`, via
`civiccast.agenda_import.mapper.import_external_agenda`.
**Key claim boundary:** an import only ever produces draft, unpublished
content (AI/agenda non-negotiables Spec §4.2) and only ever adds NEW items —
re-running an import on the same meeting is idempotent and never clobbers an
operator's own edits.

---

## 1. Goal & rationale

A station whose city already runs an agenda system (PrimeGov, CivicClerk,
Legistar/Granicus, or a CivicPlus AgendaCenter) does not want staff to
retype what the city already publishes. This module discovers upcoming/
recent meetings from that system and imports one meeting's agenda into an
S25 `MeetingAgenda` as a set of draft `AgendaItem` rows, reusing S25's
existing storage, publish gate, and idempotent `(agenda_id, order)` upsert —
this module adds no new item storage of its own.

## 2. Adapter seam

Every vendor implements one Protocol
(`civiccast.agenda_import.base.AgendaSource`):

```python
class AgendaSource(Protocol):
    def fetch_meetings(self, client_code: str, *, since: date | None = None) -> list[ExternalMeetingSummary]: ...
    def fetch_agenda(self, client_code: str, event_id: str) -> ExternalAgenda: ...
```

`civiccast.agenda_import.registry.build_source(name, ...)` resolves a name
to an adapter; `civiccast.agenda_import.router` exposes it as two staff
routes (`GET /api/staff/agenda-sources/{source}/{client_code}/meetings` for
discovery, `POST /api/staff/agenda/{agenda_id}/import-external` for the
actual import), gated the same way as every other agenda-editor write
(`records_clerk`/`meeting_operator`). `CIVICCAST_AGENDA_SOURCE` (env,
default `off`) selects the one active vendor for a station; both routes 404
naming the env var when it is `off`.

Shared, vendor-agnostic errors
(`AgendaSourceAuthRequiredError`/`AgendaSourceUpstreamError`/
`AgendaSourceNotAvailableError`/`AgendaSourceDependencyMissingError`) map to
502/422/503 respectively — see `civiccast/agenda_import/base.py`'s
docstring for the full taxonomy and why `AgendaSourceDependencyMissingError`
(Phase 4, below) is the one genuinely new failure mode.

## 3. Phase 1-3: Legistar, PrimeGov, CivicClerk (plain HTTP, no browser)

All three vendors have a documented, anonymous, plain-HTTP endpoint — no
headless browser is needed or used:

* **Legistar** (`legistar.py`) — the OData Web API
  (`webapi.legistar.com/v1/{client}/Events`), token-gated for a minority of
  tenants (confirmed live: NYC), open for most (confirmed live: Seattle).
* **PrimeGov** (`primegov.py`) — the anonymous Public Portal API
  (`{client}.primegov.com/api/v2/PublicPortal/ListUpcomingMeetings`) +
  compiled-HTML-agenda extraction (`docparse.py`). Live-verified against
  `longmont.primegov.com`.
* **CivicClerk** (`civicclerk.py`) — the anonymous Events API
  (`{client}.api.civicclerk.com/v1/Events`) + a documented per-document PDF
  fetch. Live-verified against `portagemi.api.civicclerk.com`.

Each adapter's own module docstring carries its live-verification ledger
(exact endpoints, real tenant, capture date) — not restated here to avoid a
second copy that can drift from the code.

## 4. Phase 4: `js_portal` (crawl4ai/Playwright, JS-hydrated portals)

**The endpoint evaluation that scoped this adapter.** Before building a
headless-browser adapter, this pass re-checked whether PrimeGov/CivicClerk
genuinely need one: they do not (§3 above) — both have a documented,
anonymous, plain-HTTP path, already the primary/only adapter for each. A
headless-browser fallback for either would be strictly heavier for no
capability gain, so `js_portal` is NOT the default path for any vendor that
already has one; it exists for the vendor family that does not:
**CivicPlus's AgendaCenter and Granicus/Legistar's public-facing pages**,
both confirmed (by inspection) to render their meeting content client-side
with no documented anonymous JSON/iCal endpoint of their own.

**Design.** `civiccast/agenda_import/js_portal.py`'s `JsPortalSource` uses
[crawl4ai](https://github.com/unclecode/crawl4ai) (Apache-2.0,
Playwright-based) to render a portal URL, then applies a heuristic text
classifier (numbered items, markdown headings, confidence-scored 0.0-1.0 —
the same convention `civiccast.agenda.pdf_import`'s PDF-upload heuristic
already established, reused via `ExternalAgendaItem.confidence`, newly added
this phase and threaded through the mapper) to extract meetings and items.
Config is per-import: `portal_url` (the portal's own URL — validated
http/https, no userinfo, no private/loopback/metadata IP literal) +
`portal_vendor_hint` (tunes which extra keywords the listing-link filter
uses; `client_code` stays a plain operator-assigned display label, unlike
the other three vendors, since there is no fixed per-vendor host to splice
it into).

**Bounding (non-negotiable for any headless-browser crawl):** same-origin
only (never follows or fetches a link off the configured portal), robots.txt
fetched and respected before any navigation, at most two pages per call
(the listing page, then one meeting's detail page — v1 does not paginate),
a wall-clock timeout, and no auth flow of any kind (no login form, no stored
session, no anti-forgery-token compile-download flow).

**Optional dependency.** crawl4ai + Playwright's Chromium binary (~300 MB)
ships as the `civiccast[agenda-js-import]` extra — NOT bundled by the native
Windows installer's `requirements-native-app.txt` lock (deliberately
excluded from that file's `uv pip compile --extra ...` invocation, mirroring
`captions-runtime`'s existing pattern for `faster-whisper`). Absent, the
adapter's lazy import raises `JsPortalRuntimeUnavailableError`
(`AgendaSourceDependencyMissingError`), mapped to HTTP 503. A dedicated,
always-reachable route (`GET /api/staff/agenda-sources/js-portal/posture`)
reports the honest install posture without raising, so the operator console
can show a "not installed" state before an import attempt, not after.

Pinned floor is `crawl4ai>=0.9.2,<0.10`, not the first version this extra
was drafted against — `pip-audit` against an earlier `crawl4ai>=0.7.4` lock
showed it forces a project-wide `lxml` downgrade (to satisfy its own
`lxml~=5.3` pin against `pikepdf`/`sacrebleu`'s newer floor) that
reintroduces a known, fixed CVE (PYSEC-2026-87) into `uv.lock`, even though
the extra itself is never installed by default. `0.9.2` relaxed that pin to
`lxml<7,>=5.3`; re-locked and re-verified clean.

**Live-verification status.** The bounding/sandboxing machinery is
live-proven (a real crawl against `friscotexas.gov/AgendaCenter` succeeded:
robots.txt honored, page rendered, markdown returned). The extraction
heuristic is fixture-proven (synthetic CivicPlus/Granicus-shaped markdown)
but NOT yet proven useful against a real CivicPlus tenant: Frisco's real
meeting rows only render after an interactive category-selection step this
v1 does not perform, so today's result on that shape of tenant is an honest
empty/low-yield miss, not a wrong answer. See
`civiccast/agenda_import/js_portal.py`'s module docstring for the full
ledger. Closing this gap (simulating the category-selection interaction via
crawl4ai's `js_code`/`wait_for` config) is real, scoped follow-up work.

## 5. Draft-only guarantee (AI/agenda non-negotiables §4.2)

A new agenda already defaults to draft (S25's `MeetingAgendaInput`). The
case §4.2 actually governs is importing INTO an agenda that is already
published: `import_external_agenda` reopens it to draft whenever it writes
at least one new item (a no-op re-import writes nothing and does not
disturb a published agenda). This mirrors
`civiccast.agenda.service.AgendaService.import_from_doc`'s identical PDF-
import reopen behavior, added here in Phase 4 alongside `js_portal` (whose
heuristic output is the first vendor-import content that is genuinely
uncertain) and applied uniformly to all four vendors, since the underlying
principle — "this content did not come from the operator's own typing" — is
equally true of a Legistar/PrimeGov/CivicClerk fetch. This function never
sets `status` to `"published"` under any circumstance.

## 6. Tests

`tests/agenda_import/`: `test_legistar.py`, `test_primegov.py`,
`test_civicclerk.py`, `test_docparse.py` (Phases 1-3, pre-existing);
`test_js_portal.py`, `test_config.py`, `test_registry.py`, `test_router.py`,
`test_mapper.py`, `test_models.py`, `test_provenance.py` (shared + Phase 4
additions). `test_live_proof*.py` are live-network-gated (skipped by
default; set `CIVICCAST_RUN_AGENDA_SOURCE_PROOF=1`) — `js_portal` has no
live-proof test file of its own because its dependency is optional and not
installed by default in CI; its live-verification evidence (§4 above) was
gathered manually, outside the test suite, and disclosed in the module
docstring rather than gated behind a CI-conditional test.

Operator console: `civiccast/apps/portal-operator/src/screens/
AgendasScreen.tsx`'s "External agenda import" bulk-action section (added
Phase 4 — the vendor-bridge API had no console consumer at all before this
phase). Source picker (four vendors), per-source config fields, a two-step
discover-then-import flow, and `js_portal`'s not-installed/loading/
installed posture states.
