# Custom Fields  (nav id: custom-fields, section: Setup)
Source files (under `civiccast\apps\portal-operator\src\`): `screens\CustomFieldsScreen.tsx` (screen + CustomFieldDefForm + DefRow), `screens\custom-fields-format.ts` (type labels, option parsing, sort), `screens\AssetCustomFieldsEditor.tsx` (the per-asset editor, used on the asset detail page, `AssetDetailScreen.tsx:801`), `components\EmptyState.tsx`, `api\client.ts:1835-1885`. Public consumer: `apps\portal-public\src\screens\RecordingsScreen.tsx` (facets).
Backend: `civiccast\metadata\router.py` (staff routes `/api/staff/custom-fields*`, `/api/staff/assets/{id}/custom-fields`, public `/api/public/search`), `metadata\service.py`, `metadata\store.py` (upsert_def 149, delete_def 200, _validate 311), `metadata\models.py:56-180`.
Who can open it: sidebar shows it to `setup_admin` only (`Sidebar.tsx:113`); the screen repeats the check (`ROLES = ['setup_admin']`, line 48) and shows "Custom Fields requires the setup admin role. Ask your station admin for access." (542). The server lets `setup_admin`, `meeting_operator`, `records_clerk` READ field definitions and only `setup_admin` create/edit/delete (`_READ`, `_DEF_WRITE`, router.py:57-58). The per-asset editor is usable by `setup_admin`, `meeting_operator`, `records_clerk` (`AssetDetailScreen.tsx:27`, router `_VALUE_WRITE`).

## What it is for
It is where the station invents its own labels for programs (for example "Meeting type", "Department", "Episode number"). Each label becomes a box on every asset's detail page, and, if marked searchable and public, a filter on the public Recordings page. It does not hold the values themselves; values are typed on each asset.

## What the user sees
H1 "Custom Fields" + "Define your station's own metadata fields (meeting type, board members, episode number…). Typed and validated, set per asset, and — when searchable — shown as a portal search facet. The key is fixed after creation so saved searches and reports keep working." (554-557). Then a form card ("Define a new field" or "Edit field"), any error banners, and the "Defined fields" list.

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Field key (machine name) (162; aria "Field key"; placeholder "meeting_type") | Permanent code name of the field | `POST /api/staff/custom-fields` (`field_id` is made as `cf-<key slug>`, `station_id` hard-coded `civiccast-station`; CustomFieldsScreen.tsx:122-129,501-503) | `setup_admin` | Disabled when editing. Help: "Lowercase machine key (immutable once created). The label is what operators see." / editing: "The key is fixed after creation so saved searches and reports keep working." The key itself is not validated for lowercase (server only checks 1-120 chars for `key`, models.py:152) |
| Label (operator-facing) (186; placeholder "Meeting type") | Name shown to staff and on the public filter | same | | Required, max 200 |
| Type (204) | Text, Long text, List (pick one), Date, Number, Yes / no, Asset reference, Producer reference (`custom-fields-format.ts:34-43`) | same | | Editable after creation (PATCH sends `type`); no warning when values exist (UNVERIFIED how existing values behave) |
| List options (one per line) (227; placeholder Regular / Special / Workshop) | Choices for a List field | same | | Only shown for type List |
| Required (checkbox) | Every asset save must then have a value | same | | See findings; `Required field 'cf-x' ('Label') must be present.` is the server error (store.py:328) |
| Searchable (portal facet) (checkbox, default ticked) | Allows filtering | same | | Public filter only appears when also "Exposed to public API" (service.py `search_public_assets`; store.py:193-196) |
| Exposed to public API (checkbox, default ticked) | Makes the value visible to the public | same | | |
| Order (number, default 0) | Sort position (lower first) | same | | |
| Create field (300) / Save changes (300) | Creates a field, or saves edits (label, type, options, flags, order only) | `POST` / `PATCH /api/staff/custom-fields/{field_id}` | `setup_admin` | Disabled until key and label filled. Success clears the form; errors: "Could not create the field." / "Could not save the field." or server text. **Creating with a key that makes the same field id as an existing field overwrites that field's label/type/options/flags without warning** (`upsert_def`, store.py:149-175; service.py:169-171 "or update an existing one") |
| Cancel (309) | Leaves edit mode, clears the form | none | | Only when editing |
| ↑ / ↓ (aria "Move <label> up/down") | Swaps this field's Order number with its neighbour | two `PATCH`es per click (521-522) | `setup_admin` | Disabled at the ends. If neighbours have the same Order (all new fields default to 0) the swap changes nothing, so the arrows appear dead |
| Edit (aria "Edit <label>") | Loads the field into the form | none | | |
| Delete (aria "Delete <label>") -> "Confirm delete (cascades values)" | First click calls delete without confirm. If no values exist it deletes at once with no warning; if values exist the server answers 409 and the row turns the button into the red confirm button; second click deletes the field and all its saved values | `DELETE /api/staff/custom-fields/{id}` then `?confirm=true` | `setup_admin` | The row text under the buttons is the server's sentence + "Confirming will permanently delete this field and all its values." The row has no Cancel for this state (only a page reload clears it) |

### Per-asset editor (`AssetCustomFieldsEditor`) — on the Assets > asset detail page
Section "Custom fields". One input per defined field in Order order, widgets: text input, textarea (Long text), number, date, checkbox (Yes / no), dropdown with "— Select —" (List; a saved value no longer in the list shows "<value> (not in current options)"), and a text box with a suggestion list for Asset reference (placeholder "Asset id") and Producer reference (placeholder "Producer id"). Required fields are marked with a red `*`. Button "Save custom fields" (busy "Saving…") sends the whole set via `PUT /api/staff/assets/{id}/custom-fields` (full replace; empty values are left out so clearing a box removes the value); success shows "✓ Saved." Failure: "Save failed. <server text>" (422 for invalid number/date, value not in list, reference not found). If a required value is missing: "Fill required fields before saving: <labels>" and Save is disabled. Read-only roles see disabled inputs and no Save. Empty text: "No custom fields are defined. Define fields in Setup → Custom Fields to tag assets here." Loading: "Loading custom fields…".

## States
- Loading: "Loading…" (identity), "Loading fields…".
- Identity error: AuthRequiredState text (see station-profile inventory).
- Load error: "Could not load fields." or server text; 503 "Durable storage is not ready yet." (router.py:52).
- Empty list: headline "No custom fields yet." body "Custom fields let this station tag its programs with its own labels — a department, a meeting body, a sponsor code. Add your first field with the form above and it appears here." (586-587).
- Row summary: `<Label> <key> · <Type> · required · searchable · public` (flags shown only when set; 349-358).

## Typical task flows
1. Add a "Meeting type" list: key `meeting_type`, label "Meeting type", type List, options one per line, leave Searchable and Exposed ticked, Create field.
2. Use it: Assets -> open an asset -> Custom fields -> pick a value -> Save custom fields.
3. Public filter: residents see a filter on the Recordings page for fields that are Searchable AND Exposed and have a value on at least one published recording (RecordingsScreen.tsx:182-190).
4. Remove a field: Delete; if values exist, Confirm delete.

## Statuses and words on this screen
Type names above; row tags "required", "searchable", "public". No readiness vocabulary.

## Related settings / env / CLI / API
`CIVICCAST_STATION_ID` (server's active station, default `civiccast-station`; router.py:137-141), `GET /api/public/search?cf.<key>=<value>` plus `cf.<key>_gte` / `_lte`, spec tag S22.

## Help-text findings
- [HELP-01] CustomFieldsScreen.tsx:262 — "Searchable (portal facet)" and 271 "Exposed to public API" — a field only appears as a public filter when BOTH are ticked; ticking only "Searchable" does nothing for residents, and "API" is jargon for "visible to the public" — fix: one control "Show on the public website" or explain that both are needed.
- [HELP-02] CustomFieldsScreen.tsx:162,181 — "Field key (machine name)" / "Lowercase machine key" — nothing stops capitals or spaces (only the internal id is slugged), and creating a second field with the same key silently replaces the first (upsert), including changing its type — fix: refuse duplicate keys with a plain message, or validate the pattern.
- [HELP-03] CustomFieldsScreen.tsx:415 — delete conflict text is the server's: "Custom field 'cf-meeting-type' has existing values; pass confirm=True to cascade-delete them." followed by "Confirming will permanently delete this field and all its values." — shows an internal id and "confirm=True"; also the first Delete click on a field with no values deletes it with no prompt — fix: always confirm and say "N assets have a value for this field".
- [HELP-04] CustomFieldsScreen.tsx:361-380 — ↑ ↓ reorder buttons swap the Order numbers; when fields share Order 0 (every field made without setting Order) nothing visibly moves — fix: renumber all rows on move, or explain Order.
- [HELP-05] CustomFieldsScreen.tsx:203-222 — Type can be changed on a field that already has values; no warning about what happens to existing values (UNVERIFIED) — fix: warn or lock when values exist.
- [HELP-06] AssetCustomFieldsEditor.tsx / store.py:328 — a "Required" field makes any asset without a value unsavable (including values for other fields); server message uses ids: "Required field 'cf-x' ('Label') must be present." — page never warns that ticking Required affects every existing asset — fix: warn on the Required checkbox.
- [HELP-07] CustomFieldsScreen.tsx:51 — the screen creates fields for station id `civiccast-station` always, while the server lists fields for `CIVICCAST_STATION_ID` if set; with that variable set new fields would not appear in the list — fix: let the server assign the station.
- [HELP-08] Nav/section: sidebar group "Setup" holds this entry, but its effect is mostly on Assets and the public site; neither page says where the fields show up besides the one H1 sentence — fix: add "Edit values on Assets > (an asset)".

## Screenshot plan
1. Empty state ("No custom fields yet.").
2. Form with type List and options filled, flags visible.
3. Defined fields list with 3 rows showing tags and arrows.
4. Delete conflict row with red "Confirm delete (cascades values)" and the server sentence.
5. Edit mode with disabled key.
6. Asset detail page "Custom fields" section with a required field and the "Fill required fields before saving" warning; and the public Recordings page facet.
Setup: create two fields and give one a value on a sample asset (use the sample content).

## UNVERIFIED / open questions
- UNVERIFIED: what happens to already-saved values when a field's Type or List options change.
- UNVERIFIED: whether the public portal hides a facet when no recording has a value (read RecordingsScreen.tsx:182-190 only partly).
- UNVERIFIED: whether `records_clerk` can reach the asset page (the asset screen's own role gate not traced).
- UNVERIFIED: that `key` uniqueness per station is enforced anywhere other than through the derived field id (no unique constraint read; migration not opened).
