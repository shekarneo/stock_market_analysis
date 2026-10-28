# Analysis, Forecasting & Options Logic Audit — 2026-10-22

**Scope:** `apps/api/app/analysis`, `forecasting`, `options`, `risk`, `execution`, `watchlist`, `market/groww_options.py`, and the `/live` page in `apps/web`.
**Method:** Read-only code review plus a check of the reported results in `docs/M2x–M4x` reports. No live data or database was available in this checkout, so results were not re-run.
**Verdict:** The system is **not fit for real trading decisions**. The issue is not only "no edge". Several user-facing numbers are hard-coded, synthetic, sign-inverted, or stale while being labelled as live or verified.

---

## 1. Is there any real edge? (results in the docs)

| Evidence | What it shows |
|---|---|
| M37 Table 1: *Empirical Prior + Regime Gated* (a constant, no model) makes +2.12% full / +3.97% holdout. *Logistic Regression + Regime Gated* makes +2.83% / +3.30%. | The model adds nothing over a constant. The ADX/DI trend filter does all the work. |
| The "optimal" strategy loses on development folds (−1.77% / −0.46%) and wins only on a 75-bar (~37 session) holdout. | Holdout luck, not edge. 52–56% accuracy at n≈75 has a 95% CI of about ±11 pp. |
| Holdout turnover is 5 units, i.e. 2–3 trades. | No statistical meaning. |
| Model, mode, instrument, threshold and milestone combinations (M19–M41) were ranked by **holdout** return. | Multiple testing. The holdout is no longer untouched. |
| M40 BANKNIFTY data is **synthetic**: `beta*nifty_ret + rng.normal()` (`m40_multi_asset_research.py:167-197`). | All "multi-asset generalization" results are meaningless. Zero-shot transfer still failed (−7.85%, −3.19%). |
| Costs are 2 bps on spot index returns, but the app recommends **buying options**. | Option spread, theta and IV change are not modelled. Real friction is many times larger. |
| `tests/test_m40_*` assert holdout return > +5%. | The tests lock in a backtest outcome instead of testing correctness. |

**Conclusion:** No evidence of predictive edge after realistic costs. Only one year of 15-minute data (≈488 half-day bars) exists.

---

## 2. Critical defects (fabricated or wrong numbers shown to the user)

### Forecasting
- **F1** `forecasting/instrument_hub.py:207-216`: when the model is missing, it emits `direction="BULLISH"`, `calibrated_p=0.5340`, and spot `24850.0` / `81380.0` / `6150.0`. The "supporting evidence" strings are static text.
- **F2** `forecasting/instrument_hub.py:382-453`: the backtest card is literals (MDD `9.62`, accuracy `0.52`, BSS `0.0101`, baseline table, "Zero overnight gap risk", which is false).
- **F3** `main.py:845-864` (`/api/forecasting/live-trend-chart`): `direction` is the **sign of last year's holdout P&L**, and "probability" is the historical accuracy. Fallbacks are `or "BULLISH"` and `or 0.53`. The 19-fold benchmark is re-run on every GET.
- **F4** `forecasting/live_forecast.py:299-354`: silently falls back to old dataset files and still reports `ACTIVE` with no freshness check. There is a hard-coded `static_cutoff = 2026-10-14` (line 213). Exceptions are swallowed.
- **F5** The live model is the M3 15-minute logistic regression, trained on a 60% slice with raw price-level features (`targets.py:27-39`), never refit, and uncalibrated. It is **not** the strategy that was backtested (half-day, regime-gated, constant prior).

### Agents / consensus
- **A1** `analysis/evidence.py:118` stamps every item `UNVERIFIED`, so Veto E always fires and quality is capped at 0.5. `agent_nodes.py:916` hard-codes `decision = "NO_TRADE"`. The consensus engine can never produce a trade, so its numbers are decorative.
- **A2** The calls users actually see ("BUY CE / BUY PE") come from a **separate** integer score in `intelligence._evaluate_market_consensus`. The gate does not overwrite `markets[inst].decision`, `bias`, `options_evaluation.verdict`, or the option picks (`nodes.py:470-485`, `intelligence.py:793-811`). The UI can show "BUY CE" and "STAND ASIDE" together.
- **A3** `agent_nodes.py:414-450` (technical analyst): computes a "return" across `last_price` of **different instruments** (for example NIFTY ~25k vs SENSEX ~82k gives ±70–228%). It then emits BULLISH/BEARISH at 0.85 confidence under the highest-weighted role. No RSI, ADX or Hurst is computed in this node.
- **A4** Crude is inverted twice. `groww_market_snapshot.py:572` maps falling crude to BULLISH (equity view). `intelligence.py:509-511` reads BULLISH as "crude rising" and subtracts. For CRUDEOILMINI itself, that row drives its own technical call.
- **A5** `intelligence.py:175-193`: headline sentiment uses substring keywords with no word boundaries or negation ("war" matches "software"/"award"; "gain" matches "against"; "bull" matches "bulletin"). News is not filtered by instrument. One headline can flip the call to "BUY CE (MOMENTUM)".
- **A6** US VIX is treated as India VIX and counted as a bullish vote when it rises (`agent_nodes.py:526,546`, `intelligence.py:612`). VIX defaults to `14.0` when missing.

### Options / watchlist
- **O1** `intelligence.py:751`: `is_bull = "BUY" in consensus["call"]`. "BUY PE" contains "BUY", so **every bearish pick gets bullish spot target/SL**.
- **O2** `market/groww_options.py:262-317`: the live option quote matches only strike + CE/PE from one shared `option_chain_latest.json`. There is no check on underlying, expiry or age. A stale or cross-instrument LTP is labelled `is_live_quote=True` and used to lock watchlist entries and resolve hits.
- **O3** `watchlist/service.py:182-199`: a spot SL hit is cancelled if the premium hasn't breached, but a spot target hit is never cancelled. Accuracy is biased toward TARGET_HIT. `delta or 0.5` is invented.
- **O4** `intelligence.py:364-454`: when there is no chain quote, premiums are synthetic (`0.40*spot*iv*sqrt(3/365)`, IV from VIX or 14%, also applied to crude), and are quoted in the execution guide as "Top pick ₹…".
- **O5** Lot sizes disagree. NIFTY is 75 (`intelligence.py:330`), 25 (`portfolio_risk.py:39`, `instrument_hub.py:52`, web `/live`), and 65 (`simulation.py` default). SENSEX is 10 in `portfolio_risk.py:43` and the web page, vs 20 elsewhere. *Verify current values against the exchange contract master.*
- **O6** `groww_options.py:29-90`: a static NIFTY-only expiry list is used for every underlying (SENSEX and MCX are mis-resolved). Dates use UTC rather than IST.

### Web `/live` page (`apps/web/app/live/page.js`)
- **W1** Lines 440-455: watchlist payload defaults are entry ₹120, target ₹180, SL ₹80, delta 0.5, lot 25/10, target points 80/250/50.
- **W2** Lines 593-610: simulated orders are browser-only state with random IDs. The entry defaults to ₹120, target and SL are ×1.4 / ×0.75, and `entrySpot` falls back to the **premium**. P&L = spot move × fixed delta 0.5 (no theta or IV). Positions are lost on refresh.
- **W3** `pick = rec.top_5_options[2]`: picks the third element regardless of quality.

---

## 3. High / medium defects (summary)

- **Holdout selection:** `/multi-benchmark` ranks about 7 models × 3 modes × 4 instruments by holdout return. "OPTIMAL_CANDIDATE" is assigned despite negative dev return.
- **Overnight exposure:** the half-day O2O target includes the overnight gap (`m27_htf_research.py:349-353`). `close_ts` is the bar start.
- **Accounting:** fold returns are summed. Max drawdown is the mean or max of per-fold values, not the drawdown of the chained equity curve. Exits are not charged at fold end. No Sharpe is computed.
- **Quant vote:** `p_up >= 0.50` gives BULLISH with no deadband, at weight 2.5. Thresholds disagree across modules (0.45/0.55, 0.47/0.53, 0.48/0.52).
- **Neutral votes:** the News analyst always returns NEUTRAL at 0.60–0.65 (all items `UNKNOWN`). The Market-Data analyst is always NEUTRAL at 0.70. Both dilute the consensus.
- **Dispersion index:** unweighted. Confidence is imputed at 0.60 when absent.
- **LLM agents:** receive only text findings, not numbers. They may overwrite bias and confidence without citing evidence.
- **Hard-coded defaults:** `forward_price=25000`, `time_years=7/365` (agent_nodes 704-705), `spot_price or 23146.15` written into the outcome tracker (nodes 390).
- **Risk gates:** a short option passes as LONG_CE/LONG_PE (`gates.py`). `experimental`, `execution_context` and `expected_net` come from the client and bypass gates. Sizing mixes the underlying's ATR with the option premium. Defaults of win_prob 0.5 and RR 1.5 give a positive Kelly.
- **Paper sim** (`execution/simulation.py`):
  - A SELL entry crashes (`bid` is not passed).
  - Quantity is always 1 lot.
  - Missing exit price books a flat exit.
  - Exchange charge is 0.05% vs 0.03503%.
  - NSE rates are applied to MCX.
- **Registry:** text version sort ("v9" > "v10"). Accepts `TRAINED`, i.e. unapproved, models.
- **Black-76:** the call theta rate-term sign is wrong (`m39_options_analytics.py:132`).

**Sound as written:** M2 features are trailing. Scalers are fit on train only. Embargo and purge are correct. ADX and Hurst are causal. Black-76 d1/d2, gamma, vega and rho are correct. Stamp duty, STT, SEBI fee and GST are correct. Paper P&L signs are correct. The core `options/expected_value.py` fails closed.

---

## 4. Fix plan (proposed order)

**Phase 1 — Stop showing false numbers (truth in data)**
1. Remove the hard-coded fallbacks in `instrument_hub.py`, `main.py` live-trend-chart, `live_forecast.py` and `nodes.py`. Return `UNAVAILABLE`/`null` instead.
2. Add a feature-freshness check to the live forecast. Remove `static_cutoff`.
3. Quarantine the synthetic BANKNIFTY dataset (flag it `SYNTHETIC`, exclude it from live and benchmarks).
4. Stop returning synthetic option premiums. Show premiums only from a fresh, matching (underlying + expiry) chain quote.
5. Remove the `/live` page defaults (₹120 / 180 / 80, delta 0.5, hard-coded lots).

**Phase 1 status (2026-10-22): implemented, not yet run against Postgres/Node.**
Covers F1–F4, the defaults in A6/A7 (VIX 14, spot 23146.15, forward 25000), O2 (quote underlying/expiry/age checks), O4, M40 BANKNIFTY quarantine, and W1/W2.
Also declared the missing `beautifulsoup4` dependency.
New tests: `apps/api/tests/test_truth_in_data_fallbacks.py`.

**Phase 2 — Fix sign and logic bugs**
6. `is_bull` for PE calls. Crude direction (store the raw price direction, apply transmission once). US VIX vs India VIX.
7. Technical analyst: per-instrument, time-ordered bars of a known timeframe. Real indicators.
8. Use one decision path. The gated result must overwrite every directional field and pick.
9. Symmetric watchlist hit/SL scoring.
10. A single instrument master (lot, strike step, tick, expiry calendar) per underlying.

**Phase 2 status (2026-10-22): implemented, not yet run against Postgres/Node.**
- O1: PE direction now comes from the bias, not the call text.
- A4: crude sign is applied once; snapshot rows carry a raw `price_direction`.
- A6: only India VIX is read, it is not used for crude, and a rising VIX counts as bearish.
- A3: the technical analyst only reads the target instrument.
- A2: there is one decision gate (`nodes.apply_decision_gate`).
- O3: watchlist scoring is spot-only and symmetric.
- O5: a single instrument master (`app/instrument_specs.py`) feeds the backend and the UI.
- Also removed the fabricated PCR, max pain and spot values from `V6OptionsGreeksCard`.

Not yet done:
- O6: expiry calendars for SENSEX and MCX.
- Exchange-fee and MCX charge corrections.
- The `close_paper_position` flat-exit fallback.
- Per-instrument consensus.
- The always-UNVERIFIED evidence veto.

New tests: `apps/api/tests/test_signal_direction_logic.py` and two new cases in `apps/api/tests/test_watchlist.py`.

**Phase 3 — Make the research honest**
11. Deploy exactly what was validated (or validate what is deployed). Persist one model and run inference only.
12. Chain out-of-sample folds into one equity curve. Compute Sharpe and max drawdown properly. Bootstrap CIs. Report a deflated Sharpe / Reality Check.
13. Backtest the traded instrument (option-chain P&L or futures) with realistic costs.
14. Get multi-year data. Pick models on dev only, then evaluate once on a fresh holdout.
15. Replace tests that assert backtest returns with correctness tests.

**Phase 3 status (2026-10-22): implemented in code, results not yet regenerated.**

What changed:
- `app/forecasting/evaluation.py` is the new evaluation module. It provides:
  - a chained out-of-sample equity curve, with a cost on every position change and on the final exit;
  - a correctly annualized Sharpe ratio;
  - the probabilistic and deflated Sharpe ratios;
  - the Wilson interval and binomial p-value for accuracy;
  - a Brier skill score measured against the evaluation set's own base rate;
  - a block-bootstrap confidence interval;
  - a cost model for NSE index futures (statutory charges plus 1 bp assumed slippage, about 2.5 bps per side).
- **M37/M40:**
  - Legacy figures are now compounded on the chained curve. Fold returns are no longer summed, and drawdown is no longer averaged across folds.
  - Every strategy carries an `honest` block (development, holdout and full).
  - A model whose library is missing is excluded, instead of being reported under the empirical prior's numbers.
  - The Chronos wraparound misalignment is removed.
- **Benchmarks:** `/multi-benchmark` and `/train-benchmark` rank on development deflated Sharpe only. They report an edge verdict and return `MODEL_UNAVAILABLE` instead of substituting another model.
- **Live model:**
  - The quant analyst votes only on its own instrument's ACTIVE forecast, with a [0.45, 0.55] deadband.
  - The registry orders versions numerically, so v10 sorts after v9.
  - Forecasts are labelled `after_cost_validation: NONE`.
- **Tests:** tests asserting returns above +5% (M40), above Rs 40k (M42) and exact golden P&L (CLI) are replaced with chaining, accounting-identity and structure checks.

Still open:
- **Data:** only one year of 15-minute data exists. Multi-year history is needed before any holdout is meaningful.
- **Option P&L backtest:** this needs historical option-chain data, which is not in the repo. Costs remain futures-based.
- **Results:** regenerate the M37/M40/M42 artifacts on the Linux box. Past report numbers (M28–M42 docs) were produced with the old aggregation and should not be quoted.
- **CLI golden test:** since Phase 2, NIFTY sizing uses lot 65 (the earlier tests assumed 25). Any golden numbers from older runs no longer apply.


---

## Phase 4 status (2026-10-23): implemented

Verified on a temporary SQLite database with Postgres functions stubbed. The Postgres test suite has not been run.

**Headline sentiment (`analysis/intelligence.py`)**
- Matching is now whole-word and negation-aware. "war" no longer matches "software", "gain" no longer matches "against", and "bull" no longer matches "bulletin".
- IPO terms are dropped.
- A relevance filter decides which headlines count for each instrument: equity terms for NIFTY and SENSEX, crude terms for CRUDEOILMINI.
- Equity risk words such as war and recession are not applied to crude.
- A news vote needs at least 2 relevant headlines, with the dominant side at least twice the other.
- Directions supplied by the news provider are stored separately from inferred ones.

**Paper simulation (`execution/simulation.py`)**
- The bid is carried into the intent. A missing quote side returns `QUOTE_SIDE_UNAVAILABLE` instead of crashing.
- Quantity is `lots` × lot size. `lots` is a new request field, and the exposure gate vetoes `LOTS_EXCEED_RISK_BUDGET` when it is above the risk-sized lot count.
- A close needs an exit price, or an exit quote with the right side. It is no longer booked flat at the entry price.
- Exit charges reuse the entry's charges-per-lot.
- Charge schedules are set per exchange and instrument type:
  - NSE options: exchange charge 0.03503%.
  - BSE options: 0.0325%.
  - NSE futures: their own rates.
  - MCX: uses CTT and is flagged `rates_verified: false`.
- The fill breakdown records the exchange, lot size and charges-per-lot.

**Risk gates (`risk/gates.py`)**
- Selling an option to open is `SHORT_CE` / `SHORT_PE`, which is not on the allow-list. Selling to exit is still allowed.
- Experimental relaxed gates are granted only server-side (`_server_experimental`: PAPER mode, kill switch off, all virtual risk controls configured). A request body can ask but cannot grant.
- The daily-loss lockout counts realized P&L by IST session day only. It no longer also matches the UTC date.
- `expected_net` is now labelled `CLIENT_SUPPLIED` in the intent. It is still accepted as input.

Still open:
- Server-side EV for `expected_net`.
- MCX charge rate verification.
- Expiry calendars for SENSEX and MCX.
- The m39 options-analytics defaults and theta sign.
- Consensus veto design.
- Live-model feature normalization.


## Phase 5 status (2026-10-23): implemented

**Options analytics (`options/m39_options_analytics.py`)**
- Black-76 call theta is now `(-e^-rT·F·σ·φ(d1)/(2√T) + r·C)/365`. It is checked against a numerical derivative; the old sign was off by 74% in a long-dated test case.
- The IV solver returns None when IV is undefined (at expiry, at or below intrinsic, or no fit), instead of 0.15 or 0.01.
- Missing bid, ask, open interest and volume stay None; they are no longer turned into 0.
- PCR is None when open interest is missing, and sentiment is then UNKNOWN. Previously both fell back to PCR 1.0.
- Max pain needs open interest at every strike.
- ATM IV is None instead of 0.15.
- The 25-delta skew uses only records that have Greeks.

**Expiries (`market/groww_options.py`, `options/validation.py`)**
- Expiries are listed per underlying.
- SENSEX and MCX return `EXPIRY_MASTER_UNAVAILABLE` instead of being checked against NIFTY dates.
- "Upcoming" never returns an expired date.
- All expiry comparisons use the IST date.

**Consensus (`analysis/consensus_engine.py`, `analysis/agent_nodes.py`)**
- An unreported confidence is not imputed; that specialist carries no weight.
- UNKNOWN and MIXED biases carry no weight.
- The disagreement index is weighted by effective weight.
- The Market Data analyst checks provenance only, so it no longer votes.
- The News analyst uses relevance-aware headline reading. It abstains when there is no clear signal, and no longer votes NEUTRAL at 0.60–0.65.
- `test_options_analyst_node_integration` was failing since Phase 1 because its quotes lacked `time_years`; the test now supplies it.

Still open:
- Server-side EV for `expected_net`.
- MCX charge rates.
- SENSEX and MCX expiry lists, which need loading from the BSE and MCX instrument masters.
- The always-UNVERIFIED provenance veto.
- Live-model feature normalization, which needs a retrain.


## Phase 6 status (2026-10-23): implemented

**Scale-free model inputs (feature set `ohlc-2`)**
- New features: `close_vs_sma_3`, `sma_3_vs_sma_5` and `atr_3_pct`.
- `MODEL_FEATURES` now drops the price-level inputs (`sma_3`, `sma_5`, `sma_3_minus_sma_5`, `atr_3`). Those columns stay in datasets for lineage.
- A check confirms the features are identical at index levels 25,000 and 82,000.
- Hard-coded `"ohlc-1"` strings now use `FEATURE_SET_VERSION`.
- Models trained on the old inputs are refused by the live loader. **Run `retrain-live` before expecting an ACTIVE forecast.**

**Retrain command (`python -m app.cli retrain-live --dataset-id <id>`)**
- It rebuilds features from a stored history dataset, runs the M3 holdout, and registers the model through the existing registry path, keeping checksums and lineage.
- Without `--dataset-id`, it lists the stored datasets.

**Server-side expected net (`execution/simulation.py`)**
- A client-sent `expected_net` is never used for gating. The server asks the EV module, which today returns no expected net, so `EXPECTED_NET_UNAVAILABLE` vetoes experimental simulations by default.
- There is a new risk config setting, `experimental_requires_server_ev`, which defaults to true. Setting it to false in the operator's stored config lets the client figure through, labelled `CLIENT_SUPPLIED_OPERATOR_ALLOWED`.

**Expiries from the instrument master (`market/instrument_master.py`)**
- The command `python -m app.cli refresh-expiries --download [--api]` reads Groww's public instruments CSV. With `--api`, it also queries the authenticated Groww Expiries API (`GET /v1/historical/expiries`, NSE/BSE only).
- It writes `var/market/listed_expiries.json`, which `groww_options.listed_expiries_for` prefers over the built-in NIFTY list.
- It reports lot-size mismatches against `instrument_specs.py`, and prints the MCX crude-mini front-month future.
- `read_mcx_quote` now requires a trading symbol, replacing the stale default `CRUDEOILM19OCT26FUT`.

**Charges**
- Rates checked 2026-10-23 against the Zerodha exchange-charges pages:
  - NSE totals now include the IPFT levy: options 0.03553%, futures 0.00183%.
  - BSE SENSEX options: 0.0325%.
  - MCX options: 0.0418% exchange charge plus 0.05% CTT on sells.
  - MCX futures: 0.0021% plus 0.01% CTT.
- Every schedule is marked verified. The futures cost model is updated to match.

**Tests**
- Tests that hard-coded `"ohlc-1"` as the current version now use the constant. Tests that used `"ohlc-2"` as an unsupported version now use `"ohlc-99"`.

**Operator actions after deploying**
1. `python -m app.cli refresh-expiries --download --api`
2. `python -m app.cli retrain-live --dataset-id <NIFTY history dataset>`
3. Check the lot-size mismatch output (for example, NIFTY 65).

## Research phase (2026-10-23): multi-year daily / half-day research

**Why**
- The 15-minute direction model trained on about one year of data is close to a coin flip. This phase tests whether longer horizons, more history, cross-asset inputs or a volatility target hold up under the same honest evaluation.
- It is research only. It does not change the live model, the gates or any trading path.

**Data loader** (`app/market/history_loader.py`)
- Uses `GET /v1/historical/candles` from 2020 onwards. Requests are split to stay within the per-request limits: 30 days for 1–5 minute candles, 90 days for 10–30 minute candles, 180 days for 1 hour and longer.
- Rows with bad OHLC geometry are rejected and counted. Missing volume or OI stays `null`.
- Failed windows are logged in the series file and never filled. Re-running merges new candles into the saved series.
- Output: `var/datasets/history/<groww_symbol>_<interval>.json`, with every request logged.
- Default series: `NSE-NIFTY`, `NSE-BANKNIFTY`, `NSE-INDIAVIX`, `BSE-SENSEX`. Verify these symbols against the instrument CSV if any of them returns no candles.

**Options positioning** (`app/market/options_history.py`, optional)
- For each NIFTY expiry, contracts come from the Expiries and Contracts APIs. Daily CE and PE candles (which carry OI) are fetched for strikes within ±N steps of spot.
- Spot for the strike band is the last close at least 12 days before expiry, so contract selection never uses prices from after the PCR window.
- The feature is the PE/CE OI ratio of the nearest unexpired expiry. A day appears only when both sides report OI.
- Cost: several thousand requests. Results are cached per contract, so the job can be resumed.

**Research** (`app/research/daily_research.py`)
- **Horizons:**
  - next-day close-to-close direction;
  - next half-day direction, using AM (before 12:15) and PM bars built from 15-minute candles, with incomplete halves dropped;
  - next-day realized volatility, measured as Parkinson variance.
- **Features** (all known at the close of day t):
  - returns over 1, 5 and 20 days;
  - overnight gap;
  - log Parkinson variance over 1, 5 and 20 days;
  - India VIX level and its change;
  - the variance risk premium (VIX-implied variance minus 5-day realized variance);
  - BANKNIFTY and SENSEX returns relative to NIFTY;
  - PCR level and its change.
  
  A row with any missing input is dropped, never filled.
- **Walk-forward:** expanding window with a one-row embargo. The last 20% of folds are the holdout. Selection uses the development period only.
- **Direction scoring:**
  - Models are the empirical prior, L2 logistic regression and a shallow LightGBM, for each feature set.
  - Positions use a deadband (long above 0.55, short below 0.45). Index-futures costs come from `FuturesCostModel`.
  - Each feature set and model combination is one trial. The deflated Sharpe ratio is computed over all trials.
  - "Edge supported" requires a development DSR of at least 0.95 and a holdout PSR of at least 0.9.
- **Volatility scoring:**
  - Models are naive (today's realized variance), HAR-RV, VIX-implied (bias-corrected on the training window) and HAR plus VIX.
  - Scored on QLIKE and MSE of log variance, with Mincer–Zarnowitz R².
  - Diebold–Mariano tests (Newey–West, lag 5) compare each model with the naive and VIX forecasts.
- **Tests** (`tests/test_research_multiyear.py`):
  - On a GARCH series, HAR beats naive with a significant DM result, and no direction edge is claimed on the random-walk returns.
  - A predictable AR(1) series is detected as an edge, which is the positive control.

**Not available, therefore not used:** MCX crude and USD/INR history (Groww's historical API serves only NSE and BSE), and FII/DII flows.

**Run**
1. `python -m app.cli fetch-history --symbols NIFTY,BANKNIFTY,INDIAVIX,SENSEX --from 2020-01-01 --interval 1day`
2. `python -m app.cli fetch-history --symbols NIFTY --from 2020-01-01 --interval 15minute` (for the half-day horizon)
3. Optional: `python -m app.cli fetch-history --symbols NIFTY --interval 1day --options` (the NIFTY daily PCR)
4. `python -m app.cli research-daily [--with-pcr]` writes `var/datasets/research_daily_report.json` and prints every trial.

**Results:** not yet run. This environment has no Groww token. Until the report exists, no edge claim is made.

## Macro flows fix (2026-10-23): no invented releases, staleness, FII-led direction

**Found in a live run:** the global-macro agent voted BULLISH because of FII/DII flows dated 2026-10-16, a week old. Those figures were themselves invented. When `var/market/macro_series.json` did not exist, `get_macro_observations` wrote a hard-coded snapshot labelled `VERIFIED_PUBLIC_REPORT`: FII −1245.5 Cr, DII +1850.25 Cr, USD/INR 95.08, US10Y 4.08. Missing values fell back to 0 or to those numbers. The direction also came from the net total, so FII selling offset by DII buying counted as bullish.

**Fixed** (`app/market/macro_series.py`, `app/analysis/agent_nodes.py`):
- **No file means no observations.** Nothing is written, and a series with a missing value is skipped instead of being filled.
- **Staleness follows each release's publication schedule:**
  - FII/DII at 17:30 IST, USD/INR at 13:30 IST, US10Y at the US close. Weekends are skipped.
  - A release more than one business day behind the latest expected one is stale. It gets a `STALE: ...` limitation and no direction.
- **FII-led direction:**
  - BULLISH or BEARISH only when FII flow (at least ₹500 Cr) and net flow agree in sign.
  - MIXED when DII flow offsets FII flow.
  - UNKNOWN below ₹500 Cr.
- **Macro agent:**
  - Stale inputs are excluded from the vote and named in its findings.
  - With no fresh directional factor it returns UNKNOWN with null confidence; it used to return NEUTRAL at 0.60.
  - The latest daily release still counts during market hours, even though it is hours old.
- **Real fetcher** (`app/market/macro_fetch.py`, `python -m app.cli fetch-macro`):
  - **Sources**, all public unauthenticated reads with TLS verified (no CAPTCHA involved):
    - NSE `api/fiidiiTradeReact`. The NSE home page is requested first because the API needs its cookies.
    - FBIL `wasdm/refrates/fetchfiltered`, the endpoint behind FBIL's public reference-rate table.
    - The US Treasury daily par yield CSV, `10 Yr` column.
  - **Failures:** a failed source keeps its previous entry, which then turns stale by its own date. The error is recorded in the file's `errors`. Nothing is filled in.
  - **First live run (2026-10-23):**
    - FII −3,458.7 Cr and DII +2,891.3 Cr on 22 Oct, so BEARISH.
    - US10Y 4.96% on 22 Oct.
    - FBIL's latest USD/INR was dated 15 Oct, so it was STALE and did not vote.
  - Run it once a day after 17:30 IST, before analysis runs.

## Realistic forecast (2026-10-23): fresh data, tuned models, honest output

**Fresh data:** the WSL test install's old `var/` was archived, not deleted. Groww daily and 15-minute history since 2020 was then re-fetched for NIFTY, BANKNIFTY, India VIX and SENSEX, with 0 failed windows and 0 rejected rows. Macro data and news were refreshed too.

**Tuning** (`app/research/realistic_forecast.py`, `python -m app.cli forecast-daily`; the research job on `/backtest` runs it too):
- **Direction:** feature sets × (L2 logistic C ∈ {0.01, 0.1, 1}, shallow LightGBM in 3 settings) × deadbands {0.45/0.55, 0.40/0.60}, plus the prior, gives 38 trials on 1,690 sessions.
  - Selection uses the development period only; the deflated Sharpe counts every trial.
  - A model probability is published only when development DSR ≥ 0.95 and holdout PSR ≥ 0.9. Otherwise the historical up-day rate is shown as `NO_RELIABLE_EDGE`.
- **Range:** naive, HAR, HAR+VIX, HAR+VIX+leverage and HAR+VIX+leverage+gap, chosen on development QLIKE.
  - The bands come from development out-of-sample errors, and their coverage is checked on the holdout.
  - The close-to-close move is the empirical ratio of |return| to forecast volatility.

**First result (as of the 22 Oct close, for 23 Oct):**
- **Range:** HAR was selected. Expected range 2.05% (~465 pts), 90% band 0.99–4.40%. The 90% band held on **exactly 90%** of unseen sessions, and the forecast was 38% better than "same as yesterday" (DM p < 0.001).
- **Typical close-to-close move:** 0.90% (~204 pts); 9 sessions in 10 stay within 2.60%.
- **Direction, next session:** NO_RELIABLE_EDGE. The best of 38 trials reached 57.7% holdout accuracy, p = 0.56.
- **Direction, next half-day:** NO_RELIABLE_EDGE, at 49.5%.

**The 15-minute live model:**
- **Training data:** the registry's model was trained on 6 months of real NIFTY data (origin PROVIDER).
- **Its own evaluation:** model selection picked `majority_class` over it, so it never beat the baseline.
- **Status:** it is refused after the scale-free feature change and shows NO_FITTED_MODEL.
- **Why it can't simply be retrained on the new data:** the M15 feature pipeline's validator accepts only one unbroken run of 15-minute bars, so multi-day real history cannot pass without redesigning the validator. Given the evidence of no edge at intraday horizons, it stays retired.
- **Tests:** the live-forecast plumbing tests now use a fixture registry (`tests/live_model_fixture.py`), not the operator's registry.

**Benchmark honesty:** the original M37 benchmark filled in a base-rate prediction under the name of a model whose library (CatBoost, PyTorch) was not installed. Since Phase 3 such models are skipped. `/api/forecasting/multi-benchmark` now lists them in `unavailable_models`.

## Agent accuracy (2026-10-23): measured track records, locked calls, forward scorecard

**Technical Analyst replay** (`app/research/agent_backtest.py`, `python -m app.cli agent-backtest`):
- The real node was replayed with the LLM off on 1,679 completed sessions of fresh Groww 15-minute data.
- Calls were made at 10:15, 12:00 and 14:00 IST, with the live-shaped evidence: the latest price and the previous close.

| Call at | About | Right, all years | Right, unseen period (Jun 2025 →) | Net per call after costs |
|---|---|---|---|---|
| 10:15 | rest of day | 53.0% (p = 0.026) | 58.7% (p = 0.004) | −0.045% |
| 12:00 | rest of day | 54.8% (p < 0.001) | 56.3% (p = 0.035) | −0.018% |
| 14:00 | rest of day | 52.4% (p = 0.066) | 52.8% | −0.024% |
| 12:00 | next session | 54.7% (p < 0.001) | 53.1% | +0.041% (not significant) |

- **Momentum effect:** the intraday effect is small but real.
- **No tradeable edge:** nothing makes money with index futures after costs.
- **Overstated confidence:** the formula claimed 0.60–0.80, but actual hit rates were 0.44–0.64, with no consistent ordering.

**Changes:**
- **Measured confidence:** the technical agent's confidence is now its measured hit rate for that time of day (`MEASURED_HIT_RATE`, calibrated). The finding states n and the CI; the limitations say it lost money after costs.
- **Consensus weighting:** a measured agent is weighted by its skill, 2 × hit − 1. So 54.8% is worth 0.096, where the old stated 0.8 was worth eight times more.
- **Locked calls:** the technical, macro, news and options agents keep their rule's bias and confidence (`lock_bias`). Before, an LLM could replace both, so what users saw could not be measured.
- **Forward scorecard** (`app/analysis/agent_scorecard.py`):
  - Every NIFTY analysis records each agent's call and the spot price.
  - Calls are scored against the session close and the next close from saved Groww history.
  - Status: COLLECTING (fewer than 30 scored), then PROVEN, NO_EDGE_YET or WORSE_THAN_CHANCE.
  - This is the only honest test for the news, macro and LLM-assisted agents, because a historical replay would leak the future.

## Consensus weighted by track record (2026-10-23)

**Problem seen live:** at 15:23 IST NIFTY was above the previous close, and the measured technical agent said BULLISH (weight 0.05). The unmeasured news and macro agents said BEARISH with stated confidences of 0.65 and 0.69 (weights 0.33 and 0.24), so the consensus was −0.84 against the price.

**Change** (`consensus_engine.evaluate_multi_agent_consensus(evidence=...)`; the decision nodes pass the forward scorecard):
- **Measured on history** (`MEASURED_HIT_RATE`) or **PROVEN** on the scorecard: full weight, with confidence = skill (2 × hit − 1). A PROVEN agent uses its scored hit rate.
- **NO_EDGE_YET / WORSE_THAN_CHANCE:** weight 0.
- **Unmeasured** (no scored calls, or still COLLECTING): 10% of its stated weight (`UNMEASURED_WEIGHT_FACTOR`).
- **Unchanged:** direct engine calls without evidence keep the stated weights. Each specialist score now carries `evidence_status` and `evidence_factor`.

**Result in the UI (15:30 IST):** news 0.33 → 0.03, macro 0.24 → 0.02, technical 0.07 (now the largest). The total proven weight was 0.13, so the verdict stayed at stand aside.

## Data integrity (2026-10-23): bad quotes, repeat calls, stale USD/INR

**Findings after the close (checked against Groww 1-minute candles):**
- **A quote that never traded.** At 15:23 IST the Groww quote gave NIFTY 22795.15, but the day's high was 22786.95 (09:17), and the 15:15 bar never rose above 22600. So the "NIFTY above the previous close" in the section above came from this bad print, and the technical agent's BULLISH call was made on it. The 1-minute candles were also flat at 22516.40 from 15:15 to 15:27, then printed exactly 22600.00 at 15:28.
- **Repeat runs counted as evidence.** Six analysis runs within 40 minutes gave six "calls" per agent. Thirty clicks in one afternoon could have marked an agent PROVEN.
- **Slow scoring.** Every call waited for the next session's close, even its rest-of-day result.
- **Stale USD/INR.** FBIL's public table had no row after 16-Oct (it returned nothing for 20–23 Oct), so the macro input was a week old.
- **US 10Y missing in WSL.** The corporate proxy intercepts home.treasury.gov (and api.openai.com) with its own root CA ("Cloud Services Root CA", Blue Coat), which Windows trusts but WSL does not.

**Changes:**
- **Quote range check** (`live_quotes._normalize_quote`): a NIFTY quote outside the day's own low/high (the quote's `ohlc`) is rejected as `QUOTE_OUT_OF_RANGE` and not stored. A quote without a day range is kept with the limitation "could not be range-checked".
- **No carry-forward:** an instrument whose read failed or was rejected is not filled back in from the previous read (`_persist`, `poller.perform_live_sync`). Without a fresh NIFTY price the analysis has no spot, and the scorecard records nothing.
- **Scorecard counting** (`agent_scorecard.counted_calls`): one call per agent per session: the first in-session call, plus the first off-hours call (which is about the next session). Every call is still recorded; the summary reports `recorded_calls` and the counted `calls`.
- **Scoring at the close** (`score_pending`): the rest-of-day result is scored as soon as that session's close is saved, and the next-session result a session later. A pre-open call is scored on that day's close (before, it was scored on the day after). Each NIFTY 1day history fetch now scores pending calls.
- **USD/INR** (`macro_fetch.fetch_usdinr`): the ECB daily euro reference rates give the USD/INR cross (INR per EUR ÷ USD per EUR). The fresher of FBIL and ECB is kept, FBIL on a tie, and the source is named in the entry. On 22-Oct ECB gave 94.82 (FBIL 16-Oct: 95.02).
- **US 10Y:** no code change; the fetcher already verifies TLS. It works on Windows. In WSL, the proxy root CA must be added to the system trust store (an operator step). With that CA, both home.treasury.gov and api.openai.com verified (`openssl s_client -CAfile`).

## Rest-of-day range from the live quote (2026-10-23)

**Question:** with the live Groww quote, can the app forecast what is left of today? Direction was already tested on the same live inputs (technical agent replay: 53–59% right, not profitable after costs). Size is different: volatility persists, both from day to day and within a day.

**Model** (`app/research/intraday_range.py`; trained by `run_intraday_range` / `cli intraday-range`; served by `GET /api/research/intraday-range`):
- **Target**, at each checkpoint (09:30 … 15:15, after k of the 25 regular 15-minute bars): the log of the rest-of-day range including the current price. It also gives the rest-of-day high above the price, the low below it, and the close relative to it.
- **Inputs** (only what the live quote and saved history supply):
  - previous daily log ranges (1 / 5 / 22-day);
  - today's range so far;
  - |gap| and |move from the previous close|;
  - the previous India VIX close.
- **Candidates**:
  - `naive_prev_day`: yesterday's range scaled to the time left;
  - `so_far_scaled`: today's range so far, scaled;
  - `har_intraday`, `har_intraday_vix`: OLS per checkpoint.
- **Evaluation**: walk-forward by session, selection on the development period, holdout reported once. The Diebold–Mariano test uses per-session mean loss, because the 24 rows of one session are not independent. Bands are quantiles of development errors.
- **Live refusals** (no forecast is shown):
  - `MARKET_CLOSED`, `PRE_OPEN`, `NO_SESSION_TODAY` (the quote repeats the last session);
  - `NO_LIVE_QUOTE`, `STALE_QUOTE` (> 180 s);
  - `HISTORY_BEHIND` (saved last close ≠ Groww's previous close by > 0.05%, or the VIX history is behind), `HISTORY_MISSING`;
  - `MODEL_MISSING`.

**Result** (1,656 complete sessions 2020-01-31 → 2026-10-23; holdout 235 sessions from 2025-11-11):
- **Selected:** `har_intraday_vix`. Holdout MSE of the log range was 0.187, against 0.799 for `naive_prev_day` (−77%, DM p < 0.001) and 0.245 for `so_far_scaled` (−23%, DM p < 0.001).
- **Holdout coverage**, averaged over checkpoints:
  - range: 68% band 69%, 90% band 91%;
  - rest-of-day high under its 90% level: 89%; low above its 90% level: 87%;
  - close 90% band: 87%.
- **Weak spot:** the last checkpoint (15:15) under-covers; the close 90% band held 78%. This is the closing period, and the card flags any 90% band below 85% at the current checkpoint.
- **Replay of 23-Oct-2026** (day-so-far inputs from the 15-minute bars):

  | Time | Forecast | Actual |
  |---|---|---|
  | 10:15 | 1.02% | 1.02% |
  | 12:15 | 0.82% | 1.02% |
  | 14:15 | 0.51% | 0.65% |

  At all three times the rest-of-day high and low stayed inside the 90% levels.

**Extended to BANKNIFTY and SENSEX (2026-10-23):** each index has its own model, trained only on its own history, and India VIX is the volatility input for all three. The live quotes come from two new read-only allowlist entries, `NSE/CASH/BANKNIFTY` and `BSE/CASH/SENSEX` (`INDEX_QUOTE_PARAMS`). They are range-checked like NIFTY. A rejected SENSEX quote also drops its unchecked LTP.

| Index | Sessions | Holdout | Error vs yesterday-scaled | vs so-far-scaled | 90% range band held | High / low within p90 | Close 90% |
|---|---|---|---|---|---|---|---|
| NIFTY | 1,656 | 235 (from 2025-11-11) | −77% (p<0.001) | −23% (p<0.001) | 91% | 89% / 87% | 87% |
| BANKNIFTY | 1,655 | 234 (from 2025-11-12) | −54% (p<0.001) | −25% (p<0.001) | 91% | 91% / 91% | 90% |
| SENSEX | 986 | 85 (from 2026-06-22) | −68% (p<0.001) | −27% (p<0.001) | 90% | 95% / 88% | 88% |

- **SENSEX:** Groww's history starts in Sep-2022, so its holdout is only 85 sessions and its coverage numbers are less certain.
- **MCX crude:** no model. Groww's historical API does not serve MCX, so a crude model cannot be tested.
- **Replay of 23-Oct** at 10:15, 12:15 and 14:15: the rest-of-day high and low of all three indices stayed inside the 90% levels at every checkpoint.

## First unseen sessions and the live forecast log (2026-10-28)

**Out-of-sample check on 26 and 27 Oct.** The models were trained, and the daily forecast made, on data up to 23-Oct. The app itself was down over these days, so the forecasts were rebuilt from the data that existed at the time.
- **Next-session NIFTY range:**
  - 26-Oct: forecast 2.07%, actual 1.90%;
  - 27-Oct: forecast 2.09%, actual 2.14%.
  Both were inside the 68% band. Direction (P(up) 0.54, the base rate) went up one day and down the other.
- **Rest-of-day** (48 checkpoints per index):

  | Index | Range in 90% band | High under 90% level | Low above 90% level | Typical size miss |
  |---|---|---|---|---|
  | NIFTY | 98% | 92% | 98% | ±20% |
  | BANKNIFTY | 96% | 100% | 98% | ±33% |
  | SENSEX | 98% | 94% | 100% | ±20% |

- **Close 68% band:** held on only 48–58% of checkpoints.
- **Sample:** two sessions; the checkpoints within a day are not independent.

**Live forecast log** (`app/research/forecast_log.py`, `var/analysis/forecast_log.jsonl`): the stronger test is what the cards actually showed.
- **Daily:** published next-session forecasts are logged once per target session, before it opens.
- **Intraday:** the poller logs each index's rest-of-day forecast within 2 minutes of every checkpoint.
- **Scoring:** after each history fetch and research run, against completed sessions only. Records are never edited except to add their outcome once.
- **Where to see it:** `GET /api/research/forecast-track-record` and the Forecast Track Record card. The card marks fewer than 20 sessions as too early to judge.
- **Tests:** an autouse fixture keeps them away from the real log.
