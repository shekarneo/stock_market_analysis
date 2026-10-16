"""Trailing OHLC features for one instrument.

The row cutoff is the observation candle's bar_end. Slices end at that candle.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.features.definitions import (
    AVAILABILITY_CONVENTION,
    DATASET_SCHEMA_VERSION,
    FEATURE_SET_VERSION,
    FEATURE_SPECS,
    INTERVAL_MINUTES,
    MISSING_DATA_POLICY,
    PIPELINE_VERSION,
    POINT_IN_TIME_LIMITATION,
)
from app.market.calendar import CalendarState, ExchangeCalendar
from app.market.fixtures import CLOSED_TEST_DAY, FIXTURE_DAY
from app.market.quality import validate_series
from app.market.schemas import Candle, DataOrigin, require_aware

INTERVAL = timedelta(minutes=INTERVAL_MINUTES)
FeatureStatus = Literal[
    "VALID",
    "WARMUP",
    "INVALID_INPUT",
    "MISSING_OBSERVATION",
    "CALENDAR_UNKNOWN",
    "INCOMPLETE_CANDLE",
]
_STATUS_RANK = {
    "VALID": 0,
    "WARMUP": 1,
    "CALENDAR_UNKNOWN": 2,
    "MISSING_OBSERVATION": 3,
    "INCOMPLETE_CANDLE": 4,
    "INVALID_INPUT": 5,
}


class FeatureValue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: float | None
    status: FeatureStatus


class FeatureRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instrument_id: str
    underlying: str
    as_of: datetime
    origin: DataOrigin
    source_id: str
    calendar_state: str
    values: dict[str, FeatureValue]


class DatasetBuildResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    code: str | None = None
    message: str | None = None
    partial: bool = False
    forecast_ready: Literal[False] = False
    rejected_row_count: int = 0
    issues: list[dict] = []
    artifact: dict | None = None


def candle_is_complete(candle: Candle) -> bool:
    """Completion is bar_end, and only once the candle has been retrieved at or after that time."""
    return candle.retrieved_at >= candle.bar_end


def content_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def seal(body: dict) -> dict:
    """Checksum the canonical JSON so a later read hashes the same bytes."""
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    artifact = json.loads(encoded)
    artifact["dataset_id"] = digest
    artifact["checksum"] = digest
    return artifact


def _worse(left: FeatureStatus, right: FeatureStatus) -> FeatureStatus:
    return left if _STATUS_RANK[left] >= _STATUS_RANK[right] else right


def _gap(candles: list[Candle], index: int, bars_back: int) -> FeatureStatus | None:
    if bars_back <= 0:
        return None
    if index - bars_back < 0:
        return "WARMUP"
    expected = candles[index].bar_end - (INTERVAL * bars_back)
    if candles[index - bars_back].bar_end != expected:
        return "MISSING_OBSERVATION"
    return None


def _number(value: float) -> FeatureValue:
    if not math.isfinite(value):
        return FeatureValue(value=None, status="INVALID_INPUT")
    return FeatureValue(value=value, status="VALID")


def _close_at(candles: list[Candle], index: int, bars_back: int) -> tuple[float | None, FeatureStatus]:
    state = _gap(candles, index, bars_back)
    if state is not None:
        return None, state
    return candles[index - bars_back].close, "VALID"


def _true_range(candle: Candle, previous_close: float) -> float:
    return max(
        candle.high - candle.low,
        abs(candle.high - previous_close),
        abs(candle.low - previous_close),
    )


def compute_feature_row(candles: list[Candle], index: int, calendar: ExchangeCalendar) -> FeatureRow:
    candle = candles[index]
    if not candle_is_complete(candle):
        blank = {name: FeatureValue(value=None, status="INCOMPLETE_CANDLE") for name in FEATURE_SPECS}
        return FeatureRow(
            instrument_id=candle.instrument_id,
            underlying=candle.underlying,
            as_of=candle.bar_end,
            origin=candle.origin,
            source_id=candle.source_id,
            calendar_state="INCOMPLETE",
            values=blank,
        )

    values: dict[str, FeatureValue] = {}
    previous, previous_state = _close_at(candles, index, 1)
    if previous_state != "VALID" or previous is None:
        values["ret_1"] = FeatureValue(value=None, status=previous_state)
        values["hl_range_vs_prev_close"] = FeatureValue(value=None, status=previous_state)
    else:
        values["ret_1"] = _number(candle.close / previous - 1)
        values["hl_range_vs_prev_close"] = _number((candle.high - candle.low) / previous)

    far, far_state = _close_at(candles, index, 3)
    if far_state != "VALID" or far is None:
        values["ret_3"] = FeatureValue(value=None, status=far_state)
    else:
        values["ret_3"] = _number(candle.close / far - 1)

    values["sma_3"] = _trailing_mean(candles, index, 3)
    values["sma_5"] = _trailing_mean(candles, index, 5)
    if values["sma_5"].status != "VALID" or values["sma_5"].value in (None, 0):
        status = values["sma_5"].status if values["sma_5"].value != 0 else "INVALID_INPUT"
        values["close_vs_sma_5"] = FeatureValue(value=None, status=status)
    else:
        values["close_vs_sma_5"] = _number(candle.close / values["sma_5"].value - 1)

    spread_status = _worse(values["sma_3"].status, values["sma_5"].status)
    if spread_status != "VALID" or values["sma_3"].value is None or values["sma_5"].value is None:
        values["sma_3_minus_sma_5"] = FeatureValue(value=None, status=spread_status)
    else:
        values["sma_3_minus_sma_5"] = _number(values["sma_3"].value - values["sma_5"].value)

    values["ret_std_5"] = _return_std(candles, index)
    values["atr_3"] = _atr(candles, index)
    if candle.open <= 0 or not math.isfinite(candle.open):
        values["oc_return"] = FeatureValue(value=None, status="INVALID_INPUT")
    else:
        values["oc_return"] = _number(candle.close / candle.open - 1)
    span = candle.high - candle.low
    if span == 0:
        values["close_position"] = FeatureValue(value=None, status="INVALID_INPUT")
    elif span < 0 or not math.isfinite(span):
        values["close_position"] = FeatureValue(value=None, status="INVALID_INPUT")
    else:
        values["close_position"] = _number((candle.close - candle.low) / span)

    assessment = calendar.assess(candle.bar_start)
    if assessment.state is CalendarState.LISTED_SESSION:
        values["session_confirmed"] = FeatureValue(value=1.0, status="VALID")
        calendar_state = assessment.state.value
    elif assessment.state is CalendarState.UNKNOWN:
        values["session_confirmed"] = FeatureValue(value=None, status="CALENDAR_UNKNOWN")
        calendar_state = assessment.state.value
    else:
        values["session_confirmed"] = FeatureValue(value=None, status="INVALID_INPUT")
        calendar_state = assessment.state.value

    return FeatureRow(
        instrument_id=candle.instrument_id,
        underlying=candle.underlying,
        as_of=candle.bar_end,
        origin=candle.origin,
        source_id=candle.source_id,
        calendar_state=calendar_state,
        values=values,
    )


def _trailing_mean(candles: list[Candle], index: int, window: int) -> FeatureValue:
    state = _gap(candles, index, window - 1)
    if state is not None:
        return FeatureValue(value=None, status=state)
    closes = [candles[pos].close for pos in range(index - window + 1, index + 1)]
    return _number(sum(closes) / window)


def _return_std(candles: list[Candle], index: int) -> FeatureValue:
    returns: list[float] = []
    status: FeatureStatus = "VALID"
    for offset in range(4, -1, -1):
        position = index - offset
        if position < 1:
            return FeatureValue(value=None, status="WARMUP")
        state = _gap(candles, position, 1)
        if state is not None:
            status = _worse(status, state)
            continue
        previous = candles[position - 1].close
        returns.append(candles[position].close / previous - 1)
    if status != "VALID":
        return FeatureValue(value=None, status=status)
    if len(returns) < 5:
        return FeatureValue(value=None, status="MISSING_OBSERVATION")
    return _number(statistics.stdev(returns))


def _atr(candles: list[Candle], index: int) -> FeatureValue:
    ranges: list[float] = []
    status: FeatureStatus = "VALID"
    for offset in range(2, -1, -1):
        position = index - offset
        if position < 1:
            return FeatureValue(value=None, status="WARMUP")
        state = _gap(candles, position, 1)
        if state is not None:
            status = _worse(status, state)
            continue
        ranges.append(_true_range(candles[position], candles[position - 1].close))
    if status != "VALID":
        return FeatureValue(value=None, status=status)
    if len(ranges) < 3:
        return FeatureValue(value=None, status="MISSING_OBSERVATION")
    return _number(sum(ranges) / 3)


def select_available(candles: list[Candle], as_of: datetime | None) -> list[Candle]:
    if as_of is None:
        return list(candles)
    cutoff = require_aware(as_of, "as_of")
    return [candle for candle in candles if candle.bar_end <= cutoff]


def _source_payload(candles: list[Candle]) -> list[dict]:
    return [candle.model_dump(mode="json") for candle in candles]


def _quarantine_input(candles: object) -> tuple[str, str] | None:
    from app.market.provenance import quarantine_candle_block, quarantine_training_block

    if isinstance(candles, dict):
        return quarantine_training_block(candles)
    if isinstance(candles, list):
        return quarantine_candle_block(candles)
    return None


def _failure(
    code: str,
    message: str,
    issues: list[dict] | None = None,
    *,
    rejected_row_count: int = 0,
) -> DatasetBuildResult:
    return DatasetBuildResult(
        ok=False,
        code=code,
        message=message,
        partial=False,
        rejected_row_count=rejected_row_count,
        issues=issues or [],
        artifact=None,
    )


def _calendar_label(calendar: ExchangeCalendar) -> str:
    if calendar.listed_sessions == {FIXTURE_DAY} and calendar.closed_dates == {CLOSED_TEST_DAY}:
        return "fixture-m1"
    return "custom-non-authoritative"


def build_dataset(
    candles: list[Candle],
    calendar: ExchangeCalendar,
    *,
    as_of: datetime | None = None,
    feature_set_version: str = FEATURE_SET_VERSION,
    history_dataset_id: str | None = None,
    history_checksum: str | None = None,
) -> DatasetBuildResult:
    blocked = _quarantine_input(candles)
    if blocked is not None:
        return _failure(blocked[0], blocked[1])
    if feature_set_version != FEATURE_SET_VERSION:
        return _failure("UNKNOWN_FEATURE_SET", f"Feature set {feature_set_version} is not implemented.")
    if not candles:
        return _failure("NO_CANDLES", "No candles were supplied.")
    origins = {candle.origin for candle in candles}
    if len(origins) != 1:
        return _failure("MIXED_ORIGIN", "Candles with different origins cannot be combined.")
    source_ids = {candle.source_id for candle in candles}
    if len(source_ids) != 1:
        return _failure("MIXED_SOURCE", "Candles with different source ids cannot be combined.")
    instruments = {candle.instrument_id for candle in candles}
    if len(instruments) != 1:
        return _failure("MIXED_INSTRUMENT", "A dataset contains one instrument.")
    intervals = {candle.interval for candle in candles}
    if intervals != {"M15"}:
        return _failure("UNSUPPORTED_INTERVAL", "Only M15 candles are accepted.")

    selected = select_available(candles, as_of)
    if not selected:
        return _failure("NO_CANDLES", "No candle is complete at the requested as_of timestamp.", rejected_row_count=len(candles))
    report = validate_series(selected, calendar)
    issue_payload = [issue.model_dump(mode="json") for issue in report.issues]
    if not report.ok:
        fatal = next(issue for issue in report.issues if issue.severity.value == "FATAL")
        return _failure(fatal.code, fatal.message, issue_payload, rejected_row_count=len(selected))

    rows = [compute_feature_row(selected, index, calendar) for index in range(len(selected))]
    origin = selected[0].origin
    synthetic = origin is DataOrigin.SYNTHETIC
    partial = any(item.status != "VALID" for row in rows for item in row.values.values())
    calendar_states = {row.calendar_state for row in rows}
    reasons = ["FORECASTING_NOT_IMPLEMENTED", "CALENDAR_NOT_AUTHORITATIVE"]
    if synthetic:
        reasons.append("SYNTHETIC_INPUT")
    elif origin is DataOrigin.DOCUMENTED_SAMPLE:
        reasons.append("DOCUMENTED_SAMPLE_INPUT")
    if partial:
        reasons.append("PARTIAL_FEATURES")
    if "UNKNOWN" in calendar_states:
        reasons.append("CALENDAR_UNKNOWN")
    source_rows = _source_payload(selected)
    source_digest = content_hash({"candles": source_rows})
    from app.market.provenance import make_lineage

    lineage = make_lineage(
        origin=origin.value,
        source_id=selected[0].source_id,
        source_row_sha256=source_digest,
        parent_dataset_id=history_dataset_id,
        parent_checksum=history_checksum,
    )
    counts: dict[str, int] = {}
    for row in rows:
        for item in row.values.values():
            counts[item.status] = counts.get(item.status, 0) + 1
    body = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "feature_set_version": FEATURE_SET_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "instrument_id": selected[0].instrument_id,
        "underlying": selected[0].underlying,
        "interval": "M15",
        "origin": origin.value,
        "source_id": selected[0].source_id,
        "source_row_sha256": source_digest,
        "lineage": lineage,
        "source_candles": source_rows,
        "start": selected[0].bar_start.isoformat(),
        "end": selected[-1].bar_end.isoformat(),
        "created_at": max(candle.retrieved_at for candle in selected).isoformat(),
        "feature_config": FEATURE_SPECS,
        "lookback": {name: spec["lookback_bars"] for name, spec in FEATURE_SPECS.items()},
        "missing_data_policy": MISSING_DATA_POLICY,
        "availability_convention": AVAILABILITY_CONVENTION,
        "point_in_time_limitation": POINT_IN_TIME_LIMITATION,
        "calendar_version": _calendar_label(calendar),
        "calendar_authoritative": False,
        "calendar_listed_sessions": sorted(day.isoformat() for day in calendar.listed_sessions),
        "calendar_closed_dates": sorted(day.isoformat() for day in calendar.closed_dates),
        "calendar_limitation": calendar.limitation,
        "validation": {"status": report.status.value, "ok": report.ok, "issues": issue_payload},
        "feature_quality": {"partial": partial, "status_counts": counts, "forecast_ready": False},
        "source_row_count": len(selected),
        "output_row_count": len(rows),
        "rejected_row_count": 0,
        "excluded_after_cutoff": len(candles) - len(selected),
        "synthetic": synthetic,
        "live_market_data": False,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "readiness_reasons": reasons,
        "untouched_test_start": None,
        "untouched_test_end": None,
        "untouched_test_note": "No model is fit in M2. Untouched test dates are not selected.",
        "rows": [row.model_dump(mode="json") for row in rows],
    }
    if history_dataset_id is not None:
        body["history_dataset_id"] = history_dataset_id
        body["history_checksum"] = history_checksum
    artifact = seal(body)
    return DatasetBuildResult(ok=True, partial=partial, issues=issue_payload, artifact=artifact)
