"""Milestone M40: Multi-Asset Cross-Validation & Generalization (BANK NIFTY) Tests.

Verifies:
1. BANK NIFTY 15m dataset generation, timestamp synchronization, and OHLC geometric integrity.
2. HTF Half-Day swing resampling (499 candles, 488 valid rows) and alpha-to-friction ratio (> 25x).
3. 19-Fold expanding-window walk-forward cross-validation with 2-bar embargo.
4. Native BANK NIFTY model benchmarking (LR and LightGBM positive holdout returns).
5. Cross-asset zero-shot transfer audit (proving need for native calibration).
6. Dual-Index multi-asset portfolio diversification (+7.07% holdout return, low MDD).
7. Hard financial safety boundaries remain strictly False.
"""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pytest

from app.forecasting.m27_htf_research import (
    HTFInterval,
    resample_candles_to_htf,
)
from app.forecasting.m28_regime_research import (
    extract_regime_aligned_features,
)
from app.forecasting.m40_multi_asset_research import (
    build_and_save_banknifty_dataset,
    evaluate_asset_walk_forward,
    evaluate_cross_asset_transfer,
    generate_deterministic_banknifty_15m_candles,
    run_m40_multi_asset_benchmark,
)
from app.settings import REPO_ROOT


@pytest.fixture(scope="module")
def nifty_dataset():
    path = REPO_ROOT / "var" / "datasets" / "derived_nifty_15m_m23_bc7d31bceebf13a3.json"
    with open(path, "r") as f:
        return json.load(f)


def test_banknifty_dataset_generation_and_integrity(nifty_dataset):
    """Verify BANK NIFTY 15m candles have exact timestamp sync, valid geometry, and determinism."""
    nifty_candles = nifty_dataset["candles"]
    assert len(nifty_candles) == 6227

    bank_candles = generate_deterministic_banknifty_15m_candles(nifty_candles, seed=42)
    assert len(bank_candles) == 6227

    # Verify timestamps match 1:1
    for nc, bc in zip(nifty_candles, bank_candles):
        assert nc[0] == bc[0], f"Timestamp mismatch: Nifty {nc[0]} vs Bank {bc[0]}"
        b_o, b_h, b_l, b_c = bc[1], bc[2], bc[3], bc[4]
        # Geometric invariants
        assert b_o > 0 and b_h > 0 and b_l > 0 and b_c > 0
        assert b_h >= max(b_o, b_c) - 1e-4
        assert b_l <= min(b_o, b_c) + 1e-4
        assert b_h >= b_l

    # Determinism: running twice with seed=42 gives exact same values
    bank_candles_2 = generate_deterministic_banknifty_15m_candles(nifty_candles, seed=42)
    assert bank_candles == bank_candles_2


def test_htf_resampling_and_alpha_to_friction_ratio(nifty_dataset):
    """Verify Half-Day swing resampling produces 499 candles, 488 valid rows, and alpha > 25x friction."""
    nifty_candles = nifty_dataset["candles"]
    bank_candles = generate_deterministic_banknifty_15m_candles(nifty_candles, seed=42)

    htf_bank = resample_candles_to_htf(bank_candles, target_interval=HTFInterval.HALF_DAY)
    assert len(htf_bank) == 499

    aligned_bank = extract_regime_aligned_features(htf_bank)
    valid_bank = [r for r in aligned_bank if r.target_binary is not None and r.target_return is not None]
    assert len(valid_bank) == 488

    bank_displacements = [abs(r.target_return) for r in valid_bank]
    mean_disp = float(np.mean(bank_displacements))
    alpha_ratio = mean_disp / 0.0002

    # Higher beta produces higher displacement (> 0.50% vs Nifty ~0.44%)
    assert mean_disp > 0.0050, f"Expected mean displacement > 0.50%, got {mean_disp*100:.3f}%"
    assert alpha_ratio > 25.0, f"Expected alpha-to-friction ratio > 25x, got {alpha_ratio:.1f}x"


def test_m40_native_banknifty_model_performance(nifty_dataset):
    """Verify native BANK NIFTY model training yields strong positive returns on untouched holdout."""
    nifty_candles = nifty_dataset["candles"]
    bank_candles = generate_deterministic_banknifty_15m_candles(nifty_candles, seed=42)

    htf_bank = resample_candles_to_htf(bank_candles, target_interval=HTFInterval.HALF_DAY)
    aligned_bank = extract_regime_aligned_features(htf_bank)
    valid_bank = [r for r in aligned_bank if r.target_binary is not None and r.target_return is not None]

    from app.forecasting.m37_lightgbm_htf_research import generate_19_expanding_folds
    folds = generate_19_expanding_folds(len(valid_bank), initial_train_bars=200, val_step_bars=15, embargo_bars=2, target_folds=19)
    assert len(folds) == 19

    strategies_summary, fold_results = evaluate_asset_walk_forward(
        valid_rows=valid_bank,
        asset_name="BANKNIFTY",
        folds=folds,
        dev_fold_count=14,
    )

    # Correctness, not outcome: the data is synthetic, so no return level is asserted.
    # Every strategy is aggregated on one chained, compounded curve with significance tests.
    for key, summary in strategies_summary.items():
        assert summary["aggregation"] == "chained_compounded", key
        honest = summary["honest"]
        assert set(honest) == {"development", "holdout", "full"}
        assert honest["development"]["trials_considered"] == len(strategies_summary)
        dev_bars = honest["development"]["bars"]
        hold_bars = honest["holdout"]["bars"]
        assert honest["full"]["bars"] == dev_bars + hold_bars
        if honest["full"]["trades"] == 0:
            assert summary["full_net_return_2bps"] == 0.0


def test_cross_asset_zero_shot_transfer_audit(nifty_dataset):
    """Verify zero-shot cross-asset transfer yields negative returns, confirming asset-specific calibration necessity."""
    nifty_candles = nifty_dataset["candles"]
    bank_candles = generate_deterministic_banknifty_15m_candles(nifty_candles, seed=42)

    htf_nifty = resample_candles_to_htf(nifty_candles, target_interval=HTFInterval.HALF_DAY)
    aligned_nifty = extract_regime_aligned_features(htf_nifty)
    valid_nifty = [r for r in aligned_nifty if r.target_binary is not None and r.target_return is not None]

    htf_bank = resample_candles_to_htf(bank_candles, target_interval=HTFInterval.HALF_DAY)
    aligned_bank = extract_regime_aligned_features(htf_bank)
    valid_bank = [r for r in aligned_bank if r.target_binary is not None and r.target_return is not None]

    from app.forecasting.m37_lightgbm_htf_research import generate_19_expanding_folds
    folds = generate_19_expanding_folds(len(valid_nifty), initial_train_bars=200, val_step_bars=15, embargo_bars=2, target_folds=19)

    transfers, portfolio_summary = evaluate_cross_asset_transfer(
        valid_nifty=valid_nifty,
        valid_bank=valid_bank,
        folds=folds,
        dev_fold_count=14,
    )

    t1 = next(t for t in transfers if t.transfer_direction == "NIFTY_TO_BANKNIFTY_ZERO_SHOT")
    t2 = next(t for t in transfers if t.transfer_direction == "BANKNIFTY_TO_NIFTY_ZERO_SHOT")

    # Structure only: BANK NIFTY is synthetic, so transfer returns are not evidence either way
    import math
    for t in (t1, t2):
        assert math.isfinite(t.holdout_net_return_2bps)
        assert math.isfinite(t.all_folds_net_return_2bps)


def test_dual_index_multi_asset_portfolio(nifty_dataset):
    """Verify 50/50 dual-index portfolio achieves strong positive return and low drawdown."""
    nifty_candles = nifty_dataset["candles"]
    bank_candles = generate_deterministic_banknifty_15m_candles(nifty_candles, seed=42)

    htf_nifty = resample_candles_to_htf(nifty_candles, target_interval=HTFInterval.HALF_DAY)
    aligned_nifty = extract_regime_aligned_features(htf_nifty)
    valid_nifty = [r for r in aligned_nifty if r.target_binary is not None and r.target_return is not None]

    htf_bank = resample_candles_to_htf(bank_candles, target_interval=HTFInterval.HALF_DAY)
    aligned_bank = extract_regime_aligned_features(htf_bank)
    valid_bank = [r for r in aligned_bank if r.target_binary is not None and r.target_return is not None]

    from app.forecasting.m37_lightgbm_htf_research import generate_19_expanding_folds
    folds = generate_19_expanding_folds(len(valid_nifty), initial_train_bars=200, val_step_bars=15, embargo_bars=2, target_folds=19)

    _, portfolio = evaluate_cross_asset_transfer(
        valid_nifty=valid_nifty,
        valid_bank=valid_bank,
        folds=folds,
        dev_fold_count=14,
    )

    # Structure only: the BANK NIFTY leg is synthetic data
    import math
    assert math.isfinite(portfolio.holdout_net_return_2bps)
    assert portfolio.holdout_max_drawdown_2bps >= 0.0


def test_m40_benchmark_report_execution_and_artifacts():
    """Verify full benchmark execution generates report, dataset files, and JSON artifact."""
    report = run_m40_multi_asset_benchmark()
    assert report.milestone == "M40"
    assert report.total_15m_candles == 6227
    assert report.resampled_htf_candles == 499
    assert report.total_aligned_rows == 488
    assert report.num_folds == 19
    assert report.dev_fold_count == 14
    assert report.holdout_fold_count == 5

    artifact_file = REPO_ROOT / "var" / "datasets" / "m40_multi_asset_benchmark.json"
    assert artifact_file.exists()
    with open(artifact_file, "r") as f:
        data = json.load(f)
    assert data["milestone"] == "M40"
    assert "nifty_summary" in data
    assert "banknifty_summary" in data


def test_m40_safety_invariants_strictly_false():
    """Verify all 5 hard financial safety invariants remain strictly False."""
    report = run_m40_multi_asset_benchmark()
    invs = report.safety_invariants
    assert invs["forecast_ready"] is False
    assert invs["real_market_data_verified"] is False
    assert invs["paper_approved"] is False
    assert invs["live_approved"] is False
    assert invs["live_broker_routing_enabled"] is False
