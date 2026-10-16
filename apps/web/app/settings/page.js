"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { changePassword, saveProfile, signOut, useSession } from "../components/session";

export default function ProfilePage() {
  const session = useSession();
  const [displayName, setDisplayName] = useState("");
  const [timezone, setTimezone] = useState("Asia/Kolkata");
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (session.me) {
      setDisplayName(session.me.display_name || "");
      setTimezone(session.me.timezone || "Asia/Kolkata");
    }
  }, [session.me]);

  async function leave() {
    await signOut();
    window.location.assign("/");
  }

  async function submitProfile(event) {
    event.preventDefault();
    setError("");
    setNotice("");
    try {
      await saveProfile({ displayName, timezone });
      setNotice("Profile saved.");
      await session.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "The profile could not be saved.");
    }
  }

  async function submitPassword(event) {
    event.preventDefault();
    setError("");
    setNotice("");
    try {
      await changePassword({ current, next });
      setCurrent("");
      setNext("");
      setNotice("Password changed.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "The password could not be changed.");
    }
  }

  const signedIn = session.phase === "ready" && session.actor;
  const stored = session.me?.stored === true;

  return (
    <main>
      <header className="page-head">
        <p className="eyebrow">Account</p>
        <h1>Profile</h1>
        <p>The operator account, API keys, and the session. Secrets are not shown after they are saved.</p>
      </header>
      {notice ? <p className="notice">{notice}</p> : null}
      {error ? <p className="error" role="alert">{error}</p> : null}
      {session.phase === "signed-out" ? (
        <section>
          <h2>Sign in required</h2>
          <Link className="primary" href="/">Sign in</Link>
        </section>
      ) : null}
      {signedIn ? (
        <section data-testid="profile">
          <h2>Operator</h2>
          <dl className="meta-row">
            <div><dt>Username</dt><dd>{session.me?.username}</dd></div>
            <div><dt>Stored in database</dt><dd>{stored ? "yes" : "no, signed in with the environment password"}</dd></div>
            <div><dt>Created</dt><dd>{session.me?.created_at || "not set"}</dd></div>
            <div><dt>Last login</dt><dd>{session.me?.last_login_at || "not set"}</dd></div>
          </dl>
          {stored ? (
            <form onSubmit={submitProfile}>
              <label>
                Display name
                <input type="text" value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
              </label>
              <label>
                Timezone
                <input type="text" value={timezone} onChange={(event) => setTimezone(event.target.value)} />
              </label>
              <button className="primary" type="submit">Save profile</button>
            </form>
          ) : (
            <p>No stored account exists. <Link href="/signup">Create the operator account</Link> to keep a profile in the database.</p>
          )}
        </section>
      ) : null}
      {signedIn && stored ? (
        <section>
          <h2>Password</h2>
          <form onSubmit={submitPassword}>
            <label>
              Current password
              <input type="password" autoComplete="current-password" value={current} onChange={(event) => setCurrent(event.target.value)} />
            </label>
            <label>
              New password
              <input type="password" autoComplete="new-password" value={next} onChange={(event) => setNext(event.target.value)} />
            </label>
            <button type="submit" disabled={next.length < 8 || current.length === 0}>Change password</button>
          </form>
        </section>
      ) : null}
      <section>
        <h2>Risk & Capital Allocation</h2>
        <p>Risk capital is enforced by fail-closed safety gates. Without explicit capital, all paper and live trading executions are blocked.</p>
        <div className="choice-row">
          <Link href="/risk">Configure Risk Capital in Portfolio</Link>
        </div>
      </section>
      <section>
        <h2>API keys</h2>
        <p>Groww and OpenAI credentials are saved encrypted in the database. A saved key is not shown again. Live trading stays off.</p>
        <div className="choice-row">
          <Link href="/settings/integrations">Set up API keys</Link>
        </div>
      </section>
      <section>
        <h2>Session</h2>
        <p>{signedIn ? "This browser holds the operator session." : "No session is stored in this browser."}</p>
        <p>Log out clears the session cookie. It does not delete the account or saved API keys.</p>
        {signedIn ? <button type="button" onClick={leave}>Log out</button> : null}
      </section>
    </main>
  );
}
