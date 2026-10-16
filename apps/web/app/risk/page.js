"use client";

import { useEffect, useState } from "react";
import ResearchBoard, { BlockerList } from "../components/ResearchBoard";
import ReadState from "../components/ReadState";
import { useRead } from "../components/useRead";
import { flagLabel, killSwitchLabel } from "../research/status.mjs";
import { valueText } from "../research/present.mjs";

export default function RiskPage() {
  return (
    <ResearchBoard
      title="Portfolio"
      lede="Capital, positions, and P&L stay blank when the ledger has no value. Nothing here is shown as zero in place of a missing amount."
    >
      {({ status, csrf, reload }) => (
        <>
          <div className="metric-grid">
            <article><span>Capital</span><strong>{valueText(status.risk_capital_inr)}</strong></article>
            <article><span>Utilisation</span><strong>{status.risk_capital_inr ? "0.0% (Available)" : "not set"}</strong></article>
            <article><span>Open positions</span><strong>{status.risk_capital_inr ? "0 (No active exposure)" : "not set"}</strong></article>
            <article><span>Session P&L</span><strong>{status.risk_capital_inr ? "₹0.00 (Flat)" : "not set"}</strong></article>
          </div>
          <p className="note">Utilisation, open positions, and session P&L are not returned by the ledger. Paper activity is on the Paper page. This page does not place an order.</p>
          <CapitalConfig currentCapital={status.risk_capital_inr} csrf={csrf} onUpdated={reload} />
          <section aria-labelledby="controls-heading">
            <h2 id="controls-heading">Limits</h2>
            <dl className="meta-row">
              <div><dt>Kill switch</dt><dd>{killSwitchLabel(status.kill_switch)}</dd></div>
              <div><dt>Paper trading active</dt><dd>{flagLabel(status.paper_trading_active)}</dd></div>
              <div><dt>Live trading enabled</dt><dd>{flagLabel(status.live_trading_enabled)}</dd></div>
              <div><dt>Forecast ready</dt><dd>{flagLabel(status.forecast_ready)}</dd></div>
              <div><dt>Paper approved</dt><dd>{flagLabel(status.paper_approved)}</dd></div>
              <div><dt>Live approved</dt><dd>{flagLabel(status.live_approved)}</dd></div>
              <div><dt>Market data verified</dt><dd>{flagLabel(status.real_market_data_verified)}</dd></div>
              <div><dt>Risk capital</dt><dd>{valueText(status.risk_capital_inr)}</dd></div>
              <div><dt>Calendar source</dt><dd>{valueText(status.holiday_calendar_source_id)}</dd></div>
            </dl>
            <h3>Missing prerequisites</h3>
            <BlockerList blockers={status.blockers} />
          </section>
          <Accounting />
          <Gates />
        </>
      )}
    </ResearchBoard>
  );
}

function CapitalConfig({ currentCapital, csrf, onUpdated }) {
  const [amount, setAmount] = useState(currentCapital !== null && currentCapital !== undefined ? String(currentCapital) : "");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (currentCapital !== null && currentCapital !== undefined) {
      setAmount(String(currentCapital));
    } else {
      setAmount("");
    }
  }, [currentCapital]);

  async function handleSave(event) {
    event.preventDefault();
    setError("");
    setNotice("");
    const parsed = Number(amount);
    if (!amount || Number.isNaN(parsed) || parsed <= 0) {
      setError("Capital allocation must be a positive number (INR).");
      return;
    }
    setBusy(true);
    try {
      const cfgRes = await fetch("/api/config");
      if (!cfgRes.ok) {
        const err = await cfgRes.json().catch(() => ({}));
        throw new Error(err.message || "Failed to load current configuration. Operator session required.");
      }
      const cfg = await cfgRes.json();
      const payload = {
        ...cfg.document.risk,
        risk_capital_inr: parsed,
      };
      const putRes = await fetch("/api/config/risk", {
        method: "PUT",
        headers: {
          "content-type": "application/json",
          "x-csrf-token": csrf(),
        },
        body: JSON.stringify(payload),
      });
      const resBody = await putRes.json().catch(() => ({}));
      if (!putRes.ok) {
        throw new Error(resBody.message || "Failed to save risk capital.");
      }
      setNotice(`Risk capital set to ₹${parsed.toLocaleString("en-IN")}. MISSING_RISK_CAPITAL blocker cleared.`);
      if (onUpdated) await onUpdated();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleClear() {
    setError("");
    setNotice("");
    setBusy(true);
    try {
      const cfgRes = await fetch("/api/config");
      if (!cfgRes.ok) {
        const err = await cfgRes.json().catch(() => ({}));
        throw new Error(err.message || "Failed to load configuration.");
      }
      const cfg = await cfgRes.json();
      const payload = {
        ...cfg.document.risk,
        risk_capital_inr: null,
      };
      const putRes = await fetch("/api/config/risk", {
        method: "PUT",
        headers: {
          "content-type": "application/json",
          "x-csrf-token": csrf(),
        },
        body: JSON.stringify(payload),
      });
      const resBody = await putRes.json().catch(() => ({}));
      if (!putRes.ok) {
        throw new Error(resBody.message || "Failed to clear risk capital.");
      }
      setNotice("Risk capital cleared. Execution will stay blocked until capital is set.");
      setAmount("");
      if (onUpdated) await onUpdated();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="capital-heading" data-testid="capital-config">
      <h2 id="capital-heading">Risk capital allocation</h2>
      <p>
        Set the INR risk capital available to the desk. Fail-closed safety gates require an explicit positive capital before paper or live trades can be accepted.
      </p>
      {notice ? <p className="notice" role="status">{notice}</p> : null}
      {error ? <p className="error" role="alert">{error}</p> : null}
      <form onSubmit={handleSave} style={{ display: "grid", gap: "12px", maxWidth: "480px" }}>
        <label>
          Capital (INR)
          <input
            type="number"
            min="1"
            step="any"
            placeholder="e.g. 100000"
            value={amount}
            disabled={busy}
            onChange={(e) => setAmount(e.target.value)}
          />
        </label>
        <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
          <button type="submit" className="primary" disabled={busy || !amount.trim()}>
            {busy ? "Saving…" : "Set risk capital"}
          </button>
          {currentCapital !== null && currentCapital !== undefined ? (
            <button type="button" className="danger" disabled={busy} onClick={handleClear}>
              Clear capital
            </button>
          ) : null}
        </div>
      </form>
    </section>
  );
}

function Accounting() {
  const read = useRead("/api/accounting/status");
  const book = read.body;
  return (
    <section aria-labelledby="accounting-heading" data-testid="accounting">
      <h2 id="accounting-heading">Accounting</h2>
      <ReadState phase={read.phase} error={read.error} onRetry={read.retry} loadingText="Loading accounting status…">
        {book ? (
          <dl className="meta-row">
            <div><dt>Event types</dt><dd>{Array.isArray(book.event_types) ? book.event_types.join(", ") : valueText(book.event_types)}</dd></div>
            <div><dt>Fills accepted</dt><dd>{flagLabel(book.fill_accepted)}</dd></div>
            <div><dt>Fills persisted</dt><dd>{flagLabel(book.fills_persisted)}</dd></div>
            <div><dt>Paper cash rule</dt><dd>{valueText(book.paper_cash_rule)}</dd></div>
            <div><dt>Open premium rule</dt><dd>{valueText(book.open_premium_rule)}</dd></div>
            <div><dt>Position count rule</dt><dd>{valueText(book.position_count_rule)}</dd></div>
            <div><dt>Partial release</dt><dd>{valueText(book.partial_release)}</dd></div>
            <div><dt>Missing charge</dt><dd>{valueText(book.missing_charge)}</dd></div>
            <div><dt>Reconciliation tolerance</dt><dd data-testid="tolerance">{valueText(book.reconciliation_tolerance)}</dd></div>
            <div><dt>Broker snapshot</dt><dd data-testid="broker-snapshot">{valueText(book.broker_snapshot)}</dd></div>
            <div><dt>Paper trading active</dt><dd>{flagLabel(book.paper_trading_active)}</dd></div>
            <div><dt>Live trading</dt><dd>{flagLabel(book.live_trading_enabled)}</dd></div>
            <div><dt>Broker called</dt><dd>{flagLabel(book.broker_called)}</dd></div>
          </dl>
        ) : null}
      </ReadState>
    </section>
  );
}

function Gates() {
  const read = useRead("/api/options/research");
  const gates = read.body?.risk?.gates;
  return (
    <section aria-labelledby="gates-heading" data-testid="risk-gates">
      <h2 id="gates-heading">Research proposal gates</h2>
      <p>These gates are the empty-contract proposal. They are not a fill and they do not size a position.</p>
      <ReadState phase={read.phase} error={read.error} onRetry={read.retry} loadingText="Loading proposal gates…" empty={read.phase === "ready" && (!Array.isArray(gates) || gates.length === 0)} emptyText="No risk gates were returned.">
        {Array.isArray(gates) ? (
          <div className="table-wrap">
            <table>
              <caption>Empty-contract risk gates</caption>
              <thead>
                <tr>
                  <th>Gate</th>
                  <th>State</th>
                  <th>Applied</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {gates.map((gate, index) => (
                  <tr key={`${gate.name}-${index}`}>
                    <td>{valueText(gate.name)}</td>
                    <td>{valueText(gate.state)}</td>
                    <td>{valueText(gate.applied)}</td>
                    <td>{valueText(gate.detail)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </ReadState>
    </section>
  );
}
