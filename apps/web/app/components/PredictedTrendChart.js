"use client";

import { useEffect, useMemo, useState } from "react";
import { useMarketData } from "./MarketDataContext";

export default function PredictedTrendChart() {
  const { selectedInstrument, selectInstrument, spots, selectedModel, setSelectedModel, selectedStrategyMode, setSelectedStrategyMode } = useMarketData();
  const [instrument, setInstrument] = useState(selectedInstrument || "NIFTY");
  const [barsCount, setBarsCount] = useState(35);
  const [chartData, setChartData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [hoveredPoint, setHoveredPoint] = useState(null);

  useEffect(() => {
    if (selectedInstrument && selectedInstrument !== instrument) {
      setInstrument(selectedInstrument);
    }
  }, [selectedInstrument]);

  useEffect(() => {
    let cancelled = false;
    async function fetchChart() {
      setLoading(true);
      setError(null);
      try {
        const mParam = selectedModel || "champion";
        const modeParam = selectedStrategyMode || "regime_gated";
        const res = await fetch(`/api/forecasting/live-trend-chart?instrument=${instrument}&bars=${barsCount}&model=${mParam}&strategy_mode=${modeParam}`);
        if (!res.ok) {
          throw new Error(`Failed to load live trend data for ${instrument} (${res.status})`);
        }
        const data = await res.json();
        if (!cancelled) {
          setChartData(data);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err.message || String(err));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    fetchChart();
    const interval = setInterval(fetchChart, 15000); // Polling every 15s during live market
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [instrument, barsCount, selectedModel, selectedStrategyMode]);

  const handleInstrumentChange = (inst) => {
    setInstrument(inst);
    if (selectInstrument) {
      selectInstrument(inst);
    }
  };

  // Derive SVG Coordinate Scales
  const viewGeometry = useMemo(() => {
    if (!chartData || !chartData.candles || chartData.candles.length === 0) {
      return null;
    }

    const candles = chartData.candles;
    const projected = chartData.projected_path || [];

    const histLows = candles.map((c) => c.low);
    const histHighs = candles.map((c) => c.high);
    const projLow = projected.length > 0 ? Math.min(...projected.map((p) => p.lower_bound)) : chartData.current_spot;
    const projHigh = projected.length > 0 ? Math.max(...projected.map((p) => p.upper_bound)) : chartData.current_spot;

    const stopVal = chartData.stop_loss_spot || histLows[0];
    const targetVal = chartData.target_spot || histHighs[0];

    const allMins = [...histLows, projLow, stopVal, targetVal].filter(Number.isFinite);
    const allMaxs = [...histHighs, projHigh, stopVal, targetVal].filter(Number.isFinite);

    const minPrice = Math.min(...allMins);
    const maxPrice = Math.max(...allMaxs);
    const pricePadding = (maxPrice - minPrice) * 0.08 || 10;

    const domainMin = minPrice - pricePadding;
    const domainMax = maxPrice + pricePadding;
    const domainRange = domainMax - domainMin;

    // SVG Canvas Dimensions
    const svgW = 840;
    const svgH = 340;
    const chartTop = 30;
    const chartBottom = 290;
    const chartHeight = chartBottom - chartTop;

    const histLeft = 45;
    const histRight = 620;
    const histWidth = histRight - histLeft;

    const projRight = 815;

    const priceToY = (price) => {
      if (domainRange <= 0) return svgH / 2;
      return chartBottom - ((price - domainMin) / domainRange) * chartHeight;
    };

    const candleWidth = Math.max(4, Math.min(16, (histWidth / candles.length) - 3));

    return {
      domainMin,
      domainMax,
      domainRange,
      svgW,
      svgH,
      chartTop,
      chartBottom,
      histLeft,
      histRight,
      projRight,
      priceToY,
      candleWidth,
      candles,
      projected,
    };
  }, [chartData]);

  const isBuy = chartData?.decision === "BUY";
  const isSell = chartData?.decision === "SELL";
  const isNeutral = !isBuy && !isSell;
  const trendColor = isBuy ? "#10b981" : isSell ? "#f43f5e" : "#f59e0b";
  const trendBgColor = isBuy ? "rgba(16, 185, 129, 0.12)" : isSell ? "rgba(244, 63, 94, 0.12)" : "rgba(245, 158, 11, 0.12)";

  return (
    <section
      aria-labelledby="trend-chart-heading"
      style={{
        background: "var(--card-subtle, #131c31)",
        border: "1px solid var(--line, #334155)",
        borderRadius: "12px",
        padding: "20px",
        marginBottom: "28px",
      }}
    >
      {/* Header and Instrument Switcher */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "10px", marginBottom: "14px" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "4px" }}>
            <span className="pill info" style={{ fontSize: "0.72rem", padding: "2px 8px" }}>
              LIVE QUANT PREDICTIVE DESK
            </span>
            <span className={`pill ${chartData?.is_live ? "ok" : "warn"}`} style={{ fontSize: "0.72rem", padding: "2px 8px" }}>
              {chartData?.is_live ? "🟢 LIVE FEED TICKING" : "VERIFIED HISTORICAL BARS"}
            </span>
          </div>
          <h2 id="trend-chart-heading" style={{ margin: 0, fontSize: "1.25rem", fontWeight: 700, color: "var(--ink, #f8fafc)" }}>
            📈 Live Price Action &amp; Forward Projected Trend Graph
          </h2>
          <p style={{ margin: "4px 0 0", fontSize: "0.85rem", color: "var(--sub, #94a3b8)" }}>
            Real-time candle ledger with forward projected model trajectory and ±1σ volatility confidence cone.
          </p>
        </div>

        {/* Controls: Instrument & Bars */}
        <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
          <div style={{ display: "flex", background: "var(--bg, #0f172a)", border: "1px solid var(--line, #334155)", borderRadius: "6px", padding: "2px" }}>
            {["NIFTY", "BANKNIFTY", "SENSEX", "CRUDEOILMINI"].map((id) => (
              <button
                key={id}
                type="button"
                onClick={() => handleInstrumentChange(id)}
                className={`btn ${instrument === id ? "primary" : "secondary"}`}
                style={{
                  fontSize: "0.75rem",
                  padding: "4px 10px",
                  borderRadius: "4px",
                  background: instrument === id ? "var(--primary, #3b82f6)" : "transparent",
                  border: "none",
                }}
              >
                {id === "CRUDEOILMINI" ? "CRUDE" : id}
              </button>
            ))}
          </div>

          {/* Model Architecture Selector */}
          <select
            value={selectedModel || "champion"}
            onChange={(e) => setSelectedModel(e.target.value)}
            title="Choose SOTA Forecasting Model for Analysis"
            style={{
              padding: "5px 8px",
              background: "var(--bg, #0f172a)",
              border: "1px solid var(--line, #334155)",
              borderRadius: "6px",
              color: "var(--ink, #f8fafc)",
              fontSize: "0.78rem",
              fontWeight: 600,
            }}
          >
            <option value="champion">🏆 Model: Champion (Ranked #1 Auto)</option>
            <option value="lightgbm">⚡ LightGBM (GBDT SOTA)</option>
            <option value="xgboost">🚀 XGBoost (Boosting SOTA)</option>
            <option value="catboost">🐱 CatBoost (Symmetric Trees)</option>
            <option value="dlinear">📐 DLinear (Decomposition SOTA)</option>
            <option value="chronos">⏳ Chronos-2 (Foundation Transformer)</option>
            <option value="random_forest">🌲 Random Forest (Ensemble SOTA)</option>
            <option value="mlp">🧠 MLP (Deep Neural Net)</option>
            <option value="logistic_regression">📊 Logistic Regression (Baseline)</option>
            <option value="empirical_prior">🎲 Empirical Prior (Majority Baseline)</option>
          </select>

          {/* Strategy Gating Mode Selector */}
          <select
            value={selectedStrategyMode || "regime_gated"}
            onChange={(e) => setSelectedStrategyMode(e.target.value)}
            title="Choose Strategy Gating Mode"
            style={{
              padding: "5px 8px",
              background: "var(--bg, #0f172a)",
              border: "1px solid var(--line, #334155)",
              borderRadius: "6px",
              color: "var(--ink, #f8fafc)",
              fontSize: "0.78rem",
            }}
          >
            <option value="regime_gated">Regime-Gated (Consensus)</option>
            <option value="deadband">Deadband (48%–52%)</option>
            <option value="raw">Raw Directional</option>
          </select>

          <select
            value={barsCount}
            onChange={(e) => setBarsCount(Number(e.target.value))}
            style={{
              padding: "5px 8px",
              background: "var(--bg, #0f172a)",
              border: "1px solid var(--line, #334155)",
              borderRadius: "6px",
              color: "var(--ink, #f8fafc)",
              fontSize: "0.78rem",
            }}
          >
            <option value={20}>20 Bars (5h)</option>
            <option value={35}>35 Bars (~1.5d)</option>
            <option value={50}>50 Bars (2d)</option>
          </select>
        </div>
      </div>

      {/* Dynamic Hover/Status Strip */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "8px",
          padding: "8px 12px",
          background: "rgba(255,255,255,0.02)",
          border: "1px solid var(--line, #334155)",
          borderRadius: "6px",
          fontSize: "0.82rem",
          marginBottom: "12px",
        }}
      >
        {hoveredPoint ? (
          hoveredPoint.is_projection ? (
            <div style={{ display: "flex", gap: "16px", flexWrap: "wrap" }}>
              <span style={{ color: "#38bdf8", fontWeight: 700 }}>🔮 Horizon: {hoveredPoint.time}</span>
              <span><strong>Projected Target:</strong> ₹{hoveredPoint.projected_price?.toLocaleString("en-IN")}</span>
              <span style={{ color: "#34d399" }}><strong>Upper Bound (+1σ):</strong> ₹{hoveredPoint.upper_bound?.toLocaleString("en-IN")}</span>
              <span style={{ color: "#f87171" }}><strong>Lower Bound (-1σ):</strong> ₹{hoveredPoint.lower_bound?.toLocaleString("en-IN")}</span>
            </div>
          ) : (
            <div style={{ display: "flex", gap: "14px", flexWrap: "wrap" }}>
              <span style={{ color: "var(--sub)" }}><strong>Bar:</strong> {hoveredPoint.full_time}</span>
              <span><strong>Open:</strong> ₹{hoveredPoint.open}</span>
              <span><strong>High:</strong> ₹{hoveredPoint.high}</span>
              <span><strong>Low:</strong> ₹{hoveredPoint.low}</span>
              <span style={{ color: hoveredPoint.close >= hoveredPoint.open ? "#34d399" : "#f87171" }}>
                <strong>Close:</strong> ₹{hoveredPoint.close}
              </span>
              <span style={{ color: "var(--muted)" }}><strong>Vol:</strong> {hoveredPoint.volume?.toLocaleString("en-IN")}</span>
            </div>
          )
        ) : (
          <div style={{ display: "flex", gap: "16px", flexWrap: "wrap", alignItems: "center" }}>
            <span><strong>Asset:</strong> {instrument}</span>
            <span>
              <strong>Model:</strong>{" "}
              <span style={{ color: "#a855f7", fontWeight: 700 }}>
                {chartData?.model_name ? chartData.model_name.toUpperCase() : (selectedModel || "CHAMPION").toUpperCase()}
              </span>
            </span>
            <span>
              <strong>Live Spot:</strong>{" "}
              <span style={{ color: "#38bdf8", fontWeight: 700 }}>
                ₹{chartData?.current_spot != null ? chartData.current_spot.toLocaleString("en-IN", { minimumFractionDigits: 2 }) : "---"}
              </span>
            </span>
            <span>
              <strong>Direction:</strong>{" "}
              <span style={{ color: trendColor, fontWeight: 700 }}>
                {chartData?.predicted_direction || "NEUTRAL"}
              </span>
            </span>
            <span>
              <strong>Target:</strong> ₹{chartData?.target_spot?.toLocaleString("en-IN") || "---"}
            </span>
            <span>
              <strong>Stop Loss:</strong> ₹{chartData?.stop_loss_spot?.toLocaleString("en-IN") || "---"}
            </span>
            <span>
              <strong>Decision:</strong>{" "}
              <span className={`pill ${chartData?.decision === "BUY" ? "ok" : chartData?.decision === "SELL" ? "err" : "info"}`} style={{ fontSize: "0.72rem", padding: "1px 6px" }}>
                {chartData?.decision || "NO TRADE"}
              </span>
            </span>
          </div>
        )}
      </div>

      {/* SVG Canvas Area */}
      {loading && !chartData ? (
        <div style={{ height: "340px", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--sub)" }}>
          Loading live price action and model projection…
        </div>
      ) : error ? (
        <div style={{ padding: "16px", background: "rgba(239, 68, 68, 0.1)", border: "1px solid #ef4444", borderRadius: "8px", color: "#fca5a5" }}>
          {error}
        </div>
      ) : viewGeometry ? (
        <div style={{ width: "100%", overflowX: "auto", position: "relative" }}>
          <svg
            viewBox={`0 0 ${viewGeometry.svgW} ${viewGeometry.svgH}`}
            style={{ width: "100%", height: "auto", display: "block", background: "#0b1120", borderRadius: "8px", border: "1px solid var(--line)" }}
          >
            <defs>
              {/* Gradient for forward forecast confidence cone */}
              <linearGradient id="forecastConeGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor={trendColor} stopOpacity="0.22" />
                <stop offset="100%" stopColor={trendColor} stopOpacity="0.04" />
              </linearGradient>
            </defs>

            {/* Background Grid Lines */}
            {[0.2, 0.4, 0.6, 0.8].map((ratio, idx) => {
              const y = viewGeometry.chartTop + ratio * (viewGeometry.chartBottom - viewGeometry.chartTop);
              const pVal = viewGeometry.domainMax - ratio * viewGeometry.domainRange;
              return (
                <g key={idx}>
                  <line x1={viewGeometry.histLeft} y1={y} x2={viewGeometry.projRight} y2={y} stroke="#1e293b" strokeDasharray="3 3" />
                  <text x={viewGeometry.histLeft - 8} y={y + 4} textAnchor="end" fill="#64748b" fontSize="10">
                    ₹{Math.round(pVal).toLocaleString("en-IN")}
                  </text>
                </g>
              );
            })}

            {/* Vertical Boundary Line: NOW / LIVE SPOT */}
            <line
              x1={viewGeometry.histRight}
              y1={viewGeometry.chartTop - 10}
              x2={viewGeometry.histRight}
              y2={viewGeometry.chartBottom + 20}
              stroke="#38bdf8"
              strokeWidth="1.5"
              strokeDasharray="4 4"
            />
            <text x={viewGeometry.histRight} y={viewGeometry.chartTop - 14} textAnchor="middle" fill="#38bdf8" fontSize="11" fontWeight="700">
              NOW (Live Bar)
            </text>

            {/* Target & Stop Loss Horizontal Guide Lines */}
            {chartData?.target_spot && (
              <g>
                <line
                  x1={viewGeometry.histRight}
                  y1={viewGeometry.priceToY(chartData.target_spot)}
                  x2={viewGeometry.projRight}
                  y2={viewGeometry.priceToY(chartData.target_spot)}
                  stroke="#10b981"
                  strokeWidth="1.5"
                  strokeDasharray="2 2"
                />
                <rect
                  x={viewGeometry.projRight - 65}
                  y={viewGeometry.priceToY(chartData.target_spot) - 10}
                  width="65"
                  height="18"
                  fill="#10b981"
                  rx="3"
                />
                <text
                  x={viewGeometry.projRight - 32}
                  y={viewGeometry.priceToY(chartData.target_spot) + 3}
                  textAnchor="middle"
                  fill="#ffffff"
                  fontSize="9.5"
                  fontWeight="700"
                >
                  TARGET
                </text>
              </g>
            )}

            {chartData?.stop_loss_spot && (
              <g>
                <line
                  x1={viewGeometry.histRight}
                  y1={viewGeometry.priceToY(chartData.stop_loss_spot)}
                  x2={viewGeometry.projRight}
                  y2={viewGeometry.priceToY(chartData.stop_loss_spot)}
                  stroke="#ef4444"
                  strokeWidth="1.5"
                  strokeDasharray="2 2"
                />
                <rect
                  x={viewGeometry.projRight - 65}
                  y={viewGeometry.priceToY(chartData.stop_loss_spot) - 10}
                  width="65"
                  height="18"
                  fill="#ef4444"
                  rx="3"
                />
                <text
                  x={viewGeometry.projRight - 32}
                  y={viewGeometry.priceToY(chartData.stop_loss_spot) + 3}
                  textAnchor="middle"
                  fill="#ffffff"
                  fontSize="9.5"
                  fontWeight="700"
                >
                  STOP LOSS
                </text>
              </g>
            )}

            {/* 1. Historical Candlesticks */}
            {viewGeometry.candles.map((c, i) => {
              const xCenter = viewGeometry.histLeft + (i * ((viewGeometry.histRight - viewGeometry.histLeft) / viewGeometry.candles.length));
              const yOpen = viewGeometry.priceToY(c.open);
              const yClose = viewGeometry.priceToY(c.close);
              const yHigh = viewGeometry.priceToY(c.high);
              const yLow = viewGeometry.priceToY(c.low);

              const isGreen = c.close >= c.open;
              const color = isGreen ? "#10b981" : "#ef4444";
              const candleTop = Math.min(yOpen, yClose);
              const candleHeight = Math.max(2, Math.abs(yClose - yOpen));
              const w = viewGeometry.candleWidth;

              return (
                <g
                  key={i}
                  onMouseEnter={() => setHoveredPoint(c)}
                  onMouseLeave={() => setHoveredPoint(null)}
                  style={{ cursor: "crosshair" }}
                >
                  {/* Wick */}
                  <line x1={xCenter} y1={yHigh} x2={xCenter} y2={yLow} stroke={color} strokeWidth="1" />
                  {/* Body */}
                  <rect
                    x={xCenter - w / 2}
                    y={candleTop}
                    width={w}
                    height={candleHeight}
                    fill={color}
                    opacity="0.85"
                    rx="1"
                  />
                  {/* Time label on select bars */}
                  {i % Math.ceil(viewGeometry.candles.length / 5) === 0 && (
                    <text x={xCenter} y={viewGeometry.chartBottom + 16} textAnchor="middle" fill="#64748b" fontSize="9">
                      {c.time}
                    </text>
                  )}
                </g>
              );
            })}

            {/* 2. Forward Projected Confidence Cone */}
            {(() => {
              const startX = viewGeometry.histRight;
              const startY = viewGeometry.priceToY(chartData.current_spot);

              const projPoints = viewGeometry.projected.map((p, idx) => {
                const x = startX + ((idx + 1) * ((viewGeometry.projRight - startX) / viewGeometry.projected.length));
                return {
                  x,
                  yTarget: viewGeometry.priceToY(p.projected_price),
                  yUpper: viewGeometry.priceToY(p.upper_bound),
                  yLower: viewGeometry.priceToY(p.lower_bound),
                  data: p,
                };
              });

              // Upper contour: startY -> upper points
              const upperPath = projPoints.map((pt) => `L ${pt.x} ${pt.yUpper}`).join(" ");
              // Lower contour in reverse
              const lowerPath = [...projPoints].reverse().map((pt) => `L ${pt.x} ${pt.yLower}`).join(" ");

              const conePolygonD = `M ${startX} ${startY} ${upperPath} ${lowerPath} Z`;
              const trendLineD = `M ${startX} ${startY} ` + projPoints.map((pt) => `L ${pt.x} ${pt.yTarget}`).join(" ");

              return (
                <g>
                  {/* Shaded Corridor */}
                  <path d={conePolygonD} fill="url(#forecastConeGrad)" />

                  {/* Upper Bound Dashed Arc */}
                  <path
                    d={`M ${startX} ${startY} ` + projPoints.map((pt) => `L ${pt.x} ${pt.yUpper}`).join(" ")}
                    stroke={trendColor}
                    strokeWidth="1.2"
                    strokeDasharray="3 3"
                    fill="none"
                    opacity="0.6"
                  />

                  {/* Lower Bound Dashed Arc */}
                  <path
                    d={`M ${startX} ${startY} ` + projPoints.map((pt) => `L ${pt.x} ${pt.yLower}`).join(" ")}
                    stroke={trendColor}
                    strokeWidth="1.2"
                    strokeDasharray="3 3"
                    fill="none"
                    opacity="0.6"
                  />

                  {/* Central Projected Trend Path */}
                  <path
                    d={trendLineD}
                    stroke={trendColor}
                    strokeWidth="2.5"
                    strokeDasharray="5 3"
                    fill="none"
                  />

                  {/* Projected Point Anchors */}
                  {projPoints.map((pt, idx) => (
                    <g
                      key={idx}
                      onMouseEnter={() => setHoveredPoint(pt.data)}
                      onMouseLeave={() => setHoveredPoint(null)}
                      style={{ cursor: "pointer" }}
                    >
                      <circle cx={pt.x} cy={pt.yTarget} r="4.5" fill={trendColor} stroke="#ffffff" strokeWidth="1.5" />
                      <text x={pt.x} y={viewGeometry.chartBottom + 16} textAnchor="middle" fill="#94a3b8" fontSize="9.5" fontWeight="600">
                        {pt.data.time}
                      </text>
                    </g>
                  ))}
                </g>
              );
            })()}

            {/* Current Spot Live Indicator Ping */}
            <g>
              <circle
                cx={viewGeometry.histRight}
                cy={viewGeometry.priceToY(chartData.current_spot)}
                r="7"
                fill="#38bdf8"
                opacity="0.3"
              >
                <animate attributeName="r" values="6;12;6" dur="2s" repeatCount="indefinite" />
                <animate attributeName="opacity" values="0.6;0.1;0.6" dur="2s" repeatCount="indefinite" />
              </circle>
              <circle
                cx={viewGeometry.histRight}
                cy={viewGeometry.priceToY(chartData.current_spot)}
                r="4.5"
                fill="#38bdf8"
                stroke="#ffffff"
                strokeWidth="1.5"
              />
            </g>
          </svg>
        </div>
      ) : null}

      {/* Legend and Model Intelligence Footer */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px", marginTop: "14px", fontSize: "0.82rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "16px", flexWrap: "wrap" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <span style={{ width: "12px", height: "12px", background: "#10b981", borderRadius: "2px", display: "inline-block" }} />
            <span style={{ color: "var(--sub)" }}>Bullish Candle</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <span style={{ width: "12px", height: "12px", background: "#ef4444", borderRadius: "2px", display: "inline-block" }} />
            <span style={{ color: "var(--sub)" }}>Bearish Candle</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <span style={{ width: "18px", height: "2px", borderTop: `2.5px dashed ${trendColor}`, display: "inline-block" }} />
            <span style={{ color: "var(--ink)", fontWeight: 600 }}>Predicted Model Trend</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <span style={{ width: "14px", height: "10px", background: trendBgColor, border: `1px solid ${trendColor}`, display: "inline-block" }} />
            <span style={{ color: "var(--sub)" }}>±1σ Volatility Cone</span>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <span className={`pill ${isBuy ? "ok" : isSell ? "warn" : "info"}`} style={{ fontSize: "0.78rem" }}>
            DECISION: {chartData?.decision || "NO TRADE"}
          </span>
          <span style={{ color: "var(--muted)", fontSize: "0.75rem" }}>
            P(Up): {chartData?.calibrated_probability != null ? `${(chartData.calibrated_probability * 100).toFixed(1)}%` : "50.0%"}
          </span>
        </div>
      </div>
    </section>
  );
}
