"use client";

import { useEffect, useState } from "react";

import ResearchBoard from "../components/ResearchBoard";

export default function RegistryPage() {
  return (
    <ResearchBoard
      title="Model registry"
      lede="Approval for paper or live trading is refused by the registry. This page does not change a model status."
    >
      {() => <Activations />}
    </ResearchBoard>
  );
}

function Activations() {
  const [body, setBody] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    fetch("/api/models/activations")
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) setError(payload.message || "Activations could not be read.");
        else setBody(payload);
      })
      .catch((err) => setError(String(err)));
  }, []);
  if (error) return <p className="error">{error}</p>;
  if (!body) return <p>Loading registry…</p>;
  return (
    <section>
      <h2>Model slots and governance status</h2>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "16px", marginBottom: "20px" }}>
        <article style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: "8px", padding: "16px" }}>
          <span className="eyebrow">Execution Slot</span>
          <h3 style={{ margin: "4px 0 8px" }}>Paper Trading</h3>
          <p style={{ margin: 0, fontSize: "0.9rem" }}>
            Active Slot: <strong>{body.paper_slot || "None (NOT_AVAILABLE)"}</strong>
          </p>
          <p style={{ margin: "4px 0 0", fontSize: "0.82rem", color: "var(--sub, #94a3b8)" }}>
            Paper approval required before any execution can be simulated.
          </p>
        </article>
        <article style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: "8px", padding: "16px" }}>
          <span className="eyebrow">Execution Slot</span>
          <h3 style={{ margin: "4px 0 8px" }}>Live Trading</h3>
          <p style={{ margin: 0, fontSize: "0.9rem" }}>
            Active Slot: <strong>{body.live_slot || "Locked (NO_TRADE)"}</strong>
          </p>
          <p style={{ margin: "4px 0 0", fontSize: "0.82rem", color: "var(--sub, #94a3b8)" }}>
            Live trading is permanently disabled in this build.
          </p>
        </article>
      </div>

      <h3>Governance Gates</h3>
      <dl className="meta-row" style={{ marginBottom: "20px" }}>
        <div><dt>Forecast Ready</dt><dd>{String(body.forecast_ready)}</dd></div>
        <div><dt>Paper Approved</dt><dd>{String(body.paper_approved)}</dd></div>
        <div><dt>Live Approved</dt><dd>{String(body.live_approved)}</dd></div>
        <div><dt>Market Data Verified</dt><dd>{String(body.real_market_data_verified)}</dd></div>
      </dl>

      <h3>Research Selections</h3>
      {(!body.research_selections || body.research_selections.length === 0) ? (
        <p className="note">No research model has been selected. You can select research models on the <a href="/studio">Forecast Model Studio</a>.</p>
      ) : (
        <ul>
          {body.research_selections.map((sel, idx) => (
            <li key={idx}>{JSON.stringify(sel)}</li>
          ))}
        </ul>
      )}

      <details style={{ marginTop: "20px" }}>
        <summary>Registry Technical Payload (JSON)</summary>
        <pre style={{ marginTop: "10px" }}>{JSON.stringify(body, null, 2)}</pre>
      </details>
    </section>
  );
}
