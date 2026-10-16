"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useMarketData } from "./MarketDataContext";
import { signOut, useSession } from "./session";

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
  { href: "/history", label: "Market data" },
  { href: "/studio", label: "Model studio" },
  { href: "/backtest", label: "Walk-forward" },
  { href: "/registry", label: "Registry" },
  { href: "/paper", label: "Paper book" },
  { href: "/settings", label: "Account" },
  { href: "/settings/integrations", label: "API keys" },
];

export default function Shell({ children }) {
  const path = usePathname();
  const session = useSession();
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
          <p className="nav-label">Tools</p>
          {TOOLS.map((link) => (
            <Link key={link.href} href={link.href} className={path === link.href ? "active" : undefined} aria-current={path === link.href ? "page" : undefined}>
              {link.label}
            </Link>
          ))}
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
            background: "#ffffff",
            borderBottom: "1px solid #e2e8f0",
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
            boxShadow: "0 1px 2px rgba(0,0,0,0.03)",
          }}
        >
          {/* Real-time Ticker across all instruments */}
          <div style={{ display: "flex", alignItems: "center", gap: "16px", flexWrap: "wrap" }}>
            {isEquityOpen ? (
              <span style={{ display: "inline-flex", alignItems: "center", gap: "6px", fontWeight: 700, color: "#166534", fontSize: "0.78rem" }}>
                <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#16a34a", boxShadow: "0 0 6px #86efac" }} />
                NSE/BSE LIVE SESSION
              </span>
            ) : isCommodityOpen ? (
              <span style={{ display: "inline-flex", alignItems: "center", gap: "6px", fontWeight: 700, color: "#854d0e", fontSize: "0.78rem" }}>
                <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#eab308", boxShadow: "0 0 6px #fde047" }} />
                ⚡ MCX LIVE · EQUITY CLOSED
              </span>
            ) : (
              <span style={{ display: "inline-flex", alignItems: "center", gap: "6px", fontWeight: 700, color: "#475569", fontSize: "0.78rem" }}>
                <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#94a3b8" }} />
                🌙 MARKETS CLOSED (POST-CLOSE CONTEXT)
              </span>
            )}
            <div style={{ display: "flex", gap: "14px", alignItems: "center", fontSize: "0.82rem" }}>
              <span>
                NIFTY {!isEquityOpen && <small style={{ color: "var(--muted)" }}>(Close)</small>}: <strong style={{ color: "#0f172a" }}>₹{Number(spots.NIFTY || 0).toLocaleString("en-IN", { minimumFractionDigits: 1, maximumFractionDigits: 2 })}</strong>
              </span>
              <span>
                SENSEX {!isEquityOpen && <small style={{ color: "var(--muted)" }}>(Close)</small>}: <strong style={{ color: "#0f172a" }}>₹{Number(spots.SENSEX || 0).toLocaleString("en-IN", { minimumFractionDigits: 1, maximumFractionDigits: 2 })}</strong>
              </span>
              <span>
                CRUDE MINI {isCommodityOpen ? <span style={{ color: "#16a34a", fontSize: "0.7rem", fontWeight: 700 }}>● LIVE</span> : <small style={{ color: "var(--muted)" }}>(Close)</small>}: <strong style={{ color: "#0f172a" }}>₹{Number(spots.CRUDEOILMINI || spots.CRUDEMINI || 0).toLocaleString("en-IN", { minimumFractionDigits: 1, maximumFractionDigits: 2 })}</strong>
              </span>
            </div>
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
                  padding: "3px 6px",
                  borderRadius: "6px",
                  border: "1px solid #cbd5e1",
                  background: "#f8fafc",
                  cursor: "pointer",
                }}
              >
                <option value="15">Every 15s (Fast)</option>
                <option value="30">Every 30s</option>
                <option value="60">Every 1 min</option>
                <option value="120">Every 2 mins</option>
                <option value="300">Every 5 mins</option>
                <option value="0">Paused</option>
              </select>
            </div>

            <button
              type="button"
              onClick={refreshNow}
              disabled={isRefreshing}
              style={{
                background: "#0f172a",
                color: "#ffffff",
                border: "none",
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

