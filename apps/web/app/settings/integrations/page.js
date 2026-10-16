"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  connectionLabel,
  credentialLabel,
  diagnosticPreview,
  diagnosticSubmitAllowed,
  expiryLabel,
  growwSavePlan,
  historicalLabel,
  integrationLabel,
  openaiSavePlan,
  safetySummary,
  secretIndicator,
  wallSpanMinutes,
} from "./labels.mjs";

function csrf() {
  const match = document.cookie.match(/(?:^|; )imm_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

function when(value) {
  if (!value) return "Not run";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Kolkata",
  }).format(date);
}

const MODELS = ["gpt-4.1-mini", "gpt-6-luna", "gpt-6.1-sol"];
const DEFAULT_START = "2026-10-13T09:15";
const DEFAULT_END = "2026-10-13T09:45";
const METHODS = {
  api_key_secret: "API key and secret",
  totp: "API key and TOTP",
  access_token: "Access token",
};

function pillClass(kind) {
  if (kind === "ok") return "pill ok";
  if (kind === "bad") return "pill bad";
  if (kind === "wait") return "pill wait";
  return "pill idle";
}

function GrowwMark() {
  return (
    <span className="mark groww" aria-hidden="true">
      <svg viewBox="0 0 32 32" width="22" height="22">
        <path fill="currentColor" d="M8 22V10h4.2l3.8 7.2L19.8 10H24v12h-3.2v-6.4L17.2 22h-2.4l-3.6-6.4V22H8z" />
      </svg>
    </span>
  );
}

function OpenAIMark() {
  return (
    <span className="mark openai" aria-hidden="true">
      <svg viewBox="0 0 32 32" width="22" height="22">
        <circle cx="16" cy="16" r="4" fill="currentColor" />
        <path fill="none" stroke="currentColor" strokeWidth="1.8" d="M16 6.5v3.2M16 22.3v3.2M6.5 16h3.2M22.3 16h3.2M9.2 9.2l2.2 2.2M20.6 20.6l2.2 2.2M22.8 9.2l-2.2 2.2M11.4 20.6l-2.2 2.2" />
      </svg>
    </span>
  );
}

export default function IntegrationsPage() {
  const [ready, setReady] = useState(false);
  const [status, setStatus] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");
  const [booting, setBooting] = useState(true);
  const [panel, setPanel] = useState(null);
  const [growwDraft, setGrowwDraft] = useState(null);
  const [openaiDraft, setOpenaiDraft] = useState(null);
  const [confirmEnable, setConfirmEnable] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [diagStart, setDiagStart] = useState(DEFAULT_START);
  const [diagEnd, setDiagEnd] = useState(DEFAULT_END);
  const [diagConfirm, setDiagConfirm] = useState(false);
  const [diagResult, setDiagResult] = useState(null);

  async function load() {
    const response = await fetch("/api/integrations");
    if (response.status === 401) {
      setReady(false);
      setStatus(null);
      return;
    }
    const body = await response.json();
    setStatus(body);
    setReady(true);
  }

  useEffect(() => {
    load().catch((err) => setError(String(err))).finally(() => setBooting(false));
  }, []);

  async function send(path, payload) {
    setError("");
    setNotice("");
    setBusy(path);
    try {
      const method = path.endsWith("/test") || path.endsWith("/clear") || path.endsWith("/enabled") || path.endsWith("/profile") || path.endsWith("/historical-diagnostic") ? "POST" : "PUT";
      const response = await fetch(path, {
        method,
        headers: { "content-type": "application/json", "x-csrf-token": csrf() },
        body: payload === undefined ? undefined : JSON.stringify(payload),
      });
      const body = await response.json();
      if (body.groww || body.openai) setStatus(body);
      if (!response.ok) {
        const origin = body.error_origin === "provider" ? "Provider" : "Local check";
        setError(`${origin}: ${body.result?.message || body.message || "The request failed"}`);
        return null;
      }
      if (path.endsWith("/test")) setNotice("Connection test finished.");
      else if (path.endsWith("/clear")) setNotice("Credentials removed.");
      else if (path.endsWith("/enabled")) setNotice(payload.enabled ? "Integration enabled. Live trading stays off." : "Integration disabled.");
      else if (!path.endsWith("/historical-diagnostic")) setNotice("Settings saved.");
      return body;
    } finally {
      setBusy("");
    }
  }

  function openGroww() {
    const groww = status?.groww;
    if (!groww) return;
    setGrowwDraft({
      method: groww.auth_method || "api_key_secret",
      enabled: groww.enabled === true,
      apiKey: "",
      apiSecret: "",
      accessToken: "",
      totpSecret: "",
    });
    setConfirmEnable(false);
    setConfirmClear(false);
    setPanel("groww");
  }

  function openOpenAI() {
    const openai = status?.openai;
    if (!openai) return;
    setOpenaiDraft({
      model: openai.model || "gpt-4.1-mini",
      label: openai.label || "",
      enabled: openai.enabled === true,
      apiKey: "",
    });
    setConfirmEnable(false);
    setPanel("openai");
  }

  function closePanel() {
    setPanel(null);
    setConfirmEnable(false);
    setConfirmClear(false);
  }

  async function saveGroww(event) {
    event.preventDefault();
    const groww = status.groww;
    const secretsEntered = [growwDraft.apiKey, growwDraft.apiSecret, growwDraft.accessToken, growwDraft.totpSecret].some((value) => value.trim());
    const plan = growwSavePlan({
      method: growwDraft.method,
      savedMethod: groww.auth_method || "api_key_secret",
      enabled: growwDraft.enabled,
      savedEnabled: groww.enabled === true,
      secretsEntered,
      confirmEnable,
    });
    if (plan.blocked === "UNCHANGED") return;
    if (plan.blocked === "CREDENTIALS_REQUIRED") {
      setError("Local check: enter the credentials for the selected authentication method before saving.");
      return;
    }
    if (plan.blocked === "CONFIRMATION_REQUIRED") {
      setConfirmEnable(true);
      return;
    }
    if (plan.steps.includes("save-credentials")) {
      const payload = { method: growwDraft.method, label: groww.label || "" };
      if (growwDraft.method === "access_token") payload.access_token = growwDraft.accessToken;
      if (growwDraft.method === "api_key_secret") {
        payload.api_key = growwDraft.apiKey;
        payload.api_secret = growwDraft.apiSecret;
      }
      if (growwDraft.method === "totp") {
        payload.api_key = growwDraft.apiKey;
        payload.totp_secret = growwDraft.totpSecret;
      }
      const saved = await send("/api/integrations/groww", payload);
      if (!saved) return;
    }
    if (plan.steps.includes("set-enabled")) {
      const saved = await send("/api/integrations/groww/enabled", { enabled: growwDraft.enabled, confirm: true });
      if (!saved) return;
    }
    closePanel();
  }

  async function saveOpenAI(event) {
    event.preventDefault();
    const openai = status.openai;
    const plan = openaiSavePlan({
      model: openaiDraft.model,
      savedModel: openai.model || "",
      label: openaiDraft.label,
      savedLabel: openai.label || "",
      enabled: openaiDraft.enabled,
      savedEnabled: openai.enabled === true,
      keyEntered: Boolean(openaiDraft.apiKey.trim()),
      confirmEnable,
    });
    if (plan.blocked === "UNCHANGED") return;
    if (plan.blocked === "CONFIRMATION_REQUIRED") {
      setConfirmEnable(true);
      return;
    }
    if (plan.steps.includes("save-credentials")) {
      const saved = await send("/api/integrations/openai", {
        api_key: openaiDraft.apiKey,
        model: openaiDraft.model,
        label: openaiDraft.label,
        enabled: openai.enabled === true,
      });
      if (!saved) return;
    }
    if (plan.steps.includes("save-profile")) {
      const saved = await send("/api/integrations/openai/profile", {
        model: openaiDraft.model,
        label: openaiDraft.label,
        confirm: true,
      });
      if (!saved) return;
    }
    if (plan.steps.includes("set-enabled")) {
      const saved = await send("/api/integrations/openai/enabled", { enabled: openaiDraft.enabled, confirm: true });
      if (!saved) return;
    }
    closePanel();
  }

  async function runDiagnostic(event) {
    event.preventDefault();
    const decision = diagnosticSubmitAllowed({
      enabled: status?.groww?.enabled === true,
      confirmed: diagConfirm,
      span: wallSpanMinutes(diagStart, diagEnd),
    });
    if (!decision.ok) {
      setError(decision.code === "INTEGRATION_DISABLED"
        ? "Local check: enable Groww before running a historical diagnostic."
        : decision.code === "RANGE"
          ? "Local check: the one-minute diagnostic accepts a range of at most 30 minutes."
          : "Local check: confirm the diagnostic before a request is sent.");
      return;
    }
    const body = await send("/api/integrations/groww/historical-diagnostic", {
      exchange: "NSE",
      segment: "CASH",
      groww_symbol: "NSE-NIFTY",
      candle_interval: "1minute",
      start: `${diagStart}:00+05:30`,
      end: `${diagEnd}:00+05:30`,
      confirm: true,
    });
    setDiagResult(body);
    setDiagConfirm(false);
    if (body && !body.groww) await load().catch(() => {});
  }

  const groww = status?.groww;
  const openai = status?.openai;
  const safety = safetySummary(status);
  const span = wallSpanMinutes(diagStart, diagEnd);
  const diagnosticDecision = diagnosticSubmitAllowed({
    enabled: groww?.enabled === true,
    confirmed: diagConfirm,
    span,
  });
  const preview = diagnosticPreview({
    exchange: "NSE",
    segment: "CASH",
    groww_symbol: "NSE-NIFTY",
    candle_interval: "1minute",
    start: diagStart,
    end: diagEnd,
  });

  return (
    <main className="integrations">
      <header className="page-head">
        <p className="eyebrow">Settings</p>
        <h1>API Integrations</h1>
        <p>Manage provider credentials, connection tests, and read-only diagnostics.</p>
      </header>
      {notice ? <p className="notice">{notice}</p> : null}
      {error ? <p className="alert" role="alert">{error}</p> : null}
      {booting ? <p className="note">Checking the operator session.</p> : null}
      {!booting && !ready ? (
        <section>
          <h2>Sign in required</h2>
          <p>API keys can be saved after the operator session starts.</p>
          <Link className="primary" href="/">Sign in</Link>
        </section>
      ) : null}
      {status ? (
        <div className="summary-strip" aria-label="Status summary">
          <article><span>Live trading</span><strong>{safety.liveTrading}</strong></article>
          <article><span>Groww</span><strong>{groww ? integrationLabel(groww.enabled) : "Unavailable"}</strong></article>
          <article><span>OpenAI</span><strong>{openai ? integrationLabel(openai.enabled) : "Unavailable"}</strong></article>
          <article><span>Market data</span><strong>{safety.marketData}</strong></article>
        </div>
      ) : null}
      {groww && openai ? (
        <div className="provider-grid">
          <ProviderCard
            mark={<GrowwMark />}
            name="Groww"
            detail={METHODS[groww.auth_method] || "No method saved"}
            enabled={groww.enabled}
            configured={groww.configured}
            connection={groww.last_test_ok}
            extraBadge={expiryLabel(groww.token_status?.status)}
            extraKind={groww.token_status?.status === "VALID" ? "ok" : groww.token_status?.status === "EXPIRED" ? "bad" : "wait"}
            historyBadge={historicalLabel(groww.permissions?.historical_candles)}
            historyKind={groww.permissions?.historical_candles === "verified" ? "ok" : groww.permissions?.historical_candles === "not_tested" ? "idle" : "wait"}
            facts={[
              ["Last test", `${connectionLabel(groww.last_test_ok)} · ${when(groww.last_test_at)}`],
              ["Token expiry", groww.token_status?.display_ist || "Not available"],
            ]}
            detailsTitle="Connection details"
            details={`${groww.connectivity?.endpoint || "No endpoint recorded"}. ${groww.connectivity?.does_not_prove || ""}`}
            busy={busy}
            onConfigure={openGroww}
            onTest={() => send("/api/integrations/groww/test")}
            onDiagnostics={() => document.getElementById("groww-diagnostics")?.scrollIntoView({ behavior: "smooth", block: "start" })}
          />
          <ProviderCard
            mark={<OpenAIMark />}
            name="OpenAI"
            detail={openai.model || "No model selected"}
            enabled={openai.enabled}
            configured={openai.configured}
            connection={openai.last_test_ok}
            facts={[
              ["Last test", `${connectionLabel(openai.last_test_ok)} · ${when(openai.last_test_at)}`],
              ["Model", openai.model || "None"],
            ]}
            detailsTitle="Connection details"
            details={`${openai.connectivity?.endpoint || "No endpoint recorded"}. ${openai.connectivity?.does_not_prove || ""}`}
            busy={busy}
            onConfigure={openOpenAI}
            onTest={() => send("/api/integrations/openai/test")}
            testDisabled={!openai.enabled}
          />
        </div>
      ) : null}
      {groww && ready ? (
        <section id="groww-diagnostics" className="diagnostics">
          <div className="section-head">
            <div>
              <h2>Groww historical diagnostics</h2>
              <p>One read-only candle request for a completed session. This is not a live quote.</p>
            </div>
            <span className={pillClass(groww.one_minute_diagnostic === "not_tested" ? "idle" : "wait")}>
              {historicalLabel(groww.one_minute_diagnostic)}
            </span>
          </div>
          {groww.enabled !== true ? (
            <div className="callout">
              <p>Groww is disabled, so this diagnostic cannot run. Enable it in configuration. That does not turn on live trading.</p>
              <button type="button" className="primary" onClick={openGroww}>Configure Groww</button>
            </div>
          ) : null}
          <form onSubmit={runDiagnostic}>
            <div className="diag-layout">
              <div className="fact-grid">
                <div className="fact"><span>Exchange</span><b>NSE</b></div>
                <div className="fact"><span>Segment</span><b>CASH</b></div>
                <div className="fact"><span>Instrument</span><b>NSE-NIFTY</b></div>
                <div className="fact"><span>Interval</span><b>1 minute</b></div>
                <div className="fact"><span>Maximum range</span><b>30 minutes</b></div>
                <div className="fact"><span>Current span</span><b>{span === null ? "—" : `${span} min`}</b></div>
              </div>
              <div>
                <label>
                  Start
                  <input type="datetime-local" value={diagStart} onChange={(event) => { setDiagStart(event.target.value); setDiagConfirm(false); }} />
                </label>
                <label>
                  End
                  <input type="datetime-local" value={diagEnd} onChange={(event) => { setDiagEnd(event.target.value); setDiagConfirm(false); }} />
                </label>
                <label className="check">
                  <input type="checkbox" checked={diagConfirm} onChange={(event) => setDiagConfirm(event.target.checked)} disabled={groww.enabled !== true} />
                  Run this request once. Do not retry or refresh the token.
                </label>
                <button className="primary" type="submit" disabled={Boolean(busy) || !diagnosticDecision.ok}>Run diagnostic</button>
              </div>
              <pre aria-label="Request preview">{preview}</pre>
            </div>
          </form>
          <details>
            <summary>Diagnostic details</summary>
            <p>The clock is sent as Asia/Kolkata wall time. Provider timestamp meaning stays unverified. No exchange calendar is configured, so this page does not say whether the market is open. A response stays quarantined.</p>
          </details>
          {diagResult ? (
            <p className="note">
              {diagResult.error_origin === "provider" ? "Provider" : "Local check"}: {diagResult.message}
              {diagResult.report ? ` · HTTP ${diagResult.report.http_status} · ${diagResult.report.candle_count} candles · not trusted` : ""}
            </p>
          ) : null}
          <h3>Previous results</h3>
          {groww.diagnostic_history?.length ? (
            <table>
              <thead>
                <tr><th>Interval</th><th>Candles</th><th>From</th><th>To</th><th>HTTP</th><th>Status</th></tr>
              </thead>
              <tbody>
                {groww.diagnostic_history.map((item) => (
                  <tr key={item.quarantine_id}>
                    <td>{item.candle_interval || "—"}</td>
                    <td>{item.candle_count ?? "—"}</td>
                    <td>{item.first_raw_timestamp || "—"}</td>
                    <td>{item.last_raw_timestamp || "—"}</td>
                    <td>{item.http_status ?? "—"}</td>
                    <td>{item.label || "Unreadable"} · not trusted</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <p className="note">No previous diagnostic is stored.</p>}
        </section>
      ) : null}
      {panel === "groww" && growwDraft ? (
        <div className="modal-backdrop" onClick={closePanel}>
          <form className="modal" role="dialog" aria-labelledby="groww-settings-title" onClick={(event) => event.stopPropagation()} onSubmit={saveGroww}>
            <div className="section-head">
              <h2 id="groww-settings-title">Configure Groww</h2>
              <button type="button" onClick={closePanel}>Close</button>
            </div>
            <button type="button" className={`switch ${growwDraft.enabled ? "on" : ""}`} onClick={() => { setGrowwDraft({ ...growwDraft, enabled: !growwDraft.enabled }); setConfirmEnable(false); }}>
              <span>Integration <small>{growwDraft.enabled ? "Enabled" : "Disabled"} · live trading stays off</small></span>
              <span className="knob" aria-hidden="true"><span /></span>
            </button>
            <label>
              Authentication method
              <select value={growwDraft.method} onChange={(event) => setGrowwDraft({ ...growwDraft, method: event.target.value })}>
                <option value="api_key_secret">API key and secret</option>
                <option value="totp">API key and TOTP</option>
                <option value="access_token">Access token</option>
              </select>
            </label>
            <div className="status-line"><span>API key</span><b>{secretIndicator(groww.api_key_configured)}</b></div>
            {growwDraft.method !== "access_token" ? (
              <label>
                Replace API key
                <input type="password" autoComplete="off" value={growwDraft.apiKey} placeholder={groww.api_key_configured ? "Saved · hidden" : "Enter API key"} onChange={(event) => setGrowwDraft({ ...growwDraft, apiKey: event.target.value })} />
              </label>
            ) : null}
            <div className="status-line"><span>API secret</span><b>{secretIndicator(groww.api_secret_configured)}</b></div>
            {growwDraft.method === "api_key_secret" ? (
              <label>
                Replace API secret
                <input type="password" autoComplete="off" value={growwDraft.apiSecret} placeholder={groww.api_secret_configured ? "Saved · hidden" : "Enter API secret"} onChange={(event) => setGrowwDraft({ ...growwDraft, apiSecret: event.target.value })} />
              </label>
            ) : null}
            <div className="status-line"><span>Access token</span><b>{secretIndicator(groww.access_token_configured)}</b></div>
            <div className="status-line"><span>Token expiry</span><b>{groww.token_status?.display_ist || "Not available"} · {expiryLabel(groww.token_status?.status)}</b></div>
            {growwDraft.method === "access_token" ? (
              <label>
                Replace access token
                <input type="password" autoComplete="off" value={growwDraft.accessToken} placeholder={groww.access_token_configured ? "Saved · hidden" : "Enter access token"} onChange={(event) => setGrowwDraft({ ...growwDraft, accessToken: event.target.value })} />
              </label>
            ) : null}
            <div className="status-line"><span>TOTP secret</span><b>{secretIndicator(groww.totp_secret_configured)}</b></div>
            {growwDraft.method === "totp" ? (
              <label>
                Replace TOTP secret
                <input type="password" autoComplete="off" value={growwDraft.totpSecret} placeholder={groww.totp_secret_configured ? "Saved · hidden" : "Enter TOTP secret"} onChange={(event) => setGrowwDraft({ ...growwDraft, totpSecret: event.target.value })} />
              </label>
            ) : null}
            {confirmEnable ? <p className="note">Confirm to {growwDraft.enabled ? "enable" : "disable"} Groww. Enabling lets the app use stored credentials. Live trading stays off, and endpoint access is not guaranteed.</p> : null}
            <div className="actions">
              <button className="primary" type="submit" disabled={Boolean(busy)}>{confirmEnable ? "Confirm and save" : "Save changes"}</button>
              <button type="button" onClick={() => send("/api/integrations/groww/test")} disabled={Boolean(busy)}>Test connection</button>
              <button className="danger" type="button" onClick={async () => { if (!confirmClear) { setConfirmClear(true); return; } if (await send("/api/integrations/groww/clear")) closePanel(); }} disabled={Boolean(busy)}>{confirmClear ? "Confirm removal" : "Remove credentials"}</button>
            </div>
          </form>
        </div>
      ) : null}
      {panel === "openai" && openaiDraft ? (
        <div className="modal-backdrop" onClick={closePanel}>
          <form className="modal" role="dialog" aria-labelledby="openai-settings-title" onClick={(event) => event.stopPropagation()} onSubmit={saveOpenAI}>
            <div className="section-head">
              <h2 id="openai-settings-title">Configure OpenAI</h2>
              <button type="button" onClick={closePanel}>Close</button>
            </div>
            <button type="button" className={`switch ${openaiDraft.enabled ? "on" : ""}`} onClick={() => { setOpenaiDraft({ ...openaiDraft, enabled: !openaiDraft.enabled }); setConfirmEnable(false); }}>
              <span>Integration <small>{openaiDraft.enabled ? "Enabled" : "Disabled"}</small></span>
              <span className="knob" aria-hidden="true"><span /></span>
            </button>
            <div className="status-line"><span>API key</span><b>{secretIndicator(openai.api_key_configured)}</b></div>
            <label>
              Replace API key
              <input type="password" autoComplete="off" value={openaiDraft.apiKey} placeholder={openai.api_key_configured ? "Saved · hidden" : "Enter API key"} onChange={(event) => setOpenaiDraft({ ...openaiDraft, apiKey: event.target.value })} />
            </label>
            <label>
              Model
              <select value={openaiDraft.model} onChange={(event) => setOpenaiDraft({ ...openaiDraft, model: event.target.value })}>
                {MODELS.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </label>
            <label>
              Label
              <input value={openaiDraft.label} onChange={(event) => setOpenaiDraft({ ...openaiDraft, label: event.target.value })} />
            </label>
            {confirmEnable ? <p className="note">Confirm to {openaiDraft.enabled ? "enable" : "disable"} OpenAI. This does not request a completion.</p> : null}
            <div className="actions">
              <button className="primary" type="submit" disabled={Boolean(busy)}>{confirmEnable ? "Confirm and save" : "Save changes"}</button>
              <button type="button" onClick={() => send("/api/integrations/openai/test")} disabled={Boolean(busy) || !openai.enabled}>Test connection</button>
            </div>
          </form>
        </div>
      ) : null}
    </main>
  );
}

function ProviderCard({ mark, name, detail, enabled, configured, connection, extraBadge, extraKind, historyBadge, historyKind, facts, detailsTitle, details, busy, onConfigure, onTest, onDiagnostics, testDisabled }) {
  const connectionKind = connection === true ? "ok" : connection === false ? "bad" : "idle";
  return (
    <section className="provider-card">
      <div className="provider-head">
        <div className="provider-id">
          {mark}
          <div className="provider-copy">
            <h2>{name}</h2>
            <small>{detail}</small>
          </div>
        </div>
        <span className={pillClass(enabled ? "ok" : "wait")}>{integrationLabel(enabled)}</span>
      </div>
      <div className="badge-row">
        <span className={pillClass(configured ? "ok" : "idle")}>{credentialLabel(configured)}</span>
        <span className={pillClass(connectionKind)}>{connectionLabel(connection)}</span>
        {extraBadge ? <span className={pillClass(extraKind)}>{extraBadge}</span> : null}
        {historyBadge ? <span className={pillClass(historyKind)}>{historyBadge}</span> : null}
      </div>
      <dl className="meta-row">
        {facts.map(([label, value]) => (
          <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
        ))}
      </dl>
      <details>
        <summary>{detailsTitle}</summary>
        <p>{details}</p>
      </details>
      <div className="card-actions">
        <button type="button" className="primary" onClick={onConfigure} disabled={Boolean(busy)}>Configure</button>
        <button type="button" onClick={onTest} disabled={Boolean(busy) || testDisabled}>Test connection</button>
        {onDiagnostics ? <button type="button" onClick={onDiagnostics}>Diagnostics</button> : null}
      </div>
    </section>
  );
}
