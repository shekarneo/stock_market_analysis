"use client";

export default function ReadState({ phase, error, onRetry, empty = false, emptyText, loadingText, children }) {
  if (phase === "idle") return null;
  if (phase === "loading") {
    return <p role="status">{loadingText || "Loading…"}</p>;
  }
  if (phase === "error") {
    return (
      <div className="error" role="alert">
        <p>{error || "The request failed."}</p>
        {onRetry ? <button type="button" onClick={onRetry}>Retry</button> : null}
      </div>
    );
  }
  if (empty) return <p>{emptyText || "Nothing was returned."}</p>;
  return children;
}
