# Risk and execution specification

**Status:** A local ledger, gate evaluation, and a paper state machine exist. Paper trading is not activated, fills are not applied, and live routing stays disabled. These controls do not cap a loss at the stop price, and they do not make trading loss-free.
**Parent:** `docs/DESIGN.md`
**Companions:** `docs/OPTIONS_EXPECTED_VALUE_SPEC.md`, `docs/DATA_SOURCE_MATRIX.md`

The risk engine and the execution service are deterministic. No prompt, news item, LangGraph node, model score, or agent output can change a limit, clear a veto, or place an order. The paper broker does not import the live order function. Live submission stays disabled until the M14 gate in `docs/IMPLEMENTATION_PLAN.md`. The percentages below are starting configuration, not measured optima.

---

## 1. Gates

`evaluate` returns one row per gate. Any failure vetoes the intent. The check runs at proposal time and again immediately before submit.

1. Mode allows the action. `PAPER` cannot call the live order function. `LIVE_TRADING` requires the config flag, the server flag, and a confirmation that is still valid.
2. Kill switch is off for new entries.
3. The exchange calendar says the market is open and the instrument master says the contract is tradable (`buy_allowed` when that field is present).
4. The quote is present and younger than the configured entry age. Option-chain eligibility uses `freshness.option_block_seconds`. This risk gate, and the index-quote block in the market snapshot, use `risk.quote_max_age_seconds`. Those settings are separate.
5. Symbol, expiry, strike, CE/PE, lot size, and tick size match the pinned instrument-master row. Tick **unit** must be verified before a live submit (`docs/OPTIONS_EXPECTED_VALUE_SPEC.md`).
6. The pinned model version is `APPROVED_FOR_PAPER` in paper mode or `APPROVED_FOR_LIVE` in live mode, for this underlying, horizon, feature schema, and strategy revision. `model_health` is `HEALTHY`. A qualitative forecast fails this gate. Research selection does not satisfy the gate.
7. Broker funds cover the requirement in section 2, using `option_buy_balance_available` for a long option when that Groww field is present. A missing funds read fails closed in live mode.
8. Per-trade and aggregate exposure, including reservations, fit in the budgets.
9. Open-position count, session entry count, daily-loss lockout, drawdown lockout, and cooldown are inside policy.
10. Spread, volume, and open interest pass the configured floors. Those floors are research gates, not proven optima.
11. Expected net is available and strictly greater than zero. A missing estimate fails. There is no override that trades the "best" negative contract.
12. Entry condition, invalidation, exit rule, and time stop are non-empty.
13. No intent is in `UNKNOWN_REQUIRES_RECONCILIATION`. Broker positions match local positions for this account.
14. The contract is on the allow-list. Default allow-list is long NIFTY and long BANK NIFTY options. SENSEX options stay off until a master row for that contract has been read.

There is no discretionary live bypass. A proposal that does not carry an approved model for its horizon fails gate 6.

Quote age for gate 4 ships at 15 seconds. That is the same default as `docs/DESIGN.md`. It is a freshness policy, not a measured optimal age.

### 1.1 Exits are not new entries

An `EXIT` intent does not run gates 6, 8, 9, 10, 11, or 12. Those gates would block closing a loser or closing during a lockout. An exit still requires a known position, a typed intent, confirmation, and gates 1, 3, 4, 5, and 13. The kill switch (gate 2) blocks new entries and does not by itself block the exit workflow. A confirmed exit that is requested while the market is closed waits in `AWAITING_APPROVAL` until gate 3 passes. It is not priced from a stale quote.

In `PAPER`, gates that say "broker" use the paper ledger. Groww is not read. `REPLAY` cannot create an entry or an exit.

---

## 2. Position sizing

Risk capital is a configured rupee amount. It is not Groww's balance and not `clear_cash`.

```text
trade_risk_budget = risk_capital * max_risk_fraction_per_trade
one_lot_risk = ask * lot_size + charges_per_lot
lot_count = floor(trade_risk_budget / one_lot_risk)
quantity = lot_count * lot_size
premium_outlay = ask * quantity
```

`max_risk_fraction_per_trade` ships as `0.01` in `config/defaults.yaml`. That is a conservative starting policy, not a result from this project's data.

If `lot_count < 1`, the decision is `NO TRADE`. The engine does not round up to one lot.

For a long option the sized risk is the premium outlay plus charges, because that is what can be lost if the option expires worthless or cannot be sold. A stop is an exit plan. It is not an input to `one_lot_risk`.

Charges prefer Groww `get_order_margin_details.brokerage_and_charges` for that order. Live mode fails closed when the call fails. Paper mode may use a config schedule labelled `OPERATOR_SCHEDULE_UNVERIFIED`.

Cash buffer:

```text
live deployable = option_buy_balance_available * (1 - cash_buffer_fraction)
paper deployable = paper_cash * (1 - cash_buffer_fraction)
```

`paper_cash` starts at the configured risk capital and then follows paper fills. It is not a Groww balance. A missing Groww funds read fails closed in live mode and is ignored in paper mode. `cash_buffer_fraction` ships as `0.20`, a starting policy, not an optimized reserve. `premium_outlay + charges` must be less than or equal to the mode's deployable amount and less than or equal to the remaining aggregate budget. Aggregate budget is `risk_capital` minus reserved and open premium-at-risk.

The engine never increases size after a loss and never adds to a loser to change the average.

---

## 3. Daily loss, reservations, and concurrency

### 3.1 Daily loss

For the current exchange session date:

```text
session_pnl = realized_pnl
            + unrealized_mark
            - charges_already_booked
            - estimated_exit_charges_on_open_long_options
```

`daily_loss_includes_unrealized` defaults to true. Unrealized mark for a long option is `(bid - average_entry_ask) * filled_quantity` when a fresh bid exists. If the bid is stale, unrealized is treated as a full premium loss for the lockout test only, so a dead quote cannot hide a drawdown. That conservative mark is labelled on the risk page.

Groww's documented position payload includes `realised_pnl` and does not show an unrealized field. Local unrealized mark is computed from the quote. It is not copied from an undocumented broker field.

Lockout triggers when `session_pnl <= -risk_capital * daily_loss_fraction`. The shipped fraction is `0.02`, a starting policy.

The lockout row stores `session_date`, `active`, `reason`, and `config_revision`. It survives restart. A new calendar date does not clear it until the worker has read the exchange calendar and confirmed the new session date. Clearing it early is a separate audited action. It is not a button on the order ticket.

Drawdown lockout uses the same ledger from a configured high-water mark of session PnL. The default in `config/defaults.yaml` is disarmed until the operator sets a fraction.

### 3.2 What counts as exposure

| State | Exposure reserved |
|---|---|
| Open long-option position | Premium at risk of the filled quantity |
| Pending or partially filled entry | Full remaining order quantity at its limit or ask, plus charges, until the order is filled, cancelled, or reconciled |
| Partial fill | Filled quantity is position exposure. Unfilled quantity stays reserved until reconciliation shows it gone. |
| Exit order working | Does not free the reserve until the broker position quantity has fallen |

If broker `realised_pnl` disagrees with the local ledger by more than a configured rupee tolerance, new entries stop until a person accepts a reconciliation adjustment. The tolerance is an accounting setting.

### 3.3 One budget

All workers share one ledger row per session, updated in a transaction:

```text
BEGIN
SELECT ledger FOR UPDATE
re-read positions and working orders
apply the formulas
insert a reservation linked to the intent id, or veto
COMMIT
```

A second transaction that sees the reservation cannot spend the same remainder. The worker lease stops two submitters. The ledger stops two approvers. Both are required.

Restarting a worker does not delete reservations. Startup reconciliation either attaches them to broker orders or voids them only after the broker order list shows no matching `order_reference_id`.

---

## 4. Kill switch and exits

The kill switch blocks every new entry as soon as the row is written. It does not cancel or close positions by itself.

Closing or reducing an existing position is a separate intent with `intent_purpose = EXIT`. It still goes through the execution service, still reconciles, and still requires a confirmation. It does not require unused entry budget. It does require a known position. If the quote is stale, the exit stays `AWAITING_APPROVAL` with the stale-quote warning visible. The system does not invent a marketable price.

| Event | New entries | Existing position |
|---|---|---|
| Broker disconnect | Block | Leave the last reconciled broker snapshot visible and labelled stale. Do not trade off it. |
| Stale quote or dead market-data feed | Block | Do not mark a stop as filled. |
| Unknown order state | Block | Reconcile by `order_reference_id` and `groww_order_id` before any new submit. |
| Partial fill | No further quantity on that intent | Track filled quantity only. |
| Rejected entry | No position | Reservation released. |
| Cancel failure | Block | Keep the order working until status says cancelled or filled. |
| Exit rejection | Block new entries | Alert. Do not send a second exit until reconciliation. |
| Gap through a stop | Block | The fill can be worse than the stop. Premium at risk is the long-option bound only while the position is still held. |
| Restart with an open order | Block until reconciliation | Resume from the broker. Do not place the order again. |
| Restart with an open position | Block until positions match | Position monitor resumes. It does not submit a second entry. |

---

## 5. Order state machine

```text
PROPOSED
  -> RISK_APPROVED
  -> AWAITING_APPROVAL     live, while confirmation is required
  -> SUBMITTED
  -> PENDING or OPEN
  -> PARTIALLY_FILLED
  -> FILLED
  -> EXIT_PENDING
  -> CLOSED

Alternates: VETOED, REJECTED, CANCELLED, UNKNOWN_REQUIRES_RECONCILIATION
```

Every transition is validated against an allow-list and stored as its own row. An illegal transition throws and writes an audit event.

`AWAITING_APPROVAL` is skipped only in `PAPER`, or when the operator has separately enabled unattended live mode. Unattended mode is off in the shipped config. It still runs section 1 at submit time.

Timeout after the place call returns `UNKNOWN_REQUIRES_RECONCILIATION`. The next step is `get_order_status_by_reference`, then `get_order_list` and `get_positions_for_user`. A new place call is forbidden while the intent is unknown.

Groww's documented `order_reference_id` is 8 to 20 characters, alphanumeric, with at most two hyphens. A UUID does not fit. The execution service stores a generated reference in that shape. If that lookup is later found not to work for F&O, the capability matrix moves the feature to `UNSUPPORTED` and live entries stay off.

Paper mode uses the same states and the same sizing formulas. Its fill model buys at the ask and sells at the bid minus the configured paper haircut. The paper broker module must not import the Groww place, modify, or cancel functions.

On process start, reconciliation finishes before the scheduler may create an entry.

No code path transfers, deposits, or withdraws funds.

---

## 6. What the broker call is allowed to contain

The execution service accepts a typed intent that already contains the pinned symbol, segment, side, quantity, order type, limit price if any, validity, and the reference id. It does not accept a free-form sentence from an agent.

Live option buys use the product and order type the official F&O docs confirm at implementation time. This specification does not invent an F&O product code. If the verified order schema has no supported product for a long option, live trading stays disabled.

---

## 7. What M9 runs

The local ledger stores `RESERVE`, `RELEASE`, `LOCKOUT_SET`, and `LOCKOUT_CLEAR`. Each applied or refused business event keeps its id, timestamp, session date, contract identity when supplied, quantity, rupee amount, provenance, and the resulting session row. A repeated id does not change the row. A changed payload for an existing id is a conflict and also does not change the row. Provenance must be `CONFIGURED_INPUT`, `LEDGER`, or `OPERATOR_ACTION`. Synthetic and quarantined provenance is rejected. Paper cash is the configured `risk_capital_inr` when that value is set, and null when it is not. Null cash is not replaced with zero.

A reservation is applied only when paper cash and risk capital exist and the explicit rupee amount fits both the cash buffer and the remaining aggregate budget. The session row is locked for the update. Reserved rupees must equal the applied reserve events minus the applied releases. A release must match the intent's remaining reservation and must not be timestamped before that reservation. A second release of the same reservation does not reduce another intent's reserved amount. Reserved rupees and open premium stay non-negative, and their sum cannot exceed configured capital. Open premium stays at zero because no fill or position event exists. Paper cash is not reduced by a reservation and is not changed by an unapplied event. `lot_count` uses the section 2 formula and is `NO TRADE` below one. The formula does not run when ask, lot size, charges per lot, capital, or the risk fraction is missing. No charge schedule is configured, so the exposure gate stays `NOT_CONFIGURED` and does not reserve from a caller-supplied fee.

Session P&L is the section 3.1 sum only when realized P&L, unrealized mark, booked charges, and estimated exit charges are all supplied. A missing term stays null. It is not stored as zero. A fresh bid uses `(bid - average_entry_ask) * filled_quantity`. A bid known to be stale uses the full entry premium as a loss. Unknown freshness does not choose either mark. Estimated exit charges have no schedule, and the ledger has no realized-P&L events, so a session row does not carry a P&L figure.

A lockout row stores the session date, active flag, reason, and config revision. It remains after a new database session. A later date does not clear it, because the exchange calendar is not authoritative. An operator clear is audited only while the lockout is active.

`evaluate` returns one row per gate. Each row is `PASS`, `VETO`, `NOT_CONFIGURED`, `UNAVAILABLE`, or `NOT_EVALUATED`. An exit skips the entry-only gates with `NOT_APPLICABLE`. `UNAVAILABLE`, `NOT_EVALUATED`, and a mandatory `NOT_CONFIGURED` gate block the decision. The drawdown lockout is `NOT_CONFIGURED` and does not block while its fraction is null, because the spec disarms that control. The overall result stays `VETO` while any blocking gate remains. These gates can pass on their own inputs: paper mode cannot call the live order function, a kill switch that was read and is off, a fresh quote under `risk.quote_max_age_seconds`, the entry plan when its four texts are present, and the configured NIFTY and BANKNIFTY long-option allow-list. A configured paper-cash figure does not pass the funds gate, because the order's charge requirement cannot be computed.

| Gate | State while inputs are missing | Why |
|---|---|---|
| Mode `REPLAY`, `LIVE_READ_ONLY`, or `LIVE_TRADING` | `VETO` | Replay cannot trade. Live routing is disabled. |
| Mode absent | `UNAVAILABLE` | The mode was not supplied. |
| Kill switch unread or on | `NOT_EVALUATED` or `VETO` | A missing row is not treated as off. An on switch blocks entries and does not by itself block an exit. |
| Calendar | `NOT_EVALUATED` or `UNAVAILABLE` | No authoritative holiday calendar is configured. A caller-built calendar flag is not accepted. |
| Instrument master and tick unit | `UNAVAILABLE` or `VETO` | A missing master is not inferred. A mismatch vetoes. Tick unit is unverified. |
| Model approval | `UNAVAILABLE` or `VETO` | A missing forecast is unavailable. Research selection and a claimed paper or live state do not approve the model. |
| Funds | `UNAVAILABLE` | Paper cash is null in the shipped config. Even when capital is set, charges are not configured, so coverage cannot be shown. Live funds are not read. |
| Exposure | `NOT_CONFIGURED` | No charge schedule is configured. |
| Session P&L and position limits | `UNAVAILABLE` or `VETO` | P&L inputs are absent. An active lockout vetoes. |
| Drawdown lockout | `NOT_CONFIGURED` | The shipped fraction is null, so the control is disarmed. |
| Spread, volume, and open interest | `NOT_CONFIGURED` | No floors are configured, and none are applied. |
| Expected net | `UNAVAILABLE` or `VETO` | A missing estimate is unavailable. A non-positive estimate vetoes. |
| Reconciliation | `NOT_CONFIGURED` | No broker snapshot or rupee tolerance is configured. |

The paper module uses the section 5 allow-list. `PROPOSED` can be recorded and then `VETOED`. `RISK_APPROVED` is not applied, including when a caller says risk passed. Submission and fills are not applied. `PAPER_TRADING_ACTIVE` stays false. No simulated fill is produced, and nothing is labelled as a market fill. The module does not import the live order function or a Groww client. An M8 research proposal reviewed here stays non-executable even if its payload claims paper approval, live approval, or `executable`. The proposal page is not served: the specified page includes paper submit and live confirm, and neither action is available. Paper activation is a later milestone and has no implemented procedure.

An explicit `POST /api/paper/simulations` request can open one paper intent and run the same risk gates. A sealed synthetic dataset is still vetoed, because the calendar, tick unit, model approval, charges, and reconciliation evidence are absent. The veto is stored and no reservation or fill is written. A quarantined dataset, a broken lineage record, or a missing contract field is rejected before an intent is opened. The buy-at-ask and bid-minus-half-spread prices can be calculated from explicit quotes, and that calculation does not record a fill. The session loop does not run while the holiday calendar is unconfigured and unattended orders are off. `paper_approved` stays false. M10 is not complete: fills, the worker lease, and broker reconciliation are not applied.

M9 can be accepted only when an authoritative exchange calendar, a verified instrument-master row and tick unit, a registry model that has actually reached the required approval, configured risk capital, a configured charge schedule, computable session P&L, a configured reconciliation tolerance with a broker position snapshot, and the later paper-activation rule are all present. The fill model belongs to the next milestone. M9 is not complete.

### 7.1 Offline paper-accounting replay

`replay_paper_accounts` is an in-memory check of explicit events. It is not called by `POST /api/paper/simulations`, it does not import the order function, and it does not insert a ledger row. `PAPER_TRADING_ACTIVE` stays false.

The persisted ledger still accepts only `RESERVE`, `RELEASE`, `LOCKOUT_SET`, and `LOCKOUT_CLEAR`. A `FILL` event is `INVALID_EVENT_TYPE`. The session invariant keeps open premium at zero, local positions at zero, and paper cash equal to configured capital when capital is set. Those rules are why a fill cannot be posted into the ledger yet. Doing so would require a new event type and a migration. That persistence is not implemented.

Invariants the replay does enforce, using only values the caller supplies:

1. An intent id and an aware timestamp are required. Events are applied in timestamp then event-id order, so the same list replays to the same book.
2. A repeated event id with the same payload is skipped. A repeated fill id with a different payload stops the replay and does not change the quantity already applied.
3. A buy adds quantity and sets `average_entry_ask` to the quantity-weighted explicit price. A second buy uses that same average. A sell reduces quantity and does not change the remaining average. A sell larger than the open quantity is `OVERSELL` and is not applied. The allowed book is long only; no short-option quantity is created.
4. Cash moves only when the opening cash, the explicit price, the quantity, and the charge are all present. A buy debits `price * quantity + charges`. A sell credits `price * quantity - charges`. The replay does not compute the ask or the half-spread haircut; the caller must pass the execution price.
5. A fill with `charges_inr` omitted makes booked charges and cash unknown for the rest of the replay. The missing charge is not stored as zero. Open premium for a remaining long quantity is `average_entry_ask * quantity` because both of those inputs are then known. Session P&L stays null. Estimated exit charges have no schedule.
6. A cancel or reject does not remove a quantity already filled. Unfilled quantity is `order_quantity - filled_quantity` only when the order quantity was supplied. Otherwise it stays null.
7. The first invalid event stops the replay. Later events in that list are not applied. The prefix stays visible and is marked stopped.
8. `reconcile_paper_accounts` compares the replay with a separate statement. A missing position, cash, charge, or fill list is an absent-record reason. A null or unparseable statement amount is not a match against a known balance, and a replay that omits its position list is not treated as an empty book. Differing numbers are mismatches. The comparison does not read a broker.
9. The replay has no database transaction. The ledger's own transaction still locks one session row, rolls back an invariant failure, and commits one accepted event. Recovery of a persisted fill after a crash is not defined, because fills are not persisted.
10. Ledger rows that do exist stay append-only: a repeated id does not update the stored event. The replay uses the same idea for its in-memory ids and writes nothing.

These points are not established by the current contracts, so the replay does not guess them: an exchange fee or tax schedule, a verified tick unit, a lot size, a risk-capital amount, a broker position snapshot, a reconciliation tolerance, and a rule for releasing a rupee reservation when a partial fill is cancelled. The trading rule that forbids adding to a loser is a risk-gate concern. This replay does not apply it.

### 7.2 Smallest ledger extension

The persisted book is one `risk_sessions` row per session date and append-only `risk_events`. `apply_event` locks that row, validates the event, mutates the row, checks the invariant, inserts the event, and commits. A failed check rolls the row and the insert back together. `event_id` is the primary key. The same payload returns `DUPLICATE_EVENT` and does not apply again. A different payload for that id returns `DUPLICATE_EVENT_CONFLICT` and does not change the row. `RESERVE` increases `reserved_inr` and does not change paper cash. `RELEASE` decreases that intent's outstanding reservation by the same amount. `LOCKOUT_SET` and `LOCKOUT_CLEAR` change only the lockout fields. After the commit, `reserved_inr` equals the applied reserves minus the applied releases for that session date. Open premium and `local_open_positions` stay zero. When risk capital is null, paper cash is null. When it is set, paper cash stays equal to that capital. The stored snapshot keeps `session_pnl_inr`, `charges_booked_inr`, and `estimated_exit_charges_inr` null. `broker_positions_known` stays false. `paper_accounting.py` does not perform this persistence. It repeats the idempotency idea for an in-memory fill list and does not replace the ledger.

| Decision | Class | Consequence |
|---|---|---|
| Represent a future fill as another immutable `risk_events` row, not a second table | B | One locked session row and one event insert stay in the same transaction. A separate fill table would commit a position without the cash row, or the reverse. |
| Keep `event_id` plus `body_hash` as the idempotency rule | A | A retry of the same fill id is a no-op. A changed payload conflicts and is not applied. |
| Apply the row update and the event insert in the existing transaction | A | An interrupted transaction rolls both back. There is no recovery procedure for a persisted fill, because no fill is persisted. |
| Leave `FILL` outside `EVENT_TYPES` | A | `apply_event` returns `INVALID_EVENT_TYPE` and does not change cash, premium, or positions. |
| Refuse a fill while charges or paper cash are missing, without substituting zero | B | This matches the current reserve veto `FUNDS_UNAVAILABLE` and the replay rule that an omitted charge makes cash unknown. It is not implemented for fills. |
| Derive open quantity and `average_entry_ask` from applied fill events for that contract | B | The in-memory replay does this from explicit prices. The session row cannot store it while positions are fixed at zero. |
| Keep session P&L on the four-term formula in `accounting.py` | A | A fill does not set `session_pnl_inr`. The stored value stays null until realized P&L, unrealized mark, booked charges, and estimated exit charges are all supplied. |
| Compare a broker snapshot with the local book only when both sides are present | A for the in-memory comparison; C for the ledger | `reconcile_paper_accounts` reports an absent statement instead of zero. The ledger has no tolerance and no broker snapshot. |
| Keep reservations and lockouts on their current event types | A | A fill extension must not change `RESERVE`, `RELEASE`, `LOCKOUT_SET`, or `LOCKOUT_CLEAR`. An entry reservation remains blocked while that session's lockout is active. |
| Add no migration for this review | A | `event_type` is already a string. Widening the invariant is an application change, and it is not made here. Old rows stay valid. |

The prose says paper cash follows fills. The code says paper cash equals configured capital. Both are current repository statements. The code is the enforced contract. Changing it is a later explicit revision, not part of this review.

Blocked until evidence or an explicit approval exists: a charge amount, an operator risk-capital value, a verified tick and lot, an authoritative calendar, a broker position snapshot, a reconciliation tolerance, and model approval for paper. The rupee amount to release from a reservation after a partial fill is also blocked while charges are unknown. No worker lease is defined. M11 is not started.

### 7.3 M10 blocker inventory

Classes: A local plumbing, B an operator value, C authoritative market or broker evidence, D an explicit approval, E accounting that is not implemented. A blocker marked "every entry" stops the current simulation from leaving `VETOED`. The others stop only the named capability.

| Blocker | Gate or control | Class | Evidence already in the repo | Offline only | External evidence | Operator or approval | Depends on | Scope | Acceptance test |
|---|---|---|---|---|---|---|---|---|---|
| Exchange calendar | `calendar` returns `CALENDAR_NOT_EVALUATED` or `CALENDAR_NOT_AUTHORITATIVE`. `holiday_calendar_source_id` is null. The fixture calendar sets `authoritative` false. | C | The fixture clock 09:15–15:30 and the null source id | No | An NSE or BSE session and holiday calendar | None beyond accepting that source | None | Every entry, and the session loop | A listed authoritative calendar passes this gate. The fixture calendar still fails it. |
| Tick unit | `instrument_master` returns `TICK_UNIT_UNVERIFIED` after the fields match. `extra_tick_penalty` is false. | C | Open question 7. A caller tick is copied and still rejected. | No | Exchange or broker confirmation of the unit | None | Instrument master | Every entry that has a matching master | A verified unit is the only input that may clear this reason. A matching unverified tick still vetoes. |
| Lot size and tradability | `MASTER_NOT_TRADABLE`, `MISSING_MASTER`, `MISSING_LOT_SIZE` when the master or lot is absent | C | Option fixtures leave lot and tick null. `65` is a test input, not a master row. | No | Instrument master with `buy_allowed`, lot, and tick | None | Tick unit | Every entry | A master that disagrees with the intent is `MASTER_MISMATCH`. A matching master still leaves the tick reason. |
| Model approval | `model_approval` is `MODEL_NOT_APPROVED`. The gate has no pass branch. | D | Three `TRAINED` versions. Paper and live slots are empty. The registry refuses `APPROVED_FOR_PAPER`. | No | Untouched-test evidence required by M11 | Explicit paper approval | M11 | Every entry | A payload labelled `APPROVED_FOR_PAPER` still vetoes, and the registry still refuses that status. |
| Capital and funds | `funds` is `FUNDS_UNAVAILABLE`. `position_limits` adds `MISSING_RISK_CAPITAL`. | B | `risk_capital_inr` is null. A test figure is not configuration. | The null can be confirmed offline. Setting a value is an operator act. | None. It is not a broker balance. | The operator chooses the rupee amount | Charges, before the funds requirement can pass | Every entry | Null capital vetoes. A configured amount still leaves `FUNDS_REQUIREMENT_UNAVAILABLE` while charges are unknown. |
| Charges and taxes | `exposure` is `CHARGES_UNVERIFIED` | B for an operator schedule that is not in the schema. C for Groww margin charges. | No charge field. Margin charges are documented and untested. | No | `brokerage_and_charges` for a live charge, or a written operator schedule | The operator must accept a paper schedule before it exists | None | Every entry | A caller `charges_per_lot` does not clear the gate. An omitted charge is not stored as zero. |
| Session P&L | `position_limits` is `SESSION_PNL_UNAVAILABLE` | E | The four-term formula exists. The ledger value stays null. | The formula can be checked with explicit inputs. The ledger cannot be valued offline. | Fills and a charge schedule | None | Fills, charges, positions | Every entry | A missing term stays null. The stored session row stays null. |
| Liquidity floors | `liquidity_floors` is `LIQUIDITY_FLOORS_NOT_CONFIGURED` and blocks | B | No floor fields in `RiskConfig` | An operator can set them later. Inventing numbers is not allowed. | None | The operator sets spread, volume, and open-interest floors | None | Every entry | The gate stays `NOT_CONFIGURED` while the fields are absent. |
| Reconciliation | `reconciliation` is `RECONCILIATION_UNAVAILABLE` | B for the tolerance. C for the broker snapshot. E for the ledger comparison. | In-memory reconciliation reports an absent statement. The ledger has no tolerance. | The absent-statement check is offline. A broker match is not. | Broker positions | The operator sets the tolerance | Snapshot and tolerance | Every entry | An absent statement is not treated as zero. No broker call is made. |
| Fill persistence | Paper states stop at `PROPOSED` and `VETOED`. `FILL` is `INVALID_EVENT_TYPE`. | E | The in-memory replay is disconnected. Cash must equal capital. Positions and open premium stay zero. | The replay tests are offline. Posting a fill is not. | A charge and a price that the caller does not invent | Paper activation | Capital, charges, calendar, tick, model approval, reconciliation | The capability of recording a fill | `apply_event` rejects `FILL`. A veto writes no risk event and no fill. |
| Partial fill and reservation release | No fill quantity is stored. The release amount after a partial fill is not defined while charges are unknown. | E | A full release must match the outstanding reservation. | The missing rule can be stated offline. The amount cannot be calculated. | Charges for the unfilled remainder | None until charges exist | Charges and fill persistence | Partial-fill accounting only | A release of a different amount is `RELEASE_AMOUNT_MISMATCH`. No partial quantity is created. |
| Quote freshness and provenance | `quote_age` uses `occurred_at` minus `quote_timestamp`, limited to 15 seconds | A for the clock. C for a verified quote. | The route passes `occurred_at`. It does not use the wall clock. Quarantine stays `UNVERIFIED_PROVIDER`. | The clock check is offline. A verified quote is not. | A market quote with a confirmed timestamp | None | None for the clock | A real executable quote, not the veto path | A timestamp 15 seconds old is fresh. One 16 seconds old is `STALE_QUOTE`. A missing or naive timestamp is `MISSING_QUOTE_TIME`. |
| Kill switch | Read from `ops_state`. A missing row is `KILL_SWITCH_NOT_READ`. On blocks entries and does not by itself block an exit. | A, already wired | The simulation seeds the existing row and then reads it. | Yes | None | The operator turns it on | None | Entries while the switch is on or unreadable | An explicit on vetoes. A read failure vetoes. The seeded off state does not add `KILL_SWITCH`. |
| Drawdown lockout | `drawdown_lockout` is `NOT_CONFIGURED` and does not block while the fraction is null | B, disarmed | `drawdown_lockout_fraction` is null, as specified | Yes | None | The operator sets a fraction before the control can arm | Session P&L, once armed | Only an armed drawdown control | The null fraction does not add a veto reason. |
| Idempotency and recovery | `event_id` and `body_hash` on the ledger. `intent_id` plus a request snapshot on paper. | A | Duplicate and conflicting ledger ids are tested. A simulation retry reuses the same intent. | Yes | None | None | None | Recovery of one interrupted intent | Ledger duplicates do not change the row. A matching simulation retry does not open a second intent. |
| Interrupted simulation | `open_intent` commits `PROPOSED` with the request snapshot, then evaluates. An exception leaves `PROPOSED`. The same payload is re-evaluated and vetoed. A different payload is `INPUT_CONFLICT`. A `PROPOSED` row with no snapshot is vetoed as `INPUTS_NOT_STORED` and is not evaluated from the retry body. | A | Seed, evaluation, and veto-transition failures are caught. | Yes | None | None | None | That intent only. It does not create a fill. | A forced exception after `PROPOSED` stays recoverable. The matching retry ends `VETOED`. No cash or position row appears. |

An interrupted simulation now keeps one intent. A matching retry re-runs the existing gates and records `VETOED`. Capital, charges, the calendar, the tick unit, and fill persistence stay behind that because each one needs an operator value or external evidence.

### 7.4 Simulation decision replay

No migration. The request snapshot and each decision attempt are JSON documents on the existing `audit_events` table. Older rows stay valid. A replay reports a missing key instead of filling it.

The first `paper.simulation_request` row is the snapshot. A later row for the same intent does not replace it. The snapshot stores `body_hash`, `request_occurred_at`, `quote_timestamp` when the quote itself carried one, lineage identifiers copied from the dataset and forecast, and the risk intent. It does not store the dataset candles. A quote timestamp is not copied from the request clock.

Each `paper.simulation` row is one attempt. It stores the ordered veto reasons, the gate name and state when evaluation completed, and whether the attempt was a decision, a duplicate of the stored snapshot, a recovery, or an input conflict. A conflict records the presented hash and leaves the original snapshot in place. A repeat that evaluates again is a new attempt. It does not rewrite the earlier reasons. An interrupted attempt has `decision_attempt` false and no gate list.

A completed decision stores the six risk fields `evaluate()` reads: `risk_capital_inr`, `max_risk_fraction_per_trade`, `drawdown_lockout_fraction`, `allowed_underlyings`, `allowed_structures`, and `quote_max_age_seconds`. The call passes no calendar, and the record says so. Fields the evaluator does not read, including daily-loss fraction, cash buffer, position caps, and the holiday source, are not copied. The dataset candles are not copied. An older attempt without `evaluator_inputs` stays missing. Replay does not fill it from the current defaults file.

The same evaluation result carries `operational_state` schema `operational-state-1`. The kill-switch section is the boolean returned by that read, or `row_missing`, `read_failed`, or `not_read`. The funds section records paper cash only when capital is set and the session row is read. The position section records `lockout_active`, `lockout_reason`, and `config_revision` from that read. A missing row is not stored as cash zero or as the switch off. Replay returns this object and does not read `ops_state` or `risk_sessions` again. An interrupted attempt leaves it null. An older attempt without the object stays missing. The stored value is the one returned inside `evaluate()`, kept in memory until the attempt row is inserted. Replay does not replace it with a later read.

PostgreSQL and the SQLAlchemy engine use `READ COMMITTED`. The engine does not set another isolation level. Evaluation now takes `pg_advisory_xact_lock(841105, 1)` before the intent lock, then locks the existing `ops_state` row and the existing session row with `FOR UPDATE`. `set_kill_switch`, `open_session`, `apply_event`, and `ensure_seed` take that operational lock before they write. A kill-switch commit cannot land between the two reads while that transaction holds the lock. A missing row is not inserted by the reader and is not stored as off or as cash zero. The lock does not make a fill atomic: no fill is written.

Opening an intent, moving it, and recording an attempt take `pg_advisory_xact_lock` on PostgreSQL 16 before reading the current rows. The lock lasts until that transaction commits or rolls back. A second request for the same intent waits, then sees the committed snapshot and transitions. Identical requests therefore share one `PROPOSED` row, one original snapshot, and attempt numbers `1..n`. A conflicting request does not replace the snapshot. A commit that fails rolls the transition and the snapshot back together. No migration is added: a uniqueness constraint would reject historical duplicate rows, and those rows stay in place for replay.

Replay does not renumber stored attempts and does not choose a later snapshot. Rows inserted outside this lock can still repeat an attempt number or add a second snapshot. Replay reports that conflict and keeps the earliest snapshot. `hashtext` is 32 bits, so two different intent ids can share a lock. That only serializes them. It does not merge their rows.

`replay_simulation_decision` reads those rows and the paper transitions. It does not evaluate, reserve cash, or create a fill. The full dataset, a model version that was not on the forecast, a quote timestamp that was not supplied, and the risk configuration cannot be reconstructed.

### 7.5 Simulated-fill boundary

`propose_simulated_fill` accepts a `SIMULATED_FILL` payload only as a citation of a stored simulation. It reads the first `paper.simulation_request` row and the first completed `paper.simulation` decision. Caller approval flags, a caller risk pass, a caller price source, and caller lineage do not authorize execution. A lineage object that differs from the stored record is a conflict. `UNVERIFIED_PROVIDER` stays unverified.

The payload hash covers the event id, intent, decision audit id, snapshot hash, instrument, side, quantity, price, timestamp, price source, charges, slippage, tick, and lot. Approval flags are not part of the hash. The same hash for an event id returns the stored refusal. A different hash is a conflict and does not replace it. The operational lock is taken before the intent lock, and the existing kill-switch and session rows are locked for update when they exist. A missing row is not created just to lock it.

The refusal is an audit row, `paper.execution_refused`. It is not a ledger event. Cash, positions, open premium, booked charges, and P&L are not written. `FILL` remains outside the ledger. A failed commit rolls the refusal back.

Execution stays disabled while `PAPER_TRADING_ACTIVE` is false. It also stays disabled because a kill-switch read and a ledger read can observe different commits, and this boundary does not lock those rows. Missing capital, unknown cash, an unknown or unverified charge, an unverified tick or lot, and the absent reconciliation tolerance each remain a refusal. None of those is replaced with zero.

### 7.6 Future fill transaction

The transactional design is `docs/M10_TRANSACTIONAL_PAPER_EXECUTION_DESIGN.md`. It does not enable a fill.

`open_intent`, `transition`, `_finish`, `propose_simulated_fill`, `open_session`, `apply_event`, and `set_kill_switch` each commit inside the function. A fill cannot call them as steps of one transaction. `_invariant` rolls back any session whose paper cash is not the configured capital, or whose open premium or position count is not zero. A fill that changed those values cannot commit through the ledger as it stands. The in-memory book in `replay_paper_accounts` is the arithmetic a later ledger would have to match. Unknown charges and unknown cash stay unknown there. They are not zero.

The writers now share one order: `pg_advisory_xact_lock(841105, 1)`, then the intent lock when the operation names an intent, then `ops_state` id 1 `FOR UPDATE`, then the session-date row `FOR UPDATE`. `lock_intent` takes the operational lock first, so `ensure_seed` cannot deadlock with it. A caller may pass `commit=False` to `open_session`, `apply_event`, `set_kill_switch`, `open_intent`, and `transition`. Those calls flush and leave the commit to the caller. The default remains a standalone commit. A fill is still not an atomic financial update, because `_invariant` rejects any cash value other than configured capital and any non-zero position or open premium, and no fill row is written.

Paper cash that follows fills, and the reservation amount released by a partial fill, are unresolved. They need an explicit decision before any financial write. M11 is not started.

## 8. Readiness audit

A local read of `config/defaults.yaml`, stored config revision 1, `ops_state`, and `var/registry/registry.json` was made without a provider request. Revision 1 has `risk_capital_inr: null`, no charge fields, `holiday_calendar_source_id: null`, mode `PAPER`, and live trading disabled. The kill switch row is off. That is a control state, not a verification that trading is safe. The registry has three `TRAINED` versions, no research selection, and empty paper and live slots. `forecast_ready`, `paper_approved`, `live_approved`, and `real_market_data_verified` are false. Policy fractions such as `0.01` are present as starting settings. Presence is not verification. The stored application database did not contain the ledger tables at the time of the read. The test database creates them through the migration.

A stale or missing bid now uses the full entry premium for the lockout mark. A fresh bid still requires a positive bid. A release is ordered against the outstanding reservation, not against an arbitrary earlier reserve. A missing cash-buffer fraction vetoes instead of raising.

| Blocker | Spec status | Current behaviour | Missing input | Local data enough | External confirmation | Safe to implement now | Test |
|---|---|---|---|---|---|---|---|
| Risk capital | Mandatory for sizing, paper cash, and daily-loss threshold | Null. Reservations that need cash veto | A configured rupee amount | No. The field exists and the value is null | No. It is an operator setting, not a broker balance | No. Inventing an amount would weaken the gate | Existing null-capital veto |
| Transaction charges | Mandatory for `one_lot_risk`, net, and exit-charge estimates | No schedule. Exposure gate `NOT_CONFIGURED` | `charges_per_lot` from Groww margin fields, or an explicit `OPERATOR_SCHEDULE_UNVERIFIED` config for paper | No schedule is stored | Live charges need a broker margin read. Paper can use an operator schedule that is not present | No | Existing missing-charge tests |
| Instrument master and tick unit | Mandatory before a buy | No master row. Tick unit unverified. Gate `UNAVAILABLE` | `buy_allowed`, lot size, tick size, and a verified tick unit | No local master row | Yes. The documented sample tick does not establish the unit | No | Existing master and tick tests |
| Session calendar | Mandatory for gate 3 and for clearing a lockout by date | Holiday source is null. Calendar is not authoritative | An authoritative holiday and session calendar | No | Yes | No | Lockout date-change test |
| Forecast approval | Mandatory for gate 6 | Versions are `TRAINED`. Paper and live slots are empty. Research approval is not paper approval | `APPROVED_FOR_PAPER` or `APPROVED_FOR_LIVE` from the registry path, with `model_health` `HEALTHY` | No. The registry cannot reach those statuses yet | The approval also needs the later untouched-test rule | No | Proposal and gate tests |
| Session P&L | Mandatory for the daily-loss test | Formula exists. Ledger value stays null | Realized P&L, a position, a fresh or explicitly stale bid, booked charges, and estimated exit charges | No positions or charge events exist | Fills and charges are not local facts | The formula can be checked with explicit inputs. It cannot value the ledger | Explicit and missing-term tests |
| Reconciliation tolerance and broker snapshot | Mandatory for gate 13 | `NOT_CONFIGURED` | A rupee tolerance setting and a broker position snapshot | Neither is stored | Yes for the snapshot | No. A zero tolerance would be invented | Gate-state test |
| Liquidity floors | Named gates, values not configured | `NOT_CONFIGURED` and not applied | Spread maximum, volume floor, open-interest floor | No | No, once an operator sets them | No | Gate-state test |
| Drawdown lockout | Disarmed while the fraction is null | `NOT_CONFIGURED`, does not block | An operator fraction | The null value is the specified disarmed state | No | Already implemented | Gate-state test |
| Quote age, allow-list, kill switch, paper mode | Mandatory and configured or stored | Evaluated when their own inputs are present | A quote is still required at decision time | The limits and the off switch are stored. A quote is not | A live quote would be external | Already implemented for the checks that have inputs | Gate tests |
| Paper activation and proposal page | Page is specified with paper submit and live confirm. Activation is a later milestone | Page is not served. `PAPER_TRADING_ACTIVE` is false | A persisted proposal, a passing risk result, and an activation rule | No | Human approval is required before activation | A read-only view could show decision, status, reasons, provenance, null expected net, gate states, and false approval flags. It must not show submit, approve, or a prefilled quantity | Proposal non-execution test |
| Fills and slippage | Half-spread price can be calculated from explicit quotes | No fill is recorded. `PAPER_TRADING_ACTIVE` stays false | An applied fill still needs passing risk gates, a charge schedule, and a broker snapshot | No | A calculated price is not a market print or a broker fill | No. The simulation records a veto and leaves the ledger unchanged | Paper simulation tests |

### What can be shown without a trading control

If a read-only proposal surface is added later, it can show the research decision `NO_TRADE`, `INCOMPLETE` or qualitative `COMPLETE`, machine-readable reasons, quote provenance, a null modelled value, a null expected net, the gate states above, and the four false readiness flags. It cannot show a paper-submit button, a live-confirm modal, an approval action, or a prefilled quantity. Those controls require a risk pass, paper activation, and the order transitions that are still blocked.

### Acceptance checklist

Code already present:

- Ledger events, row locks, duplicate and conflicting ids, reservation and release invariants, and lockout persistence.
- The sizing and session-P&L formulas when every named input is explicit.
- Gate states that stay off `PASS` when their mandatory input is missing.
- Paper states `PROPOSED` and `VETOED`, with submission and fills refused.
- Research proposals remain non-executable.

Verified configuration still required:

- A non-null risk capital chosen by the operator.
- A charge schedule the operator accepts for paper, labelled unverified if it is not a broker margin result.
- Liquidity floors only if those gates are to be applied.
- A reconciliation tolerance, as an accounting setting.

Authoritative external data still required:

- Exchange session calendar.
- Instrument master, including lot size and a verified tick unit.
- Broker position snapshot for reconciliation.
- Live charges if paper is not using an operator schedule.

Explicit human approval still required:

- Model promotion to `APPROVED_FOR_PAPER` under the later activation rule.
- Paper activation itself. It is not implied by mode `PAPER` or by a research selection.

Reserved for the next milestone:

- Persisted simulated fills, partial-fill reservations, and fill-driven changes to the ledger's paper cash and open premium. An in-memory replay can check explicit events. It is not activated.
