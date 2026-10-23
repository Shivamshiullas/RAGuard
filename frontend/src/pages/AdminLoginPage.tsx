import { useState, type FormEvent } from "react";
import { signInAdmin } from "../api/auth";
import BrandLogo from "../components/BrandLogo";
import { branding } from "../config/branding";
import type { AdminSession } from "../types/auth";

interface AdminLoginPageProps {
  onSignedIn: (session: AdminSession) => void;
  onBack: () => void;
}

export default function AdminLoginPage({ onSignedIn, onBack }: AdminLoginPageProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      onSignedIn(await signInAdmin(username, password));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed. Try again.");
      setSubmitting(false);
    }
  }

  return (
    <main className="login-page">
      <div className="login-panel">
        <div className="login-panel__brand">
          <BrandLogo />
          <p className="chat-header__college">{branding.collegeName}</p>
        </div>
        <h1 className="login-panel__title">Admin sign in</h1>
        <p className="login-panel__text">Manage the documents the {branding.assistantTitle} answers from.</p>

        <form className="login-form" onSubmit={handleSubmit}>
          <div className="field">
            <label className="field__label" htmlFor="login-username">
              Username
            </label>
            <input
              id="login-username"
              className="input"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </div>
          <div className="field">
            <label className="field__label" htmlFor="login-password">
              Password
            </label>
            <input
              id="login-password"
              type="password"
              className="input"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          {error && (
            <p className="form-message form-message--error" role="alert">
              {error}
            </p>
          )}
          <button type="submit" className="button button--primary button--block" disabled={submitting}>
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <button type="button" className="link-button login-panel__back" onClick={onBack}>
          ← Back to student chat
        </button>
      </div>
    </main>
  );
}
