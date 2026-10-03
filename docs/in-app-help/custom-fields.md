# Custom Fields (nav id: custom-fields)

Sidebar: Setup > **Custom Fields**. Manual authority: `docs/manual/src/22-configuration.md` section "Define Custom Fields" (`#configuration-custom-fields`). The values are typed on each asset (Assets > open an asset > Custom fields).

## Where the help text lives now
`civiccast/apps/portal-operator/src/screens/CustomFieldsScreen.tsx` (611 lines: CustomFieldsScreen, CustomFieldDefForm, DefRow), `custom-fields-format.ts` (type names), and the per-asset editor `AssetCustomFieldsEditor.tsx` (used on the asset detail page). Server text from `civiccast/metadata/store.py`. Lines confirmed by opening the files (HEAD 0b35aef6).

## Current text
| String | Where | Source line |
| --- | --- | --- |
| "Custom Fields"; "Define your station's own metadata fields (meeting type, board members, episode number…). Typed and validated, set per asset, and — when searchable — shown as a portal search facet. The key is fixed after creation so saved searches and reports keep working." | H1 and intro | CustomFieldsScreen.tsx:553, 555-557 |
| "Custom Fields requires the setup admin role. Ask your station admin for access."; "Loading…"; "Loading fields…"; "Could not load fields." | gate and states | 542, 527, 580, 583 |
| "Define a new field" / "Edit field" | form heading | 159 |
| "Field key (machine name)" (placeholder meeting_type); help "Lowercase machine key (immutable once created). The label is what operators see." / when editing "The key is fixed after creation so saved searches and reports keep working." | key box | 162, 169, 180-181 |
| "Label (operator-facing)" (placeholder "Meeting type") | label box | 186, 192 |
| "Type" (Text, Long text, List (pick one), Date, Number, Yes / no, Asset reference, Producer reference); "List options (one per line)" (placeholder Regular / Special / Workshop) | type and options | 204, 227, 233; custom-fields-format.ts:34-43 |
| Checkboxes "Required", "Searchable (portal facet)", "Exposed to public API"; "Order" | flags | 253, 262, 271, 276 |
| "Create field" / "Save changes"; "Cancel"; "Could not create the field."; "Could not save the field." | buttons and errors | 300, 309, 570, 573 |
| "Defined fields"; row summary "<Label> <key> · <Type> · required · searchable · public" | list | 577; 349-358 |
| Buttons "Edit", "Delete", "Confirm delete (cascades values)"; arrows "Move <label> up" / "down"; "<server sentence> Confirming will permanently delete this field and all its values." | row | 388, 408, 398, 363-375, 415 |
| "No custom fields yet." + "Custom fields let this station tag its programs with its own labels — a department, a meeting body, a sponsor code. Add your first field with the form above and it appears here." | empty state | 586-587 |
| Per-asset editor: "Custom fields"; "Loading custom fields…"; "No custom fields are defined. Define fields in Setup → Custom Fields to tag assets here."; "— Select —"; "<value> (not in current options)"; placeholders "Asset id" / "Producer id"; "Save custom fields" / "Saving…"; "✓ Saved."; "Save failed. <text>"; "Fill required fields before saving: <labels>" | AssetCustomFieldsEditor.tsx | 277, 282, 286, 127, 131, 155, 339, 343, 308, 325 |

## What the screen really does
It defines your own labels for assets, for example "Meeting type" or "Department". Each field becomes a box on every asset's detail page. If a field is Searchable and Exposed to public API (both are ticked by default) and at least one published recording has a value, residents get a filter for it on the Recordings page. This screen holds only the definitions; values are typed on each asset (Setup admin, Meeting operator and Records clerk can set them). A field's key cannot be changed after it is created. Order numbers decide the sort order. Deleting a field that has values asks for a second click and then deletes the field and all its saved values.

## Mismatches
| ID | What the text says | What really happens | Severity |
| --- | --- | --- | --- |
| HELP-01 | "Searchable (portal facet)" and "Exposed to public API" (262, 271) | Residents see a filter only when both are ticked and a published recording has a value; "API" is jargon for "visible to the public" | misleading |
| HELP-02 | "Lowercase machine key (immutable once created)" (181) | Nothing checks for capitals or spaces (only the internal id is slugged); a second field with the same key silently replaces the first, including its type (store.py:149-175) | blocks work (silent overwrite) |
| HELP-03 | Delete conflict shows "Custom field 'cf-meeting-type' has existing values; pass confirm=True to cascade-delete them." (415) | Internal id and `confirm=True`; the first Delete on a field with no values deletes at once with no prompt | misleading (data loss) |
| HELP-04 | Up and down arrows (363-375) | They swap Order numbers; fields that all have Order 0 do not appear to move | misleading |
| HELP-05 | "Type" can be changed on a field that has values (204) | No warning; what happens to saved values is UNVERIFIED | misleading |
| HELP-06 | "Required" (253) | Every asset without a value becomes unsaveable, including edits to its other fields; the error uses internal ids "Required field 'cf-x' ('Label') must be present." (store.py:328) | blocks work |
| HELP-07 | Always creates fields for station id `civiccast-station` (CustomFieldsScreen.tsx:51) | If the service sets `CIVICCAST_STATION_ID`, new fields do not appear in the list | misleading |
| HELP-08 | Intro names only the portal facet | Neither this page nor the asset page says where the values are typed beyond one H1 sentence | cosmetic |
| NEW-1 | "Confirm delete (cascades values)" row has no Cancel (398) | Only a page reload clears the armed state | cosmetic |

## Proposed text
**Intro:** "What this is for: add your own labels to videos, such as 'Meeting type' or 'Department'. Each label becomes a box on every asset's page (Assets > open an asset > Custom fields), and can become a filter on the public Recordings page. Who can use this: Setup admin. Meeting operator and Records clerk can fill in the values. This page defines the labels only."
**Field key help:** "A short code name for the field. Use lowercase letters, numbers and underscores, for example meeting_type. You cannot change it later. Do not reuse a key: creating a field with an existing key replaces that field." After fix: refuse duplicate keys with "A field with this key already exists."
**Searchable label:** "Let residents filter by this field". **Exposed label:** "Show this field on the public website". Help line: "Residents see a filter only when both boxes are ticked and a published recording has a value for the field."
**Required label:** "Required. Every asset must have a value before it can be saved. Tick this only when you are ready to fill it in on every existing asset."
**Order help:** "Lower numbers come first. Fields with the same number may not move when you use the arrows." After fix: arrows renumber all rows.
**Type help (when editing a field that has values):** "Changing the type may make saved values invalid. Ask IT before you change it." After fix: lock the type once values exist.
**Delete:** first click always opens a confirmation: "Delete '<Label>'? <N> assets have a value for this field and all those values will be deleted. This cannot be undone." Buttons "Delete field" and "Cancel". Replace the server sentence with this text.
**Empty state:** keep, and add "Values are typed on each asset's page."
**Per-asset editor, required note:** "Fill in the fields marked * before saving. A required field blocks saving the whole form."

## Notes for the coder
- Files: `CustomFieldsScreen.tsx` (labels at 253-276, delete row 388-415), `AssetCustomFieldsEditor.tsx`, `civiccast/metadata/store.py:149-175, 311-330`, `service.py:169-171`.
- Pins: tests use accessible names, so keep the `aria-label` values: `CustomFieldsScreen.test.tsx` uses `findByLabelText('Field key')`, `/create field/i`, `/confirm delete/i`; `AssetCustomFieldsEditor.test.tsx:198` pins "no custom fields are defined". No test pins the intro or the helper texts. If you change the visible "Searchable"/"Exposed" wording keep `aria-label="Searchable"` and `aria-label="Exposed to public API"` or update the tests.
- Code fix needed, not text: reject a duplicate key instead of overwriting (HELP-02); always confirm delete and report the count of affected assets (HELP-03); renumber on move (HELP-04); let the server assign the station id (HELP-07); a Cancel on the armed delete (NEW-1); lock type changes when values exist.
