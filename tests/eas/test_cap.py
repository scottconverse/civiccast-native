# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S11c CAP 1.2 XML + NWS GeoJSON parsing and the source filter (pure; no I/O)."""

from __future__ import annotations

from datetime import UTC, datetime

from civiccast.eas.cap import (
    alert_passes_source_filter,
    parse_cap_xml,
    parse_nws_geojson,
    stable_alert_id,
)
from civiccast.eas.models import EasCapAlert, EasCapSource

_CAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
  <identifier>NWS-IDP-PROD-1234</identifier>
  <sender>w-nws.webmaster@noaa.gov</sender>
  <sent>2026-01-01T12:00:00-00:00</sent>
  <status>Actual</status>
  <msgType>Alert</msgType>
  <scope>Public</scope>
  <references>w-nws.webmaster@noaa.gov,NWS.0,2026-01-01T11:00:00-00:00</references>
  <info>
    <category>Met</category>
    <event>Tornado Warning</event>
    <urgency>Immediate</urgency>
    <severity>Extreme</severity>
    <certainty>Observed</certainty>
    <effective>2026-01-01T12:00:00-00:00</effective>
    <expires>2026-01-01T13:00:00-00:00</expires>
    <headline>Tornado Warning issued</headline>
    <description>A tornado was detected.</description>
    <instruction>Take shelter now.</instruction>
    <area>
      <areaDesc>Some County</areaDesc>
      <geocode><valueName>SAME</valueName><value>027001</value></geocode>
      <geocode><valueName>UGC</valueName><value>MNZ001</value></geocode>
    </area>
  </info>
</alert>
"""

_NWS_GEOJSON = """{
  "features": [
    {"properties": {
      "id": "urn:oid:2.49.0.1.840.0.NWS.1",
      "sender": "w-nws.webmaster@noaa.gov",
      "sent": "2026-01-01T12:00:00+00:00",
      "messageType": "Alert",
      "event": "Flash Flood Warning",
      "severity": "Severe",
      "urgency": "Immediate",
      "certainty": "Likely",
      "headline": "Flash Flood Warning",
      "description": "Flooding is occurring.",
      "instruction": "Move to higher ground.",
      "geocode": {"SAME": ["027003"], "UGC": ["MNZ002"]},
      "effective": "2026-01-01T12:00:00+00:00",
      "expires": "2026-01-01T15:00:00+00:00"
    }}
  ]
}"""


def test_parse_cap_xml_extracts_normalized_alert() -> None:
    [alert] = parse_cap_xml(_CAP_XML, source_id="src_ipaws")
    assert alert.sender == "w-nws.webmaster@noaa.gov"
    assert alert.identifier == "NWS-IDP-PROD-1234"
    assert alert.msg_type == "alert"
    assert alert.severity == "extreme"  # normalized to lowercase
    assert alert.event == "Tornado Warning"
    assert set(alert.areas) == {"027001", "MNZ001"}
    assert alert.instruction == "Take shelter now."
    assert alert.references and "NWS.0" in alert.references
    assert alert.expires == datetime(2026, 1, 1, 13, 0, tzinfo=UTC)
    assert alert.alert_id == stable_alert_id(alert.sender, alert.identifier)


def test_parse_cap_xml_garbage_returns_empty() -> None:
    assert parse_cap_xml("not xml at all", source_id="s") == []
    assert parse_cap_xml("<other>doc</other>", source_id="s") == []
    assert parse_cap_xml("", source_id="s") == []


def test_parse_nws_geojson_extracts_alert_with_geocodes() -> None:
    [alert] = parse_nws_geojson(_NWS_GEOJSON, source_id="src_nws")
    assert alert.identifier == "urn:oid:2.49.0.1.840.0.NWS.1"
    assert alert.severity == "severe"
    assert alert.event == "Flash Flood Warning"
    assert set(alert.areas) == {"027003", "MNZ002"}
    assert alert.expires == datetime(2026, 1, 1, 15, 0, tzinfo=UTC)


def test_parse_nws_geojson_garbage_returns_empty() -> None:
    assert parse_nws_geojson("{}", source_id="s") == []
    assert parse_nws_geojson("not json", source_id="s") == []
    assert parse_nws_geojson('{"features": "nope"}', source_id="s") == []


def _alert(
    severity: str = "extreme", *, msg_type: str = "alert", areas: list[str] | None = None
) -> EasCapAlert:
    return EasCapAlert(
        alert_id="a1",
        source_id="s",
        sender="snd",
        identifier="id1",
        sent=datetime(2026, 1, 1, tzinfo=UTC),
        msg_type=msg_type,  # type: ignore[arg-type]
        event="Test",
        severity=severity,  # type: ignore[arg-type]
        areas=areas if areas is not None else ["MNZ001"],
    )


def _source(*, floor: str = "severe", geocodes: list[str] | None = None) -> EasCapSource:
    return EasCapSource(
        source_id="s",
        label="src",
        kind="nws-cap",
        severity_floor=floor,  # type: ignore[arg-type]
        geocode_filter=geocodes if geocodes is not None else [],
    )


def test_filter_severity_floor() -> None:
    assert alert_passes_source_filter(_alert("extreme"), _source(floor="severe")) is True
    assert alert_passes_source_filter(_alert("moderate"), _source(floor="severe")) is False


def test_filter_geocode_intersection() -> None:
    src = _source(floor="minor", geocodes=["MNZ001"])
    assert alert_passes_source_filter(_alert(areas=["MNZ001", "MNZ009"]), src) is True
    assert alert_passes_source_filter(_alert(areas=["MNZ999"]), src) is False
    # empty filter = no geo restriction
    assert alert_passes_source_filter(_alert(areas=["MNZ999"]), _source(floor="minor")) is True


def test_filter_drops_ack_and_error() -> None:
    assert alert_passes_source_filter(_alert(msg_type="ack"), _source(floor="minor")) is False
    assert alert_passes_source_filter(_alert(msg_type="error"), _source(floor="minor")) is False
