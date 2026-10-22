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
