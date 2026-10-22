"use client";

import { useMarketData } from "./MarketDataContext";

export default function InstrumentSelector({ compact = false }) {
  const {
    selectedInstrument,
    setSelectedInstrument,
    supportedInstruments,
    instrumentConfig,
    spots,
    isEquityOpen,
    isCommodityOpen,
  } = useMarketData();

  const activeId = selectedInstrument || "NIFTY";
  const cfg = instrumentConfig || {};
  const currentSpot = spots[activeId] || (activeId === "CRUDEOILMINI" ? spots["CRUDEMINI"] : null);

  const isOpen = activeId === "CRUDEOILMINI" ? isCommodityOpen : isEquityOpen;

  if (compact) {
    return (
      <div className="v6-instrument-selector-compact" data-testid="compact-instrument-selector">
        <div className="v6-selector-pills">
          {(supportedInstruments || []).map((inst) => {
            const isSelected = inst.id === activeId;
            const price = spots[inst.id] || (inst.id === "CRUDEOILMINI" ? spots["CRUDEMINI"] : null);
            return (
              <button
                key={inst.id}
                type="button"
                className={`v6-selector-pill ${isSelected ? "active" : ""}`}
                onClick={() => setSelectedInstrument(inst.id)}
                title={`${inst.name} (${inst.exchange})`}
              >
                <span className="v6-pill-sym">{inst.name}</span>
                {price != null && (
                  <span className="v6-pill-price">₹{Number(price).toLocaleString("en-IN")}</span>
                )}
                <span className={`v6-pill-status-dot ${inst.id === "CRUDEOILMINI" ? (isCommodityOpen ? "open" : "closed") : (isEquityOpen ? "open" : "closed")}`} />
              </button>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div className="v6-instrument-selector-panel" data-testid="global-instrument-selector">
      <div className="v6-selector-header">
        <div>
          <span className="v6-badge-sub">Unified Multi-Instrument Suite</span>
          <h3 className="v6-panel-title">Active Tradable Instrument Selector</h3>
        </div>
        <div className="v6-selector-tabs">
          {(supportedInstruments || []).map((inst) => {
            const isSelected = inst.id === activeId;
            return (
              <button
                key={inst.id}
                type="button"
                className={`v6-tab-btn ${isSelected ? "active" : ""}`}
                onClick={() => setSelectedInstrument(inst.id)}
              >
                <strong>{inst.name}</strong>
                <small>{inst.exchange} • Lot: {inst.contract_lot_size ?? "N/A"}</small>
              </button>
            );
          })}
        </div>
      </div>

      <div className="v6-instrument-metadata-grid">
        <div className="v6-meta-cell">
          <span className="v6-meta-label">Selected Instrument</span>
          <div className="v6-meta-val cyan-text">
            <strong>{cfg.name || activeId}</strong>
            <span className="v6-pill indigo">{cfg.exchange} {cfg.segment}</span>
          </div>
          <small className="v6-meta-sub">Lot Size: {cfg.contract_lot_size ?? "N/A"} units • Strike Step: {cfg.strike_step != null ? `₹${cfg.strike_step}` : "N/A"}</small>
        </div>

        <div className="v6-meta-cell">
          <span className="v6-meta-label">Trading Session Clock</span>
          <div className="v6-meta-val">
            <span className={`v6-pill ${isOpen ? "emerald" : "amber"}`}>
              {isOpen ? "SESSION OPEN" : "SESSION CLOSED"}
            </span>
          </div>
          <small className="v6-meta-sub">{cfg.session || cfg.session_timings} ({cfg.sessionType || cfg.session_type})</small>
        </div>

        <div className="v6-meta-cell">
          <span className="v6-meta-label">Actual Data Source</span>
          <div className="v6-meta-val">{cfg.dataSource || cfg.data_source}</div>
          <small className="v6-meta-sub">Freshness: {cfg.dataFreshness || cfg.data_freshness}</small>
        </div>

        <div className="v6-meta-cell">
          <span className="v6-meta-label">Available History Depth</span>
          <div className="v6-meta-val">{cfg.availableHistory || cfg.available_history}</div>
          <small className="v6-meta-sub">Horizons: {(cfg.forecastHorizons || cfg.forecast_horizons || []).join(" • ")}</small>
        </div>

        <div className="v6-meta-cell">
          <span className="v6-meta-label">Options Analytics</span>
          <div className="v6-meta-val">
            <span className={`v6-pill ${cfg.optionsSupported ?? cfg.options_supported ? "emerald" : "rose"}`}>
              {cfg.optionsSupported ?? cfg.options_supported ? "SUPPORTED" : "DISABLED (FEED GAP)"}
            </span>
          </div>
          <small className="v6-meta-sub">{cfg.optionsNote || cfg.options_note}</small>
        </div>

        <div className="v6-meta-cell">
          <span className="v6-meta-label">Model Validation Status</span>
          <div className="v6-meta-val">
            {cfg.validationStatus === "VERIFIED_RESEARCH_DATASET" ? (
              <span className="v6-pill emerald">VERIFIED RESEARCH</span>
            ) : cfg.validationStatus === "INDEPENDENT_PROVENANCE_REQUIRED" ? (
              <span className="v6-pill amber">INDEPENDENT DATA REQUIRED</span>
            ) : (
              <span className="v6-pill rose">DATA FEED GAP</span>
            )}
          </div>
          <small className="v6-meta-sub">
            {cfg.validationStatus === "VERIFIED_RESEARCH_DATASET"
              ? "19-Fold Walk-Forward Verified"
              : cfg.validationStatus === "INDEPENDENT_PROVENANCE_REQUIRED"
              ? "BSE Holdout Required Before Model Claims"
              : "Groww API does not provide MCX commodity candles"}
          </small>
        </div>
      </div>
    </div>
  );
}
