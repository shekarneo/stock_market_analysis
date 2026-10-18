"""Milestone M32: Observability, Feature Drift Monitoring & Kill Switch Tripping.

Prepared strictly for research and financial loss-prevention verification.
Live trading, paper trading, and forecast approval are strictly disabled.
All safety invariants remain hardcoded to False.

Core Capabilities:
1. Population Stability Index (PSI):
   - Quantile-based binning of reference feature distributions.
   - Robust Laplace smoothing (epsilon) to avoid division by zero.
   - Classification:
       PSI < 0.10: STABLE
       0.10 <= PSI < 0.25: MODERATE_DRIFT (Warning)
       PSI >= 0.25: CRITICAL_DRIFT (Severe Distribution Shift)
2. 2-Sample Kolmogorov-Smirnov (KS) Statistic & p-value:
   - Non-parametric test detecting shifts in continuous empirical CDFs.
3. Wasserstein Distance:
   - Quantifies the physical earth-mover displacement between feature distributions.
4. Automated Fail-Safe Circuit Breaker:
   - Evaluates system-level drift across multiple quantitative market features.
   - Automatically trips the operational kill switch (`OpsState.kill_switch = True`)
     and logs an immutable risk audit event when critical drift is confirmed.
5. Historical NIFTY Dev vs Holdout Drift Audit:
   - Computes drift across 1-year NIFTY dataset comparing Development Folds 1–14
     against Untouched Holdout Folds 15–19.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
import math
from pathlib import Path
from typing import Any, Sequence
import numpy as np
from scipy import stats
from sqlalchemy.orm import Session

from app.risk.ledger import set_kill_switch
from app.settings import REPO_ROOT

log = logging.getLogger("imm.monitoring.drift")

# Default Statistical Thresholds
DEFAULT_WARNING_PSI_THRESHOLD = 0.10
DEFAULT_CRITICAL_PSI_THRESHOLD = 0.25


@dataclass
class FeatureDriftResult:
    feature_name: str
    psi: float
    ks_statistic: float
    ks_pvalue: float
    wasserstein_distance: float
    status: str  # "STABLE", "MODERATE_DRIFT", "CRITICAL_DRIFT"
    reference_mean: float
    target_mean: float
    reference_std: float
    target_std: float
    sample_size_ref: int
    sample_size_target: int
    bin_breakdown: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SystemDriftReport:
    evaluated_at: str
    overall_status: str  # "STABLE", "MODERATE_DRIFT", "CRITICAL_DRIFT"
    max_psi: float
    warning_psi_threshold: float
    critical_psi_threshold: float
    critical_features: list[str]
    warning_features: list[str]
    stable_features: list[str]
    feature_metrics: dict[str, FeatureDriftResult]
    kill_switch_tripped: bool
    kill_switch_reason: str | None
    forecast_ready: bool = False
    real_market_data_verified: bool = False
    paper_approved: bool = False
    live_approved: bool = False
    live_broker_routing_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["feature_metrics"] = {k: v.to_dict() for k, v in self.feature_metrics.items()}
        return data


def _clean_numeric_array(arr: Sequence[float]) -> np.ndarray:
    """Filter out non-finite (NaN, inf) elements."""
    cleaned = np.array([x for x in arr if x is not None and not math.isnan(x) and not math.isinf(x)], dtype=float)
    return cleaned


def calculate_psi(
    reference: Sequence[float],
    target: Sequence[float],
    num_bins: int = 10,
    epsilon: float = 1e-4,
) -> tuple[float, list[dict[str, Any]]]:
    """Calculate the Population Stability Index (PSI) between reference and target samples.
    
    Returns:
        tuple[float, list[dict[str, Any]]]: (total_psi, list of per-bin statistics)
    """
    ref_clean = _clean_numeric_array(reference)
    tgt_clean = _clean_numeric_array(target)

    if len(ref_clean) < 5 or len(tgt_clean) < 5:
        # Insufficient data to reliably construct quantiles
        return 0.0, []

    # Calculate quantile bin edges from reference distribution
    percentiles = np.linspace(0, 100, num_bins + 1)
    bin_edges = np.percentile(ref_clean, percentiles)
    unique_edges = np.unique(bin_edges)

    if len(unique_edges) < 2:
        # Constant feature; no variance
        return 0.0, []

    # Extend endpoints to catch edge cases
    unique_edges[0] = -np.inf
    unique_edges[-1] = np.inf

    # Count occurrences in each bin
    ref_counts, _ = np.histogram(ref_clean, bins=unique_edges)
    tgt_counts, _ = np.histogram(tgt_clean, bins=unique_edges)

    n_bins = len(ref_counts)
    total_ref = len(ref_clean)
    total_tgt = len(tgt_clean)

    # Laplace smoothing to prevent division by zero / log(0)
    ref_probs = (ref_counts + epsilon) / (total_ref + n_bins * epsilon)
    tgt_probs = (tgt_counts + epsilon) / (total_tgt + n_bins * epsilon)

    bin_breakdown: list[dict[str, Any]] = []
    total_psi = 0.0

    for i in range(n_bins):
        lower = float(unique_edges[i])
        upper = float(unique_edges[i + 1])
        p_ref = float(ref_probs[i])
        q_tgt = float(tgt_probs[i])

        bin_psi = (q_tgt - p_ref) * math.log(q_tgt / p_ref)
        total_psi += bin_psi

        bin_breakdown.append({
            "bin_index": i,
            "lower_bound": lower if not math.isinf(lower) else None,
            "upper_bound": upper if not math.isinf(upper) else None,
            "ref_count": int(ref_counts[i]),
            "tgt_count": int(tgt_counts[i]),
            "ref_proportion": p_ref,
            "tgt_proportion": q_tgt,
            "bin_psi": bin_psi,
        })

    return float(max(0.0, total_psi)), bin_breakdown


def calculate_ks(reference: Sequence[float], target: Sequence[float]) -> tuple[float, float]:
    """Calculate 2-sample Kolmogorov-Smirnov statistic and p-value."""
    ref_clean = _clean_numeric_array(reference)
    tgt_clean = _clean_numeric_array(target)

    if len(ref_clean) < 2 or len(tgt_clean) < 2:
        return 0.0, 1.0

    res = stats.ks_2samp(ref_clean, tgt_clean)
    return float(res.statistic), float(res.pvalue)


def calculate_wasserstein(reference: Sequence[float], target: Sequence[float]) -> float:
    """Calculate Wasserstein (Earth Mover's) Distance between reference and target."""
    ref_clean = _clean_numeric_array(reference)
    tgt_clean = _clean_numeric_array(target)

    if len(ref_clean) < 1 or len(tgt_clean) < 1:
        return 0.0

    return float(stats.wasserstein_distance(ref_clean, tgt_clean))


def calculate_feature_drift(
    feature_name: str,
    reference: Sequence[float],
    target: Sequence[float],
    *,
    num_bins: int = 10,
    warning_psi_threshold: float = DEFAULT_WARNING_PSI_THRESHOLD,
    critical_psi_threshold: float = DEFAULT_CRITICAL_PSI_THRESHOLD,
) -> FeatureDriftResult:
    """Evaluate statistical drift metrics for a single feature."""
    ref_clean = _clean_numeric_array(reference)
    tgt_clean = _clean_numeric_array(target)

    psi, bin_breakdown = calculate_psi(ref_clean, tgt_clean, num_bins=num_bins)
    ks_stat, ks_pval = calculate_ks(ref_clean, tgt_clean)
    wass_dist = calculate_wasserstein(ref_clean, tgt_clean)

    if psi >= critical_psi_threshold:
        status = "CRITICAL_DRIFT"
    elif psi >= warning_psi_threshold:
        status = "MODERATE_DRIFT"
    else:
        status = "STABLE"

    ref_mean = float(np.mean(ref_clean)) if len(ref_clean) > 0 else 0.0
    tgt_mean = float(np.mean(tgt_clean)) if len(tgt_clean) > 0 else 0.0
    ref_std = float(np.std(ref_clean)) if len(ref_clean) > 0 else 0.0
    tgt_std = float(np.std(tgt_clean)) if len(tgt_clean) > 0 else 0.0

    return FeatureDriftResult(
        feature_name=feature_name,
        psi=psi,
        ks_statistic=ks_stat,
        ks_pvalue=ks_pval,
        wasserstein_distance=wass_dist,
        status=status,
        reference_mean=ref_mean,
        target_mean=tgt_mean,
        reference_std=ref_std,
        target_std=tgt_std,
        sample_size_ref=len(ref_clean),
        sample_size_target=len(tgt_clean),
        bin_breakdown=bin_breakdown,
    )


def evaluate_feature_matrix_drift(
    reference_matrix: dict[str, Sequence[float]],
    target_matrix: dict[str, Sequence[float]],
    *,
    warning_psi_threshold: float = DEFAULT_WARNING_PSI_THRESHOLD,
    critical_psi_threshold: float = DEFAULT_CRITICAL_PSI_THRESHOLD,
    num_bins: int = 10,
) -> SystemDriftReport:
    """Evaluate statistical drift across an entire matrix of quantitative features."""
    now_iso = datetime.now(timezone.utc).isoformat()
    feature_metrics: dict[str, FeatureDriftResult] = {}
    critical_features: list[str] = []
    warning_features: list[str] = []
    stable_features: list[str] = []

    common_features = [f for f in reference_matrix.keys() if f in target_matrix]
    if not common_features:
        return SystemDriftReport(
            evaluated_at=now_iso,
            overall_status="STABLE",
            max_psi=0.0,
            warning_psi_threshold=warning_psi_threshold,
            critical_psi_threshold=critical_psi_threshold,
            critical_features=[],
            warning_features=[],
            stable_features=[],
            feature_metrics={},
            kill_switch_tripped=False,
            kill_switch_reason=None,
        )

    for feat in common_features:
        res = calculate_feature_drift(
            feat,
            reference_matrix[feat],
            target_matrix[feat],
            num_bins=num_bins,
            warning_psi_threshold=warning_psi_threshold,
            critical_psi_threshold=critical_psi_threshold,
        )
        feature_metrics[feat] = res

        if res.status == "CRITICAL_DRIFT":
            critical_features.append(feat)
        elif res.status == "MODERATE_DRIFT":
            warning_features.append(feat)
        else:
            stable_features.append(feat)

    max_psi = max([m.psi for m in feature_metrics.values()]) if feature_metrics else 0.0

    if critical_features:
        overall_status = "CRITICAL_DRIFT"
    elif warning_features:
        overall_status = "MODERATE_DRIFT"
    else:
        overall_status = "STABLE"

    return SystemDriftReport(
        evaluated_at=now_iso,
        overall_status=overall_status,
        max_psi=max_psi,
        warning_psi_threshold=warning_psi_threshold,
        critical_psi_threshold=critical_psi_threshold,
        critical_features=critical_features,
        warning_features=warning_features,
        stable_features=stable_features,
        feature_metrics=feature_metrics,
        kill_switch_tripped=False,
        kill_switch_reason=None,
    )


def evaluate_and_enforce_drift_circuit_breaker(
    session: Session,
    reference_matrix: dict[str, Sequence[float]],
    target_matrix: dict[str, Sequence[float]],
    *,
    actor: str = "system.drift_monitor",
    warning_psi_threshold: float = DEFAULT_WARNING_PSI_THRESHOLD,
    critical_psi_threshold: float = DEFAULT_CRITICAL_PSI_THRESHOLD,
    commit: bool = True,
) -> SystemDriftReport:
    """Evaluate drift and immediately trip the operational kill switch if critical drift is detected.
    
    When critical drift is confirmed:
    - Calls set_kill_switch(session, True, actor=actor, reason=..., commit=commit)
    - Records immutable RiskAuditLog event
    - Sets report.kill_switch_tripped = True
    - Prevents any simulated or future paper orders from passing risk gates.
    """
    report = evaluate_feature_matrix_drift(
        reference_matrix,
        target_matrix,
        warning_psi_threshold=warning_psi_threshold,
        critical_psi_threshold=critical_psi_threshold,
    )

    if report.overall_status == "CRITICAL_DRIFT":
        reason = (
            f"CRITICAL_FEATURE_DRIFT: Max PSI {report.max_psi:.4f} >= threshold {critical_psi_threshold:.2f} "
            f"detected in features: {', '.join(report.critical_features)}"
        )
        log.error("Circuit breaker triggered: %s", reason)
        set_kill_switch(session, enabled=True, actor=actor, reason=reason, commit=commit)
        report.kill_switch_tripped = True
        report.kill_switch_reason = reason
    elif report.overall_status == "MODERATE_DRIFT":
        log.warning(
            "Moderate feature drift observed (Max PSI %.4f). Features: %s",
            report.max_psi,
            ", ".join(report.warning_features),
        )

    return report


def extract_nifty_drift_features(candles: list[dict | list]) -> dict[str, list[float]]:
    """Extract causal statistical features (Returns, ATR, ADX, Volume) from candles.
    
    Candle format can be dict or [timestamp, open, high, low, close, volume, oi].
    """
    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    volumes: list[float] = []

    for c in candles:
        if isinstance(c, dict):
            closes.append(float(c.get("close", 0.0)))
            highs.append(float(c.get("high", 0.0)))
            lows.append(float(c.get("low", 0.0)))
            volumes.append(float(c.get("volume", 0.0)))
        elif isinstance(c, (list, tuple)) and len(c) >= 6:
            highs.append(float(c[2]))
            lows.append(float(c[3]))
            closes.append(float(c[4]))
            volumes.append(float(c[5]))

    n = len(closes)
    if n < 15:
        return {"returns": [], "atr": [], "adx": [], "volume": volumes}

    # 1. 1-bar Log Returns
    returns: list[float] = [0.0]
    for i in range(1, n):
        prev = closes[i - 1]
        curr = closes[i]
        ret = math.log(curr / prev) if prev > 0 and curr > 0 else 0.0
        returns.append(ret)

    # 2. 14-period True Range and Wilder ATR
    tr_list: list[float] = [highs[0] - lows[0]]
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        tr_list.append(tr)

    atr_list: list[float] = []
    # Seed ATR
    atr_curr = float(np.mean(tr_list[:14]))
    for _ in range(14):
        atr_list.append(atr_curr)
    for i in range(14, n):
        atr_curr = (atr_curr * 13.0 + tr_list[i]) / 14.0
        atr_list.append(atr_curr)

    # 3. 14-period Wilder Directional Movement (+DM, -DM) and ADX
    plus_dm: list[float] = [0.0]
    minus_dm: list[float] = [0.0]
    for i in range(1, n):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        pdm = up_move if (up_move > down_move and up_move > 0) else 0.0
        mdm = down_move if (down_move > up_move and down_move > 0) else 0.0
        plus_dm.append(pdm)
        minus_dm.append(mdm)

    smooth_pdm = float(np.mean(plus_dm[:14]))
    smooth_mdm = float(np.mean(minus_dm[:14]))
    dx_list: list[float] = []

    for i in range(14):
        dx_list.append(20.0)

    for i in range(14, n):
        smooth_pdm = (smooth_pdm * 13.0 + plus_dm[i]) / 14.0
        smooth_mdm = (smooth_mdm * 13.0 + minus_dm[i]) / 14.0
        current_atr = atr_list[i] if atr_list[i] > 1e-6 else 1e-6

        pdi = 100.0 * (smooth_pdm / current_atr)
        mdi = 100.0 * (smooth_mdm / current_atr)
        di_sum = pdi + mdi
        dx = 100.0 * abs(pdi - mdi) / di_sum if di_sum > 1e-6 else 0.0
        dx_list.append(dx)

    adx_list: list[float] = []
    adx_curr = float(np.mean(dx_list[:28])) if n >= 28 else 20.0
    for _ in range(min(n, 28)):
        adx_list.append(adx_curr)
    for i in range(28, n):
        adx_curr = (adx_curr * 13.0 + dx_list[i]) / 14.0
        adx_list.append(adx_curr)

    return {
        "returns": returns,
        "atr": atr_list,
        "adx": adx_list,
        "volume": volumes,
    }


def run_nifty_benchmark_drift_audit(dataset_path: Path | str | None = None) -> SystemDriftReport:
    """Run an empirical feature drift audit on the 1-year NIFTY dataset.
    
    Compares:
    - Reference: Development Window (Folds 1–14, bars 0..3500)
    - Target: Holdout Window (Folds 15–19, bars 3500..4750)
    
    Persists results to var/datasets/m32_drift_benchmark_results.json.
    """
    if dataset_path is None:
        target_file = REPO_ROOT / "var/datasets/derived_nifty_15m_m23_bc7d31bceebf13a3.json"
    else:
        target_file = Path(dataset_path)

    if not target_file.exists():
        raise FileNotFoundError(f"NIFTY benchmark dataset not found at {target_file}")

    with open(target_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    candles = data["candles"] if "candles" in data else data
    total_candles = len(candles)

    # Partition into Dev (0..3500) and Holdout (3500..4750)
    dev_candles = candles[:3500]
    holdout_candles = candles[3500:4750] if total_candles >= 4750 else candles[3500:]

    ref_features = extract_nifty_drift_features(dev_candles)
    tgt_features = extract_nifty_drift_features(holdout_candles)

    report = evaluate_feature_matrix_drift(ref_features, tgt_features)

    # Persist artifact
    out_dir = REPO_ROOT / "var/datasets"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "m32_drift_benchmark_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2)

    log.info("Persisted M32 drift benchmark audit to %s", out_file)
    return report
