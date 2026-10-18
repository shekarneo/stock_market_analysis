# Known Issues & Technical Defect Registry — V6 System

**System:** V6 Autonomous Indian Market AI Trading System  
**Status:** Living Defect and Limitation Tracker  
**Last Updated:** 2026-10-17  

---

## 1. Quantitative & Alpha Deficiencies

### ISSUE-QUANT-001: Signal-to-Noise Deficit on 15-Minute Intraday Horizon
- **Severity:** High (Alpha Blocker for 15m Trading)
- **Status:** **RESOLVED IN M27 (FORMAL NO-GO ON 15M; HTF HALF-DAY ADOPTED)**
- **Description:** Walk-forward benchmarks across 1-year of NIFTY 15m data (6,227 candles) reveal that directional forecasting accuracy ranges between $50.1\%$ and $50.7\%$, with negative Brier Skill Scores ($BSS < 0$) relative to the empirical prior. Because average 15m price displacement is only $0.12\%$, standard exchange transaction costs ($0.02\%$ per leg = $0.04\%$ roundtrip) consume more than $100\%$ of gross returns.
- **Root Cause:** 15m bars are dominated by microstructure noise, tick-level bid-ask bouncing, and intraday mean reversion.
- **Resolution:** Milestone M27 resampled continuous 15m bars into 1-Hour and Half-Day swing bars. Half-Day swings increased average gross moves to 0.65%–1.20%, slashing 2 bps fee drag from 33.3% to 9.03% and turnover by 87.5%.

---

### ISSUE-QUANT-002: Excessive Churn and Drawdown in Sideways / Consolidation Regimes
- **Severity:** Medium
- **Status:** **RESOLVED IN M28 (REGIME CONSENSUS GATING IMPLEMENTED)**
- **Description:** Analysis of strategy equity curves in M26 demonstrates that more than $80\%$ of cumulative strategy drawdown occurs during prolonged sideways consolidation regimes (e.g. Folds 3–6 and Folds 11–13). Unconstrained models oscillate rapidly between LONG and SHORT positions, incurring heavy friction without capturing trending moves.
- **Resolution:** Milestone M28 implemented causal Wilder ADX(14) and Hurst Exponent regime detection. Mandating `NO_TRADE` during sideways consolidation (which comprises 82.2% of market bars) cut turnover by >90%, reduced maximum drawdown from 2.65% to 0.31%, and produced positive net returns (+0.08% overall, +0.51% on untouched holdout).

---

## 2. Market Data & Provenance Deficiencies

### ISSUE-DATA-001: Single-Provider Historical Market Data Dependency
- **Severity:** High (Safety Blocker for `real_market_data_verified`)
- **Status:** **RESOLVED IN M29 (NSE BHAVCOPY ADAPTER VALIDATED)**
- **Description:** Historical candles were originally sourced solely from Groww API without independent secondary verification.
- **Resolution:** Milestone M29 built the official NSE Bhavcopy adapter (`bhavcopy_adapter.py`) with 5.0 bps discrepancy cross-reconciliation, database conflict auditing (`CandleConflictAudit`), and verified zero irreconcilable differences against official closing marks.


---

### ISSUE-DATA-002: Special Trading Sessions (Muhurat Trading) Discontinuity
- **Severity:** Low
- **Status:** **HANDLED BY CALENDAR ENGINE, AUDIT CONTINUOUS**
- **Description:** Special annual trading sessions such as Diwali Muhurat trading occur outside normal market hours (e.g. 18:15–19:15 IST) with low volume. If included in standard 15m intraday sequences, they create irregular overnight gaps.
- **Current Status:** Tagged as `SPECIAL` in `market_candles` and excluded from continuous intraday feature calculations.

---

## 3. Infrastructure & Runtime Notes

### ISSUE-INFRA-001: Localhost Test Container Network Port Isolation
- **Severity:** Low (Operational Note)
- **Status:** **DOCUMENTED**
- **Description:** The PostgreSQL integration test container (`imm-m0-test-pg`) runs on host port `54329`. In strictly isolated sandboxes without external network permissions, connection to host localhost ports requires `BypassSandbox: true` for the test command runner.
- **Resolution:** Explicitly handled in test runner configurations.

---

### ISSUE-INFRA-002: Live Groww Credentials Omission in Test Suite
- **Severity:** Informational
- **Status:** **EXPECTED BEHAVIOR**
- **Description:** `test_integrations.py::test_groww_live_connection` is designed to skip automatically when `GROWW_API_KEY` and `GROWW_API_SECRET` are not set in the environment. This ensures that CI and autonomous agents never attempt unauthenticated or unauthorized broker calls.
- **Status:** Passing with 1 expected skip.
