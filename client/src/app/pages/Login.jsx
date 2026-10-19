// The landing page, and the only screen that states the whole project.
//
// It does two jobs. The account someone signs in with is the actor recorded
// against every recommendation, confirmation and override, so nothing in this
// product happens anonymously. And a person arriving has not seen anything
// yet, so this is where the project gets named and where the three things it
// does are laid out. The third one, a ticket that can reach a hardware
// replacement decision, gets the emphasis, because it is the piece a reader is
// least likely to have seen in a service desk before.
//
// It is kept short on purpose. A landing page that explains the whole system
// is a landing page nobody finishes reading, and every claim here is shown
// properly on the screen that owns it.
//
// The decoration is cheap: two soft radial washes and a hairline grid, drawn
// in CSS from the accent token that already exists. No images and nothing to
// download. Every piece of text still sits on a solid surface, which is why the
// contrast measurements did not move when this went in.

import { useState } from "react";
import { api } from "../lib/api";
import { Failure } from "../components/States";

//: The three things the project title names, in the order the shell presents
//: them. One line each.
const PILLARS = [
  {
    step: "01",
    name: "Predictive allocation",
    body: "Models price every qualified resolver; the Hungarian method picks.",
  },
  {
    step: "02",
    name: "SLA escalation",
    body: "One ranked list. Reviews open against a name and close on an outcome.",
  },
  {
    step: "03",
    name: "Hardware replacement",
    body: "A machine that keeps generating tickets goes to a replacement decision.",
    novel: true,
  },
];

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
    <div className="landing relative isolate">
      <div className="landing-wash" aria-hidden="true" />

      <div className="relative grid items-center gap-10 lg:grid-cols-[minmax(0,1fr)_21rem] lg:gap-14">
        {/* --- the pitch ------------------------------------------------ */}
        <div className="min-w-0">
          <span className="landing-rule" aria-hidden="true" />
          <h1 className="mt-5 font-display text-[clamp(2rem,5vw,3.25rem)] leading-[1.06] tracking-tight text-ink">
            AI-Driven SLA
            <br />
            Optimization
          </h1>

          <p className="mt-4 max-w-xl text-[15px] leading-relaxed text-ink-2">
            Predictive ticket allocation, escalation and hardware replacement in
            IT service desks.
          </p>

          <ol className="mt-8 grid gap-3 sm:grid-cols-3">
            {PILLARS.map((pillar) => (
              <li
                key={pillar.step}
                className={
                  "rounded-[var(--radius-card)] border bg-surface p-4 " +
                  (pillar.novel
                    ? "border-accent/45 shadow-[0_10px_24px_-18px_rgba(16,42,80,0.45)]"
                    : "border-rule")
                }
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span
                    className={
                      "font-mono text-xs " +
                      (pillar.novel ? "text-accent" : "text-muted")
                    }
                  >
                    {pillar.step}
                  </span>
                  {pillar.novel ? (
                    <span className="rounded-[var(--radius-pill)] bg-accent px-2 py-0.5 text-[11px] font-medium text-accent-ink">
                      New here
                    </span>
                  ) : null}
                </div>
                <h2 className="mt-2 font-display text-[15px] leading-snug text-ink">
                  {pillar.name}
                </h2>
                <p className="mt-1.5 text-[13px] leading-relaxed text-muted">
                  {pillar.body}
                </p>
              </li>
            ))}
          </ol>
        </div>

        {/* --- the door ------------------------------------------------- */}
        <section
          className="w-full rounded-[var(--radius-card)] border border-rule bg-surface p-6 shadow-[0_18px_40px_-28px_rgba(16,42,80,0.55)]"
          aria-labelledby="sign-in-heading"
        >
          <h2 id="sign-in-heading" className="font-display text-xl text-ink">
            Sign in
          </h2>
          <p className="mt-1 text-sm text-muted">
            Every recommendation, confirmation and override is recorded against
            the signed-in user.
          </p>

          <form className="mt-5 flex flex-col gap-3" onSubmit={submit}>
            <label className="flex flex-col gap-1 text-sm" htmlFor="login-username">
              <span className="font-medium text-ink">Username</span>
              <input
                id="login-username"
                className="field"
                value={username}
                autoComplete="username"
                onChange={(event) => setUsername(event.target.value)}
                required
              />
            </label>
            <label className="flex flex-col gap-1 text-sm" htmlFor="login-password">
              <span className="font-medium text-ink">Password</span>
              <input
                id="login-password"
                className="field"
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
              className="mt-1 rounded-[var(--radius-control)] bg-accent px-4 py-2.5 font-medium text-accent-ink transition-[filter,opacity] duration-150 hover:brightness-110 disabled:opacity-60"
            >
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>
        </section>
      </div>
    </div>
  );
}
