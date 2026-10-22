# Sprint 6 station federation console receipt

Scope: the operator screen and typed client for administrator-configured station
peers. The backend and its two-station API checks are recorded in
[station-federation.md](station-federation.md). This receipt does not cover the
separate CivicSuite integration contract.

Acceptance: permitted staff can choose a configured station, browse published
programs through public watch links, and read shared channel status. Only a
setup administrator or meeting operator sees Start/Stop controls. Both actions
require confirmation naming the station and channel. A successful command
displays queue acceptance and directs staff to refresh status; it never changes
the displayed channel state optimistically. A failed command closes its dialog
and asks staff to refresh before retrying. Catalog and channel failures can be
retried independently. Empty configuration and absent control credentials have
explicit states. No URL, token or credential entry is present.

Files:

- `civiccast/apps/portal-operator/src/api/federation.ts`: fixed local API routes,
  encoded identifiers, typed projections, explicit confirmed Stop body.
- `civiccast/apps/portal-operator/src/screens/StationFederationScreen.tsx`:
  `StationFederationScreen` export, shared identity query, role checks,
  configured station selection, catalog/status, confirmations and queue receipt.
  Playback links require HTTPS, no credentials and the configured public origin.
- `civiccast/apps/portal-operator/src/screens/StationFederationScreen.test.tsx`:
  four executable UI behavior checks with the existing React Query/router setup.
- `docs/manual/src/26-integrations.md`: operator flow and setup-guide link at
  `station-federation`; coordinator owns assembled manual and Help output.

Coordinator owns navigation wiring: `/stations`, navigation ID `stations`, label
**Other stations** in **Run meeting**. Read roles are `setup_admin`,
`meeting_operator`, `support_admin`, `publish_operator`; command roles are the
first two. Backend enforcement remains authoritative.

## Commands and outcomes

Working directory for commands below:
`civiccast/apps/portal-operator`.

The first baseline attempt could not locate Vitest because local dependencies
were absent. `npm ci --ignore-scripts --no-audit --no-fund` installed 281 locked
packages; no dependency or lockfile changes were made.

- Baseline `npm run test:unit -- src/screens/StationImportScreen.test.tsx`:
  **2 passed**, 958 ms.
- RED `npm run test:unit -- src/screens/StationFederationScreen.test.tsx`:
  **4 failed**, 4.79 s against a minimal heading-only screen. Failures were
  missing access, empty-state, watch/control and retry behavior, not import errors.
- Initial implementation: three passed and one failed because the new test
  incorrectly expected React Query mutation context as an extra argument to an
  explicitly wrapped client call. Corrected the assertion to the actual three
  arguments. The next run found a test matcher unsupported by this repository;
  changed it to the existing Chai-compatible `textContent`/`toMatch` assertion.
- `npm run test:unit -- src/screens/StationFederationScreen.test.tsx src/screens/StationImportScreen.test.tsx`:
  **6 passed**, 1.20 s. Checks cover denied roles without station requests, empty
  peer configuration, published playback URL, confirmation before command,
  queued receipt with unchanged reported state, explicit status refresh, read-only
  staff controls, and independent catalog recovery.
- `npx tsc -p tsconfig.app.json --noEmit`: **exit 0** after correcting the
  unsupported matcher (the preceding typecheck identified that matcher only).
- After the small failure-dialog and semantic definition-list corrections,
  `npm run test:unit -- src/screens/StationFederationScreen.test.tsx`:
  **4 passed**, 1.12 s.
- `npx eslint src/api/federation.ts src/screens/StationFederationScreen.tsx src/screens/StationFederationScreen.test.tsx`:
  **exit 0**, including the final screen corrections.
- Scoped `git diff --check`: **exit 0**.

Independent backend read review traced `civiccast/federation/{models,service,router}.py`
to the actual public asset and staff egress routes. No material defect found:
only administrator configuration selects origins, credentials are sent solely
to the configured staff origin, public requests have no credentials,
redirects/environment proxies are disabled, HTTPS uses normal certificate
verification, local roles/actions/channels are constrained, remote roles still
apply, error bodies are sanitized, responses/time are bounded and queue
acknowledgements are checked for the selected channel and action. Private HTTPS
LAN peers are intentionally allowed by the administrator trust model. This is a
source review, not deployed TLS or device verification. The coordinator performs
the independent frontend review.

Limits: these UI checks mock the API; the backend receipt separately covers
actual two-ASGI-application requests and the existing queue. No live station,
credential, service configuration, on-air output or installed application was
changed. No frontend production build, new general harness or broad suite was
run. Browser layout and deployed cross-machine operation are not claimed.

proved: four new UI behavior checks passed; TypeScript and scoped ESLint clean · lane: Critical
