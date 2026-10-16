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
const GEMINI_MODELS = ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash"];
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

function KiteMark() {
  return (
    <span className="mark kite" aria-hidden="true" style={{ background: "#ff5722", color: "#fff", display: "inline-flex", alignItems: "center", justifyContent: "center", borderRadius: "6px", width: "24px", height: "24px", fontWeight: "bold", fontSize: "14px" }}>
      K
    </span>
  );
}

function UpstoxMark() {
  return (
    <span className="mark upstox" aria-hidden="true" style={{ background: "#4a148c", color: "#fff", display: "inline-flex", alignItems: "center", justifyContent: "center", borderRadius: "6px", width: "24px", height: "24px", fontWeight: "bold", fontSize: "14px" }}>
      U
    </span>
  );
}

function AngelOneMark() {
  return (
    <span className="mark angelone" aria-hidden="true" style={{ background: "#0288d1", color: "#fff", display: "inline-flex", alignItems: "center", justifyContent: "center", borderRadius: "6px", width: "24px", height: "24px", fontWeight: "bold", fontSize: "14px" }}>
      A
    </span>
  );
}

function GeminiMark() {
  return (
    <span className="mark gemini" aria-hidden="true" style={{ background: "#1a73e8", color: "#fff", display: "inline-flex", alignItems: "center", justifyContent: "center", borderRadius: "6px", width: "24px", height: "24px", fontWeight: "bold", fontSize: "14px" }}>
      G
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
  const [upstoxDraft, setUpstoxDraft] = useState(null);
  const [kiteDraft, setKiteDraft] = useState(null);
  const [angeloneDraft, setAngeloneDraft] = useState(null);
  const [geminiDraft, setGeminiDraft] = useState(null);
  const [agentsConfig, setAgentsConfig] = useState(null);
  const [agentsBusy, setAgentsBusy] = useState(false);
  const [compResult, setCompResult] = useState(null);
  const [compBusy, setCompBusy] = useState(false);
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
    fetch("/api/analysis/agents/config")
      .then((r) => (r.ok ? r.json() : null))
      .then((cfg) => {
        if (cfg) setAgentsConfig(cfg);
      })
      .catch(() => {});
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
      if (body.groww || body.openai || body.gemini || body.upstox || body.kite || body.angelone) setStatus(body);
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

  function openUpstox() {
    const upstox = status?.upstox;
    if (!upstox) return;
    setUpstoxDraft({
      enabled: upstox.enabled === true,
      accessToken: "",
      label: upstox.label || "",
    });
    setConfirmEnable(false);
    setPanel("upstox");
  }

  function openKite() {
    const kite = status?.kite;
    if (!kite) return;
    setKiteDraft({
      enabled: kite.enabled === true,
      apiKey: "",
      accessToken: "",
      label: kite.label || "",
    });
    setConfirmEnable(false);
    setPanel("kite");
  }

  function openAngelOne() {
    const angelone = status?.angelone;
    if (!angelone) return;
    setAngeloneDraft({
      enabled: angelone.enabled === true,
      apiKey: "",
      clientCode: "",
      jwtToken: "",
      label: angelone.label || "",
    });
    setConfirmEnable(false);
    setPanel("angelone");
  }

  function openGemini() {
    const gemini = status?.gemini;
    if (!gemini) return;
    setGeminiDraft({
      enabled: gemini.enabled === true,
      apiKey: "",
      model: gemini.model || "gemini-1.5-pro",
      label: gemini.label || "",
    });
    setConfirmEnable(false);
    setPanel("gemini");
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

  async function saveUpstox(event) {
    event.preventDefault();
    if (upstoxDraft.accessToken.trim()) {
      const saved = await send("/api/integrations/upstox", {
        access_token: upstoxDraft.accessToken,
        label: upstoxDraft.label,
        enabled: status.upstox?.enabled === true,
      });
      if (!saved) return;
    }
    if (upstoxDraft.enabled !== (status.upstox?.enabled === true)) {
      const saved = await send("/api/integrations/upstox/enabled", {
        enabled: upstoxDraft.enabled,
        confirm: true,
      });
      if (!saved) return;
    }
    closePanel();
  }

  async function saveKite(event) {
    event.preventDefault();
    if (kiteDraft.apiKey.trim() || kiteDraft.accessToken.trim()) {
      const saved = await send("/api/integrations/kite", {
        api_key: kiteDraft.apiKey,
        access_token: kiteDraft.accessToken,
        label: kiteDraft.label,
        enabled: status.kite?.enabled === true,
      });
      if (!saved) return;
    }
    if (kiteDraft.enabled !== (status.kite?.enabled === true)) {
      const saved = await send("/api/integrations/kite/enabled", {
        enabled: kiteDraft.enabled,
        confirm: true,
      });
      if (!saved) return;
    }
    closePanel();
  }

  async function saveAngelOne(event) {
    event.preventDefault();
    if (angeloneDraft.apiKey.trim() || angeloneDraft.jwtToken.trim() || angeloneDraft.clientCode.trim()) {
      const saved = await send("/api/integrations/angelone", {
        api_key: angeloneDraft.apiKey,
        client_code: angeloneDraft.clientCode,
        jwt_token: angeloneDraft.jwtToken,
        label: angeloneDraft.label,
        enabled: status.angelone?.enabled === true,
      });
      if (!saved) return;
    }
    if (angeloneDraft.enabled !== (status.angelone?.enabled === true)) {
      const saved = await send("/api/integrations/angelone/enabled", {
        enabled: angeloneDraft.enabled,
        confirm: true,
      });
      if (!saved) return;
    }
    closePanel();
  }

  async function saveGemini(event) {
    event.preventDefault();
    if (geminiDraft.apiKey.trim()) {
      const saved = await send("/api/integrations/gemini", {
        api_key: geminiDraft.apiKey,
        model: geminiDraft.model,
        label: geminiDraft.label,
        enabled: status.gemini?.enabled === true,
      });
      if (!saved) return;
    }
    if (geminiDraft.model !== (status.gemini?.model || "gemini-1.5-pro")) {
      const saved = await send("/api/integrations/gemini/profile", {
        model: geminiDraft.model,
        label: geminiDraft.label,
        confirm: true,
      });
      if (!saved) return;
    }
    if (geminiDraft.enabled !== (status.gemini?.enabled === true)) {
      const saved = await send("/api/integrations/gemini/enabled", {
        enabled: geminiDraft.enabled,
        confirm: true,
      });
      if (!saved) return;
    }
    closePanel();
  }

  async function saveAgentConfig(event) {
    event.preventDefault();
    setAgentsBusy(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch("/api/analysis/agents/config", {
        method: "PUT",
        headers: { "content-type": "application/json", "x-csrf-token": csrf() },
        body: JSON.stringify(agentsConfig),
      });
      const data = await response.json();
      if (!response.ok) {
        setError(`Failed to save agent config: ${data.detail || data.message || "Unknown error"}`);
      } else {
        setAgentsConfig(data);
        setNotice("AI Agent configurations saved successfully.");
      }
    } catch (err) {
      setError(String(err));
    } finally {
      setAgentsBusy(false);
    }
  }

  async function resetAgentConfig() {
    setAgentsBusy(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch("/api/analysis/agents/reset", {
        method: "POST",
        headers: { "content-type": "application/json", "x-csrf-token": csrf() },
      });
      const data = await response.json();
      if (!response.ok) {
        setError(`Failed to reset: ${data.detail || data.message}`);
      } else {
        setAgentsConfig(data);
        setNotice("AI Agent configuration reset to defaults.");
      }
    } catch (err) {
      setError(String(err));
    } finally {
      setAgentsBusy(false);
    }
  }

  async function runModelComparison() {
    setCompBusy(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch("/api/forecasting/compare", {
        method: "POST",
        headers: { "content-type": "application/json", "x-csrf-token": csrf() },
        body: JSON.stringify({
          symbol: "NIFTY",
          n_splits: 3,
          train_size: 50,
          test_size: 15,
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        setError(`Model comparison failed: ${data.detail || data.message}`);
      } else {
        setCompResult(data);
        setNotice("Controlled quantitative model comparison completed.");
      }
    } catch (err) {
      setError(String(err));
    } finally {
      setCompBusy(false);
    }
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
  const kite = status?.kite;
  const upstox = status?.upstox;
  const angelone = status?.angelone;
  const gemini = status?.gemini;
  const indmoney = status?.indmoney;
  const nse_official = status?.nse_official;

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
          <article><span>Kite</span><strong>{kite ? integrationLabel(kite.enabled) : "Unavailable"}</strong></article>
          <article><span>Upstox</span><strong>{upstox ? integrationLabel(upstox.enabled) : "Unavailable"}</strong></article>
          <article><span>Angel One</span><strong>{angelone ? integrationLabel(angelone.enabled) : "Unavailable"}</strong></article>
          <article><span>OpenAI</span><strong>{openai ? integrationLabel(openai.enabled) : "Unavailable"}</strong></article>
          <article><span>Gemini</span><strong>{gemini ? integrationLabel(gemini.enabled) : "Unavailable"}</strong></article>
        </div>
      ) : null}

      {status ? (
        <>
          <h2 style={{ marginTop: "24px", marginBottom: "8px" }}>Market Data & AI Model Providers</h2>
          <div className="provider-grid">
            {groww ? (
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
            ) : null}

            {kite ? (
              <ProviderCard
                mark={<KiteMark />}
                name="Zerodha Kite Connect"
                detail="Kite Connect v3 REST API"
                enabled={kite.enabled}
                configured={kite.configured}
                connection={kite.last_test_ok}
                historyBadge="Historical Candles: /instruments/historical"
                historyKind={kite.configured ? "ok" : "wait"}
                facts={[
                  ["Last test", `${connectionLabel(kite.last_test_ok)} · ${when(kite.last_test_at)}`],
                  ["Rate Limit", `${kite.rate_limit_per_second || 3} req/s`],
                ]}
                detailsTitle="Connection details"
                details={`${kite.connectivity?.endpoint || "api.kite.trade"}. Credentials are securely encrypted.`}
                busy={busy}
                onConfigure={openKite}
                onTest={() => send("/api/integrations/kite/test")}
                testDisabled={!kite.enabled}
              />
            ) : null}

            {upstox ? (
              <ProviderCard
                mark={<UpstoxMark />}
                name="Upstox API"
                detail="Upstox v2 API"
                enabled={upstox.enabled}
                configured={upstox.configured}
                connection={upstox.last_test_ok}
                historyBadge="Historical Candles: /v2/historical-candle"
                historyKind={upstox.configured ? "ok" : "wait"}
                facts={[
                  ["Last test", `${connectionLabel(upstox.last_test_ok)} · ${when(upstox.last_test_at)}`],
                  ["Rate Limit", `${upstox.rate_limit_per_second || 5} req/s`],
                ]}
                detailsTitle="Connection details"
                details={`${upstox.connectivity?.endpoint || "api.upstox.com/v2"}. Bearer token authenticated.`}
                busy={busy}
                onConfigure={openUpstox}
                onTest={() => send("/api/integrations/upstox/test")}
                testDisabled={!upstox.enabled}
              />
            ) : null}

            {angelone ? (
              <ProviderCard
                mark={<AngelOneMark />}
                name="Angel One SmartAPI"
                detail="SmartAPI REST"
                enabled={angelone.enabled}
                configured={angelone.configured}
                connection={angelone.last_test_ok}
                historyBadge="Historical Candles: /getCandleData"
                historyKind={angelone.configured ? "ok" : "wait"}
                facts={[
                  ["Last test", `${connectionLabel(angelone.last_test_ok)} · ${when(angelone.last_test_at)}`],
                  ["Rate Limit", `${angelone.rate_limit_per_second || 3} req/s`],
                ]}
                detailsTitle="Connection details"
                details={`${angelone.connectivity?.endpoint || "apiconnect.angelone.in"}. JWT & PrivateKey authenticated.`}
                busy={busy}
                onConfigure={openAngelOne}
                onTest={() => send("/api/integrations/angelone/test")}
                testDisabled={!angelone.enabled}
              />
            ) : null}

            {openai ? (
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
                details={`${openai.connectivity?.endpoint || "api.openai.com"}. ${openai.connectivity?.does_not_prove || ""}`}
                busy={busy}
                onConfigure={openOpenAI}
                onTest={() => send("/api/integrations/openai/test")}
                testDisabled={!openai.enabled}
              />
            ) : null}

            {gemini ? (
              <ProviderCard
                mark={<GeminiMark />}
                name="Google Gemini"
                detail={gemini.model || "gemini-1.5-pro"}
                enabled={gemini.enabled}
                configured={gemini.configured}
                connection={gemini.last_test_ok}
                facts={[
                  ["Last test", `${connectionLabel(gemini.last_test_ok)} · ${when(gemini.last_test_at)}`],
                  ["Model", gemini.model || "gemini-1.5-pro"],
                ]}
                detailsTitle="Connection details"
                details={`${gemini.connectivity?.endpoint || "generativelanguage.googleapis.com"}. Google AI API.`}
                busy={busy}
                onConfigure={openGemini}
                onTest={() => send("/api/integrations/gemini/test")}
                testDisabled={!gemini.enabled}
              />
            ) : null}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginTop: "16px" }}>
            <div style={{ background: "var(--card-bg, #1e1e24)", border: "1px solid var(--border-color, #333)", borderRadius: "8px", padding: "16px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <h3 style={{ margin: 0, fontSize: "16px" }}>INDmoney Reference Evaluation</h3>
                <span className="pill bad">{indmoney?.status || "BLOCKED_NOT_PERMITTED"}</span>
              </div>
              <p style={{ fontSize: "13px", color: "var(--text-muted, #aaa)", marginTop: "8px", lineHeight: "1.4" }}>
                {indmoney?.findings || "INDmoney does not provide an official, documented public API for third-party automated historical market data ingestion. Reverse-engineering mobile/private app endpoints violates ToS."}
              </p>
            </div>

            <div style={{ background: "var(--card-bg, #1e1e24)", border: "1px solid var(--border-color, #333)", borderRadius: "8px", padding: "16px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <h3 style={{ margin: 0, fontSize: "16px" }}>NSE Official Reference Evaluation</h3>
                <span className="pill wait">{nse_official?.status || "LIMITED_TO_DAILY_PUBLIC_REPORTS"}</span>
              </div>
              <p style={{ fontSize: "13px", color: "var(--text-muted, #aaa)", marginTop: "8px", lineHeight: "1.4" }}>
                {nse_official?.findings || "Official public NSE portal data is strictly limited to end-of-day reports (Bhavcopy CSVs). Direct programmatic 15-minute intraday tick/candle access requires commercial licensed data feed agreements (DotEx/NSE Data & Analytics)."}
              </p>
            </div>
          </div>
        </>
      ) : null}

      {/* INDEPENDENT AI AGENTS CONFIGURATION */}
      {agentsConfig && agentsConfig.agents ? (
        <section style={{ marginTop: "32px", background: "var(--card-bg, #1e1e24)", border: "1px solid var(--border-color, #333)", borderRadius: "8px", padding: "20px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
            <div>
              <h2 style={{ margin: 0, fontSize: "20px" }}>Independently Configurable AI Agents (LangGraph)</h2>
              <p style={{ margin: "4px 0 0 0", fontSize: "13px", color: "var(--text-muted, #aaa)" }}>
                Config Version {agentsConfig.version}. Configure distinct AI model providers and parameters per specialist role.
              </p>
            </div>
            <div style={{ display: "flex", gap: "8px" }}>
              <button type="button" onClick={resetAgentConfig} disabled={agentsBusy} style={{ padding: "6px 14px" }}>
                Reset to Defaults
              </button>
              <button type="button" className="primary" onClick={saveAgentConfig} disabled={agentsBusy} style={{ padding: "6px 14px" }}>
                Save Agent Settings
              </button>
            </div>
          </div>

          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid #444", textAlign: "left" }}>
                  <th style={{ padding: "8px" }}>Agent Role</th>
                  <th style={{ padding: "8px" }}>Active Provider</th>
                  <th style={{ padding: "8px" }}>Model ID</th>
                  <th style={{ padding: "8px" }}>Temperature</th>
                  <th style={{ padding: "8px" }}>Max Tokens</th>
                  <th style={{ padding: "8px" }}>Fallback Provider</th>
                  <th style={{ padding: "8px" }}>Fallback Model</th>
                  <th style={{ padding: "8px" }}>Enabled</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(agentsConfig.agents).map(([role, cfg]) => (
                  <tr key={role} style={{ borderBottom: "1px solid #2a2a30" }}>
                    <td style={{ padding: "8px", fontWeight: "bold" }}>
                      {role.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                    </td>
                    <td style={{ padding: "8px" }}>
                      <select
                        value={cfg.provider}
                        onChange={(e) => {
                          const updated = { ...agentsConfig };
                          updated.agents[role].provider = e.target.value;
                          setAgentsConfig(updated);
                        }}
                        style={{ padding: "4px 6px" }}
                      >
                        <option value="openai">OpenAI</option>
                        <option value="google">Google Gemini</option>
                      </select>
                    </td>
                    <td style={{ padding: "8px" }}>
                      <input
                        type="text"
                        value={cfg.model_id}
                        onChange={(e) => {
                          const updated = { ...agentsConfig };
                          updated.agents[role].model_id = e.target.value;
                          setAgentsConfig(updated);
                        }}
                        style={{ width: "130px", padding: "4px 6px" }}
                      />
                    </td>
                    <td style={{ padding: "8px" }}>
                      <input
                        type="number"
                        step="0.05"
                        min="0"
                        max="1"
                        value={cfg.temperature}
                        onChange={(e) => {
                          const updated = { ...agentsConfig };
                          updated.agents[role].temperature = parseFloat(e.target.value) || 0;
                          setAgentsConfig(updated);
                        }}
                        style={{ width: "60px", padding: "4px 6px" }}
                      />
                    </td>
                    <td style={{ padding: "8px" }}>
                      <input
                        type="number"
                        step="100"
                        min="256"
                        max="8192"
                        value={cfg.max_output_tokens}
                        onChange={(e) => {
                          const updated = { ...agentsConfig };
                          updated.agents[role].max_output_tokens = parseInt(e.target.value, 10) || 1024;
                          setAgentsConfig(updated);
                        }}
                        style={{ width: "70px", padding: "4px 6px" }}
                      />
                    </td>
                    <td style={{ padding: "8px" }}>
                      <select
                        value={cfg.fallback_provider || ""}
                        onChange={(e) => {
                          const updated = { ...agentsConfig };
                          updated.agents[role].fallback_provider = e.target.value || null;
                          setAgentsConfig(updated);
                        }}
                        style={{ padding: "4px 6px" }}
                      >
                        <option value="">None</option>
                        <option value="openai">OpenAI</option>
                        <option value="google">Google Gemini</option>
                      </select>
                    </td>
                    <td style={{ padding: "8px" }}>
                      <input
                        type="text"
                        value={cfg.fallback_model_id || ""}
                        placeholder="Fallback Model"
                        onChange={(e) => {
                          const updated = { ...agentsConfig };
                          updated.agents[role].fallback_model_id = e.target.value || null;
                          setAgentsConfig(updated);
                        }}
                        style={{ width: "130px", padding: "4px 6px" }}
                      />
                    </td>
                    <td style={{ padding: "8px", textAlign: "center" }}>
                      <input
                        type="checkbox"
                        checked={cfg.enabled}
                        onChange={(e) => {
                          const updated = { ...agentsConfig };
                          updated.agents[role].enabled = e.target.checked;
                          setAgentsConfig(updated);
                        }}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {/* QUANTITATIVE MODEL STUDIO: CONTROLLED MODEL COMPARISON */}
      <section style={{ marginTop: "32px", background: "var(--card-bg, #1e1e24)", border: "1px solid var(--border-color, #333)", borderRadius: "8px", padding: "20px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
          <div>
            <h2 style={{ margin: 0, fontSize: "20px" }}>Forecast Model Studio: Controlled Model Comparison</h2>
            <p style={{ margin: "4px 0 0 0", fontSize: "13px", color: "var(--text-muted, #aaa)" }}>
              Chronological walk-forward evaluation preventing look-ahead leakage. Strict baseline comparisons.
            </p>
          </div>
          <button type="button" className="primary" onClick={runModelComparison} disabled={compBusy} style={{ padding: "8px 16px" }}>
            {compBusy ? "Evaluating Folds..." : "Run Multi-Model Comparison (NIFTY)"}
          </button>
        </div>

        {compResult ? (
          <div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "12px", marginBottom: "16px" }}>
              <div style={{ background: "#25252b", padding: "12px", borderRadius: "6px" }}>
                <span style={{ fontSize: "12px", color: "#888" }}>Instrument Target</span>
                <p style={{ margin: "4px 0 0 0", fontWeight: "bold" }}>{compResult.symbol} (Target: {compResult.target})</p>
              </div>
              <div style={{ background: "#25252b", padding: "12px", borderRadius: "6px" }}>
                <span style={{ fontSize: "12px", color: "#888" }}>Chronological Splits</span>
                <p style={{ margin: "4px 0 0 0", fontWeight: "bold" }}>{compResult.n_splits} Walk-Forward Folds</p>
              </div>
              <div style={{ background: "#25252b", padding: "12px", borderRadius: "6px" }}>
                <span style={{ fontSize: "12px", color: "#888" }}>Lookahead Leakage Guard</span>
                <p style={{ margin: "4px 0 0 0", fontWeight: "bold", color: compResult.lookahead_leakage_prevented ? "#4caf50" : "#f44336" }}>
                  {compResult.lookahead_leakage_prevented ? "Verified Enforced" : "Warning"}
                </p>
              </div>
            </div>

            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid #444", textAlign: "left" }}>
                  <th style={{ padding: "8px" }}>Model</th>
                  <th style={{ padding: "8px" }}>Mean Directional Accuracy</th>
                  <th style={{ padding: "8px" }}>Mean Balanced Accuracy</th>
                  <th style={{ padding: "8px" }}>Mean Brier Score</th>
                  <th style={{ padding: "8px" }}>Baseline Comparison</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(compResult.model_evaluations || {}).map(([mName, evalData]) => (
                  <tr key={mName} style={{ borderBottom: "1px solid #2a2a30" }}>
                    <td style={{ padding: "8px", fontWeight: "bold" }}>
                      {mName.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                    </td>
                    <td style={{ padding: "8px" }}>
                      {(evalData.mean_directional_accuracy * 100).toFixed(1)}%
                    </td>
                    <td style={{ padding: "8px" }}>
                      {(evalData.mean_balanced_accuracy * 100).toFixed(1)}%
                    </td>
                    <td style={{ padding: "8px" }}>
                      {evalData.mean_brier_score !== null ? evalData.mean_brier_score.toFixed(4) : "—"}
                    </td>
                    <td style={{ padding: "8px" }}>
                      {compResult.baseline_comparisons && compResult.baseline_comparisons[mName] ? (
                        <span>
                          vs Majority: {(compResult.baseline_comparisons[mName].accuracy_vs_majority_diff * 100).toFixed(1)}% | vs Last Return: {(compResult.baseline_comparisons[mName].accuracy_vs_last_return_diff * 100).toFixed(1)}%
                        </span>
                      ) : "Baseline Anchor"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p style={{ fontSize: "13px", color: "var(--text-muted, #888)", margin: "8px 0" }}>
            Click &ldquo;Run Multi-Model Comparison&rdquo; to execute an expanding-window chronological walk-forward benchmark across Majority Class, Last Return Sign, and Logistic Regression models.
          </p>
        )}
      </section>

      {/* GROWW DIAGNOSTICS */}
      {groww && ready ? (
        <section id="groww-diagnostics" className="diagnostics" style={{ marginTop: "32px" }}>
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

      {/* MODALS */}
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

      {panel === "upstox" && upstoxDraft ? (
        <div className="modal-backdrop" onClick={closePanel}>
          <form className="modal" role="dialog" aria-labelledby="upstox-settings-title" onClick={(event) => event.stopPropagation()} onSubmit={saveUpstox}>
            <div className="section-head">
              <h2 id="upstox-settings-title">Configure Upstox API v2</h2>
              <button type="button" onClick={closePanel}>Close</button>
            </div>
            <button type="button" className={`switch ${upstoxDraft.enabled ? "on" : ""}`} onClick={() => setUpstoxDraft({ ...upstoxDraft, enabled: !upstoxDraft.enabled })}>
              <span>Integration <small>{upstoxDraft.enabled ? "Enabled" : "Disabled"} · live trading stays off</small></span>
              <span className="knob" aria-hidden="true"><span /></span>
            </button>
            <div className="status-line"><span>Access Token</span><b>{secretIndicator(upstox.access_token_configured)}</b></div>
            <label>
              Replace Access Token
              <input type="password" autoComplete="off" value={upstoxDraft.accessToken} placeholder={upstox.access_token_configured ? "Saved · hidden" : "Enter Upstox access token"} onChange={(e) => setUpstoxDraft({ ...upstoxDraft, accessToken: e.target.value })} />
            </label>
            <label>
              Label
              <input value={upstoxDraft.label} onChange={(e) => setUpstoxDraft({ ...upstoxDraft, label: e.target.value })} />
            </label>
            <div className="actions">
              <button className="primary" type="submit" disabled={Boolean(busy)}>Save changes</button>
              <button type="button" onClick={() => send("/api/integrations/upstox/test")} disabled={Boolean(busy) || !upstox.enabled}>Test connection</button>
            </div>
          </form>
        </div>
      ) : null}

      {panel === "kite" && kiteDraft ? (
        <div className="modal-backdrop" onClick={closePanel}>
          <form className="modal" role="dialog" aria-labelledby="kite-settings-title" onClick={(event) => event.stopPropagation()} onSubmit={saveKite}>
            <div className="section-head">
              <h2 id="kite-settings-title">Configure Zerodha Kite Connect</h2>
              <button type="button" onClick={closePanel}>Close</button>
            </div>
            <button type="button" className={`switch ${kiteDraft.enabled ? "on" : ""}`} onClick={() => setKiteDraft({ ...kiteDraft, enabled: !kiteDraft.enabled })}>
              <span>Integration <small>{kiteDraft.enabled ? "Enabled" : "Disabled"} · live trading stays off</small></span>
              <span className="knob" aria-hidden="true"><span /></span>
            </button>
            <div className="status-line"><span>API Key</span><b>{secretIndicator(kite.api_key_configured)}</b></div>
            <label>
              Replace API Key
              <input type="password" autoComplete="off" value={kiteDraft.apiKey} placeholder={kite.api_key_configured ? "Saved · hidden" : "Enter Kite API Key"} onChange={(e) => setKiteDraft({ ...kiteDraft, apiKey: e.target.value })} />
            </label>
            <div className="status-line"><span>Access Token</span><b>{secretIndicator(kite.access_token_configured)}</b></div>
            <label>
              Replace Access Token
              <input type="password" autoComplete="off" value={kiteDraft.accessToken} placeholder={kite.access_token_configured ? "Saved · hidden" : "Enter Kite Access Token"} onChange={(e) => setKiteDraft({ ...kiteDraft, accessToken: e.target.value })} />
            </label>
            <label>
              Label
              <input value={kiteDraft.label} onChange={(e) => setKiteDraft({ ...kiteDraft, label: e.target.value })} />
            </label>
            <div className="actions">
              <button className="primary" type="submit" disabled={Boolean(busy)}>Save changes</button>
              <button type="button" onClick={() => send("/api/integrations/kite/test")} disabled={Boolean(busy) || !kite.enabled}>Test connection</button>
            </div>
          </form>
        </div>
      ) : null}

      {panel === "angelone" && angeloneDraft ? (
        <div className="modal-backdrop" onClick={closePanel}>
          <form className="modal" role="dialog" aria-labelledby="angelone-settings-title" onClick={(event) => event.stopPropagation()} onSubmit={saveAngelOne}>
            <div className="section-head">
              <h2 id="angelone-settings-title">Configure Angel One SmartAPI</h2>
              <button type="button" onClick={closePanel}>Close</button>
            </div>
            <button type="button" className={`switch ${angeloneDraft.enabled ? "on" : ""}`} onClick={() => setAngeloneDraft({ ...angeloneDraft, enabled: !angeloneDraft.enabled })}>
              <span>Integration <small>{angeloneDraft.enabled ? "Enabled" : "Disabled"} · live trading stays off</small></span>
              <span className="knob" aria-hidden="true"><span /></span>
            </button>
            <div className="status-line"><span>API Key</span><b>{secretIndicator(angelone.api_key_configured)}</b></div>
            <label>
              Replace API Key
              <input type="password" autoComplete="off" value={angeloneDraft.apiKey} placeholder={angelone.api_key_configured ? "Saved · hidden" : "Enter Angel One API Key"} onChange={(e) => setAngeloneDraft({ ...angeloneDraft, apiKey: e.target.value })} />
            </label>
            <div className="status-line"><span>Client Code</span><b>{angelone.client_code ? "Saved" : "Missing"}</b></div>
            <label>
              Client Code
              <input type="text" value={angeloneDraft.clientCode} placeholder={angelone.client_code || "e.g. S123456"} onChange={(e) => setAngeloneDraft({ ...angeloneDraft, clientCode: e.target.value })} />
            </label>
            <div className="status-line"><span>JWT Token</span><b>{secretIndicator(angelone.jwt_token_configured)}</b></div>
            <label>
              Replace JWT Token
              <input type="password" autoComplete="off" value={angeloneDraft.jwtToken} placeholder={angelone.jwt_token_configured ? "Saved · hidden" : "Enter JWT Token"} onChange={(e) => setAngeloneDraft({ ...angeloneDraft, jwtToken: e.target.value })} />
            </label>
            <label>
              Label
              <input value={angeloneDraft.label} onChange={(e) => setAngeloneDraft({ ...angeloneDraft, label: e.target.value })} />
            </label>
            <div className="actions">
              <button className="primary" type="submit" disabled={Boolean(busy)}>Save changes</button>
              <button type="button" onClick={() => send("/api/integrations/angelone/test")} disabled={Boolean(busy) || !angelone.enabled}>Test connection</button>
            </div>
          </form>
        </div>
      ) : null}

      {panel === "gemini" && geminiDraft ? (
        <div className="modal-backdrop" onClick={closePanel}>
          <form className="modal" role="dialog" aria-labelledby="gemini-settings-title" onClick={(event) => event.stopPropagation()} onSubmit={saveGemini}>
            <div className="section-head">
              <h2 id="gemini-settings-title">Configure Google Gemini</h2>
              <button type="button" onClick={closePanel}>Close</button>
            </div>
            <button type="button" className={`switch ${geminiDraft.enabled ? "on" : ""}`} onClick={() => setGeminiDraft({ ...geminiDraft, enabled: !geminiDraft.enabled })}>
              <span>Integration <small>{geminiDraft.enabled ? "Enabled" : "Disabled"}</small></span>
              <span className="knob" aria-hidden="true"><span /></span>
            </button>
            <div className="status-line"><span>API key</span><b>{secretIndicator(gemini.api_key_configured)}</b></div>
            <label>
              Replace API key
              <input type="password" autoComplete="off" value={geminiDraft.apiKey} placeholder={gemini.api_key_configured ? "Saved · hidden" : "Enter Gemini API key"} onChange={(e) => setGeminiDraft({ ...geminiDraft, apiKey: e.target.value })} />
            </label>
            <label>
              Model
              <select value={geminiDraft.model} onChange={(e) => setGeminiDraft({ ...geminiDraft, model: e.target.value })}>
                {GEMINI_MODELS.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </label>
            <label>
              Label
              <input value={geminiDraft.label} onChange={(e) => setGeminiDraft({ ...geminiDraft, label: e.target.value })} />
            </label>
            <div className="actions">
              <button className="primary" type="submit" disabled={Boolean(busy)}>Save changes</button>
              <button type="button" onClick={() => send("/api/integrations/gemini/test")} disabled={Boolean(busy) || !gemini.enabled}>Test connection</button>
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
