# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S23 slice 4 — EPG exporters (X-List / XMLTV / CSV) + orchestrator.

Covers spec §6 (EPG export algorithm) + §7 DC-4:

* Each serializer round-trips through its native parser at 0/1/3 slots; the
  exact rows/elements + attribute values are asserted, not just "didn't crash".
* ``field_map`` renames CSV column headers (and X-List too); for XMLTV the
  ``field_map`` is documented as a no-op (the slot still produces canonical
  ``<title>/<desc>/<category>/<rating>`` children).
* Embedded special chars (``,`` ``"`` ``&`` ``<`` newline) survive — CSV via
  ``csv.reader`` round-trip; XMLTV via ``ET.fromstring`` (well-formed).
* :class:`EpgExporter` returns the document when ``endpoint is None``; when
  set, calls the injected ``http_post`` with the right URL/body/content-type;
  when the push raises, captures ``error=str(e)`` and does NOT re-raise.
* Default :func:`_safe_http_post` SSRF guard rejects ``http://``, loopback /
  private IPs, and redirects (urllib opener mocked).
* ``validate_xmltv`` accepts a generated doc and rejects a foreign root;
  ``validate_xlist`` mismatch raises.
* A slot with ``asset_id=None`` (filler / live with no library asset) still
  serializes.
"""

from __future__ import annotations

import csv
import io
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from civiccast.reporting.epg import (
    CommittedSlot,
    EpgExporter,
    EpgValidationError,
    InMemoryCommittedScheduleReader,
    _safe_http_post,
    serialize_csv,
    serialize_xlist,
    serialize_xmltv,
    validate_xlist,
    validate_xmltv,
)
from civiccast.reporting.models import EpgExportConfig

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _slot(
    *,
    slot_id: str = "s1",
    asset_id: str | None = "asset-001",
    title: str = "City Council Meeting",
    start: datetime | None = None,
    duration_s: int = 3600,
    description: str | None = "Regular session",
    category: str | None = "Government",
    rating: str | None = "G",
) -> CommittedSlot:
    start = start if start is not None else datetime(2026, 7, 1, 18, 0, 0, tzinfo=UTC)
    return CommittedSlot(
        slot_id=slot_id,
        asset_id=asset_id,
        title=title,
        start=start,
        end=start + timedelta(seconds=duration_s),
        duration_s=duration_s,
        description=description,
        category=category,
        rating=rating,
    )


def _config(
    *,
    fmt: str = "csv",
    horizon_days: int = 14,
    endpoint: str | None = None,
    field_map: dict[str, str] | None = None,
) -> EpgExportConfig:
    return EpgExportConfig(
        config_id="cfg-1",
        station_id="station-a",
        channel_id="ch1",
        format=fmt,  # type: ignore[arg-type]
        horizon_days=horizon_days,
        endpoint=endpoint,
        field_map=field_map or {},
    )


# ---------------------------------------------------------------------------
# X-List serializer
# ---------------------------------------------------------------------------


class TestXList:
    def test_zero_slots_is_header_only(self) -> None:
        doc = serialize_xlist([], field_map={})
        # header only, with X-List CRLF terminator
        assert doc.endswith("\r\n")
        reader = csv.reader(io.StringIO(doc))
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0] == [
            "start_date",
            "start_time",
            "end_date",
            "end_time",
            "title",
            "description",
            "category",
            "rating",
        ]

    def test_single_slot_row(self) -> None:
        s = _slot()
        doc = serialize_xlist([s], field_map={})
        rows = list(csv.reader(io.StringIO(doc)))
        assert len(rows) == 2
        assert rows[1] == [
            "2026-07-01",
            "18:00:00",
            "2026-07-01",
            "19:00:00",
            "City Council Meeting",
            "Regular session",
            "Government",
            "G",
        ]

    def test_three_slots(self) -> None:
        base = datetime(2026, 7, 1, 18, 0, 0, tzinfo=UTC)
        slots = [
            _slot(slot_id="a", title="A", start=base, duration_s=600),
            _slot(slot_id="b", title="B", start=base + timedelta(seconds=600), duration_s=900),
            _slot(slot_id="c", title="C", start=base + timedelta(seconds=1500), duration_s=300),
        ]
        rows = list(csv.reader(io.StringIO(serialize_xlist(slots, field_map={}))))
        assert len(rows) == 4
        titles = [r[4] for r in rows[1:]]
        assert titles == ["A", "B", "C"]

    def test_field_map_renames_columns(self) -> None:
        doc = serialize_xlist([_slot()], field_map={"title": "ProgramTitle", "rating": "TVRating"})
        header = next(csv.reader(io.StringIO(doc)))
        assert "ProgramTitle" in header
        assert "TVRating" in header
        assert "title" not in header
        assert "rating" not in header

    def test_special_chars_round_trip(self) -> None:
        s = _slot(
            title='Mayor, "Live" & Unfiltered',
            description="Line one\nLine two with <tags>",
        )
        doc = serialize_xlist([s], field_map={})
        rows = list(csv.reader(io.StringIO(doc)))
        assert rows[1][4] == 'Mayor, "Live" & Unfiltered'
        assert rows[1][5] == "Line one\nLine two with <tags>"

    def test_optional_station_call_sign_emitted_when_provided(self) -> None:
        # X-List operationally allows an extra call-sign column; spec says the
        # caller can supply one. When omitted, no extra column is emitted.
        doc_with = serialize_xlist([_slot()], field_map={}, station_call_sign="KCIV")
        header_with = next(csv.reader(io.StringIO(doc_with)))
        assert "station_call_sign" in header_with
        rows = list(csv.reader(io.StringIO(doc_with)))
        assert "KCIV" in rows[1]

    def test_crlf_line_terminator(self) -> None:
        # X-List convention is CRLF (Excel / TitanTV ingest).
        doc = serialize_xlist([_slot()], field_map={})
        # There should be at least two CRLFs: end of header + end of row.
        assert doc.count("\r\n") >= 2


# ---------------------------------------------------------------------------
# XMLTV serializer
# ---------------------------------------------------------------------------


class TestXmltv:
    def test_zero_slots_has_channel_only(self) -> None:
        doc = serialize_xmltv(
            [], field_map={}, channel_id="ch1", channel_display_name="CivicCast Channel 1"
        )
        assert doc.startswith("<?xml")
        root = ET.fromstring(doc[doc.index("?>") + 2 :])
        assert root.tag == "tv"
        channels = root.findall("channel")
        assert len(channels) == 1
        assert channels[0].get("id") == "ch1"
        assert channels[0].findtext("display-name") == "CivicCast Channel 1"
        assert root.findall("programme") == []

    def test_one_slot_emits_programme(self) -> None:
        s = _slot()
        doc = serialize_xmltv([s], field_map={}, channel_id="ch1", channel_display_name="Civic 1")
        root = ET.fromstring(doc[doc.index("?>") + 2 :])
        progs = root.findall("programme")
        assert len(progs) == 1
        p = progs[0]
        assert p.get("channel") == "ch1"
        assert p.get("start") == "20260701180000 +0000"
        assert p.get("stop") == "20260701190000 +0000"
        assert p.findtext("title") == "City Council Meeting"
        assert p.findtext("desc") == "Regular session"
        assert p.findtext("category") == "Government"
        assert p.findtext("rating") == "G"

    def test_three_slots(self) -> None:
        base = datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)
        slots = [
            _slot(slot_id=f"s{i}", title=f"Title {i}", start=base + timedelta(hours=i))
            for i in range(3)
        ]
        doc = serialize_xmltv(slots, field_map={}, channel_id="ch1", channel_display_name="Civic 1")
        root = ET.fromstring(doc[doc.index("?>") + 2 :])
        progs = root.findall("programme")
        assert [p.findtext("title") for p in progs] == ["Title 0", "Title 1", "Title 2"]

    def test_special_chars_well_formed_xml(self) -> None:
        s = _slot(
            title='Mayor, "Live" & Unfiltered',
            description="Line one\nWith <tags> & ampersands",
        )
        doc = serialize_xmltv([s], field_map={}, channel_id="ch1", channel_display_name="Civic & 1")
        # Must parse without raising — ET escapes &, <, > automatically.
        root = ET.fromstring(doc[doc.index("?>") + 2 :])
        assert root.findall("channel")[0].findtext("display-name") == "Civic & 1"
        prog = root.findall("programme")[0]
        assert prog.findtext("title") == 'Mayor, "Live" & Unfiltered'
        assert prog.findtext("desc") == "Line one\nWith <tags> & ampersands"

    def test_naive_datetime_serializes_as_utc_with_offset(self) -> None:
        # T-8: the serializer's ``tzinfo is None`` branch (``replace(tzinfo=UTC)``)
        # must produce the same +0000 attr and an unchanged YYYYMMDDHHMMSS
        # date/time portion as a tz-aware UTC fixture would.
        naive_start = datetime(2026, 7, 1, 18, 0, 0)  # naive
        naive_end = datetime(2026, 7, 1, 19, 0, 0)  # naive
        s = CommittedSlot(
            slot_id="naive-1",
            asset_id="asset-naive",
            title="Naive Slot",
            start=naive_start,
            end=naive_end,
            duration_s=3600,
            description=None,
            category=None,
            rating=None,
        )
        doc = serialize_xmltv([s], field_map={}, channel_id="ch1", channel_display_name="Civic 1")
        root = ET.fromstring(doc[doc.index("?>") + 2 :])
        p = root.findall("programme")[0]
        # Must end +0000 AND the YYYYMMDDHHMMSS portion is unchanged from input
        # (i.e. the serializer did NOT shift the absolute time when attaching UTC).
        assert p.get("start") == "20260701180000 +0000"
        assert p.get("stop") == "20260701190000 +0000"

    def test_optional_fields_absent(self) -> None:
        s = _slot(description=None, category=None, rating=None)
        doc = serialize_xmltv([s], field_map={}, channel_id="ch1", channel_display_name="Civic 1")
        root = ET.fromstring(doc[doc.index("?>") + 2 :])
        prog = root.findall("programme")[0]
        assert prog.findtext("title") == "City Council Meeting"
        assert prog.find("desc") is None
        assert prog.find("category") is None
        assert prog.find("rating") is None

    def test_field_map_is_noop_for_xmltv(self) -> None:
        # Documented behavior: XMLTV ignores field_map in this version.
        doc = serialize_xmltv(
            [_slot()],
            field_map={"title": "ProgramTitle"},
            channel_id="ch1",
            channel_display_name="Civic 1",
        )
        root = ET.fromstring(doc[doc.index("?>") + 2 :])
        # Canonical <title> is still emitted; no <ProgramTitle> element appears.
        assert root.findall("programme")[0].findtext("title") == "City Council Meeting"
        assert root.findall("programme")[0].find("ProgramTitle") is None


# ---------------------------------------------------------------------------
# Plain CSV serializer
# ---------------------------------------------------------------------------


class TestCsv:
    def test_zero_slots_header_only(self) -> None:
        doc = serialize_csv([], field_map={})
        rows = list(csv.reader(io.StringIO(doc)))
        assert len(rows) == 1
        # No CRLF, plain "\n" line terminator.
        assert "\r\n" not in doc

    def test_single_slot(self) -> None:
        doc = serialize_csv([_slot()], field_map={})
        rows = list(csv.reader(io.StringIO(doc)))
        assert rows[1][4] == "City Council Meeting"

    def test_three_slots(self) -> None:
        base = datetime(2026, 7, 1, 18, 0, 0, tzinfo=UTC)
        slots = [
            _slot(slot_id=f"s{i}", title=f"T{i}", start=base + timedelta(hours=i)) for i in range(3)
        ]
        rows = list(csv.reader(io.StringIO(serialize_csv(slots, field_map={}))))
        assert [r[4] for r in rows[1:]] == ["T0", "T1", "T2"]

    def test_field_map_renames(self) -> None:
        doc = serialize_csv([_slot()], field_map={"title": "ProgramTitle"})
        header = next(csv.reader(io.StringIO(doc)))
        assert "ProgramTitle" in header
        assert "title" not in header

    def test_special_chars(self) -> None:
        s = _slot(title='Mayor, "Live" & <Unfiltered>')
        rows = list(csv.reader(io.StringIO(serialize_csv([s], field_map={}))))
        assert rows[1][4] == 'Mayor, "Live" & <Unfiltered>'


# ---------------------------------------------------------------------------
# Asset-id-None slot (filler/live with no library asset)
# ---------------------------------------------------------------------------


class TestNoAssetSlot:
    def test_xlist_serializes_filler_slot(self) -> None:
        s = _slot(asset_id=None, title="Community Bulletin Board")
        rows = list(csv.reader(io.StringIO(serialize_xlist([s], field_map={}))))
        assert rows[1][4] == "Community Bulletin Board"

    def test_xmltv_serializes_filler_slot(self) -> None:
        s = _slot(asset_id=None, title="Community Bulletin Board")
        doc = serialize_xmltv([s], field_map={}, channel_id="ch1", channel_display_name="Civic 1")
        root = ET.fromstring(doc[doc.index("?>") + 2 :])
        assert root.findall("programme")[0].findtext("title") == "Community Bulletin Board"


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


class TestValidators:
    def test_validate_xmltv_accepts_generated_doc(self) -> None:
        doc = serialize_xmltv(
            [_slot()],
            field_map={},
            channel_id="ch1",
            channel_display_name="Civic 1",
        )
        # 1 programme expected.
        validate_xmltv(doc, expected_programmes=1)

    def test_validate_xmltv_rejects_foreign_root(self) -> None:
        with pytest.raises(EpgValidationError):
            validate_xmltv("<?xml version='1.0'?><foo/>", expected_programmes=0)

    def test_validate_xmltv_rejects_wrong_programme_count(self) -> None:
        doc = serialize_xmltv(
            [_slot()],
            field_map={},
            channel_id="ch1",
            channel_display_name="Civic 1",
        )
        with pytest.raises(EpgValidationError):
            validate_xmltv(doc, expected_programmes=99)

    def test_validate_xlist_accepts_matching_header(self) -> None:
        doc = serialize_xlist([_slot()], field_map={})
        validate_xlist(
            doc,
            expected_columns=[
                "start_date",
                "start_time",
                "end_date",
                "end_time",
                "title",
                "description",
                "category",
                "rating",
            ],
        )

    def test_validate_xlist_mismatch_raises(self) -> None:
        doc = serialize_xlist([_slot()], field_map={})
        with pytest.raises(EpgValidationError):
            validate_xlist(doc, expected_columns=["nope"])


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class TestOrchestrator:
    def _reader_with(self, slots: list[CommittedSlot]) -> InMemoryCommittedScheduleReader:
        return InMemoryCommittedScheduleReader(slots=slots)

    def test_no_endpoint_returns_document(self) -> None:
        slot = _slot()
        reader = self._reader_with([slot])
        exporter = EpgExporter(schedule_reader=reader, http_post=lambda *a, **k: None)
        cfg = _config(fmt="csv", endpoint=None)
        result = exporter.generate(cfg, now=datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC))
        assert result.format == "csv"
        assert result.slot_count == 1
        assert result.document is not None
        assert "City Council Meeting" in result.document
        assert result.pushed_to is None
        assert result.pushed_at is None
        assert result.error is None
        assert result.bytes == len(result.document.encode("utf-8"))

    def test_endpoint_set_calls_http_post(self) -> None:
        slot = _slot()
        reader = self._reader_with([slot])
        captured: dict[str, Any] = {}

        def fake_post(url: str, body: str, content_type: str) -> None:
            captured["url"] = url
            captured["body"] = body
            captured["content_type"] = content_type

        exporter = EpgExporter(schedule_reader=reader, http_post=fake_post)
        cfg = _config(fmt="xlist", endpoint="https://aggregator.example.com/epg")
        now = datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)
        result = exporter.generate(cfg, now=now)
        assert captured["url"] == "https://aggregator.example.com/epg"
        assert captured["content_type"] == "text/csv"
        assert "City Council Meeting" in captured["body"]
        assert result.pushed_to == "https://aggregator.example.com/epg"
        assert result.pushed_at == now
        assert result.document is None
        assert result.error is None

    def test_endpoint_xmltv_uses_application_xml(self) -> None:
        captured: dict[str, str] = {}

        def fake_post(url: str, body: str, content_type: str) -> None:
            captured["content_type"] = content_type

        exporter = EpgExporter(schedule_reader=self._reader_with([_slot()]), http_post=fake_post)
        cfg = _config(fmt="xmltv", endpoint="https://aggregator.example.com/epg")
        exporter.generate(cfg, now=datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC))
        assert captured["content_type"] == "application/xml"

    def test_push_failure_captured_not_raised(self) -> None:
        def boom(url: str, body: str, content_type: str) -> None:
            raise RuntimeError("aggregator down")

        exporter = EpgExporter(schedule_reader=self._reader_with([_slot()]), http_post=boom)
        cfg = _config(fmt="csv", endpoint="https://aggregator.example.com/epg")
        result = exporter.generate(cfg, now=datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC))
        assert result.error == "aggregator down"
        assert result.document is None
        assert result.pushed_to is None
        assert result.pushed_at is None

    def test_horizon_window_passed_to_reader(self) -> None:
        captured: dict[str, datetime] = {}

        class _CapturingReader:
            def list_committed(
                self,
                *,
                station_id: str,
                channel_id: str,
                from_ts: datetime,
                to_ts: datetime,
            ) -> list[CommittedSlot]:
                captured["from_ts"] = from_ts
                captured["to_ts"] = to_ts
                return []

        exporter = EpgExporter(
            schedule_reader=_CapturingReader(),  # type: ignore[arg-type]
            http_post=lambda *a, **k: None,
        )
        cfg = _config(fmt="csv", horizon_days=7, endpoint=None)
        now = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
        exporter.generate(cfg, now=now)
        assert captured["from_ts"] == now
        assert captured["to_ts"] == now + timedelta(days=7)


# ---------------------------------------------------------------------------
# SSRF guard on the default _safe_http_post
# ---------------------------------------------------------------------------


class TestSafeHttpPost:
    def test_rejects_http_scheme(self) -> None:
        with pytest.raises(ValueError, match="https"):
            _safe_http_post("http://example.com/epg", "body", "text/csv")

    def test_rejects_loopback_v4(self) -> None:
        with pytest.raises(ValueError, match=r"loopback|private|off-box"):
            _safe_http_post("https://127.0.0.1/epg", "body", "text/csv")

    def test_rejects_loopback_hostname(self) -> None:
        with pytest.raises(ValueError, match=r"loopback|private|off-box"):
            _safe_http_post("https://localhost/epg", "body", "text/csv")

    def test_rejects_private_v4(self) -> None:
        with pytest.raises(ValueError, match=r"loopback|private|off-box"):
            _safe_http_post("https://10.0.0.5/epg", "body", "text/csv")

    def test_rejects_link_local_metadata(self) -> None:
        # 169.254.169.254 = AWS / GCP / Azure metadata service; the canonical SSRF target.
        with pytest.raises(ValueError, match=r"loopback|private|off-box|link-local"):
            _safe_http_post("https://169.254.169.254/latest/meta-data/", "body", "text/csv")

    def test_rejects_multicast(self) -> None:
        # E-2: 224.0.0.0/4 is not loopback/private/link-local/reserved but is
        # still off-box-invalid. Pre-fix it leaked through the guard.
        with pytest.raises(ValueError, match=r"multicast|off-box"):
            _safe_http_post("https://224.0.0.5/x", "body", "text/csv")

    def test_rejects_unspecified_any(self) -> None:
        # E-2: 0.0.0.0 is technically caught by ``is_private`` on most Pythons,
        # but the contract should be explicit. The guard now refuses the
        # "any-address" target as a named class regardless.
        with pytest.raises(ValueError, match=r"unspecified|private|off-box"):
            _safe_http_post("https://0.0.0.0/x", "body", "text/csv")

    def test_rejects_redirect(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Mock the opener.open so we can prove the no-redirect handler is wired.
        # urllib raises HTTPError when the handler returns None for a 3xx; we
        # mimic that by raising one directly out of the opener.
        class _FakeOpener:
            def open(self, request: Any, timeout: float) -> Any:
                raise urllib.error.HTTPError(
                    url=request.full_url,
                    code=302,
                    msg="Found",
                    hdrs=None,  # type: ignore[arg-type]
                    fp=None,
                )

        from civiccast.reporting import epg as epg_module

        monkeypatch.setattr(epg_module, "_EPG_OPENER", _FakeOpener())
        with pytest.raises(RuntimeError, match=r"redirect|HTTP|302"):
            _safe_http_post("https://aggregator.example.com/epg", "body", "text/csv")

    def test_happy_path_uses_opener(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        class _FakeResp:
            def __enter__(self) -> Any:
                return self

            def __exit__(self, *args: Any) -> None:
                return None

            def read(self) -> bytes:
                return b""

        class _FakeOpener:
            def open(self, request: Any, timeout: float) -> Any:
                captured["url"] = request.full_url
                captured["body"] = request.data
                captured["content_type"] = request.get_header("Content-type")
                captured["timeout"] = timeout
                return _FakeResp()

        from civiccast.reporting import epg as epg_module

        monkeypatch.setattr(epg_module, "_EPG_OPENER", _FakeOpener())
        _safe_http_post("https://aggregator.example.com/epg", "hello", "text/csv")
        assert captured["url"] == "https://aggregator.example.com/epg"
        assert captured["body"] == b"hello"
        assert captured["content_type"] == "text/csv"
        assert captured["timeout"] == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# InMemoryCommittedScheduleReader (smoke)
# ---------------------------------------------------------------------------


class TestInMemoryReader:
    def test_filters_by_window(self) -> None:
        base = datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)
        slots = [
            _slot(slot_id="early", start=base - timedelta(hours=2), duration_s=600),
            _slot(slot_id="inside", start=base + timedelta(hours=1), duration_s=600),
            _slot(slot_id="late", start=base + timedelta(days=30), duration_s=600),
        ]
        reader = InMemoryCommittedScheduleReader(slots=slots)
        got = reader.list_committed(
            station_id="station-a",
            channel_id="ch1",
            from_ts=base,
            to_ts=base + timedelta(days=7),
        )
        assert [s.slot_id for s in got] == ["inside"]
