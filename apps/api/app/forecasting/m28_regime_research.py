"""Milestone M28: Causal Market Regime Detection & Volatility Gate Engine.

Prepared strictly for research and validation.
Live trading, paper trading, and forecast approval are strictly disabled.
All safety invariants remain hardcoded to False.

Core Objectives:
1. Address the #1 root cause of strategy failure identified in M26 & M27:
   Churn and losses during Sideways Consolidation regimes.
2. Implement causal, point-in-time regime indicators:
   - Wilder's Average Directional Index (ADX, +DI, -DI) with causal EMA smoothing.
   - ATR Expansion/Contraction Ratio.
   - Causal Hurst Exponent estimation.
3. Classify market into 3 explicit regimes:
   - TRENDING_BULL (Strong directional upside)
   - TRENDING_BEAR (Strong directional downside)
   - SIDEWAYS_CONSOLIDATION (Choppy range, low trend strength)
4. Enforce strict NO_TRADE gate when market is in SIDEWAYS_CONSOLIDATION:
   Position is clamped to 0.0 (Cash), preventing whipsaw losses.
5. Benchmark regime-filtered models against unconstrained models on Half-Day and 1-Hour swing data.
"""

from __future__ import annotations

import enum
import json
import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression, RidgeClassifier
from sklearn.preprocessing import StandardScaler

try:
    import lightgbm as lgb
    HAS_LIGHTGBM = True
except ImportError:
    HAS_LIGHTGBM = False

try:
    import xgboost as xgb
    HAS_XGBOOST = True
except ImportError:
    HAS_XGBOOST = False

from app.forecasting.m27_htf_research import (
    HTFCandle,
    HTFInterval,
    extract_htf_features_and_targets,
    resample_candles_to_htf,
)
from app.forecasting.metrics import binary_metrics
from app.settings import REPO_ROOT

log = logging.getLogger("imm.m28_regime_research")


class MarketRegime(str, enum.Enum):
    TRENDING_BULL = "TRENDING_BULL"
    TRENDING_BEAR = "TRENDING_BEAR"
    SIDEWAYS_CONSOLIDATION = "SIDEWAYS_CONSOLIDATION"


@dataclass
class RegimeIndicators:
    adx: float
    plus_di: float
    minus_di: float
    atr: float
    atr_ratio: float
    hurst: float
    regime: MarketRegime


@dataclass
class RegimeFilteredRow:
    index: int
    timestamp: str
    candle: HTFCandle
    features: list[float]
    regime_indicators: RegimeIndicators
    regime: MarketRegime
    exec_price_open: float | None
    target_price_open: float | None
    target_return: float | None
    target_binary: int | None


@dataclass
class M28FoldMetrics:
    fold_index: int
    model_name: str
    strategy_mode: str  # "unconstrained", "regime_gated", "regime_consensus"
    accuracy: float
    brier_score: float
    brier_skill_score: float
    gross_return_0bps: float
    net_return_2bps: float
    net_return_5bps: float
    net_return_10bps: float
    turnover_units: float
    order_count: int
    max_drawdown_2bps: float
    bars_active_pct: float
    win_rate: float


# ==============================================================================
# 1. CAUSAL REGIME INDICATOR CALCULATION
# ==============================================================================

def compute_causal_adx_and_regimes(
    candles: list[HTFCandle],
    adx_period: int = 14,
    adx_threshold: float = 20.0,
    hurst_window: int = 30,
) -> list[RegimeIndicators]:
    """Compute point-in-time ADX, +DI, -DI, ATR ratio, Hurst Exponent, and Regime.
    
    Strictly causal: Indicator at index t only uses candles[0 : t+1].
    """
    n = len(candles)
    indicators: list[RegimeIndicators] = []

    if n < adx_period + 2:
        for _ in range(n):
            indicators.append(
                RegimeIndicators(
                    adx=0.0, plus_di=0.0, minus_di=0.0, atr=0.0,
                    atr_ratio=1.0, hurst=0.50, regime=MarketRegime.SIDEWAYS_CONSOLIDATION,
                )
            )
        return indicators

    # Step 1: True Range and Directional Movements
    tr = [0.0] * n
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n

    for i in range(1, n):
        h = candles[i].high
        l = candles[i].low
        prev_c = candles[i - 1].close
        prev_h = candles[i - 1].high
        prev_l = candles[i - 1].low

        # True Range
        tr[i] = max(h - l, abs(h - prev_c), abs(l - prev_c))

        # Directional Movement
        up_move = h - prev_h
        down_move = prev_l - l

        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        else:
            plus_dm[i] = 0.0

        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move
        else:
            minus_dm[i] = 0.0

    # Step 2: Wilder's Smoothing for ATR, +DI, -DI
    atr = [0.0] * n
    smooth_plus_dm = [0.0] * n
    smooth_minus_dm = [0.0] * n
    adx = [0.0] * n

    # Initial sums
    if n >= adx_period:
        atr[adx_period - 1] = sum(tr[1:adx_period])
        smooth_plus_dm[adx_period - 1] = sum(plus_dm[1:adx_period])
        smooth_minus_dm[adx_period - 1] = sum(minus_dm[1:adx_period])

    dx = [0.0] * n

    for i in range(adx_period, n):
        # Wilder smoothing: prev_val - (prev_val / period) + current_val
        atr[i] = atr[i - 1] - (atr[i - 1] / adx_period) + tr[i]
        smooth_plus_dm[i] = smooth_plus_dm[i - 1] - (smooth_plus_dm[i - 1] / adx_period) + plus_dm[i]
        smooth_minus_dm[i] = smooth_minus_dm[i - 1] - (smooth_minus_dm[i - 1] / adx_period) + minus_dm[i]

        p_di = (smooth_plus_dm[i] / (atr[i] + 1e-6)) * 100.0
        m_di = (smooth_minus_dm[i] / (atr[i] + 1e-6)) * 100.0
        di_sum = p_di + m_di
        dx[i] = (abs(p_di - m_di) / (di_sum + 1e-6)) * 100.0 if di_sum > 0 else 0.0

    # Smooth DX into ADX
    adx_start = 2 * adx_period - 1
    if n >= adx_start:
        adx[adx_start - 1] = float(np.mean(dx[adx_period:adx_start]))
        for i in range(adx_start, n):
            adx[i] = ((adx[i - 1] * (adx_period - 1)) + dx[i]) / adx_period

    # Step 3: Rolling ATR Ratio & Hurst Exponent
    for i in range(n):
        if i < adx_start:
            indicators.append(
                RegimeIndicators(
                    adx=0.0, plus_di=0.0, minus_di=0.0, atr=atr[i] / adx_period if atr[i] > 0 else 0.0,
                    atr_ratio=1.0, hurst=0.50, regime=MarketRegime.SIDEWAYS_CONSOLIDATION,
                )
            )
            continue

        curr_atr = atr[i] / adx_period
        # Rolling baseline ATR over past 28 bars
        past_atrs = [atr[j] / adx_period for j in range(max(0, i - 28), i + 1)]
        base_atr = float(np.mean(past_atrs)) if past_atrs else curr_atr
        atr_ratio = curr_atr / (base_atr + 1e-6)

        # Causal Hurst Exponent estimation (Rescaled Range R/S analysis on past window)
        w_start = max(0, i - hurst_window + 1)
        window_closes = [candles[j].close for j in range(w_start, i + 1)]
        if len(window_closes) >= 16:
            diffs = np.diff(window_closes)
            mean_diff = np.mean(diffs)
            cum_dev = np.cumsum(diffs - mean_diff)
            r_val = np.max(cum_dev) - np.min(cum_dev)
            s_val = np.std(diffs) + 1e-6
            r_s = max(r_val / s_val, 1e-4)
            hurst = float(np.log(r_s) / np.log(len(diffs)))
            # Clamp hurst to [0.1, 0.9]
            hurst = max(0.1, min(0.9, hurst))
        else:
            hurst = 0.50

        # Current +DI and -DI
        p_di = (smooth_plus_dm[i] / (atr[i] + 1e-6)) * 100.0
        m_di = (smooth_minus_dm[i] / (atr[i] + 1e-6)) * 100.0
        curr_adx = adx[i]
        di_diff = abs(p_di - m_di)

        # Classification rule:
        # A market is in SIDEWAYS_CONSOLIDATION if:
        # - ADX is below trend threshold (< adx_threshold), OR
        # - Directional spread is narrow (di_diff < 15.0), OR
        # - Volatility has severely contracted (atr_ratio < 0.70), OR
        # - Hurst exponent indicates mean-reversion (< 0.45).
        is_trending = (
            curr_adx >= adx_threshold
            and di_diff >= 15.0
            and atr_ratio >= 0.70
            and hurst >= 0.45
        )

        if is_trending:
            if p_di > m_di:
                regime = MarketRegime.TRENDING_BULL
            else:
                regime = MarketRegime.TRENDING_BEAR
        else:
            regime = MarketRegime.SIDEWAYS_CONSOLIDATION

        indicators.append(
            RegimeIndicators(
                adx=curr_adx,
                plus_di=p_di,
                minus_di=m_di,
                atr=curr_atr,
                atr_ratio=atr_ratio,
                hurst=hurst,
                regime=regime,
            )
        )

    return indicators


# ==============================================================================
# 2. FEATURE ROWS & REGIME ALIGNMENT
# ==============================================================================

def extract_regime_aligned_features(
    candles: list[HTFCandle],
) -> list[RegimeFilteredRow]:
    """Extract causal features, compute causal regime indicators, and align strict O2O targets."""
    features_base, feat_names = extract_htf_features_and_targets(candles)
    regime_indicators = compute_causal_adx_and_regimes(candles)

    aligned_rows: list[RegimeFilteredRow] = []

    for f_row in features_base:
        t = f_row.index
        reg_ind = regime_indicators[t]

        # Append regime indicator features to ML feature vector
        extended_features = list(f_row.features) + [
            reg_ind.adx / 100.0,
            (reg_ind.plus_di - reg_ind.minus_di) / 100.0,
            reg_ind.atr_ratio,
            reg_ind.hurst,
            1.0 if reg_ind.regime == MarketRegime.TRENDING_BULL else 0.0,
            1.0 if reg_ind.regime == MarketRegime.TRENDING_BEAR else 0.0,
        ]

        aligned_rows.append(
            RegimeFilteredRow(
                index=t,
                timestamp=f_row.timestamp,
                candle=candles[t],
                features=extended_features,
                regime_indicators=reg_ind,
                regime=reg_ind.regime,
                exec_price_open=f_row.exec_price_open,
                target_price_open=f_row.target_price_open,
                target_return=f_row.target_return,
                target_binary=f_row.target_binary,
            )
        )

    return aligned_rows


# ==============================================================================
# 3. REGIME FILTERING TRADING ENGINE & BENCHMARK RUNNER
# ==============================================================================

def run_regime_walk_forward_benchmark(
    candles_15m: list[list[Any]],
    dataset_id: str,
    interval: HTFInterval = HTFInterval.HALF_DAY,
    initial_train_bars: int = 200,
    val_step_bars: int = 20,
    embargo_bars: int = 2,
    holdout_fold_count: int = 4,
    adx_threshold: float = 20.0,
) -> dict[str, Any]:
    """Execute walk-forward benchmark comparing unconstrained models vs regime-gated models."""
    log.info(f"Starting M28 Regime Benchmark for {interval.value} with ADX threshold {adx_threshold}.")

    # Resample candles
    htf_candles = resample_candles_to_htf(candles_15m, target_interval=interval)
    aligned_rows = extract_regime_aligned_features(htf_candles)
    # Filter rows with complete targets
    valid_rows = [r for r in aligned_rows if r.target_binary is not None and r.target_return is not None]
    total_valid = len(valid_rows)

    if total_valid < initial_train_bars + val_step_bars:
        raise ValueError(f"Insufficient samples ({total_valid}) for walk-forward evaluation.")

    # Folds
    folds: list[tuple[int, int, int, int]] = []
    curr_train_end = initial_train_bars

    while curr_train_end + embargo_bars + val_step_bars <= total_valid:
        val_start = curr_train_end + embargo_bars
        val_end = min(val_start + val_step_bars, total_valid)
        folds.append((0, curr_train_end, val_start, val_end))
        curr_train_end += val_step_bars

    num_folds = len(folds)
    holdout_start_fold = max(1, num_folds - holdout_fold_count + 1)

    model_names = ["empirical_prior", "logistic_regression", "ridge"]
    if HAS_LIGHTGBM:
        model_names.append("lightgbm")
    if HAS_XGBOOST:
        model_names.append("xgboost")

    # Strategy modes to evaluate
    strategy_modes = [
        "unconstrained",      # Classic +/- 1.0 on every bar
        "regime_gated",       # If Sideways, position = 0.0 (Cash). Otherwise model direction.
        "regime_consensus",   # Only take Long if Model says Long AND Regime is Bull; Short if Model Short AND Regime Bear.
    ]

    fold_metrics_list: list[dict[str, Any]] = []

    cost_0bps = 0.0
    cost_2bps = 0.0002
    cost_5bps = 0.0005
    cost_10bps = 0.0010

    for fold_idx, (train_s, train_e, val_s, val_e) in enumerate(folds, 1):
        train_data = valid_rows[train_s:train_e]
        val_data = valid_rows[val_s:val_e]

        y_train = np.array([r.target_binary for r in train_data], dtype=int)
        y_val = np.array([r.target_binary for r in val_data], dtype=int)
        val_returns = np.array([r.target_return for r in val_data], dtype=float)
        val_regimes = [r.regime for r in val_data]

        scaler = StandardScaler()
        X_train = scaler.fit_transform(np.array([r.features for r in train_data]))
        X_val = scaler.transform(np.array([r.features for r in val_data]))

        p_base = float(np.mean(y_train))

        for m_name in model_names:
            if m_name == "empirical_prior":
                p_val = np.full(len(y_val), p_base)
            elif m_name == "logistic_regression":
                clf = LogisticRegression(C=1.0, max_iter=500, random_state=42)
                clf.fit(X_train, y_train)
                p_val = clf.predict_proba(X_val)[:, 1]
            elif m_name == "ridge":
                clf = RidgeClassifier(alpha=1.0, random_state=42)
                clf.fit(X_train, y_train)
                dec = clf.decision_function(X_val)
                p_val = 1.0 / (1.0 + np.exp(-dec))
            elif m_name == "lightgbm":
                clf = lgb.LGBMClassifier(
                    n_estimators=50, max_depth=3, num_leaves=7,
                    learning_rate=0.05, min_child_samples=15, random_state=42, verbose=-1,
                )
                clf.fit(X_train, y_train)
                p_val = clf.predict_proba(X_val)[:, 1]
            elif m_name == "xgboost":
                clf = xgb.XGBClassifier(
                    n_estimators=50, max_depth=3, learning_rate=0.05, random_state=42, eval_metric="logloss",
                )
                clf.fit(X_train, y_train)
                p_val = clf.predict_proba(X_val)[:, 1]
            else:
                continue

            bm = binary_metrics(y_val.tolist(), p_val.tolist())
            acc_val = float(bm["accuracy"]["value"]) if bm.get("accuracy") and bm["accuracy"].get("value") is not None else 0.0
            brier_val = float(bm["brier"]["value"]) if bm.get("brier") and bm["brier"].get("value") is not None else 0.25
            ref_brier = max(p_base * (1.0 - p_base), 1e-6)
            bss_val = (1.0 - (brier_val / ref_brier)) * 100.0

            # Raw unconstrained direction (+1 or -1)
            raw_direction = np.where(p_val > 0.50, 1.0, -1.0)

            for mode in strategy_modes:
                positions = np.zeros(len(val_data))

                for i in range(len(val_data)):
                    reg = val_regimes[i]
                    raw_dir = raw_direction[i]

                    if mode == "unconstrained":
                        positions[i] = raw_dir
                    elif mode == "regime_gated":
                        if reg == MarketRegime.SIDEWAYS_CONSOLIDATION:
                            positions[i] = 0.0  # Cash (NO_TRADE)
                        else:
                            positions[i] = raw_dir
                    elif mode == "regime_consensus":
                        if reg == MarketRegime.TRENDING_BULL and raw_dir > 0:
                            positions[i] = 1.0
                        elif reg == MarketRegime.TRENDING_BEAR and raw_dir < 0:
                            positions[i] = -1.0
                        else:
                            positions[i] = 0.0  # Conflict or Sideways -> Cash (NO_TRADE)

                # Accounting simulation
                turnover_units = 0.0
                order_count = 0
                prev_pos = 0.0

                r_net_0 = []
                r_net_2 = []
                r_net_5 = []
                r_net_10 = []

                for t_idx, pos in enumerate(positions):
                    pos_delta = abs(pos - prev_pos)
                    if pos_delta > 0.0:
                        order_count += 1
                        turnover_units += pos_delta / 2.0

                    gross_r = pos * val_returns[t_idx]
                    r_net_0.append(gross_r - (pos_delta * cost_0bps))
                    r_net_2.append(gross_r - (pos_delta * cost_2bps))
                    r_net_5.append(gross_r - (pos_delta * cost_5bps))
                    r_net_10.append(gross_r - (pos_delta * cost_10bps))

                    prev_pos = pos

                ret_0 = float(np.prod(1.0 + np.array(r_net_0)) - 1.0) * 100.0
                ret_2 = float(np.prod(1.0 + np.array(r_net_2)) - 1.0) * 100.0
                ret_5 = float(np.prod(1.0 + np.array(r_net_5)) - 1.0) * 100.0
                ret_10 = float(np.prod(1.0 + np.array(r_net_10)) - 1.0) * 100.0

                cum_equity = np.cumprod(1.0 + np.array(r_net_2))
                peaks = np.maximum.accumulate(cum_equity)
                drawdowns = (peaks - cum_equity) / peaks
                max_dd_2bps = float(np.max(drawdowns)) * 100.0 if len(drawdowns) > 0 else 0.0

                active_bars = sum(1 for p in positions if abs(p) > 0.0)
                active_pct = (active_bars / len(positions)) * 100.0 if positions.size > 0 else 0.0

                active_returns = [r for pos, r in zip(positions, r_net_2) if abs(pos) > 0.0]
                win_count = sum(1 for r in active_returns if r > 0)
                win_rate = (win_count / len(active_returns)) * 100.0 if active_returns else 0.0

                fold_m = M28FoldMetrics(
                    fold_index=fold_idx,
                    model_name=m_name,
                    strategy_mode=mode,
                    accuracy=acc_val,
                    brier_score=brier_val,
                    brier_skill_score=bss_val,
                    gross_return_0bps=ret_0,
                    net_return_2bps=ret_2,
                    net_return_5bps=ret_5,
                    net_return_10bps=ret_10,
                    turnover_units=turnover_units,
                    order_count=order_count,
                    max_drawdown_2bps=max_dd_2bps,
                    bars_active_pct=active_pct,
                    win_rate=win_rate,
                )
                fold_metrics_list.append(asdict(fold_m))

    # Aggregate by model and strategy mode
    aggregated: dict[str, Any] = {}

    for m_name in model_names:
        aggregated[m_name] = {}
        for mode in strategy_modes:
            matching = [f for f in fold_metrics_list if f["model_name"] == m_name and f["strategy_mode"] == mode]
            dev_matching = [f for f in matching if f["fold_index"] < holdout_start_fold]
            holdout_matching = [f for f in matching if f["fold_index"] >= holdout_start_fold]

            def _mean(lst: list[dict], key: str) -> float:
                v = [x[key] for x in lst]
                return float(np.mean(v)) if v else 0.0

            aggregated[m_name][mode] = {
                "all_folds": {
                    "mean_net_return_2bps": _mean(matching, "net_return_2bps"),
                    "mean_net_return_0bps": _mean(matching, "gross_return_0bps"),
                    "total_turnover_units": sum(x["turnover_units"] for x in matching),
                    "mean_max_drawdown_2bps": _mean(matching, "max_drawdown_2bps"),
                    "mean_bars_active_pct": _mean(matching, "bars_active_pct"),
                    "mean_win_rate": _mean(matching, "win_rate"),
                },
                "dev_folds": {
                    "fold_count": len(dev_matching),
                    "mean_net_return_2bps": _mean(dev_matching, "net_return_2bps"),
                    "total_turnover_units": sum(x["turnover_units"] for x in dev_matching),
                    "mean_max_drawdown_2bps": _mean(dev_matching, "max_drawdown_2bps"),
                },
                "holdout_folds": {
                    "fold_count": len(holdout_matching),
                    "mean_net_return_2bps": _mean(holdout_matching, "net_return_2bps"),
                    "total_turnover_units": sum(x["turnover_units"] for x in holdout_matching),
                    "mean_max_drawdown_2bps": _mean(holdout_matching, "max_drawdown_2bps"),
                },
            }

    # Summary of regime prevalence across full dataset
    all_regimes = [r.regime.value for r in valid_rows]
    regime_dist = {
        MarketRegime.TRENDING_BULL.value: all_regimes.count(MarketRegime.TRENDING_BULL.value) / len(all_regimes) * 100.0,
        MarketRegime.TRENDING_BEAR.value: all_regimes.count(MarketRegime.TRENDING_BEAR.value) / len(all_regimes) * 100.0,
        MarketRegime.SIDEWAYS_CONSOLIDATION.value: all_regimes.count(MarketRegime.SIDEWAYS_CONSOLIDATION.value) / len(all_regimes) * 100.0,
    }

    result = {
        "milestone": "M28",
        "description": "Causal Market Regime Detection & Volatility Gating Walk-Forward Benchmark",
        "interval": interval.value,
        "dataset_id": dataset_id,
        "adx_threshold": adx_threshold,
        "total_candles_15m": len(candles_15m),
        "total_htf_bars": len(htf_candles),
        "total_valid_samples": total_valid,
        "num_folds": num_folds,
        "holdout_start_fold": holdout_start_fold,
        "regime_distribution_pct": regime_dist,
        "models": aggregated,
        "fold_results": fold_metrics_list,
        "safety_invariants": {
            "forecast_ready": False,
            "real_market_data_verified": False,
            "paper_approved": False,
            "live_approved": False,
            "live_broker_routing_enabled": False,
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    out_file = REPO_ROOT / "var" / "datasets" / "m28_regime_benchmark_results.json"
    with open(out_file, "w") as f:
        json.dump(result, f, indent=2)

    log.info(f"Persisted M28 Regime Benchmark results to {out_file}")
    return result
