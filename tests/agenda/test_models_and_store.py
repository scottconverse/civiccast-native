# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S25 agenda data layer — models + AgendaStore + migration 0058."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from civiccast.agenda.models import (
    AgendaItem,
    AgendaItemInput,
    AgendaItemUpdate,
    MeetingAgenda,
    MeetingAgendaInput,
    MeetingAgendaUpdate,
    PublicAgendaItem,
    PublicMeetingAgenda,
)
from civiccast.agenda.store import (
    AgendaItemNotFoundError,
    AgendaItemOrderConflictError,
    AgendaNotFoundError,
    AgendaPublishEmptyError,
    AgendaStore,
    AgendaUniqueViolationError,
)
from civiccast.db import Base

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


@pytest.fixture
def store(tmp_path: Path) -> Iterator[AgendaStore]:
    eng = create_engine(f"sqlite:///{tmp_path / 'a.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as sess:
            yield sess

    try:
        yield AgendaStore(factory)
    finally:
        eng.dispose()


# --- models -----------------------------------------------------------------


class TestMeetingAgendaModel:
    def test_valid_agenda_defaults_to_draft(self) -> None:
        a = MeetingAgenda(
            agenda_id="ag-2026-01",
            station_id="civiccast-station",
            meeting_asset_id="meeting-jan-2026",
        )
        assert a.status == "draft"
        assert a.source_doc_url is None

    def test_uppercase_id_rejected_by_slug(self) -> None:
        with pytest.raises(ValueError):
            MeetingAgenda(
                agenda_id="AG-Bad",
                station_id="civiccast-station",
                meeting_asset_id="meeting-jan-2026",
            )

    def test_source_doc_url_max_length(self) -> None:
        long_url = "https://example.com/" + "x" * 5000
        with pytest.raises(ValueError):
            MeetingAgenda(
                agenda_id="ag-x",
                station_id="sta",
                meeting_asset_id="meet-x",
                source_doc_url=long_url,
            )

    def test_status_literal_rejects_garbage(self) -> None:
        with pytest.raises(ValueError):
            MeetingAgenda(
                agenda_id="ag-x",
                station_id="sta",
                meeting_asset_id="meet-x",
                status="garbage",  # type: ignore[arg-type]
            )


class TestSourceDocUrlValidator:
    """E-1 / Q-3 / E-4 — ``source_doc_url`` must reject non-http(s) schemes
    on every model that accepts it (``MeetingAgenda``, ``MeetingAgendaInput``,
    ``MeetingAgendaUpdate``) and must coerce the empty string to ``None``.

    The public portal renders this value as an ``<a href>``, so a
    ``javascript:`` / ``data:`` / ``file:`` / ``vbscript:`` URL is a stored
    XSS vector. The validator's allowlist closes the door at the API
    boundary — defense in depth.
    """

    BAD_URLS = (
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "  javascript:alert(1)  ",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "vbscript:msgbox(1)",
        "about:blank",
        "blob:https://evil.example/abc",
        "no-scheme-just-text",
        ":missing-scheme",
    )

    @pytest.mark.parametrize("bad", BAD_URLS)
    def test_meeting_agenda_rejects_bad_scheme(self, bad: str) -> None:
        with pytest.raises(ValueError):
            MeetingAgenda(
                agenda_id="ag-x",
                station_id="sta",
                meeting_asset_id="meet-x",
                source_doc_url=bad,
            )

    @pytest.mark.parametrize("bad", BAD_URLS)
    def test_meeting_agenda_input_rejects_bad_scheme(self, bad: str) -> None:
        with pytest.raises(ValueError):
            MeetingAgendaInput(
                agenda_id="ag-x",
                station_id="sta",
                meeting_asset_id="meet-x",
                source_doc_url=bad,
            )

    @pytest.mark.parametrize("bad", BAD_URLS)
    def test_meeting_agenda_update_rejects_bad_scheme(self, bad: str) -> None:
        with pytest.raises(ValueError):
            MeetingAgendaUpdate(source_doc_url=bad)

    @pytest.mark.parametrize(
        "good",
        (
            "http://example.com/a.pdf",
            "https://example.com/a.pdf",
            "HTTPS://example.com/A.PDF",  # case-insensitive scheme accepted
            "https://example.com/a.pdf?q=1&r=2",
            "  https://example.com/a.pdf  ",  # whitespace trimmed
        ),
    )
    def test_http_and_https_accepted_and_trimmed(self, good: str) -> None:
        a = MeetingAgenda(
            agenda_id="ag-x",
            station_id="sta",
            meeting_asset_id="meet-x",
            source_doc_url=good,
        )
        assert a.source_doc_url is not None
        # Whitespace is stripped at the boundary so the stored value has no
        # leading/trailing spaces that would round-trip into the href.
        assert a.source_doc_url == good.strip()

    def test_empty_string_coerced_to_none_on_meeting_agenda(self) -> None:
        """E-4 — ``source_doc_url=""`` must NOT be stored as a literal empty
        string; the portal would otherwise render an empty href."""
        a = MeetingAgenda(
            agenda_id="ag-x",
            station_id="sta",
            meeting_asset_id="meet-x",
            source_doc_url="",
        )
        assert a.source_doc_url is None

    def test_empty_string_coerced_to_none_on_input(self) -> None:
        a = MeetingAgendaInput(
            agenda_id="ag-x",
            station_id="sta",
            meeting_asset_id="meet-x",
            source_doc_url="",
        )
        assert a.source_doc_url is None

    def test_empty_string_coerced_to_none_on_update(self) -> None:
        u = MeetingAgendaUpdate(source_doc_url="")
        assert u.source_doc_url is None

    def test_whitespace_only_coerced_to_none(self) -> None:
        a = MeetingAgenda(
            agenda_id="ag-x",
            station_id="sta",
            meeting_asset_id="meet-x",
            source_doc_url="   \t  ",
        )
        assert a.source_doc_url is None

    def test_none_stays_none(self) -> None:
        a = MeetingAgenda(
            agenda_id="ag-x",
            station_id="sta",
            meeting_asset_id="meet-x",
            source_doc_url=None,
        )
        assert a.source_doc_url is None


class TestAgendaItemModel:
    def _valid(self, **kw: object) -> AgendaItem:
        body: dict[str, object] = {
            "item_id": "it-1",
            "agenda_id": "ag-2026-01",
            "order": 0,
            "title": "Call to order",
        }
        body.update(kw)
        return AgendaItem(**body)  # type: ignore[arg-type]

    def test_valid_item(self) -> None:
        i = self._valid()
        assert i.video_timecode_s is None
        assert i.title == "Call to order"

    def test_title_min_length(self) -> None:
        with pytest.raises(ValueError):
            self._valid(title="")

    def test_negative_order_rejected(self) -> None:
        with pytest.raises(ValueError):
            self._valid(order=-1)

    def test_negative_timecode_rejected(self) -> None:
        with pytest.raises(ValueError):
            self._valid(video_timecode_s=-1)


class TestPublicProjections:
    def test_public_item_excludes_notes_and_timestamps(self) -> None:
        i = PublicAgendaItem(
            item_id="it-1",
            order=0,
            title="Call to order",
        )
        keys = set(i.model_dump().keys())
        assert "notes" not in keys
        assert "created_at" not in keys
        assert "updated_at" not in keys
        assert keys == {
            "item_id",
            "order",
            "number",
            "title",
            "video_timecode_s",
            "doc_anchor",
        }

    def test_public_agenda_excludes_status_and_station(self) -> None:
        a = PublicMeetingAgenda(
            agenda_id="ag-1",
            meeting_asset_id="m-1",
            items=[],
        )
        keys = set(a.model_dump().keys())
        assert "status" not in keys
        assert "station_id" not in keys
        assert keys == {"agenda_id", "meeting_asset_id", "source_doc_url", "items"}


# --- store ------------------------------------------------------------------


def _agenda(agenda_id: str = "ag-1", **kw: object) -> MeetingAgenda:
    body: dict[str, object] = {
        "agenda_id": agenda_id,
        "station_id": "civiccast-station",
        "meeting_asset_id": "meeting-jan-2026",
    }
    body.update(kw)
    return MeetingAgenda(**body)  # type: ignore[arg-type]


def _item(item_id: str = "it-1", order: int = 0, agenda_id: str = "ag-1") -> AgendaItem:
    return AgendaItem(
        item_id=item_id,
        agenda_id=agenda_id,
        order=order,
        title=f"Item {order}",
    )


class TestStoreAgendas:
    def test_upsert_then_get(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda())
        got = store.get_agenda("ag-1")
        assert got is not None
        assert got.status == "draft"
        assert got.station_id == "civiccast-station"

    def test_get_agenda_by_asset(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda())
        got = store.get_agenda_by_asset("civiccast-station", "meeting-jan-2026")
        assert got is not None
        assert got.agenda_id == "ag-1"
        # Wrong station — no match.
        assert store.get_agenda_by_asset("other-station", "meeting-jan-2026") is None

    def test_set_status_to_published(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda())
        store.set_status("ag-1", "published")
        got = store.get_agenda("ag-1")
        assert got is not None
        assert got.status == "published"

    def test_set_status_missing_raises(self, store: AgendaStore) -> None:
        with pytest.raises(AgendaNotFoundError):
            store.set_status("no-such", "published")

    def test_list_agendas_filters_to_station(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda("ag-a"))
        store.upsert_agenda(_agenda("ag-b", station_id="other-station", meeting_asset_id="m-other"))
        out = store.list_agendas("civiccast-station")
        assert [a.agenda_id for a in out] == ["ag-a"]

    def test_list_agendas_filters_to_status(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda("ag-a"))
        store.upsert_agenda(_agenda("ag-b", meeting_asset_id="m-different", status="published"))
        published = store.list_agendas("civiccast-station", status="published")
        assert [a.agenda_id for a in published] == ["ag-b"]

    def test_delete_agenda_cascades_items(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda())
        store.upsert_item(_item("it-1", order=0))
        store.upsert_item(_item("it-2", order=1))
        store.delete_agenda("ag-1")
        assert store.get_agenda("ag-1") is None
        assert store.get_item("it-1") is None
        assert store.get_item("it-2") is None

    def test_delete_missing_agenda_raises(self, store: AgendaStore) -> None:
        with pytest.raises(AgendaNotFoundError):
            store.delete_agenda("no-such")


class TestStoreItems:
    def test_upsert_round_trip(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda())
        store.upsert_item(_item("it-1", order=0))
        got = store.get_item("it-1")
        assert got is not None
        assert got.title == "Item 0"

    def test_list_items_order_default(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda())
        for i in range(3):
            store.upsert_item(_item(f"it-{i}", order=2 - i))  # insert in reverse
        out = store.list_items("ag-1")
        assert [i.order for i in out] == [0, 1, 2]

    def test_list_items_by_timecode_nulls_last(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda())
        store.upsert_item(
            AgendaItem(item_id="it-a", agenda_id="ag-1", order=0, title="A", video_timecode_s=300)
        )
        store.upsert_item(
            AgendaItem(item_id="it-b", agenda_id="ag-1", order=1, title="B", video_timecode_s=None)
        )
        store.upsert_item(
            AgendaItem(item_id="it-c", agenda_id="ag-1", order=2, title="C", video_timecode_s=100)
        )
        out = store.list_items("ag-1", order_by="timecode")
        # by timecode asc, NULL last
        assert [i.item_id for i in out] == ["it-c", "it-a", "it-b"]

    def test_delete_missing_item_raises(self, store: AgendaStore) -> None:
        with pytest.raises(AgendaItemNotFoundError):
            store.delete_item("no-such")

    def test_upsert_item_duplicate_order_raises_typed(self, store: AgendaStore) -> None:
        """Two distinct item_ids at the same (agenda_id, order) collide on
        the unique constraint. The store catches the underlying
        ``IntegrityError`` and re-raises a typed
        ``AgendaItemOrderConflictError`` (E-2 / Q-2 / T-1) so the router
        translates it to 409 instead of letting it bubble to 500."""
        store.upsert_agenda(_agenda())
        store.upsert_item(_item("it-a", order=0))
        with pytest.raises(AgendaItemOrderConflictError) as exc:
            store.upsert_item(_item("it-b", order=0))
        msg = str(exc.value)
        assert "order=0" in msg
        assert "ag-1" in msg

    def test_upsert_agenda_duplicate_station_asset_raises_typed(self, store: AgendaStore) -> None:
        """Two distinct agenda_ids targeting the same (station_id,
        meeting_asset_id) collide on the unique constraint. The store
        re-raises a typed ``AgendaUniqueViolationError`` so the router
        responds 409."""
        store.upsert_agenda(_agenda("ag-a"))
        with pytest.raises(AgendaUniqueViolationError):
            store.upsert_agenda(_agenda("ag-b"))

    def test_publish_if_nonempty_flips_to_published(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda())
        store.upsert_item(_item("it-1", order=0))
        out = store.publish_if_nonempty("ag-1")
        assert out.status == "published"

    def test_publish_if_nonempty_raises_on_empty_agenda(self, store: AgendaStore) -> None:
        """E-5 — the atomic publish gate fails closed when the items table
        is empty at the moment of the transaction. No partial state — the
        status stays draft."""
        store.upsert_agenda(_agenda())
        with pytest.raises(AgendaPublishEmptyError):
            store.publish_if_nonempty("ag-1")
        # Status untouched.
        got = store.get_agenda("ag-1")
        assert got is not None
        assert got.status == "draft"

    def test_publish_if_nonempty_raises_on_missing_agenda(self, store: AgendaStore) -> None:
        with pytest.raises(AgendaNotFoundError):
            store.publish_if_nonempty("no-such")


# --- migration 0058 ---------------------------------------------------------


def _make_cfg(database_url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


class TestMeetingAgendaMigration:
    """0058_meeting_agenda creates its two tables on upgrade and drops exactly
    those on a single-step downgrade to 0057 (the parent), leaving 0057's
    tables intact."""

    _TABLES = ("meeting_agendas", "agenda_items")

    def test_upgrade_to_0058_lands_at_that_revision(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "0058_meeting_agenda")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            with eng.connect() as conn:
                head = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert head == "0058_meeting_agenda"
        finally:
            eng.dispose()

    def test_upgrade_creates_the_two_tables_and_indexes(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "0058_meeting_agenda")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            insp = inspect(eng)
            for table in self._TABLES:
                assert insp.has_table(table), table
            ag_idx = {ix["name"] for ix in insp.get_indexes("meeting_agendas")}
            assert "ix_meeting_agendas_station" in ag_idx
            assert "ix_meeting_agendas_asset" in ag_idx
            it_idx = {ix["name"] for ix in insp.get_indexes("agenda_items")}
            assert "ix_agenda_items_agenda_order" in it_idx
            assert "ix_agenda_items_agenda_timecode" in it_idx
        finally:
            eng.dispose()

    def test_single_step_downgrade_drops_only_the_two_tables(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "0058_meeting_agenda")
        command.downgrade(cfg, "0057_underwriting_spots")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            insp = inspect(eng)
            for table in self._TABLES:
                assert not insp.has_table(table), table
            # 0057's tables survive the single-step downgrade.
            assert insp.has_table("underwriting_spots")
            assert insp.has_table("spot_flights")
            assert insp.has_table("spot_placements")
        finally:
            eng.dispose()


# --- request body shapes (Input + Update) -----------------------------------


class TestInputAndUpdateShapes:
    def test_agenda_input_forbids_status_so_creates_are_always_drafts(self) -> None:
        with pytest.raises(ValueError):
            MeetingAgendaInput(
                agenda_id="ag-1",
                station_id="sta",
                meeting_asset_id="m-1",
                status="published",  # type: ignore[call-arg]
            )

    def test_agenda_update_accepts_partial(self) -> None:
        u = MeetingAgendaUpdate(status="published")
        assert u.source_doc_url is None
        assert u.status == "published"

    def test_item_input_round_trip(self) -> None:
        i = AgendaItemInput(
            item_id="it-1",
            agenda_id="ag-1",
            order=0,
            title="Call to order",
        )
        assert i.video_timecode_s is None
        assert i.notes is None

    def test_item_update_partial(self) -> None:
        u = AgendaItemUpdate(video_timecode_s=300)
        assert u.title is None
        assert u.video_timecode_s == 300
