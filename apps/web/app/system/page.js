"use client";

import { useEffect, useState } from "react";

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
        <p className="eyebrow">System</p>
        <h1>Health</h1>
        <p>Database connectivity is reported by the API. A missing kill switch is not shown as off. Secrets are not displayed.</p>
      </header>
      {error ? <p className="error">{error}</p> : null}
      {!health && !error ? <p>Loading health…</p> : null}
      {health ? (
        <section>
          <p>Status {health.status}. Database {String(health.database)}. Mode {health.mode || "unknown"}.</p>
          <p>Live trading enabled {String(health.live_trading_enabled)}. Live order server flag {String(health.live_order_server_flag)}.</p>
          <p>Kill switch {health.kill_switch === null ? "not read" : String(health.kill_switch)}.</p>
        </section>
      ) : null}
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
