"use client";

import { useState } from "react";

import ResearchBoard, { csrf } from "../components/ResearchBoard";

export default function BacktestPage() {
  return (
    <ResearchBoard
      title="Walk-forward"
      lede="A synthetic walk-forward run is research. It is not out-of-sample market performance and it does not approve a model."
    >
      {() => <Runner />}
    </ResearchBoard>
  );
}

function Runner() {
  const [instrument, setInstrument] = useState("NIFTY");
  const [provider, setProvider] = useState("synthetic");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  async function run() {
    setError("");
    setBusy(true);
    try {
      const response = await fetch("/api/walk-forward", {
        method: "POST",
        headers: { "content-type": "application/json", "x-csrf-token": csrf() },
        body: JSON.stringify({ instrument, provider }),
      });
      const body = await response.json();
      if (!response.ok && !body.artifact) setError(body.message || "The run was refused.");
      setResult({ status: response.status, ...body });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <h2>Walk-forward evaluation runner</h2>
      <div style={{ display: "flex", gap: "12px", alignItems: "center", flexWrap: "wrap", marginBottom: "16px" }}>
        <label>
          Instrument
          <select value={instrument} onChange={(e) => setInstrument(e.target.value)}>
            <option value="NIFTY">NIFTY 50</option>
            <option value="SENSEX">SENSEX</option>
            <option value="CRUDEOILMINI">CRUDE OIL MINI</option>
          </select>
        </label>
        <label>
          Provider
          <select value={provider} onChange={(e) => setProvider(e.target.value)}>
            <option value="synthetic">Synthetic Quiet-Day Fixture</option>
            <option value="historical">Historical Ingested Dataset</option>
          </select>
        </label>
      </div>
      <button className="primary" type="button" onClick={run} disabled={busy}>
        {busy ? "Running evaluation…" : "Run walk-forward evaluation"}
      </button>
      {error ? <p className="error" style={{ marginTop: "12px" }}>{error}</p> : null}
      {result ? (
        <div style={{ marginTop: "16px" }}>
          <p>
            HTTP {result.status}. Forecast ready: <strong>{String(result.forecast_ready)}</strong>. Paper approved: <strong>{String(result.paper_approved)}</strong>. Real market data verified: <strong>{String(result.real_market_data_verified)}</strong>.
            {result.code ? ` Code: ${result.code}.` : ""}
          </p>
          {result.message ? <p className="note">{result.message}</p> : null}
          {result.readiness?.unmet_requirements?.length > 0 && (
            <div style={{ marginTop: "12px" }}>
              <h3>Required Pipeline Gates ({result.readiness.unmet_requirements.length} unmet)</h3>
              <ul>
                {result.readiness.unmet_requirements.map((gate) => (
                  <li key={gate} style={{ fontSize: "0.88rem", color: "var(--sub, #94a3b8)" }}>
                    🚫 {gate}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}
