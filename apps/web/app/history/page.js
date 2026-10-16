"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

function csrf() {
  const match = document.cookie.match(/(?:^|; )imm_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

export default function HistoryPage() {
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [report, setReport] = useState(null);
  const [datasets, setDatasets] = useState(null);
  const [instrument, setInstrument] = useState("NIFTY");
  const [interval, setInterval] = useState("M15");
  const [start, setStart] = useState("2026-10-13");
  const [end, setEnd] = useState("2026-10-13");
  const [result, setResult] = useState(null);
  const [quarantine, setQuarantine] = useState(null);
  const [busy, setBusy] = useState(false);

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

  return (
    <main>
      <header className="page-head">
        <p className="eyebrow">History</p>
        <h1>Historical data</h1>
        <p>Research import for NIFTY 50 and SENSEX 15-minute candles. This page does not place orders and does not approve a model.</p>
      </header>
      {ready ? null : (
        <section>
          <h2>Sign in required</h2>
          <Link className="primary" href="/">Sign in</Link>
        </section>
      )}
      {ready ? (
        <section className="groww-contract-card" style={{ background: "rgba(16, 185, 129, 0.08)", border: "1px solid rgba(16, 185, 129, 0.3)", borderRadius: "8px", padding: "16px", marginBottom: "20px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "8px" }}>
            <div>
              <h2 style={{ margin: 0, fontSize: "1.15rem", color: "#10b981" }}>📨 Groww Trading API Official Clarifications</h2>
              <p style={{ margin: "4px 0 0", fontSize: "0.88rem", color: "var(--sub, #94a3b8)" }}>
                Verified technical response from Groww Customer Success received regarding historical candle contracts.
              </p>
            </div>
            <span className="pill ok"><i />GROWW SUPPORT CONFIRMED</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "12px", marginTop: "14px" }}>
            <div style={{ background: "rgba(0,0,0,0.2)", padding: "10px", borderRadius: "6px" }}>
              <strong>Timezone</strong>
              <p style={{ margin: "4px 0 0", fontSize: "0.85rem" }}>Request & response timestamps in <strong>Indian Standard Time (IST)</strong>.</p>
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
        </section>
      ) : null}
      {report ? (
        <section>
          <h2>Provider capability</h2>
          <p className="note">
            A retrieval calls the Groww Trading API and safely stores the raw payload in the quarantine repository with SHA-256 integrity checksums.
          </p>
          <p>Status: {report.blocking_code}</p>
          <p>{report.blocking_reason}</p>
          <p>Market data verified: {String(report.real_market_data_verified)}</p>
          <p>Forecast ready: {String(report.forecast_ready)}</p>
          <p>Paper approved: {String(report.paper_approved)}</p>
          <p>Live approved: {String(report.live_approved)}</p>
          <p>Documented NIFTY symbol: {report.instruments?.NIFTY?.groww_symbol}</p>
          <p>Documented SENSEX symbol: {report.instruments?.SENSEX?.groww_symbol}</p>
          <p>Support response received: {String(report.support_response_received)}</p>
          <p>Trusted history: {report.verified_history?.status || "BLOCKED"}. A trusted dataset was created: {String(Boolean(report.verified_history?.trusted_dataset_created))}.</p>
          <p>{report.verified_history?.reason}</p>
          {report.verified_history?.minimum_evidence?.length ? (
            <ul>
              {report.verified_history.minimum_evidence.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : null}
          {report.verified_history?.requirements?.length ? (
            <ul>
              {report.verified_history.requirements.map((item) => (
                <li key={item.id}>{item.status}: {item.id}</li>
              ))}
            </ul>
          ) : null}
          {report.outstanding_confirmations?.length ? (
            <ul>
              {report.outstanding_confirmations.map((item) => (
                <li key={item.id}>{item.status}: {item.question}</li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}
      {ready ? (
        <form onSubmit={submitImport}>
          <h2>Request a range</h2>
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
          <p className="note">The request uses the saved Groww token. The clock sent to Groww is the selected date from 09:15 to 15:30 with the offset removed. That does not establish the provider timezone.</p>
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
        <section>
          <h2>Quarantine diagnostic</h2>
          <p className="note">
            This report reads the stored raw response. It does not send another Groww request and it does not create trusted candles.
          </p>
          {quarantine.records?.length ? quarantine.records.map((row) => (
            <article key={row.quarantine_id}>
              <p>{row.groww_symbol} {row.interval}. Candles {row.candle_count}. Label {row.label}.</p>
              <p>Requested range {row.requested_start_sent} to {row.requested_end_sent}.</p>
              <p>Response range {String(row.response_start_time)} to {String(row.response_end_time)}.</p>
              <p>
                {row.full_timestamp_list_stored
                  ? `Raw timestamps: ${row.raw_timestamps.join(", ")}.`
                  : `Full timestamp list was not stored in this record. First ${row.first_raw_timestamp || "none"}. Last ${row.last_raw_timestamp || "none"}.`}
              </p>
              <p>Quarantine {row.quarantine_id}.</p>
              <p>Record checksum {row.checksum}.</p>
              <p>Raw body SHA-256 {row.raw_body_sha256}.</p>
              <p>Known format: {row.known?.timestamp_format_documented}. Observed offset: {row.known?.observed_offset}.</p>
              <p>Unknown timezone: {row.unknown?.timestamp_timezone}. Unknown boundary: {row.unknown?.candle_boundary}. Unknown request inclusivity: {row.unknown?.request_boundary}.</p>
              <p>Unknown partial candles: {row.unknown?.partial_candles}. Unknown session open: {row.unknown?.session_open_candle}. Unknown session close: {row.unknown?.session_close_candle}.</p>
              <p>Rejection: {row.rejection_code}. {row.rejection_reason}</p>
              <p>Passed checks: {(row.validation?.passed || []).map((item) => item.id).join(", ") || "none"}.</p>
              <p>Failed checks: {(row.validation?.failed || []).map((item) => item.id).join(", ") || "none"}.</p>
              <p>Undetermined checks: {(row.validation?.undetermined || []).map((item) => item.id).join(", ") || "none"}.</p>
              <p>Forecast eligible: {String(row.forecast_eligible)}. Trusted dataset: {String(row.trusted_dataset_created)}.</p>
            </article>
          )) : <p>No quarantined response is stored.</p>}
        </section>
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
      {error ? <p className="error">{error}</p> : null}
    </main>
  );
}
