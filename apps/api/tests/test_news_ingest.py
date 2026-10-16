from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.analysis.service import assemble_analysis
from app.news.ingest import load_news, run_news_read, stored_news_observations
from app.news.rss import parse_feed
from tests.conftest import login

_RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
<item>
  <title>Nifty ends flat as banks slip</title>
  <link>https://news.example/nifty</link>
  <pubDate>Wed, 15 Oct 2026 03:30:00 +0000</pubDate>
  <description>&lt;p&gt;Banks &amp; metals lagged.&lt;/p&gt;</description>
</item>
<item>
  <title>Headline without a date</title>
  <link>https://news.example/undated</link>
  <description>No publication time was given.</description>
</item>
</channel></rss>
"""

_ATOM = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry>
  <title>RBI holds the rate</title>
  <link href="https://news.example/rbi"/>
  <published>2026-10-15T04:00:00Z</published>
  <summary>The policy rate was left unchanged.</summary>
</entry>
</feed>
"""


def test_parser_keeps_a_real_time_and_leaves_a_missing_time_blank():
    retrieved = datetime(2026, 10, 15, 5, 0, tzinfo=timezone.utc)
    rows = parse_feed(_RSS, source_name="Example", retrieved_at=retrieved, max_items=8)
    assert rows[0]["claim"] == "Nifty ends flat as banks slip"
    assert rows[0]["published_at"].startswith("2026-10-15T03:30:00")
    assert rows[0]["summary"] == "Banks & metals lagged."
    assert rows[0]["directional_implication"] == "UNKNOWN"
    assert "published_at" not in rows[1]
    assert "observed_at" not in rows[1]
    atom = parse_feed(_ATOM, source_name="Example", retrieved_at=retrieved, max_items=8)
    assert atom[0]["source_url"] == "https://news.example/rbi"
    assert atom[0]["published_at"].startswith("2026-10-15T04:00:00")


def test_refresh_stores_headlines_and_a_bad_feed_does_not_erase_the_good_one(tmp_path: Path):
    target = tmp_path / "latest.json"
    feeds = (("example", "Example", "https://news.example/rss"), ("broken", "Broken", "https://news.example/bad"))

    def getter(url, *, timeout):
        del timeout
        if url.endswith("/bad"):
            return 500, b""
        return 200, _RSS

    result = run_news_read(
        getter=getter,
        retrieved_at=datetime(2026, 10, 15, 5, 0, tzinfo=timezone.utc),
        path=target,
        feeds=feeds,
    )
    assert result["status"] == "READ"
    assert result["count"] == 2
    assert result["decision"] == "NO_TRADE"
    assert result["network_calls"] == 2
    assert {item["status"] for item in result["feeds"]} == {"READ", "FAILED"}
    stored = stored_news_observations(target)
    assert stored[0]["provenance"] == "PROVIDER"
    assert load_news(target)["items"][0]["claim"].startswith("Nifty")


def test_stored_headlines_reach_the_news_agent_without_a_trade(tmp_path: Path):
    target = tmp_path / "latest.json"
    run_news_read(
        getter=lambda url, timeout: (200, _RSS),
        retrieved_at=datetime(2026, 10, 15, 5, 0, tzinfo=timezone.utc),
        path=target,
        feeds=(("example", "Example", "https://news.example/rss"),),
    )
    report = assemble_analysis(
        instruments=["NIFTY"],
        observations=stored_news_observations(target),
        created_at=datetime(2026, 10, 15, 5, 30, tzinfo=timezone.utc),
    )
    news = report["intelligence"]["news"]
    assert any(item["claim"] == "Nifty ends flat as banks slip" for item in news)
    assert all(item["directions"] == ["UNKNOWN"] for item in news)
    assert report["decision"] == "NO_TRADE"


def test_news_routes_require_a_session_and_store_a_confirmed_read(client, monkeypatch, tmp_path: Path):
    target = tmp_path / "latest.json"
    monkeypatch.setattr("app.news.routes.load_news", lambda: None)
    assert client.get("/api/news").status_code == 401
    token = login(client)
    empty = client.get("/api/news")
    assert empty.status_code == 200
    assert empty.json()["status"] == "NOT_READ"
    missing = client.post("/api/news/refresh", json={})
    assert missing.status_code == 422
    no_csrf = client.post("/api/news/refresh", json={"confirm": True})
    assert no_csrf.status_code == 403

    def fake_read(*, getter, retrieved_at, path=None, feeds=None):
        del getter, retrieved_at, path, feeds
        return {
            "status": "READ",
            "retrieved_at": "2026-10-15T05:00:00+00:00",
            "network_calls": 1,
            "count": 1,
            "items": [{"claim": "Stored headline", "source_name": "Example", "source_url": "https://news.example/a", "summary": "", "published_at": None, "retrieved_at": "2026-10-15T05:00:00+00:00", "directional_implication": "UNKNOWN"}],
            "feeds": [],
            "directional_implication": "UNKNOWN",
            "decision": "NO_TRADE",
        }

    monkeypatch.setattr("app.news.routes.run_news_read", fake_read)
    refreshed = client.post("/api/news/refresh", headers={"x-csrf-token": token}, json={"confirm": True})
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["count"] == 1
    assert refreshed.json()["decision"] == "NO_TRADE"
