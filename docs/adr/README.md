# ADR status and filename index

**Updated:** 2026-10-11. This index helps distinguish decision records from
current shipped behavior. It does not rewrite, supersede, or add to an accepted
owner decision. Cite ADRs by exact filename because two records use number
0023.

| Exact ADR filename | Recorded decision status | Current-status note |
|---|---|---|
| [`0001-messaging-substrate.md`](0001-messaging-substrate.md) | Superseded | [`0023-nats-removed-in-process-event-bus.md`](0023-nats-removed-in-process-event-bus.md) explicitly supersedes it; the product uses the in-process event bus. |
| [`0002-whisper-runtime.md`](0002-whisper-runtime.md) | Accepted historical runtime decision | Its faster-whisper-only shipping statement does not describe Beta 12. The current implementation uses Whistle CPU as live primary and per-channel Whisper fallback; see [`runtime.py`](../../civiccast/ai_models/runtime.py), [`whistle.py`](../../civiccast/captions/whistle.py), and the [Beta 12 verification record](../releases/v1.0.0-beta.12-verification.md). No superseding ADR is recorded here. |
| [`0003-project-hardware.md`](0003-project-hardware.md) | Superseded | [`0021-native-windows-runtime.md`](0021-native-windows-runtime.md) records the native Windows runtime decision. Its GPU-required historical framing is superseded by its dated CPU-only addendum. |
| [`0021-native-windows-runtime.md`](0021-native-windows-runtime.md) | Accepted native Windows runtime decision | Its parallel WSL/native wording is a historical decision state. The owner retired the WSL2 lane on 2026-08-19; current repository branch policy is recorded in [`BRANCHES.md`](../../BRANCHES.md). |
| [`0023-nats-removed-in-process-event-bus.md`](0023-nats-removed-in-process-event-bus.md) | Accepted | Supersedes `0001-messaging-substrate.md`. This is the NATS-removal record. |
| [`0023-asrun-durable-outbox.md`](0023-asrun-durable-outbox.md) | Accepted | Separate as-run durable-outbox record. It shares the numeric identifier 0023 with the NATS-removal record; use its exact filename. |

For current Beta 12 package identity and observed behavior, consult the [release
verification record](../releases/v1.0.0-beta.12-verification.md) and the exact
source revision it names. This index is navigation and status clarification,
not a new ADR, release gate, or authority to change an accepted decision.
