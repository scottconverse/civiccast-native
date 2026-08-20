# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Typed errors for channel egress."""

from __future__ import annotations


class EgressError(RuntimeError):
    """Base error for egress control and playout failures."""


class SinkConnectError(EgressError):
    """Raised when an output sink cannot be reached or prepared."""


class SourcePrepareError(EgressError):
    """Raised when a media source cannot be conformed before air."""


class NoValidSourceError(EgressError):
    """Raised when no program source exists and slate substitution is required."""


class ConfigInvalidError(EgressError):
    """Raised when egress configuration cannot be accepted."""


class SecretUnresolvedError(EgressError):
    """Raised when a sink requires a secret that cannot be resolved."""


class EncoderUnavailableError(EgressError):
    """Raised when the channel's configured hardware encoder is not available on
    this machine and no acceptable fallback applies (native-Windows pre-flight)."""
