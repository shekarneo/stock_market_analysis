# Options expected-value specification

**Status:** Chain schema, selection, pure pricing checks, and a research proposal contract exist. Candidate expected net stays unavailable. This is a modelled estimate, not a guaranteed P&L.
**Parent:** `docs/DESIGN.md`
**Requires:** a frozen underlying forecast from `docs/FORECASTING_AND_BACKTEST_SPEC.md`, a current instrument-master row, and a current quote. Historical option-chain snapshots are **not** assumed to exist.

Predicting that the index rises does not establish that a call is profitable, and it does not mean `BUY_CE`. A falling forecast does not mean `BUY_PE`. Premium, spread, theta, IV, and charges can consume the move.

The valuation service is deterministic Python. It is not a LangGraph node and it does not read agent prose as a number. If a required input is missing or its unit is unverified, the result is `UNAVAILABLE` or `INSUFFICIENT_DATA`. Historical option backtests stay off until `docs/DATA_SOURCE_MATRIX.md` records a verified history of expired contracts, prices, and expiries.

---

## 1. Pipeline order

1. Underlying forecast for one task.
2. Eligible contracts from the current chain and instrument master.
3. Lot count from the sizing formula in `docs/RISK_AND_EXECUTION_SPEC.md`. If the count is below 1, the decision is `NO TRADE` and no expected net is invented.
4. Modelled option outcomes at that quantity, under the method rules below.
5. Comparison with `NO TRADE`.
6. Full risk-engine pass on the survivor.
7. Execution, only for a proposal whose status is `COMPLETE` and whose risk result is `PASS`.

Stages 3 and 4 are deterministic code. A Cursor agent may explain the chosen row. It may not change the estimate, the rank, or the decision.

---

## 2. Contract record

Every candidate stores, from the current official instrument metadata and a current quote:

| Field | Source rule |
|---|---|
| Underlying, CE or PE, strike, expiry | Instrument master. Expiry is a date on that row, not a weekday assumption. |
| Broker instrument id (`trading_symbol`, and `groww_symbol` when present) | Same row. |
| Lot size, tick size | Same row. Never a constant in code. |
| Premium used for entry and for expected net | The ask. Chain LTP is display-only and is never copied into this field. |
| Bid, ask, quote timestamp | `get_quote` or an equivalent verified quote. Absent bid or ask rejects the candidate. |
| Volume, open interest, IV, delta, gamma, theta, vega | Used when the provider sent them. Null stays null. |

Groww's documented `get_option_chain` response, as read on 14 Oct 2026, includes LTP, volume, open interest, and greeks. It does not include bid and ask. Those must be read from the quote method for each shortlisted contract. See `docs/DATA_SOURCE_MATRIX.md`.

If the master row and the quote disagree on symbol, expiry, strike, or option type, the candidate is rejected.

Stale or missing premium, bid, or ask rejects the candidate. Nothing is interpolated.

### Tick size

The instrument CSV documents `tick_size`, and the instruments page says prices are in rupees. The sample equity row shows `tick_size` of `5` for RELIANCE, which does not match the usual rupee tick of 0.05. The unit is **unverified**. Until a read-only check shows how a live quote increments relative to `tick_size`, live orders stay blocked. Paper mode may round only inside a fixture whose unit is labelled on the fixture.

---

## 3. When an estimate is allowed

| Inputs available | Method | Label on the proposal |
|---|---|---|
| Vendor delta, gamma, theta, vega, IV, plus bid and ask, plus frozen class-conditional underlying returns | Local greek approximation below | `MODELLED_VENDOR_GREEKS` |
| IV and an underlying price, but no greeks, and the contract spec confirms European exercise | Black-76 below | `MODELLED_BLACK76` |
| Anything less | No expected value | Candidate cannot be selected. `NO TRADE` if no other candidate qualifies. |

Vendor greeks are the vendor's model. They are inputs, not our calibration.

Black-76 is enabled only when the stored contract specification says the option is European. If the specification does not say that, Black-76 stays off. This design does not treat "index option" as proof of exercise style.

Both methods are local and wrong for large jumps. If the frozen class-conditional move has absolute return above a configured bound, that node is marked `EXTRAPOLATED`. If the probability of extrapolated nodes exceeds a configured research gate, the candidate's expected value is **unavailable**, not clipped into a confident number.

There is no historical option backtest until per-contract history, including expired contracts, is verified. The matrix currently marks that history unverified.

---

## 4. Scenario method

Let the approved forecast supply `p_up`, `p_range`, `p_down` and the frozen training-fold mean simple returns `r_up`, `r_range`, `r_down`.

Underlying nodes: `S * (1 + r_k)` for `k` in `{up, range, down}`, with probability `p_k`.

IV nodes: `0`, `+v`, and `-v` volatility points, where `v` is a configured stress, labelled `ASSUMED_STRESS`. It is not a forecast of IV. Each IV node is combined with each underlying node. IV-node probabilities are **not** invented. The reported expected value used for ranking is the `v = 0` slice. The `+v` and `-v` slices are adverse and favourable sensitivities, shown separately. They do not get folded into the headline expected value unless an IV model with its own validated probabilities exists. None exists in this design.

Time: from the quote timestamp to the task endpoint, in the vendor greek's own time unit. If the vendor does not document whether theta is per day, the greek method is unavailable. That unit is unverified for Groww until their greek docs are confirmed in implementation; the chain page describes theta as time decay and does not state the time unit. Until the unit is confirmed, `MODELLED_VENDOR_GREEKS` is disabled and only Black-76 with an explicit year fraction may run.

### 4.1 Vendor-greek approximation

For underlying move `dS`, IV move `dσ` in the same units as vega, and time `dt` in the theta unit:

```text
dPremium = delta * dS + 0.5 * gamma * dS^2 + theta * dt + vega * dσ
modelled_premium = max(0, quoted_mid + dPremium)
```

`quoted_mid = (bid + ask) / 2` at the quote timestamp.

This is a Taylor approximation around the quote. It is not a future print.

### 4.2 Black-76

Used only under the European-spec rule. Forward `F` is the current underlying index level, which is an assumption and is labelled as such: index options are often priced off the future, and this design does not yet have a verified futures series. If a verified matching future is configured, `F` is that future. If not, Black-76 is disabled rather than silently using the spot.

Discount and rate come from configured inputs. If no rate source is enabled, Black-76 is disabled.

```text
modelled_premium = max(0, Black76(F, K, σ, T, rate, type))
```

`σ` is the vendor IV converted to the decimal convention the formula expects. If the feed's IV scale (percent versus decimal) is ambiguous, the method is disabled. Groww's chain text says IV is a percentage. Implementation must still check a live value before dividing or not dividing.

### 4.3 Fills, charges, exits

| Item | Assumption |
|---|---|
| Entry | Pay the ask. |
| Exit | Sell at the modelled premium minus at least the observed half-spread, and not below zero. |
| Charges | Prefer Groww `get_order_margin_details` fields `option_buy_premium` and `brokerage_and_charges` for that order. |
| Paper fallback | A config charge schedule labelled `OPERATOR_SCHEDULE_UNVERIFIED`. Live mode does not use it. |
| Slippage | The half-spread haircut above. An extra configured tick penalty is allowed only when tick units are verified. |
| Partial fill | Expected value uses the full proposed quantity. A partial fill is an execution event, not a better backtest. |
| Stop | Not a fill price. The scenario does not assume the stop trades at the stop. |
| Time stop | Exit valuation at the task endpoint, using the same method. |

```text
gross = (exit_fill - ask) * quantity
net = gross - charges
```

`quantity` is lot size times lot count, from the risk engine's sizing formula. The options engine does not choose a larger size to improve the estimate.

Headline figures, each labelled `MODELLED`:

- Expected gross and expected net on the `v = 0` slice: `sum_k p_k * net_k`.
- Modelled probability of `net > 0` on that slice.
- Modelled probability of `net` at or below the configured loss display threshold.
- Adverse slice: the `+v` or `-v` node with the worse expected net, shown beside the headline, not averaged in.
- Premium at risk: `ask * quantity + charges`. For a long option this is the loss if the option expires worthless or cannot be sold. It is not a prediction that the loss will be smaller because a stop exists.
- Sensitivities: the three underlying nodes and both IV stresses, as a table.

If charges cannot be computed, expected net is null and the proposal is `INCOMPLETE`.

---

## 5. Ranking

Eligibility constraints, all required, none of them score weights:

- Quote age inside the entry limit.
- Bid, ask, and premium present.
- Spread at or below the configured maximum. The maximum is a research gate, not a proven liquidity edge.
- Volume and open interest at or above configured floors, same caveat.
- Expiry on the configured allow-list.
- Lot size and tick size present on the master row.
- An allowed pricing method from section 3.
- Expected net available.

Among eligible contracts, the rank key is expected net on the `v = 0` slice. There is no weighted score of spread, delta, and IV.

`NO TRADE` has expected net of zero. A candidate is selectable only when its expected net is strictly greater than zero. If every candidate is at or below zero, or none are eligible, the decision is `NO TRADE`. The highest score among unattractive contracts is not a trade.

The Cursor explanation may discuss the winner. It may not reorder the list.

---

## 6. Proposal

`decision` is only `BUY_CE`, `BUY_PE`, or `NO_TRADE`. `INCOMPLETE` is a status, not a fourth decision.

`BUY_CE` and `BUY_PE` are conditional. They still require the entry trigger, a risk-engine pass, and the approval rule for the current mode. They are not an instruction to send an order immediately.

If any field required for a buy decision is missing, `decision` stays `NO_TRADE` or is cleared to `NO_TRADE`, and `status = INCOMPLETE`. The execution service will not submit an `INCOMPLETE` proposal. A qualitative forecast is `NO_TRADE` with status `COMPLETE` and a recorded reason. It is not `INCOMPLETE`.

| Field | Required |
|---|---|
| Decision and status | Yes |
| Underlying and horizon | Yes |
| Forecast probabilities, model version, promotion state, or an explicit qualitative flag | Yes. Qualitative forces `NO_TRADE`. |
| Contract symbol, strike, expiry, CE/PE | Yes for a buy decision |
| Premium, bid, ask, quote timestamp | Yes for a buy decision |
| Entry condition and order type | Yes for a buy decision |
| Lot count, quantity, lot size | Yes for a buy decision |
| Premium outlay, charges, slippage assumption | Yes for a buy decision |
| Expected net, the method label, and the assumption list | Yes for a buy decision |
| Adverse IV slice | Yes for a buy decision |
| Risk budget and premium at risk | Yes for a buy decision |
| Invalidation, exit rule, time stop | Yes for a buy decision |
| Why this contract, and the contrarian counterargument | Yes for a buy decision |
| Risk-engine result | Yes. `VETO` forces the executable decision to `NO_TRADE`. |

`NO_TRADE` still records the reason: no eligible contract, expected net not positive, qualitative forecast, fusion not required for this path, risk veto, or incomplete data.

## 7. Input gate

`apps/api/app/options/validation.py` checks a candidate before any valuation code exists. It accepts three origins and keeps them separate: `UNVERIFIED_MARKET_INPUT`, `SYNTHETIC_FIXTURE`, and `CALCULATED`. A calculated value is rejected as a quote. A synthetic fixture stays unverified. The check does not fetch a chain and does not read quarantined candles.

Strike, underlying price, bid, and ask must be positive finite numbers. The ask must be at least the bid. An entry premium, when supplied, must equal the ask. Last price is not copied into the premium. Expiry must be a real `YYYY-MM-DD` date on or after the quote's own calendar date. A weekday name is not an expiry. The quote timestamp must include an offset. Volatility must name `PERCENT` or `DECIMAL`. An interest rate must name `ANNUAL_DECIMAL` and `CONFIGURED_INPUT`. Null greeks stay null.

A candidate that passes these checks still has pricing status `UNAVAILABLE`, no premium, no expected net, and decision `NO_TRADE`. The four readiness flags stay false. Passing validation does not mean the premium matches a Groww premium.

## 8. Chain snapshot and synthetic fixture

`apps/api/app/options/schema.py` and `validate_option_chain` accept one chain. The chain carries an underlying, one expiry date, one underlying price, a quote timestamp, an optional retrieval timestamp, and a list of contracts. Each contract carries CE or PE, strike, bid, ask, optional last price, and optional volume, open interest, volatility, and greeks. `trading_symbol`, `groww_symbol`, lot size, and tick size stay null unless the caller supplied them. The schema does not contain an exchange field.

`synthetic_nifty_chain` returns six NIFTY contracts, strikes 25000, 25100, and 25200, each with CE and PE. The chain and every contract are labelled `SYNTHETIC_FIXTURE`. The bid, ask, and last-price numbers are fixed test values. They are not a market observation and they are not a model premium. Broker symbols, lot size, tick size, volume, open interest, and greeks are null. The fixture is reproducible: two calls return the same contents.

A chain whose contracts disagree on origin, underlying, expiry, underlying price, or quote timestamp is rejected. An empty list, a non-list, and a non-object contract are rejected. Last price is not copied into the entry premium. A chain that passes still has pricing status `UNAVAILABLE`, expected net null, and decision `NO_TRADE`, because this stage has no approved forecast and neither pricing method is enabled. No options route or scanner page was added.

### Ambiguities left as stated

- The options spec names a quote timestamp and does not name its timezone. The gate requires an offset and does not convert the timestamp to Asia/Kolkata.
- Option-quote eligibility uses `freshness.option_block_seconds`. Index quotes in the market snapshot, and the risk spec's entry-age gate, use `risk.quote_max_age_seconds`. The two settings are both 15 in the current defaults. Changing one does not change the other.
- Contract identity for selection is underlying, expiry, strike, and CE or PE. `trading_symbol` and `groww_symbol` are Groww provider fields and stay null unless supplied. `broker_symbol` is the design alias: when both it and `trading_symbol` are present they must match, and it is not copied into `groww_symbol`.
- The design record lists a bare `iv` number. The spec requires an explicit percent or decimal scale, so a bare number is rejected. The fixture leaves volatility null.
- The spec's ranking rules mention a spread maximum, volume and open-interest floors, and an expiry allow-list. No such values are configured. Those gates are not applied.
- The spec does not say whether a quote timestamp may be later than `retrieved_at`. The gate does not reorder the two timestamps.
- Lot size and tick size remain null on the fixture because the spec forbids a code constant. A ranking rule that requires them cannot pass yet.

## 9. Selection and pricing gates

`select_contract` picks one contract from a chain that has already passed validation. The caller supplies the underlying, CE or PE, expiry, and either an exact strike or the rule `NEAREST_UNDERLYING`. The nearest rule uses the chain's own underlying price. An equal distance is an ambiguous match and returns no contract. A missing match, a stale quote, mixed provenance, or an invalid chain also returns no contract. The selected row keeps its origin. A synthetic fixture stays `market_observation: false`. An unverified market input is not marked verified. The decision stays `NO_TRADE`. Selection does not rank by expected net.

`price_contract` names the two documented methods, `MODELLED_VENDOR_GREEKS` and `MODELLED_BLACK76`. Both stay `UNAVAILABLE`. Vendor Greeks need delta, gamma, theta, vega, labelled volatility, bid, and ask, plus a verified theta time unit and an approved forecast. Black-76 needs labelled volatility, strike, underlying price, option type, and a year fraction, plus a verified European exercise style, a verified matching future, an enabled rate source, and an approved forecast. None of those assumptions are verified in this repository. A caller-supplied assumption does not turn a method on. The premium and expected net stay null. The pricing result is labelled `CALCULATED` and cannot be stored as a quote.

## 10. Formula verification

The pure functions in `apps/api/app/options/formulas.py` are mathematical checks. They do not read a chain, a forecast, or a provider. A successful result has origin `CALCULATED`, `usable_as_quote` false, production status `UNAVAILABLE`, expected net null, and decision `NO_TRADE`. The four readiness flags stay false. `price_contract` does not call these functions, so a chain spot is not used as a forward.

Black-76 is calculated only when the caller supplies an explicit test forward, decimal volatility, time in years, and a rate named `ANNUAL_CONTINUOUS` with convention `CONTINUOUS`. The discount is `exp(-rate * time_years)`. The undiscounted value is the Black (1976) call `F N(d1) - K N(d2)` or put `K N(-d2) - F N(-d1)`, with `d1 = (ln(F/K) + σ²T/2) / (σ√T)` and `d2 = d1 - σ√T`. At zero time or zero volatility the formula uses the discounted intrinsic value, because the normal formula would divide by zero. The result is floored at zero. An independent reference for forward 100, strike 100, one year, volatility 0.20, and rate 0.05 is call 7.5770821464 and put 7.5770821464. Call minus put equals the continuous discount times forward minus strike.

The vendor-Greek step is the spec expression `delta * dS + 0.5 * gamma * dS² + theta * dt + vega * dσ`, added to `(bid + ask) / 2` and floored at zero. Theta's unit and vega's unit must be named by the caller and are not converted. A named test unit does not verify Groww's theta unit. A hand check with mid 11, delta 0.5, gamma 0.02, theta -0.1, vega 0.3, dS 2, dt 1, and dσ 0.01 gives 11.943.

These calculations do not establish a live premium or a trading edge.

### Conventions the spec leaves unresolved

- The spec names `Black76(F, K, σ, T, rate, type)` and does not write the normal formula or the compounding rule. Only an explicitly selected continuous convention is calculated.
- The spec does not say that the index level may be used as `F`. A forward source of spot or underlying is rejected.
- Groww's theta time unit is unverified. The Taylor step does not convert days and years.
- The spec says the volatility move uses vega's unit. It does not say whether that unit is one decimal or one percentage point. Mismatched names are rejected, and no conversion is applied.
- A labelled decimal volatility on a fixture is not a live scale check, so production Black-76 stays off.
- Expected net needs an approved forecast, charges, and a lot size. None of those are produced here.

## 11. Expected net and ranking

The specified headline on the zero-stress slice is `sum_k p_k * net_k`, with `gross = (exit_fill - ask) * quantity` and `net = gross - charges`. `combine_scenario_nets` calculates that sum only when the caller supplies the three scenario probabilities and the three scenario nets. The unit is the currency of the ask and the charges. The result is labelled `CALCULATED`, cannot be stored as a quote, and has decision `NO_TRADE`.

`evaluate_expected_value` does not build those scenario nets. It returns `UNAVAILABLE`, leaves modelled value, gross expected value, charges, and expected net null, and decides `NO_TRADE`. A quoted ask is recorded only after the existing quote gate accepts the bid and ask. A positive class-conditional return is not turned into a call or put profit.

### Inputs the current contracts do not provide

- The implemented forecast artifact is `binary-1`, the next M15 close-to-close sign. It does not emit `p_up`, `p_range`, `p_down`, or the frozen training-fold means `r_up`, `r_range`, and `r_down`. `APPROVED_FOR_RESEARCH` is not `APPROVED_FOR_PAPER` or `APPROVED_FOR_LIVE`. A direction probability is not a price forecast.
- No task horizon is stored on the option contract. A caller must name the task horizon. A different forecast horizon is a mismatch. The module does not invent one.
- Both production pricing methods stay unavailable. Black-76 has no verified matching future, so the index level is not used as the forward. Vendor Greeks have no verified theta time unit, so the step from quote time to the task endpoint is not calculated.
- `config/defaults.yaml` has `risk_capital_inr: null` and no charge schedule. A missing charge stays missing. A supplied charge, including zero, is not applied, because no schedule is configured. The spec does not say that total charges equal `charges_per_lot * lot_count`; that product is not calculated.
- Lot size is not on the synthetic fixture and is not inferred. The configured spread maximum, volume floor, open-interest floor, expiry allow-list, IV stress `v`, and extrapolation bound are still absent, so those gates are not applied.

`rank_candidates` orders only rows whose expected net was supplied as an explicit test input and whose identity is unique. The order is expected net descending, then underlying, expiry, strike, and CE or PE. Synthetic, quarantined, duplicate, and unavailable rows are rejected. The decision remains `NO_TRADE`. A ranked row is not an order and does not change an approval flag.

## 12. Research proposal contract

`build_research_proposal` records one candidate in schema `m8-proposal-1`. It keeps these quantities separate: the quoted ask and its origin, the modelled value, the forecast and its promotion state, scenario probabilities and class-conditional assumptions, gross expected value, charges and their source, expected net, contract identity with lot size and quantity, risk-gate results, research-candidate status, and paper and live approval. Paper and live approval stay false. `APPROVED_FOR_RESEARCH` is recorded as research selection. A forecast object that names `APPROVED_FOR_PAPER` or `APPROVED_FOR_LIVE` is recorded as a claim, and that claim does not set either approval flag.

The decision is `NO_TRADE`. A qualitative forecast has status `COMPLETE` and reason `QUALITATIVE_FORECAST`. Every other current candidate has status `INCOMPLETE` because a buy field is missing. Expected net stays null. A missing charge is not stored as zero. Lot size is not inferred, and quantity and lot count stay null. A calculated premium is stored only as a rejected calculated input. Ranking sets `ranked` and adds `RANK_IS_NOT_AN_ORDER`; `executable` stays false. The function does not call the order entry point.

Risk result is `VETO`. Expected net, forecast approval, and charges are applied vetoes. Mode, kill switch, calendar, funds, exposure, position limits, and reconciliation are `NOT_EVALUATED` because this milestone does not read those stores. Spread, volume, open interest, expiry allow-list, IV stress, and the extrapolation bound are `NOT_CONFIGURED` and are not applied. The configured structure allow-list is applied. A caller-supplied risk `PASS` is refused while those vetoes remain.

The spec's statement that a completed `NO_TRADE` has expected net of zero applies only after an expected net has been calculated and is not strictly positive. A missing estimate remains null. It is not replaced with zero.
