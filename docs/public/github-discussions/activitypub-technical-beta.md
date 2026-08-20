# Historical GitHub Discussion Seed: v2.1.0 ActivityPub Technical Beta

> Historical seed for the v2.1.0 line. Use the current
> [v1.0.0-rc18 community seed pack](v1.0.0-rc18-community-seed-pack.md) for
> release-facing posts.

Category: Ideas or Q&A

Title: CivicCast v2.1.0 ActivityPub technical beta: who can test default-off federation?

Body:

CivicCast v2.1.0 includes a default-off ActivityPub station actor for
technical beta testing. Enabled deployments require an explicit public base
URL, generated station key, and a selected policy mode. The recommended first
posture is `approval-only` plus authorized fetch.

This is not enabled during the normal non-technical beta install. Turn it on
only when you have a controlled target instance, a moderator/operator ready to
watch the Federation screen, and a plan for redacting logs before sharing them.

What we need from testers:

- A controlled target instance or lab server.
- Confirmation that WebFinger resolves the station account.
- A signed follow request that appears in the operator console Federation
  screen.
- Operator approval, rejection, and blocking feedback.
- Redacted delivery evidence for signed `Accept`, `Reject`, and publish
  `Create` activities.

Please do not post private keys, tokens, private moderation-account details, or
resident data. Share versions, commands, sanitized logs, and screenshots only.

ActivityPub remains an optional provider lane for early adopters. A successful
target-instance proof should not be used as a broad public-fediverse
interoperability claim until the exact target and redacted evidence are named.
