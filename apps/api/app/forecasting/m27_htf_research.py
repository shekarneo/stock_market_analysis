"""Milestone M27: Higher-Timeframe (1-Hour and 4-Hour Swing) Resampling,
Target Alignment, and Walk-Forward Research Engine.

Prepared strictly for research and validation.
Live trading, paper trading, and forecast approval are strictly disabled.
All safety invariants remain hardcoded to False.

Core Objectives:
1. Resample validated 15m continuous intraday candles into Higher-Timeframe (HTF)
   swing bars (1-Hour, Half-Day/4-Hour, and Daily) preserving strict point-in-time
   causal availability and session boundaries (no cross-day leakage).
2. Quantify the Alpha-to-Friction Ratio:
   Measure average bar price displacement E[|R|] vs 2 bps roundtrip transaction costs
   to empirically evaluate if HTF overcomes the 15m signal-to-noise deficit.
3. Strict Open-to-Open (O2O) Swing Target Alignment:
   Signal evaluated at Close of HTF bar k, executed at Open of bar k+1, target
   return measured from Open k+1 to Open k+2.
4. Expanding-Window Walk-Forward Cross-Validation:
   Chronological folds, train-only feature scaling, 2-bar label embargo.
5. Multi-Model Benchmark:
   Empirical Prior, Logistic Regression, Ridge, LightGBM, and XGBoost across
   multiple fee tiers (0 bps, 2 bps, 5 bps, 10 bps).
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

from app.forecasting.metrics import binary_metrics
from app.settings import REPO_ROOT

log = logging.getLogger("imm.m27_htf_research")


class HTFInterval(str, enum.Enum):
    ONE_HOUR = "1H"         # ~60 min blocks aligned to market open 09:15
    HALF_DAY = "HALF_DAY"   # 2 session bars per day: AM (09:15-12:15), PM (12:15-15:30)
    DAILY = "1D"           # 1 full session bar per day (09:15-15:30)


@dataclass
class HTFCandle:
    timestamp: str          # Close timestamp of the bar (point-in-time availability)
    open: float
    high: float
    low: float
    close: float
    volume: float
    open_interest: float
    constituent_bars: int
    session_date: str
    interval: HTFInterval


@dataclass
class HTFFeatureRow:
    index: int
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    # Features strictly <= t
    features: list[float]
    feature_names: list[str]
    # Execution prices and target
    exec_price_open: float | None     # O_{t+1} (Open of next HTF bar)
    target_price_open: float | None   # O_{t+2} (Open of bar t+2)
    target_return: float | None       # (O_{t+2} - O_{t+1}) / O_{t+1}
    target_binary: int | None         # 1 if target_return > 0 else 0


@dataclass
class HTFFoldMetrics:
    fold_index: int
    train_bars: int
    val_bars: int
    val_start: str
    val_end: str
    model_name: str
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
    win_rate: float


@dataclass
class HTFBenchmarkSummary:
    interval: str
    dataset_id: str
    total_15m_candles: int
    resampled_htf_candles: int
    aligned_sample_count: int
    num_folds: int
    mean_bar_displacement_pct: float
    fee_to_alpha_ratio_2bps_pct: float
    models: dict[str, Any]
    fold_results: list[dict[str, Any]]
    holdout_summary: dict[str, Any]
    safety_invariants: dict[str, bool]
    timestamp: str


# ==============================================================================
# 1. RESAMPLING ENGINE
# ==============================================================================

def parse_candle_date(ts_str: str) -> tuple[str, str]:
    """Parse 'YYYY-MM-DD HH:MM:SS' into (date_str, time_str)."""
    parts = ts_str.strip().split(" ")
    if len(parts) >= 2:
        return parts[0], parts[1]
    return ts_str[:10], ts_str[11:19]


def resample_candles_to_htf(
    raw_candles: list[list[Any]],
    target_interval: HTFInterval = HTFInterval.ONE_HOUR,
) -> list[HTFCandle]:
    """Resample 15m continuous intraday candles into Higher-Timeframe candles.
    
    Guarantees:
    - Point-in-time causality: resampled timestamp is the close of the final constituent 15m bar.
    - Zero cross-day leakage: groups strictly respect session_date.
    - Strict geometric integrity: High >= max(Open, Close), Low <= min(Open, Close).
    """
    if not raw_candles:
        return []

    # Group 15m candles by session date
    days: dict[str, list[list[Any]]] = {}
    for c in raw_candles:
        date_str, _ = parse_candle_date(str(c[0]))
        if date_str not in days:
            days[date_str] = []
        days[date_str].append(c)

    resampled: list[HTFCandle] = []

    for date_str, session_candles in days.items():
        if target_interval == HTFInterval.DAILY:
            # 1 full bar per day
            group_buckets = [session_candles]
        elif target_interval == HTFInterval.HALF_DAY:
            # AM (09:15 - 12:15, first 12 bars) and PM (12:15 - 15:30, remaining 13 bars)
            # In general, split into two equal halves based on time
            am_bars = []
            pm_bars = []
            for c in session_candles:
                _, time_str = parse_candle_date(str(c[0]))
                if time_str < "12:15:00":
                    am_bars.append(c)
                else:
                    pm_bars.append(c)
            group_buckets = [b for b in [am_bars, pm_bars] if b]
        elif target_interval == HTFInterval.ONE_HOUR:
            # 4 x 15m bars per hour:
            # 09:15–10:15 (4 bars), 10:15–11:15 (4 bars), 11:15–12:15 (4 bars),
            # 12:15–13:15 (4 bars), 13:15–14:15 (4 bars), 14:15–15:15 (4 bars),
            # 15:15–15:30 (1 tail bar of 15m)
            group_buckets = []
            current_bucket = []
            for idx, c in enumerate(session_candles):
                current_bucket.append(c)
                # Form bucket after every 4 bars or at end of session
                if len(current_bucket) == 4 or idx == len(session_candles) - 1:
                    group_buckets.append(current_bucket)
                    current_bucket = []
        else:
            raise ValueError(f"Unsupported HTF interval: {target_interval}")

        for bucket in group_buckets:
            if not bucket:
                continue
            first_c = bucket[0]
            last_c = bucket[-1]

            b_open = float(first_c[1])
            b_high = max(float(x[2]) for x in bucket)
            b_low = min(float(x[3]) for x in bucket)
            b_close = float(last_c[4])
            b_vol = sum(float(x[5]) for x in bucket)
            b_oi = float(last_c[6]) if len(last_c) > 6 else 0.0

            # Point-in-time timestamp: close of the final constituent bar
            close_ts = str(last_c[0])

            # Geometric validation
            assert b_high >= b_low, f"High {b_high} < Low {b_low} on {close_ts}"
            assert b_high >= max(b_open, b_close) - 1e-4, f"High lower than open/close on {close_ts}"
            assert b_low <= min(b_open, b_close) + 1e-4, f"Low higher than open/close on {close_ts}"

            resampled.append(
                HTFCandle(
                    timestamp=close_ts,
                    open=b_open,
                    high=b_high,
                    low=b_low,
                    close=b_close,
                    volume=b_vol,
                    open_interest=b_oi,
                    constituent_bars=len(bucket),
                    session_date=date_str,
                    interval=target_interval,
                )
            )

    return resampled


# ==============================================================================
# 2. FEATURE EXTRACTION & STRICT O2O TARGET ALIGNMENT
# ==============================================================================

def extract_htf_features_and_targets(
    candles: list[HTFCandle],
) -> tuple[list[HTFFeatureRow], list[str]]:
    """Extract causal features and align strict Open-to-Open (O2O) swing targets.
    
    Target Semantics:
    At bar t (closing at T_t):
      - Features X_t use prices strictly <= T_t.
      - Trade signal is submitted and executed at Open of bar t+1 (O_{t+1}).
      - Target return is (O_{t+2} - O_{t+1}) / O_{t+1}.
      - Target binary label is 1 if target_return > 0 else 0.
    
    Rows where t+2 does not exist (the final 2 bars) have None for target.
    """
    feature_names = [
        "ret_1",          # 1-bar return
        "ret_2",          # 2-bar return
        "ret_4",          # 4-bar return
        "ret_8",          # 8-bar return
        "vol_4",          # 4-bar Parkinson volatility
        "vol_8",          # 8-bar standard deviation of returns
        "bar_spread",     # (High - Low) / Close
        "bar_pos",        # (Close - Low) / (High - Low + eps)
        "body_ratio",     # (Close - Open) / (High - Low + eps)
        "vol_ratio",      # Volume / rolling 8-bar average volume
        "sin_tod",        # Cyclical time-of-day sine
        "cos_tod",        # Cyclical time-of-day cosine
        "trend_hh_ll",    # Higher-High / Lower-Low indicator (+1, -1, 0)
    ]

    n = len(candles)
    rows: list[HTFFeatureRow] = []

    # Warm-up requirement for 8-bar lookback
    warmup = 9

    for t in range(warmup, n):
        c_t = candles[t].close
        c_prev = candles[t - 1].close
        c_t2 = candles[t - 2].close
        c_t4 = candles[t - 4].close
        c_t8 = candles[t - 8].close

        # 1. Causal returns
        ret_1 = (c_t - c_prev) / (c_prev + 1e-6)
        ret_2 = (c_t - c_t2) / (c_t2 + 1e-6)
        ret_4 = (c_t - c_t4) / (c_t4 + 1e-6)
        ret_8 = (c_t - c_t8) / (c_t8 + 1e-6)

        # 2. Volatilities (strictly causal window t-7 to t)
        ret_window = [
            (candles[i].close - candles[i - 1].close) / (candles[i - 1].close + 1e-6)
            for i in range(t - 7, t + 1)
        ]
        vol_8 = float(np.std(ret_window)) if len(ret_window) > 1 else 0.0

        # Parkinson volatility over last 4 bars
        park_sum = sum(
            (math.log(candles[i].high / (candles[i].low + 1e-6))) ** 2
            for i in range(t - 3, t + 1)
        )
        vol_4 = math.sqrt(park_sum / (4.0 * math.log(4.0)))

        # 3. Bar shape & spread
        h_t = candles[t].high
        l_t = candles[t].low
        o_t = candles[t].open
        rng = max(h_t - l_t, 1e-4)

        bar_spread = rng / (c_t + 1e-6)
        bar_pos = (c_t - l_t) / rng
        body_ratio = (c_t - o_t) / rng

        # 4. Volume ratio
        v_t = candles[t].volume
        v_avg = np.mean([candles[i].volume for i in range(t - 7, t + 1)])
        vol_ratio = float(v_t / (v_avg + 1e-6))

        # 5. Cyclical time of day
        _, time_str = parse_candle_date(candles[t].timestamp)
        h_val = float(time_str[:2]) + float(time_str[3:5]) / 60.0
        # Normal session span: 9.25 to 15.5
        norm_time = (h_val - 9.25) / 6.25
        sin_tod = math.sin(2.0 * math.pi * norm_time)
        cos_tod = math.cos(2.0 * math.pi * norm_time)

        # 6. Trend indicator: Higher-High & Higher-Low vs 4 bars ago
        hh = h_t > candles[t - 4].high
        ll = l_t < candles[t - 4].low
        if hh and not ll:
            trend_hh_ll = 1.0
        elif ll and not hh:
            trend_hh_ll = -1.0
        else:
            trend_hh_ll = 0.0

        feat_vec = [
            ret_1, ret_2, ret_4, ret_8,
            vol_4, vol_8, bar_spread, bar_pos, body_ratio, vol_ratio,
            sin_tod, cos_tod, trend_hh_ll,
        ]

        # Target alignment: Next-bar Open O_{t+1} to O_{t+2}
        if t + 2 < n:
            exec_open = candles[t + 1].open
            target_open = candles[t + 2].open
            target_ret = (target_open - exec_open) / (exec_open + 1e-6)
            target_bin = 1 if target_ret > 0 else 0
        else:
            exec_open = candles[t + 1].open if t + 1 < n else None
            target_open = None
            target_ret = None
            target_bin = None

        rows.append(
            HTFFeatureRow(
                index=t,
                timestamp=candles[t].timestamp,
                open=o_t,
                high=h_t,
                low=l_t,
                close=c_t,
                volume=v_t,
                features=feat_vec,
                feature_names=feature_names,
                exec_price_open=exec_open,
                target_price_open=target_open,
                target_return=target_ret,
                target_binary=target_bin,
            )
        )

    return rows, feature_names


# ==============================================================================
# 3. WALK-FORWARD RUNNER & MODEL EVALUATION
# ==============================================================================

def run_htf_walk_forward_benchmark(
    candles_15m: list[list[Any]],
    dataset_id: str,
    interval: HTFInterval = HTFInterval.ONE_HOUR,
    initial_train_bars: int = 500,
    val_step_bars: int = 50,
    embargo_bars: int = 2,
    holdout_fold_count: int = 4,
) -> HTFBenchmarkSummary:
    """Run an expanding-window chronological walk-forward benchmark on HTF candles."""
    log.info(f"Starting M27 HTF Benchmark for {interval.value} on {len(candles_15m)} 15m candles.")

    # Step 1: Resample
    htf_candles = resample_candles_to_htf(candles_15m, target_interval=interval)
    log.info(f"Resampled to {len(htf_candles)} {interval.value} candles.")

    # Step 2: Features and strict O2O targets
    feature_rows, feat_names = extract_htf_features_and_targets(htf_candles)
    # Filter only rows with valid targets
    aligned_rows = [r for r in feature_rows if r.target_binary is not None and r.target_return is not None]
    total_aligned = len(aligned_rows)

    if total_aligned < initial_train_bars + val_step_bars:
        raise ValueError(
            f"Not enough aligned rows ({total_aligned}) for initial_train {initial_train_bars} + val_step {val_step_bars}"
        )

    # Calculate fundamental bar displacement statistics
    abs_returns = [abs(r.target_return) for r in aligned_rows]
    mean_displacement = float(np.mean(abs_returns)) if abs_returns else 0.0
    # Fee to alpha ratio at 2 bps roundtrip (0.04% = 0.0004)
    fee_to_alpha_ratio = (0.0004 / mean_displacement) * 100.0 if mean_displacement > 0 else 0.0

    # Step 3: Compute Folds
    folds: list[tuple[int, int, int, int]] = []
    current_train_end = initial_train_bars

    while current_train_end + embargo_bars + val_step_bars <= total_aligned:
        val_start = current_train_end + embargo_bars
        val_end = min(val_start + val_step_bars, total_aligned)
        folds.append((0, current_train_end, val_start, val_end))
        current_train_end += val_step_bars

    num_folds = len(folds)
    log.info(f"Generated {num_folds} walk-forward folds. Partitioning last {holdout_fold_count} folds as Holdout.")

    # Model types
    model_names = ["empirical_prior", "logistic_regression", "ridge"]
    if HAS_LIGHTGBM:
        model_names.append("lightgbm")
    if HAS_XGBOOST:
        model_names.append("xgboost")

    fold_metrics_list: list[dict[str, Any]] = []

    # Cost hurdles in bps
    cost_0bps = 0.0
    cost_2bps = 0.0002
    cost_5bps = 0.0005
    cost_10bps = 0.0010

    for fold_idx, (train_s, train_e, val_s, val_e) in enumerate(folds, 1):
        train_data = aligned_rows[train_s:train_e]
        val_data = aligned_rows[val_s:val_e]

        y_train = np.array([r.target_binary for r in train_data], dtype=int)
        y_val = np.array([r.target_binary for r in val_data], dtype=int)
        val_returns = np.array([r.target_return for r in val_data], dtype=float)

        # Scale features strictly fit on train
        scaler = StandardScaler()
        X_train = scaler.fit_transform(np.array([r.features for r in train_data]))
        X_val = scaler.transform(np.array([r.features for r in val_data]))

        # Empirical base rate
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
                # Sigmoid transform to probability
                p_val = 1.0 / (1.0 + np.exp(-dec))
            elif m_name == "lightgbm":
                clf = lgb.LGBMClassifier(
                    n_estimators=50,
                    max_depth=3,
                    num_leaves=7,
                    learning_rate=0.05,
                    min_child_samples=15,
                    random_state=42,
                    verbose=-1,
                )
                clf.fit(X_train, y_train)
                p_val = clf.predict_proba(X_val)[:, 1]
            elif m_name == "xgboost":
                clf = xgb.XGBClassifier(
                    n_estimators=50,
                    max_depth=3,
                    learning_rate=0.05,
                    random_state=42,
                    eval_metric="logloss",
                )
                clf.fit(X_train, y_train)
                p_val = clf.predict_proba(X_val)[:, 1]
            else:
                continue

            # Binary metrics
            bm = binary_metrics(y_val.tolist(), p_val.tolist())
            acc_val = float(bm["accuracy"]["value"]) if bm.get("accuracy") and bm["accuracy"].get("value") is not None else 0.0
            brier_val = float(bm["brier"]["value"]) if bm.get("brier") and bm["brier"].get("value") is not None else 0.25
            ref_brier = max(p_base * (1.0 - p_base), 1e-6)
            bss_val = (1.0 - (brier_val / ref_brier)) * 100.0

            # Trading simulation: O2O signal
            # Position: +1 if p > 0.50 else -1
            positions = np.where(p_val > 0.50, 1.0, -1.0)
            
            # Position transitions & turnover
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
                    turnover_units += pos_delta / 2.0  # 1.0 unit per full roundtrip entry/exit
                
                gross_r = pos * val_returns[t_idx]
                r_net_0.append(gross_r - (pos_delta * cost_0bps))
                r_net_2.append(gross_r - (pos_delta * cost_2bps))
                r_net_5.append(gross_r - (pos_delta * cost_5bps))
                r_net_10.append(gross_r - (pos_delta * cost_10bps))

                prev_pos = pos

            # Compounded equity returns
            ret_0 = float(np.prod(1.0 + np.array(r_net_0)) - 1.0) * 100.0
            ret_2 = float(np.prod(1.0 + np.array(r_net_2)) - 1.0) * 100.0
            ret_5 = float(np.prod(1.0 + np.array(r_net_5)) - 1.0) * 100.0
            ret_10 = float(np.prod(1.0 + np.array(r_net_10)) - 1.0) * 100.0

            # Max drawdown on 2 bps equity curve
            cum_equity = np.cumprod(1.0 + np.array(r_net_2))
            peaks = np.maximum.accumulate(cum_equity)
            drawdowns = (peaks - cum_equity) / peaks
            max_dd_2bps = float(np.max(drawdowns)) * 100.0 if len(drawdowns) > 0 else 0.0

            win_count = sum(1 for r in r_net_2 if r > 0)
            win_rate = (win_count / len(r_net_2)) * 100.0 if r_net_2 else 0.0

            fold_m = HTFFoldMetrics(
                fold_index=fold_idx,
                train_bars=len(train_data),
                val_bars=len(val_data),
                val_start=val_data[0].timestamp,
                val_end=val_data[-1].timestamp,
                model_name=m_name,
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
                win_rate=win_rate,
            )
            fold_metrics_list.append(asdict(fold_m))

    # Step 4: Aggregate Models across Folds
    holdout_start_fold = max(1, num_folds - holdout_fold_count + 1)
    model_summaries: dict[str, Any] = {}
    holdout_summaries: dict[str, Any] = {}

    for m_name in model_names:
        all_fold_res = [f for f in fold_metrics_list if f["model_name"] == m_name]
        dev_fold_res = [f for f in all_fold_res if f["fold_index"] < holdout_start_fold]
        holdout_fold_res = [f for f in all_fold_res if f["fold_index"] >= holdout_start_fold]

        def _avg(lst: list[dict], key: str) -> float:
            vals = [x[key] for x in lst]
            return float(np.mean(vals)) if vals else 0.0

        model_summaries[m_name] = {
            "all_folds": {
                "mean_accuracy": _avg(all_fold_res, "accuracy"),
                "mean_brier_score": _avg(all_fold_res, "brier_score"),
                "mean_brier_skill_score": _avg(all_fold_res, "brier_skill_score"),
                "mean_gross_return_0bps": _avg(all_fold_res, "gross_return_0bps"),
                "mean_net_return_2bps": _avg(all_fold_res, "net_return_2bps"),
                "mean_net_return_5bps": _avg(all_fold_res, "net_return_5bps"),
                "mean_net_return_10bps": _avg(all_fold_res, "net_return_10bps"),
                "total_turnover_units": sum(x["turnover_units"] for x in all_fold_res),
                "total_order_count": sum(x["order_count"] for x in all_fold_res),
                "mean_max_drawdown_2bps": _avg(all_fold_res, "max_drawdown_2bps"),
                "mean_win_rate": _avg(all_fold_res, "win_rate"),
            },
            "dev_folds": {
                "fold_count": len(dev_fold_res),
                "mean_net_return_2bps": _avg(dev_fold_res, "net_return_2bps"),
                "mean_accuracy": _avg(dev_fold_res, "accuracy"),
            },
            "holdout_folds": {
                "fold_count": len(holdout_fold_res),
                "mean_net_return_2bps": _avg(holdout_fold_res, "net_return_2bps"),
                "mean_accuracy": _avg(holdout_fold_res, "accuracy"),
                "mean_gross_return_0bps": _avg(holdout_fold_res, "gross_return_0bps"),
                "total_turnover_units": sum(x["turnover_units"] for x in holdout_fold_res),
            },
        }

    summary = HTFBenchmarkSummary(
        interval=interval.value,
        dataset_id=dataset_id,
        total_15m_candles=len(candles_15m),
        resampled_htf_candles=len(htf_candles),
        aligned_sample_count=total_aligned,
        num_folds=num_folds,
        mean_bar_displacement_pct=mean_displacement * 100.0,
        fee_to_alpha_ratio_2bps_pct=fee_to_alpha_ratio,
        models=model_summaries,
        fold_results=fold_metrics_list,
        holdout_summary={
            "holdout_start_fold": holdout_start_fold,
            "holdout_fold_count": len(folds) - holdout_start_fold + 1,
        },
        safety_invariants={
            "forecast_ready": False,
            "real_market_data_verified": False,
            "paper_approved": False,
            "live_approved": False,
            "live_broker_routing_enabled": False,
        },
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    return summary


def run_and_save_htf_benchmarks() -> dict[str, Any]:
    """Execute both 1-Hour and Half-Day swing benchmarks and save results."""
    m23_dataset_file = REPO_ROOT / "var" / "datasets" / "derived_nifty_15m_m23_bc7d31bceebf13a3.json"
    if not m23_dataset_file.exists():
        raise FileNotFoundError(f"Source 15m dataset {m23_dataset_file} not found.")

    with open(m23_dataset_file, "r") as f:
        payload = json.load(f)

    candles_15m = payload["candles"]
    dataset_id = payload["dataset_id"]

    # Benchmark 1: 1-Hour HTF
    res_1h = run_htf_walk_forward_benchmark(
        candles_15m=candles_15m,
        dataset_id=dataset_id,
        interval=HTFInterval.ONE_HOUR,
        initial_train_bars=500,
        val_step_bars=50,
        embargo_bars=2,
        holdout_fold_count=4,
    )

    # Benchmark 2: Half-Day (Session Half) HTF
    res_half_day = run_htf_walk_forward_benchmark(
        candles_15m=candles_15m,
        dataset_id=dataset_id,
        interval=HTFInterval.HALF_DAY,
        initial_train_bars=200,
        val_step_bars=20,
        embargo_bars=2,
        holdout_fold_count=4,
    )

    combined_artifact = {
        "benchmark_milestone": "M27",
        "description": "Higher-Timeframe 1-Hour and Half-Day Walk-Forward Research Benchmark",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "one_hour": asdict(res_1h),
        "half_day": asdict(res_half_day),
        "safety_invariants": {
            "forecast_ready": False,
            "real_market_data_verified": False,
            "paper_approved": False,
            "live_approved": False,
            "live_broker_routing_enabled": False,
        },
    }

    out_path = REPO_ROOT / "var" / "datasets" / "m27_htf_benchmark_results.json"
    with open(out_path, "w") as f:
        json.dump(combined_artifact, f, indent=2)

    log.info(f"Persisted M27 HTF Benchmark results to {out_path}")
    return combined_artifact
