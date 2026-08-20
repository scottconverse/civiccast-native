# Live Remote Ingest Relay Operations

This guide explains the v1.8.7 remote-ingest posture for stations that need a
room encoder, field kit, or partner facility to reach CivicCast without opening
fragile inbound firewall paths. It is for station admins, integrators, and
technical operators.

## Operating Goal

CivicCast should always have a usable local meeting path, and it should also be
able to describe optional remote paths that are safe for an operator to choose.
The live-room ingest plan is the operator-facing contract:

- **Local encoder:** the default path on the CivicCast host or station LAN.
- **Cloud relay:** an outbound-only RTMP/RTMPS path that returns a playback URL
  for CivicCast station playout.
- **Direct platform:** an emergency or policy-approved path that sends the
  encoder directly to a destination platform.

The plan does not expose stream keys, bearer tokens, private URLs, or credential
handles. It shows only labels, endpoint URLs safe for the operator workflow,
health, recommended path, next action, and risk notes.

## Deployment Postures

### Local Default

Use this when the encoder and CivicCast host are on the same room network or
station LAN.

- Encoder points to `rtmp://127.0.0.1/live/{channel_id}` on the CivicCast host
  or the equivalent LAN endpoint configured by the station.
- No relay account is required.
- No inbound internet firewall opening is required.
- CivicCast keeps this path available even when remote relays are configured.

This is the recommended fallback for every station because it is the simplest
path to record, preview, and recover a meeting.

### Project-Hosted Relay

Use this when CivicCast controls the relay service on behalf of a station.

- Encoder sends outbound RTMP/RTMPS to the relay endpoint.
- The relay returns a playback URL that CivicCast can read for station playout.
- The station firewall only needs outbound access to the relay endpoint.
- Credentials live in the CivicCast credential store and are not shown in the
  operator room.

This posture is useful for field kits, guest networks, rooms without port
forwarding, and partner facilities where the station cannot change firewall
rules.

### Integrator-Hosted Relay

Use this when an IT partner, community-media partner, or municipal hosting team
runs the relay.

- CivicCast stores the relay endpoint, provider label, return playback URL, and
  credential handle.
- The integrator is responsible for relay uptime, TLS certificates, endpoint
  rotation, and source-IP access rules.
- CivicCast reports relay health through `ready`, `degraded`, `offline`, or
  `not configured` states.

This posture is appropriate when the station already has a managed video
network, CDN, or contribution relay.

### Direct Platform

Use direct platform mode only when station policy accepts the tradeoff.

- Encoder sends directly to a platform endpoint.
- CivicCast can show the path and health state, but this mode may bypass local
  recording unless a separate recording target is active.
- The live-room plan marks this path with a risk note.

Do not make direct platform mode the default for public-record meetings unless
the recording and retention path is separately proven.

## Health States

| State | Meaning | Operator Action |
| --- | --- | --- |
| Ready | The path is configured and the latest probe says it can be used. | It may be recommended for the meeting. |
| Degraded | The path exists but a recent check found latency, return-playback, credential, or probe trouble. | Prefer local default unless the admin has cleared the issue. |
| Offline | The path is configured but the latest check cannot use it. | Do not rely on it for the meeting. |
| Not configured | The station has not completed the relay setup. | Use local default or complete setup before the meeting. |

When every remote path is degraded or offline, CivicCast recommends the local
encoder path. That is intentional; remote reach should improve resilience, not
hide a broken station path.

## Operator Room Behavior

The live room asks the backend for:

```text
GET /api/staff/live/ingest-plan?channel_id={channel_id}
```

The response includes:

- the local default path;
- enabled remote relay paths;
- the recommended path ID;
- degraded path count;
- whether direct syndication is available.

Operators should see:

- **Recommended:** the path CivicCast would choose right now;
- **Local default:** the fallback path if no relay is ready;
- **Outbound only:** confirmation that a cloud relay does not require inbound
  firewall changes;
- **Next step:** the practical action for the selected path;
- direct-mode risk copy when local recording could be bypassed.

## Failure Handling

1. If a relay is degraded, use local default unless the admin has recently
   confirmed the relay is safe.
2. If a relay is offline, do not use it for the meeting.
3. If the ingest-plan endpoint is unavailable, continue with local sources only
   and ask a technical admin to check API/database health after the meeting.
4. If the local source drops during a meeting, follow the live-room source-drop
   slate guidance and keep the recording path alive.
5. After a remote-path incident, capture the relay health state, endpoint label,
   provider, timestamp, and operator action in the meeting notes or support
   bundle.

## Pre-Meeting Checklist

- Confirm local default appears in the live room.
- Confirm the chosen relay path shows **Ready** before relying on it.
- Confirm the return playback URL opens from the CivicCast host when using a
  relay path.
- Confirm the recording target is ready before any direct platform path is used.
- Run live preflight and do not start the public broadcast until required checks
  pass.

## Security Notes

- Do not paste stream keys, private relay URLs, or credential handles into
  meeting notes, screenshots, chat, or public issues.
- Store relay credentials through the station credential path, not in docs.
- Rotate relay credentials after an operator workstation compromise or partner
  staff change.
- Treat direct platform endpoints as sensitive even when the public playback URL
  is not secret.
