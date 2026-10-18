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
  lifecycleKind,
  lifecycleLabel,
  openaiSavePlan,
  safetySummary,
  secretIndicator,
  wallSpanMinutes,
} from "./labels.mjs";

function csrf() {
  const match = document.cookie.match(/(?:^|; )imm_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

const MASK_VALUE = "••••••••••••••••";
const hasMask = (val) => Boolean(val && (val.includes("•") || val.includes("\u2022")));
const isNewSecret = (val) => Boolean(val && val.trim() && !hasMask(val));

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

const DEFAULT_OPENAI_MODELS = [
  { id: "gpt-4o", label: "gpt-4o (Omni Flagship · High Intelligence)" },
  { id: "gpt-4o-mini", label: "gpt-4o-mini (Fast & Cost Efficient)" },
  { id: "o1", label: "o1 (Deep Reasoning & Complex Analysis)" },
  { id: "o1-mini", label: "o1-mini (Fast Reasoning)" },
  { id: "o1-preview", label: "o1-preview (Advanced Reasoning Preview)" },
  { id: "gpt-4-turbo", label: "gpt-4-turbo (High Capability)" },
  { id: "gpt-4", label: "gpt-4 (Legacy Baseline)" },
  { id: "gpt-3.5-turbo", label: "gpt-3.5-turbo (Legacy Speed)" },
];

const DEFAULT_GEMINI_MODELS = [
  { id: "gemini-flash-latest", label: "gemini-flash-latest (Recommended Live Flash)" },
  { id: "gemini-flash-lite-latest", label: "gemini-flash-lite-latest (High-Speed / High-Quota Lite)" },
  { id: "gemini-3.8-flash", label: "gemini-3.8-flash (Latest Generation Flash)" },
  { id: "gemini-3.1-flash-lite", label: "gemini-3.1-flash-lite (Fast Low-Latency Lite)" },
  { id: "gemini-2.5-pro", label: "gemini-2.5-pro (Flagship Reasoning & Code)" },
  { id: "gemini-2.5-flash", label: "gemini-2.5-flash (Fast, Highly Capable)" },
  { id: "gemini-2.0-flash", label: "gemini-2.0-flash (High-Speed Multimodal)" },
  { id: "gemini-2.0-flash-lite", label: "gemini-2.0-flash-lite (Ultra Lightweight)" },
  { id: "gemini-1.5-pro", label: "gemini-1.5-pro (Long Context)" },
  { id: "gemini-1.5-flash", label: "gemini-1.5-flash (Legacy Fast)" },
  { id: "gemini-1.5-flash-8b", label: "gemini-1.5-flash-8b (High Volume / Low Cost)" },
];
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
  const [confirmClearProvider, setConfirmClearProvider] = useState(null);
  const [diagStart, setDiagStart] = useState(DEFAULT_START);
  const [diagEnd, setDiagEnd] = useState(DEFAULT_END);
  const [diagConfirm, setDiagConfirm] = useState(false);
  const [diagResult, setDiagResult] = useState(null);
  const [openaiModels, setOpenaiModels] = useState(DEFAULT_OPENAI_MODELS);
  const [geminiModels, setGeminiModels] = useState(DEFAULT_GEMINI_MODELS);
  const [loadingModels, setLoadingModels] = useState(false);
  const [modelsStatusMessage, setModelsStatusMessage] = useState("");

  async function refreshModels(provider, apiKey = "") {
    setLoadingModels(true);
    setModelsStatusMessage(`Querying live ${provider === "openai" ? "OpenAI" : "Google Gemini"} models...`);
    try {
      const res = await fetch(`/api/integrations/${provider}/models`, {
        method: "POST",
        headers: { "content-type": "application/json", "x-csrf-token": csrf() },
        body: JSON.stringify({ api_key: apiKey }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data && Array.isArray(data.models)) {
          if (provider === "openai") setOpenaiModels(data.models);
          if (provider === "gemini") setGeminiModels(data.models);
          setModelsStatusMessage(data.message || (data.source === "live" ? "Live models loaded" : "Catalog loaded"));
          return data.models;
        }
      }
    } catch (e) {
      console.warn("Failed to fetch models for", provider, e);
      setModelsStatusMessage(`Could not query live ${provider} models; showing catalog.`);
    } finally {
      setLoadingModels(false);
    }
    return null;
  }

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
      const method = path.endsWith("/test") || path.endsWith("/clear") || path.endsWith("/disconnect") || path.endsWith("/enabled") || path.endsWith("/profile") || path.endsWith("/historical-diagnostic") ? "POST" : "PUT";
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
      else if (path.endsWith("/disconnect")) setNotice("Provider disconnected. Active synchronization stopped; credentials retained.");
      else if (path.endsWith("/enabled")) setNotice(payload?.enabled ? "Integration enabled. Live trading stays off." : "Integration disabled.");
      else if (!path.endsWith("/historical-diagnostic")) setNotice("Settings saved.");
      return body;
    } finally {
      setBusy("");
    }
  }

  async function disconnectProvider(provider) {
    await send(`/api/integrations/${provider}/disconnect`);
  }

  async function connectProvider(provider) {
    await send(`/api/integrations/${provider}/enabled`, { enabled: true, confirm: true });
  }

  async function removeProvider(provider) {
    const res = await send(`/api/integrations/${provider}/clear`);
    if (res) {
      setConfirmClearProvider(null);
    }
  }

  function openGroww() {
    setError("");
    const groww = status?.groww;
    if (!groww) return;
    setGrowwDraft({
      method: groww.auth_method || "totp",
      enabled: groww.enabled === true,
      apiKey: groww.api_key_configured ? MASK_VALUE : "",
      apiSecret: groww.api_secret_configured ? MASK_VALUE : "",
      accessToken: groww.access_token_configured ? MASK_VALUE : "",
      totpSecret: groww.totp_secret_configured ? MASK_VALUE : "",
    });
    setConfirmEnable(false);
    setConfirmClear(false);
    setPanel("groww");
  }

  function openOpenAI() {
    setError("");
    const openai = status?.openai;
    if (!openai) return;
    setOpenaiDraft({
      model: openai.model || "gpt-4o-mini",
      label: openai.label || "",
      enabled: openai.enabled === true,
      apiKey: openai.api_key_configured ? MASK_VALUE : "",
    });
    setConfirmEnable(false);
    setPanel("openai");
    setModelsStatusMessage("");
    refreshModels("openai", "");
  }

  function openUpstox() {
    setError("");
    const upstox = status?.upstox;
    if (!upstox) return;
    setUpstoxDraft({
      enabled: upstox.enabled === true,
      accessToken: upstox.access_token_configured ? MASK_VALUE : "",
      label: upstox.label || "",
    });
    setConfirmEnable(false);
    setPanel("upstox");
  }

  function openKite() {
    setError("");
    const kite = status?.kite;
    if (!kite) return;
    setKiteDraft({
      enabled: kite.enabled === true,
      apiKey: kite.api_key_configured ? MASK_VALUE : "",
      accessToken: kite.access_token_configured ? MASK_VALUE : "",
      label: kite.label || "",
    });
    setConfirmEnable(false);
    setPanel("kite");
  }

  function openAngelOne() {
    setError("");
    const angelone = status?.angelone;
    if (!angelone) return;
    setAngeloneDraft({
      enabled: angelone.enabled === true,
      apiKey: angelone.api_key_configured ? MASK_VALUE : "",
      clientCode: angelone.client_code || "",
      jwtToken: angelone.jwt_token_configured ? MASK_VALUE : "",
      label: angelone.label || "",
    });
    setConfirmEnable(false);
    setPanel("angelone");
  }

  function openGemini() {
    setError("");
    const gemini = status?.gemini;
    if (!gemini) return;
    setGeminiDraft({
      enabled: gemini.enabled === true,
      apiKey: gemini.api_key_configured ? MASK_VALUE : "",
      model: gemini.model || "gemini-2.5-flash",
      label: gemini.label || "",
      customModelActive: !DEFAULT_GEMINI_MODELS.some(m => m.id === (gemini.model || "gemini-2.5-flash")),
    });
    setConfirmEnable(false);
    setPanel("gemini");
    setModelsStatusMessage("");
    refreshModels("gemini", "");
  }

  function closePanel() {
    setPanel(null);
    setConfirmEnable(false);
    setConfirmClear(false);
    setError("");
  }

  async function saveGroww(event) {
    event.preventDefault();
    const groww = status.groww;
    const hasNewSecrets = [growwDraft.apiKey, growwDraft.apiSecret, growwDraft.accessToken, growwDraft.totpSecret].some(isNewSecret);
    const plan = growwSavePlan({
      method: growwDraft.method,
      savedMethod: groww.auth_method || "totp",
      enabled: growwDraft.enabled,
      savedEnabled: groww.enabled === true,
      secretsEntered: hasNewSecrets,
      confirmEnable,
    });
    if (plan.blocked === "UNCHANGED") {
      closePanel();
      return;
    }
    if (plan.blocked === "CREDENTIALS_REQUIRED") {
      const methodConfigured = (growwDraft.method === "totp" && groww.totp_secret_configured && groww.api_key_configured) ||
                               (growwDraft.method === "api_key_secret" && groww.api_secret_configured && groww.api_key_configured) ||
                               (growwDraft.method === "access_token" && groww.access_token_configured);
      if (!methodConfigured && !hasNewSecrets) {
        setError("Local check: enter the credentials for the selected authentication method before saving.");
        return;
      }
    }
    if (plan.blocked === "CONFIRMATION_REQUIRED") {
      setConfirmEnable(true);
      return;
    }
    if (plan.steps.includes("save-credentials") || hasNewSecrets || growwDraft.method !== (groww.auth_method || "totp")) {
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
    if (plan.steps.includes("set-enabled") || growwDraft.enabled !== (groww.enabled === true)) {
      const saved = await send("/api/integrations/groww/enabled", { enabled: growwDraft.enabled, confirm: true });
      if (!saved) return;
    }
    closePanel();
  }

  async function testGrowwInModal() {
    const hasNewSecrets = [growwDraft.apiKey, growwDraft.apiSecret, growwDraft.accessToken, growwDraft.totpSecret].some(isNewSecret);
    if (hasNewSecrets) {
      const payload = { method: growwDraft.method, label: status.groww?.label || "" };
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
    if (!status.groww?.enabled) {
      await send("/api/integrations/groww/enabled", { enabled: true, confirm: true });
    }
    await send("/api/integrations/groww/test");
  }

  async function saveOpenAI(event) {
    event.preventDefault();
    const openai = status.openai;
    const keyEntered = isNewSecret(openaiDraft.apiKey);
    if (!openai.configured && !keyEntered) {
      setError("Enter an OpenAI API key before saving.");
      return;
    }
    if (keyEntered) {
      const saved = await send("/api/integrations/openai", {
        api_key: openaiDraft.apiKey,
        model: openaiDraft.model,
        label: openaiDraft.label,
        enabled: openaiDraft.enabled === true,
      });
      if (!saved) return;
    } else {
      if (openaiDraft.model !== (openai.model || "") || openaiDraft.label !== (openai.label || "")) {
        const saved = await send("/api/integrations/openai/profile", {
          model: openaiDraft.model,
          label: openaiDraft.label,
          confirm: true,
        });
        if (!saved) return;
      }
      if (openaiDraft.enabled !== (openai.enabled === true)) {
        if (!confirmEnable) {
          setConfirmEnable(true);
          return;
        }
        const saved = await send("/api/integrations/openai/enabled", { enabled: openaiDraft.enabled, confirm: true });
        if (!saved) return;
      }
    }
    closePanel();
  }

  async function testOpenAIInModal() {
    const keyEntered = isNewSecret(openaiDraft.apiKey);
    if (keyEntered) {
      const saved = await send("/api/integrations/openai", {
        api_key: openaiDraft.apiKey,
        model: openaiDraft.model,
        label: openaiDraft.label,
        enabled: true,
      });
      if (!saved) return;
      setOpenaiDraft((prev) => ({ ...prev, enabled: true, apiKey: MASK_VALUE }));
    } else {
      if (!status.openai?.enabled) {
        const saved = await send("/api/integrations/openai/enabled", { enabled: true, confirm: true });
        if (!saved) return;
      }
      if (openaiDraft.model !== (status.openai?.model || "gpt-4o-mini")) {
        const saved = await send("/api/integrations/openai/profile", {
          model: openaiDraft.model,
          label: openaiDraft.label,
          confirm: true,
        });
        if (!saved) return;
      }
    }
    await send("/api/integrations/openai/test");
  }

  async function saveUpstox(event) {
    event.preventDefault();
    const upstox = status.upstox;
    const tokenEntered = Boolean(upstoxDraft.accessToken.trim());
    if (!upstox.configured && !tokenEntered) {
      setError("Enter an Upstox access token before saving.");
      return;
    }
    if (tokenEntered) {
      const saved = await send("/api/integrations/upstox", {
        access_token: upstoxDraft.accessToken,
        label: upstoxDraft.label,
        enabled: upstoxDraft.enabled === true,
      });
      if (!saved) return;
    } else {
      if (upstoxDraft.label !== (upstox?.label || "")) {
        const saved = await send("/api/integrations/upstox/profile", {
          label: upstoxDraft.label,
          confirm: true,
        });
        if (!saved) return;
      }
      if (upstoxDraft.enabled !== (upstox?.enabled === true)) {
        const saved = await send("/api/integrations/upstox/enabled", {
          enabled: upstoxDraft.enabled,
          confirm: true,
        });
        if (!saved) return;
      }
    }
    closePanel();
  }

  async function testUpstoxInModal() {
    const tokenEntered = isNewSecret(upstoxDraft.accessToken);
    if (tokenEntered) {
      const saved = await send("/api/integrations/upstox", {
        access_token: upstoxDraft.accessToken,
        label: upstoxDraft.label,
        enabled: true,
      });
      if (!saved) return;
      setUpstoxDraft((prev) => ({ ...prev, enabled: true, accessToken: MASK_VALUE }));
    } else {
      if (!status.upstox?.enabled) {
        const saved = await send("/api/integrations/upstox/enabled", { enabled: true, confirm: true });
        if (!saved) return;
      }
    }
    await send("/api/integrations/upstox/test");
  }

  async function saveKite(event) {
    event.preventDefault();
    const kite = status.kite;
    const credsEntered = isNewSecret(kiteDraft.apiKey) || isNewSecret(kiteDraft.accessToken);
    if (!kite.configured && !credsEntered) {
      setError("Enter Kite API Key and Access Token before saving.");
      return;
    }
    if (credsEntered) {
      const saved = await send("/api/integrations/kite", {
        api_key: kiteDraft.apiKey,
        access_token: kiteDraft.accessToken,
        label: kiteDraft.label,
        enabled: kiteDraft.enabled === true,
      });
      if (!saved) return;
    } else {
      if (kiteDraft.label !== (kite?.label || "")) {
        const saved = await send("/api/integrations/kite/profile", {
          label: kiteDraft.label,
          confirm: true,
        });
        if (!saved) return;
      }
      if (kiteDraft.enabled !== (kite?.enabled === true)) {
        const saved = await send("/api/integrations/kite/enabled", {
          enabled: kiteDraft.enabled,
          confirm: true,
        });
        if (!saved) return;
      }
    }
    closePanel();
  }

  async function testKiteInModal() {
    const credsEntered = isNewSecret(kiteDraft.apiKey) || isNewSecret(kiteDraft.accessToken);
    if (credsEntered) {
      const saved = await send("/api/integrations/kite", {
        api_key: kiteDraft.apiKey,
        access_token: kiteDraft.accessToken,
        label: kiteDraft.label,
        enabled: true,
      });
      if (!saved) return;
      setKiteDraft((prev) => ({ ...prev, enabled: true, apiKey: MASK_VALUE, accessToken: MASK_VALUE }));
    } else {
      if (!status.kite?.enabled) {
        const saved = await send("/api/integrations/kite/enabled", { enabled: true, confirm: true });
        if (!saved) return;
      }
    }
    await send("/api/integrations/kite/test");
  }

  async function saveAngelOne(event) {
    event.preventDefault();
    const angelone = status.angelone;
    const credsEntered = isNewSecret(angeloneDraft.apiKey) || isNewSecret(angeloneDraft.jwtToken) || (angeloneDraft.clientCode.trim() && !hasMask(angeloneDraft.clientCode));
    if (!angelone.configured && !credsEntered) {
      setError("Enter Angel One API Key, Client Code, and JWT Token before saving.");
      return;
    }
    if (credsEntered) {
      const saved = await send("/api/integrations/angelone", {
        api_key: angeloneDraft.apiKey,
        client_code: angeloneDraft.clientCode,
        jwt_token: angeloneDraft.jwtToken,
        label: angeloneDraft.label,
        enabled: angeloneDraft.enabled === true,
      });
      if (!saved) return;
    } else {
      if (angeloneDraft.label !== (angelone?.label || "")) {
        const saved = await send("/api/integrations/angelone/profile", {
          label: angeloneDraft.label,
          confirm: true,
        });
        if (!saved) return;
      }
      if (angeloneDraft.enabled !== (angelone?.enabled === true)) {
        const saved = await send("/api/integrations/angelone/enabled", {
          enabled: angeloneDraft.enabled,
          confirm: true,
        });
        if (!saved) return;
      }
    }
    closePanel();
  }

  async function testAngelOneInModal() {
    const credsEntered = isNewSecret(angeloneDraft.apiKey) || isNewSecret(angeloneDraft.jwtToken);
    if (credsEntered) {
      const saved = await send("/api/integrations/angelone", {
        api_key: angeloneDraft.apiKey,
        client_code: angeloneDraft.clientCode,
        jwt_token: angeloneDraft.jwtToken,
        label: angeloneDraft.label,
        enabled: true,
      });
      if (!saved) return;
      setAngeloneDraft((prev) => ({ ...prev, enabled: true, apiKey: MASK_VALUE, jwtToken: MASK_VALUE }));
    } else {
      if (!status.angelone?.enabled) {
        const saved = await send("/api/integrations/angelone/enabled", { enabled: true, confirm: true });
        if (!saved) return;
      }
    }
    await send("/api/integrations/angelone/test");
  }

  async function saveGemini(event) {
    if (event) event.preventDefault();
    const gemini = status.gemini;
    const keyEntered = isNewSecret(geminiDraft.apiKey);
    if (!gemini.configured && !keyEntered) {
      setError("Enter a Gemini API key before saving.");
      return;
    }
    if (keyEntered) {
      const saved = await send("/api/integrations/gemini", {
        api_key: geminiDraft.apiKey,
        model: geminiDraft.model,
        label: geminiDraft.label,
        enabled: geminiDraft.enabled === true,
      });
      if (!saved) return;
    } else {
      if (geminiDraft.model !== (gemini?.model || "gemini-2.5-flash") || geminiDraft.label !== (gemini?.label || "")) {
        const saved = await send("/api/integrations/gemini/profile", {
          model: geminiDraft.model,
          label: geminiDraft.label,
          confirm: true,
        });
        if (!saved) return;
      }
      if (geminiDraft.enabled !== (gemini?.enabled === true)) {
        const saved = await send("/api/integrations/gemini/enabled", {
          enabled: geminiDraft.enabled,
          confirm: true,
        });
        if (!saved) return;
      }
    }
    closePanel();
  }

  async function testGeminiInModal() {
    const keyEntered = isNewSecret(geminiDraft.apiKey);
    if (keyEntered) {
      const saved = await send("/api/integrations/gemini", {
        api_key: geminiDraft.apiKey,
        model: geminiDraft.model,
        label: geminiDraft.label,
        enabled: true,
      });
      if (!saved) return;
      setGeminiDraft((prev) => ({ ...prev, enabled: true, apiKey: MASK_VALUE }));
    } else {
      if (!status.gemini?.enabled) {
        const saved = await send("/api/integrations/gemini/enabled", { enabled: true, confirm: true });
        if (!saved) return;
      }
      if (geminiDraft.model !== (status.gemini?.model || "gemini-2.5-flash")) {
        const saved = await send("/api/integrations/gemini/profile", {
          model: geminiDraft.model,
          label: geminiDraft.label,
          confirm: true,
        });
        if (!saved) return;
      }
    }
    await send("/api/integrations/gemini/test");
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
                lifecycleState={groww.lifecycle_state}
                capabilities={groww.capabilities}
                lastError={groww.last_test_ok === false ? groww.last_test_message : ""}
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
                onTest={async () => {
                  setError("");
                  if (!groww.enabled) {
                    const enabled = await send("/api/integrations/groww/enabled", { enabled: true, confirm: true });
                    if (!enabled) return;
                  }
                  await send("/api/integrations/groww/test");
                }}
                onConnect={() => connectProvider("groww")}
                onDisconnect={() => disconnectProvider("groww")}
                onRemove={() => setConfirmClearProvider("groww")}
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
                lifecycleState={kite.lifecycle_state}
                capabilities={kite.capabilities}
                lastError={kite.last_test_ok === false ? kite.last_test_message : ""}
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
                onTest={async () => {
                  if (!kite.enabled) {
                    const enabled = await send("/api/integrations/kite/enabled", { enabled: true, confirm: true });
                    if (!enabled) return;
                  }
                  await send("/api/integrations/kite/test");
                }}
                onConnect={() => connectProvider("kite")}
                onDisconnect={() => disconnectProvider("kite")}
                onRemove={() => setConfirmClearProvider("kite")}
                testDisabled={!kite.configured}
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
                lifecycleState={upstox.lifecycle_state}
                capabilities={upstox.capabilities}
                lastError={upstox.last_test_ok === false ? upstox.last_test_message : ""}
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
                onTest={async () => {
                  if (!upstox.enabled) {
                    const enabled = await send("/api/integrations/upstox/enabled", { enabled: true, confirm: true });
                    if (!enabled) return;
                  }
                  await send("/api/integrations/upstox/test");
                }}
                onConnect={() => connectProvider("upstox")}
                onDisconnect={() => disconnectProvider("upstox")}
                onRemove={() => setConfirmClearProvider("upstox")}
                testDisabled={!upstox.configured}
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
                lifecycleState={angelone.lifecycle_state}
                capabilities={angelone.capabilities}
                lastError={angelone.last_test_ok === false ? angelone.last_test_message : ""}
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
                onTest={async () => {
                  if (!angelone.enabled) {
                    const enabled = await send("/api/integrations/angelone/enabled", { enabled: true, confirm: true });
                    if (!enabled) return;
                  }
                  await send("/api/integrations/angelone/test");
                }}
                onConnect={() => connectProvider("angelone")}
                onDisconnect={() => disconnectProvider("angelone")}
                onRemove={() => setConfirmClearProvider("angelone")}
                testDisabled={!angelone.configured}
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
                lifecycleState={openai.lifecycle_state}
                capabilities={openai.capabilities}
                lastError={openai.last_test_ok === false ? openai.last_test_message : ""}
                facts={[
                  ["Last test", `${connectionLabel(openai.last_test_ok)} · ${when(openai.last_test_at)}`],
                  ["Model", openai.model || "None"],
                ]}
                detailsTitle="Connection details"
                details={`${openai.connectivity?.endpoint || "api.openai.com"}. ${openai.connectivity?.does_not_prove || ""}`}
                busy={busy}
                onConfigure={openOpenAI}
                onTest={async () => {
                  if (!openai.enabled) {
                    const enabled = await send("/api/integrations/openai/enabled", { enabled: true, confirm: true });
                    if (!enabled) return;
                  }
                  await send("/api/integrations/openai/test");
                }}
                onConnect={() => connectProvider("openai")}
                onDisconnect={() => disconnectProvider("openai")}
                onRemove={() => setConfirmClearProvider("openai")}
                testDisabled={!openai.configured}
              />
            ) : null}

            {gemini ? (
              <ProviderCard
                mark={<GeminiMark />}
                name="Google Gemini"
                detail={gemini.model || "gemini-2.5-flash"}
                enabled={gemini.enabled}
                configured={gemini.configured}
                connection={gemini.last_test_ok}
                lifecycleState={gemini.lifecycle_state}
                capabilities={gemini.capabilities}
                lastError={gemini.last_test_ok === false ? gemini.last_test_message : ""}
                facts={[
                  ["Last test", `${connectionLabel(gemini.last_test_ok)} · ${when(gemini.last_test_at)}`],
                  ["Model", gemini.model || "gemini-2.5-flash"],
                ]}
                detailsTitle="Connection details"
                details={`${gemini.connectivity?.endpoint || "generativelanguage.googleapis.com"}. Google AI API.`}
                busy={busy}
                onConfigure={openGemini}
                onTest={async () => {
                  if (!gemini.enabled) {
                    const enabled = await send("/api/integrations/gemini/enabled", { enabled: true, confirm: true });
                    if (!enabled) return;
                  }
                  await send("/api/integrations/gemini/test");
                }}
                onConnect={() => connectProvider("gemini")}
                onDisconnect={() => disconnectProvider("gemini")}
                onRemove={() => setConfirmClearProvider("gemini")}
                testDisabled={!gemini.configured}
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
                      {cfg.display_name || role.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                    </td>
                    <td style={{ padding: "8px" }}>
                      <select
                        value={cfg.provider === "google" ? "gemini" : (cfg.provider || "openai")}
                        onChange={(e) => setAgentsConfig((prev) => ({ ...prev, agents: { ...prev.agents, [role]: { ...prev.agents[role], provider: e.target.value } } }))}
                        style={{ padding: "4px 6px" }}
                      >
                        <option value="openai">OpenAI</option>
                        <option value="gemini">Google Gemini</option>
                      </select>
                    </td>
                    <td style={{ padding: "8px" }}>
                      <input
                        type="text"
                        value={cfg.model ?? cfg.model_id ?? ""}
                        onChange={(e) => setAgentsConfig((prev) => ({ ...prev, agents: { ...prev.agents, [role]: { ...prev.agents[role], model: e.target.value } } }))}
                        style={{ width: "130px", padding: "4px 6px" }}
                      />
                    </td>
                    <td style={{ padding: "8px" }}>
                      <input
                        type="number"
                        step="0.05"
                        min="0"
                        max="2"
                        value={cfg.temperature ?? 0}
                        onChange={(e) => setAgentsConfig((prev) => ({ ...prev, agents: { ...prev.agents, [role]: { ...prev.agents[role], temperature: parseFloat(e.target.value) || 0 } } }))}
                        style={{ width: "60px", padding: "4px 6px" }}
                      />
                    </td>
                    <td style={{ padding: "8px" }}>
                      <input
                        type="number"
                        step="100"
                        min="100"
                        max="8000"
                        value={cfg.max_tokens ?? cfg.max_output_tokens ?? 1000}
                        onChange={(e) => setAgentsConfig((prev) => ({ ...prev, agents: { ...prev.agents, [role]: { ...prev.agents[role], max_tokens: parseInt(e.target.value, 10) || 1000 } } }))}
                        style={{ width: "70px", padding: "4px 6px" }}
                      />
                    </td>
                    <td style={{ padding: "8px" }}>
                      <select
                        value={cfg.fallback_provider === "google" ? "gemini" : (cfg.fallback_provider || "")}
                        onChange={(e) => setAgentsConfig((prev) => ({ ...prev, agents: { ...prev.agents, [role]: { ...prev.agents[role], fallback_provider: e.target.value || null } } }))}
                        style={{ padding: "4px 6px" }}
                      >
                        <option value="">None</option>
                        <option value="openai">OpenAI</option>
                        <option value="gemini">Google Gemini</option>
                      </select>
                    </td>
                    <td style={{ padding: "8px" }}>
                      <input
                        type="text"
                        value={cfg.fallback_model ?? cfg.fallback_model_id ?? ""}
                        placeholder="Fallback Model"
                        onChange={(e) => setAgentsConfig((prev) => ({ ...prev, agents: { ...prev.agents, [role]: { ...prev.agents[role], fallback_model: e.target.value || null } } }))}
                        style={{ width: "130px", padding: "4px 6px" }}
                      />
                    </td>
                    <td style={{ padding: "8px", textAlign: "center" }}>
                      <input
                        type="checkbox"
                        checked={Boolean(cfg.enabled)}
                        onChange={(e) => setAgentsConfig((prev) => ({ ...prev, agents: { ...prev.agents, [role]: { ...prev.agents[role], enabled: e.target.checked } } }))}
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
                      {evalData.mean_directional_accuracy != null ? `${(evalData.mean_directional_accuracy * 100).toFixed(1)}%` : "—"}
                    </td>
                    <td style={{ padding: "8px" }}>
                      {evalData.mean_balanced_accuracy != null ? `${(evalData.mean_balanced_accuracy * 100).toFixed(1)}%` : "—"}
                    </td>
                    <td style={{ padding: "8px" }}>
                      {evalData.mean_brier_score != null ? evalData.mean_brier_score.toFixed(4) : "—"}
                    </td>
                    <td style={{ padding: "8px" }}>
                      {compResult.baseline_comparisons && compResult.baseline_comparisons[mName] ? (
                        <span>
                          vs Majority: {compResult.baseline_comparisons[mName].accuracy_vs_majority_diff != null ? `${(compResult.baseline_comparisons[mName].accuracy_vs_majority_diff * 100).toFixed(1)}%` : "—"} | vs Last Return: {compResult.baseline_comparisons[mName].accuracy_vs_last_return_diff != null ? `${(compResult.baseline_comparisons[mName].accuracy_vs_last_return_diff * 100).toFixed(1)}%` : "—"}
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
                API key {groww.api_key_configured ? <span style={{ fontSize: "0.75rem", color: "var(--muted)", fontWeight: "normal" }}>(masked)</span> : null}
                <input
                  type="password"
                  autoComplete="off"
                  value={growwDraft.apiKey}
                  placeholder={groww.api_key_configured ? "Saved · masked" : "Enter API key"}
                  onFocus={(e) => { if (e.target.value.includes("•")) e.target.select(); }}
                  onChange={(event) => setGrowwDraft({ ...growwDraft, apiKey: event.target.value })}
                />
              </label>
            ) : null}
            <div className="status-line"><span>API secret</span><b>{secretIndicator(groww.api_secret_configured)}</b></div>
            {growwDraft.method === "api_key_secret" ? (
              <label>
                API secret {groww.api_secret_configured ? <span style={{ fontSize: "0.75rem", color: "var(--muted)", fontWeight: "normal" }}>(masked)</span> : null}
                <input
                  type="password"
                  autoComplete="off"
                  value={growwDraft.apiSecret}
                  placeholder={groww.api_secret_configured ? "Saved · masked" : "Enter API secret"}
                  onFocus={(e) => { if (e.target.value.includes("•")) e.target.select(); }}
                  onChange={(event) => setGrowwDraft({ ...growwDraft, apiSecret: event.target.value })}
                />
              </label>
            ) : null}
            <div className="status-line"><span>Access token</span><b>{secretIndicator(groww.access_token_configured)}</b></div>
            <div className="status-line"><span>Token expiry</span><b>{groww.token_status?.display_ist || "Not available"} · {expiryLabel(groww.token_status?.status)}</b></div>
            {growwDraft.method === "access_token" ? (
              <label>
                Access token {groww.access_token_configured ? <span style={{ fontSize: "0.75rem", color: "var(--muted)", fontWeight: "normal" }}>(masked)</span> : null}
                <input
                  type="password"
                  autoComplete="off"
                  value={growwDraft.accessToken}
                  placeholder={groww.access_token_configured ? "Saved · masked" : "Enter access token"}
                  onFocus={(e) => { if (e.target.value.includes("•")) e.target.select(); }}
                  onChange={(event) => setGrowwDraft({ ...growwDraft, accessToken: event.target.value })}
                />
              </label>
            ) : null}
            <div className="status-line"><span>TOTP secret</span><b>{secretIndicator(groww.totp_secret_configured)}</b></div>
            {growwDraft.method === "totp" ? (
              <label>
                TOTP secret {groww.totp_secret_configured ? <span style={{ fontSize: "0.75rem", color: "var(--muted)", fontWeight: "normal" }}>(masked)</span> : null}
                <input
                  type="password"
                  autoComplete="off"
                  value={growwDraft.totpSecret}
                  placeholder={groww.totp_secret_configured ? "Saved · masked" : "Enter TOTP secret"}
                  onFocus={(e) => { if (e.target.value.includes("•")) e.target.select(); }}
                  onChange={(event) => setGrowwDraft({ ...growwDraft, totpSecret: event.target.value })}
                />
              </label>
            ) : null}
            {confirmEnable ? <p className="note">Confirm to {growwDraft.enabled ? "enable" : "disable"} Groww. Enabling lets the app use stored credentials. Live trading stays off, and endpoint access is not guaranteed.</p> : null}
            <p className="note" style={{ fontSize: "0.8rem", color: "var(--muted)", margin: "8px 0" }}>
              💡 <strong>Disconnect vs Remove:</strong> Disconnect suspends active synchronization while keeping your encrypted credentials safe for later reconnection. Remove permanently deletes all stored credentials.
            </p>
            <div className="actions">
              <button className="primary" type="submit" disabled={Boolean(busy)}>{confirmEnable ? "Confirm and save" : "Save changes"}</button>
              <button
                type="button"
                onClick={testGrowwInModal}
                disabled={Boolean(busy) || (!groww.configured && ![growwDraft.apiKey, growwDraft.apiSecret, growwDraft.accessToken, growwDraft.totpSecret].some((v) => v.trim()))}
                title={(!groww.configured && ![growwDraft.apiKey, growwDraft.apiSecret, growwDraft.accessToken, growwDraft.totpSecret].some((v) => v.trim())) ? "Enter credentials first" : "Save and test Groww margin connection"}
              >
                Test connection
              </button>
              {groww.enabled ? (
                <button
                  type="button"
                  onClick={async () => {
                    await disconnectProvider("groww");
                    closePanel();
                  }}
                  disabled={Boolean(busy)}
                >
                  Disconnect
                </button>
              ) : null}
              {groww.configured ? (
                <button
                  className="danger"
                  type="button"
                  onClick={async () => {
                    if (!confirmClear) { setConfirmClear(true); return; }
                    if (await send("/api/integrations/groww/clear")) closePanel();
                  }}
                  disabled={Boolean(busy)}
                >
                  {confirmClear ? "Confirm permanent removal" : "Remove credentials"}
                </button>
              ) : null}
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
              Access Token {upstox.access_token_configured ? <span style={{ fontSize: "0.75rem", color: "var(--muted)", fontWeight: "normal" }}>(masked)</span> : null}
              <input
                type="password"
                autoComplete="off"
                value={upstoxDraft.accessToken}
                placeholder={upstox.access_token_configured ? "Saved · masked" : "Enter Upstox access token"}
                onFocus={(e) => { if (e.target.value.includes("•")) e.target.select(); }}
                onChange={(e) => setUpstoxDraft({ ...upstoxDraft, accessToken: e.target.value })}
              />
            </label>
            <label>
              Label
              <input value={upstoxDraft.label} onChange={(e) => setUpstoxDraft({ ...upstoxDraft, label: e.target.value })} />
            </label>
            <p className="note" style={{ fontSize: "0.8rem", color: "var(--muted)", margin: "8px 0" }}>
              💡 <strong>Disconnect vs Remove:</strong> Disconnect suspends active market-data synchronization while preserving your token. Remove permanently deletes all stored credentials.
            </p>
            <div className="actions">
              <button className="primary" type="submit" disabled={Boolean(busy)}>Save changes</button>
              <button
                type="button"
                onClick={testUpstoxInModal}
                disabled={Boolean(busy) || (!upstoxDraft.accessToken.trim() && !upstox.access_token_configured)}
                title={(!upstoxDraft.accessToken.trim() && !upstox.access_token_configured) ? "Enter access token first" : "Save and test Upstox connection"}
              >
                Test connection
              </button>
              {upstox.enabled ? (
                <button
                  type="button"
                  onClick={async () => {
                    await disconnectProvider("upstox");
                    closePanel();
                  }}
                  disabled={Boolean(busy)}
                >
                  Disconnect
                </button>
              ) : null}
              {upstox.configured ? (
                <button
                  className="danger"
                  type="button"
                  onClick={async () => {
                    if (!confirmClear) { setConfirmClear(true); return; }
                    if (await send("/api/integrations/upstox/clear")) closePanel();
                  }}
                  disabled={Boolean(busy)}
                >
                  {confirmClear ? "Confirm permanent removal" : "Remove credentials"}
                </button>
              ) : null}
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
              API Key {kite.api_key_configured ? <span style={{ fontSize: "0.75rem", color: "var(--muted)", fontWeight: "normal" }}>(masked)</span> : null}
              <input
                type="password"
                autoComplete="off"
                value={kiteDraft.apiKey}
                placeholder={kite.api_key_configured ? "Saved · masked" : "Enter Kite API Key"}
                onFocus={(e) => { if (e.target.value.includes("•")) e.target.select(); }}
                onChange={(e) => setKiteDraft({ ...kiteDraft, apiKey: e.target.value })}
              />
            </label>
            <div className="status-line"><span>Access Token</span><b>{secretIndicator(kite.access_token_configured)}</b></div>
            <label>
              Access Token {kite.access_token_configured ? <span style={{ fontSize: "0.75rem", color: "var(--muted)", fontWeight: "normal" }}>(masked)</span> : null}
              <input
                type="password"
                autoComplete="off"
                value={kiteDraft.accessToken}
                placeholder={kite.access_token_configured ? "Saved · masked" : "Enter Kite Access Token"}
                onFocus={(e) => { if (e.target.value.includes("•")) e.target.select(); }}
                onChange={(e) => setKiteDraft({ ...kiteDraft, accessToken: e.target.value })}
              />
            </label>
            <label>
              Label
              <input value={kiteDraft.label} onChange={(e) => setKiteDraft({ ...kiteDraft, label: e.target.value })} />
            </label>
            <p className="note" style={{ fontSize: "0.8rem", color: "var(--muted)", margin: "8px 0" }}>
              💡 <strong>Disconnect vs Remove:</strong> Disconnect suspends active market-data synchronization while preserving your credentials. Remove permanently deletes all stored credentials.
            </p>
            <div className="actions">
              <button className="primary" type="submit" disabled={Boolean(busy)}>Save changes</button>
              <button
                type="button"
                onClick={testKiteInModal}
                disabled={Boolean(busy) || ((!kiteDraft.apiKey.trim() || !kiteDraft.accessToken.trim()) && !kite.configured)}
                title={((!kiteDraft.apiKey.trim() || !kiteDraft.accessToken.trim()) && !kite.configured) ? "Enter API Key and Access Token first" : "Save and test Kite connection"}
              >
                Test connection
              </button>
              {kite.enabled ? (
                <button
                  type="button"
                  onClick={async () => {
                    await disconnectProvider("kite");
                    closePanel();
                  }}
                  disabled={Boolean(busy)}
                >
                  Disconnect
                </button>
              ) : null}
              {kite.configured ? (
                <button
                  className="danger"
                  type="button"
                  onClick={async () => {
                    if (!confirmClear) { setConfirmClear(true); return; }
                    if (await send("/api/integrations/kite/clear")) closePanel();
                  }}
                  disabled={Boolean(busy)}
                >
                  {confirmClear ? "Confirm permanent removal" : "Remove credentials"}
                </button>
              ) : null}
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
              API Key {angelone.api_key_configured ? <span style={{ fontSize: "0.75rem", color: "var(--muted)", fontWeight: "normal" }}>(masked)</span> : null}
              <input
                type="password"
                autoComplete="off"
                value={angeloneDraft.apiKey}
                placeholder={angelone.api_key_configured ? "Saved · masked" : "Enter Angel One API Key"}
                onFocus={(e) => { if (e.target.value.includes("•")) e.target.select(); }}
                onChange={(e) => setAngeloneDraft({ ...angeloneDraft, apiKey: e.target.value })}
              />
            </label>
            <div className="status-line"><span>Client Code</span><b>{angelone.client_code ? "Saved" : "Missing"}</b></div>
            <label>
              Client Code
              <input type="text" value={angeloneDraft.clientCode} placeholder={angelone.client_code || "e.g. S123456"} onChange={(e) => setAngeloneDraft({ ...angeloneDraft, clientCode: e.target.value })} />
            </label>
            <div className="status-line"><span>JWT Token</span><b>{secretIndicator(angelone.jwt_token_configured)}</b></div>
            <label>
              JWT Token {angelone.jwt_token_configured ? <span style={{ fontSize: "0.75rem", color: "var(--muted)", fontWeight: "normal" }}>(masked)</span> : null}
              <input
                type="password"
                autoComplete="off"
                value={angeloneDraft.jwtToken}
                placeholder={angelone.jwt_token_configured ? "Saved · masked" : "Enter JWT Token"}
                onFocus={(e) => { if (e.target.value.includes("•")) e.target.select(); }}
                onChange={(e) => setAngeloneDraft({ ...angeloneDraft, jwtToken: e.target.value })}
              />
            </label>
            <label>
              Label
              <input value={angeloneDraft.label} onChange={(e) => setAngeloneDraft({ ...angeloneDraft, label: e.target.value })} />
            </label>
            <p className="note" style={{ fontSize: "0.8rem", color: "var(--muted)", margin: "8px 0" }}>
              💡 <strong>Disconnect vs Remove:</strong> Disconnect suspends active market-data synchronization while preserving your credentials. Remove permanently deletes all stored credentials.
            </p>
            <div className="actions">
              <button className="primary" type="submit" disabled={Boolean(busy)}>Save changes</button>
              <button
                type="button"
                onClick={testAngelOneInModal}
                disabled={Boolean(busy) || ((!angeloneDraft.apiKey.trim() || !angeloneDraft.jwtToken.trim()) && !angelone.configured)}
                title={((!angeloneDraft.apiKey.trim() || !angeloneDraft.jwtToken.trim()) && !angelone.configured) ? "Enter API Key and JWT Token first" : "Save and test Angel One connection"}
              >
                Test connection
              </button>
              {angelone.enabled ? (
                <button
                  type="button"
                  onClick={async () => {
                    await disconnectProvider("angelone");
                    closePanel();
                  }}
                  disabled={Boolean(busy)}
                >
                  Disconnect
                </button>
              ) : null}
              {angelone.configured ? (
                <button
                  className="danger"
                  type="button"
                  onClick={async () => {
                    if (!confirmClear) { setConfirmClear(true); return; }
                    if (await send("/api/integrations/angelone/clear")) closePanel();
                  }}
                  disabled={Boolean(busy)}
                >
                  {confirmClear ? "Confirm permanent removal" : "Remove credentials"}
                </button>
              ) : null}
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
              API key {gemini.api_key_configured ? <span style={{ fontSize: "0.75rem", color: "var(--muted)", fontWeight: "normal" }}>(masked)</span> : null}
              <input
                type="password"
                autoComplete="off"
                value={geminiDraft.apiKey}
                placeholder={gemini.api_key_configured ? "Saved · masked" : "Enter Gemini API key"}
                onFocus={(e) => { if (e.target.value.includes("•")) e.target.select(); }}
                onChange={(e) => setGeminiDraft({ ...geminiDraft, apiKey: e.target.value })}
              />
            </label>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "10px" }}>
              <span style={{ fontSize: "0.85rem", fontWeight: 600 }}>Model</span>
              <button
                type="button"
                onClick={() => refreshModels("gemini", geminiDraft.apiKey)}
                disabled={loadingModels}
                style={{ fontSize: "0.78rem", padding: "3px 8px", background: "var(--card-subtle, #131c31)", border: "1px solid var(--line)", borderRadius: "6px", cursor: "pointer", color: "var(--ink, #f8fafc)" }}
                title="Query live models from Google AI using the configured or entered API key"
              >
                {loadingModels ? "⏳ Fetching..." : "🔄 Query Live Models"}
              </button>
            </div>
            <select
              value={geminiModels.some(m => m.id === geminiDraft.model) ? geminiDraft.model : "custom"}
              onChange={(e) => {
                if (e.target.value !== "custom") {
                  setGeminiDraft({ ...geminiDraft, model: e.target.value, customModelActive: false });
                } else {
                  setGeminiDraft({ ...geminiDraft, customModelActive: true });
                }
              }}
              style={{ marginTop: "4px", width: "100%" }}
            >
              <optgroup label="Available Gemini Models">
                {geminiModels.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label || item.id}
                  </option>
                ))}
              </optgroup>
              <option value="custom">Custom / Fine-Tuned Model...</option>
            </select>
            {modelsStatusMessage ? (
              <small style={{ display: "block", color: "var(--muted)", marginTop: "4px", fontSize: "0.75rem" }}>
                ℹ️ {modelsStatusMessage}
              </small>
            ) : null}
            {(!geminiModels.some(m => m.id === geminiDraft.model) || geminiDraft.customModelActive) ? (
              <label style={{ marginTop: "8px" }}>
                Custom Model ID
                <input
                  type="text"
                  placeholder="e.g. gemini-2.5-pro-preview or tunedModels/custom-model"
                  value={geminiDraft.model}
                  onChange={(e) => setGeminiDraft({ ...geminiDraft, model: e.target.value, customModelActive: true })}
                />
              </label>
            ) : null}
            <label>
              Label
              <input value={geminiDraft.label} onChange={(e) => setGeminiDraft({ ...geminiDraft, label: e.target.value })} />
            </label>
            <p className="note" style={{ fontSize: "0.8rem", color: "var(--muted)", margin: "8px 0" }}>
              💡 <strong>Disconnect vs Remove:</strong> Disconnect stops AI agent usage while preserving your API key. Remove permanently erases the key from encrypted storage.
            </p>
            <div className="actions">
              <button className="primary" type="submit" disabled={Boolean(busy)}>Save changes</button>
              <button
                type="button"
                onClick={testGeminiInModal}
                disabled={Boolean(busy) || (!geminiDraft.apiKey.trim() && !gemini.api_key_configured)}
                title={(!geminiDraft.apiKey.trim() && !gemini.api_key_configured) ? "Enter an API key first" : "Save and test Gemini model connectivity"}
              >
                Test connection
              </button>
              {gemini.enabled ? (
                <button
                  type="button"
                  onClick={async () => {
                    await disconnectProvider("gemini");
                    closePanel();
                  }}
                  disabled={Boolean(busy)}
                >
                  Disconnect
                </button>
              ) : null}
              {gemini.configured ? (
                <button
                  className="danger"
                  type="button"
                  onClick={async () => {
                    if (!confirmClear) { setConfirmClear(true); return; }
                    if (await send("/api/integrations/gemini/clear")) closePanel();
                  }}
                  disabled={Boolean(busy)}
                >
                  {confirmClear ? "Confirm permanent removal" : "Remove credentials"}
                </button>
              ) : null}
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
              API key {openai.api_key_configured ? <span style={{ fontSize: "0.75rem", color: "var(--muted)", fontWeight: "normal" }}>(masked)</span> : null}
              <input
                type="password"
                autoComplete="off"
                value={openaiDraft.apiKey}
                placeholder={openai.api_key_configured ? "Saved · masked" : "Enter API key"}
                onFocus={(e) => { if (e.target.value.includes("•")) e.target.select(); }}
                onChange={(event) => setOpenaiDraft({ ...openaiDraft, apiKey: event.target.value })}
              />
            </label>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "10px" }}>
              <span style={{ fontSize: "0.85rem", fontWeight: 600 }}>Model</span>
              <button
                type="button"
                onClick={() => refreshModels("openai", openaiDraft.apiKey)}
                disabled={loadingModels}
                style={{ fontSize: "0.78rem", padding: "3px 8px", background: "var(--card-subtle, #131c31)", border: "1px solid var(--line)", borderRadius: "6px", cursor: "pointer", color: "var(--ink, #f8fafc)" }}
                title="Query live models from OpenAI using the configured or entered API key"
              >
                {loadingModels ? "⏳ Fetching..." : "🔄 Query Live Models"}
              </button>
            </div>
            <select
              value={openaiDraft.model}
              onChange={(event) => setOpenaiDraft({ ...openaiDraft, model: event.target.value })}
              style={{ marginTop: "4px", width: "100%" }}
            >
              {openaiModels.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label || item.id}
                </option>
              ))}
            </select>
            {modelsStatusMessage ? (
              <small style={{ display: "block", color: "var(--muted)", marginTop: "4px", fontSize: "0.75rem" }}>
                ℹ️ {modelsStatusMessage}
              </small>
            ) : null}
            <label>
              Label
              <input value={openaiDraft.label} onChange={(event) => setOpenaiDraft({ ...openaiDraft, label: event.target.value })} />
            </label>
            {confirmEnable ? <p className="note">Confirm to {openaiDraft.enabled ? "enable" : "disable"} OpenAI. This does not request a completion.</p> : null}
            <p className="note" style={{ fontSize: "0.8rem", color: "var(--muted)", margin: "8px 0" }}>
              💡 <strong>Disconnect vs Remove:</strong> Disconnect stops AI agent usage while preserving your API key. Remove permanently erases the key from encrypted storage.
            </p>
            <div className="actions">
              <button className="primary" type="submit" disabled={Boolean(busy)}>{confirmEnable ? "Confirm and save" : "Save changes"}</button>
              <button
                type="button"
                onClick={testOpenAIInModal}
                disabled={Boolean(busy) || (!openaiDraft.apiKey.trim() && !openai.api_key_configured)}
                title={(!openaiDraft.apiKey.trim() && !openai.api_key_configured) ? "Enter an API key first" : "Save and test OpenAI model connectivity"}
              >
                Test connection
              </button>
              {openai.enabled ? (
                <button
                  type="button"
                  onClick={async () => {
                    await disconnectProvider("openai");
                    closePanel();
                  }}
                  disabled={Boolean(busy)}
                >
                  Disconnect
                </button>
              ) : null}
              {openai.configured ? (
                <button
                  className="danger"
                  type="button"
                  onClick={async () => {
                    if (!confirmClear) { setConfirmClear(true); return; }
                    if (await send("/api/integrations/openai/clear")) closePanel();
                  }}
                  disabled={Boolean(busy)}
                >
                  {confirmClear ? "Confirm permanent removal" : "Remove credentials"}
                </button>
              ) : null}
            </div>
          </form>
        </div>
      ) : null}

      {confirmClearProvider ? (
        <div className="modal-backdrop" onClick={() => setConfirmClearProvider(null)}>
          <div className="modal" role="dialog" aria-labelledby="clear-dialog-title" onClick={(e) => e.stopPropagation()}>
            <div className="section-head">
              <h2 id="clear-dialog-title" style={{ color: "var(--red, #f87171)" }}>Remove {confirmClearProvider.toUpperCase()} Credentials?</h2>
              <button type="button" onClick={() => setConfirmClearProvider(null)}>Close</button>
            </div>
            <p style={{ fontSize: "0.9rem", lineHeight: 1.5, margin: "12px 0" }}>
              <strong>Permanent Deletion:</strong> This action permanently deletes your saved encrypted credentials, API keys, and session tokens for <strong>{confirmClearProvider.toUpperCase()}</strong>.
            </p>
            <p style={{ fontSize: "0.85rem", color: "var(--muted)", margin: "0 0 16px" }}>
              💡 If you only want to stop background synchronization and deactivate the provider while retaining your credentials for later use, click <strong>Cancel</strong> and use <strong>Disconnect</strong> instead.
            </p>
            <div className="actions" style={{ display: "flex", gap: "10px", justifyContent: "flex-end" }}>
              <button type="button" onClick={() => setConfirmClearProvider(null)}>Cancel</button>
              <button type="button" className="danger" onClick={() => removeProvider(confirmClearProvider)} disabled={Boolean(busy)}>
                Permanently Delete Credentials
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}

function ProviderCard({
  mark,
  name,
  detail,
  enabled,
  configured,
  connection,
  lifecycleState,
  capabilities,
  lastError,
  extraBadge,
  extraKind,
  historyBadge,
  historyKind,
  facts,
  detailsTitle,
  details,
  busy,
  onConfigure,
  onTest,
  onConnect,
  onDisconnect,
  onRemove,
  onDiagnostics,
  testDisabled,
}) {
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
        <div style={{ display: "flex", gap: "6px", alignItems: "center", flexWrap: "wrap", justifyContent: "flex-end" }}>
          {lifecycleState ? (
            <span className={pillClass(lifecycleKind(lifecycleState))}>{lifecycleLabel(lifecycleState)}</span>
          ) : null}
          <span className={pillClass(enabled ? "ok" : "wait")}>{integrationLabel(enabled)}</span>
        </div>
      </div>
      <div className="badge-row">
        <span className={pillClass(configured ? "ok" : "idle")}>{credentialLabel(configured)}</span>
        {connection !== null && connection !== undefined ? (
          <span className={pillClass(connectionKind)}>{connectionLabel(connection)}</span>
        ) : null}
        {capabilities?.authentication ? (
          <span className={pillClass(capabilities.authentication === "verified" ? "ok" : capabilities.authentication === "rejected" ? "bad" : "wait")}>
            Auth: {capabilities.authentication === "verified" ? "Verified" : capabilities.authentication === "rejected" ? "Failed" : "Not Tested"}
          </span>
        ) : null}
        {capabilities?.market_data ? (
          <span className={pillClass(capabilities.market_data === "verified" ? "ok" : capabilities.market_data === "rejected" ? "bad" : "wait")}>
            Market Data: {capabilities.market_data === "verified" ? "Verified" : capabilities.market_data === "rejected" ? "Failed" : "Not Tested"}
          </span>
        ) : null}
        {capabilities?.model_lookup ? (
          <span className={pillClass(capabilities.model_lookup === "verified" ? "ok" : capabilities.model_lookup === "rejected" ? "bad" : "wait")}>
            Model: {capabilities.model_lookup === "verified" ? "Verified" : capabilities.model_lookup === "rejected" ? "Failed" : "Not Tested"}
          </span>
        ) : null}
        {extraBadge ? <span className={pillClass(extraKind)}>{extraBadge}</span> : null}
        {historyBadge ? <span className={pillClass(historyKind)}>{historyBadge}</span> : null}
      </div>
      {lastError ? (
        <p className="note" style={{ color: "#f87171", background: "rgba(239, 68, 68, 0.1)", border: "1px solid rgba(239, 68, 68, 0.2)", borderRadius: "6px", padding: "6px 10px", margin: "6px 0 10px", fontSize: "0.82rem" }}>
          ⚠️ <strong>Last Error:</strong> {lastError}
        </p>
      ) : null}
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
        {enabled && onDisconnect ? (
          <button type="button" onClick={onDisconnect} disabled={Boolean(busy)} title="Disconnect stops background usage while retaining credentials">
            Disconnect
          </button>
        ) : !enabled && configured && onConnect ? (
          <button type="button" onClick={onConnect} disabled={Boolean(busy)} title="Connect re-enables provider operations using saved credentials">
            Connect
          </button>
        ) : null}
        {configured && onRemove ? (
          <button type="button" className="danger" onClick={onRemove} disabled={Boolean(busy)} title="Permanently delete stored credentials">
            Remove
          </button>
        ) : null}
        {onDiagnostics ? <button type="button" onClick={onDiagnostics}>Diagnostics</button> : null}
      </div>
    </section>
  );
}
