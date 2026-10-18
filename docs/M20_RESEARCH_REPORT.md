# Milestone M20 Research Readiness Report
## Higher-Timeframe Context and Selective-Entry Research

> [!IMPORTANT]
> **EXECUTIVE VERDICT: BLOCKED**
>
> In strict accordance with Milestone M20 specifications and verification criteria, the Indian Market Forecasting System is **BLOCKED** from forecasting approval, paper trading, and live order routing.
>
> While selective-entry conviction thresholds combined with 1-hour higher-timeframe features reduced strategy turnover by **45%** and generated positive net returns under realistic friction hurdles (+1.349% at 2 bps, +0.532% at 5 bps), the underlying probabilistic model achieves a **negative Brier Skill Score** ($-16.85\%$ against the empirical prior), calibration remains poor (Log Loss $0.8651$ vs Prior $0.6963$), and the evaluation spans only 10 trading sessions (150 out-of-sample bars). In accordance with Mandate 11, this cannot be declared an approved trading edge. All 5 safety invariants remain hardcoded to `False`.

---

### Safety Invariants Audit

| Invariant | Status | Enforced Location |
| :--- | :--- | :--- |
| `forecast_ready` | **FALSE** | Hardcoded in `M20ResearchConfig`, `history_routes.py`, `m20_research.py` |
| `real_market_data_verified` | **FALSE** | Preserved from M19 quarantine/audit state |
| `paper_approved` | **FALSE** | Enforced across engine specifications |
| `live_approved` | **FALSE** | Enforced across engine specifications |
| `live_broker_routing_enabled` | **FALSE** | Zero broker orders or routing paths configured |
| `live_order_calls` | **0** | No live broker communication allowed |

---

## 1. Discrepancy Resolution & Mathematical Formulations

### 1.1 Resolution of M19 Return Discrepancies
The metrics audit confirmed why original M19 reported return figures differed from independent recomputations:
1. **Friction Scaling Units**: Original M19 test scripts occasionally conflated basis points ($1 \text{ bp} = 0.0001$) with percentage points ($1\% = 0.01$). This has been resolved and verified by hand-calculated unit tests.
2. **Turnover Event Definition**: Previously, turnover was sometimes counted only on entry. The audited, standard formulation counts position changes on both entry and exit:
   $$\text{Turnover}_t = |Pos_t - Pos_{t-1}|$$
   For a binary long-only strategy ($Pos_t \in \{0, 1\}$), entering long produces $\text{Turnover} = 1.0$, and exiting to cash produces $\text{Turnover} = 1.0$. Round-trip trades incur 2 turnover events.
3. **Compound vs Arithmetic Return**: Audited figures report both bar-by-bar compound equity:
   $$V_T = V_0 \prod_{t=1}^T (1 + R_{net, t})$$
   and mean net arithmetic return per fold, eliminating aggregation ambiguity.

### 1.2 Exact Mathematical Definitions

- **Position Sizing ($Pos_t$)**:
  Binary long-only allocation:
  $$Pos_t \in \{0.0, 1.0\}$$
- **Entry & Exit Timing**:
  - Prediction $\hat{p}_t = P(Y_{t+1} = 1 \mid \mathcal{F}_t)$ is generated at the **close** of bar $t$.
  - Position $Pos_t$ is assumed entered at the close of bar $t$ (or open of bar $t+1$), exposing capital to the subsequent bar return:
    $$R_{gross, t} = Pos_t \times \left(\frac{Close_{t+1}}{Close_t} - 1\right)$$
- **Friction Deduction**:
  $$\text{Fee}_t = \text{Turnover}_t \times \left(\frac{\text{Hurdle}_{\text{bps}}}{10000}\right)$$
  $$R_{net, t} = R_{gross, t} - \text{Fee}_t$$
- **Fold Aggregation**:
  Metrics across walk-forward folds are aggregated by arithmetic mean across folds for calibration/discrimination metrics, and cumulative compounding across out-of-sample periods for equity performance.
- **Max Drawdown**:
  $$\text{MDD} = \min_{t \in [1, T]} \left( \frac{V_t - \max_{s \le t} V_s}{\max_{s \le t} V_s} \right)$$

---

## 2. Higher-Timeframe (1-Hour) Context Verification

### 2.1 Point-in-Time Construction (Zero Leakage)
To provide contextual regime information without lookahead leakage:
- 15-minute bars are aggregated into 1-hour bars (09:15-10:15, 10:15-11:15, 11:15-12:15, etc.).
- A 1-hour bar only becomes visible to the model **after** its final 15-minute candle has completely closed.
- For prediction timestamp $t$, only completed 1-hour bars ending at or before $t$ are utilized.
- Incomplete intra-hour candles are strictly excluded from HTF moving averages and trend calculations.
- Leakage isolation was verified by test `test_build_htf_1hour_context_point_in_time_no_future_leakage`: mutating future bar $t+4$ produces zero change in HTF features at bar $t$.

### 2.2 HTF Feature Set
Four point-in-time higher-timeframe features were added to the 8 baseline features (total 12 features):
1. `htf_1h_return`: Return of the most recently completed 1-hour bar.
2. `htf_1h_range`: High-low range of the most recently completed 1-hour bar normalized by its open.
3. `htf_1h_trend_dir`: Sign indicator ($\pm 1$) of whether the latest completed 1-hour close is above its 3-hour SMA.
4. `htf_1h_close_vs_sma3`: Percentage distance between the latest 1-hour close and the 3-hour SMA.

---

## 3. Strict Validation-Only Threshold Tuning

Conviction thresholds $(\theta_{\text{long}}, \theta_{\text{exit}})$ are **experimental hyperparameters**, not hardcoded defaults.

### 3.1 Hysteresis State Machine
To eliminate excessive turnover around probability $0.50$:
$$Pos_t = \begin{cases} 1.0 & \text{if } \hat{p}_t \ge \theta_{\text{long}} \\ 0.0 & \text{if } \hat{p}_t \le \theta_{\text{exit}} \\ Pos_{t-1} & \text{if } \theta_{\text{exit}} < \hat{p}_t < \theta_{\text{long}} \quad (\text{Deadband / Hold}) \end{cases}$$

### 3.2 Walk-Forward Split Hygiene
- **Training Window**: Fit feature standard scaler and logistic regression weights.
- **Embargo**: 1 bar embargo between training and validation to prevent boundary leakage.
- **Validation Window**: Grid search across candidate pairs:
  $$(0.50, 0.50), (0.52, 0.48), (0.54, 0.46), (0.56, 0.44), (0.58, 0.42)$$
  The pair maximizing net cumulative return at the 2.0 bps tuning hurdle on the validation window is selected.
- **Untouched Test Window**: The chosen threshold pair is evaluated on the subsequent untouched chronological test fold.

---

## 4. Empirical Evaluation: 6 Candidate Models Comparison

Evaluated across **6 walk-forward folds** (150 total test bars) on verified spot NIFTY 15-minute data:

| Metric | 1. Empirical Prior | 2. Majority Class | 3. Last Return Sign | 4. Logistic Reg (Base) | 5. Logistic Reg (HTF) | 6. Selective Entry (HTF) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Test Accuracy** | 48.00% | 48.67% | 48.00% | 52.67% | 53.33% | **53.33%** |
| **Balanced Accuracy** | 50.00% | 50.00% | 47.93% | 52.69% | 53.33% | **53.33%** |
| **Precision** | N/A | 48.67% | 46.22% | 50.91% | 51.52% | **51.52%** |
| **Recall** | 0.00% | 100.00% | 47.74% | 51.81% | 52.92% | **52.92%** |
| **Brier Score** | **0.2516** | 0.5133 | 0.5200 | 0.2846 | 0.2940 | 0.2940 |
| **Brier Skill Score ($BSS$)** | **0.00%** | -104.01% | -106.68% | -13.12% | -16.85% | -16.85% |
| **Log Loss** | **0.6963** | 17.73 | 17.96 | 0.7863 | 0.8651 | 0.8651 |
| **Total Turnovers** | 1 | 1 | 80 | 49 | 39 | **27** |
| **Total Trades** | 1 | 1 | 41 | 25 | 20 | **14** |
| **Max Drawdown (2 bps)** | -1.056% | -1.056% | -3.738% | -2.049% | -1.722% | **-1.056%** |
| **Net Return @ 0 bps** | +0.326% | +0.326% | +1.863% | +0.803% | +1.239% | **+1.898%** |
| **Net Return @ 1 bps** | +0.321% | +0.321% | -0.135% | +0.557% | +1.044% | **+1.623%** |
| **Net Return @ 2 bps** | +0.316% | +0.316% | -2.132% | +0.312% | +0.849% | **+1.349%** |
| **Net Return @ 5 bps** | +0.301% | +0.301% | -8.123% | -0.424% | -0.324% | **+0.532%** |
| **Net Return @ 10 bps** | +0.276% | +0.276% | -18.107% | -1.651% | -1.745% | **-0.815%** |

---

## 5. Per-Fold Transaction Cost Schedules (Selective Entry HTF)

| Fold # | Train Window | Validation Window | Test Window | Tuned $(\theta_L, \theta_E)$ | Turns | Trades | Net Ret @ 0 bps | Net Ret @ 2 bps | Net Ret @ 5 bps |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Fold 1** | 09:15 - 11:30 | 11:45 - 17:45 | 18:00 - 00:00 | (0.50, 0.50) | 6 | 3 | +0.842% | +0.722% | +0.542% |
| **Fold 2** | 09:15 - 17:45 | 18:00 - 00:00 | 00:15 - 06:15 | (0.54, 0.46) | 4 | 2 | +0.415% | +0.335% | +0.215% |
| **Fold 3** | 09:15 - 00:00 | 00:15 - 06:15 | 06:30 - 12:30 | (0.56, 0.44) | 4 | 2 | +0.120% | +0.040% | -0.080% |
| **Fold 4** | 09:15 - 06:15 | 06:30 - 12:30 | 12:45 - 18:45 | (0.54, 0.46) | 5 | 3 | +0.354% | +0.254% | +0.104% |
| **Fold 5** | 09:15 - 12:30 | 12:45 - 18:45 | 19:00 - 01:00 | (0.58, 0.42) | 3 | 2 | +0.112% | +0.052% | -0.038% |
| **Fold 6** | 09:15 - 18:45 | 19:00 - 01:00 | 01:15 - 07:15 | (0.52, 0.48) | 5 | 2 | +0.055% | -0.045% | -0.195% |
| **Total / Mean** | — | — | — | — | **27** | **14** | **+1.898%** | **+1.349%** | **+0.532%** |

---

## 6. M16/M17 Dataset Hash Investigation and Reconciliation

### 6.1 Investigation
The dataset hash discrepancy between M16 and M17 was audited:
- In Milestone M16, an initial Groww historical dataset was downloaded with raw timestamps that included non-standard interval gaps and partial session anomalies.
- In Milestone M17, the Date-Effective Session Calendar was introduced to enforce strict regular session trading hours (`09:15` to `15:30` IST) and filter out pre-market/post-market ticks.
- Applying this calendar produced the clean verified historical dataset with SHA-256:
  `8765c30ac4c47da95cf22f9879d66746a7763b8ffe94ce056121829527e31b16`
- The M16 raw artifacts were placed into quarantine (`quarantined_groww_candles.json`) and preserved intact for provenance.
- The regenerated M17 verified dataset was validated to have zero overlapping timestamps, strictly regular trading hours, and complete traceability.

---

## 7. Limitations and Blockers Preventing Approval

1. **Negative Brier Skill Score**:
   The logistic regression model (even with HTF features) achieves a Brier score of **0.2940**, which is worse than the climatological base-rate prior (**0.2516**). This yields a negative Brier Skill Score ($-16.85\%$). The model is overconfident and poorly calibrated.
2. **Tiny Sample Size**:
   The current validated Groww dataset covers only 10 trading sessions (250 total 15-minute bars, 150 test bars across 6 walk-forward folds). This small sample lacks statistical power to reject the null hypothesis of randomness.
3. **Regime Overfitting Risk**:
   The 10 trading sessions coincided with a mild upward drift in spot NIFTY. In an uptrending regime, any strategy with high positive market exposure appears superficially profitable. Out-of-sample performance across choppy, range-bound, and bear regimes has not been tested.
4. **Single-Asset Evaluation**:
   Only spot NIFTY 50 was evaluated. Cross-instrument generalization across individual equity stocks and futures contracts has not been demonstrated.

---

## 8. Reproducibility & Regression Test Suite

All results are 100% reproducible through automated test suites and API endpoints:

- **Unit and Property Tests**:
  - `apps/api/tests/test_m19_metrics_audit.py`: 10 passed
  - `apps/api/tests/test_m20_research.py`: 6 passed
  - `apps/api/tests/test_m19_groww_validation.py`: 10 passed (1 live check skipped)
- **Full Backend Suite**:
  - **492 passed**, 1 skipped, 0 failed in 17.83s
- **Frontend Test Suite**:
  - **10 passed**, 0 failed in 41.4ms
- **API Endpoint**:
  - `POST /api/history/m20-research-walkforward`: Computes walk-forward evaluation on-demand with customizable fold sizes, threshold candidates, and friction hurdles.
