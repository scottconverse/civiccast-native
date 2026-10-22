<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Sprint 6: resident webhooks and Roku input

Source review and implementation completed on 2026-10-17 in
`fix/beta19-ci-and-install-docs`, based on
`b6f7f6f3b33f51c0cd7e4254e2e4853ba1c65f51`. These results cover the uncommitted
subscription/Roku changes in the shared working tree, not a signed installer
or a released candidate. Other agents' changes were preserved.

## Behavior

Webhook registration delivers its confirmation token and a random 32-byte
signing secret only to the registered HTTPS endpoint. The public response
exposes neither. The endpoint must explicitly confirm before notices send.
Pending re-registration rotates the saved secret and token, invalidating the
previous challenge. Already-confirmed current registrations remain intact.
Old identifier-derived secrets are blocked on confirmation, immediate delivery
and retries; those endpoints must register and confirm again. Email behavior
is preserved.

The real webhook transport rejects non-public destinations, including mixed
public/private DNS answers, pins the connection IP, preserves the original
Host and TLS SNI, and disables redirects and environment proxies. Installed
HTTPcore source confirms that `sni_hostname` reaches TLS `wrap_socket` as
`server_hostname`; the existing verified SSL context remains in use.

Roku scene arguments trigger a callback after startup and on running-app
`roInputEvent` messages. The callback keeps a pending request until the catalog
is ready, then consumes it once. Main receives input events on its existing
message port. No release package was created.

## Focused verification

Commands were run from the repository root unless otherwise stated.

Baseline:

```powershell
.venv\Scripts\python.exe -m pytest tests/subscribe/test_webhook_real.py tests/subscribe/test_subscribe_service.py tests/subscribe/test_subscribe_router.py tests/subscribe/test_double_optin_is_real.py tests/apps/test_ott_native_empty_states.py -q
```

Result: `38 passed in 10.97s`.

Initial bug reproductions:

```powershell
.venv\Scripts\python.exe -m pytest tests/subscribe/test_subscribe_service.py::test_webhook_signup_does_not_return_endpoint_ownership_proof tests/subscribe/test_webhook_real.py::TestHttpWebhookClient::test_refuses_private_destination_before_transport -q
```

Result before implementation: `2 failed in 2.09s`. The first assertion found
the confirmation token in the caller's response; the second observed that a
private destination reached the injected transport without rejection.

Final affected checks:

```powershell
.venv\Scripts\python.exe -m pytest tests/subscribe tests/publish/test_subscriber_notification_delivery.py tests/apps/test_ott_native_empty_states.py -q
.venv\Scripts\python.exe -m ruff check civiccast/subscribe tests/subscribe/test_subscribe_service.py tests/subscribe/test_webhook_real.py tests/publish/test_subscriber_notification_delivery.py
git diff --check -- civiccast/subscribe civiccast/apps/ott-native/roku tests/subscribe/test_subscribe_service.py tests/subscribe/test_webhook_real.py tests/publish/test_subscriber_notification_delivery.py docs/ops/cdn-and-providers.md docs/manual/src/26-integrations.md
```

Results: `126 passed in 23.74s`; `All checks passed!`; scoped diff check exit 0
with no output. No warnings in the final pytest result. The affected tests
cover endpoint-only provisioning, consent before delivery, signature integrity,
unsafe URL/DNS rejection, connection IP/Host/SNI preservation, redirect refusal,
legacy-key refusal on both delivery paths, and saved challenge rotation using
the actual `0014_subscribe_v08` migration and SQL-backed store.

An intermediate loopback integration failure was corrected by mapping a public
test URL to the existing loopback server through an injected test transport;
the real-socket signature assertion remains. An intermediate persistence-test
failure (`no such table: subscriptions`) was a fixture omission: the original
retry fixture created only ORM tables. It now applies the actual subscription
migration before exercising registration. Final results above include both.

From `civiccast/apps/ott-native/roku`:

```powershell
npm ci --ignore-scripts --no-audit --no-fund
npm run check
```

The locked local tooling install added 134 packages; package-lock was unchanged.
`npm run check` ran `bsc --project bsconfig.json`: parsing and project validation
completed, exit 0. The initial offline tooling probe returned `ENOTCACHED`;
installing the missing routine tooling resolved it.

## Review and limits

The coordinating agent independently reviewed the webhook trust boundaries
and reported no remaining material security finding. No external receiver TLS
round trip, production subscription delivery, Roku device/emulator playback,
installer build, push or deployment was performed. Roku evidence is syntax
validation and traced event wiring, not device behavior.

Separate read-only review of the preparer changes found two issues and sent
them to the coordinator/coder: the shared video-copy cache could be cleared
between membership check and final indexing, producing `KeyError`; and an
already-queued opportunistic warm is deduplicated before it can be promoted
when its asset enters an upcoming plan. These findings concern the separate
preparer work and are not fixed or certified by this receipt.

proved: 126 affected tests, Ruff and Roku bsc passed · lane: Critical (security).
