// The version-2 shell: its own nav, its own sign-in gate, its own banners.
//
// It deliberately does not reuse the legacy TopNav or CommandPalette. The
// legacy application is an Operations Research demonstration with eight
// technique pages and no login; this one is a signed-in dispatch desk with
// four. Sharing chrome would have implied they are the same product, and the
// legacy routes have to keep working untouched until the phase 5 cutover.

import { Routes, Route, NavLink, useNavigate } from "react-router-dom";
import { SessionContext, useHealth, useSessionQuery, isOfflineDemo } from "./lib/session";
import { V2_NAV } from "./routes";
import { v2 } from "./lib/api";
import { Banner, Failure, Loading } from "./components/States";
import { DISPLAY_ZONE } from "./lib/format";
import Login from "./pages/Login";
import Queue from "./pages/Queue";
import TicketDetail from "./pages/TicketDetail";
import RiskRadar from "./pages/RiskRadar";
import Administration from "./pages/Administration";

export default function V2App() {
  const session = useSessionQuery();
  const health = useHealth();

  if (session.isLoading) return <Shell><Loading what="your session" /></Shell>;
  if (session.isError) {
    return (
      <Shell>
        <Failure error={session.error} onRetry={() => session.refetch()} />
      </Shell>
    );
  }
  if (!session.data) return <Shell><Login onSignedIn={() => session.refetch()} /></Shell>;

  const actor = session.data.actor;
  return (
    <SessionContext.Provider value={{ actor, health: health.data }}>
      <Shell actor={actor} health={health.data}>
        <Routes>
          <Route index element={<Queue />} />
          <Route path="tickets/:ticketId" element={<TicketDetail />} />
          <Route path="radar" element={<RiskRadar />} />
          <Route path="admin" element={<Administration />} />
        </Routes>
      </Shell>
    </SessionContext.Provider>
  );
}

function Shell({ actor, health, children }) {
  const navigate = useNavigate();
  return (
    <div className="min-h-screen bg-paper">
      <header className="border-b border-rule bg-surface">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-4 p-4">
          <div>
            <p className="font-display text-lg text-ink">SLA service desk</p>
            <p className="font-mono-label text-[10px] text-muted">
              version 2 · times shown in {DISPLAY_ZONE}
            </p>
          </div>
          {actor ? (
            <nav className="flex gap-1" aria-label="Version 2">
              {V2_NAV.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    `rounded-[var(--radius-control)] px-3 py-1.5 text-sm ${
                      isActive
                        ? "bg-accent text-accent-ink"
                        : "text-ink-2 hover:bg-paper-2"
                    }`
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
          ) : null}
          <div className="ml-auto flex items-center gap-3 text-sm">
            <a className="text-muted underline" href="/">
              Legacy OR demo
            </a>
            {actor ? (
              <>
                <span className="text-muted">
                  {actor.username} · {actor.role}
                </span>
                <button
                  type="button"
                  className="rounded-[var(--radius-control)] border border-rule-2 px-3 py-1.5"
                  onClick={async () => {
                    await v2.logout();
                    navigate(0);
                  }}
                >
                  Sign out
                </button>
              </>
            ) : null}
          </div>
        </div>
      </header>

      <main className="mx-auto flex max-w-6xl flex-col gap-4 p-4 sm:p-6">
        {health ? <BuildBanners health={health} /> : null}
        {children}
      </main>
    </div>
  );
}

/** Two facts the demo must state on every screen rather than in a footnote. */
function BuildBanners({ health }) {
  return (
    <>
      {isOfflineDemo(health) ? (
        <Banner title="Offline demo data.">
          This build is serving the seeded SQLite database. Every ticket, agent
          and SLA policy in it is illustrative; none of it is a measured result.
        </Banner>
      ) : null}
      {health.models_available ? null : (
        <Banner tone="critical" title="Model unavailable — manual dispatch.">
          No risk artifact loaded, so recommendations are blocked. Tickets can
          still be created, read and assigned by hand, and each one records that
          no model was available.
        </Banner>
      )}
    </>
  );
}
