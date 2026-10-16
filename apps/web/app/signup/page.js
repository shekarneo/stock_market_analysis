"use client";

import Link from "next/link";
import { useState } from "react";

import { signUp, useAccountStatus } from "../components/session";

export default function SignupPage() {
  const account = useAccountStatus();
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const closed = account?.account_exists === true;

  async function submit(event) {
    event.preventDefault();
    setError("");
    if (password !== confirm) {
      setError("The two passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await signUp({ username, password, displayName });
      window.location.assign("/settings");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Signup failed");
      setBusy(false);
    }
  }

  return (
    <main className="auth-page">
      <header className="page-head">
        <p className="eyebrow">Account</p>
        <h1>Create account</h1>
        <p>This desk keeps one operator account in its database. The password is stored as a salted hash.</p>
      </header>
      <section className="auth-card">
        {closed ? (
          <>
            <p>The operator account already exists.</p>
            <Link className="primary" href="/">Sign in</Link>
          </>
        ) : account && account.storage_ready === false ? (
          <>
            <p>The API database has no account table yet. Run <code>alembic upgrade head</code> from <code>apps/api</code>, restart the API, then come back here. Until then the local operator password signs you in.</p>
            <Link className="primary" href="/">Sign in</Link>
          </>
        ) : (
          <form onSubmit={submit}>
            <label>
              Username
              <input type="text" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} />
            </label>
            <label>
              Display name
              <input type="text" autoComplete="name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
            </label>
            <label>
              Password
              <input type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} />
            </label>
            <label>
              Confirm password
              <input type="password" autoComplete="new-password" value={confirm} onChange={(event) => setConfirm(event.target.value)} />
            </label>
            <button className="primary" type="submit" disabled={busy || username.length < 3 || password.length < 8}>{busy ? "Creating…" : "Create account"}</button>
            <p>At least 8 characters. Already have the account? <Link href="/">Sign in</Link>.</p>
          </form>
        )}
        {error ? <p className="error" role="alert">{error}</p> : null}
      </section>
    </main>
  );
}
