"""RSS and Atom headlines. A missing publication time stays missing."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from xml.etree import ElementTree

_TAGS = re.compile(r"<[^>]+>")
_MAX_SUMMARY = 240


def parse_feed(payload: bytes, *, source_name: str, retrieved_at: datetime, max_items: int) -> list[dict]:
    """Return headline rows. Dates that do not parse are omitted rather than guessed."""
    root = ElementTree.fromstring(payload)
    rows: list[dict] = []
    for node in root.iter():
        if _local(node.tag) not in {"item", "entry"}:
            continue
        title = _plain(_child_text(node, "title"))
        if not title:
            continue
        link = _link(node)
        published = _published(node)
        summary = _plain(_child_text(node, "description") or _child_text(node, "summary"))[:_MAX_SUMMARY]
        row = {
            "category": "NEWS",
            "claim": title[:500],
            "claim_type": "SOURCE_CLAIM",
            "claim_kind": "UNKNOWN",
            "source_name": source_name,
            "source_url": link,
            "summary": summary,
            "retrieved_at": _iso(retrieved_at),
            "provenance": "PROVIDER",
            "directional_implication": "UNKNOWN",
            "time_horizon": "UNKNOWN",
        }
        if published is not None:
            stamp = _iso(published)
            row["published_at"] = stamp
            row["observed_at"] = stamp
        rows.append(row)
        if len(rows) >= max_items:
            break
    return rows


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(node: ElementTree.Element, name: str) -> str:
    for child in list(node):
        if _local(child.tag) == name:
            return "".join(child.itertext())
    return ""


def _link(node: ElementTree.Element) -> str | None:
    for child in list(node):
        if _local(child.tag) != "link":
            continue
        href = child.attrib.get("href") or (child.text or "")
        href = href.strip()
        if href.startswith(("http://", "https://")):
            return href[:500]
    return None


def _published(node: ElementTree.Element) -> datetime | None:
    raw = ""
    for name in ("pubDate", "published", "updated", "date"):
        raw = _child_text(node, name).strip()
        if raw:
            break
    if not raw:
        return None
    parsed = _parse_time(raw)
    if parsed is None or parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        return None
    return parsed.astimezone(timezone.utc)


def _parse_time(raw: str) -> datetime | None:
    try:
        parsed = parsedate_to_datetime(raw)
        if parsed is not None:
            return parsed
    except (TypeError, ValueError, IndexError, OverflowError):
        pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _plain(value: str) -> str:
    text = unescape(_TAGS.sub(" ", value or ""))
    return " ".join(text.split())


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()
