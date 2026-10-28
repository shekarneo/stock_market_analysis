"use client";

import { useEffect, useMemo, useState } from "react";
import { useMarketData } from "./MarketDataContext";

// Indices with saved Groww history; MCX crude has none
const HISTORY_INSTRUMENTS = new Set(["NIFTY", "BANKNIFTY", "SENSEX"]);

export default function InstrumentHistoricalChart() {
  const { selectedInstrument, spots, instrumentConfig } = useMarketData();
  const [candles, setCandles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [timeframe, setTimeframe] = useState("15minute");
  const [hoveredCandle, setHoveredCandle] = useState(null);

  const activeId = selectedInstrument || "NIFTY";
  const cfg = instrumentConfig || {};
  const spot = spots[activeId] || (activeId === "CRUDEOILMINI" ? spots["CRUDEMINI"] : null);

  const hasHistory = HISTORY_INSTRUMENTS.has(activeId);
  const [note, setNote] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function loadCandles() {
      setLoading(true);
      setNote("");
      try {
        if (hasHistory) {
          // Saved Groww history (completed sessions), the latest 60 bars for clean rendering
          const res = await fetch(`/api/research/history-candles?instrument=${activeId}&interval=${timeframe}&limit=60`);
          const data = await res.json().catch(() => ({}));
          if (!cancelled) {
            setCandles(res.ok && Array.isArray(data.candles) ? data.candles : []);
            setNote(res.ok ? (data.status === "OK" ? `${data.source} · last fetch ${data.last_fetch ? data.last_fetch.slice(0, 16).replace("T", " ") : "unknown"} UTC` : data.message) : `HTTP ${res.status}`);
          }
        } else if (!cancelled) {
          setCandles([]);
        }
      } catch {
        if (!cancelled) setCandles([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    loadCandles();
    return () => {
      cancelled = true;
    };
  }, [activeId, timeframe, hasHistory]);

  // Window stats come from the candles only; nothing is shown without them
  const stats = useMemo(() => {
    if (!candles || candles.length === 0) {
      return { min: null, max: null, last: null };
    }
    const highs = candles.map((c) => Number(c.high || c[2]));
    const lows = candles.map((c) => Number(c.low || c[3]));
    const closes = candles.map((c) => Number(c.close || c[4]));
    const minVal = Math.min(...lows);
    const maxVal = Math.max(...highs);
    const lastVal = closes[closes.length - 1];
    return { min: minVal, max: maxVal, last: lastVal, range: maxVal - minVal };
  }, [candles, spot]);

  return (
    <div className="v6-card" data-testid="instrument-historical-chart">
      <div className="v6-card-header">
        <div>
          <span className="v6-badge-sub">Interactive Market Data Chart</span>
          <h2 className="v6-card-title">{cfg.name || activeId} Price Action & Volume</h2>
        </div>
        <div className="v6-header-controls">
          <div className="v6-timeframe-selector">
            {["15minute", "1hour", "1day"].map((tf) => (
              <button
                key={tf}
                type="button"
                className={`v6-tf-btn ${timeframe === tf ? "active" : ""}`}
                onClick={() => setTimeframe(tf)}
              >
                {tf === "15minute" ? "15m" : tf === "1hour" ? "1H" : "1D"}
              </button>
            ))}
          </div>
          <span className="v6-pill cyan">
            Live: ₹{spot != null ? Number(spot).toLocaleString("en-IN") : "---"}
          </span>
        </div>
      </div>

      {/* Crosshair / Hover Header Bar */}
      <div className="v6-chart-stats-bar">
        {hoveredCandle ? (
          <>
            <span><strong>Time:</strong> {hoveredCandle.time}</span>
            <span><strong>O:</strong> ₹{hoveredCandle.open}</span>
            <span><strong>H:</strong> ₹{hoveredCandle.high}</span>
            <span><strong>L:</strong> ₹{hoveredCandle.low}</span>
            <span><strong>C:</strong> ₹{hoveredCandle.close}</span>
            <span><strong>Vol:</strong> {hoveredCandle.volume}</span>
          </>
        ) : (
          <>
            <span><strong>Instrument:</strong> {cfg.name || activeId}</span>
            <span><strong>Exchange:</strong> {cfg.exchange}</span>
            <span><strong>Session:</strong> {cfg.session}</span>
            <span><strong>High (Window):</strong> {stats.max != null ? `₹${stats.max.toLocaleString("en-IN")}` : "N/A"}</span>
            <span><strong>Low (Window):</strong> {stats.min != null ? `₹${stats.min.toLocaleString("en-IN")}` : "N/A"}</span>
          </>
        )}
      </div>

      {note ? <p className="v6-section-desc" style={{ fontSize: "0.78rem" }} data-testid="historical-chart-source">{note}</p> : null}
      {loading ? (
        <div className="v6-loading-box">Loading the saved Groww candles…</div>
      ) : !hasHistory ? (
        <div className="v6-chart-data-gap-view">
          <div className="v6-gap-icon">📊</div>
          <h3>Historical Candle Ingestion Status for {cfg.name || activeId}</h3>
          <p>
            MCX Crude Oil Mini: Groww Trade API does not provide historical commodity candle feeds. External global crude
            benchmarks (Brent/WTI) serve as macro indicators and cannot be plotted as MCX exchange execution candles.
          </p>
          <div className="v6-provenance-box">
            <strong>Current Live Spot:</strong> ₹{spot != null ? Number(spot).toLocaleString("en-IN") : "Awaiting quote"}
            <span className="v6-pill amber">Feed: {cfg.dataSource}</span>
          </div>
        </div>
      ) : candles.length === 0 ? (
        <div className="v6-empty-box">No completed candles available for {activeId} in the selected timeframe.</div>
      ) : (
        <div className="v6-svg-chart-container">
          <svg className="v6-candlestick-svg" viewBox="0 0 800 320" preserveAspectRatio="none">
            {/* Horizontal Grid lines */}
            <line x1="0" y1="40" x2="800" y2="40" stroke="#1e293b" strokeDasharray="4" />
            <line x1="0" y1="120" x2="800" y2="120" stroke="#1e293b" strokeDasharray="4" />
            <line x1="0" y1="200" x2="800" y2="200" stroke="#1e293b" strokeDasharray="4" />
            <line x1="0" y1="260" x2="800" y2="260" stroke="#1e293b" strokeDasharray="2" />

            {/* Candle Rendering */}
            {candles.map((c, i) => {
              const o = Number(c.open || c[1]);
              const h = Number(c.high || c[2]);
              const l = Number(c.low || c[3]);
              const close = Number(c.close || c[4]);
              const vol = Number(c.volume || c[5] || 0);

              const range = Math.max(1, stats.range);
              const x = 30 + (i * (740 / candles.length));
              const candleW = Math.max(3, (740 / candles.length) - 3);

              // SVG Y is inverted (0 top, 240 bottom for price)
              const yHigh = 240 - (((h - stats.min) / range) * 220);
              const yLow = 240 - (((l - stats.min) / range) * 220);
              const yOpen = 240 - (((o - stats.min) / range) * 220);
              const yClose = 240 - (((close - stats.min) / range) * 220);

              const isGreen = close >= o;
              const barColor = isGreen ? "#10b981" : "#f43f5e";
              const candleTop = Math.min(yOpen, yClose);
              const candleHeight = Math.max(2, Math.abs(yClose - yOpen));

              // Volume bar (y from 260 to 310)
              const volH = Math.min(50, (vol / 50000) * 45);

              return (
                <g
                  key={i}
                  className="v6-candle-group"
                  onMouseEnter={() =>
                    setHoveredCandle({
                      time: c.timestamp ? new Date(c.timestamp).toLocaleTimeString("en-IN") : `Bar ${i}`,
                      open: o.toFixed(1),
                      high: h.toFixed(1),
                      low: l.toFixed(1),
                      close: close.toFixed(1),
                      volume: vol.toLocaleString("en-IN"),
                    })
                  }
                  onMouseLeave={() => setHoveredCandle(null)}
                >
                  {/* High-Low Wick */}
                  <line x1={x + candleW / 2} y1={yHigh} x2={x + candleW / 2} y2={yLow} stroke={barColor} strokeWidth="1.2" />
                  {/* Candle Body */}
                  <rect x={x} y={candleTop} width={candleW} height={candleHeight} fill={barColor} rx="1" />
                  {/* Volume Bar */}
                  <rect x={x} y={310 - volH} width={candleW} height={volH} fill={barColor} opacity="0.35" />
                </g>
              );
            })}
          </svg>
        </div>
      )}

      <div className="v6-chart-footer">
        <span><strong>Storage:</strong> saved Groww history <code>var/datasets/history</code></span>
        <span><strong>Interval:</strong> {timeframe === "1hour" ? "1-hour bars built from 15-minute bars" : `${timeframe} bars`}, completed sessions only</span>
      </div>
    </div>
  );
}
