"""Milestone M33: End-to-End Paper Execution Simulation & Slippage Accounting Harness.

Prepared strictly for research and simulated loss-prevention verification.
Live broker routing and paper order approval are strictly disabled.
All 5 financial safety invariants remain hardcoded to False.

Core Capabilities:
1. Indian Statutory Regulatory Charges & Taxation Engine:
   - Securities Transaction Tax (STT):
       - Futures: 0.02% (2.0 bps) on SELL turnover.
       - Options: 0.10% (10.0 bps) on SELL premium turnover (Oct 2024 budget revision).
       - Equity Intraday: 0.025% (2.5 bps) on SELL turnover.
   - Exchange Transaction Charges (NSE):
       - Futures: 0.00173% on turnover.
       - Options: 0.03503% on premium turnover.
       - Equity: 0.00297% on turnover.
   - SEBI Turnover Charges: 0.0001% (Rs 10 / crore) on both BUY and SELL.
   - Brokerage: min(Rs 20.00, 0.05% of turnover) per order.
   - Goods & Services Tax (GST): 18.0% on (Brokerage + Exchange Charges + SEBI Charges).
   - Stamp Duty: 0.002% on BUY futures, 0.003% on BUY options/equity.
2. Market Impact & Tick Slippage Modeling:
   - Discrete tick alignment (0.05 INR for NSE index contracts).
   - Half-spread haircut penalty and ATR-volatility market impact.
3. Paper Lifecycle Simulation:
   - Integrates M28/M30 regime gating, M31 volatility-parity & Half-Kelly sizing.
   - Produces structured replay events compatible with app.risk.paper_accounting.
4. Historical Simulation Benchmark:
   - Compares 0 bps theoretical, 2 bps flat, and full Indian statutory friction.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
import logging
import math
from pathlib import Path
from typing import Any, Sequence

from app.forecasting.m27_htf_research import (
    HTFCandle,
    HTFInterval,
    resample_candles_to_htf,
)
from app.forecasting.m28_regime_research import (
    MarketRegime,
    compute_causal_adx_and_regimes,
)
from app.risk.portfolio_risk import (
    SquareOffAssessment,
    assess_intraday_square_off,
    calculate_volatility_parity_size,
)
from app.settings import REPO_ROOT

log = logging.getLogger("imm.execution.paper_harness")

# Tick size for Indian index derivatives (NSE)
NSE_TICK_SIZE = Decimal("0.05")

# Statutory Tax Rates (Decimal representation)
STT_FUTURES_SELL = Decimal("0.0002")       # 0.02% on Sell
STT_OPTIONS_SELL = Decimal("0.0010")       # 0.10% on Sell Premium
STT_EQUITY_INTRADAY_SELL = Decimal("0.00025")  # 0.025% on Sell

EXCHANGE_FUTURES = Decimal("0.0000173")    # 0.00173%
EXCHANGE_OPTIONS = Decimal("0.0003503")    # 0.03503%
EXCHANGE_EQUITY = Decimal("0.0000297")     # 0.00297%

SEBI_TURNOVER_RATE = Decimal("0.000001")   # Rs 10 per crore (0.0001%)
GST_RATE = Decimal("0.18")                 # 18% GST

STAMP_DUTY_FUTURES_BUY = Decimal("0.00002")  # 0.002% on Buy
STAMP_DUTY_OPTIONS_BUY = Decimal("0.00003")  # 0.003% on Buy
STAMP_DUTY_EQUITY_BUY = Decimal("0.00003")   # 0.003% on Buy

DEFAULT_BROKERAGE_PER_ORDER = Decimal("20.00")
MAX_BROKERAGE_PCT = Decimal("0.0005")      # 0.05% cap


@dataclass
class IndianRegulatoryCharges:
    instrument_type: str                   # "FUTURES", "OPTIONS", "EQUITY_INTRADAY"
    side: str                              # "BUY" or "SELL"
    turnover: Decimal
    stt: Decimal
    exchange_charges: Decimal
    sebi_charges: Decimal
    brokerage: Decimal
    gst: Decimal
    stamp_duty: Decimal
    total_charges: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument_type": self.instrument_type,
            "side": self.side,
            "turnover": float(self.turnover),
            "stt": float(self.stt),
            "exchange_charges": float(self.exchange_charges),
            "sebi_charges": float(self.sebi_charges),
            "brokerage": float(self.brokerage),
            "gst": float(self.gst),
            "stamp_duty": float(self.stamp_duty),
            "total_charges": float(self.total_charges),
        }


def round_to_tick(price: Decimal, tick_size: Decimal = NSE_TICK_SIZE) -> Decimal:
    """Round price to the nearest discrete exchange tick increment."""
    return (price / tick_size).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * tick_size


def calculate_indian_market_charges(
    instrument_type: str,
    side: str,
    price: Decimal,
    quantity: int,
    *,
    brokerage_per_order: Decimal = DEFAULT_BROKERAGE_PER_ORDER,
) -> IndianRegulatoryCharges:
    """Calculate exact statutory charges for Indian equity/derivative transactions."""
    turnover = (price * Decimal(str(quantity))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # 1. Brokerage: flat min(20.00, 0.05% turnover)
    brokerage_candidate = (turnover * MAX_BROKERAGE_PCT).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    brokerage = min(brokerage_per_order, brokerage_candidate)

    # 2. STT
    if side == "SELL":
        if instrument_type == "FUTURES":
            stt = (turnover * STT_FUTURES_SELL).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        elif instrument_type == "OPTIONS":
            stt = (turnover * STT_OPTIONS_SELL).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:  # EQUITY_INTRADAY
            stt = (turnover * STT_EQUITY_INTRADAY_SELL).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        stt = Decimal("0.00")

    # 3. Exchange Turnover Charges
    if instrument_type == "FUTURES":
        exchange_charges = (turnover * EXCHANGE_FUTURES).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    elif instrument_type == "OPTIONS":
        exchange_charges = (turnover * EXCHANGE_OPTIONS).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        exchange_charges = (turnover * EXCHANGE_EQUITY).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # 4. SEBI Turnover Charges
    sebi_charges = (turnover * SEBI_TURNOVER_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # 5. GST: 18% on (brokerage + exchange + sebi)
    gst = ((brokerage + exchange_charges + sebi_charges) * GST_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # 6. Stamp Duty
    if side == "BUY":
        if instrument_type == "FUTURES":
            stamp_duty = (turnover * STAMP_DUTY_FUTURES_BUY).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        elif instrument_type == "OPTIONS":
            stamp_duty = (turnover * STAMP_DUTY_OPTIONS_BUY).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            stamp_duty = (turnover * STAMP_DUTY_EQUITY_BUY).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        stamp_duty = Decimal("0.00")

    total_charges = stt + exchange_charges + sebi_charges + brokerage + gst + stamp_duty

    return IndianRegulatoryCharges(
        instrument_type=instrument_type,
        side=side,
        turnover=turnover,
        stt=stt,
        exchange_charges=exchange_charges,
        sebi_charges=sebi_charges,
        brokerage=brokerage,
        gst=gst,
        stamp_duty=stamp_duty,
        total_charges=total_charges,
    )


def calculate_simulated_fill_price(
    side: str,
    reference_price: Decimal,
    *,
    atr: Decimal | None = None,
    bid: Decimal | None = None,
    ask: Decimal | None = None,
    tick_size: Decimal = NSE_TICK_SIZE,
    slippage_bps: Decimal = Decimal("2.0"),
) -> tuple[Decimal, Decimal]:
    """Calculate simulated fill price applying spread and slippage.
    
    Returns:
        tuple[Decimal, Decimal]: (fill_price, slippage_inr_per_share)
    """
    if bid is not None and ask is not None and ask >= bid:
        spread = ask - bid
        half_spread = (spread / Decimal("2")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if side == "BUY":
            fill_price = ask
            slippage = half_spread
        else:
            fill_price = bid
            slippage = half_spread
    else:
        # Volatility / BPS modeled slippage
        bps_slippage = reference_price * (slippage_bps / Decimal("10000"))
        if atr is not None and atr > Decimal("0"):
            # Slippage scales with 1% of ATR or flat BPS, whichever is greater
            atr_slippage = atr * Decimal("0.01")
            slippage = max(bps_slippage, atr_slippage, tick_size)
        else:
            slippage = max(bps_slippage, tick_size)

        slippage = slippage.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if side == "BUY":
            fill_price = reference_price + slippage
        else:
            fill_price = reference_price - slippage

    fill_price = round_to_tick(fill_price, tick_size)
    return fill_price, slippage


@dataclass
class PaperTradeLifecycle:
    intent_id: str
    symbol: str
    instrument_type: str
    entry_side: str
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
    exit_reason: str
    gross_pnl_inr: Decimal
    total_slippage_inr: Decimal
    total_charges_inr: Decimal
    net_pnl_inr: Decimal
    roi_pct: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "symbol": self.symbol,
            "instrument_type": self.instrument_type,
            "entry_side": self.entry_side,
            "quantity": self.quantity,
            "entry_signal_price": float(self.entry_signal_price),
            "entry_fill_price": float(self.entry_fill_price),
            "entry_slippage_inr": float(self.entry_slippage_inr),
            "entry_charges": self.entry_charges.to_dict(),
            "entry_timestamp": self.entry_timestamp,
            "exit_signal_price": float(self.exit_signal_price),
            "exit_fill_price": float(self.exit_fill_price),
            "exit_slippage_inr": float(self.exit_slippage_inr),
            "exit_charges": self.exit_charges.to_dict(),
            "exit_timestamp": self.exit_timestamp,
            "exit_reason": self.exit_reason,
            "gross_pnl_inr": float(self.gross_pnl_inr),
            "total_slippage_inr": float(self.total_slippage_inr),
            "total_charges_inr": float(self.total_charges_inr),
            "net_pnl_inr": float(self.net_pnl_inr),
            "roi_pct": self.roi_pct,
        }


@dataclass
class PaperSimulationHarnessSummary:
    symbol: str
    initial_capital_inr: float
    final_capital_inr: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    gross_pnl_inr: float
    total_stt_inr: float
    total_exchange_turnover_inr: float
    total_sebi_charges_inr: float
    total_gst_inr: float
    total_stamp_duty_inr: float
    total_brokerage_inr: float
    total_regulatory_charges_inr: float
    total_slippage_inr: float
    net_pnl_inr: float
    profit_factor: float
    max_drawdown_pct: float
    fee_drag_pct: float
    trades: list[PaperTradeLifecycle]
    forecast_ready: bool = False
    real_market_data_verified: bool = False
    paper_approved: bool = False
    live_approved: bool = False
    live_broker_routing_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["trades"] = [t.to_dict() for t in self.trades]
        return data


def run_nifty_swing_paper_simulation(
    dataset_path: Path | str | None = None,
    *,
    initial_capital_inr: float = 1_000_000.0,
    instrument_type: str = "FUTURES",
    product_type: str = "NRML",
) -> PaperSimulationHarnessSummary:
    """Run an end-to-end paper trading simulation on NIFTY Half-Day swing bars.
    
    Applies:
    - M28 Causal Regime Consensus gating (trades only in clear trend).
    - M31 Volatility-Parity and Fractional Half-Kelly sizing.
    - Full Indian statutory regulatory charges (STT, NSE, SEBI, GST, Stamp Duty, Brokerage).
    - Discrete 0.05 INR tick alignment and slippage modeling.
    - Product type: "NRML" (Positional carryforward across sessions) or "MIS" (Intraday square-off at 15:15 IST).
    """
    if dataset_path is None:
        target_file = REPO_ROOT / "var/datasets/derived_nifty_15m_m23_bc7d31bceebf13a3.json"
    else:
        target_file = Path(dataset_path)

    with open(target_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    candles_raw = data["candles"] if "candles" in data else data
    htf_candles = resample_candles_to_htf(candles_raw, target_interval=HTFInterval.HALF_DAY)
    indicators = compute_causal_adx_and_regimes(htf_candles)

    trades: list[PaperTradeLifecycle] = []
    current_capital = Decimal(str(initial_capital_inr))
    n = len(htf_candles)

    in_position = False
    entry_bar_idx = -1
    entry_side = "BUY"
    position_qty = 0
    entry_fill_price = Decimal("0.00")
    entry_signal_price = Decimal("0.00")
    entry_slippage_total = Decimal("0.00")
    entry_charges: IndianRegulatoryCharges | None = None
    entry_timestamp = ""

    # Peak equity for drawdown tracking
    peak_equity = current_capital
    max_drawdown = Decimal("0.00")

    # Run bar-by-bar causal simulation
    for i in range(28, n - 1):
        ind = indicators[i]
        bar = htf_candles[i]
        next_bar = htf_candles[i + 1]

        # Check square-off timeline if MIS intraday product
        square_off = assess_intraday_square_off(bar.timestamp)
        if product_type == "MIS" and square_off.force_square_off_now and in_position:
            # Force exit at current bar open
            exit_signal_price = Decimal(str(bar.open))
            exit_fill, exit_slip_per_share = calculate_simulated_fill_price(
                "SELL" if entry_side == "BUY" else "BUY",
                exit_signal_price,
                atr=Decimal(str(ind.atr)),
            )
            exit_slip_total = (exit_slip_per_share * Decimal(str(position_qty))).quantize(Decimal("0.01"))
            exit_charges = calculate_indian_market_charges(
                instrument_type,
                "SELL" if entry_side == "BUY" else "BUY",
                exit_fill,
                position_qty,
            )

            if entry_side == "BUY":
                gross_pnl = (exit_fill - entry_fill_price) * Decimal(str(position_qty))
            else:
                gross_pnl = (entry_fill_price - exit_fill) * Decimal(str(position_qty))

            total_charges = entry_charges.total_charges + exit_charges.total_charges
            total_slippage = entry_slippage_total + exit_slip_total
            net_pnl = gross_pnl - total_charges
            current_capital += net_pnl

            trades.append(
                PaperTradeLifecycle(
                    intent_id=f"paper_sim_{len(trades) + 1}",
                    symbol="NIFTY",
                    instrument_type=instrument_type,
                    entry_side=entry_side,
                    quantity=position_qty,
                    entry_signal_price=entry_signal_price,
                    entry_fill_price=entry_fill_price,
                    entry_slippage_inr=entry_slippage_total,
                    entry_charges=entry_charges,
                    entry_timestamp=entry_timestamp,
                    exit_signal_price=exit_signal_price,
                    exit_fill_price=exit_fill,
                    exit_slippage_inr=exit_slip_total,
                    exit_charges=exit_charges,
                    exit_timestamp=bar.timestamp,
                    exit_reason="MANDATORY_SQUARE_OFF_1515",
                    gross_pnl_inr=gross_pnl,
                    total_slippage_inr=total_slippage,
                    total_charges_inr=total_charges,
                    net_pnl_inr=net_pnl,
                    roi_pct=float((net_pnl / (entry_fill_price * Decimal(str(position_qty)))) * 100),
                )
            )
            in_position = False
            continue

        # Manage open position
        if in_position:
            # Check exit conditions: trend regime reversal or 2-bar swing target
            bars_held = i - entry_bar_idx
            reversal = (
                (entry_side == "BUY" and ind.regime == MarketRegime.TRENDING_BEAR)
                or (entry_side == "SELL" and ind.regime == MarketRegime.TRENDING_BULL)
                or (ind.regime == MarketRegime.SIDEWAYS_CONSOLIDATION and bars_held >= 2)
            )

            if reversal or bars_held >= 4:
                exit_signal_price = Decimal(str(next_bar.open))
                exit_fill, exit_slip_per_share = calculate_simulated_fill_price(
                    "SELL" if entry_side == "BUY" else "BUY",
                    exit_signal_price,
                    atr=Decimal(str(ind.atr)),
                )
                exit_slip_total = (exit_slip_per_share * Decimal(str(position_qty))).quantize(Decimal("0.01"))
                exit_charges = calculate_indian_market_charges(
                    instrument_type,
                    "SELL" if entry_side == "BUY" else "BUY",
                    exit_fill,
                    position_qty,
                )

                if entry_side == "BUY":
                    gross_pnl = (exit_fill - entry_fill_price) * Decimal(str(position_qty))
                else:
                    gross_pnl = (entry_fill_price - exit_fill) * Decimal(str(position_qty))

                total_charges = entry_charges.total_charges + exit_charges.total_charges
                total_slippage = entry_slippage_total + exit_slip_total
                net_pnl = gross_pnl - total_charges
                current_capital += net_pnl

                if current_capital > peak_equity:
                    peak_equity = current_capital
                dd = (peak_equity - current_capital) / peak_equity if peak_equity > 0 else Decimal("0.00")
                if dd > max_drawdown:
                    max_drawdown = dd

                trades.append(
                    PaperTradeLifecycle(
                        intent_id=f"paper_sim_{len(trades) + 1}",
                        symbol="NIFTY",
                        instrument_type=instrument_type,
                        entry_side=entry_side,
                        quantity=position_qty,
                        entry_signal_price=entry_signal_price,
                        entry_fill_price=entry_fill_price,
                        entry_slippage_inr=entry_slippage_total,
                        entry_charges=entry_charges,
                        entry_timestamp=entry_timestamp,
                        exit_signal_price=exit_signal_price,
                        exit_fill_price=exit_fill,
                        exit_slippage_inr=exit_slip_total,
                        exit_charges=exit_charges,
                        exit_timestamp=next_bar.timestamp,
                        exit_reason="REGIME_REVERSAL" if reversal else "SWING_TIME_HORIZON",
                        gross_pnl_inr=gross_pnl,
                        total_slippage_inr=total_slippage,
                        total_charges_inr=total_charges,
                        net_pnl_inr=net_pnl,
                        roi_pct=float((net_pnl / (entry_fill_price * Decimal(str(position_qty)))) * 100),
                    )
                )
                in_position = False

        # If not in position, evaluate entry under Regime Consensus
        if not in_position and ind.regime in (MarketRegime.TRENDING_BULL, MarketRegime.TRENDING_BEAR):
            # Check square off before entering
            if product_type == "MIS" and not square_off.allow_new_entries:
                continue

            entry_side = "BUY" if ind.regime == MarketRegime.TRENDING_BULL else "SELL"
            entry_signal_price = Decimal(str(next_bar.open))
            atr_dec = Decimal(str(ind.atr))

            # Sizing via M31 Volatility Parity
            stop_distance = atr_dec * Decimal("1.5")
            stop_loss = entry_signal_price - stop_distance if entry_side == "BUY" else entry_signal_price + stop_distance
            target_price = entry_signal_price + (stop_distance * Decimal("2.0")) if entry_side == "BUY" else entry_signal_price - (stop_distance * Decimal("2.0"))

            size_res = calculate_volatility_parity_size(
                instrument="NIFTY",
                total_capital_inr=float(current_capital),
                entry_price=float(entry_signal_price),
                stop_loss_price=float(stop_loss),
                atr_value=float(atr_dec),
                win_probability=0.55,
                reward_to_risk_ratio=1.5,
            )

            if size_res.decision == "EXECUTE" and size_res.recommended_lots > 0:
                position_qty = size_res.total_quantity
                entry_fill_price, entry_slip_per_share = calculate_simulated_fill_price(
                    entry_side,
                    entry_signal_price,
                    atr=atr_dec,
                )
                entry_slippage_total = (entry_slip_per_share * Decimal(str(position_qty))).quantize(Decimal("0.01"))
                entry_charges = calculate_indian_market_charges(
                    instrument_type,
                    entry_side,
                    entry_fill_price,
                    position_qty,
                )
                entry_bar_idx = i
                entry_timestamp = next_bar.timestamp
                in_position = True

    # Aggregate simulation statistics
    total_trades = len(trades)
    winning_trades = sum(1 for t in trades if t.net_pnl_inr > 0)
    losing_trades = sum(1 for t in trades if t.net_pnl_inr <= 0)
    win_rate = (winning_trades / total_trades * 100.0) if total_trades > 0 else 0.0

    gross_pnl = sum((t.gross_pnl_inr for t in trades), Decimal("0.00"))
    net_pnl = sum((t.net_pnl_inr for t in trades), Decimal("0.00"))
    total_stt = sum((t.entry_charges.stt + t.exit_charges.stt for t in trades), Decimal("0.00"))
    total_exchange = sum((t.entry_charges.exchange_charges + t.exit_charges.exchange_charges for t in trades), Decimal("0.00"))
    total_sebi = sum((t.entry_charges.sebi_charges + t.exit_charges.sebi_charges for t in trades), Decimal("0.00"))
    total_gst = sum((t.entry_charges.gst + t.exit_charges.gst for t in trades), Decimal("0.00"))
    total_stamp = sum((t.entry_charges.stamp_duty + t.exit_charges.stamp_duty for t in trades), Decimal("0.00"))
    total_brokerage = sum((t.entry_charges.brokerage + t.exit_charges.brokerage for t in trades), Decimal("0.00"))
    total_regulatory = sum((t.total_charges_inr for t in trades), Decimal("0.00"))
    total_slippage = sum((t.total_slippage_inr for t in trades), Decimal("0.00"))

    gross_gains = sum((t.gross_pnl_inr for t in trades if t.gross_pnl_inr > 0), Decimal("0.00"))
    gross_losses = abs(sum((t.gross_pnl_inr for t in trades if t.gross_pnl_inr < 0), Decimal("0.00")))
    profit_factor = float(gross_gains / gross_losses) if gross_losses > 0 else float("inf")

    fee_drag = float((total_regulatory + total_slippage) / gross_gains * 100) if gross_gains > 0 else 0.0

    summary = PaperSimulationHarnessSummary(
        symbol="NIFTY",
        initial_capital_inr=initial_capital_inr,
        final_capital_inr=float(current_capital),
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate_pct=win_rate,
        gross_pnl_inr=float(gross_pnl),
        total_stt_inr=float(total_stt),
        total_exchange_turnover_inr=float(total_exchange),
        total_sebi_charges_inr=float(total_sebi),
        total_gst_inr=float(total_gst),
        total_stamp_duty_inr=float(total_stamp),
        total_brokerage_inr=float(total_brokerage),
        total_regulatory_charges_inr=float(total_regulatory),
        total_slippage_inr=float(total_slippage),
        net_pnl_inr=float(net_pnl),
        profit_factor=profit_factor,
        max_drawdown_pct=float(max_drawdown * 100),
        fee_drag_pct=fee_drag,
        trades=trades,
    )

    out_file = REPO_ROOT / "var/datasets/m33_paper_simulation_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(summary.to_dict(), f, indent=2)

    log.info("Persisted M33 paper simulation benchmark to %s", out_file)
    return summary
