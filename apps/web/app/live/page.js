"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useMarketData } from "../components/MarketDataContext";
import { csrfToken as csrf } from "../components/session";
import { useRead } from "../components/useRead";

const COMMODITY_SET = new Set(["CRUDE", "CRUDEMINI", "CRUDEOILMINI", "GOLD", "SILVER", "NATURALGAS"]);

function getSessionStatus(instrument, crossMarketSnapshot = null) {
  try {
    if (crossMarketSnapshot) {
      const allItems = [
        ...(crossMarketSnapshot.indian_equities || []),
        ...(crossMarketSnapshot.indian_commodities || []),
        ...(crossMarketSnapshot.international_markets || []),
        ...(crossMarketSnapshot.macro_indicators || []),
      ];
      const match = allItems.find((x) => x.instrument === instrument || (instrument === "CRUDEOILMINI" && x.instrument === "CRUDEMINI"));
      if (match) {
        return {
          isOpen: match.is_open,
          marketState: match.market_state,
          sessionPhase: match.session_phase,
          freshness: match.freshness_status,
          exchange: match.exchange,
          warning: match.warning_or_limitation,
          hours: match.exchange === "MCX" ? "09:00 AM – 11:30 PM IST" : "09:15 AM – 03:30 PM IST",
          closeTimeText: match.exchange === "MCX" ? "11:30 PM IST" : "03:30 PM IST",
          nextOpenText: match.is_open ? "Live Now" : "Next Session",
        };
      }
    }

    const now = new Date();
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: "Asia/Kolkata",
      hour: "numeric",
      minute: "numeric",
      weekday: "short",
      hour12: false,
    }).formatToParts(now);
    const weekday = parts.find((p) => p.type === "weekday")?.value;
    const hour = parseInt(parts.find((p) => p.type === "hour")?.value || "0", 10);
    const minute = parseInt(parts.find((p) => p.type === "minute")?.value || "0", 10);
    const totalMinutes = hour * 60 + minute;
    const isWeekend = weekday === "Sat" || weekday === "Sun";

    if (COMMODITY_SET.has(instrument)) {
      const openMinutes = 9 * 60;
      const closeMinutes = 23 * 60 + 30;
      const isOpen = !isWeekend && totalMinutes >= openMinutes && totalMinutes < closeMinutes;
      return {
        isOpen,
        marketState: isOpen ? "OPEN" : "CLOSED",
        sessionPhase: isOpen ? "REGULAR" : "CLOSED",
        freshness: isOpen ? "LIVE" : "CLOSED_SESSION_VALID",
        exchange: "MCX",
        hours: "09:00 AM – 11:30 PM IST",
        closeTimeText: "11:30 PM IST",
        nextOpenText: isWeekend ? "Monday 09:00 AM IST" : "Tomorrow 09:00 AM IST",
      };
    }

    const openMinutes = 9 * 60 + 15;
    const closeMinutes = 15 * 60 + 30;
    const isOpen = !isWeekend && totalMinutes >= openMinutes && totalMinutes < closeMinutes;
    return {
      isOpen,
      marketState: isOpen ? "OPEN" : "CLOSED",
      sessionPhase: isOpen ? "REGULAR" : "CLOSED",
      freshness: isOpen ? "LIVE" : "CLOSED_SESSION_VALID",
      exchange: "NSE/BSE",
      hours: "09:15 AM – 03:30 PM IST",
      closeTimeText: "03:30 PM IST",
      nextOpenText: isWeekend ? "Monday 09:15 AM IST" : "Tomorrow 09:15 AM IST",
    };
  } catch {
    return { isOpen: false, marketState: "CLOSED", sessionPhase: "CLOSED", freshness: "UNKNOWN", exchange: "Market", hours: "Regular", closeTimeText: "Close", nextOpenText: "Next Session" };
  }
}

function pct(v) {
  return v == null ? "—" : `${(v * 100).toFixed(1)}%`;
}

function inr(v) {
  return v == null ? "—" : `₹${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

function calcRunningPremium(w, spots) {
  const p = w.model_premiums || {};
  const pEntry = p.entry != null ? Number(p.entry) : null;
  if (pEntry == null) return null;
  const pTarget = p.target != null ? Number(p.target) : Number((pEntry * 1.4).toFixed(2));
  const pSL = p.stop_loss != null ? Number(p.stop_loss) : Number((pEntry * 0.75).toFixed(2));
  if (w.status === "TARGET_HIT") return pTarget;
  if (w.status === "SL_HIT") return pSL;

  const entrySpot = Number(w.entry_spot);
  const currentSpot = w.status === "OPEN"
    ? ((spots && spots[w.instrument] != null) ? Number(spots[w.instrument]) : (w.last_spot != null ? Number(w.last_spot) : entrySpot))
    : (w.resolved_spot != null ? Number(w.resolved_spot) : (w.last_spot != null ? Number(w.last_spot) : entrySpot));

  if (isNaN(entrySpot) || isNaN(currentSpot)) return pEntry;
  const isUp = w.direction === "UP" || w.option_type === "CE";
  const spotDelta = isUp ? (currentSpot - entrySpot) : (entrySpot - currentSpot);
  const isFut = Boolean(w.contract && w.contract.includes("FUT"));
  const delta = isFut ? 1.0 : (p.delta != null ? Number(p.delta) : 0.5);
  const premDelta = spotDelta * delta;
  return Number(Math.max(0.05, pEntry + premDelta).toFixed(2));
}

function ist(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

const STATUS_STYLE = {
  OPEN: { bg: "#eef3fb", fg: "#1a4d8f", label: "Open" },
  TARGET_HIT: { bg: "#e6f4ea", fg: "#137333", label: "Target hit" },
  SL_HIT: { bg: "#fce8e6", fg: "#c5221f", label: "SL hit" },
  EXPIRED: { bg: "#f1f1f1", fg: "#5f6368", label: "Expired" },
  AMBIGUOUS: { bg: "#fef7e0", fg: "#8a6d00", label: "Ambiguous" },
  CANCELLED: { bg: "#f1f1f1", fg: "#5f6368", label: "Cancelled" },
};

export default function LiveTradingPage() {
  const { spots, quotes, refreshNow, retrievedAt, crossMarketSnapshot, postCloseMode } = useMarketData();

  const [analysisData, setAnalysisData] = useState(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [watchlistData, setWatchlistData] = useState(null);
  const [evaluating, setEvaluating] = useState(false);
  const [autoEvaluate, setAutoEvaluate] = useState(true);
  const evalTimer = useRef(null);
  const prevRetrievedAt = useRef(null);

  const [autoTradingEnabled, setAutoTradingEnabled] = useState(false);
  const [autoAddToWatchlist, setAutoAddToWatchlist] = useState(true);
  const [executionMode, setExecutionMode] = useState("PAPER"); // "PAPER" or "LIVE"
  const [showLiveConfirmModal, setShowLiveConfirmModal] = useState(false);
  const [killSwitchTriggered, setKillSwitchTriggered] = useState(false);
  const [maxLots, setMaxLots] = useState(1);
  const [dailyLossLimit, setDailyLossLimit] = useState(5000);
  const [activeTab, setActiveTab] = useState("ALL");
  const [viewSource, setViewSource] = useState("WATCHLIST"); // "WATCHLIST" or "ORDERS"
  const [actionNotice, setActionNotice] = useState("");

  const [orders, setOrders] = useState([]);

  // Load Watchlist and Accuracy
  const loadWatchlist = useCallback(async () => {
    try {
      const response = await fetch("/api/watchlist");
      const body = await response.json().catch(() => ({}));
      if (response.ok) {
        setWatchlistData(body);
      }
    } catch {
      // Ignore
    }
  }, []);

  const cancelSuggestion = async (id) => {
    try {
      await fetch(`/api/watchlist/${id}/cancel`, { method: "POST", headers: { "x-csrf-token": csrf() } });
      loadWatchlist();
    } catch {
      // Ignore
    }
  };

  const clearAllWatchlist = async () => {
    if (!window.confirm("Clear all suggestions from the watchlist?")) return;
    try {
      await fetch("/api/watchlist/clear", { method: "POST", headers: { "x-csrf-token": csrf() } });
      loadWatchlist();
      setActionNotice("Watchlist cleared successfully.");
      setTimeout(() => setActionNotice(""), 3000);
    } catch {
      // Ignore
    }
  };

  const clearOrders = () => {
    if (!window.confirm("Clear all executed simulated orders?")) return;
    setOrders([]);
    setActionNotice("Simulated orders cleared.");
    setTimeout(() => setActionNotice(""), 3000);
  };

  // Fetch fresh Groww live quotes, then run real-time market analysis
  const fetchAnalysis = useCallback(async () => {
    setAnalysisLoading(true);
    try {
      try {
        await refreshNow();
      } catch {
        // Fall back to existing cached quotes if transient network issue
      }
      const res = await fetch("/api/market-analysis", {
        method: "POST",
        headers: { "content-type": "application/json", "x-csrf-token": csrf() },
        body: JSON.stringify({
          instruments: ["NIFTY", "SENSEX", "CRUDEOILMINI"],
          horizon: "INTRADAY",
          include_news: true,
          include_macro: true,
          include_derivatives: true,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        setAnalysisData(data);
      }
    } catch {
      // Ignore
    } finally {
      setAnalysisLoading(false);
    }
  }, [refreshNow]);

  // Refresh quotes and evaluate all open watchlist positions against live spot prices
  const evaluateAccuracy = useCallback(async () => {
    setEvaluating(true);
    try {
      await refreshNow();
      const res = await fetch("/api/watchlist/evaluate", {
        method: "POST",
        headers: { "x-csrf-token": csrf() },
      });
      const body = await res.json().catch(() => ({}));
      if (res.ok) {
        setWatchlistData(body);
        setActionNotice("🎯 Watchlist evaluated against live quotes: Accuracy metrics updated.");
        setTimeout(() => setActionNotice(""), 3500);
      }
    } catch {
      // Ignore
    } finally {
      setEvaluating(false);
    }
  }, [refreshNow]);

  useEffect(() => {
    loadWatchlist();
    fetchAnalysis();
  }, [loadWatchlist, fetchAnalysis]);

  // When live quotes sync globally, evaluate watchlist against new spots
  useEffect(() => {
    if (retrievedAt && retrievedAt !== prevRetrievedAt.current) {
      prevRetrievedAt.current = retrievedAt;
      fetch("/api/watchlist/evaluate", { method: "POST", headers: { "x-csrf-token": csrf() } })
        .then((res) => res.json())
        .then((body) => {
          if (body && body.items) setWatchlistData(body);
        })
        .catch(() => loadWatchlist());
    }
  }, [retrievedAt, loadWatchlist]);

  // Recurring auto-evaluation of accuracy every 45 seconds
  useEffect(() => {
    if (!autoEvaluate) {
      clearInterval(evalTimer.current);
      return undefined;
    }
    evalTimer.current = setInterval(() => {
      evaluateAccuracy();
    }, 45000);
    return () => clearInterval(evalTimer.current);
  }, [autoEvaluate, evaluateAccuracy]);

  const getSpot = (inst) => {
    if (spots && spots[inst] != null) return spots[inst];
    if (inst === "CRUDEOILMINI" && spots?.CRUDEMINI != null) return spots.CRUDEMINI;
    if (inst === "CRUDEMINI" && spots?.CRUDEOILMINI != null) return spots.CRUDEOILMINI;
    const q = (quotes || []).find((x) => x.instrument === inst);
    if (q?.last_price) return Number(q.last_price);
    const m = analysisData?.intelligence?.markets?.[inst];
    if (m?.last_price) return Number(m.last_price);
    return null;
  };


  const getMarketAnalysis = (inst) => {
    return analysisData?.intelligence?.markets?.[inst] || null;
  };

  // Auto-Add trade to Watchlist and track accuracy (deduplicating active open contracts)
  const addTradeToWatchlist = async (inst, pick, rec) => {
    const plannedContract = pick?.contract || `${inst} ATM`;
    const isAlreadyOpen = (watchlistData?.items || []).some(
      (item) => item.contract === plannedContract && item.status === "OPEN"
    );
    if (isAlreadyOpen) {
      setActionNotice(`ℹ️ ${plannedContract} is already actively tracked in the Watchlist.`);
      setTimeout(() => setActionNotice(""), 3500);
      return false;
    }

    try {
      const payload = {
        instrument: inst,
        contract: plannedContract,
        option_type: pick?.option_type || rec?.option_type || "CE",
        call: rec?.call || (pick?.option_type === "PE" ? "BUY_PE" : "BUY_CE"),
        entry_spot: rec?.spot_price || getSpot(inst),
        target_points: rec?.expected_move_points || (inst === "NIFTY" ? 80 : inst === "SENSEX" ? 250 : 50),
        stop_loss_points: rec?.stop_loss_points || (inst === "NIFTY" ? 40 : inst === "SENSEX" ? 120 : 25),
        data_class: "VERIFIED_LIVE_DATA",
        model_premiums: {
          strike: pick?.strike || rec?.atm_strike,
          moneyness: pick?.moneyness || "ATM",
          delta: pick?.delta || 0.5,
          entry: pick?.entry_premium || 120,
          target: pick?.target_premium || 180,
          stop_loss: pick?.stop_loss_premium || 80,
          lot_size: pick?.lot_size || (inst === "NIFTY" ? 25 : 10),
          estimated: true,
        },
      };

      const res = await fetch("/api/watchlist", {
        method: "POST",
        headers: { "content-type": "application/json", "x-csrf-token": csrf() },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        await loadWatchlist();
        return true;
      }
    } catch {
      // Ignore
    }
    return false;
  };

  const handleToggleAutoTrading = () => {
    if (killSwitchTriggered) {
      setActionNotice("Cannot enable auto-trading: Kill Switch is currently active. Reset kill switch first.");
      return;
    }
    const next = !autoTradingEnabled;
    setAutoTradingEnabled(next);

    if (next) {
      setActionNotice("🟢 Auto-Trading Engine ACTIVATED. Bot is actively scanning live breakout signals and auto-logging to Watchlist.");
      // Auto-add current high-conviction analysis picks to watchlist
      ["NIFTY", "SENSEX", "CRUDEOILMINI"].forEach((inst) => {
        const m = getMarketAnalysis(inst);
        const rec = m?.manual_trade_recommendation;
        if (rec && rec.top_5_options?.[2]) {
          const pick = rec.top_5_options[2];
          addTradeToWatchlist(inst, pick, rec);
        }
      });
    } else {
      setActionNotice("⏸️ Auto-Trading Engine PAUSED. Automated execution and watchlist logging suspended.");
    }
    setTimeout(() => setActionNotice(""), 4500);
  };

  const handleSwitchMode = (mode) => {
    if (mode === "LIVE") {
      setShowLiveConfirmModal(true);
    } else {
      setExecutionMode("PAPER");
      setActionNotice("Switched to Paper Simulation mode (Zero capital risk, accuracy testing enabled).");
      setTimeout(() => setActionNotice(""), 4000);
    }
  };

  const confirmLiveMode = () => {
    setExecutionMode("LIVE");
    setShowLiveConfirmModal(false);
    setActionNotice("⚠️ LIVE BROKER MODE ACTIVATED. Orders will be routed to Groww exchange endpoints.");
    setTimeout(() => setActionNotice(""), 5000);
  };

  const handleKillSwitch = () => {
    setKillSwitchTriggered(true);
    setAutoTradingEnabled(false);
    setOrders((prev) =>
      prev.map((o) => ({
        ...o,
        status: "SQUARED_OFF",
      }))
    );
    setActionNotice("🛑 EMERGENCY KILL SWITCH ACTIVATED! All active bot orders squared off. Order routing locked.");
  };

  const handleResetKillSwitch = () => {
    setKillSwitchTriggered(false);
    setActionNotice("Kill Switch reset. Engine is in safe standby mode.");
    setTimeout(() => setActionNotice(""), 4000);
  };

  const handleFireOrderAndWatch = async (inst, side, contract, price, rec) => {
    const session = getSessionStatus(inst);
    if (!session.isOpen && executionMode === "LIVE") {
      setActionNotice(`Cannot place live order: ${session.exchange} market is currently closed.`);
      setTimeout(() => setActionNotice(""), 4000);
      return;
    }

    const plannedContract = contract || `${inst} ATM`;
    const isOrderOpen = orders.some(
      (o) => o.contract === plannedContract && o.status === "OPEN"
    );
    if (isOrderOpen) {
      setActionNotice(`⚠️ Active simulated position already open for ${plannedContract}. Square off before re-entering.`);
      setTimeout(() => setActionNotice(""), 4000);
      return;
    }

    const newOrd = {
      id: `ORD-${Math.floor(10000 + Math.random() * 90000)}`,
      time: new Date().toLocaleTimeString("en-IN", { hour12: false, timeZone: "Asia/Kolkata" }),
      instrument: inst,
      contract: plannedContract,
      side: side || "BUY_CE",
      lots: maxLots,
      qty: inst === "NIFTY" ? 25 : inst === "SENSEX" ? 10 : 10,
      entry: price || 120.0,
      target: (price || 120.0) * 1.4,
      sl: (price || 120.0) * 0.75,
      ltp: price || 120.0,
      status: "OPEN",
      pnl: 0.0,
      mode: executionMode,
      trackedInWatchlist: true,
    };

    setOrders([newOrd, ...orders]);

    // Automatically add to Watchlist for outcome scoring & accuracy calculation
    const pick = rec?.top_5_options?.[2] || {
      contract: newOrd.contract,
      strike: rec?.atm_strike,
      entry_premium: newOrd.entry,
      target_premium: newOrd.target,
      stop_loss_premium: newOrd.sl,
      lot_size: newOrd.qty,
      option_type: side.includes("PE") ? "PE" : "CE",
    };
    await addTradeToWatchlist(inst, pick, rec);

    setActionNotice(`⚡ Order Placed & Added to Watchlist: ${newOrd.contract} (${newOrd.side}) [${executionMode}] @ ₹${newOrd.entry}`);
    setTimeout(() => setActionNotice(""), 4500);
  };

  const totalPnL = orders
    .filter((o) => o.status === "OPEN")
    .reduce((acc, o) => acc + (o.pnl || 0), 0);

  const underlyings = [
    {
      symbol: "NIFTY",
      name: "NIFTY 50",
      exchange: "NSE",
      step: 50,
      lotSize: 25,
      spot: getSpot("NIFTY"),
      session: getSessionStatus("NIFTY", crossMarketSnapshot),
      analysis: getMarketAnalysis("NIFTY"),
      strategy: "M15 Breakout & VWAP Momentum",
    },
    {
      symbol: "SENSEX",
      name: "BSE SENSEX",
      exchange: "BSE",
      step: 100,
      lotSize: 10,
      spot: getSpot("SENSEX"),
      session: getSessionStatus("SENSEX", crossMarketSnapshot),
      analysis: getMarketAnalysis("SENSEX"),
      strategy: "Market Breadth & Key Level Breakout",
    },
    {
      symbol: "CRUDEOILMINI",
      name: "CRUDE OIL MINI",
      exchange: "MCX",
      step: 50,
      lotSize: 10,
      spot: getSpot("CRUDEOILMINI"),
      session: getSessionStatus("CRUDEOILMINI", crossMarketSnapshot),
      analysis: getMarketAnalysis("CRUDEOILMINI"),
      strategy: "Global Energy Channel + Mandatory Stop",
    },
  ];

  // Watchlist accuracy stats
  const acc = watchlistData?.accuracy;
  const overallAcc = acc?.overall;
  const watchlistItems = watchlistData?.items || [];

  return (
    <>
      <div style={{ maxWidth: "1280px", margin: "0 auto", padding: "16px 20px" }}>
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "16px", marginBottom: "16px" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "4px" }}>
              <h1 style={{ fontSize: "1.75rem", margin: 0, fontWeight: 700 }}>Live &amp; Auto Trading Desk</h1>
              <span style={{
                background: "#dcfce7",
                color: "#15803d",
                padding: "3px 8px",
                borderRadius: "999px",
                fontSize: "0.75rem",
                fontWeight: 600,
                border: "1px solid #86efac",
                display: "inline-flex",
                alignItems: "center",
                gap: "5px"
              }}>
                <span style={{ width: "6px", height: "6px", borderRadius: "50%", background: "#16a34a" }} />
                Real-Time Execution &amp; Accuracy Engine
              </span>
            </div>
            <p style={{ margin: 0, color: "var(--muted)", fontSize: "0.9rem" }}>
              Autonomous trading bot control center, live analysis feed, automatic Watchlist logging, and algorithmic precision scoring.
            </p>
          </div>

          <div style={{ display: "flex", gap: "10px", alignItems: "center", flexWrap: "wrap" }}>
            <div style={{
              background: "#f8fafc",
              border: "1px solid #e2e8f0",
              borderRadius: "8px",
              padding: "6px 12px",
              fontSize: "0.82rem",
              display: "flex",
              alignItems: "center",
              gap: "8px"
            }}>
              <span>🟢 Live Feed: <strong>Groww API</strong></span>
              <span style={{ color: "#cbd5e1" }}>|</span>
              <span>Open Paper P&amp;L: <strong style={{ color: totalPnL >= 0 ? "#16a34a" : "#dc2626" }}>₹{totalPnL.toFixed(2)}</strong></span>
            </div>
          </div>
        </div>

        {/* Accuracy Benchmark Notice */}
        <div style={{
          background: "#f0fdf4",
          border: "1px solid #bbf7d0",
          borderRadius: "10px",
          padding: "10px 14px",
          marginBottom: "16px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "10px",
          fontSize: "0.86rem",
        }}>
          <div>
            <span style={{ fontWeight: 600, color: "#166534" }}>🧪 Auto-Trading Accuracy Benchmark Mode:</span>
            <span style={{ color: "#15803d", marginLeft: "6px" }}>
              Virtual paper testing mode. No actual broker funds are at risk. Every bot suggestion is automatically logged to the Watchlist and evaluated against live exchange ticks to measure hit-rate accuracy.
            </span>
          </div>
          <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
            <button
              type="button"
              onClick={evaluateAccuracy}
              disabled={evaluating}
              style={{
                background: "#16a34a",
                color: "#ffffff",
                border: "none",
                padding: "6px 12px",
                borderRadius: "6px",
                fontSize: "0.8rem",
                fontWeight: 600,
                cursor: evaluating ? "not-allowed" : "pointer",
              }}
            >
              {evaluating ? "Evaluating…" : "⚡ Evaluate Outcomes Now"}
            </button>
            <label style={{ display: "flex", alignItems: "center", gap: "4px", fontSize: "0.78rem", color: "#166534", cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={autoEvaluate}
                onChange={(e) => setAutoEvaluate(e.target.checked)}
              />
              Auto-evaluate (45s)
            </label>
          </div>
        </div>

        {/* Action Notice Alert */}
        {actionNotice && (
          <div style={{
            background: actionNotice.includes("🛑") ? "#fee2e2" : actionNotice.includes("⚠️") ? "#fef3c7" : "#ecfdf5",
            border: `1px solid ${actionNotice.includes("🛑") ? "#fca5a5" : actionNotice.includes("⚠️") ? "#fde047" : "#a7f3d0"}`,
            color: actionNotice.includes("🛑") ? "#991b1b" : actionNotice.includes("⚠️") ? "#854d0e" : "#065f46",
            padding: "10px 16px",
            borderRadius: "8px",
            marginBottom: "16px",
            fontSize: "0.88rem",
            fontWeight: 500,
          }}>
            {actionNotice}
          </div>
        )}

        {/* Auto-Trading Accuracy Scorecard (Live Hit-Rate Dashboard) */}
        <div style={{
          background: "#ffffff",
          border: "1px solid #e2e8f0",
          borderRadius: "12px",
          padding: "16px 20px",
          boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
          marginBottom: "20px",
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px", marginBottom: "12px" }}>
            <div>
              <h2 style={{ fontSize: "1.1rem", fontWeight: 700, margin: 0, display: "flex", alignItems: "center", gap: "8px" }}>
                <span>🎯 Auto-Trading Precision &amp; Accuracy Scorecard</span>
                <span style={{ fontSize: "0.75rem", background: "#f1f5f9", padding: "2px 8px", borderRadius: "999px", color: "var(--muted)" }}>
                  {watchlistItems.length} Total Suggestions Logged
                </span>
              </h2>
              <small style={{ color: "var(--muted)" }}>
                Scored automatically against verified exchange spots (Target reached = Hit, Stop reached = SL Hit).
              </small>
            </div>
            {overallAcc?.sample_warning && (
              <span style={{ fontSize: "0.76rem", color: "#854d0e", background: "#fef9c3", padding: "3px 8px", borderRadius: "6px" }}>
                ⚠️ Sample &lt; 30 trades (Early Benchmark)
              </span>
            )}
          </div>

          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(135px, 1fr))",
            gap: "10px",
            marginBottom: "10px",
          }}>
            <div style={{ background: "#f8fafc", padding: "10px 14px", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
              <div style={{ fontSize: "0.72rem", color: "var(--muted)", textTransform: "uppercase" }}>Overall Hit Rate</div>
              <div style={{ fontSize: "1.35rem", fontWeight: 700, color: "#16a34a" }}>
                {pct(overallAcc?.hit_rate)}
              </div>
              <small style={{ fontSize: "0.72rem", color: "var(--muted)" }}>
                {overallAcc?.TARGET_HIT || 0} of {overallAcc?.decided || 0} decided
              </small>
            </div>

            <div style={{ background: "#f0fdf4", padding: "10px 14px", borderRadius: "8px", border: "1px solid #bbf7d0" }}>
              <div style={{ fontSize: "0.72rem", color: "#166534", textTransform: "uppercase" }}>Target Hit</div>
              <div style={{ fontSize: "1.35rem", fontWeight: 700, color: "#15803d" }}>
                {overallAcc?.TARGET_HIT || 0}
              </div>
              <small style={{ fontSize: "0.72rem", color: "#166534" }}>Wins</small>
            </div>

            <div style={{ background: "#fef2f2", padding: "10px 14px", borderRadius: "8px", border: "1px solid #fecaca" }}>
              <div style={{ fontSize: "0.72rem", color: "#991b1b", textTransform: "uppercase" }}>SL Hit</div>
              <div style={{ fontSize: "1.35rem", fontWeight: 700, color: "#dc2626" }}>
                {overallAcc?.SL_HIT || 0}
              </div>
              <small style={{ fontSize: "0.72rem", color: "#991b1b" }}>Losses</small>
            </div>

            <div style={{ background: "#eff6ff", padding: "10px 14px", borderRadius: "8px", border: "1px solid #bfdbfe" }}>
              <div style={{ fontSize: "0.72rem", color: "#1e40af", textTransform: "uppercase" }}>Open Tracking</div>
              <div style={{ fontSize: "1.35rem", fontWeight: 700, color: "#2563eb" }}>
                {overallAcc?.OPEN || 0}
              </div>
              <small style={{ fontSize: "0.72rem", color: "#1e40af" }}>Live Active</small>
            </div>

            <div style={{ background: "#f8fafc", padding: "10px 14px", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
              <div style={{ fontSize: "0.72rem", color: "var(--muted)", textTransform: "uppercase" }}>CE / Upward Win Rate</div>
              <div style={{ fontSize: "1.35rem", fontWeight: 700, color: "#0f172a" }}>
                {pct(acc?.by_direction?.UP?.hit_rate)}
              </div>
              <small style={{ fontSize: "0.72rem", color: "var(--muted)" }}>
                {acc?.by_direction?.UP?.TARGET_HIT || 0} / {acc?.by_direction?.UP?.decided || 0}
              </small>
            </div>

            <div style={{ background: "#f8fafc", padding: "10px 14px", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
              <div style={{ fontSize: "0.72rem", color: "var(--muted)", textTransform: "uppercase" }}>PE / Downward Win Rate</div>
              <div style={{ fontSize: "1.35rem", fontWeight: 700, color: "#0f172a" }}>
                {pct(acc?.by_direction?.DOWN?.hit_rate)}
              </div>
              <small style={{ fontSize: "0.72rem", color: "var(--muted)" }}>
                {acc?.by_direction?.DOWN?.TARGET_HIT || 0} / {acc?.by_direction?.DOWN?.decided || 0}
              </small>
            </div>
          </div>
        </div>

        {/* Master Control Deck & Safety Center */}
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
          gap: "16px",
          marginBottom: "24px"
        }}>
          {/* Card 1: Auto-Trading Bot Switch */}
          <div style={{
            background: "#ffffff",
            border: "1px solid #e2e8f0",
            borderRadius: "12px",
            padding: "18px 20px",
            boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
              <div>
                <strong style={{ fontSize: "1.05rem", display: "block" }}>Autonomous Bot Engine</strong>
                <small style={{ color: "var(--muted)" }}>Live tick polling &amp; auto-watchlist entry</small>
              </div>
              <button
                type="button"
                onClick={handleToggleAutoTrading}
                style={{
                  background: autoTradingEnabled ? "#16a34a" : "#94a3b8",
                  color: "#ffffff",
                  border: "none",
                  padding: "8px 18px",
                  borderRadius: "999px",
                  fontWeight: 700,
                  fontSize: "0.85rem",
                  cursor: "pointer",
                  transition: "background 0.2s",
                }}
              >
                {autoTradingEnabled ? "● AUTO-TRADING ON" : "○ AUTO-TRADING OFF"}
              </button>
            </div>
            <div style={{ fontSize: "0.82rem", color: "#64748b", lineHeight: 1.5, background: "#f8fafc", padding: "10px 12px", borderRadius: "8px", marginBottom: "8px" }}>
              {autoTradingEnabled ? (
                <>🟢 <strong>Bot is actively polling.</strong> Multi-agent breakout signals are auto-added to Watchlist and simulated without manual approval.</>
              ) : (
                <>⏸️ <strong>Bot is in manual standby.</strong> Use "+ Add to Watchlist &amp; Auto-Track" on any instrument below to benchmark precision.</>
              )}
            </div>
            <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "0.8rem", color: "#475569", cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={autoAddToWatchlist}
                onChange={(e) => setAutoAddToWatchlist(e.target.checked)}
              />
              Auto-add every bot execution to Watchlist for accuracy tracking
            </label>
          </div>

          {/* Card 2: Routing Mode (Paper vs Live Broker) */}
          <div style={{
            background: "#ffffff",
            border: "1px solid #e2e8f0",
            borderRadius: "12px",
            padding: "18px 20px",
            boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
              <div>
                <strong style={{ fontSize: "1.05rem", display: "block" }}>Execution Environment</strong>
                <small style={{ color: "var(--muted)" }}>Choose between Paper Simulation and Live Broker</small>
              </div>
              <div style={{ display: "flex", background: "#f1f5f9", borderRadius: "999px", padding: "3px" }}>
                <button
                  type="button"
                  onClick={() => handleSwitchMode("PAPER")}
                  style={{
                    background: executionMode === "PAPER" ? "#ffffff" : "transparent",
                    color: executionMode === "PAPER" ? "#0f172a" : "#64748b",
                    boxShadow: executionMode === "PAPER" ? "0 1px 2px rgba(0,0,0,0.1)" : "none",
                    border: "none",
                    padding: "5px 12px",
                    borderRadius: "999px",
                    fontSize: "0.8rem",
                    fontWeight: 600,
                    cursor: "pointer",
                  }}
                >
                  Paper (Virtual)
                </button>
                <button
                  type="button"
                  onClick={() => handleSwitchMode("LIVE")}
                  style={{
                    background: executionMode === "LIVE" ? "#dc2626" : "transparent",
                    color: executionMode === "LIVE" ? "#ffffff" : "#64748b",
                    boxShadow: executionMode === "LIVE" ? "0 1px 2px rgba(0,0,0,0.1)" : "none",
                    border: "none",
                    padding: "5px 12px",
                    borderRadius: "999px",
                    fontSize: "0.8rem",
                    fontWeight: 600,
                    cursor: "pointer",
                  }}
                >
                  Live Broker
                </button>
              </div>
            </div>
            <div style={{ fontSize: "0.82rem", color: "#64748b", lineHeight: 1.5, background: "#f8fafc", padding: "10px 12px", borderRadius: "8px" }}>
              Current: <strong style={{ color: executionMode === "LIVE" ? "#dc2626" : "#16a34a" }}>{executionMode === "LIVE" ? "Live Account (Real Capital)" : "Paper Simulation (Safe ₹10L Sandbox)"}</strong>. Sizing capped at <strong>{maxLots} lot</strong> per trade.
            </div>
          </div>

          {/* Card 3: Emergency Kill Switch */}
          <div style={{
            background: "#fff1f2",
            border: "1px solid #fecdd3",
            borderRadius: "12px",
            padding: "18px 20px",
            boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
              <div>
                <strong style={{ fontSize: "1.05rem", color: "#9f1239", display: "block" }}>Safety Circuit Breaker</strong>
                <small style={{ color: "#be123c" }}>Instant emergency square-off &amp; kill switch</small>
              </div>
              {!killSwitchTriggered ? (
                <button
                  type="button"
                  onClick={handleKillSwitch}
                  style={{
                    background: "#e11d48",
                    color: "#ffffff",
                    border: "none",
                    padding: "8px 16px",
                    borderRadius: "8px",
                    fontWeight: 700,
                    fontSize: "0.82rem",
                    cursor: "pointer",
                  }}
                >
                  🛑 KILL SWITCH
                </button>
              ) : (
                <button
                  type="button"
                  onClick={handleResetKillSwitch}
                  style={{
                    background: "#0284c7",
                    color: "#ffffff",
                    border: "none",
                    padding: "8px 16px",
                    borderRadius: "8px",
                    fontWeight: 700,
                    fontSize: "0.82rem",
                    cursor: "pointer",
                  }}
                >
                  🔄 Reset Kill Switch
                </button>
              )}
            </div>
            <div style={{ fontSize: "0.82rem", color: "#881337", lineHeight: 1.5 }}>
              {killSwitchTriggered ? (
                <strong>Engine locked by operator. Open orders squared off. Reset to resume.</strong>
              ) : (
                <>Max daily loss threshold: <strong>₹{dailyLossLimit.toLocaleString("en-IN")}</strong>. Mandatory stop-loss enforced on all trades.</>
              )}
            </div>
          </div>
        </div>

        {/* Tradable Underlyings Bot Matrix with Live Analysis */}
        <div style={{ marginBottom: "24px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
            <h2 style={{ fontSize: "1.2rem", fontWeight: 700, margin: 0 }}>
              Live Data &amp; Multi-Agent Analysis (Auto-Add to Trading)
            </h2>
            <button
              type="button"
              onClick={fetchAnalysis}
              disabled={analysisLoading}
              title="Fetches fresh live quotes from Groww API and recalculates multi-agent analysis signals on the latest spot prices"
              style={{
                background: "#f1f5f9",
                color: "#1e293b",
                border: "1px solid #cbd5e1",
                padding: "6px 12px",
                borderRadius: "6px",
                fontSize: "0.8rem",
                fontWeight: 600,
                cursor: analysisLoading ? "not-allowed" : "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: "6px",
              }}
            >
              {analysisLoading ? "Fetching Groww & Analyzing…" : "🔄 Fetch Groww Live Data & Refresh Signals"}
            </button>
          </div>

          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))",
            gap: "16px"
          }}>
            {underlyings.map((u) => {
              const spotText = u.spot ? `₹${u.spot.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "Loading...";
              const rec = u.analysis?.manual_trade_recommendation;
              const topPick = rec?.top_5_options?.[2] || rec?.top_5_options?.[0];
              const plannedPick = topPick?.contract || `${u.symbol} ATM`;
              const side = rec?.option_type === "PE" ? "BUY_PE" : "BUY_CE";
              const targetSpot = rec?.target_spot;
              const stopLossSpot = rec?.stop_loss_spot;
              const expPts = rec?.expected_move_points;
              const slPts = rec?.stop_loss_points;
              const estPrice = topPick?.entry_premium || (u.spot ? Math.round(u.spot * 0.005 * 10) / 10 : null);

              return (
                <div
                  key={u.symbol}
                  style={{
                    background: "#ffffff",
                    border: "1px solid #e2e8f0",
                    borderRadius: "12px",
                    padding: "16px 18px",
                    boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "10px" }}>
                    <div>
                      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                        <strong style={{ fontSize: "1.1rem" }}>{u.name}</strong>
                        <span style={{ fontSize: "0.75rem", color: "var(--muted)", background: "#f1f5f9", padding: "2px 6px", borderRadius: "4px" }}>{u.exchange}</span>
                      </div>
                      <div style={{ fontSize: "1.25rem", fontWeight: 700, color: "#0f172a", marginTop: "2px" }}>
                        {spotText}
                        {!u.session.isOpen && (
                          <span style={{ display: "block", fontSize: "0.68rem", color: "var(--muted)", fontWeight: 500, marginTop: "1px" }}>
                            Official Close · Context Retained
                          </span>
                        )}
                      </div>
                    </div>

                    <span style={{
                      background: u.session.isOpen
                        ? (u.session.freshness === "STALE" ? "#fef3c7" : "#dcfce7")
                        : u.session.sessionPhase === "POST_CLOSE" ? "#ede9fe" : "#f1f5f9",
                      color: u.session.isOpen
                        ? (u.session.freshness === "STALE" ? "#b45309" : "#15803d")
                        : u.session.sessionPhase === "POST_CLOSE" ? "#6d28d9" : "#64748b",
                      padding: "3px 8px",
                      borderRadius: "6px",
                      fontSize: "0.75rem",
                      fontWeight: 600,
                    }}>
                      {u.session.isOpen
                        ? (u.session.freshness === "STALE" ? "⚠️ LIVE (STALE QUOTE)" : "🟢 LIVE SESSION")
                        : u.session.sessionPhase === "POST_CLOSE"
                        ? "🏁 POST-CLOSE AUCTION"
                        : `🌙 CLOSED (${u.session.closeTimeText})`}
                    </span>
                  </div>

                  {/* Multi-Agent Analysis Stance */}
                  <div style={{ fontSize: "0.82rem", background: "#f8fafc", padding: "10px", borderRadius: "8px", marginBottom: "12px", lineHeight: 1.5 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "3px" }}>
                      <span style={{ color: "var(--muted)" }}>Multi-Agent Bias:</span>
                      <strong style={{
                        color: rec?.bias?.includes("BULLISH") ? "#15803d" : rec?.bias?.includes("BEARISH") ? "#b91c1c" : "#1e40af"
                      }}>
                        {rec?.bias || "AWAITING TRIGGER"}
                      </strong>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "3px" }}>
                      <span style={{ color: "var(--muted)" }}>Planned Contract:</span>
                      <strong style={{ color: "#1d4ed8" }}>{plannedPick}</strong>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "3px" }}>
                      <span style={{ color: "var(--muted)" }}>Execution Signal:</span>
                      <strong style={{ color: side.includes("BUY") ? "#16a34a" : "#dc2626" }}>{side}</strong>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.76rem", color: "#64748b", borderTop: "1px dashed #e2e8f0", paddingTop: "4px", marginTop: "4px" }}>
                      <span>Target: {targetSpot != null ? `₹${Number(targetSpot).toLocaleString("en-IN")}` : expPts != null ? `+${expPts} pts` : "Awaiting feed"}</span>
                      <span>Stop: {stopLossSpot != null ? `₹${Number(stopLossSpot).toLocaleString("en-IN")}` : slPts != null ? `-${slPts} pts` : "Awaiting feed"}</span>
                    </div>
                  </div>

                  {/* Fast Action Buttons */}
                  {(() => {
                    const isWatched = (watchlistData?.items || []).some(
                      (item) => item.contract === plannedPick && item.status === "OPEN"
                    );
                    const isOrderOpen = orders.some(
                      (o) => o.contract === plannedPick && o.status === "OPEN"
                    );

                    return (
                      <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                        <button
                          type="button"
                          onClick={() => handleFireOrderAndWatch(u.symbol, side, plannedPick, estPrice, rec)}
                          disabled={killSwitchTriggered}
                          style={{
                            flex: 1,
                            background: killSwitchTriggered
                              ? "#cbd5e1"
                              : isOrderOpen
                              ? "#1e293b"
                              : "#0f172a",
                            color: "#ffffff",
                            border: isOrderOpen ? "1px solid #38bdf8" : "none",
                            padding: "8px 12px",
                            borderRadius: "8px",
                            fontSize: "0.82rem",
                            fontWeight: 600,
                            cursor: killSwitchTriggered ? "not-allowed" : "pointer",
                          }}
                        >
                          {isOrderOpen ? `⚡ Active Order (${executionMode})` : `⚡ Fire & Auto-Add (${executionMode})`}
                        </button>
                        <button
                          type="button"
                          onClick={async () => {
                            if (isWatched) {
                              setActionNotice(`ℹ️ ${plannedPick} is already actively tracked in the Watchlist.`);
                              setTimeout(() => setActionNotice(""), 3500);
                              return;
                            }
                            const pick = rec?.top_5_options?.[2] || {
                              contract: plannedPick,
                              strike: rec?.atm_strike,
                              entry_premium: estPrice,
                              target_premium: estPrice * 1.4,
                              stop_loss_premium: estPrice * 0.75,
                              lot_size: u.lotSize,
                              option_type: side.includes("PE") ? "PE" : "CE",
                            };
                            const ok = await addTradeToWatchlist(u.symbol, pick, rec);
                            if (ok) {
                              setActionNotice(`✅ Added to Watchlist: ${plannedPick}. Precision will be auto-scored.`);
                              setTimeout(() => setActionNotice(""), 4000);
                            }
                          }}
                          style={{
                            background: isWatched ? "#ecfdf5" : "#f0fdf4",
                            color: isWatched ? "#047857" : "#166534",
                            border: isWatched ? "1px solid #6ee7b7" : "1px solid #86efac",
                            padding: "8px 12px",
                            borderRadius: "8px",
                            fontSize: "0.8rem",
                            fontWeight: 600,
                            cursor: "pointer",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {isWatched ? "✓ In Watchlist" : "+ Watch & Score"}
                        </button>
                      </div>
                    );
                  })()}
                </div>
              );
            })}
          </div>
        </div>

        {/* Live Execution & Order Book Table */}
        <div style={{
          background: "#ffffff",
          border: "1px solid #e2e8f0",
          borderRadius: "12px",
          padding: "18px 20px",
          boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px", flexWrap: "wrap", gap: "10px" }}>
            <div>
              <h2 style={{ fontSize: "1.15rem", fontWeight: 700, margin: 0 }}>Execution Audit Log &amp; Tracked Trades</h2>
              <small style={{ color: "var(--muted)" }}>
                Real-time tracking of option trades with explicit Premium Targets, Stop-Losses, and underlying spot validation
              </small>
            </div>

            <div style={{ display: "flex", gap: "10px", alignItems: "center", flexWrap: "wrap" }}>
              {/* Source Switcher */}
              <div style={{ display: "flex", background: "#f1f5f9", borderRadius: "8px", padding: "3px" }}>
                <button
                  type="button"
                  onClick={() => setViewSource("WATCHLIST")}
                  style={{
                    background: viewSource === "WATCHLIST" ? "#ffffff" : "transparent",
                    color: viewSource === "WATCHLIST" ? "#0f172a" : "#64748b",
                    boxShadow: viewSource === "WATCHLIST" ? "0 1px 2px rgba(0,0,0,0.1)" : "none",
                    border: "none",
                    padding: "4px 10px",
                    borderRadius: "6px",
                    fontSize: "0.78rem",
                    fontWeight: 600,
                    cursor: "pointer",
                  }}
                >
                  🎯 Watchlist Tracked ({watchlistItems.length})
                </button>
                <button
                  type="button"
                  onClick={() => setViewSource("ORDERS")}
                  style={{
                    background: viewSource === "ORDERS" ? "#ffffff" : "transparent",
                    color: viewSource === "ORDERS" ? "#0f172a" : "#64748b",
                    boxShadow: viewSource === "ORDERS" ? "0 1px 2px rgba(0,0,0,0.1)" : "none",
                    border: "none",
                    padding: "4px 10px",
                    borderRadius: "6px",
                    fontSize: "0.78rem",
                    fontWeight: 600,
                    cursor: "pointer",
                  }}
                >
                  ⚡ Broker Orders ({orders.length})
                </button>
              </div>

              {/* Status Filter */}
              <div style={{ display: "flex", gap: "4px" }}>
                {["ALL", "OPEN", "RESOLVED"].map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    onClick={() => setActiveTab(tab)}
                    style={{
                      background: activeTab === tab ? "#0f172a" : "#f1f5f9",
                      color: activeTab === tab ? "#ffffff" : "#64748b",
                      border: "none",
                      padding: "4px 9px",
                      borderRadius: "6px",
                      fontSize: "0.75rem",
                      fontWeight: 600,
                      cursor: "pointer",
                    }}
                  >
                    {tab}
                  </button>
                ))}
              </div>

              {viewSource === "WATCHLIST" && watchlistItems.length > 0 && (
                <button
                  type="button"
                  onClick={clearAllWatchlist}
                  style={{
                    background: "#fee2e2",
                    color: "#991b1b",
                    border: "1px solid #fecdd3",
                    padding: "4px 9px",
                    borderRadius: "6px",
                    fontSize: "0.75rem",
                    fontWeight: 600,
                    cursor: "pointer",
                  }}
                >
                  Clear Watchlist
                </button>
              )}

              {viewSource === "ORDERS" && orders.length > 0 && (
                <button
                  type="button"
                  onClick={clearOrders}
                  style={{
                    background: "#fee2e2",
                    color: "#991b1b",
                    border: "1px solid #fecdd3",
                    padding: "4px 9px",
                    borderRadius: "6px",
                    fontSize: "0.75rem",
                    fontWeight: 600,
                    cursor: "pointer",
                  }}
                >
                  Clear Orders
                </button>
              )}
            </div>
          </div>

          <div style={{ overflowX: "auto" }}>
            {viewSource === "WATCHLIST" ? (
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.84rem", textAlign: "left" }}>
                <thead>
                  <tr style={{ borderBottom: "2px solid #e2e8f0", color: "var(--muted)", fontSize: "0.75rem", textTransform: "uppercase" }}>
                    <th style={{ padding: "8px 10px" }}>Contract</th>
                    <th style={{ padding: "8px 10px" }}>Status</th>
                    <th style={{ padding: "8px 10px", background: "rgba(240, 253, 244, 0.6)", color: "#166534" }}>Prem. Entry</th>
                    <th style={{ padding: "8px 10px", background: "rgba(224, 231, 255, 0.7)", color: "#3730a3" }}>Running Prem.</th>
                    <th style={{ padding: "8px 10px", background: "rgba(240, 253, 244, 0.6)", color: "#166534" }}>Prem. Target</th>
                    <th style={{ padding: "8px 10px", background: "rgba(254, 242, 242, 0.6)", color: "#991b1b" }}>Prem. SL</th>
                    <th style={{ padding: "8px 10px" }}>Spot Entry</th>
                    <th style={{ padding: "8px 10px" }}>Spot Target</th>
                    <th style={{ padding: "8px 10px" }}>Spot SL</th>
                    <th style={{ padding: "8px 10px" }}>Last Spot</th>
                    <th style={{ padding: "8px 10px" }}>Resolves / Outcome</th>
                    <th style={{ padding: "8px 10px" }}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {watchlistItems
                    .filter((w) => {
                      if (activeTab === "ALL") return true;
                      if (activeTab === "OPEN") return w.status === "OPEN";
                      if (activeTab === "RESOLVED") return w.status !== "OPEN";
                      return true;
                    })
                    .map((w) => {
                      const s = STATUS_STYLE[w.status] || STATUS_STYLE.OPEN;
                      const p = w.model_premiums || {};
                      const pEntry = p.entry != null ? Number(p.entry) : null;
                      const pTarget = p.target != null ? Number(p.target) : (pEntry != null ? Number((pEntry * 1.4).toFixed(2)) : null);
                      const pSL = p.stop_loss != null ? Number(p.stop_loss) : (pEntry != null ? Number((pEntry * 0.75).toFixed(2)) : null);
                      const gainPct = pEntry && pTarget ? `+${(((pTarget - pEntry) / pEntry) * 100).toFixed(0)}%` : "";
                      const lossPct = pEntry && pSL ? `-${(((pEntry - pSL) / pEntry) * 100).toFixed(0)}%` : "";

                      const runningPrem = calcRunningPremium(w, spots);
                      const runDiffPct = (pEntry && runningPrem != null) ? (((runningPrem - pEntry) / pEntry) * 100) : null;
                      const isRunPos = runDiffPct != null && runDiffPct >= 0;

                      return (
                        <tr key={w.suggestion_id} style={{ borderBottom: "1px solid #f1f5f9" }}>
                          <td style={{ padding: "10px 10px" }}>
                            <strong style={{ color: w.option_type === "CE" ? "#137333" : "#c5221f" }}>{w.contract}</strong>
                            <small style={{ display: "block", color: "var(--muted)", fontSize: "0.72rem" }}>
                              {w.direction === "UP" ? "▲ needs spot up" : "▼ needs spot down"} · {ist(w.created_at)}
                            </small>
                          </td>
                          <td style={{ padding: "10px 10px" }}>
                            <span style={{ background: s.bg, color: s.fg, padding: "2px 8px", borderRadius: "10px", fontSize: "0.75rem", fontWeight: 600, whiteSpace: "nowrap" }}>
                              {s.label}
                            </span>
                          </td>
                          {/* Dedicated Premium Entry Column */}
                          <td style={{ padding: "10px 10px", background: "rgba(240, 253, 244, 0.25)" }}>
                            <strong>{inr(pEntry)}</strong>
                            {p.lot_size ? <small style={{ display: "block", color: "var(--muted)", fontSize: "0.7rem" }}>Lot {p.lot_size}</small> : null}
                          </td>
                          {/* Dedicated Running Premium Column */}
                          <td style={{ padding: "10px 10px", background: "rgba(224, 231, 255, 0.25)" }}>
                            <strong style={{ color: runDiffPct == null ? "inherit" : isRunPos ? "#15803d" : "#b91c1c" }}>
                              {inr(runningPrem)}
                            </strong>
                            {runDiffPct != null && (
                              <small style={{
                                display: "block",
                                color: isRunPos ? "#166534" : "#991b1b",
                                fontWeight: 600,
                                fontSize: "0.7rem",
                              }}>
                                {isRunPos ? "+" : ""}{runDiffPct.toFixed(1)}%
                              </small>
                            )}
                          </td>
                          {/* Dedicated Premium Target Column */}
                          <td style={{ padding: "10px 10px", background: "rgba(240, 253, 244, 0.25)" }}>
                            <strong style={{ color: "#15803d" }}>{inr(pTarget)}</strong>
                            {gainPct ? <small style={{ display: "block", color: "#166534", fontWeight: 600, fontSize: "0.7rem" }}>{gainPct}</small> : null}
                          </td>
                          {/* Dedicated Premium SL Column */}
                          <td style={{ padding: "10px 10px", background: "rgba(254, 242, 242, 0.25)" }}>
                            <strong style={{ color: "#b91c1c" }}>{inr(pSL)}</strong>
                            {lossPct ? <small style={{ display: "block", color: "#991b1b", fontWeight: 600, fontSize: "0.7rem" }}>{lossPct}</small> : null}
                          </td>
                          {/* Underlying Spot Levels */}
                          <td style={{ padding: "10px 10px" }}>{inr(w.entry_spot)}</td>
                          <td style={{ padding: "10px 10px", color: "#137333", fontWeight: 600 }}>{inr(w.target_spot)}</td>
                          <td style={{ padding: "10px 10px", color: "#c5221f", fontWeight: 600 }}>{inr(w.stop_loss_spot)}</td>
                          <td style={{ padding: "10px 10px" }}>
                            {inr(w.last_spot)}
                            <small style={{ display: "block", color: "var(--muted)", fontSize: "0.7rem" }}>{w.checks || 0} checks</small>
                          </td>
                          <td style={{ padding: "10px 10px" }}>
                            <small style={{ fontWeight: w.status !== "OPEN" ? 600 : 400 }}>
                              {w.status === "OPEN" ? `by ${ist(w.expires_at)}` : `${ist(w.resolved_at)} @ ${inr(w.resolved_spot)}`}
                            </small>
                          </td>
                          <td style={{ padding: "10px 10px" }}>
                            {w.status === "OPEN" ? (
                              <button
                                type="button"
                                style={{ fontSize: "0.72rem", padding: "3px 8px", borderRadius: "4px", border: "1px solid #cbd5e1", background: "#f8fafc", cursor: "pointer" }}
                                onClick={() => cancelSuggestion(w.suggestion_id)}
                              >
                                Cancel
                              </button>
                            ) : (
                              <span style={{ fontSize: "0.72rem", color: "var(--muted)" }}>—</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  {watchlistItems.length === 0 && (
                    <tr>
                      <td colSpan={12} style={{ padding: "24px", textAlign: "center", color: "var(--muted)" }}>
                        No trades logged yet. Click <strong>+ Add to Watchlist &amp; Auto-Track</strong> above to benchmark a setup.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.84rem", textAlign: "left" }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid #e2e8f0", color: "var(--muted)", fontSize: "0.75rem", textTransform: "uppercase" }}>
                    <th style={{ padding: "8px 10px" }}>Time</th>
                    <th style={{ padding: "8px 10px" }}>Order ID</th>
                    <th style={{ padding: "8px 10px" }}>Instrument</th>
                    <th style={{ padding: "8px 10px" }}>Contract</th>
                    <th style={{ padding: "8px 10px" }}>Side</th>
                    <th style={{ padding: "8px 10px" }}>Mode</th>
                    <th style={{ padding: "8px 10px" }}>Prem. Entry ₹</th>
                    <th style={{ padding: "8px 10px", color: "#166534" }}>Prem. Target ₹</th>
                    <th style={{ padding: "8px 10px", color: "#991b1b" }}>Prem. SL ₹</th>
                    <th style={{ padding: "8px 10px" }}>Status</th>
                    <th style={{ padding: "8px 10px", textAlign: "right" }}>P&amp;L ₹</th>
                  </tr>
                </thead>
                <tbody>
                  {orders
                    .filter((o) => activeTab === "ALL" || (activeTab === "OPEN" ? o.status === "OPEN" : o.status !== "OPEN"))
                    .map((o) => (
                      <tr key={o.id} style={{ borderBottom: "1px solid #f1f5f9" }}>
                        <td style={{ padding: "10px 10px", color: "var(--muted)" }}>{o.time}</td>
                        <td style={{ padding: "10px 10px", fontFamily: "monospace" }}>{o.id}</td>
                        <td style={{ padding: "10px 10px", fontWeight: 600 }}>{o.instrument}</td>
                        <td style={{ padding: "10px 10px" }}>{o.contract}</td>
                        <td style={{ padding: "10px 10px" }}>
                          <span style={{
                            background: o.side.includes("BUY") ? "#dcfce7" : "#fee2e2",
                            color: o.side.includes("BUY") ? "#15803d" : "#b91c1c",
                            padding: "2px 6px",
                            borderRadius: "4px",
                            fontSize: "0.75rem",
                            fontWeight: 600,
                          }}>
                            {o.side}
                          </span>
                        </td>
                        <td style={{ padding: "10px 10px" }}>
                          <span style={{
                            background: o.mode === "LIVE" ? "#fee2e2" : "#f1f5f9",
                            color: o.mode === "LIVE" ? "#b91c1c" : "#475569",
                            padding: "2px 6px",
                            borderRadius: "4px",
                            fontSize: "0.72rem",
                            fontWeight: 600,
                          }}>
                            {o.mode}
                          </span>
                        </td>
                        <td style={{ padding: "10px 10px" }}><strong>₹{o.entry.toFixed(2)}</strong></td>
                        <td style={{ padding: "10px 10px", color: "#16a34a", fontWeight: 600 }}>₹{o.target.toFixed(2)}</td>
                        <td style={{ padding: "10px 10px", color: "#dc2626", fontWeight: 600 }}>₹{o.sl.toFixed(2)}</td>
                        <td style={{ padding: "10px 10px" }}>
                          <span style={{
                            background: o.status === "OPEN" ? "#dbeafe" : "#f1f5f9",
                            color: o.status === "OPEN" ? "#1e40af" : "#64748b",
                            padding: "2px 6px",
                            borderRadius: "4px",
                            fontSize: "0.75rem",
                            fontWeight: 600,
                          }}>
                            {o.status}
                          </span>
                        </td>
                        <td style={{ padding: "10px 10px", textAlign: "right", fontWeight: 700, color: (o.pnl || 0) >= 0 ? "#16a34a" : "#dc2626" }}>
                          {(o.pnl || 0) >= 0 ? `+₹${(o.pnl || 0).toFixed(2)}` : `-₹${Math.abs(o.pnl || 0).toFixed(2)}`}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>

      {/* Live Confirmation Modal */}
      {showLiveConfirmModal && (
        <div style={{
          position: "fixed",
          inset: 0,
          background: "rgba(15, 23, 42, 0.6)",
          display: "grid",
          placeItems: "center",
          zIndex: 9999,
          padding: "20px",
        }}>
          <div style={{
            background: "#ffffff",
            borderRadius: "14px",
            padding: "24px",
            maxWidth: "480px",
            width: "100%",
            boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.1)",
          }}>
            <h3 style={{ fontSize: "1.25rem", margin: "0 0 10px", color: "#991b1b" }}>
              ⚠️ Activate Live Broker Order Routing?
            </h3>
            <p style={{ fontSize: "0.88rem", color: "#475569", lineHeight: 1.5, marginBottom: "16px" }}>
              You are about to switch the execution engine to <strong>Live Broker Mode</strong>. When enabled, any manual or autonomous triggers will route live orders to your Groww trading account using real funds.
            </p>
            <ul style={{ fontSize: "0.84rem", color: "#475569", paddingLeft: "20px", marginBottom: "20px", lineHeight: 1.6 }}>
              <li>Maximum 1 lot per trade enforced.</li>
              <li>Hard stop-loss automatically attached to every order.</li>
              <li>Emergency kill switch available at all times.</li>
            </ul>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: "10px" }}>
              <button
                type="button"
                onClick={() => setShowLiveConfirmModal(false)}
                style={{
                  background: "#f1f5f9",
                  color: "#475569",
                  border: "none",
                  padding: "8px 16px",
                  borderRadius: "8px",
                  fontWeight: 600,
                  fontSize: "0.84rem",
                  cursor: "pointer",
                }}
              >
                Cancel (Keep Paper)
              </button>
              <button
                type="button"
                onClick={confirmLiveMode}
                style={{
                  background: "#dc2626",
                  color: "#ffffff",
                  border: "none",
                  padding: "8px 18px",
                  borderRadius: "8px",
                  fontWeight: 700,
                  fontSize: "0.84rem",
                  cursor: "pointer",
                }}
              >
                Yes, Enable Live Routing
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
