"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { csrfToken as csrf } from "./session";

const MarketDataContext = createContext({
  spots: {},
  quotes: [],
  commodities: [],
  globalIndices: [],
  sectoralIndices: [],
  retrievedAt: null,
  pollConfig: { enabled: true, interval_seconds: 15, status: "RUNNING" },
  isRefreshing: false,
  refreshNow: async () => {},
  setPollInterval: async () => {},
  togglePolling: async () => {},
});

export function MarketDataProvider({ children }) {
  const [data, setData] = useState(null);
  const [pollConfig, setPollConfig] = useState({ enabled: true, interval_seconds: 15, status: "RUNNING" });
  const [isRefreshing, setIsRefreshing] = useState(false);
  const timerRef = useRef(null);

  // Parse unified spot map across all instruments
  const spots = {};
  const quotes = data?.quotes || [];
  const commodities = data?.commodities || [];
  const globalIndices = data?.global_indices || [];
  const sectoralIndices = data?.sectoral_indices || [];

  for (const q of quotes) {
    if (q.instrument && q.last_price != null) {
      spots[q.instrument] = Number(q.last_price);
    }
  }

  for (const c of commodities) {
    if (c.instrument && c.last_price != null) {
      spots[c.instrument] = Number(c.last_price);
      if (c.instrument === "CRUDEMINI" && !spots["CRUDEOILMINI"]) {
        spots["CRUDEOILMINI"] = Number(c.last_price);
      }
      if (c.instrument === "CRUDEOILMINI" && !spots["CRUDEMINI"]) {
        spots["CRUDEMINI"] = Number(c.last_price);
      }
    }
  }

  // Mirror aliases between CRUDEOILMINI and CRUDEMINI
  if (spots["CRUDEOILMINI"] != null && spots["CRUDEMINI"] == null) {
    spots["CRUDEMINI"] = spots["CRUDEOILMINI"];
  } else if (spots["CRUDEMINI"] != null && spots["CRUDEOILMINI"] == null) {
    spots["CRUDEOILMINI"] = spots["CRUDEMINI"];
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

  const value = {
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
