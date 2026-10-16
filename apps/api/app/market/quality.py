from __future__ import annotations

import math
from datetime import datetime, timedelta

from app.market.calendar import CalendarState, ExchangeCalendar
from app.market.schemas import (
    Candle,
    IssueSeverity,
    QualityIssue,
    QualityReport,
    QualityStatus,
    Quote,
)

from app.instruments import INDEX_UNDERLYINGS

INTERVAL = timedelta(minutes=15)


def _finite(value: float | None) -> bool:
    return value is not None and isinstance(value, (int, float)) and math.isfinite(value)


def _report(issues: list[QualityIssue]) -> QualityReport:
    if any(issue.severity is IssueSeverity.FATAL for issue in issues):
        status = QualityStatus.FAIL
        ok = False
    elif issues:
        status = QualityStatus.WARN
        ok = True
    else:
        status = QualityStatus.PASS
        ok = True
    return QualityReport(status=status, ok=ok, issues=issues)


def validate_candle(candle: Candle) -> QualityReport:
    issues: list[QualityIssue] = []
    prices = {
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
    }
    for name, value in prices.items():
        if not _finite(value) or value <= 0:
            issues.append(
                QualityIssue(
                    code="INVALID_PRICE",
                    severity=IssueSeverity.FATAL,
                    message=f"{name} must be a finite price above zero",
                    instrument_id=candle.instrument_id,
                )
            )
    if candle.volume is not None and (not _finite(candle.volume) or candle.volume < 0):
        issues.append(
            QualityIssue(
                code="INVALID_VOLUME",
                severity=IssueSeverity.FATAL,
                message="volume must be absent or a finite number of zero or more",
                instrument_id=candle.instrument_id,
            )
        )
    if all(_finite(value) and value > 0 for value in prices.values()):
        if candle.high < max(candle.open, candle.close, candle.low) or candle.low > min(
            candle.open, candle.close, candle.high
        ):
            issues.append(
                QualityIssue(
                    code="INVALID_OHLC",
                    severity=IssueSeverity.FATAL,
                    message="high and low do not contain the open and close",
                    instrument_id=candle.instrument_id,
                )
            )
    if candle.bar_end <= candle.bar_start:
        issues.append(
            QualityIssue(
                code="INVALID_INTERVAL",
                severity=IssueSeverity.FATAL,
                message="bar_end must be after bar_start",
                instrument_id=candle.instrument_id,
            )
        )
    elif candle.bar_end - candle.bar_start != INTERVAL:
        issues.append(
            QualityIssue(
                code="UNEXPECTED_INTERVAL",
                severity=IssueSeverity.FATAL,
                message="M15 bars must cover 15 minutes",
                instrument_id=candle.instrument_id,
            )
        )
    if candle.retrieved_at < candle.bar_end:
        issues.append(
            QualityIssue(
                code="RETRIEVAL_BEFORE_EVENT",
                severity=IssueSeverity.FATAL,
                message="retrieved_at cannot be earlier than the bar end",
                instrument_id=candle.instrument_id,
            )
        )
    return _report(issues)


def validate_series(candles: list[Candle], calendar: ExchangeCalendar) -> QualityReport:
    issues: list[QualityIssue] = []
    for candle in candles:
        issues.extend(validate_candle(candle).issues)
    ends = [candle.bar_end for candle in candles]
    if ends != sorted(ends):
        issues.append(
            QualityIssue(
                code="OUT_OF_ORDER",
                severity=IssueSeverity.FATAL,
                message="candles are not in bar_end order",
                instrument_id=candles[0].instrument_id if candles else None,
            )
        )
    ordered = sorted(candles, key=lambda item: item.bar_end)
    seen: set[datetime] = set()
    for candle in ordered:
        if candle.bar_end in seen:
            issues.append(
                QualityIssue(
                    code="DUPLICATE_TIMESTAMP",
                    severity=IssueSeverity.FATAL,
                    message="duplicate bar_end",
                    instrument_id=candle.instrument_id,
                )
            )
        seen.add(candle.bar_end)
        assessment = calendar.assess(candle.bar_start)
        if assessment.state is CalendarState.NOT_A_SESSION:
            issues.append(
                QualityIssue(
                    code="NOT_A_SESSION",
                    severity=IssueSeverity.FATAL,
                    message=assessment.limitation,
                    instrument_id=candle.instrument_id,
                )
            )
        elif assessment.state is CalendarState.UNKNOWN:
            issues.append(
                QualityIssue(
                    code="CALENDAR_UNKNOWN",
                    severity=IssueSeverity.WARNING,
                    message=assessment.limitation,
                    instrument_id=candle.instrument_id,
                )
            )
        elif not calendar.in_regular_window(candle.bar_start):
            issues.append(
                QualityIssue(
                    code="OUTSIDE_SESSION_WINDOW",
                    severity=IssueSeverity.FATAL,
                    message="bar starts outside the configured 09:15-15:30 IST window",
                    instrument_id=candle.instrument_id,
                )
            )
    if ordered and not any(issue.code == "DUPLICATE_TIMESTAMP" for issue in issues):
        cursor = ordered[0].bar_end
        last = ordered[-1].bar_end
        present = {item.bar_end for item in ordered}
        while cursor < last:
            cursor = cursor + INTERVAL
            if cursor not in present and cursor <= last:
                issues.append(
                    QualityIssue(
                        code="MISSING_CANDLE",
                        severity=IssueSeverity.FATAL,
                        message=f"missing bar ending {cursor.isoformat()}",
                        instrument_id=ordered[0].instrument_id,
                    )
                )
    return _report(issues)


def validate_quote(quote: Quote, *, now: datetime, warn_after_seconds: int, block_after_seconds: int) -> QualityReport:
    issues: list[QualityIssue] = []
    if quote.last_price is None:
        issues.append(
            QualityIssue(
                code="MISSING_PRICE",
                severity=IssueSeverity.FATAL,
                message=quote.unavailable_reason or "last price is absent",
                instrument_id=quote.instrument_id,
            )
        )
    elif not _finite(quote.last_price) or quote.last_price <= 0:
        issues.append(
            QualityIssue(
                code="INVALID_PRICE",
                severity=IssueSeverity.FATAL,
                message="last price must be a finite number above zero",
                instrument_id=quote.instrument_id,
            )
        )
    for name, value in ("open", quote.open), ("high", quote.high), ("low", quote.low), ("close", quote.close):
        if value is not None and (not _finite(value) or value <= 0):
            issues.append(
                QualityIssue(
                    code="INVALID_PRICE",
                    severity=IssueSeverity.FATAL,
                    message=f"{name} must be a finite price above zero",
                    instrument_id=quote.instrument_id,
                )
            )
    if quote.retrieved_at < quote.event_timestamp:
        issues.append(
            QualityIssue(
                code="RETRIEVAL_BEFORE_EVENT",
                severity=IssueSeverity.FATAL,
                message="retrieved_at cannot be earlier than the event timestamp",
                instrument_id=quote.instrument_id,
            )
        )
    age = (now - quote.event_timestamp).total_seconds()
    if age > block_after_seconds:
        issues.append(
            QualityIssue(
                code="STALE_QUOTE",
                severity=IssueSeverity.WARNING,
                message="event timestamp is older than the proposal block age",
                instrument_id=quote.instrument_id,
            )
        )
    elif age > warn_after_seconds:
        issues.append(
            QualityIssue(
                code="STALE_QUOTE",
                severity=IssueSeverity.WARNING,
                message="event timestamp is older than the warn age",
                instrument_id=quote.instrument_id,
            )
        )
    return _report(issues)
