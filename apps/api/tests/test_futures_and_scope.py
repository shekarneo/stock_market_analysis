from datetime import datetime, timezone
import pytest

from app.config.loader import load_defaults
from app.config.schemas import RiskConfig
from app.instruments import (
    ALL_STRUCTURES,
    DECISIONS,
    FUTURES_STRUCTURES,
    FUTURES_UNDERLYINGS,
    INDEX_UNDERLYINGS,
    OPTION_UNDERLYINGS,
    REMOVED_UNDERLYINGS,
    TRADABLE_UNDERLYINGS,
    canonical_underlying,
)
from app.options.candidate import assess_option_candidate
from app.options.validation import validate_option_inputs
from app.risk.gates import evaluate
from app.settings import REPO_ROOT

AT = datetime(2026, 10, 16, 9, 30, tzinfo=timezone.utc)


def _base_risk_config(**overrides) -> RiskConfig:
    risk = load_defaults(REPO_ROOT / "config" / "defaults.yaml").risk
    return risk.model_copy(update=overrides)


def test_instrument_constants():
    assert "NIFTY" in INDEX_UNDERLYINGS
    assert "SENSEX" in INDEX_UNDERLYINGS
    assert "BANKNIFTY" not in INDEX_UNDERLYINGS

    assert "CRUDEOILMINI" in TRADABLE_UNDERLYINGS
    assert "CRUDEOILMINI" in OPTION_UNDERLYINGS
    assert "CRUDEOILMINI" in FUTURES_UNDERLYINGS
    assert "BANKNIFTY" in REMOVED_UNDERLYINGS

    assert canonical_underlying("CRUDEMINI") == "CRUDEOILMINI"
    assert canonical_underlying("crudeoilm") == "CRUDEOILMINI"
    assert canonical_underlying("NIFTY") == "NIFTY"


def test_crudeoilmini_and_sensex_option_validation():
    # SENSEX option candidate
    sensex_cand = {
        "origin": "SYNTHETIC_FIXTURE",
        "underlying": "SENSEX",
        "option_type": "CE",
        "strike": 75000,
        "expiry": "2026-10-22",
        "underlying_price": 75100,
        "bid": 200,
        "ask": 205,
        "quote_timestamp": AT.isoformat(),
    }
    rep_sensex = validate_option_inputs(sensex_cand)
    assert rep_sensex["ok"] is True
    assert "INVALID_UNDERLYING" not in [e["code"] for e in rep_sensex["errors"]]

    # CRUDEOILMINI option candidate
    crude_cand = {
        "origin": "SYNTHETIC_FIXTURE",
        "underlying": "CRUDEOILMINI",
        "option_type": "PE",
        "strike": 6500,
        "expiry": "2026-10-22",
        "underlying_price": 6480,
        "bid": 80,
        "ask": 82,
        "quote_timestamp": AT.isoformat(),
    }
    rep_crude = validate_option_inputs(crude_cand)
    assert rep_crude["ok"] is True
    assert "INVALID_UNDERLYING" not in [e["code"] for e in rep_crude["errors"]]

    # BANKNIFTY option candidate rejected
    bank_cand = dict(sensex_cand, underlying="BANKNIFTY")
    rep_bank = validate_option_inputs(bank_cand)
    assert rep_bank["ok"] is False
    assert "INVALID_UNDERLYING" in [e["code"] for e in rep_bank["errors"]]


def test_futures_default_off_in_risk_allow_list():
    # By default, allowed_structures = ["LONG_CE", "LONG_PE"]
    config = _base_risk_config()
    intent = {
        "mode": "PAPER",
        "intent_purpose": "ENTRY",
        "instrument_type": "FUT",
        "underlying": "CRUDEOILMINI",
        "side": "BUY",
        "stop_loss": 6400,
        "margin_required": 15000,
        "lots": 1,
    }
    res = evaluate(intent, session=None, config=config, as_of=AT)
    assert res["passed"] is False
    assert "NOT_ON_ALLOW_LIST" in res["reasons"]


def test_futures_risk_gates_enforce_stop_margin_and_lot_cap():
    # Enable LONG_FUT in allowed_structures
    config = _base_risk_config(allowed_structures=["LONG_CE", "LONG_PE", "LONG_FUT", "SHORT_FUT"])

    # 1. Missing stop loss
    intent_no_stop = {
        "mode": "PAPER",
        "intent_purpose": "ENTRY",
        "instrument_type": "FUT",
        "underlying": "CRUDEOILMINI",
        "side": "BUY",
        "margin_required": 15000,
        "lots": 1,
    }
    res1 = evaluate(intent_no_stop, session=None, config=config, as_of=AT)
    assert "MISSING_FUTURES_STOP" in res1["reasons"]
    stop_gate = next(g for g in res1["gates"] if g["name"] == "futures_stop")
    assert stop_gate["state"] == "VETO"

    # 2. Unknown margin
    intent_no_margin = {
        "mode": "PAPER",
        "intent_purpose": "ENTRY",
        "instrument_type": "FUT",
        "underlying": "CRUDEOILMINI",
        "side": "BUY",
        "stop_loss": 6400,
        "lots": 1,
    }
    res2 = evaluate(intent_no_margin, session=None, config=config, as_of=AT)
    assert "UNKNOWN_MARGIN_REQUIRED" in res2["reasons"]
    margin_gate = next(g for g in res2["gates"] if g["name"] == "futures_margin")
    assert margin_gate["state"] == "VETO"

    # 3. Exceeds max lots
    intent_exceed_lots = {
        "mode": "PAPER",
        "intent_purpose": "ENTRY",
        "instrument_type": "FUT",
        "underlying": "CRUDEOILMINI",
        "side": "BUY",
        "stop_loss": 6400,
        "margin_required": 30000,
        "lots": 5,
    }
    res3 = evaluate(intent_exceed_lots, session=None, config=config, as_of=AT)
    assert "EXCEEDS_MAX_FUTURES_LOTS" in res3["reasons"]
    lots_gate = next(g for g in res3["gates"] if g["name"] == "futures_lots")
    assert lots_gate["state"] == "VETO"

    # 4. Valid futures passes futures-specific gates
    intent_valid = {
        "mode": "PAPER",
        "intent_purpose": "ENTRY",
        "instrument_type": "FUT",
        "underlying": "CRUDEOILMINI",
        "side": "BUY",
        "stop_loss": 6400,
        "margin_required": 15000,
        "lots": 1,
    }
    res4 = evaluate(intent_valid, session=None, config=config, as_of=AT)
    assert "MISSING_FUTURES_STOP" not in res4["reasons"]
    assert "UNKNOWN_MARGIN_REQUIRED" not in res4["reasons"]
    assert "EXCEEDS_MAX_FUTURES_LOTS" not in res4["reasons"]
    assert "NOT_ON_ALLOW_LIST" not in res4["reasons"]


def test_short_futures_allow_list():
    # Only LONG_FUT enabled -> SHORT_FUT vetoed by allow_list
    config_long_only = _base_risk_config(allowed_structures=["LONG_CE", "LONG_PE", "LONG_FUT"])
    intent_short = {
        "mode": "PAPER",
        "intent_purpose": "ENTRY",
        "instrument_type": "FUT",
        "underlying": "CRUDEOILMINI",
        "side": "SELL",
        "stop_loss": 6600,
        "margin_required": 15000,
        "lots": 1,
    }
    res = evaluate(intent_short, session=None, config=config_long_only, as_of=AT)
    assert "NOT_ON_ALLOW_LIST" in res["reasons"]

    # When SHORT_FUT enabled -> allow_list passes
    config_both = _base_risk_config(allowed_structures=["LONG_CE", "LONG_PE", "LONG_FUT", "SHORT_FUT"])
    res2 = evaluate(intent_short, session=None, config=config_both, as_of=AT)
    assert "NOT_ON_ALLOW_LIST" not in res2["reasons"]
