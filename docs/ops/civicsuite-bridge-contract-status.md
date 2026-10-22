# TownLight integration — owner-deferred to 2.0

On October 17, 2026, the owner clarified that CivicSuite is now TownLight and
directed: **no CivicSuite/TownLight integration at this time**. The integrated
edition, TownLight: Station, is deferred to a 2.0 product. Do not seek the
contract, implement the bridge, or treat it as a Sprint 6 blocker.

CivicCast-to-CivicCast station connections remain in Sprint 6 and are implemented:
published catalog/watch-link sharing, channel status and authorized remote
start/stop requests. See [station connections](station-federation.md) and
[Sprint 6 completion](sprint6.md).

## Historical investigation, superseded by the owner's deferral

Sprint 6 promotes CivicSuite integration into implementation scope. The current
`civiccast/civicclerk_bridge` directory contains only `.gitkeep`; ordinary agenda
import and ActivityPub are different features and do not satisfy this item.

Historical event payloads and intended actions are in Appendix A of
`docs/spec/spec.md`: meeting scheduled/in-progress/adjourned/cancelled and agenda
updated inbound; recording published/redacted, syndication completed and broadcast
failed outbound. Scheduling proposes an operator-confirmed event, while recording
and publication use existing CivicCast workflows. Outbound resync must survive
bridge unavailability without stopping standalone station operation.

The specification names CivicCore service tokens with a `broadcast-bridge` role
and an event bus, but does not supply its current transport interface. The local
CivicCast broker is in-process; NATS was removed. Restoring NATS or declaring that
an invented HTTP endpoint is compatible would not implement the real contract.

The owner was asked for the CivicSuite/CivicCore repository or current integration
documentation on October 17. Required receiving-side details are:

- Event-bus connection/subscription/publication API and event envelope, including
  delivery identifiers, acknowledgements and replay behavior.
- Service-token acquisition and verification, audience/scope rules and current
  CivicCore adapter interface.
- Protocol-version negotiation and the exact recording/event callback interface.

Existing event names/payloads need not be invented again. Once the real interface
is available, implementation can bind those events to existing station workflows,
retain durable pending deliveries, and exercise both sides using the actual
adapter contract. No outside station trial is required by this sprint.

Status: **not implemented; awaiting the external software contract**. This is
not permission to remove the item or mark Sprint 6 complete. Multi-station
catalog sharing and central controls are separate local software work proceeding
under the owner's explicit selection of both capabilities.

## Contract recheck (October 17)

The footer of `docs/spec/spec.md` explicitly identifies it as a historical,
pre-reset specification. The current 3.0 master/sections do not define a
CivicCore event-bus or bridge authentication interface. Appendix A therefore
provides intended behavior, not proof of today's receiving-side API.
`civiccast/platform/__init__.py` confirms that the in-process broker is the
only implementation after the August 20 NATS removal.

A fresh `gh repo list scottconverse --limit 1000 --json name,url` lookup found
no repository named CivicSuite, CivicCore or CivicClerk. This does not prove
that none exists under another owner or name. The owner-provided repository
or interface is still needed; the goal has not been marked complete.
