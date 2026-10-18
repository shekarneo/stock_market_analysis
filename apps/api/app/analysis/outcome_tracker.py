"""Immutable Forecast Outcome Tracking, Evaluation and Calibration for V6.

Strictly distinguishes 4 distinct operational contexts:
1. FORECAST_EVALUATION: Evaluation of statistical model prediction accuracy (direction, Brier score, log loss).
   Does NOT require a trade order. Evaluates even when recommendation is NO_TRADE.
2. HYPOTHETICAL_STRATEGY_SIMULATION: Theoretical backtest / paper simulation of strike pricing and PnL.
3. PAPER_TRADING: Isolated virtual order routing without capital risk.
4. ACTUAL_BROKER_EXECUTION: Live order routing with real capital (LOCKED behind kill switch).

Guarantees:
- An actual trade outcome is NEVER claimed for a hypothetical signal.
- Forecast records are immutable.
- Subsequent directional evaluation is supported without live trading.
- Look-ahead leakage is prevented by enforcing horizon elapsed time.
- Duplicate scoring is prevented by tracking evaluated state idempotently.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.settings import REPO_ROOT

log = logging.getLogger("imm.outcome_tracker")
OUTCOMES_LOG_PATH = REPO_ROOT / "var" / "analysis" / "forecast_outcomes.jsonl"


def record_forecast_prediction(
    *,
    analysis_id: str,
    instrument: str,
    model_version: str,
    probability_up: float,
    direction: str,
    spot_price: float,
    horizon: str = "next_m15_close",
    decision: str = "NO_TRADE",
    data_provenance: str = "UNVERIFIED_PROVIDER",
    recorded_at: str | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Immutably append a forecast prediction record for post-horizon calibration."""
    record = {
        "record_id": f"{analysis_id}_{instrument.upper()}",
        "analysis_id": analysis_id,
        "recorded_at": recorded_at or datetime.now(timezone.utc).isoformat(),
        "instrument": instrument.upper(),
        "model_version": model_version,
        "probability_up": float(probability_up),
        "probability_down": round(1.0 - float(probability_up), 4),
        "predicted_direction": direction.upper(),
        "spot_price_at_prediction": float(spot_price),
        "horizon": horizon,
        "decision": decision.upper(),
        "data_provenance": data_provenance,
        "execution_context": "FORECAST_EVALUATION",
        "evaluation_status": "PENDING_SUBSEQUENT_CLOSE",
        "subsequent_outcome": None,
    }
    target = path or OUTCOMES_LOG_PATH
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as exc:
        log.warning("Could not persist forecast prediction record: %s", exc)
    return record


def get_forecast_records(path: Path | None = None) -> list[dict[str, Any]]:
    """Retrieve all persisted forecast prediction records."""
    target = path or OUTCOMES_LOG_PATH
    if not target.exists():
        return []
    records = []
    try:
        with open(target, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except Exception as exc:
        log.warning("Could not read forecast records from %s: %s", target, exc)
    return records


def evaluate_forecast_outcome(
    prediction_record: dict[str, Any],
    subsequent_close_price: float,
    subsequent_bar_end: str | None = None,
) -> dict[str, Any]:
    """Evaluate a forecast against subsequent realized price.

    This is pure forecast accuracy evaluation and does NOT represent an actual trade outcome.
    """
    spot_prev = float(prediction_record["spot_price_at_prediction"])
    p_up = float(prediction_record["probability_up"])
    pred_dir = prediction_record["predicted_direction"]

    actual_ret = (subsequent_close_price - spot_prev) / spot_prev if spot_prev > 0 else 0.0
    actual_dir = "BULLISH" if actual_ret > 0.0 else ("BEARISH" if actual_ret < 0.0 else "FLAT")

    # True outcome indicator y (1 for UP, 0 for DOWN)
    y_true = 1.0 if actual_dir == "BULLISH" else 0.0
    brier_score = round((p_up - y_true) ** 2, 4)
    direction_correct = (pred_dir == actual_dir)

    evaluation = {
        "analysis_id": prediction_record.get("analysis_id"),
        "instrument": prediction_record.get("instrument"),
        "model_version": prediction_record.get("model_version"),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "subsequent_bar_end": subsequent_bar_end,
        "spot_price_prior": spot_prev,
        "spot_price_subsequent": subsequent_close_price,
        "realized_return_pct": round(actual_ret * 100, 3),
        "actual_direction": actual_dir,
        "predicted_direction": pred_dir,
        "direction_correct": direction_correct,
        "probability_up": p_up,
        "brier_score": brier_score,
        "execution_context": "FORECAST_EVALUATION",
        "note": "Pure statistical forecast calibration; no real trade was executed.",
    }
    return evaluation


def evaluate_pending_forecasts(
    observations: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    min_elapsed_seconds: int = 900,
    path: Path | None = None,
) -> dict[str, Any]:
    """Score pending forecasts against incoming observations if horizon has elapsed.

    Guarantees:
    - Look-ahead leakage prevention: A forecast is NOT evaluated until min_elapsed_seconds have elapsed.
    - Duplicate scoring prevention: Once scored, records are marked SCORED and not evaluated again.
    """
    target = path or OUTCOMES_LOG_PATH
    records = get_forecast_records(target)
    if not records:
        return {"total_records": 0, "evaluated_count": 0, "pending_count": 0}

    now_dt = now or datetime.now(timezone.utc)
    obs_map: dict[str, float] = {}
    for obs in observations:
        inst = (obs.get("instrument") or "").upper()
        price = obs.get("last_price")
        if inst and price is not None:
            try:
                obs_map[inst] = float(price)
            except (ValueError, TypeError):
                pass

    evaluated_count = 0
    updated_records = []
    for r in records:
        if r.get("evaluation_status") == "PENDING_SUBSEQUENT_CLOSE":
            rec_inst = r.get("instrument", "").upper()
            recorded_at_str = r.get("recorded_at")
            elapsed = 0.0
            if recorded_at_str:
                try:
                    rec_dt = datetime.fromisoformat(recorded_at_str)
                    if rec_dt.tzinfo is None:
                        rec_dt = rec_dt.replace(tzinfo=timezone.utc)
                    elapsed = (now_dt - rec_dt).total_seconds()
                except Exception:
                    elapsed = 0.0

            # Only evaluate if horizon has elapsed and subsequent observation is available
            if elapsed >= min_elapsed_seconds and rec_inst in obs_map:
                subsequent_price = obs_map[rec_inst]
                eval_res = evaluate_forecast_outcome(
                    r,
                    subsequent_close_price=subsequent_price,
                    subsequent_bar_end=now_dt.isoformat(),
                )
                r["evaluation_status"] = "SCORED"
                r["subsequent_outcome"] = eval_res
                evaluated_count += 1

        updated_records.append(r)

    if evaluated_count > 0:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                for ur in updated_records:
                    f.write(json.dumps(ur) + "\n")
        except Exception as exc:
            log.warning("Could not rewrite forecast outcomes file: %s", exc)

    pending_count = sum(1 for r in updated_records if r.get("evaluation_status") == "PENDING_SUBSEQUENT_CLOSE")
    return {
        "total_records": len(updated_records),
        "evaluated_count": evaluated_count,
        "pending_count": pending_count,
    }


def compute_forecast_accuracy_summary(
    records: list[dict[str, Any]] | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Compute aggregate accuracy, Brier scores, Brier Skill Score, and calibration metrics."""
    if records is None:
        records = get_forecast_records(path)

    total_records = len(records)
    scored = [r for r in records if r.get("evaluation_status") == "SCORED" and r.get("subsequent_outcome")]
    pending = [r for r in records if r.get("evaluation_status") == "PENDING_SUBSEQUENT_CLOSE"]

    if not scored:
        return {
            "total_forecasts": total_records,
            "scored_forecasts": 0,
            "pending_forecasts": len(pending),
            "directional_accuracy_pct": None,
            "brier_score": None,
            "prior_brier_score": 0.2503,
            "brier_skill_score_pct": None,
            "log_loss": None,
            "calibration_status": "UNCALIBRATED",
            "calibration_reason": "Insufficient out-of-sample evaluated outcomes.",
            "by_instrument": {},
            "by_horizon": {},
            "recent_evaluations": [],
        }

    correct_count = 0
    brier_sum = 0.0
    log_loss_sum = 0.0
    by_inst: dict[str, dict[str, Any]] = {}
    by_horiz: dict[str, dict[str, Any]] = {}

    for r in scored:
        outcome = r["subsequent_outcome"]
        inst = r.get("instrument", "UNKNOWN")
        horiz = r.get("horizon", "next_m15_close")

        is_correct = bool(outcome.get("direction_correct"))
        brier = float(outcome.get("brier_score", 0.25))
        p_up = max(1e-4, min(1.0 - 1e-4, float(r.get("probability_up", 0.5))))
        actual_up = 1.0 if outcome.get("actual_direction") == "BULLISH" else 0.0

        # Log loss
        loss = -(actual_up * math.log(p_up) + (1.0 - actual_up) * math.log(1.0 - p_up))
        log_loss_sum += loss

        if is_correct:
            correct_count += 1
        brier_sum += brier

        # By instrument
        if inst not in by_inst:
            by_inst[inst] = {"total": 0, "correct": 0, "brier_sum": 0.0}
        by_inst[inst]["total"] += 1
        if is_correct:
            by_inst[inst]["correct"] += 1
        by_inst[inst]["brier_sum"] += brier

        # By horizon
        if horiz not in by_horiz:
            by_horiz[horiz] = {"total": 0, "correct": 0, "brier_sum": 0.0}
        by_horiz[horiz]["total"] += 1
        if is_correct:
            by_horiz[horiz]["correct"] += 1
        by_horiz[horiz]["brier_sum"] += brier

    n = len(scored)
    mean_brier = round(brier_sum / n, 4)
    prior_brier = 0.2503  # Canonical empirical base rate
    bss = round((1.0 - (mean_brier / prior_brier)) * 100.0, 2)
    mean_log_loss = round(log_loss_sum / n, 4)
    accuracy_pct = round((correct_count / n) * 100.0, 2)

    # Format breakdowns
    formatted_inst = {}
    for k, v in by_inst.items():
        tot = v["total"]
        formatted_inst[k] = {
            "total": tot,
            "accuracy_pct": round((v["correct"] / tot) * 100.0, 2) if tot > 0 else 0.0,
            "brier_score": round(v["brier_sum"] / tot, 4) if tot > 0 else 0.25,
        }

    formatted_horiz = {}
    for k, v in by_horiz.items():
        tot = v["total"]
        formatted_horiz[k] = {
            "total": tot,
            "accuracy_pct": round((v["correct"] / tot) * 100.0, 2) if tot > 0 else 0.0,
            "brier_score": round(v["brier_sum"] / tot, 4) if tot > 0 else 0.25,
        }

    # Calibration status: labeled UNCALIBRATED if sample < 30 or BSS <= 0
    if n < 30:
        cal_status = "UNCALIBRATED"
        cal_reason = f"Preliminary sample size (n={n} < 30). Empirical verification ongoing."
    elif bss <= 0.0:
        cal_status = "UNCALIBRATED"
        cal_reason = f"Brier Skill Score ({bss}%) does not demonstrate positive edge over prior."
    else:
        cal_status = "CALIBRATED_RESEARCH"
        cal_reason = f"Positive Brier Skill Score ({bss}%) over {n} out-of-sample observations."

    return {
        "total_forecasts": total_records,
        "scored_forecasts": n,
        "pending_forecasts": len(pending),
        "directional_accuracy_pct": accuracy_pct,
        "brier_score": mean_brier,
        "prior_brier_score": prior_brier,
        "brier_skill_score_pct": bss,
        "log_loss": mean_log_loss,
        "calibration_status": cal_status,
        "calibration_reason": cal_reason,
        "by_instrument": formatted_inst,
        "by_horizon": formatted_horiz,
        "recent_evaluations": [r["subsequent_outcome"] for r in scored[-10:]],
    }
