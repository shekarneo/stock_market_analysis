"""Contract selection and pricing gates. No provider is called."""

import inspect
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.config.loader import load_defaults
from app.market.service import build_snapshot
from app.options.fixtures import synthetic_nifty_chain
from app.options.pricing import price_contract
from app.options.selection import select_contract
from app.options.validation import option_eligibility_seconds, validate_option_inputs
from app.settings import REPO_ROOT

QUOTE = "2026-10-14T10:00:00+05:30"


def _codes(result: dict) -> set[str]:
    return {item["code"] for item in result["errors"]}


def test_option_eligibility_uses_the_freshness_limit_only():
    config = load_defaults(REPO_ROOT / "config" / "defaults.yaml")
    assert option_eligibility_seconds(config) == config.freshness.option_block_seconds
    split = SimpleNamespace(
        freshness=SimpleNamespace(option_block_seconds=30),
        risk=SimpleNamespace(quote_max_age_seconds=5),
    )
    assert option_eligibility_seconds(split) == 30
    chain = synthetic_nifty_chain()
    criteria = {"underlying": "NIFTY", "option_type": "CE", "expiry": "2026-10-20", "strike": 25100}
    as_of = datetime.fromisoformat(QUOTE) + timedelta(seconds=10)
    fresh = select_contract(chain, criteria, as_of=as_of, max_age=timedelta(seconds=30))
    stale = select_contract(chain, criteria, as_of=as_of, max_age=timedelta(seconds=5))
    assert fresh["matched"] is True
    assert "STALE_QUOTE" in _codes(stale)
    source = inspect.getsource(build_snapshot)
    assert "config.risk.quote_max_age_seconds" in source
    assert "option_block_seconds" not in source


def test_broker_symbol_matches_trading_symbol_and_does_not_invent_groww_symbol():
    quoted = validate_option_inputs(
        {
            "origin": "UNVERIFIED_MARKET_INPUT",
            "underlying": "NIFTY",
            "option_type": "CE",
            "strike": 25100,
            "expiry": "2026-10-20",
            "underlying_price": 25100,
            "bid": 140,
            "ask": 142,
            "quote_timestamp": QUOTE,
            "broker_symbol": "NIFTY25OCT25100CE",
            "trading_symbol": "NIFTY25OCT25100CE",
        }
    )
    assert quoted["ok"] is True
    assert quoted["accepted"]["broker_symbol"] == "NIFTY25OCT25100CE"
    assert quoted["accepted"]["trading_symbol"] == "NIFTY25OCT25100CE"
    assert quoted["accepted"]["groww_symbol"] is None
    mismatch = validate_option_inputs(
        {
            "origin": "UNVERIFIED_MARKET_INPUT",
            "underlying": "NIFTY",
            "option_type": "CE",
            "strike": 25100,
            "expiry": "2026-10-20",
            "underlying_price": 25100,
            "bid": 140,
            "ask": 142,
            "quote_timestamp": QUOTE,
            "broker_symbol": "ONE",
            "trading_symbol": "OTHER",
        }
    )
    assert "SYMBOL_MISMATCH" in _codes(mismatch)


def test_exact_and_nearest_selection_are_not_recommendations():
    criteria = {"underlying": "NIFTY", "option_type": "PE", "expiry": "2026-10-20", "strike": 25000}
    selected = select_contract(synthetic_nifty_chain(), criteria)
    assert selected["matched"] is True
    assert selected["selected"]["option_type"] == "PE"
    assert selected["selected"]["strike"] == 25000
    assert selected["selected"]["origin"] == "SYNTHETIC_FIXTURE"
    assert selected["selected"]["market_observation"] is False
    assert selected["selected"]["real_market_data_verified"] is False
    assert selected["decision"] == "NO_TRADE"
    assert selected["trade_recommendation"] is False
    assert selected["premium"] is None
    assert selected["expected_net"] is None
    nearest = select_contract(
        synthetic_nifty_chain(),
        {"underlying": "NIFTY", "option_type": "CE", "expiry": "2026-10-20", "strike_rule": "NEAREST_UNDERLYING"},
    )
    assert nearest["matched"] is True
    assert nearest["selected"]["strike"] == 25100
    assert nearest["forecast_ready"] is False
    assert nearest["paper_approved"] is False
    assert nearest["live_approved"] is False
    assert nearest["real_market_data_verified"] is False


def test_missing_ambiguous_invalid_and_stale_selection():
    chain = synthetic_nifty_chain()
    missing = select_contract(chain, {"underlying": "NIFTY", "option_type": "CE", "expiry": "2026-10-20", "strike": 26000})
    assert "NO_MATCH" in _codes(missing)
    assert missing["selected"] is None
    tied = synthetic_nifty_chain()
    for row in tied["contracts"]:
        if row["strike"] == 25100 and row["option_type"] == "CE":
            row["strike"] = 24900
    ambiguous = select_contract(
        tied,
        {"underlying": "NIFTY", "option_type": "CE", "expiry": "2026-10-20", "strike_rule": "NEAREST_UNDERLYING"},
    )
    assert "AMBIGUOUS_MATCH" in _codes(ambiguous)
    assert ambiguous["selected"] is None
    bad_type = select_contract(chain, {"underlying": "NIFTY", "option_type": "SHORT_CE", "expiry": "2026-10-20", "strike": 25100})
    assert "INVALID_OPTION_TYPE" in _codes(bad_type)
    bad_expiry = select_contract(chain, {"underlying": "NIFTY", "option_type": "CE", "expiry": "Thursday", "strike": 25100})
    assert "INVALID_EXPIRY" in _codes(bad_expiry)
    stale = select_contract(
        chain,
        {"underlying": "NIFTY", "option_type": "CE", "expiry": "2026-10-20", "strike": 25100},
        as_of=datetime.fromisoformat(QUOTE) + timedelta(seconds=16),
    )
    assert "STALE_QUOTE" in _codes(stale)
    mixed = synthetic_nifty_chain()
    mixed["contracts"][0]["origin"] = "UNVERIFIED_MARKET_INPUT"
    mixed_result = select_contract(mixed, {"underlying": "NIFTY", "option_type": "CE", "expiry": "2026-10-20", "strike": 25100})
    assert "MIXED_PROVENANCE" in _codes(mixed_result)


def test_unverified_input_stays_unverified_and_calculated_prices_are_not_quotes():
    chain = synthetic_nifty_chain()
    chain["origin"] = "UNVERIFIED_MARKET_INPUT"
    for row in chain["contracts"]:
        row["origin"] = "UNVERIFIED_MARKET_INPUT"
    selected = select_contract(chain, {"underlying": "NIFTY", "option_type": "CE", "expiry": "2026-10-20", "strike": 25200})
    assert selected["matched"] is True
    assert selected["origin"] == "UNVERIFIED_MARKET_INPUT"
    assert selected["real_market_data_verified"] is False
    priced = price_contract(selected["selected"], "MODELLED_VENDOR_GREEKS", {"theta_time_unit": "PER_DAY"})
    assert priced["status"] == "UNAVAILABLE"
    assert priced["enabled"] is False
    assert priced["premium"] is None
    assert priced["expected_net"] is None
    assert priced["decision"] == "NO_TRADE"
    assert priced["usable_as_quote"] is False
    assert priced["origin"] == "CALCULATED"
    assert "theta" in priced["missing"]
    assert any(item.startswith("theta_time_unit:") for item in priced["unverified"])
    assert "ASSUMPTION_UNVERIFIED" in _codes(priced)
    fed_back = validate_option_inputs(
        {
            "origin": priced["origin"],
            "underlying": "NIFTY",
            "option_type": "CE",
            "strike": 25200,
            "expiry": "2026-10-20",
            "underlying_price": 25100,
            "bid": 100,
            "ask": 102,
            "quote_timestamp": QUOTE,
        }
    )
    assert "CALCULATED_NOT_A_QUOTE" in _codes(fed_back)


def test_black76_stays_unavailable_without_verified_assumptions():
    contract = {
        "option_type": "CE",
        "strike": 25100,
        "underlying_price": 25100,
        "bid": 140,
        "ask": 142,
        "volatility": {"value": 12.5, "scale": "PERCENT"},
        "greeks": {"delta": 0.5, "gamma": 0.01, "theta": -1, "vega": 2},
    }
    black = price_contract(contract, "MODELLED_BLACK76", {"exercise_style": "EUROPEAN", "rate": 0.06, "future": 25100})
    assert black["enabled"] is False
    assert black["premium"] is None
    assert black["expected_net"] is None
    assert black["decision"] == "NO_TRADE"
    assert "year_fraction" in black["missing"]
    assert "approved_forecast" in black["missing"]
    assert any(item.startswith("exercise_style:") for item in black["unverified"])
    assert any(item.startswith("matching_future:") for item in black["unverified"])
    assert black["forecast_ready"] is False
    assert black["paper_approved"] is False
    assert black["live_approved"] is False
    assert black["real_market_data_verified"] is False
    vendor = price_contract(contract, "MODELLED_VENDOR_GREEKS")
    assert vendor["status"] == "UNAVAILABLE"
    assert vendor["premium"] is None
    assert "approved_forecast" in vendor["missing"]
    assert "METHOD_UNKNOWN" in _codes(price_contract(contract, "BLACK_SCHOLES"))
