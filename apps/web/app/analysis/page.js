"use client";

import { useState } from "react";
import ResearchBoard from "../components/ResearchBoard";
import V6Desk from "../components/V6Desk";
import V6IntelligenceHub from "../components/V6IntelligenceHub";
import InstrumentSelector from "../components/InstrumentSelector";
import InstrumentForecastCard from "../components/InstrumentForecastCard";
import NewsSourcesManager from "../components/NewsSourcesManager";
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
          {/* Top Compact Instrument Switcher */}
          <div style={{ marginBottom: "16px" }}>
            <InstrumentSelector compact={true} />
          </div>

          {/* Analysis View Mode Navigation to eliminate endless vertical scrolling */}
          <div style={{
            display: "flex",
            gap: "8px",
            background: "var(--card-subtle, #131c31)",
            padding: "4px",
            borderRadius: "10px",
            border: "1px solid var(--line)",
            marginBottom: "20px",
            flexWrap: "wrap",
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
            <button
              type="button"
              onClick={() => setActiveTab("forecast")}
              style={{
                flex: "1 1 auto",
                padding: "8px 16px",
                borderRadius: "8px",
                border: "none",
                background: activeTab === "forecast" ? "rgba(255, 255, 255, 0.12)" : "transparent",
                color: activeTab === "forecast" ? "#ffffff" : "var(--muted)",
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
              <span>📈</span> Multi-Horizon Statistical Forecasts
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("news-config")}
              style={{
                flex: "1 1 auto",
                padding: "8px 16px",
                borderRadius: "8px",
                border: "none",
                background: activeTab === "news-config" ? "rgba(255, 255, 255, 0.12)" : "transparent",
                color: activeTab === "news-config" ? "#ffffff" : "var(--muted)",
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
              <span>📰</span> News Agent Web Feeds
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("all")}
              style={{
                padding: "8px 14px",
                borderRadius: "8px",
                border: "none",
                background: activeTab === "all" ? "rgba(255, 255, 255, 0.12)" : "transparent",
                color: activeTab === "all" ? "#ffffff" : "var(--muted)",
                fontWeight: 650,
                fontSize: "0.85rem",
                cursor: "pointer",
                transition: "all 0.15s ease",
              }}
              title="View all components stacked"
            >
              📄 Expanded View
            </button>
          </div>

          {/* Tab 1: Primary Multi-Agent Decision Desk (Right at the top!) */}
          {(activeTab === "desk" || activeTab === "all") && (
            <V6Desk defaultTab="trades" hideTickers={true} />
          )}

          {/* Tab 2: Institutional Intelligence Hub (Greeks, Multi-Asset, 8-Gate) */}
          {(activeTab === "consensus" || activeTab === "all") && (
            <V6IntelligenceHub initialTab="consensus" liveQuotes={quotes} />
          )}

          {/* Tab 3: Multi-Horizon Statistical Forecasts */}
          {(activeTab === "forecast" || activeTab === "all") && (
            <>
              <InstrumentSelector compact={false} />
              <InstrumentForecastCard />
            </>
          )}

          {/* Tab 4: News Agent Web Feeds Configuration */}
          {(activeTab === "news-config" || activeTab === "all") && (
            <NewsSourcesManager />
          )}
        </>
      )}
    </ResearchBoard>
  );
}
