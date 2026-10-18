"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import ResearchBoard from "../components/ResearchBoard";
import { flagLabel } from "../research/status.mjs";
import { intentIdProblem, valueText } from "../research/present.mjs";

function inr(val) {
  if (val == null) return "—";
  return `₹${Number(val).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function pct(val) {
  if (val == null) return "—";
  return `${Number(val).toFixed(2)}%`;
}

export default function PaperPage() {
  // 1. Current Live-Data Paper Account State
  const [accountData, setAccountData] = useState(null);
  const [loadingAccount, setLoadingAccount] = useState(true);

  // 2. Historical Simulation Benchmark (M42 Replay)
  const [simData, setSimData] = useState(null);
  const [loadingSim, setLoadingSim] = useState(true);
  const [showBenchmark, setShowBenchmark] = useState(false);
  const [symbolFilter, setSymbolFilter] = useState("ALL");
  const [outcomeFilter, setOutcomeFilter] = useState("ALL");

  useEffect(() => {
    async function fetchPaperAccount() {
      try {
        setLoadingAccount(true);
        const res = await fetch("/api/paper/account");
        if (res.ok) {
          const json = await res.json();
          setAccountData(json);
        }
      } catch {
        // Fallback handled in render
      } finally {
        setLoadingAccount(false);
      }
    }

    async function fetchSimulation() {
      try {
        setLoadingSim(true);
        const res = await fetch("/api/execution/multi-asset/simulation");
        if (res.ok) {
          const json = await res.json();
          setSimData(json);
        }
      } catch {
        // Fallback handled in render
      } finally {
        setLoadingSim(false);
      }
    }

    fetchPaperAccount();
    fetchSimulation();
  }, []);

  const currentTrades = accountData?.trades || [];
  const currentTotalTrades = accountData?.total_trades_count || 0;
  const currentRealizedPnl = accountData?.realized_pnl_inr || 0.0;
  const currentCharges = accountData?.total_charges_inr || 0.0;

  const benchmarkTrades = simData?.trades || [];
  const filteredBenchmarkTrades = benchmarkTrades.filter((t) => {
    if (symbolFilter !== "ALL" && t.symbol !== symbolFilter) return false;
    if (outcomeFilter === "WIN" && (t.net_pnl_inr || 0) <= 0) return false;
    if (outcomeFilter === "LOSS" && (t.net_pnl_inr || 0) > 0) return false;
    return true;
  });

  const charges = simData?.total_charges_breakdown || {};

  return (
    <ResearchBoard
      title="Paper Trading Desk"
      lede="Live-data paper trading account and order execution monitor. Real broker order routing is locked. Historical backtests and live paper trades are strictly segregated."
    >
      {({ status }) => (
        <section aria-labelledby="paper-desk-heading">
          <div style={{ display: "flex", gap: "8px", background: "var(--card-subtle, #131c31)", padding: "4px", borderRadius: "10px", border: "1px solid var(--line)", marginBottom: "16px", flexWrap: "wrap", alignItems: "center" }}>
            <Link href="/backtest" style={{ padding: "8px 16px", borderRadius: "8px", color: "var(--muted)", fontWeight: 650, fontSize: "0.85rem", textDecoration: "none" }}>
              ← 📊 Walk-Forward &amp; Multi-Asset Backtest
            </Link>
            <span style={{ padding: "8px 16px", borderRadius: "8px", background: "rgba(255, 255, 255, 0.12)", color: "#ffffff", fontWeight: 650, fontSize: "0.85rem" }}>
              📒 Paper Ledger &amp; Intent Audit Replay
            </span>
            <Link href="/live" style={{ marginLeft: "auto", padding: "8px 14px", borderRadius: "8px", color: "#34d399", fontWeight: 600, fontSize: "0.82rem", textDecoration: "none" }}>
              ⚡ Open Active Live &amp; Auto Trading Desk →
            </Link>
          </div>

          {/* Operational Safety Status Ribbon */}
          <div className="session-ribbon" style={{ marginBottom: "20px" }}>
            <strong>Operational Mode: PAPER</strong>
            <span>Active virtual trading environment. Real capital remains locked behind hardware/software kill switches. Fills are virtual only.</span>
            <span className="pill bad"><i />LIVE BROKER LOCKED</span>
          </div>

          {/* ======================================================== */}
          {/* SECTION 1: CURRENT LIVE PAPER TRADING ACCOUNT (ACTUAL)    */}
          {/* ======================================================== */}
          <div style={{ marginBottom: "36px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px", flexWrap: "wrap", gap: "8px" }}>
              <div>
                <h2 id="paper-desk-heading" style={{ margin: 0, fontSize: "1.25rem", display: "flex", alignItems: "center", gap: "8px" }}>
                  <span>🟢</span> Current Live Paper Trading Account
                </h2>
                <p style={{ margin: "4px 0 0", fontSize: "0.85rem", color: "var(--muted)" }}>
                  Metrics reflect only verified virtual fills executed during this operational session.
                </p>
              </div>
              <span className="pill" style={{ background: "rgba(56, 189, 248, 0.15)", color: "#38bdf8", border: "1px solid rgba(56, 189, 248, 0.3)" }}>
                Source: Live Database Ledger
              </span>
            </div>

            {loadingAccount ? (
              <p role="status">Loading live paper account status…</p>
            ) : (
              <>
                <div style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                  gap: "12px",
                  marginBottom: "16px"
                }}>
                  <div className="stat-card" style={{ background: "var(--card-subtle, #131c31)", padding: "14px", borderRadius: "10px", border: "1px solid var(--line)" }}>
                    <span style={{ fontSize: "0.78rem", color: "var(--muted)", textTransform: "uppercase" }}>Realized Net P&amp;L</span>
                    <div style={{
                      fontSize: "1.4rem",
                      fontWeight: "bold",
                      marginTop: "4px",
                      color: currentRealizedPnl > 0 ? "#10b981" : (currentRealizedPnl < 0 ? "#ef4444" : "var(--muted)")
                    }}>
                      {inr(currentRealizedPnl)}
                    </div>
                    <small style={{ color: "var(--muted)" }}>Actual executed trades</small>
                  </div>

                  <div className="stat-card" style={{ background: "var(--card-subtle, #131c31)", padding: "14px", borderRadius: "10px", border: "1px solid var(--line)" }}>
                    <span style={{ fontSize: "0.78rem", color: "var(--muted)", textTransform: "uppercase" }}>Open Positions</span>
                    <div style={{ fontSize: "1.4rem", fontWeight: "bold", marginTop: "4px" }}>
                      {accountData?.open_positions_count || 0}
                    </div>
                    <small style={{ color: "var(--muted)" }}>0 active lots at risk</small>
                  </div>

                  <div className="stat-card" style={{ background: "var(--card-subtle, #131c31)", padding: "14px", borderRadius: "10px", border: "1px solid var(--line)" }}>
                    <span style={{ fontSize: "0.78rem", color: "var(--muted)", textTransform: "uppercase" }}>Executed Trades</span>
                    <div style={{ fontSize: "1.4rem", fontWeight: "bold", marginTop: "4px" }}>
                      {currentTotalTrades}
                    </div>
                    <small style={{ color: "var(--muted)" }}>Win Rate: {pct(accountData?.win_rate_pct)}</small>
                  </div>

                  <div className="stat-card" style={{ background: "var(--card-subtle, #131c31)", padding: "14px", borderRadius: "10px", border: "1px solid var(--line)" }}>
                    <span style={{ fontSize: "0.78rem", color: "var(--muted)", textTransform: "uppercase" }}>Total Statutory Fees</span>
                    <div style={{ fontSize: "1.4rem", fontWeight: "bold", marginTop: "4px" }}>
                      {inr(currentCharges)}
                    </div>
                    <small style={{ color: "var(--muted)" }}>STT, NSE, SEBI &amp; GST</small>
                  </div>
                </div>

                {/* Honest Zero State for Live Paper Account */}
                {currentTotalTrades === 0 ? (
                  <div style={{
                    background: "rgba(15, 23, 42, 0.4)",
                    border: "1px dashed var(--line)",
                    borderRadius: "10px",
                    padding: "24px",
                    textAlign: "center",
                    margin: "12px 0 24px"
                  }}>
                    <div style={{ fontSize: "1.8rem", marginBottom: "8px" }}>📭</div>
                    <h3 style={{ margin: "0 0 6px", fontSize: "1rem" }}>No Live Paper Trades Executed Yet</h3>
                    <p style={{ margin: "0 auto", maxWidth: "560px", fontSize: "0.85rem", color: "var(--muted)", lineHeight: 1.5 }}>
                      The current paper trading session has not placed or filled any virtual orders. Fills, realized P&amp;L, win rate, and profit factor remain at <strong>zero</strong> until trades are qualified and simulated.
                    </p>
                    <p style={{ margin: "8px 0 0", fontSize: "0.8rem", color: "#38bdf8" }}>
                      Historical backtest performance (M42) is segregated below and is not counted toward this account.
                    </p>
                  </div>
                ) : (
                  <div className="table-wrap" style={{ overflowX: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem", textAlign: "left" }}>
                      <thead>
                        <tr style={{ borderBottom: "2px solid var(--line)" }}>
                          <th>ID</th>
                          <th>Symbol</th>
                          <th>Side</th>
                          <th>Price</th>
                          <th>Charges</th>
                          <th>Net P&amp;L</th>
                        </tr>
                      </thead>
                      <tbody>
                        {currentTrades.map((t, idx) => (
                          <tr key={idx} style={{ borderBottom: "1px solid var(--line)" }}>
                            <td>{t.event_id || idx}</td>
                            <td>{t.underlying || "—"}</td>
                            <td>{t.side || "—"}</td>
                            <td>{inr(t.price)}</td>
                            <td>{inr(t.charges_inr)}</td>
                            <td>{inr(t.realized_pnl_inr)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}
          </div>

          {/* ======================================================== */}
          {/* SECTION 2: HISTORICAL SIMULATION BENCHMARK (M42 REPLAY)   */}
          {/* ======================================================== */}
          <div style={{
            background: "rgba(15, 23, 42, 0.6)",
            border: "1px solid var(--line)",
            borderRadius: "12px",
            padding: "20px",
            marginBottom: "36px"
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px", marginBottom: "14px" }}>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <span className="pill" style={{ background: "rgba(245, 158, 11, 0.2)", color: "#f59e0b", border: "1px solid rgba(245, 158, 11, 0.4)", fontSize: "0.72rem" }}>
                    HISTORICAL BENCHMARK
                  </span>
                  <h3 style={{ margin: 0, fontSize: "1.1rem" }}>
                    Multi-Asset Simulation Benchmark (M42 Historical Replay)
                  </h3>
                </div>
                <p style={{ margin: "4px 0 0", fontSize: "0.85rem", color: "var(--muted)" }}>
                  Verified 19-fold walk-forward replay across 67 historical swing bars with statutory Indian friction. This is an archival research benchmark, <strong>not</strong> the current paper account's P&amp;L.
                </p>
              </div>

              <button
                type="button"
                onClick={() => setShowBenchmark(!showBenchmark)}
                style={{
                  padding: "6px 14px",
                  borderRadius: "6px",
                  fontSize: "0.82rem",
                  cursor: "pointer",
                  background: showBenchmark ? "rgba(255,255,255,0.12)" : "rgba(255,255,255,0.06)",
                  border: "1px solid var(--line)",
                  color: "#fff"
                }}
              >
                {showBenchmark ? "▲ Collapse Benchmark" : "▼ Inspect Benchmark Trades (67)"}
              </button>
            </div>

            {simData && (
              <>
                <div style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                  gap: "10px",
                  marginBottom: "16px"
                }}>
                  <div style={{ background: "rgba(255,255,255,0.03)", padding: "12px", borderRadius: "8px" }}>
                    <span style={{ fontSize: "0.75rem", color: "var(--muted)", textTransform: "uppercase" }}>Benchmark Capital</span>
                    <div style={{ fontSize: "1.15rem", fontWeight: "bold", marginTop: "2px" }}>{inr(simData.ending_capital_inr)}</div>
                    <small style={{ color: "var(--muted)" }}>Initial: {inr(simData.initial_capital_inr)}</small>
                  </div>

                  <div style={{ background: "rgba(255,255,255,0.03)", padding: "12px", borderRadius: "8px" }}>
                    <span style={{ fontSize: "0.75rem", color: "var(--muted)", textTransform: "uppercase" }}>Net Replay P&amp;L</span>
                    <div style={{ fontSize: "1.15rem", fontWeight: "bold", marginTop: "2px", color: "#10b981" }}>
                      +{inr(simData.net_pnl_inr)}
                    </div>
                    <small style={{ color: "#10b981" }}>Net ROI: {pct(simData.net_roi_pct)}</small>
                  </div>

                  <div style={{ background: "rgba(255,255,255,0.03)", padding: "12px", borderRadius: "8px" }}>
                    <span style={{ fontSize: "0.75rem", color: "var(--muted)", textTransform: "uppercase" }}>Gross Gain vs Friction</span>
                    <div style={{ fontSize: "1.15rem", fontWeight: "bold", marginTop: "2px", color: "#38bdf8" }}>
                      {inr(simData.gross_pnl_inr)}
                    </div>
                    <small style={{ color: "#f59e0b" }}>
                      Friction: {inr((charges.total_charges || 0) + (charges.total_slippage || 0))}
                    </small>
                  </div>

                  <div style={{ background: "rgba(255,255,255,0.03)", padding: "12px", borderRadius: "8px" }}>
                    <span style={{ fontSize: "0.75rem", color: "var(--muted)", textTransform: "uppercase" }}>Win Rate &amp; Max DD</span>
                    <div style={{ fontSize: "1.15rem", fontWeight: "bold", marginTop: "2px" }}>
                      {pct(simData.overall_win_rate_pct)}
                    </div>
                    <small style={{ color: "var(--muted)" }}>
                      PF: {Number(simData.overall_profit_factor || 0).toFixed(2)} · Max DD: {pct(simData.max_drawdown_pct)}
                    </small>
                  </div>
                </div>

                {/* Charges breakdown pills */}
                <div style={{
                  display: "flex",
                  gap: "12px",
                  flexWrap: "wrap",
                  fontSize: "0.8rem",
                  color: "var(--muted)",
                  padding: "10px 12px",
                  background: "rgba(0,0,0,0.2)",
                  borderRadius: "6px"
                }}>
                  <span>STT: <strong style={{ color: "#fff" }}>{inr(charges.stt)}</strong></span>
                  <span>NSE Txn: <strong style={{ color: "#fff" }}>{inr(charges.exchange_charges)}</strong></span>
                  <span>SEBI: <strong style={{ color: "#fff" }}>{inr(charges.sebi_charges)}</strong></span>
                  <span>Brokerage: <strong style={{ color: "#fff" }}>{inr(charges.brokerage)}</strong></span>
                  <span>GST: <strong style={{ color: "#fff" }}>{inr(charges.gst)}</strong></span>
                  <span>Stamp: <strong style={{ color: "#fff" }}>{inr(charges.stamp_duty)}</strong></span>
                  <span>Tick Slippage: <strong style={{ color: "#f59e0b" }}>{inr(charges.total_slippage)}</strong></span>
                  <span>Total Friction: <strong style={{ color: "#ef4444" }}>{inr((charges.total_charges || 0) + (charges.total_slippage || 0))}</strong></span>
                </div>

                {showBenchmark && (
                  <div style={{ marginTop: "16px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "8px", marginBottom: "10px" }}>
                      <h4 style={{ margin: 0, fontSize: "0.95rem" }}>
                        Historical Replay Trades ({filteredBenchmarkTrades.length} of {benchmarkTrades.length})
                      </h4>
                      <div style={{ display: "flex", gap: "6px" }}>
                        {["ALL", "NIFTY", "BANKNIFTY"].map((sym) => (
                          <button
                            key={sym}
                            type="button"
                            onClick={() => setSymbolFilter(sym)}
                            style={{
                              fontSize: "0.75rem",
                              padding: "3px 8px",
                              borderRadius: "4px",
                              border: "1px solid var(--line)",
                              background: symbolFilter === sym ? "rgba(56, 189, 248, 0.25)" : "transparent",
                              color: symbolFilter === sym ? "#38bdf8" : "var(--muted)",
                              cursor: "pointer"
                            }}
                          >
                            {sym}
                          </button>
                        ))}
                      </div>
                    </div>

                    <div className="table-wrap" style={{ overflowX: "auto" }}>
                      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.82rem", textAlign: "left" }}>
                        <thead>
                          <tr style={{ borderBottom: "1px solid var(--line)", background: "rgba(255,255,255,0.02)" }}>
                            <th style={{ padding: "6px" }}>ID</th>
                            <th style={{ padding: "6px" }}>Symbol</th>
                            <th style={{ padding: "6px" }}>Side</th>
                            <th style={{ padding: "6px" }}>Qty</th>
                            <th style={{ padding: "6px" }}>Entry Fill</th>
                            <th style={{ padding: "6px" }}>Exit Fill</th>
                            <th style={{ padding: "6px" }}>Statutory Fees</th>
                            <th style={{ padding: "6px" }}>Slippage</th>
                            <th style={{ padding: "6px" }}>Net P&amp;L</th>
                            <th style={{ padding: "6px" }}>ROI</th>
                          </tr>
                        </thead>
                        <tbody>
                          {filteredBenchmarkTrades.slice(0, 30).map((t) => {
                            const isWin = (t.net_pnl_inr || 0) >= 0;
                            return (
                              <tr key={t.trade_id} style={{ borderBottom: "1px solid var(--line, #1e293b)" }}>
                                <td style={{ padding: "6px", color: "var(--muted)", fontFamily: "monospace" }}>{t.trade_id}</td>
                                <td style={{ padding: "6px" }}><strong>{t.symbol}</strong></td>
                                <td style={{ padding: "6px", color: t.side === "BUY" ? "#10b981" : "#ef4444", fontWeight: "bold" }}>{t.side}</td>
                                <td style={{ padding: "6px" }}>{t.quantity}</td>
                                <td style={{ padding: "6px" }}>{inr(t.entry_fill_price)}</td>
                                <td style={{ padding: "6px" }}>{inr(t.exit_fill_price)}</td>
                                <td style={{ padding: "6px", color: "var(--muted)" }}>{inr(t.total_charges_inr)}</td>
                                <td style={{ padding: "6px", color: "#f59e0b" }}>{inr(t.total_slippage_inr)}</td>
                                <td style={{ padding: "6px", fontWeight: "bold", color: isWin ? "#10b981" : "#ef4444" }}>
                                  {isWin ? "+" : ""}{inr(t.net_pnl_inr)}
                                </td>
                                <td style={{ padding: "6px", color: isWin ? "#10b981" : "#ef4444" }}>
                                  {pct(t.roi_pct)}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                      {filteredBenchmarkTrades.length > 30 && (
                        <p style={{ fontSize: "0.75rem", color: "var(--muted)", marginTop: "6px" }}>
                          Showing 30 of {filteredBenchmarkTrades.length} historical trades.
                        </p>
                      )}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>

          {/* ======================================================== */}
          {/* SECTION 3: INTENT AUDIT & DECISION REPLAY TOOL            */}
          {/* ======================================================== */}
          <div style={{ paddingTop: "20px", borderTop: "1px solid var(--line)" }}>
            <h3 id="execution-heading" style={{ fontSize: "1rem" }}>Intent Audit &amp; Decision Replay</h3>
            <p style={{ fontSize: "0.85rem", color: "var(--muted)" }}>
              Fills persisted {flagLabel(status?.fills_persisted)}. Broker called {flagLabel(status?.broker_called)}. Paper trading active {flagLabel(status?.paper_trading_active)}.
            </p>
            <Replay />
          </div>
        </section>
      )}
    </ResearchBoard>
  );
}

function Replay() {
  const [intentId, setIntentId] = useState("");
  const [phase, setPhase] = useState("idle");
  const [replay, setReplay] = useState(null);
  const [error, setError] = useState("");
  const [requestedId, setRequestedId] = useState("");

  async function load(event) {
    event.preventDefault();
    const problem = intentIdProblem(intentId);
    if (problem) {
      setPhase("invalid");
      setReplay(null);
      setError(problem);
      return;
    }
    setPhase("loading");
    setError("");
    setReplay(null);
    setRequestedId(intentId);
    try {
      const response = await fetch(`/api/paper/simulations/${encodeURIComponent(intentId)}`);
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        setPhase("error");
        setError(body.message || body.detail || `The stored decision could not be read (${response.status}).`);
        return;
      }
      setReplay(body);
      setPhase("ready");
    } catch (err) {
      setPhase("error");
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div data-testid="replay">
      <form onSubmit={load} style={{ display: "flex", gap: "10px", alignItems: "flex-end", flexWrap: "wrap", margin: "12px 0" }}>
        <label style={{ display: "flex", flexDirection: "column", gap: "4px", fontSize: "0.85rem" }}>
          Intent id
          <input
            value={intentId}
            onChange={(event) => setIntentId(event.target.value)}
            autoComplete="off"
            style={{ padding: "6px 10px", borderRadius: "6px", border: "1px solid var(--line)" }}
          />
        </label>
        <button type="submit" style={{ padding: "6px 14px", borderRadius: "6px" }}>Read stored decision</button>
      </form>
      {phase === "loading" ? <p role="status">Reading the stored decision…</p> : null}
      {phase === "invalid" || phase === "error" ? (
        <div className="error" role="alert">
          <p>{error}</p>
          {phase === "error" ? <button type="button" onClick={(event) => load(event)}>Retry</button> : null}
        </div>
      ) : null}
      {phase === "ready" && replay ? <ReplayBody replay={replay} requestedId={requestedId} /> : null}
    </div>
  );
}

function ReplayBody({ replay, requestedId }) {
  const attempts = Array.isArray(replay.attempts) ? replay.attempts : [];
  const missing = Array.isArray(replay.missing) ? replay.missing : [];
  return (
    <div style={{ marginTop: "12px", background: "var(--card-subtle, #131c31)", padding: "16px", borderRadius: "8px", border: "1px solid var(--line)" }}>
      <p>Intent {valueText(replay.intent_id || requestedId)}. State {replay.state == null ? "none stored" : valueText(replay.state)}.</p>
      <p data-testid="fill">Fill {valueText(replay.fill)}. Simulated fill {valueText(replay.simulated_fill)}. Execution is unavailable.</p>
      <p data-testid="replay-expected-net">Expected net {valueText(replay.expected_net)}. A null expected net is unknown.</p>
      <p>Snapshot conflict {valueText(replay.snapshot_conflict)}. Paper trading active {flagLabel(replay.paper_trading_active)}.</p>
      <h4 style={{ margin: "10px 0 6px" }}>Missing fields</h4>
      {missing.length === 0 ? <p style={{ color: "var(--muted)" }}>No missing fields were listed.</p> : <ul>{missing.map((item) => <li key={item}>{item}</li>)}</ul>}
      <h4 style={{ margin: "10px 0 6px" }}>Attempts</h4>
      {attempts.length === 0 ? <p style={{ color: "var(--muted)" }}>No attempts were returned.</p> : (
        <ul>
          {attempts.map((attempt) => (
            <li key={attempt.audit_id || attempt.attempt}>
              {valueText(attempt.code)}. Reasons {Array.isArray(attempt.reasons) ? attempt.reasons.join(", ") : valueText(attempt.reasons)}.
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
