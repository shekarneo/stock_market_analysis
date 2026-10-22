"""Phase 5 regressions: options analytics correctness, per-underlying expiries, consensus math."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.analysis.agent_config import AgentRole
from app.analysis.agent_nodes import market_data_analyst_node, news_event_analyst_node
from app.analysis.consensus_engine import evaluate_multi_agent_consensus
from app.market.groww_options import ist_today, resolve_upcoming_expiry, validate_contract_expiry
from app.options.m39_options_analytics import (
    analyze_options_chain,
    calculate_black76_and_greeks,
    solve_black76_implied_volatility,
)


# --- Black-76 theta -------------------------------------------------------------

@pytest.mark.parametrize("is_call", [True, False])
def test_theta_matches_numerical_time_decay(is_call):
    # Long-dated, high-rate case so the r*V term is large enough to expose a sign error
    f, k, t, vol, r = 25000.0, 24000.0, 1.0, 0.18, 0.10
    h = 1e-6
    numerical_per_year = (
        calculate_black76_and_greeks(f, k, t - h, vol, r, is_call).price
        - calculate_black76_and_greeks(f, k, t + h, vol, r, is_call).price
    ) / (2 * h)
    analytic = calculate_black76_and_greeks(f, k, t, vol, r, is_call).theta
    assert analytic == pytest.approx(numerical_per_year / 365.0, rel=1e-4)


# --- IV solver ------------------------------------------------------------------

def test_iv_is_none_when_undefined():
    assert solve_black76_implied_volatility(100.0, 25000.0, 25000.0, 0.0) is None  # at expiry
    assert solve_black76_implied_volatility(1.0, 25500.0, 25000.0, 7 / 365) is None  # below intrinsic


def test_iv_round_trip_still_works():
    price = calculate_black76_and_greeks(25000.0, 25000.0, 10 / 365, 0.2, 0.065, True).price
    assert solve_black76_implied_volatility(price, 25000.0, 25000.0, 10 / 365) == pytest.approx(0.2, abs=1e-5)


# --- Chain analysis without OI --------------------------------------------------

def test_missing_open_interest_is_not_zero():
    quotes = [
        {"strike": 25000.0, "option_type": "CE", "bid": 200.0, "ask": 205.0},
        {"strike": 25000.0, "option_type": "PE", "bid": 195.0, "ask": 200.0},
    ]
    s = analyze_options_chain(quotes, 25000.0, 7 / 365)
    assert s.pcr_oi is None and s.pcr_volume is None
    assert s.max_pain_strike is None
    assert s.directional_sentiment == "UNKNOWN" and s.sentiment_confidence is None
    assert "PCR_UNAVAILABLE_OI_MISSING" in s.reason_codes
    assert s.atm_iv is not None  # IV still solvable from bid/ask


def test_quotes_without_prices_have_no_iv():
    quotes = [{"strike": 25000.0, "option_type": "CE", "open_interest": 100.0, "volume": 10.0},
              {"strike": 25000.0, "option_type": "PE", "open_interest": 150.0, "volume": 12.0}]
    s = analyze_options_chain(quotes, 25000.0, 7 / 365)
    assert s.atm_iv is None
    assert s.volatility_skew_25d is None
    assert s.pcr_oi == 1.5


# --- Expiries -------------------------------------------------------------------

def test_sensex_and_mcx_are_not_checked_against_nifty_dates():
    ok, code = validate_contract_expiry("2026-10-27", as_of=date(2026, 10, 20), underlying="SENSEX")
    assert (ok, code) == (False, "EXPIRY_MASTER_UNAVAILABLE")
    assert resolve_upcoming_expiry("SENSEX", as_of=date(2026, 10, 20)) is None
    assert resolve_upcoming_expiry("CRUDEOILMINI", as_of=date(2026, 10, 20)) is None


def test_no_expired_date_is_returned_as_upcoming():
    assert resolve_upcoming_expiry("NIFTY", as_of=date(2040, 1, 1)) is None
    assert resolve_upcoming_expiry("NIFTY", as_of=date(2026, 10, 18)) == "2026-10-19"


def test_today_is_the_ist_date():
    # 19:00 UTC on the 19th is 00:30 IST on the 20th: the 19th expiry has passed in India
    late = datetime(2026, 10, 19, 19, 0, tzinfo=timezone.utc)
    assert ist_today(late) == date(2026, 10, 20)
    ok, code = validate_contract_expiry("2026-10-19", as_of=ist_today(late))
    assert (ok, code) == (False, "EXPIRED_CONTRACT")


# --- Consensus ------------------------------------------------------------------

def test_weighted_disagreement_discounts_a_weak_dissenter():
    outputs = {
        AgentRole.TECHNICAL.value: {"status": "SUCCESS", "directional_bias": "BULLISH", "confidence": 0.9},
        AgentRole.QUANT_FORECAST.value: {"status": "SUCCESS", "directional_bias": "BULLISH", "confidence": 0.9},
        AgentRole.NEWS_EVENT.value: {"status": "SUCCESS", "directional_bias": "BEARISH", "confidence": 0.2},
    }
    ev = evaluate_multi_agent_consensus(outputs)
    assert ev.disagreement_index < 0.2  # unweighted would be 1 - 1/3 = 0.67


def test_unknown_and_unconfident_agents_carry_no_weight():
    outputs = {
        AgentRole.TECHNICAL.value: {"status": "SUCCESS", "directional_bias": "BULLISH", "confidence": 0.8},
        AgentRole.MARKET_DATA.value: {"status": "SUCCESS", "directional_bias": "UNKNOWN", "confidence": None},
        AgentRole.GLOBAL_MACRO.value: {"status": "SUCCESS", "directional_bias": "NEUTRAL"},  # no confidence
    }
    ev = evaluate_multi_agent_consensus(outputs)
    scores = ev.specialist_scores
    assert scores[AgentRole.MARKET_DATA.value]["effective_weight"] == 0.0
    assert scores[AgentRole.GLOBAL_MACRO.value]["effective_weight"] == 0.0
    assert ev.consensus_score == pytest.approx(1.0)  # only the technical vote counts


def test_market_data_analyst_does_not_vote():
    out = market_data_analyst_node({"evidence": [], "agent_outputs": {}})["agent_outputs"][AgentRole.MARKET_DATA.value]
    assert out["directional_bias"] == "UNKNOWN"
    assert out["confidence"] is None


def test_news_analyst_abstains_without_clear_relevant_headlines():
    now = datetime(2026, 10, 16, 5, 0, tzinfo=timezone.utc).isoformat()
    state = {"instruments": ["NIFTY"], "agent_outputs": {}, "evidence": [
        {"category": "NEWS", "claim": "Software award for TCS", "published_at": now, "retrieved_at": now},
    ]}
    out = news_event_analyst_node(state)["agent_outputs"][AgentRole.NEWS_EVENT.value]
    assert out["directional_bias"] == "UNKNOWN"
    empty = news_event_analyst_node({"instruments": ["NIFTY"], "agent_outputs": {}, "evidence": []})
    assert empty["agent_outputs"][AgentRole.NEWS_EVENT.value]["directional_bias"] == "UNKNOWN"
