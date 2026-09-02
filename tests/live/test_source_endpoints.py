# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Centralized live-source endpoint validation (WP-07).

Before this module existed the rule lived only in the Setup wizard
(``civiccast.installer.service._source_setup_endpoint``), keyed on the wizard's
``kind`` rather than on the stored ``source_type``. The staff API's own
``LiveSourceCreate`` accepted ``HttpUrl | str`` and never asked whether the
address matched the type, so a row could be stored that no probe and no
playout element could ever open.

What these tests lock:

* each source type accepts only its own scheme(s), and rejects the others;
* the TLS spellings (rtmps / rtsps) stay valid under the plain source types
  the DB CHECK constraint allows, because the Setup wizard has always stored
  them that way and rejecting them would break existing stations on edit;
* NDI takes a NAME (spaces and parentheses included) and never a path;
* credentials in the address are refused for every type, and an SRT
  passphrase in a query parameter is refused specifically;
* only SRT may carry a stored credential handle, and the copy explaining why
  the others may not is a real sentence, not a code.
"""

from __future__ import annotations

import pytest

from civiccast.live.source_endpoints import (
    CREDENTIAL_SUPPORTED_SOURCE_TYPES,
    EndpointValidationError,
    credential_support_reason,
    normalize_endpoint,
    supports_credentials,
)


class TestAcceptedShapes:
    @pytest.mark.parametrize(
        ("source_type", "endpoint", "expected"),
        [
            ("rtmp", "rtmp://encoder.local/live/a", "rtmp://encoder.local/live/a"),
            ("rtmp", "RTMP://encoder.local/live/a", "rtmp://encoder.local/live/a"),
            # The Setup wizard stores an rtmps:// address under source_type
            # "rtmp" (installer.service._source_setup_endpoint); the DB CHECK
            # constraint has no "rtmps" value to store instead.
            ("rtmp", "rtmps://encoder.local:1935/live/a", "rtmps://encoder.local:1935/live/a"),
            ("rtsp", "rtsp://camera.local:554/stream1", "rtsp://camera.local:554/stream1"),
            ("rtsp", "rtsps://camera.local:322/stream1", "rtsps://camera.local:322/stream1"),
            ("srt", "srt://0.0.0.0:9000?mode=listener", "srt://0.0.0.0:9000?mode=listener"),
            ("ndi", "COUNCIL-CAM (Channel 1)", "ndi://COUNCIL-CAM (Channel 1)"),
            ("ndi", "ndi://COUNCIL-CAM (Channel 1)", "ndi://COUNCIL-CAM (Channel 1)"),
        ],
    )
    def test_valid_endpoint_is_normalized(
        self, source_type: str, endpoint: str, expected: str
    ) -> None:
        assert normalize_endpoint(source_type, endpoint) == expected

    def test_surrounding_whitespace_is_trimmed(self) -> None:
        assert normalize_endpoint("srt", "  srt://host:9000  ") == "srt://host:9000"


class TestRejectedShapes:
    @pytest.mark.parametrize(
        ("source_type", "endpoint"),
        [
            # The exact cross-type mix-ups the old permissive union allowed.
            ("srt", "https://encoder.example/stream.m3u8"),
            ("rtmp", "https://encoder.example/stream.m3u8"),
            ("rtmp", "srt://encoder.example:9000"),
            ("rtsp", "rtmp://encoder.example/live"),
            ("srt", "rtsp://camera.local/stream1"),
            ("ndi", "ndi://rack/camera/1"),
            ("ndi", "rtsp://camera.local/stream1"),
        ],
    )
    def test_wrong_scheme_for_type_is_rejected(self, source_type: str, endpoint: str) -> None:
        with pytest.raises(EndpointValidationError):
            normalize_endpoint(source_type, endpoint)

    def test_empty_endpoint_is_rejected(self) -> None:
        with pytest.raises(EndpointValidationError, match="Enter the stream address"):
            normalize_endpoint("rtmp", "   ")

    def test_missing_host_is_rejected(self) -> None:
        with pytest.raises(EndpointValidationError, match="no host"):
            normalize_endpoint("rtmp", "rtmp:///live/a")

    def test_control_characters_are_rejected(self) -> None:
        with pytest.raises(EndpointValidationError, match="control characters"):
            normalize_endpoint("rtmp", "rtmp://encoder.local/li\x00ve")

    def test_space_inside_a_url_is_rejected(self) -> None:
        with pytest.raises(EndpointValidationError, match="spaces"):
            normalize_endpoint("rtmp", "rtmp://encoder.local/li ve")

    def test_embedded_credentials_are_rejected(self) -> None:
        with pytest.raises(EndpointValidationError, match="username or password"):
            normalize_endpoint("rtsp", "rtsp://admin:hunter2@camera.local/stream1")

    def test_srt_passphrase_in_the_query_is_rejected(self) -> None:
        # A passphrase in the address would be persisted in a row, echoed in
        # the ingest plan, and written into logs. It has one legitimate home:
        # the station credential store.
        with pytest.raises(EndpointValidationError, match="passphrase"):
            normalize_endpoint("srt", "srt://host:9000?passphrase=hunter2")

    def test_srt_passphrase_query_key_is_matched_case_insensitively(self) -> None:
        with pytest.raises(EndpointValidationError, match="passphrase"):
            normalize_endpoint("srt", "srt://host:9000?mode=caller&PassPhrase=hunter2")

    def test_srt_passphrase_in_the_fragment_is_rejected(self) -> None:
        # ``normalize_endpoint`` only inspected ``parsed.query`` and then
        # re-emitted the fragment unchanged, so a passphrase after '#' was
        # accepted and persisted in plaintext, byte-for-byte, in the row.
        with pytest.raises(EndpointValidationError, match="passphrase"):
            normalize_endpoint("srt", "srt://10.0.0.5:9000#passphrase=hunter2")

    def test_any_url_fragment_is_rejected_even_without_the_word_passphrase(self) -> None:
        # A fragment that does not literally spell "passphrase=" is still an
        # operator pasting a secret after '#' -- an SRT passphrase copied
        # without its key name, a bearer token, anything. Reject the fragment
        # outright rather than pattern-matching only the one spelling.
        with pytest.raises(EndpointValidationError, match="#"):
            normalize_endpoint("srt", "srt://10.0.0.5:9000#hunter2")

    def test_an_empty_fragment_marker_is_stripped_not_rejected(self) -> None:
        # A bare trailing '#' with nothing after it carries no secret and no
        # information; ``urlsplit`` reports it as an empty fragment, which
        # must normalize away cleanly rather than round-trip.
        assert normalize_endpoint("rtmp", "rtmp://encoder.local/live/a#") == (
            "rtmp://encoder.local/live/a"
        )

    def test_a_non_srt_fragment_is_rejected_too(self) -> None:
        # The fragment rule is not SRT-specific: any URL-type source could
        # carry a secret after '#'.
        with pytest.raises(EndpointValidationError, match="#"):
            normalize_endpoint("rtsp", "rtsp://camera.local:554/stream1#token=abc123")

    def test_at_sign_in_an_ndi_name_is_rejected(self) -> None:
        with pytest.raises(EndpointValidationError, match="username or password"):
            normalize_endpoint("ndi", "admin@COUNCIL-CAM")

    def test_unknown_source_type_is_rejected(self) -> None:
        with pytest.raises(EndpointValidationError, match="not a source type"):
            normalize_endpoint("sdi", "sdi://0")

    def test_absurdly_long_endpoint_is_rejected(self) -> None:
        with pytest.raises(EndpointValidationError, match="longer than"):
            normalize_endpoint("rtmp", "rtmp://host/" + "a" * 4000)


class TestCredentialCapability:
    def test_only_srt_supports_a_stored_credential(self) -> None:
        assert frozenset({"srt"}) == CREDENTIAL_SUPPORTED_SOURCE_TYPES
        assert supports_credentials("srt") is True
        for unsupported in ("rtmp", "rtsp", "ndi"):
            assert supports_credentials(unsupported) is False

    def test_supported_type_has_no_unsupported_copy(self) -> None:
        assert credential_support_reason("srt") is None

    @pytest.mark.parametrize("source_type", ["rtmp", "rtsp", "ndi"])
    def test_unsupported_types_explain_themselves_in_plain_words(self, source_type: str) -> None:
        reason = credential_support_reason(source_type)
        assert reason is not None
        # An operator reading a disabled control needs a sentence, not a code.
        assert reason.endswith(".")
        assert len(reason.split()) > 8
        assert "CivicCast" in reason or "NDI" in reason
