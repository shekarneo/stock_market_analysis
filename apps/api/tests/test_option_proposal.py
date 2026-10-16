"""Research proposal contract. Fixed inputs only. No provider or order calls."""

from app.execution.orders import live_order_calls
from app.options.fixtures import synthetic_nifty_chain
from app.options.pricing import price_contract
from app.options.proposal import build_research_proposal

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
        "model_version": "binary-1",
        "p_up": 0.6,
    }
    payload.update(overrides)
    return payload


def test_incomplete_proposal_keeps_expected_net_null_and_flags_false():
    before = len(live_order_calls)
    forecast = _forecast()
    proposal = build_research_proposal(forecast, _contract(), task_horizon="M15")
    assert proposal["schema_version"] == "m8-proposal-1"
    assert proposal["status"] == "INCOMPLETE"
    assert proposal["decision"] == "NO_TRADE"
    assert proposal["expected_net"] is None
    assert proposal["gross_expected"] is None
    assert proposal["executable"] is False
    assert proposal["order_connected"] is False
    assert proposal["research_candidate"]["status"] == "REJECTED"
    assert proposal["approvals"]["paper_approved"] is False
    assert proposal["approvals"]["live_approved"] is False
    assert proposal["approvals"]["forecast_ready"] is False
    assert proposal["approvals"]["real_market_data_verified"] is False
    assert proposal["approvals"]["research_selected"] is True
    assert forecast["promotion_state"] == "APPROVED_FOR_RESEARCH"
    assert len(live_order_calls) == before


def test_quoted_ask_stays_separate_from_a_calculated_premium():
    quoted = build_research_proposal(_forecast(), _contract(), task_horizon="M15")
    assert quoted["quote"]["accepted"] is True
    assert quoted["quote"]["ask"] == 122.0
    assert quoted["quote"]["premium"] == 122.0
    assert quoted["quote"]["premium_role"] == "QUOTED_ASK"
    assert quoted["quote"]["market_observation"] is False
    assert quoted["modelled_value"]["value"] is None
    assert quoted["modelled_value"]["usable_as_quote"] is False
    calculated = build_research_proposal(
        _forecast(),
        _contract(origin="CALCULATED", premium=4.0),
        task_horizon="M15",
    )
    assert calculated["quote"]["accepted"] is False
    assert calculated["quote"]["premium"] is None
    assert "CALCULATED_NOT_A_QUOTE" in calculated["decision_reasons"]
    assert calculated["modelled_value"]["supplied_calculated_premium"] == 4.0
    assert calculated["modelled_value"]["accepted_as_quote"] is False
    assert calculated["expected_net"] is None
    assert price_contract(_contract(), "MODELLED_BLACK76")["premium"] is None
    assert price_contract(_contract(), "MODELLED_VENDOR_GREEKS")["enabled"] is False


def test_missing_forecast_horizon_and_scenarios_are_explicit():
    missing = build_research_proposal(None, _contract(), task_horizon="M15")
    assert "MISSING_FORECAST" in missing["decision_reasons"]
    assert missing["forecast"]["present"] is False
    assert missing["status"] == "INCOMPLETE"
    mismatch = build_research_proposal(_forecast(horizon="M15"), _contract(), task_horizon="INTRADAY")
    assert "HORIZON_MISMATCH" in mismatch["decision_reasons"]
    assert "MISSING_SCENARIO_INPUTS" in mismatch["decision_reasons"]
    assert mismatch["scenarios"]["assumptions"] == {"up": None, "range": None, "down": None}
    assert mismatch["scenarios"]["status"] == "UNAVAILABLE"
    assert mismatch["decision"] == "NO_TRADE"
    positive = build_research_proposal(
        _forecast(r_up=0.02, p_up=0.9, p_range=0.05, p_down=0.05),
        _contract(option_type="CE"),
        task_horizon="M15",
    )
    assert positive["decision"] == "NO_TRADE"
    assert positive["expected_net"] is None


def test_missing_charges_and_lot_size_do_not_become_zero():
    proposal = build_research_proposal(
        _forecast(),
        _contract(),
        {"charges": 0, "charges_source": "OPERATOR_SCHEDULE_UNVERIFIED"},
        task_horizon="M15",
    )
    assert "MISSING_LOT_SIZE" in proposal["decision_reasons"]
    assert "CHARGES_UNVERIFIED" in proposal["decision_reasons"]
    assert proposal["charges"]["amount"] is None
    assert proposal["charges"]["verified"] is False
    assert proposal["charges"]["supplied_amount_used"] is False
    assert proposal["identity"]["lot_size"] is None
    assert proposal["identity"]["quantity"] is None
    assert proposal["identity"]["lot_count"] is None
    assert "MISSING_QUANTITY" in proposal["decision_reasons"]
    assert proposal["expected_net"] is None


def test_invalid_and_duplicate_identities_are_rejected():
    duplicate = build_research_proposal(
        _forecast(),
        _contract(),
        task_horizon="M15",
        siblings=[_contract()],
    )
    assert "DUPLICATE_CONTRACT" in duplicate["decision_reasons"]
    assert duplicate["identity"]["duplicate"] is True
    assert duplicate["executable"] is False
    invalid = build_research_proposal(_forecast(), _contract(expiry=None, strike=None), task_horizon="M15")
    assert "INVALID_EXPIRY" in invalid["decision_reasons"]
    assert "INVALID_STRIKE" in invalid["decision_reasons"]
    assert invalid["decision"] == "NO_TRADE"


def test_synthetic_and_quarantined_provenance_stay_unverified():
    fixture = synthetic_nifty_chain()["contracts"][0]
    synthetic = build_research_proposal(_forecast(), fixture, task_horizon="M15")
    assert "SYNTHETIC_NOT_A_MARKET_OBSERVATION" in synthetic["decision_reasons"]
    assert synthetic["quote"]["market_observation"] is False
    assert synthetic["quote"]["usable_as_quote"] is False
    assert synthetic["approvals"]["real_market_data_verified"] is False
    quarantined = build_research_proposal(
        _forecast(),
        _contract(label="UNVERIFIED_PROVIDER", quarantine_id="stored-row"),
        task_horizon="M15",
    )
    assert "QUARANTINE_REJECTED" in quarantined["decision_reasons"]
    assert quarantined["expected_net"] is None


def test_risk_veto_and_a_supplied_pass_cannot_approve_a_trade():
    veto = build_research_proposal(
        _forecast(),
        _contract(),
        task_horizon="M15",
        risk={"result": "VETO", "gates": [{"name": "kill_switch", "pass": False, "detail": "on"}]},
    )
    assert veto["risk"]["result"] == "VETO"
    assert veto["risk"]["passed"] is False
    assert "RISK_VETO" in veto["decision_reasons"]
    assert veto["decision"] == "NO_TRADE"
    refused = build_research_proposal(
        _forecast(promotion_state="APPROVED_FOR_PAPER"),
        _contract(),
        task_horizon="M15",
        risk={"result": "PASS", "gates": []},
    )
    assert "RISK_PASS_REFUSED" in refused["decision_reasons"]
    assert refused["approvals"]["paper_approved"] is False
    assert refused["approvals"]["live_approved"] is False
    assert refused["forecast"]["claims_paper_approval"] is True
    assert refused["executable"] is False
    names = {gate["name"]: gate for gate in refused["risk"]["gates"]}
    assert names["spread_volume_open_interest"]["applied"] is False
    assert names["spread_volume_open_interest"]["state"] == "NOT_CONFIGURED"
    assert names["iv_stress"]["applied"] is False
    assert names["mode"]["state"] == "NOT_EVALUATED"


def test_qualitative_forecast_is_complete_no_trade_and_ranking_is_not_executable():
    qualitative = build_research_proposal(
        _forecast(is_qualitative=True, p_up=None),
        _contract(),
        task_horizon="M15",
    )
    assert qualitative["status"] == "COMPLETE"
    assert qualitative["decision"] == "NO_TRADE"
    assert "QUALITATIVE_FORECAST" in qualitative["decision_reasons"]
    assert qualitative["approvals"]["paper_approved"] is False
    ranked = build_research_proposal(_forecast(), _contract(), task_horizon="M15", ranked=True)
    assert ranked["research_candidate"]["ranked"] is True
    assert ranked["research_candidate"]["status"] == "REJECTED"
    assert ranked["research_candidate"]["executable"] is False
    assert ranked["executable"] is False
    assert "RANK_IS_NOT_AN_ORDER" in ranked["decision_reasons"]
    again = build_research_proposal(_forecast(), _contract(), task_horizon="M15", ranked=True)
    assert again["decision_reasons"] == ranked["decision_reasons"]
