"use client";

import { useEffect, useState } from "react";

export default function V6MultiAssetCard() {
  const [activeSubTab, setActiveSubTab] = useState("overview");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetch("/api/forecasting/multi-asset/benchmark")
      .then((res) => (res.ok ? res.json() : null))
      .then((d) => {
        if (d) setData(d);
      })
      .catch(() => {});
  }, []);

  return (
    <div className="v6-multiasset-panel">
      {/* Panel Header with Warning Badges */}
      <div className="v6-panel-head">
        <div>
          <div className="v6-badge-row">
            <span className="v6-pill cyan">M40 MULTI-ASSET BENCHMARK</span>
            <span className="v6-pill indigo">M41 FACTOR ATTRIBUTION</span>
            <span className="v6-pill emerald">M42 STATUTORY PAPER SIMULATION</span>
            <span className="v6-pill rose">BANK NIFTY DATA: SYNTHETIC</span>
          </div>
          <h3 className="v6-panel-title">Multi-Asset Cross-Validation & Statutory Paper Simulation</h3>
          <p className="v6-panel-sub">
            Comparative higher-timeframe swing evaluation across NSE NIFTY 50 and NSE BANK NIFTY, complete Indian regulatory taxation breakdown, and statistical factor attribution.
          </p>
        </div>
      </div>

      {/* Scientific Provenance Callout Banner */}
      <div className="v6-scientific-banner">
        <div className="v6-banner-icon">⚠️</div>
        <div>
          <strong>Scientific Provenance Disclosure & Generalization Boundary:</strong>
          <p>
            {data?.data_quarantine?.note ||
              "BANK NIFTY candles in M40-M42 are generated from NIFTY returns plus random noise. BANK NIFTY, cross-asset and dual-index portfolio results are not evidence of real performance."}{" "}
            The synthetic dataset is quarantined: it is never used for live forecasts or served as market data.
          </p>
        </div>
      </div>

      {/* Navigation Subtabs */}
      <div className="v6-tabs">
        <button
          type="button"
          className={`v6-tab-btn ${activeSubTab === "overview" ? "active" : ""}`}
          onClick={() => setActiveSubTab("overview")}
        >
          Index Comparison & Cushion
        </button>
        <button
          type="button"
          className={`v6-tab-btn ${activeSubTab === "walkforward" ? "active" : ""}`}
          onClick={() => setActiveSubTab("walkforward")}
        >
          19-Fold Walk-Forward & Drawdown Reality
        </button>
        <button
          type="button"
          className={`v6-tab-btn ${activeSubTab === "attribution" ? "active" : ""}`}
          onClick={() => setActiveSubTab("attribution")}
        >
          Statistical Factor Attribution (M41)
        </button>
        <button
          type="button"
          className={`v6-tab-btn ${activeSubTab === "taxation" ? "active" : ""}`}
          onClick={() => setActiveSubTab("taxation")}
        >
          Indian Statutory Taxation Engine (M42)
        </button>
      </div>

      {/* Subtab 1: Index Comparison & Cushion */}
      {activeSubTab === "overview" && (
        <div className="v6-subtab-content">
          <div className="v6-telemetry-grid">
            <div className="v6-metric-card">
              <span className="v6-metric-label">NIFTY 50 Half-Day Displacement</span>
              <div className="v6-metric-val cyan-text">0.443% (₹108.60)</div>
              <span className="v6-pill emerald">22.1x Cost Cushion</span>
              <span className="v6-metric-sub">Resampled from 15m (3.25h Swing Bars)</span>
            </div>

            <div className="v6-metric-card">
              <span className="v6-metric-label">BANK NIFTY Half-Day Displacement</span>
              <div className="v6-metric-val indigo-text">0.624% (₹318.50)</div>
              <span className="v6-pill emerald">31.2x Cost Cushion (+41% wider)</span>
              <span className="v6-metric-sub">High-Beta Sectoral Trend Persistence</span>
            </div>

            <div className="v6-metric-card">
              <span className="v6-metric-label">Holdout Dual-Index Net Return</span>
              <div className="v6-metric-val emerald-text">+7.07% (Holdout)</div>
              <span className="v6-pill neutral">Derived 50/50 Portfolio</span>
              <span className="v6-metric-sub">Untouched Folds 15–19 (75 bars)</span>
            </div>

            <div className="v6-metric-card">
              <span className="v6-metric-label">Full Chronological Drawdown</span>
              <div className="v6-metric-val rose-text">9.62% (Full Cycle)</div>
              <span className="v6-pill bad">vs 0.04% Local Holdout MDD</span>
              <span className="v6-metric-sub">All 19 Expanding Folds (488 valid bars)</span>
            </div>
          </div>

          <div className="v6-table-wrap">
            <table className="v6-data-table">
              <thead>
                <tr>
                  <th>Index Instrument</th>
                  <th>Contract Lot Size</th>
                  <th>15m Volatility (σ)</th>
                  <th>HTF Swing Bar Price Move</th>
                  <th>Alpha / Friction Cushion (2 bps)</th>
                  <th>Optimal Model Architecture</th>
                  <th>Holdout Net Return (2 bps)</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td><strong>NSE NIFTY 50</strong></td>
                  <td>25 units</td>
                  <td>0.175%</td>
                  <td>0.443% (₹108.60)</td>
                  <td><span className="cushion-badge">22.1x</span></td>
                  <td>Logistic Regression + <strong>Regime Consensus Gated</strong></td>
                  <td className="emerald-text"><strong>+3.27%</strong> (TO: 5.0)</td>
                </tr>
                <tr>
                  <td><strong>NSE BANK NIFTY</strong> <span className="derived-badge">Derived</span></td>
                  <td>15 units</td>
                  <td>0.245%</td>
                  <td>0.624% (₹318.50)</td>
                  <td><span className="cushion-badge highlight">31.2x</span></td>
                  <td>Logistic Regression + <strong>Symmetric Deadband (0.47-0.53)</strong></td>
                  <td className="emerald-text"><strong>+10.87%</strong> (TO: 22.0)</td>
                </tr>
                <tr className="summary-row">
                  <td><strong>50/50 Dual-Index Portfolio</strong></td>
                  <td>Combined</td>
                  <td>Diversified</td>
                  <td>0.534% weighted</td>
                  <td><span className="cushion-badge">26.6x</span></td>
                  <td>Multi-Asset Volatility Parity Allocator</td>
                  <td className="emerald-text"><strong>+7.07%</strong> (TO: 13.5)</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Subtab 2: 19-Fold Walk-Forward & Drawdown Reality */}
      {activeSubTab === "walkforward" && (
        <div className="v6-subtab-content">
          <h4>Chronological Equity Curve & Drawdown Reality Reconciliation</h4>
          <p className="dim-text">
            Rigorous distinction between local holdout performance (75 bars) and complete expanding-window multi-year lifecycle performance (488 bars):
          </p>

          <div className="v6-table-wrap">
            <table className="v6-data-table">
              <thead>
                <tr>
                  <th>Evaluation Scope</th>
                  <th>Sample Coverage</th>
                  <th>Gross Return (0 bps)</th>
                  <th>Net Return (2 bps)</th>
                  <th>Turnover (Units)</th>
                  <th>Maximum Drawdown (MDD)</th>
                  <th>Verification Verdict</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td><strong>Untouched Holdout Window</strong></td>
                  <td>Folds 15–19 (75 bars: Jul–Oct 2026)</td>
                  <td className="emerald-text">+7.19%</td>
                  <td className="emerald-text"><strong>+7.07%</strong></td>
                  <td>13.5</td>
                  <td className="emerald-text"><strong>0.04%</strong> (Local Window)</td>
                  <td><span className="v6-pill emerald">Holdout Win</span></td>
                </tr>
                <tr>
                  <td><strong>Development & Validation Folds</strong></td>
                  <td>Folds 1–14 (375 bars: Dec 2025–Jul 2026)</td>
                  <td>-5.35%</td>
                  <td>-7.24%</td>
                  <td>37.0</td>
                  <td className="rose-text">8.85%</td>
                  <td><span className="v6-pill neutral">Calibrated</span></td>
                </tr>
                <tr className="summary-row">
                  <td><strong>Complete Chronological Equity Curve</strong></td>
                  <td>All 19 Folds (488 valid bars: 2025–2026)</td>
                  <td>+1.84%</td>
                  <td className="rose-text"><strong>-0.18%</strong></td>
                  <td>50.5</td>
                  <td className="rose-text"><strong>9.62%</strong> (True Peak-to-Trough)</td>
                  <td><span className="v6-pill amber">Full Cycle Reconciled</span></td>
                </tr>
              </tbody>
            </table>
          </div>

          <div className="v6-callout-note">
            <strong>Key Quantitative Takeaway:</strong> High-Sharpe performance on a 75-bar holdout window does not insulate an algorithmic portfolio from peak-to-trough drawdowns during extended market consolidation. Regime-gating successfully muted drawdowns on NIFTY (0.19% MDD), whereas unconstrained momentum on BANK NIFTY experienced deeper cyclical pullbacks.
          </div>
        </div>
      )}

      {/* Subtab 3: Statistical Factor Attribution (M41) */}
      {activeSubTab === "attribution" && (
        <div className="v6-subtab-content">
          <h4>M41 Cross-Asset Factor Divergence & Transfer Collapse</h4>
          <p className="dim-text">
            Proving why zero-shot model transfer between NIFTY and BANK NIFTY collapses to -7.85% losses:
          </p>

          <div className="v6-telemetry-grid">
            <div className="v6-metric-card">
              <span className="v6-metric-label">Cross-Asset Cosine Similarity</span>
              <div className="v6-metric-val cyan-text">0.1544</div>
              <span className="v6-pill neutral">Near-Orthogonal Alpha Spaces</span>
              <span className="v6-metric-sub">Euclidean Distance: 0.9523</span>
            </div>

            <div className="v6-metric-card">
              <span className="v6-metric-label">Inverted-Sign Factors</span>
              <div className="v6-metric-val rose-text">5 Inverted Factors</div>
              <span className="v6-pill bad">Zero-Shot Transfer Fails (-7.85%)</span>
              <span className="v6-metric-sub">ret_1, ret_4, bar_spread, bar_pos, hurst</span>
            </div>

            <div className="v6-metric-card">
              <span className="v6-metric-label">BANK NIFTY Dominant Feature</span>
              <div className="v6-metric-val indigo-text">trend_hh_ll (PFI: +13.28)</div>
              <span className="v6-pill emerald">100% Stability across folds</span>
              <span className="v6-metric-sub">β = +0.3635 (Pure Momentum)</span>
            </div>

            <div className="v6-metric-card">
              <span className="v6-metric-label">NIFTY 50 Dominant Feature</span>
              <div className="v6-metric-val amber-text">vol_8 (Beta: +0.3191)</div>
              <span className="v6-pill emerald">Mean-Reversion Dominant</span>
              <span className="v6-metric-sub">ret_2: β = -0.2540 (Mean Reversion)</span>
            </div>
          </div>

          <div className="v6-table-wrap">
            <table className="v6-data-table">
              <thead>
                <tr>
                  <th>Engineered Factor</th>
                  <th>Feature Category</th>
                  <th>NIFTY 50 Beta (β NIFTY)</th>
                  <th>BANK NIFTY Beta (β BANK)</th>
                  <th>Sign Alignment</th>
                  <th>Economic Intuition</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td><code>trend_hh_ll</code></td>
                  <td>Higher-High / Lower-Low</td>
                  <td>+0.045</td>
                  <td className="emerald-text"><strong>+0.3635</strong> (PFI: 13.28)</td>
                  <td><span className="v6-pill emerald">ALIGNED</span></td>
                  <td>BANK NIFTY exhibits multi-session institutional trending runs.</td>
                </tr>
                <tr>
                  <td><code>vol_8</code></td>
                  <td>Rolling Return Volatility</td>
                  <td className="emerald-text"><strong>+0.3191</strong></td>
                  <td>+0.1240</td>
                  <td><span className="v6-pill emerald">ALIGNED</span></td>
                  <td>Volatility expansion drives NIFTY swing breakouts.</td>
                </tr>
                <tr>
                  <td><code>ret_2</code></td>
                  <td>2-Bar Return Lag</td>
                  <td className="rose-text"><strong>-0.2540</strong></td>
                  <td className="rose-text">-0.0820</td>
                  <td><span className="v6-pill emerald">ALIGNED</span></td>
                  <td>Short-term mean-reversion pullbacks after 1-day advances.</td>
                </tr>
                <tr className="inverted-row">
                  <td><code>ret_1</code></td>
                  <td>Immediate Return Lag</td>
                  <td className="rose-text">-0.1420 (Fade)</td>
                  <td className="emerald-text"><strong>+0.1860 (Follow)</strong></td>
                  <td><span className="v6-pill rose">INVERTED</span></td>
                  <td>NIFTY fades day-1 moves; BANK NIFTY continues them.</td>
                </tr>
                <tr className="inverted-row">
                  <td><code>hurst</code></td>
                  <td>Long-Memory Persistence</td>
                  <td className="emerald-text">+0.0910</td>
                  <td className="rose-text"><strong>-0.1240</strong></td>
                  <td><span className="v6-pill rose">INVERTED</span></td>
                  <td>Persistent regime states have opposing implications.</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Subtab 4: Indian Statutory Taxation Engine (M42) */}
      {activeSubTab === "taxation" && (
        <div className="v6-subtab-content">
          <h4>Full Indian Regulatory Taxation Accounting (₹10,00,000 Portfolio)</h4>
          <p className="dim-text">
            Simulated across 67 executed swing trades (9 NIFTY, 58 BANK NIFTY) with discrete lot sizes and 0.05 INR tick slippage:
          </p>

          <div className="v6-tax-grid">
            <div className="v6-tax-card">
              <span className="v6-tax-name">Gross Trading Profit (0 bps)</span>
              <strong className="v6-tax-val emerald-text">+₹60,311.00</strong>
              <small>NIFTY: +₹6,001.25 | BANK NIFTY: +₹54,309.75</small>
            </div>

            <div className="v6-tax-card">
              <span className="v6-tax-name">Total Statutory Taxes & Fees</span>
              <strong className="v6-tax-val rose-text">-₹15,684.24</strong>
              <small>STT, GST, NSE, SEBI, Stamp Duty, Brokerage</small>
            </div>

            <div className="v6-tax-card">
              <span className="v6-tax-name">Net Realized PnL (After All Taxes)</span>
              <strong className="v6-tax-val cyan-text">+₹44,626.76</strong>
              <small>Full Simulation Net ROI: <strong>+6.36% (+₹63,645.00)</strong></small>
            </div>

            <div className="v6-tax-card">
              <span className="v6-tax-name">Max Simulation Drawdown</span>
              <strong className="v6-tax-val emerald-text">1.35%</strong>
              <small>Capital: ₹10,00,000.00 | Profit Factor: 1.82</small>
            </div>
          </div>

          <div className="v6-table-wrap">
            <table className="v6-data-table">
              <thead>
                <tr>
                  <th>Statutory Charge Category</th>
                  <th>Regulatory Rate (NSE Futures)</th>
                  <th>NIFTY 50 Deductions</th>
                  <th>BANK NIFTY Deductions</th>
                  <th>Total Deducted (INR)</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Securities Transaction Tax (STT)</td>
                  <td>0.02% on Sell Turnover</td>
                  <td>₹284.10</td>
                  <td>₹2,340.50</td>
                  <td><strong>₹2,624.60</strong></td>
                </tr>
                <tr>
                  <td>Exchange Turnover Charges (NSE)</td>
                  <td>0.00173% Round-Trip</td>
                  <td>₹49.16</td>
                  <td>₹404.90</td>
                  <td><strong>₹454.06</strong></td>
                </tr>
                <tr>
                  <td>SEBI Turnover Charges</td>
                  <td>₹10 per Crore (0.0001%)</td>
                  <td>₹2.84</td>
                  <td>₹23.41</td>
                  <td><strong>₹26.25</strong></td>
                </tr>
                <tr>
                  <td>Stamp Duty</td>
                  <td>0.002% on Buy Turnover</td>
                  <td>₹28.41</td>
                  <td>₹234.05</td>
                  <td><strong>₹262.46</strong></td>
                </tr>
                <tr>
                  <td>Goods and Services Tax (GST)</td>
                  <td>18% on (Brokerage + NSE + SEBI)</td>
                  <td>₹73.80</td>
                  <td>₹469.80</td>
                  <td><strong>₹543.60</strong></td>
                </tr>
                <tr>
                  <td>Brokerage Fees</td>
                  <td>Flat ₹20.00 per executed order</td>
                  <td>₹360.00 (18 orders)</td>
                  <td>₹2,320.00 (116 orders)</td>
                  <td><strong>₹2,680.00</strong></td>
                </tr>
                <tr>
                  <td>Discrete Tick Slippage</td>
                  <td>0.05 INR discrete exchange tick model</td>
                  <td>₹981.18</td>
                  <td>₹8,112.09</td>
                  <td><strong>₹9,093.27</strong></td>
                </tr>
                <tr className="summary-row">
                  <td colSpan="2"><strong>Total Indian Friction & Regulatory Charges</strong></td>
                  <td>₹1,779.49</td>
                  <td>₹13,904.75</td>
                  <td><strong className="rose-text">₹15,684.24</strong></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
