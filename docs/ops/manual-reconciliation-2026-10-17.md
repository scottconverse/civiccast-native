# Manual reconciliation — October 17, 2026

Scope: the owner's nine-item documentation correction. No product behavior,
installer, installed station, publication or historical signed artifact is changed.
This records current source documentation, including unreleased Sprint 6 features.

## Finding dispositions

| Supplied finding | Disposition |
| --- | --- |
| Missing screens and inconsistent sidebar counts | Corrected chapter and appendix lists to 42 entries, including Other stations, with current navigation roles. |
| Missing staff-login troubleshooting | Added ordinary staff credential and rate-limit cases. |
| Recovery button wording | Explained the confirmation button rename without inventing different UI behavior. |
| Control Room refresh, countdown and lock recovery contradictions | Reconciled with restored open sessions, visible deadlines and authorized force-close. Live-screen state is a separate workflow. |
| AI preflight contradiction | Clarified that unconfigured AI is allowed but a failed AI check blocks. |
| Stop versus auto-start | Explained session-local suppression after explicit Stop/drain and the separate setting needed across restarts. |
| Sidebar visibility versus API permissions | Corrected table headings and explanation. |
| Recorded packaging and status labels | Corrected Recorded eligibility and Not servable yet wording. |
| Public portal emergency notice | Removed obsolete special-link requirement; documented actual polling. |
| Caption edit versus approval | Made the next approval step explicit; preserved the existing distinction between Edited and Approved. |
| Obsolete future publishing surfaces | Removed outdated future-badge claims; documented current available workflows. |
| Shared-first-admin assumptions | Corrected individual staff accounts and sign-in instructions. |
| Alerts permissions | Initial review was wrong: all roles read runtime-safe-to-air, but full alert-event listing/acknowledgment requires setup, support or meeting operator. Documentation now distinguishes these. No permission change. |
| Publication always queues captions / Portal-only implication | Explained enabled settings and stored-source prerequisites, separate from selected publication surfaces; preserved intentional Portal retry behavior. |
| Recorded captions cannot be disabled / mandatory Spanish | Corrected profile controls, English-only and English-first completion, and accepted legacy environment defaults. |
| RTMP unsupported | Corrected sink guidance to current GStreamer RTMP support. |
| Corrupted PowerShell paths | Existing Sprint 6 generator fix retained; regenerated documents checked. Installed old Help remains unchanged pending package update. |
| Lost recovery codes require first-setup reset | Pointed to offline local administrator password recovery; retained warning against using first-setup reset for this purpose. |
| Wrong station-state environment variable | Corrected to CIVICCAST_STATION_STATE_PATH. |
| Profile and registry ACL descriptions | Documented installer-managed ProgramData profile and service SID access alongside SYSTEM/Administrators. |
| Offline kit count/tree discrepancy | Replaced universal file count with release-manifest authority and identified the tree as a layout illustration. |
| Ollama startup condition inverted | Corrected missing executable/model-store condition. |
| GStreamer per-output normalization / UTC ADR rows | Reconciled with current implementation and station-time behavior. |
| Freeze budget exhaustion always requires manual restart | Explained fallback/cooldown and bounded programme retry, including operator-override boundary. |
| No account-role management screen | Corrected to Staff accounts. |
| Emergency compositor uncertain | Documented configured GStreamer inline overlay path and separate opt-in automatic presentation. |
| Refused summaries can be approved | Corrected to pending-review/state and audit-fingerprint guards, including store enforcement. |
| CLI/API/environment inventories stale | Regenerated existing inventories from current source: 47 commands, 522 operations, 443 variable names. |
| Contribution route summaries | Refreshed generated summaries. Closing a room still does not prove external provider disconnection. |
| CAPTION_RUNTIME=faster-whisper allegedly wrong | Retained: this differs from the separate Whistle live-primary selection. |
| Missing exit 136, paths and network choices | Added/corrected references, preserving loopback-only application binding and configured proxy access. |
| Backup checklist denies restore | Documented encrypted station archives and offline restore; did not claim restore over a running station. |
| Glossary/version/component/release-history drift | Corrected Whistle/Whisper, alerts, agenda, current version and Beta 16/17 entries; distinguished fetched contribution components from bundled components. |
| Heading IDs allegedly absent | The three cited anchors already rendered correctly and were preserved. A separate emergency-alert link was repaired after rendered inspection. |
| Tables, chapter links, typos and editorial placeholders | Corrected affected source, including extra/missing table cells and the stale regeneration note. |
| TSDuck guarantees unbroken media | Qualified continuity/PCR/source-port handling; no assertion that encoder outages produce uninterrupted media. |
| Gain ride applies universally | Identified preparation behavior and actual defaults; no universal live-input guarantee. |
| Summary generation strictly enforces stored approved captions | Corrected to normal console workflow versus authorized API-supplied cues. Citation checks are not semantic truth verification. No API redesign or vulnerability claim. |
| RFC 3161 timestamping universally active | Distinguished configured real authority from default deterministic placeholder and validation result types. |
| Historical Beta 11 measurements | Preserved original release attribution and measured values. |

## Source and delivery boundaries

The corrections are in chapter sources and regenerated inventories, with matching
README, architecture, capability/operations and release guidance. TownLight
integration remains owner-deferred to 2.0. The installed Beta 19 Help and signed
release documents are historical artifacts and are not overwritten.

## Verification

Existing generator/render tools are used; no new harness, product test suite,
soak or installer build was run. PowerShell is parsed for syntax only;
administrative examples are not executed.

- Inventory generators completed: 47 CLI commands, 522 API operations in 84
  groups and 443 environment variable names. Named missing backup/auth/federation
  endpoints and caption/MediaMTX settings are present. The API generator creates
  an application object without starting its service; it applied migrations to
  its development SQLite store, not the running station's PostgreSQL database.
- Final assembled manual: all 16 executable PowerShell fences parse without
  syntax errors. A CLI synopsis with angle-bracket placeholders is correctly
  labeled text rather than executable PowerShell.
- Chapter-source table column check: no mismatches. The extra installer row
  cell and missing public-route row delimiter were corrected.
- Rendered Help: 111 internal link targets resolve, including the three preserved
  caption anchors. The separate emergency-alert anchor now resolves.
- Named stale operating claims and path-corruption patterns are absent from the
  assembled manual. This was a targeted content check, not a claim that an
  arbitrary substring scan proves the entire product correct.
- Independent source review corrected a remaining caption startup-error example
  and the initial review's incorrect Alerts permission interpretation.
- `render_docsite_manual.py --check-current` and `git diff --check` passed.

Final PDF/Word render completed. `render_user_manual.py --check-current` passed:
both artifacts match the final source hashes and the PDF running-header version.
The PDF contains 520 pages of text. Extracted text and Word XML contain the
corrected captions, recovery-variable and station-connection instructions.
PDF physical pages 188 (caption settings) and 19 (role table) were rendered to
images and inspected: the corrected text and table fit and remain readable.
The first render exposed an unresolved emergency-alert anchor; that was fixed
before the final render, which reported no undefined-reference warning.
MiKTeX printed its update-check advisory; rendering exited successfully.

Artifacts are under `artifacts/documentation-correction-2026-10-17`:
`USER-MANUAL.pdf`, `USER-MANUAL.docx` and `USER-MANUAL.render.json`.
The in-app artifact is `civiccast/docsite/manual.json`, generated from the same
`docs/USER-MANUAL.md`. Published kits and installed Help remain unchanged.

Disposition: all nine owner-authorized documentation correction items completed
at the source/rendered-artifact layer. Installer rebuilding, publication and
updating the running station remain separate, unauthorized delivery steps.

proved: focused content, 16 PowerShell syntax examples, 111 internal anchors,
table structure, Help/PDF/Word currentness and sampled rendered pages passed · lane: Standard
