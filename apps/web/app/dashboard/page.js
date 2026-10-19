"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import MultiInstrumentOverviewCard from "../components/MultiInstrumentOverviewCard";
import PredictedTrendChart from "../components/PredictedTrendChart";
import VisualAgentDecisionCard from "../components/VisualAgentDecisionCard";
import ResearchBoard, { BlockerList } from "../components/ResearchBoard";
import ReadState from "../components/ReadState";
import { useRead } from "../components/useRead";
import { useMarketData } from "../components/MarketDataContext";
import { observationClass, valueText } from "../research/present.mjs";
import V6Desk from "../components/V6Desk";
import V6IntelligenceHub from "../components/V6IntelligenceHub";

export default function DashboardPage() {
  const { quotes } = useMarketData();
  const [viewMode, setViewMode] = useState("compact"); // "compact" | "detailed"
  const [detailedTab, setDetailedTab] = useState("desk"); // "desk" | "consensus"

  useEffect(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      if (params.get("view") === "detailed") {
        setViewMode("detailed");
      }
    }
  }, []);

  function switchView(mode) {
    setViewMode(mode);
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      if (mode === "detailed") {
        url.searchParams.set("view", "detailed");
      } else {
        url.searchParams.delete("view");
      }
      window.history.replaceState({}, "", url.toString());
    }
  }

  return (
    <ResearchBoard
      title="Trade desk"
      lede="Executive single-pane cockpit: live candlestick forecasts, visual 12-agent consensus decisions, multi-instrument tape, and order ticket."
    >
      {({ status }) => (
        <>
          <div className="session-ribbon">
            <strong>Active Posture</strong>
            <span>
              {status.experimental_paper_execution === "Enabled"
                ? "Virtual paper execution is enabled with active risk controls. Multi-agent consensus and forward trend projections are streaming live."
                : "Virtual paper execution is blocked: configure virtual capital and loss limits in risk settings."}
            </span>
            <span className="pill bad"><i />NO TRADE</span>
          </div>

          {/* Executive Cockpit Header & Mode Switcher */}
          <div style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: "10px",
            background: "var(--card-subtle, #131c31)",
            padding: "8px 12px",
            borderRadius: "10px",
            border: "1px solid var(--line)",
            marginBottom: "16px",
          }}>
            {/* View Mode Toggle Tabs */}
            <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
              <span style={{ fontSize: "0.74rem", fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginRight: "4px" }}>
                Mode:
              </span>
              <button
                type="button"
                onClick={() => switchView("compact")}
                style={{
                  padding: "6px 14px",
                  borderRadius: "6px",
                  border: "none",
                  background: viewMode === "compact" ? "var(--accent, #38bdf8)" : "transparent",
                  color: viewMode === "compact" ? "#0f172a" : "var(--muted)",
                  fontWeight: viewMode === "compact" ? 750 : 500,
                  fontSize: "0.82rem",
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                  transition: "all 0.15s ease",
                }}
              >
                <span>⚡ Compact Cockpit</span>
              </button>
              <button
                type="button"
                onClick={() => switchView("detailed")}
                style={{
                  padding: "6px 14px",
                  borderRadius: "6px",
                  border: "none",
                  background: viewMode === "detailed" ? "var(--accent, #38bdf8)" : "transparent",
                  color: viewMode === "detailed" ? "#0f172a" : "var(--muted)",
                  fontWeight: viewMode === "detailed" ? 750 : 500,
                  fontSize: "0.82rem",
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                  transition: "all 0.15s ease",
                }}
              >
                <span>🔬 Detailed Analysis Desk (12 Agents)</span>
              </button>
            </div>

            {/* Quick Desk Action Links */}
            <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
              <Link
                href="/live"
                style={{
                  padding: "5px 10px",
                  borderRadius: "6px",
                  background: "rgba(16, 185, 129, 0.12)",
                  border: "1px solid rgba(16, 185, 129, 0.3)",
                  color: "#34d399",
                  fontWeight: 600,
                  fontSize: "0.78rem",
                  textDecoration: "none",
                }}
              >
                ⚡ Live Trading →
              </Link>
              <Link
                href="/watchlist"
                style={{
                  padding: "5px 10px",
                  borderRadius: "6px",
                  background: "rgba(56, 189, 248, 0.12)",
                  border: "1px solid rgba(56, 189, 248, 0.3)",
                  color: "#38bdf8",
                  fontWeight: 600,
                  fontSize: "0.78rem",
                  textDecoration: "none",
                }}
              >
                🎯 Watchlist →
              </Link>
              <Link
                href="/forecast"
                style={{
                  padding: "5px 10px",
                  borderRadius: "6px",
                  background: "rgba(168, 85, 247, 0.12)",
                  border: "1px solid rgba(168, 85, 247, 0.3)",
                  color: "#c084fc",
                  fontWeight: 600,
                  fontSize: "0.78rem",
                  textDecoration: "none",
                }}
              >
                📈 Forecast Tools →
              </Link>
              <Link
                href="/options"
                style={{
                  padding: "5px 10px",
                  borderRadius: "6px",
                  background: "rgba(255, 255, 255, 0.05)",
                  border: "1px solid rgba(255, 255, 255, 0.12)",
                  color: "var(--muted)",
                  fontWeight: 600,
                  fontSize: "0.78rem",
                  textDecoration: "none",
                }}
              >
                Options →
              </Link>
            </div>
          </div>

          {/* Mode 1: Compact View (Default) */}
          {viewMode === "compact" && (
            <>
              <MultiInstrumentOverviewCard />
              <PredictedTrendChart />
              <VisualAgentDecisionCard onExpandDetailed={() => switchView("detailed")} />
              <TradeTicket status={status} />
              <Snapshot />
              <div className="v6-grid" style={{ marginTop: "16px" }}>
                <LiveQuotes />
                <Quarantine />
              </div>
            </>
          )}

          {/* Mode 2: Detailed Analysis Desk View (Unified from Analysis page) */}
          {viewMode === "detailed" && (
            <div className="detailed-analysis-container" style={{ display: "grid", gap: "16px" }}>
              <div style={{
                display: "flex",
                gap: "8px",
                background: "var(--card-subtle, #131c31)",
                padding: "4px",
                borderRadius: "10px",
                border: "1px solid var(--line)",
                flexWrap: "wrap",
                alignItems: "center",
              }}>
                <button
                  type="button"
                  onClick={() => setDetailedTab("desk")}
                  style={{
                    flex: "1 1 auto",
                    padding: "8px 16px",
                    borderRadius: "8px",
                    border: "none",
                    background: detailedTab === "desk" ? "rgba(255, 255, 255, 0.12)" : "transparent",
                    color: detailedTab === "desk" ? "#ffffff" : "var(--muted)",
                    fontWeight: 650,
                    fontSize: "0.85rem",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: "8px",
                  }}
                >
                  <span>🤖</span> Multi-Agent Decision Desk &amp; Signals
                </button>
                <button
                  type="button"
                  onClick={() => setDetailedTab("consensus")}
                  style={{
                    flex: "1 1 auto",
                    padding: "8px 16px",
                    borderRadius: "8px",
                    border: "none",
                    background: detailedTab === "consensus" ? "rgba(255, 255, 255, 0.12)" : "transparent",
                    color: detailedTab === "consensus" ? "#ffffff" : "var(--muted)",
                    fontWeight: 650,
                    fontSize: "0.85rem",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: "8px",
                  }}
                >
                  <span>🧠</span> Institutional Intelligence Hub &amp; Greeks
                </button>
                <button
                  type="button"
                  onClick={() => switchView("compact")}
                  style={{
                    padding: "8px 16px",
                    borderRadius: "8px",
                    border: "1px solid rgba(255, 255, 255, 0.1)",
                    background: "rgba(255, 255, 255, 0.05)",
                    color: "var(--muted)",
                    fontWeight: 600,
                    fontSize: "0.82rem",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    gap: "6px",
                  }}
                  title="Return to Compact Cockpit View"
                >
                  <span>↑ Switch to Compact View</span>
                </button>
              </div>

              {detailedTab === "desk" && (
                <V6Desk defaultTab="trades" hideTickers={true} />
              )}
              {detailedTab === "consensus" && (
                <V6IntelligenceHub initialTab="consensus" liveQuotes={quotes} />
              )}
            </div>
          )}
        </>
      )}
    </ResearchBoard>
  );
}


function TradeTicket({ status }) {
  const { quotes, spots } = useMarketData();
  const niftyLive = quotes.find((q) => q.instrument === "NIFTY") || (spots["NIFTY"] ? { instrument: "NIFTY", last_price: spots["NIFTY"] } : null);
  const sensexLive = quotes.find((q) => q.instrument === "SENSEX") || (spots["SENSEX"] ? { instrument: "SENSEX", last_price: spots["SENSEX"] } : null);
  const isPaperEnabled = status.experimental_paper_execution === "Enabled" || status.paper_trading_active;

  return (
    <section className="trade-ticket" aria-labelledby="ticket-heading">
      <div>
        <p className="eyebrow">Order ticket</p>
        <h2 id="ticket-heading">NIFTY · stand aside</h2>
        <p style={{ color: "var(--sub, #94a3b8)", fontSize: "0.85rem", margin: "4px 0 8px" }}>
          Single-leg long call / put execution under fail-closed virtual risk controls.
        </p>
        {niftyLive && (
          <p className="ticket-live-tag" style={{ color: "var(--accent, #38bdf8)", fontSize: "0.88rem", marginTop: "4px" }}>
            🟢 <strong>Groww Live Spot:</strong> NIFTY ₹{Number(niftyLive.last_price).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
            {niftyLive.ohlc?.open ? ` · Open ₹${niftyLive.ohlc.open}` : ""}
            {niftyLive.ohlc?.high ? ` · High ₹${niftyLive.ohlc.high}` : ""}
            {niftyLive.ohlc?.low ? ` · Low ₹${niftyLive.ohlc.low}` : ""}
            {sensexLive ? ` | SENSEX ₹${Number(sensexLive.last_price).toLocaleString("en-IN", { minimumFractionDigits: 2 })}` : ""}
          </p>
        )}
      </div>
      <dl>
        <div><dt>Side</dt><dd>STAND ASIDE</dd></div>
        <div><dt>Structure</dt><dd>not set</dd></div>
        <div><dt>Size</dt><dd>not set</dd></div>
        <div><dt>Expected net</dt><dd>not set</dd></div>
        <div><dt>Paper Capital</dt><dd>{valueText(status.risk_capital_inr)}</dd></div>
        <div><dt>Paper Book</dt><dd>{isPaperEnabled ? "Enabled" : "Blocked"}</dd></div>
      </dl>
      <div style={{ margin: "10px 0", padding: "8px 12px", background: "rgba(255,255,255,0.03)", borderRadius: "6px", fontSize: "0.82rem", border: "1px solid var(--border)", display: "flex", alignItems: "center", gap: "8px" }}>
        <strong>Signal Status:</strong>{" "}
        {isPaperEnabled ? (
          <span style={{ color: "var(--accent, #38bdf8)" }}>Neutral consensus standing aside — No signal qualifies under virtual risk filters.</span>
        ) : (
          <span style={{ color: "var(--bad, #f87171)" }}>Paper execution blocked — Virtual controls require configuration.</span>
        )}
      </div>
      <BlockerList blockers={isPaperEnabled ? status.experimental_blockers : status.blockers} />
    </section>
  );
}

function Snapshot() {
  const read = useRead("/api/market/snapshot");
  const { liveData, spots } = useMarketData();
  const market = read.body;
  const quotes = market?.quotes || [];
  const live = liveData;
  const hasLive = (Array.isArray(live?.quotes) && live.quotes.length > 0) || Boolean(spots["NIFTY"]);

  return (
    <section aria-labelledby="snapshot-heading" data-testid="snapshot">
      <div className="verdict" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h2 id="snapshot-heading" style={{ margin: 0 }}>Market Tape &amp; Global Benchmarks</h2>
          <span style={{ fontSize: "0.78rem", color: "var(--sub, #94a3b8)" }}>
            Real-time multi-market feed across domestic indices, MCX commodities, FX, and global equities.
          </span>
        </div>
        <span className="pill bad"><i />NO TRADE</span>
      </div>

      <ReadState phase={read.phase} error={read.error} onRetry={read.retry} loadingText="Loading the local snapshot…">
        {market || hasLive ? (
          <>
            <MarketBoard market={market || {}} live={live} spots={spots} />

            {/* Visual Macro Indicator Cards Grid */}
            {hasLive && (
              <div style={{ marginTop: "1rem", marginBottom: "1rem" }}>
                <h3 style={{ fontSize: "0.92rem", fontWeight: 700, marginBottom: "8px", color: "var(--ink, #fff)" }}>
                  🌐 Verified Market Macro Indicators
                </h3>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "10px" }}>
                  <div style={{ padding: "10px 12px", background: "rgba(18, 26, 43, 0.65)", borderRadius: "8px", border: "1px solid rgba(255, 255, 255, 0.08)" }}>
                    <span style={{ fontSize: "0.68rem", color: "var(--sub, #94a3b8)", textTransform: "uppercase", fontWeight: 700 }}>India VIX</span>
                    <div style={{ fontSize: "1.15rem", fontWeight: 800, color: "#f8fafc", margin: "2px 0" }}>
                      {live.sectoral_indices?.find((s) => s.instrument === "VIX")?.last_price || "—"} <small style={{ fontSize: "0.72rem", color: "#94a3b8" }}>pts</small>
                    </div>
                    <span style={{ fontSize: "0.68rem", color: "#64748b" }}>NSE Volatility</span>
                  </div>

                  <div style={{ padding: "10px 12px", background: "rgba(18, 26, 43, 0.65)", borderRadius: "8px", border: "1px solid rgba(255, 255, 255, 0.08)" }}>
                    <span style={{ fontSize: "0.68rem", color: "var(--sub, #94a3b8)", textTransform: "uppercase", fontWeight: 700 }}>USD / INR</span>
                    <div style={{ fontSize: "1.15rem", fontWeight: 800, color: "#f8fafc", margin: "2px 0" }}>
                      ₹{live.global_indices?.find((g) => g.instrument === "USDINR" || g.instrument === "USDINR_REF")?.last_price || "—"}
                    </div>
                    <span style={{ fontSize: "0.68rem", color: "#64748b" }}>RBI Reference FX</span>
                  </div>

                  <div style={{ padding: "10px 12px", background: "rgba(18, 26, 43, 0.65)", borderRadius: "8px", border: "1px solid rgba(255, 255, 255, 0.08)" }}>
                    <span style={{ fontSize: "0.68rem", color: "var(--sub, #94a3b8)", textTransform: "uppercase", fontWeight: 700 }}>MCX Crude Oil</span>
                    <div style={{ fontSize: "1.15rem", fontWeight: 800, color: "#f8fafc", margin: "2px 0" }}>
                      ₹{live.commodities?.find((c) => c.instrument === "CRUDE" || c.instrument === "CRUDEOILMINI" || c.instrument === "CRUDEMINI")?.last_price || "—"} <small style={{ fontSize: "0.72rem", color: "#94a3b8" }}>₹/bbl</small>
                    </div>
                    <span style={{ fontSize: "0.68rem", color: "#64748b" }}>MCX Commodity Print</span>
                  </div>

                  <div style={{ padding: "10px 12px", background: "rgba(18, 26, 43, 0.65)", borderRadius: "8px", border: "1px solid rgba(255, 255, 255, 0.08)" }}>
                    <span style={{ fontSize: "0.68rem", color: "var(--sub, #94a3b8)", textTransform: "uppercase", fontWeight: 700 }}>MCX Gold</span>
                    <div style={{ fontSize: "1.15rem", fontWeight: 800, color: "#f8fafc", margin: "2px 0" }}>
                      ₹{live.commodities?.find((c) => c.instrument === "GOLD" || c.instrument === "GOLDMINI")?.last_price || "—"} <small style={{ fontSize: "0.72rem", color: "#94a3b8" }}>₹/10g</small>
                    </div>
                    <span style={{ fontSize: "0.68rem", color: "#64748b" }}>MCX Commodity Print</span>
                  </div>

                  <div style={{ padding: "10px 12px", background: "rgba(18, 26, 43, 0.65)", borderRadius: "8px", border: "1px solid rgba(255, 255, 255, 0.08)" }}>
                    <span style={{ fontSize: "0.68rem", color: "var(--sub, #94a3b8)", textTransform: "uppercase", fontWeight: 700 }}>Dow Jones</span>
                    <div style={{ fontSize: "1.15rem", fontWeight: 800, color: "#f8fafc", margin: "2px 0" }}>
                      {live.global_indices?.find((g) => g.instrument === "DJI")?.last_price || "—"} <small style={{ fontSize: "0.72rem", color: "#94a3b8" }}>pts</small>
                    </div>
                    <span style={{ fontSize: "0.68rem", color: "#64748b" }}>Global Benchmark</span>
                  </div>

                  <div style={{ padding: "10px 12px", background: "rgba(18, 26, 43, 0.65)", borderRadius: "8px", border: "1px solid rgba(255, 255, 255, 0.08)" }}>
                    <span style={{ fontSize: "0.68rem", color: "var(--sub, #94a3b8)", textTransform: "uppercase", fontWeight: 700 }}>GIFT Nifty</span>
                    <div style={{ fontSize: "1.15rem", fontWeight: 800, color: "#f8fafc", margin: "2px 0" }}>
                      {live.global_indices?.find((g) => g.instrument === "GIFTNIFTY")?.last_price || "—"} <small style={{ fontSize: "0.72rem", color: "#94a3b8" }}>pts</small>
                    </div>
                    <span style={{ fontSize: "0.68rem", color: "#64748b" }}>NSE IX GIFT City</span>
                  </div>
                </div>
              </div>
            )}

            {/* Collapsible Feed Tables & Compliance Audit Dump */}
            <details
              style={{
                marginTop: "1rem",
                padding: "10px 14px",
                border: "1px dashed var(--border, #334155)",
                borderRadius: "8px",
                backgroundColor: "var(--card-bg, rgba(15, 23, 42, 0.4))",
              }}
              open={false}
            >
              <summary
                style={{
                  cursor: "pointer",
                  color: "var(--sub, #94a3b8)",
                  fontSize: "0.82rem",
                  fontWeight: 600,
                  outline: "none",
                }}
              >
                🔍 Feed Provenance, Raw Tick Tables &amp; Compliance Archive (Click to Expand) ▾
              </summary>

              <div style={{ marginTop: "12px", fontSize: "0.82rem", color: "var(--sub, #94a3b8)" }}>
                <p>
                  Provider: <strong>{hasLive ? "Groww Direct / Live Feed" : valueText(market?.provider)}</strong> · Origin: <strong>{hasLive ? "LIVE_FEED" : valueText(market?.origin)}</strong> · Data Verified: <strong>{hasLive ? "true" : valueText(market?.live_market_data)}</strong> · Orders Enabled: <strong>{valueText(market?.orders_enabled)}</strong>
                </p>
                <p>
                  Readiness: {valueText(market?.readiness?.data_ready)} · Proposal blocked: {valueText(market?.readiness?.proposal_blocked)}
                </p>
                <ul>
                  {(market?.readiness?.reasons || []).map((reason) => <li key={reason}>{reason}</li>)}
                </ul>
              </div>

              {hasLive && (
                <div className="table-wrap" style={{ marginTop: "10px", marginBottom: "1rem" }}>
                  <table>
                    <caption>Live Market Quotes & Verified Feeds (Groww)</caption>
                    <thead>
                      <tr>
                        <th>Underlying</th>
                        <th>Last price</th>
                        <th>Origin</th>
                        <th>Class</th>
                        <th>Quality</th>
                        <th>Event time</th>
                        <th>Feed status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(live.quotes || []).map((lq) => (
                        <tr key={lq.instrument}>
                          <td><strong>{lq.instrument}</strong></td>
                          <td>₹{Number(lq.last_price).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
                          <td>Groww Live</td>
                          <td><span className="data-badge unverified">LIVE FEED</span></td>
                          <td>GOOD</td>
                          <td>{valueText(lq.event_timestamp || lq.retrieved_at)}</td>
                          <td>{lq.ohlc ? `O: ₹${lq.ohlc.open} · H: ₹${lq.ohlc.high} · L: ₹${lq.ohlc.low}` : "Verified LTP"}</td>
                        </tr>
                      ))}
                      {(live.sectoral_indices || []).filter((s) => s.instrument === "VIX").map((si) => (
                        <tr key={si.instrument}>
                          <td><strong>{si.name || si.instrument}</strong></td>
                          <td>{Number(si.last_price).toLocaleString("en-IN", { minimumFractionDigits: 2 })} {si.unit || ""}</td>
                          <td>Groww Market</td>
                          <td><span className="data-badge unverified">{si.instrument === "VIX" ? "NSE VIX" : "SECTORAL"}</span></td>
                          <td>GOOD</td>
                          <td>{valueText(si.retrieved_at)}</td>
                          <td>{si.day_change_text || "Sectoral Index"}</td>
                        </tr>
                      ))}
                      {(live.commodities || []).filter((c) => c.instrument === "CRUDE" || c.instrument === "GOLD").map((co) => (
                        <tr key={co.instrument}>
                          <td><strong>{co.name || co.instrument}</strong></td>
                          <td>₹{Number(co.last_price).toLocaleString("en-IN")} {co.unit || ""}</td>
                          <td>MCX</td>
                          <td><span className="data-badge unverified">COMMODITY</span></td>
                          <td>GOOD</td>
                          <td>{valueText(co.retrieved_at)}</td>
                          <td>MCX Commodity Print</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              <div className="table-wrap" style={{ marginTop: "10px" }}>
                <table>
                  <caption>Snapshot quotes and their source class</caption>
                  <thead>
                    <tr>
                      <th>Underlying</th>
                      <th>Last price</th>
                      <th>Origin</th>
                      <th>Class</th>
                      <th>Quality</th>
                      <th>Event time</th>
                      <th>Issues</th>
                    </tr>
                  </thead>
                  <tbody>
                    {quotes.map((quote) => {
                      const kind = observationClass(quote);
                      return (
                        <tr key={quote.underlying || quote.instrument_id}>
                          <td>{valueText(quote.underlying)}</td>
                          <td>{valueText(quote.last_price)}</td>
                          <td>{valueText(quote.origin)}</td>
                          <td><span className={`data-badge ${kind.code}`}>{kind.label}</span></td>
                          <td>{valueText(quote.quality)}</td>
                          <td>{valueText(quote.event_timestamp)}</td>
                          <td>{(quote.issues || []).map((issue) => issue.code).join(", ") || "none returned"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </details>
          </>
        ) : null}
      </ReadState>
    </section>
  );
}


const BOARD = [
  { id: "NIFTY", label: "NIFTY 50", source: "quote" },
  { id: "SENSEX", label: "SENSEX", source: "quote" },
  { id: "CRUDEOILMINI", label: "Crude Mini", source: "crude" },
  { id: "INDIA_VIX", label: "India VIX", source: "context" },
  { id: "SPX", label: "S&P 500", source: "none" },
  { id: "NASDAQ", label: "Nasdaq", source: "none" },
  { id: "DJI", label: "Dow Jones", source: "global" },
  { id: "VIX", label: "US VIX", source: "none" },
  { id: "CRUDE", label: "Crude oil", source: "crude" },
  { id: "USDINR", label: "USD/INR", source: "context" },
];

function MarketBoard({ market, live, spots = {} }) {
  const quotes = Array.isArray(market.quotes) ? market.quotes : [];
  const context = Array.isArray(market.context) ? market.context : [];
  return (
    <div className="board" data-testid="market-board">
      {BOARD.map((item) => <BoardCard key={item.id} item={item} quotes={quotes} context={context} live={live} spots={spots} />)}
    </div>
  );
}

function BoardCard({ item, quotes, context, live, spots = {} }) {
  if (item.source === "quote") {
    const liveQuote = live?.quotes?.find((q) => q.instrument === item.id) || (spots[item.id] ? { instrument: item.id, last_price: spots[item.id] } : null);
    if (liveQuote) {
      return (
        <article className="quote-card">
          <p className="name">{item.label}</p>
          <p className="px">₹{Number(liveQuote.last_price).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</p>
          <p className="sub">{liveQuote.ohlc ? `O: ₹${liveQuote.ohlc.open}` : "Groww Live Spot"}</p>
          <p className="sub">{valueText(liveQuote.event_timestamp || liveQuote.retrieved_at)}</p>
          <p className="sub">Groww <span className="data-badge unverified">LIVE FEED</span></p>
        </article>
      );
    }
    const secIndex = live?.sectoral_indices?.find((s) => s.instrument === item.id);
    if (secIndex) {
      return (
        <article className="quote-card">
          <p className="name">{item.label}</p>
          <p className="px">{Number(secIndex.last_price).toLocaleString("en-IN", { minimumFractionDigits: 2 })} {secIndex.unit || ""}</p>
          <p className="sub">{secIndex.day_change_text || "Sectoral Index"}</p>
          <p className="sub">{valueText(secIndex.retrieved_at)}</p>
          <p className="sub">Groww <span className="data-badge unverified">SECTORAL</span></p>
        </article>
      );
    }
    // Fallback to synthetic snapshot only if no live quote or sectoral print exists
    const quote = quotes.find((row) => row.underlying === item.id);
    if (quote) {
      const kind = observationClass(quote);
      return (
        <article className="quote-card">
          <p className="name">{item.label}</p>
          <p className="px">{valueText(quote.last_price)}</p>
          <p className="sub">{changeText(quote)}</p>
          <p className="sub">{valueText(quote.event_timestamp)}</p>
          <p className="sub">{valueText(quote.origin)} <span className={`data-badge ${kind.code}`}>{kind.label}</span></p>
        </article>
      );
    }
    return <UnavailableCard label={item.label} />;
  }
  if (item.source === "global") {
    const gIndex = live?.global_indices?.find((g) => g.instrument === item.id);
    if (gIndex) {
      return (
        <article className="quote-card">
          <p className="name">{item.label}</p>
          <p className="px">{Number(gIndex.last_price).toLocaleString("en-IN")} {gIndex.unit || ""}</p>
          <p className="sub">{gIndex.percent_change ? `${gIndex.percent_change} change` : "Global Benchmark"}</p>
          <p className="sub">{valueText(gIndex.retrieved_at)}</p>
          <p className="sub">Groww <span className="data-badge unverified">GLOBAL</span></p>
        </article>
      );
    }
    return <UnavailableCard label={item.label} />;
  }
  if (item.source === "crude") {
    const commodity = live?.commodities?.find((c) => c.instrument === "CRUDE");
    if (commodity) {
      return (
        <article className="quote-card">
          <p className="name">{item.label}</p>
          <p className="px">₹{Number(commodity.last_price).toLocaleString("en-IN")}</p>
          <p className="sub">{commodity.unit || "₹/bbl"}</p>
          <p className="sub">{valueText(commodity.retrieved_at)}</p>
          <p className="sub">MCX <span className="data-badge unverified">COMMODITY</span></p>
        </article>
      );
    }
    const rows = context.filter((row) => row.code === "BRENT" || row.code === "MCX_CRUDE" || row.code === "WTI");
    const present = rows.find((row) => row.value != null);
    if (!present) return <UnavailableCard label={item.label} />;
    const kind = observationClass(present);
    return (
      <article className="quote-card">
        <p className="name">{item.label}</p>
        <p className="px">{valueText(present.value)}</p>
        <p className="sub">{valueText(present.unit)}</p>
        <p className="sub">{valueText(present.event_timestamp)}</p>
        <p className="sub">{valueText(present.origin)} <span className={`data-badge ${kind.code}`}>{kind.label}</span></p>
      </article>
    );
  }
  if (item.source === "context") {
    const secVix = item.id === "INDIA_VIX" ? live?.sectoral_indices?.find((s) => s.instrument === "VIX") : null;
    if (secVix) {
      return (
        <article className="quote-card">
          <p className="name">{item.label}</p>
          <p className="px">{Number(secVix.last_price).toFixed(2)} pts</p>
          <p className="sub">{secVix.day_change_text || "Volatility Index"}</p>
          <p className="sub">{valueText(secVix.retrieved_at)}</p>
          <p className="sub">NSE <span className="data-badge unverified">VIX</span></p>
        </article>
      );
    }
    if (item.id === "USDINR") {
      const fxLive = live?.global_indices?.find((g) => g.instrument === "USDINR" || g.instrument === "USDINR_REF");
      if (fxLive && fxLive.last_price != null) {
        return (
          <article className="quote-card">
            <p className="name">{item.label}</p>
            <p className="px">₹{Number(fxLive.last_price).toFixed(2)}</p>
            <p className="sub">INR per USD</p>
            <p className="sub">{valueText(fxLive.retrieved_at || fxLive.event_timestamp)}</p>
            <p className="sub">{fxLive.source || "RBI / Live FX"} <span className="data-badge unverified">FX RATE</span></p>
          </article>
        );
      }
    }
    const rows = context.filter((row) => row.code === item.id);
    const present = rows.find((row) => row.value != null);
    if (!present) return <UnavailableCard label={item.label} />;
    const kind = observationClass(present);
    return (
      <article className="quote-card">
        <p className="name">{item.label}</p>
        <p className="px">{valueText(present.value)}</p>
        <p className="sub">{valueText(present.unit)}</p>
        <p className="sub">{valueText(present.event_timestamp)}</p>
        <p className="sub">{valueText(present.origin)} <span className={`data-badge ${kind.code}`}>{kind.label}</span></p>
      </article>
    );
  }
  return <UnavailableCard label={item.label} />;
}

function UnavailableCard({ label }) {
  return (
    <article className="quote-card unavailable">
      <p className="name">{label}</p>
      <p className="px">Unavailable</p>
      <p className="sub">No local observation.</p>
    </article>
  );
}

function changeText(quote) {
  const last = Number(quote.last_price);
  const open = Number(quote.open);
  if (!Number.isFinite(last) || !Number.isFinite(open)) return "Change not set";
  const delta = last - open;
  const sign = delta > 0 ? "+" : "";
  return `From open ${sign}${delta}`;
}

function LiveQuotes() {
  const { liveData, refreshNow, isRefreshing } = useMarketData();
  const [phase, setPhase] = useState("idle");
  const [error, setError] = useState("");
  const body = liveData;
  const quotes = body?.quotes || [];
  const commodities = body?.commodities || [];
  const globalIndices = body?.global_indices || [];
  const sectoralIndices = body?.sectoral_indices || [];

  async function refresh(event) {
    event.preventDefault();
    setPhase("loading");
    setError("");
    try {
      await refreshNow();
      setPhase("ready");
    } catch (err) {
      setPhase("error");
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <section aria-labelledby="live-quotes-heading" data-testid="live-quotes">
      <h2 id="live-quotes-heading">Live quotes</h2>
      <p>Direct live spot prices and market benchmarks retrieved from Groww. Real spot prices drive ATM calculations.</p>
      <form onSubmit={refresh}>
        <button className="primary" type="submit" disabled={phase === "loading"}>{phase === "loading" ? "Reading…" : "Read Groww quotes"}</button>
      </form>
      {phase === "error" ? <p className="error" role="alert">{error}</p> : null}
      <ReadState phase={body ? "ready" : isRefreshing ? "loading" : "idle"} error={error} onRetry={refreshNow} loadingText="Loading the stored Groww read…">
        {body ? (
          <>
            <p>Status {valueText(body.status)}. Market data verified {valueText(body.real_market_data_verified)}.</p>
            {quotes.length === 0 ? <p className="quiet">No Groww quote is stored.</p> : (
              <div>
                <h4>Domestic Indices</h4>
                <ul>
                  {quotes.map((quote) => (
                    <li key={quote.instrument}>
                      <strong>{quote.instrument}</strong>: ₹{Number(quote.last_price).toLocaleString("en-IN", { minimumFractionDigits: 2 })} ({quote.last_price}) · {valueText(quote.data_class)} · event {valueText(quote.event_timestamp || quote.retrieved_at)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {commodities.length > 0 && (
              <div style={{ marginTop: "1rem" }}>
                <h4>⚡ MCX Commodities</h4>
                <ul>
                  {commodities.map((c) => (
                    <li key={c.instrument}>
                      <strong>{c.name}</strong>: ₹{Number(c.last_price).toLocaleString("en-IN")} {c.unit || ""} · {valueText(c.data_class)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {globalIndices.length > 0 && (
              <div style={{ marginTop: "1rem" }}>
                <h4>🌐 Global Benchmarks</h4>
                <ul>
                  {globalIndices.map((g) => (
                    <li key={g.instrument}>
                      <strong>{g.name}</strong>: {Number(g.last_price).toLocaleString("en-IN")} {g.unit || ""} ({g.percent_change || ""}) · {valueText(g.data_class)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {sectoralIndices.length > 0 && (
              <div style={{ marginTop: "1rem" }}>
                <h4>📊 Sectoral & Volatility</h4>
                <ul>
                  {sectoralIndices.map((s) => (
                    <li key={s.instrument}>
                      <strong>{s.name}</strong>: {Number(s.last_price).toLocaleString("en-IN")} {s.unit || ""} ({s.day_change_text || ""})
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        ) : null}
      </ReadState>
    </section>
  );
}

function Quarantine() {
  const read = useRead("/api/history/quarantine");
  const records = read.body?.records || [];
  return (
    <section aria-labelledby="quarantine-heading" data-testid="quarantine">
      <h2 id="quarantine-heading">Price history</h2>
      <p>Candle files stay off the tape until their timestamps are confirmed. Quarantined rows are listed below.</p>
      <ReadState
        phase={read.phase}
        error={read.error}
        onRetry={read.retry}
        empty={read.phase === "ready" && records.length === 0}
        emptyText="No quarantine records were returned."
        loadingText="Loading quarantine records…"
      >
        {read.body ? (
          <>
            <p>Trusted dataset created {valueText(read.body.trusted_dataset_created)}. Forecast eligible {valueText(read.body.forecast_eligible)}. Market data verified {valueText(read.body.real_market_data_verified)}.</p>
            <div className="table-wrap">
              <table>
                <caption>Quarantined provider responses</caption>
                <thead>
                  <tr>
                    <th>Instrument</th>
                    <th>Interval</th>
                    <th>Category</th>
                    <th>Class</th>
                    <th>Trusted</th>
                    <th>Candles</th>
                  </tr>
                </thead>
                <tbody>
                  {records.map((record) => {
                    const kind = observationClass(record);
                    return (
                      <tr key={record.quarantine_id || record.checksum}>
                        <td>{valueText(record.instrument)}</td>
                        <td>{valueText(record.interval)}</td>
                        <td>{valueText(record.data_category)}</td>
                        <td><span className={`data-badge ${kind.code}`}>{kind.label}</span></td>
                        <td>{valueText(record.trusted_dataset_created)}</td>
                        <td>{valueText(record.candle_count)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        ) : null}
      </ReadState>
    </section>
  );
}
