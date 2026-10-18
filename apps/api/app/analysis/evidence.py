"""Observation checks. Unknown times stay unknown. Quarantine stays out."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone

from app.analysis.schema import EvidenceItem

_INJECTION = re.compile(
    r"(?i)(ignore\s+(all\s+)?previous|system\s*:|api[_-]?key|begin\s+tool|place\s+an?\s+order|forecast_ready\s*[:=])"
)
_WINDOWS = {
    "INTRADAY": timedelta(minutes=30),
    "SHORT_TERM": timedelta(days=3),
    "LONGER_TERM": timedelta(days=30),
}


def aware(value: object) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return None
    return value.astimezone(timezone.utc)


def quarantine_reason(row: dict) -> str | None:
    if row.get("quarantine_id") or row.get("label") == "UNVERIFIED_PROVIDER":
        return "Quarantined provider data is not a trusted observation."
    if row.get("candle_boundary") == "UNVERIFIED" or row.get("timestamp_timezone") == "UNVERIFIED":
        return "Unverified candle timestamp semantics were rejected."
    if row.get("data_category") == "UNVERIFIED_PROVIDER":
        return "Unverified provider history was rejected."
    return None


def freshness(observed_at: datetime | None, as_of: datetime, horizon: str, instrument: str | None = None) -> str:
    if observed_at is None:
        return "UNKNOWN"
    if observed_at > as_of:
        return "UNKNOWN"
    window = _WINDOWS.get(horizon, _WINDOWS["INTRADAY"])
    if as_of - observed_at > window:
        if instrument:
            try:
                from app.market.session_intelligence import (
                    MarketState,
                    assess_market_session,
                )
                sess = assess_market_session(instrument, as_of)
                if sess.market_state in (MarketState.CLOSED, MarketState.POST_CLOSE):
                    return "CLOSED_SESSION_VALID"
            except Exception:
                pass
        return "STALE"
    return "FRESH"


def evidence_id(row: dict) -> str:
    raw = "|".join(
        [
            str(row.get("category") or ""),
            str(row.get("claim") or ""),
            str(row.get("source_name") or ""),
            str(row.get("instrument") or ""),
            str(row.get("published_at") or ""),
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def untrusted(text: str) -> tuple[str, list[str]]:
    cleaned = " ".join(str(text or "").split())[:500]
    notes: list[str] = []
    if _INJECTION.search(cleaned):
        notes.append("Source text contained instruction-like content and was not followed.")
        cleaned = "Untrusted source text was withheld from the claim."
    return cleaned, notes


def build_evidence(row: dict, *, as_of: datetime, horizon: str) -> EvidenceItem | None:
    claim, notes = untrusted(str(row.get("claim") or ""))
    if not claim:
        return None
    retrieved = aware(row.get("retrieved_at"))
    if retrieved is None:
        return None
    observed = aware(row.get("observed_at")) if row.get("observed_at") is not None else None
    published = aware(row.get("published_at")) if row.get("published_at") is not None else None
    if row.get("observed_at") is not None and observed is None:
        return None
    if row.get("published_at") is not None and published is None:
        return None
    provenance = row.get("provenance") if row.get("provenance") in {"PROVIDER", "DOCUMENTED_SAMPLE", "SYNTHETIC"} else "SYNTHETIC"
    category = row.get("category") if row.get("category") in {"NEWS", "MACRO", "GLOBAL_MARKET", "INDIAN_MARKET", "DERIVATIVES", "TECHNICAL", "OTHER"} else "OTHER"
    item = EvidenceItem(
        evidence_id=evidence_id(row),
        category=category,
        claim=claim,
        claim_type=row.get("claim_type") if row.get("claim_type") in {"OBSERVATION", "SOURCE_CLAIM", "CALCULATION", "INTERPRETATION"} else "SOURCE_CLAIM",
        source_name=str(row.get("source_name") or "unspecified"),
        source_url=row.get("source_url") if isinstance(row.get("source_url"), str) else None,
        observed_at=observed,
        published_at=published,
        retrieved_at=retrieved,
        instrument=row.get("instrument") if isinstance(row.get("instrument"), str) else None,
        directional_implication=row.get("directional_implication") if row.get("directional_implication") in {"BULLISH", "BEARISH", "MIXED", "UNKNOWN"} else "UNKNOWN",
        time_horizon=row.get("time_horizon") if row.get("time_horizon") in {"INTRADAY", "SHORT_TERM", "LONGER_TERM", "UNKNOWN"} else "UNKNOWN",
        provenance=provenance,
        freshness=freshness(observed, as_of, horizon, instrument=row.get("instrument")),
        verification_status="UNVERIFIED",
        limitations=list(dict.fromkeys(notes + ([str(x) for x in row["limitations"] if isinstance(x, str)] if isinstance(row.get("limitations"), list) else []))),
        claim_kind=_claim_kind(row.get("claim_kind")),
        event_category=_category_label(row.get("event_category")),
        affected_entities=_entities(row.get("affected_entities")),
    )
    return item


def _claim_kind(value: object) -> str:
    if value in {"FACT", "ALLEGATION", "ESTIMATE", "OPINION", "UNKNOWN"}:
        return str(value)
    return "UNKNOWN"


def _category_label(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    label = " ".join(value.split())[:80]
    return label or None


def _entities(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    names = []
    for item in value:
        if isinstance(item, str) and item.strip():
            names.append(" ".join(item.split())[:80])
    return names[:12]
