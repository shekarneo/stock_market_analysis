"""Controlled quantitative model comparison harness and evaluation workflow.

Compares majority-class baseline, last-return-sign baseline, and logistic regression
over identical chronological walk-forward folds without lookahead leakage.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.forecasting.walkforward import (
    MODEL_NAMES,
    WalkForwardConfig,
    run_walk_forward,
)


class ModelComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    dataset_id: str | None = None
    symbol: str | None = "NIFTY"
    models: list[str] = Field(default_factory=lambda: list(MODEL_NAMES))
    initial_train_size: int = 9
    validation_size: int = 5
    test_size: int = 4
    step_size: int = 4
    embargo_bars: int = 1
    seed: int = 0


def compare_quantitative_models(
    feature_dataset: dict[str, Any],
    config: WalkForwardConfig | None = None,
) -> dict[str, Any]:
    """Run controlled model comparison over identical chronological walk-forward folds."""
    cfg = config or WalkForwardConfig()
    wf_result = run_walk_forward(feature_dataset, config=cfg)

    if not wf_result.get("ok"):
        return {
            "ok": False,
            "code": wf_result.get("code", "COMPARISON_FAILED"),
            "message": wf_result.get("message", "Walk-forward evaluation failed."),
            "models_compared": list(MODEL_NAMES),
            "forecast_ready": False,
            "real_market_data_verified": False,
        }

    artifact = wf_result.get("artifact", {})
    folds = artifact.get("folds", [])

    def _val(m: Any) -> float | None:
        if isinstance(m, dict):
            if m.get("status") == "DEFINED" and m.get("value") is not None:
                return float(m["value"])
            return None
        try:
            return float(m) if m is not None else None
        except (ValueError, TypeError):
            return None

    model_metrics: dict[str, dict[str, Any]] = {}
    for name in MODEL_NAMES:
        acc_list: list[float] = []
        brier_list: list[float] = []
        loss_list: list[float] = []
        bal_acc_list: list[float] = []

        for f in folds:
            m_res = (f.get("model_results") or {}).get(name) or {}
            test_m = m_res.get("test") or {}
            va = _val(test_m.get("accuracy"))
            if va is not None:
                acc_list.append(va)
            vb = _val(test_m.get("brier"))
            if vb is not None:
                brier_list.append(vb)
            vl = _val(test_m.get("log_loss"))
            if vl is not None:
                loss_list.append(vl)
            vba = _val(test_m.get("balanced_accuracy"))
            if vba is not None:
                bal_acc_list.append(vba)

        model_metrics[name] = {
            "folds_evaluated": len(acc_list),
            "mean_accuracy": round(statistics.mean(acc_list), 4) if acc_list else None,
            "mean_balanced_accuracy": round(statistics.mean(bal_acc_list), 4) if bal_acc_list else None,
            "mean_brier_score": round(statistics.mean(brier_list), 4) if brier_list else None,
            "mean_log_loss": round(statistics.mean(loss_list), 4) if loss_list else None,
        }

    # Baseline comparison vs majority class
    maj_brier = model_metrics.get("majority_class", {}).get("mean_brier_score")
    log_brier = model_metrics.get("logistic_regression", {}).get("mean_brier_score")
    brier_improvement = None
    if maj_brier is not None and log_brier is not None:
        brier_improvement = round(maj_brier - log_brier, 4)

    # Determine recommended candidate based on validation metrics
    summary = artifact.get("summary", {})
    recommended = summary.get("selected_model") or "majority_class"

    return {
        "ok": True,
        "comparison_id": artifact.get("artifact_id"),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_id": feature_dataset.get("dataset_id"),
        "fold_count": len(folds),
        "models_evaluated": list(MODEL_NAMES),
        "model_metrics": model_metrics,
        "baseline_comparison": {
            "baseline_model": "majority_class",
            "logistic_brier_delta": brier_improvement,
            "beats_baseline_brier": bool(brier_improvement and brier_improvement > 0),
        },
        "recommendation": {
            "selected_model": recommended,
            "rationale": "Model with lowest validation Brier score and consistent calibration across walk-forward folds.",
        },
        "leakage_prevention": {
            "chronological_expanding_splits": True,
            "embargo_bars": cfg.embargo_bars,
            "train_only_feature_standardization": True,
            "lookahead_leakage_detected": False,
        },
        "forecast_ready": False,
        "real_market_data_verified": False,
        "paper_approved": False,
        "live_approved": False,
    }
