from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.config.loader import load_defaults
from app.market.fixtures import CLOSED_TEST_DAY, fixture_calendar, quiet_day_candles
from app.market.providers import GrowwReadProvider, SyntheticProvider
from app.market.quality import validate_candle, validate_quote, validate_series
from app.market.schemas import IST, Candle, DataOrigin, MarketSession
from app.market.service import build_history, build_snapshot
from app.settings import get_settings
from tests.conftest import login


def _config():
    return load_defaults(get_settings().defaults_path)


def _fresh_now() -> datetime:
    return datetime(2026, 1, 5, 10, 15, tzinfo=IST)


def test_valid_synthetic_candles_are_labelled_and_normalized():
    candles = quiet_day_candles("NIFTY", retrieved_at=_fresh_now())
    report = validate_series(candles, fixture_calendar())
    assert report.ok is True
    assert report.status.value == "PASS"
    assert {candle.origin for candle in candles} == {DataOrigin.SYNTHETIC}
    assert all(candle.volume is None for candle in candles)
    assert all(candle.bar_end.tzinfo == IST for candle in candles)


def test_utc_input_is_normalized_to_kolkata():
    start = datetime(2026, 1, 5, 3, 45, tzinfo=timezone.utc)
    raw = quiet_day_candles("NIFTY", retrieved_at=_fresh_now())[0].model_dump()
    raw["bar_start"] = start
    raw["bar_end"] = start + timedelta(minutes=15)
    moved = Candle.model_validate(raw)
    assert moved.bar_start.hour == 9
    assert moved.bar_start.utcoffset() == IST.utcoffset(moved.bar_start)
    report = validate_candle(moved)
    assert report.ok is True


def test_naive_timestamp_is_rejected():
    raw = quiet_day_candles("NIFTY", retrieved_at=_fresh_now())[0].model_dump()
    raw["bar_start"] = datetime(2026, 1, 5, 9, 15)
    with pytest.raises(ValidationError):
        Candle.model_validate(raw)


def test_invalid_ohlc_is_fatal_and_not_repaired():
    candle = quiet_day_candles("NIFTY", retrieved_at=_fresh_now())[0].model_copy(update={"high": 1})
    report = validate_candle(candle)
    assert report.ok is False
    assert report.issues[0].code == "INVALID_OHLC"
    assert candle.high == 1


def test_missing_documented_quote_field():
    provider = GrowwReadProvider(transport=type("T", (), {"get_quote": lambda self, symbol: {"ohlc": {}}})())
    result = provider.get_quote("NIFTY", now=_fresh_now())
    assert result.ok is False
    assert result.code == "MISSING_FIELD"


def test_duplicate_and_out_of_order_and_missing_candles():
    candles = quiet_day_candles("SENSEX", retrieved_at=_fresh_now())
    duplicate = validate_series(candles + [candles[0]], fixture_calendar())
    assert duplicate.ok is False
    assert any(issue.code == "DUPLICATE_TIMESTAMP" for issue in duplicate.issues)
    reversed_report = validate_series(list(reversed(candles)), fixture_calendar())
    assert any(issue.code == "OUT_OF_ORDER" for issue in reversed_report.issues)
    gap = [candles[0], candles[2], candles[3]]
    missing = validate_series(gap, fixture_calendar())
    assert missing.ok is False
    assert any(issue.code == "MISSING_CANDLE" for issue in missing.issues)
    assert len(gap) == 3


def test_stale_quote_blocks_proposal_without_rewriting_the_timestamp():
    quote = SyntheticProvider().get_quote("NIFTY", now=_fresh_now())
    later = quote.event_timestamp + timedelta(seconds=30)
    report = validate_quote(quote, now=later, warn_after_seconds=60, block_after_seconds=15)
    assert report.ok is True
    assert report.status.value == "WARN"
    assert report.issues[0].code == "STALE_QUOTE"
    snapshot = build_snapshot(_config(), now=later)
    assert snapshot["readiness"]["proposal_blocked"] is True
    assert "STALE_INDEX_LTP" in snapshot["readiness"]["reasons"]
    assert snapshot["quotes"][0]["event_timestamp"].startswith("2026-01-05")


def test_closed_fixture_date_is_not_treated_as_a_session():
    candles = quiet_day_candles("SENSEX", retrieved_at=_fresh_now())
    shifted = []
    for candle in candles:
        delta = candle.bar_start.date() - CLOSED_TEST_DAY
        # Move the listed Monday fixture onto the explicit closed test date.
        start = candle.bar_start - timedelta(days=1)
        shifted.append(
            candle.model_copy(
                update={
                    "bar_start": start,
                    "bar_end": start + timedelta(minutes=15),
                }
            )
        )
    assert shifted[0].bar_start.date() == CLOSED_TEST_DAY
    report = validate_series(shifted, fixture_calendar())
    assert any(issue.code == "NOT_A_SESSION" for issue in report.issues)
    assert delta.days == 1


def test_unknown_calendar_day_is_a_warning_not_a_filled_session():
    candles = quiet_day_candles("NIFTY", retrieved_at=datetime(2026, 1, 6, 10, 15, tzinfo=IST))
    moved = [
        candle.model_copy(
            update={
                "bar_start": candle.bar_start + timedelta(days=1),
                "bar_end": candle.bar_end + timedelta(days=1),
            }
        )
        for candle in candles
    ]
    report = validate_series(moved, fixture_calendar())
    assert report.ok is True
    assert any(issue.code == "CALENDAR_UNKNOWN" for issue in report.issues)


def test_invalid_instrument_and_provider_url_are_rejected():
    history = build_history("http://example.com", retrieved_at=_fresh_now())
    assert history["ok"] is False
    assert history["code"] == "UNKNOWN_INSTRUMENT"
    with pytest.raises(ValueError):
        build_snapshot(_config(), now=_fresh_now(), provider_name="https://evil.example/quote")


def test_groww_timeout_and_unverified_history_create_no_candles():
    class TimeoutTransport:
        def get_quote(self, trading_symbol: str) -> dict:
            raise TimeoutError("timed out")

    provider = GrowwReadProvider(transport=TimeoutTransport())
    timed_out = provider.get_quote("NIFTY", now=_fresh_now())
    assert timed_out.ok is False
    assert timed_out.code == "PROVIDER_TIMEOUT"
    history = provider.get_candles("NIFTY", retrieved_at=_fresh_now())
    assert history.ok is False
    assert history.code == "CANDLE_BOUNDARY_UNVERIFIED"
    assert provider.network_calls == 1


def test_documented_sample_is_not_labelled_live():
    class Sample:
        def get_quote(self, trading_symbol: str) -> dict:
            return {
                "last_price": 100.0,
                "last_trade_time": int(_fresh_now().timestamp() * 1000),
                "volume": 5,
                "ohlc": {"open": 99, "high": 101, "low": 98, "close": 100},
            }

    quote = GrowwReadProvider(transport=Sample()).get_quote("NIFTY", now=_fresh_now())
    assert quote.origin is DataOrigin.DOCUMENTED_SAMPLE
    assert quote.session is MarketSession.UNKNOWN
    sensex = GrowwReadProvider(transport=Sample()).get_quote("SENSEX", now=_fresh_now())
    assert sensex.code == "UNVERIFIED_SYMBOL"


def test_quiet_day_snapshot_keeps_empty_crude_and_blocks_forecasting():
    snapshot = build_snapshot(_config(), now=_fresh_now())
    assert snapshot["live_market_data"] is False
    assert snapshot["origin"] == "SYNTHETIC"
    assert [row["underlying"] for row in snapshot["quotes"]] == ["NIFTY", "SENSEX"]
    crude = {row["code"]: row["value"] for row in snapshot["context"] if row["code"] in {"BRENT", "MCX_CRUDE", "WTI"}}
    assert crude == {"BRENT": None, "MCX_CRUDE": None, "WTI": None}
    assert "CRUDE_UNAVAILABLE" in snapshot["readiness"]["reasons"]
    assert snapshot["readiness"]["forecast_ready"] is False
    assert snapshot["readiness"]["data_ready"] is True
    assert snapshot["orders_enabled"] is False


def test_history_api_requires_login_and_labels_synthetic_data(client):
    denied = client.get("/api/market/history?instrument=NIFTY")
    assert denied.status_code == 401
    login(client)
    response = client.get("/api/market/history?instrument=NIFTY")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["origin"] == "SYNTHETIC"
    assert body["live_market_data"] is False
    assert body["candles"]
    assert body["readiness"]["forecast_ready"] is False
    groww = client.get("/api/market/history?instrument=NIFTY&provider=groww")
    assert groww.status_code == 501
    assert groww.json()["code"] == "CANDLE_BOUNDARY_UNVERIFIED"
