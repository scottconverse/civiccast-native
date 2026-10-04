# Manual screenshot sources

## Live source, pre-flight and end-confirmation examples (2026-10-03)

Three actual current React LiveRoomScreen/App/HashRouter captures with product
CSS, native headless Chrome and synthetic intercepted API replies only. Fourteen
source/style/support paths matched the isolated frontend before capture and were
rehashed unchanged afterward. Owned localhost port 5195 served modules only;
other origins and unexpected API requests failed closed. No real backend,
camera, media, source probe or station was contacted. No credentials were used.
Inert Vite HMR is a harness limitation, not packaged-app proof.

The source example has no session and an unprobed example camera. The checklist
shows nine synthetic rows and a failed source check; Start Live Stream is disabled.
To reach the end dialog through actual UI controls, session creation, start
pre-flight, evaluation and go-on-air received synthetic intercepted responses.
Its On air / Pre-flight ready labels are examples, not broadcast proof. End was
opened and cancelled; no end-broadcast request occurred. Each image was inspected.

Evidence: oversight `evidence/live-manual-examples.py`, `live-manual-capture.txt`
and `live-manual-source-receipt.json` (complete source hashes/request inventory).
LiveRoomScreen SHA-256:
`634d99e2e535de57be977b36eb765fe8de3fafa84b6330ef0f8562cb29795198`.
Product CSS: `b54dfb51d3caf0fb63a509ea4fa114f889cad56dc6709e677cec343efe821db9`.
ConfirmDialog: `119af618113acdb49b8d6ed6abb39e56211ccf564831392a5fd498570fb53c4c`.

Copied PNG SHA-256:

- `operator-live-sources.png`: `e20e4547ed3f8e8cd1138900805e6f9e29fc394b1900eb5259d743d746268fa2`
- `operator-live-preflight.png`: `2df85c4e546647d7aa7615117287acbe925f0dfc22091ab8a848171ba901d1d2`
- `operator-live-endconfirm.png`: `a178929c3b12b838b826dbdd7fecd2cbec6e39730bc3860079f21c4bd15459ca`

## First-admin and sign-in examples (2026-10-03)

Actual current App/SetupScreen and product CSS, captured in headless Chrome with
synthetic GET-only station/setup responses. Ten selected source files were
hash-equal between the checkout and isolated frontend before capture and unchanged
afterward. Unexpected origins, API routes and all writes were refused. The single
synthetic signed-out HTTP 401 per example was expected; no other browser errors or
horizontal overflow were observed. No password, valid recovery code or credential
was entered, and no account, kit, sign-in or recovery operation was performed.

Browser screenshot clips include the complete relevant forms, excluding blank
viewport space and unrelated lower setup tools; product DOM/CSS was not modified.
Both images were individually visually inspected after capture and copied unchanged.

- `operator-setup-firstadmin.png`: SHA256
  `B40C3275C5D9D5D3FB552E3EA9C656DD90C81BDFDE76E8710AED64A55DD90935`.
- `operator-setup-signin.png`: SHA256
  `BB563A6D121C942FE6B07ECBEE61E67BEE2A5C97E5BA5B7B7E86E5ED1AD8AC38`.

Evidence: oversight `evidence/setup-entry-examples.py` and
`evidence/setup-entry-source-receipt.json`. These are UI illustrations, not proof
of clean installation, storage readiness, account creation or recovery behavior.
Owned hidden server26668 exited0 and browser contexts closed after capture.

## Public agenda, captions, contribution and subscription examples (2026-10-03)

Four screenshots from the actual current public React App, WatchScreen,
HomeScreen, HlsPlayer, MeetingAgendaSidebar and PaywallGate with the product
stylesheet. The isolated source copy was hash-equal to the checkout, including
its existing public-App corrections; no product source was changed for capture.
Normal headless Chrome used a 1440 by 1000 viewport on owned localhost port 5197.

All API replies were synthetic GET responses. Unexpected API methods/paths and
other origins failed closed; no credentials, station or real backend were used.
The actual hls.js player received the repository's two-second test segment and
synthetic English/Spanish caption playlists. Meeting metadata and agenda times
are example values, not the test clip's content or duration. The caption-controls
image has Spanish selected; it does not establish translation or caption accuracy.
The subscription example has no plans configured; no email, checkout or payment
was requested. The contribution form contains example details, with no video file
selected, submission sent or agreement accepted. Nothing was saved or published.

- `portal-agenda-sidebar.png`:
  `300e4227f65b6756cf22f62d569b70f45606f19052875251505b6f67d09d8a33`.
- `portal-watch-captions-agenda.png`:
  `e77fa7f8af481ddbc2d437f4a52bbfa30dbbc4ace7cde1402994112a92b6418b`.
- `portal-paywall-gate.png`:
  `d4a196fbb6440cfce0bd98c4ae2975ca0bf7e738aeb545a159cbdc0057efe355`.
- `portal-contribute-form.png`:
  `f40aa478188ef12a74de2cf37253d331d0436a947865511d12675afd35c6cb44`.

Each image was opened and visually inspected before byte-identical copy. No
browser errors, unexpected requests or horizontal page overflow occurred in the
successful run, including 375-pixel watch and home checks. Browser security stayed
enabled; only the development hot-reload client was inert. The finite hidden
owned server and browser closed. Exact source hashes, request inventory and check
receipts are retained in private oversight evidence. These are current-source UI
illustrations, not installed-beta.10, payment, submission or station acceptance.
Refresh them when the visible components change.

## Summary review example (2026-10-03)

`operator-summary-review.png` is the actual SummaryReviewScreen and product CSS
in headless Chrome at 1440 by 1100, without the surrounding shell. The draft,
records-clerk identity and retained source cue are synthetic examples. Selecting
the Source button reads a synthetic generation job; no approval, export, audio,
resident record, station endpoint or credential was used. Unexpected origins and
non-GET APIs were blocked. No browser errors or horizontal overflow occurred.
The image was inspected before byte-identical copy.

Image SHA-256: `8a39ec4ae64eb6c36f484042da358ed7f779d2189a24d9873a915c3af4c4dbb0`.
Component SHA-256: `aec7f74c37e14f011c4db5daa262c9d0a172f8d64a9817d7e8ac699e020c4c5b`.
This is an interface illustration, not live summary or signed-record acceptance.

## Recording, contributor and disabled-paywall examples (2026-10-03)

Four actual current React App/product-CSS captures from synthetic GET-only replies
on owned localhost port 5195 in normal headless Chrome at 1440 by 3000. Actual
element screenshots show the weekly New schedule region, Recordings region,
Contributor submissions screen and Subscription paywall screen. The tall viewport
keeps complete cards visible without editing pixels or hiding overflow.

- `operator-recording-form-weekly.png`: `e18826493df7216de5d025c54daf0d84ad53331e88634c2003bed9c81de688f4`.
- `operator-recording-jobs.png`: `c45aa0376f7aab29f7700159715c46cb2d454bf1919b51ac6eef379a27026f98`.
- `operator-contribute-queue.png`: `e0ad53104e28f4e5160c5d57f0a8c4620e32a31c8cd294a0b0d1ca8a6dc454fb`.
- `operator-paywall-off.png`: `4741b30bdc739b8561789ac4f3d872545eff9bb305509b7f61023ebbc064885f`.

The weekly plan is unsaved, its example SDI preset is not a real detected device,
and its next-fire preview is calculated by the actual component. The active job
and Live-refresh label are synthetic, not a real recording. Contributions use
example identities/text and not-run media gates; no media or agreement was checked.
Paywall is synthetic disabled configuration with no secret. No save, record, stop,
device inspection, review, payment, grant or secret-generation action was performed.
No actual station, backend, credential, resident material or external provider was
accessed. Unexpected/external requests failed closed; all API calls were GET.

Every final PNG was viewed before byte-identical copy. No console errors,
unexpected requests or page overflow; targets fit the viewport. Browser security
remained enabled and only development hot reload was omitted. The finite hidden
server and browser closed. Exact source hashes/scripts are retained privately.
These current-source examples do not establish installed-beta.10 or shipping
artifact currency, hardware operation, persistence, approval or access enforcement.

## Chapter 15 publishing and playback-policy examples (2026-10-03)

Three actual current React App/product-CSS illustrations using synthetic GET-only
replies on owned localhost port 5195. Normal headless Chrome used 1440 by 2600 for
the full nine-surface dashboard and 1440 by 1000 for confirmation/playback policy.
The example recording and every readiness reply are synthetic, not actual station
state. Opening the actual confirmation dialog sends no mutation; it was canceled.
No final approval, retry, policy save, archive or dispatch action ran. No backend,
station, credential, media, provider or actual access decision was accessed.

- `operator-publish-dashboard.png`: `cf2bcf0dcf8eb57c3ff0ddd15aee7a14035fb78ab8233ffd0e3c96ef3e6eb0f6`.
- `operator-publish-confirm.png`: `883367803776dd601cbf567fb4d13c83b8845a18cb15e88f35d4f21cfcaa4c74`.
- `operator-playback-policy.png`: `7775e029994995d6e0664d2a46bebfc519c95864301ab258148fcfa7a38c93a0`.

Each screenshot was viewed before byte-identical copy. The first shorter dashboard
capture was rejected for scroll-area clipping; the taller viewport shows the full
card and approval button. Final runs had no console errors, unexpected requests or
page overflow. All API requests were GET, with unexpected/external requests rejected.
Browser security remained enabled; development hot reload alone was omitted.
Source hash evidence is retained privately. The hidden finite server/browser closed.
These are current-source examples, not installed-beta.10 or shipping-manual proof.

## Alerts empty-state correction (2026-10-03)

`operator-alerts-empty.png` replaces the earlier diagnostic capture below.
SHA-256: `8bc5a8e26cd179ddbe8064bbab23d3f0a69587fea61489ded2074f2f59be74af`.
Actual current AlertsScreen and product CSS, synthetic empty GET replies, normal
headless Chrome at 1440 by 1000. Screen content is shown without the console shell.
The image was opened and visually checked. Its neutral message explicitly says an
empty list does not verify station health. No station or real backend was accessed.
The same UI was exercised at 375 pixels: two synthetic 503 errors, one read-only
Retry alerts request, recovery, and successful empty lists. Only those expected
503 console errors occurred; no page errors, unexpected requests or overflow.
The hidden owned server27052 exited0 and the browser closed. Source AlertsScreen
SHA-256: `c9c2f31286d8cc7c0713ce76a51ecf4753a784e16a740749add4ca6d32140816`.
This is interface evidence, not monitoring or notification delivery acceptance.

## Chapter 14 assets, upload, caption review and lifecycle examples (2026-10-03)

Four actual current React App/product-CSS screenshots, captured in normal headless
Chrome at 1440 by 1000 with synthetic GET-only API replies on owned localhost port
5195. Assets shows three EXAMPLE ONLY recordings and derived statuses. Upload
shows the actual opened panel with no file selected. Review queue shows an example
pending English cue; no cue was decided or audio fetched. Lifecycle Settings
shows empty synthetic watch folders/rules and zero example usage. No station,
backend, actual media, captions, folders, credentials or storage was accessed.
No upload, packaging, review decision, browse/scan, rule or storage action ran.

Image SHA-256 values:

- `operator-assets-list.png`: `714626433ff42c55733a77e64792d945b31eb2deec7d78d7efd8fc551f73a2d4`.
- `operator-assets-upload.png`: `c2c800e3b3b9d050bf7d087eb864097d707ef82f78aec98879a73e7eb4fa894e`.
- `operator-review-queue.png`: `0a07affc27be2b2b4b8625accb82f9492202804e7379df6828d09cf898690b8e`.
- `operator-media-lifecycle-settings.png`: `f368178005c8273dea9e6b60bed432077d40d3fe665b5c2b335a4cd76633ecf0`.

Each screenshot was individually opened and inspected before byte-identical copy.
No console errors, unexpected requests or page overflow occurred. Every API
request was GET; all other origins and unexpected API requests were rejected.
Browser protections remained enabled; only development hot reload was omitted.
The hidden finite owned server and browser closed. Source hashes are retained in
private oversight evidence. These current-source illustrations do not attest to
installed-beta.10, actual readiness or persisted workflow behavior.

## Program guide, Auto-schedule and Federation examples (2026-10-03)

Four actual current React App screenshots with product CSS, captured in normal
headless Chrome at 1440 by 1000 using owned localhost port 5195. The Program guide
shows synthetic recurring slots and log entries; Auto-schedule shows an example
search, daypart, rule and intercepted synthetic Simulate response. Federation
shows synthetic disabled configuration. No station guide was built, rule saved,
program scheduled, configuration read or key generated. No real backend, station,
secrets or stored credentials were accessed. Unexpected requests and all other
origins were rejected. The only POST was the intercepted example preview reply.

Image SHA-256 values:

- `operator-federation-off.png`: `86744c6526ff42103ea551fa885fc144fbfaaf1dcf68d75c9528abe19c827069`.
- `operator-guide-populated.png`: `8c04db4b5ee25bfc4f583b9f3ead92606ef6235db853b2db258c50985a7343b7`.
- `operator-autoschedule-overview.png`: `c53bce11a11c24fc57310f90bd9112bd2ee46c1306e1719606d39dfe2092ff52`.
- `operator-autoschedule-simulate.png`: `f49903be99e3fc9df359c8250b06e12e26f34fc0b966943d9b5ae836734a5fc4`.

Each PNG was individually viewed before copying. No console errors, unexpected
requests or viewport overflow occurred. Source hash receipts and capture scripts
are retained in the private oversight evidence. The finite hidden server and
browser closed after capture. These are current-source illustrations, not proof
of installed-beta.10 behavior or persistence/dispatch behavior. Only development
hot reload was omitted; browser security protections remained enabled.

## Chapter 17 diagnostics and chapter 21 readiness example (2026-10-03)

Four screenshots captured from the actual current React App, SystemHealthScreen,
AlertsScreen and EasScreen with the product stylesheet in headless Chrome at
1440 by 1000. All API responses were synthetic GET replies on owned localhost
port 5195. All other origins and unexpected requests were rejected. No buttons
that run checks, repair, display alerts or change station state were clicked.
No station, real backend, secrets or stored credentials were accessed.

Readiness payloads follow the actual SystemHealthReport and RuntimeSafeToAirStatus
contracts. Visible labels and messages say EXAMPLE ONLY and not live station
status. No automatic channels or channel profiles are configured in the example.
The green Ready state is illustrative, not health, installation or broadcast
acceptance. The Alerts empty state has no configured rules/destinations; it does
not prove notification delivery. The Emergency Alerts example has no sources,
alerts or display decisions; the actual not-an-EAS-device banner remains visible.

Image SHA-256 values:

- `operator-readiness-top.png`: cropped actual top through the readiness card,
  `c1e8ba67f530b9f51d1a8c065d941ab5040dc2a48a3fab6acc122b05ebe80bc9`.
- `operator-health-ready.png`: actual console viewport, referenced by chapter 21,
  `e47f51413d8f5379266c5c879438b01fa76b64cd8341892ca7c0e02df4cdd948`.
- Superseded `operator-alerts-empty.png`: former actual screen element,
  `70599aa0525ef93396e6641bcca28765fec14dfb0580a74bf20d7234d52f6c01`.
- `operator-eas-empty.png`: actual screen element,
  `30ec7b3f87b553234513de32ff7c4f5bba38f05ef3e955ab2249e290087feae1`.

All final PNGs were individually opened and visually inspected before copying.
No console errors, unexpected requests or viewport overflow occurred. Normal
browser security remained enabled; only the development hot-reload client was
omitted. The finite hidden owned server and browser closed after capture.
These current-source examples do not establish installed-beta.10 behavior.
Refresh them when the visible components change.

## Underwriting and App Admin examples (2026-10-03)

Actual current React components and product CSS, captured in headless Chrome at
1440 by 900 pixels with synthetic empty API responses and an example station
profile. These show content without the console shell. The isolated port5196
capture allowed only expected GET requests; no forms were submitted, builds queued,
sponsor records saved, or external stores contacted. Normal browser protections
were retained and development hot reload was inert. Both images were visually
inspected; headings, disabled actions and empty states were visible with no console
errors or horizontal overflow. The owned server and browser closed afterward.

- `operator-underwriting-spots.png`:
  `022cd376aea43070ecb77f4e5bb26c7e11cea5f4957b72151e8cd2fa3d419e97`.
- `operator-appadmin-empty.png`:
  `63cd458debfc6887456d5968b837e6a3331601dc436fbb56f84bc2bcbccf5e3d`.

Component hashes: Underwriting
`6892ba5357c81d3d8a4588e86ed5602eba303e3fdf6a9c34493a679df11e6211`;
App Admin `0d61e768cd8e39ebe88711b9f5e75e85d3ffe4d92073d44b12b9d80de338b42f`.
CSS `b54dfb51d3caf0fb63a509ea4fa114f889cad56dc6709e677cec343efe821db9`.
These illustrations do not establish working sponsorship placement, billing proof,
app builds or store publication. The manual's feature limitations remain in place.

## Chapter 12 schedule examples (2026-10-03)

Captured from the actual current React App, ScheduleScreen, ScheduleDrawer and
DryRunReview, with the product stylesheet in headless Chrome at a 1440 by 1000
viewport. The drawer image captures the actual aside; list and review images
capture the actual ScheduleScreen element without the surrounding console shell.
Each final PNG was opened and visually inspected before copying here.

The isolated frontend served only localhost port 5195. API responses for operator
identity, assets, channel profiles, schedule and prepare-commit were synthetic.
Other origins and unexpected API requests were rejected. The example program
title says EXAMPLE ONLY. The drawer shows America/Denver and a local time preview.
No station or credentials were accessed. No schedule creation, commit, cancellation
or backend operation occurred. The synthetic Safe to air result is not a real
readiness check or approval. Normal browser security remained enabled; only the
development Vite hot-reload client was omitted. No console errors or unexpected
requests occurred; the finite owned server and browser closed after capture.

Image SHA-256 values:

- `operator-schedule-drawer.png`:
  `5fdb6389f85eb48e1aacd1c5fd87b58d4d2da8c20e67c7a59433b5b6acb0376b`.
- `operator-schedule-list.png`:
  `e9b6b242c878354a2fc25c3e6b3abf77233d1a17f7af16e5e6a58ef3f6674024`.
- `operator-schedule-review-safe.png`:
  `98fc41f17c4649ed3691425944b0cb798115895ded07a4577a601d3f1e99acbb`.

Component SHA-256 values: ScheduleScreen
`e306c51de6ea30aeaab0ff279b0cf608c84fcd0accc4fd923000f4e34a9ce274`;
ScheduleDrawer `697ba274a59e931ab17163c5f9b5870df8848de82cf0f7baf600d6dbe510097a`;
CommitToAirPanel `335fff5537f83a19f537ccf15d83150fbbb065da741afc17d457f37853c32957`;
CSS `b54dfb51d3caf0fb63a509ea4fa114f889cad56dc6709e677cec343efe821db9`.
Refresh these illustrations when their visible components change. These captures
do not establish beta.10 installed behavior or freshness of the shipping manual.

## Reports and EPG examples (2026-10-03)

Captured from the actual `ReportsScreen.tsx` and `EpgExportScreen.tsx` components
with the product stylesheet in headless Chrome. The isolated frontend used port
5196, synthetic empty API responses, and no station credentials or resident data.
These images show screen content without the surrounding console shell. A capture
container provides vertical spacing; the screen components were not altered.
They illustrate the interface, not successful report generation or guide export.

- `operator-reports-shows.png`: Shows tab, date/channel filters and empty results.
  SHA-256: `bfe0ebf86f1b10c49cd184af74407c5e988fef94a63b1bb3942181a9757d6bb4`.
- `operator-epg-form.png`: Create export config form and empty configured exports.
  SHA-256: `bc2583e98256fbb76225a9d2b39432a242b6823b70fbfeb2adea3841e8b7e288`.

Both final images were visually inspected. Required headings and controls were
visible, with no horizontal overflow, console errors or unexpected API requests.
Only the isolated origin was allowed; no writes were issued. Normal browser
security protections remained enabled; the development hot-reload client was inert.
The owned server and browser were closed after capture.

Component hashes: Reports `ccb6ae93e1043f6937ddc9fdeac9c871e05b1b67b32b701ab4ecdc0aec89bffb`;
EPG `bce179451fa165eaaf87e4c35ddcfefbf234602302535af590d05fb3143bace4`;
CSS `b54dfb51d3caf0fb63a509ea4fa114f889cad56dc6709e677cec343efe821db9`.
Refresh these illustrations when their visible components change.

## Chapter 11 operator examples (2026-10-03)

These four images were captured from the actual current operator React app and
product stylesheet in headless Chrome, served by an isolated frontend on port
5195. API responses were synthetic examples. Every other network origin and
unexpected API request was rejected. No station, backend, stored credentials or
live recovery kit was accessed. The normal browser security protections remained
enabled; the development-only Vite hot-reload client was omitted.

- `operator-signin-cards.png`: configured-station example, signed out; both actual
  sign-in forms and buttons are visible. SHA-256:
  `d01280d57e7d59ff9a78b522d8c4adfbfd0227044a47714727547e6a001c8d22`.
- `operator-setup-kit.png`: actual setup form and recovery-kit component using
  EXAMPLE ONLY values and eight EXAMPLE-NOT-VALID codes. No save, print,
  acknowledgement or real setup operation was performed. SHA-256:
  `a1265ffc660d1e6c54a0a6b1d5afc9ddc4af623b0e935b3b804e701a9a64ac65`.
- `operator-shell-desktop.png`: actual signed-in shell with six sidebar sections,
  synthetic operator identity and a CURRENT-SOURCE-EXAMPLE version label, at
  1440 by 1000 pixels. SHA-256:
  `9b429682bfc3eaf46ef33af395ecc43bfb98c925a941b78b67ff3bfef65319cd`.
- `operator-manual-contents.png`: actual public Manual screen, title filter and
  grouped contents, at 1440 by 1000 pixels. SHA-256:
  `638aa088a57c1e20f0f7e0bf4a7e12cd26c49a5b42e6c22e4df465d509cdebf1`.

The manual examples used an isolated 635-heading artifact compiled from source
SHA-256 `75cdcd447e4afeff256ce81126cc791da8f57edc39690e849886d637f311aa50`.
Known missing illustrations remain absent from that fixture. It is not the
shipping bundled manual and does not establish installer or live-station behavior.

Captured component SHA-256 values:
SetupScreen `d88351e631aae2b0f365275643963d76013664a5ef02c6ac8ccda9f70b5419fd`;
ManualScreen `614f8b942e597e49cac5137bc0fc4960e3fbf2461a53308e0ed7485fa3b257f9`;
App `0010965d1ea088121da756973cf620b50b9bee1ca0c05b89204a3d1fe92f7895`;
product CSS `b54dfb51d3caf0fb63a509ea4fa114f889cad56dc6709e677cec343efe821db9`.
All four final images were inspected individually. Synthetic signed-out 401
responses were expected; no other browser errors or unexpected requests occurred.
Refresh these examples when their visible components change.

## operator-analytics-telemetry-off.png

Captured 2026-10-03 from the actual operator `AnalyticsScreen.tsx`, rendered by
React with the product stylesheet in headless Chrome at 1440 by 900 pixels.
The screenshot shows the screen content without the surrounding console shell.

The report and rollup API responses were synthetic empty examples, with
`ingest_configured=false`. No station credentials, resident information or live
station state were used. This image illustrates the interface; it is not evidence
that a station's analytics backend was tested. Its caption identifies example data.

Component SHA-256 at capture:
`dfcc33ac1e2bb9a30eeb6f6b3edad2b2c4d1d63bedb002f3345c39a08e38d960`.
The visible telemetry guidance was checked in the browser, the page had no
horizontal overflow at the capture width, and no browser console errors or
unexpected API requests were observed. Refresh this image when that screen's
visible content changes.
# Channels feed, confirmation, takeover and commit examples - 2026-10-03

Captured from actual current React App/HashRouter and product CSS on isolated
localhost port 5195, with synthetic API responses intercepted in headless Chrome.
These are element screenshots, not drawn UI or production-state evidence.
Feed, Stop confirmation and takeover used a 1440 by 1800 viewport; commit review
used 1100 by 1800 to show the natural single-column card without grid stretch.

- `operator-channels-feed.png`: `9b8dd9a3d0570c73e6f14e04341ebe78945308285940df4ae517afd8d25e2a95`.
- `operator-channels-stop-confirm.png`: `f6903b41083371f51edc3a41821c2c8523460982a515b453a5911ed2f92a0cb4`.
- `operator-channels-takeover-live.png`: `28bf54f2afe14e66117f1c6068c8e3e4aecc675ddd5c99b8d5153aa4f44dcd7a`.
- `operator-channels-commit-review.png`: `81f14f820e8270a6d3173f0ff1589c743a0996d6a553e66dc83a6f3452b82e66`.

On-air state, five-minute takeover, operator, source and safety-check result are
examples only. Stop opened only the local confirmation dialog, then Cancel closed
it. Review & prepare used a browser-intercepted synthetic preview POST; it never
reached a backend. No commit, feed command, takeover or return was performed.
No credentials, resident content, station/backend or external provider was accessed.
External/unexpected requests failed closed; all other API requests were GET.
All four images were individually inspected, with no browser errors or horizontal
page overflow. Refresh these illustrations when the visible components change.

Captured source SHA-256: ChannelOpsScreen
`67a8d1ee4151b5ae937adc1f0efc6ebe4da389585e933a7c100963df98fea829`;
TakeoverCard `13b1d2075de8f889e7378907e80289d98f88ab71d4670b440b1ae269e588ee7e`;
CommitToAirPanel `335fff5537f83a19f537ccf15d83150fbbb065da741afc17d457f37853c32957`;
App `0010965d1ea088121da756973cf620b50b9bee1ca0c05b89204a3d1fe92f7895`;
product CSS `b54dfb51d3caf0fb63a509ea4fa114f889cad56dc6709e677cec343efe821db9`.

# Corrected Auto-schedule copy - 2026-10-03

These two captures supersede the earlier Auto-schedule overview/preview images
recorded below. Actual current React App/HashRouter and product CSS were rendered
in normal headless Chrome at 1440 by 1000, on isolated owned localhost port 5195.
All data is synthetic. Only GET replies and the browser-intercepted Simulate
preview POST were permitted; no rule was saved, compiled, approved or dispatched.

- `operator-autoschedule-overview.png`: `13ecaeff20638ab53af50246b12908c6bd7880aca172a97d1334703ce580c784`.
- `operator-autoschedule-simulate.png`: `70593ec440c905a99badbe0e9f0e193c67e29285200a8affb89667e5b50c915e`.

Source AutoScheduleScreen SHA-256
`414efefa9b23165e0a47135ea2dd1dedda54056d6d4fa08382b0ad9c556bbec5`;
App `0010965d1ea088121da756973cf620b50b9bee1ca0c05b89204a3d1fe92f7895`;
CSS `b54dfb51d3caf0fb63a509ea4fa114f889cad56dc6709e677cec343efe821db9`.
Both images were individually inspected. Browser assertions verify corrected
rule approval, scheduled-time and conditional startup/hourly wording, obsolete
commit warnings absent, preview labels present, no errors or horizontal overflow.
No actual station, credentials or resident material was accessed. These images
illustrate source UI, not installed-station or background-worker acceptance.

# Production console examples - 2026-10-03

Four missing illustrations captured from actual React App/HashRouter and product
CSS, rendered in normal headless Chrome on isolated localhost port 5195 at
1440 by 2600. Element screenshots show complete screen content; no pixel editing,
drawn controls or shipping placeholders were used. All data is synthetic.

- `operator-cgboard-bulletins.png`: `ce0656906da01a997917bca6b7a7228616a2214df1c9080b946f90bcd871e90f`.
- `operator-facility-preview.png`: `b296105a5a68ab0694bd0eaa76b912c33b2a71d07062c2e6bb5b005d940bc1f9`.
- `operator-remote-guests.png`: `cefaee9f25cbf7847976d8f51a4b1150c84edaa0fd15863c8b1f9dcf9aff8e98`.
- `operator-controlroom-test-session.png`: `eb8e5dbf7dabbeb05be94f9b32e1415ec0c2f5de1c98ef72cd6e6f128139f9c0`.

CG uses an example template and submitted notice; no moderation or source fetch.
Facility preview POST was fulfilled entirely in the browser with a blocked plan
and documentation-only address. No router or hardware socket was accessed.
Remote room/guest are initial synthetic GET state; no invite or room/guest action.
The Control Room's Open Test Session POST was browser-intercepted, asserting test
mode and no on-air confirmation. No backend session, cue, probe, lock or support
bundle was created. Readiness is explicitly unverified, with no devices/cues.
All remaining API requests were intercepted GET replies; external/unexpected
requests failed closed. No station, credentials, resident data or remote provider
was accessed. Captions identify the exact synthetic boundary. All four final
images were inspected and passed no-browser-error/no-horizontal-overflow checks.

Captured source SHA-256: CgBoardScreen
`ca3bc054405cee686e7bf3253d72ac0629d8de719c76697aefb7a3c8afd6e04e`;
FacilityRouterScreen `17c268eb7ece59e46801f5a848700a5dd9aecc252739513d3f7850827bfbc990`;
RemoteContributionScreen `52f5d5f1f69f740fc6b5f5c83e52e3cf62fbcdd90462a4b58d71da2612494563`;
ControlRoomScreen `ac2b6b05ed4e7ba2443406ac2940630f2d192e0bdfd68702559ee3251b78c5a4`;
App `0010965d1ea088121da756973cf620b50b9bee1ca0c05b89204a3d1fe92f7895`;
CSS `b54dfb51d3caf0fb63a509ea4fa114f889cad56dc6709e677cec343efe821db9`.
Refresh these illustrations when their visible components change.
