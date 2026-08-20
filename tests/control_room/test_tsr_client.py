# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S16 build step 9 slice 2d — Python HttpTsrClient + license-hygiene guard.

HttpTsrClient is tested against a real httpx stack with a MockTransport (no
network, no Node sidecar): success mapping, secret resolution over loopback,
and the fail-closed TsrClientError on non-200 / transport error / bad body.
The license guard asserts the Apache tree vendors only TSR (MIT) and no
GPL/AGPL device-control source.
"""

from __future__ import annotations

import json
import pathlib
from datetime import UTC, datetime

import httpx
import pytest

from civiccast.control_room.models import DeviceProfile, ProductionDevice
from civiccast.control_room.tsr_client import HttpTsrClient, TsrClientError

_T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _device(**kw) -> ProductionDevice:
    base: dict = {
        "device_id": "dev_obs",
        "label": "OBS",
        "kind": "obs",
        "transport": "websocket",
        "host": "127.0.0.1",
        "port": 4455,
        "created_at": _T0,
        "updated_at": _T0,
    }
    base.update(kw)
    return ProductionDevice(**base)  # type: ignore[arg-type]


def _profile() -> DeviceProfile:
    return DeviceProfile(
        profile_id="p",
        device_id="dev_obs",
        tsr_device_type="OBS",
        options={"port": 4455},
        created_at=_T0,
        updated_at=_T0,
    )


def _client(handler, *, secret_resolver=None) -> HttpTsrClient:
    return HttpTsrClient(
        "http://127.0.0.1:7717",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        secret_resolver=secret_resolver,
    )


def test_constructor_accepts_loopback_only_urls() -> None:
    for url in (
        "http://127.0.0.1:7717",
        "http://localhost:7717/",
        "http://[::1]:7717",
    ):
        client = HttpTsrClient(
            url,
            client=httpx.Client(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, json={"reachable": True})
                )
            ),
        )
        assert client is not None


@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.1.20:7717",
        "http://10.1.10.114:7717",
        "http://example.com:7717",
        "http://user:pass@127.0.0.1:7717",
        "ws://127.0.0.1:7717",
        "127.0.0.1:7717",
    ],
)
def test_constructor_rejects_non_loopback_or_credentialed_urls(url: str) -> None:
    with pytest.raises(ValueError):
        HttpTsrClient(
            url,
            secret_resolver=lambda ref: pytest.fail(f"secret resolver was called for {ref}"),
        )


def test_health_maps_sidecar_healthz_without_resolving_secret() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/healthz"
        return httpx.Response(200, json={"ok": True, "tsr": "9.3.2"})

    client = HttpTsrClient(
        "http://127.0.0.1:7717",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        secret_resolver=lambda ref: pytest.fail(f"secret resolver was called for {ref}"),
    )

    result = client.health()

    assert result.reachable is True
    assert result.capability_map == {"tsr": "9.3.2"}


def test_health_unreachable_raises_tsrclienterror() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(TsrClientError, match="unreachable"):
        HttpTsrClient(
            "http://127.0.0.1:7717",
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        ).health()


def test_apply_cue_maps_success_and_sends_action() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"ok": True, "detail": "", "device_state": {"scene": "CAM2"}}
        )

    r = _client(handler).apply_cue(
        device=_device(), profile=_profile(), action="scene", payload={"scene": "CAM2"}
    )
    assert r.ok is True
    assert r.device_state["scene"] == "CAM2"
    assert captured["body"]["action"] == "scene"
    assert captured["body"]["device"]["kind"] == "obs"
    assert captured["body"]["device"]["options"] == {"port": 4455}


def test_apply_resolves_secret_from_keyring_over_loopback() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    client = _client(handler, secret_resolver=lambda ref: "hunter2" if ref == "kr1" else None)
    client.apply_cue(device=_device(secret_ref="kr1"), profile=None, action="scene", payload={})
    # the resolved secret is sent over loopback to the sidecar, never persisted in the request object
    assert captured["body"]["device"]["secret"] == "hunter2"


def test_no_secret_ref_sends_no_secret() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    _client(handler).apply_cue(
        device=_device(secret_ref=None), profile=None, action="scene", payload={}
    )
    assert "secret" not in captured["body"]["device"]


def test_non_200_raises_tsrclienterror() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"ok": False, "detail": "device rejected"})

    with pytest.raises(TsrClientError):
        _client(handler).probe_device(device=_device(), profile=None)


def test_transport_error_raises_tsrclienterror() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(TsrClientError):
        _client(handler).apply_cue(device=_device(), profile=None, action="scene", payload={})


def test_apply_rejected_when_sidecar_returns_ok_false() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "detail": "scene not found"})

    with pytest.raises(TsrClientError):
        _client(handler).apply_cue(device=_device(), profile=None, action="scene", payload={})


def test_probe_maps_reachability_and_capabilities() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"reachable": True, "capability_map": {"cues": ["scene"]}, "detail": ""}
        )

    r = _client(handler).probe_device(device=_device(), profile=_profile())
    assert r.reachable is True
    assert r.capability_map["cues"] == ["scene"]


# --- license-hygiene guard ---------------------------------------------------


def test_control_room_vendors_only_mit_tsr_no_gpl_source() -> None:
    """The Apache control_room tree must vendor only TSR (MIT). OBS / obs-websocket /
    CasparCG / SuperConductor are reached over sockets as separate processes (or
    read as worked examples) — never vendored/linked."""
    root = pathlib.Path(__file__).resolve().parents[2] / "civiccast" / "control_room"
    pkg = json.loads((root / "tsr_service" / "package.json").read_text(encoding="utf-8"))
    assert set(pkg.get("dependencies", {})) == {"timeline-state-resolver"}, pkg.get("dependencies")
    # No GPL/AGPL device-control source vendored into the committed tree
    # (node_modules is gitignored and not committed).
    forbidden = ("obs-websocket", "casparcg", "superconductor", "sofie-core")
    for p in root.rglob("*"):
        if "node_modules" in p.parts or not p.is_file():
            continue
        assert not any(f in p.name.lower() for f in forbidden), f"GPL/AGPL artifact vendored: {p}"
