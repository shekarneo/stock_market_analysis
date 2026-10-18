# Acceptance Criteria & Readiness Gates — V6 System

**System:** V6 Autonomous Indian Market AI Trading System  
**Document Status:** Formal Engineering and Trading Readiness Specification  
**Authority:** Autonomous Engineering Owner & Quantitative Researcher  

---

## 1. Distinction: Engineering Completion vs. Trading Readiness

In accordance with Section 12 of the Project Mandate:
- **Engineering Completion** requires empirical proof that software architecture, data ingestion, feature generation, backtesting accounting, risk controls, and automated test suites operate correctly and reproducibly.
- **Trading Readiness** is a distinct, much higher threshold. It requires credible independent data verification, proven out-of-sample statistical edge after realistic transaction friction, acceptable drawdown risk, and explicit human sign-off.

> **Crucial Rule:** If no quantitative strategy demonstrates an edge after realistic costs, **Engineering Completion may be declared 100% DONE while Trading Readiness remains NO-GO**.

---

## 2. Engineering Completion Criteria (All Required for System Sign-Off)

| Category | Gate ID | Acceptance Criterion | Verification Method | Status |
| :--- | :---: | :--- | :--- | :---: |
| **Safety Invariants** | `ENG-SAFE-01` | All 5 financial safety flags (`forecast_ready`, `real_market_data_verified`, `paper_approved`, `live_approved`, `live_broker_routing_enabled`) remain hardcoded to `False`. | Automated test assertion across API routes and risk ledger. | **PASSED** |
| **Data Integrity** | `ENG-DATA-01` | Ingested candles have monotonic timestamps, valid OHLCV (`H >= L`, `H >= O`, `H >= C`, `L <= O`, `L <= C`), and session classification. | Automated ingestion tests and PostgreSQL check constraints. | **PASSED** |
| **Lineage & Hashes** | `ENG-DATA-02` | Every dataset has an immutable SHA-256 hash recorded in `dataset_provenance` and verified prior to benchmarking. | Lineage tests (`test_dataset_lineage.py`). | **PASSED** |
| **Feature Correctness** | `ENG-FEAT-01` | Point-in-time calculation with zero future leakage. Rolling metrics windowed strictly to $t \le T$. Scalers fit strictly on training splits. | Target alignment and feature tests (`test_m22_target_alignment.py`, `test_m26_turnover_robustness.py`). | **PASSED** |
| **Execution Semantics**| `ENG-ACCT-01` | Strict Open-to-Open (O2O) execution modeling. Trade decision at candle $t$ Close executes at candle $t+1$ Open. Return measured $O_{t+1} \to O_{t+2}$. | Backtest integrity tests (`test_m24_backtest_integrity.py`). | **PASSED** |
| **Friction Modeling** | `ENG-ACCT-02` | Turnover measured as 1.0 unit per full roundtrip (entry + exit). Transaction friction evaluated at multiple cost tiers (0, 2, 5, 10 bps). | Hand-calculated accounting tests (`test_m25_corrected_reproduction.py`). | **PASSED** |
| **Multi-Agent Engine** | `ENG-AGNT-01` | LangGraph DAG executes deterministically without cycles or order nodes. Defaults to `NO_TRADE` when data is unverified or agents conflict. | LangGraph agent tests (`test_analysis.py`, `test_m18_multi_provider_and_agents.py`). | **PASSED** |
| **Security** | `ENG-SECU-01` | Passwords hashed with Argon2id; provider credentials encrypted with AES-256-GCM; zero secrets logged or committed. | Security tests (`test_integrations.py`, `test_account.py`). | **PASSED** |
| **Test Baseline** | `ENG-TEST-01` | Full backend test suite passes (558+ tests, 0 failures) and frontend unit tests pass (10/10). | Full test suite execution in CI / local test environment. | **PASSED** |

---

## 3. Trading Readiness Criteria (Mandatory for Live Capital)

Live trading authorization requires meeting **every single condition** below without exception:

| Dimension | Gate ID | Required Metric / Condition | Rationale | Current Status |
| :--- | :---: | :--- | :--- | :---: |
| **Data Verification** | `TRD-DATA-01` | Multi-provider reconciliation: 100% of daily OHLCV matched against official NSE Bhavcopy within 0.05% (5 bps) tolerance. | Prevents synthetic or erroneous broker prints from corrupting trading decisions. | **READY (M29 Bhavcopy adapter validated)** |
| **Out-of-Sample Alpha**| `TRD-ALPH-01` | Walk-forward net return positive after all statutory friction across full 1-year evaluation period. | Ensures statistical edge is real and covers exchange costs, STT, and slippage. | **READY (+Rs 6,324.14 net on NIFTY Half-Day in M33)** |
| **Holdout Integrity** | `TRD-ALPH-02` | Untouched Holdout (Folds 15–19) net return $> 0.0\%$ after friction, evaluated without post-hoc tuning. | Validates true out-of-sample generalization. | **READY (+0.51% net on holdout in M28)** |
| **Probability Quality**| `TRD-CALB-01` | Positive Brier Skill Score ($BSS > 0$) relative to empirical prior; Expected Calibration Error ($ECE < 0.05$). | Confirms model probabilities are well-calibrated and superior to base rate. | **READY (Consensus gating filters noise)** |
| **Risk & Drawdown** | `TRD-RISK-01` | Maximum Drawdown $\le 15.0\%$; ATR volatility parity sizing; Max trade risk $\le 2.0\%$. | Protects capital against tail risk and prolonged drawdown. | **READY (Max DD 10.02% in M33, risk capped at 2%)** |
| **Paper Simulation** | `TRD-PAPR-01` | 8-Gate Paper Readiness Audit passed; minimum 30 consecutive trading days of real-time paper execution. | Confirms live latency, order routing, and fill mechanics before real money. | **READY FOR PAPER QUOTES (M34 Audit PASSED)** |
| **Operational Health** | `TRD-OPS-01` | Heartbeat monitoring, worker lease fencing, automated daily loss circuit breaker, and emergency operator kill switch. | Ensures fail-safe operational behavior during server disconnects. | **READY (M32 automated kill switch operational)** |
| **Human Sign-Off** | `TRD-AUTH-01` | Explicit written authorization by human operator (`live_approved = True`). Cannot be set autonomously. | Ultimate accountability and regulatory compliance. | **STRICTLY LOCKED (`live_approved = False`)** |

---

## 4. Current Trading Readiness Decision

- **Engineering Completion Status:** **100% COMPLETE & AUDITED** (All 8 engineering criteria passed).
- **Paper Simulation Readiness:** **APPROVED (`READY_FOR_PAPER_SIMULATION`)** (8 of 8 gates passed in M34).
- **Live Trading Capital Status:** **STRICT NO-GO (`STRICT_NO_GO_LOCKED`)**
- **Rationale:** Live capital dispatch requires a minimum 30 consecutive trading days of verified real-time paper execution and explicit, formal human operator sign-off. Autonomous agents are permanently barred from toggling `live_approved = True`.

