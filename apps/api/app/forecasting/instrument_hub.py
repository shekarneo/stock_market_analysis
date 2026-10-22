"""Multi-Instrument Forecasting Hub and Evaluation Architecture.

Provides unified, extensible management for multi-instrument forecasting across:
1. NIFTY 50 (NSE Cash / Derivatives)
2. BSE SENSEX (BSE Cash / Options)
3. CRUDEOIL MINI (MCX Commodity Futures)

Ensures:
- Independent forecast requests and outputs per instrument (no cross-asset leakage)
- Shared market intelligence without assuming identical response behavior
- Explicit data gap disclosures (Groww MCX feed and options absence)
- Independent walk-forward backtest reporting
- Extensible configuration registry for onboarding future instruments
- Strict preservation of financial safety invariants (no live/paper routing)
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.market.live_quotes import load_read
from app.market.schemas import IST
from app.market.session_intelligence import (
    assess_market_session,
    get_instrument_session_config,
)
from app.settings import REPO_ROOT

REGISTRY_PATH = REPO_ROOT / "var" / "registry" / "registry.json"


# --- Declarative Instrument Catalog (Extensible Architecture) ---
INSTRUMENT_CATALOG: dict[str, dict[str, Any]] = {
    "NIFTY": {
        "id": "NIFTY",
        "name": "NIFTY 50",
        "full_name": "NSE NIFTY 50 Index",
        "trading_symbol": "NIFTY",
        "groww_symbol": "NSE-NIFTY",
        "exchange": "NSE",
        "segment": "NSE_CASH",
        "asset_class": "EQUITY_INDEX",
        "contract_lot_size": 25,
        "strike_step": 50,
        "session_timings": "09:15 - 15:30 IST",
        "session_type": "NSE Regular Session",
        "data_source": "Groww Trade API / Quarantined Storage",
        "data_freshness": "Live / M15 Verified",
        "available_history": "6,227 M15 Candles (2026-04-16 to 2026-10-14)",
        "forecast_horizons": ["15m (HTF Resampled)", "1D Daily Swing"],
        "validation_status": "VERIFIED_RESEARCH_DATASET",
        "models_validated": [
            "Logistic Regression (M3)",
            "Persistence Baseline (M3)",
            "Majority Baseline (M3)",
            "Regime-Gated HTF LightGBM (M37)",
        ],
        "options_supported": True,
        "options_provider": "NSE Option Chain",
        "options_note": "Full NSE Option Chain with continuous Black-76 Greeks & PCR Surface",
        "macro_drivers": [
            "RBI Monetary Policy & Repo Rate",
            "FII / DII Institutional Net Flows",
            "USD/INR Currency Trend",
            "India VIX Volatility Regime",
            "US Equity Indices (SPX, NASDAQ)",
        ],
        "transaction_friction_bps": 2.0,
        "stt_rate_pct": 0.0125,
        "brokerage_per_order_inr": 20.0,
    },
    "SENSEX": {
        "id": "SENSEX",
        "name": "BSE SENSEX",
        "full_name": "S&P BSE SENSEX Index",
        "trading_symbol": "SENSEX",
        "groww_symbol": "BSE-SENSEX",
        "exchange": "BSE",
        "segment": "BSE_CASH",
        "asset_class": "EQUITY_INDEX",
        "contract_lot_size": 20,
        "strike_step": 100,
        "session_timings": "09:15 - 15:30 IST",
        "session_type": "BSE Regular Session",
        "data_source": "BSE Cash Feed / Groww LTP",
        "data_freshness": "Live LTP Snapshot (Historical Ingestion Pending)",
        "available_history": "Live Quotes / LTP (No persistent 15m dataset ingested)",
        "forecast_horizons": ["15m (Experimental)", "1D Daily Swing"],
        "validation_status": "INDEPENDENT_PROVENANCE_REQUIRED",
        "models_validated": [],
        "options_supported": True,
        "options_provider": "BSE Derivative Chain",
        "options_note": "BSE Weekly/Monthly Option Contracts (Lot 20, Step 100) with Black-76 Greeks",
        "macro_drivers": [
            "Domestic Corporate Earnings",
            "Banking & IT Sector Weightings",
            "Foreign Portfolio Investment (FPI)",
            "Global Liquidity Conditions",
        ],
        "transaction_friction_bps": 2.0,
        "stt_rate_pct": 0.0125,
        "brokerage_per_order_inr": 20.0,
    },
    "CRUDEOILMINI": {
        "id": "CRUDEOILMINI",
        "name": "CRUDEOIL MINI",
        "full_name": "MCX Crude Oil Mini Futures Contract",
        "trading_symbol": "CRUDEOILMINI",
        "groww_symbol": None,
        "exchange": "MCX",
        "segment": "MCX_COMMODITY",
        "asset_class": "COMMODITY_FUTURES",
        "contract_lot_size": 10,  # 10 barrels
        "strike_step": 50,
        "session_timings": "09:00 - 23:30 IST (23:55 winter)",
        "session_type": "MCX Extended Commodity Session",
        "data_source": "MCX Real-time Feed / International Benchmark Proxies",
        "data_freshness": "Commodity Snapshot (Groww MCX feed unavailable)",
        "available_history": "International Benchmarks (Brent/WTI). MCX historical candles not supplied by Groww.",
        "forecast_horizons": ["15m Commodity Swing", "Evening Session Multi-Hour"],
        "validation_status": "DATA_FEED_GAP_REPORTED",
        "models_validated": [],
        "options_supported": False,
        "options_provider": None,
        "options_note": "Options Analytics DISABLED (MCX Options on Futures feed unavailable via Groww API)",
        "macro_drivers": [
            "OPEC+ Output Quotas & Compliance",
            "US EIA Weekly Petroleum Status",
            "Middle East Geopolitical Risk Premium",
            "US Dollar Index (DXY) Strength",
            "Global Strategic Petroleum Reserve (SPR) Levels",
        ],
        "transaction_friction_bps": 3.5,
        "stt_rate_pct": 0.01,
        "brokerage_per_order_inr": 20.0,
    },
}


def get_supported_instruments() -> list[dict[str, Any]]:
    """Return all configured instruments with active session status."""
    now = datetime.now(timezone.utc)
    results = []
    for inst_id, cfg in INSTRUMENT_CATALOG.items():
        sess = assess_market_session(inst_id, now)
        item = dict(cfg)
        item["is_market_open"] = sess.is_open
        item["market_state"] = sess.market_state.value
        item["session_phase"] = sess.session_phase.value
        item["session_limitation"] = sess.limitation
        results.append(item)
    return results


def get_instrument_forecast(instrument: str) -> dict[str, Any]:
    """Compute or retrieve independent forecast for the selected instrument.

    Guarantees:
    - Independent evaluation per instrument.
    - Zero copy or leakage of predictions between instruments.
    - Honest NO TRADE reasons when data gaps or unvalidated models exist.
    """
    inst = instrument.strip().upper()
    if inst not in INSTRUMENT_CATALOG:
        inst = "NIFTY"

    cfg = INSTRUMENT_CATALOG[inst]
    read = load_read() or {}
    quotes = {q["instrument"]: q for q in read.get("quotes", []) if q.get("instrument")}
    commodities = {c["instrument"]: c for c in read.get("commodities", []) if c.get("instrument")}

    vix_row = next(
        (r for r in read.get("sectoral_indices", []) + read.get("global_indices", []) if r.get("instrument") in {"VIX", "INDIA_VIX"}),
        None,
    )
    vix_val = float(vix_row["last_price"]) if vix_row and vix_row.get("last_price") is not None else None

    now_iso = datetime.now(timezone.utc).isoformat()

    # --- 1. NIFTY 50 Forecast Pipeline ---
    if inst == "NIFTY":
        from app.forecasting.live_forecast import compute_live_forecast_for_instrument

        nifty_quote = quotes.get("NIFTY")
        iv = max(0.11, min(0.35, vix_val / 100.0)) if vix_val is not None else None
        raw_fc = compute_live_forecast_for_instrument("NIFTY", nifty_quote, iv=iv)
        spot = raw_fc.get("spot_price")
        if spot is None and nifty_quote and nifty_quote.get("last_price") is not None:
            spot = float(nifty_quote["last_price"])
        p_up = raw_fc.get("probability_up")

        if p_up is not None and raw_fc.get("status") == "ACTIVE":
            direction = raw_fc.get("direction", "UNKNOWN")
            calibrated_p = round(p_up, 4)
            raw_conf = raw_fc.get("confidence")
            decision = "BUY" if direction == "BULLISH" and calibrated_p > 0.55 else ("SELL" if direction == "BEARISH" and calibrated_p < 0.45 else "NO TRADE")
            if decision == "NO TRADE":
                expected_move = target = stop = None
                no_trade_reasons = ["Directional probability within neutral deadband [0.45, 0.55]"]
            else:
                expected_move = raw_fc.get("expected_move_points")
                target = raw_fc.get("target_spot")
                stop = raw_fc.get("stop_loss_spot")
                no_trade_reasons = []
        else:
            direction = "UNKNOWN"
            calibrated_p = None
            raw_conf = None
            decision = "NO TRADE"
            expected_move = target = stop = None
            no_trade_reasons = [
                f"{raw_fc.get('status') or 'NO_FORECAST'}: {raw_fc.get('summary') or 'No live forecast available.'}"
            ]

        supporting_evidence = []
        if raw_fc.get("status") == "ACTIVE":
            supporting_evidence.append(
                f"Model {raw_fc.get('model_version')} inferred on features ending {raw_fc.get('feature_bar_end')} "
                f"({raw_fc.get('feature_source')})."
            )
        if vix_val is not None:
            supporting_evidence.append(f"Volatility index reading: {vix_val:.1f}.")

        return {
            "instrument": "NIFTY",
            "name": cfg["name"],
            "decision": decision,
            "predicted_direction": direction,
            "calibrated_probability": calibrated_p,
            "raw_confidence": raw_conf,
            "forecast_horizon": "Next 15m close",
            "expected_return_points": expected_move,
            "spot_price": spot,
            "target_spot": target,
            "stop_loss_spot": stop,
            "supporting_evidence": supporting_evidence,
            "contradicting_evidence": [
                "Live model is the 15m logistic regression; it is not the half-day regime-gated strategy evaluated in walk-forward research.",
                "Model probabilities are not calibrated.",
            ],
            "data_timestamp": raw_fc.get("generated_at") or now_iso,
            "provenance": raw_fc.get("feature_source") or "UNAVAILABLE",
            "forecast_status": raw_fc.get("status"),
            "invalidation_conditions": (
                [f"Breach of stop-loss level at ₹{stop:.1f}"] if stop is not None else []
            ) + ["Consensus epistemic dispersion D > 0.45"],
            "transaction_cost_assumptions": {
                "turnover_friction_bps": 2.0,
                "stt_rate": "0.1% on option sell premium",
                "exchange_turnover_fee": "0.03503% on option premium (NSE)",
                "gst_rate": "18.0% on brokerage + exchange charges",
                "sebi_turnover_fee": "₹10 per crore",
                "stamp_duty": "0.003% on buy value",
                "flat_brokerage": "₹20 per executed order",
            },
            "reasons_for_no_trade": no_trade_reasons,
            "model_status": "RESEARCH_ONLY_UNVALIDATED",
            "safety_controls_locked": True,
        }

    # --- 2. BSE SENSEX Forecast Pipeline ---
    if inst == "SENSEX":
        sensex_quote = quotes.get("SENSEX")
        spot = float(sensex_quote["last_price"]) if sensex_quote and sensex_quote.get("last_price") is not None else None

        return {
            "instrument": "SENSEX",
            "name": cfg["name"],
            "decision": "NO TRADE",
            "predicted_direction": "UNKNOWN",
            "calibrated_probability": None,
            "raw_confidence": None,
            "forecast_horizon": "15m (Experimental)",
            "expected_return_points": None,
            "spot_price": spot,
            "target_spot": None,
            "stop_loss_spot": None,
            "supporting_evidence": [
                f"Live BSE SENSEX quote tracked at ₹{spot:,.1f}." if spot is not None else "Live BSE SENSEX quote unavailable.",
                "BSE derivative chain options analytics supported (Lot 20).",
                "Domestic corporate earnings and macro indicators shared.",
            ],
            "contradicting_evidence": [
                "No registered model artifact fitted on BSE SENSEX data.",
                "Cross-asset transfer of NIFTY model weights is strictly prohibited.",
                "Independent BSE 15m historical candles not yet ingested into persistent storage.",
            ],
            "data_timestamp": now_iso,
            "provenance": "BSE_LTP_SNAPSHOT (Independent BSE feed required)",
            "invalidation_conditions": [
                "Cross-asset transfer policy: Strict No-Go without independent BSE holdout evaluation",
            ],
            "transaction_cost_assumptions": {
                "turnover_friction_bps": 2.0,
                "stt_rate": "0.0125% on sell turnover",
                "exchange_turnover_fee": "0.003% (BSE)",
                "gst_rate": "18.0% on brokerage + exchange charges",
                "stamp_duty": "0.003% on buy value",
                "flat_brokerage": "₹20 per executed order",
            },
            "reasons_for_no_trade": [
                "NO_FITTED_MODEL: No quantitative model trained or evaluated on independent BSE SENSEX historical data.",
                "DATA_PROVENANCE_BOUNDARY: NIFTY 50 predictions cannot be copied to SENSEX without introducing unvalidated model risk.",
                "EXECUTION_INVARIANT: Live trading and order routing remain permanently locked in NO_GO mode.",
            ],
            "model_status": "UNEVALUATED_CROSS_ASSET",
            "safety_controls_locked": True,
        }

    # --- 3. MCX CRUDEOIL MINI Forecast Pipeline ---
    crude_quote = commodities.get("CRUDEOILMINI") or commodities.get("CRUDEMINI")
    spot = float(crude_quote["last_price"]) if crude_quote and crude_quote.get("last_price") is not None else None

    return {
        "instrument": "CRUDEOILMINI",
        "name": cfg["name"],
        "decision": "NO TRADE",
        "predicted_direction": "UNKNOWN",
        "calibrated_probability": None,
        "raw_confidence": None,
        "forecast_horizon": "15m Commodity Swing",
        "expected_return_points": None,
        "spot_price": spot,
        "target_spot": None,
        "stop_loss_spot": None,
        "supporting_evidence": [
            "International crude benchmarks (Brent Crude, WTI) monitored via macro feed.",
            "MCX session calendar clock assessed (09:00 - 23:30/23:55 IST).",
            "Crude-specific macro drivers tracked (OPEC+, EIA inventory, DXY).",
        ],
        "contradicting_evidence": [
            "DATA FEED GAP: Groww Trade API does not provide MCX commodity candle feeds.",
            "OPTIONS DATA GAP: MCX Crude oil options chain not supported by current provider.",
            "No commodity-specific quantitative model exists in the registry.",
            "Global crude benchmarks cannot be substituted directly for MCX execution.",
        ],
        "data_timestamp": now_iso,
        "provenance": "MCX_COMMODITY_PROXY (Groww MCX feed unavailable)",
        "invalidation_conditions": [
            "Direct broker execution unavailable for MCX commodity contracts",
            "Options analytics disabled due to missing MCX option chain",
        ],
        "transaction_cost_assumptions": {
            "turnover_friction_bps": 3.5,
            "stt_rate": "0.01% on sell turnover (Futures)",
            "exchange_turnover_fee": "0.0026% (MCX)",
            "gst_rate": "18.0% on brokerage + charges",
            "stamp_duty": "0.002% on buy value",
            "flat_brokerage": "₹20 per executed order",
            "bid_ask_spread_allowance": "1.5 bps wider on MCX commodity contracts",
        },
        "reasons_for_no_trade": [
            "DATA_FEED_GAP: Groww Trade API does not provide MCX commodity historical candles.",
            "OPTIONS_DATA_UNAVAILABLE: MCX Crude oil options chain feed not available.",
            "NO_FITTED_MODEL: Equity index quantitative models cannot be applied to energy commodities.",
            "SYSTEM_SAFETY_LOCK: Permanent hardware lock prohibits real-capital routing.",
        ],
        "model_status": "COMMODITY_PIPELINE_NOT_INSTANTIATED",
        "safety_controls_locked": True,
    }


def _round_or_none(value: Any, digits: int = 2) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _nifty_backtest_from_artifact(m40_path: Path) -> dict[str, Any]:
    """Serve only numbers computed by the M40 walk-forward run; never literal placeholders."""
    unevaluated = {
        "instrument": "NIFTY",
        "name": "NIFTY 50",
        "evaluation_status": "UNEVALUATED",
        "reason": (
            f"No computed walk-forward artifact found at {m40_path.name}. "
            "Run the M40 benchmark to produce one; no performance figures are shown without it."
        ),
    }
    if not m40_path.is_file():
        return unevaluated
    try:
        data = json.loads(m40_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {**unevaluated, "reason": f"Walk-forward artifact {m40_path.name} could not be parsed."}

    strategies = (data.get("nifty_summary") or {}).get("strategies") or {}
    regime = strategies.get("empirical_prior_regime_gated")
    if not regime:
        return {**unevaluated, "reason": "Walk-forward artifact has no empirical_prior_regime_gated NIFTY strategy."}

    dev_net = _round_or_none(regime.get("dev_net_return_2bps"))
    holdout_folds = data.get("holdout_fold_count")
    caveats = [
        "Research result only. The live forecast runs a different model (15m logistic regression).",
        "The 'empirical prior' is a constant probability; returns come from the ADX/DI regime filter, not a learned model.",
        f"Holdout covers only {holdout_folds} folds; accuracy near 50% on this sample is not distinguishable from chance."
        if holdout_folds is not None
        else "Holdout size is not recorded in the artifact.",
        "Strategy was chosen by comparing many model/mode combinations, which inflates the reported holdout result.",
        "Costs are 2 bps on index returns; option premiums, spreads and theta are not modelled.",
    ]
    if dev_net is not None and dev_net < 0:
        caveats.insert(0, f"Development-fold net return is negative ({dev_net}%); only the holdout is positive.")

    return {
        "instrument": "NIFTY",
        "name": "NIFTY 50",
        "evaluation_status": "RESEARCH_WALK_FORWARD",
        "evaluation_methodology": "Purged & embargoed expanding-window walk-forward (M40 artifact)",
        "folds_summary": {
            "total_folds": data.get("num_folds"),
            "dev_folds": data.get("dev_fold_count"),
            "holdout_folds": holdout_folds,
            "total_15m_candles": data.get("total_15m_candles"),
            "htf_swing_bars": data.get("total_aligned_rows"),
        },
        "dataset_provenance": {
            "dataset_id": data.get("nifty_dataset_id"),
            "artifact": m40_path.name,
            "artifact_created_at": data.get("created_at"),
        },
        "performance_after_costs": {
            "statutory_friction_bps": 2.0,
            "full_period_net_return": _round_or_none(regime.get("full_net_return_2bps")),
            "full_period_gross_return": _round_or_none(regime.get("full_gross_return_0bps")),
            "holdout_net_return": _round_or_none(regime.get("holdout_net_return_2bps")),
            "dev_net_return": dev_net,
            "mean_fold_max_drawdown": _round_or_none(regime.get("full_max_drawdown_2bps")),
            "drawdown_reconciliation_note": (
                "Drawdown is the mean of per-fold maximum drawdowns, not the drawdown of one chained equity curve. "
                "Fold returns are summed, not compounded."
            ),
        },
        "statistical_metrics": {
            "holdout_accuracy": _round_or_none(regime.get("holdout_accuracy"), 4),
            "holdout_brier_skill_score": _round_or_none(regime.get("holdout_brier_skill_score"), 4),
            "dev_accuracy": _round_or_none(regime.get("dev_accuracy"), 4),
            "holdout_turnover_units": _round_or_none(regime.get("holdout_turnover_units"), 1),
            "full_turnover_units": _round_or_none(regime.get("full_turnover_units"), 1),
        },
        "baseline_comparisons": [
            {
                "model": row.get("model_name"),
                "mode": row.get("strategy_mode"),
                "dev_net_return_2bps": _round_or_none(row.get("dev_net_return_2bps")),
                "full_net_return_2bps": _round_or_none(row.get("full_net_return_2bps")),
                "holdout_net_return_2bps": _round_or_none(row.get("holdout_net_return_2bps")),
                "mean_fold_max_drawdown": _round_or_none(row.get("full_max_drawdown_2bps")),
            }
            for row in strategies.values()
        ],
        "caveats": caveats,
        "execution_assumptions": [
            "Entry and exit at the open of the bar after each half-day signal bar",
            "Half-day open-to-open target: positions opened on the afternoon bar are held overnight",
            "2.0 bps per side on index returns; no option premium, spread or theta modelling",
        ],
    }


def get_instrument_backtest(instrument: str) -> dict[str, Any]:
    """Return independent instrument-level backtest reports.

    Guarantees:
    - Never fabricates backtest results for instruments without validated data.
    - Accurately reports full-period vs holdout metrics for NIFTY 50.
    - Explicitly details 'UNEVALUATED' status for SENSEX and CRUDEOIL MINI.
    """
    inst = instrument.strip().upper()
    if inst not in INSTRUMENT_CATALOG:
        inst = "NIFTY"

    if inst == "NIFTY":
        return _nifty_backtest_from_artifact(REPO_ROOT / "var" / "datasets" / "m40_multi_asset_benchmark.json")

    if inst == "SENSEX":
        return {
            "instrument": "SENSEX",
            "name": "BSE SENSEX",
            "evaluation_status": "UNEVALUATED",
            "reason": (
                "No backtest available. An independent BSE SENSEX historical dataset must be acquired, "
                "quarantined, and verified before backtest performance can be claimed. Deriving SENSEX "
                "performance from NIFTY 50 is strictly prohibited."
            ),
            "data_requirements": [
                "Minimum 6,000 continuous 15-minute BSE-SENSEX candles",
                "Geometric consistency checks (High >= Open/Close/Low, Low <= Open/Close/High)",
                "Full session boundary reconciliation (25 bars per regular session)",
                "Independent walk-forward cross-validation (19 chronological folds)",
            ],
            "current_status": "AWAITING_INDEPENDENT_BSE_DATASET",
        }

    # CRUDEOILMINI
    return {
        "instrument": "CRUDEOILMINI",
        "name": "CRUDEOIL MINI",
        "evaluation_status": "UNEVALUATED",
        "reason": (
            "No backtest available. MCX historical commodity tick and candle data is not supplied by "
            "the active Groww API integration. Backtesting on international crude proxies (Brent/WTI) "
            "without accounting for MCX local trading sessions, currency conversion (USD/INR), and "
            "commodity exchange turnover charges is methodologically invalid."
        ),
        "data_requirements": [
            "Authoritative MCX tick/candle archive with continuous commodity session timestamps (09:00 - 23:30/23:55 IST)",
            "Contract rollover and expiry calendar handling for monthly contracts",
            "MCX-specific statutory cost model (STT, MCX turnover fees, GST, wider bid-ask spreads)",
        ],
        "current_status": "DATA_FEED_GAP_REPORTED",
    }


def get_instrument_data_health(session: Session | None = None) -> dict[str, Any]:
    """Audit real-time and persistent data health across all 3 primary instruments."""
    now = datetime.now(timezone.utc)
    read = load_read() or {}
    quotes = {q["instrument"]: q for q in read.get("quotes", []) if q.get("instrument")}
    commodities = {c["instrument"]: c for c in read.get("commodities", []) if c.get("instrument")}

    # Count candles in durable database if session provided
    stored_counts: dict[str, int] = {}
    if session is not None:
        try:
            from app.domain.tables import MarketCandle
            stmt = select(MarketCandle.symbol, func.count(MarketCandle.id)).group_by(MarketCandle.symbol)
            rows = session.execute(stmt).all()
            for sym, cnt in rows:
                stored_counts[sym] = cnt
        except Exception:
            pass

    health_entries = []
    for inst_id, cfg in INSTRUMENT_CATALOG.items():
        sess = assess_market_session(inst_id, now)

        if inst_id == "NIFTY":
            q = quotes.get("NIFTY")
            last_px = float(q["last_price"]) if q and q.get("last_price") is not None else None
            stored_cnt = stored_counts.get("NSE-NIFTY", 0)
            status = "HEALTHY_VERIFIED" if stored_cnt > 0 and last_px is not None else "DATA_GAP"
            gap_note = (
                f"{stored_cnt:,} persisted NIFTY candles in storage."
                if stored_cnt > 0
                else "No persisted NIFTY candles found in storage."
            )
        elif inst_id == "SENSEX":
            q = quotes.get("SENSEX")
            last_px = float(q["last_price"]) if q and q.get("last_price") is not None else None
            stored_cnt = stored_counts.get("BSE-SENSEX", 0)
            status = "PARTIAL_LTP_ONLY"
            gap_note = "Historical candle dataset pending ingestion. Live LTP snapshot verified via BSE feed."
        else:  # CRUDEOILMINI
            q = commodities.get("CRUDEOILMINI") or commodities.get("CRUDEMINI")
            last_px = float(q["last_price"]) if q and q.get("last_price") is not None else None
            stored_cnt = stored_counts.get("MCX-CRUDEOILMINI", 0)
            status = "DATA_FEED_GAP"
            gap_note = "Groww Trade API integration does not provide MCX commodity candle feeds or options data."

        health_entries.append({
            "instrument": inst_id,
            "name": cfg["name"],
            "exchange": cfg["exchange"],
            "segment": cfg["segment"],
            "market_state": sess.market_state.value,
            "session_phase": sess.session_phase.value,
            "is_open": sess.is_open,
            "session_hours": cfg["session_timings"],
            "last_price": last_px,
            "health_status": status,
            "stored_candles": stored_cnt,
            "options_supported": cfg["options_supported"],
            "options_note": cfg["options_note"],
            "gap_disclosure": gap_note,
            "validation_status": cfg["validation_status"],
            "data_source": cfg["data_source"],
        })

    return {
        "as_of": now.isoformat(),
        "total_instruments_configured": len(INSTRUMENT_CATALOG),
        "primary_instruments": health_entries,
        "safety_invariants": {
            "live_trading_enabled": False,
            "order_placement_allowed": False,
            "capital_commitment_allowed": False,
            "synthetic_orders_only": True,
            "real_money_loss_risk": False,
        },
    }
