"""Honest out-of-sample evaluation for walk-forward research.

Replaces per-fold aggregation shortcuts with metrics computed on one chained
out-of-sample equity curve, and adds the statistics needed to judge whether a
result could be luck:

- Chained equity: positions carry across contiguous validation folds; a cost is
  charged on every position change, including the final exit. Return is
  compounded; drawdown is measured on the single chained curve.
- Sharpe ratio annualized with the bar frequency actually traded.
- Probabilistic Sharpe Ratio (PSR) and Deflated Sharpe Ratio (DSR), Bailey &
  Lopez de Prado (2012, 2014). DSR raises the bar by the expected maximum Sharpe
  of N independent trials, so selecting the best of many strategies is penalized.
- Wilson confidence interval and exact binomial p-value for directional accuracy.
- Brier skill score against the evaluation set's own base rate.
- Moving-block bootstrap confidence interval for the mean bar return.

Nothing here fabricates a value: undefined statistics are returned as None.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from scipy import stats

EULER_MASCHERONI = 0.5772156649015329

# Trading sessions per year on NSE (approximate; used only to annualize Sharpe).
TRADING_DAYS_PER_YEAR = 248
HALF_DAY_BARS_PER_YEAR = 2 * TRADING_DAYS_PER_YEAR


@dataclass(frozen=True)
class OOSBar:
    """One out-of-sample bar: the position held over the bar and the bar's return."""

    timestamp: str
    partition: str  # "development" | "holdout"
    position: float  # -1.0 .. +1.0
    bar_return: float  # simple return of the underlying over the bar
    probability: float | None  # model P(up), when the model emits one
    label: int | None  # 1 if the bar closed up, else 0


# ----------------------------------------------------------------------------- costs

@dataclass(frozen=True)
class FuturesCostModel:
    """Per-side cost of trading an index future, as a fraction of notional.

    Statutory rates for NSE index futures (re-check when SEBI/exchanges revise them):
    STT 0.02% on the sell side, exchange transaction charge 0.00173%, SEBI fee
    Rs10/crore (0.0001%), stamp duty 0.002% on the buy side, GST 18% on
    (brokerage + exchange + SEBI). Slippage is an assumption, not a statutory rate.
    """

    stt_sell: float = 0.0002
    exchange_txn: float = 0.0000173
    sebi_fee: float = 0.000001
    stamp_buy: float = 0.00002
    gst_rate: float = 0.18
    brokerage_per_order_inr: float = 20.0
    slippage_per_side: float = 0.0001  # 1 bp assumed half-spread + impact

    def per_side(self, notional_inr: float | None = None) -> float:
        """Average one-way cost fraction (buy and sell sides averaged)."""
        brokerage = (self.brokerage_per_order_inr / notional_inr) if notional_inr else 0.0
        gst = self.gst_rate * (brokerage + self.exchange_txn + self.sebi_fee)
        buy = self.exchange_txn + self.sebi_fee + self.stamp_buy + brokerage + gst
        sell = self.exchange_txn + self.sebi_fee + self.stt_sell + brokerage + gst
        return (buy + sell) / 2.0 + self.slippage_per_side


# --------------------------------------------------------------------- equity curve

def chained_equity_metrics(
    bars: Sequence[OOSBar],
    *,
    cost_per_side: float,
    periods_per_year: int = HALF_DAY_BARS_PER_YEAR,
) -> dict:
    """Metrics of one continuous out-of-sample curve built from `bars` in order.

    A position change of size |dp| costs |dp| * cost_per_side. Any open position is
    closed after the last bar and that exit is charged.
    """
    n = len(bars)
    if n == 0:
        return {"bars": 0, "total_return_pct": None, "max_drawdown_pct": None, "sharpe_annualized": None,
                "trades": 0, "turnover_units": 0.0, "exposure_pct": None, "per_bar_returns": []}

    net: list[float] = []
    prev = 0.0
    trades = 0
    turnover = 0.0
    for i, bar in enumerate(bars):
        delta = abs(bar.position - prev)
        if delta > 0:
            trades += 1
            turnover += delta / 2.0
        r = bar.position * bar.bar_return - delta * cost_per_side
        if i == n - 1 and bar.position != 0:
            r -= abs(bar.position) * cost_per_side  # final exit
            turnover += abs(bar.position) / 2.0
        net.append(r)
        prev = bar.position

    arr = np.asarray(net, dtype=float)
    equity = np.cumprod(1.0 + arr)
    peaks = np.maximum.accumulate(np.concatenate([[1.0], equity]))[1:]
    drawdowns = (peaks - equity) / peaks
    exposure = float(np.mean([abs(b.position) > 0 for b in bars])) * 100.0

    std = float(np.std(arr, ddof=1)) if n > 1 else 0.0
    sharpe_period = float(np.mean(arr) / std) if std > 0 else None
    return {
        "bars": n,
        "total_return_pct": float(equity[-1] - 1.0) * 100.0,
        "max_drawdown_pct": float(np.max(drawdowns)) * 100.0,
        "sharpe_per_bar": sharpe_period,
        "sharpe_annualized": sharpe_period * math.sqrt(periods_per_year) if sharpe_period is not None else None,
        "skew": float(stats.skew(arr)) if n > 2 and std > 0 else None,
        "kurtosis": float(stats.kurtosis(arr, fisher=False)) if n > 3 and std > 0 else None,
        "trades": trades,
        "turnover_units": turnover,
        "exposure_pct": exposure,
        "per_bar_returns": net,
    }


# ------------------------------------------------------------- Sharpe significance

def probabilistic_sharpe_ratio(
    sharpe_per_bar: float | None,
    n_bars: int,
    skew: float | None,
    kurtosis: float | None,
    benchmark_sharpe_per_bar: float = 0.0,
) -> float | None:
    """P(true Sharpe > benchmark), adjusting for sample length, skew and fat tails."""
    if sharpe_per_bar is None or n_bars < 3:
        return None
    g3 = skew if skew is not None else 0.0
    g4 = kurtosis if kurtosis is not None else 3.0
    denom_sq = 1.0 - g3 * sharpe_per_bar + (g4 - 1.0) / 4.0 * sharpe_per_bar ** 2
    if denom_sq <= 0:
        return None
    z = (sharpe_per_bar - benchmark_sharpe_per_bar) * math.sqrt(n_bars - 1) / math.sqrt(denom_sq)
    return float(stats.norm.cdf(z))


def expected_max_sharpe(n_trials: int, sharpe_variance: float) -> float:
    """Expected maximum per-bar Sharpe among n_trials skill-less strategies."""
    if n_trials < 2 or sharpe_variance <= 0:
        return 0.0
    sd = math.sqrt(sharpe_variance)
    return sd * (
        (1.0 - EULER_MASCHERONI) * stats.norm.ppf(1.0 - 1.0 / n_trials)
        + EULER_MASCHERONI * stats.norm.ppf(1.0 - 1.0 / (n_trials * math.e))
    )


def deflated_sharpe_ratio(
    sharpe_per_bar: float | None,
    n_bars: int,
    skew: float | None,
    kurtosis: float | None,
    *,
    n_trials: int,
    trial_sharpe_variance: float,
) -> float | None:
    """PSR against the Sharpe the best of n_trials random strategies would reach."""
    return probabilistic_sharpe_ratio(
        sharpe_per_bar, n_bars, skew, kurtosis,
        benchmark_sharpe_per_bar=expected_max_sharpe(n_trials, trial_sharpe_variance),
    )


# ------------------------------------------------------------- accuracy and skill

def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n <= 0:
        return None
    p = successes / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (centre - half, centre + half)


def directional_accuracy(bars: Sequence[OOSBar]) -> dict:
    """Accuracy of the sign of non-flat positions vs the realized bar direction."""
    active = [b for b in bars if b.position != 0 and b.label is not None]
    n = len(active)
    if n == 0:
        return {"n": 0, "accuracy": None, "ci95": None, "p_value_vs_50pct": None}
    hits = sum(1 for b in active if (b.position > 0) == (b.label == 1))
    p_value = float(stats.binomtest(hits, n, 0.5).pvalue)
    return {"n": n, "accuracy": hits / n, "ci95": wilson_interval(hits, n), "p_value_vs_50pct": p_value}


def brier_skill_vs_climatology(bars: Sequence[OOSBar]) -> float | None:
    """1 - Brier / Brier(base rate of the evaluated bars). None when undefined."""
    rows = [(b.probability, b.label) for b in bars if b.probability is not None and b.label is not None]
    if len(rows) < 2:
        return None
    p = np.array([r[0] for r in rows], dtype=float)
    y = np.array([r[1] for r in rows], dtype=float)
    base = float(np.mean(y))
    ref = float(np.mean((base - y) ** 2))
    if ref <= 0:
        return None
    return 1.0 - float(np.mean((p - y) ** 2)) / ref


def block_bootstrap_mean_ci(
    values: Sequence[float],
    *,
    block: int = 5,
    n_boot: int = 2000,
    alpha: float = 0.05,
    seed: int = 42,
) -> tuple[float, float] | None:
    """Moving-block bootstrap CI for the mean (preserves short-range autocorrelation)."""
    arr = np.asarray(values, dtype=float)
    n = len(arr)
    if n < max(10, 2 * block):
        return None
    rng = np.random.default_rng(seed)
    n_blocks = int(math.ceil(n / block))
    starts_max = n - block + 1
    means = np.empty(n_boot)
    for i in range(n_boot):
        starts = rng.integers(0, starts_max, size=n_blocks)
        sample = np.concatenate([arr[s:s + block] for s in starts])[:n]
        means[i] = sample.mean()
    return (float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2)))


# --------------------------------------------------------------------- summary

def evaluate_partition(
    bars: Sequence[OOSBar],
    *,
    cost_per_side: float,
    periods_per_year: int = HALF_DAY_BARS_PER_YEAR,
) -> dict:
    """All honest metrics for one partition (or the full out-of-sample run)."""
    eq = chained_equity_metrics(bars, cost_per_side=cost_per_side, periods_per_year=periods_per_year)
    acc = directional_accuracy(bars)
    returns = eq.pop("per_bar_returns")
    mean_ci = block_bootstrap_mean_ci(returns)
    return {
        **eq,
        "mean_bar_return_ci95_pct": (mean_ci[0] * 100.0, mean_ci[1] * 100.0) if mean_ci else None,
        "psr_vs_zero": probabilistic_sharpe_ratio(eq.get("sharpe_per_bar"), eq["bars"], eq.get("skew"), eq.get("kurtosis")),
        "directional_accuracy": acc,
        "brier_skill_vs_climatology": brier_skill_vs_climatology(bars),
        "cost_per_side": cost_per_side,
    }


def add_deflated_sharpe(evaluations: list[dict], partition: str = "development") -> None:
    """Attach DSR to each strategy, treating every evaluated strategy as one trial.

    `evaluations` items must contain evaluations[i][partition] from evaluate_partition.
    """
    srs = [e[partition].get("sharpe_per_bar") for e in evaluations]
    valid = [s for s in srs if s is not None]
    n_trials = len(evaluations)
    variance = float(np.var(valid, ddof=1)) if len(valid) > 1 else 0.0
    for e in evaluations:
        part = e[partition]
        part["deflated_sharpe"] = deflated_sharpe_ratio(
            part.get("sharpe_per_bar"), part["bars"], part.get("skew"), part.get("kurtosis"),
            n_trials=n_trials, trial_sharpe_variance=variance,
        )
        part["trials_considered"] = n_trials
