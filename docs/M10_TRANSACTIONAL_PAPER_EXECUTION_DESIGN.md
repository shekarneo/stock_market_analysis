# M10 transactional paper-execution design

This is the transaction design for a future paper fill. The shared lock order and the caller-owned `commit=False` path are now in the code. A fill is not. `PAPER_TRADING_ACTIVE` stays false. `POST /api/paper/executions` stays a refusal. No fill is written.

The statements below are taken from the current code: `apps/api/app/execution/boundary.py`, `simulation.py`, `paper.py`, `routes.py`, `apps/api/app/risk/ledger.py`, `paper_accounting.py`, `gates.py`, `config/store.py`, `db.py`, and `domain/tables.py`.

## 1. Transactions that exist today

PostgreSQL 16.6 and the SQLAlchemy engine use `READ COMMITTED`. `create_engine` does not set an isolation level. Each `SELECT` sees rows committed before that statement. A plain `SELECT` does not lock the row. `SELECT … FOR UPDATE` waits for a writer, then returns the latest committed row. It does not block an `INSERT` of a row that was not there.

These functions commit inside themselves. They cannot be called as steps of one larger transaction:

| Function | What it commits | Lock it takes |
|---|---|---|
| `open_intent` | `PROPOSED` transition and, once, the first `paper.simulation_request` | operational lock `841105`, then intent lock `841104` |
| `transition` | one paper transition, or an illegal-transition audit | same pair |
| `_finish` | one `paper.simulation` attempt | same pair |
| `propose_simulated_fill` | one `paper.execution_refused` audit, or nothing on duplicate, conflict, or a failed commit | same pair |
| `open_session` | one `risk_sessions` insert | operational lock `841105` |
| `apply_event` | one `risk_events` row and the session update, or a rollback | operational lock, then the intent lock when the event names an intent, then `SELECT … FOR UPDATE` |
| `set_kill_switch` | the `ops_state` update and a `risk.kill_switch` audit | operational lock, then `ops_state` id 1 `FOR UPDATE` |
| route `get_db` | a second commit after the handler | none |

`ensure_seed` does not commit. It inserts `ops_state` id 1 with `kill_switch` false when the row is missing, then flushes. Simulation calls it after the intent lock. Health and config routes call it with no intent lock.

`replay_paper_accounts` has no database transaction. It is not called by the simulation or by the execution boundary.

`read_kill_switch` and `read_session` are plain reads. `read_session` then calls `session.refresh`, which is another `SELECT`. Under `READ COMMITTED` those statements can observe different commits. `test_one_evaluation_can_record_two_committed_states` shows a kill switch read of false stored next to a lockout that was committed after that read.

## 2. Writers

| Writer | Rows it can change |
|---|---|
| `ensure_seed` | inserts `ops_state` id 1 |
| `set_kill_switch` | inserts or updates `ops_state` id 1 |
| `open_session` | inserts `risk_sessions` for one date |
| `apply_event` `RESERVE` / `RELEASE` | `reserved_inr` on that date, plus a `risk_events` row |
| `apply_event` `LOCKOUT_SET` / `LOCKOUT_CLEAR` | `lockout_active`, `lockout_reason`, `config_revision` |
| `propose_simulated_fill` | inserts `paper.execution_refused` only |
| simulation open, transition, and finish | `paper_transitions` and simulation audit rows |

No current writer changes `paper_cash_inr` after the session is opened, and none changes `open_premium_at_risk_inr` or `local_open_positions` away from zero. `FILL` is not in `EVENT_TYPES`. `_invariant` rolls the transaction back when capital is set and `paper_cash_inr` is not equal to that capital, or when open premium or the position count is not zero.

Those writers take `841105` before they change `ops_state` or `risk_sessions`. A reader does not insert a missing row. `test_operational_lock_blocks_a_writer_during_evaluation` shows a kill-switch update timing out while an evaluation holds the lock. That test does not post a fill.

## 3. Why one atomic fill is not available yet

A future approved fill would need all of the following in one transaction, with no commit until the last step:

1. Load the first `paper.simulation_request` and the first completed decision attempt. Reject a missing, conflicting, or stale citation. Ignore caller approval, caller risk, caller lineage, and a caller price source.
2. Re-check the live kill switch, the session row, capital, charges, tick, lot, and reconciliation under locks held by every writer of those rows.
3. Reject the fill when a reservation cannot be accounted for without guessing a release amount.
4. Insert one immutable fill event keyed by `event_id`, with the payload hash.
5. Update cash, open premium, position count, and charges from that event.
6. Append the audit row.
7. Commit once. Any failure rolls all of those writes back.

That transaction cannot be built by calling the current helpers. They commit on their own. It also cannot update the session row. `_invariant` rejects a cash value other than configured capital and rejects a non-zero position or open premium. Changing that check is a policy change, not a local refactor. Until it is made, the fill update is impossible inside the ledger that exists.

The operational pair is also not one snapshot. The kill-switch statement and the session statement are separate, and their writers do not share a lock. This design does not claim that today's boundary is atomic. The refusal reason `OPERATIONAL_SNAPSHOT_NOT_ATOMIC` remains correct.

## 4. Lock order for a later change

Do not add these locks in one module only. Every writer in section 2 has to move together. A fill that takes a new lock while simulation still takes the intent lock first can deadlock with `ensure_seed`.

Use two advisory namespaces so the operational key cannot collide with `hashtext`:

1. `pg_advisory_xact_lock(841105, 1)` — one lock for the operational tables, including the case where the row is missing.
2. `pg_advisory_xact_lock(841104, hashtext(intent_id))` — the existing per-intent lock, only when the operation names an intent.
3. `SELECT ops_state WHERE id = 1 FOR UPDATE`, or `INSERT` when the row is absent. The insert is allowed only while step 1 is held.
4. `SELECT risk_sessions WHERE session_date = :day FOR UPDATE`, or `INSERT` when that date is absent, again only while step 1 is held.

`hashtext` stays 32 bits. Two intent ids can still share the intent lock. That serializes them. It does not merge their rows.

Call order after the change:

- `set_kill_switch` and `ensure_seed` callers that have no intent: step 1, then step 3.
- `open_session` and `apply_event`: step 1, then step 4. When the event has an intent id, step 2 comes after step 1 and before step 4.
- Simulation and the fill boundary: step 1, then step 2, then steps 3 and 4 before any read that the decision depends on.

`READ COMMITTED` plus `FOR UPDATE` then shows the latest committed row, and another writer of that row waits until commit or rollback. The advisory lock in step 1 is what covers the missing-row insert. `FOR UPDATE` alone does not.

A duplicate `event_id` with the same payload hash is a no-op and must not change cash or positions. A different payload is `DUPLICATE_EVENT_CONFLICT` and rolls back. The database primary key on `risk_events.event_id` is the uniqueness rule for a future ledger fill. An id that already has a `paper.execution_refused` row must not later be inserted as an applied fill. A failed commit leaves neither the event nor the balance change, which is the rule already used by `apply_event` and by the execution-boundary rollback test.

Retries use the same id and the same hash. They do not allocate a second event.

## 5. Accounting invariants

The in-memory book in `replay_paper_accounts` is the arithmetic a future ledger would have to match. It is not persisted.

- A buy with known opening cash, price, quantity, and charge sets cash to `cash - price * quantity - charge`. A sell sets cash to `cash + price * quantity - charge`.
- If opening cash is missing, cash stays unknown. A present charge can still be booked. Unknown cash is not zero.
- If `charges_inr` is omitted or null, booked charges and cash become unknown for the rest of the book. A later numeric charge does not restore them. An explicit zero is a claimed charge, not a substitute for a missing one, and it remains unverified until a schedule exists.
- The average entry of a new long is the fill price. A second buy sets the average to `(old_quantity * old_average + new_quantity * price) / new_quantity_total`. A sell reduces quantity and leaves the remaining average unchanged. A sell larger than the open quantity is `OVERSELL` and is not applied. No short position is created.
- Open premium for a remaining long is `average * quantity` only when both are known. Session P&L stays null. The ledger's four-term P&L is not filled in by a fill event.
- Unfilled quantity is `order_quantity - filled_quantity` only when the order quantity was supplied. Otherwise it stays null. A cancel or reject does not remove quantity already filled and does not refund cash.
- The same event id and payload is skipped. A different payload for that id, or the same fill id with a different payload, stops the book and does not apply the new quantity.
- Reconciliation treats a missing cash, charge, position list, or fill list as absent. A null or unparseable statement amount is not a match. A replay that omits positions is not an empty book. A discrepancy does not authorize another fill.

The persisted ledger does not follow those cash rules. Its enforced rule is: when capital is null, paper cash is null; when capital is set, paper cash equals that capital; open premium is zero; the position count is zero; reserved plus open premium does not exceed capital. A fill that changed any of those values would be rolled back by `_invariant`.

`_reserve` also uses paper cash as the deployable balance. If cash later moves with fills, that formula changes meaning. That is unresolved. See section 7.

`local_open_positions` is an integer count. The replay's quantity is a decimal size. Those are not the same field. A future book may set the count to the number of contracts whose remaining quantity is positive. It must not store the lot quantity in that integer.

`charges_booked_inr` is not a column. `_state` always returns it as null. Unknown charges must stay null. They must not be stored as zero. Adding a column is a migration and is not part of this design.

Slippage is a required field on the refusal contract. A missing slippage is `SLIPPAGE_UNKNOWN`. The replay does not apply a half-spread haircut. The caller of the in-memory book passes an explicit price. `simulated_execution_price` can quote a half-spread sell price and still records no fill. A future fill must not invent that price from a missing bid or ask.

## 6. What a future transaction would reject

Reject, and write nothing financial, when any of these is true:

- `PAPER_TRADING_ACTIVE` is false.
- The stored decision is missing, stale, conflicting, or not a pass of the stored gates.
- Capital, cash, charges, slippage, tick unit, lot, calendar, or reconciliation evidence is missing or unverified.
- The kill switch is on, missing, or failed to read.
- The session row is missing, the lockout flag is unknown, or the lockout is active for an entry.
- Charges are unknown. The transaction does not continue with cash set to zero.
- A reservation is outstanding and the amount to release after this quantity is not an explicit input. The partial-release amount is not defined.
- The resulting cash, premium, or position count would fail the invariant that is in force. Today that includes any cash value other than configured capital and any non-zero position or premium.
- The event id matches a refusal or a ledger row with a different hash.

An exit is not given a special pass. The current exit path still has no known position.

## 7. Unresolved decisions

These block persistence. They are not answered here.

1. Paper cash equals configured capital in code. Older prose says paper cash follows fills. The reserve check uses cash as deployable funds. One of those meanings has to be chosen before a fill can update the row.
2. The rupee amount of a reservation to release on a partial fill is undefined while charges are unknown, and it is still undefined when charges are known but no release rule is written down.
3. Whether `local_open_positions` counts contracts. It cannot store a fractional quantity without a schema change.
4. Whether booked charges need a nullable column. Until then they stay derivable only from events, and unknown stays null.
5. A reconciliation tolerance and a broker snapshot do not exist. A discrepancy rule cannot pass.

## 8. Implementation boundaries

### A. Safe to implement and test later, without a fill

- Move every writer in section 2 onto the lock order in section 4 in one change. Tests use two sessions and a barrier. They must show that a kill-switch commit cannot land between the switch read and the session read once both sides take `841105` first.
- Keep `propose_simulated_fill` as a refusal. A refused event id stays refused.
- Keep the in-memory accounting tests. They already cover duplicate ids, conflicts, oversell, unknown charges, partial fills, cancels, and statement discrepancies.

### B. Blocked on external evidence

- Verified tick unit and lot, from an instrument master rather than a caller number.
- An authoritative session calendar.
- A charge schedule. A caller `charges_inr` does not verify it.
- Verified market-data lineage. `UNVERIFIED_PROVIDER` stays quarantined.
- A broker position snapshot for reconciliation.

### C. Blocked on operator approval

- Setting `risk_capital_inr`.
- Setting `PAPER_TRADING_ACTIVE` and any activation endpoint. Neither is added here.
- Choosing the cash invariant in section 7.
- Approving a model for paper. The registry still refuses `APPROVED_FOR_PAPER`.

No item in B or C is implemented by adopting the lock order.

## 9. Tests

Already running on PostgreSQL 16.6, port 54329:

- `test_one_evaluation_can_record_two_committed_states` — a commit between the kill-switch read and the ledger read is stored as both values.
- `test_disabled_execution_ignores_caller_approval_and_leaves_the_book` — the boundary returns `EXECUTION_DISABLED` and does not write a ledger row.
- `test_duplicate_event_is_idempotent_and_a_changed_payload_conflicts` — one refusal row; a changed price conflicts.
- `test_concurrent_refusals_and_a_failed_commit_leave_no_fill` — two sessions, one refusal; a failed commit leaves that event unrecorded.
- `test_second_reservation_sees_the_first` — two ledger sessions, `FOR UPDATE`, one reserve sticks.
- `test_reconciliation_does_not_treat_absent_records_as_zero` — null and unparseable statement amounts do not match a known book.
- `test_partial_fill_cancel_and_failed_tail_leave_a_declared_book` — in memory only. The ledger is unchanged.

Future tests, after the lock change and still before any fill:

- A barrier between `set_kill_switch` and `apply_event` shows the second waiter observes both commits, not a mix, when both take `841105` first.
- A missing `ops_state` row cannot be inserted by a second session while the first holds `841105`.
- Reversing the lock order in a test double is expected to deadlock and must not be the production order.
- Rollback of the future fill function leaves `risk_events`, cash, premium, and position count unchanged.

Tests that apply a fill, move cash, or set `PAPER_TRADING_ACTIVE` are out of scope until sections 7 and 8.C are decided.
