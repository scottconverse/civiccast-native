# CivicCast Operator Language Guide

This guide pins the vocabulary for the operator product layer. Use it in the
installer, operator console, README, FAQ, user manual, API narrative copy, and
support docs.

## Audience Terms

| Use | Meaning | Avoid |
| --- | --- | --- |
| Station | The CivicCast deployment for one organization or channel. | Tenant, instance |
| Admin | The person who installs, updates, configures, and recovers CivicCast. | Superuser, root user |
| Meeting operator | The person running the broadcast during a meeting. | Staff user, end user |
| Records clerk | The person reviewing captions, summaries, records, and publish approval. | Reviewer actor |
| Resident | A public viewer or subscriber. | Consumer, anonymous user |
| IT help | A technical helper, vendor, or support engineer. | Admin intervention required |

## Product Verbs

| Use | Meaning | Avoid |
| --- | --- | --- |
| Broadcast | Send live or recorded meeting video to residents. | Ingest, stream session, live pipeline |
| Publish | Make approved records, replays, captions, summaries, feeds, and notifications public. | Syndicate, finalize artifact |
| Review | Check captions, sourced claims, and records before approval. | Moderate unless it is ActivityPub moderation |
| Archive | Preserve an approved copy for retention. | Deep storage, object lifecycle |
| Set up | Add the account, credential, source, or path needed for a feature. | Configure env vars |
| Proof | Run an automated test or manual verification that a system state or feature works. | Validation, evidence collection |
| Preflight | Check system health and required settings before starting a broadcast. | Pre-flight check, health scan |
| Recovery kit | The printable or saved emergency sheet from first-admin setup. | Token dump, break-glass secret |

## Readiness States

| Use | Meaning | Avoid |
| --- | --- | --- |
| Ready | Required checks passed for the selected action. | ok, complete, pass |
| Check before meeting | Something optional or recoverable needs attention. | warning, degraded |
| Do not broadcast yet | A required check failed for tonight's broadcast. | failed, error |
| Not set up yet | Optional provider or feature has no credential or proof. | blocked, credential_or_secret_required |
| Needs IT help | The next step requires admin, shell, certificate, database, or service work. | mTLS, NATS, DATABASE_URL, ACL |

When a machine contract still uses exact enum values, keep those values in API
responses and generated docs. Translate them at the product layer before they
reach non-technical copy.

## Caption And Record Terms

| Use | Meaning | Avoid |
| --- | --- | --- |
| Auto-generated captions | Captions produced by the local model and not yet reviewed by a person. | AI captions, raw captions |
| Reviewed captions | Captions a records clerk approved or edited. | Approved captions, verified captions |
| Sourced summary | A summary where each quantitative claim links back to transcript evidence. | Cited summary, annotated summary |
| Signed record | A CivicCast export with integrity metadata and approval history. | Sealed record, certified export |
| Legal record claim | A jurisdiction-specific claim that requires station legal review. | Jurisdiction claim, legal requirement |

## Required, Optional, And Advanced

Use **required** only for checks that prevent the selected action.

Use **optional** for provider lanes such as YouTube, ActivityPub, subscriber
notifications, podcast, or additional archives when the station has not chosen
them for the meeting.

Use **advanced** for certificate rotation, NATS, mTLS, ActivityPub policy,
manual model imports, and command-line proof collection. Advanced does not
mean unsafe; it means a meeting operator should not have to handle it.

## Error Copy Shape

Operator copy should answer three questions:

1. What happened?
2. Can we still broadcast or publish?
3. What is the next human action?

Examples:

- "YouTube is not set up yet. You can still publish to the resident portal and
  archive. To add YouTube, open Setup, save the station account details, then
  run live proof before using it for residents."
- "Camera audio is missing. Do not broadcast yet. Check the camera input, then
  run preflight again."
- "The archive drive needs IT help. You can rehearse, but do not approve a
  public record until storage is fixed."

## Scope Guard

This is a product-language contract, not a permission model and not a release
claim. If a feature is only designed or contracted, say so. Do not say it works
until the implementation and proof exist.
