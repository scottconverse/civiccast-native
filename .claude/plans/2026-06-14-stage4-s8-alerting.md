# Stage 4 (build step 4) — S8: Operational Alerting + Runtime Safe-to-Air

**Branch:** `work/3.0-gstreamer-engine` · **Spec:** `docs/spec/3.0/sections/S8-health-alerting-support-updates.md`
**Started 2026-06-14** after S9 (build step 3) closed & pushed (`9241e78`).

## Goal
An unattended single-PC PEG box must **call for help when it goes off-air**. Today health is pull-only.
S8 adds: push alerting (email/SMS/webhook to the operator), a continuous runtime safe-to-air signal, the
QA-004 sink-health correctness fix, a consolidated system-health dashboard + support bundle, and the
update-check/self-test surfaces. S8 is the **routing hub** every other section hands conditions to via
`record_alert_condition(kind, resource, detail, resolved=False)`.

## MIGRATION — locked
`0039_alerting_and_sinkhealth` (down_revision = the current head `0038_reliability_fields`). The spec's
planned `0042` is superseded by as-built numbering (see RECONCILIATION + HANDOFF, reconciled 2026-06-14).
Adds the persisted alerting tables + SystemResourceSample + SystemSelfTest; RuntimeSafeToAirStatus /
ChannelRuntimeStatus are computed (not persisted). Batch-alter / create_table with `schema=schema`,
SQLite+multi-schema safe (mirror 0038); a real up+down reflection test (mirror test_migration_0038).

## Cross-section seam (the hub)
`record_alert_condition` is the ONLY way other sections raise an operational condition. S9's
restart-escalation proof event (`daemon._append_restart_escalation_event`, source_path
`ffmpeg-child:restart-escalation`) is the first upstream producer → maps to `encoder-death`/`relay-blocked`.
Other producers (S2 compliance, S4 commit, S5 takeover, S7 missing-media, S13 ai-runtime) land as their
sections build — S8 ships the hub + the conditions it self-derives (off-air / encoder-death / server-crash).

## Slices (audit-lite per slice → 0/0/0/0/0 → commit; /walkthrough + /audit-team at stage close)
- **S8-1 — QA-004 sink-health fix (headline correctness, self-contained).** `egress/health.py`
  `build_default_sink_health(*, config, metrics, state)`: require encoder progress ONLY when
  `state == "ON_AIR"`; idle-on-slate UDP = healthy (not a disconnection); ON_AIR-with-no-metrics = False
  (a real, observable stall). Thread `state=` from the daemon health sampler. Update all callers + tests.
  Blast radius: daemon `_append_health`/`_sink_connected`, any test asserting sink_connected on slate.
- **S8-2 — models + migration 0039 + enums + `record_alert_condition` store.** AlertSeverity/
  AlertConditionKind/AlertChannelKind/AlertDeliveryStatus/AlertEventState/SelfTestKind/SafeToAirColor;
  AlertRule/AlertChannel/AlertEvent/AlertEventDelivery + SystemResourceSample + SystemSelfTest (pydantic +
  ORM); the §6.2 default-rule seed; store CRUD + the condition-ingest API (in-process).
- **S8-3 — evaluator (dedupe / rate-limit / resolve) in the daemon loop.** Self-derive off-air/
  encoder-death/server-crash from EgressStateRow + post-QA-004 sink health + a clean-shutdown marker;
  notify-on-first-failure + re_alert_after + resolve + quiet-hours hold (critical ignores quiet hours).
  Wire S9's restart-escalation event into the hub.
- **S8-4 — delivery (reuse subscribe/ patterns, SEPARATE stack).** email (SMTP) / sms (Twilio-shaped) /
  webhook (HMAC-signed); bounded-backoff retry + dead-letter; dead-letter surfaces as a warning (failure
  to alert is never silent). No PII crossover with resident `subscribe/` tables.
- **S8-5 — runtime safe-to-air + system resources/self-test/updates + dashboard + support bundle + UI.**
  RuntimeSafeToAirStatus/ChannelRuntimeStatus (cached ~3-5s, reuse SafeToBroadcastColor); SystemResourceSample
  sampler (psutil, reuse installer/platform+storage); daily/weekly SystemSelfTest; hourly update check +
  release-notes (extend build_update_rollback_status) wired to alerts; extend create_diagnostic_bundle with
  alert/health/proof/self-test/resource windows; SystemHealthScreen alerting config + dashboard + runtime
  safe-to-air badge (vitest component coverage for new UI). `/walkthrough` applies (UI surface).

## Discipline
[[no-false-greens]] [[do-it-right-no-shortcuts]] [[fix-all-severities-zero-audit]] — every claim verified;
nothing half-built at a slice boundary. Agents at discretion, capped + tracked ([[no-subagents-without-permission]]).
Tests: Windows egress suite + the real-Postgres path (portable PG :5433) for store/router; a migration
reflection test; the evaluator dedupe/resolve/quiet-hours as deterministic unit tests with an injected clock.

## Open decisions (spec §10.2 — defaults chosen, veto-able)
OD-2 quiet-hours hold (not drop); OD-4 daily self-test 02:00; OD-5 weekly Sun 03:00; OD-6 no silent
auto-install; OD-7 share-vs-copy the webhook-signing helper (default: copy into an alerting `delivery`
module so operator/resident stacks never share a table). SMS provider = pluggable adapter (no account wired;
LPM/operator supplies credentials — matches the "build to spec, verify code, no online accounts" directive).
