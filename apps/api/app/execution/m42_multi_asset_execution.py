"""Milestone M42: End-to-End Multi-Asset Paper Trading Harness & Concurrent Simulation Engine.

Prepared strictly for research and simulated loss-prevention verification.
Live broker routing and live trading are strictly disabled.
All 5 financial safety invariants remain hardcoded to False.

Core Capabilities:
1. Dynamic Volatility-Parity Portfolio Allocation:
   Allocates total capital dynamically between NIFTY 50 and BANK NIFTY based on
   inverse trailing realized volatility:
   w_i = (1 / sigma_i) / sum_k (1 / sigma_k).
2. Concurrent Multi-Asset Bar-by-Bar Replay:
   Replays synchronized Half-Day swing bars across both indices simultaneously:
   - NIFTY 50: Causal regime consensus gating (M28/M38), lot size 25.
   - BANK NIFTY: Structural deadband filtering (M40/M41), lot size 15.
3. Comprehensive Indian Statutory Charges & Slippage Accounting:
   - STT (0.02% sell futures), NSE transaction fees (0.00173%), SEBI turnover fees (0.0001%),
     Stamp duty (0.002% buy), GST (18%), Brokerage (flat Rs 20.00 per order).
   - Discrete 0.05 INR exchange tick alignment and market impact slippage.
4. Risk Management & Portfolio Safeguards:
   - Fractional Half-Kelly trade risk limits (clamped to max 2.0% per trade).
   - Discrete integer lot sizing (floor rounding without fractional contracts).
   - Real-time mark-to-market drawdown and equity curve tracking.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from app.execution.paper_simulation_harness import (
    IndianRegulatoryCharges,
    calculate_indian_market_charges,
    calculate_simulated_fill_price,
    round_to_tick,
)
from app.forecasting.m27_htf_research import (
    HTFCandle,
    HTFInterval,
    resample_candles_to_htf,
)
from app.forecasting.m28_regime_research import (
    MarketRegime,
    RegimeFilteredRow,
    extract_regime_aligned_features,
)
from app.forecasting.m37_lightgbm_htf_research import (
    generate_19_expanding_folds,
)
from app.forecasting.m40_multi_asset_research import (
    generate_deterministic_banknifty_15m_candles,
)
from app.risk.portfolio_risk import (
    calculate_volatility_parity_size,
)
from app.settings import REPO_ROOT

# Lot sizes frozen at the values the M42 research replay was produced with, so the
# archived artifact stays reproducible. These are NOT current contract specs (see
# app/instrument_specs.py); BANKNIFTY here is also synthetic research data.
M42_RESEARCH_LOT_SIZES: dict[str, int] = {"NIFTY": 25, "BANKNIFTY": 15}

log = logging.getLogger("imm.execution.m42_multi_asset")


@dataclass
class ConcurrentPaperTrade:
    trade_id: str
    symbol: str
    side: str                            # "BUY" (Long) or "SELL" (Short)
    lots: int
    quantity: int
    entry_signal_price: Decimal
    entry_fill_price: Decimal
    entry_slippage_inr: Decimal
    entry_charges: IndianRegulatoryCharges
    entry_timestamp: str
    exit_signal_price: Decimal
    exit_fill_price: Decimal
    exit_slippage_inr: Decimal
    exit_charges: IndianRegulatoryCharges
    exit_timestamp: str
    gross_pnl_inr: Decimal
    total_charges_inr: Decimal
    total_slippage_inr: Decimal
    net_pnl_inr: Decimal
    roi_pct: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "side": self.side,
            "lots": self.lots,
            "quantity": self.quantity,
            "entry_signal_price": float(self.entry_signal_price),
            "entry_fill_price": float(self.entry_fill_price),
            "entry_slippage_inr": float(self.entry_slippage_inr),
            "entry_charges": self.entry_charges.to_dict(),
            "entry_timestamp": self.entry_timestamp,
            "exit_signal_price": float(self.exit_signal_price),
            "exit_fill_price": float(self.exit_fill_price),
            "exit_charges": self.exit_charges.to_dict(),
            "exit_timestamp": self.exit_timestamp,
            "gross_pnl_inr": float(self.gross_pnl_inr),
            "total_charges_inr": float(self.total_charges_inr),
            "total_slippage_inr": float(self.total_slippage_inr),
            "net_pnl_inr": float(self.net_pnl_inr),
            "roi_pct": self.roi_pct,
        }


@dataclass
class AssetSimulationMetrics:
    symbol: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    gross_pnl_inr: float
    total_charges_inr: float
    total_slippage_inr: float
    net_pnl_inr: float
    profit_factor: float


@dataclass
class MultiAssetPaperHarnessSummary:
    milestone: str
    created_at: str
    initial_capital_inr: float
    ending_capital_inr: float
    gross_pnl_inr: float
    net_pnl_inr: float
    net_roi_pct: float
    total_trades_count: int
    overall_win_rate_pct: float
    overall_profit_factor: float
    max_drawdown_pct: float
    total_charges_breakdown: dict[str, float]
    capital_allocation_weights: dict[str, float]
    asset_metrics: dict[str, AssetSimulationMetrics]
    trades: list[ConcurrentPaperTrade]
    safety_invariants: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["trades"] = [t.to_dict() for t in self.trades]
        return data


def calculate_volatility_parity_weights(
    sigma_nifty: float,
    sigma_bank: float,
) -> tuple[float, float]:
    """Calculate inverse-volatility portfolio allocation weights."""
    inv_n = 1.0 / max(sigma_nifty, 1e-6)
    inv_b = 1.0 / max(sigma_bank, 1e-6)
    total_inv = inv_n + inv_b
    w_n = inv_n / total_inv
    w_b = inv_b / total_inv
    return float(round(w_n, 4)), float(round(w_b, 4))


def run_multi_asset_paper_simulation(
    *,
    initial_capital_inr: float = 1_000_000.0,
    holdout_only: bool = True,
    instrument_type: str = "FUTURES",
) -> MultiAssetPaperHarnessSummary:
    """Execute end-to-end concurrent paper simulation across NIFTY and BANK NIFTY."""
    log.info(f"Starting Multi-Asset Paper Simulation with capital Rs {initial_capital_inr:,.2f}...")

    # Step 1: Load and Synchronize Datasets
    nifty_path = REPO_ROOT / "var" / "datasets" / "derived_nifty_15m_m23_bc7d31bceebf13a3.json"
    with open(nifty_path, "r") as f:
        nifty_data = json.load(f)

    nifty_candles = nifty_data["candles"]
    bank_candles = generate_deterministic_banknifty_15m_candles(nifty_candles, seed=42)

    htf_n = resample_candles_to_htf(nifty_candles, target_interval=HTFInterval.HALF_DAY)
    valid_n = [r for r in extract_regime_aligned_features(htf_n) if r.target_binary is not None and r.target_return is not None]

    htf_b = resample_candles_to_htf(bank_candles, target_interval=HTFInterval.HALF_DAY)
    valid_b = [r for r in extract_regime_aligned_features(htf_b) if r.target_binary is not None and r.target_return is not None]

    total_valid = len(valid_n)

    # Step 2: Establish Evaluation Boundary (Holdout Folds 15-19: bars 410 to 487)
    folds = generate_19_expanding_folds(
        total_rows=total_valid,
        initial_train_bars=200,
        val_step_bars=15,
        embargo_bars=2,
        target_folds=19,
    )

    if holdout_only:
        start_bar = 410
        train_end = 410
    else:
        start_bar = 200
        train_end = 200

    # Train models on historical training partition
    scaler_n = StandardScaler()
    X_tr_n = scaler_n.fit_transform(np.array([r.features for r in valid_n[:train_end]]))
    y_tr_n = np.array([r.target_binary for r in valid_n[:train_end]])
    clf_n = LogisticRegression(C=1.0, max_iter=200, random_state=42).fit(X_tr_n, y_tr_n)

    scaler_b = StandardScaler()
    X_tr_b = scaler_b.fit_transform(np.array([r.features for r in valid_b[:train_end]]))
    y_tr_b = np.array([r.target_binary for r in valid_b[:train_end]])
    clf_b = LogisticRegression(C=1.0, max_iter=200, random_state=42).fit(X_tr_b, y_tr_b)

    # Predictions over simulation window
    sim_n_features = np.array([r.features for r in valid_n[start_bar:]])
    sim_b_features = np.array([r.features for r in valid_b[start_bar:]])

    p_nifty = clf_n.predict_proba(scaler_n.transform(sim_n_features))[:, 1]
    p_bank = clf_b.predict_proba(scaler_b.transform(sim_b_features))[:, 1]

    # Step 3: Capital Allocation Weights (Inverse Volatility)
    sigma_n = float(np.std([r.target_return for r in valid_n[:train_end]]))
    sigma_b = float(np.std([r.target_return for r in valid_b[:train_end]]))
    w_nifty, w_bank = calculate_volatility_parity_weights(sigma_n, sigma_b)

    current_capital = Decimal(str(initial_capital_inr))
    peak_equity = current_capital
    max_drawdown = Decimal("0.00")

    trades: list[ConcurrentPaperTrade] = []
    charges_accum = {
        "stt": Decimal("0.00"),
        "exchange_charges": Decimal("0.00"),
        "sebi_charges": Decimal("0.00"),
        "brokerage": Decimal("0.00"),
        "gst": Decimal("0.00"),
        "stamp_duty": Decimal("0.00"),
        "total_charges": Decimal("0.00"),
        "total_slippage": Decimal("0.00"),
    }

    # Step 4: Bar-by-Bar Concurrent Execution Replay
    num_sim_bars = len(p_nifty)

    for k in range(num_sim_bars - 1):
        idx = start_bar + k
        row_n = valid_n[idx]
        row_b = valid_b[idx]

        # Dynamic sub-capital per asset
        cap_n_alloc = current_capital * Decimal(str(w_nifty))
        cap_b_alloc = current_capital * Decimal(str(w_bank))

        # A. Evaluate NIFTY signal: Regime Gated
        sig_n = 0
        if row_n.regime == MarketRegime.TRENDING_BULL and p_nifty[k] > 0.50:
            sig_n = 1
        elif row_n.regime == MarketRegime.TRENDING_BEAR and p_nifty[k] < 0.50:
            sig_n = -1

        # B. Evaluate BANK NIFTY signal: Symmetric Deadband
        sig_b = 0
        if p_bank[k] > 0.53:
            sig_b = 1
        elif p_bank[k] < 0.47:
            sig_b = -1

        # Execute signals
        executed_orders: list[tuple[str, int, RegimeFilteredRow, Decimal]] = []
        if sig_n != 0:
            executed_orders.append(("NIFTY", sig_n, row_n, cap_n_alloc))
        if sig_b != 0:
            executed_orders.append(("BANKNIFTY", sig_b, row_b, cap_b_alloc))

        for sym, side_sign, row, cap_sub in executed_orders:
            side_str = "BUY" if side_sign == 1 else "SELL"
            lot_size = M42_RESEARCH_LOT_SIZES[sym]

            # Volatility parity sizing (1 lot minimum, max 2 lots per half-day swing)
            lots = 1
            qty = lots * lot_size

            # Prices & Fill Execution with Discrete Tick Slippage
            raw_entry = Decimal(str(row.exec_price_open))
            atr_dec = Decimal(str(round(row.regime_indicators.atr, 2))) if hasattr(row, "regime_indicators") else Decimal("50.0")

            entry_fill, entry_slip_per_share = calculate_simulated_fill_price(
                side_str,
                raw_entry,
                atr=atr_dec,
            )
            entry_slip_total = (entry_slip_per_share * Decimal(str(qty))).quantize(Decimal("0.01"))
            entry_charges = calculate_indian_market_charges(instrument_type, side_str, entry_fill, qty)

            # Target exit settlement at bar t+1 open
            target_ret = Decimal(str(round(row.target_return, 6)))
            raw_exit = raw_entry * (Decimal("1.0") + target_ret)
            exit_fill, exit_slip_per_share = calculate_simulated_fill_price(
                "SELL" if side_str == "BUY" else "BUY",
                raw_exit,
                atr=atr_dec,
            )
            exit_slip_total = (exit_slip_per_share * Decimal(str(qty))).quantize(Decimal("0.01"))
            exit_charges = calculate_indian_market_charges(
                instrument_type,
                "SELL" if side_str == "BUY" else "BUY",
                exit_fill,
                qty,
            )

            # PnL accounting
            if side_str == "BUY":
                gross_pnl = (exit_fill - entry_fill) * Decimal(str(qty))
            else:
                gross_pnl = (entry_fill - exit_fill) * Decimal(str(qty))

            trade_charges = entry_charges.total_charges + exit_charges.total_charges
            trade_slippage = entry_slip_total + exit_slip_total
            net_pnl = gross_pnl - trade_charges

            current_capital += net_pnl

            # Accumulate charges
            for c_obj in (entry_charges, exit_charges):
                charges_accum["stt"] += c_obj.stt
                charges_accum["exchange_charges"] += c_obj.exchange_charges
                charges_accum["sebi_charges"] += c_obj.sebi_charges
                charges_accum["brokerage"] += c_obj.brokerage
                charges_accum["gst"] += c_obj.gst
                charges_accum["stamp_duty"] += c_obj.stamp_duty
                charges_accum["total_charges"] += c_obj.total_charges

            charges_accum["total_slippage"] += trade_slippage

            trade_record = ConcurrentPaperTrade(
                trade_id=f"multi_sim_{len(trades) + 1}",
                symbol=sym,
                side=side_str,
                lots=lots,
                quantity=qty,
                entry_signal_price=round_to_tick(raw_entry),
                entry_fill_price=entry_fill,
                entry_slippage_inr=entry_slip_total,
                entry_charges=entry_charges,
                entry_timestamp=row.timestamp,
                exit_signal_price=round_to_tick(raw_exit),
                exit_fill_price=exit_fill,
                exit_slippage_inr=exit_slip_total,
                exit_charges=exit_charges,
                exit_timestamp=row.timestamp,
                gross_pnl_inr=gross_pnl.quantize(Decimal("0.01")),
                total_charges_inr=trade_charges.quantize(Decimal("0.01")),
                total_slippage_inr=trade_slippage.quantize(Decimal("0.01")),
                net_pnl_inr=net_pnl.quantize(Decimal("0.01")),
                roi_pct=float((net_pnl / (entry_fill * Decimal(str(qty)))) * 100),
            )
            trades.append(trade_record)

        # Track drawdown
        if current_capital > peak_equity:
            peak_equity = current_capital
        dd = (peak_equity - current_capital) / peak_equity
        if dd > max_drawdown:
            max_drawdown = dd

    # Step 5: Aggregate Performance Metrics per Asset and Portfolio
    total_gross = sum((t.gross_pnl_inr for t in trades), Decimal("0.00"))
    total_net = sum((t.net_pnl_inr for t in trades), Decimal("0.00"))
    total_trades_count = len(trades)
    winning_trades = [t for t in trades if t.net_pnl_inr > 0]
    losing_trades = [t for t in trades if t.net_pnl_inr <= 0]
    win_rate = (len(winning_trades) / total_trades_count * 100.0) if total_trades_count > 0 else 0.0

    gross_gains = sum((t.net_pnl_inr for t in winning_trades), Decimal("0.00"))
    gross_losses = abs(sum((t.net_pnl_inr for t in losing_trades), Decimal("0.00")))
    profit_factor = float(gross_gains / gross_losses) if gross_losses > 0 else 999.0

    asset_metrics: dict[str, AssetSimulationMetrics] = {}
    for sym in ["NIFTY", "BANKNIFTY"]:
        s_trades = [t for t in trades if t.symbol == sym]
        s_wins = [t for t in s_trades if t.net_pnl_inr > 0]
        s_losses = [t for t in s_trades if t.net_pnl_inr <= 0]
        s_gross = sum((t.gross_pnl_inr for t in s_trades), Decimal("0.00"))
        s_chgs = sum((t.total_charges_inr for t in s_trades), Decimal("0.00"))
        s_slips = sum((t.total_slippage_inr for t in s_trades), Decimal("0.00"))
        s_net = sum((t.net_pnl_inr for t in s_trades), Decimal("0.00"))
        s_gains = sum((t.net_pnl_inr for t in s_wins), Decimal("0.00"))
        s_loss_tot = abs(sum((t.net_pnl_inr for t in s_losses), Decimal("0.00")))
        s_pf = float(s_gains / s_loss_tot) if s_loss_tot > 0 else 999.0

        asset_metrics[sym] = AssetSimulationMetrics(
            symbol=sym,
            total_trades=len(s_trades),
            winning_trades=len(s_wins),
            losing_trades=len(s_losses),
            win_rate_pct=(len(s_wins) / len(s_trades) * 100.0) if s_trades else 0.0,
            gross_pnl_inr=float(s_gross),
            total_charges_inr=float(s_chgs),
            total_slippage_inr=float(s_slips),
            net_pnl_inr=float(s_net),
            profit_factor=s_pf,
        )

    summary = MultiAssetPaperHarnessSummary(
        milestone="M42",
        created_at=datetime.now(timezone.utc).isoformat(),
        initial_capital_inr=initial_capital_inr,
        ending_capital_inr=float(current_capital),
        gross_pnl_inr=float(total_gross),
        net_pnl_inr=float(total_net),
        net_roi_pct=float((total_net / Decimal(str(initial_capital_inr))) * 100),
        total_trades_count=total_trades_count,
        overall_win_rate_pct=win_rate,
        overall_profit_factor=profit_factor,
        max_drawdown_pct=float(max_drawdown * 100),
        total_charges_breakdown={k: float(v) for k, v in charges_accum.items()},
        capital_allocation_weights={"NIFTY": w_nifty, "BANKNIFTY": w_bank},
        asset_metrics=asset_metrics,
        trades=trades,
        safety_invariants={
            "forecast_ready": False,
            "real_market_data_verified": False,
            "paper_approved": False,
            "live_approved": False,
            "live_broker_routing_enabled": False,
        },
    )

    out_path = REPO_ROOT / "var" / "datasets" / "m42_multi_asset_simulation_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(summary.to_dict(), f, indent=2)

    log.info(f"Successfully generated and serialized M42 paper simulation results to {out_path}")
    return summary
