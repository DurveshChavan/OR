// Local sign-in. The credentials are the demo ones and they are printed on the
// page on purpose: the viva runs offline against a seeded database, and a
// reviewer who cannot get past the first screen sees nothing else.

import { useState } from "react";
import { api } from "../lib/api";
import { Failure } from "../components/States";

export default function Login({ onSignedIn }) {
  const [username, setUsername] = useState("dispatcher.demo");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.login(username, password);
      onSignedIn();
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mx-auto w-full max-w-md rounded-[var(--radius-card)] border border-rule bg-surface p-6">
      <h1 className="font-display text-xl text-ink">Sign in</h1>
      <p className="mt-1 text-sm text-muted">
        Every recommendation, acceptance and override is recorded against the
        signed-in user, so there is no anonymous path into this application.
      </p>

      <form className="mt-4 flex flex-col gap-3" onSubmit={submit}>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-mono-label text-[11px] text-muted">Username</span>
          <input
            className="rounded-[var(--radius-control)] border border-rule-2 bg-paper px-3 py-2"
            value={username}
            autoComplete="username"
            onChange={(event) => setUsername(event.target.value)}
            required
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-mono-label text-[11px] text-muted">Password</span>
          <input
            className="rounded-[var(--radius-control)] border border-rule-2 bg-paper px-3 py-2"
            type="password"
            value={password}
            autoComplete="current-password"
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>

        {error ? <Failure error={error} /> : null}

        <button
          type="submit"
          disabled={busy}
          className="rounded-[var(--radius-control)] bg-accent px-4 py-2 text-accent-ink disabled:opacity-60"
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>

      <p className="mt-4 border-t border-rule pt-3 text-xs text-muted">
        Seeded demo accounts: <code>dispatcher.demo</code> and{" "}
        <code>manager.demo</code>, password <code>local-demo-password</code>.
        They exist only in the offline demo database.
      </p>
    </section>
  );
}
