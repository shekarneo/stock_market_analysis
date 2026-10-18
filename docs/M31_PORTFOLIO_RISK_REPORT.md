# Milestone M31: Portfolio Risk Management, Volatility-Parity Sizing, & Square-Off Report

**Milestone:** M31 Portfolio Risk Management & Position Sizing (Priority P8)  
**Date:** 2026-10-17  
**Author:** Autonomous Engineering & Quantitative Research Agent  
**Module:** `apps/api/app/risk/portfolio_risk.py`  
**Test Suite:** `apps/api/tests/test_m31_portfolio_risk.py` (5 passed in 0.07s)  
**Regression Status:** All 14 tests in `test_risk_ledger.py` passed.  
**Financial Safety Invariants:** All 5 strictly `False` (`forecast_ready = false`, etc.)

---

## 1. Executive Summary & Objective

In quantitative trading, signal direction is only half of the strategy equation. Without principled risk allocation:
1. High-volatility regimes generate outsized dollar losses that overwhelm normal profits.
2. Equal share/lot sizing across instruments causes unbalanced risk concentrations.
3. Overtrading on weak statistical conviction erodes capital through fee churn.
4. Intraday equity/derivatives positions in the Indian market risk penalty liquidation if not closed prior to the exchange auto-square-off window (15:15–15:30 IST).

**The M31 Deliverable:**
We implemented the **Portfolio Risk Management Engine** in [`apps/api/app/risk/portfolio_risk.py`](file:///home/neo/work/personal/stock_market_analysis/apps/api/app/risk/portfolio_risk.py):
- **Volatility-Parity Position Sizing:** Inverse-ATR weighting equalizes dollar volatility risk across trades and market regimes.
- **Fractional Half-Kelly Sizing:** Sizes capital dynamically based on win rate $p$, reward-to-risk $b$, and caps trade risk to a maximum $2.0\%$ of capital. Enforces `NO_TRADE` when Kelly $\le 0$.
- **Indian Exchange Intraday Square-Off Safeguards:** Strict automated timeline enforcing entry cutoffs at 15:10 IST and mandatory square-off at 15:15 IST.

---

## 2. Mathematical Position-Sizing Formulation

### 1. Fractional Half-Kelly Capital Fraction:
$$f^* = \frac{b \cdot p - (1 - p)}{b}$$
$$f_{\text{allocated}} = \min\left(0.5 \times f^*, \;\text{MaxTradeRiskFraction}\right)$$
Where $\text{MaxTradeRiskFraction} = 0.02$ ($2.0\%$).
If $f^* \le 0$, the trade is vetoed (`decision = "NO_TRADE"`).

### 2. Dollar Risk Budget:
$$\text{RiskBudget}_{\text{INR}} = \text{TotalCapital}_{\text{INR}} \times f_{\text{allocated}}$$

### 3. Per-Share Volatility Risk:
$$\text{RiskPerShare} = \max\left(|\text{Entry} - \text{StopLoss}|, \;1.0 \times \text{ATR}_{14}\right)$$

### 4. Discrete Lot Sizing:
$$\text{TargetShares} = \frac{\text{RiskBudget}_{\text{INR}}}{\text{RiskPerShare}}$$
$$\text{RecommendedLots} = \left\lfloor \frac{\text{TargetShares}}{\text{LotSize}} \right\rfloor$$
> **Crucial Risk Invariant:** If $\text{RecommendedLots} < 1$, the trade is strictly rejected (`NO_TRADE`). The system **never rounds up** to exceed the pre-defined risk budget.

---

## 3. Indian Market Intraday Square-Off Timeline

| Time Window (Asia/Kolkata) | Session Status | New Entries Allowed | Auto Square-Off Mandated | Rationale |
| :--- | :--- | :---: | :---: | :--- |
| **09:15 to 15:10 IST** | **`NORMAL_TRADING`** | **YES** | NO | Standard market hours for position entry and exit. |
| **15:10 to 15:15 IST** | **`ENTRY_CUTOFF`** | **NO** | NO | Prevents opening new positions within 5 minutes of square-off. |
| **15:15 to 15:30 IST** | **`MANDATORY_SQUARE_OFF`**| **NO** | **YES** | Mandatory closure of all intraday positions to avoid exchange penalty. |
| **15:30+ IST** | **`MARKET_CLOSED`** | **NO** | NO | Regular cash/derivatives exchange session closed. |

---

## 4. Test Suite Verification

The test suite [`apps/api/tests/test_m31_portfolio_risk.py`](file:///home/neo/work/personal/stock_market_analysis/apps/api/tests/test_m31_portfolio_risk.py) ran 5 tests with **100% pass rate in 0.07s**:
1. `test_volatility_parity_sizing_scales_inversely_with_atr`: Verified that low-volatility regimes (ATR = 50) allocate more lots than high-volatility regimes (ATR = 200), keeping total risk strictly $\le 20,000\text{ INR}$.
2. `test_half_kelly_non_positive_edge_vetoes_trade`: Verified that negative-edge configurations ($p=0.35, b=1.0$) trigger `KELLY_VETO_NON_POSITIVE_EDGE` and clamp lots to 0.
3. `test_lot_size_floor_and_budget_constraints`: Verified that under-capitalized accounts output `BUDGET_BELOW_MINIMUM_LOT_SIZE` rather than rounding up.
4. `test_intraday_square_off_timeline`: Verified timeline transitions across 10:30, 15:12, 15:18, 15:45, and 08:30 IST.
5. `test_m31_safety_invariants_strictly_false`: Verified all 5 financial safety invariants remain strictly `False`.

---

## 5. Hard Financial Safety Boundaries

All five safety invariants remain strictly enforced as **`False`**:
- `forecast_ready = False`
- `real_market_data_verified = False`
- `paper_approved = False`
- `live_approved = False`
- `live_broker_routing_enabled = False`
