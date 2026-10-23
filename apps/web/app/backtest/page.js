"use client";

import { useState } from "react";
import Link from "next/link";

import ResearchBoard, { csrf } from "../components/ResearchBoard";
import InstrumentBacktestCard from "../components/InstrumentBacktestCard";
import V6MultiAssetCard from "../components/V6MultiAssetCard";
import MultiYearResearchCard from "../components/MultiYearResearchCard";

export default function BacktestPage() {
  return (
    <ResearchBoard
      title="Walk-forward & Multi-Asset Research"
      lede="Independent instrument-level evaluation, higher-timeframe swing resampling, 19-fold walk-forward cross-validation, statutory friction accounting, and factor attribution."
    >
      {() => (
        <>
          <div style={{ display: "flex", gap: "8px", background: "var(--card-subtle, #131c31)", padding: "4px", borderRadius: "10px", border: "1px solid var(--line)", marginBottom: "20px", flexWrap: "wrap" }}>
            <span style={{ padding: "8px 16px", borderRadius: "8px", background: "rgba(255, 255, 255, 0.12)", color: "#ffffff", fontWeight: 650, fontSize: "0.85rem" }}>
              📊 Walk-Forward &amp; Multi-Asset Backtest
            </span>
            <Link href="/paper" style={{ padding: "8px 16px", borderRadius: "8px", color: "var(--muted)", fontWeight: 650, fontSize: "0.85rem", textDecoration: "none" }}>
              📒 Paper Ledger &amp; Intent Audit Replay →
            </Link>
          </div>
          <InstrumentBacktestCard />
          <V6MultiAssetCard />
          <MultiYearResearchCard />
          <Runner />
        </>
      )}
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
