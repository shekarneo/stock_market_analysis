"use client";

import { useEffect, useState } from "react";

import Link from "next/link";

import { fillLabel, flagLabel, killSwitchLabel, paperLabel } from "../research/status.mjs";
import { valueText } from "../research/present.mjs";

export function csrf() {
  const match = document.cookie.match(/(?:^|; )imm_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

export default function ResearchBoard({ title, lede, children }) {
  const [status, setStatus] = useState(null);
  const [phase, setPhase] = useState("loading");
  const [error, setError] = useState("");
  async function load() {
    setPhase("loading");
    setError("");
    const response = await fetch("/api/research/status");
    const body = await response.json().catch(() => ({}));
    if (response.status === 401) {
      setStatus(null);
      setPhase("signed-out");
      return;
    }
    if (!response.ok) {
      setStatus(null);
      setPhase("error");
      setError(body.message || body.detail || `Research status failed (${response.status}).`);
      return;
    }
    setStatus(body);
    setPhase("ready");
  }

  useEffect(() => {
    load().catch((err) => {
      setPhase("error");
      setError(err instanceof Error ? err.message : String(err));
    });
  }, []);

  return (
    <main>
      <header className="page-head">
        <p className="eyebrow">Trading desk</p>
        <h1>{title}</h1>
        <p>{lede}</p>
      </header>
      {phase === "loading" ? <p role="status">Loading the book…</p> : null}
      {phase === "error" ? (
        <div className="error" role="alert">
          <p>{error}</p>
          <button type="button" onClick={() => load().catch((err) => setError(String(err)))}>Retry</button>
        </div>
      ) : null}
      {phase === "ready" && status ? <StatusStrip status={status} /> : null}
      {phase === "signed-out" ? (
        <section>
          <h2>Sign in required</h2>
          <p>This page reads the local API. It does not fetch a broker or a market-data vendor.</p>
          {error ? <p className="error" role="alert">{error}</p> : null}
          <Link className="primary" href="/">Sign in</Link>
        </section>
      ) : null}
      {phase === "ready" && status ? children({ status, csrf, reload: load }) : null}
    </main>
  );
}

function StatusStrip({ status }) {
  const experimentalPaper = status.experimental_paper_execution || (status.paper_trading_active ? "Enabled" : "Blocked");
  const forecastEval = status.forecast_evaluation_status || "Active";
  const dataVerification = status.data_verification || (status.real_market_data_verified ? "Verified" : "Unverified");
  const liveBroker = status.live_broker_execution || (status.live_trading_enabled ? "Enabled" : "Locked");

  return (
    <div className="safety">
      <article>
        <h3>Experimental paper</h3>
        <strong style={{ color: experimentalPaper === "Enabled" ? "var(--good, #4ade80)" : "inherit" }}>
          {experimentalPaper}
        </strong>
      </article>
      <article>
        <h3>Forecast evaluation</h3>
        <strong style={{ color: forecastEval === "Active" ? "var(--good, #4ade80)" : "inherit" }}>
          {forecastEval}
        </strong>
      </article>
      <article>
        <h3>Data verification</h3>
        <strong>{dataVerification}</strong>
      </article>
      <article>
        <h3>Live broker</h3>
        <strong style={{ color: liveBroker === "Locked" ? "var(--muted, #94a3b8)" : "var(--bad, #f87171)" }}>
          {liveBroker}
        </strong>
      </article>
      <article>
        <h3>Kill switch</h3>
        <strong>{killSwitchLabel(status.kill_switch)}</strong>
      </article>
      <article>
        <h3>Simulated fills</h3>
        <strong>{fillLabel(status.fills_persisted)}</strong>
      </article>
    </div>
  );
}

export function BlockerList({ blockers }) {
  if (!blockers?.length) return <p>No blockers were returned.</p>;
  return (
    <table>
      <thead>
        <tr>
          <th>Blocker</th>
          <th>Class</th>
        </tr>
      </thead>
      <tbody>
        {blockers.map((item) => (
          <tr key={item.code}>
            <td>
              {item.code === "MISSING_RISK_CAPITAL" ? (
                <Link href="/risk" style={{ textDecoration: "underline", color: "inherit" }} title="Click to configure risk capital in Positions & Capital">
                  MISSING_RISK_CAPITAL
                </Link>
              ) : (
                item.code
              )}
            </td>
            <td>{item.class}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
