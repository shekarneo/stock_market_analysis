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

function formatExpiry(d) {
  if (!d) return null;
  try {
    const dt = new Date(d);
    if (isNaN(dt.getTime())) return d;
    return dt.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
  } catch {
    return d;
  }
}

function pct(v) {
  return v == null ? "—" : `${(v * 100).toFixed(1)}%`;
}

function calcRunningPremium(item, spots) {
  // 1. Prioritize genuine live option quote directly from Groww Option Chain
  if (item.live_option_premium != null && Number(item.live_option_premium) > 0) {
    return Number(item.live_option_premium);
  }
  const p = item.model_premiums || {};
  if (p.running_premium != null && Number(p.running_premium) > 0) {
    return Number(p.running_premium);
  }

  // 2. Fallback to model delta calculation if option chain LTP is unavailable
  const pEntry = p.entry != null ? Number(p.entry) : null;
  if (pEntry == null) return null;

  const entrySpot = Number(item.entry_spot);
  const currentSpot = (spots && spots[item.instrument] != null)
    ? Number(spots[item.instrument])
    : (item.last_spot != null
        ? Number(item.last_spot)
        : (item.resolved_spot != null ? Number(item.resolved_spot) : entrySpot));

  if (isNaN(entrySpot) || isNaN(currentSpot)) return pEntry;
  const isUp = item.direction === "UP" || item.option_type === "CE";
  const spotDelta = isUp ? (currentSpot - entrySpot) : (entrySpot - currentSpot);
  const isFut = Boolean(item.contract && item.contract.includes("FUT"));
  const delta = isFut ? 1.0 : (p.delta != null ? Number(p.delta) : null);
  if (delta == null) return null; // no live delta captured: do not estimate a running premium
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
  const [showAddForm, setShowAddForm] = useState(false);
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
        <button
          type="button"
          onClick={() => setShowAddForm(!showAddForm)}
          style={{
            fontSize: "0.85rem",
            padding: "6px 14px",
            background: showAddForm ? "rgba(56, 189, 248, 0.2)" : "var(--card-subtle, #131c31)",
            color: "#38bdf8",
            border: "1px solid rgba(56, 189, 248, 0.4)",
            borderRadius: "6px",
            cursor: "pointer",
            fontWeight: 600,
          }}
        >
          {showAddForm ? "✕ Cancel Add" : "+ Add Contract / Suggestion"}
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

      {showAddForm && (
        <AddSuggestionCard
          spots={spots}
          onSuccess={() => {
            setShowAddForm(false);
            load();
          }}
        />
      )}

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
                const pTarget = p.target != null ? Number(p.target) : null;
                const pSL = p.stop_loss != null ? Number(p.stop_loss) : null;
                const gainPct = pEntry && pTarget ? `+${(((pTarget - pEntry) / pEntry) * 100).toFixed(0)}%` : "";
                const lossPct = pEntry && pSL ? `-${(((pEntry - pSL) / pEntry) * 100).toFixed(0)}%` : "";

                const runningPrem = calcRunningPremium(i, spots);
                const runDiffPct = (pEntry && runningPrem != null) ? (((runningPrem - pEntry) / pEntry) * 100) : null;
                const isRunPos = runDiffPct != null && runDiffPct >= 0;

                return (
                  <tr key={i.suggestion_id} style={{ borderBottom: "1px solid var(--line, #f1f5f9)" }}>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
                        <a
                          href={`/dashboard?instrument=${encodeURIComponent(i.instrument)}`}
                          style={{ textDecoration: "none", color: i.option_type === "CE" ? "#137333" : "#c5221f" }}
                          title="View instrument details on Trade Desk"
                        >
                          <strong>{i.contract}</strong> ↗
                        </a>
                        {(i.contract_expiry || i.model_premiums?.expiry_date) && (
                          <span style={{
                            display: "inline-block",
                            background: "rgba(2, 132, 199, 0.12)",
                            color: "#0284c7",
                            padding: "1px 6px",
                            borderRadius: "4px",
                            fontSize: "0.7rem",
                            fontWeight: 700,
                          }}>
                            Exp: {formatExpiry(i.contract_expiry || i.model_premiums?.expiry_date)}
                          </span>
                        )}
                      </div>
                      {i.trading_symbol && (
                        <small style={{ display: "block", color: "#0284c7", fontWeight: 600, fontSize: "0.72rem" }}>
                          {i.trading_symbol}
                        </small>
                      )}
                      <small style={{ display: "block", color: "var(--muted)" }}>
                        {i.direction === "UP" ? "▲ needs spot up" : "▼ needs spot down"} · {i.data_class || "—"} · <a href={`/analysis?instrument=${encodeURIComponent(i.instrument)}`} style={{ color: "#38bdf8", textDecoration: "none" }}>Analysis</a>
                      </small>
                    </td>
                    <td>
                      <span style={{ background: s.bg, color: s.fg, padding: "2px 8px", borderRadius: "10px", fontSize: "0.75rem", fontWeight: 600, whiteSpace: "nowrap" }}>
                        {s.label}
                      </span>
                    </td>
                    {/* Option Premium Entry */}
                    <td style={{ background: "rgba(240, 253, 244, 0.25)" }}>
                      <strong>{inr(pEntry)}</strong>
                      {(p.is_live_quote || p.data_source === "GROWW_OPTION_CHAIN" || i.is_live_contract) && (
                        <small style={{ display: "block", color: "#16a34a", fontSize: "0.68rem", fontWeight: 600 }}>
                          Groww Entry LTP
                        </small>
                      )}
                      {p.lot_size ? <small style={{ display: "block", color: "var(--muted)" }}>Lot {p.lot_size}</small> : null}
                    </td>
                    {/* Option Premium Running / Exit */}
                    <td style={{ background: "rgba(224, 231, 255, 0.25)" }}>
                      {i.status === "OPEN" ? (
                        <>
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
                          <small style={{
                            display: "inline-block",
                            fontSize: "0.65rem",
                            padding: "1px 5px",
                            borderRadius: "3px",
                            background: i.live_option_premium ? "rgba(34, 197, 94, 0.15)" : "rgba(148, 163, 184, 0.15)",
                            color: i.live_option_premium ? "#16a34a" : "var(--muted)",
                            fontWeight: 600,
                            marginTop: "2px",
                          }}>
                            {i.live_option_premium ? "Groww Live LTP" : "Model Est."}
                          </small>
                        </>
                      ) : i.status === "SL_HIT" ? (
                        <>
                          <strong style={{ color: "#b91c1c" }}>{inr(p.exit_premium || pSL)}</strong>
                          <small style={{ display: "block", color: "#991b1b", fontWeight: 700 }}>
                            {p.exit_premium ? "Realized Exit" : (lossPct || "Spot stop hit")}
                          </small>
                          {runningPrem != null && (
                            <small style={{ display: "block", color: "var(--muted)", fontSize: "0.68rem", marginTop: "2px" }} title="Current market option premium if held post-exit">
                              Post-Exit: {inr(runningPrem)} ({isRunPos ? "+" : ""}{runDiffPct?.toFixed(1)}%)
                            </small>
                          )}
                        </>
                      ) : i.status === "TARGET_HIT" ? (
                        <>
                          <strong style={{ color: "#15803d" }}>{inr(p.exit_premium || pTarget)}</strong>
                          <small style={{ display: "block", color: "#166534", fontWeight: 700 }}>
                            {p.exit_premium ? "Realized Exit" : (gainPct || "Spot target hit")}
                          </small>
                          {runningPrem != null && (
                            <small style={{ display: "block", color: "var(--muted)", fontSize: "0.68rem", marginTop: "2px" }} title="Current market option premium if held post-exit">
                              Post-Exit: {inr(runningPrem)} ({isRunPos ? "+" : ""}{runDiffPct?.toFixed(1)}%)
                            </small>
                          )}
                        </>
                      ) : (
                        <span style={{ color: "var(--muted)" }}>—</span>
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
                      {i.status === "OPEN" ? (
                        <>
                          <strong>{inr(spots?.[i.instrument] ?? i.last_spot)}</strong>
                          <small style={{ display: "block", color: "var(--muted)" }}>{i.checks} checks · {ist(i.last_checked_at)}</small>
                        </>
                      ) : (
                        <>
                          <strong style={{ color: i.status === "TARGET_HIT" ? "#137333" : "#c5221f" }}>
                            {inr(i.resolved_spot ?? i.last_spot)}
                          </strong>
                          <small style={{ display: "block", color: i.status === "TARGET_HIT" ? "#15803d" : "#991b1b", fontWeight: 600 }}>
                            {i.status === "TARGET_HIT" ? "Target Triggered" : "SL Triggered"}
                          </small>
                          {spots?.[i.instrument] != null && (
                            <small style={{ display: "block", color: "var(--muted)", fontSize: "0.68rem" }}>
                              Live: {inr(spots[i.instrument])}
                            </small>
                          )}
                        </>
                      )}
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
        * <strong>Option Premiums:</strong> Dedicated columns display the option Entry, Target and Stop-Loss premiums when they came from a fresh live option-chain quote (blank otherwise). Trade resolution &amp; accuracy hit-rates are verified against the underlying index/commodity spot levels reaching Target or SL. {acc?.method}
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

function AddSuggestionCard({ spots, onSuccess }) {
  const [instrument, setInstrument] = useState("NIFTY");
  const [optionType, setOptionType] = useState("CE");
  const initialSpot = spots["NIFTY"] ?? null;
  const [contract, setContract] = useState(initialSpot != null ? `NIFTY ${Math.round(initialSpot / 50) * 50} CE` : "");
  const [entrySpot, setEntrySpot] = useState(initialSpot ?? "");
  const [targetPoints, setTargetPoints] = useState(50);
  const [stopLossPoints, setStopLossPoints] = useState(25);
  const [entryPremium, setEntryPremium] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState("");

  const handleInstrumentChange = (inst) => {
    setInstrument(inst);
    // Live spot only; if it is missing the operator must enter it (no placeholder prices).
    const sp = spots[inst] ?? null;
    setEntrySpot(sp ?? "");
    const strikeFor = (step) => (sp != null ? `${Math.round(sp / step) * step} ` : "");
    if (inst === "NIFTY") {
      setContract(`NIFTY ${strikeFor(50)}${optionType}`);
      setTargetPoints(50);
      setStopLossPoints(25);
    } else if (inst === "SENSEX") {
      setContract(`SENSEX ${strikeFor(100)}${optionType}`);
      setTargetPoints(150);
      setStopLossPoints(75);
    } else {
      setContract(`CRUDEMINI ${strikeFor(50)}${optionType}`);
      setTargetPoints(40);
      setStopLossPoints(20);
    }
  };

  const handleOptionTypeChange = (ot) => {
    setOptionType(ot);
    const sp = entrySpot === "" ? null : Number(entrySpot);
    const base = instrument === "NIFTY" ? 50 : (instrument === "SENSEX" ? 100 : 50);
    setContract(sp != null && !isNaN(sp) ? `${instrument} ${Math.round(sp / base) * base} ${ot}` : `${instrument} ${ot}`);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setFormError("");
    try {
      const res = await fetch("/api/watchlist", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-csrf-token": csrf(),
        },
        body: JSON.stringify({
          instrument,
          contract: contract.trim(),
          option_type: optionType,
          call: "BUY",
          entry_spot: Number(entrySpot),
          target_points: Number(targetPoints),
          stop_loss_points: Number(stopLossPoints),
          model_premiums: entryPremium === "" ? {} : { entry: Number(entryPremium) },
          data_class: "UNVERIFIED_PROVIDER_DATA",
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.message || data.detail || `Error (${res.status})`);
      onSuccess();
    } catch (err) {
      setFormError(err.message || String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{
      background: "var(--card-subtle, #131c31)",
      border: "1px solid rgba(56, 189, 248, 0.4)",
      borderRadius: "10px",
      padding: "16px",
      marginBottom: "20px",
    }}>
      <h3 style={{ margin: "0 0 12px", fontSize: "1rem", color: "#38bdf8" }}>
        + Add Instrument Contract to Watchlist
      </h3>
      {formError && <p className="error" style={{ marginBottom: "10px" }}>{formError}</p>}
      <form onSubmit={handleSubmit} style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: "10px", alignItems: "flex-end" }}>
        <label style={{ fontSize: "0.8rem", color: "var(--muted)", display: "flex", flexDirection: "column", gap: "4px" }}>
          Instrument
          <select
            value={instrument}
            onChange={(e) => handleInstrumentChange(e.target.value)}
            style={{ padding: "6px 8px", borderRadius: "6px", border: "1px solid var(--line)" }}
          >
            <option value="NIFTY">NIFTY 50</option>
            <option value="SENSEX">SENSEX</option>
            <option value="CRUDEMINI">CRUDEOIL MINI</option>
          </select>
        </label>

        <label style={{ fontSize: "0.8rem", color: "var(--muted)", display: "flex", flexDirection: "column", gap: "4px" }}>
          Option Type
          <select
            value={optionType}
            onChange={(e) => handleOptionTypeChange(e.target.value)}
            style={{ padding: "6px 8px", borderRadius: "6px", border: "1px solid var(--line)" }}
          >
            <option value="CE">Call (CE - Up)</option>
            <option value="PE">Put (PE - Down)</option>
          </select>
        </label>

        <label style={{ fontSize: "0.8rem", color: "var(--muted)", display: "flex", flexDirection: "column", gap: "4px" }}>
          Contract Symbol
          <input
            value={contract}
            onChange={(e) => setContract(e.target.value)}
            required
            style={{ padding: "6px 8px", borderRadius: "6px", border: "1px solid var(--line)" }}
          />
        </label>

        <label style={{ fontSize: "0.8rem", color: "var(--muted)", display: "flex", flexDirection: "column", gap: "4px" }}>
          Entry Spot (₹)
          <input
            type="number"
            step="any"
            value={entrySpot}
            onChange={(e) => setEntrySpot(e.target.value)}
            required
            style={{ padding: "6px 8px", borderRadius: "6px", border: "1px solid var(--line)" }}
          />
        </label>

        <label style={{ fontSize: "0.8rem", color: "var(--muted)", display: "flex", flexDirection: "column", gap: "4px" }}>
          Target Points (pts)
          <input
            type="number"
            step="any"
            value={targetPoints}
            onChange={(e) => setTargetPoints(e.target.value)}
            required
            style={{ padding: "6px 8px", borderRadius: "6px", border: "1px solid var(--line)" }}
          />
        </label>

        <label style={{ fontSize: "0.8rem", color: "var(--muted)", display: "flex", flexDirection: "column", gap: "4px" }}>
          Stop Loss (pts)
          <input
            type="number"
            step="any"
            value={stopLossPoints}
            onChange={(e) => setStopLossPoints(e.target.value)}
            required
            style={{ padding: "6px 8px", borderRadius: "6px", border: "1px solid var(--line)" }}
          />
        </label>

        <label style={{ fontSize: "0.8rem", color: "var(--muted)", display: "flex", flexDirection: "column", gap: "4px" }}>
          Entry Prem. (₹, optional)
          <input
            type="number"
            step="any"
            value={entryPremium}
            onChange={(e) => setEntryPremium(e.target.value)}
            style={{ padding: "6px 8px", borderRadius: "6px", border: "1px solid var(--line)" }}
          />
        </label>

        <div>
          <button
            type="submit"
            disabled={submitting}
            className="primary"
            style={{ padding: "7px 16px", borderRadius: "6px", width: "100%", fontWeight: 600 }}
          >
            {submitting ? "Adding…" : "Save to Watchlist"}
          </button>
        </div>
      </form>
    </div>
  );
}

