# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Unit tests for the pure hardware-encoder-availability decision (no ``gi`` import)."""

from __future__ import annotations

from civiccast.egress.gst.encoder_probe import hardware_encoder_available


def test_hardware_present() -> None:
    table = {"mfh264enc": "Codec/Encoder/Video/Hardware"}
    assert hardware_encoder_available("mfh264enc", lookup=table.get) is True


def test_software_present() -> None:
    table = {"openh264enc": "Encoder/Video"}
    assert hardware_encoder_available("openh264enc", lookup=table.get) is False


def test_absent_factory() -> None:
    table: dict[str, str] = {}
    assert hardware_encoder_available("nope264enc", lookup=table.get) is False


def test_listed_but_not_hardware() -> None:
    table = {"mfh264enc": "Codec/Encoder/Video"}
    assert hardware_encoder_available("mfh264enc", lookup=table.get) is False


def test_nvenc_hardware() -> None:
    table = {"nvh264enc": "Codec/Encoder/Video/Hardware"}
    assert hardware_encoder_available("nvh264enc", lookup=table.get) is True
