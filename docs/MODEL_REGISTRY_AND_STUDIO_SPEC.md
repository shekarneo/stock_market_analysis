# Model registry and Forecast Model Studio

**Status:** M5 implements a research registry and Forecast Model Studio for the three binary models. Rows are not approved for paper or live trading. `forecast_ready`, `paper_approved`, `live_approved`, and `real_market_data_verified` stay false. No model has a measured edge.
**Parent:** `docs/DESIGN.md`
**Metrics and leakage rules:** `docs/FORECASTING_AND_BACKTEST_SPEC.md`
**UI and API summary:** `docs/DESIGN.md` sections 16 and 17

This file is the source of truth for model identity, lifecycle, approval scope, studio behaviour, and the model HTTP contract. The forecasting spec remains the source of truth for labels, walk-forward, and promotion metrics.

---

## 1. What the studio is

The Forecast Model Studio lists models from the backend registry. The selector is not a hardcoded menu of every candidate family in this document.

A row appears in a selector only when the registry has that model version and the requested underlying and horizon are in its supported scope. A family named below with implementation status `NOT_IMPLEMENTED` is documentation of a candidate. It is not selectable.

Unavailable fields render as `UNKNOWN`, `NOT_EVALUATED`, or `NOT_AVAILABLE`. The UI does not substitute a sample metric, a sample probability, or a sample training date.

---

## 2. Candidate families

These families are allowed names for a future registry row. Training them is not required, and none is assumed to forecast Indian intraday index returns.

| Family id | Role in the benchmark order | Implementation status in this repository |
|---|---|---|
| `base_rate` | 1. First baseline. M3 implements the binary majority class under the name `majority_class`. | Research registry only. Not approved. |
| `persistence` | 2. Second baseline. M3 implements it as experiment key `last_return_sign`: the sign of `ret_1`, with a training-only Laplace map. | Research registry only. Not approved. |
| `logistic_regression` | 3. First learned model. M3 implements L2 logistic regression for `binary-1`. | Research registry only. Not approved. |
| `lightgbm` | 4. One tree family, and only if it beats logistic regression under the forecasting spec | `NOT_IMPLEMENTED` |
| `xgboost` | 4. The other allowed tree family. The project trains one of LightGBM or XGBoost, not both, unless a later evaluation justifies the second | `NOT_IMPLEMENTED` |
| `random_forest` | Not in the default order. A row may be registered only with a written justification stored on the version | `NOT_IMPLEMENTED` |
| `tcn` | 5. Sequence model, only if the dataset size and a written justification support it | `NOT_IMPLEMENTED` |
| `lstm_gru` | Not in the default order. Same justification rule as a sequence model | `NOT_IMPLEMENTED` |
| `small_transformer` | 5. Alternative to TCN, not an additional mandate | `NOT_IMPLEMENTED` |
| `timesfm` | 6. Only with a pinned upstream version, licence note, and a suitability note for this feature schema | `NOT_IMPLEMENTED` |
| `chronos2` | 6. Same gate as TimesFM. The name means a supported Chronos-2 release, not an unversioned weight file | `NOT_IMPLEMENTED` |
| `ensemble` | 7. Only after it beats the best approved single model on the predeclared metric | `NOT_IMPLEMENTED` |

Any other family is rejected until this table is amended and the code exists. Completing training does not approve a model.

---

## 3. Underlyings and horizons

Underlyings and horizons are configuration, not a fixed menu baked into the page.

Shipped analysis underlyings are `NIFTY`, `SENSEX`, and `BANKNIFTY`. The order allow-list is still the risk spec: NIFTY and BANK NIFTY options, with SENSEX options off until the instrument master confirms the chain. A forecast model for SENSEX does not by itself allow a SENSEX option order.

Candidate horizons:

| Horizon id | Meaning | Studio rule |
|---|---|---|
| `M1` | 1 minute of regular session time | Hidden from paper and live selectors until a dataset version, label rule, and evaluation report exist for that underlying. The Groww backtesting annexures name a 1-minute interval. M6 did not verify index coverage or candle-boundary semantics, so this horizon stays unavailable. |
| `M5` | 5 minutes of regular session time | Same as `M1`. |
| `M15` | 15 minutes | May be listed when a registry row supports it. Not production-ready until that row is approved for the requested operation. |
| `M30` | 30 minutes | Same as `M15`. |
| `H1` | 60 minutes of regular session time, not a clock hour that crosses a break | Same as `M1` until the session clock and labels exist. |
| `SESSION` | Remainder of the regular session, endpoint at the official close | Same as `M15`. |
| `NEXT_SESSION` | Next regular session's official close | Same as `M15`. |

The label definition, the threshold `T`, and the endpoint rule stay in the forecasting spec. A horizon without those definitions is `NOT_AVAILABLE`. The shipped config does not enable `M1`, `M5`, or `H1`.

One model version is for one underlying and one horizon. A NIFTY `M15` approval is not an approval for SENSEX or for `H1`.

---

## 4. Lifecycle

```text
REGISTERED -> TRAINED -> EVALUATED -> APPROVED_FOR_RESEARCH
                                      -> APPROVED_FOR_PAPER -> APPROVED_FOR_LIVE
Any state -> DEPRECATED
Any state -> DISABLED
```

`APPROVED_FOR_RESEARCH` is not on the path to paper by implication. Paper approval is a separate transition from `EVALUATED` or from `APPROVED_FOR_RESEARCH`, with its own evidence and its own audit row. Live approval is a separate transition from `APPROVED_FOR_PAPER`.

Earlier documents used `EXPERIMENTAL` and `VALIDATED`. Those names are retired. `REGISTERED` or `TRAINED` covers what `EXPERIMENTAL` meant. `EVALUATED` covers what `VALIDATED` meant. Stored rows, when they exist, must use the names in this section.

| State | Required evidence | Allowed use |
|---|---|---|
| `REGISTERED` | Family id, input schema, output schema, and a code entry point. No artifact required. | Listed as not runnable. Cannot be selected for inference. |
| `TRAINED` | Artifact location and checksum, training-data version, training config, training timestamp. | Inspection only. Metrics are `NOT_EVALUATED`. Cannot pass a model gate. |
| `EVALUATED` | Walk-forward report on training and validation folds. Frozen `T`. Baselines present. Untouched test dates were written down before fitting and were not used to choose `T` or hyperparameters. | Research comparison. Cannot activate paper or live. |
| `APPROVED_FOR_RESEARCH` | `EVALUATED`, plus an explicit person action. | Research selection for replay and display. Paper and live stay off. |
| `APPROVED_FOR_PAPER` | Untouched-test report. The forecasting spec's predeclared gate against the stronger baseline is met. A person records the approval. The scope fields below are set. | Paper entries only, and only inside that scope. |
| `APPROVED_FOR_LIVE` | Everything required for paper, plus a second explicit approval of this version. Paper approval is not this state. | Live entries still have to pass the risk engine, the server flag, and confirmation. |
| `DEPRECATED` | A person records the reason. | Historical comparison. No new inference and no new activation. |
| `DISABLED` | A person records the reason, or drift policy moves the version here. | No inference and no activation. Rollback cannot target a disabled version. |

An LLM recommendation, a finished training job, or a research selection is not a transition.

Drift (`model_health = DRIFT`) does not delete the version. It blocks the model gate until a person reviews it. The system does not auto-promote a retrain.

---

## 5. Approval scope

An approval row is valid only for the combination stored on it:

- underlying
- horizon
- model version id
- feature schema version
- strategy configuration revision

The strategy configuration revision is the config revision that held the label threshold, cost assumptions, and promotion gates used in the evaluation. Changing that revision does not silently extend the approval.

---

## 6. Three operations

These are different requests. The studio must not use one control for all three.

| Operation | What changes | What it must not do |
|---|---|---|
| Research selection | The operator's research pointer for one underlying and horizon | Change the paper slot or the live slot. Run a live order. |
| Paper activation | The paper slot for one scope, and only from `APPROVED_FOR_PAPER` or `APPROVED_FOR_LIVE` | Grant live trading. Change a run that has already pinned a version. |
| Live approval | The lifecycle state and the live slot, only through the separate live-readiness path | Become available because paper activation succeeded. The control stays disabled until the live milestone's readiness checks are implemented and the open compliance questions are closed. |

The live control is specified so a later milestone can build it. This specification does not mark that control as working.

---

## 7. Pinning, rollback, and in-flight runs

Every analysis run and every forecast row stores the model version id at start, before inference. The LangGraph thread described in `docs/LANGGRAPH_ORCHESTRATION_SPEC.md` copies that same id into graph state. A studio change after the pin does not alter that run.

Rollback inserts a new activation row that points at the previous approved version for that scope. It does not rewrite old forecasts, old orders, or old checkpoints. The previous version must still be `APPROVED_FOR_PAPER` or `APPROVED_FOR_LIVE` for the same scope and must not be `DISABLED`.

Activation of a scope takes a row lock so two requests cannot install different versions. The loser receives `ACTIVATION_CONFLICT`.

---

## 8. Registry metadata

Each model version row holds:

| Field | Rule |
|---|---|
| `model_id` | Stable id, unique. |
| `family` | Section 2. |
| `version` | Monotonic label. A new artifact is a new version. |
| `artifact_uri` | Location of the fitted artifact. Null while `REGISTERED`. |
| `artifact_checksum` | Required once an artifact exists. |
| `supported_underlyings`, `supported_horizons` | Lists. Selection outside them is `UNSUPPORTED_SCOPE`. |
| `feature_schema_version` | Required. |
| `output_schema_version` | The forecast object in the forecasting spec. |
| `training_data_version` | Dataset card id. Null if not trained. |
| `training_config` | Hyperparameters and the frozen `T`. Null if not trained. |
| `evaluation_report_id` | Null until `EVALUATED`. The report is a separate object, not a pasted blob with no id. |
| `calibration_report_id` | Null until calibration is computed. The studio then shows `NOT_EVALUATED`. |
| `approval_state` | Section 4. |
| `created_at`, `trained_at`, `last_evaluated_at` | Timestamps. Missing values stay null. |
| `limitations` | Text from the evaluation report, or `NOT_AVAILABLE`. |
| `last_successful_inference_at` | Null until a real inference succeeds. |
| `health` | `HEALTHY`, `DRIFT`, `UNAVAILABLE`, or `UNKNOWN`. |

The studio shows those fields and the active paper slot, the research pointer, and the live slot. It does not invent the active slot when none is set.

Forecast display, when a run has a real forecast row:

- `p_up`, `p_down`, and `p_range` when the three-class label is in force. They must sit in `[0, 1]` and sum to 1 within `0.01`, or the forecast is qualitative and the probabilities are null.
- `expected_return` when the frozen class-conditional means exist; otherwise `NOT_AVAILABLE`.
- `interval_low` and `interval_high` as uncertainty when the artifact defines them; otherwise `NOT_AVAILABLE`.
- Forecast timestamp, data timestamp, freshness, model version, and health.
- Feature contribution only when that version's output schema includes a declared method. Otherwise `NOT_AVAILABLE`.

A bullish class is not `BUY_CE`. A bearish class is not `BUY_PE`. The studio labels the number as a forecast, separate from calibration, option value, trade eligibility, and order status.

---

## 9. HTTP contract

All routes require the operator session and CSRF on writes, as in `docs/DESIGN.md` section 16. List and read routes do not change state.

Write requests accept an `Idempotency-Key`. A repeat with the same key, same actor, and same body returns the original result. The same key with a different body returns `IDEMPOTENCY_CONFLICT`.

| Method | Path | Rule |
|---|---|---|
| GET | `/api/models` | Registry rows. Query `underlying` and `horizon` filter to supported scope. Empty registry returns an empty list. Static paths (`compare`, `activations`, `evaluation`) are registered before `/{model_id}`. |
| GET | `/api/models/{model_id}` | One version family, including version history. Unknown id is `UNKNOWN_MODEL`. |
| GET | `/api/models/{model_id}/versions/{version}` | Metadata in section 8. Missing reports are null. |
| GET | `/api/models/compare` | Query version ids. Returns stored metrics only. A version without a report contributes `NOT_EVALUATED`, not a zero. |
| POST | `/api/models/research-selection` | Body: model version, underlying, horizon. Allowed from `EVALUATED` and any approved state that is not `DISABLED`. Does not change paper or live slots. |
| POST | `/api/models/paper-activation` | Body: model version, underlying, horizon, expected feature schema, expected strategy revision. Rejects any version that is not `APPROVED_FOR_PAPER` or `APPROVED_FOR_LIVE` for that full scope. |
| POST | `/api/models/paper-rollback` | Restores the previous activation for that scope under section 7. |
| POST | `/api/models/{model_id}/versions/{version}/evaluate` | Requests an evaluation job. Does not approve. If the trainer is not implemented, the route returns `NOT_IMPLEMENTED`. |
| GET | `/api/forecasts` | Stored forecasts. Query underlying, horizon, run id. |
| GET | `/api/models/activations` | Activation and rollback history. |

Error codes include `UNKNOWN_MODEL`, `UNSUPPORTED_SCOPE`, `MODEL_NOT_APPROVED`, `ACTIVATION_CONFLICT`, `WORKFLOW_PINNED`, `IDEMPOTENCY_CONFLICT`, `NOT_IMPLEMENTED`, and `NOT_EVALUATED`.

There is no live-activation route in the current API contract. Adding one before the readiness milestone is a defect.

---

## 10. Tables

- `model_definitions` — family, code entry, schemas.
- `model_versions` — section 8, with `evaluation_report_id` and `calibration_report_id` as references.
- `evaluation_reports` — fold metrics, test-period dates, baseline comparison. One row per finished evaluation.
- `model_approvals` — state transition, actor, scope, timestamp.
- `model_activations` — research pointer or paper slot, previous version id, actor, timestamp.
- `forecast_runs` — pinned model version, input dataset version, output forecast id.

Artifacts and full metric tables stay in object storage or the report row. They are not copied into the activation row.

Audit events already defined for config cover these writes: `model.research_select`, `model.paper_activate`, `model.paper_rollback`, `model.approve`, `model.disable`.

---

## 11. Tests

The cases are in `docs/IMPLEMENTATION_PLAN.md` under model registry. A passing test is not evidence of forecast skill.

---

## 12. What M5 implements

The spec above remains the target contract. This section records the smaller surface that exists now, and the conflicts that were resolved in favor of the safety constraints.

Storage is one checksummed JSON document under `var/registry`, not the SQL tables in section 10. The project already stores datasets and experiments as JSON artifacts. The registry file uses an exclusive lock, a revision number, and an atomic replace. A stale `expected_revision` returns `REVISION_CONFLICT`. A failed update does not replace the file. The document checksum is checked on read. A caller cannot supply an artifact path. Fitted weights stay inside the registry row; the row's `artifact_uri` is null and the M3 or M4 file is not rewritten.

`model_id` is `{experiment_key}:{instrument}:{horizon}`. The spec family id is stored beside it: `majority_class` is `base_rate`, and `last_return_sign` is `persistence`. A new fit or a new experiment creates the next version, `v1`, `v2`, and so on. The same artifact registered again returns the existing version and does not change its fitted state. An untrained definition is `REGISTERED` with null training fields. A verified fit is `TRAINED`. Registration does not set `EVALUATED`.

`EVALUATED` is an explicit transition. The evidence must be a linked `m4-expanding-1` artifact whose successful folds contain all three models, did not use the test for selection, and scored that version on every successful fold. An M3 holdout can be registered and inspected, but it is not that evidence. This follows section 4's walk-forward requirement rather than treating the holdout as a finished evaluation.

`APPROVED_FOR_RESEARCH` is a further explicit transition. It requires `confirm=true`, a reason, and, for `SYNTHETIC` or `DOCUMENTED_SAMPLE`, an acknowledgement that the result is not real-market evidence. A request that sets market verification or a performance claim is refused. Being the selected model, or having the lowest log loss, does not approve anything.

`DEPRECATED` and `DISABLED` are explicit transitions with a reason. `APPROVED_FOR_PAPER` and `APPROVED_FOR_LIVE` are refused. `POST /api/models/paper-activation` and `POST /api/models/paper-rollback` return `MODEL_NOT_APPROVED` and do not create a slot. There is no live-activation route. `POST /api/models/{id}/versions/{version}/evaluate` returns `NOT_IMPLEMENTED`.

Research selection is allowed from `EVALUATED` or `APPROVED_FOR_RESEARCH` for the version's own instrument and horizon. It appends a research pointer. The paper slot and the live slot stay null. The studio at `/studio` lists registry rows, saved M3 and M4 artifacts, per-fold and aggregate metrics, and the research control. It does not show a fabricated forecast. Holdout and walk-forward results are compared only when the dataset checksum, target, feature set, instrument, horizon, origin, and evaluation version all match. Otherwise the page shows why they are incompatible and does not rank them. Macro averages and pooled metrics stay in separate fields. Undefined metrics stay null.

Write routes require the session and the CSRF header. `Idempotency-Key` repeats the original result. The same key with a different body returns `IDEMPOTENCY_CONFLICT`. Registry writes also append an audit event. The four trading-readiness flags stay false.
