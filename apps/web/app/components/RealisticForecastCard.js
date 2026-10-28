"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

const pct = (v, d = 2) => (v == null ? "N/A" : `${Number(v).toFixed(d)}%`);
const pts = (v) => (v == null ? "N/A" : `~${Math.round(Number(v)).toLocaleString("en-IN")} pts`);
const ratio = (v, d = 1) => (v == null ? "N/A" : `${(Number(v) * 100).toFixed(d)}%`);
const num = (v, d = 3) => (v == null ? "N/A" : Number(v).toFixed(d));

/** Next-session NIFTY forecast from the tuned multi-year models (GET /api/research/multiyear/forecast). */
export default function RealisticForecastCard({ compact = false }) {
  const [forecast, setForecast] = useState(null);
  const [state, setState] = useState("loading");

  useEffect(() => {
    let cancelled = false;
    fetch("/api/research/multiyear/forecast")
      .then(async (res) => {
        const body = await res.json();
        if (cancelled) return;
        if (res.ok) {
          setForecast(body);
          setState("ready");
        } else {
          setState(body.code === "FORECAST_MISSING" ? "missing" : "error");
        }
      })
      .catch(() => !cancelled && setState("error"));
    return () => {
      cancelled = true;
    };
  }, []);

  if (state === "loading") return <div className="v6-card"><div className="v6-loading-box">Loading the next-session forecast…</div></div>;
  if (state !== "ready") {
    return (
      <div className="v6-card" data-testid="realistic-forecast-card">
        <h2 className="v6-card-title">Next-Session NIFTY Forecast</h2>
        <p className="v6-section-desc">
          {state === "missing"
            ? "No forecast yet. Fetch history and run the research on the Backtest page (Multi-Year Research card), or run `python -m app.cli forecast-daily`."
            : "The forecast could not be loaded."}
        </p>
        <Link href="/backtest">Open the research card →</Link>
      </div>
    );
  }

  const rng = forecast.range || {};
  const d = forecast.direction_next_session || {};
  const h = forecast.direction_next_half_day || {};
  const edge = d.status === "EDGE_SUPPORTED";
  // A forecast for a session that has already passed is history, not a forecast
  const todayIst = new Date(Date.now() + 5.5 * 3600000).toISOString().slice(0, 10);
  const stale = forecast.for_session && forecast.for_session < todayIst;

  return (
    <div className="v6-card" data-testid="realistic-forecast-card">
      <div className="v6-card-header">
        <div>
          <span className="v6-badge-sub">Tuned on {forecast.inputs?.nifty_daily_bars} sessions since {forecast.inputs?.first_session} · checked on unseen data</span>
          <h2 className="v6-card-title">
            NIFTY Forecast for {forecast.for_session} <small style={{ fontWeight: 500, color: "var(--muted)" }}>(as of close {forecast.as_of_session}: ₹{Number(forecast.last_close).toLocaleString("en-IN")})</small>
          </h2>
        </div>
        <div className="v6-header-tags">
          {stale ? <span className="v6-pill rose" data-testid="realistic-stale-pill">STALE: FOR {forecast.for_session}</span> : null}
          <span className="v6-pill indigo">RANGE: RELIABLE</span>
          <span className={`v6-pill ${edge ? "emerald" : "amber"}`} data-testid="realistic-direction-pill">
            DIRECTION: {edge ? "EDGE SUPPORTED" : "NO RELIABLE EDGE"}
          </span>
        </div>
      </div>

      {stale ? (
        <p className="v6-section-desc rose-text" data-testid="realistic-stale-note">
          This forecast was for {forecast.for_session}, which has passed. After today's close, run Fetch history and then
          Run research (Backtest → Multi-Year Research) to publish the next one.
        </p>
      ) : null}
      {rng.status === "OK" ? (
        <div className="v6-metrics-grid" style={stale ? { opacity: 0.5 } : undefined}>
          <div className="v6-metric-card">
            <span className="v6-metric-label">Expected high–low range</span>
            <div className="v6-metric-val cyan-text">{pct(rng.expected_range_pct)}</div>
            <span className="v6-metric-sub">{pts(rng.expected_range_points)} · 90% band {pct(rng.range_band90_pct?.[0])}–{pct(rng.range_band90_pct?.[1])}</span>
          </div>
          <div className="v6-metric-card">
            <span className="v6-metric-label">Typical close-to-close move</span>
            <div className="v6-metric-val">{pct(rng.typical_close_move_pct)}</div>
            <span className="v6-metric-sub">{pts(rng.typical_close_move_points)} · 9 in 10 sessions within {pct(rng.close_move_p90_pct)} ({pts(rng.close_move_p90_points)})</span>
          </div>
          <div className="v6-metric-card">
            <span className="v6-metric-label">Direction (next session)</span>
            <div className={`v6-metric-val ${edge ? "emerald-text" : ""}`}>P(up) {ratio(d.probability_up)}</div>
            <span className="v6-metric-sub">
              {edge ? "From the selected model" : "Historical up-day rate (no model beat chance)"} · best of {d.trials} trials: holdout accuracy {ratio(d.holdout_accuracy)} (p = {num(d.holdout_accuracy_p)})
            </span>
          </div>
          {!compact ? (
            <div className="v6-metric-card">
              <span className="v6-metric-label">Track record of the range (holdout)</span>
              <div className="v6-metric-val">{ratio(rng.holdout_band_coverage?.band90, 0)}</div>
              <span className="v6-metric-sub">
                of unseen sessions fell inside the 90% band · {num(rng.holdout_qlike_improvement_vs_naive_pct, 1)}% better than “same as yesterday” (DM p = {num(rng.dm_vs_naive_holdout?.p_value)})
              </span>
            </div>
          ) : null}
        </div>
      ) : (
        <p className="v6-section-desc">Range forecast unavailable: {rng.status}</p>
      )}

      {!compact ? (
        <>
          <p className="v6-section-desc" style={{ marginTop: "10px" }}>
            <strong>Next half-day:</strong> {h.status === "EDGE_SUPPORTED" ? `P(up) ${ratio(h.probability_up)} from the selected model` : `no reliable edge (best holdout accuracy ${ratio(h.holdout_accuracy)}, p = ${num(h.holdout_accuracy_p)})`}.
            {" "}Model output shown only when it beat chance after costs on data it never saw{d.model_output_unreliable != null ? ` (raw model output today: ${ratio(d.model_output_unreliable)}, not reliable)` : ""}.
          </p>
          <ul className="v6-bullet-list" style={{ fontSize: "0.8rem", color: "var(--muted)" }}>
            {(forecast.caveats || []).map((c) => <li key={c}>{c}</li>)}
            <li>{forecast.for_session_note}</li>
            <li>Generated {forecast.generated_at ? forecast.generated_at.slice(0, 16).replace("T", " ") : "—"}. Refresh after each close: Backtest → Multi-Year Research → Fetch history, then Run research.</li>
          </ul>
        </>
      ) : (
        <p className="v6-section-desc" style={{ marginTop: "8px", fontSize: "0.78rem" }}>
          Statistical expectations, not trade signals. <Link href="/forecast">Details →</Link>
        </p>
      )}
    </div>
  );
}
