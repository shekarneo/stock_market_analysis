"""Expected-value gates. Fixed inputs only. No provider calls."""

from datetime import datetime, timedelta

from app.options.expected_value import combine_scenario_nets, evaluate_expected_value, rank_candidates
from app.options.fixtures import synthetic_nifty_chain
from app.options.pricing import price_contract

QUOTE = "2026-10-14T10:00:00+05:30"


def _contract(**overrides) -> dict:
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
    }
    payload.update(overrides)
    return payload


def _forecast(**overrides) -> dict:
    payload = {
        "horizon": "M15",
        "promotion_state": "APPROVED_FOR_RESEARCH",
        "is_qualitative": False,
        "p_up": 0.6,
        "p_range": 0.2,
        "p_down": 0.2,
    }
    payload.update(overrides)
    return payload


def test_missing_and_unapproved_forecasts_have_no_expected_net():
    missing = evaluate_expected_value(None, _contract(), task_horizon="M15")
    assert "MISSING_FORECAST" in missing["reasons"]
    assert missing["expected_net"] is None
    research = evaluate_expected_value(_forecast(), _contract(), task_horizon="M15")
    assert "FORECAST_NOT_APPROVED" in research["reasons"]
    assert "RESEARCH_SELECTION_NOT_APPROVAL" in research["reasons"]
    assert research["expected_net"] is None
    assert research["paper_approved"] is False
    assert research["live_approved"] is False


def test_direction_probability_and_horizon_mismatch_are_not_a_price_forecast():
    result = evaluate_expected_value(_forecast(horizon="M15"), _contract(), task_horizon="INTRADAY")
    assert "HORIZON_MISMATCH" in result["reasons"]
    assert "DIRECTION_PROBABILITY_NOT_A_PRICE_FORECAST" in result["reasons"]
    assert "MISSING_CLASS_CONDITIONAL_RETURNS" in result["reasons"]
    assert result["modelled_value"] is None
    assert result["gross_expected"] is None
    assert result["expected_net"] is None


def test_stale_synthetic_quarantine_and_missing_quote_inputs_stay_unavailable():
    as_of = datetime.fromisoformat(QUOTE) + timedelta(seconds=16)
    stale = evaluate_expected_value(_forecast(), _contract(), task_horizon="M15", as_of=as_of)
    assert "STALE_QUOTE" in stale["reasons"]
    fixture = synthetic_nifty_chain()["contracts"][0]
    synthetic = evaluate_expected_value(_forecast(), fixture, task_horizon="M15")
    assert "SYNTHETIC_NOT_A_MARKET_OBSERVATION" in synthetic["reasons"]
    assert synthetic["expected_net"] is None
    quarantined = evaluate_expected_value(
        _forecast(),
        _contract(label="UNVERIFIED_PROVIDER", quarantine_id="stored-row"),
        task_horizon="M15",
    )
    assert "QUARANTINE_REJECTED" in quarantined["reasons"]
    expired = evaluate_expected_value(_forecast(), _contract(expiry=None), task_horizon="M15")
    assert "INVALID_EXPIRY" in expired["reasons"]


def test_missing_pricing_inputs_lot_size_and_charges_leave_expected_net_null():
    bare = _contract(volatility=None, greeks=None)
    result = evaluate_expected_value(_forecast(), bare, task_horizon="M15")
    assert "MISSING_PRICING_INPUT:MODELLED_VENDOR_GREEKS:volatility" in result["reasons"]
    assert "MISSING_PRICING_INPUT:MODELLED_BLACK76:year_fraction" in result["reasons"]
    assert "MISSING_FORWARD" in result["reasons"]
    assert "MISSING_LOT_SIZE" in result["reasons"]
    assert "MISSING_CHARGES" in result["reasons"]
    assert result["charges"] is None
    assert result["expected_net"] is None
    supplied = evaluate_expected_value(
        _forecast(),
        _contract(lot_size=65),
        {"charges": 0, "charges_source": "OPERATOR_SCHEDULE_UNVERIFIED"},
        task_horizon="M15",
    )
    assert "CHARGES_UNVERIFIED" in supplied["reasons"]
    assert supplied["charges"] is None
    assert supplied["expected_net"] is None


def test_explicit_scenario_sum_is_not_a_quote_or_an_approval():
    calculated = combine_scenario_nets({"up": 0.5, "range": 0.3, "down": 0.2}, {"up": 10.0, "range": 0.0, "down": -5.0})
    assert calculated["expected_net"] == 4.0
    assert calculated["unit"] == "CURRENCY_OF_ASK_AND_CHARGES"
    assert calculated["usable_as_quote"] is False
    assert calculated["production_enabled"] is False
    assert calculated["decision"] == "NO_TRADE"
    assert calculated["forecast_ready"] is False
    rejected = validate_quote(calculated)
    assert rejected["ok"] is False
    approved_looking = evaluate_expected_value(
        _forecast(
            promotion_state="APPROVED_FOR_PAPER",
            r_up=0.01,
            r_range=0.0,
            r_down=-0.01,
            p_up=0.5,
            p_range=0.3,
            p_down=0.2,
        ),
        _contract(option_type="CE", lot_size=65),
        {"charges": 20, "charges_source": "VERIFIED_SCHEDULE"},
        task_horizon="M15",
    )
    assert approved_looking["expected_net"] is None
    assert approved_looking["charges"] is None
    assert approved_looking["modelled_value"] is None
    assert "CHARGES_UNVERIFIED" in approved_looking["reasons"]
    assert "PRICING_UNAVAILABLE:MODELLED_BLACK76" in approved_looking["reasons"]
    assert price_contract(_contract(), "MODELLED_BLACK76")["premium"] is None


def validate_quote(calculated: dict) -> dict:
    from app.options.validation import validate_option_inputs

    return validate_option_inputs(_contract(origin="CALCULATED", premium=calculated["expected_net"]))


def test_ranking_is_stable_and_refuses_invalid_or_duplicate_rows():
    rows = [
        _row(strike=25200, expected_net=4.0),
        _row(strike=25000, expected_net=4.0),
        _row(strike=25100, expected_net=9.0),
        _row(strike=25100, expected_net=9.0),
        _row(strike=24900, expected_net=None),
        _row(strike=24800, expected_net=3.0, origin="SYNTHETIC_FIXTURE"),
    ]
    ranked = rank_candidates(rows)
    assert ranked["decision"] == "NO_TRADE"
    assert ranked["trade_recommendation"] is False
    assert ranked["paper_approved"] is False
    assert [item["strike"] for item in ranked["ordered"]] == [25000, 25200]
    assert all(item["trade_recommendation"] is False for item in ranked["ordered"])
    rejected = {item["index"]: item["reasons"] for item in ranked["rejected"]}
    assert "DUPLICATE_CONTRACT" in rejected[2]
    assert "DUPLICATE_CONTRACT" in rejected[3]
    assert "EXPECTED_NET_UNAVAILABLE" in rejected[4]
    assert "PROVENANCE_NOT_TRADABLE" in rejected[5]


def test_no_eligible_candidate_is_no_trade():
    ranked = rank_candidates([_row(strike=25000, expected_net=None), {"strike": "bad"}])
    assert ranked["decision"] == "NO_TRADE"
    assert ranked["ordered"] == []
    assert "NO_ELIGIBLE_CANDIDATE" in ranked["reasons"]
    assert ranked["forecast_ready"] is False
    assert ranked["real_market_data_verified"] is False


def _row(**overrides) -> dict:
    payload = {
        "underlying": "NIFTY",
        "expiry": "2026-10-20",
        "strike": 25000,
        "option_type": "CE",
        "expected_net": 4.0,
        "calculation_status": "EXPLICIT_TEST_INPUT",
        "origin": "EXPLICIT_TEST_INPUT",
    }
    payload.update(overrides)
    return payload
