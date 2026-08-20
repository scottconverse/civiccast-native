# Portal meeting-body categories (option b) — Implementation Plan

> Branch work/portal-meeting-body off post-#159 main. Closes the "browse by
> meeting body/category" remainder of #107 (shipped without it: the asset
> model had no taxonomy field — product decision now made, option b).

**Shape:** one nullable `meeting_body` string on assets (e.g. "City Council",
"School Board"), operator-set on the asset detail screen, surfaced through
the existing public assets payload, and a portal browse facet derived from
the data exactly like the publish-year facet. No new config surface, no
fixed vocabulary — the station's own usage defines the list.

## Pieces (TDD, RED first per piece)

1. **Migration 0037_asset_meeting_body** (schedule module's versions dir;
   parent `0036_sdi_relay_device` — revision numbers are repo-global,
   directory = owning module): `assets.meeting_body VARCHAR(120) NULL`.
   Advance the single-head pin in tests/live/test_real_postgres.py.
2. **Models** (schedule/models.py): ORM `Asset.meeting_body`;
   `AssetMetadata.meeting_body` (public payload rides this for free);
   `StaffAssetRow.meeting_body`; `AssetMetadataUpdate.meeting_body`
   (PATCH; follow the existing unset-vs-null pattern used by description).
3. **Store** (schedule/store.py `update_metadata`): round-trip + clear.
4. **Operator console**: "Meeting body" text input on AssetDetailScreen
   (blank = none), rides the existing PATCH; e2e/unit pin if present.
5. **Portal-public**: meeting-body facet dropdown on RecordingsScreen
   (unique values derived from loaded recordings, like the year facet),
   filter in filterRecordings(), hash-route param so URLs stay shareable.
6. **Docs/truth**: CAPABILITIES public-portal row (remove "NOT implemented"
   caveat), API-REFERENCE/openapi regen.
7. Full gate -> PR (refs #107 remainder; option b decision) -> merge.

Out of scope: subscriptions target_type="meeting_body" wiring (separate
existing plumbing), CTV browse_facets, retroactive bulk tagging.
