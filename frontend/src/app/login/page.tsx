"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, type FormEvent, useState } from "react";

import { ApiError, api, type LoginChallenge } from "@/lib/api/client";

function LoginForm() {
  const search = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [challenge, setChallenge] = useState<LoginChallenge | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submitPassword(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try { setChallenge(await api.login(email, password)); setPassword(""); }
    catch (reason) { setError(reason instanceof ApiError ? reason.message : "Login failed."); }
    finally { setBusy(false); }
  }
  async function submitCode(event: FormEvent) {
    event.preventDefault(); if (!challenge) return;
    setBusy(true); setError("");
    try {
      await api.verifyMfa(challenge.challenge_token, code);
      const requested = search.get("returnTo");
      window.location.assign(requested?.startsWith("/") && !requested.startsWith("//") ? requested : "/cases");
    } catch (reason) { setError(reason instanceof ApiError ? reason.message : "Verification failed."); }
    finally { setBusy(false); }
  }

  return (
    <section className="auth-card" aria-labelledby="login-title">
      <p className="eyebrow">Employee access</p>
      <h1 id="login-title">{challenge ? (challenge.status === "mfa_enrollment_required" ? "Set up MFA" : "Verify MFA") : "Sign in"}</h1>
      {error ? <div className="error-panel" role="alert">{error}</div> : null}
      {!challenge ? (
        <form onSubmit={submitPassword} className="stacked-form">
          <label>Email<input type="email" autoComplete="username" required value={email} onChange={(event) => setEmail(event.target.value)} /></label>
          <label>Password<input type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} /></label>
          <button className="button" disabled={busy}>{busy ? "Checking…" : "Continue"}</button>
        </form>
      ) : (
        <form onSubmit={submitCode} className="stacked-form">
          {challenge.status === "mfa_enrollment_required" ? (
            <div className="enrollment-panel">
              <p>Add this account to your authenticator app, then enter its six-digit code. The secret is shown only during this enrollment.</p>
              <label>Setup key<code className="setup-key">{challenge.enrollment_secret}</code></label>
              <details><summary>Authenticator URI</summary><code className="setup-uri">{challenge.provisioning_uri}</code></details>
            </div>
          ) : <p>Enter the current six-digit code from your authenticator app.</p>}
          <label>Authentication code<input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} required value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))} /></label>
          <button className="button" disabled={busy || code.length !== 6}>{busy ? "Verifying…" : "Verify and sign in"}</button>
        </form>
      )}
    </section>
  );
}

export default function LoginPage() {
  return <Suspense fallback={<div className="state-panel">Loading sign in…</div>}><LoginForm /></Suspense>;
}
