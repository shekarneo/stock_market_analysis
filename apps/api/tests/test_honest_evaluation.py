"""Tests for the chained out-of-sample evaluation toolkit and dev-only selection.

Synthetic data only; these check that the statistics behave correctly, not that
any strategy is profitable.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from app.forecasting.evaluation import (
    FuturesCostModel,
    OOSBar,
    add_deflated_sharpe,
    block_bootstrap_mean_ci,
    brier_skill_vs_climatology,
    chained_equity_metrics,
    deflated_sharpe_ratio,
    directional_accuracy,
    evaluate_partition,
    expected_max_sharpe,
    probabilistic_sharpe_ratio,
    wilson_interval,
)


def _bars(positions, returns, partition="development", probs=None):
    out = []
    for i, (p, r) in enumerate(zip(positions, returns)):
        out.append(OOSBar(str(i), partition, float(p), float(r),
                          None if probs is None else float(probs[i]), 1 if r > 0 else 0))
    return out


def test_chained_curve_compounds_and_charges_every_change_and_final_exit():
    bars = _bars([1, 1, 0, -1], [0.01, -0.02, 0.03, -0.01])
    m = chained_equity_metrics(bars, cost_per_side=0.001)
    expected = [0.01 - 0.001, -0.02, 0.0 - 0.001, 0.01 - 0.001 - 0.001]
    assert m["total_return_pct"] == pytest.approx((np.prod([1 + x for x in expected]) - 1) * 100)
    assert m["trades"] == 3
    assert m["turnover_units"] == pytest.approx(0.5 + 0.5 + 0.5 + 0.5)


def test_drawdown_is_measured_on_the_chained_curve():
    bars = _bars([1, 1, 1], [0.10, -0.20, 0.05])
    m = chained_equity_metrics(bars, cost_per_side=0.0)
    # peak 1.10, trough 0.88 -> 20% drawdown
    assert m["max_drawdown_pct"] == pytest.approx(20.0)


def test_empty_partition_reports_none_not_zero():
    m = evaluate_partition([], cost_per_side=0.0002)
    assert m["total_return_pct"] is None
    assert m["sharpe_annualized"] is None
    assert m["directional_accuracy"]["accuracy"] is None


def test_flat_strategy_has_no_sharpe():
    m = chained_equity_metrics(_bars([0, 0, 0], [0.01, -0.01, 0.02]), cost_per_side=0.0002)
    assert m["sharpe_per_bar"] is None
    assert m["total_return_pct"] == 0.0


def test_random_positions_are_not_significant():
    rng = np.random.default_rng(7)
    r = rng.normal(0, 0.006, 600)
    pos = rng.choice([-1.0, 1.0], 600)
    e = evaluate_partition(_bars(pos, r), cost_per_side=FuturesCostModel().per_side())
    assert e["directional_accuracy"]["p_value_vs_50pct"] > 0.05
    assert e["psr_vs_zero"] < 0.95


def test_genuine_edge_is_detected():
    rng = np.random.default_rng(11)
    r = rng.normal(0, 0.006, 600)
    sign = np.sign(r)
    pos = np.where(rng.random(600) < 0.65, sign, -sign)
    e = evaluate_partition(_bars(pos, r), cost_per_side=0.0)
    assert e["directional_accuracy"]["p_value_vs_50pct"] < 0.01
    assert e["psr_vs_zero"] > 0.95


def test_deflated_sharpe_penalizes_more_trials():
    sr, n = 0.08, 500
    few = deflated_sharpe_ratio(sr, n, 0.0, 3.0, n_trials=2, trial_sharpe_variance=0.002)
    many = deflated_sharpe_ratio(sr, n, 0.0, 3.0, n_trials=100, trial_sharpe_variance=0.002)
    assert few > many
    assert expected_max_sharpe(1, 0.002) == 0.0
    assert probabilistic_sharpe_ratio(None, 100, 0.0, 3.0) is None


def test_add_deflated_sharpe_counts_every_strategy_as_a_trial():
    rng = np.random.default_rng(3)
    evals = []
    for _ in range(5):
        r = rng.normal(0, 0.006, 200)
        evals.append({"development": evaluate_partition(_bars(rng.choice([-1.0, 1.0], 200), r), cost_per_side=0.0)})
    add_deflated_sharpe(evals)
    assert all(e["development"]["trials_considered"] == 5 for e in evals)
    assert all(0.0 <= e["development"]["deflated_sharpe"] <= 1.0 for e in evals)


def test_wilson_interval_and_accuracy():
    lo, hi = wilson_interval(52, 100)
    assert lo < 0.5 < hi  # 52% on 100 trades is not distinguishable from a coin flip
    acc = directional_accuracy(_bars([1, 1, -1, 0], [0.01, -0.01, -0.02, 0.05]))
    assert acc["n"] == 3 and acc["accuracy"] == pytest.approx(2 / 3)


def test_brier_skill_uses_evaluation_climatology():
    bars = _bars([1, 1, 1, 1], [0.01, 0.02, -0.01, 0.03], probs=[0.75, 0.75, 0.75, 0.75])
    # base rate of the evaluated bars is 0.75, so a constant 0.75 forecast has zero skill
    assert brier_skill_vs_climatology(bars) == pytest.approx(0.0, abs=1e-12)


def test_block_bootstrap_ci_contains_sample_mean():
    rng = np.random.default_rng(5)
    x = rng.normal(0.001, 0.01, 300)
    lo, hi = block_bootstrap_mean_ci(x)
    assert lo < float(np.mean(x)) < hi
    assert block_bootstrap_mean_ci([0.01, 0.02]) is None


def test_futures_cost_model_is_in_a_realistic_range():
    per_side_bps = FuturesCostModel().per_side() * 1e4
    assert 1.5 < per_side_bps < 4.0
    with_brokerage = FuturesCostModel().per_side(notional_inr=65 * 25000) * 1e4
    assert with_brokerage > per_side_bps


def test_benchmark_ranking_uses_development_only():
    from app.main import _dev_rank_key

    rows = [
        {"dev_deflated_sharpe": 0.20, "dev_sharpe_annualized": 0.5, "holdout_net_return_2bps": 25.0},
        {"dev_deflated_sharpe": 0.60, "dev_sharpe_annualized": 0.3, "holdout_net_return_2bps": -3.0},
        {"dev_deflated_sharpe": None, "dev_sharpe_annualized": None, "holdout_net_return_2bps": 50.0},
    ]
    best = max(rows, key=_dev_rank_key)
    assert best["dev_deflated_sharpe"] == 0.60  # a large holdout return never buys the top rank
    assert math.isinf(_dev_rank_key(rows[2])[0])
