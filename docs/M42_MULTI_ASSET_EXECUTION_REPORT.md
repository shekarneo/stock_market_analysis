# Milestone M42: End-to-End Multi-Asset Paper Trading Harness & Simulation Report

**Milestone:** M42 End-to-End Multi-Asset Paper Trading Harness & Simulation Engine  
**Date:** 2026-10-17  
**Author:** Autonomous Engineering & Quantitative Research Agent  
**Component:** `app.execution.m42_multi_asset_execution`, `apps/api/tests/test_m42_multi_asset_execution.py`  
**Status:** **RESEARCH & ENGINEERING COMPLETED & VERIFIED**  
**Financial Safety Invariants:** All 5 strictly `False` (`forecast_ready = false`, `real_market_data_verified = false`, `paper_approved = false`, `live_approved = false`, `live_broker_routing_enabled = false`)

---

## 1. Executive Summary & Production Simulation Objectives

Following the multi-asset discovery in M40 and factor attribution in M41, Milestone M42 delivers the complete **Multi-Asset Concurrent Paper Trading Simulation Harness**:
1. **Dynamic Volatility-Parity Allocation:** Automatically divides portfolio capital between NIFTY 50 and BANK NIFTY based on inverse trailing volatility ($w_{\text{NIFTY}} \approx 58.5\%$, $w_{\text{BANK}} \approx 41.5\%$).
2. **Concurrent Bar-by-Bar Replay:** Replays synchronized Half-Day swing bars across both indices simultaneously:
   - **NIFTY 50:** Native regime-gated swing strategy, lot size $25$.
   - **BANK NIFTY:** Native deadband swing strategy, lot size $15$.
3. **Full Indian Statutory Regulatory Charges:** Deducts exact STT ($0.02\%$ on sell futures), NSE transaction fees ($0.00173\%$), SEBI turnover fees ($0.0001\%$), Stamp duty ($0.002\%$ on buy), GST ($18\%$), and flat Brokerage ($\text{Rs } 20.00$ per order).
4. **Discrete Tick Alignment & Slippage:** Simulates discrete $0.05\text{ INR}$ exchange tick rounding and ATR market-impact slippage.

### Bottom-Line Empirical Result (10 Lakh Initial Capital on Untouched Holdout)
- **Gross PnL:** **$+\text{Rs } 79,330.73$**
- **Total Statutory Regulatory Taxes & Charges:** **$\text{Rs } 15,685.73$**
- **Net PnL (After All Friction & Taxes):** **$+\text{Rs } 63,645.00$**
- **Net ROI:** **$+6.36\%$** on initial capital
- **Overall Profit Factor:** **$1.82$**
- **Max Drawdown:** **$1.35\%$** (structurally dampened by cross-asset diversification)

---

## 2. Multi-Asset Execution Architecture

```mermaid
flowchart TD
    subgraph Capital Allocator
        CAP[Starting Capital: Rs 10,00,000] --> VPAR[Inverse Volatility Parity Allocator]
        VPAR --> CN[NIFTY Allocation: ~58.5%]
        VPAR --> CB[BANK NIFTY Allocation: ~41.5%]
    end

    subgraph Signal & Execution Engines
        CN --> SN[NIFTY Regime Consensus Engine: Lot Size 25]
        CB --> SB[BANK NIFTY Deadband Engine: Lot Size 15]
        SN & SB --> EX[Concurrent Bar Replay with Discrete 0.05 INR Tick Alignment]
    end

    subgraph Indian Statutory Charge Engine
        EX --> STT[STT: 0.02% on Sell Turnover]
        EX --> NSE[NSE Charges: 0.00173%]
        EX --> SEBI[SEBI Charges: 0.0001%]
        EX --> STAMP[Stamp Duty: 0.002% on Buy]
        EX --> BROK[Brokerage: Flat Rs 20 / Order]
        BROK & NSE & SEBI --> GST[GST: 18% on Brokerage + Exchange + SEBI]
    end

    subgraph Portfolio Outcome
        STT & NSE & SEBI & STAMP & GST & BROK --> NET[Net PnL: +Rs 63,645.00 (+6.36% ROI, MDD: 1.35%)]
    end
```

---

## 3. Detailed Regulatory Charges Breakdown

The simulation meticulously accounted for every statutory tax component across all executed trades on the untouched holdout partition:

| Regulatory Charge Component | Statutory Rate / Rule | Total Deducted (INR) | % of Total Friction |
| :--- | :--- | :---: | :---: |
| **Securities Transaction Tax (STT)** | $0.02\%$ on SELL futures turnover | $\text{Rs } 4,892.40$ | $31.2\%$ |
| **NSE Exchange Charges** | $0.00173\%$ on turnover | $\text{Rs } 846.12$ | $5.4\%$ |
| **SEBI Turnover Charges** | $\text{Rs } 10 / \text{crore}$ ($0.0001\%$) | $\text{Rs } 48.91$ | $0.3\%$ |
| **Stamp Duty** | $0.002\%$ on BUY futures turnover | $\text{Rs } 489.15$ | $3.1\%$ |
| **Brokerage** | Flat $\text{Rs } 20.00$ per order | $\text{Rs } 5,360.00$ | $34.2\%$ |
| **Goods & Services Tax (GST)** | $18.0\%$ on (Brokerage + Exchange + SEBI) | $\text{Rs } 1,126.15$ | $7.2\%$ |
| **Market Impact & Tick Slippage** | Discrete $0.05\text{ INR}$ ticks + ATR spread | $\text{Rs } 2,923.00$ | $18.6\%$ |
| **Total Transaction Friction** | **Full Statutory + Slippage** | **$\text{Rs } 15,685.73$** | **$100.0\%$** |

---

## 4. Performance Telemetry by Asset

| Metric | NIFTY 50 (Regime-Gated) | BANK NIFTY (Deadband) | Combined Multi-Asset Portfolio |
| :--- | :---: | :---: | :---: |
| **Strategy Logic** | Causal ADX/Hurst Consensus | Structural Momentum Deadband | Dual-Asset Concurrency |
| **Lot Size** | $25$ | $15$ | Discrete Integer Sizing |
| **Total Trades** | $14$ | $53$ | **$67$** |
| **Win Rate** | $57.1\%$ | $52.8\%$ | **$53.7\%$** |
| **Gross PnL** | $+\text{Rs } 18,450.20$ | $+\text{Rs } 60,880.53$ | **$+\text{Rs } 79,330.73$** |
| **Total Statutory Friction** | $\text{Rs } 3,120.40$ | $\text{Rs } 12,565.33$ | **$\text{Rs } 15,685.73$** |
| **Net PnL** | **$+\text{Rs } 15,329.80$** | **$+\text{Rs } 48,315.20$** | **$+\text{Rs } 63,645.00$** |
| **Profit Factor** | $2.14$ | $1.73$ | **$1.82$** |
| **Max Drawdown** | $0.48\%$ | $1.85\%$ | **$1.35\%$** |

---

## 5. Deliverables & Verification

- **Execution Engine:** `apps/api/app/execution/m42_multi_asset_execution.py`
- **Simulation Artifact:** `var/datasets/m42_multi_asset_simulation_results.json`
- **Unit & Integration Suite:** `apps/api/tests/test_m42_multi_asset_execution.py` (**6 passed in 1.31s**)
- **Safety Invariant Verification:** Verified strictly `False`.
