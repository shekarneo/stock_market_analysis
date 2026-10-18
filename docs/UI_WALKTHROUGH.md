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
1. **NIFTY 50 (`NIFTY`)**: National Stock Exchange of India (NSE) benchmark equity index (50 large-cap stocks; lot size 25; strike interval 50 pts).
2. **BSE SENSEX (`SENSEX`)**: Bombay Stock Exchange (BSE) benchmark equity index (30 blue-chip stocks; lot size 20; strike interval 100 pts).
3. **CRUDEOIL MINI (`CRUDEOILMINI` / `CRUDEMINI`)**: Multi Commodity Exchange of India (MCX) energy commodity future/option contract (lot size 10 bbl; strike interval 50 pts).

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
- **Section `TRADE`** (8 primary operational destinations):
  1. `Overview`: High-level tape, order ticket, and market summary.
  2. `Analysis`: 12-agent consensus desk, scenarios, and Greek matrices.
  3. `Live & Auto Trading`: Live bot execution matrix, order book, and real-time risk controls.
  4. `Watchlist & Accuracy`: Historical tracking of suggestions against live spot moves.
  5. `Forecast`: Multi-horizon directional probability distributions and registered models.
  6. `Options`: Interactive strike matrix, Black-Scholes Greeks, and spread strategies.
  7. `Positions & Capital`: Ledger capital allocation, risk limits, and gate blockers.
  8. `System`: Health checks, 8-gate readiness audit, and data provenance.
- **Section `TOOLS`** (4 consolidated engineering & governance hubs):
  - **Collapsible Toggle**: Click `Tools Show (4) ▾` to expand; click `Tools Hide ▴` to collapse.
  - Automatically expands if navigating directly to any tool page (`/history`, `/backtest`, `/paper`, `/studio`, `/registry`, `/settings`, `/settings/integrations`).
  - When expanded, reveals:
    1. `Market Data & History` (`/history`): Interactive historical candle charts, data health audit, historical imports, and collapsible Groww/quarantine diagnostics.
    2. `Backtest & Walk-Forward` (`/backtest` & `/paper`): 19-fold walk-forward validation, factor attribution, and a unified switcher to `Paper Ledger & Intent Audit Replay` (`/paper`).
    3. `Model Studio & Registry` (`/studio` & `/registry`): Model versioning, side-by-side comparisons, and a unified switcher to `Model Registry & Execution Slots` (`/registry`).
    4. `Settings & API Keys` (`/settings/integrations` & `/settings`): Broker/LLM credential configuration, AI Agent model mapping, and a unified switcher to `Operator Profile & Account` (`/settings`).
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

### 4.1 Overview Desk (`/dashboard`)
- **Purpose**: The central executive single-pane cockpit providing a streamlined visual overview of market tape, forward forecast trajectory cones, visual 12-agent consensus decisions, and active order tickets without dense walls of text.
- **Components & Options**:
  1. **Active Posture Ribbon**:
     - Visual badge indicating current posture (`Active Posture`, `NO TRADE`).
     - Dynamic status message detailing whether virtual paper execution is active with configured risk controls or blocked pending configuration.
  2. **Quick Desk Shortcuts**:
     - `🤖 Open 12-Agent Analysis Desk →` (`/analysis`): Opens the full 12-agent consensus and options recommendation desk.
     - `⚡ Live & Auto Trading →` (`/live`): Opens the live paper/auto execution and outcome evaluation desk.
     - `📈 Statistical Forecasts & Accuracy →` (`/forecast`): Opens the multi-horizon quantitative forecast and Brier calibration desk.
     - `🎯 Options Chain & Greeks →` (`/options`): Opens the live strike matrix and Black-Scholes Greeks workstation.
  3. **Multi-Instrument Overview Card (`<MultiInstrumentOverviewCard />`)**:
     - 3-card comparison grid for NIFTY 50, SENSEX, and CRUDEOIL MINI.
     - Displays Spot LTP, Day Change (pts & %), Session Phase (`OPEN` / `CLOSED`), Trading Hours, Data Source, and options support status.
  4. **Live Candlestick & Forward Projected Trend Chart (`<PredictedTrendChart />`)**:
     - Embedded directly on the overview desk to provide visual price context.
     - Renders verified historical candlesticks (selectable 20, 35, or 50 bars), live streaming spot quotes, vertical cyan `NOW (Live Spot)` boundary line, forward projected 4-step trajectory path, expanding $\pm 1\sigma$ volatility confidence corridor, and target/stop badges.
  5. **Visual Multi-Agent Decision & Execution Cockpit (`<VisualAgentDecisionCard />`)**:
     - **Purpose**: Translates complex 12-agent mathematical and regime assessments into high-impact visual indicators, meters, and cards instead of dense text paragraphs.
     - **Execution & Context Toolbar**:
       - `Instrument Selector Chips`: Instant toggles for `NIFTY`, `SENSEX`, and `CRUDE` syncing with `MarketDataContext`.
       - `⚡ Run Live Analysis` Button: One-click CTA that triggers on-demand `POST /api/market-analysis` across all 12 specialist agents with an animated loading spinner.
     - **Visual Executive Verdict Deck**:
       - `Core Trade Decision Card`: High-impact stance badge (`🟢 STRONG BUY CE`, `🔴 STRONG BUY PE`, `🟡 STAND ASIDE · NO TRADE`) with deadband and safety gate indicators.
       - `Consensus Spectrum Meter`: Horizontal visual spectrum bar (-10 to +10) with Red-to-Green gradient and dynamic pointer showing exact net directional score (e.g. `+3.5 Bullish` or `0.0 Neutral`).
       - `Bayesian Epistemic Gate Meter`: Safety progress bar comparing composite epistemic uncertainty against the strict `0.65` cutoff threshold (`✓ Uncertainty Safe` vs `⚠️ Safety Veto Engaged`).
       - `Quant-Agent Confluence Card`: Visual confluence badge comparing machine learning calibrated probabilities (e.g. `53.8% P(Up)`) against specialist consensus to flag alignment or veto divergence.
     - **12 Specialist Perspectives Visual Grid**:
       - Displays all 12 quantitative specialist agents (News Sentiment 📰, Global Macro 🌐, Intermarket & MCX 🛢️, Order Flow 📊, Options & Greeks ⚡, Trend & Momentum 📈, Mean Reversion 🔄, HTF Resampling ⏱, Quant ML Forecaster 🔬, Bayesian Gate 🛡️, Expected Payoff 💰, Consensus Arbiter ⚖️).
       - Each card features: Agent Icon, Agent Name, Sub-Role, Visual Stance Badge (`BULLISH` in green, `BEARISH` in red, `NEUTRAL` in gray), and a visual confidence progress bar with percentage readout.
       - `Grid / Compact View Toggle`: Allows switching between a detailed grid view and a space-saving compact matrix.
  6. **Visual Order Ticket (`<TradeTicket />`)**:
     - Clean, focused order ticket showing current recommendation (`STAND ASIDE`), live Groww spot reference tag, side, structure, paper capital, and paper book readiness.
     - `Signal Status Badge`: Visually highlights paper filter qualification status.
     - `Blocker List (`<BlockerList />`)`: Renders active pipeline gate blockers as visual tag chips.
  7. **Market Tape & Verified Macro Indicators (`<Snapshot />`)**:
     - `<MarketBoard />`: Real-time quote cards across 10 domestic and global benchmarks (NIFTY, SENSEX, CRUDE MINI, INDIA VIX, S&P 500, NASDAQ, DOW JONES, US VIX, CRUDE OIL, USD/INR).
     - `Verified Market Macro Indicators Grid`: Clean visual cards displaying live prints for India VIX (NSE Volatility), USD/INR (RBI Reference), MCX Crude Oil, MCX Gold, Dow Jones, and GIFT Nifty.
     - `Collapsible Feed Provenance & Compliance Archive`: Expandable `<details>` drawer cleanly archiving raw tick inspection tables, provider readiness metadata, and synthetic fixtures for compliance auditing without cluttering the executive view.
  8. **Diagnostics Grid (`<LiveQuotes />` & `<Quarantine />`)**:
     - **Live Quotes Reader (`<LiveQuotes />`)**: Direct inspection of raw quotes retrieved from Groww with domestic indices, MCX commodities, global benchmarks, and sectoral/volatility prints, plus `Read Groww quotes` button.
     - **Quarantine Ledger (`<Quarantine />`)**: Table of any candle files quarantined due to invalid timestamp formatting, clock drift, or empty payloads.


---

### 4.2 Multi-Agent Analysis Desk (`/analysis`)
- **Purpose**: Deep institutional analysis synthesizing technical regimes, order flows, macro indicators, and Bayesian uncertainty gates across 12 specialized agents.
- **Top View Mode Navigation Bar**:
  - Uses the sticky global header `<InstrumentSelector compact />` (no duplicate selector banners).
  - **2 Focused View Modes + Direct Desk Links**:
    1. `🤖 Multi-Agent Decision Desk & Signals` (Default): Shows `V6Desk` with the core trade call, 12 specialist agents, master dossier, and news wire.
    2. `🧠 Institutional Intelligence Hub & Greeks`: Shows `V6IntelligenceHub` with correlation matrices, Greek radar, and 8-gate readiness.
    3. `📈 Forecasts & Accuracy →` link: Navigates directly to `/forecast` for multi-horizon statistical probability distributions and out-of-sample Brier calibration.
    4. `⚡ Live Desk →` link: Navigates directly to `/live` for automated paper trading and live contract evaluation.

#### Tab 1: Multi-Agent Decision Desk (`V6Desk`)
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
  - Granular Instrument Selector Chips: Select individual indices (NIFTY, SENSEX), MCX commodities (Crude Mini, Gold Mini, Silver Mini, NG Mini), and global benchmarks.
  - Execution Options:
    - `⚡ Combine ML Forecast with Agent Consensus (Quant Fusion)` toggle: Combines statistical model probabilities with the 12-agent consensus. When checked, automatically activates the forward forecast chart.
    - `📈 Forecast Graph: Visible` inline toggle button: Appears alongside Quant Fusion to quickly show or hide the `<PredictedTrendChart />` directly above the trade decisions.
    - `Include model commentary` toggle.
    - `🔄 Auto-run Analysis` toggle (`imm_auto_run_analysis`), and `Analysis auto-run interval` dropdown (`Every 30s`, `Every 1m (60s)`, `Every 2m (120s)`, `Every 5m (300s)`, `Every 15m (900s)`, persisted in `imm_analysis_interval_sec`).
  - Primary CTA: `Run analysis (X Selected)` button with live execution feedback.
- **6 Inner Desk Navigation Tabs**:
  1. `🎯 Trade Decisions & Options`: Real spot-based option picks (ATM/OTM/ITM), strike targets, stop losses, and agent consensus. When Quant Fusion is active, embeds `<PredictedTrendChart />` right above the decision matrix for instant trajectory and strike verification.
  2. `📈 ML Forecasting & Trend Graph`: Dedicated full-width workspace view rendering `<PredictedTrendChart />` with live Groww candlesticks, lookback selector (20, 35, 50 bars), cyan `NOW (Live Spot)` boundary line, forward projected trend path, and dynamic $\pm 1\sigma$ volatility confidence cones.
  3. `🤖 12 Specialist Agents`: The 12 quantitative specialist agents structured across 4 sequential analytical stages.
  4. `📋 Master Dossier & Pipeline (Stages 0–14)`: Institutional audit dossier containing 4 sub-tabs:
     - `V6 Master Dossier (Stages 0–14)`: Granular stage-by-stage cards covering Data Quality, Executive View, Global Macro, Fresh News, Geopolitics, Energy & FX, NIFTY Spot, SENSEX Spot, VIX & Sectors, Options Chain & OI, Price Confirmation, Quantitative Forecasts, Scenario Calibration, Contrarian Scan, and Final Verdict.
     - `Pipeline Stages (19)`: Complete tabular audit of all 19 pipeline nodes, displaying stage number, stage name, status pill badge, and explicit audit justification detail.
     - `Contradictions & Red Team`: Explicit contrarian challenges comparing macro narratives against price actions and technical order flows.
     - `Raw Observations`: Inspection table of all raw ingested telemetry rows, timestamps, data classes, SHA-256 hashes, and verification provenance.
  5. `📰 Headlines & News Wire`: Real-time news sentiment items with an embedded `⚙ Configure Feeds & Web Pages` collapsible drawer for `<NewsSourcesManager />`.
  6. `🛡️ Risk & Contradictions`: Expected Net Payoff, statutory friction breakdown (STT, exchange turnover, GST, SEBI charges, stamp duty, slippage buffer), hard risk limits, and fail-closed safety gates.

- **Trade Recommendation Card**:
  - Recommended Contract (e.g., `NIFTY 23200 CE 24-OCT`).
  - Entry Spot & Estimated Premium.
  - Target Spot & Target Premium.
  - Stop Loss Spot & Stop Loss Premium.
  - Risk/Reward Ratio (e.g., `1 : 2.4`).
  - **Quant-Agent Fusion Banner (`recommendation.quant_fusion`)**:
    - `Confluence Status Badge`: `🟢 HIGH CONFLUENCE (STRONG SIGNAL)` when Multi-Agent stance and ML forecast probability align (`>52%` Up or `<48%` Down), `🔵 STANDARD CONFLUENCE` when the ML model is in the neutral `48%–52%` deadband, or `⚠️ DIVERGENCE (CAUTION / VETO RISK)` when the ML model leans strongly against the Multi-Agent stance.
    - `ML Model Prob`: Displays 1-decimal calibrated probabilities (`<up>% P(Up) / <down>% P(Down)`).
    - `Agent Score`: Displays the signed Multi-Agent score (`+4`, `+2`, `-2`, etc.) propagated from `consensus.total_score`.
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
  - Emergency circuit breaker: Immediately halts all automated trading, forces `imm_auto_trading_enabled` to `false` in `localStorage`, cancels open pending orders, and blocks new order generation.
  - Displays red warning banner when tripped: *"Engine locked by operator. Open orders squared off. Reset to resume."*
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
  - Real-time Spot LTP and change.
  - Trading session hours and market state.
  - Multi-Agent Signal badge (`STRONG_BUY_CE`, `BUY_CE`, `WAIT`, `BUY_PE`, `STRONG_BUY_PE`).
  - Directional Confidence Score (%) and primary drivers.
  - Option trade pick with strike, expiry, target spot, stop-loss spot, and estimated premium.
  - **`+ Add to Watchlist` Button**: Enrolls the trade in the accuracy tracker.
  - **`⚡ Execute Trade Now` Button**: Submits the order to the active execution mode (Paper or Live).

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
  - Columns: Underlying, Contract, Entry Spot, Target Spot, Stop Loss Spot, Current Spot, Model Premiums (Entry, Running LTP, Target, Stop Loss), P&L (%), Status Badge, and Actions (`Exit` / `Cancel`).
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
  - `Entry Spot (₹)` numeric input: Pre-filled with live underlying spot price.
  - `Target Points (pts)` numeric input: Default 50 pts (NIFTY), 150 pts (SENSEX), or 40 pts (CRUDEOILMINI).
  - `Stop Loss (pts)` numeric input: Default 25 pts (NIFTY), 75 pts (SENSEX), or 20 pts (CRUDEOILMINI).
  - `Est. Prem. (₹)` numeric input: Theoretical entry option premium (default ₹120.00).
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
  - `Contract`: Clickable link navigating directly to `/dashboard?instrument=...` with sub-link to `/analysis`. Displays option direction tag and data class.
  - `Status`: Color-coded pill (`Open`, `Target hit`, `SL hit`, `Expired`, `Cancelled`).
  - `Prem. Entry`: Theoretical entry option premium and lot size.
  - `Running Prem.`: Real-time estimated option premium modeled on live spot delta, showing color-coded running gain/loss percentage.
  - `Prem. Target` & `Prem. SL`: Target (+40%) and Stop-Loss (-25%) premium estimates.
  - `Spot Entry`, `Spot Target`, `Spot SL`: Underlying spot boundary levels.
  - `Last Spot`: Most recent observed spot price with total checks count and time.
  - `Best / Worst`: Maximum favorable and maximum adverse spot excursions observed.
  - `Saved` & `Resolves`: Creation timestamp, expiry time, and resolution price.
  - `Cancel` button: Available on `OPEN` suggestions to manually abort tracking.

---

### 4.5 Multi-Horizon Forecast Desk (`/forecast`)
- **Purpose**: Quantitative multi-horizon forecasting, directional probabilities, and empirical out-of-sample calibration tracking.
- **Components & Controls**:
  - **Live Candlestick & Forward Projected Trend Chart (`<PredictedTrendChart />`)**:
    - **Purpose**: Combines verified historical candlesticks, live market spot price action, and ML forward projected trajectory with dynamic confidence cones ($\pm 1\sigma$ volatility corridors), target spot, and stop-loss levels.
    - **Header Controls & State**:
      - `Instrument Selector Pills`: One-click buttons for `NIFTY 50`, `BANK NIFTY`, `BSE SENSEX`, and `CRUDEOIL MINI`. Automatically synchronizes with global `MarketDataContext`.
      - `Lookback Window Pills`: Choose historical bar depth (`20 Bars`, `35 Bars`, `50 Bars`).
      - `Live Market Status Pill`: Green pulsing indicator displaying `🟢 LIVE STREAM ACTIVE` when streaming live Groww quotes, or `🟡 VERIFIED FEED` with last tick timestamp.
    - **Key Metrics Ribbon**:
      - `Live Spot Price`: High-visibility bold current underlying market price.
      - `Predicted Direction & Decision Badge`: Pill indicating `🟢 BULLISH (BUY)`, `🔴 BEARISH (SELL)`, or `🟡 NEUTRAL (STAND ASIDE)`.
      - `Calibrated Probability`: Model calibrated confidence (e.g. `54.2% P(Up)`).
      - `Horizon & Model`: Horizon (e.g. `+4 Bars (60m)`) and serving model architecture (`LightGBM M37`).
      - `Target Spot & Potential Gain`: Target price in INR and points / percentage move.
      - `Stop Loss & Invalidation Risk`: Protective stop price in INR and risk distance.
    - **Interactive Candlestick & Projection Chart Area**:
      - `Historical OHLC Candlesticks`: Green (`#10b981`) bullish and Red (`#f43f5e`) bearish candles with vertical wicks and rectangular bodies representing historical interval bars.
      - `NOW (Live Spot) Vertical Divider`: Prominent cyan dashed line (`#38bdf8`) separating realized historical data from the future predictive horizon, adorned with a glowing live spot price tag.
      - `Projected Forecast Path`: Dashed colored trajectory line projecting future prices across upcoming intervals ($T+1$, $T+2$, $T+3$, $T+4$).
      - `Probabilistic Confidence Corridor (Cone)`: Semi-transparent shaded cone expanding into the future representing $\pm 1\sigma$ volatility bounds derived from historical ATR and calibrated variance.
      - `Target & Stop Loss Horizontal Markers`: Dashed target line (`#10b981`) with `TARGET` badge and dashed stop line (`#f43f5e`) with `STOP LOSS` badge.
      - `Interactive Crosshair & Hover Tooltip`: Moving across historical candles reveals exact Bar Open, High, Low, Close, and Volume; hovering future projection points displays Projected Spot, Upper Confidence Bound, Lower Confidence Bound, and Delta from current spot.
      - `Chart Legend`: Color keys for Bullish Bar, Bearish Bar, Live Spot, Forward Projection, and Confidence Corridor.
  - `<InstrumentSelector />`: Select primary underlying to inspect.
  - `<InstrumentForecastCard />`: Displays forecast cards for 1-hour, 4-hour, 1-day, and 5-day horizons with calibrated probabilities and expected return.
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
      - `Individual Benchmark Scorecard`: Holdout Accuracy %, Brier Skill Score, Holdout Net Return (2.0 bps friction), and Full Max Drawdown %.
      - `Strategy Comparison Matrix Table`: Displays all strategy gating variations for the evaluated model with `SELECTED` badge on the active mode.
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
      - `Champion Trophy Summary Cards`:
        - `🏆 #1 Champion Model & Strategy`: Displays the top-ranked combination across all assets, its holdout net return %, mode, and accuracy.
        - `🎯 Top Holdout Accuracy`: Highest directional accuracy model and Brier Skill Score.
        - `🛡 Lowest Max Drawdown`: Model with minimal peak-to-trough equity drawdown.
        - `📊 Evaluated Combinations`: Total combinations tested across the 19 expanding folds.
      - `🥇 Top Champion Model by Instrument Cards`:
        - Dedicated cards highlighting the #1 winning model, mode, holdout return, and accuracy for each evaluated instrument (`NIFTY`, `BANKNIFTY`, `SENSEX`, `CRUDEOILMINI`).
      - `Filter Instrument Dropdown`:
        - Instant client-side filtering (`All Instruments`, `NIFTY`, `BANKNIFTY`, `SENSEX`, `CRUDEOILMINI`).
      - `🏆 Ranked SOTA Walk-Forward Leaderboard Table`:
        - Ranked by Holdout Net Return after 2.0 bps friction with tie-breakers on accuracy and full walk-forward net return.
        - Medals for top positions: `🥇 #1`, `🥈 #2`, `🥉 #3`, followed by numeric rank `#4`, `#5`, etc.
        - Columns: `Rank`, `Instrument`, `Model Architecture`, `Strategy Mode`, `Holdout Net Return (2bps)`, `Full Net Return (2bps)`, `Holdout Accuracy`, `Brier Skill Score`, `Max Drawdown`, `Status` (`ALPHA+` in green or `NEGATIVE` in amber).
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
  - Real-time calculations for Delta ($\Delta$), Gamma ($\Gamma$), Theta ($\Theta$), Vega ($\mathcal{V}$), Implied Volatility (IV), and Put-Call Ratio (PCR).
- **Live Option Strike Matrix**:
  - Automatically identifies real-time At-The-Money (ATM) strike based on verified live Groww spot quotes.
  - Fail-closed empty state: If live spot quotes are not yet retrieved, renders an awaiting feed notification without inventing fictitious prices.
  - Accurate exchange lot sizes: 25 for NIFTY, 20 for SENSEX, and 10 for CRUDEOIL MINI.
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
  - Net Sharpe Ratio, Max Drawdown %, Win Rate %, Profit Factor, Annualized Return.
  - Transaction Costs Breakdown: STT (Securities Transaction Tax), Exchange Turnover Fees, GST, and Stamp Duty.
- **Factor Attribution Card (`<V6MultiAssetCard />`)**:
  - Decomposes strategy returns into Market Beta, Momentum, Volatility Regime, and Mean Reversion factors.

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
  - `Inspect Benchmark Trades (67) / Collapse Benchmark` button: Collapsible drawer toggling the detailed historical replay records.
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
