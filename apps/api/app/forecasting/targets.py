"""Binary next-bar target binary-1.

This is an experimental label. It is not the three-class threshold protocol.
Zero returns are class 0. The last bar has no fabricated label.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from app.features.definitions import FEATURE_SET_VERSION, INTERVAL_MINUTES
from app.market.schemas import IST

TARGET_ID = "m15_next_close_direction"
TARGET_VERSION = "binary-1"
HORIZON = "next_m15_close"
LABEL_FORMULA = "future_return[t] = close[t+1] / close[t] - 1; direction[t] = 1 if future_return[t] > 0 else 0"
LABEL_AVAILABILITY = (
    "The label for prediction time t is available only at bar_end[t+1], and only when "
    "that candle is complete under the M1 rule retrieved_at >= bar_end. Features at t "
    "stop at bar_end[t]. The final candle in the series has no label."
)
INTERVAL = timedelta(minutes=INTERVAL_MINUTES)

# session_confirmed is a calendar gate, not a model input. It is constant on a listed session.
# Every model input is scale-free (a return, ratio or position), so the fitted scaler does
# not drift out of distribution as the index level moves. Price-level columns (sma_3,
# sma_5, sma_3_minus_sma_5, atr_3) stay in the dataset but are not model inputs.
MODEL_FEATURES: tuple[str, ...] = (
    "ret_1",
    "ret_3",
    "close_vs_sma_3",
    "close_vs_sma_5",
    "sma_3_vs_sma_5",
    "ret_std_5",
    "atr_3_pct",
    "hl_range_vs_prev_close",
    "oc_return",
    "close_position",
)


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(IST)


def _stamp(value: str) -> str:
    return _parse(value).isoformat()


def _reason_for_features(values: dict) -> str | None:
    for name in MODEL_FEATURES:
        item = values.get(name)
        if item is None:
            return f"FEATURE_MISSING_{name}"
        status = item.get("status")
        if status != "VALID":
            return f"FEATURE_{status}_{name}"
        value = item.get("value")
        if value is None or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return f"FEATURE_INVALID_{name}"
    return None


def label_dataset(artifact: dict) -> dict:
    """Join feature rows to the next completed candle. Does not invent labels."""
    from app.market.provenance import quarantine_training_block

    blocked = quarantine_training_block(artifact)
    if blocked is not None:
        return _failure(blocked[0], blocked[1])
    if artifact.get("lineage") is not None:
        from app.market.provenance import lineage_block

        lineage_error = lineage_block(artifact)
        if lineage_error is not None:
            return _failure(lineage_error[0], lineage_error[1])
    if artifact.get("feature_set_version") != FEATURE_SET_VERSION:
        return _failure("FEATURE_VERSION_MISMATCH", f"The dataset feature set is not {FEATURE_SET_VERSION}.")
    if artifact.get("interval") != "M15":
        return _failure("UNSUPPORTED_INTERVAL", "The binary-1 target is defined for M15 only.")
    if artifact.get("forecast_ready") is not False:
        return _failure("FORECAST_READY_REFUSED", "A dataset must not already claim forecast readiness.")
    candles = artifact.get("source_candles") or []
    rows = artifact.get("rows") or []
    by_end: dict[str, dict] = {}
    for candle in candles:
        try:
            stamp = _stamp(candle["bar_end"])
        except (KeyError, TypeError, ValueError):
            return _failure("MALFORMED_CANDLE", "A source candle has no timezone-aware bar_end.")
        if stamp in by_end:
            return _failure("DUPLICATE_OBSERVATION", "Source candles repeat a bar_end.")
        by_end[stamp] = candle
    seen: set[str] = set()
    eligible: list[dict] = []
    exclusions: dict[str, int] = {}
    zero_with_future = 0
    future_rows = 0

    def exclude(reason: str) -> None:
        exclusions[reason] = exclusions.get(reason, 0) + 1

    for row in rows:
        try:
            as_of = _stamp(row["as_of"])
        except (KeyError, TypeError, ValueError):
            exclude("NAIVE_TIMESTAMP")
            continue
        key = f"{row.get('instrument_id')}|{as_of}"
        if as_of in seen:
            return _failure("DUPLICATE_OBSERVATION", "Feature rows repeat an as_of timestamp.")
        seen.add(as_of)
        candle = by_end.get(as_of)
        if candle is None:
            exclude("NO_SOURCE_CANDLE")
            continue
        if not _complete(candle):
            exclude("INCOMPLETE_CANDLE")
            continue
        try:
            if _parse(candle["bar_start"]) != _parse(as_of) - INTERVAL:
                exclude("MALFORMED_CANDLE")
                continue
            label_at = (_parse(as_of) + INTERVAL).isoformat()
        except (KeyError, TypeError, ValueError):
            exclude("MALFORMED_CANDLE")
            continue
        future = by_end.get(label_at)
        if future is None:
            exclude("NO_FUTURE_CANDLE")
            continue
        if not _complete(future):
            exclude("INCOMPLETE_FUTURE_CANDLE")
            continue
        try:
            if _parse(future["bar_start"]) != _parse(as_of):
                exclude("MALFORMED_FUTURE_CANDLE")
                continue
            if _parse(future["bar_end"]) <= _parse(as_of):
                exclude("LABEL_NOT_AFTER_FEATURES")
                continue
            if not math.isfinite(candle["close"]) or not math.isfinite(future["close"]) or candle["close"] == 0:
                exclude("INVALID_PRICE")
                continue
        except (KeyError, TypeError, ValueError):
            exclude("MALFORMED_FUTURE_CANDLE")
            continue
        future_rows += 1
        future_return = future["close"] / candle["close"] - 1
        if not math.isfinite(future_return):
            exclude("INVALID_PRICE")
            continue
        if future_return == 0:
            zero_with_future += 1
        feature_reason = _reason_for_features(row.get("values") or {})
        if feature_reason is not None:
            exclude(feature_reason)
            continue
        direction = 1 if future_return > 0 else 0
        eligible.append(
            {
                "key": key,
                "instrument_id": row["instrument_id"],
                "as_of": as_of,
                "label_available_at": label_at,
                "future_return": future_return,
                "direction": direction,
                "origin": row["origin"],
                "features": {name: row["values"][name]["value"] for name in MODEL_FEATURES},
            }
        )

    origin = artifact.get("origin")
    synthetic = origin == "SYNTHETIC"
    share = None if future_rows == 0 else zero_with_future / future_rows
    report = {
        "ok": True,
        "code": None,
        "target_id": TARGET_ID,
        "target_version": TARGET_VERSION,
        "instrument": artifact.get("instrument_id"),
        "interval": "M15",
        "horizon": HORIZON,
        "label_formula": LABEL_FORMULA,
        "label_availability": LABEL_AVAILABILITY,
        "source_dataset_id": artifact.get("dataset_id"),
        "created_at": artifact.get("created_at"),
        "origin": origin,
        "source_id": artifact.get("source_id"),
        "synthetic": synthetic,
        "documented_sample": origin == "DOCUMENTED_SAMPLE",
        "real_market_eligible": origin == "PROVIDER",
        "real_market_data_verified": False,
        "performance_claim_allowed": False,
        "start": artifact.get("start"),
        "end": artifact.get("end"),
        "eligible_observations": len(eligible),
        "excluded_observations": sum(exclusions.values()),
        "exclusion_reasons": exclusions,
        "rows_with_future_candle": future_rows,
        "zero_return_count": zero_with_future,
        "zero_return_share": share,
        "rows": eligible,
        "lineage": artifact.get("lineage"),
        "forecast_ready": False,
    }
    return report


def _complete(candle: dict) -> bool:
    """Same completion rule as M1: retrieved_at is at or after bar_end."""
    try:
        return _parse(candle["retrieved_at"]) >= _parse(candle["bar_end"])
    except (KeyError, TypeError, ValueError):
        return False


def _failure(code: str, message: str) -> dict:
    return {"ok": False, "code": code, "message": message, "forecast_ready": False, "rows": []}
