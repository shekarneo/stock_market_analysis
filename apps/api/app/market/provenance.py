"""Provenance categories for research evaluation.

A provider origin is not verification. HTTP success and OHLC validation are not
verification. This module never returns VERIFIED_HISTORICAL.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from app.settings import REPO_ROOT

_CATEGORIES = {
    "SYNTHETIC": "SYNTHETIC",
    "DOCUMENTED_SAMPLE": "DOCUMENTED_SAMPLE",
    "PROVIDER": "UNVERIFIED_PROVIDER",
}
_REJECTED = (
    "QUARANTINE_REJECTED",
    "Quarantined Groww candles cannot be used as trusted training data.",
)
LINEAGE_SCHEMA = "lineage-1"
_RESEARCH_ORIGINS = {"SYNTHETIC", "DOCUMENTED_SAMPLE", "PROVIDER"}


def data_category(dataset: dict) -> str:
    return _CATEGORIES.get(str(dataset.get("origin") or ""), "UNKNOWN")


def quarantine_training_block(payload: dict) -> tuple[str, str] | None:
    """Stop a quarantined Groww payload before features, labels, or training.

    A structural OHLC pass is not trusted market data. Markers can be removed
    and bar times can be replaced. Stored quarantine OHLC still identifies the
    copied candle. This function does not write a file or call a provider.
    """
    stored = _stored_quarantine_ohlc()
    if stored is None:
        return _REJECTED
    if _quarantine_marker(payload) or _matches_stored_ohlc(payload, stored):
        return _REJECTED
    for key in ("candles", "source_candles", "raw_candles", "rows"):
        rows = payload.get(key)
        if isinstance(rows, list) and any(_row_is_quarantined(row, stored) for row in rows):
            return _REJECTED
    return None


def quarantine_candle_block(candles: list) -> tuple[str, str] | None:
    """Reject a candle list when any row still carries stored quarantine OHLC."""
    stored = _stored_quarantine_ohlc()
    if stored is None:
        return _REJECTED
    if any(_row_is_quarantined(candle, stored) for candle in candles):
        return _REJECTED
    return None


def _quarantine_marker(item: dict) -> bool:
    if item.get("quarantine_id") or item.get("label") == "UNVERIFIED_PROVIDER" or item.get("data_category") == "UNVERIFIED_PROVIDER":
        return True
    return item.get("timestamp_timezone") == "UNVERIFIED" or item.get("candle_boundary") == "UNVERIFIED"


def _row_is_quarantined(row: object, stored: set[tuple[float, float, float, float]]) -> bool:
    if isinstance(row, dict) and _quarantine_marker(row):
        return True
    key = _ohlc_key(row)
    return key is not None and key in stored


def _matches_stored_ohlc(item: object, stored: set[tuple[float, float, float, float]]) -> bool:
    key = _ohlc_key(item)
    return key is not None and key in stored


def _ohlc_key(item: object) -> tuple[float, float, float, float] | None:
    if isinstance(item, dict):
        if not all(name in item for name in ("open", "high", "low", "close")):
            return None
        values = (item.get("open"), item.get("high"), item.get("low"), item.get("close"))
    elif isinstance(item, (list, tuple)) and len(item) >= 5 and isinstance(item[0], str):
        values = (item[1], item[2], item[3], item[4])
    elif all(hasattr(item, name) for name in ("open", "high", "low", "close")):
        values = (item.open, item.high, item.low, item.close)
    else:
        return None
    try:
        key = tuple(float(value) for value in values)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in key):
        return None
    return key


def _source_digest(candles: list) -> str:
    from app.features.pipeline import content_hash

    return content_hash({"candles": candles})


def _feature_checksum(artifact: dict) -> bool:
    from app.features.pipeline import content_hash

    body = {key: value for key, value in artifact.items() if key not in {"dataset_id", "checksum"}}
    digest = content_hash(body)
    return artifact.get("dataset_id") == digest and artifact.get("checksum") == digest


def _parent_is_quarantined(parent_id: object) -> bool:
    if not isinstance(parent_id, str) or parent_id == "":
        return False
    root = Path(REPO_ROOT / "var" / "history" / "quarantine")
    try:
        names = {path.stem for path in root.glob("*.json")}
    except OSError:
        return True
    return parent_id in names


def _stored_quarantine_ohlc() -> set[tuple[float, float, float, float]] | None:
    """Read stored quarantine prices. None means the directory could not be trusted."""
    root = Path(REPO_ROOT / "var" / "history" / "quarantine")
    if not root.exists():
        return set()
    found: set[tuple[float, float, float, float]] = set()
    try:
        paths = list(root.glob("*.json"))
    except OSError:
        return None
    for path in paths:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        if not isinstance(record, dict):
            return None
        candles = record.get("raw_candles") or []
        if not isinstance(candles, list):
            return None
        for row in candles:
            key = _ohlc_key(row)
            if key is not None:
                found.add(key)
    return found


def make_lineage(
    *,
    origin: str,
    source_id: str,
    source_row_sha256: str,
    parent_dataset_id: str | None,
    parent_checksum: str | None,
) -> dict:
    """Identity carried inside a sealed dataset.

    The research declaration is the explicit dataset origin. It is not market
    verification, and a caller eligibility flag is not part of this record.
    """
    return {
        "schema": LINEAGE_SCHEMA,
        "origin": origin,
        "source_id": source_id,
        "source_row_sha256": source_row_sha256,
        "parent_dataset_id": parent_dataset_id,
        "parent_checksum": parent_checksum,
        "market_data_verified": False,
        "research_declaration": origin if origin in _RESEARCH_ORIGINS else "UNVERIFIED_PROVIDER",
    }


def lineage_block(dataset: dict) -> tuple[str, str] | None:
    """Reject training input whose sealed lineage is missing or no longer matches.

    This is the dataset boundary. Exact OHLC comparison is not the decision.
    """
    lineage = dataset.get("lineage")
    if not isinstance(lineage, dict) or lineage.get("schema") != LINEAGE_SCHEMA:
        return ("LINEAGE_MISSING", "Training requires the sealed dataset lineage record.")
    if lineage.get("market_data_verified") is not False:
        return ("VERIFICATION_REFUSED", "Lineage cannot claim verified market history.")
    if lineage.get("origin") != dataset.get("origin") or lineage.get("research_declaration") != dataset.get("origin"):
        return ("LINEAGE_MISMATCH", "The dataset origin does not match its sealed lineage.")
    if dataset.get("origin") not in _RESEARCH_ORIGINS:
        return _REJECTED
    source = dataset.get("source_candles")
    if not isinstance(source, list) or lineage.get("source_row_sha256") != _source_digest(source):
        return ("LINEAGE_MISMATCH", "Source candles do not match the sealed lineage.")
    if dataset.get("source_row_sha256") != lineage.get("source_row_sha256"):
        return ("LINEAGE_MISMATCH", "Source candles do not match the sealed lineage.")
    if not _feature_checksum(dataset):
        return ("CHECKSUM_MISMATCH", "The feature dataset checksum does not match its contents.")
    parent = lineage.get("parent_dataset_id")
    if _parent_is_quarantined(parent):
        return _REJECTED
    return None


def evaluation_block(dataset: dict, *, require_verified_history: bool) -> tuple[str, str] | None:
    blocked = quarantine_training_block(dataset)
    if blocked is not None:
        return blocked
    if dataset.get("real_market_data_verified") is True or dataset.get("live_market_data") is True:
        return (
            "VERIFICATION_REFUSED",
            "This dataset claims verified or live market history. That claim is not accepted.",
        )
    if dataset.get("candle_completion_verified") is False:
        return (
            "CANDLE_COMPLETION_UNVERIFIED",
            "Candle completion semantics are unverified, so the series cannot be evaluated.",
        )
    category = data_category(dataset)
    if category == "UNKNOWN":
        return (
            "MIXED_PROVENANCE",
            "The dataset origin is missing or is not a known provenance category.",
        )
    blocked = lineage_block(dataset)
    if blocked is not None:
        return blocked
    if require_verified_history:
        return (
            "UNVERIFIED_HISTORY",
            f"Verified historical evaluation requires verified market data. This dataset is {category}.",
        )
    return None
