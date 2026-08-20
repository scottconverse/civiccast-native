# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from civiccast.facility import (
    ROUTER_VENDOR_BLACKMAGIC,
    ROUTER_VENDOR_EVERTZ,
    ROUTER_VENDOR_ROSS,
    ROUTER_VENDOR_UTAH,
    RouterEndpoint,
    RouterInput,
    RouterOutput,
    RouterScheduledTakeRequest,
    RouterTakeRequest,
    build_router_scheduled_take_plan,
    build_router_take_plan,
    build_virtual_router_panel,
)


def _endpoint(vendor: str, protocol: str) -> RouterEndpoint:
    return RouterEndpoint(
        endpoint_id=f"{vendor}-router",
        label=f"{vendor} router",
        vendor=vendor,  # type: ignore[arg-type]
        protocol=protocol,  # type: ignore[arg-type]
        transport="tcp",
        host="192.0.2.10",
        port=9990,
    )


def _source() -> RouterInput:
    return RouterInput(
        input_id="cam-1",
        label="Council chamber",
        physical_port="1",
        live_source_id="rtmp-cam-01",
    )


def _destination() -> RouterOutput:
    return RouterOutput(
        output_id="civiccast",
        label="CivicCast capture",
        physical_port="7",
        channel_id="gov-ch12",
    )


@pytest.mark.parametrize(
    ("vendor", "protocol", "preview"),
    [
        (ROUTER_VENDOR_BLACKMAGIC, "blackmagic-videohub", "VIDEO OUTPUT ROUTING:\\n7 1\\n\\n"),
        (ROUTER_VENDOR_ROSS, "ross-rosstalk", "XPT 1:7\\r\\n"),
        (ROUTER_VENDOR_UTAH, "utah-scientific", "@ TAKE 7 1\\r"),
        (ROUTER_VENDOR_EVERTZ, "evertz", "X 7,1\\r"),
    ],
)
def test_router_take_plan_for_known_vendors(vendor: str, protocol: str, preview: str) -> None:
    request = RouterTakeRequest(
        request_id="take-001",
        endpoint=_endpoint(vendor, protocol),
        source=_source(),
        destination=_destination(),
        requested_by="operator-1",
        scheduled_for=datetime(2026, 6, 1, 18, tzinfo=UTC),
    )

    plan = build_router_take_plan(request)

    assert plan.command_preview == preview
    assert plan.ready_to_send is True
    assert plan.target == "tcp://192.0.2.10:9990"
    assert plan.source_label == "Council chamber"
    assert plan.destination_label == "CivicCast capture"
    assert "hardware connection" in plan.proof_boundary


def test_generic_text_command_template_is_supported() -> None:
    endpoint = RouterEndpoint(
        endpoint_id="generic-router",
        label="Generic router",
        vendor="generic",
        protocol="generic-text",
        transport="udp",
        host="192.0.2.55",
        port=4000,
        command_template="TAKE OUT={destination} IN={source}\n",
    )
    request = RouterTakeRequest(
        request_id="take-002",
        endpoint=endpoint,
        source=_source(),
        destination=_destination(),
        requested_by="operator-1",
    )

    plan = build_router_take_plan(request)

    assert plan.command_preview == "TAKE OUT=7 IN=1\\n"
    assert bytes.fromhex(plan.command_bytes_hex) == b"TAKE OUT=7 IN=1\n"
    assert plan.target == "udp://192.0.2.55:4000"


def test_rs232_endpoint_requires_serial_fields() -> None:
    with pytest.raises(ValidationError, match="serial_port and baud_rate"):
        RouterEndpoint(
            endpoint_id="serial-router",
            label="Serial router",
            vendor="generic",
            protocol="generic-text",
            transport="rs232",
            command_template="TAKE {destination} {source}",
        )


def test_disabled_endpoint_builds_preview_but_not_send_ready() -> None:
    endpoint = _endpoint(ROUTER_VENDOR_BLACKMAGIC, "blackmagic-videohub").model_copy(
        update={"enabled": False}
    )
    request = RouterTakeRequest(
        request_id="take-003",
        endpoint=endpoint,
        source=_source(),
        destination=_destination(),
        requested_by="operator-1",
    )

    plan = build_router_take_plan(request)

    assert plan.ready_to_send is False
    assert plan.operator_action.startswith("Enable the router endpoint")


def test_virtual_router_panel_builds_mobile_safe_buttons() -> None:
    panel = build_virtual_router_panel(
        panel_id="control-room",
        label="Control room",
        endpoint=_endpoint(ROUTER_VENDOR_BLACKMAGIC, "blackmagic-videohub"),
        sources=[_source()],
        destinations=[_destination()],
    )

    assert panel.mobile_columns == 2
    assert panel.buttons[0].label == "Council chamber to CivicCast capture"
    assert panel.buttons[0].requires_confirmation is True
    assert panel.buttons[0].enabled is True


def test_duplicate_virtual_router_button_ids_are_rejected() -> None:
    with pytest.raises(ValidationError, match="button IDs must be unique"):
        build_virtual_router_panel(
            panel_id="control-room",
            label="Control room",
            endpoint=_endpoint(ROUTER_VENDOR_BLACKMAGIC, "blackmagic-videohub"),
            sources=[_source(), _source()],
            destinations=[_destination()],
        )


def test_scheduled_take_plan_uses_preroll_time() -> None:
    plan = build_router_scheduled_take_plan(
        RouterScheduledTakeRequest(
            request_id="scheduled-take-1",
            schedule_item_id="schedule-123",
            channel_id="gov-ch12",
            starts_at=datetime(2026, 6, 1, 18, 0, tzinfo=UTC),
            endpoint=_endpoint(ROUTER_VENDOR_BLACKMAGIC, "blackmagic-videohub"),
            source=_source(),
            destination=_destination(),
            requested_by="scheduler",
            preroll_seconds=10,
        )
    )

    assert plan.scheduled_take_at == datetime(2026, 6, 1, 17, 59, 50, tzinfo=UTC)
    assert plan.take_plan.scheduled_for == plan.scheduled_take_at
    assert plan.automatic_take_ready is True
    assert (
        plan.proof_boundary
        == "Schedule-to-router command planning only; no hardware command is sent."
    )
