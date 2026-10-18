"use client";

import { useCallback, useEffect, useState } from "react";
import { csrfToken } from "./session";

export default function NewsSourcesManager({ onNewsUpdated }) {
  const [sources, setSources] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busyId, setBusyId] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  // Add feed form state
  const [showAddForm, setShowAddForm] = useState(false);
  const [newName, setNewName] = useState("");
  const [newUrl, setNewUrl] = useState("");
  const [addBusy, setAddBusy] = useState(false);

  const loadSources = useCallback(async () => {
    try {
      const res = await fetch("/api/news/sources");
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.message || `Failed to load news sources (${res.status})`);
      }
      const data = await res.json();
      setSources(data.sources || []);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSources();
  }, [loadSources]);

  async function handleToggle(source) {
    setBusyId(source.id);
    setError("");
    setNotice("");
    try {
      const res = await fetch(`/api/news/sources/${encodeURIComponent(source.id)}`, {
        method: "PATCH",
        headers: {
          "content-type": "application/json",
          "x-csrf-token": csrfToken(),
        },
        body: JSON.stringify({ enabled: !source.enabled }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.message || "Failed to update source.");
      setNotice(`"${source.name}" is now ${!source.enabled ? "enabled" : "disabled"}.`);
      await loadSources();
      if (onNewsUpdated) onNewsUpdated();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  async function handleAdd(e) {
    e.preventDefault();
    setError("");
    setNotice("");
    if (!newName.trim() || !newUrl.trim()) {
      setError("Please provide both a feed name and a valid web URL.");
      return;
    }
    setAddBusy(true);
    try {
      const res = await fetch("/api/news/sources", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-csrf-token": csrfToken(),
        },
        body: JSON.stringify({
          name: newName.trim(),
          url: newUrl.trim(),
          enabled: true,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.message || "Failed to add news feed.");
      setNotice(`Added news feed "${data.name}".`);
      setNewName("");
      setNewUrl("");
      setShowAddForm(false);
      await loadSources();
      if (onNewsUpdated) onNewsUpdated();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setAddBusy(false);
    }
  }

  async function handleDelete(source) {
    if (!window.confirm(`Are you sure you want to remove the news feed "${source.name}"?`)) return;
    setBusyId(source.id);
    setError("");
    setNotice("");
    try {
      const res = await fetch(`/api/news/sources/${encodeURIComponent(source.id)}`, {
        method: "DELETE",
        headers: {
          "x-csrf-token": csrfToken(),
        },
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.message || "Failed to delete news feed.");
      setNotice(`Removed news feed "${source.name}".`);
      await loadSources();
      if (onNewsUpdated) onNewsUpdated();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  async function handleReset() {
    if (!window.confirm("Reset all news sources back to the 5 default feeds? Any custom links will be removed and default feeds will be re-enabled.")) return;
    setLoading(true);
    setError("");
    setNotice("");
    try {
      const res = await fetch("/api/news/sources/reset", {
        method: "POST",
        headers: {
          "x-csrf-token": csrfToken(),
        },
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.message || "Failed to reset news feeds.");
      setNotice("News sources reset to original defaults.");
      await loadSources();
      if (onNewsUpdated) onNewsUpdated();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function handleRefreshNews() {
    setRefreshing(true);
    setError("");
    setNotice("");
    try {
      const res = await fetch("/api/news/refresh", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-csrf-token": csrfToken(),
        },
        body: JSON.stringify({ confirm: true }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.message || "Failed to fetch news from feeds.");
      setNotice(`News updated: fetched ${data.count || 0} articles across active feeds.`);
      await loadSources();
      if (onNewsUpdated) onNewsUpdated();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRefreshing(false);
    }
  }

  const activeCount = sources.filter((s) => s.enabled).length;

  return (
    <div
      style={{
        background: "var(--card-subtle, #131c31)",
        border: "1px solid var(--line)",
        borderRadius: "12px",
        padding: "18px 20px",
        marginBottom: "20px",
      }}
    >
      {/* Header & Controls Toolbar */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "12px", marginBottom: "16px" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <h3 style={{ margin: 0, fontSize: "1.1rem", fontWeight: 700, color: "var(--ink, #f8fafc)" }}>
              📰 News Agent Feed Configuration
            </h3>
            <span
              style={{
                fontSize: "0.72rem",
                fontWeight: 700,
                padding: "2px 8px",
                borderRadius: "999px",
                background: activeCount > 0 ? "rgba(34, 197, 94, 0.15)" : "rgba(239, 68, 68, 0.15)",
                color: activeCount > 0 ? "#4ade80" : "#f87171",
                border: `1px solid ${activeCount > 0 ? "rgba(34, 197, 94, 0.3)" : "rgba(239, 68, 68, 0.3)"}`,
              }}
            >
              {activeCount} of {sources.length} Active
            </span>
          </div>
          <p style={{ margin: "4px 0 0", fontSize: "0.82rem", color: "var(--muted, #94a3b8)" }}>
            Configure web pages and RSS feeds fetched by the News &amp; Event Analyst agent. Disable, add, or remove links at will.
          </p>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
          <button
            type="button"
            onClick={() => setShowAddForm((prev) => !prev)}
            style={{
              background: showAddForm ? "rgba(255,255,255,0.08)" : "var(--card, #0f172a)",
              color: "var(--ink, #f8fafc)",
              border: "1px solid var(--line)",
              borderRadius: "6px",
              padding: "6px 12px",
              fontSize: "0.78rem",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            {showAddForm ? "✕ Cancel Add" : "+ Add Feed Link"}
          </button>

          <button
            type="button"
            onClick={handleReset}
            style={{
              background: "transparent",
              color: "var(--muted, #94a3b8)",
              border: "1px solid var(--line)",
              borderRadius: "6px",
              padding: "6px 12px",
              fontSize: "0.78rem",
              fontWeight: 500,
              cursor: "pointer",
            }}
            title="Restore the 5 original default Indian market news feeds"
          >
            ↺ Reset Defaults
          </button>

          <button
            type="button"
            onClick={handleRefreshNews}
            disabled={refreshing}
            style={{
              background: "var(--card, #0f172a)",
              color: "#38bdf8",
              border: "1px solid rgba(56, 189, 248, 0.3)",
              borderRadius: "6px",
              padding: "6px 12px",
              fontSize: "0.78rem",
              fontWeight: 600,
              cursor: refreshing ? "not-allowed" : "pointer",
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
            }}
          >
            {refreshing ? "↻ Fetching Active Feeds…" : "↻ Fetch Live Articles Now"}
          </button>
        </div>
      </div>

      {notice && (
        <div style={{ background: "rgba(34, 197, 94, 0.1)", border: "1px solid rgba(34, 197, 94, 0.25)", color: "#4ade80", padding: "8px 12px", borderRadius: "6px", fontSize: "0.82rem", marginBottom: "14px" }}>
          {notice}
        </div>
      )}

      {error && (
        <div style={{ background: "rgba(239, 68, 68, 0.1)", border: "1px solid rgba(239, 68, 68, 0.25)", color: "#f87171", padding: "8px 12px", borderRadius: "6px", fontSize: "0.82rem", marginBottom: "14px" }}>
          {error}
        </div>
      )}

      {/* Inline Add New Feed Form */}
      {showAddForm && (
        <form
          onSubmit={handleAdd}
          style={{
            background: "rgba(255, 255, 255, 0.03)",
            border: "1px dashed rgba(255, 255, 255, 0.15)",
            borderRadius: "8px",
            padding: "14px",
            marginBottom: "16px",
            display: "grid",
            gridTemplateColumns: "minmax(180px, 1fr) minmax(280px, 2fr) auto",
            gap: "10px",
            alignItems: "flex-end",
          }}
        >
          <div>
            <label style={{ display: "block", fontSize: "0.74rem", fontWeight: 700, color: "var(--muted)", marginBottom: "4px" }}>
              Feed / Publisher Name:
            </label>
            <input
              type="text"
              placeholder="e.g. NDTV Profit, Reuters India"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              style={{
                width: "100%",
                background: "#0f172a",
                color: "#f8fafc",
                border: "1px solid var(--line)",
                padding: "6px 10px",
                borderRadius: "6px",
                fontSize: "0.82rem",
                outline: "none",
              }}
            />
          </div>

          <div>
            <label style={{ display: "block", fontSize: "0.74rem", fontWeight: 700, color: "var(--muted)", marginBottom: "4px" }}>
              Web Page / RSS Feed URL:
            </label>
            <input
              type="url"
              placeholder="https://example.com/rss/markets.xml"
              value={newUrl}
              onChange={(e) => setNewUrl(e.target.value)}
              style={{
                width: "100%",
                background: "#0f172a",
                color: "#f8fafc",
                border: "1px solid var(--line)",
                padding: "6px 10px",
                borderRadius: "6px",
                fontSize: "0.82rem",
                outline: "none",
              }}
            />
          </div>

          <button
            type="submit"
            disabled={addBusy}
            style={{
              background: "#38bdf8",
              color: "#090d16",
              border: "none",
              borderRadius: "6px",
              padding: "7px 16px",
              fontSize: "0.82rem",
              fontWeight: 700,
              cursor: addBusy ? "not-allowed" : "pointer",
              whiteSpace: "nowrap",
            }}
          >
            {addBusy ? "Adding…" : "+ Add Link"}
          </button>
        </form>
      )}

      {/* Sources List */}
      {loading ? (
        <p style={{ color: "var(--muted)", fontSize: "0.85rem", margin: 0 }}>Loading news feeds…</p>
      ) : sources.length === 0 ? (
        <p style={{ color: "var(--muted)", fontSize: "0.85rem", margin: 0 }}>No news feeds configured. Click "Reset Defaults" to restore standard feeds.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          {sources.map((source) => {
            const isBusy = busyId === source.id;
            return (
              <div
                key={source.id}
                style={{
                  background: source.enabled ? "var(--card, #0f172a)" : "rgba(15, 23, 42, 0.4)",
                  border: `1px solid ${source.enabled ? "var(--line)" : "rgba(255, 255, 255, 0.04)"}`,
                  borderRadius: "8px",
                  padding: "10px 14px",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  flexWrap: "wrap",
                  gap: "10px",
                  opacity: source.enabled ? 1 : 0.65,
                  transition: "all 0.15s ease",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "10px", minWidth: "220px", flex: "1 1 auto" }}>
                  <span
                    style={{
                      width: "8px",
                      height: "8px",
                      borderRadius: "50%",
                      background: source.enabled ? "#22c55e" : "#64748b",
                      boxShadow: source.enabled ? "0 0 6px rgba(34, 197, 94, 0.6)" : "none",
                      flexShrink: 0,
                    }}
                  />
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                      <strong style={{ fontSize: "0.88rem", color: source.enabled ? "var(--ink, #f8fafc)" : "var(--muted)" }}>
                        {source.name}
                      </strong>
                      {source.is_default && (
                        <span style={{ fontSize: "0.65rem", padding: "1px 5px", borderRadius: "4px", background: "rgba(255, 255, 255, 0.06)", color: "var(--muted)", fontWeight: 600 }}>
                          DEFAULT
                        </span>
                      )}
                      {source.last_status === "READ" && source.last_count != null && (
                        <span style={{ fontSize: "0.7rem", color: "#4ade80", fontWeight: 600 }}>
                          ✓ {source.last_count} articles
                        </span>
                      )}
                      {source.last_status === "FAILED" && (
                        <span style={{ fontSize: "0.7rem", color: "#f87171", fontWeight: 600 }}>
                          ⚠ {source.last_error || "Failed"}
                        </span>
                      )}
                    </div>
                    <div style={{ fontSize: "0.74rem", color: "var(--muted)", marginTop: "2px", wordBreak: "break-all" }}>
                      <a href={source.url} target="_blank" rel="noreferrer" style={{ color: "#38bdf8", textDecoration: "none", opacity: 0.85 }}>
                        {source.url} ↗
                      </a>
                    </div>
                  </div>
                </div>

                {/* Actions: Enable / Disable Toggle + Remove Button */}
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <button
                    type="button"
                    onClick={() => handleToggle(source)}
                    disabled={isBusy}
                    style={{
                      background: source.enabled ? "rgba(34, 197, 94, 0.15)" : "rgba(255, 255, 255, 0.06)",
                      color: source.enabled ? "#4ade80" : "var(--muted)",
                      border: `1px solid ${source.enabled ? "rgba(34, 197, 94, 0.3)" : "rgba(255, 255, 255, 0.1)"}`,
                      borderRadius: "6px",
                      padding: "4px 10px",
                      fontSize: "0.75rem",
                      fontWeight: 650,
                      cursor: isBusy ? "not-allowed" : "pointer",
                    }}
                    title={source.enabled ? "Click to disable this feed" : "Click to enable this feed"}
                  >
                    {isBusy ? "Updating…" : source.enabled ? "✓ Enabled" : "○ Disabled"}
                  </button>

                  <button
                    type="button"
                    onClick={() => handleDelete(source)}
                    disabled={isBusy}
                    style={{
                      background: "transparent",
                      color: "#f87171",
                      border: "1px solid rgba(239, 68, 68, 0.2)",
                      borderRadius: "6px",
                      padding: "4px 8px",
                      fontSize: "0.74rem",
                      cursor: isBusy ? "not-allowed" : "pointer",
                      opacity: 0.8,
                    }}
                    title={`Delete "${source.name}"`}
                  >
                    🗑 Remove
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
