"use client";

import { useState } from "react";
import V6ConsensusCard from "./V6ConsensusCard";
import V6OptionsGreeksCard from "./V6OptionsGreeksCard";
import V6MultiAssetCard from "./V6MultiAssetCard";
import V6ReadinessAuditCard from "./V6ReadinessAuditCard";

export default function V6IntelligenceHub({ initialTab = "consensus", liveQuotes = [] }) {
  const [activeTab, setActiveTab] = useState(initialTab);

  return (
    <section className="v6-intelligence-hub" aria-labelledby="v6-hub-heading">
      <div className="v6-hub-nav-bar">
        <div className="v6-hub-title-group">
          <span className="v6-hub-brand-badge">V6 CORE INTELLIGENCE</span>
          <h2 id="v6-hub-heading">Institutional Multi-Asset Decision Desk</h2>
        </div>

        <div className="v6-hub-tab-buttons">
          <button
            type="button"
            className={`v6-hub-tab-btn ${activeTab === "consensus" ? "active" : ""}`}
            onClick={() => setActiveTab("consensus")}
          >
            <span>🤖</span> Multi-Agent Consensus
          </button>
          <button
            type="button"
            className={`v6-hub-tab-btn ${activeTab === "options" ? "active" : ""}`}
            onClick={() => setActiveTab("options")}
          >
            <span>⚡</span> Black-76 Options Greeks
          </button>
          <button
            type="button"
            className={`v6-hub-tab-btn ${activeTab === "multiasset" ? "active" : ""}`}
            onClick={() => setActiveTab("multiasset")}
          >
            <span>📊</span> Multi-Asset & Factor Attribution
          </button>
          <button
            type="button"
            className={`v6-hub-tab-btn ${activeTab === "audit" ? "active" : ""}`}
            onClick={() => setActiveTab("audit")}
          >
            <span>🛡️</span> 8-Gate Paper Readiness
          </button>
        </div>
      </div>

      <div className="v6-hub-tab-panel">
        {activeTab === "consensus" && <V6ConsensusCard />}
        {activeTab === "options" && <V6OptionsGreeksCard liveQuotes={liveQuotes} />}
        {activeTab === "multiasset" && <V6MultiAssetCard />}
        {activeTab === "audit" && <V6ReadinessAuditCard />}
      </div>
    </section>
  );
}
