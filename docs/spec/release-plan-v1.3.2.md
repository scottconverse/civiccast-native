# 1.3.2 - Public Distribution Bridge

Public framing: **Private beta to public-download bridge**.

Release-note line:

> v1.3.2 prepares the v1.3 installer path for people outside the private repo
> by resolving access, signing, and public support expectations without adding
> v1.4 feature scope.

## Scope

v1.3.2 is a distribution and trust milestone. It decides where non-collaborator
users download CivicCast, how Windows publisher trust is handled, and what
support channel receives tester reports once the release is no longer confined
to private GitHub collaborators.

## Deliverables

1. Public download/access decision: public repo, public release-only repo, or
   external download host.
2. Windows signing decision: Authenticode-signed installer or explicit
   unsigned-beta policy with user-facing SmartScreen instructions.
3. Public install page that does not require GitHub collaborator access.
4. Support intake path for testers who cannot open private repo issues.
5. Release asset proof from the public download location.
6. Clear known-limits language for WSL2/Ubuntu/reboot expectations.

## Non-Goals

- Broad external-provider live proof.
- Full granular RBAC or SSO.
- Hosted deployment offering.
- Public marketing launch.

## Handoff To v1.4

v1.4 should build on the stable installer/distribution base with broader
external-provider live proof, more granular role enforcement, and deeper
operator workflow hardening.
