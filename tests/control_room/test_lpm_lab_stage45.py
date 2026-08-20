# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Stage 4-5 LPM lab executable fixture tests."""

from __future__ import annotations

import base64
import hashlib
import json
import socket
import threading
from collections.abc import Callable
from pathlib import Path

import pytest

import civiccast.control_room.lpm_lab_stage45 as stage45
from civiccast.control_room.lpm_lab_harness import run_lpm_contract_lab
from civiccast.control_room.lpm_lab_stage45 import (
    REFERENCE_URLS,
    _obs_websocket_auth,
    _probe_obs,
    _require_usb_audio_present,
    parse_vmix_status_xml,
    validate_atem_state_fixture,
    validate_audio_control_not_claimed,
    validate_audio_topology_fixture,
    validate_capture_identity_fixture,
    validate_midi_nrpn_message,
    validate_midi_scene_recall,
    validate_ndi_source_disappears,
    validate_ndi_source_list,
    validate_ndi_source_present,
    validate_ndi_source_reappears,
    validate_ndi_source_rename,
    validate_obs_websocket_5_frames,
    validate_obs_websocket_disabled,
    validate_sq_midi_mute_message,
    validate_tsr_sidecar_restart,
    validate_usb_audio_sample_rate,
    validate_usb_audio_sync_delay,
    validate_visca_udp_exchange,
    validate_vmix_api_disabled,
    validate_vmix_auth_response,
    validate_vmix_capture_identity,
    validate_vmix_input_identity,
    validate_vmix_input_removed,
    validate_vmix_input_select,
    validate_vmix_resource_ceiling,
)


def test_vmix_status_xml_parser_accepts_required_status_shape() -> None:
    state = parse_vmix_status_xml(
        """
        <vmix>
          <version>29.0.0.48</version>
          <inputs>
            <input key="a" number="1" title="Program" state="Running">Program</input>
            <input key="b" number="2" title="Preview" state="Running">Preview</input>
          </inputs>
          <active>1</active>
          <preview>2</preview>
          <recording>False</recording>
          <streaming>True</streaming>
        </vmix>
        """
    )

    assert state.version == "29.0.0.48"
    assert state.active == 1
    assert state.preview == 2
    assert state.streaming is True
    assert [item.title for item in state.inputs] == ["Program", "Preview"]


def test_vmix_status_xml_parser_rejects_schema_drift() -> None:
    with pytest.raises(ValueError, match="preview"):
        parse_vmix_status_xml(
            """
            <vmix>
              <version>29.0.0.48</version>
              <inputs><input key="a" number="1" title="Program">Program</input></inputs>
              <active>1</active>
              <recording>False</recording>
              <streaming>False</streaming>
            </vmix>
            """
        )

    with pytest.raises(ValueError, match="root"):
        parse_vmix_status_xml("<not-vmix />")

    with pytest.raises(ValueError, match="boolean"):
        parse_vmix_status_xml(
            """
            <vmix>
              <version>29.0.0.48</version>
              <inputs><input key="a" number="1" title="Program">Program</input></inputs>
              <active>1</active>
              <preview>1</preview>
              <recording>Maybe</recording>
              <streaming>False</streaming>
            </vmix>
            """
        )

    with pytest.raises(ValueError, match="active/preview"):
        parse_vmix_status_xml(
            """
            <vmix>
              <version>29.0.0.48</version>
              <inputs><input key="a" number="1" title="Program">Program</input></inputs>
              <active>2</active>
              <preview>1</preview>
              <recording>False</recording>
              <streaming>False</streaming>
            </vmix>
            """
        )


def test_obs_websocket_5_fixture_requires_correlated_responses() -> None:
    state = validate_obs_websocket_5_frames(
        json.loads(
            """
            [
              {"op": 0, "d": {"obsWebSocketVersion": "5.5.4", "rpcVersion": 1}},
              {"op": 6, "d": {"requestType": "GetRecordStatus", "requestId": "req-1"}},
              {"op": 7, "d": {"requestId": "req-1", "requestStatus": {"result": true, "code": 100}}},
              {"op": 5, "d": {"eventType": "RecordStateChanged", "eventIntent": 64}}
            ]
            """
        )
    )

    assert state.rpc_version == 1
    assert state.request_ids == ["req-1"]
    assert state.event_types == ["RecordStateChanged"]


def test_obs_websocket_5_fixture_rejects_unmatched_response() -> None:
    with pytest.raises(ValueError, match="does not match"):
        validate_obs_websocket_5_frames(
            [
                {"op": 0, "d": {"obsWebSocketVersion": "5.5.4", "rpcVersion": 1}},
                {"op": 7, "d": {"requestId": "ghost", "requestStatus": {"result": True}}},
            ]
        )

    with pytest.raises(ValueError, match="Duplicate"):
        validate_obs_websocket_5_frames(
            [
                {"op": 0, "d": {"obsWebSocketVersion": "5.5.4", "rpcVersion": 1}},
                {"op": 6, "d": {"requestType": "GetVersion", "requestId": "dup"}},
                {"op": 6, "d": {"requestType": "GetRecordStatus", "requestId": "dup"}},
            ]
        )

    with pytest.raises(ValueError, match="without responses"):
        validate_obs_websocket_5_frames(
            [
                {"op": 0, "d": {"obsWebSocketVersion": "5.5.4", "rpcVersion": 1}},
                {"op": 6, "d": {"requestType": "GetVersion", "requestId": "lonely"}},
            ]
        )


def test_obs_software_probe_rejects_plain_tcp_listener() -> None:
    port, thread = _serve_once(lambda conn: conn.sendall(b"not a websocket"))

    result = _probe_obs("127.0.0.1", port, 1.0)
    thread.join(timeout=2)

    assert result["reachable"] is False
    assert "protocol probe failed" in result["observed"]


def test_obs_software_probe_rejects_protocol_valid_listener_without_obs_process_identity() -> None:
    def handler(conn: socket.socket) -> None:
        request = _recv_until(conn, b"\r\n\r\n")
        key = _http_header(request, "Sec-WebSocket-Key")
        accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        ).decode("ascii")
        conn.sendall(
            (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n"
                "\r\n"
            ).encode("ascii")
        )
        _send_server_ws_json(
            conn, {"op": 0, "d": {"obsWebSocketVersion": "5.5.4", "rpcVersion": 1}}
        )
        assert _read_client_ws_json(conn)["op"] == 1
        _send_server_ws_json(conn, {"op": 2, "d": {"negotiatedRpcVersion": 1}})
        request_frame = _read_client_ws_json(conn)
        assert request_frame["d"]["requestId"] == "civiccast-probe-get-version"
        _send_server_ws_json(
            conn,
            {
                "op": 7,
                "d": {
                    "requestType": "GetVersion",
                    "requestId": "civiccast-probe-get-version",
                    "requestStatus": {"result": True, "code": 100},
                    "responseData": {
                        "obsVersion": "32.1.2",
                        "obsWebSocketVersion": "5.5.4",
                        "rpcVersion": 1,
                        "platform": "windows",
                    },
                },
            },
        )

    port, thread = _serve_once(handler)

    result = _probe_obs("127.0.0.1", port, 1.0)
    thread.join(timeout=2)

    assert result["reachable"] is False
    assert "process identity was not verified" in result["observed"]


def test_listener_identity_dependency_absence_is_structured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(stage45.os, "name", "nt")
    monkeypatch.setattr(stage45, "_load_psutil", lambda: None)

    result = stage45._verify_tcp_listener_process(
        port=4455,
        expected_process_names={"obs64", "obs"},
        expected_executable="C:/Program Files/obs-studio/bin/64bit/obs64.exe",
    )

    assert result["verified"] is False
    assert "psutil dependency is not installed" in result["observed"]


def test_listener_identity_requires_loopback_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeAddress:
        ip = "0.0.0.0"
        port = 4455

    class FakeConnection:
        laddr = FakeAddress()
        pid = 7
        status = "LISTEN"

    class FakeProcess:
        def __init__(self, _pid: int) -> None:
            pass

        def name(self) -> str:
            return "obs64.exe"

        def exe(self) -> str:
            return "C:/Program Files/obs-studio/bin/64bit/obs64.exe"

    class FakePsutil:
        CONN_LISTEN = "LISTEN"
        Error = OSError

        @staticmethod
        def net_connections(kind: str) -> list[FakeConnection]:
            assert kind == "tcp"
            return [FakeConnection()]

        Process = FakeProcess

    monkeypatch.setattr(stage45.os, "name", "nt")
    monkeypatch.setattr(stage45, "_load_psutil", lambda: FakePsutil)
    monkeypatch.setattr(stage45, "_windows_firewall_confines_port", lambda _port: False)

    result = stage45._verify_tcp_listener_process(
        port=4455,
        expected_process_names={"obs64", "obs"},
        expected_executable="C:/Program Files/obs-studio/bin/64bit/obs64.exe",
    )

    assert result["verified"] is True
    assert result["loopback_bound"] is False
    assert result["network_confined"] is False
    assert result["non_loopback_addresses"] == ["0.0.0.0"]
    assert "not loopback-bound" in result["observed"]


def test_software_probe_records_unconfined_listener_without_security_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        stage45,
        "_probe_vmix",
        lambda url, timeout_seconds: {
            "reachable": True,
            "software_class": "vmix",
            "url": url,
            "executable": "C:/Program Files/vMix/vMix64.exe",
            "listener_process": {
                "verified": True,
                "network_confined": False,
                "observed": "listener pid=5; not loopback-bound",
            },
            "observed": "vMix HTTP API returned version 29.0.0.48 with 2 input(s).",
        },
    )

    result = run_lpm_contract_lab(
        execution_stage="stage45",
        profile_ids=["fixed-studio-livestreaming"],
        probe_real_software=True,
        require_software_lab=True,
    )

    probe = next(event for event in result.events if event.check_id == "software-probe-vmix-http")
    # Overall status is honestly "failed" because other required checks on this
    # profile (e.g. usb-audio-present) have no Stage 4-5 fixture yet; the vmix
    # probe itself passed.
    assert result.status == "failed"
    assert probe.status == "passed"
    assert probe.proof_level == "software-lab-proven"
    assert "not network-confined" in (probe.not_claimed or "")


def test_obs_websocket_auth_matches_obs_protocol() -> None:
    password = "lab-secret"
    salt = "salt-value"
    challenge = "challenge-value"
    secret = base64.b64encode(hashlib.sha256((password + salt).encode("utf-8")).digest()).decode(
        "ascii"
    )
    expected = base64.b64encode(
        hashlib.sha256((secret + challenge).encode("utf-8")).digest()
    ).decode("ascii")

    assert _obs_websocket_auth(password=password, salt=salt, challenge=challenge) == expected


def test_listener_identity_records_loopback_listener_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeAddress:
        ip = "127.0.0.1"
        port = 4455

    class FakeConnection:
        laddr = FakeAddress()
        pid = 7
        status = "LISTEN"

    class FakeProcess:
        def __init__(self, _pid: int) -> None:
            pass

        def name(self) -> str:
            return "obs64.exe"

        def exe(self) -> str:
            return "C:/Program Files/obs-studio/bin/64bit/obs64.exe"

    class FakePsutil:
        CONN_LISTEN = "LISTEN"
        Error = OSError

        @staticmethod
        def net_connections(kind: str) -> list[FakeConnection]:
            assert kind == "tcp"
            return [FakeConnection()]

        Process = FakeProcess

    monkeypatch.setattr(stage45.os, "name", "nt")
    monkeypatch.setattr(stage45, "_load_psutil", lambda: FakePsutil)
    monkeypatch.setattr(stage45, "_windows_firewall_confines_port", lambda _port: False)

    result = stage45._verify_tcp_listener_process(
        port=4455,
        expected_process_names={"obs64", "obs"},
        expected_executable="C:/Program Files/obs-studio/bin/64bit/obs64.exe",
    )

    assert result["verified"] is True
    assert result["loopback_bound"] is True
    assert result["local_address"] == "127.0.0.1"
    assert result["listeners"] == [
        {
            "pid": 7,
            "process_name": "obs64.exe",
            "path": "C:/Program Files/obs-studio/bin/64bit/obs64.exe",
            "local_address": "127.0.0.1",
            "local_port": 4455,
        }
    ]


def test_visca_udp_exchange_requires_ack_and_completion() -> None:
    assert validate_visca_udp_exchange("81 01 04 3F 02 01 FF", ["90 41 FF", "90 51 FF"]) == {
        "command_bytes": 7,
        "responses": 2,
        "ack": True,
        "completion": True,
    }

    with pytest.raises(ValueError, match="ACK and completion"):
        validate_visca_udp_exchange("81 01 04 3F 02 01 FF", ["90 41 FF"])


def test_atem_and_capture_fixtures_validate_required_contract_fields() -> None:
    atem = validate_atem_state_fixture(
        {
            "protocol_version": "atem-connection-3.x",
            "program_input": 1,
            "preview_input": 2,
            "in_transition": False,
        }
    )
    assert atem["program_input"] == 1

    capture = validate_capture_identity_fixture(
        {"devices": [{"name": "Cam Link HDMI", "class": "uvc-video", "stable_id": "usbvid-0001"}]}
    )
    assert capture["device_count"] == 1

    with pytest.raises(ValueError, match="stable_id"):
        validate_capture_identity_fixture(
            {"devices": [{"name": "Cam Link HDMI", "class": "uvc-video"}]}
        )


def _vmix_status_xml(
    *,
    active: int,
    preview: int,
    input2_key: str = "vmix-cam-2",
    input2_title: str = "Cam Link HDMI",
) -> str:
    return f"""
    <vmix>
      <version>29.0.0.48</version>
      <inputs>
        <input key="vmix-cam-1" number="1" type="Camera" title="DeckLink Duo 2" state="Running">DeckLink Duo 2</input>
        <input key="{input2_key}" number="2" type="Camera" title="{input2_title}" state="Running">{input2_title}</input>
      </inputs>
      <active>{active}</active>
      <preview>{preview}</preview>
      <recording>False</recording>
      <streaming>True</streaming>
    </vmix>
    """


def test_vmix_input_select_accepts_preserved_identity() -> None:
    before = parse_vmix_status_xml(_vmix_status_xml(active=1, preview=2))
    after = parse_vmix_status_xml(_vmix_status_xml(active=2, preview=1))

    result = validate_vmix_input_select(before, after, requested_number=2)

    assert result == {"input_number": 2, "key": "vmix-cam-2", "title": "Cam Link HDMI"}


def test_vmix_input_select_rejects_mutated_identity_on_select() -> None:
    before = parse_vmix_status_xml(_vmix_status_xml(active=1, preview=2))
    mutated_after = parse_vmix_status_xml(
        _vmix_status_xml(active=2, preview=1, input2_key="vmix-cam-2-swapped")
    )

    with pytest.raises(ValueError, match="key changed on select"):
        validate_vmix_input_select(before, mutated_after, requested_number=2)


def test_vmix_input_select_rejects_select_that_never_activated() -> None:
    before = parse_vmix_status_xml(_vmix_status_xml(active=1, preview=2))
    stuck = parse_vmix_status_xml(_vmix_status_xml(active=1, preview=2))

    with pytest.raises(ValueError, match="must make input 2 active"):
        validate_vmix_input_select(before, stuck, requested_number=2)


def test_tsr_sidecar_restart_accepts_fresh_fetch_after_restart() -> None:
    result = validate_tsr_sidecar_restart(
        {"healthy": True, "fetched_at_unix": 100.0},
        {"restarted_at_unix": 110.0},
        {"healthy": True, "fetched_at_unix": 112.0},
    )

    assert result["recovered"] is True


def test_tsr_sidecar_restart_rejects_jump_straight_to_recovered() -> None:
    """The forbidden theater pattern: post-restart state reuses a fetch that
    predates (or coincides with) the restart, i.e. no fresh heartbeat ever
    happened. This must be rejected, not accepted as recovery."""

    with pytest.raises(ValueError, match="was not fetched after the restart"):
        validate_tsr_sidecar_restart(
            {"healthy": True, "fetched_at_unix": 100.0},
            {"restarted_at_unix": 110.0},
            {"healthy": True, "fetched_at_unix": 105.0},
        )


def test_ndi_source_list_rejects_malformed_entry() -> None:
    with pytest.raises(ValueError, match="requires a url_address"):
        validate_ndi_source_list([{"name": "Camera 1"}])


def test_ndi_source_present_accepts_expected_name() -> None:
    result = validate_ndi_source_present(
        [{"name": "Camera 1", "url_address": "10.0.0.5:5961", "last_seen_unix": 1.0}],
        expected_name="Camera 1",
    )
    assert result["name"] == "Camera 1"


def test_ndi_source_present_rejects_absent_source() -> None:
    with pytest.raises(ValueError, match="is not present in the discovery list"):
        validate_ndi_source_present(
            [{"name": "Camera 2", "url_address": "10.0.0.6:5961", "last_seen_unix": 1.0}],
            expected_name="Camera 1",
        )


def test_ndi_source_disappears_rejects_source_still_present_in_after() -> None:
    before = [{"name": "Camera 1", "url_address": "10.0.0.5:5961", "last_seen_unix": 1.0}]
    still_there = [{"name": "Camera 1", "url_address": "10.0.0.5:5961", "last_seen_unix": 2.0}]

    with pytest.raises(ValueError, match="still present in the 'after' list"):
        validate_ndi_source_disappears(before, still_there, tracked_name="Camera 1")


def test_ndi_source_reappears_rejects_missing_intervening_absence() -> None:
    always_present = [{"name": "Camera 1", "url_address": "10.0.0.5:5961", "last_seen_unix": 1.0}]

    with pytest.raises(ValueError, match="no intervening"):
        validate_ndi_source_reappears(
            [always_present, always_present, always_present], tracked_name="Camera 1"
        )


def test_ndi_source_rename_accepts_same_stable_id_new_display_name() -> None:
    before = [{"name": "Camera 1", "url_address": "10.0.0.5:5961", "last_seen_unix": 1.0}]
    after = [{"name": "Podium Camera", "url_address": "10.0.0.5:5961", "last_seen_unix": 2.0}]

    result = validate_ndi_source_rename(before, after, stable_id="10.0.0.5:5961")
    assert result == {
        "stable_id": "10.0.0.5:5961",
        "old_name": "Camera 1",
        "new_name": "Podium Camera",
        "renamed": True,
    }


def test_ndi_source_rename_rejects_stable_id_missing_from_after() -> None:
    """The broken-fixture case: the tracked source's stable id (url_address)
    changes under the rename, so the renamed source is indistinguishable from
    the old one simply being lost."""

    before = [{"name": "Camera 1", "url_address": "10.0.0.5:5961", "last_seen_unix": 1.0}]
    after = [{"name": "Podium Camera", "url_address": "10.0.0.9:5961", "last_seen_unix": 2.0}]

    with pytest.raises(ValueError, match="the source was treated as lost"):
        validate_ndi_source_rename(before, after, stable_id="10.0.0.5:5961")


def test_ndi_source_rename_rejects_old_name_reappearing_under_a_new_stable_id() -> None:
    """If the old display name shows up again at a *different* url_address,
    that is the old source being treated as lost and a new one appearing --
    not a tracked rename -- and must be rejected."""

    before = [{"name": "Camera 1", "url_address": "10.0.0.5:5961", "last_seen_unix": 1.0}]
    after = [
        {"name": "Podium Camera", "url_address": "10.0.0.5:5961", "last_seen_unix": 2.0},
        {"name": "Camera 1", "url_address": "10.0.0.9:5961", "last_seen_unix": 2.0},
    ]

    with pytest.raises(ValueError, match="mistaken for the old source disappearing"):
        validate_ndi_source_rename(before, after, stable_id="10.0.0.5:5961")


def test_ndi_source_rename_rejects_missing_from_before() -> None:
    before = [{"name": "Camera 2", "url_address": "10.0.0.6:5961", "last_seen_unix": 1.0}]
    after = [{"name": "Podium Camera", "url_address": "10.0.0.5:5961", "last_seen_unix": 2.0}]

    with pytest.raises(ValueError, match="must be present in the 'before' list"):
        validate_ndi_source_rename(before, after, stable_id="10.0.0.5:5961")


def test_ndi_source_rename_rejects_unchanged_display_name() -> None:
    before = [{"name": "Camera 1", "url_address": "10.0.0.5:5961", "last_seen_unix": 1.0}]
    after = [{"name": "Camera 1", "url_address": "10.0.0.5:5961", "last_seen_unix": 2.0}]

    with pytest.raises(ValueError, match="must change the display name"):
        validate_ndi_source_rename(before, after, stable_id="10.0.0.5:5961")


def test_vmix_api_disabled_accepts_connect_error_reason() -> None:
    result = validate_vmix_api_disabled("connection refused")
    assert result == {"reachable": False, "reason": "connection refused"}


def test_vmix_api_disabled_rejects_missing_connect_error() -> None:
    with pytest.raises(ValueError, match="requires a connect_error reason"):
        validate_vmix_api_disabled(None)


def test_vmix_api_disabled_rejects_a_success_shaped_body() -> None:
    """A live/reachable vMix status XML body must never be accepted as proof
    the controller is disabled -- that would let a real response be mistaken
    for an outage."""

    success_body = """
        <vmix>
          <version>29.0.0.48</version>
          <inputs><input key="a" number="1" title="Program">Program</input></inputs>
          <active>1</active>
          <preview>1</preview>
          <recording>False</recording>
          <streaming>False</streaming>
        </vmix>
        """
    with pytest.raises(ValueError, match="contradicts itself"):
        validate_vmix_api_disabled("connection refused", success_body)


def test_obs_websocket_disabled_accepts_connect_error_reason() -> None:
    result = validate_obs_websocket_disabled("connection refused")
    assert result == {"reachable": False, "reason": "connection refused"}


def test_obs_websocket_disabled_rejects_missing_connect_error() -> None:
    with pytest.raises(ValueError, match="requires a connect_error reason"):
        validate_obs_websocket_disabled(None)


def test_obs_websocket_disabled_rejects_a_success_shaped_frame_stream() -> None:
    """A live/reachable OBS Hello frame must never be accepted as proof the
    websocket is disabled -- that would let a real session be mistaken for
    an outage."""

    success_frames = [{"op": 0, "d": {"obsWebSocketVersion": "5.5.4", "rpcVersion": 1}}]
    with pytest.raises(ValueError, match="contradicts itself"):
        validate_obs_websocket_disabled("connection refused", success_frames)


def test_vmix_auth_response_accepts_401_with_challenge() -> None:
    result = validate_vmix_auth_response(
        status_code=401, www_authenticate_header="Basic realm=vMix"
    )
    assert result["status_code"] == 401


def test_vmix_auth_response_rejects_200_ok_as_if_auth_enforced() -> None:
    with pytest.raises(ValueError, match="requires a 401 or 403 status"):
        validate_vmix_auth_response(status_code=200, www_authenticate_header=None)


def test_vmix_auth_response_rejects_401_without_challenge_header() -> None:
    with pytest.raises(ValueError, match="requires a WWW-Authenticate challenge header"):
        validate_vmix_auth_response(status_code=401, www_authenticate_header=None)


def test_vmix_input_identity_drift_rejects_changed_key_number() -> None:
    dry_run = parse_vmix_status_xml(_vmix_status_xml(active=1, preview=2))
    drifted_live = parse_vmix_status_xml(
        _vmix_status_xml(active=1, preview=2, input2_key="vmix-cam-2-different")
    )

    with pytest.raises(ValueError, match="changed key/number before live fire"):
        validate_vmix_input_identity(dry_run, drifted_live, input_number=2)


def test_vmix_input_identity_accepts_matching_snapshots() -> None:
    dry_run = parse_vmix_status_xml(_vmix_status_xml(active=1, preview=2))
    live = parse_vmix_status_xml(_vmix_status_xml(active=1, preview=2))

    result = validate_vmix_input_identity(dry_run, live, input_number=2)
    assert result["key"] == "vmix-cam-2"


def test_vmix_input_removed_rejects_key_still_present_in_live() -> None:
    dry_run = parse_vmix_status_xml(_vmix_status_xml(active=1, preview=2))
    live = parse_vmix_status_xml(_vmix_status_xml(active=1, preview=2))

    with pytest.raises(AssertionError, match="must remove"):
        validate_vmix_input_removed(dry_run, live, required_key="vmix-cam-2")


def test_vmix_input_removed_raises_when_key_gone_from_live() -> None:
    dry_run = parse_vmix_status_xml(_vmix_status_xml(active=1, preview=2))
    live = parse_vmix_status_xml(
        """
        <vmix>
          <version>29.0.0.48</version>
          <inputs>
            <input key="vmix-cam-1" number="1" title="DeckLink Duo 2">DeckLink Duo 2</input>
          </inputs>
          <active>1</active>
          <preview>1</preview>
          <recording>False</recording>
          <streaming>True</streaming>
        </vmix>
        """
    )

    with pytest.raises(ValueError, match="is no longer present at live fire"):
        validate_vmix_input_removed(dry_run, live, required_key="vmix-cam-2")


def test_vmix_capture_identity_drift_rejects_unchanged_stable_id() -> None:
    vmix_snapshot = parse_vmix_status_xml(_vmix_status_xml(active=1, preview=2))
    capture = {"devices": [{"name": "Cam Link HDMI", "class": "uvc-video", "stable_id": "same-id"}]}

    with pytest.raises(ValueError, match="no identity drift to detect"):
        validate_vmix_capture_identity(
            vmix_snapshot,
            vmix_snapshot,
            capture,
            capture,
            input_number=2,
            device_name="Cam Link HDMI",
        )


def test_vmix_capture_identity_drift_accepts_changed_stable_id() -> None:
    vmix_snapshot = parse_vmix_status_xml(_vmix_status_xml(active=1, preview=2))
    before = {
        "devices": [{"name": "Cam Link HDMI", "class": "uvc-video", "stable_id": "before-id"}]
    }
    after = {"devices": [{"name": "Cam Link HDMI", "class": "uvc-video", "stable_id": "after-id"}]}

    result = validate_vmix_capture_identity(
        vmix_snapshot, vmix_snapshot, before, after, input_number=2, device_name="Cam Link HDMI"
    )
    assert result["before_stable_id"] == "before-id"
    assert result["after_stable_id"] == "after-id"


def test_vmix_resource_ceiling_rejects_over_threshold_sample() -> None:
    with pytest.raises(ValueError, match="over ceiling"):
        validate_vmix_resource_ceiling({"cpu_percent": 95.0, "dropped_frames": 0})


def test_vmix_resource_ceiling_accepts_under_threshold_sample() -> None:
    result = validate_vmix_resource_ceiling({"cpu_percent": 10.0, "dropped_frames": 0})
    assert result["over_ceiling"] is False


def test_audio_topology_fixture_accepts_valid_shape() -> None:
    topology = validate_audio_topology_fixture(
        {"mixer_model": "Allen & Heath SQ5", "channel_count": 48, "output_routes": ["Program Mix"]}
    )
    assert topology.mixer_model == "Allen & Heath SQ5"
    assert topology.channel_count == 48


def test_audio_topology_fixture_rejects_missing_output_routes() -> None:
    with pytest.raises(ValueError, match="at least one output_route"):
        validate_audio_topology_fixture(
            {"mixer_model": "Allen & Heath SQ5", "channel_count": 48, "output_routes": []}
        )


def test_audio_topology_fixture_rejects_non_positive_channel_count() -> None:
    with pytest.raises(ValueError, match="positive integer channel_count"):
        validate_audio_topology_fixture(
            {
                "mixer_model": "Allen & Heath SQ5",
                "channel_count": 0,
                "output_routes": ["Program Mix"],
            }
        )


def test_audio_control_not_claimed_accepts_clean_topology() -> None:
    result = validate_audio_control_not_claimed(
        {"mixer_model": "Allen & Heath SQ5", "channel_count": 48, "output_routes": ["Program Mix"]}
    )
    assert result["control_claimed"] is False


def test_audio_control_not_claimed_rejects_leaked_control_field() -> None:
    with pytest.raises(ValueError, match="must not carry control fields"):
        validate_audio_control_not_claimed(
            {
                "mixer_model": "Allen & Heath SQ5",
                "channel_count": 48,
                "output_routes": ["Program Mix"],
                "midi_port": 51325,
            }
        )


def test_require_usb_audio_present_accepts_fixture_with_audio_class() -> None:
    result = _require_usb_audio_present(
        {"devices": [{"name": "Behringer U-Phoria", "class": "usb-audio", "stable_id": "a"}]}
    )
    assert result["device_count"] == 1


def test_require_usb_audio_present_rejects_fixture_without_audio_class() -> None:
    with pytest.raises(ValueError, match="No usb-audio class device present"):
        _require_usb_audio_present(
            {"devices": [{"name": "Cam Link HDMI", "class": "uvc-video", "stable_id": "a"}]}
        )


def test_run_executable_fixtures_usb_audio_present_counts_only_audio_devices() -> None:
    """Harness-level wiring guard: usb-audio-present must go through the
    class-filtering _require_usb_audio_present, not validate_capture_identity_fixture
    directly. The shared capture fixture has 2 devices (a uvc-video camera and
    a usb-audio interface); a correctly-wired check reports device_count=1
    (audio only). A count of 2 means it was wired to the unfiltered function
    and would report a camera as an audio device."""

    proofs = stage45._run_executable_fixtures()
    present = proofs["usb-audio-present"]
    assert present.status == "passed"
    assert present.details["device_count"] == 1
    assert all(d["class"] == "usb-audio" for d in present.details["devices"])


def test_run_executable_fixtures_usb_audio_present_fails_loud_on_camera_only_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the capture fixture ever loses its audio device, usb-audio-present
    must fail loudly (the whole fixture run raises) rather than silently
    reporting a non-audio device as present."""

    camera_only = {"devices": [{"name": "Cam Link HDMI", "class": "uvc-video", "stable_id": "a"}]}
    monkeypatch.setattr(stage45, "_USB_CAPTURE_FIXTURE", camera_only)
    with pytest.raises(ValueError, match="No usb-audio class device present"):
        stage45._run_executable_fixtures()


def test_usb_audio_sample_rate_accepts_matching_rate() -> None:
    result = validate_usb_audio_sample_rate(
        {"name": "x", "sample_rate_hz": 48_000}, expected_hz=48_000
    )
    assert result["sample_rate_hz"] == 48_000


def test_usb_audio_sample_rate_rejects_mismatched_rate() -> None:
    with pytest.raises(ValueError, match="does not match the expected 48000 Hz"):
        validate_usb_audio_sample_rate({"name": "x", "sample_rate_hz": 44_100}, expected_hz=48_000)


def test_usb_audio_sync_delay_accepts_under_ceiling() -> None:
    result = validate_usb_audio_sync_delay({"name": "x", "delay_ms": 10.0}, max_delay_ms=40.0)
    assert result["delay_ms"] == 10.0


def test_usb_audio_sync_delay_rejects_at_or_over_ceiling() -> None:
    with pytest.raises(ValueError, match="sync-warning ceiling"):
        validate_usb_audio_sync_delay({"name": "x", "delay_ms": 40.0}, max_delay_ms=40.0)


def test_sq_midi_mute_accepts_documented_4_frame_nrpn_mute() -> None:
    # SQ MIDI Protocol Issue 5 page 11 s3.3: BN 63/62/06/26, LSB 01=on / 00=off.
    # Mirrors the doc's Ip1 Mute On, Ch1 example: B0 63 00 B0 62 00 B0 06 00 B0 26 01.
    on = validate_sq_midi_mute_message(["B0 63 00", "B0 62 00", "B0 06 00", "B0 26 01"], channel=0)
    off = validate_sq_midi_mute_message(["B0 63 00", "B0 62 00", "B0 06 00", "B0 26 00"], channel=0)
    assert on["muted"] is True
    assert off["muted"] is False


def test_sq_midi_mute_rejects_note_on_the_old_wrong_format() -> None:
    # A Note On is the SQ's Soft Key format (Issue 5 page 10 s3.2), NOT a mute.
    with pytest.raises(ValueError, match="requires exactly 4 CC frames"):
        validate_sq_midi_mute_message(["90 30 7F"], channel=0)


def test_sq_midi_mute_rejects_non_mute_data_value() -> None:
    # A valid NRPN whose data value isn't 0/1 is a level write, not a mute.
    with pytest.raises(ValueError, match="mute data value must be"):
        validate_sq_midi_mute_message(["B0 63 00", "B0 62 00", "B0 06 40", "B0 26 00"], channel=0)


def test_midi_nrpn_message_accepts_documented_4_frame_sequence() -> None:
    result = validate_midi_nrpn_message(["B0 63 00", "B0 62 01", "B0 06 40", "B0 26 00"], channel=0)
    assert result["nrpn_number"] == 1
    assert result["data_value"] == 64 * 128


def test_midi_nrpn_message_rejects_out_of_order_frames() -> None:
    with pytest.raises(ValueError, match="must use CC 98, got CC 6"):
        validate_midi_nrpn_message(["B0 63 00", "B0 06 40", "B0 62 01", "B0 26 00"], channel=0)


def test_midi_nrpn_message_rejects_wrong_frame_count() -> None:
    with pytest.raises(ValueError, match="requires exactly 4 CC frames"):
        validate_midi_nrpn_message(["B0 63 00"], channel=0)


def test_midi_scene_recall_accepts_bank_change_and_program_change() -> None:
    # SQ MIDI Protocol Issue 5 page 9 s3.1: CC 0 bank change + Program Change,
    # 2 messages, no CC 32. Mirrors the doc's Scene 7, Ch1 example B0 00 00 C0 06.
    result = validate_midi_scene_recall("B0 00 00", "C0 05", channel=0)
    assert result["bank"] == 0
    assert result["program_number"] == 5


def test_midi_scene_recall_rejects_spurious_cc32_the_old_wrong_format() -> None:
    # An earlier draft required a CC 32 Bank LSB; the real spec does not use it.
    with pytest.raises(ValueError, match="does not use CC 32 for scene recall"):
        validate_midi_scene_recall("B0 20 02", "C0 05", channel=0)


def test_midi_scene_recall_rejects_bank_channel_mismatch() -> None:
    with pytest.raises(ValueError, match="bank change channel 0 does not match expected 5"):
        validate_midi_scene_recall("B0 00 00", "C0 05", channel=5)


def test_midi_scene_recall_rejects_program_change_channel_mismatch() -> None:
    # Bank change passes on channel 0, but the Program Change is on channel 1 --
    # the PC channel-mismatch branch (masked when the bank check catches it first).
    with pytest.raises(ValueError, match="Program Change channel 1 does not match expected 0"):
        validate_midi_scene_recall("B0 00 00", "C1 05", channel=0)


def test_midi_scene_recall_rejects_non_program_change_status() -> None:
    with pytest.raises(ValueError, match="requires a Program Change status byte"):
        validate_midi_scene_recall("B0 00 00", "B0 05", channel=0)


def test_atem_stage45_api_fixtures_use_atem_specific_reference() -> None:
    result = run_lpm_contract_lab(
        execution_stage="stage45",
        profile_ids=["portable-field-kit"],
    )

    atem_events = [event for event in result.events if event.check_id.startswith("atem-")]
    assert atem_events
    atem_api_fixtures = [event for event in atem_events if event.proof_source == "api-fixture"]
    assert atem_api_fixtures
    assert all(
        REFERENCE_URLS["blackmagic-atem-sdk"] in event.details.get("references", [])
        for event in atem_api_fixtures
    )


def test_stage45_execution_adds_real_fixture_and_simulator_events_without_upgrading_catalog_rows() -> (
    None
):
    result = run_lpm_contract_lab(execution_stage="stage45", profile_ids=["all"])

    # Overall status is honestly "failed" because several required checks
    # (e.g. ptz-camera-offline, usb-audio-present) still have no Stage 4-5
    # fixture behind them — see
    # test_stage45_required_check_without_executed_proof_fails_loudly.
    assert result.status == "failed"
    assert result.execution_stage == "stage45"
    assert any(
        event.check_id == "vmix-status-xml"
        and event.proof_source == "api-fixture"
        and event.proof_level == "api-contract-proven"
        for event in result.events
    )
    assert any(
        event.check_id == "visca-udp-52381-ack"
        and event.proof_source == "stateful-simulator"
        and event.proof_level == "simulated-proven"
        for event in result.events
    )
    assert any(
        event.check_id == "vmix-status-xml"
        and event.proof_source == "check-catalog"
        and event.proof_level == "mocked"
        for event in result.events
    )


def test_stage45_required_check_without_executed_proof_fails_loudly() -> None:
    """A required check with no Stage 4-5 fixture/simulator/probe must not be
    silently dropped — it must report an explicit failed event, and the run
    overall must fail. This is the regression test for the harness's
    fail-loud behavior on unexecuted required checks."""

    result = run_lpm_contract_lab(execution_stage="stage45", profile_ids=["all"])

    unexecuted = next(
        event
        for event in result.events
        if event.check_id == "ptz-camera-offline" and event.status == "failed"
    )
    assert unexecuted.status == "failed"
    assert unexecuted.proof_source == "check-catalog"
    assert unexecuted.proof_level == "mocked"
    assert "no stage 4-5" in unexecuted.observed.lower()
    assert result.status == "failed"


def test_obs_source_missing_and_removed_fail_on_the_real_missing_source_error() -> None:
    """obs-source-missing and obs-source-removed must pass because the REAL
    detection logic fired ("Required OBS source ... is not present in scene
    state"), not because an unrelated parser error (e.g. an uncorrelated
    requestId) raised first. Guards against the wrong-reason failure mode."""

    proofs = stage45._run_executable_fixtures()

    missing = proofs["obs-source-missing"]
    removed = proofs["obs-source-removed"]
    assert missing.status == "passed"
    assert "Required OBS source 'Camera 2' is not present in scene state" in missing.observed
    assert removed.status == "passed"
    assert "Required OBS source 'Camera 1' is not present in scene state" in removed.observed
    # The parser-level wrong-reason message must NOT be what these record.
    assert "does not match a requestId" not in missing.observed
    assert "does not match a requestId" not in removed.observed


def test_expect_value_error_rejects_wrong_reason_failures() -> None:
    def raise_unrelated() -> None:
        raise ValueError("some unrelated parser error")

    with pytest.raises(AssertionError, match="wrong reason"):
        stage45._expect_value_error(raise_unrelated, match="is not present in scene state")


def test_stage45_not_applicable_catalog_row_stays_not_applicable_when_unexecuted() -> None:
    """A check the catalog explicitly declares not-applicable (e.g. audio mixer
    control, intentionally out of scope) must not be reframed as a failure
    just because Stage 4-5 never executes it — that would punish an honest
    non-claim as if it were a dropped required check."""

    result = run_lpm_contract_lab(execution_stage="stage45", profile_ids=["all"])

    audio_control = next(
        event for event in result.events if event.check_id == "audio-control-not-claimed"
    )
    assert audio_control.status == "not-applicable"


def test_stage45_software_probe_records_absence_without_field_claim() -> None:
    result = run_lpm_contract_lab(
        execution_stage="stage45",
        profile_ids=["digitization-obs"],
        probe_real_software=True,
    )

    probe_events = [
        event for event in result.events if event.check_id.startswith("software-probe-")
    ]
    assert probe_events
    assert all(event.proof_source == "software-lab" for event in probe_events)
    assert all(
        "station-device evidence" in (event.not_claimed or "").lower()
        or "no software-lab proof" in (event.not_claimed or "").lower()
        for event in probe_events
    )


def test_unreachable_vmix_probe_cannot_use_success_shaped_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        stage45,
        "_probe_vmix",
        lambda url, timeout_seconds: {
            "reachable": False,
            "software_class": "vmix",
            "url": url,
            "executable": None,
            "observed": "vMix HTTP API not reachable in test.",
        },
    )

    result = run_lpm_contract_lab(
        execution_stage="stage45",
        profile_ids=["fixed-studio-livestreaming"],
        probe_real_software=True,
    )

    vmix_probe = next(
        event for event in result.events if event.check_id == "software-probe-vmix-http"
    )
    assert vmix_probe.status == "not-applicable"
    assert vmix_probe.proof_level == "mocked"
    assert "is reachable" not in vmix_probe.claim
    assert "returns status XML" not in vmix_probe.claim
    assert "no software-lab proof" in (vmix_probe.not_claimed or "")


def test_stage45_can_require_real_software_lab_for_a_hard_gate() -> None:
    result = run_lpm_contract_lab(
        execution_stage="stage45",
        profile_ids=["digitization-obs"],
        probe_real_software=False,
        require_software_lab=True,
    )

    assert result.status == "failed"
    assert any("software-lab proof was required" in issue for issue in result.issues)


def test_all_profile_software_lab_requirement_is_device_class_aware() -> None:
    result = run_lpm_contract_lab(
        execution_stage="stage45",
        profile_ids=["all"],
        probe_real_software=False,
        require_software_lab=True,
    )

    assert result.status == "failed"
    assert any("obs, vmix" in issue for issue in result.issues)


def test_stage45_readme_has_plain_software_probe_summary(tmp_path: Path) -> None:
    run_lpm_contract_lab(
        execution_stage="stage45",
        profile_ids=["all"],
        probe_real_software=False,
        artifact_root=tmp_path,
    )

    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "Read First - Software Probe Summary" in readme
    assert "OBS software lab: not run." in readme
    assert "vMix software lab: not run." in readme
    assert "Station-device evidence: none in this local artifact." in readme


def test_local_ci_runner_restores_obs_config_and_writes_utf8_logs() -> None:
    script = Path("scripts/run_local_3_2_lpm_contract_lab_ci.ps1").read_text(encoding="utf-8")

    assert "Restore-LocalObsWebSocketLab" in script
    assert "obs-lab-appdata" in script
    assert '$psi.Environment["APPDATA"] = $script:ObsLabAppData' in script
    assert "$env:APPDATA" not in script
    assert "} finally {" in script
    assert "Out-File -FilePath $logPath -Append -Encoding utf8" in script
    assert "Run Stage 4 OBS software proof hard gate" in script
    assert "Run Stage 4 all-profile OBS and vMix software proof hard gate" in script
    assert "contract-lab-stage45-all-software" in script
    assert "[string]$ArtifactRoot" in script
    assert 'if ($ArtifactRoot -ne "")' in script


def _serve_once(handler: Callable[[socket.socket], None]) -> tuple[int, threading.Thread]:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = int(server.getsockname()[1])

    def run() -> None:
        try:
            conn, _addr = server.accept()
            with conn:
                handler(conn)
        finally:
            server.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return port, thread


def _recv_until(conn: socket.socket, marker: bytes) -> bytes:
    data = bytearray()
    while marker not in data:
        chunk = conn.recv(1)
        if not chunk:
            break
        data.extend(chunk)
    return bytes(data)


def _http_header(request: bytes, header_name: str) -> str:
    for line in request.decode("iso-8859-1").split("\r\n"):
        if line.lower().startswith(header_name.lower() + ":"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"Missing HTTP header {header_name}")


def _send_server_ws_json(conn: socket.socket, payload: dict[str, object]) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    if len(body) < 126:
        header = bytes([0x81, len(body)])
    else:
        header = bytes([0x81, 126]) + len(body).to_bytes(2, "big")
    conn.sendall(header + body)


def _read_client_ws_json(conn: socket.socket) -> dict[str, object]:
    header = conn.recv(2)
    assert len(header) == 2
    payload_len = header[1] & 0x7F
    if payload_len == 126:
        payload_len = int.from_bytes(conn.recv(2), "big")
    elif payload_len == 127:
        payload_len = int.from_bytes(conn.recv(8), "big")
    mask = conn.recv(4)
    payload = conn.recv(payload_len)
    unmasked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    decoded = json.loads(unmasked.decode("utf-8"))
    assert isinstance(decoded, dict)
    return decoded
