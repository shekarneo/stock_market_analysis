# India Market Master (IMM) V6 — Comprehensive UI Walkthrough & Option Reference

> **Document Status**: Complete & Canonical  
> **Last Synchronized**: October 2026 (IMM V6 Architecture)  
> **Maintenance Invariant**: Whenever any page, component, navigation link, form field, button, toggle, or metric inside `apps/web/` is modified, added, or relocated, this document **must** be updated concurrently (enforced by `.agents/rules/ui-documentation.md` and `AGENTS.md`).

---

## Table of Contents
1. [Platform Architecture & Layout Overview](#1-platform-architecture--layout-overview)
2. [Global Persistent Shell & Controls](#2-global-persistent-shell--controls)
3. [Authentication & Operator Identity](#3-authentication--operator-identity)
4. [Primary Trading Desk Pages](#4-primary-trading-desk-pages)
   - [4.1 Overview Desk (`/dashboard`)](#41-overview-desk-dashboard)
   - [4.2 Multi-Agent Analysis Desk (`/analysis`)](#42-multi-agent-analysis-desk-analysis)
   - [4.3 Live & Auto Trading Desk (`/live`)](#43-live--auto-trading-desk-live)
   - [4.4 Watchlist & Accuracy Desk (`/watchlist`)](#44-watchlist--accuracy-desk-watchlist)
   - [4.5 Multi-Horizon Forecast Desk (`/forecast`)](#45-multi-horizon-forecast-desk-forecast)
   - [4.6 Options Strategy & Greeks Desk (`/options`)](#46-options-strategy--greeks-desk-options)
   - [4.7 Positions, Risk & Capital Allocation (`/risk`)](#47-positions-risk--capital-allocation-risk)
   - [4.8 System Architecture & Paper Readiness Audit (`/system`)](#48-system-architecture--paper-readiness-audit-system)
5. [Tools & Diagnostics Pages](#5-tools--diagnostics-pages)
   - [5.1 Historical Market Data & Quarantine (`/history`)](#51-historical-market-data--quarantine-history)
   - [5.2 Model Studio & Benchmarking (`/studio`)](#52-model-studio--benchmarking-studio)
   - [5.3 Walk-Forward Backtesting (`/backtest`)](#53-walk-forward-backtesting-backtest)
   - [5.4 Model Registry & Governance (`/registry`)](#54-model-registry--governance-registry)
   - [5.5 Paper Trading Book & Replay (`/paper`)](#55-paper-trading-book--replay-paper)
   - [5.6 Account & Operator Profile (`/settings`)](#56-account--operator-profile-settings)
   - [5.7 API Keys & Broker Integrations (`/integrations` & `/settings/integrations`)](#57-api-keys--broker-integrations-integrations--settingsintegrations)
6. [Global Status Badges, Indicators & Glossary](#6-global-status-badges-indicators--glossary)
7. [UI Maintenance Protocol for Developers and Agents](#7-ui-maintenance-protocol-for-developers-and-agents)

---

## 1. Platform Architecture & Layout Overview

**India Market Master (IMM)** is an autonomous, quantitative forecasting and options trading desk engineered specifically for the Indian financial markets.

### Supported Tradable Instruments
1. **NIFTY 50 (`NIFTY`)**: National Stock Exchange of India (NSE) benchmark equity index (50 large-cap stocks).
2. **BSE SENSEX (`SENSEX`)**: Bombay Stock Exchange (BSE) benchmark equity index (30 blue-chip stocks).
3. **CRUDEOIL MINI (`CRUDEOILMINI` / `CRUDEMINI`)**: Multi Commodity Exchange of India (MCX) energy commodity future/option contract.

Lot size, strike step and tick size are defined once in the backend instrument master (`apps/api/app/instrument_specs.py`, reviewed date in `SPECS_REVIEWED_ON`) and served to the UI by `GET /api/forecasting/instruments` (`contract_lot_size`, `strike_step`). No page hardcodes them; where the catalog has not loaded, lot and step show `N/A` and strike matrices are not drawn. Re-check the master whenever the exchange revises lot sizes.

### Design System & Layout Rules
- **Color Palette**: Dark theme using tailored CSS variables (`--bg: #090d16`, `--card: #0f172a`, `--card-subtle: #131c31`, `--line: rgba(255, 255, 255, 0.08)`, `--ink: #f8fafc`, `--accent: #38bdf8`).
- **Two-Column Responsive Grid**: Left rail navigation (`240px` fixed desktop) + Main workspace canvas (`min-width: 0`).
- **Sticky Live Sync Bar**: Top header (`z-index: 100`) sticky across all pages for constant real-time market synchronization.

---

## 2. Global Persistent Shell & Controls

The Shell wraps every page in the application.

### 2.1 Top Global Market Sync Bar
Located at the top of the canvas on all screens:
- **Market Session Indicator**:
  - `🟢 NSE/BSE LIVE SESSION`: Displayed when current IST time is between 09:15 AM and 03:30 PM on non-holiday weekdays.
  - `⚡ MCX LIVE · EQUITY CLOSED`: Displayed when Indian equity markets have closed, but MCX commodity trading is open (09:00 AM – 11:30 PM IST).
  - `🌙 MARKETS CLOSED (POST-CLOSE CONTEXT)`: Displayed when all domestic exchanges are closed; indicates that metrics represent post-close settlement prices.
- **Compact Instrument Selector (`<InstrumentSelector compact />`)**:
  - Horizontal pill buttons for `NIFTY 50`, `BSE SENSEX`, and `CRUDEOIL MINI`.
  - Shows real-time Last Traded Price (LTP) with currency formatting (e.g., `₹23,146.15`).
  - Clicking any pill immediately switches the global active instrument across all components on the current page.
- **Sync Status**: Displays the exact Indian Standard Time of the most recent backend data sync (e.g., `Synced 09:15 pm IST`).
- **Auto-fetch Dropdown (`#poll-interval-select`)**:
  - Controls how frequently the frontend polls the backend `/api/market/live` endpoint:
    - `Every 15s (Fast)`: Recommended during active trading hours for rapid quotes.
    - `Every 30s`: Standard real-time intraday monitoring.
    - `Every 1 min`: Balanced default interval for standard research.
    - `Every 2 mins`: Low-overhead background monitoring.
    - `Every 5 mins`: Minimal network activity.
    - `Paused`: Completely disables automated background polling.
- **`↻ Fetch Now` Button**:
  - Immediately triggers an on-demand quote retrieval from the Groww API backend and updates all open pages without reloading.
  - Displays `↻ Syncing…` while the request is in flight.

### 2.2 Left Sidebar Navigation Rail
- **Brand Header**: `IMM` gradient mark + **India Market Master** title + subtitle.
- **Section `TRADE`** (6 primary operational destinations):
  1. `Overview`: Unified executive cockpit with instant mode toggle between Compact Cockpit and Detailed Analysis Desk.
  2. `Live & Auto Trading`: Live bot execution matrix, order book, and real-time risk controls.
  3. `Watchlist & Accuracy`: Historical tracking of suggestions against live spot moves.
  4. `Options`: Interactive strike matrix, Black-Scholes Greeks, and spread strategies.
  5. `Positions & Capital`: Ledger capital allocation, risk limits, and gate blockers.
  6. `System`: Health checks, 8-gate readiness audit, and data provenance.
- **Section `TOOLS`** (5 consolidated engineering, forecasting & governance hubs):
  - **Collapsible Toggle**: Click `Tools Show (5) ▾` to expand; click `Tools Hide ▴` to collapse.
  - Automatically expands if navigating directly to any tool page (`/forecast`, `/history`, `/backtest`, `/paper`, `/studio`, `/registry`, `/settings`, `/settings/integrations`).
  - When expanded, reveals:
    1. `Forecast & Accuracy` (`/forecast`): Multi-horizon quantitative probability distributions, out-of-sample Brier skill score calibration, and approved forecast models hub.
    2. `Market Data & History` (`/history`): Interactive historical candle charts, data health audit, historical imports, and collapsible Groww/quarantine diagnostics.
    3. `Backtest & Walk-Forward` (`/backtest` & `/paper`): 19-fold walk-forward validation, factor attribution, and a unified switcher to `Paper Ledger & Intent Audit Replay` (`/paper`).
    4. `Model Studio & Registry` (`/studio` & `/registry`): Model versioning, side-by-side comparisons, and a unified switcher to `Model Registry & Execution Slots` (`/registry`).
    5. `Settings & API Keys` (`/settings/integrations` & `/settings`): Broker/LLM credential configuration, AI Agent model mapping, and a unified switcher to `Operator Profile & Account` (`/settings`).
- **Rail Footer**:
  - Signed-in user identity: Shows display name or username.
  - `Log out` button: Clears session cookie and redirects to `/`.
  - Regulatory safety note: *"The book is standing aside. This desk shows the call and does not send an order."*

### 2.3 ResearchBoard Safety & Execution Status Strip (`<StatusStrip />`)
Located immediately beneath the page header across trading desks (`/dashboard`, `/risk`, `/system`, etc.):
- **`Experimental paper`**: Displays `Enabled` (green) when the runtime mode is `PAPER`, virtual risk controls (`risk_capital_inr > 0`, position limits, trade risk fraction, daily loss fraction) are configured, and the kill switch is disarmed. Displays `Blocked` if virtual controls are missing.
- **`Forecast evaluation`**: Displays `Active` (green) confirming that 12-agent consensus generation, multi-horizon probabilistic forecasts, and post-horizon outcome scoring are operational.
- **`Data verification`**: Displays `Unverified` (honest provenance label confirming experimental inputs without vendor certification) or `Verified`.
- **`Live broker`**: Displays `Locked` (muted gray) confirming fail-closed execution safety where live broker routing is strictly disarmed (`live_order_calls = 0`).
- **`Kill switch`**: Displays `OFF` (normal operational state) or `ON` (immediate fail-closed emergency circuit breaker).
- **`Simulated fills`**: Displays `None persisted` or `Persisted` tracking whether simulated virtual executions have been journaled in `PaperAccountEvent`.

---

## 3. Authentication & Operator Identity

### 3.1 Sign In Page (`/`)
- **Purpose**: Authenticates the operator into the trading system.
- **Security Architecture**: Single-operator design; session token saved in secure HTTP-only cookie with CSRF protection (`imm_csrf`).
- **Form Controls**:
  - `Username`: Required only if an operator account has been created in the SQLite database.
  - `Password`: Salty PBKDF2 verification against database or fallback local environment password.
  - `Sign in` button: Submits credentials; disabled while busy or password is empty.
  - `Create the operator account` link: Visible only if no operator account exists yet.
  - `Signed in` state view: Displays welcome card with buttons to `Open the desk` (`/dashboard`), view `Account` (`/settings`), or `Log out`.

### 3.2 Create Account Page (`/signup`)
- **Purpose**: First-time initialization of the local operator credentials in SQLite.
- **Options & Controls**:
  - `Username`: Must be at least 3 characters.
  - `Display name`: Human-readable name used across the UI.
  - `Password`: Minimum 8 characters; salted with PBKDF2 before storage.
  - `Confirm password`: Validated for strict match with password.
  - `Create account` button: Creates operator profile and redirects to `/settings`.
  - Lock Constraint: Once created, this page permanently closes (`The operator account already exists.`).

---

## 4. Primary Trading Desk Pages

### 4.1 Overview & Analysis Cockpit (`/dashboard`)
- **Purpose**: The unified single-pane trading cockpit combining a high-level visual market overview with an expandable, deep institutional 8-agent analysis desk. Eliminates disjoint navigation by integrating compact visual meters with full audit dossiers on a single screen.
- **Unified Cockpit Mode Switcher Bar**:
  - Located at the top of the desk to seamlessly toggle between visual summary and institutional depth:
    1. `Mode: ⚡ Compact Cockpit` (Default): Streamlined single-pane view featuring multi-instrument tape, live candlestick forward trajectory forecasts, visual 12-agent consensus meters, order ticket, and market snapshots without dense text walls.
    2. `Mode: 🔬 Detailed Analysis Desk (8 Agents)`: Full institutional workstation (merged from the previous `/analysis` page) with sub-tabs for `🤖 Multi-Agent Decision Desk & Signals` (`V6Desk`) and `🧠 Institutional Intelligence Hub & Greeks` (`V6IntelligenceHub`).
  - **URL State Synchronization**: Supports `?view=detailed` and `?view=compact` query parameters; navigating to `/analysis` automatically forwards to `/dashboard?view=detailed`.
  - **Quick Action Links**: Direct links to `⚡ Live Trading →` (`/live`), `🎯 Watchlist →` (`/watchlist`), `📈 Forecast Tools →` (`/forecast`), and `Options →` (`/options`).

- **Compact Cockpit View Components (`viewMode === "compact"`)**:
  1. **Active Posture Ribbon**:
     - Visual badge indicating current posture (`Active Posture`, `NO TRADE`).
     - Dynamic status message detailing whether virtual paper execution is active with configured risk controls or blocked pending configuration.
  2. **Multi-Instrument Overview Card (`<MultiInstrumentOverviewCard />`)**:
     - 3-card comparison grid for NIFTY 50, SENSEX, and CRUDEOIL MINI.
     - Displays Spot LTP, Day Change (pts & %), Session Phase (`OPEN` / `CLOSED`), Trading Hours, Data Source, and options support status.
  3. **Live Candlestick & Forward Projected Trend Chart (`<PredictedTrendChart />`)**:
     - Embedded directly on the overview desk to provide visual price context.
     - Renders verified historical candlesticks (selectable 20, 35, or 50 bars), live streaming spot quotes, vertical cyan `NOW (Live Spot)` boundary line, forward projected 4-step trajectory path, expanding $\pm 1\sigma$ volatility confidence corridor, and target/stop badges.
     - The projection, target, stop and `P(Up)` appear **only** when the live forecast is `ACTIVE`. Otherwise the chart shows candles only, `P(Up): N/A`, and a `No projection: <status>` label (hover for the reason, e.g. `STALE_FEATURES`, `NO_FITTED_MODEL`, `MODEL_NOT_DEPLOYED`). No default direction or probability is ever drawn.
  4. **Visual Multi-Agent Decision & Execution Cockpit (`<VisualAgentDecisionCard />`)**:
     - **Purpose**: Translates complex mathematical, macro, order flow, and regime assessments across 8 implemented LangGraph specialist agents and 4 research reference desks into high-impact visual indicators, meters, and cards instead of dense text paragraphs.
     - **Execution & Context Toolbar**:
       - `Badge Row`: `🤖 8 SPECIALIST AGENTS · 4 RESEARCH DESKS` and `DETERMINISTIC CONSENSUS` clearly distinguishing implemented agents from research reference entries.
       - `Active Underlying Indicator`: Displays current symbol (e.g. `NIFTY`).
       - `Analysis Cycle ID & Timestamp Badge`: Displays `🕒 Cycle: [id] · HH:MM:SS IST` dynamically when analysis is available, explicitly binding consensus score, uncertainty, vetoes, and forecast probability to the active evaluation cycle.
       - `Instrument Selector Chips`: Instant toggles for `NIFTY`, `SENSEX`, and `CRUDE` syncing with `MarketDataContext`.
       - `⚡ Run Live Analysis` Button: One-click CTA that triggers on-demand `POST /api/market-analysis` across all 8 specialist agents and simultaneously refetches the live statistical forecast (`/api/forecasting/live-trend-chart`) for the selected model with an animated loading spinner (`Synthesizing Specialists…`).
       - `🔬 Detailed Desk ▾` Quick Button: Instantly expands into the detailed 8-agent analysis desk.
     - **Visual Executive Verdict Deck**:
       - `Core Trade Decision Card`: High-impact stance badge (`AWAITING ANALYSIS (NO TRADE)` prior to running, or `STAND ASIDE (NO TRADE)`, `🟢 STRONG BUY CE`, `🔴 STRONG BUY PE` post-run). When backend decision is `NO_TRADE`, or any active gating vetoes are present, strictly preserves `STAND ASIDE (NO TRADE)` and disables trade action eligibility. Includes strict execution gating status badge (`⏸ Awaiting Analysis Cycle` when idle, `🔒 Deadband / Safety Gated (NO TRADE)` when gated or vetoed, or `🔒 Live Routing Disabled (Paper Only)`). Never falsely claims active live execution.
       - `Consensus Spectrum Meter`: Horizontal visual spectrum bar (-1.0 to +1.0) with Red-to-Green gradient and dynamic pointer showing exact net directional score (e.g. `+0.45 Bullish`, `0.00 Neutral`, or `— Not Run` prior to analysis execution).
       - `Bayesian Epistemic Gate Meter`: Safety progress bar comparing composite epistemic uncertainty against the backend's true `0.45` cutoff threshold (`✓ Uncertainty Safe` vs `⚠️ Safety Veto Engaged`, or `UNAVAILABLE / 0.45 Limit` prior to execution).
       - `Quant-Agent Confluence Card`: Visual confluence badge comparing machine learning probabilities (e.g. `50% P(Up)`) against specialist consensus to flag alignment or veto divergence (`🟢 High Confluence (Long)`, `🔴 High Confluence (Short)`, or `🔵 Neutral Deadband (48%–52%)`). Explicitly displays the active model name (e.g. `ML Model: CHAMPION · 15m Horizon`). Strictly anchors P(Up) to the report's active cycle to prevent cross-cycle mixing with asynchronous background queries. When not yet evaluated, displays `— P(Up)` and `⏸ Awaiting Forecast Data`.
     - **Active Risk & Quorum Vetoes Alert Banner**:
       - Appears dynamically whenever one or more deterministic risk or participation vetoes fire.
       - Header: `🛡️ ACTIVE GATING VETOES (X Triggered — All Trades Blocked)`.
       - Renders individual crimson code tags for every active veto (e.g., `⛔ INSUFFICIENT_DIRECTIONAL_PARTICIPATION`, `⛔ EXCESSIVE_EPISTEMIC_UNCERTAINTY`, `⛔ CORE_SPECIALIST_CONFLICT`, `⛔ REGIME_SIDEWAYS_CONSOLIDATION`, `⛔ UNVERIFIED_DATA_PROVENANCE`, `⛔ INSUFFICIENT_SPECIALIST_WEIGHT`).
     - **Execution Dimensions & Quorum Truth Strip**: Dedicated telemetry row detailing all execution dimensions and specialist quorum:
       - `● Ingestion: Active`: Indicates live quote ingestion is actively streaming spot snapshots.
       - `● Forecast: Evaluated (M15)` / `● Forecast: Snapshot Ready` / `○ Forecast: Pending`: Reflects whether M15 statistical forecasting has run.
       - `● Paper Execution: Disarmed / Gated`: Truthfully indicates experimental paper trading is disarmed.
       - `🔒 Live Broker: Hard Locked (Blocked)`: Invariant fail-closed lock asserting that real broker routing is unconditionally blocked.
       - `● Quorum: X/6 Reporting`: Displays reporting specialists out of configured quorum denominator (6).
       - `● Participation: Y Voters (Z% / Min 33%)`: Reports count of active directional voters ($N_{\text{dir}}$) and directional participation rate ($R_{\text{part}}$) relative to the mandatory 33% threshold. Highlighted emerald when $\ge 33\%$, amber when below.
       - `○ Fallback: N`: Appears when specialists (such as unconfigured options) return static/fallback responses without fresh market evidence.
       - `⚠️ Missing: M`: Appears if any configured specialists failed to report.
       - `Σ W_eff: W.ww`: Displays point-in-time total effective quality-weighted specialist weight.
       - `● Cycle: [id] (HH:MM:SS IST)`: Confirms the exact cycle timestamp to rule out stale or mixed-cycle telemetry.
     - **8 Implemented Specialists & 4 Research Desks Grid**:
       - Header: Displays `👥 8 Specialist Agents · 4 Research Desks` and dynamic online counter (`X/8 Implemented Online` or `0/8 Online · Awaiting Run`).
       - `Implemented Specialist Agents (8)`: News Sentiment 📰 (`Specialist Agent`), Global Macro 🌐 (`Specialist Agent`), Data Quality 📊 (`Specialist Agent`), Options & Greeks ⚡ (`Specialist Agent`), Trend & Momentum 📈 (`Specialist Agent`), Quant ML Forecaster 🔬 (`Specialist Agent`), Bayesian Gate 🛡️ (`Specialist Agent`), Final Decision ⚖️ (`Specialist Agent`).
- **Agent card subtitles** (each says what the agent actually does):
  - News Sentiment: headline tone for the instrument.
  - Global Macro: FII/DII flows, yields and FX (fresh releases only).
  - Data Quality: feed coverage and provenance.
  - Options & Greeks: the option chain, when a verified feed exists.
  - Trend & Momentum: the move vs the previous close, scored on 6 years of history.
  - Quant ML Model: the registered 15-minute model, if any.
  - Risk & Uncertainty: the disagreement gate (0.45 cutoff).
  - Final Decision: weighted consensus plus safety vetoes.
- **Trend & Momentum reference close**: when the live quote has no OHLC, the previous session's close comes from the saved Groww daily history, and the finding names that date.
- **`⚡ Run Live Analysis`**: a full run with LLM agents can take over a minute. The web proxy allows up to 3 minutes (`proxyTimeout` in `apps/web/next.config.js`); before, runs longer than 30 s showed `Analysis failed (500)`.
       - `Research & Catalog Reference Desks (4)`: Intermarket & MCX 🛢️ (`Catalog Ref`), Mean Reversion 🔄 (`Catalog Ref`), HTF Resampling ⏱ (`Catalog Ref`), Expected Net Payoff 💰 (`Payoff Model`).
       - `Specialist Semantic Metadata & Weight Badges`:
         - `Uncalibrated ML Prob` (Purple badge): Displays for `quant_forecast_analyst`, explicitly designating walk-forward tree probabilities as uncalibrated. Never labeled as calibrated.
         - `Unmeasured Heuristic` (Cyan badge): a rule-based confidence that has not been scored against outcomes yet (`global_macro_analyst`, `news_event_analyst`; any agent without a measured record). Treat it as an opinion until the Agent Track Records scorecard shows it as PROVEN.
         - `Measured Hit Rate` (Green badge): the agent's confidence is the hit rate its call actually had at this time of day, replayed on years of NIFTY data (`technical_analyst`). The consensus weights it by its skill over a coin flip.
         - `Static Default` (Slate badge): Displays for specialists reporting static/fallback catalog defaults.
         - `W_eff: 0.0 (Fallback)` (Crimson badge): Displays when options chain data is unavailable, confirming zero effective weight in consensus aggregation.
         - `W_eff: X.XX` (Slate badge): Displays exact quality-weighted effective specialist weight.
         - Dynamic metric row: Displays `Probability` for statistical model outputs, and `Confidence / Score` for heuristic and static specialists.
       - `Data-Integrity Behavior`:
         - Pre-run state: Implemented agents display `NOT RUN` with `—` confidence. Catalog references display `UNIMPLEMENTED` or `UNAVAILABLE`. No fake default stances or fabricated percentages.
         - Post-run state: Expected Net Payoff displays `UNAVAILABLE` with `Options EV Unavailable` and `—` confidence, truthfully reporting that options pricing is disabled. Catalog references display `CATALOG ONLY`. Implemented agents display verified directional stances, confidences, semantic pills, and effective weights.
       - `Grid / Compact View Toggle`: Allows switching between a detailed grid view and a space-saving compact matrix.
     - **Bottom Expand CTA Button**: `🔬 Expand Detailed 8-Agent Analysis Desk & Full Audit Dossier (Stages 0–14) ▾` switches the view to the detailed institutional analysis desk.
  5. **Visual Order Ticket (`<TradeTicket />`)**:
     - Clean, focused order ticket showing current recommendation (`STAND ASIDE`), live Groww spot reference tag, side, structure, paper capital, and paper book readiness.
     - `Signal Status Badge`: Visually highlights paper filter qualification status.
     - `Blocker List (`<BlockerList />`)`: Renders active pipeline gate blockers as visual tag chips.
  6. **Market Tape & Verified Macro Indicators (`<Snapshot />`)**:
     - `<MarketBoard />`: Real-time quote cards across 10 domestic and global benchmarks (NIFTY, SENSEX, CRUDE MINI, INDIA VIX, S&P 500, NASDAQ, DOW JONES, US VIX, CRUDE OIL, USD/INR).
     - `Verified Market Macro Indicators Grid`: Clean visual cards displaying live prints for India VIX (NSE Volatility), USD/INR (RBI Reference), MCX Crude Oil, MCX Gold, Dow Jones, and GIFT Nifty.
     - `Collapsible Feed Provenance & Compliance Archive`: Expandable `<details>` drawer cleanly archiving raw tick inspection tables, provider readiness metadata, and synthetic fixtures for compliance auditing without cluttering the executive view.
  7. **Diagnostics Grid (`<LiveQuotes />` & `<Quarantine />`)**:
     - **Live Quotes Reader (`<LiveQuotes />`)**: Direct inspection of raw quotes retrieved from Groww with domestic indices, MCX commodities, global benchmarks, and sectoral/volatility prints, plus `Read Groww quotes` button.
     - **Quarantine Ledger (`<Quarantine />`)**: Table of any candle files quarantined due to invalid timestamp formatting, clock drift, or empty payloads.

- **Detailed Analysis Desk View Components (`viewMode === "detailed"`)**:
  - **Sub-View Navigation Tabs**:
    1. `🤖 Multi-Agent Decision Desk & Signals` (Default): Activates `<V6Desk />`.
    2. `🧠 Institutional Intelligence Hub & Greeks`: Activates `<V6IntelligenceHub />`.
    3. `↑ Switch to Compact View` button: Instantly collapses back to the compact cockpit.

#### Detailed Desk Sub-Tab 1: Multi-Agent Decision Desk (`V6Desk`)
- **Collapsible Market Ticker Strip**:
  - Defaults to collapsed (`Show Market Tickers (15) ▾`) to save screen space.
  - When expanded, shows 15+ live quotes (NIFTY, BANKNIFTY, SENSEX, CRUDE, GOLD, VIX, US Indices).
  - Includes `Refresh Groww live quotes` button.
- **Executive System Health & Engine Status Ribbon (4-Column Deck)**:
  - `Market Quotes Feed`: Connection state (🟢 Live Active / 🟡 Polling), active quotes count, polling interval, and public Groww LTP reader status. Clarifies that this reads domestic public/cached market index snapshots and commodities, distinct from private broker trading authentication.
  - `Specialist Agents`: Status (🟢 12 Online), deterministic quant consensus engine mode, news item count.
  - `AI Commentary`: In-loop state (🟢 In-Loop with LLM commentary / ⚪ Standby with Zero-Hallucination Deterministic Quant Core). Clarifies that specialist multi-agent analysis runs mathematical and technical quant rules deterministically without requiring an LLM.
  - `ML Forecasting`: Models ready count (🟢 Models Ready / 🟡 Fitted Active), model architecture, probability engines. **Interactive Deck Card**: Clicking this card activates the `📈 ML Forecasting & Trend Graph` tab, rendering the live candlestick forward trajectory chart and volatility confidence corridor.
- **Institutional Desk Verdict Hero Banner**:
  - High-impact horizontal banner spanning the full desk width with accent color coding (Amber for Caution/Stand Aside, Emerald for Bullish Buy, Crimson for Bearish Sell).
  - Consensus Signal Badge (e.g., `⚠️ NO TRADE / CAUTION`, `🟢 STRONG_BUY_CE`, `🔴 STRONG_BUY_PE`).
  - Allocation Tag: `Deadband Gated` or `Active Allocation`.
  - Meta-Chips: Recommended Horizon (e.g., `Intraday`), Forecast Models approved count, Statistical Probabilities status, and Quant Fusion enablement.
  - Macro & Market Regime Pills: Displays volatility regime (`🛡️ Normal Volatility`) and risk limits clearance (`✓ Risk Limits Clear`).
- **Command Toolbar & Analysis Launcher**:
  - Quick Presets: `🇮🇳 All Indices (3)`, `🛢️ MCX Commodities (8)`, `🌐 All Markets (15)`, and `Clear`.
  - Section counters (`⚡ MCX Commodities (n)`, `🌐 Global Benchmarks (n)`, `News Wire (n)`) show the number of rows actually loaded, including `0`; no placeholder counts are shown.
  - Granular Instrument Selector Chips: Select individual indices (NIFTY, SENSEX), MCX commodities (Crude Mini, Gold Mini, Silver Mini, NG Mini), and global benchmarks.
  - Execution Options:
    - `⚡ Combine ML Forecast with Agent Consensus (Quant Fusion)` toggle: Combines statistical model probabilities with the 12-agent consensus. When checked, automatically activates the forward forecast chart.
    - `📈 Forecast Graph: Visible` inline toggle button: Appears alongside Quant Fusion to quickly show or hide the `<PredictedTrendChart />` directly above the trade decisions.
    - `Include model commentary` toggle.
    - `🔄 Auto-run Analysis` toggle (`imm_auto_run_analysis`), and `Analysis auto-run interval` dropdown (`Every 30s`, `Every 1m (60s)`, `Every 2m (120s)`, `Every 5m (300s)`, `Every 15m (900s)`, persisted in `imm_analysis_interval_sec`).
  - Primary CTA: `Run analysis (X Selected)` button with live execution feedback.
- **6 Inner Desk Navigation Tabs**:
  1. `🎯 Trade Decisions & Options`: Real spot-based option picks (ATM/OTM/ITM), strike targets, stop losses, and agent consensus. When Quant Fusion is active, embeds `<PredictedTrendChart />` right above the decision matrix for instant trajectory and strike verification.
     - **Decision Matrix & Option Recommendations Section (`InstrumentDecisions`)**:
       - `Section Header & Focus Filter`: Prominently titled with `⚡ OPTION RECOMMENDATIONS` badge and an instrument focus bar (`All Instruments (X)` or single-instrument filter pills with live spot prices).
       - `Instrument Card Header`: Displays the instrument name, exchange badge (e.g., `NSE`, `BSE`, `MCX`), live session status indicator (`🟢 Live Trading Session Active` or `🌙 Closed`), real-time Spot LTP in prominent typography with decimal precision, and data provenance badge (`🟢 LIVE FEED (UNVERIFIED PROVENANCE)` / `MISSING DATA`).
       - `Executive Verdict Banner`: High-contrast, theme-matched signal card displaying the directional verdict (`🟢 SIGNAL: BUY_CE`, `🔴 SIGNAL: BUY_PE`, `🟡 STAND ASIDE (MARKET CLOSED)` or `🟡 STAND ASIDE (SAFETY GATED / NO TRADE)`), multi-agent verification status, and fail-closed risk gate clearance badge (`🛡️ Risk Gate: PASS` or `🛡️ Risk Gate: VETOED (X Active)`). When consensus vetoes are active or the consensus decision is `NO_TRADE`, the banner locks to `STAND ASIDE` to prevent conflicting rogue signals.
       - `Collapsible Regime Triggers & Invalidation Drawer (`<details className="intelligence-drawer">`)`: Replaces bulky text walls with an elegant expandable accordion (`📋 Regime Triggers & Invalidation Framework (Regime: <REGIME>)`). When expanded, displays the Regime Summary, Bullish Breakout Trigger (`▲`), Bearish Breakdown Trigger (`▼`), and Thesis Invalidation Criteria (`⚠️`).
     - **Actionable Option Trade Card (`ManualTradeCard`)**:
       - `Market Closed Settlement Banner`: Displayed when session is closed, explaining that spot is the official closing settlement and option premiums are next-session Black-Scholes planning estimates.
       - `Commodity Futures Notice Banner`: For commodities like `CRUDEOILMINI`, displays a distinct `⚡ FUTURES: <CONTRACT>` banner specifying that outright futures is the recommended instrument, and clearly notes that the options table below is provided for catalog reference only.
       - `Trade Hero Strip`: Features the large directional Call Pill (`BUY CE` in green, `BUY PE` in red, `BUY_FUT` in cyan, `STAND ASIDE` in amber), underlying spot chip, snapshot reference spot chip (`Ref Spot: ₹<spot>`), Target Spot chip with positive points gain and dynamic live delta (`+X pts from ref | +Y live`), Stop-Loss Spot chip with points risk and dynamic live delta (`-X pts from ref | -Y live`), and Conviction badge (`HIGH`, `STANDARD`, `DEADBAND / NO EDGE`, `UNAVAILABLE`, or `NO TRADE / GATED`). When gated under consensus vetoes, Target and Stop display `— (Gated)` to eliminate speculative targets.
       - `Agent Consensus Breakdown Ribbon`: Visual vote tally (`X Bullish · Y Bearish · Z Neutral`) followed by a compact horizontal ribbon of mini-chips for each participating specialist agent with color-coded stance badges and hover explanation tooltips.
       - `Quant-Agent Fusion Confluence Bar`: Sleek horizontal bar displaying alignment status (`🟢 HIGH CONFLUENCE`, `⚠️ DIVERGENCE (VETO RISK)`, `🔵 STANDARD CONFLUENCE`, `🟡 MODEL DEADBAND (48%-52%)`, or `⚪ NO VERIFIED FORECAST`), ML walk-forward calibrated probability (`<P>% P(Up)`), signed Agent consensus score (`+X` / `-Y`), and one-line qualitative takeaway. If the forecast is in the deadband (48%–52%) or missing, fusion strictly locks the stance to `STAND ASIDE`.
       - `Authoritative Consensus Synchronization`: If the consensus engine emits `NO_TRADE` or active vetoes exist, all market cards override legacy heuristics and enforce `STAND ASIDE (NO TRADE)` with `is_actionable = false`.`
       - `Option Picks Switcher`: Toggle between `Recommended (<TYPE> · 5 Strikes)` and `Hedge / Alternate (<ALT_TYPE> · 5 Strikes)`.
       - `Top 5 Ranked Strikes Table`: Clean tabular view with columns `# Strike & Contract` (with ATM/OTM role tags), `Moneyness` badge, `Delta (Δ)`, `Est. Entry Premium`, `Est. Target Premium`, `Est. Stop Premium`, `Risk:Reward Ratio`, `1 Lot Capital & Max Loss/Gain`, and Action CTAs:
         - `Copy` button: Copies contract entry, target, and stop loss specifications to clipboard with instant `"Copied!"` feedback.
         - `+ Watch` button: Enrolls the strike directly into the live Watchlist & Accuracy Tracker (`POST /api/watchlist`) with dynamic state feedback (`Saving…`, `Watching ✓`, or `Retry`).
       - `Execution Note`: Key intraday execution and slippage considerations.
  2. `📈 ML Forecasting & Trend Graph`: Dedicated full-width workspace view rendering `<PredictedTrendChart />` with live Groww candlesticks, lookback selector (20, 35, 50 bars), cyan `NOW (Live Spot)` boundary line, forward projected trend path, and dynamic $\pm 1\sigma$ volatility confidence cones.
  3. `🤖 12 Specialist Agents`: The 12 quantitative specialist agents structured across 4 sequential analytical stages.
  4. `📋 Master Dossier & Pipeline (Stages 0–14)`: Institutional audit dossier containing 4 sub-tabs:
     - `V6 Master Dossier (Stages 0–14)`: Granular stage-by-stage cards covering Data Quality, Executive View, Global Macro, Fresh News, Geopolitics, Energy & FX, NIFTY Spot, SENSEX Spot, VIX & Sectors, Options Chain & OI, Price Confirmation, Quantitative Forecasts, Scenario Calibration, Contrarian Scan, and Final Verdict.
     - `Pipeline Stages (19)`: Complete tabular audit of all 19 pipeline nodes, displaying stage number, stage name, status pill badge, and explicit audit justification detail.
     - `Contradictions & Red Team`: Explicit contrarian challenges comparing macro narratives against price actions and technical order flows.
     - `Raw Observations`: Inspection table of all raw ingested telemetry rows, timestamps, data classes, SHA-256 hashes, and verification provenance.
  5. `📰 Headlines & News Wire`: Real-time news sentiment items with an embedded `⚙ Configure Feeds & Web Pages` collapsible drawer for `<NewsSourcesManager />`.
  6. `🛡️ Risk & Contradictions`: Expected Net Payoff, statutory friction breakdown (STT, exchange turnover, GST, SEBI charges, stamp duty, slippage buffer), hard risk limits, and fail-closed safety gates.

- **12 Specialist Agent Cards**:
  - Stage 1: News Sentiment Agent, Macro Regime Agent, Foreign Flow (FII/DII) Agent.
  - Stage 2: Order Flow & Microstructure Agent, Volatility & Skew Agent, Intermarket Commodity Agent.
  - Stage 3: Trend & Momentum Agent, Mean Reversion Agent, Multi-Timeframe Resampling Agent.
  - Stage 4: Bayesian Uncertainty Gate, Expected Net Payoff Agent, Hard Risk Limit Engine.
- **Interactive Scenario Simulator**:
  - Allows operator to adjust spot sliders and implied volatility shocks to simulate portfolio payoffs under simulated market gaps.

#### Tab 2: Institutional Intelligence Hub (`V6IntelligenceHub`)
- Cross-market correlation heatmaps between Indian Equities, MCX Commodities, US Benchmarks, and USD/INR.
- Institutional Sentiment Gauge synthesizing domestic news feeds.
- Greeks Sensitivity Surface (Delta, Gamma, Theta, Vega across varying expiries).

#### Embedded News Agent Web Feeds (`NewsSourcesManager` inside `V6Desk` -> `📰 Headlines & News Wire`)
- **Purpose**: Gives operators granular control over which external web portals and RSS feeds the News Sentiment Agent reads for market intelligence.
- **Top Metrics & Global Controls**:
  - `Feed Count Badge`: Displays current active feeds versus total configured (e.g., `11/11 Active`).
  - `+ Add Feed Link` button: Toggles the inline custom link addition form.
  - `↺ Reset Defaults` button: Reverts the feed configuration back to the 11 baseline financial feeds (Economic Times Markets, ET Stocks, ET Commodities, Mint, Business Standard, The Hindu, The Hindu BusinessLine, CNBC-TV18, NDTV Profit, Business Today, Moneycontrol) and reenables all. Requires explicit confirmation dialog.
  - `↻ Fetch Live Articles Now` button: Triggers immediate multi-source RSS scraping and article ingestion across all active feeds, refreshing sentiment scores in real-time.
- **Add Feed Link Form**:
  - `Feed / Publication Name` input (e.g., `Reuters India Equities`): Human-readable source label.
  - `Web / RSS Feed URL` input: Full URL (must begin with `http://` or `https://`). Server validates domain and enforces SSRF blocking against private/internal loopback addresses.
  - `Save Feed` button: Submits feed to API, saves to `data/news_sources.json`, and records audit event.
  - `Cancel` button: Closes the form without saving.
- **Feed Source Cards**:
  - `Source Name & Badge`: Displays feed name and type tag (`Default Feed` or `Custom Feed`).
  - `Feed URL Link`: Shows feed endpoint with an external link icon opening in a new tab.
  - `Article Health & Count`: Shows number of articles parsed during the most recent scrape cycle (e.g., `12 articles`).
  - `Enable / Disable Toggle` button (`✓ Enabled` in vibrant emerald / `○ Disabled` in muted gray): Allows temporarily suspending ingestion from a specific publication without deleting its link configuration.
  - `Remove Feed` button (`🗑 Remove`): Deletes custom feeds (with confirmation dialog). Default feeds can be disabled but not permanently removed to protect baseline system integrity.
- **Notification & Error Banners**:
  - Displays instant visual feedback toasts when feeds are enabled/disabled, added, deleted, reset, or when scraping fails.

---

- **Compact Cockpit, first card**: the Next-Session NIFTY Forecast Card in compact view (see §4.5).

### 4.3 Live & Auto Trading Desk (`/live`)
- **Purpose**: Autonomous algorithmic execution desk, automated trade suggestions, live paper/broker order management, and active risk monitoring.
- **Components & Controls**:

#### 1. Cross-Market Session Ribbon
- Real-time exchange status for NSE/BSE (09:15 AM – 03:30 PM IST) and MCX (09:00 AM – 11:30 PM IST).
- Shows live freshness tag (`LIVE` or `CLOSED_SESSION_VALID`) and countdown to next session open.

#### 2. Live Control Station
- **`Auto-Trading Master Switch` (Toggle Button)**:
  - Turns autonomous trading engine ON (`● AUTO-TRADING ON`, green) or OFF (`○ AUTO-TRADING OFF`, subtle gray).
  - **State Persistence**: The enabled/disabled state is persisted to browser `localStorage` under `imm_auto_trading_enabled` and hydrated automatically on page load/refresh. When enabled, refreshing the page keeps Auto-Trading active without turning off.
  - When ON, eligible high-conviction breakout signals from multi-agent analysis are automatically evaluated and enrolled in the Watchlist/execution pipeline upon quote polling.
- **`Auto-Add to Watchlist` (Toggle Checkbox)**:
  - When checked, new algorithmic trade suggestions are automatically enrolled in the outcome accuracy tracker.
  - State persisted in `localStorage` under `imm_auto_add_watchlist`.
- **`Execution Mode` Switcher**:
  - `PAPER` (Default): All orders are routed to the simulated ledger with realistic slippage and statutory STT/GST friction.
  - `LIVE`: Routes orders to actual broker API.
  - **State Persistence**: Current mode is stored under `imm_execution_mode` in `localStorage`.
  - **Fail-Closed Confirmation Modal**: Switching to `LIVE` triggers a modal requiring explicit confirmation. Live orders remain permanently locked if Kill Switch is engaged.
- **`🛑 KILL SWITCH` / `🔄 Reset Kill Switch` Button**:
  - Emergency circuit breaker wired to the **server** kill switch (`POST /api/kill-switch`, audited). Pressing it locks this page immediately (auto-trading off, simulated orders squared off), then trips the server switch so new entries are blocked for every session, the worker and the risk gates. If the server call fails, the notice says the lock is local only.
  - `🔄 Reset Kill Switch` clears the server switch. It is disabled while the out-of-band halt is active, and the page stays locked if the server still reports entries halted.
  - Exits are never blocked by the kill switch, so open positions can still be closed.
  - Status line `Server switch: clear | TRIPPED | UNKNOWN (entries blocked)` and `Out-of-band halt: clear | ACTIVE (<reasons>)`, refreshed from `GET /api/kill-switch` every 15 seconds. Any server-side halt also locks the page.
  - Out-of-band halt: a halt file (`IMM_HALT_FILE`, default `var/run/HALT`) or a GPIO-style input (`IMM_HALT_GPIO_PATH`, halts when its value equals `IMM_HALT_GPIO_ACTIVE`, default `1`; an unreadable input also halts). It works with the database and UI down and can only be cleared at its source (`python -m app.cli halt clear` or the physical switch), never from this page.
  - Displays red warning text when tripped: *"Engine locked. New entries blocked; exits still allowed. Reset to resume."*
- **Risk Threshold Controls**:
  - `Max Lots per Trade`: Limits position size (default: 1 lot; persisted in `imm_max_lots`).
  - `Daily Loss Threshold (₹)`: Hard loss cap (default: ₹5,000; persisted in `imm_daily_loss_limit`); if cumulative daily loss reaches this limit, the Kill Switch trips automatically.
- **Accuracy Benchmark & Auto-Refresh Controls Banner**:
  - `🔄 Run Analysis Now` button: Immediately refreshes Groww live quotes and executes `POST /api/market-analysis` (`include_forecast: true`) to update all instrument decisions, Quant-Agent Fusion scores, and option strike recommendations.
  - `Auto-run Analysis` checkbox & interval dropdown (`Every 30s`, `Every 1m (60s)`, `Every 2m (120s)`, `Every 5m (300s)`, `Every 15m (900s)`): Automatically re-runs the full multi-agent and ML forecast analysis on the selected schedule so `/live` continuously updates with the latest decisions (persisted in `imm_auto_run_analysis` and `imm_analysis_interval_sec`).
  - `⚡ Evaluate Outcomes Now` button: Immediately evaluates all open Watchlist positions against live exchange spot prices.
  - `Auto-evaluate` checkbox & interval dropdown (`Every 15s`, `Every 30s`, `Every 45s`, `Every 1m (60s)`, `Every 2m (120s)`): Automatically re-evaluates open positions against live spot quotes at the selected interval (persisted in `imm_auto_evaluate` and `imm_eval_interval_sec`).
  - `Updated: <timestamp>` indicator: Displays the exact IST timestamp of the most recent analysis cycle.
- **`🔄 Fetch Groww Live Data & Refresh Signals` Button**:
  - Pulls live spot prices and recalculates signals across all instruments.

#### 3. Tradable Underlyings Bot Matrix
- 3 dedicated execution cards for **NIFTY 50**, **BSE SENSEX**, and **CRUDEOIL MINI**.
- Each card displays:
  - Real-time Spot LTP and change, alongside snapshot reference spot (`Ref: ₹<price>`).
  - Trading session hours, exchange tag (`NSE`, `BSE`, `MCX`), and session market state.
  - Commodity Instrument Tag: Dedicated `⚡ FUTURES` badge appears for MCX commodities (e.g. `CRUDEOILMINI`), recommending outright futures contracts (`CRUDEOILMINI FUTURES`) rather than call options.
  - Multi-Agent Bias & Signal: Stance badge (`STAND ASIDE (NO TRADE)`, `BUY_CE`, `BUY_PE`, `BUY_FUT`, or `SELL_FUT`). When the backend decision is `NO_TRADE` or active consensus vetoes exist, strictly enforces `STAND ASIDE (NO TRADE)` in red.
    - One decision path: when gated, the backend also sets the market's `decision` to `NO_TRADE`, its options verdict to `NO_TRADE`, and clears target/stop premiums and per-lot risk on every listed strike (strike and any live entry premium remain for reference). The pre-gate signal is kept in `ungated_signal` for transparency.
    - A market whose call disagrees with its own fused bias (`CALL_CONFLICTS_WITH_FUSED_BIAS`) or with the consensus direction (`CALL_CONFLICTS_WITH_CONSENSUS` / `NO_DIRECTIONAL_CONSENSUS`) is gated individually.
    - For `BUY PE` calls the spot target is below the reference spot and the stop above it.
  - Target & Stop-Loss Points: Anchored to reference spot with dynamic live spot delta (`Target: ₹23,079.90 (+129.7 pts ref | +144.6 live)` and `Stop: ₹22,885.40 (-64.8 pts ref | -49.9 live)`). When gated under consensus vetoes, displays `— (Gated)` to eliminate speculative execution targets.
  - **`+ Watch & Score` Button**: Enrolls the trade into the live accuracy tracker. Disabled with `not-allowed` cursor when gated by consensus vetoes. Automatically records `data_class: "UNVERIFIED_PROVIDER_DATA"` to preserve data provenance integrity.
  - **`⚡ Fire & Auto-Add / Active Order` Button**: Submits simulated broker orders. When consensus vetoes are active or the decision is `NO_TRADE`, transforms into a disabled `🔒 Gated (<Conviction>)` button, preventing rogue orders.
    - Requires a fresh live option-chain premium for the ATM pick, a backend-supplied lot size, and a live spot. If any is missing the order is refused with `Cannot simulate …` instead of using placeholder prices. Entry, target and stop come from the live pick; quantity comes from the pick's `lot_size`.
    - Running P&L is marked to market with the delta captured from the live quote at entry. If no live delta was available, the order's P&L is not estimated.
  - **Est. premium**: Shown only from a live option-chain quote (`is_live_quote`); never estimated from spot.
  - **`+ Watch & Score` and auto-add**: Refused when the live spot or the analysis target/stop point distances are missing. Premium fields are sent only when the pick came from a live chain quote; otherwise the suggestion is tracked against spot levels only.
  - **Autonomous Bot Safety Gate**: The background auto-trading routine (`triggerAutoTradingScan`) strictly aborts without placing orders or polluting the watchlist whenever `analysisData.decision === "NO_TRADE"` or `rec.is_actionable === false`.

#### 4. Live Watchlist & Active Order Book
- **Status Filter Tabs**: `ALL`, `OPEN`, `TARGET_HIT`, `SL_HIT`, `EXPIRED`.
- **View Source Switcher**: `Watchlist Suggestions` vs `Live/Paper Orders`.
- **Performance Summary Cards**:
  - `Win Rate (%)`: Percentage of closed trades where target was hit before stop-loss.
  - `Total Signals`: Total suggestions recorded.
  - `Target Hits`: Successful trades that reached target price.
  - `SL Hits`: Trades that breached stop loss.
  - `Realized P&L (₹)`: Total closed profit/loss.
  - `Running P&L (₹)`: Mark-to-market unrealized profit/loss calculated from live spot prices.
- **Orders Table**:
  - Columns: Underlying, Contract, Entry Spot, Target Spot, Stop Loss Spot, Current Spot, Model Premiums (Entry, Running LTP, Target, Stop Loss), P&L (%), Status Badge, and Actions (`Exit` / `Cancel`). Missing premiums are shown as `—`; target/stop premiums are never derived as fixed percentages of entry.
  - **Orders Persistence**: Active and squared-off simulated broker orders are persisted in `localStorage` under `imm_live_simulated_orders`, allowing order logs, entry prices, and running P&L to survive page reloads until explicitly cleared via `Clear Orders`.

---

### 4.4 Watchlist & Accuracy Desk (`/watchlist`)
- **Purpose**: Independent, objective tracking and scoring of algorithmic suggestions against actual market spot prices reported by Groww.
- **Evaluation Rules**:
  - `Target hit`: Spot touched or exceeded target level while position was open.
  - `SL hit`: Spot touched or breached stop-loss level.
  - `Expired`: Neither target nor stop was hit before session close (15:30 IST for equities; 23:30 IST for commodities).
  - Note: Option premiums are theoretical estimates and are not used for scoring; evaluations are 100% spot-driven to prevent pricing distortion.
- **Top Action Controls**:
  - `Refresh quotes & check outcomes` button: Pulls current spot prices and re-scores all open suggestions against fresh market prints.
  - `+ Add Contract / Suggestion` button: Toggles the interactive inline contract creation card (`<AddSuggestionCard />`).
  - `Clear Watchlist` button: Prompts operator for confirmation and purges all suggestions.
  - `Auto-check every 60s` checkbox: Keeps a 60-second polling timer running in the browser tab.
- **Interactive Add Suggestion Card (`<AddSuggestionCard />`)**:
  - `Instrument` dropdown: Select from `NIFTY 50`, `SENSEX`, or `CRUDEOIL MINI`. Automatically updates default strike and step sizes.
  - `Option Type` dropdown: Select `CE (Call - Up)` or `PE (Put - Down)`.
  - `Contract Symbol` text input: Editable contract descriptor (e.g., `NIFTY 23200 CE`).
  - `Entry Spot (₹)` numeric input (required): Pre-filled with the live underlying spot when available; left blank (operator must enter it) when no live spot exists. The contract strike is pre-filled only from a live spot.
  - `Target Points (pts)` numeric input: Default 50 pts (NIFTY), 150 pts (SENSEX), or 40 pts (CRUDEOILMINI).
  - `Stop Loss (pts)` numeric input: Default 25 pts (NIFTY), 75 pts (SENSEX), or 20 pts (CRUDEOILMINI).
  - `Entry Prem. (₹, optional)` numeric input: Operator-entered entry premium. Blank by default; when left blank no premium is stored. A fresh live option-chain quote, if available, replaces it on save.
  - `Save to Watchlist` button: Submits `POST /api/watchlist` and refreshes the table upon success.
- **Accuracy Metric Cards**:
  - `Hit rate`: Percentage of decided trades where target was reached prior to stop-loss (`Targets / (Targets + SL)`).
  - `Target hit`: Absolute count of target-resolved suggestions.
  - `SL hit`: Absolute count of stop-loss resolved suggestions.
  - `Open`: Number of active suggestions being monitored against incoming spot quotes.
  - `Expired`: Suggestions that expired at session close without touching target or stop.
  - `CE / up hit rate`: Win rate specific to Call options / bullish underlying moves.
  - `PE / down hit rate`: Win rate specific to Put options / bearish underlying moves.
- **Status Filter Buttons**:
  - Filter by lifecycle status: `All`, `Open`, `Target hit`, `SL hit`, `Expired`, `Cancelled`.
- **Interactive Suggestions Table**:
  - `Contract`: Clickable link navigating directly to `/dashboard?instrument=...` with sub-link to `/analysis`. Displays contract name, dedicated **Expiry Date** badge (e.g. `Exp: 19 Oct 2026` in cyan), official exchange trading symbol (e.g. `NIFTY26O1923050PE`), option direction tag, and data class.
  - `Status`: Color-coded pill (`Open`, `Target hit`, `SL hit`, `Expired`, `Cancelled`).
  - `Prem. Entry`: Entry option premium and lot size. Marked with a green `Groww Entry LTP` badge when populated directly from a fresh Groww live Option Chain quote (same underlying, unexpired, under 15 minutes old). Blank when no live or operator-entered premium exists.
  - `Running Prem.` / `Exit Prem`:
    - For `OPEN` suggestions: Displays live mark-to-market premium and running gain/loss percentage. Features a distinct badge: **`Groww Live LTP`** (green) when streaming live exchange quotes from Groww GET `/v1/option-chain`, or **`Model Est.`** (slate) when using spot-delta estimation with the live delta captured at entry. Without a captured live delta, no running premium is shown.
    - For `RESOLVED` suggestions (`SL hit` / `Target hit`): Displays the **Realized Exit Premium** (captured directly from the live Groww option chain at resolution time) labeled `Realized Exit`. Without a realized exit premium, shows the percentage to the stored premium target/stop, or `Spot stop hit` / `Spot target hit` when no premium levels were stored. Beneath the realized exit, a subtle label displays `Post-Exit: ₹... (+/-%)` showing ongoing live market option recovery without ambiguous signals.
  - `Prem. Target` & `Prem. SL`: Target and Stop-Loss option premium levels derived from a live entry LTP and live delta. Blank when either was unavailable (no fixed +40% / -25% defaults). These are reference levels only: **outcomes (`Target hit` / `SL hit`) are decided on spot alone, with the same rule for target and stop**. A live premium never cancels a spot stop or creates a target hit. Premiums quoted before the suggestion was saved are never attached to it.
  - `Spot Entry`, `Spot Target`, `Spot SL`: Underlying spot boundary levels.
  - `Last Spot`:
    - For `OPEN` suggestions: Real-time observed spot price dynamically refreshed from streaming market feeds, with total checks count and last check timestamp.
    - For `RESOLVED` suggestions: Clearly displays the **Trigger Spot** that resolved the trade (`SL Triggered` or `Target Triggered`), accompanied by the current live market spot underneath (`Live Now: ₹...`) to maintain mathematical alignment.
  - `Best / Worst`: Maximum favorable and maximum adverse spot excursions observed.
  - `Saved` & `Resolves`: Creation timestamp, expiry time, and resolution price (`<timestamp> @ ₹<resolved_spot>`).
  - `Cancel` button: Available on `OPEN` suggestions to manually abort tracking.

---

### 4.5 Multi-Horizon Forecast Desk (`/forecast`)
- **Purpose**: Quantitative multi-horizon forecasting, directional probabilities, and empirical out-of-sample calibration tracking.
- **Components & Controls**:
  - **Next-Session NIFTY Forecast Card (`<RealisticForecastCard />`)**:
    - **Purpose**: the app's realistic forecast for the next NIFTY session, from models tuned on daily Groww history since 2020 and checked on data they never saw (`GET /api/research/multiyear/forecast`). It describes expected movement; it is not a trade signal and never places or proposes orders.
    - **Heading**: `NIFTY Forecast for <date>` with the last completed close it is based on. The date is the next weekday; exchange holidays are not checked.
    - **Pills**:
      - `RANGE: RELIABLE`: the range model beat the naive forecast significantly on the holdout.
      - `DIRECTION: EDGE SUPPORTED` (green) or `NO RELIABLE EDGE` (amber). Supported needs a development deflated Sharpe of at least 0.95 across every tuned trial and a holdout PSR of at least 0.9.
    - **Tiles**:
      - `Expected high–low range`: the session's expected high-to-low range in % and points, with the 90% band (about 1 session in 10 falls outside it).
      - `Typical close-to-close move`: the median absolute move in % and points, and the size that 9 sessions in 10 stay within.
      - `Direction (next session)`: P(up). With no supported edge it is the historical up-day rate, not a model output. The sub-line gives the best trial's holdout accuracy and binomial p-value, and the number of trials tried.
      - `Track record of the range (holdout)` (full view only): the share of unseen sessions inside the 90% band, the improvement over "same as yesterday", and the Diebold–Mariano p-value.
    - **Full view only**: the next half-day direction, the raw model output labelled unreliable when there is no edge, the caveats, and when the forecast was generated.
    - **Compact view** (dashboard): the first three tiles and a `Details →` link to `/forecast`.
    - **No forecast yet**: a note says how to create one (Backtest → Multi-Year Research → Fetch history, then Run research; or `python -m app.cli forecast-daily`).
  - **Agent Track Records Card (`<AgentTrackRecordCard />`)** (`GET /api/research/agents`):
    - **Purpose**: shows how often each agent's calls were actually right, so its suggestions can be weighed by evidence. Agent calls are locked to their scored rule: the LLM may add an explanation but cannot change a call's direction or confidence.
    - **Header pill**: `TECHNICAL: TRADEABLE EDGE` (green) or `NO TRADEABLE EDGE` (amber). A tradeable edge needs the unseen period to beat 50% and the same-bias baseline (p < 0.05), and to make money after index-futures costs.
    - **Technical Analyst replay table**: the real agent code replayed (LLM off) on every completed session since 2020 at 10:15, 12:00 and 14:00 IST, with the latest price and the previous close as inputs. One row per time and horizon.
      - Horizons: `Rest of day` (session close vs the price at the call) and `Next session` (the next close vs that price).
      - Columns: `Right (all years, 95% CI)` with the number of calls; `p vs 50%`; `Right (unseen period)` (the last 20% of sessions); `Net per call after costs` (green if positive); `Stated vs actual confidence` (the confidence the old formula stated, against the hit rate it actually had).
    - **Forward scorecard table**: every agent's NIFTY call from live analyses (and the consensus).
      - Columns: `Status`, `Right: rest of day`, `Right: next session` (hit rate of n, p-value), `Calls (directional / pending)` and `Last call`.
      - Calls are scored with the saved Groww closes once the session (and the next one) has closed.
      - Status values:
        - `COLLECTING`: fewer than 30 scored calls.
        - `PROVEN`: better than 50% with p < 0.05.
        - `NO EDGE YET`: not distinguishable from chance.
        - `WORSE THAN CHANCE`: significantly below 50%.
    - **How it feeds the consensus**: a measured agent's confidence is its historical hit rate at that time of day, and the consensus weights it by its skill over a coin flip (2 × hit rate − 1; an agent right 50% of the time carries no weight).
    - Refreshed by the research job on `/backtest` (it also re-runs the replay and scores pending calls), or by `python -m app.cli agent-backtest`.
  - **Live Candlestick & Forward Projected Trend Chart (`<PredictedTrendChart />`)**:
    - **Purpose**: Combines verified historical candlesticks, live market spot price action, and ML forward projected trajectory with dynamic confidence cones ($\pm 1\sigma$ volatility corridors), target spot, and stop-loss levels.
    - **Header Controls & State**:
      - `Instrument Selector Pills`: One-click buttons for `NIFTY 50`, `BANK NIFTY`, `BSE SENSEX`, and `CRUDEOIL MINI`. Automatically synchronizes with global `MarketDataContext`.
      - `Model Architecture Selector Dropdown`: Select which quantitative model drives the forward projected trend line, target, stop loss, and confidence corridor:
        - `🏆 Model: Champion (Ranked #1 Auto)`: Uses the deployed live forecast (`/api/forecasting/instrument-forecast`). Projection is drawn only when that forecast is `ACTIVE`.
        - Any other model choice: research benchmarks have no deployed live artifact, so the chart returns `forecast_status: MODEL_NOT_DEPLOYED` and draws no projection. Their walk-forward results are available from Model Studio.
        - `⚡ LightGBM (GBDT SOTA)`: Gradient-boosted decision trees with leaf-wise expansion.
        - `🚀 XGBoost (Boosting SOTA)`: Regularized gradient boosting with histogram tree method.
        - `🐱 CatBoost (Symmetric Trees)`: Oblivious decision trees with categorical handling.
        - `📐 DLinear (Decomposition SOTA)`: Direct linear trend and seasonal decomposition neural network.
        - `⏳ Chronos-2 (Foundation Transformer)`: Zero-shot time-series transformer foundation model.
        - `🌲 Random Forest (Ensemble SOTA)`: Bootstrap bagging ensemble of decision trees.
        - `🧠 MLP (Deep Neural Net)`: Multi-layer perceptron neural network.
        - `📊 Logistic Regression (Baseline)`: L2-regularized linear benchmark.
        - `🎲 Empirical Prior (Majority Baseline)`: Constant historical empirical probability.
      - `Strategy Gating Mode Dropdown`: Switch gating strategy between `Regime-Gated (Consensus)`, `Deadband (48%–52%)`, and `Raw Directional`.
      - `Lookback Window Dropdown`: Choose historical bar depth (`20 Bars (5h)`, `35 Bars (~1.5d)`, `50 Bars (2d)`).
      - `Live Market Status Pill`: Green pulsing indicator displaying `🟢 LIVE FEED TICKING` when streaming live Groww quotes, or `VERIFIED HISTORICAL BARS` with verified candle data.
    - **Key Metrics Ribbon & Status Strip**:
      - `Active Model Tag`: High-visibility purple tag showing active model architecture (e.g. `LIGHTGBM`, `XGBOOST`, `CHAMPION`).
      - `Live Spot Price`: Bold current underlying market price.
      - `Predicted Direction & Decision Badge`: Pill indicating `🟢 BULLISH (BUY)`, `🔴 BEARISH (SELL)`, or `🟡 NEUTRAL (STAND ASIDE / NO TRADE)`.
      - `Target Spot & Potential Gain`: Target price in INR.
      - `Stop Loss & Invalidation Risk`: Protective stop price in INR.
    - **Interactive Candlestick & Projection Chart Area**:
      - `Historical OHLC Candlesticks`: Green (`#10b981`) bullish and Red (`#f43f5e`) bearish candles with vertical wicks and rectangular bodies representing historical interval bars.
      - `NOW (Live Spot) Vertical Divider`: Prominent cyan dashed line (`#38bdf8`) separating realized historical data from the future predictive horizon, adorned with a glowing live spot price tag.
      - `Projected Forecast Path`: Dashed colored trajectory line projecting future prices across upcoming intervals ($T+1$, $T+2$, $T+3$, $T+4$).
      - `Probabilistic Confidence Corridor (Cone)`: Semi-transparent shaded cone expanding into the future representing $\pm 1\sigma$ volatility bounds derived from historical ATR and calibrated variance.
      - `Target & Stop Loss Horizontal Markers`: Dashed target line (`#10b981`) with `TARGET` badge and dashed stop line (`#f43f5e`) with `STOP LOSS` badge.
      - `Interactive Crosshair & Hover Tooltip`: Moving across historical candles reveals exact Bar Open, High, Low, Close, and Volume; hovering future projection points displays Projected Spot, Upper Confidence Bound, Lower Confidence Bound, and Delta from current spot.
      - `Chart Legend`: Color keys for Bullish Bar, Bearish Bar, Live Spot, Forward Projection, and Confidence Corridor.
  - `<InstrumentSelector />`: Select primary underlying to inspect.
  - `<InstrumentForecastCard />`: Displays the live forecast for the selected instrument.
    - `Model Probability P(Up)`: Raw model output, labelled `Uncalibrated model output`, followed by the forecast status when it is not `ACTIVE`. Shows `N/A` when there is no forecast; no default probability or direction is substituted.
    - `Raw Confidence`: `|P(Up) − 0.5| × 2`, or `N/A` when there is no forecast.
    - `Spot / Move / Target / Stop`: `N/A` when the live quote, VIX-based sizing, or a directional decision is unavailable.
    - Forecasts are issued only from features of the latest completed bars (≤ 30 minutes old). Older or historical-dataset features return `STALE_FEATURES`.
  - **Forecast Accuracy & Out-of-Sample Calibration Hub (`<ForecastAccuracyHub />`)**:

    - `Evaluate Pending Outcomes` action button: Triggers `POST /api/analysis/forecast-accuracy/evaluate` to score pending forecasts whose horizon has elapsed against incoming quotes without look-ahead bias.
    - **Calibration Status Banner**:
      - Status badge: Displays `CALIBRATED_RESEARCH` (green) if sample size $\ge 30$ and Brier Skill Score $> 0$, or `UNCALIBRATED` (amber) if preliminary sample or negative skill score.
      - Reason message: Clear textual explanation of statistical significance and empirical edge.
      - Sample summary: Shows total scored outcomes and pending outcomes awaiting subsequent bar close.
    - **Metric Cards Grid**:
      - `Directional Win Rate`: Percentage of predictions where realized direction matched hypothesis.
      - `Mean Brier Score`: Average squared error $\frac{1}{N}\sum (\hat{p}_i - y_i)^2$.
      - `Prior Baseline Brier Score`: Canonical empirical benchmark ($0.2503$).
      - `Brier Skill Score (BSS)`: Relative improvement over prior baseline $1 - (\text{Brier} / \text{Brier}_{\text{prior}})$.
      - `Log Loss (Cross-Entropy)`: Logarithmic probabilistic loss.
    - **Accuracy by Instrument Grid**:
      - Dedicated cards for `NIFTY`, `SENSEX`, and `CRUDEOILMINI` showing total forecasts, directional accuracy %, and Brier score.
    - **Forecast-versus-Actual History Table**:
      - `Analysis / Time`: Timestamp in IST and short analysis run UUID.
      - `Instrument`: Tradable asset symbol.
      - `Predicted`: Hypothesized direction (`BULLISH` / `BEARISH`).
      - `Prob (Up)`: Model-estimated probability of upward move.
      - `Prior Spot`: Underlying spot price at forecast creation time.
      - `Subsequent Spot`: Realized underlying close price post-horizon.
      - `Realized Ret`: Realized percentage move of underlying.
      - `Outcome`: Color-coded indicator: `✓ Correct (BULLISH/BEARISH)`, `✗ Incorrect`, or `⏳ Horizon pending`.
      - `Brier`: Individual squared prediction error.
      - `Status`: `SCORED` or `PENDING` pill.
  - **Historical Data Ingestion Workstation (`<DataPullWorkstation />`)**:
    - **Purpose**: Enables operators to query, fetch, and ingest historical OHLCV candle datasets on demand for any supported Indian market index or commodity future across multiple API brokers and granularities.
    - **Component / Instrument Selector**:
      - Dropdown options: `NIFTY` (NSE NIFTY 50), `BANKNIFTY` (NSE NIFTY BANK), `SENSEX` (BSE SENSEX 30), and `CRUDEOILMINI` (MCX Crude Oil Mini).
    - **Data Provider Dropdown**:
      - Supported brokers/data feeds: `groww` (Groww Direct API), `upstox` (Upstox Pro API), `kite` (Zerodha Kite Connect), and `angelone` (Angel One SmartAPI).
    - **Granular Candle Interval Dropdown**:
      - Granularities: `1m` (1 Minute - Scalping), `5m` (5 Minutes - Intraday), `15m` (15 Minutes - Standard M15 Model Benchmark), `1h` (1 Hour - Swing), and `1d` (1 Day - Positional).
    - **Date Range Presets & Selectors**:
      - Quick preset buttons: `1 Month` (30 Days), `3 Months` (90 Days), `6 Months` (180 Days), `1 Year (365d Max)` (365 Days) — interactive round pill buttons with active blue glow indicator (`#38bdf8`) reflecting current selection, automatically setting both start and end dates with single-click ease.
      - `Start Date` and `End Date` date picker inputs for arbitrary ISO date range configurations.
      - **Live Query Span & Auto-Clamp Strip**: Displays real-time day count difference (`Query Span: X days`). If the selected duration exceeds the 366-day statutory broker limit, a warning badge is highlighted alongside a one-click `⚡ Auto-clamp to 365 Days` button. Client-side pre-submission validation automatically caps ranges to 365 days to prevent `RANGE_TOO_LONG` API rejections.
    - **`Pull & Ingest Historical Data` Action Button**:
      - Sends asynchronous request to `POST /api/history/imports` to fetch candles, parse timestamps, validate boundary alignment, and store candle ledgers.
      - Renders loading spinner (`Ingesting Historical Candles...`) while processing.
    - **Live Ingestion Result Panel**:
      - Status pill: `COMPLETED` (green) or `QUARANTINED_&_VERIFIED` (green) or `FAILED` (red).
      - Metadata breakdown: Import Job ID, total candles ingested, provider, interval, and date span.
      - **Groww Official Clarification Verified Notice**: Displays contextual confirmation referencing the official Groww Customer Success ticket (recorded 15 Oct 2026 confirming IST timezone and `bar_start` timestamp semantics). Displays total quarantined chunks and confirms immediate availability of the compiled dataset for walk-forward model training.
      - Interactive prompt: Offers immediate guidance to select the asset in the Model Training Station below to benchmark LightGBM or Logistic Regression.

  - **SOTA Model Walk-Forward & End-to-End Benchmark Workstation (`<ModelTrainingWorkstation />`)**:
    - **Purpose**: Provides dual-mode model training, validation, and benchmarking: a focused single-model walk-forward inspector and a comprehensive end-to-end multi-dataset, multi-model walk-forward matrix benchmark that ranks all configurations on an interactive leaderboard.
    - **Station Mode Switcher Buttons**:
      - `🎯 Individual Model`: Switches to focused single-asset, single-model evaluation with deep metric inspection and strategy mode matrix.
      - `🚀 End-to-End Suite & Leaderboard`: Switches to multi-dataset, multi-model cross-validation suite evaluating all combinations concurrently.
    - **Individual Model Controls**:
      - `Target Asset Dropdown`:
        - `NIFTY`: NSE NIFTY 50 (6,227 M15 candles across 19 walk-forward folds).
        - `BANKNIFTY`: NSE BANK NIFTY (6,227 M15 candles across 19 walk-forward folds).
        - `SENSEX`: BSE SENSEX (6,831 M15 candles across 19 walk-forward folds).
        - `CRUDEOILMINI`: MCX CRUDEOIL MINI (6,227 M15 candles across 19 walk-forward folds).
      - `Model Architecture Dropdown`:
        - `lightgbm`: LightGBM GBDT (Leaf-Wise SOTA - M37).
        - `xgboost`: XGBoost Classifier (Regularized Boosting SOTA).
        - `catboost`: CatBoost Classifier (Symmetric Oblivious Decision Trees SOTA).
        - `dlinear`: DLinear / NLinear (Time-Series Decomposition Neural Net SOTA - AAAI).
        - `chronos`: Amazon Chronos-2 (Zero-Shot Time-Series Transformer Foundation Model).
        - `random_forest`: Random Forest Ensemble (Bootstrap Bagging SOTA).
        - `mlp`: Deep Neural Net / MLP (Multi-Layer Perceptron).
        - `logistic_regression`: Logistic Regression (L2 Newton Baseline - M3/M23).
        - `empirical_prior`: Empirical Prior (Majority Baseline - M3).
      - `Strategy / Gating Mode Dropdown`:
        - `regime_gated`: Dynamic regime-conditioned execution (consensus with ATR/ADX trend regime; neutral in range).
        - `deadband`: Strict probability deadband cutoff ($P > 0.52$ for Long, $P < 0.48$ for Short; cash otherwise).
        - `raw`: Continuous unconstrained directional execution ($P > 0.50$).
      - `Validation Scheme Badge`: Confirms 19 Expanding Folds (14 Development / 5 Holdout).
      - `⚡ Train & Benchmark [MODEL]` Button: Triggers `POST /api/forecasting/train-benchmark` with real-time progress.
      - `Individual Benchmark Scorecard`: Holdout Accuracy %, Brier Skill Score, Holdout Net Return (2.0 bps friction), and Full Max Drawdown % (drawdown of the chained out-of-sample curve). Missing values show `N/A`.
      - `Significance Tiles` (from `honest_evaluation`): `Edge Evidence` (`EDGE SUPPORTED` only when development deflated Sharpe ≥ 0.95 and holdout PSR ≥ 0.5, otherwise `NO EDGE`), `Dev Deflated Sharpe` (with annualized Sharpe), `Holdout at Realistic Cost` (NSE futures statutory charges + 1 bp slippage per side, with trade count), and `Holdout Hit Rate (95% CI)` (Wilson interval on non-flat bars).
      - `Excluded (library not installed)` note: models whose library is missing are excluded and listed, never reported under the empirical prior. Requesting such a model returns `MODEL_UNAVAILABLE` instead of another model's results.
      - `Strategy Comparison Matrix Table`: Displays all strategy gating variations for the evaluated model with `SELECTED` badge on the active mode, plus `Dev DSR` and `Edge` columns.
    - **End-to-End Suite & Leaderboard Controls**:
      - `1. Select Datasets Checkbox Grid`:
        - Independent selection checkboxes for `NIFTY 50` (NSE), `BANK NIFTY` (NSE), `BSE SENSEX` (BSE), and `CRUDEOIL MINI` (MCX).
        - Includes `Select All` and `Clear All` quick-action buttons.
      - `2. Select SOTA Models Checkbox Grid`:
        - Checkboxes for all 9 model families (`LIGHTGBM`, `XGBOOST`, `CATBOOST`, `DLINEAR`, `CHRONOS`, `RANDOM_FOREST`, `MLP`, `LOGISTIC_REGRESSION`, `EMPIRICAL_PRIOR`).
        - Tag badges: `GBDT SOTA`, `BOOSTING SOTA`, `TREES SOTA`, `DECOMPOSITION SOTA`, `FOUNDATION SOTA`, `BAGGING SOTA`, `NEURAL SOTA`, `BASELINE`, `CLIMATOLOGY`.
        - Includes `Select All` and `Clear All` quick-action buttons.
      - `3. Select Strategy Gating Modes Checkbox Grid`:
        - Checkboxes for `Regime-Gated Consensus (ATR/ADX Filter)`, `Deadband Neutral Filter (48%–52%)`, and `Raw Directional (Unconstrained)`.
      - `🚀 Run End-to-End Walk-Forward Benchmark & Rank` Button:
        - Submits `POST /api/forecasting/multi-benchmark` with selected datasets, models, and modes.
        - Animated execution indicator (`⏳ Executing Multi-Asset Walk-Forward Matrix...`).
        - **High-Performance Multi-Threading & Response Caching**: Multi-instrument benchmark runs concurrently across thread pools with optimized estimators (XGBoost `hist` tree method, top-level PyTorch DLinear decomposition, and thread-pinned CatBoost/Random Forest), dropping runtime from >70s to ~8–12 seconds. Subsequent runs with identical configurations return instantaneously (<5ms) from the in-memory cache.
        - **Gateway Timeout & Non-JSON Fallback Protection**: Both individual and suite benchmark API calls implement defensive JSON response parsing. If a reverse proxy 504 gateway timeout occurs, the UI intercepts the HTML response and surfaces an informative guidance message rather than an unhandled `JSON.parse` syntax error.
      - `Edge Verdict Banner` (green when any combination has supported edge, amber otherwise): states how many combinations show development DSR ≥ 0.95 with a non-negative holdout, or that none do and the top rank is the least-bad rather than a recommendation. Shows the ranking basis.
      - `Champion Trophy Summary Cards`:
        - `🏆 #1 on Development Evidence`: The combination with the highest development deflated Sharpe (every evaluated combination counted as a trial), its `EDGE SUPPORTED` / `NO EDGE` pill, and its holdout return labelled "confirmation only".
        - `🎯 Top Holdout Accuracy`: Highest directional accuracy model and Brier Skill Score.
        - `🛡 Lowest Max Drawdown`: Model with minimal peak-to-trough equity drawdown.
        - `📊 Evaluated Combinations`: Total combinations tested across the 19 expanding folds.
      - `🥇 Top Model by Instrument (development evidence) Cards`:
        - Dedicated cards highlighting the best model and mode per instrument by development deflated Sharpe, with holdout return and accuracy for reference. BANK NIFTY is skipped (its dataset is synthetic and quarantined).
      - `Filter Instrument Dropdown`:
        - Instant client-side filtering (`All Instruments`, `NIFTY`, `BANKNIFTY`, `SENSEX`, `CRUDEOILMINI`).
      - `🏆 Ranked SOTA Walk-Forward Leaderboard Table`:
        - Ranked by development deflated Sharpe, then development Sharpe. The holdout is never used to rank or choose a winner; it is shown once for confirmation.
        - Medals for top positions: `🥇 #1`, `🥈 #2`, `🥉 #3`, followed by numeric rank `#4`, `#5`, etc.
        - Columns: `Rank`, `Instrument`, `Model Architecture`, `Strategy Mode`, `Holdout Net Return (2bps)`, `Full Net Return (2bps)`, `Holdout Accuracy`, `Brier Skill Score`, `Max Drawdown` (chained curve), `Dev DSR`, `Status` (`EDGE SUPPORTED` in green or `NO EDGE` in amber), and `Action`.
        - `⚡ Set for Analysis` Action Button: Promotes any model and strategy mode combination from the leaderboard to serve as the live predictive model across the Overview, Analysis Desk, and Live Trend Graph. When active, displays a `✓ Active in Analysis` pill.
      - `Active Analysis Model Banner & Indicator`: Prominent banner at the top of the workstation displaying the currently active model architecture (e.g. `LIGHTGBM`, `XGBOOST`, `DLINEAR`) and strategy mode (`Regime-Gated`, `Deadband`, `Raw`), accompanied by a direct jump link to the Live Trend Graph (`📈 View in Live Graph ↑`).
      - `⚡ Set as Active Model for Analysis Button` (Individual Mode): Located directly below the strategy comparison table in the Individual Model tab, allowing operators to immediately promote any individually evaluated model to active analysis status.
    - **Approved Forecasts Section**: Lists all active models approved for production forecasting.
    - **Registered Models Table**: Lineage, training dataset ID, checksum, and safety flags.
    - **Experiments Section**: Holdout and walk-forward experiment tables.

---

### 4.6 Options Strategy & Greeks Desk (`/options`)
- **Purpose**: Deep option chain pricing, Greeks modeling (Black-Scholes-Merton), and multi-leg spread strategy formulation.
- **Interactive Workstation Controls**:
  - `Underlying`: Dropdown or buttons to select `NIFTY`, `SENSEX`, or `CRUDEOILMINI`.
  - `Side`: Toggle between `CE` (Calls) and `PE` (Puts).
  - `Structure`: Choose between `Single leg` (Outright Option), `Bull call spread`, or `Bear put spread`.
- **Live Options Greeks Card (`<V6OptionsGreeksCard />`)**:
  - Asset buttons: `NIFTY`, `SENSEX` (BANKNIFTY removed; it is out of scope).
  - `Forward / Spot`: live quote only; shows `Awaiting live quote` when none exists (no default spot). Lot size and strike step come from the instrument master.
  - `Institutional PCR` and `Max Pain Pin Strike`: show `N/A`; this panel does not load live option-chain open interest, so no PCR or max-pain value is displayed.
  - `Calculator IV (operator input)`: the IV slider value used for the Black-76 calculator; it is an input, not a market reading.
  - Black-76 Greeks table: Delta ($\Delta$), Gamma ($\Gamma$), Theta ($\Theta$), Vega ($\mathcal{V}$) for 7 strikes around ATM, computed from the live spot and the operator's days-to-expiry / IV / rate inputs. Empty (with a notice) until a live spot and strike step exist.
- **Live Option Strike Matrix**:
  - Automatically identifies real-time At-The-Money (ATM) strike based on verified live Groww spot quotes.
  - Fail-closed empty state: If live spot quotes are not yet retrieved, renders an awaiting feed notification without inventing fictitious prices.
  - Lot size and strike step from the instrument master (`/api/forecasting/instruments`); if the catalog is not loaded the matrix shows a notice instead of strikes.
  - Shows 5 key strike levels: ATM, ITM 1, ITM 2, OTM 1, OTM 2.
  - Displays strike, option type, moneyness tag, theoretical premium estimate, and lot size.
  - `Select Strike` button: Prefills the research order ticket.
- **Decision Record & Expected Value**:
  - Computes Expected Net ($EV$) after subtracting bid-ask spread and statutory friction.
  - Displays risk veto status from the risk engine.

---

### 4.7 Positions, Risk & Capital Allocation (`/risk`)
- **Purpose**: Hard financial risk control, portfolio capital allocation, and enforcement of safety gates.
- **Portfolio Metric Grid**:
  - `Capital`: Allocated risk capital in INR (e.g., `₹50,000.00`).
  - `Utilisation`: Percentage of capital currently committed to margin/premiums.
  - `Open positions`: Number of active contracts held.
  - `Session P&L`: Cumulative session profit or loss.
- **Capital Configuration Form (`<CapitalConfig />`)**:
  - `Allocated Risk Capital (INR)` input: Set allocated trading capital.
  - `Save capital allocation` button: Persists capital to configuration; immediately clears the `MISSING_RISK_CAPITAL` blocker across all desks.
  - `Clear capital allocation` button: Resets capital to `null` (engaging safety stand-aside).
- **Limits & Safety Flags**:
  - Displays state of Kill Switch, Paper Trading, Live Trading, Forecast Approval, Paper Approval, Live Approval, and Market Data Verification.
  - **Missing Prerequisites Blocker List**: Displays list of active pipeline blockers preventing live trading.

---

### 4.8 System Architecture & Paper Readiness Audit (`/system`)
- **Purpose**: Operational health verification, data provenance audit, and statutory 8-Gate Paper Readiness certification.
- **System Health Strip**:
  - Reports API server status (`HEALTHY`), SQLite database connectivity (`CONNECTED`), Operating Mode, Live Orders lock status (`LOCKED`), and Kill Switch state (`NORMAL (ARMED)`).
- **Instrument Data Health Card (`<InstrumentDataHealthCard />`)**:
  - Verifies data provenance for the selected instrument.
  - `Last price` shows `N/A` when no live quote exists; `Stored candles` is the actual persisted count (NIFTY is `DATA_GAP` when none are stored).
  - Checks candle boundary alignment, holiday calendars, clock drift, and quarantine logs.
- **V6 8-Gate Paper Readiness Certification Card (`<V6ReadinessAuditCard />`)**:
  - Displays the 8 mandatory gates required for algorithmic trading:
    1. Gate 1: Real Market Data Provenance (Groww/Exchange verified).
    2. Gate 2: Invariant Checksums & Boundary Validation.
    3. Gate 3: 19-Fold Walk-Forward Cross-Validation.
    4. Gate 4: Statutory Friction & Slippage Accounting.
    5. Gate 5: 12-Agent Deterministic Consensus.
    6. Gate 6: Risk Budget & Hard Loss Limit Enforcement.
    7. Gate 7: Fail-Closed Kill Switch & Emergency Stop.
    8. Gate 8: Execution Isolation (Simulation vs Live Broker).
- **Diagnostics Section**: Quick navigation links to secondary diagnostic tools.

---

## 5. Tools & Diagnostics Pages

Accessible via the collapsible `Tools Show (7) ▾` toggle in the left navigation rail.

### 5.1 Historical Market Data & Quarantine (`/history`)
- **Purpose**: Management of historical OHLCV candle datasets, multi-provider reconciliation, and inspection of quarantined data files.
- **Historical Import Form**:
  - `Provider`: Select `groww` or `upstox`.
  - `Instrument`: `NIFTY`, `SENSEX`, or `CRUDEOILMINI`.
  - `Interval`: `M1` (1-min), `M5` (5-min), `M15` (15-min), `H1` (1-hour), `D1` (Daily).
  - `Start Date` & `End Date`: Date pickers.
  - `Submit Import` button: Ingests candle data and validates boundaries.
- **Cross-Provider Reconciliation Form**:
  - Compares historical prints between Provider A and Provider B within a specified tolerance (pts) to identify data errors.
- **Interactive Candle Chart (`<InstrumentHistoricalChart />`)**:
  - Canvas chart for reviewing ingested OHLCV bars.
- **Quarantined Records Table**:
  - Displays candle files rejected due to timestamp ambiguity or data gaps.

---

### 5.2 Model Studio & Benchmarking (`/studio`)
- **Purpose**: Quantitative machine learning laboratory for model training, feature weight inspection, and cross-model benchmarking.
- **Top Hub Switcher Bar**:
  - `🔬 Forecast Model Studio & Comparisons` (Active view).
  - `🏛️ Model Registry & Execution Slots →` link (`/registry`).
  - `📈 Live Forecasts & Accuracy →` link (`/forecast`).
- **Registered Models & Experiment Registry**:
  - Browse trained models (Logistic L2, LightGBM, Persistence, Random Forest).
  - `Register Experiment` button: Promotes an experiment to registered model status.
- **Model Details Inspector**:
  - View model hyperparameters, training dataset checksums, and feature importance scores.
- **Side-by-Side Model Comparison Tool**:
  - Select any two models using checkboxes.
  - Click `Compare Selected Models` to view side-by-side AUC-ROC, Brier Score, Sharpe ratio, and calibration curves.
- **Research Selection**:
  - Designates an active research model for offline forecasting.

---

### 5.3 Walk-Forward Backtesting (`/backtest`)
- **Purpose**: Rigorous 19-fold walk-forward cross-validation, higher-timeframe swing resampling, and factor attribution.
- **Top Hub Switcher Bar**:
  - `📊 Walk-Forward & Multi-Asset Backtest` (Active view).
  - `📒 Paper Ledger & Intent Audit Replay →` link (`/paper`).
- **Evaluation Runner**:
  - `Instrument`: `NIFTY 50`, `SENSEX`, or `CRUDE OIL MINI`.
  - `Provider`: Choose between `Synthetic Quiet-Day Fixture` (compliance testing) or `Historical Ingested Dataset` (real market validation).
  - `Run walk-forward evaluation` button: Executes out-of-sample backtest.
- **Walk-Forward Performance Metrics Card (`<InstrumentBacktestCard />`)**:
  - Reads only the computed M40 artifact (`var/datasets/m40_multi_asset_benchmark.json`). If it is missing or unreadable, status is `UNEVALUATED` and no figures are shown.
  - Header pills: `STATUS: RESEARCH_WALK_FORWARD` (or `UNEVALUATED`) and `FRICTION: <bps> BPS ON INDEX (NOT OPTIONS)`.
  - **Caveats banner** (shown first): development-fold return when negative, live-model mismatch, constant-prior strategy, small holdout, holdout selection bias, and index-only costs.
  - Metric tiles: `Holdout Net Return` (with Full Period and Dev Folds), `Max Drawdown` (sub-label `Chained out-of-sample curve`, or `Legacy: mean of per-fold maxima` for artifacts produced before the chained evaluation), `Holdout Skill & Calibration` (Brier Skill Score and accuracy), and `Turnover` (holdout and full period, holdout fold count). Signs come from the data; missing values show `N/A`.
  - `Is the edge real? (Significance after realistic costs)` panel: `Edge Evidence` (Supported / Not supported; requires dev DSR ≥ 0.95 and holdout PSR ≥ 0.5), `Dev Deflated Sharpe` (with Sharpe and number of trials counted), `Holdout at <bps> bps/side` (return, trades, PSR), and `Holdout Hit Rate (95% CI)` with binomial p-value. For a legacy artifact the panel says significance is unavailable and to regenerate the M40 benchmark.
  - `How these figures are aggregated` note: chained, compounded curve with every position change and the final exit charged (or the legacy summed/averaged description for old artifacts).
  - `All Evaluated Strategies` table: Model, Mode, Dev / Holdout / Full net return, Max DD, and Dev DSR for every strategy in the artifact. No "optimal candidate" label is assigned.
  - Execution assumptions list and provenance footer (`Dataset`, `Artifact`, `Computed` timestamp).
- **Factor Attribution Card (`<V6MultiAssetCard />`)**:
  - Header pill `BANK NIFTY DATA: SYNTHETIC` (rose) and a disclosure banner using the API's `data_quarantine.note`: BANK NIFTY candles are generated from NIFTY returns plus noise, so BANK NIFTY, cross-asset and dual-index results are not evidence of real performance. The synthetic dataset is never used for live forecasts.
  - Decomposes strategy returns into Market Beta, Momentum, Volatility Regime, and Mean Reversion factors.
- **Multi-Year Daily & Half-Day Research Card (`<MultiYearResearchCard />`)**:
  - **Purpose**: tests on several years of Groww history (from 2020) whether next-day direction, next-half-day direction or next-day volatility can be forecast, and scores every result with walk-forward evaluation, trading costs and significance tests. Research only: nothing on this card places orders, touches the paper ledger or changes the live model.
  - **Header pills**:
    - `FETCH: RUNNING | SUCCEEDED | FAILED` or `RESEARCH: ...`: the state of the last background job (one job runs at a time).
    - `DIRECTION EDGE: SUPPORTED` (green) or `NOT SUPPORTED` (red): shown once a report exists. Supported needs a development deflated Sharpe of at least 0.95 and a holdout PSR of at least 0.9.
  - The description lists the inputs Groww cannot supply and that are therefore not used (MCX crude, USD/INR, FII/DII flows).
  - **1. Fetch history from Groww**:
    - `Symbols` checkboxes: `NIFTY`, `BANKNIFTY`, `INDIAVIX`, `SENSEX` (all ticked by default).
    - `Intervals` checkboxes: `Daily (1day)` (ticked by default) and `15-minute (for half-day)`, which the half-day horizon needs.
    - `From` / `To` date pickers: `From` defaults to 2020-01-01 and cannot be earlier; an empty `To` means today.
    - `Also build NIFTY put/call OI ratio` checkbox: also builds the daily NIFTY PE/CE open-interest ratio from near-the-money option contracts. Slow (thousands of requests), resumable, and it needs NIFTY daily history (saved or in this fetch).
    - `Fetch history` button (`POST /api/research/multiyear/fetch`): starts the download in the background using the saved Groww token. It is disabled while a job runs or when no symbol or interval is ticked. The request is audited.
    - **Series table**: one row per symbol and interval, showing `Candles` (or `not fetched`), `From`, `To`, `Failed windows` (red when above zero: those date ranges were not received and are left empty, never filled), and `Rejected rows` (candles dropped for impossible prices). The `NIFTY PCR` row shows the days built and expiries skipped.
  - **2. Run the research**:
    - `First training window (days)` (default 500, range 100–5000) and `Test window (days)` (default 20, range 5–250): the walk-forward settings. The half-day horizon uses 1000 and 40 half-day bars.
    - `Include put/call ratio features` checkbox: adds the PCR feature set; disabled until a PCR has been built.
    - `Run research` button (`POST /api/research/multiyear/run`): runs in the background and writes `var/datasets/research_daily_report.json`, then tunes the models and publishes the next-session forecast (`var/datasets/realistic_forecast.json`) shown on `/forecast` and the dashboard. It is disabled while a job runs or when nothing has been fetched (a note then says to fetch NIFTY daily history first). The request is audited.
  - **Last job**: the job's kind, start time (UTC), status, its error (if it failed) and its log. The card polls `GET /api/research/multiyear` every 3 seconds while a job runs.
  - **3. Results** (from `GET /api/research/multiyear/report`):
    - **Note line**: when the report was generated, the bars used per input and the cost per side.
    - **Tiles**:
      - `Direction: best on development`: model and feature set, with horizon and number of trials.
      - `Its holdout return / accuracy`: that model's return on the final 20% of the data, its accuracy and the binomial p-value against 50%.
      - `Volatility: selected model`: chosen on development QLIKE, with its holdout QLIKE (lower is better).
      - `Beats naive volatility (holdout)`: `YES` only when the Diebold–Mariano test against "today's volatility" is significant (p < 0.05) in the model's favour; the DM p-value is shown below.
    - **`Direction trials` table**: one row per horizon, feature set and model, with `Dev deflated Sharpe`, `Holdout return` (green or red by sign), `Holdout Sharpe` (annualized), `Holdout accuracy (n, p)` and `Trades`. A row with too little data shows `INSUFFICIENT_ROWS` and its row count.
      - Feature sets: `price` (returns, gap, realized volatility), `price_vix` (adds VIX level, VIX change and the VIX-minus-realized-variance spread), `price_vix_cross` (adds BANKNIFTY and SENSEX returns relative to NIFTY), `price_vix_cross_pcr` (adds PCR level and change).
      - Models: `empirical_prior` (always predicts the training up-rate; the baseline), `logistic` (L2 logistic regression), `lightgbm` (shallow trees).
    - **`Volatility models (next-day)` table**:
      - Models: `naive_rv1`, `har`, `vix_implied`, `har_vix`. ★ marks the one selected on development.
      - Columns: holdout `QLIKE`, `MSE (log var)`, `Mincer–Zarnowitz R²` (how much of the realized variation the forecast explains), and Diebold–Mariano `stat, p` against the naive and VIX forecasts. A negative stat means the row's model had lower loss.
    - Missing values show `N/A` or `—`; undefined metrics are served as null, never as zero.

---

### 5.4 Model Registry & Governance (`/registry`)
- **Purpose**: Enforces formal regulatory separation between research models, paper trading, and live deployment.
- **Top Hub Switcher Bar**:
  - `← 🔬 Forecast Model Studio & Comparisons` link (`/studio`).
  - `🏛️ Model Registry & Execution Slots` (Active view).
- **Model Slots**:
  - `Paper Trading Slot`: Displays active model authorized for simulated trading (or `None (NOT_AVAILABLE)`).
  - `Live Trading Slot`: Displays active model for live orders (`Permanently Locked` in current build).
- **Governance Gates**:
  - Real-time audit flags: `Forecast Ready`, `Paper Approved`, `Live Approved`, `Market Data Verified`.
- **Raw Technical JSON**: Inspect full registry state payload.

---

### 5.5 Paper Trading Simulation Desk (`/paper`)
- **Purpose**: Zero-risk simulated execution environment modeling discrete Indian statutory charges, half-spread tick slippage, Half-Kelly position sizing, and sub-millisecond audit trails without live broker interaction. Strictly segregates the active live-data paper trading account from historical walk-forward replay benchmarks.
- **Top Hub Switcher Bar**:
  - `← 📊 Walk-Forward & Multi-Asset Backtest` link (`/backtest`).
  - `📒 Paper Ledger & Intent Audit Replay` (Active view).
  - `⚡ Open Active Live & Auto Trading Desk →` link (`/live`).
- **Operational Safeguards Ribbon**:
  - `Operational Mode: PAPER`: Explains active virtual trading environment where real capital remains locked behind hardware/software kill switches. Fills are virtual only.
  - `LIVE BROKER LOCKED`: Prominent red badge confirming that real broker routing is disabled.
- **Section 1: Current Live Paper Trading Account (Actual)**:
  - `Source: Live Database Ledger` badge: Connects to `GET /api/paper/account` querying actual execution ledger tables (`PaperAccountEvent`, `RiskSession`).
  - `Realized Net P&L`: Shows current session's actual realized profit/loss in INR (default `₹0.00`). Color-coded green (positive), red (negative), or neutral.
  - `Open Positions`: Count of currently open virtual lots/positions (default `0`).
  - `Executed Trades`: Total number of live virtual orders filled in the current session (default `0`), with live Win Rate %.
  - `Total Statutory Fees`: Real accumulated Indian statutory friction (STT, NSE, SEBI, GST) from live paper executions (default `₹0.00`).
  - **Honest Zero State Card (`📭 No Live Paper Trades Executed Yet`)**:
    - Displayed when `Executed Trades === 0`.
    - Explicitly informs the operator that no virtual orders have been placed or filled during the session, and that realized P&L, win rate, and profit factor remain at zero rather than fabricating or inheriting historical backtest figures.
  - **Live Executed Trades Table**:
    - Displayed when live fills exist. Columns: `ID`, `Symbol`, `Side` (`BUY`/`SELL`), `Price`, `Charges`, and `Net P&L`.
- **Section 2: Historical Simulation Benchmark (M42 Historical Replay)**:
  - `HISTORICAL BENCHMARK` amber badge: Distinctly identifies this section as archival research performance across historical swing bars, **not** the current paper account's P&L.
  - `Inspect Benchmark Trades (<count>) / Collapse Benchmark` button: Collapsible drawer toggling the detailed historical replay records; the count is the number of trades in the loaded simulation.
  - **Synthetic data warning** (rose banner): Shown when the API returns `data_quarantine`. States that the BANK NIFTY leg of the M42 replay uses synthetic candles, so the benchmark is not evidence of real performance.
  - `Net Replay P&L` is coloured and signed by its actual value (green/`+` when positive, red when negative).
  - **Benchmark Portfolio Cards**:
    - `Ending Virtual Capital`: Final simulated capital (₹10,44,626.76) vs initial seed capital (₹10,00,000.00).
    - `Net Realized P&L`: Total net strategy profit (+₹44,626.76) and Net ROI percentage (+4.46%).
    - `Gross P&L vs Friction`: Compares gross price gain (₹60,311.00) against total friction (₹34,706.09).
    - `Win Rate & Profit Factor`: Strategy win rate (56.72%), profit factor (1.46), and maximum peak-to-trough drawdown (1.35%).
  - **Indian Statutory Charges & Slippage Breakdown Box**:
    - `STT`: Securities Transaction Tax (0.10% on SELL options premium turnover; 0.02% on SELL futures turnover).
    - `NSE Txn`: NSE Exchange Turnover charges (0.03503% on options turnover).
    - `SEBI Turnover`: SEBI regulatory turnover charges (0.0001% / ₹10 per crore).
    - `Brokerage`: Institutional discount brokerage ($\min(₹20.00, 0.05\% \times \text{turnover})$).
    - `GST (18%)`: 18% tax on sum of (Brokerage + Exchange Fees + SEBI charges).
    - `Stamp Duty`: 0.003% on BUY options premium turnover.
    - `Tick Slippage`: Discrete 0.05 INR exchange tick alignment and half-spread impact penalty.
    - `Total Charges`: Combined statutory regulatory fees deducted from strategy P&L.
  - **Dynamic Volatility-Parity Asset Allocation Cards**:
    - Dedicated performance cards for `NIFTY` (lot size 25, regime consensus gated) and `BANKNIFTY` (lot size 15, structural deadband filtered) showing trade count, winning/losing breakdown, win rate %, net P&L, profit factor, and inverse-volatility allocation weights.
  - **Simulated Trade History Table**:
    - Asset Filter Buttons: `ALL`, `NIFTY`, `BANKNIFTY`.
    - Outcome Filter Buttons: `ALL`, `WIN`, `LOSS`.
    - Columns:
      - `ID`: Unique simulated execution trade ID.
      - `Contract`: Underlying symbol / contract descriptor.
      - `Side`: Color-coded `BUY` (green) or `SELL` (red).
      - `Lots/Qty`: Integer lot sizing and total contract quantity.
      - `Entry Price`: Execution price at entry including half-spread haircut.
      - `Exit Price`: Execution price at exit.
      - `Statutory Fees`: Sum of all Indian statutory charges for entry and exit.
      - `Slippage`: Half-spread and tick penalty in INR.
      - `Net P&L`: Profit or loss after all charges and slippage (color-coded).
      - `ROI`: Return on trade capital percentage.
- **Intent Audit & Decision Replay Tool**:
  - `Intent ID` text input: Query any specific trade intent identifier.
  - `Read stored decision` button: Replays the exact decision path of the trading engine, verifying fill state, simulated fill status, expected net, snapshot conflict, paper trading active status, missing fields, and reason codes.

---

### 5.6 Account & Operator Profile (`/settings`)
- **Top Hub Switcher Bar**:
  - `🔑 API Keys, Brokers & AI Agents` link (`/settings/integrations`).
  - `👤 Operator Profile & Account` (Active view).
- **Purpose**: Operator profile settings, session management, and credential updates.
- **Operator Card**:
  - Username, database storage status, account creation date, and last login timestamp.
- **Profile Configuration Form**:
  - `Display name` input: Change operator display name.
  - `Timezone` input: Default `Asia/Kolkata`.
  - `Save profile` button: Persists profile changes.
- **Password Change Form**:
  - `Current password` input.
  - `New password` input (minimum 8 characters).
  - `Change password` button: Re-hashes password with fresh salt.
- **Sign Out**: Ends operator session and clears cookies.
- **News Agent Sources & Web Feeds (`<NewsSourcesManager />`)**:
  - Embedded feed configuration panel allowing operators to review, toggle, add, remove, and refresh News Sentiment Agent feeds globally from the Settings dashboard without navigating to the Analysis Desk.

---

### 5.7 API Keys & Broker Integrations (`/integrations` & `/settings/integrations`)
- **Purpose**: Comprehensive credential management, lifecycle state tracking, real provider connection verification, separate capability reporting (authentication vs market data vs model lookup), live dynamic model discovery, LangGraph AI multi-agent configuration, and read-only chronological diagnostics.
- **URL Routing**: Both `/integrations` and `/settings/integrations` map to the same unified API Integrations interface.
- **Top Summary Strip**:
  - `Live Trading Badge`: Displays fail-closed status (`LOCKED` / `FAIL_CLOSED`).
  - `Provider Enablement Status Badges`: Real-time pill indicators (`Enabled` in green, `Disabled` in amber) for Groww, Kite, Upstox, Angel One, OpenAI, and Gemini.
- **Lifecycle States & Badges**:
  Each provider displays its canonical integration lifecycle status:
  - `Connected` (Green pill, `ok`): Provider credentials are valid, enabled, and the live connection test succeeded.
  - `Configured (Not Tested)` (Amber pill, `wait`): Credentials have been saved in encrypted storage but a live test has not yet run. Saving credentials does NOT automatically mark a provider connected.
  - `Connection Failed` (Red pill, `bad`): A connection test was attempted but the provider returned an authentication, rate limit, quota, or network error.
  - `Token Expired (Reauth Required)` (Red pill, `bad`): The provider's stored session token has passed its expiration deadline and requires re-authentication.
  - `Disconnected` (Gray pill, `idle`): The operator has explicitly disconnected the provider. Background synchronization and live calls are stopped while saved credentials remain safely encrypted for future reconnection.
  - `Not Configured` (Gray pill, `idle`): No credentials or API keys have been saved for this provider.
- **Capability Badges**:
  Capabilities are reported separately from raw HTTP connection:
  - `Auth: Verified / Failed / Not Tested`: Proves operator authentication and account profile access (e.g., Groww margin balance read).
  - `Market Data: Verified / Failed / Not Tested`: Proves real market-data access for trading instruments (e.g., Groww live quote lookup).
  - `Model: Verified / Failed / Not Tested`: Proves AI model availability and token validation (OpenAI / Gemini model lookups).
  - `Historical Candles: Verified / Unverified / Not Tested`: Proves historical candle ingestion and quarantine integrity.
- **Last Error Banner**:
  - Whenever a test connection fails, an inline callout (`⚠️ Last Error: <message>`) appears directly on the provider card highlighting the exact reason returned by the provider (e.g. invalid TOTP seed, rate limit, model not found, expired session) without exposing secret keys.
- **Provider Card Action Buttons**:
  - `Configure`: Opens the provider configuration modal to edit credentials, auth method, model, or label.
  - `Test Connection`: Executes a real provider-specific test request. Auto-enables the integration if currently disabled and reports separate authentication and market data capability results.
  - `Disconnect`: Available when the provider is active/enabled. Disconnects the provider immediately, invalidates derived access tokens, stops background synchronization, and marks the provider as `Disconnected` while preserving all saved credentials for later reconnection.
  - `Connect`: Available when a configured provider is disconnected. Re-enables the integration and prepares it for synchronization using already stored credentials.
  - `Remove`: Available when credentials exist. Triggers an explicit confirmation modal before permanently deleting stored secrets.
  - `Diagnostics`: Available on Groww. Scrolls down to the historical diagnostics runner.
- **Disconnect vs. Remove Configuration Distinction**:
  - **Disconnect**: Halts active usage and market data synchronization without deleting saved credentials. Used when temporarily pausing sync, avoiding API quota depletion, or during market closed hours.
  - **Remove Configuration**: Destructive operation that permanently deletes stored credentials, API keys, and derivation tokens from the encrypted vault. Requires explicit double confirmation in a dedicated confirmation dialog.
- **Supported Providers & Cards**:
  1. **Groww Direct API**: Real-time quotes, historical candles, and order placement.
     - `Configure`: Opens Groww modal.
     - `Test Connection`: Makes authenticated calls to `GET /v1/margins/detail/user` (authentication) and `GET /v1/live-data/quote` (market data access). Reports authentication success and market-data access separately. Handles RFC 6238 TOTP clock drift with automatic $\pm 30\text{s}$ time-step skew retry.
     - `Disconnect`: Halts active quotes, revokes derived JWT tokens, and preserves TOTP/API secrets.
     - `Connect`: Re-enables Groww without requiring re-entry of secrets.
     - `Remove`: Opens permanent deletion confirmation dialog.
     - `Diagnostics`: Scrolls directly to the historical candle diagnostic suite.
     - `Facts`: Displays Last test result/timestamp, and Token expiry in IST.
     - `TOTP Auto-Renewal`: For `API key and TOTP`, tokens auto-renew seamlessly every morning at 06:00 AM IST using the stored TOTP secret.
  2. **Zerodha Kite Connect**: Kite Connect v3 REST API for external data and secondary execution.
     - `Configure`: Opens Zerodha Kite configuration modal.
     - `Test Connection`: Tests `GET /user/profile`.
     - `Disconnect` / `Connect`: Toggles active usage while retaining Kite API Key and Access Token.
     - `Remove`: Confirmation dialog to delete stored Kite credentials.
     - `Facts`: Displays Last test result/timestamp, and Rate limit (3 req/s).
  3. **Upstox API**: Upstox v2 API for cross-provider market data and bhavcopy reconciliation.
     - `Configure`: Opens Upstox configuration modal.
     - `Test Connection`: Tests `GET /v2/user/profile`.
     - `Disconnect` / `Connect`: Toggles active usage while retaining Upstox Access Token.
     - `Remove`: Confirmation dialog to delete stored Upstox credentials.
     - `Facts`: Displays Last test result/timestamp, and Rate limit (5 req/s).
  4. **Angel One SmartAPI**: SmartAPI REST backup market data feed.
     - `Configure`: Opens Angel One configuration modal.
     - `Test Connection`: Tests `GET /rest/secure/angelbroking/user/v1/getProfile`.
     - `Disconnect` / `Connect`: Toggles active usage while retaining Angel One API Key, Client Code, and JWT.
     - `Remove`: Confirmation dialog to delete stored Angel One credentials.
     - `Facts`: Displays Last test result/timestamp, and Rate limit (3 req/s).
  5. **OpenAI API**: Advanced LLM reasoning, code analysis, and specialist multi-agent commentary.
     - `Configure`: Opens OpenAI configuration modal.
     - `Test Connection`: Tests `GET /v1/models/{model}` using API key. Accurately distinguishes authentication, quota/billing, and rate limit errors.
     - `Disconnect` / `Connect`: Halts OpenAI agent invocations while keeping the API key stored.
     - `Remove`: Confirmation dialog to delete stored OpenAI API key.
     - `Facts`: Displays Last test result/timestamp, and Selected Model ID.
  6. **Google Gemini API**: Quantitative reasoning, long context analysis, and multimodal processing.
     - `Configure`: Opens Google Gemini configuration modal.
     - `Test Connection`: Tests `GET /v1beta/models/{model}` using API key. Accurately distinguishes authentication failure, model unavailability, and quota exhaustion.
     - `Disconnect` / `Connect`: Halts Gemini agent invocations while keeping the API key stored.
     - `Remove`: Confirmation dialog to delete stored Gemini API key.
     - `Facts`: Displays Last test result/timestamp, and Selected Model ID.
  7. **INDmoney Reference Evaluation**:
     - Status: `BLOCKED_NOT_PERMITTED` (Rose Red pill).
     - Informational card documenting lack of official public API and ToS restrictions against reverse-engineering.
  8. **NSE Official Reference Evaluation**:
     - Status: `LIMITED_TO_DAILY_PUBLIC_REPORTS` (Amber Yellow pill).
     - Informational card documenting that official NSE portal data is strictly limited to end-of-day reports (Bhavcopy CSVs), with commercial licensing required for tick feeds.
- **Modal Dialog Functionalities**:
  - `Disconnect vs Remove Explanation Notice`: Clear visual callout in every modal explaining that Disconnect retains credentials for reconnection while Remove erases keys.
  - `Integration Enabled Toggle`: Switches the provider's active status. Live broker trading remains strictly disabled behind two-factor operator authorization and the software kill switch.
  - `Authentication Method Dropdown (Groww)`: Choose between `API key and secret`, `API key and TOTP`, or `Access token`.
  - `Input Fields & Masking`:
    - **Default Environment Seeding**: Credentials present in the repository root `.env` (`GROWW_TOTP_TOKEN`, `GROWW_TOTP_SECRET`, `GROWW_API_KEYS`, `OPENAI_API_KEY`, `GEMINI_API_KEYS`, etc.) are automatically loaded by default on backend startup and upon reading integration status into the encrypted database storage.
    - **Field Masking (`••••••••••••••••`)**: Whenever credentials are configured in the system, modal `<input type="password">` fields render them masked with bullet dots (`••••••••••••••••`) and display a subtle `(masked)` label.
    - **One-Click Replace Focus**: Focusing or clicking any masked password field automatically selects the masked placeholder (`e.target.select()`), allowing seamless typing to overwrite without manually deleting characters.
    - **Mask-Safe Preservation**: Saving or testing connection with unchanged masked bullets safely retains the existing decrypted secrets in backend storage rather than throwing missing credential errors or overwriting with literal bullet characters.
  - `Label Input`: Custom nickname for the credential profile (e.g. `Primary Account`). Persisted via dedicated profile endpoints.
  - `Model Selector & Dynamic Discovery (OpenAI & Gemini)`:
    - **Dynamic Discovery on Open**: Opening the modal queries the live provider API to fetch active account models.
    - `🔄 Query Live Models` button: Re-queries available models on-demand using either the saved credentials or a newly entered API key.
    - **Google Gemini Catalog**: Supports live Google AI models (`gemini-flash-latest`, `gemini-flash-lite-latest`, `gemini-3.8-flash`, `gemini-3.1-flash-lite`, `gemini-2.5-pro`, `gemini-2.5-flash`, `gemini-2.0-flash`, `gemini-2.0-flash-lite`, `gemini-1.5-pro`, etc.) plus custom/fine-tuned model names via `Custom / Fine-Tuned Model...`.
    - **OpenAI Catalog**: Supports chat and reasoning intelligence models (`gpt-4o`, `gpt-4o-mini`, `o1`, `o1-mini`, `o1-preview`, etc.).
  - `Save Changes` button: Validates credentials upfront. Persists encrypted secrets, enablement switches, and profile labels.
  - `Test Connection` button: Runs real connection test directly from the modal. If new credentials were typed, automatically saves and enables them before running the test.
  - `Disconnect` button: Disconnects the active integration without closing the modal or deleting keys.
  - `Remove Credentials` button: Enforces double confirmation (`Confirm permanent removal`) before wiping credentials and test history from the database vault.
- **Confirmation Dialog for Credential Removal**:
  - When clicking `Remove` on any card, a focused modal dialog opens explaining that the action is permanent, highlighting the alternative to use `Disconnect` instead, and offering `Cancel` or `Permanently Delete Credentials`.
- **Independently Configurable AI Agents (LangGraph)**:
  - Configures distinct LLM providers, live callability routing, and hyperparameters across 8 specialized multi-agent roles (`market_data_analyst`, `technical_analyst`, `global_macro_analyst`, `news_event_analyst`, `options_analyst`, `quant_forecast_analyst`, `risk_uncertainty_analyst`, `final_decision_agent`):
    1. `Market Data Analyst`: Ingests and verifies OHLCV ticks.
    2. `Technical Analyst`: Momentum, support/resistance, and volume oscillators.
    3. `Global Macro Analyst`: Currency pairs (USD/INR), treasury yields, and crude oil.
    4. `News & Event Analyst`: Regulatory filings and sentiment extraction.
    5. `Options Analyst`: Greeks ($\Delta, \Gamma, \Theta, \mathcal{V}$), IV skew, and PCR.
    6. `Quant Forecast Analyst`: Probabilistic ML model calibration and Brier metrics.
    7. `Risk & Uncertainty Analyst`: Stress testing and tail-risk gating.
    8. `Final Decision Agent`: Master consensus arbitrator enforcing fail-closed trade safety.
  - **Global Routing & Execution Controls Bar**:
    - `Enable Live LLM Agent Execution` checkbox (`agentsConfig.enable_live_llm`): Controls whether the 8 specialist agents execute live OpenAI/Gemini completions (`LLM` / `LLM_FALLBACK`) or stay in offline `DETERMINISTIC_RULE` mode. Syncs `IMM_ENABLE_AGENT_LLM` in the running backend server when saved.
    - `Auto-Reroute to Available Models on Quota/Billing Failure` checkbox (`agentsConfig.auto_reroute_available_models`): Globally enables automatic cascading across verified available models (`gemini-flash-lite-latest`, `gemini-3.1-flash-lite`, `gemini-flash-latest`, `gpt-4o-mini`, `gpt-4o`) whenever a configured primary or fallback model fails due to quota exhaustion (`429`), account billing exhaustion (`credit_balance_exhausted`), or model unavailability (`404`/`503`).
    - `Quick Bulk Model Assignment` buttons:
      - `All → Gemini Flash-Lite (Verified Callable)`: Sets all 8 agents to `gemini/gemini-flash-lite-latest` with fallback `gemini/gemini-3.1-flash-lite` and enables `auto_reroute`.
      - `All → OpenAI GPT-4o-mini + Gemini Failover`: Sets all 8 agents to `openai/gpt-4o-mini` with fallback `gemini/gemini-flash-lite-latest` and enables `auto_reroute`.
  - **Header Action Buttons**:
    - `Check Callable Models` button: Sends `POST /api/analysis/agents/check-models` (`{ auto_apply: false }`) to probe live completion callability across candidate OpenAI and Google Gemini models and renders the **Live Model Callability Matrix**.
    - `Auto-Assign Available Models` button: Sends `POST /api/analysis/agents/check-models` (`{ auto_apply: true }`), probes all candidate models, automatically assigns verified callable models as primary and fallback across any agent whose current model is uncallable, enables `auto_reroute_available_models`, and persists the configuration to `var/config/agent_system_config.json`.
    - `Reset to Defaults` button: Restores default LangGraph configuration (`POST /api/analysis/agents/reset`).
    - `Save Agent Settings` button: Persists the full `MultiAgentSystemConfig` (`enable_live_llm`, `auto_reroute_available_models`, and all 8 `SingleAgentConfig` entries) to `PUT /api/analysis/agents/config`.
  - **Live Model Callability Matrix Panel** (rendered after clicking `Check Callable Models` or `Auto-Assign Available Models`):
    - Displays each probed model (`GEMINI · gemini-flash-lite-latest`, `GEMINI · gemini-3.1-flash-lite`, `GEMINI · gemini-flash-latest`, `GEMINI · gemini-2.5-flash`, `OPENAI · gpt-4o-mini`, `OPENAI · gpt-4o`) with a green `CALLABLE (<latency> ms)` status or red `BLOCKED (<error_code>)` status.
    - `Use for All` button on each callable model card: One-click assigns that verified callable provider/model across all 8 specialist agents.
  - **Per-Agent Configuration Table Columns**:
    - `Active Provider`: Dropdown (`OpenAI` or `Google Gemini`) per role; switching provider automatically selects that provider's default callable model.
    - `Model ID` (`cfg.model`): Dual control featuring a provider-aware `<select>` dropdown populated from the active provider's model catalog (`geminiModels` or `openaiModels`) paired with a synchronized text `<input>` for custom/fine-tuned model IDs.
    - `Temperature` (`cfg.temperature`): Float input (`0.0` to `2.0`, step `0.05`) controlling deterministic vs. creative output.
    - `Max Tokens` (`cfg.max_tokens`): Output token limit (`100` to `8000`, step `100`).
    - `Fallback Provider` (`cfg.fallback_provider`): Dropdown (`None`, `OpenAI`, `Google Gemini`) specifying the failover provider.
    - `Fallback Model` (`cfg.fallback_model`): Dual control with a provider-aware `<select>` dropdown and custom text `<input>` for the failover model ID.
    - `Auto-Reroute` checkbox (`cfg.auto_reroute`): Per-agent toggle allowing the agent to automatically cascade to available models in the registry pool if both its primary and fallback models fail.
    - `Enabled` checkbox (`cfg.enabled`): Toggle specialist agent participation in the analysis graph.
  - **LangGraph Multi-Agent Dynamic Consensus Card (`<V6ConsensusCard />`)**:
    - `Run Consensus Cycle` button: Sends `POST /api/market-analysis` and immediately binds the returned report (`consensus` and `agent_outputs`) into local component state without requiring a page reload or falling back to hardcoded mock metrics.
    - Displays real-time `Directional Dispersion Index (D)` (`disagreement_index`), `Composite Epistemic Uncertainty (U)` (`epistemic_uncertainty`), `Consensus Directional Bias` (`directional_recommendation` and `consensus_score`), and `Active Risk Vetoes` (`vetoes` / `reason_codes`).
    - Each of the 8 specialist agent cards in the `Specialist Voting Matrix` displays `Base Weight`, `Dynamic Weight` (`effective_weight`), `Confidence`, measured `Latency` (`latency_ms`), truthful `Execution Mode` (`LLM`, `LLM_FALLBACK`, `MOCK_LLM`, `DETERMINISTIC_RULE`, `DETERMINISTIC_FALLBACK_ON_LLM_ERROR`, `SKIPPED`), and `Engine / Model` (`provider/model`).
- **Forecast Model Studio (Controlled Model Comparison)**:
  - Purpose: Chronological expanding-window walk-forward validation preventing look-ahead leakage.
  - `Run Multi-Model Comparison (NIFTY)` button: Executes chronological walk-forward benchmark across `Majority Class`, `Last Return Sign`, and `Logistic Regression` models.
  - `Summary Metrics`: Displays Instrument Target, Chronological Splits count, and `Lookahead Leakage Guard` status (`Verified Enforced` in green).
  - `Evaluation Table`: Mean Directional Accuracy %, Mean Balanced Accuracy %, Mean Brier Score, and Baseline comparison vs Majority Class and Last Return Sign.
- **Groww Historical Diagnostics**:
  - `Start Time` & `End Time`: Date-time range for live test query (maximum 30-minute span).
  - `Confirmation Checkbox`: Explicit confirmation to execute the read-only request once without automatic token refresh.
  - `Run Diagnostic` button: Submits `POST /api/integrations/groww/historical-diagnostic`.
  - `Quarantine Details & Previous Results Table`: Shows HTTP status, candle counts, timestamps, and quarantine validation results.

---

## 6. Global Status Badges, Indicators & Glossary

### Status Badges & Pill Colors
| Badge Text | Class | Color | Meaning |
|:---|:---|:---|:---|
| `LIVE SESSION` | `.pill.ok` | Vibrant Green | Market is open for regular trading |
| `CLOSED` | `.pill.idle` | Slate Gray | Exchange is closed; post-close prices active |
| `NO TRADE` / `STAND ASIDE` | `.pill.bad` | Rose Red | Risk or forecast gates block trade entry |
| `TARGET HIT` | `STATUS_STYLE` | Emerald Green | Live spot reached or exceeded target price |
| `SL HIT` | `STATUS_STYLE` | Crimson Red | Live spot breached stop-loss threshold |
| `OPEN` | `STATUS_STYLE` | Sky Blue | Trade is active and running |
| `EXPIRED` | `STATUS_STYLE` | Neutral Gray | Session closed before target or stop was touched |
| `LIVE FEED` | `.data-badge` | Sky Blue | Real market quote direct from Groww API |
| `UNVERIFIED` / `FIXTURE` | `.data-badge` | Amber Yellow | Offline synthetic fixture; not real market data |

### Pipeline Stage & Dossier Status Badges
| Badge Text | Class | Color | Meaning & Evaluation Criteria |
|:---|:---|:---|:---|
| `COMPLETED` | `.stage-pill.completed` | Soft Green | Pipeline node executed and validated successfully |
| `PRESENT` | `.stage-pill.present` | Soft Green | Telemetry or series verified and present in ingested payload |
| `VERIFIED` | `.stage-pill.verified` | Soft Green | Provider price print confirmed against an independent secondary reference |
| `UNVERIFIED` | `.stage-pill.unverified` | Amber Yellow | Real provider data observed, but unverified by secondary cross-check |
| `PARTIAL` | `.stage-pill.partial` | Amber Yellow | Partial telemetry available (e.g., India VIX present, but sector breadth absent) |
| `UNCALIBRATED` | `.stage-pill.uncalibrated` | Amber Yellow | Probabilities derived heuristically with uncertainty buffer; empirical calibration pending |
| `SYNTHETIC` | `.stage-pill.synthetic` | Amber Yellow | Offline fixture or synthetic mock print; strictly barred from live routing |
| `STALE` | `.stage-pill.stale` | Amber Yellow | Observation timestamp exceeds session freshness threshold |
| `MISSING_DATA` | `.stage-pill.missing_data` | Rose Red | Required series or telemetry completely absent from observation |
| `VETO` | `.stage-pill.veto` | Rose Red | Risk gate or capital validation tripped, blocking downstream execution |
| `BLOCKED` | `.stage-pill.blocked` | Rose Red | Downstream execution halted due to missing prerequisites or upstream veto |

### Core Financial & Technical Acronyms
- **LTP**: Last Traded Price reported by the exchange.
- **ATM (At The Money)**: Option strike closest to the current spot price.
- **ITM (In The Money)**: Call strike below spot price, or Put strike above spot price.
- **OTM (Out Of The Money)**: Call strike above spot price, or Put strike below spot price.
- **CE (Call European)**: Right to buy underlying index/commodity.
- **PE (Put European)**: Right to sell underlying index/commodity.
- **IV (Implied Volatility)**: Market's forecast of underlying volatility reflected in option pricing.
- **PCR (Put-Call Ratio)**: Ratio of total open interest of Put options to Call options (sentiment indicator).
- **Delta ($\Delta$)**: Rate of change of option premium per ₹1 move in spot price.
- **Gamma ($\Gamma$)**: Rate of change of Delta per ₹1 move in spot price.
- **Theta ($\Theta$)**: Daily time decay of option premium.
- **Vega ($\mathcal{V}$)**: Sensitivity of option premium to a 1% change in implied volatility.
- **Brier Score**: Metric measuring calibration of probabilistic forecasts (0.0 = perfect accuracy).
- **Sharpe Ratio**: Risk-adjusted excess return per unit of volatility.

---

## 7. UI Maintenance Protocol for Developers and Agents

To ensure this document never becomes stale or out-of-sync:

1. **Mandatory Edit Rule**:
   - Whenever any file in `apps/web/app/` is edited (pages, components, CSS styles, or navigation):
   - You must review `docs/UI_WALKTHROUGH.md` and update any affected sections.
2. **Review Checklist for Pull Requests & Agent Tasks**:
   - [ ] Were any buttons, inputs, dropdowns, or toggles added or removed?
   - [ ] Were any default values or intervals changed (e.g., auto-fetch rates)?
   - [ ] Were any page layouts or tabs modified (e.g., analysis tab switcher)?
   - [ ] Were any new badges, colors, or status messages introduced?
   - [ ] Does the walkthrough document accurately describe the behavior seen in the live browser?
3. **Automated Enforcement**:
   - This invariant is codified in `.agents/rules/ui-documentation.md` and `AGENTS.md`. Future agents operating on this codebase will automatically verify and synchronize this file.
