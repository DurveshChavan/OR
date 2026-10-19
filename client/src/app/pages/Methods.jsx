// Methods — the Operations Research work the rest of the product is built on.
//
// This is not an archive and it is not a second application. Two of the methods
// below are load-bearing in the live product: the assignment method is what
// picks a resolver on the Queue screen, and the replacement analysis is what the
// Hardware screen computes. The other six are the models around them - what
// funds a headcount, how work is distributed and sequenced, how an escalation
// is decided under uncertainty, and how a major incident is scheduled.
//
// Each one is a page a reader can put numbers into and check by hand. That is
// the point of the section: a recommendation whose arithmetic cannot be
// reproduced on paper is a number to be trusted rather than a number to be
// checked, and this product does not ask to be trusted.

import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api as engine } from "../../lib/api";
import { Banner, Loading } from "../components/States";
import { Section } from "../components/Bits";
import Overview from "../../pages/Overview";
import StaffingPlanner from "../../pages/StaffingPlanner";
import RegionalLoad from "../../pages/RegionalLoad";
import TicketAssignment from "../../pages/TicketAssignment";
import WorkQueue from "../../pages/WorkQueue";
import EscalationAdvisor from "../../pages/EscalationAdvisor";
import MajorIncident from "../../pages/MajorIncident";
import HardwareHealth from "../../pages/HardwareHealth";

//: Each entry names the technique and the syllabus unit, because that is what a
//: reader is checking it against.
const METHODS = [
  { to: "", label: "Overview", technique: "scenario", element: <Overview />, end: true },
  {
    to: "staffing",
    label: "Staffing",
    technique: "linear programming · Unit I",
    element: <StaffingPlanner />,
  },
  {
    to: "regional-load",
    label: "Regional load",
    technique: "transportation · Unit III",
    element: <RegionalLoad />,
  },
  {
    to: "assignment",
    label: "Assignment",
    technique: "Hungarian method · Unit III",
    element: <TicketAssignment />,
  },
  {
    to: "sequencing",
    label: "Sequencing",
    technique: "Johnson's rule · Unit III",
    element: <WorkQueue />,
  },
  {
    to: "escalation",
    label: "Escalation",
    technique: "decision & game theory · Unit II",
    element: <EscalationAdvisor />,
  },
  {
    to: "project",
    label: "Major incident",
    technique: "CPM / PERT · Unit IV",
    element: <MajorIncident />,
  },
  {
    to: "replacement",
    label: "Replacement",
    technique: "replacement analysis · Unit IV",
    element: <HardwareHealth />,
  },
];

export default function Methods() {
  return (
    <div className="flex flex-col gap-4">
      <header>
        <p className="text-sm text-muted">Research appendix</p>
        <h1 className="mt-0.5 font-display text-2xl text-ink">
          Operations Research methods
        </h1>
        <p className="mt-2 max-w-3xl text-sm text-ink-2">
          This build is the practical half of <em>AI-Driven SLA Optimization:
          Predictive Ticket Allocation, Escalation and Hardware Replacement in IT
          Service Desks</em>. Two of the methods below run in the product itself.
          The assignment method chooses the resolver the Queue suggests, and the
          replacement analysis computes the verdict the Hardware replacement
          screen shows. The rest are the models around them, kept because a
          recommendation whose arithmetic cannot be reproduced on paper is a
          number to be trusted rather than a number to be checked.
        </p>
      </header>

      <Section
        title="Worksheets"
        note="Every page takes numbers and shows its whole working. These are teaching evidence for the oral examination, not dispatcher controls, which is why they are not in the shell's navigation."
      >
        <nav className="flex flex-wrap gap-1.5" aria-label="Methods">
          {METHODS.map((method) => (
            <NavLink
              key={method.to || "overview"}
              to={`/methods${method.to ? `/${method.to}` : ""}`}
              end={method.end}
              className={({ isActive }) =>
                "rounded-[var(--radius-control)] border px-3 py-1.5 text-[13px] " +
                "transition-colors duration-150 " +
                (isActive
                  ? "border-accent bg-accent-soft text-ink"
                  : "border-rule-2 text-ink-2 hover:bg-paper-2")
              }
            >
              {method.label}
            </NavLink>
          ))}
        </nav>
        <EngineStatus />
      </Section>

      <Routes>
        {METHODS.map((method) => (
          <Route
            key={method.to || "index"}
            index={method.end || undefined}
            path={method.to || undefined}
            element={<MethodFrame method={method} />}
          />
        ))}
        <Route path="*" element={<Navigate to="/methods" replace />} />
      </Routes>
    </div>
  );
}

/** Whether the engine process is answering, said once instead of eight times.
 *
 *  These worksheets talk to a second FastAPI process, not to the service desk.
 *  When it is not running every page below fails on its own with a bare 500,
 *  which tells a reader that something broke but not that the thing which broke
 *  is a process nobody started. One probe, and the answer is a sentence with the
 *  command in it.
 */
function EngineStatus() {
  const health = useQuery({
    queryKey: ["engine", "health"],
    queryFn: engine.health,
    retry: false,
    staleTime: 15_000,
  });

  if (health.isLoading) {
    return <div className="mt-3"><Loading what="the Operations Research engine" /></div>;
  }
  if (health.error) {
    return (
      <div className="mt-3">
        <Banner tone="warning" title="The Operations Research engine is not answering.">
          <p>
            These worksheets read a second process, separate from the service
            desk. Start it and reload:
          </p>
          <pre className="mt-2 overflow-x-auto rounded bg-paper-2 p-2 font-mono text-xs text-ink-2">
uvicorn api.main:app --port 8000
          </pre>
          <p className="mt-2">
            Nothing in the Queue, At risk or Hardware replacement screens depends
            on it. Those read the service-desk API, which is answering.
          </p>
        </Banner>
      </div>
    );
  }
  return (
    <p className="mt-3 text-xs text-muted">
      Operations Research engine: answering on port 8000. Every worksheet below
      reads it directly.
    </p>
  );
}

function MethodFrame({ method }) {
  return (
    <div>
      <p className="mb-2 text-xs text-muted">
        {method.technique}
      </p>
      {method.element}
    </div>
  );
}
