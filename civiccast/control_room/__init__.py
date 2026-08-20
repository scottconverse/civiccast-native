# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S16 — Production & Control Room.

A thin CivicCast control surface that drives the station's existing production
switchers (OBS / vMix / ATEM / HyperDeck / PTZ / OSC / generic TCP-HTTP /
CasparCG, plus GPI and RS-232/422 serial) through TSR (timeline-state-resolver,
MIT), then routes the produced program feed into the S15 playout engine as an
ordinary ``live/`` source. S16 produces the source; S5 arbitrates air.

This package owns the CivicCast-side control plane (models, store, cue plan/fire
service, API, operator console). The Node TSR sidecar that actually speaks to
the devices lives under ``tsr_service/`` and is reached only over a localhost
REST/IPC contract — no GPL/AGPL source is vendored into this Apache tree.
"""
