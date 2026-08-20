# 1.3 - Operator Product Foundation Plan

Public framing: **Operator-first beta**.

Release-note line:

> v1.3 starts the shift from CivicCast as a platform you operate to CivicCast
> as a product meeting teams can use.

## Scope

v1.3 is foundation work plus the public tester readiness vertical slice. It
ships the contracts future operator-first features depend on and implements the
setup/readiness path those contracts describe so CivicCast can be installed,
set up, rehearsed, operated, reviewed, published locally, and diagnosed by
technical and non-technical testers without CLI handholding.

Required modules for this line are `civiccast.installer`, `civiccast.auth`,
`civiccast.live`, `civiccast.schedule`, `civiccast.publish`,
`civiccast.apps.installer`, `civiccast.apps.portal-operator`,
`civiccast.apps.portal-public`, `docs`, and `tests`.

## Deliverables

1. **Persona docs split.** The user manual routes readers to Admin, Meeting
   Operator, Records Clerk, and Technical Operations Reference docs.
2. **Operator language guide.** Product copy uses shared terms for broadcast,
   publish, ready states, optional setup, IT-help boundaries, captions, and
   resident-facing language.
3. **First-admin and recovery-kit flow.** The setup API and console screen
   create the first local admin, return one-time recovery codes, store only
   hashes, hand the browser an operator-console token, and let the admin sign
   in or recover access later without using a CLI bearer-token flow.
4. **Role-based console shell.** The operator console groups existing routes
   into Setup, Run Meeting, Review Records, Publish, and System Health, with
   URL-addressable hash routes so refreshes and shared links preserve the task.
   This is navigation only, not full RBAC.
5. **System Health and safe-to-broadcast.** The installer API and console
   expose green, yellow, and red readiness, required checks, optional checks,
   resident preview, and five-minutes-before-meeting operator guidance. A
   configured camera, recording target, or resident URL stays yellow until the
   report carries live preflight, write-probe, or preview-confirmation proof.
6. **Private rehearsal.** The console can run a private first-broadcast
   rehearsal that returns the same readiness model before a public meeting.
7. **Public tester installer path.** Make the Windows installer the canonical
   tester entrypoint.
8. **Hidden setup mechanics.** Hide WSL2 and setup nonce from non-technical
   tester workflows.
9. **Tester operations surfaces.** Implement first-admin recovery,
   safe-to-broadcast, rehearsal, source/provider readiness, backup/update/support
   surfaces.
10. **External provider honesty.** Keep external provider proof honest and
   optional unless configured.
11. **Remote visibility.** Commit and push every clean slice to the private
   GitHub repo.

## Non-Goals

- Public fediverse interoperability guarantee.
- Full RBAC, SSO, or permission enforcement.
- Hosted or managed deployment offering.

## Verification

- Docs links resolve from README, FAQ, docs index, and the rendered user manual.
- `docs/USER-MANUAL.md` renders to PDF and DOCX.
- New installer setup/readiness APIs forbid extra response fields and keep the
  unauthenticated first-admin endpoint local-only or installer-nonce gated when
  reached through a non-local host name.
- OpenAPI JSON, generated API reference, and operator TypeScript API types are
  regenerated from the live app.
- Operator console build, lint, axe, and focused Playwright paths cover the new
  first-mile screens.
- Clean Windows install proof reaches the operator dashboard without CLI
  handholding.
- A non-technical tester script completes install, setup, rehearsal,
  upload/source, resident preview, review/publish, and support bundle.
- All generated API docs and TypeScript types match implemented contracts.
- Full backend, frontend, installer, accessibility, and audit gates pass.
- Release tag is not created until Agent Pipeline approval.

## Follow-On Queue

v1.4 should build on these surfaces with broader external-provider live proof
and more granular role enforcement. v1.5 can then layer hosted-deployment
packaging and additional deployment profiles.
