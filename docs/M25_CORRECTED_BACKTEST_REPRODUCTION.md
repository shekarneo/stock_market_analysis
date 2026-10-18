# M25: CORRECTED BACKTEST REPRODUCTION AND PRODUCTION FIX INTEGRATION REPORT

**Author:** Quantitative Research & Engineering Team  
**Milestone:** M25 Backtest Reproduction and Production Fix Integration  
**Date:** 2026-10-17  
**Branch:** `main`  
**Evaluation Dataset Artifact:** `var/datasets/derived_nifty_15m_m23_bc7d31bceebf13a3.json`  
**Dataset ID:** `bc7d31bceebf13a34a1c94daabd788d2b83ee1397f89060183ed7e68d2b55692`  
**Raw SHA-256:** `9154899b1e1898a68bf200d729a9a661ff8b13d4fd0d7e7c39e481bcbbf09b9d`  
**Corrected Benchmark Artifact:** `var/datasets/m25_benchmark_results.json`  
**Safety Classification:** `OFFLINE_RESEARCH_ONLY` (All 5 safety invariants strictly `FALSE`)

---

## 1. Executive Summary

Milestone M24 conducted an independent accounting audit and identified five architectural and execution defects in the initial M23 walk-forward evaluation framework:
1. **Missing Validation-to-Test Embargo:** Multi-step targets had a 1-to-2 bar overlap between validation targets and test fold prices.
2. **Target O2C_1B Transaction-Cost Undercounting:** Consecutive long signals skipped exit and re-entry costs despite being flat inter-bar.
3. **Target O2C_2B Overlapping Horizon Double-Counting:** 2-bar holding periods were sequentially compounded on a single equity pool, multiplying market returns during concurrent bars.
4. **Turnover Metric Ambiguity:** Traded position units ($\sum |\Delta s|$) were conflated with discrete order events.
5. **Benchmark Cache Invalidation Risk:** Cache keys lacked an explicit accounting version, allowing stale evaluation runs to be served after logic changes.
6. **Max Drawdown Signature Mismatch (Defect F, discovered during M25):** The legacy `compute_max_drawdown` function expected periodic returns but was passed cumulative equity values $\approx 1.0$, treating them as $+100\%$ returns and returning $0.0\%$ drawdown for every fold.

**Objective of M25:** Integrate confirmed corrections directly into the production walk-forward research pipeline (`apps/api/app/forecasting/m23_research.py`, `MarketDataStorageService`, and `history_routes.py`), re-run the complete benchmark across all 4 targets (`O2O`, `O2C_1B`, `O2C_2B`, `C2C`), reconstruct the out-of-sample equity curve for Logistic Regression with mathematical proof of nominal friction vs compounded return decay, and verify the full test suites.

### Key Audit & Reproduction Takeaways
- **Production Integration Verified:** All 5 corrections and the drawdown fix are integrated directly into production functions (`evaluate_m23_walkforward`, `run_m23_comprehensive_benchmark`, `compute_equity_curve_max_drawdown`, and `compute_benchmark_cache_key`). Isolated helpers were not relied upon.
- **Logistic Regression Reconciliation:** On `O2O`, Logistic Regression produced 974.0 turnover units across 19 walk-forward folds (487 completed round-trip trades over 4,750 test observations). Nominal friction at 2 bps was strictly $19.48\%$. Net compounded return was $-21.436\%$ (vs $-4.533\%$ gross at 0 bps). The apparent discrepancy between $19.48\%$ nominal fees and the $16.903\%$ compounded return difference is proven to be the mathematical result of deducting percentage fees from a progressively declining capital base.
- **O2C_1B Fee Enforcement Impact:** Enforcing round-trip costs ($2c$) on every active single-bar trade increased turnover for majority class from 14 units to 3,500 units, dropping its 2 bps return from $-6.385\%$ to $-53.426\%$. Logistic Regression 2 bps return dropped from $-18.722\%$ to $-30.429\%$ (1,818 turnover units, 909 trades).
- **O2C_2B Concurrent Queue Impact:** Replacing sequential compounding with a concurrent two-tranche queue (50% capital per tranche) capped portfolio exposure at 1.0, eliminated return double-counting, and produced realistic metrics: LR gross return moved from an artificial $-4.683\%$ to $-2.125\%$, and 2 bps net return settled at $-28.561\%$.
- **Test Integrity:** 546 backend tests passed, 0 failed, 1 skipped. 10 frontend tests passed, 0 failed.

---

## 2. Actual Implementation Files and Functions Inspected & Modified

| Component | File Path | Functions / Classes Modified | Description of Correction |
| :--- | :--- | :--- | :--- |
| **Walk-Forward Engine** | [`apps/api/app/forecasting/m23_research.py`](file:///home/neo/work/personal/stock_market_analysis/apps/api/app/forecasting/m23_research.py) | `evaluate_m23_walkforward` (lines 485–746) | Applied 2-bar embargo between validation and test (`test_start = val_end + cfg.embargo_bars`). |
| **Friction & Execution** | [`apps/api/app/forecasting/m23_research.py`](file:///home/neo/work/personal/stock_market_analysis/apps/api/app/forecasting/m23_research.py) | `evaluate_m23_walkforward` (lines 675–735) | Separate execution branches for `O2C_1B` (mandatory round-trip fees), `O2C_2B` (concurrent two-tranche queue), and `O2O` (continuous holding). Decoupled `turnover_units`, `order_count`, `trades`, and `total_fees_equity`. |
| **Drawdown Calculation** | [`apps/api/app/forecasting/m23_research.py`](file:///home/neo/work/personal/stock_market_analysis/apps/api/app/forecasting/m23_research.py) | `compute_equity_curve_max_drawdown` (lines 53–66) | Fixed signature mismatch; correctly evaluates peak-to-trough drawdowns on cumulative equity values. |
| **Benchmark Runner & Cache** | [`apps/api/app/forecasting/m23_research.py`](file:///home/neo/work/personal/stock_market_analysis/apps/api/app/forecasting/m23_research.py) | `run_m23_comprehensive_benchmark` (lines 870–930) | Upgraded `model_version="m25-audited-v1"` and added `"accounting_version": "m25-audited-v1"` to `eval_settings`. |
| **Cache Storage Engine** | [`apps/api/app/market/storage.py`](file:///home/neo/work/personal/stock_market_analysis/apps/api/app/market/storage.py) | `MarketDataStorageService.compute_benchmark_cache_key` | Evaluates deterministic SHA-256 incorporating dataset hash, model version, and `eval_settings` (with `accounting_version`). |
| **API Endpoint** | [`apps/api/app/market/history_routes.py`](file:///home/neo/work/personal/stock_market_analysis/apps/api/app/market/history_routes.py) | `POST /api/market/history/m23/benchmark` | Invokes `run_m23_comprehensive_benchmark` with audited production pipeline. |
| **Independent Accounting** | [`apps/api/app/forecasting/m24_accounting.py`](file:///home/neo/work/personal/stock_market_analysis/apps/api/app/forecasting/m24_accounting.py) | `simulate_independent_accounting` | Standalone reference simulator updated to call `compute_equity_curve_max_drawdown`. |
| **Regression Test Suite** | [`apps/api/tests/test_m25_corrected_reproduction.py`](file:///home/neo/work/personal/stock_market_analysis/apps/api/tests/test_m25_corrected_reproduction.py) | 8 comprehensive tests | Covers embargo isolation, O2C_1B fees, O2C_2B tranches, turnover vs orders, drawdown, cache versioning, LR reconciliation, and safety flags. |

---

## 3. Execution Semantics by Target Specification

| Specification | Target | Is Executable? | Signal / Prediction Availability | Earliest Entry Fill | Exit Price Fill | Holding Horizon | Inter-Bar State | Frictions & Turnover Rules |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **C2C** | Theoretical | **NO** | Bar $t$ close timestamp | `Close[t]` (SIMULATED) | `Close[t+1]` | 1 bar | Continuous | Theoretical baseline only. Cannot retroactively fill at `Close[t]`. |
| **O2O** | Executable | **YES** | Bar $t$ close timestamp | `Open[t+1]` | `Open[t+2]` | 1 bar | Continuous | Continuous holding allowed when $s_t=1, s_{t+1}=1$ ($\Delta s=0$). Costs apply strictly on position changes $|\Delta s| \times c$ and terminal liquidation. |
| **O2C_1B** | Executable | **YES** | Bar $t$ close timestamp | `Open[t+1]` | `Close[t+1]` | Intraday (1 bar) | Flat | Position MUST exit at bar close. Overnight holding forbidden. Every active bar incurs round-trip costs ($2c$), 2 turnover units, and 2 orders. |
| **O2C_2B** | Executable | **YES** | Bar $t$ close timestamp | `Open[t+1]` | `Close[t+2]` | Multi-bar swing (2 bars) | Overlapping | Executed via concurrent two-tranche queue (50% capital Tranche 0 on even $t$, 50% capital Tranche 1 on odd $t$). Sequential compounding without tranches is strictly BLOCKED. |

---

## 4. Phase 2 — Logistic Regression on O2O Equity Curve Reproduction

Using the exact persisted 1-year NIFTY 15m dataset (6,227 regular session candles, 6,209 aligned rows) across all 19 expanding folds (1,000 to 5,500 train, 250 val, 250 test, 2-bar embargo):

### Chronological Fold Breakdown (Logistic Regression on O2O)

| Fold | Train Window | Test Window | 0 bps Net Return | 2 bps Net Return | 5 bps Net Return | 10 bps Net Return | Turnover Units | Order Count | Closed Trades | Total Fees (2 bps Equity) | Worst Fold Drawdown |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | 2025-10-14 to 2025-12-12 | 2025-12-29 to 2026-01-12 | -1.319% | -2.067% | -3.177% | -5.000% | 38.0 | 38 | 19 | 0.00757 | -2.571% |
| **2** | 2025-10-14 to 2025-12-29 | 2026-01-12 to 2026-01-28 | +0.447% | -0.751% | -2.522% | -5.405% | 60.0 | 60 | 30 | 0.01190 | -1.218% |
| **3** | 2025-10-14 to 2026-01-12 | 2026-01-28 to 2026-02-10 | -0.093% | -0.293% | -0.591% | -1.088% | 10.0 | 10 | 5 | 0.00200 | -0.329% |
| **4** | 2025-10-14 to 2026-01-28 | 2026-02-10 to 2026-02-24 | -3.128% | -4.743% | -7.114% | -10.938% | 84.0 | 84 | 42 | 0.01644 | -4.743% |
| **5** | 2025-10-14 to 2026-02-10 | 2026-02-24 to 2026-03-11 | 0.000% | 0.000% | 0.000% | 0.000% | 0.0 | 0 | 0 | 0.00000 | 0.000% |
| **6** | 2025-10-14 to 2026-02-24 | 2026-03-11 to 2026-03-25 | -0.029% | -0.149% | -0.329% | -0.628% | 6.0 | 6 | 3 | 0.00120 | -0.158% |
| **7** | 2025-10-14 to 2026-03-11 | 2026-03-25 to 2026-04-13 | +0.926% | -1.231% | -4.381% | -9.411% | 108.0 | 108 | 54 | 0.02131 | -2.148% |
| **8** | 2025-10-14 to 2026-03-25 | 2026-04-13 to 2026-04-28 | +0.325% | -0.634% | -2.055% | -4.379% | 48.0 | 48 | 24 | 0.00957 | -0.985% |
| **9** | 2025-10-14 to 2026-04-13 | 2026-04-28 to 2026-05-13 | -2.301% | -4.351% | -7.346% | -12.133% | 106.0 | 106 | 53 | 0.02086 | -4.502% |
| **10** | 2025-10-14 to 2026-04-28 | 2026-05-13 to 2026-05-27 | +1.976% | +0.558% | -1.532% | -4.921% | 70.0 | 70 | 35 | 0.01407 | -0.842% |
| **11** | 2025-10-14 to 2026-05-13 | 2026-05-27 to 2026-06-11 | -1.980% | -4.764% | -8.792% | -15.134% | 144.0 | 144 | 72 | 0.02800 | -5.735% |
| **12** | 2025-10-14 to 2026-05-27 | 2026-06-11 to 2026-06-25 | +1.036% | +0.231% | -0.965% | -2.927% | 40.0 | 40 | 20 | 0.00800 | -0.724% |
| **13** | 2025-10-14 to 2026-06-11 | 2026-06-25 to 2026-07-10 | -0.104% | -2.551% | -6.110% | -11.759% | 124.0 | 124 | 62 | 0.02448 | -3.120% |
| **14** | 2025-10-14 to 2026-06-25 | 2026-07-10 to 2026-07-24 | 0.000% | 0.000% | 0.000% | 0.000% | 0.0 | 0 | 0 | 0.00000 | 0.000% |
| **15** | 2025-10-14 to 2026-07-10 | 2026-07-24 to 2026-08-07 | +0.367% | -1.345% | -3.859% | -7.908% | 86.0 | 86 | 43 | 0.01718 | -1.821% |
| **16** | 2025-10-14 to 2026-07-24 | 2026-08-07 to 2026-08-21 | -0.008% | -0.288% | -0.706% | -1.399% | 14.0 | 14 | 7 | 0.00280 | -0.320% |
| **17** | 2025-10-14 to 2026-08-07 | 2026-08-21 to 2026-09-04 | -0.058% | -0.218% | -0.457% | -0.855% | 8.0 | 8 | 4 | 0.00160 | -0.252% |
| **18** | 2025-10-14 to 2026-08-21 | 2026-09-04 to 2026-09-21 | -0.036% | -0.076% | -0.136% | -0.236% | 2.0 | 2 | 1 | 0.00040 | -0.081% |
| **19** | 2025-10-14 to 2026-09-04 | 2026-09-21 to 2026-10-06 | -0.522% | -1.038% | -1.807% | -3.077% | 26.0 | 26 | 13 | 0.00517 | -1.241% |
| **Total / Agg** | **19 Folds Expanding** | **4,750 Test Observations** | **-4.533%** | **-21.436%** | **-41.347%** | **-63.974%** | **974.0** | **974** | **487** | **0.19255** | **-5.735%** |

---

## 5. Mathematical Proof: Nominal Fees vs Difference in Compounded Returns

A central question raised in M24 was why the previously reported 2 bps result for Logistic Regression on O2O was approximately $-21.79\%$ compared to $-5.00\%$ at 0 bps: a raw arithmetic difference of $16.79\%$, while 972 turnover transitions at 2 bps represented a linear cost drag of $972 \times 0.02\% = 19.44\%$.

In M25 with the corrected embargo:
- **Turnover Units:** $974.0$
- **Order Count:** $974$
- **Completed Trades:** $487$
- **Nominal Friction (Linear Sum):** $974.0 \times 0.0002 \times 100\% = 19.480\%$
- **Net Compounded Return at 0 bps ($R_{0}$):** $-4.533\%$ (Terminal Wealth $W_{0} = 0.95467$)
- **Net Compounded Return at 2 bps ($R_{2}$):** $-21.436\%$ (Terminal Wealth $W_{2} = 0.78564$)
- **Arithmetic Difference ($R_{0} - R_{2}$):** $16.903\%$

### The Mathematical Proof
Why is the arithmetic difference ($16.903\%$) strictly less than the nominal fees ($19.480\%$)?

1. **Path-Dependent Capital Base Degradation:**
   Transaction costs are charged as a percentage of current capital at execution time:
   $$\text{Fee}_{t} = |\Delta s_{t}| \times c \times W_{t}$$
   Because the underlying strategy is unprofitable ($R_0 = -4.533\%$), the average capital base $W_t$ over time is strictly less than initial capital $W_0 = 1.0$.
   Summing the actual fees deducted in units of initial capital:
   $$\sum_{t=1}^{T} \text{Fee}_{t} = 0.19255 \text{ (or } 19.255\% \text{ of initial wealth)}$$
   This alone explains why nominal linear fees on initial wealth ($19.48\%$) overestimate the actual currency extracted by fees ($19.255\%$).

2. **Compounding Interaction of Costs on Declining Capital:**
   At each step, net capital transition is:
   $$W_{t} = W_{t-1} \cdot (1 + r_{t}^{\text{gross}} - f_{t}) = W_{t-1} \cdot (1 + r_{t}^{\text{gross}}) \left(1 - \frac{f_{t}}{1 + r_{t}^{\text{gross}}}\right)$$
   Over the full horizon, terminal wealth under costs relative to terminal wealth without costs is:
   $$\frac{W_{2}}{W_{0}} = \frac{1 - 0.21436}{1 - 0.04533} = \frac{0.78564}{0.95467} = 0.82294 \implies -17.706\% \text{ relative drag}$$
   The difference in percentage points is:
   $$R_0 - R_2 = (W_0 - 1) - (W_2 - 1) = W_0 - W_2 = W_0 \cdot \left(1 - \frac{W_2}{W_0}\right) = 0.95467 \times 0.17706 = 16.903\%$$

**Conclusion:** Equating nominal turnover fees to the difference in compounded returns is mathematically invalid without multiplying by the degraded terminal wealth base ($0.95467 \times 17.706\% = 16.903\%$). Turnover alone fully explains the performance drop.

---

## 6. Phase 4 — Backtest Leakage and Embargo Audit

| Audit Area | Investigation Method | Defect Status | Resolution & Verification |
| :--- | :--- | :--- | :--- |
| **Validation-to-Test Embargo** | Verified fold bounds in `evaluate_m23_walkforward` across expanding windows. | **CONFIRMED & FIXED (Defect A)** | Implemented `test_start = val_end + cfg.embargo_bars`. Regression test [`test_validation_to_test_embargo_strictly_prevents_label_overlap`](file:///home/neo/work/personal/stock_market_analysis/apps/api/tests/test_m25_corrected_reproduction.py#L32-L61) proves validation targets cannot reference test candle prices. |
| **Target O2C_1B Frictions** | Verified handling of consecutive $1 \to 1$ signals. | **CONFIRMED & FIXED (Defect B)** | Enforced mandatory inter-bar exits and $2c$ round-trip fees on every active single-bar trade. Regression test [`test_o2c_1b_enforces_interbar_exit_and_charges_roundtrip_fees`](file:///home/neo/work/personal/stock_market_analysis/apps/api/tests/test_m25_corrected_reproduction.py#L64-L95) confirms turnover is $2 \times N$. |
| **Target O2C_2B Overlap** | Verified multi-bar swing trade return compounding. | **CONFIRMED & FIXED (Defect C)** | Implemented concurrent two-tranche queue (50% capital per tranche). Sequential compounding without tranches is permanently marked BLOCKED. Regression test [`test_o2c_2b_concurrent_two_tranche_queue_eliminates_double_counting`](file:///home/neo/work/personal/stock_market_analysis/apps/api/tests/test_m25_corrected_reproduction.py#L98-L113) verifies portfolio exposure $\le 1.0$. |
| **Turnover vs Orders** | Audited variable tracking in fold loop. | **CONFIRMED & FIXED (Defect D)** | Separated `turnover_units` ($\sum |\Delta s|$) from `order_count` ($\sum \mathbf{1}_{\Delta s \ne 0}$). Regression test [`test_turnover_units_vs_order_count_distinction`](file:///home/neo/work/personal/stock_market_analysis/apps/api/tests/test_m25_corrected_reproduction.py#L116-L125) passes. |
| **Benchmark Cache Invalidation** | Verified `compute_benchmark_cache_key`. | **CONFIRMED & FIXED (Defect E)** | Added `"accounting_version": "m25-audited-v1"` to `eval_settings` and bumped `model_version="m25-audited-v1"`. Regression test [`test_benchmark_cache_key_invalidation_on_accounting_version_change`](file:///home/neo/work/personal/stock_market_analysis/apps/api/tests/test_m25_corrected_reproduction.py#L137-L179) proves cache misses on version change. |
| **Max Drawdown Signature** | Audited `compute_max_drawdown` usage on equity curves. | **CONFIRMED & FIXED (Defect F)** | Created `compute_equity_curve_max_drawdown` operating directly on cumulative equity values. Regression test [`test_drawdown_signature_fix_calculates_correct_trough`](file:///home/neo/work/personal/stock_market_analysis/apps/api/tests/test_m25_corrected_reproduction.py#L128-L135) passes. |
| **Feature Extraction Point-in-Time** | Audited `extract_m23_expanded_features`. | **CLEAN (PASS)** | Features (returns, volatility, spreads, HTF 1H context, cyclic time) use strictly indices $\le t$. Windows are capped at 64 bars looking backward. |
| **Normalization Leakage** | Audited feature scaling in walk-forward loop. | **CLEAN (PASS)** | `StandardScaler` is fitted strictly on `X_train`. Validation and test are transformed out-of-sample. |
| **Threshold Tuning Leakage** | Audited Selective Entry HTF candidate search. | **CLEAN (PASS)** | `best_tau` is optimized strictly on `val_rows`. Test inference uses frozen `best_tau`. |

---

## 7. Phase 6 — M23 vs M25 Comprehensive Reproduction Tables

Historical reports are preserved in `var/datasets/m23_benchmark_results.json`. The corrected audited results are persisted in `var/datasets/m25_benchmark_results.json`.

### Table 1: Target O2O (Single-Bar Open-to-Open Executable Fill)

| Model Architecture | M23 Accuracy | M25 Accuracy | M23 Brier Score | M25 Brier Score | M23 0 bps Net Return | M25 0 bps Net Return | M23 2 bps Net Return | M25 2 bps Net Return | M23 Turnover | M25 Turnover Units | M25 Order Count | M25 Worst Fold Drawdown |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Empirical Prior** | 0.4907 | 0.4912 | 0.2503 | 0.2503 | -12.629% | -12.505% | -13.294% | -13.165% | 38 | 38.0 | 38 | -7.407% |
| **Majority Class** | 0.4907 | 0.4912 | 0.5093 | 0.5088 | -12.629% | -12.505% | -13.294% | -13.165% | 38 | 38.0 | 38 | -7.407% |
| **Last Return Sign** | 0.4949 | 0.4949 | 0.5051 | 0.5051 | -9.982% | -9.912% | -44.812% | -44.705% | 2,446 | 2,440.0 | 2,440 | -6.839% |
| **Logistic Regression** | 0.5034 | 0.5042 | 0.2564 | 0.2564 | -5.003% | -4.533% | -21.792% | -21.436% | 972 | 974.0 | 974 | -5.735% |
| **Logistic Regression + HTF** | 0.5059 | 0.5065 | 0.2541 | 0.2541 | -1.860% | -1.980% | -19.713% | -19.847% | 1,004 | 1,006.0 | 1,006 | -5.321% |
| **Selective Entry HTF** | 0.5059 | 0.5065 | 0.2541 | 0.2541 | -2.502% | -2.605% | -21.128% | -21.244% | 1,060 | 1,062.0 | 1,062 | -5.589% |
| **LightGBM Trees** | 0.5011 | 0.5011 | 0.2589 | 0.2589 | -11.334% | -10.781% | -28.215% | -27.796% | 1,056 | 1,058.0 | 1,058 | -7.908% |
| **XGBoost Trees** | 0.4966 | 0.4964 | 0.2584 | 0.2584 | -9.280% | -9.465% | -23.434% | -23.561% | 848 | 846.0 | 846 | -5.215% |
| **Amazon Chronos-2** | 0.5085 | 0.5085 | 0.2524 | 0.2524 | -2.314% | -2.314% | -6.741% | -6.741% | 229 | 229.0 | 229 | -3.118% |
| **Google TimesFM 3.0** | BLOCKED | BLOCKED | BLOCKED | BLOCKED | BLOCKED | BLOCKED | BLOCKED | BLOCKED | N/A | N/A | N/A | N/A |

---

### Table 2: Target O2C_1B (Intraday Single-Bar Open-to-Close Fill)

*Key Correction:* Enforces mandatory inter-bar exits and $2c$ round-trip fees for active bars.

| Model Architecture | M23 Accuracy | M25 Accuracy | M23 0 bps Return | M25 0 bps Return | M23 2 bps Return | M25 2 bps Return | M23 Turnover | M25 Turnover Units | M25 Order Count | M25 Trades | Discrepancy Cause |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Empirical Prior** | 0.5053 | 0.5048 | -6.122% | -6.197% | -6.385% | -53.426% | 14 | 3,500.0 | 3,500 | 1,750 | Corrected fee undercounting: previously skipped close-to-open exit/entry fees. |
| **Majority Class** | 0.5053 | 0.5048 | -6.122% | -6.197% | -6.385% | -53.426% | 14 | 3,500.0 | 3,500 | 1,750 | Consecutive 1s now pay round-trip intraday commissions. |
| **Last Return Sign** | 0.4905 | 0.4905 | -13.786% | -13.721% | -47.143% | -66.304% | 2,446 | 4,700.0 | 4,700 | 2,350 | Churning intraday entries/exits incurs massive round-trip friction. |
| **Logistic Regression** | 0.5164 | 0.5168 | -0.287% | +0.084% | -18.722% | -30.429% | 1,022 | 1,818.0 | 1,818 | 909 | 909 completed trades $\times 2c$ round-trip friction. |
| **Logistic Regression + HTF** | 0.5131 | 0.5126 | -2.370% | -2.891% | -21.497% | -43.979% | 1,090 | 2,750.0 | 2,750 | 1,375 | Corrected round-trip fee application across 1,375 active bars. |
| **Selective Entry HTF** | 0.5131 | 0.5126 | -0.301% | -0.820% | -16.226% | -34.839% | 870 | 2,100.0 | 2,100 | 1,050 | Corrected round-trip fee application across 1,050 active bars. |
| **LightGBM Trees** | 0.5095 | 0.5091 | -7.599% | -7.565% | -22.234% | -44.613% | 862 | 2,560.0 | 2,560 | 1,280 | Corrected round-trip fee application across 1,280 active bars. |
| **XGBoost Trees** | 0.5061 | 0.5061 | -10.761% | -9.886% | -24.503% | -49.551% | 836 | 2,900.0 | 2,900 | 1,450 | Corrected round-trip fee application across 1,450 active bars. |

---

### Table 3: Target O2C_2B (Multi-Bar Swing Open-to-Close Fill)

*Key Correction:* Concurrent two-tranche queue (50% Tranche 0, 50% Tranche 1) eliminates sequential double-counting of overlapping bars.

| Model Architecture | M23 Accuracy | M25 Accuracy | M23 0 bps Return | M25 0 bps Return | M23 2 bps Return | M25 2 bps Return | M23 Turnover | M25 Turnover Units | M25 Order Count | Discrepancy Cause |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Empirical Prior** | 0.4998 | 0.5002 | -15.656% | -8.135% | -15.891% | -35.269% | 14 | 1,750.0 | 3,500 | Eliminated return double-counting; properly weighted across tranches. |
| **Majority Class** | 0.4998 | 0.5002 | -15.656% | -8.135% | -15.891% | -35.269% | 14 | 1,750.0 | 3,500 | 50% capital allocated per tranche; full transaction costs charged. |
| **Last Return Sign** | 0.4956 | 0.4956 | -19.224% | -9.906% | -50.481% | -43.702% | 2,446 | 2,350.0 | 4,700 | Overlapping returns decoupled; tranche compounding enforced. |
| **Logistic Regression** | 0.5048 | 0.5044 | -4.683% | -2.125% | -14.269% | -28.561% | 530 | 1,574.0 | 3,148 | Eliminated return compounding distortion and charged roundtrip per leg. |
| **Logistic Regression + HTF** | 0.5072 | 0.5067 | -6.963% | -3.303% | -16.554% | -27.462% | 544 | 1,437.0 | 2,874 | Realistic portfolio tranche modeling. |
| **Selective Entry HTF** | 0.5072 | 0.5067 | -7.030% | -3.275% | -16.446% | -27.048% | 534 | 1,410.0 | 2,820 | Realistic portfolio tranche modeling. |
| **LightGBM Trees** | 0.5029 | 0.5025 | -17.723% | -8.816% | -31.281% | -35.638% | 900 | 1,741.0 | 3,482 | Realistic portfolio tranche modeling. |
| **XGBoost Trees** | 0.5084 | 0.5080 | -6.083% | -3.302% | -20.674% | -26.615% | 844 | 1,379.0 | 2,758 | Realistic portfolio tranche modeling. |

---

### Table 4: Target C2C (Theoretical Research Baseline)

*Key Note:* Classified strictly as non-executable research benchmark.

| Model Architecture | M23 Accuracy | M25 Accuracy | M23 0 bps Return | M25 0 bps Return | M23 2 bps Return | M25 2 bps Return | M25 Turnover Units | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Empirical Prior** | 0.4945 | 0.4949 | -12.629% | -12.501% | -13.292% | -13.167% | 38.0 | THEORETICAL_BENCHMARK |
| **Majority Class** | 0.4945 | 0.4949 | -12.629% | -12.501% | -13.292% | -13.167% | 38.0 | THEORETICAL_BENCHMARK |
| **Last Return Sign** | 0.4882 | 0.4882 | -15.907% | -15.839% | -48.444% | -48.341% | 2,440.0 | THEORETICAL_BENCHMARK |
| **Logistic Regression** | 0.5023 | 0.5029 | -2.899% | -2.470% | -20.913% | -20.596% | 1,028.0 | THEORETICAL_BENCHMARK |
| **Logistic Regression + HTF** | 0.5032 | 0.5029 | -5.554% | -6.034% | -24.146% | -24.502% | 1,094.0 | THEORETICAL_BENCHMARK |
| **Selective Entry HTF** | 0.5032 | 0.5029 | -7.136% | -7.722% | -24.848% | -25.293% | 1,056.0 | THEORETICAL_BENCHMARK |
| **LightGBM Trees** | 0.5051 | 0.5042 | -2.048% | -2.418% | -16.733% | -17.050% | 812.0 | THEORETICAL_BENCHMARK |
| **XGBoost Trees** | 0.4994 | 0.4989 | -8.636% | -9.381% | -23.046% | -23.705% | 860.0 | THEORETICAL_BENCHMARK |

---

## 8. Defect Log, Root Causes, and Permanent Resolutions

### Defect A: Missing Validation-to-Test Embargo
- **Status:** CONFIRMED & RESOLVED.
- **Root Cause:** In `evaluate_m23_walkforward`, `test_start = val_end` had 0 embargo bars while train-to-val had 2 embargo bars. For 2-step targets (`O2O`, `O2C_2B`), label $y_{\text{val}}[-1]$ relies on `open[val_end + 1]`, creating a 1-bar target overlap with the test fold.
- **Resolution:** Updated `test_start = val_end + cfg.embargo_bars`.
- **Regression Test:** `tests/test_m25_corrected_reproduction.py::test_validation_to_test_embargo_strictly_prevents_label_overlap` (PASSED).

### Defect B: O2C_1B Fee Undercounting
- **Status:** CONFIRMED & RESOLVED.
- **Root Cause:** By contract, `O2C_1B` exits at close of bar $t+1$. Capital is flat until open of bar $t+2$. Consecutive signals ($1 \to 1$) were treated as continuous holding with $\Delta s = 0$, charging zero fees and ignoring overnight market risk.
- **Resolution:** Mandated round-trip friction ($2c$), 2 turnover units, and 2 order counts for every active bar.
- **Regression Test:** `tests/test_m25_corrected_reproduction.py::test_o2c_1b_enforces_interbar_exit_and_charges_roundtrip_fees` (PASSED).

### Defect C: O2C_2B Overlapping Return Double-Counting
- **Status:** CONFIRMED & RESOLVED.
- **Root Cause:** Trades spanned 2 bars ($[Open[t+1], Close[t+2]]$ and $[Open[t+2], Close[t+3]]$). Sequential single-pool compounding multiplied the overlapping return during $[Open[t+2], Close[t+2]]$ twice.
- **Resolution:** Replaced sequential compounding with an explicit concurrent two-tranche queue (50% Tranche 0, 50% Tranche 1).
- **Regression Test:** `tests/test_m25_corrected_reproduction.py::test_o2c_2b_concurrent_two_tranche_queue_eliminates_double_counting` (PASSED).

### Defect D: Conflation of Orders and Turnover Units
- **Status:** CONFIRMED & RESOLVED.
- **Root Cause:** `turnover += 1` incremented on non-zero transitions, conflating order execution count with traded position volume. Direct reversals ($+1 \to -1$) were undercounted as 1 unit instead of 2.
- **Resolution:** Decoupled `turnover_units = sum(|delta_s|)` from `order_count = count(delta_s != 0)`.
- **Regression Test:** `tests/test_m25_corrected_reproduction.py::test_turnover_units_vs_order_count_distinction` (PASSED).

### Defect E: Benchmark Cache Staleness Risk
- **Status:** CONFIRMED & RESOLVED.
- **Root Cause:** Cache keying hashed evaluation parameters but omitted an explicit accounting implementation version. Changes to backtest accounting returned stale cache hits.
- **Resolution:** Added `"accounting_version": "m25-audited-v1"` to `eval_settings` and bumped `model_version="m25-audited-v1"`.
- **Regression Test:** `tests/test_m25_corrected_reproduction.py::test_benchmark_cache_key_invalidation_on_accounting_version_change` (PASSED).

### Defect F: Max Drawdown Signature Mismatch
- **Status:** CONFIRMED & RESOLVED.
- **Root Cause:** `compute_max_drawdown` in `m20_research.py` was written to take periodic returns `[r1, r2, ...]` and compound them. `m23_research.py` passed `curve` (cumulative equity `[1.0, 1.019, ...]`), treating $1.0$ as a $+100\%$ return and causing monotonically ballooning equity, yielding $0.0\%$ drawdown for every fold.
- **Resolution:** Created `compute_equity_curve_max_drawdown` in `m23_research.py` operating directly on cumulative equity curves.
- **Regression Test:** `tests/test_m25_corrected_reproduction.py::test_drawdown_signature_fix_calculates_correct_trough` (PASSED).

---

## 9. Test Commands and Actual Test Results

### 1. Focused M25 Regression Test Suite
**Command:**
```bash
/home/neo/work/personal/stock_market_analysis/.venv/bin/pytest tests/test_m25_corrected_reproduction.py
```
**Result:**
```
======================== 8 passed, 1 warning in 36.47s =========================
```

### 2. Full Backend Test Suite
**Command:**
```bash
/home/neo/work/personal/stock_market_analysis/.venv/bin/pytest tests/
```
**Result:**
```
============ 546 passed, 1 skipped, 1 warning in 140.12s (0:02:20) =============
```
*Note on skipped test:* 1 test in `test_m19_groww_validation.py` is conditionally skipped when live broker API credentials are intentionally unconfigured, strictly adhering to safety invariants.

### 3. Frontend Web Test Suite
**Command:**
```bash
/home/neo/.nvm/versions/node/v22.20.0/bin/node --test app/research/*.test.mjs app/settings/integrations/*.test.mjs
```
**Result:**
```
✔ null and missing values stay distinct from zero (0.551109ms)
✔ observations use the payload class and do not invent a price (0.189046ms)
✔ intent lookup rejects an empty or spaced id before a request (0.218248ms)
✔ a missing kill switch is not labelled off (0.488525ms)
✔ connection success is separate from integration enablement (0.551986ms)
✔ token and historical badges do not treat unknown as verified (0.149713ms)
✔ saved secrets stay masked and empty in the draft (0.631433ms)
✔ opening configuration does not save until an explicit confirmed action (0.594316ms)
✔ diagnostic stays blocked until the integration is enabled and the request is confirmed (0.382375ms)
✔ safety flags stay off unless the server says otherwise (0.114214ms)
ℹ tests 10, pass 10, fail 0, duration_ms 46.18
```

---

## 10. Safety Invariants Verification

All five safety invariants remain strictly enforced as `FALSE` in application code, API responses, and database records:
```python
forecast_ready = False
real_market_data_verified = False
paper_approved = False
live_approved = False
live_broker_routing_enabled = False
```
- No live broker orders placed.
- No paper trading orders placed.
- No broker routing calls made.
- No broker credentials modified or decrypted.
- External market data verification remains pending.

---

## 11. Recommendations for Milestone M26

1. **Turnover-Throttled Strategies:** Directional 15-minute forecasting on NIFTY 50 produces marginal predictive edge ($50.1\%$ to $50.6\%$ accuracy). High turnover (e.g. 974 transitions) destroys capital via transaction friction ($-19.48\%$ nominal fee drag). M26 must implement turnover-throttling filters:
   - Minimum holding duration (e.g., 4 to 8 bars).
   - Dynamic thresholding ($P(\text{Up}) > 0.55$ or $P(\text{Up}) < 0.45$).
   - Deadband hysteresis bands preventing single-bar whipsaws.
2. **Selective Foundation Model Ensemble:** Amazon Chronos-2 demonstrates superior probability calibration (Brier 0.2524) and significantly lower turnover (229 units vs 974 units for Logistic Regression), resulting in the lowest net cost drag ($-6.74\%$ at 2 bps vs $-21.44\%$). A hybrid architecture combining Chronos-2 zero-shot embeddings with regularized GBDT models should be benchmarked.
3. **Secondary Market Data Provider Ingestion:** Ingest historical candles from a secondary independent source (Zerodha Kite or Upstox) to enable independent cross-validation and finally satisfy the verification requirement (`real_market_data_verified`).
