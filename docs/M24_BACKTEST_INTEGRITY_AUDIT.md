# M24 — INDEPENDENT STRATEGY ACCOUNTING, EXECUTION SIMULATION AND BACKTEST INTEGRITY AUDIT

**Project**: V6 Indian Market Forecasting System  
**Audit Target**: M23 Strategy Accounting, Walk-Forward Simulation, Target Alignment, and Return Accounting  
**Persisted Dataset**: 1-Year NIFTY 15-Minute Candles (6,227 regular session bars, 250 trading days)  
**Dataset ID**: `bc7d31bceebf13a34a1c94daabd788d2b83ee1397f89060183ed7e68d2b55692`  
**Dataset SHA-256**: `9154899b1e1898a68bf200d729a9a661ff8b13d4fd0d7e7c39e481bcbbf09b9d`  
**Date**: October 17, 2026  
**Status**: AUDIT COMPLETE (All Code Traced, Results Independently Reproduced, Defects Documented)

---

## 1. EXECUTIVE SUMMARY

An independent accounting audit of the complete path from out-of-sample predictions to position transitions, friction costs, equity curves, and reported returns was conducted across all 10 models benchmarked in Milestone M23.

### Key Conclusions:
1. **Root Cause of M23 Negative Trading Performance**:
   - The negative returns reported for `O2O` models (e.g., Logistic Regression at -5.00% gross, -21.79% at 2 bps, -64.08% at 10 bps) are **mathematically correct consequences of excessive turnover** combined with near-zero directional edge (~50.1% to 50.6% accuracy).
   - In Logistic Regression, the strategy executed **972 position transitions (486 closed round trips)** over 4,750 test observations. At 2 bps per transition ($0.02\%$), the raw transaction cost drag alone equals $972 \times 0.02\% = \mathbf{19.44\%}$. When compounded across the 19 expanding folds, this directly and completely accounts for the drop from -5.003% to -21.792%.
2. **Confirmed Architectural Defects Discovered During Audit**:
   - **Defect A (Missing Embargo Between Validation and Test Folds)**: While an `embargo_bars = 2` buffer was correctly placed between `train_end` and `val_start`, `test_start = val_end` had 0 embargo bars. For 2-step targets (`O2O` and `O2C_2B`), the final validation label $y_{\text{val}}[-1]$ references `open[val_end + 1]`, creating a 1-bar target overlap with the start of the test fold during validation-based calibration.
   - **Defect B (Target `O2C_1B` Turnover & Cost Undercounting)**: In `O2C_1B`, every trade enters at `open[t+1]` and exits at `close[t+1]`. By definition, the strategy is in cash between `close[t+1]` and `open[t+2]`. In M23, consecutive long signals (`1 -> 1`) were assigned $\Delta s = |1 - 1| = 0$, charging zero cost and zero turnover, despite the return series omitting the close-to-open gap. In physical reality, staying flat between sessions requires a closing sell and next-day opening buy ($2c$ fee).
   - **Defect C (Target `O2C_2B` Overlapping Return Double-Counting)**: `O2C_2B` spans a 2-bar holding period (`open[t+1]` to `close[t+2]`). When adjacent predictions are both 1, the holding periods overlap over $[open[t+2], close[t+2]]$. Sequential bar compounding in M23 treated them as two consecutive 100% unleveraged trades, effectively double-counting market returns during overlapping intervals.
   - **Defect D (Turnover Ambiguity: Orders vs Units)**: In `m23_research.py`, `turnover += 1` incremented by 1 on any non-zero transition. While valid for long-only ($s \in \{0, 1\}$), a direct reversal ($+1 \to -1$) in long-short requires changing 2 units. The audit formally decouples `turnover_units = sum(|delta_s|)` from `order_count = count(delta_s != 0)`.
3. **Foundation Model Findings**:
   - **Google TimesFM 3.0**: Formally blocked by `timesfm-non-commercial-license-v1.0`. Commercial/production deployment is prohibited by Google terms. Results were omitted without fabrication.
   - **Amazon Chronos-2**: Permissive Apache-2.0. Generated the lowest turnover (229 trades on O2O) and best probability calibration (Brier 0.2524–0.2534), suffering the lowest fee degradation (-43.95% at 10 bps vs -64% to -69% for linear and tree models).

---

## 2. ACTUAL IMPLEMENTATION FILES & FUNCTIONS INSPECTED

| File Path | Component / Functions Inspected | Audit Role |
| :--- | :--- | :--- |
| [`apps/api/app/forecasting/m23_research.py`](file:///home/neo/work/personal/stock_market_analysis/apps/api/app/forecasting/m23_research.py) | `extract_m23_expanded_features` (L217–L355)<br>`evaluate_m23_walkforward` (L485–L841)<br>`run_m23_comprehensive_benchmark` (L844–L937) | Production benchmark engine, feature extraction, walk-forward loop, cost compounding. |
| [`apps/api/app/forecasting/m22_research.py`](file:///home/neo/work/personal/stock_market_analysis/apps/api/app/forecasting/m22_research.py) | `audit_information_availability_contract` (L120–L240)<br>`extract_point_in_time_features` | Target definitions and information availability contracts. |
| [`apps/api/app/market/storage.py`](file:///home/neo/work/personal/stock_market_analysis/apps/api/app/market/storage.py) | `MarketDataStorageService.cache_benchmark_result` (L385–L440)<br>`get_cached_benchmark` (L442–L490) | Benchmark cache lookup, hash generation, and invalidation rules. |
| [`apps/api/app/market/history_routes.py`](file:///home/neo/work/personal/stock_market_analysis/apps/api/app/market/history_routes.py) | `run_m23_benchmark_endpoint` (L1155–L1228)<br>`invalidate_benchmark_cache_endpoint` (L1117–L1147) | API routing, request validation, and cache management. |
| [`apps/api/app/forecasting/m24_accounting.py`](file:///home/neo/work/personal/stock_market_analysis/apps/api/app/forecasting/m24_accounting.py) | `simulate_independent_accounting`<br>`EXECUTION_CONTRACTS` | Independent reference accounting engine implemented for M24 audit. |

---

## 3. TARGET DEFINITIONS & EXECUTION SEMANTICS

| Target | Formula | Prediction Time | Earliest Fill | Entry Price | Exit Price | Holding Horizon | Overlapping? | Executable? | Rationale |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :---: | :---: | :--- |
| **`C2C`** | $\frac{\text{Close}[t+1] - \text{Close}[t]}{\text{Close}[t]}$ | $\text{Close}[t]$ | $\text{Close}[t]$ | $\text{Close}[t]$ | $\text{Close}[t+1]$ | 1 bar | No | **NO** | **Theoretical benchmark only**. A signal computed after bar $t$ closes cannot execute at that exact closing price. |
| **`O2O`** | $\frac{\text{Open}[t+2] - \text{Open}[t+1]}{\text{Open}[t+1]}$ | $\text{Close}[t]$ | $\text{Open}[t+1]$ | $\text{Open}[t+1]$ | $\text{Open}[t+2]$ | 1 bar | No | **YES** | **Physically executable**. Features use data $\le t$. Order submitted for $\text{Open}[t+1]$. Contiguous holding across $t+1 \to t+2$ without fee when position remains unchanged. |
| **`O2C_1B`** | $\frac{\text{Close}[t+1] - \text{Open}[t+1]}{\text{Open}[t+1]}$ | $\text{Close}[t]$ | $\text{Open}[t+1]$ | $\text{Open}[t+1]$ | $\text{Close}[t+1]$ | Intraday bar | No | **YES** | **Executable intraday**. Enters at $\text{Open}[t+1]$, exits at $\text{Close}[t+1]$. Flat between $\text{Close}[t+1]$ and $\text{Open}[t+2]$. Requires round-trip fee for every traded bar. |
| **`O2C_2B`** | $\frac{\text{Close}[t+2] - \text{Open}[t+1]}{\text{Open}[t+1]}$ | $\text{Close}[t]$ | $\text{Open}[t+1]$ | $\text{Open}[t+1]$ | $\text{Close}[t+2]$ | 2 bars | **YES** | **YES** | **Multi-bar swing**. Overlaps by 1 bar on consecutive 1s. Requires separate trade-leg tracking to prevent double-counting. |

---

## 4. INDEPENDENT ACCOUNTING METHODOLOGY

An independent simulator [`simulate_independent_accounting`](file:///home/neo/work/personal/stock_market_analysis/apps/api/app/forecasting/m24_accounting.py#L98-L225) was constructed from first principles without calling production return functions:
1. **Decoupled Turnover Metrics**:
   - $\text{Turnover Units} = \sum_{t=1}^N |\Delta s_t|$ (Total units of position traded)
   - $\text{Order Count} = \sum_{t=1}^N \mathbf{1}(\Delta s_t \ne 0)$ (Number of order executions)
2. **Transaction Cost Timing**:
   - One-way fee $c = \frac{\text{bps}}{10000}$ applied to actual position delta: $\text{Fee}_t = |\Delta s_t| \times c$.
   - Entry cost deducted on entry; exit cost deducted on exit; terminal exit cost deducted on fold completion if position remains open.
3. **Equity Compounding**:
   - Per-bar net return: $R_{\text{net}, t} = s_t R_t - \text{Fee}_t$.
   - Compounded capital: $E_t = E_{t-1} \times (1 + R_{\text{net}, t})$.
   - Final terminal exit: If $s_N \ne 0$, $E_{\text{final}} = E_N \times (1 - |s_N| c)$.

---

## 5. HAND-CALCULATED TEST FIXTURES & RESULTS

All 10 scenarios required by Phase 3 were implemented with exact analytical solutions and verified via automated tests in [`tests/test_m24_backtest_integrity.py`](file:///home/neo/work/personal/stock_market_analysis/apps/api/tests/test_m24_backtest_integrity.py):

| Scenario | Input Signals | Returns | Cost (bps) | Analytical Expected Net Return | Independent Simulator Net Return | Turnover Units | Orders | Status |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **1. Long Entry from Flat** | `[1]` | `[+0.02]` | 10 | $1.0 \cdot (1 + 0.019) \cdot (1 - 0.001) - 1 = \mathbf{+1.7981\%}$ | **+1.7981%** | 2.0 | 2 | **PASSED** |
| **2. Long Exit to Flat** | `[1, 0]` | `[+0.01, +0.05]` | 10 | $(1 + 0.009) \cdot (1 - 0.001) - 1 = \mathbf{+0.7991\%}$ | **+0.7991%** | 2.0 | 2 | **PASSED** |
| **3. Direct Reversal (+1 to -1)** | `[1, -1]` | `[+0.01, -0.02]` | 10 | $(1 + 0.009) \cdot (1 + 0.018) \cdot 0.999 - 1 = \mathbf{+2.6135\%}$ | **+2.6135%** | **4.0** | **3** | **PASSED** |
| **4. Unchanged Position** | `[1, 1, 1]` | `[+0.01, +0.01, +0.01]` | 10 | $1.009 \cdot 1.01 \cdot 1.01 \cdot 0.999 - 1 = \mathbf{+2.8252\%}$ | **+2.8252%** | 2.0 | 2 | **PASSED** |
| **5. Zero-Return Market** | `[1, 1, 0, 1]` | `[0.0, 0.0, 0.0, 0.0]` | 10 | $0.999 \cdot 1.0 \cdot 0.999 \cdot 0.999 \cdot 0.999 - 1 = \mathbf{-0.3994\%}$ | **-0.3994%** | 4.0 | 4 | **PASSED** |
| **6. Whipsaw Returns** | `[1, 0, 1, 0]` | `[-0.01, +0.02, -0.015, +0.03]` | 5 | $0.9895 \cdot 0.9995 \cdot 0.9845 \cdot 0.9995 - 1 = \mathbf{-2.6811\%}$ | **-2.6811%** | 4.0 | 4 | **PASSED** |
| **7. Monotonic Cost Drag** | `[1, 0, 1, 1, 0, 1]` | Multi | 0, 2, 5, 10 | $R(0) > R(2) > R(5) > R(10)$ strictly holds | Verified Monotonic | 6.0 | 6 | **PASSED** |
| **8. Session Gap / Missing Bar** | `[1, 1]` | `[+0.01, +0.01]` | 2 | Gap return treated as price ratio, zero synthetic bars | Verified Consistent | 2.0 | 2 | **PASSED** |
| **9. Boundary Liquidation** | `[0, 1]` | `[+0.01, +0.02]` | 5 | $1.0 \cdot (1 + 0.0195) \cdot 0.9995 - 1 = \mathbf{+1.8990\%}$ | **+1.8990%** | 2.0 | 2 | **PASSED** |
| **10. O2C_1B Inter-Bar Exit** | `[1, 1]` | `[+0.01, +0.01]` | 10 | Mandates inter-bar exit ($4c$ fee) vs contiguous ($2c$ fee) | Verified $R(\text{O2C}) < R(\text{O2O})$ | 4.0 | 4 | **PASSED** |

---

## 6. BACKTEST LEAKAGE AUDIT FINDINGS

| Audit Category | Investigation & Code Evidence | Verdict | Defect Level |
| :--- | :--- | :---: | :--- |
| **Feature Leakage** | All 12 feature dimensions in `extract_m23_expanded_features` strictly index $\le t$. Returns, volatility, bar position, and cyclical time-of-day use information available at bar close $t$. | **CLEAN** | No defect. |
| **Rolling Window Leakage** | Rolling volatility windows (8 and 16 bars) strictly look back from $t$. | **CLEAN** | No defect. |
| **Normalization Leakage** | Feature scaling via `StandardScaler` is fitted strictly on `X_train_base` / `X_train_htf` and applied out-of-sample to validation and test folds. | **CLEAN** | No defect. |
| **Validation-to-Test Embargo** | In `evaluate_m23_walkforward`, `val_start = train_end + 2` enforces a 2-bar embargo. However, `test_start = val_end` has **0 embargo bars**. For target `O2O`, label $y_{\text{val}}[-1]$ references `open[val_end + 1]`, creating a 1-bar target overlap during validation threshold selection. | **LEAKAGE IDENTIFIED** | **Confirmed Defect A** |
| **O2C_1B Turnover Undercount** | `m23_research.py` computed `delta_s = abs(sig - prev_s)`. For consecutive long signals (`1 -> 1`), zero cost was charged, despite the return series omitting the close-to-open overnight gap. Physical reality requires closing at close and buying at open. | **UNDERCOUNT IDENTIFIED** | **Confirmed Defect B** |
| **O2C_2B Overlapping Periods** | Sequential compounding of 2-bar holding periods on adjacent bars double-counts returns during the overlapping bar. | **OVERLAP IDENTIFIED** | **Confirmed Defect C** |
| **Turnover Definition Ambiguity** | Metric `turnover += 1` counted orders rather than traded units ($|\Delta s|$). In long-short reversals, notional turnover is 2.0, not 1.0. | **AMBIGUITY IDENTIFIED** | **Confirmed Defect D** |
| **Cache Staleness Risk** | `benchmark_cache` is keyed on `(dataset_id, model_version, feature_config, target, eval_settings)`. Modifying model code without bumping `model_version` returns stale pre-fix results. | **STALENESS RISK IDENTIFIED** | **Confirmed Defect E** |

---

## 7. M23 REPRODUCTION TABLE (DATASET SHA-256 VERIFIED)

Using the exact persisted dataset `var/datasets/derived_nifty_15m_m23_bc7d31bceebf13a3.json` (SHA-256: `9154899b1e1898a68bf200d729a9a661ff8b13d4fd0d7e7c39e481bcbbf09b9d`), all 19 folds were independently reproduced:

### Target: `O2O` (Executable Next-Bar Open to Subsequent Open)
| Model | Accuracy | Balanced Acc | Brier Score | BSS vs Prior | 0 bps Net Return | 2 bps Net Return | 5 bps Net Return | 10 bps Net Return | Total Trades | Turnover |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Empirical Prior** | 0.4907 | 0.5000 | 0.2503 | +0.00% | -12.63% | -13.29% | -14.27% | -15.89% | 19 | 38 |
| **Majority Class** | 0.4907 | 0.5000 | 0.5093 | -103.48% | -12.63% | -13.29% | -14.27% | -15.89% | 19 | 38 |
| **Last Return Sign** | 0.4949 | 0.4939 | 0.5051 | -101.80% | -9.98% | -44.81% | -73.51% | -92.21% | 1,223 | 2,446 |
| **Logistic Regression** | 0.5034 | 0.4988 | 0.2564 | -2.44% | -5.00% | -21.79% | -41.58% | -64.08% | 486 | 972 |
| **Logistic Regression HTF** | 0.5059 | 0.4989 | 0.2541 | -1.52% | -1.86% | -19.71% | -40.60% | -64.06% | 502 | 1,004 |
| **Selective Entry HTF** | 0.5059 | 0.4989 | 0.2541 | -1.52% | -2.50% | -21.13% | -42.62% | -66.24% | 530 | 1,060 |
| **LightGBM** | 0.5011 | 0.4942 | 0.2589 | -3.44% | -11.33% | -28.21% | -47.71% | -69.17% | 528 | 1,056 |
| **XGBoost** | 0.4966 | 0.4903 | 0.2584 | -3.24% | -9.28% | -23.43% | -40.64% | -61.17% | 424 | 848 |
| **Amazon Chronos-2** | 0.5019 | 0.4950 | **0.2534** | **-1.24%** | -11.36% | -19.12% | **-29.51%** | **-43.95%** | **229** | **458** |
| **Google TimesFM 3.0** | *BLOCKED* | *BLOCKED* | *BLOCKED* | *BLOCKED* | *BLOCKED* | *BLOCKED* | *BLOCKED* | *BLOCKED* | N/A | N/A |

---

## 8. PER-FOLD PERFORMANCE & TRADING COSTS (LOGISTIC REGRESSION O2O)

To resolve the user's specific prompt instruction (*"Verify whether the previously reported Logistic Regression result of approximately -5.00% at zero cost and -21.79% at 2 bps is correct. Investigate the size of this difference rather than assuming that turnover alone explains it"*), all 19 folds were independently audited:

| Fold Index | Test Date Bounds | Net Return (0 bps) | Net Return (2 bps) | Net Return (5 bps) | Net Return (10 bps) | Turnover Units | Trades | Linear Cost Fee ($972 \times 0.02\%$) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Fold 1** | 2025-12-29 to 2026-01-12 | -1.95% | -2.69% | -3.79% | -5.58% | 38 | 19 | 0.76% |
| **Fold 2** | 2026-01-12 to 2026-01-28 | +1.02% | -0.18% | -1.97% | -4.89% | 60 | 30 | 1.20% |
| **Fold 3** | 2026-01-28 to 2026-02-10 | -0.09% | -0.29% | -0.58% | -1.07% | 10 | 5 | 0.20% |
| **Fold 4** | 2026-02-10 to 2026-02-24 | -3.13% | -4.74% | -7.09% | -10.87% | 84 | 42 | 1.68% |
| **Fold 5** | 2026-02-24 to 2026-03-11 | +0.00% | +0.00% | +0.00% | +0.00% | 0 | 0 | 0.00% |
| **Fold 6** | 2026-03-11 to 2026-03-25 | -0.03% | -0.15% | -0.32% | -0.62% | 6 | 3 | 0.12% |
| **Fold 7** | 2026-03-25 to 2026-04-13 | +0.93% | -1.23% | -4.39% | -9.43% | 108 | 54 | 2.16% |
| **Fold 8** | 2026-04-13 to 2026-04-28 | +0.33% | -0.63% | -2.04% | -4.36% | 48 | 24 | 0.96% |
| **Fold 9** | 2026-04-28 to 2026-05-13 | -2.22% | -4.27% | -7.26% | -11.99% | 106 | 53 | 2.12% |
| **Fold 10** | 2026-05-13 to 2026-05-27 | +1.82% | +0.40% | -1.71% | -5.13% | 70 | 35 | 1.40% |
| **Fold 11** | 2026-05-27 to 2026-06-11 | -2.02% | -4.77% | -8.74% | -14.96% | 142 | 71 | 2.84% |
| **Fold 12** | 2026-06-11 to 2026-06-25 | +1.04% | +0.23% | -0.96% | -2.93% | 40 | 20 | 0.80% |
| **Fold 13** | 2026-06-25 to 2026-07-10 | -0.41% | -2.85% | -6.37% | -11.96% | 124 | 62 | 2.48% |
| **Fold 14** | 2026-07-10 to 2026-07-24 | +0.00% | +0.00% | +0.00% | +0.00% | 0 | 0 | 0.00% |
| **Fold 15** | 2026-07-24 to 2026-08-07 | +0.37% | -1.34% | -3.85% | -7.89% | 86 | 43 | 1.72% |
| **Fold 16** | 2026-08-07 to 2026-08-21 | -0.01% | -0.29% | -0.71% | -1.40% | 14 | 7 | 0.28% |
| **Fold 17** | 2026-08-21 to 2026-09-04 | -0.06% | -0.22% | -0.46% | -0.86% | 8 | 4 | 0.16% |
| **Fold 18** | 2026-09-04 to 2026-09-21 | -0.04% | -0.08% | -0.14% | -0.23% | 2 | 1 | 0.04% |
| **Fold 19** | 2026-09-21 to 2026-10-06 | -0.52% | -1.04% | -1.80% | -3.07% | 26 | 13 | 0.52% |
| **Compounded Total** | **2025-12-29 to 2026-10-06** | **-5.003%** | **-21.792%** | **-41.580%** | **-64.080%** | **972** | **486** | **19.440%** |

### Mathematical Reconciliation:
- Linear sum of uncompounded fold returns:
  - $\sum R_{0\text{bps}} = -4.983\%$
  - $\sum R_{2\text{bps}} = -24.147\%$
  - Difference: $\mathbf{19.164\%}$
- Total turnover across all 19 folds: $972 \text{ units}$.
- Expected linear fee drag at 2 bps ($0.02\%$ per unit): $972 \times 0.0002 = \mathbf{19.440\%}$.
- The difference between linear fee drag ($19.440\%$) and simple return degradation ($19.164\%$) is merely $0.276\%$, attributable to the shrinking capital base during compounding.
- **Verdict**: The drop from -5.00% to -21.79% is **100% mathematically accounted for by turnover friction**. The strategy traded 486 times in 4,750 bars (a trade every 9.7 bars / 2.4 hours), completely eroding its gross return through trading frictions.

---

## 9. CONFIRMED BUGS, POTENTIAL RISKS, AND UNRESOLVED QUESTIONS

### Confirmed Bugs (Defects):
1. **Defect A: Validation-to-Test Embargo Omission**:
   - `test_start = val_end` allowed validation labels $y_{\text{val}}[-1]$ to reference prices in the test fold.
   - **Correction required**: Set `test_start = val_end + cfg.embargo_bars`.
2. **Defect B: Intraday Target `O2C_1B` Fee Exemption on Consecutive Longs**:
   - Consecutive signals (`1 -> 1`) were charged zero cost, despite exiting at bar close and re-entering at next open.
   - **Correction required**: Mandate inter-bar round-trip fees for `O2C_1B`.
3. **Defect C: Multi-Bar Target `O2C_2B` Return Double-Counting**:
   - Overlapping 2-bar returns were sequentially compounded as if they were non-overlapping single bars.
   - **Correction required**: Maintain separate concurrent trade queues or step by 2 bars.

### Potential Risks:
1. **Exchange Microstructure Drift**:
   - Simulated 2 bps one-way cost assumes zero market impact. On NIFTY index futures / ETFs, exchange turnover fees, STT, GST, and bid-ask spreads frequently exceed 2.5–3.5 bps round trip. High-turnover intraday models are unviable under realistic market frictions.
2. **Cache Poisoning on Code Updates**:
   - Database cache keys in `benchmark_cache` must incorporate an engine code hash or incremented version identifier (e.g., `m24-audited-v1`) to prevent stale cached entries from surviving code refactors.

### Unresolved Questions:
1. **Independent Secondary Provider Verification**:
   - Still pending. Groww remains the sole historical provider in the database. Cross-validation against a secondary provider (Zerodha Kite or Upstox) is mandatory before live deployment.

---

## 10. TEST COMMANDS & ACTUAL EXECUTION RESULTS

### 10.1 Independent Accounting Test Suite (`tests/test_m24_backtest_integrity.py`)
```bash
pytest tests/test_m24_backtest_integrity.py -v
```
**Output**:
```
tests/test_m24_backtest_integrity.py::test_scenario_1_long_entry_from_flat PASSED [  7%]
tests/test_m24_backtest_integrity.py::test_scenario_2_long_exit_to_flat PASSED [ 15%]
tests/test_m24_backtest_integrity.py::test_scenario_3_direct_reversal_long_to_short PASSED [ 23%]
tests/test_m24_backtest_integrity.py::test_scenario_4_repeated_unchanged_position PASSED [ 30%]
tests/test_m24_backtest_integrity.py::test_scenario_5_zero_return_market PASSED [ 38%]
tests/test_m24_backtest_integrity.py::test_scenario_6_whipsaw_positive_negative_returns PASSED [ 46%]
tests/test_m24_backtest_integrity.py::test_scenario_7_monotonic_cost_hurdles PASSED [ 53%]
tests/test_m24_backtest_integrity.py::test_scenario_8_session_boundaries_and_missing_bars PASSED [ 61%]
tests/test_m24_backtest_integrity.py::test_scenario_9_first_and_last_prediction_handling PASSED [ 69%]
tests/test_m24_backtest_integrity.py::test_scenario_10_o2c_1b_interbar_exit_mandate PASSED [ 76%]
tests/test_m24_backtest_integrity.py::test_target_execution_contracts PASSED [ 84%]
tests/test_m24_backtest_integrity.py::test_logistic_regression_turnover_cost_drag_audit PASSED [ 92%]
tests/test_m24_backtest_integrity.py::test_m24_safety_invariants PASSED  [100%]

======================== 13 passed, 1 warning in 0.84s =========================
```

### 10.2 Complete Backend Test Suite
```bash
pytest tests/
==================== 525 passed, 1 skipped, 1 warning in 95.59s ====================
```

### 10.3 Complete Frontend Test Suite
```bash
npm test (apps/web)
✔ 10 tests passed (102.85ms)
```

---

## 11. RECOMMENDATIONS FOR MILESTONE M25

1. **Implement Embargo Buffer on Validation-to-Test Boundary**:
   Update `evaluate_m23_walkforward` to set `test_start = val_end + cfg.embargo_bars` to completely eliminate the 1-bar target overlap.
2. **Apply Separate Trade-Leg Accounting for Multi-Bar Targets**:
   Replace sequential compounding for `O2C_1B` and `O2C_2B` with a portfolio trade manager that models individual position tickets, cash allocation, and exact entry/exit timestamps.
3. **Turnover Filtering & Minimum Holding Periods**:
   Because transaction costs dominate gross alpha (-19.44% drag on 972 transitions), M25 research should enforce a minimum holding period (e.g., 4 to 8 bars) or probability confidence thresholding (e.g. $P(\text{Up}) > 0.55$) to cut turnover by at least 60–75%.
4. **Cache Key Code Hashing**:
   Incorporate an engine code hash into `benchmark_cache` keys to prevent stale cache hits after algorithmic modifications.

---

## 12. MANDATORY SAFETY INVARIANTS CONFIRMATION

All five safety invariants remain strictly enforced as **`false`**:

```python
forecast_ready = false
real_market_data_verified = false
paper_approved = false
live_approved = false
live_broker_routing_enabled = false
```

- **Zero live broker orders were placed.**
- **No paper or live trading states were enabled.**
- **Zero broker order-placement calls were made.**
- **No changes to broker credentials were made.**
- **Independent cross-broker market data verification remains pending.**
