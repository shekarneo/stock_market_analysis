"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { csrfToken as csrf } from "./session";

export const INSTRUMENT_CONFIGS = {
  NIFTY: {
    id: "NIFTY",
    name: "NIFTY 50",
    symbol: "NSE:NIFTY50-INDEX",
    growwSymbol: "NSE-NIFTY",
    exchange: "NSE",
    segment: "NSE_CASH",
    // Lot size and strike step come from /api/forecasting/instruments (backend instrument master)
    session: "09:15 - 15:30 IST",
    sessionType: "NSE Regular Session",
    // Fallback until /api/forecasting/instruments answers; the history depth comes only from the backend
    dataSource: "Groww live quote (with day OHLC) + saved Groww history",
    dataFreshness: "Loading…",
    availableHistory: "Loading…",
    forecastHorizons: ["Rest of day (15-minute checkpoints)", "Next session"],
    validationStatus: "RANGE_VALIDATED",
    modelsValidated: ["Next-session range", "Rest-of-day range"],
    optionsSupported: true,
    optionsNote: "Full NSE Option Chain with continuous Black-76 Greeks & PCR Surface",
    frictionBps: 2.0,
  },
  SENSEX: {
    id: "SENSEX",
    name: "BSE SENSEX",
    symbol: "BSE:SENSEX-INDEX",
    growwSymbol: "BSE-SENSEX",
    exchange: "BSE",
    segment: "BSE_CASH",
    // Lot size and strike step come from /api/forecasting/instruments (backend instrument master)
    session: "09:15 - 15:30 IST",
    sessionType: "BSE Regular Session",
    dataSource: "Groww live quote (BSE, with day OHLC) + saved Groww history",
    dataFreshness: "Loading…",
    availableHistory: "Loading…",
    forecastHorizons: ["Rest of day (15-minute checkpoints)"],
    validationStatus: "RANGE_VALIDATED",
    modelsValidated: ["Rest-of-day range"],
    optionsSupported: true,
    optionsNote: "BSE Weekly/Monthly Option Contracts with Black-76 Greeks",
    frictionBps: 2.0,
  },
  CRUDEOILMINI: {
    id: "CRUDEOILMINI",
    name: "CRUDEOIL MINI",
    symbol: "MCX:CRUDEOILM-FUT",
    growwSymbol: null,
    exchange: "MCX",
    segment: "MCX_COMMODITY",
    // Lot size and strike step come from /api/forecasting/instruments (backend instrument master)
    session: "09:00 - 23:30 IST (23:55 winter)",
    sessionType: "MCX Extended Commodity Session",
    dataSource: "MCX Real-time Feed / International Benchmark Proxies",
    dataFreshness: "Commodity Snapshot (Groww MCX feed unavailable)",
    availableHistory: "International Benchmarks (Brent/WTI). MCX historical candles not supplied by Groww.",
    forecastHorizons: ["15m Commodity Swing", "Evening Session Multi-Hour"],
    validationStatus: "DATA_FEED_GAP_REPORTED",
    modelsValidated: [],
    optionsSupported: false,
    optionsNote: "Options Analytics DISABLED (MCX Options on Futures feed unavailable via Groww API)",
    frictionBps: 3.5,
  },
};

const MarketDataContext = createContext({
  selectedInstrument: "NIFTY",
  setSelectedInstrument: () => {},
  instrumentConfig: INSTRUMENT_CONFIGS.NIFTY,
  supportedInstruments: Object.values(INSTRUMENT_CONFIGS),
  spots: {},
  quotes: [],
  commodities: [],
  globalIndices: [],
  sectoralIndices: [],
  selectedModel: "champion",
  setSelectedModel: () => {},
  selectedStrategyMode: "regime_gated",
  setSelectedStrategyMode: () => {},
  retrievedAt: null,
  pollConfig: { enabled: true, interval_seconds: 15, status: "RUNNING" },
  isRefreshing: false,
  refreshNow: async () => {},
  setPollInterval: async () => {},
  togglePolling: async () => {},
});

export function MarketDataProvider({ children }) {
  const [selectedInstrument, setSelectedInstrument] = useState("NIFTY");
  const [selectedModel, setSelectedModelState] = useState("champion");
  const [selectedStrategyMode, setSelectedStrategyModeState] = useState("regime_gated");

  useEffect(() => {
    try {
      const savedM = localStorage.getItem("imm_selected_model");
      if (savedM) setSelectedModelState(savedM);
      const savedMode = localStorage.getItem("imm_selected_strategy_mode");
      if (savedMode) setSelectedStrategyModeState(savedMode);
    } catch (_) {}
  }, []);

  const setSelectedModel = useCallback((m) => {
    setSelectedModelState(m);
    try { localStorage.setItem("imm_selected_model", m); } catch (_) {}
  }, []);

  const setSelectedStrategyMode = useCallback((mode) => {
    setSelectedStrategyModeState(mode);
    try { localStorage.setItem("imm_selected_strategy_mode", mode); } catch (_) {}
  }, []);

  const [instrumentsCatalog, setInstrumentsCatalog] = useState(Object.values(INSTRUMENT_CONFIGS));
  const [data, setData] = useState(null);
  const [pollConfig, setPollConfig] = useState({ enabled: true, interval_seconds: 15, status: "RUNNING" });
  const [isRefreshing, setIsRefreshing] = useState(false);
  const timerRef = useRef(null);

  // Parse unified spot map across all instruments from live or cached observations
  const spots = {};
  const rawQuotes = data?.quotes || [];
  const commodities = data?.commodities || [];
  const globalIndices = data?.global_indices || [];
  const sectoralIndices = data?.sectoral_indices || [];

  for (const q of rawQuotes) {
    if (q.instrument && q.last_price != null) {
      spots[q.instrument] = Number(q.last_price);
    }
  }

  for (const c of commodities) {
    if (c.instrument && c.last_price != null) {
      spots[c.instrument] = Number(c.last_price);
      if (c.instrument === "CRUDEMINI") spots["CRUDEOILMINI"] = Number(c.last_price);
      if (c.instrument === "CRUDEOILMINI") spots["CRUDEMINI"] = Number(c.last_price);
    }
  }

  for (const s of sectoralIndices) {
    if (s.instrument && s.last_price != null) {
      spots[s.instrument] = Number(s.last_price);
    }
  }

  const indianEquities = data?.cross_market_snapshot?.indian_equities || [];
  for (const eq of indianEquities) {
    if (eq.instrument && eq.price != null) {
      spots[eq.instrument] = Number(eq.price);
    }
  }

  const observations = data?.observations || [];
  if (rawQuotes.length === 0 && observations.length > 0) {
    for (const obs of observations) {
      if (obs.instrument && obs.last_price != null && spots[obs.instrument] == null) {
        spots[obs.instrument] = Number(obs.last_price);
      }
    }
  }

  // Mirror aliases between CRUDEOILMINI and CRUDEMINI
  if (spots["CRUDEOILMINI"] != null && spots["CRUDEMINI"] == null) {
    spots["CRUDEMINI"] = spots["CRUDEOILMINI"];
  } else if (spots["CRUDEMINI"] != null && spots["CRUDEOILMINI"] == null) {
    spots["CRUDEOILMINI"] = spots["CRUDEMINI"];
  }

  let quotes = rawQuotes;
  if (quotes.length === 0 && observations.length > 0) {
    quotes = observations.map((o) => ({
      instrument: o.instrument,
      last_price: o.last_price,
      ohlc: o.ohlc,
      retrieved_at: o.retrieved_at,
      event_timestamp: o.observed_at,
      data_class: "CACHED_STALE",
      source: o.source_name || "Cached Snapshot",
      stale: true,
    }));
  }

  const fetchLiveQuotes = useCallback(async () => {
    try {
      const res = await fetch("/api/market/live-quotes");
      if (res.ok) {
        const body = await res.json();
        setData(body);
        if (body.poll_config) {
          setPollConfig((prev) => ({ ...prev, ...body.poll_config }));
        }
      }
    } catch {
      // Ignore background network transient
    }
  }, []);

  const refreshNow = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const res = await fetch("/api/market/live-quotes", {
        method: "POST",
        headers: { "content-type": "application/json", "x-csrf-token": csrf() },
        body: JSON.stringify({ confirm: true }),
      });
      if (res.ok) {
        const body = await res.json();
        setData(body);
      }
    } finally {
      setIsRefreshing(false);
      fetchLiveQuotes();
    }
  }, [fetchLiveQuotes]);

  const setPollInterval = useCallback(async (seconds) => {
    const sec = Number(seconds);
    setPollConfig((c) => ({ ...c, interval_seconds: sec }));
    try {
      await fetch("/api/market/poll-config", {
        method: "POST",
        headers: { "content-type": "application/json", "x-csrf-token": csrf() },
        body: JSON.stringify({ enabled: true, interval_seconds: sec }),
      });
    } catch {
      // Ignore
    }
  }, []);

  const togglePolling = useCallback(async () => {
    const nextState = !pollConfig.enabled;
    setPollConfig((c) => ({ ...c, enabled: nextState }));
    try {
      await fetch("/api/market/poll-config", {
        method: "POST",
        headers: { "content-type": "application/json", "x-csrf-token": csrf() },
        body: JSON.stringify({ enabled: nextState, interval_seconds: pollConfig.interval_seconds }),
      });
    } catch {
      // Ignore
    }
  }, [pollConfig.enabled, pollConfig.interval_seconds]);

  // Initial load
  useEffect(() => {
    fetchLiveQuotes();
  }, [fetchLiveQuotes]);

  // Shared polling loop synchronized with user configuration
  useEffect(() => {
    if (!pollConfig.enabled) {
      if (timerRef.current) clearInterval(timerRef.current);
      return undefined;
    }

    const intervalMs = Math.max(10000, (pollConfig.interval_seconds || 60) * 1000);
    timerRef.current = setInterval(() => {
      fetchLiveQuotes();
    }, intervalMs);

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [pollConfig.enabled, pollConfig.interval_seconds, fetchLiveQuotes]);

  // Fetch live instruments catalog from backend API
  useEffect(() => {
    async function loadCatalog() {
      try {
        const res = await fetch("/api/forecasting/instruments");
        if (res.ok) {
          const body = await res.json();
          if (body.instruments && Array.isArray(body.instruments)) {
            setInstrumentsCatalog(body.instruments);
          }
        }
      } catch {
        // Fallback to static catalog
      }
    }
    loadCatalog();
  }, []);

  const currentConfig = instrumentsCatalog.find((c) => c.id === selectedInstrument) || INSTRUMENT_CONFIGS[selectedInstrument] || INSTRUMENT_CONFIGS.NIFTY;

  const value = {
    selectedInstrument,
    setSelectedInstrument,
    selectedModel,
    setSelectedModel,
    selectedStrategyMode,
    setSelectedStrategyMode,
    instrumentConfig: currentConfig,
    supportedInstruments: instrumentsCatalog,
    spots,
    quotes,
    commodities,
    globalIndices,
    sectoralIndices,
    liveData: data,
    crossMarketSnapshot: data?.cross_market_snapshot || null,
    postCloseMode: data?.post_close_mode ?? false,
    isEquityOpen: data?.is_equity_open ?? false,
    isCommodityOpen: data?.is_commodity_open ?? false,
    postCloseAnalysis: data?.post_close_analysis || null,
    marketWarnings: data?.cross_market_snapshot?.warnings || [],
    retrievedAt: data?.retrieved_at || (quotes[0]?.retrieved_at) || null,
    pollConfig,
    isRefreshing,
    refreshNow,
    setPollInterval,
    togglePolling,
  };

  return <MarketDataContext.Provider value={value}>{children}</MarketDataContext.Provider>;
}

export function useMarketData() {
  return useContext(MarketDataContext);
}
