# Milestone M27: Higher-Timeframe (1-Hour & Half-Day Swing) Research Report

**Milestone:** M27 Higher-Timeframe Resampling & Swing Target Alignment  
**Date:** 2026-10-17  
**Author:** Autonomous Engineering & Quantitative Research Agent  
**Dataset:** 1-Year NIFTY 15m Dataset (`bc7d31bceebf13a3...`, 6,227 candles)  
**Status:** **RESEARCH COMPLETED & PERSISTED**  
**Financial Safety Invariants:** All 5 strictly `False` (`forecast_ready = false`, etc.)

---

## 1. Executive Summary & Core Hypothesis

Milestone M26 demonstrated that attempting to forecast and trade on a **15-minute intraday horizon** is fundamentally impaired by an insurmountable **fee-to-alpha ratio**:
- On 15m bars, average price displacement $\mathbb{E}[|R|]$ is merely **$0.12\%$** ($12\text{ bps}$).
- A standard exchange transaction friction of $2\text{ bps}$ per leg ($4\text{ bps}$ roundtrip) consumes **$33.3\%$** of every gross move.
- Consequently, unconstrained 15m models suffered severe turnover drag (974 turnover units), and even after a 60% turnover reduction via hysteresis, no strategy achieved positive net return at 2 bps fees.

**The M27 Hypothesis:**
By mathematically resampling 15m continuous candles into **Higher-Timeframe (HTF)** swing bars (1-Hour and Half-Day sessions) without lookahead, we expect:
1. Average bar displacement to expand $2\times$ to $4\times$, reducing fee drag from $33.3\%$ to below $10\%$.
2. Baseline turnover to drop naturally by $70\%$ to $90\%$ without requiring artificial holding constraints.
3. Macro swing trends to emerge with lower microstructure noise.

---

## 2. Resampling Architecture & Point-in-Time Causality

The resampling engine (`resample_candles_to_htf`) operates under strict causal constraints:
- **No Cross-Session Leakage:** Candles are bucketed strictly within their calendar `session_date`. The 15:15–15:30 tail of Day $D$ is never merged with the 09:15–09:30 open of Day $D+1$.
- **Point-in-Time Availability:** The emitted timestamp of an HTF bar is the close timestamp of its final constituent 15m bar. For example:
  - 1-Hour bar covering 09:15, 09:30, 09:45, 10:00 is emitted at `10:00:00`.
  - It becomes available for signal generation strictly at `10:00:00`.
- **Strict Geometric Validation:** Every bar verifies:
  $$\text{High} \ge \max(\text{Open}, \text{Close}) \quad \text{and} \quad \text{Low} \le \min(\text{Open}, \text{Close})$$
  $$\text{Volume} = \sum \text{constituent volumes}$$

---

## 3. Alpha-to-Friction Empirical Comparison

Across the 1-year NIFTY dataset (6,227 15m candles):

| Timeframe | Candle Count | Avg Bar Displacement $\mathbb{E}[\|R\|]$ | 2 bps Fee-to-Alpha Ratio | Max Turnover Potential |
| :--- | :---: | :---: | :---: | :---: |
| **15-Minute (M25/M26)** | 6,227 | **0.120%** | **33.33%** | Very High (~1,000 units) |
| **1-Hour (M27)** | 1,743 | **0.207%** | **19.30%** | Medium (~400 units) |
| **Half-Day (M27)** | 499 | **0.443%** | **9.03%** | Low (~120 units) |

> **Key Finding:** Resampling to Half-Day swing bars cuts the fee-to-alpha friction from **33.3% down to 9.03%**—a **$3.7\times$ reduction in friction sensitivity**.

---

## 4. Benchmark Results: 1-Hour Timeframe (24 Expanding Folds)

- **Initial Training Window:** 500 bars (~80 trading days)
- **Validation Step:** 50 bars (~8 trading days)
- **Embargo:** 2 bars
- **Total Folds:** 24 folds
- **Holdout Partition:** Folds 21–24 (Untouched Holdout)

| Model | Accuracy | Brier Score | Gross Ret (0 bps) | Net Ret (2 bps) | Net Ret (5 bps) | Turnover Units | Max DD (2 bps) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Empirical Prior** | 51.0% | 0.2503 | +0.11% | **+0.09%** | +0.07% | 12.0 | 2.37% |
| **Logistic Regression** | 50.0% | 0.2572 | -0.12% | -0.79% | -1.79% | 404.0 | 2.97% |
| **Ridge Classifier** | 50.0% | 0.2520 | -0.17% | -0.85% | -1.87% | 410.0 | 3.01% |
| **LightGBM** | 50.0% | 0.2545 | **+0.51%** | -0.23% | -1.33% | 445.0 | 2.57% |
| **XGBoost** | 50.0% | 0.2533 | **+0.31%** | -0.43% | -1.53% | 444.0 | 2.69% |

### Untouched Holdout (Folds 21–24, 200 bars):
- **Empirical Prior:** +1.85% at 2 bps (Turnover: 2.0 units)
- **Logistic Regression:** -0.55% at 2 bps (Turnover: 76.0 units)
- **LightGBM:** -1.21% at 2 bps (Turnover: 83.0 units)

---

## 5. Benchmark Results: Half-Day Timeframe (14 Expanding Folds)

- **Initial Training Window:** 200 bars (~100 trading days)
- **Validation Step:** 20 bars (~10 trading days)
- **Embargo:** 2 bars
- **Total Folds:** 14 folds
- **Holdout Partition:** Folds 11–14 (Untouched Holdout)

| Model | Accuracy | Brier Score | Gross Ret (0 bps) | Net Ret (2 bps) | Net Ret (5 bps) | Turnover Units | Max DD (2 bps) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Empirical Prior** | 47.0% | 0.2513 | +0.17% | **+0.15%** | +0.12% | 7.0 | 2.33% |
| **Logistic Regression** | 49.0% | 0.2629 | -0.71% | -1.07% | -1.61% | 125.0 | 2.87% |
| **Ridge Classifier** | 49.0% | 0.2526 | -0.65% | -0.99% | -1.49% | 122.0 | 2.83% |
| **LightGBM** | 46.0% | 0.2605 | -1.80% | -2.18% | -2.75% | 136.0 | 3.49% |
| **XGBoost** | 49.0% | 0.2585 | -0.31% | -0.65% | -1.16% | 121.0 | 3.00% |

### Untouched Holdout (Folds 11–14, 80 bars):
- **Empirical Prior:** +1.39% at 2 bps (Turnover: 2.0 units)
- **Logistic Regression:** -1.06% at 2 bps (Turnover: 39.0 units)
- **XGBoost:** -0.70% at 2 bps (Turnover: 30.0 units)

---

## 6. Critical Quantitative Diagnostic & Root Cause

While HTF resampling successfully solved the turnover problem (slashing turnover by **87.5%** from 974 down to 121 units) and fee drag (dropping to 9.03%), **directional accuracy remains centered around 48%–51%**.

### Why do standard ML classifiers fail to predict directional swing returns?
1. **Regime Ignorance:** Standard models treat all market bars identically. In trending phases, momentum rules generate profits; but in sideways consolidation ranges, the same momentum rules suffer consecutive false breakout whipsaws.
2. **Feature Saturation:** Static rolling lookbacks (4-bar, 8-bar) do not adapt when market volatility contracts or expands.
3. **Absence of Volatility / Regime Gate:** The models attempt to force a directional trade (+1 or -1) on every single bar, rather than asserting `NO_TRADE` during choppy consolidations.

---

## 7. Next Actions on Autonomous Roadmap

To convert the improved fee-to-alpha structure into a viable trading edge, the next priority is:
- **Milestone M28: Causal Market Regime Detection (Trend vs. Mean Reverting vs. Consolidation)**
  - Implement adaptive ATR, ADX (Average Directional Index), and Hurst Exponent filters.
  - Enforce `NO_TRADE` when trend strength is below threshold, taking trades exclusively when regime confidence is confirmed.
