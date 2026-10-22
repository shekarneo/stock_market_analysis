# India Market Master (IMM) — V6

**India Market Master** is an institutional quantitative forecasting, multi-agent consensus, and options strategy desk engineered specifically for the Indian financial markets (NSE, BSE, and MCX).

The platform bridges real-time market data ingestion with higher-timeframe swing modeling, 12-perspective LangGraph multi-agent consensus, Black-Scholes Greeks modeling, and paper simulation under complete Indian statutory taxation.

---

## Architecture Overview

```
                          ┌────────────────────────┐
                          │    Live Market Data    │
                          │ Groww / RBI FX / Yahoo │
                          └───────────┬────────────┘
                                      │
                                      ▼
                          ┌────────────────────────┐
                          │ Data Hygiene & Pipeline│
                          │ Quarantines & Lineage  │
                          └───────────┬────────────┘
                                      │
              ┌───────────────────────┴───────────────────────┐
              ▼                                               ▼
  ┌───────────────────────┐                       ┌───────────────────────┐
  │   12 Specialist AI    │                       │ Quantitative Forecast │
  │    Graph Consensus    │                       │  Logistic & HTF Swing │
  └───────────┬───────────┘                       └───────────┬───────────┘
              │                                               │
              └───────────────────────┬───────────────────────┘
                                      │
                                      ▼
                          ┌────────────────────────┐
                          │ Quant-Agent Confluence │
                          │  Direction & Deadband  │
                          └───────────┬────────────┘
                                      │
                                      ▼
                          ┌────────────────────────┐
                          │    Risk Safety Gate    │
                          │ EV, Sizing & Statutory │
                          └───────────┬────────────┘
                                      │
                                      ▼
                          ┌────────────────────────┐
                          │ Paper Simulation Book  │
                          │ 0.05 Tick & Full Taxes │
                          └────────────────────────┘
```

- **Backend (`apps/api`)**: FastAPI on Python 3.10 with SQLAlchemy, Alembic, SQLite / PostgreSQL, and LangGraph orchestration.
- **Frontend (`apps/web`)**: Next.js 14 desk featuring live tickers, strike matrix, Greeks radar, consensus timeline, and unified tools hubs.
- **Multi-Instrument Coverage**:
  1. **NIFTY 50 (`NIFTY`)**: NSE benchmark index (lot size: 25, strike step: ₹50).
  2. **BSE SENSEX (`SENSEX`)**: BSE blue-chip index (lot size: 20, strike step: ₹100).
  3. **MCX CRUDEOIL MINI (`CRUDEOILMINI`)**: MCX energy commodity (lot size: 10 bbl, strike step: ₹50).

---

## Core Trading Desks & Unified Hubs

### Trade
1. **Overview (`/dashboard`)**: Unified cockpit with executive summary, macro context, trade ticket, and live market tape. Includes the multi-agent consensus desk (`V6Desk`) with Compact and Detailed views (`/dashboard?view=detailed`). The legacy `/analysis` route redirects here.
2. **Live & Auto Trading (`/live`)**: Automated execution monitoring, auto-run intervals, and real-time outcome tracking.
3. **Watchlist & Accuracy (`/watchlist`)**: Tracked suggestions, contract expiry badges, realized exit premiums, and prediction accuracy.
4. **Options & Greeks Desk (`/options`)**: Live strike matrix, ATM detection, Black-Scholes Greeks ($\Delta, \Gamma, \Theta, \mathcal{V}$), and expected value ($EV$).
5. **Positions & Capital (`/risk`)**: Risk limits, risk capital allocation, accounting, and research proposal gates.
6. **System (`/system`)**: Health, data provenance, paper-readiness audit, and diagnostics.

### Tools
- **Forecast & Accuracy (`/forecast`)**: Calibrated probabilities, Brier score tracking, and out-of-sample backtest metrics.
- **Market Data & History (`/history`)**: Candle ingestion, data hygiene, and Bhavcopy reconciliation.
- **Backtest & Walk-Forward (`/backtest` ↔ `/paper`)**: Walk-forward backtesting and paper portfolio simulation.
- **Model Studio & Registry (`/studio` ↔ `/registry`)**: Machine learning model training, lineage, and artifact registry.
- **Settings & API Keys (`/settings` ↔ `/settings/integrations`)**: Operator security, API integrations, and agent model configurations.

---

## Strict Financial Safety Invariants

The platform operates under strict fail-closed safety invariants:
- **Fail-Closed Live Execution**: Real-money broker routing remains locked behind explicit operator authentication, double confirmation, and hardware/software kill switches.
- **Simulation Isolation**: Paper trading simulation is isolated from live broker accounts.
- **Truth in Data**: Never substitute missing, unverified, or null values with zero or invented numbers in financial ledgers or spot tickers.
- **Microstructural Friction Modeling**: All backtest and paper simulation accounting deducts exact Indian statutory charges (STT, NSE turnover fees, SEBI charges, stamp duty, GST, and discrete 0.05 INR tick slippage).

---

## Getting Started

### Prerequisites
- Python 3.10+
- Node.js 18+
- SQLite (default) or PostgreSQL (optional via Docker)

### Quick Start (Local Development)

1. **Configure Environment**:
   ```bash
   cp .env.example .env
   # Ensure OPERATOR_PASSWORD and SESSION_SECRET are set in .env
   ```

2. **Start Backend API**:
   ```bash
   source .venv/bin/activate
   cd apps/api
   uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```
   API Health: http://127.0.0.1:8000/health

3. **Start Frontend Desk** (in a separate terminal):
   ```bash
   cd apps/web
   npm run dev -- --hostname 127.0.0.1 --port 3000
   ```
   Trading Desk: http://127.0.0.1:3000

---

## Running Verification Tests

- **Backend API Tests** (`pytest`):
  ```bash
  PYTHONPATH=apps/api .venv/bin/pytest -p no:launch_testing apps/api/tests/test_v6*.py apps/api/tests/test_analysis*.py apps/api/tests/test_forecasting.py
  ```

- **Frontend Unit Tests** (`node --test`):
  ```bash
  npm test --prefix apps/web
  ```

---

## Documentation

- **[UI Walkthrough (`docs/UI_WALKTHROUGH.md`)](docs/UI_WALKTHROUGH.md)**: Exhaustive documentation of every page, button, dropdown, metric card, and badge across the desk.
- **[Autonomous System Synthesis (`docs/V6_AUTONOMOUS_SYSTEM_SYNTHESIS_REPORT.md`)](docs/V6_AUTONOMOUS_SYSTEM_SYNTHESIS_REPORT.md)**: Milestone M0 through M43 quantitative research and certification report.
- **[Autonomous Project State (`docs/AUTONOMOUS_PROJECT_STATE.md`)](docs/AUTONOMOUS_PROJECT_STATE.md)**: Current system state, dataset SHA-256 hashes, and safety invariant verifications.
- **[Operational Runbook (`docs/PRODUCTION_OPERATIONAL_RUNBOOK.md`)](docs/PRODUCTION_OPERATIONAL_RUNBOOK.md)**: Daily production workflows, session transitions, and emergency procedures.
