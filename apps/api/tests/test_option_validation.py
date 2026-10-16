"""Option input validation. These tests do not price a contract or call a provider."""

from datetime import datetime, timedelta, timezone

from app.options.validation import validate_option_inputs

QUOTE = "2026-10-14T10:00:00+05:30"


def _candidate(**overrides) -> dict:
    payload = {
        "origin": "UNVERIFIED_MARKET_INPUT",
        "underlying": "NIFTY",
        "option_type": "CE",
        "strike": 25000,
        "expiry": "2026-10-20",
        "underlying_price": 25100.5,
        "bid": 120.5,
        "ask": 122.0,
        "quote_timestamp": QUOTE,
        "greeks": {"delta": None, "gamma": None, "theta": None, "vega": None},
        "volatility": {"value": 12.5, "scale": "PERCENT"},
        "interest_rate": {"value": 0.06, "unit": "ANNUAL_DECIMAL", "source": "CONFIGURED_INPUT"},
    }
    payload.update(overrides)
    return payload


def _codes(result: dict) -> set[str]:
    return {item["code"] for item in result["errors"]}


def test_valid_inputs_do_not_create_a_premium_or_a_trade():
    result = validate_option_inputs(_candidate())
    assert result["ok"] is True
    assert result["pricing"]["premium"] is None
    assert result["pricing"]["expected_net"] is None
    assert result["pricing"]["method"] is None
    assert result["pricing"]["status"] == "UNAVAILABLE"
    assert result["pricing"]["matches_broker_premium"] is False
    assert result["decision"] == "NO_TRADE"
    assert result["forecast_ready"] is False
    assert result["paper_approved"] is False
    assert result["live_approved"] is False
    assert result["real_market_data_verified"] is False
    assert result["accepted"]["greeks"] == {"delta": None, "gamma": None, "theta": None, "vega": None}


def test_origins_stay_distinct_and_calculated_values_are_not_quotes():
    synthetic = validate_option_inputs(_candidate(origin="SYNTHETIC_FIXTURE"))
    assert synthetic["ok"] is True
    assert synthetic["origin"] == "SYNTHETIC_FIXTURE"
    assert synthetic["real_market_data_verified"] is False
    calculated = validate_option_inputs(_candidate(origin="CALCULATED"))
    assert "CALCULATED_NOT_A_QUOTE" in _codes(calculated)
    assert calculated["pricing"]["premium"] is None
    claimed = validate_option_inputs(_candidate(matches_broker_premium=True))
    assert "VERIFICATION_REFUSED" in _codes(claimed)


def test_invalid_prices_strikes_and_underlyings_are_rejected():
    assert "INVALID_STRIKE" in _codes(validate_option_inputs(_candidate(strike=0)))
    assert "INVALID_STRIKE" in _codes(validate_option_inputs(_candidate(strike=True)))
    assert "INVALID_UNDERLYING_PRICE" in _codes(validate_option_inputs(_candidate(underlying_price=float("nan"))))
    assert "INVALID_BID" in _codes(validate_option_inputs(_candidate(bid=-1)))
    assert "INVALID_SPREAD" in _codes(validate_option_inputs(_candidate(bid=130, ask=120)))
    assert "PREMIUM_NOT_ASK" in _codes(validate_option_inputs(_candidate(premium=121)))
    assert "MISSING_ASK" in _codes(validate_option_inputs(_candidate(ask=None, ltp=121)))
    assert "INVALID_UNDERLYING" in _codes(validate_option_inputs(_candidate(underlying="BANKNIFTY")))
    assert "INVALID_UNDERLYING" not in _codes(validate_option_inputs(_candidate(underlying="SENSEX")))
    assert "INVALID_OPTION_TYPE" in _codes(validate_option_inputs(_candidate(option_type="SHORT_CE")))


def test_expiry_must_be_a_calendar_date_on_or_after_the_quote():
    assert "INVALID_EXPIRY" in _codes(validate_option_inputs(_candidate(expiry="Thursday")))
    assert "INVALID_EXPIRY" in _codes(validate_option_inputs(_candidate(expiry="2026-02-31")))
    assert "EXPIRED" in _codes(validate_option_inputs(_candidate(expiry="2026-10-13")))
    assert "INVALID_QUOTE_TIME" in _codes(validate_option_inputs(_candidate(quote_timestamp="2026-10-14T10:00:00")))
    stale = validate_option_inputs(
        _candidate(),
        as_of=datetime.fromisoformat(QUOTE) + timedelta(seconds=16),
    )
    assert "STALE_QUOTE" in _codes(stale)


def test_volatility_and_rate_need_units_and_do_not_enable_pricing():
    missing_scale = validate_option_inputs(_candidate(volatility={"value": 12.5}))
    assert "INVALID_VOLATILITY" in _codes(missing_scale)
    assert "INVALID_VOLATILITY" in _codes(validate_option_inputs(_candidate(volatility={"value": -1, "scale": "PERCENT"})))
    assert "INVALID_VOLATILITY" in _codes(validate_option_inputs(_candidate(volatility={"value": 9, "scale": "DECIMAL"})))
    labelled = validate_option_inputs(_candidate(volatility={"value": 0.125, "scale": "DECIMAL"}))
    assert labelled["ok"] is True
    assert labelled["accepted"]["volatility"] == {"value": 0.125, "scale": "DECIMAL"}
    assert labelled["pricing"]["method"] is None
    assert "INVALID_RATE" in _codes(validate_option_inputs(_candidate(interest_rate={"value": 0.06})))
    rated = validate_option_inputs(_candidate())
    assert rated["accepted"]["interest_rate"]["unit"] == "ANNUAL_DECIMAL"
    assert rated["pricing"]["status"] == "UNAVAILABLE"


def test_null_greeks_stay_null_and_text_greeks_fail():
    result = validate_option_inputs(_candidate(greeks={"delta": 0.4, "gamma": None, "theta": "per day", "vega": None}))
    assert "INVALID_GREEKS" in _codes(result)
    assert result["accepted"]["greeks"]["gamma"] is None
    assert result["pricing"]["premium"] is None
