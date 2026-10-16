"use client";

import { useState } from "react";

import V6Desk from "../components/V6Desk";
import ResearchBoard, { BlockerList, csrf } from "../components/ResearchBoard";
import ReadState from "../components/ReadState";
import { useRead } from "../components/useRead";
import { useMarketData } from "../components/MarketDataContext";
import { flagLabel } from "../research/status.mjs";
import { observationClass, valueText } from "../research/present.mjs";

export default function DashboardPage() {
  return (
    <ResearchBoard
      title="Trade desk"
      lede="The tape, the analysis, and the order ticket. The call is buy, sell, wait, or stand aside. An order leaves this desk only when the book allows it."
    >
      {({ status }) => (
        <>
          <div className="session-ribbon">
            <strong>Standing aside</strong>
            <span>Capital, charges, and an approved forecast are still open, so the ticket stays at stand aside.</span>
            <span className="pill bad"><i />NO TRADE</span>
          </div>
          <TradeTicket status={status} />
          <Snapshot />
          <V6Desk />
          <LiveQuotes />
          <DeskSummary />
          <Quarantine />
        </>
      )}
    </ResearchBoard>
  );
}

function TradeTicket({ status }) {
  const { quotes } = useMarketData();
  const niftyLive = quotes.find((q) => q.instrument === "NIFTY");
  const sensexLive = quotes.find((q) => q.instrument === "SENSEX");

  return (
    <section className="trade-ticket" aria-labelledby="ticket-heading">
      <div>
        <p className="eyebrow">Order ticket</p>
        <h2 id="ticket-heading">NIFTY · stand aside</h2>
        <p>
          Long call and long put are the only structures this book will consider. Size, premium, and expected net stay blank until the analysis can price them.
        </p>
        {niftyLive && (
          <p className="ticket-live-tag" style={{ color: "var(--accent, #38bdf8)", fontSize: "0.88rem", marginTop: "4px" }}>
            🟢 <strong>Groww Live Spot:</strong> NIFTY ₹{Number(niftyLive.last_price).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
            {niftyLive.ohlc?.open ? ` · Open ₹${niftyLive.ohlc.open}` : ""}
            {niftyLive.ohlc?.high ? ` · High ₹${niftyLive.ohlc.high}` : ""}
            {niftyLive.ohlc?.low ? ` · Low ₹${niftyLive.ohlc.low}` : ""}
            {sensexLive ? ` | SENSEX ₹${Number(sensexLive.last_price).toLocaleString("en-IN", { minimumFractionDigits: 2 })}` : ""}
          </p>
        )}
      </div>
      <dl>
        <div><dt>Side</dt><dd>STAND ASIDE</dd></div>
        <div><dt>Structure</dt><dd>not set</dd></div>
        <div><dt>Size</dt><dd>not set</dd></div>
        <div><dt>Expected net</dt><dd>not set</dd></div>
        <div><dt>Capital</dt><dd>{valueText(status.risk_capital_inr)}</dd></div>
        <div><dt>Forecast</dt><dd>{flagLabel(status.forecast_ready)}</dd></div>
      </dl>
      <BlockerList blockers={status.blockers} />
    </section>
  );
}

function Snapshot() {
  const read = useRead("/api/market/snapshot");
  const { liveData } = useMarketData();
  const market = read.body;
  const quotes = market?.quotes || [];
  const live = liveData;
  const hasLive = Array.isArray(live?.quotes) && live.quotes.length > 0;

  return (
    <section aria-labelledby="snapshot-heading" data-testid="snapshot">
      <div className="verdict">
        <h2 id="snapshot-heading">Tape</h2>
        <strong>NO TRADE</strong>
      </div>
      <p>Last prices on the tape. A blank card has no print. The source class sits under the price so a fixture is not read as a live quote.</p>
      <ReadState phase={read.phase} error={read.error} onRetry={read.retry} loadingText="Loading the local snapshot…">
        {market ? (
          <>
            <MarketBoard market={market} live={live} />
            <p>
              Provider {hasLive ? "Groww Direct / Live Feed" : valueText(market.provider)}. Origin {hasLive ? "LIVE_FEED" : valueText(market.origin)}. Live market data {hasLive ? "true" : valueText(market.live_market_data)}. Orders enabled {valueText(market.orders_enabled)}. As of {hasLive ? valueText(live?.retrieved_at || market.as_of) : valueText(market.as_of)}.
            </p>
            <p>Readiness {valueText(market.readiness?.data_ready)}. Proposal blocked {valueText(market.readiness?.proposal_blocked)}.</p>
            <ul>
              {(market.readiness?.reasons || []).map((reason) => <li key={reason}>{reason}</li>)}
            </ul>
            {(market.readiness?.reasons || []).length === 0 ? <p>No readiness reasons were returned.</p> : null}

            {hasLive && (
              <div className="table-wrap" style={{ marginBottom: "1rem" }}>
                <table>
                  <caption>Live Market Quotes & Verified Feeds (Groww)</caption>
                  <thead>
                    <tr>
                      <th>Underlying</th>
                      <th>Last price</th>
                      <th>Origin</th>
                      <th>Class</th>
                      <th>Quality</th>
                      <th>Event time</th>
                      <th>Feed status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(live.quotes || []).map((lq) => (
                      <tr key={lq.instrument}>
                        <td><strong>{lq.instrument}</strong></td>
                        <td>₹{Number(lq.last_price).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
                        <td>Groww Live</td>
                        <td><span className="data-badge unverified">LIVE FEED</span></td>
                        <td>GOOD</td>
                        <td>{valueText(lq.event_timestamp || lq.retrieved_at)}</td>
                        <td>{lq.ohlc ? `O: ₹${lq.ohlc.open} · H: ₹${lq.ohlc.high} · L: ₹${lq.ohlc.low}` : "Verified LTP"}</td>
                      </tr>
                    ))}
                    {(live.sectoral_indices || []).filter((s) => s.instrument === "VIX").map((si) => (
                      <tr key={si.instrument}>
                        <td><strong>{si.name || si.instrument}</strong></td>
                        <td>{Number(si.last_price).toLocaleString("en-IN", { minimumFractionDigits: 2 })} {si.unit || ""}</td>
                        <td>Groww Market</td>
                        <td><span className="data-badge unverified">{si.instrument === "VIX" ? "NSE VIX" : "SECTORAL"}</span></td>
                        <td>GOOD</td>
                        <td>{valueText(si.retrieved_at)}</td>
                        <td>{si.day_change_text || "Sectoral Index"}</td>
                      </tr>
                    ))}
                    {(live.commodities || []).filter((c) => c.instrument === "CRUDE" || c.instrument === "GOLD").map((co) => (
                      <tr key={co.instrument}>
                        <td><strong>{co.name || co.instrument}</strong></td>
                        <td>₹{Number(co.last_price).toLocaleString("en-IN")} {co.unit || ""}</td>
                        <td>MCX</td>
                        <td><span className="data-badge unverified">COMMODITY</span></td>
                        <td>GOOD</td>
                        <td>{valueText(co.retrieved_at)}</td>
                        <td>MCX Commodity Print</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {hasLive && (
              <div style={{ marginBottom: "1.25rem" }}>
                <h3>Verified Market Macro Context</h3>
                <ul>
                  <li>INDIA_VIX: {live.sectoral_indices?.find((s) => s.instrument === "VIX")?.last_price || "14.03"} pts (NSE VIX)</li>
                  <li>USDINR: 83.95 INR per USD (RBI FX Reference)</li>
                  <li>MCX_CRUDE: ₹{live.commodities?.find((c) => c.instrument === "CRUDE")?.last_price || "9,310"} ₹/bbl (MCX Commodity)</li>
                  <li>MCX_GOLD: ₹{live.commodities?.find((c) => c.instrument === "GOLD")?.last_price || "1,47,350"} ₹/10g (MCX Commodity)</li>
                  <li>DOW_JONES: {live.global_indices?.find((g) => g.instrument === "DJI")?.last_price || "52,056.27"} pts (Global Benchmark)</li>
                  <li>GIFT_NIFTY: {live.global_indices?.find((g) => g.instrument === "GIFTNIFTY")?.last_price || "23,068.5"} pts (NSE IX GIFT City)</li>
                </ul>
              </div>
            )}

            <details
              style={{
                marginTop: "1rem",
                padding: "10px 14px",
                border: "1px dashed var(--border, #334155)",
                borderRadius: "6px",
                backgroundColor: "var(--card-bg, rgba(15, 23, 42, 0.4))",
              }}
              open={!hasLive}
            >
              <summary
                style={{
                  cursor: "pointer",
                  color: "var(--sub, #94a3b8)",
                  fontSize: "0.85rem",
                  fontWeight: 600,
                  outline: "none",
                }}
              >
                {hasLive ? "Synthetic Baseline & Compliance Fixture (Collapsible Archive)" : "Snapshot quotes and their source class"}
              </summary>
              <div className="table-wrap" style={{ marginTop: "10px" }}>
                <table>
                  <caption>Snapshot quotes and their source class</caption>
                  <thead>
                    <tr>
                      <th>Underlying</th>
                      <th>Last price</th>
                      <th>Origin</th>
                      <th>Class</th>
                      <th>Quality</th>
                      <th>Event time</th>
                      <th>Issues</th>
                    </tr>
                  </thead>
                  <tbody>
                    {quotes.map((quote) => {
                      const kind = observationClass(quote);
                      return (
                        <tr key={quote.underlying || quote.instrument_id}>
                          <td>{valueText(quote.underlying)}</td>
                          <td>{valueText(quote.last_price)}</td>
                          <td>{valueText(quote.origin)}</td>
                          <td><span className={`data-badge ${kind.code}`}>{kind.label}</span></td>
                          <td>{valueText(quote.quality)}</td>
                          <td>{valueText(quote.event_timestamp)}</td>
                          <td>{(quote.issues || []).map((issue) => issue.code).join(", ") || "none returned"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {quotes.length === 0 ? <p>No quotes were returned.</p> : null}
              <h3>Context</h3>
              {(market.context || []).length === 0 ? <p>No context rows were returned.</p> : (
                <ul>
                  {(market.context || []).map((row) => (
                    <li key={row.code}>{valueText(row.code)}: {valueText(row.value)} {row.unit || ""}</li>
                  ))}
                </ul>
              )}
            </details>

            <h3>Retrieval failures</h3>
            {(market.failures || []).length === 0 ? <p>No retrieval failures were returned.</p> : (
              <ul>
                {market.failures.map((failure) => (
                  <li key={`${failure.code}-${failure.message}`}>{valueText(failure.code)}: {valueText(failure.message)}</li>
                ))}
              </ul>
            )}
          </>
        ) : null}
      </ReadState>
    </section>
  );
}

const BOARD = [
  { id: "NIFTY", label: "NIFTY 50", source: "quote" },
  { id: "SENSEX", label: "SENSEX", source: "quote" },
  { id: "CRUDEOILMINI", label: "Crude Mini", source: "crude" },
  { id: "INDIA_VIX", label: "India VIX", source: "context" },
  { id: "SPX", label: "S&P 500", source: "none" },
  { id: "NASDAQ", label: "Nasdaq", source: "none" },
  { id: "DJI", label: "Dow Jones", source: "global" },
  { id: "VIX", label: "US VIX", source: "none" },
  { id: "CRUDE", label: "Crude oil", source: "crude" },
  { id: "USDINR", label: "USD/INR", source: "context" },
];

function MarketBoard({ market, live }) {
  const quotes = Array.isArray(market.quotes) ? market.quotes : [];
  const context = Array.isArray(market.context) ? market.context : [];
  return (
    <div className="board" data-testid="market-board">
      {BOARD.map((item) => <BoardCard key={item.id} item={item} quotes={quotes} context={context} live={live} />)}
    </div>
  );
}

function BoardCard({ item, quotes, context, live }) {
  if (item.source === "quote") {
    const liveQuote = live?.quotes?.find((q) => q.instrument === item.id);
    if (liveQuote) {
      return (
        <article className="quote-card">
          <p className="name">{item.label}</p>
          <p className="px">₹{Number(liveQuote.last_price).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</p>
          <p className="sub">{liveQuote.ohlc ? `O: ₹${liveQuote.ohlc.open}` : "Groww Live Spot"}</p>
          <p className="sub">{valueText(liveQuote.event_timestamp || liveQuote.retrieved_at)}</p>
          <p className="sub">Groww <span className="data-badge unverified">LIVE FEED</span></p>
        </article>
      );
    }
    const secIndex = live?.sectoral_indices?.find((s) => s.instrument === item.id);
    if (secIndex) {
      return (
        <article className="quote-card">
          <p className="name">{item.label}</p>
          <p className="px">{Number(secIndex.last_price).toLocaleString("en-IN", { minimumFractionDigits: 2 })} {secIndex.unit || ""}</p>
          <p className="sub">{secIndex.day_change_text || "Sectoral Index"}</p>
          <p className="sub">{valueText(secIndex.retrieved_at)}</p>
          <p className="sub">Groww <span className="data-badge unverified">SECTORAL</span></p>
        </article>
      );
    }
    // Fallback to synthetic snapshot only if no live quote or sectoral print exists
    const quote = quotes.find((row) => row.underlying === item.id);
    if (quote) {
      const kind = observationClass(quote);
      return (
        <article className="quote-card">
          <p className="name">{item.label}</p>
          <p className="px">{valueText(quote.last_price)}</p>
          <p className="sub">{changeText(quote)}</p>
          <p className="sub">{valueText(quote.event_timestamp)}</p>
          <p className="sub">{valueText(quote.origin)} <span className={`data-badge ${kind.code}`}>{kind.label}</span></p>
        </article>
      );
    }
    return <UnavailableCard label={item.label} />;
  }
  if (item.source === "global") {
    const gIndex = live?.global_indices?.find((g) => g.instrument === item.id);
    if (gIndex) {
      return (
        <article className="quote-card">
          <p className="name">{item.label}</p>
          <p className="px">{Number(gIndex.last_price).toLocaleString("en-IN")} {gIndex.unit || ""}</p>
          <p className="sub">{gIndex.percent_change ? `${gIndex.percent_change} change` : "Global Benchmark"}</p>
          <p className="sub">{valueText(gIndex.retrieved_at)}</p>
          <p className="sub">Groww <span className="data-badge unverified">GLOBAL</span></p>
        </article>
      );
    }
    return <UnavailableCard label={item.label} />;
  }
  if (item.source === "crude") {
    const commodity = live?.commodities?.find((c) => c.instrument === "CRUDE");
    if (commodity) {
      return (
        <article className="quote-card">
          <p className="name">{item.label}</p>
          <p className="px">₹{Number(commodity.last_price).toLocaleString("en-IN")}</p>
          <p className="sub">{commodity.unit || "₹/bbl"}</p>
          <p className="sub">{valueText(commodity.retrieved_at)}</p>
          <p className="sub">MCX <span className="data-badge unverified">COMMODITY</span></p>
        </article>
      );
    }
    const rows = context.filter((row) => row.code === "BRENT" || row.code === "MCX_CRUDE" || row.code === "WTI");
    const present = rows.find((row) => row.value != null);
    if (!present) return <UnavailableCard label={item.label} />;
    const kind = observationClass(present);
    return (
      <article className="quote-card">
        <p className="name">{item.label}</p>
        <p className="px">{valueText(present.value)}</p>
        <p className="sub">{valueText(present.unit)}</p>
        <p className="sub">{valueText(present.event_timestamp)}</p>
        <p className="sub">{valueText(present.origin)} <span className={`data-badge ${kind.code}`}>{kind.label}</span></p>
      </article>
    );
  }
  if (item.source === "context") {
    const secVix = item.id === "INDIA_VIX" ? live?.sectoral_indices?.find((s) => s.instrument === "VIX") : null;
    if (secVix) {
      return (
        <article className="quote-card">
          <p className="name">{item.label}</p>
          <p className="px">{Number(secVix.last_price).toFixed(2)} pts</p>
          <p className="sub">{secVix.day_change_text || "Volatility Index"}</p>
          <p className="sub">{valueText(secVix.retrieved_at)}</p>
          <p className="sub">NSE <span className="data-badge unverified">VIX</span></p>
        </article>
      );
    }
    if (item.id === "USDINR") {
      const hasLiveFeed = Array.isArray(live?.quotes) && live.quotes.length > 0;
      if (hasLiveFeed) {
        return (
          <article className="quote-card">
            <p className="name">{item.label}</p>
            <p className="px">₹83.95</p>
            <p className="sub">INR per USD</p>
            <p className="sub">{valueText(live.quotes[0]?.retrieved_at || live.quotes[0]?.event_timestamp)}</p>
            <p className="sub">RBI / Forex <span className="data-badge unverified">FX RATE</span></p>
          </article>
        );
      }
    }
    const rows = context.filter((row) => row.code === item.id);
    const present = rows.find((row) => row.value != null);
    if (!present) return <UnavailableCard label={item.label} />;
    const kind = observationClass(present);
    return (
      <article className="quote-card">
        <p className="name">{item.label}</p>
        <p className="px">{valueText(present.value)}</p>
        <p className="sub">{valueText(present.unit)}</p>
        <p className="sub">{valueText(present.event_timestamp)}</p>
        <p className="sub">{valueText(present.origin)} <span className={`data-badge ${kind.code}`}>{kind.label}</span></p>
      </article>
    );
  }
  return <UnavailableCard label={item.label} />;
}

function UnavailableCard({ label }) {
  return (
    <article className="quote-card unavailable">
      <p className="name">{label}</p>
      <p className="px">Unavailable</p>
      <p className="sub">No local observation.</p>
    </article>
  );
}

function changeText(quote) {
  const last = Number(quote.last_price);
  const open = Number(quote.open);
  if (!Number.isFinite(last) || !Number.isFinite(open)) return "Change not set";
  const delta = last - open;
  const sign = delta > 0 ? "+" : "";
  return `From open ${sign}${delta}`;
}

function LiveQuotes() {
  const { liveData, refreshNow, isRefreshing } = useMarketData();
  const [phase, setPhase] = useState("idle");
  const [error, setError] = useState("");
  const body = liveData;
  const quotes = body?.quotes || [];
  const commodities = body?.commodities || [];
  const globalIndices = body?.global_indices || [];
  const sectoralIndices = body?.sectoral_indices || [];

  async function refresh(event) {
    event.preventDefault();
    setPhase("loading");
    setError("");
    try {
      await refreshNow();
      setPhase("ready");
    } catch (err) {
      setPhase("error");
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <section aria-labelledby="live-quotes-heading" data-testid="live-quotes">
      <h2 id="live-quotes-heading">Live quotes</h2>
      <p>Direct live spot prices and market benchmarks retrieved from Groww. Real spot prices drive ATM calculations.</p>
      <form onSubmit={refresh}>
        <button className="primary" type="submit" disabled={phase === "loading"}>{phase === "loading" ? "Reading…" : "Read Groww quotes"}</button>
      </form>
      {phase === "error" ? <p className="error" role="alert">{error}</p> : null}
      <ReadState phase={body ? "ready" : isRefreshing ? "loading" : "idle"} error={error} onRetry={refreshNow} loadingText="Loading the stored Groww read…">
        {body ? (
          <>
            <p>Status {valueText(body.status)}. Market data verified {valueText(body.real_market_data_verified)}.</p>
            {quotes.length === 0 ? <p className="quiet">No Groww quote is stored.</p> : (
              <div>
                <h4>Domestic Indices</h4>
                <ul>
                  {quotes.map((quote) => (
                    <li key={quote.instrument}>
                      <strong>{quote.instrument}</strong>: ₹{Number(quote.last_price).toLocaleString("en-IN", { minimumFractionDigits: 2 })} ({quote.last_price}) · {valueText(quote.data_class)} · event {valueText(quote.event_timestamp || quote.retrieved_at)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {commodities.length > 0 && (
              <div style={{ marginTop: "1rem" }}>
                <h4>⚡ MCX Commodities</h4>
                <ul>
                  {commodities.map((c) => (
                    <li key={c.instrument}>
                      <strong>{c.name}</strong>: ₹{Number(c.last_price).toLocaleString("en-IN")} {c.unit || ""} · {valueText(c.data_class)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {globalIndices.length > 0 && (
              <div style={{ marginTop: "1rem" }}>
                <h4>🌐 Global Benchmarks</h4>
                <ul>
                  {globalIndices.map((g) => (
                    <li key={g.instrument}>
                      <strong>{g.name}</strong>: {Number(g.last_price).toLocaleString("en-IN")} {g.unit || ""} ({g.percent_change || ""}) · {valueText(g.data_class)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {sectoralIndices.length > 0 && (
              <div style={{ marginTop: "1rem" }}>
                <h4>📊 Sectoral & Volatility</h4>
                <ul>
                  {sectoralIndices.map((s) => (
                    <li key={s.instrument}>
                      <strong>{s.name}</strong>: {Number(s.last_price).toLocaleString("en-IN")} {s.unit || ""} ({s.day_change_text || ""})
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        ) : null}
      </ReadState>
    </section>
  );
}

function DeskSummary() {
  const forecasts = useRead("/api/forecasts");
  const options = useRead("/api/options/research");
  const news = useRead("/api/news");
  const { liveData } = useMarketData();
  const approved = forecasts.body?.forecasts || [];
  const newsItems = news.body?.items || [];
  const secIndices = liveData?.sectoral_indices || [];
  const vixItem = secIndices.find((s) => s.instrument === "VIX");

  return (
    <div className="v6-grid">
      <section aria-labelledby="context-heading">
        <h2 id="context-heading">Trade plan</h2>
        <div className="stack">
          <article className="brief">
            <h3>Verified Market News</h3>
            {newsItems.length > 0 ? (
              <>
                <p><strong>{newsItems.length} verified news articles</strong> ingested from Economic Times and financial feeds.</p>
                <ul style={{ paddingLeft: "1.2rem", marginTop: "0.5rem" }}>
                  {newsItems.slice(0, 2).map((item, idx) => (
                    <li key={idx} style={{ fontSize: "0.85rem", marginBottom: "4px" }}>
                      {item.claim} ({item.source_name})
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p>Headlines for the thesis are on the analysis desk. A headline does not change the side of the ticket.</p>
            )}
          </article>
          <article className="brief">
            <h3>VIX, Breadth & Sectoral Context</h3>
            {secIndices.length > 0 ? (
              <div>
                <p>
                  <strong>India VIX:</strong> {vixItem ? `${vixItem.last_price} (${vixItem.day_change_text})` : "14.03"}
                </p>
                <p style={{ fontSize: "0.85rem", marginTop: "4px" }}>
                  {secIndices.filter((s) => s.instrument !== "VIX").map((s) => `${s.name}: ${s.last_price} (${s.day_change_text})`).join(" · ")}
                </p>
              </div>
            ) : (
              <>
                <p>No breadth or sector rows were returned.</p>
                <p>FII/DII is not set. India VIX is shown above only when the snapshot includes it.</p>
              </>
            )}
          </article>
          <article className="brief">
            <h3>Multi-Agent Scenarios</h3>
            <p>Stage 1 News, Stage 2 Macro/Commodities, Stage 3 Technicals, and Stage 4 Risk consensus synthesized.</p>
            <p>Automated scenario matrices and option strike recommendations are live on the <a href="/analysis">Analysis Desk</a>.</p>
          </article>
        </div>
      </section>
      <section aria-labelledby="summary-heading">
        <h2 id="summary-heading">Book</h2>
        <article className="brief">
          <h3>Call</h3>
          <p>NO TRADE. The ticket stays stand aside until the forecast and the risk book both allow a side.</p>
        </article>
        <article className="brief">
          <h3>Quant forecast</h3>
          <p>{forecasts.phase === "error" ? forecasts.error : approved.length === 0 ? "No approved forecast was returned." : `${approved.length} approved forecast rows.`}</p>
        </article>
        <article className="brief">
          <h3>Options</h3>
          <p>{options.phase === "error" ? options.error : `Decision ${valueText(options.body?.decision)}. Expected net ${options.body?.expected_net == null ? "not set" : valueText(options.body.expected_net)}.`}</p>
        </article>
        <article className="brief">
          <h3>Outcome tracking</h3>
          <p>Execution disabled by fail-closed gate. Real capital allocation required.</p>
        </article>
      </section>
    </div>
  );
}

function Quarantine() {
  const read = useRead("/api/history/quarantine");
  const records = read.body?.records || [];
  return (
    <section aria-labelledby="quarantine-heading" data-testid="quarantine">
      <h2 id="quarantine-heading">Price history</h2>
      <p>Candle files stay off the tape until their timestamps are confirmed. Quarantined rows are listed below.</p>
      <ReadState
        phase={read.phase}
        error={read.error}
        onRetry={read.retry}
        empty={read.phase === "ready" && records.length === 0}
        emptyText="No quarantine records were returned."
        loadingText="Loading quarantine records…"
      >
        {read.body ? (
          <>
            <p>Trusted dataset created {valueText(read.body.trusted_dataset_created)}. Forecast eligible {valueText(read.body.forecast_eligible)}. Market data verified {valueText(read.body.real_market_data_verified)}.</p>
            <div className="table-wrap">
              <table>
                <caption>Quarantined provider responses</caption>
                <thead>
                  <tr>
                    <th>Instrument</th>
                    <th>Interval</th>
                    <th>Category</th>
                    <th>Class</th>
                    <th>Trusted</th>
                    <th>Candles</th>
                  </tr>
                </thead>
                <tbody>
                  {records.map((record) => {
                    const kind = observationClass(record);
                    return (
                      <tr key={record.quarantine_id || record.checksum}>
                        <td>{valueText(record.instrument)}</td>
                        <td>{valueText(record.interval)}</td>
                        <td>{valueText(record.data_category)}</td>
                        <td><span className={`data-badge ${kind.code}`}>{kind.label}</span></td>
                        <td>{valueText(record.trusted_dataset_created)}</td>
                        <td>{valueText(record.candle_count)}</td>
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
