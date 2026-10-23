"use client";

import { useCallback, useEffect, useState } from "react";
import { csrf } from "./ResearchBoard";

const SYMBOLS = ["NIFTY", "BANKNIFTY", "INDIAVIX", "SENSEX"];
const INTERVALS = [
  { id: "1day", label: "Daily (1day)" },
  { id: "15minute", label: "15-minute (for half-day)" },
];

const num = (v, digits = 3) => (v == null ? "N/A" : Number(v).toFixed(digits));
const pctOf = (v) => (v == null ? "N/A" : `${(v * 100).toFixed(1)}%`);
const signedPct = (v) => (v == null ? "N/A" : `${v >= 0 ? "+" : ""}${Number(v).toFixed(2)}%`);

export default function MultiYearResearchCard() {
  const [state, setState] = useState(null);
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");
  const [symbols, setSymbols] = useState(["NIFTY", "INDIAVIX", "BANKNIFTY", "SENSEX"]);
  const [intervals, setIntervals] = useState(["1day"]);
  const [start, setStart] = useState("2020-01-01");
  const [end, setEnd] = useState("");
  const [options, setOptions] = useState(false);
  const [withPcr, setWithPcr] = useState(false);
  const [initialTrain, setInitialTrain] = useState(500);
  const [step, setStep] = useState(20);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/research/multiyear");
      const body = await res.json();
      if (!res.ok) throw new Error(body.message || `HTTP ${res.status}`);
      setState(body);
      if (body.report) {
        const r = await fetch("/api/research/multiyear/report");
        if (r.ok) setReport(await r.json());
      } else {
        setReport(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const job = state?.job;
  const running = job?.status === "RUNNING";

  // Poll while a job runs; reload everything once it finishes.
  useEffect(() => {
    if (!running) return undefined;
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  }, [running, load]);

  async function post(path, payload) {
    setError("");
    try {
      const res = await fetch(path, {
        method: "POST",
        headers: { "content-type": "application/json", "x-csrf-token": csrf() },
        body: JSON.stringify(payload),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.message || body.detail?.[0]?.msg || `HTTP ${res.status}`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const toggle = (list, setList, value) =>
    setList(list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);

  const startFetch = () =>
    post("/api/research/multiyear/fetch", { symbols, intervals, start, end: end || null, options });
  const runResearch = () =>
    post("/api/research/multiyear/run", { with_pcr: withPcr, initial_train: Number(initialTrain), step: Number(step) });

  const summary = report?.summary;
  const vol = report?.volatility;
  const nothingSaved = state && !state.series.some((s) => s.saved);

  return (
    <div className="v6-card" data-testid="multiyear-research-card">
      <div className="v6-card-header">
        <div>
          <span className="v6-badge-sub">Research only: never used for orders</span>
          <h2 className="v6-card-title">Multi-Year Daily &amp; Half-Day Research</h2>
        </div>
        <div className="v6-header-tags">
          {job ? (
            <span className={`v6-pill ${running ? "amber" : job.status === "FAILED" ? "rose" : "indigo"}`} data-testid="multiyear-job-status">
              {job.kind.toUpperCase()}: {job.status}
            </span>
          ) : null}
          {report ? (
            <span className={`v6-pill ${summary?.direction_edge_supported ? "emerald" : "rose"}`}>
              DIRECTION EDGE: {summary?.direction_edge_supported ? "SUPPORTED" : "NOT SUPPORTED"}
            </span>
          ) : null}
        </div>
      </div>

      <p className="v6-section-desc">
        Downloads Groww history from 2020, then tests whether next-day or next-half-day direction, and next-day
        volatility, can be forecast. Models are chosen on the earlier years only and checked once on the final 20%,
        with trading costs and a correction for the number of models tried. Missing data is dropped, never filled.
        Not available from Groww and not used: {(state?.unavailable || []).join(", ")}.
      </p>

      {error ? <div className="v6-error-box">{error}</div> : null}

      {/* Step 1: fetch */}
      <h3>1. Fetch history from Groww</h3>
      <div style={{ display: "flex", gap: "16px", flexWrap: "wrap", alignItems: "center", marginBottom: "10px" }}>
        <span>Symbols:</span>
        {SYMBOLS.map((s) => (
          <label key={s} style={{ display: "flex", gap: "4px", alignItems: "center" }}>
            <input type="checkbox" checked={symbols.includes(s)} onChange={() => toggle(symbols, setSymbols, s)} />
            {s}
          </label>
        ))}
      </div>
      <div style={{ display: "flex", gap: "16px", flexWrap: "wrap", alignItems: "center", marginBottom: "10px" }}>
        <span>Intervals:</span>
        {INTERVALS.map((i) => (
          <label key={i.id} style={{ display: "flex", gap: "4px", alignItems: "center" }}>
            <input type="checkbox" checked={intervals.includes(i.id)} onChange={() => toggle(intervals, setIntervals, i.id)} />
            {i.label}
          </label>
        ))}
        <label>
          From <input type="date" value={start} min="2020-01-01" onChange={(e) => setStart(e.target.value)} />
        </label>
        <label>
          To <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} placeholder="today" />
        </label>
        <label style={{ display: "flex", gap: "4px", alignItems: "center" }}>
          <input type="checkbox" checked={options} onChange={(e) => setOptions(e.target.checked)} />
          Also build NIFTY put/call OI ratio (slow: thousands of requests)
        </label>
      </div>
      <button
        className="primary"
        type="button"
        onClick={startFetch}
        disabled={running || symbols.length === 0 || intervals.length === 0}
        data-testid="multiyear-fetch-button"
      >
        {running && job?.kind === "fetch" ? "Fetching…" : "Fetch history"}
      </button>

      {state ? (
        <table className="v6-data-table" style={{ marginTop: "14px" }} data-testid="multiyear-series-table">
          <thead>
            <tr>
              <th>Series</th>
              <th>Interval</th>
              <th>Candles</th>
              <th>From</th>
              <th>To</th>
              <th>Failed windows</th>
              <th>Rejected rows</th>
            </tr>
          </thead>
          <tbody>
            {state.series.map((s) => (
              <tr key={`${s.name}-${s.interval}`}>
                <td>{s.name}</td>
                <td>{s.interval}</td>
                <td>{s.saved ? s.candle_count : "not fetched"}</td>
                <td>{s.first ? s.first.slice(0, 10) : "—"}</td>
                <td>{s.last ? s.last.slice(0, 10) : "—"}</td>
                <td className={s.failed_windows ? "rose-text" : ""}>{s.saved ? s.failed_windows : "—"}</td>
                <td>{s.saved ? s.rejected_rows : "—"}</td>
              </tr>
            ))}
            <tr>
              <td>NIFTY PCR</td>
              <td>daily</td>
              <td>{state.pcr ? `${state.pcr.days} days` : "not built"}</td>
              <td>{state.pcr?.first || "—"}</td>
              <td>{state.pcr?.last || "—"}</td>
              <td className={state.pcr?.skipped ? "rose-text" : ""}>{state.pcr ? `${state.pcr.skipped} skipped` : "—"}</td>
              <td>—</td>
            </tr>
          </tbody>
        </table>
      ) : null}

      {/* Step 2: research */}
      <h3 style={{ marginTop: "20px" }}>2. Run the research</h3>
      <div style={{ display: "flex", gap: "16px", flexWrap: "wrap", alignItems: "center", marginBottom: "10px" }}>
        <label>
          First training window (days){" "}
          <input type="number" min="100" max="5000" value={initialTrain} onChange={(e) => setInitialTrain(e.target.value)} style={{ width: "90px" }} />
        </label>
        <label>
          Test window (days){" "}
          <input type="number" min="5" max="250" value={step} onChange={(e) => setStep(e.target.value)} style={{ width: "80px" }} />
        </label>
        <label style={{ display: "flex", gap: "4px", alignItems: "center" }}>
          <input type="checkbox" checked={withPcr} onChange={(e) => setWithPcr(e.target.checked)} disabled={!state?.pcr} />
          Include put/call ratio features
        </label>
      </div>
      <button className="primary" type="button" onClick={runResearch} disabled={running || nothingSaved} data-testid="multiyear-run-button">
        {running && job?.kind === "research" ? "Running research…" : "Run research"}
      </button>
      {nothingSaved ? <p className="note">Fetch at least NIFTY daily history first.</p> : null}

      {job ? (
        <div style={{ marginTop: "14px" }}>
          <strong>Last job</strong> ({job.kind}, started {job.started_at?.slice(0, 19).replace("T", " ")} UTC): {job.status}
          {job.error ? <div className="v6-error-box">{job.error}</div> : null}
          {job.log?.length ? (
            <pre style={{ maxHeight: "160px", overflow: "auto", fontSize: "0.78rem", marginTop: "6px" }} data-testid="multiyear-job-log">
              {job.log.join("\n")}
            </pre>
          ) : null}
        </div>
      ) : null}

      {/* Step 3: results */}
      {report ? (
        <div style={{ marginTop: "20px" }} data-testid="multiyear-report">
          <h3>3. Results</h3>
          <p className="note">
            Generated {report.generated_at ? report.generated_at.slice(0, 19).replace("T", " ") : "—"}. NIFTY{" "}
            {report.inputs?.nifty_daily_bars} daily bars, {report.inputs?.nifty_half_day_bars} half-day bars, VIX{" "}
            {report.inputs?.vix_bars}, BANKNIFTY {report.inputs?.banknifty_bars}, SENSEX {report.inputs?.sensex_bars}, PCR{" "}
            {report.inputs?.pcr_days} days. Cost per side {pctOf(report.cost_per_side)}.
          </p>

          <div className="v6-metrics-grid">
            <div className="v6-metric-card">
              <span className="v6-metric-label">Direction: best on development</span>
              <div className="v6-metric-val">
                {summary?.direction_best_on_development
                  ? `${summary.direction_best_on_development.model} / ${summary.direction_best_on_development.feature_set}`
                  : "N/A"}
              </div>
              <span className="v6-metric-sub">
                {summary?.direction_best_on_development?.horizon || ""} · {summary?.direction_trials} trials
              </span>
            </div>
            <div className="v6-metric-card">
              <span className="v6-metric-label">Its holdout return / accuracy</span>
              <div className="v6-metric-val">
                {signedPct(summary?.direction_best_on_development?.holdout_return_pct)}
              </div>
              <span className="v6-metric-sub">
                accuracy {pctOf(summary?.direction_best_on_development?.holdout_accuracy?.accuracy)} · p ={" "}
                {num(summary?.direction_best_on_development?.holdout_accuracy?.p_value_vs_50pct)}
              </span>
            </div>
            <div className="v6-metric-card">
              <span className="v6-metric-label">Volatility: selected model</span>
              <div className="v6-metric-val">{summary?.volatility?.selected_model || "N/A"}</div>
              <span className="v6-metric-sub">holdout QLIKE {num(summary?.volatility?.holdout_qlike)}</span>
            </div>
            <div className="v6-metric-card">
              <span className="v6-metric-label">Beats naive volatility (holdout)</span>
              <div className={`v6-metric-val ${summary?.volatility?.beats_naive_holdout ? "emerald-text" : "rose-text"}`}>
                {summary?.volatility ? (summary.volatility.beats_naive_holdout ? "YES" : "NO") : "N/A"}
              </div>
              <span className="v6-metric-sub">DM p = {num(summary?.volatility?.dm_vs_naive_holdout?.p_value)}</span>
            </div>
          </div>

          <h4>Direction trials</h4>
          <table className="v6-data-table" data-testid="multiyear-direction-table">
            <thead>
              <tr>
                <th>Horizon</th>
                <th>Features</th>
                <th>Model</th>
                <th>Dev deflated Sharpe</th>
                <th>Holdout return</th>
                <th>Holdout Sharpe</th>
                <th>Holdout accuracy (n, p)</th>
                <th>Trades</th>
              </tr>
            </thead>
            <tbody>
              {(report.direction || []).map((r, i) =>
                r.status !== "EVALUATED" ? (
                  <tr key={i}>
                    <td>{r.horizon}</td>
                    <td>{r.feature_set}</td>
                    <td colSpan={6}>{r.status} ({r.rows} rows)</td>
                  </tr>
                ) : (
                  <tr key={i}>
                    <td>{r.horizon}</td>
                    <td>{r.feature_set}</td>
                    <td>{r.model}</td>
                    <td>{num(r.development?.deflated_sharpe)}</td>
                    <td className={r.holdout?.total_return_pct >= 0 ? "emerald-text" : "rose-text"}>
                      {signedPct(r.holdout?.total_return_pct)}
                    </td>
                    <td>{num(r.holdout?.sharpe_annualized, 2)}</td>
                    <td>
                      {pctOf(r.holdout?.directional_accuracy?.accuracy)} ({r.holdout?.directional_accuracy?.n},{" "}
                      {num(r.holdout?.directional_accuracy?.p_value_vs_50pct)})
                    </td>
                    <td>{r.holdout?.trades}</td>
                  </tr>
                ),
              )}
            </tbody>
          </table>

          <h4 style={{ marginTop: "14px" }}>Volatility models (next-day)</h4>
          {vol?.status === "EVALUATED" ? (
            <table className="v6-data-table" data-testid="multiyear-volatility-table">
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Holdout QLIKE</th>
                  <th>Holdout MSE (log var)</th>
                  <th>Mincer–Zarnowitz R²</th>
                  <th>DM vs naive (stat, p)</th>
                  <th>DM vs VIX (stat, p)</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(vol.models).map(([name, m]) => (
                  <tr key={name}>
                    <td>
                      {name}
                      {vol.selected_on_development === name ? " ★" : ""}
                    </td>
                    <td>{num(m.holdout?.qlike)}</td>
                    <td>{num(m.holdout?.mse_log_var)}</td>
                    <td>{num(m.holdout?.mincer_zarnowitz_r2)}</td>
                    <td>
                      {m.holdout?.dm_vs_naive_rv1
                        ? `${num(m.holdout.dm_vs_naive_rv1.stat, 2)}, ${num(m.holdout.dm_vs_naive_rv1.p_value)}`
                        : "—"}
                    </td>
                    <td>
                      {m.holdout?.dm_vs_vix_implied
                        ? `${num(m.holdout.dm_vs_vix_implied.stat, 2)}, ${num(m.holdout.dm_vs_vix_implied.p_value)}`
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="note">Volatility: {vol?.status || "not evaluated"}{vol?.rows != null ? ` (${vol.rows} rows)` : ""}</p>
          )}
        </div>
      ) : null}
    </div>
  );
}
