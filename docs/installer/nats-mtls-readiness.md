# NATS And mTLS Readiness

v1.2 requires two local infrastructure checks before an install can be treated
as ready:

- `nats-jetstream`: CivicCast must reach a NATS server over `tls://` with
  JetStream enabled, local-CA client credentials loaded, and the managed
  `CIVICCAST_EVENTS` stream.
- `mtls-local-ca`: CivicCast must have a local CA and service certificates for
  `civiccast-api`, `civiccast-worker`, and `nats`.

Run:

```bash
civiccast installer health-check
```

The checks fail closed. A missing NATS URL, non-TLS NATS URL, wrong stream
name, unreachable server, missing CA, missing service certificate, expired
certificate, or rotation-due certificate reports `failed` with a concrete next
step.

## Required Environment

```bash
export CIVICCAST_BROKER_MODE=production
export CIVICCAST_NATS_URL=tls://127.0.0.1:4222
export CIVICCAST_NATS_STREAM=CIVICCAST_EVENTS
export CIVICCAST_NATS_DURABLE=civiccast-publish
export CIVICCAST_CERT_ROOT=/var/lib/civiccast/certs
```

By default the NATS client uses the local CA certificate and the
`civiccast-api` service certificate material under `CIVICCAST_CERT_ROOT`. Those
paths can be overridden for managed deployments, but readiness still requires
real readable certificate files before NATS is treated as available.

Development and unit tests may explicitly use the in-process broker. Production
readiness never silently falls back to it.

## Certificate Bootstrap

Issue or rotate service credentials with:

```bash
civiccast cert rotate civiccast-api
civiccast cert rotate civiccast-worker
civiccast cert rotate nats
```

CLI and API status output includes certificate paths, fingerprints, issuer
fingerprints, SANs, and validity windows only. Private key paths and PEM bytes
are not exposed by public status models.
