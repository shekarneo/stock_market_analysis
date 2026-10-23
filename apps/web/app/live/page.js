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
  // 1. Prioritize genuine live option quote directly from Groww Option Chain
  if (w.live_option_premium != null && Number(w.live_option_premium) > 0) {
    return Number(w.live_option_premium);
  }
  const p = w.model_premiums || {};
  if (p.running_premium != null && Number(p.running_premium) > 0) {
    return Number(p.running_premium);
  }

  // 2. Fallback to model delta calculation if option chain LTP is unavailable
  const pEntry = p.entry != null ? Number(p.entry) : null;
  if (pEntry == null) return null;

  const entrySpot = Number(w.entry_spot);
  const currentSpot = (spots && spots[w.instrument] != null)
    ? Number(spots[w.instrument])
    : (w.last_spot != null
        ? Number(w.last_spot)
        : (w.resolved_spot != null ? Number(w.resolved_spot) : entrySpot));

  if (isNaN(entrySpot) || isNaN(currentSpot)) return pEntry;
  const isUp = w.direction === "UP" || w.option_type === "CE";
  const spotDelta = isUp ? (currentSpot - entrySpot) : (entrySpot - currentSpot);
  const isFut = Boolean(w.contract && w.contract.includes("FUT"));
  const delta = isFut ? 1.0 : (p.delta != null ? Number(p.delta) : null);
  if (delta == null) return null; // no live delta captured: do not estimate a running premium
  const premDelta = spotDelta * delta;
  return Number(Math.max(0.05, pEntry + premDelta).toFixed(2));
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

const STATUS_STYLE = {
  OPEN: { bg: "rgba(56, 189, 248, 0.15)", fg: "#38bdf8", label: "Open" },
  TARGET_HIT: { bg: "rgba(16, 185, 129, 0.15)", fg: "#34d399", label: "Target hit" },
  SL_HIT: { bg: "rgba(244, 63, 94, 0.15)", fg: "#f87171", label: "SL hit" },
  EXPIRED: { bg: "rgba(255, 255, 255, 0.08)", fg: "#94a3b8", label: "Expired" },
  AMBIGUOUS: { bg: "rgba(245, 158, 11, 0.15)", fg: "#fbbf24", label: "Ambiguous" },
  CANCELLED: { bg: "rgba(255, 255, 255, 0.08)", fg: "#94a3b8", label: "Cancelled" },
};

export default function LiveTradingPage() {
  const { spots, quotes, refreshNow, retrievedAt, crossMarketSnapshot, postCloseMode } = useMarketData();

  const [analysisData, setAnalysisData] = useState(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [lastAnalysisAt, setLastAnalysisAt] = useState(null);
  const [autoRunAnalysis, setAutoRunAnalysis] = useState(true);
  const [analysisIntervalSec, setAnalysisIntervalSec] = useState(60);
  const [watchlistData, setWatchlistData] = useState(null);
  const [evaluating, setEvaluating] = useState(false);
  const [autoEvaluate, setAutoEvaluate] = useState(true);
  const [evalIntervalSec, setEvalIntervalSec] = useState(45);
  const evalTimer = useRef(null);
  const analysisTimer = useRef(null);
  const prevRetrievedAt = useRef(null);

  const [isHydrated, setIsHydrated] = useState(false);
  const [autoTradingEnabled, setAutoTradingEnabled] = useState(false);
  const [autoAddToWatchlist, setAutoAddToWatchlist] = useState(true);
  const [executionMode, setExecutionMode] = useState("PAPER"); // "PAPER" or "LIVE"
  const [showLiveConfirmModal, setShowLiveConfirmModal] = useState(false);
  const [killSwitchTriggered, setKillSwitchTriggered] = useState(false);
  // Server-side state (source of truth): DB kill switch + out-of-band halt (file/GPIO)
  const [serverHalt, setServerHalt] = useState(null);
  const [killSwitchBusy, setKillSwitchBusy] = useState(false);
  const [maxLots, setMaxLots] = useState(1);
  const [dailyLossLimit, setDailyLossLimit] = useState(5000);
  const [activeTab, setActiveTab] = useState("ALL");
  const [viewSource, setViewSource] = useState("WATCHLIST"); // "WATCHLIST" or "ORDERS"
  const [actionNotice, setActionNotice] = useState("");

  const [orders, setOrders] = useState([]);

  // Hydrate persistent state from browser localStorage on mount
  useEffect(() => {
    try {
      const savedAuto = localStorage.getItem("imm_auto_trading_enabled");
      if (savedAuto !== null) {
        setAutoTradingEnabled(savedAuto === "true");
      }
      const savedMode = localStorage.getItem("imm_execution_mode");
      if (savedMode === "PAPER" || savedMode === "LIVE") {
        setExecutionMode(savedMode);
      }
      const savedWatchlist = localStorage.getItem("imm_auto_add_watchlist");
      if (savedWatchlist !== null) {
        setAutoAddToWatchlist(savedWatchlist === "true");
      }
      const savedAutoEval = localStorage.getItem("imm_auto_evaluate");
      if (savedAutoEval !== null) {
        setAutoEvaluate(savedAutoEval === "true");
      }
      const savedEvalSec = localStorage.getItem("imm_eval_interval_sec");
      if (savedEvalSec) {
        const parsedEval = parseInt(savedEvalSec, 10);
        if (!isNaN(parsedEval) && parsedEval >= 15) setEvalIntervalSec(parsedEval);
      }
      const savedAutoAnalysis = localStorage.getItem("imm_auto_run_analysis");
      if (savedAutoAnalysis !== null) {
        setAutoRunAnalysis(savedAutoAnalysis === "true");
      }
      const savedAnalysisSec = localStorage.getItem("imm_analysis_interval_sec");
      if (savedAnalysisSec) {
        const parsedAnalysis = parseInt(savedAnalysisSec, 10);
        if (!isNaN(parsedAnalysis) && parsedAnalysis >= 15) setAnalysisIntervalSec(parsedAnalysis);
      }
      const savedLots = localStorage.getItem("imm_max_lots");
      if (savedLots) {
        const parsed = parseInt(savedLots, 10);
        if (!isNaN(parsed) && parsed > 0) setMaxLots(parsed);
      }
      const savedLossLimit = localStorage.getItem("imm_daily_loss_limit");
      if (savedLossLimit) {
        const parsed = parseFloat(savedLossLimit);
        if (!isNaN(parsed) && parsed > 0) setDailyLossLimit(parsed);
      }
      const savedOrders = localStorage.getItem("imm_live_simulated_orders");
      if (savedOrders) {
        const parsed = JSON.parse(savedOrders);
        if (Array.isArray(parsed)) {
          setOrders(parsed);
        }
      }
    } catch {
      // Storage unavailable or quota blocked
    } finally {
      setIsHydrated(true);
    }
  }, []);

  // Sync state changes to localStorage so settings and orders persist across refreshes
  useEffect(() => {
    if (!isHydrated) return;
    try {
      localStorage.setItem("imm_auto_trading_enabled", String(autoTradingEnabled));
      localStorage.setItem("imm_execution_mode", executionMode);
      localStorage.setItem("imm_auto_add_watchlist", String(autoAddToWatchlist));
      localStorage.setItem("imm_auto_evaluate", String(autoEvaluate));
      localStorage.setItem("imm_eval_interval_sec", String(evalIntervalSec));
      localStorage.setItem("imm_auto_run_analysis", String(autoRunAnalysis));
      localStorage.setItem("imm_analysis_interval_sec", String(analysisIntervalSec));
      localStorage.setItem("imm_max_lots", String(maxLots));
      localStorage.setItem("imm_daily_loss_limit", String(dailyLossLimit));
      localStorage.setItem("imm_live_simulated_orders", JSON.stringify(orders));
    } catch {
      // Ignore storage errors
    }
  }, [autoTradingEnabled, executionMode, autoAddToWatchlist, autoEvaluate, evalIntervalSec, autoRunAnalysis, analysisIntervalSec, maxLots, dailyLossLimit, orders, isHydrated]);

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
    try {
      localStorage.removeItem("imm_live_simulated_orders");
    } catch {
      // Ignore
    }
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
          include_forecast: true,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        setAnalysisData(data);
        setLastAnalysisAt(new Date().toISOString());
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

  // Recurring auto-run of full market analysis & strike decisions at configurable interval
  useEffect(() => {
    if (!autoRunAnalysis) {
      clearInterval(analysisTimer.current);
      return undefined;
    }
    const intervalMs = Math.max(15000, (Number(analysisIntervalSec) || 60) * 1000);
    analysisTimer.current = setInterval(() => {
      fetchAnalysis();
    }, intervalMs);
    return () => clearInterval(analysisTimer.current);
  }, [autoRunAnalysis, analysisIntervalSec, fetchAnalysis]);

  // Recurring auto-evaluation of accuracy at configurable interval
  useEffect(() => {
    if (!autoEvaluate) {
      clearInterval(evalTimer.current);
      return undefined;
    }
    const intervalMs = Math.max(15000, (Number(evalIntervalSec) || 45) * 1000);
    evalTimer.current = setInterval(() => {
      evaluateAccuracy();
    }, intervalMs);
    return () => clearInterval(evalTimer.current);
  }, [autoEvaluate, evalIntervalSec, evaluateAccuracy]);

  const getSpot = useCallback((inst) => {
    if (spots && spots[inst] != null) return spots[inst];
    if (inst === "CRUDEOILMINI" && spots?.CRUDEMINI != null) return spots.CRUDEMINI;
    if (inst === "CRUDEMINI" && spots?.CRUDEOILMINI != null) return spots.CRUDEOILMINI;
    const q = (quotes || []).find((x) => x.instrument === inst);
    if (q?.last_price) return Number(q.last_price);
    const m = analysisData?.intelligence?.markets?.[inst];
    if (m?.last_price) return Number(m.last_price);
    return null;
  }, [spots, quotes, analysisData]);

  const getMarketAnalysis = useCallback((inst) => {
    return analysisData?.intelligence?.markets?.[inst] || null;
  }, [analysisData]);

  // Auto-Add trade to Watchlist and track accuracy (deduplicating active open contracts and recent resolutions)
  const addTradeToWatchlist = useCallback(async (inst, pick, rec) => {
    const plannedContract = pick?.contract || `${inst} ATM`;
    const isRecentlyTracked = (watchlistData?.items || []).some((item) => {
      if (item.contract !== plannedContract) return false;
      if (item.status === "OPEN") return true;
      if (item.resolved_at) {
        const diffMs = Date.now() - new Date(item.resolved_at).getTime();
        return diffMs < 15 * 60 * 1000; // 15-minute cooldown to prevent repetitive SL-hit loops
      }
      return false;
    });
    if (isRecentlyTracked) {
      setActionNotice(`ℹ️ ${plannedContract} is already actively tracked or recently resolved.`);
      setTimeout(() => setActionNotice(""), 3500);
      return false;
    }

    try {
      if (rec?.is_actionable === false || rec?.call?.includes("STAND ASIDE")) {
        setActionNotice(`⚠️ Trade rejected: Consensus risk gate is active (${rec?.conviction || "STAND ASIDE"}).`);
        setTimeout(() => setActionNotice(""), 3500);
        return false;
      }
      const liveSpotPrice = getSpot(inst) ?? rec?.spot_price ?? null;
      const targetPoints = rec?.expected_move_points ?? null;
      const stopLossPoints = rec?.stop_loss_points ?? null;
      if (liveSpotPrice == null || targetPoints == null || stopLossPoints == null) {
        setActionNotice(`⚠️ ${plannedContract} not tracked: live spot or analysis target/stop distances are unavailable.`);
        setTimeout(() => setActionNotice(""), 3500);
        return false;
      }
      // Only live option-chain values are sent; missing premiums stay missing (Truth in Data).
      const modelPremiums = {
        strike: pick?.strike ?? rec?.atm_strike ?? null,
        moneyness: pick?.moneyness ?? null,
        lot_size: pick?.lot_size ?? null,
      };
      if (pick?.is_live_quote) {
        modelPremiums.entry = pick.entry_premium ?? null;
        modelPremiums.target = pick.target_premium ?? null;
        modelPremiums.stop_loss = pick.stop_loss_premium ?? null;
        modelPremiums.delta = pick.delta ?? null;
      }
      const payload = {
        instrument: inst,
        contract: plannedContract,
        option_type: pick?.option_type || rec?.option_type || "CE",
        call: rec?.call || (pick?.option_type === "PE" ? "BUY_PE" : "BUY_CE"),
        entry_spot: liveSpotPrice,
        target_points: targetPoints,
        stop_loss_points: stopLossPoints,
        data_class: rec?.data_class || "UNVERIFIED_PROVIDER_DATA",
        model_premiums: modelPremiums,
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
  }, [watchlistData, getSpot, loadWatchlist]);

  // Auto-scan routine for autonomous bot
  const triggerAutoTradingScan = useCallback(() => {
    if (killSwitchTriggered) return;
    if (analysisData?.decision === "NO_TRADE") return;
    ["NIFTY", "SENSEX", "CRUDEOILMINI"].forEach((inst) => {
      const m = getMarketAnalysis(inst);
      const rec = m?.manual_trade_recommendation;
      if (rec && rec.is_actionable !== false && rec.call && !rec.call.startsWith("STAND ASIDE") && rec.top_5_options?.[2]) {
        const pick = rec.top_5_options[2];
        if (autoAddToWatchlist) {
          addTradeToWatchlist(inst, pick, rec);
        }
      }
    });
  }, [killSwitchTriggered, analysisData, autoAddToWatchlist, getMarketAnalysis, addTradeToWatchlist]);

  // When live quotes sync or analysis arrives, auto-scan if auto trading is enabled
  useEffect(() => {
    if (!autoTradingEnabled || killSwitchTriggered || !analysisData) return;
    triggerAutoTradingScan();
  }, [analysisData, retrievedAt, autoTradingEnabled, killSwitchTriggered, triggerAutoTradingScan]);

  const handleToggleAutoTrading = () => {
    if (killSwitchTriggered) {
      setActionNotice("Cannot enable auto-trading: Kill Switch is currently active. Reset kill switch first.");
      return;
    }
    const next = !autoTradingEnabled;
    setAutoTradingEnabled(next);
    try {
      localStorage.setItem("imm_auto_trading_enabled", String(next));
    } catch {
      // Ignore
    }

    if (next) {
      setActionNotice("🟢 Auto-Trading Engine ACTIVATED. Bot is actively scanning live breakout signals and auto-logging to Watchlist.");
      triggerAutoTradingScan();
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
      try {
        localStorage.setItem("imm_execution_mode", "PAPER");
      } catch {
        // Ignore
      }
      setActionNotice("Switched to Paper Simulation mode (Zero capital risk, accuracy testing enabled).");
      setTimeout(() => setActionNotice(""), 4000);
    }
  };

  const confirmLiveMode = () => {
    setExecutionMode("LIVE");
    try {
      localStorage.setItem("imm_execution_mode", "LIVE");
    } catch {
      // Ignore
    }
    setShowLiveConfirmModal(false);
    setActionNotice("⚠️ LIVE BROKER MODE ACTIVATED. Orders will be routed to Groww exchange endpoints.");
    setTimeout(() => setActionNotice(""), 5000);
  };

  const applyServerHalt = useCallback((state) => {
    setServerHalt(state);
    // Any server-side halt (or an unknown switch) locks this page too
    if (state?.entries_halted) setKillSwitchTriggered(true);
  }, []);

  const loadKillSwitch = useCallback(async () => {
    try {
      const res = await fetch("/api/kill-switch");
      if (res.ok) applyServerHalt(await res.json());
    } catch {
      // Keep the last known state; the local lock is unaffected
    }
  }, [applyServerHalt]);

  useEffect(() => {
    loadKillSwitch();
    const timer = setInterval(loadKillSwitch, 15000);
    return () => clearInterval(timer);
  }, [loadKillSwitch]);

  const postKillSwitch = async (enabled, reason) => {
    const res = await fetch("/api/kill-switch", {
      method: "POST",
      headers: { "content-type": "application/json", "x-csrf-token": csrf() },
      body: JSON.stringify({ enabled, reason }),
    });
    const body = await res.json().catch(() => null);
    if (!res.ok || !body) throw new Error(body?.message || `HTTP ${res.status}`);
    return body;
  };

  const handleKillSwitch = async () => {
    // Lock locally first so this page stops even if the server call fails
    setKillSwitchTriggered(true);
    setAutoTradingEnabled(false);
    try {
      localStorage.setItem("imm_auto_trading_enabled", "false");
    } catch {
      // Ignore
    }
    setOrders((prev) =>
      prev.map((o) => ({
        ...o,
        status: "SQUARED_OFF",
      }))
    );
    setKillSwitchBusy(true);
    try {
      applyServerHalt(await postKillSwitch(true, "Emergency kill switch from /live"));
      setActionNotice("🛑 KILL SWITCH ACTIVATED on the server. New entries are blocked for every session; simulated orders here squared off.");
    } catch (err) {
      setActionNotice(`⚠️ Server kill switch NOT confirmed (${err.message}). This page is locked locally only — trip it from the CLI or the halt file.`);
    } finally {
      setKillSwitchBusy(false);
    }
  };

  const handleResetKillSwitch = async () => {
    if (serverHalt?.external_halt?.halted) {
      setActionNotice(`Out-of-band halt is active (${serverHalt.external_halt.reasons.join(", ")}). Clear it at its source first.`);
      setTimeout(() => setActionNotice(""), 5000);
      return;
    }
    setKillSwitchBusy(true);
    try {
      const state = await postKillSwitch(false, "Kill switch reset from /live");
      setServerHalt(state);
      if (state.entries_halted) {
        setActionNotice("Server still reports entries halted; the lock stays on.");
      } else {
        setKillSwitchTriggered(false);
        setActionNotice("Kill switch cleared on the server. Engine is in safe standby mode.");
      }
    } catch (err) {
      setActionNotice(`⚠️ Kill switch not cleared (${err.message}). The lock stays on.`);
    } finally {
      setKillSwitchBusy(false);
      setTimeout(() => setActionNotice(""), 5000);
    }
  };

  const handleFireOrderAndWatch = async (inst, side, contract, price, rec) => {
    if (rec?.is_actionable === false || rec?.call?.includes("STAND ASIDE") || side?.includes("STAND ASIDE")) {
      setActionNotice(`⚠️ Trade blocked: Consensus risk gate active (${rec?.conviction || "STAND ASIDE"}). Execution disallowed.`);
      setTimeout(() => setActionNotice(""), 4500);
      return;
    }

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

    const spotVal = getSpot(inst);
    const livePick = rec?.top_5_options?.[2];
    if (price == null || spotVal == null || !livePick?.is_live_quote || livePick?.lot_size == null) {
      setActionNotice(`⚠️ Cannot simulate ${plannedContract}: a fresh live option-chain premium, lot size and live spot are required.`);
      setTimeout(() => setActionNotice(""), 4500);
      return;
    }
    const newOrd = {
      id: `ORD-${Math.floor(10000 + Math.random() * 90000)}`,
      time: new Date().toLocaleTimeString("en-IN", { hour12: false, timeZone: "Asia/Kolkata" }),
      instrument: inst,
      contract: plannedContract,
      side: side || "BUY_CE",
      lots: maxLots,
      qty: livePick.lot_size,
      entry: price,
      target: livePick.target_premium ?? null,
      sl: livePick.stop_loss_premium ?? null,
      delta: livePick.delta ?? null,
      ltp: price,
      entrySpot: spotVal,
      status: "OPEN",
      pnl: 0.0,
      mode: executionMode,
      trackedInWatchlist: true,
    };

    setOrders([newOrd, ...orders]);

    // Automatically add to Watchlist for outcome scoring & accuracy calculation
    await addTradeToWatchlist(inst, livePick, rec);

    setActionNotice(`⚡ Order Placed & Added to Watchlist: ${newOrd.contract} (${newOrd.side}) [${executionMode}] @ ₹${newOrd.entry}`);
    setTimeout(() => setActionNotice(""), 4500);
  };

  // Update open simulated orders LTP & mark-to-market PnL when spots update
  useEffect(() => {
    if (!spots || orders.length === 0) return;
    setOrders((prevOrders) => {
      let changed = false;
      const nextOrders = prevOrders.map((ord) => {
        if (ord.status !== "OPEN") return ord;
        const currentSpot = spots[ord.instrument] != null ? Number(spots[ord.instrument]) : null;
        if (currentSpot == null || isNaN(currentSpot)) return ord;
        const entrySpot = ord.entrySpot;
        const delta = ord.contract?.includes("FUT") ? 1.0 : ord.delta;
        if (entrySpot == null || delta == null || ord.entry == null || ord.qty == null) return ord;
        const isCe = ord.side ? ord.side.includes("CE") : true;
        const spotDelta = isCe ? (currentSpot - entrySpot) : (entrySpot - currentSpot);
        const currentLtp = Number(Math.max(0.05, ord.entry + spotDelta * delta).toFixed(2));
        const currentPnl = Number(((currentLtp - ord.entry) * ord.qty * ord.lots).toFixed(2));
        if (currentLtp !== ord.ltp || currentPnl !== ord.pnl) {
          changed = true;
          return { ...ord, ltp: currentLtp, pnl: currentPnl, entrySpot };
        }
        return ord;
      });
      return changed ? nextOrders : prevOrders;
    });
  }, [spots, orders.length]);

  const totalPnL = orders
    .filter((o) => o.status === "OPEN")
    .reduce((acc, o) => acc + (o.pnl || 0), 0);

  const underlyings = [
    {
      symbol: "NIFTY",
      name: "NIFTY 50",
      exchange: "NSE",
      step: 50,
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
              background: "var(--card, #0f172a)",
              border: "1px solid var(--line)",
              borderRadius: "8px",
              padding: "6px 12px",
              fontSize: "0.82rem",
              display: "flex",
              alignItems: "center",
              gap: "8px",
              color: "var(--ink, #f8fafc)"
            }}>
              <span>🟢 Live Feed: <strong>Groww API</strong></span>
              <span style={{ color: "var(--line)" }}>|</span>
              <span>Open Paper P&amp;L: <strong style={{ color: totalPnL >= 0 ? "#10b981" : "#f43f5e" }}>₹{totalPnL.toFixed(2)}</strong></span>
            </div>
          </div>
        </div>

        {/* Accuracy Benchmark Notice */}
        <div style={{
          background: "var(--green-bg, rgba(16, 185, 129, 0.12))",
          border: "1px solid rgba(16, 185, 129, 0.3)",
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
            <span style={{ fontWeight: 600, color: "var(--green, #10b981)" }}>🧪 Auto-Trading Accuracy Benchmark Mode:</span>
            <span style={{ color: "#a7f3d0", marginLeft: "6px" }}>
              Virtual paper testing mode. No actual broker funds are at risk. Every bot suggestion is automatically logged to the Watchlist and evaluated against live exchange ticks to measure hit-rate accuracy.
            </span>
          </div>
          <div style={{ display: "flex", gap: "10px", alignItems: "center", flexWrap: "wrap" }}>
            <button
              type="button"
              onClick={fetchAnalysis}
              disabled={analysisLoading}
              style={{
                background: "#2563eb",
                color: "#ffffff",
                border: "none",
                padding: "6px 12px",
                borderRadius: "6px",
                fontSize: "0.8rem",
                fontWeight: 600,
                cursor: analysisLoading ? "not-allowed" : "pointer",
              }}
            >
              {analysisLoading ? "Running Analysis…" : "🔄 Run Analysis Now"}
            </button>
            <label style={{ display: "flex", alignItems: "center", gap: "4px", fontSize: "0.78rem", color: "#a7f3d0", cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={autoRunAnalysis}
                onChange={(e) => setAutoRunAnalysis(e.target.checked)}
              />
              Auto-run Analysis:
            </label>
            <select
              aria-label="Auto-run analysis interval"
              value={analysisIntervalSec}
              onChange={(e) => setAnalysisIntervalSec(Number(e.target.value) || 60)}
              style={{ fontSize: "0.78rem", padding: "3px 6px", borderRadius: "4px", background: "#0f172a", color: "#f8fafc", border: "1px solid rgba(16, 185, 129, 0.4)" }}
            >
              <option value={30}>Every 30s</option>
              <option value={60}>Every 1m (60s)</option>
              <option value={120}>Every 2m (120s)</option>
              <option value={300}>Every 5m (300s)</option>
              <option value={900}>Every 15m (900s)</option>
            </select>

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
            <label style={{ display: "flex", alignItems: "center", gap: "4px", fontSize: "0.78rem", color: "#a7f3d0", cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={autoEvaluate}
                onChange={(e) => setAutoEvaluate(e.target.checked)}
              />
              Auto-evaluate:
            </label>
            <select
              aria-label="Auto-evaluate interval"
              value={evalIntervalSec}
              onChange={(e) => setEvalIntervalSec(Number(e.target.value) || 45)}
              style={{ fontSize: "0.78rem", padding: "3px 6px", borderRadius: "4px", background: "#0f172a", color: "#f8fafc", border: "1px solid rgba(16, 185, 129, 0.4)" }}
            >
              <option value={15}>Every 15s</option>
              <option value={30}>Every 30s</option>
              <option value={45}>Every 45s</option>
              <option value={60}>Every 1m (60s)</option>
              <option value={120}>Every 2m (120s)</option>
            </select>
            {lastAnalysisAt ? (
              <span style={{ fontSize: "0.73rem", color: "#a7f3d0" }}>
                Updated: {ist(lastAnalysisAt)}
              </span>
            ) : null}
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
          background: "var(--card, #0f172a)",
          border: "1px solid var(--line)",
          borderRadius: "12px",
          padding: "16px 20px",
          boxShadow: "var(--shadow)",
          marginBottom: "20px",
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px", marginBottom: "12px" }}>
            <div>
              <h2 style={{ fontSize: "1.1rem", fontWeight: 700, margin: 0, display: "flex", alignItems: "center", gap: "8px", color: "var(--ink)" }}>
                <span>🎯 Auto-Trading Precision &amp; Accuracy Scorecard</span>
                <span style={{ fontSize: "0.75rem", background: "rgba(255, 255, 255, 0.08)", padding: "2px 8px", borderRadius: "999px", color: "var(--muted)" }}>
                  {watchlistItems.length} Total Suggestions Logged
                </span>
              </h2>
              <small style={{ color: "var(--muted)" }}>
                Scored automatically against verified exchange spots (Target reached = Hit, Stop reached = SL Hit).
              </small>
            </div>
            {overallAcc?.sample_warning && (
              <span style={{ fontSize: "0.76rem", color: "var(--amber)", background: "var(--amber-bg)", padding: "3px 8px", borderRadius: "6px", border: "1px solid rgba(245, 158, 11, 0.3)" }}>
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
            <div style={{ background: "var(--card-subtle, #131c31)", padding: "10px 14px", borderRadius: "8px", border: "1px solid var(--line)" }}>
              <div style={{ fontSize: "0.72rem", color: "var(--muted)", textTransform: "uppercase" }}>Overall Hit Rate</div>
              <div style={{ fontSize: "1.35rem", fontWeight: 700, color: "var(--green)" }}>
                {pct(overallAcc?.hit_rate)}
              </div>
              <small style={{ fontSize: "0.72rem", color: "var(--muted)" }}>
                {overallAcc?.TARGET_HIT || 0} of {overallAcc?.decided || 0} decided
              </small>
            </div>

            <div style={{ background: "var(--green-bg)", padding: "10px 14px", borderRadius: "8px", border: "1px solid rgba(16, 185, 129, 0.3)" }}>
              <div style={{ fontSize: "0.72rem", color: "#6ee7b7", textTransform: "uppercase" }}>Target Hit</div>
              <div style={{ fontSize: "1.35rem", fontWeight: 700, color: "var(--green)" }}>
                {overallAcc?.TARGET_HIT || 0}
              </div>
              <small style={{ fontSize: "0.72rem", color: "#6ee7b7" }}>Wins</small>
            </div>

            <div style={{ background: "var(--red-bg)", padding: "10px 14px", borderRadius: "8px", border: "1px solid rgba(244, 63, 94, 0.3)" }}>
              <div style={{ fontSize: "0.72rem", color: "#fda4af", textTransform: "uppercase" }}>SL Hit</div>
              <div style={{ fontSize: "1.35rem", fontWeight: 700, color: "var(--red)" }}>
                {overallAcc?.SL_HIT || 0}
              </div>
              <small style={{ fontSize: "0.72rem", color: "#fda4af" }}>Losses</small>
            </div>

            <div style={{ background: "var(--cyan-bg)", padding: "10px 14px", borderRadius: "8px", border: "1px solid rgba(56, 189, 248, 0.3)" }}>
              <div style={{ fontSize: "0.72rem", color: "#7dd3fc", textTransform: "uppercase" }}>Open Tracking</div>
              <div style={{ fontSize: "1.35rem", fontWeight: 700, color: "var(--cyan)" }}>
                {overallAcc?.OPEN || 0}
              </div>
              <small style={{ fontSize: "0.72rem", color: "#7dd3fc" }}>Live Active</small>
            </div>

            <div style={{ background: "var(--card-subtle, #131c31)", padding: "10px 14px", borderRadius: "8px", border: "1px solid var(--line)" }}>
              <div style={{ fontSize: "0.72rem", color: "var(--muted)", textTransform: "uppercase" }}>CE / Upward Win Rate</div>
              <div style={{ fontSize: "1.35rem", fontWeight: 700, color: "var(--ink)" }}>
                {pct(acc?.by_direction?.UP?.hit_rate)}
              </div>
              <small style={{ fontSize: "0.72rem", color: "var(--muted)" }}>
                {acc?.by_direction?.UP?.TARGET_HIT || 0} / {acc?.by_direction?.UP?.decided || 0}
              </small>
            </div>

            <div style={{ background: "var(--card-subtle, #131c31)", padding: "10px 14px", borderRadius: "8px", border: "1px solid var(--line)" }}>
              <div style={{ fontSize: "0.72rem", color: "var(--muted)", textTransform: "uppercase" }}>PE / Downward Win Rate</div>
              <div style={{ fontSize: "1.35rem", fontWeight: 700, color: "var(--ink)" }}>
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
            background: "var(--card, #0f172a)",
            border: "1px solid var(--line)",
            borderRadius: "12px",
            padding: "18px 20px",
            boxShadow: "var(--shadow)",
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
              <div>
                <strong style={{ fontSize: "1.05rem", display: "block", color: "var(--ink, #f8fafc)" }}>Autonomous Bot Engine</strong>
                <small style={{ color: "var(--muted)" }}>Live tick polling &amp; auto-watchlist entry</small>
              </div>
              <button
                type="button"
                onClick={handleToggleAutoTrading}
                style={{
                  background: autoTradingEnabled ? "#16a34a" : "rgba(255, 255, 255, 0.12)",
                  color: "#ffffff",
                  border: autoTradingEnabled ? "none" : "1px solid var(--line)",
                  padding: "8px 18px",
                  borderRadius: "999px",
                  fontWeight: 700,
                  fontSize: "0.85rem",
                  cursor: "pointer",
                  transition: "all 0.2s",
                }}
              >
                {autoTradingEnabled ? "● AUTO-TRADING ON" : "○ AUTO-TRADING OFF"}
              </button>
            </div>
            <div style={{ fontSize: "0.82rem", color: "var(--muted)", lineHeight: 1.5, background: "var(--card-subtle, #131c31)", border: "1px solid var(--line)", padding: "10px 12px", borderRadius: "8px", marginBottom: "8px" }}>
              {autoTradingEnabled ? (
                <>🟢 <strong style={{ color: "var(--ink, #f8fafc)" }}>Bot is actively polling.</strong> Multi-agent breakout signals are auto-added to Watchlist and simulated without manual approval.</>
              ) : (
                <>⏸️ <strong style={{ color: "var(--ink, #f8fafc)" }}>Bot is in manual standby.</strong> Use "+ Add to Watchlist &amp; Auto-Track" on any instrument below to benchmark precision.</>
              )}
            </div>
            <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "0.8rem", color: "var(--muted)", cursor: "pointer" }}>
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
            background: "var(--card, #0f172a)",
            border: "1px solid var(--line)",
            borderRadius: "12px",
            padding: "18px 20px",
            boxShadow: "var(--shadow)",
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
              <div>
                <strong style={{ fontSize: "1.05rem", display: "block", color: "var(--ink, #f8fafc)" }}>Execution Environment</strong>
                <small style={{ color: "var(--muted)" }}>Choose between Paper Simulation and Live Broker</small>
              </div>
              <div style={{ display: "flex", background: "var(--card-subtle, #131c31)", border: "1px solid var(--line)", borderRadius: "999px", padding: "3px" }}>
                <button
                  type="button"
                  onClick={() => handleSwitchMode("PAPER")}
                  style={{
                    background: executionMode === "PAPER" ? "rgba(255, 255, 255, 0.15)" : "transparent",
                    color: executionMode === "PAPER" ? "#ffffff" : "var(--muted)",
                    boxShadow: executionMode === "PAPER" ? "0 1px 2px rgba(0,0,0,0.3)" : "none",
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
                    color: executionMode === "LIVE" ? "#ffffff" : "var(--muted)",
                    boxShadow: executionMode === "LIVE" ? "0 1px 2px rgba(0,0,0,0.3)" : "none",
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
            <div style={{ fontSize: "0.82rem", color: "var(--muted)", lineHeight: 1.5, background: "var(--card-subtle, #131c31)", border: "1px solid var(--line)", padding: "10px 12px", borderRadius: "8px" }}>
              Current: <strong style={{ color: executionMode === "LIVE" ? "#f43f5e" : "#10b981" }}>{executionMode === "LIVE" ? "Live Account (Real Capital)" : "Paper Simulation (Safe ₹10L Sandbox)"}</strong>. Sizing capped at <strong style={{ color: "var(--ink, #f8fafc)" }}>{maxLots} lot</strong> per trade.
            </div>
          </div>

          {/* Card 3: Emergency Kill Switch */}
          <div style={{
            background: "var(--red-bg, rgba(244, 63, 94, 0.12))",
            border: "1px solid rgba(244, 63, 94, 0.3)",
            borderRadius: "12px",
            padding: "18px 20px",
            boxShadow: "var(--shadow)",
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
              <div>
                <strong style={{ fontSize: "1.05rem", color: "#fda4af", display: "block" }}>Safety Circuit Breaker</strong>
                <small style={{ color: "#fecdd3" }}>Instant emergency square-off &amp; kill switch</small>
              </div>
              {!killSwitchTriggered ? (
                <button
                  type="button"
                  onClick={handleKillSwitch}
                  disabled={killSwitchBusy}
                  style={{
                    background: "#e11d48",
                    color: "#ffffff",
                    border: "none",
                    padding: "8px 16px",
                    borderRadius: "8px",
                    fontWeight: 700,
                    fontSize: "0.82rem",
                    cursor: "pointer",
                    boxShadow: "0 2px 4px rgba(225, 29, 72, 0.4)",
                  }}
                >
                  🛑 KILL SWITCH
                </button>
              ) : (
                <button
                  type="button"
                  onClick={handleResetKillSwitch}
                  disabled={killSwitchBusy || Boolean(serverHalt?.external_halt?.halted)}
                  title={serverHalt?.external_halt?.halted ? "Out-of-band halt active: clear the halt file or GPIO input first" : "Clear the server kill switch"}
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
            <div style={{ fontSize: "0.82rem", color: "#fecdd3", lineHeight: 1.5 }}>
              {killSwitchTriggered ? (
                <strong style={{ color: "#ffffff" }}>Engine locked. New entries blocked; exits still allowed. Reset to resume.</strong>
              ) : (
                <>Max daily loss threshold: <strong style={{ color: "#ffffff" }}>₹{dailyLossLimit.toLocaleString("en-IN")}</strong>. Mandatory stop-loss enforced on all trades.</>
              )}
              <div data-testid="server-kill-switch-status" style={{ marginTop: "6px", fontSize: "0.76rem" }}>
                Server switch:{" "}
                <strong style={{ color: "#ffffff" }}>
                  {serverHalt == null ? "unknown" : serverHalt.kill_switch == null ? "UNKNOWN (entries blocked)" : serverHalt.kill_switch ? "TRIPPED" : "clear"}
                </strong>
                {" · "}Out-of-band halt:{" "}
                <strong style={{ color: "#ffffff" }}>
                  {serverHalt?.external_halt?.halted ? `ACTIVE (${serverHalt.external_halt.reasons.join(", ")})` : serverHalt ? "clear" : "unknown"}
                </strong>
              </div>
            </div>
          </div>
        </div>

        {/* Tradable Underlyings Bot Matrix with Live Analysis */}
        <div style={{ marginBottom: "24px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
            <h2 style={{ fontSize: "1.2rem", fontWeight: 700, margin: 0, color: "var(--ink, #f8fafc)" }}>
              Live Data &amp; Multi-Agent Analysis (Auto-Add to Trading)
            </h2>
            <button
              type="button"
              onClick={fetchAnalysis}
              disabled={analysisLoading}
              title="Fetches fresh live quotes from Groww API and recalculates multi-agent analysis signals on the latest spot prices"
              style={{
                background: "var(--card, #0f172a)",
                color: "var(--ink, #f8fafc)",
                border: "1px solid var(--line)",
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
              const isGated = rec?.is_actionable === false || rec?.call?.includes("STAND ASIDE") || analysisData?.decision === "NO_TRADE";
              const isFutures = rec?.contract_type === "FUTURES" || COMMODITY_SET.has(u.symbol);
              const topPick = rec?.top_5_options?.[2] || rec?.top_5_options?.[0];
              const plannedPick = isFutures
                ? (rec?.contract || `${u.symbol} FUTURES`)
                : (topPick?.contract || `${u.symbol} ATM`);
              const side = isGated
                ? (rec?.call || "STAND ASIDE (NO TRADE)")
                : (isFutures
                    ? (rec?.call?.includes("SELL") ? "SELL_FUT" : "BUY_FUT")
                    : (rec?.option_type === "PE" ? "BUY_PE" : "BUY_CE"));
              const targetSpot = rec?.target_spot;
              const stopLossSpot = rec?.stop_loss_spot;
              const expPts = rec?.expected_move_points;
              const slPts = rec?.stop_loss_points;
              const estPrice = topPick?.is_live_quote ? topPick.entry_premium ?? null : null;

              return (
                <div
                  key={u.symbol}
                  style={{
                    background: "var(--card, #0f172a)",
                    border: isGated ? "1px solid rgba(244, 63, 94, 0.3)" : "1px solid var(--line)",
                    borderRadius: "12px",
                    padding: "16px 18px",
                    boxShadow: "var(--shadow)",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "10px" }}>
                    <div>
                      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                        <strong style={{ fontSize: "1.1rem", color: "var(--ink, #f8fafc)" }}>{u.name}</strong>
                        <span style={{ fontSize: "0.75rem", color: "var(--muted)", background: "rgba(255, 255, 255, 0.08)", border: "1px solid var(--line)", padding: "2px 6px", borderRadius: "4px" }}>{u.exchange}</span>
                        {isFutures && (
                          <span style={{ fontSize: "0.7rem", color: "#38bdf8", background: "rgba(56, 189, 248, 0.15)", border: "1px solid rgba(56, 189, 248, 0.3)", padding: "2px 6px", borderRadius: "4px", fontWeight: 700 }}>
                            ⚡ FUTURES
                          </span>
                        )}
                      </div>
                      <div style={{ fontSize: "1.25rem", fontWeight: 700, color: "var(--ink, #f8fafc)", marginTop: "2px" }}>
                        {spotText}
                        {rec?.reference_spot != null && (
                          <span style={{ display: "inline-block", marginLeft: "8px", fontSize: "0.72rem", color: "var(--muted)", fontWeight: 500 }}>
                            (Ref: ₹{Number(rec.reference_spot).toLocaleString("en-IN")})
                          </span>
                        )}
                        {!u.session.isOpen && (
                          <span style={{ display: "block", fontSize: "0.68rem", color: "var(--muted)", fontWeight: 500, marginTop: "1px" }}>
                            Official Close · Context Retained
                          </span>
                        )}
                      </div>
                    </div>

                    <span style={{
                      background: u.session.isOpen
                        ? (u.session.freshness === "STALE" ? "var(--amber-bg, rgba(245, 158, 11, 0.15))" : "var(--green-bg, rgba(16, 185, 129, 0.15))")
                        : u.session.sessionPhase === "POST_CLOSE" ? "rgba(139, 92, 246, 0.18)" : "var(--card-subtle, #131c31)",
                      color: u.session.isOpen
                        ? (u.session.freshness === "STALE" ? "#fbbf24" : "#34d399")
                        : u.session.sessionPhase === "POST_CLOSE" ? "#c4b5fd" : "var(--muted)",
                      border: `1px solid ${
                        u.session.isOpen
                          ? (u.session.freshness === "STALE" ? "rgba(245, 158, 11, 0.3)" : "rgba(16, 185, 129, 0.3)")
                          : u.session.sessionPhase === "POST_CLOSE" ? "rgba(139, 92, 246, 0.3)" : "var(--line)"
                      }`,
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
                  <div style={{ fontSize: "0.82rem", background: "var(--card-subtle, #131c31)", border: "1px solid var(--line)", padding: "10px", borderRadius: "8px", marginBottom: "12px", lineHeight: 1.5 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "3px" }}>
                      <span style={{ color: "var(--muted)" }}>Multi-Agent Bias:</span>
                      <strong style={{
                        color: isGated ? "#f87171" : rec?.bias?.includes("BULLISH") ? "#34d399" : rec?.bias?.includes("BEARISH") ? "#f87171" : "#60a5fa"
                      }}>
                        {isGated ? (rec?.conviction || "STAND ASIDE (NO TRADE)") : (rec?.bias || "AWAITING TRIGGER")}
                      </strong>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "3px" }}>
                      <span style={{ color: "var(--muted)" }}>Planned Contract:</span>
                      <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                        <strong style={{ color: "#38bdf8" }}>{plannedPick}</strong>
                        {!isFutures && topPick?.expiry_date && (
                          <span style={{ display: "inline-block", background: "rgba(56, 189, 248, 0.15)", color: "#38bdf8", padding: "1px 5px", borderRadius: "3px", fontSize: "0.68rem", fontWeight: 700 }}>
                            Exp: {formatExpiry(topPick.expiry_date)}
                          </span>
                        )}
                      </div>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "3px" }}>
                      <span style={{ color: "var(--muted)" }}>Execution Signal:</span>
                      <strong style={{ color: isGated ? "#f87171" : side.includes("BUY") ? "#34d399" : "#f87171" }}>
                        {side}
                      </strong>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.76rem", color: "var(--muted)", borderTop: "1px dashed var(--line)", paddingTop: "4px", marginTop: "4px" }}>
                      <span>
                        Target:{" "}
                        <strong style={{ color: "var(--ink, #f8fafc)" }}>
                          {isGated
                            ? "— (Gated)"
                            : targetSpot != null
                            ? `₹${Number(targetSpot).toLocaleString("en-IN")}${expPts != null ? ` (+${expPts} pts ref)` : ""}${u.spot ? ` | ${targetSpot > u.spot ? "+" : ""}${(targetSpot - u.spot).toFixed(1)} live` : ""}`
                            : expPts != null
                            ? `+${expPts} pts`
                            : "Awaiting feed"}
                        </strong>
                      </span>
                      <span>
                        Stop:{" "}
                        <strong style={{ color: "var(--ink, #f8fafc)" }}>
                          {isGated
                            ? "— (Gated)"
                            : stopLossSpot != null
                            ? `₹${Number(stopLossSpot).toLocaleString("en-IN")}${slPts != null ? ` (-${slPts} pts ref)` : ""}${u.spot ? ` | ${(stopLossSpot - u.spot).toFixed(1)} live` : ""}`
                            : slPts != null
                            ? `-${slPts} pts`
                            : "Awaiting feed"}
                        </strong>
                      </span>
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
                          disabled={killSwitchTriggered || isGated}
                          style={{
                            flex: 1,
                            background: (killSwitchTriggered || isGated)
                              ? "rgba(255, 255, 255, 0.08)"
                              : isOrderOpen
                              ? "rgba(56, 189, 248, 0.2)"
                              : "rgba(255, 255, 255, 0.12)",
                            color: (killSwitchTriggered || isGated) ? "var(--muted)" : "#ffffff",
                            border: isOrderOpen ? "1px solid #38bdf8" : "1px solid var(--line)",
                            padding: "8px 12px",
                            borderRadius: "8px",
                            fontSize: "0.82rem",
                            fontWeight: 600,
                            cursor: (killSwitchTriggered || isGated) ? "not-allowed" : "pointer",
                          }}
                        >
                          {isGated
                            ? `🔒 Gated (${rec?.conviction || "NO TRADE"})`
                            : isOrderOpen
                            ? `⚡ Active Order (${executionMode})`
                            : `⚡ Fire & Auto-Add (${executionMode})`}
                        </button>
                        <button
                          type="button"
                          disabled={isGated}
                          onClick={async () => {
                            if (isGated) return;
                            if (isWatched) {
                              setActionNotice(`ℹ️ ${plannedPick} is already actively tracked in the Watchlist.`);
                              setTimeout(() => setActionNotice(""), 3500);
                              return;
                            }
                            const pick = rec?.top_5_options?.[2] || {
                              contract: plannedPick,
                              strike: rec?.atm_strike ?? null,
                              option_type: side.includes("PE") ? "PE" : "CE",
                            };
                            const ok = await addTradeToWatchlist(u.symbol, pick, rec);
                            if (ok) {
                              setActionNotice(`✅ Added to Watchlist: ${plannedPick}. Precision will be auto-scored.`);
                              setTimeout(() => setActionNotice(""), 4000);
                            }
                          }}
                          style={{
                            background: isWatched ? "rgba(16, 185, 129, 0.18)" : "transparent",
                            color: isGated ? "var(--muted)" : isWatched ? "#34d399" : "#10b981",
                            border: isWatched ? "1px solid #10b981" : "1px solid rgba(16, 185, 129, 0.4)",
                            padding: "8px 12px",
                            borderRadius: "8px",
                            fontSize: "0.8rem",
                            fontWeight: 600,
                            cursor: isGated ? "not-allowed" : "pointer",
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
          background: "var(--card, #0f172a)",
          border: "1px solid var(--line)",
          borderRadius: "12px",
          padding: "18px 20px",
          boxShadow: "var(--shadow)",
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px", flexWrap: "wrap", gap: "10px" }}>
            <div>
              <h2 style={{ fontSize: "1.15rem", fontWeight: 700, margin: 0, color: "var(--ink, #f8fafc)" }}>Execution Audit Log &amp; Tracked Trades</h2>
              <small style={{ color: "var(--muted)" }}>
                Real-time tracking of option trades with explicit Premium Targets, Stop-Losses, and underlying spot validation
              </small>
            </div>

            <div style={{ display: "flex", gap: "10px", alignItems: "center", flexWrap: "wrap" }}>
              {/* Source Switcher */}
              <div style={{ display: "flex", background: "var(--card-subtle, #131c31)", border: "1px solid var(--line)", borderRadius: "8px", padding: "3px" }}>
                <button
                  type="button"
                  onClick={() => setViewSource("WATCHLIST")}
                  style={{
                    background: viewSource === "WATCHLIST" ? "rgba(255, 255, 255, 0.15)" : "transparent",
                    color: viewSource === "WATCHLIST" ? "#ffffff" : "var(--muted)",
                    boxShadow: viewSource === "WATCHLIST" ? "0 1px 2px rgba(0,0,0,0.3)" : "none",
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
                    background: viewSource === "ORDERS" ? "rgba(255, 255, 255, 0.15)" : "transparent",
                    color: viewSource === "ORDERS" ? "#ffffff" : "var(--muted)",
                    boxShadow: viewSource === "ORDERS" ? "0 1px 2px rgba(0,0,0,0.3)" : "none",
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
                      background: activeTab === tab ? "rgba(255, 255, 255, 0.18)" : "transparent",
                      color: activeTab === tab ? "#ffffff" : "var(--muted)",
                      border: activeTab === tab ? "1px solid var(--line)" : "1px solid transparent",
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
                    background: "var(--red-bg, rgba(244, 63, 94, 0.15))",
                    color: "#fca5a5",
                    border: "1px solid rgba(244, 63, 94, 0.3)",
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
                    background: "var(--red-bg, rgba(244, 63, 94, 0.15))",
                    color: "#fca5a5",
                    border: "1px solid rgba(244, 63, 94, 0.3)",
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
                  <tr style={{ borderBottom: "2px solid var(--line)", color: "var(--muted)", fontSize: "0.75rem", textTransform: "uppercase" }}>
                    <th style={{ padding: "8px 10px" }}>Contract</th>
                    <th style={{ padding: "8px 10px" }}>Status</th>
                    <th style={{ padding: "8px 10px", background: "rgba(16, 185, 129, 0.1)", color: "#34d399" }}>Prem. Entry</th>
                    <th style={{ padding: "8px 10px", background: "rgba(56, 189, 248, 0.1)", color: "#38bdf8" }}>Running Prem.</th>
                    <th style={{ padding: "8px 10px", background: "rgba(16, 185, 129, 0.1)", color: "#34d399" }}>Prem. Target</th>
                    <th style={{ padding: "8px 10px", background: "rgba(244, 63, 94, 0.1)", color: "#f87171" }}>Prem. SL</th>
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
                      const pTarget = p.target != null ? Number(p.target) : null;
                      const pSL = p.stop_loss != null ? Number(p.stop_loss) : null;
                      const gainPct = pEntry && pTarget ? `+${(((pTarget - pEntry) / pEntry) * 100).toFixed(0)}%` : "";
                      const lossPct = pEntry && pSL ? `-${(((pEntry - pSL) / pEntry) * 100).toFixed(0)}%` : "";

                      const runningPrem = calcRunningPremium(w, spots);
                      const runDiffPct = (pEntry && runningPrem != null) ? (((runningPrem - pEntry) / pEntry) * 100) : null;
                      const isRunPos = runDiffPct != null && runDiffPct >= 0;

                      return (
                        <tr key={w.suggestion_id} style={{ borderBottom: "1px solid var(--line)", color: "var(--ink, #f8fafc)" }}>
                          <td style={{ padding: "10px 10px" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
                              <strong style={{ color: w.option_type === "CE" ? "#34d399" : "#f87171" }}>{w.contract}</strong>
                              {(w.contract_expiry || w.model_premiums?.expiry_date) && (
                                <span style={{
                                  display: "inline-block",
                                  background: "rgba(56, 189, 248, 0.15)",
                                  color: "#38bdf8",
                                  padding: "1px 5px",
                                  borderRadius: "4px",
                                  fontSize: "0.68rem",
                                  fontWeight: 700,
                                }}>
                                  Exp: {formatExpiry(w.contract_expiry || w.model_premiums?.expiry_date)}
                                </span>
                              )}
                            </div>
                            {w.trading_symbol && (
                              <small style={{ display: "block", color: "#38bdf8", fontWeight: 600, fontSize: "0.7rem" }}>
                                {w.trading_symbol}
                              </small>
                            )}
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
                          <td style={{ padding: "10px 10px", background: "rgba(16, 185, 129, 0.05)" }}>
                            <strong style={{ color: "var(--ink, #f8fafc)" }}>{inr(pEntry)}</strong>
                            {(p.is_live_quote || p.data_source === "GROWW_OPTION_CHAIN" || w.is_live_contract) && (
                              <small style={{ display: "block", color: "#34d399", fontSize: "0.68rem", fontWeight: 600 }}>
                                Groww Entry LTP
                              </small>
                            )}
                            {p.lot_size ? <small style={{ display: "block", color: "var(--muted)", fontSize: "0.7rem" }}>Lot {p.lot_size}</small> : null}
                          </td>
                          {/* Dedicated Running / Exit Premium Column */}
                          <td style={{ padding: "10px 10px", background: "rgba(56, 189, 248, 0.05)" }}>
                            {w.status === "OPEN" ? (
                              <>
                                <strong style={{ color: runDiffPct == null ? "inherit" : isRunPos ? "#34d399" : "#f87171" }}>
                                  {inr(runningPrem)}
                                </strong>
                                {runDiffPct != null && (
                                  <small style={{
                                    display: "block",
                                    color: isRunPos ? "#34d399" : "#f87171",
                                    fontWeight: 600,
                                    fontSize: "0.7rem",
                                  }}>
                                    {isRunPos ? "+" : ""}{runDiffPct.toFixed(1)}%
                                  </small>
                                )}
                                <small style={{
                                  display: "inline-block",
                                  fontSize: "0.65rem",
                                  padding: "1px 5px",
                                  borderRadius: "3px",
                                  background: w.live_option_premium ? "rgba(34, 197, 94, 0.15)" : "rgba(148, 163, 184, 0.15)",
                                  color: w.live_option_premium ? "#34d399" : "var(--muted)",
                                  fontWeight: 600,
                                  marginTop: "2px",
                                }}>
                                  {w.live_option_premium ? "Groww Live LTP" : "Model Est."}
                                </small>
                              </>
                            ) : w.status === "SL_HIT" ? (
                              <>
                                <strong style={{ color: "#f87171" }}>{inr(p.exit_premium || pSL)}</strong>
                                <small style={{ display: "block", color: "#f87171", fontWeight: 700, fontSize: "0.7rem" }}>
                                  {p.exit_premium ? "Realized Exit" : (lossPct || "-25% Exit")}
                                </small>
                                {runningPrem != null && (
                                  <small style={{ display: "block", color: "var(--muted)", fontSize: "0.68rem", marginTop: "2px" }} title="Current market option premium if held post-exit">
                                    Post-Exit: {inr(runningPrem)} ({isRunPos ? "+" : ""}{runDiffPct?.toFixed(1)}%)
                                  </small>
                                )}
                              </>
                            ) : w.status === "TARGET_HIT" ? (
                              <>
                                <strong style={{ color: "#34d399" }}>{inr(p.exit_premium || pTarget)}</strong>
                                <small style={{ display: "block", color: "#34d399", fontWeight: 700, fontSize: "0.7rem" }}>
                                  {p.exit_premium ? "Realized Exit" : (gainPct || "+40% Exit")}
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
                          {/* Dedicated Premium Target Column */}
                          <td style={{ padding: "10px 10px", background: "rgba(16, 185, 129, 0.05)" }}>
                            <strong style={{ color: "#34d399" }}>{inr(pTarget)}</strong>
                            {gainPct ? <small style={{ display: "block", color: "#6ee7b7", fontWeight: 600, fontSize: "0.7rem" }}>{gainPct}</small> : null}
                          </td>
                          {/* Dedicated Premium SL Column */}
                          <td style={{ padding: "10px 10px", background: "rgba(244, 63, 94, 0.05)" }}>
                            <strong style={{ color: "#f87171" }}>{inr(pSL)}</strong>
                            {lossPct ? <small style={{ display: "block", color: "#fda4af", fontWeight: 600, fontSize: "0.7rem" }}>{lossPct}</small> : null}
                          </td>
                          {/* Underlying Spot Levels */}
                          <td style={{ padding: "10px 10px", color: "var(--ink, #f8fafc)" }}>{inr(w.entry_spot)}</td>
                          <td style={{ padding: "10px 10px", color: "#34d399", fontWeight: 600 }}>{inr(w.target_spot)}</td>
                          <td style={{ padding: "10px 10px", color: "#f87171", fontWeight: 600 }}>{inr(w.stop_loss_spot)}</td>
                          <td style={{ padding: "10px 10px", color: "var(--ink, #f8fafc)" }}>
                            {w.status === "OPEN" ? (
                              <>
                                <strong>{inr(spots?.[w.instrument] ?? w.last_spot)}</strong>
                                <small style={{ display: "block", color: "var(--muted)", fontSize: "0.7rem" }}>{w.checks || 0} checks</small>
                              </>
                            ) : (
                              <>
                                <strong style={{ color: w.status === "TARGET_HIT" ? "#34d399" : "#f87171" }}>
                                  {inr(w.resolved_spot ?? w.last_spot)}
                                </strong>
                                <small style={{ display: "block", color: w.status === "TARGET_HIT" ? "#34d399" : "#f87171", fontWeight: 600, fontSize: "0.7rem" }}>
                                  {w.status === "TARGET_HIT" ? "Target Triggered" : "SL Triggered"}
                                </small>
                                {spots?.[w.instrument] != null && (
                                  <small style={{ display: "block", color: "var(--muted)", fontSize: "0.68rem" }}>
                                    Live: {inr(spots[w.instrument])}
                                  </small>
                                )}
                              </>
                            )}
                          </td>
                          <td style={{ padding: "10px 10px", color: "var(--ink, #f8fafc)" }}>
                            <small style={{ fontWeight: w.status !== "OPEN" ? 600 : 400 }}>
                              {w.status === "OPEN" ? `by ${ist(w.expires_at)}` : `${ist(w.resolved_at)} @ ${inr(w.resolved_spot)}`}
                            </small>
                          </td>
                          <td style={{ padding: "10px 10px" }}>
                            {w.status === "OPEN" ? (
                              <button
                                type="button"
                                style={{ fontSize: "0.72rem", padding: "3px 8px", borderRadius: "4px", border: "1px solid var(--line)", background: "var(--card-subtle, #131c31)", color: "var(--muted)", cursor: "pointer" }}
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
                      <td colSpan={12} style={{ padding: "28px 14px", textAlign: "center", color: "var(--muted)" }}>
                        No trades logged yet. Click <strong style={{ color: "var(--green, #10b981)" }}>+ Add to Watchlist &amp; Auto-Track</strong> above to benchmark a setup.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.84rem", textAlign: "left" }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid var(--line)", color: "var(--muted)", fontSize: "0.75rem", textTransform: "uppercase" }}>
                    <th style={{ padding: "8px 10px" }}>Time</th>
                    <th style={{ padding: "8px 10px" }}>Order ID</th>
                    <th style={{ padding: "8px 10px" }}>Instrument</th>
                    <th style={{ padding: "8px 10px" }}>Contract</th>
                    <th style={{ padding: "8px 10px" }}>Side</th>
                    <th style={{ padding: "8px 10px" }}>Mode</th>
                    <th style={{ padding: "8px 10px" }}>Prem. Entry ₹</th>
                    <th style={{ padding: "8px 10px", color: "#34d399" }}>Prem. Target ₹</th>
                    <th style={{ padding: "8px 10px", color: "#f87171" }}>Prem. SL ₹</th>
                    <th style={{ padding: "8px 10px" }}>Status</th>
                    <th style={{ padding: "8px 10px", textAlign: "right" }}>P&amp;L ₹</th>
                  </tr>
                </thead>
                <tbody>
                  {orders
                    .filter((o) => activeTab === "ALL" || (activeTab === "OPEN" ? o.status === "OPEN" : o.status !== "OPEN"))
                    .map((o) => (
                      <tr key={o.id} style={{ borderBottom: "1px solid var(--line)", color: "var(--ink, #f8fafc)" }}>
                        <td style={{ padding: "10px 10px", color: "var(--muted)" }}>{o.time}</td>
                        <td style={{ padding: "10px 10px", fontFamily: "monospace", color: "var(--ink, #f8fafc)" }}>{o.id}</td>
                        <td style={{ padding: "10px 10px", fontWeight: 600, color: "var(--ink, #f8fafc)" }}>{o.instrument}</td>
                        <td style={{ padding: "10px 10px", color: "var(--ink, #f8fafc)" }}>{o.contract}</td>
                        <td style={{ padding: "10px 10px" }}>
                          <span style={{
                            background: o.side.includes("BUY") ? "rgba(16, 185, 129, 0.15)" : "rgba(244, 63, 94, 0.15)",
                            color: o.side.includes("BUY") ? "#34d399" : "#f87171",
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
                            background: o.mode === "LIVE" ? "rgba(244, 63, 94, 0.15)" : "rgba(255, 255, 255, 0.08)",
                            color: o.mode === "LIVE" ? "#f87171" : "var(--muted)",
                            padding: "2px 6px",
                            borderRadius: "4px",
                            fontSize: "0.72rem",
                            fontWeight: 600,
                          }}>
                            {o.mode}
                          </span>
                        </td>
                        <td style={{ padding: "10px 10px", color: "var(--ink, #f8fafc)" }}><strong>{o.entry != null ? `₹${o.entry.toFixed(2)}` : "—"}</strong></td>
                        <td style={{ padding: "10px 10px", color: "#34d399", fontWeight: 600 }}>{o.target != null ? `₹${o.target.toFixed(2)}` : "—"}</td>
                        <td style={{ padding: "10px 10px", color: "#f87171", fontWeight: 600 }}>{o.sl != null ? `₹${o.sl.toFixed(2)}` : "—"}</td>
                        <td style={{ padding: "10px 10px" }}>
                          <span style={{
                            background: o.status === "OPEN" ? "rgba(56, 189, 248, 0.15)" : "rgba(255, 255, 255, 0.08)",
                            color: o.status === "OPEN" ? "#38bdf8" : "var(--muted)",
                            padding: "2px 6px",
                            borderRadius: "4px",
                            fontSize: "0.75rem",
                            fontWeight: 600,
                          }}>
                            {o.status}
                          </span>
                        </td>
                        <td style={{ padding: "10px 10px", textAlign: "right", fontWeight: 700, color: (o.pnl || 0) >= 0 ? "#34d399" : "#f87171" }}>
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
          background: "rgba(0, 0, 0, 0.75)",
          backdropFilter: "blur(4px)",
          display: "grid",
          placeItems: "center",
          zIndex: 9999,
          padding: "20px",
        }}>
          <div style={{
            background: "var(--card, #0f172a)",
            border: "1px solid var(--line)",
            borderRadius: "14px",
            padding: "24px",
            maxWidth: "480px",
            width: "100%",
            boxShadow: "var(--shadow)",
          }}>
            <h3 style={{ fontSize: "1.25rem", margin: "0 0 10px", color: "#fda4af" }}>
              ⚠️ Activate Live Broker Order Routing?
            </h3>
            <p style={{ fontSize: "0.88rem", color: "var(--ink, #f8fafc)", lineHeight: 1.5, marginBottom: "16px" }}>
              You are about to switch the execution engine to <strong>Live Broker Mode</strong>. When enabled, any manual or autonomous triggers will route live orders to your Groww trading account using real funds.
            </p>
            <ul style={{ fontSize: "0.84rem", color: "var(--muted)", paddingLeft: "20px", marginBottom: "20px", lineHeight: 1.6 }}>
              <li>Maximum 1 lot per trade enforced.</li>
              <li>Hard stop-loss automatically attached to every order.</li>
              <li>Emergency kill switch available at all times.</li>
            </ul>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: "10px" }}>
              <button
                type="button"
                onClick={() => setShowLiveConfirmModal(false)}
                style={{
                  background: "var(--card-subtle, #131c31)",
                  color: "var(--ink, #f8fafc)",
                  border: "1px solid var(--line)",
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
