# Forecasting and backtest specification

**Status:** M3 implements an experimental binary next-bar target and three baselines on `ohlc-1` datasets. No three-class model has been trained. No result here is a measured edge or a trading result. `forecast_ready` stays false. No threshold, weight, or gate in this document is an empirically proven optimum.
**Parent:** `docs/DESIGN.md`
**Companions:** `docs/MODEL_REGISTRY_AND_STUDIO_SPEC.md`, `docs/LANGGRAPH_ORCHESTRATION_SPEC.md`, `docs/OPTIONS_EXPECTED_VALUE_SPEC.md`, `docs/RISK_AND_EXECUTION_SPEC.md`, `docs/DATA_SOURCE_MATRIX.md`

The forecast predicts the **underlying**. It does not output BUY CE or BUY PE. Option value is a later calculation. A high directional accuracy is not evidence of profit.

---

## 1. Responsibilities

| Stage | Owner | May emit `p_up`, `p_range`, `p_down` |
|---|---|---|
| A. Data and features | Deterministic feature code | No |
| B. Statistical and ML forecast | `quant_forecast` service | Yes, and only from a model artifact |
| C. Specialist analysis | M8 LangGraph evidence nodes. M8.1 records a failed node as `NODE_FAILED` and still returns `NO_TRADE`. The graph is not a model and does not emit a probability. Cursor agents are not called. | No |
| D. Forecast fusion | `forecast_fusion` service | Only by copying an approved model output, or by an approved fusion artifact |
| E. Option expected value | Options engine | No. It may emit a **modelled** probability that an option scenario is profitable. That number is not a calibrated underlying probability. |
| F. Risk approval | Risk engine | No |
| G. Broker execution | Execution service | No |

Specialist agents return facts, features, scenarios, and uncertainty. Agreement among them is not independent evidence. They often restate the same price, the same article, or the same feature the model already used.

---

## 2. Tasks

Each task is trained, calibrated, promoted, and reported on its own. An M15 model is never shown as a session forecast.

Candidate tasks, configurable, not assumed optimal. The studio lists a horizon only when the registry supports it. `M1`, `M5`, and `H1` stay unavailable until a dataset version and an evaluation exist. None of these tasks has been fit.

| Task id | Horizon | Endpoint | Ready for a paper selector |
|---|---|---|---|
| `M1` | 1 minute of regular session time | Next completed checkpoint at or after t+1m | No. Index 1-minute history is unverified. |
| `M5` | 5 minutes of regular session time | Next completed checkpoint at or after t+5m | No. |
| `M15` | 15 minutes of regular session time | Next completed checkpoint at or after t+15m | Only after a scoped approval. |
| `M30` | 30 minutes of regular session time | Next completed checkpoint at or after t+30m | Only after a scoped approval. |
| `H1` | 60 minutes of regular session time | Next completed checkpoint at or after t+60m, without crossing a session break | No, until the session clock is defined for this task. |
| `SESSION` | Remainder of the regular session | Official session close | Only after a scoped approval. |
| `NEXT_SESSION` | Next regular session | Next session's official close | Only after a scoped approval. |

The operator may disable a task in config. Disabling a task removes it from trading. It does not retarget another model. A model approved for one row of this table is not approved for another row or another underlying.

### 2.1 What every task must store

For each training row and each live forecast:

| Item | Rule |
|---|---|
| Underlying | `NIFTY`, `SENSEX`, or `BANKNIFTY`. One model per underlying per task. |
| Observation timestamp | Exchange timestamp of the last **completed** candle used. The forming candle is not an input. |
| Forecast horizon | The task id. |
| Target calculation | Simple return `R = P(endpoint) / P(observation) - 1`, using the close of those candles. |
| Label | `up` if `R > T`, `down` if `R < -T`, `range` otherwise. `T` is the frozen threshold for that task and underlying. |
| Data cutoff | No feature, news revision, or instrument attribute with a known-time after this instant. |
| Market calendar | Official session clock and holiday list for that exchange. M2 does not have that calendar. It records the fixture calendar and `calendar_authoritative: false`. |
| Evaluation id | Walk-forward fold id, or `LIVE` plus the model version. |

`P(observation)` is the close at the observation timestamp, not the last traded price of a still-forming bar.

### 2.2 Closures and missing candles

- Session time does not run through the closing auction gap, weekends, or holidays. A 15-minute task whose endpoint would fall after the session close is **not** labelled by jumping to the next day. That row is dropped. Only `NEXT_SESSION` crosses a close, and its endpoint is the next regular session's close.
- If the checkpoint candle is missing, the row is dropped. It is not filled from a neighbouring bar. M2 goes further for dataset emission: a missing M15 interval fails validation and no feature artifact is written.
- A gap inside the feature window longer than one bar interval nulls the features that need a continuous window. Those rows may still train only if the model artifact's missing-value policy was the one used in validation. Live inference uses that same policy. There is no second, friendlier policy at inference. M2's policy is `explicit_status_no_fill`. The dataset builder does not emit a series that failed the missing-candle check.
- Corporate-action or index-level adjustments follow the vendor's stated method and are stored on the dataset version. A series with an unknown adjustment method is not used for training.

### 2.3 Thresholds

`T` is not a tuned constant hidden in code. Earlier drafts used 0.05%, 0.08%, 0.15%, and 0.40% as illustrations. Those numbers are **not** approved.

Protocol:

1. On the training and validation folds only, evaluate a configured candidate grid of `T`.
2. Selection criterion is also configured and written on the dataset card before the run: primary metric is log loss or Brier score of the resulting three-class problem, with a constraint that each class has at least a configured minimum count. The criterion is a research gate. It is not a claim that the chosen `T` is optimal out of sample.
3. Freeze `T`, the class-conditional mean returns, and the feature list **before** the untouched test period is opened.
4. The test period is not used to change `T`.
5. The frozen `T` and the frozen class-conditional mean returns are stored on the model version. The options engine needs those means. If they are absent, option expected value is unavailable.

Changing `T` creates a new dataset version and a new model version. It does not edit history.

The three-class protocol above is not implemented. M3 does not choose `T`.

### 2.4 Experimental binary target `binary-1`

M3 adds a separate target so the evaluation code can be tested before a threshold exists.

| Field | Value |
|---|---|
| Target id | `m15_next_close_direction` |
| Target version | `binary-1` |
| Interval | M15 |
| Horizon | The next completed M15 close |
| Formula | `future_return[t] = close[t+1] / close[t] - 1`. `direction[t] = 1` when that return is positive, and `0` otherwise. |
| Zero returns | Class `0`. The label report counts them and their share of rows that have a future candle. |
| Availability | The label exists only at `bar_end[t+1]`, and only when that candle is complete (`retrieved_at >= bar_end`). |
| Final bar | No label is created. |
| Join key | `instrument_id` plus the feature `as_of`, which is `bar_end[t]`. |

Features at `t` still stop at `bar_end[t]`. The close that forms the label is not an input to that row. This target is not the task table in section 2 and is not a claim that the next bar is predictable.

`session_confirmed` stays out of the model matrix. It is a calendar flag. The model features are the other eleven `ohlc-1` outputs. A row is dropped when any of those eleven is not `VALID`. Nothing is imputed.

---

## 3. Features

Point-in-time only. A feature timestamp must be less than or equal to the data cutoff.

### 3.1 Implemented set `ohlc-1`

M2 calculates only the features in this table. Each value is a number with status `VALID`, or null with one of `WARMUP`, `INVALID_INPUT`, `MISSING_OBSERVATION`, `CALENDAR_UNKNOWN`, or `INCOMPLETE_CANDLE`. Those statuses are not interchangeable. Nothing is forward-filled, replaced with zero, or copied from a neighbouring bar. `ret_5` is not implemented; `ret_1` and `ret_3` already cover close-to-close returns at two horizons.

| Output | Formula | Inputs | Lookback | Warm-up |
|---|---|---|---|---|
| `ret_1` | `close[t] / close[t-1] - 1` | close | 1 prior bar | first bar |
| `ret_3` | `close[t] / close[t-3] - 1` | close | 3 prior bars | first three bars |
| `sma_3` | mean of `close[t-2]` through `close[t]` | close | 3 bars including t | fewer than 3 bars |
| `sma_5` | mean of `close[t-4]` through `close[t]` | close | 5 bars including t | fewer than 5 bars |
| `close_vs_sma_5` | `close[t] / sma_5[t] - 1` | close and `sma_5` | same as `sma_5` | same as `sma_5` |
| `sma_3_minus_sma_5` | `sma_3[t] - sma_5[t]` | both means | 5 bars | until both means exist |
| `ret_std_5` | sample standard deviation, divisor n-1, of `ret_1[t-4]` through `ret_1[t]` | close | 6 closes | until five returns exist |
| `atr_3` | mean of the last three true ranges. True range is `max(high-low, abs(high-previous close), abs(low-previous close))`. This is not Wilder smoothing. | high, low, close | 4 bars | until three true ranges exist |
| `hl_range_vs_prev_close` | `(high[t] - low[t]) / close[t-1]` | high, low, previous close | 1 prior bar | first bar |
| `oc_return` | `close[t] / open[t] - 1` | open, close | none | none |
| `close_position` | `(close[t] - low[t]) / (high[t] - low[t])` | high, low, close | none | `INVALID_INPUT` when high equals low |
| `session_confirmed` | `1` when the fixture calendar lists the bar date | bar start and calendar | none | `CALENDAR_UNKNOWN` when the date is not listed |

Missing behaviour: a gap inside a required span is `MISSING_OBSERVATION` if a row is computed directly. The dataset builder does not emit a dataset when validation reports a missing candle, duplicate timestamp, out-of-order candle, invalid OHLC, or a date marked `NOT_A_SESSION`. An incomplete candle (`retrieved_at` before `bar_end`) also prevents a dataset. A failed build writes no artifact and returns `ok: false`.

Availability: the row `as_of` is the observation candle's `bar_end`. A candle contributes only when its own `bar_end` is at or before that cutoff and `retrieved_at` is at or after its `bar_end`. Windows are trailing. They include the observation candle and exclude later candles. There is no centered window and no scaler fitted on another part of the sample. `provider_timestamp` is not treated as the completion time. Later revisions of a print are not stored, so this is not a full point-in-time archive.

The fixture calendar version is `fixture-m1`. It is not authoritative. `session_confirmed` is the field that stays unavailable when the date is unknown. Price features can still be computed from the OHLC of those bars. The dataset records `calendar_authoritative: false` and does not treat the unknown date as a confirmed session. No bars are created for closures.

`forecast_ready` on every feature artifact is false. Synthetic and documented-sample origins are copied onto the dataset and each row. Mixed origins are rejected. The quiet-day fixture can produce feature rows and remains synthetic. It is not a forecasting dataset. The feature artifact still stores untouched test dates as null. An M3 experiment records its own split window and does not rewrite the dataset, because rewriting it would change the dataset id.

Feature version is `ohlc-1`. Pipeline version is `m2`. Dataset schema version is `1.0`. The dataset id is the SHA-256 of the canonical manifest body, including the source candles and this configuration. Rebuilding from those stored candles reproduces the id. Metadata that identifies the series, configuration, validation, and checksum is in the artifact file. It is not copied into Postgres.

### 3.2 Not implemented

These were listed for later models. They are not calculated:

- Session VWAP. The M1 candle volume is often null, and VWAP is not defined here.
- India VIX level and change.
- Breadth.
- USD/INR return and Brent return.
- The three-class label and threshold `T` from section 2.3.

M3 does calculate the `binary-1` label and a training-only z-score for logistic regression. A computed feature or a fitted coefficient is not evidence that it predicts a return.

The model card will list every feature and its source id once a model exists. A specialist narrative about VIX or crude is not an extra feature and is not a second probability.

Missing optional features stay missing. They are not filled with a future print or with zero unless zero was the validated missing-value policy for that column. The M2 policy is `explicit_status_no_fill`, which does not use zero.

News text is not a numeric feature in the first models. A later news feature must use the article version whose `published_at` and fetch time are both at or before the cutoff. A correction that arrives later is invisible to that row.

---

## 4. Models

Train in this order. Do not add a family until the previous one has a finished walk-forward report on real market data. Random forests, LSTM/GRU, TCN, a small transformer, TimesFM, and Chronos-2 are optional and stay unregistered until the justification in the registry spec exists.

M3 implements the first three families for `binary-1` only. They are experiment artifacts, not registry rows, and none is approved. LightGBM, XGBoost, and the later families are not implemented.

1. Majority class: the training-fold frequency of direction `1`. The hard class is `1` only when that frequency is greater than one half. A tie predicts class `0`. Validation and test labels are not used.
2. Last-return sign, experiment key `last_return_sign`. This is the persistence baseline. The hard class is `1` when `ret_1 > 0`, otherwise `0`. A zero `ret_1` predicts class `0`. If `ret_1` is missing, the model fails and does not guess. Probabilities are a Laplace map, `(count + 1) / (total + 2)`, fit on the training fold only and not refit on the test period.
3. Logistic regression on the eleven price features in section 3.1, excluding `session_confirmed`. Rows with a non-finite or non-`VALID` feature are excluded. Features are z-scored with the training sample standard deviation. A column whose sample variance is at most `1e-18`, including an exact constant, is recorded as zero variance, stored with scale `0`, and scaled to `0`. It is not divided by a tiny number. A non-finite variance rejects the fit. Coefficients are L2-regularized Newton steps (`l2 = 1`, intercept not penalized, at most 25 steps). A step is converged when the largest absolute coefficient change is below `1e-8`. A singular Hessian, a step larger than `1e6`, a non-finite coefficient, or exhaustion of the iteration limit returns `SINGULAR_HESSIAN`, `ILL_CONDITIONED`, `INVALID_FIT`, or `NON_CONVERGED`. Those failures do not keep coefficients or probabilities. The class threshold stays fixed at a probability greater than one half and is not taken from the test period. A one-class training fold returns `SINGLE_CLASS` and no probabilities. No seed draws rows. The recorded seed is `0`.
4. LightGBM or XGBoost, one family, only if its walk-forward log loss or Brier score improves on the logistic model by more than a **configured research gate** on validation folds, and the untouched test is not worse than logistic on the same metric. The gate is not a proven universal margin. Not implemented.
5. A TCN or a small transformer only when the written justification and the data volume are on the model version. Not implemented.
6. TimesFM or Chronos-2 only when a pinned upstream version, a licence note, and a suitability note are on the model version. Not implemented.
7. An ensemble only when it improves on the best single model under the same predeclared metric on the untouched test. Not implemented.

The M3 split is one chronological holdout, evaluation version `m3-holdout-1`. Rows are sorted by `as_of` and are not shuffled. Default fractions are 60% train and 20% validation, with the remainder as test. The embargo then removes a training row whose `label_available_at` is at or after the first validation `as_of`, and a validation row whose `label_available_at` is at or after the first test `as_of`. On contiguous M15 bars those are the last raw training row and the last raw validation row: their labels are the first candle of the next period. The removed keys are stored on the split manifest. Defaults also require at least 8 training, 4 validation, and 4 test rows after that embargo. A short series returns `INSUFFICIENT_DATA` and no artifact. These minima are harness settings, not a sample-size recommendation.

M4 adds evaluation version `m4-expanding-1`. It reuses the M3 models, metrics, embargo, and artifact rules. It does not replace the single holdout. The walk-forward policy is an expanding training window with fixed validation and test sizes. Fold `k` uses raw indexes `[0, initial_train_size + k * step_size)` for training, the next `validation_size` rows for validation, and the next `test_size` rows for test. `step_size` must be at least `test_size`, so test windows do not overlap and the pooled predictions do not count a row twice. A fold that would end past the series is not emitted and is not shortened. Defaults are an initial training window of 9 rows, validation 5, test 4, and step 4, with the same post-embargo minima as M3: 8, 4, and 4. The initial window is 9 because the one-bar embargo removes a training row and the minimum is not lowered to compensate. A fold that is still short after the embargo is stored as `INSUFFICIENT_AFTER_EMBARGO` with its original raw counts. It is not resized. If the series cannot hold even one raw window, the result is `INSUFFICIENT_DATA` and no artifact.

A later fold may train on rows that an earlier fold tested. Those rows now precede the later fold's own test window. An earlier fold is not refit from a later test.

Each fitted model is scored on the same validation rows and the same test rows. Validation log loss, then Brier score, then the model name, chooses one model. The tolerance remains `1e-12`. Test scores do not make that choice. Both categories are stored: `model_results` holds every model, including a structured failure when a fit does not score, and `selected_model_result` holds only the chosen model's validation and test metrics. A failed model is not given another model's rows and is not silently replaced. If every model fails, the fold is `NO_SELECTABLE_MODEL`. If scored models disagree on the observation count, the fold is `METRIC_ROW_MISMATCH` and nothing is selected.

Across folds, the macro mean, median, and sample standard deviation give each successful fold equal weight. Undefined metric values are omitted. They are not converted to zero. The standard deviation is null when fewer than two folds define that metric. The pooled metrics concatenate the selected model's test predictions. That pool is a different object from the macro average, and it is only built when the test windows are disjoint. Confusion matrices stay on each fold. They are not averaged. The pooled confusion matrix is only the one inside the pooled metric object. A computed log loss, Brier score, or calibration table does not mean the probabilities are calibrated. `probabilities_are_calibrated` stays false.

The walk-forward id is the checksum of the canonical body. The body copies the dataset id and checksum and does not rewrite the dataset. It has no file-write timestamp. The store writes only `{store_root}/{walkforward_id}.json` and rejects `path`, `output_path`, `artifact_path`, and `file`. Loading checks the checksum, `binary-1`, `ohlc-1`, `m4-expanding-1`, and false `forecast_ready`, `paper_approved`, `live_approved`, and `real_market_data_verified`. Each experiment and walk-forward artifact records `data_category`: `SYNTHETIC`, `DOCUMENTED_SAMPLE`, or `UNVERIFIED_PROVIDER`. M6 does not emit `VERIFIED_HISTORICAL`. A request that requires verified history is rejected. A dataset that claims `real_market_data_verified` is rejected. Synthetic and `DOCUMENTED_SAMPLE` runs stay marked as non-market evidence. A `PROVIDER` origin still does not verify the series.

Labels inside one test window still overlap by one bar. M4 does not thin those rows to non-overlapping decision points. The embargo applies at the train/validation and validation/test boundaries only. Multiclass Brier, regime buckets, and a profitability report are not part of this harness.

Synthetic and `DOCUMENTED_SAMPLE` series may exercise this harness. Their origin and `data_category` are stored on the experiment and on the walk-forward artifact. They do not verify real-market performance. `PROVIDER` remains `UNVERIFIED_PROVIDER`. M6 can build `ohlc-1` features from a source-candle dataset only when that dataset names bar ends, passes the quality report, and does not claim verified market history. A Groww historical response can be quarantined and inspected by a read-only diagnostic. It stays ineligible for this harness while the candle boundary and timezone are unverified. The 14 Oct 2026 re-read did not establish either fact, and M7.2 found no support reply, so no timestamp mapping is applied. No verified historical series has been evaluated. A later contract checklist left the NIFTY 15-minute timezone and candle boundary unverified, so M2, M3, and M4 were not run on market history. `real_market_data_verified` stays false. Comparisons do not mix `data_category` values: the registry compare already treats origin as part of compatibility.

Choosing among later families on the untouched test more than once spends that test. Each additional comparison is recorded on the evaluation report. It is not a fresh untouched result.

### 4.1 Binary metrics implemented in M3

For `binary-1`, the positive class is direction `1`. On identical eligible rows, each fitted model reports observation count, positive prevalence, accuracy, balanced accuracy, precision, recall, F1, log loss, Brier score, the confusion matrix, and a five-bin probability histogram. Log loss and Brier both start from the model probabilities. Brier uses them unchanged. Log loss applies them inside the logarithm after clipping to `[1e-15, 1-1e-15]` and records that floor. A metric that is undefined, such as precision with no predicted positives or balanced accuracy with one class missing, is null with a status. It is not stored as zero.

Calibration bins are computed only when a scored split has at least 20 rows. Otherwise the status is `INSUFFICIENT_OBSERVATIONS`. `probabilities_are_calibrated` stays false. No significance test is implemented.

The experiment artifact is canonical JSON. Its checksum is the experiment id. The body records the dataset id, `ohlc-1`, `binary-1`, `m3-holdout-1`, the split window, the model configuration, and the dataset retrieval time as `created_at`. It does not add a file-write timestamp, so the same dataset and configuration keep the same id. The runner returns the artifact and does not accept a file path. A store writes only `{store_root}/{experiment_id}.json` and rejects an artifact that carries `path`, `output_path`, `artifact_path`, or `file`. Loading checks the checksum, the feature set, the target, and a false `forecast_ready` flag. There is no pickle. A successful train does not set paper or live approval.

`forecast_ready` stays false. The readiness block separates pipeline attestation (not set by the runner), training, evaluation, verified real-market data, out-of-sample scoring, calibration computed, calibration accepted, and production approval. The last three real-market and approval flags stay false.

The live forecast object below is still not emitted. M3 does not produce `p_up`, `p_range`, and `p_down`.

Each live forecast is a typed object:

| Field | Rule |
|---|---|
| `underlying`, `horizon` | Task identity |
| `observation_timestamp`, `data_cutoff` | Section 2.1 |
| `p_up`, `p_range`, `p_down` | In `[0, 1]`. Sum within `0.01` of 1. Otherwise the forecast is rejected and treated as qualitative. |
| `expected_return` | Training-fold class-conditional mean, probability-weighted. Null if those means were not frozen. |
| `interval_low`, `interval_high` | Empirical quantiles of training-fold returns, or null. Not a promise of the future range. |
| `model_name`, `model_version` | Artifact id and content hash |
| `calibration_snapshot` | Brier, log loss, and the reliability summary from the promotion report |
| `data_quality` | `PASS`, `WARN`, or `FAIL` from the quality gate at cutoff |
| `model_health` | `HEALTHY`, `DRIFT`, or `UNAVAILABLE` |
| `promotion_state` | Registry lifecycle in `docs/MODEL_REGISTRY_AND_STUDIO_SPEC.md` |
| `is_qualitative` | True when no approved calibrated model exists. Probabilities are then null. |

If `is_qualitative` is true, the trade decision is `NO TRADE`. The report may still describe the tape.

---

## 5. Evaluation

Chronological walk-forward only. Folds are expanding or sliding windows with a purge: any training label whose endpoint is after the validation observation time is removed. The embargo is at least the task horizon. Random splits are forbidden.

M4 implements that purge for `binary-1` as expanding windows with fixed validation and test lengths, evaluation version `m4-expanding-1`. The fold boundaries, embargo keys, and minima are in section 4. Comparisons use timezone-aware instants, so a UTC stamp and an Asia/Kolkata stamp of the same moment are the same boundary. A naive or repeated timestamp is rejected. This implementation does not claim the multiclass report below, and it does not convert an overlapping intraday label into an independent sample.

Overlapping intraday labels are not treated as independent samples. The intended reported sample size is the count of non-overlapping decision points, and the fold metrics are also computed on that thinned set. That thinning is not implemented. M4 scores every eligible row inside the fold and applies the embargo only at the period boundaries.

Hold out a final test period that is not used for features, thresholds, hyperparameters, or fusion. Its dates are written down before training starts.

Report, for each task and underlying:

- Brier score and log loss, multiclass.
- A reliability diagram per class, or a binned table if the UI has no chart yet.
- Directional accuracy and balanced accuracy, with the definitions printed (argmax class versus realized class).
- Precision and recall for `up` and for `down` separately. Range is not hidden inside accuracy.
- The same metrics inside volatility buckets, time-of-day buckets, expiry days, and days on the configured event calendar.
- The same metrics for the base-rate and persistence baselines.
- Signal frequency, turnover of the argmax class, and forecast stability between adjacent decision times.
- Behaviour when required features are missing, using the artifact's stored missing-value policy.

Directional accuracy is not a selection metric and is not a profit metric. A candidate is promoted only when it beats the stronger of the base-rate and persistence baselines on the predeclared Brier or log-loss gate on the untouched test. If it does not, it stays unapproved and the standalone path remains the baseline, or qualitative `NO TRADE` when no baseline is approved.

Strategy results, when they are reported, come from the options engine and the cost model. They include brokerage and other charges, bid-ask spread, slippage, missed fills, partial fills, drawdown, a stated risk-adjusted return, tail loss, and a cost-sensitivity rerun. Market impact is reported only when an impact model is specified. Until historical option contracts exist, those strategy numbers are `NOT_EVALUATED` and cannot approve a model. That history is not verified (`docs/DATA_SOURCE_MATRIX.md`).

---

## 6. Promotion

Lifecycle names, transitions, and the separation of research selection from paper activation are `docs/MODEL_REGISTRY_AND_STUDIO_SPEC.md` section 4. This section states the evidence those transitions require. The retired names `EXPERIMENTAL` and `VALIDATED` are not written on new rows.

| Target state | Evidence required |
|---|---|
| `EVALUATED` | Walk-forward report on validation folds, frozen `T`, baselines present, untouched test dates stored and not used for selection. |
| `APPROVED_FOR_RESEARCH` | `EVALUATED`, plus an explicit person action. Display and replay only. |
| `APPROVED_FOR_PAPER` | Untouched test report exists. Configured research gates on Brier or log loss versus the stronger baseline are met on that test, for this underlying, horizon, feature schema, and strategy revision. A person records the approval. |
| `APPROVED_FOR_LIVE` | Everything above, plus an explicit second approval naming this version. Not implied by paper approval. |

An LLM recommendation is not evidence for any transition. Training completion is not an approval.

`model_health = DRIFT` when the trailing scored window (configured length, starting example 20 sessions, not a proven window) has worse Brier than the stored baseline by more than a configured research gate. Drift, a failed calibration check, or a missing feature set disables ML-driven entries until a person reviews the version. The system does not auto-promote a retrain.

A silent change of `model_version` on an approved slot is forbidden. Promotion is a new row. The previous version remains addressable for rollback.

---

## 7. Fusion

### 7.1 Baseline

The baseline decision distribution **is** the quantitative forecast for the selected task. `fusion_status = BASELINE_ONLY` unless a fusion artifact is promoted far enough for the current mode: `APPROVED_FOR_PAPER` while the server is in `PAPER`, and `APPROVED_FOR_LIVE` while the server is in `LIVE_TRADING`. Any weaker fusion artifact is ignored and the status stays `BASELINE_ONLY`.

Hand-set weights are not a fusion model. They may be stored as an experiment. They cannot authorize paper or live entries.

Specialist agents do not contribute probabilities. Mapping a trend label or an options comment onto `0.62` is a defect.

### 7.2 Candidate fusion

A candidate may combine the quantitative probabilities with **numeric** point-in-time features that are not already inside the baseline model. The feature list must state this, so VIX is not counted twice.

Any learned fusion model uses the same walk-forward, purge, and untouched-test rules as section 5. It is a model version with its own promotion state.

Before it can be `APPROVED_FOR_PAPER` or `APPROVED_FOR_LIVE` it must, on the untouched test:

- Improve Brier or log loss versus the quantitative baseline by more than the configured research gate.
- Not worsen the configured tail metric (starting definition: mean return in the worst decile of outcomes). The gate values are research settings, not proven constants.
- Pass an ablation: removing each added feature family is reported. A family that does not move the metric is dropped rather than left in as decoration.

### 7.3 Incomplete fusion

If the baseline model is qualitative, fusion is qualitative and the trade decision is `NO TRADE`.

If an approved fusion artifact is missing an input or the fusion service fails, fusion falls back to `BASELINE_ONLY` when the pinned quantitative forecast is approved for the current mode, and it records the missing input. It does not renormalize a partial set of invented component probabilities and it does not build a replacement forecast from agent text. With no approved standalone forecast, the decision is `NO_TRADE`. Missing required market data uses the verdict `INSUFFICIENT DATA`.

Correlated LLM writeups are not inputs.

### 7.4 Contrarian

The contrarian agent runs after the other reasoning agents and before the trade decision is shown. It must list evidence against the leading hypothesis. It cannot change `p_up`, the fusion output, or a risk-engine result.

The entry condition includes a configured price-location rule. That rule is a safety constraint. Its parameters are research gates, not a probability model, and this document does not choose them. If the rule is unset or the latest completed bar does not meet it, the entry condition is missing, the proposal status is `INCOMPLETE`, and nothing is submitted. The contrarian writeup does not satisfy the rule.

---

## 8. Outcome records

`outcome` writes the realized return and realized class after the endpoint exists. It does not rewrite the forecast row. Scoring joins on forecast id where `forecast.created_at` is earlier than the endpoint timestamp.

Drift checks read those joined rows. They do not score a forecast that was inserted after the market had already printed the endpoint.
