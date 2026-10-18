"use client";

import { useEffect, useState } from "react";
import ResearchBoard, { csrf } from "../components/ResearchBoard";
import ReadState from "../components/ReadState";
import { useRead } from "../components/useRead";
import InstrumentForecastCard from "../components/InstrumentForecastCard";
import { flagLabel } from "../research/status.mjs";
import { observationClass, valueText } from "../research/present.mjs";

function pct(val) {
  if (val == null) return "—";
  return `${Number(val).toFixed(2)}%`;
}

function num(val, digits = 4) {
  if (val == null) return "—";
  return Number(val).toFixed(digits);
}

function inr(val) {
  if (val == null) return "—";
  return `₹${Number(val).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export default function ForecastPage() {
  return (
    <ResearchBoard
      title="Forecasts & Accuracy Desk"
      lede="V6 multi-instrument forecasting desk. Predictions are calculated independently per instrument. Directional forecasts are separated from validated trading strategies; raw model confidence is distinguished from calibrated probabilities."
    >
      {() => (
        <>
          <InstrumentForecastCard />
          <ForecastAccuracyHub />
          <Approved />
          <Models />
          <Experiments />
        </>
      )}
    </ResearchBoard>
  );
}

function ForecastAccuracyHub() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [evaluating, setEvaluating] = useState(false);

  const fetchAccuracy = async () => {
    try {
      setLoading(true);
      const res = await fetch("/api/analysis/forecast-accuracy");
      if (!res.ok) throw new Error(`Failed to load forecast accuracy (${res.status})`);
      const json = await res.json();
      setData(json);
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAccuracy();
  }, []);

  const handleEvaluate = async () => {
    try {
      setEvaluating(true);
      const res = await fetch("/api/analysis/forecast-accuracy/evaluate", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-csrf-token": csrf(),
        },
      });
      if (!res.ok) throw new Error(`Evaluation failed (${res.status})`);
      const updated = await res.json();
      setData(updated);
    } catch (err) {
      alert(`Evaluation error: ${err.message || String(err)}`);
    } finally {
      setEvaluating(false);
    }
  };

  const forecasts = data?.forecasts || [];
  const scoredCount = data?.scored_forecasts || 0;
  const pendingCount = data?.pending_forecasts || 0;

  return (
    <section aria-labelledby="accuracy-heading" style={{ marginBottom: "30px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px", marginBottom: "12px" }}>
        <div>
          <h2 id="accuracy-heading" style={{ margin: 0, fontSize: "1.2rem" }}>
            Forecast Accuracy &amp; Out-of-Sample Calibration
          </h2>
          <p style={{ margin: "4px 0 0", fontSize: "0.85rem", color: "var(--muted)" }}>
            Post-horizon scoring of statistical predictions against realized underlying market closes.
          </p>
        </div>
        <button
          type="button"
          onClick={handleEvaluate}
          disabled={evaluating}
          style={{
            padding: "8px 16px",
            borderRadius: "8px",
            fontSize: "0.85rem",
            fontWeight: 600,
            cursor: "pointer",
            background: "rgba(56, 189, 248, 0.15)",
            color: "#38bdf8",
            border: "1px solid rgba(56, 189, 248, 0.4)",
          }}
        >
          {evaluating ? "Scoring pending…" : "⚡ Evaluate Pending Outcomes"}
        </button>
      </div>

      {loading && !data ? (
        <p role="status">Loading forecast accuracy records…</p>
      ) : error ? (
        <div className="error" role="alert">
          <p>{error}</p>
        </div>
      ) : data ? (
        <>
          {/* Calibration Status Banner */}
          <div style={{
            background: data.calibration_status === "CALIBRATED_RESEARCH" ? "rgba(16, 185, 129, 0.1)" : "rgba(245, 158, 11, 0.1)",
            border: `1px solid ${data.calibration_status === "CALIBRATED_RESEARCH" ? "#10b981" : "#f59e0b"}`,
            padding: "12px 16px",
            borderRadius: "8px",
            marginBottom: "16px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: "8px",
          }}>
            <div>
              <strong>Calibration Status: </strong>
              <span style={{
                color: data.calibration_status === "CALIBRATED_RESEARCH" ? "#10b981" : "#f59e0b",
                fontWeight: "bold",
                marginRight: "8px"
              }}>
                {data.calibration_status}
              </span>
              <span style={{ fontSize: "0.85rem", color: "var(--muted)" }}>{data.calibration_reason}</span>
            </div>
            <div style={{ fontSize: "0.82rem", color: "var(--muted)" }}>
              Sample: <strong>{scoredCount}</strong> scored · <strong>{pendingCount}</strong> pending
            </div>
          </div>

          {/* Metric Cards Grid */}
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
            gap: "12px",
            marginBottom: "20px"
          }}>
            <div style={{ background: "var(--card-subtle, #131c31)", padding: "14px", borderRadius: "10px", border: "1px solid var(--line)" }}>
              <span style={{ fontSize: "0.8rem", color: "var(--muted)", textTransform: "uppercase" }}>Directional Win Rate</span>
              <div style={{ fontSize: "1.3rem", fontWeight: "bold", marginTop: "4px", color: (data.directional_accuracy_pct || 0) >= 50 ? "#10b981" : "#ef4444" }}>
                {pct(data.directional_accuracy_pct)}
              </div>
              <small style={{ color: "var(--muted)" }}>Over {scoredCount} realized horizons</small>
            </div>

            <div style={{ background: "var(--card-subtle, #131c31)", padding: "14px", borderRadius: "10px", border: "1px solid var(--line)" }}>
              <span style={{ fontSize: "0.8rem", color: "var(--muted)", textTransform: "uppercase" }}>Mean Brier Score</span>
              <div style={{ fontSize: "1.3rem", fontWeight: "bold", marginTop: "4px", color: "#38bdf8" }}>
                {num(data.brier_score)}
              </div>
              <small style={{ color: "var(--muted)" }}>Prior baseline: {num(data.prior_brier_score)}</small>
            </div>

            <div style={{ background: "var(--card-subtle, #131c31)", padding: "14px", borderRadius: "10px", border: "1px solid var(--line)" }}>
              <span style={{ fontSize: "0.8rem", color: "var(--muted)", textTransform: "uppercase" }}>Brier Skill Score (BSS)</span>
              <div style={{
                fontSize: "1.3rem",
                fontWeight: "bold",
                marginTop: "4px",
                color: (data.brier_skill_score_pct || 0) > 0 ? "#10b981" : "#f59e0b"
              }}>
                {(data.brier_skill_score_pct || 0) > 0 ? "+" : ""}{pct(data.brier_skill_score_pct)}
              </div>
              <small style={{ color: "var(--muted)" }}>Relative to empirical prior</small>
            </div>

            <div style={{ background: "var(--card-subtle, #131c31)", padding: "14px", borderRadius: "10px", border: "1px solid var(--line)" }}>
              <span style={{ fontSize: "0.8rem", color: "var(--muted)", textTransform: "uppercase" }}>Log Loss (Cross-Entropy)</span>
              <div style={{ fontSize: "1.3rem", fontWeight: "bold", marginTop: "4px" }}>
                {num(data.log_loss)}
              </div>
              <small style={{ color: "var(--muted)" }}>Binary directional target</small>
            </div>
          </div>

          {/* Breakdown By Instrument */}
          {data.by_instrument && Object.keys(data.by_instrument).length > 0 && (
            <div style={{ marginBottom: "20px" }}>
              <h4 style={{ fontSize: "0.95rem", marginBottom: "8px" }}>Accuracy by Instrument</h4>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "10px" }}>
                {Object.entries(data.by_instrument).map(([inst, stat]) => (
                  <div key={inst} style={{ background: "var(--card-subtle, #131c31)", padding: "12px", borderRadius: "8px", border: "1px solid var(--line)" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
                      <strong>{inst}</strong>
                      <span style={{ fontWeight: "bold", color: stat.accuracy_pct >= 50 ? "#10b981" : "#ef4444" }}>
                        {pct(stat.accuracy_pct)}
                      </span>
                    </div>
                    <div style={{ fontSize: "0.8rem", color: "var(--muted)" }}>
                      Total: {stat.total} · Brier: {num(stat.brier_score)}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Forecast-versus-Actual History Table */}
          <div style={{ marginBottom: "30px" }}>
            <h4 style={{ fontSize: "0.95rem", marginBottom: "8px" }}>
              Forecast-versus-Actual Outcomes History ({forecasts.length} total logged)
            </h4>
            <div className="table-wrap" style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem", textAlign: "left" }}>
                <thead>
                  <tr style={{ borderBottom: "2px solid var(--line)", background: "rgba(255,255,255,0.02)" }}>
                    <th style={{ padding: "8px" }}>Analysis / Time</th>
                    <th style={{ padding: "8px" }}>Instrument</th>
                    <th style={{ padding: "8px" }}>Predicted</th>
                    <th style={{ padding: "8px" }}>Prob (Up)</th>
                    <th style={{ padding: "8px" }}>Prior Spot</th>
                    <th style={{ padding: "8px" }}>Subsequent Spot</th>
                    <th style={{ padding: "8px" }}>Realized Ret</th>
                    <th style={{ padding: "8px" }}>Outcome</th>
                    <th style={{ padding: "8px" }}>Brier</th>
                    <th style={{ padding: "8px" }}>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {forecasts.slice().reverse().slice(0, 30).map((f) => {
                    const out = f.subsequent_outcome;
                    const isCorrect = out?.direction_correct;
                    const isPending = f.evaluation_status === "PENDING_SUBSEQUENT_CLOSE";

                    return (
                      <tr key={f.record_id || f.analysis_id} style={{ borderBottom: "1px solid var(--line, #1e293b)" }}>
                        <td style={{ padding: "8px", color: "var(--muted)" }}>
                          <div>{f.recorded_at ? new Date(f.recorded_at).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—"}</div>
                          <small style={{ fontSize: "0.72rem", color: "var(--muted)", fontFamily: "monospace" }}>{f.analysis_id?.slice(0, 8)}</small>
                        </td>
                        <td style={{ padding: "8px" }}><strong>{f.instrument}</strong></td>
                        <td style={{ padding: "8px" }}>
                          <span style={{ color: f.predicted_direction === "BULLISH" ? "#10b981" : "#ef4444", fontWeight: "bold" }}>
                            {f.predicted_direction}
                          </span>
                        </td>
                        <td style={{ padding: "8px" }}>{pct(f.probability_up * 100)}</td>
                        <td style={{ padding: "8px" }}>{inr(f.spot_price_at_prediction)}</td>
                        <td style={{ padding: "8px" }}>{out?.spot_price_subsequent ? inr(out.spot_price_subsequent) : "—"}</td>
                        <td style={{ padding: "8px", color: out?.realized_return_pct >= 0 ? "#10b981" : "#ef4444" }}>
                          {out?.realized_return_pct != null ? `${out.realized_return_pct >= 0 ? "+" : ""}${pct(out.realized_return_pct)}` : "—"}
                        </td>
                        <td style={{ padding: "8px" }}>
                          {isPending ? (
                            <span style={{ color: "#f59e0b", fontSize: "0.78rem" }}>⏳ Horizon pending</span>
                          ) : isCorrect ? (
                            <span style={{ color: "#10b981", fontWeight: "bold" }}>✓ Correct ({out.actual_direction})</span>
                          ) : (
                            <span style={{ color: "#ef4444", fontWeight: "bold" }}>✗ Incorrect ({out.actual_direction})</span>
                          )}
                        </td>
                        <td style={{ padding: "8px" }}>{out?.brier_score != null ? num(out.brier_score) : "—"}</td>
                        <td style={{ padding: "8px" }}>
                          <span className={`pill ${isPending ? "uncalibrated" : "good"}`} style={{ fontSize: "0.72rem" }}>
                            {isPending ? "PENDING" : "SCORED"}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {forecasts.length > 30 && (
                <p style={{ fontSize: "0.8rem", color: "var(--muted)", marginTop: "8px" }}>
                  Showing latest 30 forecasts of {forecasts.length} logged.
                </p>
              )}
            </div>
          </div>
        </>
      ) : null}
    </section>
  );
}

function Approved() {
  const read = useRead("/api/forecasts");
  const rows = read.body?.forecasts || [];
  return (
    <section aria-labelledby="approved-heading" data-testid="approved-forecasts">
      <h2 id="approved-heading">Approved forecasts</h2>
      <ReadState
        phase={read.phase}
        error={read.error}
        onRetry={read.retry}
        empty={read.phase === "ready" && rows.length === 0}
        emptyText="No approved forecast was returned."
        loadingText="Loading the forecast list…"
      >
        {read.body ? (
          <>
            <p>Forecast ready {flagLabel(read.body.forecast_ready)}. {valueText(read.body.note)}</p>
            <ul>
              {rows.map((row, index) => <li key={row.id || index}>{valueText(row.id)}</li>)}
            </ul>
          </>
        ) : null}
      </ReadState>
    </section>
  );
}

function Models() {
  const read = useRead("/api/models");
  const rows = read.body?.models || [];
  return (
    <section aria-labelledby="models-heading" data-testid="forecast-models">
      <h2 id="models-heading">Registered models</h2>
      <ReadState
        phase={read.phase}
        error={read.error}
        onRetry={read.retry}
        empty={read.phase === "ready" && rows.length === 0}
        emptyText="No model rows were returned. That is not an approval."
        loadingText="Loading registered models…"
      >
        {read.body ? (
          <>
            <p>Forecast ready {flagLabel(read.body.forecast_ready)}. Paper approved {flagLabel(read.body.paper_approved)}. Live approved {flagLabel(read.body.live_approved)}. Market data verified {flagLabel(read.body.real_market_data_verified)}.</p>
            <div className="table-wrap">
              <table>
                <caption>Model lineage and verification flags</caption>
                <thead>
                  <tr>
                    <th>Model</th>
                    <th>Status</th>
                    <th>Origin</th>
                    <th>Class</th>
                    <th>Dataset</th>
                    <th>Checksum</th>
                    <th>Evaluated</th>
                    <th>Forecast ready</th>
                    <th>Paper</th>
                    <th>Live</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => {
                    const kind = observationClass({ origin: row.origin, synthetic: row.synthetic, real_market_data_verified: row.real_market_data_verified, live_market_data: false });
                    return (
                      <tr key={row.version_id || `${row.model_id}-${row.version}`}>
                        <td>{valueText(row.model_id)} {valueText(row.version)}</td>
                        <td>{valueText(row.status)}</td>
                        <td>{valueText(row.origin)}</td>
                        <td><span className={`data-badge ${kind.code}`}>{kind.label}</span></td>
                        <td>{valueText(row.training_dataset_id)}</td>
                        <td>{valueText(row.training_dataset_checksum)}</td>
                        <td>{valueText(row.last_evaluated_at)}</td>
                        <td>{flagLabel(row.forecast_ready)}</td>
                        <td>{flagLabel(row.paper_approved)}</td>
                        <td>{flagLabel(row.live_approved)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        ) : null}
      </ReadState>
    </section>
  );
}

function Experiments() {
  const read = useRead("/api/experiments");
  const holdout = read.body?.holdout || [];
  const walk = read.body?.walk_forward || [];
  const empty = read.phase === "ready" && holdout.length === 0 && walk.length === 0;
  return (
    <section aria-labelledby="experiments-heading" data-testid="experiments">
      <h2 id="experiments-heading">Saved experiments</h2>
      <ReadState phase={read.phase} error={read.error} onRetry={read.retry} empty={empty} emptyText="No saved experiments were returned." loadingText="Loading saved experiments…">
        {read.body ? (
          <>
            <p>Forecast ready {flagLabel(read.body.forecast_ready)}. These rows are research results, not an approved forecast.</p>
            <ExperimentTable title="Holdout" rows={holdout} />
            <ExperimentTable title="Walk-forward" rows={walk} />
          </>
        ) : null}
      </ReadState>
    </section>
  );
}

function ExperimentTable({ title, rows }) {
  return (
    <>
      <h3>{title}</h3>
      {rows.length === 0 ? <p>No {title.toLowerCase()} rows were returned.</p> : (
        <div className="table-wrap">
          <table>
            <caption>{title} experiment lineage</caption>
            <thead>
              <tr>
                <th>Experiment</th>
                <th>Origin</th>
                <th>Class</th>
                <th>Dataset</th>
                <th>Instrument</th>
                <th>Horizon</th>
                <th>Selected model</th>
                <th>Incomplete</th>
                <th>Evaluation</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const kind = observationClass({ origin: row.origin, real_market_data_verified: false, live_market_data: false });
                return (
                  <tr key={row.experiment_id || `${row.kind}-${row.code}`}>
                    <td>{valueText(row.experiment_id)}{row.ok === false ? ` (${valueText(row.code)})` : ""}</td>
                    <td>{valueText(row.origin)}</td>
                    <td><span className={`data-badge ${kind.code}`}>{kind.label}</span></td>
                    <td>{valueText(row.dataset_id)}</td>
                    <td>{valueText(row.instrument)}</td>
                    <td>{valueText(row.horizon)}</td>
                    <td>{valueText(row.selected_model)}</td>
                    <td>{valueText(row.incomplete)}</td>
                    <td>{evaluationText(row.aggregate)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function evaluationText(aggregate) {
  if (aggregate === undefined) return "not returned";
  if (aggregate === null) return "not set";
  if (typeof aggregate !== "object") return valueText(aggregate);
  const entries = Object.entries(aggregate);
  if (entries.length === 0) return "no metrics returned";
  return entries.map(([key, value]) => `${key}: ${valueText(value)}`).join("; ");
}
