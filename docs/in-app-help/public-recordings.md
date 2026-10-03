# Browse recordings (route: `#/recordings?q=&year=&body=&cf.<key>=&page=`)

Paths are under `civiccast/apps/portal-public/`. Line numbers are `src/screens/RecordingsScreen.tsx` unless noted.

## Where the text lives now
`RecordingsScreen.tsx` (lines 239-451). The recording cards are a shared part in `src/screens/HomeScreen.tsx:764-780`. Menu words for extra filters come from the station (custom field labels).

## Current text
| String | Where | Source line |
| --- | --- | --- |
| Browse recordings | Heading | 239 |
| Search and replay every published meeting recording. Each page, search, and recording has its own shareable link. | Intro | 242-243 |
| (search form, role "search") | Form | 248 |
| Search recordings / Search by title or description | Box label / placeholder | 256 / 263 |
| Year; All years; `<year>` (no recordings) | Menu | 268; 274; 277 |
| Meeting body; All bodies; `<body>` (no recordings) | Menu | 287; 293; 298 |
| Search | Button | 311 |
| `<field label>`; All; `<value>` (no recordings) | Extra menus, one per station-made field | 322; 329; 333 |
| Loading published recordings. | Loading | 353 |
| Showing recordings in a reduced-search mode — full search is temporarily unavailable, so some filters below may show fewer results than normal. Try again shortly for full search. | Amber note | 363-365 |
| Published recordings could not be loaded. Try again or contact the station. | Error | 374 |
| Retry | Button | 380 |
| No recordings have been published yet. See what's on the channels — new meeting recordings appear here after they are published. | Empty archive ("what's on the channels" links to `#/schedule`) | 389-393 |
| No recordings match this filter. Clear the search or facets to browse everything. | No match | 396 |
| `N` recording(s) match this filter / page `x` of `y` (or "published" instead of "match this filter") | Results line | 404-405 |
| Recording pages; Previous; Next; page numbers | Page buttons | 413; 420; 443; 434 |
| Recording description not posted.; Published `<date>`; Watch recording | Each card | `HomeScreen.tsx:769,772,778` |

## What the page really does
It loads the whole list of published recordings once, then filters in the browser. A search matches any part of the title or description; capital letters do not matter (88-89). The Year menu lists the years the recordings were published, not the years of the meetings (78, 168). The Meeting body menu lists the bodies tagged on recordings; a recording with no body never matches when you pick one (81). Twelve cards show per page (27). If the search service is not ready (HTTP 503) it falls back to a plain list and shows the amber note (140-146), and the extra menus disappear. Every filter and page is in the address, so a search can be shared.

## Mismatches
| ID | What it says | What really happens | Severity |
| --- | --- | --- | --- |
| public-recordings/HELP-20 | "Clear the search or facets" | There is no clear button, and "facets" is jargon (396). The resident must reset each box. | Medium |
| public-recordings/HELP-21 | "Search and replay every published meeting recording" | The search reads only titles and descriptions, not captions, agendas or spoken words (88-89). The placeholder is right; the intro suggests more. | Medium |
| public-recordings/HELP-22 | "Recording description not posted." | Looks like an error on every card with no description (`HomeScreen.tsx:769`). | Low |
| public-recordings/HELP-23 | "reduced-search mode", an em dash | Jargon and a long sentence (363-365). | Low |
| public-recordings/HELP-24 | (missing) | Nothing says matching is by parts of words, any capitals. | Low |
| public-recordings/NEW-1 | Menu "Year" | It is the year the video was published, not the meeting year (78). A December meeting posted in January sits under the later year. | Medium |
| public-recordings/NEW-2 | Menu "Meeting body" | Recordings with no body vanish when a body is chosen (81). Nothing says so. | Medium |
| public-recordings/NEW-3 | Year and body menus | They apply the moment the choice changes (`onChange`, 271, 290), but the text box needs the Search button. A keyboard or screen reader user arrowing through the closed menu can reload the list on every arrow press (WCAG 3.2.2). Read from code; not tested in a browser. | Medium |
| public-recordings/NEW-4 | Results line `N recordings published / page 1 of 3` | A slash reads badly aloud, and the line announces after every change (role "status", 403). | Low |
| public-recordings/NEW-5 | Amber note | In this mode extra menus vanish (customFieldFacets come from search-only data, `types.ts:16-19`) with no mention. | Low |

## Proposed text
| Replace | With |
| --- | --- |
| 242-243 | Search past meetings by title or description. You can also pick a year or a meeting body. You can copy the page address to share your search. |
| 263 placeholder | Words in the title or description |
| 268 label | Year published |
| 274 / 293 | All years / All meeting bodies |
| 363-365 | Search is limited right now. Some filters may show fewer results. Please try again soon. |
| 374 | We could not load the recordings. Please try again, or contact the station. |
| 389-393 | No recordings have been posted yet. See [what is on the channels] (link to Schedule). New recordings appear here after the station posts them. |
| 396 | No recordings match. Try different words, or choose All years and All meeting bodies. |
| 404-405 | `N` recordings. Page `x` of `y`. (With a filter: `N` recordings match. Page `x` of `y`.) |
| New line under the filters (when a body is picked) | Recordings that have no meeting body are not shown when you pick one. |
| Card description fallback | (hide the line) or "No description yet." |

**New: Clear all button.** Label "Clear all filters". It goes to `#/recordings`. After fix, 396 becomes: "No recordings match. Press Clear all filters to see everything."

**Accessibility.** Search box is inside a labeled search form (keep). Menus have visible labels (keep). Current page button has `aria-current="page"` (keep). Make Year and body wait for the Search button, or announce the change politely. Keep 44 px buttons. Page-number buttons need no new label.

## Notes for the coder
- Edit `RecordingsScreen.tsx` and the card in `HomeScreen.tsx:764-780`.
- Code fixes: a Clear all button; labeling of Year; apply menu choices on Search (or on blur) instead of on every change.
- Tests that pin strings: `e2e/routing.spec.ts:132,170` ("No recordings match this filter. Clear the search or facets to browse everything."), `routing.spec.ts:102,107,111,122,126,154,158,177` (results line wording), `RecordingsScreen.test.tsx:55` (the "reduced-search mode — full search..." text), `RecordingsScreen.test.tsx:80,107` (error line), `ResidentRetry.test.tsx:68,72-74` (label names Year, Meeting body, Topic; loading text). Changing the "Year" label breaks `ResidentRetry.test.tsx:72` (`getByLabelText('Year')` is an exact match); `routing.spec.ts:124` uses Playwright `getByLabel('Year')`, which matches part of a name, so it should still pass (not run).
- Not verified: which recordings the server lists (read from `schedule/router.py:150-165`: published ones only) and how the body tag gets set (staff side, see manual chapter 15).
