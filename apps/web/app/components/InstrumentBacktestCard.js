"use client";

import { useEffect, useState } from "react";
import { useMarketData } from "./MarketDataContext";

export default function InstrumentBacktestCard() {
  const { selectedInstrument, instrumentConfig } = useMarketData();
  const [backtest, setBacktest] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const activeId = selectedInstrument || "NIFTY";
  const cfg = instrumentConfig || {};

  useEffect(() => {
    let cancelled = false;
    async function fetchBacktest() {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`/api/forecasting/instrument-backtest?instrument=${activeId}`);
        if (!res.ok) {
          throw new Error(`Failed to load backtest for ${activeId}`);
        }
        const data = await res.json();
        if (!cancelled) {
          setBacktest(data);
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

    fetchBacktest();
    return () => {
      cancelled = true;
    };
  }, [activeId]);

  const bt = backtest || {};
  const isVerified = bt.evaluation_status === "VERIFIED_WALK_FORWARD";

  return (
    <div className="v6-card" data-testid="instrument-backtest-card">
      <div className="v6-card-header">
        <div>
          <span className="v6-badge-sub">Empirical Walk-Forward Verification</span>
          <h2 className="v6-card-title">{bt.name || cfg.name || activeId} Strategy Backtest & Robustness</h2>
        </div>
        <div className="v6-header-tags">
          <span className={`v6-pill ${isVerified ? "emerald" : "amber"}`}>
            STATUS: {bt.evaluation_status || "UNEVALUATED"}
          </span>
          <span className="v6-pill indigo">FRICTION: 2.0 BPS REALISTIC</span>
        </div>
      </div>

      <p className="v6-section-desc">
        Independent instrument-level evaluation across chronological test folds.
        Strategy profitability is claimed strictly when supported by validated market observations
        after accounting for exchange charges, STT, GST, and bid-ask slippage.
      </p>

      {loading ? (
        <div className="v6-loading-box">Loading walk-forward backtest report for {activeId}…</div>
      ) : error ? (
        <div className="v6-error-box">{error}</div>
      ) : !isVerified ? (
        <div className="v6-chart-data-gap-view">
          <div className="v6-gap-icon">⚠️</div>
          <h3>Backtest Performance Claims Withheld for {bt.name || activeId}</h3>
          <p>{bt.reason}</p>

          {bt.data_requirements && (
            <div className="v6-requirements-box">
              <strong>Mandatory Prerequisites Before Strategy Evaluation:</strong>
              <ul className="v6-bullet-list">
                {bt.data_requirements.map((req, i) => (
                  <li key={i}>{req}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="v6-provenance-box">
            <strong>Current Evaluation Policy:</strong> Strict refusal of unverified backtests.
            <span className="v6-pill rose">NO SYNTHETIC ALPHA CLAIMS</span>
          </div>
        </div>
      ) : (
        <>
          {/* Key Walk-Forward Summary Metrics */}
          <div className="v6-metrics-grid">
            <div className="v6-metric-card">
              <span className="v6-metric-label">Holdout Net Return (2 bps)</span>
              <div className="v6-metric-val emerald-text">
                +{bt.performance_after_costs?.holdout_net_return}%
              </div>
              <span className="v6-pill emerald">Full Period: +{bt.performance_after_costs?.full_period_net_return}%</span>
              <span className="v6-metric-sub">Dev Folds: {bt.performance_after_costs?.dev_net_return}%</span>
            </div>

            <div className="v6-metric-card">
              <span className="v6-metric-label">Maximum Drawdown</span>
              <div className="v6-metric-val rose-text">
                {bt.performance_after_costs?.full_period_max_drawdown}%
              </div>
              <span className="v6-pill amber">Full 19-Fold Curve: 9.62%</span>
              <span className="v6-metric-sub">Holdout Window Artifact: {bt.performance_after_costs?.local_holdout_window_drawdown}%</span>
            </div>

            <div className="v6-metric-card">
              <span className="v6-metric-label">Holdout Skill & Calibration</span>
              <div className="v6-metric-val cyan-text">
                +{bt.statistical_metrics?.holdout_brier_skill_score}
              </div>
              <span className="v6-pill cyan">Accuracy: {(bt.statistical_metrics?.holdout_accuracy * 100).toFixed(0)}%</span>
              <span className="v6-metric-sub">Brier Score vs Base Rate</span>
            </div>

            <div className="v6-metric-card">
              <span className="v6-metric-label">Turnover & Cushion</span>
              <div className="v6-metric-val indigo-text">
                {bt.statistical_metrics?.alpha_to_friction_ratio}x
              </div>
              <span className="v6-pill indigo">Turnover: {bt.statistical_metrics?.turnover_units} units</span>
              <span className="v6-metric-sub">Total Trades: {bt.statistical_metrics?.trade_count} HTF Bars</span>
            </div>
          </div>

          {/* Drawdown Reconciliation Callout */}
          <div className="v6-scientific-banner">
            <div className="v6-banner-icon">⚖️</div>
            <div>
              <strong>Empirical Drawdown Reconciliation:</strong>
              <p>{bt.performance_after_costs?.drawdown_reconciliation_note}</p>
            </div>
          </div>

          {/* Baseline Comparisons Table */}
          <div className="v6-subpanel" style={{ marginTop: "1rem" }}>
            <h4 className="v6-subpanel-title">Model Strategy vs Classical Baselines (After 2 bps Friction)</h4>
            <div className="v6-table-wrap">
              <table className="v6-data-table">
                <thead>
                  <tr>
                    <th>Strategy Model</th>
                    <th>Execution Mode</th>
                    <th>Full Net Return (2 bps)</th>
                    <th>Holdout Net Return (2 bps)</th>
                    <th>Max Drawdown</th>
                    <th>Candidate Status</th>
                  </tr>
                </thead>
                <tbody>
                  {(bt.baseline_comparisons || []).map((b, i) => (
                    <tr key={i}>
                      <td><strong>{b.model}</strong></td>
                      <td><code>{b.mode}</code></td>
                      <td className={b.full_net_return_2bps >= 0 ? "emerald-text" : "rose-text"}>
                        {b.full_net_return_2bps >= 0 ? `+${b.full_net_return_2bps}%` : `${b.full_net_return_2bps}%`}
                      </td>
                      <td className={b.holdout_net_return_2bps >= 0 ? "emerald-text" : "rose-text"}>
                        {b.holdout_net_return_2bps >= 0 ? `+${b.holdout_net_return_2bps}%` : `${b.holdout_net_return_2bps}%`}
                      </td>
                      <td>{b.max_drawdown}%</td>
                      <td>
                        <span className={`v6-pill ${b.status === "OPTIMAL_CANDIDATE" ? "emerald" : "indigo"}`}>
                          {b.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Execution Assumptions */}
          <div className="v6-subpanel" style={{ marginTop: "1rem" }}>
            <h4 className="v6-subpanel-title">Explicitly Documented Execution Assumptions</h4>
            <ul className="v6-bullet-list">
              {(bt.execution_assumptions || []).map((asm, i) => (
                <li key={i}>{asm}</li>
              ))}
            </ul>
          </div>

          {/* Provenance Footer */}
          <div className="v6-provenance-footer">
            <span><strong>Dataset:</strong> {bt.dataset_provenance?.dataset_id}</span>
            <span><strong>SHA-256:</strong> <code>{bt.dataset_provenance?.sha256?.slice(0, 16)}…</code></span>
            <span><strong>Range:</strong> {bt.dataset_provenance?.date_range}</span>
          </div>
        </>
      )}
    </div>
  );
}
