# NATS JetStream Operations

v1.2 implements the production broker foundation behind
`civiccast.platform.broker.BrokerClient`.

## Managed Stream

| Field | Value |
| --- | --- |
| Stream | `CIVICCAST_EVENTS` |
| Logical subject | `publish.asset.approved` |
| Provider subject | `civiccast.publish.asset.approved` |
| Retention | `limits` |
| Ack policy | `explicit` |
| Durable consumer | `civiccast-publish` |

The mapping lives in `civiccast.platform.broker_config`. Feature modules publish
only documented logical subjects. Raw provider subjects stay inside the
platform registry.

## Readiness

Set:

```bash
export CIVICCAST_BROKER_MODE=production
export CIVICCAST_NATS_URL=tls://127.0.0.1:4222
export CIVICCAST_NATS_STREAM=CIVICCAST_EVENTS
export CIVICCAST_CERT_ROOT=/var/lib/civiccast/certs
```

Then run:

```bash
civiccast installer health-check
```

The installer reports `ok` only after configuration validates, the local CA and
`civiccast-api` client certificate/key exist, the NATS host is reachable over
`tls://`, and the managed JetStream stream accepts the documented subject. Missing
URL, non-TLS URL, missing stream, wrong stream, invalid durable name, missing
certificate material, or connection failure blocks readiness with
operator-actionable copy.

ActivityPub federation, cable playout, NDI/SDI output, external provider proof,
RTX caption proof, and real-station production proof are not claimed by this
foundation.
