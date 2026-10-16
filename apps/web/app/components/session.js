"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

export function csrfToken() {
  const match = document.cookie.match(/(?:^|; )imm_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

export function useSession() {
  const [actor, setActor] = useState(null);
  const [me, setMe] = useState(null);
  const [phase, setPhase] = useState("loading");

  const reload = useCallback(async () => {
    const response = await fetch("/api/session");
    if (response.status === 401) {
      setActor(null);
      setMe(null);
      setPhase("signed-out");
      return;
    }
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      setActor(null);
      setMe(null);
      setPhase("error");
      return;
    }
    setActor(body.actor || null);
    setMe(body);
    setPhase(body.actor ? "ready" : "signed-out");
  }, []);

  useEffect(() => {
    reload().catch(() => setPhase("error"));
  }, [reload]);

  return { actor, me, phase, reload };
}

export function useAccountStatus() {
  const [status, setStatus] = useState(null);
  useEffect(() => {
    fetch("/api/account/status")
      .then(async (response) => (response.ok ? response.json() : null))
      .then((body) => setStatus(body))
      .catch(() => setStatus(null));
  }, []);
  return status;
}

async function post(path, payload, { csrf = false, method = "POST" } = {}) {
  const headers = { "content-type": "application/json" };
  if (csrf) headers["x-csrf-token"] = csrfToken();
  const response = await fetch(path, { method, headers, body: JSON.stringify(payload) });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(body.message || "The request failed");
    error.code = body.code;
    throw error;
  }
  return body;
}

export function signIn(password, username) {
  const payload = { password };
  if (username) payload.username = username;
  return post("/api/session/login", payload);
}

export function signUp({ username, password, displayName }) {
  return post("/api/account/signup", { username, password, display_name: displayName });
}

export function saveProfile({ displayName, timezone }) {
  return post("/api/account/profile", { display_name: displayName, timezone }, { csrf: true, method: "PUT" });
}

export function changePassword({ current, next }) {
  return post("/api/account/password", { current_password: current, new_password: next }, { csrf: true });
}

export async function signOut() {
  await fetch("/api/session/logout", { method: "POST" });
}

export function SignInPrompt() {
  return (
    <section>
      <h2>Sign in required</h2>
      <p>This desk has one operator account. Sign in on the account page.</p>
      <Link className="primary" href="/">Sign in</Link>
    </section>
  );
}
