"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useMarketData } from "./MarketDataContext";
import { signOut, useSession } from "./session";
import InstrumentSelector from "./InstrumentSelector";

const DESK = [
  { href: "/dashboard", label: "Overview" },
  { href: "/analysis", label: "Analysis" },
  { href: "/live", label: "Live & Auto Trading" },
  { href: "/watchlist", label: "Watchlist & Accuracy" },
  { href: "/forecast", label: "Forecast" },
  { href: "/options", label: "Options" },
  { href: "/risk", label: "Positions & Capital" },
  { href: "/system", label: "System" },
];

const TOOLS = [
  { href: "/history", label: "Market Data & History", matchPaths: ["/history"] },
  { href: "/backtest", label: "Backtest & Walk-Forward", matchPaths: ["/backtest", "/paper"] },
  { href: "/studio", label: "Model Studio & Registry", matchPaths: ["/studio", "/registry"] },
  { href: "/settings/integrations", label: "Settings & API Keys", matchPaths: ["/settings/integrations", "/integrations", "/settings"] },
];

export default function Shell({ children }) {
  const path = usePathname();
  const session = useSession();
  const isToolActive = TOOLS.some((t) => t.matchPaths.includes(path));
  const [showTools, setShowTools] = useState(isToolActive);
  const {
    spots,
    retrievedAt,
    pollConfig,
    setPollInterval,
    togglePolling,
    refreshNow,
    isRefreshing,
    isEquityOpen,
    isCommodityOpen,
    postCloseMode,
  } = useMarketData();

  async function leave() {
    await signOut();
    window.location.assign("/");
  }
  return (
    <div className="shell">
      <a className="skip" href="#content">Skip to content</a>
      <aside className="rail">
        <div className="brand">
          <span className="brand-mark">IMM</span>
          <div>
            <strong>India Market Master</strong>
            <small>Analysis and trading</small>
          </div>
        </div>
        <nav className="rail-nav" aria-label="Research pages">
          <p className="nav-label">Trade</p>
          {DESK.map((link) => (
            <Link key={link.href} href={link.href} className={path === link.href ? "active" : undefined} aria-current={path === link.href ? "page" : undefined}>
              {link.label}
            </Link>
          ))}
          <div style={{ marginTop: "12px", borderTop: "1px solid rgba(255, 255, 255, 0.06)", paddingTop: "8px" }}>
            <button
              type="button"
              onClick={() => setShowTools((prev) => !prev)}
              className="nav-label"
              style={{
                background: "transparent",
                border: "none",
                cursor: "pointer",
                padding: "4px 12px",
                margin: 0,
                width: "100%",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                textAlign: "left",
                color: "#9aab9f",
              }}
            >
              <span>Tools</span>
              <span style={{ fontSize: "0.65rem", opacity: 0.7, textTransform: "none", letterSpacing: "normal" }}>
                {showTools ? "Hide ▴" : `Show (${TOOLS.length}) ▾`}
              </span>
            </button>
            {showTools && (
              <div style={{ display: "flex", flexDirection: "column", gap: "2px", marginTop: "4px" }}>
                {TOOLS.map((link) => {
                  const active = link.matchPaths.includes(path);
                  return (
                    <Link key={link.href} href={link.href} className={active ? "active" : undefined} aria-current={path === link.href ? "page" : undefined}>
                      {link.label}
                    </Link>
                  );
                })}
              </div>
            )}
          </div>
        </nav>
        <div className="rail-account">
          {session.actor ? (
            <>
              <p>Signed in as {session.me?.display_name || session.actor}</p>
              <button type="button" onClick={leave}>Log out</button>
            </>
          ) : (
            <Link href="/">Sign in</Link>
          )}
        </div>
        <p className="rail-note">The book is standing aside. This desk shows the call and does not send an order.</p>
      </aside>
      <div className="canvas" id="content">
        {/* Global Live Market Sync Bar - Shared across all pages */}
        <header
          style={{
            background: "rgba(9, 13, 22, 0.88)",
            backdropFilter: "blur(12px)",
            WebkitBackdropFilter: "blur(12px)",
            borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
            padding: "8px 20px",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: "10px",
            fontSize: "0.82rem",
            position: "sticky",
            top: 0,
            zIndex: 100,
            boxShadow: "0 4px 20px rgba(0,0,0,0.35)",
          }}
        >
          {/* Real-time Ticker across all instruments */}
          <div style={{ display: "flex", alignItems: "center", gap: "16px", flexWrap: "wrap" }}>
            {isEquityOpen ? (
              <span style={{ display: "inline-flex", alignItems: "center", gap: "6px", fontWeight: 700, color: "#4ade80", fontSize: "0.78rem" }}>
                <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#22c55e", boxShadow: "0 0 8px #4ade80" }} />
                NSE/BSE LIVE SESSION
              </span>
            ) : isCommodityOpen ? (
              <span style={{ display: "inline-flex", alignItems: "center", gap: "6px", fontWeight: 700, color: "#facc15", fontSize: "0.78rem" }}>
                <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#eab308", boxShadow: "0 0 8px #fde047" }} />
                ⚡ MCX LIVE · EQUITY CLOSED
              </span>
            ) : (
              <span style={{ display: "inline-flex", alignItems: "center", gap: "6px", fontWeight: 700, color: "#94a3b8", fontSize: "0.78rem" }}>
                <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#64748b" }} />
                🌙 MARKETS CLOSED (POST-CLOSE CONTEXT)
              </span>
            )}
            {/* Global Compact Instrument Selector & Ticker */}
            <InstrumentSelector compact />
          </div>

          {/* Sync status, Auto-fetch config interval & Refresh Now button */}
          <div style={{ display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap" }}>
            <span style={{ color: "var(--muted)", fontSize: "0.74rem" }}>
              {retrievedAt ? `Synced ${new Date(retrievedAt).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit" })}` : "Synced"}
            </span>

            {/* Config Setting for automatic polling interval */}
            <div style={{ display: "flex", alignItems: "center", gap: "5px" }}>
              <label htmlFor="poll-interval-select" style={{ fontSize: "0.72rem", color: "var(--muted)" }}>Auto-fetch:</label>
              <select
                id="poll-interval-select"
                value={pollConfig.enabled ? String(pollConfig.interval_seconds) : "0"}
                onChange={(e) => {
                  const val = parseInt(e.target.value, 10);
                  if (val === 0) {
                    togglePolling();
                  } else {
                    setPollInterval(val);
                  }
                }}
                style={{
                  fontSize: "0.74rem",
                  padding: "4px 8px",
                  borderRadius: "6px",
                  border: "1px solid rgba(255, 255, 255, 0.16)",
                  background: "#0f172a",
                  color: "#f8fafc",
                  cursor: "pointer",
                  outline: "none",
                }}
              >
                <option value="15" style={{ background: "#0f172a", color: "#f8fafc" }}>Every 15s (Fast)</option>
                <option value="30" style={{ background: "#0f172a", color: "#f8fafc" }}>Every 30s</option>
                <option value="60" style={{ background: "#0f172a", color: "#f8fafc" }}>Every 1 min</option>
                <option value="120" style={{ background: "#0f172a", color: "#f8fafc" }}>Every 2 mins</option>
                <option value="300" style={{ background: "#0f172a", color: "#f8fafc" }}>Every 5 mins</option>
                <option value="0" style={{ background: "#0f172a", color: "#f8fafc" }}>Paused</option>
              </select>
            </div>

            <button
              type="button"
              onClick={refreshNow}
              disabled={isRefreshing}
              style={{
                background: "#0f172a",
                color: "#ffffff",
                border: "1px solid rgba(255, 255, 255, 0.16)",
                borderRadius: "6px",
                padding: "4px 10px",
                fontSize: "0.75rem",
                fontWeight: 600,
                cursor: "pointer",
                transition: "opacity 0.2s",
              }}
              title="Fetch latest Groww quotes and sync every open page immediately"
            >
              {isRefreshing ? "↻ Syncing…" : "↻ Fetch Now"}
            </button>
          </div>
        </header>

        {children}
      </div>
    </div>
  );
}

