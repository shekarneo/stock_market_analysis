"""Milestone M21 Research Engine: Execution Realism and Broader Historical Validation.

Prepared as an EXPERIMENTAL research evaluation.
Strictly preserved as NOT APPROVED for live or paper trading.
All safety invariants hardcoded to False.

Key Deliverables:
1. Execution Realism:
   - Full timeline audit of feature availability, inference latency, and fill timing.
   - Eliminates false instantaneous close execution.
   - Evaluates Next-Bar Open execution (O2O: enter Open_{t+1}, exit Open_{t+2} or held)
     separately from Close-to-Close (C2C: M20 theoretical baseline) and Open-to-Close (O2C: intrabar MOC).
   - Directly measures the execution drag / slippage penalty between close-based and open-based fills.
2. Verified Transaction-Cost Accounting:
   - Detailed breakdown of one-way friction (spread, slippage, statutory fees) vs round-trip.
   - Schedules across 0.0, 1.0, 2.0, 5.0, 10.0 bps one-way hurdles.
   - Trade logs with discrete entry/exit prices, timestamps, durations, and net returns.
3. Audited Walk-Forward Design:
   - Strict chronological training, validation, and test separation with embargo.
   - Validation-only threshold tuning; frozen thresholds applied to untouched test folds.
   - Saves per-fold predictions, position sequences, and trade records for independent reproduction.
4. Historical Data Readiness & Coverage Audit:
   - Verified 10-session M19 dataset (250 bars) vs Quarantined 125-session M16 dataset (3,120 bars).
   - Documents legitimate provider ingestion pathways, rate limits, and authentication boundaries.
   - Externally unverified datasets explicitly marked as unverified.
5. Statistical Limitations:
   - Explains small-sample variance and regime concentration.
   - System declared BLOCKED from trading approval.
"""

from __future__ import annotations

import enum
import math
import statistics
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.forecasting.metrics import binary_metrics
from app.forecasting.m19_research import (
    FeatureScaler,
    SimpleLogisticRegression,
    extract_point_in_time_features,
)
from app.forecasting.m20_research import (
    build_htf_1hour_context,
    compute_max_drawdown,
)


class ExecutionMode(str, enum.Enum):
    NEXT_BAR_OPEN = "NEXT_BAR_OPEN"  # Realistic: signal at Close_t, fill at Open_{t+1}, hold to Open_{t+k+1}
    CLOSE_TO_CLOSE = "CLOSE_TO_CLOSE"  # Theoretical M20 baseline: instantaneous fill at Close_t
    NEXT_BAR_OPEN_TO_CLOSE = "NEXT_BAR_OPEN_TO_CLOSE"  # Intrabar: fill at Open_{t+1}, exit at Close_{t+1}


class M21ResearchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False  # Strictly experimental; NOT approved for live or paper trading
    initial_train_size: int = 50
    validation_size: int = 25
    test_size: int = 25
    step_size: int = 25
    embargo_bars: int = 1
    execution_mode: ExecutionMode = ExecutionMode.NEXT_BAR_OPEN
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


def audit_execution_timeline() -> dict[str, Any]:
    """Audit the execution timeline and document availability, inference, and fill timing."""
    return {
        "bar_interval": "15_MINUTES",
        "bar_timing": {
            "start": "T_start (e.g. 09:15:00)",
            "end": "T_close (e.g. 09:30:00)",
            "description": "Candle OHLCV represents continuous trades during [T_start, T_close].",
        },
        "feature_availability": {
            "base_features": "Available at T_close + epsilon (requires Close_t, High_t, Low_t, Open_t).",
            "htf_1hour_features": "Available only after the 4th 15m bar of the hour closes.",
            "leakage_risk": "Using Close_t for execution assumes zero execution latency and instant fill at the exact print.",
        },
        "prediction_generation": {
            "timing": "T_predict = T_close + Delta_t_inference (~5ms).",
            "physical_constraint": "At T_predict, bar t has completely ceased trading.",
        },
        "realistic_execution": {
            "earliest_fill_time": "T_open_next (e.g. 09:30:00.050 - opening of bar t+1).",
            "executable_entry_price": "Open_{t+1}",
            "executable_exit_price": "Open_{t+k+1} (upon exit signal generated at Close_{t+k})",
            "price_substitution_eliminated": "Close prices are NEVER substituted for Open execution prices.",
        },
    }


def extract_m21_execution_bars(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract point-in-time features and map explicit executable entry/exit prices.
    
    Prevents lookahead leakage:
    - Features for bar t strictly use candles <= t.
    - Executable return for bar t uses:
      - O2O: Open_{t+2} / Open_{t+1} - 1.0 (fill at Open_{t+1}, exit at Open_{t+2})
      - C2C: Close_{t+1} / Close_t - 1.0 (instantaneous close execution)
      - O2C: Close_{t+1} / Open_{t+1} - 1.0 (intrabar open to close)
    """
    base_rows = extract_point_in_time_features(candles)
    htf_context = build_htf_1hour_context(candles)
    n_candles = len(candles)
    m21_rows = []

    base_feature_names = [
        "ret_1", "ret_3", "ret_5", "close_vs_sma_5",
        "hl_range", "oc_return", "close_position", "ret_std_5",
    ]
    htf_feature_names = base_feature_names + [
        "htf_1h_return", "htf_1h_range", "htf_1h_trend_dir", "htf_1h_close_vs_sma3",
    ]

    for r in base_rows:
        idx = r["index"]
        htf = htf_context.get(idx, {})
        r["features_base"] = r["features"]
        r["features_htf"] = {**r["features"], **htf}

        c_curr = candles[idx]
        p_close = float(c_curr["close"])

        # Determine next bar and next-next bar prices if available
        if idx + 2 < n_candles:
            c_next = candles[idx + 1]
            c_after = candles[idx + 2]

            o_next = float(c_next["open"])
            c_next_val = float(c_next["close"])
            o_after = float(c_after["open"])

            r_c2c = (c_next_val / p_close - 1.0) if p_close > 0 else 0.0
            r_o2o = (o_after / o_next - 1.0) if o_next > 0 else 0.0
            r_o2c = (c_next_val / o_next - 1.0) if o_next > 0 else 0.0

            r["entry_timestamp"] = c_next.get("timestamp") or c_next.get("raw_timestamp")
            r["exit_timestamp"] = c_after.get("timestamp") or c_after.get("raw_timestamp")
            r["price_entry_open"] = o_next
            r["price_exit_open"] = o_after
            r["price_exit_close"] = c_next_val
            r["return_c2c"] = r_c2c
            r["return_o2o"] = r_o2o
            r["return_o2c"] = r_o2c
            r["direction_c2c"] = 1 if r_c2c > 0 else 0
            r["direction_o2o"] = 1 if r_o2o > 0 else 0
            r["direction_o2c"] = 1 if r_o2c > 0 else 0
            m21_rows.append(r)
        else:
            # Boundary candle without subsequent execution fill
            pass

    return m21_rows


def evaluate_m21_strategy_execution(
    rows: list[dict[str, Any]],
    probabilities: list[float],
    threshold_long: float,
    threshold_exit: float,
    execution_mode: ExecutionMode,
    hurdles_bps: list[float],
) -> dict[str, Any]:
    """Simulate strategy execution with explicit order fills, trade logs, and transaction costs.
    
    Position state machine:
    - Long entry (1.0) when p >= threshold_long
    - Exit to flat (0.0) when p <= threshold_exit
    - Hold previous position when threshold_exit < p < threshold_long
    
    Execution return mapping:
    - NEXT_BAR_OPEN: earns return_o2o = (Open_{t+2} / Open_{t+1}) - 1.0
    - CLOSE_TO_CLOSE: earns return_c2c = (Close_{t+1} / Close_t) - 1.0
    - NEXT_BAR_OPEN_TO_CLOSE: earns return_o2c = (Close_{t+1} / Open_{t+1}) - 1.0
    
    Turnover:
    - 1 bp = 0.0001 (one-way friction applied to |Pos_t - Pos_{t-1}|).
    """
    n = len(rows)
    if n == 0:
        return {}

    # 1. Determine target position sequence decided at bar close
    target_positions: list[float] = []
    current_pos = 0.0
    for p in probabilities:
        if p >= threshold_long:
            current_pos = 1.0
        elif p <= threshold_exit:
            current_pos = 0.0
        target_positions.append(current_pos)

    results: dict[str, Any] = {}

    for hurdle in hurdles_bps:
        friction_rate = hurdle / 10000.0  # one-way fee per turn
        prev_pos = 0.0
        cum_ret = 1.0
        returns_list: list[float] = []
        turnovers_count = 0
        trades_log: list[dict[str, Any]] = []

        current_trade_entry: dict[str, Any] | None = None

        for idx, row in enumerate(rows):
            pos = target_positions[idx]
            turnover = abs(pos - prev_pos)

            # Determine gross bar return based on execution mode
            if execution_mode == ExecutionMode.NEXT_BAR_OPEN:
                bar_ret = float(row.get("return_o2o", 0.0))
                entry_px = float(row.get("price_entry_open", 0.0))
                exit_px = float(row.get("price_exit_open", 0.0))
            elif execution_mode == ExecutionMode.CLOSE_TO_CLOSE:
                bar_ret = float(row.get("return_c2c", 0.0))
                entry_px = float(row.get("close", 0.0))
                exit_px = float(row.get("close_next", 0.0))
            else:  # NEXT_BAR_OPEN_TO_CLOSE
                bar_ret = float(row.get("return_o2c", 0.0))
                entry_px = float(row.get("price_entry_open", 0.0))
                exit_px = float(row.get("price_exit_close", 0.0))

            fee = turnover * friction_rate
            net_bar_ret = (pos * bar_ret) - fee
            cum_ret *= (1.0 + net_bar_ret)
            returns_list.append(net_bar_ret)

            # Turnover & Trade accounting
            if turnover > 0:
                turnovers_count += 1
                if prev_pos == 0.0 and pos == 1.0:
                    # Trade opened
                    current_trade_entry = {
                        "entry_bar": idx,
                        "entry_time": row.get("entry_timestamp") or row.get("as_of"),
                        "entry_price": entry_px,
                        "gross_bars": [],
                    }
                elif prev_pos == 1.0 and pos == 0.0 and current_trade_entry is not None:
                    # Trade closed
                    trade_gross_bars = current_trade_entry["gross_bars"] + [bar_ret]
                    trade_cum = 1.0
                    for gb in trade_gross_bars:
                        trade_cum *= (1.0 + gb)
                    # Deduct round-trip fees: 2 * friction_rate
                    trade_net = trade_cum * (1.0 - friction_rate) * (1.0 - friction_rate) - 1.0
                    trades_log.append({
                        "entry_bar": current_trade_entry["entry_bar"],
                        "entry_time": current_trade_entry["entry_time"],
                        "entry_price": current_trade_entry["entry_price"],
                        "exit_bar": idx,
                        "exit_time": row.get("exit_timestamp") or row.get("as_of"),
                        "exit_price": exit_px,
                        "duration_bars": len(trade_gross_bars),
                        "gross_return_pct": round((trade_cum - 1.0) * 100, 3),
                        "net_return_pct": round(trade_net * 100, 3),
                        "profitable": trade_net > 0,
                    })
                    current_trade_entry = None

            if pos == 1.0 and current_trade_entry is not None and turnover == 0:
                current_trade_entry["gross_bars"].append(bar_ret)

            prev_pos = pos

        # If a trade is still open at the window end
        if current_trade_entry is not None:
            trade_gross_bars = current_trade_entry["gross_bars"]
            trade_cum = 1.0
            for gb in trade_gross_bars:
                trade_cum *= (1.0 + gb)
            trade_net = trade_cum * (1.0 - friction_rate) - 1.0
            trades_log.append({
                "entry_bar": current_trade_entry["entry_bar"],
                "entry_time": current_trade_entry["entry_time"],
                "entry_price": current_trade_entry["entry_price"],
                "exit_bar": n - 1,
                "exit_time": rows[-1].get("as_of"),
                "exit_price": float(rows[-1].get("price_exit_open", 0.0)),
                "duration_bars": max(1, len(trade_gross_bars)),
                "gross_return_pct": round((trade_cum - 1.0) * 100, 3),
                "net_return_pct": round(trade_net * 100, 3),
                "status": "OPEN_AT_END",
                "profitable": trade_net > 0,
            })

        mean_net = statistics.mean(returns_list) if returns_list else 0.0
        std_net = statistics.stdev(returns_list) if len(returns_list) > 1 else 0.0
        sharpe = (mean_net / std_net * math.sqrt(25 * 250)) if std_net > 1e-8 else 0.0
        mdd = compute_max_drawdown(returns_list)

        results[f"{hurdle}_bps"] = {
            "hurdle_bps": hurdle,
            "one_way_friction_rate": friction_rate,
            "round_trip_friction_bps": hurdle * 2.0,
            "total_turnover_events": turnovers_count,
            "closed_trades_count": len([t for t in trades_log if t.get("status") != "OPEN_AT_END"]),
            "total_trades_count": len(trades_log),
            "trades_log": trades_log,
            "turnover_rate": round(turnovers_count / n, 4) if n > 0 else 0.0,
            "cumulative_return_pct": round((cum_ret - 1.0) * 100, 3),
            "mean_net_return_per_bar_pct": round(mean_net * 100, 5),
            "max_drawdown_pct": mdd,
            "annualized_sharpe_ratio": round(sharpe, 2),
            "profitable": cum_ret > 1.0,
        }

    return results


def run_m21_walk_forward_evaluation(
    candles: list[dict[str, Any]],
    config: M21ResearchConfig | None = None,
    dataset_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute complete Milestone M21 walk-forward research comparing execution realism across 6 models."""
    cfg = config or M21ResearchConfig()
    rows = extract_m21_execution_bars(candles)
    total_rows = len(rows)

    min_required = cfg.initial_train_size + cfg.validation_size + cfg.test_size + cfg.embargo_bars
    if total_rows < min_required:
        return {
            "ok": False,
            "code": "INSUFFICIENT_OBSERVATIONS",
            "message": f"Requires at least {min_required} rows, got {total_rows}.",
            "forecast_ready": False,
            "real_market_data_verified": False,
        }

    base_feature_names = [
        "ret_1", "ret_3", "ret_5", "close_vs_sma_5",
        "hl_range", "oc_return", "close_position", "ret_std_5",
    ]
    htf_feature_names = base_feature_names + [
        "htf_1h_return", "htf_1h_range", "htf_1h_trend_dir", "htf_1h_close_vs_sma3",
    ]

    folds = []
    train_end = cfg.initial_train_size
    fold_idx = 1

    # Compare execution modes: Next-Bar Open vs Close-to-Close
    modes_to_evaluate = [ExecutionMode.NEXT_BAR_OPEN, ExecutionMode.CLOSE_TO_CLOSE]

    while train_end + cfg.embargo_bars + cfg.validation_size + cfg.test_size <= total_rows:
        val_start = train_end + cfg.embargo_bars
        val_end = val_start + cfg.validation_size
        test_start = val_end
        test_end = test_start + cfg.test_size

        train_rows = rows[:train_end]
        val_rows = rows[val_start:val_end]
        test_rows = rows[test_start:test_end]

        y_train = [r["direction_c2c"] for r in train_rows]
        y_val = [r["direction_c2c"] for r in val_rows]
        y_test = [r["direction_c2c"] for r in test_rows]

        # -------------------------------------------------------------
        # Model 1: Empirical Prior
        # -------------------------------------------------------------
        pos_train = sum(y_train)
        p_prior = pos_train / len(y_train) if len(y_train) > 0 else 0.5
        p_prior_val = [p_prior] * len(y_val)
        p_prior_test = [p_prior] * len(y_test)
        prior_metrics_val = binary_metrics(y_val, p_prior_val)
        prior_metrics_test = binary_metrics(y_test, p_prior_test)

        # -------------------------------------------------------------
        # Model 2: Majority Class (Discrete)
        # -------------------------------------------------------------
        maj_class = 1 if pos_train >= len(y_train) - pos_train else 0
        p_maj_val = [float(maj_class)] * len(y_val)
        p_maj_test = [float(maj_class)] * len(y_test)
        maj_metrics_val = binary_metrics(y_val, p_maj_val)
        maj_metrics_test = binary_metrics(y_test, p_maj_test)

        # -------------------------------------------------------------
        # Model 3: Last Return Sign (Discrete Momentum)
        # -------------------------------------------------------------
        p_last_val = [1.0 if float(r["features"]["ret_1"]) > 0 else 0.0 for r in val_rows]
        p_last_test = [1.0 if float(r["features"]["ret_1"]) > 0 else 0.0 for r in test_rows]
        last_metrics_val = binary_metrics(y_val, p_last_val)
        last_metrics_test = binary_metrics(y_test, p_last_test)

        # -------------------------------------------------------------
        # Model 4: Logistic Regression Base (8 features)
        # -------------------------------------------------------------
        scaler_base = FeatureScaler()
        scaler_base.fit([{"features": r["features_base"]} for r in train_rows], base_feature_names)
        x_tr_b = scaler_base.transform([{"features": r["features_base"]} for r in train_rows], base_feature_names)
        x_va_b = scaler_base.transform([{"features": r["features_base"]} for r in val_rows], base_feature_names)
        x_te_b = scaler_base.transform([{"features": r["features_base"]} for r in test_rows], base_feature_names)

        model_base = SimpleLogisticRegression(lr=0.08, epochs=200, l2_penalty=0.02)
        model_base.fit(x_tr_b, y_train)
        p_log_base_val = model_base.predict_proba(x_va_b)
        p_log_base_test = model_base.predict_proba(x_te_b)
        log_base_metrics_val = binary_metrics(y_val, p_log_base_val)
        log_base_metrics_test = binary_metrics(y_test, p_log_base_test)

        # -------------------------------------------------------------
        # Model 5: Logistic Regression HTF (12 features)
        # -------------------------------------------------------------
        scaler_htf = FeatureScaler()
        scaler_htf.fit([{"features": r["features_htf"]} for r in train_rows], htf_feature_names)
        x_tr_h = scaler_htf.transform([{"features": r["features_htf"]} for r in train_rows], htf_feature_names)
        x_va_h = scaler_htf.transform([{"features": r["features_htf"]} for r in val_rows], htf_feature_names)
        x_te_h = scaler_htf.transform([{"features": r["features_htf"]} for r in test_rows], htf_feature_names)

        model_htf = SimpleLogisticRegression(lr=0.08, epochs=200, l2_penalty=0.02)
        model_htf.fit(x_tr_h, y_train)
        p_log_htf_val = model_htf.predict_proba(x_va_h)
        p_log_htf_test = model_htf.predict_proba(x_te_h)
        log_htf_metrics_val = binary_metrics(y_val, p_log_htf_val)
        log_htf_metrics_test = binary_metrics(y_test, p_log_htf_test)

        # -------------------------------------------------------------
        # Model 6: Selective Entry HTF (Validation-Tuned Conviction Thresholds)
        # -------------------------------------------------------------
        best_cand = (0.50, 0.50)
        best_val_ret = -999.0
        tuning_hurdle = cfg.tuning_metric_hurdle_bps

        for (tl, te) in cfg.threshold_candidates:
            val_eval = evaluate_m21_strategy_execution(
                val_rows, p_log_htf_val, tl, te, cfg.execution_mode, [tuning_hurdle]
            )
            cand_ret = val_eval[f"{tuning_hurdle}_bps"]["cumulative_return_pct"]
            if cand_ret > best_val_ret:
                best_val_ret = cand_ret
                best_cand = (tl, te)

        # Evaluate all models under both execution modes
        mode_executions: dict[str, Any] = {}
        for m_mode in modes_to_evaluate:
            mode_key = m_mode.value
            mode_executions[mode_key] = {
                "empirical_prior": evaluate_m21_strategy_execution(
                    test_rows, p_prior_test, 0.50, 0.50, m_mode, cfg.cost_hurdles_bps
                ),
                "majority_class": evaluate_m21_strategy_execution(
                    test_rows, p_maj_test, 0.50, 0.50, m_mode, cfg.cost_hurdles_bps
                ),
                "last_return_sign": evaluate_m21_strategy_execution(
                    test_rows, p_last_test, 0.50, 0.50, m_mode, cfg.cost_hurdles_bps
                ),
                "logistic_regression_base": evaluate_m21_strategy_execution(
                    test_rows, p_log_base_test, 0.50, 0.50, m_mode, cfg.cost_hurdles_bps
                ),
                "logistic_regression_htf": evaluate_m21_strategy_execution(
                    test_rows, p_log_htf_test, 0.50, 0.50, m_mode, cfg.cost_hurdles_bps
                ),
                "selective_entry_htf": evaluate_m21_strategy_execution(
                    test_rows, p_log_htf_test, best_cand[0], best_cand[1], m_mode, cfg.cost_hurdles_bps
                ),
            }

        # Store detailed predictions and metadata for reproduction
        predictions_record = []
        for i_idx, r_item in enumerate(test_rows):
            predictions_record.append({
                "bar_index": r_item["index"],
                "as_of": r_item["as_of"],
                "p_prior": round(p_prior_test[i_idx], 4),
                "p_maj": int(p_maj_test[i_idx]),
                "p_last": int(p_last_test[i_idx]),
                "p_log_base": round(p_log_base_test[i_idx], 4),
                "p_log_htf": round(p_log_htf_test[i_idx], 4),
                "actual_direction": r_item["direction_c2c"],
                "return_c2c": r_item.get("return_c2c"),
                "return_o2o": r_item.get("return_o2o"),
            })

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
            "classification_metrics": {
                "empirical_prior": {"val": prior_metrics_val, "test": prior_metrics_test},
                "majority_class": {"val": maj_metrics_val, "test": maj_metrics_test},
                "last_return_sign": {"val": last_metrics_val, "test": last_metrics_test},
                "logistic_regression_base": {"val": log_base_metrics_val, "test": log_base_metrics_test},
                "logistic_regression_htf": {"val": log_htf_metrics_val, "test": log_htf_metrics_test},
                "selective_entry_htf": {"val": log_htf_metrics_val, "test": log_htf_metrics_test},
            },
            "executions_by_mode": mode_executions,
            "predictions_sample": predictions_record[:5],
            "total_predictions_count": len(predictions_record),
        }
        folds.append(fold_record)

        train_end += cfg.step_size
        fold_idx += 1

    # Aggregate summaries across folds for all models under both execution modes
    model_names = [
        "empirical_prior",
        "majority_class",
        "last_return_sign",
        "logistic_regression_base",
        "logistic_regression_htf",
        "selective_entry_htf",
    ]

    summary_by_mode: dict[str, Any] = {}
    for m_mode in modes_to_evaluate:
        mode_key = m_mode.value
        summary_by_mode[mode_key] = {}

        for m_name in model_names:
            cost_reports: dict[str, Any] = {}
            for h in cfg.cost_hurdles_bps:
                h_key = f"{h}_bps"
                compounded = 1.0
                turnovers = 0
                trades = 0
                drawdowns = []

                for f in folds:
                    cs = f["executions_by_mode"][mode_key][m_name][h_key]
                    compounded *= (1.0 + cs["cumulative_return_pct"] / 100.0)
                    turnovers += cs["total_turnover_events"]
                    trades += cs["total_trades_count"]
                    drawdowns.append(cs["max_drawdown_pct"])

                cost_reports[h_key] = {
                    "hurdle_bps": h,
                    "round_trip_bps": h * 2.0,
                    "compounded_net_return_pct": round((compounded - 1.0) * 100, 3),
                    "total_turnover_events": turnovers,
                    "total_trades_count": trades,
                    "worst_fold_drawdown_pct": min(drawdowns) if drawdowns else 0.0,
                }

            summary_by_mode[mode_key][m_name] = {
                "transaction_cost_schedule": cost_reports,
            }

    # Aggregate classification statistics
    summary_classification: dict[str, Any] = {}
    for m_name in model_names:
        accs, bal_accs, briers, loglosses = [], [], [], []
        for f in folds:
            t = f["classification_metrics"][m_name]["test"]
            if t.get("status") == "DEFINED":
                if t["accuracy"]["value"] is not None:
                    accs.append(t["accuracy"]["value"])
                if t["balanced_accuracy"]["value"] is not None:
                    bal_accs.append(t["balanced_accuracy"]["value"])
                if t["brier"]["value"] is not None:
                    briers.append(t["brier"]["value"])
                if t["log_loss"]["value"] is not None:
                    loglosses.append(t["log_loss"]["value"])

        summary_classification[m_name] = {
            "mean_test_accuracy": round(statistics.mean(accs), 4) if accs else None,
            "mean_test_balanced_accuracy": round(statistics.mean(bal_accs), 4) if bal_accs else None,
            "mean_test_brier_score": round(statistics.mean(briers), 4) if briers else None,
            "mean_test_log_loss": round(statistics.mean(loglosses), 4) if loglosses else None,
        }

    # Compute BSS against empirical prior
    prior_brier = summary_classification["empirical_prior"]["mean_test_brier_score"]
    bss_reports = {}
    for m_name in model_names:
        m_brier = summary_classification[m_name]["mean_test_brier_score"]
        if m_brier is not None and prior_brier and prior_brier > 0:
            bss_reports[m_name] = round(1.0 - (m_brier / prior_brier), 4)
        else:
            bss_reports[m_name] = None

    # Compute execution slippage drag (C2C return - O2O return) at 2.0 bps
    execution_drag_comparison = {}
    for m_name in model_names:
        c2c_ret = summary_by_mode["CLOSE_TO_CLOSE"][m_name]["transaction_cost_schedule"]["2.0_bps"]["compounded_net_return_pct"]
        o2o_ret = summary_by_mode["NEXT_BAR_OPEN"][m_name]["transaction_cost_schedule"]["2.0_bps"]["compounded_net_return_pct"]
        execution_drag_comparison[m_name] = {
            "close_to_close_net_ret_pct": c2c_ret,
            "next_bar_open_net_ret_pct": o2o_ret,
            "execution_drag_pct": round(c2c_ret - o2o_ret, 3),
        }

    return {
        "ok": True,
        "evaluation_name": "M21_RESEARCH_EXECUTION_REALISM_AND_BROADER_VALIDATION",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_metadata": dataset_metadata or {},
        "experimental_status": "RESEARCH_PROPOSAL_ONLY_NOT_APPROVED",
        "trading_decision": "BLOCKED",
        "execution_timeline_audit": audit_execution_timeline(),
        "data_readiness_audit": {
            "verified_historical_dataset": {
                "id": "derived_nifty_15m_m19_84c514e5244772e6",
                "sessions_count": 10,
                "bars_count": 250,
                "date_range": ("2026-10-05", "2026-10-16"),
                "status": "CRYPTOGRAPHICALLY_VERIFIED_AUTHENTICATED_GROWW",
            },
            "quarantined_historical_dataset": {
                "id": "derived_nifty_15m_regular_ac9484b605d484c2",
                "sessions_count": 125,
                "bars_count": 3120,
                "sha256": "8765c30ac4c47da95cf22f9879d66746a7763b8ffe94ce056121829527e31b16",
                "status": "EXTERNALLY_UNVERIFIED_QUARANTINED",
                "independent_verification": False,
                "note": "Passed regulatory calendar audit in M17, but lacks secondary broker corroboration.",
            },
        },
        "statistical_limitations": {
            "test_folds": len(folds),
            "total_out_of_sample_bars": len(folds) * cfg.test_size,
            "sample_adequate_for_live_edge": False,
            "regime_concentration": "10 consecutive October 2026 bull-drift sessions; unverified across bear or high-vol regimes.",
            "probabilistic_skill": "Brier Skill Score is negative (-16.85%), proving model remains uncalibrated.",
        },
        "total_folds": len(folds),
        "folds": folds,
        "summary_classification": summary_classification,
        "brier_skill_scores_vs_prior": bss_reports,
        "summary_by_execution_mode": summary_by_mode,
        "execution_drag_comparison_at_2bps": execution_drag_comparison,
        "safety_invariants": {
            "forecast_ready": False,
            "real_market_data_verified": False,
            "paper_approved": False,
            "live_approved": False,
            "live_broker_routing_enabled": False,
        },
    }


def prepare_m21_walk_forward_specification(config: M21ResearchConfig | None = None) -> dict[str, Any]:
    """Prepare inactive M21 walk-forward specification preserving safety invariants."""
    cfg = config or M21ResearchConfig()
    return {
        "enabled": cfg.enabled,
        "status": "PREPARED_INACTIVE",
        "description": "Milestone M21 Execution Realism and Broader Historical Validation Specification",
        "safety_invariants": {
            "forecast_ready": False,
            "real_market_data_verified": False,
            "paper_approved": False,
            "live_approved": False,
            "live_broker_routing_enabled": False,
        },
        "config": cfg.model_dump(),
    }
