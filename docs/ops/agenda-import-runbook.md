# Agenda Import Runbook (Legistar / PrimeGov / CivicClerk)

This runbook explains how a station configures CivicCast to pull agenda items
in from their city's agenda system (4.1.0 "Agenda Bridge"). It is for
meeting operators, station admins, and technical integrators.

---

## Part 1 — Plain English (for station staff)

### What this does

Instead of copy-pasting a city council agenda item by item, an operator can
click **Import from agenda system**, pick the upcoming meeting from a
dropdown, and CivicCast pulls in every agenda item automatically — title,
number, order, and a link to the official document. The operator still
lines up video timecodes and publishes by hand; that part isn't automated in
this release.

This works with three different agenda systems city governments use:

- **Legistar** — used by many larger cities (e.g. Seattle).
- **PrimeGov** — used by many small-to-midsize cities.
- **CivicClerk** — used by many small-to-midsize cities (a third, separate
  vendor family from PrimeGov, even though both mostly serve similar-sized
  cities).

### What your station needs to know

- Find out which of the three systems your city government uses, and your
  city's "client code" (the short subdomain/tenant name the vendor assigns
  your city — for example `seattle` for Legistar, or `longmont` for
  PrimeGov). Ask your city clerk's office or IT contact if you're not sure.
- Give both pieces of information (which vendor, and the client code) to
  whoever manages your CivicCast station's configuration.
- If your city's system asks for a login/token and it isn't already
  working, that's a real limitation some cities' Legistar tenants have
  (confirmed live against New York City, which requires a token; Seattle's
  does not) — ask your city IT contact for an API token.
- If an import comes back empty or with an error, that is deliberate:
  CivicCast refuses to silently create a blank agenda. Read the error
  message — it names exactly what went wrong (a missing document, a
  required login, or the city's system being unreachable).
- Importing never overwrites items an operator has already edited by hand.
  Running the import again just adds anything new since the last import.

### What this is not

- It does not automatically sync agenda items to the right moment in the
  video — that's a separate, manual step.
- It does not write anything back to the city's agenda system — read-only.
- It is not a background service that watches for new meetings on its own —
  the operator triggers each import.

---

## Part 2 — Technical / IT reference

### Architecture

```
Operator (agenda editor)
   |
   | GET  /api/staff/agenda-sources/{source}/{client_code}/meetings
   | POST /api/staff/agenda/{agenda_id}/import-external
   v
civiccast/agenda_import/router.py  (2 routes; 404 when CIVICCAST_AGENDA_SOURCE=off)
   |
   v
civiccast/agenda_import/mapper.py  (the ONE writer -- validates every doc_url,
   |                                 then AgendaStore.upsert_item, idempotent
   |                                 on (agenda_id, order))
   v
civiccast/agenda_import/base.py  (AgendaSource Protocol)
   |
   +--- legistar.py    -- anonymous OData, 2-call fetch (Events, EventItems)
   +--- primegov.py     -- anonymous JSON + docparse.py (compiled HTML/PDF agenda)
   +--- civicclerk.py   -- anonymous OData + docparse.py (reused unchanged)

NOT touched: civiccast/civicclerk_bridge/  -- a separate, already-speced,
separate-repo CivicSuite event-bus integration. Not this package, not
renamed, not repurposed.
```

### Configuration

```
CIVICCAST_AGENDA_SOURCE           = off | legistar | primegov | civicclerk   (default off)
CIVICCAST_AGENDA_SOURCE_CLIENT    = <your city's tenant/client code>
CIVICCAST_AGENDA_SOURCE_TOKEN     = <optional Legistar token, only for a token-gated tenant>
CIVICCAST_AGENDA_SOURCE_TIMEOUT_S = 10
```

Set `CIVICCAST_AGENDA_SOURCE` to your city's vendor and restart. No code
change, no migration, no credential is required for the default
credential-free path — all three vendor APIs this connects to are public and
anonymous for every tenant confirmed live during development, with the
single known exception of a minority of Legistar tenants (e.g. NYC) that
require `CIVICCAST_AGENDA_SOURCE_TOKEN`.

### Per-vendor client codes

| Vendor | `client_code` is... | Example |
|---|---|---|
| Legistar | the tenant path segment on `webapi.legistar.com/v1/{client_code}` | `seattle` |
| PrimeGov | the tenant subdomain on `{client_code}.primegov.com` | `longmont` |
| CivicClerk | the tenant subdomain on `{client_code}.api.civicclerk.com` | `portagemi` |

### API surface

```
POST /api/staff/agenda/{agenda_id}/import-external
  body: { source: "legistar"|"primegov"|"civicclerk", client_code, event_id }
  -> 200 { imported: [AgendaItem...] }
     401 no staff token · 404 agenda import disabled/agenda not found
     422 unknown source name · 502 upstream fetch failed (incl. token-gated tenant)

GET /api/staff/agenda-sources/{source}/{client_code}/meetings?since=YYYY-MM-DD
  -> [{ external_id, title, meeting_datetime }]
```

Both routes require the `records_clerk` or `meeting_operator` role.

### Error taxonomy (all three vendors, identical)

| Situation | Response |
|---|---|
| `CIVICCAST_AGENDA_SOURCE=off` | 404, message names the env var |
| Unknown `source` value | 422 |
| Meeting agenda doesn't exist | 404 |
| Token-gated tenant (401/403) | 502, actionable message naming the client code |
| Upstream timeout / 5xx / malformed response | 502 |
| Vendor document has no reliably parseable items | 502, `extraction_status` named in the message (never a fabricated empty import) |
| Hostile URL scheme anywhere in the vendor payload | 502, nothing written |

### Idempotency

Re-running an import for the same meeting never duplicates or clobbers an
operator-edited item — `AgendaStore.upsert_item`'s existing
`(agenda_id, order)` skip rule (the same one `AgendaService.import_from_doc`
already uses) is shared by all three vendor adapters via
`agenda_import/mapper.py`. Only genuinely new items (a higher `order` not
seen before) are added on a re-import.

### Known, disclosed limits (not silently assumed away)

- **PrimeGov PDF-only meetings** are supported: when a document's `link` is
  null (the common case) the adapter builds PrimeGov's PUBLIC
  `/Public/CompiledDocument?meetingTemplateId=...&compileOutputType=...` URL from
  the document's `templateId` and downloads the PDF anonymously (the endpoint
  redirects to the real PDF). A document is only imported when the PDF's text
  layer parses into flat, top-level numbered items; a differently formatted
  agenda is an honest 502 `pdf_no_items`, not a fabricated import. A meeting
  whose only document is a cancellation notice yields an honest 502
  `cancellation_notice_only`.
- **PrimeGov bounded handling**: PDF downloads are capped at 100 MiB / 180 s
  (streamed, checked per chunk) and extraction at 500 pages / 2,000,000
  characters. The application retains the original on disk, its SHA256 and
  provider identity, and each successfully extracted page. Processing continues
  automatically in 12-page batches within a 20-minute attempt; retry resumes
  unfinished pages from that same retained original. Each local parser attempt
  has a 45-second killable subprocess budget. Native pypdf extraction falls back
  to independent PDFium text/rendering and local Tesseract OCR for image-only pages.
  A document
  over those bounds, an unreadable/encrypted PDF, a page that fails to extract,
  or a PARTIAL extraction is refused with a distinct error
  (`document_too_large`/`document_timeout`/`pdf_unreadable`/`pdf_partial`)
  BEFORE anything is written -- a truncated or page-incomplete document never
  silently replaces a complete agenda. The character budget is checked against
  each page's text BEFORE that page is parsed, so an overrun is refused whether
  the excess sits on the first, a middle, or the final page; text that totals
  exactly the limit is complete when every page was covered. A page whose text
  extraction raises is recorded (`pages_failed`) and makes the whole extraction
  partial even when numbered items were recovered from the surviving pages;
  every page failing reports `pdf_unreadable` rather than an empty agenda. The vendor's redirect to its external public blob storage is
  followed manually, each hop validated with the existing public-URL guard, so a
  redirect to a LITERAL loopback/private/link-local/metadata host is refused
  (DNS-rebinding remains that guard's pre-existing, disclosed residual risk).
- **PrimeGov discovery is upcoming + one finite archive list** (deduped by
  meeting id). If only one of the two list endpoints answers, the results are
  returned with an `X-Agenda-Discovery-Warning` PARTIAL banner; if both fail it
  is an honest 502, never an empty calendar. The archived year is the year of
  the existing `since` date filter, or the current year when it is blank --
  exactly one archive year per discovery call, never a multi-year scan. The
  import is scoped to the SAME finite year: the operator console sends the
  selected meeting's year as `archive_year` (PrimeGov-only request field,
  rejected for the other vendors), and the import lookup reads the upcoming
  list, that year and the current year -- at most three archive lists. Without
  an explicit year it keeps the older behaviour (current year plus the two prior
  years). So every meeting discovery offered, including one from an archived
  year older than current-2, is importable; provider ids are preserved unchanged
  and deduped, and an operator still selects one meeting explicitly.
  Discovery and import share ONE finite year rule: an archived-list year is the
  current UTC year or any earlier one, with no other arbitrary floor (a `since`
  date far in the past is offered and importable, because discovery clamps the
  requested year to that same rule). A meeting dated in a FUTURE year is never
  in an archived list -- it arrives through the always-queried upcoming list,
  which the importer reads first, so it needs no archive year at all and the
  console sends none for it.
- **CivicClerk's extraction is honestly bounded**: the shared PDF extractor
  recognizes flat, top-level digit-numbered lines only. A real agenda that
  nests numbered sub-items under lettered top-level sections (e.g.
  `A. Consent Agenda` → `1.`, `2.`, ...) still extracts those numbered
  lines, but flattens them into one sequential list rather than
  reconstructing the section hierarchy — proven against a real,
  live-fetched City of Portage, MI agenda during development.
- **Legistar token-gated tenants**: confirmed real (NYC). Ask the partner
  station's city IT contact for a token; there is no way around this for a
  gated tenant.

### Retained PDF storage and local OCR

PrimeGov's application adapter streams originals into
`CIVICCAST_UPLOAD_DIR/agenda-import` (development default: `uploads/agenda-import`).
`CIVICCAST_AGENDA_DOCUMENT_DIR` overrides that directory for an isolated deployment.
Each version-1 manifest records provider/tenant/meeting/document/URL, bytes and
SHA256. `original.pdf` and `pages.json` must be backed up together with that
managed storage. They contain public meeting material, not provider credentials.
Existing agenda tables require no migration; the new versioned files are additive.
Rollback preserves these files; older code ignores them. Do not delete originals
or checkpoints to retry a read. A changed original is refused rather than silently
mixed with prior pages. Incomplete download files are removed on failure.

Install a local Tesseract executable and English language data to enable scanned
page recovery, then set `CIVICCAST_TESSERACT_CMD` to its executable path (or put
`tesseract` on PATH). No cloud OCR or paid provider is called. Missing OCR, failed
pages, cancellation and exhausted budgets leave completed pages intact and refuse
an incomplete agenda import. A visually confirmed white page can count as blank;
an image containing unreadable content cannot silently count as complete.

The page reader is provider-independent; Longmont's published 258-page packet is
the large-document acceptance fixture. Complete page extraction alone does not
establish correct agenda-item interpretation. Agenda-section parsing and operator
preview/confirmation are the subsequent integration slice.
