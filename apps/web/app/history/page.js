"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import InstrumentHistoricalChart from "../components/InstrumentHistoricalChart";
import InstrumentDataHealthCard from "../components/InstrumentDataHealthCard";

function csrf() {
  const match = document.cookie.match(/(?:^|; )imm_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

export default function HistoryPage() {
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [report, setReport] = useState(null);
  const [datasets, setDatasets] = useState(null);
  const [provider, setProvider] = useState("groww");
  const [instrument, setInstrument] = useState("NIFTY");
  const [interval, setInterval] = useState("M15");
  const [start, setStart] = useState("2026-10-13");
  const [end, setEnd] = useState("2026-10-13");
  const [result, setResult] = useState(null);
  const [quarantine, setQuarantine] = useState(null);
  const [busy, setBusy] = useState(false);
  const [reconProviderA, setReconProviderA] = useState("groww");
  const [reconProviderB, setReconProviderB] = useState("upstox");
  const [reconTolerance, setReconTolerance] = useState(2.0);
  const [reconResult, setReconResult] = useState(null);
  const [reconBusy, setReconBusy] = useState(false);

  async function load() {
    const [capabilityResponse, datasetResponse, quarantineResponse] = await Promise.all([
      fetch("/api/history/capabilities"),
      fetch("/api/history/datasets"),
      fetch("/api/history/quarantine"),
    ]);
    if (capabilityResponse.status === 401) {
      setReady(false);
      return;
    }
    setReport(await capabilityResponse.json());
    setDatasets(await datasetResponse.json());
    setQuarantine(await quarantineResponse.json());
    setReady(true);
  }

  useEffect(() => {
    load().catch((err) => setError(String(err)));
  }, []);

  async function submitImport(event) {
    event.preventDefault();
    setError("");
    setResult(null);
    setBusy(true);
    try {
      const response = await fetch("/api/history/imports", {
        method: "POST",
        headers: { "content-type": "application/json", "x-csrf-token": csrf() },
        body: JSON.stringify({
          provider,
          instrument,
          interval,
          start: `${start}T09:15:00+05:30`,
          end: `${end}T15:30:00+05:30`,
        }),
      });
      const body = await response.json();
      setResult(body);
      if (!response.ok && body.code !== "CANDLE_BOUNDARY_UNVERIFIED" && body.code !== "EMPTY_CANDLES") {
        setError(body.message || body.code || "Retrieval failed");
      }
      await load();
    } finally {
      setBusy(false);
    }
  }

  async function submitReconciliation(event) {
    event.preventDefault();
    setReconBusy(true);
    setReconResult(null);
    try {
      const response = await fetch("/api/history/reconcile", {
        method: "POST",
        headers: { "content-type": "application/json", "x-csrf-token": csrf() },
        body: JSON.stringify({
          provider_a: reconProviderA,
          provider_b: reconProviderB,
          instrument,
          interval,
          tolerance: Number(reconTolerance),
        }),
      });
      const body = await response.json();
      setReconResult(body);
    } catch (err) {
      setError(String(err));
    } finally {
      setReconBusy(false);
    }
  }

  return (
    <main>
      <header className="page-head">
        <p className="eyebrow">History</p>
        <h1>Historical data &amp; Market Health</h1>
        <p>Independent multi-instrument data validation, historical interactive charts, session audits, and quarantine inspection.</p>
      </header>

      {/* V6 Interactive Chart & Data Health (uses global sticky header InstrumentSelector) */}
      <InstrumentHistoricalChart />
      <InstrumentDataHealthCard />
      {ready ? null : (
        <section>
          <h2>Sign in required</h2>
          <Link className="primary" href="/">Sign in</Link>
        </section>
      )}
      {ready ? (
        <details className="groww-contract-card" style={{ background: "rgba(16, 185, 129, 0.08)", border: "1px solid rgba(16, 185, 129, 0.3)", borderRadius: "8px", padding: "14px 16px", marginBottom: "20px" }}>
          <summary style={{ cursor: "pointer", fontWeight: 700, color: "#10b981", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>📨 Groww Trading API Official Clarifications &amp; Provider Capability</span>
            <span className="pill ok" style={{ fontSize: "0.72rem" }}><i />GROWW SUPPORT CONFIRMED</span>
          </summary>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "12px", marginTop: "14px" }}>
            <div style={{ background: "rgba(0,0,0,0.2)", padding: "10px", borderRadius: "6px" }}>
              <strong>Timezone</strong>
              <p style={{ margin: "4px 0 0", fontSize: "0.85rem" }}>Request &amp; response timestamps in <strong>Indian Standard Time (IST)</strong>.</p>
            </div>
            <div style={{ background: "rgba(0,0,0,0.2)", padding: "10px", borderRadius: "6px" }}>
              <strong>Candle Timestamps</strong>
              <p style={{ margin: "4px 0 0", fontSize: "0.85rem" }}>Each timestamp represents the <strong>beginning of the candle</strong> (e.g. 09:15 = 09:15-09:30).</p>
            </div>
            <div style={{ background: "rgba(0,0,0,0.2)", padding: "10px", borderRadius: "6px" }}>
              <strong>Boundaries</strong>
              <p style={{ margin: "4px 0 0", fontSize: "0.85rem" }}>start_time and end_time behavior is identical to <strong>Groww live charts</strong>.</p>
            </div>
            <div style={{ background: "rgba(0,0,0,0.2)", padding: "10px", borderRadius: "6px" }}>
              <strong>Incomplete Candles</strong>
              <p style={{ margin: "4px 0 0", fontSize: "0.85rem" }}>API may return unfinished candles; flagged by quarantine validator.</p>
            </div>
          </div>
          {report && (
            <div style={{ marginTop: "14px", paddingTop: "12px", borderTop: "1px solid rgba(255,255,255,0.08)", fontSize: "0.85rem" }}>
              <p><strong>Provider Status:</strong> {report.blocking_code} — {report.blocking_reason}</p>
              <p>Market data verified: {String(report.real_market_data_verified)} · Forecast ready: {String(report.forecast_ready)} · Trusted history: {report.verified_history?.status || "BLOCKED"}</p>
            </div>
          )}
        </details>
      ) : null}
      {ready ? (
        <form onSubmit={submitImport}>
          <h2>Request a range</h2>
          <label>
            Market data provider
            <select value={provider} onChange={(event) => setProvider(event.target.value)}>
              <option value="groww">Groww (Saved token)</option>
              <option value="kite">Zerodha Kite Connect</option>
              <option value="upstox">Upstox API v2</option>
              <option value="angelone">Angel One SmartAPI</option>
            </select>
          </label>
          <label>
            Instrument
            <select value={instrument} onChange={(event) => setInstrument(event.target.value)}>
              <option value="NIFTY">NIFTY</option>
              <option value="SENSEX">SENSEX</option>
              <option value="CRUDEOILMINI">CRUDE OIL MINI</option>
            </select>
          </label>
          <label>
            Start date
            <input type="date" value={start} onChange={(event) => setStart(event.target.value)} />
          </label>
          <label>
            End date
            <input type="date" value={end} onChange={(event) => setEnd(event.target.value)} />
          </label>
          <label>
            Interval
            <select value={interval} onChange={(event) => setInterval(event.target.value)}>
              <option value="M15">15 minutes</option>
            </select>
          </label>
          <p className="note">The request uses credentials saved for the selected provider. Raw payloads are quarantined with SHA-256 integrity hashes.</p>
          <button className="primary" type="submit" disabled={busy}>{busy ? "Retrieving…" : "Retrieve historical candles"}</button>
        </form>
      ) : null}
      {result ? (
        <section>
          <h2>Retrieval result</h2>
          <p>{result.message}</p>
          <div className="fact-grid">
            <div className="fact"><span>Request sent</span><b>{result.states?.request_sent ? "Yes" : "No"}</b></div>
            <div className="fact"><span>Raw response</span><b>{result.states?.raw_response_retrieved ? "Quarantined" : "None"}</b></div>
            <div className="fact"><span>Numeric quality</span><b>{result.states?.quality_passed ? "Passed" : "Not passed"}</b></div>
            <div className="fact"><span>Timestamp semantics</span><b>{result.states?.timestamp_semantics_verified ? "Verified" : "Unverified"}</b></div>
            <div className="fact"><span>Forecast eligible</span><b>{result.states?.forecast_eligible ? "Yes" : "No"}</b></div>
            <div className="fact"><span>Trusted candles</span><b>{Array.isArray(result.candles) ? result.candles.length : 0}</b></div>
          </div>
          {result.retrieval ? (
            <p>
              HTTP {String(result.retrieval.http_status)}. Provider status {String(result.retrieval.provider_status)}. Returned candles {String(result.retrieval.candle_count)}. First raw timestamp {result.retrieval.first_raw_timestamp || "none"}. Last raw timestamp {result.retrieval.last_raw_timestamp || "none"}. Response range {String(result.retrieval.response_start_time)} to {String(result.retrieval.response_end_time)}.
            </p>
          ) : null}
          {result.quarantine?.length ? (
            <p>
              Quarantine {result.quarantine[0].quarantine_id}. Checksum {result.quarantine[0].checksum}. Label {result.quarantine[0].label}.
            </p>
          ) : null}
          <p>Code: {result.code}. Market data verified: {String(result.real_market_data_verified)}.</p>
        </section>
      ) : null}
      {quarantine ? (
        <details style={{ background: "rgba(255,255,255,0.02)", border: "1px solid var(--line, #1e293b)", borderRadius: "8px", padding: "14px 16px", marginBottom: "16px" }}>
          <summary style={{ cursor: "pointer", fontWeight: 700 }}>
            🔍 Quarantine Diagnostic Archive ({quarantine.records?.length || 0} raw payload records)
          </summary>
          <p className="note" style={{ marginTop: "10px" }}>
            This report reads the stored raw response. It does not send another Groww request and it does not create trusted candles.
          </p>
          {quarantine.records?.length ? quarantine.records.map((row) => (
            <article key={row.quarantine_id} style={{ padding: "10px 0", borderTop: "1px solid rgba(255,255,255,0.06)" }}>
              <p><strong>{row.groww_symbol} {row.interval}</strong> · Candles: {row.candle_count} · Label: {row.label}</p>
              <p style={{ fontSize: "0.85rem", color: "var(--muted)" }}>Range: {row.requested_start_sent} to {row.requested_end_sent} · Checksum: <code>{row.checksum?.slice(0, 16)}…</code></p>
              <p style={{ fontSize: "0.85rem" }}>Rejection: {row.rejection_code} — {row.rejection_reason}</p>
            </article>
          )) : <p>No quarantined response is stored.</p>}
        </details>
      ) : null}
      {datasets ? (
        <section>
          <h2>Stored datasets</h2>
          <p>Ingestion operational: {String(datasets.ingestion_operational)}</p>
          {datasets.datasets?.length ? (
            <ul>
              {datasets.datasets.map((row) => (
                <li key={row.dataset_id}>
                  {row.instrument} {row.data_category} {row.validation_status} eligible {String(row.forecast_eligible)}
                </li>
              ))}
            </ul>
          ) : (
            <p>No historical dataset is stored. Evaluation is unavailable until an eligible dataset exists.</p>
          )}
        </section>
      ) : null}
      {ready ? (
        <section className="reconciliation-panel" style={{ marginTop: "24px" }}>
          <h2>Cross-Provider Historical Reconciliation</h2>
          <p className="note">
            Compare candle series between independent providers with configurable tolerances to detect duplicate, missing, or divergent bars.
          </p>
          <form onSubmit={submitReconciliation} style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "12px", alignItems: "end" }}>
            <label>
              Provider A (Reference)
              <select value={reconProviderA} onChange={(e) => setReconProviderA(e.target.value)}>
                <option value="groww">Groww (Quarantine)</option>
                <option value="upstox">Upstox API</option>
                <option value="kite">Zerodha Kite Connect</option>
                <option value="angelone">Angel One SmartAPI</option>
              </select>
            </label>
            <label>
              Provider B (Comparison)
              <select value={reconProviderB} onChange={(e) => setReconProviderB(e.target.value)}>
                <option value="upstox">Upstox API</option>
                <option value="kite">Zerodha Kite Connect</option>
                <option value="angelone">Angel One SmartAPI</option>
                <option value="groww">Groww (Quarantine)</option>
              </select>
            </label>
            <label>
              Max Delta Tolerance (points)
              <input type="number" step="0.1" value={reconTolerance} onChange={(e) => setReconTolerance(e.target.value)} />
            </label>
            <button className="primary" type="submit" disabled={reconBusy}>{reconBusy ? "Reconciling…" : "Run Pairwise Reconciliation"}</button>
          </form>

          {reconResult ? (
            <div style={{ marginTop: "16px", background: "rgba(0,0,0,0.2)", padding: "16px", borderRadius: "8px" }}>
              <h3>Reconciliation Result: <span className={`pill ${reconResult.ok ? "ok" : "wait"}`}>{reconResult.status}</span></h3>
              <p>{reconResult.message || `Compared ${reconResult.provider_a} vs ${reconResult.provider_b}`}</p>
              <div className="fact-grid" style={{ marginTop: "12px" }}>
                <div className="fact"><span>Common Candles</span><b>{reconResult.common_candles_count ?? "—"}</b></div>
                <div className="fact"><span>Matched Candles</span><b>{reconResult.matched_candles_count ?? "—"}</b></div>
                <div className="fact"><span>Mismatches</span><b>{reconResult.mismatches_count ?? 0}</b></div>
                <div className="fact"><span>Max OHLC Delta</span><b>{reconResult.max_delta ?? "—"} pts</b></div>
                <div className="fact"><span>Missing in B</span><b>{reconResult.missing_in_b_count ?? 0}</b></div>
                <div className="fact"><span>Extra in B</span><b>{reconResult.extra_in_b_count ?? 0}</b></div>
              </div>
            </div>
          ) : null}
        </section>
      ) : null}
      {error ? <p className="error">{error}</p> : null}
    </main>
  );
}
