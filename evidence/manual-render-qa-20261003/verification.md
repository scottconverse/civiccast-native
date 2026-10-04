# Manual render verification

Scope: candidate files under `.agent-runs/manual-render-20261003/`; existing shipped manual artifacts were not modified.

- Render job: root-owned project renderer exited 0 with PASS and reported no warnings. Source binding: `docs/USER-MANUAL.md`, SHA-256 `82d4e5c4704ed3f5d0ee932a41c8e2755746b9d36410ef925239fea07f362e1b`.
- PDF: 10,289,861 bytes; SHA-256 `3b11979156d74b2c614d5362e45e6147a877957eff064efc2d25bb9c4fd885dc`; Poppler `pdfinfo` reports 496 pages, Letter, unencrypted, PDF 1.7. Text extraction found 0 empty pages and 0 U+FFFD replacement characters.
- DOCX: 8,448,589 bytes; SHA-256 `dcddf71de5c6d7fd7caab52a50736577ff973a5f473cd313433d19467a066812`; ZIP integrity passed; structural read found 3,840 paragraphs, 306 tables, 79 inline shapes, and 76 `word/media` parts.
- PDF visual check: rendered all 496 pages to 45-DPI previews and reviewed all 21 contact sheets covering pages 1–496. No obvious missing pages, blank-content pages, clipping, overlap, or broken figures/tables at overview scale. These thumbnails are not a 100%-zoom page-by-page inspection.
- DOCX visual check: not run. This Windows runtime has no supported bundled LibreOffice renderer; using the desktop installation is disallowed by the document-rendering instructions.
- Font-warning scan: not independently run; the temporary TeX build directory had already been removed. Renderer completed successfully without emitted warnings. Poppler bundle lacks `pdffonts.exe`.
- Not established: full-page 100%-zoom PDF QA, DOCX rendered-layout QA, or equivalence to Word rendering.

Preview intermediates are in this directory; generated from the candidate PDF, not product/source edits.
