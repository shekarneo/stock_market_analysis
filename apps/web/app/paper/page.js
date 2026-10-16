"use client";

import { useState } from "react";

import ResearchBoard from "../components/ResearchBoard";
import { flagLabel } from "../research/status.mjs";
import { intentIdProblem, valueText } from "../research/present.mjs";

export default function PaperPage() {
  return (
    <ResearchBoard
      title="Paper trading"
      lede="Paper trading is disabled. Looking up an intent reads the stored audit. This page does not submit a simulation, retry an execution, or place an order."
    >
      {({ status }) => (
        <section aria-labelledby="execution-heading">
          <h2 id="execution-heading">Execution</h2>
          <p>Fills persisted {flagLabel(status.fills_persisted)}. Broker called {flagLabel(status.broker_called)}. Paper trading active {flagLabel(status.paper_trading_active)}. Execution is unavailable.</p>
          <Replay />
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
      <form onSubmit={load}>
        <label>
          Intent id
          <input value={intentId} onChange={(event) => setIntentId(event.target.value)} autoComplete="off" />
        </label>
        <button type="submit">Read stored decision</button>
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
    <div>
      <p>Intent {valueText(replay.intent_id || requestedId)}. State {replay.state == null ? "none stored" : valueText(replay.state)}.</p>
      <p data-testid="fill">Fill {valueText(replay.fill)}. Simulated fill {valueText(replay.simulated_fill)}. Execution is unavailable.</p>
      <p data-testid="replay-expected-net">Expected net {valueText(replay.expected_net)}. A null expected net is unknown.</p>
      <p>Snapshot conflict {valueText(replay.snapshot_conflict)}. Paper trading active {flagLabel(replay.paper_trading_active)}.</p>
      <h3>Missing fields</h3>
      {missing.length === 0 ? <p>No missing fields were listed.</p> : <ul>{missing.map((item) => <li key={item}>{item}</li>)}</ul>}
      <h3>Attempts</h3>
      {attempts.length === 0 ? <p>No attempts were returned.</p> : (
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
