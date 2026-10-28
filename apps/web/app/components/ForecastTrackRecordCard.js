"use client";

import { useEffect, useState } from "react";

const pct = (v, d = 2) => (v == null ? "N/A" : `${Number(v).toFixed(d)}%`);
const rate = (v) => (v == null ? "—" : `${Math.round(Number(v) * 100)}%`);
const band = (b) => (b ? `${pct(b[0])}–${pct(b[1])}` : "N/A");
const MIN_FOR_JUDGEMENT = 20; // sessions; fewer is too few to tell a good model from luck

function verdict(o) {
  if (!o) return { cls: "indigo", text: "PENDING" };
  if (o.in_band68) return { cls: "emerald", text: "IN 68% BAND" };
  if (o.in_band90) return { cls: "amber", text: "IN 90% BAND" };
  return { cls: "rose", text: "OUTSIDE 90%" };
}

/** Live track record: the forecasts the cards showed, logged when shown, scored after the close. */
export default function ForecastTrackRecordCard() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch("/api/research/forecast-track-record")
      .then(async (res) => {
        const body = await res.json();
        if (res.ok) setData(body);
        else setError(body.message || `HTTP ${res.status}`);
      })
      .catch(() => setError("The forecast track record could not be loaded."));
  }, []);

  if (error) return <div className="v6-card"><p className="v6-section-desc">{error}</p></div>;
  if (!data) return <div className="v6-card"><div className="v6-loading-box">Loading the forecast track record…</div></div>;

  const d = data.daily || {};
  const intraday = Object.entries(data.intraday || {});
  const sessions = Math.max(d.scored || 0, ...intraday.map(([, v]) => v.sessions || 0));

  return (
    <div className="v6-card" data-testid="forecast-track-record-card">
      <div className="v6-card-header">
        <div>
          <span className="v6-badge-sub">
            Recorded when shown, never edited · scored against Groww closes ·{" "}
            {data.first_record ? `since ${data.first_record.slice(0, 10)}` : "nothing recorded yet"}
          </span>
          <h2 className="v6-card-title">Forecast Track Record (live)</h2>
        </div>
        <div className="v6-header-tags">
          <span className={`v6-pill ${sessions >= MIN_FOR_JUDGEMENT ? "indigo" : "amber"}`} data-testid="track-record-sample">
            {sessions >= MIN_FOR_JUDGEMENT ? `${sessions} SESSIONS` : `EARLY: ${sessions} SESSION${sessions === 1 ? "" : "S"}`}
          </span>
        </div>
      </div>
      <p className="v6-section-desc">
        This is the real test: the numbers the cards above showed, saved before the outcome existed. A 90% band should
        hold on about 9 days in 10 and a 68% band on about 2 in 3. Fewer than {MIN_FOR_JUDGEMENT} sessions is too few to judge.
      </p>

      <h3 style={{ marginTop: "12px" }}>Next-session NIFTY range</h3>
      <p className="v6-section-desc" data-testid="track-record-daily-summary">
        {d.scored
          ? `${d.scored} scored: actual range inside the 68% band ${rate(d.range_in_band68)}, inside the 90% band ${rate(d.range_in_band90)}; close move within its 9-in-10 limit ${rate(d.move_within_p90)}.`
          : `${d.logged || 0} logged, none scored yet. A forecast is logged when the research run publishes it before its session, and scored once that session's close is saved.`}
      </p>
      {d.recent?.length ? (
        <table className="v6-data-table" data-testid="track-record-daily-table">
          <thead>
            <tr><th>Session</th><th>Forecast range</th><th>68% / 90% band</th><th>Actual</th><th>Result</th></tr>
          </thead>
          <tbody>
            {d.recent.map((r) => {
              const v = verdict(r.outcome);
              return (
                <tr key={r.for_session}>
                  <td>{r.for_session}</td>
                  <td>{pct(r.expected_range_pct)}</td>
                  <td>{band(r.range_band68_pct)} / {band(r.range_band90_pct)}</td>
                  <td>{r.outcome ? pct(r.outcome.actual_range_pct) : "—"}</td>
                  <td><span className={`v6-pill ${v.cls}`}>{v.text}</span></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : null}

      <h3 style={{ marginTop: "16px" }}>Rest-of-day range (every 15-minute checkpoint)</h3>
      {intraday.length === 0 ? (
        <p className="v6-section-desc">
          Nothing logged yet. While the app runs during market hours, each index's forecast is saved at every checkpoint
          (09:30 … 15:15) and scored after the close once that day's 15-minute history is saved.
        </p>
      ) : (
        <table className="v6-data-table" data-testid="track-record-intraday-table">
          <thead>
            <tr>
              <th>Index</th><th>Checkpoints scored (sessions)</th><th>Range in 90% band</th><th>Range in 68% band</th>
              <th>High under 90% level</th><th>Low above 90% level</th><th>Close in 68% band</th><th>Typical size miss</th>
            </tr>
          </thead>
          <tbody>
            {intraday.map(([name, v]) => (
              <tr key={name}>
                <td>{name}</td>
                <td>{v.scored} of {v.logged} ({v.sessions})</td>
                <td>{rate(v.range_in_band90)}</td>
                <td>{rate(v.range_in_band68)}</td>
                <td>{rate(v.high_within_p90)}</td>
                <td>{rate(v.low_within_p90)}</td>
                <td>{rate(v.close_in_band68)}</td>
                <td>{v.typical_size_error_factor == null ? "—" : `±${Math.round((v.typical_size_error_factor - 1) * 100)}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <ul className="v6-bullet-list" style={{ fontSize: "0.8rem", color: "var(--muted)" }}>
        <li>Targets: 90% bands ≈ 90%, 68% bands ≈ 68%. Much higher means the bands are too wide; much lower means too narrow.</li>
        <li>A checkpoint the app was not running for is missing, not filled in. Scoring runs after each history fetch and research run.</li>
      </ul>
    </div>
  );
}
