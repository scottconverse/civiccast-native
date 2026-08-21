# Local CA mTLS Operations

v1.2 adds first-party local-CA credential management for CivicCast internal
service identity. It is required for install readiness even on single-host
loopback deployments.

## Required Identities

- `civiccast-api`
- `civiccast-worker`

The certificate root defaults to `~/.civiccast/certs` and can be overridden:

```bash
export CIVICCAST_CERT_ROOT=/var/lib/civiccast/certs
```

## Rotation

Run:

```bash
civiccast cert rotate civiccast-api
civiccast cert rotate civiccast-worker
```

Service certificates are issued for a 90-day cadence. Certificates inside the
30-day danger window report `rotation_due` and block mTLS readiness until
rotated.

## Private Key Boundary

Public status models and CLI output do not contain `private_key`,
`private_key_path`, `private_key_pem`, or PEM key bytes. Status output is
limited to certificate paths, fingerprints, issuer fingerprint, SANs, and
validity windows.
