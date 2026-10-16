# Open questions

These block a claim that live trading can be built as specified. They do not block a fixture-backed paper shell. None of them are answered by guessing.

## Parked at the 15 Oct 2026 close

This session is treated as closed. The items below stay unresolved until a later session:

1. Groww candle timestamps still have no documented timezone and no bar-start or bar-end rule. Quarantined candles stay quarantined.
2. The documented NIFTY quote and BSE_SENSEX last-price read is implemented. It was not called against Groww at the close, and a stored result stays unverified provider data.
3. Public market RSS headlines can be fetched on demand and stored for the news agent. Breadth, sectors, FII/DII, yields, and a verified option chain are not connected. Headlines stay unlabeled and do not authorize a trade.
4. Migration `005_operator_accounts` adds the stored operator account (salted PBKDF2 hash, display name, timezone). It has been applied to the test database only. The operator applies it to the app database with `alembic upgrade head` from `apps/api`; until then the environment password signs in and the signup page says the table is missing.

## User decisions

1. Risk-capital amount, and whether the shipped policy fractions (1% per trade, 2% daily loss, 20% cash buffer, 2 positions, 3 entries) stay as the starting policy.
2. Which forecast tasks to enable first. `M15`, `M30`, `SESSION`, and `NEXT_SESSION` are the candidates that can be approved later. `M1`, `M5`, and `H1` stay unavailable until their data and labels exist.
3. The candidate grid and the selection metric for the label threshold `T`. The old percentages are not approved.
4. Whether unattended live mode will exist at all. The design leaves it off and requires per-order confirmation.
5. Which news, macro, crude, FX, VIX, and FII/DII outlets will be enabled, and under what licence.
6. Whether SENSEX options are in the analysis set only, or also on the order allow-list after the instrument master is read.
7. The drawdown-lockout fraction. It ships disarmed until set.

## Official API verification

1. Access-token lifetime. The Groww API dashboard resets API keys daily at 6:00 AM IST. An offset-less `expiry` string is read as Asia/Kolkata and compared with the current Asia/Kolkata time. A past expiry does not start a token exchange. The key-and-secret flow still requires daily approval on Groww's API keys page.
2. `get_historical_candles` timestamp contract: **RESOLVED on 15 Oct 2026**. Groww Customer Support officially replied (recorded in `docs/GROWW_CANDLE_TIMESTAMP_SUPPORT_RESPONSE.md`). Timezone is confirmed as Indian Standard Time (IST, `Asia/Kolkata`). Candle timestamps denote the start (beginning) of the candle bar. Request boundaries follow Groww charts. Opening 15-minute regular session candle is `09:15:00` (covering 09:15–09:30). Unfinished/incomplete candles can be returned by the API during an active session, requiring dynamic classification (`retrieved_at < bar_end`). Rules apply consistently across supported instruments including `NSE-NIFTY` and `BSE-SENSEX`.
3. An authenticated `get_historical_candles` call on 14 Oct 2026 accepted `NSE-NIFTY` with `exchange=NSE` and `segment=CASH` and returned candles. `BSE-SENSEX` remains documented but was not requested. BANK NIFTY still has no documented index groww symbol. The worked candle example on the page is `NSE-WIPRO` and an FNO contract, not the index.
4. SENSEX and BANK NIFTY index quote symbols, exchanges, and segments.
5. Bid and ask on F&O `get_quote`, as opposed to the equity-shaped example.
6. Theta's time unit and IV's numeric scale on `get_option_chain` and `get_greeks`.
7. `tick_size` units. The instruments page says prices are in rupees. The RELIANCE sample shows `tick_size` 5.
8. The F&O `product` and `order_type` values for a long option buy. The order examples use equity `PRODUCT_CNC`.
9. `get_order_status_by_reference` for F&O after a client timeout.
10. The order-list `page_size` maximum. The orders page prose says 100 and the schema says 25.
11. Whether `get_positions_for_user` returns an unrealized P&L. The documented field is `realised_pnl` only.
12. A crude-oil instrument on the Groww instrument file, and whether Brent is available at all.
13. Groww's current terms for automated retail orders, including any static IP, algo registration, or segment approval. Availability of an API is not a compliance determination.
14. Exercise style is not a column on the instrument CSV page that was read. No discount-rate source and no matching futures series are configured. Together with the unknown theta unit, neither `MODELLED_VENDOR_GREEKS` nor `MODELLED_BLACK76` is enabled on the Groww data documented on 14 Oct 2026. Expected net stays unavailable until one method's preconditions are actually met.

## Historical data

1. A verified source of expired index-option premiums, bids, asks, and greeks. Without it, there is no option-strategy backtest.
2. Point-in-time India VIX, USD/INR, Brent, and breadth aligned to the forecast cutoff.
3. Official FII/DII history with publication timestamps, not revised prints backfilled as if they were known during the session.
4. A holiday and session-hours calendar with an identified publisher. The M2 fixture calendar is not that calendar.
5. Point-in-time revisions of OHLC after retrieval. M2 treats a candle as available at `bar_end` only when `retrieved_at` is at or after `bar_end`. It does not store a later revision. The Groww backtesting page does not describe revisions, so M6 does not claim point-in-time reproducibility of historical OHLC.
6. Which dates are the untouched test period for a real market series. M2 leaves those fields null on the feature artifact. M3 writes a split window only on an experiment that has enough rows, and that window is not a market test while the source is synthetic.

## Model families and orchestration

1. Whether the first tree model is LightGBM or XGBoost. The forecasting spec trains one of them, not both, unless a later report justifies the second.
2. Whether a TCN, a small transformer, LSTM/GRU, TimesFM, or Chronos-2 is worth registering. Each needs a pinned upstream version, a licence note, and a suitability note. None of those notes exist.
3. How long LangGraph checkpoints are retained. The graph spec stores them in Postgres and does not treat that choice as a compliance decision.
4. A verified 1-minute and 5-minute history for the three indices. The annexures name those intervals. M6 did not ingest them. Fifteen-minute index candles are also unverified until the timestamp boundary and timezone are documented.

## Empirical testing

1. Which frozen `T` the validation protocol actually selects, after data exists.
2. Whether logistic regression beats the base rate and the last-return-sign baseline out of sample, by task and underlying. M3 can score one holdout and M4 can score expanding folds on a supplied dataset. M5 can register those runs. No real-market series has been scored, and a synthetic or research-approved row is not that result.
3. Whether a tree model beats logistic regression by more than the configured research gate on the untouched test.
4. Whether any fusion feature improves Brier or log loss versus the quantitative baseline without worsening the tail metric.
5. Calibration by time of day, expiry day, and event day.
6. Paper-trading results of the expected-value rule against `NO TRADE`, including costs. Directional accuracy is not that test.
7. Drift-window length. Twenty sessions is only a starting example.

## Compliance review

1. Whether this operator's Groww account and API subscription permit the order flow in `docs/RISK_AND_EXECUTION_SPEC.md`.
2. Whether unattended orders, if ever enabled, need any exchange or broker approval beyond the API subscription.
3. Record-keeping and audit retention the operator wants, given this is a single-user local system and not a service for other clients.

No question in this file is resolved by the current design. `docs/DESIGN_REVIEW_RESOLUTIONS.md` lists the design choices that were made while leaving these open.
