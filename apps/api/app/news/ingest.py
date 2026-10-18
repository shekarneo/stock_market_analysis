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
SOURCES_PATH = REPO_ROOT / "var" / "news" / "sources.json"
_MAX_BYTES = 1_000_000
_PER_FEED = 8

# Default public market feeds.
DEFAULT_SOURCES = [
    {
        "id": "economic_times_markets",
        "name": "Economic Times",
        "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "enabled": True,
        "is_default": True,
    },
    {
        "id": "livemint_markets",
        "name": "Mint",
        "url": "https://www.livemint.com/rss/markets",
        "enabled": True,
        "is_default": True,
    },
    {
        "id": "business_standard_markets",
        "name": "Business Standard",
        "url": "https://www.business-standard.com/rss/markets-106.rss",
        "enabled": True,
        "is_default": True,
    },
    {
        "id": "the_hindu_business",
        "name": "The Hindu",
        "url": "https://www.thehindu.com/business/feeder/default.rss",
        "enabled": True,
        "is_default": True,
    },
    {
        "id": "moneycontrol_latest",
        "name": "Moneycontrol",
        "url": "https://www.moneycontrol.com/rss/latestnews.xml",
        "enabled": True,
        "is_default": True,
    },
]

# Backward-compatible tuple for legacy consumers
PUBLIC_FEEDS = tuple((s["id"], s["name"], s["url"]) for s in DEFAULT_SOURCES)


def load_news_sources(path: Path | None = None) -> list[dict]:
    """Load the configured news feeds from disk, falling back to default sources."""
    target = path or SOURCES_PATH
    if not target.is_file():
        return [dict(s) for s in DEFAULT_SOURCES]
    try:
        data = json.loads(target.read_text())
        if isinstance(data, list) and len(data) > 0:
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return [dict(s) for s in DEFAULT_SOURCES]


def save_news_sources(sources: list[dict], path: Path | None = None) -> None:
    """Save the configured news feeds atomically to disk."""
    target = path or SOURCES_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(sources, indent=2))
    temporary.replace(target)


def get_active_news_feeds(path: Path | None = None) -> list[tuple[str, str, str]]:
    """Return only enabled feeds as (id, name, url) tuples for the reader."""
    sources = load_news_sources(path)
    return [
        (s["id"], s["name"], s["url"])
        for s in sources
        if s.get("enabled", True)
    ]


def _slugify(text: str) -> str:
    import re
    cleaned = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "_", cleaned) or "feed"


def add_news_source(name: str, url: str, enabled: bool = True, path: Path | None = None) -> dict:
    """Add a new news source and save configuration."""
    from urllib.parse import urlsplit
    name = name.strip()
    url = url.strip()
    if not name:
        raise ValueError("Feed name cannot be blank")
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError("Feed URL must start with http:// or https://")
    try:
        guard_endpoint("rss", url)
    except Exception as exc:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
        if not host or host in {"localhost", "localhost.localdomain", "127.0.0.1", "::1"}:
            raise ValueError("Private or loopback addresses are forbidden.")
        if host.startswith(("10.", "192.168.", "172.16.", "169.254.")):
            raise ValueError("Private network addresses are forbidden.")
        # If it was just an offline DNS lookup failure, allow public web domain
    sources = load_news_sources(path)
    base_id = _slugify(name)
    feed_id = base_id
    idx = 1
    existing_ids = {s["id"] for s in sources}
    while feed_id in existing_ids:
        feed_id = f"{base_id}_{idx}"
        idx += 1
    new_source = {
        "id": feed_id,
        "name": name,
        "url": url,
        "enabled": enabled,
        "is_default": False,
    }
    sources.append(new_source)
    save_news_sources(sources, path)
    return new_source


def toggle_news_source(source_id: str, enabled: bool | None = None, path: Path | None = None) -> dict:
    """Toggle or set the enabled flag for a news source."""
    sources = load_news_sources(path)
    matched = None
    for s in sources:
        if s["id"] == source_id:
            s["enabled"] = not s["enabled"] if enabled is None else bool(enabled)
            matched = s
            break
    if not matched:
        raise KeyError(f"News source '{source_id}' not found")
    save_news_sources(sources, path)
    return matched


def delete_news_source(source_id: str, path: Path | None = None) -> bool:
    """Remove a news source from configuration."""
    sources = load_news_sources(path)
    new_sources = [s for s in sources if s["id"] != source_id]
    if len(new_sources) == len(sources):
        return False
    save_news_sources(new_sources, path)
    return True


def reset_news_sources(path: Path | None = None) -> list[dict]:
    """Reset all news sources to the original defaults."""
    defaults = [dict(s) for s in DEFAULT_SOURCES]
    save_news_sources(defaults, path)
    return defaults


def stored_news_observations(path: Path | None = None) -> list[dict]:
    record = load_news(path)
    if not record:
        return []
    items = record.get("items")
    if not isinstance(items, list):
        return []
    from app.news.classifier import classify_news_item
    return [classify_news_item(item) for item in items if isinstance(item, dict)]


def load_news(path: Path | None = None) -> dict | None:
    target = path or READ_PATH
    if not target.is_file():
        return None
    try:
        body = json.loads(target.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(body, dict) and isinstance(body.get("items"), list):
        from app.news.classifier import classify_all_news_items
        body["items"] = classify_all_news_items(body["items"])
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


def run_news_read(*, getter, retrieved_at: datetime, path: Path | None = None, feeds=None) -> dict:
    """Read the configured public feeds and store headlines. This does not score direction."""
    if feeds is None:
        feeds = get_active_news_feeds()
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
    from app.news.classifier import classify_all_news_items
    classified_items = classify_all_news_items(items)
    record = {
        "status": "READ" if classified_items else "EMPTY",
        "retrieved_at": retrieved_at.astimezone(timezone.utc).isoformat(),
        "network_calls": calls,
        "items": classified_items,
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
                "event_category": row.get("event_category"),
                "classification_provenance": row.get("classification_provenance"),
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
