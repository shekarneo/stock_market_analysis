"use client";

import { useState } from "react";
import Link from "next/link";
import ResearchBoard from "../components/ResearchBoard";
import V6Desk from "../components/V6Desk";
import V6IntelligenceHub from "../components/V6IntelligenceHub";
import { useMarketData } from "../components/MarketDataContext";

export default function AnalysisPage() {
  const { quotes } = useMarketData();
  const [activeTab, setActiveTab] = useState("desk");

  return (
    <ResearchBoard
      title="Multi-Agent Analysis Desk"
      lede="12 specialist agents synthesize technical regimes, order flows, macro indicators, and Bayesian uncertainty gates to formulate unified market consensus."
    >
      {() => (
        <>
          {/* Streamlined 2-View Mode Bar + Direct Links to Dedicated Desks */}
          <div style={{
            display: "flex",
            gap: "8px",
            background: "var(--card-subtle, #131c31)",
            padding: "4px",
            borderRadius: "10px",
            border: "1px solid var(--line)",
            marginBottom: "20px",
            flexWrap: "wrap",
            alignItems: "center",
          }}>
            <button
              type="button"
              onClick={() => setActiveTab("desk")}
              style={{
                flex: "1 1 auto",
                padding: "8px 16px",
                borderRadius: "8px",
                border: "none",
                background: activeTab === "desk" ? "rgba(255, 255, 255, 0.12)" : "transparent",
                color: activeTab === "desk" ? "#ffffff" : "var(--muted)",
                fontWeight: 650,
                fontSize: "0.85rem",
                cursor: "pointer",
                transition: "all 0.15s ease",
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
              onClick={() => setActiveTab("consensus")}
              style={{
                flex: "1 1 auto",
                padding: "8px 16px",
                borderRadius: "8px",
                border: "none",
                background: activeTab === "consensus" ? "rgba(255, 255, 255, 0.12)" : "transparent",
                color: activeTab === "consensus" ? "#ffffff" : "var(--muted)",
                fontWeight: 650,
                fontSize: "0.85rem",
                cursor: "pointer",
                transition: "all 0.15s ease",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "8px",
              }}
            >
              <span>🧠</span> Institutional Intelligence Hub &amp; Greeks
            </button>
            <Link
              href="/forecast"
              style={{
                padding: "8px 14px",
                borderRadius: "8px",
                color: "#c084fc",
                fontWeight: 600,
                fontSize: "0.82rem",
                textDecoration: "none",
                display: "flex",
                alignItems: "center",
                gap: "6px",
              }}
              title="Open dedicated Multi-Horizon Statistical Forecasts & Out-of-Sample Accuracy Desk"
            >
              <span>📈</span> Forecasts &amp; Accuracy →
            </Link>
            <Link
              href="/live"
              style={{
                padding: "8px 14px",
                borderRadius: "8px",
                color: "#34d399",
                fontWeight: 600,
                fontSize: "0.82rem",
                textDecoration: "none",
                display: "flex",
                alignItems: "center",
                gap: "6px",
              }}
              title="Open Live & Auto Trading Desk"
            >
              <span>⚡</span> Live Desk →
            </Link>
          </div>

          {/* View 1: Primary Multi-Agent Decision Desk */}
          {activeTab === "desk" && (
            <V6Desk defaultTab="trades" hideTickers={true} />
          )}

          {/* View 2: Institutional Intelligence Hub (Greeks, Multi-Asset, 8-Gate) */}
          {activeTab === "consensus" && (
            <V6IntelligenceHub initialTab="consensus" liveQuotes={quotes} />
          )}
        </>
      )}
    </ResearchBoard>
  );
}
