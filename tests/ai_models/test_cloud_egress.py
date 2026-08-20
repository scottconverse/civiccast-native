# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S13 cloud egress guard — the INVERSE of the local loopback guard.

``_require_cloud_https`` must let credentialed traffic LEAVE the box (cloud is
off-box by definition) while a misconfigured base URL can never exfiltrate to an
arbitrary host: https-only, NOT loopback, and host must be on a hard-coded
allowlist. This file also asserts the LOCAL ``_require_local_http`` is unchanged
(a regression guard proving the local default was never loosened — spec line 30).
"""

from __future__ import annotations

import io
import urllib.error
import urllib.request

import pytest

from civiccast.ai_models.cloud import egress
from civiccast.ai_models.cloud.egress import (
    CloudEgressError,
    CloudRuntimeUnavailableError,
    require_cloud_https,
)
from civiccast.ai_models.cloud.ollama_cloud import OllamaCloudAdapter
from civiccast.ai_runtime.ollama_client import (
    OllamaRuntimeUnavailableError,
    _require_local_http,
)

_ALLOWED = frozenset({"ollama.com"})


def test_cloud_guard_accepts_allowlisted_https_host() -> None:
    # The happy path: https + off-box + allowlisted -> no raise.
    require_cloud_https("https://ollama.com/api/generate", allowed_hosts=_ALLOWED)


def test_cloud_guard_rejects_plain_http() -> None:
    with pytest.raises(CloudEgressError, match=r"https"):
        require_cloud_https("http://ollama.com/api/generate", allowed_hosts=_ALLOWED)


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "localhost", "[::1]"],  # IPv6 literal is bracketed in a URL authority.
)
def test_cloud_guard_rejects_loopback(host: str) -> None:
    # Cloud must leave the box; loopback is the local client's job, never cloud's.
    url = f"https://{host}/api/generate"
    with pytest.raises(CloudEgressError, match=r"loopback|off-box|local"):
        require_cloud_https(url, allowed_hosts=_ALLOWED)


def test_cloud_guard_rejects_non_allowlisted_host() -> None:
    # A misconfigured/hostile base URL must not be able to exfiltrate.
    with pytest.raises(CloudEgressError, match=r"allow"):
        require_cloud_https("https://evil.example.com/api/generate", allowed_hosts=_ALLOWED)


def test_cloud_guard_rejects_lookalike_subdomain() -> None:
    # Exact-host allowlist: "ollama.com.evil.com" must NOT pass.
    with pytest.raises(CloudEgressError):
        require_cloud_https("https://ollama.com.evil.com/api/generate", allowed_hosts=_ALLOWED)


# --- Regression guard: the LOCAL default must remain loopback-only -----------


@pytest.mark.parametrize("host", ["ollama.com", "openrouter.ai", "evil.example.com"])
def test_local_guard_still_rejects_every_non_loopback_host(host: str) -> None:
    # Proves slice 3 did NOT loosen _require_local_http to reach the network.
    with pytest.raises(OllamaRuntimeUnavailableError):
        _require_local_http(f"https://{host}/api/generate")


@pytest.mark.parametrize("url", ["http://127.0.0.1:11434/api/tags", "https://localhost:11434/x"])
def test_local_guard_still_accepts_loopback(url: str) -> None:
    # Existing local behavior unchanged.
    _require_local_http(url)


# --- Redirect guard: a 3xx off the allowlisted host must NOT be followed ------


class _FakeResponse(io.BytesIO):
    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


@pytest.mark.parametrize(
    "redirect_target",
    [
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata endpoint (SSRF)
        "https://evil.example.com/steal",  # off-allowlist exfil host
    ],
)
def test_no_redirect_handler_refuses_redirect(redirect_target: str) -> None:
    # The handler must REFUSE (return None) so urllib does not re-issue the request
    # to the redirect target with the bearer header attached.
    handler = egress._NoRedirectHandler()
    req = urllib.request.Request("https://ollama.com/api/generate")
    result = handler.redirect_request(
        req, io.BytesIO(b""), 302, "Found", {"location": redirect_target}, redirect_target
    )
    assert result is None


def test_cloud_opener_has_no_redirect_following() -> None:
    # The dedicated cloud opener carries our no-redirect handler (so a 3xx is never
    # auto-followed), and we did NOT mutate urllib's process-wide default opener.
    handlers = egress._CLOUD_OPENER.handlers
    assert any(isinstance(h, egress._NoRedirectHandler) for h in handlers)


def test_adapter_redirect_does_not_egress_to_off_allowlist_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # End-to-end: a malicious 302 from the allowlisted host to the metadata endpoint
    # must surface as a typed runtime error with the bearer token NEVER sent to the
    # redirect target. We simulate the no-redirect opener raising HTTPError (urllib's
    # behavior once redirect_request returns None) and assert the only request seen is
    # the original allowlisted POST.
    seen_urls: list[str] = []

    def fake_urlopen(request: urllib.request.Request, *, timeout: object = None) -> None:
        seen_urls.append(request.full_url)
        # urllib raises the unhandled 3xx as HTTPError (an OSError subclass).
        raise urllib.error.HTTPError(
            request.full_url,
            302,
            "Found",
            {"Location": "http://169.254.169.254/latest/meta-data/"},  # type: ignore[arg-type]
            io.BytesIO(b""),
        )

    monkeypatch.setattr(egress, "urlopen", fake_urlopen)
    adapter = OllamaCloudAdapter(
        model_key="gemma4-31b-cloud",
        credential_ref="ollama-cloud-key",
        resolve_secret=lambda ref: "oc-secret-token",
        consent_accepted=True,
    )
    with pytest.raises(CloudRuntimeUnavailableError):
        adapter.generate(prompt="hello")
    # Only the original allowlisted host was contacted; the metadata host never was.
    assert seen_urls == ["https://ollama.com/api/generate"]
    assert all("169.254.169.254" not in url for url in seen_urls)
