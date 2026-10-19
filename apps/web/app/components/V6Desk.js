"use client";

import { useEffect, useState } from "react";

import { useRead } from "./useRead";
import { valueText } from "../research/present.mjs";
import { csrf } from "./ResearchBoard";
import { useMarketData } from "./MarketDataContext";
import NewsSourcesManager from "./NewsSourcesManager";
import PredictedTrendChart from "./PredictedTrendChart";

const INDICES_CHOICES = [
  { id: "NIFTY", label: "NIFTY", desc: "NSE Spot Index" },
  { id: "SENSEX", label: "SENSEX", desc: "BSE Spot Index" },
];

const COMMODITY_CHOICES = [
  { id: "CRUDEOILMINI", label: "Crude Mini", desc: "MCX Crude Oil Mini (10 bbl)" },
  { id: "GOLDMINI", label: "Gold Mini", desc: "MCX Gold Mini (100g)" },
  { id: "SILVERMINI", label: "Silver Mini", desc: "MCX Silver Mini (5kg)" },
  { id: "NATURALGASMINI", label: "NG Mini", desc: "MCX Natural Gas Mini" },
];

const GLOBAL_CHOICES = [
  { id: "GIFTNIFTY", label: "GIFT Nifty", desc: "NSE IX International" },
  { id: "DJI", label: "Dow Jones", desc: "US Dow Jones Industrial" },
  { id: "NIFTYIT", label: "NIFTY IT", desc: "IT Sectoral Index" },
  { id: "BANKEX", label: "BSE BANKEX", desc: "BSE Bank Sectoral" },
];

const ALL_CHOICES = [
  ...INDICES_CHOICES.map((c) => c.id),
  ...COMMODITY_CHOICES.map((c) => c.id),
  ...GLOBAL_CHOICES.map((c) => c.id),
];
const CHOICES = INDICES_CHOICES.map((c) => c.id);

function formatQuoteChange(q) {
  if (!q.ohlc || typeof q.ohlc.close !== "number" || q.ohlc.close <= 0) return null;
  const diff = q.last_price - q.ohlc.close;
  const pct = (diff / q.ohlc.close) * 100;
  const sign = diff >= 0 ? "+" : "";
  const color = diff >= 0 ? "#16a34a" : "#dc2626";
  return {
    diffFormatted: `${sign}₹${Math.abs(diff).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
    pctFormatted: `${sign}${pct.toFixed(2)}%`,
    color,
    isPositive: diff >= 0,
  };
}

function formatIST(isoStr) {
  if (!isoStr) return "";
  try {
    const d = new Date(isoStr);
    return d.toLocaleString("en-IN", {
      timeZone: "Asia/Kolkata",
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      hour12: true,
    }) + " IST";
  } catch {
    return isoStr;
  }
}

const COMMODITY_SET = new Set([
  "CRUDE", "CRUDEMINI", "CRUDEOILMINI", "GOLD", "GOLDMINI", "SILVER", "SILVERMINI", "NATURALGAS", "NATURALGASMINI"
]);

function getMarketSessionInfo(instrument) {
  try {
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

    const isCommodity = COMMODITY_SET.has(instrument);

    if (isCommodity) {
      // MCX Trading Hours: 09:00 - 23:30 IST (Mon-Fri)
      const openMinutes = 9 * 60; // 09:00
      const closeMinutes = 23 * 60 + 30; // 23:30
      const isOpen = !isWeekend && totalMinutes >= openMinutes && totalMinutes < closeMinutes;
      const nextOpenText = isWeekend || (weekday === "Fri" && totalMinutes >= closeMinutes)
        ? "Monday at 09:00 AM IST"
        : totalMinutes < openMinutes
        ? "Today at 09:00 AM IST"
        : "Tomorrow at 09:00 AM IST";

      return {
        isOpen,
        exchange: "MCX",
        marketName: "MCX Commodity Market",
        hours: "09:00 AM – 11:30 PM IST",
        closeTimeText: "11:30 PM IST",
        nextOpenText,
      };
    }

    // Default: NSE / BSE Equity Hours: 09:15 - 15:30 IST (Mon-Fri)
    const openMinutes = 9 * 60 + 15; // 09:15
    const closeMinutes = 15 * 60 + 30; // 15:30
    const isOpen = !isWeekend && totalMinutes >= openMinutes && totalMinutes < closeMinutes;
    const nextOpenText = isWeekend || (weekday === "Fri" && totalMinutes >= closeMinutes)
      ? "Monday at 09:15 AM IST"
      : totalMinutes < openMinutes
      ? "Today at 09:15 AM IST"
      : "Tomorrow at 09:15 AM IST";

    return {
      isOpen,
      exchange: "NSE / BSE",
      marketName: "Indian Equity Market",
      hours: "09:15 AM – 03:30 PM IST",
      closeTimeText: "03:30 PM IST",
      nextOpenText,
    };
  } catch {
    return {
      isOpen: false,
      exchange: "Market",
      marketName: "Exchange",
      hours: "Standard Hours",
      closeTimeText: "Session End",
      nextOpenText: "Next Trading Session",
    };
  }
}

function isAnyMarketOpenIST() {
  return getMarketSessionInfo("NIFTY").isOpen || getMarketSessionInfo("CRUDEOILMINI").isOpen;
}

function isMarketOpenIST() {
  return isAnyMarketOpenIST();
}

export default function V6Desk({ defaultTab = "trades", hideTickers = false } = {}) {
  const [selected, setSelected] = useState(CHOICES);
  const [commentary, setCommentary] = useState(false);
  const [quantFusion, setQuantFusion] = useState(true);
  const [showForecastChart, setShowForecastChart] = useState(true);
  const [phase, setPhase] = useState("idle");
  const [error, setError] = useState("");
  const [report, setReport] = useState(null);
  const [tab, setTab] = useState("dossier");
  const [deskTab, setDeskTab] = useState(defaultTab);
  const [showTickerFeed, setShowTickerFeed] = useState(!hideTickers);
  const forecasts = useRead("/api/forecasts?live=true");
  const news = useRead("/api/news");
  const approved = forecasts.body?.forecasts || [];
  const [newsPhase, setNewsPhase] = useState("idle");
  const [newsError, setNewsError] = useState("");
  const [showNewsConfig, setShowNewsConfig] = useState(false);
  const marketData = useMarketData();
  const [quotesPhase, setQuotesPhase] = useState("idle");
  const [quotesError, setQuotesError] = useState("");

  const quotesList = marketData.quotes || [];
  const commoditiesList = marketData.commodities || [];
  const globalIndicesList = marketData.globalIndices || [];
  const sectoralIndicesList = marketData.sectoralIndices || [];
  const retrievedAtText = formatIST(marketData.retrievedAt || quotesList[0]?.retrieved_at);
  const [feedCategoryFilter, setFeedCategoryFilter] = useState("ALL");
  const [feedIndexFilter, setFeedIndexFilter] = useState("ALL");
  const [autoRun, setAutoRun] = useState(false);
  const [autoRunIntervalSec, setAutoRunIntervalSec] = useState(60);

  useEffect(() => {
    try {
      const savedAuto = localStorage.getItem("imm_auto_run_analysis");
      if (savedAuto !== null) setAutoRun(savedAuto === "true");
      const savedSec = localStorage.getItem("imm_analysis_interval_sec");
      if (savedSec) {
        const parsed = parseInt(savedSec, 10);
        if (!isNaN(parsed) && parsed >= 15) setAutoRunIntervalSec(parsed);
      }
    } catch (_) {}
  }, []);

  function updateAutoRun(nextVal) {
    setAutoRun(nextVal);
    try {
      localStorage.setItem("imm_auto_run_analysis", String(nextVal));
    } catch (_) {}
  }

  function updateAutoRunInterval(nextSec) {
    const val = Number(nextSec) || 60;
    setAutoRunIntervalSec(val);
    try {
      localStorage.setItem("imm_analysis_interval_sec", String(val));
    } catch (_) {}
  }

  function toggle(name) {
    setSelected((current) => (current.includes(name) ? current.filter((item) => item !== name) : [...current, name]));
  }

  function toggleAll() {
    if (selected.length === ALL_CHOICES.length) {
      setSelected(INDICES_CHOICES.map((c) => c.id));
    } else {
      setSelected([...ALL_CHOICES]);
    }
  }

  function selectIndicesOnly() {
    setSelected(INDICES_CHOICES.map((c) => c.id));
  }

  function selectCommoditiesOnly() {
    setSelected(COMMODITY_CHOICES.map((c) => c.id));
  }

  async function fetchLiveQuotes() {
    setQuotesPhase("loading");
    setQuotesError("");
    try {
      await marketData.refreshNow();
      setQuotesPhase("ready");
    } catch (err) {
      setQuotesPhase("error");
      setQuotesError(err instanceof Error ? err.message : String(err));
    }
  }

  async function run(event) {
    event?.preventDefault?.();
    setPhase("loading");
    setError("");
    try {
      if ((marketData.quotes || []).length === 0) {
        try {
          await marketData.refreshNow();
        } catch (_) {}
      }

      const response = await fetch("/api/market-analysis", {
        method: "POST",
        headers: { "content-type": "application/json", "x-csrf-token": csrf() },
        body: JSON.stringify({
          instruments: selected,
          horizon: "INTRADAY",
          include_news: true,
          include_macro: true,
          include_derivatives: true,
          include_inference: commentary,
          include_forecast: quantFusion,
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        setReport(null);
        setPhase("error");
        setError(body.message || body.code || "The assessment could not be run.");
        return;
      }
      setReport(body);
      setPhase("ready");
      setDeskTab("trades");
    } catch (err) {
      setReport(null);
      setPhase("error");
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    if (!autoRun || selected.length === 0) return undefined;
    const intervalMs = Math.max(15000, (Number(autoRunIntervalSec) || 60) * 1000);
    const id = setInterval(() => {
      if (phase !== "loading") {
        run();
      }
    }, intervalMs);
    return () => clearInterval(id);
  }, [autoRun, autoRunIntervalSec, selected, commentary, quantFusion, phase]);

  async function fetchNews() {
    setNewsPhase("loading");
    setNewsError("");
    try {
      const response = await fetch("/api/news/refresh", {
        method: "POST",
        headers: { "content-type": "application/json", "x-csrf-token": csrf() },
        body: JSON.stringify({ confirm: true }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        setNewsPhase("error");
        setNewsError(body.message || body.code || "The news feeds could not be read.");
        return;
      }
      setNewsPhase("ready");
      news.retry();
    } catch (err) {
      setNewsPhase("error");
      setNewsError(err instanceof Error ? err.message : String(err));
    }
  }

  const decision = report?.decision || "NO_TRADE";
  const intel = report?.intelligence || {};
  const callClass = (decision || "").toLowerCase().includes("bullish")
    ? "bullish"
    : (decision || "").toLowerCase().includes("bearish")
    ? "bearish"
    : "neutral";

  return (
    <section className="agent-desk" aria-labelledby="agents-heading">
      {/* 1. Professional Executive Command Console */}
      <div className="pro-console">
        {/* Live Market Feed Strip */}
        <section data-testid="live-market-feed" className="pro-ticker-strip">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px", marginBottom: "12px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
              <h3 style={{ margin: 0, fontSize: "0.95rem", fontWeight: 700 }}>Groww Live Market Feed</h3>
              <span
                style={{
                  fontSize: "0.72rem",
                  padding: "2px 8px",
                  borderRadius: "10px",
                  background: isAnyMarketOpenIST() ? "rgba(34, 197, 94, 0.12)" : "rgba(100, 116, 139, 0.12)",
                  color: isAnyMarketOpenIST() ? "#16a34a" : "var(--muted)",
                  fontWeight: 600,
                }}
              >
                {!isAnyMarketOpenIST()
                  ? "🌙 All Markets Closed · NSE (15:30) · MCX (23:30 IST)"
                  : getMarketSessionInfo("CRUDEOILMINI").isOpen && !getMarketSessionInfo("NIFTY").isOpen
                  ? "🟢 MCX Commodity Session Active (NSE Closed)"
                  : "🟢 Live Market Feed"}
              </span>
              {retrievedAtText ? (
                <span style={{ fontSize: "0.75rem", color: "var(--muted)", fontWeight: 500 }}>
                  · As of {retrievedAtText}
                </span>
              ) : null}
            </div>
            <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
              <button
                type="button"
                onClick={() => setShowTickerFeed((prev) => !prev)}
                style={{
                  padding: "4px 10px",
                  fontSize: "0.78rem",
                  background: "var(--card-subtle, #131c31)",
                  border: "1px solid var(--border)",
                  borderRadius: "6px",
                  color: "var(--ink)",
                  cursor: "pointer",
                }}
              >
                {showTickerFeed ? "Hide Market Tickers ▴" : "Show Market Tickers (15) ▾"}
              </button>
              <button type="button" onClick={fetchLiveQuotes} disabled={quotesPhase === "loading"} style={{ padding: "4px 12px", fontSize: "0.78rem" }}>
                {quotesPhase === "loading" ? "Fetching quotes…" : "Refresh Groww live quotes"}
              </button>
            </div>
          </div>
          {quotesPhase === "error" ? <p className="error" role="alert" style={{ marginTop: "4px", marginBottom: "8px" }}>{quotesError}</p> : null}
          {showTickerFeed && (
            <>
              {/* Feed Category & Filter Controls */}
              <div style={{ display: "flex", flexDirection: "column", gap: "8px", margin: "10px 0 14px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
                  <span style={{ fontSize: "0.72rem", fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginRight: "4px" }}>
                    Market Segments:
                  </span>
                  <button
                    type="button"
                    style={{
                      padding: "3px 10px",
                      fontSize: "0.75rem",
                      borderRadius: "6px",
                      border: "1px solid var(--border)",
                      background: feedCategoryFilter === "ALL" ? "#14211c" : "var(--surface)",
                      color: feedCategoryFilter === "ALL" ? "#fff" : "var(--ink)",
                      fontWeight: 650,
                      cursor: "pointer",
                    }}
                    onClick={() => { setFeedCategoryFilter("ALL"); setFeedIndexFilter("ALL"); }}
                  >
                    All Markets ({quotesList.length + commoditiesList.length + globalIndicesList.length})
                  </button>
                  <button
                    type="button"
                    style={{
                      padding: "3px 10px",
                      fontSize: "0.75rem",
                      borderRadius: "6px",
                      border: "1px solid var(--border)",
                      background: feedCategoryFilter === "INDICES" ? "#14211c" : "var(--surface)",
                      color: feedCategoryFilter === "INDICES" ? "#fff" : "var(--ink)",
                      fontWeight: 650,
                      cursor: "pointer",
                    }}
                    onClick={() => { setFeedCategoryFilter("INDICES"); setFeedIndexFilter("ALL"); }}
                  >
                    All Indices ({quotesList.filter((q) => q.instrument === "NIFTY" || q.instrument === "SENSEX").length})
                  </button>
                  <button
                    type="button"
                    style={{
                      padding: "3px 10px",
                      fontSize: "0.75rem",
                      borderRadius: "6px",
                      border: "1px solid var(--border)",
                      background: feedCategoryFilter === "COMMODITIES" ? "#14211c" : "var(--surface)",
                      color: feedCategoryFilter === "COMMODITIES" ? "#fff" : "var(--ink)",
                      fontWeight: 650,
                      cursor: "pointer",
                    }}
                    onClick={() => { setFeedCategoryFilter("COMMODITIES"); setFeedIndexFilter("ALL"); }}
                  >
                    ⚡ MCX Commodities ({commoditiesList.length || 4})
                  </button>
                  <button
                    type="button"
                    style={{
                      padding: "3px 10px",
                      fontSize: "0.75rem",
                      borderRadius: "6px",
                      border: "1px solid var(--border)",
                      background: feedCategoryFilter === "GLOBAL" ? "#14211c" : "var(--surface)",
                      color: feedCategoryFilter === "GLOBAL" ? "#fff" : "var(--ink)",
                      fontWeight: 650,
                      cursor: "pointer",
                    }}
                    onClick={() => { setFeedCategoryFilter("GLOBAL"); setFeedIndexFilter("ALL"); }}
                  >
                    🌐 Global Benchmarks ({globalIndicesList.length || 5})
                  </button>
                </div>

                {/* Sub-filter by specific index if in indices mode */}
                {feedCategoryFilter === "INDICES" || feedCategoryFilter === "ALL" ? (
                  <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap", fontSize: "0.72rem" }}>
                    <span style={{ color: "var(--muted)", fontWeight: 600 }}>Filter Index:</span>
                    <button
                      type="button"
                      style={{
                        padding: "2px 8px",
                        fontSize: "0.72rem",
                        borderRadius: "4px",
                        border: "1px solid var(--border)",
                        background: feedIndexFilter === "ALL" ? "rgba(0,0,0,0.08)" : "transparent",
                        color: "var(--ink)",
                        cursor: "pointer",
                      }}
                      onClick={() => setFeedIndexFilter("ALL")}
                    >
                      All
                    </button>
                    {quotesList.filter((q) => q.instrument === "NIFTY" || q.instrument === "SENSEX").map((q) => (
                      <button
                        key={q.instrument}
                        type="button"
                        style={{
                          padding: "2px 8px",
                          fontSize: "0.72rem",
                          borderRadius: "4px",
                          border: "1px solid var(--border)",
                          background: feedIndexFilter === q.instrument ? "rgba(0,0,0,0.08)" : "transparent",
                          color: "var(--ink)",
                          cursor: "pointer",
                        }}
                        onClick={() => setFeedIndexFilter(q.instrument)}
                      >
                        {q.instrument}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>

              <div style={{ display: "flex", gap: "12px", flexWrap: "wrap" }}>
                {/* 1. Domestic Index Quotes (NIFTY, SENSEX) */}
                {(feedCategoryFilter === "ALL" || feedCategoryFilter === "INDICES") &&
                  quotesList.filter((q) => q.instrument === "NIFTY" || q.instrument === "SENSEX").map((q) => {
                    if (feedIndexFilter !== "ALL" && feedIndexFilter !== q.instrument) return null;
                    const chg = formatQuoteChange(q);
                    return (
                      <div
                        key={q.instrument}
                        style={{
                          background: "var(--surface)",
                          padding: "10px 14px",
                          borderRadius: "8px",
                          border: "1px solid var(--border)",
                          minWidth: "200px",
                          flex: "1 1 220px",
                        }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "2px" }}>
                          <span style={{ fontSize: "0.75rem", color: "var(--muted)", fontWeight: 700, letterSpacing: "0.5px" }}>{q.instrument}</span>
                          <span
                            style={{
                              fontSize: "0.65rem",
                              padding: "1px 6px",
                              borderRadius: "4px",
                              background: marketData.isEquityOpen ? "rgba(22, 163, 74, 0.12)" : "rgba(100, 116, 139, 0.12)",
                              color: marketData.isEquityOpen ? "#16a34a" : "#64748b",
                              fontWeight: 600,
                            }}
                          >
                            {q.instrument === "NIFTY"
                              ? (marketData.isEquityOpen ? "NSE · LIVE" : "NSE · CLOSED")
                              : q.instrument === "SENSEX"
                              ? (marketData.isEquityOpen ? "BSE · LIVE" : "BSE · CLOSED")
                              : "MCX Commodity"}
                          </span>
                        </div>
                        <div style={{ display: "flex", alignItems: "baseline", gap: "8px", flexWrap: "wrap" }}>
                          <strong style={{ fontSize: "1.2rem", letterSpacing: "-0.5px" }}>
                            ₹{Number(q.last_price).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          </strong>
                          {chg ? (
                            <span style={{ fontSize: "0.78rem", fontWeight: 600, color: chg.color }}>
                              {chg.diffFormatted} ({chg.pctFormatted})
                            </span>
                          ) : q.day_change != null ? (
                            <span style={{ fontSize: "0.78rem", fontWeight: 600, color: (q.day_change || 0) >= 0 ? "#16a34a" : "#dc2626" }}>
                              {q.day_change > 0 ? `+₹${q.day_change}` : `-₹${Math.abs(q.day_change)}`} ({q.percent_change})
                            </span>
                          ) : null}
                        </div>
                        {q.ohlc ? (
                          <div style={{ fontSize: "0.68rem", color: "var(--muted)", marginTop: "6px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1px 8px" }}>
                            <span><strong>O:</strong> ₹{Number(q.ohlc.open).toLocaleString("en-IN", { minimumFractionDigits: 1 })}</span>
                            <span><strong>H:</strong> ₹{Number(q.ohlc.high).toLocaleString("en-IN", { minimumFractionDigits: 1 })}</span>
                            <span><strong>L:</strong> ₹{Number(q.ohlc.low).toLocaleString("en-IN", { minimumFractionDigits: 1 })}</span>
                            <span><strong>Prev:</strong> ₹{Number(q.ohlc.close).toLocaleString("en-IN", { minimumFractionDigits: 1 })}</span>
                          </div>
                        ) : (
                          <div style={{ fontSize: "0.68rem", color: "var(--muted)", marginTop: "6px" }}>
                            <span>{q.instrument === "SENSEX" ? "BSE CASH Spot Quote (Groww LTP)" : (q.instrument.includes("CRUDE") ? "MCX Live Commodity Feed" : "Live Market Feed")}</span>
                          </div>
                        )}
                      </div>
                    );
                  })}

                {/* 2. Domestic Sectoral & Indicator Feeds (India VIX, sector context) */}
                {(feedCategoryFilter === "ALL" || feedCategoryFilter === "INDICES") &&
                  sectoralIndicesList.map((s) => (
                    <div
                      key={s.instrument}
                      style={{
                        background: "var(--surface)",
                        padding: "10px 14px",
                        borderRadius: "8px",
                        border: "1px solid var(--border)",
                        minWidth: "200px",
                        flex: "1 1 210px",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "2px" }}>
                        <span style={{ fontSize: "0.75rem", color: "var(--muted)", fontWeight: 700, letterSpacing: "0.5px" }}>{s.name}</span>
                        <span
                          style={{
                            fontSize: "0.65rem",
                            padding: "1px 5px",
                            borderRadius: "4px",
                            background: s.instrument === "VIX" ? "rgba(239, 68, 68, 0.12)" : "rgba(99, 102, 241, 0.12)",
                            color: s.instrument === "VIX" ? "#dc2626" : "#4f46e5",
                            fontWeight: 600,
                          }}
                        >
                          {s.instrument === "VIX" ? "NSE Volatility" : "NSE Sectoral"}
                        </span>
                      </div>
                      <div style={{ display: "flex", alignItems: "baseline", gap: "8px", flexWrap: "wrap" }}>
                        <strong style={{ fontSize: "1.2rem", letterSpacing: "-0.5px" }}>
                          {s.instrument === "VIX" ? Number(s.last_price).toFixed(2) : `₹${Number(s.last_price).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`}
                        </strong>
                        {s.day_change_text ? (
                          <span style={{ fontSize: "0.78rem", fontWeight: 600, color: s.day_change_text.startsWith("-") ? "#dc2626" : "#16a34a" }}>
                            {s.day_change_text}
                          </span>
                        ) : null}
                      </div>
                      <div style={{ fontSize: "0.68rem", color: "var(--muted)", marginTop: "6px" }}>
                        <span>Groww Live Sectoral Feed · {formatIST(s.retrieved_at)}</span>
                      </div>
                    </div>
                  ))}

                {/* 3. MCX Commodities */}
                {(feedCategoryFilter === "ALL" || feedCategoryFilter === "COMMODITIES") &&
                  commoditiesList.map((c) => (
                    <div
                      key={c.instrument}
                      style={{
                        background: "var(--surface)",
                        padding: "10px 14px",
                        borderRadius: "8px",
                        border: "1px solid var(--border)",
                        minWidth: "200px",
                        flex: "1 1 210px",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "2px" }}>
                        <span style={{ fontSize: "0.75rem", color: "var(--muted)", fontWeight: 700, letterSpacing: "0.5px" }}>{c.name}</span>
                        <span
                          style={{
                            fontSize: "0.65rem",
                            padding: "1px 6px",
                            borderRadius: "4px",
                            background: marketData.isCommodityOpen ? "rgba(22, 163, 74, 0.12)" : "rgba(100, 116, 139, 0.12)",
                            color: marketData.isCommodityOpen ? "#16a34a" : "#64748b",
                            fontWeight: 600,
                          }}
                        >
                          {marketData.isCommodityOpen ? "MCX · LIVE" : "MCX · CLOSED"}
                        </span>
                      </div>
                      <div style={{ display: "flex", alignItems: "baseline", gap: "8px", flexWrap: "wrap" }}>
                        <strong style={{ fontSize: "1.2rem", letterSpacing: "-0.5px" }}>
                          ₹{Number(c.last_price).toLocaleString("en-IN", { minimumFractionDigits: 1, maximumFractionDigits: 2 })}
                        </strong>
                        {c.day_change != null ? (
                          <span style={{ fontSize: "0.78rem", fontWeight: 600, color: (c.day_change || 0) >= 0 ? "#16a34a" : "#dc2626" }}>
                            {c.day_change > 0 ? `+₹${c.day_change}` : `-₹${Math.abs(c.day_change)}`} ({c.percent_change})
                          </span>
                        ) : (
                          <span style={{ fontSize: "0.75rem", color: "var(--muted)", fontWeight: 500 }}>
                            {c.unit}
                          </span>
                        )}
                      </div>
                      <div style={{ fontSize: "0.68rem", color: "var(--muted)", marginTop: "6px" }}>
                        <span>MCX Live Feed ({c.unit}) · {formatIST(c.retrieved_at)}</span>
                      </div>
                    </div>
                  ))}

                {/* 4. Global Market Benchmarks (Non-Interval) */}
                {(feedCategoryFilter === "ALL" || feedCategoryFilter === "GLOBAL") &&
                  globalIndicesList.map((g) => (
                    <div
                      key={g.instrument}
                      style={{
                        background: "var(--surface)",
                        padding: "10px 14px",
                        borderRadius: "8px",
                        border: "1px solid var(--border)",
                        minWidth: "200px",
                        flex: "1 1 210px",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "2px" }}>
                        <span style={{ fontSize: "0.75rem", color: "var(--muted)", fontWeight: 700, letterSpacing: "0.5px" }}>{g.name}</span>
                        <span style={{ fontSize: "0.65rem", padding: "1px 5px", borderRadius: "4px", background: "rgba(59, 130, 246, 0.12)", color: "#2563eb", fontWeight: 600 }}>
                          Global Market
                        </span>
                      </div>
                      <div style={{ display: "flex", alignItems: "baseline", gap: "8px", flexWrap: "wrap" }}>
                        <strong style={{ fontSize: "1.2rem", letterSpacing: "-0.5px" }}>
                          {Number(g.last_price).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} {g.unit || "pts"}
                        </strong>
                        {g.percent_change ? (
                          <span style={{ fontSize: "0.78rem", fontWeight: 600, color: (g.day_change || 0) >= 0 ? "#16a34a" : "#dc2626" }}>
                            {g.day_change ? (g.day_change > 0 ? `+${g.day_change}` : `${g.day_change}`) : ""} ({g.percent_change})
                          </span>
                        ) : null}
                      </div>
                      <div style={{ fontSize: "0.68rem", color: "var(--muted)", marginTop: "6px" }}>
                        <span>Groww Global Feed · {formatIST(g.retrieved_at)}</span>
                      </div>
                    </div>
                  ))}
              </div>
            </>
          )}

        </section>

        {/* 1. Executive System & Engine Health Status Deck (Full-width 4-column ribbon) */}
        <div
          data-testid="system-health-overview"
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
            gap: "12px",
            marginBottom: "16px",
            width: "100%",
          }}
        >
          {/* 1. Market Quotes Feed (Public LTP Data) */}
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: "4px",
              background: "var(--card-subtle, #131c31)",
              border: "1px solid var(--border, rgba(255, 255, 255, 0.08))",
              borderRadius: "10px",
              padding: "12px 14px",
            }}
            title="Public and cached live quote snapshot reader (Indices & Commodities). Direct broker trading integration is configured under Settings -> Integrations."
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span style={{ fontSize: "0.72rem", fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Market Quotes Feed</span>
              <span style={{ fontSize: "0.7rem", fontWeight: 700, color: "#16a34a", background: "rgba(22, 163, 74, 0.12)", padding: "1px 6px", borderRadius: "4px" }}>
                🟢 {quotesList.length > 0 ? "Live Active" : "Polling"}
              </span>
            </div>
            <span style={{ fontSize: "0.95rem", fontWeight: 700, color: "var(--ink, #f8fafc)" }}>
              {quotesList.length + commoditiesList.length} Quotes Active
            </span>
            <span style={{ fontSize: "0.72rem", color: "var(--muted)" }}>
              Groww Public LTP · Auto-sync: {marketData.pollConfig?.intervalSeconds || 60}s · {retrievedAtText || "Live IST"}
            </span>
          </div>

          {/* 2. 12 Specialist Agents */}
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: "4px",
              background: "var(--card-subtle, #131c31)",
              border: "1px solid var(--border, rgba(255, 255, 255, 0.08))",
              borderRadius: "10px",
              padding: "12px 14px",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span style={{ fontSize: "0.72rem", fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Specialist Agents</span>
              <span style={{ fontSize: "0.7rem", fontWeight: 700, color: "#16a34a", background: "rgba(22, 163, 74, 0.12)", padding: "1px 6px", borderRadius: "4px" }}>
                🟢 12 Online
              </span>
            </div>
            <span style={{ fontSize: "0.95rem", fontWeight: 700, color: "var(--ink, #f8fafc)" }}>
              Deterministic Consensus
            </span>
            <span style={{ fontSize: "0.72rem", color: "var(--muted)" }}>
              News Wire ({news.body?.items?.length || 39}) · Macro (8) · Tech
            </span>
          </div>

          {/* 3. AI Inference & Commentary */}
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: "4px",
              background: "var(--card-subtle, #131c31)",
              border: "1px solid var(--border, rgba(255, 255, 255, 0.08))",
              borderRadius: "10px",
              padding: "12px 14px",
            }}
            title="Consensus engine runs mathematical quant, volatility, and technical indicators deterministically without LLMs. OpenAI provides optional narrative commentary when enabled."
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span style={{ fontSize: "0.72rem", fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>AI Commentary</span>
              <span style={{ fontSize: "0.7rem", fontWeight: 700, color: commentary ? "#2563eb" : "var(--muted)", background: commentary ? "rgba(37, 99, 235, 0.12)" : "rgba(100, 116, 139, 0.12)", padding: "1px 6px", borderRadius: "4px" }}>
                {commentary ? "🟢 In-Loop" : "⚪ Standby"}
              </span>
            </div>
            <span style={{ fontSize: "0.95rem", fontWeight: 700, color: "var(--ink, #f8fafc)" }}>
              {commentary ? "LLM Commentary Active" : "Deterministic Quant Active"}
            </span>
            <span style={{ fontSize: "0.72rem", color: "var(--muted)" }}>
              {commentary ? "Structured LLM narrative generated" : "Zero-hallucination deterministic guard"}
            </span>
          </div>

          {/* 4. Statistical ML Model */}
          <div
            onClick={() => setDeskTab("forecast")}
            role="button"
            tabIndex={0}
            style={{
              display: "flex",
              flexDirection: "column",
              gap: "4px",
              background: deskTab === "forecast" ? "rgba(56, 189, 248, 0.12)" : "var(--card-subtle, #131c31)",
              border: `1px solid ${deskTab === "forecast" ? "rgba(56, 189, 248, 0.45)" : "var(--border, rgba(255, 255, 255, 0.08))"}`,
              borderRadius: "10px",
              padding: "12px 14px",
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
            title="Click to view Live ML Forecast Trend Chart and Volatility Cones"
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span style={{ fontSize: "0.72rem", fontWeight: 700, color: deskTab === "forecast" ? "#38bdf8" : "var(--muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                ML Forecasting 📈
              </span>
              <span style={{ fontSize: "0.7rem", fontWeight: 700, color: approved.length > 0 ? "#16a34a" : "#ca8a04", background: approved.length > 0 ? "rgba(22, 163, 74, 0.12)" : "rgba(202, 138, 4, 0.12)", padding: "1px 6px", borderRadius: "4px" }}>
                {approved.length > 0 ? `🟢 ${approved.length} Models Ready` : "🟡 Fitted Active"}
              </span>
            </div>
            <span style={{ fontSize: "0.95rem", fontWeight: 700, color: "var(--ink, #f8fafc)" }}>
              {deskTab === "forecast" ? "Live Trend Chart Active" : "Logistic L2 + SOTA GBDT"}
            </span>
            <span style={{ fontSize: "0.72rem", color: deskTab === "forecast" ? "#38bdf8" : "var(--muted)" }}>
              {deskTab === "forecast" ? "Showing forward trajectory cone" : "Quant P(Up)/P(Down) Probabilities"}
            </span>
          </div>

        </div>

        {/* 2. Institutional Desk Verdict Hero Banner */}
        <div
          className="pro-verdict-hero"
          style={{
            borderLeft: `4px solid ${
              callClass === "bullish"
                ? "#10b981"
                : callClass === "bearish"
                ? "#f43f5e"
                : "#f59e0b"
            }`,
            marginBottom: "16px",
          }}
        >
          <div className="pro-verdict-summary">
            <span className="pro-eyebrow">
              🏛️ Institutional Desk Verdict &amp; Consensus Signal
            </span>
            <div style={{ display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap", marginTop: "2px" }}>
              <h2 id="agents-heading" className={`pro-call-badge ${callClass}`} style={{ margin: 0 }}>
                {decision === "NO_TRADE" ? "NO TRADE / CAUTION" : decision}
              </h2>
              <span
                style={{
                  fontSize: "0.75rem",
                  fontWeight: 700,
                  padding: "3px 10px",
                  borderRadius: "6px",
                  background:
                    callClass === "bullish"
                      ? "rgba(16, 185, 129, 0.15)"
                      : callClass === "bearish"
                      ? "rgba(244, 63, 94, 0.15)"
                      : "rgba(245, 158, 11, 0.15)",
                  color:
                    callClass === "bullish"
                      ? "#10b981"
                      : callClass === "bearish"
                      ? "#f43f5e"
                      : "#f59e0b",
                  border: `1px solid ${
                    callClass === "bullish"
                      ? "rgba(16, 185, 129, 0.3)"
                      : callClass === "bearish"
                      ? "rgba(244, 63, 94, 0.3)"
                      : "rgba(245, 158, 11, 0.3)"
                  }`,
                }}
              >
                {decision === "NO_TRADE" ? "Deadband Gated" : "Active Allocation"}
              </span>
            </div>
            <div className="pro-meta-chips" style={{ marginTop: "6px" }}>
              <span>⏱ Horizon: <strong>Intraday</strong></span>
              <span>📊 Forecasts: <strong>{approved.length === 0 ? (intel.forecast?.live_forecasts?.length ? `${intel.forecast.live_forecasts.length} live active` : "none") : `${approved.length} approved`}</strong></span>
              <span>🎯 Probabilities: <strong>{intel.forecast?.probabilities != null ? "returned" : (approved.length > 0 ? "ready" : "not set")}</strong></span>
              <span>⚡ Quant Fusion: <strong style={{ color: quantFusion ? "#10b981" : "var(--muted)" }}>{quantFusion ? "ENABLED" : "OFF"}</strong></span>
            </div>
          </div>

          {/* Regime & Safety Context Pills */}
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "6px" }}>
            <span style={{ fontSize: "0.72rem", color: "var(--muted)", textTransform: "uppercase", fontWeight: 700, letterSpacing: "0.06em" }}>
              Macro &amp; Market Regime
            </span>
            <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", justifyContent: "flex-end" }}>
              <span style={{ fontSize: "0.78rem", fontWeight: 650, color: "var(--ink)", background: "rgba(255, 255, 255, 0.04)", padding: "4px 10px", borderRadius: "6px", border: "1px solid var(--border)" }}>
                🛡️ Normal Volatility
              </span>
              <span style={{ fontSize: "0.78rem", fontWeight: 650, color: "#10b981", background: "rgba(16, 185, 129, 0.1)", padding: "4px 10px", borderRadius: "6px", border: "1px solid rgba(16, 185, 129, 0.2)" }}>
                ✓ Risk Limits Clear
              </span>
            </div>
          </div>
        </div>

        {/* 3. Command Toolbar & Action Bar */}
        <div className="pro-command-bar">

          <form onSubmit={run} className="agent-run pro-run-form" style={{ display: "grid", gap: "10px" }}>
            {/* Quick preset selector buttons */}
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", alignItems: "center" }}>
              <span style={{ fontSize: "0.78rem", fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                Presets:
              </span>
              <button
                type="button"
                className={INDICES_CHOICES.every((c) => selected.includes(c.id)) && selected.length === INDICES_CHOICES.length ? "selected pro-all-btn" : "pro-all-btn"}
                onClick={selectIndicesOnly}
                style={{ fontSize: "0.8rem", padding: "4px 10px", borderRadius: "6px" }}
              >
                🇮🇳 All Indices (3)
              </button>
              <button
                type="button"
                className={COMMODITY_CHOICES.every((c) => selected.includes(c.id)) && selected.length === COMMODITY_CHOICES.length ? "selected pro-all-btn" : "pro-all-btn"}
                onClick={selectCommoditiesOnly}
                style={{ fontSize: "0.8rem", padding: "4px 10px", borderRadius: "6px" }}
              >
                🛢️ MCX Commodities (8)
              </button>
              <button
                type="button"
                className={selected.length === ALL_CHOICES.length ? "selected pro-all-btn" : "pro-all-btn"}
                onClick={toggleAll}
                style={{ fontSize: "0.8rem", padding: "4px 10px", borderRadius: "6px" }}
              >
                {selected.length === ALL_CHOICES.length ? "✓ All Selected (15)" : "🌐 All Markets (15)"}
              </button>
              <button
                type="button"
                onClick={() => setSelected([])}
                style={{ fontSize: "0.8rem", padding: "4px 10px", borderRadius: "6px", opacity: 0.7 }}
              >
                Clear
              </button>
            </div>

            {/* Granular Instrument Chips */}
            <div className="choice-row" role="group" aria-label="Instruments" style={{ display: "flex", flexWrap: "wrap", gap: "6px", alignItems: "center" }}>
              <span style={{ fontSize: "0.78rem", color: "var(--muted)", fontWeight: 600, marginRight: "4px" }}>Indices:</span>
              {INDICES_CHOICES.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={selected.includes(item.id) ? "selected" : undefined}
                  aria-pressed={selected.includes(item.id)}
                  onClick={() => toggle(item.id)}
                  title={item.desc}
                  style={{ fontSize: "0.82rem", padding: "5px 10px", borderRadius: "6px" }}
                >
                  {item.label}
                </button>
              ))}

              <span style={{ fontSize: "0.78rem", color: "var(--muted)", fontWeight: 600, margin: "0 4px 0 10px" }}>MCX:</span>
              {COMMODITY_CHOICES.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={selected.includes(item.id) ? "selected" : undefined}
                  aria-pressed={selected.includes(item.id)}
                  onClick={() => toggle(item.id)}
                  title={`${item.label} (${item.desc})`}
                  style={{ fontSize: "0.82rem", padding: "5px 10px", borderRadius: "6px" }}
                >
                  {item.label}
                </button>
              ))}

              <span style={{ fontSize: "0.78rem", color: "var(--muted)", fontWeight: 600, margin: "0 4px 0 10px" }}>Global/Sectoral:</span>
              {GLOBAL_CHOICES.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={selected.includes(item.id) ? "selected" : undefined}
                  aria-pressed={selected.includes(item.id)}
                  onClick={() => toggle(item.id)}
                  title={`${item.label} (${item.desc})`}
                  style={{ fontSize: "0.82rem", padding: "5px 10px", borderRadius: "6px" }}
                >
                  {item.label}
                </button>
              ))}
            </div>

            <div style={{ display: "flex", gap: "16px", alignItems: "center", flexWrap: "wrap", marginTop: "4px" }}>
              <label className="check pro-check" style={{ display: "flex", alignItems: "center", gap: "6px", cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={quantFusion}
                  onChange={(event) => {
                    const checked = event.target.checked;
                    setQuantFusion(checked);
                    if (checked) setShowForecastChart(true);
                  }}
                />
                <span style={{ fontWeight: 650, color: quantFusion ? "var(--ink)" : "var(--muted)" }}>
                  ⚡ Combine ML Forecast with Agent Consensus (Quant Fusion)
                </span>
              </label>
              {quantFusion && (
                <button
                  type="button"
                  onClick={() => setShowForecastChart((prev) => !prev)}
                  style={{
                    padding: "3px 9px",
                    borderRadius: "6px",
                    fontSize: "0.75rem",
                    fontWeight: 650,
                    background: showForecastChart ? "rgba(56, 189, 248, 0.18)" : "var(--surface)",
                    border: "1px solid rgba(56, 189, 248, 0.35)",
                    color: showForecastChart ? "#38bdf8" : "var(--muted)",
                    cursor: "pointer",
                  }}
                >
                  {showForecastChart ? "📈 Forecast Graph: Visible" : "📈 Show Forecast Graph"}
                </button>
              )}

              <label className="check pro-check" style={{ display: "flex", alignItems: "center", gap: "6px", cursor: "pointer" }}>
                <input type="checkbox" checked={commentary} onChange={(event) => setCommentary(event.target.checked)} />
                <span>Include model commentary</span>
              </label>
              <label className="check pro-check" style={{ display: "flex", alignItems: "center", gap: "6px", cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={autoRun}
                  onChange={(event) => updateAutoRun(event.target.checked)}
                />
                <span>🔄 Auto-run Analysis:</span>
              </label>
              <select
                aria-label="Analysis auto-run interval"
                value={autoRunIntervalSec}
                onChange={(event) => updateAutoRunInterval(event.target.value)}
                style={{ fontSize: "0.8rem", padding: "4px 8px", borderRadius: "6px" }}
              >
                <option value={30}>Every 30s</option>
                <option value={60}>Every 1m (60s)</option>
                <option value={120}>Every 2m (120s)</option>
                <option value={300}>Every 5m (300s)</option>
                <option value={900}>Every 15m (900s)</option>
              </select>
              <button className="primary pro-run-btn" type="submit" disabled={phase === "loading" || selected.length === 0}>
                {phase === "loading" ? "Analyzing Pipeline…" : `Run analysis (${selected.length} Selected)`}
              </button>
            </div>
          </form>
        </div>
      </div>

      {/* 2. Professional Workspace Navigation Tabs */}
      <nav className="pro-workspace-tabs" aria-label="Analysis workspace tabs">
        <button
          type="button"
          className={deskTab === "trades" ? "active" : ""}
          onClick={() => setDeskTab("trades")}
        >
          <span>🎯 Trade Decisions & Options</span>
          {report ? <span className="tab-chip">{selected.length}</span> : null}
        </button>
        <button
          type="button"
          className={deskTab === "agents" ? "active" : ""}
          onClick={() => setDeskTab("agents")}
        >
          <span>🤖 12 Specialist Agents</span>
          <span className="tab-chip">12</span>
        </button>
        <button
          type="button"
          className={deskTab === "dossier" ? "active" : ""}
          onClick={() => setDeskTab("dossier")}
        >
          <span>📋 Master Dossier & Pipeline</span>
          <span className="tab-chip">Stages 0–14</span>
        </button>
        <button
          type="button"
          className={deskTab === "news" ? "active" : ""}
          onClick={() => setDeskTab("news")}
        >
          <span>📰 Headlines & News Wire</span>
          <span className="tab-chip">{news.body?.items?.length || 0}</span>
        </button>
        <button
          type="button"
          className={deskTab === "forecast" ? "active" : ""}
          onClick={() => setDeskTab("forecast")}
        >
          <span>📈 ML Forecasting &amp; Trend Graph</span>
          <span className="tab-chip">SOTA</span>
        </button>
        <button
          type="button"
          className={deskTab === "risk" ? "active" : ""}
          onClick={() => setDeskTab("risk")}
        >
          <span>🛡️ Risk & Contradictions</span>
        </button>
      </nav>

      {/* 3. Tab Panel: Trade Decisions & Options */}
      <div style={{ display: deskTab === "trades" ? "block" : "none" }}>
        {quantFusion && showForecastChart && (
          <div style={{ marginBottom: "20px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
              <span style={{ fontSize: "0.78rem", fontWeight: 700, color: "#38bdf8", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                📈 Quant Fusion: Live Price Action &amp; Forward Projected Trajectory
              </span>
              <button
                type="button"
                onClick={() => setShowForecastChart(false)}
                style={{
                  padding: "2px 8px",
                  fontSize: "0.72rem",
                  background: "transparent",
                  border: "none",
                  color: "var(--sub, #94a3b8)",
                  cursor: "pointer",
                }}
              >
                Hide Graph ✕
              </button>
            </div>
            <PredictedTrendChart />
          </div>
        )}

        {phase === "idle" ? (
          <div className="pro-welcome-card">
            <div className="pro-welcome-icon">🎯</div>
            <div>
              <h3 style={{ margin: "0 0 6px 0", fontSize: "1.05rem" }}>Ready for Multi-Agent Market Assessment</h3>
              <p style={{ margin: 0, fontSize: "0.85rem", color: "var(--muted)", lineHeight: 1.5 }}>
                Direct live quotes stream from Groww API. Real spot prices drive all ATM and option strike calculations without assumed data.
                Select instruments and click <strong>&ldquo;Run analysis&rdquo;</strong> above to generate real spot-based option picks (ATM/OTM/ITM), strike targets, stop losses, and agent consensus.
              </p>
            </div>
          </div>
        ) : null}

        {phase === "loading" ? (
          <div className="pro-loading-card" role="status">
            <div className="pro-spinner" />
            <div>
              <h3 style={{ margin: "0 0 4px 0", fontSize: "1.02rem" }}>Running the local assessment…</h3>
              <p style={{ margin: 0, fontSize: "0.82rem", color: "var(--muted)" }}>
                Evaluating live quotes, synthesizing news, calculating option strikes, and checking risk gates…
              </p>
            </div>
          </div>
        ) : null}

        {phase === "error" ? (
          <div className="error" role="alert" style={{ marginBottom: "20px" }}>
            <p>{error}</p>
            <button type="button" onClick={run}>
              Retry
            </button>
          </div>
        ) : null}

        {phase === "ready" && report ? (
          <InstrumentDecisions selected={selected} report={report} />
        ) : null}
      </div>

      {/* Tab Panel: ML Forecasting & Trend Graph */}
      <div style={{ display: deskTab === "forecast" ? "block" : "none" }}>
        <div style={{ marginBottom: "14px" }}>
          <h3 style={{ margin: 0, fontSize: "1.05rem" }}>Statistical ML Forecasting &amp; Forward Trajectory</h3>
          <p className="subtle-text" style={{ margin: "3px 0 0 0" }}>
            Live candlesticks from Groww API combined with SOTA forward-projected 1-hour trend trajectory, target spot, and dynamic &plusmn;1&sigma; volatility confidence cone.
          </p>
        </div>
        <PredictedTrendChart />
      </div>


      {/* 4. Tab Panel: Specialist Perspectives (12 Agents) */}
      <div style={{ display: deskTab === "agents" ? "block" : "none" }}>
        <div style={{ marginBottom: "14px" }}>
          <h3 style={{ margin: 0, fontSize: "1.05rem" }}>Specialist perspectives</h3>
          <p className="subtle-text" style={{ margin: "3px 0 0 0" }}>
            V6 evidence specialists operate deterministically over stored observations. Probabilities originate solely
            from validated statistical models.
          </p>
        </div>
        <div className="agent-grid" data-testid="perspectives">
          <Agent title="Data quality" body={report ? qualityBody(report) : "Not run."} />
          <Agent title="News agent" body={report ? newsBody(intel) : "Not run."} />
          <Agent title="Geopolitical agent" body={report ? geoBody(intel) : "Not run."} />
          <Agent title="Macro agent" body={report ? macroBody(intel, report) : "Not run."} />
          <Agent title="Crude & cross-asset" body={report ? crudeBody(intel) : "Not run."} />
          <Agent title="Market impact" body={report ? impactBody(intel) : "Not run."} />
          <Agent title="Breadth & flows" body={report ? breadthBody(intel) : "Not run."} />
          <Agent title="Options & derivatives" body={report ? optionsBody(intel) : "Not run."} />
          <Agent title="Contrarian agent" body={report ? contraBody(intel) : "Not run."} />
          <Agent
            title="Forecast model"
            body={
              report
                ? `Forecast ready ${valueText(report.forecast_ready || approved.length > 0 || intel.forecast?.probabilities != null)}. ${
                    (approved.length > 0 || intel.forecast?.live_forecasts?.length)
                      ? `${approved.length || intel.forecast.live_forecasts.length} approved statistical forecast models active.`
                      : "No approved forecast was returned."
                  } Probabilities ${
                    intel.forecast?.probabilities != null
                      ? Object.entries(intel.forecast.probabilities)
                          .map(([k, v]) => `${k}: ${Math.round(v * 100)}% P(Up)`)
                          .join(", ")
                      : approved.length > 0
                      ? approved.map((f) => `${f.instrument}: ${Math.round(f.probability_up * 100)}% P(Up)`).join(", ")
                      : "not set"
                  }.`
                : "Not run."
            }
          />
          <Agent
            title="Risk veto"
            body={
              report
                ? `Decision ${valueText(report.decision)}. Live approved ${valueText(report.live_approved)}. The risk engine keeps the veto.`
                : "Not run."
            }
          />
          <Agent
            title="Final verdict"
            body={
              report
                ? `Decision ${valueText(report.decision)}. Direction ${valueText(report.directional_assessment)}. Status ${valueText(
                    report.status
                  )}.`
                : "Not run."
            }
          />
        </div>
      </div>

      {/* 5. Tab Panel: Master Dossier & Pipeline Audit */}
      <div style={{ display: deskTab === "dossier" ? "block" : "none" }}>
        <div data-testid="intelligence">
          <h3 style={{ margin: "0 0 8px 0", fontSize: "1.05rem" }}>Agent record</h3>
          {phase !== "ready" ? (
            <p>The pipeline has not run. It does not invent articles, prices, or probabilities.</p>
          ) : (
            <IntelligenceDossier
              report={report}
              approved={approved}
              tab={tab}
              onSelectTab={setTab}
              selected={selected}
            />
          )}
        </div>
      </div>

      {/* 6. Tab Panel: Market News Wire */}
      <div style={{ display: deskTab === "news" ? "block" : "none" }}>
        <section data-testid="market-news">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px", marginBottom: "10px" }}>
            <div>
              <h3 style={{ margin: 0, fontSize: "1.05rem" }}>Headlines &amp; News Wire</h3>
              <p style={{ margin: "2px 0 0 0", fontSize: "0.82rem", color: "var(--muted)" }}>
                Latest market articles for the thesis. Configured web pages and RSS feeds are fetched by the News Agent.
              </p>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
              <button
                type="button"
                onClick={() => setShowNewsConfig((prev) => !prev)}
                style={{
                  background: showNewsConfig ? "rgba(56, 189, 248, 0.2)" : "rgba(255, 255, 255, 0.05)",
                  color: showNewsConfig ? "#38bdf8" : "var(--ink)",
                  border: "1px solid var(--line)",
                  borderRadius: "6px",
                  padding: "6px 12px",
                  fontSize: "0.8rem",
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                {showNewsConfig ? "✕ Close Feed Config" : "⚙ Configure Feeds & Web Pages"}
              </button>
              <button type="button" onClick={fetchNews} disabled={newsPhase === "loading"}>
                {newsPhase === "loading" ? "Fetching…" : "Fetch latest articles"}
              </button>
            </div>
          </div>
          {showNewsConfig && (
            <NewsSourcesManager
              onNewsUpdated={() => {
                news.retry();
                fetchNews();
              }}
            />
          )}
          {newsPhase === "error" ? <p className="error" role="alert">{newsError}</p> : null}
          {news.phase === "ready" && (news.body?.items || []).length === 0 ? <p>No articles are stored yet.</p> : null}
          {news.phase === "error" ? <p className="error">{news.error}</p> : null}
          <ul style={{ paddingLeft: "20px", margin: "10px 0" }}>
            {(news.body?.items || []).slice(0, 16).map((item) => (
              <li key={`${item.source_name}-${item.claim}`} style={{ marginBottom: "6px", fontSize: "0.85rem" }}>
                {item.source_url ? <a href={item.source_url} target="_blank" rel="noreferrer" style={{ fontWeight: 600 }}>{item.claim}</a> : <strong>{item.claim}</strong>}
                {" "}
                <span style={{ color: "var(--muted)", fontSize: "0.75rem" }}>
                  — {item.source_name}{item.published_at ? ` · ${item.published_at}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </section>
      </div>

      {/* 7. Tab Panel: Risk & Contradictions */}
      <div style={{ display: deskTab === "risk" ? "block" : "none" }}>
        <div style={{ background: "var(--card, #fff)", border: "1px solid var(--line, #e4ddd0)", borderRadius: "10px", padding: "16px 20px" }}>
          <h3 style={{ margin: "0 0 6px 0", fontSize: "1.05rem" }}>Contradictions & Red Team</h3>
          <p style={{ fontSize: "0.82rem", color: "var(--muted)", margin: "0 0 12px 0" }}>
            Automated falsification checks and challenges against directional consensus.
          </p>
          {phase !== "ready" ? (
            <p>No challenge has been run.</p>
          ) : (
            <p style={{ fontSize: "0.85rem" }}>
              {report?.contradictions?.length ? JSON.stringify(report.contradictions) : "No contradictory evidence was returned."}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}

function Agent({ title, body }) {
  return (
    <article className="agent-card">
      <h3>{title}</h3>
      <p>{body}</p>
    </article>
  );
}

function IntelligenceDossier({ report, approved, tab, onSelectTab }) {
  const intel = report?.intelligence || {};
  const stages = Array.isArray(intel.stages) ? intel.stages : [];
  const news = Array.isArray(intel.news) ? intel.news : [];
  const markets = intel.markets || {};

  return (
    <div>
      {/* Test-compatible baseline summary */}
      <p>
        Decision {valueText(intel.decision?.decision || report?.decision)}. Forecast probabilities{" "}
        {intel.forecast?.probabilities == null ? "not set" : valueText(intel.forecast.probabilities)}.
      </p>
      {intel.markets ? (
        <p>
          NIFTY {valueText(markets.NIFTY?.data_class || "MISSING_DATA")}. SENSEX{" "}
          {valueText(markets.SENSEX?.data_class || "MISSING_DATA")}.
        </p>
      ) : null}

      {/* View Switcher Tabs */}
      <nav className="v6-view-nav" aria-label="Analysis report views">
        <button
          type="button"
          className={tab === "dossier" ? "active" : undefined}
          onClick={() => onSelectTab("dossier")}
        >
          V6 Master Dossier (Stages 0–14)
        </button>
        <button
          type="button"
          className={tab === "pipeline" ? "active" : undefined}
          onClick={() => onSelectTab("pipeline")}
        >
          Pipeline Stages ({stages.length})
        </button>
        <button
          type="button"
          className={tab === "contradictions" ? "active" : undefined}
          onClick={() => onSelectTab("contradictions")}
        >
          Contradictions & Red Team
        </button>
        <button
          type="button"
          className={tab === "evidence" ? "active" : undefined}
          onClick={() => onSelectTab("evidence")}
        >
          Raw Observations ({report.evidence?.length || 0})
        </button>
      </nav>

      {/* Tab 1: Master Dossier (Stages 0 to 14) */}
      {tab === "dossier" && (
        <div className="dossier-grid">
          {/* Stage 0: Data Quality & Market Status */}
          <article className="dossier-card">
            <header className="dossier-head">
              <h3>
                <span className="stage-tag">0</span> Data Quality & Market Status
              </h3>
              <span className={`stage-pill ${report.quality?.status?.toLowerCase() || "unverified"}`}>
                Quality: {valueText(report.quality?.status || "UNKNOWN")}
              </span>
            </header>
            <div className="mini-meta">
              <article>
                <span>Market Status</span>
                <strong>CLOSED</strong>
              </article>
              <article>
                <span>Data Cutoff</span>
                <strong>{valueText(report.created_at)}</strong>
              </article>
              <article>
                <span>Accepted Rows</span>
                <strong>{report.quality?.accepted_count ?? (report.evidence?.length || 0)}</strong>
              </article>
              <article>
                <span>Rejected Rows</span>
                <strong>{report.quality?.rejected_count ?? (report.rejected?.length || 0)}</strong>
              </article>
              <article>
                <span>Synthetic Rows</span>
                <strong>{report.quality?.synthetic_count ?? 0}</strong>
              </article>
              <article>
                <span>Decision</span>
                <strong>{valueText(report.decision)}</strong>
              </article>
            </div>
            {report.rejected?.length > 0 && (
              <div className="dossier-callout warning">
                <strong>Data Validation Alerts:</strong> {report.rejected.length} row(s) failed strict verification and were quarantined.
              </div>
            )}
          </article>

          {/* Stage 1: Executive View */}
          <article className="dossier-card">
            <header className="dossier-head">
              <h3>
                <span className="stage-tag">1</span> Executive View
              </h3>
              <span className="stage-pill veto">{valueText(report.decision)}</span>
            </header>
            <div className="mini-meta">
              <article>
                <span>NIFTY Bias</span>
                <strong>{valueText(markets.NIFTY?.direction || "UNKNOWN")}</strong>
              </article>
              <article>
                <span>SENSEX Bias</span>
                <strong>{valueText(markets.SENSEX?.direction || "UNKNOWN")}</strong>
              </article>
              <article>
                <span>Overall Regime</span>
                <strong>{valueText(report.directional_assessment || "NO_DIRECTIONAL_EDGE")}</strong>
              </article>
              <article>
                <span>Forecast Horizon</span>
                <strong>Intraday</strong>
              </article>
            </div>
            <p>
              <strong>Main Driver:</strong>{" "}
              {news.length > 0
                ? `${news[0].claim} (${news[0].claim_kind || "SOURCE_CLAIM"})`
                : "No verified driver supplied. A missing series stays missing."}
            </p>
            <p>
              <strong>Main Counterargument:</strong>{" "}
              {Array.isArray(intel.contrarian) && intel.contrarian.length > 0
                ? intel.contrarian[0].finding
                : "Missing verified cross-asset and institutional flow confirmations."}
            </p>
          </article>

          {/* Stage 2: Global & Macro */}
          <article className="dossier-card">
            <header className="dossier-head">
              <h3>
                <span className="stage-tag">2</span> Global & Macro Drivers
              </h3>
              <span className={`stage-pill ${(intel.global_context?.length || intel.macro?.length) ? "present" : "missing"}`}>
                {(intel.global_context?.length || intel.macro?.length) ? "PRESENT" : "MISSING_DATA"}
              </span>
            </header>
            {(intel.global_context?.length || intel.macro?.length) ? (
              <div className="mini-meta">
                {(intel.global_context || []).map((g) => (
                  <article key={g.instrument}>
                    <span>{g.instrument} (Global)</span>
                    <strong>{g.direction || g.data_class}</strong>
                  </article>
                ))}
                {(intel.macro || []).map((m) => (
                  <article key={m.instrument}>
                    <span>{m.instrument} (MCX Macro)</span>
                    <strong>{m.direction || m.data_class}</strong>
                  </article>
                ))}
              </div>
            ) : (
              <p className="quiet">
                No verified global-index feed is configured. SPX, Nasdaq, Russell, and US yields stay unasserted.
              </p>
            )}
          </article>

          {/* Stage 3: Fresh News — Verified */}
          <article className="dossier-card">
            <header className="dossier-head">
              <h3>
                <span className="stage-tag">3</span> Fresh Verified News
              </h3>
              <span className={`stage-pill ${news.length ? "present" : "missing"}`}>
                {news.length ? `${news.length} ITEMS` : "MISSING_DATA"}
              </span>
            </header>
            {news.length === 0 ? (
              <p className="quiet">No authorized article was supplied. A missing source stays missing.</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Event / Claim</th>
                      <th>Class</th>
                      <th>Status</th>
                      <th>Direction</th>
                      <th>Sources</th>
                      <th>Published At</th>
                      <th>Transmission</th>
                    </tr>
                  </thead>
                  <tbody>
                    {news.map((item) => (
                      <tr key={item.claim}>
                        <td><strong>{item.claim}</strong></td>
                        <td><span className="data-badge">{item.data_class || item.claim_kind}</span></td>
                        <td>{item.verification_status}</td>
                        <td>{Array.isArray(item.directions) ? item.directions.join(", ") : "not set"}</td>
                        <td>{Array.isArray(item.sources) ? item.sources.join(", ") : "not set"}</td>
                        <td>{valueText(item.published_at)}</td>
                        <td>{item.why_it_may_matter || "not asserted"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </article>

          {/* Stage 4: Crude, INR & Commodities */}
          <article className="dossier-card">
            <header className="dossier-head">
              <h3>
                <span className="stage-tag">4</span> Crude Oil, INR & Commodities
              </h3>
              <span className={`stage-pill ${Array.isArray(intel.macro) && intel.macro.length ? "present" : "missing"}`}>
                {Array.isArray(intel.macro) && intel.macro.length ? "PRESENT" : "MISSING_DATA"}
              </span>
            </header>
            {Array.isArray(intel.macro) && intel.macro.length > 0 ? (
              <div className="mini-meta">
                {intel.macro.map((m) => (
                  <article key={m.instrument}>
                    <span>{m.instrument}</span>
                    <strong>{m.direction || m.data_class}</strong>
                    <small>{m.freshness || "unknown"}</small>
                  </article>
                ))}
              </div>
            ) : (
              <p className="quiet">
                Crude, currency, and yields stay missing unless a row was supplied. Cross-asset transmission is not assumed.
              </p>
            )}
            {Array.isArray(intel.geopolitics) && intel.geopolitics.length > 0 && (
              <div className="dossier-callout info">
                <strong>Geopolitical Channels:</strong> {intel.geopolitics.map((g) => g.channels.join(", ")).join("; ")}
              </div>
            )}
          </article>

          {/* Stages 5, 6, 7: Indian Indices */}
          <article className="dossier-card">
            <header className="dossier-head">
              <h3>
                <span className="stage-tag">5–7</span> Indian Index Technicals (NIFTY, SENSEX)
              </h3>
              <span className="stage-pill unverified">TECHNICALS</span>
            </header>
            <div className="mini-meta">
              <article>
                <span>NIFTY 50</span>
                <strong>{valueText(markets.NIFTY?.data_class || "MISSING_DATA")}</strong>
                <small>Direction: {valueText(markets.NIFTY?.direction || "not set")}</small>
              </article>
              <article>
                <span>SENSEX</span>
                <strong>{valueText(markets.SENSEX?.data_class || "MISSING_DATA")}</strong>
                <small>Direction: {valueText(markets.SENSEX?.direction || "not set")}</small>
              </article>
            </div>
            {Array.isArray(intel.impact) && intel.impact.length > 0 && (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>News Claim</th>
                      <th>Expected Reaction</th>
                      <th>Observed Direction</th>
                      <th>Confirms Narrative</th>
                      <th>Interpretation</th>
                    </tr>
                  </thead>
                  <tbody>
                    {intel.impact.map((imp, idx) => (
                      <tr key={idx}>
                        <td>{imp.claim}</td>
                        <td>{valueText(imp.expected)}</td>
                        <td>{valueText(imp.actual)}</td>
                        <td>{imp.confirms_narrative === true ? "YES" : imp.confirms_narrative === false ? "NO" : "UNKNOWN"}</td>
                        <td>{imp.alternative}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </article>

          {/* Stage 8: VIX, Breadth, Sectors & Flows */}
          <article className="dossier-card">
            <header className="dossier-head">
              <h3>
                <span className="stage-tag">8</span> VIX, Breadth, Sectors & Flows
              </h3>
              <span className="stage-pill missing">MISSING_DATA</span>
            </header>
            <p className="quiet">
              No breadth or institutional flow series was supplied. FII/DII cash and derivatives positioning stay unasserted.
            </p>
          </article>

          {/* Stage 9: Options & Open Interest */}
          <article className="dossier-card">
            <header className="dossier-head">
              <h3>
                <span className="stage-tag">9</span> Options Chain & Open Interest
              </h3>
              <span className="stage-pill veto">{valueText(intel.options?.decision || "NO_TRADE")}</span>
            </header>
            <div className="mini-meta">
              <article>
                <span>Chain Status</span>
                <strong>{valueText(intel.options?.chain || "MISSING_DATA")}</strong>
              </article>
              <article>
                <span>PCR</span>
                <strong>not set</strong>
              </article>
              <article>
                <span>Max Pain / Walls</span>
                <strong>not set</strong>
              </article>
              <article>
                <span>Expected Move</span>
                <strong>not set</strong>
              </article>
            </div>
            <p className="subtle-text">
              {intel.options?.reason || "Required option inputs are not a verified chain. Options can lose 100% of premium."}
            </p>
          </article>

          {/* Stage 10: Quantitative Forecast Matrix */}
          <article className="dossier-card">
            <header className="dossier-head">
              <h3>
                <span className="stage-tag">10</span> Quantitative Forecast Matrix
              </h3>
              <span className="stage-pill missing">{valueText(intel.forecast?.status || "MISSING_DATA")}</span>
            </header>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Horizon</th>
                    <th>Up Probability</th>
                    <th>Range Probability</th>
                    <th>Down Probability</th>
                    <th>Expected Move</th>
                    <th>Calibration</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>INTRADAY</td>
                    <td>{intel.forecast?.probabilities?.up == null ? "not set" : valueText(intel.forecast.probabilities.up)}</td>
                    <td>{intel.forecast?.probabilities?.range == null ? "not set" : valueText(intel.forecast.probabilities.range)}</td>
                    <td>{intel.forecast?.probabilities?.down == null ? "not set" : valueText(intel.forecast.probabilities.down)}</td>
                    <td>{intel.forecast?.expected_move == null ? "not set" : valueText(intel.forecast.expected_move)}</td>
                    <td>Uncalibrated (No approved model)</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p className="subtle-text">
              {intel.forecast?.reason || "No validated class-conditional return is configured. A narrative is not a probability."}
            </p>
          </article>

          {/* Stage 11: Scenario Matrix */}
          <article className="dossier-card">
            <header className="dossier-head">
              <h3>
                <span className="stage-tag">11</span> Scenario Matrix
              </h3>
              <span className="stage-pill unverified">SCENARIOS</span>
            </header>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Scenario</th>
                    <th>Probability</th>
                    <th>Trigger</th>
                    <th>Confirmation</th>
                    <th>Invalidation</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td><strong>Bullish Expansion</strong></td>
                    <td>not set</td>
                    <td>Price acceptance above prior session high with expanding volume</td>
                    <td>Crude softening or USD/INR stabilization</td>
                    <td>Breakdown below session VWAP</td>
                  </tr>
                  <tr>
                    <td><strong>Range / Consolidation</strong></td>
                    <td>not set</td>
                    <td>Inside range oscillation without follow-through</td>
                    <td>Flat IV and balanced call/put OI build-up</td>
                    <td>Sustained breach of initial balance</td>
                  </tr>
                  <tr>
                    <td><strong>Bearish Breakdown</strong></td>
                    <td>not set</td>
                    <td>Sustained trade below prior session low or key support zone</td>
                    <td>Surge in crude or USD/INR depreciation</td>
                    <td>V-shaped reclaim of breakdown zone</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </article>

          {/* Stage 12: Contrarian / Red Team Scan */}
          <article className="dossier-card">
            <header className="dossier-head">
              <h3>
                <span className="stage-tag">12</span> Contrarian / Red Team Scan
              </h3>
              <span className="stage-pill present">ACTIVE</span>
            </header>
            {Array.isArray(intel.contrarian) && intel.contrarian.length > 0 ? (
              <ul>
                {intel.contrarian.map((note, idx) => (
                  <li key={idx}>
                    <strong>{note.question}</strong> — {note.finding}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="quiet">No contrarian note was returned.</p>
            )}
          </article>

          {/* Stage 13: Conditional Trade Evaluation & Risk Veto */}
          <article className="dossier-card">
            <header className="dossier-head">
              <h3>
                <span className="stage-tag">13</span> Conditional Trade Evaluation & Risk Veto
              </h3>
              <span className="stage-pill veto">RISK VETO</span>
            </header>
            <div className="mini-meta">
              <article>
                <span>Risk Gate</span>
                <strong>VETO</strong>
              </article>
              <article>
                <span>Veto Code</span>
                <strong>{valueText(intel.risk?.code || "EXPECTED_NET_UNAVAILABLE")}</strong>
              </article>
              <article>
                <span>Paper Approved</span>
                <strong>false</strong>
              </article>
              <article>
                <span>Live Approved</span>
                <strong>false</strong>
              </article>
            </div>
            <div className="dossier-callout danger">
              <strong>Order Placement Blocked:</strong> Trade proposals require validated input evidence, positive expected
              net payoff after all statutory charges and slippage, and human operator confirmation.
            </div>
          </article>

          {/* Stage 14: Final Vote / Verdict */}
          <article className="dossier-card">
            <header className="dossier-head">
              <h3>
                <span className="stage-tag">14</span> Final Vote / Verdict
              </h3>
              <span className="stage-pill veto">{valueText(intel.decision?.decision || report.decision)}</span>
            </header>
            <p>
              <strong>Enforced Vocabulary:</strong> {Array.isArray(intel.decision?.supported_vocabulary) ? intel.decision.supported_vocabulary.join(", ") : "NO_TRADE"}
            </p>
            <p className="subtle-text">
              {intel.decision?.reason || "The enforced decision contract returns NO_TRADE until verified inputs and a risk check both allow a trade."}
            </p>
          </article>
        </div>
      )}

      {/* Tab 2: Pipeline Stages (19 Stages) */}
      {tab === "pipeline" && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Stage Name</th>
                <th>Status</th>
                <th>Audit Detail</th>
              </tr>
            </thead>
            <tbody>
              {stages.length === 0 ? (
                <tr>
                  <td colSpan={4}>No pipeline stages were returned.</td>
                </tr>
              ) : (
                stages.map((stage, idx) => (
                  <tr key={stage.name}>
                    <td>{idx + 1}</td>
                    <td><strong>{stage.name}</strong></td>
                    <td>
                      <span className={`stage-pill ${stage.status?.toLowerCase() || "unverified"}`}>
                        {stage.status}
                      </span>
                    </td>
                    <td>{stage.detail}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Tab 3: Contradictions & Red Team */}
      {tab === "contradictions" && (
        <div className="dossier-grid">
          <article className="dossier-card">
            <header className="dossier-head">
              <h3>Contradiction & Signal Conflicts</h3>
              <span className="stage-pill present">
                {report.contradictions?.length ? "CONFLICTS DETECTED" : "NO CONFLICTS"}
              </span>
            </header>
            {report.contradictions?.length ? (
              <pre>{JSON.stringify(report.contradictions, null, 2)}</pre>
            ) : (
              <p className="quiet">No conflicting evidence between bullish and bearish observations was detected.</p>
            )}
          </article>
          <article className="dossier-card">
            <header className="dossier-head">
              <h3>Red Team Challenges & Falsification Conditions</h3>
            </header>
            <ul>
              {(intel.contrarian || []).map((note, idx) => (
                <li key={idx}>
                  <strong>{note.question}</strong>
                  <p>{note.finding}</p>
                </li>
              ))}
            </ul>
          </article>
        </div>
      )}

      {/* Tab 4: Raw Observations */}
      {tab === "evidence" && (
        <div className="dossier-grid">
          <article className="dossier-card">
            <header className="dossier-head">
              <h3>Accepted Observations ({report.evidence?.length || 0})</h3>
            </header>
            {(!report.evidence || report.evidence.length === 0) ? (
              <p className="quiet">No observations were accepted into this analysis run.</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Category</th>
                      <th>Claim</th>
                      <th>Type</th>
                      <th>Provenance</th>
                      <th>Freshness</th>
                      <th>Verification</th>
                      <th>Direction</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.evidence.map((row) => (
                      <tr key={row.evidence_id}>
                        <td><code>{row.evidence_id}</code></td>
                        <td>{row.category}</td>
                        <td>{row.claim}</td>
                        <td>{row.claim_type}</td>
                        <td><span className="data-badge">{row.provenance}</span></td>
                        <td>{row.freshness}</td>
                        <td>{row.verification_status}</td>
                        <td>{row.directional_implication}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </article>

          {report.rejected?.length > 0 && (
            <article className="dossier-card">
              <header className="dossier-head">
                <h3>Rejected & Quarantined Observations ({report.rejected.length})</h3>
                <span className="stage-pill veto">QUARANTINED</span>
              </header>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Rejection Reason</th>
                      <th>Quarantine ID</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.rejected.map((rej, idx) => (
                      <tr key={idx}>
                        <td>{idx + 1}</td>
                        <td>{rej.reason}</td>
                        <td><code>{rej.quarantine_id || "n/a"}</code></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </article>
          )}
        </div>
      )}
    </div>
  );
}

function qualityBody(report) {
  const quality = report?.quality || {};
  const rejected = quality.rejected_count ?? (report?.rejected?.length || 0);
  const accepted = quality.accepted_count ?? (report?.evidence?.length || 0);
  const synthetic = quality.synthetic_count ?? 0;
  return `Quality ${quality.status || "UNKNOWN"}. Accepted: ${accepted}, Rejected: ${rejected}, Synthetic: ${synthetic}.`;
}

function newsBody(intel) {
  const count = Array.isArray(intel.news) ? intel.news.length : 0;
  if (count === 0) return "No authorized article was supplied. The news agent did not invent one.";
  return `${count} deduplicated item(s). Conflicting directions are kept.`;
}

function geoBody(intel) {
  const count = Array.isArray(intel.geopolitics) ? intel.geopolitics.length : 0;
  if (count === 0) return "No supplied item carried a geopolitical category. Nothing was marked bearish by default.";
  return `${count} transmission reading(s), each with a bullish, bearish and neutral channel.`;
}

function macroBody(intel, report) {
  const macroRows = Array.isArray(intel.macro) ? intel.macro : [];
  if (macroRows.length === 0) return "Crude, currency and yields stay missing unless a row was supplied.";
  return `${macroRows.length} macro series present: ${macroRows.map((r) => r.instrument).join(", ")}.`;
}

function crudeBody(intel) {
  const macroRows = Array.isArray(intel.macro) ? intel.macro : [];
  const crude = macroRows.find((r) => r.instrument === "CRUDE" || r.instrument === "CRUDEOILMINI" || r.instrument === "CRUDEMINI");
  if (!crude) return "Crude is missing. Cross-asset transmission into Indian equities is unverified.";
  return `${crude.instrument === "CRUDEOILMINI" ? "Crude Mini" : "Crude"} ${crude.data_class}. Direction: ${crude.direction || "not set"}. Freshness: ${crude.freshness || "unknown"}.`;
}

function impactBody(intel) {
  const markets = intel.markets || {};
  return `NIFTY ${valueText(markets.NIFTY?.data_class)}. SENSEX ${valueText(markets.SENSEX?.data_class)}.`;
}

function breadthBody(intel) {
  const breadth = intel.breadth_flows;
  if (!breadth || breadth.status === "MISSING_DATA") return "No breadth or institutional flow series was supplied. FII/DII is unverified.";
  return `VIX: ${breadth.vix ? valueText(breadth.vix.claim) : "missing"}. Breadth: ${valueText(breadth.breadth)}.`;
}

function optionsBody(intel) {
  const options = intel.options || {};
  return `Chain ${valueText(options.chain)}. Decision ${valueText(options.decision)}. Required options inputs stay unverified.`;
}

function contraBody(intel) {
  const notes = Array.isArray(intel.contrarian) ? intel.contrarian : [];
  if (notes.length === 0) return "No contrarian note was returned.";
  return notes.map((note) => note.finding).filter(Boolean).join(" ") || "The challenge used only supplied rows.";
}

const INSTRUMENT_METADATA = {
  NIFTY: {
    name: "NIFTY 50",
    exchange: "NSE",
    lotSize: 75,
    description: "Benchmark Indian Equity Index representing top 50 large-cap stocks.",
  },
  SENSEX: {
    name: "BSE SENSEX",
    exchange: "BSE",
    lotSize: 20,
    description: "Benchmark 30-stock index of Bombay Stock Exchange.",
  },
  FINNIFTY: {
    name: "FIN NIFTY",
    exchange: "NSE",
    lotSize: 25,
    description: "Nifty Financial Services index tracking financial companies.",
  },
  MIDCPNIFTY: {
    name: "MIDCAP NIFTY",
    exchange: "NSE",
    lotSize: 75,
    description: "Nifty Midcap Select index tracking top midcap performers.",
  },
  BANKEX: {
    name: "BSE BANKEX",
    exchange: "BSE",
    lotSize: 15,
    description: "BSE Bankex tracking major banking stocks.",
  },
  NIFTYIT: {
    name: "NIFTY IT",
    exchange: "NSE",
    lotSize: 25,
    description: "Nifty IT index tracking Indian information technology firms.",
  },
  CRUDEOILMINI: {
    name: "MCX Crude Oil Mini",
    exchange: "MCX",
    lotSize: 10,
    description: "MCX Crude Oil Mini (10 bbl contract, retail friendly).",
  },
  CRUDEMINI: {
    name: "MCX Crude Oil Mini",
    exchange: "MCX",
    lotSize: 10,
    description: "MCX Crude Oil Mini (10 bbl contract, retail friendly).",
  },
  CRUDE: {
    name: "MCX Crude Oil",
    exchange: "MCX",
    lotSize: 100,
    description: "MCX Crude Oil Futures (100 bbl standard contract).",
  },
  GOLDMINI: {
    name: "MCX Gold Mini",
    exchange: "MCX",
    lotSize: 1,
    description: "MCX Gold Mini contract (100g / 10g denomination).",
  },
  GOLD: {
    name: "MCX Gold",
    exchange: "MCX",
    lotSize: 1,
    description: "MCX Gold standard contract (1 kg / 100g deliverable).",
  },
  SILVERMINI: {
    name: "MCX Silver Mini",
    exchange: "MCX",
    lotSize: 5,
    description: "MCX Silver Mini contract (5 kg denomination).",
  },
  SILVER: {
    name: "MCX Silver",
    exchange: "MCX",
    lotSize: 30,
    description: "MCX Silver standard contract (30 kg denomination).",
  },
  NATURALGASMINI: {
    name: "MCX Natural Gas Mini",
    exchange: "MCX",
    lotSize: 250,
    description: "MCX Natural Gas Mini contract (250 mmBtu).",
  },
  NATURALGAS: {
    name: "MCX Natural Gas",
    exchange: "MCX",
    lotSize: 1250,
    description: "MCX Natural Gas standard contract (1250 mmBtu).",
  },
  GIFTNIFTY: {
    name: "GIFT Nifty (NSE IX)",
    exchange: "NSE IX",
    lotSize: 50,
    description: "International dollar-denominated Nifty derivative trading in GIFT City.",
  },
  DJI: {
    name: "Dow Jones (DJI)",
    exchange: "US",
    lotSize: 1,
    description: "Dow Jones Industrial Average 30 US blue-chip benchmark.",
  },
};

function InstrumentDecisions({ selected, report }) {
  const { spots } = useMarketData();
  const [focusedInst, setFocusedInst] = useState(selected[0] || "ALL");
  const intel = report?.intelligence || {};
  const markets = intel.markets || {};

  return (
    <section className="instrument-decision-section" aria-labelledby="instrument-decisions-heading">
      <div className="section-head" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "12px", marginBottom: "16px" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "4px" }}>
            <span className="eyebrow" style={{ margin: 0 }}>Decision Matrix</span>
            <span style={{ fontSize: "0.68rem", fontWeight: 700, padding: "2px 8px", borderRadius: "999px", background: "rgba(56, 189, 248, 0.12)", color: "#38bdf8", border: "1px solid rgba(56, 189, 248, 0.25)" }}>
              ⚡ OPTION RECOMMENDATIONS
            </span>
          </div>
          <h3 id="instrument-decisions-heading" style={{ margin: 0, fontSize: "1.15rem", fontWeight: 800 }}>Instrument Decisions & Option Recommendations</h3>
          <p className="subtle-text" style={{ margin: "2px 0 0 0", fontSize: "0.8rem", color: "var(--muted)" }}>
            Deterministic multi-agent synthesis from live Groww spot feeds, macro transmission, and risk engine rules.
          </p>
        </div>

        {selected.length > 1 && (
          <div className="pro-inst-filter" role="tablist" aria-label="Instrument switcher">
            <span style={{ fontSize: "0.78rem", fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.06em", marginRight: "4px" }}>
              Focus:
            </span>
            <button
              type="button"
              className={focusedInst === "ALL" ? "active" : ""}
              onClick={() => setFocusedInst("ALL")}
            >
              All Instruments ({selected.length})
            </button>
            {selected.map((item) => {
              const m = markets[item] || {};
              const liveSpot = (spots && (spots[item] || (item === "CRUDEMINI" ? spots["CRUDEOILMINI"] : null))) ?? m.last_price;
              const spot = liveSpot != null ? `₹${Number(liveSpot).toLocaleString("en-IN", { maximumFractionDigits: 0 })}` : "No Feed";
              return (
                <button
                  key={item}
                  type="button"
                  className={focusedInst === item ? "active" : ""}
                  onClick={() => setFocusedInst(item)}
                >
                  {item} <span style={{ opacity: 0.8, fontSize: "0.75rem", marginLeft: "4px" }}>({spot})</span>
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="instrument-decision-grid">
        {selected.map((item) => {
          const isVisible = focusedInst === "ALL" || focusedInst === item;
          const meta = INSTRUMENT_METADATA[item] || { name: item, exchange: "INDEX", description: "" };
          const data = markets[item] || {
            status: "MISSING_DATA",
            data_class: "MISSING_DATA",
            direction: null,
            decision: "NO_TRADE — MISSING_DATA",
            bias: "RANGE / NO DIRECTIONAL EDGE",
            last_price: null,
            what_happens: {
              regime: "INDETERMINATE",
              summary: `No verified live price observation was supplied for ${item}. Market reaction cannot be confirmed without real data.`,
              bullish_trigger: "Price acceptance above prior session high on verified volume, confirmed by cross-asset stability.",
              bearish_trigger: "Sustained breach below prior session low or key support zone, confirmed by crude/USDINR pressure.",
              invalidation: "Any speculative thesis is immediately invalidated without verified multi-source confirmation.",
            },
            options_evaluation: {
              verdict: "NO_TRADE",
              reason: `No verified option chain or strike OI available for ${item}. Options can lose 100% of premium.`,
            },
            risk_veto: {
              vetoed: true,
              reason: "Deterministic risk engine veto: missing verified price series and expected net payoff unavailable.",
            },
          };

          const whatHappens = data.what_happens || {};
          const isBullish = (data.bias || "").toLowerCase().includes("bullish");
          const isBearish = (data.bias || "").toLowerCase().includes("bearish");
          const biasClass = isBullish ? "bullish" : isBearish ? "bearish" : "neutral";
          const session = getMarketSessionInfo(item);
          const liveSpot = (spots && (spots[item] || (item === "CRUDEMINI" ? spots["CRUDEOILMINI"] : null))) ?? data.last_price;

          return (
            <article
              key={item}
              className="instrument-card"
              data-testid={`instrument-decision-${item}`}
              style={{ display: isVisible ? "block" : "none" }}
            >
              <div className="instrument-card-head" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px", paddingBottom: "12px", borderBottom: "1px solid var(--line)" }}>
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                    <h4 style={{ fontSize: "1.2rem", margin: 0, fontWeight: 800 }}>{meta.name}</h4>
                    <span style={{ fontSize: "0.72rem", padding: "1px 6px", borderRadius: "4px", background: "rgba(255,255,255,0.06)", color: "var(--muted)", fontWeight: 600 }}>
                      {meta.exchange}
                    </span>
                  </div>
                  <small style={{ color: "var(--muted)", fontSize: "0.74rem" }}>
                    {session.isOpen ? "🟢 Live Trading Session Active" : `🌙 Closed (Session Ended ${session.closeTimeText})`}
                  </small>
                </div>
                <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                  {liveSpot != null && (
                    <div style={{ textAlign: "right", marginRight: "4px" }}>
                      <span style={{ fontSize: "0.68rem", color: "var(--muted)", display: "block", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                        {session.isOpen ? "Live Spot LTP" : "Settlement Spot"}
                      </span>
                      <span style={{ fontSize: "1.05rem", fontWeight: 850, color: "var(--ink)", letterSpacing: "-0.01em" }}>
                        ₹{Number(liveSpot).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </span>
                    </div>
                  )}
                  <span className="data-badge" style={{
                    background: data.data_class?.includes("PROVIDER") ? "rgba(16, 185, 129, 0.12)" : undefined,
                    color: data.data_class?.includes("PROVIDER") ? "#34d399" : undefined,
                    borderColor: data.data_class?.includes("PROVIDER") ? "rgba(16, 185, 129, 0.3)" : undefined,
                  }}>
                    {data.data_class?.includes("PROVIDER") ? "🟢 LIVE FEED" : (data.data_class || "MISSING DATA")}
                  </span>
                  <span className={`bias-badge ${biasClass}`}>{data.bias || "RANGE / NO EDGE"}</span>
                </div>
              </div>

              <div
                className="decision-banner"
                style={{
                  background: !session.isOpen
                    ? "rgba(15, 23, 42, 0.65)"
                    : isBullish
                    ? "rgba(16, 185, 129, 0.08)"
                    : isBearish
                    ? "rgba(244, 63, 94, 0.08)"
                    : "rgba(245, 158, 11, 0.08)",
                  border: `1px solid ${
                    !session.isOpen
                      ? "var(--line)"
                      : isBullish
                      ? "rgba(16, 185, 129, 0.3)"
                      : isBearish
                      ? "rgba(244, 63, 94, 0.3)"
                      : "rgba(245, 158, 11, 0.3)"
                  }`,
                  borderRadius: "10px",
                  padding: "10px 14px",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  flexWrap: "wrap",
                  gap: "10px",
                  margin: "12px 0",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
                  <span style={{
                    fontSize: "0.92rem",
                    fontWeight: 800,
                    padding: "4px 12px",
                    borderRadius: "6px",
                    letterSpacing: "0.02em",
                    background: !session.isOpen
                      ? "rgba(255, 255, 255, 0.06)"
                      : isBullish
                      ? "rgba(16, 185, 129, 0.2)"
                      : isBearish
                      ? "rgba(244, 63, 94, 0.2)"
                      : "rgba(245, 158, 11, 0.2)",
                    color: !session.isOpen
                      ? "var(--muted)"
                      : isBullish
                      ? "#34d399"
                      : isBearish
                      ? "#fb7185"
                      : "#fbbf24",
                    border: `1px solid ${
                      !session.isOpen
                        ? "var(--line)"
                        : isBullish
                        ? "rgba(16, 185, 129, 0.35)"
                        : isBearish
                        ? "rgba(244, 63, 94, 0.35)"
                        : "rgba(245, 158, 11, 0.35)"
                    }`,
                  }}>
                    {!session.isOpen
                      ? "STAND ASIDE (MARKET CLOSED)"
                      : (data.bias ? `SIGNAL: ${data.bias}` : "WAIT_FOR_CONFIRMATION")}
                  </span>
                  <span style={{ fontSize: "0.76rem", color: "var(--muted)" }}>
                    {session.isOpen 
                      ? "Multi-agent consensus active · Live market feed verified"
                      : `Market Closed · Stand aside until session opens (${session.nextOpenText})`}
                  </span>
                </div>
                <div style={{ display: "flex", gap: "8px", alignItems: "center", fontSize: "0.75rem", color: "var(--muted)" }}>
                  <span>Risk Gate: <strong style={{ color: "#34d399" }}>PASS</strong></span>
                </div>
              </div>

              {/* Actionable Option Trade Card Priority Placement */}
              {data.manual_trade_recommendation && (
                <ManualTradeCard
                  instrument={item}
                  meta={meta}
                  recommendation={data.manual_trade_recommendation}
                  dataClass={data.data_class}
                />
              )}

              {/* Collapsible Intelligence & Trigger Framework */}
              <details className="intelligence-drawer">
                <summary>
                  <span>📋 Regime Triggers & Invalidation Framework ({whatHappens.regime || "INDETERMINATE"})</span>
                  <span style={{ fontSize: "0.75rem", color: "var(--cyan)", fontWeight: 600 }}>Toggle Rules ▾</span>
                </summary>
                <div style={{ padding: "12px 14px", display: "grid", gap: "10px", fontSize: "0.82rem" }}>
                  <div style={{ display: "flex", gap: "8px", alignItems: "baseline", flexWrap: "wrap" }}>
                    <span style={{ fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", fontSize: "0.72rem" }}>Regime Summary:</span>
                    <span style={{ color: "var(--ink)", lineHeight: 1.45 }}>{whatHappens.summary}</span>
                  </div>
                  <div className="trigger-grid" style={{ marginTop: "4px" }}>
                    <div className="trigger-item bullish">
                      <strong>▲ Bullish Case (What triggers UP):</strong>
                      <span>{whatHappens.bullish_trigger || "Breakout above session resistance on expanding volume."}</span>
                    </div>
                    <div className="trigger-item bearish">
                      <strong>▼ Bearish Case (What triggers DOWN):</strong>
                      <span>{whatHappens.bearish_trigger || "Breakdown below session support confirmed by crude/FX surge."}</span>
                    </div>
                    <div className="trigger-item invalidation">
                      <strong>⚠️ Invalidation (When thesis fails):</strong>
                      <span>{whatHappens.invalidation || "Reversal below session VWAP or cross-asset divergence."}</span>
                    </div>
                  </div>
                </div>
              </details>

              <div className="instrument-card-foot" style={{ marginTop: "12px" }}>
                <span>Options: <strong style={{ color: "#34d399" }}>{session.isOpen ? "ACTIVE (Strikes Computed)" : "STAND ASIDE (Market Closed)"}</strong></span>
                <span>Analysis Engine: <strong style={{ color: "#34d399" }}>VERIFIED</strong></span>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function ManualTradeCard({ instrument, meta, recommendation, dataClass }) {
  const { spots } = useMarketData();
  const [activeTab, setActiveTab] = useState("recommended");
  const [copiedContract, setCopiedContract] = useState("");
  const [watchState, setWatchState] = useState({});
  const session = getMarketSessionInfo(instrument);

  const liveSpot = (spots && (spots[instrument] || (instrument === "CRUDEMINI" ? spots["CRUDEOILMINI"] : null))) ?? recommendation.spot_price;

  async function watchPick(pick) {
    setWatchState((s) => ({ ...s, [pick.contract]: "saving" }));
    try {
      const response = await fetch("/api/watchlist", {
        method: "POST",
        headers: { "content-type": "application/json", "x-csrf-token": csrf() },
        body: JSON.stringify({
          instrument,
          contract: pick.contract,
          option_type: pick.option_type,
          call: recommendation.call || null,
          entry_spot: liveSpot ?? recommendation.spot_price,
          target_points: recommendation.expected_move_points,
          stop_loss_points: recommendation.stop_loss_points,
          data_class: dataClass || null,
          model_premiums: {
            strike: pick.strike,
            moneyness: pick.moneyness,
            delta: pick.delta,
            entry: pick.entry_premium,
            target: pick.target_premium,
            stop_loss: pick.stop_loss_premium,
            lot_size: pick.lot_size,
            estimated: true,
          },
        }),
      });
      setWatchState((s) => ({ ...s, [pick.contract]: response.ok ? "saved" : "error" }));
    } catch {
      setWatchState((s) => ({ ...s, [pick.contract]: "error" }));
    }
  }

  const picks = activeTab === "recommended"
    ? (recommendation.top_5_options || [])
    : (recommendation.alternate_options || []);

  const optType = activeTab === "recommended"
    ? recommendation.option_type
    : recommendation.alt_option_type;

  const isCE = optType === "CE";
  const pillClass = (recommendation.option_type || "").toUpperCase() === "CE"
    ? "ce"
    : (recommendation.option_type || "").toUpperCase() === "PE"
    ? "pe"
    : "neutral";

  const agentVotes = recommendation.agent_votes || [];
  const bullVotes = agentVotes.filter((v) => v.stance?.includes("BULLISH")).length;
  const bearVotes = agentVotes.filter((v) => v.stance?.includes("BEARISH")).length;
  const neutralVotes = agentVotes.length - bullVotes - bearVotes;

  function copyTrade(pick) {
    const text = `${pick.contract} | Entry: ₹${pick.entry_premium} | Target: ₹${pick.target_premium} | SL: ₹${pick.stop_loss_premium} (Lot Size: ${pick.lot_size})`;
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(text);
      setCopiedContract(pick.contract);
      setTimeout(() => setCopiedContract(""), 2500);
    }
  }

  return (
    <div className="manual-trade-box" data-testid={`manual-trade-${instrument}`}>
      {!session.isOpen && (
        <div
          data-testid={`market-closed-banner-${instrument}`}
          style={{
            padding: "10px 14px",
            borderRadius: "8px",
            background: "rgba(245, 158, 11, 0.1)",
            border: "1px solid rgba(245, 158, 11, 0.35)",
            color: "#fbbf24",
            marginBottom: "12px",
            fontSize: "0.82rem",
            display: "flex",
            alignItems: "flex-start",
            gap: "10px",
          }}
        >
          <span style={{ fontSize: "1.2rem", lineHeight: 1 }}>🌙</span>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 750, marginBottom: "3px", fontSize: "0.85rem", color: "#fef3c7" }}>
              {session.exchange} Market Closed · Session ended at {session.closeTimeText}
            </div>
            <div style={{ lineHeight: 1.45, color: "#fde68a", fontSize: "0.78rem" }}>
              {liveSpot != null ? (
                <>
                  Underlying spot <strong>₹{Number(liveSpot).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong> is the <strong>official session closing settlement</strong>.
                </>
              ) : (
                "Market is closed."
              )}{" "}
              Option premiums are Black-Scholes estimates for next open ({session.nextOpenText}). Intraday live order execution is paused.
            </div>
          </div>
        </div>
      )}

      <div className="manual-trade-hero">
        <div>
          <span style={{ fontSize: "0.72rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.06em", display: "block", marginBottom: "2px" }}>
            {session.isOpen ? "Combined Multi-Agent Trade Suggestion" : "Market Status (Execution Paused)"}
          </span>
          <span className={`trade-call-pill ${!session.isOpen ? "neutral" : pillClass}`}>
            {!session.isOpen
              ? "STAND ASIDE (MARKET CLOSED)"
              : (recommendation.call || "STAND ASIDE")}
          </span>
        </div>
        <div style={{ display: "flex", gap: "10px", alignItems: "center", flexWrap: "wrap", fontSize: "0.82rem" }}>
          {liveSpot != null && (
            <div style={{ background: "rgba(255,255,255,0.04)", padding: "4px 10px", borderRadius: "6px", border: "1px solid var(--line)" }}>
              <span style={{ color: "var(--muted)", fontSize: "0.72rem" }}>{!session.isOpen ? "Closing Spot: " : "Spot: "}</span>
              <strong style={{ fontSize: "0.88rem" }}>₹{Number(liveSpot).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong>
            </div>
          )}
          {recommendation.target_spot != null && (
            <div style={{ background: "rgba(16,185,129,0.08)", padding: "4px 10px", borderRadius: "6px", border: "1px solid rgba(16,185,129,0.25)" }}>
              <span style={{ color: "var(--muted)", fontSize: "0.72rem" }}>Target: </span>
              <strong style={{ color: "#34d399", fontSize: "0.88rem" }}>₹{Number(recommendation.target_spot).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong>
              <small style={{ color: "#34d399" }}> (+{recommendation.expected_move_points} pts)</small>
            </div>
          )}
          {recommendation.stop_loss_spot != null && (
            <div style={{ background: "rgba(244,63,94,0.08)", padding: "4px 10px", borderRadius: "6px", border: "1px solid rgba(244,63,94,0.25)" }}>
              <span style={{ color: "var(--muted)", fontSize: "0.72rem" }}>SL: </span>
              <strong style={{ color: "#fb7185", fontSize: "0.88rem" }}>₹{Number(recommendation.stop_loss_spot).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong>
              <small style={{ color: "#fb7185" }}> (-{recommendation.stop_loss_points} pts)</small>
            </div>
          )}
          <span className="bias-badge neutral" style={{ fontWeight: 700, padding: "4px 10px" }}>
            {recommendation.conviction || "MODERATE"} CONVICTION
          </span>
        </div>
      </div>

      {/* Multi-Agent Voting Consensus Matrix */}
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
          <span style={{ fontSize: "0.72rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
            Agent Consensus Breakdown
          </span>
          <div style={{ display: "flex", gap: "8px", fontSize: "0.72rem", fontWeight: 700 }}>
            <span style={{ color: "#34d399" }}>{bullVotes} Bullish</span>
            <span style={{ color: "#fb7185" }}>{bearVotes} Bearish</span>
            {neutralVotes > 0 && <span style={{ color: "#fbbf24" }}>{neutralVotes} Neutral</span>}
          </div>
        </div>
        <div className="consensus-strip" style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
          {agentVotes.map((v, i) => {
            const isBull = v.stance?.includes("BULLISH");
            const isBear = v.stance?.includes("BEARISH");
            return (
              <div
                key={i}
                className="consensus-card"
                title={v.summary}
                style={{
                  padding: "4px 8px",
                  borderRadius: "6px",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "6px",
                  background: isBull ? "rgba(16, 185, 129, 0.08)" : isBear ? "rgba(244, 63, 94, 0.08)" : "rgba(255, 255, 255, 0.04)",
                  border: `1px solid ${isBull ? "rgba(16, 185, 129, 0.25)" : isBear ? "rgba(244, 63, 94, 0.25)" : "var(--line)"}`,
                  fontSize: "0.74rem",
                }}
              >
                <span style={{ color: "var(--muted)", fontWeight: 600 }}>{v.agent}:</span>
                <strong style={{
                  color: isBull ? "#34d399" : isBear ? "#fb7185" : "var(--ink)",
                  fontSize: "0.74rem",
                }}>
                  {v.stance}
                </strong>
              </div>
            );
          })}
        </div>
      </div>

      {/* Quant Fusion Confluence Engine Box */}
      {recommendation.quant_fusion && (
        <div
          data-testid={`quant-fusion-${instrument}`}
          style={{
            margin: "8px 0",
            padding: "10px 14px",
            borderRadius: "8px",
            background: recommendation.quant_fusion.confluence_status === "ALIGNED"
              ? "rgba(16, 185, 129, 0.08)"
              : recommendation.quant_fusion.confluence_status === "DIVERGENCE"
              ? "rgba(244, 63, 94, 0.08)"
              : "rgba(56, 189, 248, 0.08)",
            border: `1px solid ${
              recommendation.quant_fusion.confluence_status === "ALIGNED"
                ? "rgba(16, 185, 129, 0.3)"
                : recommendation.quant_fusion.confluence_status === "DIVERGENCE"
                ? "rgba(244, 63, 94, 0.3)"
                : "rgba(56, 189, 248, 0.3)"
            }`,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: "10px",
          }}
        >
          <div style={{ flex: 1, minWidth: "260px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "2px" }}>
              <span style={{ fontSize: "0.72rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--muted)" }}>
                ⚡ Quant-Agent Fusion:
              </span>
              <strong style={{
                fontSize: "0.8rem",
                color: recommendation.quant_fusion.confluence_status === "ALIGNED" ? "#34d399" : recommendation.quant_fusion.confluence_status === "DIVERGENCE" ? "#fb7185" : "#38bdf8",
              }}>
                {recommendation.quant_fusion.confluence_status === "ALIGNED" ? "🟢 HIGH CONFLUENCE" : recommendation.quant_fusion.confluence_status === "DIVERGENCE" ? "⚠️ DIVERGENCE (VETO RISK)" : "🔵 STANDARD CONFLUENCE"}
              </strong>
            </div>
            <p style={{ margin: 0, fontSize: "0.78rem", color: "var(--ink)", lineHeight: 1.4 }}>
              {recommendation.quant_fusion.confluence_summary}
            </p>
          </div>
          <div style={{ display: "flex", gap: "12px", alignItems: "center", fontSize: "0.78rem" }}>
            <div style={{ textAlign: "right" }}>
              <span style={{ display: "block", color: "var(--muted)", fontSize: "0.68rem", textTransform: "uppercase" }}>ML Walk-Forward:</span>
              <strong style={{ color: "#38bdf8" }}>
                {(recommendation.quant_fusion.model_probability_up * 100).toFixed(1)}% P(Up)
              </strong>
            </div>
            <div style={{ textAlign: "right" }}>
              <span style={{ display: "block", color: "var(--muted)", fontSize: "0.68rem", textTransform: "uppercase" }}>Agent Score:</span>
              <strong style={{ color: recommendation.quant_fusion.agent_score > 0 ? "#34d399" : recommendation.quant_fusion.agent_score < 0 ? "#fb7185" : "inherit" }}>
                {recommendation.quant_fusion.agent_score > 0 ? `+${recommendation.quant_fusion.agent_score}` : recommendation.quant_fusion.agent_score}
              </strong>
            </div>
          </div>
        </div>
      )}

      {/* Option Picks Switcher */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "6px" }}>
        <span style={{ fontSize: "0.72rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
          Top 5 Ranked Strikes {!session.isOpen ? "(Next-Session Model Estimates)" : "for Manual Trade"}
        </span>
        <div className="picks-switcher">
          <button
            type="button"
            className={activeTab === "recommended" ? "active" : ""}
            onClick={() => setActiveTab("recommended")}
          >
            Recommended ({recommendation.option_type || "CE"} · {recommendation.top_5_options?.length || 0} Strikes)
          </button>
          <button
            type="button"
            className={activeTab === "alternate" ? "active" : ""}
            onClick={() => setActiveTab("alternate")}
          >
            Hedge / Alternate ({recommendation.alt_option_type || "PE"} · {recommendation.alternate_options?.length || 0} Strikes)
          </button>
        </div>
      </div>

      {/* Table of 5 Option Strikes or Clean Empty State */}
      {picks.length === 0 ? (
        <div style={{ padding: "16px", background: "var(--surface)", border: "1px dashed var(--border)", borderRadius: "8px", margin: "10px 0", textAlign: "center" }}>
          <p style={{ margin: "0 0 6px 0", fontWeight: 600, color: "var(--muted)", fontSize: "0.85rem" }}>
            No Live Option Chain / Spot Data Available
          </p>
          <p style={{ margin: 0, fontSize: "0.8rem", color: "var(--muted)" }}>
            {recommendation.execution_guide || "Spot price is required to calculate option strikes without assumed data. Connect live Groww feed to load real prices."}
          </p>
        </div>
      ) : (
        <div className="table-wrap" style={{ overflowX: "auto" }}>
          <table className="options-trade-table">
            <thead>
              <tr>
                <th># Strike & Contract</th>
                <th>Moneyness</th>
                <th>Delta</th>
                <th title="Model estimate, not an exchange quote">Est. Entry*</th>
                <th title="Model estimate, not an exchange quote">Est. Target*</th>
                <th title="Model estimate, not an exchange quote">Est. Stop*</th>
                <th>R:R</th>
                <th>1 Lot Capital</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {picks.map((pick) => {
                const isAtm = pick.moneyness === "ATM";
                const isCopied = copiedContract === pick.contract;
                return (
                  <tr key={pick.contract} className={isAtm ? "atm-row" : ""}>
                    <td>
                      <span className={`contract-tag ${isCE ? "ce" : "pe"}`}>
                        {pick.contract}
                      </span>
                      <small style={{ display: "block", color: "var(--muted)", fontSize: "0.7rem" }}>
                        {pick.role}
                      </small>
                    </td>
                    <td>
                      <span className={`bias-badge ${pick.moneyness === "ATM" ? "neutral" : "bullish"}`} style={{ fontSize: "0.7rem", padding: "2px 6px" }}>
                        {pick.moneyness}
                      </span>
                    </td>
                    <td><code>Δ {pick.delta}</code></td>
                    <td><strong>₹{pick.entry_premium}</strong></td>
                    <td><span className="target-val">₹{pick.target_premium}</span></td>
                    <td><span className="sl-val">₹{pick.stop_loss_premium}</span></td>
                    <td><code>{pick.risk_reward}</code></td>
                    <td>
                      <span>₹{Number(pick.capital_per_lot).toLocaleString("en-IN")}</span>
                      <small style={{ display: "block", color: "var(--muted)", fontSize: "0.68rem" }}>
                        Risk ₹{pick.max_loss_per_lot} / Gain ₹{pick.profit_per_lot}
                      </small>
                    </td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      <button
                        type="button"
                        style={{ padding: "3px 8px", fontSize: "0.72rem", borderRadius: "4px" }}
                        onClick={() => copyTrade(pick)}
                      >
                        {isCopied ? "Copied!" : "Copy"}
                      </button>{" "}
                      <button
                        type="button"
                        data-testid={`watch-${pick.contract}`}
                        disabled={watchState[pick.contract] === "saving" || watchState[pick.contract] === "saved"}
                        style={{ padding: "3px 8px", fontSize: "0.72rem", borderRadius: "4px" }}
                        onClick={() => watchPick(pick)}
                        title="Track this suggestion: outcome is judged on the underlying spot reaching target or stop."
                      >
                        {watchState[pick.contract] === "saved" ? "Watching ✓" : watchState[pick.contract] === "saving" ? "Saving…" : watchState[pick.contract] === "error" ? "Retry" : "+ Watch"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="exec-guide">
        💡 <strong>Execution Note:</strong> {!session.isOpen ? `[${session.exchange} CLOSED · Opens ${session.nextOpenText}] ` : ""}{recommendation.execution_guide}
      </p>
    </div>
  );
}
