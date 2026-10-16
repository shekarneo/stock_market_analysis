from __future__ import annotations

from datetime import datetime

from app.config.schemas import AppConfig
from app.market.fixtures import fixture_calendar
from app.market.providers import INDEXES, GrowwReadProvider, SyntheticProvider
from app.market.quality import validate_quote, validate_series
from app.market.schemas import (
    IST,
    ContextObservation,
    QualityStatus,
    Readiness,
    RetrievalFailure,
    require_aware,
)

ALLOWED_PROVIDERS = {"synthetic", "groww"}


def assert_provider_name(provider: str) -> None:
    if provider not in ALLOWED_PROVIDERS or "://" in provider or provider.startswith("."):
        raise ValueError("provider must be a configured name, not a URL")


def build_snapshot(config: AppConfig, *, now: datetime, provider_name: str = "synthetic") -> dict:
    assert_provider_name(provider_name)
    now = require_aware(now, "now")
    provider = SyntheticProvider() if provider_name == "synthetic" else GrowwReadProvider()
    quotes = []
    failures = []
    for underlying in INDEXES:
        result = provider.get_quote(underlying, now=now)
        if isinstance(result, RetrievalFailure):
            failures.append(result.model_dump(mode="json"))
        else:
            report = validate_quote(
                result,
                now=now,
                warn_after_seconds=config.freshness.index_warn_seconds,
                block_after_seconds=config.risk.quote_max_age_seconds,
            )
            payload = result.model_dump(mode="json")
            payload["quality"] = report.status.value
            payload["quality_ok"] = report.ok
            payload["issues"] = [issue.model_dump(mode="json") for issue in report.issues]
            quotes.append(payload)
    context = provider.get_context(now=now)
    standing = set(config.context_book.standing)
    context_rows = [row for row in context if row.code in standing]
    readiness = assess_readiness(quotes, context_rows, failures)
    return {
        "ok": readiness.data_ready,
        "schema_version": "1.0",
        "provider": provider.provider_id,
        "origin": "SYNTHETIC" if provider_name == "synthetic" else None,
        "live_market_data": False,
        "orders_enabled": False,
        "as_of": now.astimezone(IST).isoformat(),
        "calendar": fixture_calendar().assess(now).model_dump(mode="json"),
        "quotes": quotes,
        "context": [row.model_dump(mode="json") for row in context_rows],
        "failures": failures,
        "readiness": readiness.model_dump(mode="json"),
    }


def build_history(underlying: str, *, retrieved_at: datetime, provider_name: str = "synthetic") -> dict:
    assert_provider_name(provider_name)
    if "://" in underlying or not underlying.isidentifier() or not underlying.isupper():
        return RetrievalFailure(code="UNKNOWN_INSTRUMENT", message="Invalid instrument identifier.").model_dump(mode="json")
    provider = SyntheticProvider() if provider_name == "synthetic" else GrowwReadProvider()
    result = provider.get_candles(underlying, retrieved_at=require_aware(retrieved_at, "retrieved_at"))
    if isinstance(result, RetrievalFailure):
        return result.model_dump(mode="json")
    report = validate_series(result, fixture_calendar())
    return {
        "ok": report.ok,
        "schema_version": "1.0",
        "provider": provider.provider_id,
        "origin": result[0].origin.value if result else None,
        "live_market_data": False,
        "instrument_id": underlying,
        "quality": report.status.value,
        "issues": [issue.model_dump(mode="json") for issue in report.issues],
        "candles": [candle.model_dump(mode="json") for candle in result] if report.ok else [],
        "readiness": Readiness(
            data_ready=report.ok,
            proposal_blocked=not report.ok,
            reasons=["FORECASTING_NOT_IMPLEMENTED"] + [issue.code for issue in report.issues if not report.ok],
        ).model_dump(mode="json"),
    }


def assess_readiness(
    quotes: list[dict],
    context: list[ContextObservation],
    failures: list[dict],
) -> Readiness:
    reasons: list[str] = ["FORECASTING_NOT_IMPLEMENTED"]
    by_underlying = {row["underlying"]: row for row in quotes}
    data_ready = not failures
    for underlying in INDEXES:
        row = by_underlying.get(underlying)
        if row is None:
            data_ready = False
            reasons.append(f"MISSING_{underlying}")
            continue
        if row["quality"] == QualityStatus.FAIL.value or not row["quality_ok"]:
            data_ready = False
            reasons.append(f"QUALITY_FAIL_{underlying}")
    crude = [row for row in context if row.code in {"BRENT", "MCX_CRUDE", "WTI"}]
    if not crude or any(row.value is None for row in crude):
        reasons.append("CRUDE_UNAVAILABLE")
    stale = any(any(issue["code"] == "STALE_QUOTE" for issue in row["issues"]) for row in quotes)
    if stale:
        reasons.append("STALE_INDEX_LTP")
    return Readiness(data_ready=data_ready, proposal_blocked=(not data_ready) or stale, reasons=reasons)
