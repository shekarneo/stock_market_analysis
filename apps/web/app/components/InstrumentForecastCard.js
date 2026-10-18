"use client";

import { useEffect, useState } from "react";
import { useMarketData } from "./MarketDataContext";

export default function InstrumentForecastCard() {
  const { selectedInstrument, instrumentConfig } = useMarketData();
  const [forecast, setForecast] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const activeId = selectedInstrument || "NIFTY";
  const cfg = instrumentConfig || {};

  useEffect(() => {
    let cancelled = false;
    async function fetchForecast() {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`/api/forecasting/instrument-forecast?instrument=${activeId}`);
        if (!res.ok) {
          throw new Error(`Failed to load forecast for ${activeId} (${res.status})`);
        }
        const data = await res.json();
        if (!cancelled) {
          setForecast(data);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err.message);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    fetchForecast();
    return () => {
      cancelled = true;
    };
  }, [activeId]);

  const fc = forecast || {};
  const decision = fc.decision || "NO TRADE";
  const isBuy = decision === "BUY";
  const isSell = decision === "SELL";
  const isNoTrade = decision === "NO TRADE";

  const decisionBadgeClass = isBuy ? "emerald" : isSell ? "rose" : "amber";

  return (
    <div className="v6-card" data-testid="instrument-forecast-card">
      <div className="v6-card-header">
        <div>
          <span className="v6-badge-sub">Instrument-Specific Quantitative Forecast</span>
          <h2 className="v6-card-title">{fc.name || cfg.name || activeId} Forecast & Consensus Engine</h2>
        </div>
        <div className="v6-header-tags">
          <span className={`v6-pill ${decisionBadgeClass}`}>
            DECISION: {decision}
          </span>
          <span className="v6-pill indigo">HORIZON: {fc.forecast_horizon || "15m"}</span>
        </div>
      </div>

      <p className="v6-section-desc">
        Independent statistical forecasting and risk gating for {fc.name || activeId}.
        Directional predictions are separated from validated trading strategies; raw model confidence is
        distinguished from calibrated probabilities.
      </p>

      {loading ? (
        <div className="v6-loading-box">Computing independent forecast for {activeId}…</div>
      ) : error ? (
        <div className="v6-error-box">{error}</div>
      ) : (
        <>
          {/* Key Metric Gauges */}
          <div className="v6-metrics-grid">
            <div className="v6-metric-card">
              <span className="v6-metric-label">Signal Recommendation</span>
              <div className={`v6-metric-val ${isBuy ? "emerald-text" : isSell ? "rose-text" : "amber-text"}`}>
                {decision}
              </div>
              <span className={`v6-pill ${decisionBadgeClass}`}>Direction: {fc.predicted_direction || "UNKNOWN"}</span>
              <span className="v6-metric-sub">Friction Allowance: {fc.transaction_cost_assumptions?.turnover_friction_bps || 2.0} bps</span>
            </div>

            <div className="v6-metric-card">
              <span className="v6-metric-label">Calibrated Probability P(Up)</span>
              <div className="v6-metric-val cyan-text">
                {fc.calibrated_probability != null ? `${(fc.calibrated_probability * 100).toFixed(1)}%` : "N/A"}
              </div>
              <span className="v6-pill cyan">
                Raw Confidence: {fc.raw_confidence != null ? `${(fc.raw_confidence * 100).toFixed(0)}%` : "0%"}
              </span>
              <span className="v6-metric-sub">Platt / Laplace Scaled over Holdout</span>
            </div>

            <div className="v6-metric-card">
              <span className="v6-metric-label">Spot Price & Expected Move</span>
              <div className="v6-metric-val">
                {fc.spot_price != null ? `₹${Number(fc.spot_price).toLocaleString("en-IN", { minimumFractionDigits: 1, maximumFractionDigits: 2 })}` : "N/A"}
              </div>
              <span className="v6-pill indigo">
                Move: {fc.expected_return_points != null ? `±${fc.expected_return_points} pts` : "N/A"}
              </span>
              <span className="v6-metric-sub">
                Target: {fc.target_spot ? `₹${fc.target_spot}` : "N/A"} • Stop: {fc.stop_loss_spot ? `₹${fc.stop_loss_spot}` : "N/A"}
              </span>
            </div>

            <div className="v6-metric-card">
              <span className="v6-metric-label">Model Provenance & Status</span>
              <div className="v6-metric-val" style={{ fontSize: "1.05rem" }}>
                {fc.model_status || "UNEVALUATED"}
              </div>
              <span className="v6-pill purple">Hardware Lock: ACTIVE</span>
              <span className="v6-metric-sub">Broker Order Routing: LOCKED</span>
            </div>
          </div>

          {/* NO TRADE Explanation Callout (when active) */}
          {isNoTrade && fc.reasons_for_no_trade && fc.reasons_for_no_trade.length > 0 && (
            <div className="v6-scientific-banner">
              <div className="v6-banner-icon">🛡️</div>
              <div>
                <strong>Deterministic Reasons for NO TRADE on {activeId}:</strong>
                <ul className="v6-reasons-list">
                  {fc.reasons_for_no_trade.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          {/* Evidence Panels: Supporting vs Contradicting */}
          <div className="v6-dual-evidence-grid">
            <div className="v6-evidence-card supporting">
              <div className="v6-evidence-header emerald-text">
                <span>✓</span> Supporting Market Evidence
              </div>
              <ul className="v6-evidence-list">
                {(fc.supporting_evidence || []).map((item, idx) => (
                  <li key={idx}>{item}</li>
                ))}
              </ul>
            </div>

            <div className="v6-evidence-card contradicting">
              <div className="v6-evidence-header rose-text">
                <span>⚠️</span> Contradicting Factors & Risk Warnings
              </div>
              <ul className="v6-evidence-list">
                {(fc.contradicting_evidence || []).map((item, idx) => (
                  <li key={idx}>{item}</li>
                ))}
              </ul>
            </div>
          </div>

          {/* Invalidation Conditions and Cost Breakdown */}
          <div className="v6-details-split-grid">
            <div className="v6-subpanel">
              <h4 className="v6-subpanel-title">Trade Invalidation Conditions</h4>
              <ul className="v6-bullet-list">
                {(fc.invalidation_conditions || []).map((cond, i) => (
                  <li key={i}>{cond}</li>
                ))}
              </ul>
            </div>

            <div className="v6-subpanel">
              <h4 className="v6-subpanel-title">Realistic Transaction Cost Assumptions</h4>
              {fc.transaction_cost_assumptions ? (
                <div className="v6-table-wrap">
                  <table className="v6-data-table compact">
                    <tbody>
                      <tr>
                        <td>Turnover Friction</td>
                        <td><strong>{fc.transaction_cost_assumptions.turnover_friction_bps} bps</strong></td>
                      </tr>
                      <tr>
                        <td>Securities Transaction Tax (STT)</td>
                        <td>{fc.transaction_cost_assumptions.stt_rate}</td>
                      </tr>
                      <tr>
                        <td>Exchange Turnover Fee</td>
                        <td>{fc.transaction_cost_assumptions.exchange_turnover_fee}</td>
                      </tr>
                      <tr>
                        <td>GST Rate</td>
                        <td>{fc.transaction_cost_assumptions.gst_rate}</td>
                      </tr>
                      <tr>
                        <td>Brokerage</td>
                        <td>{fc.transaction_cost_assumptions.flat_brokerage}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              ) : (
                <p>Standard statutory charges apply.</p>
              )}
            </div>
          </div>

          {/* Provenance Footer */}
          <div className="v6-provenance-footer">
            <span><strong>Data Provenance:</strong> {fc.provenance}</span>
            <span><strong>Timestamp:</strong> {fc.data_timestamp ? new Date(fc.data_timestamp).toLocaleString("en-IN") : "Now"}</span>
          </div>
        </>
      )}
    </div>
  );
}
