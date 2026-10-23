"use client";

import { useCallback, useEffect, useState } from "react";
import { csrf } from "./ResearchBoard";

const pct = (v, d = 2) => (v == null ? "N/A" : `${Number(v).toFixed(d)}%`);
const lvl = (v) => (v == null ? "N/A" : `₹${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`);
const ratio = (v, d = 0) => (v == null ? "N/A" : `${(Number(v) * 100).toFixed(d)}%`);
const pval = (v) => (v == null ? "N/A" : v < 0.001 ? "<0.001" : Number(v).toFixed(3));

const WAITING = {
  MARKET_CLOSED: "Market closed",
  PRE_OPEN: "Before the first bar",
  NO_SESSION_TODAY: "No session today",
};
const COVERAGE_LABELS = {
  range_band90: "Range inside 90% band",
  high_within_p90: "High stayed under the 90% level",
  low_within_p90: "Low stayed above the 90% level",
  close_band90: "Close inside 90% band",
};

// Indices with saved Groww history and a live quote; MCX crude has no Groww history, so no model
const INSTRUMENTS = ["NIFTY", "BANKNIFTY", "SENSEX"];

/** Rest-of-day index range, recomputed from the live Groww quote (GET /api/research/intraday-range). */
export default function IntradayRangeCard() {
  const [instrument, setInstrument] = useState("NIFTY");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [updating, setUpdating] = useState(null);

  const load = useCallback(() => {
    fetch(`/api/research/intraday-range?instrument=${instrument}`)
      .then(async (res) => {
        const body = await res.json();
        if (body.instrument && body.instrument !== instrument) return; // a late reply for the previous index
        if (res.ok) {
          setData(body);
          setError(null);
        } else {
          setError(body.message || `HTTP ${res.status}`);
        }
      })
      .catch(() => setError("The intraday range could not be loaded."));
  }, [instrument]);

  useEffect(() => {
    setData(null);
    setError(null);
    setUpdating(null);
    load();
    const timer = setInterval(load, 60000); // the quote is refreshed by the poller every 15 s
    return () => clearInterval(timer);
  }, [load]);

  // Fetch the last two weeks of the index + INDIAVIX daily candles (the model's previous-session inputs)
  const updateHistory = async () => {
    setUpdating("Fetching daily history…");
    const start = new Date(Date.now() - 14 * 86400000).toISOString().slice(0, 10);
    const res = await fetch("/api/research/multiyear/fetch", {
      method: "POST",
      headers: { "content-type": "application/json", "x-csrf-token": csrf() },
      body: JSON.stringify({ symbols: [instrument, "INDIAVIX"], intervals: ["1day"], start }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      setUpdating(`Fetch refused: ${body.message || res.status}`);
      return;
    }
    for (let i = 0; i < 30; i += 1) {
      await new Promise((r) => setTimeout(r, 2000));
      const job = (await (await fetch("/api/research/multiyear")).json()).job;
      if (job && job.status !== "RUNNING") {
        setUpdating(job.status === "SUCCEEDED" ? null : `Fetch failed: ${job.error}`);
        load();
        return;
      }
    }
    setUpdating("Still fetching; refresh in a minute.");
  };

  const m = data?.model || {};
  const ok = data?.status === "OK";
  const header = (
    <div className="v6-card-header">
      <div>
        <span className="v6-badge-sub">
          From the live Groww quote · one model per 15-minute checkpoint · checked on {m.sessions ? `${m.sessions} sessions` : "history"}
        </span>
        <h2 className="v6-card-title">Rest of Today: {instrument} Range</h2>
      </div>
      <div className="v6-header-tags">
        {INSTRUMENTS.map((name) => (
          <button
            key={name}
            type="button"
            className={`v6-btn-toggle ${instrument === name ? "active" : ""}`}
            onClick={() => setInstrument(name)}
            data-testid={`intraday-instrument-${name}`}
          >
            {name}
          </button>
        ))}
        {ok ? <span className="v6-pill indigo" data-testid="intraday-checkpoint">AS OF {data.checkpoint} IST</span> : null}
        {data && !ok ? (
          <span className={`v6-pill ${WAITING[data.status] ? "indigo" : "amber"}`} data-testid="intraday-status">
            {WAITING[data.status] || data.status.replaceAll("_", " ")}
          </span>
        ) : null}
      </div>
    </div>
  );

  if (!data && !error) return <div className="v6-card"><div className="v6-loading-box">Loading the rest-of-day range…</div></div>;

  const imp = m.holdout_mse_improvement_pct || {};
  const dm = m.dm_holdout || {};
  const evidence = m.selected_on_development ? (
    <p className="v6-section-desc" style={{ fontSize: "0.8rem" }} data-testid="intraday-evidence">
      Checked on {m.models?.[m.selected_on_development]?.holdout?.sessions ?? "N/A"} unseen sessions (from {m.holdout_from}):
      error {pct(imp.naive_prev_day, 0)} lower than “yesterday's range scaled to the time left” (DM p = {pval(dm.naive_prev_day?.p_value)}) and{" "}
      {pct(imp.so_far_scaled, 0)} lower than “today's range so far, scaled” (p = {pval(dm.so_far_scaled?.p_value)}).
      Averaged over all checkpoints, the 90% range band held on {ratio(m.holdout_coverage_mean?.range_band90)} of those sessions
      and the 68% band on {ratio(m.holdout_coverage_mean?.range_band68)}.
    </p>
  ) : null;

  if (!ok) {
    return (
      <div className="v6-card" data-testid="intraday-range-card">
        {header}
        <p className="v6-section-desc">{error || data.message}</p>
        {data?.status === "HISTORY_BEHIND" || data?.status === "HISTORY_MISSING" ? (
          <button type="button" className="v6-btn" onClick={updateHistory} disabled={Boolean(updating)} data-testid="intraday-update-history">
            Update daily history
          </button>
        ) : null}
        {updating ? <p className="v6-section-desc">{updating}</p> : null}
        {evidence}
      </div>
    );
  }

  const under = data.undercovered || [];
  return (
    <div className="v6-card" data-testid="intraday-range-card">
      {header}
      <div className="v6-metrics-grid">
        <div className="v6-metric-card">
          <span className="v6-metric-label">Still to travel by the close</span>
          <div className="v6-metric-val cyan-text" data-testid="intraday-expected">{pct(data.expected_remaining_range_pct)}</div>
          <span className="v6-metric-sub">
            ~{Math.round(data.expected_remaining_range_points)} pts from ₹{Number(data.price).toLocaleString("en-IN")} · 90% band{" "}
            {pct(data.remaining_range_band90_pct?.[0])}–{pct(data.remaining_range_band90_pct?.[1])}
          </span>
        </div>
        <div className="v6-metric-card">
          <span className="v6-metric-label">High from now to the close</span>
          <div className="v6-metric-val">{lvl(data.high_by_close?.p68)}</div>
          <span className="v6-metric-sub">68% of days stay under this · 90%: {lvl(data.high_by_close?.p90)}</span>
        </div>
        <div className="v6-metric-card">
          <span className="v6-metric-label">Low from now to the close</span>
          <div className="v6-metric-val">{lvl(data.low_by_close?.p68)}</div>
          <span className="v6-metric-sub">68% of days stay above this · 90%: {lvl(data.low_by_close?.p90)}</span>
        </div>
        <div className="v6-metric-card">
          <span className="v6-metric-label">Close band</span>
          <div className="v6-metric-val">{lvl(data.close_band68?.[0])} – {lvl(data.close_band68?.[1])}</div>
          <span className="v6-metric-sub">68% band · 90%: {lvl(data.close_band90?.[0])} – {lvl(data.close_band90?.[1])}</span>
        </div>
      </div>

      <table className="v6-data-table" style={{ marginTop: "12px" }} data-testid="intraday-coverage-table">
        <thead>
          <tr>
            <th>At {data.checkpoint} on unseen sessions (n={data.holdout_sessions})</th>
            <th>Held</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(COVERAGE_LABELS).map(([key, label]) => (
            <tr key={key}>
              <td>{label}</td>
              <td className={under.includes(key) ? "amber-text" : ""}>{ratio(data.holdout_coverage?.[key], 1)} (target 90%)</td>
            </tr>
          ))}
        </tbody>
      </table>
      {under.length ? (
        <p className="v6-section-desc amber-text" data-testid="intraday-undercovered">
          At this time of day some 90% bands held less than 85% of the time on unseen sessions; treat them as narrower than stated.
        </p>
      ) : null}
      {evidence}
      <ul className="v6-bullet-list" style={{ fontSize: "0.8rem", color: "var(--muted)" }}>
        <li>Size of the move only: this says how far {instrument} is likely to travel, not which way.</li>
        <li>
          Quote {data.quote?.retrieved_at ? new Date(data.quote.retrieved_at).toLocaleTimeString("en-IN") : "N/A"} (day so far: open{" "}
          {lvl(data.quote?.ohlc?.open)}, high {lvl(data.quote?.ohlc?.high)}, low {lvl(data.quote?.ohlc?.low)}); refreshed every minute.
        </li>
        <li>Statistical expectations, not trade signals.</li>
      </ul>
    </div>
  );
}
