"use client";

import ResearchBoard from "../components/ResearchBoard";
import ReadState from "../components/ReadState";
import { useRead } from "../components/useRead";
import { flagLabel } from "../research/status.mjs";
import { observationClass, valueText } from "../research/present.mjs";

export default function ForecastPage() {
  return (
    <ResearchBoard
      title="Forecasts"
      lede="V6 quant stage. These cards are saved research. A classification metric is not an expected return, and none of these models is an approved forecast. Scenario probabilities stay unset."
    >
      {() => (
        <>
          <Approved />
          <Models />
          <Experiments />
        </>
      )}
    </ResearchBoard>
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
