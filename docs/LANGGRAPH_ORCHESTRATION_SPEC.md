# LangGraph orchestration for the V6 analysis workflow

**Status:** M8 installs `langgraph` `1.2.15` and runs a linear evidence graph in `app/analysis`. M8.1 verified the failure paths in mocked tests. Cursor agents, `AsyncPostgresSaver`, fusion probabilities, options pricing, and order execution are not part of this graph. Checkpoint retention remains an open question, so the compiled graph uses the in-memory saver for the request thread only. This is not a production-ready market-analysis service.
**Parent:** `docs/DESIGN.md`
**Agent list:** `docs/India_Market_Master_V6_Multi_Agent_Spec.md` section 4. This file does not add agents.
**Forecasts:** `docs/FORECASTING_AND_BACKTEST_SPEC.md` and `docs/MODEL_REGISTRY_AND_STUDIO_SPEC.md`

---

## 1. Package versions checked, not imported

On 14 Oct 2026 the public PyPI metadata and the LangGraph docs showed:

| Package | Version read | Role |
|---|---|---|
| `langgraph` | `1.2.15` | `StateGraph`, `START`, `END`, `add_node`, `add_edge`, `compile` |
| `langgraph-checkpoint-postgres` | `3.1.3` | `AsyncPostgresSaver` in `langgraph.checkpoint.postgres.aio` |

Both declare a dependency on `langgraph-checkpoint` `>=4.3.0,<5`. That is a compatibility statement from the package metadata, not an install or an import test in this repository.

Documented calls this design is allowed to use when the LangGraph milestone is built:

- `StateGraph(state_schema).add_node(name, fn, retry_policy=...).add_edge(...).compile(checkpointer=...)`
- `RetryPolicy` from `langgraph.types`, with an explicit `retry_on` predicate. The documented default retries most exceptions and skips `ValueError` and `TypeError`.
- `interrupt` from `langgraph.types`, and resume with `Command(resume=...)` using the same `thread_id`.
- `AsyncPostgresSaver.from_conn_string`, then `setup()` once. `InMemorySaver` is documented as process memory and is not the worker checkpointer.
- `config={"configurable": {"thread_id": ...}}`. The Postgres checkpointer documents a `thread_id` length limit; this design uses the run UUID, which fits under 255 characters.
- `graph.get_state(config)` to read the latest checkpoint.

`TimeoutPolicy` is not part of this contract. Node timeouts are enforced inside the node with the existing configured limits. A later milestone may adopt a LangGraph timeout API only after that signature is read in the pinned version.

The milestone that adds these packages pins those versions and runs an import smoke test before any workflow uses them. This document does not add them to the M0 environment.

---

## 2. What the graph is

LangGraph coordinates the V6 evidence workflow: which specialist runs, what it may read, how a failure is recorded, and how an interrupted run resumes.

It is not a forecasting model. It does not emit `p_up`, `p_range`, or `p_down`. It is not the risk engine and it is not the execution service. A conditional edge may skip a specialist when its input is already `FAIL`. It may not skip the worker stages that sit outside the graph.

Cursor local agents remain the language-model runtime inside the specialist nodes that need one. The call shape in `docs/DESIGN.md` section 5.1 still applies: one local `AsyncAgent.prompt` per specialist per run, no cloud agent, no subagents, no shell, no SQL, and no broker client. LangGraph is the dispatcher the design previously described as `app/reasoning/orchestrator.py`. A node does not choose an undeclared successor and does not spawn another agent.

---

## 3. Two paths

The worker starts both paths after data validation. They share a `run_id` and a data cutoff. They do not share writable probabilities.

```text
Market data -> validation
    |                                  |
    | PATH A                           | PATH B
    v                                  v
Feature row                            LangGraph evidence graph
    -> pinned model version            -> specialist evidence
    -> calibrated forecast             -> conflict and missing-data record
    -> forecast validation             -> structured context result
    |                                  |
    +------------------+---------------+
                       v
              Fusion service, usually BASELINE_ONLY
                       v
              Options valuation service
                       v
              Risk engine
                       v
              Paper broker, or no order
```

Path A is Python in `app/models_ml`. Path B is the graph in this file. Fusion, options valuation, risk, and the paper broker are worker services. They read the stored outputs. They are not LLM nodes.

If Path A has no approved model, the forecast is qualitative and the trade decision is `NO_TRADE`. Path B may still produce a report context. It may not fill the probabilities.

---

## 4. Nodes

Names follow the V6 roster. Market data, data quality, the quantitative forecast, fusion, contract valuation, the risk engine, execution, and outcome scoring are services. They are not graph nodes.

| Node | V6 role | Runtime | Notes |
|---|---|---|---|
| `news_verification` | News verification | Cursor, inside the node | Enabled sources only. |
| `global_macro` | Global macro | Cursor | No probabilities. |
| `crude_cross_asset` | Crude and INR | Cursor | Missing crude marks the node degraded. It does not invent a price. |
| `index_nifty` | Index technical | Cursor | NIFTY fact pack only. |
| `index_sensex` | Index technical | Cursor | SENSEX fact pack only. |
| `index_banknifty` | Index technical | Cursor | BANK NIFTY fact pack only. |
| `breadth_flow` | Breadth and flows | Cursor | Dated prints only. |
| `options_chain_evidence` | Options chain commentary | Cursor | Words and caveats. It does not price a contract. |
| `contrarian` | Contrarian / red team | Cursor | After the other evidence nodes. Cannot veto. |
| `aggregate_evidence` | Evidence aggregation | Python | Conflicts, missing fields, and degraded flags. No probabilities. |

The report writer stays a Cursor call in the worker after the trade decision is stored. Putting it inside the graph would let narrative code run before risk. That is rejected.

Parallel edges are allowed among `global_macro`, `crude_cross_asset`, the three index nodes, `breadth_flow`, and `options_chain_evidence` after news verification, because their fact packs are already stored. `contrarian` waits for those nodes. `aggregate_evidence` is last.

---

## 5. Graph state

`AnalysisState` is a `TypedDict` passed to `StateGraph`. The checkpointer persists it. It must not contain API keys, session cookies, or broker tokens.

| Field | Meaning |
|---|---|
| `workflow_id` | Graph definition version. |
| `run_id` | Analysis run id. Also the `thread_id`. |
| `market_session` | `PRE_OPEN`, `OPEN`, `CLOSED`, or `UNKNOWN`. |
| `underlying` | The run's primary underlying when the graph is scoped; index nodes still cover all three. |
| `forecast_horizon` | Pinned horizon id. |
| `market_data_timestamps` | Source timestamps already stored. |
| `data_quality_status` | `PASS`, `WARN`, or `FAIL` from the worker. `FAIL` means the graph is not started. |
| `model_version_id` | Pinned Path A version. The graph does not change it. |
| `model_output_ref` | Forecast row id when Path A has finished. Null while Path A is still running. The graph does not write probabilities into this field. |
| `evidence` | Map of node name to evidence id. |
| `evidence_sources` | Source refs and timestamps copied from those rows. |
| `conflicts` | Pairs of evidence ids that disagree. Both sides are kept. |
| `missing_required` | Fields or nodes that are absent. |
| `context_result_id` | Aggregate row. |
| `errors` | Node name, attempt, error class. |
| `retry_counts` | Per node. |
| `audit` | Config revision, prompt hashes, cursor agent ids. |

Options valuation and the risk result are worker columns on the analysis run. They are not fields the graph can set.

---

## 6. Specialist output

Each Cursor node returns the evidence envelope already required by the V6 spec and by `docs/DESIGN.md`. This design adds these constraints:

- `facts` are labelled `VERIFIED_FACT` or `SOURCE_CLAIM`. `interpretations` are labelled `INTERPRETATION`. A source claim cites a stored source id and a timestamp.
- `confidence.tier` is `LOW`, `MEDIUM`, or `HIGH` evidence strength. It is not a calibrated probability and it is not copied into `p_up`.
- The schema rejects probability fields.
- `missing_data` lists what the node did not have. The node does not fill those values.
- If the fact pack is missing or stale, the node result is `UNAVAILABLE` or `DEGRADED` and the report says so.

One schema repair prompt is allowed, matching the existing Cursor rule. A second invalid payload marks the node `FAIL` and leaves the section missing.

---

## 7. Failures, retries, and duplicates

| Case | Behaviour |
|---|---|
| Agent timeout | Node `FAIL`. No invented section. |
| Source failure | That node is `DEGRADED` or `UNAVAILABLE`. Other nodes still run if their own inputs exist. |
| Invalid JSON | One repair, then `FAIL`. |
| Conflicting conclusions | `aggregate_evidence` stores both. Fusion does not average them into a probability. |
| Stale critical market data | The worker does not start the graph. Verdict `INSUFFICIENT DATA`. |
| Duplicate run request | The same idempotency key returns the original `run_id`. A second graph is not started. |
| Interrupted process | Resume from `AsyncPostgresSaver` with the same `thread_id`. |
| Retry limit | Configured `max_attempts` on `RetryPolicy`. Shipped example is 2. This is not a measured optimum. |
| Cursor never started | Retry only when `CursorAgentError.is_retryable` is set. |
| Cursor run failed after start | No LangGraph retry. Node `FAIL`. |

Retries are for read-only node work. The node writes evidence with an attempt number and does not append a second contradictory fact as if it were a new observation. Order submission is not in the graph and is never given a `RetryPolicy`. A broker timeout remains `UNKNOWN_REQUIRES_RECONCILIATION`.

---

## 8. Checkpoint and human resume

The worker compiles the graph with `AsyncPostgresSaver` on the same Postgres database. `setup()` creates the checkpointer's tables. Those tables are not copied by hand into an Alembic migration that would drift from the package.

`InMemorySaver` is allowed in unit tests only.

An interrupt, if a later milestone needs a person to read the context before the report, uses `interrupt` and resumes with `Command(resume=...)`. The resume payload is a review acknowledgement. It cannot carry a risk-limit edit, a probability, or an order. After resume, the worker still runs fusion, options valuation, and the risk engine. Resume does not jump to the paper broker.

Checkpoints are retained for the operator-configured period. That period is not a compliance determination. `docs/OPEN_QUESTIONS.md` still holds the retention question. Secrets are redacted before a value is placed in state.

---

## 9. Fusion boundary

The fusion service is the forecasting spec section 7. It stays `BASELINE_ONLY` until a fusion artifact is approved for the current mode.

If fusion throws or lacks an input, it records the failure and uses the pinned quantitative forecast when that forecast is approved for the mode. It does not create a new probability from agent text. If there is no approved standalone forecast, the decision is `NO_TRADE` and the verdict is `INSUFFICIENT DATA` when the reason is missing data, otherwise `NO TRADE — RISK / DATA / CONFLICT`.

Agent confidence, news labels, and contrarian prose cannot clear a risk veto or change a limit.

---

## 10. M8.1 verified failure handling

These behaviors were checked with mocked tests. They are not a claim that live providers degrade gracefully.

- Each node is wrapped. An exception is stored as `NODE_FAILED` with the exception class name only, and the later nodes still run. A validation exception clears accepted observations so an unvalidated row cannot reach the report.
- A missing news, macro, Indian, or derivatives provider is `PROVIDER_UNAVAILABLE` on that node. The report status is `INSUFFICIENT_DATA` and the decision is `NO_TRADE`. Missing Indian names are listed. Derivatives rows are not invented.
- Contrarian commentary is an `INTERPRETATION`. A one-sided fixture does not create an opposing market fact.
- Fusion copies provider errors and missing inputs into the quality block. The report keeps `provider_errors`.
- If the graph returns no report, the API result is `FAILED` with `REPORT_FAILED`. Confidence stays null. `forecast_ready`, `paper_approved`, `live_approved`, and `real_market_data_verified` are forced false.
- OpenAI commentary retries HTTP 429 only when `Retry-After` is a number of seconds from 0 through 2. At most one retry is made. A missing, non-numeric, negative, date-formatted, or larger `Retry-After` is not waited on and is not retried. HTTP 401 and timeouts are one attempt. The model-lookup classifier also labels HTTP 429 as `RATE_LIMITED` and does not retry. A failed commentary call adds no invented note. Commentary is optional.
- The public report schema requires the status, decision, missing list, provider errors, evidence, and limitations. Source claims stay `SOURCE_CLAIM`. Synthetic provenance stays `SYNTHETIC` and `UNVERIFIED`. Quarantine markers are rejected before the graph.
- No verified news, macro, global-index, or options provider is configured. Groww historical candles stay quarantined and are not read by this graph.
- M8.1 added 4 mocked tests. The API suite then passed 132 tests and failed 0. No live provider was called by those tests.

---

## 11. OpenAI commentary hardening

The public call path is `POST /api/market-analysis`. The graph runs once and builds the deterministic report. OpenAI is called only after that, and only when the request sets `include_inference` to true, the saved OpenAI integration is enabled, and the report contains evidence other than the graph's own contrarian note. The default request leaves `include_inference` false, so it sends no completion. The form checkbox starts unchecked.

The completion URL is the fixed `https://api.openai.com/v1/chat/completions` allow-list entry. The browser cannot supply a provider URL or an API key. The model id must match the existing rule: 1 to 64 characters from letters, digits, and `. _ : -`. There is no fallback model.

Commentary outcomes keep the existing codes: `NOT_REQUESTED`, `NOT_CONFIGURED`, `INTEGRATION_DISABLED`, `SKIPPED`, `INVALID_MODEL`, `COMPLETED`, `RATE_LIMITED`, `QUOTA_EXCEEDED`, `INVALID_CREDENTIALS`, `MODEL_UNAVAILABLE`, `TIMEOUT`, `PROVIDER_UNAVAILABLE`, `PROVIDER_ERROR`, `SCHEMA_MISMATCH`, `MALFORMED_OUTPUT`, and `EMPTY_OUTPUT`. Each result also says whether commentary was requested, attempted, and produced. `COMPLETED` means the model returned a schema-valid note on a supplied evidence id. It does not mean the analysis succeeded.

The completion timeout is 15 seconds. A numeric `Retry-After` from 0 through 2 seconds allows one extra attempt, and the total wait stays within 2 seconds. Authentication failures, timeouts, connection failures, HTTP 5xx, malformed JSON, truncated `finish_reason=length`, and empty or non-text content are not retried. Logs record the outcome, attempt count, and wait. They do not record the prompt, the API key, or the authorization header.

Claims are rewritten before they enter the prompt when they look like instructions. Notes that fail the commentary schema are discarded. Unknown evidence ids are discarded. A note cannot add an observation, change `NO_TRADE`, or set an approval flag. If inference fails, the deterministic report is still returned.

The same idempotency key shares one in-process lock, so a duplicate request waits and reuses the stored report instead of sending a second completion. Two requests without that key are separate requests. The API suite after this pass passed 138 tests and failed 0. No live completion was part of those tests. A manual smoke test is a single commentary call with the saved model, a 15-second timeout, no market facts, and no retry after `RATE_LIMITED`. That smoke test has not established a successful real completion. This graph is not production-ready, and the plan's paper-broker milestone was not started.
