"use client";

import Link from "next/link";
import { useState } from "react";

import { signIn, signOut, useAccountStatus, useSession } from "./components/session";

export default function LoginPage() {
  const session = useSession();
  const account = useAccountStatus();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const stored = account?.account_exists === true;

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await signIn(password, stored ? username : undefined);
      setPassword("");
      window.location.assign("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
      setBusy(false);
    }
  }

  async function leave() {
    await signOut();
    window.location.assign("/");
  }

  return (
    <main className="auth-page">
      <header className="page-head">
        <p className="eyebrow">Account</p>
        <h1>Sign in</h1>
        <p>{stored ? "Sign in with the stored operator account." : "No operator account is stored yet. Create one, or sign in with the local operator password."}</p>
      </header>
      <section className="auth-card">
        {session.phase === "ready" ? (
          <>
            <h2>Signed in</h2>
            <p>You are signed in as {session.me?.display_name || session.actor}. API keys and the profile are on the account page.</p>
            <div className="actions">
              <Link className="primary" href="/dashboard">Open the desk</Link>
              <Link href="/settings">Account</Link>
              <button type="button" onClick={leave}>Log out</button>
            </div>
          </>
        ) : (
          <form onSubmit={submit}>
            {stored ? (
              <label>
                Username
                <input type="text" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} />
              </label>
            ) : null}
            <label>
              Password
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </label>
            <button className="primary" type="submit" disabled={busy || password.length === 0}>{busy ? "Signing in…" : "Sign in"}</button>
            {account?.signup_open ? <p>First time here? <Link href="/signup">Create the operator account</Link>.</p> : null}
          </form>
        )}
        {error ? <p className="error" role="alert">{error}</p> : null}
      </section>
    </main>
  );
}
