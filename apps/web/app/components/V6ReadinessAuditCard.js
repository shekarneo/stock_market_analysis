"use client";

import { useEffect, useState } from "react";
import { csrfToken as csrf } from "./session";

const GATE_ORDER = [
  "GATE_1_SAFETY_INVARIANTS",
  "GATE_2_DATA_PROVENANCE",
  "GATE_3_COST_ABSORPTION",
  "GATE_4_PORTFOLIO_RISK",
  "GATE_5_DRIFT_MONITORING",
  "GATE_6_MULTI_AGENT_CONSENSUS",
  "GATE_7_PAPER_ACCOUNTING",
  "GATE_8_OPS_CONTROLS",
];
// These gates confirm the module exists; they do not measure its results
const CODE_PRESENCE_GATES = new Set([
  "GATE_2_DATA_PROVENANCE",
  "GATE_4_PORTFOLIO_RISK",
  "GATE_5_DRIFT_MONITORING",
  "GATE_6_MULTI_AGENT_CONSENSUS",
  "GATE_7_PAPER_ACCOUNTING",
]);
const STATUS_CLASS = { PASSED: "passed", WARNING: "warning", FAILED: "failed" };
const SOURCE_LABEL = {
  daily_direction_research: "Daily direction research",
  next_session_forecast: "Next-session forecast",
  technical_agent_replay: "Technical agent replay",
};
const sourceText = (v) => (v === true ? "edge shown" : v === false ? "no edge" : "not run");

export default function V6ReadinessAuditCard() {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [killSwitchActive, setKillSwitchActive] = useState(false);
  const [busySwitch, setBusySwitch] = useState(false);
  const [error, setError] = useState("");

  async function loadAudit() {
    setLoading(true);
    setLoadError("");
    try {
      const res = await fetch("/api/research/paper-readiness");
      if (res.ok) {
        setReport(await res.json());
      } else {
        setReport(null);
        setLoadError(`The readiness audit could not be run (HTTP ${res.status}).`);
      }
    } catch {
      setReport(null);
      setLoadError("The readiness audit could not be reached.");
    } finally {
      setLoading(false);
    }
  }

  async function loadHealth() {
    try {
      const res = await fetch("/health");
      if (res.ok) {
        const h = await res.json();
        setKillSwitchActive(Boolean(h.kill_switch));
      }
    } catch {}
  }

  useEffect(() => {
    loadAudit();
    loadHealth();
  }, []);

  async function toggleKillSwitch() {
    setBusySwitch(true);
    setError("");
    try {
      const res = await fetch("/api/config/risk", {
        method: "PUT",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf() },
        body: JSON.stringify({ kill_switch: !killSwitchActive }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setError(body.message || `The kill switch was not changed (HTTP ${res.status}).`);
        return;
      }
      await loadHealth(); // show the server's state, not the one we asked for
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusySwitch(false);
    }
  }

  const invariants = report?.safety_invariants || {};
  const gates = report?.gates || {};
  const ready = report?.overall_readiness === "READY_FOR_PAPER_SIMULATION";
  const edge = gates.GATE_3_COST_ABSORPTION?.metrics;

  return (
    <div className="v6-audit-panel" data-testid="readiness-audit-card">
      <div className="v6-panel-head">
        <div>
          <div className="v6-badge-row">
            <span className="v6-pill cyan">PAPER READINESS AUDIT</span>
            {report ? (
              <span className={`v6-pill ${report.failed_gates ? "rose" : report.warning_gates ? "amber" : "emerald"}`} data-testid="readiness-gate-count">
                {report.passed_gates}/{report.total_gates_evaluated} GATES PASSED
              </span>
            ) : null}
            <span className="v6-pill rose">LIVE: {report?.live_trading_verdict || "STRICT_NO_GO_LOCKED"}</span>
          </div>
          <h3 className="v6-panel-title">8-Gate Paper Readiness Audit & Risk Invariants</h3>
          <p className="v6-panel-sub">
            Evaluates the 8 prerequisites before paper simulation. Live broker routing is permanently locked.
          </p>
        </div>

        <button className="v6-btn neutral" type="button" onClick={loadAudit} disabled={loading}>
          {loading ? "Running the audit…" : "Re-Run Readiness Audit"}
        </button>
      </div>

      {error ? <div className="v6-alert error">{error}</div> : null}
      {loadError ? <div className="v6-alert error">{loadError}</div> : null}

      {report ? (
        <>
          <div className="v6-verdict-banner">
            <div className="v6-verdict-left">
              <div className="v6-verdict-pill-wrap">
                <span className={`v6-verdict-tag ${ready ? "passed" : "locked"}`}>PAPER SIMULATION VERDICT</span>
                <span className="v6-verdict-tag locked">LIVE CAPITAL ROUTING</span>
              </div>
              <h2 className="v6-verdict-heading" data-testid="readiness-verdict">{report.overall_readiness}</h2>
              <p className="v6-verdict-desc">
                {ready
                  ? "No gate failed. All safety invariants are False."
                  : `Blocked by: ${(report.active_blockers || []).join(", ") || `${report.failed_gates} failing gate(s)`}.`}
              </p>
            </div>
            <div className="v6-verdict-right">
              <div className="v6-lock-status">
                <span className="v6-lock-icon">🔒</span>
                <div>
                  <strong>{report.live_trading_verdict}</strong>
                  <small>Live broker execution blocked by hardware/software invariants</small>
                </div>
              </div>
            </div>
          </div>

          <div className="v6-invariants-box">
            <div className="v6-invariants-head">
              <h4>The 5 Financial Safety Invariants</h4>
              <span className={`v6-pill ${Object.values(invariants).every((v) => v === false) ? "emerald" : "rose"}`}>
                {Object.values(invariants).every((v) => v === false) ? "ALL 5 FALSE (LOCKED)" : "AN INVARIANT IS NOT FALSE"}
              </span>
            </div>
            <div className="v6-invariants-grid">
              {Object.entries(invariants).map(([flag, value]) => (
                <div className="v6-invariant-card" key={flag}>
                  <code>{flag}</code>
                  <strong className={value === false ? "rose-text" : "amber-text"}>{String(value)}</strong>
                </div>
              ))}
            </div>
          </div>

          <div className="v6-gates-container">
            <h4>Detailed 8-Gate Readiness Assessment</h4>
            <div className="v6-gates-list">
              {GATE_ORDER.filter((id) => gates[id]).map((id, i) => {
                const gate = gates[id];
                const cls = STATUS_CLASS[gate.status] || "warning";
                return (
                  <div key={id} className={`v6-gate-row ${cls}`} data-testid={`readiness-gate-${i + 1}`}>
                    <div className="v6-gate-num">{i + 1}</div>
                    <div className="v6-gate-info">
                      <div className="v6-gate-title-row">
                        <strong>{gate.name}</strong>
                        <span className={`v6-gate-status-pill ${cls}`}>{gate.status}</span>
                      </div>
                      <p className="v6-gate-desc">{gate.description}</p>
                      {id === "GATE_3_COST_ABSORPTION" && edge?.sources ? (
                        <p className="v6-gate-desc" data-testid="readiness-edge-sources">
                          Evidence:{" "}
                          {Object.entries(edge.sources)
                            .map(([k, v]) => `${SOURCE_LABEL[k] || k}: ${sourceText(v)}`)
                            .join(" · ")}
                        </p>
                      ) : null}
                      {CODE_PRESENCE_GATES.has(id) ? (
                        <p className="v6-gate-desc dim-text">Checks that the module exists, not its results.</p>
                      ) : null}
                      <span className="v6-gate-verified">Checked against: <code>{gate.verified_by}</code></span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
          {(report.audit_notes || []).length ? (
            <ul className="v6-bullet-list" style={{ fontSize: "0.8rem" }}>
              {report.audit_notes.map((n) => <li key={n}>{n}</li>)}
            </ul>
          ) : null}
        </>
      ) : null}

      <div className="v6-killswitch-bar">
        <div>
          <strong>Operational Kill Switch Failsafe</strong>
          <p className="dim-text">
            Tripping the kill switch immediately locks all worker daemon loops, cancels pending simulation orders, and enters emergency stand-aside state.
          </p>
        </div>

        <div className="v6-killswitch-controls">
          <span className={`v6-killswitch-indicator ${killSwitchActive ? "tripped" : "normal"}`}>
            ● {killSwitchActive ? "KILL SWITCH TRIPPED" : "KILL SWITCH NORMAL (ARMED)"}
          </span>
          <button
            type="button"
            className={`v6-btn ${killSwitchActive ? "neutral" : "danger"}`}
            onClick={toggleKillSwitch}
            disabled={busySwitch}
          >
            {busySwitch ? "Processing…" : killSwitchActive ? "Clear Kill Switch" : "Trip Kill Switch"}
          </button>
        </div>
      </div>
    </div>
  );
}
