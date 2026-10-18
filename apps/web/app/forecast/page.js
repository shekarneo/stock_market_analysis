"use client";

import { useEffect, useState } from "react";
import ResearchBoard, { csrf } from "../components/ResearchBoard";
import ReadState from "../components/ReadState";
import { useRead } from "../components/useRead";
import InstrumentForecastCard from "../components/InstrumentForecastCard";
import { flagLabel } from "../research/status.mjs";
import { observationClass, valueText } from "../research/present.mjs";

function pct(val) {
  if (val == null) return "—";
  return `${Number(val).toFixed(2)}%`;
}

function num(val, digits = 4) {
  if (val == null) return "—";
  return Number(val).toFixed(digits);
}

function inr(val) {
  if (val == null) return "—";
  return `₹${Number(val).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export default function ForecastPage() {
  return (
    <ResearchBoard
      title="Forecasts & Accuracy Desk"
      lede="V6 multi-instrument forecasting desk. Predictions are calculated independently per instrument. Directional forecasts are separated from validated trading strategies; raw model confidence is distinguished from calibrated probabilities."
    >
      {() => (
        <>
          <InstrumentForecastCard />
          <DataPullWorkstation />
          <ModelTrainingWorkstation />
          <ForecastAccuracyHub />
          <Approved />
          <Models />
          <Experiments />
        </>
      )}
    </ResearchBoard>
  );
}

function DataPullWorkstation() {
  const [instrument, setInstrument] = useState("NIFTY");
  const [provider, setProvider] = useState("groww");
  const [interval, setInterval] = useState("M15");
  const [start, setStart] = useState("2026-09-18");
  const [end, setEnd] = useState("2026-10-18");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  const setPreset = (months) => {
    const e = new Date("2026-10-18");
    const s = new Date(e);
    s.setMonth(s.getMonth() - months);
    setStart(s.toISOString().slice(0, 10));
    setEnd(e.toISOString().slice(0, 10));
  };

  const handlePullData = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const res = await fetch("/api/history/imports", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-csrf-token": csrf(),
        },
        body: JSON.stringify({
          provider,
          instrument,
          interval,
          start: `${start}T09:15:00+05:30`,
          end: `${end}T15:30:00+05:30`,
        }),
      });
      const data = await res.json();
      setResult(data);
      if (!res.ok && data.code !== "CANDLE_BOUNDARY_UNVERIFIED" && data.code !== "EMPTY_CANDLES") {
        setError(data.message || data.code || "Failed to pull candle data.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-labelledby="pull-data-heading" style={{ background: "var(--card-subtle, #131c31)", border: "1px solid var(--line, #334155)", borderRadius: "12px", padding: "20px", marginBottom: "28px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "10px", marginBottom: "16px" }}>
        <div>
          <h2 id="pull-data-heading" style={{ margin: 0, fontSize: "1.2rem", fontWeight: 700, color: "var(--ink, #f8fafc)" }}>
            📥 Historical Data Ingestion Workstation
          </h2>
          <p style={{ margin: "4px 0 0", fontSize: "0.85rem", color: "var(--sub, #94a3b8)" }}>
            Pull component historical candle series across NSE, BSE, and MCX with customizable intervals and calendar-aligned date ranges.
          </p>
        </div>
        <span className="pill info"><i />DATA PIPELINE</span>
      </div>

      <form onSubmit={handlePullData}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: "14px", marginBottom: "14px" }}>
          <div>
            <label style={{ display: "block", fontSize: "0.8rem", fontWeight: 600, color: "var(--sub, #94a3b8)", marginBottom: "4px" }}>
              Component / Asset
            </label>
            <select
              value={instrument}
              onChange={(e) => setInstrument(e.target.value)}
              style={{ width: "100%", padding: "8px 10px", background: "var(--bg, #0f172a)", border: "1px solid var(--line, #334155)", borderRadius: "6px", color: "var(--ink, #f8fafc)", fontSize: "0.9rem" }}
            >
              <option value="NIFTY">NIFTY 50 (NSE-NIFTY)</option>
              <option value="BANKNIFTY">BANK NIFTY (NSE-BANKNIFTY)</option>
              <option value="SENSEX">BSE SENSEX (BSE-SENSEX)</option>
              <option value="CRUDEOILMINI">CRUDEOIL MINI (MCX-CRUDEOILMINI)</option>
            </select>
          </div>

          <div>
            <label style={{ display: "block", fontSize: "0.8rem", fontWeight: 600, color: "var(--sub, #94a3b8)", marginBottom: "4px" }}>
              Candle Interval
            </label>
            <select
              value={interval}
              onChange={(e) => setInterval(e.target.value)}
              style={{ width: "100%", padding: "8px 10px", background: "var(--bg, #0f172a)", border: "1px solid var(--line, #334155)", borderRadius: "6px", color: "var(--ink, #f8fafc)", fontSize: "0.9rem" }}
            >
              <option value="M1">1 Minute (M1)</option>
              <option value="M5">5 Minutes (M5)</option>
              <option value="M15">15 Minutes (M15 - Standard)</option>
              <option value="H1">1 Hour (H1 Swing)</option>
              <option value="D1">1 Day (Daily)</option>
            </select>
          </div>

          <div>
            <label style={{ display: "block", fontSize: "0.8rem", fontWeight: 600, color: "var(--sub, #94a3b8)", marginBottom: "4px" }}>
              Provider Feed
            </label>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              style={{ width: "100%", padding: "8px 10px", background: "var(--bg, #0f172a)", border: "1px solid var(--line, #334155)", borderRadius: "6px", color: "var(--ink, #f8fafc)", fontSize: "0.9rem" }}
            >
              <option value="groww">Groww Direct / Snapshot</option>
              <option value="upstox">Upstox Reference Feed</option>
              <option value="kite">Zerodha Kite Connect</option>
              <option value="angelone">AngelOne SmartAPI</option>
            </select>
          </div>

          <div>
            <label style={{ display: "block", fontSize: "0.8rem", fontWeight: 600, color: "var(--sub, #94a3b8)", marginBottom: "4px" }}>
              Start Date
            </label>
            <input
              type="date"
              value={start}
              onChange={(e) => setStart(e.target.value)}
              style={{ width: "100%", padding: "8px 10px", background: "var(--bg, #0f172a)", border: "1px solid var(--line, #334155)", borderRadius: "6px", color: "var(--ink, #f8fafc)", fontSize: "0.88rem" }}
            />
          </div>

          <div>
            <label style={{ display: "block", fontSize: "0.8rem", fontWeight: 600, color: "var(--sub, #94a3b8)", marginBottom: "4px" }}>
              End Date
            </label>
            <input
              type="date"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
              style={{ width: "100%", padding: "8px 10px", background: "var(--bg, #0f172a)", border: "1px solid var(--line, #334155)", borderRadius: "6px", color: "var(--ink, #f8fafc)", fontSize: "0.88rem" }}
            />
          </div>
        </div>

        {/* Quick Date Range Presets */}
        <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap", marginBottom: "16px" }}>
          <span style={{ fontSize: "0.78rem", color: "var(--muted, #64748b)" }}>Quick Presets:</span>
          <button type="button" className="btn small secondary" onClick={() => setPreset(1)}>1 Month</button>
          <button type="button" className="btn small secondary" onClick={() => setPreset(3)}>3 Months</button>
          <button type="button" className="btn small secondary" onClick={() => setPreset(6)}>6 Months</button>
          <button type="button" className="btn small secondary" onClick={() => { setStart("2025-10-14"); setEnd("2026-10-16"); }}>1 Year (M23 Baseline)</button>
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end", gap: "10px" }}>
          <button type="submit" className="btn primary" disabled={busy} style={{ minWidth: "180px" }}>
            {busy ? "Fetching & Validating…" : `📥 Pull ${instrument} ${interval} Data`}
          </button>
        </div>
      </form>

      {error ? (
        <div style={{ marginTop: "14px", padding: "10px 14px", background: "rgba(239, 68, 68, 0.1)", border: "1px solid #ef4444", borderRadius: "6px", color: "#fca5a5", fontSize: "0.85rem" }}>
          <strong>Error:</strong> {error}
        </div>
      ) : null}

      {result ? (
        <div style={{ marginTop: "14px", padding: "12px 14px", background: result.ok ? "rgba(16, 185, 129, 0.08)" : "rgba(245, 158, 11, 0.1)", border: `1px solid ${result.ok ? "#10b981" : "#f59e0b"}`, borderRadius: "6px", fontSize: "0.85rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
            <strong>{result.ok ? "✓ Ingestion Succeeded" : "⚠ Pipeline Notification"}:</strong>
            <span className={`pill ${result.ok ? "ok" : "warn"}`}>{result.code || "RESPONSE"}</span>
          </div>
          <p style={{ margin: "0 0 4px", color: "var(--ink, #f8fafc)" }}>{result.message || JSON.stringify(result)}</p>
          {result.candles_stored ? (
            <p style={{ margin: 0, color: "var(--sub, #94a3b8)" }}>
              Durable candles stored: <strong>{result.candles_stored}</strong> · Dataset: <code>{result.dataset_id || "registered"}</code>
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function ModelTrainingWorkstation() {
  const [instrument, setInstrument] = useState("NIFTY");
  const [model, setModel] = useState("logistic_regression");
  const [strategyMode, setStrategyMode] = useState("regime_gated");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  const handleTrainBenchmark = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const res = await fetch("/api/forecasting/train-benchmark", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-csrf-token": csrf(),
        },
        body: JSON.stringify({
          instrument,
          model,
          strategy_mode: strategyMode,
          interval: "M15",
          folds: 19,
        }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        setError(data.message || data.code || `Training error (${res.status})`);
      } else {
        setResult(data);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-labelledby="training-station-heading" style={{ background: "var(--card-subtle, #131c31)", border: "1px solid var(--line, #334155)", borderRadius: "12px", padding: "20px", marginBottom: "28px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "10px", marginBottom: "16px" }}>
        <div>
          <h2 id="training-station-heading" style={{ margin: 0, fontSize: "1.2rem", fontWeight: 700, color: "var(--ink, #f8fafc)" }}>
            🧠 Model Selection &amp; Walk-Forward Training Station
          </h2>
          <p style={{ margin: "4px 0 0", fontSize: "0.85rem", color: "var(--sub, #94a3b8)" }}>
            Train and benchmark statistical and machine learning models across 19 expanding folds with exact Indian statutory friction accounting.
          </p>
        </div>
        <span className="pill ok"><i />WALK-FORWARD VERIFIED</span>
      </div>

      <form onSubmit={handleTrainBenchmark}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "14px", marginBottom: "16px" }}>
          <div>
            <label style={{ display: "block", fontSize: "0.8rem", fontWeight: 600, color: "var(--sub, #94a3b8)", marginBottom: "4px" }}>
              Target Asset
            </label>
            <select
              value={instrument}
              onChange={(e) => setInstrument(e.target.value)}
              style={{ width: "100%", padding: "8px 10px", background: "var(--bg, #0f172a)", border: "1px solid var(--line, #334155)", borderRadius: "6px", color: "var(--ink, #f8fafc)", fontSize: "0.9rem" }}
            >
              <option value="NIFTY">NIFTY 50 (6,227 Candles)</option>
              <option value="BANKNIFTY">BANK NIFTY (6,227 Candles)</option>
              <option value="SENSEX">BSE SENSEX (Independent Dataset Required)</option>
              <option value="CRUDEOILMINI">CRUDEOIL MINI (MCX Dataset Required)</option>
            </select>
          </div>

          <div>
            <label style={{ display: "block", fontSize: "0.8rem", fontWeight: 600, color: "var(--sub, #94a3b8)", marginBottom: "4px" }}>
              Model Architecture
            </label>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              style={{ width: "100%", padding: "8px 10px", background: "var(--bg, #0f172a)", border: "1px solid var(--line, #334155)", borderRadius: "6px", color: "var(--ink, #f8fafc)", fontSize: "0.9rem" }}
            >
              <option value="logistic_regression">Logistic Regression (L2 Newton - M3/M23)</option>
              <option value="lightgbm">LightGBM GBDT (HTF Resampled - M37)</option>
              <option value="empirical_prior">Empirical Prior (Majority Baseline - M3)</option>
            </select>
          </div>

          <div>
            <label style={{ display: "block", fontSize: "0.8rem", fontWeight: 600, color: "var(--sub, #94a3b8)", marginBottom: "4px" }}>
              Strategy / Gating Mode
            </label>
            <select
              value={strategyMode}
              onChange={(e) => setStrategyMode(e.target.value)}
              style={{ width: "100%", padding: "8px 10px", background: "var(--bg, #0f172a)", border: "1px solid var(--line, #334155)", borderRadius: "6px", color: "var(--ink, #f8fafc)", fontSize: "0.9rem" }}
            >
              <option value="regime_gated">Regime-Gated Consensus (ATR/ADX Filter)</option>
              <option value="deadband">Deadband Filter (48%–52% Neutral Zone)</option>
              <option value="raw">Raw Directional (Unconstrained)</option>
            </select>
          </div>

          <div>
            <label style={{ display: "block", fontSize: "0.8rem", fontWeight: 600, color: "var(--sub, #94a3b8)", marginBottom: "4px" }}>
              Validation Scheme
            </label>
            <div style={{ padding: "8px 10px", background: "rgba(255,255,255,0.03)", border: "1px solid var(--line, #334155)", borderRadius: "6px", color: "var(--sub, #94a3b8)", fontSize: "0.85rem" }}>
              19 Folds (14 Dev / 5 Holdout)
            </div>
          </div>
        </div>

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px" }}>
          <small style={{ color: "var(--muted, #64748b)" }}>
            ⚡ Friction hurdle: 2.0 bps (STT + NSE Fees + SEBI + GST + 0.05 Tick Slippage). Zero future lookahead.
          </small>
          <button type="submit" className="btn primary" disabled={busy} style={{ minWidth: "220px" }}>
            {busy ? "Fitting & Benchmarking Folds…" : `⚡ Train & Benchmark ${model}`}
          </button>
        </div>
      </form>

      {error ? (
        <div style={{ marginTop: "16px", padding: "10px 14px", background: "rgba(239, 68, 68, 0.1)", border: "1px solid #ef4444", borderRadius: "6px", color: "#fca5a5", fontSize: "0.85rem" }}>
          <strong>Error:</strong> {error}
        </div>
      ) : null}

      {result ? (
        <div style={{ marginTop: "20px" }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "12px", marginBottom: "16px" }}>
            <div style={{ background: "rgba(255,255,255,0.02)", border: "1px solid var(--line)", borderRadius: "8px", padding: "14px", textAlign: "center" }}>
              <span style={{ display: "block", fontSize: "0.75rem", color: "var(--sub)", textTransform: "uppercase", fontWeight: 600 }}>Holdout Accuracy</span>
              <strong style={{ fontSize: "1.4rem", color: result.holdout_accuracy >= 0.52 ? "#10b981" : "#f59e0b" }}>
                {(result.holdout_accuracy * 100).toFixed(2)}%
              </strong>
              <small style={{ display: "block", color: "var(--muted)", fontSize: "0.7rem", marginTop: "2px" }}>Folds 15–19 Out-of-Sample</small>
            </div>

            <div style={{ background: "rgba(255,255,255,0.02)", border: "1px solid var(--line)", borderRadius: "8px", padding: "14px", textAlign: "center" }}>
              <span style={{ display: "block", fontSize: "0.75rem", color: "var(--sub)", textTransform: "uppercase", fontWeight: 600 }}>Brier Skill Score</span>
              <strong style={{ fontSize: "1.4rem", color: result.holdout_brier_skill_score > 0 ? "#10b981" : "#ef4444" }}>
                {result.holdout_brier_skill_score > 0 ? "+" : ""}{result.holdout_brier_skill_score.toFixed(4)}
              </strong>
              <small style={{ display: "block", color: "var(--muted)", fontSize: "0.7rem", marginTop: "2px" }}>vs Climatological Baseline</small>
            </div>

            <div style={{ background: "rgba(255,255,255,0.02)", border: "1px solid var(--line)", borderRadius: "8px", padding: "14px", textAlign: "center" }}>
              <span style={{ display: "block", fontSize: "0.75rem", color: "var(--sub)", textTransform: "uppercase", fontWeight: 600 }}>Holdout Net Return</span>
              <strong style={{ fontSize: "1.4rem", color: result.holdout_net_return_2bps > 0 ? "#10b981" : "#ef4444" }}>
                {result.holdout_net_return_2bps > 0 ? "+" : ""}{result.holdout_net_return_2bps.toFixed(2)}%
              </strong>
              <small style={{ display: "block", color: "var(--muted)", fontSize: "0.7rem", marginTop: "2px" }}>After 2 bps Friction</small>
            </div>

            <div style={{ background: "rgba(255,255,255,0.02)", border: "1px solid var(--line)", borderRadius: "8px", padding: "14px", textAlign: "center" }}>
              <span style={{ display: "block", fontSize: "0.75rem", color: "var(--sub)", textTransform: "uppercase", fontWeight: 600 }}>Full Max Drawdown</span>
              <strong style={{ fontSize: "1.4rem", color: "#f87171" }}>
                {result.full_max_drawdown.toFixed(2)}%
              </strong>
              <small style={{ display: "block", color: "var(--muted)", fontSize: "0.7rem", marginTop: "2px" }}>Across 19 Expanding Folds</small>
            </div>
          </div>

          {result.all_strategies && result.all_strategies.length > 0 ? (
            <div className="table-wrap">
              <table>
                <caption>Strategy Comparison Matrix ({result.instrument} · 19 Expanding Folds)</caption>
                <thead>
                  <tr>
                    <th>Model</th>
                    <th>Strategy Mode</th>
                    <th>Holdout Accuracy</th>
                    <th>Brier Skill Score</th>
                    <th>Holdout Net Return (2bps)</th>
                    <th>Full Net Return (2bps)</th>
                    <th>Max Drawdown</th>
                  </tr>
                </thead>
                <tbody>
                  {result.all_strategies.map((row, idx) => {
                    const isSelected = row.model_name === result.model_name && row.strategy_mode === result.strategy_mode;
                    return (
                      <tr key={idx} style={{ background: isSelected ? "rgba(59, 130, 246, 0.1)" : "transparent" }}>
                        <td><strong>{row.model_name}</strong> {isSelected ? <span className="pill ok" style={{ fontSize: "0.65rem", padding: "1px 6px" }}>SELECTED</span> : null}</td>
                        <td><code>{row.strategy_mode}</code></td>
                        <td>{(row.holdout_accuracy * 100).toFixed(2)}%</td>
                        <td>{row.holdout_brier_skill_score > 0 ? "+" : ""}{row.holdout_brier_skill_score.toFixed(4)}</td>
                        <td style={{ color: row.holdout_net_return_2bps > 0 ? "#10b981" : "#ef4444", fontWeight: 600 }}>
                          {row.holdout_net_return_2bps > 0 ? "+" : ""}{row.holdout_net_return_2bps.toFixed(2)}%
                        </td>
                        <td style={{ color: row.full_net_return_2bps > 0 ? "#10b981" : "#ef4444" }}>
                          {row.full_net_return_2bps > 0 ? "+" : ""}{row.full_net_return_2bps.toFixed(2)}%
                        </td>
                        <td>{row.full_max_drawdown.toFixed(2)}%</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function ForecastAccuracyHub() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [evaluating, setEvaluating] = useState(false);

  const fetchAccuracy = async () => {
    try {
      setLoading(true);
      const res = await fetch("/api/analysis/forecast-accuracy");
      if (!res.ok) throw new Error(`Failed to load forecast accuracy (${res.status})`);
      const json = await res.json();
      setData(json);
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAccuracy();
  }, []);

  const handleEvaluate = async () => {
    try {
      setEvaluating(true);
      const res = await fetch("/api/analysis/forecast-accuracy/evaluate", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-csrf-token": csrf(),
        },
      });
      if (!res.ok) throw new Error(`Evaluation failed (${res.status})`);
      const updated = await res.json();
      setData(updated);
    } catch (err) {
      alert(`Evaluation error: ${err.message || String(err)}`);
    } finally {
      setEvaluating(false);
    }
  };

  const forecasts = data?.forecasts || [];
  const scoredCount = data?.scored_forecasts || 0;
  const pendingCount = data?.pending_forecasts || 0;

  return (
    <section aria-labelledby="accuracy-heading" style={{ marginBottom: "30px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px", marginBottom: "12px" }}>
        <div>
          <h2 id="accuracy-heading" style={{ margin: 0, fontSize: "1.2rem" }}>
            Forecast Accuracy &amp; Out-of-Sample Calibration
          </h2>
          <p style={{ margin: "4px 0 0", fontSize: "0.85rem", color: "var(--muted)" }}>
            Post-horizon scoring of statistical predictions against realized underlying market closes.
          </p>
        </div>
        <button
          type="button"
          onClick={handleEvaluate}
          disabled={evaluating}
          style={{
            padding: "8px 16px",
            borderRadius: "8px",
            fontSize: "0.85rem",
            fontWeight: 600,
            cursor: "pointer",
            background: "rgba(56, 189, 248, 0.15)",
            color: "#38bdf8",
            border: "1px solid rgba(56, 189, 248, 0.4)",
          }}
        >
          {evaluating ? "Scoring pending…" : "⚡ Evaluate Pending Outcomes"}
        </button>
      </div>

      {loading && !data ? (
        <p role="status">Loading forecast accuracy records…</p>
      ) : error ? (
        <div className="error" role="alert">
          <p>{error}</p>
        </div>
      ) : data ? (
        <>
          {/* Calibration Status Banner */}
          <div style={{
            background: data.calibration_status === "CALIBRATED_RESEARCH" ? "rgba(16, 185, 129, 0.1)" : "rgba(245, 158, 11, 0.1)",
            border: `1px solid ${data.calibration_status === "CALIBRATED_RESEARCH" ? "#10b981" : "#f59e0b"}`,
            padding: "12px 16px",
            borderRadius: "8px",
            marginBottom: "16px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: "8px",
          }}>
            <div>
              <strong>Calibration Status: </strong>
              <span style={{
                color: data.calibration_status === "CALIBRATED_RESEARCH" ? "#10b981" : "#f59e0b",
                fontWeight: "bold",
                marginRight: "8px"
              }}>
                {data.calibration_status}
              </span>
              <span style={{ fontSize: "0.85rem", color: "var(--muted)" }}>{data.calibration_reason}</span>
            </div>
            <div style={{ fontSize: "0.82rem", color: "var(--muted)" }}>
              Sample: <strong>{scoredCount}</strong> scored · <strong>{pendingCount}</strong> pending
            </div>
          </div>

          {/* Metric Cards Grid */}
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
            gap: "12px",
            marginBottom: "20px"
          }}>
            <div style={{ background: "var(--card-subtle, #131c31)", padding: "14px", borderRadius: "10px", border: "1px solid var(--line)" }}>
              <span style={{ fontSize: "0.8rem", color: "var(--muted)", textTransform: "uppercase" }}>Directional Win Rate</span>
              <div style={{ fontSize: "1.3rem", fontWeight: "bold", marginTop: "4px", color: (data.directional_accuracy_pct || 0) >= 50 ? "#10b981" : "#ef4444" }}>
                {pct(data.directional_accuracy_pct)}
              </div>
              <small style={{ color: "var(--muted)" }}>Over {scoredCount} realized horizons</small>
            </div>

            <div style={{ background: "var(--card-subtle, #131c31)", padding: "14px", borderRadius: "10px", border: "1px solid var(--line)" }}>
              <span style={{ fontSize: "0.8rem", color: "var(--muted)", textTransform: "uppercase" }}>Mean Brier Score</span>
              <div style={{ fontSize: "1.3rem", fontWeight: "bold", marginTop: "4px", color: "#38bdf8" }}>
                {num(data.brier_score)}
              </div>
              <small style={{ color: "var(--muted)" }}>Prior baseline: {num(data.prior_brier_score)}</small>
            </div>

            <div style={{ background: "var(--card-subtle, #131c31)", padding: "14px", borderRadius: "10px", border: "1px solid var(--line)" }}>
              <span style={{ fontSize: "0.8rem", color: "var(--muted)", textTransform: "uppercase" }}>Brier Skill Score (BSS)</span>
              <div style={{
                fontSize: "1.3rem",
                fontWeight: "bold",
                marginTop: "4px",
                color: (data.brier_skill_score_pct || 0) > 0 ? "#10b981" : "#f59e0b"
              }}>
                {(data.brier_skill_score_pct || 0) > 0 ? "+" : ""}{pct(data.brier_skill_score_pct)}
              </div>
              <small style={{ color: "var(--muted)" }}>Relative to empirical prior</small>
            </div>

            <div style={{ background: "var(--card-subtle, #131c31)", padding: "14px", borderRadius: "10px", border: "1px solid var(--line)" }}>
              <span style={{ fontSize: "0.8rem", color: "var(--muted)", textTransform: "uppercase" }}>Log Loss (Cross-Entropy)</span>
              <div style={{ fontSize: "1.3rem", fontWeight: "bold", marginTop: "4px" }}>
                {num(data.log_loss)}
              </div>
              <small style={{ color: "var(--muted)" }}>Binary directional target</small>
            </div>
          </div>

          {/* Breakdown By Instrument */}
          {data.by_instrument && Object.keys(data.by_instrument).length > 0 && (
            <div style={{ marginBottom: "20px" }}>
              <h4 style={{ fontSize: "0.95rem", marginBottom: "8px" }}>Accuracy by Instrument</h4>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "10px" }}>
                {Object.entries(data.by_instrument).map(([inst, stat]) => (
                  <div key={inst} style={{ background: "var(--card-subtle, #131c31)", padding: "12px", borderRadius: "8px", border: "1px solid var(--line)" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
                      <strong>{inst}</strong>
                      <span style={{ fontWeight: "bold", color: stat.accuracy_pct >= 50 ? "#10b981" : "#ef4444" }}>
                        {pct(stat.accuracy_pct)}
                      </span>
                    </div>
                    <div style={{ fontSize: "0.8rem", color: "var(--muted)" }}>
                      Total: {stat.total} · Brier: {num(stat.brier_score)}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Forecast-versus-Actual History Table */}
          <div style={{ marginBottom: "30px" }}>
            <h4 style={{ fontSize: "0.95rem", marginBottom: "8px" }}>
              Forecast-versus-Actual Outcomes History ({forecasts.length} total logged)
            </h4>
            <div className="table-wrap" style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem", textAlign: "left" }}>
                <thead>
                  <tr style={{ borderBottom: "2px solid var(--line)", background: "rgba(255,255,255,0.02)" }}>
                    <th style={{ padding: "8px" }}>Analysis / Time</th>
                    <th style={{ padding: "8px" }}>Instrument</th>
                    <th style={{ padding: "8px" }}>Predicted</th>
                    <th style={{ padding: "8px" }}>Prob (Up)</th>
                    <th style={{ padding: "8px" }}>Prior Spot</th>
                    <th style={{ padding: "8px" }}>Subsequent Spot</th>
                    <th style={{ padding: "8px" }}>Realized Ret</th>
                    <th style={{ padding: "8px" }}>Outcome</th>
                    <th style={{ padding: "8px" }}>Brier</th>
                    <th style={{ padding: "8px" }}>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {forecasts.slice().reverse().slice(0, 30).map((f) => {
                    const out = f.subsequent_outcome;
                    const isCorrect = out?.direction_correct;
                    const isPending = f.evaluation_status === "PENDING_SUBSEQUENT_CLOSE";

                    return (
                      <tr key={f.record_id || f.analysis_id} style={{ borderBottom: "1px solid var(--line, #1e293b)" }}>
                        <td style={{ padding: "8px", color: "var(--muted)" }}>
                          <div>{f.recorded_at ? new Date(f.recorded_at).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—"}</div>
                          <small style={{ fontSize: "0.72rem", color: "var(--muted)", fontFamily: "monospace" }}>{f.analysis_id?.slice(0, 8)}</small>
                        </td>
                        <td style={{ padding: "8px" }}><strong>{f.instrument}</strong></td>
                        <td style={{ padding: "8px" }}>
                          <span style={{ color: f.predicted_direction === "BULLISH" ? "#10b981" : "#ef4444", fontWeight: "bold" }}>
                            {f.predicted_direction}
                          </span>
                        </td>
                        <td style={{ padding: "8px" }}>{pct(f.probability_up * 100)}</td>
                        <td style={{ padding: "8px" }}>{inr(f.spot_price_at_prediction)}</td>
                        <td style={{ padding: "8px" }}>{out?.spot_price_subsequent ? inr(out.spot_price_subsequent) : "—"}</td>
                        <td style={{ padding: "8px", color: out?.realized_return_pct >= 0 ? "#10b981" : "#ef4444" }}>
                          {out?.realized_return_pct != null ? `${out.realized_return_pct >= 0 ? "+" : ""}${pct(out.realized_return_pct)}` : "—"}
                        </td>
                        <td style={{ padding: "8px" }}>
                          {isPending ? (
                            <span style={{ color: "#f59e0b", fontSize: "0.78rem" }}>⏳ Horizon pending</span>
                          ) : isCorrect ? (
                            <span style={{ color: "#10b981", fontWeight: "bold" }}>✓ Correct ({out.actual_direction})</span>
                          ) : (
                            <span style={{ color: "#ef4444", fontWeight: "bold" }}>✗ Incorrect ({out.actual_direction})</span>
                          )}
                        </td>
                        <td style={{ padding: "8px" }}>{out?.brier_score != null ? num(out.brier_score) : "—"}</td>
                        <td style={{ padding: "8px" }}>
                          <span className={`pill ${isPending ? "uncalibrated" : "good"}`} style={{ fontSize: "0.72rem" }}>
                            {isPending ? "PENDING" : "SCORED"}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {forecasts.length > 30 && (
                <p style={{ fontSize: "0.8rem", color: "var(--muted)", marginTop: "8px" }}>
                  Showing latest 30 forecasts of {forecasts.length} logged.
                </p>
              )}
            </div>
          </div>
        </>
      ) : null}
    </section>
  );
}

function Approved() {
  const read = useRead("/api/forecasts");
  const rows = read.body?.forecasts || [];
  return (
    <section aria-labelledby="approved-heading" data-testid="approved-forecasts">
      <h2 id="approved-heading">Approved forecasts</h2>
      <ReadState
        phase={read.phase}
        error={read.error}
        onRetry={read.retry}
        empty={read.phase === "ready" && rows.length === 0}
        emptyText="No approved forecast was returned."
        loadingText="Loading the forecast list…"
      >
        {read.body ? (
          <>
            <p>Forecast ready {flagLabel(read.body.forecast_ready)}. {valueText(read.body.note)}</p>
            <ul>
              {rows.map((row, index) => <li key={row.id || index}>{valueText(row.id)}</li>)}
            </ul>
          </>
        ) : null}
      </ReadState>
    </section>
  );
}

function Models() {
  const read = useRead("/api/models");
  const rows = read.body?.models || [];
  return (
    <section aria-labelledby="models-heading" data-testid="forecast-models">
      <h2 id="models-heading">Registered models</h2>
      <ReadState
        phase={read.phase}
        error={read.error}
        onRetry={read.retry}
        empty={read.phase === "ready" && rows.length === 0}
        emptyText="No model rows were returned. That is not an approval."
        loadingText="Loading registered models…"
      >
        {read.body ? (
          <>
            <p>Forecast ready {flagLabel(read.body.forecast_ready)}. Paper approved {flagLabel(read.body.paper_approved)}. Live approved {flagLabel(read.body.live_approved)}. Market data verified {flagLabel(read.body.real_market_data_verified)}.</p>
            <div className="table-wrap">
              <table>
                <caption>Model lineage and verification flags</caption>
                <thead>
                  <tr>
                    <th>Model</th>
                    <th>Status</th>
                    <th>Origin</th>
                    <th>Class</th>
                    <th>Dataset</th>
                    <th>Checksum</th>
                    <th>Evaluated</th>
                    <th>Forecast ready</th>
                    <th>Paper</th>
                    <th>Live</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => {
                    const kind = observationClass({ origin: row.origin, synthetic: row.synthetic, real_market_data_verified: row.real_market_data_verified, live_market_data: false });
                    return (
                      <tr key={row.version_id || `${row.model_id}-${row.version}`}>
                        <td>{valueText(row.model_id)} {valueText(row.version)}</td>
                        <td>{valueText(row.status)}</td>
                        <td>{valueText(row.origin)}</td>
                        <td><span className={`data-badge ${kind.code}`}>{kind.label}</span></td>
                        <td>{valueText(row.training_dataset_id)}</td>
                        <td>{valueText(row.training_dataset_checksum)}</td>
                        <td>{valueText(row.last_evaluated_at)}</td>
                        <td>{flagLabel(row.forecast_ready)}</td>
                        <td>{flagLabel(row.paper_approved)}</td>
                        <td>{flagLabel(row.live_approved)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        ) : null}
      </ReadState>
    </section>
  );
}

function Experiments() {
  const read = useRead("/api/experiments");
  const holdout = read.body?.holdout || [];
  const walk = read.body?.walk_forward || [];
  const empty = read.phase === "ready" && holdout.length === 0 && walk.length === 0;
  return (
    <section aria-labelledby="experiments-heading" data-testid="experiments">
      <h2 id="experiments-heading">Saved experiments</h2>
      <ReadState phase={read.phase} error={read.error} onRetry={read.retry} empty={empty} emptyText="No saved experiments were returned." loadingText="Loading saved experiments…">
        {read.body ? (
          <>
            <p>Forecast ready {flagLabel(read.body.forecast_ready)}. These rows are research results, not an approved forecast.</p>
            <ExperimentTable title="Holdout" rows={holdout} />
            <ExperimentTable title="Walk-forward" rows={walk} />
          </>
        ) : null}
      </ReadState>
    </section>
  );
}

function ExperimentTable({ title, rows }) {
  return (
    <>
      <h3>{title}</h3>
      {rows.length === 0 ? <p>No {title.toLowerCase()} rows were returned.</p> : (
        <div className="table-wrap">
          <table>
            <caption>{title} experiment lineage</caption>
            <thead>
              <tr>
                <th>Experiment</th>
                <th>Origin</th>
                <th>Class</th>
                <th>Dataset</th>
                <th>Instrument</th>
                <th>Horizon</th>
                <th>Selected model</th>
                <th>Incomplete</th>
                <th>Evaluation</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const kind = observationClass({ origin: row.origin, real_market_data_verified: false, live_market_data: false });
                return (
                  <tr key={row.experiment_id || `${row.kind}-${row.code}`}>
                    <td>{valueText(row.experiment_id)}{row.ok === false ? ` (${valueText(row.code)})` : ""}</td>
                    <td>{valueText(row.origin)}</td>
                    <td><span className={`data-badge ${kind.code}`}>{kind.label}</span></td>
                    <td>{valueText(row.dataset_id)}</td>
                    <td>{valueText(row.instrument)}</td>
                    <td>{valueText(row.horizon)}</td>
                    <td>{valueText(row.selected_model)}</td>
                    <td>{valueText(row.incomplete)}</td>
                    <td>{evaluationText(row.aggregate)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function evaluationText(aggregate) {
  if (aggregate === undefined) return "not returned";
  if (aggregate === null) return "not set";
  if (typeof aggregate !== "object") return valueText(aggregate);
  const entries = Object.entries(aggregate);
  if (entries.length === 0) return "no metrics returned";
  return entries.map(([key, value]) => `${key}: ${valueText(value)}`).join("; ");
}
