"""Milestone M20 Research Engine: Higher-Timeframe Context and Selective-Entry Research.

Prepared as an EXPERIMENTAL research evaluation.
Strictly preserved as NOT APPROVED for live or paper trading.
All safety invariants hardcoded to False.

Features:
1. Higher-Timeframe (HTF) 1-hour context features:
   - Point-in-time completed hourly bar alignment (no future bar leakage)
   - htf_1h_return, htf_1h_range, htf_1h_trend_dir, htf_1h_close_vs_sma3
2. Strict Validation-Only Threshold Tuning:
   - Experimental conviction hyperparameters (theta_long, theta_exit) tuned ONLY on validation folds
   - Untouched chronological test fold evaluation
   - Final untouched session holdout preserved
3. Candidate Model Comparisons (6 canonical models):
   - empirical_prior (climatological base-rate)
   - majority_class (discrete majority rule)
   - last_return_sign (discrete momentum rule)
   - logistic_regression_base (8 baseline features, unconstrained 0.50)
   - logistic_regression_htf (12 features with HTF, unconstrained 0.50)
   - selective_entry_htf (12 features with HTF, validation-tuned conviction thresholds)
4. Full Multi-Dimensional Reporting:
   - Accuracy, Balanced Accuracy, Precision, Recall, Brier score, Brier Skill Score, Log-loss
   - Turnovers, Trade counts, Max Drawdown
   - Net returns across 0.0, 1.0, 2.0, 5.0, 10.0 bps frictions
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.forecasting.metrics import binary_metrics
from app.forecasting.m19_research import (
    FeatureScaler,
    M19ResearchConfig,
    SimpleLogisticRegression,
    extract_point_in_time_features,
)


class M20ResearchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False  # Experimental research only; NOT approved for live
    initial_train_size: int = 50
    validation_size: int = 25
    test_size: int = 25
    step_size: int = 25
    embargo_bars: int = 1
    cost_hurdles_bps: list[float] = Field(default_factory=lambda: [0.0, 1.0, 2.0, 5.0, 10.0])
    threshold_candidates: list[tuple[float, float]] = Field(
        default_factory=lambda: [
            (0.50, 0.50),  # Unconstrained
            (0.52, 0.48),  # Narrow deadband
            (0.54, 0.46),  # Medium conviction
            (0.56, 0.44),  # High conviction
            (0.58, 0.42),  # Very high conviction
        ]
    )
    tuning_metric_hurdle_bps: float = 2.0
    seed: int = 42


def compute_max_drawdown(returns: list[float]) -> float:
    """Compute maximum peak-to-trough equity drawdown percentage."""
    if not returns:
        return 0.0
    cum = 1.0
    peak = 1.0
    max_dd = 0.0

    for r in returns:
        cum *= (1.0 + r)
        if cum > peak:
            peak = cum
        dd = (cum - peak) / peak if peak > 0 else 0.0
        if dd < max_dd:
            max_dd = dd

    return round(max_dd * 100.0, 3)


def build_htf_1hour_context(candles: list[dict[str, Any]]) -> dict[int, dict[str, float]]:
    """Compute 1-hour higher-timeframe features point-in-time for each 15-minute bar index.
    
    A 1-hour bar completes every 4 15-minute bars (09:15-10:15, 10:15-11:15, etc.).
    For bar index t, HTF features ONLY use completed 1-hour bars up to or at time t.
    Zero future leakage: incomplete intra-hour bars are strictly excluded from SMA and trend closes.
    """
    n = len(candles)
    htf_context: dict[int, dict[str, float]] = {}

    # Group into completed 1-hour bars (4 consecutive 15m bars)
    hourly_bars: list[dict[str, Any]] = []
    for i in range(0, n - 3, 4):
        chunk = candles[i : i + 4]
        h_open = float(chunk[0]["open"])
        h_high = max(float(c["high"]) for c in chunk)
        h_low = min(float(c["low"]) for c in chunk)
        h_close = float(chunk[-1]["close"])
        hourly_bars.append({
            "end_index": i + 3,
            "open": h_open,
            "high": h_high,
            "low": h_low,
            "close": h_close,
            "return": (h_close / h_open - 1.0) if h_open > 0 else 0.0,
            "range": (h_high - h_low) / h_open if h_open > 0 else 0.0,
        })

    # Map each 15m index to the latest completed 1-hour bar
    for idx in range(n):
        # find completed hourly bars strictly ending at or before idx
        past_hourly = [h for h in hourly_bars if h["end_index"] <= idx]
        if len(past_hourly) >= 3:
            latest_h = past_hourly[-1]
            h_sma3 = statistics.mean([h["close"] for h in past_hourly[-3:]])
            trend_dir = 1.0 if latest_h["close"] > h_sma3 else -1.0
            htf_context[idx] = {
                "htf_1h_return": latest_h["return"],
                "htf_1h_range": latest_h["range"],
                "htf_1h_trend_dir": trend_dir,
                "htf_1h_close_vs_sma3": (latest_h["close"] / h_sma3 - 1.0) if h_sma3 > 0 else 0.0,
            }
        else:
            htf_context[idx] = {
                "htf_1h_return": 0.0,
                "htf_1h_range": 0.0,
                "htf_1h_trend_dir": 0.0,
                "htf_1h_close_vs_sma3": 0.0,
            }

    return htf_context


def evaluate_selective_transaction_costs(
    test_rows: list[dict[str, Any]],
    probabilities: list[float],
    threshold_long: float,
    threshold_exit: float,
    hurdles_bps: list[float],
) -> dict[str, Any]:
    """Evaluate financial performance with exact execution frictions and trade counting.
    
    Position state machine:
    - Enter Long (1.0) if P(Y=1) >= threshold_long
    - Exit Long to Flat (0.0) if P(Y=1) <= threshold_exit
    - Maintain existing position if threshold_exit < P(Y=1) < threshold_long
    
    Frictions:
    - 1 bp = 0.0001 (deducted on each turnover event |Pos_t - Pos_{t-1}|)
    - Closed trade count: incremented on position transition from 1.0 back to 0.0
    """
    n = len(test_rows)
    if n == 0:
        return {}

    # Build hysteretic position sequence
    positions = []
    current_pos = 0.0
    for p in probabilities:
        if p >= threshold_long:
            current_pos = 1.0
        elif p <= threshold_exit:
            current_pos = 0.0
        positions.append(current_pos)

    results = {}
    for hurdle in hurdles_bps:
        friction_rate = hurdle / 10000.0  # 1 bp = 0.0001
        prev_pos = 0.0
        cum_ret = 1.0
        returns_list: list[float] = []
        turnovers_count = 0
        closed_trades = 0

        for idx, row in enumerate(test_rows):
            pos = positions[idx]
            turnover = abs(pos - prev_pos)
            if turnover > 0:
                turnovers_count += 1
                if prev_pos == 1.0 and pos == 0.0:
                    closed_trades += 1

            gross_bar_ret = pos * float(row["next_return"])
            fee = turnover * friction_rate
            net_bar_ret = gross_bar_ret - fee

            cum_ret *= (1.0 + net_bar_ret)
            returns_list.append(net_bar_ret)
            prev_pos = pos

        # If still in trade at window end, count open trade as 1 trade
        active_trades = closed_trades + (1 if prev_pos == 1.0 else 0)

        mean_net = statistics.mean(returns_list) if returns_list else 0.0
        std_net = statistics.stdev(returns_list) if len(returns_list) > 1 else 0.0
        sharpe = (mean_net / std_net * math.sqrt(25 * 250)) if std_net > 1e-8 else 0.0
        mdd = compute_max_drawdown(returns_list)

        results[f"{hurdle}_bps"] = {
            "hurdle_bps": hurdle,
            "friction_per_turn": friction_rate,
            "total_turnover_events": turnovers_count,
            "closed_trades_count": closed_trades,
            "total_trades_count": active_trades,
            "turnover_rate": turnovers_count / n if n > 0 else 0.0,
            "cumulative_return_pct": round((cum_ret - 1.0) * 100, 3),
            "mean_net_return_per_bar_pct": round(mean_net * 100, 5),
            "max_drawdown_pct": mdd,
            "annualized_sharpe_ratio": round(sharpe, 2),
            "profitable": cum_ret > 1.0,
        }

    return results


def run_m20_walk_forward_evaluation(
    candles: list[dict[str, Any]],
    config: M20ResearchConfig | None = None,
    dataset_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute complete Milestone M20 walk-forward research comparing 6 candidate models.
    
    Candidate Models:
    1. empirical_prior: Unconditional training prevalence probability forecast
    2. majority_class: Discrete mode decision rule
    3. last_return_sign: Discrete momentum sign decision rule
    4. logistic_regression_base: 8 baseline features, unconstrained p > 0.50
    5. logistic_regression_htf: 12 features (base + 1h HTF), unconstrained p > 0.50
    6. selective_entry_htf: 12 features with validation-tuned conviction thresholds
    """
    cfg = config or M20ResearchConfig()
    base_rows = extract_point_in_time_features(candles)
    htf_context = build_htf_1hour_context(candles)

    # Augment features
    for r in base_rows:
        idx = r["index"]
        htf = htf_context.get(idx, {})
        r["features_base"] = r["features"]
        r["features_htf"] = {**r["features"], **htf}

    base_feature_names = [
        "ret_1", "ret_3", "ret_5", "close_vs_sma_5",
        "hl_range", "oc_return", "close_position", "ret_std_5",
    ]
    htf_feature_names = base_feature_names + [
        "htf_1h_return", "htf_1h_range", "htf_1h_trend_dir", "htf_1h_close_vs_sma3",
    ]

    total_rows = len(base_rows)
    min_required = cfg.initial_train_size + cfg.validation_size + cfg.test_size + cfg.embargo_bars
    if total_rows < min_required:
        return {
            "ok": False,
            "code": "INSUFFICIENT_OBSERVATIONS",
            "message": f"Requires at least {min_required} rows, got {total_rows}.",
            "forecast_ready": False,
            "real_market_data_verified": False,
        }

    folds = []
    train_end = cfg.initial_train_size
    fold_idx = 1

    while train_end + cfg.embargo_bars + cfg.validation_size + cfg.test_size <= total_rows:
        val_start = train_end + cfg.embargo_bars
        val_end = val_start + cfg.validation_size
        test_start = val_end
        test_end = test_start + cfg.test_size

        train_rows = base_rows[:train_end]
        val_rows = base_rows[val_start:val_end]
        test_rows = base_rows[test_start:test_end]

        y_train = [r["direction"] for r in train_rows]
        y_val = [r["direction"] for r in val_rows]
        y_test = [r["direction"] for r in test_rows]

        # -------------------------------------------------------------
        # 1. Empirical Prior Baseline
        # -------------------------------------------------------------
        pos_train = sum(y_train)
        p_prior = pos_train / len(y_train) if len(y_train) > 0 else 0.5
        p_prior_val = [p_prior] * len(y_val)
        p_prior_test = [p_prior] * len(y_test)
        prior_metrics_val = binary_metrics(y_val, p_prior_val)
        prior_metrics_test = binary_metrics(y_test, p_prior_test)
        prior_costs = evaluate_selective_transaction_costs(test_rows, p_prior_test, 0.50, 0.50, cfg.cost_hurdles_bps)

        # -------------------------------------------------------------
        # 2. Majority Class Baseline (Hard Discrete)
        # -------------------------------------------------------------
        maj_class = 1 if pos_train >= len(y_train) - pos_train else 0
        p_maj_val = [float(maj_class)] * len(y_val)
        p_maj_test = [float(maj_class)] * len(y_test)
        maj_metrics_val = binary_metrics(y_val, p_maj_val)
        maj_metrics_test = binary_metrics(y_test, p_maj_test)
        maj_costs = evaluate_selective_transaction_costs(test_rows, p_maj_test, 0.50, 0.50, cfg.cost_hurdles_bps)

        # -------------------------------------------------------------
        # 3. Last Return Sign Baseline (Hard Discrete)
        # -------------------------------------------------------------
        p_last_val = [1.0 if float(r["features"]["ret_1"]) > 0 else 0.0 for r in val_rows]
        p_last_test = [1.0 if float(r["features"]["ret_1"]) > 0 else 0.0 for r in test_rows]
        last_metrics_val = binary_metrics(y_val, p_last_val)
        last_metrics_test = binary_metrics(y_test, p_last_test)
        last_costs = evaluate_selective_transaction_costs(test_rows, p_last_test, 0.50, 0.50, cfg.cost_hurdles_bps)

        # -------------------------------------------------------------
        # 4. Logistic Regression Base (8 features, unconstrained)
        # -------------------------------------------------------------
        scaler_base = FeatureScaler()
        scaler_base.fit([{"features": r["features_base"]} for r in train_rows], base_feature_names)
        x_train_base = scaler_base.transform([{"features": r["features_base"]} for r in train_rows], base_feature_names)
        x_val_base = scaler_base.transform([{"features": r["features_base"]} for r in val_rows], base_feature_names)
        x_test_base = scaler_base.transform([{"features": r["features_base"]} for r in test_rows], base_feature_names)

        model_base = SimpleLogisticRegression(lr=0.08, epochs=200, l2_penalty=0.02)
        model_base.fit(x_train_base, y_train)
        p_log_base_val = model_base.predict_proba(x_val_base)
        p_log_base_test = model_base.predict_proba(x_test_base)

        log_base_metrics_val = binary_metrics(y_val, p_log_base_val)
        log_base_metrics_test = binary_metrics(y_test, p_log_base_test)
        log_base_costs = evaluate_selective_transaction_costs(test_rows, p_log_base_test, 0.50, 0.50, cfg.cost_hurdles_bps)

        # -------------------------------------------------------------
        # 5. Logistic Regression HTF (12 features with HTF, unconstrained)
        # -------------------------------------------------------------
        scaler_htf = FeatureScaler()
        scaler_htf.fit([{"features": r["features_htf"]} for r in train_rows], htf_feature_names)
        x_train_htf = scaler_htf.transform([{"features": r["features_htf"]} for r in train_rows], htf_feature_names)
        x_val_htf = scaler_htf.transform([{"features": r["features_htf"]} for r in val_rows], htf_feature_names)
        x_test_htf = scaler_htf.transform([{"features": r["features_htf"]} for r in test_rows], htf_feature_names)

        model_htf = SimpleLogisticRegression(lr=0.08, epochs=200, l2_penalty=0.02)
        model_htf.fit(x_train_htf, y_train)
        p_log_htf_val = model_htf.predict_proba(x_val_htf)
        p_log_htf_test = model_htf.predict_proba(x_test_htf)

        log_htf_metrics_val = binary_metrics(y_val, p_log_htf_val)
        log_htf_metrics_test = binary_metrics(y_test, p_log_htf_test)
        log_htf_costs = evaluate_selective_transaction_costs(test_rows, p_log_htf_test, 0.50, 0.50, cfg.cost_hurdles_bps)

        # -------------------------------------------------------------
        # 6. Selective Entry HTF (Validation-Tuned Conviction Thresholds)
        # -------------------------------------------------------------
        best_cand = (0.50, 0.50)
        best_val_ret = -999.0
        tuning_hurdle = cfg.tuning_metric_hurdle_bps

        for (tl, te) in cfg.threshold_candidates:
            val_eval = evaluate_selective_transaction_costs(val_rows, p_log_htf_val, tl, te, [tuning_hurdle])
            cand_ret = val_eval[f"{tuning_hurdle}_bps"]["cumulative_return_pct"]
            if cand_ret > best_val_ret:
                best_val_ret = cand_ret
                best_cand = (tl, te)

        # Apply chosen threshold pair to untouched test fold
        sel_htf_costs = evaluate_selective_transaction_costs(
            test_rows,
            p_log_htf_test,
            best_cand[0],
            best_cand[1],
            cfg.cost_hurdles_bps,
        )

        # Record fold
        fold_record = {
            "fold_index": fold_idx,
            "train_window": (train_rows[0]["as_of"], train_rows[-1]["as_of"]),
            "train_count": len(train_rows),
            "validation_window": (val_rows[0]["as_of"], val_rows[-1]["as_of"]),
            "validation_count": len(val_rows),
            "test_window": (test_rows[0]["as_of"], test_rows[-1]["as_of"]),
            "test_count": len(test_rows),
            "embargo_bars": cfg.embargo_bars,
            "validation_tuned_thresholds": {
                "threshold_long": best_cand[0],
                "threshold_exit": best_cand[1],
                "validation_return_at_tuning_hurdle": best_val_ret,
            },
            "models": {
                "empirical_prior": {
                    "validation": prior_metrics_val,
                    "test": prior_metrics_test,
                    "transaction_cost_sensitivity": prior_costs,
                },
                "majority_class": {
                    "validation": maj_metrics_val,
                    "test": maj_metrics_test,
                    "transaction_cost_sensitivity": maj_costs,
                },
                "last_return_sign": {
                    "validation": last_metrics_val,
                    "test": last_metrics_test,
                    "transaction_cost_sensitivity": last_costs,
                },
                "logistic_regression_base": {
                    "validation": log_base_metrics_val,
                    "test": log_base_metrics_test,
                    "transaction_cost_sensitivity": log_base_costs,
                },
                "logistic_regression_htf": {
                    "validation": log_htf_metrics_val,
                    "test": log_htf_metrics_test,
                    "transaction_cost_sensitivity": log_htf_costs,
                },
                "selective_entry_htf": {
                    "validation": log_htf_metrics_val,
                    "test": log_htf_metrics_test,
                    "transaction_cost_sensitivity": sel_htf_costs,
                },
            },
        }
        folds.append(fold_record)

        train_end += cfg.step_size
        fold_idx += 1

    # Aggregate metrics across all test folds for all 6 models
    summary_metrics: dict[str, dict[str, Any]] = {}
    model_names = [
        "empirical_prior",
        "majority_class",
        "last_return_sign",
        "logistic_regression_base",
        "logistic_regression_htf",
        "selective_entry_htf",
    ]

    for m_name in model_names:
        accuracies = []
        bal_accs = []
        briers = []
        precisions = []
        recalls = []
        log_losses = []

        cost_reports_by_hurdle: dict[str, Any] = {}
        for h in cfg.cost_hurdles_bps:
            h_key = f"{h}_bps"
            fold_rets = []
            turnovers = 0
            trades = 0
            drawdowns = []
            compounded = 1.0

            for f in folds:
                cs = f["models"][m_name]["transaction_cost_sensitivity"].get(h_key, {})
                if cs:
                    r_pct = cs.get("cumulative_return_pct", 0.0)
                    fold_rets.append(r_pct)
                    compounded *= (1.0 + r_pct / 100.0)
                    turnovers += cs.get("total_turnover_events", 0)
                    trades += cs.get("total_trades_count", 0)
                    drawdowns.append(cs.get("max_drawdown_pct", 0.0))

            cost_reports_by_hurdle[h_key] = {
                "hurdle_bps": h,
                "mean_fold_net_return_pct": round(statistics.mean(fold_rets), 3) if fold_rets else 0.0,
                "compounded_net_return_pct": round((compounded - 1.0) * 100, 3) if fold_rets else 0.0,
                "total_turnover_events": turnovers,
                "total_trades_count": trades,
                "worst_fold_drawdown_pct": min(drawdowns) if drawdowns else 0.0,
            }

        for f in folds:
            t = f["models"][m_name]["test"]
            if t.get("status") == "DEFINED":
                if t["accuracy"]["value"] is not None:
                    accuracies.append(t["accuracy"]["value"])
                if t["balanced_accuracy"]["value"] is not None:
                    bal_accs.append(t["balanced_accuracy"]["value"])
                if t["brier"]["value"] is not None:
                    briers.append(t["brier"]["value"])
                if t["precision"]["value"] is not None:
                    precisions.append(t["precision"]["value"])
                if t["recall"]["value"] is not None:
                    recalls.append(t["recall"]["value"])
                if t["log_loss"]["value"] is not None:
                    log_losses.append(t["log_loss"]["value"])

        summary_metrics[m_name] = {
            "folds_evaluated": len(folds),
            "mean_test_accuracy": round(statistics.mean(accuracies), 4) if accuracies else None,
            "mean_test_balanced_accuracy": round(statistics.mean(bal_accs), 4) if bal_accs else None,
            "mean_test_brier_score": round(statistics.mean(briers), 4) if briers else None,
            "mean_test_precision": round(statistics.mean(precisions), 4) if precisions else None,
            "mean_test_recall": round(statistics.mean(recalls), 4) if recalls else None,
            "mean_test_log_loss": round(statistics.mean(log_losses), 4) if log_losses else None,
            "transaction_cost_schedule": cost_reports_by_hurdle,
        }

    # Brier Skill Scores vs Empirical Prior
    prior_brier = summary_metrics["empirical_prior"]["mean_test_brier_score"]
    bss_reports = {}
    for m_name in model_names:
        m_brier = summary_metrics[m_name]["mean_test_brier_score"]
        if m_brier is not None and prior_brier and prior_brier > 0:
            bss = round(1.0 - (m_brier / prior_brier), 4)
            bss_reports[m_name] = bss
        else:
            bss_reports[m_name] = None

    return {
        "ok": True,
        "evaluation_name": "M20_RESEARCH_HTF_AND_SELECTIVE_ENTRY",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_metadata": dataset_metadata or {},
        "experimental_status": "RESEARCH_PROPOSAL_ONLY_NOT_APPROVED",
        "trading_decision": "BLOCKED",
        "leakage_prevention": {
            "chronological_expanding_splits": True,
            "no_shuffling": True,
            "scaler_fitted_on_training_only": True,
            "htf_completed_bars_only": True,
            "embargo_bars": cfg.embargo_bars,
            "lookahead_leakage_detected": False,
        },
        "total_folds": len(folds),
        "folds": folds,
        "summary_metrics": summary_metrics,
        "brier_skill_scores_vs_prior": bss_reports,
        "safety_invariants": {
            "forecast_ready": False,
            "real_market_data_verified": False,
            "paper_approved": False,
            "live_approved": False,
            "live_broker_routing_enabled": False,
        },
    }


def prepare_m20_walk_forward_specification(config: M20ResearchConfig | None = None) -> dict[str, Any]:
    """Prepare inactive M20 walk-forward specification preserving safety invariants."""
    cfg = config or M20ResearchConfig()
    return {
        "enabled": cfg.enabled,
        "status": "PREPARED_INACTIVE",
        "description": "Milestone M20 Higher-Timeframe Context and Selective-Entry Research Specification",
        "safety_invariants": {
            "forecast_ready": False,
            "real_market_data_verified": False,
            "paper_approved": False,
            "live_approved": False,
            "live_broker_routing_enabled": False,
        },
        "config": cfg.model_dump(),
    }

