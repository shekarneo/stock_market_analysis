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
  const isEvaluated = bt.evaluation_status === "RESEARCH_WALK_FORWARD";
  const perf = bt.performance_after_costs || {};
  const stats = bt.statistical_metrics || {};
  const sig = bt.significance || null;
  const pct = (v) => (v == null ? "N/A" : `${v >= 0 ? "+" : ""}${v}%`);
  const tone = (v) => (v == null ? "" : v >= 0 ? "emerald-text" : "rose-text");

  return (
    <div className="v6-card" data-testid="instrument-backtest-card">
      <div className="v6-card-header">
        <div>
          <span className="v6-badge-sub">Walk-Forward Research (not a live track record)</span>
          <h2 className="v6-card-title">{bt.name || cfg.name || activeId} Strategy Backtest & Robustness</h2>
        </div>
        <div className="v6-header-tags">
          <span className={`v6-pill ${isEvaluated ? "indigo" : "amber"}`}>
            STATUS: {bt.evaluation_status || "UNEVALUATED"}
          </span>
          {isEvaluated && (
            <span className="v6-pill amber">FRICTION: {perf.statutory_friction_bps ?? "N/A"} BPS ON INDEX (NOT OPTIONS)</span>
          )}
        </div>
      </div>

      <p className="v6-section-desc">
        Numbers below are read from the computed walk-forward artifact only. Nothing is shown when the
        artifact is missing. Read the caveats before treating any figure as evidence of edge.
      </p>

      {loading ? (
        <div className="v6-loading-box">Loading walk-forward backtest report for {activeId}…</div>
      ) : error ? (
        <div className="v6-error-box">{error}</div>
      ) : !isEvaluated ? (
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
          {/* Caveats first: these change how every number below should be read */}
          {(bt.caveats || []).length > 0 && (
            <div className="v6-scientific-banner">
              <div className="v6-banner-icon">⚠️</div>
              <div>
                <strong>Read before using these results:</strong>
                <ul className="v6-bullet-list">
                  {bt.caveats.map((c, i) => (
                    <li key={i}>{c}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          {/* Key Walk-Forward Summary Metrics */}
          <div className="v6-metrics-grid">
            <div className="v6-metric-card">
              <span className="v6-metric-label">Holdout Net Return ({perf.statutory_friction_bps ?? "N/A"} bps)</span>
              <div className={`v6-metric-val ${tone(perf.holdout_net_return)}`}>{pct(perf.holdout_net_return)}</div>
              <span className="v6-pill indigo">Full Period: {pct(perf.full_period_net_return)}</span>
              <span className="v6-metric-sub">Dev Folds: {pct(perf.dev_net_return)}</span>
            </div>

            <div className="v6-metric-card">
              <span className="v6-metric-label">Max Drawdown</span>
              <div className="v6-metric-val rose-text">
                {perf.max_drawdown != null ? `${perf.max_drawdown}%` : "N/A"}
              </div>
              <span className="v6-metric-sub">
                {perf.drawdown_basis === "CHAINED_CURVE" ? "Chained out-of-sample curve" : "Legacy: mean of per-fold maxima"}
              </span>
            </div>

            <div className="v6-metric-card">
              <span className="v6-metric-label">Holdout Skill & Calibration</span>
              <div className="v6-metric-val cyan-text">
                {stats.holdout_brier_skill_score != null ? stats.holdout_brier_skill_score : "N/A"}
              </div>
              <span className="v6-pill cyan">
                Accuracy: {stats.holdout_accuracy != null ? `${(stats.holdout_accuracy * 100).toFixed(1)}%` : "N/A"}
              </span>
              <span className="v6-metric-sub">Brier Skill Score vs Base Rate</span>
            </div>

            <div className="v6-metric-card">
              <span className="v6-metric-label">Turnover</span>
              <div className="v6-metric-val indigo-text">
                {stats.holdout_turnover_units != null ? `${stats.holdout_turnover_units} units` : "N/A"}
              </div>
              <span className="v6-pill indigo">Full Period: {stats.full_turnover_units ?? "N/A"} units</span>
              <span className="v6-metric-sub">Holdout folds: {bt.folds_summary?.holdout_folds ?? "N/A"}</span>
            </div>
          </div>

          {/* Significance after realistic costs (chained evaluation) */}
          <div className="v6-subpanel" style={{ marginTop: "1rem" }}>
            <h4 className="v6-subpanel-title">Is the edge real? (Significance after realistic costs)</h4>
            {sig ? (
              <div className="v6-metrics-grid">
                <div className="v6-metric-card">
                  <span className="v6-metric-label">Edge Evidence</span>
                  <div className={`v6-metric-val ${sig.edge_evidence === "STATISTICALLY_SUPPORTED" ? "emerald-text" : "rose-text"}`}>
                    {sig.edge_evidence === "STATISTICALLY_SUPPORTED" ? "Supported" : "Not supported"}
                  </div>
                  <span className="v6-metric-sub">Requires dev DSR ≥ 0.95 and holdout PSR ≥ 0.5</span>
                </div>
                <div className="v6-metric-card">
                  <span className="v6-metric-label">Dev Deflated Sharpe</span>
                  <div className="v6-metric-val">{sig.dev_deflated_sharpe ?? "N/A"}</div>
                  <span className="v6-metric-sub">
                    Sharpe {sig.dev_sharpe_annualized ?? "N/A"} · {sig.trials_considered ?? "N/A"} trials counted
                  </span>
                </div>
                <div className="v6-metric-card">
                  <span className="v6-metric-label">Holdout at {sig.cost_per_side_bps ?? "N/A"} bps/side</span>
                  <div className={`v6-metric-val ${tone(sig.holdout_return_realistic_cost_pct)}`}>{pct(sig.holdout_return_realistic_cost_pct)}</div>
                  <span className="v6-metric-sub">{sig.holdout_trades ?? "N/A"} trades · PSR {sig.holdout_psr_vs_zero ?? "N/A"}</span>
                </div>
                <div className="v6-metric-card">
                  <span className="v6-metric-label">Holdout Hit Rate (95% CI)</span>
                  <div className="v6-metric-val">
                    {sig.holdout_active_accuracy != null ? `${(sig.holdout_active_accuracy * 100).toFixed(1)}%` : "N/A"}
                  </div>
                  <span className="v6-metric-sub">
                    {sig.holdout_accuracy_ci95 ? `${(sig.holdout_accuracy_ci95[0] * 100).toFixed(0)}–${(sig.holdout_accuracy_ci95[1] * 100).toFixed(0)}%` : "CI N/A"}
                    {sig.holdout_accuracy_p_value != null ? ` · p=${sig.holdout_accuracy_p_value}` : ""}
                  </span>
                </div>
              </div>
            ) : (
              <p className="v6-section-desc">Significance tests are not available for this (legacy) artifact. Regenerate the M40 benchmark.</p>
            )}
          </div>

          {/* Aggregation note */}
          <div className="v6-scientific-banner">
            <div className="v6-banner-icon">⚖️</div>
            <div>
              <strong>How these figures are aggregated:</strong>
              <p>{perf.drawdown_reconciliation_note}</p>
            </div>
          </div>

          {/* All evaluated strategies */}
          <div className="v6-subpanel" style={{ marginTop: "1rem" }}>
            <h4 className="v6-subpanel-title">All Evaluated Strategies (After {perf.statutory_friction_bps ?? "N/A"} bps Friction)</h4>
            <div className="v6-table-wrap">
              <table className="v6-data-table">
                <thead>
                  <tr>
                    <th>Strategy Model</th>
                    <th>Execution Mode</th>
                    <th>Dev Net Return</th>
                    <th>Holdout Net Return</th>
                    <th>Full Net Return</th>
                    <th>Max DD</th>
                    <th>Dev DSR</th>
                  </tr>
                </thead>
                <tbody>
                  {(bt.baseline_comparisons || []).map((b, i) => (
                    <tr key={i}>
                      <td><strong>{b.model}</strong></td>
                      <td><code>{b.mode}</code></td>
                      <td className={tone(b.dev_net_return_2bps)}>{pct(b.dev_net_return_2bps)}</td>
                      <td className={tone(b.holdout_net_return_2bps)}>{pct(b.holdout_net_return_2bps)}</td>
                      <td className={tone(b.full_net_return_2bps)}>{pct(b.full_net_return_2bps)}</td>
                      <td>{b.max_drawdown != null ? `${b.max_drawdown}%` : "N/A"}</td>
                      <td>{b.dev_deflated_sharpe ?? "N/A"}</td>
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
            <span><strong>Dataset:</strong> {bt.dataset_provenance?.dataset_id ?? "N/A"}</span>
            <span><strong>Artifact:</strong> <code>{bt.dataset_provenance?.artifact ?? "N/A"}</code></span>
            <span><strong>Computed:</strong> {bt.dataset_provenance?.artifact_created_at ?? "N/A"}</span>
          </div>
        </>
      )}
    </div>
  );
}
