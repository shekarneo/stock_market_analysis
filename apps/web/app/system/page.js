"use client";

import { useEffect, useState } from "react";
import InstrumentSelector from "../components/InstrumentSelector";
import InstrumentDataHealthCard from "../components/InstrumentDataHealthCard";
import V6ReadinessAuditCard from "../components/V6ReadinessAuditCard";

export default function SystemPage() {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    fetch("/health")
      .then(async (response) => setHealth(await response.json()))
      .catch((err) => setError(String(err)));
  }, []);
  return (
    <main>
      <header className="page-head">
        <p className="eyebrow">System Architecture</p>
        <h1>Health, Provenance & Paper Readiness Audit</h1>
        <p>Operational health, multi-instrument data provenance, 8-Gate Paper Readiness certification, and hard financial safety invariants.</p>
      </header>
      {error ? <p className="error">{error}</p> : null}
      {!health && !error ? <p>Loading health…</p> : null}
      {health ? (
        <section className="v6-health-strip">
          <p>
            System Status: <strong className="cyan-text">{health.status}</strong> · Database: <strong>{String(health.database)}</strong> · Operating Mode: <strong>{health.mode || "unknown"}</strong> · Live Orders: <strong className="rose-text">{String(health.live_trading_enabled)} (LOCKED)</strong> · Kill Switch: <strong className={health.kill_switch ? "rose-text" : "emerald-text"}>{health.kill_switch ? "TRIPPED" : "NORMAL (ARMED)"}</strong>
          </p>
        </section>
      ) : null}

      <InstrumentSelector />
      <InstrumentDataHealthCard />
      <V6ReadinessAuditCard />
      <section aria-labelledby="diagnostics-heading">
        <h2 id="diagnostics-heading">Diagnostics</h2>
        <p>Verification detail, model files, and connection settings stay on these pages. They are not the trading desk.</p>
        <ul>
          <li><a href="/history">Historical data and quarantine</a></li>
          <li><a href="/studio">Model studio</a></li>
          <li><a href="/backtest">Walk-forward</a></li>
          <li><a href="/registry">Model registry</a></li>
          <li><a href="/paper">Paper activity</a></li>
          <li><a href="/settings/integrations">Integrations</a></li>
        </ul>
      </section>
    </main>
  );
}
