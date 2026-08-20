# S26 — Subscription Paywall (OPTIONAL, V1.x)

**Status:** SHIPPED 2026-06-18 · CivicCast 3.0 · Authored 2026-06-14 · Closes S18 gap C (migration `0059_paywall_access`; chain HEAD is now `0060_recording_paywall_merge` after S21's `0056` sibling shipped 2026-06-18 and the merge revision unified the heads) · **OPTIONAL / default OFF**
**Migration note:** renumbered from planned `0057` → `0059` per RECONCILIATION D19 after S23 took the on-disk `0055`; reconciled 2026-06-18.
**Scope:** Gate selected VOD/live behind an email **magic-link** + Stripe subscription
**Functional target:** an incumbent PEG platform's subscription workflow Subscription Paywalls (Stripe magic-link)
**Owning section:** public portal (+ S12 OTT) · reuses the real-provider adapter pattern (v2.1 B5)
**Priority:** **niche, V1.x-optional** (S18 D19) — do **not** build before the core. Default OFF; most PEG content stays free/public.

---

## 1. Goal & rationale (and why it's optional)

Some stations want to monetize premium content (e.g., exclusive HS sports) to offset declining franchise fees — an incumbent PEG platform added Stripe magic-link paywalls in 7.10. It's a **revenue nicety, not a parity essential**, and it introduces payment handling, so it ships **last, default OFF**, and only via **Stripe-hosted Checkout** (no card data ever touches CivicCast → PCI SAQ-A scope).

---

## 2. Current state
`paywall`/`stripe` ≈ 1 hit (effectively absent). The real-provider adapter framework (B5: `CIVICCAST_PROVIDER_*`, mocks-by-default) is the integration pattern to reuse.

---

## 3. Entities & migration `0059_paywall_access`
```python
class PaywallConfig(BaseModel):
    config_id: Slug
    station_id: Slug
    enabled: bool = False              # DEFAULT OFF
    provider: Literal["stripe"] = "stripe"
    tiers: list[dict] = []             # {tier_id, name, price_id (Stripe), interval}
    signing_secret: str | None = None  # per-station HMAC secret; signs magic-link tokens AND
                                       # verifies Stripe webhook signatures (separated in a future
                                       # slice if these concerns diverge — see Q-3 close-out in the
                                       # S26 gauntlet)

class AccessGrant(BaseModel):          # email magic-link → access
    grant_id: Slug
    email: str
    scope: str                         # asset_id | series_id | "all"
    granted_via: Literal["subscription","comp","magic_link"]
    expires_at: datetime | None

class Subscription(BaseModel):         # mirror of Stripe state (source of truth = Stripe)
    sub_id: str                        # Stripe subscription id
    email: str
    tier_id: str
    status: Literal["active","past_due","canceled","incomplete"]
    current_period_end: datetime
```
Migration `0059_paywall_access` adds `paywall_configs` + `access_grants` + `paywall_subscriptions` (the subscriptions table is prefixed `paywall_` on disk to avoid collision with a future generic `subscriptions` table — the in-process pydantic model keeps the unprefixed `Subscription` class name). Sequences after `0058_meeting_agenda` (S25). Gated entirely behind `enabled=false` so a station that never turns it on carries empty tables + zero behavior change.

---

## 4. API surface
```
GET/PATCH  /api/staff/paywall/config                 # configure tiers, enable/disable
POST       /api/public/paywall/checkout              # → Stripe-hosted Checkout session (no card data here)
POST       /api/public/paywall/magic-link            # email a sign-in link
GET        /api/public/paywall/verify?token=         # redeem magic link → session
POST       /api/webhooks/stripe                       # signed webhook → update Subscription/AccessGrant
GET        /api/public/paywall/access?asset_id=       # does this session have access?
```
Roles: `setup_admin` on every `/api/staff/paywall/*` route (config GET/PUT/PATCH/DELETE + grants POST + grants DELETE); public endpoints rate-limited; webhook signature-verified.

Tier price ids are **existing** Stripe-side price ids the operator already created in the Stripe dashboard — CivicCast never creates Stripe prices, customers, or products from the operator UI. Keeping price/tax/refund settings in the Stripe console keeps the PCI SAQ-A scope intact and avoids dragging revenue config (tax codes, currency, refunds) into CivicCast.

## 5. Operator UI
- **Paywall config** (`/portal-operator/paywall`): enable toggle (default off), define tiers (mapped to Stripe price IDs), mark which series/assets are gated, comp-access grants.
- **Viewer flow**: gated item → "subscribe or sign in" → Stripe Checkout / magic-link email → access.

## 6. Behavior / algorithm
- **Default OFF**: when `enabled=false`, all content is public and the paywall code path is inert.
- **Gating**: a gated asset checks `AccessGrant`/`Subscription` for the session's email; no access → Checkout/magic-link.
- **Stripe-hosted only**: Checkout + Customer Portal are Stripe-hosted; **no card data on CivicCast servers** (PCI SAQ-A). Stripe is the source of truth; the signed webhook reconciles `Subscription`/`AccessGrant`.
- **Magic-link**: short-lived signed token emailed (reuse the SMTP provider from B5); redeem → session.
- **Self-hosted ethos preserved**: this is opt-in monetization, not a required cloud tollbooth; a station can ignore it entirely.

## 7. Proof tier + testable DONE-criteria
| # | Done-criterion (testable) | Proof |
|---|---|---|
| DC-1 | With `enabled=false`, all content is public and no paywall path executes (default-off regression). | contract |
| DC-2 | A gated asset denies a no-grant session and allows a valid subscription/magic-link session. | contract (mock provider) |
| DC-3 | Stripe webhook (signed) updates Subscription→AccessGrant; bad signature rejected. | contract |
| DC-4 | No card/PAN data is ever stored or logged (grep guard + redaction test). | contract |
| DC-5 | Magic-link tokens are short-lived, single-use, signed. | contract |

Proof tier: **contract** (mock provider) → lab (with a real Stripe test key). Mocks-by-default like B5.

## 8. Test plan
Unit: gating logic, default-off inertness, magic-link token lifecycle, webhook signature. Security: no-PAN-storage redaction test (like #122). API: config + public flow with the mock provider. Coverage >80%; audit 0/0/0/0/0. **Met** — per `gate-civiccast-s26-2026-06-18/` (full GauntletGate, 2026-06-18): tests/paywall green, audit 0/0/0/0/0 across the 5 lanes after the docs/UI/backend fix-up passes; cite the gate directory's executive report for the final tally.

## 9. Dependencies & cross-references
Public portal (gating) · S12 (OTT gating, if enabled there) · B5 real-provider pattern + SMTP · S25 (a paywalled meeting still shows its public agenda). **Build AFTER the core — V1.x.**

## 10. DONE when
DC-1…DC-5 pass; migration `0059`; default-off verified; Stripe-hosted (no PCI scope creep); audit 0/0/0/0/0; index/RECONCILIATION reference S26/`0059` marked optional.

Estimated effort: **~1.5 engineer-weeks** (mostly the Stripe integration + magic-link + gating; deferred to after core).
