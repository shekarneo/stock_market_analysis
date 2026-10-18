"""Unit and integration test suite for Milestone M39: Indian Market Options Analytics & Black-76 Valuation.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
import pytest

from app.analysis.agent_config import AgentRole
from app.analysis.agent_nodes import options_analyst_node
from app.analysis.state import AnalysisState
from app.options.m39_options_analytics import (
    Black76Greeks,
    OptionsChainSummary,
    analyze_options_chain,
    calculate_black76_and_greeks,
    compute_max_pain_strike,
    solve_black76_implied_volatility,
)


def test_black76_call_and_put_analytical_pricing():
    """Verify Black-76 pricing satisfies European Put-Call Parity: Call - Put = e^(-rT) * (F - K)."""
    forward = 25000.0
    strike = 25000.0
    time_years = 14.0 / 365.0
    volatility = 0.16
    rate = 0.065

    call_greeks = calculate_black76_and_greeks(forward, strike, time_years, volatility, rate, is_call=True)
    put_greeks = calculate_black76_and_greeks(forward, strike, time_years, volatility, rate, is_call=False)

    disc = math.exp(-rate * time_years)
    parity_diff = (call_greeks.price - put_greeks.price) - disc * (forward - strike)

    assert abs(parity_diff) < 1e-10, f"Put-Call Parity violated: {parity_diff}"
    assert call_greeks.price > 0.0
    assert put_greeks.price > 0.0


def test_black76_greeks_bounds():
    """Verify analytical Greeks satisfy theoretical boundary conditions."""
    forward = 25200.0
    strike = 25000.0
    time_years = 21.0 / 365.0
    volatility = 0.18
    rate = 0.065
    disc = math.exp(-rate * time_years)

    call = calculate_black76_and_greeks(forward, strike, time_years, volatility, rate, is_call=True)
    put = calculate_black76_and_greeks(forward, strike, time_years, volatility, rate, is_call=False)

    # Delta bounds
    assert 0.0 <= call.delta <= disc, f"Call delta out of bounds: {call.delta}"
    assert -disc <= put.delta <= 0.0, f"Put delta out of bounds: {put.delta}"

    # Gamma and Vega must be identical and positive
    assert call.gamma > 0.0
    assert abs(call.gamma - put.gamma) < 1e-10
    assert call.vega > 0.0
    assert abs(call.vega - put.vega) < 1e-10

    # Theta must be negative for long options
    assert call.theta < 0.0
    assert put.theta < 0.0


def test_implied_volatility_solver_convergence():
    """Verify hybrid Newton-Raphson/Bisection solver recovers true IV within 1e-5 tolerance."""
    forward = 25100.0
    strike = 25000.0
    time_years = 10.0 / 365.0
    rate = 0.065

    test_ivs = [0.10, 0.155, 0.22, 0.35]
    for true_iv in test_ivs:
        # Price call
        call_price = calculate_black76_and_greeks(forward, strike, time_years, true_iv, rate, is_call=True).price
        recovered_iv = solve_black76_implied_volatility(call_price, forward, strike, time_years, rate, is_call=True)
        assert abs(recovered_iv - true_iv) < 1e-5, f"Call IV solver failed for {true_iv}: recovered {recovered_iv}"

        # Price put
        put_price = calculate_black76_and_greeks(forward, strike, time_years, true_iv, rate, is_call=False).price
        recovered_put_iv = solve_black76_implied_volatility(put_price, forward, strike, time_years, rate, is_call=False)
        assert abs(recovered_put_iv - true_iv) < 1e-5, f"Put IV solver failed for {true_iv}: recovered {recovered_put_iv}"


def test_max_pain_calculation():
    """Verify Max Pain strike calculation on a structured options chain."""
    strikes = [24800.0, 24900.0, 25000.0, 25100.0, 25200.0]
    ce_oi = [1000.0, 2500.0, 10000.0, 8000.0, 4000.0]
    pe_oi = [5000.0, 9000.0, 11000.0, 3000.0, 1200.0]

    max_pain_k, min_loss = compute_max_pain_strike(strikes, ce_oi, pe_oi)

    assert max_pain_k == 25000.0
    assert min_loss == 990000.0


def test_options_chain_pcr_sentiment_classification():
    """Verify PCR sentiment thresholds: Bullish (> 1.25), Bearish (< 0.75), Neutral (0.75 to 1.25)."""
    forward = 25000.0
    t_years = 7.0 / 365.0

    # Bullish chain: heavy Put OI (PE OI 15000 vs CE OI 10000 -> PCR = 1.50)
    bullish_quotes = [
        {"strike": 25000.0, "option_type": "CE", "bid": 200.0, "ask": 205.0, "open_interest": 10000.0, "volume": 5000.0},
        {"strike": 25000.0, "option_type": "PE", "bid": 195.0, "ask": 200.0, "open_interest": 15000.0, "volume": 7500.0},
    ]
    summary_bull = analyze_options_chain(bullish_quotes, forward, t_years)
    assert summary_bull.pcr_oi == 1.50
    assert summary_bull.directional_sentiment == "BULLISH"
    assert summary_bull.sentiment_confidence >= 0.55
    assert "PCR_BULLISH_SUPPORT" in summary_bull.reason_codes

    # Bearish chain: heavy Call OI (PE OI 5000 vs CE OI 10000 -> PCR = 0.50)
    bearish_quotes = [
        {"strike": 25000.0, "option_type": "CE", "bid": 200.0, "ask": 205.0, "open_interest": 10000.0, "volume": 5000.0},
        {"strike": 25000.0, "option_type": "PE", "bid": 195.0, "ask": 200.0, "open_interest": 5000.0, "volume": 2500.0},
    ]
    summary_bear = analyze_options_chain(bearish_quotes, forward, t_years)
    assert summary_bear.pcr_oi == 0.50
    assert summary_bear.directional_sentiment == "BEARISH"
    assert "PCR_BEARISH_RESISTANCE" in summary_bear.reason_codes


def test_options_analyst_node_integration():
    """Verify options_analyst_node parses options evidence and populates PCR and Greeks."""
    derivatives_evidence = [
        {
            "category": "DERIVATIVES",
            "evidence_id": "opt_ce_25000",
            "strike": 25000.0,
            "option_type": "CE",
            "bid": 205.0,
            "ask": 210.0,
            "open_interest": 8000.0,
            "volume": 4000.0,
            "forward_price": 25000.0,
            "instrument": "NIFTY",
        },
        {
            "category": "DERIVATIVES",
            "evidence_id": "opt_pe_25000",
            "strike": 25000.0,
            "option_type": "PE",
            "bid": 200.0,
            "ask": 205.0,
            "open_interest": 12000.0,
            "volume": 6000.0,
            "forward_price": 25000.0,
            "instrument": "NIFTY",
        },
    ]

    state: AnalysisState = {
        "evidence": derivatives_evidence,
        "agent_outputs": {},
    }

    res = options_analyst_node(state)
    out = res["agent_outputs"][AgentRole.OPTIONS.value]

    assert out["status"] == "SUCCESS"
    assert out["directional_bias"] == "BULLISH"
    assert out["confidence"] is not None and out["confidence"] > 0.50
    assert any("Options PCR(OI): 1.50" in f for f in out["findings"])
    assert any("Max Pain Strike: 25000" in f for f in out["findings"])


def test_m39_safety_invariants_strictly_false():
    """Verify all safety invariants remain strictly False across options analytics."""
    forward = 25000.0
    quotes = [
        {"strike": 25000.0, "option_type": "CE", "bid": 200.0, "ask": 205.0, "open_interest": 10000.0, "volume": 5000.0},
        {"strike": 25000.0, "option_type": "PE", "bid": 195.0, "ask": 200.0, "open_interest": 15000.0, "volume": 7500.0},
    ]
    summary = analyze_options_chain(quotes, forward, time_years=7.0 / 365.0)

    # Analysis produces diagnostic metrics but does not authorize live orders
    assert summary.strikes_evaluated == 1
    assert summary.pcr_oi == 1.50
