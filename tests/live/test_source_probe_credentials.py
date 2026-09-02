# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Credential resolution and redaction in the live-source probe (WP-07).

``live_sources.credentials_handle`` had existed since migration 0007 and
nothing anywhere read it back; ``source_probe``'s own docstring said so. This
module locks what "closing that surface" actually means, and -- just as
importantly -- what it deliberately does NOT do:

* the handle is resolved at PROBE time through an injected resolver, so
  rotating a passphrase in the credential store takes effect on the next check
  without restarting the service;
* the SRT passphrase is an ffprobe protocol option (``-passphrase``), never
  appended to the endpoint URL that gets persisted, logged, or planned;
* a handle that resolves to nothing FAILS the probe rather than quietly
  probing unauthenticated and reporting ready;
* an authenticated shape on a protocol that would require the secret in the
  URL (rtsp/rtmp) is refused, with copy, not silently downgraded;
* anything the probe hands back is scrubbed of the resolved secret, even when
  the secret came back in a third party's stderr.

The ffprobe subprocess boundary is mocked; ``tests/live/test_source_probe.py``
covers the argv/parse contract for the unauthenticated path.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from civiccast.live.models import LiveSourceResponse
from civiccast.live.secrets import redact_secrets
from civiccast.live.source_probe import (
    ERROR_CREDENTIALS_UNRESOLVED,
    ERROR_CREDENTIALS_UNSUPPORTED,
    observe_live_source,
)

_SECRET = "council-chamber-passphrase"


def _source(*, source_type: str = "srt", endpoint: str | None = None, handle: str | None = None):  # type: ignore[no-untyped-def]
    default_endpoint = {
        "srt": "srt://0.0.0.0:9000?mode=listener",
        "rtsp": "rtsp://camera.local/stream1",
        "rtmp": "rtmp://encoder.local/live/a",
        "ndi": "ndi://COUNCIL-CAM",
    }[source_type]
    return LiveSourceResponse(
        live_source_id="council-encoder",
        channel_id="gov-ch12",
        name="Council Room Encoder",
        source_type=source_type,  # type: ignore[arg-type]
        endpoint_url=endpoint or default_endpoint,
        credentials_handle=handle,
        created_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
    )


class _Completed:
    def __init__(self, *, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


_OK_JSON = '{"streams": [{"codec_type": "video"}], "format": {}}'


@pytest.fixture
def captured_argv(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []
    monkeypatch.setattr("civiccast.live.source_probe.shutil.which", lambda _name: "ffprobe")

    def _run(cmd, **_kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        return _Completed(returncode=0, stdout=_OK_JSON)

    monkeypatch.setattr("civiccast.live.source_probe.subprocess.run", _run)
    return calls


class TestResolvedAtProbeTime:
    def test_srt_passphrase_is_passed_as_a_protocol_option(
        self, captured_argv: list[list[str]]
    ) -> None:
        observation = observe_live_source(
            _source(handle="council-srt"),
            timeout_seconds=2.0,
            resolve_secret=lambda handle: _SECRET if handle == "council-srt" else None,
        )
        assert observation.ok is True
        argv = captured_argv[0]
        assert "-passphrase" in argv
        assert argv[argv.index("-passphrase") + 1] == _SECRET
        # BEFORE -i, which is where FFmpeg reads per-protocol AVOptions.
        assert argv.index("-passphrase") < argv.index("-i")

    def test_the_secret_never_enters_the_endpoint_url(self, captured_argv: list[list[str]]) -> None:
        observe_live_source(
            _source(handle="council-srt"),
            timeout_seconds=2.0,
            resolve_secret=lambda _h: _SECRET,
        )
        argv = captured_argv[0]
        endpoint = argv[argv.index("-i") + 1]
        assert _SECRET not in endpoint
        assert endpoint == "srt://0.0.0.0:9000?mode=listener"

    def test_the_resolver_is_called_with_the_stored_handle(
        self, captured_argv: list[list[str]]
    ) -> None:
        seen: list[str] = []

        def _resolve(handle: str) -> str:
            seen.append(handle)
            return _SECRET

        observe_live_source(
            _source(handle="council-srt"), timeout_seconds=2.0, resolve_secret=_resolve
        )
        assert seen == ["council-srt"]

    def test_no_handle_means_no_credential_argument(self, captured_argv: list[list[str]]) -> None:
        observe_live_source(_source(), timeout_seconds=2.0, resolve_secret=lambda _h: _SECRET)
        assert "-passphrase" not in captured_argv[0]


class TestFailClosed:
    def test_an_unresolvable_handle_fails_the_probe(self, captured_argv: list[list[str]]) -> None:
        observation = observe_live_source(
            _source(handle="council-srt"), timeout_seconds=2.0, resolve_secret=lambda _h: None
        )
        assert observation.ok is False
        assert observation.error_code == ERROR_CREDENTIALS_UNRESOLVED
        assert captured_argv == [], "ffprobe must not run unauthenticated"
        assert "council-srt" in observation.detail
        assert "credential store" in observation.detail

    def test_a_raising_resolver_fails_closed_without_leaking(
        self, captured_argv: list[list[str]]
    ) -> None:
        def _explode(_handle: str) -> str:
            raise RuntimeError(f"keyring backend blew up holding {_SECRET}")

        observation = observe_live_source(
            _source(handle="council-srt"), timeout_seconds=2.0, resolve_secret=_explode
        )
        assert observation.ok is False
        assert observation.error_code == ERROR_CREDENTIALS_UNRESOLVED
        assert _SECRET not in observation.detail

    def test_no_resolver_at_all_fails_closed(self, captured_argv: list[list[str]]) -> None:
        observation = observe_live_source(
            _source(handle="council-srt"), timeout_seconds=2.0, resolve_secret=None
        )
        assert observation.ok is False
        assert observation.error_code == ERROR_CREDENTIALS_UNRESOLVED

    @pytest.mark.parametrize("source_type", ["rtsp", "rtmp", "ndi"])
    def test_a_legacy_handle_on_an_unsupported_type_is_refused(
        self, captured_argv: list[list[str]], source_type: str
    ) -> None:
        # Validation blocks this shape at write time; a row that predates the
        # rule still must not be probed as if the credential were applied.
        observation = observe_live_source(
            _source(source_type=source_type, handle="cam-password"),
            timeout_seconds=2.0,
            resolve_secret=lambda _h: _SECRET,
        )
        assert observation.ok is False
        assert observation.error_code == ERROR_CREDENTIALS_UNSUPPORTED
        assert captured_argv == []
        # Real copy the operator can act on, not a code.
        assert len(observation.detail.split()) > 10


class TestRedaction:
    def test_a_secret_echoed_in_ffprobe_stderr_is_scrubbed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("civiccast.live.source_probe.shutil.which", lambda _n: "ffprobe")
        monkeypatch.setattr(
            "civiccast.live.source_probe.subprocess.run",
            lambda *_a, **_k: _Completed(
                returncode=1, stderr=f"srt: bad passphrase '{_SECRET}' rejected by peer"
            ),
        )
        observation = observe_live_source(
            _source(handle="council-srt"), timeout_seconds=2.0, resolve_secret=lambda _h: _SECRET
        )
        assert observation.ok is False
        assert _SECRET not in observation.detail
        assert "[redacted]" in observation.detail

    def test_a_secret_in_a_timeout_message_is_scrubbed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import subprocess

        monkeypatch.setattr("civiccast.live.source_probe.shutil.which", lambda _n: "ffprobe")

        def _timeout(*_a, **_k):  # type: ignore[no-untyped-def]
            raise subprocess.TimeoutExpired(cmd=["ffprobe"], timeout=2.0)

        monkeypatch.setattr("civiccast.live.source_probe.subprocess.run", _timeout)
        # A pathological source whose ENDPOINT happens to contain the secret
        # string; the endpoint is quoted into the timeout message.
        source = _source(endpoint=f"srt://host:9000?streamid={_SECRET}", handle="council-srt")
        observation = observe_live_source(
            source, timeout_seconds=2.0, resolve_secret=lambda _h: _SECRET
        )
        assert _SECRET not in observation.detail

    def test_short_values_are_not_redacted_into_gibberish(self) -> None:
        # Replacing every occurrence of a two-character "secret" would corrupt
        # a useful diagnostic without protecting anything.
        assert redact_secrets("Connection refused at 10.0.0.5", ["0."]) == (
            "Connection refused at 10.0.0.5"
        )

    def test_redaction_handles_a_bare_string_and_an_empty_input(self) -> None:
        assert redact_secrets(f"saw {_SECRET} here", _SECRET) == "saw [redacted] here"
        assert redact_secrets("", [_SECRET]) == ""
        assert redact_secrets("nothing here", []) == "nothing here"
