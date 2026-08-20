# civiccast.records Changelog

## Unreleased

- Clarified that signed-record output now renders veraPDF-validated PDF/A-3B
  artifacts while timestamp authority and legal signing authority remain
  deterministic/local by default.
- Added real PDF/A-3B signed-record rendering, veraPDF validation plumbing, and
  server-verified operator identity binding for export audit fingerprints.
- Fixed PDF/A-3B veraPDF validation under ISO 19005-3:2012. The four veraPDF
  failure categories from CI run `25971878411` are closed at the source:
  - Replaced the prior `sRGB_v4_ICC_preference.icc` fixture (Device Class
    `spac`, a PCS preference profile) with a Device Class `mntr` sRGB display
    profile generated via `PIL.ImageCms` / lcms2 and committed as `sRGB.icc`;
    clause 6.2.3 test 1 now passes.
  - Set `/Subtype` to the MIME-typed Name (`/application/json`,
    `/application/octet-stream`) on every `/EF/F` and `/EF/UF` stream of every
    file specification; clause 6.8 test 1 now passes.
  - Removed the `civiccast:*` custom XMP namespace from the metadata packet.
    PDF/A-3 section 6.6.2.3.1 forbids XMP properties that are not predefined or
    declared in an extension schema; the same audit data was already published
    in the structured attachments (`sourced-claims.json`, `provenance.json`,
    `approval.json`) and in the deterministic `xmpMM:DocumentID` UUID, so the
    XMP duplication was net-negative. Clauses 6.6.2.3.1 tests 1 and 2 now pass.
- Hardened `validate_pdfa3_shape` so the local check catches the saved-byte
  fields veraPDF rejected during Phase 1: `/Subtype` on every EF stream, ICC
  Device Class in `{mntr, prtr}` with version <5, no `civiccast:` namespace in
  XMP, `uuid:` URI shape on `xmpMM:DocumentID`/`InstanceID`, and no device-RGB
  operators in any page content stream. The pinned veraPDF workflow remains
  the conformance authority.
- Fixed module-internal mypy errors that ci-lint had been red on for several
  iterations (incomplete reportlab/pikepdf type stubs around
  `Canvas(initialFontName=...)` and `pikepdf.Object` dict iteration).

## v0.6.0 - 2026-05-14

- Added signed-record Pydantic contracts.
- Added deterministic PDF/A-3B contract-fixture rendering and local validation
  proof; this historical proof does not claim the deterministic fixture
  conforms to PDF/A-3B in v1.0.0.
- Added deterministic fixture timestamp metadata and tamper verification.
- Added server-side approved-summary export orchestration.
- Added in-memory and Postgres-backed signed-record stores.
- Added staff routes for export, download, and verification.
