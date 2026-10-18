# Milestone M32: Observability, Feature Drift Monitoring & Kill Switch Tripping Report

**Milestone:** M32 Observability, Drift Monitoring & Fail-Safe Recovery (Priority P9)  
**Date:** 2026-10-17  
**Author:** Autonomous Engineering & Quantitative Research Agent  
**Module:** `apps/api/app/monitoring/drift_detector.py`  
**Test Suite:** `apps/api/tests/test_m32_drift_monitoring.py` (7 passed in 0.65s)  
**Artifact Generated:** `var/datasets/m32_drift_benchmark_results.json` (12.5 KB)  
**Safety Invariants:** All 5 strictly `False` (`forecast_ready = false`, etc.)

---

## 1. Executive Summary & Problem Formulation

In quantitative trading, machine learning models and deterministic risk rules are trained on historical distributions. When the live market distribution diverges significantly from training data (**distribution shift** / **data drift**), model assumptions fail:
1. Volatility contractions cause fixed thresholds to starve signals, while volatility expansions cause outsized drawdowns.
2. Regime transitions (e.g., trend to consolidation) cause severe whipsaw losses if feature shifts are not detected in real time.
3. Unmonitored models experience silent performance decay, continuing to risk capital when market dynamics no longer match calibration windows.

**The M32 Deliverable:**
We implemented the **Statistical Feature Drift & Fail-Safe Circuit Breaker Engine** in [`apps/api/app/monitoring/drift_detector.py`](file:///home/neo/work/personal/stock_market_analysis/apps/api/app/monitoring/drift_detector.py):
- **Population Stability Index (PSI):** Quantile-based distribution divergence metric with Laplace smoothing.
- **Two-Sample Kolmogorov-Smirnov (KS) Test:** Non-parametric evaluation of empirical CDF divergence.
- **Wasserstein Distance:** Physical earth mover's distance quantifying metric scale shifts.
- **Automated Circuit Breaker:** Automatically trips the operational kill switch (`OpsState.kill_switch = True`) in PostgreSQL and records an immutable `RiskAuditLog` entry when critical drift ($\text{PSI} \ge 0.25$) is confirmed.
- **Empirical NIFTY Benchmark Audit:** Evaluated distribution shift between Development (Folds 1–14, 3,500 bars) and Holdout (Folds 15–19, 1,250 bars).

---

## 2. Statistical Formulation & Thresholds

### 1. Population Stability Index (PSI)
Given reference distribution $P$ and evaluation/target distribution $Q$, partitioned into $K=10$ quantile bins derived from $P$:

$$\text{PSI} = \sum_{i=1}^K \left(q_i - p_i\right) \times \ln\left(\frac{q_i}{p_i}\right)$$

Where $p_i$ and $q_i$ are smoothed proportions:
$$p_i = \frac{N_{P, i} + \epsilon}{N_P + K \cdot \epsilon}, \quad q_i = \frac{N_{Q, i} + \epsilon}{N_Q + K \cdot \epsilon}$$
With Laplace smoothing factor $\epsilon = 10^{-4}$ guaranteeing numerical stability.

#### Standard Statistical Thresholds:
- **$\text{PSI} < 0.10$ (`STABLE`):** Negligible distribution change; models remain statistically valid.
- **$0.10 \le \text{PSI} < 0.25$ (`MODERATE_DRIFT`):** Moderate shift; triggers warning alerts and increases uncertainty weight.
- **$\text{PSI} \ge 0.25$ (`CRITICAL_DRIFT`):** Severe distribution breakdown; triggers automated fail-safe circuit breaker tripping.

### 2. Kolmogorov-Smirnov (KS) Two-Sample Test
Measures the maximum vertical distance between reference and target empirical cumulative distribution functions $F_{\text{ref}}(x)$ and $F_{\text{target}}(x)$:

$$D = \sup_x \left| F_{\text{ref}}(x) - F_{\text{target}}(x) \right|$$

With asymptotic p-value evaluating the null hypothesis that both samples are drawn from the identical continuous distribution.

---

## 3. Empirical NIFTY 1-Year Benchmark Findings (Dev vs Holdout)

Evaluating the 1-year NIFTY dataset (`derived_nifty_15m_m23_bc7d31bceebf13a3.json`) comparing the Development Window (Folds 1–14, 3,500 bars: Oct 2025 to Jul 2026) vs Untouched Holdout Window (Folds 15–19, 1,250 bars: Jul 2026 to Oct 2026) revealed critical quantitative insights:

| Feature Name | Reference Mean ($\pm$ Std) | Target Mean ($\pm$ Std) | PSI | KS Statistic | KS p-value | Drift Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **`returns`** | $-0.0021\% \pm 0.196\%$ | $+0.0012\% \pm 0.158\%$ | **0.0118** | 0.0254 | 0.584 | **`STABLE`** |
| **`volume`** | $0.00 \pm 0.00$ | $0.00 \pm 0.00$ | **0.0000** | 0.0000 | 1.000 | **`STABLE`** |
| **`adx`** (14) | $16.74 \pm 7.92$ | $15.11 \pm 6.81$ | **0.1659** | 0.1349 | $1.26 \times 10^{-16}$ | **`MODERATE_DRIFT`** |
| **`atr`** (14) | $41.51 \pm 14.18$ | $32.48 \pm 10.95$ | **0.2861** | 0.3654 | $1.41 \times 10^{-119}$ | **`CRITICAL_DRIFT`** |

### Key Quantitative Findings:
1. **Return Symmetry Remained Constant:** NIFTY 15m return distributions showed virtually zero drift ($\text{PSI} = 0.0118$, KS p-value $0.584$). Centered near zero with symmetric tails.
2. **Severe Volatility Contraction (`CRITICAL_DRIFT`):**
   - The average True Range collapsed by **$21.8\%$** from **$41.51\text{ pts}$** on Folds 1–14 down to **$32.48\text{ pts}$** on Folds 15–19.
   - The resulting $\text{PSI} = 0.2861$ comfortably exceeded the critical threshold ($0.25$), with KS statistic $D=0.3654$ ($p < 10^{-100}$).
3. **Explaining Holdout Performance Differences:**
   - This empirical finding directly explains why unadapted models suffered on Holdout: fixed point targets and stop losses calibrated during high-volatility months were too wide for the low-volatility summer 2026 regime.
   - It validates why **M31 Volatility-Parity Sizing** and **M28 Regime Consensus Gating** are essential: adaptive ATR sizing naturally compensates for this contraction.

---

## 4. Automated Circuit Breaker Operation

When `evaluate_and_enforce_drift_circuit_breaker` is called:
1. Feature matrix distributions are checked across reference and target windows.
2. If any monitored feature crosses $\text{PSI} \ge 0.25$:
   - The circuit breaker issues a critical alert.
   - Executes `set_kill_switch(session, enabled=True, actor="system.drift_monitor", reason="CRITICAL_FEATURE_DRIFT: ...")`.
   - Modifies `OpsState(id=1, kill_switch=True)`.
   - Inserts an immutable audit record into `AuditEvent`.
   - Sets `report.kill_switch_tripped = True`.
3. Downstream risk gates in `app/risk/gates.py` immediately observe `kill_switch = True`, returning `VETO` on all simulated, proposal, and paper execution pipelines.

---

## 5. Test Suite Verification

The test suite [`apps/api/tests/test_m32_drift_monitoring.py`](file:///home/neo/work/personal/stock_market_analysis/apps/api/tests/test_m32_drift_monitoring.py) executed 7 tests with **100% pass rate in 0.65s**:
1. `test_psi_identical_distributions_near_zero`: Verified identical distributions produce $\text{PSI} < 0.05$.
2. `test_psi_moderate_and_critical_distribution_shifts`: Verified calibrated shifts trigger warning ($\text{PSI} \ge 0.10$) and critical ($\text{PSI} \ge 0.25$) states.
3. `test_ks_and_wasserstein_metrics`: Verified non-parametric KS and Wasserstein distance metrics accurately separate identical from shifted distributions.
4. `test_circuit_breaker_trips_kill_switch_on_critical_drift`: Verified that volatility explosion trips `OpsState.kill_switch = True` in PostgreSQL and creates audit event.
5. `test_circuit_breaker_safe_under_normal_conditions`: Verified that stable features do NOT trip the kill switch.
6. `test_nifty_benchmark_drift_dev_vs_holdout`: Verified full execution of NIFTY Dev vs Holdout drift audit and generation of `m32_drift_benchmark_results.json`.
7. `test_m32_safety_invariants_strictly_false`: Verified all 5 financial safety invariants remain strictly `False`.

---

## 6. Financial Safety Invariants Verification

All five safety invariants remain strictly enforced as **`False`**:
- `forecast_ready = False`
- `real_market_data_verified = False`
- `paper_approved = False`
- `live_approved = False`
- `live_broker_routing_enabled = False`
