# S22 — User-Defined Custom Metadata Fields

**Status:** Build spec for CivicCast 3.0 · Authored 2026-06-14 · Closes S18 gap 3 (migration `0054`)
**Scope:** Operator-defined custom fields on assets/shows — typed, searchable, exposed in the API
**Functional target:** incumbent PEG platform **Show Meta-Data & Custom Fields** — unlimited user-defined fields (text/list/date/number/asset/producer), searchable, in the API
**Owning section:** extends S7 (asset model); feeds S19 (saved-search queries), S23 (hours-by-category reporting), the public portal (search facets)
**Key claim boundary:** custom fields are additive metadata — they never alter core asset behavior; absence of any custom field is always valid.

---

## 1. Goal & PEG automation rationale

incumbent PEG platform lets each station define its own metadata fields ("Meeting Type", "Board Members", "Producer", "Episode #") and use them to organize galleries, drive saved-search scheduling, and prove franchise hours-by-category. **CivicCast's `Asset` is a fixed ~20-column schema** (title, series, meeting_body, ffprobe extracts, trim/chapter/retention) with **no user-defined fields** (verified: `custom_field` = 0 hits). Stations migrating off incumbent PEG platform lose their cataloging taxonomy without this — S18 gap 3 (common).

---

## 2. Current state (code grounding)
| Component | Where | Status |
|---|---|---|
| Fixed `Asset` schema (~20 typed columns) | `civiccast/schedule/models.py` (`Asset`) | shipped |
| `meeting_body` taxonomy facet | portal (#160) | shipped |
| **User-defined custom fields** | — | **absent (net-new)** |

---

## 3. Entities & migration `0054_custom_metadata_fields`

```python
CustomFieldType = Literal["text","longtext","list","date","number","boolean","asset_ref","producer_ref"]

class CustomFieldDef(BaseModel):
    field_id: Slug
    station_id: Slug
    key: str                       # stable machine key (immutable once created)
    label: str                     # operator-facing
    type: CustomFieldType
    options: list[str] = []        # for type=list
    required: bool = False
    searchable: bool = True        # exposed as a search facet + saved-search filter
    api_exposed: bool = True
    order: int = 0

class CustomFieldValue(BaseModel):
    asset_id: Slug
    field_id: Slug
    value: str                     # canonical string; typed-validated against the def
    value_num: float | None = None # denormalized for numeric range queries
    value_date: date | None = None # denormalized for date range queries
```
Migration `0054_custom_metadata_fields` adds `custom_field_defs` + `custom_field_values` (indexed on `(field_id, value)`, plus `value_num`/`value_date` for range search). Single global chain, after `0053`.

---

## 4. API surface
```
GET/POST       /api/staff/custom-fields                 # field definitions
GET/PATCH/DEL  /api/staff/custom-fields/{field_id}      # DEL blocked if values exist (or cascades w/ confirm)
GET/PUT        /api/staff/assets/{asset_id}/custom-fields  # get/set this asset's values (typed-validated)
GET            /api/public/search?cf.<key>=<value>      # custom-field facets exposed in portal search (if searchable+api_exposed)
```
Roles: `setup_admin` defines fields; `meeting_operator`/`records_clerk` set values; public read only for `api_exposed` fields.

## 5. Operator UI
- **Custom-field admin** (`/portal-operator/custom-fields`): define key/label/type/options/required/searchable; reorder.
- **Asset editor**: renders typed inputs for each field (text, dropdown for list, date picker, number, asset/producer pickers); validates required.
- **Portal search**: searchable fields appear as facets (accessible per S20).

## 6. Behavior / algorithm
- **Typed validation** at write: list→must be an option; number→`value_num`; date→`value_date`; required→must be present; `asset_ref`/`producer_ref`→must resolve.
- **Search:** searchable fields index into the existing portal/transcript search; `value_num`/`value_date` enable range queries; **S19 saved-searches can filter on custom fields**; **S23 reporting can group hours by a custom field** (e.g., "Government" vs "Public-access").
- **Key immutability:** `key` is fixed after creation (label is editable) so saved-searches/reports don't break.
- **Deletion safety:** deleting a field with existing values requires explicit confirm (cascade) — never silent data loss.

## 7. Proof tier + testable DONE-criteria
| # | Done-criterion (testable) | Proof |
|---|---|---|
| DC-1 | Define one field of each type; set values on an asset; typed validation rejects bad input (list/number/date/required). | contract |
| DC-2 | Searchable field appears as a portal facet and filters results; numeric/date range queries work via `value_num`/`value_date`. | contract→lab |
| DC-3 | A saved-search (S19) filters on a custom field and resolves the correct assets. | contract |
| DC-4 | S23 reporting groups aired-hours by a custom field. | contract (with S23) |
| DC-5 | `api_exposed` fields appear in the asset API; non-exposed do not leak to public. | contract |
| DC-6 | Deleting a field with values requires confirm; `key` is immutable after creation. | contract |

Proof tier: **contract → lab**.

## 8. Test plan
Unit: typed validation per type, range-query denormalization, key-immutability, delete-safety. API: defs + values + search + role gating + public-exposure boundary. E2E: define field → set on asset → search by it → use in a saved-search. Coverage >80%; audit 0/0/0/0/0.

## 9. Dependencies & cross-references
S7 (asset model) · **S19** (saved-search filters on custom fields) · **S23** (hours-by-category reporting) · public portal search · S20 (accessible field UI) · S21 (recording schedules stamp custom fields).

## 10. DONE when
DC-1…DC-6 pass; migration `0054` on the chain; admin + asset-editor + facet UI complete + accessible; audit 0/0/0/0/0; index/RECONCILIATION reference S22/`0054`.

Estimated effort: **~1 engineer-week** (models + migration + validation + API + UI + search wiring + tests).
