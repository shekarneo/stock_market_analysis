"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

function csrf() {
  const match = document.cookie.match(/(?:^|; )imm_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

function metricText(metric) {
  if (!metric || metric.value === null || metric.value === undefined) {
    return metric?.status || "NOT_EVALUATED";
  }
  return String(metric.value);
}

export default function StudioPage() {
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [models, setModels] = useState(null);
  const [experiments, setExperiments] = useState(null);
  const [detail, setDetail] = useState(null);
  const [comparison, setComparison] = useState(null);
  const [picked, setPicked] = useState([]);
  const [reason, setReason] = useState("");
  const [confirmSelection, setConfirmSelection] = useState(false);
  const [message, setMessage] = useState("");

  async function load() {
    const [modelResponse, experimentResponse] = await Promise.all([
      fetch("/api/models"),
      fetch("/api/experiments"),
    ]);
    if (modelResponse.status === 401) {
      setReady(false);
      return;
    }
    setModels(await modelResponse.json());
    setExperiments(await experimentResponse.json());
    setReady(true);
  }

  useEffect(() => {
    load().catch((err) => setError(String(err)));
  }, []);

  async function registerExperiment(kind, experimentId) {
    setError("");
    const response = await fetch("/api/models/registrations", {
      method: "POST",
      headers: { "content-type": "application/json", "x-csrf-token": csrf() },
      body: JSON.stringify({ kind, experiment_id: experimentId }),
    });
    const body = await response.json();
    if (!response.ok) {
      setError(`${body.code}: ${body.message}`);
      return;
    }
    setMessage(body.duplicate ? "Already registered. The version was not changed." : "Registered. Status is not approval.");
    await load();
  }

  async function openVersion(modelId, version) {
    setError("");
    const response = await fetch(`/api/models/${encodeURIComponent(modelId)}/versions/${encodeURIComponent(version)}`);
    const body = await response.json();
    if (!response.ok) {
      setError(`${body.code}: ${body.message}`);
      return;
    }
    setDetail(body);
  }

  function togglePick(item) {
    setPicked((current) => {
      const exists = current.includes(item);
      if (exists) return current.filter((value) => value !== item);
      return current.length >= 2 ? current : [...current, item];
    });
    setComparison(null);
  }

  async function compare() {
    setError("");
    const response = await fetch(`/api/models/compare?items=${encodeURIComponent(picked.join(","))}`);
    const body = await response.json();
    if (!response.ok) {
      setError(`${body.code}: ${body.message}`);
      return;
    }
    setComparison(body);
  }

  async function selectResearch() {
    setError("");
    const response = await fetch("/api/models/research-selection", {
      method: "POST",
      headers: { "content-type": "application/json", "x-csrf-token": csrf() },
      body: JSON.stringify({
        model_id: detail.model_id,
        version: detail.version,
        instrument: detail.instrument,
        horizon: detail.horizon,
        reason,
        confirm: confirmSelection,
      }),
    });
    const body = await response.json();
    if (!response.ok) {
      setError(`${body.code}: ${body.message}`);
      return;
    }
    setMessage("Research pointer updated. Paper and live slots were not changed.");
    setConfirmSelection(false);
  }

  const saved = [
    ...(experiments?.holdout || []).map((item) => ({ ...item, label: "M3 holdout" })),
    ...(experiments?.walk_forward || []).map((item) => ({ ...item, label: "M4 walk-forward" })),
  ];

  return (
    <main>
      <header className="page-head">
        <p className="eyebrow">Research</p>
        <h1>Forecast Model Studio</h1>
      </header>
      <p className="note">
        Research only. Synthetic and documented-sample results are not market performance. A stored score is not
        profitability. Forecast ready, paper approval, live approval, and verified market data stay false. This page
        does not place orders.
      </p>
      {!ready ? (
        <section>
          <h2>Sign in required</h2>
          <Link className="primary" href="/">Sign in</Link>
        </section>
      ) : null}
      {models ? (
        <section>
          <h2>Registry overview</h2>
          <p>
            Registered versions: {models.count}. Forecast ready: {String(models.forecast_ready)}. Paper slot:{" "}
            {models.paper_slot === null ? "NOT_AVAILABLE" : "unexpected"}. Live slot:{" "}
            {models.live_slot === null ? "NOT_AVAILABLE" : "unexpected"}.
          </p>
          {models.count === 0 ? <p>NOT_AVAILABLE. No model version is registered.</p> : null}
          <table>
            <thead>
              <tr>
                <th>Model</th>
                <th>Status</th>
                <th>Origin</th>
                <th>Scope</th>
                <th>Last evaluated</th>
              </tr>
            </thead>
            <tbody>
              {models.models.map((model) => (
                <tr key={model.version_id}>
                  <td>
                    <button type="button" onClick={() => openVersion(model.model_id, model.version)}>
                      {model.experiment_key} {model.version}
                    </button>
                  </td>
                  <td>{model.status}</td>
                  <td>{model.origin || "NOT_AVAILABLE"}</td>
                  <td>
                    {model.instrument} {model.horizon}
                  </td>
                  <td>{model.last_evaluated_at || "NOT_EVALUATED"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}
      {experiments ? (
        <section>
          <h2>Experiment browser</h2>
          <p>M3 holdout rows stay separate from M4 walk-forward rows.</p>
          {saved.length === 0 ? <p>NOT_AVAILABLE. No saved experiment artifact was found.</p> : null}
          {saved.map((item) => (
            <article key={`${item.kind}-${item.experiment_id}`}>
              <h3>{item.label}</h3>
              {item.ok === false ? (
                <p className="error">
                  Unreadable {item.experiment_id}: {item.code}
                </p>
              ) : (
                <>
                  <p>
                    Experiment {item.experiment_id}. Dataset {item.dataset_id}. Target {item.target_version}. Features{" "}
                    {item.feature_set_version}. Evaluation {item.evaluation_version}. Origin {item.origin}. Created{" "}
                    {item.created_at || "NOT_AVAILABLE"}.
                  </p>
                  <p>
                    Failures: {Object.keys(item.failures || {}).length ? JSON.stringify(item.failures) : "none recorded"}
                    . Incomplete: {String(item.incomplete)}.
                  </p>
                  <label>
                    <input
                      type="checkbox"
                      checked={picked.includes(`${item.kind}:${item.experiment_id}:logistic_regression`)}
                      onChange={() => togglePick(`${item.kind}:${item.experiment_id}:logistic_regression`)}
                    />
                    Compare logistic regression
                  </label>
                  <button type="button" onClick={() => registerExperiment(item.kind, item.experiment_id)}>
                    Register artifact
                  </button>
                </>
              )}
            </article>
          ))}
          <button type="button" onClick={compare} disabled={picked.length !== 2}>
            Compare selected results
          </button>
          {comparison ? (
            <div>
              <p>
                Compatible: {String(comparison.compatible)}. Winner: {String(comparison.winner)}. Profitability claim:{" "}
                {String(comparison.profitability_claim)}.
              </p>
              {comparison.reasons?.length ? <p>{comparison.reasons.join(" ")}</p> : null}
              <p>{comparison.aggregation_note}</p>
              <table>
                <thead>
                  <tr>
                    <th>Result</th>
                    <th>Observations</th>
                    <th>Prevalence</th>
                    <th>Log loss</th>
                    <th>Brier</th>
                    <th>Accuracy</th>
                    <th>Balanced accuracy</th>
                  </tr>
                </thead>
                <tbody>
                  {comparison.results.map((result) => {
                    const report = result.holdout_test || result.walkforward_pooled;
                    return (
                      <tr key={`${result.kind}-${result.experiment_id}-${result.experiment_key}`}>
                        <td>
                          {result.evaluation_version} {result.experiment_key} {result.origin}
                        </td>
                        <td>{report?.observations ?? "NOT_EVALUATED"}</td>
                        <td>{report?.positive_prevalence ?? "NOT_EVALUATED"}</td>
                        <td>{metricText(report?.log_loss)}</td>
                        <td>{metricText(report?.brier)}</td>
                        <td>{metricText(report?.accuracy)}</td>
                        <td>{metricText(report?.balanced_accuracy)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {comparison.results.some((result) => result.walkforward_folds) ? (
                <div>
                  <h3>Walk-forward folds</h3>
                  <p>Macro averages and pooled metrics are separate. Fold rows are not averaged into the macro column.</p>
                  {comparison.results.map((result) =>
                    (result.walkforward_folds || []).map((fold) => (
                      <p key={`${result.experiment_id}-${fold.fold_id}`}>
                        {fold.fold_id}: {fold.ok ? "scored" : fold.code || "incomplete"}. Test log loss{" "}
                        {metricText(fold.test?.log_loss)}. Macro mean{" "}
                        {result.walkforward_macro?.log_loss?.mean ?? "NOT_EVALUATED"}. Pooled{" "}
                        {metricText(result.walkforward_pooled?.log_loss)}.
                      </p>
                    )),
                  )}
                </div>
              ) : null}
            </div>
          ) : null}
        </section>
      ) : null}
      {detail ? (
        <section>
          <h2>Model details</h2>
          <p>
            {detail.experiment_key} {detail.model_version || "NOT_AVAILABLE"} is {detail.status}. Scope {detail.instrument}{" "}
            {detail.horizon}. Dataset {detail.training_dataset_id || "NOT_AVAILABLE"}. Artifact{" "}
            {detail.artifact_id || "NOT_AVAILABLE"}. Output schema {detail.output_schema_version}. Health {detail.health}.
            Evaluation {detail.evaluation_status || detail.evaluation_report_id || "NOT_EVALUATED"}.
          </p>
          <p>{detail.limitations || "NOT_AVAILABLE"}</p>
          <h3>Lifecycle history</h3>
          <ul>
            {(detail.history || []).map((event, index) => (
              <li key={`${event.to}-${index}`}>
                {event.from || "start"} to {event.to}: {event.reason}
              </li>
            ))}
          </ul>
          <h3>Research selection</h3>
          <p>This changes the research pointer only. It does not train, approve, deploy, or trade.</p>
          <label>
            Reason
            <input value={reason} onChange={(event) => setReason(event.target.value)} />
          </label>
          <label>
            <input
              type="checkbox"
              checked={confirmSelection}
              onChange={(event) => setConfirmSelection(event.target.checked)}
            />
            I confirm this research selection
          </label>
          <button type="button" onClick={selectResearch} disabled={!confirmSelection || !reason.trim()}>
            Select for research
          </button>
        </section>
      ) : null}
      {message ? <p>{message}</p> : null}
      {error ? <p className="error">{error}</p> : null}
    </main>
  );
}
