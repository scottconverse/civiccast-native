# 1.4 - Provider Proof And Role Hardening

Public framing: **Beta operations hardening**.

Release-note line:

> v1.4 turns the v1.3 installer-first private beta into a more complete
> operations beta by proving selected external provider lanes live and by
> separating setup, meeting operation, records review, publishing, and support
> responsibilities inside the operator console.

## Scope

v1.4 builds on the proven v1.3.1 Windows installer path. It should not reopen
the installer release-smoke loop unless a product change affects first-run
setup, runtime bootstrap, or release packaging. The main work is to make
external provider readiness less theoretical, add useful role boundaries, and
turn beta-operator friction into tests and product copy.

Required modules for this line are `civiccast.auth`, `civiccast.installer`,
`civiccast.publish`, `civiccast.schedule`,
`civiccast.apps.portal-operator`, `civiccast.apps.portal-public`, `docs`, and
`tests`.

## Deliverables

1. **Controlled provider proof lane.** Select a first live-provider proof set
   from Internet Archive, YouTube, local NAS, email/webhook notifications,
   podcast feed discovery, and ActivityPub target-instance proof. Each live
   pass must record redacted evidence and must not claim unsupported providers.
2. **Provider proof workflow.** System Health and Setup should guide operators
   from "credential configured" to "controlled proof passed" with clear skip,
   retry, rotate, and redact paths.
3. **Granular operator roles.** Split the current local-admin behavior into
   product roles for setup/admin, meeting operator, records clerk, publish
   operator, and support/admin. The first slice may be local-only, but routes,
   UI affordances, and tests must not imply SSO or hosted identity.
4. **Role-aware console behavior.** Setup, Run Meeting, Review Records,
   Publish, and System Health should show only actions the signed-in role can
   take, while keeping read-only guidance available where it helps handoff.
5. **Full restore proof plan.** Extend the current small restore rehearsal into
   a scoped DB/media/config restore proof plan, with an isolated station profile
   as the target before any release claim.
6. **Update and rollback design.** Convert the current update/rollback status
   surface into an executable plan for safe update apply, rollback asset
   selection, and post-update safe-to-broadcast proof.
7. **Observed beta walkthroughs.** Run at least one non-technical operator
   walkthrough and one technical-admin walkthrough. Convert friction into
   product fixes, documentation fixes, or regression tests.

## Non-Goals

- Hosted or managed deployment offering.
- Public marketing launch.
- Broad public fediverse interoperability guarantee.
- Enterprise SSO or organization-wide identity management.
- Silent cloud fallback for AI or provider lanes.

## Verification

- Provider readiness remains fail-closed until live proof evidence exists.
- Redacted live-provider evidence is durable, reviewed for secret leakage, and
  linked from the credential matrix or release evidence.
- Role tests cover route access, hidden actions, permitted actions, and
  read-only guidance for each implemented role.
- Operator-console Playwright coverage includes the provider-proof workflow and
  at least one role-restricted workflow.
- Backend tests cover role enforcement for staff APIs touched by v1.4.
- Docs links resolve from README, docs index, user manual, tester packet, and
  relevant ops guides.
- Clean Windows installer proof is rerun only if v1.4 changes installer,
  runtime bootstrap, first-admin setup, or release packaging behavior.

## Carry-Forward Notes

- v1.3.2 remains reserved for public distribution posture, signing posture,
  and support intake outside the private repo.
- GitHub is the day-to-day working and publishing remote for this line.
