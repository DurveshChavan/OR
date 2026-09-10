// The cutover lives here.
//
// Version 2 is now what `/` serves. The legacy Operations Research demo is not
// deleted, hidden or rewritten: it moved to `/legacy/*`, every one of its old
// paths still resolves through a redirect, and the switch is reversible with
// one environment variable until after the presentation:
//
//     VITE_DEFAULT_APP=legacy npm run dev     # `/` serves the OR demo again
//
// Each application keeps one canonical URL prefix rather than being reachable
// at two. A redirect at `/` is unambiguous about which one is the default;
// mounting both at the root would have left the address bar disagreeing with
// the nav about where the user is.

import { Navigate, Route, Routes } from "react-router-dom";
import TopNav from "./components/TopNav";
import CommandPalette from "./components/CommandPalette";
import Overview from "./pages/Overview";
import StaffingPlanner from "./pages/StaffingPlanner";
import RegionalLoad from "./pages/RegionalLoad";
import TicketAssignment from "./pages/TicketAssignment";
import WorkQueue from "./pages/WorkQueue";
import EscalationAdvisor from "./pages/EscalationAdvisor";
import MajorIncident from "./pages/MajorIncident";
import HardwareHealth from "./pages/HardwareHealth";
import { LEGACY_OLD_PATHS } from "./lib/routes";
import V2App from "./v2/V2App";

const DEFAULT_APP = import.meta.env.VITE_DEFAULT_APP || "v2";

export default function App() {
  return (
    <Routes>
      <Route path="/v2/*" element={<V2App />} />
      <Route path="/legacy/*" element={<LegacyApp />} />

      {/* A demo that was rehearsed against `/assignment` must not meet a blank
          page after the cutover. */}
      {LEGACY_OLD_PATHS.map((path) => (
        <Route
          key={path}
          path={path}
          element={<Navigate to={`/legacy${path === "/" ? "" : path}`} replace />}
        />
      ))}

      <Route
        path="/"
        element={
          <Navigate to={DEFAULT_APP === "legacy" ? "/legacy" : "/v2"} replace />
        }
      />
      <Route path="*" element={<Navigate to="/v2" replace />} />
    </Routes>
  );
}

function LegacyApp() {
  return (
    <div className="min-h-screen bg-paper">
      <TopNav />
      <CommandPalette />
      <main className="mx-auto max-w-6xl p-4 sm:p-6">
        {/* Relative paths: this whole tree hangs off `/legacy`. */}
        <Routes>
          <Route index element={<Overview />} />
          <Route path="staffing" element={<StaffingPlanner />} />
          <Route path="regional-load" element={<RegionalLoad />} />
          <Route path="assignment" element={<TicketAssignment />} />
          <Route path="work-queue" element={<WorkQueue />} />
          <Route path="escalations" element={<EscalationAdvisor />} />
          <Route path="incident" element={<MajorIncident />} />
          <Route path="hardware" element={<HardwareHealth />} />
        </Routes>
      </main>
    </div>
  );
}
