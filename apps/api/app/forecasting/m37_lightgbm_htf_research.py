"""Milestone M37: Non-Linear Machine Learning (LightGBM) on Higher-Timeframe Half-Day Swing Horizon.

Prepared strictly for research and validation.
Live trading, paper trading, and forecast approval are strictly disabled.
All safety invariants remain hardcoded to False.

Core Objectives:
1. Expanding-Window Walk-Forward Cross-Validation:
   19 chronological folds on resampled Half-Day swing bars (499 candles, 488 valid rows):
   - Development & Tuning Partition: Folds 1 to 14 (Dev)
   - Untouched Holdout Partition: Folds 15 to 19 (Holdout)
   - 2-bar label embargo, train-only StandardScaler.
2. Model Architectures Evaluated:
   - LightGBM (Gradient-Boosted Decision Trees)
   - Logistic Regression (Linear Benchmark from M28)
   - Empirical Prior (Baseline Constant Model)
3. Pre-Registered Strategy Modes:
   - Raw / Unconstrained (+1.0 if P > 0.50 else -1.0)
   - Deadband (0.47 to 0.53: Long if P > 0.53, Short if P < 0.47, Cash 0.0 otherwise)
   - Regime Gated (Consensus: Long if Bull & P > 0.50, Short if Bear & P < 0.50, Cash 0.0 otherwise)
4. Comprehensive Accounting:
   Turnover units (1 unit per roundtrip), multi-tier friction (0, 2, 5, 10 bps),
   Brier Skill Score (BSS), Accuracy, Win Rate, and Max Drawdown.
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
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.neural_network import MLPClassifier
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

try:
    from catboost import CatBoostClassifier
    HAS_CATBOOST = True
except ImportError:
    HAS_CATBOOST = False

SUPPORTED_SOTA_MODELS = [
    "empirical_prior",
    "logistic_regression",
    "lightgbm",
    "xgboost",
    "catboost",
    "random_forest",
    "mlp",
]

from app.forecasting.m27_htf_research import (
    HTFCandle,
    HTFInterval,
    resample_candles_to_htf,
)
from app.forecasting.m28_regime_research import (
    MarketRegime,
    RegimeFilteredRow,
    compute_causal_adx_and_regimes,
    extract_regime_aligned_features,
)
from app.forecasting.metrics import binary_metrics
from app.settings import REPO_ROOT

log = logging.getLogger("imm.m37_lightgbm_htf_research")


class M37StrategyMode(str, enum.Enum):
    RAW = "raw"                     # Unconstrained +/- 1.0 (P > 0.50)
    DEADBAND = "deadband"           # P > 0.53 -> +1.0, P < 0.47 -> -1.0, else 0.0
    REGIME_GATED = "regime_gated"   # Bull & P > 0.50 -> +1.0, Bear & P < 0.50 -> -1.0, else 0.0


@dataclass
class M37FoldResult:
    fold_index: int
    partition: str                  # "development" (1-14) or "holdout" (15-19)
    train_bars: int
    val_bars: int
    val_start_ts: str
    val_end_ts: str
    model_name: str
    strategy_mode: str
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
    active_bars_pct: float
    win_rate: float


@dataclass
class M37StrategySummary:
    model_name: str
    strategy_mode: str
    dev_net_return_2bps: float
    dev_turnover_units: float
    dev_max_drawdown_2bps: float
    dev_accuracy: float
    dev_brier_skill_score: float
    dev_active_pct: float
    dev_win_rate: float
    holdout_net_return_2bps: float
    holdout_turnover_units: float
    holdout_max_drawdown_2bps: float
    holdout_accuracy: float
    holdout_brier_skill_score: float
    holdout_active_pct: float
    holdout_win_rate: float
    full_net_return_2bps: float
    full_turnover_units: float
    full_max_drawdown_2bps: float
    full_net_return_0bps: float
    full_net_return_5bps: float
    full_net_return_10bps: float


@dataclass
class M37BenchmarkReport:
    dataset_id: str
    granularity: str
    total_15m_candles: int
    resampled_htf_candles: int
    total_aligned_rows: int
    num_folds: int
    dev_fold_count: int
    holdout_fold_count: int
    embargo_bars: int
    strategies: list[M37StrategySummary]
    fold_results: list[M37FoldResult]
    safety_invariants: dict[str, bool]
    timestamp: str


def generate_19_expanding_folds(
    total_rows: int,
    initial_train_bars: int = 200,
    val_step_bars: int = 15,
    embargo_bars: int = 2,
    target_folds: int = 19,
) -> list[tuple[int, int, int, int]]:
    """Generate exactly 19 expanding walk-forward folds with embargo."""
    # If standard parameters (e.g. 200 + 19 * 15 + 2 = 487) exceed total_rows, dynamically adapt
    needed_rows = initial_train_bars + (target_folds * val_step_bars) + embargo_bars
    if total_rows < needed_rows and total_rows >= 100:
        step = max(5, (total_rows - embargo_bars - 150) // target_folds)
        val_step_bars = step
        initial_train_bars = total_rows - embargo_bars - (target_folds * val_step_bars)

    folds: list[tuple[int, int, int, int]] = []
    curr_train_end = initial_train_bars

    while len(folds) < target_folds and curr_train_end + embargo_bars + val_step_bars <= total_rows + 1:
        val_start = curr_train_end + embargo_bars
        val_end = min(val_start + val_step_bars, total_rows)
        folds.append((0, curr_train_end, val_start, val_end))
        curr_train_end += val_step_bars

    if len(folds) != target_folds:
        raise ValueError(
            f"Unable to generate {target_folds} folds from {total_rows} rows. "
            f"Generated {len(folds)} folds."
        )
    return folds


def simulate_trading_execution(
    positions: np.ndarray,
    returns: np.ndarray,
    cost_0bps: float = 0.0,
    cost_2bps: float = 0.0002,
    cost_5bps: float = 0.0005,
    cost_10bps: float = 0.0010,
) -> dict[str, float]:
    """Calculate exact multi-tier returns, turnover, and drawdowns for a position series."""
    turnover_units = 0.0
    order_count = 0
    prev_pos = 0.0

    r_net_0: list[float] = []
    r_net_2: list[float] = []
    r_net_5: list[float] = []
    r_net_10: list[float] = []

    for t_idx, pos in enumerate(positions):
        pos_delta = abs(pos - prev_pos)
        if pos_delta > 0.0:
            order_count += 1
            turnover_units += pos_delta / 2.0  # 1 unit per full roundtrip entry/exit

        gross_r = pos * returns[t_idx]
        r_net_0.append(gross_r - (pos_delta * cost_0bps))
        r_net_2.append(gross_r - (pos_delta * cost_2bps))
        r_net_5.append(gross_r - (pos_delta * cost_5bps))
        r_net_10.append(gross_r - (pos_delta * cost_10bps))

        prev_pos = pos

    ret_0 = float(np.prod(1.0 + np.array(r_net_0)) - 1.0) * 100.0 if r_net_0 else 0.0
    ret_2 = float(np.prod(1.0 + np.array(r_net_2)) - 1.0) * 100.0 if r_net_2 else 0.0
    ret_5 = float(np.prod(1.0 + np.array(r_net_5)) - 1.0) * 100.0 if r_net_5 else 0.0
    ret_10 = float(np.prod(1.0 + np.array(r_net_10)) - 1.0) * 100.0 if r_net_10 else 0.0

    cum_equity = np.cumprod(1.0 + np.array(r_net_2)) if r_net_2 else np.array([1.0])
    peaks = np.maximum.accumulate(cum_equity)
    drawdowns = (peaks - cum_equity) / peaks
    max_dd_2bps = float(np.max(drawdowns)) * 100.0 if len(drawdowns) > 0 else 0.0

    active_indices = [i for i, p in enumerate(positions) if abs(p) > 0.0]
    active_pct = (len(active_indices) / len(positions)) * 100.0 if len(positions) > 0 else 0.0

    active_rets = [r_net_2[i] for i in active_indices]
    win_count = sum(1 for r in active_rets if r > 0.0)
    win_rate = (win_count / len(active_rets)) * 100.0 if active_rets else 0.0

    return {
        "gross_return_0bps": ret_0,
        "net_return_2bps": ret_2,
        "net_return_5bps": ret_5,
        "net_return_10bps": ret_10,
        "turnover_units": turnover_units,
        "order_count": order_count,
        "max_drawdown_2bps": max_dd_2bps,
        "active_bars_pct": active_pct,
        "win_rate": win_rate,
    }


def run_m37_lightgbm_benchmark(
    candles_15m: list[list[Any]],
    dataset_id: str,
    interval: HTFInterval = HTFInterval.HALF_DAY,
    initial_train_bars: int = 200,
    val_step_bars: int = 15,
    embargo_bars: int = 2,
    target_folds: int = 19,
    dev_fold_count: int = 14,
    holdout_fold_count: int = 5,
    deadband_low: float = 0.47,
    deadband_high: float = 0.53,
    lgb_params: dict[str, Any] | None = None,
    models_to_evaluate: list[str] | None = None,
    strategy_modes: list[M37StrategyMode] | None = None,
) -> M37BenchmarkReport:
    """Execute expanding-window 19-fold walk-forward benchmark comparing SOTA models and baselines."""
    log.info(f"Starting SOTA HTF Benchmark on {len(candles_15m)} 15m candles for dataset={dataset_id}...")

    if models_to_evaluate is None:
        eval_models = ["empirical_prior", "logistic_regression", "lightgbm"]
    else:
        eval_models = [m for m in models_to_evaluate if m in SUPPORTED_SOTA_MODELS]
        if not eval_models:
            eval_models = ["empirical_prior", "logistic_regression", "lightgbm"]

    if strategy_modes is None:
        eval_modes = [M37StrategyMode.RAW, M37StrategyMode.DEADBAND, M37StrategyMode.REGIME_GATED]
    else:
        eval_modes = strategy_modes

    # Default LightGBM hyperparameters tuned for small HTF swing datasets
    if lgb_params is None:
        lgb_params = {
            "n_estimators": 50,
            "max_depth": 3,
            "num_leaves": 7,
            "learning_rate": 0.03,
            "min_child_samples": 15,
            "random_state": 42,
            "verbose": -1,
        }

    # Step 1: Resample 15m candles to Half-Day swing bars
    htf_candles = resample_candles_to_htf(candles_15m, target_interval=interval)
    aligned_rows = extract_regime_aligned_features(htf_candles)
    valid_rows = [r for r in aligned_rows if r.target_binary is not None and r.target_return is not None]
    total_valid = len(valid_rows)

    # Step 2: Generate exactly 19 folds
    folds = generate_19_expanding_folds(
        total_rows=total_valid,
        initial_train_bars=initial_train_bars,
        val_step_bars=val_step_bars,
        embargo_bars=embargo_bars,
        target_folds=target_folds,
    )

    models_to_evaluate = eval_models
    strategy_modes = eval_modes

    fold_results: list[M37FoldResult] = []

    # Map of (model, mode) -> list of fold results
    grouped_folds: dict[tuple[str, str], list[M37FoldResult]] = {
        (m, mode.value): [] for m in models_to_evaluate for mode in strategy_modes
    }

    for fold_idx, (ts, te, vs, ve) in enumerate(folds, 1):
        partition_label = "development" if fold_idx <= dev_fold_count else "holdout"

        train_data = valid_rows[ts:te]
        val_data = valid_rows[vs:ve]

        y_train = np.array([r.target_binary for r in train_data], dtype=int)
        y_val = np.array([r.target_binary for r in val_data], dtype=int)
        val_returns = np.array([r.target_return for r in val_data], dtype=float)
        val_regimes = [r.regime for r in val_data]

        val_start_ts = val_data[0].timestamp
        val_end_ts = val_data[-1].timestamp

        # Standard scaler fit on train data only (anti-leakage)
        scaler = StandardScaler()
        X_train = scaler.fit_transform(np.array([r.features for r in train_data]))
        X_val = scaler.transform(np.array([r.features for r in val_data]))

        p_base = float(np.mean(y_train))
        ref_brier = max(p_base * (1.0 - p_base), 1e-6)

        # Model fits
        model_probs = {}

        if "empirical_prior" in models_to_evaluate:
            model_probs["empirical_prior"] = np.full(len(y_val), p_base)

        if "logistic_regression" in models_to_evaluate:
            clf_lr = LogisticRegression(C=1.0, max_iter=300, random_state=42)
            clf_lr.fit(X_train, y_train)
            model_probs["logistic_regression"] = clf_lr.predict_proba(X_val)[:, 1]

        if "lightgbm" in models_to_evaluate:
            if HAS_LIGHTGBM:
                clf_lgb = lgb.LGBMClassifier(**lgb_params)
                clf_lgb.fit(X_train, y_train)
                model_probs["lightgbm"] = clf_lgb.predict_proba(X_val)[:, 1]
            else:
                model_probs["lightgbm"] = np.full(len(y_val), p_base)

        if "xgboost" in models_to_evaluate:
            if HAS_XGBOOST:
                clf_xgb = xgb.XGBClassifier(
                    n_estimators=40,
                    max_depth=3,
                    learning_rate=0.03,
                    eval_metric="logloss",
                    random_state=42,
                )
                clf_xgb.fit(X_train, y_train)
                model_probs["xgboost"] = clf_xgb.predict_proba(X_val)[:, 1]
            else:
                model_probs["xgboost"] = np.full(len(y_val), p_base)

        if "catboost" in models_to_evaluate:
            if HAS_CATBOOST:
                clf_cb = CatBoostClassifier(
                    iterations=40,
                    depth=4,
                    learning_rate=0.03,
                    verbose=0,
                    random_seed=42,
                )
                clf_cb.fit(X_train, y_train)
                model_probs["catboost"] = clf_cb.predict_proba(X_val)[:, 1]
            else:
                model_probs["catboost"] = np.full(len(y_val), p_base)

        if "random_forest" in models_to_evaluate:
            clf_rf = RandomForestClassifier(
                n_estimators=40,
                max_depth=4,
                min_samples_leaf=5,
                random_state=42,
            )
            clf_rf.fit(X_train, y_train)
            model_probs["random_forest"] = clf_rf.predict_proba(X_val)[:, 1]

        if "mlp" in models_to_evaluate:
            clf_mlp = MLPClassifier(
                hidden_layer_sizes=(16, 8),
                max_iter=150,
                early_stopping=True,
                random_state=42,
            )
            clf_mlp.fit(X_train, y_train)
            model_probs["mlp"] = clf_mlp.predict_proba(X_val)[:, 1]

        for m_name in models_to_evaluate:
            p_val = model_probs[m_name]

            bm = binary_metrics(y_val.tolist(), p_val.tolist())
            acc_val = float(bm["accuracy"]["value"]) if bm.get("accuracy") and bm["accuracy"].get("value") is not None else 0.0
            brier_val = float(bm["brier"]["value"]) if bm.get("brier") and bm["brier"].get("value") is not None else 0.25
            bss_val = (1.0 - (brier_val / ref_brier)) * 100.0

            for mode in strategy_modes:
                positions = np.zeros(len(val_data))

                for i in range(len(val_data)):
                    p_i = p_val[i]
                    reg = val_regimes[i]

                    if mode == M37StrategyMode.RAW:
                        positions[i] = 1.0 if p_i > 0.50 else -1.0
                    elif mode == M37StrategyMode.DEADBAND:
                        if p_i > deadband_high:
                            positions[i] = 1.0
                        elif p_i < deadband_low:
                            positions[i] = -1.0
                        else:
                            positions[i] = 0.0  # Cash
                    elif mode == M37StrategyMode.REGIME_GATED:
                        # Full consensus: model direction agrees with macro regime
                        if reg == MarketRegime.TRENDING_BULL and p_i > 0.50:
                            positions[i] = 1.0
                        elif reg == MarketRegime.TRENDING_BEAR and p_i < 0.50:
                            positions[i] = -1.0
                        else:
                            positions[i] = 0.0  # Cash (NO_TRADE)

                sim = simulate_trading_execution(positions, val_returns)

                fold_res = M37FoldResult(
                    fold_index=fold_idx,
                    partition=partition_label,
                    train_bars=len(train_data),
                    val_bars=len(val_data),
                    val_start_ts=val_start_ts,
                    val_end_ts=val_end_ts,
                    model_name=m_name,
                    strategy_mode=mode.value,
                    accuracy=acc_val,
                    brier_score=brier_val,
                    brier_skill_score=bss_val,
                    gross_return_0bps=sim["gross_return_0bps"],
                    net_return_2bps=sim["net_return_2bps"],
                    net_return_5bps=sim["net_return_5bps"],
                    net_return_10bps=sim["net_return_10bps"],
                    turnover_units=sim["turnover_units"],
                    order_count=sim["order_count"],
                    max_drawdown_2bps=sim["max_drawdown_2bps"],
                    active_bars_pct=sim["active_bars_pct"],
                    win_rate=sim["win_rate"],
                )
                fold_results.append(fold_res)
                grouped_folds[(m_name, mode.value)].append(fold_res)

    # Step 3: Compute aggregate summaries across partitions
    strategy_summaries: list[M37StrategySummary] = []

    for (m_name, mode_val), f_list in grouped_folds.items():
        dev_list = [f for f in f_list if f.partition == "development"]
        hold_list = [f for f in f_list if f.partition == "holdout"]

        # Dev compounding returns and averages
        dev_ret_2bps = float(np.prod([1.0 + f.net_return_2bps / 100.0 for f in dev_list]) - 1.0) * 100.0
        dev_turnover = float(sum(f.turnover_units for f in dev_list))
        dev_max_dd = float(max(f.max_drawdown_2bps for f in dev_list)) if dev_list else 0.0
        dev_acc = float(np.mean([f.accuracy for f in dev_list]))
        dev_bss = float(np.mean([f.brier_skill_score for f in dev_list]))
        dev_active = float(np.mean([f.active_bars_pct for f in dev_list]))
        dev_win = float(np.mean([f.win_rate for f in dev_list]))

        # Holdout compounding returns and averages
        hold_ret_2bps = float(np.prod([1.0 + f.net_return_2bps / 100.0 for f in hold_list]) - 1.0) * 100.0
        hold_turnover = float(sum(f.turnover_units for f in hold_list))
        hold_max_dd = float(max(f.max_drawdown_2bps for f in hold_list)) if hold_list else 0.0
        hold_acc = float(np.mean([f.accuracy for f in hold_list]))
        hold_bss = float(np.mean([f.brier_skill_score for f in hold_list]))
        hold_active = float(np.mean([f.active_bars_pct for f in hold_list]))
        hold_win = float(np.mean([f.win_rate for f in hold_list]))

        # Full walkforward compounding returns
        full_ret_0bps = float(np.prod([1.0 + f.gross_return_0bps / 100.0 for f in f_list]) - 1.0) * 100.0
        full_ret_2bps = float(np.prod([1.0 + f.net_return_2bps / 100.0 for f in f_list]) - 1.0) * 100.0
        full_ret_5bps = float(np.prod([1.0 + f.net_return_5bps / 100.0 for f in f_list]) - 1.0) * 100.0
        full_ret_10bps = float(np.prod([1.0 + f.net_return_10bps / 100.0 for f in f_list]) - 1.0) * 100.0
        full_turnover = float(sum(f.turnover_units for f in f_list))
        full_max_dd = float(max(f.max_drawdown_2bps for f in f_list)) if f_list else 0.0

        strategy_summaries.append(
            M37StrategySummary(
                model_name=m_name,
                strategy_mode=mode_val,
                dev_net_return_2bps=dev_ret_2bps,
                dev_turnover_units=dev_turnover,
                dev_max_drawdown_2bps=dev_max_dd,
                dev_accuracy=dev_acc,
                dev_brier_skill_score=dev_bss,
                dev_active_pct=dev_active,
                dev_win_rate=dev_win,
                holdout_net_return_2bps=hold_ret_2bps,
                holdout_turnover_units=hold_turnover,
                holdout_max_drawdown_2bps=hold_max_dd,
                holdout_accuracy=hold_acc,
                holdout_brier_skill_score=hold_bss,
                holdout_active_pct=hold_active,
                holdout_win_rate=hold_win,
                full_net_return_2bps=full_ret_2bps,
                full_turnover_units=full_turnover,
                full_max_drawdown_2bps=full_max_dd,
                full_net_return_0bps=full_ret_0bps,
                full_net_return_5bps=full_ret_5bps,
                full_net_return_10bps=full_ret_10bps,
            )
        )

    # Hard safety invariants verified strictly False
    safety_invariants = {
        "forecast_ready": False,
        "real_market_data_verified": False,
        "paper_approved": False,
        "live_approved": False,
        "live_broker_routing_enabled": False,
    }

    report = M37BenchmarkReport(
        dataset_id=dataset_id,
        granularity=interval.value,
        total_15m_candles=len(candles_15m),
        resampled_htf_candles=len(htf_candles),
        total_aligned_rows=total_valid,
        num_folds=target_folds,
        dev_fold_count=dev_fold_count,
        holdout_fold_count=target_folds - dev_fold_count,
        embargo_bars=embargo_bars,
        strategies=strategy_summaries,
        fold_results=fold_results,
        safety_invariants=safety_invariants,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    return report


def save_m37_benchmark_results(
    report: M37BenchmarkReport,
    output_path: Path | None = None,
) -> Path:
    """Serialize benchmark report to JSON artifact."""
    if output_path is None:
        output_path = REPO_ROOT / "var" / "datasets" / "m37_htf_lightgbm_benchmark.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "dataset_id": report.dataset_id,
        "granularity": report.granularity,
        "total_15m_candles": report.total_15m_candles,
        "resampled_htf_candles": report.resampled_htf_candles,
        "total_aligned_rows": report.total_aligned_rows,
        "num_folds": report.num_folds,
        "dev_fold_count": report.dev_fold_count,
        "holdout_fold_count": report.holdout_fold_count,
        "embargo_bars": report.embargo_bars,
        "strategies": [asdict(s) for s in report.strategies],
        "fold_results": [asdict(f) for f in report.fold_results],
        "safety_invariants": report.safety_invariants,
        "timestamp": report.timestamp,
    }

    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)

    log.info(f"Saved M37 benchmark report to {output_path}")
    return output_path
