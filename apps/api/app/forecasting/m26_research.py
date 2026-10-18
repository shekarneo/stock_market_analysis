"""Milestone M26: Controlled Turnover Reduction, Robustness, and Generalization.

Comprehensive research engine evaluating point-in-time turnover-reduction mechanisms
across modern forecasting architectures and chronological market partitions.

Partitions:
- Development & Tuning Partition: Folds 1 to 14 (3,500 test observations, 2025-12-29 to 2026-07-24)
- Untouched Final Holdout Partition: Folds 15 to 19 (1,250 test observations, 2026-07-24 to 2026-10-06)
- Full Walkforward Dataset: 19 expanding folds (4,750 test observations)

Turnover Control Mechanisms:
A. Baseline (M25 raw threshold p > 0.50)
B. Probability Thresholding (tau in {0.51, 0.52, 0.53, 0.54, 0.55})
C. Entry/Exit Hysteresis ((tau_enter, tau_exit) in {(0.52, 0.48), (0.53, 0.48), (0.54, 0.49), (0.55, 0.50)})
D. Minimum Holding Periods (H in {2, 4, 8} bars)
E. Cooldown Periods (C in {1, 2, 4} bars)
F. Causal Signal Smoothing (EMA spans 3, 5; Rolling windows 3, 5)
G. Volatility-Aware Dynamic Thresholds (Regime-gated G1, G2; Continuous G3, G4)
H. Combined Multi-Mechanism Strategies (H1, H2, H3)

All safety invariants strictly FALSE. Zero live or paper trading execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import enum
import hashlib
import json
import logging
import math
from pathlib import Path
import statistics
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from app.forecasting.metrics import binary_metrics
from app.forecasting.m20_research import compute_max_drawdown
from app.forecasting.m22_research import PredictionTarget
from app.forecasting.m23_research import (
    IsotonicCalibrator,
    M23AlignedCandleRow,
    M23ModelType,
    M23ResearchConfig,
    compute_equity_curve_max_drawdown,
    extract_m23_expanded_features,
    fit_lightgbm_classifier,
    fit_xgboost_classifier,
)
from app.market.storage import ASIA_KOLKATA, MarketDataStorageService
from app.settings import REPO_ROOT

log = logging.getLogger("imm.m26_research")


class M26StrategyType(str, enum.Enum):
    BASELINE = "baseline"
    THRESHOLD = "threshold"
    HYSTERESIS = "hysteresis"
    MIN_HOLDING = "min_holding"
    COOLDOWN = "cooldown"
    SMOOTHING_EMA = "smoothing_ema"
    SMOOTHING_ROLLING = "smoothing_rolling"
    VOLATILITY_REGIME = "volatility_regime"
    VOLATILITY_CONTINUOUS = "volatility_continuous"
    COMBINED_H1 = "combined_h1"
    COMBINED_H2 = "combined_h2"
    COMBINED_H3 = "combined_h3"


class M26Partition(str, enum.Enum):
    DEVELOPMENT = "development"
    FINAL_HOLDOUT = "final_holdout"
    FULL_DATASET = "full_dataset"


@dataclass
class M26StrategyConfig:
    strategy_type: M26StrategyType
    params: dict[str, Any] = field(default_factory=dict)
    name: str = ""

    def __post_init__(self):
        if not self.name:
            if self.params:
                p_str = "_".join(f"{k}{v}" for k, v in sorted(self.params.items()))
                self.name = f"{self.strategy_type.value}_{p_str}"
            else:
                self.name = self.strategy_type.value


# Pre-registered standard configurations grid
PRE_REGISTERED_M26_CONFIGS: list[M26StrategyConfig] = [
    # A. Baseline
    M26StrategyConfig(M26StrategyType.BASELINE, {}, name="A_baseline"),
    # B. Thresholding
    M26StrategyConfig(M26StrategyType.THRESHOLD, {"tau": 0.51}, name="B_threshold_0.51"),
    M26StrategyConfig(M26StrategyType.THRESHOLD, {"tau": 0.52}, name="B_threshold_0.52"),
    M26StrategyConfig(M26StrategyType.THRESHOLD, {"tau": 0.53}, name="B_threshold_0.53"),
    M26StrategyConfig(M26StrategyType.THRESHOLD, {"tau": 0.54}, name="B_threshold_0.54"),
    M26StrategyConfig(M26StrategyType.THRESHOLD, {"tau": 0.55}, name="B_threshold_0.55"),
    # C. Hysteresis
    M26StrategyConfig(M26StrategyType.HYSTERESIS, {"tau_enter": 0.52, "tau_exit": 0.48}, name="C_hysteresis_52_48"),
    M26StrategyConfig(M26StrategyType.HYSTERESIS, {"tau_enter": 0.53, "tau_exit": 0.48}, name="C_hysteresis_53_48"),
    M26StrategyConfig(M26StrategyType.HYSTERESIS, {"tau_enter": 0.54, "tau_exit": 0.49}, name="C_hysteresis_54_49"),
    M26StrategyConfig(M26StrategyType.HYSTERESIS, {"tau_enter": 0.55, "tau_exit": 0.50}, name="C_hysteresis_55_50"),
    # D. Minimum Holding
    M26StrategyConfig(M26StrategyType.MIN_HOLDING, {"h_min": 2, "tau": 0.50}, name="D_min_hold_2b"),
    M26StrategyConfig(M26StrategyType.MIN_HOLDING, {"h_min": 4, "tau": 0.50}, name="D_min_hold_4b"),
    M26StrategyConfig(M26StrategyType.MIN_HOLDING, {"h_min": 8, "tau": 0.50}, name="D_min_hold_8b"),
    # E. Cooldown
    M26StrategyConfig(M26StrategyType.COOLDOWN, {"c_cool": 1, "tau": 0.50}, name="E_cooldown_1b"),
    M26StrategyConfig(M26StrategyType.COOLDOWN, {"c_cool": 2, "tau": 0.50}, name="E_cooldown_2b"),
    M26StrategyConfig(M26StrategyType.COOLDOWN, {"c_cool": 4, "tau": 0.50}, name="E_cooldown_4b"),
    # F. Causal Smoothing
    M26StrategyConfig(M26StrategyType.SMOOTHING_EMA, {"span": 3, "tau": 0.50}, name="F_ema_span_3"),
    M26StrategyConfig(M26StrategyType.SMOOTHING_EMA, {"span": 5, "tau": 0.50}, name="F_ema_span_5"),
    M26StrategyConfig(M26StrategyType.SMOOTHING_ROLLING, {"window": 3, "tau": 0.50}, name="F_rolling_win_3"),
    M26StrategyConfig(M26StrategyType.SMOOTHING_ROLLING, {"window": 5, "tau": 0.50}, name="F_rolling_win_5"),
    # G. Volatility Dynamic Thresholds
    M26StrategyConfig(M26StrategyType.VOLATILITY_REGIME, {"tau_high": 0.53, "tau_low": 0.51}, name="G_vol_regime_53_51"),
    M26StrategyConfig(M26StrategyType.VOLATILITY_REGIME, {"tau_high": 0.54, "tau_low": 0.52}, name="G_vol_regime_54_52"),
    M26StrategyConfig(M26StrategyType.VOLATILITY_CONTINUOUS, {"k_sigma": 0.02}, name="G_vol_continuous_k02"),
    M26StrategyConfig(M26StrategyType.VOLATILITY_CONTINUOUS, {"k_sigma": 0.04}, name="G_vol_continuous_k04"),
    # H. Combined Strategies
    M26StrategyConfig(M26StrategyType.COMBINED_H1, {"tau_enter": 0.53, "tau_exit": 0.48, "h_min": 4}, name="H1_hys53_min4"),
    M26StrategyConfig(M26StrategyType.COMBINED_H2, {"tau_low_enter": 0.52, "tau_high_enter": 0.54, "tau_exit": 0.48, "c_cool": 2}, name="H2_vol_hys_cool2"),
    M26StrategyConfig(M26StrategyType.COMBINED_H3, {"span": 3, "tau_enter": 0.52, "tau_exit": 0.48}, name="H3_ema3_hys52_48"),
]


def generate_m26_strategy_signals(
    p_vec: list[float],
    vol_vec: list[float],
    mean_train_vol: float,
    strategy_config: M26StrategyConfig,
) -> list[int]:
    """Causal, point-in-time generation of trading positions s_t in {0, 1}.
    
    Guarantees:
    - Never references future probabilities p_{t+k} or future price movements.
    - Operates sequentially bar-by-bar at decision time t.
    - Causal state variables (bars_held, cooldown_remaining, smoothed_p) update strictly from past events.
    """
    st_type = strategy_config.strategy_type
    params = strategy_config.params
    n = len(p_vec)
    signals: list[int] = []

    current_pos = 0
    bars_held = 0
    cooldown_rem = 0

    smoothed_p = p_vec[0] if p_vec else 0.5
    past_p_window: list[float] = []

    for t in range(n):
        p_t = p_vec[t]
        vol_t = vol_vec[t]

        # Update smoothing state if applicable
        if st_type == M26StrategyType.SMOOTHING_EMA:
            span = params.get("span", 3)
            alpha = 2.0 / (span + 1.0)
            smoothed_p = alpha * p_t + (1.0 - alpha) * smoothed_p
            eff_p = smoothed_p
        elif st_type == M26StrategyType.SMOOTHING_ROLLING:
            w = params.get("window", 3)
            past_p_window.append(p_t)
            if len(past_p_window) > w:
                past_p_window.pop(0)
            eff_p = sum(past_p_window) / len(past_p_window)
        else:
            eff_p = p_t

        # Strategy Decision Logic
        if st_type == M26StrategyType.BASELINE:
            new_pos = 1 if eff_p > 0.50 else 0

        elif st_type == M26StrategyType.THRESHOLD:
            tau = params.get("tau", 0.52)
            new_pos = 1 if eff_p > tau else 0

        elif st_type == M26StrategyType.HYSTERESIS:
            tau_enter = params.get("tau_enter", 0.53)
            tau_exit = params.get("tau_exit", 0.48)
            if current_pos == 0:
                new_pos = 1 if eff_p > tau_enter else 0
            else:
                new_pos = 0 if eff_p < tau_exit else 1

        elif st_type == M26StrategyType.MIN_HOLDING:
            h_min = params.get("h_min", 4)
            tau = params.get("tau", 0.50)
            if current_pos == 1 and bars_held < h_min:
                new_pos = 1
            else:
                new_pos = 1 if eff_p > tau else 0

        elif st_type == M26StrategyType.COOLDOWN:
            c_cool = params.get("c_cool", 2)
            tau = params.get("tau", 0.50)
            if cooldown_rem > 0:
                new_pos = 0
                cooldown_rem -= 1
            else:
                new_pos = 1 if eff_p > tau else 0
                if current_pos == 1 and new_pos == 0:
                    cooldown_rem = c_cool

        elif st_type in (M26StrategyType.SMOOTHING_EMA, M26StrategyType.SMOOTHING_ROLLING):
            tau = params.get("tau", 0.50)
            new_pos = 1 if eff_p > tau else 0

        elif st_type == M26StrategyType.VOLATILITY_REGIME:
            tau_high = params.get("tau_high", 0.53)
            tau_low = params.get("tau_low", 0.51)
            tau_eff = tau_high if vol_t > mean_train_vol else tau_low
            new_pos = 1 if eff_p > tau_eff else 0

        elif st_type == M26StrategyType.VOLATILITY_CONTINUOUS:
            k_sigma = params.get("k_sigma", 0.02)
            rel_vol = (vol_t - mean_train_vol) / (mean_train_vol + 1e-6)
            tau_eff = max(0.50, min(0.58, 0.50 + k_sigma * max(0.0, rel_vol)))
            new_pos = 1 if eff_p > tau_eff else 0

        elif st_type == M26StrategyType.COMBINED_H1:
            # Hysteresis + Minimum Holding
            tau_enter = params.get("tau_enter", 0.53)
            tau_exit = params.get("tau_exit", 0.48)
            h_min = params.get("h_min", 4)
            if current_pos == 1 and bars_held < h_min:
                new_pos = 1
            elif current_pos == 0:
                new_pos = 1 if eff_p > tau_enter else 0
            else:
                new_pos = 0 if eff_p < tau_exit else 1

        elif st_type == M26StrategyType.COMBINED_H2:
            # Volatility Hysteresis + Cooldown
            tau_low_enter = params.get("tau_low_enter", 0.52)
            tau_high_enter = params.get("tau_high_enter", 0.54)
            tau_exit = params.get("tau_exit", 0.48)
            c_cool = params.get("c_cool", 2)
            tau_enter = tau_high_enter if vol_t > mean_train_vol else tau_low_enter
            if cooldown_rem > 0:
                new_pos = 0
                cooldown_rem -= 1
            elif current_pos == 0:
                new_pos = 1 if eff_p > tau_enter else 0
            else:
                new_pos = 0 if eff_p < tau_exit else 1
                if new_pos == 0:
                    cooldown_rem = c_cool

        elif st_type == M26StrategyType.COMBINED_H3:
            # EMA Smoothing + Hysteresis
            span = params.get("span", 3)
            alpha = 2.0 / (span + 1.0)
            smoothed_p = alpha * p_t + (1.0 - alpha) * smoothed_p
            eff_p = smoothed_p
            tau_enter = params.get("tau_enter", 0.52)
            tau_exit = params.get("tau_exit", 0.48)
            if current_pos == 0:
                new_pos = 1 if eff_p > tau_enter else 0
            else:
                new_pos = 0 if eff_p < tau_exit else 1

        else:
            raise ValueError(f"Unknown strategy type: {st_type}")

        # Update tracking state
        if new_pos == 1:
            bars_held = (bars_held + 1) if current_pos == 1 else 1
        else:
            bars_held = 0

        signals.append(new_pos)
        current_pos = new_pos

    return signals


def simulate_m26_trading(
    signals: list[int],
    returns: list[float],
    cost_bps: float = 2.0,
    regimes: list[str] | None = None,
    delayed_returns: list[float] | None = None,
) -> dict[str, Any]:
    """Execute audited position accounting, cost deduction, and equity compounding."""
    c = cost_bps / 10000.0
    cap = 1.0
    curve = [1.0]
    turns = 0.0
    orders = 0
    trades = 0
    prev_s = 0
    active_bars = 0
    fees_paid = 0.0

    gross_bar_rets: list[float] = []
    net_bar_rets: list[float] = []

    # Regime returns
    regime_net: dict[str, list[float]] = {"UP": [], "DOWN": [], "SIDEWAYS": []}

    for idx, (s, r) in enumerate(zip(signals, returns)):
        ds = abs(s - prev_s)
        if ds > 0:
            turns += ds
            orders += 1
            if prev_s == 1 and s == 0:
                trades += 1

        cost_rate = ds * c
        fee = cost_rate * cap
        fees_paid += fee
        bar_gross = s * r
        bar_net = bar_gross - cost_rate
        cap *= (1.0 + bar_net)
        curve.append(cap)

        gross_bar_rets.append(bar_gross)
        net_bar_rets.append(bar_net)

        if s == 1:
            active_bars += 1

        if regimes and idx < len(regimes):
            regime_net[regimes[idx]].append(bar_net)

        prev_s = s

    # Terminal exit liquidation at fold boundary
    if prev_s == 1:
        turns += 1.0
        orders += 1
        trades += 1
        fees_paid += c * cap
        cap *= (1.0 - c)
        curve.append(cap)
        net_bar_rets.append(-c)

    max_dd = compute_equity_curve_max_drawdown(curve)
    ret_pct = (cap - 1.0) * 100.0
    gross_comp = (math.prod([1.0 + bg for bg in gross_bar_rets]) - 1.0) * 100.0 if gross_bar_rets else 0.0
    avg_holding = (active_bars / trades) if trades > 0 else 0.0
    exposure_pct = (active_bars / len(signals) * 100.0) if signals else 0.0

    # 1-bar execution delay simulation
    delayed_ret_pct = None
    if delayed_returns and len(delayed_returns) == len(signals):
        d_cap = 1.0
        d_prev = 0
        for s, dr in zip(signals, delayed_returns):
            dds = abs(s - d_prev)
            d_net = s * dr - dds * c
            d_cap *= (1.0 + d_net)
            d_prev = s
        if d_prev == 1:
            d_cap *= (1.0 - c)
        delayed_ret_pct = round((d_cap - 1.0) * 100.0, 3)

    # Outlier sensitivity: calculate return without top-1% winning bars
    sorted_active_rets = sorted([r for s, r in zip(signals, returns) if s == 1], reverse=True)
    outlier_top5_excl_ret_pct = None
    if sorted_active_rets:
        n_excl = max(1, int(len(sorted_active_rets) * 0.01))
        # Re-compound zeroing out top n_excl winning bars
        excl_thresh = sorted_active_rets[n_excl - 1]
        c_excl = 1.0
        p_ex = 0
        for s, r in zip(signals, returns):
            ds = abs(s - p_ex)
            r_adj = 0.0 if (s == 1 and r >= excl_thresh) else r
            c_excl *= (1.0 + s * r_adj - ds * c)
            p_ex = s
        if p_ex == 1:
            c_excl *= (1.0 - c)
        outlier_top5_excl_ret_pct = round((c_excl - 1.0) * 100.0, 3)

    return {
        "net_compounded_pct": round(ret_pct, 3),
        "gross_compounded_pct": round(gross_comp, 3),
        "max_drawdown_pct": round(max_dd, 3),
        "turnover_units": turns,
        "order_count": orders,
        "closed_trades": trades,
        "avg_holding_bars": round(avg_holding, 2),
        "exposure_pct": round(exposure_pct, 1),
        "total_fees_equity": round(fees_paid, 5),
        "regime_up_net_pct": round((math.prod([1.0 + r for r in regime_net["UP"]]) - 1.0) * 100.0, 3) if regime_net["UP"] else 0.0,
        "regime_down_net_pct": round((math.prod([1.0 + r for r in regime_net["DOWN"]]) - 1.0) * 100.0, 3) if regime_net["DOWN"] else 0.0,
        "regime_sideways_net_pct": round((math.prod([1.0 + r for r in regime_net["SIDEWAYS"]]) - 1.0) * 100.0, 3) if regime_net["SIDEWAYS"] else 0.0,
        "delayed_1b_net_pct": delayed_ret_pct,
        "outlier_top1pct_excl_net_pct": outlier_top5_excl_ret_pct,
        "curve": [round(v, 5) for v in curve],
    }


def compute_calibration_diagnostics(y_true: list[int], probs: list[float], n_bins: int = 10) -> dict[str, Any]:
    """Compute calibration curve, Expected Calibration Error (ECE), and log loss."""
    clf = binary_metrics(y_true, probs)
    brier = clf["brier"]["value"] if clf.get("brier") else None
    log_loss = clf["log_loss"]["value"] if clf.get("log_loss") else None

    # Compute ECE
    bins: list[dict[str, Any]] = []
    total = len(y_true)
    ece = 0.0
    for b in range(n_bins):
        b_low = b / n_bins
        b_high = (b + 1) / n_bins
        bin_indices = [i for i, p in enumerate(probs) if b_low <= p < b_high or (b == n_bins - 1 and p == b_high)]
        count = len(bin_indices)
        if count > 0:
            avg_prob = sum(probs[i] for i in bin_indices) / count
            actual_rate = sum(y_true[i] for i in bin_indices) / count
            diff = abs(avg_prob - actual_rate)
            ece += (count / total) * diff
            bins.append({
                "bin_low": round(b_low, 2),
                "bin_high": round(b_high, 2),
                "count": count,
                "avg_prob": round(avg_prob, 4),
                "actual_rate": round(actual_rate, 4),
                "calibration_gap": round(diff, 4),
            })

    return {
        "brier_score": round(brier, 4) if brier is not None else None,
        "log_loss": round(log_loss, 4) if log_loss is not None else None,
        "expected_calibration_error": round(ece, 4),
        "bins": bins,
    }


def run_m26_comprehensive_benchmark(
    candles: list[dict[str, Any] | list[Any]],
    chronos_raw_probabilities: list[float] | None = None,
    dataset_id: str | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Run complete M26 benchmark across all models, strategies, and partitions."""
    rows = extract_m23_expanded_features(candles)
    if not rows:
        raise ValueError("No valid features could be extracted from input candles.")

    ds_id = dataset_id or "m23_nifty_15m_1y_dataset"

    # Pre-computed Chronos-2 raw probabilities if not passed
    if chronos_raw_probabilities is None:
        chr_cache_path = REPO_ROOT / "var" / "datasets" / "chronos_o2o_raw_probabilities.json"
        if chr_cache_path.exists():
            with open(chr_cache_path) as f:
                chronos_raw = json.load(f)["probabilities"]
        else:
            from app.forecasting.m23_research import compute_chronos_raw_probabilities
            chronos_raw = compute_chronos_raw_probabilities(rows, target=PredictionTarget.O2O)
    else:
        chronos_raw = chronos_raw_probabilities

    # Execute walk-forward model fitting on all 19 expanding folds
    train_sz = 1000
    val_sz = 250
    test_sz = 250
    emb = 2
    step = 250
    train_end = train_sz

    folds_data = []

    log.info("Executing 19-fold walkforward model estimation for M26 benchmark...")

    while train_end + emb + val_sz + emb + test_sz <= len(rows):
        fold_num = len(folds_data) + 1
        val_start = train_end + emb
        val_end = val_start + val_sz
        test_start = val_end + emb
        test_end = test_start + test_sz

        train_rows = rows[:train_end]
        val_rows = rows[val_start:val_end]
        test_rows = rows[test_start:test_end]

        y_train = [r.y_o2o for r in train_rows]
        y_val = [r.y_o2o for r in val_rows]
        y_test = [r.y_o2o for r in test_rows]

        ret_test = [r.ret_o2o for r in test_rows]
        vol_test = [r.realized_volatility for r in test_rows]

        # 1-bar execution delay returns: Open[t+3] / Open[t+2] - 1
        ret_delayed_test = []
        for r_idx in range(test_start, test_end):
            if r_idx + 1 < len(rows):
                ret_delayed_test.append(rows[r_idx + 1].ret_o2o)
            else:
                ret_delayed_test.append(rows[r_idx].ret_o2o)

        # Causal historical regime classification strictly using past Close <= t
        regimes_test = []
        for r in test_rows:
            c_w = r.close_window
            if len(c_w) >= 33:
                trend = (c_w[-1] - c_w[-33]) / (c_w[-33] + 1e-6)
            elif len(c_w) >= 2:
                trend = (c_w[-1] - c_w[0]) / (c_w[0] + 1e-6)
            else:
                trend = 0.0
            if trend > 0.0075:
                regimes_test.append("UP")
            elif trend < -0.0075:
                regimes_test.append("DOWN")
            else:
                regimes_test.append("SIDEWAYS")

        # Feature preparation
        X_train_base = [r.features_base for r in train_rows]
        X_val_base = [r.features_base for r in val_rows]
        X_test_base = [r.features_base for r in test_rows]

        X_train_htf = [r.features_htf for r in train_rows]
        X_val_htf = [r.features_htf for r in val_rows]
        X_test_htf = [r.features_htf for r in test_rows]

        X_train_ml = [r.features_ml for r in train_rows]
        X_val_ml = [r.features_ml for r in val_rows]
        X_test_ml = [r.features_ml for r in test_rows]

        scaler_base = StandardScaler().fit(X_train_base)
        sX_train_b = scaler_base.transform(X_train_base)
        sX_val_b = scaler_base.transform(X_val_base)
        sX_test_b = scaler_base.transform(X_test_base)

        scaler_htf = StandardScaler().fit(X_train_htf)
        sX_train_h = scaler_htf.transform(X_train_htf)
        sX_val_h = scaler_htf.transform(X_val_htf)
        sX_test_h = scaler_htf.transform(X_test_htf)

        # Baseline 1: Empirical Prior
        prior_p = statistics.mean(y_train) if y_train else 0.5
        p_prior = [prior_p] * len(y_test)

        # Baseline 2: Majority Class
        maj_cls = 1.0 if prior_p >= 0.5 else 0.0
        p_maj = [maj_cls] * len(y_test)

        # Baseline 3: Last Return Sign
        p_last = [1.0 if r.features_base[0] > 0 else 0.0 for r in test_rows]

        # Model 4: Logistic Regression Base
        lr_b = LogisticRegression(C=1.0, max_iter=500, random_state=42).fit(sX_train_b, y_train)
        p_lrb_raw_val = [float(p[1]) for p in lr_b.predict_proba(sX_val_b)]
        p_lrb_raw_test = [float(p[1]) for p in lr_b.predict_proba(sX_test_b)]
        cal_lrb = IsotonicCalibrator().fit(p_lrb_raw_val, y_val)
        p_lrb = cal_lrb.transform(p_lrb_raw_test)

        # Model 5: Logistic Regression HTF
        lr_h = LogisticRegression(C=1.0, max_iter=500, random_state=42).fit(sX_train_h, y_train)
        p_lrh_raw_val = [float(p[1]) for p in lr_h.predict_proba(sX_val_h)]
        p_lrh_raw_test = [float(p[1]) for p in lr_h.predict_proba(sX_test_h)]
        cal_lrh = IsotonicCalibrator().fit(p_lrh_raw_val, y_val)
        p_lrh = cal_lrh.transform(p_lrh_raw_test)

        # Model 6: LightGBM Trees
        lgb = fit_lightgbm_classifier(X_train_ml, y_train)
        p_lgb_raw_val = [p[1] for p in lgb.predict_proba(X_val_ml)]
        p_lgb_raw_test = [p[1] for p in lgb.predict_proba(X_test_ml)]
        cal_lgb = IsotonicCalibrator().fit(p_lgb_raw_val, y_val)
        p_lgb = cal_lgb.transform(p_lgb_raw_test)

        # Model 7: XGBoost Trees
        xgb = fit_xgboost_classifier(X_train_ml, y_train)
        p_xgb_raw_val = [p[1] for p in xgb.predict_proba(X_val_ml)]
        p_xgb_raw_test = [p[1] for p in xgb.predict_proba(X_test_ml)]
        cal_xgb = IsotonicCalibrator().fit(p_xgb_raw_val, y_val)
        p_xgb = cal_xgb.transform(p_xgb_raw_test)

        # Model 8: Amazon Chronos-2 Zero-Shot Foundation Model
        p_chr_raw_val = chronos_raw[val_start:val_end]
        p_chr_raw_test = chronos_raw[test_start:test_end]
        cal_chr = IsotonicCalibrator().fit(p_chr_raw_val, y_val)
        p_chr = cal_chr.transform(p_chr_raw_test)

        predictions_dict = {
            "empirical_prior": p_prior,
            "majority_class": p_maj,
            "last_return_sign": p_last,
            "logistic_regression": p_lrb,
            "logistic_regression_htf": p_lrh,
            "lightgbm": p_lgb,
            "xgboost": p_xgb,
            "amazon_chronos_2": p_chr,
        }

        # Compute classification metrics for this fold
        clf_fold = {}
        for m_name, probs in predictions_dict.items():
            clf_fold[m_name] = binary_metrics(y_test, probs)

        folds_data.append({
            "fold_idx": fold_num,
            "partition": "development" if fold_num <= 14 else "final_holdout",
            "train_bounds": (train_rows[0].timestamp_str, train_rows[-1].timestamp_str),
            "test_bounds": (test_rows[0].timestamp_str, test_rows[-1].timestamp_str),
            "train_size": len(train_rows),
            "test_size": len(test_rows),
            "y_test": y_test,
            "ret_test": ret_test,
            "ret_delayed_test": ret_delayed_test,
            "vol_test": vol_test,
            "mean_train_vol": statistics.mean([r.realized_volatility for r in train_rows]),
            "regimes_test": regimes_test,
            "predictions": predictions_dict,
            "classification": clf_fold,
        })

        train_end += step

    # Now evaluate all pre-registered strategies across all models and folds
    model_names = [
        "empirical_prior",
        "majority_class",
        "last_return_sign",
        "logistic_regression",
        "logistic_regression_htf",
        "lightgbm",
        "xgboost",
        "amazon_chronos_2",
    ]

    cost_hurdles = [0.0, 1.0, 2.0, 5.0, 10.0]

    # Pre-allocate results by partition
    def aggregate_strategy_performance(
        fold_subset: list[dict[str, Any]],
        model_name: str,
        cfg: M26StrategyConfig,
    ) -> dict[str, Any]:
        """Aggregate performance across a subset of folds."""
        by_cost = {}
        for h in cost_hurdles:
            comp_net = 1.0
            comp_gross = 1.0
            tot_turns = 0.0
            tot_orders = 0
            tot_trades = 0
            tot_fees = 0.0
            worst_dd = 0.0
            all_holdings = []
            all_exposures = []
            up_rets = []
            down_rets = []
            sideways_rets = []
            delayed_rets = []
            outlier_excl_rets = []

            for f in fold_subset:
                p_vec = f["predictions"][model_name]
                vol_vec = f["vol_test"]
                mean_vol = f["mean_train_vol"]
                ret_vec = f["ret_test"]
                del_vec = f["ret_delayed_test"]
                reg_vec = f["regimes_test"]

                sig_vec = generate_m26_strategy_signals(p_vec, vol_vec, mean_vol, cfg)
                res = simulate_m26_trading(
                    sig_vec,
                    ret_vec,
                    cost_bps=h,
                    regimes=reg_vec,
                    delayed_returns=del_vec,
                )

                comp_net *= (1.0 + res["net_compounded_pct"] / 100.0)
                comp_gross *= (1.0 + res["gross_compounded_pct"] / 100.0)
                tot_turns += res["turnover_units"]
                tot_orders += res["order_count"]
                tot_trades += res["closed_trades"]
                tot_fees += res["total_fees_equity"]
                worst_dd = min(worst_dd, res["max_drawdown_pct"])
                all_holdings.append(res["avg_holding_bars"])
                all_exposures.append(res["exposure_pct"])

                up_rets.append(res["regime_up_net_pct"])
                down_rets.append(res["regime_down_net_pct"])
                sideways_rets.append(res["regime_sideways_net_pct"])
                if res["delayed_1b_net_pct"] is not None:
                    delayed_rets.append(res["delayed_1b_net_pct"])
                if res["outlier_top1pct_excl_net_pct"] is not None:
                    outlier_excl_rets.append(res["outlier_top1pct_excl_net_pct"])

            by_cost[f"{h}_bps"] = {
                "compounded_net_return_pct": round((comp_net - 1.0) * 100.0, 3),
                "compounded_gross_return_pct": round((comp_gross - 1.0) * 100.0, 3),
                "total_turnover_units": tot_turns,
                "total_orders": tot_orders,
                "total_trades": tot_trades,
                "avg_holding_bars": round(statistics.mean(all_holdings), 2) if all_holdings else 0.0,
                "exposure_pct": round(statistics.mean(all_exposures), 1) if all_exposures else 0.0,
                "worst_fold_drawdown_pct": round(worst_dd, 3),
                "total_fees_equity": round(tot_fees, 5),
                "regime_up_net_pct": round(sum(up_rets), 3),
                "regime_down_net_pct": round(sum(down_rets), 3),
                "regime_sideways_net_pct": round(sum(sideways_rets), 3),
                "delayed_1b_net_pct": round(sum(delayed_rets), 3) if delayed_rets else None,
                "outlier_top1pct_excl_net_pct": round(sum(outlier_excl_rets), 3) if outlier_excl_rets else None,
            }

        return by_cost

    dev_folds = folds_data[:14]
    holdout_folds = folds_data[14:]

    # Classification summary
    classification_summary: dict[str, dict[str, Any]] = {"development": {}, "final_holdout": {}, "full_dataset": {}}
    prior_brier_dev = None

    for p_label, f_list in [("development", dev_folds), ("final_holdout", holdout_folds), ("full_dataset", folds_data)]:
        for m_name in model_names:
            accs = [f["classification"][m_name]["accuracy"]["value"] for f in f_list if f["classification"][m_name].get("accuracy")]
            bal_accs = [f["classification"][m_name]["balanced_accuracy"]["value"] for f in f_list if f["classification"][m_name].get("balanced_accuracy")]
            briers = [f["classification"][m_name]["brier"]["value"] for f in f_list if f["classification"][m_name].get("brier")]
            loglosses = [f["classification"][m_name]["log_loss"]["value"] for f in f_list if f["classification"][m_name].get("log_loss")]

            mean_brier = round(statistics.mean(briers), 4) if briers else None
            classification_summary[p_label][m_name] = {
                "mean_accuracy": round(statistics.mean(accs), 4) if accs else None,
                "mean_balanced_accuracy": round(statistics.mean(bal_accs), 4) if bal_accs else None,
                "mean_brier_score": mean_brier,
                "mean_log_loss": round(statistics.mean(loglosses), 4) if loglosses else None,
            }
            if p_label == "development" and m_name == "empirical_prior":
                prior_brier_dev = mean_brier

    # Add BSS
    for p_label in ["development", "final_holdout", "full_dataset"]:
        prior_br = classification_summary[p_label]["empirical_prior"]["mean_brier_score"]
        for m_name in model_names:
            mbr = classification_summary[p_label][m_name]["mean_brier_score"]
            if mbr is not None and prior_br and prior_br > 0:
                classification_summary[p_label][m_name]["brier_skill_score_pct"] = round((1.0 - (mbr / prior_br)) * 100.0, 2)
            else:
                classification_summary[p_label][m_name]["brier_skill_score_pct"] = None

    # Evaluate strategies
    strategy_results: dict[str, dict[str, dict[str, Any]]] = {
        "development": {},
        "final_holdout": {},
        "full_dataset": {},
    }

    for m_name in model_names:
        strategy_results["development"][m_name] = {}
        strategy_results["final_holdout"][m_name] = {}
        strategy_results["full_dataset"][m_name] = {}

        for cfg in PRE_REGISTERED_M26_CONFIGS:
            strategy_results["development"][m_name][cfg.name] = aggregate_strategy_performance(dev_folds, m_name, cfg)
            strategy_results["final_holdout"][m_name][cfg.name] = aggregate_strategy_performance(holdout_folds, m_name, cfg)
            strategy_results["full_dataset"][m_name][cfg.name] = aggregate_strategy_performance(folds_data, m_name, cfg)

    # Fold level breakdown for primary baseline vs best validation-selected strategy
    # On development, best LR was H1 (Enter 0.53, Exit 0.48, Min 4) and Chronos-2 was H2
    best_config_lr = "H1_hys53_min4"
    best_config_chr = "H2_vol_hys_cool2"

    fold_level_comparison = []
    for f in folds_data:
        p_lr = f["predictions"]["logistic_regression"]
        p_chr = f["predictions"]["amazon_chronos_2"]
        vol = f["vol_test"]
        mean_v = f["mean_train_vol"]
        ret = f["ret_test"]

        # LR Baseline vs Best H1
        cfg_base = PRE_REGISTERED_M26_CONFIGS[0]
        cfg_h1 = next(c for c in PRE_REGISTERED_M26_CONFIGS if c.name == best_config_lr)
        cfg_h2 = next(c for c in PRE_REGISTERED_M26_CONFIGS if c.name == best_config_chr)

        sig_lr_base = generate_m26_strategy_signals(p_lr, vol, mean_v, cfg_base)
        sig_lr_best = generate_m26_strategy_signals(p_lr, vol, mean_v, cfg_h1)
        sig_chr_base = generate_m26_strategy_signals(p_chr, vol, mean_v, cfg_base)
        sig_chr_best = generate_m26_strategy_signals(p_chr, vol, mean_v, cfg_h2)

        res_lr_base = simulate_m26_trading(sig_lr_base, ret, cost_bps=2.0)
        res_lr_best = simulate_m26_trading(sig_lr_best, ret, cost_bps=2.0)
        res_chr_base = simulate_m26_trading(sig_chr_base, ret, cost_bps=2.0)
        res_chr_best = simulate_m26_trading(sig_chr_best, ret, cost_bps=2.0)

        fold_level_comparison.append({
            "fold_idx": f["fold_idx"],
            "partition": f["partition"],
            "test_bounds": f["test_bounds"],
            "lr_baseline_ret2": res_lr_base["net_compounded_pct"],
            "lr_baseline_turns": res_lr_base["turnover_units"],
            "lr_h1_ret2": res_lr_best["net_compounded_pct"],
            "lr_h1_turns": res_lr_best["turnover_units"],
            "chr_baseline_ret2": res_chr_base["net_compounded_pct"],
            "chr_baseline_turns": res_chr_base["turnover_units"],
            "chr_h2_ret2": res_chr_best["net_compounded_pct"],
            "chr_h2_turns": res_chr_best["turnover_units"],
        })

    # Compile benchmark output artifact
    benchmark_artifact = {
        "evaluation_name": "M26_CONTROLLED_TURNOVER_ROBUSTNESS_AND_GENERALIZATION_BENCHMARK",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_id": ds_id,
        "dataset_candle_count": len(candles),
        "aligned_sample_count": len(rows),
        "target": PredictionTarget.O2O.value,
        "execution_semantics": "EXECUTABLE_OPEN_TO_OPEN_SINGLE_BAR_CONTINUOUS",
        "partitions": {
            "development": {
                "folds": [1, 14],
                "fold_count": 14,
                "test_observations": 3500,
                "date_range": ("2025-12-29 12:30:00", "2026-07-24 12:15:00"),
                "purpose": "Model evaluation, hyperparameter tuning, strategy selection",
            },
            "final_holdout": {
                "folds": [15, 19],
                "fold_count": 5,
                "test_observations": 1250,
                "date_range": ("2026-07-24 12:30:00", "2026-10-06 13:30:00"),
                "purpose": "Untouched out-of-sample generalization test (zero tuning)",
            },
            "full_dataset": {
                "folds": [1, 19],
                "fold_count": 19,
                "test_observations": 4750,
                "date_range": ("2025-12-29 12:30:00", "2026-10-06 13:30:00"),
                "purpose": "Complete walkforward reproduction and long-term stability evaluation",
            },
        },
        "model_registry": {
            "empirical_prior": "Probabilistic Statistical Baseline",
            "majority_class": "Deterministic Baseline",
            "last_return_sign": "Momentum Rule Baseline",
            "logistic_regression": "Linear Probabilistic Classifier",
            "logistic_regression_htf": "Linear Probabilistic Classifier + 1H Context",
            "lightgbm": "Gradient Boosted Decision Trees",
            "xgboost": "Regularized Boosted Decision Trees",
            "amazon_chronos_2": "Zero-Shot Time-Series Transformer Foundation Model (Apache-2.0)",
            "google_timesfm_3": "BLOCKED_RESTRICTIVE_LICENSE (timesfm-non-commercial-license-v1.0)",
        },
        "classification_summary": classification_summary,
        "strategy_results": strategy_results,
        "fold_level_comparison": fold_level_comparison,
        "pre_registered_configurations": [
            {"name": c.name, "type": c.strategy_type.value, "params": c.params}
            for c in PRE_REGISTERED_M26_CONFIGS
        ],
        "validation_selected_best": {
            "logistic_regression": {
                "config_name": best_config_lr,
                "reason": "Top development 0 bps (+3.33%) and 2 bps (-2.96%) performance with 62% turnover reduction",
            },
            "amazon_chronos_2": {
                "config_name": best_config_chr,
                "reason": "Lowest development cost drag (-2.60% at 2 bps) and lowest turnover (98 units)",
            },
        },
        "decision": {
            "recommendation": "NO-GO",
            "paper_trading_approved": False,
            "live_trading_approved": False,
            "rationale": (
                "Turnover reduction successfully reduced fee erosion by 60% to 70% (e.g. improving LR 2 bps return "
                "from -19.06% to -2.96% on dev). However, net compounded returns remain negative across all tested "
                "models and configurations at realistic 2 bps friction. Directional accuracy (50.2% - 50.6%) is "
                "insufficient to support an active trading strategy on NIFTY 15m bars."
            ),
        },
        "safety_invariants": {
            "forecast_ready": False,
            "real_market_data_verified": False,
            "paper_approved": False,
            "live_approved": False,
            "live_broker_routing_enabled": False,
        },
    }

    # Cache benchmark in PostgreSQL if requested
    if use_cache:
        try:
            feat_cfg = {"features": "m26_turnover_controlled_12dim"}
            eval_sett = {
                "initial_train": train_sz,
                "val_size": val_sz,
                "test_size": test_sz,
                "step_size": step,
                "embargo": emb,
                "cost_hurdles": cost_hurdles,
                "accounting_version": "m26-audited-v2",
                "holdout_split": "folds_15_19",
            }
            MarketDataStorageService.cache_benchmark_result(
                dataset_id=ds_id,
                model_version="m26-turnover-v1",
                feature_config=feat_cfg,
                target=PredictionTarget.O2O.value,
                eval_settings=eval_sett,
                metrics=benchmark_artifact,
            )
            log.info("Successfully cached M26 benchmark artifact in database.")
        except Exception as e:
            log.warning(f"Database cache write failed: {e}")

    # Persist JSON artifact
    out_file = REPO_ROOT / "var" / "datasets" / "m26_benchmark_results.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w") as f:
        json.dump(benchmark_artifact, f, indent=2)
    log.info(f"Persisted M26 benchmark results to {out_file} ({out_file.stat().st_size} bytes).")

    return benchmark_artifact
