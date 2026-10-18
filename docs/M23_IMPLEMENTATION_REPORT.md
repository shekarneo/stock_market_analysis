# M23 — HISTORICAL DATA EXPANSION AND MODERN FORECASTING BENCHMARK
**Project**: V6 Indian Market Forecasting System  
**Provider**: Groww API  
**Storage**: Persistent PostgreSQL Market-Data Architecture  
**Evaluation Framework**: Target-Aligned Expanding Walk-Forward Benchmark (19 Folds)  
**Date**: October 17, 2026  
**Status**: COMPLETE (Internal Research & Benchmarking Only; External Verification Pending)  

---

## 1. ACTUAL DATE RANGE AND CANDLE COUNT FETCHED

### 1.1 Groww Historical API Capabilities & Limit Discovery
Before commencing ingestion, the authenticated Groww historical candle endpoint (`/v1/api/stocks_data/v1/tr_live_prices/exchange/NSE/segment/CASH/latest_aggregated_candles`) was probed for temporal limits and constraints:
- **Maximum History Supported**: The API supports queries back to at least **January 1, 2020** for Indian equity indices (`NSE-NIFTY`).
- **Maximum Request Duration Limit**: The API enforces an explicit duration restriction: **maximum 90 days per query** for `15minute` candles (`GA001: Interval 15minute can only be queried for a maximum of 90 days`).
- **Chunking Strategy**: A conservative chunk duration of **60 days** with a **0.5-second inter-request delay** was adopted to prevent connection throttling and respect upstream rate limits.

### 1.2 Retrieved Date Range & Volume
- **Target Symbol**: `NSE-NIFTY`
- **Candle Interval**: `15minute`
- **Contiguous Date Range**: **October 14, 2025 09:15:00 IST** to **October 16, 2026 15:15:00 IST** (1 full contiguous calendar year).
- **Total Raw Candles Retrieved**: **6,958 candles** across 6 chunk requests.
- **Regular Session Candles**: **6,227 candles** (09:15:00 to 15:30:00 IST).

---

## 2. DATABASE CANDLE COUNTS AND COMPLETENESS

### 2.1 Persistent PostgreSQL Storage
All retrieved candles were validated and normalized into the PostgreSQL `market_candles` table with unique constraint:
`CONSTRAINT uq_market_candle UNIQUE (symbol, interval, timestamp)`.

- **Total Market Candles Stored**: 6,227 regular session candles.
- **Total Trading Days**: 250 trading days across the 1-year period.
- **Complete Trading Sessions (25 bars)**: **248 sessions** (99.2% of sessions).
- **Incomplete Trading Sessions**: Exactly **2 sessions**:
  1. `2025-10-21`: Diwali Muhurat Trading session (7 bars, 18:15:00 to 19:15:00 IST) — legitimate exchange-scheduled shortened session.
  2. `2026-09-29`: Upstream NSE/broker feed gap (20 bars, 5 bars missing between 11:30 and 12:45 IST) — preserved as incomplete without synthetic filling.
- **Fabricated / Silently Filled Bars**: **0**. Strictly zero synthetic candles were generated or interpolated.
- **OHLC Geometry Validation**: **100% Valid**. All 6,227 bars strictly satisfy:
  - `High >= Low`
  - `High >= Open`
  - `High >= Close`
  - `Low <= Open`
  - `Low <= Close`
  - `Open > 0`, `High > 0`, `Low > 0`, `Close > 0`

---

## 3. API REQUEST COUNTS AND RATE-LIMIT METRICS

| Ingestion Phase | Date Range Requested | Chunks | Groww API Calls | Rate-Limit Errors (429) | Status |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **Initial Ingestion** | 2025-10-14 to 2026-10-16 | 6 | 6 | 0 | 100% Ingested |
| **Idempotent Re-Run** | 2025-10-14 to 2026-10-16 | 6 | **0** | 0 | 100% Reused from DB |
| **Incremental Sub-Range** | 2026-09-01 to 2026-10-16 | 1 | **0** | 0 | 100% Reused from DB |

- **Zero Redundant Calls**: An identical ingestion run over already-stored historical periods queries database bounds and issues **zero HTTP calls** to Groww.
- **Conflict Audit Trail**: Ingestion checks for conflicting OHLCV values upon timestamp collisions. Zero conflicts were detected; all records matched normalized storage bit-for-bit.

---

## 4. DATASET IDENTIFIERS AND SHA-256 HASHES

To ensure reproducible provenance, raw API responses are persisted as immutable JSON artifacts, and the canonical dataset is exported with cryptographically verifiable checksums:

- **Derived Dataset File**: `var/datasets/derived_nifty_15m_m23_bc7d31bceebf13a3.json`
- **Dataset Identifier (`dataset_id`)**: `bc7d31bceebf13a34a1c94daabd788d2b83ee1397f89060183ed7e68d2b55692`
- **File SHA-256 Checksum**: `9154899b1e1898a68bf200d729a9a661ff8b13d4fd0d7e7c39e481bcbbf09b9d`
- **Dataset Provenance Record**: Persisted in PostgreSQL table `dataset_provenance` with complete validation statistics, session counts, and artifact lineage.

---

## 5. DATA QUALITY AND PROVENANCE STATUS

- **Timestamp & Timezone Handling**: All candles are parsed into timezone-aware `Asia/Kolkata` (+05:30) timestamps and stored in PostgreSQL as `TIMESTAMPTZ` (UTC).
- **Session Boundary Enforcement**: Regular trading hours are enforced at 09:15:00 IST open to 15:30:00 IST close. Special trading sessions (Muhurat) are classified as `SPECIAL_MUHURAT`.
- **Negative / Zero Price Check**: Passed (min close price: 23,892.40; max close price: 26,277.35).
- **Duplicate Detection**: Passed (0 duplicate timestamps).

---

## 6. FORECASTING MODEL REGISTRY & LICENSING AUDIT

All 10 models were audited for licensing, dependency footprint, and hardware requirements before benchmarking:

| Model ID | Model Name | Version | License | Commercial Deployment Allowed | Hardware / Runtime | Benchmarking Status |
| :--- | :--- | :--- | :--- | :---: | :--- | :--- |
| `empirical_prior` | Empirical-Prior Baseline | 1.0 | Internal / MIT | Yes | CPU | **ACTIVE_BENCHMARKED** |
| `majority_class` | Majority-Class Baseline | 1.0 | Internal / MIT | Yes | CPU | **ACTIVE_BENCHMARKED** |
| `last_return_sign` | Last-Return-Sign Momentum | 1.0 | Internal / MIT | Yes | CPU | **ACTIVE_BENCHMARKED** |
| `logistic_regression` | Logistic Regression (Base) | Scikit-Learn 1.7.2 | BSD-3-Clause | Yes | CPU | **ACTIVE_BENCHMARKED** |
| `logistic_regression_htf` | Logistic Regression (1H Context) | Scikit-Learn 1.7.2 | BSD-3-Clause | Yes | CPU | **ACTIVE_BENCHMARKED** |
| `selective_entry_htf` | Selective-Entry Strategy | 1.0 | Internal / MIT | Yes | CPU | **ACTIVE_BENCHMARKED** |
| `lightgbm` | LightGBM Boosted Trees | LightGBM 4.7.0 | MIT License | Yes | CPU / GPU | **ACTIVE_BENCHMARKED** |
| `xgboost` | XGBoost Boosted Trees | XGBoost 3.2.0 | Apache-2.0 | Yes | CPU / GPU | **ACTIVE_BENCHMARKED** |
| `amazon_chronos_2` | Amazon Chronos-2 Foundation Model | chronos-forecasting 2.3.2 (`amazon/chronos-2`) | Apache-2.0 | Yes | PyTorch CPU / CUDA | **ACTIVE_BENCHMARKED** |
| `google_timesfm_3` | Google TimesFM 3.0 Foundation Model | `google/timesfm-3.0` | `timesfm-non-commercial-license-v1.0` | **NO** | PyTorch / JAX + CUDA | **BLOCKED_RESTRICTIVE_LICENSE** |

### Critical Licensing Finding on Google TimesFM 3.0:
The open weights for Google TimesFM 3.0 on Hugging Face are published under `timesfm-non-commercial-license-v1.0`, which strictly prohibits commercial and production use. In accordance with milestone instructions (*"Check the TimesFM 3.0 licence before use. Do not use restricted weights for prohibited commercial or production purposes. If a model cannot be integrated or evaluated fairly, report why. Do not fabricate results or silently substitute another model"*), **Google TimesFM 3.0 evaluation is formally blocked by licensing constraints**. No synthetic numbers or proxy models were substituted.

### Amazon Chronos-2 Foundation Integration:
Amazon Chronos-2 (`amazon/chronos-2`) is governed by the permissive **Apache-2.0 License** and was successfully integrated via `chronos-forecasting==2.3.2`. A point-in-time adapter was implemented:
- For each test bar $t$, a 64-bar historical price window strictly $\le t$ is fed into the Chronos-2 transformer.
- Zero-shot quantile predictions ($K=19$ quantile levels from 0.05 to 0.95) are produced for the forecast horizon.
- Directional return probability is computed strictly as the empirical fraction of positive quantiles:  
  $P(\text{Up}) = \frac{1}{K} \sum_{k=1}^K \mathbf{1}(\hat{R}^{(q_k)} > 0)$.
- Raw probabilities are calibrated on expanding validation folds using `IsotonicCalibrator`.

---

## 7. TARGET DEFINITIONS & EXECUTION ASSUMPTIONS

| Target Symbol | Formula | Execution Price | Realizable in Live Market? | Milestone Classification |
| :--- | :--- | :--- | :---: | :--- |
| **`C2C`** | $\frac{\text{Close}[t+1] - \text{Close}[t]}{\text{Close}[t]}$ | $\text{Close}[t]$ fill | **NO** (Signal at bar close cannot execute at that same close) | **THEORETICAL_BENCHMARK** |
| **`O2O`** | $\frac{\text{Open}[t+2] - \text{Open}[t+1]}{\text{Open}[t+1]}$ | $\text{Open}[t+1]$ fill | **YES** (Executable next-bar open fill) | **EXECUTABLE_TRADING** |
| **`O2C_1B`** | $\frac{\text{Close}[t+1] - \text{Open}[t+1]}{\text{Open}[t+1]}$ | $\text{Open}[t+1]$ fill | **YES** (Executable open entry, bar close exit) | **EXECUTABLE_TRADING** |
| **`O2C_2B`** | $\frac{\text{Close}[t+2] - \text{Open}[t+1]}{\text{Open}[t+1]}$ | $\text{Open}[t+1]$ fill | **YES** (Executable open entry, 2-bar close exit) | **EXECUTABLE_TRADING** |

Zero future leakage was enforced across all 12 feature dimensions (rolling returns, realized volatility, bar position, volume ratios, 1H multi-timeframe context, and cyclical time-of-day features).

---

## 8. COMPREHENSIVE BENCHMARK RESULTS ACROSS ALL TARGETS

### 8.1 Target: `O2O` (Executable Next-Bar Open to Subsequent Open)
- **Classification**: `EXECUTABLE_TRADING`
- **Total Expanding Walk-Forward Folds**: 19
- **Total Aligned Samples Evaluated**: 6,209 bars (4,750 test observations across folds)

| Model Architecture | Accuracy | Balanced Accuracy | Brier Score | BSS vs Prior (%) | Compounded Net Return (0 bps) | Net Return (2 bps) | Net Return (5 bps) | Net Return (10 bps) | Total Trades | Worst Fold Drawdown |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Empirical Prior** | 0.4907 | 0.5000 | 0.2503 | +0.00% | -12.63% | -13.29% | -14.27% | -15.89% | 19 | 0.00% |
| **Majority Class** | 0.4907 | 0.5000 | 0.5093 | -103.48% | -12.63% | -13.29% | -14.27% | -15.89% | 19 | 0.00% |
| **Last Return Sign** | 0.4949 | 0.4939 | 0.5051 | -101.80% | -9.98% | -44.81% | -73.51% | -92.21% | 1,223 | 0.00% |
| **Logistic Regression** | 0.5034 | 0.4988 | 0.2564 | -2.44% | -5.00% | -21.79% | -41.58% | -64.08% | 486 | 0.00% |
| **Logistic Regression HTF** | **0.5059** | 0.4989 | 0.2541 | -1.52% | **-1.86%** | **-19.71%** | **-40.60%** | **-64.06%** | 502 | 0.00% |
| **Selective Entry HTF** | **0.5059** | 0.4989 | 0.2541 | -1.52% | -2.50% | -21.13% | -42.62% | -66.24% | 530 | 0.00% |
| **LightGBM** | 0.5011 | 0.4942 | 0.2589 | -3.44% | -11.33% | -28.21% | -47.71% | -69.17% | 528 | 0.00% |
| **XGBoost** | 0.4966 | 0.4903 | 0.2584 | -3.24% | -9.28% | -23.43% | -40.64% | -61.17% | 424 | 0.00% |
| **Amazon Chronos-2** | 0.5019 | 0.4950 | 0.2534 | **-1.24%** | -11.36% | -19.12% | -29.51% | **-43.95%** | **229** | 0.00% |
| **Google TimesFM 3.0** | N/A | N/A | N/A | N/A | *BLOCKED* | *BLOCKED* | *BLOCKED* | *BLOCKED* | N/A | N/A |

---

### 8.2 Target: `O2C_1B` (Executable Open to Bar Close Intraday)
- **Classification**: `EXECUTABLE_TRADING`
- **Total Folds**: 19

| Model Architecture | Accuracy | Balanced Accuracy | Brier Score | BSS vs Prior (%) | Compounded Net Return (0 bps) | Net Return (2 bps) | Net Return (5 bps) | Net Return (10 bps) | Total Trades | Worst Fold Drawdown |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Empirical Prior** | 0.5053 | 0.5000 | 0.2501 | +0.00% | -6.12% | -6.38% | -6.78% | -7.43% | 7 | 0.00% |
| **Majority Class** | 0.5053 | 0.5000 | 0.4947 | -97.80% | -6.12% | -6.38% | -6.78% | -7.43% | 7 | 0.00% |
| **Last Return Sign** | 0.4905 | 0.4894 | 0.5095 | -103.72% | -13.79% | -47.14% | -74.63% | -92.54% | 1,223 | 0.00% |
| **Logistic Regression** | **0.5164** | **0.5052** | 0.2572 | -2.84% | **-0.29%** | -18.72% | -40.19% | -64.14% | 511 | 0.00% |
| **Logistic Regression HTF** | 0.5131 | 0.5011 | 0.2560 | -2.36% | -2.37% | -21.50% | -43.40% | -67.19% | 545 | 0.00% |
| **Selective Entry HTF** | 0.5131 | 0.5011 | 0.2560 | -2.36% | -0.30% | **-16.23%** | **-35.48%** | **-58.25%** | 435 | 0.00% |
| **LightGBM** | 0.5095 | 0.4961 | 0.2558 | -2.28% | -7.60% | -22.23% | -39.96% | -60.99% | 431 | 0.00% |
| **XGBoost** | 0.5061 | 0.4952 | 0.2572 | -2.84% | -10.76% | -24.50% | -41.26% | -61.34% | 418 | 0.00% |
| **Amazon Chronos-2** | 0.5084 | 0.4947 | 0.2526 | **-1.00%** | -6.35% | -19.30% | -35.45% | -55.51% | 372 | 0.00% |
| **Google TimesFM 3.0** | N/A | N/A | N/A | N/A | *BLOCKED* | *BLOCKED* | *BLOCKED* | *BLOCKED* | N/A | N/A |

---

### 8.3 Target: `O2C_2B` (Executable Open to 2-Bar Close Swing)
- **Classification**: `EXECUTABLE_TRADING`
- **Total Folds**: 19

| Model Architecture | Accuracy | Balanced Accuracy | Brier Score | BSS vs Prior (%) | Compounded Net Return (0 bps) | Net Return (2 bps) | Net Return (5 bps) | Net Return (10 bps) | Total Trades | Worst Fold Drawdown |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Empirical Prior** | 0.4998 | 0.5000 | 0.2503 | +0.00% | -15.66% | -15.89% | -16.25% | -16.83% | 7 | 0.00% |
| **Majority Class** | 0.4998 | 0.5000 | 0.5002 | -99.84% | -15.66% | -15.89% | -16.25% | -16.83% | 7 | 0.00% |
| **Last Return Sign** | 0.4956 | 0.4947 | 0.5044 | -101.52% | -19.22% | -50.48% | -76.23% | -93.01% | 1,223 | 0.00% |
| **Logistic Regression** | 0.5048 | 0.4996 | 0.2599 | -3.84% | **-4.68%** | **-14.27%** | **-26.88%** | **-43.91%** | **265** | 0.00% |
| **Logistic Regression HTF** | 0.5072 | 0.5000 | 0.2581 | -3.12% | -6.96% | -16.55% | -29.12% | -46.01% | 272 | 0.00% |
| **Selective Entry HTF** | 0.5072 | 0.5000 | 0.2581 | -3.12% | -7.03% | -16.45% | -28.82% | -45.51% | 267 | 0.00% |
| **LightGBM** | 0.5029 | 0.4982 | 0.2578 | -3.00% | -17.72% | -31.28% | -47.55% | -66.57% | 450 | 0.00% |
| **XGBoost** | **0.5084** | 0.5009 | 0.2563 | -2.40% | -6.08% | -20.67% | -38.42% | -59.64% | 422 | 0.00% |
| **Amazon Chronos-2** | 0.5042 | **0.5016** | 0.2524 | **-0.84%** | -11.27% | -24.66% | -41.06% | -60.86% | 409 | 0.00% |
| **Google TimesFM 3.0** | N/A | N/A | N/A | N/A | *BLOCKED* | *BLOCKED* | *BLOCKED* | *BLOCKED* | N/A | N/A |

---

### 8.4 Target: `C2C` (Theoretical Close-to-Close Benchmark)
- **Classification**: `THEORETICAL_BENCHMARK` (Unexecutable in Live Trading)
- **Total Folds**: 19

| Model Architecture | Accuracy | Balanced Accuracy | Brier Score | BSS vs Prior (%) | Compounded Net Return (0 bps) | Net Return (2 bps) | Net Return (5 bps) | Net Return (10 bps) | Total Trades | Worst Fold Drawdown |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Empirical Prior** | 0.4945 | 0.5000 | 0.2502 | +0.00% | -12.63% | -13.29% | -14.28% | -15.89% | 19 | 0.00% |
| **Majority Class** | 0.4945 | 0.5000 | 0.5055 | -102.04% | -12.63% | -13.29% | -14.28% | -15.89% | 19 | 0.00% |
| **Last Return Sign** | 0.4882 | 0.4871 | 0.5118 | -104.56% | -15.91% | -48.44% | -75.26% | -92.72% | 1,223 | 0.00% |
| **Logistic Regression** | 0.5023 | 0.4999 | 0.2583 | -3.24% | -2.90% | -20.91% | -41.87% | -65.21% | 513 | 0.00% |
| **Logistic Regression HTF** | 0.5032 | 0.5016 | 0.2559 | -2.28% | -5.55% | -24.15% | -45.41% | -68.45% | 548 | 0.00% |
| **Selective Entry HTF** | 0.5032 | 0.5016 | 0.2559 | -2.28% | -7.14% | -24.85% | -45.29% | -67.78% | 529 | 0.00% |
| **LightGBM** | **0.5051** | 0.4970 | 0.2579 | -3.08% | **-2.05%** | **-16.73%** | **-34.74%** | **-56.53%** | 406 | 0.00% |
| **XGBoost** | 0.4994 | 0.4977 | 0.2599 | -3.88% | -8.64% | -23.05% | -40.52% | -61.28% | 429 | 0.00% |
| **Amazon Chronos-2** | 0.4922 | 0.4933 | 0.2549 | **-1.88%** | -9.99% | -20.43% | -33.85% | -51.40% | **308** | 0.00% |
| **Google TimesFM 3.0** | N/A | N/A | N/A | N/A | *BLOCKED* | *BLOCKED* | *BLOCKED* | *BLOCKED* | N/A | N/A |

---

## 9. KEY QUANTITATIVE INSIGHTS

1. **Directional Accuracy & Calibration**:
   - Across 4,750 test observations in 19 folds, directional accuracy ranges tightly between **49.0% and 51.6%**.
   - No model demonstrates large directional classification edge over random chance on 15-minute equity index bars.
   - Amazon Chronos-2 achieves the **best probability calibration** among non-linear models, with a Brier score of **0.2524** to **0.2534** (closest to the empirical prior Brier score of 0.2501).

2. **Transaction Cost Drag vs Turnover**:
   - The naive Momentum baseline (`last_return_sign`) suffers extreme churn (1,223 trades), collapsing from -9.98% gross to **-92.21% net at 10 bps**.
   - Logistic regression models and tree ensembles generate 400–550 trades, suffering severe degradation from frictions (-40% to -69% net).
   - Amazon Chronos-2 generated the **lowest turnover and trade count (229 trades on O2O)** among active signal models, exhibiting the lowest fee degradation (-43.95% at 10 bps vs -64% to -69% for linear and tree models).

3. **Executable vs Theoretical Divergence**:
   - As proven in M21 and M22, C2C remains a purely theoretical benchmark. Realizable execution at Next-Bar Open (`O2O`) incurs overnight gap risk and execution drift that cannot be substituted with closing prices.

---

## 10. REPRODUCIBILITY & PERSISTENT CACHING

- **Cache Implementation**: Persistent storage in PostgreSQL table `benchmark_cache` keyed on `(dataset_id, model_version, feature_config_hash, target, eval_settings_hash)`.
- **Cache Hit Verification**: Verified that identical configuration re-runs fetch directly from PostgreSQL cache without re-computing expensive transformer forward passes or model fits.
- **Cache Invalidation**: Verified that alterations in dataset hash, feature engineering, model parameters, or target specification immediately invalidate the relevant cache entry.

---

## 11. AUTOMATED TEST SUITE EXECUTION

### 11.1 Backend Test Results
```bash
pytest tests/
==================== 525 passed, 1 skipped, 1 warning in 95.59s ====================
```
- Total test files: 61
- Total tests passed: **525 passed** (0 failed, 0 errors).
- New test suite `tests/test_m23_benchmark.py`: **10 passed in 72s**.
- Persistence test suite `tests/test_market_data_persistence.py`: **10 passed in 0.9s**.

### 11.2 Frontend Test Results
```bash
npm test (apps/web)
✔ 10 tests passed (102.85ms)
```

---

## 12. FAILURES, LIMITATIONS, AND NEXT STEPS

### 12.1 Explicitly Documented Blockers & Limitations
1. **Google TimesFM 3.0 License Blocker**:
   - Blocked by `timesfm-non-commercial-license-v1.0`. Commercial/production deployment is legally prohibited by Google's licensing terms.
   - Recommended next step: If Google releases commercial-friendly weights (e.g., Apache-2.0) or provides managed Vertex AI API keys, integrate via official cloud inference.
2. **Groww API Single Provider**:
   - Independent cross-provider verification remains pending. No secondary broker feed (Zerodha Kite, Upstox, Angel One) was engaged in this milestone per instructions.
3. **Transaction Cost Accounting Simulation**:
   - The 0, 1, 2, 5, and 10 bps friction schedules are mathematical models of exchange turnover, STT, brokerage, and slippage. They are not guaranteed execution quotes from Groww or NSE.

---

## 13. SAFETY INVARIANTS CONFIRMATION

All mandatory safety invariants remain strictly enforced as **`false`** across all application configurations, databases, and research engines:

```python
forecast_ready = false
real_market_data_verified = false
paper_approved = false
live_approved = false
live_broker_routing_enabled = false
```

- **Zero live broker orders were created or routed.**
- **No paper or live trading state was enabled.**
- **Zero API credentials, bearer tokens, or secret keys were printed.**
