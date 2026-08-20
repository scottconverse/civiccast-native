# Patent Risk Notes And Watchlist

Date: 2026-06-23

This document is technical/legal-risk triage for CivicCast 3.0. It is not legal
advice, not a freedom-to-operate opinion, and not a claim of non-infringement.
Patent risk is claim-by-claim and should be reviewed by qualified counsel before
commercial distribution or any sales push.

## Current Posture

The 2026-06-23 cleanup review did not identify an obvious public
Tightrope/Cablecast-owned utility patent that directly blocks CivicCast's core
software feature set. That does not eliminate patent risk. The strongest known
patent/licensing exposure remains standards and codecs: AVC/H.264, HEVC/H.265,
AAC, and related media-format pools.

CivicCast should keep open-codec defaults where practical, avoid redistributing
patent-encumbered proprietary builds unless cleared, and require operators to
obtain licenses for AVC/HEVC/AAC delivery, proprietary hardware runtimes, cloud
services, app stores, and any other deployment-specific obligations.

## Watchlist

These items are not proven infringement problems. They are areas to claim-chart
before expanding CivicCast into commercial or adjacent product territory.

| Area | Why it matters | CivicCast posture |
| --- | --- | --- |
| Automated removal of date-specific or promotional material from live automation logs when generating VOD | Broadcast automation to VOD workflows can be patent-sensitive. | Do not market or implement automatic date-specific promo stripping without counsel review. |
| Downstream replacement events with content verification | Replacement-event schedulers can combine media lookup, verification, and schedule update claims. | Describe current behavior as operator takeover, conflict detection, and schedule repair. Avoid broad "replacement engine" claims. |
| Hierarchical regional or multi-site playout federation | Regional schedule propagation and node hierarchy are patent-dense in broadcast automation. | Keep V2 federation behind a counsel-review trigger. |
| Real-time caption translation with topic dictionaries or live glossary substitution | Caption translation is patent-dense, especially when paired with domain dictionaries and live text-flow controls. | Market current work as local-model caption translation support. Review before adding proprietary-style live topic dictionaries. |
| Receiver-side EPG and set-top guide behavior | EPG display, reminders, and receiver behavior have a long patent history. | CivicCast exports guide/report data; avoid set-top guide replacement claims. |
| Dynamic ad insertion, targeted pre-roll, SCTE-35, ad decisioning, measurement | Ad-tech and targeted insertion are patent-heavy. | Keep 3.0 focused on scheduled linear spots and affidavits; review before SCTE-35 or targeted ad work. |
| Standards and codec pools | H.264/AVC, HEVC/H.265, AAC, NDI, DeckLink, and app-store delivery can require licenses. | Keep proprietary and patent-encumbered paths operator-enabled and documented; commercial distributions need separate clearance. |

## Counsel-Review Triggers

- V2 multi-site federation, overflow, or station-network workflows.
- Any dynamic ad insertion, ad decisioning, SCTE-35, targeted pre-roll, or
  audience-based monetization.
- Automated VOD derivation that edits or removes date-specific promotional,
  slate, overlay, or schedule material from a live automation playlist.
- Real-time caption translation with custom topic dictionaries, live glossary
  substitution, or text-flow management beyond ordinary model prompting.
- Commercial binary distribution with AVC/H.264, HEVC/H.265, AAC, NDI, DeckLink,
  or other patent/licensed defaults enabled.
- App-store publication, paid managed hosting, or bundled cloud media services.

## Search Record

The cleanup memo reviewed public repo surfaces and public web/patent sources for
Tightrope Media Systems, Cablecast, MediaScribe, Cablecast feature names, codec
pool evidence, and adjacent broadcast-automation patent areas. The search did
not include paid patent databases, prosecution histories, active-family review,
claim charts, confidential product information, or a formal legal opinion.
