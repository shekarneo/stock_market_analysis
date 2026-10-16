"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { csrf } from "../components/ResearchBoard";
import { useMarketData } from "../components/MarketDataContext";

const STATUS_STYLE = {
  OPEN: { bg: "#eef3fb", fg: "#1a4d8f", label: "Open" },
  TARGET_HIT: { bg: "#e6f4ea", fg: "#137333", label: "Target hit" },
  SL_HIT: { bg: "#fce8e6", fg: "#c5221f", label: "SL hit" },
  EXPIRED: { bg: "#f1f1f1", fg: "#5f6368", label: "Expired" },
  AMBIGUOUS: { bg: "#fef7e0", fg: "#8a6d00", label: "Ambiguous" },
  CANCELLED: { bg: "#f1f1f1", fg: "#5f6368", label: "Cancelled" },
};

function inr(v) {
  return v == null ? "—" : `₹${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

function ist(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

function pct(v) {
  return v == null ? "—" : `${(v * 100).toFixed(1)}%`;
}

function calcRunningPremium(item, spots) {
  const p = item.model_premiums || {};
  const pEntry = p.entry != null ? Number(p.entry) : null;
  if (pEntry == null) return null;
  const pTarget = p.target != null ? Number(p.target) : Number((pEntry * 1.4).toFixed(2));
  const pSL = p.stop_loss != null ? Number(p.stop_loss) : Number((pEntry * 0.75).toFixed(2));
  if (item.status === "TARGET_HIT") return pTarget;
  if (item.status === "SL_HIT") return pSL;

  const entrySpot = Number(item.entry_spot);
  const currentSpot = item.status === "OPEN"
    ? ((spots && spots[item.instrument] != null) ? Number(spots[item.instrument]) : (item.last_spot != null ? Number(item.last_spot) : entrySpot))
    : (item.resolved_spot != null ? Number(item.resolved_spot) : (item.last_spot != null ? Number(item.last_spot) : entrySpot));

  if (isNaN(entrySpot) || isNaN(currentSpot)) return pEntry;
  const isUp = item.direction === "UP" || item.option_type === "CE";
  const spotDelta = isUp ? (currentSpot - entrySpot) : (entrySpot - currentSpot);
  const isFut = Boolean(item.contract && item.contract.includes("FUT"));
  const delta = isFut ? 1.0 : (p.delta != null ? Number(p.delta) : 0.5);
  const premDelta = spotDelta * delta;
  return Number(Math.max(0.05, pEntry + premDelta).toFixed(2));
}

export default function WatchlistPage() {
  const { retrievedAt, refreshNow, isRefreshing, spots } = useMarketData();
  const [data, setData] = useState(null);
  const [phase, setPhase] = useState("loading");
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("ALL");
  const [auto, setAuto] = useState(false);
  const [busy, setBusy] = useState(false);
  const timer = useRef(null);
  const prevRetrievedAt = useRef(null);

  const load = useCallback(async () => {
    try {
      const response = await fetch("/api/watchlist");
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.message || `Request failed (${response.status})`);
      setData(body);
      setPhase("ready");
    } catch (err) {
      setError(String(err.message || err));
      setPhase("error");
    }
  }, []);

  // Whenever global market data refreshes, evaluate open positions against the latest spots
  useEffect(() => {
    if (retrievedAt && retrievedAt !== prevRetrievedAt.current) {
      prevRetrievedAt.current = retrievedAt;
      fetch("/api/watchlist/evaluate", { method: "POST", headers: { "x-csrf-token": csrf() } })
        .then((res) => res.json())
        .then((body) => {
          if (body && body.items) setData(body);
        })
        .catch(() => load());
    }
  }, [retrievedAt, load]);

  // Pull fresh Groww quotes, then evaluate open suggestions against them.
  const refreshAndEvaluate = useCallback(async () => {
    setBusy(true);
    try {
      await refreshNow();
      const response = await fetch("/api/watchlist/evaluate", { method: "POST", headers: { "x-csrf-token": csrf() } });
      const body = await response.json().catch(() => ({}));
      if (response.ok) setData(body);
    } finally {
      setBusy(false);
    }
  }, [refreshNow]);

  async function cancel(id) {
    await fetch(`/api/watchlist/${id}/cancel`, { method: "POST", headers: { "x-csrf-token": csrf() } });
    load();
  }

  async function clearAll() {
    if (!window.confirm("Clear all suggestions from the watchlist?")) return;
    await fetch("/api/watchlist/clear", { method: "POST", headers: { "x-csrf-token": csrf() } });
    load();
  }

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!auto) {
      clearInterval(timer.current);
      return undefined;
    }
    refreshAndEvaluate();
    timer.current = setInterval(refreshAndEvaluate, 60000);
    return () => clearInterval(timer.current);
  }, [auto, refreshAndEvaluate]);

  const items = data?.items || [];
  const shown = filter === "ALL" ? items : items.filter((i) => i.status === filter);
  const acc = data?.accuracy;
  const o = acc?.overall;

  return (
    <section className="page">
      <p className="eyebrow">Trading desk</p>
      <h1>Watchlist &amp; suggestion accuracy</h1>
      <p className="lede">
        Every saved suggestion is tracked against the underlying spot that Groww reports. It resolves as
        <strong> Target hit</strong> when spot reaches the target level, <strong>SL hit</strong> when it reaches the stop level,
        or <strong>Expired</strong> at session close. Option premiums are model estimates and are <em>not</em> scored.
      </p>

      <div style={{ display: "flex", gap: "10px", alignItems: "center", flexWrap: "wrap", margin: "12px 0" }}>
        <button type="button" className="primary" onClick={refreshAndEvaluate} disabled={busy}>
          {busy ? "Checking…" : "Refresh quotes & check outcomes"}
        </button>
        {items.length > 0 ? (
          <button
            type="button"
            onClick={clearAll}
            style={{ fontSize: "0.85rem", padding: "6px 12px", background: "#fef2f2", color: "#991b1b", border: "1px solid #fecdd3", borderRadius: "6px", cursor: "pointer", fontWeight: 600 }}
          >
            Clear Watchlist
          </button>
        ) : null}
        <label className="check" style={{ display: "flex", gap: "6px", alignItems: "center" }}>
          <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
          <span>Auto-check every 60s (keep this tab open)</span>
        </label>
      </div>

      {phase === "error" ? <p className="error" role="alert">{error}</p> : null}

      {o ? (
        <div data-testid="accuracy" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "10px", margin: "10px 0 6px" }}>
          <Stat label="Hit rate" value={pct(o.hit_rate)} sub={`${o.TARGET_HIT} of ${o.decided} decided`} strong />
          <Stat label="Target hit" value={o.TARGET_HIT} color="#137333" />
          <Stat label="SL hit" value={o.SL_HIT} color="#c5221f" />
          <Stat label="Open" value={o.OPEN} />
          <Stat label="Expired (not scored)" value={o.EXPIRED} />
          <Stat label="CE / up hit rate" value={pct(acc.by_direction.UP.hit_rate)} sub={`${acc.by_direction.UP.decided} decided`} />
          <Stat label="PE / down hit rate" value={pct(acc.by_direction.DOWN.hit_rate)} sub={`${acc.by_direction.DOWN.decided} decided`} />
        </div>
      ) : null}
      {acc?.sample_warning ? (
        <p style={{ fontSize: "0.8rem", color: "#8a6d00", margin: "4px 0 12px" }}>
          ⚠️ Fewer than 30 decided suggestions. The hit rate is not statistically meaningful yet.
        </p>
      ) : null}

      {acc && Object.keys(acc.by_instrument).length ? (
        <details style={{ margin: "6px 0 14px" }}>
          <summary style={{ cursor: "pointer", fontWeight: 600 }}>Accuracy by instrument</summary>
          <table style={{ marginTop: "8px" }}>
            <thead>
              <tr><th>Instrument</th><th>Hit rate</th><th>Target</th><th>SL</th><th>Open</th><th>Expired</th></tr>
            </thead>
            <tbody>
              {Object.entries(acc.by_instrument).map(([inst, t]) => (
                <tr key={inst}>
                  <td><strong>{inst}</strong></td><td>{pct(t.hit_rate)}</td><td>{t.TARGET_HIT}</td><td>{t.SL_HIT}</td><td>{t.OPEN}</td><td>{t.EXPIRED}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      ) : null}

      <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", margin: "8px 0" }}>
        {["ALL", "OPEN", "TARGET_HIT", "SL_HIT", "EXPIRED", "CANCELLED"].map((f) => (
          <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)} style={{ fontSize: "0.8rem", padding: "4px 10px" }}>
            {f === "ALL" ? `All (${items.length})` : `${STATUS_STYLE[f].label} (${items.filter((i) => i.status === f).length})`}
          </button>
        ))}
      </div>

      {phase === "ready" && items.length === 0 ? (
        <p>No suggestions saved yet. Run an analysis and press <strong>+ Watch</strong> on a strike.</p>
      ) : null}

      {shown.length ? (
        <div className="table-wrap" style={{ overflowX: "auto" }}>
          <table data-testid="watchlist-table" style={{ width: "100%", borderCollapse: "collapse", textAlign: "left" }}>
            <thead>
              <tr style={{ borderBottom: "2px solid var(--line, #e2e8f0)" }}>
                <th>Contract</th>
                <th>Status</th>
                <th style={{ background: "rgba(240, 253, 244, 0.5)", color: "#166534" }}>Prem. Entry</th>
                <th style={{ background: "rgba(224, 231, 255, 0.7)", color: "#3730a3" }}>Running Prem.</th>
                <th style={{ background: "rgba(240, 253, 244, 0.5)", color: "#166534" }}>Prem. Target</th>
                <th style={{ background: "rgba(254, 242, 242, 0.5)", color: "#991b1b" }}>Prem. SL</th>
                <th>Spot Entry</th>
                <th>Spot Target</th>
                <th>Spot SL</th>
                <th>Last Spot</th>
                <th>Best / Worst</th>
                <th>Saved</th>
                <th>Resolves</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {shown.map((i) => {
                const s = STATUS_STYLE[i.status] || STATUS_STYLE.OPEN;
                const p = i.model_premiums || {};
                const pEntry = p.entry != null ? Number(p.entry) : null;
                const pTarget = p.target != null ? Number(p.target) : (pEntry != null ? Number((pEntry * 1.4).toFixed(2)) : null);
                const pSL = p.stop_loss != null ? Number(p.stop_loss) : (pEntry != null ? Number((pEntry * 0.75).toFixed(2)) : null);
                const gainPct = pEntry && pTarget ? `+${(((pTarget - pEntry) / pEntry) * 100).toFixed(0)}%` : "";
                const lossPct = pEntry && pSL ? `-${(((pEntry - pSL) / pEntry) * 100).toFixed(0)}%` : "";

                const runningPrem = calcRunningPremium(i, spots);
                const runDiffPct = (pEntry && runningPrem != null) ? (((runningPrem - pEntry) / pEntry) * 100) : null;
                const isRunPos = runDiffPct != null && runDiffPct >= 0;

                return (
                  <tr key={i.suggestion_id} style={{ borderBottom: "1px solid var(--line, #f1f5f9)" }}>
                    <td>
                      <strong style={{ color: i.option_type === "CE" ? "#137333" : "#c5221f" }}>{i.contract}</strong>
                      <small style={{ display: "block", color: "var(--muted)" }}>{i.direction === "UP" ? "▲ needs spot up" : "▼ needs spot down"} · {i.data_class || "—"}</small>
                    </td>
                    <td>
                      <span style={{ background: s.bg, color: s.fg, padding: "2px 8px", borderRadius: "10px", fontSize: "0.75rem", fontWeight: 600, whiteSpace: "nowrap" }}>
                        {s.label}
                      </span>
                    </td>
                    {/* Option Premium Entry */}
                    <td style={{ background: "rgba(240, 253, 244, 0.25)" }}>
                      <strong>{inr(pEntry)}</strong>
                      {p.lot_size ? <small style={{ display: "block", color: "var(--muted)" }}>Lot {p.lot_size}</small> : null}
                    </td>
                    {/* Option Premium Running */}
                    <td style={{ background: "rgba(224, 231, 255, 0.25)" }}>
                      <strong style={{ color: runDiffPct == null ? "inherit" : isRunPos ? "#15803d" : "#b91c1c" }}>
                        {inr(runningPrem)}
                      </strong>
                      {runDiffPct != null && (
                        <small style={{
                          display: "block",
                          color: isRunPos ? "#166534" : "#991b1b",
                          fontWeight: 600,
                        }}>
                          {isRunPos ? "+" : ""}{runDiffPct.toFixed(1)}%
                        </small>
                      )}
                    </td>
                    {/* Option Premium Target */}
                    <td style={{ background: "rgba(240, 253, 244, 0.25)" }}>
                      <strong style={{ color: "#15803d" }}>{inr(pTarget)}</strong>
                      {gainPct ? <small style={{ display: "block", color: "#166534", fontWeight: 600 }}>{gainPct}</small> : null}
                    </td>
                    {/* Option Premium Stop-Loss */}
                    <td style={{ background: "rgba(254, 242, 242, 0.25)" }}>
                      <strong style={{ color: "#b91c1c" }}>{inr(pSL)}</strong>
                      {lossPct ? <small style={{ display: "block", color: "#991b1b", fontWeight: 600 }}>{lossPct}</small> : null}
                    </td>
                    {/* Underlying Spot Levels */}
                    <td>{inr(i.entry_spot)}</td>
                    <td style={{ color: "#137333", fontWeight: 600 }}>{inr(i.target_spot)}</td>
                    <td style={{ color: "#c5221f", fontWeight: 600 }}>{inr(i.stop_loss_spot)}</td>
                    <td>
                      {inr(i.last_spot)}
                      <small style={{ display: "block", color: "var(--muted)" }}>{i.checks} checks · {ist(i.last_checked_at)}</small>
                    </td>
                    <td><small>{inr(i.max_favorable_spot)} / {inr(i.max_adverse_spot)}</small></td>
                    <td><small>{ist(i.created_at)}</small></td>
                    <td>
                      <small style={{ fontWeight: i.status !== "OPEN" ? 600 : 400 }}>
                        {i.status === "OPEN" ? `by ${ist(i.expires_at)}` : `${ist(i.resolved_at)} @ ${inr(i.resolved_spot)}`}
                      </small>
                    </td>
                    <td>
                      {i.status === "OPEN" ? (
                        <button type="button" style={{ fontSize: "0.72rem", padding: "3px 8px" }} onClick={() => cancel(i.suggestion_id)}>
                          Cancel
                        </button>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}

      <p style={{ fontSize: "0.78rem", color: "var(--muted)", marginTop: "14px" }}>
        * <strong>Option Premiums:</strong> Dedicated columns display the Option Entry Premium, Target Premium (+40%), and Stop-Loss Premium (-25%). Trade resolution &amp; accuracy hit-rates are verified against the underlying index/commodity spot levels reaching Target or SL. {acc?.method}
      </p>
    </section>
  );
}

function Stat({ label, value, sub, color, strong }) {
  return (
    <div style={{ background: "var(--card, #fff)", border: "1px solid var(--line, #e4ddd0)", borderRadius: "10px", padding: "10px 12px" }}>
      <div style={{ fontSize: "0.72rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</div>
      <div style={{ fontSize: strong ? "1.5rem" : "1.2rem", fontWeight: 700, color: color || "inherit" }}>{value}</div>
      {sub ? <div style={{ fontSize: "0.72rem", color: "var(--muted)" }}>{sub}</div> : null}
    </div>
  );
}
