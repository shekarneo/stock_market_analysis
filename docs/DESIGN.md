# India Market Master — System Design

**Status:** Reviewed design. M0 through M6 exist in the repository. M5 is the research model registry and Forecast Model Studio. M6 adds the historical-candle boundary, quality report, and source-dataset store. Genuine Groww history was not retrieved: the candle timestamp role and timezone are unverified. Settings includes an API integrations page for Groww and OpenAI credentials. Saving a credential does not verify it and does not enable trading. The registry does not approve paper or live trading. M8 runs a LangGraph evidence report and does not approve a model. M8.1 records provider and node failures on that report and does not treat a failed commentary call as analysis. Optional OpenAI commentary stays off unless the request asks for it, and a failed or skipped completion leaves the deterministic report unchanged. A later verified-history check did not create a trusted NIFTY dataset. Upstox, Kite Connect, Angel One, and DhanHQ were read on 14 Oct 2026 and were not connected. A later checklist left timezone, candle boundary, and partial candles unverified, so no new read was sent. Options valuation, paper trading, and live trading are not implemented. `forecast_ready` and `real_market_data_verified` stay false. Live trading is not implementation-ready; the blockers are in `docs/OPEN_QUESTIONS.md`. A local check of the stored Groww quarantine confirmed the record checksums and left the timestamp contract unverified. No trusted dataset was created.
**Sources:** `docs/India_Market_Master_V6_Multi_Agent_Spec.md` (analysis workflow) and `docs/Cursor_Prompt_Autonomous_Groww_Trading_Platform.md` (product and execution).
**Companions:** `docs/FORECASTING_AND_BACKTEST_SPEC.md`, `docs/MODEL_REGISTRY_AND_STUDIO_SPEC.md`, `docs/LANGGRAPH_ORCHESTRATION_SPEC.md`, `docs/OPTIONS_EXPECTED_VALUE_SPEC.md`, `docs/RISK_AND_EXECUTION_SPEC.md`, `docs/DATA_SOURCE_MATRIX.md`, `docs/IMPLEMENTATION_PLAN.md`, `docs/DESIGN_REVIEW_RESOLUTIONS.md`, `docs/OPEN_QUESTIONS.md`.
**Intent:** The system design. The companions hold the formulas and the source matrix so this file does not drift from them. Where they disagree, the companion written for that topic wins and this file must be updated to match.

This is decision support for Indian index markets, with optional paper trading and a locked-off path to live Groww orders. It is not a system that promises profits or removes the chance of loss. Long options can expire worthless. A correct index call can still lose money after premium, theta, IV, spread, and costs.

---

## 1. Product

A local web application that, on demand and on a schedule:

1. Pulls timestamped data for **NIFTY 50, SENSEX, and CRUDEOILMINI**, their option chains, futures, flows, and news. **Crude oil is pulled on every run.** USD/INR and gold are pulled with it. Further cross-asset series are added only while a day, week, or month geopolitical situation is active. BANK NIFTY was removed from scope.
2. Checks that data before anyone interprets it.
3. Runs specialist analyzers that return typed evidence.
4. Forecasts the **underlying** on separate tasks. Calibrated probabilities come only from a promoted model. Otherwise the forecast is qualitative and the trade decision is `NO TRADE`.
5. Estimates modelled option/futures expected net from that forecast, the live bid and ask, and costs. Compares the result with `NO TRADE`. A higher index does not by itself select a call.
6. Lets a **deterministic risk engine** veto every candidate.
7. Writes a V6 report, stores the forecast before the outcome exists, and later scores it.
8. Simulates orders in paper mode. Live orders stay disabled until the owner turns them on through configuration, a server flag, and a confirmation in the UI.

Allowed verdicts, and no others:

- `BULLISH BIAS — WAIT FOR CONFIRMATION`
- `BEARISH BIAS — WAIT FOR CONFIRMATION`
- `RANGE / NO DIRECTIONAL EDGE`
- `NO TRADE — RISK / DATA / CONFLICT`
- `INSUFFICIENT DATA`

The market verdict and the trade decision are different. The verdict is a display label. It is not a probability and it does not authorize an order.

| Condition | Verdict |
|---|---|
| Critical data-quality failure | `INSUFFICIENT DATA` |
| Forecast qualitative, or no unique largest class | `NO TRADE — RISK / DATA / CONFLICT` |
| Unique largest class is `up` | `BULLISH BIAS — WAIT FOR CONFIRMATION` |
| Unique largest class is `down` | `BEARISH BIAS — WAIT FOR CONFIRMATION` |
| Unique largest class is `range` | `RANGE / NO DIRECTIONAL EDGE` |

The class probabilities are the fusion output, which is the quantitative forecast while `fusion_status` is `BASELINE_ONLY`. "Unique" means the largest probability exceeds the next by more than the `0.01` sum tolerance. No other cutoff is used.

The trade decision vocabulary is `BUY_CE`, `BUY_PE`, `BUY_FUT`, `SELL_FUT`, or `NO_TRADE`. (Futures decisions apply to CRUDEOILMINI only, and require explicit allow-list activation, a mandatory stop-loss, and known margin). A buy or sell decision is still conditional on the entry trigger, a fresh quote, the risk engine, and the mode's approval rule. It is not an order by itself. A proposal with a missing mandatory field has `status = INCOMPLETE` and `decision = NO_TRADE`, and cannot be submitted.

### Who it is for

One operator, on one machine, using their own Groww account. There is no multi-tenant product in this design.

### In scope

- Research dashboard and the full V6 report.
- Settings for every behavior parameter, including which news and article sources are fetched.
- Option-chain scanner and contract comparison.
- Versioned forecasts, baselines, and later walk-forward evaluation.
- Paper trading through the same order state machine as live.
- Groww read access (funds, positions, orders, market data the official API actually provides).
- Live order placement only as a final, explicitly enabled milestone.

### Out of scope

- Auto-transfer, deposit, or withdrawal of money.
- Browser automation or undocumented Groww endpoints.
- Hardcoded lot sizes, invented premiums, invented OI, invented IV, or LLM-written probabilities.
- Martingale, averaging down, revenge sizing, or raising limits after a loss.
- Treating SENSEX as a copy of NIFTY, or treating one day’s FII/DII print as a next-session signal.
- Claiming a stop order caps loss during a gap or in an illiquid contract.
- Multi-user accounts, mobile-first UI, TimescaleDB, and a separate queue cluster. Those can be added later if a real constraint appears.

---

## 2. Decisions to confirm

These are the choices this design locks so implementation can start. Change any of them in review and the build follows the change.

| # | Decision | Default in this design |
|---|---|---|
| 1 | Shape of an “agent” | Three planes. LangGraph orchestrates the V6 evidence workflow. Cursor local agents are the language-model runtime inside specialist nodes. Python computes prices, indicators, option math, model probabilities, fusion, risk vetoes, and orders. |
| 2 | Process model | One FastAPI app and one worker process. A Postgres row lease prevents two workers from submitting the same order. No Redis or Celery until a milestone is blocked without them. |
| 3 | Database | PostgreSQL from the first milestone, via Docker Compose. Alembic migrations. SQLite is not a second schema to maintain. |
| 4 | Frontend | Next.js, TypeScript, Tailwind, shadcn/ui, TradingView Lightweight Charts. |
| 5 | API contract | FastAPI + Pydantic, OpenAPI as the frontend contract. |
| 6 | Default runtime mode | `PAPER`. `LIVE_TRADING` cannot be reached from a prompt, agent output, or missing config. |
| 7 | Tradable underlyings | Analysis covers NIFTY, SENSEX, and BANK NIFTY. Default **order** allow-list is NIFTY and BANK NIFTY. SENSEX options join the allow-list only after the Groww instrument master confirms the contract. |
| 8 | Options the system will propose | Long CE and long PE only. No short options, no spreads, no futures orders in the first live milestone. |
| 9 | Forecast tasks | Separate models for configurable horizons. Candidates are `M1`, `M5`, `M15`, `M30`, `H1`, `SESSION`, and `NEXT_SESSION`. A horizon is selectable only when the registry has that scope. `M1`, `M5`, and `H1` are not enabled until data, labels, and an evaluation exist. Tasks are not mixed. |
| 10 | Range label | `up` / `down` / `range` use a threshold `T` chosen on training and validation data only, then frozen before the untouched test. The old fixed percentages are not approved. |
| 11 | Fusion | The quantitative forecast is the baseline. A fusion model may influence paper or live entries only after it beats that baseline under `docs/FORECASTING_AND_BACKTEST_SPEC.md`. Hand-set weights cannot authorize a trade. |
| 12 | Risk capital | A configured rupee budget, never the full Groww balance. Starting defaults in section 12. |
| 13 | Human gate | Every live order needs operator confirmation until a later, separate setting enables unattended mode. Unattended mode still passes the risk engine. |
| 14 | Providers | Everything external sits behind an interface. Missing coverage is stored as missing data and lowers confidence or blocks the run. No silent scrape of restricted sources. |
| 15 | Context book | Crude is standing: every run requests Brent and, when the contract spec exists, MCX Crude Oil Mini. A situation registry adds other series for an active day, week, or month. A Cursor agent cannot invent a ticker. |
| 16 | Reasoning runtime | LangGraph `StateGraph` is the orchestrator (`docs/LANGGRAPH_ORCHESTRATION_SPEC.md`). Specialist nodes call Python `cursor-sdk` local agents. Cloud Agents REST is not the runtime. The graph is not a parent Cursor agent and is not the forecasting model. |
| 17 | Configuration | Behavior lives in versioned Postgres config, seeded from `config/defaults.yaml`. Environment variables hold secrets and bind addresses only. News outlets are rows the operator enables. |
| 18 | Model registry | Lifecycle, scope, and the Forecast Model Studio are `docs/MODEL_REGISTRY_AND_STUDIO_SPEC.md`. Research selection, paper activation, and live approval are separate actions. No candidate family in that spec is trained in this repository. |
| 19 | In-flight model pin | A run stores the model version before inference and before the graph starts. A later studio change does not alter that run. |

---

## 3. Operating rules

These rules override a confident model, a strong headline, and a UI that wants to show a trade.

1. Fresh, timestamped data comes before any view.
2. Facts, reports, model outputs, inferences, and scenarios stay labelled. The report agent may phrase them. It may not change a model probability.
3. Price, breadth, volume, and cross-asset reaction outrank the story told about them.
4. Every directional view carries the opposite case and an invalidation condition. If invalidation cannot be stated, the setup is not trade-ready.
5. Probabilities come from a calibrated model or are marked qualitative. The LLM does not fill in `p_up`.
6. The risk engine is plain code. It can veto. Nothing in a prompt can clear a veto or edit a limit.
7. `NO TRADE` and `INSUFFICIENT DATA` are successful outputs.
8. A timeout after an order submit is `UNKNOWN_REQUIRES_RECONCILIATION`, not a failed order. No retry until the broker order book and positions match local state.
9. Paper mode has no code path that calls a live order endpoint.
10. Every forecast is stored before the horizon elapses, then scored.

---

## 4. Runtime modes

| Mode | Market data | Orders | How it is entered |
|---|---|---|---|
| `REPLAY` | Stored session snapshots | None. The run is historical and cannot submit. | Operator picks a session. |
| `PAPER` | Live providers where configured, otherwise fixtures | `PaperBroker` only | Default. |
| `LIVE_READ_ONLY` | Groww official read APIs | None. Funds, positions, and orders are visible. | Credentials present and a read-only connection test has passed. |
| `LIVE_TRADING` | Same as read-only, plus fresh quotes | `GrowwAdapter` place/modify/cancel | All three of: config flag, server feature flag, UI confirmation. Each live order still confirms until unattended mode is separately enabled. |

The active mode is stored server-side and rendered as a persistent banner. Live mode uses a distinct visual treatment so it cannot be mistaken for paper.

Mode checks happen in the execution service, not only in the page. A paper request that arrives while the server is in `LIVE_TRADING` still cannot skip confirmation. A live request that arrives while the server is in `PAPER` is rejected.

---

## 5. Architecture

```text
Operator UI (Next.js)
        |
        | HTTPS, typed JSON
        v
FastAPI  ---- reads/writes ---- PostgreSQL
        |
        | enqueues AnalysisRun / OrderIntent
        v
Worker (single leader via row lease)
        |
        +-- Context book (standing crude + active situations)
        +-- MarketDataProvider ---- Groww read | Replay store | fixtures
        +-- CommodityProvider, MacroProvider, NewsProvider, FlowProvider
        +-- Fact packs (indicators, chain math, model probabilities)
        +-- Cursor reasoning plane (local cursor-sdk agents, section 5.1)
        +-- Analysis pipeline (typed modules, section 9)
        +-- RiskEngine (pure functions)
        +-- ExecutionService
                |
                +-- PaperBroker
                +-- GrowwAdapter   (live writes only in LIVE_TRADING)
```

The UI never calls Groww or Cursor. The worker is the only process that holds `CURSOR_API_KEY`. A Cursor agent never holds a broker client. Only `ExecutionService` can call an order method, and only with a persisted `OrderIntent` that has already passed `RiskEngine`.

### 5.1 Multi-agent reasoning

Analysis evidence is a LangGraph workflow of specialist nodes. The graph decides only the edges in `docs/LANGGRAPH_ORCHESTRATION_SPEC.md`. A Cursor agent does not choose the next agent, and it does not spawn subagents. Quantitative forecasting is Path A in that spec and is not a graph node.

**Client.** The worker uses the Python SDK (`cursor-sdk`) through one `AsyncClient` per process. Each specialist call is a local agent: `local=LocalAgentOptions(...)` is set explicitly. Cloud is not used. Cloud runs on a VM, can clone a repo and open a pull request, and the tool allowlist and custom tools are local-only. The Cloud Agents REST API (`/v1/agents`) is the same family of APIs; this design calls them through the Python SDK rather than raw HTTP.

**Call shape.** One shot per specialist per analysis run, via `AsyncAgent.prompt`, so the agent is disposed when the run finishes. Pass `api_key` explicitly. Model id comes from config, starting default `composer-2.5`, and must be one returned by `Cursor.models.list()` for this key. Log `agent_id` and `run.id` before waiting. `CursorAgentError` means the run never started: retry only when `is_retryable` is set. `result.status == "error"` means the run started and failed: mark that agent `quality = FAIL` and do not invent its section. If the text is not valid evidence JSON, send one repair prompt with the validation error, then fail the agent. Downstream stages treat a failed agent as missing input. If Cursor is unavailable, the affected graph node is missing, fusion still runs on the quantitative forecast and the fact packs, and the report says reasoning was unavailable.

**What each agent is allowed to do.** `cwd` is an empty per-run scratch directory, not the application repo. Do not set `setting_sources`. Do not pass MCP servers. Do not pass `agents=` subagent definitions, and disallow the `task` tool so a specialist cannot launch another agent. The LangGraph compiled graph is the only dispatcher.

| Cursor agent | Reasons about | Built-in tools | Reads via custom tools |
|---|---|---|---|
| `news_verification` | Source status, event time vs publish time, priced-in, contradictions | `webSearch` only if `cursor.news_open_web` is on | fetched articles from enabled sources |
| `global_macro` | Transmission into Indian indices, for and against | `webSearch` only if `cursor.macro_open_web` is on | macro fact pack |
| `crude_cross_asset` | Observed oil, INR, and gold relationship for this window; active situation | none | commodity and FX fact pack |
| `index_technical` ×3 | Separate NIFTY, SENSEX, and BANK NIFTY cases, invalidation | none | that symbol’s indicator fact pack only |
| `breadth_flow` | Whether the move is broad, and what dated flows do and do not say | none | VIX, breadth, FII/DII fact pack |
| `options_chain` | OI, PCR, IV, and liquidity in words, with the stated caveats | none | chain-metrics fact pack |
| `contrarian` | The strongest case against the leading view | none | prior agents’ evidence JSON |
| `report` | V6 narrative from stored objects | none | full evidence bundle, read only |

`tools=[]` is the allowlist, except the news and macro agents receive `webSearch` only when their open-web flags in section 7 are on. Custom tools stay available because they are not built-ins; disallowing `mcp` would remove them, so do not disallow `mcp` unless those read tools move. Custom tools are Python functions on `LocalAgentOptions.custom_tools`: `get_snapshot`, `get_fact_pack`, `get_evidence`. They return rows already stored for this `run_id`. They do not query the broker, the shell, or SQL.

**Deterministic services, no Cursor call.** Market data, data quality, the context book, indicator and chain calculators, `quant_forecast`, `forecast_fusion`, `options_ev`, `outcome`, the risk engine, and execution. Section 5.2 is the roster.

### 5.2 Agent roster

Cursor agents time out at a configured limit (shipped default 90 seconds) and deterministic services at another (shipped default 10 seconds). A timeout, invalid schema, or tool error marks that agent `FAIL`. Downstream code treats the section as missing. It does not fill in a view. Every run stores the input ids, the output JSON, the config revision, and, for Cursor, `cursor_agent_id` and `cursor_run_id`.

Schemas reject any probability field on a Cursor agent. The only objects that may contain `p_up`, `p_range`, and `p_down` are `Forecast` and a fusion row that copied or computed them under section 7 of the forecasting spec.

| Agent | Class | Inputs | Outputs | Tools | Abstains when |
|---|---|---|---|---|---|
| Market data | Service | Context book, source config | Snapshots, candles, chain, quotes | Provider read methods | A critical index quote is absent. The run becomes `INSUFFICIENT DATA`. |
| Data quality | Service | Those snapshots | `PASS` / `WARN` / `FAIL` and the conflicting values | None | It does not abstain. `FAIL` on a critical field blocks the run. |
| News verification | Cursor | Enabled-source articles only | Status, times, URLs, theme tags | `webSearch` only if `cursor.news_open_web` is on | No enabled sources, or the model reply fails schema. |
| Global macro | Cursor | Macro fact pack | Transmission notes and contrary notes. No probabilities. | `webSearch` only if `cursor.macro_open_web` is on | The fact pack is empty. |
| Crude and INR | Cursor | Crude, gold, USD/INR pack, active situations | Observed relationship and window. No probabilities. | None | Standing crude is missing. Oil language is then forbidden, not invented. |
| NIFTY technical | Cursor | NIFTY fact pack only | Structure, evidence, invalidation. No probabilities. | None | NIFTY candles failed quality. |
| SENSEX technical | Cursor | SENSEX fact pack only | Same, from SENSEX candles. | None | SENSEX candles failed quality. |
| BANK NIFTY technical | Cursor | BANK NIFTY fact pack only | Same, from BANK NIFTY candles. | None | BANK NIFTY candles failed quality. |
| Breadth and flows | Cursor | VIX, breadth, dated FII/DII | What the prints do and do not support. | None | The pack is empty. |
| Options chain | Cursor | Chain metrics | Liquidity, OI, IV, and expiry notes. No probabilities and no premium invention. | None | The chain snapshot failed quality. |
| Quantitative forecast | Service | Feature row at the cutoff, model version | `Forecast` in the forecasting spec | Model artifact read | No approved calibrated model. Output is qualitative and the trade decision is `NO TRADE`. |
| Contrarian | Cursor | Prior evidence, not the risk ledger | Counterevidence list | None | It still returns an empty counterlist marked as such. It cannot abstain by vetoing. |
| Forecast fusion | Service | Quantitative `Forecast`, optional approved fusion artifact | Distribution used for the decision, `fusion_status` | None | Baseline missing. Status stays qualitative. |
| Options contract selection | Service, plus a Cursor explanation that cannot change numbers | Forecast, master row, bid/ask, charges | `decision` of `BUY_CE`, `BUY_PE`, or `NO_TRADE`, plus `status` of `COMPLETE` or `INCOMPLETE`, and the modelled expected net when a method is allowed | The service reads quotes and margin. The explanation agent has no broker tool. | Method in the options spec is disabled, sizing is below one lot, or no candidate beats `NO TRADE`. `INCOMPLETE` is the status when a buy field is missing. |
| Report | Cursor | Stored objects after the decision exists | V6 narrative | None | It still emits a stub that quotes the stored decision. It cannot change numbers. |
| Outcome tracking | Service | Forecasts whose endpoint has passed | Scores. Does not edit the forecast. | None | The endpoint is not yet known. |

The three index agents run in parallel and do not see each other's prose. News finishes before a day-situation refresh. Contrarian runs after the other reasoning agents and before the trade decision is shown. Fusion does not wait for the report. The contrarian agent cannot override the quantitative forecast or the risk engine.

Risk and execution sit after contract selection. Their contracts are `docs/RISK_AND_EXECUTION_SPEC.md`. They are not graph nodes and they are not in the Cursor fan-out.

### Repository layout

```text
apps/web/                 Next.js UI
apps/api/
  app/main.py             FastAPI routes
  app/domain/             Pydantic and SQLAlchemy models
  app/config/             schemas, defaults loader, revision store
  app/pipeline/           fact packs, fusion, deterministic stages
  app/reasoning/          LangGraph definition, Cursor node calls, one module per reasoning agent
  app/providers/          MarketData, News, Macro, Flow, Broker
  app/risk/               gates and policy
  app/execution/          state machine, paper broker, Groww adapter
  app/prompts/            versioned templates and the context builder
  app/models_ml/          training, inference, evaluation
  app/worker.py           scheduler and lease
  tests/
  alembic/
config/defaults.yaml      reviewed defaults, loaded once into revision 1
docs/                     source specs and this design
docker-compose.yml        web, api, worker, postgres
.env.example              placeholders only
```

Lot size, fees, label grids, and fusion research gates live in versioned config, not in prompt text. The catalog is section 7. Lot size for an order still comes from the instrument master, not from config.

---

## 6. Domain model

An **analysis run** is the unit of work. Child rows are immutable after the run completes. A later outcome links back; it does not rewrite the forecast.

### AnalysisRun

`id`, `mode`, `config_revision`, `requested_by`, `trigger` (`MANUAL` | `SCHEDULE` | `REPLAY`), `status` (`QUEUED` | `RUNNING` | `COMPLETED` | `FAILED` | `BLOCKED`), `market_status` (`PRE_OPEN` | `OPEN` | `CLOSED` | `UNKNOWN`), `data_cutoff`, `started_at`, `finished_at`, `verdict`, `prompt_bundle_hash`, `model_version_id` (pinned at start; null until a registry exists), `graph_thread_id` (the run id when LangGraph is used).

Model registry, evaluation, activation, and forecast-run tables are `docs/MODEL_REGISTRY_AND_STUDIO_SPEC.md` section 10. LangGraph checkpoint tables are created by `AsyncPostgresSaver.setup()` in the LangGraph milestone, not by a hand-copied schema.

`BLOCKED` means data quality failed a critical check and the run stopped before a directional view.

### MarketSnapshot

One row per symbol per run: `schema_version`, `instrument_id`, `underlying`, `last_price`, `open`, `high`, `low`, `close`, `volume` (null when the source has no volume), `source_id`, `origin` (`SYNTHETIC`, `DOCUMENTED_SAMPLE`, or `PROVIDER`), `event_timestamp`, `provider_timestamp`, `retrieved_at`. Timestamps are timezone-aware and stored in Asia/Kolkata. Candles use `bar_start`, `bar_end`, and the same origin rule. A synthetic row is never labeled as a live print. `change_pct` and `prev_close` are omitted until a provider actually supplies them.

### FeatureDataset

M2 stores one JSON artifact per instrument and feature build. The file holds the manifest and the feature rows. Postgres is not used for these artifacts: the candles and the feature configuration are inside the file, and a SHA-256 checksum covers that body. The checksum is the dataset id. A different feature version, calendar, or source series produces a different id.

The manifest records schema version, feature-set version `ohlc-1`, pipeline version, instrument, M15 interval, origin, source id, source-candle hash, start and end, source retrieval time, feature formulas, lookbacks, missing-data policy, fixture calendar version, validation issues, row counts, the synthetic flag, and null untouched-test dates. `forecast_ready`, `paper_approved`, and `live_approved` are false. `live_market_data` is false.

A candle is usable at `bar_end` only when `retrieved_at` is at or after `bar_end`. The feature row `as_of` is that `bar_end`. `provider_timestamp` is not the completion time. Trailing windows stop at `as_of`. The fixture calendar is not an official NSE or BSE calendar. Formulas and the missing-value statuses are `docs/FORECASTING_AND_BACKTEST_SPEC.md` section 3.

### ForecastExperiment

M3 can fit a majority-class baseline, a last-return-sign baseline, and an L2 logistic regression on an existing feature artifact. The last-return-sign rule is the persistence baseline: class `1` only when `ret_1` is positive. The target is the experimental binary label `binary-1`: the next M15 close-to-close return is class `1` only when it is strictly positive. The split is one time-ordered train, validation, and test holdout. Its embargo drops a row whose label candle is the first candle of the next period. Validation log loss chooses the model. Differences of at most `1e-12` are ties. The test scores are stored and do not make that choice. The experiment id is a checksum of the canonical JSON and does not include a write time. `forecast_ready` stays false, including when training succeeds on synthetic data. The formulas, metrics, and limits are `docs/FORECASTING_AND_BACKTEST_SPEC.md` sections 2.4 and 4.

### WalkForwardEvaluation

M4 scores the same three models on expanding training windows and fixed validation and test windows, evaluation version `m4-expanding-1`. Each fold records its raw and eligible counts, embargoed keys, and prevalence. Validation chooses the model. Test metrics are stored separately for every fitted model and for the selected model. Failed folds stay in the report. Macro averages weight each successful fold equally and skip undefined metrics. Pooled metrics concatenate the selected model's disjoint test predictions. The walk-forward id is a checksum with no write time. The dataset artifact is not rewritten. `forecast_ready`, `paper_approved`, `live_approved`, and `real_market_data_verified` stay false. Synthetic and documented-sample origins stay visible. The settings page can run the synthetic fixture through this harness; that result is a mechanics check, not market performance.

### ModelRegistry

M5 stores registry versions in one locked JSON document, `var/registry/registry.json`. A version is immutable in its fitted state. `REGISTERED` has no fit. `TRAINED` points at a verified M3 or M4 artifact and copies that artifact's configuration. `EVALUATED` requires an explicit citation of a linked walk-forward report. `APPROVED_FOR_RESEARCH` requires another explicit confirmation, and synthetic or documented-sample evidence must be acknowledged as not market evidence. Research selection updates only the research pointer. Paper and live slots stay empty. The details and the conflicts with the longer registry spec are `docs/MODEL_REGISTRY_AND_STUDIO_SPEC.md` section 12.

M6 stores source candles separately from feature datasets, under `var/history`, as checksummed JSON. A refresh is a new id. M7 uses the saved Groww token and sends `GET /v1/historical/candles` for an explicit range, one request per 90-day chunk, with no retry. The raw response is written under `var/history/quarantine` and labeled `UNVERIFIED_PROVIDER`. Because the 14 Oct 2026 backtesting pages do not define the timestamp role or timezone, the import returns `CANDLE_BOUNDARY_UNVERIFIED` and stores no trusted candles. `NSE-NIFTY` and `BSE-SENSEX` are the documented index symbols. BANK NIFTY is not mapped. The fixture calendar stays non-authoritative. A rejected or quarantined report cannot be evaluated. Feature rows are built with the existing `ohlc-1` formulas only from a source dataset whose bar ends were supplied explicitly and whose origin is synthetic or a documented sample. That path is for tests of the pipeline. It is not verified market history.

### OptionContractQuote

`underlying`, `expiry`, `strike`, `option_type` (`CE` | `PE`), `broker_symbol`, `lot_size`, `tick_size`, `ltp`, `bid`, `ask`, `volume`, `oi`, `oi_change`, `iv`, `delta`, `gamma`, `theta`, `vega`, `quote_timestamp`, `source`. Missing greeks stay null. `broker_symbol` is the proposal alias of `trading_symbol` when both are present; `groww_symbol` is a separate Groww field. Selection identity is underlying, expiry, strike, and CE or PE.

### EvidenceItem

The common envelope for every agent, stored as JSON validated by Pydantic:

- `run_id`, `agent_name`, `schema_version`, `created_at`, `data_cutoff`, `market_status`
- `source_refs[]` with `source`, `url`, `retrieved_at`, `data_timestamp`, `status` (`PRIMARY` | `SECONDARY` | `DERIVED`)
- `quality` (`PASS` | `WARN` | `FAIL`) and `warnings[]`
- `facts[]`, `interpretations[]`, `bullish_evidence[]`, `bearish_evidence[]`
- `scenarios[]`, `invalidation_conditions[]`, `missing_data[]`
- `confidence.tier` (`LOW` | `MEDIUM` | `HIGH`) and `confidence.basis[]`
- `cursor_agent_id`, `cursor_run_id`, `model_id` when a Cursor agent produced the item; null for fact packs and fusion

Each list item carries `kind` (`CONFIRMED_FACT` | `REPORTED` | `INFERENCE` | `SCENARIO` | `MODEL_OUTPUT`) so the UI can separate them without rereading prose.

### NewsItem

`source_id`, `headline`, `url`, `publisher`, `published_at`, `event_at`, `fetched_at`, `status` (`CONFIRMED` | `REPORTED` | `UNVERIFIED` | `DENIED_OR_CORRECTED` | `STALE` | `RUMOUR`), `relevance`, `raw_excerpt` stored as data, never as instructions. `source_id` is null only when the item came from an enabled open-web corroboration pass.

### Forecast

`run_id`, `symbol`, `horizon`, `observation_timestamp`, `label_definition`, `threshold_T`, `model_name`, `model_version`, `promotion_state`, `data_cutoff`, `p_up`, `p_range`, `p_down`, `expected_return`, `interval_low`, `interval_high`, `data_quality`, `model_health`, `is_qualitative`, `calibration_snapshot`.

Validator: if `is_qualitative` is false, probabilities are in `[0, 1]` and sum to 1 within 0.01. If true, probability fields are null.

### FusionResult

`run_id`, `fusion_status` (`BASELINE_ONLY` | `APPROVED_FUSION`), `model_version`, `probabilities`, `baseline_probabilities`. `APPROVED_FUSION` is allowed only when that fusion version is `APPROVED_FOR_PAPER` in paper mode or `APPROVED_FOR_LIVE` in live mode. Otherwise the status is `BASELINE_ONLY` and the probabilities are the quantitative forecast. Component probabilities from Cursor agents are not stored, because those agents do not emit them.

### TradeProposal

`status` (`COMPLETE` | `INCOMPLETE`), `decision` (`BUY_CE` | `BUY_PE` | `NO_TRADE`), `underlying`, `horizon`, `model_version`, `broker_symbol`, `option_type`, `strike`, `expiry`, `quote_timestamp`, `premium`, `bid`, `ask`, `lot_size`, `quantity`, `premium_outlay`, `estimated_charges`, `expected_net`, `pricing_method`, `adverse_case`, `max_planned_risk`, `entry_trigger`, `invalidation`, `exit_plan`, `time_stop`, `counterargument`, `assumptions`, `risk_decision_id`.

`INCOMPLETE` means a mandatory buy field is missing: `decision` is `NO_TRADE` and the proposal cannot be submitted. A qualitative forecast is `NO_TRADE` with status `COMPLETE` and a recorded reason. `premium` is the ask. Chain LTP is not copied into it. Quantity is never "use all available funds". The field list and the pricing method are `docs/OPTIONS_EXPECTED_VALUE_SPEC.md`.

### RiskDecision

`proposal_id` or a synthetic id for a veto before a proposal exists, `result` (`PASS` | `VETO`), `gates[]` of `{name, pass, detail}`.

### OrderIntent and transitions

See section 13. Every transition is a row: `from_state`, `to_state`, `at`, `reason`, `broker_order_id`.

### AuditEvent

Append-only: `actor`, `action`, `entity`, `before`, `after`, `at`. Config edits, risk-limit edits, mode changes, kill switch, and order actions write here. Secrets never appear in `before` / `after`.

---

## 7. Configuration

Every behavior setting is configuration. The code ships defaults. The operator changes them in Settings, and each analysis run records the revision it used.

Two stores, and they do not overlap:

| Store | Holds | Example |
|---|---|---|
| Environment (`.env`) | Secrets and process bindings only | `DATABASE_URL`, `CURSOR_API_KEY`, `GROWW_API_TOKEN`, `SESSION_SECRET` |
| Postgres `config_revision` | Everything else | Risk limits, source list, freshness, fusion research gates, schedule, model id |

A config row stores the **name** of an env var (`secret_ref`), never the secret. Editing config is authenticated, validated by a Pydantic schema per section, and written as a new revision plus an `AuditEvent`. A bad payload is rejected. The previous revision stays readable. `AnalysisRun.config_revision` pins the revision, so a replay explains itself with the settings that were active.

On an empty database the worker loads `config/defaults.yaml` as revision 1. That file is the reviewed default. Later UI edits do not rewrite the file.

### Catalog

| Section | What the operator can set |
|---|---|
| `runtime` | Mode, live feature flag, unattended-order flag. Live still needs the UI confirmation in section 4. |
| `sources` | Every external feed: market, commodity, macro, flow, calendar, and news. Schema below. |
| `freshness` | Warn and block ages for index quotes, option quotes, crude, gold, USD/INR, news. |
| `context_book` | Standing symbols, and the situation registry (code, scope, driver list). |
| `horizons` | Enabled tasks. The label-threshold grid and the selection metric. Not a single hidden percentage. |
| `fusion` | Research gates the fusion artifact must beat. Not a table of hand-set agent weights. |
| `risk` | The policy in section 12. |
| `execution` | Slippage ticks, charge model, paper fill rule, quote age for entry. |
| `schedule` | Cadence, pre-open and post-close times, holiday calendar source. |
| `cursor` | Model id, per-agent on/off, repair-attempt count, open-web flags below. |
| `notify` | Which events alert, and which `Notifier` adapter is enabled. |

Disabled agents are skipped and the report says they were turned off. Fusion and the risk engine cannot be turned off.

### Data sources

One `DataSource` shape covers prices and articles. `connector` is a code adapter that already exists (`groww`, `rss`, `atom`, `http_json`, `fixture`). The UI cannot upload a connector. Adding a new site means adding a row that uses one of those connectors, or shipping a new adapter in a milestone.

| Field | Use |
|---|---|
| `id`, `name`, `enabled` | Identity and the on/off switch |
| `kind` | `market`, `commodity`, `macro`, `flow`, `calendar`, `news` |
| `connector`, `endpoint` | How to fetch |
| `secret_ref` | Env var name when the source needs a key |
| `symbols` or `topics` | What this row is allowed to return |
| `poll_seconds`, `timeout_seconds`, `max_items` | Load control |
| `priority` | Which source wins when two enabled sources disagree. The disagreement is still stored. |
| `last_success_at`, `last_error` | Shown in Settings. Not part of the edited document. |

A disabled source is not called. A run with no enabled source for a standing series records that series as missing.

### News and articles

`kind = news` adds:

| Field | Use |
|---|---|
| `tier` | `PRIMARY`, `SECONDARY`, or `CONTEXT`. The news agent may not mark a `CONTEXT` item as `CONFIRMED` on its own. |
| `language` | Skip items that do not match. |
| `include_keywords`, `exclude_keywords` | Optional filters applied before the agent sees the item. |
| `max_items` | Cap per poll. |

The fetch runs in Python, before the news agent. It reads every enabled news row, keeps title, URL, publisher, published time, fetch time, and a bounded excerpt, and dedupes by canonical URL. The agent classifies that set. It does not choose outlets.

`cursor.news_open_web` defaults to off. When off, the news agent has no `webSearch` tool. When the operator turns it on, web search is corroboration only: a page found that way is stored as `REPORTED` or `UNVERIFIED` and names the query. It does not become a configured source by itself. `cursor.macro_open_web` is the same switch for the macro agent, also off by default. Macro numbers still come from enabled `macro` sources.

The report states the sources actually checked, for example “Sources checked: RBI press releases, NSE circulars, configured wire RSS, as of 14 Oct 2026 09:20 IST.” If none are enabled, it says “No news sources are enabled in configuration as of {time}.” It does not say that there was no news.

Settings includes add, edit, enable, disable, and a test fetch for one source. The test shows a handful of titles and timestamps and does not start an analysis run.

---

## 8. Data providers

Each provider returns normalized models plus source metadata. The pipeline does not know HTTP details.

| Interface | Needs | If unavailable |
|---|---|---|
| `MarketDataProvider` | LTP, OHLC, candles, instrument master, option chain for the three indices | Critical for index prices and any proposal. Quality gate can block the run. |
| `BrokerReadProvider` | Funds/margin, positions, orders, connection health | Required for live and for showing account state. Paper uses the paper ledger instead. |
| `BrokerWriteProvider` | Place, modify, cancel, using official Groww APIs only | Absent unless mode is `LIVE_TRADING`. |
| `CommodityProvider` | Standing crude (Brent, and MCX Crude Oil Mini when specified) and gold. Extra contracts only if the active situation lists them. | A missing standing crude quote is a warning. The report may not state an oil transmission as fact. A proposal whose thesis depends on oil is vetoed. |
| `MacroProvider` | USD/INR on every run. Yields, DXY, and global indices as standing or situation drivers. Calendar. | Missing USD/INR lowers confidence. Other missing macro series are listed per driver. |
| `FlowProvider` | FII/DII with the official print date | Shown with that date. Never treated as live. |
| `NewsProvider` | Enabled news sources only. Items with publisher, URL, published time, fetch time, and theme tags. | “No news sources are enabled” when the list is empty. Otherwise “No material new development found in the sources checked as of {time}.” The report names those sources. |

### Context book

The pipeline resolves a **context book** before it fetches. The book is stored on the run and reused in replay, so an old session is not re-read with today’s geopolitics.

**Standing series, every run.** India imports most of its crude, so oil is a transmission channel on quiet days as well as on shock days. A quiet tape is still an observation: price, change, contract, and timestamp, plus a line that no verified supply shock was found in the sources checked.

| Series | Rule |
|---|---|
| NIFTY 50, SENSEX, BANK NIFTY, India VIX, option chains | Always |
| USD/INR | Always |
| Brent front month | Always. Store benchmark, contract month, price, change, and both timestamps. |
| MCX Crude Oil Mini front contract | Always requested. Used for levels and P&L only when month, expiry, lot size, and tick size are on the instrument master. |
| WTI | Second benchmark when the source provides it. It does not replace Brent. |
| Gold | Always. It is the cross-check when oil is moving on geopolitics rather than on a local inventory print. |

**Situation series, only while a regime is active.** A situation has `code`, `scope` (`DAY` | `WEEK` | `MONTH`), `active_from`, `active_until`, `reason`, `evidence_ids`, and `driver_codes`. Week and month windows are opened or extended by the operator. A `CONFIRMED` or `REPORTED` news item may open or refresh a **day** situation when its tags match a registry rule. `UNVERIFIED` and `RUMOUR` cannot add a series. The news agent may suggest a code from the verified items; the resolver accepts it only if that code is in the registry. The agent cannot add a symbol or a provider call.

Starting registry, editable without a code change:

| Code | Usual scope | Extra series | Report has to cover |
|---|---|---|---|
| `ENERGY_SUPPLY` | Day or week | Brent–WTI spread, MCX curve if listed | Supply versus demand, and whether equities moved with oil |
| `SHIPPING_DISRUPTION` | Day or week | Freight only if a licensed source exists | The route, and what confirmed reopening or ceasefire would invalidate |
| `RATES_LIQUIDITY` | Day or month | US yields, India 10Y if sourced | Bank Nifty and the discount-rate channel |
| `TRADE_TARIFF` | Week or month | DXY, affected sector indices | Which Nifty versus Sensex weights are exposed |
| `RISK_OFF` | Day | Global index futures | Whether the local market is catching up or diverging |
| `DOMESTIC_POLICY` | Day or week | India yields, affected sector | RBI, fiscal, or regulatory event; crude stays the standing series |

Overlapping situations fetch the union of their drivers once. When `active_until` passes, those extra pulls stop. A higher crude price is not treated as an automatic equity selloff, and a lower price is not treated as an automatic rally. `crude_cross_asset` reports the observed relationship over a stated window.

If a standing crude quote is missing, the index report still runs, crude is marked missing, and confidence drops. If an active situation’s primary extra series is missing, that driver is unavailable and the macro input to fusion stays qualitative. No price is filled in.

Groww is the first live implementation of `MarketDataProvider` and both broker interfaces, **after** the current official docs are read and the fields are mapped. This design does not invent endpoint paths, auth headers, or rate limits. Where the official API lacks Greeks, historical option-chain snapshots, or a global index, the feature stays off and the UI shows the gap.

Reads: timeout, bounded retries, exponential backoff, circuit breaker.
Writes: no blind retry. Timeout moves the intent to `UNKNOWN_REQUIRES_RECONCILIATION`.

Fixtures and a replay store implement the same interfaces so tests and `REPLAY` mode do not need credentials.

---

## 9. Analysis pipeline

Sequence for every run. Parallel groups run together only because they do not depend on each other.

```text
1. resolve the book already in force
     standing: indices, VIX, chains, Brent, MCX crude, WTI if sourced, gold, USD/INR
     plus day/week/month situations whose window is still open
2. fetch that book
3. data_quality  ---- FAIL on critical index fields --> BLOCKED, verdict INSUFFICIENT DATA
4. pin model_version_id for this run, or record that no approved model exists
5. if verified news matches a registry rule, open or refresh a DAY situation,
   fetch only the new series, and store the final book on the run
6. fact packs: M2 writes separate OHLC feature datasets for NIFTY, SENSEX, and BANK NIFTY. Breadth, chain metrics, session VWAP, and crude or FX returns are not in that feature set.
7. PATH A quant_forecast and PATH B LangGraph evidence graph, in parallel
     Path B nodes are the LangGraph spec. They include contrarian and aggregation.
     Neither path waits for the report.
8. forecast_fusion                           baseline copy, unless an approved fusion artifact exists
9. options expected value                    sizing first, then modelled net versus NO TRADE
10. risk_engine                              full entry veto; exits use the reduced gate list in the risk spec
11. report                                   Cursor agent, after the decision is fixed
12. persist forecast snapshot for outcome scoring
```

`index_technical` writes three evidence objects. SENSEX levels are computed from SENSEX candles. Copying NIFTY levels into the SENSEX section is a defect.

### Quality gate

Critical, and therefore blocking: missing or stale index LTP for a symbol under analysis, timestamp skew that makes the chain and the underlying incomparable, unreadable instrument identity on a contract that a proposal would use.

Warning, and therefore confidence reduction: stale or missing standing crude, stale VIX, missing USD/INR or gold, missing FII/DII, missing Greeks, single-source macro, news that is only `REPORTED`, an active situation whose extra series failed to load.

A proposal is vetoed when its thesis cites oil and the standing crude quote is missing or stale. An energy or shipping situation with no crude quote cannot support a directional oil claim.

Freshness defaults, configurable:

- Index and option quotes during the session: warn after 60 seconds; block a **proposal** after 15 seconds.
- Standing crude, gold, and USD/INR: warn after 15 minutes outside a shock, and after 5 minutes while an energy, shipping, or risk-off situation is active.
- News: keep both `published_at` and `event_at`. A syndicated repeat of an old event is `STALE`.
- FII/DII: latest official session date, labelled as that date.

Cross-source disagreements are stored side by side. The pipeline does not pick the convenient value.

### Fusion

Fusion follows `docs/FORECASTING_AND_BACKTEST_SPEC.md` section 7. Until a fusion artifact is promoted, the decision distribution is the quantitative forecast and `fusion_status` is `BASELINE_ONLY`. Specialist text is not converted into a probability. If the baseline is qualitative, the trade decision is `NO TRADE`.

### Report

The report agent fills the V6 template from stored objects after the trade decision exists. It may quote model probabilities and modelled expected net. It may not change them. Empty sections stay empty with a missing-data line.

---

## 10. Forecasting

The model predicts the distribution of the underlying for one task. It does not output a call or a put. Labels, leakage rules, walk-forward, and calibration are `docs/FORECASTING_AND_BACKTEST_SPEC.md`. Lifecycle, scope, and the studio are `docs/MODEL_REGISTRY_AND_STUDIO_SPEC.md`.

A forecast without an approved calibrated model is qualitative: probabilities are null and the trade decision is `NO TRADE`. States run from `REGISTERED` through `APPROVED_FOR_LIVE` as that registry spec defines. Research selection does not activate paper trading. An LLM cannot promote a version. Drift sets `model_health` to `DRIFT` and fails the model gate until a person reviews it. No family listed in the registry spec has been trained here.

---

## 11. Contract selection

Contract identity, the greek and Black-76 methods, costs, and the comparison with `NO TRADE` are `docs/OPTIONS_EXPECTED_VALUE_SPEC.md`.

The rank key is modelled expected net. There is no weighted score. A missing bid, ask, or premium rejects the candidate. If no eligible contract has expected net strictly above zero, the decision is `NO TRADE`. The options explanation agent may discuss the result and may not change it.

---

## 12. Risk engine

Gates, sizing, the daily-loss ledger, reservations, and the kill switch are `docs/RISK_AND_EXECUTION_SPEC.md`.

Shipped starting policy, not a result from this project's data: risk capital is an operator amount; 1% of that capital per trade; 2% daily-loss lockout with unrealized mark included; 20% cash buffer; at most two open positions and three new entries a session. If one lot costs more than the trade budget, the decision is `NO TRADE`. A stop is not a maximum-loss input. Two workers share one ledger row locked with `SELECT FOR UPDATE`.

The kill switch blocks new entries. An exit is a separate confirmed intent.

---

## 13. Order lifecycle

```text
PROPOSED
  -> RISK_APPROVED
  -> AWAITING_APPROVAL     (live, when confirmation is required)
  -> SUBMITTED
  -> OPEN / PENDING
  -> PARTIALLY_FILLED
  -> FILLED
  -> EXIT_PENDING
  -> CLOSED

Side states from any active state:
  REJECTED
  CANCELLED
  VETOED
  UNKNOWN_REQUIRES_RECONCILIATION
```

Illegal transitions throw and write an audit row. The worker holds a lease keyed by `intent_id` before it submits. Restart picks up `SUBMITTED` and `UNKNOWN_*` by reading the broker, not by sending the order again.

The broker reference stored on the intent must match Groww's documented `order_reference_id`: 8 to 20 characters, alphanumeric, at most two hyphens. A UUID is not sent. Lookup uses `get_order_status_by_reference`. Details and failure cases are `docs/RISK_AND_EXECUTION_SPEC.md` sections 4 and 5.

Paper mode uses the same states. It buys at the ask and sells at the bid minus the configured haircut. An extra tick penalty stays off until tick units are verified. The paper broker does not import Groww place, modify, or cancel.

On startup the worker reconciles open intents and positions before the scheduler may create a new entry.

---

## 14. Groww boundary

`docs/DATA_SOURCE_MATRIX.md` is the capability matrix. It was filled from the public Python SDK pages on 14 Oct 2026. Status values are `DOCUMENTED_UNTESTED`, `UNVERIFIED`, or `UNSUPPORTED`. Nothing is `VERIFIED` until an authenticated read-only call is recorded. The adapter calls only methods that appear in that matrix. A feature marked `UNVERIFIED` or `UNSUPPORTED` stays disabled. The UI shows that state.

Known gaps that block a live option order until closed: F&O product code, tick-size units, F&O behaviour of `get_order_status_by_reference`, and at least one pricing method the options spec currently allows. With the docs read on 14 Oct 2026, vendor-greek pricing is off until theta's time unit is known, and Black-76 is off until exercise style, a discount rate, IV scale, and a verified future are all present. The historical-candle replacement schema blocks training and option backtests. It does not by itself block a live order that uses a live quote.

Adapter rules:

- Tokens come from the environment. They are not logged, returned by the API, or written into Postgres.
- Instrument master is refreshed on a schedule and pinned on each proposal.
- Partial fills, rejects, cancels, and market-closed errors map to the state machine.
- Tests use recorded fixtures. One authenticated read-only smoke test is manual and documented.
- The adapter does not transfer, deposit, or withdraw funds.
- Sizing uses `option_buy_balance_available` and `get_order_margin_details` when those reads succeed. It does not treat `clear_cash` as the strategy budget.

Indian retail algo rules and Groww's API terms are a compliance checkpoint before `LIVE_TRADING`. This design does not decide that the API's existence makes unattended orders compliant.

---

## 15. Prompts and the Cursor call

`PromptContextBuilder` assembles one message per reasoning agent from:

- a versioned role prompt for that agent;
- regime tag (`TREND` | `RANGE` | `HIGH_VOL` | `EVENT`) computed by code from VIX and price structure;
- horizon;
- the fact pack and evidence ids this agent is allowed to see, inside a delimited data block;
- verified news items only, for the agents that need them;
- a read-only summary of risk policy;
- the evidence JSON schema the reply must match.

The builder does not interpolate news, broker payloads, or user text into the role section. Retrieved text is untrusted. Delimiter collisions are stripped, length is capped, and instruction-shaped phrases in the data block are logged. They cannot change limits, mode, or orders.

The worker then calls `AsyncAgent.prompt` with that message, `local` set, the per-agent tool allowlist from section 5.1, and the custom read tools. Stored with the evidence row: template id and version, context ids, source ids, prompt hash, `cursor_agent_id`, `cursor_run_id`, and `model_id`.

Prompt Studio edits role templates and compares them on replay. A template reaches production only through an explicit promotion. Rollback restores the previous version. An in-flight run keeps the prompt hash it started with. Replay uses stored evidence unless the operator reruns reasoning.

Research agents have no broker write tool, no shell, and no SQL tool. The execution service accepts a typed intent, not the report text.

---

## 16. HTTP API

All routes except `GET /health` require the operator session. State-changing routes use the session cookie and a CSRF token. CORS allows only the web origin.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Process up, database up, mode, kill-switch state |
| GET | `/api/market/snapshot` | Latest LTPs and quality |
| GET | `/api/market/history` | Candles for a symbol and interval |
| POST | `/api/features/datasets` | Build an M2 OHLC dataset for one configured provider and instrument |
| GET | `/api/features/datasets/compare` | Compare two stored dataset manifests |
| GET | `/api/features/datasets/{dataset_id}` | Read one stored dataset after checksum verification |
| POST | `/api/walk-forward` | Run binary-1 expanding-window evaluation for one configured provider |
| GET | `/api/walk-forward/{walkforward_id}` | Read one stored walk-forward artifact after checksum verification |
| GET | `/api/options/chain` | Normalized chain for underlying + expiry |
| POST | `/api/analysis/run` | Enqueue a run |
| GET | `/api/analysis/{run_id}` | Run, evidence, verdict, report |
| GET | `/api/forecasts/latest` | Latest numeric or qualitative forecasts |
| GET | `/api/trade-proposals` | Proposals and their gate results |
| POST | `/api/trade-proposals/{id}/paper-submit` | Paper transition only; server checks mode |
| POST | `/api/trade-proposals/{id}/approve-live` | Live transition; server rechecks mode, flag, and risk |
| GET | `/api/broker/status` | Connection, permissions, last success |
| GET | `/api/broker/funds` | Funds/margin and retrieved_at |
| GET | `/api/broker/positions` | Broker and local, including mismatches |
| GET | `/api/broker/orders` | Order book |
| POST | `/api/broker/orders/{id}/cancel` | Supported cancel, confirmed |
| GET | `/api/config` | Active revision and every section |
| GET | `/api/config/revisions/{rev}` | A past revision, read only |
| PUT | `/api/config/{section}` | Validate, audit, and store a new revision of that section |
| GET | `/api/config/sources` | Enabled and disabled feeds, including news |
| POST | `/api/config/sources` | Add a source row for an existing connector |
| PATCH | `/api/config/sources/{id}` | Edit, enable, or disable one source |
| POST | `/api/config/sources/{id}/test` | Fetch a few items. Does not start an analysis run. |
| GET | `/api/risk/status` | Policy, lockout, kill switch |
| POST | `/api/risk/kill-switch` | Set or clear; clear requires a confirmation field |
| GET | `/api/agents/runs` | Agent timings, quality, errors |
| GET | `/api/prompts` | Templates and versions |
| POST | `/api/prompts/{id}/evaluate` | Replay comparison |
| GET | `/api/models` | Registry rows for the studio. Empty until a model is registered. |
| GET | `/api/models/{model_id}` | Version history and metadata. Unknown id is `UNKNOWN_MODEL`. |
| GET | `/api/models/compare` | Stored metrics only. Missing reports are `NOT_EVALUATED`. |
| POST | `/api/models/research-selection` | Research pointer only. Does not change the paper slot. |
| POST | `/api/models/paper-activation` | Paper slot for an approved scope. Idempotent. |
| POST | `/api/models/paper-rollback` | Previous approved version for that scope. |
| GET | `/api/models/activations` | Selection, activation, and rollback history. |
| GET | `/api/models/evaluation` | Walk-forward report |
| GET | `/api/workflows/{run_id}` | LangGraph thread status, node errors, and checkpoint id. |
| GET | `/api/workflows/{run_id}/evidence` | Specialist evidence for that run. |
| GET | `/api/options/valuations` | Stored valuation rows, or `UNAVAILABLE` when no method is enabled. |
| GET | `/api/paper/orders` | Paper orders, fills, and positions. |
| GET | `/api/audit` | Audit stream, filterable |

Request and response fields for the model routes are `docs/MODEL_REGISTRY_AND_STUDIO_SPEC.md` section 9. There is no live-activation route.

`POST /api/features/datasets` is implemented. The body is `{instrument, provider, as_of}`. `provider` defaults to `synthetic` and must be a configured name, not a URL or file path. `as_of`, when present, is timezone-aware. The route requires the session and the CSRF header. A valid build returns the dataset artifact with `forecast_ready: false`. Quality failures return 422 and do not write a file. Groww candle history returns 501 `CANDLE_BOUNDARY_UNVERIFIED`. Unknown dataset ids return 404. A checksum mismatch returns 422. `GET` compare and read require the session.

`POST /api/walk-forward` is implemented for the research harness. The body is `{instrument, provider, initial_train_size, validation_size, test_size, step_size, min_train, min_validation, min_test}`. Extra fields, including a file path, are rejected. `provider` must be a configured name. The route requires the session and the CSRF header. A short synthetic fixture returns 422 `INSUFFICIENT_DATA` and writes no walk-forward artifact. Groww history returns 501. A stored report is read with `GET /api/walk-forward/{walkforward_id}` after the checksum check. The response keeps `forecast_ready`, `paper_approved`, `live_approved`, and `real_market_data_verified` false.

`GET /api/history/capabilities` and `GET /api/history/datasets` require a session. `POST /api/history/imports` requires the session and the CSRF header. The body is `{instrument, interval, start, end}`. Extra fields are rejected. Without Groww credentials the route returns 422 `NOT_CONFIGURED` and sends no request. With credentials, a NIFTY or SENSEX range sends the documented candle GET, quarantines the body, and returns 422 `CANDLE_BOUNDARY_UNVERIFIED` with an empty trusted candle list. BANK NIFTY returns `UNMAPPED_INSTRUMENT`. The history page separates request, quarantine, numeric quality, timestamp verification, and forecast eligibility. `GET /api/history/capabilities` lists each unanswered timestamp confirmation. `GET /api/history/quarantine` reads the stored raw response and reports known and unknown timestamp properties. It does not rewrite the quarantine file and it does not create trusted candles. The page does not render fabricated candles.

`GET /api/integrations` requires a session and returns presence flags, labels, the OpenAI model id, and the last connection-test result. It does not return secrets. `PUT /api/integrations/groww` and `PUT /api/integrations/openai` replace stored credentials. `POST` clear, enable, and test routes require the session and the CSRF header. Groww methods are `access_token`, `api_key_secret`, and `totp`, matching the curl introduction page. The Groww test is one `GET https://api.groww.in/v1/margins/detail/user` when a saved access token has an unexpired expiry. An offset-less expiry is Asia/Kolkata. A past expiry does not start a token request. `POST https://api.groww.in/v1/token/api/access` runs only when no access token and no expiry are stored. The OpenAI test is `GET https://api.openai.com/v1/models/{model}` and runs only when the integration is enabled. Callers cannot supply a URL. Secrets are Fernet ciphertext in `integration_credentials.ciphertext`. The key is `INTEGRATIONS_SECRET_KEY` in the environment. A missing key rejects saves with `SECRET_KEY_UNCONFIGURED`. A failed test is a failed test; saving credentials leaves `last_test_ok` null.

The research registry routes in section 16 are implemented as described in `docs/MODEL_REGISTRY_AND_STUDIO_SPEC.md` section 12. `GET /api/models`, `GET /api/models/{model_id}`, `GET /api/models/{model_id}/versions/{version}`, `GET /api/models/compare`, `GET /api/models/activations`, `GET /api/experiments`, `GET /api/forecasts`, `POST /api/models`, `POST /api/models/registrations`, `POST /api/models/research-selection`, and the version transition route require the operator session. Writes also require the CSRF header. Paper activation and paper rollback return `MODEL_NOT_APPROVED` and do not change a slot. There is no live-activation route. `GET /api/forecasts` returns an empty list. The other analysis, broker, and workflow routes in the table above are not implemented.

`approve-live` calls `RiskEngine` again at submit time. A pass from minutes earlier is not enough. `PUT /api/risk/policy` writes the `risk` section of the same revision store. It is not a second copy of the limits.

Errors use a single shape: `{code, message, detail}`. Codes include `INSUFFICIENT_DATA`, `RISK_VETO`, `MODE_FORBIDDEN`, `RECONCILIATION_REQUIRED`.

---

## 17. UI

Desktop-first, and usable on a smaller laptop width. Every page shows mode, market status, and data cutoff. Paper and live use different banner treatments. Live cannot look like paper.

Labels distinguish verified facts, inferences, model forecasts, modelled scenario estimates, live broker rows, and paper fills.

1. **Dashboard** — NIFTY, SENSEX, and BANK NIFTY with LTP, change, high/low, time, and quality. Market status. The pinned model version, or `NOT_AVAILABLE` when no paper model is active. Forecast probabilities only from a stored forecast row; otherwise a qualitative banner. Separate labels for forecast, calibration, option value, trade eligibility, and order status. A bullish class is not a call order. The verdict from the table in section 1, and the trade decision `BUY_CE`, `BUY_PE`, or `NO_TRADE`. Contract, ask, and bid only when a buy decision exists. Modelled expected net only when a pricing method is enabled; otherwise the panel says the estimate is unavailable. Graph status for the latest run. Brent, MCX crude, USD/INR, and gold, or an explicit missing state. Active situation chips. VIX and breadth. Candles. News with verification status. Paper positions and P&L. Groww funds only when a read-only connection has succeeded. Risk budget remaining and daily-loss state. Data-quality warnings, agent disagreements, and the strongest opposing case.
2. **Forecast Model Studio** — implemented at `/studio` as a research page. It lists registered versions, saved M3 holdout and M4 walk-forward artifacts, compatible comparisons, model history, and a confirmed research selection. Missing values render as `NOT_AVAILABLE` or `NOT_EVALUATED`. Paper activation and live approval are not controls on this page. A score is not a forecast and is not a trade.
3. **V6 Report** — template sections, evidence kind, missing data, contrarian block, invalidation, graph errors.
3. **Options Scanner** — filters, chain, bid/ask, stale and illiquid flags, modelled payoff only when the options spec allows a method.
4. **Trade Proposal** — the proposal fields from section 6, gate list, paper submit, or live confirm modal. No prefilled maximum quantity. `INCOMPLETE` has no submit button.
5. **Positions and Orders** — broker versus local, fills, charges, open P&L, closed P&L, and fees.
6. **Risk** — policy, lockout, kill switch. Releasing the lockout or the kill switch requires a typed confirmation and an audit row.
7. **Agent Monitor** — graph node status, timing, quality, abstentions, conflicts, missing inputs, Cursor ids, model id, redacted prompt.
8. **Prompt Studio** — versions, replay comparison, promote, rollback.
9. **Backtest and Model Evaluation** — walk-forward report, baselines, reliability, regime splits, and an explicit refusal when option history is unverified. Research selection and paper activation follow the registry spec. Directional accuracy alone cannot approve a model.
10. **Groww and Settings** — one screen per config section. News sources can be added, disabled, and test-fetched. Connection status, last sync, and the capability matrix. Secrets are never shown.
11. **Audit Log** — config edits, promotions, mode changes, kill switch, lockout resets, and order transitions.

The mode banner stays visible on every page. An Enable Live Trading control is not wired to an order route in this design.

---

## 18. Scheduler and failure behavior

The worker runs four loops. Each refuses to start an entry when its own health check is failing.

| Loop | When | Failure |
|---|---|---|
| Pre-market and post-close report | Configured clock, if the calendar says it is a session day | Write the report with missing sections. Do not carry yesterday's quote forward as live. |
| Analysis | Configured cadence during the session (shipped example 5 minutes), and again when a new completed candle arrives for an enabled task | Stale critical quotes block proposals. |
| Position monitor | Configured cadence while a position or working order exists | Stale quotes or a broker read failure block new entries and do not mark a stop filled. |
| Outcome and drift | After a forecast endpoint, and on the configured drift schedule | A forecast inserted after its endpoint is not scored. Drift fails the model gate. |

The holiday calendar source is configured. If it is missing, the scheduler does not guess that today is a trading day. Entries stay blocked and the UI says the calendar is unverified.

Rate limits in `docs/DATA_SOURCE_MATRIX.md` are enforced in the provider clients. One lease row prevents two workers from submitting. The risk ledger prevents two workers from reserving the same budget. A dead worker's expired lease is taken over only after reconciliation. Notifications use a `Notifier` interface that logs until a channel is configured.

---

## 19. Security

- `.env` is gitignored. `.env.example` has empty placeholders, including `CURSOR_API_KEY`.
- Logs, prompts, and the audit table pass through a redactor for tokens, cookies, authorization headers, and the Cursor key.
- The API requires the operator session even on localhost.
- Risk policy and mode live in the config revision, not in a Cursor reply.
- A configured source URL is fetched only after SSRF checks: `http` or `https` only, no credentials in the URL, DNS answers must not be loopback, link-local, or private, redirects are checked again, and the test-fetch uses the same guard.
- Dependencies are pinned when a milestone adds them. `cursor-sdk` and `growwapi` are still not installed; no reviewed package version was recorded for them. `langgraph` `1.2.15` and `langgraph-checkpoint-postgres` `3.1.3` are the versions read on 14 Oct 2026 for the future LangGraph milestone. They are not installed yet.

---

## 20. Build milestones

The milestone table, dependencies, and acceptance tests are `docs/IMPLEMENTATION_PLAN.md`. This section stays a summary so the two files are updated together.

M0, M1, M2, M3, M4, M5, and the M6 historical boundary are implemented. M4 is expanding-window walk-forward for the experimental binary target. M5 is the research registry and Forecast Model Studio. M6 does not retrieve verified historical candles. It does not approve paper or live trading. LangGraph, baseline fusion, options value, and paper trading are not started. M12 is authenticated broker reads. M13 is a live-readiness review with orders still disabled. M14 is live orders and stays off until the API and compliance questions in `docs/OPEN_QUESTIONS.md` are closed and the empirical gates in the forecasting spec have evidence. Finishing an earlier milestone does not authorize M14. The table is `docs/IMPLEMENTATION_PLAN.md`.

---

## 21. Tests

The case list is the acceptance-test matrix in `docs/IMPLEMENTATION_PLAN.md`. Any numeric pass bar used there is a configured research gate. It is not labelled as an empirically proven threshold.

---

## 22. Acceptance

Paper mode matches this design when the M0 through M11 gates in the implementation plan pass, including an explicit `NO TRADE` and an `INCOMPLETE` proposal that cannot be submitted. M0, M1, M2, and M3 are the milestones with code in the repository. M3 does not make a forecast ready and does not approve a model.

Live mode is not accepted by this document. It also requires the matrix rows it uses to be `VERIFIED` (called `VERIFIED_BY_TEST` in the matrix vocabulary note), an `APPROVED_FOR_LIVE` model for that scope, the M13 readiness review, and the compliance questions closed.

The system is not profitable because this design exists. No backtest has been run.

---

## 23. Open points

User decisions, API checks, historical data, empirical work, and compliance review are split in `docs/OPEN_QUESTIONS.md`. The change log for this review is `docs/DESIGN_REVIEW_RESOLUTIONS.md`.
