"use client";

import { useEffect, useState } from "react";

const rate = (v, d = 1) => (v == null ? "N/A" : `${(Number(v) * 100).toFixed(d)}%`);
const ci = (pair) => (pair && pair[0] != null ? `${(pair[0] * 100).toFixed(0)}–${(pair[1] * 100).toFixed(0)}%` : "N/A");
const pval = (v) => (v == null ? "N/A" : Number(v) < 0.001 ? "<0.001" : Number(v).toFixed(3));
const signed = (v) => (v == null ? "N/A" : `${Number(v) >= 0 ? "+" : ""}${Number(v).toFixed(3)}%`);

const STATUS = {
  PROVEN: { cls: "emerald", text: "PROVEN" },
  NO_EDGE_YET: { cls: "amber", text: "NO EDGE YET" },
  WORSE_THAN_CHANCE: { cls: "rose", text: "WORSE THAN CHANCE" },
  COLLECTING: { cls: "indigo", text: "COLLECTING" },
};

/** Measured accuracy of the agents (GET /api/research/agents): history replay + forward scorecard. */
export default function AgentTrackRecordCard() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/api/research/agents")
      .then(async (res) => {
        const body = await res.json();
        if (!res.ok) throw new Error(body.message || `HTTP ${res.status}`);
        setData(body);
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  if (error) return <div className="v6-card"><div className="v6-error-box">{error}</div></div>;
  if (!data) return <div className="v6-card"><div className="v6-loading-box">Loading agent track records…</div></div>;

  const tech = data.backtest?.agents?.technical_analyst;
  const verdict = tech?.verdict;
  const scorecard = data.scorecard?.agents || {};

  return (
    <div className="v6-card" data-testid="agent-track-record-card">
      <div className="v6-card-header">
        <div>
          <span className="v6-badge-sub">Measured, not stated: each agent's calls scored against what NIFTY did next</span>
          <h2 className="v6-card-title">Agent Track Records</h2>
        </div>
        <div className="v6-header-tags">
          {tech ? (
            <span className={`v6-pill ${verdict?.edge_supported ? "emerald" : "amber"}`}>
              TECHNICAL: {verdict?.edge_supported ? "TRADEABLE EDGE" : "NO TRADEABLE EDGE"}
            </span>
          ) : null}
        </div>
      </div>
      <p className="v6-section-desc">
        Agent calls are locked to their scored rule: the LLM can explain a call but cannot change its direction or
        confidence. A measured agent's confidence is its historical hit rate, and the consensus weights it by its skill over
        a coin flip (50% right carries no weight).
      </p>

      <h3>Technical Analyst: replay on {data.backtest?.sessions ?? "—"} sessions</h3>
      {tech ? (
        <>
          <p className="v6-section-desc" style={{ fontSize: "0.8rem" }}>{tech.rule}</p>
          <table className="v6-data-table" data-testid="agent-backtest-table">
            <thead>
              <tr>
                <th>Call made at (IST)</th>
                <th>About</th>
                <th>Right (all years, 95% CI)</th>
                <th>p vs 50%</th>
                <th>Right (unseen period)</th>
                <th>Net per call after costs</th>
                <th>Stated vs actual confidence</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(tech.checkpoints || {}).flatMap(([cp, r]) =>
                ["rest_of_day", "next_session"].map((h) => {
                  const a = r[h]?.all || {};
                  const hold = r[h]?.holdout || {};
                  return (
                    <tr key={`${cp}-${h}`}>
                      <td>{cp}</td>
                      <td>{h === "rest_of_day" ? "Rest of day" : "Next session"}</td>
                      <td>{rate(a.hit_rate)} ({ci(a.hit_rate_ci95)}), n={a.n_calls ?? 0}</td>
                      <td>{pval(a.p_value_vs_50pct)}</td>
                      <td>{rate(hold.hit_rate)} (p {pval(hold.p_value_vs_50pct)})</td>
                      <td className={Number(a.mean_net_return_pct_per_call) > 0 ? "emerald-text" : "rose-text"}>{signed(a.mean_net_return_pct_per_call)}</td>
                      <td style={{ fontSize: "0.78rem" }}>
                        {(a.calibration || []).map((c) => `${c.stated_confidence} → ${rate(c.actual_hit_rate, 0)}`).join(" · ")}
                      </td>
                    </tr>
                  );
                }),
              )}
            </tbody>
          </table>
          <p className="v6-section-desc" style={{ fontSize: "0.78rem" }}>
            A tradeable edge needs the unseen period to beat both 50% and the same-bias baseline (p &lt; 0.05) and to make
            money after index-futures costs. Generated {data.backtest?.generated_at ? data.backtest.generated_at.slice(0, 16).replace("T", " ") : "—"}.
          </p>
        </>
      ) : (
        <p className="v6-section-desc">Not measured yet. Run the research on the Backtest page, or `python -m app.cli agent-backtest`.</p>
      )}

      <h3 style={{ marginTop: "18px" }}>Forward scorecard (every agent, from live analyses)</h3>
      {Object.keys(scorecard).length === 0 ? (
        <p className="v6-section-desc">
          No calls recorded yet. Each NIFTY analysis run records every agent's call; the rest-of-day result is scored
          at that session's close and the next-session result a session later. A verdict needs at least{" "}
          {data.scorecard?.min_scored_for_verdict ?? 30} scored calls.
        </p>
      ) : (
        <>
        <p className="v6-section-desc">
          Only one call per agent per session counts (the first in-session call, plus the first call made outside market
          hours): re-running the analysis repeats the same market view and does not add evidence.
        </p>
        <table className="v6-data-table" data-testid="agent-scorecard-table">
          <thead>
            <tr>
              <th>Agent</th>
              <th>Status</th>
              <th>Right: rest of day</th>
              <th>Right: next session</th>
              <th>Counted calls (directional / pending) · recorded</th>
              <th>Last call</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(scorecard).map(([name, row]) => {
              const st = STATUS[row.status] || { cls: "indigo", text: row.status };
              const cell = (s) => (s?.n ? `${rate(s.hit_rate)} of ${s.n} (p ${pval(s.p_value_vs_50pct)})` : "—");
              return (
                <tr key={name}>
                  <td>{name}</td>
                  <td><span className={`v6-pill ${st.cls}`}>{st.text}</span></td>
                  <td>{cell(row.rest_of_day)}</td>
                  <td>{cell(row.next_session)}</td>
                  <td>{row.calls} ({row.directional_calls} / {row.pending}) · {row.recorded_calls ?? row.calls}</td>
                  <td>{row.last_call ? row.last_call.slice(0, 16).replace("T", " ") : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        </>
      )}
    </div>
  );
}
