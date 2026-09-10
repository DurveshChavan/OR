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
      <Section
        title="Methods"
        note="The arithmetic behind the product, each on its own page with its inputs exposed. Two of these run live: the assignment method chooses a resolver on the Queue screen, and the replacement analysis is what the Hardware screen computes."
      >
        <nav className="flex flex-wrap gap-1.5" aria-label="Methods">
          {METHODS.map((method) => (
            <NavLink
              key={method.to || "overview"}
              to={method.to}
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
        <p className="mt-3 text-xs text-muted">
          These pages read the Operations Research engine directly. They need its
          process running — <code>uvicorn api.main:app --port 8000</code> — and
          each page shows its own error state when it is not.
        </p>
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

function MethodFrame({ method }) {
  return (
    <div>
      <p className="mb-2 font-mono-label text-[10px] text-muted">
        {method.technique}
      </p>
      {method.element}
    </div>
  );
}
