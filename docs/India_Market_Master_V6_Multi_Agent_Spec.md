# India Market Master V6 — Multi-Agent Market Analysis & Forecasting Specification

**Purpose:** A source-grounded, risk-first framework for analyzing Indian index markets and related macro drivers. This document preserves the V6 market workflow and expands it into an implementation-ready specification for a multi-agent system built in Cursor.

**Markets covered**
- Indian indices: NIFTY 50, SENSEX, BANK NIFTY
- Options: index CE/PE contracts, option chain, OI, OI change, IV, Greeks, PCR, premium, liquidity and expiry
- Global/macro drivers: US indices, Asian markets, USD/INR, bond yields, central-bank decisions, inflation, growth and risk sentiment
- Commodities: crude oil (including MCX Crude Oil Mini when data is available), gold and other relevant commodities
- Flows and market internals: FII/DII, India VIX, market breadth, sector performance and advance/decline data
- News and event risk: geopolitics, tariffs, central banks, earnings, regulation, shipping/energy disruption and scheduled events

> **Important:** This is an analysis and decision-support framework, not a guarantee of profitable predictions. Options can lose their entire premium. The system must be allowed to return **NO TRADE / INSUFFICIENT DATA** and must never invent prices, news, OI, IV, PCR, volume, or probabilities.

---

## 1. V6 Core Principles

1. **Fresh data first.** Retrieve timestamped data before forming a view.
2. **Validate before interpreting.** Check symbol, exchange, units, timezone, expiry, timestamp, market status and source consistency.
3. **Separate facts from interpretation.** Label information as `CONFIRMED FACT`, `REPORTED / UNVERIFIED`, `INFERENCE`, or `SCENARIO`.
4. **Price action outranks a narrative.** News is a possible driver; observed price, breadth, volume and cross-asset response show how the market is actually reacting.
5. **Bullish and bearish cases are both mandatory.** Actively search for evidence that contradicts the leading view.
6. **A forecast is probabilistic.** Give probabilities for defined horizons and scenarios; do not present a direction as certain.
7. **ML predicts; the LLM explains; deterministic risk controls gate execution.** The LLM must not override risk limits.
8. **No trade is a valid result.** If data is stale, conflicting, illiquid, or the expected payoff is inadequate, return `NO TRADE`.
9. **Never chase losses.** No revenge trading, martingale sizing, or increasing risk to recover a previous loss.
10. **Record and score every forecast.** Track what was known at forecast time, predicted probabilities, actual outcomes, calibration and errors.

---

## 2. Mandatory V6 Workflow

Run the following sequence for every `UPDATE` request:

**DATA → VALIDATION → GLOBAL/MACRO → FRESH NEWS → CRUDE/INR → NIFTY → SENSEX → BANK NIFTY → VIX/BREADTH → FII/DII → OPTIONS/OI → QUANT → PRICE CONFIRMATION → SCENARIOS → INVALIDATION → EXECUTION/RISK → FINAL VOTE → OUTCOME TRACKING**

### Stage 1 — DATA
Collect:
- Current and previous close/open/high/low for each index
- Last traded price (LTP), timestamp and percentage change
- Intraday candles at appropriate intervals (e.g. 1m/5m/15m/60m) and daily history
- Volume and volume profile where available
- India VIX and historical volatility
- Sector indices and constituent contribution data, if available
- FII/DII cash and derivatives flow data with publication date/time
- Option-chain snapshot with expiry, strike, CE/PE LTP, bid/ask, volume, OI, change in OI, IV and Greeks when available
- USD/INR, crude oil, gold, global index futures/indices and bond yields
- Calendar: RBI/Fed decisions, inflation/GDP releases, earnings, expiry, holidays and major scheduled events
- News items with publisher, URL, publication timestamp, event timestamp and verification status

### Stage 2 — VALIDATION
For every data field:
- Store source, exchange/provider, retrieved timestamp, event timestamp (if different), timezone, units and freshness.
- Reject malformed values, impossible prices, duplicate records and mismatched symbols/expiries.
- Cross-check key prices against a second source where feasible.
- Flag discrepancies rather than silently selecting the more convenient value.
- Mark stale or delayed feeds prominently.
- Never infer missing option-chain values from screenshots or headlines unless the value is explicitly visible and legible.
- If critical live data is unavailable, lower confidence or return `INSUFFICIENT DATA`.

**Freshness defaults (configurable):**
- Intraday index/option quotes: ideally under 60 seconds during market hours; clearly label anything older.
- News: preserve both publication time and event time; do not treat an old story newly syndicated as a new event.
- Daily flow data: use the latest officially published session and label the date.
- Historical data: retain vendor and adjustment methodology.

### Stage 3 — GLOBAL / MACRO
Analyze:
- US indices and futures (S&P 500, Nasdaq, Dow, Russell 2000 where relevant)
- Asian/European market direction and global risk sentiment
- US Treasury yields and yield changes
- Dollar strength and USD/INR
- Central-bank commentary and policy expectations
- Inflation, growth, employment, liquidity and credit conditions
- Tariff/trade policy developments
- Event calendar and overnight gaps

For each driver report:
- Current observation and timestamp
- Direction of change
- Possible transmission mechanism into Indian equities
- Evidence for and against the interpretation
- Expected time horizon (intraday, 1–3 sessions, swing)
- Confidence and data limitations

### Stage 4 — FRESH NEWS VERIFICATION
For every market-moving claim:
1. Find the original/primary source if possible (official statement, regulator, government, exchange, company filing or central bank).
2. Verify with at least one independent credible source for consequential claims.
3. Record publication time, event time, source URL and whether the report is confirmed.
4. Separate what happened from what the source says might happen.
5. Search for updates, corrections, denials, ceasefire/negotiation changes, policy clarifications and contrary reports.
6. Assess whether the market likely already priced in the information.
7. Compare headline direction with actual market, crude, FX, yields and volatility reaction.

Classify:
- `CONFIRMED`: primary evidence or sufficiently corroborated reporting
- `REPORTED`: credible reporting, not yet independently confirmed
- `UNVERIFIED`: insufficient corroboration
- `DENIED / CORRECTED`: later evidence disputes or corrects it
- `STALE`: not new; only recirculated
- `RUMOUR`: do not use as a confirmed input

Do not say “no news” unless a meaningful search was actually conducted. Instead say “No material new development found in the sources checked as of [time].”

### Stage 5 — CRUDE OIL / INR / CROSS-ASSET
Track:
- Crude price, benchmark, contract month/expiry, timestamp and percentage move
- Inventory, OPEC+ supply, demand forecasts, refinery activity and shipping risks
- USD/INR direction and volatility
- Gold, yields, dollar and global risk assets
- Whether oil and equities are moving in the expected relationship or diverging

Do not assume that higher crude always means lower Indian equities, or that lower crude guarantees a rally. Describe possible channels and observed confirmation. For MCX Crude Oil Mini, check the exact contract, expiry, lot size, tick size and quote timestamp from the exchange/broker specification before calculating P&L or levels.

### Stage 6 — NIFTY 50
Report:
- Current LTP, change %, open/high/low, previous close and timestamp
- Trend on 5m/15m/1h/daily timeframes
- VWAP, key moving averages and momentum indicators where valid data exists
- Support/resistance zones based on recent price structure, prior session levels, pivots or volume profile
- Gap behavior, opening range, breakouts/breakdowns and failed moves
- Volume confirmation and breadth/sector participation
- Bullish evidence, bearish evidence and what would invalidate each
- Intraday and next-session outlook separately

Do not output precise levels unless they can be traced to current or historical data and a stated method.

### Stage 7 — SENSEX
Use the same analysis as NIFTY, but independently:
- Do not copy NIFTY levels or assume the indices must move identically.
- Compare relative strength, constituent/sector weights and breadth.
- Identify divergence between SENSEX and NIFTY and whether it is confirmed by constituents and volume.
- State whether evidence supports the same directional bias or a different one.

### Stage 8 — BANK NIFTY
Analyze separately:
- Price structure, trend, VWAP, volatility and key levels
- Bank-sector relative strength
- Major banking constituents' contribution where available
- RBI, bond yields, credit/deposit growth, asset-quality and banking-specific news
- Option-chain liquidity and expiry-specific risks
- Divergence versus NIFTY and SENSEX

### Stage 9 — INDIA VIX / BREADTH / SECTORS
Report:
- India VIX current value, change and timestamp
- Advance/decline ratio and breadth by exchange/universe
- Sector leaders and laggards
- Whether index gains/losses are broad-based or concentrated in a few heavyweights
- Volume expansion/contraction and volatility regime
- Gap-and-go, gap-fill, trend day, range day or reversal evidence—with probabilities, not certainty

### Stage 10 — FII / DII / POSITIONING
Report:
- Latest available FII/DII cash market data and its date
- Index/stock futures and options positioning where reliably available
- Net values, units and source methodology
- Distinguish official published data from broker estimates or inferred positioning
- Do not treat one day's flow as a guaranteed next-session signal

### Stage 11 — OPTIONS / OI ENGINE
For each relevant expiry and index:
- Underlying price and quote timestamp
- Expiry date, days to expiry and expiry-day status
- Strike-wise CE and PE LTP, bid/ask spread, volume, OI and change in OI
- IV, delta, gamma, theta and vega where available
- Put-call ratio (PCR), with its exact definition and universe stated
- Highest-OI strikes / possible OI concentrations (“walls”), with caveats
- ATM and nearby strikes; liquidity and spread checks
- Premium movement versus underlying movement
- Implied move / expected range, including methodology and assumptions
- Event, gap and expiry risk

**Interpretation cautions:**
- OI increase alone does not prove writing or a directional view.
- PCR is not a standalone buy/sell signal.
- “Max pain” is not a reliable deterministic price target.
- A high-OI strike is not guaranteed support or resistance.
- Option-chain values must be timestamp-aligned with underlying data.
- Greeks depend on model assumptions and may be vendor-calculated.
- Avoid contracts with inadequate liquidity, wide spreads or stale quotes.

### Stage 12 — QUANT FORECAST
Use separate horizons:
- Intraday (e.g. next 30–60 minutes)
- Rest of session
- Next session
- 3–5 sessions, if historical data supports it

For each horizon, produce:
- Probability of up / range-bound / down
- Expected return or range with uncertainty interval
- Volatility forecast
- Key predictive features and model version
- Data cutoff timestamp
- Baseline forecast and ML forecast
- Calibration status and recent out-of-sample performance
- Confidence tier, with reasons

Probabilities must be generated by calibrated models or transparent rules, not invented by the LLM. If a model is unavailable, label the forecast as qualitative and do not present it as an ML probability.

Suggested model families to evaluate:
- Baselines: persistence, historical base rate, logistic regression, linear models
- Tabular: LightGBM/XGBoost/CatBoost (subject to licensing/deployment constraints)
- Time series: AR/ARIMA or volatility models as baselines; evaluate modern sequence models only against strong baselines
- Volatility: GARCH-family and realized-volatility features where suitable
- Regime detection: transparent clustering/HMM-like approaches only with validation
- News: event classification and sentiment/relevance extraction, with source quality and recency features

Use time-based walk-forward validation. Prevent leakage from future candles, revised data, publication timestamps, survivorship and overlapping labels. Include transaction costs and slippage in strategy evaluation. Do not optimize solely for accuracy; measure calibration, expected value, drawdown and stability.

### Stage 13 — FORECAST FUSION
Combine:
- Market structure / price action
- Quantitative model output
- Options and volatility context
- Macro and cross-asset context
- Verified news and event risk
- Breadth, sector participation and flows

Fusion rules:
- Weights must be configured, trained or validated out of sample—not improvised in prose.
- Show component contributions and conflicts.
- If models disagree materially, reduce confidence and consider `NO TRADE`.
- A news agent cannot override a strong, verified price-based contradiction without explaining the conflict.
- Keep raw predictions and final fused prediction separately for audit.

### Stage 14 — PRICE CONFIRMATION
Before a directional view is promoted to a potential trade:
- Check whether price action confirms the thesis.
- Check volume and breadth.
- Check relevant support/resistance break, retest or rejection.
- Check whether the move is extended and vulnerable to mean reversion.
- Check whether a headline-driven spike is fading.
- Check divergence between NIFTY, SENSEX, BANK NIFTY and global/cross-asset markets.
- Explicitly state the evidence that would falsify the view.

A narrative by itself is never sufficient to enter a trade.

### Stage 15 — SCENARIOS
Always provide at least three scenarios:

| Scenario | Required content |
|---|---|
| Bullish | Trigger/confirmation, target zone methodology, supporting evidence, invalidation |
| Base / range | Expected range, conditions for chop, signals that break the range |
| Bearish | Trigger/confirmation, target zone methodology, supporting evidence, invalidation |

For each scenario include:
- Probability and horizon, sourced from model output or clearly labelled qualitative judgment
- Trigger conditions, not just a predicted level
- Confirmation signals
- Invalidation condition
- Main catalyst and risks
- Expected response if the scenario does not develop

Probabilities should sum to 100% when they are mutually exclusive and exhaustive. If they do not, explain the framework.

### Stage 16 — REVERSAL / CONTRARIAN SCAN
Before finalizing:
- What evidence would make the opposite direction more likely?
- Is the current view based on a single headline or correlated indicators?
- Is the market already positioned for the expected outcome?
- Are there positive catalysts despite negative news, or negative catalysts despite positive news?
- Is price rejecting the supposedly obvious direction?
- Are global futures, INR, crude, yields, breadth or heavyweight stocks contradicting the thesis?
- Is a move due to short covering, profit-taking, a technical rebound or genuine new buying/selling—and what evidence supports that distinction?

Do not assert “short covering” or “operator activity” without evidence.

### Stage 17 — INVALIDATION
Every directional thesis must include:
- Exact invalidation condition or level, with source/method
- What observation would invalidate the macro/news thesis
- What observation would invalidate the price-action thesis
- Time-based invalidation (if the expected move fails to occur)
- Whether the position should be reduced, exited or simply reassessed under the configured risk policy

If invalidation cannot be defined, the setup is not trade-ready.

### Stage 18 — EXECUTION / OPTIONS CONTRACT ENGINE
Only after market analysis and risk checks:
- Identify the actual contract: index, CE/PE, strike, expiry, lot size, quantity and quote time
- Compare ATM/ITM/OTM candidates using delta, liquidity, spread, premium, IV, theta and expiry risk
- Estimate payoff and loss under multiple underlying/IV/time scenarios
- Include brokerage, taxes, fees, slippage and market impact where possible
- Check if the expected move is large enough to overcome costs and theta
- Verify the contract is active and tradable; never assume expiry conventions
- Never imply that an existing option's expiry can be changed. Rolling requires closing/reducing the current position and opening a separate contract, subject to market availability and broker rules.
- Do not recommend a trade solely because the index direction is predicted correctly; contract pricing and time decay matter.

### Stage 19 — RISK ENGINE (NON-NEGOTIABLE)
The deterministic risk engine must be separate from the LLM and must be able to veto every trade.

Required checks:
- Maximum risk per trade and daily loss limit set by the user/configuration
- Maximum portfolio exposure and correlated index exposure
- Maximum number of concurrent positions
- Position size derived from risk budget and defined loss—not from conviction language
- No doubling down, martingale, revenge trading or automatic averaging down
- No new trade if the daily loss limit is hit
- No trade with stale data, unverified critical news, bad spreads or unavailable contract details
- No trade when expected value after costs is non-positive or unvalidated
- Require stop/invalidation and exit plan before entry
- Require human approval for live orders by default
- Paper trading by default; live execution disabled unless explicitly configured and separately approved
- Log every veto and its reason

**Options-specific safeguards:**
- Display maximum premium at risk for long options, including all lots and costs
- Warn that long options may expire worthless
- Stress-test IV crush, theta decay, gaps, slippage and inability to exit at the displayed LTP
- Avoid using a tight stop as a guarantee of maximum loss in a gap or illiquid market
- Never tell the user to increase size to recover a loss
- If position details are missing, do not calculate or assert a precise loss or recovery amount

### Stage 20 — FINAL VOTE / VERDICT
Allowed verdicts:
- `BULLISH BIAS — WAIT FOR CONFIRMATION`
- `BEARISH BIAS — WAIT FOR CONFIRMATION`
- `RANGE / NO DIRECTIONAL EDGE`
- `NO TRADE — RISK / DATA / CONFLICT`
- `INSUFFICIENT DATA`

The verdict must state:
1. Data cutoff and market status
2. NIFTY, SENSEX and BANK NIFTY direction and confidence
3. Bullish and bearish evidence
4. Quantitative forecast, if available
5. Key support/resistance zones and their derivation
6. News verified and not verified
7. Crude/INR/global macro effect
8. Options/OI context with timestamp
9. Main scenarios and probabilities
10. Invalidation conditions
11. Risk-engine result
12. Why a trade is or is not justified

**Do not output “BUY PE” or “BUY CE” as an unconditional conclusion.** If a candidate trade is shown, label it as a conditional scenario, include maximum risk and invalidation, and require the risk engine and configured human approval.

---

## 3. Standard V6 Output Template

```markdown
# India Market Master V6 — [DATE, TIME, IST]

## 0. Data Quality & Market Status
- Market status:
- Data cutoff:
- Source timestamps:
- Missing/stale/conflicting fields:
- Overall data quality: HIGH / MEDIUM / LOW
- Decision: PROCEED / NO TRADE / INSUFFICIENT DATA

## 1. Executive View
- NIFTY:
- SENSEX:
- BANK NIFTY:
- Overall regime:
- Forecast horizon:
- Main driver:
- Main counterargument:
- Verdict:

## 2. Global & Macro
- US / Asia / Europe:
- Yields / USD / USDINR:
- Central banks / macro calendar:
- Tariffs / policy:
- Cross-asset consistency:

## 3. Fresh News — Verified
| Event | Status | Event time | Publication time | Source | Market relevance | Confirming / contrary evidence |
|---|---|---|---|---|---|---|

## 4. Crude, INR & Commodities
- Crude benchmark/contract, expiry, price, timestamp:
- Move and verified drivers:
- USD/INR:
- Gold / yields / dollar:
- India equity transmission:
- What would contradict this read:

## 5. NIFTY 50
- LTP / % / OHLC / timestamp:
- Multi-timeframe trend:
- VWAP / indicators:
- Support/resistance and method:
- Volume / breadth:
- Bullish evidence:
- Bearish evidence:
- Invalidation:

## 6. SENSEX
- LTP / % / OHLC / timestamp:
- Trend and levels:
- Relative strength vs NIFTY:
- Bullish / bearish evidence:
- Invalidation:

## 7. BANK NIFTY
- LTP / % / OHLC / timestamp:
- Trend and levels:
- Banking sector / constituent drivers:
- Bullish / bearish evidence:
- Invalidation:

## 8. VIX, Breadth, Sectors & Flows
- India VIX:
- Advance/decline:
- Sector leaders/laggards:
- FII/DII (latest published date):
- Positioning limitations:

## 9. Options / OI
- Underlying and expiry:
- PCR definition, value and timestamp:
- CE/PE OI and change:
- Key strikes / possible walls:
- ATM IV / Greeks:
- Liquidity/spread:
- Expected move and methodology:
- Expiry/theta/event risks:

## 10. Quant Forecast
| Horizon | Up probability | Range probability | Down probability | Expected range/return | Model/version | Calibration |
|---|---:|---:|---:|---|---|---|

## 11. Scenario Matrix
| Scenario | Probability | Trigger | Confirmation | Target/zone method | Invalidation |
|---|---:|---|---|---|---|

## 12. Contrarian / Reversal Scan
- Strongest argument against the leading view:
- Evidence of divergence:
- Potential priced-in catalyst:
- What would change the verdict:

## 13. Conditional Trade Evaluation (only if eligible)
- Candidate instrument:
- Entry trigger:
- Stop/invalidation:
- Target/exit logic:
- Maximum loss including costs:
- Expected value after costs:
- Liquidity / slippage / theta / IV risks:
- Risk engine: PASS / VETO
- Human approval required: YES

## 14. Final Vote
- Verdict:
- Confidence and basis:
- Reasons to trade / reasons not to trade:
- What to monitor next:
- Explicit statement if no edge exists:

## 15. Outcome Tracking
- Forecast ID:
- Predictions captured before outcome:
- Later realized result:
- Forecast error / calibration:
- Lessons:
```

---

## 4. Multi-Agent Architecture for Cursor

### Design rule
Use agents as **specialized analyzers**, not independent authorities that can each place trades. All agents return structured, timestamped evidence. LangGraph orchestrates the evidence nodes (`docs/LANGGRAPH_ORCHESTRATION_SPEC.md`). The quantitative forecast, fusion, options valuation, risk, and execution are deterministic services in `docs/DESIGN.md` section 5.2. They are not language-model nodes. A deterministic risk engine controls eligibility. Live execution must be disabled by default.

The roster below is unchanged. Items 9, 11, 12, 13, and 15 are services even though this list calls them agents. Do not add a new specialist without amending this section.

### Recommended agents

1. **Market Data Agent**
   - Fetches index, OHLCV, volatility, breadth, sectors and option-chain data.
   - Returns raw data, source, timestamp, units, quality and missing fields.
   - Must not predict direction.

2. **Data Quality Agent**
   - Detects stale feeds, gaps, duplicate candles, impossible values, symbol/expiry mismatches and cross-source discrepancies.
   - Can block downstream analysis when critical fields fail.

3. **Global Macro Agent**
   - Summarizes global indices, yields, dollar, USD/INR, central banks and scheduled events.
   - Explains possible transmission channels without asserting causality without evidence.

4. **News Verification Agent**
   - Searches and corroborates market-moving stories.
   - Returns source URLs, timestamps, status, confidence, corrections and contrary evidence.
   - Cannot treat unverified rumours as facts.

5. **Crude & Cross-Asset Agent**
   - Analyzes crude, FX, gold, yields and global risk indicators.
   - Reports actual observed correlations/divergences and the date/window used.

6. **India Index Technical Agent**
   - Separately analyzes NIFTY, SENSEX and BANK NIFTY.
   - Computes indicators and levels from data, identifies trend and invalidation.
   - Must not fabricate support/resistance.

7. **Breadth & Flows Agent**
   - Analyzes VIX, advance/decline, sectors, constituent contribution and latest FII/DII data.

8. **Options Chain Agent**
   - Analyzes CE/PE OI, change in OI, IV, Greeks, PCR, strike concentrations, spread and expiry risks.
   - States data timestamp and definitions.
   - Never converts OI changes directly into certain bullish/bearish claims.

9. **Quant Forecast Agent**
   - Runs versioned, validated ML/statistical models for each defined horizon.
   - Outputs calibrated probabilities, expected return/range, uncertainty, model version and validation metrics.
   - No LLM-generated probabilities.

10. **Contrarian / Red-Team Agent**
    - Attempts to falsify the current leading view.
    - Finds contradictory price action, contrary news, priced-in expectations and cross-market divergences.
    - Must be run before the final verdict.

11. **Forecast Fusion Agent**
    - Combines structured outputs using validated weights/rules.
    - Shows disagreement and component contributions.
    - Reduces confidence or returns no edge when inputs conflict.

12. **Options Contract Evaluation Agent**
    - Compares candidate contracts under multiple underlying, volatility and time scenarios.
    - Calculates payoff with contract specifications and costs.
    - Does not execute orders.

13. **Deterministic Risk Engine**
    - Code, not an LLM.
    - Applies exposure, loss, liquidity, data-quality, stop/invalidation and expected-value gates.
    - Can only approve or veto a candidate; cannot be overridden by an agent's prose.

14. **Report Agent**
    - Produces the standard V6 Markdown report with citations/source links and a concise verdict.
    - Preserves the difference between observed facts, model outputs and qualitative interpretation.

15. **Outcome & Calibration Agent**
    - Stores forecasts before outcomes occur.
    - Calculates directional accuracy, Brier score, log loss, calibration, return error, drawdown and strategy metrics.
    - Generates evaluation reports and flags model drift.

### Orchestration sequence

The executable sequence is `docs/DESIGN.md` section 9 and `docs/LANGGRAPH_ORCHESTRATION_SPEC.md`. In short: data and quality run first; the quantitative model and the LangGraph evidence graph run as separate paths; fusion, options valuation, and the risk engine run after both and are not graph nodes; paper trading is the default; live orders stay off.

```text
Request / Scheduler
    -> Market data and quality gate
         |                          |
         v                          v
    Quant forecast            LangGraph evidence nodes
    (Python model)            news, macro, crude, three indices,
                              breadth, chain commentary, contrarian
         |                          |
         +------------+-------------+
                      v
                 Fusion service
                      v
            Options valuation service
                      v
              Deterministic risk engine
                      v
           NO TRADE or paper candidate
```

---

## 5. Structured Agent Output Contract

Prefer typed schemas (e.g. Pydantic models) over free-form agent prose.

Example common envelope:
```json
{
  "agent_name": "index_technical",
  "schema_version": "1.0",
  "created_at": "ISO-8601 timestamp with timezone",
  "data_cutoff": "ISO-8601 timestamp with timezone",
  "market_status": "PRE_OPEN | OPEN | CLOSED | UNKNOWN",
  "symbols": ["NIFTY"],
  "source_refs": [
    {
      "source": "provider name",
      "url": "https://...",
      "retrieved_at": "ISO-8601 timestamp",
      "data_timestamp": "ISO-8601 timestamp",
      "status": "PRIMARY | SECONDARY | DERIVED"
    }
  ],
  "quality": {
    "status": "PASS | WARN | FAIL",
    "warnings": []
  },
  "facts": [],
  "interpretations": [],
  "bullish_evidence": [],
  "bearish_evidence": [],
  "scenarios": [],
  "invalidation_conditions": [],
  "missing_data": [],
  "confidence": {
    "tier": "LOW | MEDIUM | HIGH",
    "basis": []
  }
}
```

Quant forecast-specific output:
```json
{
  "symbol": "NIFTY",
  "horizon": "NEXT_SESSION",
  "data_cutoff": "ISO-8601 timestamp",
  "model_name": "model identifier",
  "model_version": "version/hash",
  "probabilities": {
    "up": 0.0,
    "range": 0.0,
    "down": 0.0
  },
  "expected_return": null,
  "prediction_interval": null,
  "volatility_forecast": null,
  "calibration_metrics": {},
  "walk_forward_metrics": {},
  "baseline_comparison": {},
  "warnings": []
}
```
Probabilities above are placeholders, not example forecasts. Validate that probabilities are numeric, in `[0,1]`, and sum to `1` within tolerance when categories are mutually exclusive.

---

## 6. ML/Data Science Requirements

### Data and labels
- Use point-in-time data. A feature must only use information available by the forecast cutoff.
- Define labels explicitly for each horizon (e.g. return threshold after costs, not vague “up”).
- Decide how to classify small moves as range/neutral.
- Avoid overlapping label leakage or account for it in validation.
- Preserve corporate actions, index constituent changes and contract roll/expiry details as appropriate.
- Record the data vendor and revisions.

### Validation
- Use chronological train/validation/test splits and walk-forward evaluation.
- Do not randomly shuffle time-series data.
- Compare to naive baselines.
- Include brokerage, taxes, slippage and realistic fills in strategy backtests.
- Report performance by volatility regime, trend/range regime, event days and time of day.
- Use probability calibration (e.g. reliability curves, Brier score, log loss).
- Evaluate false-confidence failures, not just correct calls.
- Track drawdown, turnover, exposure and tail loss—not only win rate.
- Keep a final untouched test period.
- Run paper trading before any live use.

### Model governance
- Version datasets, feature definitions, models, prompts, agent schemas and fusion weights.
- Store every forecast before the market outcome is known.
- Prevent the report agent from changing model probabilities.
- Track drift and suspend models when quality degrades.
- Retraining must not automatically promote a model without evaluation.
- Maintain a complete audit trail of inputs, outputs, decisions and vetoes.

---

## 7. Data Providers and Source Policy

Choose providers based on availability, exchange permissions, cost, latency, licensing and reliability. Possible categories:
- Broker API for live quotes, historical candles and order/position data
- Exchange publications for official contract specifications, market notices and published participant data
- Official central-bank, government, regulator and company sources for primary news
- Credible news providers for corroboration and context
- Licensed historical datasets for backtesting

Do not assume every API provides full option Greeks, reliable historical option-chain snapshots, or exchange-grade tick data. Verify the provider's schema and terms. Do not scrape restricted data or violate provider/exchange terms. Cache data with retrieval timestamps and handle API limits/retries safely.

---

## 8. Implementation Plan in Cursor

The milestone table in `docs/IMPLEMENTATION_PLAN.md` is the source of truth. The phases below are the original outline. Where they differ from that table, the table wins.

### Phase 1 — Reliable V6 report, no trading
- Build provider interfaces and normalized schemas.
- Fetch and validate market data.
- Produce the V6 report in Markdown.
- Add source links, timestamps and missing-data warnings.
- Add a replay mode for historical sessions.
- No orders or broker write permissions.

### Phase 2 — Deterministic analytics
- Implement indicators, levels, breadth and option-chain metrics in tested Python modules.
- Add unit tests for calculations, timezone conversion, expiry handling and contract multipliers.
- Ensure identical input data produces identical deterministic outputs.

### Phase 3 — Forecast models
- Establish baselines, define labels and horizons.
- Add walk-forward evaluation, calibration and cost-aware backtesting.
- Store model version, cutoff and forecast result for every run.
- Keep qualitative LLM views separate from numerical model outputs.

### Phase 4 — Multi-agent orchestration
- Add specialized agents with typed outputs and explicit tool permissions.
- Run agents in parallel only when their input dependencies allow it.
- Add retries, timeouts, token/cost limits, structured logging and graceful degradation.
- Require the red-team agent and risk engine before a final verdict.

### Phase 5 — Paper trading
- Simulate fills, slippage, costs and expiry behavior.
- Compare recommendations against a no-trade baseline.
- Review all rejected trades and false-confidence predictions.
- Do not enable live execution based on a few successful days.

### Phase 6 — Optional controlled live integration
- Disabled by default.
- Separate read-only analysis credentials from order-placement credentials.
- Require explicit human confirmation for each order initially.
- Enforce risk limits on the server side, not only in prompts.
- Add kill switch, daily loss lockout, idempotency, order reconciliation and alerting.
- Never permit an LLM to bypass the risk engine or increase limits.

---

## 9. Acceptance Tests / Definition of Done

The system is not ready until tests prove:
- Stale/missing price data causes a warning or blocks the decision.
- Conflicting sources are surfaced, not silently merged.
- Unverified breaking news is labelled and cannot be treated as confirmed.
- Every claim has a source or is explicitly labelled an inference.
- The report shows data cutoff and market status.
- NIFTY, SENSEX and BANK NIFTY are analyzed independently.
- Option expiry, strike, CE/PE, lot size and quote time are validated.
- Missing IV/Greeks/OI fields are not fabricated.
- Scenario probabilities are validated and traceable to a model or clearly qualitative.
- The red-team agent reports counterevidence.
- The risk engine vetoes trades that breach limits.
- A daily-loss lockout blocks new positions.
- Paper mode cannot accidentally place live orders.
- Forecasts are saved before outcomes and evaluated later.
- Backtests use chronological splits and realistic costs.
- Reports can return `NO TRADE` and `INSUFFICIENT DATA`.

---

## 10. Final Operating Rule

The purpose of V6 is **not** to always predict a direction or always produce a trade. It is to improve decision quality by combining verified data, independent analysis, calibrated forecasts, explicit counterarguments and strict risk controls.

A valid final answer may be:
- Bullish, but wait for price confirmation.
- Bearish, but wait for price confirmation.
- Range-bound with no directional edge.
- No trade because the evidence conflicts.
- Insufficient data because critical feeds are stale or unavailable.

**The system must optimize for reliable, auditable decisions and controlled risk—not confident-sounding predictions.**
