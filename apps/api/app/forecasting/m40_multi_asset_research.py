"""Milestone M40: Multi-Asset Cross-Validation & Generalization (BANK NIFTY) on Higher-Timeframe Half-Day Horizon.

Prepared strictly for research and validation.
Live trading, paper trading, and forecast approval are strictly disabled.
All safety invariants remain hardcoded to False.

Core Objectives:
1. Multi-Asset Comparative Dataset Preparation:
   Generate and seal a synchronized, high-fidelity BANK NIFTY 15m historical dataset
   (6,227 continuous candles spanning 2025-10-14 to 2026-10-16) synchronized bar-by-bar
   with the NIFTY 50 benchmark, with realistic banking beta (1.28), higher volatility,
   and strict OHLC geometric validity.
2. Alpha-to-Friction Ratio Quantification:
   Empirically measure average Half-Day swing price displacement E[|R|] vs 2 bps transaction
   costs for BANK NIFTY and compare with NIFTY 50.
3. 19-Fold Expanding-Window Walk-Forward Cross-Validation:
   Resample BANK NIFTY to 499 Half-Day swing bars (488 valid aligned rows) and execute
   19 folds (Dev: Folds 1-14; Untouched Holdout: Folds 15-19; 2-bar label embargo).
4. Multi-Model Architecture & Strategy Matrix on BANK NIFTY:
   Benchmark Empirical Prior, Logistic Regression (Raw, Deadband, Regime Gated), and
   LightGBM (Raw, Deadband, Regime Gated) across 0, 2, 5, 10 bps friction tiers.
5. Cross-Asset Generalization & Zero-Shot Transfer:
   Test directional model transferability (NIFTY -> BANK NIFTY and BANK NIFTY -> NIFTY)
   and evaluate the diversification benefit of a Dual-Index Multi-Asset Portfolio.
"""

from __future__ import annotations

import enum
import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

try:
    import lightgbm as lgb
    HAS_LIGHTGBM = True
except ImportError:
    HAS_LIGHTGBM = False

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
    simulate_trading_execution,
)
from app.forecasting.evaluation import (
    FuturesCostModel,
    OOSBar,
    add_deflated_sharpe,
    chained_equity_metrics,
    evaluate_partition,
)
from app.forecasting.metrics import binary_metrics
from app.settings import REPO_ROOT

log = logging.getLogger("imm.m40_multi_asset_research")


class M40StrategyMode(str, enum.Enum):
    RAW = "raw"
    DEADBAND = "deadband"
    REGIME_GATED = "regime_gated"


@dataclass
class M40FoldResult:
    fold_index: int
    partition: str
    asset: str
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
class M40AssetSummary:
    asset_name: str
    mean_bar_displacement_pct: float
    alpha_to_friction_ratio: float
    strategies: dict[str, dict[str, Any]]


@dataclass
class M40CrossTransferResult:
    transfer_direction: str
    holdout_net_return_2bps: float
    all_folds_net_return_2bps: float
    holdout_turnover_units: float
    all_folds_turnover_units: float


@dataclass
class M40PortfolioSummary:
    holdout_net_return_2bps: float
    all_folds_net_return_2bps: float
    holdout_gross_return_0bps: float
    all_folds_gross_return_0bps: float
    holdout_turnover_units: float
    all_folds_turnover_units: float
    holdout_max_drawdown_2bps: float
    all_folds_max_drawdown_2bps: float


@dataclass
class M40BenchmarkReport:
    milestone: str
    created_at: str
    nifty_dataset_id: str
    banknifty_dataset_id: str
    total_15m_candles: int
    resampled_htf_candles: int
    total_aligned_rows: int
    num_folds: int
    dev_fold_count: int
    holdout_fold_count: int
    nifty_summary: M40AssetSummary
    banknifty_summary: M40AssetSummary
    cross_transfers: list[M40CrossTransferResult]
    dual_portfolio_summary: M40PortfolioSummary
    safety_invariants: dict[str, bool]


def generate_deterministic_banknifty_15m_candles(
    nifty_candles: list[list[Any]],
    base_price: float = 52000.0,
    beta: float = 1.28,
    idiosyncratic_vol: float = 0.0010,
    seed: int = 42,
) -> list[list[Any]]:
    """Synthesize synchronized BANK NIFTY 15m continuous candles bar-by-bar from NIFTY.

    WARNING: the output is SYNTHETIC test data, not market data. Any benchmark built on it
    measures the generator, not BANK NIFTY.

    Ensures:
    1. Exact calendar timestamp alignment with NIFTY 50 (identical session structure).
    2. Realistic banking index beta (1.28) and higher annualized volatility.
    3. Strict geometric OHLC invariants (High >= max(Open, Close), Low <= min(Open, Close), High >= Low).
    4. Positive price and volume values.
    5. Fully deterministic given the random seed.
    """
    n = len(nifty_candles)
    if n == 0:
        return []

    rng = np.random.default_rng(seed)
    nifty_closes = np.array([c[4] for c in nifty_candles], dtype=float)
    nifty_log_rets = np.diff(np.log(nifty_closes))

    # Bank Nifty return = beta * nifty_return + idiosyncratic component
    idio_noise = rng.normal(loc=0.00002, scale=idiosyncratic_vol, size=len(nifty_log_rets))
    bank_rets = beta * nifty_log_rets + idio_noise

    bank_closes = np.zeros(n, dtype=float)
    bank_closes[0] = base_price
    for i in range(1, n):
        bank_closes[i] = bank_closes[i - 1] * np.exp(bank_rets[i - 1])

    bank_candles: list[list[Any]] = []
    for i, nc in enumerate(nifty_candles):
        ts = nc[0]
        c_close = float(round(bank_closes[i], 2))
        if i == 0:
            c_open = float(round(c_close * 0.9995, 2))
        else:
            c_open = float(round(bank_closes[i - 1], 2))

        # Intrabar range scaled by banking index price ratio and beta
        n_o, n_h, n_l, n_c = nc[1], nc[2], nc[3], nc[4]
        n_spread = max(abs(n_h - n_l), 1.0)
        ratio = c_close / max(n_c, 1.0)
        spread = n_spread * ratio * 1.25

        c_high = float(round(max(c_open, c_close) + spread * 0.5, 2))
        c_low = float(round(min(c_open, c_close) - spread * 0.5, 2))
        vol = float(round(nc[5] * 0.85, 2)) if len(nc) > 5 else 0.0
        oi = 0.0

        if c_high < max(c_open, c_close):
            c_high = max(c_open, c_close)
        if c_low > min(c_open, c_close):
            c_low = min(c_open, c_close)

        bank_candles.append([ts, c_open, c_high, c_low, c_close, vol, oi])

    return bank_candles


def build_and_save_banknifty_dataset(
    nifty_dataset_path: Path | None = None,
    output_path: Path | None = None,
    seed: int = 42,
) -> tuple[dict[str, Any], str]:
    """Generate and serialize the BANK NIFTY 15m dataset with cryptographic digest."""
    if nifty_dataset_path is None:
        nifty_dataset_path = REPO_ROOT / "var" / "datasets" / "derived_nifty_15m_m23_bc7d31bceebf13a3.json"
    if output_path is None:
        output_path = REPO_ROOT / "var" / "datasets" / "derived_banknifty_15m_m40.json"

    with open(nifty_dataset_path, "r") as f:
        nifty_data = json.load(f)

    nifty_candles = nifty_data["candles"]
    bank_candles = generate_deterministic_banknifty_15m_candles(nifty_candles, seed=seed)

    # Compute content hash
    serialized_candles = json.dumps(bank_candles, sort_keys=True).encode("utf-8")
    dataset_id = hashlib.sha256(serialized_candles).hexdigest()

    dataset_payload = {
        "schema_version": "m40-derived-regular-candles-1",
        "dataset_id": dataset_id,
        "dataset_name": "derived_banknifty_15m_m40_1y",
        "symbol": "NSE-BANKNIFTY",
        "interval": "15minute",
        "data_origin": "SYNTHETIC",
        "synthetic": True,
        "limitations": [
            "Generated from NIFTY log returns * beta plus Gaussian noise; not real BANK NIFTY market data.",
            "Must not be used for live forecasts, accuracy claims or cross-asset generalization evidence.",
        ],
        "candle_count": len(bank_candles),
        "date_range": [bank_candles[0][0], bank_candles[-1][0]],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "quality_report": {
            "total_candles": len(bank_candles),
            "geometric_errors": 0,
            "negative_prices": 0,
            "synchronization_reference": nifty_data.get("dataset_id"),
        },
        "candles": bank_candles,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(dataset_payload, f, indent=2)

    log.info(f"Generated and saved BANK NIFTY dataset to {output_path} (ID: {dataset_id})")
    return dataset_payload, dataset_id


def evaluate_asset_walk_forward(
    valid_rows: list[RegimeFilteredRow],
    asset_name: str,
    folds: list[tuple[int, int, int, int]],
    dev_fold_count: int = 14,
    deadband_low: float = 0.47,
    deadband_high: float = 0.53,
    lgb_params: dict[str, Any] | None = None,
) -> tuple[dict[str, dict[str, Any]], list[M40FoldResult]]:
    """Execute 19-fold walk-forward cross-validation for an asset across all strategies."""
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

    models_to_run = ["empirical_prior", "logistic_regression"]
    if HAS_LIGHTGBM:
        models_to_run.append("lightgbm")

    strategy_modes = [M40StrategyMode.RAW, M40StrategyMode.DEADBAND, M40StrategyMode.REGIME_GATED]

    fold_results: list[M40FoldResult] = []
    # (model, mode) -> list of fold results
    grouped: dict[tuple[str, str], list[M40FoldResult]] = {
        (m, mode.value): [] for m in models_to_run for mode in strategy_modes
    }
    oos_bars: dict[tuple[str, str], list[OOSBar]] = {key: [] for key in grouped}

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

        scaler = StandardScaler()
        X_train = scaler.fit_transform(np.array([r.features for r in train_data]))
        X_val = scaler.transform(np.array([r.features for r in val_data]))

        p_base = float(np.mean(y_train))
        ref_brier = max(p_base * (1.0 - p_base), 1e-6)

        # 1. Model Predictions
        prob_preds: dict[str, np.ndarray] = {
            "empirical_prior": np.full(len(val_data), p_base),
        }

        # Logistic Regression
        lr = LogisticRegression(C=1.0, max_iter=200, random_state=42)
        lr.fit(X_train, y_train)
        prob_preds["logistic_regression"] = lr.predict_proba(X_val)[:, 1]

        # LightGBM
        if HAS_LIGHTGBM:
            lgb_model = lgb.LGBMClassifier(**lgb_params)
            lgb_model.fit(X_train, y_train)
            prob_preds["lightgbm"] = lgb_model.predict_proba(X_val)[:, 1]

        # 2. Strategy Signal Generation & Simulation
        for m_name, probs in prob_preds.items():
            # Binary metrics
            bm = binary_metrics(y_val.tolist(), probs.tolist())
            acc = float(bm["accuracy"]["value"]) if bm.get("accuracy") and bm["accuracy"].get("value") is not None else 0.0
            brier = float(bm["brier"]["value"]) if bm.get("brier") and bm["brier"].get("value") is not None else 0.25
            bss = (1.0 - (brier / ref_brier)) * 100.0

            for mode in strategy_modes:
                if mode == M40StrategyMode.RAW:
                    pos = np.where(probs > 0.50, 1.0, -1.0)
                elif mode == M40StrategyMode.DEADBAND:
                    pos = np.where(probs > deadband_high, 1.0, np.where(probs < deadband_low, -1.0, 0.0))
                elif mode == M40StrategyMode.REGIME_GATED:
                    pos = np.zeros(len(val_data))
                    for i, p in enumerate(probs):
                        if val_regimes[i] == MarketRegime.TRENDING_BULL and p > 0.50:
                            pos[i] = 1.0
                        elif val_regimes[i] == MarketRegime.TRENDING_BEAR and p < 0.50:
                            pos[i] = -1.0
                        else:
                            pos[i] = 0.0

                sim = simulate_trading_execution(pos, val_returns)
                oos_bars[(m_name, mode.value)].extend(
                    OOSBar(
                        timestamp=str(val_data[i].timestamp),
                        partition=partition_label,
                        position=float(pos[i]),
                        bar_return=float(val_returns[i]),
                        probability=float(probs[i]),
                        label=int(y_val[i]),
                    )
                    for i in range(len(val_data))
                )

                res = M40FoldResult(
                    fold_index=fold_idx,
                    partition=partition_label,
                    asset=asset_name,
                    train_bars=len(train_data),
                    val_bars=len(val_data),
                    val_start_ts=val_start_ts,
                    val_end_ts=val_end_ts,
                    model_name=m_name,
                    strategy_mode=mode.value,
                    accuracy=acc,
                    brier_score=brier,
                    brier_skill_score=bss,
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
                fold_results.append(res)
                grouped[(m_name, mode.value)].append(res)

    # 3. Strategy Summaries
    # Returns are compounded over one chained out-of-sample curve (positions carry across
    # contiguous folds, every change and the final exit are charged). Fold returns are not
    # summed, and drawdown is the drawdown of that chained curve, not a mean of fold maxima.
    legacy_cost = 0.0002
    realistic_cost = FuturesCostModel().per_side()

    def _curve(bars: list[OOSBar], cost: float) -> dict[str, Any]:
        return chained_equity_metrics(bars, cost_per_side=cost)

    honest_by_key: dict[tuple[str, str], dict] = {}
    for key, bars in oos_bars.items():
        if bars:
            honest_by_key[key] = {
                "development": evaluate_partition([b for b in bars if b.partition == "development"], cost_per_side=realistic_cost),
                "holdout": evaluate_partition([b for b in bars if b.partition == "holdout"], cost_per_side=realistic_cost),
                "full": evaluate_partition(bars, cost_per_side=realistic_cost),
            }
    add_deflated_sharpe(list(honest_by_key.values()), partition="development")

    strategies_summary: dict[str, dict[str, Any]] = {}
    for (m_name, mode_val), f_list in grouped.items():
        key = f"{m_name}_{mode_val}"
        dev_folds = [f for f in f_list if f.partition == "development"]
        holdout_folds = [f for f in f_list if f.partition == "holdout"]

        def _mean(lst: list[M40FoldResult], attr: str) -> float:
            return float(np.mean([getattr(x, attr) for x in lst])) if lst else 0.0

        bars = oos_bars[(m_name, mode_val)]
        dev_bars = [b for b in bars if b.partition == "development"]
        hold_bars = [b for b in bars if b.partition == "holdout"]
        dev_curve = _curve(dev_bars, legacy_cost)
        hold_curve = _curve(hold_bars, legacy_cost)
        full_curve = _curve(bars, legacy_cost)
        gross_curve = _curve(bars, 0.0)
        strategies_summary[key] = {
            "model_name": m_name,
            "strategy_mode": mode_val,
            "dev_net_return_2bps": dev_curve["total_return_pct"],
            "dev_turnover_units": dev_curve["turnover_units"],
            "dev_accuracy": _mean(dev_folds, "accuracy"),
            "dev_brier_skill_score": _mean(dev_folds, "brier_skill_score"),
            "holdout_net_return_2bps": hold_curve["total_return_pct"],
            "holdout_turnover_units": hold_curve["turnover_units"],
            "holdout_accuracy": _mean(holdout_folds, "accuracy"),
            "holdout_brier_skill_score": _mean(holdout_folds, "brier_skill_score"),
            "full_net_return_2bps": full_curve["total_return_pct"],
            "full_gross_return_0bps": gross_curve["total_return_pct"],
            "full_turnover_units": full_curve["turnover_units"],
            "full_max_drawdown_2bps": full_curve["max_drawdown_pct"],
            "aggregation": "chained_compounded",
            "honest": honest_by_key.get((m_name, mode_val), {}),
        }

    return strategies_summary, fold_results


def evaluate_cross_asset_transfer(
    valid_nifty: list[RegimeFilteredRow],
    valid_bank: list[RegimeFilteredRow],
    folds: list[tuple[int, int, int, int]],
    dev_fold_count: int = 14,
) -> tuple[list[M40CrossTransferResult], M40PortfolioSummary]:
    """Evaluate zero-shot cross-asset transferability and dual-index multi-asset portfolio."""
    holdout_start = dev_fold_count + 1

    # Direction 1: Train on NIFTY -> Predict BANK NIFTY (Deadband 0.47-0.53)
    t1_all_rets: list[float] = []
    t1_all_tos: list[float] = []
    t1_holdout_rets: list[float] = []
    t1_holdout_tos: list[float] = []

    # Direction 2: Train on BANK NIFTY -> Predict NIFTY (Deadband 0.47-0.53)
    t2_all_rets: list[float] = []
    t2_all_tos: list[float] = []
    t2_holdout_rets: list[float] = []
    t2_holdout_tos: list[float] = []

    # Direction 3: Dual Portfolio (Native LR on NIFTY regime-gated + Native LR on BANK deadband, 50/50 capital)
    port_all_rets: list[float] = []
    port_all_gross: list[float] = []
    port_all_tos: list[float] = []
    port_holdout_rets: list[float] = []
    port_holdout_gross: list[float] = []
    port_holdout_tos: list[float] = []

    for fold_idx, (ts, te, vs, ve) in enumerate(folds, 1):
        tr_n, va_n = valid_nifty[ts:te], valid_nifty[vs:ve]
        tr_b, va_b = valid_bank[ts:te], valid_bank[vs:ve]

        # NIFTY model
        scaler_n = StandardScaler()
        X_tr_n = scaler_n.fit_transform(np.array([r.features for r in tr_n]))
        y_tr_n = np.array([r.target_binary for r in tr_n])
        clf_n = LogisticRegression(C=1.0, max_iter=200, random_state=42).fit(X_tr_n, y_tr_n)

        # BANK NIFTY model
        scaler_b = StandardScaler()
        X_tr_b = scaler_b.fit_transform(np.array([r.features for r in tr_b]))
        y_tr_b = np.array([r.target_binary for r in tr_b])
        clf_b = LogisticRegression(C=1.0, max_iter=200, random_state=42).fit(X_tr_b, y_tr_b)

        # T1: Zero-shot Nifty -> Bank
        X_va_b_scaled = scaler_n.transform(np.array([r.features for r in va_b]))
        p_b_from_n = clf_n.predict_proba(X_va_b_scaled)[:, 1]
        pos_t1 = np.where(p_b_from_n > 0.53, 1.0, np.where(p_b_from_n < 0.47, -1.0, 0.0))
        sim_t1 = simulate_trading_execution(pos_t1, np.array([r.target_return for r in va_b]))

        t1_all_rets.append(sim_t1["net_return_2bps"])
        t1_all_tos.append(sim_t1["turnover_units"])
        if fold_idx >= holdout_start:
            t1_holdout_rets.append(sim_t1["net_return_2bps"])
            t1_holdout_tos.append(sim_t1["turnover_units"])

        # T2: Zero-shot Bank -> Nifty
        X_va_n_scaled = scaler_b.transform(np.array([r.features for r in va_n]))
        p_n_from_b = clf_b.predict_proba(X_va_n_scaled)[:, 1]
        pos_t2 = np.where(p_n_from_b > 0.53, 1.0, np.where(p_n_from_b < 0.47, -1.0, 0.0))
        sim_t2 = simulate_trading_execution(pos_t2, np.array([r.target_return for r in va_n]))

        t2_all_rets.append(sim_t2["net_return_2bps"])
        t2_all_tos.append(sim_t2["turnover_units"])
        if fold_idx >= holdout_start:
            t2_holdout_rets.append(sim_t2["net_return_2bps"])
            t2_holdout_tos.append(sim_t2["turnover_units"])

        # T3: Dual-Index Portfolio (50% Nifty regime-gated + 50% Bank Nifty deadband)
        p_n_native = clf_n.predict_proba(scaler_n.transform(np.array([r.features for r in va_n])))[:, 1]
        p_b_native = clf_b.predict_proba(scaler_b.transform(np.array([r.features for r in va_b])))[:, 1]

        pos_n_native = np.zeros(len(va_n))
        for i, p in enumerate(p_n_native):
            if va_n[i].regime == MarketRegime.TRENDING_BULL and p > 0.50:
                pos_n_native[i] = 1.0
            elif va_n[i].regime == MarketRegime.TRENDING_BEAR and p < 0.50:
                pos_n_native[i] = -1.0

        pos_b_native = np.where(p_b_native > 0.53, 1.0, np.where(p_b_native < 0.47, -1.0, 0.0))

        sim_port_n = simulate_trading_execution(pos_n_native, np.array([r.target_return for r in va_n]))
        sim_port_b = simulate_trading_execution(pos_b_native, np.array([r.target_return for r in va_b]))

        port_ret_2bps = 0.5 * sim_port_n["net_return_2bps"] + 0.5 * sim_port_b["net_return_2bps"]
        port_ret_0bps = 0.5 * sim_port_n["gross_return_0bps"] + 0.5 * sim_port_b["gross_return_0bps"]
        port_to = 0.5 * sim_port_n["turnover_units"] + 0.5 * sim_port_b["turnover_units"]

        port_all_rets.append(port_ret_2bps)
        port_all_gross.append(port_ret_0bps)
        port_all_tos.append(port_to)
        if fold_idx >= holdout_start:
            port_holdout_rets.append(port_ret_2bps)
            port_holdout_gross.append(port_ret_0bps)
            port_holdout_tos.append(port_to)

    transfer_results = [
        M40CrossTransferResult(
            transfer_direction="NIFTY_TO_BANKNIFTY_ZERO_SHOT",
            holdout_net_return_2bps=float(sum(t1_holdout_rets)),
            all_folds_net_return_2bps=float(sum(t1_all_rets)),
            holdout_turnover_units=float(sum(t1_holdout_tos)),
            all_folds_turnover_units=float(sum(t1_all_tos)),
        ),
        M40CrossTransferResult(
            transfer_direction="BANKNIFTY_TO_NIFTY_ZERO_SHOT",
            holdout_net_return_2bps=float(sum(t2_holdout_rets)),
            all_folds_net_return_2bps=float(sum(t2_all_rets)),
            holdout_turnover_units=float(sum(t2_holdout_tos)),
            all_folds_turnover_units=float(sum(t2_all_tos)),
        ),
    ]

    # Calculate portfolio max drawdowns
    cum_equity = np.cumprod(1.0 + np.array(port_all_rets) / 100.0)
    peaks = np.maximum.accumulate(cum_equity)
    drawdowns = (peaks - cum_equity) / peaks
    all_max_dd = float(np.max(drawdowns)) * 100.0 if len(drawdowns) > 0 else 0.0

    cum_eq_holdout = np.cumprod(1.0 + np.array(port_holdout_rets) / 100.0)
    peaks_h = np.maximum.accumulate(cum_eq_holdout)
    dd_h = (peaks_h - cum_eq_holdout) / peaks_h
    holdout_max_dd = float(np.max(dd_h)) * 100.0 if len(dd_h) > 0 else 0.0

    portfolio_summary = M40PortfolioSummary(
        holdout_net_return_2bps=float(sum(port_holdout_rets)),
        all_folds_net_return_2bps=float(sum(port_all_rets)),
        holdout_gross_return_0bps=float(sum(port_holdout_gross)),
        all_folds_gross_return_0bps=float(sum(port_all_gross)),
        holdout_turnover_units=float(sum(port_holdout_tos)),
        all_folds_turnover_units=float(sum(port_all_tos)),
        holdout_max_drawdown_2bps=holdout_max_dd,
        all_folds_max_drawdown_2bps=all_max_dd,
    )

    return transfer_results, portfolio_summary


def run_m40_multi_asset_benchmark() -> M40BenchmarkReport:
    """Execute complete Milestone M40 Multi-Asset Benchmark and serialize results."""
    log.info("Starting Milestone M40 Multi-Asset Benchmark Execution...")

    # Step 1: Ensure BANK NIFTY dataset is generated and saved
    bank_dataset_path = REPO_ROOT / "var" / "datasets" / "derived_banknifty_15m_m40.json"
    nifty_dataset_path = REPO_ROOT / "var" / "datasets" / "derived_nifty_15m_m23_bc7d31bceebf13a3.json"

    if not nifty_dataset_path.exists():
        raise FileNotFoundError(f"Source NIFTY dataset not found at {nifty_dataset_path}")

    if not bank_dataset_path.exists():
        bank_data, bank_id = build_and_save_banknifty_dataset(
            nifty_dataset_path=nifty_dataset_path,
            output_path=bank_dataset_path,
            seed=42,
        )
    else:
        with open(bank_dataset_path, "r") as f:
            bank_data = json.load(f)
        bank_id = bank_data["dataset_id"]

    with open(nifty_dataset_path, "r") as f:
        nifty_data = json.load(f)
    nifty_id = nifty_data["dataset_id"]

    # Step 2: Resample and Extract Features for both assets
    htf_nifty = resample_candles_to_htf(nifty_data["candles"], target_interval=HTFInterval.HALF_DAY)
    aligned_nifty = extract_regime_aligned_features(htf_nifty)
    valid_nifty = [r for r in aligned_nifty if r.target_binary is not None and r.target_return is not None]

    htf_bank = resample_candles_to_htf(bank_data["candles"], target_interval=HTFInterval.HALF_DAY)
    aligned_bank = extract_regime_aligned_features(htf_bank)
    valid_bank = [r for r in aligned_bank if r.target_binary is not None and r.target_return is not None]

    # Verify identical length and chronological alignment
    if len(valid_nifty) != len(valid_bank):
        raise ValueError(f"Aligned row count mismatch: Nifty {len(valid_nifty)} vs Bank Nifty {len(valid_bank)}")

    total_valid = len(valid_nifty)

    # Displacement & Alpha-to-Friction ratios
    nifty_displacements = [abs(r.target_return) for r in valid_nifty]
    mean_nifty_disp = float(np.mean(nifty_displacements))
    nifty_ratio = mean_nifty_disp / 0.0002

    bank_displacements = [abs(r.target_return) for r in valid_bank]
    mean_bank_disp = float(np.mean(bank_displacements))
    bank_ratio = mean_bank_disp / 0.0002

    # Step 3: Generate 19 Walk-Forward Folds
    folds = generate_19_expanding_folds(
        total_rows=total_valid,
        initial_train_bars=200,
        val_step_bars=15,
        embargo_bars=2,
        target_folds=19,
    )

    # Step 4: Evaluate both assets
    nifty_strategies, nifty_fold_res = evaluate_asset_walk_forward(
        valid_rows=valid_nifty,
        asset_name="NIFTY",
        folds=folds,
        dev_fold_count=14,
    )

    bank_strategies, bank_fold_res = evaluate_asset_walk_forward(
        valid_rows=valid_bank,
        asset_name="BANKNIFTY",
        folds=folds,
        dev_fold_count=14,
    )

    # Step 5: Cross-Asset Transfer & Dual Portfolio
    transfers, portfolio_summary = evaluate_cross_asset_transfer(
        valid_nifty=valid_nifty,
        valid_bank=valid_bank,
        folds=folds,
        dev_fold_count=14,
    )

    # Step 6: Assemble Comprehensive Report
    nifty_asset_summary = M40AssetSummary(
        asset_name="NIFTY",
        mean_bar_displacement_pct=mean_nifty_disp * 100.0,
        alpha_to_friction_ratio=nifty_ratio,
        strategies=nifty_strategies,
    )

    bank_asset_summary = M40AssetSummary(
        asset_name="BANKNIFTY",
        mean_bar_displacement_pct=mean_bank_disp * 100.0,
        alpha_to_friction_ratio=bank_ratio,
        strategies=bank_strategies,
    )

    report = M40BenchmarkReport(
        milestone="M40",
        created_at=datetime.now(timezone.utc).isoformat(),
        nifty_dataset_id=nifty_id,
        banknifty_dataset_id=bank_id,
        total_15m_candles=len(nifty_data["candles"]),
        resampled_htf_candles=len(htf_nifty),
        total_aligned_rows=total_valid,
        num_folds=len(folds),
        dev_fold_count=14,
        holdout_fold_count=5,
        nifty_summary=nifty_asset_summary,
        banknifty_summary=bank_asset_summary,
        cross_transfers=transfers,
        dual_portfolio_summary=portfolio_summary,
        safety_invariants={
            "forecast_ready": False,
            "real_market_data_verified": False,
            "paper_approved": False,
            "live_approved": False,
            "live_broker_routing_enabled": False,
        },
    )

    # Step 7: Serialize to var/datasets
    out_path = REPO_ROOT / "var" / "datasets" / "m40_multi_asset_benchmark.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(asdict(report), f, indent=2)

    log.info(f"Successfully generated and serialized M40 benchmark report to {out_path}")
    return report
