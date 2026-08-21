# ADR 0022 — Sigstore/cosign keyless attestation denied for the release chain

**Status:** Accepted
**Date:** 2026-08-21
**Deciders:** Scott Converse (owner)
**Related rung:** Native-Windows Program (release/signing infrastructure)
**Related spec section:** §17.1 Release artifacts (historical; see "Consequences" below)
**Supersedes:** none
**Superseded by:** none

---

## Context

The pre-reset spec line and the retired WSL-era `release-artifacts.yml` workflow assumed
Sigstore/cosign keyless attestation (a `cosign attest-blob` step producing a `*.sigstore.json`
DSSE bundle per release asset, verified against GitHub Actions' OIDC workflow identity) as a
supply-chain-provenance layer alongside code signing. That workflow, and the `docker/`/WSL2 lane
it shipped from, was retired by owner decision on 2026-08-19 (see `docs/adr/0021-native-windows-runtime.md`
and `BRANCHES.md`). The native Windows release chain that replaced it
(`native-beta-candidate-artifacts.yml` + `sign-native-installer.yml`) was built from scratch and
never carried a cosign/sigstore step.

Several policy tests, docs, and code comments continued to describe Sigstore/cosign as a current
or reintroducible requirement for the native chain, and one runtime check
(`civiccast.installer.packages.verify_package_artifact`) unconditionally required a
`*.sigstore.json` bundle to exist next to any package artifact before it would verify — a
requirement nothing in the native chain could ever satisfy, since no workflow produces that file.

## Decision

**Sigstore/cosign keyless attestation is denied for this repository's release chain.** The
project's only release-signing mechanism is **Azure Trusted Signing (Authenticode)** for the
Windows installer, plus **ed25519 pack signing** (`civiccast.installer.native_packs`) for native
distribution packs. No workflow, script, or verifier in this repository may require a
`.sigstore.json` bundle, a cosign identity, or any other Sigstore/Rekor/Fulcio artifact.

## Alternatives considered

**Option A — Reintroduce Sigstore/cosign on the native chain.** Would have added a second
signing identity (GitHub Actions OIDC → Fulcio → Rekor transparency log) alongside Authenticode,
giving verifiers an independent, keyless proof of build provenance. Rejected by the owner: two
parallel signing/verification mechanisms for a single-maintainer project add operational surface
(a second thing that can silently stop working, a second thing testers must learn to check)
without a corresponding trust benefit once Authenticode + ed25519 pack signing already cover the
two artifact classes that ship (the installer exe and the native packs).

**Option B — Keep Sigstore as a documented-but-unenforced aspiration.** What the repository
carried into this decision: docs and tests described Sigstore as present or required while no
code produced it (`verify_package_artifact` even blocked verification on a bundle no workflow
ever writes). Rejected — a requirement nothing implements is not a lighter version of the
requirement, it is a false claim; `docs/process/CIVICCAST_AUDIT_PROTOCOL.md` treats unverified
claims and doc/code drift as defects to fix, not states to document around.

**Option C — Azure certs only (chosen).** Authenticode via Azure Trusted Signing for the one
artifact that needs publisher-identity trust on end-user machines (the Windows installer, where
SmartScreen and Windows' own trust UI read Authenticode), and ed25519 pack signing for the
native packs the installer unpacks itself (where the installer is both signer's counterpart and
verifier, so a lighter, dependency-free signature scheme is sufficient). No second identity
provider, no transparency log dependency, no `.sigstore.json` artifact to generate, retain, or
verify.

## Consequences

### Positive

- One signing identity to operate and rotate (Azure Trusted Signing), not two.
- No dependency on Sigstore's Fulcio/Rekor infrastructure being reachable at release-build time.
- Verifiers (`civiccast.installer.packages.verify_package_artifact`,
  `scripts/policy/check_sidecar_attestation_integrity.py`) check only real, always-producible
  evidence — the embedded Authenticode certificate table — instead of an artifact only a retired
  workflow ever wrote.

### Negative

- No independent, third-party transparency-log record of "this exact CI run produced this exact
  binary" beyond what the Azure Trusted Signing timestamp already proves. A future owner decision
  could reopen this if that specific property becomes a requirement (e.g. for SLSA-level supply
  chain claims); it would need a new ADR, not a silent revival.
- Non-Windows package artifacts (`.deb`, `.rpm`, `.pkg`, portable archives — none currently
  produced by the native line) have no cryptographic signing mechanism at all in this repository;
  `verify_package_artifact` now rejects a `signed: true` claim for any of them rather than
  fabricating trust it cannot back.

### Risks

- Docs or tests drifting back toward describing Sigstore as present. Mitigation: this ADR plus
  the "Supply-chain provenance" section of `CODE_SIGNING_POLICY.md` are the durable record;
  `tests/policy/test_release_proof_policy.py::TestWindowsAttestationDocumentation` asserts the
  Authenticode-only chain is what the docs describe.

## Compliance

- `civiccast/installer/packages.py::verify_package_artifact` requires embedded Authenticode
  evidence (not a Sigstore bundle) before it will mark a Windows `.exe` artifact `signed`.
- `scripts/policy/check_sidecar_attestation_integrity.py` fails a sidecar that carries a non-null
  `attestation` field, since no code path may populate one.
- `scripts/build_release_artifacts.py::_installer_artifact_entry` writes `signed` from real PE
  Authenticode-evidence bytes only.
- `CODE_SIGNING_POLICY.md` and `docs/install/windows-release-trust.md` describe the Authenticode
  + ed25519-pack-signing chain as the complete, current answer to "how do I verify a release."

## References

- `docs/adr/0021-native-windows-runtime.md` (the native line this chain belongs to).
- `BRANCHES.md` (WSL/Linux lane retirement).
- `.github/workflows/sign-native-installer.yml` (the actual signing step).
- `civiccast/installer/native_packs.py` (`verify_native_pack`, ed25519 pack verification).
- `CODE_SIGNING_POLICY.md` (operator-facing verification instructions).

---

*ADRs are immutable once Accepted. Reversing or superseding requires a new ADR that references this one.*
