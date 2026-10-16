# M10 final readiness report

Date: 15 Oct 2026. PostgreSQL 16.6, test database on port 54329. No broker or market-data request was sent.

**Status: INCOMPLETE.**

Paper trading is not activated. No simulated fill is persisted. The original M10 gate — paper fills, a scheduler, a lease, and reconciliation against broker state — is not met. The software that can run without those inputs is in place and fail-closed.

## Requirements

| Requirement | Status | Evidence | Blocker |
|---|---|---|---|
| Transaction-safe execution architecture | Partially implemented | `commit=False` on `open_session`, `apply_event`, `set_kill_switch`, `open_intent`, `transition`, and `propose_simulated_fill` flushes and does not commit. `test_caller_owned_ledger_transaction_is_invisible_until_commit` rolls the flush back. Standalone callers still commit. | A fill transaction cannot call the helpers that commit on their own and then update cash. The cash invariant still rejects that update. Software, until the cash rule is chosen. |
| Shared locking and concurrency | Implemented and tested | Order is namespace `841105`, then intent namespace `841104`, then `ops_state` `FOR UPDATE`, then the session row `FOR UPDATE`. `test_operational_lock_blocks_a_writer_during_evaluation` shows the kill-switch writer timing out while evaluation holds the lock. `test_second_reservation_sees_the_first` and the concurrent simulation tests still pass. | None for the lock itself. It does not authorize a fill. |
| Persistent accounting schema and invariants | Partially implemented | In-memory `replay_paper_accounts` enforces weighted average, oversell, unknown charges, and duplicate hashes. Migration `004_paper_account_events` adds an append-only journal. A recorded event and its replay effect commit together, or both roll back. The check constraints reject `ledger_applied = true` and `broker_confirmed = true`. The ledger still rejects `FILL` and keeps cash equal to capital, open premium at zero, and positions at zero. | The journal is not the operational book. Persisting a fill into `risk_sessions` would change financial state and break the current invariant. Operator decision on the cash rule, then software. |
| Reservations and partial fills | Partially implemented | `RESERVE`, `RELEASE`, `LOCKOUT_SET`, and `LOCKOUT_CLEAR` remain the only ledger events. `unfilled_order_quantity` returns `order_quantity - filled_quantity` when both values are explicit decimals and the filled size does not exceed the order. `classify_reservation_release` returns `release_inr` null. Its quantity status can be `FULLY_COMPUTABLE`. Its rupee status is `INPUTS_MISSING`, `CHARGES_UNKNOWN`, `INVALID_INPUT`, or `RULE_UNDEFINED`. It does not return `FULLY_COMPUTABLE` for rupees. | No written release policy and no validated charge schedule. A rupee amount stays undefined. |
| Reconciliation | Partially implemented | `reconcile_paper_accounts` rejects a missing tolerance, a null or unparseable amount, a missing position list, an unverified broker source, and a stale statement time. It does not call a broker. | No broker snapshot and no approved tolerance in configuration. External evidence and operator approval. |
| Execution boundary | Implemented and tested | `POST /api/paper/executions` returns 422. Caller approval flags do not authorize a fill. `PAPER_TRADING_ACTIVE` is false. Refusal rollback and duplicate-id tests pass. | The boundary cannot be turned on without activation. Operator approval. |
| Audit and replay | Implemented and tested | Replay reads stored audit rows. Missing historical fields stay missing. The operational snapshot is the value returned during the locked evaluation. | Candles, unused risk settings, and a verified price source are not in the snapshot. External evidence. |
| Lineage and model eligibility | Implemented and tested | Quarantine and unsealed lineage are rejected before an intent. `APPROVED_FOR_PAPER` is refused. Entries record `MODEL_NOT_APPROVED`. | A paper-approved model does not exist. Operator approval, and M11 evidence that this task does not create. |
| Risk controls and kill switch | Implemented and tested | Missing, failed, and explicit-on switch states fail closed. A missing row is not reported as off (`kill_switch_report(None)` is `None`). | An authoritative calendar, tick, lot, charges, capital, session P&L, and liquidity floors are still absent. External evidence and operator approval. |
| Activation controls | Implemented and tested | No scheduler, worker, or activation route was added. The six flags stay false. Unattended orders stay false in `config/defaults.yaml`. | Activation itself. Operator approval. |
| Test coverage | Implemented and tested | Focused paper, ledger, accounting, and health tests, then the full API suite, on PostgreSQL. No test in this change persists a fill. | Tests that would post a fill are intentionally absent. |
| External prerequisites | Blocked by external evidence | Calendar, tick unit, lot, charge schedule, verified lineage, broker snapshot, and the Groww timestamp contract are not marked verified. | External evidence. |
| Operational readiness | Blocked by operator approval | Risk capital is null. Paper activation is off. No model is approved for paper. | Operator approval. |

## What remains unimplemented

- Persisted paper fills and the cash, position, premium, charge, and P&L updates that would follow them.
- A scheduler, a lease, and a worker. A dead worker cannot be shown not to double-submit, because there is no worker.
- Broker reconciliation against an independent snapshot.
- Partial-fill reservation release in rupees.
- Applying the research projection to `risk_sessions`.
- Any change to `PAPER_TRADING_ACTIVE`.

Read-only additions after this report: `GET /api/paper/simulations/{intent_id}`, `GET /api/options/research`, and `GET /api/accounting/status`. They do not post a fill. M10 remains incomplete.

## Research desk

Dashboard, Forecasts, Options, Paper, and Risk read the local APIs and label synthetic, unverified, quarantined, stale, and unavailable data from the payload. Missing money stays unset. Options renders `NO_TRADE` and the returned reasons, with expected net null. Paper lookup replays a stored intent and has no submit, retry-to-execute, or order control. Risk shows the kill switch, accounting rules, and the empty-contract gates.

## Tests run on 15 Oct 2026

- `cd apps/api && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ../../.venv/bin/pytest -q --tb=line` — 283 passed, 0 failed, 0 skipped, 1 existing Starlette warning. The added test reads the research routes and posts an execution without a CSRF header. `risk_events`, `FILL` rows, `paper_transitions`, and `risk_sessions` stayed 0. That post returned 403 and did not write those tables. Config seeding on an empty test database is separate from those financial tables.
- `cd apps/web && npm test` — 10 passed, 0 failed. That is the research formatters, kill-switch labels, and the existing integration label tests.
- `cd apps/web && npx playwright test --reporter=line` — 12 passed, 0 failed. Chrome on this machine. Fixtures only. The server was `next start` on port 3100 with `API_URL` pointed at a closed port. No page under test posted `/api/orders/live`, `/api/paper/executions`, or `/api/paper/simulations`.
- `cd apps/web && npm run build` — succeeded, 16 static routes.

## Known limitations

- Journal rows are not ledger fills. Paper trading stays off, and `risk_sessions` cash, premium, and positions are unchanged by the journal.
- The browser suite does not sign into the operator database and does not exercise a live provider.
- M6 historical candles remain quarantined. The Groww timestamp contract is unverified.
- M7 through M9 are not a complete trading path. M8 expected net stays null without scenario inputs, charges, and an enabled pricing method. M9 does not pass gates that lack a calendar, capital, tick, charges, or an approved model.
- M10 still lacks persisted fills, a scheduler, a lease, a worker, broker reconciliation, and a defined partial-fill release.
- M11 and later were not started.

## Financial state

This change does not insert a `FILL` event, does not set a paper transition to `FILLED`, and does not change the ledger rule that paper cash equals configured capital. New tests that flush a reservation roll it back before the test ends. The research-read test above compared financial row counts before and after and they stayed equal.

## Accounting journal, 15 Oct 2026

Files: `apps/api/app/risk/account_journal.py`, `apps/api/app/risk/paper_accounting.py`, `apps/api/app/risk/ledger.py`, `apps/api/app/domain/tables.py`, `apps/api/alembic/versions/004_paper_account_events.py`, `apps/api/tests/test_account_journal.py`, `apps/api/tests/conftest.py`, `apps/api/tests/test_paper_accounting.py`.

The journal accepts `FILL`, `PARTIAL_FILL`, `CANCEL`, `REJECT`, `CHARGE_ASSESSMENT`, `CHARGE_CORRECTION`, and `RECONCILIATION_DISCREPANCY` from an explicit fixture, operator action, or replay source. The same event id and payload is a no-op. A different payload for that id is `DUPLICATE_EVENT_CONFLICT` and leaves the stored row unchanged. A rejected event, including an invalid price, an oversell, or an unknown charge, is not inserted. A caller-owned `commit=False` flush is invisible to another session until commit, and rollback removes it. Cancel keeps filled quantity. A discrepancy record does not change replay cash. Reconciliation now requires a source identity, a statement time, completeness `COMPLETE`, and a tolerance before a match. A missing, incomplete, or stale statement does not match. No broker is called.

Legacy data: `paper_account_events` is a new table. The migration does not rewrite `risk_events` or `risk_sessions`. No existing `FILL` ledger rows were found to conflict, because `FILL` is still rejected by `apply_event`. An insert with `ledger_applied = true` fails the new check constraint.

`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ../../.venv/bin/pytest -q --tb=line` from `apps/api` — 292 passed, 0 failed, 0 skipped, 1 existing Starlette warning.

Still blocked: posting a fill into the operational ledger, the cash-equals-capital rule, a rupee release for a partial fill, a charge schedule, a reconciliation tolerance in configuration, a broker snapshot, paper activation, a scheduler, a lease, and a worker. M11 was not started.

## Journal replay and research projection, 15 Oct 2026

Replay order is `(occurred_at` as an absolute instant, `event_id)`. Text order of mixed offsets is not used. Equal timestamps break ties by `event_id`. Replaying the same payloads twice returns the same book. A conflicting duplicate id is `DUPLICATE_EVENT_CONFLICT` and leaves the stored row unchanged. An invalid event or a rolled-back `commit=False` insert is absent from the next replay. A cancel or reject does not remove filled quantity. A `RECONCILIATION_DISCREPANCY` row is reported and does not change cash. The `effect` JSON on an existing row stays as it was at insert time. The projection does not rewrite it.

`project_journal` and `GET /api/accounting/projection` read committed `paper_account_events` rows. The response role is `research_projection`, version `paper-account-projection-1`. It includes the SHA-256 of `event_id:body_hash` in that order, the event ids, and the first rejected event when replay stops. Cash, charges, open premium, positions, and P&L are each `known`, `unknown`, or `unavailable`. An empty journal is unavailable. A missing charge is unknown. P&L is unavailable. The route requires a session and does not call `ensure_seed`. It takes no advisory lock and writes no ledger row.

Ordering constraint: events compare by their timezone-aware instant, then by event id. There is no separate execution-history table to reorder. Stored journal rows are not updated to match a later replay.

## Future integration transaction

This transaction is not implemented. `apply_event` still rejects `FILL`.

These steps belong in one database transaction. One commit makes all of them durable. Any failed check rolls all of them back.

1. Take `pg_advisory_xact_lock(841105, 1)`. This lock is shared with operational writers.
2. When the event names an intent, take `pg_advisory_xact_lock(841104, hashtext(intent_id))`.
3. Take `pg_advisory_xact_lock(841106, 1)` for the journal. This lock comes after `841105`. The current journal writer takes `841106` alone, which is safe only while it does not touch `risk_sessions`.
4. Lock `ops_state` id 1 with `FOR UPDATE` when that row exists, then the `risk_sessions` row for the session date with `FOR UPDATE` when that row exists. A reader does not insert a missing row.
5. Validate the idempotency key. The same `event_id` and body hash returns the stored result and writes nothing. A different hash rolls back.
6. Insert the journal event. `ledger_applied` stays false unless the ledger step in this same transaction succeeds.
7. Recompute the projection from the payloads visible in this transaction, ordered by `occurred_at`, then `event_id`. Do not update older `effect` values. Unknown, unavailable, or stopped amounts roll back.
8. Apply the operational ledger event. This step is absent. A `FILL` remains `INVALID_EVENT_TYPE` and writes nothing.
9. Adjust the reservation. This step is absent. It requires `classify_reservation_release` to return release status `FULLY_COMPUTABLE` and a non-null `release_inr`. The function returns neither. A null amount is `INVALID_AMOUNT` and must not be posted.
10. Write the audit row.
11. Commit, or roll back steps 6 through 10.

The projection read is not part of that transaction. It selects committed rows and takes neither advisory lock.

## Tests run after the projection

`cd apps/api && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ../../.venv/bin/pytest -q --tb=short tests/test_account_journal.py tests/test_research_status.py tests/test_paper_accounting.py tests/test_risk_ledger.py` — 34 passed, 0 failed, 1 existing Starlette warning.

`cd apps/api && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ../../.venv/bin/pytest -q --tb=line` — 296 passed, 0 failed, 0 skipped, 1 existing Starlette warning.

Financial counts on the isolated test database, port 54329:

- `test_research_reads_do_not_change_financial_rows` read the research, options, accounting, projection, and simulation routes, then posted `/api/paper/executions` without a CSRF header. That post returned 403. `risk_events`, `FILL` rows, `paper_transitions`, and `risk_sessions` were `(0, 0, 0, 0)` before and after.
- `test_reservation_release_statuses_do_not_reach_the_ledger` called `apply_event` with `FILL` and with `RELEASE` using `release_inr` null. Both were refused, `INVALID_EVENT_TYPE` and `INVALID_AMOUNT`. The same four counts were `(0, 0, 0, 0)` before and after. `live_order_calls` stayed empty. `PAPER_TRADING_ACTIVE` stayed false.
- `test_projection_reports_unknown_values_and_does_not_change_the_ledger` inserted one test `risk_sessions` row, cash `500`, open premium `0`, positions `3`. After the projection and the journal inserts, those three values were still `500`, `0`, and `3`. `risk_events` and `FILL` rows stayed `0`. The inserted session row is test data on the truncated test database.

The projection module does not call a broker, and the tests recorded no live-order call. Quarantine files were not rewritten. `POST /api/paper/executions` remains refused. The approval and readiness flags in the projection and research status stay false.

**Status remains INCOMPLETE.** M11 was not started.

## Options candidate fixture, 15 Oct 2026

`POST /api/options/candidates` assesses one explicit local fixture through the existing research decision and options proposal. It does not replace that pipeline. Supplied identity is kept, omitted identity stays missing, and conflicting symbols are refused. The premium and expected net stay null. The index last price is not used as a premium. Approval flags stay false. A signed-in candidate post in the research-read test left `risk_events`, `FILL` rows, `paper_transitions`, and `risk_sessions` at `(0, 0, 0, 0)`.

`cd apps/api && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ../../.venv/bin/pytest -q --tb=line` — 304 passed, 0 failed, 0 skipped, 1 existing Starlette warning.

The Options page submits the fixture and renders its blockers. `cd apps/web && npm test` — 10 passed. `cd apps/web && npx playwright test --reporter=line` — 15 passed. `cd apps/web && npm run build` — succeeded, 16 static routes.

M10 remains incomplete. Verified quotes, charges, capital, calendar, lot and tick evidence, an approved forecast, and operational fills are still absent.
