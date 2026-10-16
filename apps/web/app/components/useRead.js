"use client";

import { useCallback, useEffect, useState } from "react";

export function useRead(url, { enabled = true } = {}) {
  const [phase, setPhase] = useState(enabled ? "loading" : "idle");
  const [body, setBody] = useState(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  const retry = useCallback(() => {
    setAttempt((value) => value + 1);
  }, []);

  useEffect(() => {
    if (!enabled) return undefined;
    const controller = new AbortController();
    setPhase("loading");
    setError("");
    fetch(url, { signal: controller.signal })
      .then(async (response) => {
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          setBody(null);
          setPhase("error");
          setError(payload.message || payload.detail || `Request failed (${response.status}).`);
          return;
        }
        setBody(payload);
        setPhase("ready");
      })
      .catch((err) => {
        if (err.name === "AbortError") return;
        setBody(null);
        setPhase("error");
        setError(err instanceof Error ? err.message : String(err));
      });
    return () => controller.abort();
  }, [url, enabled, attempt]);

  return { phase, body, error, retry };
}
