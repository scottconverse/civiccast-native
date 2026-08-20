# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""civiccast.platform — platform substrate (Mode A vendored core).

Per spec §6.4 / §8.19 this package vendors the platform substrate:
hardware probe, manifests, auth, audit, secrets, LLM provider abstraction.
In Mode A the substrate is bundled with CivicCast; in Mode B the host
suite (CivicSuite) supplies it through the same protocol surface.

Sprint 0.1 shipped the hardware probe (`civiccast.platform.hardware`).
The v1.2 hardening rung adds the platform-owned broker Protocol and
in-process adapter used by module seams before a concrete NATS adapter lands.
"""

from civiccast.platform.broker import (
    BrokerClient,
    BrokerEvent,
    BrokerPublishReceipt,
    InProcessBrokerClient,
)
from civiccast.platform.broker_config import BrokerConfig, BrokerConfigurationError

__all__ = [
    "BrokerClient",
    "BrokerConfig",
    "BrokerConfigurationError",
    "BrokerEvent",
    "BrokerPublishReceipt",
    "InProcessBrokerClient",
]
