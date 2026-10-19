// The application shell.
//
// The project this is built for is called "AI-Driven SLA Optimization:
// Predictive Ticket Allocation, Escalation and Hardware Replacement in IT
// Service Desks", and the shell is arranged so a person can see those three
// things without being told the title. Queue is the allocation. At risk is the
// escalation. Asset planning is the hardware replacement. Each page names its
// own part above its heading; the full title itself is stated where somebody
// arrives - the sign-in screen - and in the research appendix, rather than
// pinned across the top of every screen a dispatcher works in.
//
// What is *not* in the shell is as deliberate. The Operations Research
// worksheets live at /methods and are reachable only from the footer, and
// Operations - SLA policy, the roster, the manual rescore - is manager-only.
// A person who cannot act on a screen is not offered it.
//
// The chrome is a translucent layer with content scrolling under it rather than
// an opaque strip that eats a fixed band of the page - Apple's material
// guidance, with the reduced-transparency and increased-contrast fallbacks that
// make it a request rather than a suggestion (see index.css, .chrome-layer).
//
// Where the data comes from is stated once, in the footer, rather than as an
// alert repeated on every screen. The disclosure is not weaker for being quiet:
// the tickets are real held-out records and the footer names the log they come
// from, the seed script records the provenance on every ticket's creation
// event, and the report carries the full account. An alert bar is for something
// a reader has to act on, and the one warning that survives as a banner is the
// one that meets that test - no risk artifact loaded, dispatch blocked.

import { Link, NavLink, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { SessionContext, useHealth, useSessionQuery, isOfflineDemo } from "./lib/session";
import { navigationForRole } from "./routes";
import { api } from "./lib/api";
import { Banner, Failure, Loading } from "./components/States";
import { Button } from "./components/Motion";
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
          <Route path="at-risk" element={<RiskRadar />} />
          <Route path="hardware" element={<Hardware />} />
          <Route path="methods/*" element={<Methods />} />
          <Route path="operations" element={<ManagerOnly><Administration /></ManagerOnly>} />
        </Routes>
      </Shell>
    </SessionContext.Provider>
  );
}

function Shell({ actor, health, children }) {
  const navigate = useNavigate();
  const navItems = actor ? navigationForRole(actor.role) : [];
  return (
    <div className="min-h-screen bg-paper">
      <a className="skip-link" href="#desk-content">Skip to main content</a>
      <header className="chrome-layer sticky top-0 z-40">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
          <div>
            <p className="font-display text-[18px] leading-tight text-ink">
              SLA Service Desk
            </p>
            <p className="text-xs text-muted">
              Local time: {DISPLAY_ZONE}
            </p>
          </div>
          {actor ? (
            <div className="flex items-center gap-3 text-sm">
              <span className="hidden text-muted sm:inline">
                {actor.username} <span aria-hidden="true">/</span> {actor.role}
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
        <div className="scroll-edge" aria-hidden="true" />
      </header>

      <div
        className={
          "mx-auto w-full px-4 py-5 sm:px-6 " +
          (actor
            ? "max-w-7xl lg:grid lg:grid-cols-[12rem_minmax(0,1fr)] lg:gap-10"
            : "max-w-6xl")
        }
      >
        {actor ? (
          <aside className="mb-5 lg:mb-0" aria-label="Primary navigation">
            <nav className="flex flex-wrap gap-1 border-b border-rule pb-3 lg:sticky lg:top-20 lg:flex-col lg:border-b-0 lg:border-r lg:pb-0 lg:pr-5" aria-label="Sections">
              {navItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    "rounded-[var(--radius-control)] px-3 py-2 text-sm font-medium transition-colors " +
                    (isActive
                      ? "bg-accent text-accent-ink"
                      : "text-ink-2 hover:bg-paper-2 hover:text-ink")
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
          </aside>
        ) : null}

        <main
          id="desk-content"
          className={
            "flex min-w-0 flex-col gap-5 " + (actor ? "" : "items-stretch")
          }
        >
          {health ? <BuildBanners health={health} /> : null}
          {children}
        </main>
      </div>

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
    <footer className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-4 gap-y-2 border-t border-rule px-4 py-5 text-xs text-muted sm:px-6">
      <span>Local sample: held-out UCI-498 incident records.</span>
      <Link className="underline hover:text-ink" to="/methods">
        Research appendix
      </Link>
    </footer>
  );
}

function ManagerOnly({ children }) {
  const session = useSessionQuery();
  if (session.data?.actor?.role !== "manager") return <Navigate to="/" replace />;
  return children;
}
