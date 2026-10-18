"""Milestone M24: Independent Strategy Accounting, Execution Simulation, and Backtest Integrity Audit.

Provides:
1. Target execution timing and availability contracts for C2C, O2O, O2C_1B, O2C_2B.
2. Independent reference accounting engine for positions, turnover, transaction costs, and compounded equity.
3. Verification fixtures for 10 specific trading scenarios with exact hand-calculated answers.
4. Independent reproduction engine for M23 benchmark results on the persisted 1-year NIFTY dataset.
5. Backtest leakage audits covering features, normalization, thresholds, fold boundaries, and cache keys.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import math
from pathlib import Path
import statistics
from typing import Any, Literal

from app.forecasting.m20_research import compute_max_drawdown
from app.forecasting.m22_research import PredictionTarget
from app.forecasting.m23_research import (
    M23AlignedCandleRow,
    M23ModelType,
    M23ResearchConfig,
    compute_equity_curve_max_drawdown,
    evaluate_m23_walkforward,
    extract_m23_expanded_features,
)
from app.settings import REPO_ROOT

log = logging.getLogger("imm.m24_accounting")


@dataclass(frozen=True)
class ExecutionContract:
    target: str
    is_executable: bool
    prediction_time: str
    earliest_entry_time: str
    entry_price_ref: str
    exit_price_ref: str
    holding_period: str
    is_overlapping: bool
    requires_interbar_exit: bool
    rationale: str


EXECUTION_CONTRACTS: dict[str, ExecutionContract] = {
    "C2C": ExecutionContract(
        target="C2C",
        is_executable=False,
        prediction_time="Bar close timestamp close[t]",
        earliest_entry_time="close[t] (SIMULATED)",
        entry_price_ref="close[t]",
        exit_price_ref="close[t+1]",
        holding_period="1 bar (close[t] to close[t+1])",
        is_overlapping=False,
        requires_interbar_exit=False,
        rationale=(
            "Theoretical research benchmark only. A prediction computed after bar t closes cannot "
            "retroactively execute at that exact closing price. In reality, close-price market orders "
            "must be submitted before the closing auction cutoff (15:40 IST in cash session)."
        ),
    ),
    "O2O": ExecutionContract(
        target="O2O",
        is_executable=True,
        prediction_time="Bar close timestamp close[t] (or post-market for overnight)",
        earliest_entry_time="Bar open timestamp open[t+1]",
        entry_price_ref="open[t+1]",
        exit_price_ref="open[t+2]",
        holding_period="1 bar (open[t+1] to open[t+2])",
        is_overlapping=False,
        requires_interbar_exit=False,
        rationale=(
            "Physically executable next-bar open fill. Features and prediction are fully computed at close[t], "
            "allowing order placement before or at open[t+1]. The return spans open[t+1] to open[t+2]. "
            "Continuous holding without additional turnover is valid when adjacent signals are both long (1 -> 1)."
        ),
    ),
    "O2C_1B": ExecutionContract(
        target="O2C_1B",
        is_executable=True,
        prediction_time="Bar close timestamp close[t]",
        earliest_entry_time="Bar open timestamp open[t+1]",
        entry_price_ref="open[t+1]",
        exit_price_ref="close[t+1]",
        holding_period="Intraday 1 bar (open[t+1] to close[t+1])",
        is_overlapping=False,
        requires_interbar_exit=True,
        rationale=(
            "Executable intraday single-bar trade. Entry at open[t+1], exit at close[t+1]. "
            "Because the exit occurs at close[t+1], the strategy is in cash between close[t+1] and open[t+2]. "
            "Therefore, holding cannot be continuous into the next bar without incurring close-to-open gap risk. "
            "Every traded bar requires an entry fee and an exit fee (round trip)."
        ),
    ),
    "O2C_2B": ExecutionContract(
        target="O2C_2B",
        is_executable=True,
        prediction_time="Bar close timestamp close[t]",
        earliest_entry_time="Bar open timestamp open[t+1]",
        entry_price_ref="open[t+1]",
        exit_price_ref="close[t+2]",
        holding_period="Multi-bar swing (open[t+1] to close[t+2] = 2 bars)",
        is_overlapping=True,
        requires_interbar_exit=False,
        rationale=(
            "Executable multi-bar swing trade. Period t spans [open[t+1], close[t+2]] and Period t+1 spans "
            "[open[t+2], close[t+3]]. These two periods overlap over [open[t+2], close[t+2]]. "
            "Sequential bar-by-bar return compounding without concurrent position-leg tracking results in "
            "unintended double counting of returns during overlapping bars."
        ),
    ),
}


@dataclass
class IndependentBacktestResult:
    target: str
    cost_bps: float
    total_bars: int
    gross_return_simple_pct: float
    net_return_simple_pct: float
    gross_return_compounded_pct: float
    net_return_compounded_pct: float
    equity_curve: list[float]
    max_drawdown_pct: float
    turnover_units: float
    order_count: int
    closed_trades: int
    market_exposure_pct: float
    per_bar_records: list[dict[str, Any]] = field(default_factory=list)


def simulate_independent_accounting(
    signals: list[int | float],
    returns: list[float],
    cost_bps: float = 0.0,
    target: str = "O2O",
    allow_short: bool = False,
    enforce_interbar_exit: bool | None = None,
) -> IndependentBacktestResult:
    """Independent reference backtest simulator.
    
    Does NOT call any existing production accounting functions.
    Implements clean cash and position tracking, one-way friction accounting,
    turnover separation (units vs orders), trade counting, and terminal exit liquidation.
    """
    n = len(signals)
    if n != len(returns):
        raise ValueError(f"Mismatched lengths: signals={n}, returns={len(returns)}")

    contract = EXECUTION_CONTRACTS.get(target.upper())
    should_interbar_exit = (
        contract.requires_interbar_exit if enforce_interbar_exit is None and contract else bool(enforce_interbar_exit)
    )

    c = cost_bps / 10000.0  # One-way cost in decimal
    capital = 1.0
    equity_curve = [1.0]

    simple_gross_sum = 0.0
    simple_net_sum = 0.0

    turnover_units = 0.0
    order_count = 0
    closed_trades = 0

    current_position = 0.0
    in_trade = False
    per_bar_records = []

    for t, (raw_sig, r_t) in enumerate(zip(signals, returns)):
        target_sig = float(raw_sig)
        if not allow_short and target_sig < 0:
            target_sig = 0.0
        # Clamp to [-1, 1]
        target_sig = max(-1.0 if allow_short else 0.0, min(1.0, target_sig))

        # Check for mandatory inter-bar re-entry if the contract requires closing at bar end (e.g. O2C_1B)
        if should_interbar_exit and current_position != 0.0:
            # Position was forced to close at previous bar's exit price
            exit_cost = abs(current_position) * c
            turnover_units += abs(current_position)
            order_count += 1
            closed_trades += 1
            capital *= (1.0 - exit_cost)
            simple_net_sum -= exit_cost
            current_position = 0.0
            in_trade = False

        # Position transition
        delta_pos = target_sig - current_position
        abs_delta = abs(delta_pos)

        entry_cost = 0.0
        if abs_delta > 1e-9:
            turnover_units += abs_delta
            order_count += 1
            entry_cost = abs_delta * c

            # Trade tracking
            if current_position == 0.0 and target_sig != 0.0:
                in_trade = True
            elif current_position != 0.0 and target_sig == 0.0:
                closed_trades += 1
                in_trade = False
            elif current_position != 0.0 and target_sig != 0.0 and (current_position * target_sig < 0):
                # Direct reversal
                closed_trades += 1
                in_trade = True

        current_position = target_sig

        # Gross return on held position
        bar_gross = current_position * r_t
        bar_net = bar_gross - entry_cost

        simple_gross_sum += bar_gross
        simple_net_sum += bar_net

        # Compound equity
        capital *= (1.0 + bar_net)
        equity_curve.append(capital)

        per_bar_records.append({
            "bar_idx": t,
            "signal": current_position,
            "delta_pos": delta_pos,
            "bar_return": r_t,
            "bar_gross": bar_gross,
            "entry_cost": entry_cost,
            "bar_net": bar_net,
            "capital_after": capital,
        })

    # Terminal Position Handling: If position is open at fold end, close at terminal bar exit price
    if abs(current_position) > 1e-9:
        term_exit_cost = abs(current_position) * c
        turnover_units += abs(current_position)
        order_count += 1
        closed_trades += 1
        capital *= (1.0 - term_exit_cost)
        simple_net_sum -= term_exit_cost
        equity_curve.append(capital)
        current_position = 0.0

    max_dd = compute_equity_curve_max_drawdown(equity_curve)
    active_bars = sum(1 for rec in per_bar_records if abs(rec["signal"]) > 1e-9)
    exposure_pct = (active_bars / n * 100.0) if n > 0 else 0.0

    return IndependentBacktestResult(
        target=target,
        cost_bps=cost_bps,
        total_bars=n,
        gross_return_simple_pct=round(simple_gross_sum * 100.0, 4),
        net_return_simple_pct=round(simple_net_sum * 100.0, 4),
        gross_return_compounded_pct=round((math.prod([1.0 + r["bar_gross"] for r in per_bar_records]) - 1.0) * 100.0, 4),
        net_return_compounded_pct=round((capital - 1.0) * 100.0, 4),
        equity_curve=equity_curve,
        max_drawdown_pct=max_dd,
        turnover_units=turnover_units,
        order_count=order_count,
        closed_trades=closed_trades,
        market_exposure_pct=round(exposure_pct, 2),
        per_bar_records=per_bar_records,
    )
