"""Mathematical checks for isolated pricing formulas. No provider is called."""

import math

from app.options.fixtures import synthetic_nifty_chain
from app.options.formulas import black76_premium, vendor_greek_step
from app.options.pricing import price_contract
from app.options.validation import validate_option_inputs

# Independent Black-76 values for F=100, K=100, T=1, sigma=0.20, r=0.05, continuous.
# Computed from the normal CDF outside this implementation.
ATM_CALL = 7.5770821464
ATM_PUT = 7.5770821464


def _black(**overrides) -> dict:
    payload = {
        "forward_source": "EXPLICIT_TEST_INPUT",
        "forward": 100,
        "strike": 100,
        "time_years": 1,
        "volatility": 0.2,
        "volatility_unit": "DECIMAL",
        "rate": 0.05,
        "rate_unit": "ANNUAL_CONTINUOUS",
        "rate_convention": "CONTINUOUS",
        "option_type": "CE",
    }
    payload.update(overrides)
    return black76_premium(payload)


def _codes(result: dict) -> set[str]:
    return {item["code"] for item in result["errors"]}


def test_black76_matches_independent_call_and_put_references():
    call = _black()
    put = _black(option_type="PE")
    assert call["ok"] is True
    assert math.isclose(call["premium"], ATM_CALL, rel_tol=0, abs_tol=1e-9)
    assert math.isclose(put["premium"], ATM_PUT, rel_tol=0, abs_tol=1e-9)
    parity = call["premium"] - put["premium"]
    assert math.isclose(parity, math.exp(-0.05) * (100 - 100), abs_tol=1e-12)
    shifted_call = _black(forward=110, strike=100)
    shifted_put = _black(forward=110, strike=100, option_type="PE")
    assert math.isclose(shifted_call["premium"] - shifted_put["premium"], math.exp(-0.05) * 10, abs_tol=1e-9)
    assert call["origin"] == "CALCULATED"
    assert call["usable_as_quote"] is False
    assert call["production_enabled"] is False
    assert call["decision"] == "NO_TRADE"
    assert call["expected_net"] is None
    assert call["forecast_ready"] is False
    assert call["paper_approved"] is False
    assert call["live_approved"] is False
    assert call["real_market_data_verified"] is False


def test_black76_boundaries_and_stability():
    assert math.isclose(_black(forward=100, strike=90, time_years=0, option_type="CE")["premium"], 10.0, abs_tol=1e-12)
    assert _black(forward=100, strike=90, time_years=0, option_type="PE")["premium"] == 0.0
    zero_vol = _black(forward=110, strike=100, volatility=0, option_type="CE")
    assert math.isclose(zero_vol["premium"], math.exp(-0.05) * 10, abs_tol=1e-12)
    assert _black(forward=110, strike=100, volatility=0, option_type="PE")["premium"] == 0.0
    deep_otm = _black(forward=100, strike=200, time_years=0.25, volatility=0.2, rate=0.01)
    assert 0 <= deep_otm["premium"] < 1e-9
    deep_itm = _black(forward=1_000_000, strike=1, volatility=0.01, rate=0)
    assert math.isfinite(deep_itm["premium"])
    assert deep_itm["premium"] > 0
    tiny = _black(time_years=1e-16)
    assert math.isfinite(tiny["premium"])


def test_black76_rejects_invalid_units_and_missing_forward_or_rate():
    assert "FORWARD_NOT_EXPLICIT" in _codes(_black(forward_source="SPOT"))
    assert "FORWARD_NOT_EXPLICIT" in _codes(_black(forward_source="UNDERLYING"))
    assert "AMBIGUOUS_RATE_CONVENTION" in _codes(_black(rate_convention=None))
    assert "AMBIGUOUS_RATE_UNIT" in _codes(_black(rate_unit="PERCENT"))
    assert "AMBIGUOUS_VOLATILITY_UNIT" in _codes(_black(volatility_unit="PERCENT"))
    assert "INVALID_DOMAIN" in _codes(_black(forward=None))
    assert "INVALID_DOMAIN" in _codes(_black(rate=None))
    assert "INVALID_DOMAIN" in _codes(_black(time_years=-1))
    assert "INVALID_DOMAIN" in _codes(_black(volatility=-0.1))
    assert "INVALID_DOMAIN" in _codes(_black(strike=True))
    assert _black(forward_source="SPOT")["premium"] is None
    assert _black(forward=None)["production_enabled"] is False


def test_vendor_greek_step_matches_the_specified_taylor_expression():
    result = vendor_greek_step(
        {
            "bid": 10,
            "ask": 12,
            "delta": 0.5,
            "gamma": 0.02,
            "theta": -0.1,
            "vega": 0.3,
            "d_underlying": 2,
            "d_time": 1,
            "d_volatility": 0.01,
            "theta_unit": "EXPLICIT_TEST_UNIT",
            "vega_unit": "EXPLICIT_TEST_UNIT",
            "d_volatility_unit": "EXPLICIT_TEST_UNIT",
        }
    )
    assert result["ok"] is True
    assert math.isclose(result["premium"], 11.943, abs_tol=1e-12)
    assert result["quoted_mid"] == 11
    assert result["origin"] == "CALCULATED"
    assert result["production_enabled"] is False
    assert result["decision"] == "NO_TRADE"
    assert result["expected_net"] is None
    floored = vendor_greek_step(
        {
            "bid": 1,
            "ask": 1,
            "delta": 0,
            "gamma": 0,
            "theta": -10,
            "vega": 0,
            "d_underlying": 0,
            "d_time": 1,
            "d_volatility": 0,
            "theta_unit": "EXPLICIT_TEST_UNIT",
            "vega_unit": "EXPLICIT_TEST_UNIT",
            "d_volatility_unit": "EXPLICIT_TEST_UNIT",
        }
    )
    assert floored["premium"] == 0.0


def test_unresolved_greek_units_do_not_guess():
    missing_theta = vendor_greek_step(
        {
            "bid": 10,
            "ask": 12,
            "delta": 0.5,
            "gamma": 0,
            "theta": -0.1,
            "vega": 0,
            "d_underlying": 1,
            "d_time": 1,
            "d_volatility": 0,
            "vega_unit": "DECIMAL",
            "d_volatility_unit": "DECIMAL",
        }
    )
    assert "UNRESOLVED_THETA_UNIT" in _codes(missing_theta)
    assert missing_theta["premium"] is None
    mismatch = vendor_greek_step(
        {
            "bid": 10,
            "ask": 12,
            "delta": 0.5,
            "gamma": 0,
            "theta": 0,
            "vega": 1,
            "d_underlying": 0,
            "d_time": 0,
            "d_volatility": 1,
            "theta_unit": "EXPLICIT_TEST_UNIT",
            "vega_unit": "PERCENT_POINT",
            "d_volatility_unit": "DECIMAL",
        }
    )
    assert "UNRESOLVED_VEGA_UNIT" in _codes(mismatch)
    assert mismatch["production_status"] == "UNAVAILABLE"


def test_formula_output_is_not_a_quote_and_production_stays_blocked():
    chain = synthetic_nifty_chain()
    before = chain["origin"]
    calculated = _black()
    assert chain["origin"] == before == "SYNTHETIC_FIXTURE"
    assert all(row["origin"] == "SYNTHETIC_FIXTURE" for row in chain["contracts"])
    rejected = validate_option_inputs(
        {
            "origin": calculated["origin"],
            "underlying": "NIFTY",
            "option_type": "CE",
            "strike": 100,
            "expiry": "2026-10-20",
            "underlying_price": 100,
            "bid": 7,
            "ask": 8,
            "premium": calculated["premium"],
            "quote_timestamp": "2026-10-14T10:00:00+05:30",
        }
    )
    assert "CALCULATED_NOT_A_QUOTE" in _codes(rejected)
    contract = {
        "option_type": "CE",
        "strike": 100,
        "underlying_price": 100,
        "forward": 100,
        "bid": 7,
        "ask": 8,
        "volatility": {"value": 0.2, "scale": "DECIMAL"},
        "greeks": {"delta": 0.5, "gamma": 0.01, "theta": -1, "vega": 2},
    }
    blocked = price_contract(contract, "MODELLED_BLACK76")
    assert blocked["status"] == "UNAVAILABLE"
    assert blocked["enabled"] is False
    assert blocked["premium"] is None
    assert blocked["expected_net"] is None
    assert blocked["decision"] == "NO_TRADE"
    assert blocked["forecast_ready"] is False
    assert blocked["paper_approved"] is False
    assert blocked["live_approved"] is False
    assert blocked["real_market_data_verified"] is False
    greeks = price_contract(contract, "MODELLED_VENDOR_GREEKS")
    assert greeks["premium"] is None
    assert greeks["decision"] == "NO_TRADE"
