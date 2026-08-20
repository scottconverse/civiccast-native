# Subscriber Privacy

This document records the subscriber and podcast privacy posture for current
CivicCast beta deployments.

## Scope

Current subscriber delivery covers email double opt-in, RSS feeds, webhook
notifications, and podcast RSS. ActivityPub federation is a separate
operator-gated station-actor surface and is disabled by default on fresh
installs.

## Subscriber Data At Rest

Subscriber email handles and webhook secrets are encrypted before persistence.
New installs generate or load deployment-specific secret material from
`CIVICCAST_SUBSCRIBE_SECRETS_FILE`, `CIVICCAST_CONFIG_DIR`, or the default user
configuration directory.

Do not use deterministic subscriber secrets for a real station. They are test
fixtures only. Existing deployments that need to read historical v0.8 local
proof tokens must opt in with `CIVICCAST_SUBSCRIBE_ACCEPT_V08_LEGACY_SECRETS=1`
only for the migration window.

Secret rotation is additive first: introduce the new current secret, keep prior
secrets in the legacy list until old confirmation and unsubscribe links expire,
then remove the retired legacy entry. This prevents existing residents from
being bricked during a rotation.

The public API never returns raw subscriber handles or webhook secrets. Staff
proof endpoints report delivery state and troubleshooting details without
exposing subscriber PII.

## Delivery Tracking

Email notifications use a deterministic local mailbox in v0.8. The local
adapter records delivery metadata for proof and tests, but it does not add
remote images, tracking pixels, third-party trackers, or cross-site analytics.

Webhook notifications include HMAC signature headers. Receivers can recompute
the signature over the exact payload body and reject tampered messages.

## Resident Controls

Residents must confirm email subscriptions through a signed token before
notifications are sent. Unsubscribe links are also signed and can be used
without a staff login. Invalid or expired tokens return actionable public
portal copy instead of exposing internal subscriber state.

## Operator Rules

- Do not export subscriber handles from the database for manual mailing.
- Do not paste webhook secrets into tickets, screenshots, or release evidence.
- Do not add remote-image tracking pixels to notification templates.
- Do not treat RSS readership as personally identifiable analytics.
- Keep `/api/staff/subscribe/*` behind loopback or an authenticating proxy,
  following `docs/ops/staff-route-protection.md`.
