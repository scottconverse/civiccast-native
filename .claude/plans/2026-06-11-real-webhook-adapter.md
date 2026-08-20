# Real Webhook Adapter With Durable Retry/Dead-Letter (issue #111 close-out) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** Finish #111's webhook half: real outbound signed POST (timeout, HMAC signature header), durable retry queue with bounded exponential backoff and dead-letter (mirroring the ActivityPub retry worker), redaction tests, and a fake-server integration test. SMTP half shipped in B5.

**Architecture:** New `HttpWebhookClient` (httpx, MockTransport-injectable) registered as `real` under `PROVIDER_KIND_WEBHOOK` — `LocalWebhookClient` mock stays default. Failed real deliveries enqueue a `WebhookRetryRecord` holding only `subscription_id` + payload (the webhook URL and per-subscription secret stay sealed in the subscriptions table; the worker re-opens them at send time, so the queue adds zero plaintext PII). `WebhookRetryWorker` mirrors `ActivityPubRetryWorker` (run_once/run_forever, exponential backoff, dead-letter at max attempts, lifespan ThreadSupervisor behind `CIVICCAST_WEBHOOK_RETRY_WORKER=inline|off`, default inline). Migration `0030_webhook_retry_queue` parents on head `0029_packaged_trim_bookkeeping`.

**Signature contract:** body = canonical JSON (`json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))`) — the exact bytes `sign_payload` HMACs — header `X-CivicCast-Signature: sha256=<hexdigest>`. The mock's signature and the real adapter's signature are identical for the same payload+secret.

**Key files (verified):** `civiccast/subscribe/delivery.py` (protocol + mock), `civiccast/subscribe/crypto.py` (`sign_payload`), `civiccast/subscribe/service.py:201` (`dispatch_notifications`), `civiccast/subscribe/store.py` (protocol + InMemory + Postgres raw-SQL), `civiccast/platform/providers.py` (registry), `civiccast/activitypub/retry_worker.py` (pattern), `civiccast/app.py:222` (`_wire_stage_f_workers`), `civiccast/activitypub/migrations/versions/0026_activitypub_retry_queue.py` (migration pattern).

**Branch:** `work/webhook-real-adapter` from `main`.

---

### Task 1: `HttpWebhookClient` + registry (TDD)

**Files:**
- Create: `civiccast/subscribe/webhook.py`
- Modify: `civiccast/platform/providers.py` (register `real`)
- Test: `tests/subscribe/test_webhook_real.py` (new)

- [ ] Step 1: failing tests — contract (MockTransport: POST, canonical body bytes, `X-CivicCast-Signature: sha256=...` header, returns the same signature `LocalWebhookClient` would), 500 raises `httpx.HTTPStatusError`, error str/repr never echoes the secret sentinel, `WebhookSettings.from_env` rejects non-numeric/<=0 `CIVICCAST_WEBHOOK_TIMEOUT_SECONDS`, registry resolves `real`→`HttpWebhookClient` and default→`LocalWebhookClient`.
- [ ] Step 2: run, expect import error / failures.
- [ ] Step 3: implement:

```python
# civiccast/subscribe/webhook.py
"""Real outbound webhook client (issue #111).

POSTs the canonical signed JSON body with an HMAC signature header.
Selected with CIVICCAST_PROVIDER_WEBHOOK=real; the in-memory
LocalWebhookClient mock remains the default. Per-subscription secrets are
passed in by the caller (sealed at rest); nothing here reads credentials
from the environment, so there is nothing to fail fast about except config.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

import httpx

from civiccast.subscribe.crypto import sign_payload
from civiccast.subscribe.models import NotificationPayload

__all__ = ["HttpWebhookClient", "WebhookSettings"]


@dataclass(frozen=True)
class WebhookSettings:
    timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> WebhookSettings:
        raw = os.environ.get("CIVICCAST_WEBHOOK_TIMEOUT_SECONDS", "").strip()
        if not raw:
            return cls()
        try:
            timeout = float(raw)
        except ValueError as exc:
            raise ValueError(
                f"CIVICCAST_WEBHOOK_TIMEOUT_SECONDS must be a number; got {raw!r}."
            ) from exc
        if timeout <= 0:
            raise ValueError(
                f"CIVICCAST_WEBHOOK_TIMEOUT_SECONDS must be positive; got {raw!r}."
            )
        return cls(timeout_seconds=timeout)


class HttpWebhookClient:
    """Webhook provider satisfying the same protocol as LocalWebhookClient."""

    def __init__(
        self,
        settings: WebhookSettings | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings or WebhookSettings()
        self._transport = transport

    def post(self, *, url: str, payload: NotificationPayload, secret: str) -> str:
        data = payload.model_dump(mode="json")
        signature = sign_payload(data, secret)
        body = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        with httpx.Client(
            transport=self._transport, timeout=self._settings.timeout_seconds
        ) as client:
            response = client.post(
                url,
                content=body,
                headers={
                    "content-type": "application/json",
                    "x-civiccast-signature": f"sha256={signature}",
                    "x-civiccast-asset-id": payload.asset_id,
                },
            )
            response.raise_for_status()
        return signature
```

providers.py: `registry.register(PROVIDER_KIND_WEBHOOK, _REAL_NAME, _real_webhook)` + factory `_real_webhook()` returning `HttpWebhookClient(WebhookSettings.from_env())`.

- [ ] Step 4: tests pass; Step 5: commit `feat(subscribe): real outbound signed webhook client behind provider registry (refs #111)`.

### Task 2: Durable retry queue — model, store, migration (TDD)

**Files:**
- Modify: `civiccast/subscribe/models.py` (WebhookRetryState + WebhookRetryRecord — pydantic only, subscribe store is raw-SQL)
- Modify: `civiccast/subscribe/store.py` (protocol + InMemory + Postgres methods: `enqueue_webhook_retry`, `get_webhook_retry`, `due_webhook_retries(now)`, `save_webhook_retry`, `list_webhook_retries`)
- Create: `civiccast/subscribe/migrations/versions/0030_webhook_retry_queue.py` (revises `0029_packaged_trim_bookkeeping`; table `subscription_webhook_retries`: retry_id PK String(120), subscription_id String(160) indexed, payload_json Text, state String(20) default pending + CHECK (pending/delivered/dead_letter), attempts Integer default 0, next_attempt_at DateTime(tz) nullable, last_status_code Integer default 0, last_error Text default '', created_at/updated_at DateTime(tz) CURRENT_TIMESTAMP — copy the 0026 pattern incl. `_use_schema()`)
- Test: `tests/subscribe/test_webhook_real.py` (InMemory) + Postgres-gated store test mirroring `tests/activitypub/test_activitypub_persistence.py`'s gating fixture

NOTE: the queue stores subscription_id + payload only — never the webhook URL or secret (those stay sealed in the subscriptions table; reopened at send time). State the reason in the migration docstring.

- [ ] Step 1 failing tests → Step 2 run → Step 3 implement → Step 4 pass → Step 5 commit `feat(subscribe): durable webhook retry queue (migration 0030) (refs #111)`. Verify single alembic head stays `0030_webhook_retry_queue` (`alembic heads` via the repo config or the existing single-head test).

### Task 3: Worker + dispatch wiring (TDD)

**Files:**
- Create: `civiccast/subscribe/retry_worker.py` — mirror `civiccast/activitypub/retry_worker.py`: `WebhookRetrySettings.from_env` (`CIVICCAST_WEBHOOK_RETRY_WORKER` inline|off default inline; `CIVICCAST_WEBHOOK_RETRY_POLL_SECONDS` 60; `CIVICCAST_WEBHOOK_RETRY_BACKOFF_SECONDS` 120; `CIVICCAST_WEBHOOK_RETRY_MAX_ATTEMPTS` 8), `enqueue_failed_webhook_delivery(...)` (attempt 1 = original send), `WebhookRetryWorker(store, webhook_client, secrets, settings)` with run_once/run_forever/_attempt. `_attempt`: `store.get(subscription_id)`; missing or status != "confirmed" → dead_letter immediately (never notify unsubscribed endpoints — note why); else open handle + secret via `secrets.secret_box.open(...)` (aad patterns from service.py: subscription_id and f"{subscription_id}:secret"), `client.post`, success → delivered, failure → exponential backoff, max → dead_letter. Retry IDs `swr_` + token_urlsafe.
- Modify: `civiccast/subscribe/service.py` `dispatch_notifications`: webhook send in try/except Exception → `failed` count + `enqueue_failed_webhook_delivery` + a `status="failed"` NotificationDelivery ("webhook delivery failed; queued for retry"). `delivery_proof` gains `status: Literal["sent","failed"] = "sent"` param. Mock path unchanged (mock never raises).
- Modify: `civiccast/app.py` `_wire_stage_f_workers`: third ThreadSupervisor `civiccast-webhook-retry-worker` with `WebhookRetryWorker(PostgresSubscribeStore(session_factory), default_registry().resolve(PROVIDER_KIND_WEBHOOK), load_subscription_secrets(), settings=...)`, enabled when mode inline.
- Test: worker success/backoff/dead-letter/unsubscribed paths with InMemory store + MockTransport + injected `now`; dispatch-failure test (real client w/ failing transport → failed=1, row queued, mailbox unaffected); settings validation.

- [ ] TDD steps as above; commit `feat(subscribe): webhook retry worker with backoff + dead-letter, dispatch queues failures (refs #111)`.

### Task 4: Fake-server integration test

- [ ] Loopback `http.server` thread (mirror `_LoopbackSmtpServer` in tests/platform/test_real_providers.py) that captures one POST; `HttpWebhookClient` (no MockTransport) delivers to `http://127.0.0.1:<port>/hook`; assert HMAC of received body with the shared secret equals the signature header. Commit `test(subscribe): loopback fake-server webhook integration proof (refs #111)`.

### Task 5: Docs truth, gates, PR

- [ ] CAPABILITIES.md: update the subscriber-webhook row honestly (real adapter config-gated `CIVICCAST_PROVIDER_WEBHOOK=real`, contract+loopback tested, not field-proven against external endpoints). Check docs/ops/cdn-and-providers.md + background-workers.md for webhook/worker mentions and extend (new envs).
- [ ] Regenerate OpenAPI artifacts if any API surface changed (none expected — dispatch response shape unchanged).
- [ ] Full gate: `pytest -q` with `CIVICCAST_POSTGRES_TEST_URL` + ffmpeg → 0 failed. Alembic single head = 0030.
- [ ] Push, PR (`closes #111`), merge per standing authority.

---

## Self-review
- Issue #111 webhook tasks: real outbound POST ✔ (T1) signing ✔ (T1) timeout ✔ (T1) retry/backoff ✔ (T3) persistence ✔ (T2) dead-letter ✔ (T3) redaction tests ✔ (T1) fake-server integration ✔ (T4) CAPABILITIES ✔ (T5). SMTP tasks were shipped in B5.
- PII rule held: queue rows carry no plaintext URL/secret.
