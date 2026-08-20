# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S6 V1 (build step 7) slice 2b — CG feed fetcher + parsers.

Covers civiccast.cg.feed_fetcher: per-kind parsers (RSS/Atom, iCal/CalDAV,
weather JSON, social JSON), the DTD/entity-expansion guard, fetch_feed_items
dispatch, the TTL cache + fetch_all (records last_fetched_at/last_fetch_error,
falls back on error, skips disabled feeds), and default_http_fetch's scheme
guard. No network — the fetch callable is injected with sample payloads.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.cg.board_models import CgFeedSource
from civiccast.cg.board_store import CgBoardStore
from civiccast.cg.feed_fetcher import (
    FeedCache,
    default_http_fetch,
    fetch_all,
    fetch_feed_items,
    parse_ical,
    parse_rss,
    parse_social,
    parse_weather,
)
from civiccast.db import Base

_NOW = datetime(2026, 6, 1, 18, 0, tzinfo=UTC)
_T0 = datetime(2026, 1, 1, tzinfo=UTC)

_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>City</title>
<item><title>Library board meets tonight</title><link>https://x.gov/lib</link>
<description>Coverage at 6 PM.</description><guid>lib-1</guid>
<pubDate>Mon, 01 Jun 2026 18:00:00 +0000</pubDate></item>
<item><title>Trail work begins Monday</title><link>https://x.gov/trail</link>
<description>Closures.</description><guid>trail-2</guid></item>
</channel></rss>"""

_ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Feed</title>
<entry><title>Atom notice</title><id>atom-1</id><link href="https://x.gov/a"/>
<summary>Summary text</summary><published>2026-06-01T18:00:00Z</published></entry>
</feed>"""

_ICAL = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:evt-1
SUMMARY:Planning Board
DTSTART;TZID=America/New_York:20260601T180000
DESCRIPTION:Monthly meeting
END:VEVENT
END:VCALENDAR"""

_WEATHER = (
    '{"alerts":[{"id":"wx-1","headline":"Winter storm warning",'
    '"description":"Heavy snow expected.","onset":"2026-06-01T18:00:00Z"}]}'
)

_SOCIAL = (
    '{"posts":[{"id":"p-1","text":"Parks posted a trail update",'
    '"url":"https://x.gov/p","created_at":"2026-06-01T18:00:00Z"}]}'
)

_BILLION_LAUGHS = (
    '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]>'
    "<rss><channel><item><title>&lol;</title></item></channel></rss>"
)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[CgBoardStore]:
    eng = create_engine(f"sqlite:///{tmp_path / 'feed.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    try:
        yield CgBoardStore(factory)
    finally:
        eng.dispose()


def _feed(
    store: CgBoardStore, feed_source_id: str, kind: str, url: str, **kwargs: object
) -> CgFeedSource:
    base: dict[str, object] = {
        "feed_source_id": feed_source_id,
        "channel_id": "public",
        "kind": kind,
        "label": f"{kind} feed",
        "source_url": url,
        "trust_tier": "operator_curated",
        "created_by": "op_a",
        "created_at": _T0,
    }
    base.update(kwargs)
    feed = CgFeedSource(**base)  # type: ignore[arg-type]
    store.upsert_feed(feed)
    return feed


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def test_parse_rss_items() -> None:
    items = parse_rss(_RSS)
    assert [i.item_id for i in items] == ["lib-1", "trail-2"]
    assert items[0].title == "Library board meets tonight"
    assert items[0].url == "https://x.gov/lib"
    assert items[0].summary == "Coverage at 6 PM."
    assert items[0].starts_at == datetime(2026, 6, 1, 18, 0, tzinfo=UTC)


def test_parse_atom_entries() -> None:
    items = parse_rss(_ATOM)
    assert len(items) == 1
    assert items[0].item_id == "atom-1"
    assert items[0].url == "https://x.gov/a"
    assert items[0].title == "Atom notice"


def test_parse_rss_rejects_dtd() -> None:
    with pytest.raises(ValueError, match="DTD/entity"):
        parse_rss(_BILLION_LAUGHS)


def test_parse_ical_event() -> None:
    items = parse_ical(_ICAL)
    assert len(items) == 1
    assert items[0].item_id == "evt-1"
    assert items[0].title == "Planning Board"
    assert items[0].summary == "Monthly meeting"
    assert items[0].starts_at == datetime(2026, 6, 1, 18, 0, tzinfo=UTC)


def test_parse_weather_alerts() -> None:
    items = parse_weather(_WEATHER)
    assert items[0].item_id == "wx-1"
    assert items[0].title == "Winter storm warning"
    assert items[0].starts_at == datetime(2026, 6, 1, 18, 0, tzinfo=UTC)


def test_parse_social_posts() -> None:
    items = parse_social(_SOCIAL)
    assert items[0].item_id == "p-1"
    assert items[0].title == "Parks posted a trail update"
    assert items[0].url == "https://x.gov/p"


def test_parser_skips_items_without_a_title() -> None:
    rss = '<?xml version="1.0"?><rss><channel><item><link>https://x</link></item></channel></rss>'
    assert parse_rss(rss) == []


# ---------------------------------------------------------------------------
# fetch_feed_items dispatch + fetch_all
# ---------------------------------------------------------------------------


def test_fetch_feed_items_dispatches_by_kind() -> None:
    feed = CgFeedSource(
        feed_source_id="f",
        channel_id="public",
        kind="ical",
        label="cal",
        source_url="https://x.gov/cal.ics",
        trust_tier="operator_curated",
        created_by="op",
        created_at=_T0,
    )
    items = fetch_feed_items(feed, fetch=lambda _url: _ICAL)
    assert items[0].title == "Planning Board"


def test_fetch_all_records_success_and_skips_disabled(store: CgBoardStore) -> None:
    _feed(store, "f_rss", "rss", "https://x.gov/news.rss")
    _feed(store, "f_off", "rss", "https://x.gov/off.rss", enabled=False)
    bodies = {"https://x.gov/news.rss": _RSS}
    result = fetch_all(store.list_feeds("public"), store, fetch=lambda url: bodies[url], now=_NOW)
    assert set(result) == {"f_rss"}  # disabled feed skipped
    assert [i.item_id for i in result["f_rss"]] == ["lib-1", "trail-2"]
    got = store.get_feed("f_rss")
    assert got is not None and got.last_fetched_at == _NOW and got.last_fetch_error is None


def test_fetch_all_cache_skips_network_within_ttl(store: CgBoardStore) -> None:
    _feed(store, "f_rss", "rss", "https://x.gov/news.rss", refresh_seconds=900)
    calls: list[str] = []

    def counting_fetch(url: str) -> str:
        calls.append(url)
        return _RSS

    cache = FeedCache()
    feeds = store.list_feeds("public")
    fetch_all(feeds, store, fetch=counting_fetch, now=_NOW, cache=cache)
    fetch_all(feeds, store, fetch=counting_fetch, now=_NOW + timedelta(seconds=100), cache=cache)
    assert len(calls) == 1  # second call was a fresh cache hit
    # Past the TTL the network is hit again.
    fetch_all(feeds, store, fetch=counting_fetch, now=_NOW + timedelta(seconds=1000), cache=cache)
    assert len(calls) == 2


def test_fetch_all_error_records_and_falls_back(store: CgBoardStore) -> None:
    _feed(store, "f_rss", "rss", "https://x.gov/news.rss")

    def boom(_url: str) -> str:
        raise OSError("connection refused")

    result = fetch_all(store.list_feeds("public"), store, fetch=boom, now=_NOW)
    assert result["f_rss"] == []  # no prior cache -> empty, not an exception
    got = store.get_feed("f_rss")
    assert got is not None and got.last_fetch_error is not None
    assert "connection refused" in got.last_fetch_error


def test_fetch_all_error_falls_back_to_last_cached(store: CgBoardStore) -> None:
    _feed(store, "f_rss", "rss", "https://x.gov/news.rss", refresh_seconds=10)
    cache = FeedCache()
    feeds = store.list_feeds("public")
    # First, a good fetch populates the cache.
    fetch_all(feeds, store, fetch=lambda _u: _RSS, now=_NOW, cache=cache)

    def boom(_url: str) -> str:
        raise OSError("down")

    # Past the TTL the refetch fails -> fall back to the last cached items.
    later = _NOW + timedelta(seconds=100)
    result = fetch_all(feeds, store, fetch=boom, now=later, cache=cache)
    assert [i.item_id for i in result["f_rss"]] == ["lib-1", "trail-2"]
    assert store.get_feed("f_rss").last_fetch_error == "down"  # type: ignore[union-attr]


def test_default_http_fetch_rejects_non_http_scheme() -> None:
    with pytest.raises(ValueError, match="unsupported feed URL scheme"):
        default_http_fetch("file:///etc/passwd")


def test_default_http_fetch_blocks_loopback_host() -> None:
    # SSRF guard: an operator-registered feed pointing at localhost is refused
    # before any socket is opened.
    with pytest.raises(ValueError, match="non-public address"):
        default_http_fetch("http://127.0.0.1/feed.xml")


def test_default_http_fetch_blocks_cloud_metadata_host() -> None:
    # The classic SSRF target (link-local cloud metadata) must be blocked.
    with pytest.raises(ValueError, match="non-public address"):
        default_http_fetch("http://169.254.169.254/latest/meta-data/")


def test_feed_source_rejects_non_http_url_at_construction() -> None:
    # Scheme is validated at model creation so a file:// URL never reaches the DB.
    with pytest.raises(ValidationError, match="http"):
        CgFeedSource(
            feed_source_id="f1",
            channel_id="public",
            kind="rss",
            label="bad",
            source_url="file:///etc/passwd",
            trust_tier="operator_curated",
            created_by="op",
            created_at=_NOW,
        )


def test_fetch_stamps_feed_tags_onto_items() -> None:
    feed = CgFeedSource(
        feed_source_id="f",
        channel_id="public",
        kind="rss",
        label="news",
        source_url="https://x.gov/news.rss",
        trust_tier="operator_curated",
        tags=["events", "community"],
        created_by="op",
        created_at=_T0,
    )
    items = fetch_feed_items(feed, fetch=lambda _url: _RSS)
    assert items and all(i.tags == ["events", "community"] for i in items)


def test_fetch_without_feed_tags_leaves_items_untagged() -> None:
    feed = CgFeedSource(
        feed_source_id="f",
        channel_id="public",
        kind="rss",
        label="news",
        source_url="https://x.gov/news.rss",
        trust_tier="operator_curated",
        created_by="op",
        created_at=_T0,
    )
    items = fetch_feed_items(feed, fetch=lambda _url: _RSS)
    assert items and all(i.tags == [] for i in items)
