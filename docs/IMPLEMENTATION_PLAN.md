# Implementation plan

**Status:** M0 through M5 are implemented. M6 adds historical-candle validation and a blocked Groww import. It did not retrieve market candles. M1 serves a labeled synthetic fixture, not live Groww data. M2 versions OHLC feature datasets. M3 fits binary baselines on one chronological holdout. M4 runs expanding-window walk-forward on that same target. M5 registers those artifacts and opens a research-only studio. It does not approve a model for paper or live trading. LangGraph, options, paper, and live trading are not implemented. Live trading is still blocked by `docs/OPEN_QUESTIONS.md`.
**Parent:** `docs/DESIGN.md`

Each milestone leaves the app runnable. A later milestone does not stub an earlier integration and call it done. Research gates referenced here are operator settings. They are not empirically proven cutoffs.

The sequence below keeps M0 as the shell that is already in the repository. It then follows data, features, baselines, the registry, a read-only studio, the LangGraph evidence graph, fusion, options, risk, and paper trading before any broker write. That is why broker read-only verification is M12 rather than an early milestone, and why live orders are M14 rather than the next coding step after paper. Paper trading must not depend on an unverified order API.

---

## Milestones

| ID | Delivers | Depends on | Gate |
|---|---|---|---|
| M0 | Compose, health, login, config revisions from `config/defaults.yaml`, Settings shell, audit log, SSRF guard on source URLs. Implemented. | — | An invalid config write is rejected. A disabled news source is not fetched. A private or link-local URL is refused. Paper mode does not call the live order function. |
| M1 | Provider interfaces, synthetic quiet-day fixture, quote and candle validation, snapshot and history APIs, dashboard cards. Implemented. Groww is a documented-sample mapper only. | M0 | A quiet-day fixture still has crude fields. NIFTY, SENSEX, and BANK NIFTY render with timestamps. Missing crude is a warning, not a fabricated price. Stale index LTP blocks a proposal. |
| M2 | Feature set `ohlc-1`, dataset manifests, and separate packs for the three indices. Implemented. No model is trained. `forecast_ready` stays false. | M1 | Identical candles and configuration produce the same dataset id. A later close does not change an earlier row. Untouched test dates are stored as null before any fit. |
| M3 | Majority class, last-return sign, and L2 logistic regression for target `binary-1`, plus one embargoed chronological holdout. Implemented. Not registered and not approved. `forecast_ready` stays false. | M2 | Probabilities used for log loss and Brier stay in `[0, 1]`. The split sorts by time and does not shuffle. A one-class or non-converged logistic fit returns a structured failure. No model is approved for paper or live. |
| M4 | Expanding-window walk-forward for `binary-1`, evaluation version `m4-expanding-1`. Reuses the three M3 models. Implemented. Not a registry and not an approval. `forecast_ready` stays false. | M3 | Training rows precede validation, validation precedes test, and the one-bar embargo is applied at both boundaries. A short fold is recorded and is not resized. Test metrics do not choose the model. |
| M5 | Research model registry and Forecast Model Studio for the three binary models. Implemented. Paper and live activation are refused. | M3, M4 | Unknown families and unsupported scopes are rejected. A research selection does not create a paper slot. Synthetic results cannot be marked as verified market data. |
| M6 | Historical candle boundary for NIFTY and SENSEX M15. Documented Groww `get_historical_candles` fields are recorded. Import validates the range and stops before a network call because the timestamp role and timezone are unverified. Source datasets are checksummed and separate from feature datasets. `forecast_ready` and `real_market_data_verified` stay false. LangGraph is not this milestone and is not implemented. | M2, M3, M4 | A blocked import stores no candles. A rejected quality report cannot be evaluated. A verified-history evaluation is refused. BANK NIFTY is not aliased to NIFTY. |
| M7 | Forecast and evidence records joined per run. Fusion service in `BASELINE_ONLY` mode. | M3, M6 | Hand-set weights cannot pass the model gate. Fusion failure does not invent a forecast. A qualitative baseline yields `NO TRADE`. |
| M8 | Deterministic options expected-value engine and chain fixtures. Null greeks stay null. | M1, M7 | A chain LTP without bid and ask cannot become a proposal premium. If the method is disabled, the decision is `NO TRADE` or the proposal is `INCOMPLETE`. A negative expected net loses to `NO TRADE`. |
| M9 | Risk ledger, paper broker, proposal page, state machine | M8 | Daily-loss lockout survives restart. Two concurrent approvals cannot spend the same remainder. Paper submit does not import Groww write functions. `lot_count < 1` is `NO TRADE`. |
| M10 | Paper fills with the cost and slippage model, scheduler, lease, and reconciliation for paper state | M9 | A dead worker does not double-submit a paper intent. Stale quotes block entries. Exits still run during an entry lockout. Holiday config skips the session loop. |
| M11 | Walk-forward report, calibration view, paper activation, and rollback for models and prompts. Forward paper evaluation starts here. | M5, M7, M10 | A model cannot reach `APPROVED_FOR_PAPER` without the untouched-test report for that scope. Activation does not change an in-flight run. Prompt promotion does not change an in-flight run. |
| M12 | Groww read-only adapter and authenticated verification | M0, matrix | Only methods listed in `docs/DATA_SOURCE_MATRIX.md` are called. Each exercised method is marked `VERIFIED` or left `UNVERIFIED` with the error. No new field is invented. |
| M13 | Live-readiness review: flags, runbooks, and the disabled live control | M11, M12, and the open API questions that M14 names | The live control does not call an order function. The page states which checks are still open. |
| M14 | Live place, modify, cancel | M9, M12, M13, empirical paper evidence, and the API and compliance questions | Feature flags default off. Timeout becomes `UNKNOWN_REQUIRES_RECONCILIATION`. This milestone stops unless all of the following are `VERIFIED`: the F&O product code, tick-size units, `get_order_status_by_reference` for F&O, and at least one pricing method the options spec currently allows. It also stops without an `APPROVED_FOR_LIVE` model for the scope being traded and without the compliance questions closed. The historical-candle schema is not an M14 gate. It blocks training and option backtests only. |

M14 is specified so it can be built later. It is not authorized by finishing M13.

M4 in this table is walk-forward evaluation. M5 is the research registry and studio. M6 is the historical-data boundary. Genuine historical ingestion is blocked on the Groww candle-timestamp contract. API integration settings store Groww and OpenAI credentials and run read-only connection tests. M7 sends `GET /v1/historical/candles` for an explicit NIFTY M15 range and quarantines the raw response. M7.1 re-read the backtesting pages, changelog, and annexure on 14 Oct 2026 and left the timestamp timezone, bar boundary, request inclusivity, partial-candle rule, and session-boundary rule unverified. The quarantine file is unchanged and is not a trusted dataset. A support request is saved in `docs/GROWW_CANDLE_TIMESTAMP_SUPPORT_REQUEST.md` and has not been answered. M7.2 found no support reply in the repository. Timezone, bar boundary, request inclusivity, session open, session close, partial candles, and index timestamp behavior each remain unanswered, so no mapping was added. `forecast_ready`, `paper_approved`, `live_approved`, and `real_market_data_verified` stay false. M8 adds a LangGraph evidence report. It does not approve a forecast, paper trading, or live trading. M8.1 checks node isolation and a bounded OpenAI 429 retry in mocked tests. A node exception is recorded and the report stays `INSUFFICIENT_DATA` or `FAILED`; it is not a successful analysis. Commentary retries only a numeric `Retry-After` of at most 2 seconds, once. A later inference-hardening pass runs that completion only when commentary is explicitly requested and the report has supplied evidence; the default request does not call OpenAI. News, macro, global-index, and options providers are still absent. Postgres checkpointing, Cursor specialist agents, and fusion probabilities remain deferred. The paper-broker milestone in this table was not started. A verified-history check found no documented 15-minute NIFTY timestamp contract, left the Groww quarantine unchanged, and did not run M2, M3, or M4 on market history. A later source read of Upstox, Kite Connect, Angel One, DhanHQ, and NSE products also left the gate `BLOCKED`. A contract checklist verified the Groww index symbol, 15-minute interval, coverage statement, and candle schema, and left timezone, bar boundary, request bounds, session candles, partial candles, rate limit, and licence unverified. No provider was contacted and no new read was sent. The plan's later live-review milestone was not started. A local read of the stored quarantine checked record checksums, 15-minute spacing, and OHLC without a new provider request. The summary record does not store the candle array. Timezone and bar boundary remain unverified, so no trusted dataset was created. Option valuation remains the plan's M8 and is not complete. A chain schema and a labelled synthetic NIFTY fixture validate quotes. Contract selection can return one matching row and still decides `NO_TRADE`. The Black-76 and vendor-Greek formulas can be checked with explicit test inputs, and both production methods stay unavailable. Expected net is the specified probability-weighted sum of scenario nets, calculated only from explicit scenario nets. A candidate expected net stays null: the stored forecast is binary-1 and has no frozen class-conditional returns, no charge schedule is configured, and neither pricing method is enabled. Research ranking can order explicit test rows and still returns `NO_TRADE`. The research proposal contract records the quote, modelled value, forecast, scenarios, charges, expected net, identity, and risk gates separately. Under the current inputs the status is `INCOMPLETE`, except a qualitative forecast, which is `COMPLETE`. The decision is `NO_TRADE`, the proposal is not executable, and it does not call the order function. M9 adds a local risk ledger and gate evaluation. Reserved cash on a session row matches the applied reserve and release events for that session date, a release cannot spend another intent's reservation, and a lockout survives a new database session. Session P&L stays null while any of its four inputs is missing. Gates that lack a calendar, master, tick unit, model approval, funds requirement, charge schedule, expected net, or reconciliation tolerance do not pass. The paper state machine records `PROPOSED` and `VETOED` only. It does not activate paper trading, apply a fill, serve the proposal page, or import a broker write function. An M8 proposal does not become an order. A local audit found null risk capital, no charge schedule, no authoritative calendar, no instrument master, and no paper or live model slot. A stale bid can now be marked as a full premium loss without a live price, and a release is ordered against the outstanding reservation. M9 is not complete. A later check of the current Groww candle page distinguished it from the deprecated range endpoint. No one-minute request was sent because the saved Groww integration is disabled. Its stored expiry has no offset and is read as 6:00 AM IST. A past expiry is not refreshed. A separate one-minute diagnostic exists and was not executed. The quarantined 15-minute files were not changed and were not marked trusted. A later one-minute NSE-NIFTY read for 13 Oct 2026 09:15–09:45 returned HTTP 200 and 31 candles. Structural checks passed: consecutive timestamps are 60 seconds apart, OHLC relationships hold, and volume and open interest are null. Two complete windows match the stored 15-minute OHLC when each 15-minute timestamp is read as the first minute of its window. That match is supporting evidence, not official confirmation of candle-start semantics. Timezone, bar boundary, request inclusivity, session candles, and incomplete candles remain unresolved. Both records stay quarantined as `UNVERIFIED_PROVIDER`. Feature datasets carry a sealed lineage record. Training and walk-forward evaluation require that record to match the source candles and the dataset checksum. A caller eligibility flag is not accepted in its place. Quarantine files cannot be parents. Explicit synthetic research data remains usable and is not verified market history. M10 adds an explicit paper-simulation route. It runs the existing risk gates, records a veto, and does not apply a fill or call a broker while those gates fail closed. An offline accounting replay can check explicit fills in memory and is not called by that route. The ledger still rejects a fill event. `paper_approved` stays false. M10 is not complete. The simulation, refusal boundary, reservation ledger, and in-memory accounting are in place. Operational writers share lock namespace `841105` before the per-intent lock. A fill is still not persisted, and paper trading is not activated. Read-only routes now replay a stored simulation, return an empty-contract options proposal as NO_TRADE, and describe the ledger rules without posting an event. The research desk shows those responses on Dashboard, Forecasts, Options, Paper, and Risk, including loading, empty, error, and retry states. Null amounts stay unset. Quarantine stays labelled quarantined. Browser tests mock those responses and do not call a broker. An append-only `paper_account_events` journal can store an explicit fill, partial fill, cancel, reject, charge assessment, charge correction, or reconciliation discrepancy and the replay effect of that event. The row is constrained so it cannot be marked applied to the ledger or broker-confirmed. It does not change `risk_sessions`. A partial fill's remaining quantity is `order_quantity - filled_quantity` when both are explicit. The rupee amount to release from a reservation on that partial fill is still undefined. This is not production-ready. M10 remains incomplete.

A later M10 pass keeps that boundary. Replay order is the persisted `occurred_at` instant, then `event_id`. An older row's stored effect is not rewritten when a later event is inserted. `GET /api/accounting/projection` replays the committed journal and labels cash, charges, open premium, positions, and P&L as known, unknown, or unavailable. It does not post an event, take the operational lock, or read a broker. `classify_reservation_release` can compute an unfilled quantity, and its rupee release stays `RULE_UNDEFINED` with `release_inr` null. A future fill that updates the journal and the operational ledger must be one transaction: lock namespace `841105` first, then `841104` when an intent is named, then the journal lock `841106`, then idempotency validation, the journal insert, the in-transaction projection, the ledger application, the reservation adjustment, and the audit row, followed by one commit or a full rollback. The ledger application and the reservation adjustment are not implemented. M10 remains incomplete.

The product path from market data to a decision is now one read. `GET /api/research/decision` joins the local synthetic snapshot, the model registry, saved holdout and walk-forward ids, the empty options proposal, and the research blockers. The Options page shows that record for NIFTY. An index last price stays an index observation. It is not copied into the option premium or the expected net. Registered model flags supplied by a caller are not treated as approval. Missing contract, quote, charge, and forecast inputs stay missing, and the decision is `NO_TRADE`. The route uses the synthetic provider only. Quarantine is not promoted. Paper trading, forecast readiness, paper approval, live approval, verified market data, and live trading stay false. M8 and M9 remain partial because there is still no verified option quote, charge schedule, or risk capital. M10 remains incomplete. M11 was not started.

Files: `apps/api/app/research/decision.py`, `apps/api/app/main.py`, `apps/api/tests/test_research_decision.py`, `apps/api/tests/test_research_status.py`, `apps/web/app/options/page.js`, `apps/web/e2e/api.js`, `apps/web/e2e/desk.spec.js`.

The workflow now supported is: sign in, open Options, read the decision record. It cites the synthetic NIFTY snapshot and any saved model or experiment ids, lists the missing contract, quote, cost, forecast, and risk inputs, and returns `NO_TRADE` with expected net null. The separate empty-contract proposal remains on the same page. This does not submit an order.

Tests: `cd apps/api && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ../../.venv/bin/pytest -q --tb=line` — 300 passed, 0 failed, 0 skipped, 1 existing Starlette warning. `cd apps/web && npm test` — 10 passed, 0 failed. `cd apps/web && npx playwright test --reporter=line` — 13 passed, 0 failed. `cd apps/web && npm run build` — succeeded, 16 static routes. The research-read regression included `GET /api/research/decision?underlying=NIFTY` and left `risk_events`, `FILL` rows, `paper_transitions`, and `risk_sessions` at `(0, 0, 0, 0)`.

Still blocked: verified market candles and the Groww timestamp contract, a charge schedule, risk capital, an authoritative calendar, tick and lot evidence, an approved forecast with scenario returns, a broker snapshot, operational paper fills, and paper activation. The next implementation task is an options candidate that accepts an explicit local contract fixture and reports each supplied identity field beside the inputs that are still missing, without calculating a premium from the index last price or enabling a trade.

That candidate workflow is now in place. `POST /api/options/candidates` accepts one `EXPLICIT_LOCAL_FIXTURE`. Supplied identity fields are recorded and omitted fields stay missing. Invalid values and conflicting symbols are refused and are not rewritten. Exchange, segment, lot size, tick size, and expiry stay unverified. A supplied bid or ask is unverified quote evidence, and the option premium stays null. The synthetic index last price is cited separately and is not copied into the premium. Charges, an approved forecast, scenario returns, risk capital, broker funds, reconciliation, and execution stay unavailable. The decision remains `NO_TRADE`, expected net and expected return stay null, and the fixture does not establish that the contract is listed or tradable. The Options page shows an empty state until the fixture is submitted, then the identity, evidence, and blockers. It also shows a validation error for a refused fixture. M8 and M9 remain partial. M10 remains incomplete. M11 was not started.

Files: `apps/api/app/options/candidate.py`, `apps/api/app/main.py`, `apps/api/tests/test_option_candidate.py`, `apps/api/tests/test_research_status.py`, `apps/web/app/options/page.js`, `apps/web/e2e/api.js`, `apps/web/e2e/desk.spec.js`.

Tests: `cd apps/api && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ../../.venv/bin/pytest -q --tb=line` — 304 passed, 0 failed, 0 skipped, 1 existing Starlette warning. The research-read regression posted one NIFTY candidate and left `risk_events`, `FILL` rows, `paper_transitions`, and `risk_sessions` at `(0, 0, 0, 0)`. `cd apps/web && npm test` — 10 passed, 0 failed. `cd apps/web && npx playwright test --reporter=line` — 15 passed, 0 failed. `cd apps/web && npm run build` — succeeded, 16 static routes.

Still blocked: verified contract-master identity, a verified option quote, a charge schedule, risk capital, an authoritative calendar, lot and tick verification, an approved forecast with scenario returns, a broker snapshot, operational paper fills, and paper activation. The next implementation task is to show a saved local candidate beside the decision record after a refresh, without storing it as a tradable position or an order.

A confirmed Groww read requests only the documented NIFTY cash quote and the documented BSE_SENSEX last price, reuses a stored unexpired token, and does not exchange a token or request candles. The prices are stored as unverified provider data and are included in the next market analysis. The candle timestamp contract remains unverified. `real_market_data_verified` stays false.

The V6 news, geopolitical, macro, market-impact, and contrarian agents run inside the existing analysis report. They deduplicate supplied items, keep conflicting directions, and label freshness and data class. A confirmed refresh reads five fixed public market RSS feeds and stores the headlines for that news agent. It does not invent prices or emit probabilities. A synthetic print cannot confirm a narrative. The decision stays NO_TRADE, the risk veto stays in place, and outcome calibration stays empty. Breadth, sectors, FII/DII, yields, and a verified option chain remain missing.

The operator account is stored. Migration `005_operator_accounts` adds one `operator_accounts` row with a salted PBKDF2 password hash, display name, timezone, and last login. The desk has a sign-in page, a one-time signup page that closes once the row exists, a profile page that edits the display name, timezone, and password, and an API-keys page that writes encrypted `integration_credentials`. Login prefers the stored account and falls back to `OPERATOR_PASSWORD` only while no row exists. Logout clears the cookie and keeps the account and saved keys. The migration is applied by the operator; a database without the table reports `ACCOUNT_STORAGE_MISSING` on signup and keeps the environment login.

The desk is now arranged as market overview, forecasts, options strategy, market analyst, portfolio, and system diagnostics. Overview shows the local snapshot for NIFTY, SENSEX, and BANK NIFTY, plus India VIX, USD/INR, and crude when those context fields exist. S&P 500, Nasdaq, Dow Jones, and US VIX stay unavailable because the snapshot does not include them. Breadth, regime, and news stay blank. Forecast cards keep saved experiments separate from approved forecasts and do not treat classification metrics as expected returns. Options keeps the research fixture behind an advanced disclosure. Strategy selection does not load a chain or compute a payoff. The analyst page runs the existing local assessment only when asked, with model commentary off unless checked. Portfolio shows capital from research status and leaves utilisation, positions, and P&L unset. Diagnostics links live on the health page. No new trading endpoint was added. M10 remains incomplete. M11 was not started.

---

## Acceptance-test matrix

Pass means the system abstains, vetoes, or records the safe state named in the row. A pass is not a claim that the strategy makes money.

### Data

| Case | Required result |
|---|---|
| Stale premium or stale bid/ask | Candidate rejected. No order. |
| Missing premium, bid, or ask | Candidate rejected. Chain LTP does not fill the gap. |
| Wrong expiry, lot, tick, or symbol versus the master row | Veto. |
| Missing checkpoint candle | That forecast row is dropped, not filled. |
| Two sources disagree | Both values stored. No silent pick. |

### Forecasting

| Case | Required result |
|---|---|
| No approved model | Qualitative forecast. `NO TRADE`. |
| `model_health = DRIFT` | Model gate fails. |
| Required feature missing and the artifact has no missing-value policy | Forecast unavailable. |
| Label threshold changed after the test window was opened | Promotion refused. |
| Shuffled split used in an evaluation report | Report rejected by the promotion check. |
| Fusion artifact does not beat the baseline on the configured metric | Fusion stays `BASELINE_ONLY`. |
| Agent returns non-JSON or a probability field | Agent output dropped. Probabilities unchanged. |

### Options

| Case | Required result |
|---|---|
| Wide spread or low open interest | Ineligible. |
| Greeks absent and Black-76 disabled | No expected net. `NO TRADE` if nothing else qualifies. |
| No historical option data | Backtest of option P&L refused. Live path may still estimate from the live quote. |
| Expected net at or below zero after costs | `NO TRADE`. |
| A buy decision missing a mandatory field | `decision` is `NO_TRADE` and `status` is `INCOMPLETE`. No submit. |

### Risk

| Case | Required result |
|---|---|
| Insufficient funds | Live mode vetoes when `option_buy_balance_available` is too small or unread. Paper mode vetoes when `paper_cash` is too small. Paper mode does not read Groww. |
| Daily loss lockout | No new entry, including after restart. |
| Position count or session entry count exhausted | Veto. |
| Two proposals at once | Second reservation sees the first. |
| Kill switch | New entries blocked. Exit is a separate confirmed intent. |
| Cooldown after the configured loss count | No new entry until the next confirmed session. |
| Smallest lot exceeds the trade budget | `NO TRADE`. |

### Execution

| Case | Required result |
|---|---|
| Place call times out | `UNKNOWN_REQUIRES_RECONCILIATION`. No second place. |
| Partial fill, reject, cancel failure | State machine rows match `docs/RISK_AND_EXECUTION_SPEC.md`. |
| Restart with an open order | Reconcile by reference id. No duplicate. |
| Broker and local positions differ | New entries blocked. |
| Paper mode | Live place, modify, and cancel are not called. |

### Security

| Case | Required result |
|---|---|
| Prompt injection in news, HTML, symbols, or agent text | Limits, mode, and orders unchanged. |
| Secret in a log or API response | Test fails. |
| Live flag set only by an agent payload | Rejected. |
| Agent requests shell, SQL, or an order tool | Tool not offered. |
| Source URL is localhost, link-local, or a private address | Fetch refused. |
| Settings write without a session | Rejected. Audit row on an accepted write. |

### Promotion

| Case | Required result |
|---|---|
| Live approval without an untouched-test report | Refused. |
| Live approval when the configured calibration gate fails | Refused. |
| Model version swapped without a promotion row | Refused. |
| Prompt promoted without an explicit action | Production hash unchanged. Rollback restores the previous hash. |
| Research selection | Paper slot unchanged. |
| Paper activation of a version that is not approved for that underlying, horizon, feature schema, and strategy revision | Refused. |
| Activation while a run is in progress | The run keeps the version it pinned. |

### Model registry

| Case | Required result |
|---|---|
| Unknown model id | `UNKNOWN_MODEL`. |
| Underlying or horizon outside the version's scope | `UNSUPPORTED_SCOPE`. |
| `TRAINED` or `EVALUATED` version sent to paper activation | `MODEL_NOT_APPROVED`. |
| Activation and rollback | Audit rows, including the previous version id. |
| Workflow pin | Forecast row and graph state name the same version id through completion. |

### LangGraph

| Case | Required result |
|---|---|
| Node timeout or invalid JSON | Section missing. No probability is written. |
| Missing source | Node `UNAVAILABLE` or `DEGRADED`. No filled-in fact. |
| Conflicting specialist outputs | Both stored. Fusion status unchanged. |
| Duplicate run idempotency key | Original `run_id` returned. |
| Resume after interrupt | Same `thread_id`. Risk gates still run afterward. |
| Retry count above the configured limit | Error recorded. No further attempt. |
| Order timeout | Not a graph retry. `UNKNOWN_REQUIRES_RECONCILIATION`. |

### Fusion

| Case | Required result |
|---|---|
| Fusion artifact not approved for the mode | `BASELINE_ONLY`. |
| Fusion exception or missing fusion input | No new forecast is synthesized. Approved standalone forecast remains, or `NO_TRADE` if none is approved. |
| Agent confidence or news label | Risk veto and model probabilities unchanged. |

---

## Definition of done for this design cycle

The design cycle is done when the documents listed in `docs/DESIGN_REVIEW_RESOLUTIONS.md` agree. It is not done when live trading is safe to enable. That waits on the open questions and on evidence the forecasting spec requires.
