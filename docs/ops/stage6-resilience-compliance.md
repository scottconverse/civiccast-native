# Stage 6 Traffic, Redundancy, Accessibility, Security, And Soak

Stage 6 verifies local evidence for traffic/SCTE-adjacent headend delivery,
redundancy, recovery, disaster rehearsal, accessibility captions, EAS compliance,
security/auth hardening, soak, stress, and local runner behavior.

## Covered Surfaces

- Traffic and SCTE-adjacent headend controls through egress headend proof paths.
- Virtual headend proof runner and receiver-side local scenarios.
- Redundancy, recovery, and disaster rehearsal through egress reliability and
  recovery tests.
- Accessibility and captions through caption proof, caption feed/embed, live
  caption proof, and caption review queue coverage.
- EAS compliance through CAP parsing, health hooks, service, router, and worker
  tests.
- Security and auth hardening through staff auth, staff token lifecycle, and
  operator token-source policy tests.
- Soak and stress through deterministic Stage 6-7 LPM lab evidence and egress soak
  verdict tests.

## Focused Tests

The Stage 6 proof runs a focused pytest bundle over Stage 6-7 lab, egress headend,
virtual headend, caption proof, compliance, reliability, recovery, soak, EAS, auth,
policy, and caption review surfaces. The completion report blocks if those focused
tests are not passed.

## Not Claimed

Stage 6 local proof does not claim legal caption compliance, real cable headend
acceptance, or elapsed wall-clock disaster recovery proof. Those require separate
station or legal/compliance evidence.
