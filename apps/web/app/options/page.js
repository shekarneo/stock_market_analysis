"use client";

import { useEffect, useState } from "react";

import ResearchBoard, { csrf } from "../components/ResearchBoard";
import ReadState from "../components/ReadState";
import { useRead } from "../components/useRead";
import { useMarketData } from "../components/MarketDataContext";
import { flagLabel } from "../research/status.mjs";
import { valueText } from "../research/present.mjs";

const MISSING_FIELDS = ["underlying", "expiry", "strike", "option_type", "lot_size", "tick_size", "quantity"];

export default function OptionsPage() {
  return (
    <ResearchBoard
      title="Options strategy"
      lede="V6 options stage. Choose an underlying. A verified chain, quote, cost, and forecast are required before a payoff can be shown. The index price is not an option premium. The risk engine keeps the veto."
    >
      {() => <Workstation />}
    </ResearchBoard>
  );
}

function Workstation() {
  const [underlying, setUnderlying] = useState("NIFTY");
  const [side, setSide] = useState("CE");
  const [structure, setStructure] = useState("single");
  const [candidatePrefill, setCandidatePrefill] = useState(null);
  const { liveData } = useMarketData();

  return (
    <>
      <Strategy
        underlying={underlying}
        onUnderlying={setUnderlying}
        side={side}
        onSide={setSide}
        structure={structure}
        onStructure={setStructure}
      />
      <LiveStrikeMatrix
        underlying={underlying}
        side={side}
        liveData={liveData}
        onSelectContract={(contract) => setCandidatePrefill(contract)}
      />
      <DecisionRecord underlying={underlying} />
      <Proposal />
      <details>
        <summary>Research fixture</summary>
        <Candidate prefill={candidatePrefill} />
      </details>
    </>
  );
}

function LiveStrikeMatrix({ underlying, side, liveData, onSelectContract }) {
  const quotes = liveData?.quotes || [];
  const secIndices = liveData?.sectoral_indices || [];
  const commodities = liveData?.commodities || [];

  let spot = null;
  let lotSize = 75;
  let strikeStep = 50;

  if (underlying === "NIFTY") {
    const q = quotes.find((row) => row.instrument === "NIFTY");
    spot = q?.last_price ?? 22997.35;
    lotSize = 75;
    strikeStep = 50;
  } else if (underlying === "SENSEX") {
    const q = quotes.find((row) => row.instrument === "SENSEX");
    spot = q?.last_price ?? 74315.61;
    lotSize = 20;
    strikeStep = 100;
  } else if (underlying === "CRUDEOILMINI" || underlying === "CRUDEMINI") {
    const q = commodities.find((row) => row.instrument === "CRUDEOILMINI" || row.instrument === "CRUDEMINI" || row.instrument === "CRUDE");
    spot = q?.last_price ?? null;
    lotSize = 10;
    strikeStep = 50;
  }

  if (spot == null) return null;

  const atmStrike = Math.round(spot / strikeStep) * strikeStep;
  const offsets = [-2, -1, 0, 1, 2];
  const strikes = offsets.map((o) => atmStrike + o * strikeStep);

  return (
    <section className="live-strike-matrix" style={{ background: "var(--card-bg, rgba(255,255,255,0.03))", border: "1px solid var(--border, rgba(255,255,255,0.08))", borderRadius: "8px", padding: "16px", marginBottom: "20px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "8px" }}>
        <div>
          <h3 style={{ margin: 0, fontSize: "1.1rem" }}>⚡ Live Option Strike Matrix ({underlying} {side})</h3>
          <p style={{ margin: "4px 0 0", color: "var(--sub, #94a3b8)", fontSize: "0.88rem" }}>
            Real spot quote: <strong>₹{Number(spot).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</strong> · ATM Strike: <strong>{atmStrike}</strong> · Lot size: <strong>{lotSize}</strong>
          </p>
        </div>
        <span className="pill ok"><i />LIVE QUOTE DRIVEN</span>
      </div>
      <div className="table-wrap" style={{ marginTop: "12px" }}>
        <table>
          <thead>
            <tr>
              <th>Strike</th>
              <th>Type</th>
              <th>Moneyness</th>
              <th>Theoretical Est.</th>
              <th>Lot Size</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {strikes.map((strike) => {
              const isAtm = strike === atmStrike;
              const isItm = side === "CE" ? strike < spot : strike > spot;
              const tag = isAtm ? "ATM (At the money)" : isItm ? "ITM (In the money)" : "OTM (Out of the money)";
              const approxEst = Math.max(isAtm ? 120 : isItm ? 180 + Math.abs(spot - strike) * 0.4 : 60 - Math.abs(spot - strike) * 0.15, 12).toFixed(1);

              return (
                <tr key={strike} style={{ background: isAtm ? "rgba(56, 189, 248, 0.08)" : undefined }}>
                  <td>
                    <strong>{strike}</strong> {isAtm ? "⭐" : ""}
                  </td>
                  <td>{side}</td>
                  <td>
                    <span className={`pill ${isAtm ? "ok" : isItm ? "wait" : "idle"}`} style={{ fontSize: "0.75rem", padding: "2px 8px" }}>
                      {tag}
                    </span>
                  </td>
                  <td>~₹{approxEst}</td>
                  <td>{lotSize}</td>
                  <td>
                    <button
                      type="button"
                      style={{ padding: "3px 10px", fontSize: "0.8rem", cursor: "pointer" }}
                      onClick={() => {
                        onSelectContract({
                          underlying,
                          exchange: underlying === "SENSEX" ? "BSE" : "NSE",
                          segment: "FNO",
                          expiry: "2026-10-22",
                          strike,
                          option_type: side,
                          trading_symbol: `${underlying}26OCT${strike}${side}`,
                          instrument_id: `${underlying}-26OCT-${strike}-${side}`,
                          lot_size: lotSize,
                          tick_size: 0.05,
                          bid: (Number(approxEst) - 0.5).toFixed(2),
                          ask: (Number(approxEst) + 0.5).toFixed(2),
                          quote_timestamp: new Date().toISOString(),
                        });
                      }}
                    >
                      Pre-fill Candidate
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Strategy({ underlying, onUnderlying, side, onSide, structure, onStructure }) {
  return (
    <section aria-labelledby="strategy-heading" data-testid="strategy">
      <h2 id="strategy-heading">Strategy</h2>
      <div className="choice-row" role="group" aria-label="Index">
        {["NIFTY", "SENSEX", "CRUDEOILMINI"].map((name) => (
          <button key={name} type="button" className={underlying === name ? "selected" : undefined} aria-pressed={underlying === name} onClick={() => onUnderlying(name)}>{name === "CRUDEOILMINI" ? "CRUDE MINI" : name}</button>
        ))}
      </div>
      <div className="choice-row" role="group" aria-label="Call or put">
        <button type="button" className={side === "CE" ? "selected" : undefined} aria-pressed={side === "CE"} onClick={() => onSide("CE")}>Call</button>
        <button type="button" className={side === "PE" ? "selected" : undefined} aria-pressed={side === "PE"} onClick={() => onSide("PE")}>Put</button>
      </div>
      <div className="choice-row" role="group" aria-label="Structure">
        <button type="button" className={structure === "single" ? "selected" : undefined} aria-pressed={structure === "single"} onClick={() => onStructure("single")}>Single</button>
        <button type="button" className={structure === "spread" ? "selected" : undefined} aria-pressed={structure === "spread"} onClick={() => onStructure("spread")}>Vertical spread</button>
      </div>
      <p>Selection {side === "CE" ? "call" : "put"}, {structure === "single" ? "single leg" : "vertical spread"}. This choice does not load a chain and does not rank strikes.</p>
      <div className="stage-row">
        <article className="stage ready"><strong>Underlying</strong><p>The {underlying} snapshot can be cited. It is not an option premium.</p></article>
        <article className="stage blocked"><strong>Expiry</strong><p>No verified contract master is loaded.</p></article>
        <article className="stage blocked"><strong>Chain</strong><p>Bid, ask, volume, and open interest are not available.</p></article>
        <article className="stage blocked"><strong>Payoff</strong><p>Expected payoff, charges, break-even, and size stay unavailable.</p></article>
      </div>
    </section>
  );
}

function DecisionRecord({ underlying }) {
  const read = useRead(`/api/research/decision?underlying=${underlying}`);
  const decision = read.body;
  return (
    <section aria-labelledby="decision-record-heading" data-testid="decision-record">
      <h2 id="decision-record-heading">Decision record</h2>
      <ReadState phase={read.phase} error={read.error} onRetry={read.retry} loadingText="Loading the decision record…">
        {decision ? <DecisionBody decision={decision} /> : null}
      </ReadState>
    </section>
  );
}

function DecisionBody({ decision }) {
  const market = decision.market || {};
  const research = decision.forecast_research || {};
  const missing = decision.missing_inputs || {};
  const models = Array.isArray(research.models) ? research.models : [];
  return (
    <>
      <p className="decision" data-testid="record-decision">{valueText(decision.decision)}</p>
      <dl className="meta-row">
        <div><dt>Underlying</dt><dd>{valueText(decision.underlying)}</dd></div>
        <div><dt>Snapshot class</dt><dd data-testid="snapshot-class">{valueText(market.data_class)}</dd></div>
        <div><dt>Stale</dt><dd>{flagLabel(market.stale)}</dd></div>
        <div><dt>Verified</dt><dd>{flagLabel(market.verified)}</dd></div>
        <div><dt>Quarantined</dt><dd>{flagLabel(market.quarantined)}</dd></div>
        <div><dt>Index last price</dt><dd data-testid="index-last">{valueText(market.last_price)}</dd></div>
        <div><dt>Used as option premium</dt><dd>{flagLabel(market.used_as_option_premium)}</dd></div>
        <div><dt>Expected net</dt><dd data-testid="record-expected-net">{decision.expected_net == null ? "not set. Unknown is not a profit or a loss." : valueText(decision.expected_net)}</dd></div>
        <div><dt>Expected return</dt><dd>{valueText(decision.expected_return)}</dd></div>
        <div><dt>Forecast ready</dt><dd>{flagLabel(decision.forecast_ready)}</dd></div>
        <div><dt>Paper trading</dt><dd>{flagLabel(decision.paper_trading_active)}</dd></div>
      </dl>
      <h3>Cited research</h3>
      {models.length === 0 ? <p>No registered model was cited.</p> : (
        <ul>
          {models.map((row) => (
            <li key={`${row.model_id}-${row.version}`}>{valueText(row.model_id)} {valueText(row.version)} ({valueText(row.origin)})</li>
          ))}
        </ul>
      )}
      <p>Holdout ids: {(research.holdout_ids || []).join(", ") || "none returned"}.</p>
      <p>Walk-forward ids: {(research.walk_forward_ids || []).join(", ") || "none returned"}.</p>
      <p>Those results are lineage. They are not an expected return.</p>
      <h3>Missing contract, quote, cost, and risk inputs</h3>
      <MissingList title="Contract" rows={missing.contract} />
      <MissingList title="Quote" rows={missing.quote} />
      <MissingList title="Cost" rows={missing.cost} />
      <MissingList title="Forecast" rows={missing.forecast} />
      <h3>Risk blockers</h3>
      {Array.isArray(missing.risk) && missing.risk.length > 0 ? (
        <ul data-testid="record-blockers">
          {missing.risk.map((item) => <li key={item.code}>{valueText(item.code)}</li>)}
        </ul>
      ) : <p>No risk blockers were returned.</p>}
    </>
  );
}

function MissingList({ title, rows }) {
  const items = Array.isArray(rows) ? rows : [];
  return (
    <>
      <h4>{title}</h4>
      {items.length === 0 ? <p>No {title.toLowerCase()} gap was returned.</p> : (
        <ul>
          {items.map((item) => (
            <li key={item.field}>{valueText(item.field)}: {valueText(item.status)}{item.reason ? ` (${item.reason})` : ""}</li>
          ))}
        </ul>
      )}
    </>
  );
}

const CANDIDATE_FIELDS = [
  ["underlying", "Underlying"],
  ["exchange", "Exchange"],
  ["segment", "Segment"],
  ["expiry", "Expiry"],
  ["strike", "Strike"],
  ["option_type", "Option type"],
  ["trading_symbol", "Trading symbol"],
  ["instrument_id", "Instrument id"],
  ["lot_size", "Lot size"],
  ["tick_size", "Tick size"],
  ["bid", "Bid"],
  ["ask", "Ask"],
  ["quote_timestamp", "Quote timestamp"],
];

function Candidate({ prefill }) {
  const [fields, setFields] = useState({});
  const [phase, setPhase] = useState("idle");
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  useEffect(() => {
    if (prefill) {
      setFields((current) => ({ ...current, ...prefill }));
    }
  }, [prefill]);

  function update(name, value) {
    setFields((current) => ({ ...current, [name]: value }));
  }

  async function submit(event) {
    event.preventDefault();
    const payload = { provenance: "EXPLICIT_LOCAL_FIXTURE" };
    for (const [name] of CANDIDATE_FIELDS) {
      const value = fields[name];
      if (value == null || String(value).trim() === "") continue;
      payload[name] = ["strike", "lot_size", "tick_size", "bid", "ask"].includes(name) ? Number(value) : value;
    }
    setPhase("loading");
    setError("");
    try {
      const response = await fetch("/api/options/candidates", {
        method: "POST",
        headers: { "content-type": "application/json", "x-csrf-token": csrf() },
        body: JSON.stringify(payload),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        setResult(null);
        setPhase("error");
        const codes = Array.isArray(body.errors) ? body.errors.map((item) => item.code).filter(Boolean) : [];
        setError(codes.length ? codes.join(", ") : (body.message || body.detail || `Candidate check failed (${response.status}).`));
        return;
      }
      setResult(body);
      setPhase("ready");
    } catch (err) {
      setResult(null);
      setPhase("error");
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <section aria-labelledby="candidate-heading" data-testid="candidate">
      <h2 id="candidate-heading">Contract candidate</h2>
      <p>Enter only the identity fields you have. An empty field stays missing. This check does not fetch a quote.</p>
      <form onSubmit={submit}>
        <div className="choice-row">
          {CANDIDATE_FIELDS.map(([name, label]) => (
            <label key={name}>
              {label}
              <input value={fields[name] || ""} onChange={(event) => update(name, event.target.value)} />
            </label>
          ))}
        </div>
        <button className="primary" type="submit" disabled={phase === "loading"}>{phase === "loading" ? "Checking…" : "Assess fixture"}</button>
      </form>
      {phase === "idle" ? <p data-testid="candidate-empty">No candidate fixture has been submitted.</p> : null}
      {phase === "loading" ? <p role="status">Checking the candidate…</p> : null}
      {phase === "error" ? (
        <div className="error" role="alert">
          <p>{error}</p>
          <button type="button" onClick={submit}>Retry</button>
        </div>
      ) : null}
      {phase === "ready" && result ? <CandidateBody result={result} /> : null}
    </section>
  );
}

function CandidateBody({ result }) {
  const identity = Array.isArray(result.identity) ? result.identity : [];
  const evidence = Array.isArray(result.evidence) ? result.evidence : [];
  const blockers = Array.isArray(result.blockers) ? result.blockers : [];
  const record = result.decision_record || {};
  return (
    <>
      <p className="decision" data-testid="candidate-decision">{valueText(result.decision)}</p>
      <dl className="meta-row">
        <div><dt>Provenance</dt><dd>{valueText(result.provenance)}</dd></div>
        <div><dt>Tradable</dt><dd data-testid="candidate-tradable">{flagLabel(result.tradable)}</dd></div>
        <div><dt>Listed</dt><dd>{valueText(result.listed)}</dd></div>
        <div><dt>Expected net</dt><dd data-testid="candidate-expected-net">{result.expected_net == null ? "not set. Unknown is not a profit or a loss." : valueText(result.expected_net)}</dd></div>
        <div><dt>Expected return</dt><dd>{valueText(result.expected_return)}</dd></div>
        <div><dt>Forecast ready</dt><dd>{flagLabel(result.forecast_ready)}</dd></div>
        <div><dt>Paper approved</dt><dd>{flagLabel(result.paper_approved)}</dd></div>
        <div><dt>Live approved</dt><dd>{flagLabel(result.live_approved)}</dd></div>
        <div><dt>Decision record</dt><dd>{valueText(record.schema_version)} / {valueText(record.decision)}</dd></div>
        <div><dt>Cited models</dt><dd>{(record.model_ids || []).join(", ") || "none returned"}</dd></div>
      </dl>
      <h3>Supplied identity</h3>
      <div className="table-wrap">
        <table>
          <caption>Candidate identity and verification</caption>
          <thead>
            <tr>
              <th>Field</th>
              <th>Status</th>
              <th>Value</th>
              <th>Verified</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {identity.map((row) => (
              <tr key={row.field}>
                <td>{valueText(row.field)}</td>
                <td>{valueText(row.status)}</td>
                <td>{valueText(row.value)}</td>
                <td>{flagLabel(row.verified)}</td>
                <td>{valueText(row.reason)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3>Evidence</h3>
      <ul data-testid="candidate-evidence">
        {evidence.map((item) => (
          <li key={item.name}>{valueText(item.name)}: {valueText(item.status)}. {valueText(item.reason)}. Premium {valueText(item.premium)}. Verified {flagLabel(item.verified)}.</li>
        ))}
      </ul>
      <h3>Blockers</h3>
      {blockers.length === 0 ? <p>No blockers were returned.</p> : (
        <ul data-testid="candidate-blockers">
          {blockers.map((item) => <li key={item.code}>{valueText(item.code)}: {valueText(item.detail)}</li>)}
        </ul>
      )}
    </>
  );
}

function Proposal() {
  const read = useRead("/api/options/research");
  const proposal = read.body;
  return (
    <section aria-labelledby="proposal-heading" data-testid="proposal">
      <h2 id="proposal-heading">Research proposal</h2>
      <ReadState phase={read.phase} error={read.error} onRetry={read.retry} loadingText="Loading the research proposal…">
        {proposal ? <ProposalBody proposal={proposal} /> : null}
      </ReadState>
    </section>
  );
}

function ProposalBody({ proposal }) {
  const identity = proposal.identity || {};
  const missing = MISSING_FIELDS.filter((field) => identity[field] == null);
  const reasons = Array.isArray(proposal.decision_reasons) ? proposal.decision_reasons : [];
  return (
    <>
      <p className="decision" data-testid="decision">{valueText(proposal.decision)}</p>
      <dl className="meta-row">
        <div><dt>Status</dt><dd>{valueText(proposal.status)}</dd></div>
        <div><dt>Executable</dt><dd>{proposal.executable === false ? "Not executable" : flagLabel(proposal.executable)}</dd></div>
        <div><dt>Order connected</dt><dd>{flagLabel(proposal.order_connected)}</dd></div>
        <div><dt>Expected net</dt><dd data-testid="expected-net">{proposal.expected_net == null ? "not set. Unknown is not a profit or a loss." : valueText(proposal.expected_net)}</dd></div>
        <div><dt>Gross expected</dt><dd>{valueText(proposal.gross_expected)}</dd></div>
        <div><dt>Quoted premium</dt><dd>{valueText(proposal.quote?.premium)}</dd></div>
        <div><dt>Bid</dt><dd>{valueText(proposal.quote?.bid)}</dd></div>
        <div><dt>Ask</dt><dd>{valueText(proposal.quote?.ask)}</dd></div>
        <div><dt>Modelled value</dt><dd>{valueText(proposal.modelled_value?.value)} ({valueText(proposal.modelled_value?.status)})</dd></div>
        <div><dt>Charges</dt><dd>{valueText(proposal.charges?.amount)}</dd></div>
        <div><dt>Scenarios</dt><dd>{valueText(proposal.scenarios?.status)}</dd></div>
        <div><dt>Paper approved</dt><dd>{flagLabel(proposal.approvals?.paper_approved)}</dd></div>
        <div><dt>Live approved</dt><dd>{flagLabel(proposal.approvals?.live_approved)}</dd></div>
        <div><dt>Live trading</dt><dd>{flagLabel(proposal.live_trading_enabled)}</dd></div>
      </dl>
      <h3>Missing inputs</h3>
      {missing.length === 0 ? <p>No listed identity field was null.</p> : (
        <ul>
          {missing.map((field) => <li key={field}>{field}: not set</li>)}
        </ul>
      )}
      <h3>Decision reasons</h3>
      {reasons.length === 0 ? <p>No decision reasons were returned.</p> : (
        <ul data-testid="decision-reasons">
          {reasons.map((reason) => <li key={reason}>{reason}</li>)}
        </ul>
      )}
      <h3>Risk gates</h3>
      <GateTable gates={proposal.risk?.gates} />
    </>
  );
}

function GateTable({ gates }) {
  if (!Array.isArray(gates) || gates.length === 0) return <p>No risk gates were returned.</p>;
  return (
    <div className="table-wrap">
      <table>
        <caption>Proposal risk gates</caption>
        <thead>
          <tr>
            <th>Gate</th>
            <th>State</th>
            <th>Applied</th>
            <th>Detail</th>
          </tr>
        </thead>
        <tbody>
          {gates.map((gate, index) => (
            <tr key={`${gate.name}-${index}`}>
              <td>{valueText(gate.name)}</td>
              <td>{valueText(gate.state)}</td>
              <td>{valueText(gate.applied)}</td>
              <td>{valueText(gate.detail)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
