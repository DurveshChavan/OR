// The application shell.
//
// One product, six sections: the dispatch queue, a ticket, the risk radar, the
// hardware register, the Operations Research methods the dispatch and
// replacement decisions are built from, and administration. There is no second
// application behind a second nav any more; the methods that used to live in a
// separate demo are a section of this one.
//
// The chrome is a translucent layer with content scrolling under it rather than
// an opaque strip that eats a fixed band of the page, and the boundary between
// the two is a fading mask instead of a hairline rule - both straight out of
// Apple's material guidance, and both degraded properly when a viewer asks for
// reduced transparency.
//
// Where the data comes from is stated once, in the footer, rather than as an
// alert repeated on all six screens. The disclosure is not weaker for being
// quiet: the tickets are real held-out records and the footer names the log
// they come from, the seed script records the provenance on every ticket's
// creation event, and the report carries the full account. An alert bar is for
// something a reader has to act on. The one warning that survives as a banner
// is the one that meets that test - no risk artifact loaded, dispatch blocked.

import { NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { SessionContext, useHealth, useSessionQuery, isOfflineDemo } from "./lib/session";
import { NAV_ITEMS } from "./routes";
import { api } from "./lib/api";
import { Banner, Failure, Loading } from "./components/States";
import { Appear, Button } from "./components/Motion";
import { DISPLAY_ZONE } from "./lib/format";
import Login from "./pages/Login";
import Queue from "./pages/Queue";
import TicketDetail from "./pages/TicketDetail";
import RiskRadar from "./pages/RiskRadar";
import Hardware from "./pages/Hardware";
import Methods from "./pages/Methods";
import Administration from "./pages/Administration";

export default function ServiceDesk() {
  const session = useSessionQuery();
  const health = useHealth();

  if (session.isLoading) {
    return (
      <Shell>
        <Loading what="your session" />
      </Shell>
    );
  }
  if (session.isError) {
    return (
      <Shell>
        <Failure error={session.error} onRetry={() => session.refetch()} />
      </Shell>
    );
  }
  if (!session.data) {
    return (
      <Shell>
        <Login onSignedIn={() => session.refetch()} />
      </Shell>
    );
  }

  const actor = session.data.actor;
  return (
    <SessionContext.Provider value={{ actor, health: health.data }}>
      <Shell actor={actor} health={health.data}>
        <Routes>
          <Route index element={<Queue />} />
          <Route path="tickets/:ticketId" element={<TicketDetail />} />
          <Route path="radar" element={<RiskRadar />} />
          <Route path="hardware" element={<Hardware />} />
          <Route path="methods/*" element={<Methods />} />
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
      <header className="sticky top-0 z-40 chrome-layer">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-5 gap-y-2 px-4 py-3 sm:px-6">
          <div className="shrink-0">
            <p className="font-display text-[17px] leading-tight tracking-[-0.02em] text-ink">
              SLA Service Desk
            </p>
            <p className="font-mono-label text-[10px] text-muted">
              times shown in {DISPLAY_ZONE}
            </p>
          </div>

          {actor ? (
            <nav className="flex min-w-0 flex-1 gap-0.5 overflow-x-auto" aria-label="Sections">
              {NAV_ITEMS.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    "shrink-0 rounded-[var(--radius-control)] px-3 py-1.5 text-sm " +
                    "transition-colors duration-150 " +
                    (isActive
                      ? "bg-accent text-accent-ink"
                      : "text-ink-2 hover:bg-paper-2")
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
          ) : null}

          {actor ? (
            <div className="flex shrink-0 items-center gap-3 text-sm">
              <span className="text-muted">
                {actor.username} · {actor.role}
              </span>
              <Button
                size="sm"
                onClick={async () => {
                  await api.logout();
                  navigate(0);
                }}
              >
                Sign out
              </Button>
            </div>
          ) : null}
        </div>
        {/* Where floating chrome meets content, a fading mask rather than a rule. */}
        <div className="scroll-edge" aria-hidden="true" />
      </header>

      <main className="mx-auto flex max-w-6xl flex-col gap-4 px-4 py-6 sm:px-6">
        {health ? <BuildBanners health={health} /> : null}
        <Appear>{children}</Appear>
      </main>

      {health ? <Provenance health={health} /> : null}
    </div>
  );
}

/** The one condition a reader has to act on, and nothing else. */
function BuildBanners({ health }) {
  if (health.models_available) return null;
  return (
    <Banner tone="critical" title="Model unavailable - manual dispatch.">
      No risk artifact loaded, so recommendations are blocked. Tickets can still
      be created, read and assigned by hand, and each one records that no model
      was available.
    </Banner>
  );
}

/** Where the data on these screens comes from, stated once. */
function Provenance({ health }) {
  if (!isOfflineDemo(health)) return null;
  return (
    <footer className="mx-auto max-w-6xl px-4 pb-8 text-xs leading-relaxed text-muted sm:px-6">
      <p>
        Demo build. The tickets are real incidents from the held-out split of the
        UCI-498 incident management process enriched event log; their fields are
        the records&rsquo; own and each one is opened at a stated offset inside
        the demo window, because the records date from 2016. The resolvers, the
        SLA policy and the machine register are illustrative, and each row says
        so in its own source note. The full account is in{" "}
        <code className="font-mono-label">docs/report.md</code>.
      </p>
    </footer>
  );
}
