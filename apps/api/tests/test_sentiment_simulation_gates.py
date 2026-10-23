"""Phase 4 regressions: headline sentiment, paper simulation correctness, risk-gate bypasses."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.analysis.intelligence import (
    NEWS_MIN_HEADLINES,
    _evaluate_market_consensus,
    _infer_headline_direction,
    headline_is_relevant,
)
from app.config.loader import load_defaults
from app.execution.simulation import CHARGE_SCHEDULES, calculate_indian_regulatory_charges, charge_schedule_for
from app.risk.gates import _allow_list_gate, evaluate
from app.settings import REPO_ROOT

RISK = load_defaults(REPO_ROOT / "config" / "defaults.yaml").risk


# --- Headline sentiment ------------------------------------------------------

@pytest.mark.parametrize("text, instrument, expected", [
    ("Software award for TCS", "NIFTY", "UNKNOWN"),               # "war" inside "software"/"award"
    ("Nifty falls against dollar worries", "NIFTY", "BEARISH"),   # "gain" inside "against"
    ("Bulletin: markets steady", "NIFTY", "UNKNOWN"),             # "bull" inside "bulletin"
    ("IPO allotment GMP at 50", "NIFTY", "UNKNOWN"),              # IPO noise is not market direction
    ("Sensex does not fall as RBI holds rates", "SENSEX", "UNKNOWN"),  # negated cue
    ("Nifty rallies as stocks hit record high", "NIFTY", "BULLISH"),
    ("Crude oil prices surge on OPEC cut", "CRUDEOILMINI", "BULLISH"),
    ("Crude oil surges as war fears grow", "NIFTY", "UNKNOWN"),   # not about Indian equities
    ("War fears grow; crude steady", "CRUDEOILMINI", "UNKNOWN"),  # equity risk words not applied to crude
])
def test_headline_direction(text, instrument, expected):
    assert _infer_headline_direction(text, instrument) == expected


def test_relevance_filter():
    assert headline_is_relevant("Sensex ends higher", "SENSEX")
    assert not headline_is_relevant("Gold jewellery demand rises", "NIFTY")
    assert headline_is_relevant("Brent crude slips", "CRUDEOILMINI")


def _news_vote(headlines, instrument="NIFTY"):
    news = [{"claim": h, "explicit_directions": []} for h in headlines]
    rows = [{"instrument": instrument, "last_price": 25000.0, "category": "INDIAN_MARKET"}]
    consensus = _evaluate_market_consensus(rows, instrument, news)
    return next(v for v in consensus["agent_votes"] if v["agent"] == "News Sentiment Agent")["stance"]


def test_one_headline_never_moves_the_call():
    assert NEWS_MIN_HEADLINES >= 2
    assert _news_vote(["Nifty rallies to record high"]) == "NEUTRAL"


def test_agreeing_relevant_headlines_vote():
    assert _news_vote(["Nifty rallies to record high", "Sensex jumps as FII inflows rise"]) == "BULLISH"


def test_irrelevant_headlines_do_not_vote():
    assert _news_vote(["Crude oil surges", "Gold prices jump"]) == "NEUTRAL"


# --- Charges -----------------------------------------------------------------

def test_nse_option_exchange_rate():
    c = calculate_indian_regulatory_charges(side="BUY", price=Decimal("100"), quantity=Decimal("1000"))
    assert Decimal(c["exchange_charges"]) == Decimal("35.53")  # 0.03553% (incl. IPFT) of Rs1,00,000 premium
    assert c["exchange"] == "NSE" and c["rates_verified"] is True


def test_sensex_uses_bse_schedule_and_crude_uses_ctt():
    assert charge_schedule_for("SENSEX")[0] == "BSE"
    exchange, _ = charge_schedule_for("CRUDEOILMINI")
    assert exchange == "MCX"
    c = calculate_indian_regulatory_charges(side="SELL", price=Decimal("100"), quantity=Decimal("100"),
                                            exchange="MCX", instrument_type="OPTION")
    assert c["transaction_tax_label"] == "CTT"
    assert c["rates_verified"] is True  # checked 2026-10-23 (CTT 0.05% on sells, exchange 0.0418%)
    assert Decimal(c["stt"]) == Decimal("5.00")  # 0.05% CTT of Rs10,000 premium


def test_unknown_schedule_is_refused():
    assert charge_schedule_for("BANKNIFTY") is None
    with pytest.raises(ValueError):
        calculate_indian_regulatory_charges(side="BUY", price=Decimal("1"), quantity=Decimal("1"), exchange="XYZ")
    assert ("NSE", "OPTION") in CHARGE_SCHEDULES


def test_breakdown_records_lot_size_for_exit():
    c = calculate_indian_regulatory_charges(side="BUY", price=Decimal("100"), quantity=Decimal("130"),
                                            lot_size=Decimal("65"), charges_per_lot=Decimal("25"))
    assert c["lot_size"] == "65" and c["charges_per_lot"] == "25"


# --- Risk gates --------------------------------------------------------------

def test_short_option_entry_is_not_a_long_option():
    reasons: list[str] = []
    gate = _allow_list_gate({"underlying": "NIFTY", "option_type": "CE", "side": "SELL", "intent_purpose": "ENTRY"}, RISK, reasons)
    assert gate["blocks"] is True and "NOT_ON_ALLOW_LIST" in reasons


def test_selling_to_exit_a_long_option_is_allowed():
    reasons: list[str] = []
    gate = _allow_list_gate({"underlying": "NIFTY", "option_type": "CE", "side": "SELL", "intent_purpose": "EXIT"}, RISK, reasons)
    assert gate["blocks"] is False


def test_client_cannot_switch_on_experimental_gates():
    intent = {
        "mode": "PAPER", "intent_purpose": "ENTRY", "underlying": "NIFTY", "option_type": "CE", "side": "BUY",
        "execution_context": "EXPERIMENTAL", "experimental": True,  # client asks; server has not granted
    }
    result = evaluate(intent, session=None, config=RISK)
    funds = next(g for g in result["gates"] if g["name"] == "funds")
    assert funds["detail"] != "FUNDS_EXPERIMENTAL_ALLOCATED"
    assert result["passed"] is False


# --- Database-backed simulation checks (run with the Postgres test fixture) ---------

def _configure_risk(session, capital=1000000.0):
    from app.config.store import current_config, ensure_seed, replace_section
    from app.settings import get_settings

    settings = get_settings()
    ensure_seed(session, settings)
    risk = current_config(session).risk.model_dump()
    risk.update(risk_capital_inr=capital, max_open_positions=3, max_risk_fraction_per_trade=0.02, daily_loss_fraction=0.03,
                experimental_requires_server_ev=False)
    replace_section(session, settings, "risk", risk, actor="tester")
    session.commit()


def _sim_body(intent_id, **kw):
    from tests.test_experimental_paper_execution import _body
    return _body(intent_id, **kw)


def test_requested_lots_are_filled_and_capped(db):
    from app.db import get_session_factory
    from app.execution.simulation import run_paper_simulation

    session = get_session_factory()()
    try:
        _configure_risk(session)  # 2% of Rs10L = Rs20,000 budget; one lot ~ Rs7,890 -> max 2 lots
        ok = run_paper_simulation(session, _sim_body("lots-2", lots=2), actor="t")
        assert ok["code"] == "SIMULATED_FILL_APPLIED"
        assert ok["simulated_fill"]["quantity"] == "130"
        too_many = run_paper_simulation(session, _sim_body("lots-5", lots=5), actor="t")
        assert too_many["code"] == "VETOED"
        assert "LOTS_EXCEED_RISK_BUDGET" in too_many["reasons"]
    finally:
        session.rollback()
        session.close()


def test_experimental_request_without_operator_config_is_vetoed(db):
    from app.db import get_session_factory
    from app.execution.simulation import run_paper_simulation

    session = get_session_factory()()
    try:
        result = run_paper_simulation(session, _sim_body("no-config"), actor="t")  # risk controls not configured
        assert result["code"] != "SIMULATED_FILL_APPLIED"
    finally:
        session.rollback()
        session.close()


def test_close_without_price_is_refused(db):
    from app.db import get_session_factory
    from app.execution.simulation import close_paper_position, run_paper_simulation

    session = get_session_factory()()
    try:
        _configure_risk(session)
        assert run_paper_simulation(session, _sim_body("close-no-price"), actor="t")["code"] == "SIMULATED_FILL_APPLIED"
        result = close_paper_position(session, "close-no-price")
        assert result["ok"] is False and result["status"] == "EXIT_PRICE_REQUIRED"
        one_sided = close_paper_position(session, "close-no-price", exit_quote={"ask": "130.00"})
        assert one_sided["ok"] is False and one_sided["status"] == "EXIT_PRICE_REQUIRED"
    finally:
        session.rollback()
        session.close()


def test_daily_loss_uses_ist_session_day(db):
    from app.db import get_session_factory
    from app.domain.tables import PaperAccountEvent
    from app.risk.gates import _experimental_paper_portfolio_state

    session = get_session_factory()()
    try:
        # 2026-10-16 20:00 UTC is 2026-10-17 01:30 IST: belongs to the 17th, not the 16th
        late = datetime(2026, 10, 16, 20, 0, tzinfo=timezone.utc)
        session.add(PaperAccountEvent(
            # Exits are journaled as FILL events whose id starts with "sim-exit-" (the table allows no EXIT type)
            event_id="sim-exit-ist-1", event_type="FILL", occurred_at=late, intent_id="ist-1", source="SIMULATION",
            body_hash="0" * 64, opening_cash_inr=Decimal("1000000"), quantity=Decimal("65"), price=Decimal("100"),
            charges_inr=Decimal("0"), payload={"net_realized_pnl_inr": -5000.0}, effect={},
            ledger_applied=False, broker_confirmed=False,
        ))
        session.flush()
        _, pnl_16 = _experimental_paper_portfolio_state(session, "2026-10-16")
        _, pnl_17 = _experimental_paper_portfolio_state(session, "2026-10-17")
        assert pnl_16 == 0.0
        assert pnl_17 == -5000.0
    finally:
        session.rollback()
        session.close()
