"use client";

import { useMarketData } from "./MarketDataContext";

export default function MultiInstrumentOverviewCard() {
  const {
    selectedInstrument,
    setSelectedInstrument,
    supportedInstruments,
    spots,
    quotes,
    commodities,
    isEquityOpen,
    isCommodityOpen,
  } = useMarketData();

  return (
    <div className="v6-card" data-testid="multi-instrument-overview-card">
      <div className="v6-card-header">
        <div>
          <span className="v6-badge-sub">Unified Multi-Instrument Platform</span>
          <h2 className="v6-card-title">Cross-Market Tradable Instruments Overview</h2>
        </div>
        <div className="v6-header-tags">
          <span className="v6-pill cyan">3 PRIMARY INSTRUMENTS</span>
          <span className="v6-pill rose">LIVE CAPITAL LOCKED</span>
        </div>
      </div>

      <p className="v6-section-desc">
        Real-time multi-market monitoring across Indian Equities (NSE/BSE) and Commodities (MCX).
        Each instrument operates an independent data pipeline and forecasting model. Select any instrument
        to switch the platform&apos;s analytical context.
      </p>

      <div className="v6-multi-instrument-grid">
        {(supportedInstruments || []).map((inst) => {
          const isSelected = inst.id === selectedInstrument;
          const price = spots[inst.id] || (inst.id === "CRUDEOILMINI" ? spots["CRUDEMINI"] : null);
          const isOpen = inst.id === "CRUDEOILMINI" ? isCommodityOpen : isEquityOpen;

          return (
            <div
              key={inst.id}
              className={`v6-instrument-card ${isSelected ? "selected-card" : ""}`}
              onClick={() => setSelectedInstrument(inst.id)}
            >
              <div className="v6-inst-card-top">
                <div>
                  <span className="v6-inst-exchange">{inst.exchange} • {inst.segment}</span>
                  <h3 className="v6-inst-name">{inst.name}</h3>
                </div>
                <span className={`v6-pill ${isOpen ? "emerald" : "amber"}`}>
                  {isOpen ? "OPEN" : "CLOSED"}
                </span>
              </div>

              <div className="v6-inst-price-box">
                <span className="v6-inst-price-label">Live Spot / LTP</span>
                <div className="v6-inst-price-val">
                  {price != null ? `₹${Number(price).toLocaleString("en-IN", { minimumFractionDigits: 1, maximumFractionDigits: 2 })}` : "Fetching…"}
                </div>
                <small className="v6-inst-lot">Contract Lot: {inst.contract_lot_size ?? "N/A"} units</small>
              </div>

              <div className="v6-inst-meta-rows">
                <div className="v6-meta-row">
                  <span>Trading Hours</span>
                  <strong>{inst.session || inst.session_timings}</strong>
                </div>
                <div className="v6-meta-row">
                  <span>Data Source</span>
                  <span>{inst.dataSource || inst.data_source}</span>
                </div>
                <div className="v6-meta-row">
                  <span>Options Analytics</span>
                  <span className={inst.optionsSupported ?? inst.options_supported ? "emerald-text" : "rose-text"}>
                    {inst.optionsSupported ?? inst.options_supported ? "Black-76 Greeks Active" : "Disabled (Feed Gap)"}
                  </span>
                </div>
                <div className="v6-meta-row">
                  <span>Model Status</span>
                  <span>
                    {/* From the backend catalog: what was actually checked on unseen data */}
                    {(inst.validation_status || inst.validationStatus) === "RANGE_VALIDATED"
                      ? "Range validated · direction: no edge"
                      : (inst.validation_status || inst.validationStatus) === "DATA_FEED_GAP_REPORTED"
                      ? "Data Gap Reported"
                      : "Not evaluated"}
                  </span>
                </div>
              </div>

              <button
                type="button"
                className={`v6-select-btn ${isSelected ? "active" : ""}`}
                onClick={(e) => {
                  e.stopPropagation();
                  setSelectedInstrument(inst.id);
                }}
              >
                {isSelected ? "Active Instrument" : `Inspect ${inst.name}`}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
