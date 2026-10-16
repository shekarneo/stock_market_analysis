"""Fetch public market RSS feeds and keep the headlines for the news agent.

Each feed URL is fixed in this module. A caller cannot supply a host.
Headlines stay unverified source claims with no bullish or bearish label.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from xml.etree.ElementTree import ParseError

import httpx

from app.news.rss import parse_feed
from app.security.ssrf import guard_endpoint
from app.settings import REPO_ROOT

READ_PATH = REPO_ROOT / "var" / "news" / "latest.json"
_MAX_BYTES = 1_000_000
_PER_FEED = 8

# Public market sections. These are the only URLs this reader requests.
PUBLIC_FEEDS = (
    ("economic_times_markets", "Economic Times", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("livemint_markets", "Mint", "https://www.livemint.com/rss/markets"),
    ("business_standard_markets", "Business Standard", "https://www.business-standard.com/rss/markets-106.rss"),
    ("the_hindu_business", "The Hindu", "https://www.thehindu.com/business/feeder/default.rss"),
    ("moneycontrol_latest", "Moneycontrol", "https://www.moneycontrol.com/rss/latestnews.xml"),
)


def stored_news_observations(path: Path | None = None) -> list[dict]:
    record = load_news(path)
    if not record:
        return []
    items = record.get("items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def load_news(path: Path | None = None) -> dict | None:
    target = path or READ_PATH
    if not target.is_file():
        return None
    try:
        body = json.loads(target.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return body if isinstance(body, dict) else None


def save_news(record: dict, path: Path | None = None) -> None:
    target = path or READ_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, separators=(",", ":")))
    temporary.replace(target)


def http_get(url: str, *, timeout: float) -> tuple[int, bytes]:
    """GET one public feed. Each redirect is checked again before it is followed."""
    current = url
    with httpx.Client(timeout=timeout, follow_redirects=False, headers={"user-agent": "IndiaMarketMaster/0.1"}) as client:
        for _ in range(3):
            guard_endpoint("rss", current)
            response = client.get(current)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    return response.status_code, b""
                current = urljoin(current, location)
                continue
            return response.status_code, response.content[:_MAX_BYTES]
    return 0, b""


def run_news_read(*, getter, retrieved_at: datetime, path: Path | None = None, feeds=PUBLIC_FEEDS) -> dict:
    """Read the fixed public feeds and store headlines. This does not score direction."""
    retrieved_at = retrieved_at if retrieved_at.tzinfo else retrieved_at.replace(tzinfo=timezone.utc)
    items: list[dict] = []
    seen: set[str] = set()
    feed_results = []
    calls = 0
    for feed_id, name, url in feeds:
        calls += 1
        try:
            status, payload = getter(url, timeout=12)
        except Exception as exc:
            feed_results.append({"id": feed_id, "name": name, "status": "FAILED", "count": 0, "error": type(exc).__name__})
            continue
        if status != 200 or not payload:
            feed_results.append({"id": feed_id, "name": name, "status": "FAILED", "count": 0, "error": f"HTTP {status}"})
            continue
        try:
            parsed = parse_feed(payload, source_name=name, retrieved_at=retrieved_at, max_items=_PER_FEED)
        except ParseError:
            feed_results.append({"id": feed_id, "name": name, "status": "FAILED", "count": 0, "error": "UNPARSEABLE"})
            continue
        kept = 0
        for row in parsed:
            key = (row.get("source_url") or row["claim"]).casefold()
            if key in seen:
                continue
            seen.add(key)
            items.append(row)
            kept += 1
        feed_results.append({"id": feed_id, "name": name, "status": "READ", "count": kept, "error": None})
    record = {
        "status": "READ" if items else "EMPTY",
        "retrieved_at": retrieved_at.astimezone(timezone.utc).isoformat(),
        "network_calls": calls,
        "items": items,
        "feeds": feed_results,
        "directional_implication": "UNKNOWN",
        "decision": "NO_TRADE",
    }
    save_news(record, path)
    return _public(record)


def _public(record: dict) -> dict:
    items = []
    for row in record.get("items") or []:
        items.append(
            {
                "claim": row.get("claim"),
                "source_name": row.get("source_name"),
                "source_url": row.get("source_url"),
                "summary": row.get("summary") or "",
                "published_at": row.get("published_at"),
                "retrieved_at": row.get("retrieved_at"),
                "directional_implication": "UNKNOWN",
            }
        )
    return {
        "status": record.get("status"),
        "retrieved_at": record.get("retrieved_at"),
        "network_calls": record.get("network_calls", 0),
        "count": len(items),
        "items": items,
        "feeds": record.get("feeds") or [],
        "directional_implication": "UNKNOWN",
        "decision": "NO_TRADE",
    }
